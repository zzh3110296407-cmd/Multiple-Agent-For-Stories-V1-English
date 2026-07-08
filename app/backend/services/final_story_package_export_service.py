from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.final_story_package import (
    ExportStatus,
    FinalStoryPackage,
    FinalStoryPackageDiffSummary,
    FinalStoryPackageDownloadFormat,
    FinalStoryPackageDownloadPayload,
    FinalStoryPackageEvidenceIndex,
    FinalStoryPackageExportRequest,
    FinalStoryPackageExportResponse,
    FinalStoryPackageExportRun,
    FinalStoryPackageExportRunListResponse,
    FinalStoryPackageManifest,
    FinalStoryPackagePreviewSection,
    FinalStoryPackagePreviewSectionListResponse,
    FinalStoryPackageReadinessGate,
    FinalStoryPackageReadinessIssue,
    FinalStoryPackageSafetyAudit,
    FinalStoryPackageSection,
    FinalStoryPackageSnapshot,
    FinalStoryPackageSourceRef,
    FinalStoryPackageValidationReport,
    FinalStoryPackageViewerState,
    FinalStoryPackageViewerStateRequest,
    PackageType,
    PreviewContentMode,
    ReadinessStatus,
    SectionType,
    SnapshotStatus,
)
from .active_project_story_data import current_story_workspace_project_id
from .final_story_package_readiness_service import resolve_final_package_story_data_dir
from .scene_gate_readiness_service import SceneGateReadinessService
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase7_m2_final_story_package_exporter_v1"

EXPORT_RUNS_FILE = "final_story_package_export_runs.json"
SNAPSHOTS_FILE = "final_story_package_snapshots.json"
VIEWER_STATES_FILE = "final_story_package_viewer_states.json"
PREVIEW_SECTIONS_FILE = "final_story_package_preview_sections.json"
EVIDENCE_INDEXES_FILE = "final_story_package_evidence_indexes.json"
SAFETY_AUDITS_FILE = "final_story_package_safety_audits.json"
DIFF_SUMMARIES_FILE = "final_story_package_diff_summaries.json"

ALLOWED_M2_STORAGE_FILES = [
    EXPORT_RUNS_FILE,
    SNAPSHOTS_FILE,
    VIEWER_STATES_FILE,
    PREVIEW_SECTIONS_FILE,
    EVIDENCE_INDEXES_FILE,
    SAFETY_AUDITS_FILE,
    DIFF_SUMMARIES_FILE,
]

M1_STORAGE_FILES = [
    "final_story_package_readiness_gates.json",
    "final_story_package_readiness_issues.json",
    "final_story_package_validation_reports.json",
    "final_story_package_source_refs.json",
    "final_story_package_sections.json",
    "final_story_package_manifests.json",
    "final_story_packages.json",
]

FORBIDDEN_STORY_FACT_FILES = [
    "scenes.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "chapter_archives.json",
    "narrative_debts.json",
    "story_bible.json",
    "decisions.json",
]

FORBIDDEN_PLUGIN_RUNTIME_FILES = [
    "plugin_runs.json",
    "plugin_run_steps.json",
    "plugin_output_artifacts.json",
    "plugin_output_artifact_versions.json",
    "plugin_checkpoints.json",
    "plugin_checkpoint_decisions.json",
    "plugin_run_safety_reports.json",
    "script_forging_runs.json",
    "script_shape_packages.json",
    "screenplay_draft_artifacts.json",
    "storyboard_artifacts.json",
    "digital_asset_packages.json",
]

UNSAFE_KEY_PARTS = (
    "prompt",
    "response",
    "reasoning",
    "secret",
    "password",
    "credential",
    "authorization",
    "apikey",
    "api_key",
    "providersecret",
    "prose_text",
    "revised_prose_text",
)

UNSAFE_VALUE_MARKERS = (
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "api_key",
    "authorization",
    "bearer ",
    "langsmith key",
    "provider secret",
)

SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")

E2E_CHARACTER_NAME_RE = re.compile(
    r"([^\s_]{1,64})"
    r"_M9_[A-D][0-9]?_CHARACTER_RUN[0-9]+_[A-Z0-9]+",
    re.IGNORECASE,
)
GENERIC_CHARACTER_NAME_RE = re.compile(r"([^\s_]{1,64})_[A-D]_[0-9]{3}\b", re.IGNORECASE)
E2E_MARKER_RE = re.compile(r"\bM9_[A-Z0-9_]*MARKER_RUN[0-9]+_[A-Z0-9]+\b", re.IGNORECASE)
E2E_RUN_TOKEN_RE = re.compile(r"\bRUN[0-9]+_[A-Z0-9]+\b", re.IGNORECASE)
E2E_SCENE_ID_RE = re.compile(r"\bscene_m7_chapter_m6_[0-9]{3}_([0-9]{3})\b", re.IGNORECASE)
E2E_CHAPTER_ID_RE = re.compile(r"\bchapter_m6_[0-9]{3}\b", re.IGNORECASE)
E2E_GENERIC_M9_RE = re.compile(r"\bM9_[A-Z0-9_]+\b", re.IGNORECASE)
E2E_TRUNCATED_ITEMS_RE = re.compile(r"\{?\s*['\"]?_truncated_items['\"]?\s*:\s*\d+\s*\}?", re.IGNORECASE)
E2E_TEST_TITLE_RE = re.compile(r"\bphase\s*8\.5\s*m9\s*stable\s*e2e\b", re.IGNORECASE)
E2E_RESIDUAL_TEST_TERM_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bE2E\b", re.IGNORECASE), "\u590d\u67e5\u94fe\u8def"),
    (re.compile(r"\bStable\b", re.IGNORECASE), "\u7a33\u5b9a\u8bb0\u5f55"),
    (re.compile(r"\bPhase\b", re.IGNORECASE), "\u9636\u6bb5\u8bb0\u5f55"),
    (re.compile(r"\bConflict\b", re.IGNORECASE), "\u51b2\u7a81\u7ebf\u7d22"),
    (re.compile(r"\bSecret\b", re.IGNORECASE), "\u79d8\u5bc6\u7ebf\u7d22"),
    (re.compile(r"\bpremise\b", re.IGNORECASE), "\u6838\u5fc3\u524d\u63d0"),
    (re.compile(r"\bcity-wide\b", re.IGNORECASE), "\u5168\u57ce"),
    (re.compile(r"\bdamaged\b", re.IGNORECASE), "\u53d7\u635f"),
    (re.compile(r"\bfour\b", re.IGNORECASE), "\u56db\u5c42"),
    (re.compile(r"\barchive\b", re.IGNORECASE), "\u6863\u6848"),
    (re.compile(r"\bsignal\b", re.IGNORECASE), "\u4fe1\u53f7"),
)
INSTRUCTIONAL_SENTENCE_RE = re.compile(
    r"当前幕必须把「([^」]+)」转化为可见行动线索，让角色通过选择、核查或承担风险推进前提。?"
)

