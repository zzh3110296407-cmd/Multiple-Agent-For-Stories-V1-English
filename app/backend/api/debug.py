from fastapi import APIRouter, HTTPException

from app.backend.models.phase2_debug import Phase2DebugResponse
from app.backend.services.phase2_debug_service import Phase2DebugService
from app.backend.storage.json_store import StorageError


router = APIRouter()
debug_service = Phase2DebugService()


@router.get("/phase2", response_model=Phase2DebugResponse)
def get_phase2_debug() -> Phase2DebugResponse:
    try:
        return debug_service.get_phase2_debug()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
