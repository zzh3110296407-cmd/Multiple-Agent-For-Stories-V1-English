from typing import Literal

from pydantic import BaseModel, Field

from .plugin_runtime import (
    PluginCheckpoint,
    PluginCheckpointDecision,
    PluginOutputArtifact,
    PluginOutputArtifactVersion,
    PluginRun,
    PluginRunSafetyReport,
    PluginRunStep,
    PluginRuntimeStrictRequest,
)


ScriptForgingStage = Literal[
    "context_created",
    "shape_suggested",
    "shape_checkpoint_pending",
    "shape_confirmed",
    "prompt_package_created",
    "prompt_package_checkpoint_pending",
    "prompt_package_confirmed",
    "scene_outline_created",
    "scene_outline_checkpoint_pending",
    "scene_outline_confirmed",
    "screenplay_draft_created",
    "screenplay_draft_checkpoint_pending",
    "screenplay_draft_confirmed",
    "self_check_created",
    "revision_candidate_created",
    "storyboard_package_created",
    "storyboard_package_checkpoint_pending",
    "storyboard_package_confirmed",
    "digital_asset_package_created",
    "digital_asset_package_checkpoint_pending",
    "digital_asset_package_confirmed",
    "blocked",
]

ScriptForgingArtifactStatus = Literal[
    "draft",
    "checkpoint_pending",
    "confirmed",
    "revision_requested",
    "rejected",
    "blocked",
]

ScriptForgingCheckpointKind = Literal[
    "shape_direction_confirmation",
    "adaptation_prompt_package_confirmation",
    "scene_outline_confirmation",
    "screenplay_draft_confirmation",
    "storyboard_package_confirmation",
    "digital_asset_package_confirmation",
]

ScreenplaySelfCheckStatus = Literal["created", "passed", "needs_revision", "blocked"]
ScreenplayRevisionCandidateStatus = Literal["created", "superseded", "rejected"]


class ScriptForgingDecisionRequest(PluginRuntimeStrictRequest):
    safe_user_note: str = ""
    requested_changes: list[str] = Field(default_factory=list)


class ScriptForgingRunContext(BaseModel):
    script_forging_run_context_id: str
    plugin_run_id: str
    project_id: str
    plugin_id: str
    final_story_package_snapshot_id: str
    m4_input_checkpoint_id: str
    m4_input_checkpoint_decision_id: str
    source_manifest_id: str
    source_package_snapshot_hash: str
    complete_story_text_hash: str
    complete_story_text_char_count: int
    source_ref_count: int
    chapter_count: int
    scene_count: int
    character_count: int
    relationship_count: int
    key_event_count: int
    style_and_tone_summary: str
    world_canvas_summary_keys: list[str] = Field(default_factory=list)
    known_residual_codes: list[str] = Field(default_factory=list)
    reads_only_final_story_package_snapshot: bool = True
    mutates_source_story: bool = False
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class ScriptForgingShapeSuggestion(BaseModel):
    shape_id: str
    title: str
    adaptation_form: str
    target_runtime_band: str
    structure_strategy: str
    point_of_view_strategy: str
    preserve_elements: list[str] = Field(default_factory=list)
    compress_elements: list[str] = Field(default_factory=list)
    omit_or_forbid_elements: list[str] = Field(default_factory=list)
    rationale: str
    risk_codes: list[str] = Field(default_factory=list)
    source_ref_ids: list[str] = Field(default_factory=list)


