from typing import Any, Literal

from pydantic import BaseModel, Field, validator


PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION = (
    "phase85c_m1_composite_agent_contract_v1"
)

COMPOSITE_AGENT_RUNTIME_STATUSES = {
    "contract_only",
    "adapter_candidate",
    "adapter_ready",
    "runtime_enabled",
    "future_only",
}

COMPOSITE_AGENT_KINDS = {
    "runtime_agent",
    "gate_adapter",
    "writer_adapter",
    "memory_adapter",
    "future_placeholder",
}

COMPOSITE_AGENT_AUTHORITY_LEVELS = {
    "read_only",
    "candidate",
    "gate_reviewed",
    "user_confirmed",
    "committed",
}

COMPOSITE_AGENT_M1_DEFAULT_AUTHORITY_LEVELS = {"read_only", "candidate"}

COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES = {
    "evidence",
    "candidate",
    "warning",
    "constraint_hint",
    "gate_request",
    "writer_input_candidate",
    "memory_reference",
}

COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES = {
    "committed_fact",
    "confirmed_event",
    "active_memory_write",
    "scene_prose_mutation",
    "resolved_continuity_issue",
    "narrative_debt_payoff",
}

CompositeAgentRuntimeStatus = Literal[
    "contract_only",
    "adapter_candidate",
    "adapter_ready",
    "runtime_enabled",
    "future_only",
]

CompositeAgentKind = Literal[
    "runtime_agent",
    "gate_adapter",
    "writer_adapter",
    "memory_adapter",
    "future_placeholder",
]

CompositeAgentAuthorityLevel = Literal[
    "read_only",
    "candidate",
    "gate_reviewed",
    "user_confirmed",
    "committed",
]

CompositeAgentRequestAuthorityLevel = Literal["read_only", "candidate"]


