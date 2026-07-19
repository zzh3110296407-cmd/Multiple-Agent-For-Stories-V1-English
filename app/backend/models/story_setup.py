from typing import Any, Optional

from pydantic import BaseModel, Field


STORY_SETUP_SCHEMA_VERSION = "phase8_m3_story_setup_v1"


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class CreateStorySetupPromptFromProjectRequest(StrictModel):
    project_id: str
    creation_request_id: Optional[str] = None
    prompt_text: Optional[str] = None
    safe_user_note: str = ""


class CreateStorySetupIntakeRequest(StrictModel):
    story_setup_prompt_id: str


class CreateStorySetupDraftBundleRequest(StrictModel):
    story_setup_prompt_id: str
    story_setup_intake_id: Optional[str] = None
    selected_framework_composition_id: Optional[str] = None


class PatchStorySetupDraftBundleRequest(StrictModel):
    world_canvas_draft_suggestion: Optional[dict[str, Any]] = None
    main_cast_draft_direction: Optional[dict[str, Any]] = None
    framework_setup_suggestion: Optional[dict[str, Any]] = None
    chapter_route_suggestion: Optional[dict[str, Any]] = None
    selected_framework_composition_id: Optional[str] = None
    safe_user_note: str = ""


class AnswerStorySetupQuestionRequest(StrictModel):
    answer_text: str = ""
    safe_user_note: str = ""


class CreateStorySetupDecisionRequest(StrictModel):
    decision_type: str
    safe_user_note: str = ""
    requested_changes: list[str] = Field(default_factory=list)


class CreateStorySetupHandoffRequest(StrictModel):
    target_workspace: str = "world_canvas_workspace"
    safe_user_note: str = ""


class BootstrapStorySetupHandoffRequest(StrictModel):
    safe_user_note: str = ""


class StorySetupUserInput(BaseModel):
    story_setup_user_input_id: str
    project_id: str
    input_type: str
    input_text: str
    safe_summary: str = ""
    created_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupPrompt(BaseModel):
    story_setup_prompt_id: str
    project_id: str
    creation_request_id: Optional[str] = None
    project_origin_metadata_id: str
    prompt_text_ref: Optional[str] = None
    safe_prompt_summary: str = ""
    controlled_prompt_text_ref: Optional[str] = None
    has_controlled_prompt_text: bool = False
    needs_prompt_text_confirmation: bool = True
    language: str = "zh"
    user_intent_tags: list[str] = Field(default_factory=list)
    active_model_selection_id: Optional[str] = None
    active_model_provider_type: Optional[str] = None
    active_model_name: Optional[str] = None
    model_health_status_at_creation: str = "unknown"
    prompt_status: str = "needs_text_confirmation"
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupIntake(BaseModel):
    story_setup_intake_id: str
    project_id: str
    story_setup_prompt_id: str
    intake_status: str = "draft"
    detected_genre_tags: list[str] = Field(default_factory=list)
    detected_tone_tags: list[str] = Field(default_factory=list)
    detected_world_scope: str = ""
    detected_core_conflict: str = ""
    detected_protagonist_hint: str = ""
    detected_story_length_hint: str = ""
    prompt_signal_summary: str = ""
    detected_key_terms: list[str] = Field(default_factory=list)
    missing_information_codes: list[str] = Field(default_factory=list)
    analysis_snapshot: dict[str, Any] = Field(default_factory=dict)
    question_ids: list[str] = Field(default_factory=list)
    used_real_provider: bool = False
    used_deterministic_fallback: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupDraftBundle(BaseModel):
    story_setup_draft_bundle_id: str
    project_id: str
    story_setup_prompt_id: str
    story_setup_intake_id: str
    bundle_status: str = "draft"
    world_canvas_draft_suggestion: dict[str, Any] = Field(default_factory=dict)
    main_cast_draft_direction: dict[str, Any] = Field(default_factory=dict)
    framework_setup_suggestion: dict[str, Any] = Field(default_factory=dict)
    chapter_route_suggestion: dict[str, Any] = Field(default_factory=dict)
    selected_framework_composition_id: str = ""
    generator_framework_context_ref: Optional[str] = None
    question_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    creates_final_story_facts_now: bool = False
    requires_downstream_confirmation: bool = True
    used_real_provider: bool = False
    used_deterministic_fallback: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupQuestion(BaseModel):
    story_setup_question_id: str
    project_id: str
    story_setup_intake_id: str
    story_setup_draft_bundle_id: str
    question_type: str
    question_text: str
    suggested_options: list[str] = Field(default_factory=list)
    answer_status: str = "unanswered"
    user_answer_ref: Optional[str] = None
    safe_answer_summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupQuestionsResponse(BaseModel):
    questions: list[StorySetupQuestion] = Field(default_factory=list)


