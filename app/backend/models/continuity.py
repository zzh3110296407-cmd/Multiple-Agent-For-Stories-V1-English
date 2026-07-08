from typing import Any, Optional

from pydantic import BaseModel, Field, root_validator, validator


CONTINUITY_VERSION_ID = "phase2_m7_continuity_gate_v1"
PRIOR_STORY_COMPLETION_CANDIDATE_VERSION_ID = "phase2_m7_prior_story_completion_candidate_v1"

CONTINUITY_TARGET_TYPES = {"scene", "scene_revision"}
CONTINUITY_ISSUE_CATEGORIES = {
    "no_source_fact",
    "unverified_old_event",
    "forbidden_knowledge",
    "do_not_include_violation",
    "relationship_contradiction",
    "location_scene_state_contradiction",
    "chapter_memory_conflict",
    "premature_information_reveal",
    "chapter_goal_drift",
    "temporary_confirmed_dependency_warning",
    "superseded_memory_used",
    "provisional_dependency_changed",
    "missing_or_stale_memory_pack",
    "world_hard_rule_direct_conflict",
    "prompt_fidelity_missing",
    "demo_default_leak",
    "scene_repetition_too_high",
    "scene_progression_missing",
    "scene_progression_statement_missing",
    "scene_objective_repeated",
    "scene_previous_summary_missing",
}
CONTINUITY_SEVERITIES = {
    "info",
    "warning",
    "blocking",
    "requires_user_confirmation",
}
CONTINUITY_STATUSES = {
    "open",
    "pending_revision_candidate",
    "resolved",
    "accepted",
    "dismissed",
    "rejected_candidate_keeps_open",
}
CONTINUITY_ACCEPTANCE_POLICIES = {
    "allowed",
    "requires_strong_confirmation",
    "forbidden",
}
CONTINUITY_RESOLUTION_ACTIONS = {
    "complete_prior_story",
    "revise_current_scene",
    "mark_as_misinformation_or_lie",
}
CONTINUITY_RESOLUTION_OPTION_TYPES = {
    "complete_prior_story",
    "revise_current_scene",
    "mark_as_claim_or_misinformation",
    "mark_as_perception_or_hallucination",
    "mark_as_apparent_contradiction",
    "create_or_update_narrative_debt",
    "keep_open_or_defer",
}
CONTINUITY_RESOLUTION_AVAILABILITY_STATUSES = {
    "recommended",
    "available",
    "advanced_gated",
    "blocked",
}
CONTINUITY_RESOLUTION_RISK_LEVELS = {"low", "medium", "high"}
CONTINUITY_RESOLUTION_TRUTH_STATUSES = {
    "rumor",
    "lie",
    "misinformation",
    "unverified_claim",
}


def normalize_continuity_resolution_type(value: str) -> str:
    legacy_prior_story_action = "complete_" + "old" + "_story"
    clean = str(value or "").strip()
    if clean == legacy_prior_story_action:
        return "complete_prior_story"
    return clean


PRIOR_STORY_COMPLETION_CANDIDATE_STATUSES = {
    "pending",
    "confirmed",
    "rejected",
    "superseded",
    "blocked",
}
PRIOR_STORY_COMPLETION_CANDIDATE_WRITE_MODES = {
    "link_existing_sources",
    "create_new_event_memory",
    "mixed",
    "blocked",
}
PRIOR_STORY_COMPLETION_CANDIDATE_DECISION_TYPES = {
    "create",
    "confirm",
    "reject",
    "request_revision",
    "supersede",
}
DEFAULT_PRIOR_STORY_COMPLETION_ALLOWED_WRITE_TARGETS = ["event", "memory_record"]
DEFAULT_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS = [
    "scene_prose",
    "character_long_term_state",
    "relationship",
    "world_canvas",
    "framework",
    "narrative_debt_payoff",
    "state_change",
]
REQUIRED_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS = {
    "scene_prose",
    "character_long_term_state",
    "relationship",
    "world_canvas",
    "framework",
    "state_change",
}


class IssueResolutionOption(BaseModel):
    option_id: str
    issue_id: str = ""
    action_type: str = "revise_current_scene"
    label: str = ""
    description: str = ""
    requires_user_input: bool = True
    requires_model_call: bool = False
    expected_effect: str = ""

    @validator("action_type")
    def action_type_must_be_known(cls, value: str) -> str:
        clean = normalize_continuity_resolution_type(value)
        if clean not in CONTINUITY_RESOLUTION_ACTIONS:
            raise ValueError("unknown_continuity_resolution_action_type")
        return clean


