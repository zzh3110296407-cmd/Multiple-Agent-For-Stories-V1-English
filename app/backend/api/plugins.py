from fastapi import APIRouter, HTTPException

from ..models.plugin_protocol import (
    PluginInputSchema,
    PluginInputValidationReport,
    PluginInputValidationRequest,
    PluginManifest,
    PluginOutputSchemaListResponse,
    PluginRegistryDetailResponse,
    PluginRegistryListResponse,
    PluginRiskDeclaration,
)
from ..models.plugin_runtime import PluginRunCreateRequest, PluginRunCreateResponse
from ..services.plugin_input_validation_service import PluginInputValidationService
from ..services.plugin_manifest_service import PluginManifestService
from ..services.plugin_registry_service import PluginRegistryService
from ..services.plugin_run_service import PluginRunService
from ..services.plugin_risk_policy_service import PluginRiskPolicyService
from ..storage.json_store import StorageError


router = APIRouter()
plugin_manifest_service = PluginManifestService()
plugin_registry_service = PluginRegistryService()
plugin_input_validation_service = PluginInputValidationService()
plugin_risk_policy_service = PluginRiskPolicyService()
plugin_run_service = PluginRunService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message or "LIVE_STORY_REF_BLOCKED" in message or "SNAPSHOT_REQUIRED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if (
        "BLOCKED" in message
        or "NOT_ALLOWED" in message
        or "STATIC_RECORD" in message
        or "VALIDATION_FAILED" in message
        or "MISMATCH" in message
        or "NOT_PENDING" in message
        or "NOT_WAITING" in message
        or "TERMINAL_STATE" in message
        or "STORAGE_NOT_LIST" in message
        or "FULL_STORY_TEXT_COPY" in message
    ):
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("", response_model=PluginRegistryListResponse)
def list_plugins() -> PluginRegistryListResponse:
    try:
        return plugin_registry_service.list_plugins()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_id}", response_model=PluginRegistryDetailResponse)
def get_plugin(plugin_id: str) -> PluginRegistryDetailResponse:
    try:
        return plugin_registry_service.get_plugin(plugin_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_id}/manifest", response_model=PluginManifest)
def get_plugin_manifest(plugin_id: str) -> PluginManifest:
    try:
        return plugin_manifest_service.get_manifest(plugin_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_id}/input-schema", response_model=PluginInputSchema)
def get_plugin_input_schema(plugin_id: str) -> PluginInputSchema:
    try:
        return plugin_manifest_service.get_input_schema(plugin_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_id}/output-schemas", response_model=PluginOutputSchemaListResponse)
def get_plugin_output_schemas(plugin_id: str) -> PluginOutputSchemaListResponse:
    try:
        return plugin_manifest_service.get_output_schemas(plugin_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_id}/risk-declaration", response_model=PluginRiskDeclaration)
def get_plugin_risk_declaration(plugin_id: str) -> PluginRiskDeclaration:
    try:
        return plugin_risk_policy_service.get_risk_declaration(plugin_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_id}/validate-input", response_model=PluginInputValidationReport)
def validate_plugin_input(
    plugin_id: str,
    request: PluginInputValidationRequest,
) -> PluginInputValidationReport:
    try:
        return plugin_input_validation_service.validate_input(plugin_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_id}/runs", response_model=PluginRunCreateResponse)
def create_plugin_run(plugin_id: str, request: PluginRunCreateRequest) -> PluginRunCreateResponse:
    try:
        return plugin_run_service.create_run(plugin_id, request)
    except StorageError as exc:
        _raise_http(exc)
