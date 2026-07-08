from fastapi import APIRouter, HTTPException, Query

from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.models.abcd_story_information import (
    ABCDStoryInformationIntegrationReport,
    ABCDStoryInformationMergePreviewRequest,
    ABCDStoryInformationMergePreviewResponse,
    ABCDStoryInformationPackageBuildRequest,
    ABCDStoryInformationPackageBuildResponse,
    ABCDStoryInformationPackageReadResponse,
    WriterABCDContextView,
)
from app.backend.services.abcd_story_information_service import (
    ABCDStoryInformationService,
)
from app.backend.services.active_project_boundary_service import (
    ActiveProjectStoryDataBlocked,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
abcd_story_information_service = ABCDStoryInformationService()


def active_abcd_story_information_service() -> ABCDStoryInformationService:
    return scoped_story_service(
        abcd_story_information_service,
        ABCDStoryInformationService,
    )


@router.post("/packages", response_model=ABCDStoryInformationPackageBuildResponse)
def build_abcd_story_information_package(
    request: ABCDStoryInformationPackageBuildRequest,
) -> ABCDStoryInformationPackageBuildResponse:
    try:
        return active_abcd_story_information_service().build_package(
            request.tiered_character_intent_package_id,
            force_refresh=request.force_refresh,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_story_information_error(exc) from exc


@router.get("/packages/current", response_model=ABCDStoryInformationPackageReadResponse)
def get_current_abcd_story_information_package(
    chapter_id: str = Query(...),
    scene_index: int = Query(..., ge=1),
) -> ABCDStoryInformationPackageReadResponse:
    try:
        return active_abcd_story_information_service().get_current_package(
            chapter_id=chapter_id,
            scene_index=scene_index,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_story_information_error(exc) from exc


@router.get("/packages/{package_id}", response_model=ABCDStoryInformationPackageReadResponse)
def get_abcd_story_information_package(
    package_id: str,
) -> ABCDStoryInformationPackageReadResponse:
    try:
        return active_abcd_story_information_service().get_package(package_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_story_information_error(exc) from exc


@router.get("/packages/{package_id}/writer-view", response_model=WriterABCDContextView)
def get_abcd_story_information_writer_view(package_id: str) -> WriterABCDContextView:
    try:
        return active_abcd_story_information_service().get_writer_view(package_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_story_information_error(exc) from exc


@router.get(
    "/packages/{package_id}/integration-report",
    response_model=ABCDStoryInformationIntegrationReport,
)
def get_abcd_story_information_integration_report(
    package_id: str,
) -> ABCDStoryInformationIntegrationReport:
    try:
        return active_abcd_story_information_service().get_integration_report(package_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_story_information_error(exc) from exc


@router.post(
    "/packages/{package_id}/merge-preview",
    response_model=ABCDStoryInformationMergePreviewResponse,
)
def merge_abcd_story_information_preview(
    package_id: str,
    request: ABCDStoryInformationMergePreviewRequest,
) -> ABCDStoryInformationMergePreviewResponse:
    try:
        return active_abcd_story_information_service().merge_preview(
            package_id,
            base_scene_information=request.base_scene_information,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _abcd_story_information_error(exc) from exc


def _abcd_story_information_error(exc: Exception) -> HTTPException:
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
        if code.startswith("ABCD_STORY_INFORMATION_")
        else "ABCD_STORY_INFORMATION_INTERNAL_ERROR"
    )
    status_code = 500
    if "NOT_FOUND" in error_code:
        status_code = 404
    elif "REQUIRED" in error_code or "INVALID" in error_code or "BLOCKED" in error_code:
        status_code = 400
    if status_code == 500:
        message = "ABCD story information operation failed."
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": message,
        },
    )
