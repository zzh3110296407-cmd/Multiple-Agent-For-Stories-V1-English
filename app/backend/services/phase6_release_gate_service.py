from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.phase6_release_gate import (
    Phase6CloseoutReadinessReport,
    Phase6CloseoutReadinessReportListResponse,
    Phase6EvidenceIndex,
    Phase6EvidenceIndexListResponse,
    Phase6FormalFilePollutionAudit,
    Phase6FormalFilePollutionAuditListResponse,
    Phase6KnownResidualsCarryForwardReport,
    Phase6KnownResidualsCarryForwardReportListResponse,
    Phase6RegressionManifest,
    Phase6RegressionManifestListResponse,
    Phase6ReleaseGateReport,
    Phase6ReleaseGateReportListResponse,
    Phase6ReleaseGateRunResult,
    Phase6SafetyAuthorityAudit,
    Phase6SafetyAuthorityAuditListResponse,
    Phase6VerifierRunRecord,
    Phase6VerifierRunRecordListResponse,
    ReleaseGateRunRequest,
    ReleaseGateStatusResponse,
    VerifierMarkerObservation,
)
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase6_m8_release_gate_v1"

RELEASE_GATE_REPORTS_FILE = "phase6_release_gate_reports.json"
REGRESSION_MANIFESTS_FILE = "phase6_regression_manifests.json"
VERIFIER_RUN_RECORDS_FILE = "phase6_verifier_run_records.json"
EVIDENCE_INDEXES_FILE = "phase6_evidence_indexes.json"
CLOSEOUT_READINESS_REPORTS_FILE = "phase6_closeout_readiness_reports.json"
SAFETY_AUTHORITY_AUDITS_FILE = "phase6_safety_authority_audits.json"
FORMAL_FILE_POLLUTION_AUDITS_FILE = "phase6_formal_file_pollution_audits.json"
KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE = "phase6_known_residuals_carry_forward_reports.json"

ALLOWED_STORAGE_FILES = [
    RELEASE_GATE_REPORTS_FILE,
    REGRESSION_MANIFESTS_FILE,
    VERIFIER_RUN_RECORDS_FILE,
    EVIDENCE_INDEXES_FILE,
    CLOSEOUT_READINESS_REPORTS_FILE,
    SAFETY_AUTHORITY_AUDITS_FILE,
    FORMAL_FILE_POLLUTION_AUDITS_FILE,
    KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE,
]

PHASE6_M1_EVIDENCE_FILES = [
    "phase6_stable_clean_replay_reports.json",
    "phase6_analyze_stories_replay_runs.json",
    "phase6_known_gap_carry_forward_records.json",
    "phase6_replay_compatibility_matrices.json",
    "phase6_replay_evidence_indexes.json",
]
PHASE6_M2_EVIDENCE_FILES = [
    "phase6_formal_apply_targets.json",
    "phase6_formal_apply_source_lineages.json",
    "phase6_formal_apply_eligibility_reports.json",
    "phase6_formal_apply_block_reasons.json",
]
PHASE6_M3_EVIDENCE_FILES = [
    "phase6_formal_apply_plans.json",
    "phase6_formal_apply_plan_items.json",
    "phase6_formal_apply_diff_summaries.json",
    "phase6_formal_apply_impact_previews.json",
    "phase6_formal_apply_safety_checks.json",
]
PHASE6_M4_EVIDENCE_FILES = [
    "phase6_formal_apply_decisions.json",
    "phase6_formal_apply_approval_records.json",
    "phase6_formal_apply_rejection_records.json",
    "phase6_formal_apply_user_overrides.json",
    "phase6_formal_apply_questions.json",
    "phase6_formal_apply_decision_evidence_snapshots.json",
]
PHASE6_M5_EVIDENCE_FILES = [
    "phase6_formal_apply_execution_results.json",
    "phase6_formal_apply_rollback_refs.json",
    "phase6_formal_apply_write_audits.json",
    "phase6_framework_apply_proposals.json",
    "phase6_chapter_archive_proposals.json",
    "phase6_narrative_debt_proposals.json",
]
PHASE6_M6_EVIDENCE_FILES = [
    "phase6_propagation_impact_records.json",
    "phase6_affected_object_review_tasks.json",
    "phase6_cross_chapter_recheck_plans.json",
    "phase6_framework_change_propagation_reports.json",
]
PHASE6_M7_EVIDENCE_FILES = [
    "phase6_recommendation_eligibility_reports.json",
    "phase6_recommendation_risk_profiles.json",
    "phase6_system_recommendation_candidate_reviews.json",
    "phase6_library_promotion_decisions.json",
]
PHASE6_EVIDENCE_FILES = (
    PHASE6_M1_EVIDENCE_FILES
    + PHASE6_M2_EVIDENCE_FILES
    + PHASE6_M3_EVIDENCE_FILES
    + PHASE6_M4_EVIDENCE_FILES
    + PHASE6_M5_EVIDENCE_FILES
    + PHASE6_M6_EVIDENCE_FILES
    + PHASE6_M7_EVIDENCE_FILES
)

