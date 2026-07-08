from datetime import datetime, timezone

from app.backend.models.runtime_participation import (
    ABCDParticipationPolicy,
    RoleRuntimeParticipationContract,
    RoleTierRuntimeRule,
)


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ABCDRuntimeParticipationPolicyService:
    """Builds Phase 8.5-B M1 policy-only ABCD runtime contracts."""

    def get_policy(self) -> ABCDParticipationPolicy:
        return ABCDParticipationPolicy(
            safe_summary=(
                "M1 defines ABCD runtime participation policy only: A/B may be "
                "explicit at chapter level, C/D are scene-selectable through later "
                "SceneAgent logic, and D memory remains minimal but persistent."
            ),
            created_at=now_utc(),
        )

    def get_role_contract(
        self,
        project_id: str = "local_project",
    ) -> RoleRuntimeParticipationContract:
        tier_rules = {
            "A": RoleTierRuntimeRule(
                tier="A",
                chapter_explicit_allowed=True,
                scene_selectable=True,
                context_depth="full",
                major_change_requires_confirmation=True,
                memory_policy="persistent",
                safe_summary="A-tier may be explicit in chapter planning and receives full scene context.",
            ),
            "B": RoleTierRuntimeRule(
                tier="B",
                chapter_explicit_allowed=True,
                scene_selectable=True,
                context_depth="medium",
                does_not_auto_enter_main_cast=True,
                memory_policy="persistent",
                safe_summary="B-tier may be explicit in chapter planning but does not auto-enter main cast.",
            ),
            "C": RoleTierRuntimeRule(
                tier="C",
                chapter_function_need_allowed=True,
                scene_selectable=True,
                context_depth="compact",
                memory_policy="persistent",
                safe_summary="C-tier is a chapter function need and must be selected by scene-level logic.",
            ),
            "D": RoleTierRuntimeRule(
                tier="D",
                chapter_function_need_allowed=True,
                scene_selectable=True,
                context_depth="minimal",
                memory_policy="minimal_but_persistent",
                safe_summary="D-tier receives minimal context but keeps persistent memory continuity.",
            ),
        }
        return RoleRuntimeParticipationContract(
            project_id=project_id,
            tier_rules=tier_rules,
            chapter_level_rules={
                "explicit_role_tiers": ["A", "B"],
                "function_need_only_tiers": ["C", "D"],
                "c_d_detailed_context_forbidden": True,
                "chapter_agent_must_not_select_scene_participants": True,
            },
            scene_level_rules={
                "selectable_role_tiers": ["A", "B", "C", "D"],
                "scene_agent_must_explain_c_d_selection": True,
                "unselected_c_d_must_not_enter_scene_context": True,
            },
            memory_rules={
                "d_tier_memory": "minimal_but_persistent",
                "tiered_writeback_future_boundary": "scene_commit_after_quality_and_continuity_gates",
                "claim_or_perception_never_auto_writes_objective_event": True,
            },
            gate_rules={
                "scene_agent_cannot_bypass_continuity_gate": True,
                "authorial_intent_soft_intent_only": True,
                "major_state_changes_require_gate_or_user_confirmation": True,
            },
            terminology_rules={
                "scene_agent": "selects and explains role participation at scene level",
                "scene_environment_agent": "future environment or stage planner, not a role selector",
                "stage_agent": "future staging helper, not the SceneAgent authority",
            },
            safe_summary=(
                "Role runtime participation contract is policy-only and cannot write story facts."
            ),
            created_at=now_utc(),
        )

    def validate_policy_and_contract(
        self,
        policy: ABCDParticipationPolicy,
        contract: RoleRuntimeParticipationContract,
    ) -> list[str]:
        issues: list[str] = []
        if not policy.contract_is_policy_only:
            issues.append("policy_must_be_policy_only")
        if contract.can_write_story_facts:
            issues.append("contract_must_not_write_story_facts")
        if not contract.contract_is_policy_only:
            issues.append("contract_must_be_policy_only")
        expected = {
            "A": ("full", True, False),
            "B": ("medium", True, False),
            "C": ("compact", False, True),
            "D": ("minimal", False, True),
        }
        for tier, (depth, chapter_explicit, function_need) in expected.items():
            rule = contract.tier_rules.get(tier)
            if rule is None:
                issues.append(f"missing_tier_rule:{tier}")
                continue
            if rule.context_depth != depth:
                issues.append(f"tier_context_depth_invalid:{tier}")
            if rule.chapter_explicit_allowed != chapter_explicit:
                issues.append(f"tier_chapter_explicit_invalid:{tier}")
            if rule.chapter_function_need_allowed != function_need:
                issues.append(f"tier_function_need_invalid:{tier}")
            if not rule.scene_selectable:
                issues.append(f"tier_scene_selectable_invalid:{tier}")
        if not contract.tier_rules.get("D") or contract.tier_rules["D"].memory_policy != "minimal_but_persistent":
            issues.append("d_tier_memory_policy_invalid")
        return issues