class ScriptShapePackage(BaseModel):
    script_shape_package_id: str
    plugin_run_id: str
    context_id: str
    project_id: str
    final_story_package_snapshot_id: str
    package_status: ScriptForgingArtifactStatus
    suggestions: list[ScriptForgingShapeSuggestion] = Field(default_factory=list)
    recommended_shape_id: str
    checkpoint_id: str
    output_artifact_id: str
    output_artifact_version_id: str
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    created_at: str
    updated_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class ScriptAdaptationPromptPackage(BaseModel):
    script_adaptation_prompt_package_id: str
    plugin_run_id: str
    context_id: str
    script_shape_package_id: str
    selected_shape_id: str
    project_id: str
    final_story_package_snapshot_id: str
    package_status: ScriptForgingArtifactStatus
    m6_input_contract: dict = Field(default_factory=dict)
    adaptation_brief: dict = Field(default_factory=dict)
    preserve_instructions: list[str] = Field(default_factory=list)
    compression_instructions: list[str] = Field(default_factory=list)
    omission_and_forbidden_instructions: list[str] = Field(default_factory=list)
    format_constraints: list[str] = Field(default_factory=list)
    source_reference_policy: dict = Field(default_factory=dict)
    safety_instructions: list[str] = Field(default_factory=list)
    checkpoint_id: str
    output_artifact_id: str
    output_artifact_version_id: str
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    created_at: str
    updated_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class ScriptForgingCheckpoint(BaseModel):
    script_forging_checkpoint_id: str
    plugin_run_id: str
    checkpoint_kind: ScriptForgingCheckpointKind
    plugin_checkpoint_id: str
    plugin_checkpoint_decision_id: str = ""
    source_domain_artifact_id: str
    confirms_plugin_step_only: bool = True
    does_not_modify_final_story_package: bool = True
    does_not_modify_source_story: bool = True
    created_at: str
    updated_at: str
    safe_summary: str


class ScriptForgingSelfRiskNote(BaseModel):
    script_forging_risk_note_id: str
    plugin_run_id: str
    context_id: str
    script_shape_package_id: str
    script_adaptation_prompt_package_id: str = ""
    risk_codes: list[str] = Field(default_factory=list)
    license_template_risks: list[str] = Field(default_factory=list)
    compression_risks: list[str] = Field(default_factory=list)
    source_fidelity_risks: list[str] = Field(default_factory=list)
    medium_mismatch_risks: list[str] = Field(default_factory=list)
    prompt_safety_risks: list[str] = Field(default_factory=list)
    mitigations: list[str] = Field(default_factory=list)
    created_at: str
    safe_summary: str


class SceneOutlineUnit(BaseModel):
    outline_unit_id: str
    scene_number: int
    title: str
    dramatic_function: str
    location_hint: str
    character_focus_ids: list[str] = Field(default_factory=list)
    preserved_element_refs: list[str] = Field(default_factory=list)
    compression_notes: list[str] = Field(default_factory=list)
    source_ref_ids: list[str] = Field(default_factory=list)


class SceneOutlineArtifact(BaseModel):
    scene_outline_id: str
    plugin_run_id: str
    script_forging_run_context_id: str
    script_shape_package_id: str
    script_adaptation_prompt_package_id: str
    selected_shape_id: str
    project_id: str
    final_story_package_snapshot_id: str
    outline_status: ScriptForgingArtifactStatus
    outline_units: list[SceneOutlineUnit] = Field(default_factory=list)
    checkpoint_id: str
    plugin_output_artifact_id: str
    plugin_output_artifact_version_id: str
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    created_at: str
    updated_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class ScreenplayDialogueBlock(BaseModel):
    speaker_hint: str
    line: str
    source_ref_ids: list[str] = Field(default_factory=list)


class ScreenplaySceneScriptUnit(BaseModel):
    script_unit_id: str
    scene_number: int
    scene_heading: str
    action_lines: list[str] = Field(default_factory=list)
    dialogue_blocks: list[ScreenplayDialogueBlock] = Field(default_factory=list)
    transition_hint: str = ""
    source_ref_ids: list[str] = Field(default_factory=list)


