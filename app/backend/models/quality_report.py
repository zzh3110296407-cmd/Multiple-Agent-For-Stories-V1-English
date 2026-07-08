from typing import Any

from pydantic import BaseModel, Field

from app.backend.models.quality import QualityReport


class LegacyQualityCheck(BaseModel):
    name: str
    status: str
    summary: str


class LegacyQualityReportSnapshot(BaseModel):
    quality_report_id: str
    target_type: str = ""
    target_id: str = ""
    overall_status: str = ""
    checks: list[LegacyQualityCheck] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)
    created_at: str = ""
    project_id: str = "local_project"
    scene_id: str = ""
    revision_id: str = ""
    passed: bool = False
    warnings: list[Any] = Field(default_factory=list)
    blocking_issues: list[Any] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    check_results: list[Any] = Field(default_factory=list)
    semantic_check_status: str = "not_run"
    summary: str = ""
    generated_by: str = ""
    version_id: str = ""


QualityCheck = LegacyQualityCheck

__all__ = [
    "QualityReport",
    "LegacyQualityCheck",
    "LegacyQualityReportSnapshot",
    "QualityCheck",
]
