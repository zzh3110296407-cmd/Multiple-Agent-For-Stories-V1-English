from fastapi import APIRouter, HTTPException, Query

from app.backend.models.pre_modify import (
    PreModifyAdjustmentPlanResponse,
    PreModifyCandidateListResponse,
    PreModifyCandidateResponse,
    PreModifyFromPreviewRequest,
    PreModifyImpactReasonResponse,
    PreModifyPipelineResult,
    PreModifySummaryResponse,
)
from app.backend.models.pre_modify_workspace import (
    CandidateAcceptRequest,
    CandidateApplyPlan,
    CandidateApplyPlanRequest,
    CandidateApplyResult,
    CandidateDeferRequest,
    CandidateRejectRequest,
    CandidateReviseRequest,
    PreModifyWorkspaceState,
)
from app.backend.services.pre_modify_pipeline_service import PreModifyPipelineService
from app.backend.services.pre_modify_workspace_service import PreModifyWorkspaceService
from app.backend.storage.json_store import StorageError


router = APIRouter()
pre_modify_service = PreModifyPipelineService()
pre_modify_workspace_service = PreModifyWorkspaceService(pre_modify_service=pre_modify_service)


def _error_detail(message: str) -> dict[str, str]:
    code, _, detail = message.partition(":")
    return {
        "error_code": code,
        "message": detail.strip() or "Pre modify request failed safely.",
    }


def _raise_pre_modify_error(exc: StorageError) -> None:
    message = str(exc)
    detail = _error_detail(message)
    code = detail["error_code"]
    if code in {
        "PRE_MODIFY_PREVIEW_NOT_FOUND",
        "PRE_MODIFY_CANDIDATE_NOT_FOUND",
        "PRE_MODIFY_PLAN_NOT_FOUND",
        "PRE_MODIFY_REASON_NOT_FOUND",
    }:
        raise HTTPException(status_code=404, detail=detail) from exc
    if code == "PRE_MODIFY_VALIDATION_ERROR":
        raise HTTPException(status_code=400, detail=detail) from exc
    if code == "PRE_MODIFY_UNSAFE_PAYLOAD_BLOCKED":
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": code,
                "message": "Pre modify payload failed the safety scan.",
            },
        ) from exc
    if code.startswith("PRE_MODIFY_WORKSPACE_"):
        status_code = 500
        if "NOT_FOUND" in code or code.endswith("_MISSING"):
            status_code = 404
        if (
            code.endswith("_REQUIRED")
            or code.endswith("_INVALID")
            or "SCHEMA_INVALID" in code
            or "CACHE_MISMATCH" in code
        ):
            status_code = 400
        if "UNSAFE_PAYLOAD_BLOCKED" in code:
            status_code = 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    if code == "PRE_MODIFY_SCHEMA_INVALID" or "schema is invalid" in message:
        raise HTTPException(status_code=400, detail=detail) from exc
    raise HTTPException(
        status_code=500,
        detail={
            "error_code": "PRE_MODIFY_INTERNAL_ERROR",
            "message": "Pre modify request failed safely.",
        },
    ) from exc


@router.post("/candidates/from-preview", response_model=PreModifyPipelineResult)
def create_pre_modify_candidates_from_preview(
    request: PreModifyFromPreviewRequest,
) -> PreModifyPipelineResult:
    try:
        return pre_modify_service.create_candidates_from_preview(request)
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.get("/candidates", response_model=PreModifyCandidateListResponse)
def list_pre_modify_candidates(
    status: str | None = Query(default=None),
    source_preview_id: str | None = Query(default=None),
    target_scene_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> PreModifyCandidateListResponse:
    try:
        candidates = pre_modify_service.list_candidates(
            status=status,
            source_preview_id=source_preview_id,
            target_scene_id=target_scene_id,
            limit=limit,
        )
        return PreModifyCandidateListResponse(candidates=candidates, count=len(candidates))
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.get("/summary", response_model=PreModifySummaryResponse)
def get_pre_modify_summary(
    source_preview_id: str | None = Query(default=None),
    target_scene_id: str | None = Query(default=None),
) -> PreModifySummaryResponse:
    try:
        return pre_modify_service.summary(
            source_preview_id=source_preview_id,
            target_scene_id=target_scene_id,
        )
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.get("/workspace", response_model=PreModifyWorkspaceState)
def get_pre_modify_workspace(
    scene_id: str | None = Query(default=None),
    chapter_id: str | None = Query(default=None),
    include_stale: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
) -> PreModifyWorkspaceState:
    try:
        return pre_modify_workspace_service.workspace_state(
            scene_id=scene_id or "",
            chapter_id=chapter_id or "",
            include_stale=include_stale,
            limit=limit,
        )
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.post("/candidates/{candidate_id}/apply-plan", response_model=CandidateApplyPlan)
def build_pre_modify_apply_plan(
    candidate_id: str,
    request: CandidateApplyPlanRequest | None = None,
) -> CandidateApplyPlan:
    try:
        normalized = request or CandidateApplyPlanRequest()
        return pre_modify_workspace_service.build_apply_plan(
            candidate_id,
            cached_candidate_id=normalized.cached_candidate_id,
            force_refresh=normalized.force_refresh,
        )
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.post("/candidates/{candidate_id}/accept", response_model=CandidateApplyResult)
def accept_pre_modify_candidate(
    candidate_id: str,
    request: CandidateAcceptRequest | None = None,
) -> CandidateApplyResult:
    try:
        return pre_modify_workspace_service.accept_candidate(candidate_id, request)
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.post("/candidates/{candidate_id}/reject", response_model=CandidateApplyResult)
def reject_pre_modify_candidate(
    candidate_id: str,
    request: CandidateRejectRequest | None = None,
) -> CandidateApplyResult:
    try:
        return pre_modify_workspace_service.reject_candidate(candidate_id, request)
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.post("/candidates/{candidate_id}/revise", response_model=CandidateApplyResult)
def revise_pre_modify_candidate(
    candidate_id: str,
    request: CandidateReviseRequest,
) -> CandidateApplyResult:
    try:
        return pre_modify_workspace_service.revise_candidate(candidate_id, request)
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.post("/candidates/{candidate_id}/defer", response_model=CandidateApplyResult)
def defer_pre_modify_candidate(
    candidate_id: str,
    request: CandidateDeferRequest | None = None,
) -> CandidateApplyResult:
    try:
        return pre_modify_workspace_service.defer_candidate(candidate_id, request)
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.get("/adjustment-plans/{plan_id}", response_model=PreModifyAdjustmentPlanResponse)
def get_pre_modify_adjustment_plan(plan_id: str) -> PreModifyAdjustmentPlanResponse:
    try:
        return PreModifyAdjustmentPlanResponse(
            plan=pre_modify_service.get_adjustment_plan(plan_id)
        )
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.get("/impact-reasons/{reason_id}", response_model=PreModifyImpactReasonResponse)
def get_pre_modify_impact_reason(reason_id: str) -> PreModifyImpactReasonResponse:
    try:
        return PreModifyImpactReasonResponse(
            reason=pre_modify_service.get_impact_reason(reason_id)
        )
    except StorageError as exc:
        _raise_pre_modify_error(exc)


@router.get("/candidates/{candidate_id}", response_model=PreModifyCandidateResponse)
def get_pre_modify_candidate(candidate_id: str) -> PreModifyCandidateResponse:
    try:
        return PreModifyCandidateResponse(
            candidate=pre_modify_service.get_candidate(candidate_id)
        )
    except StorageError as exc:
        _raise_pre_modify_error(exc)
