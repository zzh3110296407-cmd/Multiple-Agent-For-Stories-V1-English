from typing import Optional

from pydantic import BaseModel, Field, validator


SCENE_GATE_REPAIR_SCHEMA_VERSION = "phase85d_m1_gate_run_report_v1"
SCENE_GATE_ANALYSIS_SCHEMA_VERSION = "phase85d_m3_scene_gate_analysis_report_v1"
SCENE_REVISION_PLAN_SCHEMA_VERSION = "phase85d_m4_scene_revision_plan_v1"
SCENE_GATE_REPAIR_LOOP_SCHEMA_VERSION = "phase85d_m6_scene_gate_repair_loop_v1"
SCENE_GATE_REPAIR_ROUND_SCHEMA_VERSION = "phase85d_m6_scene_gate_repair_round_v1"
SCENE_GATE_REPAIR_ORDINARY_VIEW_SCHEMA_VERSION = "phase85d_m7_scene_gate_repair_ordinary_view_v1"
SCENE_GATE_REPAIR_EXPERT_VIEW_SCHEMA_VERSION = "phase85d_m7_scene_gate_repair_expert_view_v1"
SCENE_GATE_REPAIR_API_RESPONSE_SCHEMA_VERSION = "phase85d_m7_scene_gate_repair_api_response_v1"

M6_CONTENT_SIGNAL_CODES = {
    "prompt_fidelity_missing",
    "prompt_fidelity_weak",
    "demo_default_leak",
    "scene_repetition_too_high",
    "scene_progression_missing",
    "scene_progression_statement_missing",
    "scene_objective_repeated",
    "scene_previous_summary_missing",
    "character_uniqueness_violation",
    "runtime_evidence_stale",
}

GATE_FINDING_GATE_TYPES = {
    "quality",
    "continuity",
    "runtime_refresh",
    "abcd_runtime",
    "composite_runtime",
    "provider",
    "evidence",
}

GATE_FINDING_SEVERITIES = {
    "info",
    "warning",
    "blocking",
    "requires_user_confirmation",
    "degraded",
}

GATE_FINDING_STATUSES = {
    "open",
    "accepted",
    "resolved",
    "stale",
}

GATE_FINDING_ROOT_CAUSE_LAYERS = {
    "quality",
    "writer_prose_output",
    "continuity",
    "runtime_refresh",
    "abcd_runtime",
    "composite_runtime",
    "provider",
    "runtime_evidence",
    "unknown",
}

SCENE_GATE_ANALYSIS_ROOT_CAUSE_LAYERS = {
    "writer_prose_output",
    "scene_information",
    "ordered_story_information_package",
    "character_intent",
    "scene_participation",
    "memory_pack",
    "memory_extraction_candidate",
    "chapter_framework",
    "world_canvas",
    "runtime_evidence",
    "provider_degraded",
    "user_intent_conflict",
    "unknown",
}

SCENE_GATE_ANALYSIS_TARGET_REPAIR_SYSTEMS = {
    "writer",
    "scene_information",
    "story_information_integrator",
    "character_intent",
    "scene_participation",
    "memory_retrieval",
    "memory_extraction",
    "runtime_refresh",
    "quality_gate",
    "continuity_gate",
    "provider_retry",
    "user_confirmation",
    "expert_review",
    "none",
    "unknown",
}

SCENE_GATE_ANALYSIS_NEXT_ACTIONS = {
    "no_repair_needed",
    "proceed_to_revision_plan",
    "refresh_runtime_or_gate_evidence",
    "retry_provider_or_stop",
    "stop_for_user_confirmation",
    "stop_for_expert_review",
    "blocked_unsafe_for_auto_repair",
}

