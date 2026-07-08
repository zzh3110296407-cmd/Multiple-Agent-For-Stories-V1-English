from fastapi import APIRouter

from app.backend.models.tracing import TracingStatus
from app.backend.services.tracing_service import TracingService


router = APIRouter()
tracing_service = TracingService()


@router.get("/status", response_model=TracingStatus)
def get_tracing_status() -> TracingStatus:
    return tracing_service.get_status()
