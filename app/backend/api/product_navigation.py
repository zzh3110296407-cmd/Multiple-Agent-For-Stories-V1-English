from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.product_navigation import (
    PatchUserWorkspacePreferenceRequest,
    ProductNavigationGroupsResponse,
    ProductNavigationState,
    ProductWorkspaceDefinitionsResponse,
    UserWorkspacePreference,
    WorkspaceAvailabilityItem,
    WorkspaceAvailabilityReport,
)
from app.backend.services.product_navigation_service import (
    ProductNavigationError,
    ProductNavigationNotFound,
    ProductNavigationSafetyError,
    ProductNavigationService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
product_navigation_service = ProductNavigationService()


def _raise_product_navigation_error(exc: Exception) -> None:
    if isinstance(exc, ProductNavigationNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ProductNavigationSafetyError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ProductNavigationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, StorageError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


@router.get("/workspaces", response_model=ProductWorkspaceDefinitionsResponse)
def get_product_workspaces() -> ProductWorkspaceDefinitionsResponse:
    try:
        return product_navigation_service.workspaces()
    except (ProductNavigationError, StorageError) as exc:
        _raise_product_navigation_error(exc)
        raise AssertionError("unreachable")


@router.get("/groups", response_model=ProductNavigationGroupsResponse)
def get_product_navigation_groups() -> ProductNavigationGroupsResponse:
    try:
        return product_navigation_service.groups()
    except (ProductNavigationError, StorageError) as exc:
        _raise_product_navigation_error(exc)
        raise AssertionError("unreachable")


@router.get("/state", response_model=ProductNavigationState)
def get_product_navigation_state(
    project_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductNavigationState:
    try:
        return product_navigation_service.state(
            project_id=project_id,
            workspace_id=workspace_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductNavigationError, StorageError) as exc:
        _raise_product_navigation_error(exc)
        raise AssertionError("unreachable")


@router.get("/availability", response_model=WorkspaceAvailabilityReport)
def get_product_navigation_availability(
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> WorkspaceAvailabilityReport:
    try:
        return product_navigation_service.availability(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductNavigationError, StorageError) as exc:
        _raise_product_navigation_error(exc)
        raise AssertionError("unreachable")


@router.get("/workspaces/{workspace_id}/access", response_model=WorkspaceAvailabilityItem)
def get_product_workspace_access(
    workspace_id: str,
    project_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> WorkspaceAvailabilityItem:
    try:
        return product_navigation_service.access(
            workspace_id=workspace_id,
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductNavigationError, StorageError) as exc:
        _raise_product_navigation_error(exc)
        raise AssertionError("unreachable")


@router.get("/preferences", response_model=UserWorkspacePreference)
def get_product_navigation_preferences() -> UserWorkspacePreference:
    try:
        return product_navigation_service.preferences()
    except (ProductNavigationError, StorageError) as exc:
        _raise_product_navigation_error(exc)
        raise AssertionError("unreachable")


@router.patch("/preferences", response_model=UserWorkspacePreference)
def patch_product_navigation_preferences(
    request: PatchUserWorkspacePreferenceRequest,
) -> UserWorkspacePreference:
    try:
        return product_navigation_service.patch_preferences(request)
    except (ProductNavigationError, StorageError) as exc:
        _raise_product_navigation_error(exc)
        raise AssertionError("unreachable")


@router.get("/projects/{project_id}/state", response_model=ProductNavigationState)
def get_project_product_navigation_state(
    project_id: str,
    workspace_id: Optional[str] = Query(default=None),
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductNavigationState:
    try:
        return product_navigation_service.state(
            project_id=project_id,
            workspace_id=workspace_id,
            mode_profile_id=mode_profile_id,
        )
    except (ProductNavigationError, StorageError) as exc:
        _raise_product_navigation_error(exc)
        raise AssertionError("unreachable")