SCENE_GATE_ANALYSIS_RISK_LEVELS = {"none", "low", "medium", "high", "critical"}
SCENE_GATE_USER_ACTION_OPTIONS = {
    "modify",
    "complete",
    "delete",
    "confirm_keep",
    "expert_review",
    "retry_gate_repair",
}
SCENE_GATE_USER_ACTION_OPTION_ORDER = [
    "modify",
    "complete",
    "delete",
    "confirm_keep",
    "expert_review",
    "retry_gate_repair",
]
SCENE_GATE_USER_VISIBILITY_CONTRACT_VERSION = "phase85d_m3_user_visibility_v1"
SCENE_REVISION_PLAN_STATUSES = {
    "no_repair_needed",
    "ready_for_repair",
    "refresh_required",
    "requires_user_confirmation",
    "requires_expert_review",
    "blocked_no_safe_plan",
}
SCENE_REVISION_PLAN_NEXT_STEPS = {
    "no_repair_needed",
    "execute_repair_plan_later",
    "refresh_runtime_or_gate_evidence_later",
    "stop_for_user_confirmation",
    "stop_for_expert_review",
    "blocked_unsafe_for_auto_repair",
}
SCENE_REVISION_PLAN_ACTION_TYPES = {
    "rewrite_scene_prose",
    "refresh_scene_information",
    "refresh_story_information_package",
    "refresh_memory_retrieval",
    "regenerate_memory_extraction_candidates",
    "refresh_scene_participation",
    "refresh_runtime_evidence",
    "rerun_quality_gate",
    "rerun_continuity_gate",
    "stop_for_user_confirmation",
    "stop_for_expert_review",
    "no_op",
}
SCENE_GATE_REPAIR_ROUND_STATUSES = {
    "approved_candidate_ready_for_user_acceptance",
    "repair_candidate_created",
    "stopped_requires_user_confirmation",
    "stopped_requires_expert_review",
    "blocked_provider_degraded",
    "blocked_runtime_refresh_required",
    "blocked_upstream_refresh_required",
    "blocked_no_safe_plan",
    "blocked_repeated_findings",
    "blocked_no_effective_repair",
    "blocked_m5_candidate_creation_failed",
    "blocked_max_rounds_reached",
    "blocked_missing_explicit_continuity_evidence",
    "blocked_runtime_confirm_not_allowed",
}
SCENE_GATE_REPAIR_LOOP_FINAL_STATUSES = {
    "approved_candidate_ready_for_user_acceptance",
    "stopped_requires_user_confirmation",
    "stopped_requires_expert_review",
    "blocked_max_rounds_reached",
    "blocked_repeated_findings",
    "blocked_no_effective_repair",
    "blocked_no_safe_plan",
    "blocked_upstream_refresh_required",
    "blocked_runtime_refresh_required",
    "blocked_provider_degraded",
    "blocked_m5_candidate_creation_failed",
    "blocked_missing_explicit_continuity_evidence",
    "blocked_runtime_confirm_not_allowed",
}
SCENE_GATE_REPAIR_ORDINARY_STATUS_KINDS = {
    "approved",
    "needs_user_action",
    "needs_expert",
    "blocked",
    "failed",
}
SCENE_GATE_REPAIR_ORDINARY_PRIMARY_ACTIONS = {
    "accept_candidate",
    "open_editor",
    "open_continuity_tools",
    "open_expert_panel",
    "retry_gate_repair",
    "none",
}

UserActionOption = str


class GateFinding(BaseModel):
    finding_id: str
    finding_signature: str
    gate_type: str
    source_check_id: str = ""
    source_issue_id: str = ""
    category: str
    severity: str
    status: str = "open"
    target_type: str = "scene"
    target_id: str = ""
    root_cause_layer: str = "unknown"
    affected_fields: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    safe_source_excerpt: str = ""
    suggested_repair_types: list[str] = Field(default_factory=list)
    blocks_auto_repair: bool = False
    blocks_final_output: bool = False
    requires_user_confirmation: bool = False
    first_seen_round: int = 0
    last_seen_round: int = 0
    repair_attempt_count: int = 0

    @validator("gate_type")
    def gate_type_must_be_known(cls, value: str) -> str:
        return value if value in GATE_FINDING_GATE_TYPES else "evidence"

    @validator("severity")
    def severity_must_be_known(cls, value: str) -> str:
        return value if value in GATE_FINDING_SEVERITIES else "warning"

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        return value if value in GATE_FINDING_STATUSES else "open"

    @validator("root_cause_layer")
    def root_cause_layer_must_be_known(cls, value: str) -> str:
        return value if value in GATE_FINDING_ROOT_CAUSE_LAYERS else "unknown"

    @validator(
        "affected_fields",
        "evidence_refs",
        "suggested_repair_types",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("safe_source_excerpt")
    def excerpt_must_be_bounded(cls, value: str) -> str:
        text = str(value or "").strip()
        return text[:400]

    @validator("first_seen_round", "last_seen_round", "repair_attempt_count")
    def counts_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))


