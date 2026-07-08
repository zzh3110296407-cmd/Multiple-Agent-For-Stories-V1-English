from typing import Any, Optional

from pydantic import BaseModel, Field


PROJECT_CREATION_SCHEMA_VERSION = "phase8_m2_project_creation_v1"


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class ProjectCreationMode(BaseModel):
    mode_id: str
    mode_type: str
    display_name: str
    enabled: bool = True
    status: str = "enabled"
    creates_real_user_project: bool = False
    creates_demo_project: bool = False
    requires_followup_setup: bool = True
    recommended_next_step: str = ""
    will_create_story_facts_now: bool = False
    required_user_input: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class ProjectCreationModesResponse(BaseModel):
    modes: list[ProjectCreationMode] = Field(default_factory=list)


class CreateProjectCreationRequest(StrictModel):
    mode_type: str
    requested_title: str = "Untitled Story Project"
    requested_language: str = "zh"
    prompt_text: Optional[str] = None
    template_id: Optional[str] = None
    analyze_stories_import_ref: Optional[str] = None
    demo_seed_id: Optional[str] = None
    existing_project_id: Optional[str] = None
    explicit_user_selection: bool = False


class ConfirmProjectCreationDraftRequest(StrictModel):
    safe_user_note: str = ""


class ProjectCreationRequest(BaseModel):
    creation_request_id: str
    mode_type: str
    requested_title: str
    requested_language: str
    prompt_text_ref: Optional[str] = None
    prompt_safe_summary: str = ""
    template_id: Optional[str] = None
    analyze_stories_import_ref: Optional[str] = None
    demo_seed_id: Optional[str] = None
    existing_project_id: Optional[str] = None
    explicit_user_selection: bool = False
    active_model_selection_id: Optional[str] = None
    active_model_provider_type: Optional[str] = None
    active_model_name: Optional[str] = None
    model_health_status_at_request: str = "unknown"
    request_status: str = "created"
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class ProjectCreationValidationReport(BaseModel):
    validation_report_id: str
    creation_request_id: str
    validation_status: str = "pending"
    can_create_project_shell: bool = False
    can_create_real_user_project: bool = False
    can_create_demo_project: bool = False
    active_model_available: bool = False
    active_model_warning: str = ""
    demo_seed_explicitly_selected: bool = False
    demo_seed_marker_required: bool = False
    analyze_stories_requires_import_gate: bool = False
    analyze_stories_auto_activation_blocked: bool = False
    template_requires_m4_instantiation: bool = False
    prompt_first_requires_m3_setup: bool = False
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class ProjectCreationDraft(BaseModel):
    creation_draft_id: str
    creation_request_id: str
    draft_status: str = "draft"
    proposed_project_id: str
    proposed_title: str
    proposed_language: str
    origin_type: str
    origin_metadata_id: str
    validation_report_id: str
    will_create_story_facts_now: bool = False
    will_create_demo_marker: bool = False
    will_require_followup_confirmation: bool = True
    recommended_next_step: str = ""
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class ProjectCreationDecision(BaseModel):
    creation_decision_id: str
    creation_request_id: str
    creation_draft_id: str
    decision_type: str = "confirm_creation_draft"
    decision_status: str = "confirmed"
    created_project_id: Optional[str] = None
    confirms_origin_metadata: bool = True
    confirms_demo_seed_if_any: bool = False
    does_not_confirm_story_facts: bool = True
    safe_user_note: str = ""
    created_at: str = ""
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class ProjectCreationCurrentState(BaseModel):
    state_status: str = "empty"
    project_id: str = ""
    creation_request: Optional[ProjectCreationRequest] = None
    validation_report: Optional[ProjectCreationValidationReport] = None
    creation_draft: Optional[ProjectCreationDraft] = None
    creation_decision: Optional[ProjectCreationDecision] = None
    recovered_from_storage: bool = True
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class ProjectOriginMetadata(BaseModel):
    origin_metadata_id: str
    project_id: str
    origin_type: str
    is_real_user_project: bool = False
    is_demo_project: bool = False
    is_template_derived: bool = False
    is_analyze_stories_derived: bool = False
    is_prompt_first: bool = False
    is_legacy_debug_project: bool = False
    source_prompt_ref: Optional[str] = None
    template_id: Optional[str] = None
    demo_seed_id: Optional[str] = None
    analyze_stories_import_ref: Optional[str] = None
    created_by_user_action: bool = True
    explicit_user_selection_recorded: bool = False
    story_facts_created_at_project_creation: bool = False
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class DemoSeedProfile(BaseModel):
    demo_seed_id: str
    display_name: str
    demo_seed_status: str = "enabled"
    source_profile: str = "phase8_m2_demo_seed"
    safe_preview: str = ""
    creates_demo_project_only: bool = True
    may_be_copied_to_real_project: bool = False
    required_marker: str = "explicit_demo_seed_selection"
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class DemoSeedProfilesResponse(BaseModel):
    demo_seed_profiles: list[DemoSeedProfile] = Field(default_factory=list)


class ProjectShell(BaseModel):
    project_id: str
    title: str
    language: str = "zh"
    status: str = "project_shell_created"
    current_step: str = "project_created"
    origin_metadata_id: Optional[str] = None
    origin_type: str = "unknown_origin"
    created_at: str = ""
    updated_at: str = ""
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class ProjectRegistryResponse(BaseModel):
    projects: list[ProjectShell] = Field(default_factory=list)


class ProjectOpenSummary(BaseModel):
    project: ProjectShell
    origin: ProjectOriginMetadata
    badges: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class ActiveProjectSelection(StrictModel):
    active_project_selection_id: str
    project_id: str
    selected_by: str = "user"
    opened_at: str = ""
    safe_summary: str = ""
    version_id: str = PROJECT_CREATION_SCHEMA_VERSION


class SetActiveProjectSelectionRequest(StrictModel):
    project_id: str
    selected_by: str = "user"


class ActiveProjectSelectionResponse(BaseModel):
    active_project_selection: Optional[ActiveProjectSelection] = None


class ProjectCreationSafetyScanReport(BaseModel):
    ok: bool = True
    scanned_targets: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    samples: dict[str, Any] = Field(default_factory=dict)
