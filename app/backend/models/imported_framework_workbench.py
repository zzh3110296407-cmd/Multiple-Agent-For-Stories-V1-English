from typing import Any, Literal

from pydantic import BaseModel, Field


ImportedFrameworkSessionStatus = Literal[
    "draft",
    "validated",
    "plan_ready",
    "confirmed",
    "rejected",
    "blocked",
]
ImportedFrameworkActivationMode = Literal["reference_only", "merge", "set_active"]
ImportedFrameworkActivationPlanStatus = Literal[
    "draft",
    "confirmed",
    "rejected",
    "blocked",
]
ImportedFrameworkIssueSeverity = Literal["warning", "blocking"]
ImportedFrameworkPatchOperation = Literal[
    "set_activation_mode",
    "update_macro_component",
    "delete_macro_component",
    "restore_macro_component",
    "reorder_macro_components",
    "remap_chapter",
    "update_chapter_count",
]


class ImportedFrameworkSummary(BaseModel):
    framework_package_id: str = ""
    source: str = ""
    macro_component_count: int = 0
    chapter_assignment_count: int = 0
    built_chapter_framework_count: int = 0
    chapter_indexes: list[int] = Field(default_factory=list)
    safe_summary: str = ""


class ImportedFrameworkSourceRef(BaseModel):
    source_ref_id: str
    source_type: str
    source_id: str
    relationship: str = "supports"
    safe_summary: str = ""


class ImportedFrameworkValidationIssue(BaseModel):
    code: str
    severity: ImportedFrameworkIssueSeverity
    message: str
    field_path: str | None = None
    safe_detail: str | None = None


class ImportedFrameworkValidationReport(BaseModel):
    passed: bool = False
    warnings: list[ImportedFrameworkValidationIssue] = Field(default_factory=list)
    blocking_issues: list[ImportedFrameworkValidationIssue] = Field(default_factory=list)
    requires_user_confirmation: bool = True
    safe_summary: str = ""


class ImportedFrameworkEditPatch(BaseModel):
    patch_id: str
    edit_session_id: str
    candidate_id: str
    operation: ImportedFrameworkPatchOperation
    field_path: str = ""
    component_id: str | None = None
    chapter_index: int | None = None
    before_summary: str = ""
    after_summary: str = ""
    user_input: str = ""
    created_at: str
    version_id: str


class ImportedFrameworkEditSession(BaseModel):
    edit_session_id: str
    candidate_id: str
    import_id: str
    artifact_id: str = ""
    normalization_report_id: str = ""
    source_ref_id: str = ""
    story_analysis_report_ref_ids: list[str] = Field(default_factory=list)
    viewer_state_ids: list[str] = Field(default_factory=list)
    project_id: str = "local_project"
    session_status: ImportedFrameworkSessionStatus = "draft"
    activation_mode: ImportedFrameworkActivationMode | None = None
    working_framework_package: dict[str, Any] = Field(default_factory=dict)
    original_candidate_summary: ImportedFrameworkSummary = Field(default_factory=ImportedFrameworkSummary)
    source_refs: list[ImportedFrameworkSourceRef] = Field(default_factory=list)
    patch_ids: list[str] = Field(default_factory=list)
    latest_validation_report: ImportedFrameworkValidationReport | None = None
    validation_report: ImportedFrameworkValidationReport | None = None
    latest_activation_plan_id: str | None = None
    warning_count: int = 0
    blocking_issue_count: int = 0
    safe_notice: str = (
        "Imported frameworks remain inactive until an activation plan is confirmed. "
        "This workbench does not generate prose, rebuild chapter frameworks, write "
        "memory, events, facts, archives, narrative debts, or character state."
    )
    created_at: str
    updated_at: str
    version_id: str


class ImportedFrameworkImpactSummary(BaseModel):
    activation_mode: ImportedFrameworkActivationMode
    current_framework_package_id: str = ""
    imported_candidate_id: str = ""
    will_write_framework_package: bool = False
    will_write_import_decision: bool = True
    will_write_framework_macro_mapping_decision: bool = False
    will_rebuild_built_chapter_frameworks: bool = False
    built_chapter_frameworks_stale_warning_count: int = 0
    untouched_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class ImportedFrameworkActivationPlan(BaseModel):
    plan_id: str
    edit_session_id: str
    candidate_id: str
    activation_mode: ImportedFrameworkActivationMode
    plan_status: ImportedFrameworkActivationPlanStatus = "draft"
    validation_report: ImportedFrameworkValidationReport
    impact_summary: ImportedFrameworkImpactSummary
    accept_warnings_required: bool = False
    warning_count: int = 0
    blocking_issue_count: int = 0
    created_at: str
    updated_at: str
    version_id: str


class ImportedFrameworkDecision(BaseModel):
    decision_id: str
    decision_type: str
    target_type: str = "analyze_stories_framework_import"
    target_id: str
    edit_session_id: str
    plan_id: str | None = None
    activation_mode: ImportedFrameworkActivationMode | None = None
    user_input: str = ""
    safe_summary: str = ""
    created_at: str
    version_id: str


class ImportedFrameworkActionRequest(BaseModel):
    operation: ImportedFrameworkPatchOperation | None = None
    activation_mode: ImportedFrameworkActivationMode | None = None
    component_id: str | None = None
    chapter_index: int | None = None
    patch: dict[str, Any] = Field(default_factory=dict)
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    chapter_count: int | None = None
    user_input: str = ""
    accept_warnings: bool = False


class ImportedFrameworkSessionResult(BaseModel):
    success: bool
    edit_session: ImportedFrameworkEditSession
    validation_report: ImportedFrameworkValidationReport | None = None
    activation_plan: ImportedFrameworkActivationPlan | None = None
    patches: list[ImportedFrameworkEditPatch] = Field(default_factory=list)


class ImportedFrameworkPlanResult(BaseModel):
    success: bool
    activation_plan: ImportedFrameworkActivationPlan
    edit_session: ImportedFrameworkEditSession


class ImportedFrameworkDecisionResult(BaseModel):
    success: bool
    decision: ImportedFrameworkDecision
    edit_session: ImportedFrameworkEditSession
    activation_plan: ImportedFrameworkActivationPlan | None = None


class ImportedFrameworkWorkbenchState(BaseModel):
    candidate_id: str
    candidate_status: str = ""
    can_start_edit_session: bool = False
    latest_edit_session_id: str | None = None
    candidate_summary: ImportedFrameworkSummary
    current_framework_summary: ImportedFrameworkSummary
    source_refs: list[ImportedFrameworkSourceRef] = Field(default_factory=list)
    viewer_state_ids: list[str] = Field(default_factory=list)
    sessions: list[ImportedFrameworkEditSession] = Field(default_factory=list)
    warnings: list[ImportedFrameworkValidationIssue] = Field(default_factory=list)
    blocking_issues: list[ImportedFrameworkValidationIssue] = Field(default_factory=list)
    safe_notice: str = (
        "Opening a candidate here creates an editable inactive copy only. "
        "Report prose stays explanatory and is never treated as generation constraints."
    )


class ImportedFrameworkListResponse(BaseModel):
    edit_sessions: list[ImportedFrameworkEditSession] = Field(default_factory=list)
