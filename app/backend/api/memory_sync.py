from fastapi import APIRouter, HTTPException

from app.backend.models.memory_update_plan import (
    MemoryUpdatePlanDecisionRequest,
    MemoryUpdatePlanFromRevisionRequest,
    MemoryUpdatePlanResponse,
)
from app.backend.services.memory_update_plan_service import MemoryUpdatePlanService
from app.backend.storage.json_store import StorageError


router = APIRouter()
memory_update_plan_service = MemoryUpdatePlanService()


def memory_sync_error_response(exc: Exception) -> HTTPException:
    message = str(exc)
    if message.startswith("MEMORY_SYNC_SCENE_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "MEMORY_SYNC_SCENE_MISSING",
                "message": "场景不存在，无法生成记忆同步计划。",
            },
        )
    if message.startswith("MEMORY_SYNC_REVISION_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "MEMORY_SYNC_REVISION_MISSING",
                "message": "修订候选不存在，无法生成记忆同步计划。",
            },
        )
    if message.startswith("MEMORY_SYNC_REVISION_NOT_CONFIRMED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "MEMORY_SYNC_REVISION_NOT_CONFIRMED",
                "message": "请先确认场景修订，再应用记忆同步计划。",
            },
        )
    if message.startswith("MEMORY_SYNC_PLAN_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "MEMORY_SYNC_PLAN_MISSING",
                "message": "记忆同步计划不存在。",
            },
        )
    if message.startswith("MEMORY_SYNC_CONFIRMATION_REQUIRED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "MEMORY_SYNC_CONFIRMATION_REQUIRED",
                "message": "记忆同步计划需要先确认再应用。",
            },
        )
    if message.startswith("MEMORY_SYNC_PLAN_ALREADY_APPLIED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "MEMORY_SYNC_PLAN_ALREADY_APPLIED",
                "message": "记忆同步计划已经应用，不能重复拒绝。",
            },
        )
    if message.startswith("MEMORY_SYNC_PLAN_REJECTED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "MEMORY_SYNC_PLAN_REJECTED",
                "message": "记忆同步计划已经拒绝，不能继续应用。",
            },
        )
    if message.startswith("MEMORY_SYNC_APPLY_BLOCKED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "MEMORY_SYNC_APPLY_BLOCKED",
                "message": message.split(":", 1)[-1].strip() or "记忆同步计划暂不能应用。",
            },
        )
    if message.startswith("SCENE_REVISION_CONTINUITY_BLOCKING_ISSUES"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_REVISION_CONTINUITY_BLOCKING_ISSUES",
                "message": "当前修订存在连续性阻塞问题，暂不能应用记忆同步计划。",
            },
        )
    if "schema is invalid" in message:
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


@router.post("/scene/{scene_id}/plan-from-revision", response_model=MemoryUpdatePlanResponse)
def create_plan_from_revision(
    scene_id: str,
    request: MemoryUpdatePlanFromRevisionRequest,
) -> MemoryUpdatePlanResponse:
    try:
        plan = memory_update_plan_service.create_plan_from_revision(
            scene_id=scene_id,
            revision_id=request.revision_id,
            dry_run=request.dry_run,
        )
        return MemoryUpdatePlanResponse(plan=plan)
    except StorageError as exc:
        raise memory_sync_error_response(exc) from exc


@router.get("/plans/{plan_id}", response_model=MemoryUpdatePlanResponse)
def get_memory_update_plan(plan_id: str) -> MemoryUpdatePlanResponse:
    try:
        return MemoryUpdatePlanResponse(
            plan=memory_update_plan_service.get_plan(plan_id)
        )
    except StorageError as exc:
        raise memory_sync_error_response(exc) from exc


@router.post("/plans/{plan_id}/confirm", response_model=MemoryUpdatePlanResponse)
def confirm_memory_update_plan(
    plan_id: str,
    request: MemoryUpdatePlanDecisionRequest,
) -> MemoryUpdatePlanResponse:
    try:
        plan, decision = memory_update_plan_service.confirm_plan(
            plan_id,
            user_input=request.user_input or "",
        )
        return MemoryUpdatePlanResponse(plan=plan, decision=decision)
    except StorageError as exc:
        raise memory_sync_error_response(exc) from exc


@router.post("/plans/{plan_id}/apply", response_model=MemoryUpdatePlanResponse)
def apply_memory_update_plan(plan_id: str) -> MemoryUpdatePlanResponse:
    try:
        plan, decision = memory_update_plan_service.apply_plan(plan_id)
        return MemoryUpdatePlanResponse(plan=plan, decision=decision)
    except StorageError as exc:
        raise memory_sync_error_response(exc) from exc


@router.post("/plans/{plan_id}/reject", response_model=MemoryUpdatePlanResponse)
def reject_memory_update_plan(
    plan_id: str,
    request: MemoryUpdatePlanDecisionRequest,
) -> MemoryUpdatePlanResponse:
    try:
        plan, decision = memory_update_plan_service.reject_plan(
            plan_id,
            user_input=request.user_input or "",
        )
        return MemoryUpdatePlanResponse(plan=plan, decision=decision)
    except StorageError as exc:
        raise memory_sync_error_response(exc) from exc


@router.post("/plans/{plan_id}/confirm-and-apply", response_model=MemoryUpdatePlanResponse)
def confirm_and_apply_memory_update_plan(
    plan_id: str,
    request: MemoryUpdatePlanDecisionRequest,
) -> MemoryUpdatePlanResponse:
    try:
        plan, decision = memory_update_plan_service.confirm_and_apply_plan(
            plan_id,
            user_input=request.user_input or "",
        )
        return MemoryUpdatePlanResponse(plan=plan, decision=decision)
    except StorageError as exc:
        raise memory_sync_error_response(exc) from exc
