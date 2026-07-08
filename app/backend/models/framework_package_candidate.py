from typing import Any, Literal

from pydantic import BaseModel, Field


FrameworkPackageCandidateStatus = Literal[
    "created",
    "normalized_with_warnings",
    "blocked",
    "ready_for_workbench_review",
]
FrameworkPackageIssueSeverity = Literal["warning", "blocking"]
FrameworkPackageDiffChangeType = Literal[
    "defaulted",
    "normalized",
    "downgraded",
    "renamed",
    "dropped",
    "blocked",
    "downscoped",
    "moved_to_report_layer",
]
FrameworkPackageDiffSeverity = Literal["info", "warning", "blocking"]
FrameworkPackageVerificationScope = Literal["fixture_based", "real_sample", "user_upload"]


class FrameworkPackageValidationIssue(BaseModel):
    code: str
    severity: FrameworkPackageIssueSeverity
    message: str
    field_path: str | None = None
    artifact_id: str | None = None
    safe_detail: str | None = None


class FrameworkPackageNormalizedDiff(BaseModel):
    diff_id: str
    field_path: str
    change_type: FrameworkPackageDiffChangeType
    before_summary: str | None = None
    after_summary: str | None = None
    reason: str
    severity: FrameworkPackageDiffSeverity = "info"


class FrameworkPackageSourceRef(BaseModel):
    source_ref_id: str
    import_id: str
    artifact_id: str
    artifact_sha256: str
    payload_ref: str | None = None
    source_manifest_id: str | None = None
    source_validation_report_id: str | None = None
    verification_scope: FrameworkPackageVerificationScope | None = None
    created_at: str


class FrameworkPackageNormalizationReport(BaseModel):
    normalization_report_id: str
    candidate_id: str
    import_id: str
    artifact_id: str
    passed: bool
    can_proceed_to_m4_workbench: bool
    blocking_issues: list[FrameworkPackageValidationIssue] = Field(default_factory=list)
    warnings: list[FrameworkPackageValidationIssue] = Field(default_factory=list)
    normalized_diffs: list[FrameworkPackageNormalizedDiff] = Field(default_factory=list)
    detected_counts: dict[str, int] = Field(default_factory=dict)
    requires_user_confirmation: bool = True
    safe_summary: str = ""
    created_at: str


class FrameworkPackageCandidate(BaseModel):
    candidate_id: str
    import_id: str
    artifact_id: str
    project_id: str = "local_project"
    source: Literal["analyze_stories"] = "analyze_stories"
    candidate_status: FrameworkPackageCandidateStatus = "created"
    normalized_framework_package: dict[str, Any] | None = None
    normalization_report_id: str
    source_ref: FrameworkPackageSourceRef
    artifact_sha256: str
    input_fingerprint_ids: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = True
    can_proceed_to_m4_workbench: bool = False
    created_at: str
    updated_at: str
    version_id: str


class FrameworkPackageCandidateResult(BaseModel):
    success: bool
    candidate: FrameworkPackageCandidate
    normalization_report: FrameworkPackageNormalizationReport


class FrameworkPackageCandidateDetail(BaseModel):
    candidate: FrameworkPackageCandidate
    normalization_report: FrameworkPackageNormalizationReport | None = None


class FrameworkPackageCandidateListResponse(BaseModel):
    candidates: list[FrameworkPackageCandidate] = Field(default_factory=list)
