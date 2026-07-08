import hashlib
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.memory_pack import ChapterMemoryPack, MemoryPackSourceRef, SceneMemoryPack
from app.backend.models.memory_record import MemoryRecord
from app.backend.models.memory_retrieval_promotion import (
    ChapterMemoryPromotionCandidate,
    ChapterMemoryPromotionDecision,
    ChapterMemoryPromotionReport,
    MemoryCanonicalKey,
    MemoryRetrievalUsageRecord,
    TieredMemoryRetrievalPolicy,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import current_story_workspace_project_id
from app.backend.services.chapter_memory_service import ChapterMemoryService
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class MemoryCanonicalKeyService:
    def canonical_key(self, ref: MemoryPackSourceRef) -> MemoryCanonicalKey:
        memory_id = str(ref.memory_id or "").strip()
        source_type = str(ref.source_object_type or "").strip()
        source_id = str(ref.source_object_id or "").strip()
        memory_type = str(ref.memory_type or "").strip()
        if memory_id:
            return MemoryCanonicalKey(
                canonical_key=f"memory:{memory_id}",
                memory_id=memory_id,
                source_object_type=source_type,
                source_object_id=source_id,
                memory_type=memory_type,
                stable=True,
                strategy="memory_id",
            )
        if source_type and source_id:
            return MemoryCanonicalKey(
                canonical_key=f"{source_type.casefold()}:{source_id}",
                memory_id="",
                source_object_type=source_type,
                source_object_id=source_id,
                memory_type=memory_type,
                stable=True,
                strategy="source_object_ref",
            )
        summary = _safe_text(ref.summary, 160)
        keywords = "|".join(sorted(_unique([keyword.casefold() for keyword in ref.keywords])))
        if summary or keywords:
            digest = _hash_text(f"{memory_type}|{summary.casefold()}|{keywords}", 16)
            return MemoryCanonicalKey(
                canonical_key=f"derived:{digest}",
                memory_id="",
                source_object_type=source_type,
                source_object_id=source_id,
                memory_type=memory_type,
                stable=False,
                strategy="derived_summary_hash",
            )
        digest = _hash_text(repr(model_to_dict(ref)), 16)
        return MemoryCanonicalKey(
            canonical_key=f"unstable:{digest}",
            memory_id="",
            source_object_type=source_type,
            source_object_id=source_id,
            memory_type=memory_type,
            stable=False,
            strategy="unstable_payload_hash",
        )


class TieredMemoryRetrievalPolicyService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.policy_file = self.data_dir / "tiered_memory_retrieval_policy.json"

    def get_policy(self, persist_if_missing: bool = True) -> TieredMemoryRetrievalPolicy:
        if self.store.exists(self.policy_file):
            data = self.store.read(self.policy_file)
            try:
                return TieredMemoryRetrievalPolicy(**data)
            except ValidationError as exc:
                raise StorageError("TieredMemoryRetrievalPolicy JSON schema is invalid.") from exc
        timestamp = utc_now()
        policy = TieredMemoryRetrievalPolicy(
            project_id=self._current_project_id(),
            created_at=timestamp,
            updated_at=timestamp,
        )
        if persist_if_missing:
            self.store.write(self.policy_file, model_to_dict(policy))
        return policy

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback="local_project",
        )


