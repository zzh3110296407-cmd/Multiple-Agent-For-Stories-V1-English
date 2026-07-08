from typing import Literal

from pydantic import BaseModel, Field

from .plugin_protocol import PluginInputValidationReport


PluginRunStatus = Literal[
    "created",
    "input_validated",
    "waiting_for_checkpoint",
    "checkpoint_confirmed",
    "completed",
    "completed_with_warnings",
    "cancelled",
    "blocked",
    "failed",
]
PluginRunStepType = Literal[
    "input_binding",
    "checkpoint",
    "artifact_creation",
    "safety_check",
    "completion",
    "cancellation",
    "error",
]
PluginRunStepStatus = Literal[
    "pending",
    "running",
    "waiting_for_checkpoint",
    "completed",
    "blocked",
    "failed",
    "skipped",
]
PluginCheckpointType = Literal["input_confirmation", "generic_confirmation"]
PluginCheckpointStatus = Literal["pending", "confirmed", "revision_requested", "rejected", "deferred", "cancelled"]
PluginCheckpointDecisionType = Literal["confirm", "request_revision", "reject", "defer", "cancel_run"]
PluginOutputArtifactType = Literal["runtime_test_artifact", "generic_text_artifact", "generic_structured_artifact"]
PluginOutputArtifactStatus = Literal["draft", "checkpoint_pending", "confirmed", "rejected", "archived"]
PluginRunErrorType = Literal[
    "input_validation_failed",
    "checkpoint_blocked",
    "artifact_creation_failed",
    "safety_violation",
    "unsupported_plugin",
    "internal_error",
]


class PluginRuntimeStrictRequest(BaseModel):
    class Config:
        extra = "forbid"


class PluginRunCreateRequest(PluginRuntimeStrictRequest):
    snapshot_id: str
    safe_user_note: str = ""


class PluginRunCancelRequest(PluginRuntimeStrictRequest):
    safe_user_note: str = ""


class PluginCheckpointDecisionRequest(PluginRuntimeStrictRequest):
    safe_user_note: str = ""
    requested_changes: list[str] = Field(default_factory=list)


class PluginRun(BaseModel):
    plugin_run_id: str
    project_id: str
    plugin_id: str
    manifest_id: str
    input_schema_id: str
    risk_declaration_id: str
    version_record_id: str
    plugin_protocol_version: str
    plugin_version: str
    final_story_package_id: str
    final_story_package_snapshot_id: str
    input_validation_report_id: str
    run_status: PluginRunStatus
    current_step_id: str
    step_ids: list[str] = Field(default_factory=list)
    checkpoint_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    safety_report_id: str
    error_ids: list[str] = Field(default_factory=list)
    reads_only_final_story_package_snapshot: bool = True
    mutates_source_story: bool = False
    safe_user_note: str = ""
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str


class PluginRunStep(BaseModel):
    step_id: str
    plugin_run_id: str
    step_type: PluginRunStepType
    step_status: PluginRunStepStatus
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    checkpoint_id: str = ""
    output_artifact_id: str = ""
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class PluginCheckpoint(BaseModel):
    checkpoint_id: str
    plugin_run_id: str
    step_id: str
    checkpoint_type: PluginCheckpointType
    checkpoint_status: PluginCheckpointStatus
    checkpoint_prompt: str
    user_visible_summary: str
    source_artifact_ids: list[str] = Field(default_factory=list)
    decision_id: str = ""
    confirms_plugin_step_only: bool = True
    mutates_source_story: bool = False
    created_at: str
    updated_at: str


class PluginCheckpointDecision(BaseModel):
    checkpoint_decision_id: str
    plugin_run_id: str
    checkpoint_id: str
    decision_type: PluginCheckpointDecisionType
    user_note: str = ""
    requested_changes: list[str] = Field(default_factory=list)
    decision_scope: str = "plugin_step_only"
    does_not_modify_final_story_package: bool = True
    does_not_modify_source_story: bool = True
    created_at: str
    version_id: str


