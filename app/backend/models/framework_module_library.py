from typing import Any, Literal

from pydantic import BaseModel, Field


FrameworkLibraryItemType = Literal[
    "macro_component",
    "chapter_module",
    "module_component",
    "narrative_pattern",
    "apparent_contradiction_template",
    "payoff_pattern",
    "narrative_debt_pattern",
    "open_thread_pattern",
    "closed_thread_pattern",
    "information_release_pattern",
    "reader_emotion_pattern",
    "character_arc_pattern",
    "relationship_pattern",
]
FrameworkLibrarySourceType = Literal[
    "m4_confirmed_import",
    "m4_reference_only",
    "m6_reviewed_candidate",
    "analyze_stories_vocabulary",
    "user_created",
    "system_default",
]
FrameworkLibraryVisibility = Literal[
    "private",
    "project_local",
    "system_recommended_candidate",
    "archived",
    "blocked",
]
FrameworkLibraryMaturity = Literal[
    "raw_import",
    "validated",
    "validated_with_warnings",
    "user_reviewed",
    "user_confirmed",
    "system_recommended_candidate",
    "blocked",
    "deprecated",
]
FrameworkConstraintStrength = Literal["reference", "suggestion", "user_confirmed", "blocked"]
CopyrightRiskLevel = Literal["low", "medium", "high", "blocked"]
CompositionRuleStatus = Literal["candidate", "reviewed", "rejected", "archived"]
FrameworkLibraryBuildStatus = Literal["completed", "completed_with_warnings", "blocked", "no_records"]


class FrameworkLibraryIssue(BaseModel):
    code: str
    severity: Literal["info", "warning", "blocking"] = "warning"
    field_path: str | None = None
    source_id: str | None = None
    safe_detail: str = ""


class FrameworkLibrarySourceRef(BaseModel):
    source_ref_id: str
    source_type: FrameworkLibrarySourceType | str
    source_id: str
    relationship: str = "supports"
    field_path: str | None = None
    source_import_id: str | None = None
    source_artifact_id: str | None = None
    source_candidate_id: str | None = None
    source_derivation_report_id: str | None = None
    source_imported_framework_decision_id: str | None = None
    source_viewer_state_id: str | None = None
    source_report_section_id: str | None = None
    source_input_fingerprint_ids: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class FrameworkMaturityRecord(BaseModel):
    maturity_record_id: str
    project_id: str = "local_project"
    maturity_level: FrameworkLibraryMaturity
    source_type: FrameworkLibrarySourceType
    source_id: str
    requires_user_confirmation: bool = True
    warning_count: int = 0
    blocking_issue_count: int = 0
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class CopyrightSourceRecord(BaseModel):
    copyright_source_record_id: str
    project_id: str = "local_project"
    source_type: FrameworkLibrarySourceType
    source_id: str
    risk_level: CopyrightRiskLevel = "medium"
    visibility_limit: FrameworkLibraryVisibility = "private"
    has_source_fingerprint: bool = False
    source_input_fingerprint_ids: list[str] = Field(default_factory=list)
    examples_stripped: bool = False
    authority_downgraded: bool = False
    warnings: list[FrameworkLibraryIssue] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class FrameworkModuleLibraryItem(BaseModel):
    library_item_id: str
    project_id: str = "local_project"
    item_type: FrameworkLibraryItemType
    source_type: FrameworkLibrarySourceType
    label: str
    description: str = ""
    safe_summary: str = ""
    source_refs: list[FrameworkLibrarySourceRef] = Field(default_factory=list)
    visibility: FrameworkLibraryVisibility = "private"
    constraint_strength: FrameworkConstraintStrength = "reference"
    maturity_record_id: str
    copyright_source_record_id: str
    requires_user_confirmation: bool = True
    warnings: list[FrameworkLibraryIssue] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str


class FrameworkPatternRecord(BaseModel):
    pattern_id: str
    project_id: str = "local_project"
    pattern_type: str
    source_type: FrameworkLibrarySourceType
    label: str
    safe_summary: str = ""
    source_refs: list[FrameworkLibrarySourceRef] = Field(default_factory=list)
    visibility: FrameworkLibraryVisibility = "private"
    maturity_record_id: str
    copyright_source_record_id: str
    requires_user_confirmation: bool = True
    warnings: list[FrameworkLibraryIssue] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str


class ModuleCompositionRule(BaseModel):
    rule_id: str
    project_id: str = "local_project"
    relation_type: str
    source_type: FrameworkLibrarySourceType
    source_pattern_ids: list[str] = Field(default_factory=list)
    source_library_item_ids: list[str] = Field(default_factory=list)
    target_pattern_ids: list[str] = Field(default_factory=list)
    target_library_item_ids: list[str] = Field(default_factory=list)
    rule_status: CompositionRuleStatus = "candidate"
    requires_user_confirmation: bool = True
    source_refs: list[FrameworkLibrarySourceRef] = Field(default_factory=list)
    safe_summary: str = ""
    warnings: list[FrameworkLibraryIssue] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str


