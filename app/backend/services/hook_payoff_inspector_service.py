from __future__ import annotations

from app.backend.models.writer_prose_engine import (
    HookPayoffInspectionReport,
    WriterPlannerLayerOutput,
    WriterProseDraftPackage,
)
from app.backend.services.writer_quality_shared import (
    ABSTRACT_MARKERS,
    CONCRETE_ENDING_MARKERS,
    classify_issues,
    contains_any,
)


class HookPayoffInspectorService:
    def inspect(
        self,
        package: WriterProseDraftPackage,
        planner_output: WriterPlannerLayerOutput,
    ) -> HookPayoffInspectionReport:
        text = package.candidate_prose
        hook = planner_output.scene_prose_plan.opening_hook
        ending = planner_output.scene_prose_plan.ending_pull
        opening_concrete = package.opening_hook_reflected and not _mood_only(hook)
        ending_concrete = package.ending_pull_reflected and (
            contains_any(text, CONCRETE_ENDING_MARKERS) or not _mood_only(ending)
        )
        question_advanced = contains_any(
            text,
            {
                "question",
                "next",
                "risk",
                "choice",
                "cost",
                "\u4e0b\u4e00\u6b65",
                "\u95ee\u9898",
                "\u98ce\u9669",
                "\u9009\u62e9",
                "\u4ee3\u4ef7",
            },
        )
        issue_codes: list[str] = []
        if not opening_concrete:
            issue_codes.append("opening_hook_too_abstract")
        if not ending_concrete:
            issue_codes.append("ending_pull_too_abstract")
        if not question_advanced:
            issue_codes.append("reader_question_not_advanced")
        if not opening_concrete or not ending_concrete:
            issue_codes.append("hook_payoff_missing")
        repairable, blocking = classify_issues(issue_codes)
        return HookPayoffInspectionReport(
            hook_payoff_inspection_report_id=f"hook_payoff_report_{package.draft_package_id}",
            source_draft_package_id=package.draft_package_id,
            opening_hook_concrete=opening_concrete,
            ending_pull_concrete=ending_concrete,
            reader_question_advanced=question_advanced,
            issue_codes=issue_codes,
            repairable_issue_codes=repairable,
            blocking_issue_codes=blocking,
            passed=not issue_codes,
            candidate_only=True,
        )


def _mood_only(text: str) -> bool:
    value = str(text or "").casefold()
    if not value.strip():
        return True
    return contains_any(value, ABSTRACT_MARKERS) and not contains_any(
        value,
        {
            "opens",
            "moves",
            "chooses",
            "decides",
            "\u6253\u5f00",
            "\u884c\u52a8",
            "\u9009\u62e9",
            "\u51b3\u5b9a",
        },
    )
