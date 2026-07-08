import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any

from app.backend.core.config import redact_database_url
from app.backend.storage.json_store import StorageError


_SAFE_SCHEMA_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NORMALIZED_SCHEMA_NAME = "mas_phase875_proto"
_SETUP_ADMIN_DOCUMENTS = {
    "active_project_selection.json",
    "project_creation_decisions.json",
    "project_creation_drafts.json",
    "project_creation_requests.json",
    "project_creation_validation_reports.json",
    "project_origin_metadata.json",
    "project_registry.json",
}
_NORMALIZED_STORY_DOCUMENT_REPOSITORIES = {
    "apparent_contradiction_records.json",
    "character_expression_records.json",
    "character_psychology_traces.json",
    "chapter_memory_packs.json",
    "chapters.json",
    "characters.json",
    "claim_records.json",
    "continuity_issues.json",
    "decisions.json",
    "events.json",
    "framework_package.json",
    "memory_records.json",
    "memory_update_plans.json",
    "narrative_debts.json",
    "narrative_intent_records.json",
    "pending_character_state_changes.json",
    "perception_state_records.json",
    "quality_reports.json",
    "relationships.json",
    "scene_memory_packs.json",
    "scenes.json",
    "state_changes.json",
    "story_bible.json",
    "world_canvas.json",
}
_NORMALIZED_STORY_DOCUMENT_REPOSITORY_BY_FILE = {
    "apparent_contradiction_records.json": "apparent_contradiction_records",
    "character_expression_records.json": "character_expression_records",
    "character_psychology_traces.json": "character_psychology_traces",
    "chapter_memory_packs.json": "chapter_memory_packs",
    "chapters.json": "chapters",
    "characters.json": "characters",
    "claim_records.json": "claim_records",
    "continuity_issues.json": "continuity_issues",
    "decisions.json": "decisions",
    "events.json": "events",
    "framework_package.json": "framework_packages",
    "memory_records.json": "memory",
    "memory_update_plans.json": "memory_update_plans",
    "narrative_debts.json": "narrative_debts",
    "narrative_intent_records.json": "narrative_intent_records",
    "pending_character_state_changes.json": "pending_character_state_changes",
    "perception_state_records.json": "perception_state_records",
    "quality_reports.json": "quality_reports",
    "relationships.json": "relationships",
    "scene_memory_packs.json": "scene_memory_packs",
    "scenes.json": "scenes",
    "state_changes.json": "state_changes",
    "story_bible.json": "story_bibles",
    "world_canvas.json": "world_canvases",
}
_NORMALIZED_SINGLE_OBJECT_DOCUMENTS = {
    "framework_package.json",
    "story_bible.json",
    "world_canvas.json",
}
_NORMALIZED_PACK_DOCUMENTS = {
    "chapter_memory_packs.json",
    "scene_memory_packs.json",
}
_PROJECT_METADATA_DOCUMENTS = {
    "framework.json",
    "issues.json",
    "project.json",
}
_PROJECT_METADATA_DOCUMENT_PAYLOAD_KEYS = {
    "framework.json": "_postgres_json_store_framework_payload",
    "issues.json": "_postgres_json_store_issues_payload",
    "project.json": "_postgres_json_store_project_payload",
}
_BLOCKED_AUTHORITATIVE_STORY_DOCUMENTS = {
    "final_story_package.json",
    "framework_state.json",
    "old_story_completion_candidates.json",
}


