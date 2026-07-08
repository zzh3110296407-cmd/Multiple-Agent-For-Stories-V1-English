import json

from fastapi import APIRouter, HTTPException

from app.backend.models.scene_generation import (
    SceneCommitRequest,
    SceneConfirmDraftRequest,
    SceneGenerateFirstRequest,
    SceneGenerateNextRequest,
    SceneGenerationResponse,
    SceneProgressResponse,
    SceneRegenerateFirstRequest,
    SceneTemporaryConfirmRequest,
)
from app.backend.models.writer_quality_surface import WriterQualitySurfaceResponse
from app.backend.models.scene_revision import (
    SceneConfirmRevisionRequest,
    SceneRejectRevisionRequest,
    SceneReviseRequest,
    SceneRevisionResponse,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelJsonParseError,
)
from app.backend.services.scene_generation_service import SceneGenerationService
from app.backend.services.scene_runtime_refresh_state_service import (
    SceneRuntimeRefreshStateService,
)
from app.backend.services.scene_gate_readiness_service import SceneGateReadinessService
from app.backend.services.scene_revision_service import SceneRevisionService
from app.backend.services.writer_quality_surface_projection_service import (
    WriterQualitySurfaceProjectionService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
scene_generation_service = SceneGenerationService()
scene_revision_service = SceneRevisionService()
scene_runtime_refresh_state_service = SceneRuntimeRefreshStateService()
scene_gate_readiness_service = SceneGateReadinessService()
writer_quality_surface_service = WriterQualitySurfaceProjectionService()


def scene_error_response(exc: Exception) -> HTTPException:
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
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))

    message = str(exc)
    if message.startswith("SCENE_PARTICIPATION_CONFIRMATION_REQUIRED"):
        payload: dict[str, object] = {}
        _, _, raw_payload = message.partition(":")
        try:
            parsed = json.loads(raw_payload.strip())
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_PARTICIPATION_CONFIRMATION_REQUIRED",
                "message": str(
                    payload.get("message")
                    or "Scene participation needs user confirmation before scene generation."
                ),
                "recommended_action": payload.get(
                    "recommended_action",
                    "review_scene_participant_candidates",
                ),
                "pending_creation_candidate_ids": payload.get(
                    "pending_creation_candidate_ids",
                    [],
                ),
                "unresolved_required_need_ids": payload.get(
                    "unresolved_required_need_ids",
                    [],
                ),
                "chapter_id": (
                    payload.get("readiness", {}).get("chapter_id", "")
                    if isinstance(payload.get("readiness"), dict)
                    else ""
                ),
                "scene_index": (
                    payload.get("readiness", {}).get("scene_index", None)
                    if isinstance(payload.get("readiness"), dict)
                    else None
                ),
                "blocking_issues": payload.get("blocking_issues", []),
                "readiness": payload.get("readiness", {}),
            },
        )
    if message.startswith("SCENE_GENERATION_NOT_READY"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_GENERATION_NOT_READY",
                "message": "请先确认世界画布、主角团、章节路线、当前章概要和幕数，再生成第一幕。",
            },
        )
    if message.startswith("SCENE_ALREADY_CONFIRMED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_ALREADY_CONFIRMED",
                "message": "当前场景已经提交，不能覆盖。",
            },
        )
    if message.startswith("SCENE_NEXT_NOT_READY"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_NEXT_NOT_READY",
                "message": message.split(":", 1)[-1].strip() or "下一幕暂不可生成。",
            },
        )
    if message.startswith("SCENE_COUNT_REACHED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_COUNT_REACHED",
                "message": "当前章已经达到 scene_count，不能继续生成下一幕。",
            },
        )
    if message.startswith("SCENE_PREVIOUS_NOT_COMMITTED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_PREVIOUS_NOT_COMMITTED",
                "message": message.split(":", 1)[-1].strip() or "上一幕尚未确认，不能继续生成下一幕。",
            },
        )
    if message.startswith("SCENE_COMMIT_TYPE_INVALID"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_COMMIT_TYPE_INVALID",
                "message": "提交类型只能是 confirmed、revised 或 temporary_confirmed。",
            },
        )
    if message.startswith("SCENE_DRAFT_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "SCENE_DRAFT_MISSING",
                "message": "Current scene draft does not exist.",
            },
        )
    if message.startswith("SCENE_QUALITY_BLOCKING_ISSUES"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_QUALITY_BLOCKING_ISSUES",
                "message": "Cannot confirm scene while blocking quality issues exist.",
            },
        )
    if message.startswith("SCENE_CONTINUITY_BLOCKING_ISSUES"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_CONTINUITY_BLOCKING_ISSUES",
                "message": "当前幕存在连续性阻塞问题，请先运行连续性检查并处理。",
            },
        )
    if (
        message.startswith("SCENE_RUNTIME_")
        or message.startswith("SCENE_COMPOSITE_RUNTIME_")
        or message.startswith("SCENE_ABCD_RUNTIME_")
        or message.startswith("SCENE_GATE_READINESS_")
    ):
        code = message.split(":", 1)[0].strip()
        return HTTPException(
            status_code=409,
            detail={
                "error_code": code,
                "message": message.split(":", 1)[-1].strip()
                or "Scene runtime refresh state is not ready for final confirmation.",
            },
        )
    if message.startswith("ABCD_RUNTIME_GATE_BLOCKING_ISSUES"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "ABCD_RUNTIME_GATE_BLOCKING_ISSUES",
                "message": "ABCD runtime gate found blocking or confirmation-required issues.",
            },
        )
    if message.startswith("SCENE_CONFIRMATION_INPUT_REQUIRED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_CONFIRMATION_INPUT_REQUIRED",
                "message": "Quality report requires user confirmation input.",
            },
        )
    if message.startswith("SCENE_REVISION_SCENE_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "SCENE_REVISION_SCENE_MISSING",
                "message": "Scene does not exist.",
            },
        )
    if message.startswith("SCENE_REVISION_PROMPT_REQUIRED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_REVISION_PROMPT_REQUIRED",
                "message": "Revision prompt is required.",
            },
        )
    if message.startswith("SCENE_REVISION_NOT_READY"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_REVISION_NOT_READY",
                "message": message,
            },
        )
    if message.startswith("SCENE_REVISION_CONFIRMED_SCENE_LOCKED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_REVISION_CONFIRMED_SCENE_LOCKED",
                "message": "Confirmed or committed scenes cannot be revised by the Milestone 8 draft revision flow.",
            },
        )
    if message.startswith("HARD_RULE_CONFLICT"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "HARD_RULE_CONFLICT",
                "message": "Revision conflicts with World Canvas hard rules.",
            },
        )
    if message.startswith("SCENE_REVISION_CANDIDATE_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "SCENE_REVISION_CANDIDATE_MISSING",
                "message": "Revision candidate does not exist.",
            },
        )
    if message.startswith("SCENE_REVISION_CANDIDATE_NOT_ACTIVE"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_REVISION_CANDIDATE_NOT_ACTIVE",
                "message": "Revision candidate is not active.",
            },
        )
    if message.startswith("SCENE_REVISION_CONFIRMATION_INPUT_REQUIRED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_REVISION_CONFIRMATION_INPUT_REQUIRED",
                "message": "Revision requires explicit user confirmation input.",
            },
        )
    if message.startswith("SCENE_REVISION_QUALITY_BLOCKING_ISSUES"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_REVISION_QUALITY_BLOCKING_ISSUES",
                "message": "Cannot confirm revision while blocking quality issues exist.",
            },
        )
    if message.startswith("SCENE_REVISION_CONTINUITY_BLOCKING_ISSUES"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_REVISION_CONTINUITY_BLOCKING_ISSUES",
                "message": "当前修订存在连续性阻塞问题，请先运行连续性检查并处理。",
            },
        )
    if message.startswith("SCENE_REVISION_MODEL_SCHEMA_INVALID"):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("SCENE_INDEX_INVALID"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "SCENE_INDEX_INVALID",
                "message": "generate-first 只支持第 1 幕；后续场景请使用生成下一幕。",
            },
        )
    if message.startswith("SCENE_MODEL_SCHEMA_INVALID"):
        return HTTPException(status_code=400, detail=message)
    if "does not exist" in message:
        return HTTPException(status_code=404, detail=message)
    if "schema is invalid" in message:
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_scene_generation_service() -> SceneGenerationService:
    return scoped_story_service(scene_generation_service, SceneGenerationService)


