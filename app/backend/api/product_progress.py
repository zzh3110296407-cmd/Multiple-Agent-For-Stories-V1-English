from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.product_progress import (
    BlockingIssueSurface,
    ExpertEvidenceLink,
    NextRecommendedAction,
    ProductProgressAggregateResponse,
    ProductProgressSafetyReport,
    ProductProgressSummary,
    UserDecisionSurface,
)
from app.backend.services.product_progress_service import (
    ProductProgressError,
    ProductProgressSafetyError,
    ProductProgressService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
product_progress_service = ProductProgressService()


def _raise_product_progress_error(exc: Exception) -> None:
    if isinstance(exc, ProductProgressSafetyError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ProductProgressError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, StorageError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


@router.get("/state", response_model=ProductProgressAggregateResponse)
def get_product_progress_state(
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductProgressAggregateResponse:
    try:
        return product_progress_service.state(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductProgressError, StorageError) as exc:
        _raise_product_progress_error(exc)
        raise AssertionError("unreachable")


@router.get("/summary", response_model=ProductProgressSummary)
def get_product_progress_summary(
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductProgressSummary:
    try:
        return product_progress_service.summary(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductProgressError, StorageError) as exc:
        _raise_product_progress_error(exc)
        raise AssertionError("unreachable")


@router.get("/next-actions", response_model=list[NextRecommendedAction])
def get_product_progress_next_actions(
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> list[NextRecommendedAction]:
    try:
        return product_progress_service.next_actions(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductProgressError, StorageError) as exc:
        _raise_product_progress_error(exc)
        raise AssertionError("unreachable")


@router.get("/decision-surfaces", response_model=list[UserDecisionSurface])
def get_product_progress_decision_surfaces(
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> list[UserDecisionSurface]:
    try:
        return product_progress_service.decision_surfaces(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductProgressError, StorageError) as exc:
        _raise_product_progress_error(exc)
        raise AssertionError("unreachable")


@router.get("/blocking-issues", response_model=list[BlockingIssueSurface])
def get_product_progress_blocking_issues(
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> list[BlockingIssueSurface]:
    try:
        return product_progress_service.blocking_issues(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductProgressError, StorageError) as exc:
        _raise_product_progress_error(exc)
        raise AssertionError("unreachable")


@router.get("/expert-evidence", response_model=list[ExpertEvidenceLink])
def get_product_progress_expert_evidence(
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default="expert"),
) -> list[ExpertEvidenceLink]:
    try:
        return product_progress_service.expert_evidence(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductProgressError, StorageError) as exc:
        _raise_product_progress_error(exc)
        raise AssertionError("unreachable")


@router.get("/safety-report", response_model=ProductProgressSafetyReport)
def get_product_progress_safety_report(
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductProgressSafetyReport:
    try:
        return product_progress_service.safety_report(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductProgressError, StorageError) as exc:
        _raise_product_progress_error(exc)
        raise AssertionError("unreachable")


@router.get("/projects/{project_id}/state", response_model=ProductProgressAggregateResponse)
def get_project_product_progress_state(
    project_id: str,
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductProgressAggregateResponse:
    return get_product_progress_state(project_id=project_id, mode_profile_id=mode_profile_id)


@router.get("/projects/{project_id}/summary", response_model=ProductProgressSummary)
def get_project_product_progress_summary(
    project_id: str,
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductProgressSummary:
    return get_product_progress_summary(project_id=project_id, mode_profile_id=mode_profile_id)


@router.get("/projects/{project_id}/next-actions", response_model=list[NextRecommendedAction])
def get_project_product_progress_next_actions(
    project_id: str,
    mode_profile_id: Optional[str] = Query(default=None),
) -> list[NextRecommendedAction]:
    return get_product_progress_next_actions(project_id=project_id, mode_profile_id=mode_profile_id)


@router.get("/projects/{project_id}/decision-surfaces", response_model=list[UserDecisionSurface])
def get_project_product_progress_decision_surfaces(
    project_id: str,
    mode_profile_id: Optional[str] = Query(default=None),
) -> list[UserDecisionSurface]:
    return get_product_progress_decision_surfaces(project_id=project_id, mode_profile_id=mode_profile_id)


@router.get("/projects/{project_id}/blocking-issues", response_model=list[BlockingIssueSurface])
def get_project_product_progress_blocking_issues(
    project_id: str,
    mode_profile_id: Optional[str] = Query(default=None),
) -> list[BlockingIssueSurface]:
    return get_product_progress_blocking_issues(project_id=project_id, mode_profile_id=mode_profile_id)


@router.get("/projects/{project_id}/expert-evidence", response_model=list[ExpertEvidenceLink])
def get_project_product_progress_expert_evidence(
    project_id: str,
    mode_profile_id: Optional[str] = Query(default="expert"),
) -> list[ExpertEvidenceLink]:
    return get_product_progress_expert_evidence(project_id=project_id, mode_profile_id=mode_profile_id)


@router.get("/projects/{project_id}/safety-report", response_model=ProductProgressSafetyReport)
def get_project_product_progress_safety_report(
    project_id: str,
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductProgressSafetyReport:
    return get_product_progress_safety_report(project_id=project_id, mode_profile_id=mode_profile_id)