class GateRunReport(BaseModel):
    schema_version: str = SCENE_GATE_REPAIR_SCHEMA_VERSION
    gate_run_id: str
    project_id: str
    chapter_id: str = ""
    scene_id: str = ""
    candidate_id: str = ""
    revision_id: str = ""
    round_index: int = 0
    generated_at: str

    quality_checked: bool = False
    quality_gate_run_id: str = ""
    quality_checked_at: str = ""
    quality_passed: Optional[bool] = None

    continuity_checked: bool = False
    continuity_gate_run_id: str = ""
    continuity_checked_at: str = ""
    continuity_passed: Optional[bool] = None

    runtime_refresh_checked: bool = False
    runtime_refresh_state: str = ""
    runtime_confirm_allowed: Optional[bool] = None
    runtime_blocking_reasons: list[str] = Field(default_factory=list)

    abcd_runtime_checked: bool = False
    abcd_runtime_passed: Optional[bool] = None

    composite_runtime_checked: bool = False
    composite_current_scene_match: Optional[bool] = None

    provider_degraded: bool = False
    degraded_check_ids: list[str] = Field(default_factory=list)

    findings: list[GateFinding] = Field(default_factory=list)
    blocking_finding_ids: list[str] = Field(default_factory=list)
    confirmation_required_finding_ids: list[str] = Field(default_factory=list)

    safe_for_auto_repair_loop: bool = False
    safe_to_show_user: bool = True
    source_refs: list[str] = Field(default_factory=list)

    @validator(
        "runtime_blocking_reasons",
        "degraded_check_ids",
        "blocking_finding_ids",
        "confirmation_required_finding_ids",
        "source_refs",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("round_index")
    def round_index_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))


class SceneGateRootCauseGroup(BaseModel):
    group_id: str
    group_signature: str
    root_cause_layer: str = "unknown"
    target_repair_system: str = "unknown"
    finding_ids: list[str] = Field(default_factory=list)
    finding_signatures: list[str] = Field(default_factory=list)
    gate_types: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    severities: list[str] = Field(default_factory=list)
    affected_fields: list[str] = Field(default_factory=list)
    suggested_repair_types: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    priority: int = 100
    risk_level: str = "low"
    blocks_final_output: bool = False
    blocks_auto_repair: bool = False
    requires_user_confirmation: bool = False
    safe_summary: str = ""
    priority_basis: list[str] = Field(default_factory=list)
    recommended_next_action: str = "stop_for_expert_review"
    recommended_stop_reason: str = ""
    user_visible_required: bool = False
    user_action_required: bool = False
    user_action_options: list[UserActionOption] = Field(default_factory=list)
    user_facing_safe_summary: str = ""
    user_action_reason: str = ""

    @validator("root_cause_layer")
    def analysis_root_cause_layer_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_ROOT_CAUSE_LAYERS else "unknown"

    @validator("target_repair_system")
    def target_repair_system_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_TARGET_REPAIR_SYSTEMS else "unknown"

    @validator("recommended_next_action")
    def next_action_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_NEXT_ACTIONS else "stop_for_expert_review"

    @validator("risk_level")
    def risk_level_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_RISK_LEVELS else "medium"

    @validator(
        "finding_ids",
        "finding_signatures",
        "gate_types",
        "categories",
        "severities",
        "affected_fields",
        "suggested_repair_types",
        "evidence_refs",
        "priority_basis",
        pre=True,
    )
    def analysis_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("user_action_options", pre=True)
    def user_action_options_must_be_ordered(cls, value) -> list[UserActionOption]:
        return _unique_user_action_options(value)

    @validator("priority")
    def priority_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator(
        "safe_summary",
        "recommended_stop_reason",
        "user_facing_safe_summary",
        "user_action_reason",
    )
    def analysis_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:500]


