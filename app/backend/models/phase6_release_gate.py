from typing import Literal

from pydantic import BaseModel, Field


ReleaseGateStatus = Literal["pass", "pass_with_known_gaps", "blocked", "failed"]
ReleaseGateReadinessStatus = Literal["ready_for_closeout", "ready_with_known_gaps", "blocked", "failed"]
VerifierRunStatus = Literal["pass", "failed", "blocked", "skipped", "timed_out"]
RegressionScope = Literal[
    "phase6_m1_m7",
    "phase5_m8_full_with_selected_phase4",
    "frontend_build",
    "m8_release_gate",
]
EvidenceSensitivity = Literal["safe", "safe_summary_only", "blocked"]


class VerifierMarkerObservation(BaseModel):
    marker_name: str
    command: str = ""
    expected_marker: str
    observed_marker: str = ""
    run_status: VerifierRunStatus
    duration_seconds: float = 0
    timeout_seconds: int = 0
    safe_output_excerpt: str = ""
    evidence_ref: str = ""


class ReleaseGateRunRequest(BaseModel):
    safe_user_note: str = ""
    verifier_marker_observations: list[VerifierMarkerObservation] = Field(default_factory=list)


class Phase6ReleaseGateReport(BaseModel):
    release_gate_report_id: str
    project_id: str = "local_project"
    release_status: ReleaseGateStatus
    closeout_readiness_status: ReleaseGateReadinessStatus
    phase6_milestones_covered: list[str] = Field(default_factory=list)
    phase6_required_markers: list[str] = Field(default_factory=list)
    phase6_observed_markers: list[str] = Field(default_factory=list)
    selected_inherited_markers: list[str] = Field(default_factory=list)
    frontend_build_passed: bool
    formal_file_pollution_audit_id: str
    safety_authority_audit_id: str
    evidence_index_id: str
    regression_manifest_id: str
    closeout_readiness_report_id: str
    known_residuals_report_id: str
    known_residuals_carried_forward: list[str] = Field(default_factory=list)
    stable_clean_replay_claimed: bool = False
    stable_with_known_gaps_preserved: bool = True
    does_not_create_formal_story_fact: bool = True
    does_not_execute_apply: bool = True
    does_not_perform_propagation_rewrite: bool = True
    does_not_create_active_recommendation: bool = True
    does_not_mutate_active_framework: bool = True
    blocking_findings: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase6RegressionManifest(BaseModel):
    regression_manifest_id: str
    release_gate_report_id: str
    required_phase6_verifier_markers: list[str] = Field(default_factory=list)
    selected_inherited_regression_markers: list[str] = Field(default_factory=list)
    verifier_run_record_ids: list[str] = Field(default_factory=list)
    frontend_build_record_id: str | None = None
    bounded_scope: bool = True
    unbounded_history_scan_performed: bool = False
    all_required_markers_observed: bool
    all_selected_regressions_passed: bool
    duration_seconds_total: float
    timeout_policy: dict[str, int] = Field(default_factory=dict)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase6VerifierRunRecord(BaseModel):
    verifier_run_id: str
    release_gate_report_id: str | None = None
    scope: RegressionScope
    command: str
    expected_marker: str
    observed_marker: str
    run_status: VerifierRunStatus
    duration_seconds: float
    timeout_seconds: int
    safe_output_excerpt: str
    evidence_ref: str
    created_at: str
    updated_at: str
    version_id: str


