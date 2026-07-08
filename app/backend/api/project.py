from fastapi import APIRouter, HTTPException

from app.backend.models.project_data import ProjectDataBundle, SeedDataResponse
from app.backend.models.project import ProjectStatusResponse
from app.backend.services.project_data_service import ProjectDataService
from app.backend.services.project_service import ProjectService
from app.backend.storage.json_store import StorageError

router = APIRouter()
project_service = ProjectService()
project_data_service = ProjectDataService(respect_active_project_selection=True)


@router.get("/status", response_model=ProjectStatusResponse)
def get_project_status() -> ProjectStatusResponse:
    try:
        return project_service.get_status()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/init", response_model=ProjectStatusResponse)
def init_project() -> ProjectStatusResponse:
    try:
        return project_service.initialize_project()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/seed", response_model=SeedDataResponse)
def seed_project_data() -> SeedDataResponse:
    try:
        return project_data_service.seed_data()
    except StorageError as exc:
        if str(exc).startswith("DEBUG_SEED_REQUIRES_LOCAL_DEBUG_PROJECT"):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/data", response_model=ProjectDataBundle)
def get_project_data() -> ProjectDataBundle:
    try:
        return project_data_service.get_project_data()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
