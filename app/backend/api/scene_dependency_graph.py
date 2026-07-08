from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.scene_snapshot import SceneDependencyGraphSummaryResponse
from app.backend.services.scene_version_snapshot_service import (
    SceneVersionSnapshotService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
scene_snapshot_service = SceneVersionSnapshotService()


@router.get("/summary", response_model=SceneDependencyGraphSummaryResponse)
def get_scene_dependency_graph_summary(
    chapter_id: Optional[str] = Query(default=None),
    scene_id: Optional[str] = Query(default=None),
) -> SceneDependencyGraphSummaryResponse:
    try:
        return scene_snapshot_service.dependency_graph_summary(
            chapter_id=chapter_id,
            scene_id=scene_id,
        )
    except StorageError as exc:
        message = str(exc)
        code, _, detail = message.partition(":")
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": code,
                "message": detail.strip() or message,
            },
        ) from exc
