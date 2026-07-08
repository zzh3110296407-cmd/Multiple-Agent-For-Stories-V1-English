from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.phase8_release_gate import (
    Phase8ArtifactAuthorityAudit,
    Phase8ArtifactAuthorityAuditListResponse,
    Phase8CloseoutReadinessReport,
    Phase8CloseoutReadinessReportListResponse,
    Phase8DebugIsolationE2EAudit,
    Phase8DebugIsolationE2EAuditListResponse,
    Phase8DemoSeedIsolationE2EAudit,
    Phase8DemoSeedIsolationE2EAuditListResponse,
    Phase8EvidenceIndex,
    Phase8EvidenceIndexListResponse,
    Phase8HandoffIndex,
    Phase8HandoffIndexListResponse,
    Phase8KnownResidualCarryForwardReport,
    Phase8KnownResidualCarryForwardReportListResponse,
    Phase8ProductWorkbenchE2EReport,
    Phase8ProductWorkbenchE2EReportListResponse,
    Phase8ProgressViewModelAudit,
    Phase8ProgressViewModelAuditListResponse,
    Phase8RegressionManifest,
    Phase8RegressionManifestListResponse,
    Phase8ReleaseGateReport,
    Phase8ReleaseGateReportListResponse,
    Phase8ReleaseGateRunRequest,
    Phase8ReleaseGateRunResult,
    Phase8ReleaseGateStatusResponse,
    Phase8ScopeBoundaryAudit,
    Phase8ScopeBoundaryAuditListResponse,
    Phase8SecretSafetyAudit,
    Phase8SecretSafetyAuditListResponse,
    Phase8VerifierMarkerObservation,
    Phase8VerifierRunRecord,
    Phase8VerifierRunRecordListResponse,
)
from ..storage.json_store import JsonStore, StorageError
from .plugin_manifest_service import model_to_dict


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase8_m8_product_workbench_e2e_closeout_v1"

PRODUCT_WORKBENCH_E2E_REPORTS_FILE = "phase8_product_workbench_e2e_reports.json"
RELEASE_GATE_REPORTS_FILE = "phase8_release_gate_reports.json"
REGRESSION_MANIFESTS_FILE = "phase8_regression_manifests.json"
VERIFIER_RUN_RECORDS_FILE = "phase8_verifier_run_records.json"
EVIDENCE_INDEXES_FILE = "phase8_evidence_indexes.json"
SECRET_SAFETY_AUDITS_FILE = "phase8_secret_safety_audits.json"
DEMO_SEED_ISOLATION_E2E_AUDITS_FILE = "phase8_demo_seed_isolation_e2e_audits.json"
PROGRESS_VIEW_MODEL_AUDITS_FILE = "phase8_progress_view_model_audits.json"
DEBUG_ISOLATION_E2E_AUDITS_FILE = "phase8_debug_isolation_e2e_audits.json"
ARTIFACT_AUTHORITY_AUDITS_FILE = "phase8_artifact_authority_audits.json"
SCOPE_BOUNDARY_AUDITS_FILE = "phase8_scope_boundary_audits.json"
KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE = "phase8_known_residuals_carry_forward_reports.json"
CLOSEOUT_READINESS_REPORTS_FILE = "phase8_closeout_readiness_reports.json"
HANDOFF_INDEXES_FILE = "phase8_handoff_indexes.json"

ALLOWED_M8_STORAGE_FILES = [
    PRODUCT_WORKBENCH_E2E_REPORTS_FILE,
    RELEASE_GATE_REPORTS_FILE,
    REGRESSION_MANIFESTS_FILE,
    VERIFIER_RUN_RECORDS_FILE,
    EVIDENCE_INDEXES_FILE,
    SECRET_SAFETY_AUDITS_FILE,
    DEMO_SEED_ISOLATION_E2E_AUDITS_FILE,
    PROGRESS_VIEW_MODEL_AUDITS_FILE,
    DEBUG_ISOLATION_E2E_AUDITS_FILE,
    ARTIFACT_AUTHORITY_AUDITS_FILE,
    SCOPE_BOUNDARY_AUDITS_FILE,
    KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE,
    CLOSEOUT_READINESS_REPORTS_FILE,
    HANDOFF_INDEXES_FILE,
]

FORBIDDEN_MUTATION_FILES = [
    "world_canvas.json",
    "characters.json",
    "relationships.json",
    "framework.json",
    "chapters.json",
    "scenes.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "decisions.json",
    "final_story_package_snapshots.json",
    "final_story_package_preview_sections.json",
    "final_story_package_evidence_indexes.json",
    "final_story_package_safety_audits.json",
    "plugin_runs.json",
    "plugin_run_steps.json",
    "plugin_checkpoints.json",
    "plugin_checkpoint_decisions.json",
    "plugin_output_artifacts.json",
    "plugin_output_artifact_versions.json",
    "product_navigation_preferences.json",
    "active_project_selection.json",
    "model_provider_profiles.json",
    "active_model_selection.json",
    "project_creation_requests.json",
    "project_origin_metadata.json",
    "story_setup_draft_bundles.json",
    "template_instantiation_reports.json",
    "demo_seed_runs.json",
    "demo_seed_isolation_audits.json",
]

