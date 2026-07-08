from typing import Any, Literal

from pydantic import BaseModel, Field


AnalyzeStoriesFileKind = Literal[
    "framework_package",
    "story_analysis_report",
    "full_book_bundle",
    "cross_chapter_state_package",
    "unknown",
]
AnalyzeStoriesImportStatus = Literal[
    "received",
    "parsed",
    "validated_with_warnings",
    "blocked",
    "ready_for_m2",
]
AnalyzeStoriesRawStorageStatus = Literal["stored", "redacted", "hash_only", "blocked"]
AnalyzeStoriesParseStatus = Literal["not_parsed", "parsed", "parse_failed"]
AnalyzeStoriesIssueSeverity = Literal["warning", "blocking"]
AnalyzeStoriesCompletenessStatus = Literal["complete", "partial", "missing"]
AnalyzeStoriesViewerStatus = Literal["available", "missing", "invalid", "blocked"]
AnalyzeStoriesReviewStatus = Literal["not_reviewed"]
AnalyzeStoriesVerificationScope = Literal["fixture_based", "real_sample", "user_upload"]


class AnalyzeStoriesImportIssue(BaseModel):
    code: str
    severity: AnalyzeStoriesIssueSeverity
    message: str
    artifact_id: str | None = None
    field_path: str | None = None
    safe_detail: str | None = None


class AnalyzeStoriesImportManifest(BaseModel):
    import_id: str
    project_id: str = "local_project"
    source: Literal["analyze_stories"] = "analyze_stories"
    import_status: AnalyzeStoriesImportStatus = "received"
    parse_status: AnalyzeStoriesParseStatus = "not_parsed"
    file_kinds: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    validation_report_id: str | None = None
    input_fingerprint_ids: list[str] = Field(default_factory=list)
    story_analysis_report_ref_ids: list[str] = Field(default_factory=list)
    analyzer_version: str | None = None
    workflow_version: str | None = None
    model: str | None = None
    received_at: str
    created_at: str
    updated_at: str
    version_id: str


class AnalyzeStoriesImportedArtifact(BaseModel):
    artifact_id: str
    import_id: str
    file_kind: AnalyzeStoriesFileKind = "unknown"
    original_filename: str | None = None
    content_sha256: str
    content_length: int
    storage_ref: str | None = None
    payload_ref: str | None = None
    raw_storage_status: AnalyzeStoriesRawStorageStatus = "hash_only"
    parse_status: AnalyzeStoriesParseStatus = "not_parsed"
    top_level_keys: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    safe_error: str | None = None
    created_at: str


class AnalyzeStoriesInputFingerprint(BaseModel):
    fingerprint_id: str
    import_id: str
    artifact_id: str | None = None
    input_filename: str | None = None
    chapter_index: int | None = None
    input_title: str | None = None
    input_content_sha256: str | None = None
    text_length: int | None = None
    analyzer_version: str | None = None
    workflow_version: str | None = None
    model: str | None = None
    processed_at: str | None = None
    completeness_status: AnalyzeStoriesCompletenessStatus = "missing"
    missing_fields: list[str] = Field(default_factory=list)
    created_at: str


class AnalyzeStoriesImportValidationReport(BaseModel):
    report_id: str
    import_id: str
    passed: bool
    can_proceed_to_m2: bool
    passed_basic: bool | None = None
    ready_for_next_step: bool | None = None
    next_step_blockers: list[str] = Field(default_factory=list)
    blocking_issues: list[AnalyzeStoriesImportIssue] = Field(default_factory=list)
    warnings: list[AnalyzeStoriesImportIssue] = Field(default_factory=list)
    detected_file_kinds: list[str] = Field(default_factory=list)
    missing_recommended_fields: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = True
    verification_scope: AnalyzeStoriesVerificationScope | None = None
    safe_summary: str = ""
    created_at: str


class StoryAnalysisReportRef(BaseModel):
    story_analysis_report_ref_id: str
    import_id: str
    artifact_id: str
    source: Literal["analyze_stories"] = "analyze_stories"
    linked_framework_package_id: str | None = None
    viewer_status: AnalyzeStoriesViewerStatus = "missing"
    review_status: AnalyzeStoriesReviewStatus = "not_reviewed"
    safe_title: str | None = None
    safe_summary: str | None = None
    created_at: str


class AnalyzeStoriesImportResult(BaseModel):
    success: bool
    import_id: str
    manifest: AnalyzeStoriesImportManifest
    artifact: AnalyzeStoriesImportedArtifact | None = None
    artifacts: list[AnalyzeStoriesImportedArtifact] = Field(default_factory=list)
    input_fingerprints: list[AnalyzeStoriesInputFingerprint] = Field(default_factory=list)
    story_analysis_report_refs: list[StoryAnalysisReportRef] = Field(default_factory=list)
    validation_report: AnalyzeStoriesImportValidationReport


class AnalyzeStoriesImportDetail(BaseModel):
    manifest: AnalyzeStoriesImportManifest
    artifacts: list[AnalyzeStoriesImportedArtifact] = Field(default_factory=list)
    input_fingerprints: list[AnalyzeStoriesInputFingerprint] = Field(default_factory=list)
    story_analysis_report_refs: list[StoryAnalysisReportRef] = Field(default_factory=list)
    validation_report: AnalyzeStoriesImportValidationReport | None = None


class AnalyzeStoriesImportListResponse(BaseModel):
    imports: list[AnalyzeStoriesImportManifest] = Field(default_factory=list)


class AnalyzeStoriesImportEnvelope(BaseModel):
    declared_file_kind: str | None = None
    original_filename: str | None = None
    artifact: dict[str, Any] | None = None