class ContinuityIssue(BaseModel):
    issue_id: str
    project_id: str = "local_project"
    target_type: str = "scene"
    target_id: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    revision_id: str = ""
    category: str = "no_source_fact"
    severity: str = "warning"
    status: str = "open"
    acceptance_policy: str = "allowed"
    user_visible_message: str = ""
    technical_summary: str = ""
    evidence_text: str = ""
    source_memory_ids: list[str] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    source_scene_ids: list[str] = Field(default_factory=list)
    source_character_ids: list[str] = Field(default_factory=list)
    source_relationship_ids: list[str] = Field(default_factory=list)
    suggested_options: list[IssueResolutionOption] = Field(default_factory=list)
    blocks_final_confirmation: bool = False
    blocks_state_changing_revision_confirmation: bool = False
    requires_explicit_acceptance: bool = False
    linked_revision_candidate_id: str = ""
    linked_revision_candidate_status: str = ""
    resolution_lifecycle_status: str = ""
    resolution_lifecycle_message: str = ""
    apparent_contradiction_ids: list[str] = Field(default_factory=list)
    apparent_gate_action: str = ""
    apparent_classification: str = ""
    apparent_device_type: str = ""
    apparent_evidence_summary: str = ""
    apparent_matched_record_ids: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = CONTINUITY_VERSION_ID

    @validator("target_type")
    def target_type_must_be_known(cls, value: str) -> str:
        return value if value in CONTINUITY_TARGET_TYPES else "scene"

    @validator("category")
    def category_must_be_known(cls, value: str) -> str:
        return value if value in CONTINUITY_ISSUE_CATEGORIES else "no_source_fact"

    @validator("severity")
    def severity_must_be_known(cls, value: str) -> str:
        return value if value in CONTINUITY_SEVERITIES else "warning"

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        return value if value in CONTINUITY_STATUSES else "open"

    @validator("acceptance_policy")
    def acceptance_policy_must_be_known(cls, value: str) -> str:
        return (
            value
            if value in CONTINUITY_ACCEPTANCE_POLICIES
            else "allowed"
        )

    @validator(
        "source_memory_ids",
        "source_event_ids",
        "source_scene_ids",
        "source_character_ids",
        "source_relationship_ids",
        "apparent_contradiction_ids",
        "apparent_matched_record_ids",
        pre=True,
    )
    def list_values_must_be_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @root_validator(pre=True)
    def normalize_legacy_fields(cls, values: dict) -> dict:
        data = dict(values or {})
        if not data.get("version_id"):
            data["version_id"] = CONTINUITY_VERSION_ID
        if not data.get("status"):
            data["status"] = "open"
        return data


class ContinuityCheckResponse(BaseModel):
    success: bool = True
    target_type: str
    target_id: str
    mode: str = "manual"
    passed: bool = True
    continuity_passed: bool = True
    continuity_checked: bool = False
    continuity_gate_run_id: str = ""
    continuity_checked_at: str = ""
    issues: list[ContinuityIssue] = Field(default_factory=list)
    blocking_issue_ids: list[str] = Field(default_factory=list)
    warning_issue_ids: list[str] = Field(default_factory=list)
    accepted_issue_ids: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    summary: str = ""


class ContinuityTargetStateSnapshot(BaseModel):
    target_type: str
    target_id: str
    scene_id: str = ""
    revision_id: str = ""
    mode: str = "manual"
    active_issues: list[ContinuityIssue] = Field(default_factory=list)
    open_issues: list[ContinuityIssue] = Field(default_factory=list)
    accepted_issue_ids: list[str] = Field(default_factory=list)
    resolved_issue_ids: list[str] = Field(default_factory=list)
    dismissed_issue_ids: list[str] = Field(default_factory=list)
    remaining_open_issue_ids: list[str] = Field(default_factory=list)
    remaining_blocking_issue_ids: list[str] = Field(default_factory=list)
    remaining_warning_issue_ids: list[str] = Field(default_factory=list)
    continuity_passed: bool = True
    requires_user_confirmation: bool = False
    summary: str = ""
    refreshed_at: str = ""


