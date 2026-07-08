from __future__ import annotations

import re
from typing import Any

from app.backend.models.writer_prose_engine import (
    PSYCHOLOGY_ALLOWED_CHANNELS,
    PSYCHOLOGY_INTERIORITY_BUDGETS,
    PSYCHOLOGY_POV_MODES,
    PSYCHOLOGY_TIERS,
    PSYCHOLOGY_VISIBILITY_LEVELS,
    PsychologicalNegativeSpace,
    PsychologyVisibilityDecision,
    PsychologyVisibilityPlan,
    PsychologyVisibilityPlanValidationReport,
)


RAW_PSYCHOLOGY_MARKERS = {
    "raw_psychology_chain",
    "hidden_reasoning",
    "internal reasoning",
    "full psychology chain",
    "system prompt",
    "provider raw",
}


class PsychologyVisibilityPlannerService:
    def build_decision(
        self,
        *,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
        character_id: str,
        tier: str,
        visibility_level: str | None = None,
        reason: str | None = None,
    ) -> PsychologyVisibilityDecision:
        normalized_tier = str(tier or "D").strip().upper()
        level = visibility_level or self.default_visibility_level_for_tier(normalized_tier)
        max_words = self.default_max_words(normalized_tier, level)
        channels = self.default_channels_for_level(level)
        return PsychologyVisibilityDecision(
            decision_id=f"psych_visibility_{scene_id}_{character_id}",
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            character_id=character_id,
            tier=normalized_tier,
            visibility_level=level,
            reason=reason or self.default_reason_for_tier(normalized_tier, level),
            allowed_channels=channels,
            max_words=max_words,
            forbidden=self.forbidden_for_tier(normalized_tier),
            source_psychology_trace_ids=[f"psych_trace_{character_id}"],
            source_context_item_ids=[f"context_item_{character_id}"],
            safe_summary=f"{character_id} psychology is controlled as {level} for tier {normalized_tier}.",
            raw_psychology_chain_present=False,
        )

    def build_negative_space(
        self,
        *,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
        character_id: str,
        tier: str,
        withheld_summary: str,
        future_payoff_hint: str,
    ) -> PsychologicalNegativeSpace:
        return PsychologicalNegativeSpace(
            negative_space_id=f"psych_negative_space_{scene_id}_{character_id}",
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            character_id=character_id,
            tier=tier,
            withheld_psychology_summary=self.safe_summary(withheld_summary),
            reason="Keep the motive as subtext until the scene can earn it through behavior.",
            future_payoff_hint=self.safe_summary(future_payoff_hint),
            source_psychology_trace_ids=[f"psych_trace_{character_id}"],
            safe_summary=self.safe_summary(withheld_summary),
            raw_psychology_chain_present=False,
        )

    def build_fixture_plan(self) -> tuple[PsychologyVisibilityPlan, list[PsychologicalNegativeSpace]]:
        project_id = "project_m2"
        chapter_id = "chapter_001"
        scene_id = "scene_001"
        scene_index = 1
        decisions = [
            self.build_decision(
                project_id=project_id,
                chapter_id=chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
                character_id="char_a",
                tier="A",
                visibility_level="short_inner_line",
                reason="A-tier protagonist has a justified close choice pressure.",
            ),
            self.build_decision(
                project_id=project_id,
                chapter_id=chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
                character_id="char_b",
                tier="B",
                visibility_level="micro_reaction",
                reason="B-tier role shows pressure through a brief reaction.",
            ),
            self.build_decision(
                project_id=project_id,
                chapter_id=chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
                character_id="char_c",
                tier="C",
                visibility_level="micro_reaction",
                reason="C-tier role gets only a small visible reaction.",
            ),
            self.build_decision(
                project_id=project_id,
                chapter_id=chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
                character_id="char_d",
                tier="D",
                visibility_level="behavior_only",
                reason="D-tier role stays externally visible and light.",
            ),
        ]
        negative_spaces = [
            self.build_negative_space(
                project_id=project_id,
                chapter_id=chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
                character_id="char_a",
                tier="A",
                withheld_summary="A private fear remains implied by hesitation, not explained.",
                future_payoff_hint="Pay off through a later choice under pressure.",
            )
        ]
        plan = PsychologyVisibilityPlan(
            psychology_visibility_plan_id="psych_visibility_plan_scene_001",
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            pov_mode="close_limited",
            default_policy="behavior_first",
            total_interiority_budget="low",
            no_raw_psychology_chain=True,
            psychology_is_subtext_by_default=True,
            decisions=decisions,
            negative_space_ids=[item.negative_space_id for item in negative_spaces],
            source_scene_prose_plan_id="scene_prose_plan_scene_001",
            source_character_intent_package_id="tiered_intent_package_001",
            source_context_refs=["scene_prose_plan:scene_prose_plan_scene_001"],
        )
        return plan, negative_spaces

    def validate_plan(
        self,
        plan: PsychologyVisibilityPlan,
        negative_spaces: list[PsychologicalNegativeSpace] | None = None,
    ) -> PsychologyVisibilityPlanValidationReport:
        issue_codes: list[str] = []
        warning_codes: list[str] = []
        issues: list[str] = []
        warnings: list[str] = []

        def add_issue(code: str, message: str) -> None:
            if code not in issue_codes:
                issue_codes.append(code)
                issues.append(message)

        def add_warning(code: str, message: str) -> None:
            if code not in warning_codes:
                warning_codes.append(code)
                warnings.append(message)

        if not str(plan.psychology_visibility_plan_id or "").strip():
            add_issue("psychology_visibility_plan_id_missing", "PsychologyVisibilityPlan id is required.")
        for field_name in ["project_id", "chapter_id", "scene_id"]:
            if not str(getattr(plan, field_name, "") or "").strip():
                add_issue(f"{field_name}_missing", f"{field_name} is required.")
        if int(plan.scene_index or 0) < 1:
            add_issue("scene_index_invalid", "scene_index must be >= 1.")
        if plan.pov_mode not in PSYCHOLOGY_POV_MODES:
            add_issue("pov_mode_invalid", "pov_mode is not allowed.")
        if plan.total_interiority_budget not in PSYCHOLOGY_INTERIORITY_BUDGETS:
            add_issue("total_interiority_budget_invalid", "total_interiority_budget is not allowed.")
        if not plan.no_raw_psychology_chain:
            add_issue("raw_psychology_chain_forbidden", "Plan must not allow raw psychology chains.")
        if not plan.psychology_is_subtext_by_default:
            add_issue("psychology_subtext_default_required", "Psychology must be subtext by default.")
        if plan.default_policy != "behavior_first":
            add_warning("default_policy_not_behavior_first", "M2 expects behavior_first by default.")
        if not plan.decisions:
            add_issue("participant_decisions_missing", "At least one psychology visibility decision is required.")

        tier_decisions = {decision.tier for decision in plan.decisions}
        all_tiers_have_visibility_decisions = PSYCHOLOGY_TIERS.issubset(tier_decisions)

        for decision in plan.decisions:
            for code in self.validate_decision(decision, pov_mode=plan.pov_mode):
                add_issue(code, self.safe_issue_message(code))

        negative_space_safe = True
        for negative_space in negative_spaces or []:
            negative_issues = self.validate_negative_space(negative_space)
            if negative_issues:
                negative_space_safe = False
                for code in negative_issues:
                    add_issue(code, self.safe_issue_message(code))

        candidate_only_boundary_enforced = (
            plan.candidate_only is True
            and plan.can_write_scene_prose_directly is False
            and plan.can_write_story_facts_directly is False
        )
        if not candidate_only_boundary_enforced:
            add_issue("direct_write_capability_forbidden", "PsychologyVisibilityPlan cannot write prose or story facts directly.")

        tier_policy_enforced = not any(
            code in issue_codes
            for code in [
                "d_tier_full_inner_moment_forbidden",
                "c_tier_full_inner_moment_forbidden",
                "d_tier_word_budget_exceeded",
            ]
        )

        return PsychologyVisibilityPlanValidationReport(
            psychology_visibility_plan_id=plan.psychology_visibility_plan_id,
            passed=not issue_codes,
            issue_codes=issue_codes,
            warning_codes=warning_codes,
            issues=issues,
            warnings=warnings,
            candidate_only_boundary_enforced=candidate_only_boundary_enforced,
            all_tiers_have_visibility_decisions=all_tiers_have_visibility_decisions,
            tier_policy_enforced=tier_policy_enforced,
            raw_psychology_chain_forbidden="raw_psychology_chain_forbidden" not in issue_codes,
            negative_space_safe=negative_space_safe,
        )

    def validate_decision(self, decision: PsychologyVisibilityDecision, *, pov_mode: str = "limited_external") -> list[str]:
        issues: list[str] = []
        visible = decision.visibility_level != "none"
        if not str(decision.character_id or "").strip():
            issues.append("decision_character_id_missing")
        if decision.tier not in PSYCHOLOGY_TIERS:
            issues.append("decision_tier_invalid")
        if decision.visibility_level not in PSYCHOLOGY_VISIBILITY_LEVELS:
            issues.append("decision_visibility_level_invalid")
        if visible and not str(decision.reason or "").strip():
            issues.append("decision_reason_missing")
        if visible and not decision.allowed_channels:
            issues.append("visible_level_channels_missing")
        if any(channel not in PSYCHOLOGY_ALLOWED_CHANNELS for channel in decision.allowed_channels):
            issues.append("visible_level_channels_invalid")
        if not visible and int(decision.max_words or 0) != 0:
            issues.append("none_level_max_words_must_be_zero")
        if visible and int(decision.max_words or 0) <= 0:
            issues.append("visible_level_max_words_missing")
        if decision.tier == "D" and decision.visibility_level == "full_inner_moment":
            issues.append("d_tier_full_inner_moment_forbidden")
        if decision.tier == "C" and decision.visibility_level == "full_inner_moment":
            issues.append("c_tier_full_inner_moment_forbidden")
        if decision.tier == "D" and int(decision.max_words or 0) > 20:
            issues.append("d_tier_word_budget_exceeded")
        if decision.tier == "C" and int(decision.max_words or 0) > 32:
            issues.append("c_tier_word_budget_exceeded")
        if decision.visibility_level == "full_inner_moment":
            strong_reason = "strong" in str(decision.reason or "").casefold() or "close" in str(decision.reason or "").casefold()
            if decision.tier in {"A", "B"} and (pov_mode != "close_limited" or not strong_reason):
                issues.append("full_inner_moment_requires_close_pov_and_strong_reason")
        if decision.raw_psychology_chain_present or self.contains_raw_marker(decision_text(decision)):
            issues.append("raw_psychology_chain_forbidden")
        return sorted(set(issues))

    def validate_negative_space(self, negative_space: PsychologicalNegativeSpace) -> list[str]:
        issues: list[str] = []
        if not str(negative_space.negative_space_id or "").strip():
            issues.append("negative_space_id_missing")
        if not str(negative_space.scene_id or "").strip():
            issues.append("negative_space_scene_id_missing")
        if not str(negative_space.character_id or "").strip():
            issues.append("negative_space_character_id_missing")
        if not str(negative_space.safe_summary or "").strip():
            issues.append("negative_space_safe_summary_missing")
        if not str(negative_space.withheld_psychology_summary or "").strip():
            issues.append("negative_space_withheld_summary_missing")
        if (
            negative_space.raw_psychology_chain_present
            or self.contains_raw_marker(negative_space.safe_summary)
            or self.contains_raw_marker(negative_space.withheld_psychology_summary)
            or self.contains_raw_marker(negative_space.reason)
            or self.contains_raw_marker(negative_space.future_payoff_hint)
        ):
            issues.append("negative_space_raw_chain_forbidden")
        return sorted(set(issues))

    def default_visibility_level_for_tier(self, tier: str) -> str:
        if tier == "A":
            return "short_inner_line"
        if tier == "B":
            return "micro_reaction"
        if tier == "C":
            return "micro_reaction"
        return "behavior_only"

    def default_max_words(self, tier: str, visibility_level: str) -> int:
        if visibility_level == "none":
            return 0
        if tier == "A":
            return 24 if visibility_level == "short_inner_line" else 14
        if tier == "B":
            return 18 if visibility_level == "short_inner_line" else 12
        if tier == "C":
            return 14 if visibility_level == "micro_reaction" else 10
        return 8

    def default_channels_for_level(self, visibility_level: str) -> list[str]:
        if visibility_level == "none":
            return []
        if visibility_level == "behavior_only":
            return ["gesture", "action_choice"]
        if visibility_level == "micro_reaction":
            return ["gesture", "silence_pause"]
        if visibility_level == "short_inner_line":
            return ["one_short_inner_line", "dialogue_subtext"]
        return ["one_short_inner_line"]

    def default_reason_for_tier(self, tier: str, visibility_level: str) -> str:
        if visibility_level == "none":
            return ""
        if tier in {"A", "B"}:
            return f"{tier}-tier psychology is visible only because the scene choice justifies {visibility_level}."
        return f"{tier}-tier psychology remains light and externally visible."

    def forbidden_for_tier(self, tier: str) -> list[str]:
        if tier == "D":
            return ["full_inner_moment", "long interior monologue", "raw psychology chain"]
        if tier == "C":
            return ["full_inner_moment", "long interior monologue", "raw psychology chain"]
        return ["raw psychology chain"]

    def safe_summary(self, value: str) -> str:
        text = str(value or "")
        for marker in RAW_PSYCHOLOGY_MARKERS:
            text = re.sub(re.escape(marker), "[redacted-marker]", text, flags=re.IGNORECASE)
        return " ".join(text.split())[:240]

    def contains_raw_marker(self, value: str) -> bool:
        lowered = str(value or "").casefold()
        return any(marker.casefold() in lowered for marker in RAW_PSYCHOLOGY_MARKERS)

    def safe_issue_message(self, code: str) -> str:
        messages = {
            "psychology_visibility_plan_id_missing": "Psychology visibility plan id is required.",
            "participant_decisions_missing": "At least one participant decision is required.",
            "decision_character_id_missing": "Decision character id is required.",
            "decision_reason_missing": "Visible psychology requires a reason.",
            "visible_level_channels_missing": "Visible psychology requires allowed channels.",
            "visible_level_max_words_missing": "Visible psychology requires a positive word budget.",
            "d_tier_full_inner_moment_forbidden": "D-tier cannot use full inner moment.",
            "c_tier_full_inner_moment_forbidden": "C-tier cannot use full inner moment.",
            "d_tier_word_budget_exceeded": "D-tier word budget must remain minimal.",
            "raw_psychology_chain_forbidden": "Raw psychology chain markers are forbidden.",
            "negative_space_safe_summary_missing": "Negative space requires a safe summary.",
            "negative_space_raw_chain_forbidden": "Negative space cannot contain raw psychology markers.",
            "direct_write_capability_forbidden": "Psychology visibility plans cannot write prose or story facts directly.",
        }
        return messages.get(code, code)


def decision_text(decision: PsychologyVisibilityDecision) -> str:
    values: list[Any] = [
        decision.reason,
        decision.safe_summary,
        *decision.allowed_channels,
        *decision.forbidden,
        *decision.source_psychology_trace_ids,
        *decision.source_context_item_ids,
    ]
    return " ".join(str(value or "") for value in values)
