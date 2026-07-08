from typing import Any, Optional

from pydantic import BaseModel, Field, validator


MODIFICATION_IMPACT_VERSION_ID = "version_phase3_m6_modification_impact_preview_001"

MODIFICATION_SOURCE_TYPES = {
    "user_intent",
    "continuity_resolution",
    "revision_candidate",
    "manual_review",
}
MODIFICATION_SOURCE_OBJECT_TYPES = {
    "confirmed_scene",
    "chapter_archive",
    "revision_candidate",
    "scene_draft",
}
MODIFICATION_IMPACT_STATUSES = {
    "preview",
    "choice_recorded",
    "rejected",
    "deferred_to_phase4",
    "converted_to_revision_candidate",
    "memory_plan_pending",
    "declared_as_narrative_layer",
}
MODIFICATION_ACTION_TYPES = {
    "keep_current_change",
    "cancel_change",
    "defer_to_phase4_premodify",
    "rewrite_affected_current_scene",
    "patch_local_memory",
    "declare_as_narrative_layer",
}
IMPACT_LEVELS = {"low", "medium", "high"}


class AffectedObjectRef(BaseModel):
    object_type: str
    object_id: str
    chapter_id: str = ""
    scene_id: str = ""
    status: str = ""
    impact_area: str = "story"
    impact_level: str = "medium"
    relation: str = ""
    reason: str = ""
    summary: str = ""
    ref_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @validator("impact_level")
    def impact_level_must_be_known(cls, value: str) -> str:
        if value not in IMPACT_LEVELS:
            raise ValueError("AffectedObjectRef.impact_level is invalid.")
        return value


class ModificationUserOption(BaseModel):
    option_id: str
    action_type: str
    label: str
    enabled: bool = True
    recommended: bool = False
    requires_user_input: bool = False
    requires_model_call: bool = False
    expected_effect: str = ""
    disabled_reason: str = ""
    warning_codes: list[str] = Field(default_factory=list)

    @validator("action_type")
    def action_type_must_be_known(cls, value: str) -> str:
        if value not in MODIFICATION_ACTION_TYPES:
            raise ValueError("ModificationUserOption.action_type is invalid.")
        return value


class ModificationImpactPreviewRequest(BaseModel):
    source_object_type: str
    source_object_id: str
    modification_source_type: str = "user_intent"
    modification_text: str = ""
    modification_summary: str = ""
    revision_id: Optional[str] = None
    change_summary: list[str] = Field(default_factory=list)

    @validator("source_object_type")
    def source_object_type_must_be_known(cls, value: str) -> str:
        if value not in MODIFICATION_SOURCE_OBJECT_TYPES:
            raise ValueError("source_object_type is invalid.")
        return value

    @validator("modification_source_type")
    def modification_source_type_must_be_known(cls, value: str) -> str:
        if value not in MODIFICATION_SOURCE_TYPES:
            raise ValueError("modification_source_type is invalid.")
        return value


class ModificationImpactChooseRequest(BaseModel):
    action_type: str
    user_input: Optional[str] = None
    revision_prompt: Optional[str] = None
    accept_warnings: bool = False

    @validator("action_type")
    def action_type_must_be_known(cls, value: str) -> str:
        if value not in MODIFICATION_ACTION_TYPES:
            raise ValueError("action_type is invalid.")
        return value


class ModificationImpactPreview(BaseModel):
    preview_id: str
    project_id: str = "local_project"
    source_object_type: str
    source_object_id: str
    source_status: str = ""
    source_summary: str = ""
    source_revision_id: str = ""
    modification_source_type: str = "user_intent"
    modification_summary: str = ""
    modification_hash: str = ""
    affected_objects: list[AffectedObjectRef] = Field(default_factory=list)
    impact_summary: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommended_options: list[ModificationUserOption] = Field(default_factory=list)
    dry_run_memory_plan_summary: dict[str, Any] = Field(default_factory=dict)
    status: str = "preview"
    chosen_action: str = ""
    chosen_decision_id: str = ""
    resulting_revision_id: str = ""
    resulting_memory_plan_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = MODIFICATION_IMPACT_VERSION_ID

    @validator("source_object_type")
    def preview_source_object_type_must_be_known(cls, value: str) -> str:
        if value not in MODIFICATION_SOURCE_OBJECT_TYPES:
            raise ValueError("ModificationImpactPreview.source_object_type is invalid.")
        return value

    @validator("modification_source_type")
    def preview_modification_source_type_must_be_known(cls, value: str) -> str:
        if value not in MODIFICATION_SOURCE_TYPES:
            raise ValueError("ModificationImpactPreview.modification_source_type is invalid.")
        return value

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        if value not in MODIFICATION_IMPACT_STATUSES:
            raise ValueError("ModificationImpactPreview.status is invalid.")
        return value


class ModificationImpactPreviewResponse(BaseModel):
    success: bool = True
    preview: ModificationImpactPreview
    decision: Optional[Any] = None
    candidate: Optional[dict[str, Any]] = None
    memory_plan: Optional[dict[str, Any]] = None


class ModificationImpactPreviewListResponse(BaseModel):
    success: bool = True
    previews: list[ModificationImpactPreview] = Field(default_factory=list)
    count: int = 0

