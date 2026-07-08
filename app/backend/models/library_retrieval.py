from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, validator


TEXT_RETRIEVAL_MODES = ("EXACT", "ALIAS", "KEYWORD", "TAG", "FULL_TEXT")
PACK_TYPES = ("CHAPTER_MEMORY_PACK", "SCENE_MEMORY_PACK", "AGENT_CONTEXT_PACK")
SEMANTIC_RETRIEVAL_MODES = ("deferred", "optional_hook_only", "ready", "unsupported_in_this_slice")
CANONICAL_STATUS_VALUES = (
    "DRAFT",
    "CANDIDATE",
    "PROVISIONAL",
    "TEMPORARY_CONFIRMED",
    "CONFIRMED",
    "FORMAL_APPLIED",
    "SUPERSEDED",
    "REJECTED",
    "ARCHIVED",
    "DELETED",
)


class _StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"


class LibraryRetrievalScope(BaseModel):
    project_id: str
    storage_mode: str
    mapping_source: str = ""
    compatibility_selection_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class LibraryRetrievalFilters(_StrictBaseModel):
    entity_types: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    chapter_ids: list[str] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    location_ids: list[str] = Field(default_factory=list)
    framework_ids: list[str] = Field(default_factory=list)
    memory_lanes: list[str] = Field(default_factory=list)
    memory_ids: list[str] = Field(default_factory=list)
    visibility_statuses: list[str] = Field(default_factory=list)
    authority_levels: list[str] = Field(default_factory=list)

    @validator("*", pre=True)
    def normalize_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("filter fields must be string lists")
        return [str(item).strip() for item in value if str(item).strip()]


