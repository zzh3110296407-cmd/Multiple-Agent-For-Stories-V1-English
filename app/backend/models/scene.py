from typing import Any, Optional

from pydantic import BaseModel, Field

from app.backend.models.scene_generation import (
    SceneDraftContent,
    SceneGenerationTrace,
    SceneMemoryExtraction,
    SceneQualityReport,
)
from app.backend.models.scene_revision import SceneRevisionCandidate


class Scene(BaseModel):
    scene_id: str
    project_id: str = "local_project"
    chapter_id: str
    scene_index: int
    goal: str = ""
    synopsis: str = ""
    prose_text: str = ""
    input_memory_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    state_change_ids: list[str] = Field(default_factory=list)
    status: str = "draft"
    prose_status: str = "not_generated"
    is_provisional: bool = False
    depends_on_provisional_scene_ids: list[str] = Field(default_factory=list)
    depends_on_provisional_memory_ids: list[str] = Field(default_factory=list)
    needs_review_reason: str = ""
    chapter_memory_pack_id: str = ""
    scene_memory_pack_id: str = ""
    character_context_ids: list[str] = Field(default_factory=list)
    narrative_intent_ids: list[str] = Field(default_factory=list)
    scene_goal: Optional[dict[str, Any]] = None
    time_label: str = ""
    location: str = ""
    generation_trace: SceneGenerationTrace = Field(
        default_factory=SceneGenerationTrace
    )
    content: Optional[SceneDraftContent] = None
    memory_extraction: SceneMemoryExtraction = Field(
        default_factory=SceneMemoryExtraction
    )
    quality_report: SceneQualityReport = Field(default_factory=SceneQualityReport)
    quality_report_id: str = ""
    linked_world_canvas_id: str = ""
    linked_character_ids: list[str] = Field(default_factory=list)
    linked_relationship_ids: list[str] = Field(default_factory=list)
    linked_framework_package_id: str = ""
    linked_chapter_framework_id: str = ""
    linked_framework_composition_id: str = ""
    source_refs: list[str] = Field(default_factory=list)
    revision_history: list[SceneRevisionCandidate] = Field(default_factory=list)
    active_revision_id: str = ""
    version_id: str = ""
    created_at: str = ""
    updated_at: str = ""
