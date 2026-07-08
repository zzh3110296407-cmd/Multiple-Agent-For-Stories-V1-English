from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.memory_record import MemoryIndexes, MemoryRecord
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class MemoryIndexService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.index_file = self.data_dir / "memory_indexes.json"

    def build_indexes(self, records: list[MemoryRecord]) -> MemoryIndexes:
        indexes = MemoryIndexes(
            metadata={
                "schema_version": "phase2_m2_memory_index_v1",
                "built_at": utc_now(),
                "source": "memory_records.json",
            }
        )
        for record in records:
            memory_id = record.memory_id
            self._add(indexes.by_status, record.status, memory_id)
            self._add(indexes.by_memory_type, record.memory_type, memory_id)
            self._add(indexes.by_chapter, record.chapter_id, memory_id)
            self._add(indexes.by_scene, record.scene_id, memory_id)
            self._add(indexes.by_location, record.location, memory_id)
            for character_id in record.character_ids:
                self._add(indexes.by_character, character_id, memory_id)
            for relationship_id in record.relationship_ids:
                self._add(indexes.by_relationship, relationship_id, memory_id)
            for event_id in record.event_ids:
                self._add(indexes.by_event, event_id, memory_id)
            for keyword in record.keywords:
                self._add(indexes.by_keyword, self._normalize_keyword(keyword), memory_id)
        return indexes

    def write_index_cache(self, indexes: MemoryIndexes) -> None:
        self.store.write(self.index_file, model_to_dict(indexes))

    def _add(self, index: dict[str, list[str]], key: str | None, memory_id: str) -> None:
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        values = index.setdefault(clean_key, [])
        if memory_id not in values:
            values.append(memory_id)

    def _normalize_keyword(self, keyword: str) -> str:
        return str(keyword or "").strip().casefold()
