from typing import Any, Optional

from pydantic import BaseModel, Field, validator


BACKGROUND_THINKING_TASK_VERSION_ID = "phase4_m2_background_thinking_task_v1"
THINKING_CANDIDATE_VERSION_ID = "phase4_m2_thinking_candidate_v1"

BACKGROUND_THINKING_TASK_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
}
THINKING_CANDIDATE_STATUSES = {"ready", "stale", "rejected", "superseded"}
BACKGROUND_THINKING_TASK_TYPES = {
    "prepare_next_scene_thinking",
    "manual_scene_thinking",
}
BACKGROUND_THINKING_EXECUTION_MODES = {"sync_simulated"}
BACKGROUND_THINKING_EXECUTION_STRATEGIES = {
    "deterministic_fallback",
    "model_gateway",
}
BACKGROUND_THINKING_BUDGET_PROFILES = {
    "background_low",
    "background_standard",
    "background_high",
    "background_disabled",
}


class BackgroundThinkingTask(BaseModel):
    task_id: str
    project_id: str = "local_project"
    task_type: str = "prepare_next_scene_thinking"
    execution_mode: str = "sync_simulated"
    execution_strategy: str = "deterministic_fallback"
    status: str = "queued"
    source_scene_id: str = ""
    target_scene_id: str = ""
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    input_snapshot_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    safe_context_summary: dict[str, Any] = Field(default_factory=dict)
    safe_error: dict[str, Any] = Field(default_factory=dict)
    budget_profile: str = "background_standard"
    created_by: str = "user"
    created_at: str
    updated_at: str
    started_at: str = ""
    completed_at: str = ""
    version_id: str = BACKGROUND_THINKING_TASK_VERSION_ID

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "queued").strip()
        if status not in BACKGROUND_THINKING_TASK_STATUSES:
            raise ValueError("BackgroundThinkingTask.status is not supported.")
        return status

    @validator("task_type")
    def task_type_must_be_supported(cls, value: str) -> str:
        task_type = str(value or "prepare_next_scene_thinking").strip()
        if task_type not in BACKGROUND_THINKING_TASK_TYPES:
            raise ValueError("BackgroundThinkingTask.task_type is not supported.")
        return task_type

    @validator("execution_mode")
    def execution_mode_must_be_supported(cls, value: str) -> str:
        mode = str(value or "sync_simulated").strip()
        if mode not in BACKGROUND_THINKING_EXECUTION_MODES:
            raise ValueError("BackgroundThinkingTask.execution_mode is not supported.")
        return mode

    @validator("execution_strategy")
    def execution_strategy_must_be_supported(cls, value: str) -> str:
        strategy = str(value or "deterministic_fallback").strip()
        if strategy not in BACKGROUND_THINKING_EXECUTION_STRATEGIES:
            raise ValueError("BackgroundThinkingTask.execution_strategy is not supported.")
        return strategy

    @validator("budget_profile")
    def budget_profile_must_be_supported(cls, value: str) -> str:
        profile = str(value or "background_standard").strip()
        if profile not in BACKGROUND_THINKING_BUDGET_PROFILES:
            raise ValueError("BackgroundThinkingTask.budget_profile is not supported.")
        return profile


class ThinkingCandidate(BaseModel):
    candidate_id: str
    project_id: str = "local_project"
    task_id: str
    source_scene_id: str = ""
    target_scene_id: str = ""
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    based_on_snapshot_ids: list[str] = Field(default_factory=list)
    based_on_snapshot_hashes: dict[str, str] = Field(default_factory=dict)
    status: str = "ready"
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    risk_warnings: list[str] = Field(default_factory=list)
    story_information_preview: list[dict[str, Any]] = Field(default_factory=list)
    continuity_considerations: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    budget_profile: str = "background_standard"
    execution_strategy: str = "deterministic_fallback"
    created_at: str
    updated_at: str
    version_id: str = THINKING_CANDIDATE_VERSION_ID

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "ready").strip()
        if status not in THINKING_CANDIDATE_STATUSES:
            raise ValueError("ThinkingCandidate.status is not supported.")
        return status

    @validator("execution_strategy")
    def execution_strategy_must_be_supported(cls, value: str) -> str:
        strategy = str(value or "deterministic_fallback").strip()
        if strategy not in BACKGROUND_THINKING_EXECUTION_STRATEGIES:
            raise ValueError("ThinkingCandidate.execution_strategy is not supported.")
        return strategy

    @validator("budget_profile")
    def budget_profile_must_be_supported(cls, value: str) -> str:
        profile = str(value or "background_standard").strip()
        if profile not in BACKGROUND_THINKING_BUDGET_PROFILES:
            raise ValueError("ThinkingCandidate.budget_profile is not supported.")
        return profile


class BackgroundThinkingTaskCreateRequest(BaseModel):
    source_scene_id: str
    target_scene_id: str = ""
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    task_type: str = "prepare_next_scene_thinking"
    input_snapshot_ids: list[str] = Field(default_factory=list)
    execute_now: bool = True
    execution_strategy: str = "deterministic_fallback"
    budget_profile: str = "background_standard"


class BackgroundThinkingTaskExecuteRequest(BaseModel):
    execution_strategy: Optional[str] = None


class BackgroundThinkingTaskResponse(BaseModel):
    success: bool = True
    task: BackgroundThinkingTask
    candidate: Optional[ThinkingCandidate] = None


class BackgroundThinkingTaskListResponse(BaseModel):
    success: bool = True
    tasks: list[BackgroundThinkingTask] = Field(default_factory=list)
    count: int = 0


class ThinkingCandidateResponse(BaseModel):
    success: bool = True
    candidate: ThinkingCandidate


class ThinkingCandidateListResponse(BaseModel):
    success: bool = True
    candidates: list[ThinkingCandidate] = Field(default_factory=list)
    count: int = 0


class ThinkingTaskQueueSummaryResponse(BaseModel):
    success: bool = True
    project_id: str = "local_project"
    source_scene_id: str = ""
    task_count: int = 0
    queued_count: int = 0
    running_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    candidate_count: int = 0
    ready_candidate_count: int = 0
    stale_candidate_count: int = 0
    recent_task_ids: list[str] = Field(default_factory=list)
    recent_candidate_ids: list[str] = Field(default_factory=list)
    latest_safe_errors: list[dict[str, Any]] = Field(default_factory=list)
    storage_files: list[str] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)
