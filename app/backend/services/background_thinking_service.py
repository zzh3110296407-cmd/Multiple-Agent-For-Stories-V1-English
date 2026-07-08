from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.background_thinking import (
    BACKGROUND_THINKING_BUDGET_PROFILES,
    BACKGROUND_THINKING_EXECUTION_STRATEGIES,
    BACKGROUND_THINKING_TASK_TYPES,
    BackgroundThinkingTask,
    BackgroundThinkingTaskCreateRequest,
    BackgroundThinkingTaskResponse,
    ThinkingCandidate,
    ThinkingTaskQueueSummaryResponse,
)
from app.backend.models.model_gateway import ModelGatewayOptions
from app.backend.models.background_budget import TaskBudgetDecision
from app.backend.models.scene_snapshot import SceneVersionSnapshot
from app.backend.services.background_budget_service import BackgroundBudgetService
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.runtime_error_sanitizer import RuntimeErrorSanitizer
from app.backend.services.scene_version_snapshot_service import (
    SceneVersionSnapshotService,
)
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
MAX_SAFE_TEXT_LENGTH = 700
MAX_SAFE_LABEL_LENGTH = 180
MAX_LIST_ITEMS = 10
TASKS_FILE_NAME = "background_thinking_tasks.json"
CANDIDATES_FILE_NAME = "thinking_candidates.json"
FAILURE_ERROR_CODES = {
    "BACKGROUND_THINKING_NO_ACTIVE_SNAPSHOT",
    "BACKGROUND_THINKING_SNAPSHOT_NOT_FOUND",
    "BACKGROUND_THINKING_STALE_SNAPSHOT",
    "BACKGROUND_THINKING_VALIDATION_ERROR",
}
UNSAFE_KEY_NAMES = {
    "prompt",
    "system_prompt",
    "developer_prompt",
    "user_prompt",
    "raw_prompt",
    "raw_response",
    "hidden_reasoning",
    "chain_of_thought",
    "cot",
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "api_key",
    "authorization",
    "secret_key",
    "secret_token",
    "bearer_token",
}
UNSAFE_VALUE_MARKERS = {
    "raw_prompt",
    "raw response",
    "raw_response",
    "hidden_reasoning",
    "hidden reasoning",
    "chain_of_thought",
    "chain-of-thought",
    "chain of thought",
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "api_key",
    "authorization",
    "bearer ",
}
MODEL_SAFE_SUMMARY_KEYS = {
    "next_scene_focus",
    "continuity_focus",
    "character_focus",
    "information_release_strategy",
    "source_scene_id",
    "target_scene_id",
    "target_chapter_id",
    "target_scene_index",
    "location_hint",
}
MODEL_REQUIRED_SUMMARY_KEYS = {
    "next_scene_focus",
    "continuity_focus",
    "character_focus",
    "information_release_strategy",
}
MODEL_STORY_INFORMATION_KEYS = {
    "item_type",
    "label",
    "source_ref",
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


class BackgroundThinkingService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        snapshot_service: SceneVersionSnapshotService | None = None,
        model_gateway: ModelGatewayService | None = None,
        background_budget_service: BackgroundBudgetService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.tasks_file = self.data_dir / TASKS_FILE_NAME
        self.candidates_file = self.data_dir / CANDIDATES_FILE_NAME
        self.snapshot_service = snapshot_service or SceneVersionSnapshotService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.runtime_error_sanitizer = RuntimeErrorSanitizer()
        self.background_budget_service = background_budget_service or BackgroundBudgetService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self._latest_model_call_id = ""

    def create_task(
        self,
        request: BackgroundThinkingTaskCreateRequest | dict[str, Any],
    ) -> BackgroundThinkingTaskResponse:
        normalized = (
            request
            if isinstance(request, BackgroundThinkingTaskCreateRequest)
            else BackgroundThinkingTaskCreateRequest(**request)
        )
        self._validate_request(normalized)
        timestamp = now_iso()
        task = BackgroundThinkingTask(
            task_id=self._next_task_id(),
            project_id=LOCAL_PROJECT_ID,
            task_type=normalized.task_type,
            execution_mode="sync_simulated",
            execution_strategy=normalized.execution_strategy,
            status="queued",
            source_scene_id=_short_text(normalized.source_scene_id, MAX_SAFE_LABEL_LENGTH),
            target_scene_id=_short_text(normalized.target_scene_id, MAX_SAFE_LABEL_LENGTH),
            target_chapter_id=_short_text(normalized.target_chapter_id, MAX_SAFE_LABEL_LENGTH),
            target_scene_index=normalized.target_scene_index,
            input_snapshot_ids=_unique_strings(normalized.input_snapshot_ids),
            candidate_ids=[],
            safe_context_summary={},
            safe_error={},
            budget_profile=normalized.budget_profile,
            created_by="user",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._append_task(task)
        if not normalized.execute_now:
            return BackgroundThinkingTaskResponse(task=task)
        return self.execute_task(task.task_id)

    def execute_task(
        self,
        task_id: str,
        execution_strategy: str | None = None,
    ) -> BackgroundThinkingTaskResponse:
        task = self.get_task(task_id)
        if task.status == "cancelled":
            return BackgroundThinkingTaskResponse(success=False, task=task)
        clean_strategy = str(execution_strategy or task.execution_strategy).strip()
        if clean_strategy:
            self._validate_execution_strategy(clean_strategy)
        timestamp = now_iso()
        task = self._copy_task(
            task,
            status="running",
            execution_strategy=clean_strategy or task.execution_strategy,
            started_at=task.started_at or timestamp,
            updated_at=timestamp,
        )
        self._upsert_task(task)

        budget_decision: TaskBudgetDecision | None = None
        model_call_ids: list[str] = []
        self._latest_model_call_id = ""
        try:
            snapshots = self._resolve_snapshots(task)
            safe_context = self._safe_context_summary(task, snapshots)
            budget_response = self.background_budget_service.evaluate_task_execution(
                task_type="background_thinking",
                task_id=task.task_id,
                requested_profile_id=task.budget_profile,
                requested_execution_strategy=task.execution_strategy,
                snapshot_ids=[snapshot.snapshot_id for snapshot in snapshots],
                source_object_type="background_thinking_task",
                source_object_id=task.task_id,
            )
            budget_decision = budget_response.decision
            selected_strategy = budget_decision.selected_execution_strategy
            task = self._copy_task(
                task,
                execution_strategy=(
                    selected_strategy
                    if selected_strategy in BACKGROUND_THINKING_EXECUTION_STRATEGIES
                    else task.execution_strategy
                ),
                safe_context_summary={
                    **safe_context,
                    "latest_budget_status": budget_decision.selected_execution_strategy,
                },
                updated_at=now_iso(),
            )
            self._upsert_task(task)
            if not budget_decision.allowed or selected_strategy == "blocked":
                safe_error = self._safe_error(
                    "BACKGROUND_THINKING_BUDGET_BLOCKED",
                    budget_decision.decision_reason or "Background thinking was blocked by the budget guard.",
                    stage="budget_guard",
                    retryable=False,
                    suggested_action="Select an enabled background budget profile.",
                )
                task = self._copy_task(
                    task,
                    status="failed",
                    input_snapshot_ids=[snapshot.snapshot_id for snapshot in snapshots],
                    safe_context_summary=safe_context,
                    safe_error=safe_error,
                    completed_at=now_iso(),
                    updated_at=now_iso(),
                )
                self._upsert_task(task)
                self.background_budget_service.record_task_usage(
                    task_type="background_thinking",
                    task_id=task.task_id,
                    source_object_type="background_thinking_task",
                    source_object_id=task.task_id,
                    decision=budget_decision,
                    blocked=True,
                    status="blocked",
                    safe_error=safe_error,
                )
                return BackgroundThinkingTaskResponse(success=False, task=task)

            if selected_strategy == "model_gateway":
                candidate_payload, call_id = self._model_gateway_candidate_payload(
                    task,
                    snapshots,
                    safe_context,
                    budget_decision,
                )
                if call_id:
                    model_call_ids.append(call_id)
            else:
                candidate_payload = self._deterministic_candidate_payload(task, snapshots, safe_context)
            candidate = self._build_candidate(task, snapshots, candidate_payload)
            candidates = self._read_candidates()
            candidates.append(candidate)
            task = self._copy_task(
                task,
                status="completed",
                input_snapshot_ids=[snapshot.snapshot_id for snapshot in snapshots],
                candidate_ids=[*task.candidate_ids, candidate.candidate_id],
                safe_context_summary=safe_context,
                safe_error={},
                completed_at=now_iso(),
                updated_at=now_iso(),
            )
            self._guard_safe_payload(
                {
                    "task": model_to_dict(task),
                    "candidate": model_to_dict(candidate),
                }
            )
            self._write_candidates(candidates)
            self._upsert_task(task)
            self.background_budget_service.record_task_usage(
                task_type="background_thinking",
                task_id=task.task_id,
                source_object_type="background_thinking_task",
                source_object_id=task.task_id,
                decision=budget_decision,
                model_call_ids=model_call_ids,
                fallback_used=(
                    budget_decision.selected_execution_strategy
                    != budget_decision.requested_execution_strategy
                )
                if budget_decision
                else False,
                deterministic_used=task.execution_strategy != "model_gateway",
                status="completed",
            )
            return BackgroundThinkingTaskResponse(task=task, candidate=candidate)
        except Exception as exc:
            task = self._fail_task(task, exc)
            call_id = str(getattr(exc, "call_id", "") or self._latest_model_call_id or "")
            if call_id and call_id not in model_call_ids:
                model_call_ids.append(call_id)
            if budget_decision is not None:
                self.background_budget_service.record_task_usage(
                    task_type="background_thinking",
                    task_id=task.task_id,
                    source_object_type="background_thinking_task",
                    source_object_id=task.task_id,
                    decision=budget_decision,
                    model_call_ids=model_call_ids,
                    fallback_used=(
                        budget_decision.selected_execution_strategy
                        != budget_decision.requested_execution_strategy
                    ),
                    deterministic_used=budget_decision.selected_execution_strategy != "model_gateway",
                    status="failed",
                    safe_error=task.safe_error,
                )
            return BackgroundThinkingTaskResponse(success=False, task=task)

    def get_task(self, task_id: str) -> BackgroundThinkingTask:
        clean_id = str(task_id or "").strip()
        for task in self._read_tasks():
            if task.task_id == clean_id:
                return task
        raise StorageError("BACKGROUND_THINKING_TASK_NOT_FOUND: task does not exist.")

    def list_tasks(
        self,
        status: str | None = None,
        source_scene_id: str | None = None,
        limit: int = 50,
    ) -> list[BackgroundThinkingTask]:
        clean_status = str(status or "").strip()
        clean_scene_id = str(source_scene_id or "").strip()
        tasks = self._read_tasks()
        if clean_status:
            tasks = [task for task in tasks if task.status == clean_status]
        if clean_scene_id:
            tasks = [task for task in tasks if task.source_scene_id == clean_scene_id]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)[: max(1, limit)]

    def get_candidate(self, candidate_id: str) -> ThinkingCandidate:
        clean_id = str(candidate_id or "").strip()
        for candidate in self._read_candidates():
            if candidate.candidate_id == clean_id:
                return candidate
        raise StorageError("THINKING_CANDIDATE_NOT_FOUND: candidate does not exist.")

    def list_candidates(
        self,
        status: str | None = None,
        source_scene_id: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[ThinkingCandidate]:
        clean_status = str(status or "").strip()
        clean_scene_id = str(source_scene_id or "").strip()
        clean_task_id = str(task_id or "").strip()
        candidates = self._read_candidates()
        if clean_status:
            candidates = [
                candidate for candidate in candidates if candidate.status == clean_status
            ]
        if clean_scene_id:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.source_scene_id == clean_scene_id
            ]
        if clean_task_id:
            candidates = [
                candidate for candidate in candidates if candidate.task_id == clean_task_id
            ]
        return sorted(candidates, key=lambda item: item.created_at, reverse=True)[
            : max(1, limit)
        ]

    def queue_summary(
        self,
        source_scene_id: str | None = None,
    ) -> ThinkingTaskQueueSummaryResponse:
        clean_scene_id = str(source_scene_id or "").strip()
        tasks = self.list_tasks(source_scene_id=clean_scene_id or None, limit=500)
        candidates = self.list_candidates(source_scene_id=clean_scene_id or None, limit=500)
        latest_errors = [
            {
                "task_id": task.task_id,
                **self._safe_error_summary(task.safe_error),
            }
            for task in tasks
            if task.safe_error
        ][:5]
        payload = {
            "task_count": len(tasks),
            "candidate_count": len(candidates),
            "recent_task_ids": [task.task_id for task in tasks[:8]],
            "recent_candidate_ids": [candidate.candidate_id for candidate in candidates[:8]],
            "latest_safe_errors": latest_errors,
        }
        safety_issues = self._scan_for_unsafe_payload(payload)
        return ThinkingTaskQueueSummaryResponse(
            success=True,
            project_id=LOCAL_PROJECT_ID,
            source_scene_id=clean_scene_id,
            task_count=len(tasks),
            queued_count=sum(1 for item in tasks if item.status == "queued"),
            running_count=sum(1 for item in tasks if item.status == "running"),
            completed_count=sum(1 for item in tasks if item.status == "completed"),
            failed_count=sum(1 for item in tasks if item.status == "failed"),
            candidate_count=len(candidates),
            ready_candidate_count=sum(1 for item in candidates if item.status == "ready"),
            stale_candidate_count=sum(1 for item in candidates if item.status == "stale"),
            recent_task_ids=payload["recent_task_ids"],
            recent_candidate_ids=payload["recent_candidate_ids"],
            latest_safe_errors=latest_errors,
            storage_files=[self.tasks_file.name, self.candidates_file.name],
            safety={
                "safe": not safety_issues,
                "issues": safety_issues,
            },
        )

    def debug_summary(self) -> dict[str, Any]:
        tasks = self.list_tasks(limit=500)
        candidates = self.list_candidates(limit=500)
        summary = self.queue_summary()
        payload = {
            "available": True,
            "task_count": summary.task_count,
            "queued_count": summary.queued_count,
            "running_count": summary.running_count,
            "completed_count": summary.completed_count,
            "failed_count": summary.failed_count,
            "candidate_count": summary.candidate_count,
            "ready_candidate_count": summary.ready_candidate_count,
            "stale_candidate_count": summary.stale_candidate_count,
            "recent_task_ids": summary.recent_task_ids,
            "recent_candidate_ids": summary.recent_candidate_ids,
            "storage_files": summary.storage_files,
            "latest_safe_errors": summary.latest_safe_errors,
            "recent_tasks": [
                {
                    "task_id": task.task_id,
                    "status": task.status,
                    "task_type": task.task_type,
                    "budget_profile": task.budget_profile,
                    **self._latest_budget_debug(task.task_id),
                    "source_scene_id": task.source_scene_id,
                    "target_scene_id": task.target_scene_id,
                    "target_scene_index": task.target_scene_index,
                    "input_snapshot_ids": task.input_snapshot_ids,
                    "candidate_ids": task.candidate_ids,
                    "execution_strategy": task.execution_strategy,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                    "safe_error": self._safe_error_summary(task.safe_error),
                }
                for task in tasks[:8]
            ],
            "recent_candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "task_id": candidate.task_id,
                    "status": candidate.status,
                    "budget_profile": candidate.budget_profile,
                    "source_scene_id": candidate.source_scene_id,
                    "target_scene_id": candidate.target_scene_id,
                    "target_scene_index": candidate.target_scene_index,
                    "based_on_snapshot_ids": candidate.based_on_snapshot_ids,
                    "execution_strategy": candidate.execution_strategy,
                    "risk_warnings": candidate.risk_warnings[:5],
                    "open_questions": candidate.open_questions[:5],
                    "safe_summary": candidate.safe_summary,
                }
                for candidate in candidates[:8]
            ],
        }
        safety_issues = self._scan_for_unsafe_payload(payload)
        payload["safety"] = {
            "safe": not safety_issues,
            "issues": safety_issues,
        }
        return payload

    def _latest_budget_debug(self, task_id: str) -> dict[str, Any]:
        try:
            usage = self.background_budget_service.list_usage(
                task_type="background_thinking",
                task_id=task_id,
                limit=1,
            )
        except Exception:
            return {
                "latest_budget_usage_record_id": "",
                "latest_budget_status": "unavailable",
            }
        if not usage:
            return {
                "latest_budget_usage_record_id": "",
                "latest_budget_status": "not_recorded",
            }
        record = usage[0]
        return {
            "latest_budget_usage_record_id": record.usage_record_id,
            "latest_budget_status": record.status,
            "latest_budget_execution_strategy": record.selected_execution_strategy,
        }

    def _validate_request(self, request: BackgroundThinkingTaskCreateRequest) -> None:
        if not str(request.source_scene_id or "").strip():
            raise StorageError("BACKGROUND_THINKING_VALIDATION_ERROR: source_scene_id is required.")
        if request.task_type not in BACKGROUND_THINKING_TASK_TYPES:
            raise StorageError("BACKGROUND_THINKING_VALIDATION_ERROR: task_type is not supported.")
        self._validate_execution_strategy(request.execution_strategy)
        if request.budget_profile not in BACKGROUND_THINKING_BUDGET_PROFILES:
            raise StorageError("BACKGROUND_THINKING_VALIDATION_ERROR: budget_profile is not supported.")

    def _validate_execution_strategy(self, strategy: str) -> None:
        if strategy not in BACKGROUND_THINKING_EXECUTION_STRATEGIES:
            raise StorageError(
                "BACKGROUND_THINKING_VALIDATION_ERROR: execution_strategy is not supported."
            )

    def _resolve_snapshots(
        self,
        task: BackgroundThinkingTask,
    ) -> list[SceneVersionSnapshot]:
        snapshot_ids = _unique_strings(task.input_snapshot_ids)
        if not snapshot_ids:
            snapshots = self.snapshot_service.list_snapshots(
                scene_id=task.source_scene_id,
                status="active",
            )
            if not snapshots:
                raise StorageError(
                    "BACKGROUND_THINKING_NO_ACTIVE_SNAPSHOT: source_scene_id has no active snapshot."
                )
            snapshot_ids = [snapshots[0].snapshot_id]

        snapshots = []
        for snapshot_id in snapshot_ids:
            try:
                snapshot = self.snapshot_service.get_snapshot(snapshot_id)
            except StorageError as exc:
                raise StorageError(
                    "BACKGROUND_THINKING_SNAPSHOT_NOT_FOUND: input snapshot does not exist."
                ) from exc
            if snapshot.status != "active":
                raise StorageError(
                    "BACKGROUND_THINKING_STALE_SNAPSHOT: input snapshot is not active."
                )
            snapshots.append(snapshot)
        return snapshots

    def _safe_context_summary(
        self,
        task: BackgroundThinkingTask,
        snapshots: list[SceneVersionSnapshot],
    ) -> dict[str, Any]:
        source_ref_counts: dict[str, int] = {}
        snapshot_summaries = []
        for snapshot in snapshots:
            for ref_type, count in snapshot.source_ref_counts.items():
                source_ref_counts[ref_type] = source_ref_counts.get(ref_type, 0) + int(count)
            snapshot_summaries.append(
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "snapshot_type": snapshot.snapshot_type,
                    "target_scene_id": snapshot.target_scene_id,
                    "chapter_id": snapshot.chapter_id,
                    "status": snapshot.status,
                    "snapshot_hash": snapshot.snapshot_hash,
                    "goal_summary": _short_text(
                        snapshot.safe_summary.get("goal_summary"),
                        260,
                    ),
                    "synopsis_summary": _short_text(
                        snapshot.safe_summary.get("synopsis_summary"),
                        320,
                    ),
                    "location": _short_text(
                        snapshot.safe_summary.get("location"),
                        MAX_SAFE_LABEL_LENGTH,
                    ),
                    "ref_type_counts": dict(snapshot.source_ref_counts),
                }
            )
        context = {
            "source_scene_id": task.source_scene_id,
            "target_scene_id": task.target_scene_id,
            "target_chapter_id": task.target_chapter_id,
            "target_scene_index": task.target_scene_index,
            "snapshot_ids": [snapshot.snapshot_id for snapshot in snapshots],
            "snapshot_hashes": {
                snapshot.snapshot_id: snapshot.snapshot_hash for snapshot in snapshots
            },
            "snapshot_summaries": snapshot_summaries[:MAX_LIST_ITEMS],
            "source_ref_counts": dict(sorted(source_ref_counts.items())),
            "budget_profile": task.budget_profile,
        }
        return self._sanitize_payload(context)

    def _deterministic_candidate_payload(
        self,
        task: BackgroundThinkingTask,
        snapshots: list[SceneVersionSnapshot],
        safe_context: dict[str, Any],
    ) -> dict[str, Any]:
        primary = snapshots[0]
        primary_summary = primary.safe_summary or {}
        ref_counts = dict(primary.source_ref_counts)
        goal = _short_text(primary_summary.get("goal_summary"), 220)
        synopsis = _short_text(primary_summary.get("synopsis_summary"), 260)
        location = _short_text(primary_summary.get("location"), 120)
        focus = goal or synopsis or f"Continue from {primary.target_scene_id}."
        continuity_bits = []
        if ref_counts.get("memory_record"):
            continuity_bits.append(
                f"Carry forward {ref_counts['memory_record']} memory refs from the source snapshot."
            )
        if ref_counts.get("event"):
            continuity_bits.append(
                f"Preserve {ref_counts['event']} confirmed event refs."
            )
        if ref_counts.get("state_change"):
            continuity_bits.append(
                f"Check {ref_counts['state_change']} state-change refs before drafting."
            )
        if not continuity_bits:
            continuity_bits.append("Use the source scene snapshot as the only continuity anchor.")
        risk_warnings = []
        if not task.target_scene_id and task.target_scene_index is None:
            risk_warnings.append("Target scene is not specified; keep output as planning-only guidance.")
        if len(primary.source_refs) > 8:
            risk_warnings.append("Snapshot has many dependency refs; review continuity before scene generation.")
        safe_summary = {
            "next_scene_focus": focus,
            "continuity_focus": continuity_bits[0],
            "character_focus": "Use only character ids and relationship refs present in the snapshot.",
            "information_release_strategy": (
                "Keep this as background planning. Do not introduce new canon facts until a later confirmed scene."
            ),
            "source_scene_id": task.source_scene_id,
            "target_scene_id": task.target_scene_id,
            "target_scene_index": task.target_scene_index,
            "location_hint": location,
        }
        story_information_preview = [
            {
                "item_type": "snapshot_anchor",
                "label": f"Source snapshot {primary.snapshot_id}",
                "source_ref": primary.snapshot_id,
            },
            {
                "item_type": "continuity_counts",
                "label": ", ".join(f"{key}:{value}" for key, value in sorted(ref_counts.items())[:6])
                or "no refs",
                "source_ref": primary.snapshot_id,
            },
        ]
        if synopsis:
            story_information_preview.append(
                {
                    "item_type": "safe_synopsis_hint",
                    "label": synopsis,
                    "source_ref": primary.snapshot_id,
                }
            )
        return {
            "safe_summary": safe_summary,
            "risk_warnings": risk_warnings,
            "story_information_preview": story_information_preview,
            "continuity_considerations": continuity_bits[:MAX_LIST_ITEMS],
            "open_questions": [
                "Which confirmed memory should be foregrounded next?",
                "Does the next scene need a fresh SceneMemoryPack before drafting?",
            ],
            "safe_context_summary": safe_context,
        }

    def _model_gateway_candidate_payload(
        self,
        task: BackgroundThinkingTask,
        snapshots: list[SceneVersionSnapshot],
        safe_context: dict[str, Any],
        budget_decision: TaskBudgetDecision,
    ) -> tuple[dict[str, Any], str]:
        prompt = (
            "Return JSON only. Create a safe background thinking candidate from this "
            "safe context. Do not write prose. Do not create canon facts. Required keys: "
            "safe_summary, risk_warnings, story_information_preview, "
            "continuity_considerations, open_questions. Safe context: "
            f"{safe_context}"
        )
        result = self.model_gateway.generate_json(
            [{"role": "user", "content": prompt}],
            options=ModelGatewayOptions(
                temperature=budget_decision.temperature or 0.2,
                max_output_tokens=budget_decision.max_output_tokens or 900,
            ),
            service_name="BackgroundThinkingService",
            operation_name="execute_background_thinking",
        )
        call_id = _short_text(getattr(result, "call_id", ""), MAX_SAFE_LABEL_LENGTH)
        self._latest_model_call_id = call_id
        if not isinstance(result.data, dict):
            raise StorageError(
                "BACKGROUND_THINKING_MODEL_OUTPUT_INVALID: model output must be a JSON object."
            )
        payload = self._validated_model_gateway_payload(result.data, safe_context)
        self._guard_safe_payload(payload)
        return payload, call_id

    def _validated_model_gateway_payload(
        self,
        data: dict[str, Any],
        safe_context: dict[str, Any],
    ) -> dict[str, Any]:
        raw_safe_summary = _as_dict(data.get("safe_summary"))
        safe_summary = self._whitelist_model_dict(
            raw_safe_summary,
            MODEL_SAFE_SUMMARY_KEYS,
            require_text_key=True,
        )
        if not safe_summary:
            raise StorageError(
                "BACKGROUND_THINKING_MODEL_OUTPUT_INVALID: model output must include a valid safe_summary."
            )

        story_information_preview = []
        for item in _safe_list(data.get("story_information_preview")):
            clean_item = self._whitelist_model_dict(
                _as_dict(item),
                MODEL_STORY_INFORMATION_KEYS,
                require_text_key=False,
            )
            if clean_item:
                story_information_preview.append(clean_item)

        return {
            "safe_summary": safe_summary,
            "risk_warnings": _safe_list_text(data.get("risk_warnings")),
            "story_information_preview": story_information_preview[:MAX_LIST_ITEMS],
            "continuity_considerations": _safe_list_text(
                data.get("continuity_considerations")
            ),
            "open_questions": _safe_list_text(data.get("open_questions")),
            "safe_context_summary": safe_context,
        }

    def _whitelist_model_dict(
        self,
        value: dict[str, Any],
        allowed_keys: set[str],
        *,
        require_text_key: bool,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in sorted(allowed_keys):
            if key not in value:
                continue
            item = value.get(key)
            if item is None:
                continue
            if key == "target_scene_index":
                if isinstance(item, bool):
                    continue
                try:
                    result[key] = int(item)
                except (TypeError, ValueError):
                    continue
                continue
            text = _short_text(item, MAX_SAFE_TEXT_LENGTH)
            if text:
                result[key] = text
        if require_text_key and not any(
            str(result.get(key) or "").strip() for key in MODEL_REQUIRED_SUMMARY_KEYS
        ):
            return {}
        return result

    def _build_candidate(
        self,
        task: BackgroundThinkingTask,
        snapshots: list[SceneVersionSnapshot],
        candidate_payload: dict[str, Any],
    ) -> ThinkingCandidate:
        timestamp = now_iso()
        based_on_snapshot_hashes = {
            snapshot.snapshot_id: snapshot.snapshot_hash for snapshot in snapshots
        }
        safe_payload = self._sanitize_payload(candidate_payload)
        candidate = ThinkingCandidate(
            candidate_id=self._next_candidate_id(),
            project_id=LOCAL_PROJECT_ID,
            task_id=task.task_id,
            source_scene_id=task.source_scene_id,
            target_scene_id=task.target_scene_id,
            target_chapter_id=task.target_chapter_id,
            target_scene_index=task.target_scene_index,
            based_on_snapshot_ids=[snapshot.snapshot_id for snapshot in snapshots],
            based_on_snapshot_hashes=based_on_snapshot_hashes,
            status="ready",
            safe_summary=_as_dict(safe_payload.get("safe_summary")),
            risk_warnings=_safe_list_text(safe_payload.get("risk_warnings")),
            story_information_preview=[
                self._sanitize_payload(_as_dict(item))
                for item in _safe_list(safe_payload.get("story_information_preview"))
            ][:MAX_LIST_ITEMS],
            continuity_considerations=_safe_list_text(
                safe_payload.get("continuity_considerations")
            ),
            open_questions=_safe_list_text(safe_payload.get("open_questions")),
            budget_profile=task.budget_profile,
            execution_strategy=task.execution_strategy,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._guard_safe_payload(candidate)
        return candidate

    def _fail_task(
        self,
        task: BackgroundThinkingTask,
        exc: Exception,
    ) -> BackgroundThinkingTask:
        safe_error = self._safe_error_from_exception(exc)
        failed = self._copy_task(
            task,
            status="failed",
            safe_error=safe_error,
            completed_at=now_iso(),
            updated_at=now_iso(),
        )
        self._upsert_task(failed)
        return failed

    def _safe_error_from_exception(self, exc: Exception) -> dict[str, Any]:
        text = str(exc)
        code, _, detail = text.partition(":")
        code = code if code.startswith("BACKGROUND_THINKING_") else "BACKGROUND_THINKING_EXECUTION_FAILED"
        if isinstance(exc, (ModelConfigurationError, ModelCallError, ModelJsonParseError)):
            sanitized = self.runtime_error_sanitizer.sanitize(exc)
            return self._safe_error(
                "BACKGROUND_THINKING_MODEL_GATEWAY_FAILED",
                sanitized.user_visible_message,
                stage="model_gateway",
                retryable=sanitized.retryable,
                suggested_action=sanitized.suggested_action,
            )
        if code == "BACKGROUND_THINKING_EXECUTION_FAILED":
            message = "Background thinking task failed safely."
        else:
            message = detail.strip() or "Background thinking task could not be completed."
        stage = "validation"
        if "SNAPSHOT" in code:
            stage = "snapshot_dependency"
        if code == "BACKGROUND_THINKING_MODEL_OUTPUT_INVALID":
            stage = "model_gateway"
        return self._safe_error(
            code,
            message,
            stage=stage,
            retryable=code
            in {
                "BACKGROUND_THINKING_NO_ACTIVE_SNAPSHOT",
                "BACKGROUND_THINKING_MODEL_GATEWAY_FAILED",
                "BACKGROUND_THINKING_MODEL_OUTPUT_INVALID",
            },
            suggested_action=self._suggested_action_for_error(code),
        )

    def _safe_error(
        self,
        error_code: str,
        message: str,
        *,
        stage: str,
        retryable: bool,
        suggested_action: str,
    ) -> dict[str, Any]:
        payload = {
            "error_code": _short_text(error_code, 120),
            "message": _short_text(message, 260),
            "stage": _short_text(stage, 120),
            "retryable": bool(retryable),
            "suggested_action": _short_text(suggested_action, 260),
        }
        self._guard_safe_payload(payload)
        return payload

    def _suggested_action_for_error(self, error_code: str) -> str:
        if error_code == "BACKGROUND_THINKING_NO_ACTIVE_SNAPSHOT":
            return "Create an active scene snapshot before queueing background thinking."
        if error_code == "BACKGROUND_THINKING_STALE_SNAPSHOT":
            return "Refresh the scene snapshot and retry with an active snapshot."
        if error_code == "BACKGROUND_THINKING_SNAPSHOT_NOT_FOUND":
            return "Check input_snapshot_ids and retry."
        if error_code == "BACKGROUND_THINKING_MODEL_GATEWAY_FAILED":
            return "Retry later or use deterministic_fallback."
        if error_code == "BACKGROUND_THINKING_MODEL_OUTPUT_INVALID":
            return "Retry the model_gateway task or switch explicitly to deterministic_fallback."
        return "Review the request and retry."

    def _safe_error_summary(self, safe_error: dict[str, Any]) -> dict[str, Any]:
        if not safe_error:
            return {}
        return {
            "error_code": _short_text(safe_error.get("error_code"), 120),
            "message": _short_text(safe_error.get("message"), 220),
            "stage": _short_text(safe_error.get("stage"), 120),
            "retryable": bool(safe_error.get("retryable")),
            "suggested_action": _short_text(safe_error.get("suggested_action"), 220),
        }

    def _read_tasks(self) -> list[BackgroundThinkingTask]:
        if not self.store.exists(self.tasks_file):
            return []
        raw_items = self.store.read_list(self.tasks_file)
        result: list[BackgroundThinkingTask] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                result.append(BackgroundThinkingTask(**item))
            except ValidationError as exc:
                raise StorageError(f"JSON schema is invalid: {self.tasks_file}") from exc
        return result

    def _write_tasks(self, tasks: list[BackgroundThinkingTask]) -> None:
        payload = [model_to_dict(task) for task in tasks]
        self._guard_safe_payload(payload)
        self.store.write(self.tasks_file, payload)

    def _append_task(self, task: BackgroundThinkingTask) -> None:
        tasks = self._read_tasks()
        tasks.append(task)
        self._write_tasks(tasks)

    def _upsert_task(self, task: BackgroundThinkingTask) -> None:
        tasks = self._read_tasks()
        updated = []
        replaced = False
        for existing in tasks:
            if existing.task_id == task.task_id:
                updated.append(task)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(task)
        self._write_tasks(updated)

    def _read_candidates(self) -> list[ThinkingCandidate]:
        if not self.store.exists(self.candidates_file):
            return []
        raw_items = self.store.read_list(self.candidates_file)
        result: list[ThinkingCandidate] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                result.append(ThinkingCandidate(**item))
            except ValidationError as exc:
                raise StorageError(f"JSON schema is invalid: {self.candidates_file}") from exc
        return result

    def _write_candidates(self, candidates: list[ThinkingCandidate]) -> None:
        payload = [model_to_dict(candidate) for candidate in candidates]
        self._guard_safe_payload(payload)
        self.store.write(self.candidates_file, payload)

    def _next_task_id(self) -> str:
        return f"background_thinking_task_{len(self._read_tasks()) + 1:03d}"

    def _next_candidate_id(self) -> str:
        return f"thinking_candidate_{len(self._read_candidates()) + 1:03d}"

    def _copy_task(
        self,
        task: BackgroundThinkingTask,
        **updates: Any,
    ) -> BackgroundThinkingTask:
        payload = model_to_dict(task)
        payload.update(updates)
        return BackgroundThinkingTask(**payload)

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

    def _guard_safe_payload(self, payload: Any) -> None:
        issues = self._scan_for_unsafe_payload(payload)
        if issues:
            raise StorageError(
                "BACKGROUND_THINKING_UNSAFE_PAYLOAD_BLOCKED: "
                + "; ".join(issues[:5])
            )

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
            for marker in UNSAFE_VALUE_MARKERS:
                if marker in lower:
                    issues.append(f"unsafe_value:{path}")
                    break
            if any(pattern.search(text) for pattern in SECRET_LIKE_PATTERNS):
                issues.append(f"secret_like_value:{path}")
            if len(text) > MAX_SAFE_TEXT_LENGTH:
                issues.append(f"long_text:{path}")
            return issues
        return issues


def _short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _safe_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value[:MAX_LIST_ITEMS]


def _safe_list_text(value: Any) -> list[str]:
    return [_short_text(item, MAX_SAFE_LABEL_LENGTH) for item in _safe_list(value)]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
