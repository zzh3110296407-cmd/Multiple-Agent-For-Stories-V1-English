from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable

from app.backend.core.config import redact_database_url
from app.backend.storage.json_store import StorageError


_SAFE_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UUID_TEXT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_M2_RECORD_PAYLOAD_KEY = "_phase9_m2_record_payload"

_CANONICAL_STATUS_VALUES = {
    "DRAFT",
    "CANDIDATE",
    "PROVISIONAL",
    "TEMPORARY_CONFIRMED",
    "CONFIRMED",
    "FORMAL_APPLIED",
    "SUPERSEDED",
    "REJECTED",
    "ARCHIVED",
    "DELETED",
}
_LIFECYCLE_VALUES = {"ACTIVE", "PROVISIONAL", "ARCHIVED", "DELETED"}
_AUTHORITY_VALUES = {
    "USER_LOCKED",
    "USER_CONFIRMED",
    "FORMAL_APPLIED",
    "SYSTEM_CONFIRMED",
    "GENERATED_CANDIDATE",
    "ANALYZER_REFERENCE",
    "MIGRATED_REFERENCE",
    "PLUGIN_REFERENCE",
    "UNKNOWN",
}


class PostgresConnectionFactory:
    def __init__(
        self,
        *,
        database_url: str,
        schema_name: str = "mas_phase875_proto",
    ) -> None:
        if not database_url:
            raise StorageError(
                "Normalized PostgreSQL repositories require "
                "MULTIPLE_AGENT_STORIES_DATABASE_URL; no password or connection "
                "string was logged."
            )
        _assert_safe_identifier(schema_name, "schema")
        self.database_url = database_url
        self.safe_database_url = redact_database_url(database_url)
        self.schema_name = schema_name

    def connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:
            raise StorageError(
                "postgres_primary normalized repositories require psycopg. "
                "Install backend requirements; no database URL was logged."
            ) from exc
        try:
            return psycopg.connect(self.database_url)
        except Exception as exc:
            raise StorageError(
                "Cannot connect to normalized PostgreSQL repositories "
                f"({self.safe_database_url}); raw connection string was not logged."
            ) from exc

    def jsonb_adapter(self) -> Callable[[Any], Any]:
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise StorageError(
                "postgres_primary normalized repositories require psycopg JSONB support."
            ) from exc
        return Jsonb


@dataclass(frozen=True)
class NormalizedListTableConfig:
    table_name: str
    id_field: str
    business_id_column: str
    select_columns: tuple[str, ...]
    order_by: str


@dataclass(frozen=True)
class NormalizedExtraColumn:
    column_name: str
    value_getter: Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class NormalizedForeignKeyColumn:
    column_name: str
    target_table: str
    target_business_id_column: str
    required: bool = False


@dataclass(frozen=True)
class NormalizedPayloadRepositorySpec:
    repository_name: str
    table_name: str
    id_field: str
    business_id_column: str
    extra_columns: tuple[NormalizedExtraColumn, ...] = ()
    order_by: str | None = None
    active_null_columns: tuple[str, ...] = ()
    foreign_keys: tuple[NormalizedForeignKeyColumn, ...] = ()


