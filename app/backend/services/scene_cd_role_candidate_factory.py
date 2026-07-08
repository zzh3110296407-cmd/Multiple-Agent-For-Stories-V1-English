from pathlib import Path

from app.backend.core.config import settings
from app.backend.models.scene_participants import (
    SceneCDRoleCreationCandidate,
    SceneRoleCandidate,
    SceneRoleFunctionNeedRef,
)
from app.backend.services.abcd_runtime_participation_policy_service import now_utc
from app.backend.storage.json_store import JsonStore


class SceneCDRoleCandidateFactory:
    """Creates pending C/D role candidates without writing characters.json."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir

    def create_pending_candidate(
        self,
        *,
        selection_id: str,
        need: SceneRoleFunctionNeedRef,
        scene_index: int,
    ) -> tuple[SceneCDRoleCreationCandidate, SceneRoleCandidate]:
        target_tier = self._target_tier(need)
        role_label = self._role_label(target_tier, need.function_type)
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
                f"Pending {target_tier}-tier role candidate for {need.function_type}; "
                "not written to characters.json."
            ),
            warnings=["pending candidate requires user confirmation before story entry"],
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
            ("D", "guard_or_gatekeeper"): "D guard",
            ("D", "crowd_reaction"): "D crowd witness",
            ("D", "messenger"): "D messenger",
            ("C", "temporary_guide"): "C local guide",
            ("C", "case_informant"): "C case informant",
            ("C", "minor_opponent"): "C temporary opponent",
            ("D", "patrol"): "D patrol",
            ("D", "driver"): "D driver",
            ("D", "servant"): "D servant",
            ("D", "shopkeeper"): "D shopkeeper",
        }
        return labels.get((tier, function_type), f"{tier} {function_type.replace('_', ' ')}")
