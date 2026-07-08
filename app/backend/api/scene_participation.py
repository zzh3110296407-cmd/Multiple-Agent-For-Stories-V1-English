from fastapi import APIRouter, HTTPException, Query

from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.models.scene_participation import (
    SceneParticipationPrepareRequest,
    SceneParticipationPrepareResponse,
    SceneParticipationReadinessReport,
)
from app.backend.services.active_project_boundary_service import (
    ActiveProjectStoryDataBlocked,
)
from app.backend.services.scene_participation_package_service import (
    SceneParticipationPackageService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
scene_participation_service = SceneParticipationPackageService()


def active_scene_participation_service() -> SceneParticipationPackageService:
    return scoped_story_service(
        scene_participation_service,
        SceneParticipationPackageService,
    )


def _raise_scene_participation_error(exc: Exception) -> None:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        ) from exc
    message = str(exc)
    code, _, detail = message.partition(":")
    error_code = (
        code
        if code.startswith("SCENE_PARTICIPATION_")
        else "SCENE_PARTICIPATION_INTERNAL_ERROR"
    )
    status_code = 500
    if "NOT_FOUND" in error_code:
        status_code = 404
    elif "REQUIRED" in error_code or "INVALID" in error_code:
        status_code = 400
    if status_code == 500:
        error_code = "SCENE_PARTICIPATION_INTERNAL_ERROR"
        detail = "Scene participation package operation failed."
    raise HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": detail.strip() or "Scene participation package operation failed.",
        },
    ) from exc


@router.post("/prepare", response_model=SceneParticipationPrepareResponse)
def prepare_scene_participation_package(
    request: SceneParticipationPrepareRequest,
) -> SceneParticipationPrepareResponse:
    try:
        return active_scene_participation_service().prepare_package(request)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participation_error(exc)


@router.get("/packages/current", response_model=SceneParticipationPrepareResponse)
def get_current_scene_participation_package(
    chapter_id: str = Query(...),
    scene_index: int = Query(..., ge=1),
) -> SceneParticipationPrepareResponse:
    try:
        return active_scene_participation_service().get_current_package(
            chapter_id=chapter_id,
            scene_index=scene_index,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participation_error(exc)


@router.get("/packages/{package_id}", response_model=SceneParticipationPrepareResponse)
def get_scene_participation_package(
    package_id: str,
) -> SceneParticipationPrepareResponse:
    try:
        return active_scene_participation_service().get_package(package_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participation_error(exc)


@router.get(
    "/packages/{package_id}/readiness",
    response_model=SceneParticipationReadinessReport,
)
def get_scene_participation_readiness(
    package_id: str,
) -> SceneParticipationReadinessReport:
    try:
        return active_scene_participation_service().get_readiness(package_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participation_error(exc)
