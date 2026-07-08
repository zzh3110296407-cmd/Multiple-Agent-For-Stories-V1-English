from typing import Any, Literal

from pydantic import BaseModel, Field


SourcePackageStatus = Literal[
    "stable_with_known_gaps",
    "stable_clean_not_available",
    "stable_clean_verified",
    "unknown",
]
ReplayMode = Literal[
    "no_stable_clean_available",
    "targeted_stable_clean_replay",
    "fixture_replay",
    "provisional_replay",
]
ReplayStatus = Literal["pass", "failed", "blocked", "skipped"]
ExternalContractConfidence = Literal[
    "fixture_only",
    "stable_with_known_gaps",
    "stable_clean_verified",
    "blocked",
]
ReplayRunScope = Literal[
    "targeted_contract_replay",
    "fixture_only",
    "no_stable_clean_available",
]
ReplayPackageType = Literal[
    "none",
    "fixture",
    "v4_stable_with_known_gaps",
    "future_stable_clean",
]
KnownGapId = Literal[
    "character_arc_empty_by_design",
    "future_stable_clean_replay_pending",
]
KnownGapStatus = Literal["carried_forward", "closed", "downgraded", "blocked"]
CompatibilityConclusion = Literal[
    "compatible",
    "compatible_with_known_gaps",
    "not_compatible",
    "not_available",
]


class StableCleanReplayReport(BaseModel):
    replay_report_id: str
    project_id: str = "local_project"
    source_package_status_before: SourcePackageStatus = "unknown"
    replay_mode: ReplayMode
    replay_status: ReplayStatus
    stable_clean_package_available: bool
    source_import_id: str | None = None
    bundle_manifest_id: str | None = None
    framework_candidate_id: str | None = None
    source_package_fingerprint_id: str | None = None
    checked_pipeline_steps: list[str] = Field(default_factory=list)
    passed_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)
    blocked_steps: list[str] = Field(default_factory=list)
    known_gap_record_ids: list[str] = Field(default_factory=list)
    compatibility_matrix_id: str | None = None
    evidence_index_id: str | None = None
    external_contract_confidence: ExternalContractConfidence
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str


class AnalyzeStoriesReplayRun(BaseModel):
    replay_run_id: str
    project_id: str = "local_project"
    replay_report_id: str
    run_scope: ReplayRunScope
    used_package_type: ReplayPackageType = "none"
    step_results: list[dict[str, Any]] = Field(default_factory=list)
    import_id: str | None = None
    framework_candidate_id: str | None = None
    viewer_state_ids: list[str] = Field(default_factory=list)
    bundle_validation_report_id: str | None = None
    adapter_derivation_report_id: str | None = None
    library_item_ids: list[str] = Field(default_factory=list)
    all_commands_passed: bool = False
    safety_scan_passed: bool = False
    no_formal_write_pollution: bool = False
    duration_seconds: float | None = None
    safe_summary: str
    created_at: str
    version_id: str


class KnownGapCarryForwardRecord(BaseModel):
    known_gap_record_id: str
    project_id: str = "local_project"
    gap_id: KnownGapId
    source_package_status: SourcePackageStatus
    gap_status: KnownGapStatus
    affected_capabilities: list[str] = Field(default_factory=list)
    hard_block_rules: list[str] = Field(default_factory=list)
    user_supplement_allowed: bool = True
    user_supplement_must_be_separate_evidence: bool = True
    close_condition_summary: str
    source_refs: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class ReplayGateCompatibilityMatrix(BaseModel):
    matrix_id: str
    replay_report_id: str
    package_label: str
    package_status: str
    framework_package_supported: bool = False
    story_analysis_report_supported: bool = False
    full_book_bundle_supported: bool = False
    character_arc_evidence_present: bool = False
    character_arc_evidence_source_attributed: bool = False
    known_gaps: list[str] = Field(default_factory=list)
    unsupported_fields: list[str] = Field(default_factory=list)
    normalized_fields: list[str] = Field(default_factory=list)
    conclusion: CompatibilityConclusion
    safe_summary: str
    created_at: str
    version_id: str


class ReplayEvidenceIndex(BaseModel):
    evidence_index_id: str
    replay_report_id: str
    evidence_docs: list[str] = Field(default_factory=list)
    verifier_outputs: list[str] = Field(default_factory=list)
    safety_scan_refs: list[str] = Field(default_factory=list)
    storage_record_refs: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    version_id: str


class ReplayGateRunRequest(BaseModel):
    run_mode: Literal[
        "no_stable_clean_available",
        "targeted_stable_clean_replay",
    ] = "no_stable_clean_available"
    source_import_id: str | None = None
    bundle_manifest_id: str | None = None
    framework_candidate_id: str | None = None
    viewer_state_ids: list[str] = Field(default_factory=list)
    safe_user_note: str = ""


class ReplayGateStatusResponse(BaseModel):
    external_contract_confidence: ExternalContractConfidence = "stable_with_known_gaps"
    stable_clean_package_available: bool = False
    active_known_gaps: list[str] = Field(default_factory=list)
    formal_apply_guard_active: bool = True
    latest_replay_report_id: str | None = None
    safe_summary: str


class ReplayGateRunResult(BaseModel):
    success: bool
    report: StableCleanReplayReport
    replay_run: AnalyzeStoriesReplayRun
    known_gaps: list[KnownGapCarryForwardRecord] = Field(default_factory=list)
    compatibility_matrix: ReplayGateCompatibilityMatrix
    evidence_index: ReplayEvidenceIndex


class ReplayGateReportListResponse(BaseModel):
    reports: list[StableCleanReplayReport] = Field(default_factory=list)
    total_count: int = 0


class KnownGapCarryForwardListResponse(BaseModel):
    known_gaps: list[KnownGapCarryForwardRecord] = Field(default_factory=list)
    total_count: int = 0

