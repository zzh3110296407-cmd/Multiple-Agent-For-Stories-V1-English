from typing import Literal

from pydantic import BaseModel, Field


Phase7ReleaseStatus = Literal["pass", "pass_with_known_gaps", "blocked", "failed"]
Phase7CloseoutReadinessStatus = Literal["ready_for_closeout", "ready_with_known_gaps", "blocked", "failed"]
Phase7VerifierRunStatus = Literal["pass", "failed", "blocked", "skipped", "timed_out"]
Phase7EvidenceSensitivity = Literal["safe", "safe_summary_only", "blocked"]
Phase7RegressionScope = Literal["phase7_m1_m7", "frontend_build", "phase7_m8_release_gate"]


class Phase7VerifierMarkerObservation(BaseModel):
    marker_name: str
    command: str = ""
    expected_marker: str
    observed_marker: str = ""
    run_status: Phase7VerifierRunStatus
    duration_seconds: float = 0
    timeout_seconds: int = 0
    safe_output_excerpt: str = ""
    evidence_ref: str = ""


class Phase7ReleaseGateRunRequest(BaseModel):
    safe_user_note: str = ""
    verifier_marker_observations: list[Phase7VerifierMarkerObservation] = Field(default_factory=list)


class Phase7PluginE2EReport(BaseModel):
    e2e_report_id: str
    release_gate_report_id: str
    project_id: str = "local_project"
    plugin_run_ids: list[str] = Field(default_factory=list)
    final_story_package_snapshot_ids: list[str] = Field(default_factory=list)
    plugin_manifest_ids: list[str] = Field(default_factory=list)
    checkpoint_ids: list[str] = Field(default_factory=list)
    checkpoint_decision_ids: list[str] = Field(default_factory=list)
    script_forging_artifact_counts: dict[str, int] = Field(default_factory=dict)
    plugin_output_artifact_count: int = 0
    plugin_output_artifact_version_count: int = 0
    storyboard_package_count: int = 0
    digital_asset_package_count: int = 0
    e2e_chain_complete: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7ReleaseGateReport(BaseModel):
    release_gate_report_id: str
    project_id: str = "local_project"
    release_status: Phase7ReleaseStatus
    closeout_readiness_status: Phase7CloseoutReadinessStatus
    phase7_milestones_covered: list[str] = Field(default_factory=list)
    phase7_required_markers: list[str] = Field(default_factory=list)
    phase7_observed_markers: list[str] = Field(default_factory=list)
    frontend_build_passed: bool
    plugin_e2e_report_id: str
    regression_manifest_id: str
    evidence_index_id: str
    no_write_audit_id: str
    artifact_versioning_audit_id: str
    checkpoint_authority_audit_id: str
    license_template_safety_audit_id: str
    external_provider_no_call_audit_id: str
    closeout_readiness_report_id: str
    known_residuals_report_id: str
    known_residuals_carried_forward: list[str] = Field(default_factory=list)
    phase7_plugin_system_passed: bool
    phase6_external_analyze_stories_residual_carried_forward: bool
    stable_clean_analyze_stories_claimed: bool = False
    does_not_create_new_plugin_type: bool = True
    does_not_call_external_provider: bool = True
    does_not_mutate_source_story: bool = True
    does_not_overwrite_screenplay_draft: bool = True
    does_not_add_phase8_business_capability: bool = True
    blocking_findings: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7RegressionManifest(BaseModel):
    regression_manifest_id: str
    release_gate_report_id: str
    required_phase7_verifier_markers: list[str] = Field(default_factory=list)
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


class Phase7VerifierRunRecord(BaseModel):
    verifier_run_id: str
    release_gate_report_id: str | None = None
    scope: Phase7RegressionScope
    command: str
    expected_marker: str
    observed_marker: str
    run_status: Phase7VerifierRunStatus
    duration_seconds: float
    timeout_seconds: int
    safe_output_excerpt: str
    evidence_ref: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7EvidenceIndex(BaseModel):
    evidence_index_id: str
    release_gate_report_id: str
    safe_evidence_refs: list[dict] = Field(default_factory=list)
    milestone_evidence_counts: dict[str, int] = Field(default_factory=dict)
    storage_file_hashes: dict[str, str] = Field(default_factory=dict)
    guarded_storage_hashes_before: dict[str, str] = Field(default_factory=dict)
    guarded_storage_hashes_after: dict[str, str] = Field(default_factory=dict)
    evidence_sensitivity: Phase7EvidenceSensitivity = "safe"
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


