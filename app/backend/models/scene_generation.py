from typing import Any, Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.decision import Decision


ALLOWED_STORY_INFORMATION_PRIORITIES = {
    "must_use",
    "should_use",
    "optional",
    "do_not_use",
}


class StoryInformationItem(BaseModel):
    item_id: str
    type: str
    content: str
    source_node: str
    priority: str = "should_use"
    related_character_ids: list[str] = Field(default_factory=list)
    related_world_rule_ids: list[str] = Field(default_factory=list)
    related_framework_component_ids: list[str] = Field(default_factory=list)
    order_hint: Optional[int] = None

    @validator("priority")
    def priority_must_be_known(cls, value: str) -> str:
        if value not in ALLOWED_STORY_INFORMATION_PRIORITIES:
            raise ValueError("StoryInformationItem.priority is not allowed.")
        return value


class OrderedStoryInformationPackage(BaseModel):
    opening_context: list[str] = Field(default_factory=list)
    scene_progression: list[str] = Field(default_factory=list)
    character_turns: list[str] = Field(default_factory=list)
    required_reveals: list[str] = Field(default_factory=list)
    emotional_beats: list[str] = Field(default_factory=list)
    ending_beat: list[str] = Field(default_factory=list)
    anti_repeat_guidance: list[str] = Field(default_factory=list)
    do_not_include: list[str] = Field(default_factory=list)


class SceneWritingContext(BaseModel):
    project_id: str = ""
    chapter_id: str = ""
    chapter_index: int = 0
    scene_id: str = ""
    scene_index: int = 1
    scene_count: int = 0
    project_story_premise: dict[str, Any] = Field(default_factory=dict)
    prompt_fidelity_contract: dict[str, Any] = Field(default_factory=dict)
    chapter_goal: str = ""
    current_chapter_brief_summary: str = ""
    chapter_scene_beat: dict[str, Any] = Field(default_factory=dict)
    chapter_scene_beat_history: list[dict[str, Any]] = Field(default_factory=list)
    current_chapter_framework: dict[str, Any] = Field(default_factory=dict)
    framework_composition_id: str = ""
    framework_context_source_refs: list[str] = Field(default_factory=list)
    generator_framework_context: dict[str, Any] = Field(default_factory=dict)
    resolved_scene_goal: str = ""
    previous_scene_summary: str = ""
    confirmed_scene_summaries: list[dict[str, Any]] = Field(default_factory=list)
    chapter_state_so_far: dict[str, Any] = Field(default_factory=dict)
    selected_abcd_participants: list[str] = Field(default_factory=list)
    scene_participation_package: dict[str, Any] = Field(default_factory=dict)
    tiered_character_context_package: dict[str, Any] = Field(default_factory=dict)
    tiered_character_intent_package: dict[str, Any] = Field(default_factory=dict)
    scene_memory_pack: dict[str, Any] = Field(default_factory=dict)
    authorial_intent: dict[str, Any] = Field(default_factory=dict)
    forbidden_repetition_patterns: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class SceneProgressionStatement(BaseModel):
    scene_objective: str = ""
    new_information: str = ""
    character_state_delta: str = ""
    conflict_turn: str = ""
    difference_from_previous_scene: str = ""
    required_prompt_terms: list[str] = Field(default_factory=list)
    required_character_ids: list[str] = Field(default_factory=list)
    required_memory_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class SceneProgressionInspection(BaseModel):
    passed: bool = False
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    adjacent_similarity: float = 0.0
    last_three_similarity: float = 0.0
    prompt_terms_seen: list[str] = Field(default_factory=list)
    demo_default_count: int = 0
    scene_pattern_signature: dict[str, Any] = Field(default_factory=dict)
    scene_pattern_similarity_report: dict[str, Any] = Field(default_factory=dict)
    pattern_verdict: str = "not_run"
    pattern_finding_codes: list[str] = Field(default_factory=list)


class SceneGenerationTrace(BaseModel):
    generation_trace_id: str = ""
    narrative_intent_ids: list[str] = Field(default_factory=list)
    narrative_intent_summary: str = ""
    authorial_intent_status: str = ""
    authorial_intent_skip_reason: str = ""
    authorial_intent_failure_reason: str = ""
    scene_goal: Optional[dict[str, Any]] = None
    environment: Optional[dict[str, Any]] = None
    role_beats: list[dict[str, Any]] = Field(default_factory=list)
    story_information_list: list[StoryInformationItem] = Field(default_factory=list)
    ordered_story_information_package: Optional[
        OrderedStoryInformationPackage
    ] = None
    subjective_record_ids: list[str] = Field(default_factory=list)
    subjective_fact_summary: str = ""
    objective_guard_blocked_count: int = 0
    objective_guard_warnings: list[str] = Field(default_factory=list)
    scene_writing_context: Optional[SceneWritingContext] = None
    scene_progression_statement: Optional[SceneProgressionStatement] = None
    progression_inspection: Optional[SceneProgressionInspection] = None