class ScreenplayDraftArtifact(BaseModel):
    screenplay_draft_id: str
    plugin_run_id: str
    script_forging_run_context_id: str
    script_shape_package_id: str
    script_adaptation_prompt_package_id: str
    scene_outline_id: str
    selected_shape_id: str
    project_id: str
    final_story_package_snapshot_id: str
    draft_status: ScriptForgingArtifactStatus
    script_units: list[ScreenplaySceneScriptUnit] = Field(default_factory=list)
    checkpoint_id: str
    plugin_output_artifact_id: str
    plugin_output_artifact_version_id: str
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    created_at: str
    updated_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class ScreenplaySelfCheckReport(BaseModel):
    self_check_report_id: str
    plugin_run_id: str
    script_forging_run_context_id: str
    script_adaptation_prompt_package_id: str
    scene_outline_id: str
    screenplay_draft_id: str
    project_id: str
    final_story_package_snapshot_id: str
    report_status: ScreenplaySelfCheckStatus
    preserved_element_coverage: list[dict] = Field(default_factory=list)
    forbidden_change_checks: list[dict] = Field(default_factory=list)
    continuity_checks: list[dict] = Field(default_factory=list)
    drift_checks: list[dict] = Field(default_factory=list)
    format_checks: list[dict] = Field(default_factory=list)
    safety_checks: list[dict] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    requires_revision_candidate: bool = False
    plugin_output_artifact_id: str
    plugin_output_artifact_version_id: str
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class ScreenplayRevisionCandidate(BaseModel):
    revision_candidate_id: str
    plugin_run_id: str
    script_forging_run_context_id: str
    script_adaptation_prompt_package_id: str
    scene_outline_id: str
    screenplay_draft_id: str
    self_check_report_id: str
    project_id: str
    final_story_package_snapshot_id: str
    candidate_status: ScreenplayRevisionCandidateStatus
    proposed_changes: list[dict] = Field(default_factory=list)
    does_not_overwrite_screenplay_draft: bool = True
    plugin_output_artifact_id: str
    plugin_output_artifact_version_id: str
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class KeyStoryboardArtifact(BaseModel):
    key_storyboard_artifact_id: str
    plugin_run_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    artifact_status: ScriptForgingArtifactStatus
    scene_number: int
    panel_label: str
    visual_function: str
    camera_intent: str
    composition_summary: str
    continuity_refs: list[str] = Field(default_factory=list)
    source_ref_ids: list[str] = Field(default_factory=list)
    generation_mode: str = "deterministic_storyboard_plan"
    provenance: dict = Field(default_factory=dict)
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class SceneStoryboardArtifact(BaseModel):
    scene_storyboard_artifact_id: str
    plugin_run_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    artifact_status: ScriptForgingArtifactStatus
    scene_number: int
    beat_label: str
    panel_ids: list[str] = Field(default_factory=list)
    visual_continuity_notes: list[str] = Field(default_factory=list)
    source_ref_ids: list[str] = Field(default_factory=list)
    generation_mode: str = "deterministic_storyboard_plan"
    provenance: dict = Field(default_factory=dict)
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class ShotListArtifact(BaseModel):
    shot_list_artifact_id: str
    plugin_run_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    artifact_status: ScriptForgingArtifactStatus
    shots: list[dict] = Field(default_factory=list)
    generation_mode: str = "deterministic_shot_list_plan"
    provenance: dict = Field(default_factory=dict)
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class StoryboardPackage(BaseModel):
    storyboard_package_id: str
    plugin_run_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    package_status: ScriptForgingArtifactStatus
    key_storyboard_artifact_ids: list[str] = Field(default_factory=list)
    scene_storyboard_artifact_ids: list[str] = Field(default_factory=list)
    shot_list_artifact_id: str
    checkpoint_id: str
    plugin_output_artifact_id: str
    plugin_output_artifact_version_id: str
    generation_mode: str = "deterministic_storyboard_plan"
    provenance: dict = Field(default_factory=dict)
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    created_at: str
    updated_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class CharacterAssetList(BaseModel):
    character_asset_list_id: str
    plugin_run_id: str
    source_digital_asset_package_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    artifact_status: ScriptForgingArtifactStatus
    assets: list[dict] = Field(default_factory=list)
    generation_mode: str = "deterministic_asset_plan"
    provenance: dict = Field(default_factory=dict)
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class LocationAssetList(BaseModel):
    location_asset_list_id: str
    plugin_run_id: str
    source_digital_asset_package_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    artifact_status: ScriptForgingArtifactStatus
    assets: list[dict] = Field(default_factory=list)
    generation_mode: str = "deterministic_asset_plan"
    provenance: dict = Field(default_factory=dict)
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class PropAssetList(BaseModel):
    prop_asset_list_id: str
    plugin_run_id: str
    source_digital_asset_package_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    artifact_status: ScriptForgingArtifactStatus
    assets: list[dict] = Field(default_factory=list)
    generation_mode: str = "deterministic_asset_plan"
    provenance: dict = Field(default_factory=dict)
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class MotifAssetList(BaseModel):
    motif_asset_list_id: str
    plugin_run_id: str
    source_digital_asset_package_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    artifact_status: ScriptForgingArtifactStatus
    assets: list[dict] = Field(default_factory=list)
    generation_mode: str = "deterministic_asset_plan"
    provenance: dict = Field(default_factory=dict)
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class CostumeContinuityList(BaseModel):
    costume_continuity_list_id: str
    plugin_run_id: str
    source_digital_asset_package_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    artifact_status: ScriptForgingArtifactStatus
    assets: list[dict] = Field(default_factory=list)
    generation_mode: str = "deterministic_asset_plan"
    provenance: dict = Field(default_factory=dict)
    created_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class DigitalAssetPackage(BaseModel):
    digital_asset_package_id: str
    plugin_run_id: str
    source_storyboard_package_id: str
    source_scene_outline_artifact_id: str
    source_screenplay_draft_artifact_id: str
    source_screenplay_self_check_report_id: str
    source_revision_candidate_id: str = ""
    project_id: str
    final_story_package_snapshot_id: str
    package_status: ScriptForgingArtifactStatus
    character_asset_list_id: str
    location_asset_list_id: str
    prop_asset_list_id: str
    motif_asset_list_id: str
    costume_continuity_list_id: str
    checkpoint_id: str
    plugin_output_artifact_id: str
    plugin_output_artifact_version_id: str
    generation_mode: str = "deterministic_asset_plan"
    provenance: dict = Field(default_factory=dict)
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    created_at: str
    updated_at: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)


