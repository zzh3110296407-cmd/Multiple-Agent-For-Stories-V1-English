from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ArcLevel = Literal["major_arc", "sub_arc"]
ArcReviewStatus = Literal["pending_user_review", "user_confirmed", "rejected", "superseded"]


class ArcCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arc_candidate_id: str
    arc_level: ArcLevel
    parent_candidate_id: str | None = None
    chapters_included: list[int] = Field(default_factory=list)
    stage_goal: str = ""
    stage_question: str = ""
    dominant_conflict: str = ""
    dominant_reader_experience: str = ""
    entry_state: dict[str, Any] = Field(default_factory=dict)
    exit_state: dict[str, Any] = Field(default_factory=dict)
    turning_points: list[dict[str, Any]] = Field(default_factory=list)
    why_boundary_starts_here: str = ""
    why_boundary_ends_here: str = ""
    boundary_score: float = Field(default=0.0, ge=0.0, le=1.0)
    boundary_signals: list[str] = Field(default_factory=list)
    review_status: ArcReviewStatus = "pending_user_review"
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)


class ArcUserEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["split", "merge", "move_boundary", "rename", "change_parent"]
    target_arc_id: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    edited_at: str = ""


class ArcReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "story_analyzer.arc_review.v1"
    status: Literal["pending_user_review", "user_confirmed", "auto_confirmed"] = "pending_user_review"
    candidate_version: int = Field(default=1, ge=1)
    confirmed_version: int = Field(default=0, ge=0)
    candidate_arcs_ref: str = "arcs/arc_candidates.json"
    confirmed_major_arcs_ref: str = "arcs/major_arcs.json"
    confirmed_sub_arcs_ref: str = "arcs/sub_arcs.json"
    user_edits: list[ArcUserEdit] = Field(default_factory=list)