class SceneDraftContent(BaseModel):
    synopsis: str = ""
    prose_text: str = ""


class SceneMemoryExtraction(BaseModel):
    event_summary: list[dict[str, Any]] = Field(default_factory=list)
    proposed_state_changes: list[dict[str, Any]] = Field(default_factory=list)
    relationship_changes: list[dict[str, Any]] = Field(default_factory=list)
    memory_records: list[dict[str, Any]] = Field(default_factory=list)
    no_event_reason: str = ""


class SceneQualityReport(BaseModel):
    quality_report_id: str = ""
    passed: bool = False
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    continuity_checked: bool = False
    continuity_gate_run_id: str = ""
    continuity_checked_at: str = ""
    continuity_passed: bool = True
    continuity_issue_ids: list[str] = Field(default_factory=list)
    blocking_continuity_issue_ids: list[str] = Field(default_factory=list)
    accepted_continuity_issue_ids: list[str] = Field(default_factory=list)
    semantic_check_status: str = "not_run"
    summary: str = ""
    quality_degraded: bool = False
    confirmation_block_reason: str = ""


class SceneGenerationReadyStatus(BaseModel):
    ready: bool = False
    active_model_configured: bool = False
    world_canvas_confirmed: bool = False
    confirmed_a_character_count: int = 0
    main_cast_step_ready: bool = False
    main_cast_decision_exists: bool = False
    main_cast_finished: bool = False
    chapter_plan_step_ready: bool = False
    chapter_plan_decision_exists: bool = False
    chapter_plan_confirmed: bool = False
    current_chapter_exists: bool = False
    current_chapter_has_scene_count: bool = False
    current_chapter_framework_exists: bool = False
    current_chapter_framework_built: bool = False
    framework_package_ready: bool = False
    issues: list[str] = Field(default_factory=list)


class SceneGenerateFirstRequest(BaseModel):
    chapter_id: Optional[str] = None
    scene_index: int = 1


class SceneRegenerateFirstRequest(BaseModel):
    regeneration_hint: str = ""
    scene_id: Optional[str] = None
    chapter_id: Optional[str] = None
    scene_index: Optional[int] = None


class SceneConfirmDraftRequest(BaseModel):
    user_input: Optional[str] = None


class SceneGenerateNextRequest(BaseModel):
    chapter_id: Optional[str] = None
    force_refresh_packs: bool = False
    include_provisional: Optional[bool] = None


class SceneCommitRequest(BaseModel):
    commit_type: str
    user_input: Optional[str] = None
    revision_id: Optional[str] = None
    accepted_abcd_runtime_issue_ids: list[str] = Field(default_factory=list)

    @validator("accepted_abcd_runtime_issue_ids", pre=True)
    def accepted_abcd_issue_ids_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class SceneTemporaryConfirmRequest(BaseModel):
    user_input: Optional[str] = None


class SceneProgressResponse(BaseModel):
    chapter_id: str = ""
    scene_count: int = 0
    next_scene_index: int = 1
    can_generate_next: bool = False
    completion_status: str = "not_started"
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    blocking_reason_codes: list[str] = Field(default_factory=list)
    dependency_warnings: list[str] = Field(default_factory=list)


SCENE_GATE_PIPELINE_STATUSES = {
    "passed_without_repair",
    "passed_after_auto_repair",
    "blocked_requires_user_action",
    "blocked_requires_expert_review",
    "blocked_provider_degraded",
    "blocked_max_rounds",
}


class SceneGatePipelineSummary(BaseModel):
    pipeline_run_id: str = ""
    status: str = "passed_without_repair"
    rounds_completed: int = 0
    quality_checked: bool = False
    continuity_checked: bool = False
    quality_passed: bool = False
    continuity_passed: bool = False
    auto_repair_applied: bool = False
    visible_to_user: bool = True
    user_action_required: bool = False
    user_action_options: list[str] = Field(default_factory=list)
    safe_user_summary: str = ""
    approved_revision_id: str = ""
    continuity_gate_run_id: str = ""
    blocking_issue_codes: list[str] = Field(default_factory=list)

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_PIPELINE_STATUSES else "blocked_requires_expert_review"

    @validator("rounds_completed")
    def rounds_completed_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("user_action_options", "blocking_issue_codes", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("safe_user_summary")
    def summary_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:800]


class SceneGenerationResponse(BaseModel):
    success: bool = True
    scene: Optional[dict[str, Any]] = None
    story_information_summary: list[str] = Field(default_factory=list)
    quality_report: Optional[SceneQualityReport] = None
    readiness: Optional[SceneGenerationReadyStatus] = None
    decision: Optional[Decision] = None
    scene_snapshot: Optional[dict[str, Any]] = None
    progress: Optional[SceneProgressResponse] = None
    scene_gate_pipeline: Optional[SceneGatePipelineSummary] = None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
