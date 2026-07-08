from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ChapterBoundaryStatus = Literal["ok", "suspicious", "failed"]
SchemaStatus = Literal["ok", "invalid_enum", "missing_required_field"]
ConsistencyStatus = Literal["ok", "suspicious", "failed"]
SemanticSource = Literal["llm_provider", "reviewed_json", "legacy_v2_adapter", "deterministic_fallback"]


class ChapterQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    chapter_boundary_status: ChapterBoundaryStatus = "ok"
    title_status: Literal["source_title", "inferred_title", "suspicious"] = "source_title"
    schema_status: SchemaStatus = "ok"
    character_consistency_status: ConsistencyStatus = "ok"
    tracker_consistency_status: ConsistencyStatus = "ok"
    requires_repair_pass: bool = False
    review_notes: list[str] = Field(default_factory=list)
    semantic_source: SemanticSource = "deterministic_fallback"
    semantic_analyzer_id: str = ""
    semantic_input_ref: str = ""
