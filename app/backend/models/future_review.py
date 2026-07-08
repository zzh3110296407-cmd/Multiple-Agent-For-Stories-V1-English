from typing import Any, Optional

from pydantic import BaseModel, Field, validator


FUTURE_ISSUE_VERSION_ID = "phase4_m5_future_issue_v1"
DELAYED_QUESTION_VERSION_ID = "phase4_m5_delayed_question_v1"
FUTURE_TODO_VERSION_ID = "phase4_m5_future_todo_v1"

FUTURE_ISSUE_TYPES = {
    "stale_cached_candidate",
    "cache_invalidation",
    "candidate_risk_warning",
    "manual_future_issue",
}
FUTURE_ISSUE_SOURCE_TYPES = {
    "cached_scene_candidate",
    "candidate_cache_invalidation",
    "thinking_candidate",
    "pre_modify_candidate",
    "manual",
}
FUTURE_REVIEW_SEVERITIES = {
    "low",
    "medium",
    "high",
    "requires_user_confirmation",
    "blocking_before_commit",
}
FUTURE_ISSUE_STATUSES = {
    "open",
    "question_created",
    "todo_created",
    "dismissed",
    "resolved_by_user_answer",
    "archived",
}
REVEAL_CONDITIONS = {
    "when_user_opens_scene",
    "before_scene_generation",
    "when_scene_enters_outputs",
    "before_scene_commit",
    "before_chapter_archive",
    "manual_review",
}
DELAYED_QUESTION_ACTION_TYPES = {
    "answer_question",
    "accept_as_open_ambiguity",
    "dismiss_as_not_needed",
    "defer_again",
    "convert_to_todo",
    "mark_as_claim",
    "mark_as_perception",
    "request_regeneration",
}
DELAYED_QUESTION_STATUSES = {
    "pending",
    "ready",
    "shown",
    "answered",
    "deferred",
    "dismissed",
    "converted_to_todo",
    "archived",
}
FUTURE_TODO_TYPES = {
    "review_later",
    "resolve_open_question",
    "consider_claim",
    "consider_perception",
    "regeneration_request",
    "manual_follow_up",
}
FUTURE_TODO_STATUSES = {"open", "done", "dismissed", "archived"}


class FutureIssue(BaseModel):
    future_issue_id: str
    project_id: str = "local_project"
    issue_type: str
    source_type: str
    source_id: str = ""
    target_chapter_id: str = ""
    target_scene_id: str = ""
    target_scene_index: Optional[int] = None
    reveal_condition: str
    severity: str
    status: str
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    user_visible_question_hint: str = ""
    related_cache_ids: list[str] = Field(default_factory=list)
    related_cached_candidate_ids: list[str] = Field(default_factory=list)
    related_invalidation_record_ids: list[str] = Field(default_factory=list)
    related_candidate_ids: list[str] = Field(default_factory=list)
    related_snapshot_ids: list[str] = Field(default_factory=list)
    related_memory_ids: list[str] = Field(default_factory=list)
    related_narrative_debt_ids: list[str] = Field(default_factory=list)
    related_continuity_issue_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str = FUTURE_ISSUE_VERSION_ID

    @validator("issue_type")
    def issue_type_must_be_supported(cls, value: str) -> str:
        issue_type = str(value or "").strip()
        if issue_type not in FUTURE_ISSUE_TYPES:
            raise ValueError("FutureIssue.issue_type is not supported.")
        return issue_type

    @validator("source_type")
    def source_type_must_be_supported(cls, value: str) -> str:
        source_type = str(value or "").strip()
        if source_type not in FUTURE_ISSUE_SOURCE_TYPES:
            raise ValueError("FutureIssue.source_type is not supported.")
        return source_type

    @validator("reveal_condition")
    def reveal_condition_must_be_supported(cls, value: str) -> str:
        condition = str(value or "when_user_opens_scene").strip()
        if condition not in REVEAL_CONDITIONS:
            raise ValueError("FutureIssue.reveal_condition is not supported.")
        return condition

    @validator("severity")
    def severity_must_be_supported(cls, value: str) -> str:
        severity = str(value or "medium").strip()
        if severity not in FUTURE_REVIEW_SEVERITIES:
            raise ValueError("FutureIssue.severity is not supported.")
        return severity

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "open").strip()
        if status not in FUTURE_ISSUE_STATUSES:
            raise ValueError("FutureIssue.status is not supported.")
        return status


class DelayedQuestionOption(BaseModel):
    option_id: str
    label: str
    action_type: str
    safe_effect: str = ""
    requires_text: bool = False
    creates_todo: bool = False

    @validator("action_type")
    def action_type_must_be_supported(cls, value: str) -> str:
        action_type = str(value or "").strip()
        if action_type not in DELAYED_QUESTION_ACTION_TYPES:
            raise ValueError("DelayedQuestionOption.action_type is not supported.")
        return action_type


