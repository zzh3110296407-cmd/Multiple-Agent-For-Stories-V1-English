from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.phase6_replay_gate import (
    AnalyzeStoriesReplayRun,
    KnownGapCarryForwardListResponse,
    KnownGapCarryForwardRecord,
    ReplayEvidenceIndex,
    ReplayGateCompatibilityMatrix,
    ReplayGateReportListResponse,
    ReplayGateRunRequest,
    ReplayGateRunResult,
    ReplayGateStatusResponse,
    StableCleanReplayReport,
)
from ..storage.json_store import JsonStore, StorageError
from .analysis_report_viewer_service import AnalysisReportViewerService
from .analyze_stories_import_service import AnalyzeStoriesImportService
from .framework_package_candidate_service import FrameworkPackageCandidateService
from .full_book_bundle_validation_service import FullBookBundleValidationService


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase6_m1_stable_clean_replay_gate_v1"

REPORTS_FILE = "phase6_stable_clean_replay_reports.json"
RUNS_FILE = "phase6_analyze_stories_replay_runs.json"
KNOWN_GAPS_FILE = "phase6_known_gap_carry_forward_records.json"
MATRICES_FILE = "phase6_replay_compatibility_matrices.json"
EVIDENCE_INDEXES_FILE = "phase6_replay_evidence_indexes.json"

CHARACTER_ARC_GAP_ID = "character_arc_empty_by_design"

ANALYZE_STORIES_SOURCE_MARKERS = (
    "analyze_stories",
    "analysis_report",
    "framework_candidate",
    "framework_package",
    "full_book_bundle",
    "input_fingerprint",
    "arc_evidence",
    "evidence_",
    "m4_",
    "m6_",
)
KNOWN_GAP_SOURCE_MARKERS = (
    "character_arc_empty_by_design",
    "phase5_m8",
    "phase6_m1",
    "stable_known_gap",
    "known_gap",
)

UNSAFE_KEY_PARTS = (
    "prompt",
    "response",
    "reasoning",
    "secret",
    "token",
    "password",
    "credential",
    "authorization",
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
    "prose_text",
    "revised_prose_text",
    "full_user_modification_text",
    "authorization:",
    "bearer ",
)

SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()
    if isinstance(model, dict):
        return dict(model)
    raise TypeError(f"Unsupported model type: {type(model)!r}")


