from fastapi import APIRouter, HTTPException

from ..models.phase7_release_gate import (
    Phase7CheckpointAuthorityAudit,
    Phase7CheckpointAuthorityAuditListResponse,
    Phase7CloseoutReadinessReport,
    Phase7CloseoutReadinessReportListResponse,
    Phase7EvidenceIndex,
    Phase7EvidenceIndexListResponse,
    Phase7ExternalProviderNoCallAudit,
    Phase7ExternalProviderNoCallAuditListResponse,
    Phase7KnownResidualCarryForwardReport,
    Phase7KnownResidualCarryForwardReportListResponse,
    Phase7LicenseTemplateSafetyAudit,
    Phase7LicenseTemplateSafetyAuditListResponse,
    Phase7NoWriteAudit,
    Phase7NoWriteAuditListResponse,
    Phase7PluginArtifactVersioningAudit,
    Phase7PluginArtifactVersioningAuditListResponse,
    Phase7PluginE2EReport,
    Phase7PluginE2EReportListResponse,
    Phase7RegressionManifest,
    Phase7RegressionManifestListResponse,
    Phase7ReleaseGateReport,
    Phase7ReleaseGateReportListResponse,
    Phase7ReleaseGateRunRequest,
    Phase7ReleaseGateRunResult,
    Phase7ReleaseGateStatusResponse,
    Phase7VerifierRunRecord,
    Phase7VerifierRunRecordListResponse,
)
from ..services.phase7_release_gate_service import Phase7ReleaseGateService
from ..storage.json_store import StorageError


router = APIRouter()
phase7_release_gate_service = Phase7ReleaseGateService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if "BLOCKED" in message or "MUTATION" in message or "FORBIDDEN" in message:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=Phase7ReleaseGateStatusResponse)
def get_release_gate_status() -> Phase7ReleaseGateStatusResponse:
    try:
        return phase7_release_gate_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.post("/run", response_model=Phase7ReleaseGateRunResult)
