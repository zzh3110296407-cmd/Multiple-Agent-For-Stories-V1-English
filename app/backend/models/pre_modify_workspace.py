from typing import Any, Optional

from pydantic import BaseModel, Field, validator


PRE_MODIFY_WORKSPACE_VERSION_ID = "phase4_m7_pre_modify_workspace_v1"

PRE_MODIFY_APPLY_STATES = {
    "not_started",
    "plan_ready",
    "accepted_for_formal_flow",
    "rejected",
    "revision_requested",
    "deferred",
    "blocked",
}
PRE_MODIFY_PLAN_ITEM_TYPES = {
    "review_adjustment_plan",
    "review_impact_reason",
    "answer_delayed_question",
    "prepare_formal_flow_handoff",
    "preserve_source_evidence",
    "defer_future_review",
    "hide_cached_candidate",
    "archive_cached_candidate",
    "manual_review",
}
PRE_MODIFY_PLAN_ITEM_STATUSES = {"planned", "blocked", "completed", "skipped"}
PRE_MODIFY_APPLY_PLAN_STATUSES = {
    "draft",
    "ready",
    "blocked",
    "accepted",
    "rejected",
    "deferred",
    "superseded",
}
PRE_MODIFY_APPLY_MODES = {"formal_flow_handoff", "review_only", "defer_only"}
PRE_MODIFY_USER_ACTION_TYPES = {"accept", "reject", "revise", "defer"}
PRE_MODIFY_USER_ACTION_STATUSES = {"completed", "blocked", "recorded"}
PRE_MODIFY_REVISION_REQUEST_STATUSES = {
    "recorded",
    "blocked",
    "superseded",
    "completed",
}
PRE_MODIFY_REJECT_CACHE_ACTIONS = {"none", "hide", "archive"}


class PreModifyWorkspaceCandidateView(BaseModel):
    candidate_id: str
    cached_candidate_id: str = ""
    source_candidate_type: str = ""
    target_scene_id: str = ""
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    source_status: str = ""
    cache_status: str = ""
    apply_state: str = "not_started"
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    preview_label: str = ""
    user_visible_reason: str = ""
    adjustment_summary: str = ""
    adjustment_plan_id: str = ""
    impact_reason_id: str = ""
    risk_warnings: list[str] = Field(default_factory=list)
    snapshot_ids: list[str] = Field(default_factory=list)
    stale_reason_refs: list[dict[str, Any]] = Field(default_factory=list)
    blocking_delayed_question_ids: list[str] = Field(default_factory=list)
    warning_delayed_question_ids: list[str] = Field(default_factory=list)
    latest_action_id: str = ""
    latest_action_type: str = ""
    can_accept: bool
    can_reject: bool
    can_revise: bool
    can_defer: bool
    blocked_reasons: list[str] = Field(default_factory=list)
    version_id: str = PRE_MODIFY_WORKSPACE_VERSION_ID

    @validator("apply_state")
    def apply_state_must_be_supported(cls, value: str) -> str:
        state = str(value or "not_started").strip()
        if state not in PRE_MODIFY_APPLY_STATES:
            raise ValueError("PreModifyWorkspaceCandidateView.apply_state is not supported.")
        return state


class PreModifyWorkspaceState(BaseModel):
    success: bool = True
    project_id: str = "local_project"
    scene_id: str = ""
    chapter_id: str = ""
    target_scene_index: Optional[int] = None
    candidates: list[PreModifyWorkspaceCandidateView] = Field(default_factory=list)
    ready_delayed_questions: list[dict[str, Any]] = Field(default_factory=list)
    future_issue_count: int = 0
    future_todo_count: int = 0
    candidate_count: int = 0
    action_count: int = 0
    latest_action_ids: list[str] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)
    version_id: str = PRE_MODIFY_WORKSPACE_VERSION_ID


class CandidateApplyPlanItem(BaseModel):
    item_id: str
    item_type: str
    target_type: str = ""
    target_id: str = ""
    safe_summary: str
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    required_before_accept: bool = False
    requires_user_confirmation: bool = True
    creates_formal_fact: bool = False
    status: str = "planned"

    @validator("item_type")
    def item_type_must_be_supported(cls, value: str) -> str:
        item_type = str(value or "").strip()
        if item_type not in PRE_MODIFY_PLAN_ITEM_TYPES:
            raise ValueError("CandidateApplyPlanItem.item_type is not supported.")
        return item_type

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "planned").strip()
        if status not in PRE_MODIFY_PLAN_ITEM_STATUSES:
            raise ValueError("CandidateApplyPlanItem.status is not supported.")
        return status


