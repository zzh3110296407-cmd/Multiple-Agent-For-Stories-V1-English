from fastapi import APIRouter, HTTPException

from app.backend.models.project_story_premise import ProjectStoryPremiseResponse
from app.backend.services.project_story_premise_service import (
    ProjectStoryPremiseBlocked,
    ProjectStoryPremiseError,
    ProjectStoryPremiseSafetyError,
    ProjectStoryPremiseService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
project_story_premise_service = ProjectStoryPremiseService()


@router.get("/current", response_model=ProjectStoryPremiseResponse)
def get_current_project_story_premise() -> ProjectStoryPremiseResponse:
    try:
        return project_story_premise_service.get_current_response()
    except ProjectStoryPremiseSafetyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectStoryPremiseBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectStoryPremiseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
