from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.abcd_runtime_gate import ABCDRuntimeGateContext
from app.backend.models.abcd_story_information import (
    ABCDStoryInformationPackage,
    CharacterIntentStoryInformationItem,
)
from app.backend.models.character_intent import (
    CharacterActionIntentionCandidate,
    CharacterIntentRiskReport,
    TieredCharacterIntentPackage,
)
from app.backend.models.memory_record import MemoryRecord
from app.backend.models.role_memory_writeback import (
    RoleSceneMemoryEntry,
    TieredSceneMemoryWritePlan,
)
from app.backend.models.scene import Scene
from app.backend.models.scene_participation import (
    SceneParticipationPackage,
    TieredCharacterContextPackage,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ABCDRuntimeGateContextBuilder:
    def __init__(
        self,
        *,
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
        self.scene_participation_packages_file = (
            self.data_dir / "scene_participation_packages.json"
        )
        self.tiered_context_packages_file = (
            self.data_dir / "tiered_character_context_packages.json"
        )
        self.intent_packages_file = self.data_dir / "tiered_character_intent_packages.json"
        self.intent_candidates_file = (
            self.data_dir / "character_action_intention_candidates.json"
        )
        self.intent_risk_reports_file = self.data_dir / "character_intent_risk_reports.json"
        self.abcd_story_information_packages_file = (
            self.data_dir / "abcd_story_information_packages.json"
        )
        self.abcd_story_information_items_file = (
            self.data_dir / "character_intent_story_information_items.json"
        )
        self.write_plans_file = self.data_dir / "tiered_scene_memory_write_plans.json"
        self.role_entries_file = self.data_dir / "role_scene_memory_entries.json"
        self.memory_records_file = self.data_dir / "memory_records.json"

    def build_bundle(self, scene_id: str, *, mode: str) -> dict[str, Any]:
        scene = self._get_scene(scene_id)
        timestamp = utc_now()
        warnings: list[str] = []
        participation = self._current_participation(scene)
        if participation is None:
            warnings.append("scene_participation_package_missing")

        context_package = self._context_package(scene, participation)
        if participation is not None and context_package is None:
            warnings.append("tiered_character_context_package_missing_for_participation")

        intent_package = self._intent_package(scene, participation)
        if participation is not None and intent_package is None:
            warnings.append("tiered_character_intent_package_missing_for_participation")

        story_info_package = self._story_information_package(
            scene,
            participation,
            intent_package,
        )
        if participation is not None and story_info_package is None:
            warnings.append("abcd_story_information_package_missing_for_participation")

        write_plan = self._write_plan(scene, participation, intent_package, story_info_package)
        if scene.status in {"confirmed", "revised", "temporary_confirmed"} and write_plan is None:
            warnings.append("tiered_scene_memory_write_plan_missing_for_committed_scene")

        intent_candidates = self._intent_candidates(scene, participation, intent_package)
        risk_reports = self._risk_reports(scene, participation, intent_package)
        story_items = self._story_information_items(scene, participation, story_info_package)
        role_entries = self._role_entries(scene, participation, write_plan)
        role_memory_records = self._role_memory_records(role_entries)

        selected_ids, tier_by_character = self._selected_ids_and_tiers(participation)
        source_memory_by_character = self._source_memory_by_character(
            context_package,
            intent_candidates,
            role_entries,
        )
        candidate_ids_by_character = self._candidate_ids_by_character(intent_candidates)

        context = ABCDRuntimeGateContext(
            abcd_runtime_gate_context_id=f"abcd_gate_context_{scene.scene_id}_{mode}",
            project_id=scene.project_id
            or current_story_workspace_project_id(
                self.store,
                self.data_dir,
                fallback="local_project",
            ),
            chapter_id=scene.chapter_id,
            scene_id=scene.scene_id,
            scene_index=scene.scene_index,
            mode=mode,
            scene_participation_package_id=(
                participation.scene_participation_package_id if participation else ""
            ),
            tiered_character_context_package_id=(
                context_package.tiered_character_context_package_id
                if context_package
                else ""
            ),
            tiered_character_intent_package_id=(
                intent_package.tiered_character_intent_package_id
                if intent_package
                else ""
            ),
            abcd_story_information_package_id=(
                story_info_package.abcd_story_information_package_id
                if story_info_package
                else ""
            ),
            tiered_scene_memory_write_plan_id=(
                write_plan.tiered_scene_memory_write_plan_id if write_plan else ""
            ),
            selected_character_ids=selected_ids,
            selected_character_tiers=tier_by_character,
            source_memory_ids_by_character=source_memory_by_character,
            action_candidate_ids_by_character=candidate_ids_by_character,
            subjective_candidate_ids=[
                candidate.action_intention_candidate_id
                for candidate in intent_candidates
                if candidate.truth_status
                in {"subjective_claim", "perception", "lie", "misinformation", "unknown"}
            ],
            writer_story_information_item_ids=[item.item_id for item in story_items],
            role_scene_memory_entry_ids=[
                entry.role_scene_memory_entry_id for entry in role_entries
            ],
            safe_context_summary=(
                f"ABCD runtime gate context for {scene.scene_id}: "
                f"{len(selected_ids)} selected participants, "
                f"{len(intent_candidates)} action candidates, "
                f"{len(story_items)} writer items, "
                f"{len(role_entries)} role memory entries."
            ),
            warnings=warnings,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return {
            "scene": scene,
            "context": context,
            "scene_participation": participation,
            "tiered_character_context": context_package,
            "tiered_character_intent": intent_package,
            "intent_candidates": intent_candidates,
            "risk_reports": risk_reports,
            "abcd_story_information": story_info_package,
            "story_information_items": story_items,
            "tiered_scene_memory_write_plan": write_plan,
            "role_scene_memory_entries": role_entries,
            "role_memory_records": role_memory_records,
            "warnings": warnings,
        }

    def _get_scene(self, scene_id: str) -> Scene:
        clean_id = str(scene_id or "").strip()
        for row in self.repositories.scenes.list_all():
            if isinstance(row, dict) and str(row.get("scene_id") or "") == clean_id:
                try:
                    return Scene(**row)
                except ValidationError as exc:
                    raise StorageError("ABCD_RUNTIME_GATE_SCENE_INVALID") from exc
        raise StorageError(f"ABCD_RUNTIME_GATE_SCENE_NOT_FOUND: {clean_id}")

    def _current_participation(self, scene: Scene) -> SceneParticipationPackage | None:
        packages = [
            item
            for item in self._read_models(
                self.scene_participation_packages_file,
                SceneParticipationPackage,
            )
            if item.status in {"ready", "warning"}
            and (
                item.scene_id == scene.scene_id
                or (
                    not item.scene_id
                    and item.chapter_id == scene.chapter_id
                    and item.scene_index == scene.scene_index
                )
            )
        ]
        return _latest(packages)

    def _context_package(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
    ) -> TieredCharacterContextPackage | None:
        packages = self._read_models(
            self.tiered_context_packages_file,
            TieredCharacterContextPackage,
        )
        if participation is not None:
            return _latest(
                [
                    item
                    for item in packages
                    if item.scene_participation_package_id
                    == participation.scene_participation_package_id
                ]
            )
        return _latest(
            [
                item
                for item in packages
                if item.scene_id == scene.scene_id
                or (
                    not item.scene_id
                    and item.chapter_id == scene.chapter_id
                    and item.scene_index == scene.scene_index
                )
            ]
        )

    def _intent_package(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
    ) -> TieredCharacterIntentPackage | None:
        packages = self._read_models(self.intent_packages_file, TieredCharacterIntentPackage)
        if participation is not None:
            return _latest(
                [
                    item
                    for item in packages
                    if item.scene_participation_package_id
                    == participation.scene_participation_package_id
                ]
            )
        return _latest(
            [
                item
                for item in packages
                if item.scene_id == scene.scene_id
                or (
                    item.chapter_id == scene.chapter_id
                    and item.scene_index == scene.scene_index
                )
            ]
        )

    def _story_information_package(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
        intent_package: TieredCharacterIntentPackage | None,
    ) -> ABCDStoryInformationPackage | None:
        packages = self._read_models(
            self.abcd_story_information_packages_file,
            ABCDStoryInformationPackage,
        )
        if participation is not None:
            candidates = [
                item
                for item in packages
                if item.source_scene_participation_package_id
                == participation.scene_participation_package_id
            ]
            if intent_package is not None:
                candidates = [
                    item
                    for item in candidates
                    if item.source_tiered_character_intent_package_id
                    == intent_package.tiered_character_intent_package_id
                ]
            return _latest(candidates)
        return _latest(
            [
                item
                for item in packages
                if item.scene_id == scene.scene_id
                or (
                    item.chapter_id == scene.chapter_id
                    and item.scene_index == scene.scene_index
                )
            ]
        )

    def _write_plan(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
        intent_package: TieredCharacterIntentPackage | None,
        story_info_package: ABCDStoryInformationPackage | None,
    ) -> TieredSceneMemoryWritePlan | None:
        plans = self._read_models(self.write_plans_file, TieredSceneMemoryWritePlan)
        if participation is not None:
            candidates = [
                item
                for item in plans
                if item.scene_id == scene.scene_id
                and item.scene_participation_package_id
                == participation.scene_participation_package_id
            ]
            if intent_package is not None:
                candidates = [
                    item
                    for item in candidates
                    if item.tiered_character_intent_package_id
                    == intent_package.tiered_character_intent_package_id
                ]
            if story_info_package is not None:
                candidates = [
                    item
                    for item in candidates
                    if item.abcd_story_information_package_id
                    == story_info_package.abcd_story_information_package_id
                ]
            return _latest(candidates)
        return _latest([item for item in plans if item.scene_id == scene.scene_id])

    def _intent_candidates(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
        intent_package: TieredCharacterIntentPackage | None,
    ) -> list[CharacterActionIntentionCandidate]:
        rows = self._read_models(
            self.intent_candidates_file,
            CharacterActionIntentionCandidate,
        )
        if intent_package is not None:
            ids = _candidate_ids_for_runtime_gate(intent_package)
            return [item for item in rows if item.action_intention_candidate_id in ids]
        if participation is not None:
            return []
        return [
            item
            for item in rows
            if item.scene_id == scene.scene_id
            or (
                item.chapter_id == scene.chapter_id
                and item.scene_index == scene.scene_index
            )
        ]

    def _risk_reports(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
        intent_package: TieredCharacterIntentPackage | None,
    ) -> list[CharacterIntentRiskReport]:
        rows = self._read_models(self.intent_risk_reports_file, CharacterIntentRiskReport)
        if intent_package is not None:
            ids = set(intent_package.risk_report_ids)
            candidate_ids = _candidate_ids_for_runtime_gate(intent_package)
            return [
                item
                for item in rows
                if item.risk_report_id in ids
                and item.action_intention_candidate_id in candidate_ids
            ]
        if participation is not None:
            return []
        return [
            item
            for item in rows
            if item.scene_id == scene.scene_id
            or (
                item.chapter_id == scene.chapter_id
                and item.scene_index == scene.scene_index
            )
        ]

    def _story_information_items(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
        package: ABCDStoryInformationPackage | None,
    ) -> list[CharacterIntentStoryInformationItem]:
        rows = self._read_models(
            self.abcd_story_information_items_file,
            CharacterIntentStoryInformationItem,
        )
        if package is not None:
            ids = set(package.item_ids)
            return [item for item in rows if item.item_id in ids]
        if participation is not None:
            return []
        return [
            item
            for item in rows
            if item.scene_id == scene.scene_id
            or (
                item.chapter_id == scene.chapter_id
                and item.scene_index == scene.scene_index
            )
        ]

    def _role_entries(
        self,
        scene: Scene,
        participation: SceneParticipationPackage | None,
        write_plan: TieredSceneMemoryWritePlan | None,
    ) -> list[RoleSceneMemoryEntry]:
        rows = self._read_models(self.role_entries_file, RoleSceneMemoryEntry)
        if write_plan is not None:
            ids = set(write_plan.role_memory_entry_ids)
            return [item for item in rows if item.role_scene_memory_entry_id in ids]
        if participation is not None:
            return []
        return [item for item in rows if item.scene_id == scene.scene_id]

    def _role_memory_records(
        self,
        role_entries: list[RoleSceneMemoryEntry],
    ) -> list[MemoryRecord]:
        entry_ids = {entry.role_scene_memory_entry_id for entry in role_entries}
        if not entry_ids:
            return []
        return [
            item
            for item in self._read_models(self.memory_records_file, MemoryRecord)
            if item.source_object_type == "role_scene_memory_entry"
            and item.source_object_id in entry_ids
        ]

    def _selected_ids_and_tiers(
        self,
        participation: SceneParticipationPackage | None,
    ) -> tuple[list[str], dict[str, str]]:
        if participation is None:
            return [], {}
        tiers: dict[str, str] = {}
        for participant in participation.participants:
            tiers[participant.character_id] = participant.tier
        for tier, ids in (
            ("A", participation.selected_a_ids),
            ("B", participation.selected_b_ids),
            ("C", participation.selected_c_ids),
            ("D", participation.selected_d_ids),
        ):
            for character_id in ids:
                tiers.setdefault(character_id, tier)
        selected = _unique_strings([*participation.active_character_ids, *tiers.keys()])
        return selected, {character_id: tiers.get(character_id, "D") for character_id in selected}

    def _source_memory_by_character(
        self,
        context_package: TieredCharacterContextPackage | None,
        intent_candidates: list[CharacterActionIntentionCandidate],
        role_entries: list[RoleSceneMemoryEntry],
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if context_package is not None:
            for item in context_package.items:
                result.setdefault(item.character_id, [])
                result[item.character_id].extend(item.source_memory_ids)
        for candidate in intent_candidates:
            result.setdefault(candidate.character_id, [])
            result[candidate.character_id].extend([candidate.scene_memory_pack_id])
        for entry in role_entries:
            result.setdefault(entry.character_id, [])
            result[entry.character_id].extend(entry.source_memory_ids)
        return {
            character_id: _unique_strings(memory_ids)
            for character_id, memory_ids in result.items()
        }

    def _candidate_ids_by_character(
        self,
        intent_candidates: list[CharacterActionIntentionCandidate],
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for candidate in intent_candidates:
            result.setdefault(candidate.character_id, []).append(
                candidate.action_intention_candidate_id
            )
        return {
            character_id: _unique_strings(candidate_ids)
            for character_id, candidate_ids in result.items()
        }

    def _read_models(self, path: Path, model_type: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        try:
            rows = self.store.read_list(path)
            return [
                model_type(**row)
                for row in rows
                if isinstance(row, dict)
            ]
        except (TypeError, ValidationError) as exc:
            raise StorageError(f"ABCD_RUNTIME_GATE_STORAGE_INVALID: {path.name}") from exc


def _latest(items: list[Any]) -> Any | None:
    if not items:
        return None
    return sorted(
        items,
        key=lambda item: (
            str(getattr(item, "updated_at", "") or ""),
            str(getattr(item, "created_at", "") or ""),
        ),
        reverse=True,
    )[0]


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


def _candidate_ids_for_runtime_gate(package: TieredCharacterIntentPackage) -> set[str]:
    scoped_ids = set(package.writer_ready_candidate_ids) | set(
        package.needs_gate_candidate_ids
    )
    if scoped_ids:
        return scoped_ids
    return set(package.action_intention_candidate_ids)