class SceneGateAnalysisReport(BaseModel):
    schema_version: str = SCENE_GATE_ANALYSIS_SCHEMA_VERSION
    analysis_id: str
    gate_run_id: str
    project_id: str
    chapter_id: str = ""
    scene_id: str = ""
    candidate_id: str = ""
    revision_id: str = ""
    round_index: int = 0
    generated_at: str

    root_cause_groups: list[SceneGateRootCauseGroup] = Field(default_factory=list)
    merged_finding_ids: list[str] = Field(default_factory=list)
    prioritized_finding_ids: list[str] = Field(default_factory=list)
    blocking_finding_ids: list[str] = Field(default_factory=list)
    confirmation_required_finding_ids: list[str] = Field(default_factory=list)
    degraded_finding_ids: list[str] = Field(default_factory=list)

    auto_repair_allowed: bool = False
    auto_repair_blocking_reasons: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    user_confirmation_reasons: list[str] = Field(default_factory=list)
    risk_level: str = "none"
    analysis_summary: str = ""
    priority_basis: list[str] = Field(default_factory=list)
    user_intent_preservation_notes: list[str] = Field(default_factory=list)
    auto_repair_confidence: str = "none"
    same_issue_repeated: bool = False
    repeated_finding_signatures: list[str] = Field(default_factory=list)
    new_blocking_risk: bool = False
    recommended_next_action: str = "no_repair_needed"
    recommended_stop_reason: str = ""
    source_refs: list[str] = Field(default_factory=list)
    user_visibility_contract_version: str = SCENE_GATE_USER_VISIBILITY_CONTRACT_VERSION
    user_visible_required: bool = False
    user_action_required: bool = False
    user_visible_group_ids: list[str] = Field(default_factory=list)
    user_action_required_group_ids: list[str] = Field(default_factory=list)
    user_action_options: list[UserActionOption] = Field(default_factory=list)
    user_facing_status_summary: str = ""

    @validator(
        "merged_finding_ids",
        "prioritized_finding_ids",
        "blocking_finding_ids",
        "confirmation_required_finding_ids",
        "degraded_finding_ids",
        "auto_repair_blocking_reasons",
        "user_confirmation_reasons",
        "priority_basis",
        "user_intent_preservation_notes",
        "repeated_finding_signatures",
        "source_refs",
        "user_visible_group_ids",
        "user_action_required_group_ids",
        pre=True,
    )
    def report_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("user_action_options", pre=True)
    def report_user_action_options_must_be_ordered(cls, value) -> list[UserActionOption]:
        return _unique_user_action_options(value)

    @validator("risk_level")
    def report_risk_level_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_RISK_LEVELS else "medium"

    @validator("recommended_next_action")
    def report_next_action_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_NEXT_ACTIONS else "stop_for_expert_review"

    @validator("round_index")
    def report_round_index_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("analysis_summary", "recommended_stop_reason", "user_facing_status_summary")
    def report_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:800]


class SceneRevisionPlanAction(BaseModel):
    action_id: str
    action_signature: str
    action_type: str
    target_repair_system: str
    root_cause_layer: str
    source_group_ids: list[str] = Field(default_factory=list)
    source_finding_ids: list[str] = Field(default_factory=list)
    source_finding_signatures: list[str] = Field(default_factory=list)
    source_categories: list[str] = Field(default_factory=list)
    priority: int = 100
    risk_level: str = "low"

    action_summary: str = ""
    repair_instruction: str = ""
    safe_user_summary: str = ""

    required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    allowed_change_scope: list[str] = Field(default_factory=list)

    may_touch_user_requested_content: bool = False
    requires_user_confirmation: bool = False
    requires_expert_review: bool = False
    requires_fresh_story_information: bool = False
    requires_fresh_memory_retrieval: bool = False
    requires_fresh_memory_extraction: bool = False
    requires_fresh_quality_check: bool = False
    requires_fresh_continuity_check: bool = False
    requires_runtime_refresh_after_repair: bool = False

    stop_reason: str = ""

    @validator("action_type")
    def action_type_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_REVISION_PLAN_ACTION_TYPES else "no_op"

    @validator("target_repair_system")
    def plan_target_repair_system_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_TARGET_REPAIR_SYSTEMS else "unknown"

    @validator("root_cause_layer")
    def plan_root_cause_layer_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_ROOT_CAUSE_LAYERS else "unknown"

    @validator("risk_level")
    def plan_action_risk_level_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_ANALYSIS_RISK_LEVELS else "medium"

    @validator(
        "source_group_ids",
        "source_finding_ids",
        "source_finding_signatures",
        "source_categories",
        "required_inputs",
        "expected_outputs",
        "forbidden_changes",
        "allowed_change_scope",
        pre=True,
    )
    def plan_action_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("priority")
    def plan_action_priority_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("action_summary", "repair_instruction", "safe_user_summary", "stop_reason")
    def plan_action_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:900]


