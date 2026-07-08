from typing import Any, Optional

from pydantic import BaseModel, Field, root_validator, validator


LOCAL_PROJECT_ID = "local_project"
NARRATIVE_LAYER_VERSION_ID = "phase25_m1_narrative_layer_v1"

CLAIM_TRUTH_STATUSES = {
    "objective_fact",
    "unverified_claim",
    "lie",
    "rumor",
    "misinformation",
    "exaggeration",
    "self_deception",
    "unknown",
}
NON_OBJECTIVE_CLAIM_STATUSES = {
    "lie",
    "rumor",
    "misinformation",
    "exaggeration",
    "self_deception",
}
INTENT_SOURCE_TYPES = {
    "authorial_intent_agent",
    "user_declared",
    "system_inferred",
}
INTENT_TYPES = {
    "character_depth",
    "misdirection",
    "delayed_reveal",
    "hallucination",
    "unreliable_perception",
    "unreliable_claim",
    "psychological_contradiction",
    "foreshadowing",
    "open_ambiguity",
    "symbolic_unresolved",
    "other",
}
INTENT_CONSTRAINT_STRENGTHS = {"soft_intent", "suggestion"}
READER_EXPLANATION_POLICIES = {
    "explain_now",
    "subtle_hint",
    "defer",
    "do_not_explain_yet",
    "intentionally_open",
}
PSYCHOLOGY_INTERPRETATION_STATUSES = {
    "candidate",
    "used_in_expression",
    "rejected",
    "user_confirmed",
}
READER_VISIBLE_LEVELS = {"hidden", "subtle", "visible_summary"}
PERCEPTION_TYPES = {
    "hallucination",
    "dream",
    "vision",
    "misrecognition",
    "unreliable_perception",
    "magic_influence",
    "trauma_response",
    "unknown",
}
APPARENT_CONTRADICTION_CLASSIFICATIONS = {
    "intentional_narrative_device",
    "acceptable_ambiguity",
    "needs_user_confirmation",
    "true_continuity_error",
    "unknown",
}
QUALITY_GATE_ACTIONS = {
    "do_not_block",
    "warn",
    "require_user_confirmation",
    "block",
}
NARRATIVE_DEBT_TYPES = {
    "foreshadowing",
    "misdirection",
    "hallucination",
    "delayed_explanation",
    "psychological_contradiction",
    "unreliable_claim",
    "open_ambiguity",
    "symbolic_unresolved",
    "other",
}
NARRATIVE_DEBT_STATUSES = {
    "active",
    "paid_off",
    "expired",
    "intentionally_open",
    "rejected",
}


class NarrativeObjectReference(BaseModel):
    object_type: str
    object_id: str
    relation: str = ""

    @validator("object_type", "object_id", "relation", pre=True)
    def text_fields_must_be_strings(cls, value: Any) -> str:
        return str(value or "").strip()


class AllowedApparentContradiction(BaseModel):
    contradiction_type: str = "other"
    summary: str = ""
    scope: str = ""
    expected_gate_action: str = "warn"
    requires_narrative_debt: bool = False
    matched_record_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("expected_gate_action")
    def gate_action_must_be_known(cls, value: str) -> str:
        return _require_known(value, QUALITY_GATE_ACTIONS, "expected_gate_action")


class NarrativeLayerBase(BaseModel):
    project_id: str = LOCAL_PROJECT_ID
    chapter_id: str = ""
    scene_id: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    version_id: str = NARRATIVE_LAYER_VERSION_ID

    @validator("project_id", "chapter_id", "scene_id", "status", pre=True)
    def base_text_fields_must_be_strings(cls, value: Any) -> str:
        return str(value or "").strip()

    @root_validator(pre=True)
    def default_common_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        data = dict(values or {})
        data["project_id"] = str(data.get("project_id") or LOCAL_PROJECT_ID)
        data["status"] = str(data.get("status") or "active")
        data["version_id"] = str(
            data.get("version_id") or NARRATIVE_LAYER_VERSION_ID
        )
        return data


