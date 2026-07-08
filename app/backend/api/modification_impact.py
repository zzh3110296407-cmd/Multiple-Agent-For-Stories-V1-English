from fastapi import APIRouter, HTTPException

from app.backend.models.modification_impact import (
    ModificationImpactChooseRequest,
    ModificationImpactPreviewListResponse,
    ModificationImpactPreviewRequest,
    ModificationImpactPreviewResponse,
)
from app.backend.services.modification_impact_service import ModificationImpactService
from app.backend.storage.json_store import StorageError


router = APIRouter()
modification_impact_service = ModificationImpactService()


def modification_impact_error_response(exc: Exception) -> HTTPException:
    message = str(exc)
    if message.startswith("MODIFICATION_IMPACT_SOURCE_MISSING") or message.startswith(
        "MODIFICATION_IMPACT_PREVIEW_MISSING"
    ):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": message.split(":", 1)[0],
                "message": message.split(":", 1)[-1].strip(),
            },
        )
    if message.startswith("MODIFICATION_IMPACT_SOURCE_INVALID") or message.startswith(
        "MODIFICATION_IMPACT_OPTION_MISSING"
    ):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": message.split(":", 1)[0],
                "message": message.split(":", 1)[-1].strip(),
            },
        )
    if message.startswith("MODIFICATION_IMPACT_OPTION_DISABLED") or message.startswith(
        "M6_"
    ):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": message.split(":", 1)[0],
                "message": message.split(":", 1)[-1].strip(),
            },
        )
    if message.startswith("MODIFICATION_IMPACT_UNSAFE_PAYLOAD_BLOCKED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "MODIFICATION_IMPACT_UNSAFE_PAYLOAD_BLOCKED",
                "message": "Modification impact preview payload failed the safety scan.",
            },
        )
    if "schema is invalid" in message:
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


@router.post("/preview", response_model=ModificationImpactPreviewResponse)
def create_modification_impact_preview(
    request: ModificationImpactPreviewRequest,
) -> ModificationImpactPreviewResponse:
    try:
        return ModificationImpactPreviewResponse(
            preview=modification_impact_service.create_preview(request)
        )
    except StorageError as exc:
        raise modification_impact_error_response(exc) from exc


@router.get("/previews", response_model=ModificationImpactPreviewListResponse)
def list_modification_impact_previews(
    source_object_type: str | None = None,
    source_object_id: str | None = None,
    status: str | None = None,
) -> ModificationImpactPreviewListResponse:
    try:
        previews = modification_impact_service.list_previews(
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            status=status,
        )
        return ModificationImpactPreviewListResponse(
            previews=previews,
            count=len(previews),
        )
    except StorageError as exc:
        raise modification_impact_error_response(exc) from exc


@router.get("/previews/{preview_id}", response_model=ModificationImpactPreviewResponse)
def get_modification_impact_preview(preview_id: str) -> ModificationImpactPreviewResponse:
    try:
        return ModificationImpactPreviewResponse(
            preview=modification_impact_service.get_preview(preview_id)
        )
    except StorageError as exc:
        raise modification_impact_error_response(exc) from exc


@router.post("/previews/{preview_id}/choose", response_model=ModificationImpactPreviewResponse)
def choose_modification_impact_preview(
    preview_id: str,
    request: ModificationImpactChooseRequest,
) -> ModificationImpactPreviewResponse:
    try:
        preview, decision, candidate, memory_plan = modification_impact_service.choose_preview(
            preview_id,
            request,
        )
        return ModificationImpactPreviewResponse(
            preview=preview,
            decision=decision,
            candidate=candidate,
            memory_plan=memory_plan,
        )
    except StorageError as exc:
        raise modification_impact_error_response(exc) from exc

