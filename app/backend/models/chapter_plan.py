from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.backend.core.story_capacity import DEFAULT_CHAPTER_COUNT
from app.backend.models.chapter import Chapter
from app.backend.models.decision import Decision


class ChapterPlanValidationReport(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    user_confirmation_needed: list[str] = Field(default_factory=list)


class ChapterPlanFoundationStatus(BaseModel):
    ready: bool = False
    active_model_configured: bool = False
    world_canvas_confirmed: bool = False
    confirmed_a_character_count: int = 0
    project_step_ready: bool = False
    main_cast_decision_exists: bool = False
    main_cast_finished: bool = False
    framework_package_ready: bool = False
    issues: list[str] = Field(default_factory=list)


class ChapterSupportingRoleRef(BaseModel):
    character_id: str
    tier: Literal["B"] = "B"
    role_in_chapter: str = ""
    participation_reason: str = ""
    related_main_cast_ids: list[str] = Field(default_factory=list)
    expected_scene_indices: list[int] = Field(default_factory=list)
    context_depth: Literal["medium"] = "medium"


class CDRoleFunctionNeed(BaseModel):
    need_id: str
    scene_index: Optional[int] = None
    tier_preference: Literal["C", "D", "C_or_D"] = "C_or_D"
    function_type: Literal[
        "local_witness",
        "guard_or_gatekeeper",
        "crowd_reaction",
        "temporary_guide",
        "minor_opponent",
        "messenger",
        "shopkeeper",
        "driver",
        "servant",
        "patrol",
        "background_resident",
        "case_informant",
        "other",
    ] = "other"
    function_summary: str
    reason: str
    location_hint: str = ""
    relationship_hint: str = ""
    knowledge_need: str = ""
    reuse_existing_preferred: bool = True
    must_not_bind_specific_character_id: bool = True
    resolved_by_scene_agent: bool = True

    class Config:
        extra = "forbid"


class ChapterRouteItem(BaseModel):
    chapter_index: int
    temporary_title: str
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    macro_component_label: str
    light_route_summary: str
    narrative_function: str
    expected_focus_character_ids: list[str] = Field(default_factory=list)
    expected_supporting_role_ids: list[str] = Field(default_factory=list)
    cd_role_function_need_hints: list[CDRoleFunctionNeed] = Field(default_factory=list)
    expected_conflict_hint: str = ""
    planned_scene_count: Optional[int] = None
    detail_level: str = "light"
    future_lock_level: str = "low"


class ChapterSceneProgressionDelta(BaseModel):
    new_information: str = ""
    character_state_delta: str = ""
    conflict_turn: str = ""
    cost_or_risk_delta: str = ""


class ChapterSceneContinuityAnchors(BaseModel):
    carry_forward_threads: list[str] = Field(default_factory=list)
    allowed_returning_characters: list[str] = Field(default_factory=list)
    allowed_returning_locations: list[str] = Field(default_factory=list)
    required_memory_refs: list[str] = Field(default_factory=list)


class ChapterSceneStageStrategy(BaseModel):
    location_strategy: str = "open"
    time_delta: str = "must_make_time_relation_clear"
    action_mode: str = "open"
    atmosphere_delta: str = "optional"


class ChapterSceneAutonomySpace(BaseModel):
    character_action_freedom: Literal["low", "medium", "high"] = "high"
    optional_detours_allowed: bool = True
    cd_role_slots_open: bool = True


class ChapterSceneBeat(BaseModel):
    beat_id: str = ""
    chapter_id: str = ""
    scene_index: int
    scene_count: int
    scene_function: str = ""
    function_family: str = "open"
    required_progression_delta: ChapterSceneProgressionDelta = Field(
        default_factory=ChapterSceneProgressionDelta
    )
    continuity_anchors: ChapterSceneContinuityAnchors = Field(
        default_factory=ChapterSceneContinuityAnchors
    )
    stage_strategy: ChapterSceneStageStrategy = Field(default_factory=ChapterSceneStageStrategy)
    autonomy_space: ChapterSceneAutonomySpace = Field(default_factory=ChapterSceneAutonomySpace)
    avoid_repetition_axes: list[str] = Field(default_factory=list)
    ending_hook_requirement: str = ""
    source_refs: list[str] = Field(default_factory=list)


class CurrentChapterBrief(BaseModel):
    chapter_index: int
    title: str
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    chapter_framework_id: str
    chapter_goal: str
    reader_emotion_goal: list[str] = Field(default_factory=list)
    participating_character_ids: list[str] = Field(default_factory=list)
    main_cast_character_ids: list[str] = Field(default_factory=list)
    supporting_role_ids: list[str] = Field(default_factory=list)
    supporting_role_refs: list[ChapterSupportingRoleRef] = Field(default_factory=list)
    supporting_role_function_focus: list[dict[str, Any]] = Field(default_factory=list)
    cd_role_function_needs: list[CDRoleFunctionNeed] = Field(default_factory=list)
    main_conflict: str
    character_desire_or_arc_focus: list[dict[str, Any]] = Field(default_factory=list)
    world_rules_to_respect: list[str] = Field(default_factory=list)
    forbidden_moves: list[str] = Field(default_factory=list)
    recommended_scene_count: Optional[int] = None
    user_selected_scene_count: Optional[int] = None
    chapter_scene_beats: list[ChapterSceneBeat] = Field(default_factory=list)
    summary_for_scene_generation: str


class ChapterPlanDraft(BaseModel):
    draft_id: str
    project_id: str = "local_project"
    status: str = "draft"
    story_goal: str
    chapter_count: int
    current_chapter_index: int = 1
    source_world_canvas_id: str
    source_character_ids: list[str] = Field(default_factory=list)
    source_relationship_ids: list[str] = Field(default_factory=list)
    framework_package_id: str
    framework_composition_id: str = ""
    source_refs: list[str] = Field(default_factory=list)
    chapter_routes: list[ChapterRouteItem] = Field(default_factory=list)
    current_chapter_brief: CurrentChapterBrief
    current_chapter_framework: Optional[dict[str, Any]] = None
    current_chapter_framework_id: Optional[str] = None
    validation_report: ChapterPlanValidationReport
    user_confirmation_needed: list[str] = Field(default_factory=list)
    latest_user_prompt: str = ""
    created_at: str
    updated_at: str


class ChapterPlanGenerateRequest(BaseModel):
    story_goal: str
    chapter_count: int = DEFAULT_CHAPTER_COUNT
    current_chapter_index: int = 1
    framework_composition_id: str = ""


class ChapterPlanReviseRequest(BaseModel):
    revision_prompt: str


class ChapterPlanSceneCountRequest(BaseModel):
    chapter_index: int
    scene_count: int


class ChapterPlanConfirmRequest(BaseModel):
    user_input: Optional[str] = None


class ChapterPlanRemovedSupportingRoleReference(BaseModel):
    field_path: str
    character_id: str
    name: str = ""
    tier: str = ""
    status: str = ""
    reason: str = "supporting role fields require confirmed B-tier roles"


class ChapterPlanRepairSupportingRoleReferencesResponse(BaseModel):
    success: bool = True
    draft: Optional[ChapterPlanDraft] = None
    validation_report: ChapterPlanValidationReport
    removed_references: list[ChapterPlanRemovedSupportingRoleReference] = Field(
        default_factory=list
    )
    remaining_valid_supporting_role_ids: list[str] = Field(default_factory=list)
    stale_reason_cleared: bool = False
    foundation: Optional[ChapterPlanFoundationStatus] = None


class ChapterPlanWorkflowResponse(BaseModel):
    draft: Optional[ChapterPlanDraft] = None
    chapters: list[Chapter] = Field(default_factory=list)
    current_chapter_framework: Optional[dict[str, Any]] = None
    validation: Optional[ChapterPlanValidationReport] = None
    foundation: Optional[ChapterPlanFoundationStatus] = None
    decision: Optional[Decision] = None
