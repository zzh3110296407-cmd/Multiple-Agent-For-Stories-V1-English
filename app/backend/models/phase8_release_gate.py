from typing import Literal

from pydantic import BaseModel, Field


Phase8ReleaseStatus = Literal["pass", "pass_with_known_residuals", "blocked", "failed"]
Phase8CloseoutReadinessStatus = Literal["ready_for_closeout", "ready_with_known_residuals", "blocked", "failed"]
Phase8VerifierRunStatus = Literal["pass", "failed", "blocked", "skipped", "timed_out"]
Phase8EvidenceSensitivity = Literal["safe", "safe_summary_only", "blocked"]
Phase8RegressionScope = Literal["phase8_m1_m7", "frontend_build", "phase8_m8_release_gate"]


class Phase8VerifierMarkerObservation(BaseModel):
    marker_name: str
    command: str = ""
    expected_marker: str
    observed_marker: str = ""
    run_status: Phase8VerifierRunStatus
    duration_seconds: float = 0
    timeout_seconds: int = 0
    safe_output_excerpt: str = ""
    evidence_ref: str = ""


class Phase8ReleaseGateRunRequest(BaseModel):
    safe_user_note: str = ""
    verifier_marker_observations: list[Phase8VerifierMarkerObservation] = Field(default_factory=list)


