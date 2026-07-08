from typing import Any, Optional

from pydantic import BaseModel, Field, validator


PRE_MODIFY_CANDIDATE_VERSION_ID = "phase4_m3_pre_modify_candidate_v1"
PRE_MODIFY_ADJUSTMENT_PLAN_VERSION_ID = "phase4_m3_pre_modify_adjustment_plan_v1"
PRE_MODIFY_IMPACT_REASON_VERSION_ID = "phase4_m3_pre_modify_impact_reason_v1"
PRE_MODIFY_PIPELINE_RESULT_VERSION_ID = "phase4_m3_pre_modify_pipeline_result_v1"

PRE_MODIFY_CANDIDATE_STATUSES = {
    "ready",
    "blocked",
    "stale",
    "superseded",
    "warning_only",
}
PRE_MODIFY_PLAN_STATUSES = {"proposed", "blocked", "stale"}
PRE_MODIFY_ADJUSTMENT_ITEM_TYPES = {
    "scene_focus",
    "continuity_alignment",
    "memory_alignment",
    "information_release",
    "risk_warning",
    "review_note",
}
PRE_MODIFY_PRIORITIES = {"low", "medium", "high"}
PRE_MODIFY_EXECUTION_STRATEGIES = {"deterministic_fallback"}


class PreModifyCandidate(BaseModel):
    candidate_id: str
    project_id: str = "local_project"
    source_preview_id: str
    source_invalidation_id: str = ""
    source_object_type: str = ""
    source_object_id: str = ""
    source_modification_hash: str = ""
    target_scene_id: str
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    target_scene_status: str = ""
    target_snapshot_ids: list[str] = Field(default_factory=list)
    affected_snapshot_ids: list[str] = Field(default_factory=list)
    thinking_candidate_ids: list[str] = Field(default_factory=list)
    adjustment_plan_id: str = ""
    impact_reason_id: str = ""
    status: str = "ready"
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    user_visible_reason: str = ""
    adjustment_summary: str = ""
    source_affected_refs: list[dict[str, Any]] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str = PRE_MODIFY_CANDIDATE_VERSION_ID

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "ready").strip()
        if status not in PRE_MODIFY_CANDIDATE_STATUSES:
            raise ValueError("PreModifyCandidate.status is not supported.")
        return status


class PreModifyAdjustmentItem(BaseModel):
    item_id: str
    item_type: str
    priority: str = "medium"
    target_field: str = ""
    proposed_change_summary: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_snapshot_ids: list[str] = Field(default_factory=list)
    thinking_candidate_ids: list[str] = Field(default_factory=list)

    @validator("item_type")
    def item_type_must_be_supported(cls, value: str) -> str:
        item_type = str(value or "").strip()
        if item_type not in PRE_MODIFY_ADJUSTMENT_ITEM_TYPES:
            raise ValueError("PreModifyAdjustmentItem.item_type is not supported.")
        return item_type

    @validator("priority")
    def priority_must_be_supported(cls, value: str) -> str:
        priority = str(value or "medium").strip()
        return priority if priority in PRE_MODIFY_PRIORITIES else "medium"


class PreModifyAdjustmentPlan(BaseModel):
    plan_id: str
    project_id: str = "local_project"
    candidate_id: str
    source_preview_id: str
    target_scene_id: str
    status: str = "proposed"
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    items: list[PreModifyAdjustmentItem] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str = PRE_MODIFY_ADJUSTMENT_PLAN_VERSION_ID

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "proposed").strip()
        if status not in PRE_MODIFY_PLAN_STATUSES:
            raise ValueError("PreModifyAdjustmentPlan.status is not supported.")
        return status


class PreModifyImpactReason(BaseModel):
    reason_id: str
    project_id: str = "local_project"
    candidate_id: str
    source_preview_id: str
    target_scene_id: str
    impact_level: str = "medium"
    relation: str = ""
    user_visible_reason: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    affected_snapshot_ids: list[str] = Field(default_factory=list)
    thinking_candidate_ids: list[str] = Field(default_factory=list)
    created_at: str
    version_id: str = PRE_MODIFY_IMPACT_REASON_VERSION_ID

    @validator("impact_level")
    def impact_level_must_be_supported(cls, value: str) -> str:
        impact_level = str(value or "medium").strip()
        return impact_level if impact_level in PRE_MODIFY_PRIORITIES else "medium"


class PreModifyFromPreviewRequest(BaseModel):
    preview_id: str
    target_scene_ids: list[str] = Field(default_factory=list)
    include_current_scene: bool = False
    include_confirmed_targets: bool = True
    execution_strategy: str = "deterministic_fallback"


class PreModifyCandidateResponse(BaseModel):
    success: bool = True
    candidate: PreModifyCandidate


class PreModifyCandidateListResponse(BaseModel):
    success: bool = True
    candidates: list[PreModifyCandidate] = Field(default_factory=list)
    count: int = 0


class PreModifyAdjustmentPlanResponse(BaseModel):
    success: bool = True
    plan: PreModifyAdjustmentPlan


class PreModifyImpactReasonResponse(BaseModel):
    success: bool = True
    reason: PreModifyImpactReason


class PreModifyPipelineResult(BaseModel):
    success: bool = True
    source_preview_id: str = ""
    created_candidate_ids: list[str] = Field(default_factory=list)
    created_plan_ids: list[str] = Field(default_factory=list)
    created_reason_ids: list[str] = Field(default_factory=list)
    skipped_target_scene_ids: list[str] = Field(default_factory=list)
    no_candidate_reason: str = ""
    warnings: list[str] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)
    version_id: str = PRE_MODIFY_PIPELINE_RESULT_VERSION_ID


class PreModifySummaryResponse(BaseModel):
    success: bool = True
    project_id: str = "local_project"
    source_preview_id: str = ""
    target_scene_id: str = ""
    candidate_count: int = 0
    ready_count: int = 0
    blocked_count: int = 0
    stale_count: int = 0
    superseded_count: int = 0
    warning_only_count: int = 0
    plan_count: int = 0
    reason_count: int = 0
    recent_candidate_ids: list[str] = Field(default_factory=list)
    recent_source_preview_ids: list[str] = Field(default_factory=list)
    recent_target_scene_ids: list[str] = Field(default_factory=list)
    latest_warnings: list[str] = Field(default_factory=list)
    recent_candidates: list[dict[str, Any]] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)
