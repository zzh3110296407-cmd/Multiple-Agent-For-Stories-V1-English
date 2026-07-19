import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.core.model_endpoint_policy import (
    ModelEndpointPolicyError,
    validate_model_endpoint_policy,
)
from app.backend.models.agent_model_assignment import AgentModelAssignment
from app.backend.models.model_gateway import (
    ModelGatewayJsonResult,
    ModelGatewayMessage,
    ModelGatewayOptions,
    ModelGatewayRequest,
    ModelGatewaySeedResponse,
    ModelGatewayStatusResponse,
    ModelGatewayTextResult,
)
from app.backend.models.model_profile import ModelCapabilities, ModelProfile
from app.backend.models.model_provider import ModelProviderProfile
from app.backend.services.model_adapters.base import (
    ModelAdapter,
    ModelAdapterError,
)
from app.backend.services.model_adapters.local_mock import LocalMockModelAdapter
from app.backend.services.model_adapters.openai_compatible import (
    OpenAICompatibleModelAdapter,
)
from app.backend.services.model_runtime_log_service import ModelRuntimeLogService
from app.backend.services.provider_health_service import ProviderHealthService
from app.backend.services.runtime_error_sanitizer import RuntimeErrorSanitizer
from app.backend.services.tracing_service import TracingService
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.storage.json_store import JsonStore, StorageError


DEFAULT_PROVIDER_ID = "provider_active_001"
DEFAULT_MODEL_PROFILE_ID = "model_profile_default_local"
DEFAULT_ASSIGNMENT_ID = "agent_model_assignment_default"
DEFAULT_LOCAL_MODEL_NAME = "local_mock_model"
DEEPSEEK_PROVIDER_ID = "provider_deepseek_phase2_001"
DEEPSEEK_MODEL_PROFILE_ID = "model_profile_deepseek_v4_flash_phase2"
DEEPSEEK_ASSIGNMENT_ID = "agent_model_assignment_deepseek_phase2"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
DEEPSEEK_HIGH_QUALITY_MODEL = "deepseek-v4-pro"
DEEPSEEK_DEFAULT_MAX_OUTPUT_TOKENS = 6000
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
QWEN_PROVIDER_ID = "provider_qwen_phase4_interlude_001"
QWEN_MODEL_PROFILE_ID = "model_profile_qwen36_phase4_interlude"
QWEN_ASSIGNMENT_ID = "agent_model_assignment_qwen_phase4_interlude"
QWEN_DEFAULT_MODEL = "qwen3.6-35b-a3b-fp8"
QWEN_DEFAULT_BASE_URL = "https://your-openai-compatible-endpoint/v1"
QWEN_DEFAULT_API_KEY_ENV = "QWEN_API_KEY"
QWEN_DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"
QWEN_DEFAULT_MAX_OUTPUT_TOKENS = 4000
OPENAI_COMPATIBLE_DEFAULT_TIMEOUT_SECONDS = 180
OPENAI_COMPATIBLE_DEFAULT_MAX_ATTEMPTS = 4
QWEN_DEFAULT_TIMEOUT_SECONDS = 90
QWEN_DEFAULT_MAX_ATTEMPTS = 2

ALLOWED_PROVIDER_TYPES = {
    "openai",
    "anthropic",
    "deepseek",
    "qwen",
    "openai_compatible",
    "custom_http",
    "local",
}
ALLOWED_AUTH_TYPES = {"api_key", "bearer", "custom_header", "none"}
ALLOWED_COST_TIERS = {"low", "medium", "high", "unknown"}
ALLOWED_QUALITY_TIERS = {"draft", "standard", "strong", "unknown"}
ALLOWED_MODEL_STATUS = {"active", "disabled", "failed"}
ALLOWED_AGENT_ROLES = {
    "all",
    "system",
    "chapter",
    "scene",
    "character",
    "memory_curator",
    "quality_check",
}
ALLOWED_ROUTING_POLICIES = {"single_model", "by_cost", "by_quality", "by_task"}
SAFE_KEY_REF_PREFIXES = ("env:", "secret:", "runtime:")
OPENAI_KEY_PREFIX = "s" + "k-"
LANGSMITH_KEY_PREFIX = "lsv2_pt"
SECRET_VALUE_SENTINEL = "MODEL_API_KEY" + "_VALUE"


class ModelGatewayError(RuntimeError):
    """Base error for Model Gateway failures."""

    def __init__(
        self,
        message: str,
        *,
        call_id: str | None = None,
        latency_ms: int = 0,
    ) -> None:
        super().__init__(message)
        self.call_id = call_id
        self.latency_ms = latency_ms


class ModelConfigurationError(ModelGatewayError):
    """Raised when the active provider/model assignment is missing or invalid."""


class ModelCallError(ModelGatewayError):
    """Raised when a configured model call fails."""


class ModelJsonParseError(ModelGatewayError):
    """Raised when model output cannot be parsed as a JSON object."""


