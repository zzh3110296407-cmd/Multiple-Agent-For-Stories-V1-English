from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.narrative_layer import CharacterPsychologyTrace


CHARACTER_INTENT_VERSION_ID = "phase85b_m6_character_intent_v1"
TRACE_DEPTHS = {"full", "medium", "compact", "minimal"}
TIERS = {"A", "B", "C", "D"}
TRUTH_STATUSES = {
    "objective_candidate",
    "subjective_claim",
    "perception",
    "lie",
    "misinformation",
    "unknown",
}
RISK_LEVELS = {"none", "low", "medium", "high", "blocking"}
RECOMMENDED_GATES = {
    "continuity_gate",
    "apparent_gate",
    "quality_gate",
    "user_confirmation_candidate",
    "none",
}
PACKAGE_STATUSES = {"ready", "warning", "blocked"}


class CharacterPsychologyTraceRuntimeMeta(BaseModel):
    runtime_meta_id: str
    project_id: str
    psychology_trace_id: str
    scene_participation_package_id: str
    tiered_character_context_package_id: str
    scene_memory_pack_id: str
    chapter_memory_pack_id: str = ""
    chapter_id: str
    scene_id: str
    scene_index: int
    character_id: str
    tier: Literal["A", "B", "C", "D"]
    trace_depth: Literal["full", "medium", "compact", "minimal"]
    source_memory_ids: list[str] = Field(default_factory=list)
    source_context_item_ids: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    does_not_write_story_facts: bool = True
    created_at: str = ""
    updated_at: str = ""
    version_id: str = CHARACTER_INTENT_VERSION_ID

    @validator("source_memory_ids", "source_context_item_ids", pre=True)
    def refs_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CharacterActionIntentionCandidate(BaseModel):
    action_intention_candidate_id: str
    project_id: str
    psychology_trace_id: str
    scene_participation_package_id: str
    tiered_character_context_package_id: str
    scene_memory_pack_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    character_id: str
    tier: Literal["A", "B", "C", "D"]
    intention_type: str
    intention_summary: str
    psychological_reason: str
    outward_expression_hint: str
    target_character_ids: list[str] = Field(default_factory=list)
    target_object_ids: list[str] = Field(default_factory=list)
    target_location: str = ""
    truth_status: Literal[
        "objective_candidate",
        "subjective_claim",
        "perception",
        "lie",
        "misinformation",
        "unknown",
    ] = "objective_candidate"
    expected_story_function: str = ""
    continuity_risk_level: Literal["none", "low", "medium", "high", "blocking"] = "low"
    apparent_contradiction_possible: bool = False
    requires_continuity_gate: bool = False
    requires_apparent_gate: bool = False
    requires_quality_gate: bool = False
    requires_user_confirmation_candidate: bool = False
    can_be_used_by_writer: bool = True
    can_write_objective_fact_directly: bool = False
    candidate_only: bool = True
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = CHARACTER_INTENT_VERSION_ID

    @validator("target_character_ids", "target_object_ids", "warnings", pre=True)
    def candidate_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("can_write_objective_fact_directly")
    def cannot_write_objective_fact(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("M6 action intention candidates cannot write objective facts.")
        return False

    @validator("candidate_only")
    def candidate_only_must_remain_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M6 action intention candidates must remain candidate-only.")
        return True


class CharacterIntentRiskReport(BaseModel):
    risk_report_id: str
    project_id: str
    action_intention_candidate_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    character_id: str
    tier: Literal["A", "B", "C", "D"]
    risk_level: Literal["none", "low", "medium", "high", "blocking"] = "low"
    risk_categories: list[str] = Field(default_factory=list)
    possible_forbidden_knowledge: bool = False
    possible_location_conflict: bool = False
    possible_relationship_conflict: bool = False
    possible_world_rule_conflict: bool = False
    possible_major_state_change: bool = False
    possible_apparent_contradiction: bool = False
    primary_next_gate: str = ""
    recommended_next_gates: list[
        Literal[
            "continuity_gate",
            "apparent_gate",
            "quality_gate",
            "user_confirmation_candidate",
            "none",
        ]
    ] = Field(default_factory=list)
    does_not_resolve_issue: bool = True
    candidate_only: bool = True
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = CHARACTER_INTENT_VERSION_ID

    @validator("risk_categories", "warnings", pre=True)
    def risk_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("recommended_next_gates", pre=True)
    def gates_must_be_unique_known_values(cls, value: Any) -> list[str]:
        gates = _unique_strings(_as_list(value))
        if not gates:
            return ["none"]
        unknown = [gate for gate in gates if gate not in RECOMMENDED_GATES]
        if unknown:
            raise ValueError("recommended_next_gates contains unknown gate values.")
        if "none" in gates and len(gates) > 1:
            return [gate for gate in gates if gate != "none"]
        return gates

    @validator("does_not_resolve_issue")
    def cannot_resolve_issue(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M6 risk reports must not resolve issues.")
        return True

    @validator("candidate_only")
    def risk_report_candidate_only(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M6 risk reports must remain candidate-only.")
        return True


class TieredCharacterIntentPackage(BaseModel):
    tiered_character_intent_package_id: str
    project_id: str
    scene_participation_package_id: str
    tiered_character_context_package_id: str
    scene_memory_pack_id: str
    chapter_memory_pack_id: str = ""
    chapter_id: str
    scene_id: str
    scene_index: int
    active_character_ids: list[str] = Field(default_factory=list)
    psychology_trace_ids: list[str] = Field(default_factory=list)
    psychology_trace_runtime_meta_ids: list[str] = Field(default_factory=list)
    action_intention_candidate_ids: list[str] = Field(default_factory=list)
    risk_report_ids: list[str] = Field(default_factory=list)
    a_trace_count: int = 0
    b_trace_count: int = 0
    c_trace_count: int = 0
    d_trace_count: int = 0
    writer_ready_candidate_ids: list[str] = Field(default_factory=list)
    blocked_candidate_ids: list[str] = Field(default_factory=list)
    needs_gate_candidate_ids: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    no_story_fact_written: bool = True
    does_not_create_story_information: bool = True
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str
    status: Literal["ready", "warning", "blocked"] = "ready"
    created_at: str = ""
    updated_at: str = ""
    version_id: str = CHARACTER_INTENT_VERSION_ID

    @validator(
        "active_character_ids",
        "psychology_trace_ids",
        "psychology_trace_runtime_meta_ids",
        "action_intention_candidate_ids",
        "risk_report_ids",
        "writer_ready_candidate_ids",
        "blocked_candidate_ids",
        "needs_gate_candidate_ids",
        "warnings",
        pre=True,
    )
    def package_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("candidate_only", "no_story_fact_written", "does_not_create_story_information")
    def package_safety_flags_must_stay_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M6 intent package safety flags must remain true.")
        return True


class CharacterIntentGenerationPolicy(BaseModel):
    policy_id: str = "phase85b_m6_default_policy"
    project_id: str = "local_project"
    a_trace_depth: Literal["full"] = "full"
    b_trace_depth: Literal["medium"] = "medium"
    c_trace_depth: Literal["compact"] = "compact"
    d_trace_depth: Literal["minimal"] = "minimal"
    max_action_candidates_by_tier: dict[str, int] = Field(
        default_factory=lambda: {"A": 3, "B": 2, "C": 2, "D": 1}
    )
    all_outputs_candidate_only: bool = True
    no_direct_fact_write: bool = True
    requires_gate_for_state_changing_actions: bool = True
    allow_unselected_character_generation: bool = False
    allow_writer_invocation: bool = False
    allow_story_information_write: bool = False
    created_at: str = ""
    updated_at: str = ""
    version_id: str = CHARACTER_INTENT_VERSION_ID

    @validator("max_action_candidates_by_tier")
    def candidate_limits_must_cover_tiers(cls, value: dict[str, int]) -> dict[str, int]:
        limits = {str(key).upper(): int(limit) for key, limit in dict(value or {}).items()}
        for tier, default in {"A": 3, "B": 2, "C": 2, "D": 1}.items():
            if int(limits.get(tier, 0)) < 1:
                limits[tier] = default
        return {tier: limits[tier] for tier in ["A", "B", "C", "D"]}

    @validator(
        "all_outputs_candidate_only",
        "no_direct_fact_write",
        "requires_gate_for_state_changing_actions",
    )
    def required_policy_true_flags(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M6 default policy safety true flags cannot be disabled.")
        return True

    @validator(
        "allow_unselected_character_generation",
        "allow_writer_invocation",
        "allow_story_information_write",
    )
    def required_policy_false_flags(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("M6 default policy forbidden capabilities cannot be enabled.")
        return False


class CharacterIntentPackageBuildRequest(BaseModel):
    scene_participation_package_id: str
    force_refresh: bool = False


class CharacterIntentPackageBuildResponse(BaseModel):
    package: TieredCharacterIntentPackage
    psychology_traces: list[CharacterPsychologyTrace] = Field(default_factory=list)
    psychology_trace_runtime_meta: list[CharacterPsychologyTraceRuntimeMeta] = Field(default_factory=list)
    action_intention_candidates: list[CharacterActionIntentionCandidate] = Field(default_factory=list)
    risk_reports: list[CharacterIntentRiskReport] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CharacterIntentPackageReadResponse(BaseModel):
    package: Optional[TieredCharacterIntentPackage] = None
    psychology_traces: list[CharacterPsychologyTrace] = Field(default_factory=list)
    psychology_trace_runtime_meta: list[CharacterPsychologyTraceRuntimeMeta] = Field(default_factory=list)
    action_intention_candidates: list[CharacterActionIntentionCandidate] = Field(default_factory=list)
    risk_reports: list[CharacterIntentRiskReport] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CharacterIntentPolicyResponse(BaseModel):
    policy: CharacterIntentGenerationPolicy


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
