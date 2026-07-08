from fastapi import APIRouter, HTTPException

from ..models.plugin_runtime import (
    PluginOutputArtifact,
    PluginOutputArtifactVersion,
    PluginOutputArtifactVersionListResponse,
)
from ..services.plugin_run_service import PluginRunService
from ..storage.json_store import StorageError


router = APIRouter()
plugin_run_service = PluginRunService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if "BLOCKED" in message or "NOT_ALLOWED" in message:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/{artifact_id}", response_model=PluginOutputArtifact)
def get_plugin_artifact(artifact_id: str) -> PluginOutputArtifact:
    try:
        return plugin_run_service.get_artifact(artifact_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{artifact_id}/versions", response_model=PluginOutputArtifactVersionListResponse)
def list_plugin_artifact_versions(artifact_id: str) -> PluginOutputArtifactVersionListResponse:
    try:
        return plugin_run_service.list_artifact_versions(artifact_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{artifact_id}/versions/{artifact_version_id}", response_model=PluginOutputArtifactVersion)
def get_plugin_artifact_version(artifact_id: str, artifact_version_id: str) -> PluginOutputArtifactVersion:
    try:
        return plugin_run_service.get_artifact_version(artifact_id, artifact_version_id)
    except StorageError as exc:
        _raise_http(exc)
