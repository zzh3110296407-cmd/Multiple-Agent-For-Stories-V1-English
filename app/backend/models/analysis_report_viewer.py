from typing import Any, Literal

from pydantic import BaseModel, Field


AnalysisReportViewerStatus = Literal[
    "created",
    "available",
    "available_with_warnings",
    "blocked",
]
AnalysisReportReviewStatus = Literal[
    "not_reviewed",
    "reviewed",
    "flagged",
    "dismissed",
]
AnalysisReportIssueSeverity = Literal["warning", "blocking"]
AnalysisReportReferenceType = Literal[
    "import",
    "artifact",
    "input_fingerprint",
    "framework_candidate",
    "normalization_report",
    "macro_component",
    "report_section",
    "external_ref",
]
AnalysisReportReferenceRelationship = Literal[
    "explains",
    "supports",
    "warns_about",
    "contradicts",
    "unlinked",
]


class AnalysisReportViewerIssue(BaseModel):
    code: str
    severity: AnalysisReportIssueSeverity = "warning"
    message: str
    field_path: str | None = None
    safe_detail: str | None = None


class AnalysisReportViewerState(BaseModel):
    viewer_state_id: str
    project_id: str = "local_project"
    source: Literal["analyze_stories"] = "analyze_stories"
    story_analysis_report_ref_id: str
    import_id: str
    artifact_id: str
    linked_framework_package_id: str | None = None
    viewer_status: AnalysisReportViewerStatus = "created"
    review_status: AnalysisReportReviewStatus = "not_reviewed"
    safe_title: str = ""
    safe_summary: str = ""
    section_view_ids: list[str] = Field(default_factory=list)
    reference_link_ids: list[str] = Field(default_factory=list)
    warning_count: int = 0
    blocking_issue_count: int = 0
    warnings: list[AnalysisReportViewerIssue] = Field(default_factory=list)
    blocking_issues: list[AnalysisReportViewerIssue] = Field(default_factory=list)
    safe_notice: str = (
        "Story analysis reports are human-readable explanation only; they do not "
        "activate framework, generation constraints, memory, events, state changes, "
        "chapter archives, or narrative debts."
    )
    created_at: str
    updated_at: str
    version_id: str


class AnalysisReportSectionView(BaseModel):
    section_view_id: str
    viewer_state_id: str
    story_analysis_report_ref_id: str
    section_index: int
    section_id: str
    title: str
    section_type: str = "other"
    inferred_section_type: bool = False
    display_status: Literal["visible", "collapsed"] = "visible"
    safe_preview: str = ""
    safe_field_paths: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    created_at: str
    version_id: str


class AnalysisReportReferenceLink(BaseModel):
    reference_link_id: str
    viewer_state_id: str
    story_analysis_report_ref_id: str
    source_type: AnalysisReportReferenceType
    source_id: str
    source_label: str
    relationship: AnalysisReportReferenceRelationship = "supports"
    field_path: str | None = None
    safe_summary: str = ""
    created_at: str
    version_id: str


class AnalysisReportViewerResult(BaseModel):
    success: bool
    viewer_state: AnalysisReportViewerState
    section_views: list[AnalysisReportSectionView] = Field(default_factory=list)
    reference_links: list[AnalysisReportReferenceLink] = Field(default_factory=list)


class AnalysisReportViewerDetail(BaseModel):
    viewer_state: AnalysisReportViewerState
    section_views: list[AnalysisReportSectionView] = Field(default_factory=list)
    reference_links: list[AnalysisReportReferenceLink] = Field(default_factory=list)


class AnalysisReportViewerListResponse(BaseModel):
    viewer_states: list[AnalysisReportViewerState] = Field(default_factory=list)


class AnalysisReportViewerActionRequest(BaseModel):
    note: str | None = None


class AnalysisReportViewerReviewResult(BaseModel):
    success: bool
    viewer_state: AnalysisReportViewerState