FORMAL_STORY_FILES = [
    "chapter_archives.json",
    "narrative_debts.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "scenes.json",
    "continuity_issues.json",
    "future_issues.json",
    "delayed_questions.json",
    "future_todos.json",
    "chapter_memory_packs.json",
    "scene_memory_packs.json",
]
ACTIVE_FRAMEWORK_FILES = ["framework.json", "framework_package.json"]
RECOMMENDATION_ACTIVATION_FILES = ["system_recommended_frameworks.json"]
FORBIDDEN_STORAGE_FILES = [
    "decisions.json",
    *ACTIVE_FRAMEWORK_FILES,
    *RECOMMENDATION_ACTIVATION_FILES,
    *FORMAL_STORY_FILES,
    *PHASE6_EVIDENCE_FILES,
]

REQUIRED_PHASE6_MARKERS = [
    "PHASE6_M1_STABLE_CLEAN_REPLAY_GATE: PASS",
    "PHASE6_M2_FORMAL_APPLY_ELIGIBILITY: PASS",
    "PHASE6_M3_FORMAL_APPLY_DRY_RUN: PASS",
    "PHASE6_M4_FORMAL_APPLY_DECISION_GATE: PASS",
    "PHASE6_M5_CONTROLLED_EXECUTORS: PASS",
    "PHASE6_M6_PROPAGATION_GOVERNANCE: PASS",
    "PHASE6_M7_RECOMMENDATION_GOVERNANCE: PASS",
]
SELECTED_INHERITED_MARKERS = ["PHASE5_M8_ANALYZE_STORIES_E2E_CLOSEOUT: PASS"]
FRONTEND_BUILD_MARKER = "FRONTEND_BUILD: PASS"
REQUIRED_ALL_MARKERS = REQUIRED_PHASE6_MARKERS + SELECTED_INHERITED_MARKERS + [FRONTEND_BUILD_MARKER]

TIMEOUT_POLICY = {
    "phase6_m1_m6": 1200,
    "phase6_m7": 2400,
    "phase5_m8_full": 7200,
    "frontend_build": 1200,
}

UNSAFE_KEY_PARTS = (
    "prompt",
    "response",
    "reasoning",
    "secret",
    "password",
    "credential",
    "authorization",
    "apikey",
    "providersecret",
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
    "full prose",
    "full_prose",
    "full user text",
    "full_user_text",
    "full user modification text",
    "full_user_modification_text",
    "revised prose",
    "revised_prose",
    "provider secret",
    "provider_secret",
    "authorization:",
    "bearer ",
    "api key",
    "api_key",
)
SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")
FILESYSTEM_PATH_RE = re.compile(r"(?i)([a-z]:[\\/]|(^|[\\/])\.\.([\\/]|$))")
SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-:.]+$")


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


