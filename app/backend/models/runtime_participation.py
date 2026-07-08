from typing import Any

from pydantic import BaseModel, Field


class ABCDParticipationPolicy(BaseModel):
    policy_id: str = "phase85b_m1_abcd_participation_policy"
    version_id: str = "phase85b_m1_abcd_participation_policy_v1"
    a_chapter_explicit: bool = True
    b_chapter_explicit: bool = True
    c_chapter_explicit: bool = False
    d_chapter_explicit: bool = False
    c_d_allowed_as_chapter_function_needs: bool = True
    c_d_selected_by_scene_agent: bool = True
    all_confirmed_roles_are_story_eligible: bool = True
    c_d_detailed_context_forbidden_in_chapter_agent: bool = True
    scene_agent_must_explain_c_d_selection: bool = True
    unselected_c_d_must_not_enter_scene_context: bool = True
    d_tier_memory_is_minimal_but_persistent: bool = True
    authorial_intent_is_soft_intent_only: bool = True
    contract_is_policy_only: bool = True
    safe_summary: str = ""
    created_at: str = ""


class RoleTierRuntimeRule(BaseModel):
    tier: str
    chapter_explicit_allowed: bool = False
    chapter_function_need_allowed: bool = False
    scene_selectable: bool = True
    context_depth: str = "compact"
    major_change_requires_confirmation: bool = False
    does_not_auto_enter_main_cast: bool = False
    memory_policy: str = "persistent"
    safe_summary: str = ""


class RoleRuntimeParticipationContract(BaseModel):
    contract_id: str = "phase85b_m1_role_runtime_participation_contract"
    project_id: str = "local_project"
    tier_rules: dict[str, RoleTierRuntimeRule] = Field(default_factory=dict)
    chapter_level_rules: dict[str, Any] = Field(default_factory=dict)
    scene_level_rules: dict[str, Any] = Field(default_factory=dict)
    memory_rules: dict[str, Any] = Field(default_factory=dict)
    gate_rules: dict[str, Any] = Field(default_factory=dict)
    terminology_rules: dict[str, Any] = Field(default_factory=dict)
    can_write_story_facts: bool = False
    contract_is_policy_only: bool = True
    safe_summary: str = ""
    created_at: str = ""


class ABCDRuntimeGapAudit(BaseModel):
    audit_id: str = "phase85b_m1_runtime_gap_audit"
    checked_modules: list[str] = Field(default_factory=list)
    chapter_plan_a_only_or_ab_missing_detected: bool = False
    chapter_cd_function_needs_missing_or_incomplete: bool = False
    scene_generation_a_only_detected: bool = False
    sceneagent_cd_selection_missing: bool = False
    scene_memory_supports_active_character_ids: bool = False
    memory_retrieval_supports_active_character_ids: bool = False
    character_context_builder_exists: bool = False
    role_tier_budget_service_exists: bool = False
    role_tier_budget_decreasing_a_b_c_d: bool = False
    writer_story_information_integration_exists: bool = False
    tiered_memory_retrieval_hit_tracking_missing: bool = False
    tiered_memory_writeback_missing: bool = False
    frontend_abcd_runtime_surfaces_missing: bool = False
    gap_to_milestone_map: dict[str, str] = Field(default_factory=dict)
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""


class RuntimeRoleEligibilityReport(BaseModel):
    report_id: str = "phase85b_m1_runtime_role_eligibility_report"
    project_id: str = "local_project"
    confirmed_a_ids: list[str] = Field(default_factory=list)
    confirmed_b_ids: list[str] = Field(default_factory=list)
    confirmed_c_ids: list[str] = Field(default_factory=list)
    confirmed_d_ids: list[str] = Field(default_factory=list)
    eligible_for_chapter_explicit_ids: list[str] = Field(default_factory=list)
    eligible_for_scene_selection_ids: list[str] = Field(default_factory=list)
    cd_function_need_only_in_chapter: bool = True
    archived_or_invalid_ids: list[str] = Field(default_factory=list)
    source_character_count: int = 0
    safe_summary: str = ""
    created_at: str = ""


class TieredRuntimeBoundaryReport(BaseModel):
    report_id: str = "phase85b_m1_tiered_runtime_boundary_report"
    chapter_layer_allowed: dict[str, Any] = Field(default_factory=dict)
    scene_layer_allowed: dict[str, Any] = Field(default_factory=dict)
    memory_write_boundary: dict[str, Any] = Field(default_factory=dict)
    candidate_only_objects: list[str] = Field(default_factory=list)
    authority_objects: list[str] = Field(default_factory=list)
    view_model_objects: list[str] = Field(default_factory=list)
    prohibited_runtime_shortcuts: list[str] = Field(default_factory=list)
    inherited_phase85a_contracts: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""