def active_scene_revision_service() -> SceneRevisionService:
    return scoped_story_service(scene_revision_service, SceneRevisionService)


def active_scene_runtime_refresh_state_service() -> SceneRuntimeRefreshStateService:
    return scoped_story_service(
        scene_runtime_refresh_state_service,
        SceneRuntimeRefreshStateService,
    )


def active_scene_gate_readiness_service() -> SceneGateReadinessService:
    return scoped_story_service(scene_gate_readiness_service, SceneGateReadinessService)


@router.get("/current", response_model=SceneGenerationResponse)
def get_current_scene() -> SceneGenerationResponse:
    try:
        return active_scene_generation_service().get_current_scene()
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.get("/progress", response_model=SceneProgressResponse)
def get_scene_progress(chapter_id: str | None = None) -> SceneProgressResponse:
    try:
        return active_scene_generation_service().get_scene_progress(chapter_id)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/generate-first", response_model=SceneGenerationResponse)
def generate_first_scene(
    request: SceneGenerateFirstRequest,
) -> SceneGenerationResponse:
    try:
        return active_scene_generation_service().generate_first_scene(
            chapter_id=request.chapter_id,
            scene_index=request.scene_index,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/generate-next", response_model=SceneGenerationResponse)
def generate_next_scene(
    request: SceneGenerateNextRequest,
) -> SceneGenerationResponse:
    try:
        return active_scene_generation_service().generate_next_scene(request)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/regenerate-first", response_model=SceneGenerationResponse)
def regenerate_first_scene(
    request: SceneRegenerateFirstRequest,
) -> SceneGenerationResponse:
    try:
        return active_scene_generation_service().regenerate_first_scene(
            regeneration_hint=request.regeneration_hint,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/confirm-draft", response_model=SceneGenerationResponse)
def confirm_scene_draft(
    request: SceneConfirmDraftRequest,
) -> SceneGenerationResponse:
    try:
        return active_scene_generation_service().confirm_scene_draft(
            user_input=request.user_input,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/{scene_id}/commit", response_model=SceneGenerationResponse)
def commit_scene(
    scene_id: str,
    request: SceneCommitRequest,
) -> SceneGenerationResponse:
    try:
        return active_scene_generation_service().commit_scene(scene_id, request)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/{scene_id}/temporary-confirm", response_model=SceneGenerationResponse)
def temporary_confirm_scene(
    scene_id: str,
    request: SceneTemporaryConfirmRequest,
) -> SceneGenerationResponse:
    try:
        return active_scene_generation_service().temporary_confirm_scene(
            scene_id=scene_id,
            user_input=request.user_input,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.get("/{scene_id}/runtime-refresh-state")
def get_scene_runtime_refresh_state(scene_id: str) -> dict:
    try:
        return active_scene_runtime_refresh_state_service().evaluate(scene_id)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.get("/{scene_id}/gate-readiness")
def get_scene_gate_readiness(scene_id: str) -> dict:
    try:
        return active_scene_gate_readiness_service().evaluate(scene_id)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.get("/{scene_id}/writer-quality-surface", response_model=WriterQualitySurfaceResponse)
def get_scene_writer_quality_surface(
    scene_id: str,
    include_expert: bool = False,
) -> WriterQualitySurfaceResponse:
    try:
        service = scoped_story_service(
            writer_quality_surface_service,
            WriterQualitySurfaceProjectionService,
        )
        return service.build_surface(scene_id, include_expert=include_expert)
    except Exception as exc:
        raise scene_error_response(exc) from exc


@router.post("/{scene_id}/runtime-refresh-state/refresh")
def refresh_scene_runtime_refresh_state(
    scene_id: str,
    force_refresh: bool = False,
) -> dict:
    try:
        return active_scene_runtime_refresh_state_service().refresh(
            scene_id,
            force_refresh=force_refresh,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.get("/{scene_id}/revision-candidate", response_model=SceneRevisionResponse)
def get_scene_revision_candidate(scene_id: str) -> SceneRevisionResponse:
    try:
        return active_scene_revision_service().get_current_revision_candidate(scene_id)
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/{scene_id}/revise", response_model=SceneRevisionResponse)
def revise_scene(
    scene_id: str,
    request: SceneReviseRequest,
) -> SceneRevisionResponse:
    try:
        return active_scene_revision_service().revise_scene(
            scene_id=scene_id,
            revision_prompt=request.revision_prompt,
            force_hard_rule_override=request.force_hard_rule_override,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/{scene_id}/confirm-revision", response_model=SceneRevisionResponse)
def confirm_scene_revision(
    scene_id: str,
    request: SceneConfirmRevisionRequest,
) -> SceneRevisionResponse:
    try:
        return active_scene_revision_service().confirm_revision(
            scene_id=scene_id,
            revision_id=request.revision_id,
            user_input=request.user_input,
            accepted_abcd_runtime_issue_ids=request.accepted_abcd_runtime_issue_ids,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc


@router.post("/{scene_id}/reject-revision", response_model=SceneRevisionResponse)
def reject_scene_revision(
    scene_id: str,
    request: SceneRejectRevisionRequest,
) -> SceneRevisionResponse:
    try:
        return active_scene_revision_service().reject_revision(
            scene_id=scene_id,
            revision_id=request.revision_id,
            user_input=request.user_input,
        )
    except (StorageError, ModelConfigurationError, ModelJsonParseError, ModelCallError) as exc:
        raise scene_error_response(exc) from exc
