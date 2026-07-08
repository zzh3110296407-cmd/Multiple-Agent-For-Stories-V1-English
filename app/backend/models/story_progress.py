from pydantic import BaseModel, Field

from app.backend.models.chapter_archive import ChapterArchiveRecord


STORY_PROGRESS_VERSION_ID = "version_phase3_m4_story_progress_001"
CHAPTER_TRANSITION_VERSION_ID = "version_phase3_m4_chapter_transition_001"
NEXT_CHAPTER_PREPARATION_VERSION_ID = "version_phase3_m4_next_chapter_preparation_001"


class StoryProgressIssue(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    ref_type: str = ""
    ref_id: str = ""


class StoryProgress(BaseModel):
    project_id: str = "local_project"
    story_progress_status: str = "current_chapter_active"
    current_chapter_id: str = ""
    current_chapter_index: int = 1
    chapter_count: int = 0
    archived_chapter_ids: list[str] = Field(default_factory=list)
    archived_chapter_indexes: list[int] = Field(default_factory=list)
    active_transition_id: str = ""
    active_preparation_id: str = ""
    next_chapter_id: str = ""
    next_chapter_index: int = 0
    has_next_chapter: bool = False
    next_recommended_action: str = ""
    warnings: list[StoryProgressIssue] = Field(default_factory=list)
    source_decision_ids: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = STORY_PROGRESS_VERSION_ID


class ChapterTransitionRecord(BaseModel):
    transition_id: str
    project_id: str = "local_project"
    from_chapter_id: str
    from_chapter_index: int
    from_archive_id: str
    from_archive_status: str
    to_chapter_id: str = ""
    to_chapter_index: int = 0
    linked_macro_component_ids: list[str] = Field(default_factory=list)
    transition_status: str = "previewed"
    warnings: list[StoryProgressIssue] = Field(default_factory=list)
    requires_user_review: bool = False
    source_decision_id: str = ""
    created_at: str
    updated_at: str
    version_id: str = CHAPTER_TRANSITION_VERSION_ID


class NextChapterPreparationRecord(BaseModel):
    preparation_id: str
    project_id: str = "local_project"
    transition_id: str
    next_chapter_id: str
    next_chapter_index: int
    previous_chapter_id: str
    previous_chapter_index: int
    previous_archive_id: str
    previous_archive_status: str
    previous_outcome_summary: str = ""
    chapter_framework_id: str = ""
    chapter_framework_build_context_id: str = ""
    chapter_plan_draft_id: str = ""
    chapter_memory_pack_id: str = ""
    first_scene_memory_pack_id: str = ""
    scene_count_proposal: int = 0
    scene_count_confirmed: bool = False
    preparation_status: str = "prepared"
    warnings: list[StoryProgressIssue] = Field(default_factory=list)
    requires_user_review: bool = False
    source_decision_id: str = ""
    created_at: str
    updated_at: str
    version_id: str = NEXT_CHAPTER_PREPARATION_VERSION_ID


class NextChapterPreviewResponse(BaseModel):
    success: bool = True
    can_prepare_next_chapter: bool = False
    can_complete_story_draft: bool = False
    story_progress: StoryProgress
    current_archive: ChapterArchiveRecord | None = None
    transition_preview: ChapterTransitionRecord | None = None
    next_chapter_id: str = ""
    next_chapter_index: int = 0
    warnings: list[StoryProgressIssue] = Field(default_factory=list)
    blocking_issues: list[StoryProgressIssue] = Field(default_factory=list)


class PrepareNextChapterRequest(BaseModel):
    latest_user_intent_summary: str = ""
    story_goal: str = ""
    scene_count_proposal: int | None = None
    acknowledge_provisional_archive: bool = False
    force_rebuild: bool = False


class PrepareNextChapterResponse(BaseModel):
    success: bool = True
    story_progress: StoryProgress
    transition: ChapterTransitionRecord
    preparation: NextChapterPreparationRecord
    warnings: list[StoryProgressIssue] = Field(default_factory=list)
    blocking_issues: list[StoryProgressIssue] = Field(default_factory=list)
    returned_existing: bool = False


class ConfirmNextChapterRequest(BaseModel):
    preparation_id: str = ""
    scene_count: int | None = None
    confirm_chapter_plan: bool = True


class ConfirmNextChapterResponse(BaseModel):
    success: bool = True
    story_progress: StoryProgress
    transition: ChapterTransitionRecord
    preparation: NextChapterPreparationRecord
    source_decision_id: str = ""
    warnings: list[StoryProgressIssue] = Field(default_factory=list)


class ConfirmStoryDraftCompleteRequest(BaseModel):
    acknowledge_completion: bool = True


class ConfirmStoryDraftCompleteResponse(BaseModel):
    success: bool = True
    story_progress: StoryProgress
    source_decision_id: str = ""
    warnings: list[StoryProgressIssue] = Field(default_factory=list)
