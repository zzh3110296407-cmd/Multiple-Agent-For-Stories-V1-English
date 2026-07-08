from typing import Any

from pydantic import BaseModel, Field, validator

from app.backend.models.composite_agent import (
    COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES,
    COMPOSITE_AGENT_AUTHORITY_LEVELS,
    COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES,
    CompositeAgentStoryFactDelta,
    GateReviewRequest,
)


PHASE85C_M2_INTEGRATOR_GATE_PIPELINE_VERSION = (
    "phase85c_m2_integrator_gate_pipeline_v1"
)

COMPOSITE_CANDIDATE_TRUTH_STATUSES = {
    "objective_fact",
    "subjective_claim",
    "perception",
    "lie",
    "intent",
    "psychology_trace",
    "constraint_hint",
    "evidence",
    "warning",
    "unknown",
}


class CompositeCandidateItem(BaseModel):
    candidate_id: str
    run_id: str
    agent_name: str
    source_sub_agent_trace_id: str = ""
    source_object_type: str = ""
    source_object_id: str = ""
    semantic_key: str = ""
    output_type: str
    target_scope: str = ""
    tier: str = ""
    budget_scope: str = ""
    authority_level: str
    candidate_only: bool = True
    can_write_story_facts_directly: bool = False
    truth_status: str = "unknown"
    objective_fact_risk: bool = False
    confidence: float = 1.0
    evidence_refs: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str = ""

    @validator("candidate_id", "run_id")
    def required_ids_must_be_non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Composite candidates require non-empty ids")
        return text

    @validator("output_type")
    def output_type_must_be_allowed(cls, value: str) -> str:
        text = str(value or "").strip()
        if text in COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES:
            raise ValueError(f"Forbidden composite candidate output type: {text}")
        if text not in COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES:
            raise ValueError(f"Unknown composite candidate output type: {text}")
        return text

    @validator("authority_level")
    def authority_level_must_not_commit(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in COMPOSITE_AGENT_AUTHORITY_LEVELS:
            raise ValueError(f"Unknown composite authority level: {text}")
        if text in {"user_confirmed", "committed"}:
            raise ValueError("Composite candidates cannot claim confirmed authority")
        return text

    @validator("candidate_only", always=True)
    def candidate_only_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite candidates must remain candidate-only")
        return True

    @validator("can_write_story_facts_directly", always=True)
    def direct_story_fact_write_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("Composite candidates cannot write story facts directly")
        return False

    @validator("truth_status")
    def truth_status_must_be_known(cls, value: str) -> str:
        text = str(value or "").strip() or "unknown"
        if text not in COMPOSITE_CANDIDATE_TRUTH_STATUSES:
            raise ValueError(f"Unknown composite candidate truth status: {text}")
        return text

    @validator(
        "evidence_refs",
        "source_ids",
        "warnings",
        "blocking_findings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeCandidatePool(BaseModel):
    candidate_pool_id: str
    run_id: str
    agent_name: str
    source_context_ids: list[str] = Field(default_factory=list)
    candidates: list[CompositeCandidateItem] = Field(default_factory=list)
    input_candidate_count: int = 0
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""

    @validator("source_context_ids", "warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeConflictGroup(BaseModel):
    conflict_group_id: str
    run_id: str
    agent_name: str
    semantic_key: str
    candidate_ids: list[str]
    conflict_type: str
    severity: str = "warning"
    requires_gate_review: bool = True
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)

    @validator("candidate_ids", "warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeIntegratorPolicy(BaseModel):
    policy_id: str
    version_id: str
    dedupe_by_semantic_key: bool = True
    dedupe_by_source_object: bool = True
    conflict_grouping_enabled: bool = True
    authority_downgrade_requires_audit: bool = True
    candidate_only_required: bool = True
    direct_story_fact_write_allowed: bool = False
    safe_summary: str

    @validator("candidate_only_required", always=True)
    def candidate_only_required_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite Integrator requires candidate-only outputs")
        return True

    @validator("direct_story_fact_write_allowed", always=True)
    def direct_story_fact_write_allowed_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("Composite Integrator cannot allow direct story writes")
        return False


class CompositeIntegratorReport(BaseModel):
    integrator_report_id: str
    run_id: str
    agent_name: str
    source_sub_agent_trace_ids: list[str] = Field(default_factory=list)
    input_candidate_count: int = 0
    accepted_candidate_count: int = 0
    deduped_candidate_count: int = 0
    rejected_candidate_count: int = 0
    conflict_group_count: int = 0
    confidence_summary: dict[str, object] = Field(default_factory=dict)
    budget_summary: dict[str, object] = Field(default_factory=dict)
    authority_summary: dict[str, object] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str = ""

    @validator(
        "source_sub_agent_trace_ids",
        "warnings",
        "blocking_findings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeIntegratedOutputBundle(BaseModel):
    bundle_id: str
    run_id: str
    agent_name: str
    target_scope: str
    integrated_candidates: list[CompositeCandidateItem] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    conflict_groups: list[CompositeConflictGroup] = Field(default_factory=list)
    gate_review_requests: list[GateReviewRequest] = Field(default_factory=list)
    requires_gate_review: bool = True
    requires_user_confirmation_candidate: bool = False
    candidate_only: bool = True
    can_write_story_facts_directly: bool = False
    authority_level: str = "candidate"
    story_fact_delta: CompositeAgentStoryFactDelta
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    created_at: str = ""

    @validator(
        "evidence_refs",
        "warnings",
        "blocking_findings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("candidate_only", always=True)
    def candidate_only_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite integrated bundles must remain candidate-only")
        return True

    @validator("can_write_story_facts_directly", always=True)
    def direct_story_fact_write_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("Composite integrated bundles cannot write story facts")
        return False

    @validator("authority_level")
    def bundle_authority_must_be_safe(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in {"candidate", "read_only"}:
            raise ValueError("Composite integrated bundles can only be candidate/read_only")
        return text

    @validator("story_fact_delta")
    def story_fact_delta_must_be_empty(
        cls, value: CompositeAgentStoryFactDelta
    ) -> CompositeAgentStoryFactDelta:
        if not value.is_empty():
            raise ValueError("Composite integrated bundles cannot carry story fact deltas")
        return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
