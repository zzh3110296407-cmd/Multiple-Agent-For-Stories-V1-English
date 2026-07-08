from typing import Optional

from pydantic import BaseModel, Field


class FrameworkMetadata(BaseModel):
    scope: str = "chapter"
    persistence: str = "chapter_local"
    owner: str = "chapter_framework"
    write_policy: str = "no_memory_write"


class MacroComponent(BaseModel):
    component_id: str
    label: str
    order: int
    instruction: str
    source: str = "system_default"
    scope: str = "macro"


class MacroFramework(BaseModel):
    components: list[MacroComponent] = Field(default_factory=list)


class ModuleComponent(BaseModel):
    component_id: str
    label: str
    source: str = "system_default"
    scope: str = "chapter"
    persistence: str = "chapter_local"
    owner: str = "chapter_framework"
    write_policy: str = "no_memory_write"
    normalized_hint: str = ""
    order: int = 0


class ChapterModuleVocabulary(BaseModel):
    module_id: str
    label: str
    scope: str = "chapter"
    persistence: str = "chapter_local"
    owner: str = "chapter_framework"
    write_policy: str = "no_memory_write"
    order: int = 0
    allowed_components: list[ModuleComponent] = Field(default_factory=list)


class ComponentVocabulary(BaseModel):
    macro_components: list[MacroComponent] = Field(default_factory=list)
    chapter_modules: list[ChapterModuleVocabulary] = Field(default_factory=list)
    module_components: list[ModuleComponent] = Field(default_factory=list)


class ChapterMacroAssignment(BaseModel):
    chapter_index: int
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    assignment_type: str = "system_default"
    status: str = "planned"
    reason: str = ""


class BuiltFromStateVersion(BaseModel):
    world_canvas_version: int = 1
    memory_version: int = 0
    character_state_version: int = 1
    relationship_version: int = 1


class ChapterModule(BaseModel):
    module_id: str
    label: str
    scope: str = "chapter"
    persistence: str = "chapter_local"
    owner: str = "chapter_framework"
    write_policy: str = "no_memory_write"
    order: int = 0
    components: list[ModuleComponent] = Field(default_factory=list)


class ChapterFramework(BaseModel):
    chapter_framework_id: str
    chapter_index: int
    chapter_id: Optional[str] = None
    build_status: str = "built"
    built_from_state_version: BuiltFromStateVersion = Field(
        default_factory=BuiltFromStateVersion
    )
    built_after_event_ids: list[str] = Field(default_factory=list)
    user_intent_snapshot: str = ""
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    modules: list[ChapterModule] = Field(default_factory=list)
    created_at: str
    updated_at: str


class FrameworkPackage(BaseModel):
    framework_package_id: str
    project_id: str = "local_project"
    source: str = "system_default"
    language: str = "zh"
    constraint_strength: str = "strong"
    maturity: str = "System"
    macro_framework: MacroFramework = Field(default_factory=MacroFramework)
    component_vocabulary: ComponentVocabulary = Field(
        default_factory=ComponentVocabulary
    )
    chapter_macro_assignments: list[ChapterMacroAssignment] = Field(
        default_factory=list
    )
    built_chapter_frameworks: list[ChapterFramework] = Field(default_factory=list)
    version_id: str = "version_framework_pkg_001"


class FrameworkPackageSeedResponse(BaseModel):
    ready: bool
    created_files: list[str] = Field(default_factory=list)
    existing_files: list[str] = Field(default_factory=list)
    updated_files: list[str] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    package: FrameworkPackage


class FrameworkMappingIssue(BaseModel):
    code: str
    message: str
    chapter_index: Optional[int] = None
    component_id: str = ""


class FrameworkMappingValidationReport(BaseModel):
    passed: bool = False
    warnings: list[FrameworkMappingIssue] = Field(default_factory=list)
    blocking_issues: list[FrameworkMappingIssue] = Field(default_factory=list)
    requires_user_confirmation: bool = False


class MacroAssignmentRequest(BaseModel):
    chapter_count: int


class MacroAssignmentResponse(BaseModel):
    chapter_count: int
    assignments: list[ChapterMacroAssignment] = Field(default_factory=list)
    package: FrameworkPackage
    validation_report: FrameworkMappingValidationReport = Field(
        default_factory=FrameworkMappingValidationReport
    )


class ChapterFrameworkBuildRequest(BaseModel):
    chapter_index: int
    chapter_id: Optional[str] = None
    user_intent_snapshot: str = ""


class ChapterFrameworkResponse(BaseModel):
    chapter_framework: ChapterFramework
    package: FrameworkPackage


