from __future__ import annotations

from pydantic import BaseModel, Field, validator


WRITER_QUALITY_SURFACE_SCHEMA_VERSION = "phase85e_m7_writer_quality_surface_v1"


class WriterQualitySurfaceOrdinaryView(BaseModel):
    schema_version: str = WRITER_QUALITY_SURFACE_SCHEMA_VERSION
    scene_id: str = ""
    project_id: str = ""
    chapter_id: str = ""
    scene_index: int = 0
    status: str = "not_available"
    confirmability: str = "unknown"
    visible_to_user: bool = True
    safe_user_summary: str = ""
    reader_experience_status: str = "not_available"
    psychology_visibility_status: str = "not_available"
    psychology_overexposure_status: str = "not_available"
    prose_style_status: str = "not_available"
    hook_payoff_status: str = "not_available"
    subtext_balance_status: str = "not_available"
    self_revision_status: str = "not_available"
    issue_count: int = 0
    blocking_issue_count: int = 0
    auto_repair_applied: bool = False
    user_action_required: bool = False
    user_action_options: list[str] = Field(default_factory=list)
    show_expert_entry: bool = False
    background_check_state: str = "unknown"

    @validator("user_action_options", pre=True)
    def list_fields_must_be_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterQualitySurfaceExpertView(BaseModel):
    schema_version: str = WRITER_QUALITY_SURFACE_SCHEMA_VERSION
    scene_id: str = ""
    writer_candidate_draft_id: str = ""
    graph_run_id: str = ""
    source_scene_prose_plan_id: str = ""
    source_psychology_visibility_plan_id: str = ""
    source_beat_sheet_id: str = ""
    source_reader_experience_report_id: str = ""
    source_psychology_overexposure_report_id: str = ""
    source_prose_style_inspection_report_id: str = ""
    source_hook_payoff_inspection_report_id: str = ""
    source_subtext_balance_inspection_report_id: str = ""
    source_writer_self_revision_report_id: str = ""
    writer_quality_issue_codes: list[str] = Field(default_factory=list)
    writer_self_revision_applied: bool = False
    eligible_for_commit_service_review: bool = False
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    requires_post_draft_gate_review: bool = True
    safe_trace_refs: list[str] = Field(default_factory=list)
    safe_status_summaries: list[str] = Field(default_factory=list)
    redaction_applied: bool = True

    @validator(
        "writer_quality_issue_codes",
        "safe_trace_refs",
        "safe_status_summaries",
        pre=True,
    )
    def list_fields_must_be_strings(cls, value) -> list[str]:
        return _unique_strings(_as_list(value))


class WriterQualitySurfaceResponse(BaseModel):
    schema_version: str = WRITER_QUALITY_SURFACE_SCHEMA_VERSION
    scene_id: str = ""
    ordinary: WriterQualitySurfaceOrdinaryView
    expert: WriterQualitySurfaceExpertView | None = None
    read_only: bool = True


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
        key = " ".join(text.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
