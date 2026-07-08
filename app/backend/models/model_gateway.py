from typing import Any, Optional

from pydantic import BaseModel, Field


class ModelGatewayMessage(BaseModel):
    role: str
    content: str


class ModelGatewayOptions(BaseModel):
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    timeout_seconds: Optional[int] = None
    max_attempts: Optional[int] = None


class ModelGatewayRequest(BaseModel):
    messages: list[ModelGatewayMessage] = Field(default_factory=list)
    model_name: str
    temperature: float = 0.7
    max_output_tokens: int = 2000
    timeout_seconds: Optional[int] = None
    max_attempts: Optional[int] = None
    response_format: str = "text"
    schema_hint: Optional[dict[str, Any]] = None


class ModelGatewayTextResult(BaseModel):
    text: str
    provider_id: str
    model_name: str
    call_id: str = ""
    latency_ms: int = 0


class ModelGatewayJsonResult(BaseModel):
    data: dict[str, Any]
    raw_text: str
    provider_id: str
    model_name: str
    call_id: str = ""
    latency_ms: int = 0


class ModelGatewayStatusResponse(BaseModel):
    configured: bool
    provider_type: Optional[str] = None
    model_name: Optional[str] = None
    api_key_ref: str = ""
    active_assignment: Optional[str] = None
    issues: list[str] = Field(default_factory=list)


class ModelGatewaySeedResponse(BaseModel):
    ready: bool
    created_files: list[str] = Field(default_factory=list)
    existing_files: list[str] = Field(default_factory=list)
    updated_files: list[str] = Field(default_factory=list)
    status: ModelGatewayStatusResponse