class CompositeAgentDefinition(BaseModel):
    agent_name: str
    display_name: str
    version_id: str
    target_scope: str
    runtime_status: CompositeAgentRuntimeStatus
    agent_kind: CompositeAgentKind
    allowed_responsibilities: list[str]
    forbidden_actions: list[str]
    required_input_contracts: list[str]
    output_contract_id: str
    default_authority_level: CompositeAgentAuthorityLevel
    candidate_only_default: bool = True
    can_write_story_facts_directly: bool = False
    required_gates: list[str]
    sub_agent_visibility: str = "internal_only"
    implementation_anchor: list[str]
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @validator(
        "allowed_responsibilities",
        "forbidden_actions",
        "required_input_contracts",
        "required_gates",
        "implementation_anchor",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("default_authority_level")
    def default_authority_must_be_read_only_or_candidate(cls, value: str) -> str:
        if value not in COMPOSITE_AGENT_M1_DEFAULT_AUTHORITY_LEVELS:
            raise ValueError("M1 default authority must be read_only or candidate")
        return value

    @validator("candidate_only_default", always=True)
    def candidate_only_default_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite agent definitions must default to candidate-only")
        return True

    @validator("can_write_story_facts_directly", always=True)
    def direct_story_fact_write_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("Composite agent definitions cannot write story facts directly")
        return False


class CompositeAgentRunRequest(BaseModel):
    run_id: str = ""
    agent_name: str
    project_id: str
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 0
    target_scope: str
    source_context_ids: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    requested_output_contract_id: str
    requested_authority_level: CompositeAgentRequestAuthorityLevel = "candidate"
    dry_run: bool = True
    caller: str = "phase85c_m1_verifier"
    created_at: str = ""

    @validator("source_context_ids", "input_refs", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeAgentStoryFactDelta(BaseModel):
    created: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)

    @validator("created", "modified", "removed", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    def is_empty(self) -> bool:
        return not (self.created or self.modified or self.removed)


class SubAgentTrace(BaseModel):
    sub_agent_name: str
    node_kind: str
    output_type: str
    authority_level: str
    confidence: float = 1.0
    source_ids: list[str] = Field(default_factory=list)
    input_fingerprint: str = ""
    output_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""

    @validator("source_ids", "warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("output_type")
    def output_type_must_be_allowed_and_not_forbidden(cls, value: str) -> str:
        text = str(value or "").strip()
        if text in COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES:
            raise ValueError(f"Forbidden composite sub-agent output type: {text}")
        if text not in COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES:
            raise ValueError(f"Unknown composite sub-agent output type: {text}")
        return text

    @validator("authority_level")
    def sub_agent_authority_must_not_commit(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in COMPOSITE_AGENT_AUTHORITY_LEVELS:
            raise ValueError(f"Unknown composite authority level: {text}")
        if text in {"user_confirmed", "committed"}:
            raise ValueError("M1 sub-agent traces cannot claim committed authority")
        return text


class IntegratorReport(BaseModel):
    integrator_report_id: str
    agent_name: str
    merged_output_types: list[str] = Field(default_factory=list)
    source_trace_ids: list[str] = Field(default_factory=list)
    conflict_categories: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    candidate_only: bool = True
    can_write_story_facts_directly: bool = False
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)

    @validator(
        "merged_output_types",
        "source_trace_ids",
        "conflict_categories",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("merged_output_types")
    def merged_output_types_must_be_allowed(cls, value: list[str]) -> list[str]:
        forbidden = [
            output_type
            for output_type in value
            if output_type in COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES
            or output_type not in COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES
        ]
        if forbidden:
            raise ValueError(
                "Integrator report contains disallowed output types: "
                + ", ".join(forbidden)
            )
        return value

    @validator("candidate_only", always=True)
    def candidate_only_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Integrator reports must remain candidate-only")
        return True

    @validator("can_write_story_facts_directly", always=True)
    def direct_write_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("Integrator reports cannot write story facts directly")
        return False


class GateReviewRequest(BaseModel):
    gate_review_request_id: str
    agent_name: str
    requested_gates: list[str]
    candidate_output_refs: list[str] = Field(default_factory=list)
    reason: str
    does_not_mark_gate_passed: bool = True
    candidate_only: bool = True
    safe_summary: str

    @validator("requested_gates", "candidate_output_refs", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("does_not_mark_gate_passed", "candidate_only", always=True)
    def boolean_contract_flags_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Gate review requests cannot mark gates passed in M1")
        return True


class GateReviewReceipt(BaseModel):
    gate_review_receipt_id: str
    gate_name: str
    decision: str
    source_request_id: str
    issued_by: str
    does_not_commit_story_facts: bool = True
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)

    @validator("warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("does_not_commit_story_facts", always=True)
    def receipt_cannot_commit_story_facts(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Gate review receipts cannot commit story facts in M1")
        return True


class CompositeAgentRunResult(BaseModel):
    run_id: str
    agent_name: str
    status: str
    authority_level: str
    candidate_only: bool = True
    can_write_story_facts_directly: bool = False
    sub_agent_traces: list[SubAgentTrace] = Field(default_factory=list)
    integrator_report: IntegratorReport | None = None
    gate_review_requests: list[GateReviewRequest] = Field(default_factory=list)
    gate_review_receipts: list[GateReviewReceipt] = Field(default_factory=list)
    candidate_outputs: list[dict[str, Any]] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    story_fact_delta: CompositeAgentStoryFactDelta
    safe_summary: str
    created_at: str = ""

    @validator("output_refs", "blocking_findings", "warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("run_id")
    def run_id_must_be_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Composite agent run results require a non-empty run_id")
        return text

    @validator("authority_level")
    def result_authority_must_not_commit(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in COMPOSITE_AGENT_AUTHORITY_LEVELS:
            raise ValueError(f"Unknown composite authority level: {text}")
        if text in {"user_confirmed", "committed"}:
            raise ValueError("M1 run results cannot claim committed authority")
        return text

    @validator("candidate_only", always=True)
    def candidate_only_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite agent run results must remain candidate-only")
        return True

    @validator("can_write_story_facts_directly", always=True)
    def direct_write_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("Composite agent run results cannot write story facts directly")
        return False

    @validator("story_fact_delta")
    def story_fact_delta_must_be_empty(
        cls, value: CompositeAgentStoryFactDelta
    ) -> CompositeAgentStoryFactDelta:
        if not value.is_empty():
            raise ValueError("Composite agent run results cannot carry story fact deltas")
        return value


class CompositeAgentRunTrace(BaseModel):
    run_trace_id: str
    run_id: str
    agent_name: str
    version_id: str
    source_context_ids: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    sub_agent_traces: list[SubAgentTrace] = Field(default_factory=list)
    integrator_report: IntegratorReport | None = None
    gate_review_requests: list[GateReviewRequest] = Field(default_factory=list)
    gate_review_receipts: list[GateReviewReceipt] = Field(default_factory=list)
    authority_level: str = "candidate"
    candidate_only: bool = True
    can_write_story_facts_directly: bool = False
    story_fact_delta: CompositeAgentStoryFactDelta
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""

    @validator("source_context_ids", "input_refs", "warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("run_id", "run_trace_id")
    def ids_must_be_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Composite agent run traces require non-empty ids")
        return text

    @validator("authority_level")
    def trace_authority_must_not_commit(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in COMPOSITE_AGENT_AUTHORITY_LEVELS:
            raise ValueError(f"Unknown composite authority level: {text}")
        if text in {"user_confirmed", "committed"}:
            raise ValueError("M1 run traces cannot claim committed authority")
        return text

    @validator("candidate_only", always=True)
    def candidate_only_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite agent run traces must remain candidate-only")
        return True

    @validator("can_write_story_facts_directly", always=True)
    def direct_write_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("Composite agent run traces cannot write story facts directly")
        return False

    @validator("story_fact_delta")
    def story_fact_delta_must_be_empty(
        cls, value: CompositeAgentStoryFactDelta
    ) -> CompositeAgentStoryFactDelta:
        if not value.is_empty():
            raise ValueError("Composite agent run traces cannot carry story fact deltas")
        return value


class CompositeAgentOutputContract(BaseModel):
    output_contract_id: str
    version_id: str
    allowed_output_types: list[str]
    forbidden_output_types: list[str]
    default_authority_level: str
    candidate_only_default: bool = True
    can_write_story_facts_directly: bool = False
    safe_summary: str

    @validator("allowed_output_types", "forbidden_output_types", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("allowed_output_types")
    def allowed_output_types_must_be_whitelisted(cls, value: list[str]) -> list[str]:
        unknown = [
            item for item in value if item not in COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES
        ]
        if unknown:
            raise ValueError("Unknown allowed output types: " + ", ".join(unknown))
        return value

    @validator("forbidden_output_types")
    def forbidden_output_types_must_be_whitelisted(cls, value: list[str]) -> list[str]:
        unknown = [
            item for item in value if item not in COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES
        ]
        if unknown:
            raise ValueError("Unknown forbidden output types: " + ", ".join(unknown))
        return value

    @validator("default_authority_level")
    def default_authority_must_be_safe(cls, value: str) -> str:
        if value not in COMPOSITE_AGENT_M1_DEFAULT_AUTHORITY_LEVELS:
            raise ValueError("Output contracts must default to read_only or candidate")
        return value

    @validator("candidate_only_default", always=True)
    def candidate_only_default_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Output contracts must default to candidate-only")
        return True

    @validator("can_write_story_facts_directly", always=True)
    def direct_write_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("Output contracts cannot write story facts directly")
        return False


class CompositeAgentServiceStep(BaseModel):
    step_id: str
    step_name: str
    order_index: int
    concept_name: str
    current_implementation_paths: list[str] = Field(default_factory=list)
    must_run_before: list[str] = Field(default_factory=list)
    must_run_after: list[str] = Field(default_factory=list)
    safe_summary: str

    @validator(
        "current_implementation_paths",
        "must_run_before",
        "must_run_after",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeAgentRequiredServiceSequence(BaseModel):
    sequence_id: str
    version_id: str
    steps: list[CompositeAgentServiceStep]
    must_preserve_candidate_gate_commit_writeback_order: bool = True
    safe_summary: str

    @validator("must_preserve_candidate_gate_commit_writeback_order", always=True)
    def order_contract_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite agent service sequence must preserve ordering")
        return True


class CompositeAgentRegistry(BaseModel):
    registry_id: str
    version_id: str
    agents: list[CompositeAgentDefinition]
    required_service_sequence: CompositeAgentRequiredServiceSequence
    source_handoff_path: str
    source_m0_report_path: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)

    @validator("warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


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
