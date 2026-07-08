from pydantic import BaseModel, Field


class TracingStatus(BaseModel):
    enabled: bool = False
    provider: str = "langsmith"
    project: str = "multiple-agent-stories-phase8-5"
    api_key_configured: bool = False
    package_available: bool = False
    requested: bool = False
    endpoint: str = ""
    issues: list[str] = Field(default_factory=list)
