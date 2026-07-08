from __future__ import annotations

import re

from app.backend.models.writer_prose_engine import (
    PsychologyVisibilityDecision,
    PsychologyVisibilityPlan,
    SubtextRenderingDecision,
    SubtextRenderingReport,
)


RAW_PSYCHOLOGY_MARKERS = {
    "raw_psychology_chain",
    "raw psychology chain",
    "hidden_reasoning",
    "hidden reasoning",
    "internal reasoning",
    "full psychology chain",
    "provider raw",
    "system prompt",
}


class SubtextRendererService:
    def render(
        self,
        plan: PsychologyVisibilityPlan,
        *,
        language: str | None = None,
    ) -> SubtextRenderingReport:
        issue_codes: list[str] = []
        issues: list[str] = []
        render_language = language or self._language_for_plan(plan)
        decisions = [
            self.render_decision(decision, language=render_language)
            for decision in plan.decisions
        ]

        def add_issue(code: str, message: str) -> None:
            if code not in issue_codes:
                issue_codes.append(code)
                issues.append(message)

        if not plan.decisions:
            add_issue("psychology_visibility_decisions_missing", "Subtext renderer requires visibility decisions.")
        if not plan.no_raw_psychology_chain:
            add_issue("raw_psychology_chain_leaked", "Raw psychology chain is not allowed.")

        for source, rendered in zip(plan.decisions, decisions):
            if source.raw_psychology_chain_present or self.contains_raw_marker(source.safe_summary):
                add_issue("raw_psychology_chain_leaked", "Raw psychology chain marker was present.")
            if not rendered.policy_respected:
                add_issue("psychology_visibility_violation", "Subtext renderer violated tier or visibility policy.")
            if self.contains_raw_marker(rendered.rendered_subtext):
                add_issue("raw_psychology_chain_leaked", "Rendered subtext leaked raw psychology marker.")
            if source.visibility_level != "none" and not rendered.rendered_subtext.strip():
                add_issue("subtext_decision_missing", "Visible psychology decision requires rendered subtext.")

        tier_policy_respected = not any(
            code in issue_codes for code in {"psychology_visibility_violation"}
        )
        interior_line_budget_respected = all(
            decision.interior_line_word_count
            <= self._max_words_for_source(plan.decisions, decision.source_psychology_decision_id)
            for decision in decisions
        )
        if not interior_line_budget_respected:
            add_issue("interior_line_budget_exceeded", "Rendered interior line exceeded its approved budget.")

        raw_forbidden = "raw_psychology_chain_leaked" not in issue_codes
        status = "passed" if not issue_codes else "failed"
        return SubtextRenderingReport(
            subtext_report_id=f"subtext_report_{plan.scene_id}",
            status=status,
            psychology_visibility_decisions_read=bool(plan.decisions),
            subtext_decisions_written=bool(decisions),
            behavior_first_policy_respected=all(
                decision.rendered_channel
                in {"none", "gesture", "action_choice", "silence_pause", "dialogue_subtext", "one_short_inner_line"}
                for decision in decisions
            ),
            tier_policy_respected=tier_policy_respected,
            interior_line_budget_respected=interior_line_budget_respected,
            raw_psychology_chain_forbidden=raw_forbidden,
            negative_space_not_written_as_prose=True,
            decisions=decisions,
            issue_codes=issue_codes,
            issues=issues,
        )

    def render_decision(
        self,
        decision: PsychologyVisibilityDecision,
        *,
        language: str = "en",
    ) -> SubtextRenderingDecision:
        tier = str(decision.tier or "D").strip().upper()
        level = str(decision.visibility_level or "behavior_only").strip()
        zh = language == "zh"
        policy_respected = True
        rendered_channel = "action_choice"
        interior_line = ""
        rendered = ""

        if level == "none":
            rendered_channel = "none"
        elif level == "behavior_only":
            rendered_channel = "action_choice"
            rendered = "这个选择留在可见动作里。" if zh else "The choice stays visible in the way the participant moves."
        elif level == "micro_reaction":
            rendered_channel = "silence_pause"
            rendered = "参与者停顿了一下，随后把压力留在表面。" if zh else "The participant pauses once, then keeps the pressure outside."
        elif level == "short_inner_line":
            rendered_channel = "one_short_inner_line"
            interior_line = self._bounded_inner_line(decision.max_words, language=language)
            rendered = interior_line
        elif level == "full_inner_moment":
            if tier in {"C", "D"}:
                policy_respected = False
                rendered_channel = "action_choice"
                rendered = "参与者把动机留在外部动作里。" if zh else "The participant keeps the motive external."
            else:
                rendered_channel = "one_short_inner_line"
                interior_line = self._bounded_inner_line(min(decision.max_words, 24), language=language)
                rendered = interior_line
        else:
            policy_respected = False
            rendered_channel = "action_choice"
            rendered = "参与者通过动作显出压力。" if zh else "The participant shows pressure through action."

        if tier == "D" and rendered_channel == "one_short_inner_line":
            policy_respected = False
            rendered_channel = "action_choice"
            interior_line = ""
            rendered = "参与者用动作回应，而不是内心解释。" if zh else "The participant answers through action, not inner explanation."
        if tier == "C" and level == "full_inner_moment":
            policy_respected = False

        rendered = self.safe_text(rendered)
        return SubtextRenderingDecision(
            decision_id=f"subtext_{decision.decision_id}",
            source_psychology_decision_id=decision.decision_id,
            character_id=decision.character_id,
            tier=tier,
            visibility_level=level,
            rendered_channel=rendered_channel,
            rendered_subtext=rendered,
            interior_line_word_count=self._word_count(interior_line),
            policy_respected=policy_respected,
            raw_psychology_chain_present=self.contains_raw_marker(rendered),
            source_refs=[decision.decision_id, *decision.source_context_item_ids],
        )

    def safe_text(self, value: str) -> str:
        text = str(value or "")
        for marker in RAW_PSYCHOLOGY_MARKERS:
            text = re.sub(re.escape(marker), "[redacted-marker]", text, flags=re.IGNORECASE)
        return " ".join(text.split())

    def contains_raw_marker(self, value: str) -> bool:
        lowered = str(value or "").casefold()
        return any(marker.casefold() in lowered for marker in RAW_PSYCHOLOGY_MARKERS)

    def _bounded_inner_line(self, max_words: int, *, language: str = "en") -> str:
        if language == "zh":
            return "先选择眼前的风险。"
        words = "Choose the risk before the chance closes".split()
        limit = max(1, int(max_words or 1))
        return " ".join(words[:limit]) + "."

    def _word_count(self, value: str) -> int:
        return len([word for word in re.findall(r"\b\w+\b", str(value or "")) if word])

    def _max_words_for_source(
        self,
        decisions: list[PsychologyVisibilityDecision],
        source_decision_id: str,
    ) -> int:
        for decision in decisions:
            if decision.decision_id == source_decision_id:
                return max(0, int(decision.max_words or 0))
        return 0

    def _language_for_plan(self, plan: PsychologyVisibilityPlan) -> str:
        texts = [
            plan.psychology_visibility_plan_id,
            plan.project_id,
            plan.chapter_id,
            plan.scene_id,
            *plan.source_context_refs,
        ]
        for decision in plan.decisions:
            texts.extend(
                [
                    decision.reason,
                    decision.safe_summary,
                    *decision.allowed_channels,
                    *decision.forbidden,
                    *decision.source_context_item_ids,
                ]
            )
        return "zh" if any(self._contains_cjk(text) for text in texts) else "en"

    def _contains_cjk(self, value: str) -> bool:
        return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", str(value or "")))
