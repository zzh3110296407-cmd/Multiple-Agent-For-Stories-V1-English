from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.character import (
    Character,
    CharacterArcState,
    CharacterContextBudget,
    CharacterCurrentState,
    CharacterMemorySummary,
    CharacterProfile,
    RoleArchiveRequest,
    RoleCreateRequest,
    RolePatchRequest,
    RoleTierChangeRequest,
)
from app.backend.models.decision import Decision
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.character_major_change_policy import a_tier_major_patch_paths
from app.backend.services.character_service import LOCAL_PROJECT_ID, now_iso
from app.backend.storage.json_store import JsonStore, StorageError


ROLE_VERSION_ID = "phase2_m4_role_v1"


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def copy_model(model: BaseModel, **updates: Any):
    if hasattr(model, "model_copy"):
        return model.model_copy(update=updates, deep=True)
    return model.copy(update=updates, deep=True)


class RoleManagementService:
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
        self.characters_file = self.data_dir / "characters.json"
        self.story_bible_file = self.data_dir / "story_bible.json"
        self.decisions_file = self.data_dir / "decisions.json"

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def list_roles(
        self,
        tier: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
    ) -> list[Character]:
        roles = self._read_characters()
        if tier and tier.upper() != "ALL":
            roles = [role for role in roles if role.tier == tier.upper()]
        if status:
            roles = [role for role in roles if role.status == status]
        elif not include_archived:
            roles = [role for role in roles if role.status != "archived"]
        return sorted(roles, key=lambda role: (role.tier, role.name.casefold()))

    def get_role(self, character_id: str) -> Character:
        return self._find_role(character_id)

    def create_role(self, request: RoleCreateRequest) -> tuple[Character, Decision]:
        timestamp = now_iso()
        character_id = self._next_role_id(request.tier)
        role = Character(
            character_id=character_id,
            project_id=self._current_project_id(),
            name=request.name.strip(),
            tier=request.tier,
            role=request.role.strip() or "npc",
            profile=CharacterProfile(**request.profile),
            current_state=CharacterCurrentState(**request.current_state),
            memory_summary=CharacterMemorySummary(**request.memory_summary),
            status="confirmed",
            source="role_management",
            version_id=ROLE_VERSION_ID,
            created_at=timestamp,
            updated_at=timestamp,
        )
        if not role.name:
            raise StorageError("ROLE_NAME_REQUIRED")
        characters = self._read_characters()
        characters.append(role)
        self._write_characters(characters)
        decision = self._append_decision(
            decision_type="create",
            target_type="role",
            target_id=role.character_id,
            user_input=request.user_input
            or f"创建 {role.tier}-tier 角色：{role.name}",
        )
        return role, decision

    def patch_role(
        self,
        character_id: str,
        request: RolePatchRequest,
    ) -> tuple[Character, Decision]:
        characters = self._read_characters()
        role = self._find_role(character_id, characters)
        self._assert_patch_allowed(role, request)
        updates: dict[str, Any] = {"updated_at": now_iso()}
        if request.name is not None:
            name = request.name.strip()
            if not name:
                raise StorageError("ROLE_NAME_REQUIRED")
            updates["name"] = name
        if request.role is not None:
            updates["role"] = request.role.strip()
        if request.profile:
            updates["profile"] = CharacterProfile(
                **self._deep_merge(model_to_dict(role.profile), request.profile)
            )
        if request.current_state:
            updates["current_state"] = CharacterCurrentState(
                **self._deep_merge(model_to_dict(role.current_state), request.current_state)
            )
        if request.arc_state:
            updates["arc_state"] = CharacterArcState(
                **self._deep_merge(model_to_dict(role.arc_state), request.arc_state)
            )
        if request.memory_summary:
            updates["memory_summary"] = CharacterMemorySummary(
                **self._deep_merge(model_to_dict(role.memory_summary), request.memory_summary)
            )
        if request.context_budget:
            updates["context_budget"] = CharacterContextBudget(
                **self._deep_merge(model_to_dict(role.context_budget), request.context_budget)
            )
        updated = copy_model(role, **updates)
        self._replace_character(characters, updated)
        decision = self._append_decision(
            decision_type="patch",
            target_type="role",
            target_id=updated.character_id,
            user_input=request.user_input
            or f"更新角色基础信息：{updated.name}",
        )
        return updated, decision

    def change_tier(
        self,
        character_id: str,
        request: RoleTierChangeRequest,
    ) -> tuple[Character, Decision]:
        characters = self._read_characters()
        role = self._find_role(character_id, characters)
        if role.tier == request.tier:
            decision = self._append_decision(
                decision_type="change_tier",
                target_type="role",
                target_id=role.character_id,
                user_input=request.user_input
                or f"确认角色 {role.name} 保持 {role.tier}-tier。",
            )
            return role, decision
        if role.tier == "A" and request.tier != "A" and self._is_main_cast_role(role.character_id):
            raise StorageError("MAIN_CAST_A_TIER_CANNOT_BE_DOWNGRADED")
        updated = copy_model(
            role,
            tier=request.tier,
            updated_at=now_iso(),
        )
        self._replace_character(characters, updated)
        decision = self._append_decision(
            decision_type="change_tier",
            target_type="role",
            target_id=updated.character_id,
            user_input=request.user_input
            or f"将角色 {updated.name} 从 {role.tier}-tier 调整为 {updated.tier}-tier。",
        )
        return updated, decision

    def archive_role(
        self,
        character_id: str,
        request: RoleArchiveRequest,
    ) -> tuple[Character, Decision]:
        characters = self._read_characters()
        role = self._find_role(character_id, characters)
        if role.tier == "A" and self._is_main_cast_role(role.character_id):
            raise StorageError("MAIN_CAST_A_TIER_CANNOT_BE_ARCHIVED")
        timestamp = now_iso()
        updated = copy_model(
            role,
            status="archived",
            archived_at=timestamp,
            updated_at=timestamp,
        )
        self._replace_character(characters, updated)
        decision = self._append_decision(
            decision_type="archive",
            target_type="role",
            target_id=updated.character_id,
            user_input=request.user_input
            or request.reason
            or f"归档角色：{updated.name}",
        )
        return updated, decision

    def _read_characters(self) -> list[Character]:
        try:
            return [
                Character(**item)
                for item in self.repositories.characters.list_all()
                if isinstance(item, dict)
            ]
        except (TypeError, ValidationError) as exc:
            raise StorageError(f"JSON schema is invalid: {self.characters_file}") from exc

    def _write_characters(self, characters: list[Character]) -> None:
        self.repositories.characters.write_all(
            [model_to_dict(character) for character in characters],
        )

    def _find_role(
        self,
        character_id: str,
        characters: list[Character] | None = None,
    ) -> Character:
        for role in characters or self._read_characters():
            if role.character_id == character_id:
                return role
        raise StorageError(f"ROLE_NOT_FOUND: {character_id}")

    def _replace_character(
        self,
        characters: list[Character],
        updated: Character,
    ) -> None:
        replaced = False
        result: list[Character] = []
        for character in characters:
            if character.character_id == updated.character_id:
                result.append(updated)
                replaced = True
            else:
                result.append(character)
        if not replaced:
            raise StorageError(f"ROLE_NOT_FOUND: {updated.character_id}")
        self._write_characters(result)

    def _next_role_id(self, tier: str) -> str:
        existing_ids = {role.character_id for role in self._read_characters()}
        for _ in range(20):
            candidate = f"char_{tier.lower()}_{uuid4().hex[:8]}"
            if candidate not in existing_ids:
                return candidate
        raise StorageError("ROLE_ID_GENERATION_FAILED")

    def _assert_patch_allowed(self, role: Character, request: RolePatchRequest) -> None:
        if role.tier != "A":
            return
        patch = self._patch_payload(request)
        blocked_paths = a_tier_major_patch_paths(patch)
        if blocked_paths:
            joined = ",".join(blocked_paths)
            raise StorageError(
                f"A_TIER_MAJOR_PATCH_REQUIRES_PENDING_CHANGE:{joined}"
            )

    def _patch_payload(self, request: RolePatchRequest) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        if request.profile:
            patch["profile"] = request.profile
        if request.current_state:
            patch["current_state"] = request.current_state
        if request.arc_state:
            patch["arc_state"] = request.arc_state
        if request.memory_summary:
            patch["memory_summary"] = request.memory_summary
        if request.context_budget:
            patch["context_budget"] = request.context_budget
        return patch

    def _is_main_cast_role(self, character_id: str) -> bool:
        if not self.store.exists(self.story_bible_file):
            return False
        story_bible = self.store.read(self.story_bible_file)
        return character_id in set(story_bible.get("main_character_ids") or [])

    def _append_decision(
        self,
        decision_type: str,
        target_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decisions = self.repositories.decisions.list_all()
        decision = Decision(
            decision_id=self._next_decision_id(target_type, target_id),
            decision_type=decision_type,
            target_type=target_type,
            target_id=target_id,
            user_input=user_input,
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.repositories.decisions.write_all(decisions)
        return decision

    def _next_decision_id(self, target_type: str, target_id: str) -> str:
        return f"decision_{target_type}_{target_id}_{uuid4().hex[:8]}"

    def _deep_merge(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        result = dict(base)
        for key, value in patch.items():
            if (
                isinstance(value, dict)
                and isinstance(result.get(key), dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
