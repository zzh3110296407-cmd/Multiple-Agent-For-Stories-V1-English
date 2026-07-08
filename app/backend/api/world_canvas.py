from fastapi import APIRouter, HTTPException

from app.backend.models.world_canvas import (
    WorldCanvasConfirmRequest,
    WorldCanvasGenerateRequest,
    WorldCanvasReviseRequest,
    WorldCanvasWorkflowResponse,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelJsonParseError,
)
from app.backend.services.world_canvas_service import WorldCanvasService
from app.backend.storage.json_store import StorageError

router = APIRouter()
world_canvas_service = WorldCanvasService()


def world_canvas_error_response(exc: Exception) -> HTTPException:
    error_code = getattr(exc, "error_code", "")
    if error_code:
        return HTTPException(
            status_code=400,
            detail={
                "error_code": error_code,
                "message": str(exc),
            },
        )
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    if isinstance(exc, ModelConfigurationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ModelJsonParseError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, ModelCallError):
        return HTTPException(status_code=502, detail=str(exc))
    message = str(exc)
    if "does not exist" in message:
        return HTTPException(status_code=404, detail=message)
    if (
        "must not be empty" in message
        or "Cannot confirm" in message
        or "schema validation" in message
    ):
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_world_canvas_service() -> WorldCanvasService:
    return scoped_story_service(world_canvas_service, WorldCanvasService)


@router.get("/current", response_model=WorldCanvasWorkflowResponse)
def get_current_world_canvas() -> WorldCanvasWorkflowResponse:
    try:
        return active_world_canvas_service().get_current_canvas()
    except (
        ActiveProjectStoryDataBlocked,
        StorageError,
        ModelConfigurationError,
        ModelJsonParseError,
        ModelCallError,
    ) as exc:
        raise world_canvas_error_response(exc) from exc


@router.post("/generate", response_model=WorldCanvasWorkflowResponse)
def generate_world_canvas(
    request: WorldCanvasGenerateRequest,
) -> WorldCanvasWorkflowResponse:
    try:
        return active_world_canvas_service().generate_from_idea(request.story_idea)
    except (
        ActiveProjectStoryDataBlocked,
        StorageError,
        ModelConfigurationError,
        ModelJsonParseError,
        ModelCallError,
    ) as exc:
        raise world_canvas_error_response(exc) from exc


@router.post("/revise", response_model=WorldCanvasWorkflowResponse)
def revise_world_canvas(
    request: WorldCanvasReviseRequest,
) -> WorldCanvasWorkflowResponse:
    try:
        return active_world_canvas_service().revise_canvas(request.revision_prompt)
    except (
        ActiveProjectStoryDataBlocked,
        StorageError,
        ModelConfigurationError,
        ModelJsonParseError,
        ModelCallError,
    ) as exc:
        raise world_canvas_error_response(exc) from exc


@router.post("/confirm", response_model=WorldCanvasWorkflowResponse)
def confirm_world_canvas(
    request: WorldCanvasConfirmRequest,
) -> WorldCanvasWorkflowResponse:
    try:
        return active_world_canvas_service().confirm_canvas(request.user_input)
    except (
        ActiveProjectStoryDataBlocked,
        StorageError,
        ModelConfigurationError,
        ModelJsonParseError,
        ModelCallError,
    ) as exc:
        raise world_canvas_error_response(exc) from exc
