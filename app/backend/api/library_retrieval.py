from fastapi import APIRouter, HTTPException

from app.backend.models.library_retrieval import (
    LibraryPack,
    LibraryPackBuildRequest,
    LibraryPackStaleRequest,
    LibraryPackStaleResponse,
    LibraryRelationshipExpansionRequest,
    LibraryRetrievalGapRecord,
    LibraryRetrievalGapRequest,
    LibraryRetrievalSearchRequest,
    LibraryRetrievalSearchResponse,
    LibraryRetrievalTaskSpec,
    LibraryRetrievalTaskSpecPayload,
    LibraryRetrievalUsageLogRequest,
    LibraryRetrievalUsageRecord,
    LibrarySemanticRetrievalBoundary,
    LibraryTextRetrievalRequest,
)
from app.backend.services.library_retrieval_service import LibraryRetrievalService
from app.backend.storage.json_store import StorageError


router = APIRouter()
library_retrieval_service = LibraryRetrievalService()


@router.post(
    "/cards/search",
    response_model=LibraryRetrievalSearchResponse,
)
def search_library_cards(request: LibraryRetrievalSearchRequest) -> LibraryRetrievalSearchResponse:
    try:
        return library_retrieval_service.search_library_cards(request)
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.post(
    "/text/search",
    response_model=LibraryRetrievalSearchResponse,
)
def search_library_text(request: LibraryTextRetrievalRequest) -> LibraryRetrievalSearchResponse:
    try:
        return library_retrieval_service.search_library_text(request)
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.post(
    "/relationships/search",
    response_model=LibraryRetrievalSearchResponse,
)
def search_library_relationships(request: LibraryRelationshipExpansionRequest) -> LibraryRetrievalSearchResponse:
    try:
        return library_retrieval_service.search_library_relationships(request)
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.post(
    "/packs",
    response_model=LibraryPack,
)
def create_or_refresh_pack(request: LibraryPackBuildRequest) -> LibraryPack:
    try:
        return library_retrieval_service.create_or_refresh_pack(request)
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.get(
    "/packs/{pack_type}/{pack_id}",
    response_model=LibraryPack,
)
def get_pack(
    pack_type: str,
    pack_id: str,
    project_id: str = "",
) -> LibraryPack:
    try:
        return library_retrieval_service.get_pack(
            project_id=project_id,
            pack_type=pack_type,
            pack_id=pack_id,
        )
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.post(
    "/packs/stale",
    response_model=LibraryPackStaleResponse,
)
def mark_packs_stale(request: LibraryPackStaleRequest) -> LibraryPackStaleResponse:
    try:
        return library_retrieval_service.mark_packs_stale(request)
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.post(
    "/usage",
    response_model=LibraryRetrievalUsageRecord,
)
def record_retrieval_usage(request: LibraryRetrievalUsageLogRequest) -> LibraryRetrievalUsageRecord:
    try:
        return library_retrieval_service.record_retrieval_usage(request)
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.post(
    "/gaps",
    response_model=LibraryRetrievalGapRecord,
)
def record_retrieval_gap(request: LibraryRetrievalGapRequest) -> LibraryRetrievalGapRecord:
    try:
        return library_retrieval_service.record_retrieval_gap(request)
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.get(
    "/semantic/boundary",
    response_model=LibrarySemanticRetrievalBoundary,
)
def get_semantic_retrieval_boundary() -> LibrarySemanticRetrievalBoundary:
    return library_retrieval_service.get_semantic_retrieval_boundary()


@router.get(
    "/task-specs/{retrieval_task_id}",
    response_model=LibraryRetrievalTaskSpec,
)
def get_retrieval_task_spec(
    retrieval_task_id: str,
    project_id: str = "",
) -> LibraryRetrievalTaskSpec:
    try:
        return library_retrieval_service.get_retrieval_task_spec(
            project_id=project_id,
            retrieval_task_id=retrieval_task_id,
        )
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


@router.post(
    "/task-specs",
    response_model=LibraryRetrievalTaskSpec,
)
def create_retrieval_task_spec(
    payload: LibraryRetrievalTaskSpecPayload,
    project_id: str = "",
) -> LibraryRetrievalTaskSpec:
    try:
        return library_retrieval_service.create_retrieval_task_spec(
            project_id=project_id,
            payload=payload,
        )
    except StorageError as exc:
        raise _library_retrieval_error(exc) from exc


def _library_retrieval_error(exc: StorageError) -> HTTPException:
    message = str(exc)
    code = message.split(":", 1)[0]
    status_code = 409 if code == "LIBRARY_RETRIEVAL_POSTGRES_PRIMARY_REQUIRED" else 400
    if code == "LIBRARY_RETRIEVAL_TASK_SPEC_NOT_FOUND" or code == "LIBRARY_RETRIEVAL_PROJECT_NOT_FOUND":
        status_code = 404
    if not code.startswith("LIBRARY_RETRIEVAL"):
        code = "LIBRARY_RETRIEVAL_INTERNAL_ERROR"
        message = "Library retrieval operation failed."
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": code,
            "message": message,
        },
    )
