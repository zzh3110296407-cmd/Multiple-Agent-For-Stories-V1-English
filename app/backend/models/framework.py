from pydantic import BaseModel, Field


class FrameworkNode(BaseModel):
    node_id: str
    name: str
    description: str = ""
    position: int = 0


class Framework(BaseModel):
    framework_id: str
    project_id: str = "local_project"
    name: str
    constraint_strength: str
    maturity: str
    source: str = "system_default"
    framework_package_id: str | None = None
    module_ids: list[str] = Field(default_factory=list)
    stage_ids: list[str] = Field(default_factory=list)
    beat_ids: list[str] = Field(default_factory=list)
    nodes: list[FrameworkNode] = Field(default_factory=list)
