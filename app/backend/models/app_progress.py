from pydantic import BaseModel, Field

from app.backend.models.story_progress import StoryProgress
from app.backend.models.tracing import TracingStatus


class AppProgressProject(BaseModel):
    initialized: bool = False
    project_id: str = "local_project"
    title: str = ""
    current_step: str = ""
    status: str = ""


class AppProgressActiveModel(BaseModel):
    configured: bool = False
    provider_type: str = ""
    model_name: str = ""
    issues: list[str] = Field(default_factory=list)


class AppProgressWorldCanvas(BaseModel):
    exists: bool = False
    status: str = ""


class AppProgressMainCast(BaseModel):
    confirmed_character_count: int = 0
    finished: bool = False
    main_cast_decision_exists: bool = False


class AppProgressFramework(BaseModel):
    package_exists: bool = False
    mapping_exists: bool = False
    chapter_count: int = 0
    assignment_count: int = 0
    mapping_status: str = ""
    mapping_confirmed: bool = False
    requires_reconfirm: bool = False
    last_decision_id: str = ""
    current_chapter_framework_built: bool = False
    current_chapter_framework_id: str = ""
    current_chapter_framework_index: int = 0


class AppProgressChapterPlan(BaseModel):
    exists: bool = False
    status: str = ""
    current_chapter_index: int = 1
    scene_count: int = 0
    chapter_plan_decision_exists: bool = False


class AppProgressScene(BaseModel):
    current_scene_exists: bool = False
    status: str = ""
    scene_id: str = ""
    scene_index: int = 0
    prose_status: str = ""
    has_generated_prose: bool = False
    scene_count: int = 0
    next_scene_index: int = 1
    can_generate_next: bool = False
    completion_status: str = "not_started"
    dependency_warning_count: int = 0
    has_temporary_scene: bool = False
    has_revision_candidate: bool = False
    active_revision_id: str = ""
    quality_target_type: str = ""
    quality_target_id: str = ""
    quality_passed: bool = False
    blocking_issue_count: int = 0
    requires_user_confirmation: bool = False
    gate_readiness_current: bool = False
    gate_safe_to_confirm: bool = False
    gate_safe_to_release: bool = False
    gate_requires_user_action: bool = False
    gate_reason_codes: list[str] = Field(default_factory=list)


class AppProgressChapterArchive(BaseModel):
    exists: bool = False
    archive_id: str = ""
    archive_status: str = ""
    chapter_id: str = ""
    chapter_index: int = 0
    ready_for_archive: bool = False
    recommended_archive_mode: str = ""
    blocking_issue_count: int = 0
    warning_count: int = 0


class AppProgressNextChapterPreparation(BaseModel):
    exists: bool = False
    preparation_id: str = ""
    transition_id: str = ""
    next_chapter_id: str = ""
    next_chapter_index: int = 0
    previous_archive_id: str = ""
    preparation_status: str = ""
    chapter_framework_id: str = ""
    chapter_plan_draft_id: str = ""
    chapter_memory_pack_id: str = ""
    first_scene_memory_pack_id: str = ""
    requires_user_review: bool = False
    warning_count: int = 0


class AppProgressStep(BaseModel):
    key: str
    label: str
    state: str = "locked"
    locked_reasons: list[str] = Field(default_factory=list)


class AppProgressResponse(BaseModel):
    project: AppProgressProject = Field(default_factory=AppProgressProject)
    active_model: AppProgressActiveModel = Field(default_factory=AppProgressActiveModel)
    world_canvas: AppProgressWorldCanvas = Field(default_factory=AppProgressWorldCanvas)
    main_cast: AppProgressMainCast = Field(default_factory=AppProgressMainCast)
    framework: AppProgressFramework = Field(default_factory=AppProgressFramework)
    chapter_plan: AppProgressChapterPlan = Field(default_factory=AppProgressChapterPlan)
    scene: AppProgressScene = Field(default_factory=AppProgressScene)
    chapter_archive: AppProgressChapterArchive = Field(default_factory=AppProgressChapterArchive)
    story_progress: StoryProgress = Field(default_factory=StoryProgress)
    next_chapter_preparation: AppProgressNextChapterPreparation = Field(
        default_factory=AppProgressNextChapterPreparation
    )
    tracing: TracingStatus = Field(default_factory=TracingStatus)
    steps: list[AppProgressStep] = Field(default_factory=list)
    next_recommended_action: str = ""
    locked_reasons: dict[str, list[str]] = Field(default_factory=dict)
