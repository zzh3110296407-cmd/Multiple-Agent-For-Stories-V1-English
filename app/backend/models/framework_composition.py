from typing import Literal

from pydantic import BaseModel, Field


FrameworkCompositionUserMode = Literal[
    "original_writing",
    "continuation_rewrite",
    "hybrid_adaptation",
]
FrameworkCompositionReferenceType = Literal[
    "analyzer_material",
    "library_item",
    "pattern",
    "composition_rule",
]
FrameworkCompositionStatus = Literal["draft", "confirmed", "blocked"]
FrameworkCompositionIssueSeverity = Literal["warning", "blocking"]
FrameworkCompositionValidationStatus = Literal["passed", "blocked"]
FRAMEWORK_COMPOSITION_SCHEMA_VERSION = "framework_composition.v1"


class FrameworkCompositionSlot(BaseModel):
    slot_id: str
    order_index: int
    reference_type: FrameworkCompositionReferenceType
    reference_id: str
    source_dependence: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class FrameworkCompositionValidationIssue(BaseModel):
    code: str
    severity: FrameworkCompositionIssueSeverity = "warning"
    slot_id: str | None = None
    reference_type: FrameworkCompositionReferenceType | None = None
    reference_id: str | None = None
    field_path: str | None = None
    message: str
    safe_detail: str | None = None


class FrameworkCompositionValidationReport(BaseModel):
    validation_status: FrameworkCompositionValidationStatus
    blocking_issue_count: int = 0
    warning_count: int = 0
    issues: list[FrameworkCompositionValidationIssue] = Field(default_factory=list)
    safe_summary: str = ""


class FrameworkCompositionDraftCreateRequest(BaseModel):
    title: str
    user_mode: FrameworkCompositionUserMode
    project_id: str = "local_project"
    full_book_framework_slots: list[FrameworkCompositionSlot] = Field(default_factory=list)
    chapter_framework_slots: list[FrameworkCompositionSlot] = Field(default_factory=list)


class FrameworkCompositionDraft(BaseModel):
    schema_version: str = FRAMEWORK_COMPOSITION_SCHEMA_VERSION
    composition_id: str
    project_id: str = "local_project"
    title: str
    user_mode: FrameworkCompositionUserMode
    composition_status: FrameworkCompositionStatus = "draft"
    full_book_framework_slots: list[FrameworkCompositionSlot] = Field(default_factory=list)
    chapter_framework_slots: list[FrameworkCompositionSlot] = Field(default_factory=list)
    validation_report: FrameworkCompositionValidationReport
    created_at: str
    updated_at: str


class FrameworkCompositionDraftListResponse(BaseModel):
    drafts: list[FrameworkCompositionDraft] = Field(default_factory=list)
    total_count: int = 0
