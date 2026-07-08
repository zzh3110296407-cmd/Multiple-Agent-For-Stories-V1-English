from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.future_review import (
    DELAYED_QUESTION_ACTION_TYPES,
    DelayedQuestion,
    DelayedQuestionAnswerRequest,
    DelayedQuestionCreateRequest,
    DelayedQuestionOption,
    DelayedQuestionReadyQueryResponse,
    FutureIssue,
    FutureIssueCreateRequest,
    FutureIssueResponse,
    FutureReviewSummaryResponse,
    FutureTodo,
    FutureTodoResponse,
    FUTURE_TODO_TYPES,
    REVEAL_CONDITIONS,
)
from app.backend.models.scene_candidate_cache import (
    CachedSceneCandidate,
    CandidateCacheInvalidationRecord,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.scene_candidate_cache_service import (
    INVALIDATION_RECORDS_FILE_NAME,
    SceneCandidateCacheService,
)
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
MAX_SAFE_TEXT_LENGTH = 700
MAX_SAFE_LABEL_LENGTH = 260
MAX_LIST_ITEMS = 10
FUTURE_ISSUES_FILE_NAME = "future_issues.json"
DELAYED_QUESTIONS_FILE_NAME = "delayed_questions.json"
FUTURE_TODOS_FILE_NAME = "future_todos.json"

UNSAFE_KEY_NAMES = {
    "prompt",
    "messages",
    "raw_prompt",
    "raw_response",
    "raw_text",
    "hidden_reasoning",
    "internal_reasoning",
    "chain_of_thought",
    "chain-of-thought",
    "cot",
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "story_information_preview",
    "continuity_considerations",
    "open_questions",
    "adjustment_plan",
    "impact_reason",
    "source_affected_refs",
    "api_key",
    "api_key_ref",
    "authorization",
    "secret_key",
    "secret_token",
    "bearer_token",
}
UNSAFE_VALUE_MARKERS = {
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "prose_text",
    "prose text",
    "revised_prose_text",
    "revised prose text",
    "full_prose",
    "bearer ",
}
SECRET_LIKE_PATTERNS = [
    re.compile(r"(?i)(?:^|[^a-z0-9])sk-[a-z0-9][a-z0-9_\-]{8,}"),
    re.compile(r"(?i)(?:^|[^a-z0-9])lsv2_[a-z0-9][a-z0-9_\-]{8,}"),
    re.compile(
        r"(?i)(?:api[_\-\s]?key|secret[_\-\s]?(?:key|token)|authorization)\s*[:=]\s*[a-z0-9_\-]{8,}"
    ),
]


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


class FutureReviewService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        scene_candidate_cache_service: SceneCandidateCacheService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.scene_candidate_cache_service = scene_candidate_cache_service or SceneCandidateCacheService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.future_issues_file = self.data_dir / FUTURE_ISSUES_FILE_NAME
        self.delayed_questions_file = self.data_dir / DELAYED_QUESTIONS_FILE_NAME
        self.future_todos_file = self.data_dir / FUTURE_TODOS_FILE_NAME
        self.invalidation_records_file = self.data_dir / INVALIDATION_RECORDS_FILE_NAME

    def create_future_issue(self, request: FutureIssueCreateRequest | dict[str, Any]) -> FutureIssue:
        normalized = (
            request
            if isinstance(request, FutureIssueCreateRequest)
            else FutureIssueCreateRequest(**request)
        )
        timestamp = now_iso()
        issue = FutureIssue(
            future_issue_id=self._next_future_issue_id(),
            issue_type=normalized.issue_type,
            source_type=normalized.source_type,
            source_id=_short_text(normalized.source_id, MAX_SAFE_LABEL_LENGTH),
            target_chapter_id=_short_text(normalized.target_chapter_id, MAX_SAFE_LABEL_LENGTH),
            target_scene_id=_short_text(normalized.target_scene_id, MAX_SAFE_LABEL_LENGTH),
            target_scene_index=normalized.target_scene_index,
            reveal_condition=normalized.reveal_condition,
            severity=normalized.severity,
            status="open",
            safe_summary=self._sanitize_payload(normalized.safe_summary),
            user_visible_question_hint=_short_text(
                normalized.user_visible_question_hint,
                MAX_SAFE_TEXT_LENGTH,
            ),
            related_cache_ids=_safe_string_list(normalized.related_cache_ids),
            related_cached_candidate_ids=_safe_string_list(normalized.related_cached_candidate_ids),
            related_invalidation_record_ids=_safe_string_list(normalized.related_invalidation_record_ids),
            related_candidate_ids=_safe_string_list(normalized.related_candidate_ids),
            related_snapshot_ids=_safe_string_list(normalized.related_snapshot_ids),
            related_memory_ids=_safe_string_list(normalized.related_memory_ids),
            related_narrative_debt_ids=_safe_string_list(normalized.related_narrative_debt_ids),
            related_continuity_issue_ids=_safe_string_list(normalized.related_continuity_issue_ids),
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._guard_safe_payload(issue)
        return self._upsert_issue(issue, preserve_existing_status=False)

    def create_issue_from_cached_candidate(
        self,
        cached_candidate_id: str,
        reveal_condition: str = "when_user_opens_scene",
    ) -> FutureIssue:
        condition = self._validated_reveal_condition(reveal_condition)
        candidate = self.scene_candidate_cache_service.get_cached_candidate(cached_candidate_id)
        issue = self._issue_from_cached_candidate(candidate, condition)
        return self._upsert_issue(issue, preserve_existing_status=True)

    def create_issue_from_invalidation(
        self,
        invalidation_record_id: str,
        reveal_condition: str = "when_user_opens_scene",
    ) -> FutureIssue:
        condition = self._validated_reveal_condition(reveal_condition)
        record = self._get_invalidation_record(invalidation_record_id)
        candidate: CachedSceneCandidate | None = None
        if record.cached_candidate_id:
            try:
                candidate = self.scene_candidate_cache_service.get_cached_candidate(record.cached_candidate_id)
            except StorageError:
                candidate = None
        issue = self._issue_from_invalidation(record, candidate, condition)
        return self._upsert_issue(issue, preserve_existing_status=True)

    def backfill_issues_from_cache(
        self,
        scene_id: str = "",
        chapter_id: str = "",
        include_stale: bool = True,
        limit: int = 100,
    ) -> FutureReviewSummaryResponse:
        clean_scene_id = _short_text(scene_id, MAX_SAFE_LABEL_LENGTH)
        clean_chapter_id = _short_text(chapter_id, MAX_SAFE_LABEL_LENGTH)
        bounded_limit = max(1, min(int(limit or 100), 300))
        summary = self.scene_candidate_cache_service.summary(
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            include_stale=include_stale,
            limit=bounded_limit,
        )
        for candidate in summary.candidates:
            if candidate.cache_status == "stale":
                self._upsert_issue(
                    self._issue_from_cached_candidate(candidate, "when_user_opens_scene"),
                    preserve_existing_status=True,
                )
            for warning in _safe_string_list(candidate.risk_warnings):
                self._upsert_issue(
                    self._issue_from_risk_warning(candidate, warning, "when_user_opens_scene"),
                    preserve_existing_status=True,
                )

        cached_ids = {candidate.cached_candidate_id for candidate in summary.candidates}
        for record in self._read_invalidation_records():
            if record.cached_candidate_id and record.cached_candidate_id not in cached_ids:
                continue
            candidate = None
            if record.cached_candidate_id:
                try:
                    candidate = self.scene_candidate_cache_service.get_cached_candidate(record.cached_candidate_id)
                except StorageError:
                    candidate = None
            if clean_scene_id and candidate and candidate.target_scene_id != clean_scene_id:
                continue
            if clean_chapter_id and candidate and candidate.target_chapter_id != clean_chapter_id:
                continue
            self._upsert_issue(
                self._issue_from_invalidation(record, candidate, "when_user_opens_scene"),
                preserve_existing_status=True,
            )
        return self.summary(
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            limit=bounded_limit,
        )

    def list_future_issues(
        self,
        scene_id: str = "",
        chapter_id: str = "",
        status: str = "",
        limit: int = 50,
    ) -> list[FutureIssue]:
        clean_scene_id = _short_text(scene_id, MAX_SAFE_LABEL_LENGTH)
        clean_chapter_id = _short_text(chapter_id, MAX_SAFE_LABEL_LENGTH)
        clean_status = _short_text(status, MAX_SAFE_LABEL_LENGTH)
        issues = self._read_future_issues()
        if clean_scene_id:
            issues = [issue for issue in issues if issue.target_scene_id == clean_scene_id]
        if clean_chapter_id:
            issues = [issue for issue in issues if issue.target_chapter_id == clean_chapter_id]
        if clean_status:
            issues = [issue for issue in issues if issue.status == clean_status]
        result = sorted(issues, key=lambda item: item.updated_at, reverse=True)[: max(1, min(int(limit or 50), 200))]
        self._guard_safe_payload(result)
        return result

    def create_delayed_question(
        self,
        future_issue_id: str,
        request: DelayedQuestionCreateRequest | dict[str, Any] | None = None,
    ) -> DelayedQuestion:
        issue = self._get_future_issue(future_issue_id)
        normalized: DelayedQuestionCreateRequest | None = None
        if request is not None:
            normalized = (
                request
                if isinstance(request, DelayedQuestionCreateRequest)
                else DelayedQuestionCreateRequest(**request)
            )
        timestamp = now_iso()
        reveal_condition = (
            self._validated_reveal_condition(normalized.reveal_condition)
            if normalized and normalized.reveal_condition
            else issue.reveal_condition
        )
        question = DelayedQuestion(
            delayed_question_id=f"delayed_question_{issue.future_issue_id}",
            future_issue_id=issue.future_issue_id,
            target_chapter_id=issue.target_chapter_id,
            target_scene_id=issue.target_scene_id,
            target_scene_index=issue.target_scene_index,
            reveal_condition=reveal_condition,
            question_text=_short_text(
                (normalized.question_text if normalized and normalized.question_text else "")
                or issue.user_visible_question_hint
                or self._default_question_text(issue),
                MAX_SAFE_TEXT_LENGTH,
            ),
            context_summary=self._sanitize_payload(
                normalized.context_summary
                if normalized and normalized.context_summary
                else issue.safe_summary
            ),
            options=(
                normalized.options
                if normalized and normalized.options
                else self._default_question_options(issue)
            ),
            status="pending",
            created_at=timestamp,
            updated_at=timestamp,
        )
        question = self._upsert_question(question)
        if issue.status in {"open", "question_created"}:
            self._set_issue_status(issue.future_issue_id, "question_created")
        return question

    def ready_questions(
        self,
        scene_id: str = "",
        chapter_id: str = "",
        reveal_condition: str = "",
        limit: int = 50,
    ) -> DelayedQuestionReadyQueryResponse:
        clean_scene_id = _short_text(scene_id, MAX_SAFE_LABEL_LENGTH)
        clean_chapter_id = _short_text(chapter_id, MAX_SAFE_LABEL_LENGTH)
        clean_condition = _short_text(reveal_condition, MAX_SAFE_LABEL_LENGTH)
        questions = [
            question
            for question in self._read_delayed_questions()
            if question.status in {"pending", "ready", "deferred"}
        ]
        if clean_condition:
            questions = [
                question
                for question in questions
                if self._effective_reveal_condition(question) == clean_condition
            ]
        if clean_scene_id and clean_condition != "manual_review":
            questions = [question for question in questions if question.target_scene_id == clean_scene_id]
        if clean_chapter_id and clean_condition != "manual_review":
            questions = [question for question in questions if question.target_chapter_id == clean_chapter_id]
        bounded_limit = max(1, min(int(limit or 50), 200))
        questions = sorted(questions, key=lambda item: item.updated_at, reverse=True)[:bounded_limit]
        response = DelayedQuestionReadyQueryResponse(
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            reveal_condition=clean_condition,
            delayed_questions=questions,
            count=len(questions),
        )
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def answer_question(
        self,
        delayed_question_id: str,
        request: DelayedQuestionAnswerRequest | dict[str, Any],
    ) -> DelayedQuestion:
        normalized = (
            request
            if isinstance(request, DelayedQuestionAnswerRequest)
            else DelayedQuestionAnswerRequest(**request)
        )
        question = self._get_delayed_question(delayed_question_id)
        option = self._get_question_option(question, normalized.selected_option_id)
        if option.requires_text and not str(normalized.answer_text or "").strip():
            raise StorageError("FUTURE_REVIEW_ANSWER_TEXT_REQUIRED: selected option requires answer_text.")
        self._guard_safe_payload(
            {
                "selected_option_id": normalized.selected_option_id,
                "answer_text": normalized.answer_text,
                "decision_summary": normalized.decision_summary,
                "deferred_until_reveal_condition": normalized.deferred_until_reveal_condition,
            }
        )
        action_type = option.action_type
        timestamp = now_iso()
        question_status = "answered"
        issue_status = "resolved_by_user_answer"
        created_todo: FutureTodo | None = None
        deferred_until = ""
        if action_type == "dismiss_as_not_needed":
            question_status = "dismissed"
            issue_status = "dismissed"
        elif action_type == "defer_again":
            question_status = "deferred"
            issue_status = "question_created"
            deferred_until = self._validated_reveal_condition(
                normalized.deferred_until_reveal_condition or question.reveal_condition
            )
        elif action_type in {
            "convert_to_todo",
            "mark_as_claim",
            "mark_as_perception",
            "request_regeneration",
        }:
            question_status = "converted_to_todo"
            issue_status = "todo_created"
            created_todo = self._upsert_todo(
                self._todo_from_answer(question, option, normalized)
            )

        updated_question = DelayedQuestion(
            **{
                **model_to_dict(question),
                "status": question_status,
                "user_decision_id": self._decision_id(question.delayed_question_id, action_type),
                "selected_option_id": _short_text(normalized.selected_option_id, MAX_SAFE_LABEL_LENGTH),
                "selected_action_type": action_type,
                "answer_text": _short_text(normalized.answer_text, MAX_SAFE_TEXT_LENGTH),
                "decision_summary": _short_text(
                    normalized.decision_summary
                    or self._default_decision_summary(option, normalized.answer_text),
                    MAX_SAFE_TEXT_LENGTH,
                ),
                "answered_at": timestamp,
                "deferred_until_reveal_condition": deferred_until,
                "created_todo_id": created_todo.future_todo_id if created_todo else "",
                "updated_at": timestamp,
            }
        )
        questions = [
            updated_question if item.delayed_question_id == updated_question.delayed_question_id else item
            for item in self._read_delayed_questions()
        ]
        self._set_issue_status(question.future_issue_id, issue_status)
        self._write_questions(questions)
        self._guard_safe_payload(updated_question)
        return updated_question

    def list_future_todos(
        self,
        scene_id: str = "",
        chapter_id: str = "",
        status: str = "open",
        limit: int = 50,
    ) -> list[FutureTodo]:
        clean_scene_id = _short_text(scene_id, MAX_SAFE_LABEL_LENGTH)
        clean_chapter_id = _short_text(chapter_id, MAX_SAFE_LABEL_LENGTH)
        clean_status = _short_text(status, MAX_SAFE_LABEL_LENGTH)
        todos = self._read_future_todos()
        if clean_scene_id:
            todos = [todo for todo in todos if todo.target_scene_id == clean_scene_id]
        if clean_chapter_id:
            todos = [todo for todo in todos if todo.target_chapter_id == clean_chapter_id]
        if clean_status:
            todos = [todo for todo in todos if todo.status == clean_status]
        result = sorted(todos, key=lambda item: item.updated_at, reverse=True)[: max(1, min(int(limit or 50), 200))]
        self._guard_safe_payload(result)
        return result

    def create_future_todo_for_issue(
        self,
        future_issue_id: str,
        *,
        todo_type: str = "manual_follow_up",
        safe_summary: dict[str, Any] | None = None,
        source_answer_summary: str = "",
    ) -> FutureTodo:
        issue = self._get_future_issue(future_issue_id)
        clean_type = _short_text(todo_type or "manual_follow_up", MAX_SAFE_LABEL_LENGTH)
        if clean_type not in FUTURE_TODO_TYPES:
            raise StorageError("FUTURE_REVIEW_TODO_TYPE_INVALID: future todo type is not supported.")
        timestamp = now_iso()
        todo = FutureTodo(
            future_todo_id=f"future_todo_{issue.future_issue_id}_{clean_type}",
            future_issue_id=issue.future_issue_id,
            target_chapter_id=issue.target_chapter_id,
            target_scene_id=issue.target_scene_id,
            target_scene_index=issue.target_scene_index,
            todo_type=clean_type,
            safe_summary=self._sanitize_payload(
                safe_summary
                or {
                    "future_issue_id": issue.future_issue_id,
                    "source_type": issue.source_type,
                    "source_id": issue.source_id,
                }
            ),
            source_answer_summary=_short_text(source_answer_summary, MAX_SAFE_TEXT_LENGTH),
            status="open",
            created_at=timestamp,
            updated_at=timestamp,
        )
        result = self._upsert_todo(todo)
        if issue.status in {"open", "question_created", "todo_created"}:
            self._set_issue_status(issue.future_issue_id, "todo_created")
        return result

    def summary(
        self,
        *,
        scene_id: str = "",
        chapter_id: str = "",
        limit: int = 50,
    ) -> FutureReviewSummaryResponse:
        clean_scene_id = _short_text(scene_id, MAX_SAFE_LABEL_LENGTH)
        clean_chapter_id = _short_text(chapter_id, MAX_SAFE_LABEL_LENGTH)
        bounded_limit = max(1, min(int(limit or 50), 200))
        issues = self.list_future_issues(scene_id=clean_scene_id, chapter_id=clean_chapter_id, limit=bounded_limit)
        questions = self._read_delayed_questions()
        if clean_scene_id:
            questions = [question for question in questions if question.target_scene_id == clean_scene_id]
        if clean_chapter_id:
            questions = [question for question in questions if question.target_chapter_id == clean_chapter_id]
        questions = sorted(questions, key=lambda item: item.updated_at, reverse=True)[:bounded_limit]
        todos = self.list_future_todos(
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            status="",
            limit=bounded_limit,
        )
        response = FutureReviewSummaryResponse(
            project_id=LOCAL_PROJECT_ID,
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            future_issue_count=len(issues),
            delayed_question_count=len(questions),
            future_todo_count=len(todos),
            issue_counts_by_status=self._counts(issues, "status"),
            question_counts_by_status=self._counts(questions, "status"),
            todo_counts_by_status=self._counts(todos, "status"),
            recent_future_issue_ids=[issue.future_issue_id for issue in issues[:MAX_LIST_ITEMS]],
            recent_delayed_question_ids=[question.delayed_question_id for question in questions[:MAX_LIST_ITEMS]],
            recent_future_todo_ids=[todo.future_todo_id for todo in todos[:MAX_LIST_ITEMS]],
            future_issues=issues[:MAX_LIST_ITEMS],
            delayed_questions=questions[:MAX_LIST_ITEMS],
            future_todos=todos[:MAX_LIST_ITEMS],
        )
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def debug_summary(self) -> dict[str, Any]:
        issues = self._read_future_issues()
        questions = self._read_delayed_questions()
        todos = self._read_future_todos()
        recent_issues = sorted(issues, key=lambda item: item.updated_at, reverse=True)[:MAX_LIST_ITEMS]
        recent_questions = sorted(questions, key=lambda item: item.updated_at, reverse=True)[:MAX_LIST_ITEMS]
        recent_todos = sorted(todos, key=lambda item: item.updated_at, reverse=True)[:MAX_LIST_ITEMS]
        payload = {
            "available": True,
            "future_issue_count": len(issues),
            "delayed_question_count": len(questions),
            "future_todo_count": len(todos),
            "issue_counts_by_status": self._counts(issues, "status"),
            "question_counts_by_status": self._counts(questions, "status"),
            "todo_counts_by_status": self._counts(todos, "status"),
            "recent_future_issue_ids": [issue.future_issue_id for issue in recent_issues],
            "recent_delayed_question_ids": [question.delayed_question_id for question in recent_questions],
            "recent_future_todo_ids": [todo.future_todo_id for todo in recent_todos],
            "recent_issues": [self._issue_debug_row(issue) for issue in recent_issues],
            "recent_questions": [self._question_debug_row(question) for question in recent_questions],
            "recent_todos": [self._todo_debug_row(todo) for todo in recent_todos],
            "storage_files": [
                FUTURE_ISSUES_FILE_NAME,
                DELAYED_QUESTIONS_FILE_NAME,
                FUTURE_TODOS_FILE_NAME,
            ],
        }
        payload["safety"] = self._safety(payload)
        self._guard_safe_payload(payload)
        return payload

    def _issue_from_cached_candidate(
        self,
        candidate: CachedSceneCandidate,
        reveal_condition: str,
    ) -> FutureIssue:
        timestamp = now_iso()
        severity = "medium"
        if candidate.cache_status == "stale":
            severity = "requires_user_confirmation"
        if candidate.source_candidate_status == "blocked":
            severity = "blocking_before_commit"
        return FutureIssue(
            future_issue_id=f"future_issue_cached_{candidate.cached_candidate_id}",
            issue_type="stale_cached_candidate",
            source_type="cached_scene_candidate",
            source_id=candidate.cached_candidate_id,
            target_chapter_id=candidate.target_chapter_id,
            target_scene_id=candidate.target_scene_id,
            target_scene_index=candidate.target_scene_index,
            reveal_condition=reveal_condition,
            severity=severity,
            status="open",
            safe_summary=self._sanitize_payload(
                {
                    "cache_status": candidate.cache_status,
                    "source_candidate_type": candidate.source_candidate_type,
                    "source_candidate_status": candidate.source_candidate_status,
                    "preview_label": candidate.preview_label,
                    "user_visible_reason": candidate.user_visible_reason,
                    "candidate_summary": candidate.safe_summary,
                    "stale_reason_refs": candidate.stale_reason_refs,
                }
            ),
            user_visible_question_hint="这个未来场景候选已经过期。继续前是否需要重新审查它？",
            related_cache_ids=_safe_string_list([candidate.cache_id]),
            related_cached_candidate_ids=_safe_string_list([candidate.cached_candidate_id]),
            related_invalidation_record_ids=_safe_string_list(candidate.invalidation_record_ids),
            related_candidate_ids=_safe_string_list([candidate.source_candidate_id]),
            related_snapshot_ids=_safe_string_list(candidate.based_on_snapshot_ids),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _issue_from_invalidation(
        self,
        record: CandidateCacheInvalidationRecord,
        candidate: CachedSceneCandidate | None,
        reveal_condition: str,
    ) -> FutureIssue:
        timestamp = now_iso()
        return FutureIssue(
            future_issue_id=f"future_issue_invalidation_{record.invalidation_record_id}",
            issue_type="cache_invalidation",
            source_type="candidate_cache_invalidation",
            source_id=record.invalidation_record_id,
            target_chapter_id=candidate.target_chapter_id if candidate else "",
            target_scene_id=candidate.target_scene_id if candidate else "",
            target_scene_index=candidate.target_scene_index if candidate else None,
            reveal_condition=reveal_condition,
            severity="requires_user_confirmation" if record.new_status == "stale" else "medium",
            status="open",
            safe_summary=self._sanitize_payload(
                {
                    "invalidation_type": record.invalidation_type,
                    "changed_ref_type": record.changed_ref_type,
                    "changed_ref_id": record.changed_ref_id,
                    "previous_status": record.previous_status,
                    "new_status": record.new_status,
                    "user_visible_reason": record.user_visible_reason,
                }
            ),
            user_visible_question_hint="候选缓存因显式依赖变化而过期。是否需要在当前上下文中处理？",
            related_cache_ids=_safe_string_list([record.cache_id]),
            related_cached_candidate_ids=_safe_string_list([record.cached_candidate_id]),
            related_invalidation_record_ids=_safe_string_list([record.invalidation_record_id]),
            related_candidate_ids=_safe_string_list([record.source_candidate_id]),
            related_snapshot_ids=_safe_string_list(record.affected_snapshot_ids),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _issue_from_risk_warning(
        self,
        candidate: CachedSceneCandidate,
        warning: str,
        reveal_condition: str,
    ) -> FutureIssue:
        timestamp = now_iso()
        warning_text = _short_text(warning, MAX_SAFE_TEXT_LENGTH)
        warning_hash = _safe_hash(warning_text)
        severity = "requires_user_confirmation" if _requires_user_choice(warning_text) else "medium"
        return FutureIssue(
            future_issue_id=f"future_issue_risk_{candidate.cached_candidate_id}_{warning_hash}",
            issue_type="candidate_risk_warning",
            source_type=candidate.source_candidate_type,
            source_id=candidate.source_candidate_id,
            target_chapter_id=candidate.target_chapter_id,
            target_scene_id=candidate.target_scene_id,
            target_scene_index=candidate.target_scene_index,
            reveal_condition=reveal_condition,
            severity=severity,
            status="open",
            safe_summary=self._sanitize_payload(
                {
                    "risk_warning": warning_text,
                    "cached_candidate_id": candidate.cached_candidate_id,
                    "cache_status": candidate.cache_status,
                    "preview_label": candidate.preview_label,
                }
            ),
            user_visible_question_hint="这个未来候选带有风险提示。进入相关场景时是否需要人工选择处理方式？",
            related_cache_ids=_safe_string_list([candidate.cache_id]),
            related_cached_candidate_ids=_safe_string_list([candidate.cached_candidate_id]),
            related_invalidation_record_ids=_safe_string_list(candidate.invalidation_record_ids),
            related_candidate_ids=_safe_string_list([candidate.source_candidate_id]),
            related_snapshot_ids=_safe_string_list(candidate.based_on_snapshot_ids),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _upsert_issue(
        self,
        incoming: FutureIssue,
        *,
        preserve_existing_status: bool,
    ) -> FutureIssue:
        issues = self._read_future_issues()
        timestamp = now_iso()
        result = incoming
        updated: list[FutureIssue] = []
        replaced = False
        for existing in issues:
            if existing.future_issue_id != incoming.future_issue_id:
                updated.append(existing)
                continue
            result = FutureIssue(
                **{
                    **model_to_dict(incoming),
                    "status": existing.status if preserve_existing_status else incoming.status,
                    "created_at": existing.created_at,
                    "updated_at": timestamp,
                }
            )
            updated.append(result)
            replaced = True
        if not replaced:
            updated.append(incoming)
        self._write_issues(updated)
        self._guard_safe_payload(result)
        return result

    def _upsert_question(self, incoming: DelayedQuestion) -> DelayedQuestion:
        questions = self._read_delayed_questions()
        timestamp = now_iso()
        result = incoming
        updated: list[DelayedQuestion] = []
        replaced = False
        for existing in questions:
            if existing.delayed_question_id != incoming.delayed_question_id:
                updated.append(existing)
                continue
            result = DelayedQuestion(
                **{
                    **model_to_dict(incoming),
                    "status": existing.status,
                    "user_decision_id": existing.user_decision_id,
                    "selected_option_id": existing.selected_option_id,
                    "selected_action_type": existing.selected_action_type,
                    "answer_text": existing.answer_text,
                    "decision_summary": existing.decision_summary,
                    "answered_at": existing.answered_at,
                    "deferred_until_reveal_condition": existing.deferred_until_reveal_condition,
                    "created_todo_id": existing.created_todo_id,
                    "created_at": existing.created_at,
                    "updated_at": timestamp,
                }
            )
            updated.append(result)
            replaced = True
        if not replaced:
            updated.append(incoming)
        self._write_questions(updated)
        self._guard_safe_payload(result)
        return result

    def _upsert_todo(self, incoming: FutureTodo) -> FutureTodo:
        todos = self._read_future_todos()
        timestamp = now_iso()
        result = incoming
        updated: list[FutureTodo] = []
        replaced = False
        for existing in todos:
            if existing.future_todo_id != incoming.future_todo_id:
                updated.append(existing)
                continue
            result = FutureTodo(
                **{
                    **model_to_dict(incoming),
                    "status": existing.status,
                    "created_at": existing.created_at,
                    "updated_at": timestamp,
                }
            )
            updated.append(result)
            replaced = True
        if not replaced:
            updated.append(incoming)
        self._write_todos(updated)
        self._guard_safe_payload(result)
        return result

    def _todo_from_answer(
        self,
        question: DelayedQuestion,
        option: DelayedQuestionOption,
        request: DelayedQuestionAnswerRequest,
    ) -> FutureTodo:
        action_type = option.action_type
        todo_type = {
            "convert_to_todo": "resolve_open_question",
            "mark_as_claim": "consider_claim",
            "mark_as_perception": "consider_perception",
            "request_regeneration": "regeneration_request",
        }.get(action_type, "review_later")
        timestamp = now_iso()
        return FutureTodo(
            future_todo_id=f"future_todo_{question.delayed_question_id}_{todo_type}",
            future_issue_id=question.future_issue_id,
            delayed_question_id=question.delayed_question_id,
            target_chapter_id=question.target_chapter_id,
            target_scene_id=question.target_scene_id,
            target_scene_index=question.target_scene_index,
            todo_type=todo_type,
            safe_summary=self._sanitize_payload(
                {
                    "question_text": question.question_text,
                    "selected_option_id": option.option_id,
                    "selected_action_type": option.action_type,
                    "safe_effect": option.safe_effect,
                }
            ),
            source_answer_summary=_short_text(
                request.decision_summary or request.answer_text or option.label,
                MAX_SAFE_TEXT_LENGTH,
            ),
            status="open",
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _set_issue_status(self, future_issue_id: str, status: str) -> None:
        issues = self._read_future_issues()
        timestamp = now_iso()
        found = False
        updated: list[FutureIssue] = []
        for issue in issues:
            if issue.future_issue_id != future_issue_id:
                updated.append(issue)
                continue
            updated.append(
                FutureIssue(
                    **{
                        **model_to_dict(issue),
                        "status": status,
                        "updated_at": timestamp,
                    }
                )
            )
            found = True
        if not found:
            raise StorageError("FUTURE_REVIEW_ISSUE_NOT_FOUND: future issue does not exist.")
        self._write_issues(updated)

    def _effective_reveal_condition(self, question: DelayedQuestion) -> str:
        if question.status == "deferred" and question.deferred_until_reveal_condition:
            return question.deferred_until_reveal_condition
        return question.reveal_condition

    def _default_question_options(self, issue: FutureIssue) -> list[DelayedQuestionOption]:
        options = [
            DelayedQuestionOption(
                option_id="answer_question",
                label="记录回答",
                action_type="answer_question",
                safe_effect="只记录 M5 本地回答，不写入事实。",
                requires_text=True,
            ),
            DelayedQuestionOption(
                option_id="dismiss_as_not_needed",
                label="不需要处理",
                action_type="dismiss_as_not_needed",
                safe_effect="关闭这个未来问题。",
            ),
            DelayedQuestionOption(
                option_id="defer_again",
                label="继续延后",
                action_type="defer_again",
                safe_effect="保留问题并等待下一次匹配条件。",
            ),
            DelayedQuestionOption(
                option_id="convert_to_todo",
                label="转为未来待办",
                action_type="convert_to_todo",
                safe_effect="创建 FutureTodo，不自动应用更改。",
                creates_todo=True,
            ),
        ]
        if issue.issue_type in {"candidate_risk_warning", "manual_future_issue"}:
            options.extend(
                [
                    DelayedQuestionOption(
                        option_id="mark_as_claim",
                        label="标记为主观声明意图",
                        action_type="mark_as_claim",
                        safe_effect="只创建 consider_claim 待办，不写 ClaimRecord。",
                        creates_todo=True,
                    ),
                    DelayedQuestionOption(
                        option_id="mark_as_perception",
                        label="标记为感知意图",
                        action_type="mark_as_perception",
                        safe_effect="只创建 consider_perception 待办，不写 Perception。",
                        creates_todo=True,
                    ),
                    DelayedQuestionOption(
                        option_id="request_regeneration",
                        label="请求后续重生成",
                        action_type="request_regeneration",
                        safe_effect="只创建 regeneration_request 待办，不调用模型。",
                        creates_todo=True,
                    ),
                ]
            )
        return options

    def _default_question_text(self, issue: FutureIssue) -> str:
        if issue.issue_type == "candidate_risk_warning":
            return "这个未来候选存在风险提示。当前上下文是否需要人工决定处理方式？"
        if issue.issue_type == "cache_invalidation":
            return "相关缓存证据已过期。进入当前上下文前是否需要重新审查？"
        if issue.issue_type == "stale_cached_candidate":
            return "这个未来候选已变为 stale。是否继续保留为开放问题？"
        return "这个未来问题现在需要处理吗？"

    def _default_decision_summary(self, option: DelayedQuestionOption, answer_text: str) -> str:
        if answer_text:
            return _short_text(answer_text, MAX_SAFE_TEXT_LENGTH)
        return _short_text(f"User selected {option.action_type}.", MAX_SAFE_TEXT_LENGTH)

    def _decision_id(self, delayed_question_id: str, action_type: str) -> str:
        return f"m5_decision_{_safe_slug(delayed_question_id)}_{_safe_slug(action_type)}"

    def _get_question_option(
        self,
        question: DelayedQuestion,
        selected_option_id: str,
    ) -> DelayedQuestionOption:
        clean_id = _short_text(selected_option_id, MAX_SAFE_LABEL_LENGTH)
        for option in question.options:
            if option.option_id == clean_id:
                return option
        raise StorageError("FUTURE_REVIEW_OPTION_NOT_FOUND: delayed question option does not exist.")

    def _get_future_issue(self, future_issue_id: str) -> FutureIssue:
        clean_id = _short_text(future_issue_id, MAX_SAFE_LABEL_LENGTH)
        for issue in self._read_future_issues():
            if issue.future_issue_id == clean_id:
                return issue
        raise StorageError("FUTURE_REVIEW_ISSUE_NOT_FOUND: future issue does not exist.")

    def _get_delayed_question(self, delayed_question_id: str) -> DelayedQuestion:
        clean_id = _short_text(delayed_question_id, MAX_SAFE_LABEL_LENGTH)
        for question in self._read_delayed_questions():
            if question.delayed_question_id == clean_id:
                return question
        raise StorageError("FUTURE_REVIEW_QUESTION_NOT_FOUND: delayed question does not exist.")

    def _get_invalidation_record(self, invalidation_record_id: str) -> CandidateCacheInvalidationRecord:
        clean_id = _short_text(invalidation_record_id, MAX_SAFE_LABEL_LENGTH)
        for record in self._read_invalidation_records():
            if record.invalidation_record_id == clean_id:
                return record
        raise StorageError("FUTURE_REVIEW_INVALIDATION_NOT_FOUND: cache invalidation record does not exist.")

    def _read_future_issues(self) -> list[FutureIssue]:
        if not self.store.exists(self.future_issues_file):
            return []
        result: list[FutureIssue] = []
        for item in self.store.read_list(self.future_issues_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(FutureIssue(**item))
            except ValidationError as exc:
                raise StorageError("FUTURE_REVIEW_SCHEMA_INVALID: future issue JSON schema is invalid.") from exc
        return result

    def _read_delayed_questions(self) -> list[DelayedQuestion]:
        if not self.store.exists(self.delayed_questions_file):
            return []
        result: list[DelayedQuestion] = []
        for item in self.store.read_list(self.delayed_questions_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(DelayedQuestion(**item))
            except ValidationError as exc:
                raise StorageError("FUTURE_REVIEW_SCHEMA_INVALID: delayed question JSON schema is invalid.") from exc
        return result

    def _read_future_todos(self) -> list[FutureTodo]:
        if not self.store.exists(self.future_todos_file):
            return []
        result: list[FutureTodo] = []
        for item in self.store.read_list(self.future_todos_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(FutureTodo(**item))
            except ValidationError as exc:
                raise StorageError("FUTURE_REVIEW_SCHEMA_INVALID: future todo JSON schema is invalid.") from exc
        return result

    def _read_invalidation_records(self) -> list[CandidateCacheInvalidationRecord]:
        if not self.store.exists(self.invalidation_records_file):
            return []
        result: list[CandidateCacheInvalidationRecord] = []
        for item in self.store.read_list(self.invalidation_records_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(CandidateCacheInvalidationRecord(**item))
            except ValidationError as exc:
                raise StorageError("FUTURE_REVIEW_SCHEMA_INVALID: cache invalidation JSON schema is invalid.") from exc
        return result

    def _write_issues(self, issues: list[FutureIssue]) -> None:
        payload = [model_to_dict(issue) for issue in issues]
        self._guard_safe_payload(payload)
        self.store.write(self.future_issues_file, payload)

    def _write_questions(self, questions: list[DelayedQuestion]) -> None:
        payload = [model_to_dict(question) for question in questions]
        self._guard_safe_payload(payload)
        self.store.write(self.delayed_questions_file, payload)

    def _write_todos(self, todos: list[FutureTodo]) -> None:
        payload = [model_to_dict(todo) for todo in todos]
        self._guard_safe_payload(payload)
        self.store.write(self.future_todos_file, payload)

    def _next_future_issue_id(self) -> str:
        return f"future_issue_manual_{len(self._read_future_issues()) + 1:03d}"

    def _validated_reveal_condition(self, reveal_condition: str) -> str:
        condition = _short_text(reveal_condition or "when_user_opens_scene", MAX_SAFE_LABEL_LENGTH)
        if condition not in REVEAL_CONDITIONS:
            raise StorageError("FUTURE_REVIEW_REVEAL_CONDITION_INVALID: reveal condition is not supported.")
        return condition

    def _issue_debug_row(self, issue: FutureIssue) -> dict[str, Any]:
        return self._sanitize_payload(
            {
                "future_issue_id": issue.future_issue_id,
                "issue_type": issue.issue_type,
                "source_type": issue.source_type,
                "source_id": issue.source_id,
                "target_scene_id": issue.target_scene_id,
                "target_chapter_id": issue.target_chapter_id,
                "reveal_condition": issue.reveal_condition,
                "severity": issue.severity,
                "status": issue.status,
                "summary": issue.safe_summary,
            }
        )

    def _question_debug_row(self, question: DelayedQuestion) -> dict[str, Any]:
        return self._sanitize_payload(
            {
                "delayed_question_id": question.delayed_question_id,
                "future_issue_id": question.future_issue_id,
                "target_scene_id": question.target_scene_id,
                "target_chapter_id": question.target_chapter_id,
                "reveal_condition": question.reveal_condition,
                "status": question.status,
                "selected_action_type": question.selected_action_type,
                "created_todo_id": question.created_todo_id,
            }
        )

    def _todo_debug_row(self, todo: FutureTodo) -> dict[str, Any]:
        return self._sanitize_payload(
            {
                "future_todo_id": todo.future_todo_id,
                "future_issue_id": todo.future_issue_id,
                "delayed_question_id": todo.delayed_question_id,
                "target_scene_id": todo.target_scene_id,
                "target_chapter_id": todo.target_chapter_id,
                "todo_type": todo.todo_type,
                "status": todo.status,
                "summary": todo.safe_summary,
            }
        )

    def _counts(self, items: list[Any], attr: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in items:
            value = getattr(item, attr, "")
            key = str(value or "").strip()
            if not key:
                continue
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items()))

    def _sanitize_payload(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            value = model_to_dict(value)
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if key_text.casefold() in UNSAFE_KEY_NAMES:
                    continue
                result[key_text] = self._sanitize_payload(item)
            return result
        if isinstance(value, list):
            return [self._sanitize_payload(item) for item in value[:MAX_LIST_ITEMS]]
        if isinstance(value, str):
            return _short_text(value, MAX_SAFE_TEXT_LENGTH)
        return value

    def _guard_safe_payload(self, value: Any) -> None:
        issues = self._scan_for_unsafe_payload(value)
        if issues:
            raise StorageError(
                "FUTURE_REVIEW_UNSAFE_PAYLOAD_BLOCKED: "
                + "; ".join(issues[:5])
            )

    def _safety(self, value: Any) -> dict[str, Any]:
        issues = self._scan_for_unsafe_payload(value)
        return {
            "safe": not issues,
            "issues": issues[:MAX_LIST_ITEMS],
        }

    def _scan_for_unsafe_payload(self, value: Any, path: str = "$") -> list[str]:
        issues: list[str] = []
        if isinstance(value, BaseModel):
            value = model_to_dict(value)
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                if key_text.casefold() in UNSAFE_KEY_NAMES:
                    issues.append(f"unsafe_key:{path}.{key_text}")
                    continue
                issues.extend(self._scan_for_unsafe_payload(item, f"{path}.{key_text}"))
            return issues
        if isinstance(value, list):
            for index, item in enumerate(value):
                issues.extend(self._scan_for_unsafe_payload(item, f"{path}[{index}]"))
            return issues
        if isinstance(value, str):
            text = value.strip()
            lower = text.casefold()
            if any(marker in lower for marker in UNSAFE_VALUE_MARKERS):
                issues.append(f"unsafe_value:{path}")
            if any(pattern.search(text) for pattern in SECRET_LIKE_PATTERNS):
                issues.append(f"secret_like_value:{path}")
            if len(text) > MAX_SAFE_TEXT_LENGTH:
                issues.append(f"long_text:{path}")
            return issues
        return issues


def _short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, list) else [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _safe_string_list(values: Any) -> list[str]:
    return [_short_text(value, MAX_SAFE_LABEL_LENGTH) for value in _unique_strings(values)[:MAX_LIST_ITEMS]]


def _safe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _safe_slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip())
    return text[:80] or "item"


def _requires_user_choice(warning: str) -> bool:
    lower = warning.casefold()
    markers = [
        "user",
        "confirm",
        "confirmation",
        "choice",
        "manual",
        "requires",
        "冲突",
        "确认",
        "选择",
        "人工",
    ]
    return any(marker in lower for marker in markers)
