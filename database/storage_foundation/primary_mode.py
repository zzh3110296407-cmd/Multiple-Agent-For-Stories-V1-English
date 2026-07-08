from dataclasses import dataclass

from storage_foundation.storage_modes import StorageBackendType, StorageMode


class StorageRouteValidationError(ValueError):
    """Raised when a project storage assignment cannot produce a safe route."""


@dataclass(frozen=True)
class StorageRouteInput:
    project_id: str
    mode: StorageMode
    backend_type: StorageBackendType
    backend_id: str
    json_export_backend_id: str = ""


@dataclass(frozen=True)
class StorageRouteDecision:
    project_id: str
    primary_mode: StorageMode
    primary_backend_type: StorageBackendType
    primary_backend_id: str
    backup_mode: StorageMode | None
    backup_backend_id: str

    @property
    def postgres_is_primary(self) -> bool:
        return (
            self.primary_mode == StorageMode.POSTGRES_PRIMARY
            and self.primary_backend_type == StorageBackendType.POSTGRES
        )

    @property
    def json_export_available(self) -> bool:
        return self.backup_mode == StorageMode.JSON_EXPORT_ONLY and bool(self.backup_backend_id)


def resolve_storage_route(route_input: StorageRouteInput) -> StorageRouteDecision:
    if not route_input.project_id:
        raise StorageRouteValidationError("project_id is required")
    if not route_input.backend_id:
        raise StorageRouteValidationError("backend_id is required")

    if route_input.mode == StorageMode.POSTGRES_PRIMARY:
        if route_input.backend_type != StorageBackendType.POSTGRES:
            raise StorageRouteValidationError("POSTGRES_PRIMARY requires a POSTGRES backend")
        if not route_input.json_export_backend_id:
            raise StorageRouteValidationError(
                "POSTGRES_PRIMARY requires a json export backend for rollback/backup"
            )
        return StorageRouteDecision(
            project_id=route_input.project_id,
            primary_mode=StorageMode.POSTGRES_PRIMARY,
            primary_backend_type=StorageBackendType.POSTGRES,
            primary_backend_id=route_input.backend_id,
            backup_mode=StorageMode.JSON_EXPORT_ONLY,
            backup_backend_id=route_input.json_export_backend_id,
        )

    if route_input.mode == StorageMode.JSON_PRIMARY:
        if route_input.backend_type != StorageBackendType.JSON:
            raise StorageRouteValidationError("JSON_PRIMARY requires a JSON backend")
        return StorageRouteDecision(
            project_id=route_input.project_id,
            primary_mode=StorageMode.JSON_PRIMARY,
            primary_backend_type=StorageBackendType.JSON,
            primary_backend_id=route_input.backend_id,
            backup_mode=None,
            backup_backend_id="",
        )

    if route_input.mode == StorageMode.POSTGRES_SHADOW:
        if route_input.backend_type != StorageBackendType.POSTGRES:
            raise StorageRouteValidationError("POSTGRES_SHADOW requires a POSTGRES backend")
        return StorageRouteDecision(
            project_id=route_input.project_id,
            primary_mode=StorageMode.JSON_PRIMARY,
            primary_backend_type=StorageBackendType.JSON,
            primary_backend_id="json_primary_runtime",
            backup_mode=StorageMode.POSTGRES_SHADOW,
            backup_backend_id=route_input.backend_id,
        )

    if route_input.mode == StorageMode.JSON_EXPORT_ONLY:
        if route_input.backend_type != StorageBackendType.JSON:
            raise StorageRouteValidationError("JSON_EXPORT_ONLY requires a JSON backend")
        return StorageRouteDecision(
            project_id=route_input.project_id,
            primary_mode=StorageMode.JSON_EXPORT_ONLY,
            primary_backend_type=StorageBackendType.JSON,
            primary_backend_id=route_input.backend_id,
            backup_mode=None,
            backup_backend_id="",
        )

    raise StorageRouteValidationError(f"unsupported storage mode: {route_input.mode}")
