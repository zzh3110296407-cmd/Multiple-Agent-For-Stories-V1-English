from fastapi import APIRouter, HTTPException, Query

from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.models.scene_gate_repair import (
    SceneGateRepairRunRequest,
    SceneGateRepairRunResponse,
)
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.scene_gate_repair_orchestrator_service import (
    SceneGateRepairOrchestratorService,
)
from app.backend.services.scene_gate_repair_view_projection_service import (
    SceneGateRepairViewProjectionService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
scene_gate_repair_orchestrator_service = SceneGateRepairOrchestratorService()
scene_gate_repair_projection_service = SceneGateRepairViewProjectionService()


@router.post("/scenes/{scene_id}/runs", response_model=SceneGateRepairRunResponse)
def run_scene_gate_repair(
    scene_id: str,
    request: SceneGateRepairRunRequest,
    include_expert: bool = Query(False),
) -> SceneGateRepairRunResponse:
    request_scene_id = (request.scene_id or "").strip()
    if request_scene_id and request_scene_id != scene_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_GATE_REPAIR_SCENE_ID_MISMATCH",
                "message": "Request scene_id must match the route scene_id.",
            },
        )
    try:
        service = scoped_story_service(
            scene_gate_repair_orchestrator_service,
            SceneGateRepairOrchestratorService,
        )
        result = service.run_scene_gate_repair_loop(
            scene_id,
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            initial_revision_id=request.initial_revision_id,
            max_rounds=request.max_rounds,
            force_runtime_refresh=request.force_runtime_refresh,
        )
    except ActiveProjectStoryDataBlocked as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SCENE_GATE_REPAIR_STORAGE_MISSING",
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_GATE_REPAIR_INVALID_REQUEST",
                "message": str(exc),
            },
        ) from exc

    ordinary_view = scene_gate_repair_projection_service.build_ordinary_view(result)
    expert_view = scene_gate_repair_projection_service.build_expert_view(result)
    return SceneGateRepairRunResponse(
        success=True,
        scene_id=scene_id,
        ordinary_view=ordinary_view,
        expert_view=expert_view,
    )
