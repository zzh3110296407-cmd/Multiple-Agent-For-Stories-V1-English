from fastapi import APIRouter, HTTPException, Response

from ..models.final_story_package import (
    FinalStoryPackageEvidenceIndex,
    FinalStoryPackageExportRequest,
    FinalStoryPackageExportResponse,
    FinalStoryPackageExportRun,
    FinalStoryPackageExportRunListResponse,
    FinalStoryPackagePreviewSectionListResponse,
    FinalStoryPackageReadinessEvaluateRequest,
    FinalStoryPackageReadinessEvaluationResponse,
    FinalStoryPackageReadinessGate,
    FinalStoryPackageReadinessIssueListResponse,
    FinalStoryPackageReadinessStatusResponse,
    FinalStoryPackageSafetyAudit,
    FinalStoryPackageSnapshot,
    FinalStoryPackageViewerState,
    FinalStoryPackageViewerStateRequest,
)
from ..services.final_story_package_export_service import FinalStoryPackageExportService
from ..services.final_story_package_readiness_service import FinalStoryPackageReadinessService
from ..storage.json_store import StorageError


router = APIRouter()
final_story_package_readiness_service: FinalStoryPackageReadinessService | None = None
final_story_package_export_service: FinalStoryPackageExportService | None = None


def _readiness_service() -> FinalStoryPackageReadinessService:
    return final_story_package_readiness_service or FinalStoryPackageReadinessService()


def _export_service() -> FinalStoryPackageExportService:
    return final_story_package_export_service or FinalStoryPackageExportService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "DOWNLOAD_FORMAT_UNSUPPORTED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if "ACTIVE_PROJECT_STORY_DATA_NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if (
        "FORBIDDEN_STORAGE_WRITE" in message
        or "EXPORT_BLOCKED" in message
        or "EXPORT_NOT_ALLOWED" in message
        or "NOT_AUTHORIZED" in message
        or "NON_TRUTH_SOURCE_REF" in message
        or "COMPLETE_STORY_TEXT_MISSING" in message
        or "SCENE_NOT_CONFIRMED" in message
        or "PARENT_WORLD_CANVAS_NOT_TRUTH" in message
        or "SOURCE_VERSION_DRIFT" in message
        or "FIXTURE_EXPORT" in message
        or "REAL_EXPORT" in message
        or "SAFETY_AUDIT_FAILED" in message
        or "DOWNLOAD_NOT_AUTHORIZED" in message
        or "DOWNLOAD_NOT_REAL_PROJECT_PACKAGE" in message
        or "DOWNLOAD_SNAPSHOT_NOT_CREATED" in message
        or "DOWNLOAD_COMPLETE_STORY_TEXT_MISSING" in message
        or "DOWNLOAD_TEXT_HASH_MISMATCH" in message
        or "DOWNLOAD_TEXT_COUNT_MISMATCH" in message
        or "FINAL_STORY_PACKAGE_GATE_READINESS_BLOCKED" in message
    ):
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/readiness", response_model=FinalStoryPackageReadinessStatusResponse)
def get_final_story_package_readiness() -> FinalStoryPackageReadinessStatusResponse:
    try:
        return _readiness_service().get_status()
    except StorageError as exc:
        if "ACTIVE_PROJECT_STORY_DATA_NOT_FOUND" in str(exc):
            return FinalStoryPackageReadinessStatusResponse(
                safe_summary="Final story package readiness is not evaluated because the active project story data is not initialized.",
            )
        _raise_http(exc)


@router.post("/readiness/evaluate", response_model=FinalStoryPackageReadinessEvaluationResponse)
def evaluate_final_story_package_readiness(
    request: FinalStoryPackageReadinessEvaluateRequest,
) -> FinalStoryPackageReadinessEvaluationResponse:
    try:
        return _readiness_service().evaluate_readiness(
            allow_fixture=request.allow_fixture,
            persist=request.persist,
            safe_user_note=request.safe_user_note,
        )
    except StorageError as exc:
        _raise_http(exc)


@router.get("/readiness/{readiness_gate_id}", response_model=FinalStoryPackageReadinessGate)
def get_final_story_package_readiness_gate(readiness_gate_id: str) -> FinalStoryPackageReadinessGate:
    try:
        return _readiness_service().get_readiness_gate(readiness_gate_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/readiness/{readiness_gate_id}/issues", response_model=FinalStoryPackageReadinessIssueListResponse)
def list_final_story_package_readiness_issues(
    readiness_gate_id: str,
) -> FinalStoryPackageReadinessIssueListResponse:
    try:
        return _readiness_service().list_readiness_issues(readiness_gate_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/export", response_model=FinalStoryPackageExportResponse)
def export_final_story_package(request: FinalStoryPackageExportRequest) -> FinalStoryPackageExportResponse:
    try:
        return _export_service().create_export(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/exports", response_model=FinalStoryPackageExportRunListResponse)
def list_final_story_package_exports() -> FinalStoryPackageExportRunListResponse:
    try:
        return _export_service().list_export_runs()
    except StorageError as exc:
        if "ACTIVE_PROJECT_STORY_DATA_NOT_FOUND" in str(exc):
            return FinalStoryPackageExportRunListResponse(export_runs=[], total_count=0)
        _raise_http(exc)


@router.get("/exports/{export_run_id}", response_model=FinalStoryPackageExportRun)
def get_final_story_package_export(export_run_id: str) -> FinalStoryPackageExportRun:
    try:
        return _export_service().get_export_run(export_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/snapshots/{snapshot_id}", response_model=FinalStoryPackageSnapshot)
def get_final_story_package_snapshot(snapshot_id: str) -> FinalStoryPackageSnapshot:
    try:
        return _export_service().get_snapshot(snapshot_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/snapshots/{snapshot_id}/download")
def download_final_story_package_snapshot(snapshot_id: str, format: str = "txt") -> Response:
    try:
        payload = _export_service().build_snapshot_download(snapshot_id, format)
        return Response(
            content=payload.content,
            media_type=payload.media_type,
            headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
        )
    except StorageError as exc:
        _raise_http(exc)


@router.get("/snapshots/{snapshot_id}/sections", response_model=FinalStoryPackagePreviewSectionListResponse)
def get_final_story_package_snapshot_sections(snapshot_id: str) -> FinalStoryPackagePreviewSectionListResponse:
    try:
        return _export_service().get_snapshot_preview_sections(snapshot_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/snapshots/{snapshot_id}/evidence-index", response_model=FinalStoryPackageEvidenceIndex)
def get_final_story_package_evidence_index(snapshot_id: str) -> FinalStoryPackageEvidenceIndex:
    try:
        return _export_service().get_evidence_index(snapshot_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/snapshots/{snapshot_id}/safety-audit", response_model=FinalStoryPackageSafetyAudit)
def get_final_story_package_safety_audit(snapshot_id: str) -> FinalStoryPackageSafetyAudit:
    try:
        return _export_service().get_safety_audit(snapshot_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/viewer-states", response_model=FinalStoryPackageViewerState)
def create_final_story_package_viewer_state(
    request: FinalStoryPackageViewerStateRequest,
) -> FinalStoryPackageViewerState:
    try:
        return _export_service().create_viewer_state(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/viewer-states/{viewer_state_id}", response_model=FinalStoryPackageViewerState)
def get_final_story_package_viewer_state(viewer_state_id: str) -> FinalStoryPackageViewerState:
    try:
        return _export_service().get_viewer_state(viewer_state_id)
    except StorageError as exc:
        _raise_http(exc)
