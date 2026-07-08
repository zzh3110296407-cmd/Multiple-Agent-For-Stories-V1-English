from fastapi import APIRouter, HTTPException

from app.backend.models.framework_composition import (
    FrameworkCompositionDraft,
    FrameworkCompositionDraftCreateRequest,
    FrameworkCompositionDraftListResponse,
)
from app.backend.services.framework_composition_service import (
    FrameworkCompositionService,
)
from app.backend.services.generator_framework_context_service import (
    GeneratorFrameworkContextService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
framework_composition_service = FrameworkCompositionService()
generator_framework_context_service = GeneratorFrameworkContextService()


def storage_error_response(exc: StorageError) -> HTTPException:
    message = str(exc)
    if message.startswith("FRAMEWORK_COMPOSITION_DRAFT_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("GENERATOR_FRAMEWORK_CONTEXT_COMPOSITION_NOT_CONFIRMED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("GENERATOR_FRAMEWORK_CONTEXT_UNSUPPORTED_COMPOSITION_SCHEMA"):
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=500, detail=message)


@router.post("/drafts", response_model=FrameworkCompositionDraft)
def create_framework_composition_draft(
    request: FrameworkCompositionDraftCreateRequest,
) -> FrameworkCompositionDraft:
    try:
        return framework_composition_service.create_draft(request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/drafts", response_model=FrameworkCompositionDraftListResponse)
def list_framework_composition_drafts() -> FrameworkCompositionDraftListResponse:
    try:
        return framework_composition_service.list_drafts()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/drafts/{composition_id}", response_model=FrameworkCompositionDraft)
def get_framework_composition_draft(composition_id: str) -> FrameworkCompositionDraft:
    try:
        return framework_composition_service.get_draft(composition_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/drafts/{composition_id}/generator-context")
def get_framework_composition_generator_context(composition_id: str) -> dict:
    try:
        return generator_framework_context_service.build_context(composition_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post("/drafts/{composition_id}/validate", response_model=FrameworkCompositionDraft)
def validate_framework_composition_draft(
    composition_id: str,
) -> FrameworkCompositionDraft:
    try:
        return framework_composition_service.validate_draft(composition_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post("/drafts/{composition_id}/confirm", response_model=FrameworkCompositionDraft)
def confirm_framework_composition_draft(
    composition_id: str,
) -> FrameworkCompositionDraft:
    try:
        return framework_composition_service.confirm_draft(composition_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc
