from typing import Literal

from pydantic import BaseModel, Field

from .formal_apply_execution import FormalApplyProposalType


PropagationImpactStatus = Literal[
    "created",
    "review_tasks_created",
    "review_in_progress",
    "reviewed",
    "blocked",
    "superseded",
]
AffectedObjectReviewTaskStatus = Literal[
    "pending",
    "reviewed",
    "deferred",
    "dismissed",
    "blocked",
]
CrossChapterRecheckPlanStatus = Literal[
    "draft",
    "ready_for_review",
    "reviewed",
    "cancelled",
    "superseded",
]


class PropagationReadinessResult(BaseModel):
    success: bool = True
    execution_result_id: str
    can_review: bool = False
    execution_status: str = ""
    created_proposal_id: str | None = None
    created_proposal_type: FormalApplyProposalType | None = None
    proposal_status: str = ""
    rollback_ref_id: str | None = None
    write_audit_id: str = ""
    propagation_review_required: bool = False
    m6_handoff_status: str = ""
    blocked_reason_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    artifact_ids: dict[str, str] = Field(default_factory=dict)
    non_authorized_actions: list[str] = Field(default_factory=list)
    safe_summary: str


class PropagationReviewRequest(BaseModel):
    safe_user_note: str = ""


class PropagationTaskStatusRequest(BaseModel):
    safe_user_note: str = ""
    status_note: str = ""


class PropagationImpactRecord(BaseModel):
    impact_record_id: str
    project_id: str
    execution_result_id: str
    proposal_id: str
    proposal_type: FormalApplyProposalType
    approval_id: str
    decision_record_id: str
    evidence_snapshot_id: str
    target_id: str
    target_type: str
    source_lineage_id: str
    eligibility_report_id: str
    plan_id: str
    rollback_ref_id: str
    write_audit_id: str
    impact_status: PropagationImpactStatus
    affected_domains: list[str] = Field(default_factory=list)
    affected_object_refs: list[dict] = Field(default_factory=list)
    review_task_ids: list[str] = Field(default_factory=list)
    recheck_plan_ids: list[str] = Field(default_factory=list)
    framework_report_id: str | None = None
    blocked_reason_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    review_task_state_is_confirmation: bool = False
    user_confirmation_recorded: bool = False
    formal_resolution_performed: bool = False
    propagation_rewrite_performed: bool = False
    safe_user_note: str = ""
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class AffectedObjectReviewTask(BaseModel):
    task_id: str
    impact_record_id: str
    execution_result_id: str
    proposal_id: str
    proposal_type: FormalApplyProposalType
    object_type: str
    object_ref: str
    object_label: str
    review_reason: str
    review_scope: str
    task_status: AffectedObjectReviewTaskStatus = "pending"
    status_note: str = ""
    source_refs: list[str] = Field(default_factory=list)
    blocks_formal_confirmation: bool = True
    reviewed_at: str | None = None
    created_at: str
    updated_at: str
    version_id: str


class CrossChapterRecheckPlan(BaseModel):
    recheck_plan_id: str
    impact_record_id: str
    execution_result_id: str
    proposal_id: str
    proposal_type: FormalApplyProposalType
    recheck_status: CrossChapterRecheckPlanStatus = "ready_for_review"
    chapter_refs: list[str] = Field(default_factory=list)
    object_refs: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    required_before_formal_confirmation: bool = True
    no_regeneration_planned: bool = True
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class FrameworkChangePropagationReport(BaseModel):
    framework_report_id: str
    impact_record_id: str
    execution_result_id: str
    proposal_id: str
    candidate_framework_ref: str
    safe_component_refs: list[str] = Field(default_factory=list)
    active_framework_review_required: bool = True
    framework_package_review_required: bool = True
    current_chapter_jit_review_required: bool = True
    built_chapter_framework_staleness_review_required: bool = True
    future_assignment_recheck_required: bool = True
    framework_library_reference_review_required: bool = True
    affected_chapter_refs: list[str] = Field(default_factory=list)
    affected_framework_refs: list[str] = Field(default_factory=list)
    no_active_framework_mutation: bool = True
    no_framework_package_write: bool = True
    no_chapter_framework_prebuild: bool = True
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class PropagationReviewResult(BaseModel):
    success: bool
    readiness: PropagationReadinessResult
    impact_record: PropagationImpactRecord
    review_tasks: list[AffectedObjectReviewTask] = Field(default_factory=list)
    recheck_plan: CrossChapterRecheckPlan | None = None
    framework_report: FrameworkChangePropagationReport | None = None
    safe_summary: str


class PropagationGovernanceStatusResponse(BaseModel):
    impact_record_count: int = 0
    review_task_count: int = 0
    pending_review_task_count: int = 0
    recheck_plan_count: int = 0
    framework_report_count: int = 0
    latest_impact_record_id: str | None = None
    governance_only: bool = True
    formal_story_write_disabled: bool = True
    propagation_rewrite_disabled: bool = True
    allowed_storage_files: list[str] = Field(default_factory=list)
    forbidden_storage_files: list[str] = Field(default_factory=list)
    safe_summary: str


class PropagationImpactRecordListResponse(BaseModel):
    impact_records: list[PropagationImpactRecord] = Field(default_factory=list)
    total_count: int = 0


class AffectedObjectReviewTaskListResponse(BaseModel):
    review_tasks: list[AffectedObjectReviewTask] = Field(default_factory=list)
    total_count: int = 0


class CrossChapterRecheckPlanListResponse(BaseModel):
    recheck_plans: list[CrossChapterRecheckPlan] = Field(default_factory=list)
    total_count: int = 0


class FrameworkChangePropagationReportListResponse(BaseModel):
    framework_reports: list[FrameworkChangePropagationReport] = Field(default_factory=list)
    total_count: int = 0
