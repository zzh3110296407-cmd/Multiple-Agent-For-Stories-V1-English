from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.character import (
    CharacterContextBuildRequest,
    CharacterContextPreviewResponse,
    CharacterStateChangeResponse,
    PendingCharacterStateChangeDecisionRequest,
    PendingCharacterStateChangesResponse,
    ProposedCharacterStateChange,
    RoleArchiveRequest,
    RoleCreateRequest,
    RolePatchRequest,
    RoleResponse,
    RoleTierChangeRequest,
    RolesResponse,
)
from app.backend.models.role_generation import (
    RoleDraftDecisionRequest,
    RoleGenerateRequest,
    RoleGenerationResponse,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.character_context_builder import CharacterContextBuilder
from app.backend.services.character_state_update_service import CharacterStateUpdateService
from app.backend.services.role_generation_service import RoleGenerationService
from app.backend.services.role_management_service import RoleManagementService
from app.backend.storage.json_store import StorageError


router = APIRouter()
role_service = RoleManagementService()
role_generation_service = RoleGenerationService()
context_builder = CharacterContextBuilder()
state_update_service = CharacterStateUpdateService()


def role_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    message = str(exc)
    if "NOT_FOUND" in message or "does not exist" in message:
        return HTTPException(status_code=404, detail=message)
    if message.startswith("MAIN_CAST_A_TIER_CANNOT_BE_DOWNGRADED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "MAIN_CAST_A_TIER_CANNOT_BE_DOWNGRADED",
                "message": "A-tier 主角团角色不能通过 Role Management 降级。",
            },
        )
    if message.startswith("MAIN_CAST_A_TIER_CANNOT_BE_ARCHIVED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "MAIN_CAST_A_TIER_CANNOT_BE_ARCHIVED",
                "message": "A-tier 主角团角色不能通过 Role Management 归档。",
            },
        )
    if message.startswith("A_TIER_MAJOR_PATCH_REQUIRES_PENDING_CHANGE"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "A_TIER_MAJOR_PATCH_REQUIRES_PENDING_CHANGE",
                "message": "A-tier \u91cd\u5927\u957f\u671f\u72b6\u6001\u53d8\u5316\u5fc5\u987b\u5148\u8fdb\u5165\u5f85\u786e\u8ba4\u961f\u5217\uff0c\u4e0d\u80fd\u901a\u8fc7 Role Patch \u76f4\u63a5\u5199\u5165\u3002",
            },
        )
    if (
        "schema validation" in message
        or "must be" in message
        or message.startswith("ROLE_GENERATION_PROMPT_REQUIRED")
        or message.startswith("ROLE_GENERATION_INVALID_TARGET_TIER")
        or message.startswith("USE_CHARACTER_MAIN_CAST_GENERATOR_FOR_A_TIER")
        or message.startswith("WORLD_CANVAS_NOT_CONFIRMED")
        or message.startswith("role_generation_project_story_premise_missing")
        or message.startswith("ROLE_NAME_REQUIRED")
        or message.startswith("CHARACTER_STATE_CHANGE_NOT_PENDING")
        or message.startswith("ROLE_GENERATION_DRAFT_HAS_BLOCKING_ISSUES")
    ):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("ROLE_GENERATION_DRAFT_NOT_CONFIRMABLE"):
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_role_service() -> RoleManagementService:
    return scoped_story_service(role_service, RoleManagementService)


def active_role_generation_service() -> RoleGenerationService:
    return scoped_story_service(role_generation_service, RoleGenerationService)


def active_context_builder() -> CharacterContextBuilder:
    return scoped_story_service(context_builder, CharacterContextBuilder)


def active_state_update_service() -> CharacterStateUpdateService:
    return scoped_story_service(state_update_service, CharacterStateUpdateService)


@router.get("", response_model=RolesResponse)
def list_roles(
    tier: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
) -> RolesResponse:
    try:
        return RolesResponse(
            roles=active_role_service().list_roles(
                tier=tier,
                status=status,
                include_archived=include_archived,
            )
        )
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.post("/generate", response_model=RoleGenerationResponse)
def generate_role_draft(request: RoleGenerateRequest) -> RoleGenerationResponse:
    try:
        return active_role_generation_service().generate_role_draft(
            user_prompt=request.user_prompt,
            target_tier=request.target_tier,
            role_hint=request.role_hint,
            story_function_hint=request.story_function_hint,
        )
    except (StorageError, ValueError) as exc:
        raise role_error_response(exc) from exc


