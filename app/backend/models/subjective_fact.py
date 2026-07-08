from typing import Any, Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.narrative_layer import NarrativeObjectReference


SUBJECTIVE_CANDIDATE_TYPES = {
    "claim",
    "perception",
    "psychology",
    "expression",
}
OBJECTIVE_CANDIDATE_TYPES = {"event", "state_change", "memory_record"}
CLAIM_TRUTH_STATUSES = {
    "unverified_claim",
    "lie",
    "rumor",
    "misinformation",
    "exaggeration",
    "self_deception",
    "unknown",
}
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
READER_EXPLANATION_POLICIES = {
    "explain_now",
    "subtle_hint",
    "defer",
    "do_not_explain_yet",
    "intentionally_open",
}


class SubjectiveClaimCandidate(BaseModel):
    candidate_id: str
    scene_id: str = ""
    chapter_id: str = ""
    character_id: str = ""
    claim_text: str = ""
    truth_status: str = "unverified_claim"
    objective_truth: Optional[bool] = None
    reader_visible: bool = True
    speaker_intent: str = ""
    source_expression_candidate_id: str = ""
    linked_narrative_intent_id: str = ""
    source_text_summary: str = ""
    source_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("truth_status")
    def truth_status_must_be_known(cls, value: str) -> str:
        return _require_known(value, CLAIM_TRUTH_STATUSES, "truth_status")


class SubjectivePerceptionCandidate(BaseModel):
    candidate_id: str
    scene_id: str = ""
    chapter_id: str = ""
    character_id: str = ""
    perceived_object_type: str = ""
    perceived_object_id: str = ""
    objective_state_summary: str = ""
    perceived_state_summary: str = ""
    perception_type: str = "unknown"
    reader_explanation_policy: str = "defer"
    linked_narrative_intent_id: str = ""
    source_text_summary: str = ""
    source_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("perception_type")
    def perception_type_must_be_known(cls, value: str) -> str:
        return _require_known(value, PERCEPTION_TYPES, "perception_type")

    @validator("reader_explanation_policy")
    def reader_policy_must_be_known(cls, value: str) -> str:
        return _require_known(
            value,
            READER_EXPLANATION_POLICIES,
            "reader_explanation_policy",
        )


class SubjectivePsychologyCandidate(BaseModel):
    candidate_id: str
    scene_id: str = ""
    chapter_id: str = ""
    character_id: str = ""
    surface_intention: str = ""
    inner_desire: str = ""
    fear: str = ""
    self_deception: str = ""
    suppressed_motive: str = ""
    psychological_pressure: str = ""
    action_tendency: str = ""
    confidence: float = 0.0
    source_narrative_intent_id: str = ""
    linked_expression_candidate_id: str = ""
    source_text_summary: str = ""
    source_refs: list[NarrativeObjectReference] = Field(default_factory=list)


class SubjectiveExpressionCandidate(BaseModel):
    candidate_id: str
    scene_id: str = ""
    chapter_id: str = ""
    character_id: str = ""
    psychology_candidate_id: str = ""
    spoken_claim_candidate_ids: list[str] = Field(default_factory=list)
    actual_action: str = ""
    external_behavior: str = ""
    silence_or_omission: str = ""
    deception_or_concealment: str = ""
    reader_inference_hint: str = ""
    source_text_summary: str = ""
    source_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("spoken_claim_candidate_ids", pre=True)
    def claim_ids_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class BlockedObjectiveFactCandidate(BaseModel):
    candidate_type: str
    original_candidate_id: str = ""
    reason: str = ""
    suggested_subjective_record_type: str = ""
    source_text_summary: str = ""
    linked_record_ids: list[str] = Field(default_factory=list)

    @validator("candidate_type")
    def candidate_type_must_be_known(cls, value: str) -> str:
        return _require_known(value, OBJECTIVE_CANDIDATE_TYPES, "candidate_type")

    @validator("suggested_subjective_record_type")
    def suggested_type_must_be_known_or_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return _require_known(
            text,
            SUBJECTIVE_CANDIDATE_TYPES,
            "suggested_subjective_record_type",
        )

    @validator("linked_record_ids", pre=True)
    def linked_record_ids_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class SubjectiveFactExtractionResult(BaseModel):
    scene_id: str = ""
    chapter_id: str = ""
    generation_trace_id: str = ""
    claim_candidates: list[SubjectiveClaimCandidate] = Field(default_factory=list)
    perception_candidates: list[SubjectivePerceptionCandidate] = Field(default_factory=list)
    psychology_trace_candidates: list[SubjectivePsychologyCandidate] = Field(default_factory=list)
    expression_record_candidates: list[SubjectiveExpressionCandidate] = Field(default_factory=list)
    blocked_objective_candidates: list[BlockedObjectiveFactCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_narrative_intent_ids: list[str] = Field(default_factory=list)
    source_refs: list[NarrativeObjectReference] = Field(default_factory=list)

    @validator("source_narrative_intent_ids", "warnings", pre=True)
    def string_lists_must_be_unique(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ObjectiveFactWriteDecision(BaseModel):
    allowed_event_candidates: list[dict[str, Any]] = Field(default_factory=list)
    allowed_state_change_candidates: list[dict[str, Any]] = Field(default_factory=list)
    allowed_memory_record_candidates: list[dict[str, Any]] = Field(default_factory=list)
    blocked_objective_candidates: list[BlockedObjectiveFactCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @validator("warnings", pre=True)
    def warning_list_must_be_unique(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class SubjectiveFactWriteResult(BaseModel):
    scene_id: str = ""
    chapter_id: str = ""
    generation_trace_id: str = ""
    claim_record_ids: list[str] = Field(default_factory=list)
    perception_state_record_ids: list[str] = Field(default_factory=list)
    psychology_trace_ids: list[str] = Field(default_factory=list)
    expression_record_ids: list[str] = Field(default_factory=list)
    blocked_objective_candidates: list[BlockedObjectiveFactCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_narrative_intent_ids: list[str] = Field(default_factory=list)

    @validator(
        "claim_record_ids",
        "perception_state_record_ids",
        "psychology_trace_ids",
        "expression_record_ids",
        "warnings",
        "source_narrative_intent_ids",
        pre=True,
    )
    def result_lists_must_be_unique(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @property
    def subjective_record_ids(self) -> list[str]:
        return _unique_strings(
            [
                *self.claim_record_ids,
                *self.perception_state_record_ids,
                *self.psychology_trace_ids,
                *self.expression_record_ids,
            ]
        )


def _require_known(value: Any, allowed_values: set[str], field_name: str) -> str:
    text = str(value or "").strip()
    if text not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return text


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
