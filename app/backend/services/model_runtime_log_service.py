from pathlib import Path
from typing import Any
from uuid import uuid4
from datetime import datetime, timezone

from pydantic import ValidationError

from app.backend.core.config import settings
from app.backend.models.model_runtime import (
    MODEL_RUNTIME_SCHEMA_VERSION,
    ModelCallRecord,
    ModelRuntimeLogs,
    ProviderHealth,
    RuntimeErrorRecord,
    TokenUsage,
)
from app.backend.services.runtime_error_sanitizer import SafeRuntimeError
from app.backend.storage.json_store import JsonStore, StorageError


MAX_MODEL_CALL_RECORDS = 500
MAX_RUNTIME_ERRORS = 200


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ModelRuntimeLogService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.logs_file = self.data_dir / "model_runtime_logs.json"

    def create_call_id(self) -> str:
        return f"model_call_{uuid4().hex[:16]}"

    def begin_call(
        self,
        *,
        project_id: str = "local_project",
        agent_role: str = "all",
        service_name: str = "ModelGatewayService",
        operation_name: str = "",
        request_type: str = "",
    ) -> ModelCallRecord:
        now = utc_now()
        call_id = self.create_call_id()
        record = ModelCallRecord(
            call_id=call_id,
            project_id=project_id,
            agent_role=agent_role,
            service_name=service_name,
            operation_name=operation_name,
            request_type=request_type,
            started_at=now,
            created_at=now,
            local_trace_id=call_id,
            version_id=MODEL_RUNTIME_SCHEMA_VERSION,
        )
        logs = self._read_logs()
        logs.model_call_records.append(record)
        self._save_logs(logs)
        return record

    def attach_model_metadata(
        self,
        call_id: str,
        *,
        agent_role: str,
        provider_id: str,
        provider_type: str,
        model_profile_id: str,
        model_name: str,
    ) -> ModelCallRecord:
        logs = self._read_logs()
        record = self._find_record(logs, call_id)
        record.agent_role = agent_role
        record.provider_id = provider_id
        record.provider_type = provider_type
        record.model_profile_id = model_profile_id
        record.model_name = model_name
        self._save_logs(logs)
        return record

    def finish_success(
        self,
        call_id: str,
        *,
        adapter_success: bool = True,
        json_parse_success: bool | None = None,
        token_usage: TokenUsage | None = None,
    ) -> ModelCallRecord:
        logs = self._read_logs()
        record = self._find_record(logs, call_id)
        ended_at = utc_now()
        record.ended_at = ended_at
        record.latency_ms = self._latency_ms(record.started_at, ended_at)
        record.success = True
        record.adapter_success = adapter_success
        record.json_parse_success = json_parse_success
        record.error_type = None
        record.error_message_safe = None
        record.retryable = False
        record.token_usage = token_usage or TokenUsage()
        self._save_logs(logs)
        return record

    def finish_failure(
        self,
        call_id: str,
        *,
        safe_error: SafeRuntimeError,
        adapter_success: bool = False,
        json_parse_success: bool | None = None,
    ) -> ModelCallRecord:
        logs = self._read_logs()
        record = self._find_record(logs, call_id)
        ended_at = utc_now()
        record.ended_at = ended_at
        record.latency_ms = self._latency_ms(record.started_at, ended_at)
        record.success = False
        record.adapter_success = adapter_success
        record.json_parse_success = json_parse_success
        record.error_type = safe_error.error_type
        record.error_message_safe = safe_error.error_message_safe
        record.retryable = safe_error.retryable
        logs.runtime_errors.append(
            RuntimeErrorRecord(
                error_id=f"runtime_error_{uuid4().hex[:16]}",
                call_id=record.call_id,
                project_id=record.project_id,
                stage=safe_error.stage,
                error_type=safe_error.error_type,
                error_message_safe=safe_error.error_message_safe,
                retryable=safe_error.retryable,
                provider_type=record.provider_type,
                model_name=record.model_name,
                service_name=record.service_name,
                suggested_action=safe_error.suggested_action,
                user_visible_message=safe_error.user_visible_message,
                created_at=ended_at,
            )
        )
        self._save_logs(logs)
        return record

    def upsert_provider_health(self, health: ProviderHealth) -> None:
        logs = self._read_logs()
        updated: list[ProviderHealth] = []
        replaced = False
        for existing in logs.provider_health:
            if (
                existing.provider_id == health.provider_id
                and existing.model_name == health.model_name
            ):
                updated.append(health)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(health)
        logs.provider_health = updated
        self._save_logs(logs)

    def recent_calls(
        self,
        *,
        limit: int = 20,
        success: bool | None = None,
        agent_role: str | None = None,
        request_type: str | None = None,
    ) -> list[ModelCallRecord]:
        safe_limit = max(1, min(limit, 100))
        records = list(reversed(self._read_logs().model_call_records))
        if success is not None:
            records = [record for record in records if record.success == success]
        if agent_role:
            records = [record for record in records if record.agent_role == agent_role]
        if request_type:
            records = [
                record for record in records if record.request_type == request_type
            ]
        return records[:safe_limit]

    def recent_errors(self, *, limit: int = 20) -> list[RuntimeErrorRecord]:
        safe_limit = max(1, min(limit, 100))
        return list(reversed(self._read_logs().runtime_errors))[:safe_limit]

    def get_call(self, call_id: str) -> ModelCallRecord | None:
        logs = self._read_logs()
        return next(
            (record for record in logs.model_call_records if record.call_id == call_id),
            None,
        )

    def read_logs(self) -> ModelRuntimeLogs:
        return self._read_logs()

    def _read_logs(self) -> ModelRuntimeLogs:
        if not self.store.exists(self.logs_file):
            return ModelRuntimeLogs()
        try:
            return ModelRuntimeLogs(**self.store.read(self.logs_file))
        except (StorageError, ValidationError) as exc:
            raise StorageError("Model runtime logs JSON schema is invalid.") from exc

    def _save_logs(self, logs: ModelRuntimeLogs) -> None:
        logs.model_call_records = logs.model_call_records[-MAX_MODEL_CALL_RECORDS:]
        logs.runtime_errors = logs.runtime_errors[-MAX_RUNTIME_ERRORS:]
        logs.metadata.schema_version = MODEL_RUNTIME_SCHEMA_VERSION
        logs.metadata.updated_at = utc_now()
        self.store.write(self.logs_file, model_to_dict(logs))

    def _find_record(
        self,
        logs: ModelRuntimeLogs,
        call_id: str,
    ) -> ModelCallRecord:
        for record in logs.model_call_records:
            if record.call_id == call_id:
                return record
        raise StorageError(f"Model call record was not found: {call_id}")

    def _latency_ms(self, started_at: str, ended_at: str) -> int:
        try:
            started = datetime.fromisoformat(started_at)
            ended = datetime.fromisoformat(ended_at)
            return max(0, int((ended - started).total_seconds() * 1000))
        except ValueError:
            return 0
