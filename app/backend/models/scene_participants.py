from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, validator


class SceneRoleFunctionNeedRef(BaseModel):
    need_ref_id: str
    source_need_id: str
    project_id: str
    chapter_id: str
    scene_index: Optional[int] = None
    tier_preference: Literal["C", "D", "C_or_D"] = "C_or_D"
    function_type: str = "other"
    function_summary: str
    reason: str
    location_hint: str = ""
    relationship_hint: str = ""
    knowledge_need: str = ""
    reuse_existing_preferred: bool = True


class SceneRoleCandidate(BaseModel):
    candidate_id: str
    project_id: str
    chapter_id: str
    scene_index: int
    source_need_id: Optional[str] = None
    candidate_source: Literal["existing_confirmed_role", "new_role_candidate"]
    character_id: Optional[str] = None
    generated_role_candidate_id: Optional[str] = None
    tier: Literal["C", "D"]
    role_label: str
    function_type: str = "other"
    match_score: Literal["high", "medium", "low"] = "medium"
    match_reasons: list[str] = Field(default_factory=list)
    location_match: bool = False
    relationship_match: bool = False
    memory_match: bool = False
    function_match: bool = False
    continuity_risk: Literal["low", "medium", "high"] = "low"
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str


class SceneParticipantSelection(BaseModel):
    selection_id: str
    project_id: str
    chapter_id: str
    scene_index: int
    scene_id: Optional[str] = None
    selected_a_ids: list[str] = Field(default_factory=list)
    selected_b_ids: list[str] = Field(default_factory=list)
    selected_c_ids: list[str] = Field(default_factory=list)
    selected_d_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    source_need_ids: list[str] = Field(default_factory=list)
    selection_reasons: dict[str, str] = Field(default_factory=dict)
    rejected_candidate_reasons: dict[str, str] = Field(default_factory=dict)
    max_c_count: int = 2
    max_d_count: int = 3
    status: Literal[
        "draft",
        "ready_for_scene_context",
        "needs_user_confirmation",
        "blocked",
        "cancelled",
    ] = "draft"
    requires_user_confirmation: bool = False
    does_not_write_story_facts: bool = True
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    source_query_signature: str = ""
    created_at: str
    updated_at: str

    @validator("max_c_count", "max_d_count")
    def count_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))


class SceneCDRoleReuseDecision(BaseModel):
    reuse_decision_id: str
    selection_id: str
    project_id: str
    character_id: str
    tier: Literal["C", "D"]
    source_need_id: Optional[str] = None
    reuse_reason: str
    matched_memory_ids: list[str] = Field(default_factory=list)
    matched_relationship_ids: list[str] = Field(default_factory=list)
    matched_location_refs: list[str] = Field(default_factory=list)
    continuity_notes: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    created_at: str


class SceneCDRoleCreationCandidate(BaseModel):
    creation_candidate_id: str
    project_id: str
    selection_id: str
    chapter_id: str
    scene_index: int
    source_need_id: Optional[str] = None
    target_tier: Literal["C", "D"]
    role_label: str
    story_function: str
    minimal_profile: dict[str, Any] = Field(default_factory=dict)
    required_scene_function: str
    status: Literal["pending", "confirmed", "rejected", "superseded"] = "pending"
    requires_user_confirmation: bool = True
    does_not_enter_story_until_confirmed: bool = True
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class SceneParticipantSelectionReport(BaseModel):
    report_id: str
    project_id: str
    selection_id: str
    chapter_id: str
    scene_index: int
    selected_existing_count: int = 0
    new_candidate_count: int = 0
    rejected_candidate_count: int = 0
    unselected_c_d_count: int = 0
    all_selected_have_reasons: bool = False
    unselected_not_in_context: bool = True
    no_story_fact_written: bool = True
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str


class SceneParticipantSelectionRequest(BaseModel):
    chapter_id: str
    scene_index: int
    scene_id: Optional[str] = None
    scene_goal: str = ""
    scene_location: str = ""
    previous_scene_result: str = ""
    max_c_count: int = 2
    max_d_count: int = 3
    force_refresh: bool = False

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("scene_index must be positive.")
        return int(value)


class SceneParticipantSelectionResponse(BaseModel):
    selection: Optional[SceneParticipantSelection] = None
    role_needs: list[SceneRoleFunctionNeedRef] = Field(default_factory=list)
    candidates: list[SceneRoleCandidate] = Field(default_factory=list)
    creation_candidates: list[SceneCDRoleCreationCandidate] = Field(default_factory=list)
    confirmed_character_ids: list[str] = Field(default_factory=list)
    reuse_decisions: list[SceneCDRoleReuseDecision] = Field(default_factory=list)
    report: Optional[SceneParticipantSelectionReport] = None
    warnings: list[str] = Field(default_factory=list)
