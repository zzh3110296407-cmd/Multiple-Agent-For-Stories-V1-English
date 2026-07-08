from fastapi import APIRouter, HTTPException, Query

from app.backend.models.memory_record import (
    MemoryQuery,
    MemoryQueryResponse,
    MemoryRecord,
    MemoryRecordsResponse,
    MemoryReindexRequest,
    MemoryReindexResponse,
)
from app.backend.services.memory_migration_service import MemoryMigrationService
from app.backend.services.memory_query_service import MemoryQueryService
from app.backend.storage.json_store import StorageError


router = APIRouter()
memory_query_service = MemoryQueryService()
memory_migration_service = MemoryMigrationService(
    store=memory_query_service.store,
    data_dir=memory_query_service.data_dir,
)


def model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


@router.get("/records", response_model=MemoryRecordsResponse)
def list_memory_records(
    status: str | None = None,
    limit: int = Query(100, ge=1, le=200),
) -> MemoryRecordsResponse:
    try:
        return memory_query_service.list_records(status=status, limit=limit)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/records/{memory_id}", response_model=MemoryRecord)
def get_memory_record(memory_id: str) -> MemoryRecord:
    try:
        record = memory_query_service.get_record(memory_id)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Memory record was not found.")
    return record


@router.post("/query", response_model=MemoryQueryResponse)
def query_memory(request: MemoryQuery) -> MemoryQueryResponse:
    try:
        return memory_query_service.query(request)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/reindex", response_model=MemoryReindexResponse)
def reindex_memory(request: MemoryReindexRequest) -> MemoryReindexResponse:
    try:
        report = memory_migration_service.reindex(dry_run=request.dry_run)
        return MemoryReindexResponse(**model_to_dict(report))
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