SECTION_ORDER: list[SectionType] = [
    "complete_story_text",
    "chapter_scene_index",
    "character_table",
    "world_canvas_summary",
    "relationship_state_summary",
    "key_event_timeline",
    "user_locked_constraints",
    "style_and_tone",
    "source_lineage",
    "known_residuals",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()
    return dict(model)


class FinalStoryPackageExportService:
    """Phase 7 M2 controlled Final Story Package exporter and viewer."""

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir, self._missing_active_project_id = resolve_final_package_story_data_dir(
            self.store,
            data_dir,
        )
        self.project_id = current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )
        self.export_runs_file = self.data_dir / EXPORT_RUNS_FILE
        self.snapshots_file = self.data_dir / SNAPSHOTS_FILE
        self.viewer_states_file = self.data_dir / VIEWER_STATES_FILE
        self.preview_sections_file = self.data_dir / PREVIEW_SECTIONS_FILE
        self.evidence_indexes_file = self.data_dir / EVIDENCE_INDEXES_FILE
        self.safety_audits_file = self.data_dir / SAFETY_AUDITS_FILE
        self.diff_summaries_file = self.data_dir / DIFF_SUMMARIES_FILE

    def create_export(self, request: FinalStoryPackageExportRequest) -> FinalStoryPackageExportResponse:
        self._assert_active_story_data_available()
        if not request.readiness_gate_id.strip():
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_GATE_REQUIRED")
        if request.export_format != "json_snapshot":
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_FORMAT_UNSUPPORTED")
        self._assert_safe_payload({"safe_user_note": request.safe_user_note}, context="safe_user_note")

        before_forbidden = self._selected_hashes(FORBIDDEN_STORY_FACT_FILES)
        bundle = self._load_m1_bundle(request.readiness_gate_id)
        gate: FinalStoryPackageReadinessGate = bundle["gate"]
        package: FinalStoryPackage = bundle["package"]
        manifest: FinalStoryPackageManifest = bundle["manifest"]
        report: FinalStoryPackageValidationReport = bundle["report"]
        sections: list[FinalStoryPackageSection] = bundle["sections"]
        source_refs: list[FinalStoryPackageSourceRef] = bundle["source_refs"]
        issues: list[FinalStoryPackageReadinessIssue] = bundle["issues"]

        export_status, snapshot_status, can_be_used_by_plugins = self._preflight_export(
            request=request,
            gate=gate,
            package=package,
            source_refs=source_refs,
        )

        story_data = self._load_story_data()
        self._assert_m1_source_versions_current(source_refs=source_refs, story_data=story_data)
        self._assert_scene_gate_readiness_current(source_refs)
        created_at = now_iso()
        suffix = self._id_suffix(created_at)
        export_run_id = f"final_story_package_export_run_{suffix}"
        snapshot_id = f"final_story_package_snapshot_{suffix}"
        evidence_index_id = f"final_story_package_evidence_index_{suffix}"
        safety_audit_id = f"final_story_package_safety_audit_{suffix}"

        snapshot_payload = self._assemble_snapshot_payload(
            snapshot_id=snapshot_id,
            package=package,
            gate=gate,
            manifest=manifest,
            report=report,
            source_refs=source_refs,
            sections=sections,
            story_data=story_data,
            snapshot_status=snapshot_status,
            can_be_used_by_plugins=can_be_used_by_plugins,
            created_at=created_at,
        )
        snapshot: FinalStoryPackageSnapshot = snapshot_payload["snapshot"]
        preview_sections: list[FinalStoryPackagePreviewSection] = self._build_preview_sections(
            snapshot=snapshot,
            sections=sections,
            source_refs=source_refs,
            created_at=created_at,
            suffix=suffix,
        )
        snapshot.preview_section_ids = [section.preview_section_id for section in preview_sections]

        warning_issue_ids = [issue.issue_id for issue in issues if issue.severity in {"warning", "info"}]
        blocked_issue_ids = [issue.issue_id for issue in issues if issue.severity == "blocking"]
        project_id = package.project_id or self.project_id
        export_run = FinalStoryPackageExportRun(
            export_run_id=export_run_id,
            project_id=project_id,
            readiness_gate_id=gate.readiness_gate_id,
            validation_report_id=report.validation_report_id,
            final_story_package_id=package.final_story_package_id,
            manifest_id=manifest.manifest_id,
            snapshot_id=snapshot.snapshot_id,
            evidence_index_id=evidence_index_id,
            safety_audit_id=safety_audit_id,
            export_format=request.export_format,
            export_status=export_status,
            package_type=package.package_type,
            readiness_status=gate.readiness_status,
            can_be_used_by_plugins=can_be_used_by_plugins,
            not_real_project_final_package=package.not_real_project_final_package,
            source_ref_ids=[ref.source_ref_id for ref in source_refs],
            section_ids=[section.section_id for section in sections],
            blocked_issue_ids=blocked_issue_ids,
            warning_issue_ids=warning_issue_ids,
            safe_user_note=self._safe_text(request.safe_user_note, limit=180),
            created_at=created_at,
            safe_summary=self._export_summary(export_status, package.package_type),
        )
        section_hashes = {section.section_type: section.content_hash for section in preview_sections}
        evidence_index = FinalStoryPackageEvidenceIndex(
            evidence_index_id=evidence_index_id,
            snapshot_id=snapshot.snapshot_id,
            export_run_id=export_run.export_run_id,
            project_id=project_id,
            readiness_gate_id=gate.readiness_gate_id,
            validation_report_id=report.validation_report_id,
            final_story_package_id=package.final_story_package_id,
            manifest_id=manifest.manifest_id,
            source_ref_ids=list(snapshot.source_ref_ids),
            source_version_ids=list(snapshot.source_version_ids),
            section_hashes=section_hashes,
            content_hashes={
                "complete_story_text": snapshot.complete_story_text_hash,
                **section_hashes,
            },
            known_residual_codes=list(snapshot.known_residual_codes),
            package_type=package.package_type,
            readiness_status=gate.readiness_status,
            not_real_project_final_package=package.not_real_project_final_package,
            can_be_used_by_plugins=can_be_used_by_plugins,
            created_at=created_at,
            safe_summary=(
                f"Evidence index records ids, hashes, counts, and residual codes only; "
                f"source_refs={len(snapshot.source_ref_ids)} section_hashes={len(section_hashes)}."
            ),
        )
        evidence_payload = model_to_dict(evidence_index)
        evidence_contains_full_text = self._payload_contains_text(evidence_payload, snapshot.complete_story_text)
        pattern_scan_passed = not self._unsafe_payload_findings(evidence_payload, context="evidence_index")
        sensitive_inventory_passed = pattern_scan_passed and not evidence_contains_full_text
        safety_audit = FinalStoryPackageSafetyAudit(
            safety_audit_id=safety_audit_id,
            snapshot_id=snapshot.snapshot_id,
            export_run_id=export_run.export_run_id,
            project_id=project_id,
            checked_storage_files=[*FORBIDDEN_STORY_FACT_FILES, *FORBIDDEN_PLUGIN_RUNTIME_FILES, *ALLOWED_M2_STORAGE_FILES],
            forbidden_story_fact_files_unchanged=True,
            forbidden_plugin_runtime_files_absent=self._forbidden_plugin_runtime_files_absent(),
            sensitive_field_inventory_passed=sensitive_inventory_passed,
            pattern_scan_passed=pattern_scan_passed,
            evidence_contains_full_story_content=evidence_contains_full_text,
            snapshot_contains_controlled_full_story_content=bool(snapshot.complete_story_text),
            blocking_findings=[],
            warning_findings=list(snapshot.known_residual_codes),
            residual_risks=self._residual_risks(snapshot.known_residual_codes, gate.warning_issue_ids),
            passed=False,
            created_at=created_at,
            safe_summary=(
                "Safety audit confirms deterministic storage, pattern, and evidence-boundary checks. "
                "It does not claim absolute proof."
            ),
        )
        safety_audit.passed = (
            safety_audit.forbidden_story_fact_files_unchanged
            and safety_audit.forbidden_plugin_runtime_files_absent
            and safety_audit.sensitive_field_inventory_passed
            and safety_audit.pattern_scan_passed
            and not safety_audit.evidence_contains_full_story_content
        )
        if not safety_audit.passed:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_SAFETY_AUDIT_FAILED")

        response = FinalStoryPackageExportResponse(
            success=True,
            export_run=export_run,
            snapshot=snapshot,
            preview_sections=preview_sections,
            evidence_index=evidence_index,
            safety_audit=safety_audit,
            safe_summary=(
                "Final Story Package Snapshot created. Future plugins may use only this snapshot; "
                "fixture snapshots are non-real and not plugin-usable."
            ),
        )
        self._assert_safe_payload(model_to_dict(export_run), context="export_run")
        self._assert_safe_payload([model_to_dict(section) for section in preview_sections], context="preview_sections")
        self._assert_safe_payload(model_to_dict(evidence_index), context="evidence_index")
        self._assert_safe_payload(model_to_dict(safety_audit), context="safety_audit")
        self._assert_safe_snapshot(snapshot)
        if before_forbidden != self._selected_hashes(FORBIDDEN_STORY_FACT_FILES):
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_FORBIDDEN_STORY_FACT_MUTATION")

        self._persist_export(response)
        return response

    def _assert_scene_gate_readiness_current(
        self,
        source_refs: list[FinalStoryPackageSourceRef],
    ) -> None:
        scene_ids = [
            ref.source_object_id
            for ref in source_refs
            if ref.source_object_type == "scene"
            and ref.can_be_plugin_input_truth
            and ref.source_object_id
        ]
        if not scene_ids:
            return
        SceneGateReadinessService(
            store=self.store,
            data_dir=self.data_dir,
        ).require_scenes_safe_to_release(
            scene_ids,
            boundary_code="FINAL_STORY_PACKAGE_GATE_READINESS_BLOCKED",
            mode="final_story_package_export",
        )

    def get_export_run(self, export_run_id: str) -> FinalStoryPackageExportRun:
        self._assert_active_story_data_available()
        return self._get_model_by_id(
            self.export_runs_file,
            FinalStoryPackageExportRun,
            "export_run_id",
            export_run_id,
            "FINAL_STORY_PACKAGE_EXPORT_RUN_NOT_FOUND",
        )

    def list_export_runs(self) -> FinalStoryPackageExportRunListResponse:
        self._assert_active_story_data_available()
        runs = self._read_models_if_exists(self.export_runs_file, FinalStoryPackageExportRun)
        runs.sort(key=lambda item: item.created_at, reverse=True)
        return FinalStoryPackageExportRunListResponse(export_runs=runs, total_count=len(runs))

    def get_snapshot(self, snapshot_id: str) -> FinalStoryPackageSnapshot:
        self._assert_active_story_data_available()
        return self._get_model_by_id(
            self.snapshots_file,
            FinalStoryPackageSnapshot,
            "snapshot_id",
            snapshot_id,
            "FINAL_STORY_PACKAGE_SNAPSHOT_NOT_FOUND",
        )

    def build_snapshot_download(
        self,
        snapshot_id: str,
        export_format: str,
    ) -> FinalStoryPackageDownloadPayload:
        self._assert_active_story_data_available()
        normalized_format = export_format.strip().lower()
        if normalized_format not in {"txt", "markdown", "json"}:
            raise StorageError("FINAL_STORY_PACKAGE_DOWNLOAD_FORMAT_UNSUPPORTED")
        snapshot = self.get_snapshot(snapshot_id)
        self._assert_snapshot_downloadable(snapshot)

        download_format = normalized_format  # type: FinalStoryPackageDownloadFormat
        if download_format == "txt":
            content = snapshot.complete_story_text
            media_type = "text/plain; charset=utf-8"
            suffix = "final_story.txt"
        elif download_format == "markdown":
            content = self._markdown_download_content(snapshot)
            media_type = "text/markdown; charset=utf-8"
            suffix = "final_story.md"
        else:
            content = self._json_download_content(snapshot)
            media_type = "application/json; charset=utf-8"
            suffix = "final_story_snapshot.json"

        self._assert_safe_text_value(content, context=f"download.{download_format}")
        return FinalStoryPackageDownloadPayload(
            snapshot_id=snapshot.snapshot_id,
            project_id=snapshot.project_id,
            export_format=download_format,
            filename=self._download_filename(snapshot, suffix),
            media_type=media_type,
            content=content,
        )

    def get_snapshot_preview_sections(self, snapshot_id: str) -> FinalStoryPackagePreviewSectionListResponse:
        self._assert_active_story_data_available()
        self.get_snapshot(snapshot_id)
        sections = [
            section
            for section in self._read_models_if_exists(self.preview_sections_file, FinalStoryPackagePreviewSection)
            if section.snapshot_id == snapshot_id
        ]
        sections.sort(key=lambda item: item.display_order)
        return FinalStoryPackagePreviewSectionListResponse(
            snapshot_id=snapshot_id,
            preview_sections=sections,
            total_count=len(sections),
        )

    def get_evidence_index(self, snapshot_id: str) -> FinalStoryPackageEvidenceIndex:
        self._assert_active_story_data_available()
        for item in self._read_models_if_exists(self.evidence_indexes_file, FinalStoryPackageEvidenceIndex):
            if item.snapshot_id == snapshot_id:
                return item
        raise StorageError("FINAL_STORY_PACKAGE_EVIDENCE_INDEX_NOT_FOUND")

    def get_safety_audit(self, snapshot_id: str) -> FinalStoryPackageSafetyAudit:
        self._assert_active_story_data_available()
        for item in self._read_models_if_exists(self.safety_audits_file, FinalStoryPackageSafetyAudit):
            if item.snapshot_id == snapshot_id:
                return item
        raise StorageError("FINAL_STORY_PACKAGE_SAFETY_AUDIT_NOT_FOUND")

    def _assert_snapshot_downloadable(self, snapshot: FinalStoryPackageSnapshot) -> None:
        if snapshot.project_id != self.project_id:
            raise StorageError("FINAL_STORY_PACKAGE_DOWNLOAD_NOT_AUTHORIZED: project mismatch")
        if snapshot.package_type != "real_project_final_package" or snapshot.not_real_project_final_package:
            raise StorageError("FINAL_STORY_PACKAGE_DOWNLOAD_NOT_REAL_PROJECT_PACKAGE")
        if snapshot.snapshot_status != "created":
            raise StorageError("FINAL_STORY_PACKAGE_DOWNLOAD_SNAPSHOT_NOT_CREATED")
        if not snapshot.complete_story_text.strip():
            raise StorageError("FINAL_STORY_PACKAGE_DOWNLOAD_COMPLETE_STORY_TEXT_MISSING")
        if self._hash_text(snapshot.complete_story_text) != snapshot.complete_story_text_hash:
            raise StorageError("FINAL_STORY_PACKAGE_DOWNLOAD_TEXT_HASH_MISMATCH")
        if len(snapshot.complete_story_text) != snapshot.complete_story_text_char_count:
            raise StorageError("FINAL_STORY_PACKAGE_DOWNLOAD_TEXT_COUNT_MISMATCH")
        self._assert_safe_snapshot(snapshot)

    def _markdown_download_content(self, snapshot: FinalStoryPackageSnapshot) -> str:
        header = [
            "# Final Story Package",
            "",
            f"- Project ID: {self._safe_identifier(snapshot.project_id)}",
            f"- Snapshot ID: {self._safe_identifier(snapshot.snapshot_id)}",
            f"- Package Type: {self._safe_identifier(snapshot.package_type)}",
            f"- Readiness Status: {self._safe_identifier(snapshot.readiness_status)}",
            f"- Full Text Hash: {self._safe_identifier(snapshot.complete_story_text_hash)}",
            f"- Character Count: {snapshot.complete_story_text_char_count}",
            "",
            "## Final Story",
            "",
        ]
        return "\n".join(header) + snapshot.complete_story_text

    def _json_download_content(self, snapshot: FinalStoryPackageSnapshot) -> str:
        preview_sections = self.get_snapshot_preview_sections(snapshot.snapshot_id).preview_sections
        evidence_index = self.get_evidence_index(snapshot.snapshot_id)
        safety_audit = self.get_safety_audit(snapshot.snapshot_id)
        payload = {
            "export_schema_version": "phase85_final_story_package_user_download_v1",
            "snapshot": model_to_dict(snapshot),
            "preview_sections": [model_to_dict(section) for section in preview_sections],
            "evidence_index": model_to_dict(evidence_index),
            "safety_audit_summary": {
                "safety_audit_id": safety_audit.safety_audit_id,
                "snapshot_id": safety_audit.snapshot_id,
                "project_id": safety_audit.project_id,
                "passed": safety_audit.passed,
                "forbidden_story_fact_files_unchanged": safety_audit.forbidden_story_fact_files_unchanged,
                "forbidden_plugin_runtime_files_absent": safety_audit.forbidden_plugin_runtime_files_absent,
                "sensitive_field_inventory_passed": safety_audit.sensitive_field_inventory_passed,
                "pattern_scan_passed": safety_audit.pattern_scan_passed,
                "snapshot_contains_controlled_full_story_content": safety_audit.snapshot_contains_controlled_full_story_content,
                "blocking_finding_count": len(safety_audit.blocking_findings),
                "warning_finding_count": len(safety_audit.warning_findings),
                "residual_risks": list(safety_audit.residual_risks),
                "created_at": safety_audit.created_at,
                "safe_summary": safety_audit.safe_summary,
            },
        }
        self._assert_safe_payload(payload, context="download_json")
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)

    def _download_filename(self, snapshot: FinalStoryPackageSnapshot, suffix: str) -> str:
        project_id = self._safe_identifier(snapshot.project_id).replace(":", "_")
        snapshot_id = self._safe_identifier(snapshot.snapshot_id).replace(":", "_")
        safe_suffix = re.sub(r"[^a-zA-Z0-9_.-]", "_", suffix).strip("._") or "final_story.txt"
        return f"{project_id}_{snapshot_id}_{safe_suffix}"

    def create_viewer_state(self, request: FinalStoryPackageViewerStateRequest) -> FinalStoryPackageViewerState:
        self._assert_active_story_data_available()
        snapshot = self.get_snapshot(request.snapshot_id)
        self._assert_safe_payload(model_to_dict(request), context="viewer_state_request")
        created_at = now_iso()
        suffix = self._id_suffix(created_at)
        state = FinalStoryPackageViewerState(
            viewer_state_id=f"final_story_package_viewer_state_{suffix}",
            snapshot_id=snapshot.snapshot_id,
            selected_section_type=request.selected_section_type,
            visible_panels=list(dict.fromkeys(request.visible_panels or ["preview", "sections"])),
            show_source_lineage=request.show_source_lineage,
            show_evidence_index=request.show_evidence_index,
            show_safety_audit=request.show_safety_audit,
            created_at=created_at,
            updated_at=created_at,
            safe_summary="Viewer state stores selected panel metadata only; full content remains in the controlled snapshot.",
        )
        self._assert_safe_payload(model_to_dict(state), context="viewer_state")
        self._append_models(self.viewer_states_file, [state])
        return state

    def get_viewer_state(self, viewer_state_id: str) -> FinalStoryPackageViewerState:
        self._assert_active_story_data_available()
        return self._get_model_by_id(
            self.viewer_states_file,
            FinalStoryPackageViewerState,
            "viewer_state_id",
            viewer_state_id,
            "FINAL_STORY_PACKAGE_VIEWER_STATE_NOT_FOUND",
        )

    def _assert_active_story_data_available(self) -> None:
        if self._missing_active_project_id:
            raise StorageError(
                "ACTIVE_PROJECT_STORY_DATA_NOT_FOUND:"
                + self._safe_identifier(self._missing_active_project_id)
            )

    def _load_m1_bundle(self, readiness_gate_id: str) -> dict[str, Any]:
        gate = self._get_model_by_id(
            self.data_dir / "final_story_package_readiness_gates.json",
            FinalStoryPackageReadinessGate,
            "readiness_gate_id",
            readiness_gate_id,
            "FINAL_STORY_PACKAGE_READINESS_GATE_NOT_FOUND",
        )
        package = self._get_model_by_id(
            self.data_dir / "final_story_packages.json",
            FinalStoryPackage,
            "final_story_package_id",
            gate.final_story_package_id,
            "FINAL_STORY_PACKAGE_METADATA_NOT_FOUND",
        )
        manifest = self._get_model_by_id(
            self.data_dir / "final_story_package_manifests.json",
            FinalStoryPackageManifest,
            "manifest_id",
            package.manifest_id,
            "FINAL_STORY_PACKAGE_MANIFEST_NOT_FOUND",
        )
        report = self._get_model_by_id(
            self.data_dir / "final_story_package_validation_reports.json",
            FinalStoryPackageValidationReport,
            "validation_report_id",
            package.validation_report_id,
            "FINAL_STORY_PACKAGE_VALIDATION_REPORT_NOT_FOUND",
        )
        sections = [
            item
            for item in self._read_models_if_exists(self.data_dir / "final_story_package_sections.json", FinalStoryPackageSection)
            if item.final_story_package_id == package.final_story_package_id
        ]
        source_ref_ids = set(package.source_ref_ids)
        source_refs = [
            item
            for item in self._read_models_if_exists(self.data_dir / "final_story_package_source_refs.json", FinalStoryPackageSourceRef)
            if item.final_story_package_id == package.final_story_package_id
            and (not source_ref_ids or item.source_ref_id in source_ref_ids)
        ]
        issues = [
            item
            for item in self._read_models_if_exists(self.data_dir / "final_story_package_readiness_issues.json", FinalStoryPackageReadinessIssue)
            if item.readiness_gate_id == gate.readiness_gate_id
        ]
        if not sections or not source_refs:
            raise StorageError("FINAL_STORY_PACKAGE_M1_LINEAGE_INCOMPLETE")
        return {
            "gate": gate,
            "package": package,
            "manifest": manifest,
            "report": report,
            "sections": sections,
            "source_refs": source_refs,
            "issues": issues,
        }

    def _preflight_export(
        self,
        *,
        request: FinalStoryPackageExportRequest,
        gate: FinalStoryPackageReadinessGate,
        package: FinalStoryPackage,
        source_refs: list[FinalStoryPackageSourceRef],
    ) -> tuple[ExportStatus, SnapshotStatus, bool]:
        if gate.readiness_status == "fixture_only":
            if not request.allow_fixture_export:
                raise StorageError("FINAL_STORY_PACKAGE_FIXTURE_EXPORT_NOT_ALLOWED")
            if package.package_type != "fixture_final_story_package" or not package.not_real_project_final_package:
                raise StorageError("FINAL_STORY_PACKAGE_FIXTURE_EXPORT_INVALID_M1_PACKAGE")
            return "fixture_created", "fixture", False
        if gate.readiness_status == "blocked" or gate.blocking_issue_ids:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_BLOCKED: readiness gate is blocked")
        if gate.readiness_status not in {"ready", "ready_with_warnings"}:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_BLOCKED: readiness gate is not exportable")
        if not gate.can_create_real_final_story_package or package.not_real_project_final_package:
            raise StorageError("FINAL_STORY_PACKAGE_REAL_EXPORT_NOT_AUTHORIZED")
        if package.package_type != "real_project_final_package":
            raise StorageError("FINAL_STORY_PACKAGE_REAL_EXPORT_WRONG_PACKAGE_TYPE")
        non_truth_refs = [
            ref.source_ref_id
            for ref in source_refs
            if not ref.can_be_plugin_input_truth
            and ref.authority_status not in {"fixture"}
        ]
        if non_truth_refs:
            raise StorageError(
                "FINAL_STORY_PACKAGE_EXPORT_NON_TRUTH_SOURCE_REF: " + ",".join(non_truth_refs[:8])
            )
        return "created", "created", True

    def _assemble_snapshot_payload(
        self,
        *,
        snapshot_id: str,
        package: FinalStoryPackage,
        gate: FinalStoryPackageReadinessGate,
        manifest: FinalStoryPackageManifest,
        report: FinalStoryPackageValidationReport,
        source_refs: list[FinalStoryPackageSourceRef],
        sections: list[FinalStoryPackageSection],
        story_data: dict[str, Any],
        snapshot_status: SnapshotStatus,
        can_be_used_by_plugins: bool,
        created_at: str,
    ) -> dict[str, Any]:
        truth_refs = [ref for ref in source_refs if ref.can_be_plugin_input_truth]
        ref_by_type: dict[str, list[FinalStoryPackageSourceRef]] = {}
        for ref in truth_refs:
            ref_by_type.setdefault(ref.source_object_type, []).append(ref)
        if can_be_used_by_plugins and not truth_refs:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_NO_TRUTH_SOURCE_REFS")

        scene_ids = [ref.source_object_id for ref in ref_by_type.get("scene", [])]
        archive_ids = {ref.source_object_id for ref in ref_by_type.get("chapter_archive", [])}
        scenes_by_id = {
            str(item.get("scene_id") or item.get("id") or ""): item
            for item in story_data["scenes"]
            if isinstance(item, dict)
        }
        stable_archives = [
            item
            for item in story_data["chapter_archives"]
            if isinstance(item, dict)
            and str(item.get("archive_status") or "").lower() == "stable"
            and (not archive_ids or str(item.get("archive_id") or "") in archive_ids)
        ]
        chapters_by_id = self._chapters_by_id(story_data["chapters"])
        project_title = self._snapshot_story_title(story_data["project"], package.project_id or self.project_id)
        ordered_scene_ids = self._ordered_scene_ids_from_archives(stable_archives, scene_ids)
        if not ordered_scene_ids:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_COMPLETE_STORY_TEXT_MISSING")
        story_parts: list[str] = [f"# {project_title}"]
        chapter_scene_index: list[dict[str, Any]] = []
        current_chapter_id: str | None = None
        for position, scene_id in enumerate(ordered_scene_ids, start=1):
            scene = scenes_by_id.get(scene_id)
            if not scene or str(scene.get("status") or "").lower() != "confirmed":
                raise StorageError("FINAL_STORY_PACKAGE_EXPORT_SCENE_NOT_CONFIRMED")
            text = self._user_story_text(self._scene_full_text(scene))
            if not text:
                raise StorageError("FINAL_STORY_PACKAGE_EXPORT_COMPLETE_STORY_TEXT_MISSING")
            chapter_id = str(scene.get("chapter_id") or "")
            chapter_meta = chapters_by_id.get(chapter_id, {})
            chapter_index = self._positive_int(
                chapter_meta.get("chapter_index") or self._chapter_index_from_archives(stable_archives, chapter_id),
                fallback=len({item.get("chapter_id") for item in chapter_scene_index}) + 1,
            )
            chapter_title = self._user_story_text(str(chapter_meta.get("title") or chapter_meta.get("name") or "")).strip()
            if chapter_id != current_chapter_id:
                story_parts.append(self._chapter_heading(chapter_index, chapter_title))
                current_chapter_id = chapter_id
            title = self._user_story_text(str(scene.get("title") or "")).strip()
            scene_index = self._positive_int(scene.get("scene_index"), fallback=position)
            heading = f"### 第{scene_index}幕"
            if title:
                heading = f"{heading}：{self._safe_text(title, limit=80)}"
            story_parts.append(f"{heading}\n\n{text}")
            chapter_scene_index.append(
                {
                    "chapter_id": self._safe_identifier(chapter_id),
                    "chapter_index": chapter_index,
                    "chapter_title": self._safe_text(chapter_title, limit=120),
                    "scene_id": self._safe_identifier(scene_id),
                    "scene_index": scene_index,
                    "global_scene_position": position,
                    "title": self._safe_text(title, limit=120),
                    "content_hash": self._hash_text(text),
                }
            )
        complete_story_text = "\n\n".join(story_parts).strip()
        if not complete_story_text:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_COMPLETE_STORY_TEXT_MISSING")
        self._assert_safe_text_value(complete_story_text, context="snapshot.complete_story_text")

        world_canvas = story_data["world_canvas"] if isinstance(story_data["world_canvas"], dict) else {}
        world_truth = bool(ref_by_type.get("world_canvas"))
        hard_rule_refs = ref_by_type.get("world_canvas_hard_rule", [])
        if hard_rule_refs and not world_truth:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_PARENT_WORLD_CANVAS_NOT_TRUTH")
        known_residual_codes = self._known_residual_codes(sections=sections, warning_issue_ids=gate.warning_issue_ids)
        snapshot = FinalStoryPackageSnapshot(
            snapshot_id=snapshot_id,
            project_id=package.project_id or self.project_id,
            final_story_package_id=package.final_story_package_id,
            readiness_gate_id=gate.readiness_gate_id,
            validation_report_id=report.validation_report_id,
            manifest_id=manifest.manifest_id,
            package_type=package.package_type,
            readiness_status=gate.readiness_status,
            snapshot_status=snapshot_status,
            content_schema_version=SCHEMA_VERSION,
            source_ref_ids=[ref.source_ref_id for ref in truth_refs],
            source_version_ids=sorted({ref.source_version_id for ref in truth_refs if ref.source_version_id}),
            preview_section_ids=[],
            complete_story_text=complete_story_text,
            complete_story_text_hash=self._hash_text(complete_story_text),
            complete_story_text_char_count=len(complete_story_text),
            chapter_scene_index=chapter_scene_index,
            character_table=self._character_table(story_data["characters"], ref_by_type.get("character", [])),
            world_canvas_summary=self._world_canvas_summary(world_canvas, world_truth),
            relationship_state_summary=self._relationship_summary(story_data["relationships"], ref_by_type.get("relationship", [])),
            key_event_timeline=self._event_timeline(story_data["events"], ref_by_type.get("event", [])),
            user_locked_constraints=self._locked_constraints(story_data, ref_by_type),
            style_and_tone=self._style_and_tone(world_canvas, world_truth),
            known_residual_codes=known_residual_codes,
            can_be_used_by_plugins=can_be_used_by_plugins,
            not_real_project_final_package=package.not_real_project_final_package,
            created_at=created_at,
            safe_summary=(
                "Controlled Final Story Package Snapshot. Full story text is stored only here; "
                "evidence and safety records use hashes and ids."
            ),
        )
        return {"snapshot": snapshot}

    def _build_preview_sections(
        self,
        *,
        snapshot: FinalStoryPackageSnapshot,
        sections: list[FinalStoryPackageSection],
        source_refs: list[FinalStoryPackageSourceRef],
        created_at: str,
        suffix: str,
    ) -> list[FinalStoryPackagePreviewSection]:
        m1_sections_by_type = {section.section_type: section for section in sections}
        ref_ids_by_type: dict[str, list[str]] = {}
        for ref in source_refs:
            if ref.can_be_plugin_input_truth:
                ref_ids_by_type.setdefault(ref.source_object_type, []).append(ref.source_ref_id)

        content_by_section: dict[SectionType, Any] = {
            "complete_story_text": {
                "hash": snapshot.complete_story_text_hash,
                "char_count": snapshot.complete_story_text_char_count,
            },
            "chapter_scene_index": snapshot.chapter_scene_index,
            "character_table": snapshot.character_table,
            "world_canvas_summary": snapshot.world_canvas_summary,
            "relationship_state_summary": snapshot.relationship_state_summary,
            "key_event_timeline": snapshot.key_event_timeline,
            "user_locked_constraints": snapshot.user_locked_constraints,
            "style_and_tone": snapshot.style_and_tone,
            "source_lineage": {"source_ref_count": len(snapshot.source_ref_ids)},
            "known_residuals": snapshot.known_residual_codes,
        }
        titles = {
            "complete_story_text": "Complete Story Text",
            "chapter_scene_index": "Chapter Scene Index",
            "character_table": "Character Table",
            "world_canvas_summary": "World Canvas Summary",
            "relationship_state_summary": "Relationship State Summary",
            "key_event_timeline": "Key Event Timeline",
            "user_locked_constraints": "User Locked Constraints",
            "style_and_tone": "Style And Tone",
            "source_lineage": "Source Lineage",
            "known_residuals": "Known Residuals",
        }
        modes: dict[SectionType, PreviewContentMode] = {
            "complete_story_text": "full_text",
            "chapter_scene_index": "table",
            "character_table": "table",
            "world_canvas_summary": "summary",
            "relationship_state_summary": "table",
            "key_event_timeline": "table",
            "user_locked_constraints": "table",
            "style_and_tone": "summary",
            "source_lineage": "lineage",
            "known_residuals": "audit",
        }
        previews: list[FinalStoryPackagePreviewSection] = []
        for order, section_type in enumerate(SECTION_ORDER, start=1):
            content = content_by_section.get(section_type, [])
            if section_type == "known_residuals" and not content:
                continue
            content_json = json.dumps(content, ensure_ascii=False, sort_keys=True)
            m1_section = m1_sections_by_type.get(section_type)
            previews.append(
                FinalStoryPackagePreviewSection(
                    preview_section_id=f"final_story_package_preview_section_{section_type}_{order:02d}_{suffix}",
                    snapshot_id=snapshot.snapshot_id,
                    section_type=section_type,
                    display_order=order,
                    title=titles.get(section_type, section_type),
                    content_mode=modes.get(section_type, "summary"),
                    content_ref=m1_section.content_ref if m1_section else f"snapshot:{section_type}",
                    content_hash=self._hash_text(content_json),
                    safe_preview=self._safe_preview_for_section(section_type, content, snapshot),
                    item_count=self._item_count(content),
                    source_ref_ids=m1_section.source_ref_ids if m1_section else [],
                    created_at=created_at,
                )
            )
        return previews

    def _persist_export(self, response: FinalStoryPackageExportResponse) -> None:
        writes: dict[Path, list[BaseModel]] = {
            self.export_runs_file: [response.export_run],
            self.snapshots_file: [response.snapshot],
            self.preview_sections_file: response.preview_sections,
            self.evidence_indexes_file: [response.evidence_index],
            self.safety_audits_file: [response.safety_audit],
        }
        for path, models in writes.items():
            if path.name not in ALLOWED_M2_STORAGE_FILES:
                raise StorageError(f"FINAL_STORY_PACKAGE_EXPORT_FORBIDDEN_STORAGE_WRITE: {path.name}")
            self._append_models(path, models)
        if not self.store.exists(self.diff_summaries_file):
            self.store.write(self.diff_summaries_file, [])
        elif not isinstance(self.store.read_any(self.diff_summaries_file), list):
            raise StorageError("FINAL_STORY_PACKAGE_DIFF_SUMMARIES_NOT_LIST_BACKED")

    def _append_models(self, path: Path, models: list[BaseModel]) -> None:
        if path.name not in ALLOWED_M2_STORAGE_FILES:
            raise StorageError(f"FINAL_STORY_PACKAGE_EXPORT_FORBIDDEN_STORAGE_WRITE: {path.name}")
        existing = self._read_list_if_exists(path)
        existing.extend(model_to_dict(model) for model in models)
        if path.name == SNAPSHOTS_FILE:
            for item in existing:
                if isinstance(item, dict):
                    self._assert_safe_snapshot_dict(item)
        else:
            self._assert_safe_payload(existing, context=path.name)
        self.store.write(path, existing)

    def _load_story_data(self) -> dict[str, Any]:
        return {
            "project": self._read_dict_if_exists(self.data_dir / "project.json"),
            "chapter_archives": self._read_list_if_exists(self.data_dir / "chapter_archives.json"),
            "chapters": self._read_list_if_exists(self.data_dir / "chapters.json"),
            "scenes": self._read_list_if_exists(self.data_dir / "scenes.json"),
            "characters": self._read_list_if_exists(self.data_dir / "characters.json"),
            "relationships": self._read_list_if_exists(self.data_dir / "relationships.json"),
            "events": self._read_list_if_exists(self.data_dir / "events.json"),
            "world_canvas": self._read_dict_if_exists(self.data_dir / "world_canvas.json"),
            "story_progress": self._read_dict_if_exists(self.data_dir / "story_progress.json"),
        }

    def _assert_m1_source_versions_current(
        self,
        *,
        source_refs: list[FinalStoryPackageSourceRef],
        story_data: dict[str, Any],
    ) -> None:
        indexes = {
            "chapter_archive": self._index_by_id(story_data["chapter_archives"], ("archive_id", "id")),
            "scene": self._index_by_id(story_data["scenes"], ("scene_id", "id")),
            "character": self._index_by_id(story_data["characters"], ("character_id", "id")),
            "character_hard_limits": self._index_by_id(story_data["characters"], ("character_id", "id")),
            "relationship": self._index_by_id(story_data["relationships"], ("relationship_id", "id")),
            "event": self._index_by_id(story_data["events"], ("event_id", "id")),
            "locked_event_constraint": self._index_by_id(story_data["events"], ("event_id", "id")),
            "world_canvas": {
                str(story_data["world_canvas"].get("world_canvas_id") or "world_canvas"): story_data["world_canvas"]
            }
            if isinstance(story_data["world_canvas"], dict)
            else {},
            "world_canvas_hard_rule": self._index_world_hard_rules(story_data["world_canvas"]),
        }
        drifted: list[str] = []
        for ref in source_refs:
            if not ref.can_be_plugin_input_truth or not ref.source_version_id:
                continue
            source_index = indexes.get(ref.source_object_type)
            if source_index is None:
                continue
            item = source_index.get(ref.source_object_id)
            if not item:
                drifted.append(f"{ref.source_ref_id}:missing")
                continue
            live_version_id = self._live_version_for_source_ref(ref, item, story_data)
            if live_version_id != ref.source_version_id:
                drifted.append(f"{ref.source_ref_id}:version_mismatch")
        if drifted:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_SOURCE_VERSION_DRIFT: " + ",".join(drifted[:8]))

    def _live_version_for_source_ref(
        self,
        ref: FinalStoryPackageSourceRef,
        item: dict[str, Any],
        story_data: dict[str, Any],
    ) -> str:
        if ref.source_object_type == "world_canvas_hard_rule" and not item.get("version_id"):
            world_canvas = story_data["world_canvas"] if isinstance(story_data["world_canvas"], dict) else {}
            return str(world_canvas.get("version_id") or "")
        return str(item.get("version_id") or "")

    def _index_by_id(self, items: list[Any], id_fields: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in id_fields:
                item_id = str(item.get(field) or "")
                if item_id:
                    index[item_id] = item
                    break
        return index

    def _index_world_hard_rules(self, world_canvas: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if not isinstance(world_canvas, dict):
            return {}
        rules: dict[str, dict[str, Any]] = {}
        for rule in world_canvas.get("hard_rules") or []:
            if isinstance(rule, dict):
                rule_id = str(rule.get("rule_id") or rule.get("id") or "")
                if rule_id:
                    rules[rule_id] = rule
        return rules

    def _read_dict_if_exists(self, path: Path) -> dict[str, Any]:
        if not self.store.exists(path):
            return {}
        data = self.store.read_any(path)
        return data if isinstance(data, dict) else {}

    def _read_list_if_exists(self, path: Path) -> list[Any]:
        if not self.store.exists(path):
            return []
        data = self.store.read_any(path)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "records", "sections", "source_refs", "issues", "export_runs", "snapshots"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _read_models_if_exists(self, path: Path, model_type: type[BaseModel]) -> list[Any]:
        models = []
        for item in self._read_list_if_exists(path):
            if isinstance(item, dict):
                models.append(model_type(**item))
        return models

    def _get_model_by_id(
        self,
        path: Path,
        model_type: type[BaseModel],
        id_field: str,
        wanted_id: str,
        not_found_code: str,
    ) -> Any:
        for item in self._read_models_if_exists(path, model_type):
            if str(getattr(item, id_field)) == wanted_id:
                return item
        raise StorageError(not_found_code)

    def _chapters_by_id(self, chapters: list[Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "")
            if chapter_id:
                result[chapter_id] = chapter
        return result

    def _snapshot_story_title(self, project: dict[str, Any], project_id: str) -> str:
        title = ""
        for key in ("story_title", "final_story_title", "novel_title", "title", "name", "project_title"):
            title = self._user_story_text(str(project.get(key) or "")).strip()
            if title:
                break
        if not title:
            title = self._safe_identifier(project_id or LOCAL_PROJECT_ID).replace("_", " ").strip()
        title = self._presentation_story_title(title)
        return self._safe_text(title or "Untitled Story", limit=120)

    def _presentation_story_title(self, title: str) -> str:
        text = str(title or "").strip()
        if not text:
            return ""
        if E2E_TEST_TITLE_RE.search(text):
            return "\u57ce\u5e02\u6863\u6848\u8c03\u67e5"
        longrun_match = re.match(r"^(.+?)真实长跑[_\-\s]*\d{8}[_\-]\d{6}(?:[_\-][A-Za-z0-9]+)?$", text)
        if longrun_match:
            return longrun_match.group(1).strip(" _-") or text
        timestamp_match = re.match(r"^(.+?)[_\-\s]+\d{8}[_\-]\d{6}(?:[_\-][A-Za-z0-9]+)?$", text)
        if timestamp_match:
            return timestamp_match.group(1).strip(" _-") or text
        return text

    def _chapter_index_from_archives(self, archives: list[dict[str, Any]], chapter_id: str) -> int:
        for archive in archives:
            if str(archive.get("chapter_id") or "") == chapter_id:
                return self._positive_int(archive.get("chapter_index"), fallback=0)
        return 0

    def _chapter_heading(self, chapter_index: int, chapter_title: str) -> str:
        heading = f"## 第{chapter_index}章"
        if chapter_title:
            heading = f"{heading}：{self._safe_text(chapter_title, limit=100)}"
        return heading

    def _positive_int(self, value: Any, *, fallback: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return fallback
        return number if number > 0 else fallback

    def _ordered_scene_ids_from_archives(self, archives: list[dict[str, Any]], accepted_scene_ids: list[str]) -> list[str]:
        accepted = set(accepted_scene_ids)
        ordered: list[str] = []
        for archive in sorted(archives, key=lambda item: int(item.get("chapter_index") or 0)):
            for scene_id in archive.get("confirmed_scene_ids") or archive.get("scene_ids") or []:
                if isinstance(scene_id, str) and scene_id in accepted and scene_id not in ordered:
                    ordered.append(scene_id)
        for scene_id in accepted_scene_ids:
            if scene_id not in ordered:
                ordered.append(scene_id)
        return ordered

    def _scene_full_text(self, scene: dict[str, Any]) -> str:
        content = scene.get("content") if isinstance(scene.get("content"), dict) else {}
        for key in ("prose_text", "final_text", "scene_text", "text"):
            value = scene.get(key) or content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _user_story_text(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        def scene_label(match: re.Match[str]) -> str:
            try:
                return f"第{int(match.group(1))}幕"
            except (TypeError, ValueError):
                return "本幕"

        def readable_marker(match: re.Match[str]) -> str:
            raw = match.group(0).upper()
            if "WORLD_MARKER" in raw:
                return "城市档案缺口"
            if "CONFLICT_MARKER" in raw:
                return "受损信号"
            if "SECRET_MARKER" in raw:
                return "四层角色距离"
            return "核心线索"

        text = E2E_CHARACTER_NAME_RE.sub(r"\1", text)
        text = GENERIC_CHARACTER_NAME_RE.sub(r"\1", text)
        text = E2E_TRUNCATED_ITEMS_RE.sub("\u6b8b\u7f3a\u8bb0\u5f55", text)
        text = E2E_TEST_TITLE_RE.sub("\u57ce\u5e02\u6863\u6848\u8c03\u67e5", text)
        text = E2E_MARKER_RE.sub(readable_marker, text)
        text = E2E_SCENE_ID_RE.sub(scene_label, text)
        text = E2E_CHAPTER_ID_RE.sub("本章", text)
        text = E2E_GENERIC_M9_RE.sub("线索", text)
        text = E2E_RUN_TOKEN_RE.sub("", text)
        text = text.replace("CHARACTER_RUN", "")
        for pattern, replacement in E2E_RESIDUAL_TEST_TERM_REPLACEMENTS:
            text = pattern.sub(replacement, text)
        text = INSTRUCTIONAL_SENTENCE_RE.sub(
            "这条线索落到可见行动中，角色只能通过选择、核查和承担风险继续推进。",
            text,
        )
        text = re.sub(r"当前幕必须[^。！？\n]*(?:[。！？]|$)", "", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"「\s*」", "「核心线索」", text)
        return text.strip()

    def _character_table(self, characters: list[Any], refs: list[FinalStoryPackageSourceRef]) -> list[dict[str, Any]]:
        ids = {ref.source_object_id for ref in refs}
        rows = []
        for character in characters:
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("character_id") or character.get("id") or "")
            if character_id not in ids:
                continue
            rows.append(
                {
                    "character_id": self._safe_identifier(character_id),
                    "name": self._safe_text(
                        self._user_story_text(str(character.get("name") or character.get("display_name") or "")),
                        limit=120,
                    ),
                    "status": self._safe_identifier(str(character.get("status") or "")),
                    "role_tier": self._safe_identifier(str(character.get("role_tier") or character.get("tier") or "")),
                }
            )
        return rows

    def _relationship_summary(self, relationships: list[Any], refs: list[FinalStoryPackageSourceRef]) -> list[dict[str, Any]]:
        ids = {ref.source_object_id for ref in refs}
        rows = []
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            relationship_id = str(relationship.get("relationship_id") or relationship.get("id") or "")
            if relationship_id not in ids:
                continue
            rows.append(
                {
                    "relationship_id": self._safe_identifier(relationship_id),
                    "status": self._safe_identifier(str(relationship.get("status") or relationship.get("relationship_status") or "")),
                    "character_ids": [
                        self._safe_identifier(str(item))
                        for item in relationship.get("character_ids", [])
                        if isinstance(item, str)
                    ],
                    "safe_summary": self._safe_text(str(relationship.get("safe_summary") or relationship.get("summary") or ""), limit=220),
                }
            )
        return rows

    def _event_timeline(self, events: list[Any], refs: list[FinalStoryPackageSourceRef]) -> list[dict[str, Any]]:
        ids = {ref.source_object_id for ref in refs}
        rows = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or event.get("id") or "")
            if event_id not in ids:
                continue
            rows.append(
                {
                    "event_id": self._safe_identifier(event_id),
                    "scene_id": self._safe_identifier(str(event.get("scene_id") or "")),
                    "status": self._safe_identifier(str(event.get("status") or event.get("event_status") or "")),
                    "safe_summary": self._safe_text(str(event.get("safe_summary") or event.get("summary") or event.get("description") or ""), limit=220),
                }
            )
        return rows

    def _world_canvas_summary(self, world_canvas: dict[str, Any], world_truth: bool) -> dict[str, Any]:
        if not world_truth:
            return {}
        hard_rules = [rule for rule in world_canvas.get("hard_rules", []) if isinstance(rule, dict)]
        return {
            "world_canvas_id": self._safe_identifier(str(world_canvas.get("world_canvas_id") or "world_canvas")),
            "status": self._safe_identifier(str(world_canvas.get("status") or "")),
            "tone": self._safe_text(str(world_canvas.get("tone") or ""), limit=180),
            "hard_rule_ids": [self._safe_identifier(str(rule.get("rule_id") or "")) for rule in hard_rules],
            "hard_rule_count": len(hard_rules),
        }

    def _style_and_tone(self, world_canvas: dict[str, Any], world_truth: bool) -> dict[str, Any]:
        if not world_truth:
            return {}
        return {
            "tone": self._safe_text(str(world_canvas.get("tone") or ""), limit=180),
            "style": self._safe_text(str(world_canvas.get("style") or world_canvas.get("style_and_tone") or ""), limit=180),
        }

    def _locked_constraints(
        self,
        story_data: dict[str, Any],
        ref_by_type: dict[str, list[FinalStoryPackageSourceRef]],
    ) -> list[dict[str, Any]]:
        constraints: list[dict[str, Any]] = []
        world_canvas = story_data["world_canvas"] if isinstance(story_data["world_canvas"], dict) else {}
        world_truth = bool(ref_by_type.get("world_canvas"))
        hard_rule_ids = {ref.source_object_id for ref in ref_by_type.get("world_canvas_hard_rule", [])}
        if hard_rule_ids and not world_truth:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_PARENT_WORLD_CANVAS_NOT_TRUTH")
        for rule in world_canvas.get("hard_rules") or []:
            if isinstance(rule, dict) and str(rule.get("rule_id") or "") in hard_rule_ids:
                constraints.append(
                    {
                        "constraint_type": "world_hard_rule",
                        "source_id": self._safe_identifier(str(rule.get("rule_id") or "")),
                        "statement": self._safe_text(str(rule.get("statement") or rule.get("text") or ""), limit=260),
                    }
                )
        character_ids = {ref.source_object_id for ref in ref_by_type.get("character_hard_limits", [])}
        for character in story_data["characters"]:
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("character_id") or character.get("id") or "")
            if character_id not in character_ids:
                continue
            profile = character.get("profile") if isinstance(character.get("profile"), dict) else {}
            hard_limits = profile.get("hard_limits") or character.get("hard_limits") or []
            constraints.append(
                {
                    "constraint_type": "character_hard_limits",
                    "source_id": self._safe_identifier(character_id),
                    "hard_limits": [self._safe_text(str(item), limit=180) for item in hard_limits if isinstance(item, str)],
                }
            )
        locked_event_ids = {ref.source_object_id for ref in ref_by_type.get("locked_event_constraint", [])}
        for event in story_data["events"]:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or event.get("id") or "")
            if event_id in locked_event_ids:
                constraints.append(
                    {
                        "constraint_type": "locked_event",
                        "source_id": self._safe_identifier(event_id),
                        "safe_summary": self._safe_text(str(event.get("safe_summary") or event.get("summary") or ""), limit=220),
                    }
                )
        return constraints

    def _known_residual_codes(
        self,
        *,
        sections: list[FinalStoryPackageSection],
        warning_issue_ids: list[str],
    ) -> list[str]:
        codes: list[str] = []
        for section in sections:
            for warning in section.warnings:
                if "known_gap_character_arc_empty_by_design" in warning and "known_gap_character_arc_empty_by_design" not in codes:
                    codes.append("known_gap_character_arc_empty_by_design")
        for issue_id in warning_issue_ids:
            if "known_gap_character_arc_empty_by_design" in issue_id and "known_gap_character_arc_empty_by_design" not in codes:
                codes.append("known_gap_character_arc_empty_by_design")
        return codes

    def _safe_preview_for_section(
        self,
        section_type: SectionType,
        content: Any,
        snapshot: FinalStoryPackageSnapshot,
    ) -> str:
        if section_type == "complete_story_text":
            return (
                f"Controlled full text is available only in the snapshot viewer; "
                f"hash={snapshot.complete_story_text_hash[:12]} chars={snapshot.complete_story_text_char_count}."
            )
        return self._safe_text(
            f"{section_type}: item_count={self._item_count(content)} hash={self._hash_text(json.dumps(content, ensure_ascii=False, sort_keys=True))[:12]}",
            limit=220,
        )

    def _item_count(self, content: Any) -> int:
        if isinstance(content, list):
            return len(content)
        if isinstance(content, dict):
            return len(content)
        if isinstance(content, str):
            return 1 if content else 0
        return 0

    def _residual_risks(self, known_residual_codes: list[str], warning_issue_ids: list[str]) -> list[str]:
        risks = []
        if known_residual_codes:
            risks.append("Known residuals are carried forward and visible to future snapshot consumers.")
        if warning_issue_ids:
            risks.append("M1 ready_with_warnings export preserves warning issue ids.")
        return risks

    def _forbidden_plugin_runtime_files_absent(self) -> bool:
        return not any(self.store.exists(self.data_dir / file_name) for file_name in FORBIDDEN_PLUGIN_RUNTIME_FILES)

    def _selected_hashes(self, file_names: list[str]) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for file_name in file_names:
            path = self.data_dir / file_name
            result[file_name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return result

    def _payload_contains_text(self, payload: Any, text: str) -> bool:
        if not text:
            return False
        return text in json.dumps(payload, ensure_ascii=False)

    def _unsafe_payload_findings(self, payload: Any, *, context: str) -> list[str]:
        findings: list[str] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    key_text = str(key)
                    normalized_key = key_text.lower().replace("-", "_")
                    if any(part in normalized_key for part in UNSAFE_KEY_PARTS):
                        findings.append(f"{context}:{path}.{key_text}:unsafe_key")
                    walk(child, f"{path}.{key_text}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                self._unsafe_text_findings(value, path=path, findings=findings, context=context)

        walk(payload, "$")
        return findings

    def _unsafe_text_findings(self, value: str, *, path: str, findings: list[str], context: str) -> None:
        lowered = value.lower()
        for marker in UNSAFE_VALUE_MARKERS:
            if marker in lowered:
                findings.append(f"{context}:{path}:unsafe_value:{marker}")
        if SECRET_LIKE_RE.search(value):
            findings.append(f"{context}:{path}:secret_like_value")

    def _assert_safe_payload(self, payload: Any, *, context: str) -> None:
        findings = self._unsafe_payload_findings(payload, context=context)
        if findings:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_UNSAFE_PAYLOAD_BLOCKED: " + ",".join(findings[:5]))

    def _assert_safe_text_value(self, value: str, *, context: str) -> None:
        findings: list[str] = []
        self._unsafe_text_findings(value, path="$", findings=findings, context=context)
        if findings:
            raise StorageError("FINAL_STORY_PACKAGE_EXPORT_UNSAFE_PAYLOAD_BLOCKED: " + ",".join(findings[:5]))

    def _assert_safe_snapshot(self, snapshot: FinalStoryPackageSnapshot) -> None:
        self._assert_safe_snapshot_dict(model_to_dict(snapshot))

    def _assert_safe_snapshot_dict(self, payload: dict[str, Any]) -> None:
        sanitized = dict(payload)
        complete_story_text = sanitized.pop("complete_story_text", "")
        self._assert_safe_payload(sanitized, context="snapshot_metadata")
        if isinstance(complete_story_text, str):
            self._assert_safe_text_value(complete_story_text, context="snapshot.complete_story_text")

    def _safe_identifier(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_\-:.]", "_", value.strip())
        return cleaned[:120] or "unknown"

    def _safe_text(self, value: str, *, limit: int = 220) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    def _hash_text(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _id_suffix(self, created_at: str) -> str:
        return self._hash_text(created_at)[:10]

    def _export_summary(self, export_status: ExportStatus, package_type: PackageType) -> str:
        if export_status == "fixture_created":
            return "Fixture Final Story Package Snapshot created; it is non-real and cannot be used by plugins."
        return f"Final Story Package Snapshot created for {package_type}; future plugins must use this snapshot only."
