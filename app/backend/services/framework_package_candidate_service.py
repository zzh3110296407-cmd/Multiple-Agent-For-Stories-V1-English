import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.analyze_stories_import import (
    AnalyzeStoriesImportedArtifact,
    AnalyzeStoriesImportDetail,
)
from app.backend.models.framework_package_candidate import (
    FrameworkPackageCandidate,
    FrameworkPackageCandidateDetail,
    FrameworkPackageCandidateListResponse,
    FrameworkPackageCandidateResult,
    FrameworkPackageNormalizedDiff,
    FrameworkPackageNormalizationReport,
    FrameworkPackageSourceRef,
    FrameworkPackageValidationIssue,
)
from app.backend.services.analyze_stories_import_service import AnalyzeStoriesImportService
from app.backend.storage.json_store import JsonStore, StorageError


CANDIDATES_FILE = "framework_package_candidates.json"
REPORTS_FILE = "framework_package_normalization_reports.json"
SCHEMA_VERSION = "phase5_m2_framework_package_validation_v1"
LOCAL_PROJECT_ID = "local_project"

FIXED_MODULE_IDS = [
    "chapter_function",
    "reader_emotion",
    "character_desire",
    "character_arc",
    "conflict",
    "information_release",
    "style_pacing",
]
REPORT_LIKE_FIELDS = {
    "story_analysis_report",
    "analysis_summary",
    "report_sections",
    "report_title",
    "reasoning",
}
UNSAFE_NORMALIZED_KEYS = {
    "apikey",
    "authorization",
    "bearer",
    "rawprompt",
    "rawmodelprompt",
    "rawresponse",
    "rawmodelresponse",
    "hiddenreasoning",
    "internalreasoning",
    "chainofthought",
    "providersecret",
    "langsmithapikey",
    "secretkey",
    "fullprose",
    "prosetext",
    "revisedprosetext",
    "storytext",
    "chaptertext",
    "fullstorytext",
    "completestorytext",
}
UNSAFE_VALUE_MARKERS = [
    "RAW_PROMPT",
    "RAW_RESPONSE",
    "HIDDEN_REASONING",
    "INTERNAL_REASONING",
    "CHAIN_OF_THOUGHT",
    "chain-of-thought",
    "raw prompt",
    "raw response",
    "hidden reasoning",
]
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE),
]
MODULE_METADATA_KEYS = [
    "module_id",
    "label",
    "scope",
    "persistence",
    "owner",
    "write_policy",
    "order",
]
DOWNGRADED_SOURCES = {
    "system_default": "analyze_stories",
}
DOWNGRADED_WRITE_POLICIES = {
    "propose_state_change": "no_memory_write",
}
DOWNGRADED_PERSISTENCE = {
    "writes_story_fact": "candidate_only",
    "writes_character_state": "candidate_only",
}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FrameworkPackageCandidateService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        analyze_import_service: AnalyzeStoriesImportService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.analyze_import_service = analyze_import_service or AnalyzeStoriesImportService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.candidates_file = self.data_dir / CANDIDATES_FILE
        self.reports_file = self.data_dir / REPORTS_FILE

    def create_candidate_from_import(self, import_id: str) -> FrameworkPackageCandidateResult:
        detail = self.analyze_import_service.get_detail(import_id)
        self._require_import_ready_for_m2(detail)
        return self._build_and_store_candidate(import_id)

    def list_candidates(self) -> FrameworkPackageCandidateListResponse:
        candidates = [
            FrameworkPackageCandidate(**item)
            for item in self._read_list(self.candidates_file)
        ]
        candidates.sort(key=lambda item: item.created_at, reverse=True)
        return FrameworkPackageCandidateListResponse(candidates=candidates)

    def get_detail(self, candidate_id: str) -> FrameworkPackageCandidateDetail:
        candidate = self.get_candidate(candidate_id)
        report = self.get_normalization_report(candidate.normalization_report_id)
        return FrameworkPackageCandidateDetail(
            candidate=candidate,
            normalization_report=report,
        )

    def get_candidate(self, candidate_id: str) -> FrameworkPackageCandidate:
        for item in self._read_list(self.candidates_file):
            if item.get("candidate_id") == candidate_id:
                return FrameworkPackageCandidate(**item)
        raise StorageError(f"FRAMEWORK_PACKAGE_CANDIDATE_NOT_FOUND: {candidate_id}")

    def get_normalization_report(
        self,
        report_id_or_candidate_id: str,
    ) -> FrameworkPackageNormalizationReport:
        for item in self._read_list(self.reports_file):
            if item.get("normalization_report_id") == report_id_or_candidate_id:
                return FrameworkPackageNormalizationReport(**item)
            if item.get("candidate_id") == report_id_or_candidate_id:
                return FrameworkPackageNormalizationReport(**item)
        raise StorageError(f"FRAMEWORK_PACKAGE_NORMALIZATION_REPORT_NOT_FOUND: {report_id_or_candidate_id}")

    def revalidate_candidate(self, candidate_id: str) -> FrameworkPackageCandidateResult:
        existing = self.get_candidate(candidate_id)
        return self._build_and_store_candidate(
            existing.import_id,
            candidate_id=existing.candidate_id,
            created_at=existing.created_at,
        )

    def _build_and_store_candidate(
        self,
        import_id: str,
        *,
        candidate_id: str | None = None,
        created_at: str | None = None,
    ) -> FrameworkPackageCandidateResult:
        timestamp = now_iso()
        candidate_id = candidate_id or self._next_candidate_id()
        created_at = created_at or timestamp
        report_id = f"{candidate_id}_normalization_report"
        detail = self.analyze_import_service.get_detail(import_id)
        artifact = detail.artifacts[0] if detail.artifacts else None
        issues: list[FrameworkPackageValidationIssue] = []
        diffs: list[FrameworkPackageNormalizedDiff] = []
        normalized: dict[str, Any] | None = None
        detected_counts: dict[str, int] = {}
        payload_ref = artifact.payload_ref if artifact else None
        payload: dict[str, Any] | None = None

        if artifact is None:
            issues.append(self._issue("artifact_missing", "blocking", "Analyze Stories import has no artifact.", "$", None))
        else:
            issues.extend(self._m1_dependency_issues(detail, artifact))
            if not issues:
                try:
                    payload = self.analyze_import_service.read_artifact_payload(
                        import_id,
                        artifact.artifact_id,
                    )
                except StorageError:
                    issues.append(
                        self._issue(
                            "artifact_payload_unavailable",
                            "blocking",
                            "Safe framework package payload is unavailable for M2 normalization.",
                            "payload_ref",
                            artifact.artifact_id,
                            "Historical hash-only imports must be re-imported before M2.",
                        )
                    )
            if payload is not None:
                normalized, validation_issues, diffs, detected_counts = self._normalize_payload(
                    payload,
                    artifact,
                    detail,
                )
                issues.extend(validation_issues)

        blocking = [issue for issue in issues if issue.severity == "blocking"]
        warnings = [issue for issue in issues if issue.severity == "warning"]
        if blocking:
            normalized = None
        passed = not blocking
        can_proceed = passed and normalized is not None
        status = (
            "blocked"
            if blocking
            else "normalized_with_warnings"
            if warnings
            else "ready_for_workbench_review"
        )
        source_ref = self._source_ref(
            detail,
            artifact,
            payload_ref,
            timestamp,
        )
        report = FrameworkPackageNormalizationReport(
            normalization_report_id=report_id,
            candidate_id=candidate_id,
            import_id=import_id,
            artifact_id=artifact.artifact_id if artifact else "",
            passed=passed,
            can_proceed_to_m4_workbench=can_proceed,
            blocking_issues=blocking,
            warnings=warnings,
            normalized_diffs=diffs,
            detected_counts=detected_counts,
            requires_user_confirmation=True,
            safe_summary=self._safe_report_summary(
                passed,
                can_proceed,
                len(blocking),
                len(warnings),
                detected_counts,
            ),
            created_at=timestamp,
        )
        candidate = FrameworkPackageCandidate(
            candidate_id=candidate_id,
            import_id=import_id,
            artifact_id=artifact.artifact_id if artifact else "",
            project_id=LOCAL_PROJECT_ID,
            candidate_status=status,
            normalized_framework_package=normalized,
            normalization_report_id=report_id,
            source_ref=source_ref,
            artifact_sha256=artifact.content_sha256 if artifact else "",
            input_fingerprint_ids=[
                item.fingerprint_id for item in detail.input_fingerprints
            ],
            requires_user_confirmation=True,
            can_proceed_to_m4_workbench=can_proceed,
            created_at=created_at,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._replace_or_append(self.candidates_file, "candidate_id", candidate_id, model_to_dict(candidate))
        self._replace_or_append(self.reports_file, "normalization_report_id", report_id, model_to_dict(report))
        return FrameworkPackageCandidateResult(
            success=passed,
            candidate=candidate,
            normalization_report=report,
        )

    def _require_import_ready_for_m2(self, detail: AnalyzeStoriesImportDetail) -> None:
        artifact = detail.artifacts[0] if detail.artifacts else None
        report = detail.validation_report
        blockers: list[str] = []
        if artifact is None:
            blockers.append("artifact_missing")
        elif artifact.file_kind != "framework_package":
            blockers.append(f"file_kind={artifact.file_kind}")
        if detail.manifest.import_status != "ready_for_m2":
            blockers.append(f"import_status={detail.manifest.import_status}")
        if report is None:
            blockers.append("validation_report_missing")
        elif not report.can_proceed_to_m2:
            blockers.extend(report.next_step_blockers or [
                f"passed={report.passed}",
                f"can_proceed_to_m2={report.can_proceed_to_m2}",
            ])
        if blockers:
            unique_blockers = self._dedupe(blockers)
            raise StorageError(
                "FRAMEWORK_PACKAGE_IMPORT_NOT_READY_FOR_M2: "
                "Import passed basic validation but is not eligible for M2 normalization. "
                + "; ".join(unique_blockers)
            )

    def _m1_dependency_issues(
        self,
        detail: AnalyzeStoriesImportDetail,
        artifact: AnalyzeStoriesImportedArtifact,
    ) -> list[FrameworkPackageValidationIssue]:
        issues: list[FrameworkPackageValidationIssue] = []
        report = detail.validation_report
        if artifact.file_kind != "framework_package":
            issues.append(
                self._issue(
                    "not_framework_package",
                    "blocking",
                    "Only Analyze Stories framework_package imports can create framework candidates.",
                    "artifact.file_kind",
                    artifact.artifact_id,
                    f"file_kind={artifact.file_kind}",
                )
            )
        if artifact.parse_status != "parsed":
            issues.append(
                self._issue(
                    "artifact_not_parsed",
                    "blocking",
                    "Analyze Stories artifact was not parsed.",
                    "artifact.parse_status",
                    artifact.artifact_id,
                    f"parse_status={artifact.parse_status}",
                )
            )
        if report is None:
            issues.append(
                self._issue(
                    "m1_validation_report_missing",
                    "blocking",
                    "M1 validation report is missing.",
                    "validation_report",
                    artifact.artifact_id,
                )
            )
        elif not report.passed or not report.can_proceed_to_m2:
            issues.append(
                self._issue(
                    "m1_not_ready_for_m2",
                    "blocking",
                    "Import passed basic validation but is not eligible for M2 normalization.",
                    "validation_report.can_proceed_to_m2",
                    artifact.artifact_id,
                    "; ".join(report.next_step_blockers or [
                        f"passed={report.passed}",
                        f"can_proceed_to_m2={report.can_proceed_to_m2}",
                    ]),
                )
            )
        if artifact.raw_storage_status != "stored" or not artifact.payload_ref:
            issues.append(
                self._issue(
                    "artifact_payload_unavailable",
                    "blocking",
                    "Safe framework package payload is unavailable for M2 normalization.",
                    "artifact.payload_ref",
                    artifact.artifact_id,
                    f"raw_storage_status={artifact.raw_storage_status}",
                )
            )
        return issues

    def _normalize_payload(
        self,
        payload: dict[str, Any],
        artifact: AnalyzeStoriesImportedArtifact,
        detail: AnalyzeStoriesImportDetail,
    ) -> tuple[
        dict[str, Any],
        list[FrameworkPackageValidationIssue],
        list[FrameworkPackageNormalizedDiff],
        dict[str, int],
    ]:
        package = copy.deepcopy(payload)
        issues: list[FrameworkPackageValidationIssue] = []
        diffs: list[FrameworkPackageNormalizedDiff] = []
        diff_index = 1

        def add_diff(
            field_path: str,
            change_type: str,
            reason: str,
            before: Any = None,
            after: Any = None,
            severity: str = "info",
        ) -> None:
            nonlocal diff_index
            diffs.append(
                FrameworkPackageNormalizedDiff(
                    diff_id=f"diff_{diff_index:03d}",
                    field_path=field_path,
                    change_type=change_type,  # type: ignore[arg-type]
                    before_summary=self._summary(before),
                    after_summary=self._summary(after),
                    reason=reason,
                    severity=severity,  # type: ignore[arg-type]
                )
            )
            diff_index += 1

        issues.extend(self._safety_issues(package, artifact.artifact_id))
        for field in sorted(REPORT_LIKE_FIELDS):
            if field in package:
                add_diff(
                    field,
                    "moved_to_report_layer",
                    "Report-like field is excluded from normalized machine schema.",
                    before=package.get(field),
                    after=None,
                    severity="warning",
                )
                issues.append(
                    self._issue(
                        "report_like_field_excluded",
                        "warning",
                        "Report-like field was excluded from normalized machine schema.",
                        field,
                        artifact.artifact_id,
                    )
                )
                package.pop(field, None)

        source = self._first_str(package.get("source"))
        if not source:
            issues.append(
                self._issue(
                    "missing_source",
                    "warning",
                    "Package source is missing and was normalized to analyze_stories.",
                    "source",
                    artifact.artifact_id,
                )
            )
            add_diff("source", "defaulted", "Missing source defaulted to analyze_stories.", None, "analyze_stories", "warning")
        elif source != "analyze_stories":
            issues.append(
                self._issue(
                    "invalid_source",
                    "blocking",
                    "Framework package candidate source must be analyze_stories.",
                    "source",
                    artifact.artifact_id,
                    f"source={self._summary(source)}",
                )
            )

        normalized: dict[str, Any] = {
            "source": "analyze_stories",
            "version_id": SCHEMA_VERSION,
        }
        macro_framework = package.get("macro_framework")
        if not isinstance(macro_framework, dict):
            issues.append(self._issue("macro_framework_invalid", "blocking", "macro_framework must be an object.", "macro_framework", artifact.artifact_id))
            macro_framework = {}
        components_raw = macro_framework.get("components")
        if not isinstance(components_raw, list):
            issues.append(
                self._issue(
                    "macro_components_missing",
                    "blocking",
                    "macro_framework.components must be a list.",
                    "macro_framework.components",
                    artifact.artifact_id,
                )
            )
            components_raw = []
        normalized_components, component_ids = self._normalize_macro_components(
            components_raw,
            artifact.artifact_id,
            issues,
            add_diff,
        )
        constraint_strength = self._normalize_constraint_strength(
            macro_framework.get("constraint_strength", package.get("constraint_strength")),
            "macro_framework.constraint_strength",
            artifact.artifact_id,
            issues,
            add_diff,
        )
        normalized["macro_framework"] = {
            "framework_id": self._first_str(macro_framework.get("framework_id")) or "analyze_stories_framework_candidate",
            "label": self._first_str(macro_framework.get("label")) or "Analyze Stories Framework Candidate",
            "constraint_strength": constraint_strength,
            "components": normalized_components,
        }
        if not self._first_str(macro_framework.get("framework_id")):
            add_diff("macro_framework.framework_id", "defaulted", "Missing framework id defaulted for candidate only.", None, normalized["macro_framework"]["framework_id"], "warning")
        if not self._first_str(macro_framework.get("label")):
            add_diff("macro_framework.label", "defaulted", "Missing framework label defaulted for candidate only.", None, normalized["macro_framework"]["label"], "warning")

        vocabulary = package.get("component_vocabulary")
        if not isinstance(vocabulary, dict):
            issues.append(self._issue("component_vocabulary_invalid", "blocking", "component_vocabulary must be an object.", "component_vocabulary", artifact.artifact_id))
            vocabulary = {}
        chapter_modules_raw = vocabulary.get("chapter_modules")
        if not isinstance(chapter_modules_raw, list):
            issues.append(
                self._issue(
                    "chapter_modules_missing",
                    "blocking",
                    "component_vocabulary.chapter_modules must be a list.",
                    "component_vocabulary.chapter_modules",
                    artifact.artifact_id,
                )
            )
            chapter_modules_raw = []
        normalized_modules = self._normalize_chapter_modules(
            chapter_modules_raw,
            artifact.artifact_id,
            issues,
            add_diff,
        )
        missing_fixed_modules = sorted(set(FIXED_MODULE_IDS) - {item.get("module_id") for item in normalized_modules})
        if missing_fixed_modules:
            issues.append(
                self._issue(
                    "fixed_module_missing",
                    "warning",
                    "One or more fixed module ids are missing.",
                    "component_vocabulary.chapter_modules",
                    artifact.artifact_id,
                    "missing=" + ",".join(missing_fixed_modules),
                )
            )
        normalized["component_vocabulary"] = {
            "chapter_modules": normalized_modules,
        }

        assignments_raw = package.get("chapter_macro_assignments")
        if not isinstance(assignments_raw, list):
            issues.append(self._issue("chapter_macro_assignments_invalid", "blocking", "chapter_macro_assignments must be a list.", "chapter_macro_assignments", artifact.artifact_id))
            assignments_raw = []
        normalized["chapter_macro_assignments"] = self._normalize_assignments(
            assignments_raw,
            component_ids,
            artifact.artifact_id,
            issues,
            add_diff,
        )

        built_raw = package.get("built_chapter_frameworks")
        if not isinstance(built_raw, list):
            issues.append(self._issue("built_chapter_frameworks_invalid", "blocking", "built_chapter_frameworks must be a list.", "built_chapter_frameworks", artifact.artifact_id))
            built_raw = []
        fingerprint_chapters = {
            item.chapter_index
            for item in detail.input_fingerprints
            if item.chapter_index is not None
        }
        normalized["built_chapter_frameworks"] = self._normalize_built_chapter_frameworks(
            built_raw,
            component_ids,
            fingerprint_chapters,
            artifact.artifact_id,
            issues,
            add_diff,
        )

        blocking = [issue for issue in issues if issue.severity == "blocking"]
        detected_counts = {
            "macro_components": len(normalized_components),
            "chapter_modules": len(normalized_modules),
            "chapter_macro_assignments": len(normalized["chapter_macro_assignments"]),
            "built_chapter_frameworks": len(normalized["built_chapter_frameworks"]),
            "normalized_diffs": len(diffs),
            "blocking_issues": len(blocking),
            "warnings": len([issue for issue in issues if issue.severity == "warning"]),
        }
        return normalized, issues, diffs, detected_counts

    def _normalize_macro_components(
        self,
        raw_components: list[Any],
        artifact_id: str,
        issues: list[FrameworkPackageValidationIssue],
        add_diff: Any,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        normalized: list[dict[str, Any]] = []
        ids: set[str] = set()
        for index, item in enumerate(raw_components):
            path = f"macro_framework.components[{index}]"
            if not isinstance(item, dict):
                issues.append(self._issue("macro_component_invalid", "blocking", "Macro component must be an object.", path, artifact_id))
                continue
            component_id = self._first_str(item.get("component_id"))
            label = self._first_str(item.get("label"))
            order = self._safe_int(item.get("order"))
            if not component_id:
                issues.append(self._issue("macro_component_id_missing", "blocking", "Macro component id is missing.", f"{path}.component_id", artifact_id))
                continue
            if component_id in ids:
                issues.append(self._issue("duplicate_macro_component_id", "blocking", "Macro component id is duplicated.", f"{path}.component_id", artifact_id, f"component_id={component_id}"))
            ids.add(component_id)
            if not label:
                issues.append(self._issue("macro_component_label_missing", "warning", "Macro component label is missing.", f"{path}.label", artifact_id))
                label = component_id
                add_diff(f"{path}.label", "defaulted", "Missing macro component label defaulted to component id.", None, label, "warning")
            if order is None:
                issues.append(self._issue("macro_component_order_invalid", "blocking", "Macro component order must be sortable.", f"{path}.order", artifact_id))
                order = index + 1
            instruction = self._first_str(item.get("instruction"))
            if instruction is None:
                instruction = ""
                issues.append(self._issue("macro_component_instruction_missing", "warning", "Macro component instruction is missing.", f"{path}.instruction", artifact_id))
                add_diff(f"{path}.instruction", "defaulted", "Missing instruction defaulted to empty string.", None, "", "warning")
            normalized.append(
                {
                    "component_id": component_id,
                    "label": label,
                    "order": order,
                    "instruction": instruction,
                }
            )
        normalized.sort(key=lambda component: component.get("order", 0))
        return normalized, ids

    def _normalize_chapter_modules(
        self,
        raw_modules: list[Any],
        artifact_id: str,
        issues: list[FrameworkPackageValidationIssue],
        add_diff: Any,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(raw_modules):
            path = f"component_vocabulary.chapter_modules[{index}]"
            if not isinstance(item, dict):
                issues.append(self._issue("chapter_module_invalid", "blocking", "Chapter module must be an object.", path, artifact_id))
                continue
            module_id = self._first_str(item.get("module_id"))
            label = self._first_str(item.get("label"))
            if not module_id:
                issues.append(self._issue("chapter_module_id_missing", "blocking", "Chapter module id is missing.", f"{path}.module_id", artifact_id))
                continue
            if not label:
                issues.append(self._issue("chapter_module_label_missing", "warning", "Chapter module label is missing.", f"{path}.label", artifact_id))
                label = module_id
                add_diff(f"{path}.label", "defaulted", "Missing chapter module label defaulted to module id.", None, label, "warning")
            allowed = item.get("allowed_components")
            if not isinstance(allowed, list):
                issues.append(self._issue("allowed_components_invalid", "blocking", "allowed_components must be a list.", f"{path}.allowed_components", artifact_id))
                allowed = []
            normalized_allowed: list[dict[str, Any]] = []
            for allowed_index, allowed_item in enumerate(allowed):
                allowed_path = f"{path}.allowed_components[{allowed_index}]"
                if isinstance(allowed_item, str):
                    component_id = allowed_item
                    normalized_allowed.append({"component_id": component_id})
                    add_diff(allowed_path, "normalized", "String allowed component normalized to object.", allowed_item, {"component_id": component_id})
                elif isinstance(allowed_item, dict):
                    normalized_allowed.append(
                        self._normalize_candidate_component_metadata(
                            allowed_item,
                            allowed_path,
                            artifact_id,
                            issues,
                            add_diff,
                        )
                    )
                else:
                    issues.append(self._issue("allowed_component_invalid", "blocking", "Allowed component must be a string or object.", allowed_path, artifact_id))
                    continue
            normalized.append(
                {
                    "module_id": module_id,
                    "label": label,
                    "allowed_components": normalized_allowed,
                }
            )
        return normalized

    def _normalize_assignments(
        self,
        raw_assignments: list[Any],
        component_ids: set[str],
        artifact_id: str,
        issues: list[FrameworkPackageValidationIssue],
        add_diff: Any,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(raw_assignments):
            path = f"chapter_macro_assignments[{index}]"
            if not isinstance(item, dict):
                issues.append(self._issue("chapter_assignment_invalid", "blocking", "Chapter assignment must be an object.", path, artifact_id))
                continue
            chapter_index = self._safe_int(item.get("chapter_index"))
            if chapter_index is None:
                issues.append(self._issue("chapter_index_invalid", "blocking", "chapter_index must be an integer.", f"{path}.chapter_index", artifact_id))
                continue
            linked = item.get("linked_macro_component_ids")
            if not isinstance(linked, list):
                issues.append(self._issue("linked_macro_component_ids_invalid", "blocking", "linked_macro_component_ids must be a list.", f"{path}.linked_macro_component_ids", artifact_id))
                linked = []
            linked_ids = [str(component_id) for component_id in linked if str(component_id).strip()]
            for component_id in linked_ids:
                if component_id not in component_ids:
                    issues.append(self._issue("unknown_macro_ref", "blocking", "Chapter assignment references an unknown macro component.", f"{path}.linked_macro_component_ids", artifact_id, f"component_id={component_id}"))
            assignment_type = self._first_str(item.get("assignment_type"))
            if assignment_type != "analyze_stories_recommended":
                issues.append(self._issue("assignment_type_normalized", "warning", "Assignment type was normalized to analyze_stories_recommended.", f"{path}.assignment_type", artifact_id, f"before={self._summary(assignment_type)}"))
                add_diff(f"{path}.assignment_type", "normalized", "Analyze Stories candidates cannot preserve non-recommendation authority.", assignment_type, "analyze_stories_recommended", "warning")
            normalized.append(
                {
                    "chapter_index": chapter_index,
                    "linked_macro_component_ids": linked_ids,
                    "assignment_type": "analyze_stories_recommended",
                }
            )
        normalized.sort(key=lambda item: item["chapter_index"])
        return normalized

    def _normalize_built_chapter_frameworks(
        self,
        raw_frameworks: list[Any],
        component_ids: set[str],
        fingerprint_chapters: set[int],
        artifact_id: str,
        issues: list[FrameworkPackageValidationIssue],
        add_diff: Any,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(raw_frameworks):
            path = f"built_chapter_frameworks[{index}]"
            if not isinstance(item, dict):
                issues.append(self._issue("built_chapter_framework_invalid", "blocking", "Built chapter framework must be an object.", path, artifact_id))
                continue
            chapter_index = self._safe_int(item.get("chapter_index"))
            if chapter_index is None:
                issues.append(self._issue("built_chapter_index_missing", "blocking", "Built chapter framework chapter_index is missing.", f"{path}.chapter_index", artifact_id))
                continue
            modules = item.get("modules")
            if modules is None and "chapter_modules" in item:
                modules = item.get("chapter_modules")
                add_diff(f"{path}.chapter_modules", "renamed", "chapter_modules renamed to modules in normalized schema.", item.get("chapter_modules"), modules, "warning")
                issues.append(self._issue("built_chapter_modules_renamed", "warning", "built chapter chapter_modules was renamed to modules.", f"{path}.chapter_modules", artifact_id))
            if not isinstance(modules, list):
                issues.append(self._issue("built_chapter_modules_invalid", "blocking", "Built chapter framework modules must be a list.", f"{path}.modules", artifact_id))
                modules = []
            if chapter_index not in fingerprint_chapters:
                severity = "blocking" if modules else "warning"
                issues.append(
                    self._issue(
                        "unfingerprinted_future_built_chapter",
                        severity,  # type: ignore[arg-type]
                        "Built chapter framework is not backed by an M1 input fingerprint.",
                        f"{path}.chapter_index",
                        artifact_id,
                        f"chapter_index={chapter_index}",
                    )
                )
                add_diff(path, "blocked" if modules else "dropped", "Unfingerprinted future built chapter excluded from normalized schema.", item, None, severity)
                continue
            linked = item.get("linked_macro_component_ids")
            linked_ids = [str(component_id) for component_id in linked] if isinstance(linked, list) else []
            for component_id in linked_ids:
                if component_id not in component_ids:
                    issues.append(self._issue("unknown_macro_ref", "blocking", "Built chapter framework references an unknown macro component.", f"{path}.linked_macro_component_ids", artifact_id, f"component_id={component_id}"))
            normalized_modules: list[dict[str, Any]] = []
            for module_index, module in enumerate(modules):
                module_path = f"{path}.modules[{module_index}]"
                if not isinstance(module, dict):
                    issues.append(self._issue("built_chapter_module_invalid", "blocking", "Built chapter module must be an object.", module_path, artifact_id))
                    continue
                module_id = self._first_str(module.get("module_id"))
                if not module_id:
                    issues.append(self._issue("built_chapter_module_id_missing", "blocking", "Built chapter module_id is missing.", f"{module_path}.module_id", artifact_id))
                    continue
                normalized_module = {
                    key: copy.deepcopy(module[key])
                    for key in MODULE_METADATA_KEYS
                    if key in module
                }
                normalized_module["module_id"] = module_id
                self._downscope_candidate_metadata(
                    normalized_module,
                    module_path,
                    artifact_id,
                    issues,
                    add_diff,
                )
                components = module.get("components")
                legacy_component_id = self._first_str(module.get("component_id"))
                if components is None and legacy_component_id:
                    components = [{"component_id": legacy_component_id}]
                    add_diff(
                        f"{module_path}.component_id",
                        "normalized",
                        "Legacy built module component_id normalized to components[].",
                        legacy_component_id,
                        components,
                        "warning",
                    )
                    issues.append(
                        self._issue(
                            "built_module_component_id_normalized",
                            "warning",
                            "Built module scalar component_id was normalized to components[].",
                            f"{module_path}.component_id",
                            artifact_id,
                        )
                    )
                if components is None:
                    components = []
                if not isinstance(components, list):
                    issues.append(
                        self._issue(
                            "built_module_components_invalid",
                            "blocking",
                            "Built chapter module components must be a list.",
                            f"{module_path}.components",
                            artifact_id,
                        )
                    )
                    components = []
                normalized_module["components"] = self._normalize_module_components(
                    components,
                    module_path,
                    artifact_id,
                    issues,
                    add_diff,
                )
                normalized_modules.append(normalized_module)
            normalized.append(
                {
                    "chapter_index": chapter_index,
                    "linked_macro_component_ids": linked_ids,
                    "modules": normalized_modules,
                }
            )
        normalized.sort(key=lambda item: item["chapter_index"])
        return normalized

    def _normalize_module_components(
        self,
        components: list[Any],
        module_path: str,
        artifact_id: str,
        issues: list[FrameworkPackageValidationIssue],
        add_diff: Any,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for component_index, component in enumerate(components):
            component_path = f"{module_path}.components[{component_index}]"
            if isinstance(component, str):
                normalized.append({"component_id": component})
                add_diff(
                    component_path,
                    "normalized",
                    "String built module component normalized to object.",
                    component,
                    {"component_id": component},
                )
                continue
            if not isinstance(component, dict):
                issues.append(
                    self._issue(
                        "built_module_component_invalid",
                        "blocking",
                        "Built module component must be a string or object.",
                        component_path,
                        artifact_id,
                    )
                )
                continue
            normalized.append(
                self._normalize_candidate_component_metadata(
                    component,
                    component_path,
                    artifact_id,
                    issues,
                    add_diff,
                )
            )
        return normalized

    def _normalize_candidate_component_metadata(
        self,
        item: dict[str, Any],
        path: str,
        artifact_id: str,
        issues: list[FrameworkPackageValidationIssue],
        add_diff: Any,
    ) -> dict[str, Any]:
        normalized = copy.deepcopy(item)
        component_id = self._first_str(normalized.get("component_id"), normalized.get("id"))
        if component_id and normalized.get("component_id") != component_id:
            before = normalized.get("component_id")
            normalized["component_id"] = component_id
            add_diff(
                f"{path}.component_id",
                "normalized",
                "Component id normalized from component_id/id field.",
                before,
                component_id,
                "info",
            )
        self._downscope_candidate_metadata(
            normalized,
            path,
            artifact_id,
            issues,
            add_diff,
        )
        return normalized

    def _downscope_candidate_metadata(
        self,
        item: dict[str, Any],
        path: str,
        artifact_id: str,
        issues: list[FrameworkPackageValidationIssue],
        add_diff: Any,
    ) -> None:
        field_maps = {
            "source": DOWNGRADED_SOURCES,
            "write_policy": DOWNGRADED_WRITE_POLICIES,
            "persistence": DOWNGRADED_PERSISTENCE,
        }
        for field, mapping in field_maps.items():
            value = self._first_str(item.get(field))
            if value not in mapping:
                continue
            replacement = mapping[value]
            item[field] = replacement
            field_path = f"{path}.{field}"
            issues.append(
                self._issue(
                    "candidate_metadata_downscoped",
                    "warning",
                    "Candidate metadata with write authority semantics was downscoped for inactive review.",
                    field_path,
                    artifact_id,
                    f"{field}={value}",
                )
            )
            add_diff(
                field_path,
                "downscoped",
                "Analyze Stories candidate metadata was downscoped and remains inactive.",
                value,
                replacement,
                "warning",
            )

    def _normalize_constraint_strength(
        self,
        value: Any,
        field_path: str,
        artifact_id: str,
        issues: list[FrameworkPackageValidationIssue],
        add_diff: Any,
    ) -> str:
        normalized = self._first_str(value)
        if not normalized:
            issues.append(self._issue("constraint_strength_defaulted", "warning", "constraint_strength missing; defaulted to weak.", field_path, artifact_id))
            add_diff(field_path, "defaulted", "Missing constraint_strength defaulted to weak.", None, "weak", "warning")
            return "weak"
        normalized = normalized.lower()
        if normalized == "weak":
            return "weak"
        if normalized == "strong":
            issues.append(self._issue("constraint_strength_downgraded", "warning", "strong constraint was downgraded to weak.", field_path, artifact_id))
            add_diff(field_path, "downgraded", "Analyze Stories recommendations cannot create strong constraints.", "strong", "weak", "warning")
            return "weak"
        if normalized == "hard":
            issues.append(self._issue("hard_constraint_blocked", "blocking", "hard constraints from Analyze Stories are blocked by default.", field_path, artifact_id))
            add_diff(field_path, "blocked", "Analyze Stories recommendations cannot create hard constraints.", "hard", None, "blocking")
            return "weak"
        issues.append(self._issue("constraint_strength_defaulted", "warning", "Unknown constraint_strength defaulted to weak.", field_path, artifact_id, f"before={self._summary(normalized)}"))
        add_diff(field_path, "normalized", "Unknown constraint_strength normalized to weak.", normalized, "weak", "warning")
        return "weak"

    def _safety_issues(
        self,
        value: Any,
        artifact_id: str,
    ) -> list[FrameworkPackageValidationIssue]:
        issues: list[FrameworkPackageValidationIssue] = []

        def walk(node: Any, path: str, key_hint: str = "") -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    key_text = str(key)
                    normalized = self._normalize_key(key_text)
                    child_path = f"{path}.{key_text}" if path else key_text
                    if normalized in UNSAFE_NORMALIZED_KEYS:
                        issues.append(self._issue("unsafe_field_name", "blocking", "Unsafe raw or secret-like field is not allowed.", self._redacted_path(child_path), artifact_id))
                    walk(child, child_path, normalized)
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    walk(child, f"{path}[{index}]", key_hint)
            elif isinstance(node, str):
                if any(pattern.search(node) for pattern in SECRET_PATTERNS):
                    issues.append(self._issue("unsafe_secret_value", "blocking", "Secret-like value is not allowed.", self._redacted_path(path), artifact_id))
                elif any(marker in node for marker in UNSAFE_VALUE_MARKERS):
                    issues.append(self._issue("unsafe_marker_value", "blocking", "Unsafe raw marker value is not allowed.", self._redacted_path(path), artifact_id))
                elif key_hint in UNSAFE_NORMALIZED_KEYS and len(node.strip()) > 80:
                    issues.append(self._issue("unsafe_full_prose_value", "blocking", "Full prose or raw text value is not allowed.", self._redacted_path(path), artifact_id))

        walk(value, "$")
        deduped: dict[tuple[str, str | None], FrameworkPackageValidationIssue] = {}
        for issue in issues:
            deduped[(issue.code, issue.field_path)] = issue
        return list(deduped.values())

    def _source_ref(
        self,
        detail: AnalyzeStoriesImportDetail,
        artifact: AnalyzeStoriesImportedArtifact | None,
        payload_ref: str | None,
        created_at: str,
    ) -> FrameworkPackageSourceRef:
        return FrameworkPackageSourceRef(
            source_ref_id=f"{detail.manifest.import_id}_framework_source_ref",
            import_id=detail.manifest.import_id,
            artifact_id=artifact.artifact_id if artifact else "",
            artifact_sha256=artifact.content_sha256 if artifact else "",
            payload_ref=payload_ref,
            source_manifest_id=detail.manifest.import_id,
            source_validation_report_id=detail.manifest.validation_report_id,
            verification_scope=detail.validation_report.verification_scope if detail.validation_report else None,
            created_at=created_at,
        )

    def _safe_report_summary(
        self,
        passed: bool,
        can_proceed: bool,
        blocking_count: int,
        warning_count: int,
        detected_counts: dict[str, int],
    ) -> str:
        return (
            "Framework package candidate normalization "
            f"passed={passed}; can_proceed_to_m4_workbench={can_proceed}; "
            f"blocking={blocking_count}; warnings={warning_count}; "
            f"macro_components={detected_counts.get('macro_components', 0)}; "
            f"chapter_modules={detected_counts.get('chapter_modules', 0)}."
        )

    def _issue(
        self,
        code: str,
        severity: str,
        message: str,
        field_path: str | None,
        artifact_id: str | None,
        safe_detail: str | None = None,
    ) -> FrameworkPackageValidationIssue:
        return FrameworkPackageValidationIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            field_path=field_path,
            artifact_id=artifact_id,
            safe_detail=self._summary(safe_detail) if safe_detail else None,
        )

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        data = self.store.read_list(path)
        return [item for item in data if isinstance(item, dict)]

    def _replace_or_append(
        self,
        path: Path,
        id_field: str,
        id_value: str,
        item: dict[str, Any],
    ) -> None:
        items = self._read_list(path)
        replaced = False
        for index, existing in enumerate(items):
            if existing.get(id_field) == id_value:
                items[index] = item
                replaced = True
                break
        if not replaced:
            items.append(item)
        self.store.write(path, items)

    def _next_candidate_id(self) -> str:
        return f"framework_candidate_{len(self._read_list(self.candidates_file)) + 1:03d}"

    def _first_str(self, *values: Any) -> str | None:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if value is not None and not isinstance(value, (dict, list)):
                return str(value).strip()
        return None

    def _safe_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    def _summary(self, value: Any, limit: int = 160) -> str | None:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            text = str(value)
        text = " ".join(text.split())
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            return "[redacted]"
        for marker in UNSAFE_VALUE_MARKERS:
            if marker in text:
                return "[redacted]"
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _normalize_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    def _redacted_path(self, path: str) -> str:
        if any(
            self._normalize_key(part) in UNSAFE_NORMALIZED_KEYS
            for part in re.split(r"[.\[\]]+", path)
            if part
        ):
            return "$.[redacted_unsafe_field]"
        return path