class UserPrivateFramework(BaseModel):
    private_framework_id: str
    project_id: str = "local_project"
    title: str
    item_ids: list[str] = Field(default_factory=list)
    pattern_ids: list[str] = Field(default_factory=list)
    composition_rule_ids: list[str] = Field(default_factory=list)
    visibility: Literal["private", "project_local"] = "private"
    requires_user_confirmation: bool = True
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class SystemRecommendedFramework(BaseModel):
    system_recommendation_id: str
    project_id: str = "local_project"
    status: Literal["candidate", "blocked", "archived"] = "candidate"
    item_ids: list[str] = Field(default_factory=list)
    pattern_ids: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = True
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class FrameworkLibraryCollection(BaseModel):
    collection_id: str
    project_id: str = "local_project"
    title: str
    item_ids: list[str] = Field(default_factory=list)
    pattern_ids: list[str] = Field(default_factory=list)
    composition_rule_ids: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class FrameworkLibraryBuildReport(BaseModel):
    build_report_id: str
    project_id: str = "local_project"
    build_status: FrameworkLibraryBuildStatus
    source_type: FrameworkLibrarySourceType | str
    source_id: str
    created_library_item_ids: list[str] = Field(default_factory=list)
    created_pattern_ids: list[str] = Field(default_factory=list)
    created_composition_rule_ids: list[str] = Field(default_factory=list)
    created_maturity_record_ids: list[str] = Field(default_factory=list)
    created_copyright_source_record_ids: list[str] = Field(default_factory=list)
    created_private_framework_ids: list[str] = Field(default_factory=list)
    warnings: list[FrameworkLibraryIssue] = Field(default_factory=list)
    blocking_issues: list[FrameworkLibraryIssue] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class FrameworkLibraryBuildResult(BaseModel):
    success: bool
    build_report: FrameworkLibraryBuildReport
    items: list[FrameworkModuleLibraryItem] = Field(default_factory=list)
    patterns: list[FrameworkPatternRecord] = Field(default_factory=list)
    composition_rules: list[ModuleCompositionRule] = Field(default_factory=list)
    maturity_records: list[FrameworkMaturityRecord] = Field(default_factory=list)
    copyright_sources: list[CopyrightSourceRecord] = Field(default_factory=list)
    private_frameworks: list[UserPrivateFramework] = Field(default_factory=list)


class FrameworkLibraryListResponse(BaseModel):
    items: list[FrameworkModuleLibraryItem] = Field(default_factory=list)
    total_count: int = 0


class FrameworkPatternListResponse(BaseModel):
    patterns: list[FrameworkPatternRecord] = Field(default_factory=list)
    total_count: int = 0


class ModuleCompositionRuleListResponse(BaseModel):
    composition_rules: list[ModuleCompositionRule] = Field(default_factory=list)
    total_count: int = 0


class FrameworkMaturityRecordListResponse(BaseModel):
    maturity_records: list[FrameworkMaturityRecord] = Field(default_factory=list)
    total_count: int = 0


class CopyrightSourceRecordListResponse(BaseModel):
    copyright_sources: list[CopyrightSourceRecord] = Field(default_factory=list)
    total_count: int = 0


class UserPrivateFrameworkListResponse(BaseModel):
    private_frameworks: list[UserPrivateFramework] = Field(default_factory=list)
    total_count: int = 0


class SystemRecommendedFrameworkListResponse(BaseModel):
    system_recommendations: list[SystemRecommendedFramework] = Field(default_factory=list)
    total_count: int = 0


class FrameworkLibraryBuildFromConfirmedImportRequest(BaseModel):
    imported_framework_decision_id: str
    safe_user_note: str = ""


class FrameworkLibraryBuildFromAdapterDerivationRequest(BaseModel):
    derivation_report_id: str
    safe_user_note: str = ""


class FrameworkLibraryBuildFromSelectedCandidatesRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)
    safe_user_note: str = ""


class FrameworkLibraryBuildFromVocabularyArtifactRequest(BaseModel):
    artifact: dict[str, Any] = Field(default_factory=dict)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    safe_user_note: str = ""


class FrameworkLibraryItemPatchRequest(BaseModel):
    visibility: FrameworkLibraryVisibility | None = None
    safe_user_note: str = ""


class FrameworkLibraryActionRequest(BaseModel):
    safe_user_note: str = ""


class UserPrivateFrameworkCreateRequest(BaseModel):
    title: str
    item_ids: list[str] = Field(default_factory=list)
    pattern_ids: list[str] = Field(default_factory=list)
    composition_rule_ids: list[str] = Field(default_factory=list)
    safe_user_note: str = ""
