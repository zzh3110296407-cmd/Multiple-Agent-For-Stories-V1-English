from typing import Any, Optional

from pydantic import BaseModel, Field


MODEL_SETTINGS_SCHEMA_VERSION = "phase8_m1_model_settings_v1"


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class ModelProviderOption(BaseModel):
    provider_type: str
    display_name: str
    adapter_type: str
    enabled_in_phase8_m1: bool = False
    status: str = "planned"
    requires_base_url: bool = False
    requires_api_key_ref: bool = False
    supports_health_check: bool = False
    default_model_name: str = ""
    default_base_url: str = ""
    safe_summary: str = ""


class ModelProviderProfile(BaseModel):
    profile_id: str
    settings_scope: str = "local_workspace_default"
    project_id: Optional[str] = "local_project"
    provider_type: str
    display_name: str
    adapter_type: str = ""
    base_url: str = ""
    model_name: str = ""
    api_key_ref: str = ""
    api_key_configured: bool = False
    enabled: bool = True
    health_status: str = "unknown"
    last_health_check_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    version_id: str = MODEL_SETTINGS_SCHEMA_VERSION


class CreateModelProviderProfileRequest(StrictModel):
    provider_type: str
    display_name: str = ""
    base_url: str = ""
    model_name: str = ""
    api_key_ref: str = ""
    enabled: bool = True


class PatchModelProviderProfileRequest(StrictModel):
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    model_name: Optional[str] = None
    api_key_ref: Optional[str] = None
    enabled: Optional[bool] = None


class ActiveModelSelection(BaseModel):
    active_selection_id: str
    selection_scope: str = "local_workspace_default"
    project_id: Optional[str] = "local_project"
    provider_profile_id: str
    provider_type: str
    model_name: str
    selected_by: str = "user"
    deterministic_fallback_allowed: bool = True
    real_model_required: bool = False
    created_at: str = ""
    updated_at: str = ""
    version_id: str = MODEL_SETTINGS_SCHEMA_VERSION


class SetActiveModelSelectionRequest(StrictModel):
    provider_profile_id: str
    selected_by: str = "user"
    deterministic_fallback_allowed: bool = True
    real_model_required: bool = False


class ActiveModelSelectionResponse(BaseModel):
    active_selection: Optional[ActiveModelSelection] = None


class ProviderHealthCheck(BaseModel):
    health_check_id: str
    provider_profile_id: str
    provider_type: str
    model_name: str
    status: str = "skipped"
    checked_at: str = ""
    latency_ms: int = 0
    safe_error_code: Optional[str] = None
    safe_message: str = ""
    used_real_provider: bool = False
    used_deterministic_fallback: bool = False
    no_raw_key: bool = True
    no_authorization_header: bool = True
    no_raw_prompt: bool = True
    no_raw_response: bool = True
    version_id: str = MODEL_SETTINGS_SCHEMA_VERSION


class ProviderHealthCheckResponse(BaseModel):
    health_check: ProviderHealthCheck
    profile: ModelProviderProfile


class ModelSecretPolicy(BaseModel):
    resolvable_key_ref_prefixes: list[str] = Field(default_factory=lambda: ["env:"])
    safe_display_key_ref_prefixes: list[str] = Field(
        default_factory=lambda: ["env:", "secret:", "runtime:"]
    )
    unsupported_safe_reference_prefixes: list[str] = Field(
        default_factory=lambda: ["secret:", "runtime:"]
    )
    raw_key_storage_disabled: bool = True
    forbidden_storage_targets: list[str] = Field(default_factory=list)
    frontend_may_show_key_presence: bool = True
    frontend_may_show_raw_key: bool = False
    frontend_may_show_key_last_four: bool = False
    safe_summary: str = ""


class ModelSettingsHealthSummary(BaseModel):
    latest_health_check: Optional[ProviderHealthCheck] = None
    health_checks: list[ProviderHealthCheck] = Field(default_factory=list)


class ModelSettingsWorkbench(BaseModel):
    current_provider: str = ""
    current_model: str = ""
    active_profile_id: Optional[str] = None
    active_selection_id: Optional[str] = None
    provider_options: list[ModelProviderOption] = Field(default_factory=list)
    provider_profiles: list[ModelProviderProfile] = Field(default_factory=list)
    health_summary: ModelSettingsHealthSummary = Field(
        default_factory=ModelSettingsHealthSummary
    )
    secret_policy_summary: ModelSecretPolicy = Field(default_factory=ModelSecretPolicy)
    deterministic_fallback_available: bool = True
    used_deterministic_fallback: bool = False
    used_real_provider: bool = False
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class ModelSettingsProvidersResponse(BaseModel):
    providers: list[ModelProviderOption] = Field(default_factory=list)


class ModelProviderProfilesResponse(BaseModel):
    profiles: list[ModelProviderProfile] = Field(default_factory=list)


class ModelSettingsSafetyScanReport(BaseModel):
    ok: bool = True
    scanned_targets: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    contains_raw_key: bool = False
    contains_authorization_header: bool = False
    contains_bearer_token: bool = False
    contains_raw_prompt: bool = False
    contains_raw_response: bool = False
    safe_summary: str = ""
    samples: dict[str, Any] = Field(default_factory=dict)