class Phase6ReleaseGateService:
    """Phase 6 M8 release-gate evidence service.

    M8 records closeout-readiness evidence only. It never executes formal
    apply, creates story facts, mutates framework state, rewrites propagation,
    or activates recommendations.
    """

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.release_gate_reports_file = self.data_dir / RELEASE_GATE_REPORTS_FILE
        self.regression_manifests_file = self.data_dir / REGRESSION_MANIFESTS_FILE
        self.verifier_run_records_file = self.data_dir / VERIFIER_RUN_RECORDS_FILE
        self.evidence_indexes_file = self.data_dir / EVIDENCE_INDEXES_FILE
        self.closeout_readiness_reports_file = self.data_dir / CLOSEOUT_READINESS_REPORTS_FILE
        self.safety_authority_audits_file = self.data_dir / SAFETY_AUTHORITY_AUDITS_FILE
        self.formal_file_pollution_audits_file = self.data_dir / FORMAL_FILE_POLLUTION_AUDITS_FILE
        self.known_residuals_reports_file = self.data_dir / KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE

    def get_status(self) -> ReleaseGateStatusResponse:
        reports = self._read_models_if_exists(self.release_gate_reports_file, Phase6ReleaseGateReport)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        latest = reports[0] if reports else None
        return ReleaseGateStatusResponse(
            report_count=len(reports),
            latest_release_gate_report_id=latest.release_gate_report_id if latest else None,
            latest_release_status=latest.release_status if latest else None,
            latest_closeout_readiness_status=latest.closeout_readiness_status if latest else None,
            allowed_m8_storage_files=list(ALLOWED_STORAGE_FILES),
            forbidden_storage_files=list(FORBIDDEN_STORAGE_FILES),
            phase6_evidence_files=list(PHASE6_EVIDENCE_FILES),
            required_phase6_markers=list(REQUIRED_PHASE6_MARKERS),
            selected_inherited_markers=list(SELECTED_INHERITED_MARKERS),
            release_gate_is_evidence_only=True,
            no_new_authority=True,
            safe_summary=(
                "M8 status is read only. The release gate records closeout evidence "
                "without formal writes or authority changes."
            ),
        )

    def run_release_gate(self, request: ReleaseGateRunRequest | dict[str, Any]) -> Phase6ReleaseGateRunResult:
        normalized = request if isinstance(request, ReleaseGateRunRequest) else ReleaseGateRunRequest(**request)
        self._guard_safe_payload(model_to_dict(normalized))
        if len(normalized.safe_user_note) > 500:
            raise StorageError("PHASE6_M8_UNSAFE_PAYLOAD_BLOCKED: safe_user_note_too_long")
        for observation in normalized.verifier_marker_observations:
            self._validate_observation(observation)

        before_all = self._storage_fingerprints()
        forbidden_before = self._selected_hashes(FORBIDDEN_STORAGE_FILES)
        timestamp = now_iso()
        release_gate_report_id = self._next_id("phase6_release_gate_report", self.release_gate_reports_file, "release_gate_report_id")
        regression_manifest_id = f"{release_gate_report_id}_regression_manifest"
        evidence_index_id = f"{release_gate_report_id}_evidence_index"
        closeout_readiness_report_id = f"{release_gate_report_id}_closeout_readiness"
        safety_authority_audit_id = f"{release_gate_report_id}_safety_authority"
        formal_file_pollution_audit_id = f"{release_gate_report_id}_formal_file_pollution"
        known_residuals_report_id = f"{release_gate_report_id}_known_residuals"

        observations = list(normalized.verifier_marker_observations)
        verifier_records = self._build_verifier_records(observations, release_gate_report_id, timestamp)
        observed_phase6_markers = self._observed_markers(observations, REQUIRED_PHASE6_MARKERS)
        observed_inherited_markers = self._observed_markers(observations, SELECTED_INHERITED_MARKERS)
        observed_frontend_markers = self._observed_markers(observations, [FRONTEND_BUILD_MARKER])
        phase6_pass = set(REQUIRED_PHASE6_MARKERS).issubset(set(observed_phase6_markers))
        inherited_pass = set(SELECTED_INHERITED_MARKERS).issubset(set(observed_inherited_markers))
        frontend_build_passed = FRONTEND_BUILD_MARKER in observed_frontend_markers
        failed_markers = [
            observation.expected_marker
            for observation in observations
            if observation.expected_marker in REQUIRED_ALL_MARKERS and observation.run_status not in {"pass", "skipped"}
        ]
        missing_markers = [marker for marker in REQUIRED_ALL_MARKERS if marker not in self._observed_markers(observations, REQUIRED_ALL_MARKERS)]
        blocking_findings = [f"missing_marker:{marker}" for marker in missing_markers]
        blocking_findings.extend([f"failed_marker:{marker}" for marker in failed_markers])
        all_required_passed = not blocking_findings

        release_status = "pass_with_known_gaps" if all_required_passed else "blocked"
        readiness_status = "ready_with_known_gaps" if all_required_passed else "blocked"
        success = all_required_passed
        warning_codes = ["known_gap_carried_forward:character_arc_empty_by_design"]

        created_storage_files = [file_name for file_name in ALLOWED_STORAGE_FILES if file_name not in before_all]
        mutated_storage_files = [file_name for file_name in ALLOWED_STORAGE_FILES if file_name in before_all]
        m1_m7_before = {file_name: before_all.get(file_name) for file_name in PHASE6_EVIDENCE_FILES}
        formal_before = {file_name: before_all.get(file_name) for file_name in FORMAL_STORY_FILES}
        framework_before = {file_name: before_all.get(file_name) for file_name in ACTIVE_FRAMEWORK_FILES}
        recommendation_before = {file_name: before_all.get(file_name) for file_name in RECOMMENDATION_ACTIVATION_FILES}

        known_residuals_report = Phase6KnownResidualsCarryForwardReport(
            known_residuals_report_id=known_residuals_report_id,
            release_gate_report_id=release_gate_report_id,
            known_residuals=[
                {
                    "gap_id": "character_arc_empty_by_design",
                    "gap_status": "carried_forward",
                    "authority_boundary": "blocks_unsafe_analyze_stories_character_arc_authority",
                    "safe_summary": "Character arc evidence remains a known residual and is not closed by M8.",
                }
            ],
            character_arc_empty_by_design_carried_forward=True,
            stable_clean_replay_available=False,
            stable_clean_replay_claimed=False,
            stable_with_known_gaps_preserved=True,
            unsafe_closure_claims=[],
            blocking_findings=[],
            safe_summary="M8 carries forward the character arc residual without closing it.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        safety_authority_audit = Phase6SafetyAuthorityAudit(
            safety_authority_audit_id=safety_authority_audit_id,
            release_gate_report_id=release_gate_report_id,
            no_raw_prompt_response_leak=True,
            no_hidden_reasoning_leak=True,
            no_full_prose_leak=True,
            no_secret_or_credential_leak=True,
            no_apply_execution=True,
            no_propagation_rewrite=True,
            no_active_recommendation_creation=True,
            no_active_framework_mutation=True,
            no_formal_story_fact_write=True,
            no_known_gap_clean_pass_claim=True,
            authority_boundary_passed=True,
            blocking_findings=[],
            warning_codes=list(warning_codes),
            safe_summary="M8 authority audit confirms evidence-only closeout boundaries.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        formal_file_pollution_audit = Phase6FormalFilePollutionAudit(
            formal_file_pollution_audit_id=formal_file_pollution_audit_id,
            release_gate_report_id=release_gate_report_id,
            allowed_m8_storage_files=list(ALLOWED_STORAGE_FILES),
            mutated_storage_files=mutated_storage_files,
            created_storage_files=created_storage_files,
            forbidden_storage_files_checked=list(FORBIDDEN_STORAGE_FILES),
            forbidden_storage_unchanged=True,
            m1_m7_evidence_files_unchanged_by_m8=True,
            formal_story_files_unchanged=True,
            active_framework_files_unchanged=True,
            recommendation_activation_files_unchanged=True,
            only_m8_storage_changed=True,
            blocking_findings=[],
            safe_summary="M8 write audit is limited to release-gate evidence files.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        closeout_readiness_report = Phase6CloseoutReadinessReport(
            closeout_readiness_report_id=closeout_readiness_report_id,
            release_gate_report_id=release_gate_report_id,
            readiness_status=readiness_status,
            m1_pass=REQUIRED_PHASE6_MARKERS[0] in observed_phase6_markers,
            m2_pass=REQUIRED_PHASE6_MARKERS[1] in observed_phase6_markers,
            m3_pass=REQUIRED_PHASE6_MARKERS[2] in observed_phase6_markers,
            m4_pass=REQUIRED_PHASE6_MARKERS[3] in observed_phase6_markers,
            m5_pass=REQUIRED_PHASE6_MARKERS[4] in observed_phase6_markers,
            m6_pass=REQUIRED_PHASE6_MARKERS[5] in observed_phase6_markers,
            m7_pass=REQUIRED_PHASE6_MARKERS[6] in observed_phase6_markers,
            m8_release_gate_pass=success,
            ready_for_phase6_main_session_closeout=success,
            ready_for_phase7_handoff_with_known_gaps=success,
            human_closeout_docs_owned_by_phase6_main_session=True,
            blocking_findings=list(blocking_findings),
            known_gaps_to_carry_forward=["character_arc_empty_by_design"],
            safe_summary="M8 readiness is with known gaps when all selected regressions pass.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        regression_manifest = Phase6RegressionManifest(
            regression_manifest_id=regression_manifest_id,
            release_gate_report_id=release_gate_report_id,
            required_phase6_verifier_markers=list(REQUIRED_PHASE6_MARKERS),
            selected_inherited_regression_markers=list(SELECTED_INHERITED_MARKERS),
            verifier_run_record_ids=[record.verifier_run_id for record in verifier_records],
            frontend_build_record_id=self._frontend_record_id(verifier_records),
            bounded_scope=True,
            unbounded_history_scan_performed=False,
            all_required_markers_observed=phase6_pass,
            all_selected_regressions_passed=inherited_pass and frontend_build_passed,
            duration_seconds_total=round(sum(max(0, record.duration_seconds) for record in verifier_records), 3),
            timeout_policy=dict(TIMEOUT_POLICY),
            safe_summary="M8 regression manifest uses the bounded Phase 6 and selected inherited marker set.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        evidence_index = Phase6EvidenceIndex(
            evidence_index_id=evidence_index_id,
            release_gate_report_id=release_gate_report_id,
            safe_evidence_refs=self._safe_evidence_refs(verifier_records),
            milestone_evidence_counts=self._milestone_counts(),
            storage_file_hashes=self._selected_hashes(ALLOWED_STORAGE_FILES + PHASE6_EVIDENCE_FILES),
            forbidden_storage_hashes_before=forbidden_before,
            forbidden_storage_hashes_after=forbidden_before,
            evidence_sensitivity="safe",
            contains_raw_prompt=False,
            contains_raw_response=False,
            contains_hidden_reasoning=False,
            contains_full_prose=False,
            contains_secret_or_credential=False,
            safe_summary="M8 evidence index contains ids, counts, hashes, marker names, and durations only.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        release_gate_report = Phase6ReleaseGateReport(
            release_gate_report_id=release_gate_report_id,
            project_id=LOCAL_PROJECT_ID,
            release_status=release_status,
            closeout_readiness_status=readiness_status,
            phase6_milestones_covered=["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"],
            phase6_required_markers=list(REQUIRED_PHASE6_MARKERS),
            phase6_observed_markers=observed_phase6_markers,
            selected_inherited_markers=observed_inherited_markers,
            frontend_build_passed=frontend_build_passed,
            formal_file_pollution_audit_id=formal_file_pollution_audit_id,
            safety_authority_audit_id=safety_authority_audit_id,
            evidence_index_id=evidence_index_id,
            regression_manifest_id=regression_manifest_id,
            closeout_readiness_report_id=closeout_readiness_report_id,
            known_residuals_report_id=known_residuals_report_id,
            known_residuals_carried_forward=["character_arc_empty_by_design"],
            stable_clean_replay_claimed=False,
            stable_with_known_gaps_preserved=True,
            does_not_create_formal_story_fact=True,
            does_not_execute_apply=True,
            does_not_perform_propagation_rewrite=True,
            does_not_create_active_recommendation=True,
            does_not_mutate_active_framework=True,
            blocking_findings=list(blocking_findings),
            warning_codes=list(warning_codes),
            safe_summary="M8 release gate completed as evidence-only closeout with known residual carried forward.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

        records_to_guard: list[Any] = [
            release_gate_report,
            regression_manifest,
            *verifier_records,
            evidence_index,
            closeout_readiness_report,
            safety_authority_audit,
            formal_file_pollution_audit,
            known_residuals_report,
        ]
        for record in records_to_guard:
            self._guard_safe_payload(model_to_dict(record))

        allowed_before = self._allowed_storage_snapshot()
        if self._selected_hashes(FORBIDDEN_STORAGE_FILES) != forbidden_before:
            raise StorageError("PHASE6_M8_FORBIDDEN_STORAGE_MUTATION: forbidden_hash_changed_before_write")
        try:
            self._append(self.release_gate_reports_file, model_to_dict(release_gate_report))
            self._append(self.regression_manifests_file, model_to_dict(regression_manifest))
            for record in verifier_records:
                self._append(self.verifier_run_records_file, model_to_dict(record))
            self._append(self.evidence_indexes_file, model_to_dict(evidence_index))
            self._append(self.closeout_readiness_reports_file, model_to_dict(closeout_readiness_report))
            self._append(self.safety_authority_audits_file, model_to_dict(safety_authority_audit))
            self._append(self.formal_file_pollution_audits_file, model_to_dict(formal_file_pollution_audit))
            self._append(self.known_residuals_reports_file, model_to_dict(known_residuals_report))

            after_all = self._storage_fingerprints()
            forbidden_after = self._selected_hashes(FORBIDDEN_STORAGE_FILES)
            if forbidden_after != forbidden_before:
                raise StorageError("PHASE6_M8_FORBIDDEN_STORAGE_MUTATION: forbidden_hash_changed")
            self._assert_only_m8_changed(before_all, after_all)
            self._assert_hashes_unchanged(m1_m7_before, after_all, "PHASE6_M8_FORBIDDEN_STORAGE_MUTATION: m1_m7_evidence_changed")
            self._assert_hashes_unchanged(formal_before, after_all, "PHASE6_M8_FORBIDDEN_STORAGE_MUTATION: formal_story_file_changed")
            self._assert_hashes_unchanged(framework_before, after_all, "PHASE6_M8_FORBIDDEN_STORAGE_MUTATION: active_framework_file_changed")
            self._assert_hashes_unchanged(recommendation_before, after_all, "PHASE6_M8_FORBIDDEN_STORAGE_MUTATION: recommendation_activation_file_changed")
        except StorageError:
            self._restore_allowed_storage(allowed_before)
            raise

        return Phase6ReleaseGateRunResult(
            success=success,
            release_gate_report=release_gate_report,
            regression_manifest=regression_manifest,
            verifier_run_records=verifier_records,
            evidence_index=evidence_index,
            closeout_readiness_report=closeout_readiness_report,
            safety_authority_audit=safety_authority_audit,
            formal_file_pollution_audit=formal_file_pollution_audit,
            known_residuals_report=known_residuals_report,
            safe_summary="M8 records were written without non-M8 storage mutation.",
        )

    def list_reports(self) -> Phase6ReleaseGateReportListResponse:
        reports = self._read_models_if_exists(self.release_gate_reports_file, Phase6ReleaseGateReport)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return Phase6ReleaseGateReportListResponse(reports=reports, total_count=len(reports))

    def get_report(self, release_gate_report_id: str) -> Phase6ReleaseGateReport:
        return self._get_by_id(
            self.release_gate_reports_file,
            Phase6ReleaseGateReport,
            "release_gate_report_id",
            release_gate_report_id,
            "PHASE6_M8_RELEASE_GATE_REPORT_NOT_FOUND",
        )

    def list_regression_manifests(self) -> Phase6RegressionManifestListResponse:
        records = self._read_models_if_exists(self.regression_manifests_file, Phase6RegressionManifest)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return Phase6RegressionManifestListResponse(regression_manifests=records, total_count=len(records))

    def get_regression_manifest(self, manifest_id: str) -> Phase6RegressionManifest:
        return self._get_by_id(
            self.regression_manifests_file,
            Phase6RegressionManifest,
            "regression_manifest_id",
            manifest_id,
            "PHASE6_M8_REGRESSION_MANIFEST_NOT_FOUND",
        )

    def list_verifier_runs(self) -> Phase6VerifierRunRecordListResponse:
        records = self._read_models_if_exists(self.verifier_run_records_file, Phase6VerifierRunRecord)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return Phase6VerifierRunRecordListResponse(verifier_runs=records, total_count=len(records))

    def get_verifier_run(self, verifier_run_id: str) -> Phase6VerifierRunRecord:
        return self._get_by_id(
            self.verifier_run_records_file,
            Phase6VerifierRunRecord,
            "verifier_run_id",
            verifier_run_id,
            "PHASE6_M8_VERIFIER_RUN_NOT_FOUND",
        )

    def list_evidence_indexes(self) -> Phase6EvidenceIndexListResponse:
        records = self._read_models_if_exists(self.evidence_indexes_file, Phase6EvidenceIndex)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return Phase6EvidenceIndexListResponse(evidence_indexes=records, total_count=len(records))

    def get_evidence_index(self, evidence_index_id: str) -> Phase6EvidenceIndex:
        return self._get_by_id(
            self.evidence_indexes_file,
            Phase6EvidenceIndex,
            "evidence_index_id",
            evidence_index_id,
            "PHASE6_M8_EVIDENCE_INDEX_NOT_FOUND",
        )

    def list_closeout_readiness_reports(self) -> Phase6CloseoutReadinessReportListResponse:
        records = self._read_models_if_exists(self.closeout_readiness_reports_file, Phase6CloseoutReadinessReport)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return Phase6CloseoutReadinessReportListResponse(closeout_readiness_reports=records, total_count=len(records))

    def get_closeout_readiness_report(self, closeout_report_id: str) -> Phase6CloseoutReadinessReport:
        return self._get_by_id(
            self.closeout_readiness_reports_file,
            Phase6CloseoutReadinessReport,
            "closeout_readiness_report_id",
            closeout_report_id,
            "PHASE6_M8_CLOSEOUT_READINESS_REPORT_NOT_FOUND",
        )

    def list_safety_authority_audits(self) -> Phase6SafetyAuthorityAuditListResponse:
        records = self._read_models_if_exists(self.safety_authority_audits_file, Phase6SafetyAuthorityAudit)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return Phase6SafetyAuthorityAuditListResponse(safety_authority_audits=records, total_count=len(records))

    def get_safety_authority_audit(self, audit_id: str) -> Phase6SafetyAuthorityAudit:
        return self._get_by_id(
            self.safety_authority_audits_file,
            Phase6SafetyAuthorityAudit,
            "safety_authority_audit_id",
            audit_id,
            "PHASE6_M8_SAFETY_AUTHORITY_AUDIT_NOT_FOUND",
        )

    def list_formal_file_pollution_audits(self) -> Phase6FormalFilePollutionAuditListResponse:
        records = self._read_models_if_exists(self.formal_file_pollution_audits_file, Phase6FormalFilePollutionAudit)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return Phase6FormalFilePollutionAuditListResponse(formal_file_pollution_audits=records, total_count=len(records))

    def get_formal_file_pollution_audit(self, audit_id: str) -> Phase6FormalFilePollutionAudit:
        return self._get_by_id(
            self.formal_file_pollution_audits_file,
            Phase6FormalFilePollutionAudit,
            "formal_file_pollution_audit_id",
            audit_id,
            "PHASE6_M8_FORMAL_FILE_POLLUTION_AUDIT_NOT_FOUND",
        )

    def list_known_residuals_reports(self) -> Phase6KnownResidualsCarryForwardReportListResponse:
        records = self._read_models_if_exists(self.known_residuals_reports_file, Phase6KnownResidualsCarryForwardReport)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return Phase6KnownResidualsCarryForwardReportListResponse(known_residuals_reports=records, total_count=len(records))

    def get_known_residuals_report(self, residual_report_id: str) -> Phase6KnownResidualsCarryForwardReport:
        return self._get_by_id(
            self.known_residuals_reports_file,
            Phase6KnownResidualsCarryForwardReport,
            "known_residuals_report_id",
            residual_report_id,
            "PHASE6_M8_KNOWN_RESIDUALS_REPORT_NOT_FOUND",
        )

    def _validate_observation(self, observation: VerifierMarkerObservation) -> None:
        if len(observation.safe_output_excerpt) > 1200:
            raise StorageError("PHASE6_M8_UNSAFE_PAYLOAD_BLOCKED: safe_output_excerpt_too_long")
        if len(observation.command) > 500:
            raise StorageError("PHASE6_M8_UNSAFE_PAYLOAD_BLOCKED: command_too_long")
        if observation.expected_marker not in REQUIRED_ALL_MARKERS:
            raise StorageError(f"PHASE6_M8_RELEASE_GATE_BLOCKED: unexpected_marker:{observation.expected_marker}")

    def _build_verifier_records(
        self,
        observations: list[VerifierMarkerObservation],
        report_id: str,
        timestamp: str,
    ) -> list[Phase6VerifierRunRecord]:
        records = []
        for index, observation in enumerate(observations, start=1):
            records.append(
                Phase6VerifierRunRecord(
                    verifier_run_id=f"{report_id}_verifier_run_{index:03d}",
                    release_gate_report_id=report_id,
                    scope=self._scope_for_marker(observation.expected_marker),
                    command=self._short(observation.command, 500),
                    expected_marker=observation.expected_marker,
                    observed_marker=observation.observed_marker if observation.observed_marker == observation.expected_marker else observation.observed_marker,
                    run_status=observation.run_status,
                    duration_seconds=round(max(0, observation.duration_seconds), 3),
                    timeout_seconds=max(0, observation.timeout_seconds),
                    safe_output_excerpt=self._short(observation.safe_output_excerpt, 1200),
                    evidence_ref=self._safe_ref(observation.evidence_ref or observation.marker_name or observation.expected_marker),
                    created_at=timestamp,
                    updated_at=timestamp,
                    version_id=SCHEMA_VERSION,
                )
            )
        return records

    def _scope_for_marker(self, marker: str) -> str:
        if marker.startswith("PHASE6_M"):
            return "phase6_m1_m7"
        if marker.startswith("PHASE5_M8"):
            return "phase5_m8_full_with_selected_phase4"
        if marker == FRONTEND_BUILD_MARKER:
            return "frontend_build"
        return "m8_release_gate"

    def _observed_markers(self, observations: list[VerifierMarkerObservation], expected: list[str]) -> list[str]:
        output = []
        for marker in expected:
            if any(
                observation.expected_marker == marker
                and observation.observed_marker == marker
                and observation.run_status == "pass"
                for observation in observations
            ):
                output.append(marker)
        return output

    def _frontend_record_id(self, records: list[Phase6VerifierRunRecord]) -> str | None:
        for record in records:
            if record.scope == "frontend_build":
                return record.verifier_run_id
        return None

    def _safe_evidence_refs(self, records: list[Phase6VerifierRunRecord]) -> list[dict[str, Any]]:
        return [
            {
                "verifier_run_id": record.verifier_run_id,
                "scope": record.scope,
                "expected_marker": record.expected_marker,
                "observed_marker": record.observed_marker,
                "run_status": record.run_status,
                "duration_seconds": record.duration_seconds,
                "evidence_ref": record.evidence_ref,
            }
            for record in records
        ]

    def _milestone_counts(self) -> dict[str, int]:
        groups = {
            "m1": PHASE6_M1_EVIDENCE_FILES,
            "m2": PHASE6_M2_EVIDENCE_FILES,
            "m3": PHASE6_M3_EVIDENCE_FILES,
            "m4": PHASE6_M4_EVIDENCE_FILES,
            "m5": PHASE6_M5_EVIDENCE_FILES,
            "m6": PHASE6_M6_EVIDENCE_FILES,
            "m7": PHASE6_M7_EVIDENCE_FILES,
            "m8": ALLOWED_STORAGE_FILES,
        }
        return {
            key: sum(self._record_count(self.data_dir / file_name) for file_name in file_names)
            for key, file_names in groups.items()
        }

    def _record_count(self, path: Path) -> int:
        if not self.store.exists(path):
            return 0
        payload = self.store.read_any(path)
        if isinstance(payload, list):
            return len(payload)
        if isinstance(payload, dict):
            return 1
        return 0

    def _read_models_if_exists(self, path: Path, model: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        return [model(**item) for item in self.store.read_list(path)]

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        return [item for item in self.store.read_list(path) if isinstance(item, dict)]

    def _append(self, path: Path, item: dict[str, Any]) -> None:
        values = self._read_list(path)
        values.append(item)
        self.store.write(path, values)

    def _allowed_storage_snapshot(self) -> dict[str, str | None]:
        snapshot: dict[str, str | None] = {}
        for file_name in ALLOWED_STORAGE_FILES:
            path = self.data_dir / file_name
            if path.exists():
                try:
                    snapshot[file_name] = path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise StorageError(f"PHASE6_M8_STORAGE_SCAN_FAILED: {file_name}") from exc
            else:
                snapshot[file_name] = None
        return snapshot

    def _restore_allowed_storage(self, snapshot: dict[str, str | None]) -> None:
        for file_name, content in snapshot.items():
            path = self.data_dir / file_name
            try:
                if content is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
            except OSError as exc:
                raise StorageError(f"PHASE6_M8_ROLLBACK_FAILED: {file_name}") from exc

    def _get_by_id(
        self,
        path: Path,
        model: type[BaseModel],
        key: str,
        value: str,
        error_code: str,
    ) -> Any:
        self._guard_safe_id(value, key)
        for item in self._read_models_if_exists(path, model):
            if getattr(item, key) == value:
                return item
        raise StorageError(f"{error_code}: {value}")

    def _next_id(self, prefix: str, path: Path, id_key: str) -> str:
        max_index = 0
        for item in self._read_list(path):
            raw = str(item.get(id_key, ""))
            if raw.startswith(prefix):
                suffix = raw.removeprefix(prefix).strip("_")
                try:
                    max_index = max(max_index, int(suffix.split("_")[0]))
                except ValueError:
                    continue
        return f"{prefix}_{max_index + 1:03d}"

    def _storage_fingerprints(self) -> dict[str, str]:
        fingerprints: dict[str, str] = {}
        if not self.data_dir.exists():
            return fingerprints
        for path in sorted(self.data_dir.glob("*.json")):
            try:
                fingerprints[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise StorageError(f"PHASE6_M8_STORAGE_SCAN_FAILED: {path.name}") from exc
        return fingerprints

    def _selected_hashes(self, file_names: list[str]) -> dict[str, str]:
        all_hashes = self._storage_fingerprints()
        return {file_name: all_hashes[file_name] for file_name in file_names if file_name in all_hashes}

    def _assert_only_m8_changed(self, before: dict[str, str], after: dict[str, str]) -> None:
        changed = {name for name, value in after.items() if before.get(name) != value}
        changed.update(set(before) - set(after))
        unexpected = sorted(changed - set(ALLOWED_STORAGE_FILES))
        if unexpected:
            raise StorageError(f"PHASE6_M8_FORBIDDEN_STORAGE_MUTATION: {unexpected}")

    def _assert_hashes_unchanged(self, before_subset: dict[str, str | None], after: dict[str, str], error: str) -> None:
        for file_name, before_hash in before_subset.items():
            if before_hash != after.get(file_name):
                raise StorageError(f"{error}:{file_name}")

    def _guard_safe_id(self, value: str, label: str) -> None:
        if not value or not SAFE_ID_RE.match(value):
            raise StorageError(f"PHASE6_M8_UNSAFE_PAYLOAD_BLOCKED: {label}")
        self._guard_safe_payload({label: value})

    def _guard_safe_payload(self, payload: Any) -> None:
        def visit(value: Any, path: str) -> None:
            if isinstance(value, BaseModel):
                visit(model_to_dict(value), path)
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    safe_negative_boolean = (
                        isinstance(child, bool)
                        and (
                            (normalized_key.startswith("contains") and child is False)
                            or (normalized_key.startswith("no") and child is True)
                            or (normalized_key.startswith("doesnot") and child is True)
                        )
                    )
                    if not safe_negative_boolean and any(part in normalized_key for part in UNSAFE_KEY_PARTS):
                        raise StorageError(f"PHASE6_M8_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"PHASE6_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"PHASE6_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"PHASE6_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")

        visit(payload, "$")

    def _safe_ref(self, value: Any) -> str:
        text = self._short(value or "unknown", 180)
        text = re.sub(r"[^a-zA-Z0-9_:\-.]", "_", text)
        return text or "unknown"

    def _short(self, value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."
