from typing import Any

from pydantic import BaseModel, Field


class Chapter(BaseModel):
    chapter_id: str
    project_id: str
    chapter_index: int = 0
    title: str = ""
    summary: str
    goals: list[str] = Field(default_factory=list)
    participant_character_ids: list[str] = Field(default_factory=list)
    participating_character_ids: list[str] = Field(default_factory=list)
    main_cast_character_ids: list[str] = Field(default_factory=list)
    supporting_role_ids: list[str] = Field(default_factory=list)
    supporting_role_refs: list[dict[str, Any]] = Field(default_factory=list)
    cd_role_function_needs: list[dict[str, Any]] = Field(default_factory=list)
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    light_route_summary: str = ""
    narrative_function: str = ""
    chapter_goal: str = ""
    main_conflict: str = ""
    chapter_framework_id: str = ""
    scene_count: int = 0
    scene_ids: list[str] = Field(default_factory=list)
    detail_level: str = "light"
    version_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: str