class ScriptForgingContextResponse(BaseModel):
    context: ScriptForgingRunContext
    plugin_run: PluginRun
    safe_summary: str


class ScriptShapePackageResponse(BaseModel):
    shape_package: ScriptShapePackage
    plugin_run: PluginRun
    checkpoint: ScriptForgingCheckpoint
    plugin_checkpoint: PluginCheckpoint
    output_artifact: PluginOutputArtifact
    output_artifact_version: PluginOutputArtifactVersion
    step: PluginRunStep
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class ScriptAdaptationPromptPackageResponse(BaseModel):
    prompt_package: ScriptAdaptationPromptPackage
    plugin_run: PluginRun
    checkpoint: ScriptForgingCheckpoint
    plugin_checkpoint: PluginCheckpoint
    output_artifact: PluginOutputArtifact
    output_artifact_version: PluginOutputArtifactVersion
    step: PluginRunStep
    risk_note: ScriptForgingSelfRiskNote
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class ScriptForgingDecisionResponse(BaseModel):
    plugin_run: PluginRun
    plugin_checkpoint: PluginCheckpoint
    decision: PluginCheckpointDecision
    script_checkpoint: ScriptForgingCheckpoint
    shape_package: ScriptShapePackage | None = None
    prompt_package: ScriptAdaptationPromptPackage | None = None
    scene_outline: SceneOutlineArtifact | None = None
    screenplay_draft: ScreenplayDraftArtifact | None = None
    storyboard_package: StoryboardPackage | None = None
    digital_asset_package: DigitalAssetPackage | None = None
    risk_note: ScriptForgingSelfRiskNote | None = None
    step: PluginRunStep
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class ScriptForgingRiskNoteResponse(BaseModel):
    risk_note: ScriptForgingSelfRiskNote
    safe_summary: str


