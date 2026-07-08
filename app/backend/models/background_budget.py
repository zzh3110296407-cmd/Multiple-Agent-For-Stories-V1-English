from typing import Any, Optional

from pydantic import BaseModel, Field, validator


BACKGROUND_BUDGET_SCHEMA_VERSION = "phase4_m6_background_budget_v1"

EXECUTION_STRATEGIES = {
    "deterministic_fallback",
    "model_gateway",
    "no_model",
    "blocked",
}
SAFE_FAILURE_MODES = {"fallback", "block_task", "record_only"}
POLICY_STATUSES = {"active", "disabled"}
USAGE_STATUSES = {"completed", "failed", "blocked", "recorded"}
TASK_TYPES = {
    "foreground_scene_generation",
    "foreground_scene_revision",
    "background_thinking",
    "pre_modify_candidate",
    "candidate_cache_visibility",
    "future_issue_extraction",
    "delayed_question_generation",
    "chapter_framework_build",
    "modification_impact_preview",
}
M6_NO_MODEL_POLICY_TYPES = {
    "pre_modify_candidate",
    "future_issue_extraction",
    "delayed_question_generation",
}


class _StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"


class BackgroundBudgetProfile(BaseModel):
    profile_id: str
    project_id: str = "local_project"
    label: str = ""
    description: str = ""
    enabled: bool = True
    allow_task_execution: bool = True
    allow_model_gateway: bool = False
    allowed_execution_strategies: list[str] = Field(default_factory=list)
    default_execution_strategy: str
    selected_model_role: str = ""
    max_model_calls_per_task: int = 0
    max_retry_count: int = 0
    max_output_tokens: int = 0
    temperature: float = 0.0
    fallback_execution_strategy: str = "deterministic_fallback"
    compatibility_alias_for: str = ""
    updated_at: str
    version_id: str = BACKGROUND_BUDGET_SCHEMA_VERSION

    @validator("allowed_execution_strategies")
    def allowed_strategies_must_be_supported(cls, value: list[str]) -> list[str]:
        clean = []
        for item in value or []:
            strategy = str(item or "").strip()
            if strategy not in EXECUTION_STRATEGIES:
                raise ValueError("BackgroundBudgetProfile.allowed_execution_strategies is not supported.")
            if strategy not in clean:
                clean.append(strategy)
        if not clean:
            raise ValueError("BackgroundBudgetProfile.allowed_execution_strategies cannot be empty.")
        return clean

    @validator("default_execution_strategy", "fallback_execution_strategy")
    def strategy_must_be_supported(cls, value: str) -> str:
        strategy = str(value or "").strip()
        if strategy not in EXECUTION_STRATEGIES:
            raise ValueError("BackgroundBudgetProfile execution strategy is not supported.")
        return strategy

    @validator("max_model_calls_per_task")
    def model_call_count_must_be_bounded(cls, value: int) -> int:
        if int(value) < 0 or int(value) > 3:
            raise ValueError("max_model_calls_per_task must be between 0 and 3.")
        return int(value)

    @validator("max_retry_count")
    def retry_count_must_be_bounded(cls, value: int) -> int:
        if int(value) < 0 or int(value) > 2:
            raise ValueError("max_retry_count must be between 0 and 2.")
        return int(value)

    @validator("max_output_tokens")
    def output_tokens_must_be_bounded(cls, value: int) -> int:
        if int(value) < 0 or int(value) > 12000:
            raise ValueError("max_output_tokens must be between 0 and 12000.")
        return int(value)

    @validator("temperature")
    def temperature_must_be_bounded(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0 or numeric > 2:
            raise ValueError("temperature must be between 0 and 2.")
        return numeric

    @validator("version_id")
    def version_must_match(cls, value: str) -> str:
        return value or BACKGROUND_BUDGET_SCHEMA_VERSION


class TaskModelPolicy(BaseModel):
    policy_id: str
    project_id: str = "local_project"
    task_type: str
    default_profile_id: str
    allowed_profile_ids: list[str] = Field(default_factory=list)
    allow_model_gateway: bool = False
    require_snapshot_refs: bool = False
    safe_failure_mode: str = "fallback"
    fallback_profile_id: str = ""
    fallback_execution_strategy: str = "deterministic_fallback"
    status: str = "active"
    updated_at: str
    version_id: str = BACKGROUND_BUDGET_SCHEMA_VERSION

    @validator("task_type")
    def task_type_must_be_supported(cls, value: str) -> str:
        task_type = str(value or "").strip()
        if task_type not in TASK_TYPES:
            raise ValueError("TaskModelPolicy.task_type is not supported.")
        return task_type

    @validator("safe_failure_mode")
    def failure_mode_must_be_supported(cls, value: str) -> str:
        mode = str(value or "fallback").strip()
        if mode not in SAFE_FAILURE_MODES:
            raise ValueError("TaskModelPolicy.safe_failure_mode is not supported.")
        return mode

    @validator("fallback_execution_strategy")
    def fallback_strategy_must_be_supported(cls, value: str) -> str:
        strategy = str(value or "deterministic_fallback").strip()
        if strategy not in EXECUTION_STRATEGIES:
            raise ValueError("TaskModelPolicy.fallback_execution_strategy is not supported.")
        return strategy

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "active").strip()
        if status not in POLICY_STATUSES:
            raise ValueError("TaskModelPolicy.status is not supported.")
        return status


