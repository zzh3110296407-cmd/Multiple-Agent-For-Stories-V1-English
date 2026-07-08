from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "multiple-agent-for-stories-backend",
        "phase": "phase_8_5",
    }