class SceneRevisionPlan(BaseModel):
    schema_version: str = SCENE_REVISION_PLAN_SCHEMA_VERSION
    revision_plan_id: str
    revision_plan_signature: str
    analysis_id: str
    gate_run_id: str
    project_id: str
    chapter_id: str = ""
    scene_id: str = ""
    candidate_id: str = ""
    revision_id: str = ""
    round_index: int = 0
    generated_at: str

    plan_status: str = "blocked_no_safe_plan"
    recommended_next_step: str = "blocked_unsafe_for_auto_repair"
    root_cause_group_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    finding_signatures: list[str] = Field(default_factory=list)

    repair_actions: list[SceneRevisionPlanAction] = Field(default_factory=list)
    blocked_group_ids: list[str] = Field(default_factory=list)
    user_visible_group_ids: list[str] = Field(default_factory=list)
    user_action_required_group_ids: list[str] = Field(default_factory=list)

    requires_user_confirmation: bool = False
    requires_expert_review: bool = False
    auto_repair_plan_allowed: bool = False
    may_touch_user_requested_content: bool = False
    requires_fresh_story_information: bool = False
    requires_fresh_memory_retrieval: bool = False
    requires_fresh_memory_extraction: bool = False
    requires_fresh_quality_check: bool = False
    requires_fresh_continuity_check: bool = False
    requires_runtime_refresh_after_repair: bool = False

    user_intent_preservation_notes: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    plan_summary: str = ""
    safe_user_summary: str = ""
    stop_reason: str = ""
    source_refs: list[str] = Field(default_factory=list)

    @validator("plan_status")
    def plan_status_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_REVISION_PLAN_STATUSES else "blocked_no_safe_plan"

    @validator("recommended_next_step")
    def plan_next_step_must_be_known(cls, value: str) -> str:
        return (
            value
            if value in SCENE_REVISION_PLAN_NEXT_STEPS
            else "blocked_unsafe_for_auto_repair"
        )

    @validator(
        "root_cause_group_ids",
        "finding_ids",
        "finding_signatures",
        "blocked_group_ids",
        "user_visible_group_ids",
        "user_action_required_group_ids",
        "user_intent_preservation_notes",
        "forbidden_changes",
        "source_refs",
        pre=True,
    )
    def plan_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("round_index")
    def plan_round_index_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("plan_summary", "safe_user_summary", "stop_reason")
    def plan_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:1000]


class SceneGateRepairRoundReport(BaseModel):
    schema_version: str = SCENE_GATE_REPAIR_ROUND_SCHEMA_VERSION
    repair_run_id: str
    round_index: int
    project_id: str = ""
    chapter_id: str = ""
    scene_id: str

    target_type: str = "scene"
    target_id: str = ""
    revision_id: str = ""

    quality_checked: bool = False
    quality_gate_run_id: str = ""
    quality_passed: Optional[bool] = None

    continuity_checked: bool = False
    continuity_gate_run_id: str = ""
    continuity_passed: Optional[bool] = None

    runtime_refresh_checked: bool = False
    runtime_confirm_allowed: Optional[bool] = None
    runtime_blocking_reasons: list[str] = Field(default_factory=list)

    gate_run_id: str = ""
    analysis_id: str = ""
    revision_plan_id: str = ""
    revision_plan_signature: str = ""

    finding_signatures: list[str] = Field(default_factory=list)
    repeated_finding_signatures: list[str] = Field(default_factory=list)
    blocking_finding_ids: list[str] = Field(default_factory=list)
    user_action_required: bool = False
    user_action_options: list[UserActionOption] = Field(default_factory=list)

    plan_status: str = ""
    recommended_next_step: str = ""
    m5_status: str = ""
    created_revision_id: str = ""

    round_status: str = ""
    stop_reason: str = ""
    safe_user_summary: str = ""
    internal_trace_refs: list[str] = Field(default_factory=list)

    @validator(
        "runtime_blocking_reasons",
        "finding_signatures",
        "repeated_finding_signatures",
        "blocking_finding_ids",
        "internal_trace_refs",
        pre=True,
    )
    def round_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("user_action_options", pre=True)
    def round_user_action_options_must_be_ordered(cls, value) -> list[UserActionOption]:
        return _unique_user_action_options(value)

    @validator("round_index")
    def repair_round_index_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("target_type")
    def target_type_must_be_known(cls, value: str) -> str:
        return value if value in {"scene", "scene_revision"} else "scene"

    @validator("round_status")
    def round_status_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_REPAIR_ROUND_STATUSES else "blocked_no_safe_plan"

    @validator("stop_reason", "safe_user_summary")
    def round_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:1000]