class MemoryRetrievalUsageService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        canonical_key_service: MemoryCanonicalKeyService | None = None,
        policy_service: TieredMemoryRetrievalPolicyService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.canonical_key_service = canonical_key_service or MemoryCanonicalKeyService()
        self.policy_service = policy_service or TieredMemoryRetrievalPolicyService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.usage_file = self.data_dir / "memory_retrieval_usage_records.json"

    def record_scene_retrieval_usage(
        self,
        scene_pack: SceneMemoryPack,
        retrieved_by: str = "SceneMemoryService",
        retrieval_reason: str = "scene_pack_build",
    ) -> list[MemoryRetrievalUsageRecord]:
        if not scene_pack.active_character_ids:
            return []
        policy = self.policy_service.get_policy()
        recorded: list[MemoryRetrievalUsageRecord] = []
        normal_buckets = _unique(
            [
                *policy.normal_context_buckets,
                "continuity_anchor_context",
            ]
        )
        for bucket in normal_buckets:
            for ref in getattr(scene_pack, bucket, []) or []:
                record = self._record_ref(
                    scene_pack,
                    ref,
                    bucket,
                    blocked_bucket=False,
                    retrieved_by=retrieved_by,
                    retrieval_reason=retrieval_reason,
                )
                if record is not None:
                    recorded.append(record)
        forbidden_bucket = policy.forbidden_context_bucket
        for ref in getattr(scene_pack, forbidden_bucket, []) or []:
            record = self._record_ref(
                scene_pack,
                ref,
                forbidden_bucket,
                blocked_bucket=True,
                retrieved_by=retrieved_by,
                retrieval_reason=retrieval_reason,
            )
            if record is not None:
                recorded.append(record)
        return recorded

    def list_usage(
        self,
        chapter_id: str | None = None,
    ) -> list[MemoryRetrievalUsageRecord]:
        records = self._read_usage_records()
        if chapter_id:
            records = [record for record in records if record.chapter_id == chapter_id]
        return sorted(
            records,
            key=lambda record: (
                record.chapter_id,
                record.canonical_key,
                record.usage_record_id,
            ),
        )

    def get_usage_record(self, usage_record_id: str) -> MemoryRetrievalUsageRecord | None:
        for record in self._read_usage_records():
            if record.usage_record_id == usage_record_id:
                return record
        return None

    def mark_promoted(
        self,
        usage_record_id: str,
        promotion_candidate_id: str,
    ) -> MemoryRetrievalUsageRecord | None:
        records = self._read_usage_records()
        changed = False
        updated: list[MemoryRetrievalUsageRecord] = []
        target: MemoryRetrievalUsageRecord | None = None
        timestamp = utc_now()
        for record in records:
            if record.usage_record_id == usage_record_id:
                record.promoted_to_chapter_pack = True
                record.promotion_candidate_id = promotion_candidate_id
                record.promoted_at = record.promoted_at or timestamp
                record.last_retrieved_at = timestamp
                changed = True
                target = record
            updated.append(record)
        if changed:
            self._write_usage_records(updated)
        return target

    def _record_ref(
        self,
        scene_pack: SceneMemoryPack,
        ref: MemoryPackSourceRef,
        bucket: str,
        *,
        blocked_bucket: bool,
        retrieved_by: str,
        retrieval_reason: str,
    ) -> MemoryRetrievalUsageRecord | None:
        canonical = self.canonical_key_service.canonical_key(ref)
        memory = self._memory_record(ref.memory_id)
        related_character_ids = _unique(
            memory.character_ids if memory is not None else []
        )
        active_ids = _unique(scene_pack.active_character_ids)
        block_reason = "none"
        blocked = False
        if related_character_ids and not set(related_character_ids).intersection(active_ids):
            blocked = True
            block_reason = "unselected_character_memory"
        if blocked_bucket:
            blocked = True
            block_reason = "forbidden_or_conflict_context"
        status = str((memory.status if memory is not None else ref.status) or "active")
        if status != "active":
            blocked = True
            if block_reason == "none":
                block_reason = "inactive_memory_status"
        if not canonical.stable:
            blocked = True
            if block_reason == "none":
                block_reason = "unstable_source_identity"

        now = utc_now()
        scene_key = self._scene_key(scene_pack)
        usage_record_id = self._usage_record_id(
            scene_pack.chapter_id,
            canonical.canonical_key,
            retrieved_by,
        )
        records = self._read_usage_records()
        existing = next(
            (record for record in records if record.usage_record_id == usage_record_id),
            None,
        )
        if existing is None:
            existing = MemoryRetrievalUsageRecord(
                usage_record_id=usage_record_id,
                project_id=scene_pack.project_id,
                chapter_id=scene_pack.chapter_id,
                canonical_key=canonical.canonical_key,
                memory_id=canonical.memory_id or str(ref.memory_id or ""),
                source_object_type=canonical.source_object_type
                or str(ref.source_object_type or ""),
                source_object_id=canonical.source_object_id or str(ref.source_object_id or ""),
                memory_type=canonical.memory_type or str(ref.memory_type or "event"),
                status="blocked" if blocked else "active",
                importance=str((memory.importance if memory is not None else ref.importance) or "medium"),
                safe_summary=_safe_text(
                    (memory.summary if memory is not None else ref.summary),
                    240,
                ),
                scene_id=str(scene_pack.scene_id or ""),
                scene_index=scene_pack.scene_index,
                retrieved_by=retrieved_by,
                retrieval_reason=retrieval_reason,
                source_scene_keys=[],
                retrieval_count_in_chapter=0,
                context_buckets_seen=[],
                matched_by=_unique(ref.matched_by),
                active_character_ids_at_retrieval=active_ids,
                related_character_ids=related_character_ids,
                memory_status=status,
                memory_importance=str(
                    (memory.importance if memory is not None else ref.importance)
                    or "medium"
                ),
                blocked_from_normal_promotion=blocked,
                block_reason=block_reason,
                first_retrieved_at=now,
                last_retrieved_at=now,
            )
        else:
            existing.status = "blocked" if blocked or existing.blocked_from_normal_promotion else "active"
            existing.blocked_from_normal_promotion = (
                existing.blocked_from_normal_promotion or blocked
            )
            if existing.block_reason == "none" and block_reason != "none":
                existing.block_reason = block_reason
            existing.safe_summary = existing.safe_summary or _safe_text(ref.summary, 240)
            existing.importance = existing.importance or str(ref.importance or "medium")
            existing.scene_id = str(scene_pack.scene_id or existing.scene_id or "")
            existing.scene_index = int(scene_pack.scene_index or existing.scene_index or 0)
            existing.retrieved_by = retrieved_by
            existing.retrieval_reason = retrieval_reason
            existing.memory_status = existing.memory_status or status
            existing.memory_importance = existing.memory_importance or str(
                ref.importance or "medium"
            )
            existing.active_character_ids_at_retrieval = _unique(
                [*existing.active_character_ids_at_retrieval, *active_ids]
            )
            existing.related_character_ids = _unique(
                [*existing.related_character_ids, *related_character_ids]
            )
            existing.matched_by = _unique([*existing.matched_by, *ref.matched_by])
            existing.last_retrieved_at = now

        existing.context_buckets_seen = _unique([*existing.context_buckets_seen, bucket])
        if scene_key not in existing.source_scene_keys:
            existing.source_scene_keys.append(scene_key)
        existing.source_scene_keys = _unique(existing.source_scene_keys)
        existing.retrieval_count_in_chapter = len(existing.source_scene_keys)
        self._upsert_usage_record(existing)
        return existing

    def _memory_record(self, memory_id: str) -> MemoryRecord | None:
        memory_id = str(memory_id or "").strip()
        if not memory_id:
            return None
        raw = self.repositories.memory.get_by_id(memory_id)
        if not raw:
            return None
        try:
            return MemoryRecord(**raw)
        except ValidationError:
            return None

    def _read_usage_records(self) -> list[MemoryRetrievalUsageRecord]:
        return _read_model_list(self.store, self.usage_file, MemoryRetrievalUsageRecord)

    def _write_usage_records(self, records: list[MemoryRetrievalUsageRecord]) -> None:
        self.store.write(self.usage_file, [model_to_dict(record) for record in records])

    def _upsert_usage_record(self, record: MemoryRetrievalUsageRecord) -> None:
        records = self._read_usage_records()
        updated: list[MemoryRetrievalUsageRecord] = []
        replaced = False
        for existing in records:
            if existing.usage_record_id == record.usage_record_id:
                updated.append(record)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(record)
        self._write_usage_records(updated)

    def _usage_record_id(
        self,
        chapter_id: str,
        canonical_key: str,
        retrieved_by: str,
    ) -> str:
        return f"usage_{_slug(chapter_id)}_{_hash_text(f'{canonical_key}|{retrieved_by}', 12)}"

    def _scene_key(self, scene_pack: SceneMemoryPack) -> str:
        if scene_pack.scene_id:
            return f"scene:{scene_pack.scene_id}"
        return f"scene_index:{scene_pack.chapter_id}:{scene_pack.scene_index}"


