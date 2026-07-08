from fastapi import APIRouter, HTTPException

from app.backend.models.story_progress import (
    ConfirmNextChapterRequest,
    ConfirmNextChapterResponse,
    ConfirmStoryDraftCompleteRequest,
    ConfirmStoryDraftCompleteResponse,
    NextChapterPreviewResponse,
    PrepareNextChapterRequest,
    PrepareNextChapterResponse,
    StoryProgress,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelJsonParseError,
)
from app.backend.services.story_progress_service import StoryProgressService
from app.backend.storage.json_store import StorageError


router = APIRouter()
story_progress_service = StoryProgressService()


def story_progress_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    if isinstance(exc, ModelConfigurationError):
        return HTTPException(status_code=400, detail="ACTIVE_MODEL_NOT_CONFIGURED")
    if isinstance(exc, ModelJsonParseError):
        return HTTPException(status_code=502, detail="MODEL_JSON_PARSE_FAILED")
    if isinstance(exc, ModelCallError):
        return HTTPException(status_code=502, detail=str(exc))

    message = str(exc)
    if message.startswith("STORY_PROGRESS_CURRENT_ARCHIVE_REQUIRED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("STORY_PROGRESS_NO_NEXT_CHAPTER"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("STORY_PROGRESS_PROVISIONAL_ARCHIVE_ACK_REQUIRED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("STORY_PROGRESS_NEXT_CHAPTER_NOT_ASSIGNED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("STORY_PROGRESS_NEXT_CHAPTER_PREPARATION_REQUIRED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("STORY_PROGRESS_CHAPTER_PLAN_CONFIRMATION_REQUIRED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("STORY_PROGRESS_UNSAFE_PAYLOAD_BLOCKED"):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("STORY_PROGRESS_COMPLETION_ACK_REQUIRED"):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("STORY_PROGRESS_HAS_NEXT_CHAPTER"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("STORY_PROGRESS_GATE_READINESS_BLOCKED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CURRENT_CHAPTER") or message.startswith("M1_FRAMEWORK"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CHAPTER_PLAN") or message.startswith("FOUNDATION"):
        return HTTPException(status_code=409, detail=message)
    if "schema" in message or "INVALID" in message or "must" in message:
        return HTTPException(status_code=400, detail=message)
    if "MISSING" in message or "does not exist" in message:
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_story_progress_service() -> StoryProgressService:
    return scoped_story_service(story_progress_service, StoryProgressService)


@router.get("/current", response_model=StoryProgress)
def get_current_story_progress() -> StoryProgress:
    try:
        return active_story_progress_service().get_current_story_progress()
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise story_progress_error_response(exc) from exc


@router.get("/next-chapter-preview", response_model=NextChapterPreviewResponse)
def preview_next_chapter() -> NextChapterPreviewResponse:
    try:
        return active_story_progress_service().preview_next_chapter()
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise story_progress_error_response(exc) from exc


@router.post("/prepare-next-chapter", response_model=PrepareNextChapterResponse)
def prepare_next_chapter(request: PrepareNextChapterRequest) -> PrepareNextChapterResponse:
    try:
        return active_story_progress_service().prepare_next_chapter(request)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise story_progress_error_response(exc) from exc


@router.post("/confirm-next-chapter", response_model=ConfirmNextChapterResponse)
def confirm_next_chapter(request: ConfirmNextChapterRequest) -> ConfirmNextChapterResponse:
    try:
        return active_story_progress_service().confirm_next_chapter(request)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise story_progress_error_response(exc) from exc


@router.post("/confirm-story-draft-complete", response_model=ConfirmStoryDraftCompleteResponse)
def confirm_story_draft_complete(
    request: ConfirmStoryDraftCompleteRequest,
) -> ConfirmStoryDraftCompleteResponse:
    try:
        return active_story_progress_service().confirm_story_draft_complete(request)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise story_progress_error_response(exc) from exc
