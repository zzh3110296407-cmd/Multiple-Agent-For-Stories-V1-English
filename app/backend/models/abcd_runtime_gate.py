from typing import Any, Literal

from pydantic import BaseModel, Field, validator

from app.backend.models.continuity import CONTINUITY_ISSUE_CATEGORIES


ABCD_RUNTIME_GATE_VERSION_ID = "phase85b_m9_abcd_runtime_gate_v1"

ABCD_RUNTIME_GATE_MODES = {
    "pre_write_review",
    "draft_review",
    "temporary_confirmation",
    "final_confirmation",
    "post_commit_audit",
}


class ABCDRuntimeGateContext(BaseModel):
    abcd_runtime_gate_context_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    mode: str
    scene_participation_package_id: str = ""
    tiered_character_context_package_id: str = ""
    tiered_character_intent_package_id: str = ""
    abcd_story_information_package_id: str = ""
    tiered_scene_memory_write_plan_id: str = ""
    selected_character_ids: list[str] = Field(default_factory=list)
    selected_character_tiers: dict[str, str] = Field(default_factory=dict)
    source_memory_ids_by_character: dict[str, list[str]] = Field(default_factory=dict)
    action_candidate_ids_by_character: dict[str, list[str]] = Field(default_factory=dict)
    subjective_candidate_ids: list[str] = Field(default_factory=list)
    writer_story_information_item_ids: list[str] = Field(default_factory=list)
    role_scene_memory_entry_ids: list[str] = Field(default_factory=list)
    safe_context_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_RUNTIME_GATE_VERSION_ID

    @validator(
        "selected_character_ids",
        "subjective_candidate_ids",
        "writer_story_information_item_ids",
        "role_scene_memory_entry_ids",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("mode")
    def mode_must_be_known(cls, value: str) -> str:
        return value if value in ABCD_RUNTIME_GATE_MODES else "draft_review"


class ABCDContinuityRuntimeIssue(BaseModel):
    runtime_issue_id: str
    project_id: str
    scene_id: str
    chapter_id: str
    scene_index: int
    character_id: str = ""
    tier: str = ""
    issue_category: str
    mapped_continuity_category: str = "no_source_fact"
    severity: Literal["info", "warning", "blocking", "requires_user_confirmation"] = "warning"
    source_artifact_type: str = ""
    source_artifact_id: str = ""
    continuity_issue_id: str = ""
    suggested_resolution_option_types: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_RUNTIME_GATE_VERSION_ID

    @validator("mapped_continuity_category")
    def mapped_category_must_be_whitelisted(cls, value: str) -> str:
        return value if value in CONTINUITY_ISSUE_CATEGORIES else "no_source_fact"

    @validator("suggested_resolution_option_types", "warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDApparentContradictionLink(BaseModel):
    link_id: str
    project_id: str
    scene_id: str
    source_issue_id: str
    source_character_id: str = ""
    source_artifact_type: str = ""
    source_artifact_id: str = ""
    apparent_contradiction_id: str = ""
    narrative_debt_id: str = ""
    matched_claim_ids: list[str] = Field(default_factory=list)
    matched_perception_state_ids: list[str] = Field(default_factory=list)
    matched_psychology_trace_ids: list[str] = Field(default_factory=list)
    matched_expression_record_ids: list[str] = Field(default_factory=list)
    matched_narrative_intent_ids: list[str] = Field(default_factory=list)
    apparent_gate_action: str = ""
    safe_summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_RUNTIME_GATE_VERSION_ID

    @validator(
        "matched_claim_ids",
        "matched_perception_state_ids",
        "matched_psychology_trace_ids",
        "matched_expression_record_ids",
        "matched_narrative_intent_ids",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDObjectiveFactBoundaryReport(BaseModel):
    boundary_report_id: str
    project_id: str
    scene_id: str
    checked_candidate_ids: list[str] = Field(default_factory=list)
    checked_story_information_item_ids: list[str] = Field(default_factory=list)
    checked_role_memory_entry_ids: list[str] = Field(default_factory=list)
    blocked_objective_candidate_count: int = 0
    allowed_objective_candidate_count: int = 0
    subjective_claims_kept_subjective: bool = True
    perceptions_kept_subjective: bool = True
    lies_kept_non_objective: bool = True
    psychology_traces_not_written_as_events: bool = True
    expressions_not_written_as_objective_facts: bool = True
    no_unapproved_event_write: bool = True
    no_unapproved_state_change_write: bool = True
    no_unapproved_memory_record_write: bool = True
    blocked_candidate_ids: list[str] = Field(default_factory=list)
    blocked_role_memory_artifact_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_RUNTIME_GATE_VERSION_ID

    @validator(
        "checked_candidate_ids",
        "checked_story_information_item_ids",
        "checked_role_memory_entry_ids",
        "blocked_candidate_ids",
        "blocked_role_memory_artifact_ids",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDQualityGateRuntimeReport(BaseModel):
    quality_runtime_report_id: str
    project_id: str
    scene_id: str
    passed: bool = True
    character_knowledge_boundary_passed: bool = True
    role_presence_passed: bool = True
    subjective_fact_boundary_passed: bool = True
    memory_write_scope_passed: bool = True
    major_state_change_confirmation_passed: bool = True
    blocking_issue_ids: list[str] = Field(default_factory=list)
    warning_issue_ids: list[str] = Field(default_factory=list)
    requires_user_confirmation_issue_ids: list[str] = Field(default_factory=list)
    accepted_user_confirmation_issue_ids: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_RUNTIME_GATE_VERSION_ID

    @validator(
        "blocking_issue_ids",
        "warning_issue_ids",
        "requires_user_confirmation_issue_ids",
        "accepted_user_confirmation_issue_ids",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDRuntimeGateIntegrationAudit(BaseModel):
    audit_id: str
    project_id: str
    scene_id: str
    mode: str
    passed: bool = True
    continuity_gate_checked_abcd_runtime: bool = True
    apparent_gate_checked_abcd_runtime: bool = True
    quality_gate_checked_abcd_runtime: bool = True
    objective_fact_guard_checked_abcd_runtime: bool = True
    m8_role_memory_checked: bool = True
    no_authorial_intent_override: bool = True
    no_character_agent_rule_override: bool = True
    no_writer_direct_fact_override: bool = True
    no_unapproved_source_story_mutation: bool = True
    no_auto_resolution: bool = True
    no_prior_story_completion_candidate_auto_apply: bool = True
    checked_artifact_ids: list[str] = Field(default_factory=list)
    blocking_issue_ids: list[str] = Field(default_factory=list)
    requires_user_confirmation_issue_ids: list[str] = Field(default_factory=list)
    accepted_user_confirmation_issue_ids: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_RUNTIME_GATE_VERSION_ID

    @validator(
        "checked_artifact_ids",
        "blocking_issue_ids",
        "requires_user_confirmation_issue_ids",
        "accepted_user_confirmation_issue_ids",
        "violations",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("mode")
    def mode_must_be_known(cls, value: str) -> str:
        return value if value in ABCD_RUNTIME_GATE_MODES else "draft_review"


class ABCDGateReviewRequest(BaseModel):
    mode: str = "draft_review"
    force_refresh: bool = False
    accepted_issue_ids: list[str] = Field(default_factory=list)
    accept_requires_user_confirmation: bool = False
    user_confirmation_text: str = ""

    @validator("mode")
    def mode_must_be_known(cls, value: str) -> str:
        return value if value in ABCD_RUNTIME_GATE_MODES else "draft_review"

    @validator("accepted_issue_ids", pre=True)
    def accepted_issue_ids_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDRuntimeGateIssueAcceptance(BaseModel):
    acceptance_id: str
    project_id: str
    scene_id: str
    runtime_issue_id: str
    source: str = "review_request"
    user_confirmation_present: bool = True
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_RUNTIME_GATE_VERSION_ID


class ABCDGateReviewResult(BaseModel):
    success: bool = True
    mode: str
    passed: bool = True
    context: ABCDRuntimeGateContext
    continuity_runtime_issues: list[ABCDContinuityRuntimeIssue] = Field(default_factory=list)
    apparent_links: list[ABCDApparentContradictionLink] = Field(default_factory=list)
    objective_fact_boundary_report: ABCDObjectiveFactBoundaryReport
    quality_runtime_report: ABCDQualityGateRuntimeReport
    audit: ABCDRuntimeGateIntegrationAudit
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