class Phase6EvidenceIndex(BaseModel):
    evidence_index_id: str
    release_gate_report_id: str
    safe_evidence_refs: list[dict] = Field(default_factory=list)
    milestone_evidence_counts: dict[str, int] = Field(default_factory=dict)
    storage_file_hashes: dict[str, str] = Field(default_factory=dict)
    forbidden_storage_hashes_before: dict[str, str] = Field(default_factory=dict)
    forbidden_storage_hashes_after: dict[str, str] = Field(default_factory=dict)
    evidence_sensitivity: EvidenceSensitivity = "safe"
    contains_raw_prompt: bool = False
    contains_raw_response: bool = False
    contains_hidden_reasoning: bool = False
    contains_full_prose: bool = False
    contains_secret_or_credential: bool = False
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase6CloseoutReadinessReport(BaseModel):
    closeout_readiness_report_id: str
    release_gate_report_id: str
    readiness_status: ReleaseGateReadinessStatus
    m1_pass: bool
    m2_pass: bool
    m3_pass: bool
    m4_pass: bool
    m5_pass: bool
    m6_pass: bool
    m7_pass: bool
    m8_release_gate_pass: bool
    ready_for_phase6_main_session_closeout: bool
    ready_for_phase7_handoff_with_known_gaps: bool
    human_closeout_docs_owned_by_phase6_main_session: bool = True
    blocking_findings: list[str] = Field(default_factory=list)
    known_gaps_to_carry_forward: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase6SafetyAuthorityAudit(BaseModel):
    safety_authority_audit_id: str
    release_gate_report_id: str
    no_raw_prompt_response_leak: bool
    no_hidden_reasoning_leak: bool
    no_full_prose_leak: bool
    no_secret_or_credential_leak: bool
    no_apply_execution: bool
    no_propagation_rewrite: bool
    no_active_recommendation_creation: bool
    no_active_framework_mutation: bool
    no_formal_story_fact_write: bool
    no_known_gap_clean_pass_claim: bool
    authority_boundary_passed: bool
    blocking_findings: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase6FormalFilePollutionAudit(BaseModel):
    formal_file_pollution_audit_id: str
    release_gate_report_id: str
    allowed_m8_storage_files: list[str] = Field(default_factory=list)
    mutated_storage_files: list[str] = Field(default_factory=list)
    created_storage_files: list[str] = Field(default_factory=list)
    forbidden_storage_files_checked: list[str] = Field(default_factory=list)
    forbidden_storage_unchanged: bool
    m1_m7_evidence_files_unchanged_by_m8: bool
    formal_story_files_unchanged: bool
    active_framework_files_unchanged: bool
    recommendation_activation_files_unchanged: bool
    only_m8_storage_changed: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase6KnownResidualsCarryForwardReport(BaseModel):
    known_residuals_report_id: str
    release_gate_report_id: str
    known_residuals: list[dict] = Field(default_factory=list)
    character_arc_empty_by_design_carried_forward: bool
    stable_clean_replay_available: bool = False
    stable_clean_replay_claimed: bool = False
    stable_with_known_gaps_preserved: bool = True
    unsafe_closure_claims: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class ReleaseGateStatusResponse(BaseModel):
    report_count: int = 0
    latest_release_gate_report_id: str | None = None
    latest_release_status: ReleaseGateStatus | None = None
    latest_closeout_readiness_status: ReleaseGateReadinessStatus | None = None
    allowed_m8_storage_files: list[str] = Field(default_factory=list)
    forbidden_storage_files: list[str] = Field(default_factory=list)
    phase6_evidence_files: list[str] = Field(default_factory=list)
    required_phase6_markers: list[str] = Field(default_factory=list)
    selected_inherited_markers: list[str] = Field(default_factory=list)
    release_gate_is_evidence_only: bool = True
    no_new_authority: bool = True
    safe_summary: str


class Phase6ReleaseGateRunResult(BaseModel):
    success: bool
    release_gate_report: Phase6ReleaseGateReport
    regression_manifest: Phase6RegressionManifest
    verifier_run_records: list[Phase6VerifierRunRecord] = Field(default_factory=list)
    evidence_index: Phase6EvidenceIndex
    closeout_readiness_report: Phase6CloseoutReadinessReport
    safety_authority_audit: Phase6SafetyAuthorityAudit
    formal_file_pollution_audit: Phase6FormalFilePollutionAudit
    known_residuals_report: Phase6KnownResidualsCarryForwardReport
    safe_summary: str


class Phase6ReleaseGateReportListResponse(BaseModel):
    reports: list[Phase6ReleaseGateReport] = Field(default_factory=list)
    total_count: int = 0


class Phase6RegressionManifestListResponse(BaseModel):
    regression_manifests: list[Phase6RegressionManifest] = Field(default_factory=list)
    total_count: int = 0


class Phase6VerifierRunRecordListResponse(BaseModel):
    verifier_runs: list[Phase6VerifierRunRecord] = Field(default_factory=list)
    total_count: int = 0


class Phase6EvidenceIndexListResponse(BaseModel):
    evidence_indexes: list[Phase6EvidenceIndex] = Field(default_factory=list)
    total_count: int = 0


class Phase6CloseoutReadinessReportListResponse(BaseModel):
    closeout_readiness_reports: list[Phase6CloseoutReadinessReport] = Field(default_factory=list)
    total_count: int = 0


class Phase6SafetyAuthorityAuditListResponse(BaseModel):
    safety_authority_audits: list[Phase6SafetyAuthorityAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase6FormalFilePollutionAuditListResponse(BaseModel):
    formal_file_pollution_audits: list[Phase6FormalFilePollutionAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase6KnownResidualsCarryForwardReportListResponse(BaseModel):
    known_residuals_reports: list[Phase6KnownResidualsCarryForwardReport] = Field(default_factory=list)
    total_count: int = 0