class PostgresJsonStore:
    """PostgreSQL-backed implementation of the JsonStore document contract.

    This is a staged runtime adapter for Phase 8.75 M8. It keeps the existing
    service/repository contracts stable while moving JSON document persistence
    from local files to PostgreSQL in explicit postgres_primary mode.
    """

    def __init__(
        self,
        *,
        database_url: str,
        data_dir: Path,
        schema_name: str = "mas_phase875_runtime",
    ) -> None:
        if not database_url:
            raise StorageError(
                "PostgreSQL JSON store requires MULTIPLE_AGENT_STORIES_DATABASE_URL."
            )
        if not _SAFE_SCHEMA_NAME.fullmatch(schema_name):
            raise StorageError("PostgreSQL JSON store schema name is invalid.")
        self.database_url = database_url
        self.safe_database_url = redact_database_url(database_url)
        self.data_dir = data_dir.resolve(strict=False)
        self.schema_name = schema_name
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._normalized_connection_factory: Any | None = None
        self._normalized_repositories: dict[str, Any] = {}

    def exists(self, path: Path) -> bool:
        storage_root, relative_path = self._document_key(path)
        if self._normalized_repository_name(relative_path):
            return self._normalized_document_exists(relative_path)
        if self._is_project_document(relative_path):
            return self._project_document_exists(relative_path)
        table_name = self._document_table(relative_path)
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    self._sql(
                        f"SELECT 1 FROM {{schema}}.{table_name} "
                        "WHERE storage_root = %s AND relative_path = %s "
                        "LIMIT 1"
                    ),
                    (storage_root, relative_path),
                ).fetchone()
            return row is not None
        except Exception as exc:
            self._raise_storage_error("check existence for", relative_path, exc)

    def read_any(self, path: Path) -> Any:
        storage_root, relative_path = self._document_key(path)
        if self._normalized_repository_name(relative_path):
            return self._read_normalized_document(relative_path)
        if self._is_project_document(relative_path):
            return self._read_project_document(relative_path)
        table_name = self._document_table(relative_path)
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    self._sql(
                        f"SELECT document::text FROM {{schema}}.{table_name} "
                        "WHERE storage_root = %s AND relative_path = %s"
                    ),
                    (storage_root, relative_path),
                ).fetchone()
            if row is None:
                raise StorageError(f"JSON document does not exist: {relative_path}")
            return json.loads(str(row[0]))
        except StorageError:
            raise
        except Exception as exc:
            self._raise_storage_error("read", relative_path, exc)

    def read(self, path: Path) -> dict[str, Any]:
        data = self.read_any(path)
        if not isinstance(data, dict):
            raise StorageError(f"JSON root must be an object: {path}")
        return data

    def read_list(self, path: Path) -> list[Any]:
        data = self.read_any(path)
        if not isinstance(data, list):
            raise StorageError(f"JSON root must be a list: {path}")
        return data

    def write(self, path: Path, data: Any) -> None:
        storage_root, relative_path = self._document_key(path)
        if self._normalized_repository_name(relative_path):
            self._write_normalized_document(relative_path, data)
            return
        if self._is_project_document(relative_path):
            self._write_project_document(relative_path, data)
            return
        table_name = self._document_table(relative_path)
        self._assert_runtime_document_writable(relative_path, table_name)
        content_hash = self._content_hash(data)
        try:
            Jsonb = self._jsonb_adapter()
            with self._connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    self._sql(
                        f"INSERT INTO {{schema}}.{table_name} "
                        "(storage_root, relative_path, document, content_hash) "
                        "VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (storage_root, relative_path) DO UPDATE SET "
                        "document = EXCLUDED.document, "
                        "content_hash = EXCLUDED.content_hash, "
                        "updated_at = now()"
                    ),
                    (storage_root, relative_path, Jsonb(data), content_hash),
                )
        except Exception as exc:
            self._raise_storage_error("write", relative_path, exc)

    def write_if_missing(self, path: Path, data: Any) -> bool:
        storage_root, relative_path = self._document_key(path)
        if self._normalized_repository_name(relative_path):
            if self._normalized_document_exists(relative_path):
                return False
            self._write_normalized_document(relative_path, data)
            return True
        if self._is_project_document(relative_path):
            if self._project_document_exists(relative_path):
                return False
            self._write_project_document(relative_path, data)
            return True
        table_name = self._document_table(relative_path)
        self._assert_runtime_document_writable(relative_path, table_name)
        content_hash = self._content_hash(data)
        try:
            Jsonb = self._jsonb_adapter()
            with self._connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    self._sql(
                        f"INSERT INTO {{schema}}.{table_name} "
                        "(storage_root, relative_path, document, content_hash) "
                        "VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (storage_root, relative_path) DO NOTHING "
                        "RETURNING 1"
                    ),
                    (storage_root, relative_path, Jsonb(data), content_hash),
                ).fetchone()
            return row is not None
        except Exception as exc:
            self._raise_storage_error("write missing", relative_path, exc)

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:
            raise StorageError(
                "postgres_primary storage mode requires psycopg. "
                "Install backend requirements; no database URL was logged."
            ) from exc
        try:
            return psycopg.connect(self.database_url)
        except Exception as exc:
            raise StorageError(
                "Cannot connect to PostgreSQL runtime store "
                f"({self.safe_database_url}); raw connection string was not logged."
            ) from exc

    def _jsonb_adapter(self) -> Any:
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise StorageError(
                "postgres_primary storage mode requires psycopg JSONB support."
            ) from exc
        return Jsonb

    def _ensure_schema(self, conn: Any) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name}")
            conn.execute(
                self._sql(
                    "CREATE TABLE IF NOT EXISTS {schema}.runtime_json_documents ("
                    "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
                    "storage_root text NOT NULL, "
                    "relative_path text NOT NULL, "
                    "document jsonb NOT NULL, "
                    "content_hash text NOT NULL DEFAULT '', "
                    "created_at timestamptz NOT NULL DEFAULT now(), "
                    "updated_at timestamptz NOT NULL DEFAULT now(), "
                    "CONSTRAINT uq_runtime_json_documents_root_path "
                    "UNIQUE (storage_root, relative_path)"
                    ")"
                )
            )
            conn.execute(
                self._sql(
                    "CREATE INDEX IF NOT EXISTS idx_runtime_json_documents_updated_at "
                    "ON {schema}.runtime_json_documents (updated_at)"
                )
            )
            conn.execute(
                self._sql(
                    "CREATE TABLE IF NOT EXISTS {schema}.setup_admin_json_documents ("
                    "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
                    "storage_root text NOT NULL, "
                    "relative_path text NOT NULL, "
                    "document jsonb NOT NULL, "
                    "content_hash text NOT NULL DEFAULT '', "
                    "created_at timestamptz NOT NULL DEFAULT now(), "
                    "updated_at timestamptz NOT NULL DEFAULT now(), "
                    "CONSTRAINT uq_setup_admin_json_documents_root_path "
                    "UNIQUE (storage_root, relative_path)"
                    ")"
                )
            )
            conn.execute(
                self._sql(
                    "CREATE INDEX IF NOT EXISTS idx_setup_admin_json_documents_updated_at "
                    "ON {schema}.setup_admin_json_documents (updated_at)"
                )
            )
            self._move_setup_admin_documents_out_of_runtime_table(conn)
            self._schema_ready = True

    def _document_key(self, path: Path) -> tuple[str, str]:
        resolved = path.resolve(strict=False)
        try:
            relative = resolved.relative_to(self.data_dir)
            return str(self.data_dir), relative.as_posix()
        except ValueError:
            return "__absolute_path__", resolved.as_posix()

    def _sql(self, template: str) -> str:
        return template.format(schema=self.schema_name)

    def _normalized_sql(self, template: str) -> str:
        return template.format(schema=_NORMALIZED_SCHEMA_NAME)

    def _document_table(self, relative_path: str) -> str:
        normalized_path = relative_path.replace("\\", "/").strip("/")
        if normalized_path in _SETUP_ADMIN_DOCUMENTS:
            return "setup_admin_json_documents"
        return "runtime_json_documents"

    def _document_file_name(self, relative_path: str) -> str:
        normalized_path = relative_path.replace("\\", "/").strip("/")
        return normalized_path.rsplit("/", 1)[-1]

    def _normalized_repository_name(self, relative_path: str) -> str | None:
        return _NORMALIZED_STORY_DOCUMENT_REPOSITORY_BY_FILE.get(
            self._document_file_name(relative_path)
        )

    def _is_project_document(self, relative_path: str) -> bool:
        return self._document_file_name(relative_path) in _PROJECT_METADATA_DOCUMENTS

    def _project_document_payload_key(self, relative_path: str) -> str:
        file_name = self._document_file_name(relative_path)
        key = _PROJECT_METADATA_DOCUMENT_PAYLOAD_KEYS.get(file_name)
        if not key:
            raise StorageError(f"No normalized project metadata route for {relative_path}.")
        return key

    def _normalized_repository(self, relative_path: str) -> Any:
        repository_name = self._normalized_repository_name(relative_path)
        if not repository_name:
            raise StorageError(
                f"No normalized PostgreSQL repository route for {relative_path}."
            )
        cached = self._normalized_repositories.get(repository_name)
        if cached is not None:
            return cached
        from app.backend.repositories.postgres_normalized_repositories import (
            PostgresConnectionFactory,
            create_postgres_normalized_repository,
        )

        if self._normalized_connection_factory is None:
            self._normalized_connection_factory = PostgresConnectionFactory(
                database_url=self.database_url,
            )
        repository = create_postgres_normalized_repository(
            repository_name=repository_name,
            connection_factory=self._normalized_connection_factory,
            data_dir=self.data_dir,
        )
        self._normalized_repositories[repository_name] = repository
        return repository

    def _normalized_document_exists(self, relative_path: str) -> bool:
        try:
            if self._document_file_name(relative_path) in _NORMALIZED_PACK_DOCUMENTS:
                return bool(self._normalized_repository(relative_path).list_packs())
            return bool(self._normalized_repository(relative_path).list_all())
        except StorageError:
            raise
        except Exception as exc:
            self._raise_storage_error("check normalized existence for", relative_path, exc)

    def _read_normalized_document(self, relative_path: str) -> Any:
        file_name = self._document_file_name(relative_path)
        repository = self._normalized_repository(relative_path)
        try:
            if file_name in _NORMALIZED_PACK_DOCUMENTS:
                envelope = repository.read_envelope()
                if not repository.list_packs():
                    raise StorageError(f"JSON document does not exist: {relative_path}")
                return envelope
            records = repository.list_all()
            if not records:
                raise StorageError(f"JSON document does not exist: {relative_path}")
            if file_name in _NORMALIZED_SINGLE_OBJECT_DOCUMENTS:
                return dict(records[0])
            return [dict(record) for record in records]
        except StorageError:
            raise
        except Exception as exc:
            self._raise_storage_error("read normalized", relative_path, exc)

    def _write_normalized_document(self, relative_path: str, data: Any) -> None:
        file_name = self._document_file_name(relative_path)
        repository = self._normalized_repository(relative_path)
        try:
            if file_name in _NORMALIZED_PACK_DOCUMENTS:
                if isinstance(data, dict):
                    repository.write_envelope(dict(data))
                    return
                if isinstance(data, list):
                    repository.write_envelope({"packs": data})
                    return
                raise StorageError(f"{file_name} must be a JSON object or list.")
            if file_name in _NORMALIZED_SINGLE_OBJECT_DOCUMENTS:
                if not isinstance(data, dict):
                    raise StorageError(f"{file_name} must be a JSON object.")
                repository.write_all([dict(data)])
                return
            if not isinstance(data, list):
                raise StorageError(f"{file_name} must be a JSON list.")
            records: list[dict[str, Any]] = []
            for record in data:
                if not isinstance(record, dict):
                    raise StorageError(f"{file_name} list items must be JSON objects.")
                records.append(dict(record))
            repository.write_all(records)
        except StorageError:
            raise
        except Exception as exc:
            self._raise_storage_error("write normalized", relative_path, exc)

    def _project_business_id(self, relative_path: str, payload: dict[str, Any] | None = None) -> str:
        if isinstance(payload, dict):
            project_id = str(payload.get("project_id") or "").strip()
            if project_id:
                return project_id
        return self.data_dir.name or "local_project"

    def _project_document_exists(self, relative_path: str) -> bool:
        project_id = self._project_business_id(relative_path)
        try:
            with self._connect() as conn:
                row = conn.execute(
                    self._normalized_sql(
                        "SELECT metadata FROM {schema}.projects "
                        "WHERE project_id = %s AND deleted_at IS NULL LIMIT 1"
                    ),
                    (project_id,),
                ).fetchone()
            if row is None:
                return False
            if self._document_file_name(relative_path) == "project.json":
                return True
            return self._project_document_payload_key(relative_path) in dict(row[0] or {})
        except Exception as exc:
            self._raise_storage_error("check project document existence for", relative_path, exc)

    def _read_project_document(self, relative_path: str) -> dict[str, Any]:
        project_id = self._project_business_id(relative_path)
        try:
            with self._connect() as conn:
                row = conn.execute(
                    self._normalized_sql(
                        "SELECT project_id, display_name, storage_mode, status, "
                        "lifecycle_state, authority_level, metadata::text "
                        "FROM {schema}.projects "
                        "WHERE project_id = %s AND deleted_at IS NULL"
                    ),
                    (project_id,),
                ).fetchone()
            if row is None:
                raise StorageError(f"JSON document does not exist: {relative_path}")
            metadata = json.loads(str(row[6] or "{}"))
            payload = metadata.get(self._project_document_payload_key(relative_path))
            if payload is not None:
                return payload
            if self._document_file_name(relative_path) != "project.json":
                raise StorageError(f"JSON document does not exist: {relative_path}")
            return {
                "project_id": str(row[0] or ""),
                "title": str(row[1] or ""),
                "storage_mode": str(row[2] or ""),
                "status": str(row[3] or ""),
                "lifecycle_state": str(row[4] or ""),
                "authority_level": str(row[5] or ""),
            }
        except StorageError:
            raise
        except Exception as exc:
            self._raise_storage_error("read project document", relative_path, exc)

    def _write_project_document(self, relative_path: str, data: Any) -> None:
        file_name = self._document_file_name(relative_path)
        project_id = self._project_business_id(relative_path, data)
        display_name = str(
            data.get("title") or data.get("name") or data.get("display_name") or project_id
            if isinstance(data, dict)
            else project_id
        )
        metadata_payload = {
            self._project_document_payload_key(relative_path): data,
            "source": "postgres_json_store_project_metadata_document_route",
        }
        try:
            Jsonb = self._jsonb_adapter()
            with self._connect() as conn:
                if file_name == "project.json":
                    conn.execute(
                        self._normalized_sql(
                            "INSERT INTO {schema}.projects ("
                            "project_id, display_name, storage_mode, status, "
                            "lifecycle_state, authority_level, source_type, metadata"
                            ") VALUES ("
                            "%s, %s, 'POSTGRES_PRIMARY', 'CONFIRMED', "
                            "'ACTIVE', 'SYSTEM_CONFIRMED', 'RUNTIME', %s"
                            ") ON CONFLICT (project_id) DO UPDATE SET "
                            "display_name = EXCLUDED.display_name, "
                            "metadata = {schema}.projects.metadata || EXCLUDED.metadata, "
                            "updated_at = now()"
                        ),
                        (project_id, display_name, Jsonb(metadata_payload)),
                    )
                else:
                    conn.execute(
                        self._normalized_sql(
                            "INSERT INTO {schema}.projects ("
                            "project_id, display_name, storage_mode, status, "
                            "lifecycle_state, authority_level, source_type, metadata"
                            ") VALUES ("
                            "%s, %s, 'POSTGRES_PRIMARY', 'CONFIRMED', "
                            "'ACTIVE', 'SYSTEM_CONFIRMED', 'RUNTIME', %s"
                            ") ON CONFLICT (project_id) DO UPDATE SET "
                            "metadata = {schema}.projects.metadata || EXCLUDED.metadata, "
                            "updated_at = now()"
                        ),
                        (project_id, project_id, Jsonb(metadata_payload)),
                    )
        except Exception as exc:
            self._raise_storage_error("write project document", relative_path, exc)

    def _assert_runtime_document_writable(
        self,
        relative_path: str,
        table_name: str,
    ) -> None:
        if table_name != "runtime_json_documents":
            return
        file_name = self._document_file_name(relative_path)
        if file_name not in _BLOCKED_AUTHORITATIVE_STORY_DOCUMENTS:
            return
        raise StorageError(
            "postgres_primary blocks core authoritative JSON document writes "
            f"to runtime_json_documents: {file_name}. Use normalized repositories."
        )

    def _move_setup_admin_documents_out_of_runtime_table(self, conn: Any) -> None:
        conn.execute(
            self._sql(
                "INSERT INTO {schema}.setup_admin_json_documents "
                "(storage_root, relative_path, document, content_hash, created_at, updated_at) "
                "SELECT storage_root, relative_path, document, content_hash, created_at, updated_at "
                "FROM {schema}.runtime_json_documents "
                "WHERE relative_path = ANY(%s::text[]) "
                "ON CONFLICT (storage_root, relative_path) DO UPDATE SET "
                "document = EXCLUDED.document, "
                "content_hash = EXCLUDED.content_hash, "
                "updated_at = EXCLUDED.updated_at"
            ),
            (sorted(_SETUP_ADMIN_DOCUMENTS),),
        )
        conn.execute(
            self._sql(
                "DELETE FROM {schema}.runtime_json_documents "
                "WHERE relative_path = ANY(%s::text[])"
            ),
            (sorted(_SETUP_ADMIN_DOCUMENTS),),
        )

    def _content_hash(self, data: Any) -> str:
        encoded = json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _raise_storage_error(self, action: str, relative_path: str, exc: Exception) -> None:
        if isinstance(exc, StorageError):
            raise exc
        raise StorageError(
            f"PostgreSQL JSON store failed to {action} {relative_path}: "
            f"{type(exc).__name__}; database={self.safe_database_url}"
        ) from exc
