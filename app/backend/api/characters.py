from fastapi import APIRouter, HTTPException

from app.backend.models.character_workflow import (
    CharacterConfirmRequest,
    CharacterGenerateRequest,
    CharacterReviseRequest,
    CharacterWorkflowResponse,
    FinishMainCastRequest,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.character_service import CharacterService
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelJsonParseError,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
character_service = CharacterService()


def character_error_response(exc: Exception) -> HTTPException:
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
    if message.startswith("WORLD_CANVAS_NOT_CONFIRMED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "WORLD_CANVAS_NOT_CONFIRMED",
                "message": "请先确认世界画布，再创建主角。",
            },
        )
    if message.startswith("MAIN_CAST_REQUIRES_CHARACTER"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "MAIN_CAST_REQUIRES_CHARACTER",
                "message": "请至少确认 1 个 A 级角色后再完成主角团初始化。",
            },
        )
    if message.startswith("character_project_story_premise_missing"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "character_project_story_premise_missing",
                "message": message,
            },
        )
    if message.startswith("CHARACTER_DRAFT_ALREADY_CONFIRMED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CHARACTER_DRAFT_ALREADY_CONFIRMED",
                "message": "当前角色草案已经确认，不能重复确认。",
            },
        )
    if "does not exist" in message:
        return HTTPException(status_code=404, detail=message)
    if (
        "must not be empty" in message
        or "Cannot confirm" in message
        or "schema validation" in message
        or "failed schema validation" in message
        or "must be a list" in message
    ):
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_character_service() -> CharacterService:
    return scoped_story_service(character_service, CharacterService)


@router.get("/current", response_model=CharacterWorkflowResponse)
def get_current_characters() -> CharacterWorkflowResponse:
    try:
        return active_character_service().get_current_characters()
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise character_error_response(exc) from exc


@router.get("/draft", response_model=CharacterWorkflowResponse)
def get_current_character_draft() -> CharacterWorkflowResponse:
    try:
        return active_character_service().get_current_draft()
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise character_error_response(exc) from exc


@router.post("/generate", response_model=CharacterWorkflowResponse)
def generate_character(
    request: CharacterGenerateRequest,
) -> CharacterWorkflowResponse:
    try:
        return active_character_service().generate_character(
            user_prompt=request.user_prompt,
            role_hint=request.role_hint,
            story_function_hint=request.story_function_hint,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise character_error_response(exc) from exc


@router.post("/revise", response_model=CharacterWorkflowResponse)
def revise_character(
    request: CharacterReviseRequest,
) -> CharacterWorkflowResponse:
    try:
        return active_character_service().revise_character(request.revision_prompt)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise character_error_response(exc) from exc


@router.post("/confirm", response_model=CharacterWorkflowResponse)
def confirm_character(
    request: CharacterConfirmRequest,
) -> CharacterWorkflowResponse:
    try:
        return active_character_service().confirm_character(request.user_input)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise character_error_response(exc) from exc


@router.post("/finish-main-cast", response_model=CharacterWorkflowResponse)
def finish_main_cast(
    request: FinishMainCastRequest,
) -> CharacterWorkflowResponse:
    try:
        return active_character_service().finish_main_cast(request.user_input)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise character_error_response(exc) from exc
