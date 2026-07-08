from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.character import Character, ProposedCharacterStateChange
from app.backend.models.decision import Decision
from app.backend.models.event import Event
from app.backend.models.memory_record import MEMORY_M2_VERSION_ID, MemoryRecord
from app.backend.models.memory_update_plan import (
    DependentSceneAction,
    MemoryChangeItem,
    MemoryUpdatePlan,
)
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import SceneMemoryExtraction
from app.backend.models.scene_revision import SceneRevisionCandidate
from app.backend.models.state_change import StateChange
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.character_major_change_policy import (
    a_tier_change_requires_confirmation,
)
from app.backend.services.character_state_update_service import CharacterStateUpdateService
from app.backend.services.continuity_gate_service import (
    ContinuityGateService,
    SceneConfirmationGuard,
)
from app.backend.services.objective_fact_write_guard import ObjectiveFactWriteGuard
from app.backend.services.subjective_fact_extraction_service import (
    SubjectiveFactExtractionService,
)
from app.backend.services.subjective_fact_write_service import SubjectiveFactWriteService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class RevisionMemoryStructuringService:
    def __init__(self, repositories: RepositoryBundle) -> None:
        self.repositories = repositories

    def load_revision_memory(
        self,
        scene_id: str,
        revision_id: str,
    ) -> tuple[Scene, SceneRevisionCandidate, SceneMemoryExtraction, SceneMemoryExtraction]:
        scene_raw = self.repositories.scenes.get_by_id(scene_id)
        if scene_raw is None:
            raise StorageError("MEMORY_SYNC_SCENE_MISSING: Scene does not exist.")
        try:
            scene = Scene(**scene_raw)
        except ValidationError as exc:
            raise StorageError("Scene JSON schema is invalid.") from exc

        candidate = next(
            (
                item
                for item in scene.revision_history
                if item.revision_id == revision_id
            ),
            None,
        )
        if candidate is None:
            raise StorageError(
                "MEMORY_SYNC_REVISION_MISSING: Revision candidate does not exist."
            )

        old_extraction = scene.memory_extraction or SceneMemoryExtraction()
        revised_extraction = candidate.memory_extraction or SceneMemoryExtraction()
        return scene, candidate, old_extraction, revised_extraction