class CandidateApplyPlan(BaseModel):
    apply_plan_id: str
    project_id: str = "local_project"
    candidate_id: str
    cached_candidate_id: str = ""
    source_candidate_type: str = ""
    target_scene_id: str = ""
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    plan_status: str = "draft"
    apply_mode: str = "formal_flow_handoff"
    source_status: str = ""
    cache_status: str = ""
    adjustment_plan_id: str = ""
    impact_reason_id: str = ""
    snapshot_ids: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    warning_reasons: list[str] = Field(default_factory=list)
    blocking_delayed_question_ids: list[str] = Field(default_factory=list)
    warning_delayed_question_ids: list[str] = Field(default_factory=list)
    items: list[CandidateApplyPlanItem] = Field(default_factory=list)
    no_formal_story_write: bool = True
    created_by_action_id: str = ""
    created_at: str
    updated_at: str
    version_id: str = PRE_MODIFY_WORKSPACE_VERSION_ID

    @validator("plan_status")
    def plan_status_must_be_supported(cls, value: str) -> str:
        status = str(value or "draft").strip()
        if status not in PRE_MODIFY_APPLY_PLAN_STATUSES:
            raise ValueError("CandidateApplyPlan.plan_status is not supported.")
        return status

    @validator("apply_mode")
    def apply_mode_must_be_supported(cls, value: str) -> str:
        mode = str(value or "formal_flow_handoff").strip()
        if mode not in PRE_MODIFY_APPLY_MODES:
            raise ValueError("CandidateApplyPlan.apply_mode is not supported.")
        return mode


class PreModifyUserAction(BaseModel):
    user_action_id: str
    project_id: str = "local_project"
    action_type: str
    action_status: str
    candidate_id: str
    cached_candidate_id: str = ""
    apply_plan_id: str = ""
    revision_request_id: str = ""
    future_issue_id: str = ""
    delayed_question_id: str = ""
    future_todo_id: str = ""
    decision_id: str = ""
    target_scene_id: str = ""
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    safe_user_note: str = ""
    safe_action_summary: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)
    no_formal_story_write: bool = True
    created_at: str
    version_id: str = PRE_MODIFY_WORKSPACE_VERSION_ID

    @validator("action_type")
    def action_type_must_be_supported(cls, value: str) -> str:
        action_type = str(value or "").strip()
        if action_type not in PRE_MODIFY_USER_ACTION_TYPES:
            raise ValueError("PreModifyUserAction.action_type is not supported.")
        return action_type

    @validator("action_status")
    def action_status_must_be_supported(cls, value: str) -> str:
        status = str(value or "").strip()
        if status not in PRE_MODIFY_USER_ACTION_STATUSES:
            raise ValueError("PreModifyUserAction.action_status is not supported.")
        return status


class CandidateRevisionRequest(BaseModel):
    revision_request_id: str
    project_id: str = "local_project"
    source_candidate_id: str
    source_cached_candidate_id: str = ""
    parent_user_action_id: str = ""
    target_scene_id: str = ""
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    safe_revision_note: str
    requested_change_summary: str = ""
    status: str = "recorded"
    child_candidate_id: str = ""
    created_at: str
    updated_at: str
    version_id: str = PRE_MODIFY_WORKSPACE_VERSION_ID

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "recorded").strip()
        if status not in PRE_MODIFY_REVISION_REQUEST_STATUSES:
            raise ValueError("CandidateRevisionRequest.status is not supported.")
        return status


class CandidateApplyResult(BaseModel):
    success: bool = True
    action: Optional[PreModifyUserAction] = None
    apply_plan: Optional[CandidateApplyPlan] = None
    revision_request: Optional[CandidateRevisionRequest] = None
    created_future_issue_id: str = ""
    created_delayed_question_id: str = ""
    created_future_todo_id: str = ""
    no_formal_story_write: bool = True
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)


class CandidateApplyPlanRequest(BaseModel):
    cached_candidate_id: str = ""
    force_refresh: bool = False

    class Config:
        extra = "forbid"


class CandidateAcceptRequest(BaseModel):
    cached_candidate_id: str = ""
    apply_plan_id: str = ""
    safe_user_note: str = ""
    archive_after_accept: bool = False

    class Config:
        extra = "forbid"


class CandidateRejectRequest(BaseModel):
    cached_candidate_id: str = ""
    safe_user_note: str = ""
    cache_action: str = "hide"

    @validator("cache_action")
    def cache_action_must_be_supported(cls, value: str) -> str:
        action = str(value or "hide").strip()
        if action not in PRE_MODIFY_REJECT_CACHE_ACTIONS:
            raise ValueError("CandidateRejectRequest.cache_action is not supported.")
        return action

    class Config:
        extra = "forbid"


class CandidateReviseRequest(BaseModel):
    cached_candidate_id: str = ""
    safe_revision_note: str
    requested_change_summary: str = ""

    class Config:
        extra = "forbid"


class CandidateDeferRequest(BaseModel):
    cached_candidate_id: str = ""
    safe_user_note: str = ""
    reveal_condition: str = "when_user_opens_scene"
    create_delayed_question: bool = True
    question_text: str = ""
    create_future_todo: bool = False

    class Config:
        extra = "forbid"
