from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.character import (
    Character,
    CharacterContextBuildRequest,
    CharacterContextItem,
    CharacterContextPreviewResponse,
)
from app.backend.models.memory_pack import MemoryPackSourceRef, SceneMemoryPack
from app.backend.models.relationship import Relationship
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.role_tier_budget_service import RoleTierBudgetService
from app.backend.storage.json_store import JsonStore, StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class CharacterContextBuilder:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        budget_service: RoleTierBudgetService | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.characters_file = self.data_dir / "characters.json"
        self.relationships_file = self.data_dir / "relationships.json"
        self.scene_packs_file = self.data_dir / "scene_memory_packs.json"
        self.budget_service = budget_service or RoleTierBudgetService()

    def build_context(
        self,
        request: CharacterContextBuildRequest,
    ) -> CharacterContextPreviewResponse:
        characters = self._read_characters()
        relationships = self._read_relationships()
        pack = self._resolve_scene_pack(request)
        warnings: list[str] = []
        omitted: list[str] = []
        if pack is None:
            warnings.append("SceneMemoryPack is missing; using conservative character-only context.")
            omitted.append("scene_memory_pack")

        requested_ids = self._unique(request.character_ids)
        if not requested_ids and pack is not None:
            requested_ids = self._unique(pack.active_character_ids)
        if not requested_ids:
            requested_ids = [
                character.character_id
                for character in characters
                if character.status != "archived"
            ]

        refs = self._pack_refs(pack) if pack else []
        items: list[CharacterContextItem] = []
        for character in characters:
            if character.character_id not in requested_ids:
                continue
            if character.status == "archived":
                continue
            character_refs = self._refs_for_character(
                refs=refs,
                character=character,
                relationships=relationships,
            )
            item = self.budget_service.build_context_item(
                character=character,
                relationships=relationships,
                recent_memory_refs=[model_to_dict(ref) for ref in character_refs],
                omitted=omitted,
            )
            items.append(item)

        return CharacterContextPreviewResponse(
            items=items,
            warnings=self._unique(warnings),
            scene_memory_pack_id=pack.scene_memory_pack_id if pack else None,
        )

    def _resolve_scene_pack(
        self,
        request: CharacterContextBuildRequest,
    ) -> SceneMemoryPack | None:
        packs = self._read_scene_packs()
        if request.scene_memory_pack_id:
            for pack in packs:
                if pack.scene_memory_pack_id == request.scene_memory_pack_id:
                    return pack
            return None
        candidates = [
            pack
            for pack in packs
            if pack.status == "active"
            and (
                not request.chapter_id
                or pack.chapter_id == request.chapter_id
            )
            and pack.scene_index == request.scene_index
            and (
                not request.scene_id
                or pack.scene_id == request.scene_id
            )
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda pack: pack.updated_at, reverse=True)[0]

    def _pack_refs(self, pack: SceneMemoryPack) -> list[MemoryPackSourceRef]:
        return self._dedupe_refs(
            [
                *pack.must_use_context,
                *pack.should_use_context,
                *pack.optional_context,
            ]
        )

    def _refs_for_character(
        self,
        refs: list[MemoryPackSourceRef],
        character: Character,
        relationships: list[Relationship],
    ) -> list[MemoryPackSourceRef]:
        relationship_ids = {
            relationship.relationship_id
            for relationship in relationships
            if character.character_id in {relationship.source_id, relationship.target_id}
        }
        character_terms = {
            character.character_id.casefold(),
            character.name.casefold(),
            *[item.casefold() for item in character.profile.traits],
        }
        matched: list[MemoryPackSourceRef] = []
        for ref in refs:
            source_type = ref.source_object_type.casefold()
            source_id = ref.source_object_id.casefold()
            keywords = {keyword.casefold() for keyword in ref.keywords}
            summary = ref.summary.casefold()
            if source_type == "character" and source_id == character.character_id.casefold():
                matched.append(ref)
                continue
            if source_type == "relationship" and ref.source_object_id in relationship_ids:
                matched.append(ref)
                continue
            if keywords.intersection(character_terms):
                matched.append(ref)
                continue
            if any(term and term in summary for term in character_terms):
                matched.append(ref)
        return self._dedupe_refs(matched)

    def _read_characters(self) -> list[Character]:
        try:
            return [
                Character(**item)
                for item in self.repositories.characters.list_all()
                if isinstance(item, dict)
            ]
        except (TypeError, ValidationError) as exc:
            raise StorageError(f"JSON schema is invalid: {self.characters_file}") from exc

    def _read_relationships(self) -> list[Relationship]:
        try:
            return [
                Relationship(**item)
                for item in self.repositories.relationships.list_all()
                if isinstance(item, dict)
            ]
        except (TypeError, ValidationError) as exc:
            raise StorageError(f"JSON schema is invalid: {self.relationships_file}") from exc

    def _read_scene_packs(self) -> list[SceneMemoryPack]:
        try:
            return [
                SceneMemoryPack(**item)
                for item in self.repositories.scene_memory_packs.list_packs()
                if isinstance(item, dict)
            ]
        except (TypeError, ValidationError) as exc:
            raise StorageError(f"JSON schema is invalid: {self.scene_packs_file}") from exc

    def _dedupe_refs(self, refs: list[MemoryPackSourceRef]) -> list[MemoryPackSourceRef]:
        result: list[MemoryPackSourceRef] = []
        seen: set[str] = set()
        for ref in refs:
            if not ref.memory_id or ref.memory_id in seen:
                continue
            seen.add(ref.memory_id)
            result.append(ref)
        return result

    def _unique(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = str(value or "").strip()
            if not clean:
                continue
            key = clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(clean)
        return result
