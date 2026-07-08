from typing import Optional

from pydantic import BaseModel, Field


class Phase1GraphState(BaseModel):
    project_id: str = "local_project"
    current_step: str = "build_world_canvas"
    user_input: Optional[str] = None
    user_action: Optional[str] = None
    active_model_ready: bool = False
    world_canvas: Optional[dict] = None
    world_canvas_confirmed: bool = False
    character_draft: Optional[dict] = None
    characters: list[dict] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    main_cast_finished: bool = False
    chapter_plan_draft: Optional[dict] = None
    chapter_plan_confirmed: bool = False
    chapters: list[dict] = Field(default_factory=list)
    current_chapter_framework: Optional[dict] = None
    scene_generation_ready: bool = False
    current_scene: Optional[dict] = None
    scene_generation_trace: Optional[dict] = None
    ordered_story_information_package: Optional[dict] = None
    scene_quality_report: Optional[dict] = None
    scene_confirmed: bool = False
    scene_revision_candidate: Optional[dict] = None
    scene_revision_intent: str = ""
    scene_revised: bool = False
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
