from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.memory_pack import (
    CHAPTER_MEMORY_PACK_VERSION_ID,
    ChapterMemoryPack,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.memory_retrieval_service import MemoryRetrievalService
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ChapterMemoryService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        retrieval_service: MemoryRetrievalService | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.chapter_packs_file = self.data_dir / "chapter_memory_packs.json"
        self.chapters_file = self.data_dir / "chapters.json"
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.world_canvas_file = self.data_dir / "world_canvas.json"
        self.characters_file = self.data_dir / "characters.json"
        self.relationships_file = self.data_dir / "relationships.json"
        self.events_file = self.data_dir / "events.json"
        self.memory_indexes_file = self.data_dir / "memory_indexes.json"
        self.retrieval_service = retrieval_service or MemoryRetrievalService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def build_current_chapter_pack(
        self,
        chapter_id: str,
        force_refresh: bool = False,
    ) -> ChapterMemoryPack:
        chapter_id = chapter_id.strip()
        if not chapter_id:
            raise StorageError("CHAPTER_MEMORY_PACK_CHAPTER_ID_REQUIRED")
        existing = self.get_active_chapter_pack(chapter_id)
        if existing is not None and not force_refresh:
            return existing

        chapter = self._find_chapter(chapter_id)
        framework_package = self._read_dict_if_present(self.framework_package_file)
        framework = self._find_chapter_framework(framework_package, chapter)
        world_canvas = self._read_dict_if_present(self.world_canvas_file)
        characters = self.repositories.characters.list_all()
        relationships = self.repositories.relationships.list_all()
        events = self.repositories.events.list_all()
        retrieval = self.retrieval_service.retrieve_for_chapter(
            chapter=chapter,
            framework=framework,
            characters=characters,
            relationships=relationships,
            events=events,
            world_canvas=world_canvas,
        )
        timestamp = utc_now()
        pack = ChapterMemoryPack(
            chapter_memory_pack_id=self._pack_id("chapter_pack", chapter_id),
            project_id=str(chapter.get("project_id") or "local_project"),
            chapter_id=chapter_id,
            status="active",
            based_on_chapter_version_id=str(chapter.get("version_id") or ""),
            based_on_framework_version_id=self._framework_version(
                framework_package,
                framework,
            ),
            based_on_memory_index_version_id=self._memory_index_version(),
            current_chapter_goal=str(
                chapter.get("chapter_goal")
                or chapter.get("summary")
                or chapter.get("title")
                or ""
            ),
            current_main_conflict=str(chapter.get("main_conflict") or ""),
            included_memory_ids=retrieval["included_memory_ids"],
            world_context=retrieval["world_context"],
            character_context=retrieval["character_context"],
            relationship_context=retrieval["relationship_context"],
            event_context=retrieval["event_context"],
            framework_context=retrieval["framework_context"],
            retrieval_gaps=retrieval["retrieval_gaps"],
            retrieval_summary=self._retrieval_summary(retrieval),
            source_query_signature=retrieval["source_query_signature"],
            created_at=timestamp,
            updated_at=timestamp,
            version_id=CHAPTER_MEMORY_PACK_VERSION_ID,
        )
        self._persist_pack(pack)
        return pack

    def get_active_chapter_pack(self, chapter_id: str) -> ChapterMemoryPack | None:
        packs = self._read_packs()
        candidates = [
            pack
            for pack in packs
            if pack.chapter_id == chapter_id and pack.status == "active"
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda pack: pack.updated_at, reverse=True)[0]

    def refresh_chapter_pack(self, chapter_id: str) -> ChapterMemoryPack:
        return self.build_current_chapter_pack(chapter_id, force_refresh=True)

    def mark_pack_stale(self, chapter_id: str, reason: str) -> None:
        envelope = self._read_envelope()
        changed = False
        updated_packs: list[dict[str, Any]] = []
        for raw_pack in envelope["packs"]:
            try:
                pack = ChapterMemoryPack(**raw_pack)
            except ValidationError:
                updated_packs.append(raw_pack)
                continue
            if pack.chapter_id == chapter_id and pack.status == "active":
                pack.status = "stale"
                pack.updated_at = utc_now()
                pack.retrieval_gaps.append(
                    self.retrieval_service._gap(
                        "stale_pack_source",
                        chapter_id=chapter_id,
                        message=f"ChapterMemoryPack 已标记 stale：{reason}",
                        suggested_action="刷新 ChapterMemoryPack 后再继续使用。",
                        severity="warning",
                    )
                )
                changed = True
                updated_packs.append(model_to_dict(pack))
            else:
                updated_packs.append(raw_pack)
        if changed:
            envelope["packs"] = updated_packs
            envelope["updated_at"] = utc_now()
            self.repositories.chapter_memory_packs.write_envelope(envelope)

    def _persist_pack(self, pack: ChapterMemoryPack) -> None:
        envelope = self._read_envelope()
        timestamp = utc_now()
        updated_packs: list[dict[str, Any]] = []
        for raw_pack in envelope["packs"]:
            try:
                existing = ChapterMemoryPack(**raw_pack)
            except ValidationError:
                updated_packs.append(raw_pack)
                continue
            if existing.chapter_id == pack.chapter_id and existing.status == "active":
                existing.status = "superseded"
                existing.updated_at = timestamp
                updated_packs.append(model_to_dict(existing))
            else:
                updated_packs.append(raw_pack)
        updated_packs.append(model_to_dict(pack))
        envelope["packs"] = updated_packs
        envelope["updated_at"] = timestamp
        self.repositories.chapter_memory_packs.write_envelope(envelope)

    def _read_packs(self) -> list[ChapterMemoryPack]:
        packs: list[ChapterMemoryPack] = []
        for raw_pack in self._read_envelope()["packs"]:
            if not isinstance(raw_pack, dict):
                continue
            try:
                packs.append(ChapterMemoryPack(**raw_pack))
            except ValidationError as exc:
                raise StorageError("ChapterMemoryPack JSON schema is invalid.") from exc
        return packs

    def _read_envelope(self) -> dict[str, Any]:
        return self.repositories.chapter_memory_packs.read_envelope()

    def _find_chapter(self, chapter_id: str) -> dict[str, Any]:
        for chapter in self.repositories.chapters.list_all():
            if chapter.get("chapter_id") == chapter_id:
                return chapter
        raise StorageError(f"CHAPTER_MEMORY_PACK_CHAPTER_MISSING: {chapter_id}")

    def _find_chapter_framework(
        self,
        framework_package: dict[str, Any],
        chapter: dict[str, Any],
    ) -> dict[str, Any]:
        chapter_framework_id = str(chapter.get("chapter_framework_id") or "")
        chapter_id = str(chapter.get("chapter_id") or "")
        chapter_index = int(chapter.get("chapter_index") or 0)
        for framework in framework_package.get("built_chapter_frameworks") or []:
            if chapter_framework_id:
                if framework.get("chapter_framework_id") == chapter_framework_id:
                    return framework
                continue
            if chapter_index and int(framework.get("chapter_index") or 0) == chapter_index:
                return framework
            if chapter_id and framework.get("chapter_id") == chapter_id:
                return framework
        return {}

    def _framework_version(
        self,
        package: dict[str, Any],
        framework: dict[str, Any],
    ) -> str:
        values = [
            str(package.get("version_id") or ""),
            str(framework.get("chapter_framework_id") or ""),
            str(framework.get("updated_at") or ""),
        ]
        return ":".join(value for value in values if value)

    def _memory_index_version(self) -> str:
        if not self.store.exists(self.memory_indexes_file):
            return "computed:memory_records.json"
        data = self.store.read(self.memory_indexes_file)
        metadata = data.get("metadata") or {}
        return ":".join(
            value
            for value in [
                str(metadata.get("schema_version") or ""),
                str(metadata.get("built_at") or ""),
            ]
            if value
        ) or "computed:memory_records.json"

    def _retrieval_summary(self, retrieval: dict[str, Any]) -> str:
        return (
            "ChapterMemoryPack 已收集 "
            f"{len(retrieval['included_memory_ids'])} 条轻量记忆引用，"
            f"发现 {len(retrieval['retrieval_gaps'])} 个 retrieval gap。"
        )

    def _pack_id(self, prefix: str, chapter_id: str) -> str:
        compact_time = utc_now().replace("-", "").replace(":", "").replace(".", "")
        compact_time = compact_time.replace("+", "_").replace("Z", "")
        return f"{prefix}_{chapter_id}_{compact_time}_{uuid4().hex[:8]}"

    def _read_dict_if_present(self, path: Path) -> dict[str, Any]:
        if not self.store.exists(path):
            return {}
        return self.store.read(path)

    def _read_list_if_present(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        return [
            dict(item)
            for item in self.store.read_list(path)
            if isinstance(item, dict)
        ]