class SceneGateRepairLoopResult(BaseModel):
    schema_version: str = SCENE_GATE_REPAIR_LOOP_SCHEMA_VERSION
    repair_run_id: str
    repair_run_signature: str
    project_id: str = ""
    chapter_id: str = ""
    scene_id: str

    initial_target_type: str = "scene"
    initial_target_id: str = ""
    initial_revision_id: str = ""

    final_target_type: str = ""
    final_target_id: str = ""
    final_revision_id: str = ""
    approved_candidate_id: str = ""

    max_rounds: int = 3
    rounds_completed: int = 0
    final_status: str
    ready_for_user_final_acceptance: bool = False

    user_visible_required: bool = False
    user_action_required: bool = False
    user_action_options: list[UserActionOption] = Field(default_factory=list)
    safe_user_summary: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)

    round_reports: list[SceneGateRepairRoundReport] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    no_write_authority_summary: str = ""

    @validator(
        "blocked_reasons",
        "source_refs",
        pre=True,
    )
    def loop_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("user_action_options", pre=True)
    def loop_user_action_options_must_be_ordered(cls, value) -> list[UserActionOption]:
        return _unique_user_action_options(value)

    @validator("initial_target_type", "final_target_type")
    def loop_target_type_must_be_known(cls, value: str) -> str:
        if not value:
            return ""
        return value if value in {"scene", "scene_revision"} else "scene"

    @validator("max_rounds")
    def max_rounds_must_be_bounded(cls, value: int) -> int:
        return min(5, max(1, int(value or 3)))

    @validator("rounds_completed")
    def rounds_completed_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("final_status")
    def final_status_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_REPAIR_LOOP_FINAL_STATUSES else "blocked_no_safe_plan"

    @validator("safe_user_summary", "no_write_authority_summary")
    def loop_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:1200]


class SceneGateRepairRunRequest(BaseModel):
    scene_id: str = ""
    project_id: str = ""
    chapter_id: str = ""
    initial_revision_id: str = ""
    max_rounds: int = 3
    force_runtime_refresh: bool = True

    @validator("max_rounds")
    def request_max_rounds_must_be_bounded(cls, value: int) -> int:
        return min(5, max(1, int(value or 3)))


class SceneGateRepairOrdinaryView(BaseModel):
    schema_version: str = SCENE_GATE_REPAIR_ORDINARY_VIEW_SCHEMA_VERSION
    scene_id: str
    final_status: str
    status_kind: str
    title: str = ""
    safe_user_summary: str = ""
    rounds_completed: int = 0
    max_rounds: int = 3

    ready_for_user_final_acceptance: bool = False
    approved_candidate_id: str = ""
    approved_revision_id: str = ""

    user_visible_required: bool = False
    user_action_required: bool = False
    user_action_options: list[UserActionOption] = Field(default_factory=list)
    primary_action: str = "none"
    blocking_reasons: list[str] = Field(default_factory=list)

    show_expert_entry: bool = False
    retry_allowed: bool = False

    @validator("final_status")
    def ordinary_final_status_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_REPAIR_LOOP_FINAL_STATUSES else "blocked_no_safe_plan"

    @validator("status_kind")
    def ordinary_status_kind_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_REPAIR_ORDINARY_STATUS_KINDS else "blocked"

    @validator("primary_action")
    def ordinary_primary_action_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_REPAIR_ORDINARY_PRIMARY_ACTIONS else "none"

    @validator("user_action_options", pre=True)
    def ordinary_action_options_must_be_ordered(cls, value) -> list[UserActionOption]:
        return _unique_user_action_options(value)

    @validator("blocking_reasons", pre=True)
    def ordinary_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("rounds_completed")
    def ordinary_rounds_completed_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("max_rounds")
    def ordinary_max_rounds_must_be_bounded(cls, value: int) -> int:
        return min(5, max(1, int(value or 3)))

    @validator("title", "safe_user_summary")
    def ordinary_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:900]


