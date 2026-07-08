from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.character import CharacterContextItem
from app.backend.models.memory_pack import SceneMemoryPack


SCENE_PARTICIPATION_PACKAGE_VERSION_ID = "phase85b_m4_scene_participation_package_v1"
TIERED_CHARACTER_CONTEXT_PACKAGE_VERSION_ID = "phase85b_m4_tiered_character_context_package_v1"


class SceneParticipationParticipant(BaseModel):
    character_id: str
    name: str = ""
    tier: Literal["A", "B", "C", "D"] = "D"
    role_label: str = ""
    participation_source: Literal[
        "m3_selection",
        "existing_reused_role",
        "chapter_ab_fallback",
        "legacy_a_fallback",
    ] = "m3_selection"
    selection_reason: str = ""
    context_depth: Literal["full", "medium", "compact", "minimal"] = "minimal"
    budget_applied: dict[str, Any] = Field(default_factory=dict)


class SceneParticipationReadinessReport(BaseModel):
    readiness_report_id: str
    project_id: str
    chapter_id: str
    scene_index: int
    scene_id: Optional[str] = None
    scene_participation_package_id: str = ""
    source_selection_id: Optional[str] = None
    selection_mode: Literal["m3_selection", "chapter_ab_or_legacy_a"] = "chapter_ab_or_legacy_a"
    ready: bool = False
    status: Literal["ready", "warning", "blocked"] = "blocked"
    needs_user_confirmation: bool = False
    active_character_ids: list[str] = Field(default_factory=list)
    unresolved_required_need_ids: list[str] = Field(default_factory=list)
    unresolved_optional_need_ids: list[str] = Field(default_factory=list)
    pending_creation_candidate_ids: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    no_story_fact_written: bool = True
    created_at: str = ""


class SceneParticipationPackage(BaseModel):
    scene_participation_package_id: str
    project_id: str
    chapter_id: str
    scene_index: int
    scene_id: Optional[str] = None
    source_selection_id: Optional[str] = None
    source_selection_status: str = ""
    selection_mode: Literal["m3_selection", "chapter_ab_or_legacy_a"] = "chapter_ab_or_legacy_a"
    status: Literal["ready", "warning", "blocked"] = "blocked"
    active_character_ids: list[str] = Field(default_factory=list)
    selected_a_ids: list[str] = Field(default_factory=list)
    selected_b_ids: list[str] = Field(default_factory=list)
    selected_c_ids: list[str] = Field(default_factory=list)
    selected_d_ids: list[str] = Field(default_factory=list)
    participants: list[SceneParticipationParticipant] = Field(default_factory=list)
    pending_creation_candidate_ids: list[str] = Field(default_factory=list)
    excluded_candidate_ids: list[str] = Field(default_factory=list)
    unresolved_required_need_ids: list[str] = Field(default_factory=list)
    unresolved_optional_need_ids: list[str] = Field(default_factory=list)
    scene_memory_pack_id: str = ""
    tiered_character_context_package_id: str = ""
    artifact_type: str = "runtime_context_cache"
    does_not_write_story_facts: bool = True
    stale_when_selection_changes: bool = True
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_query_signature: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = SCENE_PARTICIPATION_PACKAGE_VERSION_ID


class TieredCharacterContextPackage(BaseModel):
    tiered_character_context_package_id: str
    project_id: str
    chapter_id: str
    scene_index: int
    scene_id: Optional[str] = None
    scene_participation_package_id: str
    scene_memory_pack_id: str = ""
    active_character_ids: list[str] = Field(default_factory=list)
    items: list[CharacterContextItem] = Field(default_factory=list)
    item_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    artifact_type: str = "runtime_context_cache"
    does_not_write_story_facts: bool = True
    stale_when_selection_changes: bool = True
    created_at: str = ""
    updated_at: str = ""
    version_id: str = TIERED_CHARACTER_CONTEXT_PACKAGE_VERSION_ID

    @validator("item_count", always=True)
    def item_count_matches_items(cls, value: int, values: dict[str, Any]) -> int:
        items = values.get("items") or []
        return len(items)


class SceneParticipationPrepareRequest(BaseModel):
    chapter_id: str
    scene_index: int
    scene_id: Optional[str] = None
    scene_goal: str = ""
    scene_location: str = ""
    required_memory_refs: list[str] = Field(default_factory=list)
    include_provisional: bool = False
    force_refresh: bool = False

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("scene_index must be positive.")
        return int(value)


class SceneParticipationPrepareResponse(BaseModel):
    package: Optional[SceneParticipationPackage] = None
    tiered_character_context_package: Optional[TieredCharacterContextPackage] = None
    scene_memory_pack: Optional[SceneMemoryPack] = None
    readiness: Optional[SceneParticipationReadinessReport] = None
    warnings: list[str] = Field(default_factory=list)
