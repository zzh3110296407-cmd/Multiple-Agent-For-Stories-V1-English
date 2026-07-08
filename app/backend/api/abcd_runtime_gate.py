from fastapi import APIRouter, HTTPException

from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.models.abcd_runtime_gate import (
    ABCDGateReviewRequest,
    ABCDGateReviewResult,
    ABCDObjectiveFactBoundaryReport,
    ABCDQualityGateRuntimeReport,
    ABCDRuntimeGateIntegrationAudit,
)
from app.backend.services.abcd_runtime_gate_integration_service import (
    ABCDRuntimeGateIntegrationService,
)
from app.backend.services.active_project_boundary_service import (
    ActiveProjectStoryDataBlocked,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
abcd_runtime_gate_service = ABCDRuntimeGateIntegrationService()


def active_abcd_runtime_gate_service() -> ABCDRuntimeGateIntegrationService:
    return scoped_story_service(
        abcd_runtime_gate_service,
        ABCDRuntimeGateIntegrationService,
    )


@router.post("/scenes/{scene_id}/review", response_model=ABCDGateReviewResult)
def review_abcd_runtime_gate(
    scene_id: str,
    request: ABCDGateReviewRequest | None = None,
) -> ABCDGateReviewResult:
    try:
        request = request or ABCDGateReviewRequest()
        return active_abcd_runtime_gate_service().review_scene(
            scene_id,
            mode=request.mode,
            force_refresh=request.force_refresh,
            accepted_issue_ids=request.accepted_issue_ids,
            user_confirmation_text=(
                request.user_confirmation_text
                if request.accept_requires_user_confirmation
                else ""
            ),
            acceptance_source="review_request",
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_runtime_gate_error(exc) from exc


@router.get("/scenes/{scene_id}/latest", response_model=ABCDGateReviewResult)
def latest_abcd_runtime_gate(scene_id: str) -> ABCDGateReviewResult:
    try:
        return active_abcd_runtime_gate_service().latest_for_scene(scene_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_runtime_gate_error(exc) from exc


@router.get("/audits/{audit_id}", response_model=ABCDRuntimeGateIntegrationAudit)
def get_abcd_runtime_gate_audit(audit_id: str) -> ABCDRuntimeGateIntegrationAudit:
    try:
        return active_abcd_runtime_gate_service().get_audit(audit_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_runtime_gate_error(exc) from exc


@router.get(
    "/reports/objective-fact/{report_id}",
    response_model=ABCDObjectiveFactBoundaryReport,
)
def get_abcd_objective_fact_report(report_id: str) -> ABCDObjectiveFactBoundaryReport:
    try:
        return active_abcd_runtime_gate_service().get_objective_report(report_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_runtime_gate_error(exc) from exc


@router.get(
    "/reports/quality/{report_id}",
    response_model=ABCDQualityGateRuntimeReport,
)
def get_abcd_quality_runtime_report(report_id: str) -> ABCDQualityGateRuntimeReport:
    try:
        return active_abcd_runtime_gate_service().get_quality_report(report_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_runtime_gate_error(exc) from exc


def _abcd_runtime_gate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    message = str(exc)
    code = message.split(":", 1)[0]
    error_code = (
        code
        if code.startswith("ABCD_RUNTIME_GATE_")
        else "ABCD_RUNTIME_GATE_INTERNAL_ERROR"
    )
    status_code = 500
    if "NOT_FOUND" in error_code:
        status_code = 404
    elif (
        "INVALID" in error_code
        or "BLOCKING" in error_code
        or "REQUIRED" in error_code
    ):
        status_code = 409 if "BLOCKING" in error_code else 400
    if status_code == 500:
        message = "ABCD runtime gate operation failed."
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": message,
        },
    )
