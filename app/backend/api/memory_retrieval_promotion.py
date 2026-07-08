from fastapi import APIRouter, HTTPException, Query

from app.backend.models.memory_retrieval_promotion import (
    ChapterMemoryPromotionCandidateListResponse,
    ChapterMemoryPromotionReportResponse,
    EvaluateChapterMemoryPromotionsResponse,
    MemoryRetrievalUsageListResponse,
    MemoryRetrievalUsageRecord,
    TieredMemoryRetrievalPolicyResponse,
)
from app.backend.services.memory_retrieval_promotion_service import (
    ChapterMemoryPromotionService,
    TieredMemoryRetrievalPolicyService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
promotion_service = ChapterMemoryPromotionService()
policy_service = TieredMemoryRetrievalPolicyService(
    store=promotion_service.store,
    data_dir=promotion_service.data_dir,
)


@router.get("/usage", response_model=MemoryRetrievalUsageListResponse)
def list_memory_retrieval_usage(
    chapter_id: str | None = Query(default=None),
) -> MemoryRetrievalUsageListResponse:
    try:
        records = promotion_service.usage_service.list_usage(chapter_id)
    except StorageError as exc:
        raise _memory_retrieval_error(exc) from exc
    return MemoryRetrievalUsageListResponse(usage_records=records, count=len(records))


@router.get("/usage/{usage_record_id}", response_model=MemoryRetrievalUsageRecord)
def get_memory_retrieval_usage(
    usage_record_id: str,
) -> MemoryRetrievalUsageRecord:
    try:
        record = promotion_service.usage_service.get_usage_record(usage_record_id)
    except StorageError as exc:
        raise _memory_retrieval_error(exc) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="MemoryRetrievalUsageRecord was not found.")
    return record


@router.post(
    "/chapters/{chapter_id}/evaluate-promotions",
    response_model=EvaluateChapterMemoryPromotionsResponse,
)
def evaluate_chapter_memory_promotions(
    chapter_id: str,
) -> EvaluateChapterMemoryPromotionsResponse:
    try:
        report, candidates, decisions = promotion_service.evaluate_chapter_promotions(
            chapter_id
        )
    except StorageError as exc:
        raise _memory_retrieval_error(exc) from exc
    return EvaluateChapterMemoryPromotionsResponse(
        promotion_report=report,
        promotion_candidates=candidates,
        decisions=decisions,
    )


@router.get(
    "/chapters/{chapter_id}/promotion-candidates",
    response_model=ChapterMemoryPromotionCandidateListResponse,
)
def list_chapter_memory_promotion_candidates(
    chapter_id: str,
) -> ChapterMemoryPromotionCandidateListResponse:
    try:
        candidates = promotion_service.list_candidates(chapter_id)
    except StorageError as exc:
        raise _memory_retrieval_error(exc) from exc
    return ChapterMemoryPromotionCandidateListResponse(
        promotion_candidates=candidates,
        count=len(candidates),
    )


@router.get(
    "/chapters/{chapter_id}/promotion-report",
    response_model=ChapterMemoryPromotionReportResponse,
)
def get_chapter_memory_promotion_report(
    chapter_id: str,
) -> ChapterMemoryPromotionReportResponse:
    try:
        report = promotion_service.get_latest_report(chapter_id)
    except StorageError as exc:
        raise _memory_retrieval_error(exc) from exc
    if report is None:
        raise HTTPException(status_code=404, detail="ChapterMemoryPromotionReport was not found.")
    return ChapterMemoryPromotionReportResponse(promotion_report=report)


@router.get("/policy", response_model=TieredMemoryRetrievalPolicyResponse)
def get_tiered_memory_retrieval_policy() -> TieredMemoryRetrievalPolicyResponse:
    try:
        policy = policy_service.get_policy()
    except StorageError as exc:
        raise _memory_retrieval_error(exc) from exc
    return TieredMemoryRetrievalPolicyResponse(policy=policy)


def _memory_retrieval_error(exc: StorageError) -> HTTPException:
    message = str(exc)
    if "MISSING" in message or "does not exist" in message or "not found" in message:
        return HTTPException(status_code=404, detail=message)
    if "REQUIRED" in message or "INVALID" in message:
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)
