from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.character import (
    Character,
    PendingCharacterStateChange,
    ProposedCharacterStateChange,
)
from app.backend.models.decision import Decision
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.character_major_change_policy import (
    a_tier_change_requires_confirmation,
)
from app.backend.services.character_service import LOCAL_PROJECT_ID, now_iso
from app.backend.storage.json_store import JsonStore, StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def copy_model(model: BaseModel, **updates: Any):
    if hasattr(model, "model_copy"):
        return model.model_copy(update=updates, deep=True)
    return model.copy(update=updates, deep=True)


class CharacterStateUpdateService:
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
        self.pending_changes_file = self.data_dir / "pending_character_state_changes.json"
        self.decisions_file = self.data_dir / "decisions.json"

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def list_pending(self) -> list[PendingCharacterStateChange]:
        return [
            change
            for change in self._read_changes()
            if change.status == "pending"
        ]

    def propose_change(
        self,
        proposed: ProposedCharacterStateChange,
    ) -> tuple[PendingCharacterStateChange, Character | None, Decision | None]:
        character = self._find_character(proposed.character_id)
        impact_level = (
            "major"
            if self._requires_pending_confirmation(character, proposed)
            else proposed.impact_level
        )
        timestamp = now_iso()
        change = PendingCharacterStateChange(
            change_id=self._next_change_id(character.character_id),
            project_id=self._current_project_id(),
            character_id=character.character_id,
            character_name=character.name,
            tier=character.tier,
            source_scene_id=proposed.source_scene_id,
            source_event_id=proposed.source_event_id,
            source_memory_ids=proposed.source_memory_ids,
            change_type=proposed.change_type,
            impact_level=impact_level,
            status="pending" if character.tier == "A" and impact_level == "major" else "confirmed",
            summary=proposed.summary or "角色长期状态变更。",
            reason=proposed.reason or self._default_reason(character, proposed, impact_level),
            proposed_patch=proposed.proposed_patch,
            created_at=timestamp,
            updated_at=timestamp,
            decided_at="" if character.tier == "A" and impact_level == "major" else timestamp,
        )
        changes = self._read_changes()
        if change.status == "pending":
            changes.append(change)
            self._write_changes(changes)
            return change, None, None

        updated_character = self._apply_patch(character, proposed.proposed_patch)
        decision = self._append_decision(
            decision_type="confirm",
            target_type="character_state_change",
            target_id=change.change_id,
            user_input=f"自动确认非 A-tier 或 minor 角色状态变更：{change.summary}",
        )
        change.decision_id = decision.decision_id
        changes.append(change)
        self._write_changes(changes)
        return change, updated_character, decision

    def confirm_change(
        self,
        change_id: str,
        user_input: str = "",
    ) -> tuple[PendingCharacterStateChange, Character, Decision]:
        changes = self._read_changes()
        change = self._find_change(change_id, changes)
        if change.status != "pending":
            raise StorageError("CHARACTER_STATE_CHANGE_NOT_PENDING")
        character = self._find_character(change.character_id)
        updated_character = self._apply_patch(character, change.proposed_patch)
        decision = self._append_decision(
            decision_type="confirm",
            target_type="character_state_change",
            target_id=change.change_id,
            user_input=user_input or f"确认 A-tier 角色重大状态变更：{change.summary}",
        )
        timestamp = now_iso()
        updated_change = copy_model(
            change,
            status="confirmed",
            updated_at=timestamp,
            decided_at=timestamp,
            decision_id=decision.decision_id,
        )
        self._replace_change(changes, updated_change)
        return updated_change, updated_character, decision

    def reject_change(
        self,
        change_id: str,
        user_input: str = "",
    ) -> tuple[PendingCharacterStateChange, Decision]:
        changes = self._read_changes()
        change = self._find_change(change_id, changes)
        if change.status != "pending":
            raise StorageError("CHARACTER_STATE_CHANGE_NOT_PENDING")
        decision = self._append_decision(
            decision_type="reject",
            target_type="character_state_change",
            target_id=change.change_id,
            user_input=user_input or f"拒绝 A-tier 角色重大状态变更：{change.summary}",
        )
        timestamp = now_iso()
        updated_change = copy_model(
            change,
            status="rejected",
            updated_at=timestamp,
            decided_at=timestamp,
            decision_id=decision.decision_id,
        )
        self._replace_change(changes, updated_change)
        return updated_change, decision

    def _requires_pending_confirmation(
        self,
        character: Character,
        proposed: ProposedCharacterStateChange,
    ) -> bool:
        if character.tier != "A":
            return False
        return a_tier_change_requires_confirmation(
            change_type=proposed.change_type,
            impact_level=proposed.impact_level,
            patch=proposed.proposed_patch,
        )

    def _default_reason(
        self,
        character: Character,
        proposed: ProposedCharacterStateChange,
        impact_level: str,
    ) -> str:
        if character.tier == "A" and impact_level == "major":
            return "A-tier 角色的重大长期状态变化需要用户确认。"
        return "非阻塞角色状态变化，可直接记录。"

    def _apply_patch(self, character: Character, patch: dict[str, Any]) -> Character:
        characters = self._read_characters()
        current = self._find_character(character.character_id, characters)
        data = model_to_dict(current)
        data = self._deep_merge(data, patch)
        data["updated_at"] = now_iso()
        try:
            updated = Character(**data)
        except ValidationError as exc:
            raise StorageError("Character state patch failed schema validation.") from exc
        result = [
            updated if item.character_id == updated.character_id else item
            for item in characters
        ]
        self._write_characters(result)
        return updated

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

    def _find_character(
        self,
        character_id: str,
        characters: list[Character] | None = None,
    ) -> Character:
        for character in characters or self._read_characters():
            if character.character_id == character_id:
                return character
        raise StorageError(f"CHARACTER_NOT_FOUND: {character_id}")

    def _read_changes(self) -> list[PendingCharacterStateChange]:
        try:
            return [
                PendingCharacterStateChange(**item)
                for item in self.repositories.pending_character_state_changes.list_all()
                if isinstance(item, dict)
            ]
        except (TypeError, ValidationError) as exc:
            raise StorageError(f"JSON schema is invalid: {self.pending_changes_file}") from exc

    def _write_changes(self, changes: list[PendingCharacterStateChange]) -> None:
        self.repositories.pending_character_state_changes.write_all(
            [model_to_dict(change) for change in changes],
        )

    def _find_change(
        self,
        change_id: str,
        changes: list[PendingCharacterStateChange],
    ) -> PendingCharacterStateChange:
        for change in changes:
            if change.change_id == change_id:
                return change
        raise StorageError(f"CHARACTER_STATE_CHANGE_NOT_FOUND: {change_id}")

    def _replace_change(
        self,
        changes: list[PendingCharacterStateChange],
        updated: PendingCharacterStateChange,
    ) -> None:
        result = [
            updated if change.change_id == updated.change_id else change
            for change in changes
        ]
        self._write_changes(result)

    def _append_decision(
        self,
        decision_type: str,
        target_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decisions = self.repositories.decisions.list_all()
        decision = Decision(
            decision_id=f"decision_{target_type}_{target_id}_{uuid4().hex[:8]}",
            decision_type=decision_type,
            target_type=target_type,
            target_id=target_id,
            user_input=user_input,
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.repositories.decisions.write_all(decisions)
        return decision

    def _next_change_id(self, character_id: str) -> str:
        return f"character_state_change_{character_id}_{uuid4().hex[:8]}"

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
