import json
import os
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.agent_model_assignment import AgentModelAssignment
from app.backend.models.model_profile import ModelCapabilities, ModelProfile
from app.backend.models.model_provider import ModelProviderProfile as GatewayProviderProfile
from app.backend.models.model_settings import (
    ActiveModelSelection,
    ActiveModelSelectionResponse,
    CreateModelProviderProfileRequest,
    ModelProviderOption,
    ModelProviderProfile,
    ModelProviderProfilesResponse,
    ModelSecretPolicy,
    ModelSettingsHealthSummary,
    ModelSettingsProvidersResponse,
    ModelSettingsSafetyScanReport,
    ModelSettingsWorkbench,
    PatchModelProviderProfileRequest,
    ProviderHealthCheck,
    ProviderHealthCheckResponse,
    SetActiveModelSelectionRequest,
)
from app.backend.services.model_gateway_service import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_DEFAULT_MAX_OUTPUT_TOKENS,
    DEEPSEEK_DEFAULT_MODEL,
    QWEN_DEFAULT_BASE_URL,
    QWEN_DEFAULT_MAX_OUTPUT_TOKENS,
    QWEN_DEFAULT_MODEL,
    ModelCallError,
    ModelConfigurationError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.runtime_error_sanitizer import RuntimeErrorSanitizer
from app.backend.storage.json_store import JsonStore, StorageError


MODEL_PROVIDER_PROFILES_FILE = "model_provider_profiles.json"
MODEL_ACTIVE_SELECTION_FILE = "model_active_selection.json"
MODEL_PROVIDER_HEALTH_CHECKS_FILE = "model_provider_health_checks.json"

SETTINGS_SCOPE = "local_workspace_default"
PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase8_m1_model_settings_v1"

ENABLED_PROVIDER_TYPES = {"deepseek", "qwen", "local"}
SAFE_KEY_REF_PREFIXES = ("env:", "secret:", "runtime:")
RESOLVABLE_KEY_REF_PREFIXES = ("env:",)
RAW_SECRET_PATTERNS = [
    re.compile(r"(?<![A-Za-z])sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"lsv2_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)\bauthorization\s*:"),
]
FORBIDDEN_REQUEST_KEYS = {
    "apikeyplaintext",
    "rawkey",
    "authorizationheader",
    "bearertoken",
    "authorization",
    "apikey",
    "token",
}
UNSAFE_TEXT_MARKERS = (
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "provider secret",
    "provider_secret",
)


class ModelSettingsError(RuntimeError):
    """Base error for product model settings failures."""


class ModelSettingsNotFound(ModelSettingsError):
    """Raised when a model settings record is not found."""


class ModelSettingsSafetyError(ModelSettingsError):
    """Raised when a request or stored payload violates the secret policy."""


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, BaseModel):
        return model.dict()
    return dict(model)