class ChapterMemoryPackPromotionBridge:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        chapter_memory_service: ChapterMemoryService | None = None,
        canonical_key_service: MemoryCanonicalKeyService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.chapter_memory_service = chapter_memory_service or ChapterMemoryService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.canonical_key_service = canonical_key_service or MemoryCanonicalKeyService()

    def promote_reference(
        self,
        *,
        chapter_id: str,
        ref: MemoryPackSourceRef,
        canonical_key: str,
        promotion_candidate_id: str,
        target_context_bucket: str,
    ) -> tuple[str, bool]:
        pack = self.chapter_memory_service.get_active_chapter_pack(chapter_id)
        if pack is None:
            pack = self.chapter_memory_service.build_current_chapter_pack(chapter_id)
        if self._ref_already_present(pack, canonical_key):
            return pack.chapter_memory_pack_id, False

        timestamp = utc_now()
        new_pack = pack.copy(deep=True)
        new_pack.chapter_memory_pack_id = (
            f"chapter_pack_m5_{_slug(chapter_id)}_{_hash_text(canonical_key, 10)}"
        )
        new_pack.status = "active"
        new_pack.updated_at = timestamp
        new_pack.created_at = timestamp
        new_pack.included_memory_ids = _unique([*new_pack.included_memory_ids, ref.memory_id])
        ref.reason = _join_reason(ref.reason, f"m5_reference_promotion:{promotion_candidate_id}")
        getattr(new_pack, target_context_bucket).append(ref)
        signature = dict(new_pack.source_query_signature or {})
        promotions = list(signature.get("m5_reference_promotions") or [])
        promotions.append(
            {
                "promotion_candidate_id": promotion_candidate_id,
                "canonical_key": canonical_key,
                "memory_id": ref.memory_id,
                "target_context_bucket": target_context_bucket,
                "reference_only": True,
                "creates_new_fact": False,
                "copies_full_text": False,
                "promoted_at": timestamp,
            }
        )
        signature["m5_reference_promotions"] = promotions
        signature["promotion_is_reference_only"] = True
        signature["creates_new_fact"] = False
        signature["copies_full_text"] = False
        new_pack.source_query_signature = signature
        self.chapter_memory_service._persist_pack(new_pack)
        return new_pack.chapter_memory_pack_id, True

    def _ref_already_present(self, pack: ChapterMemoryPack, canonical_key: str) -> bool:
        for ref in _chapter_pack_refs(pack):
            if self.canonical_key_service.canonical_key(ref).canonical_key == canonical_key:
                return True
        return False