@router.get("/generated-draft", response_model=RoleGenerationResponse)
def get_generated_role_draft() -> RoleGenerationResponse:
    try:
        return active_role_generation_service().get_current_draft()
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.post("/generated-draft/confirm", response_model=RoleGenerationResponse)
def confirm_generated_role_draft(
    request: RoleDraftDecisionRequest,
) -> RoleGenerationResponse:
    try:
        return active_role_generation_service().confirm_current_draft(
            user_input=request.user_input,
        )
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.delete("/generated-draft", response_model=RoleGenerationResponse)
def clear_generated_role_draft() -> RoleGenerationResponse:
    try:
        return active_role_generation_service().clear_current_draft()
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.get("/{character_id}", response_model=RoleResponse)
def get_role(character_id: str) -> RoleResponse:
    try:
        return RoleResponse(role=active_role_service().get_role(character_id))
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.post("", response_model=RoleResponse)
def create_role(request: RoleCreateRequest) -> RoleResponse:
    try:
        role, decision = active_role_service().create_role(request)
        return RoleResponse(role=role, decision=decision)
    except (StorageError, ValueError) as exc:
        raise role_error_response(exc) from exc


@router.patch("/{character_id}", response_model=RoleResponse)
def patch_role(character_id: str, request: RolePatchRequest) -> RoleResponse:
    try:
        role, decision = active_role_service().patch_role(character_id, request)
        return RoleResponse(role=role, decision=decision)
    except (StorageError, ValueError) as exc:
        raise role_error_response(exc) from exc


@router.post("/{character_id}/change-tier", response_model=RoleResponse)
def change_role_tier(
    character_id: str,
    request: RoleTierChangeRequest,
) -> RoleResponse:
    try:
        role, decision = active_role_service().change_tier(character_id, request)
        return RoleResponse(role=role, decision=decision)
    except (StorageError, ValueError) as exc:
        raise role_error_response(exc) from exc


@router.post("/{character_id}/archive", response_model=RoleResponse)
def archive_role(character_id: str, request: RoleArchiveRequest) -> RoleResponse:
    try:
        role, decision = active_role_service().archive_role(character_id, request)
        return RoleResponse(role=role, decision=decision)
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.post("/context-preview", response_model=CharacterContextPreviewResponse)
def context_preview(
    request: CharacterContextBuildRequest,
) -> CharacterContextPreviewResponse:
    try:
        return active_context_builder().build_context(request)
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.get(
    "/state-changes/pending",
    response_model=PendingCharacterStateChangesResponse,
)
def pending_state_changes() -> PendingCharacterStateChangesResponse:
    try:
        return PendingCharacterStateChangesResponse(
            changes=active_state_update_service().list_pending()
        )
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.post(
    "/state-changes/propose",
    response_model=CharacterStateChangeResponse,
)
def propose_state_change(
    request: ProposedCharacterStateChange,
) -> CharacterStateChangeResponse:
    try:
        change, character, decision = active_state_update_service().propose_change(request)
        return CharacterStateChangeResponse(
            change=change,
            character=character,
            decision=decision,
        )
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.post(
    "/state-changes/{change_id}/confirm",
    response_model=CharacterStateChangeResponse,
)
def confirm_state_change(
    change_id: str,
    request: PendingCharacterStateChangeDecisionRequest,
) -> CharacterStateChangeResponse:
    try:
        change, character, decision = active_state_update_service().confirm_change(
            change_id,
            user_input=request.user_input,
        )
        return CharacterStateChangeResponse(
            change=change,
            character=character,
            decision=decision,
        )
    except StorageError as exc:
        raise role_error_response(exc) from exc


@router.post(
    "/state-changes/{change_id}/reject",
    response_model=CharacterStateChangeResponse,
)
def reject_state_change(
    change_id: str,
    request: PendingCharacterStateChangeDecisionRequest,
) -> CharacterStateChangeResponse:
    try:
        change, decision = active_state_update_service().reject_change(
            change_id,
            user_input=request.user_input,
        )
        return CharacterStateChangeResponse(change=change, decision=decision)
    except StorageError as exc:
        raise role_error_response(exc) from exc
