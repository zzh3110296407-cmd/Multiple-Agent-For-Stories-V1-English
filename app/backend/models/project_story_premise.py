from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


PROJECT_STORY_PREMISE_SCHEMA_VERSION = "phase85_m1_project_story_premise_v1"


class PromptSourceRef(BaseModel):
    project_origin_metadata_id: str = ""
    project_creation_request_id: str = ""
    source_prompt_ref: str = ""
    story_setup_prompt_id: str = ""
    controlled_prompt_text_ref: str = ""
    story_setup_handoff_id: str = ""


class PromptFidelityContract(BaseModel):
    required_markers: list[str] = Field(default_factory=list)
    forbidden_markers: list[str] = Field(default_factory=list)
    meta_markers: list[str] = Field(default_factory=list)
    marker_counts: dict[str, int] = Field(default_factory=dict)
    forbidden_demo_defaults: list[str] = Field(default_factory=list)
    demo_default_count: int = 0
    required_terms_present: dict[str, bool] = Field(default_factory=dict)


class ProjectStoryPremise(BaseModel):
    project_id: str
    origin_type: str = "prompt_first"
    source_status: str = "controlled_prompt"
    source_refs: PromptSourceRef = Field(default_factory=PromptSourceRef)
    user_story_premise: str = ""
    safe_user_story_summary: str = ""
    core_terms: list[str] = Field(default_factory=list)
    setting_terms: list[str] = Field(default_factory=list)
    conflict_terms: list[str] = Field(default_factory=list)
    role_terms: list[str] = Field(default_factory=list)
    required_story_elements: list[str] = Field(default_factory=list)
    prompt_markers_detected: list[str] = Field(default_factory=list)
    forbidden_demo_defaults: list[str] = Field(default_factory=list)
    demo_default_leak_detected: bool = False
    prompt_fidelity_contract: PromptFidelityContract = Field(default_factory=PromptFidelityContract)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = PROJECT_STORY_PREMISE_SCHEMA_VERSION


class ProjectStoryPremiseReadiness(BaseModel):
    project_id: str = ""
    readiness_status: str = "missing"
    source_status: str = "missing"
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class ProjectStoryPremiseResponse(BaseModel):
    active_project_id: str = ""
    readiness: ProjectStoryPremiseReadiness
    premise: Optional[ProjectStoryPremise] = None
    safe_summary: str = ""
    source_refs: dict[str, Any] = Field(default_factory=dict)
