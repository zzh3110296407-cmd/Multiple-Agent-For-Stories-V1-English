from fastapi import APIRouter, HTTPException

from app.backend.models.chapter import Chapter
from app.backend.models.character import Character
from app.backend.models.decision import Decision
from app.backend.models.event import Event
from app.backend.models.framework import Framework
from app.backend.models.issue import Issue
from app.backend.models.memory_record import MemoryRecord
from app.backend.models.quality import QualityReport
from app.backend.models.relationship import Relationship
from app.backend.models.scene import Scene
from app.backend.models.state_change import StateChange
from app.backend.models.story_bible import StoryBible
from app.backend.models.world_canvas import WorldCanvas
from app.backend.services.project_data_service import ProjectDataService
from app.backend.storage.json_store import StorageError

router = APIRouter()
project_data_service = ProjectDataService(respect_active_project_selection=True)


def storage_error_response(exc: StorageError) -> HTTPException:
    status_code = 404 if "does not exist" in str(exc) else 500
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/story-bible", response_model=StoryBible)
def get_story_bible() -> StoryBible:
    try:
        return project_data_service.read_story_bible()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/world-canvas", response_model=WorldCanvas)
def get_world_canvas() -> WorldCanvas:
    try:
        return project_data_service.read_world_canvas()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/characters", response_model=list[Character])
def get_characters() -> list[Character]:
    try:
        return project_data_service.read_characters()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/relationships", response_model=list[Relationship])
def get_relationships() -> list[Relationship]:
    try:
        return project_data_service.read_relationships()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/framework", response_model=Framework)
def get_framework() -> Framework:
    try:
        return project_data_service.read_framework()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/chapters", response_model=list[Chapter])
def get_chapters() -> list[Chapter]:
    try:
        return project_data_service.read_chapters()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/scenes", response_model=list[Scene])
def get_scenes() -> list[Scene]:
    try:
        return project_data_service.read_scenes()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/events", response_model=list[Event])
def get_events() -> list[Event]:
    try:
        return project_data_service.read_events()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/state-changes", response_model=list[StateChange])
def get_state_changes() -> list[StateChange]:
    try:
        return project_data_service.read_state_changes()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/memory-records", response_model=list[MemoryRecord])
def get_memory_records() -> list[MemoryRecord]:
    try:
        return project_data_service.read_memory_records()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/decisions", response_model=list[Decision])
def get_decisions() -> list[Decision]:
    try:
        return project_data_service.read_decisions()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/issues", response_model=list[Issue])
def get_issues() -> list[Issue]:
    try:
        return project_data_service.read_issues()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/quality-reports", response_model=list[QualityReport])
def get_quality_reports() -> list[QualityReport]:
    try:
        return project_data_service.read_quality_reports()
    except StorageError as exc:
        raise storage_error_response(exc) from exc