class Phase7NoWriteAudit(BaseModel):
    no_write_audit_id: str
    release_gate_report_id: str
    allowed_m8_storage_files: list[str] = Field(default_factory=list)
    guarded_storage_files_checked: list[str] = Field(default_factory=list)
    created_storage_files: list[str] = Field(default_factory=list)
    mutated_storage_files: list[str] = Field(default_factory=list)
    deleted_storage_files: list[str] = Field(default_factory=list)
    only_m8_storage_changed: bool
    guarded_storage_unchanged: bool
    source_story_fact_files_unchanged: bool
    m1_m7_records_unchanged_by_m8: bool
    rollback_on_forbidden_mutation: bool = True
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7PluginArtifactVersioningAudit(BaseModel):
    artifact_versioning_audit_id: str
    release_gate_report_id: str
    checked_domain_record_refs: list[dict] = Field(default_factory=list)
    missing_artifact_refs: list[str] = Field(default_factory=list)
    missing_version_refs: list[str] = Field(default_factory=list)
    artifact_versioning_passed: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7CheckpointAuthorityAudit(BaseModel):
    checkpoint_authority_audit_id: str
    release_gate_report_id: str
    checked_checkpoint_ids: list[str] = Field(default_factory=list)
    checked_decision_ids: list[str] = Field(default_factory=list)
    all_decisions_plugin_step_only: bool
    all_decisions_do_not_modify_source_story: bool
    all_checkpoints_do_not_mutate_source_story: bool
    checkpoint_authority_passed: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7LicenseTemplateSafetyAudit(BaseModel):
    license_template_safety_audit_id: str
    release_gate_report_id: str
    checked_manifest_ids: list[str] = Field(default_factory=list)
    checked_template_refs: list[str] = Field(default_factory=list)
    no_unlicensed_external_template_claim: bool
    no_external_media_prompt_template_created: bool
    no_provider_specific_template_secret: bool
    license_template_safety_passed: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7ExternalProviderNoCallAudit(BaseModel):
    external_provider_no_call_audit_id: str
    release_gate_report_id: str
    forbidden_media_files_checked: list[str] = Field(default_factory=list)
    forbidden_media_files_present: list[str] = Field(default_factory=list)
    external_media_provider_called_flags: list[dict] = Field(default_factory=list)
    no_external_provider_call: bool
    no_generated_media_binary: bool
    no_external_prompt_package: bool
    external_provider_no_call_passed: bool
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7CloseoutReadinessReport(BaseModel):
    closeout_readiness_report_id: str
    release_gate_report_id: str
    readiness_status: Phase7CloseoutReadinessStatus
    m1_pass: bool
    m2_pass: bool
    m3_pass: bool
    m4_pass: bool
    m5_pass: bool
    m6_pass: bool
    m7_pass: bool
    m8_release_gate_pass: bool
    ready_for_phase7_closeout: bool
    ready_for_phase8_handoff_with_known_residuals: bool
    official_closeout_docs_owned_by_phase7_main_session: bool = True
    known_residuals_to_carry_forward: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7KnownResidualCarryForwardReport(BaseModel):
    residual_report_id: str
    release_gate_report_id: str
    known_residuals: list[dict] = Field(default_factory=list)
    character_arc_empty_by_design_carried_forward: bool
    stable_clean_analyze_stories_available: bool = False
    stable_clean_analyze_stories_claimed: bool = False
    phase7_plugin_system_passed: bool
    unsafe_closure_claims: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class Phase7ReleaseGateStatusResponse(BaseModel):
    report_count: int = 0
    latest_release_gate_report_id: str | None = None
    latest_release_status: Phase7ReleaseStatus | None = None
    latest_closeout_readiness_status: Phase7CloseoutReadinessStatus | None = None
    allowed_m8_storage_files: list[str] = Field(default_factory=list)
    guarded_storage_files: list[str] = Field(default_factory=list)
    required_phase7_markers: list[str] = Field(default_factory=list)
    release_gate_is_evidence_only: bool = True
    no_new_authority: bool = True
    safe_summary: str


class Phase7ReleaseGateRunResult(BaseModel):
    success: bool
    release_gate_report: Phase7ReleaseGateReport
    plugin_e2e_report: Phase7PluginE2EReport
    regression_manifest: Phase7RegressionManifest
    verifier_run_records: list[Phase7VerifierRunRecord] = Field(default_factory=list)
    evidence_index: Phase7EvidenceIndex
    no_write_audit: Phase7NoWriteAudit
    artifact_versioning_audit: Phase7PluginArtifactVersioningAudit
    checkpoint_authority_audit: Phase7CheckpointAuthorityAudit
    license_template_safety_audit: Phase7LicenseTemplateSafetyAudit
    external_provider_no_call_audit: Phase7ExternalProviderNoCallAudit
    closeout_readiness_report: Phase7CloseoutReadinessReport
    known_residuals_report: Phase7KnownResidualCarryForwardReport
    safe_summary: str


class Phase7PluginE2EReportListResponse(BaseModel):
    e2e_reports: list[Phase7PluginE2EReport] = Field(default_factory=list)
    total_count: int = 0


class Phase7ReleaseGateReportListResponse(BaseModel):
    reports: list[Phase7ReleaseGateReport] = Field(default_factory=list)
    total_count: int = 0


class Phase7RegressionManifestListResponse(BaseModel):
    regression_manifests: list[Phase7RegressionManifest] = Field(default_factory=list)
    total_count: int = 0


class Phase7VerifierRunRecordListResponse(BaseModel):
    verifier_runs: list[Phase7VerifierRunRecord] = Field(default_factory=list)
    total_count: int = 0


class Phase7EvidenceIndexListResponse(BaseModel):
    evidence_indexes: list[Phase7EvidenceIndex] = Field(default_factory=list)
    total_count: int = 0


class Phase7NoWriteAuditListResponse(BaseModel):
    no_write_audits: list[Phase7NoWriteAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase7PluginArtifactVersioningAuditListResponse(BaseModel):
    artifact_versioning_audits: list[Phase7PluginArtifactVersioningAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase7CheckpointAuthorityAuditListResponse(BaseModel):
    checkpoint_authority_audits: list[Phase7CheckpointAuthorityAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase7LicenseTemplateSafetyAuditListResponse(BaseModel):
    license_template_audits: list[Phase7LicenseTemplateSafetyAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase7ExternalProviderNoCallAuditListResponse(BaseModel):
    external_provider_no_call_audits: list[Phase7ExternalProviderNoCallAudit] = Field(default_factory=list)
    total_count: int = 0


class Phase7CloseoutReadinessReportListResponse(BaseModel):
    closeout_readiness_reports: list[Phase7CloseoutReadinessReport] = Field(default_factory=list)
    total_count: int = 0


class Phase7KnownResidualCarryForwardReportListResponse(BaseModel):
    known_residuals_reports: list[Phase7KnownResidualCarryForwardReport] = Field(default_factory=list)
    total_count: int = 0
