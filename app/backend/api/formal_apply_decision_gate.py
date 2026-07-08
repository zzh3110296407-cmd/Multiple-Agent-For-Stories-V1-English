from fastapi import APIRouter, HTTPException

from ..models.formal_apply_decision import (
    FormalApplyApprovalRecordListResponse,
    FormalApplyDecision,
    FormalApplyDecisionEvidenceSnapshot,
    FormalApplyDecisionGateResult,
    FormalApplyDecisionListResponse,
    FormalApplyDecisionReadinessResult,
    FormalApplyDecisionStatusResponse,
    FormalApplyDecisionSubmitRequest,
    FormalApplyQuestion,
    FormalApplyQuestionAnswerRequest,
    FormalApplyQuestionListResponse,
    FormalApplyRejectionRecordListResponse,
    FormalApplyUserOverrideListResponse,
)
from ..services.formal_apply_decision_gate_service import FormalApplyDecisionGateService
from ..storage.json_store import StorageError


router = APIRouter()
formal_apply_decision_gate_service = FormalApplyDecisionGateService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=FormalApplyDecisionStatusResponse)
def get_formal_apply_decision_status() -> FormalApplyDecisionStatusResponse:
    try:
        return formal_apply_decision_gate_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/plans/{plan_id}/readiness", response_model=FormalApplyDecisionReadinessResult)
def get_formal_apply_decision_readiness(plan_id: str) -> FormalApplyDecisionReadinessResult:
    try:
        return formal_apply_decision_gate_service.get_plan_readiness(plan_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/plans/{plan_id}/decisions", response_model=FormalApplyDecisionGateResult)
def submit_formal_apply_decision(
    plan_id: str,
    request: FormalApplyDecisionSubmitRequest,
) -> FormalApplyDecisionGateResult:
    try:
        return formal_apply_decision_gate_service.submit_decision(plan_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/decisions", response_model=FormalApplyDecisionListResponse)
def list_formal_apply_decisions() -> FormalApplyDecisionListResponse:
    try:
        return formal_apply_decision_gate_service.list_decisions()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/decisions/{decision_record_id}", response_model=FormalApplyDecision)
def get_formal_apply_decision(decision_record_id: str) -> FormalApplyDecision:
    try:
        return formal_apply_decision_gate_service.get_decision(decision_record_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get(
    "/decisions/{decision_record_id}/evidence-snapshot",
    response_model=FormalApplyDecisionEvidenceSnapshot,
)
def get_formal_apply_decision_evidence_snapshot(
    decision_record_id: str,
) -> FormalApplyDecisionEvidenceSnapshot:
    try:
        return formal_apply_decision_gate_service.get_evidence_snapshot(decision_record_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/approvals", response_model=FormalApplyApprovalRecordListResponse)
def list_formal_apply_approvals() -> FormalApplyApprovalRecordListResponse:
    try:
        return formal_apply_decision_gate_service.list_approvals()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/rejections", response_model=FormalApplyRejectionRecordListResponse)
def list_formal_apply_rejections() -> FormalApplyRejectionRecordListResponse:
    try:
        return formal_apply_decision_gate_service.list_rejections()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/overrides", response_model=FormalApplyUserOverrideListResponse)
def list_formal_apply_overrides() -> FormalApplyUserOverrideListResponse:
    try:
        return formal_apply_decision_gate_service.list_overrides()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/questions", response_model=FormalApplyQuestionListResponse)
def list_formal_apply_questions() -> FormalApplyQuestionListResponse:
    try:
        return formal_apply_decision_gate_service.list_questions()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/questions/{question_id}", response_model=FormalApplyQuestion)
def get_formal_apply_question(question_id: str) -> FormalApplyQuestion:
    try:
        return formal_apply_decision_gate_service.get_question(question_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/questions/{question_id}/answer", response_model=FormalApplyQuestion)
def answer_formal_apply_question(
    question_id: str,
    request: FormalApplyQuestionAnswerRequest,
) -> FormalApplyQuestion:
    try:
        return formal_apply_decision_gate_service.answer_question(question_id, request)
    except StorageError as exc:
        _raise_http(exc)
