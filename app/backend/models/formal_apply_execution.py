from typing import Literal

from pydantic import BaseModel, Field

from .formal_apply_decision import FormalApplyApprovedNextStep


FormalApplyExecutionStatus = Literal[
    "executed",
    "blocked",
    "stale",
    "unsupported",
    "failed_closed",
]
FormalApplyExecutionType = Literal[
    "create_framework_apply_proposal",
    "create_chapter_archive_proposal",
    "create_narrative_debt_proposal",
    "route_to_m7",
    "none",
]
FormalApplyProposalType = Literal[
    "framework_apply",
    "chapter_archive",
    "narrative_debt",
]
FormalApplyProposalStatus = Literal[
    "proposed",
    "blocked",
    "superseded",
    "cancelled",
]
FormalApplyM6HandoffStatus = Literal["required", "not_required", "blocked"]
FormalApplyM7HandoffStatus = Literal["not_applicable", "required", "blocked"]


class FormalApplyExecutionReadiness(BaseModel):
    success: bool
    approval_id: str
    decision_record_id: str = ""
    evidence_snapshot_id: str = ""
    plan_id: str = ""
    target_id: str = ""
    target_type: str = ""
    source_lineage_id: str = ""
    eligibility_report_id: str = ""
    approved_next_step: FormalApplyApprovedNextStep = "none"
    execution_type: FormalApplyExecutionType = "none"
    expected_proposal_type: FormalApplyProposalType | None = None
    can_execute: bool = False
    already_executed: bool = False
    stale_evidence: bool = False
    current_evidence_hashes: dict[str, str] = Field(default_factory=dict)
    snapshot_evidence_hashes: dict[str, str] = Field(default_factory=dict)
    blocked_reason_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    non_authorized_actions: list[str] = Field(default_factory=list)
    safe_summary: str


class FormalApplyExecutionRequest(BaseModel):
    safe_user_note: str = ""


class FormalApplyExecutionResult(BaseModel):
    execution_result_id: str
    project_id: str = "local_project"
    approval_id: str
    decision_record_id: str
    evidence_snapshot_id: str
    target_id: str
    target_type: str
    source_lineage_id: str
    eligibility_report_id: str
    plan_id: str
    approved_next_step: FormalApplyApprovedNextStep
    execution_type: FormalApplyExecutionType
    execution_status: FormalApplyExecutionStatus
    created_proposal_id: str | None = None
    created_proposal_type: FormalApplyProposalType | None = None
    rollback_ref_id: str | None = None
    write_audit_id: str
    propagation_review_required: bool = True
    m6_handoff_status: FormalApplyM6HandoffStatus = "required"
    m7_handoff_status: FormalApplyM7HandoffStatus = "not_applicable"
    authorizes_formal_record_write: bool = False
    authorizes_apply_execution_now: bool = False
    creates_formal_record_now: bool = False
    writes_formal_story_fact_now: bool = False
    no_formal_write_performed: bool = True
    no_active_framework_mutation: bool = True
    no_event_memory_state_scene_write: bool = True
    no_chapter_archive_record_created: bool = True
    no_narrative_debt_record_created: bool = True
    no_recommendation_created: bool = True
    no_propagation_rewrite: bool = True
    full_automatic_undo_supported: bool = False
    blocked_reason_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    safe_user_note: str = ""
    safe_summary: str
    created_at: str
    version_id: str


class FormalApplyRollbackRef(BaseModel):
    rollback_ref_id: str
    execution_result_id: str
    proposal_id: str | None = None
    proposal_type: FormalApplyProposalType | None = None
    target_id: str
    plan_id: str
    approval_id: str
    before_fingerprints: dict[str, str] = Field(default_factory=dict)
    after_fingerprint_previews: dict[str, str] = Field(default_factory=dict)
    inverse_plan_hints: list[str] = Field(default_factory=list)
    rollback_scope: list[str] = Field(default_factory=list)
    full_automatic_undo_supported: bool = False
    safe_summary: str
    created_at: str
    version_id: str