class SceneOutlineArtifactResponse(BaseModel):
    scene_outline: SceneOutlineArtifact
    plugin_run: PluginRun
    checkpoint: ScriptForgingCheckpoint
    plugin_checkpoint: PluginCheckpoint
    output_artifact: PluginOutputArtifact
    output_artifact_version: PluginOutputArtifactVersion
    step: PluginRunStep
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class ScreenplayDraftArtifactResponse(BaseModel):
    screenplay_draft: ScreenplayDraftArtifact
    plugin_run: PluginRun
    checkpoint: ScriptForgingCheckpoint
    plugin_checkpoint: PluginCheckpoint
    output_artifact: PluginOutputArtifact
    output_artifact_version: PluginOutputArtifactVersion
    step: PluginRunStep
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class ScreenplaySelfCheckReportResponse(BaseModel):
    self_check_report: ScreenplaySelfCheckReport
    plugin_run: PluginRun
    output_artifact: PluginOutputArtifact
    output_artifact_version: PluginOutputArtifactVersion
    step: PluginRunStep
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class ScreenplayRevisionCandidateResponse(BaseModel):
    revision_candidate: ScreenplayRevisionCandidate
    plugin_run: PluginRun
    output_artifact: PluginOutputArtifact
    output_artifact_version: PluginOutputArtifactVersion
    step: PluginRunStep
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class ScreenplayRevisionCandidateListResponse(BaseModel):
    plugin_run_id: str
    revision_candidates: list[ScreenplayRevisionCandidate] = Field(default_factory=list)
    total_count: int = 0
    safe_summary: str


class StoryboardPackageResponse(BaseModel):
    storyboard_package: StoryboardPackage
    key_storyboards: list[KeyStoryboardArtifact] = Field(default_factory=list)
    scene_storyboards: list[SceneStoryboardArtifact] = Field(default_factory=list)
    shot_list: ShotListArtifact
    plugin_run: PluginRun
    checkpoint: ScriptForgingCheckpoint
    plugin_checkpoint: PluginCheckpoint
    output_artifact: PluginOutputArtifact
    output_artifact_version: PluginOutputArtifactVersion
    step: PluginRunStep
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class KeyStoryboardArtifactListResponse(BaseModel):
    plugin_run_id: str
    key_storyboards: list[KeyStoryboardArtifact] = Field(default_factory=list)
    total_count: int = 0
    safe_summary: str


class SceneStoryboardArtifactListResponse(BaseModel):
    plugin_run_id: str
    scene_storyboards: list[SceneStoryboardArtifact] = Field(default_factory=list)
    total_count: int = 0
    safe_summary: str


class ShotListArtifactResponse(BaseModel):
    shot_list: ShotListArtifact
    safe_summary: str


class DigitalAssetPackageResponse(BaseModel):
    digital_asset_package: DigitalAssetPackage
    character_asset_list: CharacterAssetList
    location_asset_list: LocationAssetList
    prop_asset_list: PropAssetList
    motif_asset_list: MotifAssetList
    costume_continuity_list: CostumeContinuityList
    plugin_run: PluginRun
    checkpoint: ScriptForgingCheckpoint
    plugin_checkpoint: PluginCheckpoint
    output_artifact: PluginOutputArtifact
    output_artifact_version: PluginOutputArtifactVersion
    step: PluginRunStep
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class CharacterAssetListResponse(BaseModel):
    character_asset_list: CharacterAssetList
    safe_summary: str


class LocationAssetListResponse(BaseModel):
    location_asset_list: LocationAssetList
    safe_summary: str


class PropAssetListResponse(BaseModel):
    prop_asset_list: PropAssetList
    safe_summary: str


class MotifAssetListResponse(BaseModel):
    motif_asset_list: MotifAssetList
    safe_summary: str


class CostumeContinuityListResponse(BaseModel):
    costume_continuity_list: CostumeContinuityList
    safe_summary: str