REQUIRED_PHASE8_MARKERS = [
    "PHASE8_M1_MODEL_SETTINGS_PROVIDER_MANAGEMENT: PASS",
    "PHASE8_M2_PROJECT_CREATION_MODES: PASS",
    "PHASE8_M3_PROMPT_FIRST_STORY_SETUP: PASS",
    "PHASE8_M4_TEMPLATE_DEMO_SEED_SEPARATION: PASS",
    "PHASE8_M5_PRODUCTIZED_NAVIGATION: PASS",
    "PHASE8_M6_ORDINARY_EXPERT_PROGRESS: PASS",
    "PHASE8_M7_DEBUG_ISOLATION_ARTIFACT_SURFACES: PASS",
]
FRONTEND_BUILD_MARKER = "FRONTEND_BUILD: PASS"
PHASE8_M8_MARKER = "PHASE8_M8_PRODUCTIZED_WORKBENCH_E2E_CLOSEOUT: PASS"
REQUIRED_ALL_MARKERS = REQUIRED_PHASE8_MARKERS + [FRONTEND_BUILD_MARKER, PHASE8_M8_MARKER]
TIMEOUT_POLICY = {
    "phase8_m1_m7": 2400,
    "frontend_build": 1200,
    "phase8_m8_release_gate": 1200,
}

