from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, validator


PHASE85E_M1_WRITER_PROSE_ENGINE_CONTRACT_VERSION = (
    "phase85e_m1_writer_prose_engine_contract_v1"
)
PHASE85E_M2_PSYCHOLOGY_VISIBILITY_VERSION = (
    "phase85e_m2_psychology_visibility_subtext_v1"
)
PHASE85E_M3_WRITER_PLANNER_LAYER_VERSION = "phase85e_m3_writer_planner_layer_v1"
PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION = "phase85e_m4_writer_prose_drafting_v1"
PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION = (
    "phase85e_m5_reader_experience_self_revision_v1"
)
DEFAULT_PROSE_STYLE_PROFILE_ID = "web_serial_clear_plot"

PSYCHOLOGY_TIERS = {"A", "B", "C", "D"}
PSYCHOLOGY_VISIBILITY_LEVELS = {
    "none",
    "behavior_only",
    "micro_reaction",
    "short_inner_line",
    "full_inner_moment",
}
PSYCHOLOGY_ALLOWED_CHANNELS = {
    "gesture",
    "action_choice",
    "dialogue_subtext",
    "silence_pause",
    "one_short_inner_line",
}
PSYCHOLOGY_INTERIORITY_BUDGETS = {"none", "low", "medium", "high"}
PSYCHOLOGY_POV_MODES = {"limited_external", "close_limited", "rotating_limited"}
WRITER_PLANNER_BEAT_TYPES = {
    "opening_hook",
    "obstacle",
    "character_move",
    "conflict_turn",
    "information_release",
    "ending_pull",
}
WRITER_PLANNER_SUB_AGENT_ORDER = [
    "ScenePurposePlanner",
    "ReaderHookPlanner",
    "ConflictTurnPlanner",
    "CharacterMovePlanner",
    "InformationReleasePlanner",
    "PsychologyVisibilityPlanner",
    "PacingPlanner",
    "BeatSheetBuilder",
]
WRITER_PROSE_DRAFTING_MODULE_ORDER = [
    "DialogueActionWriter",
    "SubtextRenderer",
    "PlainProseStylist",
    "HookAndPayoffEditor",
    "RepetitionBreaker",
    "InteriorLineLimiter",
]


class SentenceStylePolicy(BaseModel):
    plain_language_required: bool = True
    max_sentence_length_hint: int = 28
    sentence_variety_required: bool = True
    avoid_overloaded_clauses: bool = True


class SceneStylePolicy(BaseModel):
    show_dont_explain: bool = True
    concrete_action_required: bool = True
    dialogue_or_decision_required: bool = True
    abstract_language_budget: float = 0.24

    @validator("abstract_language_budget")
    def density_must_be_safe(cls, value: float) -> float:
        return _safe_density(value, "abstract_language_budget")


class SuspenseStylePolicy(BaseModel):
    concrete_evidence_required: bool = True
    reveal_or_question_required: bool = True
    empty_mystery_budget: float = 0.18

    @validator("empty_mystery_budget")
    def density_must_be_safe(cls, value: float) -> float:
        return _safe_density(value, "empty_mystery_budget")


class PsychologyStylePolicy(BaseModel):
    mode: str = "subtext_first"
    behavior_first: bool = True
    direct_explanation_budget: float = 0.22
    interiority_requires_visible_trigger: bool = True

    @validator("direct_explanation_budget")
    def density_must_be_safe(cls, value: float) -> float:
        return _safe_density(value, "direct_explanation_budget")


