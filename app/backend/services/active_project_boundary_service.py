from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.services.active_project_story_data import (
    active_project_story_data_dir,
    active_project_without_story_data,
)
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
ACTIVE_PROJECT_SELECTION_FILE = "active_project_selection.json"


class ActiveProjectStoryDataBlocked(StorageError):
    """Raised when a normal active project would otherwise read legacy story data."""


class ActiveProjectBoundaryService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.active_project_selection_file = self.data_dir / ACTIVE_PROJECT_SELECTION_FILE
        self.project_file = self.data_dir / "project.json"

    def ensure_story_workspace_available(self) -> Path:
        story_data_dir = active_project_story_data_dir(self.store, self.data_dir)
        if story_data_dir is not None:
            return story_data_dir
        project_id = self.non_legacy_active_project_id_without_story_scope()
        if not project_id:
            return self.data_dir
        raise ActiveProjectStoryDataBlocked(
            "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT: "
            f"Story workspace data is not available for active project {project_id}."
        )

    def non_legacy_active_project_id_without_story_scope(self) -> str:
        return active_project_without_story_data(self.store, self.data_dir)

    def _read_active_selection(self) -> dict[str, Any]:
        if not self.store.exists(self.active_project_selection_file):
            return {}
        try:
            payload = self.store.read(self.active_project_selection_file)
        except StorageError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _local_story_project_id(self) -> str:
        if not self.store.exists(self.project_file):
            return ""
        try:
            payload = self.store.read(self.project_file)
        except StorageError:
            return ""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("project_id") or "")