class LocalMemoryDiffService:
    def diff(
        self,
        *,
        scene: Scene,
        candidate: SceneRevisionCandidate,
        old_extraction: SceneMemoryExtraction,
        revised_extraction: SceneMemoryExtraction,
        old_memory_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        changed_events = self._diff_collection(
            old_extraction.event_summary,
            revised_extraction.event_summary,
            object_type="event",
            id_key="event_id",
            id_prefix=f"event_{scene.scene_id}_{candidate.revision_id}",
            reason="修订候选改变了当前场景的事件摘要。",
        )
        changed_state_changes = self._diff_collection(
            old_extraction.proposed_state_changes,
            revised_extraction.proposed_state_changes,
            object_type="state_change",
            id_key="state_change_id",
            id_prefix=f"change_{scene.scene_id}_{candidate.revision_id}",
            reason="修订候选改变了当前场景的状态变更。",
        )
        changed_relationship_changes = self._diff_collection(
            old_extraction.relationship_changes,
            revised_extraction.relationship_changes,
            object_type="relationship_change",
            id_key="relationship_change_id",
            id_prefix=f"relationship_change_{scene.scene_id}_{candidate.revision_id}",
            reason="修订候选改变了当前场景的关系变更。",
        )
        memory_changed = bool(
            self._diff_collection(
                old_extraction.memory_records,
                revised_extraction.memory_records,
                object_type="memory_record",
                id_key="memory_id",
                id_prefix=f"memory_{scene.scene_id}_{candidate.revision_id}",
                reason="修订候选改变了当前场景的记忆记录。",
            )
        )
        persisted_old_memory_ids = self._persisted_old_memory_ids(
            old_memory_records,
            candidate.revision_id,
            revised_extraction,
        )
        extraction_changed = bool(
            changed_events
            or changed_state_changes
            or changed_relationship_changes
            or memory_changed
            or persisted_old_memory_ids
        )
        superseded_memory_ids = (
            [
                str(record.get("memory_id") or "")
                for record in old_memory_records
                if str(record.get("memory_id") or "").strip()
            ]
            if extraction_changed
            else []
        )
        affected_character_ids = (
            self._affected_character_ids(revised_extraction)
            if extraction_changed
            else []
        )
        affected_relationship_ids = (
            self._affected_relationship_ids(revised_extraction)
            if extraction_changed
            else []
        )
        return {
            "changed_events": changed_events,
            "changed_state_changes": changed_state_changes,
            "changed_relationship_changes": changed_relationship_changes,
            "superseded_memory_ids": _unique_strings(superseded_memory_ids),
            "affected_character_ids": affected_character_ids,
            "affected_relationship_ids": affected_relationship_ids,
            "affected_event_ids": _unique_strings(
                [
                    change.new_object_id
                    for change in changed_events
                    if change.new_object_id
                ]
            ),
            "extraction_changed": extraction_changed,
        }

    def _persisted_old_memory_ids(
        self,
        old_memory_records: list[dict[str, Any]],
        revision_id: str,
        revised_extraction: SceneMemoryExtraction,
    ) -> list[str]:
        revised_signatures = self._revised_memory_signatures(revised_extraction)
        old_ids: list[str] = []
        for record in old_memory_records:
            memory_id = str(record.get("memory_id") or "").strip()
            if not memory_id:
                continue
            source_revision_id = str(record.get("source_revision_id") or "").strip()
            source_plan_id = str(record.get("source_plan_id") or "").strip()
            if source_revision_id == revision_id or revision_id in source_plan_id:
                continue
            if self._memory_record_signature(record) in revised_signatures:
                continue
            old_ids.append(memory_id)
        return _unique_strings(old_ids)

    def _revised_memory_signatures(
        self,
        revised_extraction: SceneMemoryExtraction,
    ) -> set[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
        signatures: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()
        for memory in revised_extraction.memory_records:
            if isinstance(memory, dict):
                signatures.add(self._memory_record_signature(memory))
        if signatures:
            return signatures
        for event in revised_extraction.event_summary:
            if not isinstance(event, dict):
                continue
            signatures.add(
                (
                    _norm(event.get("summary") or event.get("result")),
                    "event",
                    tuple(sorted(_norm(item) for item in _as_strings(event.get("participants")))),
                    tuple(sorted(_norm(item) for item in _as_strings(event.get("tags")))),
                )
            )
        return signatures

    def _memory_record_signature(
        self,
        record: dict[str, Any],
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
        return (
            _norm(record.get("summary")),
            _norm(record.get("memory_type") or "event"),
            tuple(
                sorted(
                    {
                        _norm(item)
                        for item in _as_strings(record.get("character_ids"))
                    }
                )
            ),
            tuple(
                sorted(
                    {
                        _norm(item)
                        for item in [
                            *_as_strings(record.get("keywords")),
                            *_as_strings(record.get("tags")),
                        ]
                    }
                )
            ),
        )

    def _revised_event_signatures(
        self,
        revised_extraction: SceneMemoryExtraction,
    ) -> set[tuple[str, str, tuple[str, ...]]]:
        return {
            self._event_record_signature(event)
            for event in revised_extraction.event_summary
            if isinstance(event, dict)
        }

    def _event_record_signature(
        self,
        event: dict[str, Any],
    ) -> tuple[str, str, tuple[str, ...]]:
        return (
            _norm(event.get("summary") or event.get("result")),
            _norm(event.get("location_id")),
            tuple(
                sorted(
                    _norm(item)
                    for item in [
                        *_as_strings(event.get("participants")),
                        *_as_strings(event.get("character_ids")),
                    ]
                )
            ),
        )

    def _revised_state_change_signatures(
        self,
        revised_extraction: SceneMemoryExtraction,
    ) -> set[tuple[str, str, str]]:
        return {
            self._state_change_record_signature(change)
            for change in revised_extraction.proposed_state_changes
            if isinstance(change, dict)
        }

    def _state_change_record_signature(
        self,
        change: dict[str, Any],
    ) -> tuple[str, str, str]:
        after = change.get("after")
        if isinstance(after, dict):
            after_text = json.dumps(after, ensure_ascii=False, sort_keys=True)
        else:
            after_text = str(after or "")
        return (
            _norm(change.get("target_type")),
            _norm(change.get("target_id")),
            _norm(after_text),
        )

    def _diff_collection(
        self,
        old_items: list[dict[str, Any]],
        new_items: list[dict[str, Any]],
        *,
        object_type: str,
        id_key: str,
        id_prefix: str,
        reason: str,
    ) -> list[MemoryChangeItem]:
        old_clean = [dict(item) for item in old_items if isinstance(item, dict)]
        new_clean = [dict(item) for item in new_items if isinstance(item, dict)]
        if self._collection_signature(old_clean) == self._collection_signature(new_clean):
            return []

        changes: list[MemoryChangeItem] = []
        max_len = max(len(old_clean), len(new_clean))
        for index in range(max_len):
            old_item = old_clean[index] if index < len(old_clean) else None
            new_item = new_clean[index] if index < len(new_clean) else None
            change_type = "modified"
            if old_item is None:
                change_type = "added"
            elif new_item is None:
                change_type = "removed"
            elif self._item_signature(old_item) == self._item_signature(new_item):
                continue

            old_id = str((old_item or {}).get(id_key) or "")
            new_id = str((new_item or {}).get(id_key) or "")
            if new_item is not None and (not new_id or new_id == old_id):
                new_id = f"{id_prefix}_{index + 1:03d}"
            severity = "high" if object_type in {"event", "state_change"} else "medium"
            changes.append(
                MemoryChangeItem(
                    change_id=f"change_{object_type}_{index + 1:03d}",
                    change_type=change_type,
                    object_type=object_type,
                    old_object_id=old_id,
                    new_object_id=new_id,
                    old_summary=self._summary(old_item),
                    new_summary=self._summary(new_item),
                    severity=severity,
                    reason=reason,
                    requires_user_confirmation=change_type != "unchanged",
                )
            )
        return changes

    def _collection_signature(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self._item_signature(item) for item in items]

    def _item_signature(self, item: dict[str, Any]) -> dict[str, Any]:
        ignored = {
            "created_at",
            "updated_at",
            "version_id",
            "status",
            "memory_id",
            "event_id",
            "state_change_id",
            "relationship_change_id",
        }
        return {
            key: value
            for key, value in sorted(item.items())
            if key not in ignored and value not in (None, "", [], {})
        }

    def _summary(self, item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        return str(
            item.get("summary")
            or item.get("result")
            or item.get("after")
            or item.get("relationship_id")
            or ""
        )

    def _affected_character_ids(
        self,
        extraction: SceneMemoryExtraction,
    ) -> list[str]:
        values: list[str] = []
        for event in extraction.event_summary:
            values.extend(_as_strings(event.get("participants")))
            values.extend(_as_strings(event.get("character_ids")))
        for change in extraction.proposed_state_changes:
            if str(change.get("target_type") or "") == "character":
                values.append(str(change.get("target_id") or ""))
            values.extend(_as_strings(change.get("character_ids")))
        for memory in extraction.memory_records:
            values.extend(_as_strings(memory.get("character_ids")))
        return _unique_strings(values)

    def _affected_relationship_ids(
        self,
        extraction: SceneMemoryExtraction,
    ) -> list[str]:
        values: list[str] = []
        for change in extraction.relationship_changes:
            values.append(str(change.get("relationship_id") or ""))
            values.extend(_as_strings(change.get("relationship_ids")))
        for memory in extraction.memory_records:
            values.extend(_as_strings(memory.get("relationship_ids")))
        return _unique_strings(values)


class MemoryUpdatePlanService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        structuring_service: RevisionMemoryStructuringService | None = None,
        diff_service: LocalMemoryDiffService | None = None,
        character_state_service: CharacterStateUpdateService | None = None,
        continuity_gate_service: ContinuityGateService | None = None,
        subjective_fact_extraction_service: SubjectiveFactExtractionService | None = None,
        subjective_fact_write_service: SubjectiveFactWriteService | None = None,
        objective_fact_write_guard: ObjectiveFactWriteGuard | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.structuring_service = structuring_service or RevisionMemoryStructuringService(
            self.repositories
        )
        self.diff_service = diff_service or LocalMemoryDiffService()
        self.character_state_service = character_state_service or CharacterStateUpdateService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.continuity_gate_service = continuity_gate_service or ContinuityGateService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.scene_confirmation_guard = SceneConfirmationGuard(
            self.continuity_gate_service
        )
        self.subjective_fact_extraction_service = (
            subjective_fact_extraction_service
            or SubjectiveFactExtractionService()
        )
        self.subjective_fact_write_service = (
            subjective_fact_write_service
            or SubjectiveFactWriteService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.objective_fact_write_guard = (
            objective_fact_write_guard or ObjectiveFactWriteGuard()
        )

    def create_plan_from_revision(
        self,
        scene_id: str,
        revision_id: str,
        dry_run: bool = False,
    ) -> MemoryUpdatePlan:
        scene, candidate, old_extraction, revised_extraction = (
            self.structuring_service.load_revision_memory(scene_id, revision_id)
        )
        candidate, revised_extraction, guard_decision = (
            self._guard_revision_candidate_extraction(
                scene=scene,
                candidate=candidate,
                revised_extraction=revised_extraction,
                persist_subjective_records=(
                    not dry_run and candidate.status == "confirmed"
                ),
            )
        )
        old_memory_records = self._current_scene_memory_records(scene)
        plan_id = self._plan_id(scene.scene_id, candidate.revision_id)
        existing_plan = self.repositories.memory_update_plans.get_by_id(plan_id)
        if existing_plan and not dry_run:
            try:
                existing = MemoryUpdatePlan(**existing_plan)
            except ValidationError as exc:
                raise StorageError("MemoryUpdatePlan JSON schema is invalid.") from exc
            if existing.status in {"applied", "rejected"}:
                return existing
        diff = self.diff_service.diff(
            scene=scene,
            candidate=candidate,
            old_extraction=old_extraction,
            revised_extraction=revised_extraction,
            old_memory_records=old_memory_records,
        )
        self._include_current_scene_artifact_changes(
            scene,
            candidate,
            revised_extraction,
            diff,
        )
        dependent_actions = self._dependent_scene_actions(
            scene=scene,
            superseded_memory_ids=diff["superseded_memory_ids"],
            changed_event_ids=diff["affected_event_ids"],
        )
        affected_pack_ids = self._affected_memory_pack_ids(
            diff["superseded_memory_ids"]
        )
        a_tier_reasons = self._a_tier_confirmation_reasons(
            revised_extraction.proposed_state_changes
        )
        requires_confirmation = bool(
            diff["changed_events"]
            or diff["changed_state_changes"]
            or diff["changed_relationship_changes"]
            or diff["superseded_memory_ids"]
            or diff["affected_character_ids"]
            or diff["affected_relationship_ids"]
            or dependent_actions
            or affected_pack_ids
            or a_tier_reasons
            or scene.status == "temporary_confirmed"
            or scene.is_provisional
        )
        confirmation_reasons = self._confirmation_reasons(
            diff=diff,
            dependent_actions=dependent_actions,
            affected_pack_ids=affected_pack_ids,
            a_tier_reasons=a_tier_reasons,
            scene=scene,
        )
        status = "pending_user_confirmation" if requires_confirmation else "applied"
        timestamp = now_iso()
        new_memory_records = (
            self._new_memory_records(
                scene=scene,
                candidate=candidate,
                revised_extraction=revised_extraction,
                plan_id=plan_id,
            )
            if requires_confirmation or diff["extraction_changed"]
            else []
        )
        if not requires_confirmation and not new_memory_records:
            user_summary = "未检测到需要同步的修订记忆变更，计划已自动标记为已应用。"
            technical_summary = (
                "No local memory diff was detected; "
                f"subjective_guard_blocked={len(guard_decision.blocked_objective_candidates)}."
            )
        else:
            user_summary = (
                f"检测到 {len(diff['superseded_memory_ids'])} 条旧记忆、"
                f"{len(new_memory_records)} 条新记忆草案和 "
                f"{len(dependent_actions)} 个受影响后续场景。"
            )
            technical_summary = (
                "Local structured diff from scene revision memory_extraction; "
                f"events={len(diff['changed_events'])}, "
                f"state_changes={len(diff['changed_state_changes'])}, "
                f"relationships={len(diff['changed_relationship_changes'])}, "
                f"subjective_guard_blocked={len(guard_decision.blocked_objective_candidates)}."
            )

        plan = MemoryUpdatePlan(
            memory_update_plan_id=plan_id,
            project_id=scene.project_id or LOCAL_PROJECT_ID,
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            source_revision_id=candidate.revision_id,
            status=status,
            old_scene_version_id=candidate.base_scene_version_id or scene.version_id,
            revised_scene_version_id=scene.version_id,
            changed_events=diff["changed_events"],
            changed_state_changes=diff["changed_state_changes"],
            changed_relationship_changes=diff["changed_relationship_changes"],
            superseded_memory_ids=diff["superseded_memory_ids"],
            new_memory_records=new_memory_records,
            affected_character_ids=diff["affected_character_ids"],
            affected_relationship_ids=diff["affected_relationship_ids"],
            affected_event_ids=diff["affected_event_ids"],
            affected_scene_ids=_unique_strings(
                [action.dependent_scene_id for action in dependent_actions]
            ),
            dependent_scene_actions=dependent_actions,
            affected_memory_pack_ids=affected_pack_ids,
            memory_pack_refresh_recommended=bool(affected_pack_ids),
            requires_user_confirmation=requires_confirmation,
            confirmation_reasons=confirmation_reasons,
            user_facing_summary=user_summary,
            technical_summary=technical_summary,
            created_at=timestamp,
            updated_at=timestamp,
        )
        if not dry_run:
            self.repositories.memory_update_plans.upsert(
                model_to_dict(plan),
                "memory_update_plan_id",
            )
        return plan

    def get_plan(self, plan_id: str) -> MemoryUpdatePlan:
        raw = self.repositories.memory_update_plans.get_by_id(plan_id)
        if raw is None:
            raise StorageError("MEMORY_SYNC_PLAN_MISSING: Memory update plan does not exist.")
        try:
            return MemoryUpdatePlan(**raw)
        except ValidationError as exc:
            raise StorageError("MemoryUpdatePlan JSON schema is invalid.") from exc

    def confirm_plan(self, plan_id: str, user_input: str = "") -> tuple[MemoryUpdatePlan, Decision]:
        plan = self.get_plan(plan_id)
        if plan.status == "rejected":
            raise StorageError("MEMORY_SYNC_PLAN_REJECTED: Memory update plan was rejected.")
        if plan.status == "applied":
            decision = self._write_decision(
                decision_type="confirm",
                target_id=plan.memory_update_plan_id,
                user_input=user_input or "记忆同步计划已经应用，无需重复确认。",
            )
            return plan, decision
        updated = self._replace_plan_status(plan, "confirmed")
        decision = self._write_decision(
            decision_type="confirm",
            target_id=updated.memory_update_plan_id,
            user_input=user_input or "确认当前修订的记忆同步计划。",
        )
        return updated, decision

    def apply_plan(self, plan_id: str) -> tuple[MemoryUpdatePlan, Decision | None]:
        plan = self.get_plan(plan_id)
        if plan.status == "applied":
            return plan, None
        if plan.status == "rejected":
            raise StorageError("MEMORY_SYNC_PLAN_REJECTED: Memory update plan was rejected.")
        if plan.requires_user_confirmation and plan.status != "confirmed":
            raise StorageError(
                "MEMORY_SYNC_CONFIRMATION_REQUIRED: Memory update plan must be confirmed before apply."
            )

        scene, candidate, _old_extraction, revised_extraction = (
            self.structuring_service.load_revision_memory(
                plan.scene_id,
                plan.source_revision_id,
            )
        )
        if plan.requires_user_confirmation and candidate.status != "confirmed":
            raise StorageError(
                "MEMORY_SYNC_REVISION_NOT_CONFIRMED: Confirm the scene revision before applying memory sync."
            )
        self.scene_confirmation_guard.require_revision_confirmation_allowed(
            plan.scene_id,
            plan.source_revision_id,
        )
        candidate, revised_extraction, _guard_decision = (
            self._guard_revision_candidate_extraction(
                scene=scene,
                candidate=candidate,
                revised_extraction=revised_extraction,
                persist_subjective_records=True,
            )
        )

        self._apply_memory_records(plan, scene)
        self._apply_event_changes(plan, scene, candidate)
        self._apply_state_changes(plan, scene, candidate, revised_extraction)
        self._apply_dependent_scene_actions(plan)
        self._mark_memory_packs_stale(plan)
        decision = self._write_decision(
            decision_type="apply",
            target_id=plan.memory_update_plan_id,
            user_input="应用当前修订的记忆同步计划。",
        )
        updated = self._replace_plan_status(plan, "applied")
        return updated, decision

    def reject_plan(self, plan_id: str, user_input: str = "") -> tuple[MemoryUpdatePlan, Decision]:
        plan = self.get_plan(plan_id)
        if plan.status == "applied":
            raise StorageError(
                "MEMORY_SYNC_PLAN_ALREADY_APPLIED: Applied memory update plan cannot be rejected."
            )
        updated = self._replace_plan_status(plan, "rejected")
        decision = self._write_decision(
            decision_type="reject",
            target_id=updated.memory_update_plan_id,
            user_input=user_input or "拒绝当前修订的记忆同步计划。",
        )
        return updated, decision

    def confirm_and_apply_plan(
        self,
        plan_id: str,
        user_input: str = "",
    ) -> tuple[MemoryUpdatePlan, Decision | None]:
        plan = self.get_plan(plan_id)
        if plan.status not in {"confirmed", "applied"}:
            plan, _decision = self.confirm_plan(plan_id, user_input=user_input)
        if plan.status == "applied":
            return plan, None
        return self.apply_plan(plan.memory_update_plan_id)

    def _guard_revision_candidate_extraction(
        self,
        *,
        scene: Scene,
        candidate: SceneRevisionCandidate,
        revised_extraction: SceneMemoryExtraction,
        persist_subjective_records: bool,
    ):
        revision_scene = Scene(
            **{
                **model_to_dict(scene),
                "synopsis": candidate.revised_synopsis or scene.synopsis,
                "prose_text": candidate.revised_prose_text or scene.prose_text,
                "memory_extraction": model_to_dict(revised_extraction),
                "status": candidate.status or scene.status,
            }
        )
        extraction = self.subjective_fact_extraction_service.extract_from_scene(
            revision_scene
        )
        if persist_subjective_records:
            self.subjective_fact_write_service.write_from_extraction(
                extraction,
                status=self._memory_status_for_scene(scene),
                project_id=scene.project_id,
            )
        filtered_scene, guard_decision = self.objective_fact_write_guard.filter_scene(
            revision_scene,
            extraction,
        )
        filtered_extraction = filtered_scene.memory_extraction
        filtered_candidate = SceneRevisionCandidate(
            **{
                **model_to_dict(candidate),
                "memory_extraction": model_to_dict(filtered_extraction),
            }
        )
        return filtered_candidate, filtered_extraction, guard_decision

    def _current_scene_memory_records(self, scene: Scene) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for record in self.repositories.memory.list_all():
            status = str(record.get("status") or "active")
            if status in {"superseded", "rejected"}:
                continue
            if (
                str(record.get("scene_id") or "") == scene.scene_id
                or str(record.get("source_object_id") or "") == scene.scene_id
                or str(record.get("object_id") or "") == scene.scene_id
            ):
                result.append(record)
        return result

    def _include_current_scene_artifact_changes(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate,
        revised_extraction: SceneMemoryExtraction,
        diff: dict[str, Any],
    ) -> None:
        if not diff.get("extraction_changed"):
            return
        existing_event_ids = {
            change.old_object_id
            for change in diff["changed_events"]
            if change.old_object_id
        }
        revised_event_signatures = self.diff_service._revised_event_signatures(
            revised_extraction
        )
        revised_events = [
            dict(item)
            for item in revised_extraction.event_summary
            if isinstance(item, dict)
        ]
        for event in self.repositories.events.list_all():
            event_id = str(event.get("event_id") or "")
            status = str(event.get("status") or "confirmed")
            if (
                not event_id
                or event_id in existing_event_ids
                or status in {"superseded", "rejected"}
                or str(event.get("scene_id") or "") != scene.scene_id
                or str(event.get("source_revision_id") or "") == candidate.revision_id
            ):
                continue
            if self.diff_service._event_record_signature(event) in revised_event_signatures:
                continue
            revised_event = revised_events[
                min(len(diff["changed_events"]), len(revised_events) - 1)
            ] if revised_events else {}
            new_event_id = (
                f"event_{scene.scene_id}_{candidate.revision_id}_persisted_"
                f"{len(diff['changed_events']) + 1:03d}"
            ) if revised_event else ""
            diff["changed_events"].append(
                MemoryChangeItem(
                    change_id=f"change_event_persisted_{len(diff['changed_events']) + 1:03d}",
                    change_type="modified" if new_event_id else "superseded",
                    object_type="event",
                    old_object_id=event_id,
                    new_object_id=new_event_id,
                    old_summary=str(event.get("summary") or ""),
                    new_summary=str(
                        revised_event.get("summary")
                        or revised_event.get("result")
                        or ""
                    ),
                    severity="medium",
                    reason="当前场景已有事件记录需要由修订计划统一标记为 superseded。",
                    requires_user_confirmation=True,
                )
            )
            existing_event_ids.add(event_id)

        existing_state_change_ids = {
            change.old_object_id
            for change in diff["changed_state_changes"]
            if change.old_object_id
        }
        revised_state_signatures = self.diff_service._revised_state_change_signatures(
            revised_extraction
        )
        revised_state_changes = [
            dict(item)
            for item in revised_extraction.proposed_state_changes
            if isinstance(item, dict)
        ]
        for change in self.repositories.state_changes.list_all():
            change_id = str(change.get("state_change_id") or "")
            status = str(change.get("status") or "confirmed")
            if not change_id or change_id in existing_state_change_ids:
                continue
            scene_match = (
                str(change.get("scene_id") or "") == scene.scene_id
                or str(change.get("source_scene_id") or "") == scene.scene_id
            )
            if (
                not scene_match
                or status in {"superseded", "rejected"}
                or str(change.get("source_revision_id") or "") == candidate.revision_id
                or self.diff_service._state_change_record_signature(change)
                in revised_state_signatures
            ):
                continue
            revised_change = revised_state_changes[
                min(len(diff["changed_state_changes"]), len(revised_state_changes) - 1)
            ] if revised_state_changes else {}
            new_change_id = (
                f"change_{scene.scene_id}_{candidate.revision_id}_persisted_"
                f"{len(diff['changed_state_changes']) + 1:03d}"
            ) if revised_change else ""
            diff["changed_state_changes"].append(
                MemoryChangeItem(
                    change_id=f"change_state_persisted_{len(diff['changed_state_changes']) + 1:03d}",
                    change_type="modified" if new_change_id else "superseded",
                    object_type="state_change",
                    old_object_id=change_id,
                    new_object_id=new_change_id,
                    old_summary=str(change.get("summary") or change.get("after") or ""),
                    new_summary=str(
                        revised_change.get("summary")
                        or revised_change.get("after")
                        or ""
                    ),
                    severity="medium",
                    reason="当前场景已有状态变更需要由修订计划统一标记为 superseded。",
                    requires_user_confirmation=True,
                )
            )
            existing_state_change_ids.add(change_id)

    def _new_memory_records(
        self,
        *,
        scene: Scene,
        candidate: SceneRevisionCandidate,
        revised_extraction: SceneMemoryExtraction,
        plan_id: str,
    ) -> list[MemoryRecord]:
        event_ids = [
            str(event.get("event_id") or f"event_{scene.scene_id}_{candidate.revision_id}_{index:03d}")
            for index, event in enumerate(revised_extraction.event_summary, start=1)
            if isinstance(event, dict)
        ]
        memory_inputs = [
            dict(item)
            for item in revised_extraction.memory_records
            if isinstance(item, dict)
        ]
        if not memory_inputs:
            memory_inputs = [
                {
                    "summary": event.get("summary") or event.get("result") or scene.synopsis,
                    "memory_type": "event",
                    "keywords": event.get("tags") or [],
                    "character_ids": event.get("participants") or event.get("character_ids") or [],
                    "event_ids": [event_ids[index - 1]] if index - 1 < len(event_ids) else [],
                    "location": event.get("location_id") or scene.location,
                }
                for index, event in enumerate(revised_extraction.event_summary, start=1)
                if isinstance(event, dict)
            ]
        status = self._memory_status_for_scene(scene)
        records: list[MemoryRecord] = []
        for index, memory_data in enumerate(memory_inputs, start=1):
            keywords = _unique_strings(
                [
                    *_as_strings(memory_data.get("keywords")),
                    *_as_strings(memory_data.get("tags")),
                    str(memory_data.get("memory_type") or "event"),
                    scene.location,
                ]
            )
            record_event_ids = _unique_strings(
                [
                    *_as_strings(memory_data.get("event_ids")),
                    *event_ids,
                ]
            )
            record = MemoryRecord(
                memory_id=f"memory_{scene.scene_id}_{candidate.revision_id}_{index:03d}",
                project_id=scene.project_id or LOCAL_PROJECT_ID,
                source_object_type=str(
                    memory_data.get("source_object_type")
                    or memory_data.get("object_type")
                    or "scene_revision"
                ),
                source_object_id=str(
                    memory_data.get("source_object_id")
                    or memory_data.get("object_id")
                    or candidate.revision_id
                ),
                source_revision_id=candidate.revision_id,
                source_plan_id=plan_id,
                chapter_id=scene.chapter_id,
                scene_id=scene.scene_id,
                memory_type=str(memory_data.get("memory_type") or "event"),
                summary=str(memory_data.get("summary") or scene.synopsis),
                keywords=keywords,
                character_ids=_unique_strings(
                    [
                        *_as_strings(memory_data.get("character_ids")),
                        *scene.linked_character_ids,
                    ]
                ),
                relationship_ids=_unique_strings(
                    [
                        *_as_strings(memory_data.get("relationship_ids")),
                        *scene.linked_relationship_ids,
                    ]
                ),
                location=str(memory_data.get("location") or scene.location or "") or None,
                event_ids=record_event_ids,
                importance=str(memory_data.get("importance") or "medium"),
                status=status,
                truth_status=str(memory_data.get("truth_status") or "objective_fact"),
                objective_truth=bool(memory_data.get("objective_truth", True)),
                source_issue_id=str(memory_data.get("source_issue_id") or ""),
                speaker_character_id=str(memory_data.get("speaker_character_id") or ""),
                believed_by_character_ids=_unique_strings(
                    _as_strings(memory_data.get("believed_by_character_ids"))
                ),
                known_false_by_character_ids=_unique_strings(
                    _as_strings(memory_data.get("known_false_by_character_ids"))
                ),
                version_id=MEMORY_M2_VERSION_ID,
                created_at=now_iso(),
                updated_at=now_iso(),
                source_type="scene_revision",
                object_type=str(memory_data.get("object_type") or "scene_revision"),
                object_id=str(memory_data.get("object_id") or candidate.revision_id),
                tags=keywords,
            )
            records.append(record)
        return records

    def _memory_status_for_scene(self, scene: Scene) -> str:
        if scene.status == "temporary_confirmed" or scene.is_provisional:
            return "provisional"
        return "active"

    def _dependent_scene_actions(
        self,
        *,
        scene: Scene,
        superseded_memory_ids: list[str],
        changed_event_ids: list[str],
    ) -> list[DependentSceneAction]:
        source_memory_set = set(superseded_memory_ids)
        changed_event_set = set(changed_event_ids)
        actions: list[DependentSceneAction] = []
        for item in self.repositories.scenes.list_all():
            if not isinstance(item, dict) or item.get("scene_id") == scene.scene_id:
                continue
            if str(item.get("chapter_id") or "") != scene.chapter_id:
                continue
            if int(item.get("scene_index") or 0) <= scene.scene_index:
                continue
            dependent_id = str(item.get("scene_id") or "")
            provisional_scene_match = scene.scene_id in _as_strings(
                item.get("depends_on_provisional_scene_ids")
            )
            memory_match = source_memory_set.intersection(
                _as_strings(item.get("depends_on_provisional_memory_ids"))
            )
            serialized = json.dumps(item, ensure_ascii=False, sort_keys=True)
            embedded_memory_match = {
                memory_id
                for memory_id in source_memory_set
                if memory_id and memory_id in serialized
            }
            embedded_event_match = {
                event_id
                for event_id in changed_event_set
                if event_id and event_id in serialized
            }
            if embedded_memory_match:
                actions.append(
                    DependentSceneAction(
                        dependent_scene_id=dependent_id,
                        dependency_type="superseded_memory",
                        source_scene_id=scene.scene_id,
                        source_memory_ids=sorted(embedded_memory_match),
                        action="needs_regeneration",
                        reason="后续场景的信息包明确引用了已被修订替代的旧记忆。",
                    )
                )
            elif memory_match:
                actions.append(
                    DependentSceneAction(
                        dependent_scene_id=dependent_id,
                        dependency_type="superseded_memory",
                        source_scene_id=scene.scene_id,
                        source_memory_ids=sorted(memory_match),
                        action="needs_review",
                        reason="后续场景依赖的临时或旧记忆已被修订替代。",
                    )
                )
            elif provisional_scene_match:
                actions.append(
                    DependentSceneAction(
                        dependent_scene_id=dependent_id,
                        dependency_type="provisional_scene",
                        source_scene_id=scene.scene_id,
                        action="continuity_recheck",
                        reason="后续场景依赖的前置场景发生修订，需要复核连续性。",
                    )
                )
            elif embedded_event_match:
                actions.append(
                    DependentSceneAction(
                        dependent_scene_id=dependent_id,
                        dependency_type="changed_event",
                        source_scene_id=scene.scene_id,
                        action="continuity_recheck",
                        reason="后续场景引用的前置事件发生修订，需要复核连续性。",
                    )
                )
        return self._dedupe_actions(actions)

    def _affected_memory_pack_ids(self, memory_ids: list[str]) -> list[str]:
        if not memory_ids:
            return []
        memory_set = set(memory_ids)
        pack_ids: list[str] = []
        for repository, id_field in [
            (self.repositories.chapter_memory_packs, "chapter_memory_pack_id"),
            (self.repositories.scene_memory_packs, "scene_memory_pack_id"),
        ]:
            for pack in repository.list_packs():
                serialized = json.dumps(pack, ensure_ascii=False, sort_keys=True)
                if any(memory_id in serialized for memory_id in memory_set):
                    pack_ids.append(str(pack.get(id_field) or ""))
        return _unique_strings(pack_ids)

    def _a_tier_confirmation_reasons(
        self,
        proposed_state_changes: list[dict[str, Any]],
    ) -> list[str]:
        character_by_id = self._character_by_id()
        reasons: list[str] = []
        for change in proposed_state_changes:
            if str(change.get("target_type") or "") != "character":
                continue
            character_id = str(change.get("target_id") or "")
            character = character_by_id.get(character_id)
            if character is None or character.tier != "A":
                continue
            patch = self._proposed_patch_from_state_change(change)
            impact_level = str(change.get("impact_level") or "minor")
            change_type = str(change.get("change_type") or "other")
            if a_tier_change_requires_confirmation(change_type, impact_level, patch):
                reasons.append(
                    f"A-tier 角色 {character.name or character.character_id} 存在重大长期状态变更，需要进入待确认队列。"
                )
        return _unique_strings(reasons)

    def _confirmation_reasons(
        self,
        *,
        diff: dict[str, Any],
        dependent_actions: list[DependentSceneAction],
        affected_pack_ids: list[str],
        a_tier_reasons: list[str],
        scene: Scene,
    ) -> list[str]:
        reasons: list[str] = []
        if diff["changed_events"]:
            reasons.append("修订改变了当前场景事件。")
        if diff["changed_state_changes"]:
            reasons.append("修订改变了当前场景状态变更。")
        if diff["changed_relationship_changes"]:
            reasons.append("修订改变了当前场景关系变更。")
        if diff["superseded_memory_ids"]:
            reasons.append("当前场景已有记忆需要标记为 superseded。")
        if diff["affected_character_ids"]:
            reasons.append("修订影响了角色相关记忆。")
        if diff["affected_relationship_ids"]:
            reasons.append("修订影响了关系相关记忆。")
        if dependent_actions:
            reasons.append("后续场景依赖当前场景的旧记忆或临时事实，需要标记复核。")
        if affected_pack_ids:
            reasons.append("已有记忆包引用了将被替代的旧记忆，建议刷新。")
        if scene.status == "temporary_confirmed" or scene.is_provisional:
            reasons.append("当前场景仍是临时确认，新记忆应保持 provisional。")
        reasons.extend(a_tier_reasons)
        return _unique_strings(reasons)

    def _apply_memory_records(self, plan: MemoryUpdatePlan, scene: Scene) -> None:
        records = self.repositories.memory.list_all()
        by_id = {
            str(record.get("memory_id") or ""): dict(record)
            for record in records
            if isinstance(record, dict) and record.get("memory_id")
        }
        new_ids = [record.memory_id for record in plan.new_memory_records]
        first_new_id = new_ids[0] if new_ids else plan.source_revision_id
        timestamp = now_iso()
        for memory_id in plan.superseded_memory_ids:
            if memory_id not in by_id:
                continue
            if by_id[memory_id].get("status") != "superseded":
                by_id[memory_id]["status"] = "superseded"
                by_id[memory_id]["superseded_by"] = first_new_id
                by_id[memory_id]["superseded_reason"] = "Scene revision memory update plan applied."
                by_id[memory_id]["updated_at"] = timestamp
        for record in plan.new_memory_records:
            data = model_to_dict(record)
            data["status"] = self._memory_status_for_scene(scene)
            data["source_revision_id"] = plan.source_revision_id
            data["source_plan_id"] = plan.memory_update_plan_id
            data["updated_at"] = timestamp
            data["created_at"] = by_id.get(record.memory_id, {}).get("created_at") or data.get("created_at") or timestamp
            by_id[record.memory_id] = data
        self.repositories.memory.write_all(list(by_id.values()))

    def _apply_event_changes(
        self,
        plan: MemoryUpdatePlan,
        scene: Scene,
        candidate: SceneRevisionCandidate,
    ) -> None:
        if not plan.changed_events:
            return
        events = self.repositories.events.list_all()
        by_id = {
            str(event.get("event_id") or ""): dict(event)
            for event in events
            if isinstance(event, dict) and event.get("event_id")
        }
        timestamp = now_iso()
        first_new_id = next(
            (change.new_object_id for change in plan.changed_events if change.new_object_id),
            plan.source_revision_id,
        )
        for change in plan.changed_events:
            if change.old_object_id and change.old_object_id in by_id:
                by_id[change.old_object_id]["status"] = "superseded"
                by_id[change.old_object_id]["superseded_by"] = first_new_id
                by_id[change.old_object_id]["updated_at"] = timestamp
        for index, change in enumerate(plan.changed_events, start=1):
            if change.change_type == "removed" or not change.new_object_id:
                continue
            event_data = _item_at(candidate.memory_extraction.event_summary, index - 1)
            event = Event(
                event_id=change.new_object_id,
                scene_id=scene.scene_id,
                summary=str(event_data.get("summary") or change.new_summary or scene.synopsis),
                participants=_as_strings(
                    event_data.get("participants") or event_data.get("character_ids")
                ),
                location_id=str(event_data.get("location_id") or scene.location),
                cause=str(event_data.get("cause") or "Scene revision was applied."),
                result=str(event_data.get("result") or change.new_summary or scene.synopsis),
                tags=_as_strings(event_data.get("tags")),
                status=self._event_status_for_scene(scene),
                created_at=by_id.get(change.new_object_id, {}).get("created_at") or timestamp,
                updated_at=timestamp,
            )
            data = model_to_dict(event)
            data["source_revision_id"] = plan.source_revision_id
            data["source_plan_id"] = plan.memory_update_plan_id
            by_id[event.event_id] = data
        self.repositories.events.write_all(list(by_id.values()))

    def _apply_state_changes(
        self,
        plan: MemoryUpdatePlan,
        scene: Scene,
        candidate: SceneRevisionCandidate,
        revised_extraction: SceneMemoryExtraction,
    ) -> None:
        if not plan.changed_state_changes:
            return
        changes = self.repositories.state_changes.list_all()
        by_id = {
            str(change.get("state_change_id") or ""): dict(change)
            for change in changes
            if isinstance(change, dict) and change.get("state_change_id")
        }
        timestamp = now_iso()
        first_new_id = next(
            (
                change.new_object_id
                for change in plan.changed_state_changes
                if change.new_object_id
            ),
            plan.source_revision_id,
        )
        for change in plan.changed_state_changes:
            if change.old_object_id and change.old_object_id in by_id:
                by_id[change.old_object_id]["status"] = "superseded"
                by_id[change.old_object_id]["superseded_by"] = first_new_id
                by_id[change.old_object_id]["updated_at"] = timestamp
        for index, change in enumerate(plan.changed_state_changes, start=1):
            if change.change_type == "removed" or not change.new_object_id:
                continue
            change_data = _item_at(candidate.memory_extraction.proposed_state_changes, index - 1)
            state_change = StateChange(
                state_change_id=change.new_object_id,
                target_type=str(change_data.get("target_type") or "scene"),
                target_id=str(change_data.get("target_id") or scene.scene_id),
                before=dict(change_data.get("before") or {}),
                after=dict(change_data.get("after") or {"summary": change.new_summary}),
                reason_event_id=str(change_data.get("reason_event_id") or ""),
                requires_user_confirmation=bool(
                    change_data.get("requires_user_confirmation")
                ),
                status=self._state_change_status_for_scene(scene, change_data),
            )
            data = model_to_dict(state_change)
            data["scene_id"] = scene.scene_id
            data["source_scene_id"] = scene.scene_id
            data["source_revision_id"] = plan.source_revision_id
            data["source_plan_id"] = plan.memory_update_plan_id
            data["created_at"] = by_id.get(change.new_object_id, {}).get("created_at") or timestamp
            data["updated_at"] = timestamp
            by_id[state_change.state_change_id] = data
        self.repositories.state_changes.write_all(list(by_id.values()))
        self._route_character_state_changes_to_pending(
            plan=plan,
            scene=scene,
            proposed_state_changes=revised_extraction.proposed_state_changes,
        )

    def _route_character_state_changes_to_pending(
        self,
        *,
        plan: MemoryUpdatePlan,
        scene: Scene,
        proposed_state_changes: list[dict[str, Any]],
    ) -> None:
        for change in proposed_state_changes:
            if str(change.get("target_type") or "") != "character":
                continue
            character_id = str(change.get("target_id") or "")
            if not character_id:
                continue
            patch = self._proposed_patch_from_state_change(change)
            if not patch:
                continue
            try:
                self.character_state_service.propose_change(
                    ProposedCharacterStateChange(
                        character_id=character_id,
                        source_scene_id=scene.scene_id,
                        source_event_id=str(change.get("reason_event_id") or ""),
                        source_memory_ids=plan.superseded_memory_ids
                        + [record.memory_id for record in plan.new_memory_records],
                        change_type=str(change.get("change_type") or "other"),
                        impact_level=str(change.get("impact_level") or "minor"),
                        summary=str(change.get("summary") or "修订导致角色长期状态变化。"),
                        reason=str(
                            change.get("reason")
                            or "Scene revision memory sync routed the state change."
                        ),
                        proposed_patch=patch,
                    )
                )
            except StorageError as exc:
                if "CHARACTER_NOT_FOUND" in str(exc):
                    continue
                raise

    def _apply_dependent_scene_actions(self, plan: MemoryUpdatePlan) -> None:
        if not plan.dependent_scene_actions:
            return
        action_by_scene = {
            action.dependent_scene_id: action
            for action in plan.dependent_scene_actions
        }
        timestamp = now_iso()
        updated: list[dict[str, Any]] = []
        for raw in self.repositories.scenes.list_all():
            scene_id = str(raw.get("scene_id") or "")
            action = action_by_scene.get(scene_id)
            if action is None:
                updated.append(raw)
                continue
            copy = dict(raw)
            copy["status"] = action.action
            copy["needs_review_reason"] = action.reason
            copy["updated_at"] = timestamp
            updated.append(copy)
        self.repositories.scenes.write_all(updated)

    def _mark_memory_packs_stale(self, plan: MemoryUpdatePlan) -> None:
        if not plan.affected_memory_pack_ids:
            return
        affected = set(plan.affected_memory_pack_ids)
        timestamp = now_iso()
        for repository, id_field in [
            (self.repositories.chapter_memory_packs, "chapter_memory_pack_id"),
            (self.repositories.scene_memory_packs, "scene_memory_pack_id"),
        ]:
            envelope = repository.read_envelope()
            changed = False
            packs: list[dict[str, Any]] = []
            for pack in envelope.get("packs", []):
                if not isinstance(pack, dict):
                    packs.append(pack)
                    continue
                if str(pack.get(id_field) or "") not in affected:
                    packs.append(pack)
                    continue
                updated = dict(pack)
                updated["status"] = "stale"
                updated["updated_at"] = timestamp
                gaps = [
                    dict(gap)
                    for gap in updated.get("retrieval_gaps", [])
                    if isinstance(gap, dict)
                ]
                gap_id = f"memory_sync_stale_{plan.memory_update_plan_id}"
                if not any(gap.get("gap_id") == gap_id for gap in gaps):
                    gaps.append(
                        {
                            "gap_id": gap_id,
                            "gap_type": "stale_pack_source",
                            "severity": "warning",
                            "query_intent": "memory_sync",
                            "message": "记忆同步计划替换了该包引用的旧记忆，建议刷新。",
                            "related_chapter_id": plan.chapter_id,
                            "related_scene_id": plan.scene_id,
                            "related_character_ids": plan.affected_character_ids,
                            "related_keywords": [],
                            "suggested_action": "刷新相关 Chapter/Scene MemoryPack。",
                            "created_at": timestamp,
                        }
                    )
                updated["retrieval_gaps"] = gaps
                packs.append(updated)
                changed = True
            if changed:
                envelope["packs"] = packs
                envelope["updated_at"] = timestamp
                repository.write_envelope(envelope)

    def _replace_plan_status(self, plan: MemoryUpdatePlan, status: str) -> MemoryUpdatePlan:
        updated = MemoryUpdatePlan(
            **{
                **model_to_dict(plan),
                "status": status,
                "updated_at": now_iso(),
            }
        )
        self.repositories.memory_update_plans.upsert(
            model_to_dict(updated),
            "memory_update_plan_id",
        )
        return updated

    def _write_decision(
        self,
        *,
        decision_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decisions = self.repositories.decisions.list_all()
        decision = Decision(
            decision_id=f"decision_memory_sync_{len(decisions) + 1:03d}",
            decision_type=decision_type,
            target_type="memory_update_plan",
            target_id=target_id,
            user_input=user_input,
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.repositories.decisions.write_all(decisions)
        return decision

    def _plan_id(self, scene_id: str, revision_id: str) -> str:
        safe_scene = _safe_id(scene_id)
        safe_revision = _safe_id(revision_id)
        return f"memory_update_plan_{safe_scene}_{safe_revision}"

    def _event_status_for_scene(self, scene: Scene) -> str:
        if scene.status == "temporary_confirmed" or scene.is_provisional:
            return "provisional"
        return "confirmed"

    def _state_change_status_for_scene(
        self,
        scene: Scene,
        change_data: dict[str, Any],
    ) -> str:
        if scene.status == "temporary_confirmed" or scene.is_provisional:
            return "provisional"
        if change_data.get("requires_user_confirmation"):
            return "proposed"
        return str(change_data.get("status") or "confirmed")

    def _proposed_patch_from_state_change(
        self,
        change: dict[str, Any],
    ) -> dict[str, Any]:
        patch = change.get("proposed_patch")
        if isinstance(patch, dict) and patch:
            return patch
        after = change.get("after")
        if isinstance(after, dict) and after:
            return after
        return {}

    def _character_by_id(self) -> dict[str, Character]:
        characters: dict[str, Character] = {}
        for item in self.repositories.characters.list_all():
            try:
                character = Character(**item)
            except ValidationError:
                continue
            characters[character.character_id] = character
        return characters

    def _dedupe_actions(
        self,
        actions: list[DependentSceneAction],
    ) -> list[DependentSceneAction]:
        best_rank = {
            "continuity_recheck": 1,
            "needs_review": 2,
            "needs_regeneration": 3,
        }
        by_scene: dict[str, DependentSceneAction] = {}
        for action in actions:
            existing = by_scene.get(action.dependent_scene_id)
            if existing is None or best_rank[action.action] > best_rank[existing.action]:
                by_scene[action.dependent_scene_id] = action
        return list(by_scene.values())


def _as_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    return [
        str(item).strip()
        for item in values
        if str(item or "").strip()
    ]


def _unique_strings(values: list[str]) -> list[str]:
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


def _safe_id(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in str(value or "").strip()
    )


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _item_at(items: list[dict[str, Any]], index: int) -> dict[str, Any]:
    if index < 0 or index >= len(items):
        return {}
    item = items[index]
    return dict(item) if isinstance(item, dict) else {}
