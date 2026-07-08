from typing import Optional

from pydantic import BaseModel, Field


TEMPLATE_DEMO_SEED_SCHEMA_VERSION = "phase8_m4_template_demo_seed_v1"


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class ProjectTemplate(BaseModel):
    template_id: str
    display_name: str
    template_status: str = "enabled"
    template_version_id: str
    source_type: str = "built_in_safe_template"
    source_ref: str
    safe_preview: str = ""
    starter_material_refs: list[str] = Field(default_factory=list)
    recommended_entry_workspace: str = "world_canvas"
    is_demo_material: bool = False
    creates_story_facts_now: bool = False
    requires_downstream_confirmation: bool = True
    contains_full_story_prose: bool = False
    contains_full_screenplay_text: bool = False
    contains_user_private_content: bool = False
    license_status: str = "built_in_safe"
    provenance_summary: str = ""
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = TEMPLATE_DEMO_SEED_SCHEMA_VERSION


class ProjectTemplatesResponse(BaseModel):
    templates: list[ProjectTemplate] = Field(default_factory=list)


class CreateTemplateInstantiationRequest(StrictModel):
    project_id: str
    creation_request_id: Optional[str] = None
    creation_decision_id: Optional[str] = None
    target_workspace: str = "world_canvas"
    safe_user_note: str = ""


class TemplateInstantiationRequest(BaseModel):
    template_instantiation_request_id: str
    project_id: str
    creation_request_id: Optional[str] = None
    creation_decision_id: Optional[str] = None
    project_origin_metadata_id: str
    template_id: str
    template_version_id: str
    target_workspace: str = "world_canvas"
    request_status: str = "created"
    explicit_user_selection: bool = True
    safe_user_note: str = ""
    validation_report_id: Optional[str] = None
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = TEMPLATE_DEMO_SEED_SCHEMA_VERSION


class TemplateInstantiationValidationReport(BaseModel):
    template_instantiation_validation_report_id: str
    template_instantiation_request_id: str
    project_id: str
    template_id: str
    validation_status: str = "pending"
    can_instantiate: bool = False
    project_origin_metadata_present: bool = False
    origin_type_is_template: bool = False
    template_id_matches_origin: bool = False
    template_is_enabled: bool = False
    template_is_not_demo_material: bool = False
    template_source_is_safe: bool = False
    no_full_story_prose: bool = False
    no_full_screenplay_text: bool = False
    no_user_private_content: bool = False
    will_not_write_story_facts: bool = True
    requires_downstream_confirmation: bool = True
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""
    version_id: str = TEMPLATE_DEMO_SEED_SCHEMA_VERSION


class TemplateInstantiationReport(BaseModel):
    template_instantiation_report_id: str
    template_instantiation_request_id: str
    project_id: str
    project_origin_metadata_id: str
    template_id: str
    template_version_id: str
    report_status: str = "created"
    starter_material_refs: list[str] = Field(default_factory=list)
    safe_template_preview: str = ""
    target_workspace: str = "world_canvas"
    handoff_status: str = "requires_downstream_confirmation"
    creates_user_owned_story_facts_now: bool = False
    requires_downstream_confirmation: bool = True
    wrote_confirmed_world_canvas: bool = False
    wrote_confirmed_character: bool = False
    wrote_active_framework: bool = False
    wrote_chapter_plan: bool = False
    wrote_scene_event_memory_state: bool = False
    wrote_final_story_package: bool = False
    wrote_plugin_output_artifact: bool = False
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = TEMPLATE_DEMO_SEED_SCHEMA_VERSION


class RunDemoSeedRequest(StrictModel):
    project_id: str
    creation_request_id: Optional[str] = None
    creation_decision_id: Optional[str] = None
    explicit_user_selection: bool = False
    safe_user_note: str = ""


class DemoSeedRunRecord(BaseModel):
    demo_seed_run_id: str
    project_id: str
    creation_request_id: Optional[str] = None
    creation_decision_id: Optional[str] = None
    project_origin_metadata_id: str
    demo_seed_id: str
    run_status: str = "created"
    explicit_user_selection_verified: bool = True
    demo_marker: str = "explicit_demo_seed_selection"
    is_demo_project: bool = True
    creates_demo_project_only: bool = True
    writes_real_project_storage: bool = False
    created_demo_storage_ref: str = ""
    copied_to_real_project: bool = False
    demo_to_real_conversion_blocked: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = TEMPLATE_DEMO_SEED_SCHEMA_VERSION


class DemoSeedIsolationAudit(BaseModel):
    demo_seed_isolation_audit_id: str
    demo_seed_run_id: str
    project_id: str
    project_origin_metadata_id: str
    demo_seed_id: str
    passed: bool = False
    explicit_user_selection_verified: bool = False
    demo_marker_present: bool = False
    project_origin_metadata_present: bool = False
    origin_type_is_demo_seed: bool = False
    project_marked_demo: bool = False
    no_demo_data_in_real_project: bool = True
    no_legacy_debug_data_in_real_project: bool = True
    no_demo_seed_auto_opened_as_real: bool = True
    no_demo_to_real_conversion_without_audit: bool = True
    no_final_story_fact_write: bool = True
    no_final_story_package_write: bool = True
    no_plugin_output_artifact_write: bool = True
    no_raw_prompt_in_debug: bool = True
    no_raw_response: bool = True
    no_hidden_reasoning: bool = True
    no_api_key: bool = True
    no_authorization_header: bool = True
    no_bearer_token: bool = True
    no_uncontrolled_full_story_prose: bool = True
    no_full_screenplay_text: bool = True
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""
    version_id: str = TEMPLATE_DEMO_SEED_SCHEMA_VERSION


class ProjectOriginBadge(BaseModel):
    project_id: str
    project_origin_metadata_id: str
    origin_type: str
    badge_label: str
    badge_kind: str
    is_real_user_project: bool = False
    is_demo_project: bool = False
    is_template_derived: bool = False
    is_prompt_first: bool = False
    is_analyze_stories_derived: bool = False
    is_legacy_debug_project: bool = False
    requires_origin_review: bool = False
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)


class TemplateDemoSeedSafetyScanReport(BaseModel):
    ok: bool = True
    scanned_targets: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
