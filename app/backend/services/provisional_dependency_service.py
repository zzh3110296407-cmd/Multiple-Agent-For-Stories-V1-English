from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.memory_pack import SceneMemoryPack
from app.backend.models.scene import Scene
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ProvisionalDependencyService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )

    def dependencies_from_scene_pack(
        self,
        scene_pack: SceneMemoryPack | dict[str, Any] | None,
    ) -> dict[str, list[str]]:
        if scene_pack is None:
            return {
                "depends_on_provisional_scene_ids": [],
                "depends_on_provisional_memory_ids": [],
            }
        if isinstance(scene_pack, SceneMemoryPack):
            pack = scene_pack
        else:
            try:
                pack = SceneMemoryPack(**scene_pack)
            except ValidationError as exc:
                raise StorageError("SceneMemoryPack JSON schema is invalid.") from exc
        return {
            "depends_on_provisional_scene_ids": self._unique(
                pack.provisional_dependency_scene_ids
            ),
            "depends_on_provisional_memory_ids": self._unique(
                pack.provisional_memory_ids
            ),
        }

    def mark_dependents_for_recheck(
        self,
        *,
        source_scene_id: str,
        source_memory_ids: list[str] | None = None,
        reason: str,
        status: str = "continuity_recheck",
    ) -> list[Scene]:
        source_scene_id = str(source_scene_id or "").strip()
        source_memory_set = {
            str(memory_id or "").strip()
            for memory_id in source_memory_ids or []
            if str(memory_id or "").strip()
        }
        if not source_scene_id and not source_memory_set:
            return []

        changed: list[Scene] = []
        updated_records: list[dict[str, Any]] = []
        timestamp = utc_now()
        for item in self.repositories.scenes.list_all():
            if not isinstance(item, dict):
                continue
            try:
                scene = Scene(**item)
            except ValidationError as exc:
                raise StorageError("Scene JSON schema is invalid.") from exc
            if scene.scene_id == source_scene_id:
                updated_records.append(item)
                continue
            scene_match = (
                source_scene_id
                and source_scene_id in scene.depends_on_provisional_scene_ids
            )
            memory_match = bool(
                source_memory_set.intersection(scene.depends_on_provisional_memory_ids)
            )
            if scene_match or memory_match:
                updated = Scene(
                    **{
                        **model_to_dict(scene),
                        "status": status,
                        "needs_review_reason": reason,
                        "updated_at": timestamp,
                    }
                )
                changed.append(updated)
                updated_records.append(model_to_dict(updated))
            else:
                updated_records.append(item)
        if changed:
            self.repositories.scenes.write_all(updated_records)
        return changed

    def _unique(self, values: list[Any]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result
