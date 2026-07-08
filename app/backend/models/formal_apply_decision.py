from typing import Any, Literal

from pydantic import BaseModel, Field, validator


FormalApplyDecisionType = Literal[
    "approve_for_next_step",
    "override_warning_and_approve",
    "reject",
    "defer",
    "request_more_evidence",
    "cancel",
]
FormalApplyDecisionStatus = Literal["recorded", "blocked", "superseded", "expired"]
FormalApplyDecisionGateStatus = Literal["allowed", "blocked", "recorded_no_approval"]
FormalApplyDecisionScope = Literal[
    "framework_apply",
    "chapter_archive_proposal",
    "narrative_debt_proposal",
    "recommendation_governance",
    "view_only",
]
FormalApplyApprovedNextStep = Literal[
    "m5_create_framework_apply_proposal",
    "m5_create_chapter_archive_proposal",
    "m5_create_narrative_debt_proposal",
    "m7_recommendation_governance_review",
    "none",
]
FormalApplyQuestionStatus = Literal["open", "answered", "cancelled"]


class FormalApplyDecision(BaseModel):
    decision_record_id: str
    project_id: str = "local_project"
    target_id: str
    source_lineage_id: str
    eligibility_report_id: str
    plan_id: str
    impact_preview_id: str
    diff_summary_id: str
    safety_check_id: str
    evidence_snapshot_id: str
    global_decision_id: str | None = None
    decision_type: FormalApplyDecisionType
    decision_status: FormalApplyDecisionStatus = "recorded"
    decision_scope: FormalApplyDecisionScope = "view_only"
    approved_next_step: FormalApplyApprovedNextStep = "none"
    requires_m5_execution: bool = False
    authorizes_formal_record_write: bool = False
    authorizes_apply_execution_now: bool = False
    authorizes_proposal_creation_now: bool = False
    creates_formal_record_now: bool = False
    writes_formal_story_fact_now: bool = False
    no_formal_write_performed: bool = True
    user_note: str = ""
    blocked_reason_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str


class FormalApplyApprovalRecord(BaseModel):
    approval_id: str
    decision_record_id: str
    target_id: str
    plan_id: str
    approval_type: FormalApplyDecisionType
    approved_next_step: FormalApplyApprovedNextStep
    acknowledged_warning_codes: list[str] = Field(default_factory=list)
    override_record_ids: list[str] = Field(default_factory=list)
    user_confirmation_text: str = ""
    authorizes_apply_execution_now: bool = False
    authorizes_proposal_creation_now: bool = False
    creates_formal_record_now: bool = False
    no_formal_write_performed: bool = True
    created_at: str
    version_id: str


class FormalApplyRejectionRecord(BaseModel):
    rejection_id: str
    decision_record_id: str
    target_id: str
    plan_id: str
    rejection_reason: str = ""
    safe_summary: str
    created_at: str
    version_id: str


class FormalApplyUserOverride(BaseModel):
    override_id: str
    decision_record_id: str
    target_id: str
    plan_id: str
    override_type: str
    override_reason: str
    acknowledged_warning_codes: list[str] = Field(default_factory=list)
    non_overridable_block_reason_ids: list[str] = Field(default_factory=list)
    created_at: str
    version_id: str


class FormalApplyQuestion(BaseModel):
    question_id: str
    decision_record_id: str
    target_id: str
    plan_id: str
    question_type: str = "more_evidence"
    question_text: str
    question_status: FormalApplyQuestionStatus = "open"
    answer_text: str = ""
    answered_at: str | None = None
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class FormalApplyDecisionEvidenceSnapshot(BaseModel):
    evidence_snapshot_id: str
    decision_record_id: str
    target_id: str
    source_lineage_id: str
    eligibility_report_id: str
    plan_id: str
    impact_preview_id: str
    diff_summary_id: str
    safety_check_id: str
    plan_status: str
    safety_status: str
    allowed_next_step: str
    block_reason_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    before_fingerprints: dict[str, str] = Field(default_factory=dict)
    after_fingerprint_previews: dict[str, str] = Field(default_factory=dict)
    evidence_hashes: dict[str, str] = Field(default_factory=dict)
    safe_summaries: list[str] = Field(default_factory=list)
    created_at: str
    version_id: str

    @validator("safe_summaries", pre=True)
    def _coerce_safe_summaries(cls, value: Any) -> list[str]:
        if isinstance(value, dict):
            return [f"{key}: {summary}" for key, summary in value.items()]
        if isinstance(value, list):
            return value
        return []