class Phase6ReplayGateService:
    """Stable-clean replay gate for Phase 6 M1.

    M1 is an audit/replay gate only. This service never writes formal story
    state, active framework mappings, proposals, decisions, or apply plans.
    """

    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        analyze_import_service: AnalyzeStoriesImportService | None = None,
        framework_candidate_service: FrameworkPackageCandidateService | None = None,
        analysis_report_viewer_service: AnalysisReportViewerService | None = None,
        full_book_bundle_validation_service: FullBookBundleValidationService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.reports_file = self.data_dir / REPORTS_FILE
        self.runs_file = self.data_dir / RUNS_FILE
        self.known_gaps_file = self.data_dir / KNOWN_GAPS_FILE
        self.matrices_file = self.data_dir / MATRICES_FILE
        self.evidence_indexes_file = self.data_dir / EVIDENCE_INDEXES_FILE

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
        self.full_book_bundle_validation_service = full_book_bundle_validation_service or FullBookBundleValidationService(
            store=self.store,
            data_dir=self.data_dir,
            analyze_import_service=self.analyze_import_service,
            framework_candidate_service=self.framework_candidate_service,
            analysis_report_viewer_service=self.analysis_report_viewer_service,
        )

    def get_status(self) -> ReplayGateStatusResponse:
        reports = self._read_models_if_exists(self.reports_file, StableCleanReplayReport)
        gaps = self._read_models_if_exists(self.known_gaps_file, KnownGapCarryForwardRecord)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        gaps.sort(key=lambda item: item.created_at, reverse=True)
        latest_report = reports[0] if reports else None
        active_gaps = [
            gap.gap_id
            for gap in gaps
            if gap.gap_status in {"carried_forward", "downgraded", "blocked"}
        ]
        if not gaps:
            active_gaps = [CHARACTER_ARC_GAP_ID]
        return ReplayGateStatusResponse(
            external_contract_confidence=(
                latest_report.external_contract_confidence
                if latest_report
                else "stable_with_known_gaps"
            ),
            stable_clean_package_available=(
                latest_report.stable_clean_package_available if latest_report else False
            ),
            active_known_gaps=self._dedupe(active_gaps),
            formal_apply_guard_active=True,
            latest_replay_report_id=latest_report.replay_report_id if latest_report else None,
            safe_summary=(
                "Phase 6 M1 replay gate is active. Formal apply remains blocked "
                "for carried-forward Analyze Stories character-arc gaps."
            ),
        )

    def run_gate(self, request: ReplayGateRunRequest | None = None) -> ReplayGateRunResult:
        request = request or ReplayGateRunRequest()
        self._guard_safe_payload(model_to_dict(request))
        self._ensure_storage_files()
        started = time.perf_counter()
        if request.run_mode == "targeted_stable_clean_replay":
            result = self._run_targeted_replay(request, started)
        else:
            result = self._run_no_stable_clean_available(request, started)
        self._guard_safe_payload(model_to_dict(result.report))
        self._guard_safe_payload(model_to_dict(result.replay_run))
        for gap in result.known_gaps:
            self._guard_safe_payload(model_to_dict(gap))
        self._guard_safe_payload(model_to_dict(result.compatibility_matrix))
        self._guard_safe_payload(model_to_dict(result.evidence_index))
        self._append(self.reports_file, model_to_dict(result.report))
        self._append(self.runs_file, model_to_dict(result.replay_run))
        for gap in result.known_gaps:
            self._append(self.known_gaps_file, model_to_dict(gap))
        self._append(self.matrices_file, model_to_dict(result.compatibility_matrix))
        self._append(self.evidence_indexes_file, model_to_dict(result.evidence_index))
        return result

    def list_reports(self) -> ReplayGateReportListResponse:
        reports = self._read_models_if_exists(self.reports_file, StableCleanReplayReport)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return ReplayGateReportListResponse(reports=reports, total_count=len(reports))

    def get_report(self, replay_report_id: str) -> StableCleanReplayReport:
        for report in self._read_models_if_exists(self.reports_file, StableCleanReplayReport):
            if report.replay_report_id == replay_report_id:
                return report
        raise StorageError(f"PHASE6_REPLAY_REPORT_NOT_FOUND: {replay_report_id}")

    def list_known_gaps(self) -> KnownGapCarryForwardListResponse:
        gaps = self._read_models_if_exists(self.known_gaps_file, KnownGapCarryForwardRecord)
        gaps.sort(key=lambda item: item.created_at, reverse=True)
        return KnownGapCarryForwardListResponse(known_gaps=gaps, total_count=len(gaps))

    def get_compatibility_matrix(self, matrix_id: str) -> ReplayGateCompatibilityMatrix:
        for matrix in self._read_models_if_exists(self.matrices_file, ReplayGateCompatibilityMatrix):
            if matrix.matrix_id == matrix_id:
                return matrix
        raise StorageError(f"PHASE6_REPLAY_COMPATIBILITY_MATRIX_NOT_FOUND: {matrix_id}")

    def should_block_character_arc_apply(self, source_refs: list[str] | None = None) -> bool:
        source_refs = source_refs or []
        if not any(
            not self._is_user_supplement_source(ref)
            and (self._is_analyze_stories_source(ref) or self._is_known_gap_source(ref))
            for ref in source_refs
        ):
            return False
        gap = self._latest_character_arc_gap()
        if gap is None:
            return True
        return gap.gap_status in {"carried_forward", "downgraded", "blocked"}

    def _run_no_stable_clean_available(
        self,
        request: ReplayGateRunRequest,
        started: float,
    ) -> ReplayGateRunResult:
        timestamp = now_iso()
        report_id = self._next_id("phase6_replay_report", self.reports_file, "replay_report_id")
        run_id = f"{report_id}_run"
        gap_id = f"{report_id}_gap_character_arc"
        matrix_id = f"{report_id}_compatibility_matrix"
        evidence_index_id = f"{report_id}_evidence_index"
        gap = self._character_arc_gap(
            record_id=gap_id,
            gap_status="carried_forward",
            source_package_status="stable_with_known_gaps",
            source_refs=[
                "phase5_m8_v4_stable_known_gap:character_arc_empty_by_design",
                "phase6_m1:no_stable_clean_available",
            ],
            safe_summary=(
                "Analyze Stories stable-clean package is not available. Character arc "
                "data remains a carried-forward external contract gap."
            ),
            timestamp=timestamp,
        )
        matrix = ReplayGateCompatibilityMatrix(
            matrix_id=matrix_id,
            replay_report_id=report_id,
            package_label="Phase 5 M8 V4 known-gap handoff",
            package_status="stable_with_known_gaps",
            framework_package_supported=True,
            story_analysis_report_supported=True,
            full_book_bundle_supported=True,
            character_arc_evidence_present=False,
            character_arc_evidence_source_attributed=False,
            known_gaps=[CHARACTER_ARC_GAP_ID],
            unsupported_fields=["character_arc_source_attribution"],
            normalized_fields=["framework_package", "story_analysis_report", "full_book_bundle"],
            conclusion="compatible_with_known_gaps",
            safe_summary=(
                "Known Phase 5 Analyze Stories records are usable for non-character-arc "
                "replay, with character-arc apply blocked."
            ),
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        evidence_index = ReplayEvidenceIndex(
            evidence_index_id=evidence_index_id,
            replay_report_id=report_id,
            evidence_docs=[
                "Phase 5 M8 Codes brief",
                "Phase 5 M8 V4 stabilization handoff",
                "Phase 6 M1 Codes brief",
            ],
            verifier_outputs=[],
            safety_scan_refs=[
                "phase6 replay gate records",
                "phase6 generated docs",
            ],
            storage_record_refs=[
                REPORTS_FILE,
                RUNS_FILE,
                KNOWN_GAPS_FILE,
                MATRICES_FILE,
                EVIDENCE_INDEXES_FILE,
            ],
            safe_summary="Evidence index contains document labels and storage references only.",
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        report = StableCleanReplayReport(
            replay_report_id=report_id,
            source_package_status_before="stable_with_known_gaps",
            replay_mode=request.run_mode,
            replay_status="skipped",
            stable_clean_package_available=False,
            source_import_id=request.source_import_id,
            bundle_manifest_id=request.bundle_manifest_id,
            framework_candidate_id=request.framework_candidate_id,
            source_package_fingerprint_id=None,
            checked_pipeline_steps=["known_gap_guard", "storage_safety_scan", "formal_apply_guard"],
            passed_steps=["known_gap_guard", "storage_safety_scan", "formal_apply_guard"],
            failed_steps=[],
            blocked_steps=[],
            known_gap_record_ids=[gap.known_gap_record_id],
            compatibility_matrix_id=matrix.matrix_id,
            evidence_index_id=evidence_index.evidence_index_id,
            external_contract_confidence="stable_with_known_gaps",
            safe_summary=(
                "No stable-clean Analyze Stories package was supplied. Replay gate recorded "
                "the known character-arc gap and kept formal apply blocked."
            ),
            warnings=[CHARACTER_ARC_GAP_ID],
            blocking_issues=[],
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        replay_run = AnalyzeStoriesReplayRun(
            replay_run_id=run_id,
            replay_report_id=report_id,
            run_scope="no_stable_clean_available",
            used_package_type="v4_stable_with_known_gaps",
            step_results=[
                self._step_result("known_gap_guard", True, "Character arc gap carried forward."),
                self._step_result("formal_apply_guard", True, "No formal apply records were written."),
                self._step_result("storage_safety_scan", True, "Replay records passed safety scan."),
            ],
            import_id=request.source_import_id,
            framework_candidate_id=request.framework_candidate_id,
            viewer_state_ids=request.viewer_state_ids,
            bundle_validation_report_id=request.bundle_manifest_id,
            adapter_derivation_report_id=None,
            library_item_ids=[],
            all_commands_passed=True,
            safety_scan_passed=True,
            no_formal_write_pollution=True,
            duration_seconds=round(time.perf_counter() - started, 4),
            safe_summary="No stable-clean replay was available; M1 wrote audit records only.",
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        return ReplayGateRunResult(
            success=True,
            report=report,
            replay_run=replay_run,
            known_gaps=[gap],
            compatibility_matrix=matrix,
            evidence_index=evidence_index,
        )

    def _run_targeted_replay(
        self,
        request: ReplayGateRunRequest,
        started: float,
    ) -> ReplayGateRunResult:
        timestamp = now_iso()
        report_id = self._next_id("phase6_replay_report", self.reports_file, "replay_report_id")
        matrix_id = f"{report_id}_compatibility_matrix"
        evidence_index_id = f"{report_id}_evidence_index"
        step_results: list[dict[str, Any]] = []
        passed_steps: list[str] = []
        failed_steps: list[str] = []
        blocked_steps: list[str] = []
        warnings: list[str] = []
        blocking_issues: list[str] = []
        source_package_status = "unknown"
        stable_clean_available = False
        payload: dict[str, Any] | None = None
        source_package_fingerprint_id: str | None = None

        if not request.source_import_id:
            blocking_issues.append("source_import_id_required")
            blocked_steps.append("source_import")
            step_results.append(self._step_result("source_import", False, "source_import_id is required.", "blocking"))
        else:
            try:
                import_detail = self.analyze_import_service.get_detail(request.source_import_id)
                step_results.append(self._step_result("source_import", True, "Import detail loaded."))
                passed_steps.append("source_import")
                if import_detail.input_fingerprints:
                    source_package_fingerprint_id = import_detail.input_fingerprints[0].fingerprint_id
                artifact = import_detail.artifacts[0] if import_detail.artifacts else None
                if artifact is not None:
                    payload = self.analyze_import_service.read_artifact_payload(
                        request.source_import_id,
                        artifact.artifact_id,
                    )
                    package_contract = self._source_package_contract(payload)
                    source_package_status = package_contract["source_package_status"]
                    stable_clean_available = package_contract["stable_clean_available"]
                    step_results.append(
                        self._step_result(
                            "source_package_status",
                            stable_clean_available,
                            package_contract["safe_summary"],
                            None if stable_clean_available else "warning",
                        )
                    )
                    if stable_clean_available:
                        passed_steps.append("source_package_status")
                    else:
                        warnings.append(f"source_package_status_not_stable_clean:{source_package_status}")
                        warnings.extend(package_contract["warnings"])
            except StorageError as exc:
                blocking_issues.append(str(exc))
                blocked_steps.append("source_import")
                step_results.append(self._step_result("source_import", False, str(exc), "blocking"))

        if request.framework_candidate_id:
            try:
                detail = self.framework_candidate_service.get_detail(request.framework_candidate_id)
                ok = bool(detail.candidate.can_proceed_to_m4_workbench)
                step_results.append(
                    self._step_result(
                        "framework_candidate",
                        ok,
                        "Framework candidate is ready." if ok else "Framework candidate is not ready.",
                        "warning" if not ok else None,
                    )
                )
                if ok:
                    passed_steps.append("framework_candidate")
                else:
                    failed_steps.append("framework_candidate")
                    warnings.append("framework_candidate_not_ready")
            except StorageError as exc:
                blocking_issues.append(str(exc))
                blocked_steps.append("framework_candidate")
                step_results.append(self._step_result("framework_candidate", False, str(exc), "blocking"))

        for viewer_state_id in request.viewer_state_ids:
            step_name = f"viewer_state:{viewer_state_id}"
            try:
                detail = self.analysis_report_viewer_service.get_viewer_state(viewer_state_id)
                ok = detail.viewer_state.viewer_status in {"available", "available_with_warnings"}
                step_results.append(self._step_result(step_name, ok, f"Viewer state status={detail.viewer_state.viewer_status}."))
                if ok:
                    passed_steps.append(step_name)
                else:
                    failed_steps.append(step_name)
            except StorageError as exc:
                warnings.append(str(exc))
                failed_steps.append(step_name)
                step_results.append(self._step_result(step_name, False, str(exc), "warning"))

        if request.bundle_manifest_id:
            try:
                report = self.full_book_bundle_validation_service.get_validation_report(
                    request.bundle_manifest_id
                )
                ok = bool(report.passed)
                step_results.append(
                    self._step_result(
                        "full_book_bundle",
                        ok,
                        "Full-book bundle validation passed." if ok else "Full-book bundle validation did not pass.",
                        "warning" if not ok else None,
                    )
                )
                if ok:
                    passed_steps.append("full_book_bundle")
                else:
                    failed_steps.append("full_book_bundle")
                    warnings.append("full_book_bundle_not_reference_ready")
            except StorageError as exc:
                warnings.append(str(exc))
                failed_steps.append("full_book_bundle")
                step_results.append(self._step_result("full_book_bundle", False, str(exc), "warning"))

        package_probe = self._probe_character_arc_contract(payload or {})
        if not stable_clean_available:
            gap_status = "carried_forward"
            external_confidence = "stable_with_known_gaps"
            conclusion = "compatible_with_known_gaps"
            matrix_known_gaps: list[str] = [CHARACTER_ARC_GAP_ID]
            unsupported_fields: list[str] = ["stable_clean_certification_missing"]
            safe_summary = (
                "Targeted replay package is not certified stable-clean. Character-arc "
                "evidence cannot close the carried-forward Analyze Stories gap."
            )
            warnings.append(CHARACTER_ARC_GAP_ID)
            step_results.append(
                self._step_result(
                    "stable_clean_certification",
                    False,
                    "Package is not certified stable-clean; gap remains active.",
                    "warning",
                )
            )
        elif package_probe["character_arc_evidence_present"]:
            gap_status = "closed"
            external_confidence = "stable_clean_verified"
            conclusion = "compatible"
            matrix_known_gaps: list[str] = []
            unsupported_fields: list[str] = []
            safe_summary = (
                "Stable-clean replay found source-attributed character-arc evidence. "
                "The carried-forward gap can close for Analyze Stories arc apply."
            )
            passed_steps.append("character_arc_evidence")
            step_results.append(self._step_result("character_arc_evidence", True, "Source-attributed character-arc evidence found."))
        elif package_probe["character_arc_out_of_scope"]:
            gap_status = "downgraded"
            external_confidence = "stable_clean_verified"
            conclusion = "compatible_with_known_gaps"
            matrix_known_gaps = [CHARACTER_ARC_GAP_ID]
            unsupported_fields = ["character_arc_declared_out_of_scope"]
            safe_summary = (
                "Stable-clean replay marked character arc as out of scope. The external "
                "expectation is downgraded, but Analyze Stories arc apply remains blocked."
            )
            warnings.append("character_arc_out_of_scope")
            passed_steps.append("character_arc_scope_check")
            step_results.append(self._step_result("character_arc_scope_check", True, "Character arc declared out of scope."))
        else:
            gap_status = "carried_forward"
            external_confidence = "stable_with_known_gaps"
            conclusion = "compatible_with_known_gaps"
            matrix_known_gaps = [CHARACTER_ARC_GAP_ID]
            unsupported_fields = ["character_arc_source_attribution"]
            safe_summary = (
                "Targeted replay did not find source-attributed character-arc evidence. "
                "The known gap remains carried forward."
            )
            warnings.append(CHARACTER_ARC_GAP_ID)
            step_results.append(self._step_result("character_arc_evidence", False, "Character-arc evidence is still missing.", "warning"))

        blocked = bool(blocking_issues)
        replay_status = "blocked" if blocked else "pass"
        if blocked:
            external_confidence = "blocked"
            source_package_status = "unknown"

        gap = self._character_arc_gap(
            record_id=f"{report_id}_gap_character_arc",
            gap_status=gap_status if not blocked else "blocked",
            source_package_status=source_package_status,
            source_refs=package_probe["source_refs"],
            safe_summary=safe_summary if not blocked else "Targeted replay was blocked before character-arc gap closure.",
            timestamp=timestamp,
        )
        matrix = ReplayGateCompatibilityMatrix(
            matrix_id=matrix_id,
            replay_report_id=report_id,
            package_label="Targeted Analyze Stories stable-clean replay",
            package_status=source_package_status,
            framework_package_supported=bool(request.framework_candidate_id),
            story_analysis_report_supported=bool(request.viewer_state_ids),
            full_book_bundle_supported=bool(request.bundle_manifest_id),
            character_arc_evidence_present=package_probe["character_arc_evidence_present"],
            character_arc_evidence_source_attributed=package_probe["character_arc_evidence_source_attributed"],
            known_gaps=matrix_known_gaps if not blocked else [CHARACTER_ARC_GAP_ID],
            unsupported_fields=unsupported_fields,
            normalized_fields=package_probe["normalized_fields"],
            conclusion="not_available" if blocked else conclusion,
            safe_summary=safe_summary if not blocked else "Targeted stable-clean replay could not complete.",
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        evidence_index = ReplayEvidenceIndex(
            evidence_index_id=evidence_index_id,
            replay_report_id=report_id,
            evidence_docs=package_probe["evidence_docs"],
            verifier_outputs=[],
            safety_scan_refs=["phase6 replay gate targeted run"],
            storage_record_refs=[REPORTS_FILE, RUNS_FILE, KNOWN_GAPS_FILE, MATRICES_FILE, EVIDENCE_INDEXES_FILE],
            safe_summary="Targeted replay evidence index stores safe source references only.",
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        report = StableCleanReplayReport(
            replay_report_id=report_id,
            source_package_status_before=source_package_status,
            replay_mode=request.run_mode,
            replay_status=replay_status,
            stable_clean_package_available=stable_clean_available and not blocked,
            source_import_id=request.source_import_id,
            bundle_manifest_id=request.bundle_manifest_id,
            framework_candidate_id=request.framework_candidate_id,
            source_package_fingerprint_id=source_package_fingerprint_id,
            checked_pipeline_steps=[item["step"] for item in step_results],
            passed_steps=self._dedupe(passed_steps),
            failed_steps=self._dedupe(failed_steps),
            blocked_steps=self._dedupe(blocked_steps),
            known_gap_record_ids=[gap.known_gap_record_id],
            compatibility_matrix_id=matrix.matrix_id,
            evidence_index_id=evidence_index.evidence_index_id,
            external_contract_confidence=external_confidence,
            safe_summary=safe_summary if not blocked else "Targeted replay was blocked and wrote audit records only.",
            warnings=self._dedupe(warnings),
            blocking_issues=self._dedupe(blocking_issues),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        replay_run = AnalyzeStoriesReplayRun(
            replay_run_id=f"{report_id}_run",
            replay_report_id=report_id,
            run_scope="targeted_contract_replay",
            used_package_type=(
                "future_stable_clean"
                if stable_clean_available and not blocked
                else "v4_stable_with_known_gaps"
                if source_package_status == "stable_with_known_gaps" and not blocked
                else "none"
            ),
            step_results=step_results,
            import_id=request.source_import_id,
            framework_candidate_id=request.framework_candidate_id,
            viewer_state_ids=request.viewer_state_ids,
            bundle_validation_report_id=request.bundle_manifest_id,
            adapter_derivation_report_id=None,
            library_item_ids=[],
            all_commands_passed=not blocked and not failed_steps,
            safety_scan_passed=True,
            no_formal_write_pollution=True,
            duration_seconds=round(time.perf_counter() - started, 4),
            safe_summary="Targeted replay completed with audit-only writes." if not blocked else "Targeted replay was blocked before completion.",
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        return ReplayGateRunResult(
            success=not blocked,
            report=report,
            replay_run=replay_run,
            known_gaps=[gap],
            compatibility_matrix=matrix,
            evidence_index=evidence_index,
        )

    def _probe_character_arc_contract(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe_refs: list[str] = []
        normalized_fields: list[str] = []
        evidence_docs: list[str] = []
        evidence_present = False
        evidence_attributed = False
        out_of_scope = False

        def add_refs(value: Any) -> None:
            for ref in self._safe_source_refs(value):
                if ref not in safe_refs:
                    safe_refs.append(ref)

        character_arc_evidence = payload.get("character_arc_evidence")
        if isinstance(character_arc_evidence, list) and character_arc_evidence:
            normalized_fields.append("character_arc_evidence")
            for item in character_arc_evidence:
                if isinstance(item, dict):
                    add_refs(item)
                    if self._has_safe_evidence_text(item):
                        evidence_present = True
                    if self._safe_source_refs(item):
                        evidence_attributed = True
                elif isinstance(item, str) and item.strip():
                    evidence_present = True
            if evidence_present:
                evidence_docs.append("character_arc_evidence")

        arc_contract = payload.get("character_arc_contract")
        if isinstance(arc_contract, dict):
            normalized_fields.append("character_arc_contract")
            add_refs(arc_contract)
            status = str(arc_contract.get("status") or "").lower()
            if status in {"out_of_scope", "not_in_scope", "intentionally_out_of_scope"}:
                out_of_scope = True
            if not out_of_scope and self._has_safe_evidence_text(arc_contract):
                evidence_present = True
            if not out_of_scope and self._safe_source_refs(arc_contract):
                evidence_attributed = True

        component_vocabulary = payload.get("component_vocabulary")
        if isinstance(component_vocabulary, dict):
            for branch_name in ("chapter_modules", "module_components", "macro_components"):
                branch = component_vocabulary.get(branch_name)
                if isinstance(branch, list):
                    for item in branch:
                        if not isinstance(item, dict):
                            continue
                        module_id = str(
                            item.get("module_id")
                            or item.get("component_id")
                            or item.get("id")
                            or item.get("name")
                            or ""
                        ).lower()
                        if "character" in module_id and "arc" in module_id:
                            normalized_fields.append(f"component_vocabulary.{branch_name}")
                            add_refs(item)
                            if item.get("allowed_components") or item.get("safe_summary"):
                                evidence_present = True
                            if self._safe_source_refs(item):
                                evidence_attributed = True

        source_package_status = self._string_at(payload, "source_package_status")
        if source_package_status:
            normalized_fields.append("source_package_status")
        if not safe_refs:
            add_refs(payload)

        return {
            "character_arc_evidence_present": evidence_present and evidence_attributed,
            "character_arc_evidence_source_attributed": evidence_attributed,
            "character_arc_out_of_scope": out_of_scope,
            "source_refs": safe_refs or ["phase6_m1:source_ref_unavailable"],
            "normalized_fields": self._dedupe(normalized_fields),
            "evidence_docs": self._dedupe(evidence_docs),
        }

    def _source_package_status(self, payload: dict[str, Any]) -> str:
        return self._source_package_contract(payload)["source_package_status"]

    def _source_package_contract(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_manifest = payload.get("run_manifest")
        run_manifest = run_manifest if isinstance(run_manifest, dict) else {}
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        statuses = self._collect_package_statuses(payload, run_manifest, metadata)
        unique_statuses = self._dedupe([item["status"] for item in statuses])
        known_gaps = self._collect_known_package_gaps(payload, run_manifest, metadata)
        warnings: list[str] = []
        if len(unique_statuses) > 1:
            warnings.append("source_package_status_conflict")
        if known_gaps:
            warnings.append("source_package_known_gaps_present")

        if known_gaps or "stable_with_known_gaps" in unique_statuses:
            source_package_status = "stable_with_known_gaps"
        elif "stable_clean_not_available" in unique_statuses:
            source_package_status = "stable_clean_not_available"
        elif len(unique_statuses) == 1:
            source_package_status = unique_statuses[0]
        else:
            source_package_status = "unknown"

        stable_clean_available = (
            source_package_status == "stable_clean_verified"
            and len(unique_statuses) == 1
            and not known_gaps
        )
        status_summary = ",".join(unique_statuses) if unique_statuses else "unknown"
        gap_summary = ",".join(known_gaps) if known_gaps else "none"
        return {
            "source_package_status": source_package_status,
            "stable_clean_available": stable_clean_available,
            "warnings": warnings,
            "known_gaps": known_gaps,
            "safe_summary": (
                f"source_package_status={source_package_status}; "
                f"declared_statuses={status_summary}; known_package_gaps={gap_summary}."
            ),
        }

    def _collect_package_statuses(
        self,
        payload: dict[str, Any],
        run_manifest: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for scope_name, scope in [
            ("payload", payload),
            ("run_manifest", run_manifest),
            ("metadata", metadata),
        ]:
            for key in ("source_package_status", "stable_clean_status", "package_status"):
                value = scope.get(key)
                status = self._first_known_status(value)
                if status:
                    results.append({"path": f"{scope_name}.{key}", "status": status})
        return results

    def _collect_known_package_gaps(
        self,
        payload: dict[str, Any],
        run_manifest: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[str]:
        gaps: list[str] = []
        for scope in (payload, run_manifest, metadata):
            for key in (
                "known_package_gaps",
                "known_gaps",
                "active_known_gaps",
                "package_known_gaps",
            ):
                gaps.extend(self._extract_gap_ids(scope.get(key)))
        return self._dedupe(gaps)

    def _extract_gap_ids(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if self._is_safe_ref(value) else []
        if isinstance(value, list):
            gaps: list[str] = []
            for item in value:
                gaps.extend(self._extract_gap_ids(item))
            return gaps
        if isinstance(value, dict):
            for key in ("gap_id", "id", "code", "name"):
                gap = value.get(key)
                if isinstance(gap, str) and self._is_safe_ref(gap):
                    return [gap]
        return []

    def _character_arc_gap(
        self,
        *,
        record_id: str,
        gap_status: str,
        source_package_status: str,
        source_refs: list[str],
        safe_summary: str,
        timestamp: str,
    ) -> KnownGapCarryForwardRecord:
        return KnownGapCarryForwardRecord(
            known_gap_record_id=record_id,
            gap_id=CHARACTER_ARC_GAP_ID,
            source_package_status=source_package_status,
            gap_status=gap_status,
            affected_capabilities=[
                "character_arc_apply",
                "character_arc_narrative_debt",
                "character_arc_pattern_recommendation",
                "system_recommendation",
                "formal_apply_eligibility",
            ],
            hard_block_rules=[
                "Block character_arc_apply from Analyze Stories source while the gap is carried_forward, downgraded, or blocked.",
                "Block character_arc_narrative_debt from Analyze Stories source while source-attributed arc evidence is unavailable.",
                "Block system_recommendation that treats Analyze Stories character arc as complete before gap closure.",
            ],
            user_supplement_allowed=True,
            user_supplement_must_be_separate_evidence=True,
            close_condition_summary=(
                "Close only after a stable-clean Analyze Stories package provides non-empty, "
                "source-attributed character-arc evidence through the import path."
            ),
            source_refs=self._dedupe(source_refs),
            safe_summary=safe_summary,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _latest_character_arc_gap(self) -> KnownGapCarryForwardRecord | None:
        gaps = [
            gap
            for gap in self._read_models_if_exists(self.known_gaps_file, KnownGapCarryForwardRecord)
            if gap.gap_id == CHARACTER_ARC_GAP_ID
        ]
        gaps.sort(key=lambda item: item.created_at, reverse=True)
        return gaps[0] if gaps else None

    def _ensure_storage_files(self) -> None:
        for path in [
            self.reports_file,
            self.runs_file,
            self.known_gaps_file,
            self.matrices_file,
            self.evidence_indexes_file,
        ]:
            self.store.write_if_missing(path, [])

    def _read_models_if_exists(self, path: Path, model_cls: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        return [model_cls(**item) for item in self.store.read_list(path)]

    def _append(self, path: Path, payload: dict[str, Any]) -> None:
        rows = self.store.read_list(path) if self.store.exists(path) else []
        rows.append(payload)
        self.store.write(path, rows)

    def _next_id(self, prefix: str, path: Path, id_field: str) -> str:
        rows = self.store.read_list(path) if self.store.exists(path) else []
        index = len(rows) + 1
        while True:
            candidate = f"{prefix}_{index:03d}"
            if not any(isinstance(row, dict) and row.get(id_field) == candidate for row in rows):
                return candidate
            index += 1

    def _step_result(
        self,
        step: str,
        passed: bool,
        safe_summary: str,
        severity: str | None = None,
    ) -> dict[str, Any]:
        return {
            "step": step,
            "passed": passed,
            "severity": severity or ("info" if passed else "warning"),
            "safe_summary": safe_summary,
        }

    def _safe_source_refs(self, payload: Any) -> list[str]:
        refs: list[str] = []
        if isinstance(payload, dict):
            for key in [
                "source_ref",
                "source_refs",
                "source_input_fingerprint_id",
                "input_fingerprint_id",
                "input_fingerprint_ids",
                "artifact_id",
                "import_id",
                "evidence_id",
            ]:
                value = payload.get(key)
                if isinstance(value, str) and self._is_safe_ref(value):
                    refs.append(value)
                elif isinstance(value, list):
                    refs.extend([item for item in value if isinstance(item, str) and self._is_safe_ref(item)])
                elif isinstance(value, dict):
                    digest = hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
                    refs.append(f"{key}:{digest}")
        return self._dedupe(refs)

    def _is_safe_ref(self, value: str) -> bool:
        if len(value) > 160:
            return False
        lowered = value.lower()
        if SECRET_LIKE_RE.search(value):
            return False
        return not any(marker in lowered for marker in UNSAFE_VALUE_MARKERS)

    def _has_safe_evidence_text(self, payload: dict[str, Any]) -> bool:
        for key in ("safe_summary", "summary", "evidence_id", "claim_id", "arc_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip() and self._is_safe_ref(value):
                return True
        return False

    def _string_at(self, payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) else None

    def _is_analyze_stories_source(self, ref: str) -> bool:
        lowered = ref.lower()
        return any(marker in lowered for marker in ANALYZE_STORIES_SOURCE_MARKERS)

    def _is_known_gap_source(self, ref: str) -> bool:
        lowered = ref.lower()
        return any(marker in lowered for marker in KNOWN_GAP_SOURCE_MARKERS)

    def _is_user_supplement_source(self, ref: str) -> bool:
        lowered = ref.strip().lower()
        return lowered.startswith("user_supplement:") or lowered.startswith("user-supplement:")

    def _first_known_status(self, *values: Any) -> str | None:
        allowed = {
            "stable_with_known_gaps",
            "stable_clean_not_available",
            "stable_clean_verified",
            "unknown",
        }
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = value.strip().lower()
            if normalized in allowed:
                return normalized
        return None

    def _guard_safe_payload(self, payload: Any) -> None:
        issues: list[str] = []
        self._scan_payload(payload, "$", issues)
        if issues:
            raise StorageError(
                "PHASE6_REPLAY_GATE_UNSAFE_PAYLOAD_BLOCKED: " + ", ".join(issues[:5])
            )

    def _scan_payload(self, value: Any, path: str, issues: list[str]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key).lower()
                if any(part in key_text for part in UNSAFE_KEY_PARTS):
                    if key_text not in {"safe_summary", "source_package_fingerprint_id"}:
                        issues.append(f"unsafe key at {path}.{key}")
                self._scan_payload(child, f"{path}.{key}", issues)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._scan_payload(child, f"{path}[{index}]", issues)
        elif isinstance(value, str):
            lowered = value.lower()
            if SECRET_LIKE_RE.search(value):
                issues.append(f"secret-like value at {path}")
            for marker in UNSAFE_VALUE_MARKERS:
                if marker in lowered:
                    issues.append(f"unsafe marker at {path}")
                    break

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result
