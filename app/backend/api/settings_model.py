from fastapi import APIRouter, HTTPException

from app.backend.models.model_settings import (
    ActiveModelSelection,
    ActiveModelSelectionResponse,
    CreateModelProviderProfileRequest,
    ModelProviderProfile,
    ModelProviderProfilesResponse,
    ModelSecretPolicy,
    ModelSettingsProvidersResponse,
    ModelSettingsWorkbench,
    PatchModelProviderProfileRequest,
    ProviderHealthCheckResponse,
    SetActiveModelSelectionRequest,
)
from app.backend.services.model_settings_service import (
    ModelSettingsError,
    ModelSettingsNotFound,
    ModelSettingsSafetyError,
    ModelSettingsService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
model_settings_service = ModelSettingsService()


@router.get("/providers", response_model=ModelSettingsProvidersResponse)
def get_model_provider_options() -> ModelSettingsProvidersResponse:
    return model_settings_service.provider_options()


@router.get("/workbench", response_model=ModelSettingsWorkbench)
def get_model_settings_workbench() -> ModelSettingsWorkbench:
    try:
        return model_settings_service.workbench()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/profiles", response_model=ModelProviderProfile)
def create_model_provider_profile(
    request: CreateModelProviderProfileRequest,
) -> ModelProviderProfile:
    try:
        return model_settings_service.create_profile(request)
    except ModelSettingsSafetyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/profiles", response_model=ModelProviderProfilesResponse)
def get_model_provider_profiles() -> ModelProviderProfilesResponse:
    try:
        return model_settings_service.list_profiles()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/profiles/{profile_id}", response_model=ModelProviderProfile)
def get_model_provider_profile(profile_id: str) -> ModelProviderProfile:
    try:
        return model_settings_service.get_profile(profile_id)
    except ModelSettingsNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/profiles/{profile_id}", response_model=ModelProviderProfile)
def patch_model_provider_profile(
    profile_id: str,
    request: PatchModelProviderProfileRequest,
) -> ModelProviderProfile:
    try:
        return model_settings_service.patch_profile(profile_id, request)
    except ModelSettingsNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModelSettingsSafetyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/profiles/{profile_id}/health-check",
    response_model=ProviderHealthCheckResponse,
)
def run_model_provider_health_check(profile_id: str) -> ProviderHealthCheckResponse:
    try:
        return model_settings_service.run_health_check(profile_id)
    except ModelSettingsNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModelSettingsSafetyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/active-selection", response_model=ActiveModelSelection)
def set_active_model_selection(
    request: SetActiveModelSelectionRequest,
) -> ActiveModelSelection:
    try:
        return model_settings_service.set_active_selection(request)
    except ModelSettingsNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModelSettingsSafetyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/active-selection", response_model=ActiveModelSelectionResponse)
def get_active_model_selection() -> ActiveModelSelectionResponse:
    try:
        return model_settings_service.get_active_selection()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/secret-policy", response_model=ModelSecretPolicy)
def get_model_secret_policy() -> ModelSecretPolicy:
    return model_settings_service.secret_policy()
