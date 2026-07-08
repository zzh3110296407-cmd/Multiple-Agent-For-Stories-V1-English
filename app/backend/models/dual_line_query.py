from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field, root_validator, validator


REQUIRED_QUERY_MODES = (
    "SCENE_GENERATION",
    "SIMILARITY_EXPLORATION",
    "CONTINUITY_QUALITY_CHECK",
    "CHAPTER_PLANNING",
    "AGENT_CONTEXT_BUILD",
)

MINIMUM_QUERY_INTENT_FIELDS = (
    "project_id",
    "query_intent_id",
    "query_mode",
    "agent_role",
    "chapter_id",
    "scene_id",
    "narrative_time_ref",
    "world_time_ref",
    "knowledge_time_ref",
    "timeline_id",
    "characters",
    "locations",
    "scene_function",
    "required_entity_refs",
    "retrieval_task_id",
    "max_items",
    "token_budget",
    "debug_or_expert_mode",
    "source_refs",
)

PLANNER_LAYER_NAMES = (
    "hard_context",
    "temporal_state",
    "semantic_supplement",
    "forbidden_audit_layer",
)

WRITER_AGENT_DIRECT_FORBIDDEN_LABELS = (
    "AUTHOR_ONLY",
    "CHARACTER_UNKNOWN",
    "READER_FORBIDDEN",
    "FUTURE_INFO",
    "SUPERSEDED",
    "WRONG_TIMELINE",
)

ACCESS_LABELS = (
    "USABLE_NOW",
    "AUTHOR_ONLY",
    "CHARACTER_UNKNOWN",
    "READER_FORBIDDEN",
    "FUTURE_INFO",
    "CANDIDATE_ONLY",
    "SUPERSEDED",
    "CONFLICT_RISK",
    "WRONG_TIMELINE",
)

WRITER_SAFE_AUTHORITY_LEVELS = (
    "USER_LOCKED",
    "USER_CONFIRMED",
    "FORMAL_APPLIED",
    "SYSTEM_CONFIRMED",
)

USABLE_VISIBILITY_STATUSES = ("", "KNOWN", "RESTORED")
CANDIDATE_FUSION_BUCKETS = ("USABLE", "MAY_USE", "AVOID_REVEALING", "AUDIT_ONLY")
WRITE_AGENT_CONTEXT_PACK_SECTIONS = (
    "must_use",
    "may_use",
    "avoid_revealing",
    "character_visible_memory",
    "location_current_state",
    "location_change_delta",
    "style_and_framework_guidance",
    "continuity_warnings",
    "source_refs",
)
AGENT_CONTEXT_PACK_TYPES = (
    "MemoryCuratorContextPack",
    "ChapterAgentContextPack",
    "SceneAgentContextPack",
    "CharacterAgentContextPack",
    "ContinuityAgentContextPack",
    "WriteAgentContextPack",
)
RUNTIME_AGENT_CONTEXT_CONSUMERS = (
    "Memory Curator",
    "Chapter Agent",
    "Scene Agent",
    "Character Agent",
    "Continuity Agent",
    "Write Agent context package assembly",
)
RUNTIME_AGENT_REQUIRED_SECTIONS = {
    "Memory Curator": ("must_use", "character_visible_memory", "source_refs"),
    "Chapter Agent": ("must_use", "may_use", "style_and_framework_guidance", "source_refs"),
    "Scene Agent": ("location_current_state", "location_change_delta", "source_refs"),
    "Character Agent": ("character_visible_memory", "source_refs"),
    "Continuity Agent": ("avoid_revealing", "continuity_warnings", "source_refs"),
    "Write Agent context package assembly": (
        "must_use",
        "may_use",
        "avoid_revealing",
        "character_visible_memory",
        "location_current_state",
        "location_change_delta",
        "style_and_framework_guidance",
        "continuity_warnings",
        "source_refs",
    ),
}
CONTEXT_CACHE_TYPES = (
    "SceneContextCache",
    "TimelineHeadCache",
    "CharacterVisibleMemoryCache",
    "LibraryQueryCache",
    "ContextPackBuildFreshness",
)
CONTEXT_CACHE_INVALIDATION_TRIGGERS = (
    "memory_node_change",
    "location_state_versioned_insert",
    "location_change_delta_recompute",
    "relationship_change",
    "framework_component_change",
    "accepted_scene_output_or_formal_apply_writeback",
    "pack_stale_api_call",
    "superseded_timeline_node",
)

QUERY_ORCHESTRATION_STAGE_NAMES = (
    "query_intent",
    "temporal_resolver",
    "library_retriever",
    "candidate_fusion",
    "authority_visibility_gate",
    "context_pack_build",
    "agent_consumption_target",
)


class _StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"


def _clean_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("value must be a string list")
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_agent_role(value: str) -> str:
    return str(value or "").strip().replace("-", "_").replace(" ", "_").upper()


