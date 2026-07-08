from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.character import Character
from app.backend.models.scene_participants import (
    SceneCDRoleCreationCandidate,
    SceneParticipantSelection,
)
from app.backend.storage.json_store import JsonStore, StorageError


class SceneParticipantSelectionGuard:
    """Guards M3 selection output from crossing into M4/story-fact authority."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.characters_file = self.data_dir / "characters.json"

    def validate_selection(
        self,
        *,
        selection: SceneParticipantSelection,
        chapter: Chapter,
        creation_candidates: list[SceneCDRoleCreationCandidate],
    ) -> None:
        if selection.does_not_write_story_facts is not True:
            raise StorageError("SCENE_PARTICIPANT_SELECTION_STORY_FACT_WRITE_FORBIDDEN: selection must be workflow-only.")
        if len(selection.selected_c_ids) > selection.max_c_count:
            raise StorageError("SCENE_PARTICIPANT_SELECTION_C_BUDGET_EXCEEDED: too many C-tier roles selected.")
        if len(selection.selected_d_ids) > selection.max_d_count:
            raise StorageError("SCENE_PARTICIPANT_SELECTION_D_BUDGET_EXCEEDED: too many D-tier roles selected.")

        characters = self._read_characters_by_id()
        chapter_a, chapter_b = self._allowed_chapter_ab_ids(
            chapter=chapter,
            characters=characters,
        )
        if not set(selection.selected_a_ids).issubset(chapter_a):
            raise StorageError("SCENE_PARTICIPANT_SELECTION_A_NOT_CHAPTER_CARRY_IN: selected A ids must come from Chapter.")
        if not set(selection.selected_b_ids).issubset(chapter_b):
            raise StorageError("SCENE_PARTICIPANT_SELECTION_B_NOT_CHAPTER_CARRY_IN: selected B ids must come from Chapter.")

        pending_candidate_ids = {
            candidate.creation_candidate_id for candidate in creation_candidates
        }
        selected_cd_ids = [*selection.selected_c_ids, *selection.selected_d_ids]
        for character_id in selected_cd_ids:
            if character_id in pending_candidate_ids:
                raise StorageError("SCENE_PARTICIPANT_SELECTION_PENDING_CANDIDATE_SELECTED: pending candidate cannot enter selected C/D ids.")
            character = characters.get(character_id)
            if character is None:
                raise StorageError("SCENE_PARTICIPANT_SELECTION_SELECTED_ROLE_MISSING: selected C/D role does not exist.")
            tier = str(character.tier or "").upper()
            if tier not in {"C", "D"}:
                raise StorageError("SCENE_PARTICIPANT_SELECTION_SELECTED_ROLE_TIER_INVALID: selected C/D role must be tier C or D.")
            if str(character.status or "").strip() != "confirmed" or character.archived_at:
                raise StorageError("SCENE_PARTICIPANT_SELECTION_SELECTED_ROLE_NOT_CONFIRMED: selected C/D role must be confirmed and active.")
            if tier == "C" and character_id not in selection.selected_c_ids:
                raise StorageError("SCENE_PARTICIPANT_SELECTION_C_ROLE_IN_WRONG_BUCKET: C-tier role must be selected_c_ids.")
            if tier == "D" and character_id not in selection.selected_d_ids:
                raise StorageError("SCENE_PARTICIPANT_SELECTION_D_ROLE_IN_WRONG_BUCKET: D-tier role must be selected_d_ids.")
            reason = str(selection.selection_reasons.get(character_id) or "").strip()
            if not reason:
                raise StorageError("SCENE_PARTICIPANT_SELECTION_REASON_REQUIRED: every selected C/D must have a reason.")
        for candidate in creation_candidates:
            if candidate.status != "pending":
                raise StorageError("SCENE_PARTICIPANT_SELECTION_CREATION_STATUS_INVALID: M3 can create pending candidates only.")
            if candidate.does_not_enter_story_until_confirmed is not True:
                raise StorageError("SCENE_PARTICIPANT_SELECTION_CREATION_BOUNDARY_INVALID: pending candidate must not enter story until confirmed.")

    def _allowed_chapter_ab_ids(
        self,
        *,
        chapter: Chapter,
        characters: dict[str, Character],
    ) -> tuple[set[str], set[str]]:
        chapter_a = set(chapter.main_cast_character_ids or [])
        chapter_b = set(chapter.supporting_role_ids or [])
        participant_ids = set(
            chapter.participating_character_ids or chapter.participant_character_ids or []
        )
        if participant_ids and not chapter_a:
            chapter_a = self._confirmed_active_participants_by_tier(
                participant_ids=participant_ids,
                characters=characters,
                tier="A",
            )
        if participant_ids and not chapter_b:
            chapter_b = self._confirmed_active_participants_by_tier(
                participant_ids=participant_ids,
                characters=characters,
                tier="B",
            )
        return chapter_a, chapter_b

    def _confirmed_active_participants_by_tier(
        self,
        *,
        participant_ids: set[str],
        characters: dict[str, Character],
        tier: str,
    ) -> set[str]:
        result: set[str] = set()
        for character_id in participant_ids:
            character = characters.get(character_id)
            if character is None:
                continue
            if str(character.tier or "").upper() != tier:
                continue
            if str(character.status or "").strip() != "confirmed" or character.archived_at:
                continue
            result.add(character_id)
        return result

    def _read_characters_by_id(self) -> dict[str, Character]:
        if not self.store.exists(self.characters_file):
            return {}
        raw = self.store.read_any(self.characters_file)
        if not isinstance(raw, list):
            raise StorageError("SCENE_PARTICIPANT_CHARACTERS_INVALID: characters.json must be a list.")
        result: dict[str, Character] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                character = Character(**item)
            except Exception:
                continue
            result[character.character_id] = character
        return result
