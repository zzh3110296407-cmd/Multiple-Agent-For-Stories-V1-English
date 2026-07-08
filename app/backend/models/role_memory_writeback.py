from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, validator


ROLE_MEMORY_WRITEBACK_VERSION_ID = "phase85b_m8_tiered_memory_writeback_v1"

TIERS = {"A", "B", "C", "D"}
ENTRY_TYPES = {
    "participation",
    "action",
    "observation",
    "heard_statement",
    "spoken_claim",
    "promise",
    "relationship_interaction",
    "state_note",
    "knowledge_update",
    "perception",
    "misinformation",
    "other",
}
MEMORY_DENSITIES = {"full", "medium", "compact", "minimal"}
ENTRY_STATUSES = {"planned", "written", "blocked", "skipped"}
SUPPORTED_ROLE_MEMORY_TRUTH_STATUSES = {
    "objective_fact",
    "unverified_claim",
    "rumor",
    "lie",
    "misinformation",
}


class TieredMemoryWritePolicy(BaseModel):
    policy_id: str = "phase85b_m8_default_policy"
    project_id: str = "local_project"
    write_only_after_commit: bool = True
    temporary_commit_status: Literal["provisional"] = "provisional"
    final_commit_status: Literal["active"] = "active"
    d_tier_minimal_memory_required: bool = True
    all_selected_participants_get_memory_considered: bool = True
    subjective_claims_non_objective: bool = True
    major_state_change_requires_confirmation: bool = True
    no_direct_character_state_mutation: bool = True
    no_direct_relationship_mutation: bool = True
    density_by_tier: dict[str, str] = Field(
        default_factory=lambda: {
            "A": "full",
            "B": "medium",
            "C": "compact",
            "D": "minimal",
        }
    )
    max_summary_chars_by_tier: dict[str, int] = Field(
        default_factory=lambda: {
            "A": 900,
            "B": 500,
            "C": 280,
            "D": 160,
        }
    )
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ROLE_MEMORY_WRITEBACK_VERSION_ID

    @validator(
        "write_only_after_commit",
        "d_tier_minimal_memory_required",
        "all_selected_participants_get_memory_considered",
        "subjective_claims_non_objective",
        "major_state_change_requires_confirmation",
        "no_direct_character_state_mutation",
        "no_direct_relationship_mutation",
    )
    def required_true_flags_must_stay_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M8 writeback policy safety flags must stay true.")
        return True

    @validator("density_by_tier")
    def density_must_cover_tiers(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = {str(key).upper(): str(item) for key, item in dict(value or {}).items()}
        defaults = {"A": "full", "B": "medium", "C": "compact", "D": "minimal"}
        for tier, density in defaults.items():
            if normalized.get(tier) not in MEMORY_DENSITIES:
                normalized[tier] = density
        return {tier: normalized[tier] for tier in ["A", "B", "C", "D"]}

    @validator("max_summary_chars_by_tier")
    def limits_must_cover_tiers(cls, value: dict[str, int]) -> dict[str, int]:
        normalized = {str(key).upper(): int(item) for key, item in dict(value or {}).items()}
        defaults = {"A": 900, "B": 500, "C": 280, "D": 160}
        for tier, limit in defaults.items():
            if int(normalized.get(tier, 0)) < 40:
                normalized[tier] = limit
        return {tier: normalized[tier] for tier in ["A", "B", "C", "D"]}


class RoleSceneMemoryEntry(BaseModel):
    role_scene_memory_entry_id: str
    project_id: str
    scene_id: str
    chapter_id: str
    scene_index: int
    character_id: str
    character_name: str = ""
    tier: Literal["A", "B", "C", "D"]
    entry_type: Literal[
        "participation",
        "action",
        "observation",
        "heard_statement",
        "spoken_claim",
        "promise",
        "relationship_interaction",
        "state_note",
        "knowledge_update",
        "perception",
        "misinformation",
        "other",
    ] = "participation"
    memory_summary: str
    known_facts: list[str] = Field(default_factory=list)
    perceived_facts: list[str] = Field(default_factory=list)
    claims_made: list[str] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    commitments_or_tasks: list[str] = Field(default_factory=list)
    continuity_flags: list[str] = Field(default_factory=list)
    truth_status: Literal[
        "objective_fact",
        "unverified_claim",
        "rumor",
        "lie",
        "misinformation",
    ] = "objective_fact"
    objective_truth: bool = True
    source_event_ids: list[str] = Field(default_factory=list)
    source_state_change_ids: list[str] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    source_intention_candidate_ids: list[str] = Field(default_factory=list)
    source_story_information_item_ids: list[str] = Field(default_factory=list)
    target_memory_record_id: str = ""
    memory_density: Literal["full", "medium", "compact", "minimal"] = "minimal"
    status: Literal["planned", "written", "blocked", "skipped"] = "planned"
    skip_reason: str = ""
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ROLE_MEMORY_WRITEBACK_VERSION_ID

    @validator(
        "known_facts",
        "perceived_facts",
        "claims_made",
        "actions_taken",
        "commitments_or_tasks",
        "continuity_flags",
        "source_event_ids",
        "source_state_change_ids",
        "source_memory_ids",
        "source_intention_candidate_ids",
        "source_story_information_item_ids",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("objective_truth", always=True)
    def subjective_entries_must_be_non_objective(
        cls,
        value: bool,
        values: dict[str, Any],
    ) -> bool:
        truth_status = values.get("truth_status")
        if truth_status in {"unverified_claim", "rumor", "lie", "misinformation"}:
            return False
        return bool(value)


class TieredSceneMemoryWritePlan(BaseModel):
    tiered_scene_memory_write_plan_id: str
    project_id: str
    scene_id: str
    chapter_id: str
    scene_index: int
    scene_participation_package_id: str = ""
    tiered_character_intent_package_id: str = ""
    abcd_story_information_package_id: str = ""
    commit_type: Literal["confirmed", "revised", "temporary_confirmed"]
    target_memory_status: Literal["active", "provisional"]
    role_memory_entry_ids: list[str] = Field(default_factory=list)
    target_memory_record_ids: list[str] = Field(default_factory=list)
    a_entry_count: int = 0
    b_entry_count: int = 0
    c_entry_count: int = 0
    d_entry_count: int = 0
    objective_memory_count: int = 0
    subjective_memory_count: int = 0
    blocked_memory_count: int = 0
    requires_user_confirmation_count: int = 0
    no_pre_commit_write: bool = True
    no_character_state_mutation: bool = True
    no_scene_prose_mutation: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ROLE_MEMORY_WRITEBACK_VERSION_ID

    @validator(
        "role_memory_entry_ids",
        "target_memory_record_ids",
        "warnings",
        pre=True,
    )
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator(
        "no_pre_commit_write",
        "no_character_state_mutation",
        "no_scene_prose_mutation",
    )
    def safety_flags_must_stay_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M8 plan safety flags must stay true.")
        return True


class RoleMemoryWriteAudit(BaseModel):
    role_memory_write_audit_id: str
    project_id: str
    scene_id: str
    chapter_id: str
    scene_index: int
    tiered_scene_memory_write_plan_id: str
    no_pre_commit_memory_write: bool = True
    no_scene_prose_mutation: bool = True
    no_character_state_mutation: bool = True
    no_relationship_mutation: bool = True
    no_world_canvas_mutation: bool = True
    no_framework_mutation: bool = True
    all_entries_have_tier: bool = True
    all_entries_have_source_scene: bool = True
    all_subjective_entries_non_objective: bool = True
    d_tier_entries_minimal: bool = True
    a_tier_major_changes_not_auto_applied: bool = True
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["pass", "warning", "failed"] = "pass"
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ROLE_MEMORY_WRITEBACK_VERSION_ID

    @validator("issues", "warnings", pre=True)
    def lists_must_be_unique_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class TieredSceneMemoryWritebackResponse(BaseModel):
    plan: TieredSceneMemoryWritePlan
    entries: list[RoleSceneMemoryEntry] = Field(default_factory=list)
    memory_records: list[dict[str, Any]] = Field(default_factory=list)
    audits: list[RoleMemoryWriteAudit] = Field(default_factory=list)
    policy: TieredMemoryWritePolicy
    warnings: list[str] = Field(default_factory=list)


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
