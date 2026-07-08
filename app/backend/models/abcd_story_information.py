from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.scene_generation import (
    OrderedStoryInformationPackage,
    StoryInformationItem,
)


ABCD_STORY_INFORMATION_VERSION_ID = "phase85b_m7_writer_story_info_abcd_v1"
M7_SEMANTIC_TYPES = {
    "character_expression",
    "subjective_claim_hint",
    "participant_continuity_constraint",
    "do_not_use",
}
WRITER_BUCKETS = {
    "opening_context",
    "scene_progression",
    "character_turns",
    "do_not_include",
}


class CharacterIntentStoryInformationItem(BaseModel):
    item_id: str
    project_id: str
    abcd_story_information_package_id: str
    source_tiered_character_intent_package_id: str
    source_scene_participation_package_id: str = ""
    source_psychology_trace_id: str = ""
    source_action_intention_candidate_id: str = ""
    source_risk_report_id: str = ""
    chapter_id: str
    scene_id: str = ""
    scene_index: int
    character_id: str
    tier: Literal["A", "B", "C", "D"]
    truth_status: str = "objective_candidate"
    risk_level: Literal["none", "low", "medium", "high", "blocking"] = "low"
    m7_semantic_type: Literal[
        "character_expression",
        "subjective_claim_hint",
        "participant_continuity_constraint",
        "do_not_use",
    ] = "character_expression"
    writer_bucket: Literal[
        "opening_context",
        "scene_progression",
        "character_turns",
        "do_not_include",
    ] = "character_turns"
    base_story_information_item: StoryInformationItem
    safe_summary: str = ""
    writer_instruction: str = ""
    safe_for_writer: bool = True
    candidate_only: bool = True
    no_story_fact_written: bool = True
    can_write_objective_fact_directly: bool = False
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_STORY_INFORMATION_VERSION_ID

    @validator("warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("candidate_only", "no_story_fact_written")
    def true_safety_flags_must_remain_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 story information items must remain candidate-only/no-write.")
        return True

    @validator("can_write_objective_fact_directly")
    def cannot_write_objective_fact(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("M7 story information items cannot write objective facts.")
        return False

    @validator("base_story_information_item")
    def base_item_must_match_safety(cls, value: StoryInformationItem, values: dict[str, Any]) -> StoryInformationItem:
        semantic_type = values.get("m7_semantic_type")
        if semantic_type == "do_not_use" and value.priority != "do_not_use":
            raise ValueError("do_not_use semantic items must use do_not_use priority.")
        return value


class ABCDStoryInformationPackage(BaseModel):
    abcd_story_information_package_id: str
    project_id: str
    source_tiered_character_intent_package_id: str
    source_scene_participation_package_id: str = ""
    source_scene_memory_pack_id: str = ""
    source_tiered_character_context_package_id: str = ""
    chapter_id: str
    scene_id: str = ""
    scene_index: int
    active_character_ids: list[str] = Field(default_factory=list)
    related_character_ids: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)
    writer_ready_item_ids: list[str] = Field(default_factory=list)
    do_not_use_item_ids: list[str] = Field(default_factory=list)
    constraint_item_ids: list[str] = Field(default_factory=list)
    tier_counts: dict[str, int] = Field(default_factory=dict)
    priority_counts: dict[str, int] = Field(default_factory=dict)
    semantic_type_counts: dict[str, int] = Field(default_factory=dict)
    writer_ready: bool = False
    ordered_story_information_package: OrderedStoryInformationPackage = Field(
        default_factory=OrderedStoryInformationPackage
    )
    writer_view_id: str = ""
    integration_report_id: str = ""
    candidate_only: bool = True
    no_story_fact_written: bool = True
    does_not_write_generic_story_information: bool = True
    no_writer_invocation: bool = True
    status: Literal["ready", "warning", "blocked"] = "ready"
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_STORY_INFORMATION_VERSION_ID

    @validator(
        "active_character_ids",
        "related_character_ids",
        "item_ids",
        "writer_ready_item_ids",
        "do_not_use_item_ids",
        "constraint_item_ids",
        "warnings",
        pre=True,
    )
    def package_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator(
        "candidate_only",
        "no_story_fact_written",
        "does_not_write_generic_story_information",
        "no_writer_invocation",
    )
    def package_safety_flags_must_stay_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 package safety flags must remain true.")
        return True


class WriterABCDContextView(BaseModel):
    writer_view_id: str
    abcd_story_information_package_id: str
    project_id: str
    chapter_id: str
    scene_id: str = ""
    scene_index: int
    related_character_ids: list[str] = Field(default_factory=list)
    opening_context: list[str] = Field(default_factory=list)
    scene_progression: list[str] = Field(default_factory=list)
    character_turns: list[str] = Field(default_factory=list)
    required_reveals: list[str] = Field(default_factory=list)
    emotional_beats: list[str] = Field(default_factory=list)
    ending_beat: list[str] = Field(default_factory=list)
    do_not_include: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    no_raw_psychology_chain: bool = True
    no_unapproved_fact_write: bool = True
    safe_summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_STORY_INFORMATION_VERSION_ID

    @validator(
        "related_character_ids",
        "opening_context",
        "scene_progression",
        "character_turns",
        "required_reveals",
        "emotional_beats",
        "ending_beat",
        "do_not_include",
        "guardrails",
        pre=True,
    )
    def view_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("no_raw_psychology_chain", "no_unapproved_fact_write")
    def view_guard_flags_must_stay_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 writer view safety flags must remain true.")
        return True


class ABCDStoryInformationIntegrationReport(BaseModel):
    integration_report_id: str
    abcd_story_information_package_id: str
    project_id: str
    source_tiered_character_intent_package_id: str
    chapter_id: str
    scene_id: str = ""
    scene_index: int
    source_candidate_count: int = 0
    converted_item_count: int = 0
    selected_character_ids: list[str] = Field(default_factory=list)
    represented_character_ids: list[str] = Field(default_factory=list)
    blocked_candidate_ids: list[str] = Field(default_factory=list)
    do_not_use_item_ids: list[str] = Field(default_factory=list)
    truth_status_counts: dict[str, int] = Field(default_factory=dict)
    priority_counts: dict[str, int] = Field(default_factory=dict)
    semantic_type_counts: dict[str, int] = Field(default_factory=dict)
    story_fact_file_delta: dict[str, dict[str, str]] = Field(default_factory=dict)
    no_story_fact_file_mutation: bool = True
    no_generic_story_information_write: bool = True
    no_writer_invocation: bool = True
    status: Literal["ready", "warning", "blocked"] = "ready"
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ABCD_STORY_INFORMATION_VERSION_ID

    @validator(
        "selected_character_ids",
        "represented_character_ids",
        "blocked_candidate_ids",
        "do_not_use_item_ids",
        "issues",
        "warnings",
        pre=True,
    )
    def report_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator(
        "no_story_fact_file_mutation",
        "no_generic_story_information_write",
        "no_writer_invocation",
    )
    def report_safety_flags_must_stay_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 integration report safety flags must remain true.")
        return True


class ABCDStoryInformationPackageBuildRequest(BaseModel):
    tiered_character_intent_package_id: str
    force_refresh: bool = False


class ABCDStoryInformationPackageBuildResponse(BaseModel):
    package: ABCDStoryInformationPackage
    items: list[CharacterIntentStoryInformationItem] = Field(default_factory=list)
    writer_view: WriterABCDContextView
    integration_report: ABCDStoryInformationIntegrationReport
    warnings: list[str] = Field(default_factory=list)


class ABCDStoryInformationPackageReadResponse(BaseModel):
    package: Optional[ABCDStoryInformationPackage] = None
    items: list[CharacterIntentStoryInformationItem] = Field(default_factory=list)
    writer_view: Optional[WriterABCDContextView] = None
    integration_report: Optional[ABCDStoryInformationIntegrationReport] = None
    warnings: list[str] = Field(default_factory=list)


class ABCDStoryInformationMergePreviewRequest(BaseModel):
    base_scene_information: dict[str, Any] = Field(default_factory=dict)


class ABCDStoryInformationMergePreviewResponse(BaseModel):
    abcd_story_information_package_id: str
    merged_scene_information: dict[str, Any] = Field(default_factory=dict)
    added_story_information_item_ids: list[str] = Field(default_factory=list)
    ordered_story_information_package: OrderedStoryInformationPackage = Field(
        default_factory=OrderedStoryInformationPackage
    )
    no_write: bool = True
    warnings: list[str] = Field(default_factory=list)

    @validator("added_story_information_item_ids", "warnings", pre=True)
    def preview_lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("no_write")
    def preview_no_write_must_stay_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 merge preview must be no-write.")
        return True


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
