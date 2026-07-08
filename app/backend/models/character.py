from typing import Any, Optional

from pydantic import BaseModel, Field, validator


ROLE_TIERS = {"A", "B", "C", "D"}


class CharacterPersonalityBaseline(BaseModel):
    traits: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    bottom_line: str = ""
    speech_style_hint: str = ""


class CharacterHardLimit(BaseModel):
    limit_id: str
    statement: str
    reason: str = ""
    source: str = "agent_generated"


class CharacterProfile(BaseModel):
    description: str = ""
    identity: str = ""
    story_function: str = ""
    background_summary: str = ""
    species_or_group: str = ""
    faction_or_origin: str = ""
    appearance_summary: str = ""
    traits: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    fears: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    personality_baseline: CharacterPersonalityBaseline = Field(
        default_factory=CharacterPersonalityBaseline
    )
    hard_limits: list[CharacterHardLimit] = Field(default_factory=list)
    knowledge_scope: list[str] = Field(default_factory=list)
    forbidden_knowledge: list[str] = Field(default_factory=list)


class CharacterCurrentState(BaseModel):
    location_id: str = ""
    faction_id: str = ""
    species_id: str = ""
    emotional_state: str = ""
    knowledge: list[str] = Field(default_factory=list)
    active_goal: str = ""
    current_desire: str = ""
    current_fear: str = ""
    resources: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)


class CharacterArcState(BaseModel):
    current_arc: str = ""
    starting_point: str = ""
    pressure: str = ""
    inner_conflict: str = ""
    next_possible_change: str = ""
    possible_direction: str = ""
    locked_future_events: list[str] = Field(default_factory=list)


class CharacterMemorySummary(BaseModel):
    summary: str = ""
    key_memory_ids: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    last_updated_event_id: str = ""


class CharacterContextBudget(BaseModel):
    max_character_tokens: int = 0
    include_recent_events: int = 0
    include_relationships: bool | str = True
    include_memory_summary: bool | str = True
    include_arc_state: bool = True
    include_forbidden_knowledge: bool | str = True
    include_full_profile: bool = True


class Character(BaseModel):
    character_id: str
    project_id: str = "local_project"
    name: str
    tier: str = "A"
    role: str = "protagonist"
    profile: CharacterProfile = Field(default_factory=CharacterProfile)
    current_state: CharacterCurrentState = Field(default_factory=CharacterCurrentState)
    relationship_refs: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)
    arc_state: CharacterArcState = Field(default_factory=CharacterArcState)
    memory_summary: CharacterMemorySummary = Field(default_factory=CharacterMemorySummary)
    context_budget: CharacterContextBudget = Field(default_factory=CharacterContextBudget)
    status: str = "confirmed"
    source: str = "seed"
    version_id: str
    created_at: str = ""
    updated_at: str = ""
    archived_at: str = ""

    @validator("tier")
    def tier_must_be_known(cls, value: str) -> str:
        tier = str(value or "A").upper()
        return tier if tier in ROLE_TIERS else "A"


class CharacterContextBuildRequest(BaseModel):
    character_ids: list[str] = Field(default_factory=list)
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 1
    scene_memory_pack_id: str = ""
    include_provisional: bool = False


class CharacterContextItem(BaseModel):
    character_id: str
    name: str = ""
    tier: str = "A"
    profile_summary: str = ""
    current_state_summary: str = ""
    personality_summary: str = ""
    memory_summary: str = ""
    relationship_summary: str = ""
    arc_summary: str = ""
    forbidden_knowledge: list[str] = Field(default_factory=list)
    hard_limits: list[str] = Field(default_factory=list)
    recent_memory_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    budget_applied: dict[str, Any] = Field(default_factory=dict)
    omitted_due_to_budget: list[str] = Field(default_factory=list)


class CharacterContextPreviewResponse(BaseModel):
    items: list[CharacterContextItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scene_memory_pack_id: Optional[str] = None


class RoleCreateRequest(BaseModel):
    name: str
    tier: str = "D"
    role: str = "npc"
    profile: dict[str, Any] = Field(default_factory=dict)
    current_state: dict[str, Any] = Field(default_factory=dict)
    memory_summary: dict[str, Any] = Field(default_factory=dict)
    user_input: str = ""

    @validator("tier")
    def create_tier_must_be_bcd(cls, value: str) -> str:
        tier = str(value or "D").upper()
        if tier not in {"B", "C", "D"}:
            raise ValueError("POST /api/roles can only create B/C/D roles.")
        return tier


class RolePatchRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    profile: dict[str, Any] = Field(default_factory=dict)
    current_state: dict[str, Any] = Field(default_factory=dict)
    arc_state: dict[str, Any] = Field(default_factory=dict)
    memory_summary: dict[str, Any] = Field(default_factory=dict)
    context_budget: dict[str, Any] = Field(default_factory=dict)
    user_input: str = ""


class RoleTierChangeRequest(BaseModel):
    tier: str
    user_input: str = ""

    @validator("tier")
    def changed_tier_must_be_known(cls, value: str) -> str:
        tier = str(value or "").upper()
        if tier not in ROLE_TIERS:
            raise ValueError("tier must be A, B, C, or D.")
        return tier


class RoleArchiveRequest(BaseModel):
    reason: str = ""
    user_input: str = ""


class RolesResponse(BaseModel):
    roles: list[Character] = Field(default_factory=list)


class RoleResponse(BaseModel):
    role: Character
    decision: Optional[Any] = None


class ProposedCharacterStateChange(BaseModel):
    character_id: str
    source_scene_id: str = ""
    source_event_id: str = ""
    source_memory_ids: list[str] = Field(default_factory=list)
    change_type: str = "other"
    impact_level: str = "minor"
    summary: str = ""
    reason: str = ""
    proposed_patch: dict[str, Any] = Field(default_factory=dict)

    @validator("impact_level")
    def impact_level_must_be_known(cls, value: str) -> str:
        impact = str(value or "minor").lower()
        return impact if impact in {"minor", "major"} else "minor"


class PendingCharacterStateChange(BaseModel):
    change_id: str
    project_id: str = "local_project"
    character_id: str
    character_name: str = ""
    tier: str = "A"
    source_scene_id: str = ""
    source_event_id: str = ""
    source_memory_ids: list[str] = Field(default_factory=list)
    change_type: str = "other"
    impact_level: str = "minor"
    status: str = "pending"
    summary: str = ""
    reason: str = ""
    proposed_patch: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    decided_at: str = ""
    decision_id: str = ""


class PendingCharacterStateChangeDecisionRequest(BaseModel):
    user_input: str = ""


class CharacterStateChangeResponse(BaseModel):
    change: PendingCharacterStateChange
    character: Optional[Character] = None
    decision: Optional[Any] = None


class PendingCharacterStateChangesResponse(BaseModel):
    changes: list[PendingCharacterStateChange] = Field(default_factory=list)