class PluginOutputArtifact(BaseModel):
    artifact_id: str
    project_id: str
    plugin_run_id: str
    plugin_id: str
    artifact_type: PluginOutputArtifactType
    artifact_status: PluginOutputArtifactStatus
    current_version_id: str
    version_ids: list[str] = Field(default_factory=list)
    source_package_snapshot_id: str
    source_manifest_id: str
    is_derivative_artifact: bool = True
    mutates_source_story: bool = False
    safe_title: str
    safe_summary: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    version_id: str


class PluginOutputArtifactVersion(BaseModel):
    artifact_version_id: str
    artifact_id: str
    plugin_run_id: str
    version_number: int
    content_ref: str
    content_hash: str
    safe_preview: str
    structured_summary: dict = Field(default_factory=dict)
    created_from_step_id: str
    created_after_checkpoint_id: str
    no_source_story_mutation: bool = True
    created_at: str


class PluginRunSafetyReport(BaseModel):
    safety_report_id: str
    plugin_run_id: str
    passed: bool
    final_story_package_snapshot_used: bool
    live_story_state_access_blocked: bool
    unconfirmed_draft_access_blocked: bool
    phase6_proposal_as_truth_blocked: bool
    fixture_confusion_blocked_or_marked: bool
    no_scene_prose_write: bool
    no_event_write: bool
    no_memory_record_write: bool
    no_state_change_write: bool
    no_chapter_archive_write: bool
    no_narrative_debt_write: bool
    no_story_bible_write: bool
    no_final_story_package_mutation: bool
    no_m2_package_record_mutation: bool
    no_m3_static_protocol_record_mutation: bool
    no_raw_prompt: bool
    no_raw_response: bool
    no_hidden_reasoning: bool
    no_chain_of_thought: bool
    no_api_key: bool
    no_authorization_header: bool
    no_langsmith_key: bool
    no_provider_secret: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str


class PluginRunError(BaseModel):
    error_id: str
    plugin_run_id: str
    error_type: PluginRunErrorType
    safe_error_message: str
    safe_context: dict = Field(default_factory=dict)
    created_at: str


class PluginRunCreateResponse(BaseModel):
    plugin_run: PluginRun
    input_validation_report: PluginInputValidationReport
    steps: list[PluginRunStep] = Field(default_factory=list)
    checkpoints: list[PluginCheckpoint] = Field(default_factory=list)
    safety_report: PluginRunSafetyReport
    safe_summary: str


class PluginRunListResponse(BaseModel):
    plugin_runs: list[PluginRun] = Field(default_factory=list)
    total_count: int = 0
    safe_summary: str


class PluginRunStepListResponse(BaseModel):
    plugin_run_id: str
    steps: list[PluginRunStep] = Field(default_factory=list)
    total_count: int = 0


class PluginCheckpointListResponse(BaseModel):
    plugin_run_id: str
    checkpoints: list[PluginCheckpoint] = Field(default_factory=list)
    total_count: int = 0


class PluginCheckpointDecisionResponse(BaseModel):
    plugin_run: PluginRun
    checkpoint: PluginCheckpoint
    decision: PluginCheckpointDecision
    output_artifact: PluginOutputArtifact | None = None
    output_artifact_version: PluginOutputArtifactVersion | None = None
    safety_report: PluginRunSafetyReport | None = None
    safe_summary: str


class PluginOutputArtifactListResponse(BaseModel):
    plugin_run_id: str = ""
    artifacts: list[PluginOutputArtifact] = Field(default_factory=list)
    total_count: int = 0
    safe_summary: str = ""


class PluginOutputArtifactVersionListResponse(BaseModel):
    artifact_id: str
    versions: list[PluginOutputArtifactVersion] = Field(default_factory=list)
    total_count: int = 0
