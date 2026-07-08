from fastapi import APIRouter, HTTPException

from ..models.formal_apply_execution import (
    ControlledApplyWriteAuditListResponse,
    FormalApplyExecutionReadiness,
    FormalApplyExecutionRequest,
    FormalApplyExecutionResult,
    FormalApplyExecutionResultListResponse,
    FormalApplyExecutionStatusResponse,
    FormalApplyRollbackRefListResponse,
)
from ..services.controlled_formal_apply_executor_service import ControlledFormalApplyExecutorService
from ..storage.json_store import StorageError


router = APIRouter()
controlled_formal_apply_executor_service = ControlledFormalApplyExecutorService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if "FORBIDDEN_STORAGE_MUTATION" in message:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=FormalApplyExecutionStatusResponse)
def get_formal_apply_execution_status() -> FormalApplyExecutionStatusResponse:
    try:
        return controlled_formal_apply_executor_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/approvals/{approval_id}/readiness", response_model=FormalApplyExecutionReadiness)
def get_formal_apply_execution_readiness(approval_id: str) -> FormalApplyExecutionReadiness:
    try:
        return controlled_formal_apply_executor_service.get_approval_readiness(approval_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/approvals/{approval_id}/execute", response_model=FormalApplyExecutionResult)
def execute_formal_apply_approval(
    approval_id: str,
    request: FormalApplyExecutionRequest,
) -> FormalApplyExecutionResult:
    try:
        return controlled_formal_apply_executor_service.execute_approval(approval_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/executions", response_model=FormalApplyExecutionResultListResponse)
def list_formal_apply_execution_results() -> FormalApplyExecutionResultListResponse:
    try:
        return controlled_formal_apply_executor_service.list_execution_results()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/executions/{execution_result_id}", response_model=FormalApplyExecutionResult)
def get_formal_apply_execution_result(execution_result_id: str) -> FormalApplyExecutionResult:
    try:
        return controlled_formal_apply_executor_service.get_execution_result(execution_result_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/rollback-refs", response_model=FormalApplyRollbackRefListResponse)
def list_formal_apply_rollback_refs() -> FormalApplyRollbackRefListResponse:
    try:
        return controlled_formal_apply_executor_service.list_rollback_refs()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/write-audits", response_model=ControlledApplyWriteAuditListResponse)
def list_formal_apply_write_audits() -> ControlledApplyWriteAuditListResponse:
    try:
        return controlled_formal_apply_executor_service.list_write_audits()
    except StorageError as exc:
        _raise_http(exc)
