from fastapi import APIRouter, HTTPException

from app.backend.models.chapter_plan import (
    ChapterPlanConfirmRequest,
    ChapterPlanGenerateRequest,
    ChapterPlanRepairSupportingRoleReferencesResponse,
    ChapterPlanReviseRequest,
    ChapterPlanSceneCountRequest,
    ChapterPlanWorkflowResponse,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.core.story_capacity import chapter_count_range_label, scene_count_range_label
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.chapter_plan_service import ChapterPlanService
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelJsonParseError,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
chapter_plan_service = ChapterPlanService()


def chapter_plan_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    if isinstance(exc, ModelConfigurationError):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "ACTIVE_MODEL_NOT_CONFIGURED",
                "message": "Active model is not configured.",
            },
        )
    if isinstance(exc, ModelJsonParseError):
        return HTTPException(
            status_code=502,
            detail={
                "error_code": "MODEL_JSON_PARSE_FAILED",
                "message": "Model returned invalid JSON.",
            },
        )
    if isinstance(exc, ModelCallError):
        return HTTPException(
            status_code=502,
            detail={
                "error_code": "MODEL_CALL_FAILED",
                "message": str(exc),
            },
        )

    message = str(exc)
    if message.startswith("FOUNDATION_NOT_READY"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "FOUNDATION_NOT_READY",
                "message": "请先确认世界画布并完成主角团初始化，再生成章节路线。",
            },
        )
    if message.startswith("CHAPTER_COUNT_INVALID"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CHAPTER_COUNT_INVALID",
                "message": f"chapter_count must be between {chapter_count_range_label()}.",
            },
        )
    if message.startswith("CURRENT_CHAPTER_INDEX_INVALID"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CURRENT_CHAPTER_INDEX_INVALID",
                "message": "current_chapter_index must be within chapter_count.",
            },
        )
    if message.startswith("chapter_plan_project_story_premise_missing"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "chapter_plan_project_story_premise_missing",
                "message": message,
            },
        )
    if message.startswith("CURRENT_CHAPTER_FRAMEWORK_REQUIRED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CURRENT_CHAPTER_FRAMEWORK_REQUIRED",
                "message": "Build the current chapter framework before generating or confirming the chapter plan.",
            },
        )
    if message.startswith("CHAPTER_FRAMEWORK_AUDIT_MISSING"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CHAPTER_FRAMEWORK_AUDIT_MISSING",
                "message": "Current chapter framework is missing Phase 3 M2 build context or reasons.",
            },
        )
    if message.startswith("CURRENT_CHAPTER_ASSIGNMENT_MISSING"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CURRENT_CHAPTER_ASSIGNMENT_MISSING",
                "message": "Confirmed framework mapping must cover the requested chapter count.",
            },
        )
    if message.startswith("SCENE_COUNT_INVALID"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_COUNT_INVALID",
                "message": f"scene_count must be between {scene_count_range_label()} for the target chapter.",
            },
        )
    if message.startswith("CHAPTER_PLAN_DRAFT_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "CHAPTER_PLAN_DRAFT_MISSING",
                "message": "Current chapter plan draft does not exist.",
            },
        )
    if message.startswith("CHAPTER_PLAN_ALREADY_CONFIRMED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CHAPTER_PLAN_ALREADY_CONFIRMED",
                "message": "Current chapter plan draft has already been confirmed.",
            },
        )
    if message.startswith("CHAPTER_PLAN_BLOCKING_ISSUES"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CHAPTER_PLAN_BLOCKING_ISSUES",
                "message": "Cannot confirm chapter plan while blocking validation issues exist.",
            },
        )
    if "must not be empty" in message or "schema" in message or "must be a list" in message:
        return HTTPException(status_code=400, detail=message)
    if "does not exist" in message:
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_chapter_plan_service() -> ChapterPlanService:
    return scoped_story_service(chapter_plan_service, ChapterPlanService)


@router.get("/current", response_model=ChapterPlanWorkflowResponse)
def get_current_chapter_plan() -> ChapterPlanWorkflowResponse:
    try:
        return active_chapter_plan_service().get_current_plan()
    except Exception as exc:
        raise chapter_plan_error_response(exc) from exc


@router.post("/generate", response_model=ChapterPlanWorkflowResponse)
def generate_chapter_plan(
    request: ChapterPlanGenerateRequest,
) -> ChapterPlanWorkflowResponse:
    try:
        return active_chapter_plan_service().generate_chapter_plan(
            story_goal=request.story_goal,
            chapter_count=request.chapter_count,
            current_chapter_index=request.current_chapter_index,
            framework_composition_id=request.framework_composition_id,
        )
    except Exception as exc:
        raise chapter_plan_error_response(exc) from exc


@router.post("/revise", response_model=ChapterPlanWorkflowResponse)
def revise_chapter_plan(
    request: ChapterPlanReviseRequest,
) -> ChapterPlanWorkflowResponse:
    try:
        return active_chapter_plan_service().revise_chapter_plan(request.revision_prompt)
    except Exception as exc:
        raise chapter_plan_error_response(exc) from exc


@router.post("/set-scene-count", response_model=ChapterPlanWorkflowResponse)
def set_scene_count(
    request: ChapterPlanSceneCountRequest,
) -> ChapterPlanWorkflowResponse:
    try:
        return active_chapter_plan_service().set_scene_count(
            chapter_index=request.chapter_index,
            scene_count=request.scene_count,
        )
    except Exception as exc:
        raise chapter_plan_error_response(exc) from exc


@router.post(
    "/repair-supporting-role-references",
    response_model=ChapterPlanRepairSupportingRoleReferencesResponse,
)
def repair_supporting_role_references() -> ChapterPlanRepairSupportingRoleReferencesResponse:
    try:
        return active_chapter_plan_service().repair_supporting_role_references()
    except Exception as exc:
        raise chapter_plan_error_response(exc) from exc


@router.post("/confirm", response_model=ChapterPlanWorkflowResponse)
def confirm_chapter_plan(
    request: ChapterPlanConfirmRequest,
) -> ChapterPlanWorkflowResponse:
    try:
        return active_chapter_plan_service().confirm_chapter_plan(request.user_input)
    except Exception as exc:
        raise chapter_plan_error_response(exc) from exc
