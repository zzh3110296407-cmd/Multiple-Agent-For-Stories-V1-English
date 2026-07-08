from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


TitleSource = Literal["source", "filename", "inferred", "fallback"]
BoundaryStatus = Literal["ok", "suspicious", "failed"]
TitleStatus = Literal["source_title", "inferred_title", "suspicious"]


class ChapterSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_id: str
    chapter_index: int = Field(ge=1)
    source_title: str
    normalized_title: str
    title_source: TitleSource
    boundary_status: BoundaryStatus
    title_status: TitleStatus
    boundary_reason: list[str] = Field(default_factory=list)
    text_sha256: str
    text_length: int = Field(ge=0)
    source_file_path: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    original_chapter_id: str | None = None
    original_chapter_index: int | None = Field(default=None, ge=1)
    original_chapter_title: str | None = None
    part_index: int | None = Field(default=None, ge=1)
    part_count: int | None = Field(default=None, ge=1)
    part_start_char: int | None = Field(default=None, ge=0)
    part_end_char: int | None = Field(default=None, ge=0)

    @field_validator("chapter_id")
    @classmethod
    def chapter_id_matches_prefix(cls, value: str) -> str:
        if not value.startswith("chapter_"):
            raise ValueError("chapter_id must start with chapter_")
        return value


class SourceInputManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "story_analyzer.source_input_manifest.v1"
    work_title: str
    source_path: str
    source_sha256: str
    chapters: list[ChapterSource]

    @field_validator("chapters")
    @classmethod
    def has_chapters_with_unique_indexes(cls, value: list[ChapterSource]) -> list[ChapterSource]:
        if not value:
            raise ValueError("source manifest must contain at least one chapter")
        indexes = [chapter.chapter_index for chapter in value]
        if len(indexes) != len(set(indexes)):
            raise ValueError("chapter indexes must be unique")
        return value
