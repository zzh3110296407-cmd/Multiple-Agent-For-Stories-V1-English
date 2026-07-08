from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.scene_candidate_cache import (
    CachedSceneCandidateResponse,
    CandidateCacheInvalidationResponse,
    SceneCandidateCacheBackfillRequest,
    SceneCandidateCacheInvalidateByRefRequest,
    SceneCandidateCacheInvalidateBySnapshotRequest,
    SceneCandidateCacheRegisterRequest,
    SceneCandidateCacheSummaryResponse,
)
from app.backend.services.scene_candidate_cache_service import SceneCandidateCacheService
from app.backend.storage.json_store import StorageError


router = APIRouter()
scene_candidate_cache_service = SceneCandidateCacheService()


def _error_detail(message: str) -> dict[str, str]:
    code, _, detail = message.partition(":")
    return {
        "error_code": code,
        "message": detail.strip() or "Scene candidate cache operation failed.",
    }


def _raise_cache_error(exc: StorageError) -> None:
    detail = _error_detail(str(exc))
    code = detail["error_code"]
    status_code = 500
    if "NOT_FOUND" in code or code.endswith("_MISSING"):
        status_code = 404
    if (
        code.endswith("_REQUIRED")
        or "SCHEMA_INVALID" in code
        or "SNAPSHOT_REF" in code
        or "SOURCE_ID_REQUIRED" in code
        or "TARGET_SCENE_REQUIRED" in code
    ):
        status_code = 400
    if "UNSAFE_PAYLOAD_BLOCKED" in code:
        status_code = 409
    if status_code == 500:
        detail = {
            "error_code": "SCENE_CANDIDATE_CACHE_INTERNAL_ERROR",
            "message": "Scene candidate cache operation failed.",
        }
    raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/register-thinking-candidate", response_model=CachedSceneCandidateResponse)
def register_thinking_candidate(
    request: SceneCandidateCacheRegisterRequest,
) -> CachedSceneCandidateResponse:
    try:
        candidate = scene_candidate_cache_service.register_thinking_candidate(
            request.candidate_id
        )
        return CachedSceneCandidateResponse(candidate=candidate)
    except StorageError as exc:
        _raise_cache_error(exc)


@router.post("/register-pre-modify-candidate", response_model=CachedSceneCandidateResponse)
def register_pre_modify_candidate(
    request: SceneCandidateCacheRegisterRequest,
) -> CachedSceneCandidateResponse:
    try:
        candidate = scene_candidate_cache_service.register_pre_modify_candidate(
            request.candidate_id
        )
        return CachedSceneCandidateResponse(candidate=candidate)
    except StorageError as exc:
        _raise_cache_error(exc)


@router.post("/backfill", response_model=SceneCandidateCacheSummaryResponse)
def backfill_scene_candidate_cache(
    request: SceneCandidateCacheBackfillRequest,
) -> SceneCandidateCacheSummaryResponse:
    try:
        return scene_candidate_cache_service.backfill_from_sources(
            target_scene_id=request.target_scene_id,
            chapter_id=request.chapter_id,
            limit=request.limit,
        )
    except StorageError as exc:
        _raise_cache_error(exc)


@router.get("/scene/{scene_id}", response_model=SceneCandidateCacheSummaryResponse)
def get_scene_candidate_cache(
    scene_id: str,
    include_stale: bool = Query(default=False),
) -> SceneCandidateCacheSummaryResponse:
    try:
        return scene_candidate_cache_service.get_scene_cache(
            scene_id,
            include_stale=include_stale,
        )
    except StorageError as exc:
        _raise_cache_error(exc)


@router.get("/chapter/{chapter_id}", response_model=SceneCandidateCacheSummaryResponse)
def get_chapter_candidate_cache(
    chapter_id: str,
    include_stale: bool = Query(default=False),
) -> SceneCandidateCacheSummaryResponse:
    try:
        return scene_candidate_cache_service.get_chapter_cache(
            chapter_id,
            include_stale=include_stale,
        )
    except StorageError as exc:
        _raise_cache_error(exc)


@router.get("/candidates/{cached_candidate_id}", response_model=CachedSceneCandidateResponse)
def get_cached_scene_candidate(
    cached_candidate_id: str,
) -> CachedSceneCandidateResponse:
    try:
        candidate = scene_candidate_cache_service.get_cached_candidate(cached_candidate_id)
        return CachedSceneCandidateResponse(candidate=candidate)
    except StorageError as exc:
        _raise_cache_error(exc)


@router.post("/invalidate-by-snapshot", response_model=CandidateCacheInvalidationResponse)
def invalidate_scene_candidate_cache_by_snapshot(
    request: SceneCandidateCacheInvalidateBySnapshotRequest,
) -> CandidateCacheInvalidationResponse:
    try:
        return scene_candidate_cache_service.invalidate_by_snapshot_ids(
            request.snapshot_ids,
            trigger_invalidation_id=request.trigger_invalidation_id,
            reason=request.reason,
        )
    except StorageError as exc:
        _raise_cache_error(exc)


@router.post("/invalidate-by-ref", response_model=CandidateCacheInvalidationResponse)
def invalidate_scene_candidate_cache_by_ref(
    request: SceneCandidateCacheInvalidateByRefRequest,
) -> CandidateCacheInvalidationResponse:
    try:
        return scene_candidate_cache_service.invalidate_by_ref(
            request.changed_ref_type,
            request.changed_ref_id,
            trigger_invalidation_id=request.trigger_invalidation_id,
            reason=request.reason,
        )
    except StorageError as exc:
        _raise_cache_error(exc)


@router.get("/summary", response_model=SceneCandidateCacheSummaryResponse)
def get_scene_candidate_cache_summary(
    scene_id: Optional[str] = Query(default=None),
    chapter_id: Optional[str] = Query(default=None),
    include_stale: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> SceneCandidateCacheSummaryResponse:
    try:
        return scene_candidate_cache_service.summary(
            scene_id=scene_id or "",
            chapter_id=chapter_id or "",
            include_stale=include_stale,
            limit=limit,
        )
    except StorageError as exc:
        _raise_cache_error(exc)
