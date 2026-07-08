from fastapi import APIRouter, HTTPException, Query

from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.models.character_intent import (
    CharacterActionIntentionCandidate,
    CharacterIntentPackageBuildRequest,
    CharacterIntentPackageBuildResponse,
    CharacterIntentPackageReadResponse,
    CharacterIntentPolicyResponse,
    CharacterIntentRiskReport,
)
from app.backend.models.narrative_layer import CharacterPsychologyTrace
from app.backend.services.active_project_boundary_service import (
    ActiveProjectStoryDataBlocked,
)
from app.backend.services.character_intent_service import (
    TieredCharacterIntentPackageService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
intent_service = TieredCharacterIntentPackageService()


def active_character_intent_service() -> TieredCharacterIntentPackageService:
    return scoped_story_service(intent_service, TieredCharacterIntentPackageService)


@router.post("/packages", response_model=CharacterIntentPackageBuildResponse)
def build_character_intent_package(
    request: CharacterIntentPackageBuildRequest,
) -> CharacterIntentPackageBuildResponse:
    try:
        return active_character_intent_service().build_response(
            request.scene_participation_package_id,
            force_refresh=request.force_refresh,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _character_intent_error(exc) from exc


@router.get("/packages/current", response_model=CharacterIntentPackageReadResponse)
def get_current_character_intent_package(
    chapter_id: str = Query(...),
    scene_index: int = Query(..., ge=1),
) -> CharacterIntentPackageReadResponse:
    try:
        return active_character_intent_service().get_current_package(
            chapter_id=chapter_id,
            scene_index=scene_index,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _character_intent_error(exc) from exc


@router.get("/packages/{package_id}", response_model=CharacterIntentPackageReadResponse)
def get_character_intent_package(package_id: str) -> CharacterIntentPackageReadResponse:
    try:
        return active_character_intent_service().get_package(package_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _character_intent_error(exc) from exc


@router.post(
    "/packages/{package_id}/refresh",
    response_model=CharacterIntentPackageBuildResponse,
)
def refresh_character_intent_package(package_id: str) -> CharacterIntentPackageBuildResponse:
    try:
        return active_character_intent_service().refresh_package(package_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _character_intent_error(exc) from exc


@router.get("/traces/{trace_id}", response_model=CharacterPsychologyTrace)
def get_character_intent_trace(trace_id: str) -> CharacterPsychologyTrace:
    try:
        return active_character_intent_service().get_trace(trace_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _character_intent_error(exc) from exc


@router.get("/candidates/{candidate_id}", response_model=CharacterActionIntentionCandidate)
def get_character_intent_candidate(candidate_id: str) -> CharacterActionIntentionCandidate:
    try:
        return active_character_intent_service().get_candidate(candidate_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _character_intent_error(exc) from exc


@router.get(
    "/candidates/{candidate_id}/risk-report",
    response_model=CharacterIntentRiskReport,
)
def get_character_intent_candidate_risk_report(
    candidate_id: str,
) -> CharacterIntentRiskReport:
    try:
        return active_character_intent_service().get_risk_report_for_candidate(
            candidate_id
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _character_intent_error(exc) from exc


@router.get("/policy", response_model=CharacterIntentPolicyResponse)
def get_character_intent_policy() -> CharacterIntentPolicyResponse:
    try:
        policy = active_character_intent_service().get_policy()
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        raise _character_intent_error(exc) from exc
    return CharacterIntentPolicyResponse(policy=policy)


def _character_intent_error(exc: Exception) -> HTTPException:
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
        code if code.startswith("CHARACTER_INTENT_") else "CHARACTER_INTENT_INTERNAL_ERROR"
    )
    status_code = 500
    if "NOT_FOUND" in error_code:
        status_code = 404
    elif "REQUIRED" in error_code or "INVALID" in error_code or "BLOCKED" in error_code:
        status_code = 400
    if status_code == 500:
        message = "Character intent operation failed."
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": message,
        },
    )
