from typing import Any, Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.narrative_layer import AllowedApparentContradiction


AUTHORIAL_INTENT_STATUSES = {
    "created",
    "skipped",
    "failed",
    "policy_rejected",
}
AUTHORIAL_INTENT_CONSTRAINT_STRENGTHS = {"soft_intent", "suggestion"}


class AuthorialIntentContext(BaseModel):
    project_id: str = "local_project"
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 1
    generation_trace_id: str = ""
    chapter_goal: str = ""
    chapter_framework_summary: str = ""
    scene_goal: str = ""
    scene_memory_pack_summary: str = ""
    must_use_memory_summaries: list[str] = Field(default_factory=list)
    forbidden_or_conflict_summaries: list[str] = Field(default_factory=list)
    active_character_summaries: list[str] = Field(default_factory=list)
    relationship_summaries: list[str] = Field(default_factory=list)
    style_profile: str = ""
    user_intent: str = ""
    previous_scene_summary: str = ""
    provisional_dependency_summary: str = ""


class AuthorialIntentAgentOutput(BaseModel):
    should_create_intent: bool = False
    skip_reason: str = ""
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

    class Config:
        extra = "allow"

    @validator("constraint_strength", pre=True)
    def constraint_strength_is_text(cls, value: Any) -> str:
        return str(value or "soft_intent").strip()

    @validator("allowed_apparent_contradictions", pre=True)
    def normalize_allowed_contradictions(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        raw_items = value if isinstance(value, list) else [value]
        normalized: list[Any] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            mapped = dict(item)
            if not mapped.get("contradiction_type"):
                mapped["contradiction_type"] = str(
                    mapped.get("device_type")
                    or mapped.get("surface_form")
                    or mapped.get("type")
                    or "other"
                )
            if not mapped.get("summary"):
                mapped["summary"] = " ".join(
                    str(part or "").strip()
                    for part in [
                        mapped.get("surface_form"),
                        mapped.get("intended_effect"),
                        mapped.get("hidden_reason"),
                    ]
                    if str(part or "").strip()
                )
            if not mapped.get("scope"):
                mapped["scope"] = str(mapped.get("scene_scope") or "scene")
            if not mapped.get("expected_gate_action"):
                mapped["expected_gate_action"] = "warn"
            normalized.append(mapped)
        return normalized


class AuthorialIntentResult(BaseModel):
    status: str
    narrative_intent_id: str = ""
    narrative_intent_summary: str = ""
    skip_reason: str = ""
    failure_reason: str = ""
    record: Optional[Any] = None

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        if value not in AUTHORIAL_INTENT_STATUSES:
            raise ValueError("AuthorialIntentResult.status is not allowed.")
        return value