class LibraryRetrievalTaskSpecPayload(_StrictBaseModel):
    retrieval_task_id: str
    agent_role: str = ""
    task_type: str = ""
    query_text: str = ""
    filters: LibraryRetrievalFilters = Field(default_factory=LibraryRetrievalFilters)
    required_entity_refs: list[dict[str, Any]] = Field(default_factory=list)
    max_items: int = Field(20, ge=1, le=100)
    token_budget: int = Field(1200, ge=1, le=20000)
    status: str = "DRAFT"
    authority_level: str = "SYSTEM_CONFIRMED"
    source_refs: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @validator("retrieval_task_id")
    def retrieval_task_id_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("retrieval_task_id is required")
        return cleaned

    @validator("status")
    def status_must_be_canonical(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if cleaned not in CANONICAL_STATUS_VALUES:
            raise ValueError("status must be a canonical_status_value")
        return cleaned


class LibraryRetrievalTaskSpec(BaseModel):
    retrieval_task_id: str
    agent_role: str = ""
    task_type: str = ""
    query_text: str = ""
    filters: LibraryRetrievalFilters = Field(default_factory=LibraryRetrievalFilters)
    required_entity_refs: list[dict[str, Any]] = Field(default_factory=list)
    max_items: int = 20
    token_budget: int = 1200
    status: str = ""
    lifecycle_state: str = ""
    authority_level: str = ""
    source_refs: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LibraryRetrievalCandidate(BaseModel):
    candidate_id: str
    candidate_kind: str
    search_memory_card_id: str = ""
    search_document_id: str = ""
    entity_type: str = ""
    entity_business_id: str = ""
    source_type: str = ""
    title: str = ""
    text_summary: str = ""
    source_refs: list[Any] = Field(default_factory=list)
    access_label: str = "USABLE_NOW"
    visibility_status: str = ""
    authority_level: str = ""
    status: str = ""
    lifecycle_state: str = ""
    score: float = 0
    score_components: dict[str, float] = Field(default_factory=dict)
    token_estimate: int = 0
    explanation: str = ""
    m10_eligible: bool = True
    writer_agent_fact_ready: bool = False


class LibraryRetrievalSearchRequest(_StrictBaseModel):
    project_id: str = ""
    retrieval_task_id: str = ""
    task_spec: Optional[LibraryRetrievalTaskSpecPayload] = None
    filters: LibraryRetrievalFilters = Field(default_factory=LibraryRetrievalFilters)
    max_items: int = Field(20, ge=1, le=100)
    token_budget: int = Field(1200, ge=1, le=20000)
    include_cards: bool = True
    include_documents: bool = True


class LibraryTextRetrievalRequest(_StrictBaseModel):
    project_id: str = ""
    retrieval_task_id: str = ""
    query_text: str
    modes: list[str] = Field(default_factory=lambda: list(TEXT_RETRIEVAL_MODES))
    filters: LibraryRetrievalFilters = Field(default_factory=LibraryRetrievalFilters)
    max_items: int = Field(20, ge=1, le=100)
    token_budget: int = Field(1200, ge=1, le=20000)
    allow_full_text: bool = True

    @validator("query_text")
    def query_text_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("query_text is required")
        return cleaned

    @validator("modes", pre=True)
    def normalize_modes(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return list(TEXT_RETRIEVAL_MODES)
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("modes must be a string list")
        cleaned = [str(item).strip().upper() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("at least one retrieval mode is required")
        unknown = sorted(set(cleaned) - set(TEXT_RETRIEVAL_MODES))
        if unknown:
            raise ValueError(f"unknown retrieval mode: {unknown[0]}")
        return cleaned


class LibraryRelationshipExpansionRequest(_StrictBaseModel):
    project_id: str = ""
    retrieval_task_id: str = ""
    query_text: str
    modes: list[str] = Field(default_factory=lambda: list(TEXT_RETRIEVAL_MODES))
    filters: LibraryRetrievalFilters = Field(default_factory=LibraryRetrievalFilters)
    link_types: list[str] = Field(default_factory=list)
    max_graph_distance: int = Field(1, ge=0, le=1)
    max_items: int = Field(20, ge=1, le=100)
    token_budget: int = Field(1200, ge=1, le=20000)
    allow_full_text: bool = True

    @validator("query_text")
    def query_text_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("query_text is required")
        return cleaned

    @validator("modes", pre=True)
    def normalize_modes(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return list(TEXT_RETRIEVAL_MODES)
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("modes must be a string list")
        cleaned = [str(item).strip().upper() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("at least one retrieval mode is required")
        unknown = sorted(set(cleaned) - set(TEXT_RETRIEVAL_MODES))
        if unknown:
            raise ValueError(f"unknown retrieval mode: {unknown[0]}")
        return cleaned

    @validator("link_types", pre=True)
    def normalize_link_types(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("link_types must be a string list")
        return [str(item).strip().upper() for item in value if str(item).strip()]


class LibraryPackItemPayload(_StrictBaseModel):
    pack_item_id: str = ""
    search_document_id: str = ""
    memory_id: str = ""
    entity_type: str = ""
    entity_business_id: str = ""
    reason: str
    rank_score: float = 0
    token_estimate: int = Field(0, ge=0)
    required_for_generation: bool = False
    access_label: str = "USABLE_NOW"
    source_status: str = "DRAFT"
    source_refs: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @validator("reason")
    def reason_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("reason is required")
        return cleaned

    @validator("source_status")
    def source_status_must_be_canonical(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if not cleaned:
            return "DRAFT"
        if cleaned == "ACTIVE":
            return "CONFIRMED"
        if cleaned == "OPEN":
            return "CANDIDATE"
        if cleaned not in CANONICAL_STATUS_VALUES:
            raise ValueError("source_status must be a canonical_status_value")
        return cleaned


class LibraryPackBuildRequest(_StrictBaseModel):
    project_id: str = ""
    pack_type: str
    pack_id: str
    chapter_id: str = ""
    scene_id: str = ""
    agent_role: str = ""
    retrieval_task_id: str = ""
    pack_purpose: str = ""
    max_items: int = Field(60, ge=1, le=250)
    token_budget: int = Field(0, ge=0, le=20000)
    dependency_refs: list[Any] = Field(default_factory=list)
    dependency_hash: str = ""
    content_hash: str = ""
    items: list[LibraryPackItemPayload] = Field(default_factory=list)

    @validator("pack_type")
    def pack_type_allowed(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if cleaned not in PACK_TYPES:
            raise ValueError("pack_type must be CHAPTER_MEMORY_PACK, SCENE_MEMORY_PACK or AGENT_CONTEXT_PACK")
        return cleaned

    @validator("pack_id")
    def pack_id_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("pack_id is required")
        return cleaned


class LibraryPackStaleRequest(_StrictBaseModel):
    project_id: str = ""
    dependency_ref: dict[str, Any]
    stale_reason: str
    pack_types: list[str] = Field(default_factory=lambda: list(PACK_TYPES))

    @validator("stale_reason")
    def stale_reason_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("stale_reason is required")
        return cleaned

    @validator("pack_types", pre=True)
    def normalize_pack_types(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return list(PACK_TYPES)
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("pack_types must be a string list")
        cleaned = [str(item).strip().upper() for item in value if str(item).strip()]
        unknown = sorted(set(cleaned) - set(PACK_TYPES))
        if unknown:
            raise ValueError(f"unknown pack type: {unknown[0]}")
        return cleaned


class LibraryPackItem(BaseModel):
    pack_item_id: str
    entity_type: str = ""
    entity_business_id: str = ""
    reason: str = ""
    rank_score: float = 0
    token_estimate: int = 0
    required_for_generation: bool = False
    access_label: str = "USABLE_NOW"
    source_status: str = ""
    source_refs: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LibraryPack(BaseModel):
    scope: LibraryRetrievalScope
    pack_type: str
    pack_id: str
    chapter_id: str = ""
    scene_id: str = ""
    agent_role: str = ""
    pack_purpose: str = ""
    max_items: int = 0
    token_budget: int = 0
    dependency_refs: list[Any] = Field(default_factory=list)
    dependency_hash: str = ""
    freshness_status: str = ""
    invalidated_reason: str = ""
    version: int = 1
    revision: int = 1
    content_hash: str = ""
    items: list[LibraryPackItem] = Field(default_factory=list)


class LibraryPackStaleResponse(BaseModel):
    scope: LibraryRetrievalScope
    dependency_ref: dict[str, Any]
    stale_reason: str
    stale_pack_count: int
    rebuilt_pack_count: int = 0
    pack_types: list[str] = Field(default_factory=list)


class LibraryRetrievalUsageLogRequest(_StrictBaseModel):
    project_id: str = ""
    retrieval_usage_id: str
    retrieval_task_id: str = ""
    pack_type: str = ""
    pack_id: str = ""
    query_text: str = ""
    candidate_count: int = Field(0, ge=0)
    selected_count: int = Field(0, ge=0)
    used_entity_refs: list[Any] = Field(default_factory=list)
    ignored_entity_refs: list[Any] = Field(default_factory=list)
    missing_requirements: list[Any] = Field(default_factory=list)
    latency_ms: int = Field(0, ge=0)
    token_estimate: int = Field(0, ge=0)
    source_refs: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @validator("retrieval_usage_id")
    def retrieval_usage_id_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("retrieval_usage_id is required")
        return cleaned


class LibraryRetrievalGapRequest(_StrictBaseModel):
    project_id: str = ""
    retrieval_gap_id: str
    retrieval_task_id: str = ""
    scene_id: str = ""
    gap_type: str
    claim_text: str = ""
    searched_scopes: list[Any] = Field(default_factory=list)
    recommended_resolution: str = ""
    prose_fallback_accepted: bool = False
    source_refs: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @validator("retrieval_gap_id")
    def retrieval_gap_id_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("retrieval_gap_id is required")
        return cleaned

    @validator("gap_type")
    def gap_type_required(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if not cleaned:
            raise ValueError("gap_type is required")
        return cleaned


class LibraryRetrievalUsageRecord(BaseModel):
    scope: LibraryRetrievalScope
    retrieval_usage_id: str
    candidate_count: int
    selected_count: int
    ignored_entity_refs: list[Any] = Field(default_factory=list)
    missing_requirements: list[Any] = Field(default_factory=list)
    latency_ms: int = 0
    token_estimate: int = 0


class LibraryRetrievalGapRecord(BaseModel):
    scope: LibraryRetrievalScope
    retrieval_gap_id: str
    gap_type: str
    claim_text: str = ""
    searched_scopes: list[Any] = Field(default_factory=list)
    recommended_resolution: str = ""
    warning: str = ""


class LibrarySemanticRetrievalBoundary(BaseModel):
    semantic_retrieval_mode: str = "optional_hook_only"
    allowed_modes: list[str] = Field(default_factory=lambda: list(SEMANTIC_RETRIEVAL_MODES))
    embedding_ref_storage: str = "search_documents.metadata.embedding_ref/search_memory_cards.metadata.embedding_ref"
    production_pgvector_required_for_m11_pass: bool = False
    semantic_score_can_override_hard_gates: bool = False
    semantic_hook_ready: bool = False
    warning: str = "M11 semantic hook is optional metadata only; M10/M12 hard gates remain authoritative."


class LibraryRetrievalSearchResponse(BaseModel):
    scope: LibraryRetrievalScope
    retrieval_task_id: str = ""
    effective_max_items: int
    effective_token_budget: int
    candidate_count: int
    total_token_estimate: int
    truncated_by_max_items: bool = False
    truncated_by_token_budget: bool = False
    candidates: list[LibraryRetrievalCandidate] = Field(default_factory=list)
    filters_applied: list[str] = Field(default_factory=list)
    retrieval_modes: list[str] = Field(default_factory=list)
    full_text_mode: str = ""
    gaps: list[str] = Field(default_factory=list)