class ModelSettingsService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.profiles_file = self.data_dir / MODEL_PROVIDER_PROFILES_FILE
        self.active_selection_file = self.data_dir / MODEL_ACTIVE_SELECTION_FILE
        self.health_checks_file = self.data_dir / MODEL_PROVIDER_HEALTH_CHECKS_FILE
        self.gateway = ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
            config_data_dir=self.data_dir,
        )
        self.runtime_error_sanitizer = RuntimeErrorSanitizer()

    def provider_options(self) -> ModelSettingsProvidersResponse:
        return ModelSettingsProvidersResponse(providers=self._provider_options())

    def secret_policy(self) -> ModelSecretPolicy:
        return ModelSecretPolicy(
            forbidden_storage_targets=[
                "story data",
                "memory",
                "prompt snapshot",
                "runtime log",
                "debug export",
                "Final Story Package",
                "Plugin Output Artifact",
                "frontend localStorage",
                "frontend source/build artifact",
            ],
            safe_summary=(
                "Only env: key references are resolvable in Phase 8 M1. "
                "The frontend may show configured/missing state but never raw keys."
            ),
        )

    def workbench(self) -> ModelSettingsWorkbench:
        profiles = self._read_profiles()
        active = self._read_active_selection_optional()
        health_checks = self._read_health_checks()
        gateway_status = self.gateway.validate_model_config()
        current_provider = (
            active.provider_type
            if active
            else gateway_status.provider_type or ""
        )
        current_model = active.model_name if active else gateway_status.model_name or ""
        active_profile = (
            self._find_profile(active.provider_profile_id, profiles)
            if active
            else None
        )
        scoped_health_checks = (
            [
                check
                for check in health_checks
                if check.provider_profile_id == active.provider_profile_id
            ]
            if active
            else health_checks
        )
        latest_health = scoped_health_checks[-1] if scoped_health_checks else None
        warnings: list[str] = []
        blockers: list[str] = []
        if not active:
            warnings.append("no_active_model_selection")
        if active and not active_profile:
            blockers.append("active_profile_not_found")
        if active_profile and not active_profile.enabled:
            blockers.append("active_profile_disabled")
        if active_profile and self._provider_requires_api_key(active_profile.provider_type):
            ref_status = self._api_key_ref_status(active_profile.api_key_ref)
            if ref_status != "configured":
                warnings.append(f"api_key_{ref_status}")
        if gateway_status.issues:
            warnings.extend([f"gateway:{issue}" for issue in gateway_status.issues[:5]])

        used_deterministic_fallback = current_provider == "local"
        return ModelSettingsWorkbench(
            current_provider=current_provider,
            current_model=current_model,
            active_profile_id=active.provider_profile_id if active else None,
            active_selection_id=active.active_selection_id if active else None,
            provider_options=self._provider_options(),
            provider_profiles=[self._public_profile(profile) for profile in profiles],
            health_summary=ModelSettingsHealthSummary(
                latest_health_check=latest_health,
                health_checks=list(reversed(scoped_health_checks[-10:])),
            ),
            secret_policy_summary=self.secret_policy(),
            deterministic_fallback_available=True,
            used_deterministic_fallback=used_deterministic_fallback,
            used_real_provider=bool(current_provider and current_provider != "local"),
            warnings=warnings,
            blockers=blockers,
            safe_summary=(
                "Model settings workbench summarizes provider configuration only. "
                "Agent calls still go through ModelGateway."
            ),
        )

    def create_profile(
        self,
        request: CreateModelProviderProfileRequest,
    ) -> ModelProviderProfile:
        self._guard_safe_payload(model_to_dict(request))
        provider_type = request.provider_type.strip().lower()
        option = self._option_by_type(provider_type)
        if option is None or not option.enabled_in_phase8_m1:
            raise ModelSettingsError(
                "Provider is not enabled in Phase 8 M1 model settings."
            )
        now = utc_now()
        profile = ModelProviderProfile(
            profile_id=f"model_provider_profile_{provider_type}_{uuid4().hex[:12]}",
            settings_scope=SETTINGS_SCOPE,
            project_id=PROJECT_ID,
            provider_type=provider_type,
            display_name=request.display_name.strip()
            or option.display_name,
            adapter_type=option.adapter_type,
            base_url=(request.base_url.strip() or option.default_base_url).rstrip("/"),
            model_name=request.model_name.strip() or option.default_model_name,
            api_key_ref=request.api_key_ref.strip(),
            api_key_configured=self._api_key_configured(
                provider_type,
                request.api_key_ref.strip(),
            ),
            enabled=request.enabled,
            health_status="unknown",
            created_at=now,
            updated_at=now,
            version_id=SCHEMA_VERSION,
        )
        self._validate_profile(profile)
        profiles = self._read_profiles()
        profiles.append(profile)
        self._write_profiles(profiles)
        return self._public_profile(profile)

    def list_profiles(self) -> ModelProviderProfilesResponse:
        return ModelProviderProfilesResponse(
            profiles=[self._public_profile(profile) for profile in self._read_profiles()]
        )

    def get_profile(self, profile_id: str) -> ModelProviderProfile:
        return self._public_profile(self._get_profile(profile_id))

    def patch_profile(
        self,
        profile_id: str,
        request: PatchModelProviderProfileRequest,
    ) -> ModelProviderProfile:
        self._guard_safe_payload(model_to_dict(request))
        profiles = self._read_profiles()
        profile = self._find_profile(profile_id, profiles)
        if profile is None:
            raise ModelSettingsNotFound("Model provider profile was not found.")
        updates = request.dict(exclude_unset=True)
        if "display_name" in updates and updates["display_name"] is not None:
            profile.display_name = updates["display_name"].strip() or profile.display_name
        if "base_url" in updates and updates["base_url"] is not None:
            profile.base_url = updates["base_url"].strip().rstrip("/")
        if "model_name" in updates and updates["model_name"] is not None:
            profile.model_name = updates["model_name"].strip()
        if "api_key_ref" in updates and updates["api_key_ref"] is not None:
            profile.api_key_ref = updates["api_key_ref"].strip()
        if "enabled" in updates and updates["enabled"] is not None:
            profile.enabled = bool(updates["enabled"])
        profile.api_key_configured = self._api_key_configured(
            profile.provider_type,
            profile.api_key_ref,
        )
        profile.updated_at = utc_now()
        self._validate_profile(profile)
        self._write_profiles(profiles)
        active = self._read_active_selection_optional()
        if active and active.provider_profile_id == profile.profile_id:
            active.provider_type = profile.provider_type
            active.model_name = profile.model_name
            active.updated_at = utc_now()
            self._write_active_selection(active)
            self._write_gateway_config(profile)
        return self._public_profile(profile)

    def set_active_selection(
        self,
        request: SetActiveModelSelectionRequest,
    ) -> ActiveModelSelection:
        self._guard_safe_payload(model_to_dict(request))
        profile = self._get_profile(request.provider_profile_id)
        if not profile.enabled:
            raise ModelSettingsError("Cannot activate a disabled provider profile.")
        if request.selected_by not in {"user", "system_default", "migration"}:
            raise ModelSettingsError("selected_by is not allowed.")
        now = utc_now()
        selection = ActiveModelSelection(
            active_selection_id=f"active_model_selection_{uuid4().hex[:12]}",
            selection_scope=SETTINGS_SCOPE,
            project_id=PROJECT_ID,
            provider_profile_id=profile.profile_id,
            provider_type=profile.provider_type,
            model_name=profile.model_name,
            selected_by=request.selected_by,
            deterministic_fallback_allowed=request.deterministic_fallback_allowed,
            real_model_required=request.real_model_required,
            created_at=now,
            updated_at=now,
            version_id=SCHEMA_VERSION,
        )
        self._write_active_selection(selection)
        self._write_gateway_config(profile)
        return selection

    def get_active_selection(self) -> ActiveModelSelectionResponse:
        return ActiveModelSelectionResponse(
            active_selection=self._read_active_selection_optional()
        )

    def run_health_check(self, profile_id: str) -> ProviderHealthCheckResponse:
        profile = self._get_profile(profile_id)
        started = time.monotonic()
        now = utc_now()
        status = "skipped"
        safe_error_code: str | None = None
        safe_message = ""
        used_real_provider = False
        used_deterministic_fallback = False

        if not profile.enabled:
            status = "skipped"
            safe_error_code = "profile_disabled"
            safe_message = "Provider profile is disabled."
        elif profile.provider_type == "local":
            status = "passed"
            safe_message = "Local deterministic provider check passed."
            used_deterministic_fallback = True
        else:
            ref_status = self._api_key_ref_status(profile.api_key_ref)
            if ref_status == "missing":
                status = "not_configured"
                safe_error_code = "missing_api_key_ref"
                safe_message = "API key reference is missing."
            elif ref_status == "unsupported_reference":
                status = "skipped"
                safe_error_code = "unsupported_key_ref"
                safe_message = "This key reference prefix is not resolvable in Phase 8 M1."
            elif ref_status == "env_missing":
                status = "not_configured"
                safe_error_code = "env_key_missing"
                safe_message = "Environment key is not configured."
            elif ref_status == "invalid":
                status = "failed"
                safe_error_code = "invalid_key_ref"
                safe_message = "API key reference is invalid."
            else:
                used_real_provider = True
                status, safe_error_code, safe_message = self._run_real_health_check(profile)

        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        health = ProviderHealthCheck(
            health_check_id=f"provider_health_check_{uuid4().hex[:12]}",
            provider_profile_id=profile.profile_id,
            provider_type=profile.provider_type,
            model_name=profile.model_name,
            status=status,
            checked_at=now,
            latency_ms=latency_ms,
            safe_error_code=safe_error_code,
            safe_message=safe_message,
            used_real_provider=used_real_provider,
            used_deterministic_fallback=used_deterministic_fallback,
            no_raw_key=True,
            no_authorization_header=True,
            no_raw_prompt=True,
            no_raw_response=True,
            version_id=SCHEMA_VERSION,
        )
        checks = self._read_health_checks()
        checks.append(health)
        self._write_health_checks(checks)
        profile.health_status = health.status
        profile.last_health_check_id = health.health_check_id
        profile.updated_at = utc_now()
        self._replace_profile(profile)
        return ProviderHealthCheckResponse(
            health_check=health,
            profile=self._public_profile(profile),
        )

    def safety_scan(self, extra_paths: list[Path] | None = None) -> ModelSettingsSafetyScanReport:
        targets = [
            self.profiles_file,
            self.active_selection_file,
            self.health_checks_file,
            self.data_dir / "model_runtime_logs.json",
            self.data_dir / "final_story_package_snapshots.json",
            self.data_dir / "plugin_output_artifacts.json",
            self.data_dir / "plugin_output_artifact_versions.json",
        ]
        targets.extend(extra_paths or [])
        issues: list[str] = []
        scanned: list[str] = []
        for path in targets:
            if not path.exists():
                continue
            scanned.append(path.name)
            text = path.read_text(encoding="utf-8", errors="ignore")
            value_text = self._string_values_text(text)
            lowered = value_text.lower()
            if any(pattern.search(value_text) for pattern in RAW_SECRET_PATTERNS):
                issues.append(f"{path.name}: secret_like_value")
            if "raw_prompt" in lowered or "raw prompt" in lowered:
                issues.append(f"{path.name}: raw_prompt_marker")
            if "raw_response" in lowered or "raw response" in lowered:
                issues.append(f"{path.name}: raw_response_marker")
        return ModelSettingsSafetyScanReport(
            ok=not issues,
            scanned_targets=scanned,
            issues=issues,
            contains_raw_key=any("secret_like_value" in issue for issue in issues),
            contains_authorization_header=any("authorization" in issue for issue in issues),
            contains_bearer_token=any("bearer" in issue for issue in issues),
            contains_raw_prompt=any("raw_prompt" in issue for issue in issues),
            contains_raw_response=any("raw_response" in issue for issue in issues),
            safe_summary="Model settings safety scan checks persisted settings and selected downstream records for secret-like values.",
        )

    def _provider_options(self) -> list[ModelProviderOption]:
        return [
            ModelProviderOption(
                provider_type="deepseek",
                display_name="DeepSeek",
                adapter_type="openai_compatible",
                enabled_in_phase8_m1=True,
                status="enabled",
                requires_base_url=True,
                requires_api_key_ref=True,
                supports_health_check=True,
                default_model_name=DEEPSEEK_DEFAULT_MODEL,
                default_base_url=DEEPSEEK_BASE_URL,
                safe_summary="DeepSeek is enabled through ModelGateway using an OpenAI-compatible adapter.",
            ),
            ModelProviderOption(
                provider_type="qwen",
                display_name="Qwen",
                adapter_type="openai_compatible",
                enabled_in_phase8_m1=True,
                status="enabled",
                requires_base_url=True,
                requires_api_key_ref=True,
                supports_health_check=True,
                default_model_name=QWEN_DEFAULT_MODEL,
                default_base_url=QWEN_DEFAULT_BASE_URL,
                safe_summary="Qwen keeps provider_type=qwen even when the adapter is OpenAI-compatible.",
            ),
            ModelProviderOption(
                provider_type="local",
                display_name="Local Mock",
                adapter_type="deterministic",
                enabled_in_phase8_m1=True,
                status="enabled",
                requires_base_url=False,
                requires_api_key_ref=False,
                supports_health_check=True,
                default_model_name="local_mock_model",
                default_base_url="",
                safe_summary="Local deterministic mock is available for verification without real provider keys.",
            ),
            *[
                ModelProviderOption(
                    provider_type=provider_type,
                    display_name=display_name,
                    adapter_type=adapter_type,
                    enabled_in_phase8_m1=False,
                    status="planned",
                    requires_base_url=requires_base_url,
                    requires_api_key_ref=True,
                    supports_health_check=False,
                    default_model_name="",
                    default_base_url="",
                    safe_summary=f"{display_name} is listed for future planning and is not enabled in Phase 8 M1.",
                )
                for provider_type, display_name, adapter_type, requires_base_url in [
                    ("openai", "OpenAI", "openai", False),
                    ("claude", "Claude", "anthropic", False),
                    ("openai_compatible", "OpenAI Compatible", "openai_compatible", True),
                    ("custom_http", "Custom HTTP", "custom_http", True),
                    ("local_model", "Local Model", "local_model", True),
                    ("private_deployment", "Private Deployment", "private_deployment", True),
                ]
            ],
        ]

    def _option_by_type(self, provider_type: str) -> ModelProviderOption | None:
        return next(
            (option for option in self._provider_options() if option.provider_type == provider_type),
            None,
        )

    def _read_profiles(self) -> list[ModelProviderProfile]:
        if not self.store.exists(self.profiles_file):
            return []
        try:
            data = self.store.read_list(self.profiles_file)
            return [ModelProviderProfile(**item) for item in data]
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError("Model provider profiles storage is invalid.") from exc

    def _write_profiles(self, profiles: list[ModelProviderProfile]) -> None:
        self._guard_safe_payload([model_to_dict(profile) for profile in profiles])
        self.store.write(self.profiles_file, [model_to_dict(profile) for profile in profiles])

    def _replace_profile(self, updated: ModelProviderProfile) -> None:
        profiles = self._read_profiles()
        replaced = False
        for index, profile in enumerate(profiles):
            if profile.profile_id == updated.profile_id:
                profiles[index] = updated
                replaced = True
                break
        if not replaced:
            raise ModelSettingsNotFound("Model provider profile was not found.")
        self._write_profiles(profiles)

    def _get_profile(self, profile_id: str) -> ModelProviderProfile:
        profile = self._find_profile(profile_id, self._read_profiles())
        if profile is None:
            raise ModelSettingsNotFound("Model provider profile was not found.")
        return profile

    def _find_profile(
        self,
        profile_id: str,
        profiles: list[ModelProviderProfile],
    ) -> ModelProviderProfile | None:
        return next((profile for profile in profiles if profile.profile_id == profile_id), None)

    def _read_active_selection_optional(self) -> ActiveModelSelection | None:
        if not self.store.exists(self.active_selection_file):
            return None
        try:
            return ActiveModelSelection(**self.store.read(self.active_selection_file))
        except (StorageError, ValidationError) as exc:
            raise StorageError("Active model selection storage is invalid.") from exc

    def _write_active_selection(self, selection: ActiveModelSelection) -> None:
        self._guard_safe_payload(model_to_dict(selection))
        self.store.write(self.active_selection_file, model_to_dict(selection))

    def _read_health_checks(self) -> list[ProviderHealthCheck]:
        if not self.store.exists(self.health_checks_file):
            return []
        try:
            data = self.store.read_list(self.health_checks_file)
            return [ProviderHealthCheck(**item) for item in data]
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError("Model provider health checks storage is invalid.") from exc

    def _write_health_checks(self, health_checks: list[ProviderHealthCheck]) -> None:
        limited = health_checks[-200:]
        self._guard_safe_payload([model_to_dict(check) for check in limited])
        self.store.write(self.health_checks_file, [model_to_dict(check) for check in limited])

    def _validate_profile(self, profile: ModelProviderProfile) -> None:
        option = self._option_by_type(profile.provider_type)
        if option is None or not option.enabled_in_phase8_m1:
            raise ModelSettingsError("Provider profile provider_type is not enabled in Phase 8 M1.")
        if profile.provider_type == "qwen" and profile.adapter_type != "openai_compatible":
            raise ModelSettingsError("Qwen must keep adapter_type=openai_compatible in Phase 8 M1.")
        if not profile.model_name:
            raise ModelSettingsError("Model name is required.")
        if option.requires_base_url and not profile.base_url:
            raise ModelSettingsError("Provider base_url is required.")
        if option.requires_api_key_ref and not profile.api_key_ref:
            raise ModelSettingsError("Provider api_key_ref is required.")
        if profile.api_key_ref:
            self._validate_api_key_ref(profile.api_key_ref)

    def _api_key_configured(self, provider_type: str, api_key_ref: str) -> bool:
        if not self._provider_requires_api_key(provider_type):
            return True
        return self._api_key_ref_status(api_key_ref) == "configured"

    def _provider_requires_api_key(self, provider_type: str) -> bool:
        option = self._option_by_type(provider_type)
        return bool(option and option.requires_api_key_ref)

    def _api_key_ref_status(self, api_key_ref: str) -> str:
        if not api_key_ref:
            return "missing"
        if self._looks_like_plaintext_secret(api_key_ref):
            return "invalid"
        if api_key_ref.startswith("env:"):
            env_name = api_key_ref.removeprefix("env:").strip()
            if not env_name:
                return "invalid"
            return "configured" if os.environ.get(env_name) else "env_missing"
        if api_key_ref.startswith(("secret:", "runtime:")):
            return "unsupported_reference"
        return "invalid"

    def _validate_api_key_ref(self, api_key_ref: str) -> None:
        status = self._api_key_ref_status(api_key_ref)
        if status == "invalid":
            raise ModelSettingsSafetyError("API key reference is invalid or unsafe.")

    def _public_profile(self, profile: ModelProviderProfile) -> ModelProviderProfile:
        public = profile.copy(deep=True)
        if public.api_key_ref and self._looks_like_plaintext_secret(public.api_key_ref):
            public.api_key_ref = "[redacted-invalid-ref]"
            public.api_key_configured = False
        else:
            public.api_key_configured = self._api_key_configured(
                public.provider_type,
                public.api_key_ref,
            )
        return public

    def _write_gateway_config(self, profile: ModelProviderProfile) -> None:
        auth_type = "none" if profile.provider_type == "local" else "bearer"
        gateway_provider = GatewayProviderProfile(
            provider_id=profile.profile_id,
            provider_type=profile.provider_type,
            display_name=profile.display_name,
            base_url=profile.base_url,
            auth_type=auth_type,
            api_key_ref=profile.api_key_ref,
            default_model=profile.model_name,
            enabled=profile.enabled,
            created_by="user",
            notes="Phase 8 M1 product model settings active selection. No raw key is stored.",
        )
        gateway_model_profile = ModelProfile(
            model_profile_id=f"model_profile_{profile.profile_id}",
            provider_id=gateway_provider.provider_id,
            model_name=profile.model_name,
            capabilities=ModelCapabilities(
                chat=True,
                json_output=True,
                tool_calling=False,
                streaming=False,
                long_context=profile.provider_type == "qwen",
                vision=False,
                embedding=False,
            ),
            context_window_hint=262144 if profile.provider_type == "qwen" else 64000,
            cost_tier="low" if profile.provider_type in {"local", "deepseek"} else "medium",
            quality_tier="draft" if profile.provider_type == "local" else "strong",
            status="active" if profile.enabled else "disabled",
        )
        gateway_assignment = AgentModelAssignment(
            assignment_id="agent_model_assignment_phase8_m1_active",
            agent_role="all",
            primary_model_profile_id=gateway_model_profile.model_profile_id,
            fallback_model_profile_id=None,
            routing_policy="single_model",
            temperature=0.7,
            max_output_tokens=QWEN_DEFAULT_MAX_OUTPUT_TOKENS
            if profile.provider_type == "qwen"
            else DEEPSEEK_DEFAULT_MAX_OUTPUT_TOKENS,
            structured_output_required=True,
        )
        for path, data in [
            (self.gateway.provider_file, model_to_dict(gateway_provider)),
            (self.gateway.model_profile_file, model_to_dict(gateway_model_profile)),
            (self.gateway.assignment_file, model_to_dict(gateway_assignment)),
        ]:
            self._guard_safe_payload(data)
            self.store.write(path, data)

    def _run_real_health_check(
        self,
        profile: ModelProviderProfile,
    ) -> tuple[str, str | None, str]:
        try:
            with TemporaryDirectory() as temp_dir:
                temp_data_dir = Path(temp_dir) / PROJECT_ID
                temp_service = ModelGatewayService(
                    store=JsonStore(),
                    data_dir=temp_data_dir,
                    config_data_dir=temp_data_dir,
                )
                temp_settings = ModelSettingsService(
                    store=temp_service.store,
                    data_dir=temp_data_dir,
                )
                temp_profile = profile.copy(deep=True)
                temp_profile.profile_id = "provider_health_check_temp_profile"
                temp_profile.enabled = True
                temp_settings._write_profiles([temp_profile])
                temp_settings.set_active_selection(
                    SetActiveModelSelectionRequest(
                        provider_profile_id=temp_profile.profile_id,
                        selected_by="system_default",
                        deterministic_fallback_allowed=False,
                        real_model_required=True,
                    )
                )
                result = temp_service.generate_json(
                    [
                        {
                            "role": "user",
                            "content": 'Return valid JSON only. Return exactly {"ping":"ok"}.',
                        }
                    ],
                    options={"temperature": 0, "max_output_tokens": 64},
                    service_name="ModelSettingsProviderHealthCheck",
                    operation_name="manual_provider_health_check",
                )
                if str(result.data.get("ping") or "").lower() == "ok":
                    return "passed", None, "Provider health check passed."
                return "failed", "provider_unexpected_response", "Provider returned an unsupported health-check shape."
        except (ModelConfigurationError, ModelCallError, ModelJsonParseError) as exc:
            safe_error = self.runtime_error_sanitizer.sanitize(exc)
            return "failed", safe_error.error_type, safe_error.user_visible_message
        except StorageError as exc:
            return "failed", "storage_error", "Provider health check could not be recorded safely."

    def _guard_safe_payload(self, payload: Any) -> None:
        def visit(value: Any, path: str) -> None:
            if isinstance(value, BaseModel):
                visit(model_to_dict(value), path)
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    if normalized_key in FORBIDDEN_REQUEST_KEYS:
                        raise ModelSettingsSafetyError(
                            f"Unsafe model settings field is not allowed: {path}.{key}"
                        )
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_TEXT_MARKERS):
                    raise ModelSettingsSafetyError(
                        f"Unsafe model settings value is not allowed: {path}"
                    )
                if self._looks_like_plaintext_secret(value):
                    raise ModelSettingsSafetyError(
                        f"Unsafe model settings secret-like value is not allowed: {path}"
                    )

        visit(payload, "$")

    def _string_values_text(self, text: str) -> str:
        try:
            payload = json.loads(text)
        except ValueError:
            return text
        values: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for child in value.values():
                    visit(child)
                return
            if isinstance(value, list):
                for child in value:
                    visit(child)
                return
            if isinstance(value, str):
                values.append(value)

        visit(payload)
        return "\n".join(values)

    def _looks_like_plaintext_secret(self, value: str) -> bool:
        normalized = value.strip()
        candidates = [normalized]
        for prefix in SAFE_KEY_REF_PREFIXES:
            if normalized.startswith(prefix):
                candidates.append(normalized.removeprefix(prefix).strip())
        return any(
            any(pattern.search(candidate) for pattern in RAW_SECRET_PATTERNS)
            or "MODEL_API_KEY_VALUE" in candidate
            for candidate in candidates
        )
