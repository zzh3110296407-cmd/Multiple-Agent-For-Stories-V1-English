from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.decision import Decision
from app.backend.models.future_review import (
    DelayedQuestion,
    DelayedQuestionCreateRequest,
    FutureIssue,
    FutureIssueCreateRequest,
)
from app.backend.models.pre_modify import PreModifyCandidate
from app.backend.models.pre_modify_workspace import (
    CandidateAcceptRequest,
    CandidateApplyPlan,
    CandidateApplyPlanItem,
    CandidateApplyPlanRequest,
    CandidateApplyResult,
    CandidateDeferRequest,
    CandidateRejectRequest,
    CandidateReviseRequest,
    CandidateRevisionRequest,
    PreModifyUserAction,
    PreModifyWorkspaceCandidateView,
    PreModifyWorkspaceState,
)
from app.backend.models.scene_candidate_cache import CachedSceneCandidate
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.future_review_service import FutureReviewService
from app.backend.services.pre_modify_pipeline_service import PreModifyPipelineService
from app.backend.services.scene_candidate_cache_service import SceneCandidateCacheService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
MAX_SAFE_TEXT_LENGTH = 500
MAX_SAFE_LABEL_LENGTH = 220
MAX_LIST_ITEMS = 10
MAX_STORED_RECORDS = 500
USER_ACTIONS_FILE_NAME = "pre_modify_user_actions.json"
APPLY_PLANS_FILE_NAME = "candidate_apply_plans.json"
REVISION_REQUESTS_FILE_NAME = "candidate_revision_requests.json"
DECISIONS_FILE_NAME = "decisions.json"
ACTION_DECISION_TYPES = {
    "accept": "m7_pre_modify_accept",
    "reject": "m7_pre_modify_reject",
    "revise": "m7_pre_modify_revise",
    "defer": "m7_pre_modify_defer",
}
ACCEPTABLE_SOURCE_STATUSES = {"ready", "warning_only"}
ACCEPTABLE_CACHE_STATUSES = {"active"}
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
    "full prose",
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


def _short_text(value: Any, limit: int = MAX_SAFE_TEXT_LENGTH) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _short_text(value, MAX_SAFE_LABEL_LENGTH)
        if text and text not in result:
            result.append(text)
    return result[:MAX_LIST_ITEMS]


