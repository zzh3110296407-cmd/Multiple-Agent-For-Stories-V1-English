from typing import Any

from pydantic import BaseModel, Field


PHASE2_DEBUG_VERSION_ID = "phase2_m8_web_debug_panels_v1"


class Phase2DebugResponse(BaseModel):
    success: bool = True
    generated_at: str = ""
    project_id: str = "local_project"
    model_trace: dict[str, Any] = Field(default_factory=dict)
    memory_inspector: dict[str, Any] = Field(default_factory=dict)
    character_state: dict[str, Any] = Field(default_factory=dict)
    continuity: dict[str, Any] = Field(default_factory=dict)
    narrative_layer: dict[str, Any] = Field(default_factory=dict)
    modification_impact: dict[str, Any] = Field(default_factory=dict)
    scene_progress: dict[str, Any] = Field(default_factory=dict)
    scene_snapshots: dict[str, Any] = Field(default_factory=dict)
    background_budget: dict[str, Any] = Field(default_factory=dict)
    background_thinking: dict[str, Any] = Field(default_factory=dict)
    pre_modify: dict[str, Any] = Field(default_factory=dict)
    pre_modify_workspace: dict[str, Any] = Field(default_factory=dict)
    scene_candidate_cache: dict[str, Any] = Field(default_factory=dict)
    future_review: dict[str, Any] = Field(default_factory=dict)
    chapter_archive: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    version_id: str = PHASE2_DEBUG_VERSION_ID