class ContinuityResolutionRefreshResult(BaseModel):
    success: bool = True
    action_type: str
    action_status: str
    target_type: str
    target_id: str
    scene_id: str = ""
    revision_id: str = ""
    mode: str = "manual"
    affected_issue_ids: list[str] = Field(default_factory=list)
    resolved_issue_ids: list[str] = Field(default_factory=list)
    accepted_issue_ids: list[str] = Field(default_factory=list)
    dismissed_issue_ids: list[str] = Field(default_factory=list)
    remaining_open_issue_ids: list[str] = Field(default_factory=list)
    remaining_blocking_issue_ids: list[str] = Field(default_factory=list)
    remaining_warning_issue_ids: list[str] = Field(default_factory=list)
    refreshed_continuity_response: ContinuityCheckResponse | None = None
    quality_report_id: str | None = None
    quality_report_snapshot: dict[str, Any] | None = None
    quality_report_recompute_required: bool = False
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    refreshed_at: str = ""


class ContinuityIssueListResponse(BaseModel):
    success: bool = True
    issues: list[ContinuityIssue] = Field(default_factory=list)
    count: int = 0


class ContinuityIssueResolveRequest(BaseModel):
    action_type: str
    user_input: Optional[str] = None
    revision_prompt: Optional[str] = None
    truth_status: Optional[str] = None

    @validator("action_type")
    def resolve_action_type_must_be_known(cls, value: str) -> str:
        clean = normalize_continuity_resolution_type(value)
        if clean not in CONTINUITY_RESOLUTION_ACTIONS:
            raise ValueError("unknown_continuity_resolution_action_type")
        return clean


class ContinuityIssueAcceptRequest(BaseModel):
    user_input: str


class ContinuityResolutionOptionDefinition(BaseModel):
    option_type: str
    label: str
    description: str = ""
    default_risk_level: str = "medium"
    will_write_objective_fact: bool = False
    will_write_subjective_fact: bool = False
    will_create_candidate: bool = False
    will_create_revision_candidate: bool = False
    will_create_narrative_debt: bool = False
    requires_user_input: bool = False
    requires_user_confirmation: bool = False
    expected_effect: str = ""
    policy_notes: list[str] = Field(default_factory=list)

    @validator("option_type")
    def option_type_must_be_known(cls, value: str) -> str:
        clean = normalize_continuity_resolution_type(value)
        if clean not in CONTINUITY_RESOLUTION_OPTION_TYPES:
            raise ValueError("unknown_continuity_resolution_option_type")
        return clean

    @validator("default_risk_level")
    def risk_level_must_be_known(cls, value: str) -> str:
        return value if value in CONTINUITY_RESOLUTION_RISK_LEVELS else "medium"


class ContinuityResolutionAuthorityPolicy(BaseModel):
    option_type: str
    may_write_objective_fact: bool = False
    must_create_candidate: bool = False
    requires_user_confirmation: bool = False
    may_resolve_source_issue_now: bool = False
    affects_source_story_data: bool = False
    violates_hard_rule_policy: bool = False
    subjective_only: bool = False
    may_convert_blocking_to_accepted: bool = False
    notes: list[str] = Field(default_factory=list)

    @validator("option_type")
    def option_type_must_be_known(cls, value: str) -> str:
        clean = normalize_continuity_resolution_type(value)
        if clean not in CONTINUITY_RESOLUTION_OPTION_TYPES:
            raise ValueError("unknown_continuity_resolution_option_type")
        return clean


class ContinuityResolutionAuthorityGuardResult(BaseModel):
    allowed: bool = False
    option_type: str
    issue_id: str = ""
    policy: ContinuityResolutionAuthorityPolicy
    warnings: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)

    @validator("option_type")
    def option_type_must_be_known(cls, value: str) -> str:
        clean = normalize_continuity_resolution_type(value)
        if clean not in CONTINUITY_RESOLUTION_OPTION_TYPES:
            raise ValueError("unknown_continuity_resolution_option_type")
        return clean


class ContinuityResolutionOptionAvailability(BaseModel):
    option_type: str
    label: str
    description: str = ""
    enabled: bool = False
    disabled_reason: str = ""
    availability_status: str = "blocked"
    recommended: bool = False
    recommended_rank: int = 0
    risk_level: str = "medium"
    requires_user_input: bool = False
    requires_user_confirmation: bool = False
    required_input_fields: list[str] = Field(default_factory=list)
    will_write_objective_fact: bool = False
    will_write_subjective_fact: bool = False
    will_create_candidate: bool = False
    will_create_revision_candidate: bool = False
    will_create_narrative_debt: bool = False
    expected_effect: str = ""
    authority_warning: str = ""
    policy_notes: list[str] = Field(default_factory=list)

    @validator("option_type")
    def option_type_must_be_known(cls, value: str) -> str:
        clean = normalize_continuity_resolution_type(value)
        if clean not in CONTINUITY_RESOLUTION_OPTION_TYPES:
            raise ValueError("unknown_continuity_resolution_option_type")
        return clean

    @validator("availability_status")
    def availability_status_must_be_known(cls, value: str) -> str:
        if value not in CONTINUITY_RESOLUTION_AVAILABILITY_STATUSES:
            raise ValueError("unknown_continuity_resolution_availability_status")
        return value

    @validator("risk_level")
    def risk_level_must_be_known(cls, value: str) -> str:
        return value if value in CONTINUITY_RESOLUTION_RISK_LEVELS else "medium"