class ProseStyleProfile(BaseModel):
    style_profile_id: str = DEFAULT_PROSE_STYLE_PROFILE_ID
    label: str = "clear plot-driven web-serial prose"
    language_density: float = 0.48
    adjective_budget: float = 0.18
    metaphor_budget: float = 0.20
    scene_drive: list[str] = Field(default_factory=lambda: ["action", "dialogue", "decision"])
    reader_hook_required: bool = True
    sentence_style: SentenceStylePolicy = Field(default_factory=SentenceStylePolicy)
    scene_style: SceneStylePolicy = Field(default_factory=SceneStylePolicy)
    suspense_style: SuspenseStylePolicy = Field(default_factory=SuspenseStylePolicy)
    psychology_policy: PsychologyStylePolicy = Field(default_factory=PsychologyStylePolicy)
    limited_patterns: list[str] = Field(default_factory=list)
    limited_patterns_are_density_hints: bool = True
    version_id: str = PHASE85E_M1_WRITER_PROSE_ENGINE_CONTRACT_VERSION

    @validator("style_profile_id", "label")
    def required_text_must_be_non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("ProseStyleProfile requires non-empty id and label.")
        return text

    @validator("language_density", "adjective_budget", "metaphor_budget")
    def density_must_be_safe(cls, value: float) -> float:
        return _safe_density(value, "profile_density")

    @validator("scene_drive", "limited_patterns", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ConflictTurnPlan(BaseModel):
    turn_trigger: str = ""
    pressure_source: str = ""
    turn: str = ""
    outcome: str = ""

    def is_valid(self) -> bool:
        return bool(
            self.turn_trigger.strip()
            and self.pressure_source.strip()
            and self.turn.strip()
            and self.outcome.strip()
        )


class CharacterMovePlan(BaseModel):
    character_id: str = ""
    intended_move: str = ""
    visible_action: str = ""
    scene_effect: str = ""

    def is_meaningful(self) -> bool:
        return bool(
            self.character_id.strip()
            and self.intended_move.strip()
            and self.visible_action.strip()
        )


class InformationControlPlan(BaseModel):
    reveal: str = ""
    withhold: str = ""
    misdirect: str = ""
    reader_question: str = ""
    source_refs: list[str] = Field(default_factory=list)

    @validator("source_refs", pre=True)
    def refs_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class PacingPlan(BaseModel):
    opening_pressure: str = ""
    escalation: str = ""
    release_or_turn: str = ""
    target_tempo: str = "medium"
    quiet_ratio: float = 0.30

    @validator("quiet_ratio")
    def density_must_be_safe(cls, value: float) -> float:
        return _safe_density(value, "quiet_ratio")


class SceneProsePlan(BaseModel):
    scene_prose_plan_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    style_profile_id: str = DEFAULT_PROSE_STYLE_PROFILE_ID
    source_chapter_scene_beat_id: str = ""
    source_chapter_scene_beat_fallback: bool = False
    source_chapter_scene_beat_fallback_reason: str = ""
    previous_scene_summary: str = ""
    previous_scene_pattern: str = ""
    scene_purpose: str = ""
    reader_value: str = ""
    must_change_by_end: str = ""
    difference_from_previous_scene: str = ""
    opening_hook: str = ""
    ending_pull: str = ""
    conflict_turn: ConflictTurnPlan = Field(default_factory=ConflictTurnPlan)
    new_information: str = ""
    character_state_delta: str = ""
    relationship_delta: str = ""
    cost_or_risk_delta: str = ""
    character_moves: list[CharacterMovePlan] = Field(default_factory=list)
    information_control: InformationControlPlan = Field(default_factory=InformationControlPlan)
    psychology_visibility_plan_id: str = ""
    beat_sheet_id: str = ""
    pacing: PacingPlan = Field(default_factory=PacingPlan)
    forbidden_repetition_patterns: list[str] = Field(default_factory=list)
    required_prompt_terms: list[str] = Field(default_factory=list)
    required_memory_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    version_id: str = PHASE85E_M1_WRITER_PROSE_ENGINE_CONTRACT_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("SceneProsePlan.scene_index must be >= 1.")
        return int(value)

    @validator(
        "forbidden_repetition_patterns",
        "required_prompt_terms",
        "required_memory_refs",
        "source_refs",
        pre=True,
    )
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class SceneProsePlanValidationReport(BaseModel):
    schema_version: str = PHASE85E_M1_WRITER_PROSE_ENGINE_CONTRACT_VERSION
    scene_prose_plan_id: str = ""
    passed: bool = False
    issue_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    candidate_only_boundary_enforced: bool = False
    no_direct_story_write_fields: bool = False
    source_chapter_scene_beat_fallback_used: bool = False

    @validator("issue_codes", "warning_codes", "issues", "warnings", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class PsychologyVisibilityDecision(BaseModel):
    decision_id: str
    project_id: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 1
    character_id: str = ""
    tier: str = "D"
    visibility_level: str = "behavior_only"
    reason: str = ""
    allowed_channels: list[str] = Field(default_factory=list)
    max_words: int = 0
    forbidden: list[str] = Field(default_factory=list)
    source_psychology_trace_ids: list[str] = Field(default_factory=list)
    source_context_item_ids: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    raw_psychology_chain_present: bool = False
    version_id: str = PHASE85E_M2_PSYCHOLOGY_VISIBILITY_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        return max(1, int(value or 1))

    @validator("tier")
    def tier_must_be_normalized(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @validator("visibility_level")
    def visibility_level_must_be_normalized(cls, value: str) -> str:
        return str(value or "").strip()

    @validator(
        "allowed_channels",
        "forbidden",
        "source_psychology_trace_ids",
        "source_context_item_ids",
        pre=True,
    )
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class PsychologicalNegativeSpace(BaseModel):
    negative_space_id: str
    project_id: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 1
    character_id: str = ""
    tier: str = "D"
    withheld_psychology_summary: str = ""
    reason: str = ""
    future_payoff_hint: str = ""
    source_psychology_trace_ids: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    raw_psychology_chain_present: bool = False
    version_id: str = PHASE85E_M2_PSYCHOLOGY_VISIBILITY_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        return max(1, int(value or 1))

    @validator("tier")
    def tier_must_be_normalized(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @validator("source_psychology_trace_ids", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class PsychologyVisibilityPlan(BaseModel):
    psychology_visibility_plan_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    pov_mode: str = "limited_external"
    default_policy: str = "behavior_first"
    total_interiority_budget: str = "low"
    no_raw_psychology_chain: bool = True
    psychology_is_subtext_by_default: bool = True
    decisions: list[PsychologyVisibilityDecision] = Field(default_factory=list)
    negative_space_ids: list[str] = Field(default_factory=list)
    source_scene_prose_plan_id: str = ""
    source_character_intent_package_id: str = ""
    source_context_refs: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    version_id: str = PHASE85E_M2_PSYCHOLOGY_VISIBILITY_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("PsychologyVisibilityPlan.scene_index must be >= 1.")
        return int(value)

    @validator("pov_mode", "default_policy", "total_interiority_budget")
    def policy_text_must_be_normalized(cls, value: str) -> str:
        return str(value or "").strip()

    @validator("negative_space_ids", "source_context_refs", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class PsychologyVisibilityPlanValidationReport(BaseModel):
    schema_version: str = PHASE85E_M2_PSYCHOLOGY_VISIBILITY_VERSION
    psychology_visibility_plan_id: str = ""
    passed: bool = False
    issue_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    candidate_only_boundary_enforced: bool = False
    all_tiers_have_visibility_decisions: bool = False
    tier_policy_enforced: bool = False
    raw_psychology_chain_forbidden: bool = False
    negative_space_safe: bool = False

    @validator("issue_codes", "warning_codes", "issues", "warnings", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class Beat(BaseModel):
    beat_index: int
    beat_type: str
    purpose: str = ""
    required_action: str = ""
    required_reveal_or_decision: str = ""
    allowed_psychology_visibility: list[str] = Field(default_factory=list)
    source_character_ids: list[str] = Field(default_factory=list)
    source_plan_field: str = ""
    source_refs: list[str] = Field(default_factory=list)

    @validator("beat_index")
    def beat_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("Beat.beat_index must be >= 1.")
        return int(value)

    @validator("beat_type")
    def beat_type_must_be_allowed(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in WRITER_PLANNER_BEAT_TYPES:
            raise ValueError("Beat.beat_type is not allowed.")
        return text

    @validator(
        "allowed_psychology_visibility",
        "source_character_ids",
        "source_refs",
        pre=True,
    )
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class BeatSheet(BaseModel):
    beat_sheet_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    source_scene_prose_plan_id: str = ""
    source_psychology_visibility_plan_id: str = ""
    beats: list[Beat] = Field(default_factory=list)
    required_beat_types: list[str] = Field(
        default_factory=lambda: ["opening_hook", "character_move", "conflict_turn", "ending_pull"]
    )
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    version_id: str = PHASE85E_M3_WRITER_PLANNER_LAYER_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("BeatSheet.scene_index must be >= 1.")
        return int(value)

    @validator("required_beat_types", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterPlannerInputSnapshot(BaseModel):
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    style_profile_id: str = DEFAULT_PROSE_STYLE_PROFILE_ID
    scene_writing_context_summary: str = ""
    scene_progression_statement: str = ""
    chapter_scene_beat_id: str = ""
    required_progression_delta: str = ""
    previous_scene_summary: str = ""
    previous_scene_pattern: str = ""
    previous_ending_pull: str = ""
    active_character_ids: list[str] = Field(default_factory=list)
    active_character_tiers: dict[str, str] = Field(default_factory=dict)
    writer_abcd_context_view_id: str = ""
    abcd_story_information_package_id: str = ""
    memory_context_refs: list[str] = Field(default_factory=list)
    character_intent_refs: list[str] = Field(default_factory=list)
    prompt_terms: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    version_id: str = PHASE85E_M3_WRITER_PLANNER_LAYER_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("WriterPlannerInputSnapshot.scene_index must be >= 1.")
        return int(value)

    @validator(
        "active_character_ids",
        "memory_context_refs",
        "character_intent_refs",
        "prompt_terms",
        "source_refs",
        pre=True,
    )
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterPlannerSubAgentTrace(BaseModel):
    step_index: int
    sub_agent_name: str
    contributed_fields: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    safe_summary: str = ""

    @validator("step_index")
    def step_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("WriterPlannerSubAgentTrace.step_index must be >= 1.")
        return int(value)

    @validator("contributed_fields", "source_refs", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterPlannerLayerOutput(BaseModel):
    planner_output_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    input_snapshot: WriterPlannerInputSnapshot
    scene_prose_plan: SceneProsePlan
    psychology_visibility_plan: PsychologyVisibilityPlan
    beat_sheet: BeatSheet
    logical_sub_agent_traces: list[WriterPlannerSubAgentTrace] = Field(default_factory=list)
    required_progression_delta_mapped: bool = False
    ending_pull_differs_from_previous: bool = False
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    version_id: str = PHASE85E_M3_WRITER_PLANNER_LAYER_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("WriterPlannerLayerOutput.scene_index must be >= 1.")
        return int(value)


class WriterPlannerLayerValidationReport(BaseModel):
    schema_version: str = PHASE85E_M3_WRITER_PLANNER_LAYER_VERSION
    planner_output_id: str = ""
    passed: bool = False
    issue_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    beat_sheet_passed: bool = False
    logical_sub_agent_trace_order_valid: bool = False
    candidate_only_boundary_enforced: bool = False
    no_direct_story_write_fields: bool = False

    @validator("issue_codes", "warning_codes", "issues", "warnings", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class RenderedProseBeat(BaseModel):
    beat_index: int
    beat_type: str
    source_beat_type: str = ""
    source_beat_refs: list[str] = Field(default_factory=list)
    prose_segment: str = ""
    used_character_ids: list[str] = Field(default_factory=list)
    visible_action_present: bool = False
    dialogue_or_decision_present: bool = False
    concrete_information_reveal_present: bool = False
    psychology_channels_used: list[str] = Field(default_factory=list)
    interior_line_word_count: int = 0
    source_refs: list[str] = Field(default_factory=list)
    version_id: str = PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION

    @validator("beat_index")
    def beat_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("RenderedProseBeat.beat_index must be >= 1.")
        return int(value)

    @validator(
        "source_beat_refs",
        "used_character_ids",
        "psychology_channels_used",
        "source_refs",
        pre=True,
    )
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterProseDraftingInput(BaseModel):
    input_id: str
    planner_output_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    style_profile_id: str = DEFAULT_PROSE_STYLE_PROFILE_ID
    source_scene_prose_plan_id: str = ""
    source_psychology_visibility_plan_id: str = ""
    source_beat_sheet_id: str = ""
    do_not_use_texts: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    version_id: str = PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("WriterProseDraftingInput.scene_index must be >= 1.")
        return int(value)

    @validator("do_not_use_texts", "source_refs", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterProseDraftingTrace(BaseModel):
    step_index: int
    module_name: str
    contributed_fields: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    version_id: str = PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION

    @validator("step_index")
    def step_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("WriterProseDraftingTrace.step_index must be >= 1.")
        return int(value)

    @validator("contributed_fields", "source_refs", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class SubtextRenderingDecision(BaseModel):
    decision_id: str
    source_psychology_decision_id: str = ""
    character_id: str = ""
    tier: str = "D"
    visibility_level: str = "behavior_only"
    rendered_channel: str = "action_choice"
    rendered_subtext: str = ""
    interior_line_word_count: int = 0
    policy_respected: bool = True
    raw_psychology_chain_present: bool = False
    source_refs: list[str] = Field(default_factory=list)
    version_id: str = PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION

    @validator("source_refs", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class SubtextRenderingReport(BaseModel):
    schema_version: str = PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION
    subtext_report_id: str = ""
    status: str = "failed"
    psychology_visibility_decisions_read: bool = False
    subtext_decisions_written: bool = False
    behavior_first_policy_respected: bool = False
    tier_policy_respected: bool = False
    interior_line_budget_respected: bool = False
    raw_psychology_chain_forbidden: bool = False
    negative_space_not_written_as_prose: bool = True
    decisions: list[SubtextRenderingDecision] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    version_id: str = PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION

    @validator("issue_codes", "issues", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterProseDraftPackage(BaseModel):
    draft_package_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    source_planner_output_id: str
    source_scene_prose_plan_id: str
    source_psychology_visibility_plan_id: str
    source_beat_sheet_id: str
    style_profile_id: str = DEFAULT_PROSE_STYLE_PROFILE_ID
    candidate_synopsis: str = ""
    candidate_prose: str = ""
    rendered_beats: list[RenderedProseBeat] = Field(default_factory=list)
    drafting_traces: list[WriterProseDraftingTrace] = Field(default_factory=list)
    subtext_rendering_report: SubtextRenderingReport = Field(default_factory=SubtextRenderingReport)
    character_ids_present: list[str] = Field(default_factory=list)
    required_prompt_terms_used: list[str] = Field(default_factory=list)
    used_story_information_item_ids: list[str] = Field(default_factory=list)
    ignored_do_not_use_item_ids: list[str] = Field(default_factory=list)
    required_progression_delta_reflected: bool = False
    opening_hook_reflected: bool = False
    conflict_turn_reflected: bool = False
    ending_pull_reflected: bool = False
    visible_action_present: bool = False
    dialogue_or_decision_present: bool = False
    psychology_visibility_applied: bool = False
    raw_psychology_chain_forbidden: bool = False
    internal_json_forbidden: bool = False
    empty_mystery_density: float = 0.0
    abstract_language_density: float = 0.0
    adjective_density: float = 0.0
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    requires_post_draft_gate_review: bool = True
    version_id: str = PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("WriterProseDraftPackage.scene_index must be >= 1.")
        return int(value)

    @validator(
        "character_ids_present",
        "required_prompt_terms_used",
        "used_story_information_item_ids",
        "ignored_do_not_use_item_ids",
        pre=True,
    )
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterProseDraftingValidationReport(BaseModel):
    schema_version: str = PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION
    draft_package_id: str = ""
    passed: bool = False
    issue_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    beat_order_reflected: bool = False
    opening_hook_reflected: bool = False
    conflict_turn_reflected: bool = False
    character_move_reflected: bool = False
    required_progression_delta_reflected: bool = False
    ending_pull_reflected: bool = False
    visible_action_present: bool = False
    dialogue_or_decision_present: bool = False
    psychology_visibility_applied: bool = False
    raw_psychology_chain_forbidden: bool = False
    internal_json_forbidden: bool = False
    empty_mystery_density_within_threshold: bool = False
    abstract_language_density_within_threshold: bool = False
    adjective_density_within_threshold: bool = False
    candidate_only_boundary_enforced: bool = False
    post_draft_gate_requirement_preserved: bool = False

    @validator("issue_codes", "warning_codes", "issues", "warnings", pre=True)
    def list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ReaderExperienceReport(BaseModel):
    schema_version: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION
    reader_experience_report_id: str = ""
    project_id: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 1
    source_draft_package_id: str = ""
    plot_turn_present: bool = False
    visible_action_present: bool = False
    dialogue_or_decision_present: bool = False
    ending_pull_present: bool = False
    scene_reader_value_present: bool = False
    reader_question_answered_or_advanced: bool = False
    reader_question_raised: bool = False
    empty_mystery_density: float = 0.0
    abstract_language_density: float = 0.0
    adjective_density: float = 0.0
    issue_codes: list[str] = Field(default_factory=list)
    repairable_issue_codes: list[str] = Field(default_factory=list)
    blocking_issue_codes: list[str] = Field(default_factory=list)
    passed: bool = False
    candidate_only: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION

    @validator("issue_codes", "repairable_issue_codes", "blocking_issue_codes", pre=True)
    def m5_list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class PsychologyOverexposureReport(BaseModel):
    schema_version: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION
    psychology_overexposure_report_id: str = ""
    project_id: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 1
    source_draft_package_id: str = ""
    psychology_density: float = 0.0
    interior_monologue_count: int = 0
    minor_role_interiority_count: int = 0
    raw_psychology_chain_detected: bool = False
    action_replaced_by_explanation: bool = False
    subtext_policy_respected: bool = True
    issue_codes: list[str] = Field(default_factory=list)
    repairable_issue_codes: list[str] = Field(default_factory=list)
    blocking_issue_codes: list[str] = Field(default_factory=list)
    passed: bool = False
    candidate_only: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION

    @validator("issue_codes", "repairable_issue_codes", "blocking_issue_codes", pre=True)
    def m5_list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ProseStyleInspectionReport(BaseModel):
    schema_version: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION
    prose_style_inspection_report_id: str = ""
    source_draft_package_id: str = ""
    abstract_language_density: float = 0.0
    adjective_density: float = 0.0
    empty_mystery_density: float = 0.0
    metaphor_density: float = 0.0
    repeated_poetic_patterns: list[str] = Field(default_factory=list)
    plain_language_score: float = 1.0
    issue_codes: list[str] = Field(default_factory=list)
    repairable_issue_codes: list[str] = Field(default_factory=list)
    blocking_issue_codes: list[str] = Field(default_factory=list)
    passed: bool = False
    candidate_only: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION

    @validator(
        "repeated_poetic_patterns",
        "issue_codes",
        "repairable_issue_codes",
        "blocking_issue_codes",
        pre=True,
    )
    def m5_list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class HookPayoffInspectionReport(BaseModel):
    schema_version: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION
    hook_payoff_inspection_report_id: str = ""
    source_draft_package_id: str = ""
    opening_hook_concrete: bool = False
    ending_pull_concrete: bool = False
    reader_question_advanced: bool = False
    issue_codes: list[str] = Field(default_factory=list)
    repairable_issue_codes: list[str] = Field(default_factory=list)
    blocking_issue_codes: list[str] = Field(default_factory=list)
    passed: bool = False
    candidate_only: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION

    @validator("issue_codes", "repairable_issue_codes", "blocking_issue_codes", pre=True)
    def m5_list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class SubtextBalanceInspectionReport(BaseModel):
    schema_version: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION
    subtext_balance_inspection_report_id: str = ""
    source_draft_package_id: str = ""
    subtext_policy_respected: bool = True
    negative_space_preserved: bool = True
    minor_role_interiority_count: int = 0
    issue_codes: list[str] = Field(default_factory=list)
    repairable_issue_codes: list[str] = Field(default_factory=list)
    blocking_issue_codes: list[str] = Field(default_factory=list)
    passed: bool = False
    candidate_only: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION

    @validator("issue_codes", "repairable_issue_codes", "blocking_issue_codes", pre=True)
    def m5_list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterQualityInspectionBundle(BaseModel):
    schema_version: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION
    inspection_bundle_id: str = ""
    source_draft_package_id: str = ""
    reader_experience_report: ReaderExperienceReport = Field(default_factory=ReaderExperienceReport)
    psychology_overexposure_report: PsychologyOverexposureReport = Field(default_factory=PsychologyOverexposureReport)
    prose_style_report: ProseStyleInspectionReport = Field(default_factory=ProseStyleInspectionReport)
    hook_payoff_report: HookPayoffInspectionReport = Field(default_factory=HookPayoffInspectionReport)
    subtext_balance_report: SubtextBalanceInspectionReport = Field(default_factory=SubtextBalanceInspectionReport)
    issue_codes: list[str] = Field(default_factory=list)
    repairable_issue_codes: list[str] = Field(default_factory=list)
    blocking_issue_codes: list[str] = Field(default_factory=list)
    passed: bool = False
    ready_for_revision: bool = False
    ready_for_downstream_gates: bool = False
    candidate_only: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION

    @validator("issue_codes", "repairable_issue_codes", "blocking_issue_codes", pre=True)
    def m5_list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterSelfRevisionAction(BaseModel):
    action_id: str = ""
    action_type: str = ""
    source_issue_codes: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    applied: bool = False
    candidate_only: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION

    @validator("source_issue_codes", pre=True)
    def m5_list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterSelfRevisionReport(BaseModel):
    schema_version: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION
    writer_self_revision_report_id: str = ""
    source_draft_package_id: str = ""
    original_issue_codes: list[str] = Field(default_factory=list)
    revision_actions: list[WriterSelfRevisionAction] = Field(default_factory=list)
    final_issue_codes: list[str] = Field(default_factory=list)
    blocking_issue_codes: list[str] = Field(default_factory=list)
    repair_passes_run: int = 0
    ready_for_downstream_gates: bool = False
    blocking_issue_remains: bool = False
    candidate_only: bool = True
    no_story_write: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION

    @validator("original_issue_codes", "final_issue_codes", "blocking_issue_codes", pre=True)
    def m5_list_fields_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterSelfRevisionResult(BaseModel):
    schema_version: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION
    source_draft_package_id: str = ""
    revised_draft_package: WriterProseDraftPackage
    initial_inspection_bundle: WriterQualityInspectionBundle
    final_inspection_bundle: WriterQualityInspectionBundle
    revision_report: WriterSelfRevisionReport
    m4_validation_report: WriterProseDraftingValidationReport
    writer_self_revision_applied: bool = False
    ready_for_downstream_gates: bool = False
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    requires_post_draft_gate_review: bool = True
    version_id: str = PHASE85E_M5_READER_EXPERIENCE_SELF_REVISION_VERSION


def _safe_density(value: float, field_name: str) -> float:
    number = float(value)
    if number < 0 or number > 1:
        raise ValueError(f"{field_name} must be between 0 and 1.")
    return number


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
        key = " ".join(text.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
