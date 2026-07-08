from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.backend.core.config import settings
from app.backend.models.character import Character
from app.backend.repositories import RepositoryBundle, create_repositories
from app.backend.services.runtime_role_eligibility_service import (
    RuntimeRoleEligibilityService,
)
from app.backend.storage.json_store import JsonStore, StorageError


class ChapterRoleInputBundle(BaseModel):
    main_cast: list[Character] = Field(default_factory=list)
    supporting_roles: list[Character] = Field(default_factory=list)
    scene_only_role_counts: dict[str, int] = Field(default_factory=dict)
    cd_function_need_seed_hints: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChapterRoleInputBuilderService:
    """Builds chapter-level role inputs from the M1 runtime eligibility contract."""

    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        eligibility_service: RuntimeRoleEligibilityService | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.characters_file = self.data_dir / "characters.json"
        self.eligibility_service = eligibility_service or RuntimeRoleEligibilityService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def build_chapter_role_inputs(
        self,
        project_id: str | None = None,
    ) -> ChapterRoleInputBundle:
        eligibility = self.eligibility_service.build_report(project_id=project_id)
        characters = self._read_characters()
        character_by_id = {character.character_id: character for character in characters}

        main_cast = [
            character_by_id[character_id]
            for character_id in eligibility.confirmed_a_ids
            if character_id in character_by_id
        ]
        supporting_roles = [
            character_by_id[character_id]
            for character_id in eligibility.confirmed_b_ids
            if character_id in character_by_id
        ]
        scene_only_role_counts = {
            "C": len(eligibility.confirmed_c_ids),
            "D": len(eligibility.confirmed_d_ids),
        }
        return ChapterRoleInputBundle(
            main_cast=main_cast,
            supporting_roles=supporting_roles,
            scene_only_role_counts=scene_only_role_counts,
            cd_function_need_seed_hints=self._build_cd_seed_hints(scene_only_role_counts),
            warnings=[],
        )

    def _read_characters(self) -> list[Character]:
        data = self.repositories.characters.list_all()
        try:
            return [Character(**item) for item in data if isinstance(item, dict)]
        except ValidationError as exc:
            raise StorageError("Character repository schema is invalid.") from exc

    def _build_cd_seed_hints(
        self,
        scene_only_role_counts: dict[str, int],
    ) -> list[dict[str, Any]]:
        hints: list[dict[str, Any]] = []
        if scene_only_role_counts.get("C", 0) > 0:
            hints.append(
                {
                    "tier_preference": "C",
                    "allowed_use": "chapter_function_need_only",
                    "context_policy": "Do not include concrete C-tier ids or detailed character context in ChapterAgent output.",
                }
            )
        if scene_only_role_counts.get("D", 0) > 0:
            hints.append(
                {
                    "tier_preference": "D",
                    "allowed_use": "chapter_function_need_only",
                    "context_policy": "Do not include concrete D-tier ids or detailed character context in ChapterAgent output.",
                }
            )
        return hints
