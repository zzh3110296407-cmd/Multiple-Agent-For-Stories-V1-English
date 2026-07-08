from fastapi import APIRouter, HTTPException

from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.models.abcd_runtime_overview import ABCDRuntimeOverviewResponse
from app.backend.services.abcd_runtime_overview_service import (
    ABCDRuntimeOverviewService,
)
from app.backend.services.active_project_boundary_service import (
    ActiveProjectStoryDataBlocked,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
abcd_runtime_overview_service = ABCDRuntimeOverviewService()


def active_abcd_runtime_overview_service() -> ABCDRuntimeOverviewService:
    return scoped_story_service(
        abcd_runtime_overview_service,
        ABCDRuntimeOverviewService,
    )


@router.get("/scenes/{scene_id}/overview", response_model=ABCDRuntimeOverviewResponse)
def get_abcd_runtime_scene_overview(scene_id: str) -> ABCDRuntimeOverviewResponse:
    try:
        return active_abcd_runtime_overview_service().get_scene_overview(scene_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _overview_error(exc) from exc


def _overview_error(exc: Exception) -> HTTPException:
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
    status_code = 404 if "NOT_FOUND" in code or "MISSING" in code else 400
    if not code.startswith("ABCD_RUNTIME_OVERVIEW") and not code.startswith("ABCD_RUNTIME_GATE"):
        code = "ABCD_RUNTIME_OVERVIEW_INTERNAL_ERROR"
        message = "ABCD runtime overview operation failed."
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": code,
            "message": message,
        },
    )
