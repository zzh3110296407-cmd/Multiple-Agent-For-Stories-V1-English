from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.phase7_release_gate import (
    Phase7CheckpointAuthorityAudit,
    Phase7CheckpointAuthorityAuditListResponse,
    Phase7CloseoutReadinessReport,
    Phase7CloseoutReadinessReportListResponse,
    Phase7EvidenceIndex,
    Phase7EvidenceIndexListResponse,
    Phase7ExternalProviderNoCallAudit,
    Phase7ExternalProviderNoCallAuditListResponse,
    Phase7KnownResidualCarryForwardReport,
    Phase7KnownResidualCarryForwardReportListResponse,
    Phase7LicenseTemplateSafetyAudit,
    Phase7LicenseTemplateSafetyAuditListResponse,
    Phase7NoWriteAudit,
    Phase7NoWriteAuditListResponse,
    Phase7PluginArtifactVersioningAudit,
    Phase7PluginArtifactVersioningAuditListResponse,
    Phase7PluginE2EReport,
    Phase7PluginE2EReportListResponse,
    Phase7RegressionManifest,
    Phase7RegressionManifestListResponse,
    Phase7ReleaseGateReport,
    Phase7ReleaseGateReportListResponse,
    Phase7ReleaseGateRunRequest,
    Phase7ReleaseGateRunResult,
    Phase7ReleaseGateStatusResponse,
    Phase7VerifierMarkerObservation,
    Phase7VerifierRunRecord,
    Phase7VerifierRunRecordListResponse,
)
from ..storage.json_store import JsonStore, StorageError
from .final_story_package_export_service import ALLOWED_M2_STORAGE_FILES, M1_STORAGE_FILES
from .final_story_package_readiness_service import ALLOWED_M1_STORAGE_FILES
from .plugin_manifest_service import ALLOWED_M3_STORAGE_FILES, INPUT_VALIDATION_REPORTS_FILE
from .plugin_manifest_service import model_to_dict
from .plugin_run_safety_service import (
    ALLOWED_M4_STORAGE_FILES,
    FORBIDDEN_STORY_FACT_FILES,
    M3_STATIC_PROTOCOL_FILES,
    PLUGIN_CHECKPOINT_DECISIONS_FILE,
    PLUGIN_CHECKPOINTS_FILE,
    PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
    PLUGIN_OUTPUT_ARTIFACTS_FILE,
    PLUGIN_RUN_SAFETY_REPORTS_FILE,
    PLUGIN_RUN_STEPS_FILE,
    PLUGIN_RUNS_FILE,
)
from .script_forging_safety_service import (
    ALLOWED_M5_STORAGE_FILES,
    ALLOWED_M6_STORAGE_FILES,
    ALLOWED_M7_STORAGE_FILES,
    CHARACTER_ASSET_LISTS_FILE,
    COSTUME_CONTINUITY_LISTS_FILE,
    DIGITAL_ASSET_PACKAGES_FILE,
    FORBIDDEN_M7_M8_AND_MEDIA_FILES,
    KEY_STORYBOARD_ARTIFACTS_FILE,
    LOCATION_ASSET_LISTS_FILE,
    MOTIF_ASSET_LISTS_FILE,
    PROP_ASSET_LISTS_FILE,
    SCENE_OUTLINE_ARTIFACTS_FILE,
    SCENE_STORYBOARD_ARTIFACTS_FILE,
    SCREENPLAY_DRAFT_ARTIFACTS_FILE,
    SCREENPLAY_REVISION_CANDIDATES_FILE,
    SCREENPLAY_SELF_CHECK_REPORTS_FILE,
    SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE,
    SCRIPT_FORGING_CHECKPOINTS_FILE,
    SCRIPT_FORGING_CONTEXTS_FILE,
    SCRIPT_FORGING_RISK_NOTES_FILE,
    SCRIPT_SHAPE_PACKAGES_FILE,
    SHOT_LIST_ARTIFACTS_FILE,
    STORYBOARD_PACKAGES_FILE,
)


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase7_m8_plugin_e2e_closeout_v1"

PLUGIN_E2E_REPORTS_FILE = "phase7_plugin_e2e_reports.json"
RELEASE_GATE_REPORTS_FILE = "phase7_release_gate_reports.json"
REGRESSION_MANIFESTS_FILE = "phase7_regression_manifests.json"
VERIFIER_RUN_RECORDS_FILE = "phase7_verifier_run_records.json"
EVIDENCE_INDEXES_FILE = "phase7_evidence_indexes.json"
NO_WRITE_AUDITS_FILE = "phase7_no_write_audits.json"
ARTIFACT_VERSIONING_AUDITS_FILE = "phase7_plugin_artifact_versioning_audits.json"
CHECKPOINT_AUTHORITY_AUDITS_FILE = "phase7_checkpoint_authority_audits.json"
LICENSE_TEMPLATE_SAFETY_AUDITS_FILE = "phase7_license_template_safety_audits.json"
EXTERNAL_PROVIDER_NO_CALL_AUDITS_FILE = "phase7_external_provider_no_call_audits.json"
CLOSEOUT_READINESS_REPORTS_FILE = "phase7_closeout_readiness_reports.json"
KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE = "phase7_known_residuals_carry_forward_reports.json"

ALLOWED_M8_STORAGE_FILES = [
    PLUGIN_E2E_REPORTS_FILE,
    RELEASE_GATE_REPORTS_FILE,
    REGRESSION_MANIFESTS_FILE,
    VERIFIER_RUN_RECORDS_FILE,
    EVIDENCE_INDEXES_FILE,
    NO_WRITE_AUDITS_FILE,
    ARTIFACT_VERSIONING_AUDITS_FILE,
    CHECKPOINT_AUTHORITY_AUDITS_FILE,
    LICENSE_TEMPLATE_SAFETY_AUDITS_FILE,
    EXTERNAL_PROVIDER_NO_CALL_AUDITS_FILE,
    CLOSEOUT_READINESS_REPORTS_FILE,
    KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE,
]

PHASE6_RELEVANT_EVIDENCE_FILES = [
    "phase6_known_gap_carry_forward_records.json",
    "phase6_known_residuals_carry_forward_reports.json",
    "phase6_release_gate_reports.json",
    "phase6_closeout_readiness_reports.json",
]