class ChapterMemoryPromotionService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        usage_service: MemoryRetrievalUsageService | None = None,
        policy_service: TieredMemoryRetrievalPolicyService | None = None,
        bridge: ChapterMemoryPackPromotionBridge | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.policy_service = policy_service or TieredMemoryRetrievalPolicyService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.usage_service = usage_service or MemoryRetrievalUsageService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            policy_service=self.policy_service,
        )
        self.bridge = bridge or ChapterMemoryPackPromotionBridge(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.candidates_file = self.data_dir / "chapter_memory_promotion_candidates.json"
        self.decisions_file = self.data_dir / "chapter_memory_promotion_decisions.json"
        self.reports_file = self.data_dir / "chapter_memory_promotion_reports.json"

    def evaluate_chapter_promotions(
        self,
        chapter_id: str,
    ) -> tuple[
        ChapterMemoryPromotionReport,
        list[ChapterMemoryPromotionCandidate],
        list[ChapterMemoryPromotionDecision],
    ]:
        chapter_id = chapter_id.strip()
        if not chapter_id:
            raise StorageError("CHAPTER_MEMORY_PROMOTION_CHAPTER_ID_REQUIRED")
        policy = self.policy_service.get_policy()
        usages = self.usage_service.list_usage(chapter_id)
        candidates: list[ChapterMemoryPromotionCandidate] = []
        decisions: list[ChapterMemoryPromotionDecision] = []
        for usage in usages:
            candidate, decision = self._evaluate_usage(policy, usage)
            candidates.append(candidate)
            self._upsert_candidate(candidate)
            if decision is not None:
                decisions.append(decision)
                self._upsert_decision(decision)
        report = self._build_report(chapter_id, usages, candidates)
        self._upsert_report(report)
        return report, candidates, decisions

    def list_candidates(
        self,
        chapter_id: str | None = None,
    ) -> list[ChapterMemoryPromotionCandidate]:
        candidates = _read_model_list(
            self.store,
            self.candidates_file,
            ChapterMemoryPromotionCandidate,
        )
        if chapter_id:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.chapter_id == chapter_id
            ]
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.chapter_id,
                candidate.canonical_key,
                candidate.promotion_candidate_id,
            ),
        )

    def get_latest_report(self, chapter_id: str) -> ChapterMemoryPromotionReport | None:
        reports = [
            report
            for report in _read_model_list(
                self.store,
                self.reports_file,
                ChapterMemoryPromotionReport,
            )
            if report.chapter_id == chapter_id
        ]
        if not reports:
            return None
        return sorted(reports, key=lambda report: report.evaluated_at, reverse=True)[0]

    def _evaluate_usage(
        self,
        policy: TieredMemoryRetrievalPolicy,
        usage: MemoryRetrievalUsageRecord,
    ) -> tuple[ChapterMemoryPromotionCandidate, ChapterMemoryPromotionDecision | None]:
        timestamp = utc_now()
        target_bucket = self._target_context_bucket(usage)
        threshold = self._threshold(policy, usage)
        candidate = ChapterMemoryPromotionCandidate(
            promotion_candidate_id=self._candidate_id(usage.chapter_id, usage.canonical_key),
            project_id=usage.project_id,
            chapter_id=usage.chapter_id,
            usage_record_id=usage.usage_record_id,
            canonical_key=usage.canonical_key,
            memory_id=usage.memory_id,
            source_object_type=usage.source_object_type,
            source_object_id=usage.source_object_id,
            memory_type=usage.memory_type,
            retrieval_count_in_chapter=usage.retrieval_count_in_chapter,
            threshold=threshold,
            target_context_bucket=target_bucket,
            safe_summary=usage.safe_summary,
            block_reason=usage.block_reason,
            created_at=timestamp,
            updated_at=timestamp,
        )
        decision_type = ""
        reason = ""
        target_pack_id = ""
        if usage.blocked_from_normal_promotion or usage.status == "blocked":
            candidate.status = "blocked"
            candidate.block_reason = usage.block_reason or "inactive_memory_status"
            decision_type = "block_promotion"
            reason = candidate.block_reason
        elif usage.retrieval_count_in_chapter < threshold:
            candidate.status = "pending"
            reason = "retrieval_threshold_not_met"
        else:
            ref = self._ref_from_usage(usage)
            target_pack_id, wrote_pack = self.bridge.promote_reference(
                chapter_id=usage.chapter_id,
                ref=ref,
                canonical_key=usage.canonical_key,
                promotion_candidate_id=candidate.promotion_candidate_id,
                target_context_bucket=target_bucket,
            )
            candidate.promoted_chapter_memory_pack_id = target_pack_id
            candidate.status = "promoted"
            decision_type = "auto_promote_reference"
            if wrote_pack:
                reason = "threshold_met_reference_promoted"
            else:
                reason = "reference_already_present"
            self.usage_service.mark_promoted(
                usage.usage_record_id,
                candidate.promotion_candidate_id,
            )
        if not decision_type:
            return candidate, None
        decision = ChapterMemoryPromotionDecision(
            promotion_decision_id=self._decision_id(
                candidate.promotion_candidate_id,
                decision_type,
            ),
            project_id=usage.project_id,
            chapter_id=usage.chapter_id,
            promotion_candidate_id=candidate.promotion_candidate_id,
            usage_record_id=usage.usage_record_id,
            decision_type=decision_type,
            reason=reason,
            target_chapter_memory_pack_id=target_pack_id,
            created_at=timestamp,
        )
        return candidate, decision

    def _ref_from_usage(self, usage: MemoryRetrievalUsageRecord) -> MemoryPackSourceRef:
        memory = self._memory_record(usage.memory_id)
        if memory is not None:
            return MemoryPackSourceRef(
                memory_id=memory.memory_id,
                source_object_type=memory.source_object_type,
                source_object_id=memory.source_object_id,
                memory_type=memory.memory_type,
                summary=_safe_text(memory.summary, 240),
                keywords=_unique(memory.keywords),
                status=memory.status,
                importance=memory.importance,
                version_id=memory.version_id,
                matched_by=["m5_promotion_usage"],
                reason="m5_reference_promotion",
            )
        return MemoryPackSourceRef(
            memory_id=usage.memory_id,
            source_object_type=usage.source_object_type,
            source_object_id=usage.source_object_id,
            memory_type=usage.memory_type,
            summary=_safe_text(usage.safe_summary, 240),
            keywords=[],
            status="active",
            importance=usage.importance,
            matched_by=["m5_promotion_usage"],
            reason="m5_reference_promotion",
        )

    def _memory_record(self, memory_id: str) -> MemoryRecord | None:
        memory_id = str(memory_id or "").strip()
        if not memory_id:
            return None
        raw = self.repositories.memory.get_by_id(memory_id)
        if not raw:
            return None
        try:
            return MemoryRecord(**raw)
        except ValidationError:
            return None

    def _target_context_bucket(self, usage: MemoryRetrievalUsageRecord) -> str:
        memory_type = str(usage.memory_type or "").casefold()
        source_type = str(usage.source_object_type or "").casefold()
        value = memory_type or source_type
        if value in {"world", "world_canvas", "world_rule"}:
            return "world_context"
        if value in {"framework", "chapter_framework"}:
            return "framework_context"
        if value == "relationship":
            return "relationship_context"
        if value == "character":
            return "character_context"
        return "event_context"

    def _threshold(
        self,
        policy: TieredMemoryRetrievalPolicy,
        usage: MemoryRetrievalUsageRecord,
    ) -> int:
        if str(usage.importance or "").casefold() in {"critical", "high"}:
            return policy.high_importance_threshold
        return policy.default_threshold

    def _build_report(
        self,
        chapter_id: str,
        usages: list[MemoryRetrievalUsageRecord],
        candidates: list[ChapterMemoryPromotionCandidate],
    ) -> ChapterMemoryPromotionReport:
        timestamp = utc_now()
        promoted = [
            candidate
            for candidate in candidates
            if candidate.status == "promoted"
        ]
        blocked = [candidate for candidate in candidates if candidate.status == "blocked"]
        return ChapterMemoryPromotionReport(
            promotion_report_id=f"promotion_report_{_slug(chapter_id)}_{_hash_text(timestamp, 8)}",
            project_id=self._current_project_id(),
            chapter_id=chapter_id,
            evaluated_at=timestamp,
            usage_record_count=len(usages),
            promoted_candidate_count=len(
                [candidate for candidate in candidates if candidate.status == "promoted"]
            ),
            blocked_candidate_count=len(blocked),
            already_promoted_count=0,
            promoted_memory_ids=_unique([candidate.memory_id for candidate in promoted]),
            blocked_memory_ids=_unique([candidate.memory_id for candidate in blocked]),
            notes=[
                "reference_only_promotion",
                "no_story_fact_write",
                "scene_active_character_ids_guarded",
            ],
        )

    def _upsert_candidate(self, candidate: ChapterMemoryPromotionCandidate) -> None:
        _upsert_model(
            self.store,
            self.candidates_file,
            candidate,
            "promotion_candidate_id",
            ChapterMemoryPromotionCandidate,
        )

    def _upsert_decision(self, decision: ChapterMemoryPromotionDecision) -> None:
        _upsert_model(
            self.store,
            self.decisions_file,
            decision,
            "promotion_decision_id",
            ChapterMemoryPromotionDecision,
        )

    def _upsert_report(self, report: ChapterMemoryPromotionReport) -> None:
        _upsert_model(
            self.store,
            self.reports_file,
            report,
            "promotion_report_id",
            ChapterMemoryPromotionReport,
        )

    def _candidate_id(self, chapter_id: str, canonical_key: str) -> str:
        return f"promo_{_slug(chapter_id)}_{_hash_text(canonical_key, 12)}"

    def _decision_id(self, candidate_id: str, decision_type: str) -> str:
        return f"decision_{candidate_id}_{_slug(decision_type)}"

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback="local_project",
        )


