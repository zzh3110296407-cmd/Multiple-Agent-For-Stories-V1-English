from fastapi import APIRouter, HTTPException

from app.backend.models.chapter_archive import (
    ChapterArchivePreview,
    ChapterArchiveRequest,
    ChapterArchiveResponse,
    ChapterArchiveRecord,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.chapter_archive_service import ChapterArchiveService
from app.backend.storage.json_store import StorageError


router = APIRouter()
chapter_archive_service = ChapterArchiveService()


def chapter_archive_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    message = str(exc)
    if message.startswith("CHAPTER_ARCHIVE_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("CHAPTER_ARCHIVE_ALREADY_EXISTS"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CHAPTER_ARCHIVE_STABLE_REQUIRES_FINAL_COMPLETE"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CHAPTER_ARCHIVE_PROVISIONAL_ACCEPTANCE_REQUIRED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CHAPTER_ARCHIVE_FRAMEWORK_AUDIT_MISSING"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CHAPTER_ARCHIVE_ID_INDEX_MISMATCH"):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("CHAPTER_ARCHIVE_UNSAFE_PAYLOAD_BLOCKED"):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("CHAPTER_ARCHIVE_NOT_READY"):
        return HTTPException(status_code=400, detail=message)
    if "schema" in message:
        return HTTPException(status_code=400, detail=message)
    if "does not exist" in message:
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_chapter_archive_service() -> ChapterArchiveService:
    return scoped_story_service(chapter_archive_service, ChapterArchiveService)


@router.get("/preview", response_model=ChapterArchivePreview)
def preview_chapter_archive(
    chapter_id: str | None = None,
    chapter_index: int | None = None,
) -> ChapterArchivePreview:
    try:
        return active_chapter_archive_service().preview_archive(
            chapter_id=chapter_id,
            chapter_index=chapter_index,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise chapter_archive_error_response(exc) from exc


@router.post("/archive", response_model=ChapterArchiveResponse)
def archive_chapter(request: ChapterArchiveRequest) -> ChapterArchiveResponse:
    try:
        return active_chapter_archive_service().archive_chapter(request)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise chapter_archive_error_response(exc) from exc


@router.get("/by-chapter/{chapter_id}", response_model=ChapterArchiveResponse)
def get_chapter_archive_by_chapter(chapter_id: str) -> ChapterArchiveResponse:
    try:
        return active_chapter_archive_service().get_archive_by_chapter(chapter_id)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise chapter_archive_error_response(exc) from exc


@router.get("/list", response_model=list[ChapterArchiveRecord])
def list_chapter_archives() -> list[ChapterArchiveRecord]:
    try:
        return active_chapter_archive_service().list_archives()
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise chapter_archive_error_response(exc) from exc