class ClaimRecord(NarrativeLayerBase):
    claim_id: str
    character_id: str = ""
    claim_text: str = ""
    truth_status: str = "unverified_claim"
    objective_truth: Optional[bool] = None
    reader_visible: bool = True
    speaker_intent: str = ""
    source_expression_record_id: str = ""
    objective_source_refs: list[NarrativeObjectReference] = Field(default_factory=list)
    linked_event_ids: list[str] = Field(default_factory=list)
    linked_memory_ids: list[str] = Field(default_factory=list)
    linked_decision_ids: list[str] = Field(default_factory=list)

    @validator("claim_id", "character_id", "claim_text", pre=True)
    def claim_text_fields_must_be_strings(cls, value: Any) -> str:
        return str(value or "").strip()

    @validator(
        "linked_event_ids",
        "linked_memory_ids",
        "linked_decision_ids",
        pre=True,
    )
    def claim_refs_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("truth_status")
    def truth_status_must_be_known(cls, value: str) -> str:
        return _require_known(value, CLAIM_TRUTH_STATUSES, "truth_status")


class NarrativeIntentRecord(NarrativeLayerBase):
    narrative_intent_id: str
    source_type: str = "user_declared"
    intent_type: str = "other"
    summary: str = ""
    constraint_strength: str = "soft_intent"
    allowed_apparent_contradictions: list[AllowedApparentContradiction] = Field(
        default_factory=list
    )
    reader_explanation_policy: str = "defer"
    payoff_required: bool = False
    open_ambiguity_allowed: bool = False
    symbolic_unresolved: bool = False
    payoff_deadline_type: str = ""
    payoff_deadline_chapter_id: str = ""
    payoff_deadline_scene_index: Optional[int] = None
    payoff_deadline_note: str = ""
    created_before_scene_output: bool = True
    generation_trace_id: str = ""
    source_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("source_type")
    def source_type_must_be_known(cls, value: str) -> str:
        return _require_known(value, INTENT_SOURCE_TYPES, "source_type")

    @validator("intent_type")
    def intent_type_must_be_known(cls, value: str) -> str:
        return _require_known(value, INTENT_TYPES, "intent_type")

    @validator("constraint_strength")
    def constraint_strength_must_be_soft(cls, value: str) -> str:
        if value not in INTENT_CONSTRAINT_STRENGTHS:
            raise ValueError("NarrativeIntentRecord does not allow hard constraints.")
        return value

    @validator("reader_explanation_policy")
    def reader_policy_must_be_known(cls, value: str) -> str:
        return _require_known(
            value,
            READER_EXPLANATION_POLICIES,
            "reader_explanation_policy",
        )


class CharacterPsychologyTrace(NarrativeLayerBase):
    psychology_trace_id: str
    character_id: str = ""
    surface_intention: str = ""
    inner_desire: str = ""
    fear: str = ""
    self_deception: str = ""
    suppressed_motive: str = ""
    psychological_pressure: str = ""
    action_tendency: str = ""
    interpretation_status: str = "candidate"
    confidence: float = 0.0
    reader_visible_level: str = "hidden"
    source_narrative_intent_id: str = ""
    linked_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("interpretation_status")
    def interpretation_status_must_be_known(cls, value: str) -> str:
        return _require_known(
            value,
            PSYCHOLOGY_INTERPRETATION_STATUSES,
            "interpretation_status",
        )

    @validator("reader_visible_level")
    def reader_visible_level_must_be_known(cls, value: str) -> str:
        return _require_known(value, READER_VISIBLE_LEVELS, "reader_visible_level")


class CharacterExpressionRecord(NarrativeLayerBase):
    expression_record_id: str
    character_id: str = ""
    psychology_trace_id: str = ""
    spoken_claim_ids: list[str] = Field(default_factory=list)
    actual_action: str = ""
    external_behavior: str = ""
    silence_or_omission: str = ""
    deception_or_concealment: str = ""
    reader_inference_hint: str = ""
    linked_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("spoken_claim_ids", pre=True)
    def spoken_claim_ids_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class PerceptionStateRecord(NarrativeLayerBase):
    perception_state_id: str
    character_id: str = ""
    perceived_object_type: str = ""
    perceived_object_id: str = ""
    objective_state_summary: str = ""
    perceived_state_summary: str = ""
    perception_type: str = "unknown"
    reader_explanation_policy: str = "defer"
    linked_narrative_intent_id: str = ""
    linked_narrative_debt_id: str = ""
    objective_state_refs: list[NarrativeObjectReference] = Field(default_factory=list)
    perceived_state_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("perception_type")
    def perception_type_must_be_known(cls, value: str) -> str:
        return _require_known(value, PERCEPTION_TYPES, "perception_type")

    @validator("reader_explanation_policy")
    def perception_reader_policy_must_be_known(cls, value: str) -> str:
        return _require_known(
            value,
            READER_EXPLANATION_POLICIES,
            "reader_explanation_policy",
        )