class Phase8ProductWorkbenchE2EReport(BaseModel):
    e2e_report_id: str
    release_gate_report_id: str
    project_id: str = "local_project"
    provider_mode_summary: str
    deterministic_or_mock_labeled_correctly: bool
    real_provider_claimed: bool = False
    real_provider_evidence_ref: str | None = None
    product_flow_steps_checked: list[str] = Field(default_factory=list)
    m1_m7_milestones_covered: list[str] = Field(default_factory=list)
    frontend_build_passed: bool
    e2e_chain_complete: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8ReleaseGateReport(BaseModel):
    release_gate_report_id: str
    project_id: str = "local_project"
    release_status: Phase8ReleaseStatus
    closeout_readiness_status: Phase8CloseoutReadinessStatus
    phase8_required_markers: list[str] = Field(default_factory=list)
    phase8_observed_markers: list[str] = Field(default_factory=list)
    frontend_build_passed: bool
    product_workbench_e2e_report_id: str
    regression_manifest_id: str
    evidence_index_id: str
    secret_safety_audit_id: str
    demo_seed_isolation_audit_id: str
    progress_view_model_audit_id: str
    debug_isolation_audit_id: str
    artifact_authority_audit_id: str
    scope_boundary_audit_id: str
    closeout_readiness_report_id: str
    known_residuals_report_id: str
    handoff_index_id: str
    known_residuals_carried_forward: list[str] = Field(default_factory=list)
    does_not_create_new_business_capability: bool = True
    does_not_mutate_source_story: bool = True
    does_not_mutate_phase7_artifacts: bool = True
    does_not_claim_stable_clean_analyze_stories: bool = True
    blocking_findings: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8RegressionManifest(BaseModel):
    regression_manifest_id: str
    release_gate_report_id: str
    required_phase8_verifier_markers: list[str] = Field(default_factory=list)
    verifier_run_record_ids: list[str] = Field(default_factory=list)
    frontend_build_record_id: str | None = None
    m8_release_gate_record_id: str | None = None
    bounded_scope: bool = True
    unbounded_history_scan_performed: bool = False
    all_required_markers_observed: bool
    all_selected_regressions_passed: bool
    duration_seconds_total: float
    timeout_policy: dict[str, int] = Field(default_factory=dict)
    skipped_regressions: list[dict] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8VerifierRunRecord(BaseModel):
    verifier_run_id: str
    release_gate_report_id: str | None = None
    scope: Phase8RegressionScope
    command: str
    expected_marker: str
    observed_marker: str
    run_status: Phase8VerifierRunStatus
    duration_seconds: float
    timeout_seconds: int
    safe_output_excerpt: str
    evidence_ref: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8EvidenceIndex(BaseModel):
    evidence_index_id: str
    release_gate_report_id: str
    safe_evidence_refs: list[dict] = Field(default_factory=list)
    milestone_evidence_counts: dict[str, int] = Field(default_factory=dict)
    storage_file_hashes: dict[str, str] = Field(default_factory=dict)
    guarded_storage_hashes_before: dict[str, str] = Field(default_factory=dict)
    guarded_storage_hashes_after: dict[str, str] = Field(default_factory=dict)
    evidence_sensitivity: Phase8EvidenceSensitivity = "safe"
    contains_raw_prompt: bool = False
    contains_raw_response: bool = False
    contains_hidden_reasoning: bool = False
    contains_chain_of_thought: bool = False
    contains_full_story_prose: bool = False
    contains_full_screenplay_text: bool = False
    contains_secret_or_credential: bool = False
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8SecretSafetyAudit(BaseModel):
    secret_safety_audit_id: str
    release_gate_report_id: str
    env_refs_safe_only: bool
    provider_profiles_hide_raw_keys: bool
    no_raw_secret_in_release_records: bool
    qwen_identity_preserved: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8DemoSeedIsolationE2EAudit(BaseModel):
    demo_seed_isolation_audit_id: str
    release_gate_report_id: str
    demo_seed_real_project_contamination_absent: bool
    demo_seed_records_are_project_scoped: bool
    no_demo_seed_write_during_m8: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8ProgressViewModelAudit(BaseModel):
    progress_view_model_audit_id: str
    release_gate_report_id: str
    product_progress_summary_view_model_only: bool
    next_recommended_action_view_model_only: bool
    user_decision_surface_view_model_only: bool
    blocking_issue_surface_view_model_only: bool
    project_scoped_progress_checked: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8DebugIsolationE2EAudit(BaseModel):
    debug_isolation_audit_id: str
    release_gate_report_id: str
    ordinary_mode_debug_hidden: bool
    expert_diagnostics_safe_only: bool
    raw_payload_hidden: bool
    debug_routes_get_only: bool
    no_debug_mutation_authority: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8ArtifactAuthorityAudit(BaseModel):
    artifact_authority_audit_id: str
    release_gate_report_id: str
    final_story_package_is_plugin_input_authority: bool
    final_story_package_not_source_story_fact: bool
    plugin_output_artifact_is_derivative_authority: bool
    plugin_output_artifact_no_writeback: bool
    product_artifact_endpoints_get_only: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8ScopeBoundaryAudit(BaseModel):
    scope_boundary_audit_id: str
    release_gate_report_id: str
    no_phase9_routes: bool
    no_phase9_classes: bool
    no_new_provider_routing: bool
    no_new_project_creation_mode: bool
    no_new_plugin_marketplace: bool
    no_cloud_sync_or_collaboration: bool
    checked_markers: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8KnownResidualCarryForwardReport(BaseModel):
    residual_report_id: str
    release_gate_report_id: str
    known_residuals: list[dict] = Field(default_factory=list)
    character_arc_empty_by_design_carried_forward: bool = True
    stable_clean_analyze_stories_available: bool = False
    stable_clean_analyze_stories_claimed: bool = False
    unsafe_closure_claims: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8CloseoutReadinessReport(BaseModel):
    closeout_readiness_report_id: str
    release_gate_report_id: str
    readiness_status: Phase8CloseoutReadinessStatus
    m1_pass: bool
    m2_pass: bool
    m3_pass: bool
    m4_pass: bool
    m5_pass: bool
    m6_pass: bool
    m7_pass: bool
    m8_release_gate_pass: bool
    ready_for_phase8_closeout: bool
    ready_for_phase9_handoff_with_known_residuals: bool
    official_closeout_docs_owned_by_phase8_main_session: bool = True
    known_residuals_to_carry_forward: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8HandoffIndex(BaseModel):
    handoff_index_id: str
    release_gate_report_id: str
    phase8_closeout_report_ref: str
    phase9_handoff_ready: bool
    safe_handoff_refs: list[dict] = Field(default_factory=list)
    known_residuals_to_carry_forward: list[str] = Field(default_factory=list)
    forbidden_claims_absent: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase8ReleaseGateStatusResponse(BaseModel):
    report_count: int = 0
    latest_release_gate_report_id: str | None = None
    latest_release_status: Phase8ReleaseStatus | None = None
    latest_closeout_readiness_status: Phase8CloseoutReadinessStatus | None = None
    allowed_m8_storage_files: list[str] = Field(default_factory=list)
    guarded_storage_files: list[str] = Field(default_factory=list)
    required_phase8_markers: list[str] = Field(default_factory=list)
    release_gate_is_evidence_only: bool = True
    no_new_authority: bool = True
    safe_summary: str