class DelayedQuestion(BaseModel):
    delayed_question_id: str
    project_id: str = "local_project"
    future_issue_id: str
    target_chapter_id: str = ""
    target_scene_id: str = ""
    target_scene_index: Optional[int] = None
    reveal_condition: str
    question_text: str
    context_summary: dict[str, Any] = Field(default_factory=dict)
    options: list[DelayedQuestionOption] = Field(default_factory=list)
    status: str
    user_decision_id: str = ""
    selected_option_id: str = ""
    selected_action_type: str = ""
    answer_text: str = ""
    decision_summary: str = ""
    answered_at: str = ""
    deferred_until_reveal_condition: str = ""
    created_todo_id: str = ""
    created_at: str
    updated_at: str
    version_id: str = DELAYED_QUESTION_VERSION_ID

    @validator("reveal_condition")
    def reveal_condition_must_be_supported(cls, value: str) -> str:
        condition = str(value or "when_user_opens_scene").strip()
        if condition not in REVEAL_CONDITIONS:
            raise ValueError("DelayedQuestion.reveal_condition is not supported.")
        return condition

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "pending").strip()
        if status not in DELAYED_QUESTION_STATUSES:
            raise ValueError("DelayedQuestion.status is not supported.")
        return status


class FutureTodo(BaseModel):
    future_todo_id: str
    project_id: str = "local_project"
    future_issue_id: str = ""
    delayed_question_id: str = ""
    target_chapter_id: str = ""
    target_scene_id: str = ""
    target_scene_index: Optional[int] = None
    todo_type: str
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    source_answer_summary: str = ""
    status: str
    created_at: str
    updated_at: str
    version_id: str = FUTURE_TODO_VERSION_ID

    @validator("todo_type")
    def todo_type_must_be_supported(cls, value: str) -> str:
        todo_type = str(value or "review_later").strip()
        if todo_type not in FUTURE_TODO_TYPES:
            raise ValueError("FutureTodo.todo_type is not supported.")
        return todo_type

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "open").strip()
        if status not in FUTURE_TODO_STATUSES:
            raise ValueError("FutureTodo.status is not supported.")
        return status


class FutureIssueCreateRequest(BaseModel):
    issue_type: str = "manual_future_issue"
    source_type: str = "manual"
    source_id: str = ""
    target_chapter_id: str = ""
    target_scene_id: str = ""
    target_scene_index: Optional[int] = None
    reveal_condition: str = "manual_review"
    severity: str = "medium"
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    user_visible_question_hint: str = ""
    related_cache_ids: list[str] = Field(default_factory=list)
    related_cached_candidate_ids: list[str] = Field(default_factory=list)
    related_invalidation_record_ids: list[str] = Field(default_factory=list)
    related_candidate_ids: list[str] = Field(default_factory=list)
    related_snapshot_ids: list[str] = Field(default_factory=list)
    related_memory_ids: list[str] = Field(default_factory=list)
    related_narrative_debt_ids: list[str] = Field(default_factory=list)
    related_continuity_issue_ids: list[str] = Field(default_factory=list)


class FutureIssueFromCachedCandidateRequest(BaseModel):
    reveal_condition: str = "when_user_opens_scene"


class FutureIssueFromInvalidationRequest(BaseModel):
    reveal_condition: str = "when_user_opens_scene"


class FutureIssuesBackfillRequest(BaseModel):
    scene_id: str = ""
    chapter_id: str = ""
    include_stale: bool = True
    limit: int = 100


class DelayedQuestionCreateRequest(BaseModel):
    reveal_condition: str = ""
    question_text: str = ""
    context_summary: dict[str, Any] = Field(default_factory=dict)
    options: list[DelayedQuestionOption] = Field(default_factory=list)


class DelayedQuestionAnswerRequest(BaseModel):
    selected_option_id: str
    answer_text: str = ""
    decision_summary: str = ""
    deferred_until_reveal_condition: str = ""


class FutureIssueResponse(BaseModel):
    success: bool = True
    future_issue: FutureIssue
    safety: dict[str, Any] = Field(default_factory=dict)


class DelayedQuestionResponse(BaseModel):
    success: bool = True
    delayed_question: DelayedQuestion
    created_todo: Optional[FutureTodo] = None
    safety: dict[str, Any] = Field(default_factory=dict)


class FutureTodoResponse(BaseModel):
    success: bool = True
    future_todos: list[FutureTodo] = Field(default_factory=list)
    count: int = 0
    safety: dict[str, Any] = Field(default_factory=dict)


class DelayedQuestionReadyQueryResponse(BaseModel):
    success: bool = True
    scene_id: str = ""
    chapter_id: str = ""
    reveal_condition: str = ""
    delayed_questions: list[DelayedQuestion] = Field(default_factory=list)
    count: int = 0
    safety: dict[str, Any] = Field(default_factory=dict)


class FutureReviewSummaryResponse(BaseModel):
    success: bool = True
    project_id: str = "local_project"
    scene_id: str = ""
    chapter_id: str = ""
    future_issue_count: int = 0
    delayed_question_count: int = 0
    future_todo_count: int = 0
    issue_counts_by_status: dict[str, int] = Field(default_factory=dict)
    question_counts_by_status: dict[str, int] = Field(default_factory=dict)
    todo_counts_by_status: dict[str, int] = Field(default_factory=dict)
    recent_future_issue_ids: list[str] = Field(default_factory=list)
    recent_delayed_question_ids: list[str] = Field(default_factory=list)
    recent_future_todo_ids: list[str] = Field(default_factory=list)
    future_issues: list[FutureIssue] = Field(default_factory=list)
    delayed_questions: list[DelayedQuestion] = Field(default_factory=list)
    future_todos: list[FutureTodo] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)
