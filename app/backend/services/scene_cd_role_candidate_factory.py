from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.backend.agents.character_agent import CharacterAgent
from app.backend.core.config import settings
from app.backend.models.character import Character
from app.backend.models.project_story_premise import ProjectStoryPremise
from app.backend.models.relationship import Relationship
from app.backend.models.scene_participants import (
    SceneCDRoleCreationCandidate,
    SceneRoleCandidate,
    SceneRoleFunctionNeedRef,
)
from app.backend.services.abcd_runtime_participation_policy_service import now_utc
from app.backend.models.world_canvas import WorldCanvas
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelJsonParseError,
)
from app.backend.storage.json_store import JsonStore


class SceneCDRoleCandidateFactory:
    """Creates pending C/D role candidates without writing characters.json."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        character_agent: CharacterAgent | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.character_agent = character_agent or CharacterAgent()

    def create_pending_candidate(
        self,
        *,
        selection_id: str,
        need: SceneRoleFunctionNeedRef,
        scene_index: int,
    ) -> tuple[SceneCDRoleCreationCandidate, SceneRoleCandidate]:
        target_tier = self._target_tier(need)
        fallback_role_label = self._role_label(target_tier, need.function_type)
        role_label, generated_profile, profile_warnings = self._generate_candidate_profile(
            need=need,
            scene_index=scene_index,
            target_tier=target_tier,
            fallback_role_label=fallback_role_label,
        )
        now = now_utc()
        creation = SceneCDRoleCreationCandidate(
            creation_candidate_id=(
                f"cd_creation_{need.chapter_id}_{scene_index}_{need.source_need_id}_{target_tier.lower()}"
            ),
            project_id=need.project_id,
            selection_id=selection_id,
            chapter_id=need.chapter_id,
            scene_index=scene_index,
            source_need_id=need.source_need_id,
            target_tier=target_tier,
            role_label=role_label,
            story_function=need.function_type,
            minimal_profile={
                **generated_profile,
                "role_function": need.function_type,
                "location_hint": need.location_hint,
                "relationship_hint": need.relationship_hint,
                "knowledge_need": need.knowledge_need,
            },
            required_scene_function=need.function_summary or need.reason or need.function_type,
            status="pending",
            requires_user_confirmation=True,
            does_not_enter_story_until_confirmed=True,
            safe_summary=(
                f"{role_label}: "
                f"{generated_profile.get('description') or need.function_summary or need.reason}."
            ),
            warnings=[
                "candidate requires user confirmation before story entry",
                *profile_warnings,
            ],
            created_at=now,
            updated_at=now,
        )
        role_candidate = SceneRoleCandidate(
            candidate_id=(
                f"role_candidate_{need.chapter_id}_{scene_index}_{need.source_need_id}_new_{target_tier.lower()}"
            ),
            project_id=need.project_id,
            chapter_id=need.chapter_id,
            scene_index=scene_index,
            source_need_id=need.source_need_id,
            candidate_source="new_role_candidate",
            generated_role_candidate_id=creation.creation_candidate_id,
            tier=target_tier,
            role_label=role_label,
            function_type=need.function_type,
            match_score="medium",
            match_reasons=["no confirmed C/D role matched; pending candidate proposed"],
            safe_summary=creation.safe_summary,
            warnings=list(creation.warnings),
            created_at=now,
        )
        return creation, role_candidate

    def _generate_candidate_profile(
        self,
        *,
        need: SceneRoleFunctionNeedRef,
        scene_index: int,
        target_tier: str,
        fallback_role_label: str,
    ) -> tuple[str, dict[str, Any], list[str]]:
        fallback_profile = {
            "description": need.function_summary or need.reason or fallback_role_label,
            "identity": fallback_role_label,
            "story_function": need.function_type,
            "background_summary": need.reason or need.function_summary,
            "traits": [],
            "goals": [],
            "knowledge_scope": [need.knowledge_need] if need.knowledge_need else [],
            "profile_source": "deterministic_fallback",
        }
        inputs = self._load_generation_inputs()
        if inputs is None:
            return (
                fallback_role_label,
                fallback_profile,
                ["model_profile_unavailable: project context is incomplete"],
            )
        world_canvas, premise, characters, relationships = inputs
        prompt = (
            f"Create one {target_tier}-tier scene participant candidate for scene "
            f"{scene_index}. The role must serve only this function: "
            f"{need.function_summary or need.reason or need.function_type}. "
            f"Location hint: {need.location_hint or 'use the current scene location'}. "
            f"Relationship hint: {need.relationship_hint or 'derive only from confirmed context'}. "
            f"Knowledge boundary: {need.knowledge_need or 'only what this role plausibly knows'}. "
            "Return a story-specific proper name and a compact profile. Do not use labels such as "
            "C role, D role, local witness, temporary guide, NPC, or placeholder as the name. "
            "Do not invent completed story events or future outcomes."
        )
        try:
            result = self.character_agent.generate_character(
                world_canvas=world_canvas,
                existing_characters=characters,
                existing_relationships=relationships,
                user_prompt=prompt,
                role_hint=need.function_type,
                story_function_hint=(
                    need.function_summary or need.reason or need.function_type
                ),
                project_story_premise=premise,
                same_tier_characters=[
                    character
                    for character in characters
                    if str(character.tier or "").upper() == target_tier
                ],
            )
        except (
            ModelConfigurationError,
            ModelCallError,
            ModelJsonParseError,
            ValidationError,
            TypeError,
            ValueError,
        ):
            return (
                fallback_role_label,
                fallback_profile,
                ["model_profile_unavailable: provider or schema failure"],
            )
        raw_character = result.get("character") if isinstance(result, dict) else None
        if not isinstance(raw_character, dict):
            return (
                fallback_role_label,
                fallback_profile,
                ["model_profile_unavailable: character payload missing"],
            )
        name = str(raw_character.get("name") or "").strip()
        raw_profile = raw_character.get("profile") or {}
        if not name or not isinstance(raw_profile, dict) or self._is_placeholder_name(name):
            return (
                fallback_role_label,
                fallback_profile,
                ["model_profile_unavailable: candidate name or profile was generic"],
            )
        profile = {
            "description": str(raw_profile.get("description") or need.function_summary or "").strip(),
            "identity": str(raw_profile.get("identity") or raw_character.get("role") or need.function_type).strip(),
            "story_function": str(raw_profile.get("story_function") or need.function_type).strip(),
            "background_summary": str(raw_profile.get("background_summary") or need.reason or "").strip(),
            "traits": self._string_list(raw_profile.get("traits")),
            "goals": self._string_list(raw_profile.get("goals")),
            "knowledge_scope": self._string_list(
                raw_profile.get("knowledge_scope")
                or ([need.knowledge_need] if need.knowledge_need else [])
            ),
            "profile_source": "model",
        }
        return name, profile, []

    def _load_generation_inputs(
        self,
    ) -> tuple[WorldCanvas, ProjectStoryPremise, list[Character], list[Relationship]] | None:
        world_file = self.data_dir / "world_canvas.json"
        premise_file = self.data_dir / "project_story_premise.json"
        if not self.store.exists(world_file) or not self.store.exists(premise_file):
            return None
        try:
            world_canvas = WorldCanvas(**self.store.read_any(world_file))
            premise = ProjectStoryPremise(**self.store.read_any(premise_file))
            characters = self._read_models(self.data_dir / "characters.json", Character)
            relationships = self._read_models(
                self.data_dir / "relationships.json",
                Relationship,
            )
        except (ValidationError, TypeError, ValueError):
            return None
        return world_canvas, premise, characters, relationships

    def _read_models(self, path: Path, model_type: type) -> list[Any]:
        if not self.store.exists(path):
            return []
        raw = self.store.read_any(path)
        if not isinstance(raw, list):
            return []
        result: list[Any] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(model_type(**item))
            except (ValidationError, TypeError, ValueError):
                continue
        return result

    def _is_placeholder_name(self, name: str) -> bool:
        folded = str(name or "").strip().casefold()
        return any(
            marker in folded
            for marker in (
                "c role",
                "d role",
                "c local",
                "d local",
                "local witness",
                "temporary guide",
                "placeholder",
                "npc",
                "\u89c1\u8bc1\u8005\u89d2\u8272",
                "\u4e34\u65f6\u89d2\u8272",
            )
        )

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item or "").strip()]
        clean = str(value or "").strip()
        return [clean] if clean else []

    def _target_tier(self, need: SceneRoleFunctionNeedRef) -> str:
        if need.tier_preference in {"C", "D"}:
            return need.tier_preference
        if need.function_type in {
            "local_witness",
            "temporary_guide",
            "case_informant",
            "minor_opponent",
        }:
            return "C"
        return "D"

    def _role_label(self, tier: str, function_type: str) -> str:
        labels = {
            ("C", "local_witness"): "\u672c\u5730\u89c1\u8bc1\u8005",
            ("D", "guard_or_gatekeeper"): "\u5b88\u536b",
            ("D", "crowd_reaction"): "\u56f4\u89c2\u8005",
            ("D", "messenger"): "\u4fe1\u4f7f",
            ("C", "temporary_guide"): "\u4e34\u65f6\u5411\u5bfc",
            ("C", "case_informant"): "\u77e5\u60c5\u8005",
            ("C", "minor_opponent"): "\u4e34\u65f6\u5bf9\u624b",
            ("D", "patrol"): "\u5de1\u903b\u8005",
            ("D", "driver"): "\u8f66\u592b",
            ("D", "servant"): "\u4f8d\u4ece",
            ("D", "shopkeeper"): "\u5e97\u4e3b",
        }
        return labels.get((tier, function_type), "\u4e34\u65f6\u53c2\u4e0e\u8005")
