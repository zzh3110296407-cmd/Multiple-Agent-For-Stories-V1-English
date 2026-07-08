from __future__ import annotations

import json
from typing import Any

from app.backend.core.config import STORAGE_MODE_POSTGRES_PRIMARY, settings
from app.backend.models.temporal_resolver import (
    CharacterVisibleMemoryResponse,
    CharacterVisibleMemoryResult,
    LocationChangeDeltaResult,
    LocationStateAtTimeResponse,
    LocationStateAtTimeResult,
    ReaderDisclosureStatusResponse,
    TemporalResolverScope,
    TimelineNodeVersionStatusResponse,
)
from app.backend.repositories.postgres_normalized_repositories import (
    PostgresConnectionFactory,
)
from app.backend.services.runtime_project_mapping import (
    RuntimeProjectMapping,
    resolve_runtime_project_mapping,
    validate_runtime_project_id,
)
from app.backend.storage.json_store import JsonStore, StorageError


SAFE_NODE_STATUSES = ("CONFIRMED", "FORMAL_APPLIED", "TEMPORARY_CONFIRMED")
WRITER_SAFE_VISIBILITY_STATUSES = ("KNOWN", "RESTORED")
WRITER_SAFE_AUTHORITY_LEVELS = (
    "USER_LOCKED",
    "USER_CONFIRMED",
    "FORMAL_APPLIED",
    "SYSTEM_CONFIRMED",
)
WRITER_SAFE_AUTHORITY_LEVEL_SQL = "(" + ", ".join(
    f"'{level}'" for level in WRITER_SAFE_AUTHORITY_LEVELS
) + ")"
WRITER_SAFE_ACCESS_LABELS = ("USABLE_NOW",)
FORBIDDEN_ACCESS_LABELS = (
    "AUTHOR_ONLY",
    "CHARACTER_UNKNOWN",
    "READER_FORBIDDEN",
    "FUTURE_INFO",
    "CANDIDATE_ONLY",
    "SUPERSEDED",
    "CONFLICT_RISK",
    "WRONG_TIMELINE",
)