@dataclass(frozen=True)
class ActiveModelConfig:
    provider: ModelProviderProfile
    model_profile: ModelProfile
    assignment: AgentModelAssignment


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ModelGatewayService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        config_data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.config_data_dir = config_data_dir or settings.data_dir
        self.provider_file = self.config_data_dir / "model_provider_profile.json"
        self.model_profile_file = self.config_data_dir / "model_profile.json"
        self.assignment_file = self.config_data_dir / "agent_model_assignment.json"
        self.tracing = TracingService()
        self.runtime_logs = ModelRuntimeLogService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.runtime_error_sanitizer = RuntimeErrorSanitizer()
        self.provider_health = ProviderHealthService(
            model_gateway=self,
            runtime_logs=self.runtime_logs,
            store=self.store,
            data_dir=self.data_dir,
        )

    def get_active_model_config(self) -> ActiveModelConfig:
        status = self.validate_model_config()
        if not status.configured:
            raise ModelConfigurationError("; ".join(status.issues))
        provider, model_profile, assignment = self._read_required_config()
        return ActiveModelConfig(
            provider=provider,
            model_profile=model_profile,
            assignment=assignment,
        )

    def generate_text(
        self,
        messages: list[ModelGatewayMessage | dict[str, Any]],
        options: ModelGatewayOptions | dict[str, Any] | None = None,
        *,
        project_id: str = "local_project",
        agent_role: str | None = None,
        service_name: str = "ModelGatewayService.generate_text",
        operation_name: str = "generate_text",
    ) -> ModelGatewayTextResult:
        record = self.runtime_logs.begin_call(
            project_id=self._runtime_project_id(project_id),
            agent_role=agent_role or "all",
            service_name=service_name,
            operation_name=operation_name,
            request_type="generate_text",
        )
        try:
            self._attach_runtime_status_metadata(record.call_id, agent_role=agent_role)
            config = self.get_active_model_config()
            self._attach_runtime_config_metadata(record.call_id, config, agent_role)
            request = self._build_request(
                config=config,
                messages=messages,
                options=options,
                response_format="text",
            )
            adapter = self._get_adapter(config, request=request)

            def call_provider() -> str:
                try:
                    return adapter.generate_text(request)
                except ModelAdapterError as exc:
                    raise ModelCallError(str(exc)) from exc

            text = self.tracing.run_operation(
                "ModelGateway.generate_text",
                call_provider,
                run_type="llm",
                metadata=self._trace_metadata(
                    config,
                    response_format="text",
                    local_call_id=record.call_id,
                ),
                tags=self._trace_tags(config),
                inputs=self._trace_inputs(request),
            )
            completed_record = self.runtime_logs.finish_success(
                record.call_id,
                adapter_success=True,
                json_parse_success=None,
            )
            self._refresh_provider_health_safely()
        except ModelConfigurationError as exc:
            failed_record = self.runtime_logs.finish_failure(
                record.call_id,
                safe_error=self.runtime_error_sanitizer.sanitize(
                    exc,
                    stage="config_check",
                ),
                adapter_success=False,
                json_parse_success=None,
            )
            self._attach_error_call_metadata(exc, failed_record)
            self._refresh_provider_health_safely()
            raise
        except ModelCallError as exc:
            failed_record = self.runtime_logs.finish_failure(
                record.call_id,
                safe_error=self.runtime_error_sanitizer.sanitize(
                    exc,
                    stage="adapter_request",
                ),
                adapter_success=False,
                json_parse_success=None,
            )
            self._attach_error_call_metadata(exc, failed_record)
            self._refresh_provider_health_safely()
            raise
        except Exception as exc:
            self.runtime_logs.finish_failure(
                record.call_id,
                safe_error=self.runtime_error_sanitizer.sanitize(exc),
                adapter_success=False,
                json_parse_success=None,
            )
            self._refresh_provider_health_safely()
            raise
        return ModelGatewayTextResult(
            text=text,
            provider_id=config.provider.provider_id,
            model_name=config.model_profile.model_name,
            call_id=completed_record.call_id,
            latency_ms=completed_record.latency_ms,
        )

    def generate_json(
        self,
        messages: list[ModelGatewayMessage | dict[str, Any]],
        schema_hint: dict[str, Any] | None = None,
        options: ModelGatewayOptions | dict[str, Any] | None = None,
        *,
        project_id: str = "local_project",
        agent_role: str | None = None,
        service_name: str = "ModelGatewayService.generate_json",
        operation_name: str = "generate_json",
    ) -> ModelGatewayJsonResult:
        record = self.runtime_logs.begin_call(
            project_id=self._runtime_project_id(project_id),
            agent_role=agent_role or "all",
            service_name=service_name,
            operation_name=operation_name,
            request_type="generate_json",
        )
        try:
            self._attach_runtime_status_metadata(record.call_id, agent_role=agent_role)
            config = self.get_active_model_config()
            self._attach_runtime_config_metadata(record.call_id, config, agent_role)
            request = self._build_request(
                config=config,
                messages=messages,
                options=options,
                response_format="json",
                schema_hint=schema_hint,
            )
            adapter = self._get_adapter(config, request=request)

            raw_text = self._call_json_provider(
                adapter=adapter,
                request=request,
                config=config,
                call_id=record.call_id,
                retry_attempt=1,
            )
            try:
                data = self._parse_json_object(raw_text)
            except ModelJsonParseError:
                retry_request = self._build_json_retry_request(config, request)
                raw_text = self._call_json_provider(
                    adapter=adapter,
                    request=retry_request,
                    config=config,
                    call_id=record.call_id,
                    retry_attempt=2,
                )
                data = self._parse_json_object(raw_text)
            completed_record = self.runtime_logs.finish_success(
                record.call_id,
                adapter_success=True,
                json_parse_success=True,
            )
            self._refresh_provider_health_safely()
        except ModelConfigurationError as exc:
            failed_record = self.runtime_logs.finish_failure(
                record.call_id,
                safe_error=self.runtime_error_sanitizer.sanitize(
                    exc,
                    stage="config_check",
                ),
                adapter_success=False,
                json_parse_success=None,
            )
            self._attach_error_call_metadata(exc, failed_record)
            self._refresh_provider_health_safely()
            raise
        except ModelCallError as exc:
            failed_record = self.runtime_logs.finish_failure(
                record.call_id,
                safe_error=self.runtime_error_sanitizer.sanitize(
                    exc,
                    stage="adapter_request",
                ),
                adapter_success=False,
                json_parse_success=None,
            )
            self._attach_error_call_metadata(exc, failed_record)
            self._refresh_provider_health_safely()
            raise
        except ModelJsonParseError as exc:
            failed_record = self.runtime_logs.finish_failure(
                record.call_id,
                safe_error=self.runtime_error_sanitizer.sanitize(
                    exc,
                    stage="json_parse",
                    error_type="json_parse_error",
                ),
                adapter_success=True,
                json_parse_success=False,
            )
            self._attach_error_call_metadata(exc, failed_record)
            self._refresh_provider_health_safely()
            raise
        except Exception as exc:
            self.runtime_logs.finish_failure(
                record.call_id,
                safe_error=self.runtime_error_sanitizer.sanitize(exc),
                adapter_success=False,
                json_parse_success=None,
            )
            self._refresh_provider_health_safely()
            raise
        return ModelGatewayJsonResult(
            data=data,
            raw_text=raw_text,
            provider_id=config.provider.provider_id,
            model_name=config.model_profile.model_name,
            call_id=completed_record.call_id,
            latency_ms=completed_record.latency_ms,
        )

    def validate_model_config(self) -> ModelGatewayStatusResponse:
        issues: list[str] = []
        provider = self._read_optional_provider(issues)
        model_profile = self._read_optional_model_profile(issues)
        assignment = self._read_optional_assignment(issues)

        if provider is not None:
            self._validate_provider(provider, issues)
        if model_profile is not None:
            self._validate_model_profile(model_profile, provider, issues)
        if assignment is not None:
            self._validate_assignment(assignment, model_profile, issues)

        configured = (
            provider is not None
            and model_profile is not None
            and assignment is not None
            and len(issues) == 0
        )
        return ModelGatewayStatusResponse(
            configured=configured,
            provider_type=provider.provider_type if provider else None,
            model_name=model_profile.model_name if model_profile else None,
            api_key_ref=self._safe_display_api_key_ref(provider.api_key_ref)
            if provider
            else "",
            active_assignment=assignment.assignment_id if assignment else None,
            issues=issues,
        )

    def seed_default_model_config(self) -> ModelGatewaySeedResponse:
        created_files: list[str] = []
        existing_files: list[str] = []
        updated_files: list[str] = []

        provider = self._default_provider()
        provider_created = self.store.write_if_missing(
            self.provider_file,
            model_to_dict(provider),
        )
        if provider_created:
            created_files.append(self.provider_file.name)
        else:
            existing_files.append(self.provider_file.name)
            provider = self._read_optional_provider([]) or provider

        model_profile = self._default_model_profile(provider)
        model_created = self.store.write_if_missing(
            self.model_profile_file,
            model_to_dict(model_profile),
        )
        if model_created:
            created_files.append(self.model_profile_file.name)
        else:
            existing_files.append(self.model_profile_file.name)
            model_profile = self._read_optional_model_profile([]) or model_profile

        assignment = self._default_assignment(model_profile)
        assignment_created = self.store.write_if_missing(
            self.assignment_file,
            model_to_dict(assignment),
        )
        if assignment_created:
            created_files.append(self.assignment_file.name)
        else:
            existing_files.append(self.assignment_file.name)

        return ModelGatewaySeedResponse(
            ready=self.validate_model_config().configured,
            created_files=created_files,
            existing_files=existing_files,
            updated_files=updated_files,
            status=self.validate_model_config(),
        )

    def configure_deepseek_active_model(
        self,
        *,
        model_name: str = DEEPSEEK_DEFAULT_MODEL,
        require_env: bool = True,
    ) -> ModelGatewaySeedResponse:
        if model_name not in {DEEPSEEK_DEFAULT_MODEL, DEEPSEEK_HIGH_QUALITY_MODEL}:
            raise ModelConfigurationError(
                "DeepSeek 模型名不支持。请使用 deepseek-v4-flash 或 deepseek-v4-pro。"
            )
        if require_env and os.environ.get("DEEPSEEK_API_KEY") is None:
            raise ModelConfigurationError(
                "DeepSeek API Key 未配置。请设置 DEEPSEEK_API_KEY 环境变量。"
            )

        created_files: list[str] = []
        existing_files: list[str] = []
        updated_files: list[str] = []

        provider = self._deepseek_provider(model_name)
        model_profile = self._deepseek_model_profile(provider, model_name)
        assignment = self._deepseek_assignment(model_profile)

        for path, data in [
            (self.provider_file, model_to_dict(provider)),
            (self.model_profile_file, model_to_dict(model_profile)),
            (self.assignment_file, model_to_dict(assignment)),
        ]:
            if self.store.exists(path):
                existing_files.append(path.name)
                updated_files.append(path.name)
            else:
                created_files.append(path.name)
            self.store.write(path, data)

        return ModelGatewaySeedResponse(
            ready=self.validate_model_config().configured,
            created_files=created_files,
            existing_files=existing_files,
            updated_files=updated_files,
            status=self.validate_model_config(),
        )

    def configure_qwen_active_model(
        self,
        *,
        model_name: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        require_env: bool = True,
    ) -> ModelGatewaySeedResponse:
        clean_model_name = (
            model_name or os.environ.get("QWEN_MODEL_NAME") or QWEN_DEFAULT_MODEL
        ).strip()
        clean_base_url = (
            base_url or os.environ.get("QWEN_BASE_URL") or QWEN_DEFAULT_BASE_URL
        ).strip()
        clean_api_key_env = (
            api_key_env
            or os.environ.get("QWEN_API_KEY_ENV")
            or QWEN_DEFAULT_API_KEY_ENV
        ).strip()
        if not clean_model_name:
            raise ModelConfigurationError("Qwen model_name must not be empty.")
        if not clean_base_url:
            raise ModelConfigurationError("Qwen base_url must not be empty.")
        if not clean_api_key_env:
            raise ModelConfigurationError("Qwen api_key_env must not be empty.")
        try:
            clean_base_url = validate_model_endpoint_policy(
                provider_type="qwen",
                base_url=clean_base_url,
                api_key_ref=f"env:{clean_api_key_env}",
            )
        except ModelEndpointPolicyError as exc:
            raise ModelConfigurationError(str(exc)) from exc
        if require_env and os.environ.get(clean_api_key_env) is None:
            raise ModelConfigurationError(
                f"Qwen API Key is not configured. Set {clean_api_key_env}."
            )

        created_files: list[str] = []
        existing_files: list[str] = []
        updated_files: list[str] = []

        provider = self._qwen_provider(
            model_name=clean_model_name,
            base_url=clean_base_url,
            api_key_env=clean_api_key_env,
        )
        model_profile = self._qwen_model_profile(provider, clean_model_name)
        assignment = self._qwen_assignment(model_profile)

        for path, data in [
            (self.provider_file, model_to_dict(provider)),
            (self.model_profile_file, model_to_dict(model_profile)),
            (self.assignment_file, model_to_dict(assignment)),
        ]:
            if self.store.exists(path):
                existing_files.append(path.name)
                updated_files.append(path.name)
            else:
                created_files.append(path.name)
            self.store.write(path, data)

        return ModelGatewaySeedResponse(
            ready=self.validate_model_config().configured,
            created_files=created_files,
            existing_files=existing_files,
            updated_files=updated_files,
            status=self.validate_model_config(),
        )

    def _read_required_config(
        self,
    ) -> tuple[ModelProviderProfile, ModelProfile, AgentModelAssignment]:
        provider = self._read_provider()
        model_profile = self._read_model_profile()
        assignment = self._read_assignment()
        return provider, model_profile, assignment

    def _runtime_project_id(self, project_id: str) -> str:
        if project_id and project_id != "local_project":
            return project_id
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=project_id or "local_project",
        )

    def _read_provider(self) -> ModelProviderProfile:
        data = self.store.read(self.provider_file)
        try:
            return ModelProviderProfile(**data)
        except ValidationError as exc:
            raise StorageError(f"JSON schema is invalid: {self.provider_file}") from exc

    def _read_model_profile(self) -> ModelProfile:
        data = self.store.read(self.model_profile_file)
        try:
            return ModelProfile(**data)
        except ValidationError as exc:
            raise StorageError(
                f"JSON schema is invalid: {self.model_profile_file}"
            ) from exc

    def _read_assignment(self) -> AgentModelAssignment:
        data = self.store.read(self.assignment_file)
        try:
            return AgentModelAssignment(**data)
        except ValidationError as exc:
            raise StorageError(f"JSON schema is invalid: {self.assignment_file}") from exc

    def _read_optional_provider(
        self,
        issues: list[str],
    ) -> ModelProviderProfile | None:
        try:
            return self._read_provider()
        except StorageError as exc:
            issues.append(str(exc))
            return None

    def _read_optional_model_profile(self, issues: list[str]) -> ModelProfile | None:
        try:
            return self._read_model_profile()
        except StorageError as exc:
            issues.append(str(exc))
            return None

    def _read_optional_assignment(
        self,
        issues: list[str],
    ) -> AgentModelAssignment | None:
        try:
            return self._read_assignment()
        except StorageError as exc:
            issues.append(str(exc))
            return None

    def _validate_provider(
        self,
        provider: ModelProviderProfile,
        issues: list[str],
    ) -> None:
        if not provider.provider_id:
            issues.append("ModelProviderProfile.provider_id must not be empty.")
        if provider.provider_type not in ALLOWED_PROVIDER_TYPES:
            issues.append("ModelProviderProfile.provider_type is not allowed.")
        if provider.provider_type not in {
            "local",
            "openai",
            "openai_compatible",
            "deepseek",
            "qwen",
        }:
            issues.append(
                "ModelProviderProfile.provider_type is reserved but not callable in Milestone 3.5."
            )
        if (
            provider.provider_type in {"openai_compatible", "deepseek", "qwen"}
            and not provider.base_url
        ):
            issues.append("ModelProviderProfile.base_url is required for this provider_type.")
        if provider.auth_type not in ALLOWED_AUTH_TYPES:
            issues.append("ModelProviderProfile.auth_type is not allowed.")
        if not provider.default_model:
            issues.append("ModelProviderProfile.default_model must not be empty.")
        if not provider.enabled:
            issues.append("ModelProviderProfile.enabled must be true.")
        if provider.api_key_ref and self._looks_like_plaintext_secret(
            provider.api_key_ref
        ):
            issues.append("ModelProviderProfile.api_key_ref must be a safe reference.")
        if provider.auth_type == "none":
            return
        if not provider.api_key_ref:
            issues.append("ModelProviderProfile.api_key_ref is required for this auth_type.")
            return
        if not provider.api_key_ref.startswith(SAFE_KEY_REF_PREFIXES):
            issues.append("ModelProviderProfile.api_key_ref must use a safe reference prefix.")
            return
        if provider.api_key_ref.startswith("env:"):
            env_name = provider.api_key_ref.removeprefix("env:")
            if not env_name:
                issues.append("ModelProviderProfile.api_key_ref env name is empty.")
            elif os.environ.get(env_name) is None:
                issues.append("ModelProviderProfile.api_key_ref env variable is not set.")
        elif provider.provider_type != "local":
            issues.append(
                "Only env: API key refs are resolvable by Milestone 3.5 runtime."
            )

    def _validate_model_profile(
        self,
        model_profile: ModelProfile,
        provider: ModelProviderProfile | None,
        issues: list[str],
    ) -> None:
        if not model_profile.model_profile_id:
            issues.append("ModelProfile.model_profile_id must not be empty.")
        if not model_profile.provider_id:
            issues.append("ModelProfile.provider_id must not be empty.")
        if not model_profile.model_name:
            issues.append("ModelProfile.model_name must not be empty.")
        if model_profile.cost_tier not in ALLOWED_COST_TIERS:
            issues.append("ModelProfile.cost_tier is not allowed.")
        if model_profile.quality_tier not in ALLOWED_QUALITY_TIERS:
            issues.append("ModelProfile.quality_tier is not allowed.")
        if model_profile.status not in ALLOWED_MODEL_STATUS:
            issues.append("ModelProfile.status is not allowed.")
        if model_profile.status != "active":
            issues.append("ModelProfile.status must be active.")
        if provider and model_profile.provider_id != provider.provider_id:
            issues.append("ModelProfile.provider_id must point to ModelProviderProfile.")
        if provider and model_profile.model_name != provider.default_model:
            issues.append("ModelProfile.model_name must match provider.default_model.")

    def _validate_assignment(
        self,
        assignment: AgentModelAssignment,
        model_profile: ModelProfile | None,
        issues: list[str],
    ) -> None:
        if not assignment.assignment_id:
            issues.append("AgentModelAssignment.assignment_id must not be empty.")
        if assignment.agent_role not in ALLOWED_AGENT_ROLES:
            issues.append("AgentModelAssignment.agent_role is not allowed.")
        if assignment.routing_policy not in ALLOWED_ROUTING_POLICIES:
            issues.append("AgentModelAssignment.routing_policy is not allowed.")
        if assignment.routing_policy != "single_model":
            issues.append("AgentModelAssignment.routing_policy must be single_model in Milestone 3.5.")
        if assignment.fallback_model_profile_id:
            issues.append("AgentModelAssignment fallback is reserved for later milestones.")
        if assignment.temperature < 0 or assignment.temperature > 2:
            issues.append("AgentModelAssignment.temperature must be between 0 and 2.")
        if assignment.max_output_tokens <= 0:
            issues.append("AgentModelAssignment.max_output_tokens must be greater than 0.")
        if (
            model_profile
            and assignment.primary_model_profile_id != model_profile.model_profile_id
        ):
            issues.append(
                "AgentModelAssignment.primary_model_profile_id must point to ModelProfile."
            )

    def _build_request(
        self,
        config: ActiveModelConfig,
        messages: list[ModelGatewayMessage | dict[str, Any]],
        options: ModelGatewayOptions | dict[str, Any] | None,
        response_format: str,
        schema_hint: dict[str, Any] | None = None,
    ) -> ModelGatewayRequest:
        normalized_options = self._normalize_options(options)
        temperature = (
            normalized_options.temperature
            if normalized_options and normalized_options.temperature is not None
            else config.assignment.temperature
        )
        max_output_tokens = (
            normalized_options.max_output_tokens
            if normalized_options and normalized_options.max_output_tokens is not None
            else config.assignment.max_output_tokens
        )
        timeout_seconds = (
            normalized_options.timeout_seconds
            if normalized_options and normalized_options.timeout_seconds is not None
            else None
        )
        max_attempts = (
            normalized_options.max_attempts
            if normalized_options and normalized_options.max_attempts is not None
            else None
        )
        normalized_messages = self._normalize_messages(messages)
        if response_format == "json":
            normalized_messages = self._ensure_json_instruction(normalized_messages)
        if config.provider.provider_type == "qwen":
            normalized_messages = self._merge_system_messages_for_qwen(
                normalized_messages
            )
        return ModelGatewayRequest(
            messages=normalized_messages,
            model_name=config.model_profile.model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            response_format=response_format,
            schema_hint=schema_hint,
        )

    def _normalize_messages(
        self,
        messages: list[ModelGatewayMessage | dict[str, Any]],
    ) -> list[ModelGatewayMessage]:
        return [
            message
            if isinstance(message, ModelGatewayMessage)
            else ModelGatewayMessage(**message)
            for message in messages
        ]

    def _merge_system_messages_for_qwen(
        self,
        messages: list[ModelGatewayMessage],
    ) -> list[ModelGatewayMessage]:
        system_contents: list[str] = []
        non_system_messages: list[ModelGatewayMessage] = []
        saw_system = False
        for message in messages:
            if message.role.strip().lower() == "system":
                saw_system = True
                content = message.content.strip()
                if content:
                    system_contents.append(content)
            else:
                non_system_messages.append(message)
        if not saw_system:
            return messages
        if not system_contents:
            return non_system_messages
        return [
            ModelGatewayMessage(role="system", content="\n\n".join(system_contents)),
            *non_system_messages,
        ]

    def _normalize_options(
        self,
        options: ModelGatewayOptions | dict[str, Any] | None,
    ) -> ModelGatewayOptions | None:
        if options is None:
            return None
        if isinstance(options, ModelGatewayOptions):
            return options
        return ModelGatewayOptions(**options)

    def _get_adapter(
        self,
        config: ActiveModelConfig,
        *,
        request: ModelGatewayRequest | None = None,
    ) -> ModelAdapter:
        provider = config.provider
        if provider.provider_type == "local":
            return LocalMockModelAdapter()
        if provider.provider_type in {"openai", "openai_compatible", "deepseek", "qwen"}:
            provider_for_adapter = self._provider_with_default_base_url(provider)
            try:
                normalized_base_url = validate_model_endpoint_policy(
                    provider_type=provider_for_adapter.provider_type,
                    base_url=provider_for_adapter.base_url,
                    api_key_ref=provider_for_adapter.api_key_ref,
                )
            except ModelEndpointPolicyError as exc:
                raise ModelConfigurationError(str(exc)) from exc
            provider_for_adapter = self._copy_provider(
                provider_for_adapter,
                base_url=normalized_base_url,
            )
            api_key = self._resolve_api_key(provider_for_adapter.api_key_ref)
            return OpenAICompatibleModelAdapter(
                provider_for_adapter,
                api_key,
                timeout_seconds=self._adapter_timeout_seconds(provider_for_adapter, request),
                max_attempts=self._adapter_max_attempts(provider_for_adapter, request),
            )
        raise ModelCallError(
            f"Provider type {provider.provider_type!r} is not implemented in Milestone 3.5."
        )

    def _adapter_timeout_seconds(
        self,
        provider: ModelProviderProfile,
        request: ModelGatewayRequest | None,
    ) -> int:
        if request and request.timeout_seconds is not None:
            return max(1, int(request.timeout_seconds))
        if provider.provider_type == "qwen":
            raw = os.environ.get("QWEN_TIMEOUT_SECONDS")
            if raw:
                try:
                    return max(1, int(raw))
                except ValueError:
                    return QWEN_DEFAULT_TIMEOUT_SECONDS
            return QWEN_DEFAULT_TIMEOUT_SECONDS
        return OPENAI_COMPATIBLE_DEFAULT_TIMEOUT_SECONDS

    def _adapter_max_attempts(
        self,
        provider: ModelProviderProfile,
        request: ModelGatewayRequest | None,
    ) -> int:
        if request and request.max_attempts is not None:
            return max(1, int(request.max_attempts))
        if provider.provider_type == "qwen":
            raw = os.environ.get("QWEN_MAX_ATTEMPTS")
            if raw:
                try:
                    return max(1, int(raw))
                except ValueError:
                    return QWEN_DEFAULT_MAX_ATTEMPTS
            return QWEN_DEFAULT_MAX_ATTEMPTS
        return OPENAI_COMPATIBLE_DEFAULT_MAX_ATTEMPTS

    def _call_json_provider(
        self,
        *,
        adapter: ModelAdapter,
        request: ModelGatewayRequest,
        config: ActiveModelConfig,
        call_id: str,
        retry_attempt: int,
    ) -> str:
        def call_provider() -> str:
            try:
                return adapter.generate_json(request)
            except ModelAdapterError as exc:
                raise ModelCallError(str(exc)) from exc

        metadata = self._trace_metadata(
            config,
            response_format="json",
            local_call_id=call_id,
        )
        metadata["json_retry_attempt"] = retry_attempt
        return self.tracing.run_operation(
            "ModelGateway.generate_json",
            call_provider,
            run_type="llm",
            metadata=metadata,
            tags=self._trace_tags(config),
            inputs=self._trace_inputs(request),
        )

    def _build_json_retry_request(
        self,
        config: ActiveModelConfig,
        request: ModelGatewayRequest,
    ) -> ModelGatewayRequest:
        strict_retry_message = ModelGatewayMessage(
            role="system",
            content=(
                "The previous attempt did not parse as valid JSON. Retry now. "
                "Return one compact JSON object only. Do not include markdown, comments, "
                "code fences, trailing commas, or text outside JSON. Keep every string value "
                "single-line and concise. Prefer fewer array items when possible while "
                "preserving all required top-level keys."
            ),
        )
        messages = [*request.messages, strict_retry_message]
        if config.provider.provider_type == "qwen":
            messages = self._merge_system_messages_for_qwen(messages)
        return ModelGatewayRequest(
            messages=messages,
            model_name=request.model_name,
            temperature=min(request.temperature, 0.3),
            max_output_tokens=max(
                request.max_output_tokens,
                DEEPSEEK_DEFAULT_MAX_OUTPUT_TOKENS
                if config.provider.provider_type == "deepseek"
                else QWEN_DEFAULT_MAX_OUTPUT_TOKENS
                if config.provider.provider_type == "qwen"
                else request.max_output_tokens,
            ),
            timeout_seconds=request.timeout_seconds,
            max_attempts=request.max_attempts,
            response_format=request.response_format,
            schema_hint=request.schema_hint,
        )

    def _resolve_api_key(self, api_key_ref: str) -> str | None:
        if not api_key_ref:
            return None
        if api_key_ref.startswith("env:"):
            env_name = api_key_ref.removeprefix("env:")
            value = os.environ.get(env_name)
            if value is None:
                raise ModelConfigurationError(
                    f"Model API key is not configured. Set {env_name}."
                )
            return value
        raise ModelConfigurationError(
            "Model runtime only resolves env: API key references."
        )

    def _provider_with_default_base_url(
        self,
        provider: ModelProviderProfile,
    ) -> ModelProviderProfile:
        if provider.provider_type == "openai" and not provider.base_url:
            return self._copy_provider(provider, base_url="https://api.openai.com/v1")
        if provider.provider_type == "deepseek" and not provider.base_url:
            return self._copy_provider(provider, base_url=DEEPSEEK_BASE_URL)
        if provider.provider_type == "qwen" and not provider.base_url:
            return self._copy_provider(provider, base_url=QWEN_DEFAULT_BASE_URL)
        return provider

    def _copy_provider(
        self,
        provider: ModelProviderProfile,
        **updates: Any,
    ) -> ModelProviderProfile:
        if hasattr(provider, "model_copy"):
            return provider.model_copy(update=updates)
        return provider.copy(update=updates)

    def _parse_json_object(self, raw_text: str) -> dict[str, Any]:
        text = (raw_text or "").strip().lstrip("\ufeff")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            parse_error = exc
        else:
            if not isinstance(data, dict):
                raise ModelJsonParseError("模型返回 JSON 根节点必须是对象。")
            return data

        for candidate in self._json_object_recovery_candidates(text):
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
            raise ModelJsonParseError("模型返回 JSON 根节点必须是对象。")

        raise ModelJsonParseError(
            "模型返回内容不是合法 JSON，请重试或降低输出复杂度。"
        ) from parse_error

    def _json_object_recovery_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []
        for match in re.finditer(
            r"```(?:json)?\s*(.*?)```",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            fenced = match.group(1).strip()
            if fenced:
                candidates.append(fenced)

        balanced = self._extract_first_balanced_json_object(text)
        if balanced:
            candidates.append(balanced)

        result: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            result.append(candidate)
        return result

    def _extract_first_balanced_json_object(self, text: str) -> str:
        start = text.find("{")
        while start >= 0:
            candidate = self._extract_balanced_json_object_from(text, start)
            if candidate:
                return candidate
            start = text.find("{", start + 1)
        return ""

    def _extract_balanced_json_object_from(self, text: str, start: int) -> str:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return ""

    def _looks_like_plaintext_secret(self, value: str) -> bool:
        normalized = value.strip()
        candidates = [normalized]
        for prefix in SAFE_KEY_REF_PREFIXES:
            if normalized.startswith(prefix):
                candidates.append(normalized.removeprefix(prefix).strip())
        return any(
            candidate.startswith(OPENAI_KEY_PREFIX)
            or candidate.startswith(LANGSMITH_KEY_PREFIX)
            or SECRET_VALUE_SENTINEL in candidate
            for candidate in candidates
        )

    def _safe_display_api_key_ref(self, value: str) -> str:
        if not value:
            return ""
        if value.startswith(SAFE_KEY_REF_PREFIXES) and not self._looks_like_plaintext_secret(
            value
        ):
            return value
        return "[redacted-invalid-ref]"

    def _default_provider(self) -> ModelProviderProfile:
        return ModelProviderProfile(
            provider_id=DEFAULT_PROVIDER_ID,
            provider_type="local",
            display_name="Local Mock Model Provider",
            base_url="",
            auth_type="none",
            api_key_ref="",
            default_model=DEFAULT_LOCAL_MODEL_NAME,
            enabled=True,
            created_by="system",
            notes="Milestone 3.5 local mock provider. No external API key is stored.",
        )

    def _default_model_profile(self, provider: ModelProviderProfile) -> ModelProfile:
        return ModelProfile(
            model_profile_id=DEFAULT_MODEL_PROFILE_ID,
            provider_id=provider.provider_id,
            model_name=provider.default_model,
            capabilities=ModelCapabilities(
                chat=True,
                json_output=True,
                tool_calling=False,
                streaming=False,
                long_context=False,
                vision=False,
                embedding=False,
            ),
            context_window_hint=8192,
            cost_tier="low",
            quality_tier="draft",
            status="active",
        )

    def _default_assignment(
        self,
        model_profile: ModelProfile,
    ) -> AgentModelAssignment:
        return AgentModelAssignment(
            assignment_id=DEFAULT_ASSIGNMENT_ID,
            agent_role="all",
            primary_model_profile_id=model_profile.model_profile_id,
            fallback_model_profile_id=None,
            routing_policy="single_model",
            temperature=0.7,
            max_output_tokens=DEEPSEEK_DEFAULT_MAX_OUTPUT_TOKENS,
            structured_output_required=True,
        )

    def _deepseek_provider(self, model_name: str) -> ModelProviderProfile:
        return ModelProviderProfile(
            provider_id=DEEPSEEK_PROVIDER_ID,
            provider_type="deepseek",
            display_name="DeepSeek API",
            base_url=DEEPSEEK_BASE_URL,
            auth_type="bearer",
            api_key_ref="env:DEEPSEEK_API_KEY",
            default_model=model_name,
            enabled=True,
            created_by="user",
            notes="DeepSeek provider configured for Phase 2. No plaintext API key is stored.",
        )

    def _deepseek_model_profile(
        self,
        provider: ModelProviderProfile,
        model_name: str,
    ) -> ModelProfile:
        return ModelProfile(
            model_profile_id=DEEPSEEK_MODEL_PROFILE_ID
            if model_name == DEEPSEEK_DEFAULT_MODEL
            else "model_profile_deepseek_v4_pro_phase2",
            provider_id=provider.provider_id,
            model_name=model_name,
            capabilities=ModelCapabilities(
                chat=True,
                json_output=True,
                tool_calling=False,
                streaming=False,
                long_context=False,
                vision=False,
                embedding=False,
            ),
            context_window_hint=64000,
            cost_tier="low" if model_name == DEEPSEEK_DEFAULT_MODEL else "medium",
            quality_tier="standard" if model_name == DEEPSEEK_DEFAULT_MODEL else "strong",
            status="active",
        )

    def _deepseek_assignment(
        self,
        model_profile: ModelProfile,
    ) -> AgentModelAssignment:
        return AgentModelAssignment(
            assignment_id=DEEPSEEK_ASSIGNMENT_ID,
            agent_role="all",
            primary_model_profile_id=model_profile.model_profile_id,
            fallback_model_profile_id=None,
            routing_policy="single_model",
            temperature=0.7,
            max_output_tokens=2000,
            structured_output_required=True,
        )

    def _qwen_provider(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key_env: str,
    ) -> ModelProviderProfile:
        return ModelProviderProfile(
            provider_id=QWEN_PROVIDER_ID,
            provider_type="qwen",
            display_name="Qwen API",
            base_url=base_url.rstrip("/"),
            auth_type="bearer",
            api_key_ref=f"env:{api_key_env}",
            default_model=model_name,
            enabled=True,
            created_by="user",
            notes=(
                "Qwen provider configured for Phase 4 through an OpenAI-compatible "
                "chat completions API. No plaintext API key is stored."
            ),
        )

    def _qwen_model_profile(
        self,
        provider: ModelProviderProfile,
        model_name: str,
    ) -> ModelProfile:
        return ModelProfile(
            model_profile_id=QWEN_MODEL_PROFILE_ID,
            provider_id=provider.provider_id,
            model_name=model_name,
            capabilities=ModelCapabilities(
                chat=True,
                json_output=True,
                tool_calling=False,
                streaming=False,
                long_context=True,
                vision=False,
                embedding=False,
            ),
            context_window_hint=262144,
            cost_tier="medium",
            quality_tier="strong",
            status="active",
        )

    def _qwen_assignment(
        self,
        model_profile: ModelProfile,
    ) -> AgentModelAssignment:
        return AgentModelAssignment(
            assignment_id=QWEN_ASSIGNMENT_ID,
            agent_role="all",
            primary_model_profile_id=model_profile.model_profile_id,
            fallback_model_profile_id=None,
            routing_policy="single_model",
            temperature=0.7,
            max_output_tokens=QWEN_DEFAULT_MAX_OUTPUT_TOKENS,
            structured_output_required=True,
        )

    def _trace_metadata(
        self,
        config: ActiveModelConfig,
        *,
        response_format: str,
        local_call_id: str | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "provider_type": config.provider.provider_type,
            "provider_id": config.provider.provider_id,
            "model_name": config.model_profile.model_name,
            "response_format": response_format,
            "agent_role": config.assignment.agent_role,
        }
        if local_call_id:
            metadata["local_call_id"] = local_call_id
        return metadata

    def _trace_tags(self, config: ActiveModelConfig) -> list[str]:
        tags = [
            "model_gateway",
            config.provider.provider_type,
            config.model_profile.model_name,
        ]
        if config.provider.provider_type == "deepseek":
            tags.append("deepseek")
        if config.provider.provider_type == "qwen":
            tags.append("qwen")
        return tags

    def _trace_inputs(self, request: ModelGatewayRequest) -> dict[str, Any]:
        return {
            "messages": [model_to_dict(message) for message in request.messages],
            "model_name": request.model_name,
            "temperature": request.temperature,
            "max_output_tokens": request.max_output_tokens,
            "timeout_seconds": request.timeout_seconds,
            "max_attempts": request.max_attempts,
            "response_format": request.response_format,
            "schema_hint": request.schema_hint,
        }

    def _ensure_json_instruction(
        self,
        messages: list[ModelGatewayMessage],
    ) -> list[ModelGatewayMessage]:
        if any("json" in message.content.lower() for message in messages):
            return messages
        return [
            ModelGatewayMessage(
                role="system",
                content="Return valid JSON only. Do not include markdown.",
            ),
            *messages,
        ]

    def _attach_runtime_status_metadata(
        self,
        call_id: str,
        *,
        agent_role: str | None = None,
    ) -> None:
        provider = self._read_optional_provider([])
        model_profile = self._read_optional_model_profile([])
        assignment = self._read_optional_assignment([])
        self.runtime_logs.attach_model_metadata(
            call_id,
            agent_role=agent_role or (assignment.agent_role if assignment else "all"),
            provider_id=provider.provider_id if provider else "",
            provider_type=provider.provider_type if provider else "",
            model_profile_id=model_profile.model_profile_id if model_profile else "",
            model_name=model_profile.model_name if model_profile else "",
        )

    def _attach_runtime_config_metadata(
        self,
        call_id: str,
        config: ActiveModelConfig,
        agent_role: str | None,
    ) -> None:
        self.runtime_logs.attach_model_metadata(
            call_id,
            agent_role=agent_role or config.assignment.agent_role,
            provider_id=config.provider.provider_id,
            provider_type=config.provider.provider_type,
            model_profile_id=config.model_profile.model_profile_id,
            model_name=config.model_profile.model_name,
        )

    def _refresh_provider_health_safely(self) -> None:
        try:
            self.provider_health.refresh_provider_health()
        except StorageError:
            raise
        except Exception:
            return

    def _attach_error_call_metadata(
        self,
        error: ModelGatewayError,
        record,
    ) -> None:
        error.call_id = record.call_id
        error.latency_ms = record.latency_ms
