from typing import Literal

from pydantic import BaseModel, Field


PluginVisibility = Literal["visible", "hidden"]
PluginAvailabilityStatus = Literal["planned", "disabled", "experimental", "blocked"]
PluginFamily = Literal["script", "storyboard", "asset_package", "utility"]
PluginRiskLevel = Literal["low", "medium", "high", "blocked"]
PluginInputValidationStatus = Literal[
    "valid_for_future_runtime",
    "blocked",
    "unsupported",
    "invalid_snapshot",
    "plugin_unavailable",
]
PluginArtifactType = Literal[
    "script_shape_package",
    "scene_outline_package",
    "screenplay_draft_package",
    "storyboard_package",
    "shot_list_package",
    "digital_asset_package",
]


class PluginProtocolStrictRequest(BaseModel):
    class Config:
        extra = "forbid"


class PluginManifest(BaseModel):
    manifest_id: str
    plugin_id: str
    display_name: str
    description: str
    plugin_family: PluginFamily
    registry_entry_id: str
    input_schema_id: str
    output_schema_ids: list[str] = Field(default_factory=list)
    capability_declaration_id: str
    risk_declaration_id: str
    version_record_id: str
    visibility: PluginVisibility = "visible"
    availability_status: PluginAvailabilityStatus = "planned"
    runtime_available: bool = False
    can_create_plugin_run: bool = False
    requires_final_story_package_snapshot: bool = True
    allow_live_story_state_input: bool = False
    allow_unconfirmed_draft_input: bool = False
    allow_phase6_proposal_as_truth: bool = False
    allow_fixture_input: bool = False
    mutates_source_story: bool = False
    checkpoint_templates: list[dict] = Field(default_factory=list)
    created_at: str
    updated_at: str
    safe_summary: str


class PluginRegistryEntry(BaseModel):
    registry_entry_id: str
    plugin_id: str
    manifest_id: str
    display_order: int
    visibility: PluginVisibility = "visible"
    visible_in_selector: bool = True
    availability_status: PluginAvailabilityStatus = "planned"
    unavailable_reason: str = ""
    created_at: str
    updated_at: str
    safe_summary: str


class PluginInputSchema(BaseModel):
    input_schema_id: str
    plugin_id: str
    requires_final_story_package_snapshot: bool = True
    required_record_types: list[str] = Field(default_factory=list)
    required_snapshot_fields: list[str] = Field(default_factory=list)
    required_companion_record_types: list[str] = Field(default_factory=list)
    compatible_snapshot_schema_versions: list[str] = Field(default_factory=list)
    blocked_input_record_types: list[str] = Field(default_factory=list)
    allow_live_story_state_input: bool = False
    allow_unconfirmed_draft_input: bool = False
    allow_phase6_proposal_as_truth: bool = False
    allow_fixture_input: bool = False
    created_at: str
    safe_summary: str


class PluginOutputSchema(BaseModel):
    output_schema_id: str
    plugin_id: str
    artifact_type: PluginArtifactType
    artifact_schema_version: str
    future_milestone: str
    derivative_only: bool = True
    mutates_source_story: bool = False
    requires_plugin_run: bool = True
    created_at: str
    safe_summary: str


class PluginCapabilityDeclaration(BaseModel):
    capability_declaration_id: str
    plugin_id: str
    can_read_final_story_package_snapshot: bool = True
    can_read_live_story_state: bool = False
    can_read_unconfirmed_drafts: bool = False
    can_read_phase6_proposals_as_truth: bool = False
    can_create_plugin_run: bool = False
    can_create_checkpoint: bool = False
    can_create_output_artifact: bool = False
    can_call_external_provider: bool = False
    can_mutate_source_story: bool = False
    requires_user_checkpoint_in_future: bool = True
    runtime_required_milestone: str
    created_at: str
    safe_summary: str


class PluginRiskDeclaration(BaseModel):
    risk_declaration_id: str
    plugin_id: str
    risk_level: PluginRiskLevel
    data_exposure_level: str
    license_template_risks: list[str] = Field(default_factory=list)
    external_service_risks: list[str] = Field(default_factory=list)
    source_mutation_risk: bool = False
    requires_provider_secret: bool = False
    requires_user_confirmation_before_runtime: bool = True
    blocked_reason_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    created_at: str
    safe_summary: str


class PluginVersionRecord(BaseModel):
    version_record_id: str
    plugin_id: str
    plugin_semver: str
    plugin_protocol_version: str
    manifest_schema_version: str
    input_schema_version: str
    output_schema_version: str
    compatible_snapshot_schema_versions: list[str] = Field(default_factory=list)
    status: PluginAvailabilityStatus
    created_at: str
    safe_summary: str


class PluginInputValidationRequest(PluginProtocolStrictRequest):
    snapshot_id: str
    persist_validation_report: bool = True
    safe_user_note: str = ""


class PluginInputValidationReport(BaseModel):
    input_validation_report_id: str
    plugin_id: str
    manifest_id: str
    input_schema_id: str
    snapshot_id: str
    project_id: str = ""
    validation_status: PluginInputValidationStatus
    input_valid: bool
    plugin_runtime_available: bool = False
    can_create_plugin_run_now: bool = False
    can_create_plugin_run_later: bool = False
    package_type: str = ""
    snapshot_status: str = ""
    can_be_used_by_plugins: bool = False
    not_real_project_final_package: bool = True
    required_record_checks: dict[str, bool] = Field(default_factory=dict)
    required_snapshot_field_checks: dict[str, bool] = Field(default_factory=dict)
    missing_required_fields: list[str] = Field(default_factory=list)
    blocked_reason_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    evidence_index_id: str = ""
    safety_audit_id: str = ""
    source_ref_count: int = 0
    complete_story_text_hash: str = ""
    complete_story_text_char_count: int = 0
    full_story_text_copied: bool = False
    safe_user_note: str = ""
    created_at: str
    safe_summary: str


class PluginOutputSchemaListResponse(BaseModel):
    plugin_id: str
    output_schemas: list[PluginOutputSchema] = Field(default_factory=list)
    total_count: int = 0


class PluginRegistryListResponse(BaseModel):
    registry_entries: list[PluginRegistryEntry] = Field(default_factory=list)
    manifests: list[PluginManifest] = Field(default_factory=list)
    total_count: int = 0
    safe_summary: str


class PluginRegistryDetailResponse(BaseModel):
    registry_entry: PluginRegistryEntry
    manifest: PluginManifest
    input_schema: PluginInputSchema
    output_schemas: list[PluginOutputSchema] = Field(default_factory=list)
    capability_declaration: PluginCapabilityDeclaration
    risk_declaration: PluginRiskDeclaration
    version_record: PluginVersionRecord
    safe_summary: str
