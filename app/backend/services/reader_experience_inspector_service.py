from __future__ import annotations

from app.backend.models.writer_prose_engine import (
    ProseStyleProfile,
    ReaderExperienceReport,
    WriterPlannerLayerOutput,
    WriterProseDraftPackage,
)
from app.backend.services.writer_quality_shared import (
    ABSTRACT_MARKERS,
    CONCRETE_ENDING_MARKERS,
    DIALOGUE_OR_DECISION_MARKERS,
    EMPTY_MYSTERY_MARKERS,
    VISIBLE_ACTION_MARKERS,
    classify_issues,
    contains_any,
)


class ReaderExperienceInspectorService:
    def inspect(
        self,
        package: WriterProseDraftPackage,
        planner_output: WriterPlannerLayerOutput,
        profile: ProseStyleProfile | None = None,
    ) -> ReaderExperienceReport:
        style = profile or ProseStyleProfile(style_profile_id=package.style_profile_id)
        text = package.candidate_prose
        issue_codes: list[str] = []

        plot_turn_present = package.conflict_turn_reflected or contains_any(
            text,
            {"turn", "risk", "choice", "\u8f6c\u6298", "\u98ce\u9669", "\u9009\u62e9"},
        )
        visible_action_present = package.visible_action_present or contains_any(text, VISIBLE_ACTION_MARKERS)
        dialogue_or_decision_present = package.dialogue_or_decision_present or contains_any(
            text,
            DIALOGUE_OR_DECISION_MARKERS,
        )
        ending_pull_present = package.ending_pull_reflected or contains_any(text, CONCRETE_ENDING_MARKERS)
        scene_reader_value_present = (
            package.required_progression_delta_reflected
            or planner_output.scene_prose_plan.reader_value.casefold() in text.casefold()
            or contains_any(
                text,
                {
                    "changes",
                    "cost",
                    "risk",
                    "changed",
                    "\u6539\u53d8",
                    "\u4ee3\u4ef7",
                    "\u98ce\u9669",
                    "\u4e0b\u4e00\u6b65",
                },
            )
        )
        reader_question_advanced = contains_any(
            text,
            {"question", "next", "risk", "what", "\u4e0b\u4e00\u6b65", "\u95ee\u9898", "\u98ce\u9669"},
        )
        reader_question_raised = reader_question_advanced or "?" in text or "\uff1f" in text

        if not plot_turn_present:
            issue_codes.append("plot_turn_missing")
        if not visible_action_present:
            issue_codes.append("visible_action_missing")
        if not dialogue_or_decision_present:
            issue_codes.append("dialogue_or_decision_missing")
        if not ending_pull_present:
            issue_codes.append("ending_pull_missing")
        if not scene_reader_value_present:
            issue_codes.append("scene_reader_value_missing")
        if package.empty_mystery_density > style.suspense_style.empty_mystery_budget or contains_any(
            text,
            EMPTY_MYSTERY_MARKERS,
        ):
            issue_codes.append("empty_mystery_too_high")
        if package.abstract_language_density > style.scene_style.abstract_language_budget or contains_any(
            text,
            ABSTRACT_MARKERS,
        ):
            issue_codes.append("abstract_language_too_high")
        if package.adjective_density > style.adjective_budget:
            issue_codes.append("adjective_density_too_high")

        repairable, blocking = classify_issues(issue_codes)
        return ReaderExperienceReport(
            reader_experience_report_id=f"reader_experience_report_{package.draft_package_id}",
            project_id=package.project_id,
            chapter_id=package.chapter_id,
            scene_id=package.scene_id,
            scene_index=package.scene_index,
            source_draft_package_id=package.draft_package_id,
            plot_turn_present=plot_turn_present,
            visible_action_present=visible_action_present,
            dialogue_or_decision_present=dialogue_or_decision_present,
            ending_pull_present=ending_pull_present,
            scene_reader_value_present=scene_reader_value_present,
            reader_question_answered_or_advanced=reader_question_advanced,
            reader_question_raised=reader_question_raised,
            empty_mystery_density=package.empty_mystery_density,
            abstract_language_density=package.abstract_language_density,
            adjective_density=package.adjective_density,
            issue_codes=issue_codes,
            repairable_issue_codes=repairable,
            blocking_issue_codes=blocking,
            passed=not issue_codes,
            candidate_only=True,
        )
