from fastapi import APIRouter, HTTPException, Query

from ..models.propagation_governance import (
    AffectedObjectReviewTask,
    AffectedObjectReviewTaskListResponse,
    CrossChapterRecheckPlanListResponse,
    FrameworkChangePropagationReportListResponse,
    PropagationGovernanceStatusResponse,
    PropagationImpactRecord,
    PropagationImpactRecordListResponse,
    PropagationReadinessResult,
    PropagationReviewRequest,
    PropagationReviewResult,
    PropagationTaskStatusRequest,
)
from ..services.propagation_governance_service import PropagationGovernanceService
from ..storage.json_store import StorageError


router = APIRouter()
propagation_governance_service = PropagationGovernanceService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if "DUPLICATE" in message or "NOT_READY" in message or "FORBIDDEN_STORAGE_MUTATION" in message:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=PropagationGovernanceStatusResponse)
def get_propagation_governance_status() -> PropagationGovernanceStatusResponse:
    try:
        return propagation_governance_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/executions/{execution_result_id}/readiness", response_model=PropagationReadinessResult)
def get_propagation_execution_readiness(execution_result_id: str) -> PropagationReadinessResult:
    try:
        return propagation_governance_service.get_execution_readiness(execution_result_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/executions/{execution_result_id}/review", response_model=PropagationReviewResult)
def review_propagation_execution(
    execution_result_id: str,
    request: PropagationReviewRequest,
) -> PropagationReviewResult:
    try:
        return propagation_governance_service.review_execution(execution_result_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/impact-records", response_model=PropagationImpactRecordListResponse)
def list_propagation_impact_records() -> PropagationImpactRecordListResponse:
    try:
        return propagation_governance_service.list_impact_records()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/impact-records/{impact_record_id}", response_model=PropagationImpactRecord)
def get_propagation_impact_record(impact_record_id: str) -> PropagationImpactRecord:
    try:
        return propagation_governance_service.get_impact_record(impact_record_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/review-tasks", response_model=AffectedObjectReviewTaskListResponse)
def list_propagation_review_tasks(
    status: str | None = Query(default=None),
) -> AffectedObjectReviewTaskListResponse:
    try:
        return propagation_governance_service.list_review_tasks(status)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/review-tasks/{task_id}/mark-reviewed", response_model=AffectedObjectReviewTask)
def mark_propagation_task_reviewed(
    task_id: str,
    request: PropagationTaskStatusRequest,
) -> AffectedObjectReviewTask:
    try:
        return propagation_governance_service.mark_task_reviewed(task_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/review-tasks/{task_id}/defer", response_model=AffectedObjectReviewTask)
def defer_propagation_task(
    task_id: str,
    request: PropagationTaskStatusRequest,
) -> AffectedObjectReviewTask:
    try:
        return propagation_governance_service.defer_task(task_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/review-tasks/{task_id}/dismiss", response_model=AffectedObjectReviewTask)
def dismiss_propagation_task(
    task_id: str,
    request: PropagationTaskStatusRequest,
) -> AffectedObjectReviewTask:
    try:
        return propagation_governance_service.dismiss_task(task_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/recheck-plans", response_model=CrossChapterRecheckPlanListResponse)
def list_propagation_recheck_plans() -> CrossChapterRecheckPlanListResponse:
    try:
        return propagation_governance_service.list_recheck_plans()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/framework-reports", response_model=FrameworkChangePropagationReportListResponse)
def list_framework_change_propagation_reports() -> FrameworkChangePropagationReportListResponse:
    try:
        return propagation_governance_service.list_framework_reports()
    except StorageError as exc:
        _raise_http(exc)
