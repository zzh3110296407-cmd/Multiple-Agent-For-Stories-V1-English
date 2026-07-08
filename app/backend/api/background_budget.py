from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from app.backend.models.background_budget import (
    BackgroundBudgetProfileListResponse,
    BackgroundBudgetProfilePatchRequest,
    BackgroundBudgetStatusResponse,
    TaskBudgetEvaluateRequest,
    TaskBudgetEvaluateResponse,
    TaskBudgetUsageListResponse,
    TaskModelPolicyListResponse,
    TaskModelPolicyPatchRequest,
)
from app.backend.services.background_budget_service import BackgroundBudgetService
from app.backend.storage.json_store import StorageError


router = APIRouter()
background_budget_service = BackgroundBudgetService()


def _error_detail(message: str) -> dict[str, str]:
    code, _, detail = message.partition(":")
    return {
        "error_code": code,
        "message": detail.strip() or "Background budget request failed safely.",
    }


def _raise_background_budget_error(exc: Exception) -> None:
    if isinstance(exc, ValidationError):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BACKGROUND_BUDGET_REQUEST_INVALID",
                "message": "Background budget request schema is invalid.",
            },
        ) from exc
    message = str(exc)
    detail = _error_detail(message)
    code = detail["error_code"]
    status_code = 500
    if "NOT_FOUND" in code:
        status_code = 404
    elif (
        code.endswith("_INVALID")
        or "SCHEMA_INVALID" in code
        or "REQUEST_INVALID" in code
        or "PROFILE_INVALID" in code
        or "POLICY_INVALID" in code
    ):
        status_code = 400
    elif "UNSAFE_PAYLOAD_BLOCKED" in code:
        status_code = 409
    if status_code == 500:
        detail = {
            "error_code": "BACKGROUND_BUDGET_INTERNAL_ERROR",
            "message": "Background budget request failed safely.",
        }
    raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/status", response_model=BackgroundBudgetStatusResponse)
def get_background_budget_status() -> BackgroundBudgetStatusResponse:
    try:
        return background_budget_service.get_status()
    except (StorageError, ValidationError) as exc:
        _raise_background_budget_error(exc)


@router.get("/profiles", response_model=BackgroundBudgetProfileListResponse)
def list_background_budget_profiles() -> BackgroundBudgetProfileListResponse:
    try:
        return background_budget_service.profile_response()
    except (StorageError, ValidationError) as exc:
        _raise_background_budget_error(exc)


@router.patch("/profiles/{profile_id}", response_model=BackgroundBudgetProfileListResponse)
def patch_background_budget_profile(
    profile_id: str,
    request: BackgroundBudgetProfilePatchRequest,
) -> BackgroundBudgetProfileListResponse:
    try:
        background_budget_service.patch_profile(profile_id, request)
        return background_budget_service.profile_response()
    except (StorageError, ValidationError) as exc:
        _raise_background_budget_error(exc)


@router.get("/task-policies", response_model=TaskModelPolicyListResponse)
def list_task_model_policies() -> TaskModelPolicyListResponse:
    try:
        return background_budget_service.policy_response()
    except (StorageError, ValidationError) as exc:
        _raise_background_budget_error(exc)


@router.patch("/task-policies/{policy_id}", response_model=TaskModelPolicyListResponse)
def patch_task_model_policy(
    policy_id: str,
    request: TaskModelPolicyPatchRequest,
) -> TaskModelPolicyListResponse:
    try:
        background_budget_service.patch_policy(policy_id, request)
        return background_budget_service.policy_response()
    except (StorageError, ValidationError) as exc:
        _raise_background_budget_error(exc)


@router.get("/usage", response_model=TaskBudgetUsageListResponse)
def list_background_budget_usage(
    limit: int = Query(default=50, ge=1, le=200),
    task_type: Optional[str] = Query(default=None),
    task_id: Optional[str] = Query(default=None),
) -> TaskBudgetUsageListResponse:
    try:
        return background_budget_service.usage_response(
            limit=limit,
            task_type=task_type or "",
            task_id=task_id or "",
        )
    except (StorageError, ValidationError) as exc:
        _raise_background_budget_error(exc)


@router.post("/evaluate-task", response_model=TaskBudgetEvaluateResponse)
def evaluate_background_budget_task(
    request: TaskBudgetEvaluateRequest,
) -> TaskBudgetEvaluateResponse:
    try:
        return background_budget_service.evaluate_task_execution(
            task_type=request.task_type,
            task_id=request.task_id,
            requested_profile_id=request.requested_profile_id,
            requested_execution_strategy=request.requested_execution_strategy,
            snapshot_ids=request.snapshot_ids,
            source_object_type=request.source_object_type,
            source_object_id=request.source_object_id,
        )
    except (StorageError, ValidationError) as exc:
        _raise_background_budget_error(exc)
