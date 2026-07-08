from dataclasses import dataclass
from enum import StrEnum


class StorageMode(StrEnum):
    JSON_PRIMARY = "JSON_PRIMARY"
    POSTGRES_SHADOW = "POSTGRES_SHADOW"
    POSTGRES_PRIMARY = "POSTGRES_PRIMARY"
    JSON_EXPORT_ONLY = "JSON_EXPORT_ONLY"


class StorageBackendType(StrEnum):
    JSON = "JSON"
    POSTGRES = "POSTGRES"


class CanonicalStatus(StrEnum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    PROVISIONAL = "PROVISIONAL"
    TEMPORARY_CONFIRMED = "TEMPORARY_CONFIRMED"
    CONFIRMED = "CONFIRMED"
    FORMAL_APPLIED = "FORMAL_APPLIED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class LifecycleState(StrEnum):
    ACTIVE = "ACTIVE"
    PROVISIONAL = "PROVISIONAL"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class AuthorityLevel(StrEnum):
    USER_LOCKED = "USER_LOCKED"
    USER_CONFIRMED = "USER_CONFIRMED"
    FORMAL_APPLIED = "FORMAL_APPLIED"
    SYSTEM_CONFIRMED = "SYSTEM_CONFIRMED"
    GENERATED_CANDIDATE = "GENERATED_CANDIDATE"
    ANALYZER_REFERENCE = "ANALYZER_REFERENCE"
    MIGRATED_REFERENCE = "MIGRATED_REFERENCE"
    PLUGIN_REFERENCE = "PLUGIN_REFERENCE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CanonicalStatusTriple:
    status: CanonicalStatus
    lifecycle_state: LifecycleState
    authority_level: AuthorityLevel


_LEGACY_STATUS_MAP: dict[str, CanonicalStatusTriple] = {
    "confirmed": CanonicalStatusTriple(
        CanonicalStatus.CONFIRMED,
        LifecycleState.ACTIVE,
        AuthorityLevel.SYSTEM_CONFIRMED,
    ),
    "revised": CanonicalStatusTriple(
        CanonicalStatus.CONFIRMED,
        LifecycleState.ACTIVE,
        AuthorityLevel.SYSTEM_CONFIRMED,
    ),
    "temporary_confirmed": CanonicalStatusTriple(
        CanonicalStatus.TEMPORARY_CONFIRMED,
        LifecycleState.PROVISIONAL,
        AuthorityLevel.SYSTEM_CONFIRMED,
    ),
    "active": CanonicalStatusTriple(
        CanonicalStatus.CONFIRMED,
        LifecycleState.ACTIVE,
        AuthorityLevel.MIGRATED_REFERENCE,
    ),
    "outputs": CanonicalStatusTriple(
        CanonicalStatus.CONFIRMED,
        LifecycleState.ACTIVE,
        AuthorityLevel.MIGRATED_REFERENCE,
    ),
    "draft": CanonicalStatusTriple(
        CanonicalStatus.DRAFT,
        LifecycleState.ACTIVE,
        AuthorityLevel.GENERATED_CANDIDATE,
    ),
    "thinking": CanonicalStatusTriple(
        CanonicalStatus.DRAFT,
        LifecycleState.ACTIVE,
        AuthorityLevel.GENERATED_CANDIDATE,
    ),
    "candidate": CanonicalStatusTriple(
        CanonicalStatus.CANDIDATE,
        LifecycleState.PROVISIONAL,
        AuthorityLevel.GENERATED_CANDIDATE,
    ),
    "provisional": CanonicalStatusTriple(
        CanonicalStatus.PROVISIONAL,
        LifecycleState.PROVISIONAL,
        AuthorityLevel.GENERATED_CANDIDATE,
    ),
    "pending": CanonicalStatusTriple(
        CanonicalStatus.CANDIDATE,
        LifecycleState.PROVISIONAL,
        AuthorityLevel.GENERATED_CANDIDATE,
    ),
    "superseded": CanonicalStatusTriple(
        CanonicalStatus.SUPERSEDED,
        LifecycleState.ARCHIVED,
        AuthorityLevel.MIGRATED_REFERENCE,
    ),
    "rejected": CanonicalStatusTriple(
        CanonicalStatus.REJECTED,
        LifecycleState.ARCHIVED,
        AuthorityLevel.MIGRATED_REFERENCE,
    ),
    "archived": CanonicalStatusTriple(
        CanonicalStatus.ARCHIVED,
        LifecycleState.ARCHIVED,
        AuthorityLevel.MIGRATED_REFERENCE,
    ),
    "deleted": CanonicalStatusTriple(
        CanonicalStatus.DELETED,
        LifecycleState.DELETED,
        AuthorityLevel.MIGRATED_REFERENCE,
    ),
}


def canonicalize_legacy_status(value: str | None) -> CanonicalStatusTriple:
    normalized = str(value or "").strip().casefold()
    return _LEGACY_STATUS_MAP.get(
        normalized,
        CanonicalStatusTriple(
            CanonicalStatus.CANDIDATE,
            LifecycleState.PROVISIONAL,
            AuthorityLevel.UNKNOWN,
        ),
    )

