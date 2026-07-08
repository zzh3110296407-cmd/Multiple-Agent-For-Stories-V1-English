from typing import Any

from pydantic import BaseModel, Field, validator


PHASE85C_M6_WRITER_AGENT_VERSION = "phase85c_m6_writeragent_composite_wrapper_v1"


class WriterCandidateDraft(BaseModel):
    writer_candidate_draft_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    source_abcd_story_information_package_id: str
    source_writer_abcd_context_view_id: str
    source_ordered_story_information_package_id: str
    source_memory_curator_run_id: str = ""
    source_writer_planner_output_id: str = ""
    source_scene_prose_plan_id: str = ""
    source_psychology_visibility_plan_id: str = ""
    source_beat_sheet_id: str = ""
    source_prose_draft_package_id: str = ""
    source_reader_experience_report_id: str = ""
    source_psychology_overexposure_report_id: str = ""
    source_prose_style_inspection_report_id: str = ""
    source_hook_payoff_inspection_report_id: str = ""
    source_subtext_balance_inspection_report_id: str = ""
    source_writer_self_revision_report_id: str = ""
    writer_self_revision_applied: bool = False
    writer_quality_issue_codes: list[str] = Field(default_factory=list)
    candidate_synopsis: str
    candidate_prose: str
    used_story_information_item_ids: list[str] = Field(default_factory=list)
    ignored_do_not_use_item_ids: list[str] = Field(default_factory=list)
    character_ids_present: list[str] = Field(default_factory=list)
    truth_boundary_notes: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    can_write_scene_prose_directly: bool = False
    can_write_story_facts_directly: bool = False
    requires_post_draft_gate_review: bool = True
    post_draft_gate_request_id: str
    post_draft_gate_receipt_ids: list[str] = Field(default_factory=list)
    eligible_for_commit_service_review: bool = False
    created_at: str = ""
    version_id: str = PHASE85C_M6_WRITER_AGENT_VERSION

    @validator(
        "used_story_information_item_ids",
        "ignored_do_not_use_item_ids",
        "character_ids_present",
        "truth_boundary_notes",
        "post_draft_gate_receipt_ids",
        "writer_quality_issue_codes",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("candidate_only", "requires_post_draft_gate_review")
    def true_flags_must_remain_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("WriterCandidateDraft must remain candidate-only and gated.")
        return True

    @validator("can_write_scene_prose_directly", "can_write_story_facts_directly")
    def direct_write_flags_must_remain_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("WriterCandidateDraft cannot directly write prose or facts.")
        return False


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
