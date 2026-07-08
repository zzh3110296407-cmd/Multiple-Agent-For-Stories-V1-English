import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.analyze_stories_import import (
    AnalyzeStoriesFileKind,
    AnalyzeStoriesImportedArtifact,
    AnalyzeStoriesImportDetail,
    AnalyzeStoriesImportIssue,
    AnalyzeStoriesImportListResponse,
    AnalyzeStoriesImportManifest,
    AnalyzeStoriesImportResult,
    AnalyzeStoriesImportValidationReport,
    AnalyzeStoriesInputFingerprint,
    StoryAnalysisReportRef,
)
from app.backend.storage.json_store import JsonStore, StorageError


IMPORTS_FILE = "analyze_stories_imports.json"
ARTIFACTS_FILE = "analyze_stories_imported_artifacts.json"
FINGERPRINTS_FILE = "analyze_stories_input_fingerprints.json"
REPORTS_FILE = "analyze_stories_import_validation_reports.json"
REPORT_REFS_FILE = "story_analysis_report_refs.json"
SCHEMA_VERSION = "phase5_m1_analyze_stories_import_gate_v1"
LOCAL_PROJECT_ID = "local_project"

FILE_KINDS = {
    "framework_package",
    "story_analysis_report",
    "full_book_bundle",
    "cross_chapter_state_package",
    "unknown",
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
}
UNSAFE_TEXT_FIELD_KEYS = {
    "fullprose",
    "prosetext",
    "revisedprosetext",
    "storytext",
    "chaptertext",
    "fullstorytext",
    "completestorytext",
    "rawstoryinput",
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
FINGERPRINT_REQUIRED_FIELDS = [
    "input_filename",
    "chapter_index",
    "input_title",
    "input_content_sha256",
    "text_length",
    "analyzer_version",
    "workflow_version",
    "model",
    "processed_at",
]


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class AnalyzeStoriesImportService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.imports_file = self.data_dir / IMPORTS_FILE
        self.artifacts_file = self.data_dir / ARTIFACTS_FILE
        self.fingerprints_file = self.data_dir / FINGERPRINTS_FILE
        self.reports_file = self.data_dir / REPORTS_FILE
        self.report_refs_file = self.data_dir / REPORT_REFS_FILE

    def import_json(
        self,
        payload: dict[str, Any],
        declared_file_kind: str | None = None,
        original_filename: str | None = None,
        *,
        verification_scope: str = "user_upload",
    ) -> AnalyzeStoriesImportResult:
        import_id = self._next_import_id()
        artifact_id = f"{import_id}_artifact_001"
        timestamp = now_iso()
        content_bytes = stable_json_bytes(payload)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        metadata = self._metadata(payload)
        safety_issues = self._scan_safety(payload)
        detected_kind = self._detect_file_kind(payload)
        artifact_kind = self._resolve_artifact_kind(
            detected_kind,
            declared_file_kind,
            safety_issues,
            artifact_id,
        )
        top_level_keys = self._safe_top_level_keys(payload)
        safety_blocked = any(i.severity == "blocking" for i in safety_issues)
        payload_ref = (
            self._write_safe_payload(
                import_id=import_id,
                artifact_id=artifact_id,
                payload=payload,
            )
            if not safety_blocked
            and artifact_kind
            in {
                "framework_package",
                "story_analysis_report",
                "full_book_bundle",
                "cross_chapter_state_package",
            }
            else None
        )
        raw_storage_status = "blocked" if safety_blocked else "stored" if payload_ref else "hash_only"
        storage_ref = self._write_artifact_metadata(
            import_id=import_id,
            artifact_id=artifact_id,
            content_sha256=content_hash,
            file_kind=artifact_kind,
            top_level_keys=top_level_keys,
            raw_storage_status=raw_storage_status,
            safe_summary=self._artifact_summary(artifact_kind, top_level_keys, content_hash),
            payload_ref=payload_ref,
        )
        artifact = AnalyzeStoriesImportedArtifact(
            artifact_id=artifact_id,
            import_id=import_id,
            file_kind=artifact_kind,
            original_filename=original_filename,
            content_sha256=content_hash,
            content_length=len(content_bytes),
            storage_ref=storage_ref,
            payload_ref=payload_ref,
            raw_storage_status=raw_storage_status,
            parse_status="parsed",
            top_level_keys=top_level_keys,
            safe_summary=self._artifact_summary(artifact_kind, top_level_keys, content_hash),
            safe_error="Unsafe artifact markers detected." if raw_storage_status == "blocked" else None,
            created_at=timestamp,
        )
        fingerprints = self._extract_fingerprints(
            payload=payload,
            import_id=import_id,
            artifact_id=artifact_id,
            metadata=metadata,
            created_at=timestamp,
        )
        report_refs = self._build_report_refs(
            payload=payload,
            import_id=import_id,
            artifact=artifact,
            blocked=raw_storage_status == "blocked",
            created_at=timestamp,
        )
        issues = list(safety_issues)
        issues.extend(self._source_issues(payload, artifact_id))
        issues.extend(
            self._declared_kind_issues(declared_file_kind, detected_kind, artifact_id)
        )
        missing_recommended = self._missing_recommended_fields(payload, artifact_kind)
        issues.extend(
            self._recommended_field_issues(
                missing_recommended,
                artifact_id,
                artifact_kind,
            )
        )
        issues.extend(self._fingerprint_issues(fingerprints, artifact_id))
        issues.extend(self._analyzer_status_issues(payload, artifact_id))
        issues.extend(self._bundle_shallow_warnings(payload, artifact_id, artifact_kind))
        issues.extend(self._story_report_issues(artifact_kind, report_refs, artifact_id))
        if artifact_kind == "unknown":
            issues.append(
                AnalyzeStoriesImportIssue(
                    code="unknown_file_kind",
                    severity="blocking",
                    message="Analyze Stories artifact file kind could not be identified.",
                    artifact_id=artifact_id,
                    field_path="$",
                    safe_detail="Supported kinds: framework package, report, bundle, or cross-chapter state.",
                )
            )
        blocking = [issue for issue in issues if issue.severity == "blocking"]
        warnings = [issue for issue in issues if issue.severity == "warning"]
        passed = not blocking
        can_proceed_to_m2 = (
            passed
            and artifact_kind == "framework_package"
            and self._source_value(payload) == "analyze_stories"
            and not warnings
            and not missing_recommended
            and bool(fingerprints)
            and all(item.completeness_status == "complete" for item in fingerprints)
        )
        next_step_blockers = self._next_step_blockers(
            passed=passed,
            artifact_kind=artifact_kind,
            source_value=self._source_value(payload),
            warnings=warnings,
            missing_recommended=missing_recommended,
            fingerprints=fingerprints,
        )
        report = AnalyzeStoriesImportValidationReport(
            report_id=f"{import_id}_validation_report",
            import_id=import_id,
            passed=passed,
            can_proceed_to_m2=can_proceed_to_m2,
            passed_basic=passed,
            ready_for_next_step=can_proceed_to_m2,
            next_step_blockers=next_step_blockers,
            blocking_issues=blocking,
            warnings=warnings,
            detected_file_kinds=[artifact_kind],
            missing_recommended_fields=missing_recommended,
            requires_user_confirmation=True,
            verification_scope=verification_scope if verification_scope in {"fixture_based", "real_sample", "user_upload"} else "user_upload",
            safe_summary=self._validation_summary(
                artifact_kind,
                passed,
                can_proceed_to_m2,
                len(blocking),
                len(warnings),
            ),
            created_at=timestamp,
        )
        manifest = AnalyzeStoriesImportManifest(
            import_id=import_id,
            project_id=LOCAL_PROJECT_ID,
            source="analyze_stories",
            import_status=self._manifest_status(passed, can_proceed_to_m2, warnings),
            parse_status=artifact.parse_status,
            file_kinds=[artifact_kind],
            artifact_ids=[artifact.artifact_id],
            validation_report_id=report.report_id,
            input_fingerprint_ids=[item.fingerprint_id for item in fingerprints],
            story_analysis_report_ref_ids=[
                item.story_analysis_report_ref_id for item in report_refs
            ],
            analyzer_version=metadata.get("analyzer_version"),
            workflow_version=metadata.get("workflow_version"),
            model=metadata.get("model"),
            received_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._append(self.imports_file, model_to_dict(manifest))
        self._append(self.artifacts_file, model_to_dict(artifact))
        for fingerprint in fingerprints:
            self._append(self.fingerprints_file, model_to_dict(fingerprint))
        self._append(self.reports_file, model_to_dict(report))
        for ref in report_refs:
            self._append(self.report_refs_file, model_to_dict(ref))
        return AnalyzeStoriesImportResult(
            success=passed,
            import_id=import_id,
            manifest=manifest,
            artifact=artifact,
            artifacts=[artifact],
            input_fingerprints=fingerprints,
            story_analysis_report_refs=report_refs,
            validation_report=report,
        )

    def import_parse_failure(
        self,
        raw_body: bytes,
        *,
        original_filename: str | None = None,
        verification_scope: str = "user_upload",
    ) -> AnalyzeStoriesImportResult:
        import_id = self._next_import_id()
        artifact_id = f"{import_id}_artifact_001"
        timestamp = now_iso()
        content_hash = hashlib.sha256(raw_body).hexdigest()
        artifact = AnalyzeStoriesImportedArtifact(
            artifact_id=artifact_id,
            import_id=import_id,
            file_kind="unknown",
            original_filename=original_filename,
            content_sha256=content_hash,
            content_length=len(raw_body),
            storage_ref=self._write_artifact_metadata(
                import_id=import_id,
                artifact_id=artifact_id,
                content_sha256=content_hash,
                file_kind="unknown",
                top_level_keys=[],
                raw_storage_status="blocked",
                safe_summary="Invalid JSON artifact was blocked and stored as hash-only metadata.",
            ),
            raw_storage_status="blocked",
            parse_status="parse_failed",
            top_level_keys=[],
            safe_summary="Invalid JSON artifact was blocked and stored as hash-only metadata.",
            safe_error="JSON parse failed.",
            created_at=timestamp,
        )
        issue = AnalyzeStoriesImportIssue(
            code="invalid_json",
            severity="blocking",
            message="Request body is not valid JSON.",
            artifact_id=artifact_id,
            field_path="$",
            safe_detail="Raw body was not stored.",
        )
        report = AnalyzeStoriesImportValidationReport(
            report_id=f"{import_id}_validation_report",
            import_id=import_id,
            passed=False,
            can_proceed_to_m2=False,
            passed_basic=False,
            ready_for_next_step=False,
            next_step_blockers=["parse_failed"],
            blocking_issues=[issue],
            warnings=[],
            detected_file_kinds=["unknown"],
            missing_recommended_fields=[],
            requires_user_confirmation=True,
            verification_scope=verification_scope if verification_scope in {"fixture_based", "real_sample", "user_upload"} else "user_upload",
            safe_summary="Invalid JSON import was blocked before parsing.",
            created_at=timestamp,
        )
        manifest = AnalyzeStoriesImportManifest(
            import_id=import_id,
            source="analyze_stories",
            import_status="blocked",
            parse_status=artifact.parse_status,
            file_kinds=["unknown"],
            artifact_ids=[artifact_id],
            validation_report_id=report.report_id,
            input_fingerprint_ids=[],
            story_analysis_report_ref_ids=[],
            analyzer_version=None,
            workflow_version=None,
            model=None,
            received_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._append(self.imports_file, model_to_dict(manifest))
        self._append(self.artifacts_file, model_to_dict(artifact))
        self._append(self.reports_file, model_to_dict(report))
        return AnalyzeStoriesImportResult(
            success=False,
            import_id=import_id,
            manifest=manifest,
            artifact=artifact,
            artifacts=[artifact],
            input_fingerprints=[],
            story_analysis_report_refs=[],
            validation_report=report,
        )

    def list_imports(self) -> AnalyzeStoriesImportListResponse:
        manifests = [
            AnalyzeStoriesImportManifest(**item)
            for item in self._read_list(self.imports_file)
        ]
        manifests.sort(key=lambda item: item.created_at, reverse=True)
        return AnalyzeStoriesImportListResponse(imports=manifests)

    def get_detail(self, import_id: str) -> AnalyzeStoriesImportDetail:
        manifest = self.get_manifest(import_id)
        artifacts = [
            AnalyzeStoriesImportedArtifact(**item)
            for item in self._read_list(self.artifacts_file)
            if item.get("import_id") == import_id
        ]
        fingerprints = [
            AnalyzeStoriesInputFingerprint(**item)
            for item in self._read_list(self.fingerprints_file)
            if item.get("import_id") == import_id
        ]
        refs = [
            StoryAnalysisReportRef(**item)
            for item in self._read_list(self.report_refs_file)
            if item.get("import_id") == import_id
        ]
        report = self.get_validation_report(import_id)
        return AnalyzeStoriesImportDetail(
            manifest=manifest,
            artifacts=artifacts,
            input_fingerprints=fingerprints,
            story_analysis_report_refs=refs,
            validation_report=report,
        )

    def get_manifest(self, import_id: str) -> AnalyzeStoriesImportManifest:
        for item in self._read_list(self.imports_file):
            if item.get("import_id") == import_id:
                return AnalyzeStoriesImportManifest(**item)
        raise StorageError(f"ANALYZE_STORIES_IMPORT_NOT_FOUND: {import_id}")

    def get_validation_report(
        self,
        import_id: str,
    ) -> AnalyzeStoriesImportValidationReport:
        for item in self._read_list(self.reports_file):
            if item.get("import_id") == import_id:
                return AnalyzeStoriesImportValidationReport(**item)
        raise StorageError(f"ANALYZE_STORIES_VALIDATION_REPORT_NOT_FOUND: {import_id}")

    def revalidate(self, import_id: str) -> AnalyzeStoriesImportResult:
        detail = self.get_detail(import_id)
        if detail.validation_report is None:
            raise StorageError(f"ANALYZE_STORIES_VALIDATION_REPORT_NOT_FOUND: {import_id}")
        return AnalyzeStoriesImportResult(
            success=detail.validation_report.passed,
            import_id=import_id,
            manifest=detail.manifest,
            artifact=detail.artifacts[0] if detail.artifacts else None,
            artifacts=detail.artifacts,
            input_fingerprints=detail.input_fingerprints,
            story_analysis_report_refs=detail.story_analysis_report_refs,
            validation_report=detail.validation_report,
        )

    def read_artifact_payload(self, import_id: str, artifact_id: str) -> dict[str, Any]:
        detail = self.get_detail(import_id)
        artifact = next(
            (item for item in detail.artifacts if item.artifact_id == artifact_id),
            None,
        )
        if artifact is None:
            raise StorageError(f"ANALYZE_STORIES_ARTIFACT_NOT_FOUND: {artifact_id}")
        payload_ref = artifact.payload_ref
        if not payload_ref and artifact.storage_ref:
            metadata_path = self._resolve_storage_ref(artifact.storage_ref)
            if self.store.exists(metadata_path):
                metadata = self.store.read(metadata_path)
                payload_ref = self._first_str(metadata.get("payload_ref"))
        if not payload_ref:
            raise StorageError(f"ANALYZE_STORIES_ARTIFACT_PAYLOAD_UNAVAILABLE: {artifact_id}")
        payload_path = self._resolve_storage_ref(payload_ref)
        payload = self.store.read(payload_path)
        if not isinstance(payload, dict):
            raise StorageError(f"ANALYZE_STORIES_ARTIFACT_PAYLOAD_INVALID: {artifact_id}")
        return payload

    def _detect_file_kind(self, payload: dict[str, Any]) -> AnalyzeStoriesFileKind:
        if any(key in payload for key in ["full_book_bundle", "book_framework", "arcs"]):
            return "full_book_bundle"
        chapters = payload.get("chapters")
        if isinstance(chapters, list) and (
            "book_title" in payload
            or "book_framework" in payload
            or any(isinstance(item, dict) and "chapter_framework" in item for item in chapters)
        ):
            return "full_book_bundle"
        if any(key in payload for key in ["cross_chapter_state", "chapter_states"]):
            return "cross_chapter_state_package"
        if all(
            key in payload
            for key in ["macro_framework", "component_vocabulary", "chapter_macro_assignments"]
        ):
            return "framework_package"
        if any(
            key in payload
            for key in [
                "story_analysis_report",
                "report_sections",
                "analysis_summary",
                "report_title",
            ]
        ):
            return "story_analysis_report"
        if "title" in payload and "summary" in payload and "sections" in payload:
            return "story_analysis_report"
        return "unknown"

    def _resolve_artifact_kind(
        self,
        detected_kind: str,
        declared_file_kind: str | None,
        issues: list[AnalyzeStoriesImportIssue],
        artifact_id: str,
    ) -> AnalyzeStoriesFileKind:
        if any(issue.severity == "blocking" for issue in issues):
            return detected_kind if detected_kind in FILE_KINDS else "unknown"
        if detected_kind != "unknown":
            return detected_kind  # type: ignore[return-value]
        if declared_file_kind in FILE_KINDS:
            return declared_file_kind  # type: ignore[return-value]
        return "unknown"

    def _metadata(self, payload: dict[str, Any]) -> dict[str, str | None]:
        run_manifest = self._dict_at(payload, "run_manifest")
        metadata = self._dict_at(payload, "metadata")
        return {
            "analyzer_version": self._first_str(
                payload.get("analyzer_version"),
                run_manifest.get("analyzer_version"),
                metadata.get("analyzer_version"),
            ),
            "workflow_version": self._first_str(
                payload.get("workflow_version"),
                run_manifest.get("workflow_version"),
                metadata.get("workflow_version"),
            ),
            "model": self._first_str(
                payload.get("model"),
                run_manifest.get("model"),
                metadata.get("model"),
            ),
            "processed_at": self._first_str(
                payload.get("processed_at"),
                run_manifest.get("processed_at"),
                metadata.get("processed_at"),
            ),
        }

    def _extract_fingerprints(
        self,
        *,
        payload: dict[str, Any],
        import_id: str,
        artifact_id: str,
        metadata: dict[str, str | None],
        created_at: str,
    ) -> list[AnalyzeStoriesInputFingerprint]:
        candidates: list[dict[str, Any]] = []
        for key in ["input_fingerprints", "input_fingerprint"]:
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                candidates.append(value)
        run_manifest = self._dict_at(payload, "run_manifest")
        for key in ["input_fingerprints", "input_fingerprint"]:
            value = run_manifest.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                candidates.append(value)
        chapters = payload.get("chapters")
        if isinstance(chapters, list):
            for chapter in chapters:
                if not isinstance(chapter, dict):
                    continue
                fingerprint = chapter.get("input_fingerprint")
                if isinstance(fingerprint, dict):
                    chapter_candidate = dict(fingerprint)
                    chapter_candidate.setdefault("chapter_index", chapter.get("chapter_index") or chapter.get("index"))
                    chapter_candidate.setdefault("input_title", chapter.get("title"))
                    candidates.append(chapter_candidate)
        fingerprints: list[AnalyzeStoriesInputFingerprint] = []
        for index, candidate in enumerate(candidates, start=1):
            normalized = self._normalize_fingerprint(candidate, metadata)
            missing = [
                field for field in FINGERPRINT_REQUIRED_FIELDS
                if self._is_missing_value(normalized.get(field))
            ]
            status = "complete" if not missing else "partial"
            fingerprints.append(
                AnalyzeStoriesInputFingerprint(
                    fingerprint_id=f"{import_id}_fingerprint_{index:03d}",
                    import_id=import_id,
                    artifact_id=artifact_id,
                    input_filename=normalized.get("input_filename"),
                    chapter_index=normalized.get("chapter_index"),
                    input_title=normalized.get("input_title"),
                    input_content_sha256=normalized.get("input_content_sha256"),
                    text_length=normalized.get("text_length"),
                    analyzer_version=normalized.get("analyzer_version"),
                    workflow_version=normalized.get("workflow_version"),
                    model=normalized.get("model"),
                    processed_at=normalized.get("processed_at"),
                    completeness_status=status,
                    missing_fields=missing,
                    created_at=created_at,
                )
            )
        return fingerprints

    def _normalize_fingerprint(
        self,
        candidate: dict[str, Any],
        metadata: dict[str, str | None],
    ) -> dict[str, Any]:
        input_hash = self._first_str(
            candidate.get("input_content_sha256"),
            candidate.get("content_sha256"),
            candidate.get("input_sha256"),
            candidate.get("source_content_sha256"),
        )
        return {
            "input_filename": self._first_str(
                candidate.get("input_filename"),
                candidate.get("filename"),
                candidate.get("source_filename"),
            ),
            "chapter_index": self._safe_int(candidate.get("chapter_index") or candidate.get("index")),
            "input_title": self._first_str(
                candidate.get("input_title"),
                candidate.get("title"),
                candidate.get("chapter_title"),
            ),
            "input_content_sha256": input_hash,
            "text_length": self._safe_int(candidate.get("text_length") or candidate.get("input_text_length")),
            "analyzer_version": self._first_str(candidate.get("analyzer_version"), metadata.get("analyzer_version")),
            "workflow_version": self._first_str(candidate.get("workflow_version"), metadata.get("workflow_version")),
            "model": self._first_str(candidate.get("model"), metadata.get("model")),
            "processed_at": self._first_str(candidate.get("processed_at"), metadata.get("processed_at")),
        }

    def _build_report_refs(
        self,
        *,
        payload: dict[str, Any],
        import_id: str,
        artifact: AnalyzeStoriesImportedArtifact,
        blocked: bool,
        created_at: str,
    ) -> list[StoryAnalysisReportRef]:
        if artifact.file_kind != "story_analysis_report":
            return []
        title = self._first_str(
            payload.get("report_title"),
            payload.get("title"),
            self._dict_at(payload, "story_analysis_report").get("title"),
        )
        summary = self._first_str(
            payload.get("analysis_summary"),
            payload.get("summary"),
            self._dict_at(payload, "story_analysis_report").get("summary"),
        )
        sections = payload.get("report_sections") or payload.get("sections")
        viewer_status = "blocked" if blocked else "available"
        if not blocked and not any([title, summary, isinstance(sections, list)]):
            viewer_status = "invalid"
        return [
            StoryAnalysisReportRef(
                story_analysis_report_ref_id=f"{import_id}_story_report_ref_001",
                import_id=import_id,
                artifact_id=artifact.artifact_id,
                linked_framework_package_id=self._first_str(
                    payload.get("linked_framework_package_id"),
                    payload.get("framework_package_id"),
                ),
                viewer_status=viewer_status,
                review_status="not_reviewed",
                safe_title=self._short(title or "Analyze Stories report"),
                safe_summary=self._short(summary or "Report metadata imported as an inactive recommendation."),
                created_at=created_at,
            )
        ]

    def _source_issues(
        self,
        payload: dict[str, Any],
        artifact_id: str,
    ) -> list[AnalyzeStoriesImportIssue]:
        source = self._source_value(payload)
        if not source:
            return [
                AnalyzeStoriesImportIssue(
                    code="missing_source",
                    severity="warning",
                    message="Analyze Stories source marker is missing.",
                    artifact_id=artifact_id,
                    field_path="source",
                    safe_detail="Import remains inactive and cannot proceed to M2 by default.",
                )
            ]
        if source != "analyze_stories":
            return [
                AnalyzeStoriesImportIssue(
                    code="invalid_source",
                    severity="blocking",
                    message="Import source is not analyze_stories.",
                    artifact_id=artifact_id,
                    field_path="source",
                    safe_detail=f"source={self._short(source, 40)}",
                )
            ]
        return []

    def _declared_kind_issues(
        self,
        declared_file_kind: str | None,
        detected_kind: str,
        artifact_id: str,
    ) -> list[AnalyzeStoriesImportIssue]:
        if not declared_file_kind:
            return []
        if declared_file_kind not in FILE_KINDS:
            return [
                AnalyzeStoriesImportIssue(
                    code="invalid_declared_file_kind",
                    severity="warning",
                    message="Declared file kind is not recognized.",
                    artifact_id=artifact_id,
                    field_path="declared_file_kind",
                    safe_detail=f"detected={detected_kind}",
                )
            ]
        if detected_kind != "unknown" and declared_file_kind != detected_kind:
            return [
                AnalyzeStoriesImportIssue(
                    code="declared_file_kind_mismatch",
                    severity="warning",
                    message="Declared file kind differs from detected file kind.",
                    artifact_id=artifact_id,
                    field_path="declared_file_kind",
                    safe_detail=f"declared={declared_file_kind}; detected={detected_kind}",
                )
            ]
        return []

    def _missing_recommended_fields(
        self,
        payload: dict[str, Any],
        artifact_kind: str,
    ) -> list[str]:
        if artifact_kind == "framework_package":
            required = [
                "macro_framework",
                "component_vocabulary",
                "chapter_macro_assignments",
                "built_chapter_frameworks",
            ]
            return [field for field in required if field not in payload]
        if artifact_kind == "story_analysis_report":
            options = [
                "story_analysis_report",
                "report_sections",
                "analysis_summary",
                "report_title",
                "title",
                "summary",
                "sections",
            ]
            if any(field in payload for field in options):
                return []
            return ["story_analysis_report_ref_fields"]
        return []

    def _recommended_field_issues(
        self,
        missing: list[str],
        artifact_id: str,
        artifact_kind: str,
    ) -> list[AnalyzeStoriesImportIssue]:
        return [
            AnalyzeStoriesImportIssue(
                code="missing_recommended_field",
                severity="warning",
                message="Recommended Analyze Stories field is missing.",
                artifact_id=artifact_id,
                field_path=field,
                safe_detail=f"file_kind={artifact_kind}",
            )
            for field in missing
        ]

    def _fingerprint_issues(
        self,
        fingerprints: list[AnalyzeStoriesInputFingerprint],
        artifact_id: str,
    ) -> list[AnalyzeStoriesImportIssue]:
        if not fingerprints:
            return [
                AnalyzeStoriesImportIssue(
                    code="missing_input_fingerprint",
                    severity="warning",
                    message="No Analyze Stories input fingerprint was found.",
                    artifact_id=artifact_id,
                    field_path="input_fingerprint",
                    safe_detail="Artifact hash was not used as a substitute.",
                )
            ]
        issues: list[AnalyzeStoriesImportIssue] = []
        for fingerprint in fingerprints:
            if fingerprint.missing_fields:
                issues.append(
                    AnalyzeStoriesImportIssue(
                        code="missing_input_fingerprint",
                        severity="warning",
                        message="Analyze Stories input fingerprint is incomplete.",
                        artifact_id=artifact_id,
                        field_path=fingerprint.fingerprint_id,
                        safe_detail="missing=" + ",".join(fingerprint.missing_fields),
                    )
                )
        return issues

    def _analyzer_status_issues(
        self,
        payload: dict[str, Any],
        artifact_id: str,
    ) -> list[AnalyzeStoriesImportIssue]:
        status = self._first_str(
            payload.get("status"),
            payload.get("run_status"),
            payload.get("analysis_status"),
            self._dict_at(payload, "run_manifest").get("run_status"),
            self._dict_at(payload, "run_manifest").get("status"),
        )
        if not status:
            return []
        normalized = status.strip().lower()
        if normalized in {"failed", "error", "timeout", "timed_out"}:
            return [
                AnalyzeStoriesImportIssue(
                    code="analyzer_run_failed",
                    severity="blocking",
                    message="Analyze Stories run did not complete successfully.",
                    artifact_id=artifact_id,
                    field_path="run_status",
                    safe_detail=f"status={self._short(normalized, 40)}",
                )
            ]
        if normalized in {"partial", "incomplete", "degraded"}:
            return [
                AnalyzeStoriesImportIssue(
                    code="analyzer_run_partial",
                    severity="warning",
                    message="Analyze Stories run is partial or incomplete.",
                    artifact_id=artifact_id,
                    field_path="run_status",
                    safe_detail=f"status={self._short(normalized, 40)}",
                )
            ]
        return []

    def _bundle_shallow_warnings(
        self,
        payload: dict[str, Any],
        artifact_id: str,
        artifact_kind: str,
    ) -> list[AnalyzeStoriesImportIssue]:
        if artifact_kind != "full_book_bundle":
            return []
        chapters = payload.get("chapters")
        if not isinstance(chapters, list):
            return []
        warnings: list[AnalyzeStoriesImportIssue] = []
        for expected, chapter in enumerate(chapters, start=1):
            if not isinstance(chapter, dict):
                continue
            index = self._safe_int(chapter.get("chapter_index") or chapter.get("index"))
            title = self._first_str(chapter.get("title"), chapter.get("chapter_title"))
            summary = self._first_str(chapter.get("summary"), chapter.get("chapter_summary"))
            if index is not None and index != expected:
                warnings.append(
                    AnalyzeStoriesImportIssue(
                        code="bundle_shallow_mismatch",
                        severity="warning",
                        message="Full book bundle chapter index has a shallow mismatch.",
                        artifact_id=artifact_id,
                        field_path=f"chapters[{expected - 1}].chapter_index",
                        safe_detail=f"expected={expected}; found={index}",
                    )
                )
            if title and summary and self._safe_slug(title) not in self._safe_slug(summary):
                warnings.append(
                    AnalyzeStoriesImportIssue(
                        code="bundle_title_summary_mismatch",
                        severity="warning",
                        message="Full book bundle chapter title and summary may not match.",
                        artifact_id=artifact_id,
                        field_path=f"chapters[{expected - 1}]",
                        safe_detail="shallow check only; no deep validation performed.",
                    )
                )
                break
        return warnings[:3]

    def _story_report_issues(
        self,
        artifact_kind: str,
        refs: list[StoryAnalysisReportRef],
        artifact_id: str,
    ) -> list[AnalyzeStoriesImportIssue]:
        if artifact_kind != "story_analysis_report":
            return []
        if not refs:
            return [
                AnalyzeStoriesImportIssue(
                    code="story_report_ref_missing",
                    severity="warning",
                    message="Story analysis report reference could not be created.",
                    artifact_id=artifact_id,
                    field_path="$",
                    safe_detail="M1 does not create a full viewer.",
                )
            ]
        if refs[0].viewer_status in {"invalid", "blocked"}:
            return [
                AnalyzeStoriesImportIssue(
                    code="story_report_ref_unavailable",
                    severity="warning",
                    message="Story analysis report reference is not available for viewing.",
                    artifact_id=artifact_id,
                    field_path="$",
                    safe_detail=f"viewer_status={refs[0].viewer_status}",
                )
            ]
        return []

    def _scan_safety(self, value: Any) -> list[AnalyzeStoriesImportIssue]:
        issues: list[AnalyzeStoriesImportIssue] = []

        def walk(node: Any, path: str, key_hint: str = "") -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    key_text = str(key)
                    normalized = self._normalize_key(key_text)
                    child_path = f"{path}.{key_text}" if path else key_text
                    if normalized in UNSAFE_NORMALIZED_KEYS:
                        issues.append(self._unsafe_issue("unsafe_field_name", child_path))
                    if normalized in UNSAFE_TEXT_FIELD_KEYS:
                        if isinstance(child, str) and len(child.strip()) > 80:
                            issues.append(self._unsafe_issue("unsafe_full_prose_field", child_path))
                    walk(child, child_path, normalized)
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    walk(child, f"{path}[{index}]", key_hint)
            elif isinstance(node, str):
                if self._looks_like_secret(node):
                    issues.append(self._unsafe_issue("unsafe_secret_value", path))
                elif any(marker in node for marker in UNSAFE_VALUE_MARKERS):
                    issues.append(self._unsafe_issue("unsafe_marker_value", path))
                elif key_hint in UNSAFE_TEXT_FIELD_KEYS and len(node.strip()) > 80:
                    issues.append(self._unsafe_issue("unsafe_full_prose_value", path))
                elif len(node) > 12000:
                    issues.append(self._unsafe_issue("unsafe_long_text_value", path))

        walk(value, "$")
        deduped: dict[tuple[str, str | None], AnalyzeStoriesImportIssue] = {}
        for issue in issues:
            deduped[(issue.code, issue.field_path)] = issue
        return list(deduped.values())

    def _unsafe_issue(self, code: str, path: str) -> AnalyzeStoriesImportIssue:
        return AnalyzeStoriesImportIssue(
            code=code,
            severity="blocking",
            message="Analyze Stories artifact contains unsafe raw or secret-like data.",
            artifact_id=None,
            field_path=self._redacted_field_path(path),
            safe_detail="Value redacted; raw artifact was not stored.",
        )

    def _looks_like_secret(self, value: str) -> bool:
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)

    def _write_artifact_metadata(
        self,
        *,
        import_id: str,
        artifact_id: str,
        content_sha256: str,
        file_kind: str,
        top_level_keys: list[str],
        raw_storage_status: str,
        safe_summary: str,
        payload_ref: str | None = None,
    ) -> str:
        relative = Path("imports") / "analyze_stories" / import_id / f"{artifact_id}_metadata.json"
        path = self.data_dir / relative
        self.store.write(
            path,
            {
                "artifact_id": artifact_id,
                "import_id": import_id,
                "file_kind": file_kind,
                "content_sha256": content_sha256,
                "raw_storage_status": raw_storage_status,
                "top_level_keys": top_level_keys,
                "safe_summary": safe_summary,
                "stored_raw_artifact": bool(payload_ref),
                "payload_ref": payload_ref,
                "version_id": SCHEMA_VERSION,
            },
        )
        return relative.as_posix()

    def _write_safe_payload(
        self,
        *,
        import_id: str,
        artifact_id: str,
        payload: dict[str, Any],
    ) -> str:
        relative = Path("imports") / "analyze_stories" / import_id / f"{artifact_id}_payload.json"
        path = self.data_dir / relative
        self.store.write(path, payload)
        return relative.as_posix()

    def _resolve_storage_ref(self, storage_ref: str) -> Path:
        ref_path = Path(storage_ref)
        if ref_path.is_absolute() or ".." in ref_path.parts:
            raise StorageError(f"ANALYZE_STORIES_UNSAFE_STORAGE_REF: {storage_ref}")
        resolved = (self.data_dir / ref_path).resolve()
        root = self.data_dir.resolve()
        if not str(resolved).startswith(str(root)):
            raise StorageError(f"ANALYZE_STORIES_UNSAFE_STORAGE_REF: {storage_ref}")
        return resolved

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        data = self.store.read_list(path)
        return [item for item in data if isinstance(item, dict)]

    def _append(self, path: Path, item: dict[str, Any]) -> None:
        items = self._read_list(path)
        items.append(item)
        self.store.write(path, items)

    def _next_import_id(self) -> str:
        items = self._read_list(self.imports_file)
        return f"as_import_{len(items) + 1:03d}"

    def _manifest_status(
        self,
        passed: bool,
        can_proceed_to_m2: bool,
        warnings: list[AnalyzeStoriesImportIssue],
    ) -> str:
        if not passed:
            return "blocked"
        if can_proceed_to_m2:
            return "ready_for_m2"
        if warnings:
            return "validated_with_warnings"
        return "parsed"

    def _next_step_blockers(
        self,
        *,
        passed: bool,
        artifact_kind: str,
        source_value: str,
        warnings: list[AnalyzeStoriesImportIssue],
        missing_recommended: list[str],
        fingerprints: list[AnalyzeStoriesInputFingerprint],
    ) -> list[str]:
        blockers: list[str] = []
        if not passed:
            blockers.append("basic_validation_blocking_issues")
        if artifact_kind != "framework_package":
            blockers.append("not_framework_package")
        if source_value != "analyze_stories":
            blockers.append("source_not_analyze_stories")
        if warnings:
            blockers.append("warnings_present")
        if missing_recommended:
            blockers.append("missing_recommended_fields")
        if not fingerprints:
            blockers.append("input_fingerprints_missing")
        elif any(item.completeness_status != "complete" for item in fingerprints):
            blockers.append("input_fingerprints_incomplete")
        return self._dedupe(blockers)

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _artifact_summary(
        self,
        file_kind: str,
        top_level_keys: list[str],
        content_hash: str,
    ) -> str:
        keys = ", ".join(top_level_keys[:8]) or "no top-level keys"
        return (
            f"Analyze Stories artifact kind={file_kind}; "
            f"keys={keys}; sha256={content_hash[:12]}..."
        )

    def _validation_summary(
        self,
        file_kind: str,
        passed: bool,
        can_proceed_to_m2: bool,
        blocking_count: int,
        warning_count: int,
    ) -> str:
        return (
            f"Import gate checked {file_kind}; passed={passed}; "
            f"can_proceed_to_m2={can_proceed_to_m2}; "
            f"blocking={blocking_count}; warnings={warning_count}."
        )

    def _source_value(self, payload: dict[str, Any]) -> str:
        run_manifest = self._dict_at(payload, "run_manifest")
        metadata = self._dict_at(payload, "metadata")
        return (
            self._first_str(
                payload.get("source"),
                run_manifest.get("source"),
                metadata.get("source"),
            )
            or ""
        ).strip()

    def _dict_at(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        value = payload.get(key)
        return value if isinstance(value, dict) else {}

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

    def _is_missing_value(self, value: Any) -> bool:
        return value is None or value == "" or value == []

    def _safe_top_level_keys(self, payload: dict[str, Any]) -> list[str]:
        keys: list[str] = []
        for key in payload:
            normalized = self._normalize_key(str(key))
            if normalized in UNSAFE_NORMALIZED_KEYS or normalized in UNSAFE_TEXT_FIELD_KEYS:
                keys.append("[redacted_unsafe_key]")
            else:
                keys.append(self._short(str(key), 80))
        return sorted(dict.fromkeys(keys))

    def _redacted_field_path(self, path: str) -> str:
        if any(
            self._normalize_key(part) in UNSAFE_NORMALIZED_KEYS
            or self._normalize_key(part) in UNSAFE_TEXT_FIELD_KEYS
            for part in re.split(r"[.\[\]]+", path)
            if part
        ):
            return "$.[redacted_unsafe_field]"
        return self._short(path, 180)

    def _normalize_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    def _short(self, value: str, limit: int = 180) -> str:
        clean = " ".join(str(value).split())
        if len(clean) <= limit:
            return clean
        return clean[: limit - 3] + "..."

    def _safe_slug(self, value: str) -> str:
        words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", value.lower())
        return "".join(words[:8])
