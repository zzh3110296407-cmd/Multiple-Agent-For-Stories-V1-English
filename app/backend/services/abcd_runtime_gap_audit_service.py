from pathlib import Path

from app.backend.models.runtime_participation import ABCDRuntimeGapAudit
from app.backend.services.abcd_runtime_participation_policy_service import now_utc
from app.backend.services.role_tier_budget_service import RoleTierBudgetService


GAP_TO_MILESTONE_MAP: dict[str, str] = {
    "chapter_plan_ab_cd_function_needs_missing_or_incomplete": "M2",
    "scene_generation_a_only_character_input": "M3",
    "sceneagent_cd_selection_missing": "M3",
    "scene_participation_package_missing": "M4",
    "tiered_memory_retrieval_hit_tracking_missing": "M5",
    "character_psychology_action_intent_runtime_missing": "M6",
    "writer_story_information_abcd_integration_missing": "M7",
    "tiered_memory_writeback_missing": "M8",
    "abcd_continuity_quality_gate_runtime_integration_missing": "M9",
    "abcd_runtime_frontend_surfaces_missing": "M10",
}


CHECKED_MODULES = [
    "app/backend/services/chapter_plan_service.py",
    "app/backend/prompts/chapter_prompts.py",
    "app/backend/services/scene_generation_service.py",
    "app/backend/services/scene_memory_service.py",
    "app/backend/services/memory_retrieval_service.py",
    "app/backend/services/character_context_builder.py",
    "app/backend/services/role_tier_budget_service.py",
    "app/backend/services/continuity_gate_service.py",
    "app/backend/services/authorial_intent_service.py",
    "app/backend/models/scene_generation.py",
    "app/backend/models/product_progress.py",
    "app/backend/models/plugin_runtime.py",
    "app/frontend/src",
]


class ABCDRuntimeGapAuditService:
    """Read-only static audit for Phase 8.5-B M1 runtime participation gaps."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[3]

    def build_audit(self) -> ABCDRuntimeGapAudit:
        warnings: list[str] = []
        chapter_plan = self._read("app/backend/services/chapter_plan_service.py")
        chapter_prompts = self._read("app/backend/prompts/chapter_prompts.py")
        scene_generation = self._read("app/backend/services/scene_generation_service.py")
        scene_memory = self._read("app/backend/services/scene_memory_service.py")
        memory_retrieval = self._read("app/backend/services/memory_retrieval_service.py")
        context_builder_path = self.repo_root / "app/backend/services/character_context_builder.py"
        budget_path = self.repo_root / "app/backend/services/role_tier_budget_service.py"
        scene_generation_models = self._read("app/backend/models/scene_generation.py")
        frontend_text = self._read_tree("app/frontend/src", suffixes=(".jsx", ".js"))

        chapter_a_only = (
            "Confirmed A-tier characters" in chapter_prompts
            or "confirmed A-tier characters" in chapter_plan
            or '_read_confirmed_a_characters_if_present' in chapter_plan
        )
        chapter_cd_gap = not self._has_any(
            chapter_plan + chapter_prompts,
            [
                "cd_role_function_needs",
                "c_d_function_needs",
                "chapter_function_need_only_tiers",
                "function_need_only_tiers",
            ],
        )
        scene_a_only = (
            '_read_confirmed_a_characters_if_present' in scene_generation
            and 'character.tier == "A"' in scene_generation
        )
        sceneagent_missing = not self._has_any(
            scene_generation + scene_generation_models,
            [
                "SceneParticipationPackage",
                "SceneParticipantSelection",
                "SceneRoleCandidate",
                "selected_c_d",
                "selected_role_participants",
            ],
        )
        scene_memory_active = "active_character_ids" in scene_memory
        memory_retrieval_active = (
            "active_character_ids" in memory_retrieval
            and "scene_active_characters" in memory_retrieval
        )
        if not memory_retrieval_active:
            warnings.append("memory_retrieval_active_character_scope_not_detected")

        budget_decreasing = self._budget_decreasing()
        story_info_channel_exists = self._has_any(
            scene_generation + scene_generation_models,
            ["StoryInformationItem", "ordered_story_information_package"],
        )
        retrieval_hit_tracking_missing = not self._has_any(
            memory_retrieval,
            [
                "RoleTierMemoryHit",
                "tiered_memory_retrieval_hit",
                "retrieval_hit_tracking",
            ],
        )
        writeback_missing = not self._has_any(
            self._read_tree(
                "app/backend",
                suffixes=(".py",),
                exclude_parts=(
                    "abcd_runtime_gap_audit_service.py",
                    "verify_phase85b_m0_intake_audit.py",
                    "verify_phase85b_m1_abcd_runtime_gap_and_contract.py",
                ),
            ),
            [
                "TieredSceneMemoryWritePlan",
                "RoleTierMemoryWritebackPlan",
                "RoleTierMemoryWriteBackPlan",
                "SceneRoleTierMemoryWriteback",
            ],
        )
        frontend_surfaces_missing = not self._has_any(
            frontend_text,
            [
                "ABCD Runtime",
                "SceneParticipationPackage",
                "RuntimeRoleEligibilityReport",
                "scene participation package",
            ],
        )

        return ABCDRuntimeGapAudit(
            checked_modules=CHECKED_MODULES,
            chapter_plan_a_only_or_ab_missing_detected=chapter_a_only,
            chapter_cd_function_needs_missing_or_incomplete=chapter_cd_gap,
            scene_generation_a_only_detected=scene_a_only,
            sceneagent_cd_selection_missing=sceneagent_missing,
            scene_memory_supports_active_character_ids=scene_memory_active,
            memory_retrieval_supports_active_character_ids=memory_retrieval_active,
            character_context_builder_exists=context_builder_path.exists(),
            role_tier_budget_service_exists=budget_path.exists(),
            role_tier_budget_decreasing_a_b_c_d=budget_decreasing,
            writer_story_information_integration_exists=story_info_channel_exists,
            tiered_memory_retrieval_hit_tracking_missing=retrieval_hit_tracking_missing,
            tiered_memory_writeback_missing=writeback_missing,
            frontend_abcd_runtime_surfaces_missing=frontend_surfaces_missing,
            gap_to_milestone_map=dict(GAP_TO_MILESTONE_MAP),
            warnings=warnings,
            safe_summary=(
                "M1 records current ABCD runtime gaps and maps each expected gap to a later milestone."
            ),
            created_at=now_utc(),
        )

    def _budget_decreasing(self) -> bool:
        budgets = RoleTierBudgetService().default_budgets()
        try:
            return (
                budgets["A"].max_character_tokens
                > budgets["B"].max_character_tokens
                > budgets["C"].max_character_tokens
                > budgets["D"].max_character_tokens
            )
        except KeyError:
            return False

    def _read(self, relative_path: str) -> str:
        path = self.repo_root / relative_path
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _read_tree(
        self,
        relative_path: str,
        *,
        suffixes: tuple[str, ...],
        exclude_parts: tuple[str, ...] = (),
    ) -> str:
        root = self.repo_root / relative_path
        if not root.exists():
            return ""
        chunks: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in suffixes:
                normalized = path.as_posix()
                if any(part in normalized for part in exclude_parts):
                    continue
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(chunks)

    def _has_any(self, text: str, snippets: list[str]) -> bool:
        return any(snippet in text for snippet in snippets)