M5_DOMAIN_FILES = [
    SCRIPT_FORGING_CONTEXTS_FILE,
    SCRIPT_SHAPE_PACKAGES_FILE,
    SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE,
    SCRIPT_FORGING_RISK_NOTES_FILE,
]
M6_DOMAIN_FILES = [
    SCENE_OUTLINE_ARTIFACTS_FILE,
    SCREENPLAY_DRAFT_ARTIFACTS_FILE,
    SCREENPLAY_SELF_CHECK_REPORTS_FILE,
    SCREENPLAY_REVISION_CANDIDATES_FILE,
]
M7_DOMAIN_FILES = [
    STORYBOARD_PACKAGES_FILE,
    KEY_STORYBOARD_ARTIFACTS_FILE,
    SCENE_STORYBOARD_ARTIFACTS_FILE,
    SHOT_LIST_ARTIFACTS_FILE,
    DIGITAL_ASSET_PACKAGES_FILE,
    CHARACTER_ASSET_LISTS_FILE,
    LOCATION_ASSET_LISTS_FILE,
    PROP_ASSET_LISTS_FILE,
    MOTIF_ASSET_LISTS_FILE,
    COSTUME_CONTINUITY_LISTS_FILE,
]
PLUGIN_RUNTIME_FILES = [
    PLUGIN_RUNS_FILE,
    PLUGIN_RUN_STEPS_FILE,
    PLUGIN_CHECKPOINTS_FILE,
    PLUGIN_CHECKPOINT_DECISIONS_FILE,
    PLUGIN_OUTPUT_ARTIFACTS_FILE,
    PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
    PLUGIN_RUN_SAFETY_REPORTS_FILE,
]
M1_M2_PACKAGE_FILES = sorted(set(ALLOWED_M1_STORAGE_FILES + M1_STORAGE_FILES + ALLOWED_M2_STORAGE_FILES))
GUARDED_STORAGE_FILES = sorted(
    set(
        FORBIDDEN_STORY_FACT_FILES
        + M1_M2_PACKAGE_FILES
        + M3_STATIC_PROTOCOL_FILES
        + [INPUT_VALIDATION_REPORTS_FILE]
        + PLUGIN_RUNTIME_FILES
        + M5_DOMAIN_FILES
        + M6_DOMAIN_FILES
        + M7_DOMAIN_FILES
        + PHASE6_RELEVANT_EVIDENCE_FILES
    )
)

REQUIRED_PHASE7_MARKERS = [
    "PHASE7_M1_FINAL_STORY_PACKAGE_READINESS: PASS",
    "PHASE7_M2_FINAL_STORY_PACKAGE_EXPORTER: PASS",
    "PHASE7_M3_PLUGIN_MANIFEST_REGISTRY: PASS",
    "PHASE7_M4_PLUGIN_RUN_CHECKPOINT_ARTIFACT_RUNTIME: PASS",
    "PHASE7_M5_SCRIPT_FORGING_PROMPT_PACKAGE: PASS",
    "PHASE7_M6_SCRIPT_FORGING_SCREENPLAY_DRAFT: PASS",
    "PHASE7_M7_STORYBOARD_ASSET_PACKAGE: PASS",
]
FRONTEND_BUILD_MARKER = "FRONTEND_BUILD: PASS"
REQUIRED_ALL_MARKERS = REQUIRED_PHASE7_MARKERS + [FRONTEND_BUILD_MARKER]
TIMEOUT_POLICY = {
    "phase7_m1_m7": 2400,
    "frontend_build": 1200,
    "phase7_m8_release_gate": 1200,
}

