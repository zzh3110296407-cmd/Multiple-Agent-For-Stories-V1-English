from __future__ import annotations

from app.backend.models.writer_prose_engine import (
    SubtextBalanceInspectionReport,
    WriterPlannerLayerOutput,
    WriterProseDraftPackage,
)
from app.backend.services.writer_quality_shared import (
    INNER_MONOLOGUE_MARKERS,
    MINOR_ROLE_MARKERS,
    classify_issues,
    contains_any,
)


class SubtextBalanceInspectorService:
    def inspect(
        self,
        package: WriterProseDraftPackage,
        planner_output: WriterPlannerLayerOutput,
    ) -> SubtextBalanceInspectionReport:
        del planner_output
        text = package.candidate_prose
        issue_codes: list[str] = []
        minor_role_count = 0
        if contains_any(text, INNER_MONOLOGUE_MARKERS) and contains_any(text, MINOR_ROLE_MARKERS):
            minor_role_count = 1
            issue_codes.append("minor_role_over_interiorized")
        if not package.subtext_rendering_report.tier_policy_respected:
            issue_codes.append("forbidden_psychology_channel_used")
        if not package.subtext_rendering_report.behavior_first_policy_respected:
            issue_codes.append("subtext_balance_failed")
        if contains_any(
            text,
            {
                "negative_space",
                "withheld_psychology",
                "\u9690\u85cf\u5fc3\u7406",
                "\u672a\u5199\u51fa\u7684\u5fc3\u7406",
            },
        ):
            issue_codes.append("negative_space_leaked")
        repairable, blocking = classify_issues(issue_codes)
        return SubtextBalanceInspectionReport(
            subtext_balance_inspection_report_id=f"subtext_balance_report_{package.draft_package_id}",
            source_draft_package_id=package.draft_package_id,
            subtext_policy_respected=package.subtext_rendering_report.tier_policy_respected,
            negative_space_preserved="negative_space_leaked" not in issue_codes,
            minor_role_interiority_count=minor_role_count,
            issue_codes=issue_codes,
            repairable_issue_codes=repairable,
            blocking_issue_codes=blocking,
            passed=not issue_codes,
            candidate_only=True,
        )