class TemporalResolverService:
    def __init__(
        self,
        *,
        connection_factory: PostgresConnectionFactory | None = None,
        store: JsonStore | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self.store = store or JsonStore()
        self.schema_name = (
            connection_factory.schema_name
            if connection_factory is not None
            else "mas_phase875_proto"
        )

    def get_character_visible_memory(
        self,
        *,
        character_id: str,
        timeline_id: str,
        world_time_sort_key: int,
        knowledge_time_sort_key: int,
        narrative_sequence_key: int,
        project_id: str = "",
        limit: int = 20,
    ) -> CharacterVisibleMemoryResponse:
        mapping = self._resolve_mapping(project_id)
        bounded_limit = _bounded_limit(limit)
        with self._connect() as conn:
            rows = conn.execute(
                self._character_visible_memory_sql(),
                (
                    _required_id(character_id, "character_id"),
                    _required_id(timeline_id, "timeline_id"),
                    mapping.project_id,
                    int(knowledge_time_sort_key),
                    int(world_time_sort_key),
                    int(world_time_sort_key),
                    int(narrative_sequence_key),
                    bounded_limit,
                ),
            ).fetchall()
        memories = [
            CharacterVisibleMemoryResult(
                character_memory_node_id=str(row[0] or ""),
                character_id=str(row[1] or ""),
                timeline_id=str(row[2] or ""),
                memory_type=str(row[3] or ""),
                visibility_status=str(row[4] or ""),
                content=str(row[5] or ""),
                summary=str(row[6] or ""),
                experienced_at=str(row[7] or ""),
                experienced_at_sort_key=int(row[8] or 0),
                known_at=str(row[9] or ""),
                known_at_sort_key=int(row[10] or 0),
                narrative_recorded_at=str(row[11] or ""),
                narrative_recorded_at_sort_key=int(row[12] or 0),
                valid_from=str(row[13] or ""),
                valid_from_sort_key=int(row[14] or 0),
                valid_to=str(row[15] or ""),
                valid_to_sort_key=_optional_int(row[16]),
                status=str(row[17] or ""),
                authority_level=str(row[18] or ""),
                source_refs=_json_list(row[19]),
            )
            for row in rows
        ]
        return CharacterVisibleMemoryResponse(
            scope=self._scope(mapping),
            character_id=character_id,
            timeline_id=timeline_id,
            world_time_sort_key=int(world_time_sort_key),
            knowledge_time_sort_key=int(knowledge_time_sort_key),
            narrative_sequence_key=int(narrative_sequence_key),
            result_count=len(memories),
            memories=memories,
            filters_applied=self._writer_safe_filters(),
            gaps=[] if memories else ["no_safe_character_memory_nodes"],
        )

    def get_location_state_at_time(
        self,
        *,
        location_id: str,
        timeline_id: str,
        world_time_sort_key: int,
        project_id: str = "",
    ) -> LocationStateAtTimeResponse:
        mapping = self._resolve_mapping(project_id)
        with self._connect() as conn:
            row = conn.execute(
                self._location_state_at_time_sql(),
                (
                    _required_id(location_id, "location_id"),
                    _required_id(timeline_id, "timeline_id"),
                    mapping.project_id,
                    int(world_time_sort_key),
                    int(world_time_sort_key),
                    1,
                ),
            ).fetchone()
        state = self._location_state_from_row(row) if row is not None else None
        return LocationStateAtTimeResponse(
            scope=self._scope(mapping),
            location_id=location_id,
            timeline_id=timeline_id,
            world_time_sort_key=int(world_time_sort_key),
            state=state,
            result_count=1 if state is not None else 0,
            filters_applied=self._writer_safe_filters(),
            gaps=[] if state is not None else ["no_safe_location_state_node"],
        )

    def get_reader_disclosure_status(
        self,
        *,
        entity_type: str,
        entity_id: str,
        narrative_sequence_key: int,
        project_id: str = "",
    ) -> ReaderDisclosureStatusResponse:
        mapping = self._resolve_mapping(project_id)
        normalized_type = str(entity_type or "").strip()
        required_entity_id = _required_id(entity_id, "entity_id")
        gaps: list[str] = []
        evidence: list[dict[str, Any]] = []
        if normalized_type == "character_memory_node":
            with self._connect() as conn:
                rows = conn.execute(
                    self._reader_disclosure_character_memory_sql(),
                    (
                        mapping.project_id,
                        required_entity_id,
                        int(narrative_sequence_key),
                        5,
                    ),
                ).fetchall()
            evidence = [
                {
                    "entity_type": "character_memory_node",
                    "entity_id": str(row[0] or ""),
                    "visibility_status": str(row[1] or ""),
                    "narrative_recorded_at": str(row[2] or ""),
                    "narrative_recorded_at_sort_key": int(row[3] or 0),
                    "status": str(row[4] or ""),
                    "authority_level": str(row[5] or ""),
                    "usable_for_writer": True,
                }
                for row in rows
            ]
        elif normalized_type == "location_state_node":
            with self._connect() as conn:
                rows = conn.execute(
                    self._reader_disclosure_location_state_sql(),
                    (
                        mapping.project_id,
                        required_entity_id,
                        int(narrative_sequence_key),
                        5,
                    ),
                ).fetchall()
            evidence = [
                {
                    "entity_type": "location_state_node",
                    "entity_id": str(row[0] or ""),
                    "visibility_status": str(row[1] or ""),
                    "revealed_to_reader_at": str(row[2] or ""),
                    "revealed_to_reader_at_sort_key": int(row[3] or 0),
                    "status": str(row[4] or ""),
                    "authority_level": str(row[5] or ""),
                    "usable_for_writer": True,
                }
                for row in rows
            ]
        elif normalized_type == "location_change_delta":
            with self._connect() as conn:
                rows = conn.execute(
                    self._reader_disclosure_location_change_delta_sql(),
                    (
                        mapping.project_id,
                        required_entity_id,
                        int(narrative_sequence_key),
                        5,
                    ),
                ).fetchall()
            evidence = [
                {
                    "entity_type": "location_change_delta",
                    "entity_id": str(row[0] or ""),
                    "visibility_status": str(row[1] or ""),
                    "revealed_to_reader_at": str(row[2] or ""),
                    "revealed_to_reader_at_sort_key": int(row[3] or 0),
                    "status": str(row[4] or ""),
                    "authority_level": str(row[5] or ""),
                    "usable_for_writer": True,
                }
                for row in rows
            ]
        else:
            gaps.append("unsupported_entity_type")

        disclosed = bool(evidence)
        return ReaderDisclosureStatusResponse(
            scope=self._scope(mapping),
            entity_type=normalized_type,
            entity_id=required_entity_id,
            narrative_sequence_key=int(narrative_sequence_key),
            disclosed_to_reader=disclosed,
            usable_for_writer=disclosed,
            evidence_count=len(evidence),
            evidence=evidence,
            filters_applied=self._writer_safe_filters(),
            gaps=gaps if gaps else ([] if evidence else ["no_safe_reader_disclosure_evidence"]),
        )

    def get_timeline_node_version_status(
        self,
        *,
        node_type: str,
        node_id: str,
        project_id: str = "",
    ) -> TimelineNodeVersionStatusResponse:
        mapping = self._resolve_mapping(project_id)
        normalized_type = str(node_type or "").strip()
        spec = _NODE_VERSION_SPECS.get(normalized_type)
        if spec is None:
            return TimelineNodeVersionStatusResponse(
                scope=self._scope(mapping),
                node_type=normalized_type,
                node_id=node_id,
                current=False,
                gaps=["unsupported_node_type"],
            )
        with self._connect() as conn:
            row = conn.execute(
                self._timeline_node_version_status_sql(spec),
                (
                    mapping.project_id,
                    _required_id(node_id, "node_id"),
                    1,
                ),
            ).fetchone()
        if row is None:
            return TimelineNodeVersionStatusResponse(
                scope=self._scope(mapping),
                node_type=normalized_type,
                node_id=node_id,
                current=False,
                gaps=["node_not_found"],
            )
        status = str(row[0] or "")
        lifecycle_state = str(row[1] or "")
        authority_level = str(row[2] or "")
        superseded_by_id = str(row[3] or "")
        visibility_status = str(row[4] or "")
        deleted = bool(row[5])
        current = (
            not deleted
            and lifecycle_state == "ACTIVE"
            and status in SAFE_NODE_STATUSES
            and authority_level in WRITER_SAFE_AUTHORITY_LEVELS
            and not superseded_by_id
            and (not visibility_status or visibility_status in WRITER_SAFE_VISIBILITY_STATUSES)
        )
        return TimelineNodeVersionStatusResponse(
            scope=self._scope(mapping),
            node_type=normalized_type,
            node_id=node_id,
            current=current,
            status=status,
            lifecycle_state=lifecycle_state,
            authority_level=authority_level,
            visibility_status=visibility_status,
            superseded_by_id=superseded_by_id,
            deleted=deleted,
            usable_for_writer=current,
        )

    def _resolve_mapping(self, project_id: str) -> RuntimeProjectMapping:
        if settings.storage_mode != STORAGE_MODE_POSTGRES_PRIMARY:
            raise StorageError(
                "TEMPORAL_RESOLVER_POSTGRES_PRIMARY_REQUIRED: "
                "Temporal Resolver read APIs are available only in postgres_primary mode."
            )
        explicit_project_id = validate_runtime_project_id(project_id) if project_id else ""
        return resolve_runtime_project_mapping(
            explicit_project_id=explicit_project_id,
            store=self.store,
            base_data_dir=settings.data_dir,
        )

    def _connect(self) -> Any:
        return self._active_connection_factory().connect()

    def _active_connection_factory(self) -> PostgresConnectionFactory:
        if self._connection_factory is not None:
            return self._connection_factory
        return PostgresConnectionFactory(database_url=settings.database_url)

    def _scope(self, mapping: RuntimeProjectMapping) -> TemporalResolverScope:
        return TemporalResolverScope(
            project_id=mapping.project_id,
            storage_mode=mapping.storage_mode,
            mapping_source=mapping.source,
            compatibility_selection_used=mapping.compatibility_selection_used,
            warnings=list(mapping.warnings),
        )

    def _writer_safe_filters(self) -> list[str]:
        return [
            "project_id scoped by runtime project mapping",
            "deleted_at IS NULL",
            "superseded_by_id IS NULL where available",
            "status IN CONFIRMED/FORMAL_APPLIED/TEMPORARY_CONFIRMED",
            "lifecycle_state = ACTIVE",
            "authority_level IN USER_LOCKED/USER_CONFIRMED/FORMAL_APPLIED/SYSTEM_CONFIRMED",
            "visibility_status IN KNOWN/RESTORED",
            "valid_from_sort_key <= Tw and Tw < valid_to_sort_key when valid_to exists",
            "reader disclosure requires revealed_to_reader_at_sort_key <= Tn or equivalent narrative sort key",
            "Temporal Resolver never returns forbidden access labels as WriterAgent usable facts",
        ]

    def _character_visible_memory_sql(self) -> str:
        return f"""
        WITH resolved AS (
          SELECT p.id AS project_uuid, ch.id AS character_uuid, tl.id AS timeline_uuid
          FROM {self.schema_name}.projects p
          JOIN {self.schema_name}.characters ch
            ON ch.project_id = p.id
           AND ch.character_id = %s
           AND ch.deleted_at IS NULL
          JOIN {self.schema_name}.timelines tl
            ON tl.project_id = p.id
           AND tl.timeline_id = %s
           AND tl.deleted_at IS NULL
          WHERE p.project_id = %s
            AND p.deleted_at IS NULL
        )
        SELECT
          cmn.character_memory_node_id,
          ch.character_id,
          tl.timeline_id,
          cmn.memory_type,
          cmn.visibility_status,
          cmn.content,
          cmn.summary,
          cmn.experienced_at,
          cmn.experienced_at_sort_key,
          cmn.known_at,
          cmn.known_at_sort_key,
          cmn.narrative_recorded_at,
          cmn.narrative_recorded_at_sort_key,
          cmn.valid_from,
          cmn.valid_from_sort_key,
          cmn.valid_to,
          cmn.valid_to_sort_key,
          cmn.status,
          cmn.authority_level,
          cmn.source_refs
        FROM resolved r
        JOIN {self.schema_name}.character_memory_nodes cmn
          ON cmn.project_id = r.project_uuid
         AND cmn.character_id = r.character_uuid
         AND cmn.timeline_id = r.timeline_uuid
        JOIN {self.schema_name}.characters ch
          ON ch.id = cmn.character_id
         AND ch.project_id = cmn.project_id
        JOIN {self.schema_name}.timelines tl
          ON tl.id = cmn.timeline_id
         AND tl.project_id = cmn.project_id
        WHERE cmn.deleted_at IS NULL
          AND cmn.superseded_by_id IS NULL
          AND cmn.status IN ('CONFIRMED', 'FORMAL_APPLIED', 'TEMPORARY_CONFIRMED')
          AND cmn.lifecycle_state = 'ACTIVE'
          AND cmn.authority_level IN {WRITER_SAFE_AUTHORITY_LEVEL_SQL}
          AND cmn.visibility_status IN ('KNOWN', 'RESTORED')
          AND cmn.known_at_sort_key <= %s
          AND cmn.valid_from_sort_key <= %s
          AND (cmn.valid_to_sort_key IS NULL OR cmn.valid_to_sort_key > %s)
          AND cmn.narrative_recorded_at_sort_key <= %s
        ORDER BY cmn.known_at_sort_key DESC, cmn.valid_from_sort_key DESC, cmn.revision DESC, cmn.character_memory_node_id
        LIMIT %s
        """

    def _location_state_at_time_sql(self) -> str:
        return f"""
        WITH resolved AS (
          SELECT p.id AS project_uuid, wl.id AS location_uuid, tl.id AS timeline_uuid
          FROM {self.schema_name}.projects p
          JOIN {self.schema_name}.world_locations wl
            ON wl.project_id = p.id
           AND wl.location_id = %s
           AND wl.deleted_at IS NULL
          JOIN {self.schema_name}.timelines tl
            ON tl.project_id = p.id
           AND tl.timeline_id = %s
           AND tl.deleted_at IS NULL
          WHERE p.project_id = %s
            AND p.deleted_at IS NULL
        )
        SELECT
          lsn.location_state_node_id,
          wl.location_id,
          tl.timeline_id,
          lsn.time_anchor,
          lsn.time_anchor_sort_key,
          lsn.valid_from,
          lsn.valid_from_sort_key,
          lsn.valid_to,
          lsn.valid_to_sort_key,
          lsn.state_snapshot,
          lsn.known_by_character_refs,
          lsn.revealed_to_reader_at,
          lsn.visibility_status,
          lsn.status,
          lsn.authority_level,
          lcd.location_change_delta_id,
          lcd.change_summary,
          lcd.change_detail,
          lcd.visibility_status,
          lcd.status,
          lcd.authority_level
        FROM resolved r
        JOIN {self.schema_name}.location_state_nodes lsn
          ON lsn.project_id = r.project_uuid
         AND lsn.location_id = r.location_uuid
         AND lsn.timeline_id = r.timeline_uuid
        JOIN {self.schema_name}.world_locations wl
          ON wl.id = lsn.location_id
         AND wl.project_id = lsn.project_id
        JOIN {self.schema_name}.timelines tl
          ON tl.id = lsn.timeline_id
         AND tl.project_id = lsn.project_id
        LEFT JOIN {self.schema_name}.location_change_deltas lcd
          ON lcd.id = lsn.change_from_previous_id
         AND lcd.project_id = lsn.project_id
         AND lcd.deleted_at IS NULL
         AND lcd.superseded_by_id IS NULL
         AND lcd.status IN ('CONFIRMED', 'FORMAL_APPLIED', 'TEMPORARY_CONFIRMED')
         AND lcd.lifecycle_state = 'ACTIVE'
         AND lcd.authority_level IN {WRITER_SAFE_AUTHORITY_LEVEL_SQL}
         AND lcd.visibility_status IN ('KNOWN', 'RESTORED')
        WHERE lsn.deleted_at IS NULL
          AND lsn.superseded_by_id IS NULL
          AND lsn.status IN ('CONFIRMED', 'FORMAL_APPLIED', 'TEMPORARY_CONFIRMED')
          AND lsn.lifecycle_state = 'ACTIVE'
          AND lsn.authority_level IN {WRITER_SAFE_AUTHORITY_LEVEL_SQL}
          AND lsn.visibility_status IN ('KNOWN', 'RESTORED')
          AND lsn.valid_from_sort_key <= %s
          AND (lsn.valid_to_sort_key IS NULL OR lsn.valid_to_sort_key > %s)
        ORDER BY lsn.valid_from_sort_key DESC, lsn.time_anchor_sort_key DESC, lsn.revision DESC, lsn.location_state_node_id
        LIMIT %s
        """

    def _reader_disclosure_character_memory_sql(self) -> str:
        return f"""
        WITH resolved AS (
          SELECT p.id AS project_uuid
          FROM {self.schema_name}.projects p
          WHERE p.project_id = %s
            AND p.deleted_at IS NULL
        )
        SELECT
          cmn.character_memory_node_id,
          cmn.visibility_status,
          cmn.narrative_recorded_at,
          cmn.narrative_recorded_at_sort_key,
          cmn.status,
          cmn.authority_level
        FROM resolved r
        JOIN {self.schema_name}.character_memory_nodes cmn
          ON cmn.project_id = r.project_uuid
         AND cmn.character_memory_node_id = %s
        WHERE cmn.deleted_at IS NULL
          AND cmn.superseded_by_id IS NULL
          AND cmn.status IN ('CONFIRMED', 'FORMAL_APPLIED', 'TEMPORARY_CONFIRMED')
          AND cmn.lifecycle_state = 'ACTIVE'
          AND cmn.authority_level IN {WRITER_SAFE_AUTHORITY_LEVEL_SQL}
          AND cmn.visibility_status IN ('KNOWN', 'RESTORED')
          AND cmn.narrative_recorded_at_sort_key <= %s
        ORDER BY cmn.narrative_recorded_at_sort_key DESC, cmn.revision DESC
        LIMIT %s
        """

    def _reader_disclosure_location_state_sql(self) -> str:
        return f"""
        WITH resolved AS (
          SELECT p.id AS project_uuid
          FROM {self.schema_name}.projects p
          WHERE p.project_id = %s
            AND p.deleted_at IS NULL
        )
        SELECT
          lsn.location_state_node_id,
          lsn.visibility_status,
          lsn.revealed_to_reader_at,
          lsn.revealed_to_reader_at_sort_key,
          lsn.status,
          lsn.authority_level
        FROM resolved r
        JOIN {self.schema_name}.location_state_nodes lsn
          ON lsn.project_id = r.project_uuid
         AND lsn.location_state_node_id = %s
        WHERE lsn.deleted_at IS NULL
          AND lsn.superseded_by_id IS NULL
          AND lsn.status IN ('CONFIRMED', 'FORMAL_APPLIED', 'TEMPORARY_CONFIRMED')
          AND lsn.lifecycle_state = 'ACTIVE'
          AND lsn.authority_level IN {WRITER_SAFE_AUTHORITY_LEVEL_SQL}
          AND lsn.visibility_status IN ('KNOWN', 'RESTORED')
          AND lsn.revealed_to_reader_at_sort_key IS NOT NULL
          AND lsn.revealed_to_reader_at_sort_key <= %s
        ORDER BY lsn.revealed_to_reader_at_sort_key DESC, lsn.revision DESC
        LIMIT %s
        """

    def _reader_disclosure_location_change_delta_sql(self) -> str:
        return f"""
        WITH resolved AS (
          SELECT p.id AS project_uuid
          FROM {self.schema_name}.projects p
          WHERE p.project_id = %s
            AND p.deleted_at IS NULL
        )
        SELECT
          lcd.location_change_delta_id,
          lcd.visibility_status,
          lcd.revealed_to_reader_at,
          lcd.revealed_to_reader_at_sort_key,
          lcd.status,
          lcd.authority_level
        FROM resolved r
        JOIN {self.schema_name}.location_change_deltas lcd
          ON lcd.project_id = r.project_uuid
         AND lcd.location_change_delta_id = %s
        WHERE lcd.deleted_at IS NULL
          AND lcd.superseded_by_id IS NULL
          AND lcd.status IN ('CONFIRMED', 'FORMAL_APPLIED', 'TEMPORARY_CONFIRMED')
          AND lcd.lifecycle_state = 'ACTIVE'
          AND lcd.authority_level IN {WRITER_SAFE_AUTHORITY_LEVEL_SQL}
          AND lcd.visibility_status IN ('KNOWN', 'RESTORED')
          AND lcd.revealed_to_reader_at_sort_key IS NOT NULL
          AND lcd.revealed_to_reader_at_sort_key <= %s
        ORDER BY lcd.revealed_to_reader_at_sort_key DESC, lcd.revision DESC
        LIMIT %s
        """

    def _timeline_node_version_status_sql(self, spec: dict[str, str]) -> str:
        visibility_expr = (
            spec["visibility_column"]
            if spec["visibility_column"]
            else "''::text"
        )
        superseded_expr = (
            f"COALESCE(target.{spec['superseded_column']}::text, '')"
            if spec["superseded_column"]
            else "''::text"
        )
        return f"""
        WITH resolved AS (
          SELECT p.id AS project_uuid
          FROM {self.schema_name}.projects p
          WHERE p.project_id = %s
            AND p.deleted_at IS NULL
        )
        SELECT
          target.status,
          target.lifecycle_state,
          target.authority_level,
          {superseded_expr} AS superseded_by_id,
          {visibility_expr} AS visibility_status,
          (target.deleted_at IS NOT NULL) AS deleted
        FROM resolved r
        JOIN {self.schema_name}.{spec['table']} target
          ON target.project_id = r.project_uuid
         AND target.{spec['business_id_column']} = %s
        LIMIT %s
        """

    def _location_state_from_row(self, row: tuple[Any, ...]) -> LocationStateAtTimeResult:
        change = None
        if row[15]:
            change = LocationChangeDeltaResult(
                location_change_delta_id=str(row[15] or ""),
                location_id=str(row[1] or ""),
                change_summary=str(row[16] or ""),
                change_detail=str(row[17] or ""),
                visibility_status=str(row[18] or ""),
                status=str(row[19] or ""),
                authority_level=str(row[20] or ""),
            )
        return LocationStateAtTimeResult(
            location_state_node_id=str(row[0] or ""),
            location_id=str(row[1] or ""),
            timeline_id=str(row[2] or ""),
            time_anchor=str(row[3] or ""),
            time_anchor_sort_key=int(row[4] or 0),
            valid_from=str(row[5] or ""),
            valid_from_sort_key=int(row[6] or 0),
            valid_to=str(row[7] or ""),
            valid_to_sort_key=_optional_int(row[8]),
            state_snapshot=_json_dict(row[9]),
            known_by_character_refs=_json_list(row[10]),
            revealed_to_reader_at=str(row[11] or ""),
            visibility_status=str(row[12] or ""),
            status=str(row[13] or ""),
            authority_level=str(row[14] or ""),
            change_from_previous=change,
        )


_NODE_VERSION_SPECS = {
    "timeline": {
        "table": "timelines",
        "business_id_column": "timeline_id",
        "superseded_column": "",
        "visibility_column": "''::text",
    },
    "character_memory_node": {
        "table": "character_memory_nodes",
        "business_id_column": "character_memory_node_id",
        "superseded_column": "superseded_by_id",
        "visibility_column": "target.visibility_status",
    },
    "location_state_node": {
        "table": "location_state_nodes",
        "business_id_column": "location_state_node_id",
        "superseded_column": "superseded_by_id",
        "visibility_column": "target.visibility_status",
    },
    "location_change_delta": {
        "table": "location_change_deltas",
        "business_id_column": "location_change_delta_id",
        "superseded_column": "superseded_by_id",
        "visibility_column": "target.visibility_status",
    },
}


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or 20), 100))


def _required_id(value: str, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise StorageError(f"TEMPORAL_RESOLVER_INVALID_INPUT: {label} is required.")
    return cleaned


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_dict(value: Any) -> dict[str, Any]:
    parsed = _json_value(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    parsed = _json_value(value, [])
    return parsed if isinstance(parsed, list) else []


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value
