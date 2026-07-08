from fastapi import APIRouter, HTTPException, Query

from app.backend.models.model_runtime import (
    ModelRuntimeCallsResponse,
    ModelRuntimeErrorsResponse,
    ModelRuntimeHealthCheckResponse,
    ModelRuntimeStatusResponse,
)
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.model_runtime_log_service import ModelRuntimeLogService
from app.backend.services.runtime_error_sanitizer import RuntimeErrorSanitizer
from app.backend.storage.json_store import StorageError

router = APIRouter()
model_gateway_service = ModelGatewayService()
runtime_logs = ModelRuntimeLogService(
    store=model_gateway_service.store,
    data_dir=model_gateway_service.data_dir,
)
runtime_error_sanitizer = RuntimeErrorSanitizer()


@router.get("/status", response_model=ModelRuntimeStatusResponse)
def get_model_runtime_status() -> ModelRuntimeStatusResponse:
    try:
        return model_gateway_service.provider_health.build_status_response()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/calls", response_model=ModelRuntimeCallsResponse)
def get_model_runtime_calls(
    limit: int = Query(20, ge=1, le=100),
    success: bool | None = None,
    agent_role: str | None = None,
    request_type: str | None = None,
) -> ModelRuntimeCallsResponse:
    try:
        return ModelRuntimeCallsResponse(
            calls=runtime_logs.recent_calls(
                limit=limit,
                success=success,
                agent_role=agent_role,
                request_type=request_type,
            )
        )
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/calls/{call_id}")
def get_model_runtime_call(call_id: str):
    try:
        record = runtime_logs.get_call(call_id)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Model call record was not found.")
    return record


@router.get("/errors", response_model=ModelRuntimeErrorsResponse)
def get_model_runtime_errors(
    limit: int = Query(20, ge=1, le=100),
) -> ModelRuntimeErrorsResponse:
    try:
        return ModelRuntimeErrorsResponse(errors=runtime_logs.recent_errors(limit=limit))
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/health-check", response_model=ModelRuntimeHealthCheckResponse)
def run_model_runtime_health_check() -> ModelRuntimeHealthCheckResponse:
    try:
        result = model_gateway_service.generate_json(
            [
                {
                    "role": "user",
                    "content": 'Return valid JSON only. Return exactly {"ping":"ok"}.',
                }
            ],
            options={"temperature": 0, "max_output_tokens": 64},
            service_name="ModelRuntimeHealthCheck",
            operation_name="manual_health_check",
        )
        health = model_gateway_service.provider_health.build_provider_health()
        return ModelRuntimeHealthCheckResponse(
            ok=True,
            status=health.status,
            message="模型连接检查成功。",
            call_id=result.call_id,
            latency_ms=result.latency_ms,
            provider_health=health,
            data={"ping": str(result.data.get("ping") or "")},
        )
    except (ModelConfigurationError, ModelCallError, ModelJsonParseError) as exc:
        health = model_gateway_service.provider_health.build_provider_health()
        safe_error = runtime_error_sanitizer.sanitize(exc)
        return ModelRuntimeHealthCheckResponse(
            ok=False,
            status=health.status,
            message=safe_error.user_visible_message,
            call_id=exc.call_id,
            latency_ms=exc.latency_ms,
            provider_health=health,
        )
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
