from fastapi import APIRouter, HTTPException

from ..models.phase6_replay_gate import (
    KnownGapCarryForwardListResponse,
    ReplayGateCompatibilityMatrix,
    ReplayGateReportListResponse,
    ReplayGateRunRequest,
    ReplayGateRunResult,
    ReplayGateStatusResponse,
    StableCleanReplayReport,
)
from ..services.phase6_replay_gate_service import Phase6ReplayGateService
from ..storage.json_store import StorageError


router = APIRouter()
phase6_replay_gate_service = Phase6ReplayGateService()


def _dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if "BLOCKED" in message or "REQUIRED" in message:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=ReplayGateStatusResponse)
def get_phase6_replay_gate_status() -> ReplayGateStatusResponse:
    try:
        return phase6_replay_gate_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.post("/run", response_model=ReplayGateRunResult)
def run_phase6_replay_gate(request: ReplayGateRunRequest) -> ReplayGateRunResult:
    try:
        result = phase6_replay_gate_service.run_gate(request)
    except StorageError as exc:
        _raise_http(exc)
    if result.report.replay_status == "blocked":
        raise HTTPException(status_code=409, detail=_dump_model(result.report))
    return result


@router.get("/reports", response_model=ReplayGateReportListResponse)
def list_phase6_replay_gate_reports() -> ReplayGateReportListResponse:
    try:
        return phase6_replay_gate_service.list_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reports/{replay_report_id}", response_model=StableCleanReplayReport)
def get_phase6_replay_gate_report(replay_report_id: str) -> StableCleanReplayReport:
    try:
        return phase6_replay_gate_service.get_report(replay_report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/known-gaps", response_model=KnownGapCarryForwardListResponse)
def list_phase6_replay_gate_known_gaps() -> KnownGapCarryForwardListResponse:
    try:
        return phase6_replay_gate_service.list_known_gaps()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/compatibility-matrices/{matrix_id}", response_model=ReplayGateCompatibilityMatrix)
def get_phase6_replay_gate_compatibility_matrix(matrix_id: str) -> ReplayGateCompatibilityMatrix:
    try:
        return phase6_replay_gate_service.get_compatibility_matrix(matrix_id)
    except StorageError as exc:
        _raise_http(exc)
