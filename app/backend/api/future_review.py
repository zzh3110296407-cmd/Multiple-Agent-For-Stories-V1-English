from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.future_review import (
    DelayedQuestionAnswerRequest,
    DelayedQuestionCreateRequest,
    DelayedQuestionReadyQueryResponse,
    DelayedQuestionResponse,
    FutureIssueCreateRequest,
    FutureIssueFromCachedCandidateRequest,
    FutureIssueFromInvalidationRequest,
    FutureIssueResponse,
    FutureIssuesBackfillRequest,
    FutureReviewSummaryResponse,
    FutureTodoResponse,
)
from app.backend.services.future_review_service import FutureReviewService
from app.backend.storage.json_store import StorageError


router = APIRouter()
future_review_service = FutureReviewService()


def _error_detail(message: str) -> dict[str, str]:
    code, _, detail = message.partition(":")
    return {
        "error_code": code,
        "message": detail.strip() or "Future review operation failed.",
    }


def _raise_future_review_error(exc: StorageError) -> None:
    detail = _error_detail(str(exc))
    code = detail["error_code"]
    status_code = 500
    if "NOT_FOUND" in code or code.endswith("_MISSING"):
        status_code = 404
    if (
        code.endswith("_REQUIRED")
        or code.endswith("_INVALID")
        or "SCHEMA_INVALID" in code
        or "OPTION_NOT_FOUND" in code
    ):
        status_code = 400
    if "UNSAFE_PAYLOAD_BLOCKED" in code:
        status_code = 409
    if status_code == 500:
        detail = {
            "error_code": "FUTURE_REVIEW_INTERNAL_ERROR",
            "message": "Future review operation failed.",
        }
    raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/future-issues", response_model=FutureIssueResponse)
def create_future_issue(request: FutureIssueCreateRequest) -> FutureIssueResponse:
    try:
        issue = future_review_service.create_future_issue(request)
        return FutureIssueResponse(
            future_issue=issue,
            safety=future_review_service._safety({"future_issue": issue}),
        )
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.post("/future-issues/from-cached-candidate/{cached_candidate_id}", response_model=FutureIssueResponse)
def create_future_issue_from_cached_candidate(
    cached_candidate_id: str,
    request: FutureIssueFromCachedCandidateRequest | None = None,
) -> FutureIssueResponse:
    try:
        issue = future_review_service.create_issue_from_cached_candidate(
            cached_candidate_id,
            reveal_condition=(request.reveal_condition if request else "when_user_opens_scene"),
        )
        return FutureIssueResponse(
            future_issue=issue,
            safety=future_review_service._safety({"future_issue": issue}),
        )
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.post("/future-issues/from-invalidation/{invalidation_record_id}", response_model=FutureIssueResponse)
def create_future_issue_from_invalidation(
    invalidation_record_id: str,
    request: FutureIssueFromInvalidationRequest | None = None,
) -> FutureIssueResponse:
    try:
        issue = future_review_service.create_issue_from_invalidation(
            invalidation_record_id,
            reveal_condition=(request.reveal_condition if request else "when_user_opens_scene"),
        )
        return FutureIssueResponse(
            future_issue=issue,
            safety=future_review_service._safety({"future_issue": issue}),
        )
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.post("/future-issues/backfill-from-cache", response_model=FutureReviewSummaryResponse)
def backfill_future_issues_from_cache(
    request: FutureIssuesBackfillRequest,
) -> FutureReviewSummaryResponse:
    try:
        return future_review_service.backfill_issues_from_cache(
            scene_id=request.scene_id,
            chapter_id=request.chapter_id,
            include_stale=request.include_stale,
            limit=request.limit,
        )
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.get("/future-issues", response_model=FutureReviewSummaryResponse)
def get_future_issues(
    scene_id: Optional[str] = Query(default=None),
    chapter_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> FutureReviewSummaryResponse:
    try:
        issues = future_review_service.list_future_issues(
            scene_id=scene_id or "",
            chapter_id=chapter_id or "",
            status=status or "",
            limit=limit,
        )
        response = future_review_service.summary(
            scene_id=scene_id or "",
            chapter_id=chapter_id or "",
            limit=limit,
        )
        response.future_issues = issues
        response.future_issue_count = len(issues)
        response.issue_counts_by_status = future_review_service._counts(issues, "status")
        response.safety = future_review_service._safety(response)
        future_review_service._guard_safe_payload(response)
        return response
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.post("/future-issues/{future_issue_id}/delayed-question", response_model=DelayedQuestionResponse)
def create_delayed_question_from_future_issue(
    future_issue_id: str,
    request: DelayedQuestionCreateRequest | None = None,
) -> DelayedQuestionResponse:
    try:
        question = future_review_service.create_delayed_question(future_issue_id, request)
        return DelayedQuestionResponse(
            delayed_question=question,
            safety=future_review_service._safety({"delayed_question": question}),
        )
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.get("/delayed-questions/ready", response_model=DelayedQuestionReadyQueryResponse)
def get_ready_delayed_questions(
    scene_id: Optional[str] = Query(default=None),
    chapter_id: Optional[str] = Query(default=None),
    reveal_condition: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> DelayedQuestionReadyQueryResponse:
    try:
        return future_review_service.ready_questions(
            scene_id=scene_id or "",
            chapter_id=chapter_id or "",
            reveal_condition=reveal_condition or "",
            limit=limit,
        )
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.post("/delayed-questions/{delayed_question_id}/answer", response_model=DelayedQuestionResponse)
def answer_delayed_question(
    delayed_question_id: str,
    request: DelayedQuestionAnswerRequest,
) -> DelayedQuestionResponse:
    try:
        question = future_review_service.answer_question(delayed_question_id, request)
        created_todo = None
        if question.created_todo_id:
            todos = future_review_service.list_future_todos(status="", limit=200)
            created_todo = next((todo for todo in todos if todo.future_todo_id == question.created_todo_id), None)
        return DelayedQuestionResponse(
            delayed_question=question,
            created_todo=created_todo,
            safety=future_review_service._safety(
                {"delayed_question": question, "created_todo": created_todo}
            ),
        )
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.get("/future-todos", response_model=FutureTodoResponse)
def get_future_todos(
    scene_id: Optional[str] = Query(default=None),
    chapter_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=200),
) -> FutureTodoResponse:
    try:
        todos = future_review_service.list_future_todos(
            scene_id=scene_id or "",
            chapter_id=chapter_id or "",
            status=status or "",
            limit=limit,
        )
        response = FutureTodoResponse(
            future_todos=todos,
            count=len(todos),
        )
        response.safety = future_review_service._safety(response)
        future_review_service._guard_safe_payload(response)
        return response
    except StorageError as exc:
        _raise_future_review_error(exc)


@router.get("/summary", response_model=FutureReviewSummaryResponse)
def get_future_review_summary(
    scene_id: Optional[str] = Query(default=None),
    chapter_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> FutureReviewSummaryResponse:
    try:
        return future_review_service.summary(
            scene_id=scene_id or "",
            chapter_id=chapter_id or "",
            limit=limit,
        )
    except StorageError as exc:
        _raise_future_review_error(exc)
