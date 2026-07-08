from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.background_thinking import ThinkingCandidate
from app.backend.models.pre_modify import PreModifyCandidate
from app.backend.models.scene_candidate_cache import (
    CachedSceneCandidate,
    CandidateCacheInvalidationRecord,
    CandidateCacheInvalidationResponse,
    SceneCandidateCache,
    SceneCandidateCacheSummaryResponse,
)
from app.backend.models.scene_snapshot import SceneVersionSnapshot
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.background_thinking_service import BackgroundThinkingService
from app.backend.services.pre_modify_pipeline_service import PreModifyPipelineService
from app.backend.services.scene_version_snapshot_service import SceneVersionSnapshotService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
MAX_SAFE_TEXT_LENGTH = 700
MAX_SAFE_LABEL_LENGTH = 260
MAX_LIST_ITEMS = 10
CACHES_FILE_NAME = "scene_candidate_caches.json"
CACHED_CANDIDATES_FILE_NAME = "cached_scene_candidates.json"
INVALIDATION_RECORDS_FILE_NAME = "candidate_cache_invalidation_records.json"

THINKING_SUMMARY_KEYS = {
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
PRE_MODIFY_SUMMARY_KEYS = {
    "next_adjustment_focus",
    "continuity_alignment",
    "memory_alignment",
    "information_release_note",
    "target_snapshot_statuses",
}
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


class SceneCandidateCacheService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        background_thinking_service: BackgroundThinkingService | None = None,
        pre_modify_service: PreModifyPipelineService | None = None,
        snapshot_service: SceneVersionSnapshotService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.snapshot_service = snapshot_service or SceneVersionSnapshotService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.background_thinking_service = background_thinking_service or BackgroundThinkingService(
            store=self.store,
            data_dir=self.data_dir,
            snapshot_service=self.snapshot_service,
        )
        self.pre_modify_service = pre_modify_service or PreModifyPipelineService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            snapshot_service=self.snapshot_service,
            background_thinking_service=self.background_thinking_service,
        )
        self.caches_file = self.data_dir / CACHES_FILE_NAME
        self.cached_candidates_file = self.data_dir / CACHED_CANDIDATES_FILE_NAME
        self.invalidations_file = self.data_dir / INVALIDATION_RECORDS_FILE_NAME

    def register_thinking_candidate(self, candidate_id: str) -> CachedSceneCandidate:
        clean_id = str(candidate_id or "").strip()
        if not clean_id:
            raise StorageError("SCENE_CANDIDATE_CACHE_SOURCE_ID_REQUIRED: candidate_id must not be empty.")
        try:
            candidate = self.background_thinking_service.get_candidate(clean_id)
        except StorageError as exc:
            if "THINKING_CANDIDATE_NOT_FOUND" in str(exc):
                raise StorageError("SCENE_CANDIDATE_CACHE_SOURCE_NOT_FOUND: thinking candidate does not exist.") from exc
            raise
        return self._upsert_cached_candidate(self._from_thinking_candidate(candidate))

    def register_pre_modify_candidate(self, candidate_id: str) -> CachedSceneCandidate:
        clean_id = str(candidate_id or "").strip()
        if not clean_id:
            raise StorageError("SCENE_CANDIDATE_CACHE_SOURCE_ID_REQUIRED: candidate_id must not be empty.")
        try:
            candidate = self.pre_modify_service.get_candidate(clean_id)
        except StorageError as exc:
            if "PRE_MODIFY_CANDIDATE_NOT_FOUND" in str(exc):
                raise StorageError("SCENE_CANDIDATE_CACHE_SOURCE_NOT_FOUND: pre-modify candidate does not exist.") from exc
            raise
        return self._upsert_cached_candidate(self._from_pre_modify_candidate(candidate))

    def backfill_from_sources(
        self,
        target_scene_id: str = "",
        chapter_id: str = "",
        limit: int = 200,
    ) -> SceneCandidateCacheSummaryResponse:
        clean_scene_id = str(target_scene_id or "").strip()
        clean_chapter_id = str(chapter_id or "").strip()
        bounded_limit = max(1, min(int(limit or 200), 500))
        for candidate in self.background_thinking_service.list_candidates(limit=bounded_limit):
            if not str(candidate.target_scene_id or "").strip():
                continue
            if clean_scene_id and candidate.target_scene_id != clean_scene_id:
                continue
            if clean_chapter_id and candidate.target_chapter_id != clean_chapter_id:
                continue
            self.register_thinking_candidate(candidate.candidate_id)
        for candidate in self.pre_modify_service.list_candidates(limit=bounded_limit):
            if clean_scene_id and candidate.target_scene_id != clean_scene_id:
                continue
            if clean_chapter_id and candidate.target_chapter_id != clean_chapter_id:
                continue
            self.register_pre_modify_candidate(candidate.candidate_id)
        return self.summary(
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            include_stale=True,
            limit=bounded_limit,
        )

    def get_scene_cache(
        self,
        scene_id: str,
        include_stale: bool = False,
    ) -> SceneCandidateCacheSummaryResponse:
        clean_id = str(scene_id or "").strip()
        if not clean_id:
            raise StorageError("SCENE_CANDIDATE_CACHE_SCENE_ID_REQUIRED: scene_id must not be empty.")
        return self.summary(scene_id=clean_id, include_stale=include_stale)

    def get_chapter_cache(
        self,
        chapter_id: str,
        include_stale: bool = False,
    ) -> SceneCandidateCacheSummaryResponse:
        clean_id = str(chapter_id or "").strip()
        if not clean_id:
            raise StorageError("SCENE_CANDIDATE_CACHE_CHAPTER_ID_REQUIRED: chapter_id must not be empty.")
        return self.summary(chapter_id=clean_id, include_stale=include_stale)

    def get_cached_candidate(self, cached_candidate_id: str) -> CachedSceneCandidate:
        clean_id = str(cached_candidate_id or "").strip()
        for candidate in self._read_cached_candidates():
            if candidate.cached_candidate_id == clean_id:
                self._guard_safe_payload(candidate)
                return candidate
        raise StorageError("SCENE_CANDIDATE_CACHE_CANDIDATE_NOT_FOUND: cached candidate does not exist.")

    def mark_cached_candidate_status(
        self,
        cached_candidate_id: str,
        cache_status: str,
        reason: str = "",
    ) -> CachedSceneCandidate:
        clean_id = str(cached_candidate_id or "").strip()
        clean_status = str(cache_status or "").strip()
        if clean_status not in {"hidden", "archived"}:
            raise StorageError("SCENE_CANDIDATE_CACHE_STATUS_INVALID: only hidden or archived are supported.")
        self._guard_safe_payload(
            {
                "cached_candidate_id": clean_id,
                "cache_status": clean_status,
                "reason": reason,
            }
        )
        candidates = self._read_cached_candidates()
        records = self._read_invalidations()
        timestamp = now_iso()
        updated: list[CachedSceneCandidate] = []
        result: CachedSceneCandidate | None = None
        for candidate in candidates:
            if candidate.cached_candidate_id != clean_id:
                updated.append(candidate)
                continue
            previous_status = candidate.cache_status
            invalidation_type = "manual_archive" if clean_status == "archived" else "manual_hide"
            record = self._new_invalidation_record(
                records,
                candidate,
                invalidation_type=invalidation_type,
                previous_status=previous_status,
                new_status=clean_status,
                affected_snapshot_ids=candidate.based_on_snapshot_ids,
                reason=reason or f"Cached candidate was manually marked {clean_status}.",
            )
            records.append(record)
            result = CachedSceneCandidate(
                **{
                    **model_to_dict(candidate),
                    "cache_status": clean_status,
                    "invalidation_record_ids": _unique_strings(
                        candidate.invalidation_record_ids + [record.invalidation_record_id]
                    ),
                    "stale_reason_refs": _bounded_dicts(
                        candidate.stale_reason_refs
                        + [
                            {
                                "invalidation_record_id": record.invalidation_record_id,
                                "invalidation_type": record.invalidation_type,
                                "reason": record.user_visible_reason,
                            }
                        ]
                    ),
                    "updated_at": timestamp,
                }
            )
            updated.append(result)
        if result is None:
            raise StorageError("SCENE_CANDIDATE_CACHE_CANDIDATE_NOT_FOUND: cached candidate does not exist.")
        caches = self._rebuild_caches(updated)
        self._write_state(caches, updated, records)
        self._guard_safe_payload(result)
        return result

    def invalidate_by_snapshot_ids(
        self,
        snapshot_ids: list[str],
        trigger_invalidation_id: str = "",
        reason: str = "",
    ) -> CandidateCacheInvalidationResponse:
        return self._invalidate_by_snapshot_ids(
            snapshot_ids=snapshot_ids,
            trigger_invalidation_id=trigger_invalidation_id,
            reason=reason,
            invalidation_type="snapshot_invalidated",
        )

    def invalidate_by_ref(
        self,
        changed_ref_type: str,
        changed_ref_id: str,
        trigger_invalidation_id: str = "",
        reason: str = "",
    ) -> CandidateCacheInvalidationResponse:
        snapshots = self.snapshot_service.list_snapshots_using_ref(
            changed_ref_type,
            changed_ref_id,
        )
        return self._invalidate_by_snapshot_ids(
            snapshot_ids=[snapshot.snapshot_id for snapshot in snapshots],
            trigger_invalidation_id=trigger_invalidation_id,
            reason=reason,
            invalidation_type="changed_ref_invalidated",
            changed_ref_type=changed_ref_type,
            changed_ref_id=changed_ref_id,
        )

    def summary(
        self,
        *,
        scene_id: str = "",
        chapter_id: str = "",
        include_stale: bool = False,
        limit: int = 50,
    ) -> SceneCandidateCacheSummaryResponse:
        clean_scene_id = str(scene_id or "").strip()
        clean_chapter_id = str(chapter_id or "").strip()
        bounded_limit = max(1, min(int(limit or 50), 200))
        candidates = self._read_cached_candidates()
        if clean_scene_id:
            candidates = [
                candidate for candidate in candidates if candidate.target_scene_id == clean_scene_id
            ]
        if clean_chapter_id:
            candidates = [
                candidate for candidate in candidates if candidate.target_chapter_id == clean_chapter_id
            ]
        all_candidates = list(candidates)
        if not include_stale:
            candidates = [
                candidate for candidate in candidates if candidate.cache_status == "active"
            ]
        candidates = sorted(candidates, key=lambda item: item.updated_at, reverse=True)[:bounded_limit]
        caches = self._matching_caches(clean_scene_id, clean_chapter_id)
        invalidations = self._read_invalidations()
        if clean_scene_id:
            invalidations = [
                record for record in invalidations if any(
                    candidate.cached_candidate_id == record.cached_candidate_id
                    for candidate in all_candidates
                )
            ]
        if clean_chapter_id:
            invalidations = [
                record for record in invalidations if any(
                    candidate.cached_candidate_id == record.cached_candidate_id
                    for candidate in all_candidates
                )
            ]
        response = SceneCandidateCacheSummaryResponse(
            project_id=LOCAL_PROJECT_ID,
            scene_id=clean_scene_id,
            chapter_id=clean_chapter_id,
            cache_count=len(caches),
            candidate_count=len(all_candidates),
            active_candidate_count=sum(1 for item in all_candidates if item.cache_status == "active"),
            stale_candidate_count=sum(1 for item in all_candidates if item.cache_status == "stale"),
            hidden_candidate_count=sum(1 for item in all_candidates if item.cache_status == "hidden"),
            archived_candidate_count=sum(1 for item in all_candidates if item.cache_status == "archived"),
            candidate_counts_by_source_type=self._counts(all_candidates, "source_candidate_type"),
            candidate_counts_by_status=self._counts(all_candidates, "cache_status"),
            recent_cache_ids=[cache.cache_id for cache in caches[:MAX_LIST_ITEMS]],
            recent_cached_candidate_ids=[
                candidate.cached_candidate_id for candidate in candidates[:MAX_LIST_ITEMS]
            ],
            recent_source_candidate_ids=[
                candidate.source_candidate_id for candidate in candidates[:MAX_LIST_ITEMS]
            ],
            recent_invalidation_ids=[
                record.invalidation_record_id
                for record in sorted(invalidations, key=lambda item: item.created_at, reverse=True)[:MAX_LIST_ITEMS]
            ],
            caches=caches[:MAX_LIST_ITEMS],
            candidates=candidates,
            recent_candidates=[self._candidate_debug_row(candidate) for candidate in candidates[:MAX_LIST_ITEMS]],
        )
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def debug_summary(self) -> dict[str, Any]:
        candidates = self._read_cached_candidates()
        caches = self._read_caches()
        invalidations = self._read_invalidations()
        payload = {
            "available": True,
            "cache_count": len(caches),
            "candidate_count": len(candidates),
            "active_candidate_count": sum(1 for item in candidates if item.cache_status == "active"),
            "stale_candidate_count": sum(1 for item in candidates if item.cache_status == "stale"),
            "hidden_candidate_count": sum(1 for item in candidates if item.cache_status == "hidden"),
            "archived_candidate_count": sum(1 for item in candidates if item.cache_status == "archived"),
            "candidate_counts_by_source_type": self._counts(candidates, "source_candidate_type"),
            "candidate_counts_by_status": self._counts(candidates, "cache_status"),
            "recent_cache_ids": [cache.cache_id for cache in caches[:MAX_LIST_ITEMS]],
            "recent_cached_candidate_ids": [
                candidate.cached_candidate_id
                for candidate in sorted(candidates, key=lambda item: item.updated_at, reverse=True)[:MAX_LIST_ITEMS]
            ],
            "recent_source_candidate_ids": [
                candidate.source_candidate_id
                for candidate in sorted(candidates, key=lambda item: item.updated_at, reverse=True)[:MAX_LIST_ITEMS]
            ],
            "recent_invalidation_ids": [
                record.invalidation_record_id
                for record in sorted(invalidations, key=lambda item: item.created_at, reverse=True)[:MAX_LIST_ITEMS]
            ],
            "recent_candidates": [
                self._candidate_debug_row(candidate)
                for candidate in sorted(candidates, key=lambda item: item.updated_at, reverse=True)[:MAX_LIST_ITEMS]
            ],
            "storage_files": [
                CACHES_FILE_NAME,
                CACHED_CANDIDATES_FILE_NAME,
                INVALIDATION_RECORDS_FILE_NAME,
            ],
        }
        payload["safety"] = self._safety(payload)
        self._guard_safe_payload(payload)
        return payload

    def _upsert_cached_candidate(self, incoming: CachedSceneCandidate) -> CachedSceneCandidate:
        candidates = self._read_cached_candidates()
        records = self._read_invalidations()
        timestamp = now_iso()
        updated: list[CachedSceneCandidate] = []
        result = incoming
        replaced = False
        for existing in candidates:
            if existing.cached_candidate_id != incoming.cached_candidate_id:
                updated.append(existing)
                continue
            result = self._merge_existing_candidate(existing, incoming, timestamp, records)
            updated.append(result)
            replaced = True
        if not replaced:
            updated.append(incoming)
        caches = self._rebuild_caches(updated)
        self._write_state(caches, updated, records)
        self._guard_safe_payload(result)
        return result

    def _merge_existing_candidate(
        self,
        existing: CachedSceneCandidate,
        incoming: CachedSceneCandidate,
        timestamp: str,
        records: list[CandidateCacheInvalidationRecord],
    ) -> CachedSceneCandidate:
        cache_status = incoming.cache_status
        if existing.cache_status in {"hidden", "archived"} and incoming.cache_status == "active":
            cache_status = existing.cache_status
        if existing.cache_status == "stale" and incoming.cache_status == "active" and existing.stale_reason_refs:
            cache_status = "stale"
        invalidation_ids = _unique_strings(
            existing.invalidation_record_ids + incoming.invalidation_record_ids
        )
        stale_refs = _bounded_dicts(existing.stale_reason_refs + incoming.stale_reason_refs)
        merged = CachedSceneCandidate(
            **{
                **model_to_dict(incoming),
                "cache_status": cache_status,
                "created_at": existing.created_at,
                "updated_at": timestamp,
                "stale_reason_refs": stale_refs,
                "invalidation_record_ids": invalidation_ids,
            }
        )
        if existing.source_candidate_status != incoming.source_candidate_status and existing.cache_status != merged.cache_status:
            record = self._new_invalidation_record(
                records,
                merged,
                invalidation_type="source_candidate_status_changed",
                previous_status=existing.cache_status,
                new_status=merged.cache_status,
                affected_snapshot_ids=merged.based_on_snapshot_ids,
                reason=f"Source candidate status changed from {existing.source_candidate_status} to {incoming.source_candidate_status}.",
            )
            records.append(record)
            merged.invalidation_record_ids = _unique_strings(
                merged.invalidation_record_ids + [record.invalidation_record_id]
            )
            merged.stale_reason_refs = _bounded_dicts(
                merged.stale_reason_refs
                + [
                    {
                        "invalidation_record_id": record.invalidation_record_id,
                        "invalidation_type": record.invalidation_type,
                        "reason": record.user_visible_reason,
                    }
                ]
            )
        return merged

    def _from_thinking_candidate(self, candidate: ThinkingCandidate) -> CachedSceneCandidate:
        timestamp = now_iso()
        cached_id = f"cached_thinking_candidate_{candidate.candidate_id}"
        target_scene_id = str(candidate.target_scene_id or "").strip()
        if not target_scene_id:
            raise StorageError(
                "SCENE_CANDIDATE_CACHE_TARGET_SCENE_REQUIRED: thinking candidate has no explicit target_scene_id."
            )
        cached = CachedSceneCandidate(
            cached_candidate_id=cached_id,
            cache_id=self._cache_id(target_scene_id),
            source_candidate_type="thinking_candidate",
            source_candidate_id=candidate.candidate_id,
            source_task_id=candidate.task_id,
            target_scene_id=target_scene_id,
            target_chapter_id=candidate.target_chapter_id,
            target_scene_index=candidate.target_scene_index,
            based_on_snapshot_ids=_unique_strings(candidate.based_on_snapshot_ids),
            source_snapshot_refs=self._snapshot_refs(candidate.based_on_snapshot_ids),
            source_candidate_status=candidate.status,
            cache_status=self._thinking_cache_status(candidate.status),
            safe_summary=self._safe_summary(candidate.safe_summary, THINKING_SUMMARY_KEYS),
            preview_label=_short_text(
                candidate.safe_summary.get("next_scene_focus")
                or candidate.safe_summary.get("continuity_focus")
                or candidate.candidate_id,
                MAX_SAFE_LABEL_LENGTH,
            ),
            user_visible_reason="Background thinking candidate cached as planning evidence only.",
            risk_warnings=_safe_string_list(candidate.risk_warnings),
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._guard_safe_payload(cached)
        return cached

    def _from_pre_modify_candidate(self, candidate: PreModifyCandidate) -> CachedSceneCandidate:
        timestamp = now_iso()
        cached = CachedSceneCandidate(
            cached_candidate_id=f"cached_pre_modify_candidate_{candidate.candidate_id}",
            cache_id=self._cache_id(candidate.target_scene_id),
            source_candidate_type="pre_modify_candidate",
            source_candidate_id=candidate.candidate_id,
            source_preview_id=candidate.source_preview_id,
            target_scene_id=candidate.target_scene_id,
            target_chapter_id=candidate.target_chapter_id,
            target_scene_index=candidate.target_scene_index,
            based_on_snapshot_ids=_unique_strings(
                candidate.target_snapshot_ids + candidate.affected_snapshot_ids
            ),
            source_snapshot_refs=self._snapshot_refs(
                candidate.target_snapshot_ids + candidate.affected_snapshot_ids
            ),
            source_candidate_status=candidate.status,
            cache_status=self._pre_modify_cache_status(candidate.status),
            safe_summary=self._safe_summary(candidate.safe_summary, PRE_MODIFY_SUMMARY_KEYS),
            preview_label=_short_text(candidate.adjustment_summary, MAX_SAFE_LABEL_LENGTH),
            user_visible_reason=_short_text(candidate.user_visible_reason, MAX_SAFE_LABEL_LENGTH),
            risk_warnings=_safe_string_list(candidate.risk_warnings),
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._guard_safe_payload(cached)
        return cached

    def _invalidate_by_snapshot_ids(
        self,
        *,
        snapshot_ids: list[str],
        trigger_invalidation_id: str = "",
        reason: str = "",
        invalidation_type: str,
        changed_ref_type: str = "",
        changed_ref_id: str = "",
    ) -> CandidateCacheInvalidationResponse:
        clean_snapshot_ids = _unique_strings(snapshot_ids)
        candidates = self._read_cached_candidates()
        records = self._read_invalidations()
        if not clean_snapshot_ids:
            response = CandidateCacheInvalidationResponse(
                invalidation_records=[],
                stale_cached_candidate_ids=[],
                affected_snapshot_ids=[],
                count=0,
            )
            response.safety = self._safety(model_to_dict(response))
            self._guard_safe_payload(response)
            return response
        updated: list[CachedSceneCandidate] = []
        new_records: list[CandidateCacheInvalidationRecord] = []
        timestamp = now_iso()
        snapshot_set = set(clean_snapshot_ids)
        for candidate in candidates:
            affected_ids = sorted(snapshot_set.intersection(candidate.based_on_snapshot_ids))
            if not affected_ids or candidate.cache_status in {"hidden", "archived"}:
                updated.append(candidate)
                continue
            previous_status = candidate.cache_status
            record = self._new_invalidation_record(
                records + new_records,
                candidate,
                invalidation_type=invalidation_type,
                previous_status=previous_status,
                new_status="stale",
                affected_snapshot_ids=affected_ids,
                trigger_snapshot_id=affected_ids[0],
                trigger_invalidation_id=trigger_invalidation_id,
                changed_ref_type=changed_ref_type,
                changed_ref_id=changed_ref_id,
                reason=reason or "Cached candidate was marked stale by explicit snapshot evidence.",
            )
            new_records.append(record)
            candidate = CachedSceneCandidate(
                **{
                    **model_to_dict(candidate),
                    "cache_status": "stale",
                    "stale_reason_refs": _bounded_dicts(
                        candidate.stale_reason_refs
                        + [
                            {
                                "invalidation_record_id": record.invalidation_record_id,
                                "invalidation_type": record.invalidation_type,
                                "trigger_snapshot_id": record.trigger_snapshot_id,
                                "trigger_invalidation_id": record.trigger_invalidation_id,
                                "changed_ref_type": record.changed_ref_type,
                                "changed_ref_id": record.changed_ref_id,
                                "reason": record.user_visible_reason,
                            }
                        ]
                    ),
                    "invalidation_record_ids": _unique_strings(
                        candidate.invalidation_record_ids + [record.invalidation_record_id]
                    ),
                    "updated_at": timestamp,
                }
            )
            updated.append(candidate)
        records.extend(new_records)
        caches = self._rebuild_caches(updated)
        self._write_state(caches, updated, records)
        response = CandidateCacheInvalidationResponse(
            invalidation_records=new_records,
            stale_cached_candidate_ids=_unique_strings(
                [record.cached_candidate_id for record in new_records]
            ),
            affected_snapshot_ids=clean_snapshot_ids,
            count=len(new_records),
        )
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def _new_invalidation_record(
        self,
        existing_records: list[CandidateCacheInvalidationRecord],
        candidate: CachedSceneCandidate,
        *,
        invalidation_type: str,
        previous_status: str,
        new_status: str,
        affected_snapshot_ids: list[str],
        trigger_snapshot_id: str = "",
        trigger_invalidation_id: str = "",
        changed_ref_type: str = "",
        changed_ref_id: str = "",
        reason: str = "",
    ) -> CandidateCacheInvalidationRecord:
        return CandidateCacheInvalidationRecord(
            invalidation_record_id=f"candidate_cache_invalidation_{len(existing_records) + 1:03d}",
            cache_id=candidate.cache_id,
            cached_candidate_id=candidate.cached_candidate_id,
            source_candidate_type=candidate.source_candidate_type,
            source_candidate_id=candidate.source_candidate_id,
            invalidation_type=invalidation_type,
            trigger_snapshot_id=_short_text(trigger_snapshot_id, MAX_SAFE_LABEL_LENGTH),
            trigger_invalidation_id=_short_text(trigger_invalidation_id, MAX_SAFE_LABEL_LENGTH),
            changed_ref_type=_short_text(changed_ref_type, MAX_SAFE_LABEL_LENGTH),
            changed_ref_id=_short_text(changed_ref_id, MAX_SAFE_LABEL_LENGTH),
            affected_snapshot_ids=_unique_strings(affected_snapshot_ids),
            previous_status=previous_status,
            new_status=new_status,
            user_visible_reason=_short_text(reason, MAX_SAFE_LABEL_LENGTH),
            created_at=now_iso(),
        )

    def _rebuild_caches(self, candidates: list[CachedSceneCandidate]) -> list[SceneCandidateCache]:
        existing = {cache.cache_id: cache for cache in self._read_caches()}
        timestamp = now_iso()
        groups: dict[str, list[CachedSceneCandidate]] = {}
        for candidate in candidates:
            if not candidate.target_scene_id:
                continue
            groups.setdefault(candidate.cache_id, []).append(candidate)
        caches: list[SceneCandidateCache] = []
        for cache_id, items in groups.items():
            sorted_items = sorted(items, key=lambda item: item.updated_at, reverse=True)
            latest = sorted_items[0] if sorted_items else None
            previous = existing.get(cache_id)
            caches.append(
                SceneCandidateCache(
                    cache_id=cache_id,
                    chapter_id=latest.target_chapter_id if latest else "",
                    scene_id=latest.target_scene_id if latest else "",
                    target_scene_index=latest.target_scene_index if latest else None,
                    cached_candidate_ids=[item.cached_candidate_id for item in sorted_items],
                    active_candidate_count=sum(1 for item in items if item.cache_status == "active"),
                    stale_candidate_count=sum(1 for item in items if item.cache_status == "stale"),
                    hidden_candidate_count=sum(1 for item in items if item.cache_status == "hidden"),
                    archived_candidate_count=sum(1 for item in items if item.cache_status == "archived"),
                    candidate_counts_by_source_type=self._counts(items, "source_candidate_type"),
                    candidate_counts_by_status=self._counts(items, "cache_status"),
                    latest_candidate_id=latest.cached_candidate_id if latest else "",
                    latest_candidate_at=latest.updated_at if latest else "",
                    created_at=previous.created_at if previous else timestamp,
                    updated_at=timestamp,
                )
            )
        return sorted(caches, key=lambda item: item.updated_at, reverse=True)

    def _matching_caches(
        self,
        scene_id: str,
        chapter_id: str,
    ) -> list[SceneCandidateCache]:
        caches = self._read_caches()
        if scene_id:
            caches = [cache for cache in caches if cache.scene_id == scene_id]
        if chapter_id:
            caches = [cache for cache in caches if cache.chapter_id == chapter_id]
        return sorted(caches, key=lambda item: item.updated_at, reverse=True)

    def _snapshot_refs(self, snapshot_ids: list[str]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for snapshot_id in _unique_strings(snapshot_ids)[:MAX_LIST_ITEMS]:
            try:
                snapshot = self.snapshot_service.get_snapshot(snapshot_id)
                refs.append(self._snapshot_ref(snapshot))
            except StorageError:
                refs.append(
                    {
                        "snapshot_id": _short_text(snapshot_id, MAX_SAFE_LABEL_LENGTH),
                        "status": "missing",
                    }
                )
        return _bounded_dicts(refs)

    def _snapshot_ref(self, snapshot: SceneVersionSnapshot) -> dict[str, Any]:
        return self._sanitize_payload(
            {
                "snapshot_id": snapshot.snapshot_id,
                "target_scene_id": snapshot.target_scene_id or snapshot.subject_id,
                "chapter_id": snapshot.chapter_id,
                "status": snapshot.status,
                "snapshot_type": snapshot.snapshot_type,
                "snapshot_hash": snapshot.snapshot_hash,
                "safe_label": _short_text(
                    snapshot.safe_summary.get("goal_summary")
                    or snapshot.safe_summary.get("synopsis_summary")
                    or snapshot.snapshot_type,
                    MAX_SAFE_LABEL_LENGTH,
                ),
            }
        )

    def _write_state(
        self,
        caches: list[SceneCandidateCache],
        candidates: list[CachedSceneCandidate],
        invalidations: list[CandidateCacheInvalidationRecord],
    ) -> None:
        payload = {
            "caches": [model_to_dict(item) for item in caches],
            "candidates": [model_to_dict(item) for item in candidates],
            "invalidations": [model_to_dict(item) for item in invalidations],
        }
        self._guard_safe_payload(payload)
        self.store.write(self.caches_file, payload["caches"])
        self.store.write(self.cached_candidates_file, payload["candidates"])
        self.store.write(self.invalidations_file, payload["invalidations"])

    def _read_caches(self) -> list[SceneCandidateCache]:
        if not self.store.exists(self.caches_file):
            return []
        result: list[SceneCandidateCache] = []
        for item in self.store.read_list(self.caches_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(SceneCandidateCache(**item))
            except ValidationError as exc:
                raise StorageError("SCENE_CANDIDATE_CACHE_SCHEMA_INVALID: cache JSON schema is invalid.") from exc
        return result

    def _read_cached_candidates(self) -> list[CachedSceneCandidate]:
        if not self.store.exists(self.cached_candidates_file):
            return []
        result: list[CachedSceneCandidate] = []
        for item in self.store.read_list(self.cached_candidates_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(CachedSceneCandidate(**item))
            except ValidationError as exc:
                raise StorageError("SCENE_CANDIDATE_CACHE_SCHEMA_INVALID: candidate JSON schema is invalid.") from exc
        return result

    def _read_invalidations(self) -> list[CandidateCacheInvalidationRecord]:
        if not self.store.exists(self.invalidations_file):
            return []
        result: list[CandidateCacheInvalidationRecord] = []
        for item in self.store.read_list(self.invalidations_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(CandidateCacheInvalidationRecord(**item))
            except ValidationError as exc:
                raise StorageError("SCENE_CANDIDATE_CACHE_SCHEMA_INVALID: invalidation JSON schema is invalid.") from exc
        return result

    def _cache_id(self, scene_id: str) -> str:
        clean_id = _short_text(scene_id, MAX_SAFE_LABEL_LENGTH)
        if not clean_id:
            raise StorageError("SCENE_CANDIDATE_CACHE_TARGET_SCENE_REQUIRED: target scene id must not be empty.")
        return f"scene_candidate_cache_scene_{clean_id}"

    def _thinking_cache_status(self, status: str) -> str:
        mapping = {
            "ready": "active",
            "stale": "stale",
            "superseded": "stale",
            "rejected": "hidden",
        }
        return mapping.get(str(status or "").strip(), "hidden")

    def _pre_modify_cache_status(self, status: str) -> str:
        mapping = {
            "ready": "active",
            "warning_only": "active",
            "blocked": "active",
            "stale": "stale",
            "superseded": "stale",
        }
        return mapping.get(str(status or "").strip(), "stale")

    def _safe_summary(self, summary: dict[str, Any], allowed_keys: set[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        source = summary if isinstance(summary, dict) else {}
        for key in sorted(allowed_keys):
            if key not in source:
                continue
            value = source.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                result[key] = _short_text(value, MAX_SAFE_TEXT_LENGTH) if isinstance(value, str) else value
            elif isinstance(value, list):
                result[key] = _safe_string_list(value)
            elif isinstance(value, dict):
                result[key] = self._sanitize_payload(value)
        return self._sanitize_payload(result)

    def _candidate_debug_row(self, candidate: CachedSceneCandidate) -> dict[str, Any]:
        return self._sanitize_payload(
            {
                "cached_candidate_id": candidate.cached_candidate_id,
                "source_candidate_type": candidate.source_candidate_type,
                "source_candidate_id": candidate.source_candidate_id,
                "target_scene_id": candidate.target_scene_id,
                "target_chapter_id": candidate.target_chapter_id,
                "target_scene_index": candidate.target_scene_index,
                "cache_status": candidate.cache_status,
                "source_candidate_status": candidate.source_candidate_status,
                "preview_label": candidate.preview_label,
                "user_visible_reason": candidate.user_visible_reason,
                "risk_warnings": candidate.risk_warnings[:MAX_LIST_ITEMS],
                "based_on_snapshot_ids": candidate.based_on_snapshot_ids[:MAX_LIST_ITEMS],
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
                "SCENE_CANDIDATE_CACHE_UNSAFE_PAYLOAD_BLOCKED: "
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


def _bounded_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in values[:MAX_LIST_ITEMS]:
        if isinstance(item, dict):
            result.append({str(key): item[key] for key in list(item.keys())[:MAX_LIST_ITEMS]})
    return result
