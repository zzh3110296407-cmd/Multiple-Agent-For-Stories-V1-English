from fastapi import APIRouter, HTTPException

from app.backend.models.app_progress import AppProgressResponse
from app.backend.services.app_progress_service import AppProgressService
from app.backend.storage.json_store import StorageError


router = APIRouter()
app_progress_service = AppProgressService()


@router.get("/progress", response_model=AppProgressResponse)
def get_app_progress() -> AppProgressResponse:
    try:
        return app_progress_service.get_progress()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
