from typing import Literal

from pydantic import BaseModel, Field


BundleReliabilityLevel = Literal[
    "stable",
    "validated_with_warnings",
    "provisional",
    "blocked",
]
BundleStatus = Literal["detected", "validated", "validated_with_warnings", "blocked"]
BundleIssueSeverity = Literal["info", "warning", "blocking"]


class BundleValidationIssue(BaseModel):
    code: str
    severity: BundleIssueSeverity = "warning"
    field_path: str | None = None
    chapter_index: int | None = None
    artifact_id: str | None = None
    safe_detail: str | None = None
    blocks_reference: bool = False
    blocks_m6_adapter: bool = True


class BundleChapterEntry(BaseModel):
    entry_id: str
    bundle_manifest_id: str
    chapter_index: int | None = None
    chapter_order: int
    input_filename: str | None = None
    input_title_safe: str | None = None
    input_title_length: int = 0
    input_title_redacted: bool = False
    input_content_sha256: str | None = None
    source_input_meta_ref: str | None = None
    framework_package_ref: str | None = None
    story_analysis_report_ref: str | None = None
    next_pack_ref: str | None = None
    status: str = "unknown"
    status_reason_safe: str | None = None
    generated_artifacts: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    blocking_codes: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class BundleChapterInventory(BaseModel):
    chapter_inventory_id: str
    bundle_manifest_id: str
    import_id: str
    artifact_id: str
    declared_chapter_count: int | None = None
    detected_chapter_count: int = 0
    chapter_indexes: list[int] = Field(default_factory=list)
    duplicate_chapter_indexes: list[int] = Field(default_factory=list)
    missing_chapter_indexes: list[int] = Field(default_factory=list)
    entries: list[BundleChapterEntry] = Field(default_factory=list)
    warning_count: int = 0
    blocking_issue_count: int = 0
    safe_summary: str = ""
    created_at: str
    version_id: str


class BundleChapterFingerprintAudit(BaseModel):
    fingerprint_audit_id: str
    bundle_manifest_id: str
    import_id: str
    artifact_id: str
    checked_chapter_count: int = 0
    comparable_m1_fingerprint_count: int = 0
    missing_input_hash_count: int = 0
    artifact_hash_used_as_input_hash_count: int = 0
    blank_input_filename_count: int = 0
    redacted_input_title_count: int = 0
    missing_metadata_count: int = 0
    mismatch_count: int = 0
    issue_codes: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str
    version_id: str


class CrossChapterStateReferenceCheck(BaseModel):
    cross_chapter_reference_check_id: str
    bundle_manifest_id: str
    import_id: str
    artifact_id: str
    reference_count: int = 0
    missing_reference_count: int = 0
    invalid_reference_count: int = 0
    referenced_chapter_indexes: list[int] = Field(default_factory=list)
    missing_chapter_indexes: list[int] = Field(default_factory=list)
    advisory_write_policy_only: bool = True
    issue_codes: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str
    version_id: str


class BundleFrameworkReportConsistencyCheck(BaseModel):
    consistency_check_id: str
    bundle_manifest_id: str
    import_id: str
    artifact_id: str
    linked_framework_candidate_id: str | None = None
    linked_story_analysis_report_ref_id: str | None = None
    linked_framework_candidate_ids: list[str] = Field(default_factory=list)
    linked_story_analysis_report_ref_ids: list[str] = Field(default_factory=list)
    framework_context_available: bool = False
    report_context_available: bool = False
    chapter_count_match: bool | None = None
    chapter_index_match: bool | None = None
    mismatch_count: int = 0
    issue_codes: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str
    version_id: str


class FullBookBundleValidationReport(BaseModel):
    validation_report_id: str
    bundle_manifest_id: str
    import_id: str
    artifact_id: str
    passed: bool
    reliability_level: BundleReliabilityLevel = "blocked"
    bundle_status: BundleStatus = "blocked"
    can_be_used_as_reference: bool = False
    can_proceed_to_m6_adapter: bool = False
    blocking_issues: list[BundleValidationIssue] = Field(default_factory=list)
    warnings: list[BundleValidationIssue] = Field(default_factory=list)
    info: list[BundleValidationIssue] = Field(default_factory=list)
    issue_counts: dict[str, int] = Field(default_factory=dict)
    safe_summary: str = ""
    created_at: str
    version_id: str


class FullBookBundleManifest(BaseModel):
    bundle_manifest_id: str
    import_id: str
    artifact_id: str
    file_kind: str
    source: Literal["analyze_stories"] = "analyze_stories"
    bundle_id: str | None = None
    schema_version: str | None = None
    contract_version: str | None = None
    exporter_version: str | None = None
    run_id: str | None = None
    declared_chapter_count: int | None = None
    detected_chapter_count: int = 0
    chapter_inventory_id: str | None = None
    fingerprint_audit_id: str | None = None
    cross_chapter_reference_check_id: str | None = None
    consistency_check_id: str | None = None
    validation_report_id: str | None = None
    reliability_level: BundleReliabilityLevel = "blocked"
    bundle_status: BundleStatus = "detected"
    can_be_used_as_reference: bool = False
    can_proceed_to_m6_adapter: bool = False
    source_ref: dict[str, str | None] = Field(default_factory=dict)
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class FullBookBundleValidationResult(BaseModel):
    success: bool
    manifest: FullBookBundleManifest
    chapter_inventory: BundleChapterInventory
    fingerprint_audit: BundleChapterFingerprintAudit
    cross_chapter_reference_check: CrossChapterStateReferenceCheck
    consistency_check: BundleFrameworkReportConsistencyCheck
    validation_report: FullBookBundleValidationReport


class FullBookBundleListResponse(BaseModel):
    bundles: list[FullBookBundleManifest] = Field(default_factory=list)


class FullBookBundleDetail(BaseModel):
    manifest: FullBookBundleManifest
    chapter_inventory: BundleChapterInventory | None = None
    fingerprint_audit: BundleChapterFingerprintAudit | None = None
    cross_chapter_reference_check: CrossChapterStateReferenceCheck | None = None
    consistency_check: BundleFrameworkReportConsistencyCheck | None = None
    validation_report: FullBookBundleValidationReport | None = None


class FullBookBundleValidationRequest(BaseModel):
    artifact_id: str | None = None
    linked_framework_candidate_id: str | None = None
    linked_story_analysis_report_ref_id: str | None = None
    linked_framework_candidate_ids: list[str] = Field(default_factory=list)
    linked_story_analysis_report_ref_ids: list[str] = Field(default_factory=list)
