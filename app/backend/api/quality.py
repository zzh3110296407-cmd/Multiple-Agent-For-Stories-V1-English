from fastapi import APIRouter, HTTPException

from app.backend.models.quality import QualityCheckResponse
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.model_gateway_service import ModelCallError, ModelJsonParseError
from app.backend.services.quality_check_service import QualityCheckService
from app.backend.storage.json_store import StorageError


router = APIRouter()
quality_check_service = QualityCheckService()


def quality_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    message = str(exc)
    if message.startswith("QUALITY_TARGET_SCENE_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "QUALITY_TARGET_SCENE_MISSING",
                "message": "Scene does not exist.",
            },
        )
    if message.startswith("QUALITY_TARGET_REVISION_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "QUALITY_TARGET_REVISION_MISSING",
                "message": "Scene revision candidate does not exist.",
            },
        )
    if message.startswith("QUALITY_TARGET_INVALID"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "QUALITY_TARGET_INVALID",
                "message": message,
            },
        )
    if isinstance(exc, (ModelCallError, ModelJsonParseError)):
        return HTTPException(
            status_code=502,
            detail={
                "error_code": "QUALITY_MODEL_CHECK_FAILED",
                "message": message,
            },
        )
    return HTTPException(status_code=500, detail=message)


def active_quality_check_service() -> QualityCheckService:
    return scoped_story_service(quality_check_service, QualityCheckService)


@router.get("/quality-reports/current", response_model=QualityCheckResponse)
def get_current_quality_report() -> QualityCheckResponse:
    try:
        return active_quality_check_service().get_current_quality_report()
    except (ActiveProjectStoryDataBlocked, StorageError, ModelCallError, ModelJsonParseError) as exc:
        raise quality_error_response(exc) from exc


@router.post("/quality-check/scene/{scene_id}", response_model=QualityCheckResponse)
def check_scene_quality(scene_id: str) -> QualityCheckResponse:
    try:
        return active_quality_check_service().check_scene_draft(scene_id)
    except (ActiveProjectStoryDataBlocked, StorageError, ModelCallError, ModelJsonParseError) as exc:
        raise quality_error_response(exc) from exc


@router.post(
    "/quality-check/scene/{scene_id}/revision/{revision_id}",
    response_model=QualityCheckResponse,
)
def check_scene_revision_quality(
    scene_id: str,
    revision_id: str,
) -> QualityCheckResponse:
    try:
        return active_quality_check_service().check_scene_revision(scene_id, revision_id)
    except (ActiveProjectStoryDataBlocked, StorageError, ModelCallError, ModelJsonParseError) as exc:
        raise quality_error_response(exc) from exc