class ContinuityResolutionOptionAvailabilityReport(BaseModel):
    success: bool = True
    issue_id: str = ""
    issue: ContinuityIssue | None = None
    options: list[ContinuityResolutionOptionAvailability] = Field(default_factory=list)
    recommended_options: list[ContinuityResolutionOptionAvailability] = Field(default_factory=list)
    available_options: list[ContinuityResolutionOptionAvailability] = Field(default_factory=list)
    advanced_gated_options: list[ContinuityResolutionOptionAvailability] = Field(default_factory=list)
    blocked_options: list[ContinuityResolutionOptionAvailability] = Field(default_factory=list)
    generated_at: str = ""


class ContinuityResolutionOptionExecutionRequest(BaseModel):
    option_type: str
    user_input: str = ""
    revision_prompt: str = ""
    truth_status: str = "misinformation"
    perception_type: str = ""
    create_narrative_debt: bool = False
    user_confirmation: bool = False

    @validator("option_type")
    def option_type_must_be_known(cls, value: str) -> str:
        clean = normalize_continuity_resolution_type(value)
        if clean not in CONTINUITY_RESOLUTION_OPTION_TYPES:
            raise ValueError("unknown_continuity_resolution_option_type")
        return clean

    @validator("truth_status")
    def truth_status_must_be_known(cls, value: str) -> str:
        clean = (value or "misinformation").strip()
        if clean not in CONTINUITY_RESOLUTION_TRUTH_STATUSES:
            raise ValueError("unknown_non_objective_truth_status")
        return clean


class ContinuityResolutionOptionExecutionResult(BaseModel):
    success: bool = True
    option_type: str
    issue_id: str
    created_candidate_id: str = ""
    created_revision_id: str = ""
    created_claim_id: str = ""
    created_perception_id: str = ""
    created_apparent_contradiction_id: str = ""
    created_narrative_debt_id: str = ""
    decision_id: str = ""
    refresh: ContinuityResolutionRefreshResult | dict[str, Any] | None = None
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    issue: dict[str, Any] | None = None
    candidate: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    candidate_decision: dict[str, Any] | None = None
    write_plan: dict[str, Any] | None = None
    lineage: dict[str, Any] | None = None
    memory_record: dict[str, Any] | None = None
    scene_revision_response: dict[str, Any] | None = None

    @validator("option_type")
    def option_type_must_be_known(cls, value: str) -> str:
        clean = normalize_continuity_resolution_type(value)
        if clean not in CONTINUITY_RESOLUTION_OPTION_TYPES:
            raise ValueError("unknown_continuity_resolution_option_type")
        return clean


