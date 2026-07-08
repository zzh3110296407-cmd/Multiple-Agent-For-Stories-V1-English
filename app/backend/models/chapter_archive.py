from typing import Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.decision import Decision
from app.backend.models.scene_generation import SceneProgressResponse


CHAPTER_ARCHIVE_VERSION_ID = "version_phase3_m3_chapter_archive_001"
CHAPTER_ARCHIVE_MODES = {"stable", "provisional", "blocked"}
CHAPTER_ARCHIVE_STATUSES = {"stable", "provisional"}
CHAPTER_ARCHIVE_ISSUE_SEVERITIES = {"warning", "blocking"}


class ChapterOutcomeSummary(BaseModel):
    chapter_goal_result: str = ""
    reader_emotion_result: str = ""
    character_arc_progress: list[str] = Field(default_factory=list)
    relationship_progress: list[str] = Field(default_factory=list)
    conflict_state: str = ""
    open_threads: list[str] = Field(default_factory=list)
    closed_threads: list[str] = Field(default_factory=list)
    next_chapter_seeds: list[str] = Field(default_factory=list)
    world_state_notes: list[str] = Field(default_factory=list)
    unresolved_risks: list[str] = Field(default_factory=list)
    user_visible_summary: str = ""


class ChapterArchiveValidationIssue(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    ref_type: str = ""
    ref_id: str = ""

    @validator("severity")
    def severity_must_be_known(cls, value: str) -> str:
        if value not in CHAPTER_ARCHIVE_ISSUE_SEVERITIES:
            raise ValueError("ChapterArchiveValidationIssue.severity is invalid.")
        return value


class ChapterArchiveValidationReport(BaseModel):
    passed: bool = False
    archive_mode: str = "blocked"
    blocking_issues: list[ChapterArchiveValidationIssue] = Field(default_factory=list)
    warnings: list[ChapterArchiveValidationIssue] = Field(default_factory=list)
    user_confirmation_needed: list[str] = Field(default_factory=list)

    @validator("archive_mode")
    def archive_mode_must_be_known(cls, value: str) -> str:
        if value not in CHAPTER_ARCHIVE_MODES:
            raise ValueError("ChapterArchiveValidationReport.archive_mode is invalid.")
        return value


class ChapterArchiveRecord(BaseModel):
    archive_id: str
    project_id: str = "local_project"
    chapter_id: str
    chapter_index: int
    chapter_framework_id: str
    chapter_framework_build_context_id: str = ""
    archive_status: str
    chapter_completion_status: str
    scene_ids: list[str] = Field(default_factory=list)
    confirmed_scene_ids: list[str] = Field(default_factory=list)
    temporary_scene_ids: list[str] = Field(default_factory=list)
    provisional_scene_ids: list[str] = Field(default_factory=list)
    provisional_memory_ids: list[str] = Field(default_factory=list)
    dependent_scene_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    outcome_summary: ChapterOutcomeSummary = Field(default_factory=ChapterOutcomeSummary)
    key_event_ids: list[str] = Field(default_factory=list)
    key_events: list[str] = Field(default_factory=list)
    character_change_refs: list[str] = Field(default_factory=list)
    relationship_change_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    unresolved_issue_ids: list[str] = Field(default_factory=list)
    unresolved_issue_summary: list[str] = Field(default_factory=list)
    narrative_debt_ids: list[str] = Field(default_factory=list)
    narrative_debt_summary: list[str] = Field(default_factory=list)
    validation_report: ChapterArchiveValidationReport
    source_decision_id: str = ""
    created_at: str
    updated_at: str
    version_id: str = CHAPTER_ARCHIVE_VERSION_ID

    @validator("archive_status")
    def archive_status_must_be_known(cls, value: str) -> str:
        if value not in CHAPTER_ARCHIVE_STATUSES:
            raise ValueError("ChapterArchiveRecord.archive_status is invalid.")
        return value


class ChapterArchivePreview(BaseModel):
    success: bool = True
    chapter_id: str = ""
    chapter_index: int = 0
    recommended_archive_mode: str = "blocked"
    existing_archive: Optional[ChapterArchiveRecord] = None
    archive_candidate: Optional[ChapterArchiveRecord] = None
    validation_report: ChapterArchiveValidationReport = Field(
        default_factory=ChapterArchiveValidationReport
    )
    scene_progress: Optional[SceneProgressResponse] = None
    user_visible_summary: str = ""

    @validator("recommended_archive_mode")
    def recommended_archive_mode_must_be_known(cls, value: str) -> str:
        if value not in CHAPTER_ARCHIVE_MODES:
            raise ValueError("ChapterArchivePreview.recommended_archive_mode is invalid.")
        return value


class ChapterArchiveRequest(BaseModel):
    chapter_id: Optional[str] = None
    chapter_index: Optional[int] = None
    archive_mode: str = "stable"
    user_input: str = ""
    accept_warnings: bool = False

    @validator("archive_mode")
    def request_archive_mode_must_be_known(cls, value: str) -> str:
        if value not in CHAPTER_ARCHIVE_STATUSES:
            raise ValueError("ChapterArchiveRequest.archive_mode is invalid.")
        return value


class ChapterArchiveResponse(BaseModel):
    success: bool = True
    archive: Optional[ChapterArchiveRecord] = None
    preview: Optional[ChapterArchivePreview] = None
    decision: Optional[Decision] = None
    returned_existing: bool = False