class TaskBudgetDecision(BaseModel):
    allowed: bool
    task_type: str
    task_id: str = ""
    policy_id: str
    profile_id: str
    requested_execution_strategy: str = ""
    selected_execution_strategy: str
    selected_model_role: str = ""
    model_gateway_allowed: bool = False
    max_model_calls_per_task: int = 0
    max_retry_count: int = 0
    max_output_tokens: int = 0
    temperature: float = 0.0
    fallback_execution_strategy: str = ""
    decision_reason: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = BACKGROUND_BUDGET_SCHEMA_VERSION


class TaskBudgetUsageRecord(BaseModel):
    usage_record_id: str
    project_id: str = "local_project"
    task_type: str
    task_id: str = ""
    source_object_type: str = ""
    source_object_id: str = ""
    policy_id: str = ""
    profile_id: str = ""
    requested_execution_strategy: str = ""
    selected_execution_strategy: str = ""
    model_gateway_allowed: bool = False
    model_call_ids: list[str] = Field(default_factory=list)
    model_call_count: int = 0
    model_success_count: int = 0
    model_failure_count: int = 0
    provider_types: list[str] = Field(default_factory=list)
    model_names: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    deterministic_used: bool = False
    blocked: bool = False
    status: str
    safe_error: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    version_id: str = BACKGROUND_BUDGET_SCHEMA_VERSION

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "recorded").strip()
        if status not in USAGE_STATUSES:
            raise ValueError("TaskBudgetUsageRecord.status is not supported.")
        return status


class ModelRoutingDecisionRecord(BaseModel):
    routing_decision_id: str
    project_id: str = "local_project"
    task_type: str
    task_id: str = ""
    policy_id: str = ""
    profile_id: str = ""
    requested_execution_strategy: str = ""
    selected_execution_strategy: str = ""
    selected_model_role: str = ""
    model_gateway_allowed: bool = False
    allowed: bool = False
    decision_reason: str = ""
    fallback_reason: str = ""
    created_at: str
    version_id: str = BACKGROUND_BUDGET_SCHEMA_VERSION


class BackgroundBudgetStatusResponse(BaseModel):
    success: bool = True
    project_id: str = "local_project"
    profile_count: int = 0
    policy_count: int = 0
    enabled_profile_ids: list[str] = Field(default_factory=list)
    active_background_profile_ids: list[str] = Field(default_factory=list)
    recent_usage_records: list[TaskBudgetUsageRecord] = Field(default_factory=list)
    recent_routing_decisions: list[ModelRoutingDecisionRecord] = Field(default_factory=list)
    model_runtime_status: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    version_id: str = BACKGROUND_BUDGET_SCHEMA_VERSION


class BackgroundBudgetProfileListResponse(BaseModel):
    success: bool = True
    profiles: list[BackgroundBudgetProfile] = Field(default_factory=list)
    count: int = 0
    safety: dict[str, Any] = Field(default_factory=dict)


class TaskModelPolicyListResponse(BaseModel):
    success: bool = True
    policies: list[TaskModelPolicy] = Field(default_factory=list)
    count: int = 0
    safety: dict[str, Any] = Field(default_factory=dict)


class TaskBudgetUsageListResponse(BaseModel):
    success: bool = True
    usage_records: list[TaskBudgetUsageRecord] = Field(default_factory=list)
    routing_decisions: list[ModelRoutingDecisionRecord] = Field(default_factory=list)
    count: int = 0
    safety: dict[str, Any] = Field(default_factory=dict)


class TaskBudgetEvaluateRequest(_StrictBaseModel):
    task_type: str
    task_id: str = ""
    requested_profile_id: str = ""
    requested_execution_strategy: str = ""
    snapshot_ids: list[str] = Field(default_factory=list)
    source_object_type: str = ""
    source_object_id: str = ""


class TaskBudgetEvaluateResponse(BaseModel):
    success: bool = True
    decision: TaskBudgetDecision
    routing_decision: ModelRoutingDecisionRecord
    safety: dict[str, Any] = Field(default_factory=dict)


class BackgroundBudgetProfilePatchRequest(_StrictBaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    allow_task_execution: Optional[bool] = None
    allow_model_gateway: Optional[bool] = None
    allowed_execution_strategies: Optional[list[str]] = None
    default_execution_strategy: Optional[str] = None
    selected_model_role: Optional[str] = None
    max_model_calls_per_task: Optional[int] = None
    max_retry_count: Optional[int] = None
    max_output_tokens: Optional[int] = None
    temperature: Optional[float] = None
    fallback_execution_strategy: Optional[str] = None
    compatibility_alias_for: Optional[str] = None


class TaskModelPolicyPatchRequest(_StrictBaseModel):
    default_profile_id: Optional[str] = None
    allowed_profile_ids: Optional[list[str]] = None
    allow_model_gateway: Optional[bool] = None
    require_snapshot_refs: Optional[bool] = None
    safe_failure_mode: Optional[str] = None
    fallback_profile_id: Optional[str] = None
    fallback_execution_strategy: Optional[str] = None
    status: Optional[str] = None
