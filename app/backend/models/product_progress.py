from typing import Optional

from pydantic import BaseModel, Field


PRODUCT_PROGRESS_SCHEMA_VERSION = "phase8_m6_product_progress_v1"


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class ProductModeProfile(BaseModel):
    mode_profile_id: str = "ordinary"
    display_name: str = "Ordinary"
    ordinary_mode: bool = True
    expert_mode: bool = False
    display_preference_only: bool = True
    permission_authority: bool = False
    debug_mutation_authority: bool = False
    source_preference_ref: str = ""
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_PROGRESS_SCHEMA_VERSION


class PatchProductModeProfileRequest(StrictModel):
    mode_profile_id: str


class ProductProgressSummary(BaseModel):
    project_id: Optional[str] = None
    active_project_id: Optional[str] = None
    summary_status: str = "unknown"
    current_stage_id: str = "unknown"
    current_stage_label: str = "Unknown"
    ordinary_summary: str = ""
    expert_summary_available: bool = False
    no_project: bool = False
    demo_project: bool = False
    model_status: str = "unknown"
    origin_type: str = "none"
    origin_badge_label: str = ""
    source_authority_refs: list[str] = Field(default_factory=list)
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    does_not_confirm_decision: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_PROGRESS_SCHEMA_VERSION


class NextRecommendedAction(BaseModel):
    action_id: str
    action_kind: str = "navigate"
    title: str
    reason: str
    target_workspace_id: str = "home"
    target_route_path: str = "/"
    blocked: bool = False
    blocked_reason: str = ""
    required_confirmation: bool = False
    priority: int = 50
    source_authority_refs: list[str] = Field(default_factory=list)
    does_not_execute: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_PROGRESS_SCHEMA_VERSION


class UserDecisionSurface(BaseModel):
    decision_surface_id: str
    decision_kind: str
    title: str
    reason: str
    target_workspace_id: str = "home"
    target_route_path: str = "/"
    existing_decision_ref: str = ""
    required_confirmation: bool = True
    does_not_create_decision: bool = True
    safe_summary: str = ""
    source_authority_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_PROGRESS_SCHEMA_VERSION


class BlockingIssueSurface(BaseModel):
    blocking_issue_surface_id: str
    issue_kind: str
    title: str
    reason: str
    severity: str = "blocking"
    target_workspace_id: str = "home"
    target_route_path: str = "/"
    source_authority_refs: list[str] = Field(default_factory=list)
    does_not_create_or_resolve_issue: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_PROGRESS_SCHEMA_VERSION


class ExpertEvidenceLink(BaseModel):
    evidence_link_id: str
    source_kind: str
    source_ref: str
    source_label: str
    safe_summary: str
    hash_or_count: str = ""
    status: str = "unknown"
    target_workspace_id: str = "expert_diagnostics"
    safe_reference_only: bool = True
    raw_payload_included: bool = False
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_PROGRESS_SCHEMA_VERSION


class ProductProgressSafetyReport(BaseModel):
    passed: bool = True
    audit_view_only: bool = True
    progress_is_view_model_only: bool = True
    no_story_fact_write: bool = True
    no_decision_auto_creation: bool = True
    no_issue_auto_creation: bool = True
    no_debug_raw_payload_in_ordinary_mode: bool = True
    no_raw_prompt: bool = True
    no_raw_response: bool = True
    no_hidden_reasoning: bool = True
    no_api_key: bool = True
    no_authorization_header: bool = True
    no_full_story_prose: bool = True
    no_full_screenplay_text: bool = True
    no_final_package_full_content: bool = True
    no_plugin_output_full_content: bool = True
    no_debug_mutation: bool = True
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""
    version_id: str = PRODUCT_PROGRESS_SCHEMA_VERSION


class ProductProgressAggregateResponse(BaseModel):
    mode_profile: ProductModeProfile
    summary: ProductProgressSummary
    next_actions: list[NextRecommendedAction] = Field(default_factory=list)
    decision_surfaces: list[UserDecisionSurface] = Field(default_factory=list)
    blocking_issues: list[BlockingIssueSurface] = Field(default_factory=list)
    expert_evidence_links: list[ExpertEvidenceLink] = Field(default_factory=list)
    safety_report: ProductProgressSafetyReport
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    does_not_confirm_decision: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_PROGRESS_SCHEMA_VERSION
