from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .quality import ChapterQuality
from .source import TitleSource


class CanonicalSourceMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_fingerprint_id: str
    input_title: str = ""
    normalized_title: str = ""
    title_source: TitleSource = "fallback"
    text_sha256: str
    text_length: int = Field(ge=0)
    original_chapter_id: str | None = None
    original_chapter_index: int | None = Field(default=None, ge=1)
    original_chapter_title: str | None = None
    part_index: int | None = Field(default=None, ge=1)
    part_count: int | None = Field(default=None, ge=1)
    part_start_char: int | None = Field(default=None, ge=0)
    part_end_char: int | None = Field(default=None, ge=0)


class StoryFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_summary: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)
    character_state_changes: list[dict[str, Any]] = Field(default_factory=list)
    relationship_changes: list[dict[str, Any]] = Field(default_factory=list)
    world_facts_added: list[dict[str, Any]] = Field(default_factory=list)
    information_state_changes: list[dict[str, Any]] = Field(default_factory=list)
    reader_known_information: list[dict[str, Any]] = Field(default_factory=list)
    character_known_information: list[dict[str, Any]] = Field(default_factory=list)


class StructuralAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_function: dict[str, Any] = Field(default_factory=dict)
    dominant_reader_experience: dict[str, Any] = Field(default_factory=dict)
    conflict_function: dict[str, Any] = Field(default_factory=dict)
    pacing_density: dict[str, Any] = Field(default_factory=dict)
    information_release_method: dict[str, Any] = Field(default_factory=dict)
    ending_hook_type: dict[str, Any] = Field(default_factory=dict)
    macro_component_ids: list[str] = Field(default_factory=list)


class BoundarySignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_changed: bool = False
    dominant_conflict_changed: bool = False
    setting_or_social_system_changed: bool = False
    major_question_answered: bool = False
    new_question_launched: bool = False
    identity_state_changed: bool = False
    reader_experience_shifted: bool = False
    time_or_space_jump: bool = False


class CanonicalChapterAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "story_analyzer.canonical_chapter.v1"
    chapter_id: str
    chapter_index: int = Field(ge=1)
    source: CanonicalSourceMeta
    story_facts: StoryFacts = Field(default_factory=StoryFacts)
    structural_analysis: StructuralAnalysis = Field(default_factory=StructuralAnalysis)
    transferable_patterns: list[dict[str, Any]] = Field(default_factory=list)
    tracker_candidates: list[dict[str, Any]] = Field(default_factory=list)
    boundary_signals: BoundarySignals = Field(default_factory=BoundarySignals)
    quality: ChapterQuality = Field(default_factory=ChapterQuality)