class ChapterFrameworkBuildIssue(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    chapter_index: Optional[int] = None
    ref_id: str = ""


class ChapterFrameworkBuildValidationReport(BaseModel):
    passed: bool = False
    warnings: list[ChapterFrameworkBuildIssue] = Field(default_factory=list)
    blocking_issues: list[ChapterFrameworkBuildIssue] = Field(default_factory=list)


class ChapterFrameworkBuildContext(BaseModel):
    build_context_id: str
    project_id: str = "local_project"
    chapter_id: str
    chapter_index: int
    framework_package_id: str
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    source_decision_ids: list[str] = Field(default_factory=list)
    world_canvas_ref: str = ""
    world_hard_rules: list[str] = Field(default_factory=list)
    character_state_refs: list[str] = Field(default_factory=list)
    relationship_refs: list[str] = Field(default_factory=list)
    chapter_memory_pack_id: str = ""
    memory_pack_status: str = "unknown"
    memory_pack_issue_codes: list[str] = Field(default_factory=list)
    project_story_premise_status: str = "not_applicable"
    project_story_premise_ref: str = ""
    project_story_premise_terms: list[str] = Field(default_factory=list)
    previous_chapter_archive_id: str = ""
    previous_chapter_archive_status: str = ""
    previous_chapter_outcome_summary: str = ""
    latest_user_intent_summary: str = ""
    component_vocabulary_version: str = ""
    existing_built_chapter_framework_ids: list[str] = Field(default_factory=list)
    build_mode: str = "model"
    created_at: str
    version_id: str = "version_phase3_m2_build_context_001"


class ChapterFrameworkBuildReason(BaseModel):
    build_reason_id: str
    chapter_framework_id: str
    build_context_id: str
    chapter_id: str
    chapter_index: int
    selected_module_id: str
    selected_component_ids: list[str] = Field(default_factory=list)
    reason_summary: str
    input_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    created_at: str
    version_id: str = "version_phase3_m2_build_reason_001"


class ChapterFrameworkBuildResult(BaseModel):
    success: bool
    chapter_framework: Optional[ChapterFramework] = None
    build_context: Optional[ChapterFrameworkBuildContext] = None
    build_reasons: list[ChapterFrameworkBuildReason] = Field(default_factory=list)
    build_mode: str = ""
    warnings: list[ChapterFrameworkBuildIssue] = Field(default_factory=list)
    validation_report: ChapterFrameworkBuildValidationReport = Field(
        default_factory=ChapterFrameworkBuildValidationReport
    )
    user_visible_summary: str = ""
    returned_existing: bool = False


class ChapterFrameworkBuildCurrentRequest(BaseModel):
    chapter_id: Optional[str] = None
    chapter_index: Optional[int] = None
    latest_user_intent_summary: str = ""
    previous_chapter_archive_id: str = ""
    previous_chapter_archive_status: str = ""
    previous_chapter_outcome_summary: str = ""
    force_rebuild: bool = False


class FrameworkPackageValidationResponse(BaseModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)


class BuiltChapterFrameworkSummary(BaseModel):
    chapter_index: int
    chapter_framework_id: str
    chapter_id: Optional[str] = None
    build_status: str = ""
    linked_macro_component_ids: list[str] = Field(default_factory=list)


class FrameworkWorkbenchState(BaseModel):
    project_id: str = "local_project"
    framework_package_id: str = ""
    macro_components: list[MacroComponent] = Field(default_factory=list)
    chapter_count: int = 0
    chapter_macro_assignments: list[ChapterMacroAssignment] = Field(default_factory=list)
    built_chapter_frameworks_summary: list[BuiltChapterFrameworkSummary] = Field(default_factory=list)
    validation_report: FrameworkMappingValidationReport = Field(
        default_factory=FrameworkMappingValidationReport
    )
    confirmed: bool = False
    requires_reconfirm: bool = False
    last_decision_id: str = ""


class FrameworkWorkbenchChapterCountRequest(BaseModel):
    chapter_count: int
    recompute_mapping: bool = True
    accept_warnings: bool = False


class FrameworkWorkbenchRecommendRequest(BaseModel):
    chapter_count: int
    strategy: str = "balanced"
    accept_warnings: bool = False


class FrameworkWorkbenchAssignmentUpdateRequest(BaseModel):
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    accept_warnings: bool = False
    user_input: str = ""


class FrameworkWorkbenchConfirmRequest(BaseModel):
    user_input: str = ""
    accept_warnings: bool = False
