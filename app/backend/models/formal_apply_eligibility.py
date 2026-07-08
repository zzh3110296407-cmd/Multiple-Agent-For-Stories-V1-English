from typing import Literal

from pydantic import BaseModel, Field


FormalApplyTargetType = Literal[
    "imported_framework_merge_target",
    "imported_framework_set_active_target",
    "imported_framework_reference_only_target",
    "chapter_archive_candidate_target",
    "narrative_debt_candidate_target",
    "framework_library_item_target",
    "framework_pattern_target",
    "module_composition_rule_target",
    "recommendation_promotion_target",
    "unsupported_target",
]
FormalApplyTargetStatus = Literal[
    "inspected",
    "eligible",
    "blocked",
    "reference_only",
    "unsupported",
    "future_governance_required",
]
FormalApplyEligibilityStatus = Literal[
    "eligible_for_m3_dry_run",
    "eligible_with_warnings_for_m3_dry_run",
    "blocked",
    "reference_only",
    "requires_user_supplement",
    "unsupported",
    "future_governance_required",
]
FormalApplyBlockSeverity = Literal["info", "warning", "blocking"]


class FormalApplyTarget(BaseModel):
    target_id: str
    project_id: str = "local_project"
    target_type: FormalApplyTargetType
    source_type: str
    source_id: str
    source_family: str
    candidate_id: str | None = None
    target_label: str
    target_status: FormalApplyTargetStatus = "inspected"
    allowed_next_step: str
    requires_user_decision_before_apply: bool = True
    created_at: str
    updated_at: str
    version_id: str


class FormalApplySourceLineage(BaseModel):
    lineage_id: str
    target_id: str
    source_system: str
    source_record_type: str
    source_record_id: str
    source_refs: list[str] = Field(default_factory=list)
    m1_replay_report_id: str | None = None
    m1_known_gap_record_ids: list[str] = Field(default_factory=list)
    m1_compatibility_matrix_id: str | None = None
    m1_evidence_index_id: str | None = None
    source_package_status: str = "unknown"
    external_contract_confidence: str = "stable_with_known_gaps"
    known_gaps: list[str] = Field(default_factory=list)
    user_supplement_refs: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str


class FormalApplyBlockReason(BaseModel):
    reason_id: str
    target_id: str
    reason_code: str
    severity: FormalApplyBlockSeverity = "blocking"
    source_ref: str | None = None
    safe_summary: str
    requires_user_supplement: bool = False
    can_be_resolved_in_m2: bool = False
    created_at: str


class FormalApplyEligibilityReport(BaseModel):
    eligibility_report_id: str
    target_id: str
    target_type: FormalApplyTargetType
    eligibility_status: FormalApplyEligibilityStatus
    can_enter_m3_dry_run: bool = False
    can_write_formal_record_now: bool = False
    creates_formal_record_now: bool = False
    writes_formal_story_fact_now: bool = False
    no_formal_write_performed: bool = True
    requires_user_decision_before_apply: bool = True
    allowed_next_step: str
    block_reason_ids: list[str] = Field(default_factory=list)
    lineage_id: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str


class FormalApplyInspectRequest(BaseModel):
    target_type: FormalApplyTargetType = "unsupported_target"
    source_type: str = ""
    source_id: str = ""
    source_family: str = ""
    candidate_id: str | None = None
    project_id: str = "local_project"
    safe_note: str = ""


class FormalApplyEligibilityResult(BaseModel):
    success: bool
    target: FormalApplyTarget
    lineage: FormalApplySourceLineage
    eligibility_report: FormalApplyEligibilityReport
    block_reasons: list[FormalApplyBlockReason] = Field(default_factory=list)


class FormalApplyEligibilityStatusResponse(BaseModel):
    target_count: int = 0
    eligibility_report_count: int = 0
    block_reason_count: int = 0
    source_lineage_count: int = 0
    latest_eligibility_report_id: str | None = None
    formal_write_guard_active: bool = True
    known_gap_guard_active: bool = True
    allowed_storage_files: list[str] = Field(default_factory=list)
    safe_summary: str


class FormalApplyTargetListResponse(BaseModel):
    targets: list[FormalApplyTarget] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyEligibilityReportListResponse(BaseModel):
    eligibility_reports: list[FormalApplyEligibilityReport] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyBlockReasonListResponse(BaseModel):
    block_reasons: list[FormalApplyBlockReason] = Field(default_factory=list)
    total_count: int = 0
