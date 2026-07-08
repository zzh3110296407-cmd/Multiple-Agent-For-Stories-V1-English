from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.background_thinking import (
    BackgroundThinkingTaskCreateRequest,
    BackgroundThinkingTaskExecuteRequest,
    BackgroundThinkingTaskListResponse,
    BackgroundThinkingTaskResponse,
    ThinkingCandidateListResponse,
    ThinkingCandidateResponse,
    ThinkingTaskQueueSummaryResponse,
)
from app.backend.services.background_thinking_service import (
    FAILURE_ERROR_CODES,
    BackgroundThinkingService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
background_thinking_service = BackgroundThinkingService()


def _error_detail(message: str) -> dict[str, str]:
    code, _, detail = message.partition(":")
    return {
        "error_code": code,
        "message": detail.strip() or message,
    }


def _raise_background_thinking_error(exc: StorageError) -> None:
    message = str(exc)
    detail = _error_detail(message)
    code = detail["error_code"]
    status_code = 404 if "NOT_FOUND" in code else 500
    if code.startswith("BACKGROUND_THINKING_") or code.startswith("THINKING_CANDIDATE_"):
        status_code = 400
    if "NOT_FOUND" in code:
        status_code = 404
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _raise_failed_dependency_response(response: BackgroundThinkingTaskResponse) -> None:
    safe_error = response.task.safe_error or {}
    error_code = str(safe_error.get("error_code") or "")
    if response.task.status == "failed" and error_code in FAILURE_ERROR_CODES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": error_code,
                "message": str(safe_error.get("message") or "Background thinking failed."),
                "task_id": response.task.task_id,
                "stage": str(safe_error.get("stage") or ""),
                "retryable": bool(safe_error.get("retryable")),
                "suggested_action": str(safe_error.get("suggested_action") or ""),
            },
        )


@router.post("/tasks", response_model=BackgroundThinkingTaskResponse)
def create_background_thinking_task(
    request: BackgroundThinkingTaskCreateRequest,
) -> BackgroundThinkingTaskResponse:
    try:
        response = background_thinking_service.create_task(request)
        _raise_failed_dependency_response(response)
        return response
    except StorageError as exc:
        _raise_background_thinking_error(exc)


@router.post("/tasks/{task_id}/execute", response_model=BackgroundThinkingTaskResponse)
def execute_background_thinking_task(
    task_id: str,
    request: BackgroundThinkingTaskExecuteRequest | None = None,
) -> BackgroundThinkingTaskResponse:
    try:
        response = background_thinking_service.execute_task(
            task_id,
            execution_strategy=(request.execution_strategy if request else None),
        )
        _raise_failed_dependency_response(response)
        return response
    except StorageError as exc:
        _raise_background_thinking_error(exc)


@router.get("/tasks", response_model=BackgroundThinkingTaskListResponse)
def list_background_thinking_tasks(
    status: Optional[str] = Query(default=None),
    source_scene_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> BackgroundThinkingTaskListResponse:
    try:
        tasks = background_thinking_service.list_tasks(
            status=status,
            source_scene_id=source_scene_id,
            limit=limit,
        )
        return BackgroundThinkingTaskListResponse(tasks=tasks, count=len(tasks))
    except StorageError as exc:
        _raise_background_thinking_error(exc)


@router.get("/candidates", response_model=ThinkingCandidateListResponse)
def list_thinking_candidates(
    status: Optional[str] = Query(default=None),
    source_scene_id: Optional[str] = Query(default=None),
    task_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> ThinkingCandidateListResponse:
    try:
        candidates = background_thinking_service.list_candidates(
            status=status,
            source_scene_id=source_scene_id,
            task_id=task_id,
            limit=limit,
        )
        return ThinkingCandidateListResponse(
            candidates=candidates,
            count=len(candidates),
        )
    except StorageError as exc:
        _raise_background_thinking_error(exc)


@router.get("/queue-summary", response_model=ThinkingTaskQueueSummaryResponse)
def get_background_thinking_queue_summary(
    source_scene_id: Optional[str] = Query(default=None),
) -> ThinkingTaskQueueSummaryResponse:
    try:
        return background_thinking_service.queue_summary(source_scene_id=source_scene_id)
    except StorageError as exc:
        _raise_background_thinking_error(exc)


@router.get("/candidates/{candidate_id}", response_model=ThinkingCandidateResponse)
def get_thinking_candidate(candidate_id: str) -> ThinkingCandidateResponse:
    try:
        return ThinkingCandidateResponse(
            candidate=background_thinking_service.get_candidate(candidate_id)
        )
    except StorageError as exc:
        _raise_background_thinking_error(exc)


@router.get("/tasks/{task_id}", response_model=BackgroundThinkingTaskResponse)
def get_background_thinking_task(task_id: str) -> BackgroundThinkingTaskResponse:
    try:
        return BackgroundThinkingTaskResponse(
            task=background_thinking_service.get_task(task_id)
        )
    except StorageError as exc:
        _raise_background_thinking_error(exc)
