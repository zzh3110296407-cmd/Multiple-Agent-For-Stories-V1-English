from fastapi import APIRouter, HTTPException, Query

from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.models.scene_participants import (
    SceneParticipantSelectionReport,
    SceneParticipantSelectionRequest,
    SceneParticipantSelectionResponse,
    SceneRoleCandidate,
    SceneRoleFunctionNeedRef,
)
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.scene_participant_selection_service import (
    SceneParticipantSelectionService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
scene_participant_selection_service = SceneParticipantSelectionService()


def active_scene_participant_selection_service() -> SceneParticipantSelectionService:
    return scoped_story_service(
        scene_participant_selection_service,
        SceneParticipantSelectionService,
    )


def _raise_scene_participant_error(exc: Exception) -> None:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        ) from exc
    message = str(exc)
    code, _, detail = message.partition(":")
    error_code = code if code.startswith("SCENE_PARTICIPANT_") else "SCENE_PARTICIPANT_INTERNAL_ERROR"
    status_code = 500
    if "NOT_FOUND" in error_code:
        status_code = 404
    elif (
        "REQUIRED" in error_code
        or "INVALID" in error_code
        or "EXCEEDED" in error_code
        or "FORBIDDEN" in error_code
    ):
        status_code = 400
    elif "REJECTED" in error_code or "ALREADY" in error_code or "CONFLICT" in error_code:
        status_code = 409
    if status_code == 500:
        error_code = "SCENE_PARTICIPANT_INTERNAL_ERROR"
        detail = "Scene participant selection failed."
    raise HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": detail.strip() or "Scene participant selection failed.",
        },
    ) from exc


@router.post("/selections", response_model=SceneParticipantSelectionResponse)
def create_scene_participant_selection(
    request: SceneParticipantSelectionRequest,
) -> SceneParticipantSelectionResponse:
    try:
        return active_scene_participant_selection_service().create_selection(request)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)


@router.get("/selections/current", response_model=SceneParticipantSelectionResponse)
def get_current_scene_participant_selection(
    chapter_id: str = Query(...),
    scene_index: int = Query(..., ge=1),
) -> SceneParticipantSelectionResponse:
    try:
        return active_scene_participant_selection_service().get_current_selection(
            chapter_id=chapter_id,
            scene_index=scene_index,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)


@router.get("/selections/{selection_id}", response_model=SceneParticipantSelectionResponse)
def get_scene_participant_selection(
    selection_id: str,
) -> SceneParticipantSelectionResponse:
    try:
        return active_scene_participant_selection_service().get_selection(selection_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)


@router.post("/selections/{selection_id}/refresh", response_model=SceneParticipantSelectionResponse)
def refresh_scene_participant_selection(
    selection_id: str,
) -> SceneParticipantSelectionResponse:
    try:
        return active_scene_participant_selection_service().refresh_selection(selection_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)


@router.post(
    "/creation-candidates/{candidate_id}/confirm",
    response_model=SceneParticipantSelectionResponse,
)
def confirm_scene_participant_creation_candidate(
    candidate_id: str,
) -> SceneParticipantSelectionResponse:
    try:
        return active_scene_participant_selection_service().confirm_creation_candidate(
            candidate_id
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)


@router.post(
    "/creation-candidates/{candidate_id}/reject",
    response_model=SceneParticipantSelectionResponse,
)
def reject_scene_participant_creation_candidate(
    candidate_id: str,
) -> SceneParticipantSelectionResponse:
    try:
        return active_scene_participant_selection_service().reject_creation_candidate(
            candidate_id
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)


@router.get("/role-needs", response_model=list[SceneRoleFunctionNeedRef])
def get_scene_role_needs(
    chapter_id: str = Query(...),
    scene_index: int = Query(..., ge=1),
    scene_goal: str = Query(default=""),
    scene_location: str = Query(default=""),
    previous_scene_result: str = Query(default=""),
) -> list[SceneRoleFunctionNeedRef]:
    try:
        return active_scene_participant_selection_service().list_role_needs(
            chapter_id=chapter_id,
            scene_index=scene_index,
            scene_goal=scene_goal,
            scene_location=scene_location,
            previous_scene_result=previous_scene_result,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)


@router.get("/candidates", response_model=list[SceneRoleCandidate])
def get_scene_role_candidates(
    chapter_id: str = Query(...),
    scene_index: int = Query(..., ge=1),
) -> list[SceneRoleCandidate]:
    try:
        return active_scene_participant_selection_service().list_candidates(
            chapter_id=chapter_id,
            scene_index=scene_index,
        )
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)


@router.get("/reports/{report_id}", response_model=SceneParticipantSelectionReport)
def get_scene_participant_selection_report(
    report_id: str,
) -> SceneParticipantSelectionReport:
    try:
        return active_scene_participant_selection_service().get_report(report_id)
    except (StorageError, ActiveProjectStoryDataBlocked) as exc:
        _raise_scene_participant_error(exc)
