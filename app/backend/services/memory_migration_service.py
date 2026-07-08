from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.memory_record import (
    MEMORY_M2_VERSION_ID,
    MemoryMigrationReport,
    MemoryRecord,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.memory_index_service import MemoryIndexService
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class MemoryMigrationService:
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
        self.memory_records_file = self.data_dir / "memory_records.json"
        self.scenes_file = self.data_dir / "scenes.json"
        self.events_file = self.data_dir / "events.json"
        self.state_changes_file = self.data_dir / "state_changes.json"
        self.relationships_file = self.data_dir / "relationships.json"
        self.characters_file = self.data_dir / "characters.json"
        self.decisions_file = self.data_dir / "decisions.json"

    def load_normalized_records(self) -> tuple[list[MemoryRecord], list[str]]:
        raw_records = self.repositories.memory.list_all()
        context = self._context()
        warnings: list[str] = []
        records: list[MemoryRecord] = []
        for index, raw_record in enumerate(raw_records, start=1):
            if not isinstance(raw_record, dict):
                warnings.append(f"Memory record #{index} is not an object and was skipped.")
                continue
            try:
                records.append(self.normalize_record(raw_record, context, warnings))
            except (ValidationError, TypeError, ValueError) as exc:
                memory_id = raw_record.get("memory_id") or f"index_{index}"
                warnings.append(f"Memory record {memory_id} could not be normalized: {exc}")
        return records, warnings

    def reindex(self, *, dry_run: bool = True) -> MemoryMigrationReport:
        raw_records = self.repositories.memory.list_all()
        records, warnings = self.load_normalized_records()
        indexes = MemoryIndexService(store=self.store, data_dir=self.data_dir).build_indexes(
            records
        )
        if not dry_run:
            self.repositories.memory.write_all(
                [model_to_dict(record) for record in records],
            )
            MemoryIndexService(store=self.store, data_dir=self.data_dir).write_index_cache(
                indexes
            )
        return MemoryMigrationReport(
            success=True,
            dry_run=dry_run,
            records_seen=len(raw_records),
            records_normalized=len(records),
            records_written=0 if dry_run else len(records),
            indexes_built=True,
            warnings=warnings,
        )

    def normalize_record(
        self,
        raw_record: dict[str, Any],
        context: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> MemoryRecord:
        context = context or self._context()
        warnings = warnings if warnings is not None else []
        record = MemoryRecord(**raw_record)
        timestamp = utc_now()
        if not record.created_at:
            record.created_at = timestamp
        if not record.updated_at:
            record.updated_at = timestamp
        if not record.version_id:
            record.version_id = MEMORY_M2_VERSION_ID

        source_type = (record.source_object_type or record.object_type or "").strip()
        source_type_key = source_type.casefold()
        source_id = (record.source_object_id or record.object_id or "").strip()
        if not source_type:
            warnings.append(f"{record.memory_id}: source_object_type is missing.")
        if not source_id:
            warnings.append(f"{record.memory_id}: source_object_id is missing.")

        if source_type_key == "event" and source_id:
            self._infer_from_event(record, source_id, context, warnings)
        elif source_type_key == "scene" and source_id:
            self._infer_from_scene(record, source_id, context, warnings)
        elif source_type_key == "state_change" and source_id:
            self._infer_from_state_change(record, source_id, context, warnings)
        elif source_type_key == "relationship" and source_id:
            self._infer_from_relationship(record, source_id, context, warnings)

        for event_id in list(record.event_ids):
            self._infer_from_event(record, event_id, context, warnings, quiet=True)
        if record.scene_id:
            self._infer_from_scene(record, record.scene_id, context, warnings, quiet=True)

        record.keywords = self._unique(
            [
                *record.keywords,
                *record.tags,
                record.memory_type,
                record.location or "",
                record.source_object_type,
            ]
        )
        record.character_ids = self._unique(record.character_ids)
        record.relationship_ids = self._unique(record.relationship_ids)
        record.event_ids = self._unique(record.event_ids)
        if not record.object_type:
            record.object_type = record.source_object_type
        if not record.object_id:
            record.object_id = record.source_object_id
        return record

    def _context(self) -> dict[str, Any]:
        events = self.repositories.events.list_all()
        scenes = self.repositories.scenes.list_all()
        state_changes = self.repositories.state_changes.list_all()
        relationships = self.repositories.relationships.list_all()
        characters = self.repositories.characters.list_all()
        decisions = self.repositories.decisions.list_all()
        return {
            "events": self._by_id(events, "event_id"),
            "scenes": self._by_id(scenes, "scene_id"),
            "state_changes": self._by_id(state_changes, "state_change_id"),
            "relationships": self._by_id(relationships, "relationship_id"),
            "characters": self._by_id(characters, "character_id"),
            "decisions": self._by_id(decisions, "decision_id"),
            "relationships_list": relationships,
        }

    def _infer_from_event(
        self,
        record: MemoryRecord,
        event_id: str,
        context: dict[str, Any],
        warnings: list[str],
        *,
        quiet: bool = False,
    ) -> None:
        event = context["events"].get(event_id)
        if not event:
            if not quiet:
                warnings.append(f"{record.memory_id}: event not found: {event_id}")
            return
        record.event_ids = self._unique([*record.event_ids, event_id])
        if not record.scene_id:
            record.scene_id = event.get("scene_id") or None
        record.character_ids = self._unique(
            [*record.character_ids, *(event.get("participants") or [])]
        )
        if not record.location:
            record.location = event.get("location_id") or None
        record.keywords = self._unique([*record.keywords, *(event.get("tags") or [])])
        for relationship in context["relationships_list"]:
            if event_id in (relationship.get("evidence_event_ids") or []):
                record.relationship_ids = self._unique(
                    [*record.relationship_ids, relationship.get("relationship_id") or ""]
                )
        if record.scene_id:
            self._infer_from_scene(record, record.scene_id, context, warnings, quiet=True)

    def _infer_from_scene(
        self,
        record: MemoryRecord,
        scene_id: str,
        context: dict[str, Any],
        warnings: list[str],
        *,
        quiet: bool = False,
    ) -> None:
        scene = context["scenes"].get(scene_id)
        if not scene:
            if not quiet:
                warnings.append(f"{record.memory_id}: scene not found: {scene_id}")
            return
        record.scene_id = record.scene_id or scene_id
        if not record.chapter_id:
            record.chapter_id = scene.get("chapter_id") or None
        if not record.location:
            record.location = scene.get("location") or None
        record.character_ids = self._unique(
            [*record.character_ids, *(scene.get("linked_character_ids") or [])]
        )
        record.relationship_ids = self._unique(
            [*record.relationship_ids, *(scene.get("linked_relationship_ids") or [])]
        )
        record.event_ids = self._unique([*record.event_ids, *(scene.get("event_ids") or [])])

    def _infer_from_state_change(
        self,
        record: MemoryRecord,
        state_change_id: str,
        context: dict[str, Any],
        warnings: list[str],
    ) -> None:
        change = context["state_changes"].get(state_change_id)
        if not change:
            warnings.append(f"{record.memory_id}: state_change not found: {state_change_id}")
            return
        target_type = change.get("target_type") or ""
        target_id = change.get("target_id") or ""
        if target_type == "character":
            record.character_ids = self._unique([*record.character_ids, target_id])
        elif target_type == "relationship":
            record.relationship_ids = self._unique([*record.relationship_ids, target_id])
        reason_event_id = change.get("reason_event_id") or ""
        if reason_event_id:
            record.event_ids = self._unique([*record.event_ids, reason_event_id])
            self._infer_from_event(record, reason_event_id, context, warnings, quiet=True)

    def _infer_from_relationship(
        self,
        record: MemoryRecord,
        relationship_id: str,
        context: dict[str, Any],
        warnings: list[str],
    ) -> None:
        relationship = context["relationships"].get(relationship_id)
        if not relationship:
            warnings.append(f"{record.memory_id}: relationship not found: {relationship_id}")
            return
        record.relationship_ids = self._unique([*record.relationship_ids, relationship_id])
        record.character_ids = self._unique(
            [
                *record.character_ids,
                relationship.get("source_id") or "",
                relationship.get("target_id") or "",
            ]
        )
        record.event_ids = self._unique(
            [*record.event_ids, *(relationship.get("evidence_event_ids") or [])]
        )

    def _read_list_if_present(self, path: Path) -> list[Any]:
        if not self.store.exists(path):
            return []
        return self.store.read_list(path)

    def _by_id(self, records: list[Any], key: str) -> dict[str, dict[str, Any]]:
        return {
            str(record.get(key)): dict(record)
            for record in records
            if isinstance(record, dict) and record.get(key)
        }

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
