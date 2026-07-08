from fastapi import APIRouter, HTTPException

from ..models.recommendation_governance import (
    LibraryPromotionDecision,
    LibraryPromotionDecisionListResponse,
    RecommendationEligibilityReport,
    RecommendationEligibilityReportListResponse,
    RecommendationEvaluateRequest,
    RecommendationEvaluationResult,
    RecommendationGovernanceStatusResponse,
    RecommendationOpenReviewRequest,
    RecommendationReviewActionRequest,
    RecommendationReviewActionResult,
    RecommendationRiskProfile,
    RecommendationRiskProfileListResponse,
    SystemRecommendationCandidateReview,
    SystemRecommendationCandidateReviewListResponse,
)
from ..services.recommendation_governance_service import RecommendationGovernanceService
from ..storage.json_store import StorageError


router = APIRouter()
recommendation_governance_service = RecommendationGovernanceService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if (
        "BLOCKED" in message
        or "DUPLICATE" in message
        or "FORBIDDEN_STORAGE_MUTATION" in message
    ):
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=RecommendationGovernanceStatusResponse)
def get_recommendation_governance_status() -> RecommendationGovernanceStatusResponse:
    try:
        return recommendation_governance_service.get_status()
    except StorageError as exc:
        _raise_http(exc)


@router.post("/evaluate", response_model=RecommendationEvaluationResult)
def evaluate_recommendation_eligibility(
    request: RecommendationEvaluateRequest,
) -> RecommendationEvaluationResult:
    try:
        return recommendation_governance_service.evaluate(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/eligibility-reports", response_model=RecommendationEligibilityReportListResponse)
def list_recommendation_eligibility_reports() -> RecommendationEligibilityReportListResponse:
    try:
        return recommendation_governance_service.list_eligibility_reports()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/eligibility-reports/{report_id}", response_model=RecommendationEligibilityReport)
def get_recommendation_eligibility_report(report_id: str) -> RecommendationEligibilityReport:
    try:
        return recommendation_governance_service.get_eligibility_report(report_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/reviews", response_model=SystemRecommendationCandidateReview)
def open_recommendation_review(
    request: RecommendationOpenReviewRequest,
) -> SystemRecommendationCandidateReview:
    try:
        return recommendation_governance_service.open_review(request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reviews", response_model=SystemRecommendationCandidateReviewListResponse)
def list_recommendation_reviews() -> SystemRecommendationCandidateReviewListResponse:
    try:
        return recommendation_governance_service.list_reviews()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/reviews/{review_id}", response_model=SystemRecommendationCandidateReview)
def get_recommendation_review(review_id: str) -> SystemRecommendationCandidateReview:
    try:
        return recommendation_governance_service.get_review(review_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/reviews/{review_id}/approve-candidate", response_model=RecommendationReviewActionResult)
def approve_recommendation_candidate(
    review_id: str,
    request: RecommendationReviewActionRequest,
) -> RecommendationReviewActionResult:
    try:
        return recommendation_governance_service.approve_candidate(review_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/reviews/{review_id}/reject", response_model=RecommendationReviewActionResult)
def reject_recommendation_review(
    review_id: str,
    request: RecommendationReviewActionRequest,
) -> RecommendationReviewActionResult:
    try:
        return recommendation_governance_service.reject_review(review_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/reviews/{review_id}/request-more-evidence", response_model=RecommendationReviewActionResult)
def request_recommendation_more_evidence(
    review_id: str,
    request: RecommendationReviewActionRequest,
) -> RecommendationReviewActionResult:
    try:
        return recommendation_governance_service.request_more_evidence(review_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/reviews/{review_id}/keep-private", response_model=RecommendationReviewActionResult)
def keep_recommendation_private(
    review_id: str,
    request: RecommendationReviewActionRequest,
) -> RecommendationReviewActionResult:
    try:
        return recommendation_governance_service.keep_private(review_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/reviews/{review_id}/keep-project-local", response_model=RecommendationReviewActionResult)
def keep_recommendation_project_local(
    review_id: str,
    request: RecommendationReviewActionRequest,
) -> RecommendationReviewActionResult:
    try:
        return recommendation_governance_service.keep_project_local(review_id, request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/risk-profiles", response_model=RecommendationRiskProfileListResponse)
def list_recommendation_risk_profiles() -> RecommendationRiskProfileListResponse:
    try:
        return recommendation_governance_service.list_risk_profiles()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/risk-profiles/{risk_profile_id}", response_model=RecommendationRiskProfile)
def get_recommendation_risk_profile(risk_profile_id: str) -> RecommendationRiskProfile:
    try:
        return recommendation_governance_service.get_risk_profile(risk_profile_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/promotion-decisions", response_model=LibraryPromotionDecisionListResponse)
def list_recommendation_promotion_decisions() -> LibraryPromotionDecisionListResponse:
    try:
        return recommendation_governance_service.list_promotion_decisions()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/promotion-decisions/{decision_id}", response_model=LibraryPromotionDecision)
def get_recommendation_promotion_decision(decision_id: str) -> LibraryPromotionDecision:
    try:
        return recommendation_governance_service.get_promotion_decision(decision_id)
    except StorageError as exc:
        _raise_http(exc)
