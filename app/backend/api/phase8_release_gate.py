from fastapi import APIRouter, HTTPException

from ..models.phase8_release_gate import (
    Phase8ArtifactAuthorityAuditListResponse,
    Phase8CloseoutReadinessReportListResponse,
    Phase8DebugIsolationE2EAuditListResponse,
    Phase8DemoSeedIsolationE2EAuditListResponse,
    Phase8EvidenceIndexListResponse,
    Phase8HandoffIndexListResponse,
    Phase8KnownResidualCarryForwardReportListResponse,
    Phase8ProductWorkbenchE2EReport,
    Phase8ProductWorkbenchE2EReportListResponse,
    Phase8ProgressViewModelAuditListResponse,
    Phase8RegressionManifestListResponse,
    Phase8ReleaseGateReport,
    Phase8ReleaseGateReportListResponse,
    Phase8ReleaseGateRunRequest,
    Phase8ReleaseGateRunResult,
    Phase8ReleaseGateStatusResponse,
    Phase8ScopeBoundaryAuditListResponse,
    Phase8SecretSafetyAuditListResponse,
    Phase8VerifierRunRecordListResponse,
)
from ..services.phase8_release_gate_service import Phase8ReleaseGateService
from ..storage.json_store import StorageError


router = APIRouter()
phase8_release_gate_service = Phase8ReleaseGateService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if "BLOCKED" in message or "MUTATION" in message or "FORBIDDEN" in message:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=Phase8ReleaseGateStatusResponse)
def get_release_gate_status() -> Phase8ReleaseGateStatusResponse:
    try:
        return phase8_release_gate_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.post("/run", response_model=Phase8ReleaseGateRunResult)
def run_release_gate(request: Phase8ReleaseGateRunRequest) -> Phase8ReleaseGateRunResult:
    try:
        return phase8_release_gate_service.run_release_gate(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reports", response_model=Phase8ReleaseGateReportListResponse)
def list_release_gate_reports() -> Phase8ReleaseGateReportListResponse:
    try:
        return phase8_release_gate_service.list_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reports/{release_gate_report_id}", response_model=Phase8ReleaseGateReport)
def get_release_gate_report(release_gate_report_id: str) -> Phase8ReleaseGateReport:
    try:
        return phase8_release_gate_service.get_report(release_gate_report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/e2e-reports", response_model=Phase8ProductWorkbenchE2EReportListResponse)
def list_release_gate_e2e_reports() -> Phase8ProductWorkbenchE2EReportListResponse:
    try:
        return phase8_release_gate_service.list_e2e_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/e2e-reports/{e2e_report_id}", response_model=Phase8ProductWorkbenchE2EReport)
def get_release_gate_e2e_report(e2e_report_id: str) -> Phase8ProductWorkbenchE2EReport:
    try:
        return phase8_release_gate_service.get_e2e_report(e2e_report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/regression-manifests", response_model=Phase8RegressionManifestListResponse)
def list_release_gate_regression_manifests() -> Phase8RegressionManifestListResponse:
    try:
        return phase8_release_gate_service.list_regression_manifests()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/verifier-runs", response_model=Phase8VerifierRunRecordListResponse)
def list_release_gate_verifier_runs() -> Phase8VerifierRunRecordListResponse:
    try:
        return phase8_release_gate_service.list_verifier_runs()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/evidence-indexes", response_model=Phase8EvidenceIndexListResponse)
def list_release_gate_evidence_indexes() -> Phase8EvidenceIndexListResponse:
    try:
        return phase8_release_gate_service.list_evidence_indexes()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/secret-safety-audits", response_model=Phase8SecretSafetyAuditListResponse)
def list_release_gate_secret_safety_audits() -> Phase8SecretSafetyAuditListResponse:
    try:
        return phase8_release_gate_service.list_secret_safety_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/demo-seed-isolation-audits", response_model=Phase8DemoSeedIsolationE2EAuditListResponse)
def list_release_gate_demo_seed_isolation_audits() -> Phase8DemoSeedIsolationE2EAuditListResponse:
    try:
        return phase8_release_gate_service.list_demo_seed_isolation_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/progress-view-model-audits", response_model=Phase8ProgressViewModelAuditListResponse)
def list_release_gate_progress_view_model_audits() -> Phase8ProgressViewModelAuditListResponse:
    try:
        return phase8_release_gate_service.list_progress_view_model_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/debug-isolation-audits", response_model=Phase8DebugIsolationE2EAuditListResponse)
def list_release_gate_debug_isolation_audits() -> Phase8DebugIsolationE2EAuditListResponse:
    try:
        return phase8_release_gate_service.list_debug_isolation_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/artifact-authority-audits", response_model=Phase8ArtifactAuthorityAuditListResponse)
def list_release_gate_artifact_authority_audits() -> Phase8ArtifactAuthorityAuditListResponse:
    try:
        return phase8_release_gate_service.list_artifact_authority_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/scope-boundary-audits", response_model=Phase8ScopeBoundaryAuditListResponse)
def list_release_gate_scope_boundary_audits() -> Phase8ScopeBoundaryAuditListResponse:
    try:
        return phase8_release_gate_service.list_scope_boundary_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/closeout-readiness", response_model=Phase8CloseoutReadinessReportListResponse)
def list_release_gate_closeout_readiness() -> Phase8CloseoutReadinessReportListResponse:
    try:
        return phase8_release_gate_service.list_closeout_readiness_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/known-residuals", response_model=Phase8KnownResidualCarryForwardReportListResponse)
def list_release_gate_known_residuals() -> Phase8KnownResidualCarryForwardReportListResponse:
    try:
        return phase8_release_gate_service.list_known_residuals_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/handoff-indexes", response_model=Phase8HandoffIndexListResponse)
def list_release_gate_handoff_indexes() -> Phase8HandoffIndexListResponse:
    try:
        return phase8_release_gate_service.list_handoff_indexes()
    except StorageError as exc:
        _raise_http(exc)
