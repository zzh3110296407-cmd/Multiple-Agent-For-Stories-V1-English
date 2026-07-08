from typing import Any

from app.backend.models.abcd_runtime_gate import ABCDObjectiveFactBoundaryReport
from app.backend.models.memory_record import MemoryRecord
from app.backend.models.role_memory_writeback import RoleSceneMemoryEntry
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.objective_fact_write_guard import ObjectiveFactWriteGuard


NON_OBJECTIVE_M6_TRUTH_STATUSES = {
    "subjective_claim",
    "perception",
    "lie",
    "misinformation",
    "unknown",
}
NON_OBJECTIVE_ROLE_MEMORY_TRUTH_STATUSES = {
    "unverified_claim",
    "rumor",
    "lie",
    "misinformation",
}


class ABCDObjectiveFactBoundaryService:
    def __init__(
        self,
        *,
        objective_fact_write_guard: ObjectiveFactWriteGuard | None = None,
    ) -> None:
        self.objective_fact_write_guard = (
            objective_fact_write_guard or ObjectiveFactWriteGuard()
        )

    def build_report(self, bundle: dict[str, Any]) -> ABCDObjectiveFactBoundaryReport:
        context = bundle["context"]
        timestamp = utc_now()
        blocked_ids: list[str] = []
        blocked_role_memory_artifact_ids: list[str] = []
        warnings: list[str] = []
        allowed_count = 0

        do_not_use_item_ids = {
            item.item_id
            for item in bundle.get("story_information_items") or []
            if item.m7_semantic_type == "do_not_use"
            or item.base_story_information_item.priority == "do_not_use"
        }

        subjective_claims_kept_subjective = True
        perceptions_kept_subjective = True
        lies_kept_non_objective = True

        for candidate in bundle.get("intent_candidates") or []:
            candidate_id = candidate.action_intention_candidate_id
            is_blocked = self._guard_blocks(
                candidate_type="memory_record",
                candidate={
                    "memory_id": candidate_id,
                    "truth_status": candidate.truth_status,
                    "objective_truth": candidate.truth_status == "objective_candidate",
                    "source_object_type": "character_action_intention_candidate",
                    "summary": candidate.safe_summary,
                },
            )
            if candidate.can_write_objective_fact_directly:
                is_blocked = True
                warnings.append(f"candidate_direct_objective_write_blocked:{candidate_id}")
            if candidate.truth_status in NON_OBJECTIVE_M6_TRUTH_STATUSES and not is_blocked:
                is_blocked = True
                warnings.append(f"non_objective_candidate_blocked:{candidate_id}")
            if is_blocked:
                blocked_ids.append(candidate_id)
            else:
                allowed_count += 1
            if candidate.truth_status == "subjective_claim" and not is_blocked:
                subjective_claims_kept_subjective = False
            if candidate.truth_status in {"perception", "unknown"} and not is_blocked:
                perceptions_kept_subjective = False
            if candidate.truth_status in {"lie", "misinformation"} and not is_blocked:
                lies_kept_non_objective = False

        for item in bundle.get("story_information_items") or []:
            item_id = item.item_id
            is_blocked = self._guard_blocks(
                candidate_type="memory_record",
                candidate={
                    "memory_id": item_id,
                    "truth_status": _m7_truth_to_memory_truth(item.truth_status),
                    "objective_truth": item.truth_status == "objective_candidate",
                    "source_object_type": "character_intent_story_information_item",
                    "summary": item.safe_summary
                    or item.base_story_information_item.content,
                },
            )
            if (
                item.m7_semantic_type == "do_not_use"
                or not item.safe_for_writer
                or item.can_write_objective_fact_directly
            ):
                is_blocked = True
            if item.truth_status in NON_OBJECTIVE_M6_TRUTH_STATUSES:
                is_blocked = True
            if is_blocked:
                blocked_ids.append(item_id)
            else:
                allowed_count += 1
            if item.truth_status == "subjective_claim" and not is_blocked:
                subjective_claims_kept_subjective = False
            if item.truth_status in {"perception", "unknown"} and not is_blocked:
                perceptions_kept_subjective = False
            if item.truth_status in {"lie", "misinformation"} and not is_blocked:
                lies_kept_non_objective = False

        for entry in bundle.get("role_scene_memory_entries") or []:
            entry_blocked = self._role_entry_blocks(entry, do_not_use_item_ids)
            if entry_blocked:
                blocked_ids.append(entry.role_scene_memory_entry_id)
                blocked_role_memory_artifact_ids.append(entry.role_scene_memory_entry_id)
            else:
                allowed_count += 1
            if entry.truth_status in NON_OBJECTIVE_ROLE_MEMORY_TRUTH_STATUSES:
                if entry.objective_truth is not False:
                    subjective_claims_kept_subjective = False
                if entry.truth_status == "lie":
                    lies_kept_non_objective = entry.objective_truth is False

        for record in bundle.get("role_memory_records") or []:
            record_blocked = self._memory_record_blocks(record)
            if record_blocked:
                blocked_ids.append(record.memory_id)
                blocked_role_memory_artifact_ids.append(record.memory_id)
            else:
                allowed_count += 1

        checked_candidate_ids = [
            candidate.action_intention_candidate_id
            for candidate in bundle.get("intent_candidates") or []
        ]
        checked_story_item_ids = [
            item.item_id for item in bundle.get("story_information_items") or []
        ]
        checked_role_entry_ids = [
            entry.role_scene_memory_entry_id
            for entry in bundle.get("role_scene_memory_entries") or []
        ]
        return ABCDObjectiveFactBoundaryReport(
            boundary_report_id=f"abcd_objective_fact_boundary_{context.scene_id}_{context.mode}",
            project_id=context.project_id,
            scene_id=context.scene_id,
            checked_candidate_ids=checked_candidate_ids,
            checked_story_information_item_ids=checked_story_item_ids,
            checked_role_memory_entry_ids=checked_role_entry_ids,
            blocked_objective_candidate_count=len(set(blocked_ids)),
            allowed_objective_candidate_count=allowed_count,
            subjective_claims_kept_subjective=subjective_claims_kept_subjective,
            perceptions_kept_subjective=perceptions_kept_subjective,
            lies_kept_non_objective=lies_kept_non_objective,
            psychology_traces_not_written_as_events=True,
            expressions_not_written_as_objective_facts=True,
            no_unapproved_event_write=True,
            no_unapproved_state_change_write=True,
            no_unapproved_memory_record_write=True,
            blocked_candidate_ids=blocked_ids,
            blocked_role_memory_artifact_ids=blocked_role_memory_artifact_ids,
            warnings=warnings,
            safe_summary=(
                f"Objective fact boundary checked {len(checked_candidate_ids)} M6 "
                f"candidates, {len(checked_story_item_ids)} M7 items, "
                f"{len(checked_role_entry_ids)} M8 entries."
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _guard_blocks(self, *, candidate_type: str, candidate: dict[str, Any]) -> bool:
        return self.objective_fact_write_guard.is_subjective_candidate(
            candidate_type=candidate_type,
            candidate=candidate,
        )

    def _role_entry_blocks(
        self,
        entry: RoleSceneMemoryEntry,
        do_not_use_item_ids: set[str],
    ) -> bool:
        if do_not_use_item_ids.intersection(entry.source_story_information_item_ids):
            return True
        if entry.truth_status in NON_OBJECTIVE_ROLE_MEMORY_TRUTH_STATUSES:
            return entry.objective_truth is not False
        return entry.objective_truth is not True

    def _memory_record_blocks(self, record: MemoryRecord) -> bool:
        if record.source_object_type != "role_scene_memory_entry":
            return False
        if record.truth_status in NON_OBJECTIVE_ROLE_MEMORY_TRUTH_STATUSES:
            return record.objective_truth is not False
        return record.objective_truth is not True


def _m7_truth_to_memory_truth(truth_status: str) -> str:
    if truth_status == "lie":
        return "lie"
    if truth_status == "misinformation":
        return "misinformation"
    if truth_status in {"subjective_claim", "perception", "unknown"}:
        return "unverified_claim"
    return "objective_fact"