class PriorStoryCompletionCandidate(BaseModel):
    candidate_id: str
    issue_id: str
    project_id: str = "local_project"
    chapter_id: str = ""
    scene_id: str = ""
    status: str = "pending"
    proposed_event: dict[str, Any] = Field(default_factory=dict)
    proposed_memory_record: dict[str, Any] = Field(default_factory=dict)
    existing_event_ids: list[str] = Field(default_factory=list)
    existing_memory_ids: list[str] = Field(default_factory=list)
    user_visible_summary: str = ""
    source_issue_id: str = ""
    decision_id: str = ""
    candidate_status_reason: str = ""
    completion_scope_summary: str = ""
    resolves_issue_explanation: str = ""
    write_mode: str = "create_new_event_memory"
    allowed_write_targets: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PRIOR_STORY_COMPLETION_ALLOWED_WRITE_TARGETS)
    )
    forbidden_write_targets: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS)
    )
    requires_user_confirmation: bool = True
    write_scope_hash: str = ""
    parent_candidate_id: str = ""
    candidate_version_number: int = 1
    superseded_by_candidate_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = PRIOR_STORY_COMPLETION_CANDIDATE_VERSION_ID

    @validator("status")
    def candidate_status_must_be_known(cls, value: str) -> str:
        return value if value in PRIOR_STORY_COMPLETION_CANDIDATE_STATUSES else "pending"

    @validator("existing_event_ids", "existing_memory_ids", pre=True)
    def existing_refs_must_be_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("write_mode")
    def write_mode_must_be_known(cls, value: str) -> str:
        return value if value in PRIOR_STORY_COMPLETION_CANDIDATE_WRITE_MODES else "create_new_event_memory"

    @validator("allowed_write_targets", "forbidden_write_targets", pre=True)
    def write_targets_must_be_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("candidate_version_number")
    def candidate_version_must_be_positive(cls, value: int) -> int:
        return max(1, int(value or 1))

    @root_validator(pre=True)
    def normalize_candidate_governance_fields(cls, values: dict) -> dict:
        data = dict(values or {})
        if not data.get("source_issue_id") and data.get("issue_id"):
            data["source_issue_id"] = data.get("issue_id")
        if not data.get("allowed_write_targets"):
            data["allowed_write_targets"] = list(DEFAULT_PRIOR_STORY_COMPLETION_ALLOWED_WRITE_TARGETS)
        forbidden = _unique_strings(
            [
                *_as_list(data.get("forbidden_write_targets")),
                *DEFAULT_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS,
            ]
        )
        data["forbidden_write_targets"] = forbidden
        if not data.get("write_mode"):
            if data.get("existing_event_ids") or data.get("existing_memory_ids"):
                data["write_mode"] = "link_existing_sources"
            else:
                data["write_mode"] = "create_new_event_memory"
        if "requires_user_confirmation" not in data:
            data["requires_user_confirmation"] = True
        if not data.get("candidate_version_number"):
            data["candidate_version_number"] = 1
        return data


class PriorStoryCompletionCandidateWritePlan(BaseModel):
    candidate_id: str
    source_issue_id: str
    write_mode: str = "create_new_event_memory"
    event_write_preview: dict[str, Any] = Field(default_factory=dict)
    memory_write_preview: dict[str, Any] = Field(default_factory=dict)
    existing_event_ids: list[str] = Field(default_factory=list)
    existing_memory_ids: list[str] = Field(default_factory=list)
    allowed_write_targets: list[str] = Field(default_factory=list)
    forbidden_write_targets: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = True
    write_scope_hash: str = ""
    safe_summary: str = ""


class PriorStoryCompletionCandidateDecision(BaseModel):
    candidate_decision_id: str
    candidate_id: str
    source_issue_id: str
    decision_type: str
    user_input: str = ""
    decision_id: str = ""
    does_not_confirm_other_issues: bool = True
    does_not_write_beyond_candidate_scope: bool = True
    created_at: str = ""

    @validator("decision_type")
    def decision_type_must_be_known(cls, value: str) -> str:
        return value if value in PRIOR_STORY_COMPLETION_CANDIDATE_DECISION_TYPES else "create"


class PriorStoryCompletionLineage(BaseModel):
    lineage_id: str
    candidate_id: str
    source_issue_id: str
    parent_candidate_id: str = ""
    superseded_candidate_ids: list[str] = Field(default_factory=list)
    superseded_by_candidate_id: str = ""
    linked_event_ids: list[str] = Field(default_factory=list)
    linked_memory_ids: list[str] = Field(default_factory=list)
    created_decision_ids: list[str] = Field(default_factory=list)
    safe_summary: str = ""


class PriorStoryCompletionCandidateDecisionRequest(BaseModel):
    user_input: Optional[str] = None


class PriorStoryCompletionCandidateReviseRequest(BaseModel):
    user_input: str = ""
    revision_prompt: str = ""

    @root_validator(skip_on_failure=True)
    def user_input_or_revision_prompt_required(cls, values: dict) -> dict:
        user_input = str(values.get("user_input") or "").strip()
        revision_prompt = str(values.get("revision_prompt") or "").strip()
        if not user_input and not revision_prompt:
            raise ValueError("Prior story candidate revision requires user_input or revision_prompt.")
        return values


class PriorStoryCompletionCandidateResponse(BaseModel):
    success: bool = True
    candidate: PriorStoryCompletionCandidate
    decision: Optional[Any] = None
    candidate_decision: PriorStoryCompletionCandidateDecision | None = None
    write_plan: PriorStoryCompletionCandidateWritePlan | None = None
    lineage: PriorStoryCompletionLineage | None = None
    refresh: ContinuityResolutionRefreshResult | None = None


class ContinuityResolutionActionResponse(BaseModel):
    success: bool = True
    issue: ContinuityIssue | None = None
    candidate: PriorStoryCompletionCandidate | None = None
    decision: Optional[Any] = None
    refresh: ContinuityResolutionRefreshResult | None = None
    safe_summary: str = ""


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