class SceneGateRepairExpertRoundView(BaseModel):
    round_index: int
    round_status: str = ""
    target_type: str = ""
    target_id: str = ""
    revision_id: str = ""
    gate_run_id: str = ""
    quality_gate_run_id: str = ""
    continuity_gate_run_id: str = ""
    analysis_id: str = ""
    revision_plan_id: str = ""
    revision_plan_signature: str = ""
    finding_signatures: list[str] = Field(default_factory=list)
    repeated_finding_signatures: list[str] = Field(default_factory=list)
    user_action_required: bool = False
    user_action_options: list[UserActionOption] = Field(default_factory=list)
    m5_status: str = ""
    created_revision_id: str = ""
    stop_reason: str = ""
    safe_user_summary: str = ""
    internal_trace_refs: list[str] = Field(default_factory=list)

    @validator("round_index")
    def expert_round_index_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("round_status")
    def expert_round_status_must_be_known(cls, value: str) -> str:
        if not value:
            return ""
        return value if value in SCENE_GATE_REPAIR_ROUND_STATUSES else "blocked_no_safe_plan"

    @validator("target_type")
    def expert_target_type_must_be_known(cls, value: str) -> str:
        if not value:
            return ""
        return value if value in {"scene", "scene_revision"} else "scene"

    @validator("user_action_options", pre=True)
    def expert_action_options_must_be_ordered(cls, value) -> list[UserActionOption]:
        return _unique_user_action_options(value)

    @validator(
        "finding_signatures",
        "repeated_finding_signatures",
        "internal_trace_refs",
        pre=True,
    )
    def expert_round_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("stop_reason", "safe_user_summary")
    def expert_round_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:900]


class SceneGateRepairExpertView(BaseModel):
    schema_version: str = SCENE_GATE_REPAIR_EXPERT_VIEW_SCHEMA_VERSION
    repair_run_id: str
    repair_run_signature: str
    scene_id: str
    final_status: str
    rounds_completed: int = 0
    max_rounds: int = 3
    ready_for_user_final_acceptance: bool = False
    approved_candidate_id: str = ""
    approved_revision_id: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    round_views: list[SceneGateRepairExpertRoundView] = Field(default_factory=list)
    no_write_authority_summary: str = ""

    @validator("final_status")
    def expert_final_status_must_be_known(cls, value: str) -> str:
        return value if value in SCENE_GATE_REPAIR_LOOP_FINAL_STATUSES else "blocked_no_safe_plan"

    @validator("rounds_completed")
    def expert_rounds_completed_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))

    @validator("max_rounds")
    def expert_max_rounds_must_be_bounded(cls, value: int) -> int:
        return min(5, max(1, int(value or 3)))

    @validator("blocked_reasons", "source_refs", pre=True)
    def expert_lists_must_be_unique_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("no_write_authority_summary")
    def expert_text_must_be_bounded(cls, value: str) -> str:
        return str(value or "").strip()[:1200]


class SceneGateRepairRunResponse(BaseModel):
    schema_version: str = SCENE_GATE_REPAIR_API_RESPONSE_SCHEMA_VERSION
    success: bool
    scene_id: str
    ordinary_view: SceneGateRepairOrdinaryView
    expert_view: Optional[SceneGateRepairExpertView] = None


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique_strings(values: list) -> list[str]:
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


def _unique_user_action_options(value) -> list[UserActionOption]:
    values = _as_list(value)
    normalized: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if text in SCENE_GATE_USER_ACTION_OPTIONS:
            normalized.add(text)
    return [item for item in SCENE_GATE_USER_ACTION_OPTION_ORDER if item in normalized]
