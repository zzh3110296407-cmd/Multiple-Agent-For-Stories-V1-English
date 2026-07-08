from typing import Literal

from pydantic import BaseModel, Field


ReadinessStatus = Literal["ready", "ready_with_warnings", "blocked", "fixture_only"]
PackageStatus = Literal["ready", "ready_with_warnings", "blocked", "fixture"]
PackageType = Literal["real_project_final_package", "fixture_final_story_package"]
ExportStatus = Literal["created", "blocked", "fixture_created", "failed"]
SnapshotStatus = Literal["created", "fixture", "blocked"]
ExportFormat = Literal["json_snapshot"]
FinalStoryPackageDownloadFormat = Literal["txt", "markdown", "json"]
ViewerPanel = Literal["preview", "source_lineage", "evidence_index", "safety_audit", "sections"]
PreviewContentMode = Literal["full_text", "table", "summary", "lineage", "audit"]
AuthorityStatus = Literal[
    "formal_story_fact",
    "user_confirmed",
    "reference_only",
    "candidate",
    "proposal",
    "unconfirmed_draft",
    "fixture",
    "unknown",
]
IssueSeverity = Literal["blocking", "warning", "info"]
SectionValidationStatus = Literal["present", "missing", "warning", "blocked"]

SectionType = Literal[
    "complete_story_text",
    "chapter_scene_index",
    "character_table",
    "world_canvas_summary",
    "relationship_state_summary",
    "key_event_timeline",
    "user_locked_constraints",
    "style_and_tone",
    "source_lineage",
    "known_residuals",
    "other",
]


class FinalStoryPackageReadinessEvaluateRequest(BaseModel):
    allow_fixture: bool = False
    persist: bool = True
    safe_user_note: str = ""


class FinalStoryPackage(BaseModel):
    final_story_package_id: str
    project_id: str
    package_status: PackageStatus
    package_type: PackageType
    readiness_status: ReadinessStatus
    real_final_confirmation_exists: bool
    not_real_project_final_package: bool
    complete_story_text_ref: str = ""
    chapter_scene_index_ref: str = ""
    character_table_ref: str = ""
    world_canvas_summary_ref: str = ""
    relationship_state_summary_ref: str = ""
    key_event_timeline_ref: str = ""
    user_locked_constraints_ref: str = ""
    style_and_tone_ref: str = ""
    manifest_id: str
    validation_report_id: str
    readiness_gate_id: str
    source_ref_ids: list[str] = Field(default_factory=list)
    version_id: str
    created_at: str
    updated_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class FinalStoryPackageManifest(BaseModel):
    manifest_id: str
    final_story_package_id: str
    project_id: str
    package_type: PackageType
    readiness_status: ReadinessStatus
    content_sections: list[str] = Field(default_factory=list)
    declared_chapter_count: int = 0
    declared_scene_count: int = 0
    detected_chapter_count: int = 0
    detected_scene_count: int = 0
    source_version_ids: list[str] = Field(default_factory=list)
    source_ref_ids: list[str] = Field(default_factory=list)
    final_confirmation_decision_id: str = ""
    fixture_reason: str = ""
    not_real_project_final_package: bool
    created_at: str
    updated_at: str
    safe_summary: str


class FinalStoryPackageSection(BaseModel):
    section_id: str
    final_story_package_id: str
    section_type: SectionType
    content_ref: str
    safe_preview: str = ""
    item_count: int = 0
    source_ref_ids: list[str] = Field(default_factory=list)
    validation_status: SectionValidationStatus
    warnings: list[str] = Field(default_factory=list)
    created_at: str


class FinalStoryPackageSourceRef(BaseModel):
    source_ref_id: str
    final_story_package_id: str
    source_object_type: str
    source_object_id: str
    source_version_id: str = ""
    authority_status: AuthorityStatus
    can_be_plugin_input_truth: bool
    reason: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str


class FinalStoryPackageValidationReport(BaseModel):
    validation_report_id: str
    final_story_package_id: str
    project_id: str
    passed: bool
    package_ready: bool
    validation_status: ReadinessStatus
    missing_required_sections: list[str] = Field(default_factory=list)
    blocking_issue_ids: list[str] = Field(default_factory=list)
    warning_issue_ids: list[str] = Field(default_factory=list)
    has_complete_story_text: bool
    has_chapter_scene_index: bool
    has_character_table: bool
    has_world_canvas_summary: bool
    has_relationship_state_summary: bool
    has_key_event_timeline: bool
    has_user_locked_constraints: bool
    has_style_and_tone: bool
    has_final_confirmation_status: bool
    has_version_id: bool
    has_source_refs: bool
    safe_summary: str
    created_at: str


