from typing import Any

from pydantic import BaseModel, Field, validator


ABCD_RUNTIME_OVERVIEW_VERSION_ID = "phase85b_m10_abcd_runtime_overview_v1"


class ABCDRuntimeParticipantOverview(BaseModel):
    character_id: str
    name: str = ""
    tier: str = "D"
    origin: str = ""
    selection_reason: str = ""
    context_depth: str = ""
    context_summary: str = ""
    source_memory_ids: list[str] = Field(default_factory=list)

    @validator("source_memory_ids", pre=True)
    def source_refs_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDRuntimeCharacterIntentOverview(BaseModel):
    character_id: str
    tier: str = "D"
    candidate_count: int = 0
    writer_ready_candidate_count: int = 0
    blocked_candidate_count: int = 0
    needs_gate_candidate_count: int = 0
    safe_summaries: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    source_risk_report_ids: list[str] = Field(default_factory=list)

    @validator("safe_summaries", "source_candidate_ids", "source_risk_report_ids", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDRuntimeRoleMemoryOverview(BaseModel):
    character_id: str
    tier: str = "D"
    entry_count: int = 0
    written_count: int = 0
    blocked_count: int = 0
    truth_statuses: list[str] = Field(default_factory=list)
    safe_summaries: list[str] = Field(default_factory=list)
    source_role_memory_entry_ids: list[str] = Field(default_factory=list)
    target_memory_record_ids: list[str] = Field(default_factory=list)

    @validator(
        "truth_statuses",
        "safe_summaries",
        "source_role_memory_entry_ids",
        "target_memory_record_ids",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDRuntimeGateIssueOverview(BaseModel):
    issue_id: str
    severity: str = "warning"
    issue_type: str = ""
    status: str = "open"
    requires_user_confirmation: bool = False
    safe_summary: str = ""
    evidence_refs: list[str] = Field(default_factory=list)

    @validator("evidence_refs", pre=True)
    def refs_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDRuntimeGateOverview(BaseModel):
    status: str = "not_run"
    has_blockers: bool = False
    requires_user_confirmation: bool = False
    unresolved_issue_count: int = 0
    accepted_issue_count: int = 0
    blocking_issue_ids: list[str] = Field(default_factory=list)
    requires_user_confirmation_issue_ids: list[str] = Field(default_factory=list)
    accepted_issue_ids: list[str] = Field(default_factory=list)
    issues: list[ABCDRuntimeGateIssueOverview] = Field(default_factory=list)
    safe_summary: str = ""

    @validator(
        "blocking_issue_ids",
        "requires_user_confirmation_issue_ids",
        "accepted_issue_ids",
        pre=True,
    )
    def refs_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class ABCDRuntimeOverviewResponse(BaseModel):
    project_id: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 0
    scene_status: str = ""
    ordinary_mode_safe: bool = True
    view_model_only: bool = True
    does_not_write_story_facts: bool = True
    participants: list[ABCDRuntimeParticipantOverview] = Field(default_factory=list)
    context_summary: dict[str, Any] = Field(default_factory=dict)
    intent_summary: dict[str, Any] = Field(default_factory=dict)
    character_intent_summaries: list[ABCDRuntimeCharacterIntentOverview] = Field(default_factory=list)
    memory_write_summary: dict[str, Any] = Field(default_factory=dict)
    role_memory_summaries: list[ABCDRuntimeRoleMemoryOverview] = Field(default_factory=list)
    gate_summary: ABCDRuntimeGateOverview = Field(default_factory=ABCDRuntimeGateOverview)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    version_id: str = ABCD_RUNTIME_OVERVIEW_VERSION_ID

    @validator("warnings", pre=True)
    def warnings_must_be_unique_strings(cls, value: Any) -> list[str]:
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
