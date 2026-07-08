from typing import Any

from pydantic import BaseModel, Field, validator

from app.backend.models.continuity import ContinuityIssue
from app.backend.models.narrative_layer import (
    ApparentContradictionRecord,
    CharacterExpressionRecord,
    CharacterPsychologyTrace,
    ClaimRecord,
    NarrativeDebt,
    NarrativeIntentRecord,
    NarrativeObjectReference,
    PerceptionStateRecord,
)


APPARENT_CLASSIFICATIONS = {
    "intentional_narrative_device",
    "acceptable_ambiguity",
    "needs_user_confirmation",
    "true_continuity_error",
    "unknown",
}
APPARENT_GATE_ACTIONS = {
    "do_not_block",
    "warn",
    "require_user_confirmation",
    "block",
}
EVIDENCE_STRENGTHS = {"strong", "medium", "weak", "counter_evidence"}
TRACKING_ACTIONS = {
    "none",
    "create_narrative_debt",
    "update_narrative_debt",
}


class MatchedNarrativeEvidence(BaseModel):
    evidence_type: str
    evidence_id: str
    relation: str = ""
    strength: str = "weak"
    reason: str = ""

    @validator("strength")
    def strength_must_be_known(cls, value: str) -> str:
        return _require_known(value, EVIDENCE_STRENGTHS, "strength")


class ApparentContradictionContext(BaseModel):
    scene_id: str = ""
    chapter_id: str = ""
    target_type: str = "scene"
    target_id: str = ""
    revision_id: str = ""
    generation_trace_id: str = ""
    issues: list[ContinuityIssue] = Field(default_factory=list)
    claim_records: list[ClaimRecord] = Field(default_factory=list)
    perception_records: list[PerceptionStateRecord] = Field(default_factory=list)
    psychology_traces: list[CharacterPsychologyTrace] = Field(default_factory=list)
    expression_records: list[CharacterExpressionRecord] = Field(default_factory=list)
    narrative_intents: list[NarrativeIntentRecord] = Field(default_factory=list)
    narrative_debts: list[NarrativeDebt] = Field(default_factory=list)
    existing_apparent_contradictions: list[ApparentContradictionRecord] = Field(
        default_factory=list
    )
    user_decisions: list[dict[str, Any]] = Field(default_factory=list)
    objective_refs: list[NarrativeObjectReference] = Field(default_factory=list)
    safe_scene_summary: str = ""


class ApparentContradictionClassificationResult(BaseModel):
    issue_id: str
    classification: str = "unknown"
    device_type: str = ""
    quality_gate_action: str = "block"
    matched_claim_ids: list[str] = Field(default_factory=list)
    matched_narrative_intent_ids: list[str] = Field(default_factory=list)
    matched_psychology_trace_ids: list[str] = Field(default_factory=list)
    matched_expression_record_ids: list[str] = Field(default_factory=list)
    matched_perception_state_ids: list[str] = Field(default_factory=list)
    matched_narrative_debt_ids: list[str] = Field(default_factory=list)
    matched_refs: list[NarrativeObjectReference] = Field(default_factory=list)
    matched_evidence: list[MatchedNarrativeEvidence] = Field(default_factory=list)
    evidence_strength: str = "weak"
    safe_user_summary: str = ""
    internal_reason: str = ""
    tracking_action: str = "none"

    @validator("classification")
    def classification_must_be_known(cls, value: str) -> str:
        return _require_known(value, APPARENT_CLASSIFICATIONS, "classification")

    @validator("quality_gate_action")
    def gate_action_must_be_known(cls, value: str) -> str:
        return _require_known(value, APPARENT_GATE_ACTIONS, "quality_gate_action")

    @validator("evidence_strength")
    def evidence_strength_must_be_known(cls, value: str) -> str:
        return _require_known(value, EVIDENCE_STRENGTHS, "evidence_strength")

    @validator("tracking_action")
    def tracking_action_must_be_known(cls, value: str) -> str:
        return _require_known(value, TRACKING_ACTIONS, "tracking_action")

    @validator(
        "matched_claim_ids",
        "matched_narrative_intent_ids",
        "matched_psychology_trace_ids",
        "matched_expression_record_ids",
        "matched_perception_state_ids",
        "matched_narrative_debt_ids",
        pre=True,
    )
    def id_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ApparentContradictionGateDecision(BaseModel):
    issue_id: str
    quality_gate_action: str = "block"
    severity: str = "blocking"
    blocks_final_confirmation: bool = True
    blocks_state_changing_revision_confirmation: bool = True
    requires_explicit_acceptance: bool = True
    acceptance_policy: str = "requires_strong_confirmation"

    @validator("quality_gate_action")
    def decision_gate_action_must_be_known(cls, value: str) -> str:
        return _require_known(value, APPARENT_GATE_ACTIONS, "quality_gate_action")


class ApparentContradictionGateResult(BaseModel):
    apparent_records: list[ApparentContradictionRecord] = Field(default_factory=list)
    issues_to_block: list[str] = Field(default_factory=list)
    issues_to_warn: list[str] = Field(default_factory=list)
    issues_requiring_user_confirmation: list[str] = Field(default_factory=list)
    issues_not_blocking: list[str] = Field(default_factory=list)
    created_narrative_debt_ids: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    classifications: list[ApparentContradictionClassificationResult] = Field(
        default_factory=list
    )
    decisions: list[ApparentContradictionGateDecision] = Field(default_factory=list)
    gated_issues: list[ContinuityIssue] = Field(default_factory=list)

    @validator(
        "issues_to_block",
        "issues_to_warn",
        "issues_requiring_user_confirmation",
        "issues_not_blocking",
        "created_narrative_debt_ids",
        pre=True,
    )
    def result_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


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
