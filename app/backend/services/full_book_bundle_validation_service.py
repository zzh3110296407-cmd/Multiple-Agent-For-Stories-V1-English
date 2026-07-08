import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.analyze_stories_import import (
    AnalyzeStoriesImportedArtifact,
    AnalyzeStoriesImportDetail,
    AnalyzeStoriesInputFingerprint,
    StoryAnalysisReportRef,
)
from app.backend.models.full_book_bundle_validation import (
    BundleChapterEntry,
    BundleChapterFingerprintAudit,
    BundleChapterInventory,
    BundleFrameworkReportConsistencyCheck,
    BundleValidationIssue,
    CrossChapterStateReferenceCheck,
    FullBookBundleDetail,
    FullBookBundleListResponse,
    FullBookBundleManifest,
    FullBookBundleValidationReport,
    FullBookBundleValidationResult,
)
from app.backend.services.analyze_stories_import_service import AnalyzeStoriesImportService
from app.backend.services.analysis_report_viewer_service import AnalysisReportViewerService
from app.backend.services.framework_package_candidate_service import FrameworkPackageCandidateService
from app.backend.storage.json_store import JsonStore, StorageError


MANIFESTS_FILE = "full_book_bundle_manifests.json"
INVENTORIES_FILE = "bundle_chapter_inventories.json"
FINGERPRINT_AUDITS_FILE = "bundle_chapter_fingerprint_audits.json"
CROSS_REF_CHECKS_FILE = "cross_chapter_state_reference_checks.json"
CONSISTENCY_CHECKS_FILE = "bundle_framework_report_consistency_checks.json"
REPORTS_FILE = "full_book_bundle_validation_reports.json"
SCHEMA_VERSION = "phase5_m5_full_book_bundle_validation_v1"
SUPPORTED_FILE_KINDS = {"full_book_bundle", "cross_chapter_state_package"}
OPTIONAL_REPORT_VIEWER_WARNING_CODES = {
    "candidate_context_unavailable",
    "candidate_context_conflict",
    "suspicious_or_incomplete_input_metadata",
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
    "internal reasoning",
]
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class FullBookBundleValidationService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        analyze_import_service: AnalyzeStoriesImportService | None = None,
        framework_candidate_service: FrameworkPackageCandidateService | None = None,
        analysis_report_viewer_service: AnalysisReportViewerService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.analyze_import_service = analyze_import_service or AnalyzeStoriesImportService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_candidate_service = framework_candidate_service or FrameworkPackageCandidateService(
            store=self.store,
            data_dir=self.data_dir,
            analyze_import_service=self.analyze_import_service,
        )
        self.analysis_report_viewer_service = analysis_report_viewer_service or AnalysisReportViewerService(
            store=self.store,
            data_dir=self.data_dir,
            analyze_import_service=self.analyze_import_service,
            framework_candidate_service=self.framework_candidate_service,
        )
        self.manifests_file = self.data_dir / MANIFESTS_FILE
        self.inventories_file = self.data_dir / INVENTORIES_FILE
        self.fingerprint_audits_file = self.data_dir / FINGERPRINT_AUDITS_FILE
        self.cross_ref_checks_file = self.data_dir / CROSS_REF_CHECKS_FILE
        self.consistency_checks_file = self.data_dir / CONSISTENCY_CHECKS_FILE
        self.reports_file = self.data_dir / REPORTS_FILE

    def validate_bundle_from_import(
        self,
        import_id: str,
        artifact_id: str | None = None,
        linked_framework_candidate_id: str | None = None,
        linked_story_analysis_report_ref_id: str | None = None,
        linked_framework_candidate_ids: list[str] | None = None,
        linked_story_analysis_report_ref_ids: list[str] | None = None,
    ) -> FullBookBundleValidationResult:
        detail = self.analyze_import_service.get_detail(import_id)
        artifact = self._select_artifact(detail, artifact_id)
        timestamp = now_iso()
        bundle_manifest_id = self._next_manifest_id()
        inventory_id = f"{bundle_manifest_id}_inventory"
        fingerprint_audit_id = f"{bundle_manifest_id}_fingerprint_audit"
        cross_ref_check_id = f"{bundle_manifest_id}_cross_ref_check"
        consistency_check_id = f"{bundle_manifest_id}_consistency_check"
        report_id = f"{bundle_manifest_id}_validation_report"

        issues: list[BundleValidationIssue] = []
        payload: dict[str, Any] | None = None
        root: dict[str, Any] = {}
        root_path = "$"
        chapters_value: Any = None
        cross_state_value: Any = None
        declared_chapter_count: int | None = None
        metadata = self._metadata_from_detail(detail, None)

        if artifact.file_kind not in SUPPORTED_FILE_KINDS:
            issues.append(
                self._issue(
                    "unsupported_file_kind",
                    "blocking",
                    "artifact.file_kind",
                    artifact_id=artifact.artifact_id,
                    safe_detail=f"file_kind={artifact.file_kind}",
                    blocks_reference=True,
                )
            )
        elif artifact.raw_storage_status != "stored" or not artifact.payload_ref:
            issues.append(
                self._issue(
                    "artifact_payload_unavailable",
                    "blocking",
                    "payload_ref",
                    artifact_id=artifact.artifact_id,
                    safe_detail="Historical hash-only bundle imports must be re-imported before M5 validation.",
                    blocks_reference=True,
                )
            )
        else:
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
                        "payload_ref",
                        artifact_id=artifact.artifact_id,
                        safe_detail="Safe bundle payload is unavailable; re-import the bundle.",
                        blocks_reference=True,
                    )
                )

        if payload is not None:
            payload_safety = self._scan_safety(payload)
            issues.extend(payload_safety)
            if not any(item.severity == "blocking" for item in payload_safety):
                shape = self._extract_bundle_shape(payload, artifact.file_kind)
                root = shape["root"]
                root_path = shape["root_path"]
                chapters_value = shape["chapters"]
                cross_state_value = shape["cross_state"]
                declared_chapter_count = self._first_int(
                    root.get("chapter_count"),
                    root.get("declared_chapter_count"),
                    root.get("detected_chapter_count"),
                    self._dict_at(root, "run_manifest").get("chapter_count"),
                    self._dict_at(payload, "run_manifest").get("chapter_count"),
                    self._dict_at(payload, "metadata").get("chapter_count"),
                )
                metadata = self._metadata_from_detail(detail, payload)
                issues.extend(shape["issues"])

        entries, inventory_issues = self._build_entries(
            chapters_value,
            bundle_manifest_id,
            artifact,
            metadata,
            declared_chapter_count,
            root_path,
        )
        issues.extend(inventory_issues)
        inventory = self._build_inventory(
            inventory_id,
            bundle_manifest_id,
            import_id,
            artifact.artifact_id,
            declared_chapter_count,
            entries,
            inventory_issues,
            timestamp,
        )
        fingerprint_audit, fingerprint_issues = self._build_fingerprint_audit(
            fingerprint_audit_id,
            bundle_manifest_id,
            detail,
            artifact,
            entries,
            timestamp,
        )
        issues.extend(fingerprint_issues)
        cross_ref_check, cross_ref_issues = self._build_cross_ref_check(
            cross_ref_check_id,
            bundle_manifest_id,
            import_id,
            artifact.artifact_id,
            cross_state_value,
            payload,
            entries,
            timestamp,
        )
        issues.extend(cross_ref_issues)
        consistency_check, consistency_issues = self._build_consistency_check(
            consistency_check_id,
            bundle_manifest_id,
            import_id,
            artifact.artifact_id,
            entries,
            declared_chapter_count,
            linked_framework_candidate_id,
            linked_story_analysis_report_ref_id,
            linked_framework_candidate_ids,
            linked_story_analysis_report_ref_ids,
            timestamp,
        )
        issues.extend(consistency_issues)

        blocking = [issue for issue in issues if issue.severity == "blocking"]
        warnings = [issue for issue in issues if issue.severity == "warning"]
        info = [issue for issue in issues if issue.severity == "info"]
        can_reference = not any(issue.blocks_reference for issue in blocking)
        can_m6 = can_reference and not any(issue.blocks_m6_adapter for issue in issues)
        reliability = self._reliability_level(blocking, warnings, can_reference, can_m6)
        status = (
            "blocked"
            if not can_reference
            else "validated_with_warnings"
            if warnings
            else "validated"
        )
        bundle_id = self._first_str(root.get("bundle_id"), root.get("id"), artifact.artifact_id)
        manifest = FullBookBundleManifest(
            bundle_manifest_id=bundle_manifest_id,
            import_id=import_id,
            artifact_id=artifact.artifact_id,
            file_kind=artifact.file_kind,
            source="analyze_stories",
            bundle_id=bundle_id,
            schema_version=self._first_str(root.get("schema_version"), payload.get("schema_version") if payload else None),
            contract_version=self._first_str(root.get("contract_version"), payload.get("contract_version") if payload else None),
            exporter_version=self._first_str(root.get("exporter_version"), payload.get("exporter_version") if payload else None),
            run_id=self._first_str(root.get("run_id"), self._dict_at(root, "run_manifest").get("run_id"), self._dict_at(payload or {}, "run_manifest").get("run_id")),
            declared_chapter_count=declared_chapter_count,
            detected_chapter_count=len(entries),
            chapter_inventory_id=inventory.chapter_inventory_id,
            fingerprint_audit_id=fingerprint_audit.fingerprint_audit_id,
            cross_chapter_reference_check_id=cross_ref_check.cross_chapter_reference_check_id,
            consistency_check_id=consistency_check.consistency_check_id,
            validation_report_id=report_id,
            reliability_level=reliability,
            bundle_status=status,
            can_be_used_as_reference=can_reference,
            can_proceed_to_m6_adapter=can_m6,
            source_ref={
                "import_id": import_id,
                "artifact_id": artifact.artifact_id,
                "artifact_sha256": artifact.content_sha256,
                "payload_ref": artifact.payload_ref,
            },
            safe_summary=self._manifest_summary(bundle_id, len(entries), reliability, can_reference, can_m6, len(blocking), len(warnings)),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        report = FullBookBundleValidationReport(
            validation_report_id=report_id,
            bundle_manifest_id=bundle_manifest_id,
            import_id=import_id,
            artifact_id=artifact.artifact_id,
            passed=can_reference,
            reliability_level=reliability,
            bundle_status=status,
            can_be_used_as_reference=can_reference,
            can_proceed_to_m6_adapter=can_m6,
            blocking_issues=blocking,
            warnings=warnings,
            info=info,
            issue_counts={
                "blocking": len(blocking),
                "warning": len(warnings),
                "info": len(info),
            },
            safe_summary=manifest.safe_summary,
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._guard_safe_records(
            manifest,
            inventory,
            fingerprint_audit,
            cross_ref_check,
            consistency_check,
            report,
        )
        self._replace_or_append(self.manifests_file, "bundle_manifest_id", bundle_manifest_id, model_to_dict(manifest))
        self._replace_or_append(self.inventories_file, "chapter_inventory_id", inventory.chapter_inventory_id, model_to_dict(inventory))
        self._replace_or_append(self.fingerprint_audits_file, "fingerprint_audit_id", fingerprint_audit.fingerprint_audit_id, model_to_dict(fingerprint_audit))
        self._replace_or_append(self.cross_ref_checks_file, "cross_chapter_reference_check_id", cross_ref_check.cross_chapter_reference_check_id, model_to_dict(cross_ref_check))
        self._replace_or_append(self.consistency_checks_file, "consistency_check_id", consistency_check.consistency_check_id, model_to_dict(consistency_check))
        self._replace_or_append(self.reports_file, "validation_report_id", report.validation_report_id, model_to_dict(report))
        return FullBookBundleValidationResult(
            success=can_reference,
            manifest=manifest,
            chapter_inventory=inventory,
            fingerprint_audit=fingerprint_audit,
            cross_chapter_reference_check=cross_ref_check,
            consistency_check=consistency_check,
            validation_report=report,
        )

    def list_bundles(self) -> FullBookBundleListResponse:
        manifests = [
            FullBookBundleManifest(**item)
            for item in self._read_list(self.manifests_file)
        ]
        manifests.sort(key=lambda item: item.updated_at, reverse=True)
        return FullBookBundleListResponse(bundles=manifests)

    def get_bundle(self, bundle_manifest_id: str) -> FullBookBundleDetail:
        manifest = self._get_manifest(bundle_manifest_id)
        return FullBookBundleDetail(
            manifest=manifest,
            chapter_inventory=self._find_inventory(manifest.chapter_inventory_id),
            fingerprint_audit=self._find_fingerprint_audit(manifest.fingerprint_audit_id),
            cross_chapter_reference_check=self._find_cross_ref_check(manifest.cross_chapter_reference_check_id),
            consistency_check=self._find_consistency_check(manifest.consistency_check_id),
            validation_report=self._find_report(manifest.validation_report_id),
        )

    def get_validation_report(self, bundle_manifest_id: str) -> FullBookBundleValidationReport:
        manifest = self._get_manifest(bundle_manifest_id)
        report = self._find_report(manifest.validation_report_id)
        if report is None:
            raise StorageError(f"FULL_BOOK_BUNDLE_VALIDATION_REPORT_NOT_FOUND: {bundle_manifest_id}")
        return report

    def get_chapter_inventory(self, bundle_manifest_id: str) -> BundleChapterInventory:
        manifest = self._get_manifest(bundle_manifest_id)
        inventory = self._find_inventory(manifest.chapter_inventory_id)
        if inventory is None:
            raise StorageError(f"FULL_BOOK_BUNDLE_NOT_FOUND: {bundle_manifest_id}")
        return inventory

    def get_cross_chapter_reference_check(self, bundle_manifest_id: str) -> CrossChapterStateReferenceCheck:
        manifest = self._get_manifest(bundle_manifest_id)
        check = self._find_cross_ref_check(manifest.cross_chapter_reference_check_id)
        if check is None:
            raise StorageError(f"FULL_BOOK_BUNDLE_NOT_FOUND: {bundle_manifest_id}")
        return check

    def revalidate_bundle(self, bundle_manifest_id: str) -> FullBookBundleValidationResult:
        existing = self.get_bundle(bundle_manifest_id)
        consistency = existing.consistency_check
        return self.validate_bundle_from_import(
            existing.manifest.import_id,
            artifact_id=existing.manifest.artifact_id,
            linked_framework_candidate_id=consistency.linked_framework_candidate_id if consistency else None,
            linked_story_analysis_report_ref_id=consistency.linked_story_analysis_report_ref_id if consistency else None,
        )

    def _select_artifact(
        self,
        detail: AnalyzeStoriesImportDetail,
        artifact_id: str | None,
    ) -> AnalyzeStoriesImportedArtifact:
        artifacts = detail.artifacts
        if artifact_id:
            for artifact in artifacts:
                if artifact.artifact_id == artifact_id:
                    return artifact
            raise StorageError(f"FULL_BOOK_BUNDLE_ARTIFACT_NOT_READY: {artifact_id}")
        eligible = [item for item in artifacts if item.file_kind in SUPPORTED_FILE_KINDS]
        if not eligible:
            raise StorageError(f"FULL_BOOK_BUNDLE_ARTIFACT_NOT_READY: {detail.manifest.import_id}")
        if len(eligible) > 1:
            raise StorageError("FULL_BOOK_BUNDLE_ARTIFACT_NOT_READY: explicit artifact_id is required.")
        return eligible[0]

    def _extract_bundle_shape(
        self,
        payload: dict[str, Any],
        file_kind: str,
    ) -> dict[str, Any]:
        issues: list[BundleValidationIssue] = []
        root: dict[str, Any] = payload
        root_path = "$"
        if isinstance(payload.get("full_book_bundle"), dict):
            root = payload["full_book_bundle"]
            root_path = "$.full_book_bundle"
        elif isinstance(payload.get("bundle"), dict) and isinstance(payload["bundle"].get("chapters"), list):
            root = payload["bundle"]
            root_path = "$.bundle"
        elif isinstance(payload.get("cross_chapter_state_package"), dict):
            root = payload["cross_chapter_state_package"]
            root_path = "$.cross_chapter_state_package"
        chapters_value = root.get("chapters")
        cross_state = self._first_present(
            root.get("cross_chapter_state_package"),
            root.get("cross_chapter_state"),
            root.get("chapter_states"),
            payload.get("cross_chapter_state_package"),
            payload.get("cross_chapter_state"),
            payload.get("chapter_states"),
        )
        if chapters_value is None and file_kind == "cross_chapter_state_package":
            chapters_value = self._chapters_from_cross_state(cross_state)
        if not isinstance(root, dict):
            issues.append(self._issue("unknown_bundle_root", "blocking", root_path, blocks_reference=True))
        elif chapters_value is None and file_kind == "full_book_bundle":
            issues.append(self._issue("chapter_list_missing", "blocking", f"{root_path}.chapters", blocks_reference=True))
        elif chapters_value is not None and not isinstance(chapters_value, list):
            issues.append(self._issue("chapter_list_not_list", "blocking", f"{root_path}.chapters", blocks_reference=True))
        if (
            file_kind == "full_book_bundle"
            and root_path == "$"
            and "chapters" not in root
            and "full_book_bundle" not in payload
        ):
            issues.append(self._issue("unknown_bundle_root", "blocking", "$", blocks_reference=True))
        return {
            "root": root if isinstance(root, dict) else {},
            "root_path": root_path,
            "chapters": chapters_value,
            "cross_state": cross_state,
            "issues": issues,
        }

    def _build_entries(
        self,
        chapters_value: Any,
        bundle_manifest_id: str,
        artifact: AnalyzeStoriesImportedArtifact,
        metadata: dict[str, str | None],
        declared_chapter_count: int | None,
        root_path: str,
    ) -> tuple[list[BundleChapterEntry], list[BundleValidationIssue]]:
        issues: list[BundleValidationIssue] = []
        if chapters_value is None:
            chapters: list[Any] = []
        elif isinstance(chapters_value, list):
            chapters = chapters_value
        else:
            chapters = []
        entries: list[BundleChapterEntry] = []
        for order, chapter in enumerate(chapters, start=1):
            field_path = f"{root_path}.chapters[{order - 1}]"
            if not isinstance(chapter, dict):
                issues.append(self._issue("chapter_entry_not_object", "blocking", field_path, blocks_reference=True))
                continue
            chapter_index = self._first_int(
                chapter.get("chapter_index"),
                chapter.get("index"),
                chapter.get("chapter_number"),
            )
            warning_codes: list[str] = []
            blocking_codes: list[str] = []
            missing_fields: list[str] = []
            if chapter_index is None:
                missing_fields.append("chapter_index")
                blocking_codes.append("chapter_index_missing")
                issues.append(self._issue("chapter_index_missing", "blocking", f"{field_path}.chapter_index", blocks_reference=True))
            elif chapter_index != order:
                warning_codes.append("chapter_index_order_mismatch")
                issues.append(self._issue("chapter_index_order_mismatch", "warning", f"{field_path}.chapter_index", chapter_index=chapter_index, safe_detail=f"order={order}; index={chapter_index}"))
            raw_input_filename = self._first_present(
                chapter.get("input_filename"),
                chapter.get("filename"),
                chapter.get("source_filename"),
            )
            input_filename = self._first_str(raw_input_filename)
            if isinstance(raw_input_filename, str) and not raw_input_filename.strip():
                warning_codes.append("input_filename_blank")
                issues.append(self._issue("input_filename_blank", "warning", f"{field_path}.input_filename", chapter_index=chapter_index, safe_detail="Blank input_filename allows reference display but blocks M6 adapter readiness."))
            elif input_filename is None:
                missing_fields.append("input_filename")
            input_title = self._first_str(
                chapter.get("input_title"),
                chapter.get("title"),
                chapter.get("chapter_title"),
            )
            title_safe, title_length, title_redacted = self._safe_input_title(input_title)
            if title_redacted:
                warning_codes.append("input_title_raw_or_too_long")
                issues.append(self._issue("input_title_raw_or_too_long", "warning", f"{field_path}.input_title", chapter_index=chapter_index, safe_detail=title_safe))
            input_hash = self._first_str(
                chapter.get("input_content_sha256"),
                chapter.get("content_sha256"),
                chapter.get("source_content_sha256"),
                chapter.get("input_sha256"),
            )
            if input_hash is None:
                missing_fields.append("input_content_sha256")
                warning_codes.append("input_hash_missing")
                issues.append(self._issue("input_hash_missing", "warning", f"{field_path}.input_content_sha256", chapter_index=chapter_index, safe_detail="No per-chapter input content hash was found."))
            elif input_hash == artifact.content_sha256:
                warning_codes.append("artifact_hash_used_as_input_hash")
                issues.append(self._issue("artifact_hash_used_as_input_hash", "warning", f"{field_path}.input_content_sha256", chapter_index=chapter_index, safe_detail="Imported artifact hash must not substitute for per-chapter input hash."))
            generated_artifacts = self._safe_str_list(chapter.get("generated_artifacts"))
            for ref_field, generated_name in [
                ("framework_package_ref", "framework_package"),
                ("story_analysis_report_ref", "story_analysis_report"),
                ("next_pack_ref", "next_pack"),
            ]:
                if generated_name in generated_artifacts and not self._first_str(chapter.get(ref_field)):
                    warning_codes.append("generated_artifact_ref_missing")
                    issues.append(self._issue("generated_artifact_ref_missing", "warning", f"{field_path}.{ref_field}", chapter_index=chapter_index, safe_detail=f"generated_artifact={generated_name}"))
            missing_metadata = [
                name
                for name, value in metadata.items()
                if name in {"analyzer_version", "workflow_version", "model", "processed_at"} and not value
            ]
            for local_key, meta_key in [
                ("analyzer_version", "analyzer_version"),
                ("workflow_version", "workflow_version"),
                ("model", "model"),
                ("processed_at", "processed_at"),
            ]:
                if self._first_str(chapter.get(local_key)):
                    if local_key in missing_metadata:
                        missing_metadata.remove(local_key)
            if missing_metadata:
                warning_codes.append("metadata_missing")
                issues.append(self._issue("metadata_missing", "warning", field_path, chapter_index=chapter_index, safe_detail="Missing analyzer/workflow/model/processed-at metadata blocks M6 adapter readiness."))
            status = self._first_str(chapter.get("status"), chapter.get("workflow_status")) or "unknown"
            status_reason = self._short(self._first_str(chapter.get("status_reason"), chapter.get("reason")), 180)
            entry = BundleChapterEntry(
                entry_id=f"{bundle_manifest_id}_chapter_{order:03d}",
                bundle_manifest_id=bundle_manifest_id,
                chapter_index=chapter_index,
                chapter_order=order,
                input_filename=self._short(input_filename, 180) if input_filename is not None else None,
                input_title_safe=title_safe,
                input_title_length=title_length,
                input_title_redacted=title_redacted,
                input_content_sha256=input_hash if self._looks_like_hash(input_hash) else self._short(input_hash, 96) if input_hash else None,
                source_input_meta_ref=self._short(self._first_str(chapter.get("source_input_meta_ref"), chapter.get("source_meta_ref")), 180),
                framework_package_ref=self._short(self._first_str(chapter.get("framework_package_ref")), 180),
                story_analysis_report_ref=self._short(self._first_str(chapter.get("story_analysis_report_ref"), chapter.get("analysis_report_ref")), 180),
                next_pack_ref=self._short(self._first_str(chapter.get("next_pack_ref")), 180),
                status=self._short(status, 80) or "unknown",
                status_reason_safe=status_reason,
                generated_artifacts=generated_artifacts,
                missing_fields=missing_fields,
                warning_codes=self._dedupe(warning_codes),
                blocking_codes=self._dedupe(blocking_codes),
                safe_summary=self._entry_summary(chapter_index, order, input_hash, warning_codes, blocking_codes),
            )
            entries.append(entry)
        issues.extend(self._chapter_index_issues(entries, declared_chapter_count, root_path))
        return entries, issues

    def _build_inventory(
        self,
        inventory_id: str,
        bundle_manifest_id: str,
        import_id: str,
        artifact_id: str,
        declared_chapter_count: int | None,
        entries: list[BundleChapterEntry],
        issues: list[BundleValidationIssue],
        timestamp: str,
    ) -> BundleChapterInventory:
        indexes = [entry.chapter_index for entry in entries if entry.chapter_index is not None]
        duplicate_indexes = sorted(index for index, count in Counter(indexes).items() if count > 1)
        expected = set(range(1, max(indexes) + 1)) if indexes else set()
        missing = sorted(expected.difference(indexes))
        return BundleChapterInventory(
            chapter_inventory_id=inventory_id,
            bundle_manifest_id=bundle_manifest_id,
            import_id=import_id,
            artifact_id=artifact_id,
            declared_chapter_count=declared_chapter_count,
            detected_chapter_count=len(entries),
            chapter_indexes=sorted(indexes),
            duplicate_chapter_indexes=duplicate_indexes,
            missing_chapter_indexes=missing,
            entries=entries,
            warning_count=len([item for item in issues if item.severity == "warning"]),
            blocking_issue_count=len([item for item in issues if item.severity == "blocking"]),
            safe_summary=(
                f"Inventory detected {len(entries)} chapters; "
                f"declared={declared_chapter_count}; duplicate={len(duplicate_indexes)}; missing={len(missing)}."
            ),
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _chapter_index_issues(
        self,
        entries: list[BundleChapterEntry],
        declared_chapter_count: int | None,
        root_path: str,
    ) -> list[BundleValidationIssue]:
        issues: list[BundleValidationIssue] = []
        indexes = [entry.chapter_index for entry in entries if entry.chapter_index is not None]
        counts = Counter(indexes)
        for index, count in sorted(counts.items()):
            if count > 1:
                issues.append(self._issue("chapter_index_duplicate", "blocking", f"{root_path}.chapters", chapter_index=index, safe_detail=f"index={index}; count={count}", blocks_reference=True))
        if indexes:
            expected = set(range(1, max(indexes) + 1))
            missing = sorted(expected.difference(indexes))
            if missing:
                issues.append(self._issue("chapter_index_non_contiguous", "blocking", f"{root_path}.chapters", safe_detail=f"missing={missing}", blocks_reference=True))
        if declared_chapter_count is not None and declared_chapter_count != len(entries):
            issues.append(self._issue("declared_chapter_count_mismatch", "warning", f"{root_path}.chapter_count", safe_detail=f"declared={declared_chapter_count}; detected={len(entries)}"))
        return issues

    def _build_fingerprint_audit(
        self,
        audit_id: str,
        bundle_manifest_id: str,
        detail: AnalyzeStoriesImportDetail,
        artifact: AnalyzeStoriesImportedArtifact,
        entries: list[BundleChapterEntry],
        timestamp: str,
    ) -> tuple[BundleChapterFingerprintAudit, list[BundleValidationIssue]]:
        issues: list[BundleValidationIssue] = []
        fingerprint_by_chapter = {
            item.chapter_index: item
            for item in detail.input_fingerprints
            if item.chapter_index is not None
        }
        mismatch_count = 0
        for entry in entries:
            fingerprint = fingerprint_by_chapter.get(entry.chapter_index)
            if fingerprint and entry.input_content_sha256 and fingerprint.input_content_sha256:
                if entry.input_content_sha256 != fingerprint.input_content_sha256:
                    mismatch_count += 1
                    issues.append(
                        self._issue(
                            "input_fingerprint_mismatch",
                            "warning",
                            "input_content_sha256",
                            chapter_index=entry.chapter_index,
                            safe_detail=f"bundle={entry.input_content_sha256[:12]}...; m1={fingerprint.input_content_sha256[:12]}...",
                        )
                    )
        missing_hash_count = sum(1 for entry in entries if "input_hash_missing" in entry.warning_codes)
        artifact_hash_count = sum(1 for entry in entries if "artifact_hash_used_as_input_hash" in entry.warning_codes)
        blank_filename_count = sum(1 for entry in entries if "input_filename_blank" in entry.warning_codes)
        redacted_title_count = sum(1 for entry in entries if entry.input_title_redacted)
        missing_metadata_count = sum(1 for entry in entries if "metadata_missing" in entry.warning_codes)
        issue_codes = self._dedupe(
            [
                code
                for entry in entries
                for code in entry.warning_codes + entry.blocking_codes
                if code
            ]
            + [issue.code for issue in issues]
        )
        audit = BundleChapterFingerprintAudit(
            fingerprint_audit_id=audit_id,
            bundle_manifest_id=bundle_manifest_id,
            import_id=artifact.import_id,
            artifact_id=artifact.artifact_id,
            checked_chapter_count=len(entries),
            comparable_m1_fingerprint_count=len(fingerprint_by_chapter),
            missing_input_hash_count=missing_hash_count,
            artifact_hash_used_as_input_hash_count=artifact_hash_count,
            blank_input_filename_count=blank_filename_count,
            redacted_input_title_count=redacted_title_count,
            missing_metadata_count=missing_metadata_count,
            mismatch_count=mismatch_count,
            issue_codes=issue_codes,
            safe_summary=(
                f"Fingerprint audit checked {len(entries)} chapters; "
                f"missing_hash={missing_hash_count}; blank_filename={blank_filename_count}; "
                f"redacted_title={redacted_title_count}; mismatch={mismatch_count}."
            ),
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        return audit, issues

    def _build_cross_ref_check(
        self,
        check_id: str,
        bundle_manifest_id: str,
        import_id: str,
        artifact_id: str,
        cross_state_value: Any,
        payload: dict[str, Any] | None,
        entries: list[BundleChapterEntry],
        timestamp: str,
    ) -> tuple[CrossChapterStateReferenceCheck, list[BundleValidationIssue]]:
        valid_indexes = {entry.chapter_index for entry in entries if entry.chapter_index is not None}
        references = self._collect_chapter_references(cross_state_value)
        if not references and payload is not None:
            references = self._collect_chapter_references(
                {
                    key: payload.get(key)
                    for key in ["cross_chapter_state_package", "cross_chapter_state", "chapter_states"]
                    if key in payload
                }
            )
        missing = sorted({index for index in references if index not in valid_indexes})
        issues: list[BundleValidationIssue] = []
        for index in missing:
            issues.append(
                self._issue(
                    "cross_chapter_reference_missing_target",
                    "blocking",
                    "cross_chapter_state",
                    chapter_index=index,
                    safe_detail=f"Referenced chapter {index} is not present in bundle inventory.",
                    blocks_reference=True,
                )
            )
        write_policy_only = True
        if cross_state_value is not None:
            for key, value in self._walk_key_values(cross_state_value):
                if self._normalize_key(key) in {"writeauthority", "formalwriteauthority", "canonicalwrite"}:
                    write_policy_only = False
                    issues.append(self._issue("cross_chapter_write_authority_present", "blocking", key, safe_detail="Cross-chapter state references must remain advisory only.", blocks_reference=True))
                if self._normalize_key(key) == "writepolicy" and self._first_str(value):
                    issues.append(self._issue("write_policy_advisory_only", "info", key, safe_detail="write_policy is retained as reference metadata only.", blocks_m6_adapter=False))
        check = CrossChapterStateReferenceCheck(
            cross_chapter_reference_check_id=check_id,
            bundle_manifest_id=bundle_manifest_id,
            import_id=import_id,
            artifact_id=artifact_id,
            reference_count=len(references),
            missing_reference_count=len(missing),
            invalid_reference_count=len([issue for issue in issues if issue.severity == "blocking"]),
            referenced_chapter_indexes=sorted(set(references)),
            missing_chapter_indexes=missing,
            advisory_write_policy_only=write_policy_only,
            issue_codes=self._dedupe([issue.code for issue in issues]),
            safe_summary=(
                f"Cross-chapter reference check found {len(references)} references; "
                f"missing_targets={len(missing)}; advisory_only={write_policy_only}."
            ),
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        return check, issues

    def _build_consistency_check(
        self,
        check_id: str,
        bundle_manifest_id: str,
        import_id: str,
        artifact_id: str,
        entries: list[BundleChapterEntry],
        declared_chapter_count: int | None,
        linked_framework_candidate_id: str | None,
        linked_story_analysis_report_ref_id: str | None,
        linked_framework_candidate_ids: list[str] | None,
        linked_story_analysis_report_ref_ids: list[str] | None,
        timestamp: str,
    ) -> tuple[BundleFrameworkReportConsistencyCheck, list[BundleValidationIssue]]:
        issues: list[BundleValidationIssue] = []
        framework_available = False
        report_available = False
        chapter_count_match: bool | None = None
        chapter_index_match: bool | None = None
        bundle_indexes = {entry.chapter_index for entry in entries if entry.chapter_index is not None}
        framework_ids = self._dedupe(
            [
                item
                for item in [linked_framework_candidate_id, *(linked_framework_candidate_ids or [])]
                if item
            ]
        )
        report_ids = self._dedupe(
            [
                item
                for item in [linked_story_analysis_report_ref_id, *(linked_story_analysis_report_ref_ids or [])]
                if item
            ]
        )
        framework_indexes: set[int] = set()
        if framework_ids:
            missing_framework_ids = 0
            mismatch_framework_ids = 0
            single_legacy_framework_context = len(framework_ids) == 1 and not linked_framework_candidate_ids
            for framework_id in framework_ids:
                try:
                    detail = self.framework_candidate_service.get_detail(framework_id)
                    framework_available = True
                    candidate = detail.candidate
                    if single_legacy_framework_context and (
                        candidate.import_id != import_id or candidate.artifact_id != artifact_id
                    ):
                        mismatch_framework_ids += 1
                        issues.append(self._issue("linked_framework_import_mismatch", "warning", "linked_framework_candidate_id", safe_detail=f"candidate_import={candidate.import_id}; bundle_import={import_id}"))
                    package = candidate.normalized_framework_package or {}
                    assignments = package.get("chapter_macro_assignments")
                    if isinstance(assignments, list):
                        for item in assignments:
                            if not isinstance(item, dict):
                                continue
                            index = self._first_int(item.get("chapter_index"))
                            if index is not None:
                                framework_indexes.add(index)
                except StorageError:
                    missing_framework_ids += 1
            if missing_framework_ids:
                issues.append(self._issue("linked_framework_context_unavailable", "warning", "linked_framework_candidate_id", safe_detail=f"Missing linked framework candidates: {missing_framework_ids}.", blocks_m6_adapter=False))
            if framework_available and framework_indexes:
                chapter_index_match = framework_indexes == bundle_indexes
                chapter_count_match = len(framework_indexes) == len(bundle_indexes)
                if not chapter_index_match:
                    issues.append(self._issue("linked_framework_chapter_index_mismatch", "warning", "chapter_macro_assignments", safe_detail=f"framework={sorted(framework_indexes)}; bundle={sorted(bundle_indexes)}"))
                if not chapter_count_match:
                    issues.append(self._issue("linked_framework_chapter_count_mismatch", "warning", "chapter_macro_assignments", safe_detail=f"framework={len(framework_indexes)}; bundle={len(bundle_indexes)}"))
            elif framework_available:
                issues.append(self._issue("linked_framework_chapter_index_mismatch", "warning", "chapter_macro_assignments", safe_detail=f"framework=[]; bundle={sorted(bundle_indexes)}"))
            if mismatch_framework_ids:
                # The single legacy field historically meant same-import context. Multi-id V4 sibling
                # imports are checked by chapter coverage instead.
                pass
        if report_ids:
            missing_report_ids = 0
            missing_viewer_ids = 0
            single_legacy_report_context = len(report_ids) == 1 and not linked_story_analysis_report_ref_ids
            for report_id in report_ids:
                try:
                    ref = self._get_story_report_ref(report_id)
                    report_available = True
                    if single_legacy_report_context and ref.import_id != import_id:
                        issues.append(self._issue("linked_report_import_mismatch", "warning", "linked_story_analysis_report_ref_id", safe_detail=f"report_import={ref.import_id}; bundle_import={import_id}"))
                    try:
                        viewer = self.analysis_report_viewer_service.get_viewer_state_for_report(report_id)
                        warning_codes = [
                            issue.code for issue in viewer.viewer_state.warnings
                            if issue.code not in OPTIONAL_REPORT_VIEWER_WARNING_CODES
                        ]
                        for code in warning_codes[:12]:
                            issues.append(self._issue("linked_report_shape_warning", "warning", "report_viewer.warnings", safe_detail=f"viewer_warning={code}"))
                    except StorageError:
                        missing_viewer_ids += 1
                except StorageError:
                    missing_report_ids += 1
            if missing_report_ids:
                issues.append(self._issue("linked_report_context_unavailable", "warning", "linked_story_analysis_report_ref_id", safe_detail=f"Missing linked story analysis report refs: {missing_report_ids}.", blocks_m6_adapter=False))
            if missing_viewer_ids:
                issues.append(self._issue("linked_report_viewer_unavailable", "warning", "linked_story_analysis_report_ref_id", safe_detail=f"Missing linked story report viewers: {missing_viewer_ids}.", blocks_m6_adapter=False))
        if not framework_ids and not report_ids:
            issues.append(
                self._issue(
                    "consistency_context_unavailable",
                    "warning",
                    "linked_context",
                    safe_detail="No linked framework/report context was provided; no mismatch was invented.",
                    blocks_m6_adapter=False,
                )
            )
        if declared_chapter_count is not None and entries:
            if chapter_count_match is None and (framework_ids or report_ids):
                chapter_count_match = declared_chapter_count == len(entries)
        check = BundleFrameworkReportConsistencyCheck(
            consistency_check_id=check_id,
            bundle_manifest_id=bundle_manifest_id,
            import_id=import_id,
            artifact_id=artifact_id,
            linked_framework_candidate_id=linked_framework_candidate_id,
            linked_story_analysis_report_ref_id=linked_story_analysis_report_ref_id,
            linked_framework_candidate_ids=framework_ids,
            linked_story_analysis_report_ref_ids=report_ids,
            framework_context_available=framework_available,
            report_context_available=report_available,
            chapter_count_match=chapter_count_match,
            chapter_index_match=chapter_index_match,
            mismatch_count=len([issue for issue in issues if "mismatch" in issue.code]),
            issue_codes=self._dedupe([issue.code for issue in issues]),
            safe_summary=(
                f"Consistency check framework_context={framework_available}; "
                f"report_context={report_available}; mismatches={len([issue for issue in issues if 'mismatch' in issue.code])}."
            ),
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        return check, issues

    def _chapters_from_cross_state(self, cross_state: Any) -> list[dict[str, Any]] | None:
        if isinstance(cross_state, dict):
            states = cross_state.get("chapter_states")
            if isinstance(states, list):
                return [item for item in states if isinstance(item, dict)]
            if isinstance(states, dict):
                chapters: list[dict[str, Any]] = []
                for key, value in states.items():
                    if isinstance(value, dict):
                        item = dict(value)
                        item.setdefault("chapter_index", self._first_int(key))
                        chapters.append(item)
                return chapters
        if isinstance(cross_state, list):
            return [item for item in cross_state if isinstance(item, dict)]
        return None

    def _collect_chapter_references(self, value: Any) -> list[int]:
        refs: list[int] = []

        def walk(node: Any, key_hint: str = "") -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    normalized = self._normalize_key(str(key))
                    if normalized in {
                        "chapterindex",
                        "chapterindexes",
                        "chapterindices",
                        "sourcechapterindex",
                        "targetchapterindex",
                        "fromchapterindex",
                        "tochapterindex",
                        "referencedchapterindex",
                    }:
                        refs.extend(self._ints_from_value(child))
                    walk(child, normalized)
            elif isinstance(node, list):
                for child in node:
                    walk(child, key_hint)

        walk(value)
        return refs

    def _ints_from_value(self, value: Any) -> list[int]:
        if isinstance(value, int) and not isinstance(value, bool):
            return [value]
        if isinstance(value, str):
            parsed = self._first_int(value)
            return [parsed] if parsed is not None else []
        if isinstance(value, list):
            found: list[int] = []
            for item in value:
                found.extend(self._ints_from_value(item))
            return found
        return []

    def _scan_safety(self, value: Any) -> list[BundleValidationIssue]:
        issues: list[BundleValidationIssue] = []

        def walk(node: Any, path: str, key_hint: str = "") -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    key_text = str(key)
                    normalized = self._normalize_key(key_text)
                    child_path = f"{path}.{key_text}" if path else key_text
                    if normalized in UNSAFE_NORMALIZED_KEYS:
                        issues.append(self._issue("unsafe_field_name", "blocking", child_path, safe_detail="Unsafe field name was redacted.", blocks_reference=True))
                    if normalized in UNSAFE_TEXT_FIELD_KEYS and isinstance(child, str) and len(child.strip()) > 80:
                        issues.append(self._issue("unsafe_full_prose_field", "blocking", child_path, safe_detail="Full prose-like field is not allowed in M5 records.", blocks_reference=True))
                    walk(child, child_path, normalized)
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    walk(child, f"{path}[{index}]", key_hint)
            elif isinstance(node, str):
                if self._looks_like_secret(node):
                    issues.append(self._issue("unsafe_secret_value", "blocking", path, safe_detail="Secret-like value was redacted.", blocks_reference=True))
                elif any(marker in node for marker in UNSAFE_VALUE_MARKERS):
                    issues.append(self._issue("unsafe_marker_value", "blocking", path, safe_detail="Raw/hidden marker was redacted.", blocks_reference=True))
                elif key_hint in UNSAFE_TEXT_FIELD_KEYS and len(node.strip()) > 80:
                    issues.append(self._issue("unsafe_full_prose_value", "blocking", path, safe_detail="Full prose-like value is not allowed in M5 records.", blocks_reference=True))
                elif len(node) > 12000:
                    issues.append(self._issue("unsafe_long_text_value", "blocking", path, safe_detail="Unbounded long text is not allowed in M5 records.", blocks_reference=True))

        walk(value, "$")
        deduped: dict[tuple[str, str | None], BundleValidationIssue] = {}
        for issue in issues:
            deduped[(issue.code, issue.field_path)] = issue
        return list(deduped.values())

    def _guard_safe_records(self, *records: BaseModel) -> None:
        for record in records:
            payload = model_to_dict(record)
            issues = self._scan_safety(payload)
            if any(issue.severity == "blocking" for issue in issues):
                raise StorageError("FULL_BOOK_BUNDLE_UNSAFE_PAYLOAD_BLOCKED: derived M5 record failed safety scan.")

    def _metadata_from_detail(
        self,
        detail: AnalyzeStoriesImportDetail,
        payload: dict[str, Any] | None,
    ) -> dict[str, str | None]:
        payload = payload or {}
        run_manifest = self._dict_at(payload, "run_manifest")
        metadata = self._dict_at(payload, "metadata")
        return {
            "analyzer_version": self._first_str(
                detail.manifest.analyzer_version,
                payload.get("analyzer_version"),
                run_manifest.get("analyzer_version"),
                metadata.get("analyzer_version"),
            ),
            "workflow_version": self._first_str(
                detail.manifest.workflow_version,
                payload.get("workflow_version"),
                run_manifest.get("workflow_version"),
                metadata.get("workflow_version"),
            ),
            "model": self._first_str(
                detail.manifest.model,
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

    def _get_story_report_ref(self, report_ref_id: str) -> StoryAnalysisReportRef:
        for item in self._read_list(self.analyze_import_service.report_refs_file):
            if item.get("story_analysis_report_ref_id") == report_ref_id:
                return StoryAnalysisReportRef(**item)
        raise StorageError(f"STORY_ANALYSIS_REPORT_REF_NOT_FOUND: {report_ref_id}")

    def _reliability_level(
        self,
        blocking: list[BundleValidationIssue],
        warnings: list[BundleValidationIssue],
        can_reference: bool,
        can_m6: bool,
    ) -> str:
        if blocking or not can_reference:
            return "blocked"
        if warnings and can_m6:
            return "validated_with_warnings"
        if warnings:
            return "provisional"
        return "stable"

    def _safe_input_title(self, title: str | None) -> tuple[str | None, int, bool]:
        if title is None:
            return None, 0, False
        length = len(title)
        raw_like = any(marker.lower() in title.lower() for marker in UNSAFE_VALUE_MARKERS)
        too_long = length > 120
        if raw_like or too_long:
            digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
            return f"[redacted input title; sha256={digest}; length={length}]", length, True
        return self._short(title, 120), length, False

    def _entry_summary(
        self,
        chapter_index: int | None,
        order: int,
        input_hash: str | None,
        warning_codes: list[str],
        blocking_codes: list[str],
    ) -> str:
        return (
            f"chapter_index={chapter_index}; order={order}; "
            f"hash={'present' if input_hash else 'missing'}; "
            f"blocking={len(blocking_codes)}; warnings={len(warning_codes)}."
        )

    def _manifest_summary(
        self,
        bundle_id: str | None,
        chapter_count: int,
        reliability: str,
        can_reference: bool,
        can_m6: bool,
        blocking_count: int,
        warning_count: int,
    ) -> str:
        return (
            f"Bundle {bundle_id or 'unknown'} checked with {chapter_count} chapters; "
            f"reliability={reliability}; reference={can_reference}; "
            f"m6_ready={can_m6}; blocking={blocking_count}; warnings={warning_count}."
        )

    def _issue(
        self,
        code: str,
        severity: str,
        field_path: str | None = None,
        *,
        chapter_index: int | None = None,
        artifact_id: str | None = None,
        safe_detail: str | None = None,
        blocks_reference: bool = False,
        blocks_m6_adapter: bool | None = None,
    ) -> BundleValidationIssue:
        if blocks_m6_adapter is None:
            blocks_m6_adapter = severity in {"warning", "blocking"}
        return BundleValidationIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            field_path=self._redacted_field_path(field_path) if field_path else None,
            chapter_index=chapter_index,
            artifact_id=artifact_id,
            safe_detail=self._short(safe_detail, 260) if safe_detail else None,
            blocks_reference=blocks_reference,
            blocks_m6_adapter=blocks_m6_adapter,
        )

    def _find_inventory(self, inventory_id: str | None) -> BundleChapterInventory | None:
        if not inventory_id:
            return None
        for item in self._read_list(self.inventories_file):
            if item.get("chapter_inventory_id") == inventory_id:
                return BundleChapterInventory(**item)
        return None

    def _find_fingerprint_audit(self, audit_id: str | None) -> BundleChapterFingerprintAudit | None:
        if not audit_id:
            return None
        for item in self._read_list(self.fingerprint_audits_file):
            if item.get("fingerprint_audit_id") == audit_id:
                return BundleChapterFingerprintAudit(**item)
        return None

    def _find_cross_ref_check(self, check_id: str | None) -> CrossChapterStateReferenceCheck | None:
        if not check_id:
            return None
        for item in self._read_list(self.cross_ref_checks_file):
            if item.get("cross_chapter_reference_check_id") == check_id:
                return CrossChapterStateReferenceCheck(**item)
        return None

    def _find_consistency_check(self, check_id: str | None) -> BundleFrameworkReportConsistencyCheck | None:
        if not check_id:
            return None
        for item in self._read_list(self.consistency_checks_file):
            if item.get("consistency_check_id") == check_id:
                return BundleFrameworkReportConsistencyCheck(**item)
        return None

    def _find_report(self, report_id: str | None) -> FullBookBundleValidationReport | None:
        if not report_id:
            return None
        for item in self._read_list(self.reports_file):
            if item.get("validation_report_id") == report_id:
                return FullBookBundleValidationReport(**item)
        return None

    def _get_manifest(self, bundle_manifest_id: str) -> FullBookBundleManifest:
        for item in self._read_list(self.manifests_file):
            if item.get("bundle_manifest_id") == bundle_manifest_id:
                return FullBookBundleManifest(**item)
        raise StorageError(f"FULL_BOOK_BUNDLE_NOT_FOUND: {bundle_manifest_id}")

    def _next_manifest_id(self) -> str:
        return f"full_book_bundle_manifest_{len(self._read_list(self.manifests_file)) + 1:03d}"

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        data = self.store.read_list(path)
        return [item for item in data if isinstance(item, dict)]

    def _replace_or_append(self, path: Path, key: str, key_value: str, item: dict[str, Any]) -> None:
        items = self._read_list(path)
        for index, existing in enumerate(items):
            if existing.get(key) == key_value:
                items[index] = item
                self.store.write(path, items)
                return
        items.append(item)
        self.store.write(path, items)

    def _walk_key_values(self, value: Any) -> list[tuple[str, Any]]:
        pairs: list[tuple[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    pairs.append((str(key), child))
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        return pairs

    def _dict_at(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        value = payload.get(key)
        return value if isinstance(value, dict) else {}

    def _first_present(self, *values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    def _first_str(self, *values: Any) -> str | None:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                return str(value)
        return None

    def _first_int(self, *values: Any) -> int | None:
        for value in values:
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                match = re.search(r"-?\d+", value)
                if match:
                    try:
                        return int(match.group(0))
                    except ValueError:
                        continue
        return None

    def _safe_str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        safe: list[str] = []
        for item in value:
            text = self._first_str(item)
            if text:
                safe.append(self._short(text, 80) or "")
        return [item for item in safe if item]

    def _short(self, value: str | None, limit: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    def _looks_like_hash(self, value: str | None) -> bool:
        return bool(value and re.fullmatch(r"[A-Fa-f0-9]{32,128}", value.strip()))

    def _looks_like_secret(self, value: str) -> bool:
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)

    def _normalize_key(self, key: str) -> str:
        return re.sub(r"[^a-z0-9]", "", key.lower())

    def _redacted_field_path(self, field_path: str | None) -> str | None:
        if not field_path:
            return None
        parts = []
        for part in field_path.split("."):
            normalized = self._normalize_key(part)
            if normalized in UNSAFE_NORMALIZED_KEYS or normalized in UNSAFE_TEXT_FIELD_KEYS:
                parts.append("[redacted]")
            else:
                parts.append(self._short(part, 80) or "")
        return ".".join(parts)
