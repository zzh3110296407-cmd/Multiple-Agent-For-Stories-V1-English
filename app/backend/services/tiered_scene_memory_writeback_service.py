from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.event import Event
from app.backend.models.memory_record import MEMORY_M2_VERSION_ID, MemoryRecord
from app.backend.models.role_memory_writeback import (
    ROLE_MEMORY_WRITEBACK_VERSION_ID,
    RoleMemoryWriteAudit,
    RoleSceneMemoryEntry,
    TieredMemoryWritePolicy,
    TieredSceneMemoryWritePlan,
    TieredSceneMemoryWritebackResponse,
)
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import SceneMemoryExtraction
from app.backend.models.scene_participation import SceneParticipationPackage
from app.backend.models.state_change import StateChange
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


COMMITTED_SCENE_STATUSES = {"confirmed", "revised", "temporary_confirmed"}
FINAL_COMMIT_TYPES = {"confirmed", "revised"}
TIER_MAX_SUMMARY_CHARS = {"A": 900, "B": 500, "C": 280, "D": 160}
TIER_DENSITIES = {"A": "full", "B": "medium", "C": "compact", "D": "minimal"}
SUBJECTIVE_MEMORY_TRUTH_STATUSES = {
    "unverified_claim",
    "rumor",
    "lie",
    "misinformation",
}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class TieredSceneMemoryWritebackService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.plans_file = self.data_dir / "tiered_scene_memory_write_plans.json"
        self.entries_file = self.data_dir / "role_scene_memory_entries.json"
        self.audits_file = self.data_dir / "role_memory_write_audits.json"
        self.policy_file = self.data_dir / "tiered_memory_write_policy.json"
        self.scene_participation_packages_file = (
            self.data_dir / "scene_participation_packages.json"
        )
        self.character_intent_packages_file = (
            self.data_dir / "tiered_character_intent_packages.json"
        )
        self.character_intent_candidates_file = (
            self.data_dir / "character_action_intention_candidates.json"
        )
        self.character_intent_risk_reports_file = (
            self.data_dir / "character_intent_risk_reports.json"
        )
        self.abcd_story_information_packages_file = (
            self.data_dir / "abcd_story_information_packages.json"
        )
        self.abcd_story_information_items_file = (
            self.data_dir / "character_intent_story_information_items.json"
        )

    def build_plan_for_committed_scene(
        self,
        *,
        scene: Scene,
        commit_type: str,
        events: list[Event],
        state_changes: list[StateChange],
        extraction: SceneMemoryExtraction,
        generic_memory_records: list[MemoryRecord],
        force_rebuild: bool = False,
    ) -> TieredSceneMemoryWritebackResponse:
        normalized_commit_type = str(commit_type or "").strip()
        self._require_committed_scene(scene, normalized_commit_type)
        timestamp = utc_now()
        policy = self._ensure_policy(timestamp)
        commit_key = self._commit_key(normalized_commit_type)
        target_memory_status = (
            policy.final_commit_status
            if normalized_commit_type in FINAL_COMMIT_TYPES
            else policy.temporary_commit_status
        )
        participation = self._find_scene_participation_package(scene)
        warnings: list[str] = []
        if participation is None:
            warnings.append("scene_participation_package_missing")
            participants = []
        else:
            participants = list(participation.participants)
            participants = self._filter_participants_to_scene_text(
                scene=scene,
                participants=participants,
                warnings=warnings,
            )
        m6_package = self._find_m6_package(scene, participation)
        m7_package = self._find_m7_package(scene, participation, m6_package)
        strict_lineage_required = participation is not None
        if strict_lineage_required and m6_package is None:
            warnings.append("m6_exact_package_missing_for_scene_participation")
        if strict_lineage_required and m7_package is None:
            warnings.append("m7_exact_package_missing_for_scene_participation")
        candidates = self._read_character_intent_candidates(
            scene,
            m6_package,
            allow_scene_fallback=not strict_lineage_required,
        )
        risk_reports = self._read_risk_reports(
            scene,
            m6_package,
            allow_scene_fallback=not strict_lineage_required,
        )
        m7_items = self._read_m7_items(
            scene,
            m7_package,
            allow_scene_fallback=not strict_lineage_required,
        )
        m7_items, ignored_do_not_use_items = self._split_m7_writable_items(
            m7_items,
            m7_package,
        )
        if ignored_do_not_use_items:
            warnings.append(
                "m7_do_not_use_items_ignored:"
                + ",".join(
                    self._unique(
                        [
                            item.get("item_id")
                            for item in ignored_do_not_use_items
                        ]
                    )
                )
            )
        character_names = self._character_names()
        entry_models = [
            self._build_entry(
                scene=scene,
                commit_key=commit_key,
                participant=participant,
                character_name=character_names.get(
                    participant.character_id,
                    participant.name,
                ),
                target_memory_status=target_memory_status,
                events=events,
                state_changes=state_changes,
                extraction=extraction,
                generic_memory_records=generic_memory_records,
                candidates=[
                    candidate
                    for candidate in candidates
                    if str(candidate.get("character_id") or "") == participant.character_id
                ],
                risk_reports=[
                    report
                    for report in risk_reports
                    if str(report.get("character_id") or "") == participant.character_id
                ],
                m7_items=[
                    item
                    for item in m7_items
                    if str(item.get("character_id") or "") == participant.character_id
                ],
                timestamp=timestamp,
            )
            for participant in participants
        ]
        memory_records = [
            self._memory_record_for_entry(
                entry=entry,
                scene=scene,
                target_memory_status=target_memory_status,
                timestamp=timestamp,
            )
            for entry in entry_models
            if entry.status == "written"
        ]
        for entry in entry_models:
            if entry.status == "written":
                entry.target_memory_record_id = f"role_memory_{entry.role_scene_memory_entry_id}"
        plan = self._build_plan(
            scene=scene,
            commit_type=normalized_commit_type,
            commit_key=commit_key,
            target_memory_status=target_memory_status,
            participation=participation,
            m6_package=m6_package,
            m7_package=m7_package,
            entries=entry_models,
            memory_records=memory_records,
            warnings=warnings,
            timestamp=timestamp,
        )
        audit = self._build_audit(
            scene=scene,
            commit_key=commit_key,
            plan=plan,
            entries=entry_models,
            warnings=warnings,
            timestamp=timestamp,
        )
        if force_rebuild:
            self._prune_obsolete_scene_commit_role_memory(
                scene=scene,
                commit_key=commit_key,
                retained_entry_ids=[
                    entry.role_scene_memory_entry_id for entry in entry_models
                ],
                retained_memory_ids=[record.memory_id for record in memory_records],
            )
        self._upsert_models(self.entries_file, entry_models, "role_scene_memory_entry_id")
        self._upsert_models(self.plans_file, [plan], "tiered_scene_memory_write_plan_id")
        self._upsert_memory_records(memory_records)
        self._upsert_models(self.audits_file, [audit], "role_memory_write_audit_id")
        return TieredSceneMemoryWritebackResponse(
            plan=plan,
            entries=entry_models,
            memory_records=[model_to_dict(record) for record in memory_records],
            audits=[audit],
            policy=policy,
            warnings=warnings,
        )

    def _filter_participants_to_scene_text(
        self,
        *,
        scene: Scene,
        participants: list[Any],
        warnings: list[str],
    ) -> list[Any]:
        if not participants:
            return []
        content = getattr(scene, "content", None)
        text = " ".join(
            str(value or "")
            for value in [
                getattr(content, "synopsis", ""),
                getattr(content, "prose_text", ""),
                getattr(scene, "scene_goal", ""),
            ]
        )
        if not text.strip():
            return participants
        visible: list[Any] = []
        removed: list[str] = []
        for participant in participants:
            character_id = str(getattr(participant, "character_id", "") or "")
            name = str(getattr(participant, "name", "") or "")
            role_label = str(getattr(participant, "role_label", "") or "")
            candidates = [character_id, name, role_label]
            if any(candidate and candidate in text for candidate in candidates):
                visible.append(participant)
            else:
                removed.append(character_id)
        if visible and removed:
            warnings.append(
                "participants_filtered_not_visible_in_scene_text:"
                + ",".join(self._unique(removed))
            )
            return visible
        return participants

    def rebuild_write_plan_for_scene(
        self,
        scene_id: str,
        *,
        force_rebuild: bool = True,
    ) -> TieredSceneMemoryWritebackResponse:
        scene = self._get_scene(scene_id)
        commit_type = scene.status
        events = [
            Event(**event)
            for event in self.repositories.events.list_all()
            if event.get("scene_id") == scene.scene_id
        ]
        event_ids = {event.event_id for event in events}
        state_changes = [
            StateChange(**change)
            for change in self.repositories.state_changes.list_all()
            if change.get("reason_event_id") in event_ids
            or change.get("target_id") == scene.scene_id
            or change.get("state_change_id") in scene.state_change_ids
        ]
        generic_memory_records = [
            MemoryRecord(**memory)
            for memory in self.repositories.memory.list_all()
            if memory.get("scene_id") == scene.scene_id
            and str(memory.get("source_object_type") or "")
            != "role_scene_memory_entry"
        ]
        return self.build_plan_for_committed_scene(
            scene=scene,
            commit_type=commit_type,
            events=events,
            state_changes=state_changes,
            extraction=scene.memory_extraction,
            generic_memory_records=generic_memory_records,
            force_rebuild=force_rebuild,
        )

    def list_plans(self, scene_id: str | None = None) -> list[TieredSceneMemoryWritePlan]:
        plans = self._read_models(self.plans_file, TieredSceneMemoryWritePlan)
        if scene_id:
            plans = [plan for plan in plans if plan.scene_id == scene_id]
        return sorted(plans, key=lambda plan: plan.updated_at, reverse=True)

    def get_plan(self, plan_id: str) -> TieredSceneMemoryWritePlan:
        for plan in self.list_plans():
            if plan.tiered_scene_memory_write_plan_id == plan_id:
                return plan
        raise StorageError(f"TIERED_MEMORY_WRITEBACK_PLAN_NOT_FOUND: {plan_id}")

    def list_entries(
        self,
        *,
        scene_id: str | None = None,
        character_id: str | None = None,
    ) -> list[RoleSceneMemoryEntry]:
        entries = self._read_models(self.entries_file, RoleSceneMemoryEntry)
        if scene_id:
            entries = [entry for entry in entries if entry.scene_id == scene_id]
        if character_id:
            entries = [entry for entry in entries if entry.character_id == character_id]
        return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)

    def get_entry(self, entry_id: str) -> RoleSceneMemoryEntry:
        for entry in self.list_entries():
            if entry.role_scene_memory_entry_id == entry_id:
                return entry
        raise StorageError(f"TIERED_MEMORY_WRITEBACK_ENTRY_NOT_FOUND: {entry_id}")

    def get_audit(self, audit_id: str) -> RoleMemoryWriteAudit:
        for audit in self._read_models(self.audits_file, RoleMemoryWriteAudit):
            if audit.role_memory_write_audit_id == audit_id:
                return audit
        raise StorageError(f"TIERED_MEMORY_WRITEBACK_AUDIT_NOT_FOUND: {audit_id}")

    def record_writeback_failure(
        self,
        *,
        scene: Scene,
        commit_type: str,
        error_message: str,
    ) -> RoleMemoryWriteAudit:
        timestamp = utc_now()
        commit_key = (
            self._commit_key(commit_type)
            if commit_type in COMMITTED_SCENE_STATUSES
            else self._slug(commit_type)
        )
        audit = RoleMemoryWriteAudit(
            role_memory_write_audit_id=(
                f"role_memory_audit_{self._slug(scene.scene_id)}_{commit_key}_failure"
            ),
            project_id=scene.project_id,
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scene_index=scene.scene_index,
            tiered_scene_memory_write_plan_id=(
                f"tiered_write_plan_{self._slug(scene.scene_id)}_{commit_key}"
            ),
            issues=["post_commit_writeback_failed"],
            warnings=[self._short_text(error_message, 240)],
            status="failed",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._upsert_models(
            self.audits_file,
            [audit],
            "role_memory_write_audit_id",
        )
        return audit

    def _require_committed_scene(self, scene: Scene, commit_type: str) -> None:
        if commit_type not in COMMITTED_SCENE_STATUSES:
            raise StorageError(
                "TIERED_MEMORY_WRITEBACK_COMMIT_TYPE_INVALID: commit_type must be confirmed, revised, or temporary_confirmed."
            )
        if scene.status not in COMMITTED_SCENE_STATUSES:
            raise StorageError(
                "TIERED_MEMORY_WRITEBACK_COMMIT_REQUIRED: role memory writeback requires a committed scene."
            )
        if commit_type != scene.status and not (
            commit_type == "confirmed" and scene.status == "revised"
        ):
            raise StorageError(
                "TIERED_MEMORY_WRITEBACK_COMMIT_TYPE_MISMATCH: scene status and commit type do not match."
            )

    def _build_entry(
        self,
        *,
        scene: Scene,
        commit_key: str,
        participant,
        character_name: str,
        target_memory_status: str,
        events: list[Event],
        state_changes: list[StateChange],
        extraction: SceneMemoryExtraction,
        generic_memory_records: list[MemoryRecord],
        candidates: list[dict[str, Any]],
        risk_reports: list[dict[str, Any]],
        m7_items: list[dict[str, Any]],
        timestamp: str,
    ) -> RoleSceneMemoryEntry:
        tier = str(participant.tier or "").strip().upper()
        if tier not in {"A", "B", "C", "D"}:
            raise StorageError("TIERED_MEMORY_WRITEBACK_PARTICIPANT_TIER_REQUIRED")
        entry_type, truth_status, objective_truth = self._entry_truth(
            candidates,
            m7_items,
        )
        character_id = participant.character_id
        state_change_ids = [
            change.state_change_id
            for change in state_changes
            if change.target_id == character_id
        ]
        event_ids = [
            event.event_id
            for event in events
            if not event.participants or character_id in event.participants
        ] or [event.event_id for event in events]
        source_memory_ids = self._unique(
            [
                *[
                    memory.memory_id
                    for memory in generic_memory_records
                    if character_id in memory.character_ids
                ],
                *[
                    str(item.get("source_memory_id") or "")
                    for item in m7_items
                    if item.get("source_memory_id")
                ],
            ]
        )
        candidate_ids = self._unique(
            [str(candidate.get("action_intention_candidate_id") or "") for candidate in candidates]
        )
        story_information_ids = self._unique(
            [str(item.get("item_id") or "") for item in m7_items]
        )
        requires_confirmation = any(
            bool(candidate.get("requires_user_confirmation_candidate"))
            or str(candidate.get("continuity_risk_level") or "") in {"high", "blocking"}
            for candidate in candidates
        ) or any(
            bool(report.get("possible_major_state_change"))
            or str(report.get("risk_level") or "") in {"high", "blocking"}
            for report in risk_reports
        )
        summary = self._entry_summary(
            scene=scene,
            character_name=character_name or character_id,
            tier=tier,
            entry_type=entry_type,
            m7_items=m7_items,
            events=events,
            extraction=extraction,
        )
        entry_id = f"role_entry_{self._slug(scene.scene_id)}_{commit_key}_{self._slug(character_id)}"
        memory_record_id = f"role_memory_{entry_id}"
        continuity_flags = []
        if requires_confirmation:
            continuity_flags.append("major_or_blocking_candidate_not_auto_applied")
        if target_memory_status == "provisional":
            continuity_flags.append("temporary_confirmed_memory")
        return RoleSceneMemoryEntry(
            role_scene_memory_entry_id=entry_id,
            project_id=scene.project_id,
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scene_index=scene.scene_index,
            character_id=character_id,
            character_name=character_name or character_id,
            tier=tier,
            entry_type=entry_type,
            memory_summary=summary,
            known_facts=[summary] if truth_status == "objective_fact" else [],
            perceived_facts=[summary] if entry_type == "perception" else [],
            claims_made=[summary] if entry_type == "spoken_claim" else [],
            actions_taken=[summary] if entry_type == "action" else [],
            commitments_or_tasks=[],
            continuity_flags=continuity_flags,
            truth_status=truth_status,
            objective_truth=objective_truth,
            source_event_ids=event_ids,
            source_state_change_ids=state_change_ids,
            source_memory_ids=source_memory_ids,
            source_intention_candidate_ids=candidate_ids,
            source_story_information_item_ids=story_information_ids,
            target_memory_record_id=memory_record_id,
            memory_density=TIER_DENSITIES[tier],
            status="written",
            safe_summary=self._short_text(summary, 180),
            warnings=continuity_flags,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _memory_record_for_entry(
        self,
        *,
        entry: RoleSceneMemoryEntry,
        scene: Scene,
        target_memory_status: str,
        timestamp: str,
    ) -> MemoryRecord:
        truth_status = self._supported_memory_truth_status(entry.truth_status)
        objective_truth = (
            False if truth_status in SUBJECTIVE_MEMORY_TRUTH_STATUSES else entry.objective_truth
        )
        return MemoryRecord(
            memory_id=entry.target_memory_record_id,
            project_id=entry.project_id,
            source_object_type="role_scene_memory_entry",
            source_object_id=entry.role_scene_memory_entry_id,
            chapter_id=entry.chapter_id,
            scene_id=entry.scene_id,
            memory_type="character",
            summary=entry.memory_summary,
            keywords=self._unique(
                [
                    entry.character_id,
                    entry.tier,
                    entry.entry_type,
                    entry.memory_density,
                    "role_memory",
                    scene.location,
                ]
            ),
            character_ids=[entry.character_id],
            relationship_ids=[],
            location=scene.location or None,
            event_ids=entry.source_event_ids,
            importance={"A": "high", "B": "medium", "C": "medium", "D": "low"}[entry.tier],
            status=target_memory_status,
            truth_status=truth_status,
            objective_truth=objective_truth,
            speaker_character_id=entry.character_id if entry.entry_type == "spoken_claim" else "",
            believed_by_character_ids=[entry.character_id]
            if truth_status in {"unverified_claim", "rumor"}
            else [],
            known_false_by_character_ids=[entry.character_id]
            if truth_status in {"lie", "misinformation"}
            else [],
            version_id=ROLE_MEMORY_WRITEBACK_VERSION_ID,
            created_at=timestamp,
            updated_at=timestamp,
            source_type="role_memory_writeback",
            object_type="role_scene_memory_entry",
            object_id=entry.role_scene_memory_entry_id,
            tags=[entry.tier, entry.entry_type, "role_memory"],
        )

    def _build_plan(
        self,
        *,
        scene: Scene,
        commit_type: str,
        commit_key: str,
        target_memory_status: str,
        participation: SceneParticipationPackage | None,
        m6_package: dict[str, Any] | None,
        m7_package: dict[str, Any] | None,
        entries: list[RoleSceneMemoryEntry],
        memory_records: list[MemoryRecord],
        warnings: list[str],
        timestamp: str,
    ) -> TieredSceneMemoryWritePlan:
        counts = {tier: len([entry for entry in entries if entry.tier == tier]) for tier in ["A", "B", "C", "D"]}
        subjective_count = len(
            [
                record
                for record in memory_records
                if record.truth_status in SUBJECTIVE_MEMORY_TRUTH_STATUSES
            ]
        )
        objective_count = len(memory_records) - subjective_count
        return TieredSceneMemoryWritePlan(
            tiered_scene_memory_write_plan_id=(
                f"tiered_write_plan_{self._slug(scene.scene_id)}_{commit_key}"
            ),
            project_id=scene.project_id,
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scene_index=scene.scene_index,
            scene_participation_package_id=(
                participation.scene_participation_package_id if participation else ""
            ),
            tiered_character_intent_package_id=str(
                (m6_package or {}).get("tiered_character_intent_package_id") or ""
            ),
            abcd_story_information_package_id=str(
                (m7_package or {}).get("abcd_story_information_package_id") or ""
            ),
            commit_type=commit_type,
            target_memory_status=target_memory_status,
            role_memory_entry_ids=[entry.role_scene_memory_entry_id for entry in entries],
            target_memory_record_ids=[record.memory_id for record in memory_records],
            a_entry_count=counts["A"],
            b_entry_count=counts["B"],
            c_entry_count=counts["C"],
            d_entry_count=counts["D"],
            objective_memory_count=objective_count,
            subjective_memory_count=subjective_count,
            blocked_memory_count=len([entry for entry in entries if entry.status == "blocked"]),
            requires_user_confirmation_count=len(
                [
                    entry
                    for entry in entries
                    if "major_or_blocking_candidate_not_auto_applied"
                    in entry.continuity_flags
                ]
            ),
            safe_summary=self._short_text(
                f"Role memory writeback for scene {scene.scene_id}: {len(memory_records)} scoped memories.",
                220,
            ),
            warnings=warnings,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _build_audit(
        self,
        *,
        scene: Scene,
        commit_key: str,
        plan: TieredSceneMemoryWritePlan,
        entries: list[RoleSceneMemoryEntry],
        warnings: list[str],
        timestamp: str,
    ) -> RoleMemoryWriteAudit:
        issues: list[str] = []
        all_entries_have_tier = all(entry.tier in {"A", "B", "C", "D"} for entry in entries)
        all_entries_have_source_scene = all(entry.scene_id == scene.scene_id for entry in entries)
        all_subjective_entries_non_objective = all(
            entry.objective_truth is False
            for entry in entries
            if entry.truth_status in SUBJECTIVE_MEMORY_TRUTH_STATUSES
        )
        d_tier_entries_minimal = all(
            len(entry.memory_summary) <= TIER_MAX_SUMMARY_CHARS["D"]
            for entry in entries
            if entry.tier == "D"
        )
        if not all_entries_have_tier:
            issues.append("entry_missing_tier")
        if not all_entries_have_source_scene:
            issues.append("entry_missing_source_scene")
        if not all_subjective_entries_non_objective:
            issues.append("subjective_entry_marked_objective")
        if not d_tier_entries_minimal:
            issues.append("d_tier_entry_not_minimal")
        return RoleMemoryWriteAudit(
            role_memory_write_audit_id=f"role_memory_audit_{self._slug(scene.scene_id)}_{commit_key}",
            project_id=scene.project_id,
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scene_index=scene.scene_index,
            tiered_scene_memory_write_plan_id=plan.tiered_scene_memory_write_plan_id,
            all_entries_have_tier=all_entries_have_tier,
            all_entries_have_source_scene=all_entries_have_source_scene,
            all_subjective_entries_non_objective=all_subjective_entries_non_objective,
            d_tier_entries_minimal=d_tier_entries_minimal,
            issues=issues,
            warnings=warnings,
            status="pass" if not issues else "failed",
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _entry_truth(
        self,
        candidates: list[dict[str, Any]],
        m7_items: list[dict[str, Any]],
    ) -> tuple[str, str, bool]:
        statuses = [
            str(candidate.get("truth_status") or "")
            for candidate in candidates
            if candidate.get("truth_status")
        ]
        statuses.extend(
            [
                str(item.get("truth_status") or "")
                for item in m7_items
                if item.get("truth_status")
            ]
        )
        normalized = {status.strip().casefold() for status in statuses if status.strip()}
        if "lie" in normalized:
            return "misinformation", "lie", False
        if "misinformation" in normalized:
            return "misinformation", "misinformation", False
        if "perception" in normalized:
            return "perception", "unverified_claim", False
        if "subjective_claim" in normalized or "unknown" in normalized:
            return "spoken_claim", "unverified_claim", False
        if "objective_candidate" in normalized:
            return "action", "objective_fact", True
        return "action", "objective_fact", True

    def _entry_summary(
        self,
        *,
        scene: Scene,
        character_name: str,
        tier: str,
        entry_type: str,
        m7_items: list[dict[str, Any]],
        events: list[Event],
        extraction: SceneMemoryExtraction,
    ) -> str:
        safe_bits = [
            str(item.get("safe_summary") or "")
            for item in m7_items
            if str(item.get("safe_summary") or "").strip()
            and str(item.get("m7_semantic_type") or "") != "do_not_use"
        ]
        event_summary = " ".join(event.summary for event in events if event.summary)
        extraction_summary = " ".join(
            str(item.get("summary") or "")
            for item in extraction.event_summary
            if isinstance(item, dict)
        )
        base = (
            safe_bits[0]
            if safe_bits
            else event_summary
            or extraction_summary
            or scene.synopsis
            or scene.goal
            or f"{character_name} participated in scene {scene.scene_index}."
        )
        if entry_type == "perception":
            text = f"{character_name} perceived scene {scene.scene_index}: {base}"
        elif entry_type == "spoken_claim":
            text = f"{character_name} carries an unverified claim from scene {scene.scene_index}: {base}"
        elif entry_type == "misinformation":
            text = f"{character_name} carries a non-objective or false-information memory from scene {scene.scene_index}: {base}"
        else:
            text = f"{character_name} participated in scene {scene.scene_index}: {base}"
        return self._short_text(text, TIER_MAX_SUMMARY_CHARS[tier])

    def _ensure_policy(self, timestamp: str) -> TieredMemoryWritePolicy:
        if self.store.exists(self.policy_file):
            try:
                return TieredMemoryWritePolicy(**self.store.read(self.policy_file))
            except (ValidationError, StorageError):
                pass
        policy = TieredMemoryWritePolicy(
            project_id=self._current_project_id(),
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.store.write(self.policy_file, model_to_dict(policy))
        return policy

    def _find_scene_participation_package(
        self,
        scene: Scene,
    ) -> SceneParticipationPackage | None:
        packages = self._read_models(
            self.scene_participation_packages_file,
            SceneParticipationPackage,
        )
        eligible = [
            package
            for package in packages
            if package.status in {"ready", "warning"}
        ]
        exact = [package for package in eligible if package.scene_id == scene.scene_id]
        if exact:
            return sorted(exact, key=lambda package: package.updated_at, reverse=True)[0]
        candidates = [
            package
            for package in eligible
            if package.chapter_id == scene.chapter_id
            and package.scene_index == scene.scene_index
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda package: package.updated_at, reverse=True)[0]

    def _find_m6_package(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
    ) -> dict[str, Any] | None:
        packages = self._read_dicts(self.character_intent_packages_file)
        participation_id = (
            participation.scene_participation_package_id if participation else ""
        )
        eligible = [
            package
            for package in packages
            if str(package.get("status") or "ready") in {"ready", "warning"}
        ]
        if participation_id:
            exact = [
                package
                for package in eligible
                if package.get("scene_participation_package_id") == participation_id
            ]
            if exact:
                return sorted(
                    exact,
                    key=lambda item: str(item.get("updated_at") or ""),
                    reverse=True,
                )[0]
            return None
        candidates = [
            package
            for package in eligible
            if package.get("scene_id") == scene.scene_id
            or (
                package.get("chapter_id") == scene.chapter_id
                and int(package.get("scene_index") or 0) == scene.scene_index
            )
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[0]

    def _find_m7_package(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
        m6_package: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        packages = self._read_dicts(self.abcd_story_information_packages_file)
        m6_id = str((m6_package or {}).get("tiered_character_intent_package_id") or "")
        participation_id = (
            participation.scene_participation_package_id if participation else ""
        )
        eligible = [
            package
            for package in packages
            if str(package.get("status") or "ready") in {"ready", "warning"}
        ]
        if m6_id:
            exact = [
                package
                for package in eligible
                if package.get("source_tiered_character_intent_package_id") == m6_id
            ]
            if exact:
                return sorted(
                    exact,
                    key=lambda item: str(item.get("updated_at") or ""),
                    reverse=True,
                )[0]
            return None
        if participation_id:
            exact = [
                package
                for package in eligible
                if package.get("source_scene_participation_package_id") == participation_id
            ]
            if exact:
                return sorted(
                    exact,
                    key=lambda item: str(item.get("updated_at") or ""),
                    reverse=True,
                )[0]
            return None
        candidates = [
            package
            for package in eligible
            if package.get("scene_id") == scene.scene_id
            or (
                package.get("chapter_id") == scene.chapter_id
                and int(package.get("scene_index") or 0) == scene.scene_index
            )
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[0]

    def _read_character_intent_candidates(
        self,
        scene: Scene,
        m6_package: dict[str, Any] | None,
        *,
        allow_scene_fallback: bool = True,
    ) -> list[dict[str, Any]]:
        items = self._read_dicts(self.character_intent_candidates_file)
        if m6_package is not None:
            ids = set((m6_package or {}).get("action_intention_candidate_ids") or [])
            if not ids:
                return []
            return [
                item
                for item in items
                if item.get("action_intention_candidate_id") in ids
            ]
        if not allow_scene_fallback:
            return []
        return [
            item
            for item in items
            if item.get("chapter_id") == scene.chapter_id
            and int(item.get("scene_index") or 0) == scene.scene_index
        ]

    def _read_risk_reports(
        self,
        scene: Scene,
        m6_package: dict[str, Any] | None,
        *,
        allow_scene_fallback: bool = True,
    ) -> list[dict[str, Any]]:
        items = self._read_dicts(self.character_intent_risk_reports_file)
        if m6_package is not None:
            ids = set((m6_package or {}).get("risk_report_ids") or [])
            if not ids:
                return []
            return [item for item in items if item.get("risk_report_id") in ids]
        if not allow_scene_fallback:
            return []
        return [
            item
            for item in items
            if item.get("chapter_id") == scene.chapter_id
            and int(item.get("scene_index") or 0) == scene.scene_index
        ]

    def _read_m7_items(
        self,
        scene: Scene,
        m7_package: dict[str, Any] | None,
        *,
        allow_scene_fallback: bool = True,
    ) -> list[dict[str, Any]]:
        items = self._read_dicts(self.abcd_story_information_items_file)
        if m7_package is not None:
            ids = set((m7_package or {}).get("item_ids") or [])
            if not ids:
                return []
            return [item for item in items if item.get("item_id") in ids]
        if not allow_scene_fallback:
            return []
        return [
            item
            for item in items
            if item.get("chapter_id") == scene.chapter_id
            and int(item.get("scene_index") or 0) == scene.scene_index
        ]

    def _split_m7_writable_items(
        self,
        items: list[dict[str, Any]],
        m7_package: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        do_not_use_ids = {
            str(item_id or "").strip()
            for item_id in (m7_package or {}).get("do_not_use_item_ids", [])
            if str(item_id or "").strip()
        }
        writable: list[dict[str, Any]] = []
        ignored: list[dict[str, Any]] = []
        for item in items:
            if self._is_m7_do_not_use_item(item, do_not_use_ids):
                ignored.append(item)
            else:
                writable.append(item)
        return writable, ignored

    def _is_m7_do_not_use_item(
        self,
        item: dict[str, Any],
        do_not_use_ids: set[str],
    ) -> bool:
        item_id = str(item.get("item_id") or "").strip()
        base_item = item.get("base_story_information_item") or {}
        base_priority = ""
        if isinstance(base_item, dict):
            base_priority = str(base_item.get("priority") or "").strip()
        return (
            item_id in do_not_use_ids
            or str(item.get("m7_semantic_type") or "").strip() == "do_not_use"
            or base_priority == "do_not_use"
        )

    def _character_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for character in self.repositories.characters.list_all():
            character_id = str(character.get("character_id") or "")
            if character_id:
                names[character_id] = str(character.get("name") or character_id)
        return names

    def _get_scene(self, scene_id: str) -> Scene:
        scene = self.repositories.scenes.get_by_id(scene_id)
        if scene is None:
            raise StorageError(f"TIERED_MEMORY_WRITEBACK_SCENE_NOT_FOUND: {scene_id}")
        return Scene(**scene)

    def _upsert_models(
        self,
        path: Path,
        models: list[BaseModel],
        id_field: str,
    ) -> None:
        existing = self._read_dicts(path)
        by_id = {
            str(item.get(id_field) or ""): dict(item)
            for item in existing
            if item.get(id_field)
        }
        for model in models:
            payload = model_to_dict(model)
            by_id[str(payload[id_field])] = payload
        self.store.write(path, list(by_id.values()))

    def _prune_obsolete_scene_commit_role_memory(
        self,
        *,
        scene: Scene,
        commit_key: str,
        retained_entry_ids: list[str],
        retained_memory_ids: list[str],
    ) -> None:
        scene_id = str(scene.scene_id or "")
        if not scene_id:
            return
        entry_prefix = f"role_entry_{self._slug(scene_id)}_{commit_key}_"
        retained_entries = set(self._unique(retained_entry_ids))
        retained_memories = set(self._unique(retained_memory_ids))

        entries = self._read_dicts(self.entries_file)
        pruned_entries = [
            entry
            for entry in entries
            if not (
                str(entry.get("scene_id") or "") == scene_id
                and str(entry.get("role_scene_memory_entry_id") or "").startswith(entry_prefix)
                and str(entry.get("role_scene_memory_entry_id") or "") not in retained_entries
            )
        ]
        if len(pruned_entries) != len(entries):
            self.store.write(self.entries_file, pruned_entries)

        records = self.repositories.memory.list_all()
        pruned_records = [
            record
            for record in records
            if not (
                str(record.get("scene_id") or "") == scene_id
                and str(record.get("source_object_type") or "")
                == "role_scene_memory_entry"
                and str(record.get("source_object_id") or "").startswith(entry_prefix)
                and str(record.get("memory_id") or "") not in retained_memories
            )
        ]
        if len(pruned_records) != len(records):
            self.repositories.memory.write_all(pruned_records)

    def _upsert_memory_records(self, records: list[MemoryRecord]) -> None:
        existing = self.repositories.memory.list_all()
        by_id = {
            str(item.get("memory_id") or ""): dict(item)
            for item in existing
            if item.get("memory_id")
        }
        for record in records:
            by_id[record.memory_id] = model_to_dict(record)
        self.repositories.memory.write_all(list(by_id.values()))

    def _read_models(self, path: Path, model_cls: type[BaseModel]) -> list[Any]:
        models: list[Any] = []
        for item in self._read_dicts(path):
            try:
                models.append(model_cls(**item))
            except ValidationError as exc:
                raise StorageError(f"{path.name} schema is invalid.") from exc
        return models

    def _read_dicts(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        data = self.store.read_any(path)
        if isinstance(data, dict):
            if isinstance(data.get("packs"), list):
                data = data["packs"]
            elif isinstance(data.get("items"), list):
                data = data["items"]
            else:
                data = [data]
        if not isinstance(data, list):
            raise StorageError(f"{path.name} must contain a JSON list.")
        return [dict(item) for item in data if isinstance(item, dict)]

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback="local_project",
        )

    def _commit_key(self, commit_type: str) -> str:
        return "temporary" if commit_type == "temporary_confirmed" else "final"

    def _supported_memory_truth_status(self, truth_status: str) -> str:
        if truth_status == "perception":
            return "unverified_claim"
        if truth_status in {
            "objective_fact",
            "unverified_claim",
            "rumor",
            "lie",
            "misinformation",
        }:
            return truth_status
        return "unverified_claim"

    def _short_text(self, text: str, max_len: int) -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) <= max_len:
            return clean
        return clean[: max_len - 3].rstrip() + "..."

    def _unique(self, values: list[Any]) -> list[str]:
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

    def _slug(self, value: Any) -> str:
        text = str(value or "").strip()
        return "".join(
            char if char.isalnum() or char in {"_", "-"} else "_"
            for char in text
        ).strip("_") or "unknown"
