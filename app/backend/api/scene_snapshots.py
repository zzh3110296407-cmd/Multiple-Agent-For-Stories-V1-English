from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.scene_snapshot import (
    SceneSnapshotCreateForSceneRequest,
    SceneSnapshotInvalidateByRefRequest,
    SceneSnapshotListResponse,
    SceneSnapshotResponse,
    SnapshotInvalidationResponse,
)
from app.backend.services.scene_version_snapshot_service import (
    SceneVersionSnapshotService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
scene_snapshot_service = SceneVersionSnapshotService()


def _raise_scene_snapshot_error(exc: StorageError) -> None:
    message = str(exc)
    status_code = 404 if "NOT_FOUND" in message else 400
    code, _, detail = message.partition(":")
    raise HTTPException(
        status_code=status_code,
        detail={
            "error_code": code,
            "message": detail.strip() or message,
        },
    ) from exc


@router.post("/create-for-scene", response_model=SceneSnapshotResponse)
def create_snapshot_for_scene(
    request: SceneSnapshotCreateForSceneRequest,
) -> SceneSnapshotResponse:
    try:
        snapshot = scene_snapshot_service.create_snapshot_for_scene(
            scene_id=request.scene_id,
            snapshot_type=request.snapshot_type,
            target_scene_id=request.target_scene_id,
            extra_refs=request.extra_refs,
        )
        return SceneSnapshotResponse(snapshot=snapshot)
    except StorageError as exc:
        _raise_scene_snapshot_error(exc)


@router.get("/by-scene/{scene_id}", response_model=SceneSnapshotListResponse)
def list_snapshots_by_scene(
    scene_id: str,
    status: Optional[str] = Query(default=None),
    snapshot_type: Optional[str] = Query(default=None),
) -> SceneSnapshotListResponse:
    try:
        snapshots = scene_snapshot_service.list_snapshots(
            scene_id=scene_id,
            status=status,
            snapshot_type=snapshot_type,
        )
        return SceneSnapshotListResponse(snapshots=snapshots, count=len(snapshots))
    except StorageError as exc:
        _raise_scene_snapshot_error(exc)


@router.get("/using-ref", response_model=SceneSnapshotListResponse)
def list_snapshots_using_ref(
    ref_type: str,
    ref_id: str,
    status: Optional[str] = Query(default=None),
) -> SceneSnapshotListResponse:
    try:
        snapshots = scene_snapshot_service.list_snapshots_using_ref(
            ref_type=ref_type,
            ref_id=ref_id,
            status=status,
        )
        return SceneSnapshotListResponse(snapshots=snapshots, count=len(snapshots))
    except StorageError as exc:
        _raise_scene_snapshot_error(exc)


@router.post("/invalidate-by-ref", response_model=SnapshotInvalidationResponse)
def invalidate_snapshots_by_ref(
    request: SceneSnapshotInvalidateByRefRequest,
) -> SnapshotInvalidationResponse:
    try:
        return scene_snapshot_service.invalidate_by_changed_ref(
            changed_ref_type=request.changed_ref_type,
            changed_ref_id=request.changed_ref_id,
            old_version_id=request.old_version_id,
            new_version_id=request.new_version_id,
            reason=request.reason,
        )
    except StorageError as exc:
        _raise_scene_snapshot_error(exc)


@router.get("/{snapshot_id}", response_model=SceneSnapshotResponse)
def get_scene_snapshot(snapshot_id: str) -> SceneSnapshotResponse:
    try:
        return SceneSnapshotResponse(
            snapshot=scene_snapshot_service.get_snapshot(snapshot_id)
        )
    except StorageError as exc:
        _raise_scene_snapshot_error(exc)
