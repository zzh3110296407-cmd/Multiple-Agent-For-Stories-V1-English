from __future__ import annotations

from app.backend.models.writer_prose_engine import (
    ProseStyleProfile,
    WriterPlannerLayerOutput,
    WriterProseDraftPackage,
    WriterQualityInspectionBundle,
)
from app.backend.services.hook_payoff_inspector_service import HookPayoffInspectorService
from app.backend.services.prose_style_inspector_service import ProseStyleInspectorService
from app.backend.services.psychology_overexposure_inspector_service import (
    PsychologyOverexposureInspectorService,
)
from app.backend.services.reader_experience_inspector_service import (
    ReaderExperienceInspectorService,
)
from app.backend.services.subtext_balance_inspector_service import (
    SubtextBalanceInspectorService,
)
from app.backend.services.writer_quality_shared import classify_issues, unique_strings


class WriterQualityInspectionService:
    def __init__(
        self,
        *,
        reader_experience_inspector: ReaderExperienceInspectorService | None = None,
        psychology_overexposure_inspector: PsychologyOverexposureInspectorService | None = None,
        prose_style_inspector: ProseStyleInspectorService | None = None,
        hook_payoff_inspector: HookPayoffInspectorService | None = None,
        subtext_balance_inspector: SubtextBalanceInspectorService | None = None,
    ) -> None:
        self.reader_experience_inspector = reader_experience_inspector or ReaderExperienceInspectorService()
        self.psychology_overexposure_inspector = (
            psychology_overexposure_inspector or PsychologyOverexposureInspectorService()
        )
        self.prose_style_inspector = prose_style_inspector or ProseStyleInspectorService()
        self.hook_payoff_inspector = hook_payoff_inspector or HookPayoffInspectorService()
        self.subtext_balance_inspector = subtext_balance_inspector or SubtextBalanceInspectorService()

    def inspect(
        self,
        package: WriterProseDraftPackage,
        planner_output: WriterPlannerLayerOutput,
        *,
        profile: ProseStyleProfile | None = None,
    ) -> WriterQualityInspectionBundle:
        style = profile or ProseStyleProfile(style_profile_id=package.style_profile_id)
        reader_report = self.reader_experience_inspector.inspect(package, planner_output, style)
        psychology_report = self.psychology_overexposure_inspector.inspect(package, planner_output)
        prose_style_report = self.prose_style_inspector.inspect(package, style)
        hook_payoff_report = self.hook_payoff_inspector.inspect(package, planner_output)
        subtext_report = self.subtext_balance_inspector.inspect(package, planner_output)
        issue_codes = unique_strings(
            reader_report.issue_codes
            + psychology_report.issue_codes
            + prose_style_report.issue_codes
            + hook_payoff_report.issue_codes
            + subtext_report.issue_codes
        )
        repairable, blocking = classify_issues(issue_codes)
        passed = not issue_codes
        return WriterQualityInspectionBundle(
            inspection_bundle_id=f"writer_quality_inspection_bundle_{package.draft_package_id}",
            source_draft_package_id=package.draft_package_id,
            reader_experience_report=reader_report,
            psychology_overexposure_report=psychology_report,
            prose_style_report=prose_style_report,
            hook_payoff_report=hook_payoff_report,
            subtext_balance_report=subtext_report,
            issue_codes=issue_codes,
            repairable_issue_codes=repairable,
            blocking_issue_codes=blocking,
            passed=passed,
            ready_for_revision=bool(repairable) and not blocking,
            ready_for_downstream_gates=passed,
            candidate_only=True,
        )
