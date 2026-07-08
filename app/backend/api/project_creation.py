from fastapi import APIRouter, HTTPException

from app.backend.models.project_creation import (
    ActiveProjectSelection,
    ActiveProjectSelectionResponse,
    ConfirmProjectCreationDraftRequest,
    CreateProjectCreationRequest,
    DemoSeedProfilesResponse,
    ProjectCreationDecision,
    ProjectCreationDraft,
    ProjectCreationCurrentState,
    ProjectCreationModesResponse,
    ProjectCreationRequest,
    ProjectCreationValidationReport,
    ProjectOpenSummary,
    ProjectOriginMetadata,
    ProjectRegistryResponse,
    SetActiveProjectSelectionRequest,
)
from app.backend.services.project_creation_service import (
    ProjectCreationBlocked,
    ProjectCreationError,
    ProjectCreationNotFound,
    ProjectCreationSafetyError,
    ProjectCreationService,
)
from app.backend.storage.json_store import StorageError


project_creation_router = APIRouter()
projects_router = APIRouter()
project_creation_service = ProjectCreationService()


def _raise_project_creation_error(exc: Exception) -> None:
    if isinstance(exc, ProjectCreationNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ProjectCreationSafetyError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ProjectCreationBlocked):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ProjectCreationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, StorageError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


@project_creation_router.get("/modes", response_model=ProjectCreationModesResponse)
def get_project_creation_modes() -> ProjectCreationModesResponse:
    return project_creation_service.list_modes()


@project_creation_router.get("/demo-seeds", response_model=DemoSeedProfilesResponse)
def get_demo_seed_profiles() -> DemoSeedProfilesResponse:
    try:
        return project_creation_service.list_demo_seed_profiles()
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@project_creation_router.get("/current", response_model=ProjectCreationCurrentState)
def get_current_project_creation_state(
    creation_request_id: str | None = None,
    creation_draft_id: str | None = None,
    project_id: str | None = None,
) -> ProjectCreationCurrentState:
    try:
        return project_creation_service.get_current_state(
            creation_request_id=creation_request_id,
            creation_draft_id=creation_draft_id,
            project_id=project_id,
        )
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@project_creation_router.post("/requests", response_model=ProjectCreationRequest)
def create_project_creation_request(
    request: CreateProjectCreationRequest,
) -> ProjectCreationRequest:
    try:
        return project_creation_service.create_request(request)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@project_creation_router.get(
    "/requests/{creation_request_id}",
    response_model=ProjectCreationRequest,
)
def get_project_creation_request(creation_request_id: str) -> ProjectCreationRequest:
    try:
        return project_creation_service.get_request(creation_request_id)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@project_creation_router.post(
    "/requests/{creation_request_id}/validate",
    response_model=ProjectCreationValidationReport,
)
def validate_project_creation_request(
    creation_request_id: str,
) -> ProjectCreationValidationReport:
    try:
        return project_creation_service.validate_request(creation_request_id)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@project_creation_router.post(
    "/requests/{creation_request_id}/draft",
    response_model=ProjectCreationDraft,
)
async def create_project_creation_draft(creation_request_id: str) -> ProjectCreationDraft:
    try:
        return ProjectCreationService().create_draft(creation_request_id)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@project_creation_router.get(
    "/drafts/{creation_draft_id}",
    response_model=ProjectCreationDraft,
)
def get_project_creation_draft(creation_draft_id: str) -> ProjectCreationDraft:
    try:
        return project_creation_service.get_draft(creation_draft_id)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@project_creation_router.post(
    "/drafts/{creation_draft_id}/confirm",
    response_model=ProjectCreationDecision,
)
def confirm_project_creation_draft(
    creation_draft_id: str,
    request: ConfirmProjectCreationDraftRequest,
) -> ProjectCreationDecision:
    try:
        return project_creation_service.confirm_draft(creation_draft_id, request)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@project_creation_router.post(
    "/drafts/{creation_draft_id}/cancel",
    response_model=ProjectCreationDraft,
)
def cancel_project_creation_draft(creation_draft_id: str) -> ProjectCreationDraft:
    try:
        return project_creation_service.cancel_draft(creation_draft_id)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@projects_router.get("", response_model=ProjectRegistryResponse)
def list_projects() -> ProjectRegistryResponse:
    try:
        return project_creation_service.list_projects()
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@projects_router.get("/active-selection", response_model=ActiveProjectSelectionResponse)
def get_active_project_selection() -> ActiveProjectSelectionResponse:
    try:
        return project_creation_service.get_active_project_selection()
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@projects_router.post("/active-selection", response_model=ActiveProjectSelection)
def set_active_project_selection(
    request: SetActiveProjectSelectionRequest,
) -> ActiveProjectSelection:
    try:
        return project_creation_service.set_active_project_selection(request)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@projects_router.get("/{project_id}", response_model=ProjectOpenSummary)
def get_project_summary(project_id: str) -> ProjectOpenSummary:
    try:
        return project_creation_service.get_project(project_id)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@projects_router.get("/{project_id}/origin", response_model=ProjectOriginMetadata)
def get_project_origin(project_id: str) -> ProjectOriginMetadata:
    try:
        return project_creation_service.get_project_origin(project_id)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")


@projects_router.post("/{project_id}/open", response_model=ProjectOpenSummary)
def open_project(project_id: str) -> ProjectOpenSummary:
    try:
        return project_creation_service.open_project(project_id)
    except (ProjectCreationError, StorageError) as exc:
        _raise_project_creation_error(exc)
        raise AssertionError("unreachable")