class DualLineQueryIntent(_StrictBaseModel):
    project_id: str
    query_intent_id: str
    query_mode: str
    agent_role: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    narrative_time_ref: str = ""
    world_time_ref: str = ""
    knowledge_time_ref: str = ""
    timeline_id: str = ""
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    scene_function: list[str] = Field(default_factory=list)
    required_entity_refs: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_task_id: str = ""
    max_items: int = Field(20, ge=1, le=100)
    token_budget: int = Field(1200, ge=1, le=20000)
    debug_or_expert_mode: bool = False
    source_refs: list[Any] = Field(default_factory=list)
    requires_character_visible_memory: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @validator("project_id", "query_intent_id")
    def required_id_must_not_be_empty(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("required id field must not be empty")
        return cleaned

    @validator("query_mode")
    def query_mode_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if cleaned not in REQUIRED_QUERY_MODES:
            raise ValueError("query_mode is not supported")
        return cleaned

    @validator(
        "agent_role",
        "chapter_id",
        "scene_id",
        "narrative_time_ref",
        "world_time_ref",
        "knowledge_time_ref",
        "timeline_id",
        "retrieval_task_id",
        pre=True,
        always=True,
    )
    def normalize_optional_string(cls, value: Any) -> str:
        return str(value or "").strip()

    @validator("characters", "locations", "scene_function", pre=True)
    def normalize_string_list(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @root_validator(skip_on_failure=True)
    def enforce_time_axis_contract(cls, values: dict[str, Any]) -> dict[str, Any]:
        query_mode = values.get("query_mode")
        if query_mode == "SCENE_GENERATION":
            if not values.get("narrative_time_ref"):
                raise ValueError("SCENE_GENERATION requires narrative_time_ref / Tn")
            if not values.get("world_time_ref"):
                raise ValueError("SCENE_GENERATION requires world_time_ref / Tw")

        role = _normalize_agent_role(values.get("agent_role", ""))
        needs_character_memory = bool(values.get("requires_character_visible_memory")) or role == "CHARACTER_AGENT"
        if needs_character_memory and not values.get("knowledge_time_ref"):
            raise ValueError("character-visible memory requires knowledge_time_ref / Tk")
        return values


class DualLinePlannerGap(_StrictBaseModel):
    gap_code: str
    field: str
    message: str
    severity: str = "warning"


class DualLinePlannerLayer(_StrictBaseModel):
    layer_name: str
    source_contracts: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    allowed_access_labels: list[str] = Field(default_factory=list)
    forbidden_access_labels: list[str] = Field(default_factory=list)
    required: bool = True

    @validator("layer_name")
    def layer_name_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned not in PLANNER_LAYER_NAMES:
            raise ValueError("planner layer is not supported")
        return cleaned


class DualLineQueryPlan(_StrictBaseModel):
    intent: DualLineQueryIntent
    layers: list[DualLinePlannerLayer] = Field(default_factory=list)
    gaps: list[DualLinePlannerGap] = Field(default_factory=list)
    m10_hard_gate_required: bool = True
    m11_candidates_are_writer_facts: bool = False
    query_intents_persistence_ready: bool = False
    library_query_results_persistence_ready: bool = False
    planner_contract_only: bool = True
    invented_time_anchor_count: int = 0


class LibraryQueryResultRecord(_StrictBaseModel):
    project_id: str
    library_query_result_id: str
    query_intent_id: str = ""
    retrieval_task_id: str = ""
    candidate_count: int = Field(0, ge=0)
    selected_count: int = Field(0, ge=0)
    filtered_count: int = Field(0, ge=0)
    excluded_count: int = Field(0, ge=0)
    latency_ms: int = Field(0, ge=0)
    token_estimate: int = Field(0, ge=0)
    retrieval_modes: list[str] = Field(default_factory=list)
    candidate_refs: list[dict[str, Any]] = Field(default_factory=list)
    selected_candidate_refs: list[dict[str, Any]] = Field(default_factory=list)
    filtered_candidate_refs: list[dict[str, Any]] = Field(default_factory=list)
    excluded_candidate_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[Any] = Field(default_factory=list)
    status: str = "DRAFT"
    m11_candidates_are_writer_facts: bool = False

    @validator("project_id", "library_query_result_id")
    def required_record_id_must_not_be_empty(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("required record id field must not be empty")
        return cleaned

    @validator("query_intent_id", "retrieval_task_id", "status", pre=True, always=True)
    def normalize_optional_record_string(cls, value: Any) -> str:
        return str(value or "").strip()

    @root_validator(skip_on_failure=True)
    def selected_filtered_excluded_cannot_exceed_candidates(cls, values: dict[str, Any]) -> dict[str, Any]:
        candidate_count = int(values.get("candidate_count") or 0)
        total_outcomes = (
            int(values.get("selected_count") or 0)
            + int(values.get("filtered_count") or 0)
            + int(values.get("excluded_count") or 0)
        )
        if total_outcomes > candidate_count:
            raise ValueError("selected/filter/excluded counts cannot exceed candidate_count")
        if values.get("m11_candidates_are_writer_facts") is not False:
            raise ValueError("M11 candidates must not be marked WriterAgent facts")
        return values


class QueryOrchestrationTraceStage(_StrictBaseModel):
    stage_name: str
    input_ref: str = ""
    output_ref: str = ""
    selected_count: int = Field(0, ge=0)
    filtered_count: int = Field(0, ge=0)
    excluded_count: int = Field(0, ge=0)
    latency_ms: int = Field(0, ge=0)
    status: str = "DRAFT"
    source_refs: list[Any] = Field(default_factory=list)

    @validator("stage_name")
    def stage_name_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned not in QUERY_ORCHESTRATION_STAGE_NAMES:
            raise ValueError("query orchestration stage is not supported")
        return cleaned


class QueryOrchestrationRunRecord(_StrictBaseModel):
    project_id: str
    query_orchestration_run_id: str
    query_intent_id: str
    query_mode: str
    temporal_query_id: str = ""
    retrieval_task_id: str = ""
    library_query_result_id: str = ""
    candidate_fusion_result_ids: list[str] = Field(default_factory=list)
    authority_visibility_gate_result_ids: list[str] = Field(default_factory=list)
    context_pack_build_id: str = ""
    agent_consumption_target: str = "pending_runtime_integration"
    selected_count: int = Field(0, ge=0)
    filtered_count: int = Field(0, ge=0)
    excluded_count: int = Field(0, ge=0)
    latency_ms: int = Field(0, ge=0)
    source_refs: list[Any] = Field(default_factory=list)
    stages: list[QueryOrchestrationTraceStage] = Field(default_factory=list)
    runtime_scene_generation_consumed: bool = False
    writer_agent_fact_ready: bool = False
    status: str = "DRAFT"

    @validator("project_id", "query_orchestration_run_id", "query_intent_id", "query_mode")
    def required_run_id_must_not_be_empty(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("required run field must not be empty")
        return cleaned

    @validator(
        "temporal_query_id",
        "retrieval_task_id",
        "library_query_result_id",
        "context_pack_build_id",
        "agent_consumption_target",
        "status",
        pre=True,
        always=True,
    )
    def normalize_optional_run_string(cls, value: Any) -> str:
        return str(value or "").strip()

    @root_validator(skip_on_failure=True)
    def no_runtime_or_writer_fact_claim_in_task2(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("runtime_scene_generation_consumed") is not False:
            raise ValueError("Task 2 must not claim runtime scene generation consumption")
        if values.get("writer_agent_fact_ready") is not False:
            raise ValueError("Task 2 must not mark WriterAgent fact readiness")
        return values


class DualLineAdapterRequest(_StrictBaseModel):
    intent: DualLineQueryIntent
    world_time_sort_key: int = Field(..., ge=0)
    knowledge_time_sort_key: int = Field(0, ge=0)
    narrative_sequence_key: int = Field(..., ge=0)
    query_text: str = ""
    reader_disclosure_refs: list[dict[str, Any]] = Field(default_factory=list)
    version_status_refs: list[dict[str, Any]] = Field(default_factory=list)
    pack_refs: list[dict[str, Any]] = Field(default_factory=list)
    log_usage: bool = False
    log_gap_for_missing_context: bool = False

    @validator("query_text", pre=True, always=True)
    def normalize_query_text(cls, value: Any) -> str:
        return str(value or "").strip()


class DualLineAdapterIntegrationResult(_StrictBaseModel):
    project_id: str
    query_intent_id: str
    temporal_resolver_adapter_ready: bool
    library_retriever_adapter_ready: bool
    temporal_call_names: list[str] = Field(default_factory=list)
    library_call_names: list[str] = Field(default_factory=list)
    temporal_result_count: int = Field(0, ge=0)
    library_candidate_count: int = Field(0, ge=0)
    pack_item_count: int = Field(0, ge=0)
    usage_logged: bool = False
    gap_logged: bool = False
    semantic_boundary_checked: bool = False
    semantic_retrieval_mode: str = "optional_hook_only"
    semantic_score_can_override_hard_gates: bool = False
    m10_hard_gate_preserved: bool = True
    m11_candidates_are_writer_facts: bool = False
    writer_agent_fact_ready: bool = False
    runtime_scene_generation_consumed: bool = False
    raw_database_rows_exposed: bool = False
    gaps: list[str] = Field(default_factory=list)

    @root_validator(skip_on_failure=True)
    def enforce_adapter_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("writer_agent_fact_ready") is not False:
            raise ValueError("Task 3 adapter output must not be WriterAgent facts")
        if values.get("runtime_scene_generation_consumed") is not False:
            raise ValueError("Task 3 adapter output must not claim runtime scene generation consumption")
        if values.get("m11_candidates_are_writer_facts") is not False:
            raise ValueError("M11 candidates must remain non-facts")
        if values.get("semantic_score_can_override_hard_gates") is not False:
            raise ValueError("semantic score cannot override hard gates")
        if values.get("raw_database_rows_exposed") is not False:
            raise ValueError("adapter result must not expose raw database rows")
        return values


class CandidateFusionSource(_StrictBaseModel):
    project_id: str
    source_family: str
    stable_source_type: str
    stable_source_id: str
    candidate_kind: str = ""
    access_label: str = "USABLE_NOW"
    visibility_status: str = ""
    authority_level: str = "SYSTEM_CONFIRMED"
    status: str = ""
    lifecycle_state: str = ""
    source_refs: list[Any] = Field(default_factory=list)
    score: float = 0
    score_components: dict[str, float] = Field(default_factory=dict)
    explanation: str = ""
    token_estimate: int = Field(0, ge=0)
    m10_eligible: bool = True
    reader_disclosed: bool = True
    current_timeline: bool = True
    superseded: bool = False
    wrong_timeline: bool = False

    @validator("project_id", "source_family", "stable_source_type", "stable_source_id")
    def required_candidate_id_must_not_be_empty(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("candidate source identity fields must not be empty")
        return cleaned

    @validator("source_family", "access_label", "visibility_status", "authority_level", "status", "lifecycle_state", pre=True, always=True)
    def normalize_candidate_labels(cls, value: Any) -> str:
        return str(value or "").strip().upper()

    @validator("access_label")
    def access_label_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if cleaned not in ACCESS_LABELS:
            raise ValueError("candidate access_label is not supported")
        return cleaned

    @property
    def dedupe_key(self) -> str:
        return f"{self.stable_source_type}:{self.stable_source_id}"


class FusedCandidate(_StrictBaseModel):
    project_id: str
    fused_candidate_id: str
    dedupe_key: str
    candidate_refs: list[dict[str, str]] = Field(default_factory=list)
    source_families: list[str] = Field(default_factory=list)
    source_refs: list[Any] = Field(default_factory=list)
    access_label: str
    source_access_labels: list[str] = Field(default_factory=list)
    visibility_statuses: list[str] = Field(default_factory=list)
    authority_levels: list[str] = Field(default_factory=list)
    gate_bucket: str
    gate_reasons: list[str] = Field(default_factory=list)
    usable_for_writer: bool = False
    writer_agent_fact_ready: bool = False
    final_score: float = 0
    score_components: dict[str, float] = Field(default_factory=dict)
    explanations: list[str] = Field(default_factory=list)
    token_estimate: int = Field(0, ge=0)

    @validator("access_label")
    def fused_access_label_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if cleaned not in ACCESS_LABELS:
            raise ValueError("fused candidate access_label is not supported")
        return cleaned

    @validator("gate_bucket")
    def gate_bucket_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if cleaned not in CANDIDATE_FUSION_BUCKETS:
            raise ValueError("fused candidate gate_bucket is not supported")
        return cleaned

    @root_validator(skip_on_failure=True)
    def enforce_task4_gate_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        access_label = values.get("access_label")
        gate_bucket = values.get("gate_bucket")
        if not values.get("gate_reasons"):
            raise ValueError("gate reasons must be reviewable")
        if values.get("writer_agent_fact_ready") is not False:
            raise ValueError("Task 4 fused candidates must not be WriterAgent facts")
        if access_label in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS and gate_bucket not in {"AVOID_REVEALING", "AUDIT_ONLY"}:
            raise ValueError("forbidden labels cannot enter usable or may-use buckets")
        if access_label == "CANDIDATE_ONLY" and values.get("usable_for_writer") is not False:
            raise ValueError("CANDIDATE_ONLY cannot become a WriterAgent fact or usable fact")
        if values.get("usable_for_writer") is True and access_label != "USABLE_NOW":
            raise ValueError("usable_for_writer requires USABLE_NOW")
        return values


class CandidateFusionResult(_StrictBaseModel):
    project_id: str
    query_intent_id: str
    fused_candidates: list[FusedCandidate] = Field(default_factory=list)
    rejected_candidate_refs: list[dict[str, str]] = Field(default_factory=list)
    input_candidate_count: int = Field(0, ge=0)
    fused_candidate_count: int = Field(0, ge=0)
    deduped_candidate_count: int = Field(0, ge=0)
    rejected_candidate_count: int = Field(0, ge=0)
    usable_count: int = Field(0, ge=0)
    may_use_count: int = Field(0, ge=0)
    avoid_revealing_count: int = Field(0, ge=0)
    audit_only_count: int = Field(0, ge=0)
    gate_reason_count: int = Field(0, ge=0)
    all_candidates_have_access_label: bool = True
    source_refs_preserved: bool = True
    score_components_preserved: bool = True
    explanations_preserved: bool = True
    m10_labels_preserved: bool = True
    forbidden_labels_excluded_from_writer_direct: bool = True
    candidate_only_not_fact: bool = True
    high_score_cannot_override_hard_gates: bool = True
    cross_project_candidate_rejected: bool = False
    writer_agent_fact_ready: bool = False
    runtime_scene_generation_consumed: bool = False
    context_pack_build_ready: bool = False

    @root_validator(skip_on_failure=True)
    def enforce_task4_result_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        fused_candidates = values.get("fused_candidates") or []
        if values.get("writer_agent_fact_ready") is not False:
            raise ValueError("Task 4 must not mark WriterAgent fact readiness")
        if values.get("runtime_scene_generation_consumed") is not False:
            raise ValueError("Task 4 must not claim runtime scene generation consumption")
        if values.get("context_pack_build_ready") is not False:
            raise ValueError("Task 4 must not mark context pack build ready")
        if any(candidate.writer_agent_fact_ready for candidate in fused_candidates):
            raise ValueError("fused candidates must remain non-facts")
        if any(
            candidate.access_label in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS
            and candidate.gate_bucket in {"USABLE", "MAY_USE"}
            for candidate in fused_candidates
        ):
            raise ValueError("forbidden candidates cannot enter usable/may-use buckets")
        return values


class ContextPackItem(_StrictBaseModel):
    item_id: str
    dedupe_key: str
    source_section: str
    access_label: str
    gate_bucket: str
    authority_levels: list[str] = Field(default_factory=list)
    source_refs: list[Any] = Field(default_factory=list)
    inclusion_reasons: list[str] = Field(default_factory=list)
    score_components: dict[str, float] = Field(default_factory=dict)
    explanations: list[str] = Field(default_factory=list)
    token_estimate: int = Field(0, ge=0)
    direct_prose_allowed: bool = False

    @validator("source_section")
    def source_section_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned not in WRITE_AGENT_CONTEXT_PACK_SECTIONS:
            raise ValueError("context pack item section is not supported")
        return cleaned

    @validator("access_label")
    def context_item_access_label_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if cleaned not in ACCESS_LABELS:
            raise ValueError("context pack item access_label is not supported")
        return cleaned

    @root_validator(skip_on_failure=True)
    def enforce_context_item_boundaries(cls, values: dict[str, Any]) -> dict[str, Any]:
        section = values.get("source_section")
        access_label = values.get("access_label")
        gate_bucket = values.get("gate_bucket")
        direct_allowed = values.get("direct_prose_allowed") is True
        if not values.get("source_refs"):
            raise ValueError("context pack item must preserve source refs")
        if not values.get("authority_levels"):
            raise ValueError("context pack item must preserve authority levels")
        if not values.get("inclusion_reasons"):
            raise ValueError("context pack item must preserve inclusion reasons")
        if section == "must_use":
            if access_label != "USABLE_NOW" or gate_bucket != "USABLE" or not direct_allowed:
                raise ValueError("must_use requires gate-approved USABLE_NOW content")
        if section in {"avoid_revealing", "continuity_warnings"} and direct_allowed:
            raise ValueError("guardrail/audit sections cannot be direct prose context")
        if access_label in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS and section != "avoid_revealing":
            raise ValueError("forbidden labels must stay in avoid_revealing")
        if access_label == "CONFLICT_RISK" and section != "continuity_warnings":
            raise ValueError("CONFLICT_RISK must stay in continuity_warnings")
        if access_label == "CANDIDATE_ONLY" and section == "must_use":
            raise ValueError("CANDIDATE_ONLY cannot enter must_use")
        return values


class AgentSpecificContextPack(_StrictBaseModel):
    pack_type: str
    context_pack_id: str
    section_names: list[str] = Field(default_factory=list)
    item_count: int = Field(0, ge=0)
    token_estimate: int = Field(0, ge=0)
    source_refs: list[Any] = Field(default_factory=list)

    @validator("pack_type")
    def pack_type_must_be_known(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned not in AGENT_CONTEXT_PACK_TYPES:
            raise ValueError("agent context pack type is not supported")
        return cleaned


class WriteAgentContextPack(_StrictBaseModel):
    project_id: str
    query_intent_id: str
    context_pack_id: str
    query_orchestration_run_id: str
    token_budget: int = Field(1, ge=1)
    max_items: int = Field(1, ge=1)
    must_use: list[ContextPackItem] = Field(default_factory=list)
    may_use: list[ContextPackItem] = Field(default_factory=list)
    avoid_revealing: list[ContextPackItem] = Field(default_factory=list)
    character_visible_memory: list[ContextPackItem] = Field(default_factory=list)
    location_current_state: list[ContextPackItem] = Field(default_factory=list)
    location_change_delta: list[ContextPackItem] = Field(default_factory=list)
    style_and_framework_guidance: list[ContextPackItem] = Field(default_factory=list)
    continuity_warnings: list[ContextPackItem] = Field(default_factory=list)
    source_refs: list[Any] = Field(default_factory=list)
    agent_specific_packs: list[AgentSpecificContextPack] = Field(default_factory=list)
    total_token_estimate: int = Field(0, ge=0)
    included_item_count: int = Field(0, ge=0)
    excluded_item_count: int = Field(0, ge=0)
    context_pack_build_ready: bool = True
    writer_agent_context_pack_ready: bool = True
    runtime_scene_generation_consumed: bool = False
    forbidden_usage_quality_gate_ready: bool = False
    cache_invalidation_ready: bool = False
    raw_retrieval_rows_exposed: bool = False
    traceable_to_orchestration_run: bool = True
    write_agent_receives_raw_candidates: bool = False

    @root_validator(skip_on_failure=True)
    def enforce_context_pack_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("runtime_scene_generation_consumed") is not False:
            raise ValueError("Task 5 must not claim runtime scene generation consumption")
        if values.get("forbidden_usage_quality_gate_ready") is not False:
            raise ValueError("Task 5 must not claim forbidden usage quality gate readiness")
        if values.get("cache_invalidation_ready") is not False:
            raise ValueError("Task 5 must not claim cache invalidation readiness")
        if values.get("raw_retrieval_rows_exposed") is not False:
            raise ValueError("context pack must not expose raw retrieval rows")
        if values.get("write_agent_receives_raw_candidates") is not False:
            raise ValueError("WriterAgent must receive only the final context pack")
        if values.get("total_token_estimate", 0) > values.get("token_budget", 0):
            raise ValueError("context pack token estimate exceeds token budget")
        if values.get("included_item_count", 0) > values.get("max_items", 0):
            raise ValueError("context pack item count exceeds max_items")
        if not values.get("query_orchestration_run_id"):
            raise ValueError("context pack must be traceable to an orchestration run")
        for pack_type in AGENT_CONTEXT_PACK_TYPES:
            if pack_type not in {pack.pack_type for pack in values.get("agent_specific_packs", [])}:
                raise ValueError("all required agent-specific packs must be present")
        if not values.get("source_refs"):
            raise ValueError("context pack must preserve source refs")
        return values


class RuntimeAgentContextConsumption(_StrictBaseModel):
    consumer_name: str
    context_pack_id: str
    query_orchestration_run_id: str
    consumed_sections: list[str] = Field(default_factory=list)
    source_refs: list[Any] = Field(default_factory=list)
    consumes_final_gated_context_pack: bool = True
    raw_candidates_consumed: bool = False
    raw_retrieval_rows_consumed: bool = False
    writer_agent_fact_ready: bool = False

    @validator("consumer_name")
    def consumer_name_must_be_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned not in RUNTIME_AGENT_CONTEXT_CONSUMERS:
            raise ValueError("runtime context consumer is not supported")
        return cleaned

    @root_validator(skip_on_failure=True)
    def enforce_runtime_consumption_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        consumer = values.get("consumer_name")
        sections = set(values.get("consumed_sections") or [])
        required = set(RUNTIME_AGENT_REQUIRED_SECTIONS.get(consumer, ()))
        if not required.issubset(sections):
            raise ValueError("runtime consumer is missing required context pack sections")
        if any(section not in WRITE_AGENT_CONTEXT_PACK_SECTIONS for section in sections):
            raise ValueError("runtime consumer section is not a WriteAgentContextPack section")
        if values.get("consumes_final_gated_context_pack") is not True:
            raise ValueError("runtime consumer must consume the final gated context pack")
        if values.get("raw_candidates_consumed") is not False:
            raise ValueError("runtime consumer must not consume raw candidates")
        if values.get("raw_retrieval_rows_consumed") is not False:
            raise ValueError("runtime consumer must not consume raw retrieval rows")
        if values.get("writer_agent_fact_ready") is not False:
            raise ValueError("runtime consumer cannot upgrade candidates into WriterAgent facts")
        if not values.get("source_refs"):
            raise ValueError("runtime consumer must preserve source refs")
        return values


class RuntimeSceneGenerationConsumptionEvidence(_StrictBaseModel):
    project_id: str
    scene_id: str
    context_pack_id: str
    query_orchestration_run_id: str
    consumers: list[RuntimeAgentContextConsumption] = Field(default_factory=list)
    scene_generation_path_consumes_context_pack: bool = True
    runtime_scene_generation_consumed: bool = True
    write_agent_receives_gated_context_only: bool = True
    raw_candidates_consumed: bool = False
    raw_retrieval_rows_consumed: bool = False
    character_agent_receives_character_visible_memory_only: bool = True
    scene_agent_receives_location_state_and_delta: bool = True
    continuity_agent_receives_audit_layer: bool = True
    existing_non_m12_path_preserved: bool = True
    forbidden_usage_quality_gate_ready: bool = False
    cache_invalidation_ready: bool = False
    m12_closeout_ready: bool = False
    phase9_complete: bool = False

    @root_validator(skip_on_failure=True)
    def enforce_task6_runtime_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        consumers = values.get("consumers") or []
        consumer_names = {consumer.consumer_name for consumer in consumers}
        if consumer_names != set(RUNTIME_AGENT_CONTEXT_CONSUMERS):
            raise ValueError("runtime scene generation evidence must include every required consumer")
        if values.get("scene_generation_path_consumes_context_pack") is not True:
            raise ValueError("Task 6 must prove scene generation consumes the context pack")
        if values.get("runtime_scene_generation_consumed") is not True:
            raise ValueError("Task 6 must mark runtime scene generation consumption")
        if values.get("write_agent_receives_gated_context_only") is not True:
            raise ValueError("Write Agent must receive gated context only")
        if values.get("raw_candidates_consumed") is not False:
            raise ValueError("Task 6 must not consume raw candidates")
        if values.get("raw_retrieval_rows_consumed") is not False:
            raise ValueError("Task 6 must not consume raw retrieval rows")
        if values.get("forbidden_usage_quality_gate_ready") is not False:
            raise ValueError("Task 6 must not claim forbidden usage quality gate readiness")
        if values.get("cache_invalidation_ready") is not False:
            raise ValueError("Task 6 must not claim cache invalidation readiness")
        if values.get("m12_closeout_ready") is not False or values.get("phase9_complete") is not False:
            raise ValueError("Task 6 cannot close M12 or Phase 9")
        return values


class ForbiddenUsageFinding(_StrictBaseModel):
    finding_id: str
    finding_type: str
    source_item_id: str
    dedupe_key: str
    access_label: str
    matched_token: str
    matched_surface: str
    severity: str = "BLOCKING"
    source_refs: list[Any] = Field(default_factory=list)
    expert_debug_explanation: str
    surfaced_to_quality_gate: bool = True

    @root_validator(skip_on_failure=True)
    def enforce_finding_contract(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("access_label") not in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS:
            raise ValueError("forbidden usage finding requires a direct-forbidden access label")
        if values.get("surfaced_to_quality_gate") is not True:
            raise ValueError("forbidden usage finding must surface to quality gate")
        if not values.get("source_refs"):
            raise ValueError("forbidden usage finding must preserve source refs")
        if not str(values.get("expert_debug_explanation") or "").strip():
            raise ValueError("forbidden usage finding must preserve expert/debug explanation")
        return values


class ExpertDebugExclusionEvidence(_StrictBaseModel):
    source_item_id: str
    dedupe_key: str
    access_label: str
    exclusion_reason: str
    source_refs: list[Any] = Field(default_factory=list)
    inclusion_reasons: list[str] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)

    @root_validator(skip_on_failure=True)
    def enforce_exclusion_contract(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("access_label") not in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS:
            raise ValueError("debug exclusion must describe direct-forbidden material")
        if not values.get("source_refs"):
            raise ValueError("debug exclusion must preserve source refs")
        if not str(values.get("exclusion_reason") or "").strip():
            raise ValueError("debug exclusion must explain why item was excluded")
        return values


class RetrievalGapLogEvidence(_StrictBaseModel):
    gap_id: str
    gap_type: str
    message: str
    source_refs: list[Any] = Field(default_factory=list)
    warning_logged: bool = True
    prose_fallback_primary_surface: bool = False

    @root_validator(skip_on_failure=True)
    def enforce_gap_contract(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("warning_logged") is not True:
            raise ValueError("retrieval gap must be logged as a warning")
        if values.get("prose_fallback_primary_surface") is not False:
            raise ValueError("prose fallback cannot become the primary retrieval surface")
        if not str(values.get("gap_type") or "").strip():
            raise ValueError("retrieval gap must have a type")
        return values


class ForbiddenUsageQualityGateEvidence(_StrictBaseModel):
    project_id: str
    scene_id: str
    context_pack_id: str
    query_orchestration_run_id: str
    findings: list[ForbiddenUsageFinding] = Field(default_factory=list)
    expert_debug_exclusions: list[ExpertDebugExclusionEvidence] = Field(default_factory=list)
    retrieval_gaps: list[RetrievalGapLogEvidence] = Field(default_factory=list)
    forbidden_usage_quality_gate_ready: bool = True
    expert_debug_exclusion_reasons_ready: bool = True
    runtime_scene_generation_consumed: bool = True
    uses_final_gated_context_pack: bool = True
    raw_candidates_consumed: bool = False
    raw_retrieval_rows_consumed: bool = False
    forbidden_audit_material_entered_generated_prose_context: bool = False
    quality_gate_flags_attempted_forbidden_usage: bool = False
    retrieval_gap_logged: bool = False
    prose_fallback_primary_surface: bool = False
    cache_invalidation_ready: bool = False
    m12_closeout_ready: bool = False
    phase9_complete: bool = False

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def expert_debug_exclusion_count(self) -> int:
        return len(self.expert_debug_exclusions)

    @root_validator(skip_on_failure=True)
    def enforce_task7_gate_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("forbidden_usage_quality_gate_ready") is not True:
            raise ValueError("Task 7 must mark forbidden usage quality gate readiness")
        if values.get("expert_debug_exclusion_reasons_ready") is not True:
            raise ValueError("Task 7 must preserve expert/debug exclusion reasons")
        if values.get("runtime_scene_generation_consumed") is not True:
            raise ValueError("Task 7 must build on Task 6 runtime consumption evidence")
        if values.get("uses_final_gated_context_pack") is not True:
            raise ValueError("Task 7 must use the final gated context pack")
        if values.get("raw_candidates_consumed") is not False:
            raise ValueError("Task 7 must not consume raw candidates")
        if values.get("raw_retrieval_rows_consumed") is not False:
            raise ValueError("Task 7 must not consume raw retrieval rows")
        if values.get("forbidden_audit_material_entered_generated_prose_context") is not False:
            raise ValueError("forbidden audit material cannot enter generated prose context")
        if values.get("quality_gate_flags_attempted_forbidden_usage") != bool(values.get("findings") or []):
            raise ValueError("quality gate attempted-usage flag must match findings")
        if values.get("retrieval_gap_logged") != bool(values.get("retrieval_gaps") or []):
            raise ValueError("retrieval gap logged flag must match gap evidence")
        if values.get("prose_fallback_primary_surface") is not False:
            raise ValueError("prose fallback cannot become primary retrieval surface")
        if values.get("cache_invalidation_ready") is not False:
            raise ValueError("Task 7 must not claim cache invalidation readiness")
        if values.get("m12_closeout_ready") is not False or values.get("phase9_complete") is not False:
            raise ValueError("Task 7 cannot close M12 or Phase 9")
        return values


class ContextPackCacheEntry(_StrictBaseModel):
    cache_type: str
    cache_key: str
    context_pack_id: str
    query_orchestration_run_id: str
    source_refs: list[Any] = Field(default_factory=list)
    hard_gate_fingerprint: str
    cache_hit_can_bypass_hard_gates: bool = False
    writer_fact_ready: bool = False
    fresh: bool = True

    @validator("cache_type")
    def cache_type_must_be_supported(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned not in CONTEXT_CACHE_TYPES:
            raise ValueError("context cache type is not supported")
        return cleaned

    @root_validator(skip_on_failure=True)
    def enforce_cache_entry_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not str(values.get("cache_key") or "").strip():
            raise ValueError("cache entry must have a stable cache key")
        if not str(values.get("hard_gate_fingerprint") or "").strip():
            raise ValueError("cache entry must preserve hard gate fingerprint")
        if not values.get("source_refs"):
            raise ValueError("cache entry must preserve source refs")
        if values.get("cache_hit_can_bypass_hard_gates") is not False:
            raise ValueError("cache hit cannot bypass M10/M11 hard gates")
        if values.get("writer_fact_ready") is not False:
            raise ValueError("cache entry cannot serve WriterAgent facts directly")
        return values


class ContextPackPrewarmEvidence(_StrictBaseModel):
    target_scene_id: str
    target_scope: str = "next_scene"
    context_pack_id: str
    cache_keys: list[str] = Field(default_factory=list)
    token_budget: int = Field(1, ge=1)
    max_items: int = Field(1, ge=1)
    prewarm_bounded: bool = True
    raw_candidates_consumed: bool = False
    raw_retrieval_rows_consumed: bool = False

    @root_validator(skip_on_failure=True)
    def enforce_prewarm_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not str(values.get("target_scene_id") or "").strip():
            raise ValueError("prewarm evidence must identify a target scene")
        if not values.get("cache_keys"):
            raise ValueError("prewarm evidence must identify cache keys")
        if values.get("prewarm_bounded") is not True:
            raise ValueError("prewarm must be bounded")
        if values.get("raw_candidates_consumed") is not False:
            raise ValueError("prewarm must not consume raw candidates")
        if values.get("raw_retrieval_rows_consumed") is not False:
            raise ValueError("prewarm must not consume raw retrieval rows")
        return values


class ContextPackInvalidationEvidence(_StrictBaseModel):
    trigger_type: str
    affected_context_pack_ids: list[str] = Field(default_factory=list)
    affected_cache_keys: list[str] = Field(default_factory=list)
    safe_fallback_recorded: bool = False
    fallback_reason: str = ""
    m10_m11_hard_gate_recheck_required: bool = True

    @validator("trigger_type")
    def trigger_type_must_be_supported(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned not in CONTEXT_CACHE_INVALIDATION_TRIGGERS:
            raise ValueError("context cache invalidation trigger is not supported")
        return cleaned

    @root_validator(skip_on_failure=True)
    def enforce_invalidation_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        has_target = bool(values.get("affected_context_pack_ids") or values.get("affected_cache_keys"))
        if not has_target and values.get("safe_fallback_recorded") is not True:
            raise ValueError("invalidation must locate affected pack/cache keys or record safe fallback")
        if values.get("safe_fallback_recorded") is True and not str(values.get("fallback_reason") or "").strip():
            raise ValueError("safe fallback invalidation must explain the fallback reason")
        if values.get("m10_m11_hard_gate_recheck_required") is not True:
            raise ValueError("cache invalidation must require M10/M11 hard gate recheck")
        return values


class ContextPackCacheInvalidationEvidence(_StrictBaseModel):
    project_id: str
    scene_id: str
    context_pack_id: str
    query_orchestration_run_id: str
    cache_entries: list[ContextPackCacheEntry] = Field(default_factory=list)
    prewarm_entries: list[ContextPackPrewarmEvidence] = Field(default_factory=list)
    invalidation_events: list[ContextPackInvalidationEvidence] = Field(default_factory=list)
    context_pack_cache_ready: bool = True
    prewarm_ready: bool = True
    cache_invalidation_ready: bool = True
    runtime_scene_generation_consumed: bool = True
    forbidden_usage_quality_gate_ready: bool = True
    uses_final_gated_context_pack: bool = True
    raw_candidates_consumed: bool = False
    raw_retrieval_rows_consumed: bool = False
    m10_m11_hard_gates_preserved: bool = True
    cache_hit_can_bypass_hard_gates: bool = False
    cache_serves_writer_facts_directly: bool = False
    m12_closeout_ready: bool = False
    phase9_complete: bool = False

    @property
    def cache_type_count(self) -> int:
        return len({entry.cache_type for entry in self.cache_entries})

    @property
    def invalidation_trigger_count(self) -> int:
        return len({event.trigger_type for event in self.invalidation_events})

    @property
    def safe_fallback_count(self) -> int:
        return sum(1 for event in self.invalidation_events if event.safe_fallback_recorded)

    @root_validator(skip_on_failure=True)
    def enforce_task8_cache_boundary(cls, values: dict[str, Any]) -> dict[str, Any]:
        cache_types = {entry.cache_type for entry in values.get("cache_entries") or []}
        triggers = {event.trigger_type for event in values.get("invalidation_events") or []}
        if cache_types != set(CONTEXT_CACHE_TYPES):
            raise ValueError("Task 8 must cover every required cache concept")
        if triggers != set(CONTEXT_CACHE_INVALIDATION_TRIGGERS):
            raise ValueError("Task 8 must cover every required invalidation trigger")
        if not values.get("prewarm_entries"):
            raise ValueError("Task 8 must include bounded prewarm evidence")
        for key in [
            "context_pack_cache_ready",
            "prewarm_ready",
            "cache_invalidation_ready",
            "runtime_scene_generation_consumed",
            "forbidden_usage_quality_gate_ready",
            "uses_final_gated_context_pack",
            "m10_m11_hard_gates_preserved",
        ]:
            if values.get(key) is not True:
                raise ValueError(f"Task 8 must set {key}=true")
        for key in [
            "raw_candidates_consumed",
            "raw_retrieval_rows_consumed",
            "cache_hit_can_bypass_hard_gates",
            "cache_serves_writer_facts_directly",
            "m12_closeout_ready",
            "phase9_complete",
        ]:
            if values.get(key) is not False:
                raise ValueError(f"Task 8 must set {key}=false")
        for event in values.get("invalidation_events") or []:
            if not (event.affected_context_pack_ids or event.affected_cache_keys or event.safe_fallback_recorded):
                raise ValueError("each invalidation event must locate affected packs/cache keys or record fallback")
        return values


def build_dual_line_query_plan(intent: DualLineQueryIntent) -> DualLineQueryPlan:
    gaps: list[DualLinePlannerGap] = []
    if not intent.timeline_id:
        gaps.append(
            DualLinePlannerGap(
                gap_code="MISSING_TIMELINE_ID",
                field="timeline_id",
                message="Planner cannot select a timeline without an explicit timeline_id.",
            )
        )
    if not intent.retrieval_task_id:
        gaps.append(
            DualLinePlannerGap(
                gap_code="MISSING_RETRIEVAL_TASK_ID",
                field="retrieval_task_id",
                message="Library Retriever task must be explicit; Task 1 does not infer one.",
            )
        )
    for ref in intent.required_entity_refs:
        if not str(ref.get("type") or "").strip() or not str(ref.get("id") or "").strip():
            gaps.append(
                DualLinePlannerGap(
                    gap_code="MISSING_REQUIRED_ENTITY_REF",
                    field="required_entity_refs",
                    message="Required entity refs must include both type and id.",
                )
            )
            break

    layers = [
        DualLinePlannerLayer(
            layer_name="hard_context",
            source_contracts=["scene/chapter refs", "required_entity_refs", "source_refs"],
            expected_outputs=["confirmed story facts", "explicit user requirements", "scene/chapter frame"],
            allowed_access_labels=["USABLE_NOW"],
        ),
        DualLinePlannerLayer(
            layer_name="temporal_state",
            source_contracts=["M10 Temporal Resolver"],
            expected_outputs=["character_visible_memory", "location_current_state", "location_change_delta"],
            allowed_access_labels=["USABLE_NOW"],
        ),
        DualLinePlannerLayer(
            layer_name="semantic_supplement",
            source_contracts=["M11 Library Retriever candidates", "M11 pack contracts"],
            expected_outputs=["safe candidate supplements", "retrieval gaps"],
            allowed_access_labels=["USABLE_NOW", "CANDIDATE_ONLY"],
            required=False,
        ),
        DualLinePlannerLayer(
            layer_name="forbidden_audit_layer",
            source_contracts=["M10/M11 access labels", "quality/debug evidence"],
            expected_outputs=["avoid_revealing", "continuity_warnings", "exclusion reasons"],
            allowed_access_labels=["CONFLICT_RISK"],
            forbidden_access_labels=list(WRITER_AGENT_DIRECT_FORBIDDEN_LABELS),
            required=False,
        ),
    ]
    return DualLineQueryPlan(intent=intent, layers=layers, gaps=gaps)


def fuse_and_gate_candidates(
    *,
    project_id: str,
    query_intent_id: str,
    candidates: list[CandidateFusionSource],
    max_items: int = 20,
) -> CandidateFusionResult:
    grouped: dict[str, list[tuple[CandidateFusionSource, str, list[str], bool]]] = {}
    rejected_refs: list[dict[str, str]] = []
    cross_project_rejected = False
    all_have_access_label = True

    for candidate in candidates:
        if candidate.project_id != project_id:
            cross_project_rejected = True
            rejected_refs.append(
                {
                    "stable_source_type": candidate.stable_source_type,
                    "stable_source_id": candidate.stable_source_id,
                    "reason": "CROSS_PROJECT_CANDIDATE_REJECTED",
                }
            )
            continue
        if not candidate.access_label:
            all_have_access_label = False
            continue
        bucket, reasons, usable = _gate_candidate(candidate)
        grouped.setdefault(candidate.dedupe_key, []).append((candidate, bucket, reasons, usable))

    fused_candidates: list[FusedCandidate] = []
    for dedupe_key, entries in grouped.items():
        selected = sorted(entries, key=_candidate_rank_key)[0]
        candidate, bucket, reasons, usable = selected
        merged_candidates = [entry[0] for entry in entries]
        source_refs = _unique_objects(ref for item in merged_candidates for ref in item.source_refs)
        score_components = _merge_score_components(merged_candidates)
        explanations = _unique_strings(item.explanation for item in merged_candidates if item.explanation)
        gate_reasons = _unique_strings(reason for _, _, entry_reasons, _ in entries for reason in entry_reasons)
        candidate_refs = [
            {
                "source_family": item.source_family,
                "stable_source_type": item.stable_source_type,
                "stable_source_id": item.stable_source_id,
            }
            for item in merged_candidates
        ]
        fused_candidates.append(
            FusedCandidate(
                project_id=project_id,
                fused_candidate_id=f"candidate_fusion_{_stable_hash(dedupe_key)}",
                dedupe_key=dedupe_key,
                candidate_refs=candidate_refs,
                source_families=_unique_strings(item.source_family for item in merged_candidates),
                source_refs=source_refs,
                access_label=candidate.access_label,
                source_access_labels=_unique_strings(item.access_label for item in merged_candidates),
                visibility_statuses=_unique_strings(item.visibility_status for item in merged_candidates),
                authority_levels=_unique_strings(item.authority_level for item in merged_candidates),
                gate_bucket=bucket,
                gate_reasons=gate_reasons,
                usable_for_writer=usable,
                writer_agent_fact_ready=False,
                final_score=0.0 if bucket in {"AVOID_REVEALING", "AUDIT_ONLY"} else candidate.score,
                score_components=score_components,
                explanations=explanations,
                token_estimate=max(item.token_estimate for item in merged_candidates),
            )
        )

    fused_candidates = sorted(fused_candidates, key=_fused_candidate_sort_key)[:max_items]
    gate_reason_count = sum(len(candidate.gate_reasons) for candidate in fused_candidates)
    return CandidateFusionResult(
        project_id=project_id,
        query_intent_id=query_intent_id,
        fused_candidates=fused_candidates,
        rejected_candidate_refs=rejected_refs,
        input_candidate_count=len(candidates),
        fused_candidate_count=len(fused_candidates),
        deduped_candidate_count=max(0, len(candidates) - len(fused_candidates) - len(rejected_refs)),
        rejected_candidate_count=len(rejected_refs),
        usable_count=sum(1 for candidate in fused_candidates if candidate.gate_bucket == "USABLE"),
        may_use_count=sum(1 for candidate in fused_candidates if candidate.gate_bucket == "MAY_USE"),
        avoid_revealing_count=sum(1 for candidate in fused_candidates if candidate.gate_bucket == "AVOID_REVEALING"),
        audit_only_count=sum(1 for candidate in fused_candidates if candidate.gate_bucket == "AUDIT_ONLY"),
        gate_reason_count=gate_reason_count,
        all_candidates_have_access_label=all_have_access_label and all(bool(candidate.access_label) for candidate in fused_candidates),
        source_refs_preserved=all(bool(candidate.source_refs) for candidate in fused_candidates),
        score_components_preserved=all(bool(candidate.score_components) for candidate in fused_candidates),
        explanations_preserved=all(bool(candidate.explanations) for candidate in fused_candidates),
        m10_labels_preserved=all(bool(candidate.visibility_statuses) and bool(candidate.authority_levels) for candidate in fused_candidates),
        forbidden_labels_excluded_from_writer_direct=all(
            candidate.access_label not in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS or candidate.gate_bucket == "AVOID_REVEALING"
            for candidate in fused_candidates
        ),
        candidate_only_not_fact=all(
            candidate.access_label != "CANDIDATE_ONLY" or not candidate.usable_for_writer
            for candidate in fused_candidates
        ),
        high_score_cannot_override_hard_gates=all(
            candidate.access_label not in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS or candidate.final_score == 0
            for candidate in fused_candidates
        ),
        cross_project_candidate_rejected=cross_project_rejected,
        writer_agent_fact_ready=False,
        runtime_scene_generation_consumed=False,
        context_pack_build_ready=False,
    )


def build_write_agent_context_pack(
    *,
    project_id: str,
    query_intent_id: str,
    query_orchestration_run_id: str,
    fusion_result: CandidateFusionResult,
    context_pack_id: str = "",
    token_budget: int = 1200,
    max_items: int = 20,
) -> WriteAgentContextPack:
    if fusion_result.project_id != project_id:
        raise ValueError("fusion_result project_id must match context pack project_id")
    if fusion_result.query_intent_id != query_intent_id:
        raise ValueError("fusion_result query_intent_id must match context pack query_intent_id")

    pack_id = context_pack_id or f"write_agent_context_pack_{_stable_hash(project_id + ':' + query_intent_id)}"
    sections: dict[str, list[ContextPackItem]] = {section: [] for section in WRITE_AGENT_CONTEXT_PACK_SECTIONS}
    used_tokens = 0
    included_items = 0
    excluded_items = 0
    all_source_refs: list[Any] = []

    for candidate in fusion_result.fused_candidates:
        section = _context_pack_section_for_candidate(candidate)
        token_estimate = max(0, int(candidate.token_estimate or 0))
        if included_items >= max_items or used_tokens + token_estimate > token_budget:
            excluded_items += 1
            continue
        item = _context_item_from_fused_candidate(candidate, section)
        sections[section].append(item)
        used_tokens += token_estimate
        included_items += 1
        all_source_refs.extend(candidate.source_refs)

        secondary_section = _secondary_context_section_for_candidate(candidate)
        if secondary_section:
            secondary_item = _context_item_from_fused_candidate(candidate, secondary_section)
            sections[secondary_section].append(secondary_item)

    source_refs = _unique_objects(all_source_refs)
    primary_items = [
        *sections["must_use"],
        *sections["may_use"],
        *sections["avoid_revealing"],
        *sections["continuity_warnings"],
    ]
    agent_packs = [
        AgentSpecificContextPack(
            pack_type=pack_type,
            context_pack_id=f"{pack_id}_{pack_type}",
            section_names=list(WRITE_AGENT_CONTEXT_PACK_SECTIONS),
            item_count=len(primary_items),
            token_estimate=used_tokens,
            source_refs=source_refs,
        )
        for pack_type in AGENT_CONTEXT_PACK_TYPES
    ]
    return WriteAgentContextPack(
        project_id=project_id,
        query_intent_id=query_intent_id,
        context_pack_id=pack_id,
        query_orchestration_run_id=query_orchestration_run_id,
        token_budget=token_budget,
        max_items=max_items,
        must_use=sections["must_use"],
        may_use=sections["may_use"],
        avoid_revealing=sections["avoid_revealing"],
        character_visible_memory=sections["character_visible_memory"],
        location_current_state=sections["location_current_state"],
        location_change_delta=sections["location_change_delta"],
        style_and_framework_guidance=sections["style_and_framework_guidance"],
        continuity_warnings=sections["continuity_warnings"],
        source_refs=source_refs,
        agent_specific_packs=agent_packs,
        total_token_estimate=used_tokens,
        included_item_count=included_items,
        excluded_item_count=excluded_items,
        context_pack_build_ready=True,
        writer_agent_context_pack_ready=True,
        runtime_scene_generation_consumed=False,
        forbidden_usage_quality_gate_ready=False,
        cache_invalidation_ready=False,
        raw_retrieval_rows_exposed=False,
        traceable_to_orchestration_run=True,
        write_agent_receives_raw_candidates=False,
    )


def build_runtime_scene_generation_context_payload(
    context_pack: WriteAgentContextPack,
) -> dict[str, Any]:
    """Serialize the final gated pack for approved_context consumption only."""
    sections = {
        "must_use": [_context_pack_item_payload(item) for item in context_pack.must_use],
        "may_use": [_context_pack_item_payload(item) for item in context_pack.may_use],
        "avoid_revealing": [_context_pack_item_payload(item) for item in context_pack.avoid_revealing],
        "character_visible_memory": [
            _context_pack_item_payload(item) for item in context_pack.character_visible_memory
        ],
        "location_current_state": [
            _context_pack_item_payload(item) for item in context_pack.location_current_state
        ],
        "location_change_delta": [
            _context_pack_item_payload(item) for item in context_pack.location_change_delta
        ],
        "style_and_framework_guidance": [
            _context_pack_item_payload(item) for item in context_pack.style_and_framework_guidance
        ],
        "continuity_warnings": [
            _context_pack_item_payload(item) for item in context_pack.continuity_warnings
        ],
        "source_refs": list(context_pack.source_refs),
    }
    return {
        "context_pack_id": context_pack.context_pack_id,
        "query_intent_id": context_pack.query_intent_id,
        "query_orchestration_run_id": context_pack.query_orchestration_run_id,
        "project_id": context_pack.project_id,
        "sections": sections,
        "agent_consumers": list(RUNTIME_AGENT_CONTEXT_CONSUMERS),
        "runtime_scene_generation_consumed": True,
        "raw_candidates_consumed": False,
        "raw_retrieval_rows_consumed": False,
        "writer_agent_receives_gated_context_only": True,
        "source_refs": list(context_pack.source_refs),
    }


def build_runtime_scene_generation_consumption_evidence(
    *,
    project_id: str,
    scene_id: str,
    context_pack: WriteAgentContextPack,
) -> RuntimeSceneGenerationConsumptionEvidence:
    if context_pack.project_id != project_id:
        raise ValueError("context_pack project_id must match runtime scene generation project_id")
    consumers = [
        RuntimeAgentContextConsumption(
            consumer_name=consumer,
            context_pack_id=context_pack.context_pack_id,
            query_orchestration_run_id=context_pack.query_orchestration_run_id,
            consumed_sections=list(RUNTIME_AGENT_REQUIRED_SECTIONS[consumer]),
            source_refs=list(context_pack.source_refs),
            consumes_final_gated_context_pack=True,
            raw_candidates_consumed=False,
            raw_retrieval_rows_consumed=False,
            writer_agent_fact_ready=False,
        )
        for consumer in RUNTIME_AGENT_CONTEXT_CONSUMERS
    ]
    return RuntimeSceneGenerationConsumptionEvidence(
        project_id=project_id,
        scene_id=scene_id,
        context_pack_id=context_pack.context_pack_id,
        query_orchestration_run_id=context_pack.query_orchestration_run_id,
        consumers=consumers,
        scene_generation_path_consumes_context_pack=True,
        runtime_scene_generation_consumed=True,
        write_agent_receives_gated_context_only=True,
        raw_candidates_consumed=False,
        raw_retrieval_rows_consumed=False,
        character_agent_receives_character_visible_memory_only=True,
        scene_agent_receives_location_state_and_delta=True,
        continuity_agent_receives_audit_layer=True,
        existing_non_m12_path_preserved=True,
        forbidden_usage_quality_gate_ready=False,
        cache_invalidation_ready=False,
        m12_closeout_ready=False,
        phase9_complete=False,
    )


def build_forbidden_usage_quality_gate_evidence(
    *,
    project_id: str,
    scene_id: str,
    context_pack: WriteAgentContextPack,
    generated_prose_text: str,
    story_information_texts: list[str] | None = None,
    missing_required_context: list[str] | None = None,
    prose_fallback_used: bool = False,
    prose_fallback_reason: str = "",
) -> ForbiddenUsageQualityGateEvidence:
    if context_pack.project_id != project_id:
        raise ValueError("context_pack project_id must match quality gate project_id")

    surfaces = {
        "generated_prose": _normalize_detection_text(generated_prose_text),
        "story_information": _normalize_detection_text("\n".join(story_information_texts or [])),
    }
    forbidden_items = [
        item
        for item in context_pack.avoid_revealing
        if item.access_label in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS
    ]
    expert_debug_exclusions = [
        ExpertDebugExclusionEvidence(
            source_item_id=item.item_id,
            dedupe_key=item.dedupe_key,
            access_label=item.access_label,
            exclusion_reason=_exclusion_reason_for_item(item),
            source_refs=list(item.source_refs),
            inclusion_reasons=list(item.inclusion_reasons),
            explanations=list(item.explanations),
        )
        for item in forbidden_items
    ]
    findings: list[ForbiddenUsageFinding] = []
    for item in forbidden_items:
        for matched_surface, surface_text in surfaces.items():
            matched_token = _matched_forbidden_token(item, surface_text)
            if not matched_token:
                continue
            findings.append(
                ForbiddenUsageFinding(
                    finding_id=f"forbidden_usage_{_stable_hash(scene_id + ':' + item.item_id + ':' + matched_surface)}",
                    finding_type="FORBIDDEN_CONTEXT_USED_IN_PROSE_OR_STORY_INFO",
                    source_item_id=item.item_id,
                    dedupe_key=item.dedupe_key,
                    access_label=item.access_label,
                    matched_token=matched_token,
                    matched_surface=matched_surface,
                    severity="BLOCKING",
                    source_refs=list(item.source_refs),
                    expert_debug_explanation=_exclusion_reason_for_item(item),
                    surfaced_to_quality_gate=True,
                )
            )

    retrieval_gaps = [
        RetrievalGapLogEvidence(
            gap_id=f"retrieval_gap_{_stable_hash(scene_id + ':' + gap)}",
            gap_type="MISSING_REQUIRED_CONTEXT",
            message=f"Missing required context: {gap}",
            source_refs=list(context_pack.source_refs),
            warning_logged=True,
            prose_fallback_primary_surface=False,
        )
        for gap in _clean_string_list(missing_required_context or [])
    ]
    if prose_fallback_used:
        retrieval_gaps.append(
            RetrievalGapLogEvidence(
                gap_id=f"retrieval_gap_{_stable_hash(scene_id + ':prose_fallback')}",
                gap_type="PROSE_FALLBACK_USED_AS_WARNING_ONLY",
                message=prose_fallback_reason or "Prose fallback was used and must remain warning-only.",
                source_refs=list(context_pack.source_refs),
                warning_logged=True,
                prose_fallback_primary_surface=False,
            )
        )

    return ForbiddenUsageQualityGateEvidence(
        project_id=project_id,
        scene_id=scene_id,
        context_pack_id=context_pack.context_pack_id,
        query_orchestration_run_id=context_pack.query_orchestration_run_id,
        findings=findings,
        expert_debug_exclusions=expert_debug_exclusions,
        retrieval_gaps=retrieval_gaps,
        forbidden_usage_quality_gate_ready=True,
        expert_debug_exclusion_reasons_ready=bool(expert_debug_exclusions),
        runtime_scene_generation_consumed=True,
        uses_final_gated_context_pack=True,
        raw_candidates_consumed=False,
        raw_retrieval_rows_consumed=False,
        forbidden_audit_material_entered_generated_prose_context=False,
        quality_gate_flags_attempted_forbidden_usage=bool(findings),
        retrieval_gap_logged=bool(retrieval_gaps),
        prose_fallback_primary_surface=False,
        cache_invalidation_ready=False,
        m12_closeout_ready=False,
        phase9_complete=False,
    )


def build_context_pack_cache_invalidation_evidence(
    *,
    project_id: str,
    scene_id: str,
    context_pack: WriteAgentContextPack,
    prewarm_scene_ids: list[str] | None = None,
    invalidation_events: list[ContextPackInvalidationEvidence] | None = None,
) -> ContextPackCacheInvalidationEvidence:
    if context_pack.project_id != project_id:
        raise ValueError("context_pack project_id must match cache evidence project_id")

    source_refs = list(context_pack.source_refs)
    gate_fingerprint = _stable_hash(
        "|".join(
            [
                project_id,
                scene_id,
                context_pack.context_pack_id,
                context_pack.query_orchestration_run_id,
                ",".join(WRITER_SAFE_AUTHORITY_LEVELS),
                ",".join(WRITER_AGENT_DIRECT_FORBIDDEN_LABELS),
                repr(source_refs),
            ]
        )
    )
    cache_entries = [
        ContextPackCacheEntry(
            cache_type=cache_type,
            cache_key=f"{cache_type}:{project_id}:{scene_id}:{context_pack.context_pack_id}:{gate_fingerprint}",
            context_pack_id=context_pack.context_pack_id,
            query_orchestration_run_id=context_pack.query_orchestration_run_id,
            source_refs=source_refs,
            hard_gate_fingerprint=gate_fingerprint,
            cache_hit_can_bypass_hard_gates=False,
            writer_fact_ready=False,
            fresh=True,
        )
        for cache_type in CONTEXT_CACHE_TYPES
    ]
    cache_keys = [entry.cache_key for entry in cache_entries]
    prewarm_entries = [
        ContextPackPrewarmEvidence(
            target_scene_id=target_scene_id,
            target_scope="next_scene",
            context_pack_id=context_pack.context_pack_id,
            cache_keys=cache_keys,
            token_budget=context_pack.token_budget,
            max_items=context_pack.max_items,
            prewarm_bounded=True,
            raw_candidates_consumed=False,
            raw_retrieval_rows_consumed=False,
        )
        for target_scene_id in _unique_strings(prewarm_scene_ids or [scene_id])
    ]

    if invalidation_events is None:
        precise_triggers = [
            "memory_node_change",
            "location_state_versioned_insert",
            "location_change_delta_recompute",
            "relationship_change",
            "accepted_scene_output_or_formal_apply_writeback",
            "pack_stale_api_call",
            "superseded_timeline_node",
        ]
        invalidation_events = [
            ContextPackInvalidationEvidence(
                trigger_type=trigger,
                affected_context_pack_ids=[context_pack.context_pack_id],
                affected_cache_keys=cache_keys,
                safe_fallback_recorded=False,
                fallback_reason="",
                m10_m11_hard_gate_recheck_required=True,
            )
            for trigger in precise_triggers
        ]
        invalidation_events.append(
            ContextPackInvalidationEvidence(
                trigger_type="framework_component_change",
                affected_context_pack_ids=[],
                affected_cache_keys=[],
                safe_fallback_recorded=True,
                fallback_reason="framework scope can be broad; rebuild context packs before serving cached context",
                m10_m11_hard_gate_recheck_required=True,
            )
        )

    return ContextPackCacheInvalidationEvidence(
        project_id=project_id,
        scene_id=scene_id,
        context_pack_id=context_pack.context_pack_id,
        query_orchestration_run_id=context_pack.query_orchestration_run_id,
        cache_entries=cache_entries,
        prewarm_entries=prewarm_entries,
        invalidation_events=invalidation_events,
        context_pack_cache_ready=True,
        prewarm_ready=True,
        cache_invalidation_ready=True,
        runtime_scene_generation_consumed=True,
        forbidden_usage_quality_gate_ready=True,
        uses_final_gated_context_pack=True,
        raw_candidates_consumed=False,
        raw_retrieval_rows_consumed=False,
        m10_m11_hard_gates_preserved=True,
        cache_hit_can_bypass_hard_gates=False,
        cache_serves_writer_facts_directly=False,
        m12_closeout_ready=False,
        phase9_complete=False,
    )


def _gate_candidate(candidate: CandidateFusionSource) -> tuple[str, list[str], bool]:
    reasons: list[str] = []
    if candidate.access_label in WRITER_AGENT_DIRECT_FORBIDDEN_LABELS:
        reasons.append(f"FORBIDDEN_ACCESS_LABEL:{candidate.access_label}")
        return "AVOID_REVEALING", reasons, False
    if candidate.access_label == "CONFLICT_RISK":
        reasons.append("AUDIT_ONLY_ACCESS_LABEL:CONFLICT_RISK")
        return "AUDIT_ONLY", reasons, False
    if candidate.access_label == "CANDIDATE_ONLY":
        reasons.append("CANDIDATE_ONLY_REQUIRES_EXPLICIT_LABEL")
        return "MAY_USE", reasons, False
    if candidate.wrong_timeline or not candidate.current_timeline:
        reasons.append("WRONG_TIMELINE_OR_NON_CURRENT")
        return "AVOID_REVEALING", reasons, False
    if candidate.superseded or candidate.status == "SUPERSEDED" or candidate.lifecycle_state in {"ARCHIVED", "DELETED"}:
        reasons.append("SUPERSEDED_OR_DELETED")
        return "AVOID_REVEALING", reasons, False
    if not candidate.m10_eligible:
        reasons.append("M10_HARD_GATE_NOT_ELIGIBLE")
        return "AVOID_REVEALING", reasons, False
    if not candidate.reader_disclosed:
        reasons.append("READER_DISCLOSURE_GATE_FAILED")
        return "AVOID_REVEALING", reasons, False
    if candidate.visibility_status not in USABLE_VISIBILITY_STATUSES:
        reasons.append(f"VISIBILITY_GATE_FAILED:{candidate.visibility_status or 'UNKNOWN'}")
        return "AVOID_REVEALING", reasons, False
    if candidate.authority_level not in WRITER_SAFE_AUTHORITY_LEVELS:
        reasons.append(f"AUTHORITY_GATE_FAILED:{candidate.authority_level or 'UNKNOWN'}")
        return "AUDIT_ONLY", reasons, False
    reasons.append("USABLE_NOW_HARD_GATES_PASSED")
    return "USABLE", reasons, True


def _context_pack_section_for_candidate(candidate: FusedCandidate) -> str:
    if candidate.gate_bucket == "USABLE":
        return "must_use"
    if candidate.gate_bucket == "MAY_USE":
        return "may_use"
    if candidate.gate_bucket == "AVOID_REVEALING":
        return "avoid_revealing"
    return "continuity_warnings"


def _secondary_context_section_for_candidate(candidate: FusedCandidate) -> str:
    source_type = candidate.dedupe_key.split(":", 1)[0]
    if candidate.gate_bucket != "USABLE":
        return ""
    if source_type == "character_memory_node":
        return "character_visible_memory"
    if source_type == "location_state_node":
        return "location_current_state"
    if source_type == "location_change_delta":
        return "location_change_delta"
    if source_type in {"style_guidance", "framework_guidance", "search_document"}:
        return "style_and_framework_guidance"
    return ""


def _context_item_from_fused_candidate(candidate: FusedCandidate, section: str) -> ContextPackItem:
    direct_prose_allowed = section == "must_use" and candidate.gate_bucket == "USABLE" and candidate.access_label == "USABLE_NOW"
    return ContextPackItem(
        item_id=f"context_item_{_stable_hash(candidate.fused_candidate_id + ':' + section)}",
        dedupe_key=candidate.dedupe_key,
        source_section=section,
        access_label=candidate.access_label,
        gate_bucket=candidate.gate_bucket,
        authority_levels=list(candidate.authority_levels),
        source_refs=list(candidate.source_refs),
        inclusion_reasons=list(candidate.gate_reasons),
        score_components=dict(candidate.score_components),
        explanations=list(candidate.explanations),
        token_estimate=candidate.token_estimate,
        direct_prose_allowed=direct_prose_allowed,
    )


def _context_pack_item_payload(item: ContextPackItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "dedupe_key": item.dedupe_key,
        "source_section": item.source_section,
        "access_label": item.access_label,
        "gate_bucket": item.gate_bucket,
        "authority_levels": list(item.authority_levels),
        "source_refs": list(item.source_refs),
        "inclusion_reasons": list(item.inclusion_reasons),
        "score_components": dict(item.score_components),
        "explanations": list(item.explanations),
        "token_estimate": item.token_estimate,
        "direct_prose_allowed": item.direct_prose_allowed,
    }


def _normalize_detection_text(value: str) -> str:
    return str(value or "").casefold()


def _matched_forbidden_token(item: ContextPackItem, surface_text: str) -> str:
    for token in _forbidden_detection_tokens(item):
        if token.casefold() in surface_text:
            return token
    return ""


def _forbidden_detection_tokens(item: ContextPackItem) -> list[str]:
    tokens = [item.item_id, item.dedupe_key, item.access_label]
    if ":" in item.dedupe_key:
        tokens.append(item.dedupe_key.split(":", 1)[1])
    for source_ref in item.source_refs:
        if isinstance(source_ref, dict):
            tokens.extend(str(value or "") for value in source_ref.values())
        else:
            tokens.append(str(source_ref or ""))
    return _unique_strings(tokens)


def _exclusion_reason_for_item(item: ContextPackItem) -> str:
    reasons = [*item.inclusion_reasons, *item.explanations]
    reason_text = "; ".join(_unique_strings(reasons))
    if reason_text:
        return f"{item.access_label} excluded from direct prose: {reason_text}"
    return f"{item.access_label} excluded from direct prose by M10/M12 hard gates."


def _candidate_rank_key(entry: tuple[CandidateFusionSource, str, list[str], bool]) -> tuple[int, float, str]:
    candidate, bucket, _, _ = entry
    bucket_rank = {"USABLE": 0, "MAY_USE": 1, "AUDIT_ONLY": 2, "AVOID_REVEALING": 3}.get(bucket, 9)
    return (bucket_rank, -candidate.score, candidate.stable_source_id)


def _fused_candidate_sort_key(candidate: FusedCandidate) -> tuple[int, float, str]:
    bucket_rank = {"USABLE": 0, "MAY_USE": 1, "AUDIT_ONLY": 2, "AVOID_REVEALING": 3}.get(candidate.gate_bucket, 9)
    return (bucket_rank, -candidate.final_score, candidate.dedupe_key)


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _unique_objects(values: Any) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = repr(value)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _merge_score_components(candidates: list[CandidateFusionSource]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for candidate in candidates:
        for key, value in candidate.score_components.items():
            merged[key] = max(float(value), float(merged.get(key, 0.0)))
    return merged


def build_query_orchestration_trace(
    *,
    query_orchestration_run_id: str,
    intent: DualLineQueryIntent,
    library_query_result: LibraryQueryResultRecord | None = None,
    temporal_query_id: str = "",
    candidate_fusion_result_ids: list[str] | None = None,
    authority_visibility_gate_result_ids: list[str] | None = None,
    context_pack_build_id: str = "",
    agent_consumption_target: str = "pending_runtime_integration",
) -> QueryOrchestrationRunRecord:
    if library_query_result is not None and library_query_result.project_id != intent.project_id:
        raise ValueError("library_query_result project_id must match query intent project_id")
    if library_query_result is not None and library_query_result.query_intent_id:
        if library_query_result.query_intent_id != intent.query_intent_id:
            raise ValueError("library_query_result query_intent_id must match query intent")

    selected_count = library_query_result.selected_count if library_query_result else 0
    filtered_count = library_query_result.filtered_count if library_query_result else 0
    excluded_count = library_query_result.excluded_count if library_query_result else 0
    library_query_result_id = library_query_result.library_query_result_id if library_query_result else ""
    retrieval_task_id = intent.retrieval_task_id or (library_query_result.retrieval_task_id if library_query_result else "")
    source_refs = [*intent.source_refs, *((library_query_result.source_refs if library_query_result else []) or [])]

    stages = [
        QueryOrchestrationTraceStage(
            stage_name="query_intent",
            output_ref=intent.query_intent_id,
            status="CONFIRMED",
            source_refs=intent.source_refs,
        ),
        QueryOrchestrationTraceStage(
            stage_name="temporal_resolver",
            input_ref=intent.query_intent_id,
            output_ref=temporal_query_id,
            status="DRAFT" if not temporal_query_id else "CONFIRMED",
        ),
        QueryOrchestrationTraceStage(
            stage_name="library_retriever",
            input_ref=retrieval_task_id,
            output_ref=library_query_result_id,
            selected_count=selected_count,
            filtered_count=filtered_count,
            excluded_count=excluded_count,
            status="DRAFT" if not library_query_result_id else "CONFIRMED",
            source_refs=library_query_result.source_refs if library_query_result else [],
        ),
        QueryOrchestrationTraceStage(
            stage_name="candidate_fusion",
            input_ref=library_query_result_id,
            output_ref=",".join(candidate_fusion_result_ids or []),
            selected_count=selected_count,
            filtered_count=filtered_count,
            excluded_count=excluded_count,
            status="DRAFT",
        ),
        QueryOrchestrationTraceStage(
            stage_name="authority_visibility_gate",
            input_ref=",".join(candidate_fusion_result_ids or []),
            output_ref=",".join(authority_visibility_gate_result_ids or []),
            filtered_count=filtered_count,
            excluded_count=excluded_count,
            status="DRAFT",
        ),
        QueryOrchestrationTraceStage(
            stage_name="context_pack_build",
            input_ref=",".join(authority_visibility_gate_result_ids or []),
            output_ref=context_pack_build_id,
            selected_count=selected_count,
            status="DRAFT",
        ),
        QueryOrchestrationTraceStage(
            stage_name="agent_consumption_target",
            input_ref=context_pack_build_id,
            output_ref=agent_consumption_target,
            status="DRAFT",
        ),
    ]
    return QueryOrchestrationRunRecord(
        project_id=intent.project_id,
        query_orchestration_run_id=query_orchestration_run_id,
        query_intent_id=intent.query_intent_id,
        query_mode=intent.query_mode,
        temporal_query_id=temporal_query_id,
        retrieval_task_id=retrieval_task_id,
        library_query_result_id=library_query_result_id,
        candidate_fusion_result_ids=candidate_fusion_result_ids or [],
        authority_visibility_gate_result_ids=authority_visibility_gate_result_ids or [],
        context_pack_build_id=context_pack_build_id,
        agent_consumption_target=agent_consumption_target,
        selected_count=selected_count,
        filtered_count=filtered_count,
        excluded_count=excluded_count,
        source_refs=source_refs,
        stages=stages,
        runtime_scene_generation_consumed=False,
        writer_agent_fact_ready=False,
    )