class Phase8ReleaseGateRunResult(BaseModel):
    success: bool
    release_gate_report: Phase8ReleaseGateReport
    product_workbench_e2e_report: Phase8ProductWorkbenchE2EReport
    regression_manifest: Phase8RegressionManifest
    verifier_run_records: list[Phase8VerifierRunRecord] = Field(default_factory=list)
    evidence_index: Phase8EvidenceIndex
    secret_safety_audit: Phase8SecretSafetyAudit
    demo_seed_isolation_audit: Phase8DemoSeedIsolationE2EAudit
    progress_view_model_audit: Phase8ProgressViewModelAudit
    debug_isolation_audit: Phase8DebugIsolationE2EAudit
    artifact_authority_audit: Phase8ArtifactAuthorityAudit
    scope_boundary_audit: Phase8ScopeBoundaryAudit
    closeout_readiness_report: Phase8CloseoutReadinessReport
    known_residuals_report: Phase8KnownResidualCarryForwardReport
    handoff_index: Phase8HandoffIndex
    safe_summary: str


class Phase8ProductWorkbenchE2EReportListResponse(BaseModel):
    e2e_reports: list[Phase8ProductWorkbenchE2EReport] = Field(default_factory=list)
    total_count: int = 0


class Phase8ReleaseGateReportListResponse(BaseModel):
    reports: list[Phase8ReleaseGateReport] = Field(default_factory=list)
    total_count: int = 0


class Phase8RegressionManifestListResponse(BaseModel):
    regression_manifests: list[Phase8RegressionManifest] = Field(default_factory=list)
    total_count: int = 0


class Phase8VerifierRunRecordListResponse(BaseModel):
    verifier_runs: list[Phase8VerifierRunRecord] = Field(default_factory=list)
    total_count: int = 0


class Phase8EvidenceIndexListResponse(BaseModel):
    evidence_indexes: list[Phase8EvidenceIndex] = Field(default_factory=list)
    total_count: int = 0


class Phase8SecretSafetyAuditListResponse(BaseModel):
    secret_safety_audits: list[Phase8SecretSafetyAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase8DemoSeedIsolationE2EAuditListResponse(BaseModel):
    demo_seed_isolation_audits: list[Phase8DemoSeedIsolationE2EAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase8ProgressViewModelAuditListResponse(BaseModel):
    progress_view_model_audits: list[Phase8ProgressViewModelAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase8DebugIsolationE2EAuditListResponse(BaseModel):
    debug_isolation_audits: list[Phase8DebugIsolationE2EAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase8ArtifactAuthorityAuditListResponse(BaseModel):
    artifact_authority_audits: list[Phase8ArtifactAuthorityAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase8ScopeBoundaryAuditListResponse(BaseModel):
    scope_boundary_audits: list[Phase8ScopeBoundaryAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase8KnownResidualCarryForwardReportListResponse(BaseModel):
    known_residuals_reports: list[Phase8KnownResidualCarryForwardReport] = Field(default_factory=list)
    total_count: int = 0


class Phase8CloseoutReadinessReportListResponse(BaseModel):
    closeout_readiness_reports: list[Phase8CloseoutReadinessReport] = Field(default_factory=list)
    total_count: int = 0


class Phase8HandoffIndexListResponse(BaseModel):
    handoff_indexes: list[Phase8HandoffIndex] = Field(default_factory=list)
    total_count: int = 0