def run_release_gate(request: Phase7ReleaseGateRunRequest) -> Phase7ReleaseGateRunResult:
    try:
        return phase7_release_gate_service.run_release_gate(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reports", response_model=Phase7ReleaseGateReportListResponse)
def list_release_gate_reports() -> Phase7ReleaseGateReportListResponse:
    try:
        return phase7_release_gate_service.list_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reports/{release_gate_report_id}", response_model=Phase7ReleaseGateReport)
def get_release_gate_report(release_gate_report_id: str) -> Phase7ReleaseGateReport:
    try:
        return phase7_release_gate_service.get_report(release_gate_report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/e2e-reports", response_model=Phase7PluginE2EReportListResponse)
def list_release_gate_e2e_reports() -> Phase7PluginE2EReportListResponse:
    try:
        return phase7_release_gate_service.list_e2e_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/e2e-reports/{e2e_report_id}", response_model=Phase7PluginE2EReport)
def get_release_gate_e2e_report(e2e_report_id: str) -> Phase7PluginE2EReport:
    try:
        return phase7_release_gate_service.get_e2e_report(e2e_report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/regression-manifests", response_model=Phase7RegressionManifestListResponse)
def list_release_gate_regression_manifests() -> Phase7RegressionManifestListResponse:
    try:
        return phase7_release_gate_service.list_regression_manifests()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/regression-manifests/{manifest_id}", response_model=Phase7RegressionManifest)
def get_release_gate_regression_manifest(manifest_id: str) -> Phase7RegressionManifest:
    try:
        return phase7_release_gate_service.get_regression_manifest(manifest_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/verifier-runs", response_model=Phase7VerifierRunRecordListResponse)
def list_release_gate_verifier_runs() -> Phase7VerifierRunRecordListResponse:
    try:
        return phase7_release_gate_service.list_verifier_runs()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/verifier-runs/{verifier_run_id}", response_model=Phase7VerifierRunRecord)
def get_release_gate_verifier_run(verifier_run_id: str) -> Phase7VerifierRunRecord:
    try:
        return phase7_release_gate_service.get_verifier_run(verifier_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/evidence-indexes", response_model=Phase7EvidenceIndexListResponse)
def list_release_gate_evidence_indexes() -> Phase7EvidenceIndexListResponse:
    try:
        return phase7_release_gate_service.list_evidence_indexes()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/evidence-indexes/{evidence_index_id}", response_model=Phase7EvidenceIndex)
def get_release_gate_evidence_index(evidence_index_id: str) -> Phase7EvidenceIndex:
    try:
        return phase7_release_gate_service.get_evidence_index(evidence_index_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/no-write-audits", response_model=Phase7NoWriteAuditListResponse)
def list_release_gate_no_write_audits() -> Phase7NoWriteAuditListResponse:
    try:
        return phase7_release_gate_service.list_no_write_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/no-write-audits/{audit_id}", response_model=Phase7NoWriteAudit)
def get_release_gate_no_write_audit(audit_id: str) -> Phase7NoWriteAudit:
    try:
        return phase7_release_gate_service.get_no_write_audit(audit_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/artifact-versioning-audits", response_model=Phase7PluginArtifactVersioningAuditListResponse)
def list_release_gate_artifact_versioning_audits() -> Phase7PluginArtifactVersioningAuditListResponse:
    try:
        return phase7_release_gate_service.list_artifact_versioning_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/artifact-versioning-audits/{audit_id}", response_model=Phase7PluginArtifactVersioningAudit)
def get_release_gate_artifact_versioning_audit(audit_id: str) -> Phase7PluginArtifactVersioningAudit:
    try:
        return phase7_release_gate_service.get_artifact_versioning_audit(audit_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/checkpoint-authority-audits", response_model=Phase7CheckpointAuthorityAuditListResponse)
def list_release_gate_checkpoint_authority_audits() -> Phase7CheckpointAuthorityAuditListResponse:
    try:
        return phase7_release_gate_service.list_checkpoint_authority_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/checkpoint-authority-audits/{audit_id}", response_model=Phase7CheckpointAuthorityAudit)
def get_release_gate_checkpoint_authority_audit(audit_id: str) -> Phase7CheckpointAuthorityAudit:
    try:
        return phase7_release_gate_service.get_checkpoint_authority_audit(audit_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/license-template-audits", response_model=Phase7LicenseTemplateSafetyAuditListResponse)
def list_release_gate_license_template_audits() -> Phase7LicenseTemplateSafetyAuditListResponse:
    try:
        return phase7_release_gate_service.list_license_template_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/license-template-audits/{audit_id}", response_model=Phase7LicenseTemplateSafetyAudit)
def get_release_gate_license_template_audit(audit_id: str) -> Phase7LicenseTemplateSafetyAudit:
    try:
        return phase7_release_gate_service.get_license_template_audit(audit_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/external-provider-no-call-audits", response_model=Phase7ExternalProviderNoCallAuditListResponse)
def list_release_gate_external_provider_no_call_audits() -> Phase7ExternalProviderNoCallAuditListResponse:
    try:
        return phase7_release_gate_service.list_external_provider_no_call_audits()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/external-provider-no-call-audits/{audit_id}", response_model=Phase7ExternalProviderNoCallAudit)
def get_release_gate_external_provider_no_call_audit(audit_id: str) -> Phase7ExternalProviderNoCallAudit:
    try:
        return phase7_release_gate_service.get_external_provider_no_call_audit(audit_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/closeout-readiness", response_model=Phase7CloseoutReadinessReportListResponse)
def list_release_gate_closeout_readiness() -> Phase7CloseoutReadinessReportListResponse:
    try:
        return phase7_release_gate_service.list_closeout_readiness_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/closeout-readiness/{report_id}", response_model=Phase7CloseoutReadinessReport)
def get_release_gate_closeout_readiness(report_id: str) -> Phase7CloseoutReadinessReport:
    try:
        return phase7_release_gate_service.get_closeout_readiness_report(report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/known-residuals", response_model=Phase7KnownResidualCarryForwardReportListResponse)
def list_release_gate_known_residuals() -> Phase7KnownResidualCarryForwardReportListResponse:
    try:
        return phase7_release_gate_service.list_known_residuals_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/known-residuals/{residual_report_id}", response_model=Phase7KnownResidualCarryForwardReport)
def get_release_gate_known_residuals(residual_report_id: str) -> Phase7KnownResidualCarryForwardReport:
    try:
        return phase7_release_gate_service.get_known_residuals_report(residual_report_id)
    except StorageError as exc:
        _raise_http(exc)
