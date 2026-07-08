import os
from pathlib import Path

from app.backend.core.config import settings
from app.backend.models.model_runtime import (
    ModelRuntimeStatusResponse,
    ProviderHealth,
    RecentModelCallSummary,
)
from app.backend.services.model_runtime_log_service import (
    ModelRuntimeLogService,
    utc_now,
)
from app.backend.services.tracing_service import TracingService
from app.backend.storage.json_store import JsonStore


class ProviderHealthService:
    def __init__(
        self,
        *,
        model_gateway,
        runtime_logs: ModelRuntimeLogService | None = None,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.model_gateway = model_gateway
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.runtime_logs = runtime_logs or ModelRuntimeLogService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.tracing = TracingService()

    def refresh_provider_health(self) -> ProviderHealth:
        health = self.build_provider_health()
        self.runtime_logs.upsert_provider_health(health)
        return health

    def build_status_response(self) -> ModelRuntimeStatusResponse:
        logs = self.runtime_logs.read_logs()
        health = self.build_provider_health()
        recent_calls = self.runtime_logs.recent_calls(limit=10)
        recent_window = recent_calls[:20]
        return ModelRuntimeStatusResponse(
            provider_health=[health],
            recent_calls=[
                RecentModelCallSummary(
                    call_id=record.call_id,
                    request_type=record.request_type,
                    provider_type=record.provider_type,
                    model_name=record.model_name,
                    success=record.success,
                    latency_ms=record.latency_ms,
                    error_type=record.error_type,
                    error_message_safe=record.error_message_safe,
                    started_at=record.started_at,
                    ended_at=record.ended_at,
                )
                for record in recent_calls
            ],
            recent_success_count=sum(1 for record in recent_window if record.success),
            recent_failure_count=sum(
                1 for record in recent_window if record.ended_at and not record.success
            ),
            recent_json_parse_failure_count=sum(
                1
                for record in recent_window
                if record.json_parse_success is False
            ),
            tracing=self.tracing.get_status(),
            updated_at=logs.metadata.updated_at or utc_now(),
        )

    def build_provider_health(self) -> ProviderHealth:
        status = self.model_gateway.validate_model_config()
        provider = self.model_gateway._read_optional_provider([])
        model_profile = self.model_gateway._read_optional_model_profile([])
        provider_id = provider.provider_id if provider else ""
        provider_type = provider.provider_type if provider else status.provider_type or ""
        model_name = (
            model_profile.model_name if model_profile else status.model_name or ""
        )
        api_key_ref = provider.api_key_ref if provider else ""
        env_value_present = False
        if api_key_ref.startswith("env:"):
            env_name = api_key_ref.removeprefix("env:")
            env_value_present = bool(env_name and os.environ.get(env_name))

        recent_records = [
            record
            for record in self.runtime_logs.recent_calls(limit=50)
            if (
                (provider_id and record.provider_id == provider_id)
                or (model_name and record.model_name == model_name)
                or (not provider_id and not model_name)
            )
        ]
        recent_success_count = sum(1 for record in recent_records if record.success)
        recent_failure_count = sum(
            1 for record in recent_records if record.ended_at and not record.success
        )
        recent_json_parse_failure_count = sum(
            1 for record in recent_records if record.json_parse_success is False
        )
        last_success = next((record for record in recent_records if record.success), None)
        last_failure = next(
            (record for record in recent_records if record.ended_at and not record.success),
            None,
        )
        last_record = recent_records[0] if recent_records else None

        health_status = self._status_from(
            configured=status.configured,
            issues=status.issues,
            provider=provider,
            api_key_ref=api_key_ref,
            env_value_present=env_value_present,
            recent_success_count=recent_success_count,
            recent_failure_count=recent_failure_count,
            last_record=last_record,
        )
        return ProviderHealth(
            provider_id=provider_id,
            provider_type=provider_type,
            model_name=model_name,
            status=health_status,
            configured=status.configured,
            api_key_ref_present=bool(api_key_ref),
            api_key_value_present_in_env=env_value_present,
            last_success_at=last_success.ended_at if last_success else None,
            last_failure_at=last_failure.ended_at if last_failure else None,
            last_latency_ms=last_record.latency_ms if last_record else 0,
            recent_success_count=recent_success_count,
            recent_failure_count=recent_failure_count,
            recent_json_parse_failure_count=recent_json_parse_failure_count,
            last_error_type=last_failure.error_type if last_failure else None,
            last_error_message_safe=(
                last_failure.error_message_safe if last_failure else None
            ),
            updated_at=utc_now(),
        )

    def _status_from(
        self,
        *,
        configured: bool,
        issues: list[str],
        provider,
        api_key_ref: str,
        env_value_present: bool,
        recent_success_count: int,
        recent_failure_count: int,
        last_record,
    ) -> str:
        if provider is None:
            return "not_configured"
        if api_key_ref and api_key_ref.startswith("env:") and not env_value_present:
            return "missing_key"
        if not configured:
            issue_text = " ".join(issues).lower()
            if "env variable is not set" in issue_text or "api key" in issue_text:
                return "missing_key"
            return "not_configured"
        if not last_record:
            return "unknown"
        if last_record.success:
            if recent_failure_count >= 3 and recent_failure_count > recent_success_count:
                return "degraded"
            return "healthy"
        if recent_failure_count >= 3 and recent_success_count == 0:
            return "failing"
        return "degraded"
