from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.backend.core.config import STORAGE_MODE_POSTGRES_PRIMARY, settings
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    active_project_id,
    story_data_dir_for_project,
)
from app.backend.storage.json_store import JsonStore, StorageError


PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


class RuntimeProjectMappingError(StorageError):
    """Raised when runtime repositories cannot be safely scoped to a project."""


@dataclass(frozen=True)
class RuntimeProjectMapping:
    project_id: str
    source: str
    storage_mode: str
    repository_data_dir: Path
    compatibility_selection_used: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def validate_runtime_project_id(project_id: str) -> str:
    cleaned = str(project_id or "").strip()
    if not cleaned:
        raise RuntimeProjectMappingError("Runtime project id is required.")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise RuntimeProjectMappingError("Runtime project id must not be path-like.")
    if not PROJECT_ID_PATTERN.fullmatch(cleaned):
        raise RuntimeProjectMappingError("Runtime project id contains unsupported characters.")
    return cleaned


def runtime_repository_data_dir(
    project_id: str,
    *,
    base_data_dir: Path | None = None,
) -> Path:
    validated_project_id = validate_runtime_project_id(project_id)
    if settings.storage_mode == STORAGE_MODE_POSTGRES_PRIMARY:
        return Path(validated_project_id)
    return story_data_dir_for_project(validated_project_id, base_data_dir)


def resolve_runtime_project_mapping(
    *,
    explicit_project_id: str = "",
    store: Any | None = None,
    base_data_dir: Path | None = None,
) -> RuntimeProjectMapping:
    warnings: list[str] = []
    source = "explicit_project_id"
    selected_project_id = str(explicit_project_id or "").strip()

    if not selected_project_id:
        active_store = store or JsonStore()
        selected_project_id = active_project_id(active_store, base_data_dir)
        source = "active_project_selection"

    if not selected_project_id:
        raise RuntimeProjectMappingError(
            "Runtime project selection is required before creating story repositories."
        )

    validated_project_id = validate_runtime_project_id(selected_project_id)
    repository_data_dir = runtime_repository_data_dir(
        validated_project_id,
        base_data_dir=base_data_dir,
    )
    if settings.storage_mode == STORAGE_MODE_POSTGRES_PRIMARY and source == "active_project_selection":
        warnings.append("postgres_primary uses active project selection only as setup/admin compatibility metadata.")

    return RuntimeProjectMapping(
        project_id=validated_project_id,
        source=source,
        storage_mode=settings.storage_mode,
        repository_data_dir=repository_data_dir,
        compatibility_selection_used=source == "active_project_selection",
        warnings=tuple(warnings),
    )


def create_runtime_project_repositories(
    *,
    mapping: RuntimeProjectMapping | None = None,
    explicit_project_id: str = "",
    store: Any | None = None,
    base_data_dir: Path | None = None,
) -> RepositoryBundle:
    active_mapping = mapping or resolve_runtime_project_mapping(
        explicit_project_id=explicit_project_id,
        store=store,
        base_data_dir=base_data_dir,
    )
    return create_repositories(data_dir=active_mapping.repository_data_dir)
