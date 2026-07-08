from typing import Optional

from pydantic import BaseModel


class ProjectState(BaseModel):
    project_id: str = "local_project"
    title: str = "未命名故事"
    language: str = "zh"
    phase: str = "phase_1"
    current_phase: str = "foundation"
    current_step: str = "project_initialized"
    status: str = "initialized"
    story_bible_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProjectStatusResponse(BaseModel):
    initialized: bool
    message: Optional[str] = None
    project: Optional[ProjectState] = None
