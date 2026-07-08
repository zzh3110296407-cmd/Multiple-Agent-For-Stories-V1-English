from typing import Any, Optional

from pydantic import BaseModel, Field, validator


CHAPTER_MEMORY_PACK_VERSION_ID = "phase2_m3_chapter_memory_pack_v1"
SCENE_MEMORY_PACK_VERSION_ID = "phase2_m3_scene_memory_pack_v1"
MEMORY_PACK_SCHEMA_VERSION = "phase2_m3_memory_pack_v1"
MEMORY_PACK_STATUSES = {"active", "stale", "superseded"}
RETRIEVAL_GAP_TYPES = {
    "missing_character_memory",
    "missing_relationship_memory",
    "missing_location_memory",
    "missing_recent_event",
    "missing_world_rule_memory",
    "missing_framework_memory",
    "provisional_dependency_warning",
    "stale_pack_source",
}
RETRIEVAL_GAP_SEVERITIES = {
    "info",
    "warning",
    "blocking",
    "needs_user_confirmation",
}


class MemoryPackSourceRef(BaseModel):
    memory_id: str
    source_object_type: str = ""
    source_object_id: str = ""
    source_scene_id: str = ""
    memory_type: str = "event"
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    status: str = "active"
    importance: str = "medium"
    version_id: str = ""
    matched_by: list[str] = Field(default_factory=list)
    reason: str = ""
    dedupe_group_id: str = ""
    injection_role: str = ""
    downrank_reason: str = ""
    repeat_risk: str = ""
    duplicate_memory_ids: list[str] = Field(default_factory=list)


class RetrievalGap(BaseModel):
    gap_id: str
    gap_type: str
    severity: str = "warning"
    query_intent: str = ""
    message: str = ""
    related_chapter_id: Optional[str] = None
    related_scene_id: Optional[str] = None
    related_character_ids: list[str] = Field(default_factory=list)
    related_location: Optional[str] = None
    related_keywords: list[str] = Field(default_factory=list)
    suggested_action: str = ""
    created_at: str = ""

    @validator("gap_type")
    def gap_type_must_be_known(cls, value: str) -> str:
        return value if value in RETRIEVAL_GAP_TYPES else "missing_recent_event"

    @validator("severity")
    def severity_must_be_known(cls, value: str) -> str:
        return value if value in RETRIEVAL_GAP_SEVERITIES else "warning"


class ChapterMemoryPack(BaseModel):
    chapter_memory_pack_id: str
    project_id: str = "local_project"
    chapter_id: str
    status: str = "active"
    pack_type: str = "chapter"

    based_on_chapter_version_id: str = ""
    based_on_framework_version_id: str = ""
    based_on_memory_index_version_id: str = ""

    current_chapter_goal: str = ""
    current_main_conflict: str = ""

    included_memory_ids: list[str] = Field(default_factory=list)

    world_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    character_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    relationship_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    event_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    framework_context: list[MemoryPackSourceRef] = Field(default_factory=list)

    retrieval_gaps: list[RetrievalGap] = Field(default_factory=list)
    retrieval_summary: str = ""
    source_query_signature: dict[str, Any] = Field(default_factory=dict)

    created_at: str = ""
    updated_at: str = ""
    version_id: str = CHAPTER_MEMORY_PACK_VERSION_ID

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        return value if value in MEMORY_PACK_STATUSES else "active"


class SceneMemoryPack(BaseModel):
    scene_memory_pack_id: str
    project_id: str = "local_project"
    chapter_id: str
    scene_id: Optional[str] = None
    scene_index: int
    status: str = "active"
    pack_type: str = "scene"

    chapter_memory_pack_id: str

    scene_goal: str = ""
    scene_location: str = ""
    active_character_ids: list[str] = Field(default_factory=list)

    must_use_memory_ids: list[str] = Field(default_factory=list)
    should_use_memory_ids: list[str] = Field(default_factory=list)
    optional_memory_ids: list[str] = Field(default_factory=list)
    forbidden_or_conflict_memory_ids: list[str] = Field(default_factory=list)
    continuity_anchor_memory_ids: list[str] = Field(default_factory=list)
    do_not_repeat_memory_ids: list[str] = Field(default_factory=list)

    must_use_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    should_use_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    optional_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    forbidden_or_conflict_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    continuity_anchor_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    do_not_repeat_context: list[MemoryPackSourceRef] = Field(default_factory=list)
    memory_context_dedupe_report: dict[str, Any] = Field(default_factory=dict)

    provisional_memory_ids: list[str] = Field(default_factory=list)
    provisional_dependency_scene_ids: list[str] = Field(default_factory=list)

    retrieval_gaps: list[RetrievalGap] = Field(default_factory=list)
    source_query_signature: dict[str, Any] = Field(default_factory=dict)

    created_at: str = ""
    updated_at: str = ""
    version_id: str = SCENE_MEMORY_PACK_VERSION_ID

    @validator("status")
    def scene_status_must_be_known(cls, value: str) -> str:
        return value if value in MEMORY_PACK_STATUSES else "active"


class BuildChapterMemoryPackRequest(BaseModel):
    chapter_id: str
    force_refresh: bool = False


class BuildSceneMemoryPackRequest(BaseModel):
    chapter_id: str
    scene_index: int
    scene_id: Optional[str] = None
    scene_goal: str = ""
    scene_location: str = ""
    active_character_ids: list[str] = Field(default_factory=list)
    include_provisional: bool = False
    force_refresh: bool = False


class MemoryPackRefreshRequest(BaseModel):
    chapter_id: str
    scene_index: Optional[int] = None


class MemoryPackBuildResponse(BaseModel):
    success: bool = True
    chapter_memory_pack: Optional[ChapterMemoryPack] = None
    scene_memory_pack: Optional[SceneMemoryPack] = None


class ChapterMemoryPackResponse(BaseModel):
    chapter_memory_pack: ChapterMemoryPack


class SceneMemoryPackResponse(BaseModel):
    scene_memory_pack: SceneMemoryPack


class MemoryPackPreviewResponse(BaseModel):
    scene_memory_pack: Optional[SceneMemoryPack] = None
    memory_pack_context: dict[str, Any] = Field(default_factory=dict)
