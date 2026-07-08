from typing import Any, Literal

from pydantic import BaseModel, Field

from .formal_apply_eligibility import FormalApplyTargetType


FormalApplyPlanStatus = Literal["ready_for_m4_decision", "blocked", "failed_closed"]
FormalApplyWriteIntent = Literal[
    "none",
    "future_user_confirmed_merge",
    "future_proposal_creation",
    "future_governance_review",
]
FormalApplySafetyStatus = Literal["pass", "warn", "block"]


class FormalApplyPlan(BaseModel):
    plan_id: str
    project_id: str = "local_project"
    target_id: str
    eligibility_report_id: str
    target_type: FormalApplyTargetType
    source_lineage_id: str
    plan_status: FormalApplyPlanStatus
    allowed_next_step: str
    can_enter_m4_decision: bool = False
    requires_user_decision_before_apply: bool = True
    can_write_formal_record_now: bool = False
    creates_formal_record_now: bool = False
    writes_formal_story_fact_now: bool = False
    no_formal_write_performed: bool = True
    preview_record_only: bool = True
    block_reason_ids: list[str] = Field(default_factory=list)
    rollback_ref_preview: list[str] = Field(default_factory=list)
    before_fingerprints: dict[str, str] = Field(default_factory=dict)
    after_fingerprint_previews: dict[str, str] = Field(default_factory=dict)
    inverse_plan_hints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class FormalApplyPlanItem(BaseModel):
    item_id: str
    plan_id: str
    target_id: str
    item_type: str
    target_object_ref: str
    action_preview: str
    write_intent: FormalApplyWriteIntent = "none"
    no_write_guarantee: bool = True
    requires_m4_decision: bool = True
    blocked_by_reason_ids: list[str] = Field(default_factory=list)
    affected_object_refs: list[str] = Field(default_factory=list)
    rollback_hint: str
    safe_summary: str
    sort_order: int
    created_at: str


class FormalApplyDiffSummary(BaseModel):
    diff_summary_id: str
    plan_id: str
    target_id: str
    diff_kind: str
    before_refs: list[str] = Field(default_factory=list)
    after_preview_refs: list[str] = Field(default_factory=list)
    changed_fields_preview: list[str] = Field(default_factory=list)
    no_prose_diff: bool = True
    no_full_chapter_rewrite: bool = True
    no_formal_write_performed: bool = True
    safe_summary: str
    created_at: str


class FormalApplyImpactPreview(BaseModel):
    impact_preview_id: str
    plan_id: str
    target_id: str
    affected_domains: list[str] = Field(default_factory=list)
    affected_object_refs: list[str] = Field(default_factory=list)
    downstream_review_tasks: list[str] = Field(default_factory=list)
    formal_story_fact_write_attempted: bool = False
    event_memory_state_scene_write_attempted: bool = False
    active_framework_mutation_attempted: bool = False
    full_chapter_framework_prebuild_attempted: bool = False
    rollback_scope: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str


class FormalApplySafetyCheck(BaseModel):
    safety_check_id: str
    plan_id: str
    target_id: str
    safety_status: FormalApplySafetyStatus = "pass"
    check_items: list[dict[str, Any]] = Field(default_factory=list)
    block_reason_ids: list[str] = Field(default_factory=list)
    no_decision_created: bool = True
    no_proposal_created: bool = True
    no_apply_result_created: bool = True
    no_formal_record_created: bool = True
    no_active_framework_mutation: bool = True
    no_raw_prompt: bool = True
    no_raw_response: bool = True
    no_hidden_reasoning: bool = True
    no_secret_like_material: bool = True
    no_full_prose: bool = True
    safe_summary: str
    created_at: str


class FormalApplyDryRunPlanRequest(BaseModel):
    eligibility_report_id: str
    target_id: str | None = None
    project_id: str = "local_project"
    safe_note: str = ""


class FormalApplyDryRunResult(BaseModel):
    success: bool
    plan: FormalApplyPlan
    plan_items: list[FormalApplyPlanItem] = Field(default_factory=list)
    diff_summary: FormalApplyDiffSummary
    impact_preview: FormalApplyImpactPreview
    safety_check: FormalApplySafetyCheck


class FormalApplyDryRunStatusResponse(BaseModel):
    plan_count: int = 0
    plan_item_count: int = 0
    diff_summary_count: int = 0
    impact_preview_count: int = 0
    safety_check_count: int = 0
    latest_plan_id: str | None = None
    preview_record_only: bool = True
    no_formal_write_performed: bool = True
    m4_decision_required_before_write: bool = True
    allowed_storage_files: list[str] = Field(default_factory=list)
    safe_summary: str


class FormalApplyPlanListResponse(BaseModel):
    plans: list[FormalApplyPlan] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyPlanItemListResponse(BaseModel):
    plan_items: list[FormalApplyPlanItem] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyDiffSummaryListResponse(BaseModel):
    diff_summaries: list[FormalApplyDiffSummary] = Field(default_factory=list)
    total_count: int = 0


class FormalApplyImpactPreviewListResponse(BaseModel):
    impact_previews: list[FormalApplyImpactPreview] = Field(default_factory=list)
    total_count: int = 0


class FormalApplySafetyCheckListResponse(BaseModel):
    safety_checks: list[FormalApplySafetyCheck] = Field(default_factory=list)
    total_count: int = 0
