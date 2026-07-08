from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.product_progress import (
    PatchProductModeProfileRequest,
    ProductModeProfile,
)
from app.backend.services.product_progress_service import (
    ProductProgressError,
    ProductProgressSafetyError,
    ProductProgressService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
product_progress_service = ProductProgressService()


def _raise_product_mode_error(exc: Exception) -> None:
    if isinstance(exc, ProductProgressSafetyError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ProductProgressError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, StorageError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


@router.get("/profile", response_model=ProductModeProfile)
def get_product_mode_profile(
    mode_profile_id: Optional[str] = Query(default=None),
) -> ProductModeProfile:
    try:
        return product_progress_service.get_mode_profile(mode_profile_id)
    except (ProductProgressError, StorageError) as exc:
        _raise_product_mode_error(exc)
        raise AssertionError("unreachable")


@router.patch("/profile", response_model=ProductModeProfile)
def patch_product_mode_profile(
    request: PatchProductModeProfileRequest,
) -> ProductModeProfile:
    try:
        return product_progress_service.patch_mode_profile(request)
    except (ProductProgressError, StorageError) as exc:
        _raise_product_mode_error(exc)
        raise AssertionError("unreachable")
