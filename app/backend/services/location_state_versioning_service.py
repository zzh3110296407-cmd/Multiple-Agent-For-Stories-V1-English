from __future__ import annotations

import hashlib
import json
from typing import Any

from app.backend.core.config import STORAGE_MODE_POSTGRES_PRIMARY, settings
from app.backend.models.temporal_resolver import (
    LocationStateVersionedInsertRequest,
    LocationStateVersionedInsertResponse,
    TemporalResolverScope,
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


SAFE_INSERT_STATUSES = {"CONFIRMED", "FORMAL_APPLIED", "TEMPORARY_CONFIRMED"}
SAFE_INSERT_VISIBILITY = {"KNOWN", "RESTORED"}
SAFE_INSERT_AUTHORITY = {
    "USER_LOCKED",
    "USER_CONFIRMED",
    "FORMAL_APPLIED",
    "SYSTEM_CONFIRMED",
}
ACTIVE_NODE_COLUMNS = (
    "id",
    "location_state_node_id",
    "time_anchor",
    "time_anchor_sort_key",
    "next_node_id",
    "valid_from",
    "valid_from_sort_key",
    "valid_to",
    "valid_to_sort_key",
    "state_snapshot",
    "known_by_character_refs",
    "revealed_to_reader_at",
    "revealed_to_reader_at_sort_key",
    "visibility_status",
    "status",
    "lifecycle_state",
    "authority_level",
    "version",
    "revision",
    "source_refs",
    "metadata",
)


class LocationStateVersioningService:
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

    def insert_location_state_version(
        self,
        *,
        location_id: str,
        request: LocationStateVersionedInsertRequest,
        project_id: str = "",
    ) -> LocationStateVersionedInsertResponse:
        mapping = self._resolve_mapping(project_id)
        required_location_id = _required_id(location_id, "location_id")
        required_timeline_id = _required_id(request.timeline_id, "timeline_id")
        required_node_id = _required_id(
            request.location_state_node_id,
            "location_state_node_id",
        )
        _validate_write_labels(request)

        with self._connect() as conn:
            resolved = conn.execute(
                self._resolve_scope_sql(),
                (required_location_id, required_timeline_id, mapping.project_id),
            ).fetchone()
            if resolved is None:
                raise StorageError(
                    "LOCATION_STATE_VERSION_INSERT_SCOPE_NOT_FOUND: "
                    "Project, location or timeline was not found."
                )
            project_uuid, location_uuid, timeline_uuid = resolved[0], resolved[1], resolved[2]
            source_event_uuid = self._resolve_optional_event_uuid(conn, project_uuid, request.source_event_id)
            active_nodes = self._load_active_nodes(conn, project_uuid, location_uuid, timeline_uuid)
            if any(int(node["valid_from_sort_key"] or 0) == int(request.valid_from_sort_key) for node in active_nodes):
                raise StorageError(
                    "LOCATION_STATE_VERSION_INSERT_TIME_CONFLICT: "
                    "A current location state node already starts at this world-time sort key."
                )

            previous_node = _previous_node(active_nodes, request.valid_from_sort_key)
            next_node = _next_node(active_nodes, request.valid_from_sort_key)
            next_node_uuid = None
            new_node_uuid = self._insert_location_state_node(
                conn=conn,
                project_uuid=project_uuid,
                location_uuid=location_uuid,
                timeline_uuid=timeline_uuid,
                previous_node_uuid=previous_node["id"] if previous_node else None,
                next_node_uuid=None,
                change_from_previous_uuid=None,
                superseded_by_uuid=None,
                node_id=required_node_id,
                time_anchor=request.time_anchor,
                time_anchor_sort_key=request.time_anchor_sort_key,
                valid_from=request.valid_from or request.time_anchor,
                valid_from_sort_key=request.valid_from_sort_key,
                valid_to=next_node["valid_from"] if next_node else request.valid_to,
                valid_to_sort_key=next_node["valid_from_sort_key"] if next_node else request.valid_to_sort_key,
                state_snapshot=request.state_snapshot,
                known_by_character_refs=request.known_by_character_refs,
                revealed_to_reader_at=request.revealed_to_reader_at,
                revealed_to_reader_at_sort_key=request.revealed_to_reader_at_sort_key,
                visibility_status=request.visibility_status,
                status=request.status,
                authority_level=request.authority_level,
                version=1,
                revision=1,
                source_refs=request.source_refs,
                metadata={
                    **request.metadata,
                    "versioned_insert": {
                        "inserted_between_previous": _business_id(previous_node),
                        "inserted_before_successor": _business_id(next_node),
                    },
                },
            )

            delta_ids: list[str] = []
            if previous_node is not None:
                delta_ids.append(
                    self._insert_location_change_delta(
                        conn=conn,
                        project_uuid=project_uuid,
                        location_uuid=location_uuid,
                        from_node_uuid=previous_node["id"],
                        to_node_uuid=new_node_uuid,
                        source_event_uuid=source_event_uuid,
                        delta_id=f"{required_node_id}__delta_from__{previous_node['location_state_node_id']}",
                        change_summary=request.change_summary or "Versioned middle insertion delta.",
                        change_detail=request.change_detail,
                        known_by_character_refs=request.known_by_character_refs,
                        revealed_to_reader_at=request.revealed_to_reader_at,
                        revealed_to_reader_at_sort_key=request.revealed_to_reader_at_sort_key,
                        visibility_status=request.visibility_status,
                        status=request.status,
                        authority_level=request.authority_level,
                        source_refs=request.source_refs,
                        metadata={
                            "versioned_insert_delta": True,
                            "from_location_state_node_id": previous_node["location_state_node_id"],
                            "to_location_state_node_id": required_node_id,
                        },
                    )
                )

            successor_business_ids: list[str] = []
            superseded_business_ids: list[str] = []
            if next_node is not None:
                successor_business_id = _successor_business_id(next_node)
                successor_business_ids.append(successor_business_id)
                superseded_business_ids.append(str(next_node["location_state_node_id"]))
                next_node_uuid = self._insert_location_state_node(
                    conn=conn,
                    project_uuid=project_uuid,
                    location_uuid=location_uuid,
                    timeline_uuid=timeline_uuid,
                    previous_node_uuid=new_node_uuid,
                    next_node_uuid=next_node.get("next_node_id"),
                    change_from_previous_uuid=None,
                    superseded_by_uuid=None,
                    node_id=successor_business_id,
                    time_anchor=str(next_node["time_anchor"] or ""),
                    time_anchor_sort_key=int(next_node["time_anchor_sort_key"] or 0),
                    valid_from=str(next_node["valid_from"] or ""),
                    valid_from_sort_key=int(next_node["valid_from_sort_key"] or 0),
                    valid_to=str(next_node["valid_to"] or ""),
                    valid_to_sort_key=next_node["valid_to_sort_key"],
                    state_snapshot=_json_dict(next_node["state_snapshot"]),
                    known_by_character_refs=_json_list(next_node["known_by_character_refs"]),
                    revealed_to_reader_at=str(next_node["revealed_to_reader_at"] or ""),
                    revealed_to_reader_at_sort_key=next_node["revealed_to_reader_at_sort_key"],
                    visibility_status=str(next_node["visibility_status"] or "KNOWN"),
                    status=str(next_node["status"] or "CONFIRMED"),
                    authority_level=str(next_node["authority_level"] or "SYSTEM_CONFIRMED"),
                    version=int(next_node["version"] or 1) + 1,
                    revision=int(next_node["revision"] or 1) + 1,
                    source_refs=_json_list(next_node["source_refs"]),
                    metadata={
                        **_json_dict(next_node["metadata"]),
                        "supersedes_location_state_node_id": next_node["location_state_node_id"],
                        "versioned_insert_successor": True,
                        "new_previous_location_state_node_id": required_node_id,
                    },
                )
                delta_ids.append(
                    self._insert_location_change_delta(
                        conn=conn,
                        project_uuid=project_uuid,
                        location_uuid=location_uuid,
                        from_node_uuid=new_node_uuid,
                        to_node_uuid=next_node_uuid,
                        source_event_uuid=source_event_uuid,
                        delta_id=f"{successor_business_id}__delta_from__{required_node_id}",
                        change_summary="Recomputed successor delta after versioned middle insertion.",
                        change_detail=request.change_detail,
                        known_by_character_refs=_json_list(next_node["known_by_character_refs"]),
                        revealed_to_reader_at=str(next_node["revealed_to_reader_at"] or ""),
                        revealed_to_reader_at_sort_key=next_node["revealed_to_reader_at_sort_key"],
                        visibility_status=str(next_node["visibility_status"] or "KNOWN"),
                        status=str(next_node["status"] or "CONFIRMED"),
                        authority_level=str(next_node["authority_level"] or "SYSTEM_CONFIRMED"),
                        source_refs=_json_list(next_node["source_refs"]),
                        metadata={
                            "versioned_insert_delta": True,
                            "from_location_state_node_id": required_node_id,
                            "to_location_state_node_id": successor_business_id,
                        },
                    )
                )
                conn.execute(
                    self._mark_successor_superseded_sql(),
                    (next_node_uuid, next_node["id"], project_uuid),
                )
                conn.execute(
                    self._link_inserted_successor_sql(),
                    (next_node_uuid, new_node_uuid, project_uuid),
                )

            affected_refs = self._collect_affected_downstream_refs(conn, project_uuid, next_node["id"] if next_node else new_node_uuid)
            invalidated_context_pack_ids = self._invalidate_context_pack_builds(
                conn=conn,
                project_uuid=project_uuid,
                old_business_id=_business_id(next_node),
                new_business_id=required_node_id,
            )

        return LocationStateVersionedInsertResponse(
            scope=self._scope(mapping),
            location_id=required_location_id,
            timeline_id=required_timeline_id,
            inserted_location_state_node_id=required_node_id,
            inserted_node_uuid=str(new_node_uuid or ""),
            superseded_location_state_node_ids=superseded_business_ids,
            successor_location_state_node_ids=successor_business_ids,
            recomputed_location_change_delta_ids=delta_ids,
            affected_downstream_refs=affected_refs,
            invalidated_context_pack_build_ids=invalidated_context_pack_ids,
            old_records_overwritten=False,
            versioned_insert_applied=True,
        )

    def _resolve_mapping(self, project_id: str) -> RuntimeProjectMapping:
        if settings.storage_mode != STORAGE_MODE_POSTGRES_PRIMARY:
            raise StorageError(
                "LOCATION_STATE_VERSION_INSERT_POSTGRES_PRIMARY_REQUIRED: "
                "Versioned timeline inserts are available only in postgres_primary mode."
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

    def _jsonb(self, value: Any) -> Any:
        return self._active_connection_factory().jsonb_adapter()(value)

    def _resolve_scope_sql(self) -> str:
        return f"""
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
        """

    def _active_location_state_nodes_sql(self) -> str:
        return f"""
        SELECT
          id,
          location_state_node_id,
          time_anchor,
          time_anchor_sort_key,
          next_node_id,
          valid_from,
          valid_from_sort_key,
          valid_to,
          valid_to_sort_key,
          state_snapshot,
          known_by_character_refs,
          revealed_to_reader_at,
          revealed_to_reader_at_sort_key,
          visibility_status,
          status,
          lifecycle_state,
          authority_level,
          version,
          revision,
          source_refs,
          metadata
        FROM {self.schema_name}.location_state_nodes
        WHERE project_id = %s
          AND location_id = %s
          AND timeline_id = %s
          AND deleted_at IS NULL
          AND superseded_by_id IS NULL
          AND lifecycle_state = 'ACTIVE'
        ORDER BY valid_from_sort_key ASC, revision ASC, location_state_node_id ASC
        FOR UPDATE
        """

    def _insert_location_state_node_sql(self) -> str:
        return f"""
        INSERT INTO {self.schema_name}.location_state_nodes (
          project_id,
          location_state_node_id,
          location_id,
          timeline_id,
          previous_node_id,
          next_node_id,
          change_from_previous_id,
          superseded_by_id,
          schema_version,
          time_anchor,
          time_anchor_sort_key,
          valid_from,
          valid_from_sort_key,
          valid_to,
          valid_to_sort_key,
          state_snapshot,
          known_by_character_refs,
          revealed_to_reader_at,
          revealed_to_reader_at_sort_key,
          visibility_status,
          status,
          lifecycle_state,
          authority_level,
          version,
          revision,
          source_type,
          source_refs,
          content_hash,
          metadata
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, %s, %s, 'phase9_m10_task6',
          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
          %s, 'ACTIVE', %s, %s, %s, 'VERSIONED_TIMELINE_INSERT', %s, %s, %s
        )
        RETURNING id
        """

    def _insert_location_change_delta_sql(self) -> str:
        return f"""
        INSERT INTO {self.schema_name}.location_change_deltas (
          project_id,
          location_change_delta_id,
          location_id,
          from_node_id,
          to_node_id,
          source_event_id,
          schema_version,
          change_summary,
          change_detail,
          known_by_character_refs,
          revealed_to_reader_at,
          revealed_to_reader_at_sort_key,
          visibility_status,
          status,
          lifecycle_state,
          authority_level,
          version,
          revision,
          source_type,
          source_refs,
          content_hash,
          metadata
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, 'phase9_m10_task6',
          %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, 1, 1,
          'VERSIONED_TIMELINE_INSERT', %s, %s, %s
        )
        RETURNING location_change_delta_id
        """

    def _mark_successor_superseded_sql(self) -> str:
        return f"""
        UPDATE {self.schema_name}.location_state_nodes
        SET superseded_by_id = %s,
            status = 'SUPERSEDED',
            lifecycle_state = 'ARCHIVED',
            metadata = metadata || '{{"superseded_by_versioned_insert": true}}'::jsonb,
            updated_at = now()
        WHERE id = %s
          AND project_id = %s
          AND deleted_at IS NULL
        """

    def _link_inserted_successor_sql(self) -> str:
        return f"""
        UPDATE {self.schema_name}.location_state_nodes
        SET next_node_id = %s,
            updated_at = now()
        WHERE id = %s
          AND project_id = %s
          AND deleted_at IS NULL
        """

    def _optional_event_sql(self) -> str:
        return f"""
        SELECT id
        FROM {self.schema_name}.events
        WHERE project_id = %s
          AND event_id = %s
          AND deleted_at IS NULL
        """

    def _affected_refs_sql(self) -> str:
        return f"""
        SELECT 'search_memory_card' AS ref_type, search_memory_card_id AS ref_id
        FROM {self.schema_name}.search_memory_cards
        WHERE project_id = %s
          AND location_state_node_id = %s
          AND deleted_at IS NULL
        UNION ALL
        SELECT 'temporal_query_result' AS ref_type, temporal_query_result_id AS ref_id
        FROM {self.schema_name}.temporal_query_results
        WHERE project_id = %s
          AND location_state_node_id = %s
          AND deleted_at IS NULL
        """

    def _context_pack_invalidation_sql(self) -> str:
        return f"""
        UPDATE {self.schema_name}.context_pack_builds
        SET status = 'SUPERSEDED',
            lifecycle_state = 'ARCHIVED',
            metadata = metadata || %s,
            updated_at = now()
        WHERE project_id = %s
          AND deleted_at IS NULL
          AND status IN ('CONFIRMED', 'FORMAL_APPLIED', 'TEMPORARY_CONFIRMED')
          AND (
            location_current_state_refs @> %s
            OR location_current_state_refs @> %s
          )
        RETURNING context_pack_build_id
        """

    def _resolve_optional_event_uuid(self, conn: Any, project_uuid: Any, source_event_id: str) -> Any | None:
        cleaned = str(source_event_id or "").strip()
        if not cleaned:
            return None
        row = conn.execute(self._optional_event_sql(), (project_uuid, cleaned)).fetchone()
        if row is None:
            raise StorageError(
                "LOCATION_STATE_VERSION_INSERT_EVENT_NOT_FOUND: "
                "source_event_id was not found in this project."
            )
        return row[0]

    def _load_active_nodes(self, conn: Any, project_uuid: Any, location_uuid: Any, timeline_uuid: Any) -> list[dict[str, Any]]:
        rows = conn.execute(
            self._active_location_state_nodes_sql(),
            (project_uuid, location_uuid, timeline_uuid),
        ).fetchall()
        return [dict(zip(ACTIVE_NODE_COLUMNS, row)) for row in rows]

    def _insert_location_state_node(
        self,
        *,
        conn: Any,
        project_uuid: Any,
        location_uuid: Any,
        timeline_uuid: Any,
        previous_node_uuid: Any | None,
        next_node_uuid: Any | None,
        change_from_previous_uuid: Any | None,
        superseded_by_uuid: Any | None,
        node_id: str,
        time_anchor: str,
        time_anchor_sort_key: int,
        valid_from: str,
        valid_from_sort_key: int,
        valid_to: str,
        valid_to_sort_key: int | None,
        state_snapshot: dict[str, Any],
        known_by_character_refs: list[Any],
        revealed_to_reader_at: str,
        revealed_to_reader_at_sort_key: int | None,
        visibility_status: str,
        status: str,
        authority_level: str,
        version: int,
        revision: int,
        source_refs: list[Any],
        metadata: dict[str, Any],
    ) -> Any:
        row = conn.execute(
            self._insert_location_state_node_sql(),
            (
                project_uuid,
                node_id,
                location_uuid,
                timeline_uuid,
                previous_node_uuid,
                next_node_uuid,
                change_from_previous_uuid,
                superseded_by_uuid,
                str(time_anchor or ""),
                int(time_anchor_sort_key or 0),
                str(valid_from or ""),
                int(valid_from_sort_key or 0),
                str(valid_to or ""),
                valid_to_sort_key,
                self._jsonb(state_snapshot),
                self._jsonb(known_by_character_refs),
                str(revealed_to_reader_at or ""),
                revealed_to_reader_at_sort_key,
                str(visibility_status or "KNOWN"),
                str(status or "CONFIRMED"),
                str(authority_level or "SYSTEM_CONFIRMED"),
                int(version or 1),
                int(revision or 1),
                self._jsonb(source_refs),
                _stable_hash({"state_snapshot": state_snapshot, "node_id": node_id}),
                self._jsonb(metadata),
            ),
        ).fetchone()
        return row[0]

    def _insert_location_change_delta(
        self,
        *,
        conn: Any,
        project_uuid: Any,
        location_uuid: Any,
        from_node_uuid: Any | None,
        to_node_uuid: Any | None,
        source_event_uuid: Any | None,
        delta_id: str,
        change_summary: str,
        change_detail: str,
        known_by_character_refs: list[Any],
        revealed_to_reader_at: str,
        revealed_to_reader_at_sort_key: int | None,
        visibility_status: str,
        status: str,
        authority_level: str,
        source_refs: list[Any],
        metadata: dict[str, Any],
    ) -> str:
        row = conn.execute(
            self._insert_location_change_delta_sql(),
            (
                project_uuid,
                delta_id,
                location_uuid,
                from_node_uuid,
                to_node_uuid,
                source_event_uuid,
                str(change_summary or ""),
                str(change_detail or ""),
                self._jsonb(known_by_character_refs),
                str(revealed_to_reader_at or ""),
                revealed_to_reader_at_sort_key,
                str(visibility_status or "KNOWN"),
                str(status or "CONFIRMED"),
                str(authority_level or "SYSTEM_CONFIRMED"),
                self._jsonb(source_refs),
                _stable_hash({"delta_id": delta_id, "from": str(from_node_uuid or ""), "to": str(to_node_uuid or "")}),
                self._jsonb(metadata),
            ),
        ).fetchone()
        return str(row[0] or delta_id)

    def _collect_affected_downstream_refs(self, conn: Any, project_uuid: Any, old_node_uuid: Any) -> list[dict[str, Any]]:
        rows = conn.execute(
            self._affected_refs_sql(),
            (project_uuid, old_node_uuid, project_uuid, old_node_uuid),
        ).fetchall()
        return [{"ref_type": str(row[0] or ""), "ref_id": str(row[1] or "")} for row in rows]

    def _invalidate_context_pack_builds(
        self,
        *,
        conn: Any,
        project_uuid: Any,
        old_business_id: str,
        new_business_id: str,
    ) -> list[str]:
        if not old_business_id:
            return []
        rows = conn.execute(
            self._context_pack_invalidation_sql(),
            (
                self._jsonb(
                    {
                        "invalidated_by_location_state_version_insert": True,
                        "old_location_state_node_id": old_business_id,
                        "new_location_state_node_id": new_business_id,
                    }
                ),
                project_uuid,
                self._jsonb([old_business_id]),
                self._jsonb([{"location_state_node_id": old_business_id}]),
            ),
        ).fetchall()
        return [str(row[0] or "") for row in rows]


def _validate_write_labels(request: LocationStateVersionedInsertRequest) -> None:
    if request.status not in SAFE_INSERT_STATUSES:
        raise StorageError("LOCATION_STATE_VERSION_INSERT_UNSAFE_STATUS: status is not accepted for WriterAgent facts.")
    if request.visibility_status not in SAFE_INSERT_VISIBILITY:
        raise StorageError("LOCATION_STATE_VERSION_INSERT_UNSAFE_VISIBILITY: visibility_status is not WriterAgent-safe.")
    if request.authority_level not in SAFE_INSERT_AUTHORITY:
        raise StorageError("LOCATION_STATE_VERSION_INSERT_UNSAFE_AUTHORITY: authority_level is not accepted.")


def _previous_node(nodes: list[dict[str, Any]], sort_key: int) -> dict[str, Any] | None:
    before = [node for node in nodes if int(node["valid_from_sort_key"] or 0) < int(sort_key)]
    return before[-1] if before else None


def _next_node(nodes: list[dict[str, Any]], sort_key: int) -> dict[str, Any] | None:
    after = [node for node in nodes if int(node["valid_from_sort_key"] or 0) > int(sort_key)]
    return after[0] if after else None


def _successor_business_id(node: dict[str, Any]) -> str:
    version = int(node.get("version") or 1) + 1
    return f"{node['location_state_node_id']}__v{version}"


def _business_id(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    return str(node.get("location_state_node_id") or "")


def _required_id(value: str, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise StorageError(f"LOCATION_STATE_VERSION_INSERT_INVALID_INPUT: {label} is required.")
    return cleaned


def _json_dict(value: Any) -> dict[str, Any]:
    parsed = _json_value(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    parsed = _json_value(value, [])
    return parsed if isinstance(parsed, list) else []


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _stable_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
