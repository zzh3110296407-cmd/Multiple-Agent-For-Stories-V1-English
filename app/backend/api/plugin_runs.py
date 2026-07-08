from fastapi import APIRouter, HTTPException

from ..models.plugin_runtime import (
    PluginCheckpointDecisionRequest,
    PluginCheckpointDecisionResponse,
    PluginCheckpointListResponse,
    PluginOutputArtifactListResponse,
    PluginRun,
    PluginRunCancelRequest,
    PluginRunSafetyReport,
    PluginRunStepListResponse,
    PluginRunListResponse,
)
from ..services.plugin_run_service import PluginRunService
from ..storage.json_store import StorageError


router = APIRouter()
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
        or "NOT_PENDING" in message
        or "NOT_WAITING" in message
        or "VALIDATION_FAILED" in message
        or "MISMATCH" in message
    ):
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("", response_model=PluginRunListResponse)
def list_plugin_runs() -> PluginRunListResponse:
    try:
        return plugin_run_service.list_runs()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}", response_model=PluginRun)
def get_plugin_run(plugin_run_id: str) -> PluginRun:
    try:
        return plugin_run_service.get_run(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/cancel", response_model=PluginRun)
def cancel_plugin_run(plugin_run_id: str, request: PluginRunCancelRequest) -> PluginRun:
    try:
        return plugin_run_service.cancel_run(plugin_run_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/steps", response_model=PluginRunStepListResponse)
def list_plugin_run_steps(plugin_run_id: str) -> PluginRunStepListResponse:
    try:
        return plugin_run_service.list_steps(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/checkpoints", response_model=PluginCheckpointListResponse)
def list_plugin_run_checkpoints(plugin_run_id: str) -> PluginCheckpointListResponse:
    try:
        return plugin_run_service.list_checkpoints(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/artifacts", response_model=PluginOutputArtifactListResponse)
def list_plugin_run_artifacts(plugin_run_id: str) -> PluginOutputArtifactListResponse:
    try:
        return plugin_run_service.list_artifacts(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/safety-report", response_model=PluginRunSafetyReport)
def get_plugin_run_safety_report(plugin_run_id: str) -> PluginRunSafetyReport:
    try:
        return plugin_run_service.get_safety_report(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/checkpoints/{checkpoint_id}/confirm", response_model=PluginCheckpointDecisionResponse)
def confirm_plugin_checkpoint(
    plugin_run_id: str,
    checkpoint_id: str,
    request: PluginCheckpointDecisionRequest,
) -> PluginCheckpointDecisionResponse:
    try:
        return plugin_run_service.submit_checkpoint_decision(plugin_run_id, checkpoint_id, "confirm", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/checkpoints/{checkpoint_id}/revise", response_model=PluginCheckpointDecisionResponse)
def revise_plugin_checkpoint(
    plugin_run_id: str,
    checkpoint_id: str,
    request: PluginCheckpointDecisionRequest,
) -> PluginCheckpointDecisionResponse:
    try:
        return plugin_run_service.submit_checkpoint_decision(plugin_run_id, checkpoint_id, "request_revision", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/checkpoints/{checkpoint_id}/reject", response_model=PluginCheckpointDecisionResponse)
def reject_plugin_checkpoint(
    plugin_run_id: str,
    checkpoint_id: str,
    request: PluginCheckpointDecisionRequest,
) -> PluginCheckpointDecisionResponse:
    try:
        return plugin_run_service.submit_checkpoint_decision(plugin_run_id, checkpoint_id, "reject", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/checkpoints/{checkpoint_id}/defer", response_model=PluginCheckpointDecisionResponse)
def defer_plugin_checkpoint(
    plugin_run_id: str,
    checkpoint_id: str,
    request: PluginCheckpointDecisionRequest,
) -> PluginCheckpointDecisionResponse:
    try:
        return plugin_run_service.submit_checkpoint_decision(plugin_run_id, checkpoint_id, "defer", request)
    except StorageError as exc:
        _raise_http(exc)