class StorySetupDecision(BaseModel):
    story_setup_decision_id: str
    project_id: str
    story_setup_draft_bundle_id: str
    decision_type: str
    decision_status: str = "recorded"
    decision_scope: str = "setup_draft_only"
    safe_user_note: str = ""
    requested_changes: list[str] = Field(default_factory=list)
    does_not_confirm_world_canvas_final: bool = True
    does_not_confirm_characters_final: bool = True
    does_not_confirm_framework_final: bool = True
    does_not_confirm_chapter_plan_final: bool = True
    does_not_write_story_facts: bool = True
    created_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupHandoff(BaseModel):
    story_setup_handoff_id: str
    project_id: str
    story_setup_draft_bundle_id: str
    story_setup_decision_id: str
    handoff_status: str = "ready"
    target_workspace: str = "world_canvas_workspace"
    world_canvas_draft_ref: Optional[str] = None
    main_cast_direction_ref: Optional[str] = None
    framework_suggestion_ref: Optional[str] = None
    chapter_route_suggestion_ref: Optional[str] = None
    selected_framework_composition_id: str = ""
    generator_framework_context_ref: Optional[str] = None
    requires_world_canvas_confirmation: bool = True
    requires_character_confirmation: bool = True
    requires_framework_confirmation: bool = True
    requires_chapter_route_confirmation: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupSafetyReport(BaseModel):
    story_setup_safety_report_id: str
    project_id: str
    story_setup_draft_bundle_id: str
    story_setup_handoff_id: Optional[str] = None
    passed: bool = True
    no_final_story_fact_write: bool = True
    no_world_canvas_confirmed_write: bool = True
    no_character_confirmed_write: bool = True
    no_active_framework_write: bool = True
    no_chapter_plan_confirmed_write: bool = True
    no_scene_event_memory_state_write: bool = True
    no_final_story_package_write: bool = True
    no_plugin_output_artifact_write: bool = True
    no_raw_prompt_in_debug: bool = True
    no_raw_response: bool = True
    no_hidden_reasoning: bool = True
    no_api_key: bool = True
    no_authorization_header: bool = True
    no_bearer_token: bool = True
    no_uncontrolled_full_story_prose: bool = True
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupCurrentState(BaseModel):
    project_id: str = ""
    state_status: str = "empty"
    controlled_prompt_text: str = ""
    story_setup_prompt: Optional[StorySetupPrompt] = None
    story_setup_intake: Optional[StorySetupIntake] = None
    story_setup_draft_bundle: Optional[StorySetupDraftBundle] = None
    story_setup_questions: list[StorySetupQuestion] = Field(default_factory=list)
    controlled_question_answers: dict[str, str] = Field(default_factory=dict)
    story_setup_decision: Optional[StorySetupDecision] = None
    story_setup_handoff: Optional[StorySetupHandoff] = None
    story_setup_safety_report: Optional[StorySetupSafetyReport] = None
    story_setup_draft_bundle_id: str = ""
    recovered_from_storage: bool = True
    warnings: list[str] = Field(default_factory=list)
    version_id: str = STORY_SETUP_SCHEMA_VERSION


class StorySetupBootstrapResult(BaseModel):
    story_setup_bootstrap_id: str
    project_id: str
    story_setup_handoff_id: str
    bootstrap_status: str = "applied"
    story_bible_id: str = ""
    world_canvas_id: str = ""
    world_canvas_status: str = "draft"
    story_data_scope: str = "active_project"
    created_files: list[str] = Field(default_factory=list)
    updated_files: list[str] = Field(default_factory=list)
    cleared_legacy_files: list[str] = Field(default_factory=list)
    setup_required_after_bootstrap: bool = False
    next_workspace_id: str = "world_canvas"
    project_story_premise_status: str = "not_created"
    project_story_premise_ref: Optional[str] = None
    project_story_premise_blocking_issues: list[str] = Field(default_factory=list)
    selected_framework_composition_id: str = ""
    generator_framework_context_ref: Optional[str] = None
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    version_id: str = STORY_SETUP_SCHEMA_VERSION
