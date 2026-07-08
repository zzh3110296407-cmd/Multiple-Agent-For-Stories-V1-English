from fastapi import APIRouter, HTTPException, Query

from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.models.role_memory_writeback import (
    RoleMemoryWriteAudit,
    RoleSceneMemoryEntry,
    TieredSceneMemoryWritePlan,
    TieredSceneMemoryWritebackResponse,
)
from app.backend.services.active_project_boundary_service import (
    ActiveProjectStoryDataBlocked,
)
from app.backend.services.tiered_scene_memory_writeback_service import (
    TieredSceneMemoryWritebackService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
role_memory_service = TieredSceneMemoryWritebackService()


def active_role_memory_service() -> TieredSceneMemoryWritebackService:
    return scoped_story_service(
        role_memory_service,
        TieredSceneMemoryWritebackService,
    )


@router.get("/write-plans", response_model=list[TieredSceneMemoryWritePlan])
def list_role_memory_write_plans(
    scene_id: str | None = Query(default=None),
) -> list[TieredSceneMemoryWritePlan]:
    try:
        return active_role_memory_service().list_plans(scene_id=scene_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _role_memory_error(exc) from exc


@router.get("/write-plans/{plan_id}", response_model=TieredSceneMemoryWritePlan)
def get_role_memory_write_plan(plan_id: str) -> TieredSceneMemoryWritePlan:
    try:
        return active_role_memory_service().get_plan(plan_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _role_memory_error(exc) from exc


@router.get("/entries", response_model=list[RoleSceneMemoryEntry])
def list_role_memory_entries(
    scene_id: str | None = Query(default=None),
    character_id: str | None = Query(default=None),
) -> list[RoleSceneMemoryEntry]:
    try:
        return active_role_memory_service().list_entries(
            scene_id=scene_id,
            character_id=character_id,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _role_memory_error(exc) from exc


@router.get("/entries/{entry_id}", response_model=RoleSceneMemoryEntry)
def get_role_memory_entry(entry_id: str) -> RoleSceneMemoryEntry:
    try:
        return active_role_memory_service().get_entry(entry_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _role_memory_error(exc) from exc


@router.get("/audits/{audit_id}", response_model=RoleMemoryWriteAudit)
def get_role_memory_audit(audit_id: str) -> RoleMemoryWriteAudit:
    try:
        return active_role_memory_service().get_audit(audit_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _role_memory_error(exc) from exc


@router.post(
    "/scenes/{scene_id}/rebuild-write-plan",
    response_model=TieredSceneMemoryWritebackResponse,
)
def rebuild_role_memory_write_plan(
    scene_id: str,
) -> TieredSceneMemoryWritebackResponse:
    try:
        return active_role_memory_service().rebuild_write_plan_for_scene(scene_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _role_memory_error(exc) from exc


def _role_memory_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    message = str(exc)
    code = message.split(":", 1)[0]
    error_code = (
        code
        if code.startswith("TIERED_MEMORY_WRITEBACK_")
        else "TIERED_MEMORY_WRITEBACK_INTERNAL_ERROR"
    )
    status_code = 500
    if "NOT_FOUND" in error_code:
        status_code = 404
    elif (
        "REQUIRED" in error_code
        or "INVALID" in error_code
        or "MISMATCH" in error_code
    ):
        status_code = 400
    if status_code == 500:
        message = "Tiered role memory writeback operation failed."
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": message,
        },
    )
