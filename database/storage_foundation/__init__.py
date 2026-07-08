"""Database-session storage foundation prototype.

This package is intentionally isolated from the main backend during M0/M1.
"""

from storage_foundation.contracts import (
    BusinessRepository,
    JsonImportFileRecord,
    MigrationRepository,
    PackRepository,
    RepositoryFilters,
    StorageAssignment,
    StoragePort,
    WriteResult,
)
from storage_foundation.entity_refs import EntityRef, PackDependencyRef, SourceRef
from storage_foundation.storage_modes import (
    AuthorityLevel,
    CanonicalStatus,
    LifecycleState,
    StorageBackendType,
    StorageMode,
    canonicalize_legacy_status,
)

__all__ = [
    "AuthorityLevel",
    "BusinessRepository",
    "CanonicalStatus",
    "EntityRef",
    "JsonImportFileRecord",
    "LifecycleState",
    "MigrationRepository",
    "PackDependencyRef",
    "PackRepository",
    "RepositoryFilters",
    "SourceRef",
    "StorageAssignment",
    "StorageBackendType",
    "StorageMode",
    "StoragePort",
    "WriteResult",
    "canonicalize_legacy_status",
]