class FinalStoryPackageReadinessGate(BaseModel):
    readiness_gate_id: str
    project_id: str
    final_story_package_id: str
    readiness_status: ReadinessStatus
    can_create_real_final_story_package: bool
    can_create_fixture_package: bool
    final_confirmation_exists: bool
    story_draft_complete_exists: bool
    unresolved_blocking_continuity_issue_exists: bool
    pending_formal_apply_proposal_exists: bool
    pending_propagation_review_that_blocks_final_confirmation_exists: bool
    depends_on_unconfirmed_draft_or_candidate: bool
    depends_on_proposal_as_truth: bool
    uses_fixture: bool
    not_real_project_final_package: bool
    blocking_issue_ids: list[str] = Field(default_factory=list)
    warning_issue_ids: list[str] = Field(default_factory=list)
    recommended_next_step: Literal[
        "export_final_story_package_in_m2",
        "resolve_blocking_issues",
        "complete_story_draft_confirmation",
        "resolve_pending_proposals",
        "review_propagation_tasks",
        "use_fixture_only",
        "not_ready",
    ]
    safe_summary: str
    created_at: str
    updated_at: str


class FinalStoryPackageReadinessIssue(BaseModel):
    issue_id: str
    readiness_gate_id: str
    severity: IssueSeverity
    code: str
    user_visible_message: str
    recommended_resolution: str
    source_refs: list[str] = Field(default_factory=list)
    created_at: str


class FinalStoryPackageReadinessStatusResponse(BaseModel):
    gate_count: int = 0
    package_count: int = 0
    latest_readiness_gate_id: str | None = None
    latest_final_story_package_id: str | None = None
    latest_validation_report_id: str | None = None
    latest_readiness_status: ReadinessStatus | None = None
    latest_package_type: PackageType | None = None
    latest_not_real_project_final_package: bool = False
    latest_blocking_issue_count: int = 0
    latest_warning_issue_count: int = 0
    allowed_storage_files: list[str] = Field(default_factory=list)
    forbidden_story_fact_files: list[str] = Field(default_factory=list)
    forbidden_plugin_runtime_files: list[str] = Field(default_factory=list)
    final_story_package_is_only_future_plugin_input: bool = True
    plugins_cannot_read_unconfirmed_drafts: bool = True
    phase6_proposal_is_not_formal_record: bool = True
    plugin_output_must_not_write_original_story_facts: bool = True
    fixture_package_is_not_real_final_package: bool = True
    safe_summary: str


class FinalStoryPackageReadinessEvaluationResponse(BaseModel):
    success: bool
    readiness_gate: FinalStoryPackageReadinessGate
    final_story_package: FinalStoryPackage
    manifest: FinalStoryPackageManifest
    validation_report: FinalStoryPackageValidationReport
    sections: list[FinalStoryPackageSection] = Field(default_factory=list)
    source_refs: list[FinalStoryPackageSourceRef] = Field(default_factory=list)
    issues: list[FinalStoryPackageReadinessIssue] = Field(default_factory=list)
    safe_summary: str


class FinalStoryPackageReadinessIssueListResponse(BaseModel):
    readiness_gate_id: str
    issues: list[FinalStoryPackageReadinessIssue] = Field(default_factory=list)
    total_count: int = 0


class FinalStoryPackageExportRequest(BaseModel):
    readiness_gate_id: str
    allow_fixture_export: bool = False
    export_format: ExportFormat = "json_snapshot"
    safe_user_note: str = ""


class FinalStoryPackageExportRun(BaseModel):
    export_run_id: str
    project_id: str
    readiness_gate_id: str
    validation_report_id: str
    final_story_package_id: str
    manifest_id: str
    snapshot_id: str
    evidence_index_id: str
    safety_audit_id: str
    export_format: ExportFormat
    export_status: ExportStatus
    package_type: PackageType
    readiness_status: ReadinessStatus
    can_be_used_by_plugins: bool
    not_real_project_final_package: bool
    source_ref_ids: list[str] = Field(default_factory=list)
    section_ids: list[str] = Field(default_factory=list)
    blocked_issue_ids: list[str] = Field(default_factory=list)
    warning_issue_ids: list[str] = Field(default_factory=list)
    safe_user_note: str = ""
    created_at: str
    safe_summary: str


class FinalStoryPackagePreviewSection(BaseModel):
    preview_section_id: str
    snapshot_id: str
    section_type: SectionType
    display_order: int
    title: str
    content_mode: PreviewContentMode
    content_ref: str
    content_hash: str
    safe_preview: str
    item_count: int
    source_ref_ids: list[str] = Field(default_factory=list)
    created_at: str


