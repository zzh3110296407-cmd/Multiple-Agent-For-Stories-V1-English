from fastapi import APIRouter, HTTPException, Query

from app.backend.models.memory_pack import (
    BuildChapterMemoryPackRequest,
    BuildSceneMemoryPackRequest,
    ChapterMemoryPackResponse,
    MemoryPackBuildResponse,
    MemoryPackRefreshRequest,
    SceneMemoryPackResponse,
)
from app.backend.services.chapter_memory_service import ChapterMemoryService
from app.backend.services.scene_memory_service import SceneMemoryService
from app.backend.storage.json_store import StorageError


router = APIRouter()
chapter_memory_service = ChapterMemoryService()
scene_memory_service = SceneMemoryService(
    store=chapter_memory_service.store,
    data_dir=chapter_memory_service.data_dir,
    chapter_memory_service=chapter_memory_service,
)


@router.post("/chapter/build", response_model=MemoryPackBuildResponse)
def build_chapter_memory_pack(
    request: BuildChapterMemoryPackRequest,
) -> MemoryPackBuildResponse:
    try:
        pack = chapter_memory_service.build_current_chapter_pack(
            request.chapter_id,
            force_refresh=request.force_refresh,
        )
        return MemoryPackBuildResponse(chapter_memory_pack=pack)
    except StorageError as exc:
        raise _memory_pack_error(exc) from exc


@router.get("/chapter/current", response_model=ChapterMemoryPackResponse)
def get_current_chapter_memory_pack(
    chapter_id: str = Query(...),
) -> ChapterMemoryPackResponse:
    try:
        pack = chapter_memory_service.get_active_chapter_pack(chapter_id)
    except StorageError as exc:
        raise _memory_pack_error(exc) from exc
    if pack is None:
        raise HTTPException(status_code=404, detail="ChapterMemoryPack was not found.")
    return ChapterMemoryPackResponse(chapter_memory_pack=pack)


@router.post("/chapter/refresh", response_model=MemoryPackBuildResponse)
def refresh_chapter_memory_pack(
    request: MemoryPackRefreshRequest,
) -> MemoryPackBuildResponse:
    try:
        pack = chapter_memory_service.refresh_chapter_pack(request.chapter_id)
        return MemoryPackBuildResponse(chapter_memory_pack=pack)
    except StorageError as exc:
        raise _memory_pack_error(exc) from exc


@router.post("/scene/build", response_model=MemoryPackBuildResponse)
def build_scene_memory_pack(
    request: BuildSceneMemoryPackRequest,
) -> MemoryPackBuildResponse:
    try:
        pack = scene_memory_service.build_scene_pack(
            chapter_id=request.chapter_id,
            scene_index=request.scene_index,
            scene_id=request.scene_id,
            scene_goal=request.scene_goal,
            scene_location=request.scene_location,
            active_character_ids=request.active_character_ids,
            include_provisional=request.include_provisional,
            force_refresh=request.force_refresh,
        )
        return MemoryPackBuildResponse(scene_memory_pack=pack)
    except StorageError as exc:
        raise _memory_pack_error(exc) from exc


@router.get("/scene/current", response_model=SceneMemoryPackResponse)
def get_current_scene_memory_pack(
    chapter_id: str = Query(...),
    scene_index: int = Query(..., ge=1),
) -> SceneMemoryPackResponse:
    try:
        pack = scene_memory_service.get_active_scene_pack(chapter_id, scene_index)
    except StorageError as exc:
        raise _memory_pack_error(exc) from exc
    if pack is None:
        raise HTTPException(status_code=404, detail="SceneMemoryPack was not found.")
    return SceneMemoryPackResponse(scene_memory_pack=pack)


@router.post("/scene/refresh", response_model=MemoryPackBuildResponse)
def refresh_scene_memory_pack(
    request: MemoryPackRefreshRequest,
) -> MemoryPackBuildResponse:
    if request.scene_index is None:
        raise HTTPException(status_code=400, detail="scene_index is required.")
    try:
        pack = scene_memory_service.refresh_scene_pack(
            request.chapter_id,
            request.scene_index,
        )
        return MemoryPackBuildResponse(scene_memory_pack=pack)
    except StorageError as exc:
        raise _memory_pack_error(exc) from exc


def _memory_pack_error(exc: StorageError) -> HTTPException:
    message = str(exc)
    if "MISSING" in message or "does not exist" in message:
        return HTTPException(status_code=404, detail=message)
    if "REQUIRED" in message or "INVALID" in message:
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)
