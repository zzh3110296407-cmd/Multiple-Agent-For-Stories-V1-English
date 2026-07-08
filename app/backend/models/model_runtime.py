from typing import Optional

from pydantic import BaseModel, Field

from app.backend.models.tracing import TracingStatus


MODEL_RUNTIME_SCHEMA_VERSION = "phase2_m1_v1"


class TokenUsage(BaseModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class ModelCallRecord(BaseModel):
    call_id: str
    project_id: str = "local_project"
    agent_role: str = "all"
    service_name: str = "ModelGatewayService"
    operation_name: str = ""
    provider_id: str = ""
    provider_type: str = ""
    model_profile_id: str = ""
    model_name: str = ""
    request_type: str = ""
    started_at: str = ""
    ended_at: str = ""
    latency_ms: int = 0
    success: bool = False
    adapter_success: bool = False
    json_parse_success: Optional[bool] = None
    error_type: Optional[str] = None
    error_message_safe: Optional[str] = None
    retryable: bool = False
    local_trace_id: Optional[str] = None
    local_trace_link: Optional[str] = None
    token_usage: Optional[TokenUsage] = Field(default_factory=TokenUsage)
    created_at: str = ""
    version_id: str = MODEL_RUNTIME_SCHEMA_VERSION


class ProviderHealth(BaseModel):
    provider_id: str = ""
    provider_type: str = ""
    model_name: str = ""
    status: str = "unknown"
    configured: bool = False
    api_key_ref_present: bool = False
    api_key_value_present_in_env: bool = False
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_latency_ms: int = 0
    recent_success_count: int = 0
    recent_failure_count: int = 0
    recent_json_parse_failure_count: int = 0
    last_error_type: Optional[str] = None
    last_error_message_safe: Optional[str] = None
    updated_at: str = ""


class RuntimeErrorRecord(BaseModel):
    error_id: str
    call_id: str = ""
    project_id: str = "local_project"
    stage: str = "unknown"
    error_type: str = "unknown_model_error"
    error_message_safe: str = ""
    retryable: bool = False
    provider_type: str = ""
    model_name: str = ""
    service_name: str = ""
    suggested_action: str = ""
    user_visible_message: str = ""
    created_at: str = ""


class ModelRuntimeLogsMetadata(BaseModel):
    schema_version: str = MODEL_RUNTIME_SCHEMA_VERSION
    updated_at: str = ""


class ModelRuntimeLogs(BaseModel):
    model_call_records: list[ModelCallRecord] = Field(default_factory=list)
    provider_health: list[ProviderHealth] = Field(default_factory=list)
    runtime_errors: list[RuntimeErrorRecord] = Field(default_factory=list)
    metadata: ModelRuntimeLogsMetadata = Field(default_factory=ModelRuntimeLogsMetadata)


class RecentModelCallSummary(BaseModel):
    call_id: str
    request_type: str = ""
    provider_type: str = ""
    model_name: str = ""
    success: bool = False
    latency_ms: int = 0
    error_type: Optional[str] = None
    error_message_safe: Optional[str] = None
    started_at: str = ""
    ended_at: str = ""


class ModelRuntimeStatusResponse(BaseModel):
    provider_health: list[ProviderHealth] = Field(default_factory=list)
    recent_calls: list[RecentModelCallSummary] = Field(default_factory=list)
    recent_success_count: int = 0
    recent_failure_count: int = 0
    recent_json_parse_failure_count: int = 0
    tracing: TracingStatus = Field(default_factory=TracingStatus)
    updated_at: str = ""


class ModelRuntimeCallsResponse(BaseModel):
    calls: list[ModelCallRecord] = Field(default_factory=list)


class ModelRuntimeErrorsResponse(BaseModel):
    errors: list[RuntimeErrorRecord] = Field(default_factory=list)


class ModelRuntimeHealthCheckResponse(BaseModel):
    ok: bool = False
    status: str = "unknown"
    message: str = ""
    call_id: Optional[str] = None
    latency_ms: int = 0
    provider_health: Optional[ProviderHealth] = None
    data: dict[str, str] = Field(default_factory=dict)