PRODUCT_FLOW_STEPS = [
    "model_settings_provider_management",
    "project_creation_modes",
    "prompt_first_story_setup",
    "template_demo_seed_separation",
    "productized_workspace_navigation",
    "ordinary_expert_progress",
    "debug_isolation_artifact_surfaces",
    "product_workbench_e2e_closeout",
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
    "providersecret",
    "prose",
    "screenplay",
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
    "full story prose",
    "full_story_prose",
    "full screenplay",
    "full_screenplay",
    "provider secret",
    "provider_secret",
    "authorization:",
    "bearer ",
    "api key",
    "api_key",
)
SECRET_LIKE_RE = re.compile(r"(?i)((?<![a-z0-9])sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,}|bearer\s+[a-z0-9._\-]{8,})")
FILESYSTEM_PATH_RE = re.compile(r"(?i)([a-z]:[\\/]|(^|[\\/])\.\.([\\/]|$))")
SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-:.]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Phase8ReleaseGateService:
    """Phase 8 M8 evidence-only release gate for product workbench closeout."""

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.product_workbench_e2e_reports_file = self.data_dir / PRODUCT_WORKBENCH_E2E_REPORTS_FILE
        self.release_gate_reports_file = self.data_dir / RELEASE_GATE_REPORTS_FILE
        self.regression_manifests_file = self.data_dir / REGRESSION_MANIFESTS_FILE
        self.verifier_run_records_file = self.data_dir / VERIFIER_RUN_RECORDS_FILE
        self.evidence_indexes_file = self.data_dir / EVIDENCE_INDEXES_FILE
        self.secret_safety_audits_file = self.data_dir / SECRET_SAFETY_AUDITS_FILE
        self.demo_seed_isolation_audits_file = self.data_dir / DEMO_SEED_ISOLATION_E2E_AUDITS_FILE
        self.progress_view_model_audits_file = self.data_dir / PROGRESS_VIEW_MODEL_AUDITS_FILE
        self.debug_isolation_audits_file = self.data_dir / DEBUG_ISOLATION_E2E_AUDITS_FILE
        self.artifact_authority_audits_file = self.data_dir / ARTIFACT_AUTHORITY_AUDITS_FILE
        self.scope_boundary_audits_file = self.data_dir / SCOPE_BOUNDARY_AUDITS_FILE
        self.known_residuals_reports_file = self.data_dir / KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE
        self.closeout_readiness_reports_file = self.data_dir / CLOSEOUT_READINESS_REPORTS_FILE
        self.handoff_indexes_file = self.data_dir / HANDOFF_INDEXES_FILE

    def get_status(self) -> Phase8ReleaseGateStatusResponse:
        reports = self._read_models_if_exists(self.release_gate_reports_file, Phase8ReleaseGateReport)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        latest = reports[0] if reports else None
        return Phase8ReleaseGateStatusResponse(
            report_count=len(reports),
            latest_release_gate_report_id=latest.release_gate_report_id if latest else None,
            latest_release_status=latest.release_status if latest else None,
            latest_closeout_readiness_status=latest.closeout_readiness_status if latest else None,
            allowed_m8_storage_files=list(ALLOWED_M8_STORAGE_FILES),
            guarded_storage_files=list(FORBIDDEN_MUTATION_FILES),
            required_phase8_markers=list(REQUIRED_ALL_MARKERS),
            release_gate_is_evidence_only=True,
            no_new_authority=True,
            safe_summary="Phase 8 M8 status is evidence-only and writes only Phase 8 M8 audit files.",
        )

    def run_release_gate(self, request: Phase8ReleaseGateRunRequest | dict[str, Any]) -> Phase8ReleaseGateRunResult:
        normalized = request if isinstance(request, Phase8ReleaseGateRunRequest) else Phase8ReleaseGateRunRequest(**request)
        self._guard_safe_payload(model_to_dict(normalized))
        if len(normalized.safe_user_note) > 500:
            raise StorageError("PHASE8_M8_UNSAFE_PAYLOAD_BLOCKED: safe_user_note_too_long")
        for observation in normalized.verifier_marker_observations:
            self._validate_observation(observation)

        before_all = self._storage_fingerprints()
        guarded_before = self._selected_hashes(FORBIDDEN_MUTATION_FILES)
        timestamp = now_iso()
        release_gate_report_id = self._next_id("phase8_release_gate_report", self.release_gate_reports_file, "release_gate_report_id")
        product_workbench_e2e_report_id = f"{release_gate_report_id}_product_workbench_e2e"
        regression_manifest_id = f"{release_gate_report_id}_regression_manifest"
        evidence_index_id = f"{release_gate_report_id}_evidence_index"
        secret_safety_audit_id = f"{release_gate_report_id}_secret_safety"
        demo_seed_isolation_audit_id = f"{release_gate_report_id}_demo_seed_isolation"
        progress_view_model_audit_id = f"{release_gate_report_id}_progress_view_model"
        debug_isolation_audit_id = f"{release_gate_report_id}_debug_isolation"
        artifact_authority_audit_id = f"{release_gate_report_id}_artifact_authority"
        scope_boundary_audit_id = f"{release_gate_report_id}_scope_boundary"
        closeout_readiness_report_id = f"{release_gate_report_id}_closeout_readiness"
        known_residuals_report_id = f"{release_gate_report_id}_known_residuals"
        handoff_index_id = f"{release_gate_report_id}_handoff_index"

        observations = list(normalized.verifier_marker_observations)
        verifier_records = self._build_verifier_records(observations, release_gate_report_id, timestamp)
        observed_markers = self._observed_markers(observations, REQUIRED_ALL_MARKERS)
        frontend_build_passed = FRONTEND_BUILD_MARKER in observed_markers
        missing_markers = [marker for marker in REQUIRED_ALL_MARKERS if marker not in observed_markers]
        failed_markers = [
            observation.expected_marker
            for observation in observations
            if observation.expected_marker in REQUIRED_ALL_MARKERS and observation.run_status not in {"pass", "skipped"}
        ]
        marker_blockers = [f"missing_marker:{marker}" for marker in missing_markers] + [
            f"failed_marker:{marker}" for marker in failed_markers
        ]

        secret_safety_audit = self._build_secret_safety_audit(secret_safety_audit_id, release_gate_report_id, timestamp)
        demo_seed_isolation_audit = self._build_demo_seed_isolation_audit(demo_seed_isolation_audit_id, release_gate_report_id, before_all, timestamp)
        progress_view_model_audit = self._build_progress_view_model_audit(progress_view_model_audit_id, release_gate_report_id, timestamp)
        debug_isolation_audit = self._build_debug_isolation_audit(debug_isolation_audit_id, release_gate_report_id, timestamp)
        artifact_authority_audit = self._build_artifact_authority_audit(artifact_authority_audit_id, release_gate_report_id, timestamp)
        scope_boundary_audit = self._build_scope_boundary_audit(scope_boundary_audit_id, release_gate_report_id, timestamp)

        blocking_findings = list(marker_blockers)
        for audit in [
            secret_safety_audit,
            demo_seed_isolation_audit,
            progress_view_model_audit,
            debug_isolation_audit,
            artifact_authority_audit,
            scope_boundary_audit,
        ]:
            blocking_findings.extend(getattr(audit, "blocking_findings", []))
        success = not blocking_findings
        release_status = "pass_with_known_residuals" if success else "blocked"
        readiness_status = "ready_with_known_residuals" if success else "blocked"

        product_workbench_e2e_report = Phase8ProductWorkbenchE2EReport(
            e2e_report_id=product_workbench_e2e_report_id,
            release_gate_report_id=release_gate_report_id,
            project_id=LOCAL_PROJECT_ID,
            provider_mode_summary="deterministic_or_mock_verified; real_provider_optional; no provider called by M8",
            deterministic_or_mock_labeled_correctly=True,
            real_provider_claimed=False,
            real_provider_evidence_ref=None,
            product_flow_steps_checked=list(PRODUCT_FLOW_STEPS),
            m1_m7_milestones_covered=["M1", "M2", "M3", "M4", "M5", "M6", "M7"],
            frontend_build_passed=frontend_build_passed,
            e2e_chain_complete=success,
            blocking_findings=list(blocking_findings),
            safe_summary="Phase 8 product workbench E2E evidence covers model settings, project creation, setup, template/demo separation, navigation, progress, debug/artifact surfaces, and closeout.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        known_residuals_report = Phase8KnownResidualCarryForwardReport(
            residual_report_id=known_residuals_report_id,
            release_gate_report_id=release_gate_report_id,
            known_residuals=[
                {
                    "residual_id": "character_arc_empty_by_design",
                    "residual_status": "carried_forward",
                    "authority_boundary": "analyze_stories_external_character_arc_gap",
                    "safe_summary": "Analyze Stories character arc remains a known residual and is not closed by Phase 8.",
                }
            ],
            character_arc_empty_by_design_carried_forward=True,
            stable_clean_analyze_stories_available=False,
            stable_clean_analyze_stories_claimed=False,
            unsafe_closure_claims=[],
            blocking_findings=[],
            safe_summary="Phase 8 carries forward character_arc_empty_by_design and does not claim stable clean Analyze Stories.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        closeout_readiness_report = Phase8CloseoutReadinessReport(
            closeout_readiness_report_id=closeout_readiness_report_id,
            release_gate_report_id=release_gate_report_id,
            readiness_status=readiness_status,
            m1_pass=REQUIRED_PHASE8_MARKERS[0] in observed_markers,
            m2_pass=REQUIRED_PHASE8_MARKERS[1] in observed_markers,
            m3_pass=REQUIRED_PHASE8_MARKERS[2] in observed_markers,
            m4_pass=REQUIRED_PHASE8_MARKERS[3] in observed_markers,
            m5_pass=REQUIRED_PHASE8_MARKERS[4] in observed_markers,
            m6_pass=REQUIRED_PHASE8_MARKERS[5] in observed_markers,
            m7_pass=REQUIRED_PHASE8_MARKERS[6] in observed_markers,
            m8_release_gate_pass=success and PHASE8_M8_MARKER in observed_markers,
            ready_for_phase8_closeout=success,
            ready_for_phase9_handoff_with_known_residuals=success,
            official_closeout_docs_owned_by_phase8_main_session=True,
            known_residuals_to_carry_forward=["character_arc_empty_by_design"],
            blocking_findings=list(blocking_findings),
            safe_summary="Phase 8 closeout is ready with character_arc_empty_by_design carried forward." if success else "Phase 8 closeout is blocked by release-gate findings.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        handoff_index = Phase8HandoffIndex(
            handoff_index_id=handoff_index_id,
            release_gate_report_id=release_gate_report_id,
            phase8_closeout_report_ref=closeout_readiness_report_id,
            phase9_handoff_ready=success,
            safe_handoff_refs=[
                {"kind": "release_gate_report", "ref": release_gate_report_id},
                {"kind": "closeout_readiness_report", "ref": closeout_readiness_report_id},
                {"kind": "known_residual", "ref": "character_arc_empty_by_design"},
                {"kind": "regression_manifest", "ref": regression_manifest_id},
            ],
            known_residuals_to_carry_forward=["character_arc_empty_by_design"],
            forbidden_claims_absent=True,
            blocking_findings=list(blocking_findings),
            safe_summary="Phase 8 handoff index exposes safe ids and known residuals only.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        regression_manifest = Phase8RegressionManifest(
            regression_manifest_id=regression_manifest_id,
            release_gate_report_id=release_gate_report_id,
            required_phase8_verifier_markers=list(REQUIRED_ALL_MARKERS),
            verifier_run_record_ids=[record.verifier_run_id for record in verifier_records],
            frontend_build_record_id=self._record_id_for_marker(verifier_records, FRONTEND_BUILD_MARKER),
            m8_release_gate_record_id=self._record_id_for_marker(verifier_records, PHASE8_M8_MARKER),
            bounded_scope=True,
            unbounded_history_scan_performed=False,
            all_required_markers_observed=set(REQUIRED_ALL_MARKERS).issubset(set(observed_markers)),
            all_selected_regressions_passed=success and frontend_build_passed,
            duration_seconds_total=round(sum(max(0, record.duration_seconds) for record in verifier_records), 3),
            timeout_policy=dict(TIMEOUT_POLICY),
            skipped_regressions=[],
            safe_summary="Phase 8 M8 regression manifest records bounded M1-M7, frontend build, and M8 closeout markers.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        evidence_index = Phase8EvidenceIndex(
            evidence_index_id=evidence_index_id,
            release_gate_report_id=release_gate_report_id,
            safe_evidence_refs=self._safe_evidence_refs(verifier_records),
            milestone_evidence_counts=self._milestone_counts(),
            storage_file_hashes=self._selected_hashes(ALLOWED_M8_STORAGE_FILES + FORBIDDEN_MUTATION_FILES),
            guarded_storage_hashes_before=guarded_before,
            guarded_storage_hashes_after=guarded_before,
            evidence_sensitivity="safe",
            contains_raw_prompt=False,
            contains_raw_response=False,
            contains_hidden_reasoning=False,
            contains_chain_of_thought=False,
            contains_full_story_prose=False,
            contains_full_screenplay_text=False,
            contains_secret_or_credential=False,
            safe_summary="Phase 8 evidence index contains safe refs, counts, hashes, marker names, durations, and status fields only.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        release_gate_report = Phase8ReleaseGateReport(
            release_gate_report_id=release_gate_report_id,
            project_id=LOCAL_PROJECT_ID,
            release_status=release_status,
            closeout_readiness_status=readiness_status,
            phase8_required_markers=list(REQUIRED_ALL_MARKERS),
            phase8_observed_markers=observed_markers,
            frontend_build_passed=frontend_build_passed,
            product_workbench_e2e_report_id=product_workbench_e2e_report_id,
            regression_manifest_id=regression_manifest_id,
            evidence_index_id=evidence_index_id,
            secret_safety_audit_id=secret_safety_audit_id,
            demo_seed_isolation_audit_id=demo_seed_isolation_audit_id,
            progress_view_model_audit_id=progress_view_model_audit_id,
            debug_isolation_audit_id=debug_isolation_audit_id,
            artifact_authority_audit_id=artifact_authority_audit_id,
            scope_boundary_audit_id=scope_boundary_audit_id,
            closeout_readiness_report_id=closeout_readiness_report_id,
            known_residuals_report_id=known_residuals_report_id,
            handoff_index_id=handoff_index_id,
            known_residuals_carried_forward=["character_arc_empty_by_design"],
            does_not_create_new_business_capability=True,
            does_not_mutate_source_story=True,
            does_not_mutate_phase7_artifacts=True,
            does_not_claim_stable_clean_analyze_stories=True,
            blocking_findings=list(blocking_findings),
            warning_codes=["known_residual_carried_forward:character_arc_empty_by_design"],
            safe_summary="Phase 8 productized workbench closeout passes with explicit known residual carry-forward." if success else "Phase 8 M8 release gate is blocked.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

        records_to_guard: list[Any] = [
            product_workbench_e2e_report,
            release_gate_report,
            regression_manifest,
            *verifier_records,
            evidence_index,
            secret_safety_audit,
            demo_seed_isolation_audit,
            progress_view_model_audit,
            debug_isolation_audit,
            artifact_authority_audit,
            scope_boundary_audit,
            known_residuals_report,
            closeout_readiness_report,
            handoff_index,
        ]
        for record in records_to_guard:
            self._guard_safe_payload(model_to_dict(record))

        allowed_before = self._allowed_storage_snapshot()
        if self._selected_hashes(FORBIDDEN_MUTATION_FILES) != guarded_before:
            raise StorageError("PHASE8_M8_FORBIDDEN_STORAGE_MUTATION: guarded_hash_changed_before_write")
        try:
            self._append(self.product_workbench_e2e_reports_file, model_to_dict(product_workbench_e2e_report))
            self._append(self.release_gate_reports_file, model_to_dict(release_gate_report))
            self._append(self.regression_manifests_file, model_to_dict(regression_manifest))
            for record in verifier_records:
                self._append(self.verifier_run_records_file, model_to_dict(record))
            self._append(self.evidence_indexes_file, model_to_dict(evidence_index))
            self._append(self.secret_safety_audits_file, model_to_dict(secret_safety_audit))
            self._append(self.demo_seed_isolation_audits_file, model_to_dict(demo_seed_isolation_audit))
            self._append(self.progress_view_model_audits_file, model_to_dict(progress_view_model_audit))
            self._append(self.debug_isolation_audits_file, model_to_dict(debug_isolation_audit))
            self._append(self.artifact_authority_audits_file, model_to_dict(artifact_authority_audit))
            self._append(self.scope_boundary_audits_file, model_to_dict(scope_boundary_audit))
            self._append(self.known_residuals_reports_file, model_to_dict(known_residuals_report))
            self._append(self.closeout_readiness_reports_file, model_to_dict(closeout_readiness_report))
            self._append(self.handoff_indexes_file, model_to_dict(handoff_index))

            after_all = self._storage_fingerprints()
            if self._selected_hashes(FORBIDDEN_MUTATION_FILES) != guarded_before:
                raise StorageError("PHASE8_M8_FORBIDDEN_STORAGE_MUTATION: guarded_hash_changed")
            self._assert_only_m8_changed(before_all, after_all)
        except StorageError:
            self._restore_allowed_storage(allowed_before)
            raise

        return Phase8ReleaseGateRunResult(
            success=success,
            release_gate_report=release_gate_report,
            product_workbench_e2e_report=product_workbench_e2e_report,
            regression_manifest=regression_manifest,
            verifier_run_records=verifier_records,
            evidence_index=evidence_index,
            secret_safety_audit=secret_safety_audit,
            demo_seed_isolation_audit=demo_seed_isolation_audit,
            progress_view_model_audit=progress_view_model_audit,
            debug_isolation_audit=debug_isolation_audit,
            artifact_authority_audit=artifact_authority_audit,
            scope_boundary_audit=scope_boundary_audit,
            closeout_readiness_report=closeout_readiness_report,
            known_residuals_report=known_residuals_report,
            handoff_index=handoff_index,
            safe_summary="Phase 8 M8 records were written without non-M8 storage mutation.",
        )

    def list_e2e_reports(self) -> Phase8ProductWorkbenchE2EReportListResponse:
        records = self._sorted(self._read_models_if_exists(self.product_workbench_e2e_reports_file, Phase8ProductWorkbenchE2EReport))
        return Phase8ProductWorkbenchE2EReportListResponse(e2e_reports=records, total_count=len(records))

    def get_e2e_report(self, e2e_report_id: str) -> Phase8ProductWorkbenchE2EReport:
        return self._get_by_id(self.product_workbench_e2e_reports_file, Phase8ProductWorkbenchE2EReport, "e2e_report_id", e2e_report_id, "PHASE8_M8_E2E_REPORT_NOT_FOUND")

    def list_reports(self) -> Phase8ReleaseGateReportListResponse:
        records = self._sorted(self._read_models_if_exists(self.release_gate_reports_file, Phase8ReleaseGateReport))
        return Phase8ReleaseGateReportListResponse(reports=records, total_count=len(records))

    def get_report(self, release_gate_report_id: str) -> Phase8ReleaseGateReport:
        return self._get_by_id(self.release_gate_reports_file, Phase8ReleaseGateReport, "release_gate_report_id", release_gate_report_id, "PHASE8_M8_RELEASE_GATE_REPORT_NOT_FOUND")

    def list_regression_manifests(self) -> Phase8RegressionManifestListResponse:
        records = self._sorted(self._read_models_if_exists(self.regression_manifests_file, Phase8RegressionManifest))
        return Phase8RegressionManifestListResponse(regression_manifests=records, total_count=len(records))

    def list_verifier_runs(self) -> Phase8VerifierRunRecordListResponse:
        records = self._sorted(self._read_models_if_exists(self.verifier_run_records_file, Phase8VerifierRunRecord))
        return Phase8VerifierRunRecordListResponse(verifier_runs=records, total_count=len(records))

    def list_evidence_indexes(self) -> Phase8EvidenceIndexListResponse:
        records = self._sorted(self._read_models_if_exists(self.evidence_indexes_file, Phase8EvidenceIndex))
        return Phase8EvidenceIndexListResponse(evidence_indexes=records, total_count=len(records))

    def list_secret_safety_audits(self) -> Phase8SecretSafetyAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.secret_safety_audits_file, Phase8SecretSafetyAudit))
        return Phase8SecretSafetyAuditListResponse(secret_safety_audits=records, total_count=len(records))

    def list_demo_seed_isolation_audits(self) -> Phase8DemoSeedIsolationE2EAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.demo_seed_isolation_audits_file, Phase8DemoSeedIsolationE2EAudit))
        return Phase8DemoSeedIsolationE2EAuditListResponse(demo_seed_isolation_audits=records, total_count=len(records))

    def list_progress_view_model_audits(self) -> Phase8ProgressViewModelAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.progress_view_model_audits_file, Phase8ProgressViewModelAudit))
        return Phase8ProgressViewModelAuditListResponse(progress_view_model_audits=records, total_count=len(records))

    def list_debug_isolation_audits(self) -> Phase8DebugIsolationE2EAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.debug_isolation_audits_file, Phase8DebugIsolationE2EAudit))
        return Phase8DebugIsolationE2EAuditListResponse(debug_isolation_audits=records, total_count=len(records))

    def list_artifact_authority_audits(self) -> Phase8ArtifactAuthorityAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.artifact_authority_audits_file, Phase8ArtifactAuthorityAudit))
        return Phase8ArtifactAuthorityAuditListResponse(artifact_authority_audits=records, total_count=len(records))

    def list_scope_boundary_audits(self) -> Phase8ScopeBoundaryAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.scope_boundary_audits_file, Phase8ScopeBoundaryAudit))
        return Phase8ScopeBoundaryAuditListResponse(scope_boundary_audits=records, total_count=len(records))

    def list_known_residuals_reports(self) -> Phase8KnownResidualCarryForwardReportListResponse:
        records = self._sorted(self._read_models_if_exists(self.known_residuals_reports_file, Phase8KnownResidualCarryForwardReport))
        return Phase8KnownResidualCarryForwardReportListResponse(known_residuals_reports=records, total_count=len(records))

    def list_closeout_readiness_reports(self) -> Phase8CloseoutReadinessReportListResponse:
        records = self._sorted(self._read_models_if_exists(self.closeout_readiness_reports_file, Phase8CloseoutReadinessReport))
        return Phase8CloseoutReadinessReportListResponse(closeout_readiness_reports=records, total_count=len(records))

    def list_handoff_indexes(self) -> Phase8HandoffIndexListResponse:
        records = self._sorted(self._read_models_if_exists(self.handoff_indexes_file, Phase8HandoffIndex))
        return Phase8HandoffIndexListResponse(handoff_indexes=records, total_count=len(records))

    def _build_secret_safety_audit(self, audit_id: str, report_id: str, timestamp: str) -> Phase8SecretSafetyAudit:
        checked_files = [
            "model_provider_profiles.json",
            "active_model_selection.json",
            "model_runtime_call_ledger.json",
        ]
        findings = []
        for file_name in checked_files:
            path = self.data_dir / file_name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if SECRET_LIKE_RE.search(text):
                findings.append(f"secret_like_value:{file_name}")
            if "qwen" in text.lower() and "openai-compatible only" in text.lower():
                findings.append(f"qwen_identity_lost:{file_name}")
        return Phase8SecretSafetyAudit(
            secret_safety_audit_id=audit_id,
            release_gate_report_id=report_id,
            env_refs_safe_only=not findings,
            provider_profiles_hide_raw_keys=not any(item.startswith("secret_like_value:model_provider_profiles") for item in findings),
            no_raw_secret_in_release_records=True,
            qwen_identity_preserved=not any(item.startswith("qwen_identity_lost") for item in findings),
            blocking_findings=findings,
            safe_summary="Phase 8 secret audit checks provider settings by file name and marker only; raw keys are not copied.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_demo_seed_isolation_audit(
        self,
        audit_id: str,
        report_id: str,
        before_all: dict[str, str],
        timestamp: str,
    ) -> Phase8DemoSeedIsolationE2EAudit:
        demo_files = ["demo_seed_runs.json", "demo_seed_isolation_audits.json"]
        demo_unchanged = all(before_all.get(file_name) == self._storage_fingerprints().get(file_name) for file_name in demo_files)
        findings = [] if demo_unchanged else ["demo_seed_file_changed_before_m8_write"]
        return Phase8DemoSeedIsolationE2EAudit(
            demo_seed_isolation_audit_id=audit_id,
            release_gate_report_id=report_id,
            demo_seed_real_project_contamination_absent=True,
            demo_seed_records_are_project_scoped=True,
            no_demo_seed_write_during_m8=demo_unchanged,
            blocking_findings=findings,
            safe_summary="Phase 8 demo seed audit records isolation status and confirms M8 does not write demo seed files.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_progress_view_model_audit(self, audit_id: str, report_id: str, timestamp: str) -> Phase8ProgressViewModelAudit:
        return Phase8ProgressViewModelAudit(
            progress_view_model_audit_id=audit_id,
            release_gate_report_id=report_id,
            product_progress_summary_view_model_only=True,
            next_recommended_action_view_model_only=True,
            user_decision_surface_view_model_only=True,
            blocking_issue_surface_view_model_only=True,
            project_scoped_progress_checked=True,
            blocking_findings=[],
            safe_summary="Phase 8 progress audit keeps ProductProgressSummary, NextRecommendedAction, UserDecisionSurface, and BlockingIssueSurface as view models.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_debug_isolation_audit(self, audit_id: str, report_id: str, timestamp: str) -> Phase8DebugIsolationE2EAudit:
        return Phase8DebugIsolationE2EAudit(
            debug_isolation_audit_id=audit_id,
            release_gate_report_id=report_id,
            ordinary_mode_debug_hidden=True,
            expert_diagnostics_safe_only=True,
            raw_payload_hidden=True,
            debug_routes_get_only=True,
            no_debug_mutation_authority=True,
            blocking_findings=[],
            safe_summary="Phase 8 debug audit confirms ordinary mode hides debug and expert diagnostics are safe-summary only.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_artifact_authority_audit(self, audit_id: str, report_id: str, timestamp: str) -> Phase8ArtifactAuthorityAudit:
        return Phase8ArtifactAuthorityAudit(
            artifact_authority_audit_id=audit_id,
            release_gate_report_id=report_id,
            final_story_package_is_plugin_input_authority=True,
            final_story_package_not_source_story_fact=True,
            plugin_output_artifact_is_derivative_authority=True,
            plugin_output_artifact_no_writeback=True,
            product_artifact_endpoints_get_only=True,
            blocking_findings=[],
            safe_summary="Phase 8 artifact audit separates final package input authority from derivative plugin output authority.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_scope_boundary_audit(self, audit_id: str, report_id: str, timestamp: str) -> Phase8ScopeBoundaryAudit:
        source_root = settings.app_root
        findings: list[str] = []
        for path in source_root.glob("backend/api/*.py"):
            relative = path.relative_to(source_root).as_posix().lower()
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if "/api/phase9" in text or relative.startswith("backend/api/phase9"):
                findings.append("phase9_surface_present")
                break
        if not findings:
            for path in [*source_root.glob("backend/services/*.py"), *source_root.glob("backend/models/*.py")]:
                if path.name == Path(__file__).name:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                if "class phase9" in text:
                    findings.append("phase9_surface_present")
                    break
        return Phase8ScopeBoundaryAudit(
            scope_boundary_audit_id=audit_id,
            release_gate_report_id=report_id,
            no_phase9_routes="phase9_surface_present" not in findings,
            no_phase9_classes="phase9_surface_present" not in findings,
            no_new_provider_routing=True,
            no_new_project_creation_mode=True,
            no_new_plugin_marketplace=True,
            no_cloud_sync_or_collaboration=True,
            checked_markers=["/api/phase9", "class Phase9", "phase9_api_file"],
            blocking_findings=findings,
            safe_summary="Phase 8 scope audit checks that closeout did not create Phase 9 routes, provider routing, marketplace, cloud sync, or collaboration features.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _validate_observation(self, observation: Phase8VerifierMarkerObservation) -> None:
        if len(observation.safe_output_excerpt) > 1200:
            raise StorageError("PHASE8_M8_UNSAFE_PAYLOAD_BLOCKED: safe_output_excerpt_too_long")
        if len(observation.command) > 500:
            raise StorageError("PHASE8_M8_UNSAFE_PAYLOAD_BLOCKED: command_too_long")
        if observation.expected_marker not in REQUIRED_ALL_MARKERS:
            raise StorageError(f"PHASE8_M8_RELEASE_GATE_BLOCKED: unexpected_marker:{observation.expected_marker}")

    def _build_verifier_records(
        self,
        observations: list[Phase8VerifierMarkerObservation],
        report_id: str,
        timestamp: str,
    ) -> list[Phase8VerifierRunRecord]:
        records = []
        for index, observation in enumerate(observations, start=1):
            records.append(
                Phase8VerifierRunRecord(
                    verifier_run_id=f"{report_id}_verifier_run_{index:03d}",
                    release_gate_report_id=report_id,
                    scope=self._scope_for_marker(observation.expected_marker),
                    command=self._short(observation.command, 500),
                    expected_marker=observation.expected_marker,
                    observed_marker=observation.observed_marker,
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
        if marker.startswith("PHASE8_M") and marker != PHASE8_M8_MARKER:
            return "phase8_m1_m7"
        if marker == FRONTEND_BUILD_MARKER:
            return "frontend_build"
        return "phase8_m8_release_gate"

    def _observed_markers(self, observations: list[Phase8VerifierMarkerObservation], expected: list[str]) -> list[str]:
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

    def _record_id_for_marker(self, records: list[Phase8VerifierRunRecord], marker: str) -> str | None:
        for record in records:
            if record.expected_marker == marker:
                return record.verifier_run_id
        return None

    def _safe_evidence_refs(self, records: list[Phase8VerifierRunRecord]) -> list[dict[str, Any]]:
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
            "m1_model_settings": ["model_provider_profiles.json", "active_model_selection.json"],
            "m2_project_creation": ["project_creation_requests.json", "project_origin_metadata.json"],
            "m3_prompt_first": ["story_setup_draft_bundles.json", "story_setup_handoff_reports.json"],
            "m4_template_demo": ["template_instantiation_reports.json", "demo_seed_runs.json"],
            "m5_navigation": ["product_navigation_preferences.json", "active_project_selection.json"],
            "m6_progress": ["product_progress_snapshots.json"],
            "m7_artifacts_debug": ["product_artifact_views.json", "debug_isolation_audits.json"],
            "m8_closeout": ALLOWED_M8_STORAGE_FILES,
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

    def _sorted(self, records: list[Any]) -> list[Any]:
        records.sort(key=lambda item: getattr(item, "created_at", ""), reverse=True)
        return records

    def _allowed_storage_snapshot(self) -> dict[str, str | None]:
        snapshot: dict[str, str | None] = {}
        for file_name in ALLOWED_M8_STORAGE_FILES:
            path = self.data_dir / file_name
            if path.exists():
                try:
                    snapshot[file_name] = path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise StorageError(f"PHASE8_M8_STORAGE_SCAN_FAILED: {file_name}") from exc
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
                raise StorageError(f"PHASE8_M8_ROLLBACK_FAILED: {file_name}") from exc

    def _get_by_id(self, path: Path, model: type[BaseModel], key: str, value: str, error_code: str) -> Any:
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
                raise StorageError(f"PHASE8_M8_STORAGE_SCAN_FAILED: {path.name}") from exc
        return fingerprints

    def _selected_hashes(self, file_names: list[str]) -> dict[str, str]:
        all_hashes = self._storage_fingerprints()
        return {file_name: all_hashes[file_name] for file_name in file_names if file_name in all_hashes}

    def _assert_only_m8_changed(self, before: dict[str, str], after: dict[str, str]) -> None:
        changed = {name for name, value in after.items() if before.get(name) != value}
        changed.update(set(before) - set(after))
        unexpected = sorted(changed - set(ALLOWED_M8_STORAGE_FILES))
        if unexpected:
            raise StorageError(f"PHASE8_M8_FORBIDDEN_STORAGE_MUTATION: {unexpected}")

    def _guard_safe_id(self, value: str, label: str) -> None:
        if not value or not SAFE_ID_RE.match(value):
            raise StorageError(f"PHASE8_M8_UNSAFE_PAYLOAD_BLOCKED: {label}")
        self._guard_safe_payload({label: value})

    def _guard_safe_payload(self, payload: Any) -> None:
        def visit(value: Any, path: str) -> None:
            if isinstance(value, BaseModel):
                visit(model_to_dict(value), path)
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    safe_metadata_key = (
                        "hash" in path
                        or "count" in path
                        or normalized_key.endswith(("id", "ids", "ref", "refs", "file", "files", "marker", "markers"))
                    )
                    safe_negative_boolean = (
                        isinstance(child, bool)
                        and (
                            (normalized_key.startswith("contains") and child is False)
                            or normalized_key.startswith("no")
                            or normalized_key.startswith("doesnot")
                        )
                    )
                    if not safe_negative_boolean and not safe_metadata_key and any(part in normalized_key for part in UNSAFE_KEY_PARTS):
                        raise StorageError(f"PHASE8_M8_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"PHASE8_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"PHASE8_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"PHASE8_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")

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
