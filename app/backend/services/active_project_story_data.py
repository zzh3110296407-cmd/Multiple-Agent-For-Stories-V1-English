import re
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
ACTIVE_PROJECT_SELECTION_FILE = "active_project_selection.json"


def safe_project_dir_name(project_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", project_id or "").strip("._-")
    return cleaned[:96] or "project"


def story_data_root(base_data_dir: Path | None = None) -> Path:
    base = base_data_dir or settings.data_dir
    return base.parent / "projects"


def story_data_dir_for_project(project_id: str, base_data_dir: Path | None = None) -> Path:
    base = base_data_dir or settings.data_dir
    if project_id == LOCAL_PROJECT_ID:
        return base
    return story_data_root(base) / safe_project_dir_name(project_id)


def read_active_project_selection(
    store: JsonStore,
    base_data_dir: Path | None = None,
) -> dict[str, Any]:
    base = base_data_dir or settings.data_dir
    selection_file = base / ACTIVE_PROJECT_SELECTION_FILE
    if not store.exists(selection_file):
        return {}
    try:
        payload = store.read(selection_file)
    except StorageError:
        return {}
    return payload if isinstance(payload, dict) else {}


def active_project_id(store: JsonStore, base_data_dir: Path | None = None) -> str:
    selection = read_active_project_selection(store, base_data_dir)
    return str(selection.get("project_id") or "").strip()


def story_data_dir_has_project(
    store: JsonStore,
    story_data_dir: Path,
    project_id: str,
) -> bool:
    project_file = story_data_dir / "project.json"
    if not store.exists(project_file):
        return False
    try:
        payload = store.read(project_file)
    except StorageError:
        return False
    if not isinstance(payload, dict):
        return False
    return str(payload.get("project_id") or "") == project_id


def current_story_workspace_project_id(
    store: JsonStore,
    story_data_dir: Path,
    *,
    fallback: str = LOCAL_PROJECT_ID,
) -> str:
    for file_name in ("project.json", "story_bible.json", "world_canvas.json"):
        path = story_data_dir / file_name
        if not store.exists(path):
            continue
        try:
            payload = store.read(path)
        except StorageError:
            continue
        if not isinstance(payload, dict):
            continue
        project_id = str(payload.get("project_id") or "").strip()
        if project_id:
            return project_id
    return fallback


def active_project_story_data_dir(
    store: JsonStore,
    base_data_dir: Path | None = None,
) -> Path | None:
    base = base_data_dir or settings.data_dir
    project_id = active_project_id(store, base)
    if not project_id or project_id == LOCAL_PROJECT_ID:
        return base
    candidate = story_data_dir_for_project(project_id, base)
    if story_data_dir_has_project(store, candidate, project_id):
        return candidate
    return None


def active_project_without_story_data(
    store: JsonStore,
    base_data_dir: Path | None = None,
) -> str:
    base = base_data_dir or settings.data_dir
    project_id = active_project_id(store, base)
    if not project_id or project_id == LOCAL_PROJECT_ID:
        return ""
    if active_project_story_data_dir(store, base) is not None:
        return ""
    return project_id
