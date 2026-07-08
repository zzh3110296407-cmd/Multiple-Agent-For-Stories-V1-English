from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.memory_pack import (
    SCENE_MEMORY_PACK_VERSION_ID,
    SceneMemoryPack,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.chapter_memory_service import ChapterMemoryService
from app.backend.services.memory_retrieval_service import MemoryRetrievalService
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class SceneMemoryService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        chapter_memory_service: ChapterMemoryService | None = None,
        retrieval_service: MemoryRetrievalService | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.scene_packs_file = self.data_dir / "scene_memory_packs.json"
        self.chapters_file = self.data_dir / "chapters.json"
        self.scenes_file = self.data_dir / "scenes.json"
        self.events_file = self.data_dir / "events.json"
        self.chapter_memory_service = chapter_memory_service or ChapterMemoryService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.retrieval_service = retrieval_service or MemoryRetrievalService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def build_scene_pack(
        self,
        chapter_id: str,
        scene_index: int,
        scene_id: str | None = None,
        scene_goal: str = "",
        scene_location: str = "",
        active_character_ids: list[str] | None = None,
        required_memory_refs: list[str] | None = None,
        include_provisional: bool = False,
        force_refresh: bool = False,
        strict_active_character_ids: bool = False,
    ) -> SceneMemoryPack:
        chapter_id = chapter_id.strip()
        if not chapter_id:
            raise StorageError("SCENE_MEMORY_PACK_CHAPTER_ID_REQUIRED")
        if scene_index < 1:
            raise StorageError("SCENE_MEMORY_PACK_SCENE_INDEX_INVALID")

        existing = self.get_active_scene_pack(chapter_id, scene_index)
        if (
            existing is not None
            and self._strict_active_character_request(existing)
            and not strict_active_character_ids
        ):
            strict_active_character_ids = True
            scene_id = scene_id or existing.scene_id
            if not force_refresh:
                scene_goal = scene_goal or existing.scene_goal
                scene_location = scene_location or existing.scene_location
            active_character_ids = existing.active_character_ids

        resolved = self._resolve_scene_inputs(
            chapter_id=chapter_id,
            scene_index=scene_index,
            scene_id=scene_id,
            scene_goal=scene_goal,
            scene_location=scene_location,
            active_character_ids=active_character_ids or [],
            include_provisional=include_provisional,
            strict_active_character_ids=strict_active_character_ids,
        )
        resolved["required_memory_refs"] = self._unique(
            [str(ref or "") for ref in (required_memory_refs or [])]
        )
        if (
            existing is not None
            and not force_refresh
            and self._same_scene_signature(existing, resolved)
        ):
            return existing

        chapter_pack = self.chapter_memory_service.get_active_chapter_pack(chapter_id)
        if chapter_pack is None:
            chapter_pack = self.chapter_memory_service.build_current_chapter_pack(
                chapter_id,
                force_refresh=False,
            )

        recent_events = self._recent_events_for_scene(chapter_id, scene_index)
        retrieval = self.retrieval_service.retrieve_for_scene(
            chapter_pack=chapter_pack,
            scene_index=scene_index,
            scene_id=resolved["scene_id"],
            scene_goal=resolved["scene_goal"],
            scene_location=resolved["scene_location"],
            active_character_ids=resolved["active_character_ids"],
            recent_events=recent_events,
            required_memory_refs=required_memory_refs or [],
            include_provisional=bool(resolved["include_provisional"]),
        )
        timestamp = utc_now()
        project_id = (
            str(chapter_pack.project_id or "").strip() or self._current_project_id()
        )
        pack = SceneMemoryPack(
            scene_memory_pack_id=self._pack_id("scene_pack", chapter_id, scene_index),
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=resolved["scene_id"] or None,
            scene_index=scene_index,
            status="active",
            chapter_memory_pack_id=chapter_pack.chapter_memory_pack_id,
            scene_goal=resolved["scene_goal"],
            scene_location=resolved["scene_location"],
            active_character_ids=resolved["active_character_ids"],
            must_use_memory_ids=retrieval["must_use_memory_ids"],
            should_use_memory_ids=retrieval["should_use_memory_ids"],
            optional_memory_ids=retrieval["optional_memory_ids"],
            forbidden_or_conflict_memory_ids=retrieval[
                "forbidden_or_conflict_memory_ids"
            ],
            continuity_anchor_memory_ids=retrieval["continuity_anchor_memory_ids"],
            do_not_repeat_memory_ids=retrieval["do_not_repeat_memory_ids"],
            must_use_context=retrieval["must_use_context"],
            should_use_context=retrieval["should_use_context"],
            optional_context=retrieval["optional_context"],
            forbidden_or_conflict_context=retrieval["forbidden_or_conflict_context"],
            continuity_anchor_context=retrieval["continuity_anchor_context"],
            do_not_repeat_context=retrieval["do_not_repeat_context"],
            memory_context_dedupe_report=retrieval["memory_context_dedupe_report"],
            provisional_memory_ids=retrieval["provisional_memory_ids"],
            provisional_dependency_scene_ids=retrieval[
                "provisional_dependency_scene_ids"
            ],
            retrieval_gaps=retrieval["retrieval_gaps"],
            source_query_signature={
                **retrieval["source_query_signature"],
                "include_provisional": bool(resolved["include_provisional"]),
                "strict_active_character_ids": bool(resolved["strict_active_character_ids"]),
                "required_memory_refs": resolved["required_memory_refs"],
                "resolved_scene_inputs": resolved,
            },
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCENE_MEMORY_PACK_VERSION_ID,
        )
        self._persist_pack(pack)
        self._record_m5_retrieval_usage_and_promotions(pack)
        return pack

    def get_active_scene_pack(
        self,
        chapter_id: str,
        scene_index: int,
    ) -> SceneMemoryPack | None:
        packs = self._read_packs()
        candidates = [
            pack
            for pack in packs
            if pack.chapter_id == chapter_id
            and pack.scene_index == scene_index
            and pack.status == "active"
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda pack: pack.updated_at, reverse=True)[0]

    def refresh_scene_pack(
        self,
        chapter_id: str,
        scene_index: int,
    ) -> SceneMemoryPack:
        existing = self.get_active_scene_pack(chapter_id, scene_index)
        if existing is None:
            return self.build_scene_pack(chapter_id, scene_index, force_refresh=True)
        return self.build_scene_pack(
            chapter_id=chapter_id,
            scene_index=scene_index,
            scene_id=existing.scene_id,
            scene_goal=existing.scene_goal,
            scene_location=existing.scene_location,
            active_character_ids=existing.active_character_ids,
            required_memory_refs=self._required_memory_refs(existing),
            include_provisional=self._include_provisional_request(existing),
            force_refresh=True,
            strict_active_character_ids=self._strict_active_character_request(existing),
        )

    def mark_pack_stale(self, chapter_id: str, scene_index: int, reason: str) -> None:
        envelope = self._read_envelope()
        changed = False
        updated_packs: list[dict[str, Any]] = []
        for raw_pack in envelope["packs"]:
            try:
                pack = SceneMemoryPack(**raw_pack)
            except ValidationError:
                updated_packs.append(raw_pack)
                continue
            if (
                pack.chapter_id == chapter_id
                and pack.scene_index == scene_index
                and pack.status == "active"
            ):
                pack.status = "stale"
                pack.updated_at = utc_now()
                pack.retrieval_gaps.append(
                    self.retrieval_service._gap(
                        "stale_pack_source",
                        chapter_id=chapter_id,
                        scene_id=pack.scene_id,
                        character_ids=pack.active_character_ids,
                        message=f"SceneMemoryPack 已标记 stale：{reason}",
                        suggested_action="刷新 SceneMemoryPack 后再继续使用。",
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
            self.repositories.scene_memory_packs.write_envelope(envelope)

    def _persist_pack(self, pack: SceneMemoryPack) -> None:
        envelope = self._read_envelope()
        timestamp = utc_now()
        updated_packs: list[dict[str, Any]] = []
        for raw_pack in envelope["packs"]:
            try:
                existing = SceneMemoryPack(**raw_pack)
            except ValidationError:
                updated_packs.append(raw_pack)
                continue
            if (
                existing.chapter_id == pack.chapter_id
                and existing.scene_index == pack.scene_index
                and existing.status == "active"
            ):
                existing.status = "superseded"
                existing.updated_at = timestamp
                updated_packs.append(model_to_dict(existing))
            else:
                updated_packs.append(raw_pack)
        updated_packs.append(model_to_dict(pack))
        envelope["packs"] = updated_packs
        envelope["updated_at"] = timestamp
        self.repositories.scene_memory_packs.write_envelope(envelope)

    def _record_m5_retrieval_usage_and_promotions(self, pack: SceneMemoryPack) -> None:
        if not pack.active_character_ids:
            return
        from app.backend.services.memory_retrieval_promotion_service import (
            ChapterMemoryPromotionService,
            MemoryRetrievalUsageService,
            TieredMemoryRetrievalPolicyService,
        )

        policy_service = TieredMemoryRetrievalPolicyService(
            store=self.store,
            data_dir=self.data_dir,
        )
        usage_service = MemoryRetrievalUsageService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            policy_service=policy_service,
        )
        usage_service.record_scene_retrieval_usage(pack)
        ChapterMemoryPromotionService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            usage_service=usage_service,
            policy_service=policy_service,
        ).evaluate_chapter_promotions(pack.chapter_id)

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback="local_project",
        )

    def _resolve_scene_inputs(
        self,
        *,
        chapter_id: str,
        scene_index: int,
        scene_id: str | None,
        scene_goal: str,
        scene_location: str,
        active_character_ids: list[str],
        include_provisional: bool,
        strict_active_character_ids: bool = False,
    ) -> dict[str, Any]:
        scene = self._find_scene(chapter_id, scene_index)
        chapter = self._find_chapter(chapter_id)
        resolved_scene_id = str(scene_id or (scene or {}).get("scene_id") or "")
        resolved_goal = str(
            scene_goal
            or (scene or {}).get("goal")
            or (scene or {}).get("synopsis")
            or chapter.get("chapter_goal")
            or chapter.get("summary")
            or ""
        )
        resolved_location = str(
            scene_location
            or (scene or {}).get("location")
            or ""
        )
        if strict_active_character_ids:
            resolved_characters = self._unique(active_character_ids)
        else:
            resolved_characters = self._unique(
                [
                    *active_character_ids,
                    *((scene or {}).get("linked_character_ids") or []),
                    *(chapter.get("participant_character_ids") or []),
                    *(chapter.get("participating_character_ids") or []),
                ]
            )
        return {
            "scene_id": resolved_scene_id,
            "scene_goal": self._short_text(resolved_goal, 240),
            "scene_location": resolved_location,
            "active_character_ids": resolved_characters,
            "include_provisional": include_provisional,
            "strict_active_character_ids": strict_active_character_ids,
        }

    def _same_scene_signature(
        self,
        existing: SceneMemoryPack,
        resolved: dict[str, Any],
    ) -> bool:
        return (
            existing.scene_id == (resolved["scene_id"] or None)
            and existing.scene_goal == resolved["scene_goal"]
            and existing.scene_location == resolved["scene_location"]
            and existing.active_character_ids == resolved["active_character_ids"]
            and self._strict_active_character_request(existing)
            == bool(resolved["strict_active_character_ids"])
            and self._include_provisional_request(existing)
            == bool(resolved["include_provisional"])
            and self._required_memory_refs(existing)
            == self._unique([str(ref or "") for ref in resolved.get("required_memory_refs", [])])
        )

    def _include_provisional_request(self, pack: SceneMemoryPack) -> bool:
        signature = pack.source_query_signature
        if isinstance(signature, dict):
            resolved = signature.get("resolved_scene_inputs")
            if (
                isinstance(resolved, dict)
                and "include_provisional" in resolved
            ):
                return self._signature_bool(resolved["include_provisional"])
            if "include_provisional" in signature:
                return self._signature_bool(signature["include_provisional"])
        return bool(pack.provisional_memory_ids)

    def _strict_active_character_request(self, pack: SceneMemoryPack) -> bool:
        signature = pack.source_query_signature
        if isinstance(signature, dict):
            resolved = signature.get("resolved_scene_inputs")
            if (
                isinstance(resolved, dict)
                and "strict_active_character_ids" in resolved
            ):
                return self._signature_bool(resolved["strict_active_character_ids"])
            if "strict_active_character_ids" in signature:
                return self._signature_bool(signature["strict_active_character_ids"])
        return False

    def _required_memory_refs(self, pack: SceneMemoryPack) -> list[str]:
        report = pack.memory_context_dedupe_report or {}
        refs = report.get("required_memory_refs") if isinstance(report, dict) else []
        if not refs and isinstance(pack.source_query_signature, dict):
            refs = pack.source_query_signature.get("required_memory_refs")
        if not isinstance(refs, list):
            return []
        return self._unique([str(ref or "") for ref in refs])

    def _signature_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)

    def _recent_events_for_scene(
        self,
        chapter_id: str,
        scene_index: int,
    ) -> list[dict[str, Any]]:
        scenes = self.repositories.scenes.list_all()
        events = self.repositories.events.list_all()
        event_by_id = {
            str(event.get("event_id")): event
            for event in events
            if event.get("event_id")
        }
        previous_scene_ids = [
            str(scene.get("scene_id") or "")
            for scene in scenes
            if scene.get("chapter_id") == chapter_id
            and int(scene.get("scene_index") or 0) < scene_index
            and scene.get("status", "") in {"confirmed", "revised", "temporary_confirmed"}
        ]
        selected: list[dict[str, Any]] = []
        for scene in scenes:
            if scene.get("scene_id") not in previous_scene_ids:
                continue
            for event_id in scene.get("event_ids") or []:
                event = event_by_id.get(str(event_id))
                if event:
                    selected.append(event)
        if selected:
            return selected[-5:]
        return [
            event
            for event in events
            if event.get("scene_id") in previous_scene_ids
        ][-5:]

    def _read_packs(self) -> list[SceneMemoryPack]:
        packs: list[SceneMemoryPack] = []
        for raw_pack in self._read_envelope()["packs"]:
            if not isinstance(raw_pack, dict):
                continue
            try:
                packs.append(SceneMemoryPack(**raw_pack))
            except ValidationError as exc:
                raise StorageError("SceneMemoryPack JSON schema is invalid.") from exc
        return packs

    def _read_envelope(self) -> dict[str, Any]:
        return self.repositories.scene_memory_packs.read_envelope()

    def _find_scene(self, chapter_id: str, scene_index: int) -> dict[str, Any] | None:
        for scene in self.repositories.scenes.list_all():
            if (
                scene.get("chapter_id") == chapter_id
                and int(scene.get("scene_index") or 0) == scene_index
            ):
                return scene
        return None

    def _find_chapter(self, chapter_id: str) -> dict[str, Any]:
        for chapter in self.repositories.chapters.list_all():
            if chapter.get("chapter_id") == chapter_id:
                return chapter
        raise StorageError(f"SCENE_MEMORY_PACK_CHAPTER_MISSING: {chapter_id}")

    def _pack_id(self, prefix: str, chapter_id: str, scene_index: int) -> str:
        compact_time = utc_now().replace("-", "").replace(":", "").replace(".", "")
        compact_time = compact_time.replace("+", "_").replace("Z", "")
        return f"{prefix}_{chapter_id}_{scene_index:03d}_{compact_time}_{uuid4().hex[:8]}"

    def _read_list_if_present(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        return [
            dict(item)
            for item in self.store.read_list(path)
            if isinstance(item, dict)
        ]

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

    def _short_text(self, text: str, max_len: int) -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) <= max_len:
            return clean
        return clean[: max_len - 3].rstrip() + "..."
