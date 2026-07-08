from typing import Optional

from pydantic import BaseModel, Field

from app.backend.models.chapter import Chapter
from app.backend.models.character import Character
from app.backend.models.decision import Decision
from app.backend.models.event import Event
from app.backend.models.framework import Framework
from app.backend.models.framework_package import FrameworkPackage
from app.backend.models.issue import Issue
from app.backend.models.memory_record import MemoryRecord
from app.backend.models.project import ProjectState
from app.backend.models.quality import QualityReport
from app.backend.models.relationship import Relationship
from app.backend.models.scene import Scene
from app.backend.models.state_change import StateChange
from app.backend.models.story_bible import StoryBible
from app.backend.models.world_canvas import WorldCanvas


class ProjectDataBundle(BaseModel):
    seed_ready: bool
    missing_files: list[str] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    active_project_id: Optional[str] = None
    active_project_selection_id: Optional[str] = None
    project_origin_type: str = ""
    story_data_scope: str = "local_project"
    setup_required: bool = False
    project: Optional[ProjectState] = None
    story_bible: Optional[StoryBible] = None
    world_canvas: Optional[WorldCanvas] = None
    characters: list[Character] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    framework: Optional[Framework] = None
    framework_package: Optional[FrameworkPackage] = None
    framework_package_ready: bool = False
    framework_package_validation_issues: list[str] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    state_changes: list[StateChange] = Field(default_factory=list)
    memory_records: list[MemoryRecord] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    quality_reports: list[QualityReport] = Field(default_factory=list)


class SeedDataResponse(BaseModel):
    seed_ready: bool
    created_files: list[str] = Field(default_factory=list)
    existing_files: list[str] = Field(default_factory=list)
    updated_files: list[str] = Field(default_factory=list)
    data: ProjectDataBundle