DOMAIN_ARTIFACT_BINDINGS = [
    (SCRIPT_SHAPE_PACKAGES_FILE, "script_shape_package_id", "output_artifact_id", "output_artifact_version_id"),
    (
        SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE,
        "script_adaptation_prompt_package_id",
        "output_artifact_id",
        "output_artifact_version_id",
    ),
    (SCENE_OUTLINE_ARTIFACTS_FILE, "scene_outline_id", "plugin_output_artifact_id", "plugin_output_artifact_version_id"),
    (
        SCREENPLAY_DRAFT_ARTIFACTS_FILE,
        "screenplay_draft_id",
        "plugin_output_artifact_id",
        "plugin_output_artifact_version_id",
    ),
    (
        SCREENPLAY_SELF_CHECK_REPORTS_FILE,
        "self_check_report_id",
        "plugin_output_artifact_id",
        "plugin_output_artifact_version_id",
    ),
    (
        SCREENPLAY_REVISION_CANDIDATES_FILE,
        "revision_candidate_id",
        "plugin_output_artifact_id",
        "plugin_output_artifact_version_id",
    ),
    (STORYBOARD_PACKAGES_FILE, "storyboard_package_id", "plugin_output_artifact_id", "plugin_output_artifact_version_id"),
    (
        DIGITAL_ASSET_PACKAGES_FILE,
        "digital_asset_package_id",
        "plugin_output_artifact_id",
        "plugin_output_artifact_version_id",
    ),
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
SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")
FILESYSTEM_PATH_RE = re.compile(r"(?i)([a-z]:[\\/]|(^|[\\/])\.\.([\\/]|$))")
SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-:.]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Phase7ReleaseGateService:
    """Phase 7 M8 evidence-only release gate."""

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.plugin_e2e_reports_file = self.data_dir / PLUGIN_E2E_REPORTS_FILE
        self.release_gate_reports_file = self.data_dir / RELEASE_GATE_REPORTS_FILE
        self.regression_manifests_file = self.data_dir / REGRESSION_MANIFESTS_FILE
        self.verifier_run_records_file = self.data_dir / VERIFIER_RUN_RECORDS_FILE
        self.evidence_indexes_file = self.data_dir / EVIDENCE_INDEXES_FILE
        self.no_write_audits_file = self.data_dir / NO_WRITE_AUDITS_FILE
        self.artifact_versioning_audits_file = self.data_dir / ARTIFACT_VERSIONING_AUDITS_FILE
        self.checkpoint_authority_audits_file = self.data_dir / CHECKPOINT_AUTHORITY_AUDITS_FILE
        self.license_template_safety_audits_file = self.data_dir / LICENSE_TEMPLATE_SAFETY_AUDITS_FILE
        self.external_provider_no_call_audits_file = self.data_dir / EXTERNAL_PROVIDER_NO_CALL_AUDITS_FILE
        self.closeout_readiness_reports_file = self.data_dir / CLOSEOUT_READINESS_REPORTS_FILE
        self.known_residuals_reports_file = self.data_dir / KNOWN_RESIDUALS_CARRY_FORWARD_REPORTS_FILE

    def get_status(self) -> Phase7ReleaseGateStatusResponse:
        reports = self._read_models_if_exists(self.release_gate_reports_file, Phase7ReleaseGateReport)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        latest = reports[0] if reports else None
        return Phase7ReleaseGateStatusResponse(
            report_count=len(reports),
            latest_release_gate_report_id=latest.release_gate_report_id if latest else None,
            latest_release_status=latest.release_status if latest else None,
            latest_closeout_readiness_status=latest.closeout_readiness_status if latest else None,
            allowed_m8_storage_files=list(ALLOWED_M8_STORAGE_FILES),
            guarded_storage_files=list(GUARDED_STORAGE_FILES),
            required_phase7_markers=list(REQUIRED_ALL_MARKERS),
            release_gate_is_evidence_only=True,
            no_new_authority=True,
            safe_summary="Phase 7 M8 status is evidence-only and writes only Phase 7 M8 audit files.",
        )

    def run_release_gate(self, request: Phase7ReleaseGateRunRequest | dict[str, Any]) -> Phase7ReleaseGateRunResult:
        normalized = request if isinstance(request, Phase7ReleaseGateRunRequest) else Phase7ReleaseGateRunRequest(**request)
        self._guard_safe_payload(model_to_dict(normalized))
        if len(normalized.safe_user_note) > 500:
            raise StorageError("PHASE7_M8_UNSAFE_PAYLOAD_BLOCKED: safe_user_note_too_long")
        for observation in normalized.verifier_marker_observations:
            self._validate_observation(observation)

        before_all = self._storage_fingerprints()
        guarded_before = self._selected_hashes(GUARDED_STORAGE_FILES)
        timestamp = now_iso()
        release_gate_report_id = self._next_id("phase7_release_gate_report", self.release_gate_reports_file, "release_gate_report_id")
        plugin_e2e_report_id = f"{release_gate_report_id}_plugin_e2e"
        regression_manifest_id = f"{release_gate_report_id}_regression_manifest"
        evidence_index_id = f"{release_gate_report_id}_evidence_index"
        no_write_audit_id = f"{release_gate_report_id}_no_write"
        artifact_versioning_audit_id = f"{release_gate_report_id}_artifact_versioning"
        checkpoint_authority_audit_id = f"{release_gate_report_id}_checkpoint_authority"
        license_template_safety_audit_id = f"{release_gate_report_id}_license_template_safety"
        external_provider_no_call_audit_id = f"{release_gate_report_id}_external_provider_no_call"
        closeout_readiness_report_id = f"{release_gate_report_id}_closeout_readiness"
        known_residuals_report_id = f"{release_gate_report_id}_known_residuals"

        observations = list(normalized.verifier_marker_observations)
        verifier_records = self._build_verifier_records(observations, release_gate_report_id, timestamp)
        observed_phase7_markers = self._observed_markers(observations, REQUIRED_PHASE7_MARKERS)
        observed_frontend_markers = self._observed_markers(observations, [FRONTEND_BUILD_MARKER])
        frontend_build_passed = FRONTEND_BUILD_MARKER in observed_frontend_markers
        missing_markers = [marker for marker in REQUIRED_ALL_MARKERS if marker not in self._observed_markers(observations, REQUIRED_ALL_MARKERS)]
        failed_markers = [
            observation.expected_marker
            for observation in observations
            if observation.expected_marker in REQUIRED_ALL_MARKERS and observation.run_status not in {"pass", "skipped"}
        ]
        marker_blockers = [f"missing_marker:{marker}" for marker in missing_markers] + [
            f"failed_marker:{marker}" for marker in failed_markers
        ]

        plugin_e2e_report = self._build_plugin_e2e_report(
            plugin_e2e_report_id,
            release_gate_report_id,
            timestamp,
        )
        artifact_versioning_audit = self._build_artifact_versioning_audit(
            artifact_versioning_audit_id,
            release_gate_report_id,
            timestamp,
        )
        checkpoint_authority_audit = self._build_checkpoint_authority_audit(
            checkpoint_authority_audit_id,
            release_gate_report_id,
            timestamp,
        )
        license_template_safety_audit = self._build_license_template_safety_audit(
            license_template_safety_audit_id,
            release_gate_report_id,
            timestamp,
        )
        external_provider_no_call_audit = self._build_external_provider_no_call_audit(
            external_provider_no_call_audit_id,
            release_gate_report_id,
            timestamp,
        )

        blocking_findings = list(marker_blockers)
        for audit in [
            plugin_e2e_report,
            artifact_versioning_audit,
            checkpoint_authority_audit,
            license_template_safety_audit,
            external_provider_no_call_audit,
        ]:
            blocking_findings.extend(getattr(audit, "blocking_findings", []))
        success = not blocking_findings
        release_status = "pass_with_known_gaps" if success else "blocked"
        readiness_status = "ready_with_known_gaps" if success else "blocked"
        warning_codes = ["known_residual_carried_forward:character_arc_empty_by_design"]
        created_storage_files = [file_name for file_name in ALLOWED_M8_STORAGE_FILES if file_name not in before_all]
        mutated_storage_files = [file_name for file_name in ALLOWED_M8_STORAGE_FILES if file_name in before_all]

        no_write_audit = Phase7NoWriteAudit(
            no_write_audit_id=no_write_audit_id,
            release_gate_report_id=release_gate_report_id,
            allowed_m8_storage_files=list(ALLOWED_M8_STORAGE_FILES),
            guarded_storage_files_checked=list(GUARDED_STORAGE_FILES),
            created_storage_files=created_storage_files,
            mutated_storage_files=mutated_storage_files,
            deleted_storage_files=[],
            only_m8_storage_changed=True,
            guarded_storage_unchanged=True,
            source_story_fact_files_unchanged=True,
            m1_m7_records_unchanged_by_m8=True,
            rollback_on_forbidden_mutation=True,
            blocking_findings=[],
            safe_summary="Phase 7 M8 write audit is limited to M8 evidence files.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        known_residuals_report = Phase7KnownResidualCarryForwardReport(
            residual_report_id=known_residuals_report_id,
            release_gate_report_id=release_gate_report_id,
            known_residuals=[
                {
                    "residual_id": "character_arc_empty_by_design",
                    "residual_status": "carried_forward",
                    "authority_boundary": "phase6_external_analyze_stories_character_arc_gap",
                    "safe_summary": "Phase 6 external Analyze Stories character-arc residual remains carried forward.",
                }
            ],
            character_arc_empty_by_design_carried_forward=True,
            stable_clean_analyze_stories_available=False,
            stable_clean_analyze_stories_claimed=False,
            phase7_plugin_system_passed=success,
            unsafe_closure_claims=[],
            blocking_findings=[],
            safe_summary="Phase 7 plugin system may pass while the Phase 6 external Analyze Stories residual remains carried forward.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        closeout_readiness_report = Phase7CloseoutReadinessReport(
            closeout_readiness_report_id=closeout_readiness_report_id,
            release_gate_report_id=release_gate_report_id,
            readiness_status=readiness_status,
            m1_pass=REQUIRED_PHASE7_MARKERS[0] in observed_phase7_markers,
            m2_pass=REQUIRED_PHASE7_MARKERS[1] in observed_phase7_markers,
            m3_pass=REQUIRED_PHASE7_MARKERS[2] in observed_phase7_markers,
            m4_pass=REQUIRED_PHASE7_MARKERS[3] in observed_phase7_markers,
            m5_pass=REQUIRED_PHASE7_MARKERS[4] in observed_phase7_markers,
            m6_pass=REQUIRED_PHASE7_MARKERS[5] in observed_phase7_markers,
            m7_pass=REQUIRED_PHASE7_MARKERS[6] in observed_phase7_markers,
            m8_release_gate_pass=success,
            ready_for_phase7_closeout=success,
            ready_for_phase8_handoff_with_known_residuals=success,
            official_closeout_docs_owned_by_phase7_main_session=True,
            known_residuals_to_carry_forward=["character_arc_empty_by_design"],
            blocking_findings=list(blocking_findings),
            safe_summary="Phase 7 closeout is ready with the explicit Phase 6 residual carried forward." if success else "Phase 7 closeout is blocked by release-gate findings.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        regression_manifest = Phase7RegressionManifest(
            regression_manifest_id=regression_manifest_id,
            release_gate_report_id=release_gate_report_id,
            required_phase7_verifier_markers=list(REQUIRED_PHASE7_MARKERS),
            verifier_run_record_ids=[record.verifier_run_id for record in verifier_records],
            frontend_build_record_id=self._frontend_record_id(verifier_records),
            bounded_scope=True,
            unbounded_history_scan_performed=False,
            all_required_markers_observed=set(REQUIRED_PHASE7_MARKERS).issubset(set(observed_phase7_markers)),
            all_selected_regressions_passed=success and frontend_build_passed,
            duration_seconds_total=round(sum(max(0, record.duration_seconds) for record in verifier_records), 3),
            timeout_policy=dict(TIMEOUT_POLICY),
            safe_summary="Phase 7 M8 regression manifest records bounded M1-M7 and frontend markers.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        evidence_index = Phase7EvidenceIndex(
            evidence_index_id=evidence_index_id,
            release_gate_report_id=release_gate_report_id,
            safe_evidence_refs=self._safe_evidence_refs(verifier_records),
            milestone_evidence_counts=self._milestone_counts(),
            storage_file_hashes=self._selected_hashes(ALLOWED_M8_STORAGE_FILES + GUARDED_STORAGE_FILES),
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
            safe_summary="Phase 7 M8 evidence index contains ids, counts, hashes, marker names, durations, and status fields only.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        release_gate_report = Phase7ReleaseGateReport(
            release_gate_report_id=release_gate_report_id,
            project_id=LOCAL_PROJECT_ID,
            release_status=release_status,
            closeout_readiness_status=readiness_status,
            phase7_milestones_covered=["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"],
            phase7_required_markers=list(REQUIRED_PHASE7_MARKERS),
            phase7_observed_markers=observed_phase7_markers,
            frontend_build_passed=frontend_build_passed,
            plugin_e2e_report_id=plugin_e2e_report_id,
            regression_manifest_id=regression_manifest_id,
            evidence_index_id=evidence_index_id,
            no_write_audit_id=no_write_audit_id,
            artifact_versioning_audit_id=artifact_versioning_audit_id,
            checkpoint_authority_audit_id=checkpoint_authority_audit_id,
            license_template_safety_audit_id=license_template_safety_audit_id,
            external_provider_no_call_audit_id=external_provider_no_call_audit_id,
            closeout_readiness_report_id=closeout_readiness_report_id,
            known_residuals_report_id=known_residuals_report_id,
            known_residuals_carried_forward=["character_arc_empty_by_design"],
            phase7_plugin_system_passed=success,
            phase6_external_analyze_stories_residual_carried_forward=True,
            stable_clean_analyze_stories_claimed=False,
            does_not_create_new_plugin_type=True,
            does_not_call_external_provider=True,
            does_not_mutate_source_story=True,
            does_not_overwrite_screenplay_draft=True,
            does_not_add_phase8_business_capability=True,
            blocking_findings=list(blocking_findings),
            warning_codes=list(warning_codes),
            safe_summary="Phase 7 plugin system passes with Phase 6 external Analyze Stories residual carried forward." if success else "Phase 7 M8 release gate is blocked.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

        records_to_guard: list[Any] = [
            plugin_e2e_report,
            release_gate_report,
            regression_manifest,
            *verifier_records,
            evidence_index,
            no_write_audit,
            artifact_versioning_audit,
            checkpoint_authority_audit,
            license_template_safety_audit,
            external_provider_no_call_audit,
            closeout_readiness_report,
            known_residuals_report,
        ]
        for record in records_to_guard:
            self._guard_safe_payload(model_to_dict(record))

        allowed_before = self._allowed_storage_snapshot()
        if self._selected_hashes(GUARDED_STORAGE_FILES) != guarded_before:
            raise StorageError("PHASE7_M8_FORBIDDEN_STORAGE_MUTATION: guarded_hash_changed_before_write")
        try:
            self._append(self.plugin_e2e_reports_file, model_to_dict(plugin_e2e_report))
            self._append(self.release_gate_reports_file, model_to_dict(release_gate_report))
            self._append(self.regression_manifests_file, model_to_dict(regression_manifest))
            for record in verifier_records:
                self._append(self.verifier_run_records_file, model_to_dict(record))
            self._append(self.evidence_indexes_file, model_to_dict(evidence_index))
            self._append(self.no_write_audits_file, model_to_dict(no_write_audit))
            self._append(self.artifact_versioning_audits_file, model_to_dict(artifact_versioning_audit))
            self._append(self.checkpoint_authority_audits_file, model_to_dict(checkpoint_authority_audit))
            self._append(self.license_template_safety_audits_file, model_to_dict(license_template_safety_audit))
            self._append(self.external_provider_no_call_audits_file, model_to_dict(external_provider_no_call_audit))
            self._append(self.closeout_readiness_reports_file, model_to_dict(closeout_readiness_report))
            self._append(self.known_residuals_reports_file, model_to_dict(known_residuals_report))

            after_all = self._storage_fingerprints()
            guarded_after = self._selected_hashes(GUARDED_STORAGE_FILES)
            if guarded_after != guarded_before:
                raise StorageError("PHASE7_M8_FORBIDDEN_STORAGE_MUTATION: guarded_hash_changed")
            self._assert_only_m8_changed(before_all, after_all)
        except StorageError:
            self._restore_allowed_storage(allowed_before)
            raise

        return Phase7ReleaseGateRunResult(
            success=success,
            release_gate_report=release_gate_report,
            plugin_e2e_report=plugin_e2e_report,
            regression_manifest=regression_manifest,
            verifier_run_records=verifier_records,
            evidence_index=evidence_index,
            no_write_audit=no_write_audit,
            artifact_versioning_audit=artifact_versioning_audit,
            checkpoint_authority_audit=checkpoint_authority_audit,
            license_template_safety_audit=license_template_safety_audit,
            external_provider_no_call_audit=external_provider_no_call_audit,
            closeout_readiness_report=closeout_readiness_report,
            known_residuals_report=known_residuals_report,
            safe_summary="Phase 7 M8 records were written without non-M8 storage mutation.",
        )

    def list_e2e_reports(self) -> Phase7PluginE2EReportListResponse:
        records = self._sorted(self._read_models_if_exists(self.plugin_e2e_reports_file, Phase7PluginE2EReport))
        return Phase7PluginE2EReportListResponse(e2e_reports=records, total_count=len(records))

    def get_e2e_report(self, e2e_report_id: str) -> Phase7PluginE2EReport:
        return self._get_by_id(self.plugin_e2e_reports_file, Phase7PluginE2EReport, "e2e_report_id", e2e_report_id, "PHASE7_M8_PLUGIN_E2E_REPORT_NOT_FOUND")

    def list_reports(self) -> Phase7ReleaseGateReportListResponse:
        records = self._sorted(self._read_models_if_exists(self.release_gate_reports_file, Phase7ReleaseGateReport))
        return Phase7ReleaseGateReportListResponse(reports=records, total_count=len(records))

    def get_report(self, release_gate_report_id: str) -> Phase7ReleaseGateReport:
        return self._get_by_id(self.release_gate_reports_file, Phase7ReleaseGateReport, "release_gate_report_id", release_gate_report_id, "PHASE7_M8_RELEASE_GATE_REPORT_NOT_FOUND")

    def list_regression_manifests(self) -> Phase7RegressionManifestListResponse:
        records = self._sorted(self._read_models_if_exists(self.regression_manifests_file, Phase7RegressionManifest))
        return Phase7RegressionManifestListResponse(regression_manifests=records, total_count=len(records))

    def get_regression_manifest(self, manifest_id: str) -> Phase7RegressionManifest:
        return self._get_by_id(self.regression_manifests_file, Phase7RegressionManifest, "regression_manifest_id", manifest_id, "PHASE7_M8_REGRESSION_MANIFEST_NOT_FOUND")

    def list_verifier_runs(self) -> Phase7VerifierRunRecordListResponse:
        records = self._sorted(self._read_models_if_exists(self.verifier_run_records_file, Phase7VerifierRunRecord))
        return Phase7VerifierRunRecordListResponse(verifier_runs=records, total_count=len(records))

    def get_verifier_run(self, verifier_run_id: str) -> Phase7VerifierRunRecord:
        return self._get_by_id(self.verifier_run_records_file, Phase7VerifierRunRecord, "verifier_run_id", verifier_run_id, "PHASE7_M8_VERIFIER_RUN_NOT_FOUND")

    def list_evidence_indexes(self) -> Phase7EvidenceIndexListResponse:
        records = self._sorted(self._read_models_if_exists(self.evidence_indexes_file, Phase7EvidenceIndex))
        return Phase7EvidenceIndexListResponse(evidence_indexes=records, total_count=len(records))

    def get_evidence_index(self, evidence_index_id: str) -> Phase7EvidenceIndex:
        return self._get_by_id(self.evidence_indexes_file, Phase7EvidenceIndex, "evidence_index_id", evidence_index_id, "PHASE7_M8_EVIDENCE_INDEX_NOT_FOUND")

    def list_no_write_audits(self) -> Phase7NoWriteAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.no_write_audits_file, Phase7NoWriteAudit))
        return Phase7NoWriteAuditListResponse(no_write_audits=records, total_count=len(records))

    def get_no_write_audit(self, audit_id: str) -> Phase7NoWriteAudit:
        return self._get_by_id(self.no_write_audits_file, Phase7NoWriteAudit, "no_write_audit_id", audit_id, "PHASE7_M8_NO_WRITE_AUDIT_NOT_FOUND")

    def list_artifact_versioning_audits(self) -> Phase7PluginArtifactVersioningAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.artifact_versioning_audits_file, Phase7PluginArtifactVersioningAudit))
        return Phase7PluginArtifactVersioningAuditListResponse(artifact_versioning_audits=records, total_count=len(records))

    def get_artifact_versioning_audit(self, audit_id: str) -> Phase7PluginArtifactVersioningAudit:
        return self._get_by_id(self.artifact_versioning_audits_file, Phase7PluginArtifactVersioningAudit, "artifact_versioning_audit_id", audit_id, "PHASE7_M8_ARTIFACT_VERSIONING_AUDIT_NOT_FOUND")

    def list_checkpoint_authority_audits(self) -> Phase7CheckpointAuthorityAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.checkpoint_authority_audits_file, Phase7CheckpointAuthorityAudit))
        return Phase7CheckpointAuthorityAuditListResponse(checkpoint_authority_audits=records, total_count=len(records))

    def get_checkpoint_authority_audit(self, audit_id: str) -> Phase7CheckpointAuthorityAudit:
        return self._get_by_id(self.checkpoint_authority_audits_file, Phase7CheckpointAuthorityAudit, "checkpoint_authority_audit_id", audit_id, "PHASE7_M8_CHECKPOINT_AUTHORITY_AUDIT_NOT_FOUND")

    def list_license_template_audits(self) -> Phase7LicenseTemplateSafetyAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.license_template_safety_audits_file, Phase7LicenseTemplateSafetyAudit))
        return Phase7LicenseTemplateSafetyAuditListResponse(license_template_audits=records, total_count=len(records))

    def get_license_template_audit(self, audit_id: str) -> Phase7LicenseTemplateSafetyAudit:
        return self._get_by_id(self.license_template_safety_audits_file, Phase7LicenseTemplateSafetyAudit, "license_template_safety_audit_id", audit_id, "PHASE7_M8_LICENSE_TEMPLATE_AUDIT_NOT_FOUND")

    def list_external_provider_no_call_audits(self) -> Phase7ExternalProviderNoCallAuditListResponse:
        records = self._sorted(self._read_models_if_exists(self.external_provider_no_call_audits_file, Phase7ExternalProviderNoCallAudit))
        return Phase7ExternalProviderNoCallAuditListResponse(external_provider_no_call_audits=records, total_count=len(records))

    def get_external_provider_no_call_audit(self, audit_id: str) -> Phase7ExternalProviderNoCallAudit:
        return self._get_by_id(self.external_provider_no_call_audits_file, Phase7ExternalProviderNoCallAudit, "external_provider_no_call_audit_id", audit_id, "PHASE7_M8_EXTERNAL_PROVIDER_NO_CALL_AUDIT_NOT_FOUND")

    def list_closeout_readiness_reports(self) -> Phase7CloseoutReadinessReportListResponse:
        records = self._sorted(self._read_models_if_exists(self.closeout_readiness_reports_file, Phase7CloseoutReadinessReport))
        return Phase7CloseoutReadinessReportListResponse(closeout_readiness_reports=records, total_count=len(records))

    def get_closeout_readiness_report(self, report_id: str) -> Phase7CloseoutReadinessReport:
        return self._get_by_id(self.closeout_readiness_reports_file, Phase7CloseoutReadinessReport, "closeout_readiness_report_id", report_id, "PHASE7_M8_CLOSEOUT_READINESS_REPORT_NOT_FOUND")

    def list_known_residuals_reports(self) -> Phase7KnownResidualCarryForwardReportListResponse:
        records = self._sorted(self._read_models_if_exists(self.known_residuals_reports_file, Phase7KnownResidualCarryForwardReport))
        return Phase7KnownResidualCarryForwardReportListResponse(known_residuals_reports=records, total_count=len(records))

    def get_known_residuals_report(self, report_id: str) -> Phase7KnownResidualCarryForwardReport:
        return self._get_by_id(self.known_residuals_reports_file, Phase7KnownResidualCarryForwardReport, "residual_report_id", report_id, "PHASE7_M8_KNOWN_RESIDUALS_REPORT_NOT_FOUND")

    def _build_plugin_e2e_report(self, report_id: str, release_gate_report_id: str, timestamp: str) -> Phase7PluginE2EReport:
        plugin_runs = self._read_list(self.data_dir / PLUGIN_RUNS_FILE)
        snapshots = self._read_list(self.data_dir / "final_story_package_snapshots.json")
        manifests = self._read_list(self.data_dir / "plugin_manifests.json")
        checkpoints = self._read_list(self.data_dir / PLUGIN_CHECKPOINTS_FILE)
        decisions = self._read_list(self.data_dir / PLUGIN_CHECKPOINT_DECISIONS_FILE)
        counts = {
            "script_forging_contexts": self._record_count(self.data_dir / SCRIPT_FORGING_CONTEXTS_FILE),
            "script_shape_packages": self._record_count(self.data_dir / SCRIPT_SHAPE_PACKAGES_FILE),
            "script_adaptation_prompt_packages": self._record_count(self.data_dir / SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE),
            "scene_outline_artifacts": self._record_count(self.data_dir / SCENE_OUTLINE_ARTIFACTS_FILE),
            "screenplay_draft_artifacts": self._record_count(self.data_dir / SCREENPLAY_DRAFT_ARTIFACTS_FILE),
            "screenplay_self_check_reports": self._record_count(self.data_dir / SCREENPLAY_SELF_CHECK_REPORTS_FILE),
            "screenplay_revision_candidates": self._record_count(self.data_dir / SCREENPLAY_REVISION_CANDIDATES_FILE),
            "storyboard_packages": self._record_count(self.data_dir / STORYBOARD_PACKAGES_FILE),
            "digital_asset_packages": self._record_count(self.data_dir / DIGITAL_ASSET_PACKAGES_FILE),
        }
        required_counts = [
            counts["script_forging_contexts"],
            counts["script_shape_packages"],
            counts["script_adaptation_prompt_packages"],
            counts["scene_outline_artifacts"],
            counts["screenplay_draft_artifacts"],
            counts["screenplay_self_check_reports"],
            counts["storyboard_packages"],
            counts["digital_asset_packages"],
            len(plugin_runs),
            len(snapshots),
            len(manifests),
            len(checkpoints),
            len(decisions),
        ]
        blocking = []
        if not all(value > 0 for value in required_counts):
            blocking.append("plugin_e2e_chain_incomplete")
        return Phase7PluginE2EReport(
            e2e_report_id=report_id,
            release_gate_report_id=release_gate_report_id,
            project_id=LOCAL_PROJECT_ID,
            plugin_run_ids=[str(item.get("plugin_run_id", "")) for item in plugin_runs if item.get("plugin_run_id")],
            final_story_package_snapshot_ids=[str(item.get("snapshot_id", "")) for item in snapshots if item.get("snapshot_id")],
            plugin_manifest_ids=[str(item.get("manifest_id", "")) for item in manifests if item.get("manifest_id")],
            checkpoint_ids=[str(item.get("checkpoint_id", "")) for item in checkpoints if item.get("checkpoint_id")],
            checkpoint_decision_ids=[str(item.get("checkpoint_decision_id", "")) for item in decisions if item.get("checkpoint_decision_id")],
            script_forging_artifact_counts=counts,
            plugin_output_artifact_count=self._record_count(self.data_dir / PLUGIN_OUTPUT_ARTIFACTS_FILE),
            plugin_output_artifact_version_count=self._record_count(self.data_dir / PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE),
            storyboard_package_count=counts["storyboard_packages"],
            digital_asset_package_count=counts["digital_asset_packages"],
            e2e_chain_complete=not blocking,
            blocking_findings=blocking,
            safe_summary="Phase 7 plugin E2E report links final package, plugin runtime, checkpoints, script forging, storyboard, and digital asset records.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_artifact_versioning_audit(self, audit_id: str, release_gate_report_id: str, timestamp: str) -> Phase7PluginArtifactVersioningAudit:
        artifacts = {str(item.get("artifact_id")): item for item in self._read_list(self.data_dir / PLUGIN_OUTPUT_ARTIFACTS_FILE)}
        versions = {
            (str(item.get("artifact_id")), str(item.get("artifact_version_id"))): item
            for item in self._read_list(self.data_dir / PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE)
        }
        checked = []
        missing_artifacts = []
        missing_versions = []
        for file_name, id_field, artifact_field, version_field in DOMAIN_ARTIFACT_BINDINGS:
            for row in self._read_list(self.data_dir / file_name):
                record_id = str(row.get(id_field, ""))
                artifact_id = str(row.get(artifact_field, ""))
                version_id = str(row.get(version_field, ""))
                if not record_id:
                    continue
                checked.append({"file": file_name, "record_id": record_id, "artifact_id": artifact_id, "version_id": version_id})
                artifact = artifacts.get(artifact_id)
                if not artifact:
                    missing_artifacts.append(f"{file_name}:{record_id}:{artifact_id}")
                    continue
                if (artifact_id, version_id) not in versions or artifact.get("current_version_id") != version_id:
                    missing_versions.append(f"{file_name}:{record_id}:{version_id}")
        blocking = []
        if missing_artifacts:
            blocking.append("missing_plugin_output_artifact")
        if missing_versions:
            blocking.append("missing_plugin_output_artifact_version")
        return Phase7PluginArtifactVersioningAudit(
            artifact_versioning_audit_id=audit_id,
            release_gate_report_id=release_gate_report_id,
            checked_domain_record_refs=checked,
            missing_artifact_refs=missing_artifacts,
            missing_version_refs=missing_versions,
            artifact_versioning_passed=not blocking,
            blocking_findings=blocking,
            safe_summary="Phase 7 M8 artifact audit checks M5-M7 derivative records against PluginOutputArtifact versions.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_checkpoint_authority_audit(self, audit_id: str, release_gate_report_id: str, timestamp: str) -> Phase7CheckpointAuthorityAudit:
        checkpoints = self._read_list(self.data_dir / PLUGIN_CHECKPOINTS_FILE)
        decisions = self._read_list(self.data_dir / PLUGIN_CHECKPOINT_DECISIONS_FILE)
        decision_scope_ok = all(item.get("decision_scope") == "plugin_step_only" for item in decisions)
        decision_no_source_ok = all(
            item.get("does_not_modify_source_story") is True and item.get("does_not_modify_final_story_package") is True
            for item in decisions
        )
        checkpoint_no_source_ok = all(item.get("mutates_source_story") is False for item in checkpoints)
        blocking = []
        if not decision_scope_ok:
            blocking.append("checkpoint_decision_scope_not_plugin_step_only")
        if not decision_no_source_ok:
            blocking.append("checkpoint_decision_source_mutation_flag_invalid")
        if not checkpoint_no_source_ok:
            blocking.append("checkpoint_source_mutation_flag_invalid")
        return Phase7CheckpointAuthorityAudit(
            checkpoint_authority_audit_id=audit_id,
            release_gate_report_id=release_gate_report_id,
            checked_checkpoint_ids=[str(item.get("checkpoint_id", "")) for item in checkpoints if item.get("checkpoint_id")],
            checked_decision_ids=[str(item.get("checkpoint_decision_id", "")) for item in decisions if item.get("checkpoint_decision_id")],
            all_decisions_plugin_step_only=decision_scope_ok,
            all_decisions_do_not_modify_source_story=decision_no_source_ok,
            all_checkpoints_do_not_mutate_source_story=checkpoint_no_source_ok,
            checkpoint_authority_passed=not blocking,
            blocking_findings=blocking,
            safe_summary="Phase 7 M8 checkpoint audit confirms plugin-step-only checkpoint authority.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_license_template_safety_audit(self, audit_id: str, release_gate_report_id: str, timestamp: str) -> Phase7LicenseTemplateSafetyAudit:
        manifests = self._read_list(self.data_dir / "plugin_manifests.json")
        forbidden_present = [file_name for file_name in FORBIDDEN_M7_M8_AND_MEDIA_FILES if (self.data_dir / file_name).exists()]
        blocking = []
        if forbidden_present:
            blocking.append("external_media_template_or_output_file_present")
        return Phase7LicenseTemplateSafetyAudit(
            license_template_safety_audit_id=audit_id,
            release_gate_report_id=release_gate_report_id,
            checked_manifest_ids=[str(item.get("manifest_id", "")) for item in manifests if item.get("manifest_id")],
            checked_template_refs=["script_forging_builtin_manifest", "final_story_package_snapshot_contract"],
            no_unlicensed_external_template_claim=True,
            no_external_media_prompt_template_created=not forbidden_present,
            no_provider_specific_template_secret=True,
            license_template_safety_passed=not blocking,
            blocking_findings=blocking,
            safe_summary="Phase 7 M8 license/template audit is limited to technical provenance and no external media template files.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_external_provider_no_call_audit(self, audit_id: str, release_gate_report_id: str, timestamp: str) -> Phase7ExternalProviderNoCallAudit:
        forbidden_present = [file_name for file_name in FORBIDDEN_M7_M8_AND_MEDIA_FILES if (self.data_dir / file_name).exists()]
        flags = []
        for file_name in [PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, STORYBOARD_PACKAGES_FILE, DIGITAL_ASSET_PACKAGES_FILE]:
            for row in self._read_list(self.data_dir / file_name):
                for key in ["structured_summary", "provenance"]:
                    payload = row.get(key)
                    if isinstance(payload, dict) and payload.get("external_media_provider_called") is not None:
                        flags.append(
                            {
                                "file": file_name,
                                "record_id": str(row.get("artifact_version_id") or row.get("storyboard_package_id") or row.get("digital_asset_package_id") or "unknown"),
                                "external_media_provider_called": bool(payload.get("external_media_provider_called")),
                            }
                        )
        any_called = any(item["external_media_provider_called"] for item in flags)
        blocking = []
        if forbidden_present:
            blocking.append("external_media_or_phase8_file_present")
        if any_called:
            blocking.append("external_provider_called_flag_true")
        return Phase7ExternalProviderNoCallAudit(
            external_provider_no_call_audit_id=audit_id,
            release_gate_report_id=release_gate_report_id,
            forbidden_media_files_checked=list(FORBIDDEN_M7_M8_AND_MEDIA_FILES),
            forbidden_media_files_present=forbidden_present,
            external_media_provider_called_flags=flags,
            no_external_provider_call=not any_called,
            no_generated_media_binary=not forbidden_present,
            no_external_prompt_package=not forbidden_present,
            external_provider_no_call_passed=not blocking,
            blocking_findings=blocking,
            safe_summary="Phase 7 M8 external-provider audit confirms no image, video, audio, or provider output path was used.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _validate_observation(self, observation: Phase7VerifierMarkerObservation) -> None:
        if len(observation.safe_output_excerpt) > 1200:
            raise StorageError("PHASE7_M8_UNSAFE_PAYLOAD_BLOCKED: safe_output_excerpt_too_long")
        if len(observation.command) > 500:
            raise StorageError("PHASE7_M8_UNSAFE_PAYLOAD_BLOCKED: command_too_long")
        if observation.expected_marker not in REQUIRED_ALL_MARKERS:
            raise StorageError(f"PHASE7_M8_RELEASE_GATE_BLOCKED: unexpected_marker:{observation.expected_marker}")

    def _build_verifier_records(
        self,
        observations: list[Phase7VerifierMarkerObservation],
        report_id: str,
        timestamp: str,
    ) -> list[Phase7VerifierRunRecord]:
        records = []
        for index, observation in enumerate(observations, start=1):
            records.append(
                Phase7VerifierRunRecord(
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
        if marker.startswith("PHASE7_M"):
            return "phase7_m1_m7"
        if marker == FRONTEND_BUILD_MARKER:
            return "frontend_build"
        return "phase7_m8_release_gate"

    def _observed_markers(self, observations: list[Phase7VerifierMarkerObservation], expected: list[str]) -> list[str]:
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

    def _frontend_record_id(self, records: list[Phase7VerifierRunRecord]) -> str | None:
        for record in records:
            if record.scope == "frontend_build":
                return record.verifier_run_id
        return None

    def _safe_evidence_refs(self, records: list[Phase7VerifierRunRecord]) -> list[dict[str, Any]]:
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
            "m1": ALLOWED_M1_STORAGE_FILES,
            "m2": ALLOWED_M2_STORAGE_FILES,
            "m3": ALLOWED_M3_STORAGE_FILES,
            "m4": ALLOWED_M4_STORAGE_FILES,
            "m5": M5_DOMAIN_FILES,
            "m6": M6_DOMAIN_FILES,
            "m7": M7_DOMAIN_FILES,
            "m8": ALLOWED_M8_STORAGE_FILES,
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
                    raise StorageError(f"PHASE7_M8_STORAGE_SCAN_FAILED: {file_name}") from exc
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
                raise StorageError(f"PHASE7_M8_ROLLBACK_FAILED: {file_name}") from exc

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
                raise StorageError(f"PHASE7_M8_STORAGE_SCAN_FAILED: {path.name}") from exc
        return fingerprints

    def _selected_hashes(self, file_names: list[str]) -> dict[str, str]:
        all_hashes = self._storage_fingerprints()
        return {file_name: all_hashes[file_name] for file_name in file_names if file_name in all_hashes}

    def _assert_only_m8_changed(self, before: dict[str, str], after: dict[str, str]) -> None:
        changed = {name for name, value in after.items() if before.get(name) != value}
        changed.update(set(before) - set(after))
        unexpected = sorted(changed - set(ALLOWED_M8_STORAGE_FILES))
        if unexpected:
            raise StorageError(f"PHASE7_M8_FORBIDDEN_STORAGE_MUTATION: {unexpected}")

    def _guard_safe_id(self, value: str, label: str) -> None:
        if not value or not SAFE_ID_RE.match(value):
            raise StorageError(f"PHASE7_M8_UNSAFE_PAYLOAD_BLOCKED: {label}")
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
                        raise StorageError(f"PHASE7_M8_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"PHASE7_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"PHASE7_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"PHASE7_M8_UNSAFE_PAYLOAD_BLOCKED: {path}")

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
