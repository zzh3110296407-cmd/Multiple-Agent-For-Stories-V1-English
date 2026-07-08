from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from storage_foundation.entity_refs import EntityRef, PackDependencyRef, SourceRef
from storage_foundation.storage_modes import StorageBackendType, StorageMode

Row = dict[str, Any]


@dataclass(frozen=True)
class RepositoryFilters:
    status: str | None = None
    lifecycle_state: str | None = None
    chapter_id: str | None = None
    scene_id: str | None = None
    character_id: str | None = None
    location_id: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class WriteResult:
    ok: bool
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class StorageAssignment:
    project_id: str
    backend_id: str
    backend_type: StorageBackendType
    mode: StorageMode
    activated_at: str = ""
    status: str = "CONFIRMED"


@dataclass(frozen=True)
class JsonImportFileRecord:
    source_path: str
    source_hash: str
    target_domain: str
    target_table: str
    row_count: int = 0
    parse_status: str = "PENDING"
    source_refs: tuple[SourceRef, ...] = field(default_factory=tuple)


@runtime_checkable
class BusinessRepository(Protocol):
    entity_type: str

    def list_all(
        self,
        project_id: str,
        filters: RepositoryFilters | None = None,
    ) -> list[Row]:
        ...

    def get_by_business_id(self, project_id: str, business_id: str) -> Row | None:
        ...

    def append(
        self,
        project_id: str,
        row: Row,
        *,
        idempotency_key: str | None = None,
    ) -> WriteResult:
        ...

    def upsert(
        self,
        project_id: str,
        business_id: str,
        row: Row,
        *,
        idempotency_key: str | None = None,
    ) -> WriteResult:
        ...

    def write_all(
        self,
        project_id: str,
        rows: list[Row],
        *,
        batch_id: str | None = None,
    ) -> WriteResult:
        ...


@runtime_checkable
class PackRepository(Protocol):
    pack_type: str

    def read_pack(self, project_id: str, pack_id: str) -> Row | None:
        ...

    def list_packs(
        self,
        project_id: str,
        filters: RepositoryFilters | None = None,
    ) -> list[Row]:
        ...

    def write_pack(
        self,
        project_id: str,
        pack: Row,
        dependency_refs: list[PackDependencyRef],
    ) -> WriteResult:
        ...

    def mark_pack_stale(
        self,
        project_id: str,
        pack_id: str,
        stale_reason: str,
    ) -> WriteResult:
        ...


@runtime_checkable
class MigrationRepository(Protocol):
    def record_import_file(self, batch_id: str, file_record: JsonImportFileRecord) -> WriteResult:
        ...

    def record_consistency_report(
        self,
        project_id: str,
        report_id: str,
        mismatches: list[Row],
    ) -> WriteResult:
        ...


@runtime_checkable
class StoragePort(Protocol):
    mode: StorageMode

    def assignment_for_project(self, project_id: str) -> StorageAssignment | None:
        ...

    def repository_for(self, entity_type: str) -> BusinessRepository:
        ...

    def pack_repository_for(self, pack_type: str) -> PackRepository:
        ...

    def begin_transaction(self, project_id: str, reason: str) -> str:
        ...

    def commit_transaction(self, transaction_id: str) -> None:
        ...

    def rollback_transaction(self, transaction_id: str, reason: str) -> None:
        ...


def entity_dependency(project_id: str, entity_type: str, business_id: str, reason: str) -> PackDependencyRef:
    return PackDependencyRef(
        entity_ref=EntityRef(
            project_id=project_id,
            entity_type=entity_type,
            business_id=business_id,
        ),
        dependency_reason=reason,
    )

