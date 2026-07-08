from typing import Any, Optional

from pydantic import BaseModel, Field, validator


SCENE_CANDIDATE_CACHE_VERSION_ID = "phase4_m4_scene_candidate_cache_v1"
CACHED_SCENE_CANDIDATE_VERSION_ID = "phase4_m4_cached_scene_candidate_v1"
CANDIDATE_CACHE_INVALIDATION_VERSION_ID = "phase4_m4_candidate_cache_invalidation_v1"

SOURCE_CANDIDATE_TYPES = {"thinking_candidate", "pre_modify_candidate"}
CACHE_STATUSES = {"active", "stale", "hidden", "archived"}
CACHE_INVALIDATION_TYPES = {
    "snapshot_invalidated",
    "changed_ref_invalidated",
    "source_candidate_status_changed",
    "manual_hide",
    "manual_archive",
    "backfill_refresh",
}


class SceneCandidateCache(BaseModel):
    cache_id: str
    project_id: str = "local_project"
    chapter_id: str = ""
    scene_id: str = ""
    target_scene_index: Optional[int] = None
    cached_candidate_ids: list[str] = Field(default_factory=list)
    active_candidate_count: int = 0
    stale_candidate_count: int = 0
    hidden_candidate_count: int = 0
    archived_candidate_count: int = 0
    candidate_counts_by_source_type: dict[str, int] = Field(default_factory=dict)
    candidate_counts_by_status: dict[str, int] = Field(default_factory=dict)
    latest_candidate_id: str = ""
    latest_candidate_at: str = ""
    created_at: str
    updated_at: str
    version_id: str = SCENE_CANDIDATE_CACHE_VERSION_ID


class CachedSceneCandidate(BaseModel):
    cached_candidate_id: str
    project_id: str = "local_project"
    cache_id: str
    source_candidate_type: str
    source_candidate_id: str
    source_task_id: str = ""
    source_preview_id: str = ""
    target_scene_id: str
    target_chapter_id: str = ""
    target_scene_index: Optional[int] = None
    based_on_snapshot_ids: list[str] = Field(default_factory=list)
    source_snapshot_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_candidate_status: str
    cache_status: str
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    preview_label: str = ""
    user_visible_reason: str = ""
    risk_warnings: list[str] = Field(default_factory=list)
    stale_reason_refs: list[dict[str, Any]] = Field(default_factory=list)
    invalidation_record_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str = CACHED_SCENE_CANDIDATE_VERSION_ID

    @validator("source_candidate_type")
    def source_type_must_be_supported(cls, value: str) -> str:
        source_type = str(value or "").strip()
        if source_type not in SOURCE_CANDIDATE_TYPES:
            raise ValueError("CachedSceneCandidate.source_candidate_type is not supported.")
        return source_type

    @validator("cache_status")
    def cache_status_must_be_supported(cls, value: str) -> str:
        status = str(value or "active").strip()
        if status not in CACHE_STATUSES:
            raise ValueError("CachedSceneCandidate.cache_status is not supported.")
        return status


class CandidateCacheInvalidationRecord(BaseModel):
    invalidation_record_id: str
    project_id: str = "local_project"
    cache_id: str = ""
    cached_candidate_id: str = ""
    source_candidate_type: str = ""
    source_candidate_id: str = ""
    invalidation_type: str
    trigger_snapshot_id: str = ""
    trigger_invalidation_id: str = ""
    changed_ref_type: str = ""
    changed_ref_id: str = ""
    affected_snapshot_ids: list[str] = Field(default_factory=list)
    previous_status: str
    new_status: str
    user_visible_reason: str
    created_at: str
    version_id: str = CANDIDATE_CACHE_INVALIDATION_VERSION_ID

    @validator("invalidation_type")
    def invalidation_type_must_be_supported(cls, value: str) -> str:
        invalidation_type = str(value or "").strip()
        if invalidation_type not in CACHE_INVALIDATION_TYPES:
            raise ValueError("CandidateCacheInvalidationRecord.invalidation_type is not supported.")
        return invalidation_type


class SceneCandidateCacheRegisterRequest(BaseModel):
    candidate_id: str


class SceneCandidateCacheBackfillRequest(BaseModel):
    target_scene_id: str = ""
    chapter_id: str = ""
    limit: int = 200


class SceneCandidateCacheInvalidateBySnapshotRequest(BaseModel):
    snapshot_ids: list[str] = Field(default_factory=list)
    trigger_invalidation_id: str = ""
    reason: str = ""


class SceneCandidateCacheInvalidateByRefRequest(BaseModel):
    changed_ref_type: str
    changed_ref_id: str
    trigger_invalidation_id: str = ""
    reason: str = ""


class SceneCandidateCacheResponse(BaseModel):
    success: bool = True
    cache: SceneCandidateCache | None = None
    candidates: list[CachedSceneCandidate] = Field(default_factory=list)
    count: int = 0
    safety: dict[str, Any] = Field(default_factory=dict)


class SceneCandidateCacheSummaryResponse(BaseModel):
    success: bool = True
    project_id: str = "local_project"
    scene_id: str = ""
    chapter_id: str = ""
    cache_count: int = 0
    candidate_count: int = 0
    active_candidate_count: int = 0
    stale_candidate_count: int = 0
    hidden_candidate_count: int = 0
    archived_candidate_count: int = 0
    candidate_counts_by_source_type: dict[str, int] = Field(default_factory=dict)
    candidate_counts_by_status: dict[str, int] = Field(default_factory=dict)
    recent_cache_ids: list[str] = Field(default_factory=list)
    recent_cached_candidate_ids: list[str] = Field(default_factory=list)
    recent_source_candidate_ids: list[str] = Field(default_factory=list)
    recent_invalidation_ids: list[str] = Field(default_factory=list)
    caches: list[SceneCandidateCache] = Field(default_factory=list)
    candidates: list[CachedSceneCandidate] = Field(default_factory=list)
    recent_candidates: list[dict[str, Any]] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)


class CachedSceneCandidateResponse(BaseModel):
    success: bool = True
    candidate: CachedSceneCandidate
    safety: dict[str, Any] = Field(default_factory=dict)


class CandidateCacheInvalidationResponse(BaseModel):
    success: bool = True
    invalidation_records: list[CandidateCacheInvalidationRecord] = Field(default_factory=list)
    stale_cached_candidate_ids: list[str] = Field(default_factory=list)
    affected_snapshot_ids: list[str] = Field(default_factory=list)
    count: int = 0
    safety: dict[str, Any] = Field(default_factory=dict)
