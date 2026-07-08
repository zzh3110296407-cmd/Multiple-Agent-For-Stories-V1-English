from typing import Any, Optional

from pydantic import BaseModel, Field, validator


PHASE85B_M5_VERSION_ID = "phase85b_m5_tiered_memory_retrieval_promotion_v1"

USAGE_RECORD_STATUSES = {"active", "blocked", "superseded"}
PROMOTION_CANDIDATE_STATUSES = {
    "pending",
    "promoted",
    "blocked",
    "rejected",
    "superseded",
}
PROMOTION_DECISION_TYPES = {
    "auto_promote_reference",
    "recommend_promotion",
    "block_promotion",
    "reject_promotion",
}
PROMOTION_BLOCK_REASONS = {
    "none",
    "inactive_memory_status",
    "forbidden_or_conflict_context",
    "unselected_character_memory",
    "unstable_source_identity",
}


class TieredMemoryRetrievalPolicy(BaseModel):
    policy_id: str = "phase85b_m5_default_policy"
    project_id: str = "local_project"
    version_id: str = PHASE85B_M5_VERSION_ID
    active_memory_statuses: list[str] = Field(default_factory=lambda: ["active"])
    blocked_memory_statuses: list[str] = Field(
        default_factory=lambda: ["provisional", "superseded", "rejected"]
    )
    high_importance_threshold: int = 1
    default_threshold: int = 2
    normal_context_buckets: list[str] = Field(
        default_factory=lambda: [
            "must_use_context",
            "should_use_context",
            "optional_context",
        ]
    )
    forbidden_context_bucket: str = "forbidden_or_conflict_context"
    reference_only_promotion: bool = True
    created_at: str = ""
    updated_at: str = ""

    @validator("high_importance_threshold", "default_threshold")
    def threshold_must_be_positive(cls, value: int) -> int:
        return max(1, int(value or 1))


class MemoryCanonicalKey(BaseModel):
    canonical_key: str
    memory_id: str = ""
    source_object_type: str = ""
    source_object_id: str = ""
    memory_type: str = ""
    stable: bool = True
    strategy: str = ""
    version_id: str = PHASE85B_M5_VERSION_ID


class MemoryRetrievalUsageRecord(BaseModel):
    usage_record_id: str
    project_id: str = "local_project"
    chapter_id: str
    canonical_key: str
    memory_id: str = ""
    source_object_type: str = ""
    source_object_id: str = ""
    memory_type: str = "event"
    status: str = "active"
    importance: str = "medium"
    safe_summary: str = ""
    scene_id: str = ""
    scene_index: int = 0
    retrieved_by: str = "SceneMemoryService"
    retrieval_reason: str = "scene_pack_build"
    source_scene_keys: list[str] = Field(default_factory=list)
    retrieval_count_in_chapter: int = 0
    context_buckets_seen: list[str] = Field(default_factory=list)
    matched_by: list[str] = Field(default_factory=list)
    active_character_ids_at_retrieval: list[str] = Field(default_factory=list)
    related_character_ids: list[str] = Field(default_factory=list)
    memory_status: str = "active"
    memory_importance: str = "medium"
    blocked_from_normal_promotion: bool = False
    block_reason: str = "none"
    promoted_to_chapter_pack: bool = False
    promotion_candidate_id: str = ""
    promoted_at: str = ""
    first_retrieved_at: str = ""
    last_retrieved_at: str = ""
    version_id: str = PHASE85B_M5_VERSION_ID

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        return value if value in USAGE_RECORD_STATUSES else "active"

    @validator("block_reason")
    def block_reason_must_be_known(cls, value: str) -> str:
        return value if value in PROMOTION_BLOCK_REASONS else "none"


class ChapterMemoryPromotionCandidate(BaseModel):
    promotion_candidate_id: str
    project_id: str = "local_project"
    chapter_id: str
    usage_record_id: str
    canonical_key: str
    memory_id: str = ""
    source_object_type: str = ""
    source_object_id: str = ""
    memory_type: str = "event"
    status: str = "pending"
    retrieval_count_in_chapter: int = 0
    threshold: int = 2
    target_context_bucket: str = "event_context"
    safe_summary: str = ""
    block_reason: str = "none"
    promoted_chapter_memory_pack_id: str = ""
    reference_only: bool = True
    creates_new_fact: bool = False
    created_at: str = ""
    updated_at: str = ""
    version_id: str = PHASE85B_M5_VERSION_ID

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        return value if value in PROMOTION_CANDIDATE_STATUSES else "pending"

    @validator("block_reason")
    def block_reason_must_be_known(cls, value: str) -> str:
        return value if value in PROMOTION_BLOCK_REASONS else "none"


class ChapterMemoryPromotionDecision(BaseModel):
    promotion_decision_id: str
    project_id: str = "local_project"
    chapter_id: str
    promotion_candidate_id: str
    usage_record_id: str
    decision_type: str
    decision_status: str = "recorded"
    reason: str = ""
    target_chapter_memory_pack_id: str = ""
    created_at: str = ""
    version_id: str = PHASE85B_M5_VERSION_ID

    @validator("decision_type")
    def decision_type_must_be_known(cls, value: str) -> str:
        return value if value in PROMOTION_DECISION_TYPES else "block_promotion"


class ChapterMemoryPromotionReport(BaseModel):
    promotion_report_id: str
    project_id: str = "local_project"
    chapter_id: str
    evaluated_at: str
    usage_record_count: int = 0
    promoted_candidate_count: int = 0
    blocked_candidate_count: int = 0
    already_promoted_count: int = 0
    promoted_memory_ids: list[str] = Field(default_factory=list)
    blocked_memory_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    version_id: str = PHASE85B_M5_VERSION_ID


class MemoryRetrievalUsageListResponse(BaseModel):
    usage_records: list[MemoryRetrievalUsageRecord] = Field(default_factory=list)
    count: int = 0


class ChapterMemoryPromotionCandidateListResponse(BaseModel):
    promotion_candidates: list[ChapterMemoryPromotionCandidate] = Field(default_factory=list)
    count: int = 0


class ChapterMemoryPromotionReportResponse(BaseModel):
    promotion_report: Optional[ChapterMemoryPromotionReport] = None


class TieredMemoryRetrievalPolicyResponse(BaseModel):
    policy: TieredMemoryRetrievalPolicy


class EvaluateChapterMemoryPromotionsResponse(BaseModel):
    success: bool = True
    promotion_report: ChapterMemoryPromotionReport
    promotion_candidates: list[ChapterMemoryPromotionCandidate] = Field(default_factory=list)
    decisions: list[ChapterMemoryPromotionDecision] = Field(default_factory=list)