class PostgresNormalizedListRepository:
    def __init__(
        self,
        *,
        connection_factory: PostgresConnectionFactory,
        data_dir: Path,
        table_config: NormalizedListTableConfig,
        jsonb_adapter: Callable[[Any], Any] | None = None,
    ) -> None:
        _assert_safe_identifier(table_config.table_name, "table")
        _assert_safe_identifier(table_config.business_id_column, "business id column")
        _assert_safe_identifier(table_config.order_by, "order by column")
        for column in table_config.select_columns:
            _assert_safe_identifier(column, "select column")
        self.connection_factory = connection_factory
        self.data_dir = data_dir
        self.table_config = table_config
        self.schema_name = connection_factory.schema_name
        self.safe_database_url = getattr(connection_factory, "safe_database_url", "")
        self._jsonb_adapter = jsonb_adapter
        self.default_project_business_id = data_dir.name or "local_project"

    def list_all(self) -> list[dict[str, Any]]:
        project_business_id = self.default_project_business_id
        try:
            with self.connection_factory.connect() as conn:
                project_uuid = self._find_project_uuid(conn, project_business_id)
                if not project_uuid:
                    return []
                rows = self._fetch_all(conn, project_uuid)
            return [self._row_to_record(row, project_business_id) for row in rows]
        except StorageError:
            raise
        except Exception as exc:
            self._raise_repository_error("list", exc)

    def get_by_id(self, record_id: str) -> dict[str, Any] | None:
        project_business_id = self.default_project_business_id
        try:
            with self.connection_factory.connect() as conn:
                project_uuid = self._find_project_uuid(conn, project_business_id)
                if not project_uuid:
                    return None
                row = conn.execute(
                    self._select_one_sql(),
                    self._select_one_params(project_uuid, record_id),
                ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row, project_business_id)
        except StorageError:
            raise
        except Exception as exc:
            self._raise_repository_error("get", exc)

    def write_all(self, records: list[dict[str, Any]]) -> None:
        project_business_id = self._project_business_id_from_records(records)
        try:
            with self.connection_factory.connect() as conn:
                project_uuid = self._ensure_project(conn, project_business_id)
                business_ids = self._business_ids(records)
                conn.execute(
                    self._soft_delete_missing_rows_sql(),
                    self._soft_delete_missing_rows_params(project_uuid, business_ids),
                )
                for record in records:
                    self._upsert_with_conn(conn, project_uuid, project_business_id, record)
        except StorageError:
            raise
        except Exception as exc:
            self._raise_repository_error("write", exc)

    def append(self, record: dict[str, Any]) -> None:
        self.upsert(record, self.table_config.id_field)

    def upsert(self, record: dict[str, Any], id_field: str | None = None) -> None:
        project_business_id = self._project_business_id(record)
        try:
            with self.connection_factory.connect() as conn:
                project_uuid = self._ensure_project(conn, project_business_id)
                self._upsert_with_conn(conn, project_uuid, project_business_id, record, id_field)
        except StorageError:
            raise
        except Exception as exc:
            self._raise_repository_error("upsert", exc)

    def _fetch_all(self, conn: Any, project_uuid: str) -> list[tuple[Any, ...]]:
        cursor = conn.execute(self._select_all_sql(), self._select_all_params(project_uuid))
        fetchall = getattr(cursor, "fetchall", None)
        if callable(fetchall):
            return list(fetchall())
        row = cursor.fetchone()
        return [] if row is None else [row]

    def _upsert_with_conn(
        self,
        conn: Any,
        project_uuid: str,
        project_business_id: str,
        record: dict[str, Any],
        id_field: str | None = None,
    ) -> None:
        values = self._record_to_values(conn, project_uuid, project_business_id, record, id_field)
        conn.execute(self._upsert_sql(), values)

    def _record_to_values(
        self,
        conn: Any,
        project_uuid: str,
        project_business_id: str,
        record: dict[str, Any],
        id_field: str | None,
    ) -> tuple[Any, ...]:
        raise NotImplementedError

    def _row_to_record(
        self,
        row: tuple[Any, ...],
        project_business_id: str,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _project_business_id_from_records(self, records: list[dict[str, Any]]) -> str:
        for record in records:
            project_id = str(record.get("project_id") or "").strip()
            if project_id:
                return project_id
        return self.default_project_business_id

    def _project_business_id(self, record: dict[str, Any]) -> str:
        return str(record.get("project_id") or self.default_project_business_id).strip()

    def _find_project_uuid(self, conn: Any, project_business_id: str) -> str | None:
        row = conn.execute(
            f"SELECT id FROM {self.schema_name}.projects WHERE project_id = %s AND deleted_at IS NULL",
            (project_business_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def _ensure_project(self, conn: Any, project_business_id: str) -> str:
        row = conn.execute(
            f"""
            INSERT INTO {self.schema_name}.projects (
              project_id,
              display_name,
              storage_mode,
              status,
              lifecycle_state,
              authority_level,
              source_type,
              metadata
            )
            VALUES (%s, %s, 'POSTGRES_PRIMARY', 'CONFIRMED', 'ACTIVE', 'SYSTEM_CONFIRMED', 'RUNTIME', %s)
            ON CONFLICT (project_id) DO UPDATE SET
              updated_at = {self.schema_name}.projects.updated_at
            RETURNING id
            """,
            (
                project_business_id,
                project_business_id,
                self._to_jsonb({"phase": "phase9_m2", "source": "normalized_repository"}),
            ),
        ).fetchone()
        if row is None:
            raise StorageError("Normalized PostgreSQL repository could not resolve project id.")
        return str(row[0])

    def _select_all_sql(self) -> str:
        columns = ", ".join(self.table_config.select_columns)
        return (
            f"SELECT {columns} FROM {self.schema_name}.{self.table_config.table_name} "
            f"WHERE project_id = %s AND deleted_at IS NULL "
            f"ORDER BY {self.table_config.order_by}"
        )

    def _select_one_sql(self) -> str:
        columns = ", ".join(self.table_config.select_columns)
        return (
            f"SELECT {columns} FROM {self.schema_name}.{self.table_config.table_name} "
            f"WHERE project_id = %s "
            f"AND {self.table_config.business_id_column} = %s "
            f"AND deleted_at IS NULL"
        )

    def _select_all_params(self, project_uuid: str) -> tuple[Any, ...]:
        return (project_uuid,)

    def _select_one_params(self, project_uuid: str, record_id: str) -> tuple[Any, ...]:
        return (project_uuid, record_id)

    def _delete_project_rows_sql(self) -> str:
        raise NotImplementedError(
            "Normalized authoritative repositories must not hard-delete project rows."
        )

    def _soft_delete_missing_rows_sql(self) -> str:
        return (
            f"UPDATE {self.schema_name}.{self.table_config.table_name} "
            "SET deleted_at = now(), "
            "status = 'DELETED', "
            "lifecycle_state = 'DELETED', "
            "updated_at = now() "
            "WHERE project_id = %s "
            "AND deleted_at IS NULL "
            f"AND {self.table_config.business_id_column} <> ALL(%s::text[])"
        )

    def _soft_delete_missing_rows_params(
        self,
        project_uuid: str,
        business_ids: list[str],
    ) -> tuple[Any, ...]:
        return (project_uuid, business_ids)

    def _business_ids(self, records: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        for record in records:
            record_id = str(record.get(self.table_config.id_field) or "").strip()
            if not record_id:
                raise StorageError(
                    f"Normalized write_all requires {self.table_config.id_field} on every record."
                )
            ids.append(record_id)
        return ids

    def _to_jsonb(self, value: Any) -> Any:
        adapter = self._jsonb_adapter or self.connection_factory.jsonb_adapter()
        return adapter(value)

    def _raise_repository_error(self, action: str, exc: Exception) -> None:
        raise StorageError(
            f"Normalized PostgreSQL repository failed to {action} "
            f"{self.table_config.table_name}: {type(exc).__name__}; "
            f"database={self.safe_database_url}"
        ) from exc


class PostgresCharacterRepository(PostgresNormalizedListRepository):
    def __init__(
        self,
        *,
        connection_factory: PostgresConnectionFactory,
        data_dir: Path,
        jsonb_adapter: Callable[[Any], Any] | None = None,
    ) -> None:
        super().__init__(
            connection_factory=connection_factory,
            data_dir=data_dir,
            table_config=NormalizedListTableConfig(
                table_name="characters",
                id_field="character_id",
                business_id_column="character_id",
                select_columns=(
                    "character_id",
                    "display_name",
                    "role_tier",
                    "short_description",
                    "status",
                    "legacy_status_raw",
                    "lifecycle_state",
                    "authority_level",
                    "version",
                    "revision",
                    "source_type",
                    "source_id",
                    "source_refs",
                    "content_hash",
                    "metadata",
                ),
                order_by="character_id",
            ),
            jsonb_adapter=jsonb_adapter,
        )

    def _record_to_values(
        self,
        conn: Any,
        project_uuid: str,
        project_business_id: str,
        record: dict[str, Any],
        id_field: str | None,
    ) -> tuple[Any, ...]:
        field = id_field or self.table_config.id_field
        character_id = str(record.get(field) or record.get("character_id") or "").strip()
        if not character_id:
            raise StorageError("Character repository upsert requires character_id.")
        metadata = _metadata_with_payload(record)
        return (
            project_uuid,
            character_id,
            str(record.get("schema_version") or "phase9_m2"),
            _display_name(record, character_id),
            _role_tier(record),
            _short_description(record),
            _canonical_status(record),
            _legacy_status_raw(record),
            _lifecycle_state(record),
            _authority_level(record),
            _positive_int(record.get("version"), 1),
            _positive_int(record.get("revision"), 1),
            str(record.get("idempotency_key") or ""),
            str(record.get("source_type") or "RUNTIME"),
            str(record.get("source_id") or ""),
            self._to_jsonb(_source_refs(record)),
            _content_hash(record),
            self._to_jsonb(metadata),
        )

    def _row_to_record(
        self,
        row: tuple[Any, ...],
        project_business_id: str,
    ) -> dict[str, Any]:
        (
            character_id,
            display_name,
            role_tier,
            short_description,
            status,
            legacy_status_raw,
            lifecycle_state,
            authority_level,
            version,
            revision,
            source_type,
            source_id,
            source_refs,
            content_hash,
            metadata,
        ) = row
        metadata_dict = _json_value(metadata, {})
        payload = metadata_dict.get(_M2_RECORD_PAYLOAD_KEY)
        record = dict(payload) if isinstance(payload, dict) else {}
        record["project_id"] = str(record.get("project_id") or project_business_id)
        record["character_id"] = str(character_id)
        if "name" in record or "display_name" not in record:
            record["name"] = str(display_name or "")
        else:
            record["display_name"] = str(display_name or "")
        if "tier" in record or "role_tier" not in record:
            record["tier"] = str(role_tier or "")
        else:
            record["role_tier"] = str(role_tier or "")
        if short_description and not _short_description(record):
            profile = record.get("profile")
            if isinstance(profile, dict):
                profile["description"] = str(short_description)
            else:
                record["short_description"] = str(short_description)
        record["status"] = str(legacy_status_raw or status or "")
        record["lifecycle_state"] = str(lifecycle_state or "")
        record["authority_level"] = str(authority_level or "")
        record["version"] = int(version or 1)
        record["revision"] = int(revision or 1)
        record["source_type"] = str(source_type or "")
        record["source_id"] = str(source_id or "")
        record["source_refs"] = _json_value(source_refs, [])
        record["content_hash"] = str(content_hash or "")
        return record

    def _upsert_sql(self) -> str:
        return f"""
        INSERT INTO {self.schema_name}.characters (
          project_id,
          character_id,
          schema_version,
          display_name,
          role_tier,
          short_description,
          status,
          legacy_status_raw,
          lifecycle_state,
          authority_level,
          version,
          revision,
          idempotency_key,
          source_type,
          source_id,
          source_refs,
          content_hash,
          metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, ''), %s, %s, %s, %s, %s)
        ON CONFLICT (project_id, character_id) DO UPDATE SET
          schema_version = EXCLUDED.schema_version,
          display_name = EXCLUDED.display_name,
          role_tier = EXCLUDED.role_tier,
          short_description = EXCLUDED.short_description,
          status = EXCLUDED.status,
          legacy_status_raw = EXCLUDED.legacy_status_raw,
          lifecycle_state = EXCLUDED.lifecycle_state,
          authority_level = EXCLUDED.authority_level,
          version = EXCLUDED.version,
          revision = EXCLUDED.revision,
          idempotency_key = EXCLUDED.idempotency_key,
          source_type = EXCLUDED.source_type,
          source_id = EXCLUDED.source_id,
          source_refs = EXCLUDED.source_refs,
          content_hash = EXCLUDED.content_hash,
          metadata = EXCLUDED.metadata,
          updated_at = now(),
          deleted_at = NULL
        """


class PostgresPayloadListRepository(PostgresNormalizedListRepository):
    _COMMON_SELECT_COLUMNS = (
        "status",
        "legacy_status_raw",
        "lifecycle_state",
        "authority_level",
        "version",
        "revision",
        "source_type",
        "source_id",
        "source_refs",
        "content_hash",
        "metadata",
    )

    _COMMON_INSERT_COLUMNS = (
        "schema_version",
        "status",
        "legacy_status_raw",
        "lifecycle_state",
        "authority_level",
        "version",
        "revision",
        "idempotency_key",
        "source_type",
        "source_id",
        "source_refs",
        "content_hash",
        "metadata",
    )

    def __init__(
        self,
        *,
        connection_factory: PostgresConnectionFactory,
        data_dir: Path,
        repository_spec: NormalizedPayloadRepositorySpec,
        jsonb_adapter: Callable[[Any], Any] | None = None,
    ) -> None:
        _assert_safe_identifier(repository_spec.table_name, "table")
        _assert_safe_identifier(repository_spec.business_id_column, "business id column")
        for extra in repository_spec.extra_columns:
            _assert_safe_identifier(extra.column_name, "extra column")
        for column in repository_spec.active_null_columns:
            _assert_safe_identifier(column, "active filter column")
        for foreign_key in repository_spec.foreign_keys:
            _assert_safe_identifier(foreign_key.column_name, "foreign key column")
            _assert_safe_identifier(foreign_key.target_table, "foreign key target table")
            _assert_safe_identifier(
                foreign_key.target_business_id_column,
                "foreign key target business id column",
            )
        self.repository_spec = repository_spec
        self._foreign_key_columns = {
            foreign_key.column_name: foreign_key
            for foreign_key in repository_spec.foreign_keys
        }
        super().__init__(
            connection_factory=connection_factory,
            data_dir=data_dir,
            table_config=NormalizedListTableConfig(
                table_name=repository_spec.table_name,
                id_field=repository_spec.id_field,
                business_id_column=repository_spec.business_id_column,
                select_columns=(
                    repository_spec.business_id_column,
                    *self._COMMON_SELECT_COLUMNS,
                ),
                order_by=repository_spec.order_by or repository_spec.business_id_column,
            ),
            jsonb_adapter=jsonb_adapter,
        )

    def _select_all_sql(self) -> str:
        columns = ", ".join(self.table_config.select_columns)
        return (
            f"SELECT {columns} FROM {self.schema_name}.{self.table_config.table_name} "
            f"WHERE project_id = %s AND deleted_at IS NULL"
            f"{self._active_null_filter_sql()} "
            f"ORDER BY {self.table_config.order_by}"
        )

    def _select_one_sql(self) -> str:
        columns = ", ".join(self.table_config.select_columns)
        return (
            f"SELECT {columns} FROM {self.schema_name}.{self.table_config.table_name} "
            f"WHERE project_id = %s "
            f"AND {self.table_config.business_id_column} = %s "
            f"AND deleted_at IS NULL"
            f"{self._active_null_filter_sql()}"
        )

    def _active_null_filter_sql(self) -> str:
        if not self.repository_spec.active_null_columns:
            return " "
        return "".join(f" AND {column} IS NULL" for column in self.repository_spec.active_null_columns) + " "

    def _record_to_values(
        self,
        conn: Any,
        project_uuid: str,
        project_business_id: str,
        record: dict[str, Any],
        id_field: str | None,
    ) -> tuple[Any, ...]:
        business_id = _business_id(
            record,
            id_field or self.table_config.id_field,
            self.table_config.business_id_column,
        )
        if not business_id:
            raise StorageError(
                f"{self.repository_spec.repository_name} upsert requires "
                f"{self.table_config.id_field}."
            )
        common_values: tuple[Any, ...] = (
            str(record.get("schema_version") or "phase9_m2"),
            _canonical_status(record),
            _legacy_status_raw(record),
            _lifecycle_state(record),
            _authority_level(record),
            _positive_int(record.get("version"), 1),
            _positive_int(record.get("revision"), 1),
            str(record.get("idempotency_key") or "") or None,
            str(record.get("source_type") or "RUNTIME"),
            str(record.get("source_id") or ""),
            self._to_jsonb(_source_refs(record)),
            _content_hash(record),
            self._to_jsonb(_metadata_with_payload(record)),
        )
        extra_values = tuple(
            self._record_extra_value(conn, project_uuid, record, extra)
            for extra in self.repository_spec.extra_columns
        )
        return (project_uuid, business_id, *common_values, *extra_values)

    def _record_extra_value(
        self,
        conn: Any,
        project_uuid: str,
        record: dict[str, Any],
        extra: NormalizedExtraColumn,
    ) -> Any:
        value = extra.value_getter(record)
        foreign_key = self._foreign_key_columns.get(extra.column_name)
        if foreign_key is not None:
            value = self._resolve_foreign_key_value(conn, project_uuid, foreign_key, value)
        return self._normalize_extra_value(value)

    def _resolve_foreign_key_value(
        self,
        conn: Any,
        project_uuid: str,
        foreign_key: NormalizedForeignKeyColumn,
        raw_value: Any,
    ) -> str | None:
        reference_value = str(raw_value or "").strip()
        if not reference_value:
            if foreign_key.required:
                raise StorageError(
                    f"{self.repository_spec.repository_name} requires "
                    f"{foreign_key.column_name} before PostgreSQL upsert."
                )
            return None

        if _UUID_TEXT.fullmatch(reference_value):
            internal_id = self._lookup_foreign_key_id(
                conn,
                project_uuid,
                foreign_key.target_table,
                "id",
                reference_value,
            )
            if internal_id is not None:
                return internal_id

        internal_id = self._lookup_foreign_key_id(
            conn,
            project_uuid,
            foreign_key.target_table,
            foreign_key.target_business_id_column,
            reference_value,
        )
        if internal_id is not None:
            return internal_id

        raise StorageError(
            f"{self.repository_spec.repository_name} could not resolve "
            f"{foreign_key.column_name} reference in {foreign_key.target_table} "
            "for the current project."
        )

    def _lookup_foreign_key_id(
        self,
        conn: Any,
        project_uuid: str,
        target_table: str,
        lookup_column: str,
        lookup_value: str,
    ) -> str | None:
        row = conn.execute(
            f"""
            SELECT id FROM {self.schema_name}.{target_table}
            WHERE project_id = %s
            AND {lookup_column} = %s
            AND deleted_at IS NULL
            """,
            (project_uuid, lookup_value),
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def _row_to_record(
        self,
        row: tuple[Any, ...],
        project_business_id: str,
    ) -> dict[str, Any]:
        (
            business_id,
            status,
            legacy_status_raw,
            lifecycle_state,
            authority_level,
            version,
            revision,
            source_type,
            source_id,
            source_refs,
            content_hash,
            metadata,
        ) = row
        metadata_dict = _json_value(metadata, {})
        payload = metadata_dict.get(_M2_RECORD_PAYLOAD_KEY)
        record = dict(payload) if isinstance(payload, dict) else {}
        record["project_id"] = str(record.get("project_id") or project_business_id)
        record[self.table_config.id_field] = str(business_id)
        if self.table_config.business_id_column != self.table_config.id_field:
            record[self.table_config.business_id_column] = str(business_id)
        record["status"] = str(legacy_status_raw or status or "")
        record["lifecycle_state"] = str(lifecycle_state or "")
        record["authority_level"] = str(authority_level or "")
        record["version"] = int(version or 1)
        record["revision"] = int(revision or 1)
        record["source_type"] = str(source_type or "")
        record["source_id"] = str(source_id or "")
        record["source_refs"] = _json_value(source_refs, [])
        record["content_hash"] = str(content_hash or "")
        return record

    def _upsert_sql(self) -> str:
        insert_columns = (
            "project_id",
            self.table_config.business_id_column,
            *self._COMMON_INSERT_COLUMNS,
            *(extra.column_name for extra in self.repository_spec.extra_columns),
        )
        placeholders = ", ".join(["%s"] * len(insert_columns))
        update_columns = (
            *self._COMMON_INSERT_COLUMNS,
            *(extra.column_name for extra in self.repository_spec.extra_columns),
        )
        update_assignments = ",\n          ".join(
            f"{column} = EXCLUDED.{column}" for column in update_columns
        )
        return f"""
        INSERT INTO {self.schema_name}.{self.table_config.table_name} (
          {", ".join(insert_columns)}
        )
        VALUES ({placeholders})
        ON CONFLICT (project_id, {self.table_config.business_id_column}) DO UPDATE SET
          {update_assignments},
          updated_at = now(),
          deleted_at = NULL
        """

    def _normalize_extra_value(self, value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return self._to_jsonb(value)
        return value


class PostgresMemoryPackRepository(PostgresPayloadListRepository):
    def __init__(
        self,
        *,
        connection_factory: PostgresConnectionFactory,
        data_dir: Path,
        id_field: str,
        pack_type: str,
        root_name: str,
        jsonb_adapter: Callable[[Any], Any] | None = None,
    ) -> None:
        self.pack_type = pack_type
        self.root_name = root_name
        super().__init__(
            connection_factory=connection_factory,
            data_dir=data_dir,
            repository_spec=NormalizedPayloadRepositorySpec(
                repository_name=root_name,
                table_name="memory_packs",
                id_field=id_field,
                business_id_column="memory_pack_id",
                extra_columns=(
                    NormalizedExtraColumn("pack_type", lambda _record: pack_type),
                    NormalizedExtraColumn("pack_scope", lambda record: _text(record, "pack_scope", "scope")),
                    NormalizedExtraColumn("freshness_status", lambda record: _text(record, "freshness_status", "freshness", default="FRESH")),
                    NormalizedExtraColumn("built_from_hash", lambda record: _text(record, "built_from_hash")),
                ),
            ),
            jsonb_adapter=jsonb_adapter,
        )

    def read_envelope(self) -> dict[str, Any]:
        return {
            "schema_version": "phase9_m2",
            "packs": self.list_packs(),
            "updated_at": "",
        }

    def write_envelope(self, envelope: dict[str, Any]) -> None:
        packs = envelope.get("packs", [])
        if not isinstance(packs, list):
            raise StorageError(f"{self.root_name} must contain a packs list.")
        self.write_all([dict(item) for item in packs if isinstance(item, dict)])

    def list_packs(self) -> list[dict[str, Any]]:
        return self.list_all()

    def _select_all_sql(self) -> str:
        columns = ", ".join(self.table_config.select_columns)
        return (
            f"SELECT {columns} FROM {self.schema_name}.{self.table_config.table_name} "
            "WHERE project_id = %s AND pack_type = %s AND deleted_at IS NULL "
            f"ORDER BY {self.table_config.order_by}"
        )

    def _select_one_sql(self) -> str:
        columns = ", ".join(self.table_config.select_columns)
        return (
            f"SELECT {columns} FROM {self.schema_name}.{self.table_config.table_name} "
            "WHERE project_id = %s "
            f"AND {self.table_config.business_id_column} = %s "
            "AND pack_type = %s "
            "AND deleted_at IS NULL"
        )

    def _select_all_params(self, project_uuid: str) -> tuple[Any, ...]:
        return (project_uuid, self.pack_type)

    def _select_one_params(self, project_uuid: str, record_id: str) -> tuple[Any, ...]:
        return (project_uuid, record_id, self.pack_type)

    def _soft_delete_missing_rows_sql(self) -> str:
        return (
            f"UPDATE {self.schema_name}.{self.table_config.table_name} "
            "SET deleted_at = now(), "
            "status = 'DELETED', "
            "lifecycle_state = 'DELETED', "
            "updated_at = now() "
            "WHERE project_id = %s "
            "AND pack_type = %s "
            "AND deleted_at IS NULL "
            f"AND {self.table_config.business_id_column} <> ALL(%s::text[])"
        )

    def _soft_delete_missing_rows_params(
        self,
        project_uuid: str,
        business_ids: list[str],
    ) -> tuple[Any, ...]:
        return (project_uuid, self.pack_type, business_ids)


def create_postgres_normalized_repository(
    *,
    repository_name: str,
    connection_factory: PostgresConnectionFactory,
    data_dir: Path,
    jsonb_adapter: Callable[[Any], Any] | None = None,
) -> Any:
    if repository_name == "characters":
        return PostgresCharacterRepository(
            connection_factory=connection_factory,
            data_dir=data_dir,
            jsonb_adapter=jsonb_adapter,
        )
    if repository_name == "chapter_memory_packs":
        return PostgresMemoryPackRepository(
            connection_factory=connection_factory,
            data_dir=data_dir,
            id_field="chapter_memory_pack_id",
            pack_type="CHAPTER",
            root_name="chapter_memory_packs.json",
            jsonb_adapter=jsonb_adapter,
        )
    if repository_name == "scene_memory_packs":
        return PostgresMemoryPackRepository(
            connection_factory=connection_factory,
            data_dir=data_dir,
            id_field="scene_memory_pack_id",
            pack_type="SCENE",
            root_name="scene_memory_packs.json",
            jsonb_adapter=jsonb_adapter,
        )
    spec = POSTGRES_PAYLOAD_REPOSITORY_SPECS.get(repository_name)
    if spec is None:
        raise StorageError(f"No normalized PostgreSQL repository is registered for {repository_name}.")
    return PostgresPayloadListRepository(
        connection_factory=connection_factory,
        data_dir=data_dir,
        repository_spec=spec,
        jsonb_adapter=jsonb_adapter,
    )


POSTGRES_PAYLOAD_REPOSITORY_SPECS: dict[str, NormalizedPayloadRepositorySpec] = {
    "story_bibles": NormalizedPayloadRepositorySpec(
        repository_name="story_bibles",
        table_name="story_bibles",
        id_field="story_bible_id",
        business_id_column="bible_id",
        extra_columns=(
            NormalizedExtraColumn(
                "title",
                lambda record: _text(record, "title", "name", default="Story Bible"),
            ),
            NormalizedExtraColumn(
                "bible_payload",
                lambda record: _json_payload(record, "bible_payload", default=record),
            ),
        ),
    ),
    "world_canvases": NormalizedPayloadRepositorySpec(
        repository_name="world_canvases",
        table_name="world_canvases",
        id_field="world_canvas_id",
        business_id_column="canvas_id",
        extra_columns=(
            NormalizedExtraColumn(
                "canvas_name",
                lambda record: _text(record, "canvas_name", "name", "title", default="World Canvas"),
            ),
            NormalizedExtraColumn(
                "canvas_payload",
                lambda record: _json_payload(record, "canvas_payload", default=record),
            ),
        ),
    ),
    "framework_packages": NormalizedPayloadRepositorySpec(
        repository_name="framework_packages",
        table_name="framework_packages",
        id_field="framework_package_id",
        business_id_column="framework_package_id",
        extra_columns=(
            NormalizedExtraColumn(
                "package_name",
                lambda record: _text(record, "package_name", "name", default="Framework Package"),
            ),
            NormalizedExtraColumn(
                "package_payload",
                lambda record: _json_payload(record, "package_payload", default=record),
            ),
        ),
    ),
    "timelines": NormalizedPayloadRepositorySpec(
        repository_name="timelines",
        table_name="timelines",
        id_field="timeline_id",
        business_id_column="timeline_id",
        extra_columns=(
            NormalizedExtraColumn("timeline_type", lambda record: _text(record, "timeline_type", default="MAIN")),
            NormalizedExtraColumn("branch_point_ref", lambda record: _json_payload(record, "branch_point_ref", default={})),
            NormalizedExtraColumn("timeline_summary", lambda record: _text(record, "timeline_summary", "summary")),
            NormalizedExtraColumn("calendar_system_ref", lambda record: _text(record, "calendar_system_ref")),
            NormalizedExtraColumn("created_from_source_ref", lambda record: _json_payload(record, "created_from_source_ref", default={})),
        ),
    ),
    "character_memory_nodes": NormalizedPayloadRepositorySpec(
        repository_name="character_memory_nodes",
        table_name="character_memory_nodes",
        id_field="character_memory_node_id",
        business_id_column="character_memory_node_id",
        extra_columns=(
            NormalizedExtraColumn("character_id", lambda record: _nullable_text(record, "character_id", "character_uuid")),
            NormalizedExtraColumn("timeline_id", lambda record: _nullable_text(record, "timeline_id", "timeline_uuid")),
            NormalizedExtraColumn("source_scene_id", lambda record: _nullable_text(record, "source_scene_id", "scene_uuid")),
            NormalizedExtraColumn("source_event_id", lambda record: _nullable_text(record, "source_event_id", "event_uuid")),
            NormalizedExtraColumn("previous_node_id", lambda record: _nullable_text(record, "previous_node_id")),
            NormalizedExtraColumn("superseded_by_id", lambda record: _nullable_text(record, "superseded_by_id")),
            NormalizedExtraColumn("experienced_at", lambda record: _text(record, "experienced_at")),
            NormalizedExtraColumn("experienced_at_sort_key", lambda record: _integer(record, "experienced_at_sort_key", default=0)),
            NormalizedExtraColumn("known_at", lambda record: _text(record, "known_at")),
            NormalizedExtraColumn("known_at_sort_key", lambda record: _integer(record, "known_at_sort_key", default=0)),
            NormalizedExtraColumn("narrative_recorded_at", lambda record: _text(record, "narrative_recorded_at")),
            NormalizedExtraColumn("narrative_recorded_at_sort_key", lambda record: _integer(record, "narrative_recorded_at_sort_key", default=0)),
            NormalizedExtraColumn("valid_from", lambda record: _text(record, "valid_from")),
            NormalizedExtraColumn("valid_from_sort_key", lambda record: _integer(record, "valid_from_sort_key", default=0)),
            NormalizedExtraColumn("valid_to", lambda record: _text(record, "valid_to")),
            NormalizedExtraColumn("valid_to_sort_key", lambda record: _nullable_int(record, "valid_to_sort_key")),
            NormalizedExtraColumn("memory_type", lambda record: _text(record, "memory_type", default="OBJECTIVE_SEEN")),
            NormalizedExtraColumn("visibility_status", lambda record: _text(record, "visibility_status", default="KNOWN")),
            NormalizedExtraColumn("content", lambda record: _text(record, "content", "memory_text", "text")),
            NormalizedExtraColumn("summary", lambda record: _text(record, "summary")),
        ),
        foreign_keys=(
            NormalizedForeignKeyColumn("character_id", "characters", "character_id", required=True),
            NormalizedForeignKeyColumn("timeline_id", "timelines", "timeline_id", required=True),
            NormalizedForeignKeyColumn("source_scene_id", "scenes", "scene_id"),
            NormalizedForeignKeyColumn("source_event_id", "events", "event_id"),
            NormalizedForeignKeyColumn(
                "previous_node_id",
                "character_memory_nodes",
                "character_memory_node_id",
            ),
            NormalizedForeignKeyColumn(
                "superseded_by_id",
                "character_memory_nodes",
                "character_memory_node_id",
            ),
        ),
        active_null_columns=("superseded_by_id",),
    ),
    "location_state_nodes": NormalizedPayloadRepositorySpec(
        repository_name="location_state_nodes",
        table_name="location_state_nodes",
        id_field="location_state_node_id",
        business_id_column="location_state_node_id",
        extra_columns=(
            NormalizedExtraColumn("location_id", lambda record: _nullable_text(record, "location_id", "location_uuid")),
            NormalizedExtraColumn("timeline_id", lambda record: _nullable_text(record, "timeline_id", "timeline_uuid")),
            NormalizedExtraColumn("previous_node_id", lambda record: _nullable_text(record, "previous_node_id")),
            NormalizedExtraColumn("next_node_id", lambda record: _nullable_text(record, "next_node_id")),
            NormalizedExtraColumn("change_from_previous_id", lambda record: _nullable_text(record, "change_from_previous_id")),
            NormalizedExtraColumn("superseded_by_id", lambda record: _nullable_text(record, "superseded_by_id")),
            NormalizedExtraColumn("time_anchor", lambda record: _text(record, "time_anchor")),
            NormalizedExtraColumn("time_anchor_sort_key", lambda record: _integer(record, "time_anchor_sort_key", default=0)),
            NormalizedExtraColumn("valid_from", lambda record: _text(record, "valid_from")),
            NormalizedExtraColumn("valid_from_sort_key", lambda record: _integer(record, "valid_from_sort_key", default=0)),
            NormalizedExtraColumn("valid_to", lambda record: _text(record, "valid_to")),
            NormalizedExtraColumn("valid_to_sort_key", lambda record: _nullable_int(record, "valid_to_sort_key")),
            NormalizedExtraColumn("state_snapshot", lambda record: _json_payload(record, "state_snapshot", default={})),
            NormalizedExtraColumn("known_by_character_refs", lambda record: _json_payload(record, "known_by_character_refs", default=[])),
            NormalizedExtraColumn("revealed_to_reader_at", lambda record: _text(record, "revealed_to_reader_at")),
            NormalizedExtraColumn("revealed_to_reader_at_sort_key", lambda record: _nullable_int(record, "revealed_to_reader_at_sort_key")),
            NormalizedExtraColumn("visibility_status", lambda record: _text(record, "visibility_status", default="KNOWN")),
        ),
        foreign_keys=(
            NormalizedForeignKeyColumn("location_id", "world_locations", "location_id", required=True),
            NormalizedForeignKeyColumn("timeline_id", "timelines", "timeline_id", required=True),
            NormalizedForeignKeyColumn("previous_node_id", "location_state_nodes", "location_state_node_id"),
            NormalizedForeignKeyColumn("next_node_id", "location_state_nodes", "location_state_node_id"),
            NormalizedForeignKeyColumn(
                "change_from_previous_id",
                "location_change_deltas",
                "location_change_delta_id",
            ),
            NormalizedForeignKeyColumn("superseded_by_id", "location_state_nodes", "location_state_node_id"),
        ),
        active_null_columns=("superseded_by_id",),
    ),
    "location_change_deltas": NormalizedPayloadRepositorySpec(
        repository_name="location_change_deltas",
        table_name="location_change_deltas",
        id_field="location_change_delta_id",
        business_id_column="location_change_delta_id",
        extra_columns=(
            NormalizedExtraColumn("location_id", lambda record: _nullable_text(record, "location_id", "location_uuid")),
            NormalizedExtraColumn("from_node_id", lambda record: _nullable_text(record, "from_node_id")),
            NormalizedExtraColumn("to_node_id", lambda record: _nullable_text(record, "to_node_id")),
            NormalizedExtraColumn("source_event_id", lambda record: _nullable_text(record, "source_event_id", "event_uuid")),
            NormalizedExtraColumn("superseded_by_id", lambda record: _nullable_text(record, "superseded_by_id")),
            NormalizedExtraColumn("change_summary", lambda record: _text(record, "change_summary", "summary")),
            NormalizedExtraColumn("change_detail", lambda record: _text(record, "change_detail", "detail")),
            NormalizedExtraColumn("caused_by_event_refs", lambda record: _json_payload(record, "caused_by_event_refs", default=[])),
            NormalizedExtraColumn("participant_refs", lambda record: _json_payload(record, "participant_refs", default=[])),
            NormalizedExtraColumn("known_by_character_refs", lambda record: _json_payload(record, "known_by_character_refs", default=[])),
            NormalizedExtraColumn("revealed_to_reader_at", lambda record: _text(record, "revealed_to_reader_at")),
            NormalizedExtraColumn("revealed_to_reader_at_sort_key", lambda record: _nullable_int(record, "revealed_to_reader_at_sort_key")),
            NormalizedExtraColumn("visibility_status", lambda record: _text(record, "visibility_status", default="KNOWN")),
        ),
        foreign_keys=(
            NormalizedForeignKeyColumn("location_id", "world_locations", "location_id", required=True),
            NormalizedForeignKeyColumn("from_node_id", "location_state_nodes", "location_state_node_id"),
            NormalizedForeignKeyColumn("to_node_id", "location_state_nodes", "location_state_node_id"),
            NormalizedForeignKeyColumn("source_event_id", "events", "event_id"),
            NormalizedForeignKeyColumn(
                "superseded_by_id",
                "location_change_deltas",
                "location_change_delta_id",
            ),
        ),
        active_null_columns=("superseded_by_id",),
    ),
    "memory": NormalizedPayloadRepositorySpec(
        repository_name="memory",
        table_name="memory_records",
        id_field="memory_id",
        business_id_column="memory_id",
        extra_columns=(
            NormalizedExtraColumn("memory_lane", lambda record: _text(record, "memory_lane", "lane", default="OBJECTIVE")),
            NormalizedExtraColumn("memory_type", lambda record: _text(record, "memory_type", "type")),
            NormalizedExtraColumn("subject_entity_type", lambda record: _text(record, "subject_entity_type", "entity_type")),
            NormalizedExtraColumn("subject_business_id", lambda record: _text(record, "subject_business_id", "entity_id", "character_id")),
            NormalizedExtraColumn("memory_text", lambda record: _text(record, "memory_text", "text", "summary", "content")),
            NormalizedExtraColumn("visibility_scope", lambda record: _text(record, "visibility_scope", "visibility")),
            NormalizedExtraColumn("valid_from_chapter_id", lambda record: _text(record, "valid_from_chapter_id", "chapter_id")),
            NormalizedExtraColumn("valid_from_scene_id", lambda record: _text(record, "valid_from_scene_id", "scene_id")),
        ),
    ),
    "scenes": NormalizedPayloadRepositorySpec(
        repository_name="scenes",
        table_name="scenes",
        id_field="scene_id",
        business_id_column="scene_id",
        extra_columns=(
            NormalizedExtraColumn("scene_order", lambda record: _integer(record, "scene_order", "order", default=0)),
            NormalizedExtraColumn("scene_title", lambda record: _text(record, "scene_title", "title")),
            NormalizedExtraColumn("scene_summary", lambda record: _text(record, "scene_summary", "summary")),
            NormalizedExtraColumn("scene_purpose", lambda record: _text(record, "scene_purpose", "purpose")),
        ),
    ),
    "events": NormalizedPayloadRepositorySpec(
        repository_name="events",
        table_name="events",
        id_field="event_id",
        business_id_column="event_id",
        extra_columns=(
            NormalizedExtraColumn("event_type", lambda record: _text(record, "event_type", "type")),
            NormalizedExtraColumn("event_summary", lambda record: _text(record, "event_summary", "summary", "description")),
            NormalizedExtraColumn("event_order", lambda record: _integer(record, "event_order", "order", default=0)),
        ),
    ),
    "state_changes": NormalizedPayloadRepositorySpec(
        repository_name="state_changes",
        table_name="state_changes",
        id_field="state_change_id",
        business_id_column="state_change_id",
        extra_columns=(
            NormalizedExtraColumn("target_entity_type", lambda record: _text(record, "target_entity_type", "entity_type")),
            NormalizedExtraColumn("target_business_id", lambda record: _text(record, "target_business_id", "entity_id", "character_id")),
            NormalizedExtraColumn("change_payload", lambda record: _json_payload(record, "change_payload", "changes", "payload")),
        ),
    ),
    "relationships": NormalizedPayloadRepositorySpec(
        repository_name="relationships",
        table_name="relationships",
        id_field="relationship_id",
        business_id_column="relationship_id",
        extra_columns=(
            NormalizedExtraColumn("relationship_type", lambda record: _text(record, "relationship_type", "type")),
            NormalizedExtraColumn("relationship_summary", lambda record: _text(record, "relationship_summary", "summary", "description")),
        ),
    ),
    "decisions": NormalizedPayloadRepositorySpec(
        repository_name="decisions",
        table_name="decisions",
        id_field="decision_id",
        business_id_column="decision_id",
        extra_columns=(
            NormalizedExtraColumn("decision_type", lambda record: _text(record, "decision_type", "type")),
            NormalizedExtraColumn("decision_text", lambda record: _text(record, "decision_text", "text", "summary")),
            NormalizedExtraColumn("rationale", lambda record: _text(record, "rationale", "reason")),
            NormalizedExtraColumn("target_entity_ref", lambda record: _json_payload(record, "target_entity_ref", "target_ref")),
        ),
    ),
    "quality_reports": NormalizedPayloadRepositorySpec(
        repository_name="quality_reports",
        table_name="quality_reports",
        id_field="quality_report_id",
        business_id_column="quality_report_id",
        extra_columns=(
            NormalizedExtraColumn("report_type", lambda record: _text(record, "report_type", "type")),
            NormalizedExtraColumn("report_result", lambda record: _text(record, "report_result", "result", default="PENDING")),
            NormalizedExtraColumn("summary", lambda record: _text(record, "summary", "report_summary")),
        ),
    ),
    "continuity_issues": NormalizedPayloadRepositorySpec(
        repository_name="continuity_issues",
        table_name="continuity_issues",
        id_field="issue_id",
        business_id_column="continuity_issue_id",
        extra_columns=(
            NormalizedExtraColumn("issue_type", lambda record: _text(record, "issue_type", "type")),
            NormalizedExtraColumn("severity", lambda record: _text(record, "severity")),
            NormalizedExtraColumn("issue_text", lambda record: _text(record, "issue_text", "text", "summary")),
            NormalizedExtraColumn("target_entity_ref", lambda record: _json_payload(record, "target_entity_ref", "target_ref")),
        ),
    ),
    "prior_story_completion_candidates": NormalizedPayloadRepositorySpec(
        repository_name="prior_story_completion_candidates",
        table_name="prior_story_completion_candidates",
        id_field="candidate_id",
        business_id_column="candidate_id",
        extra_columns=(
            NormalizedExtraColumn("candidate_type", lambda record: _text(record, "candidate_type", "type")),
            NormalizedExtraColumn("candidate_text", lambda record: _text(record, "candidate_text", "text", "summary")),
            NormalizedExtraColumn("target_issue_id", lambda record: _text(record, "target_issue_id", "issue_id", "continuity_issue_id")),
            NormalizedExtraColumn("candidate_payload", lambda record: _json_payload(record, "candidate_payload", "payload")),
        ),
    ),
    "chapters": NormalizedPayloadRepositorySpec(
        repository_name="chapters",
        table_name="chapters",
        id_field="chapter_id",
        business_id_column="chapter_id",
        extra_columns=(
            NormalizedExtraColumn("chapter_number", lambda record: _integer(record, "chapter_number", "number", default=0)),
            NormalizedExtraColumn("title", lambda record: _text(record, "title", "chapter_title")),
            NormalizedExtraColumn("chapter_summary", lambda record: _text(record, "chapter_summary", "summary")),
        ),
    ),
    "pending_character_state_changes": NormalizedPayloadRepositorySpec(
        repository_name="pending_character_state_changes",
        table_name="pending_character_state_changes",
        id_field="change_id",
        business_id_column="pending_change_id",
        extra_columns=(
            NormalizedExtraColumn("change_payload", lambda record: _json_payload(record, "change_payload", "payload", "changes")),
        ),
    ),
    "memory_update_plans": NormalizedPayloadRepositorySpec(
        repository_name="memory_update_plans",
        table_name="memory_update_plans",
        id_field="memory_update_plan_id",
        business_id_column="memory_update_plan_id",
        extra_columns=(
            NormalizedExtraColumn("plan_type", lambda record: _text(record, "plan_type", "type")),
            NormalizedExtraColumn("affected_entity_refs", lambda record: _json_payload(record, "affected_entity_refs", default=[])),
            NormalizedExtraColumn("planned_changes", lambda record: _json_payload(record, "planned_changes", "changes", default=[])),
        ),
    ),
    "claim_records": NormalizedPayloadRepositorySpec(
        repository_name="claim_records",
        table_name="claim_records",
        id_field="claim_id",
        business_id_column="claim_id",
        extra_columns=(
            NormalizedExtraColumn("speaker_entity_type", lambda record: _text(record, "speaker_entity_type")),
            NormalizedExtraColumn("speaker_business_id", lambda record: _text(record, "speaker_business_id", "speaker_id")),
            NormalizedExtraColumn("claim_text", lambda record: _text(record, "claim_text", "text")),
            NormalizedExtraColumn("truth_status", lambda record: _text(record, "truth_status", default="UNKNOWN")),
            NormalizedExtraColumn("claim_scope", lambda record: _text(record, "claim_scope", "scope")),
            NormalizedExtraColumn("certainty_label", lambda record: _text(record, "certainty_label", "certainty")),
        ),
    ),
    "narrative_intent_records": NormalizedPayloadRepositorySpec(
        repository_name="narrative_intent_records",
        table_name="narrative_intents",
        id_field="narrative_intent_id",
        business_id_column="intent_id",
        extra_columns=(
            NormalizedExtraColumn("target_ref", lambda record: _json_payload(record, "target_ref", "target_entity_ref")),
            NormalizedExtraColumn("intent_type", lambda record: _text(record, "intent_type", "type")),
            NormalizedExtraColumn("description", lambda record: _text(record, "description", "summary", "text")),
        ),
    ),
    "character_psychology_traces": NormalizedPayloadRepositorySpec(
        repository_name="character_psychology_traces",
        table_name="character_psychology_traces",
        id_field="psychology_trace_id",
        business_id_column="trace_id",
        extra_columns=(
            NormalizedExtraColumn("character_business_id", lambda record: _text(record, "character_business_id", "character_id")),
            NormalizedExtraColumn("internal_state", lambda record: _text(record, "internal_state", "state")),
            NormalizedExtraColumn("visibility", lambda record: _text(record, "visibility")),
            NormalizedExtraColumn("trace_payload", lambda record: _json_payload(record, "trace_payload", "payload")),
        ),
    ),
    "character_expression_records": NormalizedPayloadRepositorySpec(
        repository_name="character_expression_records",
        table_name="character_expression_records",
        id_field="expression_record_id",
        business_id_column="expression_id",
        extra_columns=(
            NormalizedExtraColumn("character_business_id", lambda record: _text(record, "character_business_id", "character_id")),
            NormalizedExtraColumn("expression_text", lambda record: _text(record, "expression_text", "text")),
            NormalizedExtraColumn("expression_payload", lambda record: _json_payload(record, "expression_payload", "payload")),
        ),
    ),
    "perception_state_records": NormalizedPayloadRepositorySpec(
        repository_name="perception_state_records",
        table_name="perception_states",
        id_field="perception_state_id",
        business_id_column="perception_id",
        extra_columns=(
            NormalizedExtraColumn("character_business_id", lambda record: _text(record, "character_business_id", "character_id")),
            NormalizedExtraColumn("target_entity_type", lambda record: _text(record, "target_entity_type")),
            NormalizedExtraColumn("target_business_id", lambda record: _text(record, "target_business_id", "target_id")),
            NormalizedExtraColumn("perceived_fact", lambda record: _text(record, "perceived_fact", "fact", "text")),
        ),
    ),
    "apparent_contradiction_records": NormalizedPayloadRepositorySpec(
        repository_name="apparent_contradiction_records",
        table_name="apparent_contradictions",
        id_field="apparent_contradiction_id",
        business_id_column="contradiction_id",
        extra_columns=(
            NormalizedExtraColumn("contradiction_text", lambda record: _text(record, "contradiction_text", "text", "summary")),
            NormalizedExtraColumn("related_refs", lambda record: _json_payload(record, "related_refs", default=[])),
            NormalizedExtraColumn("classification", lambda record: _text(record, "classification")),
            NormalizedExtraColumn("resolution_status", lambda record: _text(record, "resolution_status", default="OPEN")),
        ),
    ),
    "narrative_debts": NormalizedPayloadRepositorySpec(
        repository_name="narrative_debts",
        table_name="narrative_debts",
        id_field="narrative_debt_id",
        business_id_column="debt_id",
        extra_columns=(
            NormalizedExtraColumn("debt_type", lambda record: _text(record, "debt_type", "type")),
            NormalizedExtraColumn("debt_text", lambda record: _text(record, "debt_text", "text", "summary")),
            NormalizedExtraColumn("setup_ref", lambda record: _json_payload(record, "setup_ref", default={})),
            NormalizedExtraColumn("payoff_plan", lambda record: _text(record, "payoff_plan")),
        ),
    ),
}


def _assert_safe_identifier(value: str, label: str) -> None:
    if not _SAFE_SQL_IDENTIFIER.fullmatch(value):
        raise StorageError(f"Normalized PostgreSQL {label} identifier is invalid.")


def _business_id(record: dict[str, Any], id_field: str, business_id_column: str) -> str:
    return str(record.get(id_field) or record.get(business_id_column) or "").strip()


def _text(record: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _integer(record: dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return _positive_int(value, default) if default > 0 else _int_or_default(value, default)
    return default


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_payload(
    record: dict[str, Any],
    *keys: str,
    default: Any | None = None,
) -> Any:
    fallback = {} if default is None else default
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return fallback


def _nullable_text(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _nullable_int(record: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return _int_or_default(value, 0)
    return None


def _display_name(record: dict[str, Any], fallback: str) -> str:
    return str(record.get("display_name") or record.get("name") or fallback)


def _role_tier(record: dict[str, Any]) -> str:
    return str(record.get("role_tier") or record.get("tier") or record.get("role") or "")


def _short_description(record: dict[str, Any]) -> str:
    value = record.get("short_description") or record.get("description")
    if value:
        return str(value)
    profile = record.get("profile")
    if isinstance(profile, dict):
        return str(profile.get("description") or "")
    return ""


def _canonical_status(record: dict[str, Any]) -> str:
    raw = str(record.get("canonical_status") or record.get("status") or "").strip()
    upper = raw.upper()
    if upper in _CANONICAL_STATUS_VALUES:
        return upper
    mapping = {
        "active": "CONFIRMED",
        "confirmed": "CONFIRMED",
        "complete": "CONFIRMED",
        "completed": "CONFIRMED",
        "outputs": "CONFIRMED",
        "planned": "DRAFT",
        "draft": "DRAFT",
        "candidate": "CANDIDATE",
        "provisional": "PROVISIONAL",
        "archived": "ARCHIVED",
        "deleted": "DELETED",
        "rejected": "REJECTED",
    }
    return mapping.get(raw.lower(), "DRAFT")


def _legacy_status_raw(record: dict[str, Any]) -> str:
    return str(record.get("legacy_status_raw") or record.get("status") or "")


def _lifecycle_state(record: dict[str, Any]) -> str:
    raw = str(record.get("lifecycle_state") or "").strip().upper()
    if raw in _LIFECYCLE_VALUES:
        return raw
    status = str(record.get("status") or "").strip().lower()
    if record.get("deleted_at") or status == "deleted":
        return "DELETED"
    if record.get("is_provisional") or status == "provisional":
        return "PROVISIONAL"
    if status == "archived":
        return "ARCHIVED"
    return "ACTIVE"


def _authority_level(record: dict[str, Any]) -> str:
    raw = str(record.get("authority_level") or "").strip().upper()
    if raw in _AUTHORITY_VALUES:
        return raw
    return "SYSTEM_CONFIRMED"


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _source_refs(record: dict[str, Any]) -> list[Any]:
    refs = record.get("source_refs")
    return list(refs) if isinstance(refs, list) else []


def _metadata_with_payload(record: dict[str, Any]) -> dict[str, Any]:
    raw_metadata = record.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    metadata[_M2_RECORD_PAYLOAD_KEY] = dict(record)
    return metadata


def _content_hash(record: dict[str, Any]) -> str:
    encoded = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value