class ApparentContradictionRecord(NarrativeLayerBase):
    apparent_contradiction_id: str
    source_issue_id: str = ""
    surface_contradiction: str = ""
    classification: str = "unknown"
    device_type: str = ""
    matched_claim_ids: list[str] = Field(default_factory=list)
    matched_narrative_intent_ids: list[str] = Field(default_factory=list)
    matched_psychology_trace_ids: list[str] = Field(default_factory=list)
    matched_expression_record_ids: list[str] = Field(default_factory=list)
    matched_perception_state_ids: list[str] = Field(default_factory=list)
    matched_narrative_debt_ids: list[str] = Field(default_factory=list)
    matched_refs: list[NarrativeObjectReference] = Field(default_factory=list)
    quality_gate_action: str = "warn"
    tracking_action: str = ""

    @validator("classification")
    def classification_must_be_known(cls, value: str) -> str:
        return _require_known(
            value,
            APPARENT_CONTRADICTION_CLASSIFICATIONS,
            "classification",
        )

    @validator("quality_gate_action")
    def contradiction_gate_action_must_be_known(cls, value: str) -> str:
        return _require_known(value, QUALITY_GATE_ACTIONS, "quality_gate_action")

    @validator(
        "matched_claim_ids",
        "matched_narrative_intent_ids",
        "matched_psychology_trace_ids",
        "matched_expression_record_ids",
        "matched_perception_state_ids",
        "matched_narrative_debt_ids",
        pre=True,
    )
    def matched_ids_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class NarrativeDebt(NarrativeLayerBase):
    narrative_debt_id: str
    source_scene_id: str = ""
    source_narrative_intent_id: str = ""
    source_apparent_contradiction_id: str = ""
    debt_type: str = "other"
    summary: str = ""
    payoff_required: bool = False
    open_ambiguity_allowed: bool = False
    symbolic_unresolved: bool = False
    payoff_deadline_type: str = ""
    payoff_deadline_chapter_id: str = ""
    payoff_deadline_scene_index: Optional[int] = None
    payoff_deadline_note: str = ""
    payoff_scene_id: str = ""
    user_decision_id: str = ""
    source_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("debt_type")
    def debt_type_must_be_known(cls, value: str) -> str:
        return _require_known(value, NARRATIVE_DEBT_TYPES, "debt_type")

    @validator("status")
    def debt_status_must_be_known(cls, value: str) -> str:
        return _require_known(value, NARRATIVE_DEBT_STATUSES, "status")


class ClaimRecordCreateRequest(BaseModel):
    record: ClaimRecord


class NarrativeIntentCreateRequest(BaseModel):
    record: NarrativeIntentRecord


class CharacterPsychologyTraceCreateRequest(BaseModel):
    record: CharacterPsychologyTrace


class CharacterExpressionRecordCreateRequest(BaseModel):
    record: CharacterExpressionRecord


class PerceptionStateRecordCreateRequest(BaseModel):
    record: PerceptionStateRecord


class ApparentContradictionCreateRequest(BaseModel):
    record: ApparentContradictionRecord


class NarrativeDebtCreateRequest(BaseModel):
    record: NarrativeDebt


class NarrativeRecordUpdateRequest(BaseModel):
    record: dict[str, Any] = Field(default_factory=dict)


class NarrativeLayerSceneRecords(BaseModel):
    success: bool = True
    scene_id: str
    claim_records: list[ClaimRecord] = Field(default_factory=list)
    narrative_intent_records: list[NarrativeIntentRecord] = Field(default_factory=list)
    character_psychology_traces: list[CharacterPsychologyTrace] = Field(default_factory=list)
    character_expression_records: list[CharacterExpressionRecord] = Field(default_factory=list)
    perception_state_records: list[PerceptionStateRecord] = Field(default_factory=list)
    apparent_contradiction_records: list[ApparentContradictionRecord] = Field(default_factory=list)
    narrative_debts: list[NarrativeDebt] = Field(default_factory=list)


class NarrativeDebtListResponse(BaseModel):
    success: bool = True
    debts: list[NarrativeDebt] = Field(default_factory=list)
    count: int = 0


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


def _require_known(value: Any, allowed_values: set[str], field_name: str) -> str:
    text = str(value or "").strip()
    if text not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return text
