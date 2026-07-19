from typing import Any, Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.decision import Decision
from app.backend.models.scene_generation import (
    SceneMemoryExtraction,
    SceneQualityReport,
)


ALLOWED_SCENE_REVISION_STATUSES = {"candidate", "confirmed", "rejected"}
SCENE_WRITING_REPAIR_ENTRY_SCHEMA_VERSION = "phase85d_m5_scene_writing_repair_entry_v1"


class SceneRevisionCandidate(BaseModel):
    revision_id: str
    scene_id: str
    revision_prompt: str
    revision_intent: str
    base_scene_version_id: str = ""
    source_scene_status: str = ""
    revised_synopsis: str
    revised_prose_text: str
    change_summary: list[str] = Field(default_factory=list)
    possible_impacts: list[dict[str, Any]] = Field(default_factory=list)
    updated_story_information_notes: list[str] = Field(default_factory=list)
    hard_rule_warnings: list[dict[str, Any]] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    source_continuity_issue_id: str = ""
    resolution_lifecycle_status: str = ""
    confirmation_gate: dict[str, Any] = Field(default_factory=dict)
    memory_extraction: SceneMemoryExtraction
    quality_report: SceneQualityReport = Field(default_factory=SceneQualityReport)
    quality_report_id: str = ""
    force_hard_rule_override: bool = False
    source_revision_plan_id: str = ""
    source_revision_plan_signature: str = ""
    source_gate_run_id: str = ""
    source_analysis_id: str = ""
    source_repair_action_ids: list[str] = Field(default_factory=list)
    source_repair_action_signatures: list[str] = Field(default_factory=list)
    source_finding_ids: list[str] = Field(default_factory=list)
    source_finding_signatures: list[str] = Field(default_factory=list)
    structured_repair_entry_id: str = ""
    structured_repair_prompt_signature: str = ""
    repair_round_index: int = 0
    structured_repair_status: str = ""
    safe_repair_summary: str = ""
    status: str = "candidate"
    created_at: str = ""
    updated_at: str = ""

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        if value not in ALLOWED_SCENE_REVISION_STATUSES:
            raise ValueError("SceneRevisionCandidate.status is not allowed.")
        return value

    @validator(
        "source_repair_action_ids",
        "source_repair_action_signatures",
        "source_finding_ids",
        "source_finding_signatures",
        pre=True,
    )
    def trace_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("repair_round_index")
    def repair_round_index_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))


class SceneWritingRepairEntryResponse(BaseModel):
    schema_version: str = SCENE_WRITING_REPAIR_ENTRY_SCHEMA_VERSION
    success: bool = False
    status: str = ""
    scene_id: str = ""
    revision_id: str = ""
    revision_plan_id: str = ""
    revision_plan_signature: str = ""
    source_gate_run_id: str = ""
    source_analysis_id: str = ""
    round_index: int = 0
    executed_action_ids: list[str] = Field(default_factory=list)
    skipped_action_ids: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    candidate: Optional[dict[str, Any]] = None
    scene: Optional[dict[str, Any]] = None
    safe_user_summary: str = ""
    internal_trace_refs: list[str] = Field(default_factory=list)
    no_write_authority_summary: str = ""

    @validator(
        "executed_action_ids",
        "skipped_action_ids",
        "blocked_reasons",
        "internal_trace_refs",
        pre=True,
    )
    def response_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("round_index")
    def response_round_index_must_be_non_negative(cls, value: int) -> int:
        return max(0, int(value or 0))


class SceneReviseRequest(BaseModel):
    revision_prompt: str
    force_hard_rule_override: bool = False


class SceneConfirmRevisionRequest(BaseModel):
    revision_id: str
    user_input: Optional[str] = None
    accepted_abcd_runtime_issue_ids: list[str] = Field(default_factory=list)

    @validator("accepted_abcd_runtime_issue_ids", pre=True)
    def accepted_abcd_issue_ids_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class SceneRejectRevisionRequest(BaseModel):
    revision_id: str
    user_input: Optional[str] = None


class SceneRevisionResponse(BaseModel):
    success: bool = True
    scene: Optional[dict[str, Any]] = None
    candidate: Optional[dict[str, Any]] = None
    current_candidate: Optional[dict[str, Any]] = None
    revision_intent: str = ""
    quality_report: Optional[SceneQualityReport] = None
    decision: Optional[Decision] = None


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