class PreModifyWorkspaceService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        pre_modify_service: PreModifyPipelineService | None = None,
        scene_candidate_cache_service: SceneCandidateCacheService | None = None,
        future_review_service: FutureReviewService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.pre_modify_service = pre_modify_service or PreModifyPipelineService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.scene_candidate_cache_service = (
            scene_candidate_cache_service
            or SceneCandidateCacheService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
                pre_modify_service=self.pre_modify_service,
            )
        )
        self.future_review_service = future_review_service or FutureReviewService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            scene_candidate_cache_service=self.scene_candidate_cache_service,
        )
        self.actions_file = self.data_dir / USER_ACTIONS_FILE_NAME
        self.apply_plans_file = self.data_dir / APPLY_PLANS_FILE_NAME
        self.revision_requests_file = self.data_dir / REVISION_REQUESTS_FILE_NAME
        self.decisions_file = self.data_dir / DECISIONS_FILE_NAME

    def workspace_state(
        self,
        *,
        scene_id: str = "",
        chapter_id: str = "",
        include_stale: bool = True,
        limit: int = 50,
    ) -> PreModifyWorkspaceState:
        clean_scene_id = _short_text(scene_id, MAX_SAFE_LABEL_LENGTH)
        clean_chapter_id = _short_text(chapter_id, MAX_SAFE_LABEL_LENGTH)
        bounded_limit = max(1, min(int(limit or 50), 200))
        candidates = self.pre_modify_service.list_candidates(limit=bounded_limit)
        if clean_scene_id:
            candidates = [item for item in candidates if item.target_scene_id == clean_scene_id]
        if clean_chapter_id:
            candidates = [item for item in candidates if item.target_chapter_id == clean_chapter_id]

        views: list[PreModifyWorkspaceCandidateView] = []
        ready_question_rows: list[dict[str, Any]] = []
        for candidate in candidates[:bounded_limit]:
            try:
                cached = self._resolve_cached_wrapper(candidate, "")
            except StorageError:
                cached = None
            if cached and not include_stale and cached.cache_status != "active":
                continue
            view = self._candidate_view(candidate, cached)
            views.append(view)
            ready_question_rows.extend(
                self._question_debug_rows(
                    candidate_id=candidate.candidate_id,
                    cached_candidate_id=cached.cached_candidate_id if cached else "",
                    scene_id=candidate.target_scene_id,
                    chapter_id=candidate.target_chapter_id,
                )
            )

        future_summary = self.future_review_service.summary(
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            limit=bounded_limit,
        )
        actions = self.list_user_actions(scene_id=clean_scene_id, chapter_id=clean_chapter_id, limit=bounded_limit)
        response = PreModifyWorkspaceState(
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            target_scene_index=views[0].target_scene_index if views else None,
            candidates=views,
            ready_delayed_questions=ready_question_rows[:MAX_LIST_ITEMS],
            future_issue_count=future_summary.future_issue_count,
            future_todo_count=future_summary.future_todo_count,
            candidate_count=len(views),
            action_count=len(actions),
            latest_action_ids=[action.user_action_id for action in actions[:MAX_LIST_ITEMS]],
        )
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def build_apply_plan(
        self,
        candidate_id: str,
        cached_candidate_id: str = "",
        force_refresh: bool = False,
    ) -> CandidateApplyPlan:
        candidate, cached = self._resolve_candidate_and_cache(candidate_id, cached_candidate_id)
        if not force_refresh:
            latest = self._latest_apply_plan(candidate.candidate_id, cached.cached_candidate_id)
            if latest and latest.plan_status in {"ready", "blocked", "draft"}:
                self._guard_safe_payload(latest)
                return latest
        blocking_reasons, blocking_question_ids, warning_question_ids = self._blocking_context(candidate, cached)
        warning_reasons = _unique_strings(candidate.risk_warnings)
        items = self._apply_plan_items(
            candidate,
            cached,
            blocking_question_ids=blocking_question_ids,
            blocking_reasons=blocking_reasons,
        )
        timestamp = now_iso()
        existing_plans = self._read_apply_plans()
        plan = CandidateApplyPlan(
            apply_plan_id=f"candidate_apply_plan_{len(existing_plans) + 1:03d}",
            candidate_id=candidate.candidate_id,
            cached_candidate_id=cached.cached_candidate_id,
            source_candidate_type=cached.source_candidate_type,
            target_scene_id=candidate.target_scene_id,
            target_chapter_id=candidate.target_chapter_id,
            target_scene_index=candidate.target_scene_index,
            plan_status="blocked" if blocking_reasons else "ready",
            apply_mode="formal_flow_handoff",
            source_status=candidate.status,
            cache_status=cached.cache_status,
            adjustment_plan_id=candidate.adjustment_plan_id,
            impact_reason_id=candidate.impact_reason_id,
            snapshot_ids=_unique_strings(candidate.target_snapshot_ids + candidate.affected_snapshot_ids + cached.based_on_snapshot_ids),
            blocking_reasons=blocking_reasons,
            warning_reasons=warning_reasons,
            blocking_delayed_question_ids=blocking_question_ids,
            warning_delayed_question_ids=warning_question_ids,
            items=items,
            created_at=timestamp,
            updated_at=timestamp,
        )
        updated_plans: list[CandidateApplyPlan] = []
        for existing in existing_plans:
            if (
                existing.candidate_id == plan.candidate_id
                and existing.cached_candidate_id == plan.cached_candidate_id
                and existing.plan_status in {"draft", "ready", "blocked"}
            ):
                updated_plans.append(
                    CandidateApplyPlan(
                        **{
                            **model_to_dict(existing),
                            "plan_status": "superseded",
                            "updated_at": timestamp,
                        }
                    )
                )
            else:
                updated_plans.append(existing)
        updated_plans.append(plan)
        self._write_apply_plans(updated_plans)
        self._guard_safe_payload(plan)
        return plan

    def accept_candidate(
        self,
        candidate_id: str,
        request: CandidateAcceptRequest | dict[str, Any] | None = None,
    ) -> CandidateApplyResult:
        normalized = self._accept_request(request)
        self._guard_safe_payload(normalized)
        candidate, cached = self._resolve_candidate_and_cache(candidate_id, normalized.cached_candidate_id)
        plan = self.build_apply_plan(candidate.candidate_id, cached.cached_candidate_id, force_refresh=True)
        blocked_reasons = list(plan.blocking_reasons)
        action_status = "blocked" if blocked_reasons else "completed"
        action = self._write_action_with_decision(
            action_type="accept",
            action_status=action_status,
            candidate=candidate,
            cached=cached,
            safe_user_note=normalized.safe_user_note,
            safe_action_summary=(
                "Candidate accepted for formal-flow handoff."
                if not blocked_reasons
                else "Candidate accept blocked by preflight gate."
            ),
            blocked_reasons=blocked_reasons,
            apply_plan_id=plan.apply_plan_id,
        )
        final_plan = self._mark_apply_plan(
            plan.apply_plan_id,
            "accepted" if not blocked_reasons else "blocked",
            created_by_action_id=action.user_action_id,
        )
        if not blocked_reasons and normalized.archive_after_accept:
            self.scene_candidate_cache_service.mark_cached_candidate_status(
                cached.cached_candidate_id,
                "archived",
                "Candidate was accepted for guarded formal-flow handling.",
            )
        return self._result(
            success=not blocked_reasons,
            action=action,
            apply_plan=final_plan,
            blocked_reasons=blocked_reasons,
        )

    def reject_candidate(
        self,
        candidate_id: str,
        request: CandidateRejectRequest | dict[str, Any] | None = None,
    ) -> CandidateApplyResult:
        normalized = self._reject_request(request)
        self._guard_safe_payload(normalized)
        candidate, cached = self._resolve_candidate_and_cache(candidate_id, normalized.cached_candidate_id)
        plan = self.build_apply_plan(candidate.candidate_id, cached.cached_candidate_id, force_refresh=False)
        action = self._write_action_with_decision(
            action_type="reject",
            action_status="completed",
            candidate=candidate,
            cached=cached,
            safe_user_note=normalized.safe_user_note,
            safe_action_summary="Candidate rejected; source evidence preserved.",
            apply_plan_id=plan.apply_plan_id,
        )
        final_plan = self._mark_apply_plan(
            plan.apply_plan_id,
            "rejected",
            created_by_action_id=action.user_action_id,
        )
        if normalized.cache_action in {"hide", "archive"}:
            self.scene_candidate_cache_service.mark_cached_candidate_status(
                cached.cached_candidate_id,
                "archived" if normalized.cache_action == "archive" else "hidden",
                "Candidate was manually rejected from the Pre Modify workspace.",
            )
        return self._result(action=action, apply_plan=final_plan)

    def revise_candidate(
        self,
        candidate_id: str,
        request: CandidateReviseRequest | dict[str, Any],
    ) -> CandidateApplyResult:
        normalized = request if isinstance(request, CandidateReviseRequest) else CandidateReviseRequest(**(request or {}))
        self._guard_safe_payload(normalized)
        note = _short_text(normalized.safe_revision_note, MAX_SAFE_TEXT_LENGTH)
        if not note:
            raise StorageError("PRE_MODIFY_WORKSPACE_REVISION_NOTE_REQUIRED: safe_revision_note is required.")
        candidate, cached = self._resolve_candidate_and_cache(candidate_id, normalized.cached_candidate_id)
        timestamp = now_iso()
        revision_id = f"candidate_revision_request_{len(self._read_revision_requests()) + 1:03d}"
        action_id = f"pre_modify_user_action_{len(self._read_actions()) + 1:03d}"
        revision = CandidateRevisionRequest(
            revision_request_id=revision_id,
            source_candidate_id=candidate.candidate_id,
            source_cached_candidate_id=cached.cached_candidate_id,
            parent_user_action_id=action_id,
            target_scene_id=candidate.target_scene_id,
            target_chapter_id=candidate.target_chapter_id,
            target_scene_index=candidate.target_scene_index,
            safe_revision_note=note,
            requested_change_summary=_short_text(normalized.requested_change_summary, MAX_SAFE_TEXT_LENGTH),
            status="recorded",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._guard_safe_payload(revision)
        action = self._write_action_with_decision(
            action_type="revise",
            action_status="recorded",
            candidate=candidate,
            cached=cached,
            safe_user_note=note,
            safe_action_summary="Revision request recorded without model execution.",
            revision_request_id=revision.revision_request_id,
            preset_action_id=action_id,
        )
        self._write_revision_requests(self._read_revision_requests() + [revision])
        return self._result(action=action, revision_request=revision)

    def defer_candidate(
        self,
        candidate_id: str,
        request: CandidateDeferRequest | dict[str, Any] | None = None,
    ) -> CandidateApplyResult:
        normalized = self._defer_request(request)
        self._guard_safe_payload(normalized)
        candidate, cached = self._resolve_candidate_and_cache(candidate_id, normalized.cached_candidate_id)
        issue = self.future_review_service.create_future_issue(
            FutureIssueCreateRequest(
                issue_type="manual_future_issue",
                source_type="cached_scene_candidate" if cached.cached_candidate_id else "pre_modify_candidate",
                source_id=cached.cached_candidate_id or candidate.candidate_id,
                target_chapter_id=candidate.target_chapter_id,
                target_scene_id=candidate.target_scene_id,
                target_scene_index=candidate.target_scene_index,
                reveal_condition=normalized.reveal_condition,
                severity="requires_user_confirmation",
                safe_summary={
                    "candidate_id": candidate.candidate_id,
                    "cached_candidate_id": cached.cached_candidate_id,
                    "action": "defer_pre_modify_candidate",
                    "summary": candidate.adjustment_summary or cached.preview_label,
                },
                user_visible_question_hint=(
                    normalized.question_text
                    or "Review this Pre Modify candidate before applying it to the formal flow."
                ),
                related_cache_ids=[cached.cache_id],
                related_cached_candidate_ids=[cached.cached_candidate_id],
                related_candidate_ids=[candidate.candidate_id],
                related_snapshot_ids=_unique_strings(
                    candidate.target_snapshot_ids + candidate.affected_snapshot_ids + cached.based_on_snapshot_ids
                ),
            )
        )
        question: DelayedQuestion | None = None
        if normalized.create_delayed_question:
            question = self.future_review_service.create_delayed_question(
                issue.future_issue_id,
                DelayedQuestionCreateRequest(
                    reveal_condition=normalized.reveal_condition,
                    question_text=(
                        normalized.question_text
                        or "Should this Pre Modify candidate be handled now, revised, or left for later review?"
                    ),
                    context_summary={
                        "candidate_id": candidate.candidate_id,
                        "cached_candidate_id": cached.cached_candidate_id,
                        "safe_summary": candidate.safe_summary,
                    },
                ),
            )
        todo = None
        if normalized.create_future_todo:
            todo = self.future_review_service.create_future_todo_for_issue(
                issue.future_issue_id,
                todo_type="manual_follow_up",
                safe_summary={
                    "candidate_id": candidate.candidate_id,
                    "cached_candidate_id": cached.cached_candidate_id,
                    "action": "manual_follow_up",
                },
                source_answer_summary=normalized.safe_user_note,
            )
        plan = self.build_apply_plan(candidate.candidate_id, cached.cached_candidate_id, force_refresh=False)
        action = self._write_action_with_decision(
            action_type="defer",
            action_status="recorded",
            candidate=candidate,
            cached=cached,
            safe_user_note=normalized.safe_user_note,
            safe_action_summary="Candidate deferred through Future Review evidence.",
            apply_plan_id=plan.apply_plan_id,
            future_issue_id=issue.future_issue_id,
            delayed_question_id=question.delayed_question_id if question else "",
            future_todo_id=todo.future_todo_id if todo else "",
        )
        final_plan = self._mark_apply_plan(
            plan.apply_plan_id,
            "deferred",
            created_by_action_id=action.user_action_id,
        )
        return self._result(
            action=action,
            apply_plan=final_plan,
            created_future_issue_id=issue.future_issue_id,
            created_delayed_question_id=question.delayed_question_id if question else "",
            created_future_todo_id=todo.future_todo_id if todo else "",
        )

    def list_user_actions(
        self,
        *,
        candidate_id: str = "",
        scene_id: str = "",
        chapter_id: str = "",
        limit: int = 50,
    ) -> list[PreModifyUserAction]:
        actions = self._read_actions()
        if candidate_id:
            actions = [item for item in actions if item.candidate_id == candidate_id]
        if scene_id:
            actions = [item for item in actions if item.target_scene_id == scene_id]
        if chapter_id:
            actions = [item for item in actions if item.target_chapter_id == chapter_id]
        result = sorted(actions, key=lambda item: item.created_at, reverse=True)[: max(1, min(int(limit or 50), 200))]
        self._guard_safe_payload(result)
        return result

    def list_apply_plans(
        self,
        *,
        candidate_id: str = "",
        scene_id: str = "",
        chapter_id: str = "",
        limit: int = 50,
    ) -> list[CandidateApplyPlan]:
        plans = self._read_apply_plans()
        if candidate_id:
            plans = [item for item in plans if item.candidate_id == candidate_id]
        if scene_id:
            plans = [item for item in plans if item.target_scene_id == scene_id]
        if chapter_id:
            plans = [item for item in plans if item.target_chapter_id == chapter_id]
        result = sorted(plans, key=lambda item: item.updated_at, reverse=True)[: max(1, min(int(limit or 50), 200))]
        self._guard_safe_payload(result)
        return result

    def list_revision_requests(
        self,
        *,
        candidate_id: str = "",
        scene_id: str = "",
        chapter_id: str = "",
        limit: int = 50,
    ) -> list[CandidateRevisionRequest]:
        revisions = self._read_revision_requests()
        if candidate_id:
            revisions = [item for item in revisions if item.source_candidate_id == candidate_id]
        if scene_id:
            revisions = [item for item in revisions if item.target_scene_id == scene_id]
        if chapter_id:
            revisions = [item for item in revisions if item.target_chapter_id == chapter_id]
        result = sorted(revisions, key=lambda item: item.updated_at, reverse=True)[: max(1, min(int(limit or 50), 200))]
        self._guard_safe_payload(result)
        return result

    def debug_summary(self) -> dict[str, Any]:
        actions = self._read_actions()
        plans = self._read_apply_plans()
        revisions = self._read_revision_requests()
        recent_actions = sorted(actions, key=lambda item: item.created_at, reverse=True)[:MAX_LIST_ITEMS]
        recent_plans = sorted(plans, key=lambda item: item.updated_at, reverse=True)[:MAX_LIST_ITEMS]
        recent_revisions = sorted(revisions, key=lambda item: item.updated_at, reverse=True)[:MAX_LIST_ITEMS]
        payload = {
            "available": True,
            "action_count": len(actions),
            "apply_plan_count": len(plans),
            "revision_request_count": len(revisions),
            "recent_action_ids": [item.user_action_id for item in recent_actions],
            "recent_apply_plan_ids": [item.apply_plan_id for item in recent_plans],
            "recent_revision_request_ids": [item.revision_request_id for item in recent_revisions],
            "recent_blocked_reasons": _unique_strings(
                [reason for item in recent_actions for reason in item.blocked_reasons]
                + [reason for item in recent_plans for reason in item.blocking_reasons]
            ),
            "action_counts_by_type": self._counts(actions, "action_type"),
            "action_counts_by_status": self._counts(actions, "action_status"),
            "plan_counts_by_status": self._counts(plans, "plan_status"),
            "storage_files": [
                USER_ACTIONS_FILE_NAME,
                APPLY_PLANS_FILE_NAME,
                REVISION_REQUESTS_FILE_NAME,
            ],
            "recent_actions": [self._action_debug_row(item) for item in recent_actions],
        }
        payload["safety"] = self._safety(payload)
        self._guard_safe_payload(payload)
        return payload

    def _candidate_view(
        self,
        candidate: PreModifyCandidate,
        cached: CachedSceneCandidate | None,
    ) -> PreModifyWorkspaceCandidateView:
        cached_id = cached.cached_candidate_id if cached else ""
        blocking_reasons, blocking_question_ids, warning_question_ids = self._blocking_context(candidate, cached)
        latest_action = self._latest_action(candidate.candidate_id, cached_id)
        latest_plan = self._latest_apply_plan(candidate.candidate_id, cached_id)
        apply_state = self._apply_state(latest_action, latest_plan, blocking_reasons)
        view = PreModifyWorkspaceCandidateView(
            candidate_id=candidate.candidate_id,
            cached_candidate_id=cached_id,
            source_candidate_type=cached.source_candidate_type if cached else "pre_modify_candidate",
            target_scene_id=candidate.target_scene_id,
            target_chapter_id=candidate.target_chapter_id,
            target_scene_index=candidate.target_scene_index,
            source_status=candidate.status,
            cache_status=cached.cache_status if cached else "",
            apply_state=apply_state,
            safe_summary=self._sanitize_payload(candidate.safe_summary if candidate.safe_summary else (cached.safe_summary if cached else {})),
            preview_label=_short_text((cached.preview_label if cached else "") or candidate.adjustment_summary, MAX_SAFE_LABEL_LENGTH),
            user_visible_reason=_short_text(candidate.user_visible_reason or (cached.user_visible_reason if cached else ""), MAX_SAFE_LABEL_LENGTH),
            adjustment_summary=_short_text(candidate.adjustment_summary, MAX_SAFE_LABEL_LENGTH),
            adjustment_plan_id=candidate.adjustment_plan_id,
            impact_reason_id=candidate.impact_reason_id,
            risk_warnings=_unique_strings(candidate.risk_warnings + (cached.risk_warnings if cached else [])),
            snapshot_ids=_unique_strings(candidate.target_snapshot_ids + candidate.affected_snapshot_ids + (cached.based_on_snapshot_ids if cached else [])),
            stale_reason_refs=self._bounded_dicts(cached.stale_reason_refs if cached else []),
            blocking_delayed_question_ids=blocking_question_ids,
            warning_delayed_question_ids=warning_question_ids,
            latest_action_id=latest_action.user_action_id if latest_action else "",
            latest_action_type=latest_action.action_type if latest_action else "",
            can_accept=not blocking_reasons,
            can_reject=True,
            can_revise=True,
            can_defer=True,
            blocked_reasons=blocking_reasons,
        )
        self._guard_safe_payload(view)
        return view

    def _resolve_candidate_and_cache(
        self,
        candidate_id: str,
        cached_candidate_id: str = "",
    ) -> tuple[PreModifyCandidate, CachedSceneCandidate]:
        clean_id = _short_text(candidate_id, MAX_SAFE_LABEL_LENGTH)
        if not clean_id:
            raise StorageError("PRE_MODIFY_WORKSPACE_CANDIDATE_ID_REQUIRED: candidate_id is required.")
        candidate = self.pre_modify_service.get_candidate(clean_id)
        cached = self._resolve_cached_wrapper(candidate, cached_candidate_id)
        return candidate, cached

    def _resolve_cached_wrapper(
        self,
        candidate: PreModifyCandidate,
        cached_candidate_id: str = "",
    ) -> CachedSceneCandidate:
        clean_cached_id = _short_text(cached_candidate_id, MAX_SAFE_LABEL_LENGTH)
        if clean_cached_id:
            cached = self.scene_candidate_cache_service.get_cached_candidate(clean_cached_id)
            if cached.source_candidate_id != candidate.candidate_id:
                raise StorageError("PRE_MODIFY_WORKSPACE_CACHE_MISMATCH: cached candidate does not wrap candidate_id.")
            return cached
        summary = self.scene_candidate_cache_service.summary(
            scene_id=candidate.target_scene_id,
            chapter_id=candidate.target_chapter_id,
            include_stale=True,
            limit=200,
        )
        for cached in summary.candidates:
            if (
                cached.source_candidate_type == "pre_modify_candidate"
                and cached.source_candidate_id == candidate.candidate_id
            ):
                return cached
        return self.scene_candidate_cache_service.register_pre_modify_candidate(candidate.candidate_id)

    def _blocking_context(
        self,
        candidate: PreModifyCandidate,
        cached: CachedSceneCandidate | None,
    ) -> tuple[list[str], list[str], list[str]]:
        blocking: list[str] = []
        if candidate.status not in ACCEPTABLE_SOURCE_STATUSES:
            blocking.append(f"source_status_{candidate.status or 'missing'}")
        if cached is None:
            blocking.append("cache_wrapper_missing")
        elif cached.cache_status not in ACCEPTABLE_CACHE_STATUSES:
            blocking.append(f"cache_status_{cached.cache_status}")
        question_ids = self._related_ready_question_ids(
            candidate_id=candidate.candidate_id,
            cached_candidate_id=cached.cached_candidate_id if cached else "",
            scene_id=candidate.target_scene_id,
            chapter_id=candidate.target_chapter_id,
        )
        if question_ids:
            blocking.append("ready_delayed_questions")
        return _unique_strings(blocking), question_ids, []

    def _related_ready_question_ids(
        self,
        *,
        candidate_id: str,
        cached_candidate_id: str,
        scene_id: str,
        chapter_id: str,
    ) -> list[str]:
        issues = self.future_review_service.list_future_issues(
            scene_id=scene_id,
            chapter_id=chapter_id,
            status="",
            limit=300,
        )
        related_issue_ids = {
            issue.future_issue_id
            for issue in issues
            if self._issue_matches_candidate(issue, candidate_id, cached_candidate_id)
        }
        if not related_issue_ids:
            return []
        questions = self.future_review_service.ready_questions(
            scene_id=scene_id,
            chapter_id=chapter_id,
            reveal_condition="",
            limit=300,
        ).delayed_questions
        return _unique_strings(
            [
                question.delayed_question_id
                for question in questions
                if question.future_issue_id in related_issue_ids
            ]
        )

    def _question_debug_rows(
        self,
        *,
        candidate_id: str,
        cached_candidate_id: str,
        scene_id: str,
        chapter_id: str,
    ) -> list[dict[str, Any]]:
        issue_ids = {
            issue.future_issue_id
            for issue in self.future_review_service.list_future_issues(
                scene_id=scene_id,
                chapter_id=chapter_id,
                status="",
                limit=300,
            )
            if self._issue_matches_candidate(issue, candidate_id, cached_candidate_id)
        }
        if not issue_ids:
            return []
        return [
            self._sanitize_payload(
                {
                    "delayed_question_id": question.delayed_question_id,
                    "future_issue_id": question.future_issue_id,
                    "status": question.status,
                    "reveal_condition": question.reveal_condition,
                    "question_text": question.question_text,
                }
            )
            for question in self.future_review_service.ready_questions(
                scene_id=scene_id,
                chapter_id=chapter_id,
                reveal_condition="",
                limit=300,
            ).delayed_questions
            if question.future_issue_id in issue_ids
        ][:MAX_LIST_ITEMS]

    def _issue_matches_candidate(
        self,
        issue: FutureIssue,
        candidate_id: str,
        cached_candidate_id: str,
    ) -> bool:
        return (
            candidate_id in issue.related_candidate_ids
            or bool(cached_candidate_id and cached_candidate_id in issue.related_cached_candidate_ids)
            or issue.source_id == candidate_id
            or bool(cached_candidate_id and issue.source_id == cached_candidate_id)
        )

    def _apply_plan_items(
        self,
        candidate: PreModifyCandidate,
        cached: CachedSceneCandidate,
        *,
        blocking_question_ids: list[str],
        blocking_reasons: list[str],
    ) -> list[CandidateApplyPlanItem]:
        items: list[CandidateApplyPlanItem] = []
        source_refs = self._source_refs(candidate, cached)
        items.append(
            CandidateApplyPlanItem(
                item_id="apply_item_001",
                item_type="preserve_source_evidence",
                target_type="pre_modify_candidate",
                target_id=candidate.candidate_id,
                safe_summary="Preserve M3 candidate and M4 cache evidence.",
                source_refs=source_refs,
                requires_user_confirmation=False,
                status="completed",
            )
        )
        if candidate.adjustment_plan_id:
            items.append(
                CandidateApplyPlanItem(
                    item_id=f"apply_item_{len(items) + 1:03d}",
                    item_type="review_adjustment_plan",
                    target_type="pre_modify_adjustment_plan",
                    target_id=candidate.adjustment_plan_id,
                    safe_summary="Review the M3 adjustment plan before formal handling.",
                    source_refs=source_refs,
                )
            )
        if candidate.impact_reason_id:
            items.append(
                CandidateApplyPlanItem(
                    item_id=f"apply_item_{len(items) + 1:03d}",
                    item_type="review_impact_reason",
                    target_type="pre_modify_impact_reason",
                    target_id=candidate.impact_reason_id,
                    safe_summary="Review the M3 impact reason before formal handling.",
                    source_refs=source_refs,
                )
            )
        for question_id in blocking_question_ids:
            items.append(
                CandidateApplyPlanItem(
                    item_id=f"apply_item_{len(items) + 1:03d}",
                    item_type="answer_delayed_question",
                    target_type="delayed_question",
                    target_id=question_id,
                    safe_summary="Answer or resolve the delayed question before accept.",
                    source_refs=source_refs,
                    required_before_accept=True,
                    status="blocked",
                )
            )
        items.append(
            CandidateApplyPlanItem(
                item_id=f"apply_item_{len(items) + 1:03d}",
                item_type="prepare_formal_flow_handoff",
                target_type="scene",
                target_id=candidate.target_scene_id,
                safe_summary="Hand off accepted candidate to guarded formal scene flow.",
                source_refs=source_refs,
                required_before_accept=bool(blocking_reasons),
                status="blocked" if blocking_reasons else "planned",
            )
        )
        return items

    def _source_refs(
        self,
        candidate: PreModifyCandidate,
        cached: CachedSceneCandidate,
    ) -> list[dict[str, Any]]:
        refs = [
            {
                "source_type": "pre_modify_candidate",
                "source_id": candidate.candidate_id,
                "status": candidate.status,
            },
            {
                "source_type": "cached_scene_candidate",
                "source_id": cached.cached_candidate_id,
                "status": cached.cache_status,
            },
        ]
        if candidate.adjustment_plan_id:
            refs.append({"source_type": "pre_modify_adjustment_plan", "source_id": candidate.adjustment_plan_id})
        if candidate.impact_reason_id:
            refs.append({"source_type": "pre_modify_impact_reason", "source_id": candidate.impact_reason_id})
        for snapshot_id in _unique_strings(candidate.target_snapshot_ids + candidate.affected_snapshot_ids + cached.based_on_snapshot_ids):
            refs.append({"source_type": "scene_snapshot", "source_id": snapshot_id})
        return self._bounded_dicts(refs)

    def _write_action_with_decision(
        self,
        *,
        action_type: str,
        action_status: str,
        candidate: PreModifyCandidate,
        cached: CachedSceneCandidate,
        safe_user_note: str = "",
        safe_action_summary: str = "",
        blocked_reasons: list[str] | None = None,
        apply_plan_id: str = "",
        revision_request_id: str = "",
        future_issue_id: str = "",
        delayed_question_id: str = "",
        future_todo_id: str = "",
        preset_action_id: str = "",
    ) -> PreModifyUserAction:
        clean_note = _short_text(safe_user_note, MAX_SAFE_TEXT_LENGTH)
        clean_summary = _short_text(safe_action_summary, MAX_SAFE_TEXT_LENGTH)
        self._guard_safe_payload({"safe_user_note": clean_note, "safe_action_summary": clean_summary})
        actions = self._read_actions()
        action_id = preset_action_id or f"pre_modify_user_action_{len(actions) + 1:03d}"
        decision = self._write_decision(
            decision_type=ACTION_DECISION_TYPES[action_type],
            target_id=candidate.candidate_id,
            user_input=clean_note or clean_summary or action_type,
        )
        action = PreModifyUserAction(
            user_action_id=action_id,
            action_type=action_type,
            action_status=action_status,
            candidate_id=candidate.candidate_id,
            cached_candidate_id=cached.cached_candidate_id,
            apply_plan_id=apply_plan_id,
            revision_request_id=revision_request_id,
            future_issue_id=future_issue_id,
            delayed_question_id=delayed_question_id,
            future_todo_id=future_todo_id,
            decision_id=decision.decision_id,
            target_scene_id=candidate.target_scene_id,
            target_chapter_id=candidate.target_chapter_id,
            target_scene_index=candidate.target_scene_index,
            safe_user_note=clean_note,
            safe_action_summary=clean_summary,
            blocked_reasons=_unique_strings(blocked_reasons or []),
            created_at=now_iso(),
        )
        self._write_actions(actions + [action])
        return action

    def _write_decision(self, *, decision_type: str, target_id: str, user_input: str) -> Decision:
        records = self._read_decisions()
        decision = Decision(
            decision_id=f"decision_m7_pre_modify_{len(records) + 1:03d}",
            decision_type=decision_type,
            target_type="pre_modify_candidate",
            target_id=_short_text(target_id, MAX_SAFE_LABEL_LENGTH),
            user_input=_short_text(user_input, MAX_SAFE_TEXT_LENGTH),
            created_at=now_iso(),
        )
        self._guard_safe_payload(decision)
        records.append(model_to_dict(decision))
        self.store.write(self.decisions_file, records)
        return decision

    def _mark_apply_plan(
        self,
        apply_plan_id: str,
        plan_status: str,
        *,
        created_by_action_id: str = "",
    ) -> CandidateApplyPlan:
        plans = self._read_apply_plans()
        timestamp = now_iso()
        updated: list[CandidateApplyPlan] = []
        result: CandidateApplyPlan | None = None
        for plan in plans:
            if plan.apply_plan_id != apply_plan_id:
                updated.append(plan)
                continue
            result = CandidateApplyPlan(
                **{
                    **model_to_dict(plan),
                    "plan_status": plan_status,
                    "created_by_action_id": created_by_action_id or plan.created_by_action_id,
                    "updated_at": timestamp,
                }
            )
            updated.append(result)
        if result is None:
            raise StorageError("PRE_MODIFY_WORKSPACE_APPLY_PLAN_NOT_FOUND: apply plan does not exist.")
        self._write_apply_plans(updated)
        return result

    def _latest_action(self, candidate_id: str, cached_candidate_id: str = "") -> PreModifyUserAction | None:
        actions = [
            action
            for action in self._read_actions()
            if action.candidate_id == candidate_id
            and (not cached_candidate_id or action.cached_candidate_id == cached_candidate_id)
        ]
        return sorted(actions, key=lambda item: item.created_at, reverse=True)[0] if actions else None

    def _latest_apply_plan(self, candidate_id: str, cached_candidate_id: str = "") -> CandidateApplyPlan | None:
        plans = [
            plan
            for plan in self._read_apply_plans()
            if plan.candidate_id == candidate_id
            and (not cached_candidate_id or plan.cached_candidate_id == cached_candidate_id)
        ]
        return sorted(plans, key=lambda item: item.updated_at, reverse=True)[0] if plans else None

    def _apply_state(
        self,
        latest_action: PreModifyUserAction | None,
        latest_plan: CandidateApplyPlan | None,
        blocking_reasons: list[str],
    ) -> str:
        if latest_action:
            if latest_action.action_type == "accept" and latest_action.action_status == "completed":
                return "accepted_for_formal_flow"
            if latest_action.action_type == "reject":
                return "rejected"
            if latest_action.action_type == "revise":
                return "revision_requested"
            if latest_action.action_type == "defer":
                return "deferred"
        if blocking_reasons:
            return "blocked"
        if latest_plan and latest_plan.plan_status in {"ready", "accepted", "deferred", "rejected"}:
            return "plan_ready"
        return "not_started"

    def _result(
        self,
        *,
        success: bool = True,
        action: PreModifyUserAction | None = None,
        apply_plan: CandidateApplyPlan | None = None,
        revision_request: CandidateRevisionRequest | None = None,
        created_future_issue_id: str = "",
        created_delayed_question_id: str = "",
        created_future_todo_id: str = "",
        blocked_reasons: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> CandidateApplyResult:
        result = CandidateApplyResult(
            success=success,
            action=action,
            apply_plan=apply_plan,
            revision_request=revision_request,
            created_future_issue_id=created_future_issue_id,
            created_delayed_question_id=created_delayed_question_id,
            created_future_todo_id=created_future_todo_id,
            blocked_reasons=_unique_strings(blocked_reasons or []),
            warnings=_unique_strings(warnings or []),
        )
        result.safety = self._safety(model_to_dict(result))
        self._guard_safe_payload(result)
        return result

    def _accept_request(self, request: CandidateAcceptRequest | dict[str, Any] | None) -> CandidateAcceptRequest:
        if request is None:
            return CandidateAcceptRequest()
        return request if isinstance(request, CandidateAcceptRequest) else CandidateAcceptRequest(**request)

    def _reject_request(self, request: CandidateRejectRequest | dict[str, Any] | None) -> CandidateRejectRequest:
        if request is None:
            return CandidateRejectRequest()
        return request if isinstance(request, CandidateRejectRequest) else CandidateRejectRequest(**request)

    def _defer_request(self, request: CandidateDeferRequest | dict[str, Any] | None) -> CandidateDeferRequest:
        if request is None:
            return CandidateDeferRequest()
        return request if isinstance(request, CandidateDeferRequest) else CandidateDeferRequest(**request)

    def _read_actions(self) -> list[PreModifyUserAction]:
        if not self.store.exists(self.actions_file):
            return []
        result: list[PreModifyUserAction] = []
        try:
            for item in self.store.read_list(self.actions_file):
                if isinstance(item, dict):
                    result.append(PreModifyUserAction(**item))
        except ValidationError as exc:
            raise StorageError("PRE_MODIFY_WORKSPACE_SCHEMA_INVALID: user action JSON schema is invalid.") from exc
        return result

    def _read_apply_plans(self) -> list[CandidateApplyPlan]:
        if not self.store.exists(self.apply_plans_file):
            return []
        result: list[CandidateApplyPlan] = []
        try:
            for item in self.store.read_list(self.apply_plans_file):
                if isinstance(item, dict):
                    result.append(CandidateApplyPlan(**item))
        except ValidationError as exc:
            raise StorageError("PRE_MODIFY_WORKSPACE_SCHEMA_INVALID: apply plan JSON schema is invalid.") from exc
        return result

    def _read_revision_requests(self) -> list[CandidateRevisionRequest]:
        if not self.store.exists(self.revision_requests_file):
            return []
        result: list[CandidateRevisionRequest] = []
        try:
            for item in self.store.read_list(self.revision_requests_file):
                if isinstance(item, dict):
                    result.append(CandidateRevisionRequest(**item))
        except ValidationError as exc:
            raise StorageError("PRE_MODIFY_WORKSPACE_SCHEMA_INVALID: revision request JSON schema is invalid.") from exc
        return result

    def _read_decisions(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.decisions_file):
            return []
        return [dict(item) for item in self.store.read_list(self.decisions_file) if isinstance(item, dict)]

    def _write_actions(self, actions: list[PreModifyUserAction]) -> None:
        payload = [model_to_dict(item) for item in actions[-MAX_STORED_RECORDS:]]
        self._guard_safe_payload(payload)
        self.store.write(self.actions_file, payload)

    def _write_apply_plans(self, plans: list[CandidateApplyPlan]) -> None:
        payload = [model_to_dict(item) for item in plans[-MAX_STORED_RECORDS:]]
        self._guard_safe_payload(payload)
        self.store.write(self.apply_plans_file, payload)

    def _write_revision_requests(self, revisions: list[CandidateRevisionRequest]) -> None:
        payload = [model_to_dict(item) for item in revisions[-MAX_STORED_RECORDS:]]
        self._guard_safe_payload(payload)
        self.store.write(self.revision_requests_file, payload)

    def _action_debug_row(self, action: PreModifyUserAction) -> dict[str, Any]:
        return self._sanitize_payload(
            {
                "user_action_id": action.user_action_id,
                "action_type": action.action_type,
                "action_status": action.action_status,
                "candidate_id": action.candidate_id,
                "cached_candidate_id": action.cached_candidate_id,
                "apply_plan_id": action.apply_plan_id,
                "revision_request_id": action.revision_request_id,
                "future_issue_id": action.future_issue_id,
                "target_scene_id": action.target_scene_id,
                "blocked_reasons": action.blocked_reasons,
                "summary": action.safe_action_summary,
            }
        )

    def _counts(self, items: list[Any], attr: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in items:
            key = str(getattr(item, attr, "") or "").strip()
            if key:
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

    def _bounded_dicts(self, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in values[:MAX_LIST_ITEMS]:
            if isinstance(item, dict):
                result.append(self._sanitize_payload(item))
        return result

    def _guard_safe_payload(self, value: Any) -> None:
        issues = self._scan_for_unsafe_payload(value)
        if issues:
            raise StorageError("PRE_MODIFY_WORKSPACE_UNSAFE_PAYLOAD_BLOCKED: " + "; ".join(issues[:5]))

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