def _read_model_list(
    store: JsonStore,
    path: Path,
    model_cls,
) -> list:
    if not store.exists(path):
        return []
    data = store.read_any(path)
    if not isinstance(data, list):
        raise StorageError(f"JSON root must be a list: {path}")
    records = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            records.append(model_cls(**item))
        except ValidationError as exc:
            raise StorageError(f"{model_cls.__name__} JSON schema is invalid.") from exc
    return records


def _upsert_model(
    store: JsonStore,
    path: Path,
    model: BaseModel,
    id_field: str,
    model_cls,
) -> None:
    records = _read_model_list(store, path, model_cls)
    target_id = str(getattr(model, id_field) or "")
    updated = []
    replaced = False
    for record in records:
        if str(getattr(record, id_field) or "") == target_id:
            updated.append(model)
            replaced = True
        else:
            updated.append(record)
    if not replaced:
        updated.append(model)
    store.write(path, [model_to_dict(record) for record in updated])


def _chapter_pack_refs(pack: ChapterMemoryPack) -> list[MemoryPackSourceRef]:
    refs: list[MemoryPackSourceRef] = []
    for bucket in (
        "world_context",
        "character_context",
        "relationship_context",
        "event_context",
        "framework_context",
    ):
        refs.extend(getattr(pack, bucket) or [])
    return refs


def _safe_text(value: Any, max_len: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _unique(values: list[Any]) -> list[str]:
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


def _slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "item"


def _hash_text(value: str, length: int = 12) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:length]


def _join_reason(left: str, right: str) -> str:
    return ";".join(_unique([left, right]))
