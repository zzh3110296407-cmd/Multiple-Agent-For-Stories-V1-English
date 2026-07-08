from fastapi import APIRouter, HTTPException

from ..models.phase6_release_gate import (
    Phase6CloseoutReadinessReport,
    Phase6CloseoutReadinessReportListResponse,
    Phase6EvidenceIndex,
    Phase6EvidenceIndexListResponse,
    Phase6FormalFilePollutionAudit,
    Phase6FormalFilePollutionAuditListResponse,
    Phase6KnownResidualsCarryForwardReport,
    Phase6KnownResidualsCarryForwardReportListResponse,
    Phase6RegressionManifest,
    Phase6RegressionManifestListResponse,
    Phase6ReleaseGateReport,
    Phase6ReleaseGateReportListResponse,
    Phase6ReleaseGateRunResult,
    Phase6SafetyAuthorityAudit,
    Phase6SafetyAuthorityAuditListResponse,
    Phase6VerifierRunRecord,
    Phase6VerifierRunRecordListResponse,
    ReleaseGateRunRequest,
    ReleaseGateStatusResponse,
)
from ..services.phase6_release_gate_service import Phase6ReleaseGateService
from ..storage.json_store import StorageError


router = APIRouter()
phase6_release_gate_service = Phase6ReleaseGateService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if "BLOCKED" in message or "FORBIDDEN_STORAGE_MUTATION" in message:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=ReleaseGateStatusResponse)
def get_release_gate_status() -> ReleaseGateStatusResponse:
    try:
        return phase6_release_gate_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.post("/run", response_model=Phase6ReleaseGateRunResult)
def run_release_gate(request: ReleaseGateRunRequest) -> Phase6ReleaseGateRunResult:
    try:
        return phase6_release_gate_service.run_release_gate(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reports", response_model=Phase6ReleaseGateReportListResponse)
def list_release_gate_reports() -> Phase6ReleaseGateReportListResponse:
    try:
        return phase6_release_gate_service.list_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reports/{release_gate_report_id}", response_model=Phase6ReleaseGateReport)
def get_release_gate_report(release_gate_report_id: str) -> Phase6ReleaseGateReport:
    try:
        return phase6_release_gate_service.get_report(release_gate_report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/regression-manifests", response_model=Phase6RegressionManifestListResponse)
def list_release_gate_regression_manifests() -> Phase6RegressionManifestListResponse:
    try:
        return phase6_release_gate_service.list_regression_manifests()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/regression-manifests/{manifest_id}", response_model=Phase6RegressionManifest)
def get_release_gate_regression_manifest(manifest_id: str) -> Phase6RegressionManifest:
    try:
        return phase6_release_gate_service.get_regression_manifest(manifest_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/verifier-runs", response_model=Phase6VerifierRunRecordListResponse)
def list_release_gate_verifier_runs() -> Phase6VerifierRunRecordListResponse:
    try:
        return phase6_release_gate_service.list_verifier_runs()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/verifier-runs/{verifier_run_id}", response_model=Phase6VerifierRunRecord)
def get_release_gate_verifier_run(verifier_run_id: str) -> Phase6VerifierRunRecord:
    try:
        return phase6_release_gate_service.get_verifier_run(verifier_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/evidence-indexes", response_model=Phase6EvidenceIndexListResponse)
def list_release_gate_evidence_indexes() -> Phase6EvidenceIndexListResponse:
    try:
        return phase6_release_gate_service.list_evidence_indexes()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/evidence-indexes/{evidence_index_id}", response_model=Phase6EvidenceIndex)
def get_release_gate_evidence_index(evidence_index_id: str) -> Phase6EvidenceIndex:
    try:
        return phase6_release_gate_service.get_evidence_index(evidence_index_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/closeout-readiness", response_model=Phase6CloseoutReadinessReportListResponse)
def list_release_gate_closeout_readiness() -> Phase6CloseoutReadinessReportListResponse:
    try:
        return phase6_release_gate_service.list_closeout_readiness_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/closeout-readiness/{closeout_report_id}", response_model=Phase6CloseoutReadinessReport)
def get_release_gate_closeout_readiness(closeout_report_id: str) -> Phase6CloseoutReadinessReport:
    try:
        return phase6_release_gate_service.get_closeout_readiness_report(closeout_report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/safety-authority-audits", response_model=Phase6SafetyAuthorityAuditListResponse)
def list_release_gate_safety_authority_audits() -> Phase6SafetyAuthorityAuditListResponse:
    try:
        return phase6_release_gate_service.list_safety_authority_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/safety-authority-audits/{audit_id}", response_model=Phase6SafetyAuthorityAudit)
def get_release_gate_safety_authority_audit(audit_id: str) -> Phase6SafetyAuthorityAudit:
    try:
        return phase6_release_gate_service.get_safety_authority_audit(audit_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/formal-file-pollution-audits", response_model=Phase6FormalFilePollutionAuditListResponse)
def list_release_gate_formal_file_pollution_audits() -> Phase6FormalFilePollutionAuditListResponse:
    try:
        return phase6_release_gate_service.list_formal_file_pollution_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/formal-file-pollution-audits/{audit_id}", response_model=Phase6FormalFilePollutionAudit)
def get_release_gate_formal_file_pollution_audit(audit_id: str) -> Phase6FormalFilePollutionAudit:
    try:
        return phase6_release_gate_service.get_formal_file_pollution_audit(audit_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/known-residuals", response_model=Phase6KnownResidualsCarryForwardReportListResponse)
def list_release_gate_known_residuals() -> Phase6KnownResidualsCarryForwardReportListResponse:
    try:
        return phase6_release_gate_service.list_known_residuals_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/known-residuals/{residual_report_id}", response_model=Phase6KnownResidualsCarryForwardReport)
def get_release_gate_known_residuals(residual_report_id: str) -> Phase6KnownResidualsCarryForwardReport:
    try:
        return phase6_release_gate_service.get_known_residuals_report(residual_report_id)
    except StorageError as exc:
        _raise_http(exc)