class FormalApplyDecisionGateResult(BaseModel):
    success: bool
    gate_status: FormalApplyDecisionGateStatus
    plan_id: str
    target_id: str
    decision: FormalApplyDecision | None = None
    approval_record: FormalApplyApprovalRecord | None = None
    rejection_record: FormalApplyRejectionRecord | None = None
    override_record: FormalApplyUserOverride | None = None
    question: FormalApplyQuestion | None = None
    evidence_snapshot: FormalApplyDecisionEvidenceSnapshot | None = None
    allowed_next_step: FormalApplyApprovedNextStep = "none"
    can_enter_m5: bool = False
    blocked_reason_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    safe_summary: str


class FormalApplyDecisionSubmitRequest(BaseModel):
    decision_type: FormalApplyDecisionType
    approved_next_step: FormalApplyApprovedNextStep | None = None
    user_note: str = ""
    override_reason: str = ""
    acknowledged_warning_codes: list[str] = Field(default_factory=list)
    question_text: str = ""
    rejection_reason: str = ""


class FormalApplyQuestionAnswerRequest(BaseModel):
    answer_text: str
    user_note: str = ""


class FormalApplyDecisionReadinessResult(BaseModel):
    success: bool
    gate_status: FormalApplyDecisionGateStatus = "blocked"
    plan_id: str
    target_id: str = ""
    target_type: str = ""
    source_lineage_id: str = ""
    eligibility_report_id: str = ""
    diff_summary_id: str = ""
    impact_preview_id: str = ""
    safety_check_id: str = ""
    plan_status: str = ""
    safety_status: str = ""
    can_enter_m4_decision: bool = False
    can_record_approval: bool = False
    can_request_more_evidence: bool = True
    can_reject_defer_cancel: bool = True
    allowed_next_step: str = ""
    expected_approved_next_step: FormalApplyApprovedNextStep = "none"
    decision_scope: FormalApplyDecisionScope = "view_only"
    requires_m5_execution: bool = False
    hard_blocker_ids: list[str] = Field(default_factory=list)
    blocked_reason_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    non_authorized_actions: list[str] = Field(default_factory=list)
    artifact_ids: dict[str, str] = Field(default_factory=dict)
    no_write_guarantees: dict[str, bool] = Field(default_factory=dict)
    safe_summary: str


class FormalApplyDecisionStatusResponse(BaseModel):
    decision_count: int = 0
    approval_count: int = 0
    rejection_count: int = 0
    override_count: int = 0
    question_count: int = 0
    evidence_snapshot_count: int = 0
    latest_decision_record_id: str | None = None
    global_decision_write_disabled: bool = True
    apply_execution_disabled: bool = True
    proposal_creation_disabled: bool = True
    formal_story_write_disabled: bool = True
    allowed_storage_files: list[str] = Field(default_factory=list)
    safe_summary: str


class FormalApplyDecisionListResponse(BaseModel):
    decisions: list[FormalApplyDecision] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyApprovalRecordListResponse(BaseModel):
    approval_records: list[FormalApplyApprovalRecord] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyRejectionRecordListResponse(BaseModel):
    rejection_records: list[FormalApplyRejectionRecord] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyUserOverrideListResponse(BaseModel):
    override_records: list[FormalApplyUserOverride] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyQuestionListResponse(BaseModel):
    questions: list[FormalApplyQuestion] = Field(default_factory=list)
    total_count: int = 0
