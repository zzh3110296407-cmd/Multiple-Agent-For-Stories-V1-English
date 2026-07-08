from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import SourceSpecificity, validate_evidence_refs


TrackerType = Literal["foreshadowing", "mystery", "relationship_debt", "world_rule_reveal"]
TrackerStatus = Literal["open", "partially_resolved", "resolved", "abandoned", "uncertain"]


class TrackerCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_type: TrackerType
    content: str
    candidate_action: Literal["plant", "reinforce", "surface", "resolve", "abandon"]
    possible_existing_item_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_evidence_refs(value)


class TrackerPlant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_index: int = Field(ge=1)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_evidence_refs(value)


class TrackerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_index: int = Field(ge=1)
    update_type: Literal["reinforced", "surfaced", "resolved", "abandoned", "corrected"]
    content: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_evidence_refs(value)


class ManualOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool = False
    status: TrackerStatus | None = None
    resolved_chapter_index: int | None = Field(default=None, ge=1)
    resolution_method: str | None = None
    reason: str | None = None
    updated_at: str | None = None


class TrackerItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracker_item_id: str
    tracker_type: TrackerType
    canonical_content: str
    source_specificity: SourceSpecificity
    status: TrackerStatus
    planted: TrackerPlant
    updates: list[TrackerUpdate] = Field(default_factory=list)
    resolved: TrackerUpdate | None = None
    manual_override: ManualOverride = Field(default_factory=ManualOverride)
    candidate_history_refs: list[str] = Field(default_factory=list)