class FinalStoryPackageSnapshot(BaseModel):
    snapshot_id: str
    project_id: str
    final_story_package_id: str
    readiness_gate_id: str
    validation_report_id: str
    manifest_id: str
    package_type: PackageType
    readiness_status: ReadinessStatus
    snapshot_status: SnapshotStatus
    content_schema_version: str
    source_ref_ids: list[str] = Field(default_factory=list)
    source_version_ids: list[str] = Field(default_factory=list)
    preview_section_ids: list[str] = Field(default_factory=list)
    complete_story_text: str = ""
    complete_story_text_hash: str = ""
    complete_story_text_char_count: int = 0
    chapter_scene_index: list[dict] = Field(default_factory=list)
    character_table: list[dict] = Field(default_factory=list)
    world_canvas_summary: dict = Field(default_factory=dict)
    relationship_state_summary: list[dict] = Field(default_factory=list)
    key_event_timeline: list[dict] = Field(default_factory=list)
    user_locked_constraints: list[dict] = Field(default_factory=list)
    style_and_tone: dict = Field(default_factory=dict)
    known_residual_codes: list[str] = Field(default_factory=list)
    can_be_used_by_plugins: bool
    not_real_project_final_package: bool
    created_at: str
    safe_summary: str


class FinalStoryPackageViewerState(BaseModel):
    viewer_state_id: str
    snapshot_id: str
    selected_section_type: SectionType
    visible_panels: list[ViewerPanel] = Field(default_factory=list)
    show_source_lineage: bool = True
    show_evidence_index: bool = True
    show_safety_audit: bool = True
    created_at: str
    updated_at: str
    safe_summary: str


class FinalStoryPackageViewerStateRequest(BaseModel):
    snapshot_id: str
    selected_section_type: SectionType = "complete_story_text"
    visible_panels: list[ViewerPanel] = Field(default_factory=lambda: ["preview", "sections"])
    show_source_lineage: bool = True
    show_evidence_index: bool = True
    show_safety_audit: bool = True


class FinalStoryPackageEvidenceIndex(BaseModel):
    evidence_index_id: str
    snapshot_id: str
    export_run_id: str
    project_id: str
    readiness_gate_id: str
    validation_report_id: str
    final_story_package_id: str
    manifest_id: str
    source_ref_ids: list[str] = Field(default_factory=list)
    source_version_ids: list[str] = Field(default_factory=list)
    section_hashes: dict[str, str] = Field(default_factory=dict)
    content_hashes: dict[str, str] = Field(default_factory=dict)
    known_residual_codes: list[str] = Field(default_factory=list)
    package_type: PackageType
    readiness_status: ReadinessStatus
    not_real_project_final_package: bool
    can_be_used_by_plugins: bool
    created_at: str
    safe_summary: str


class FinalStoryPackageSafetyAudit(BaseModel):
    safety_audit_id: str
    snapshot_id: str
    export_run_id: str
    project_id: str
    checked_storage_files: list[str] = Field(default_factory=list)
    forbidden_story_fact_files_unchanged: bool
    forbidden_plugin_runtime_files_absent: bool
    sensitive_field_inventory_passed: bool
    pattern_scan_passed: bool
    evidence_contains_full_story_content: bool
    snapshot_contains_controlled_full_story_content: bool
    blocking_findings: list[str] = Field(default_factory=list)
    warning_findings: list[str] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
    passed: bool
    created_at: str
    safe_summary: str


class FinalStoryPackageDiffSummary(BaseModel):
    diff_summary_id: str
    base_snapshot_id: str
    compare_snapshot_id: str
    changed_section_types: list[SectionType] = Field(default_factory=list)
    changed_content_hashes: dict[str, str] = Field(default_factory=dict)
    created_at: str
    safe_summary: str


class FinalStoryPackageExportResponse(BaseModel):
    success: bool
    export_run: FinalStoryPackageExportRun
    snapshot: FinalStoryPackageSnapshot
    preview_sections: list[FinalStoryPackagePreviewSection] = Field(default_factory=list)
    evidence_index: FinalStoryPackageEvidenceIndex
    safety_audit: FinalStoryPackageSafetyAudit
    safe_summary: str


class FinalStoryPackageDownloadPayload(BaseModel):
    snapshot_id: str
    project_id: str
    export_format: FinalStoryPackageDownloadFormat
    filename: str
    media_type: str
    content: str


class FinalStoryPackageExportRunListResponse(BaseModel):
    export_runs: list[FinalStoryPackageExportRun] = Field(default_factory=list)
    total_count: int = 0


class FinalStoryPackagePreviewSectionListResponse(BaseModel):
    snapshot_id: str
    preview_sections: list[FinalStoryPackagePreviewSection] = Field(default_factory=list)
    total_count: int = 0
