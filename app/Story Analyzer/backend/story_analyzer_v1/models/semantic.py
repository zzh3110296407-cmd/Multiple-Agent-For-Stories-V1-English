from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import validate_evidence_refs
from .trackers import TrackerType


class RawSemanticStoryFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[dict[str, Any]] = Field(default_factory=list)
    character_state_changes: list[dict[str, Any]] = Field(default_factory=list)
    relationship_changes: list[dict[str, Any]] = Field(default_factory=list)
    world_facts_added: list[dict[str, Any]] = Field(default_factory=list)
    information_state_changes: list[dict[str, Any]] = Field(default_factory=list)
    reader_known_information: list[dict[str, Any]] = Field(default_factory=list)
    character_known_information: list[dict[str, Any]] = Field(default_factory=list)


class RawSemanticStructuralAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_function: dict[str, Any] = Field(default_factory=dict)
    dominant_reader_experience: dict[str, Any] = Field(default_factory=dict)
    conflict_function: dict[str, Any] = Field(default_factory=dict)
    pacing_density: dict[str, Any] = Field(default_factory=dict)
    information_release_method: dict[str, Any] = Field(default_factory=dict)
    ending_hook_type: dict[str, Any] = Field(default_factory=dict)
    macro_component_ids: list[str] = Field(default_factory=list)


class RawSemanticTrackerCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str | None = None
    candidate_type: TrackerType
    content: str
    candidate_action: Literal["plant", "reinforce", "surface", "resolve", "abandon"] = "plant"
    possible_existing_item_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_evidence_refs(value)


class RawSemanticChapterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "story_analyzer.raw_semantic_chapter.v1"
    chapter_id: str
    chapter_index: int | None = Field(default=None, ge=1)
    analyzer_id: str = "external_semantic_analyzer"
    source_text_sha256: str = ""
    chapter_summary: str = ""
    story_facts: RawSemanticStoryFacts = Field(default_factory=RawSemanticStoryFacts)
    structural_analysis: RawSemanticStructuralAnalysis = Field(default_factory=RawSemanticStructuralAnalysis)
    transferable_patterns: list[dict[str, Any]] = Field(default_factory=list)
    tracker_candidates: list[RawSemanticTrackerCandidate] = Field(default_factory=list)
    boundary_signals: dict[str, bool] = Field(default_factory=dict)
    quality_notes: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.6, ge=0.0, le=1.0)
