from fastapi import APIRouter, HTTPException

from ..models.formal_apply_dry_run import (
    FormalApplyDiffSummaryListResponse,
    FormalApplyDryRunPlanRequest,
    FormalApplyDryRunResult,
    FormalApplyDryRunStatusResponse,
    FormalApplyImpactPreviewListResponse,
    FormalApplyPlan,
    FormalApplyPlanItemListResponse,
    FormalApplyPlanListResponse,
    FormalApplySafetyCheckListResponse,
)
from ..services.formal_apply_dry_run_service import FormalApplyDryRunService
from ..storage.json_store import StorageError


router = APIRouter()
formal_apply_dry_run_service = FormalApplyDryRunService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=FormalApplyDryRunStatusResponse)
def get_formal_apply_dry_run_status() -> FormalApplyDryRunStatusResponse:
    try:
        return formal_apply_dry_run_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.post("/plans", response_model=FormalApplyDryRunResult)
def create_formal_apply_dry_run_plan(request: FormalApplyDryRunPlanRequest) -> FormalApplyDryRunResult:
    try:
        return formal_apply_dry_run_service.create_plan(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/plans", response_model=FormalApplyPlanListResponse)
def list_formal_apply_dry_run_plans() -> FormalApplyPlanListResponse:
    try:
        return formal_apply_dry_run_service.list_plans()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/plans/{plan_id}", response_model=FormalApplyPlan)
def get_formal_apply_dry_run_plan(plan_id: str) -> FormalApplyPlan:
    try:
        return formal_apply_dry_run_service.get_plan(plan_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/plans/{plan_id}/items", response_model=FormalApplyPlanItemListResponse)
def list_formal_apply_dry_run_plan_items(plan_id: str) -> FormalApplyPlanItemListResponse:
    try:
        return formal_apply_dry_run_service.list_plan_items(plan_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/diff-summaries", response_model=FormalApplyDiffSummaryListResponse)
def list_formal_apply_diff_summaries() -> FormalApplyDiffSummaryListResponse:
    try:
        return formal_apply_dry_run_service.list_diff_summaries()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/impact-previews", response_model=FormalApplyImpactPreviewListResponse)
def list_formal_apply_impact_previews() -> FormalApplyImpactPreviewListResponse:
    try:
        return formal_apply_dry_run_service.list_impact_previews()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/safety-checks", response_model=FormalApplySafetyCheckListResponse)
def list_formal_apply_safety_checks() -> FormalApplySafetyCheckListResponse:
    try:
        return formal_apply_dry_run_service.list_safety_checks()
    except StorageError as exc:
        _raise_http(exc)
