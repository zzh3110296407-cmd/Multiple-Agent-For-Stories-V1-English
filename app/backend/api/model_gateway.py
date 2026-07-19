from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.model_gateway import (
    ModelGatewaySeedResponse,
    ModelGatewayStatusResponse,
)
from app.backend.services.model_gateway_service import ModelGatewayService
from app.backend.services.model_gateway_service import ModelConfigurationError
from app.backend.storage.json_store import StorageError

router = APIRouter()
model_gateway_service = ModelGatewayService()


@router.get("/status", response_model=ModelGatewayStatusResponse)
def get_model_gateway_status() -> ModelGatewayStatusResponse:
    return model_gateway_service.validate_model_config()


@router.post("/seed", response_model=ModelGatewaySeedResponse)
def seed_model_gateway_config() -> ModelGatewaySeedResponse:
    try:
        return model_gateway_service.seed_default_model_config()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/configure-deepseek", response_model=ModelGatewaySeedResponse)
def configure_deepseek_model_gateway() -> ModelGatewaySeedResponse:
    try:
        return model_gateway_service.configure_deepseek_active_model()
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/configure-qwen", response_model=ModelGatewaySeedResponse)
def configure_qwen_model_gateway(
    model_name: Optional[str] = Query(default=None),
) -> ModelGatewaySeedResponse:
    try:
        return model_gateway_service.configure_qwen_active_model(
            model_name=model_name,
        )
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
