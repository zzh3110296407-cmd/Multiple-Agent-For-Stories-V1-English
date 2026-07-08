from pathlib import Path
from typing import Any

from app.backend.models.memory_pack import MEMORY_PACK_SCHEMA_VERSION
from app.backend.storage.json_store import JsonStore, StorageError


class JsonListRepository:
    def __init__(
        self,
        *,
        store: JsonStore,
        path: Path,
        id_field: str,
        legacy_path: Path | None = None,
    ) -> None:
        self.store = store
        self.path = path
        self.id_field = id_field
        self.legacy_path = legacy_path

    def _read_path(self) -> Path:
        if self.store.exists(self.path):
            return self.path
        if self.legacy_path is not None and self.store.exists(self.legacy_path):
            return self.legacy_path
        return self.path

    def list_all(self) -> list[dict[str, Any]]:
        read_path = self._read_path()
        if not self.store.exists(read_path):
            return []
        return [
            dict(item)
            for item in self.store.read_list(read_path)
            if isinstance(item, dict)
        ]

    def get_by_id(self, record_id: str) -> dict[str, Any] | None:
        for record in self.list_all():
            if str(record.get(self.id_field) or "") == record_id:
                return record
        return None

    def write_all(self, records: list[dict[str, Any]]) -> None:
        self.store.write(self.path, [dict(record) for record in records])

    def append(self, record: dict[str, Any]) -> None:
        records = self.list_all()
        records.append(dict(record))
        self.write_all(records)

    def upsert(self, record: dict[str, Any], id_field: str | None = None) -> None:
        field = id_field or self.id_field
        record_id = str(record.get(field) or "")
        if not record_id:
            raise StorageError(f"Repository upsert requires {field}: {self.path}")
        records = self.list_all()
        replaced = False
        updated: list[dict[str, Any]] = []
        for existing in records:
            if str(existing.get(field) or "") == record_id:
                updated.append(dict(record))
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(dict(record))
        self.write_all(updated)


class JsonSingleObjectRepository:
    def __init__(
        self,
        *,
        store: JsonStore,
        path: Path,
        id_field: str,
    ) -> None:
        self.store = store
        self.path = path
        self.id_field = id_field

    def list_all(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.path):
            return []
        data = self.store.read_any(self.path)
        if not isinstance(data, dict):
            raise StorageError(f"{self.path.name} must contain a JSON object.")
        return [dict(data)]

    def get_by_id(self, record_id: str) -> dict[str, Any] | None:
        for record in self.list_all():
            if str(record.get(self.id_field) or "") == record_id:
                return record
        return None

    def write_all(self, records: list[dict[str, Any]]) -> None:
        if len(records) != 1:
            raise StorageError(
                f"{self.path.name} repository write_all requires exactly one object."
            )
        self.store.write(self.path, dict(records[0]))

    def append(self, record: dict[str, Any]) -> None:
        self.upsert(record, self.id_field)

    def upsert(self, record: dict[str, Any], id_field: str | None = None) -> None:
        field = id_field or self.id_field
        record_id = str(record.get(field) or "")
        if not record_id:
            raise StorageError(f"Repository upsert requires {field}: {self.path}")
        self.store.write(self.path, dict(record))


class JsonMemoryRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "memory_records.json",
            id_field="memory_id",
        )


class JsonSceneRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(store=store, path=data_dir / "scenes.json", id_field="scene_id")


class JsonEventRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(store=store, path=data_dir / "events.json", id_field="event_id")


class JsonStateChangeRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "state_changes.json",
            id_field="state_change_id",
        )


class JsonCharacterRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "characters.json",
            id_field="character_id",
        )


class JsonRelationshipRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "relationships.json",
            id_field="relationship_id",
        )


class JsonWorldCanvasRepository(JsonSingleObjectRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "world_canvas.json",
            id_field="world_canvas_id",
        )


class JsonFrameworkPackageRepository(JsonSingleObjectRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "framework_package.json",
            id_field="framework_package_id",
        )


class JsonDecisionRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "decisions.json",
            id_field="decision_id",
        )


class JsonQualityReportRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "quality_reports.json",
            id_field="quality_report_id",
        )


class JsonContinuityIssueRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "continuity_issues.json",
            id_field="issue_id",
        )


class JsonPriorStoryCompletionCandidateRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        legacy_file_name = "old" + "_story_completion_candidates.json"
        super().__init__(
            store=store,
            path=data_dir / "prior_story_completion_candidates.json",
            legacy_path=data_dir / legacy_file_name,
            id_field="candidate_id",
        )


class JsonChapterRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "chapters.json",
            id_field="chapter_id",
        )


class JsonPendingCharacterStateChangeRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "pending_character_state_changes.json",
            id_field="change_id",
        )

    def list_all(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.path):
            return []
        data = self.store.read_any(self.path)
        raw_changes = data if isinstance(data, list) else data.get("changes", [])
        if not isinstance(raw_changes, list):
            raise StorageError(
                "pending_character_state_changes.json must contain a list."
            )
        return [
            dict(item)
            for item in raw_changes
            if isinstance(item, dict)
        ]


class JsonMemoryUpdatePlanRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "memory_update_plans.json",
            id_field="memory_update_plan_id",
        )


class JsonClaimRecordRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "claim_records.json",
            id_field="claim_id",
        )


class JsonNarrativeIntentRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "narrative_intent_records.json",
            id_field="narrative_intent_id",
        )


class JsonCharacterPsychologyTraceRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "character_psychology_traces.json",
            id_field="psychology_trace_id",
        )


class JsonCharacterExpressionRecordRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "character_expression_records.json",
            id_field="expression_record_id",
        )


class JsonPerceptionStateRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "perception_state_records.json",
            id_field="perception_state_id",
        )


class JsonApparentContradictionRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "apparent_contradiction_records.json",
            id_field="apparent_contradiction_id",
        )


class JsonNarrativeDebtRepository(JsonListRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "narrative_debts.json",
            id_field="narrative_debt_id",
        )


class JsonPackRepository:
    def __init__(
        self,
        *,
        store: JsonStore,
        path: Path,
        id_field: str,
        root_name: str,
    ) -> None:
        self.store = store
        self.path = path
        self.id_field = id_field
        self.root_name = root_name

    def read_envelope(self) -> dict[str, Any]:
        if not self.store.exists(self.path):
            return {
                "schema_version": MEMORY_PACK_SCHEMA_VERSION,
                "packs": [],
                "updated_at": "",
            }
        data = self.store.read_any(self.path)
        if isinstance(data, list):
            return {
                "schema_version": MEMORY_PACK_SCHEMA_VERSION,
                "packs": data,
                "updated_at": "",
            }
        if not isinstance(data, dict):
            raise StorageError(f"{self.root_name} root must be an object.")
        packs = data.get("packs")
        if not isinstance(packs, list):
            raise StorageError(f"{self.root_name} must contain a packs list.")
        return {
            "schema_version": str(
                data.get("schema_version") or MEMORY_PACK_SCHEMA_VERSION
            ),
            "packs": packs,
            "updated_at": str(data.get("updated_at") or ""),
        }

    def write_envelope(self, envelope: dict[str, Any]) -> None:
        self.store.write(self.path, envelope)

    def list_packs(self) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self.read_envelope()["packs"]
            if isinstance(item, dict)
        ]

    def get_by_id(self, pack_id: str) -> dict[str, Any] | None:
        for pack in self.list_packs():
            if str(pack.get(self.id_field) or "") == pack_id:
                return pack
        return None


class JsonChapterMemoryPackRepository(JsonPackRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "chapter_memory_packs.json",
            id_field="chapter_memory_pack_id",
            root_name="chapter_memory_packs.json",
        )


class JsonSceneMemoryPackRepository(JsonPackRepository):
    def __init__(self, *, store: JsonStore, data_dir: Path) -> None:
        super().__init__(
            store=store,
            path=data_dir / "scene_memory_packs.json",
            id_field="scene_memory_pack_id",
            root_name="scene_memory_packs.json",
        )
