from fastapi import APIRouter, HTTPException

from ..models.formal_apply_eligibility import (
    FormalApplyBlockReasonListResponse,
    FormalApplyEligibilityReport,
    FormalApplyEligibilityReportListResponse,
    FormalApplyEligibilityResult,
    FormalApplyEligibilityStatusResponse,
    FormalApplyInspectRequest,
    FormalApplySourceLineage,
    FormalApplyTarget,
    FormalApplyTargetListResponse,
)
from ..services.formal_apply_eligibility_service import FormalApplyEligibilityService
from ..storage.json_store import StorageError


router = APIRouter()
formal_apply_eligibility_service = FormalApplyEligibilityService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=FormalApplyEligibilityStatusResponse)
def get_formal_apply_eligibility_status() -> FormalApplyEligibilityStatusResponse:
    try:
        return formal_apply_eligibility_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.post("/inspect", response_model=FormalApplyEligibilityResult)
def inspect_formal_apply_target(request: FormalApplyInspectRequest) -> FormalApplyEligibilityResult:
    try:
        return formal_apply_eligibility_service.inspect_target(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/targets", response_model=FormalApplyTargetListResponse)
def list_formal_apply_targets() -> FormalApplyTargetListResponse:
    try:
        return formal_apply_eligibility_service.list_targets()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/targets/{target_id}", response_model=FormalApplyTarget)
def get_formal_apply_target(target_id: str) -> FormalApplyTarget:
    try:
        return formal_apply_eligibility_service.get_target(target_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/eligibility-reports", response_model=FormalApplyEligibilityReportListResponse)
def list_formal_apply_eligibility_reports() -> FormalApplyEligibilityReportListResponse:
    try:
        return formal_apply_eligibility_service.list_eligibility_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/eligibility-reports/{eligibility_report_id}", response_model=FormalApplyEligibilityReport)
def get_formal_apply_eligibility_report(eligibility_report_id: str) -> FormalApplyEligibilityReport:
    try:
        return formal_apply_eligibility_service.get_eligibility_report(eligibility_report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/block-reasons", response_model=FormalApplyBlockReasonListResponse)
def list_formal_apply_block_reasons() -> FormalApplyBlockReasonListResponse:
    try:
        return formal_apply_eligibility_service.list_block_reasons()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/source-lineages/{lineage_id}", response_model=FormalApplySourceLineage)
def get_formal_apply_source_lineage(lineage_id: str) -> FormalApplySourceLineage:
    try:
        return formal_apply_eligibility_service.get_source_lineage(lineage_id)
    except StorageError as exc:
        _raise_http(exc)
