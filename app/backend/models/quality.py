from typing import Optional

from pydantic import BaseModel, Field

from app.backend.models.scene_generation import SceneQualityReport


class QualityIssue(BaseModel):
    issue_id: str
    category: str
    severity: str
    message: str
    evidence: Optional[str] = None
    related_object_type: Optional[str] = None
    related_object_id: Optional[str] = None
    suggested_action: Optional[str] = None
    user_visible: bool = True
    technical_summary: str = ""
    source_refs: list[str] = Field(default_factory=list)
    suggested_repair_types: list[str] = Field(default_factory=list)
    technical_metadata: dict = Field(default_factory=dict)


class QualityCheckResult(BaseModel):
    check_id: str
    check_name: str
    passed: bool
    status: str = "completed"
    issues: list[QualityIssue] = Field(default_factory=list)
    summary: Optional[str] = None


class QualityReport(BaseModel):
    quality_report_id: str
    project_id: str = "local_project"
    target_type: str = ""
    target_id: str = ""
    scene_id: str = ""
    revision_id: str = ""
    passed: bool = False
    warnings: list[QualityIssue] = Field(default_factory=list)
    blocking_issues: list[QualityIssue] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    continuity_checked: bool = False
    continuity_gate_run_id: str = ""
    continuity_checked_at: str = ""
    continuity_passed: bool = True
    continuity_issue_ids: list[str] = Field(default_factory=list)
    blocking_continuity_issue_ids: list[str] = Field(default_factory=list)
    accepted_continuity_issue_ids: list[str] = Field(default_factory=list)
    check_results: list[QualityCheckResult] = Field(default_factory=list)
    semantic_check_status: str = "not_run"
    summary: Optional[str] = None
    quality_degraded: bool = False
    confirmation_block_reason: str = ""
    generated_by: str = "quality_check_service"
    version_id: str = "quality_m9_001"
    created_at: str = ""


class QualityCheckResponse(BaseModel):
    success: bool = True
    report: QualityReport
    embedded_report: SceneQualityReport
    target_type: str
    target_id: str


def to_embedded_scene_quality_report(report: QualityReport) -> SceneQualityReport:
    return SceneQualityReport(
        quality_report_id=report.quality_report_id,
        passed=report.passed,
        warnings=[
            issue.message
            for issue in report.warnings
            if issue.user_visible
        ],
        blocking_issues=[
            issue.message
            for issue in report.blocking_issues
            if issue.user_visible
        ],
        requires_user_confirmation=report.requires_user_confirmation,
        continuity_checked=report.continuity_checked,
        continuity_gate_run_id=report.continuity_gate_run_id,
        continuity_checked_at=report.continuity_checked_at,
        continuity_passed=report.continuity_passed,
        continuity_issue_ids=report.continuity_issue_ids,
        blocking_continuity_issue_ids=report.blocking_continuity_issue_ids,
        accepted_continuity_issue_ids=report.accepted_continuity_issue_ids,
        semantic_check_status=report.semantic_check_status,
        summary=report.summary or "",
        quality_degraded=report.quality_degraded,
        confirmation_block_reason=report.confirmation_block_reason,
    )
