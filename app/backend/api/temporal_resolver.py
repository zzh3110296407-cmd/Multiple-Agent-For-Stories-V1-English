from fastapi import APIRouter, HTTPException, Query

from app.backend.models.temporal_resolver import (
    CharacterVisibleMemoryResponse,
    LocationStateAtTimeResponse,
    LocationStateVersionedInsertRequest,
    LocationStateVersionedInsertResponse,
    ReaderDisclosureStatusResponse,
    TimelineNodeVersionStatusResponse,
)
from app.backend.services.location_state_versioning_service import LocationStateVersioningService
from app.backend.services.temporal_resolver_service import TemporalResolverService
from app.backend.storage.json_store import StorageError


router = APIRouter()
temporal_resolver_service = TemporalResolverService()
location_state_versioning_service = LocationStateVersioningService()


@router.get(
    "/characters/{character_id}/visible-memory",
    response_model=CharacterVisibleMemoryResponse,
)
def get_character_visible_memory(
    character_id: str,
    timeline_id: str,
    world_time_sort_key: int = Query(..., ge=0),
    knowledge_time_sort_key: int = Query(..., ge=0),
    narrative_sequence_key: int = Query(..., ge=0),
    project_id: str = "",
    limit: int = Query(20, ge=1, le=100),
) -> CharacterVisibleMemoryResponse:
    try:
        return temporal_resolver_service.get_character_visible_memory(
            project_id=project_id,
            character_id=character_id,
            timeline_id=timeline_id,
            world_time_sort_key=world_time_sort_key,
            knowledge_time_sort_key=knowledge_time_sort_key,
            narrative_sequence_key=narrative_sequence_key,
            limit=limit,
        )
    except StorageError as exc:
        raise _temporal_resolver_error(exc) from exc


@router.get(
    "/locations/{location_id}/state",
    response_model=LocationStateAtTimeResponse,
)
def get_location_state_at_time(
    location_id: str,
    timeline_id: str,
    world_time_sort_key: int = Query(..., ge=0),
    project_id: str = "",
) -> LocationStateAtTimeResponse:
    try:
        return temporal_resolver_service.get_location_state_at_time(
            project_id=project_id,
            location_id=location_id,
            timeline_id=timeline_id,
            world_time_sort_key=world_time_sort_key,
        )
    except StorageError as exc:
        raise _temporal_resolver_error(exc) from exc


@router.post(
    "/locations/{location_id}/state/versioned-insert",
    response_model=LocationStateVersionedInsertResponse,
)
def insert_location_state_version(
    location_id: str,
    request: LocationStateVersionedInsertRequest,
    project_id: str = "",
) -> LocationStateVersionedInsertResponse:
    try:
        return location_state_versioning_service.insert_location_state_version(
            project_id=project_id,
            location_id=location_id,
            request=request,
        )
    except StorageError as exc:
        raise _temporal_resolver_error(exc) from exc


@router.get(
    "/reader-disclosure",
    response_model=ReaderDisclosureStatusResponse,
)
def get_reader_disclosure_status(
    entity_type: str,
    entity_id: str,
    narrative_sequence_key: int = Query(..., ge=0),
    project_id: str = "",
) -> ReaderDisclosureStatusResponse:
    try:
        return temporal_resolver_service.get_reader_disclosure_status(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            narrative_sequence_key=narrative_sequence_key,
        )
    except StorageError as exc:
        raise _temporal_resolver_error(exc) from exc


@router.get(
    "/nodes/{node_type}/{node_id}/version-status",
    response_model=TimelineNodeVersionStatusResponse,
)
def get_timeline_node_version_status(
    node_type: str,
    node_id: str,
    project_id: str = "",
) -> TimelineNodeVersionStatusResponse:
    try:
        return temporal_resolver_service.get_timeline_node_version_status(
            project_id=project_id,
            node_type=node_type,
            node_id=node_id,
        )
    except StorageError as exc:
        raise _temporal_resolver_error(exc) from exc


def _temporal_resolver_error(exc: StorageError) -> HTTPException:
    message = str(exc)
    code = message.split(":", 1)[0]
    status_code = 409 if code in {
        "TEMPORAL_RESOLVER_POSTGRES_PRIMARY_REQUIRED",
        "LOCATION_STATE_VERSION_INSERT_POSTGRES_PRIMARY_REQUIRED",
        "LOCATION_STATE_VERSION_INSERT_TIME_CONFLICT",
    } else 400
    if not code.startswith(("TEMPORAL_RESOLVER", "LOCATION_STATE_VERSION_INSERT")):
        code = "TEMPORAL_RESOLVER_INTERNAL_ERROR"
        message = "Temporal operation failed."
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": code,
            "message": message,
        },
    )
