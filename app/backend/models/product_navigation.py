from typing import Optional

from pydantic import BaseModel, Field


PRODUCT_NAVIGATION_SCHEMA_VERSION = "phase8_m5_product_navigation_v1"


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class ProductWorkspaceDefinition(BaseModel):
    workspace_id: str
    display_name: str
    group_id: str
    route_key: str
    workspace_kind: str = "workspace"
    default_visibility: str = "ordinary"
    ordinary_visible: bool = True
    expert_visible: bool = True
    requires_project: bool = False
    requires_active_model: bool = False
    requires_origin_review_clear: bool = False
    allowed_origin_types: list[str] = Field(default_factory=list)
    blocked_origin_types: list[str] = Field(default_factory=list)
    requires_final_story_package: bool = False
    requires_plugin_artifact: bool = False
    source_authority_refs: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    sort_order: int = 0
    version_id: str = PRODUCT_NAVIGATION_SCHEMA_VERSION


class ProductNavigationGroup(BaseModel):
    group_id: str
    display_name: str
    group_kind: str = "ordinary"
    ordinary_visible: bool = True
    expert_visible: bool = True
    workspace_ids: list[str] = Field(default_factory=list)
    sort_order: int = 0
    safe_summary: str = ""
    version_id: str = PRODUCT_NAVIGATION_SCHEMA_VERSION


class WorkspaceAvailabilityItem(BaseModel):
    workspace_id: str
    availability_status: str = "available"
    visibility: str = "ordinary_visible"
    can_access: bool = True
    blocked_reason: str = ""
    required_next_step: str = ""
    safe_redirect_workspace_id: str = ""
    project_id: Optional[str] = None
    origin_type: str = "none"
    origin_badge_label: str = ""
    source_authority_refs: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)


class WorkspaceAvailabilityReport(BaseModel):
    project_id: Optional[str] = None
    active_project_id: Optional[str] = None
    mode_profile_id: str = "ordinary"
    items: list[WorkspaceAvailabilityItem] = Field(default_factory=list)
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    generated_from_authorities: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_NAVIGATION_SCHEMA_VERSION


class WorkspaceModeProfile(BaseModel):
    mode_profile_id: str = "ordinary"
    display_name: str = "Ordinary"
    ordinary_default: bool = True
    expert_discoverable: bool = True
    debug_routes_visible: bool = False
    safe_summary: str = ""
    version_id: str = PRODUCT_NAVIGATION_SCHEMA_VERSION


class UserWorkspacePreference(BaseModel):
    preference_id: str = "product_navigation_preference_default"
    mode_profile_id: str = "ordinary"
    last_workspace_id: str = "home"
    collapsed_group_ids: list[str] = Field(default_factory=list)
    pinned_workspace_ids: list[str] = Field(default_factory=list)
    ui_preference_only: bool = True
    safe_summary: str = "Product navigation preference only; no story facts or artifacts."
    updated_at: str = ""
    version_id: str = PRODUCT_NAVIGATION_SCHEMA_VERSION


class PatchUserWorkspacePreferenceRequest(StrictModel):
    mode_profile_id: Optional[str] = None
    last_workspace_id: Optional[str] = None
    collapsed_group_ids: Optional[list[str]] = None
    pinned_workspace_ids: Optional[list[str]] = None


class CurrentProjectHeader(BaseModel):
    project_id: Optional[str] = None
    title: str = ""
    origin_type: str = "none"
    origin_badge_label: str = ""
    origin_requires_review: bool = False
    active_model_status: str = "unknown"
    safe_summary: str = ""


class ProductNavigationState(BaseModel):
    active_workspace_id: str = "home"
    selected_project_id: Optional[str] = None
    active_project_id: Optional[str] = None
    groups: list[ProductNavigationGroup] = Field(default_factory=list)
    workspaces: list[ProductWorkspaceDefinition] = Field(default_factory=list)
    availability: WorkspaceAvailabilityReport
    mode_profile: WorkspaceModeProfile
    preference: UserWorkspacePreference
    current_project_header: CurrentProjectHeader
    origin_badge: Optional[dict] = None
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_NAVIGATION_SCHEMA_VERSION


class ProductWorkspaceDefinitionsResponse(BaseModel):
    workspaces: list[ProductWorkspaceDefinition] = Field(default_factory=list)
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    version_id: str = PRODUCT_NAVIGATION_SCHEMA_VERSION


class ProductNavigationGroupsResponse(BaseModel):
    groups: list[ProductNavigationGroup] = Field(default_factory=list)
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    version_id: str = PRODUCT_NAVIGATION_SCHEMA_VERSION
