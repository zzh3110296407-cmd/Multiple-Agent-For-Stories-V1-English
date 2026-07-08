from typing import Any

from pydantic import BaseModel, Field, root_validator, validator

from app.backend.models.composite_agent import CompositeAgentStoryFactDelta


COMPOSITE_GATE_DECISIONS = {
    "pass",
    "pass_with_warnings",
    "needs_revision",
    "needs_user_confirmation",
    "blocked",
    "candidate_only",
}

COMPOSITE_GATE_SEVERITIES = {
    "info",
    "warning",
    "blocking",
    "requires_user_confirmation",
}

COMPOSITE_GATE_DEFAULT_VERSION = "phase85c_m2_integrator_gate_pipeline_v1"


class CompositeGateBlockingFinding(BaseModel):
    finding_id: str
    gate_name: str
    severity: str
    candidate_id: str = ""
    finding_code: str = ""
    source_refs: list[str] = Field(default_factory=list)
    finding_type: str
    source_ref: str = ""
    safe_summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: str = ""

    @root_validator(pre=True)
    def support_m2_contract_field_names(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not values.get("finding_code") and values.get("finding_type"):
            values["finding_code"] = values.get("finding_type")
        if not values.get("finding_type") and values.get("finding_code"):
            values["finding_type"] = values.get("finding_code")
        if not values.get("source_refs") and values.get("source_ref"):
            values["source_refs"] = [values.get("source_ref")]
        if not values.get("source_ref") and values.get("source_refs"):
            refs = _as_list(values.get("source_refs"))
            values["source_ref"] = str(refs[0] or "") if refs else ""
        return values

    @validator("severity")
    def severity_must_be_known(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in COMPOSITE_GATE_SEVERITIES:
            raise ValueError(f"Unknown composite gate severity: {text}")
        return text

    @validator("source_refs", "evidence_refs", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeNoWriteAuditReceipt(BaseModel):
    receipt_id: str
    run_id: str
    bundle_id: str = ""
    input_bundle_id: str = ""
    gate_version: str = COMPOSITE_GATE_DEFAULT_VERSION
    passed: bool
    dry_review: bool = True
    checked_candidate_ids: list[str] = Field(default_factory=list)
    blocked_candidate_ids: list[str] = Field(default_factory=list)
    direct_write_attempt_count: int = 0
    active_memory_write_attempt_count: int = 0
    confirmed_event_attempt_count: int = 0
    state_change_attempt_count: int = 0
    user_confirmation_acceptance_attempt_count: int = 0
    relationship_write_attempt_count: int = 0
    scene_prose_mutation_attempt_count: int = 0
    resolved_continuity_issue_attempt_count: int = 0
    narrative_debt_payoff_attempt_count: int = 0
    story_fact_delta: CompositeAgentStoryFactDelta
    blocking_findings: list[CompositeGateBlockingFinding] = Field(default_factory=list)
    checked_forbidden_write_types: list[str] = Field(default_factory=list)
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""

    @root_validator(pre=True)
    def default_input_bundle_id(cls, values: dict[str, Any]) -> dict[str, Any]:
        return _default_contract_bundle_ids(values)

    @validator("input_bundle_id")
    def input_bundle_id_must_be_non_empty(cls, value: str) -> str:
        return _require_non_empty_string(value, "input_bundle_id")

    @validator(
        "checked_candidate_ids",
        "blocked_candidate_ids",
        "checked_forbidden_write_types",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("dry_review", always=True)
    def dry_review_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite no-write audit receipts must be dry-review only")
        return True

    @validator("story_fact_delta")
    def story_fact_delta_must_be_empty(
        cls, value: CompositeAgentStoryFactDelta
    ) -> CompositeAgentStoryFactDelta:
        if not value.is_empty():
            raise ValueError("Composite no-write audit cannot carry story fact deltas")
        return value


class CompositeObjectiveFactBoundaryReceipt(BaseModel):
    receipt_id: str
    run_id: str
    bundle_id: str = ""
    input_bundle_id: str = ""
    gate_version: str = COMPOSITE_GATE_DEFAULT_VERSION
    passed: bool
    dry_review: bool = True
    checked_candidate_ids: list[str] = Field(default_factory=list)
    blocked_candidate_ids: list[str] = Field(default_factory=list)
    subjective_claims_kept_subjective: bool = True
    perceptions_kept_subjective: bool = True
    lies_kept_non_objective: bool = True
    psychology_traces_not_written_as_events: bool = True
    intents_not_written_as_occurred_facts: bool = True
    intents_not_written_as_events: bool = True
    hard_rule_overrides_blocked: bool = True
    blocking_findings: list[CompositeGateBlockingFinding] = Field(default_factory=list)
    story_fact_delta: CompositeAgentStoryFactDelta
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""

    @root_validator(pre=True)
    def default_objective_contract_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        values = _default_contract_bundle_ids(values)
        if (
            "intents_not_written_as_occurred_facts" not in values
            and "intents_not_written_as_events" in values
        ):
            values["intents_not_written_as_occurred_facts"] = values.get(
                "intents_not_written_as_events"
            )
        return values

    @validator("input_bundle_id")
    def input_bundle_id_must_be_non_empty(cls, value: str) -> str:
        return _require_non_empty_string(value, "input_bundle_id")

    @validator("checked_candidate_ids", "blocked_candidate_ids", "warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("dry_review", always=True)
    def dry_review_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite objective boundary receipts must be dry-review only")
        return True

    @validator("story_fact_delta")
    def story_fact_delta_must_be_empty(
        cls, value: CompositeAgentStoryFactDelta
    ) -> CompositeAgentStoryFactDelta:
        if not value.is_empty():
            raise ValueError(
                "Composite objective fact boundary cannot carry story fact deltas"
            )
        return value


class CompositeGateStepReceipt(BaseModel):
    receipt_id: str
    run_id: str
    bundle_id: str = ""
    input_bundle_id: str = ""
    gate_name: str
    gate_version: str = COMPOSITE_GATE_DEFAULT_VERSION
    decision: str
    severity: str = "info"
    hard_block: bool = False
    dry_review: bool = True
    checked_candidate_ids: list[str] = Field(default_factory=list)
    blocked_candidate_ids: list[str] = Field(default_factory=list)
    source_receipt_ids: list[str] = Field(default_factory=list)
    candidate_output_refs: list[str] = Field(default_factory=list)
    blocking_findings: list[CompositeGateBlockingFinding] = Field(default_factory=list)
    requires_user_confirmation_candidate_ids: list[str] = Field(default_factory=list)
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""

    @root_validator(pre=True)
    def default_gate_step_contract_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        values = _default_contract_bundle_ids(values)
        if not values.get("checked_candidate_ids") and values.get("candidate_output_refs"):
            values["checked_candidate_ids"] = values.get("candidate_output_refs")
        if not values.get("blocked_candidate_ids") and values.get("blocking_findings"):
            blocked: list[str] = []
            for finding in _as_list(values.get("blocking_findings")):
                if isinstance(finding, dict):
                    blocked.append(str(finding.get("candidate_id") or ""))
                else:
                    blocked.append(str(getattr(finding, "candidate_id", "") or ""))
            values["blocked_candidate_ids"] = blocked
        return values

    @validator("input_bundle_id")
    def input_bundle_id_must_be_non_empty(cls, value: str) -> str:
        return _require_non_empty_string(value, "input_bundle_id")

    @validator("decision")
    def decision_must_be_known(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in COMPOSITE_GATE_DECISIONS:
            raise ValueError(f"Unknown composite gate decision: {text}")
        return text

    @validator("severity")
    def severity_must_be_known(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in COMPOSITE_GATE_SEVERITIES:
            raise ValueError(f"Unknown composite gate severity: {text}")
        return text

    @validator(
        "source_receipt_ids",
        "candidate_output_refs",
        "checked_candidate_ids",
        "blocked_candidate_ids",
        "requires_user_confirmation_candidate_ids",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("dry_review", always=True)
    def dry_review_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite gate step receipts must be dry-review only")
        return True


class CompositeGatePipelineResult(BaseModel):
    pipeline_result_id: str
    run_id: str
    bundle_id: str = ""
    input_bundle_id: str = ""
    agent_name: str = ""
    version_id: str
    overall_decision: str
    hard_block: bool = False
    dry_review: bool = True
    gate_step_receipts: list[CompositeGateStepReceipt] = Field(default_factory=list)
    no_write_audit_receipt: CompositeNoWriteAuditReceipt
    objective_fact_boundary_receipt: CompositeObjectiveFactBoundaryReceipt
    candidate_outputs_allowed_for_downstream: list[str] = Field(default_factory=list)
    candidate_outputs_blocked: list[str] = Field(default_factory=list)
    requires_user_confirmation_candidate_ids: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    story_fact_delta: CompositeAgentStoryFactDelta
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    blocking_findings: list[CompositeGateBlockingFinding] = Field(default_factory=list)
    created_at: str = ""

    @root_validator(pre=True)
    def support_m2_pipeline_contract_names(cls, values: dict[str, Any]) -> dict[str, Any]:
        values = _default_contract_bundle_ids(values)
        if (
            "requires_user_confirmation" not in values
            and values.get("requires_user_confirmation_candidate_ids")
        ):
            values["requires_user_confirmation"] = bool(
                values.get("requires_user_confirmation_candidate_ids")
            )
        return values

    @validator("input_bundle_id")
    def input_bundle_id_must_be_non_empty(cls, value: str) -> str:
        return _require_non_empty_string(value, "input_bundle_id")

    @validator("overall_decision")
    def overall_decision_must_be_known(cls, value: str) -> str:
        text = str(value or "").strip()
        if text not in COMPOSITE_GATE_DECISIONS:
            raise ValueError(f"Unknown composite gate pipeline decision: {text}")
        return text

    @validator(
        "candidate_outputs_allowed_for_downstream",
        "candidate_outputs_blocked",
        "requires_user_confirmation_candidate_ids",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("dry_review", always=True)
    def dry_review_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Composite gate pipeline results must be dry-review only")
        return True

    @validator("story_fact_delta")
    def story_fact_delta_must_be_empty(
        cls, value: CompositeAgentStoryFactDelta
    ) -> CompositeAgentStoryFactDelta:
        if not value.is_empty():
            raise ValueError("Composite gate pipeline cannot carry story fact deltas")
        return value

    @validator("gate_step_receipts")
    def gate_step_receipts_must_be_dry_review(
        cls, value: list[CompositeGateStepReceipt]
    ) -> list[CompositeGateStepReceipt]:
        if any(receipt.dry_review is not True for receipt in value):
            raise ValueError("Composite gate pipeline can only contain dry-review receipts")
        return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _default_contract_bundle_ids(values: dict[str, Any]) -> dict[str, Any]:
    if not values.get("input_bundle_id") and values.get("bundle_id"):
        values["input_bundle_id"] = values.get("bundle_id")
    if not values.get("bundle_id") and values.get("input_bundle_id"):
        values["bundle_id"] = values.get("input_bundle_id")
    return values


def _require_non_empty_string(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Composite gate contract requires non-empty {field_name}")
    return text


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
