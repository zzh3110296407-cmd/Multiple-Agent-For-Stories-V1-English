from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.character import Character
from app.backend.models.scene_participants import (
    SceneRoleCandidate,
    SceneRoleFunctionNeedRef,
)
from app.backend.services.abcd_runtime_participation_policy_service import now_utc
from app.backend.storage.json_store import JsonStore, StorageError


class SceneRoleCandidateSearchService:
    """Searches existing confirmed C/D roles without building scene context."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.characters_file = self.data_dir / "characters.json"

    def search_candidates(
        self,
        *,
        need: SceneRoleFunctionNeedRef,
        scene_index: int,
        scene_goal: str = "",
        scene_location: str = "",
        previous_scene_result: str = "",
        limit: int = 5,
    ) -> list[SceneRoleCandidate]:
        candidates: list[SceneRoleCandidate] = []
        for character in self._read_confirmed_cd_characters():
            candidate = self._score_character(
                character=character,
                need=need,
                scene_index=scene_index,
                scene_goal=scene_goal,
                scene_location=scene_location,
                previous_scene_result=previous_scene_result,
            )
            if candidate is not None:
                candidates.append(candidate)
        return sorted(candidates, key=_candidate_sort_key)[: max(1, int(limit or 5))]

    def _score_character(
        self,
        *,
        character: Character,
        need: SceneRoleFunctionNeedRef,
        scene_index: int,
        scene_goal: str,
        scene_location: str,
        previous_scene_result: str,
    ) -> SceneRoleCandidate | None:
        tier = str(character.tier or "").upper()
        if tier not in {"C", "D"}:
            return None
        if need.tier_preference in {"C", "D"} and tier != need.tier_preference:
            tier_match = False
        else:
            tier_match = True

        profile_text = " ".join(
            [
                character.name,
                character.role,
                character.profile.description,
                character.profile.identity,
                character.profile.story_function,
                character.profile.background_summary,
                character.profile.faction_or_origin,
                " ".join(character.profile.traits),
                " ".join(character.profile.goals),
                " ".join(character.profile.knowledge_scope),
                character.current_state.location_id,
                character.current_state.faction_id,
                character.current_state.active_goal,
                character.current_state.current_desire,
                character.memory_summary.summary,
                " ".join(character.memory_summary.open_threads),
            ]
        )
        scene_text = " ".join([scene_goal, scene_location, previous_scene_result])
        function_tokens = set(_meaningful_tokens(f"{need.function_type} {need.function_summary} {need.reason}"))
        location_tokens = set(_meaningful_tokens(f"{need.location_hint} {scene_location}"))
        relationship_tokens = set(_meaningful_tokens(need.relationship_hint))
        knowledge_tokens = set(_meaningful_tokens(need.knowledge_need))
        profile_tokens = set(_meaningful_tokens(profile_text))
        scene_tokens = set(_meaningful_tokens(scene_text))

        function_match = bool(function_tokens & profile_tokens)
        location_match = bool(location_tokens & profile_tokens)
        relationship_match = bool(relationship_tokens & profile_tokens)
        memory_match = bool(knowledge_tokens & profile_tokens) or bool(
            set(_meaningful_tokens(previous_scene_result)) & profile_tokens
        )
        if not function_match and function_tokens & scene_tokens & profile_tokens:
            function_match = True

        score = 0
        reasons: list[str] = []
        if tier_match:
            score += 1
            reasons.append("tier preference matches")
        if function_match:
            score += 3
            reasons.append("function keywords match role profile")
        if location_match:
            score += 2
            reasons.append("location hint matches role state/profile")
        if relationship_match:
            score += 1
            reasons.append("relationship hint matches role profile")
        if memory_match:
            score += 1
            reasons.append("light memory/knowledge hint matches")
        if not reasons:
            reasons.append("generic C/D fallback candidate")

        match_score = "low"
        if score >= 5:
            match_score = "high"
        elif score >= 3:
            match_score = "medium"

        return SceneRoleCandidate(
            candidate_id=f"role_candidate_{need.chapter_id}_{scene_index}_{need.source_need_id}_{character.character_id}",
            project_id=need.project_id,
            chapter_id=need.chapter_id,
            scene_index=scene_index,
            source_need_id=need.source_need_id,
            candidate_source="existing_confirmed_role",
            character_id=character.character_id,
            tier=tier,
            role_label=character.name,
            function_type=need.function_type,
            match_score=match_score,
            match_reasons=reasons,
            location_match=location_match,
            relationship_match=relationship_match,
            memory_match=memory_match,
            function_match=function_match,
            continuity_risk="low",
            safe_summary=(
                f"{character.name} is a {tier}-tier existing role candidate for "
                f"{need.function_type}."
            ),
            created_at=now_utc(),
        )

    def _read_confirmed_cd_characters(self) -> list[Character]:
        if not self.store.exists(self.characters_file):
            return []
        raw = self.store.read_any(self.characters_file)
        if not isinstance(raw, list):
            raise StorageError("SCENE_PARTICIPANT_CHARACTERS_INVALID: characters.json must be a list.")
        characters: list[Character] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                character = Character(**item)
            except Exception:
                continue
            if str(character.status or "").strip() != "confirmed":
                continue
            if character.archived_at:
                continue
            if str(character.tier or "").upper() not in {"C", "D"}:
                continue
            if _is_placeholder_role_character(character):
                continue
            characters.append(character)
        return characters


def _candidate_sort_key(candidate: SceneRoleCandidate) -> tuple[int, str]:
    score_weight = {"high": 0, "medium": 1, "low": 2}
    return (score_weight.get(candidate.match_score, 9), candidate.candidate_id)


def _meaningful_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in str(text or "").casefold().replace("_", " ").replace("/", " ").split():
        clean = "".join(ch for ch in token if ch.isalnum())
        if len(clean) >= 3:
            tokens.append(clean)
    return tokens


def _is_placeholder_role_character(character: Character) -> bool:
    text = " ".join(
        [
            character.name,
            character.profile.identity,
            character.profile.description,
        ]
    ).casefold()
    return any(
        marker in text
        for marker in (
            "c local",
            "d local",
            "c role",
            "d role",
            "pending c-tier",
            "pending d-tier",
            "placeholder",
            "not written to characters.json",
            "\u672c\u5730\u89c1\u8bc1\u8005",
            "\u4e34\u65f6\u5411\u5bfc",
            "\u4e34\u65f6\u53c2\u4e0e\u8005",
        )
    )
