from __future__ import annotations

from app.backend.models.writer_prose_engine import (
    PsychologyOverexposureReport,
    WriterPlannerLayerOutput,
    WriterProseDraftPackage,
)
from app.backend.services.writer_quality_shared import (
    INNER_MONOLOGUE_MARKERS,
    MINOR_ROLE_MARKERS,
    PSYCHOLOGY_EXPLANATION_MARKERS,
    blocking_markers,
    classify_issues,
    contains_any,
    word_count,
)


class PsychologyOverexposureInspectorService:
    def inspect(
        self,
        package: WriterProseDraftPackage,
        planner_output: WriterPlannerLayerOutput,
    ) -> PsychologyOverexposureReport:
        del planner_output
        text = package.candidate_prose
        issue_codes: list[str] = []
        blocking = blocking_markers(text)
        issue_codes.extend(blocking)
        interior_count = sum(1 for marker in INNER_MONOLOGUE_MARKERS if marker.casefold() in text.casefold())
        minor_count = 0
        if interior_count and contains_any(text, MINOR_ROLE_MARKERS):
            minor_count = interior_count
            issue_codes.append("minor_role_over_interiorized")
        psychology_count = interior_count + sum(
            1 for marker in PSYCHOLOGY_EXPLANATION_MARKERS if marker.casefold() in text.casefold()
        )
        density = round(psychology_count / max(1, word_count(text)), 4)
        action_replaced = contains_any(
            text,
            {"is about", "everyone understands", "\u89e3\u91ca\u4e86\u52a8\u673a", "\u5185\u5fc3\u539f\u56e0"},
        )
        if density > 0.08 or psychology_count >= 3:
            issue_codes.append("psychology_overexposed")
        if interior_count >= 2:
            issue_codes.append("interior_monologue_not_earned")
        if action_replaced:
            issue_codes.append("action_replaced_by_explanation")
        if not package.subtext_rendering_report.tier_policy_respected:
            issue_codes.append("subtext_should_be_behavior")

        repairable, blocking_codes = classify_issues(issue_codes)
        return PsychologyOverexposureReport(
            psychology_overexposure_report_id=f"psychology_overexposure_report_{package.draft_package_id}",
            project_id=package.project_id,
            chapter_id=package.chapter_id,
            scene_id=package.scene_id,
            scene_index=package.scene_index,
            source_draft_package_id=package.draft_package_id,
            psychology_density=density,
            interior_monologue_count=interior_count,
            minor_role_interiority_count=minor_count,
            raw_psychology_chain_detected="raw_psychology_chain_leak" in issue_codes,
            action_replaced_by_explanation=action_replaced,
            subtext_policy_respected=package.subtext_rendering_report.tier_policy_respected,
            issue_codes=issue_codes,
            repairable_issue_codes=repairable,
            blocking_issue_codes=blocking_codes,
            passed=not issue_codes,
            candidate_only=True,
        )