class ControlledApplyWriteAudit(BaseModel):
    write_audit_id: str
    execution_result_id: str
    approval_id: str
    allowed_storage_files: list[str] = Field(default_factory=list)
    forbidden_storage_files: list[str] = Field(default_factory=list)
    created_storage_files: list[str] = Field(default_factory=list)
    mutated_storage_files: list[str] = Field(default_factory=list)
    unchanged_forbidden_files: list[str] = Field(default_factory=list)
    only_allowed_storage_changed: bool = True
    no_global_decision_write: bool = True
    no_active_framework_mutation: bool = True
    no_formal_story_fact_write: bool = True
    no_event_memory_state_scene_write: bool = True
    no_chapter_archive_record_created: bool = True
    no_narrative_debt_record_created: bool = True
    no_recommendation_created: bool = True
    no_propagation_rewrite: bool = True
    safe_summary: str
    created_at: str
    version_id: str


class FormalApplyProposalBase(BaseModel):
    proposal_id: str
    proposal_type: FormalApplyProposalType
    proposal_status: FormalApplyProposalStatus = "proposed"
    project_id: str = "local_project"
    approval_id: str
    decision_record_id: str
    evidence_snapshot_id: str
    target_id: str
    target_type: str
    source_lineage_id: str
    eligibility_report_id: str
    plan_id: str
    source_candidate_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class FrameworkApplyProposal(FormalApplyProposalBase):
    proposal_type: Literal["framework_apply"] = "framework_apply"
    merge_strategy: str = "merge_into_user_confirmed_framework_version"
    candidate_framework_ref: str
    active_framework_mutation_performed: bool = False
    set_active_requested: bool = False
    proposed_change_summary: str
    safe_component_refs: list[str] = Field(default_factory=list)


class ChapterArchiveProposal(FormalApplyProposalBase):
    proposal_type: Literal["chapter_archive"] = "chapter_archive"
    chapter_index: int | None = None
    archive_summary_candidate: str = ""
    chapter_goal_result_candidate: str = ""
    reader_emotion_result_candidate: str = ""
    conflict_state_candidate: str = ""
    candidate_status_at_creation: str = ""
    creates_chapter_archive_record_now: bool = False


class NarrativeDebtProposal(FormalApplyProposalBase):
    proposal_type: Literal["narrative_debt"] = "narrative_debt"
    debt_type: str = "unknown"
    payoff_required: bool = False
    open_ambiguity_allowed: bool = False
    symbolic_unresolved: bool = False
    payoff_deadline_hint: str = ""
    candidate_status_at_creation: str = ""
    creates_narrative_debt_record_now: bool = False


class FormalApplyExecutionStatusResponse(BaseModel):
    execution_result_count: int = 0
    rollback_ref_count: int = 0
    write_audit_count: int = 0
    latest_execution_result_id: str | None = None
    proposal_only: bool = True
    formal_story_write_disabled: bool = True
    active_framework_mutation_disabled: bool = True
    allowed_storage_files: list[str] = Field(default_factory=list)
    forbidden_storage_files: list[str] = Field(default_factory=list)
    safe_summary: str


class FormalApplyExecutionResultListResponse(BaseModel):
    execution_results: list[FormalApplyExecutionResult] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyRollbackRefListResponse(BaseModel):
    rollback_refs: list[FormalApplyRollbackRef] = Field(default_factory=list)
    total_count: int = 0


class ControlledApplyWriteAuditListResponse(BaseModel):
    write_audits: list[ControlledApplyWriteAudit] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyProposalStatusResponse(BaseModel):
    framework_proposal_count: int = 0
    chapter_archive_proposal_count: int = 0
    narrative_debt_proposal_count: int = 0
    total_count: int = 0
    allowed_storage_files: list[str] = Field(default_factory=list)
    proposal_only: bool = True
    no_formal_write_performed: bool = True
    safe_summary: str


class FrameworkApplyProposalListResponse(BaseModel):
    framework_proposals: list[FrameworkApplyProposal] = Field(default_factory=list)
    total_count: int = 0


class ChapterArchiveProposalListResponse(BaseModel):
    chapter_archive_proposals: list[ChapterArchiveProposal] = Field(default_factory=list)
    total_count: int = 0


class NarrativeDebtProposalListResponse(BaseModel):
    narrative_debt_proposals: list[NarrativeDebtProposal] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyProposalListResponse(BaseModel):
    proposals: list[
        FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal
    ] = Field(default_factory=list)
    total_count: int = 0
