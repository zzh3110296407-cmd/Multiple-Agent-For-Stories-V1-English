from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.product_artifacts import (
    FinalStoryPackageProductView,
    FinalStoryPackageProductViewListResponse,
    PluginOutputProductView,
    PluginOutputProductViewListResponse,
    ProductArtifactAuthorityBadge,
    ProductArtifactEntry,
    ProductArtifactEntryListResponse,
    ProductArtifactLibraryState,
    ProductArtifactSafePreview,
    ProductArtifactSafetySummary,
)
from app.backend.services.product_artifact_library_service import (
    ProductArtifactLibraryService,
    ProductArtifactNotFound,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
product_artifact_library_service: ProductArtifactLibraryService | None = None


def _artifact_service() -> ProductArtifactLibraryService:
    return product_artifact_library_service or ProductArtifactLibraryService()


def _raise_product_artifact_error(exc: Exception) -> None:
    if isinstance(exc, ProductArtifactNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, StorageError):
        message = str(exc)
        if "ACTIVE_PROJECT_STORY_DATA_NOT_FOUND" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        if "INVALID" in message:
            raise HTTPException(status_code=422, detail=message) from exc
        raise HTTPException(status_code=500, detail=message) from exc
    raise exc


@router.get("/library", response_model=ProductArtifactLibraryState)
def get_product_artifact_library(
    project_id: Optional[str] = Query(default=None),
) -> ProductArtifactLibraryState:
    try:
        return _artifact_service().library(project_id=project_id)
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/entries", response_model=ProductArtifactEntryListResponse)
def list_product_artifact_entries(
    project_id: Optional[str] = Query(default=None),
) -> ProductArtifactEntryListResponse:
    try:
        return _artifact_service().entries(project_id=project_id)
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/entries/{artifact_entry_id}", response_model=ProductArtifactEntry)
def get_product_artifact_entry(
    artifact_entry_id: str,
    project_id: Optional[str] = Query(default=None),
) -> ProductArtifactEntry:
    try:
        return _artifact_service().get_entry(artifact_entry_id, project_id=project_id)
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/entries/{artifact_entry_id}/authority-badge", response_model=ProductArtifactAuthorityBadge)
def get_product_artifact_authority_badge(
    artifact_entry_id: str,
    project_id: Optional[str] = Query(default=None),
) -> ProductArtifactAuthorityBadge:
    try:
        return _artifact_service().get_authority_badge(
            artifact_entry_id,
            project_id=project_id,
        )
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/entries/{artifact_entry_id}/safe-preview", response_model=ProductArtifactSafePreview)
def get_product_artifact_safe_preview(
    artifact_entry_id: str,
    project_id: Optional[str] = Query(default=None),
) -> ProductArtifactSafePreview:
    try:
        return _artifact_service().get_safe_preview(
            artifact_entry_id,
            project_id=project_id,
        )
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/entries/{artifact_entry_id}/safety-summary", response_model=ProductArtifactSafetySummary)
def get_product_artifact_safety_summary(
    artifact_entry_id: str,
    project_id: Optional[str] = Query(default=None),
) -> ProductArtifactSafetySummary:
    try:
        return _artifact_service().get_safety_summary(
            artifact_entry_id,
            project_id=project_id,
        )
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/final-story-packages", response_model=FinalStoryPackageProductViewListResponse)
def list_final_story_package_product_views(
    project_id: Optional[str] = Query(default=None),
) -> FinalStoryPackageProductViewListResponse:
    try:
        return _artifact_service().final_story_package_views(project_id=project_id)
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/final-story-packages/{view_id}", response_model=FinalStoryPackageProductView)
def get_final_story_package_product_view(
    view_id: str,
    project_id: Optional[str] = Query(default=None),
) -> FinalStoryPackageProductView:
    try:
        return _artifact_service().get_final_story_package_view(view_id, project_id=project_id)
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/plugin-outputs", response_model=PluginOutputProductViewListResponse)
def list_plugin_output_product_views(
    project_id: Optional[str] = Query(default=None),
) -> PluginOutputProductViewListResponse:
    try:
        return _artifact_service().plugin_output_views(project_id=project_id)
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")


@router.get("/plugin-outputs/{view_id}", response_model=PluginOutputProductView)
def get_plugin_output_product_view(
    view_id: str,
    project_id: Optional[str] = Query(default=None),
) -> PluginOutputProductView:
    try:
        return _artifact_service().get_plugin_output_view(view_id, project_id=project_id)
    except StorageError as exc:
        _raise_product_artifact_error(exc)
        raise AssertionError("unreachable")
