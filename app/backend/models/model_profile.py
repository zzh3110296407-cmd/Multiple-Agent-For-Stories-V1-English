from pydantic import BaseModel, Field


class ModelCapabilities(BaseModel):
    chat: bool = True
    json_output: bool = True
    tool_calling: bool = False
    streaming: bool = False
    long_context: bool = False
    vision: bool = False
    embedding: bool = False


class ModelProfile(BaseModel):
    model_profile_id: str
    provider_id: str
    model_name: str
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    context_window_hint: int = 0
    cost_tier: str = "unknown"
    quality_tier: str = "unknown"
    status: str = "active"
