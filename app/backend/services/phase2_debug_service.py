from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.phase2_debug import Phase2DebugResponse
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.background_thinking_service import BackgroundThinkingService
from app.backend.services.background_budget_service import BackgroundBudgetService
from app.backend.services.chapter_archive_service import ChapterArchiveService, model_to_dict as archive_model_to_dict
from app.backend.services.future_review_service import FutureReviewService
from app.backend.services.model_gateway_service import ModelGatewayService
from app.backend.services.model_runtime_log_service import ModelRuntimeLogService
from app.backend.services.modification_impact_service import ModificationImpactService
from app.backend.services.narrative_debt_visibility_service import (
    NarrativeDebtVisibilityService,
)
from app.backend.services.pre_modify_pipeline_service import PreModifyPipelineService
from app.backend.services.pre_modify_workspace_service import PreModifyWorkspaceService
from app.backend.services.scene_progress_service import SceneProgressService
from app.backend.services.scene_candidate_cache_service import SceneCandidateCacheService
from app.backend.services.scene_version_snapshot_service import (
    SceneVersionSnapshotService,
)
from app.backend.services.tracing_service import TracingService
from app.backend.storage.json_store import JsonStore


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
SECRET_VALUE_MARKERS = ["s" + "k-", "lsv2_"]
UNSAFE_DEBUG_KEYS = {
    "api_key",
    "api_key_ref",
    "api_key_value",
    "prompt",
    "raw_prompt",
    "raw_response",
    "raw_text",
    "hidden_reasoning",
    "chain_of_thought",
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "authorization",
    "bearer",
    "bearer_token",
}


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class Phase2DebugService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        model_gateway: ModelGatewayService | None = None,
        runtime_logs: ModelRuntimeLogService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.runtime_logs = runtime_logs or ModelRuntimeLogService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.tracing = TracingService()
        self.scene_progress_service = SceneProgressService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.narrative_debt_visibility_service = NarrativeDebtVisibilityService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.modification_impact_service = ModificationImpactService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.chapter_archive_service = ChapterArchiveService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            scene_progress_service=self.scene_progress_service,
        )
        self.scene_snapshot_service = SceneVersionSnapshotService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.background_budget_service = BackgroundBudgetService(
            store=self.store,
            data_dir=self.data_dir,
            runtime_logs=self.runtime_logs,
        )
        self.background_thinking_service = BackgroundThinkingService(
            store=self.store,
            data_dir=self.data_dir,
            snapshot_service=self.scene_snapshot_service,
            model_gateway=self.model_gateway,
            background_budget_service=self.background_budget_service,
        )
        self.pre_modify_service = PreModifyPipelineService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            modification_impact_service=self.modification_impact_service,
            snapshot_service=self.scene_snapshot_service,
            background_thinking_service=self.background_thinking_service,
            background_budget_service=self.background_budget_service,
        )
        self.scene_candidate_cache_service = SceneCandidateCacheService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            background_thinking_service=self.background_thinking_service,
            pre_modify_service=self.pre_modify_service,
            snapshot_service=self.scene_snapshot_service,
        )
        self.future_review_service = FutureReviewService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            scene_candidate_cache_service=self.scene_candidate_cache_service,
        )
        self.pre_modify_workspace_service = PreModifyWorkspaceService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            pre_modify_service=self.pre_modify_service,
            scene_candidate_cache_service=self.scene_candidate_cache_service,
            future_review_service=self.future_review_service,
        )

    def get_phase2_debug(self) -> Phase2DebugResponse:
        current_chapter = self._current_chapter()
        current_scene = self._current_scene(current_chapter)
        payload = Phase2DebugResponse(
            generated_at=now_iso(),
            project_id=LOCAL_PROJECT_ID,
            model_trace=self._model_trace(),
            memory_inspector=self._memory_inspector(current_chapter, current_scene),
            character_state=self._character_state(),
            continuity=self._continuity(current_scene),
            narrative_layer=self._narrative_layer(current_chapter, current_scene),
            modification_impact=self._modification_impact(),
            scene_progress=self._scene_progress(current_chapter),
            scene_snapshots=self._scene_snapshots(),
            background_budget=self._background_budget(),
            background_thinking=self._background_thinking(),
            pre_modify=self._pre_modify(),
            pre_modify_workspace=self._pre_modify_workspace(),
            scene_candidate_cache=self._scene_candidate_cache(),
            future_review=self._future_review(),
            chapter_archive=self._chapter_archive(),
        )
        response_data = self._strip_unsafe_debug_keys(model_to_dict(payload))
        response_data["safety"] = self._safety(response_data)
        return Phase2DebugResponse(**response_data)

    def _scene_snapshots(self) -> dict[str, Any]:
        try:
            return self.scene_snapshot_service.debug_summary()
        except Exception as exc:
            return {
                "available": False,
                "snapshot_count": 0,
                "active_count": 0,
                "stale_count": 0,
                "recent_snapshots": [],
                "latest_invalidations": [],
                "safety": {
                    "safe": False,
                    "issues": [f"scene_snapshot_debug_failed:{type(exc).__name__}"],
                },
            }

    def _background_budget(self) -> dict[str, Any]:
        try:
            return self.background_budget_service.debug_summary()
        except Exception as exc:
            return {
                "available": False,
                "profile_count": 0,
                "policy_count": 0,
                "enabled_profile_ids": [],
                "active_background_profile_ids": [],
                "recent_usage_records": [],
                "recent_routing_decisions": [],
                "safety": {
                    "safe": False,
                    "issues": [f"background_budget_debug_failed:{type(exc).__name__}"],
                },
            }

    def _background_thinking(self) -> dict[str, Any]:
        try:
            return self.background_thinking_service.debug_summary()
        except Exception as exc:
            return {
                "available": False,
                "task_count": 0,
                "candidate_count": 0,
                "recent_tasks": [],
                "recent_candidates": [],
                "latest_safe_errors": [
                    {
                        "error_code": "BACKGROUND_THINKING_DEBUG_FAILED",
                        "message": _short_text(type(exc).__name__, 120),
                        "stage": "debug_summary",
                        "retryable": False,
                        "suggested_action": "Review background thinking storage schema.",
                    }
                ],
                "safety": {
                    "safe": False,
                    "issues": [f"background_thinking_debug_failed:{type(exc).__name__}"],
                },
            }

    def _pre_modify_workspace(self) -> dict[str, Any]:
        try:
            return self.pre_modify_workspace_service.debug_summary()
        except Exception as exc:
            return {
                "available": False,
                "action_count": 0,
                "apply_plan_count": 0,
                "revision_request_count": 0,
                "recent_action_ids": [],
                "recent_apply_plan_ids": [],
                "recent_revision_request_ids": [],
                "recent_blocked_reasons": [],
                "action_counts_by_type": {},
                "action_counts_by_status": {},
                "safety": {
                    "safe": False,
                    "issues": [f"pre_modify_workspace_debug_failed:{type(exc).__name__}"],
                },
            }

    def _pre_modify(self) -> dict[str, Any]:
        try:
            return self.pre_modify_service.debug_summary()
        except Exception as exc:
            return {
                "available": False,
                "candidate_count": 0,
                "ready_count": 0,
                "blocked_count": 0,
                "stale_count": 0,
                "superseded_count": 0,
                "warning_only_count": 0,
                "plan_count": 0,
                "reason_count": 0,
                "recent_candidate_ids": [],
                "recent_source_preview_ids": [],
                "recent_target_scene_ids": [],
                "latest_warnings": [],
                "safety": {
                    "safe": False,
                    "issues": [f"pre_modify_debug_failed:{type(exc).__name__}"],
                },
            }

    def _scene_candidate_cache(self) -> dict[str, Any]:
        try:
            return self.scene_candidate_cache_service.debug_summary()
        except Exception as exc:
            return {
                "available": False,
                "cache_count": 0,
                "candidate_count": 0,
                "active_candidate_count": 0,
                "stale_candidate_count": 0,
                "hidden_candidate_count": 0,
                "archived_candidate_count": 0,
                "recent_cache_ids": [],
                "recent_cached_candidate_ids": [],
                "recent_invalidation_ids": [],
                "recent_candidates": [],
                "safety": {
                    "safe": False,
                    "issues": [f"scene_candidate_cache_debug_failed:{type(exc).__name__}"],
                },
            }

    def _future_review(self) -> dict[str, Any]:
        try:
            return self.future_review_service.debug_summary()
        except Exception as exc:
            return {
                "available": False,
                "future_issue_count": 0,
                "delayed_question_count": 0,
                "future_todo_count": 0,
                "recent_future_issue_ids": [],
                "recent_delayed_question_ids": [],
                "recent_future_todo_ids": [],
                "safety": {
                    "safe": False,
                    "issues": [f"future_review_debug_failed:{type(exc).__name__}"],
                },
            }

    def _model_trace(self) -> dict[str, Any]:
        status = self.model_gateway.validate_model_config()
        runtime_status = self.model_gateway.provider_health.build_status_response()
        tracing = self.tracing.get_status()
        provider_health = [
            {
                "provider_id": health.provider_id,
                "provider_type": health.provider_type,
                "model_name": health.model_name,
                "status": health.status,
                "configured": health.configured,
                "key_ref_configured": health.api_key_ref_present,
                "key_value_present_in_env": health.api_key_value_present_in_env,
                "last_success_at": health.last_success_at,
                "last_failure_at": health.last_failure_at,
                "last_latency_ms": health.last_latency_ms,
                "recent_success_count": health.recent_success_count,
                "recent_failure_count": health.recent_failure_count,
                "recent_json_parse_failure_count": health.recent_json_parse_failure_count,
                "last_error_type": health.last_error_type,
                "last_error_message_safe": health.last_error_message_safe,
                "updated_at": health.updated_at,
            }
            for health in runtime_status.provider_health
        ]
        recent_calls = [
            self._safe_call_summary(model_to_dict(call))
            for call in self.runtime_logs.recent_calls(limit=5)
        ]
        recent_errors = [
            self._safe_error_summary(model_to_dict(error))
            for error in self.runtime_logs.recent_errors(limit=5)
        ]
        return {
            "active_provider": status.provider_type or "",
            "active_model": status.model_name or "",
            "configured": status.configured,
            "configuration_issues": list(status.issues),
            "provider_health": provider_health,
            "langsmith": {
                "enabled": tracing.enabled,
                "requested": tracing.requested,
                "project": tracing.project,
                "package_available": tracing.package_available,
                "key_configured": tracing.api_key_configured,
                "issues": list(tracing.issues),
            },
            "recent_safe_calls": recent_calls,
            "recent_errors": recent_errors,
            "recent_success_count": runtime_status.recent_success_count,
            "recent_failure_count": runtime_status.recent_failure_count,
            "recent_json_parse_failure_count": runtime_status.recent_json_parse_failure_count,
            "updated_at": runtime_status.updated_at,
        }

    def _memory_inspector(
        self,
        current_chapter: dict[str, Any] | None,
        current_scene: dict[str, Any] | None,
    ) -> dict[str, Any]:
        chapter_pack = self._current_chapter_pack(current_chapter, current_scene)
        scene_pack = self._current_scene_pack(current_scene)
        memory_ids = self._memory_ids_from_packs(current_scene, chapter_pack, scene_pack)
        memory_records = [
            self._memory_summary(memory)
            for memory in self.repositories.memory.list_all()
            if str(memory.get("memory_id") or "") in set(memory_ids)
        ]
        explanations = [
            self._memory_usage_explanation(memory_id, current_scene, scene_pack)
            for memory_id in memory_ids
        ]
        return {
            "current_chapter": self._chapter_summary(current_chapter),
            "current_scene": self._scene_debug_summary(current_scene),
            "chapter_pack": self._chapter_pack_summary(chapter_pack),
            "scene_pack": self._scene_pack_summary(scene_pack),
            "memory_records_used": memory_records,
            "usage_explanations": explanations,
            "source_query_summary": self._source_query_summary(scene_pack),
        }

    def _character_state(self) -> dict[str, Any]:
        characters = self.repositories.characters.list_all()
        pending_changes = self.repositories.pending_character_state_changes.list_all()
        active_memories = self.repositories.memory.list_all()
        a_tier = [
            self._role_summary(character, active_memories, include_state=True)
            for character in characters
            if str(character.get("tier") or "").upper() == "A"
        ]
        supporting_roles = [
            self._role_summary(character, active_memories, include_state=False)
            for character in characters
            if str(character.get("tier") or "").upper() in {"B", "C", "D"}
        ]
        pending_major = [
            self._pending_change_summary(change)
            for change in pending_changes
            if str(change.get("status") or "") == "pending"
            and str(change.get("tier") or "").upper() == "A"
            and str(change.get("impact_level") or "").lower() == "major"
        ]
        return {
            "a_tier_roles": a_tier,
            "supporting_roles": supporting_roles,
            "pending_major_state_changes": pending_major,
            "pending_major_count": len(pending_major),
            "role_count_by_tier": self._role_count_by_tier(characters),
        }

    def _continuity(self, current_scene: dict[str, Any] | None) -> dict[str, Any]:
        current_scene_id = str((current_scene or {}).get("scene_id") or "")
        issues = [
            self._continuity_issue_summary(issue)
            for issue in self.repositories.continuity_issues.list_all()
            if not current_scene_id or issue.get("scene_id") == current_scene_id
        ]
        candidates = [
            self._prior_story_completion_candidate_summary(candidate)
            for candidate in self.repositories.prior_story_completion_candidates.list_all()
            if not current_scene_id or candidate.get("scene_id") == current_scene_id
        ]
        return {
            "current_scene_id": current_scene_id,
            "issues": issues,
            "open_issue_count": sum(1 for issue in issues if issue.get("status") == "open"),
            "blocking_issue_count": sum(
                1
                for issue in issues
                if issue.get("status") == "open"
                and issue.get("blocks_final_confirmation")
            ),
            "prior_story_completion_candidates": candidates,
            "available_actions": [
                "accept_issue",
                "complete_prior_story",
                "revise_current_scene",
                "mark_as_misinformation_or_lie",
                "confirm_prior_story_completion_candidate",
                "reject_prior_story_completion_candidate",
            ],
        }

    def _narrative_layer(
        self,
        current_chapter: dict[str, Any] | None,
        current_scene: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "narrative_debts": self.narrative_debt_visibility_service.visibility_summary(
                scene_id=str((current_scene or {}).get("scene_id") or "") or None,
                chapter_id=str((current_chapter or {}).get("chapter_id") or "") or None,
            )
        }

    def _modification_impact(self) -> dict[str, Any]:
        try:
            return self.modification_impact_service.debug_summary()
        except Exception as exc:
            return {
                "available": False,
                "error": _short_text(str(exc), 240),
                "recent_previews": [],
            }

    def _scene_progress(self, current_chapter: dict[str, Any] | None) -> dict[str, Any]:
        progress = self.scene_progress_service.get_progress(
            str((current_chapter or {}).get("chapter_id") or "") or None
        )
        scenes = [self._progress_scene_summary(scene) for scene in progress.scenes]
        return {
            "chapter_id": progress.chapter_id,
            "scene_count": progress.scene_count,
            "next_scene_index": progress.next_scene_index,
            "can_generate_next": progress.can_generate_next,
            "blocking_reasons": progress.blocking_reasons,
            "dependency_warnings": progress.dependency_warnings,
            "completion_status": progress.completion_status,
            "scenes": scenes,
            "temporary_confirmed_scene_ids": [
                scene["scene_id"]
                for scene in scenes
                if scene.get("status") == "temporary_confirmed"
            ],
        }

    def _chapter_archive(self) -> dict[str, Any]:
        try:
            preview = self.chapter_archive_service.preview_archive()
            archives = self.chapter_archive_service.list_archives()
        except Exception as exc:
            return {
                "available": False,
                "error": _short_text(str(exc), 240),
                "records": [],
            }
        return {
            "available": True,
            "recommended_archive_mode": preview.recommended_archive_mode,
            "ready_for_archive": preview.validation_report.passed,
            "blocking_issue_count": len(preview.validation_report.blocking_issues),
            "warning_count": len(preview.validation_report.warnings),
            "existing_archive_id": preview.existing_archive.archive_id
            if preview.existing_archive
            else "",
            "candidate_archive_id": preview.archive_candidate.archive_id
            if preview.archive_candidate
            else "",
            "user_visible_summary": _short_text(preview.user_visible_summary, 360),
            "records": [
                {
                    "archive_id": archive.archive_id,
                    "chapter_id": archive.chapter_id,
                    "chapter_index": archive.chapter_index,
                    "archive_status": archive.archive_status,
                    "chapter_completion_status": archive.chapter_completion_status,
                    "scene_ids": archive.scene_ids,
                    "unresolved_issue_ids": archive.unresolved_issue_ids,
                    "narrative_debt_ids": archive.narrative_debt_ids,
                    "summary": _short_text(archive.summary, 360),
                }
                for archive in archives
            ],
            "validation": {
                "blocking_issues": [
                    archive_model_to_dict(issue)
                    for issue in preview.validation_report.blocking_issues
                ],
                "warnings": [
                    archive_model_to_dict(issue)
                    for issue in preview.validation_report.warnings
                ],
            },
        }

    def _safety(self, payload: dict[str, Any]) -> dict[str, Any]:
        issues = self._scan_for_unsafe_debug_payload(payload)
        no_secret_key_leak = not any(issue.startswith("secret_value:") for issue in issues)
        no_full_prompt_or_raw_output = not any(
            issue.startswith("unsafe_key:") for issue in issues
        )
        return {
            "no_secret_key_leak": no_secret_key_leak,
            "no_full_prompt_or_raw_output": no_full_prompt_or_raw_output,
            "debug_load_does_not_call_model": True,
            "notes": [
                "Debug payload is read-only and built from repositories/runtime ledger.",
                "Full prompt, raw response, API key values, and full prose are not returned.",
            ],
            "issues": issues,
        }

    def _strip_unsafe_debug_keys(self, value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if key_text.lower() in UNSAFE_DEBUG_KEYS:
                    continue
                result[key_text] = self._strip_unsafe_debug_keys(item)
            return result
        if isinstance(value, list):
            return [self._strip_unsafe_debug_keys(item) for item in value]
        return value

    def _current_chapter(self) -> dict[str, Any] | None:
        chapters = self.repositories.chapters.list_all()
        return (
            next((item for item in chapters if item.get("detail_level") == "current_chapter_brief"), None)
            or next((item for item in chapters if item.get("status") == "active"), None)
            or next((item for item in chapters if item.get("chapter_framework_id")), None)
            or (chapters[0] if chapters else None)
        )

    def _current_scene(
        self,
        current_chapter: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        chapter_id = str((current_chapter or {}).get("chapter_id") or "")
        scenes = [
            scene
            for scene in self.repositories.scenes.list_all()
            if not chapter_id or scene.get("chapter_id") == chapter_id
        ]
        if not scenes:
            return None
        return sorted(
            scenes,
            key=lambda scene: (
                int(scene.get("scene_index") or 0),
                str(scene.get("updated_at") or scene.get("created_at") or ""),
            ),
            reverse=True,
        )[0]

    def _current_chapter_pack(
        self,
        current_chapter: dict[str, Any] | None,
        current_scene: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        scene_pack_id = str((current_scene or {}).get("chapter_memory_pack_id") or "")
        if scene_pack_id:
            pack = self.repositories.chapter_memory_packs.get_by_id(scene_pack_id)
            if pack:
                return pack
        chapter_id = str((current_chapter or {}).get("chapter_id") or "")
        packs = [
            pack
            for pack in self.repositories.chapter_memory_packs.list_packs()
            if not chapter_id or pack.get("chapter_id") == chapter_id
        ]
        return next((pack for pack in packs if pack.get("status") == "active"), None) or (
            packs[-1] if packs else None
        )

    def _current_scene_pack(
        self,
        current_scene: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        scene_pack_id = str((current_scene or {}).get("scene_memory_pack_id") or "")
        if scene_pack_id:
            pack = self.repositories.scene_memory_packs.get_by_id(scene_pack_id)
            if pack:
                return pack
        scene_id = str((current_scene or {}).get("scene_id") or "")
        scene_index = int((current_scene or {}).get("scene_index") or 0)
        packs = [
            pack
            for pack in self.repositories.scene_memory_packs.list_packs()
            if (scene_id and pack.get("scene_id") == scene_id)
            or (scene_index and int(pack.get("scene_index") or 0) == scene_index)
        ]
        return next((pack for pack in packs if pack.get("status") == "active"), None) or (
            packs[-1] if packs else None
        )

    def _memory_ids_from_packs(
        self,
        current_scene: dict[str, Any] | None,
        chapter_pack: dict[str, Any] | None,
        scene_pack: dict[str, Any] | None,
    ) -> list[str]:
        values: list[Any] = []
        if current_scene:
            values.extend(current_scene.get("input_memory_ids") or [])
            values.extend(current_scene.get("depends_on_provisional_memory_ids") or [])
        if chapter_pack:
            values.extend(chapter_pack.get("included_memory_ids") or [])
        if scene_pack:
            for key in [
                "must_use_memory_ids",
                "should_use_memory_ids",
                "optional_memory_ids",
                "provisional_memory_ids",
            ]:
                values.extend(scene_pack.get(key) or [])
            for key in [
                "must_use_context",
                "should_use_context",
                "optional_context",
            ]:
                for item in scene_pack.get(key) or []:
                    if isinstance(item, dict):
                        values.append(item.get("memory_id"))
        return _unique_strings(values)

    def _chapter_summary(self, chapter: dict[str, Any] | None) -> dict[str, Any]:
        if not chapter:
            return {}
        return {
            "chapter_id": chapter.get("chapter_id", ""),
            "chapter_index": chapter.get("chapter_index", 0),
            "title": chapter.get("title", ""),
            "status": chapter.get("status", ""),
            "scene_count": chapter.get("scene_count", 0),
            "chapter_goal": _short_text(chapter.get("chapter_goal"), 220),
            "main_conflict": _short_text(chapter.get("main_conflict"), 220),
        }

    def _scene_debug_summary(self, scene: dict[str, Any] | None) -> dict[str, Any]:
        if not scene:
            return {}
        return {
            "scene_id": scene.get("scene_id", ""),
            "chapter_id": scene.get("chapter_id", ""),
            "scene_index": scene.get("scene_index", 0),
            "status": scene.get("status", ""),
            "prose_status": scene.get("prose_status", ""),
            "is_provisional": bool(scene.get("is_provisional")),
            "goal": _short_text(scene.get("goal") or scene.get("synopsis"), 220),
            "location": scene.get("location", ""),
            "chapter_memory_pack_id": scene.get("chapter_memory_pack_id", ""),
            "scene_memory_pack_id": scene.get("scene_memory_pack_id", ""),
            "input_memory_ids": _unique_strings(scene.get("input_memory_ids") or []),
            "depends_on_provisional_scene_ids": _unique_strings(
                scene.get("depends_on_provisional_scene_ids") or []
            ),
            "depends_on_provisional_memory_ids": _unique_strings(
                scene.get("depends_on_provisional_memory_ids") or []
            ),
            "needs_review_reason": _short_text(scene.get("needs_review_reason"), 220),
            "active_revision_id": scene.get("active_revision_id", ""),
        }

    def _chapter_pack_summary(self, pack: dict[str, Any] | None) -> dict[str, Any]:
        if not pack:
            return {}
        return {
            "chapter_memory_pack_id": pack.get("chapter_memory_pack_id", ""),
            "chapter_id": pack.get("chapter_id", ""),
            "status": pack.get("status", ""),
            "included_memory_ids": _unique_strings(pack.get("included_memory_ids") or []),
            "retrieval_gaps": self._retrieval_gaps(pack),
            "retrieval_summary": _short_text(pack.get("retrieval_summary"), 260),
            "source_query_summary": self._source_query_summary(pack),
        }

    def _scene_pack_summary(self, pack: dict[str, Any] | None) -> dict[str, Any]:
        if not pack:
            return {}
        return {
            "scene_memory_pack_id": pack.get("scene_memory_pack_id", ""),
            "chapter_memory_pack_id": pack.get("chapter_memory_pack_id", ""),
            "chapter_id": pack.get("chapter_id", ""),
            "scene_id": pack.get("scene_id", ""),
            "scene_index": pack.get("scene_index", 0),
            "status": pack.get("status", ""),
            "must_use_memory_ids": _unique_strings(pack.get("must_use_memory_ids") or []),
            "should_use_memory_ids": _unique_strings(pack.get("should_use_memory_ids") or []),
            "optional_memory_ids": _unique_strings(pack.get("optional_memory_ids") or []),
            "forbidden_or_conflict_memory_ids": _unique_strings(
                pack.get("forbidden_or_conflict_memory_ids") or []
            ),
            "provisional_memory_ids": _unique_strings(pack.get("provisional_memory_ids") or []),
            "provisional_dependency_scene_ids": _unique_strings(
                pack.get("provisional_dependency_scene_ids") or []
            ),
            "retrieval_gaps": self._retrieval_gaps(pack),
            "source_query_summary": self._source_query_summary(pack),
        }

    def _retrieval_gaps(self, pack: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "gap_id": gap.get("gap_id", ""),
                "gap_type": gap.get("gap_type", ""),
                "severity": gap.get("severity", ""),
                "message": _short_text(gap.get("message"), 260),
                "suggested_action": _short_text(gap.get("suggested_action"), 220),
                "related_scene_id": gap.get("related_scene_id"),
                "related_character_ids": gap.get("related_character_ids") or [],
                "related_keywords": gap.get("related_keywords") or [],
            }
            for gap in pack.get("retrieval_gaps") or []
            if isinstance(gap, dict)
        ]

    def _source_query_summary(self, pack: dict[str, Any] | None) -> dict[str, Any]:
        if not pack:
            return {}
        signature = pack.get("source_query_signature") or {}
        resolved = signature.get("resolved_scene_inputs") if isinstance(signature, dict) else {}
        if not isinstance(resolved, dict):
            resolved = {}
        return {
            "scene_goal": _short_text(
                pack.get("scene_goal") or resolved.get("scene_goal") or signature.get("scene_goal"),
                220,
            ),
            "scene_location": (
                pack.get("scene_location")
                or resolved.get("scene_location")
                or signature.get("scene_location")
                or ""
            ),
            "active_character_ids": _unique_strings(
                pack.get("active_character_ids")
                or resolved.get("active_character_ids")
                or signature.get("active_character_ids")
                or []
            ),
            "include_provisional": bool(
                resolved.get("include_provisional")
                or signature.get("include_provisional")
            ),
            "chapter_id": pack.get("chapter_id", ""),
            "scene_id": pack.get("scene_id", ""),
            "scene_index": pack.get("scene_index", 0),
        }

    def _memory_summary(self, memory: dict[str, Any]) -> dict[str, Any]:
        return {
            "memory_id": memory.get("memory_id", ""),
            "summary": _short_text(memory.get("summary"), 260),
            "memory_type": memory.get("memory_type", ""),
            "status": memory.get("status", ""),
            "truth_status": memory.get("truth_status", ""),
            "objective_truth": memory.get("objective_truth"),
            "source_object_type": memory.get("source_object_type") or memory.get("source_type") or "",
            "source_object_id": memory.get("source_object_id") or memory.get("object_id") or "",
            "chapter_id": memory.get("chapter_id", ""),
            "scene_id": memory.get("scene_id", ""),
            "character_ids": _unique_strings(memory.get("character_ids") or []),
            "relationship_ids": _unique_strings(memory.get("relationship_ids") or []),
            "event_ids": _unique_strings(memory.get("event_ids") or []),
            "location": memory.get("location"),
            "keywords": _unique_strings(memory.get("keywords") or memory.get("tags") or [])[:12],
        }

    def _memory_usage_explanation(
        self,
        memory_id: str,
        current_scene: dict[str, Any] | None,
        scene_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        matched_by: list[str] = []
        if current_scene and memory_id in (current_scene.get("input_memory_ids") or []):
            matched_by.append("scene_input_memory")
        if current_scene and memory_id in (
            current_scene.get("depends_on_provisional_memory_ids") or []
        ):
            matched_by.append("provisional_dependency")
        if scene_pack:
            for key, label in [
                ("must_use_memory_ids", "scene_memory_pack_must_use"),
                ("should_use_memory_ids", "scene_memory_pack_should_use"),
                ("optional_memory_ids", "scene_memory_pack_optional"),
                ("provisional_memory_ids", "scene_memory_pack_provisional"),
            ]:
                if memory_id in (scene_pack.get(key) or []):
                    matched_by.append(label)
            for key, label in [
                ("must_use_context", "source_ref_must_use"),
                ("should_use_context", "source_ref_should_use"),
                ("optional_context", "source_ref_optional"),
            ]:
                for item in scene_pack.get(key) or []:
                    if isinstance(item, dict) and item.get("memory_id") == memory_id:
                        matched_by.extend(item.get("matched_by") or [])
                        if item.get("reason"):
                            return {
                                "memory_id": memory_id,
                                "reason": _short_text(item.get("reason"), 260),
                                "matched_by": _unique_strings([label, *matched_by]),
                            }
                        matched_by.append(label)
        if not matched_by:
            matched_by.append("chapter_memory_pack")
        reason_parts = []
        if scene_pack:
            if scene_pack.get("scene_goal"):
                reason_parts.append("matched current scene goal")
            if scene_pack.get("scene_location"):
                reason_parts.append("matched current scene location")
            if scene_pack.get("active_character_ids"):
                reason_parts.append("matched active characters")
        reason = "; ".join(reason_parts) or "included by current memory pack"
        return {
            "memory_id": memory_id,
            "reason": reason,
            "matched_by": _unique_strings(matched_by),
        }

    def _role_summary(
        self,
        character: dict[str, Any],
        memories: list[dict[str, Any]],
        *,
        include_state: bool,
    ) -> dict[str, Any]:
        character_id = str(character.get("character_id") or "")
        profile = character.get("profile") or {}
        current_state = character.get("current_state") or {}
        arc_state = character.get("arc_state") or {}
        result = {
            "character_id": character_id,
            "name": character.get("name", ""),
            "tier": character.get("tier", ""),
            "role": character.get("role", ""),
            "status": character.get("status", ""),
            "recent_memory_refs": self._recent_character_memories(character_id, memories),
        }
        if include_state:
            result.update(
                {
                    "current_state": {
                        "location_id": current_state.get("location_id", ""),
                        "emotional_state": current_state.get("emotional_state", ""),
                        "active_goal": _short_text(current_state.get("active_goal"), 220),
                        "current_desire": _short_text(current_state.get("current_desire"), 160),
                        "current_fear": _short_text(current_state.get("current_fear"), 160),
                        "knowledge": _safe_list_text(current_state.get("knowledge"), 8),
                    },
                    "arc_state": {
                        "current_arc": _short_text(arc_state.get("current_arc"), 160),
                        "pressure": _short_text(arc_state.get("pressure"), 160),
                        "inner_conflict": _short_text(arc_state.get("inner_conflict"), 160),
                        "next_possible_change": _short_text(
                            arc_state.get("next_possible_change"), 160
                        ),
                    },
                    "forbidden_knowledge": _safe_list_text(
                        profile.get("forbidden_knowledge"), 10
                    ),
                    "hard_limits": _safe_list_text(profile.get("hard_limits"), 10),
                }
            )
        return result

    def _recent_character_memories(
        self,
        character_id: str,
        memories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refs = [
            memory
            for memory in memories
            if character_id in set(str(value) for value in memory.get("character_ids") or [])
        ]
        refs = sorted(
            refs,
            key=lambda memory: str(memory.get("updated_at") or memory.get("created_at") or ""),
            reverse=True,
        )
        return [
            {
                "memory_id": memory.get("memory_id", ""),
                "summary": _short_text(memory.get("summary"), 180),
                "status": memory.get("status", ""),
                "truth_status": memory.get("truth_status", ""),
            }
            for memory in refs[:5]
        ]

    def _pending_change_summary(self, change: dict[str, Any]) -> dict[str, Any]:
        return {
            "change_id": change.get("change_id", ""),
            "character_id": change.get("character_id", ""),
            "character_name": change.get("character_name", ""),
            "tier": change.get("tier", ""),
            "impact_level": change.get("impact_level", ""),
            "change_type": change.get("change_type", ""),
            "status": change.get("status", ""),
            "summary": _short_text(change.get("summary"), 220),
            "reason": _short_text(change.get("reason"), 220),
            "source_scene_id": change.get("source_scene_id", ""),
            "source_event_id": change.get("source_event_id", ""),
            "source_memory_ids": _unique_strings(change.get("source_memory_ids") or []),
            "created_at": change.get("created_at", ""),
        }

    def _role_count_by_tier(self, characters: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        for character in characters:
            tier = str(character.get("tier") or "").upper()
            if tier in counts:
                counts[tier] += 1
        return counts

    def _continuity_issue_summary(self, issue: dict[str, Any]) -> dict[str, Any]:
        return {
            "issue_id": issue.get("issue_id", ""),
            "target_type": issue.get("target_type", ""),
            "target_id": issue.get("target_id", ""),
            "scene_id": issue.get("scene_id", ""),
            "revision_id": issue.get("revision_id", ""),
            "category": issue.get("category", ""),
            "severity": issue.get("severity", ""),
            "status": issue.get("status", ""),
            "acceptance_policy": issue.get("acceptance_policy", ""),
            "user_visible_message": _short_text(issue.get("user_visible_message"), 260),
            "technical_summary": _short_text(issue.get("technical_summary"), 260),
            "evidence_text": _short_text(issue.get("evidence_text"), 180),
            "apparent_contradiction_ids": _unique_strings(
                issue.get("apparent_contradiction_ids") or []
            ),
            "apparent_gate_action": issue.get("apparent_gate_action", ""),
            "apparent_classification": issue.get("apparent_classification", ""),
            "apparent_device_type": issue.get("apparent_device_type", ""),
            "apparent_evidence_summary": _short_text(
                issue.get("apparent_evidence_summary"),
                260,
            ),
            "apparent_matched_record_ids": _unique_strings(
                issue.get("apparent_matched_record_ids") or []
            ),
            "source_memory_ids": _unique_strings(issue.get("source_memory_ids") or []),
            "source_event_ids": _unique_strings(issue.get("source_event_ids") or []),
            "source_scene_ids": _unique_strings(issue.get("source_scene_ids") or []),
            "source_character_ids": _unique_strings(issue.get("source_character_ids") or []),
            "source_relationship_ids": _unique_strings(
                issue.get("source_relationship_ids") or []
            ),
            "blocks_final_confirmation": bool(issue.get("blocks_final_confirmation")),
            "blocks_state_changing_revision_confirmation": bool(
                issue.get("blocks_state_changing_revision_confirmation")
            ),
            "requires_explicit_acceptance": bool(issue.get("requires_explicit_acceptance")),
            "suggested_options": [
                {
                    "option_id": option.get("option_id", ""),
                    "action_type": option.get("action_type", ""),
                    "label": option.get("label", ""),
                    "requires_user_input": bool(option.get("requires_user_input")),
                    "requires_model_call": bool(option.get("requires_model_call")),
                    "expected_effect": _short_text(option.get("expected_effect"), 220),
                }
                for option in issue.get("suggested_options") or []
                if isinstance(option, dict)
            ],
        }

    def _prior_story_completion_candidate_summary(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate.get("candidate_id", ""),
            "issue_id": candidate.get("issue_id", ""),
            "scene_id": candidate.get("scene_id", ""),
            "status": candidate.get("status", ""),
            "user_visible_summary": _short_text(candidate.get("user_visible_summary"), 240),
            "existing_event_ids": _unique_strings(candidate.get("existing_event_ids") or []),
            "existing_memory_ids": _unique_strings(candidate.get("existing_memory_ids") or []),
            "has_proposed_event": bool(candidate.get("proposed_event")),
            "has_proposed_memory_record": bool(candidate.get("proposed_memory_record")),
        }

    def _progress_scene_summary(self, scene: dict[str, Any]) -> dict[str, Any]:
        return {
            "scene_id": scene.get("scene_id", ""),
            "chapter_id": scene.get("chapter_id", ""),
            "scene_index": scene.get("scene_index", 0),
            "status": scene.get("status", ""),
            "prose_status": scene.get("prose_status", ""),
            "prose_generated": scene.get("prose_status") == "generated",
            "prose_skipped": scene.get("prose_status") in {"skipped", "not_generated"},
            "temporary_confirmed": scene.get("status") == "temporary_confirmed",
            "is_provisional": bool(scene.get("is_provisional")),
            "depends_on_provisional_scene_ids": _unique_strings(
                scene.get("depends_on_provisional_scene_ids") or []
            ),
            "depends_on_provisional_memory_ids": _unique_strings(
                scene.get("depends_on_provisional_memory_ids") or []
            ),
            "needs_review_reason": _short_text(scene.get("needs_review_reason"), 220),
            "chapter_memory_pack_id": scene.get("chapter_memory_pack_id", ""),
            "scene_memory_pack_id": scene.get("scene_memory_pack_id", ""),
            "active_revision_id": scene.get("active_revision_id", ""),
        }

    def _safe_call_summary(self, call: dict[str, Any]) -> dict[str, Any]:
        return {
            "call_id": call.get("call_id", ""),
            "agent_role": call.get("agent_role", ""),
            "service_name": call.get("service_name", ""),
            "operation_name": call.get("operation_name", ""),
            "request_type": call.get("request_type", ""),
            "provider_type": call.get("provider_type", ""),
            "model_name": call.get("model_name", ""),
            "success": bool(call.get("success")),
            "adapter_success": bool(call.get("adapter_success")),
            "json_parse_success": call.get("json_parse_success"),
            "latency_ms": call.get("latency_ms", 0),
            "error_type": call.get("error_type"),
            "error_message_safe": _short_text(call.get("error_message_safe"), 220),
            "started_at": call.get("started_at", ""),
            "ended_at": call.get("ended_at", ""),
            "local_trace_id": call.get("local_trace_id", ""),
            "token_usage": call.get("token_usage") or {},
        }

    def _safe_error_summary(self, error: dict[str, Any]) -> dict[str, Any]:
        return {
            "error_id": error.get("error_id", ""),
            "call_id": error.get("call_id", ""),
            "stage": error.get("stage", ""),
            "error_type": error.get("error_type", ""),
            "error_message_safe": _short_text(error.get("error_message_safe"), 220),
            "retryable": bool(error.get("retryable")),
            "provider_type": error.get("provider_type", ""),
            "model_name": error.get("model_name", ""),
            "service_name": error.get("service_name", ""),
            "suggested_action": _short_text(error.get("suggested_action"), 220),
            "user_visible_message": _short_text(error.get("user_visible_message"), 220),
            "created_at": error.get("created_at", ""),
        }

    def _scan_for_unsafe_debug_payload(self, value: Any, path: str = "$") -> list[str]:
        issues: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                key_lower = key_text.lower()
                if key_lower in UNSAFE_DEBUG_KEYS:
                    issues.append(f"unsafe_key:{path}.{key_text}")
                issues.extend(self._scan_for_unsafe_debug_payload(item, f"{path}.{key_text}"))
            return issues
        if isinstance(value, list):
            for index, item in enumerate(value):
                issues.extend(self._scan_for_unsafe_debug_payload(item, f"{path}[{index}]"))
            return issues
        if isinstance(value, str):
            if any(marker in value for marker in SECRET_VALUE_MARKERS):
                issues.append(f"secret_value:{path}")
        return issues


def _short_text(value: Any, limit: int = 200) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = " ".join(text.split())
    return compact[:limit]


def _safe_list_text(values: Any, limit: int = 8) -> list[Any]:
    if not isinstance(values, list):
        return []
    result: list[Any] = []
    for value in values[:limit]:
        if isinstance(value, dict):
            result.append(
                {
                    key: _short_text(item, 160) if isinstance(item, str) else item
                    for key, item in value.items()
                    if key not in UNSAFE_DEBUG_KEYS
                }
            )
        else:
            result.append(_short_text(value, 160))
    return result


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
