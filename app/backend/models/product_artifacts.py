from pydantic import BaseModel, Field


PRODUCT_ARTIFACTS_SCHEMA_VERSION = "phase8_m7_product_artifacts_v1"


class ProductArtifactAuthorityBadge(BaseModel):
    authority_kind: str
    authority_label: str
    authority_scope: str
    not_source_story_fact: bool = True
    is_plugin_input_authority: bool = False
    is_derivative_output: bool = False
    does_not_apply_to_source_story: bool = True
    safe_summary: str = ""


class ProductArtifactSafePreview(BaseModel):
    preview_mode: str = "safe_summary_only"
    safe_title: str = ""
    safe_excerpt: str = ""
    metadata: dict = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    source_ref_ids: list[str] = Field(default_factory=list)
    content_hash: str = ""
    bounded_char_count: int = 0
    raw_payload_included: bool = False
    safe_reference_only: bool = True
    safe_summary: str = ""


class ProductArtifactSafetySummary(BaseModel):
    passed: bool = True
    blocking_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
    no_source_story_write: bool = True
    no_final_package_mutation: bool = True
    no_plugin_output_mutation: bool = True
    does_not_create_story_fact: bool = True
    does_not_mutate_source_story: bool = True
    does_not_mutate_source_artifact: bool = True
    does_not_apply_to_source_story: bool = True
    raw_payload_included: bool = False
    safe_summary: str = ""


class ProductArtifactEntry(BaseModel):
    artifact_entry_id: str
    project_id: str = ""
    artifact_category: str
    artifact_kind: str
    artifact_ref_id: str
    display_title: str
    display_status: str = "unknown"
    authority_badge: ProductArtifactAuthorityBadge
    safe_preview: ProductArtifactSafePreview
    safety_summary: ProductArtifactSafetySummary
    source_authority_refs: list[str] = Field(default_factory=list)
    is_derivative_artifact: bool = False
    can_open_controlled_product_view: bool = True
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    does_not_apply_to_source_story: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION


class FinalStoryPackageProductView(BaseModel):
    view_id: str
    snapshot_id: str
    project_id: str
    display_title: str
    display_status: str
    authority_badge: ProductArtifactAuthorityBadge
    safe_preview: ProductArtifactSafePreview
    safety_summary: ProductArtifactSafetySummary
    section_count: int = 0
    evidence_ref_count: int = 0
    source_version_count: int = 0
    known_residual_codes: list[str] = Field(default_factory=list)
    can_be_used_by_plugins: bool = False
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    does_not_mutate_source_story: bool = True
    does_not_mutate_source_artifact: bool = True
    does_not_apply_to_source_story: bool = True
    safe_reference_only: bool = True
    raw_payload_included: bool = False
    safe_summary: str = ""
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION


class PluginOutputProductView(BaseModel):
    view_id: str
    artifact_id: str
    project_id: str
    plugin_run_id: str
    plugin_id: str
    artifact_type: str
    display_title: str
    display_status: str
    current_version_id: str = ""
    version_count: int = 0
    source_package_snapshot_id: str = ""
    authority_badge: ProductArtifactAuthorityBadge
    safe_preview: ProductArtifactSafePreview
    safety_summary: ProductArtifactSafetySummary
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    does_not_mutate_source_story: bool = True
    does_not_mutate_source_artifact: bool = True
    does_not_apply_to_source_story: bool = True
    safe_reference_only: bool = True
    raw_payload_included: bool = False
    safe_summary: str = ""
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION


class ProductArtifactLibraryState(BaseModel):
    project_id: str = ""
    entries: list[ProductArtifactEntry] = Field(default_factory=list)
    final_story_package_views: list[FinalStoryPackageProductView] = Field(default_factory=list)
    plugin_output_views: list[PluginOutputProductView] = Field(default_factory=list)
    total_count: int = 0
    category_counts: dict[str, int] = Field(default_factory=dict)
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    does_not_mutate_source_story: bool = True
    does_not_apply_to_source_story: bool = True
    raw_payload_included: bool = False
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION


class ProductArtifactEntryListResponse(BaseModel):
    entries: list[ProductArtifactEntry] = Field(default_factory=list)
    total_count: int = 0
    view_model_only: bool = True
    does_not_create_story_fact: bool = True
    safe_summary: str = ""
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION


class FinalStoryPackageProductViewListResponse(BaseModel):
    views: list[FinalStoryPackageProductView] = Field(default_factory=list)
    total_count: int = 0
    view_model_only: bool = True
    safe_summary: str = ""
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION


class PluginOutputProductViewListResponse(BaseModel):
    views: list[PluginOutputProductView] = Field(default_factory=list)
    total_count: int = 0
    view_model_only: bool = True
    safe_summary: str = ""
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION


class DebugVisibilityPolicy(BaseModel):
    ordinary_mode_debug_visible: bool = False
    ordinary_mode_raw_payload_visible: bool = False
    expert_mode_safe_diagnostics_visible: bool = True
    expert_mode_raw_payload_visible: bool = False
    debug_routes_mutable: bool = False
    display_preference_only: bool = True
    permission_authority: bool = False
    view_model_only: bool = True
    safe_summary: str = ""
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION


class DebugIsolationAudit(BaseModel):
    ordinary_payload_safe: bool = True
    expert_payload_safe: bool = True
    artifact_cards_safe: bool = True
    controlled_product_view_separated_from_debug_summary: bool = True
    frontend_build_scan_passed: bool = True
    no_raw_prompt: bool = True
    no_raw_response: bool = True
    no_hidden_reasoning: bool = True
    no_api_key: bool = True
    no_authorization_header: bool = True
    no_uncontrolled_full_story_prose: bool = True
    no_uncontrolled_full_screenplay_text: bool = True
    no_source_story_write: bool = True
    no_final_package_mutation: bool = True
    no_plugin_output_mutation: bool = True
    no_m8_surface_created: bool = True
    passed: bool = True
    checked_payloads: list[str] = Field(default_factory=list)
    blocking_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    view_model_only: bool = True
    debug_mutation_authority: bool = False
    permission_authority: bool = False
    raw_payload_included: bool = False
    safe_summary: str = ""
    version_id: str = PRODUCT_ARTIFACTS_SCHEMA_VERSION
