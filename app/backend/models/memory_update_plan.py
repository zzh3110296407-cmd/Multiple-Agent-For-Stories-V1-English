from typing import Any, Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.memory_record import MemoryRecord


MEMORY_UPDATE_PLAN_VERSION_ID = "phase2_m6_memory_update_plan_v1"
MEMORY_UPDATE_PLAN_STATUSES = {
    "draft",
    "pending_user_confirmation",
    "confirmed",
    "applied",
    "rejected",
}
MEMORY_CHANGE_TYPES = {
    "added",
    "removed",
    "modified",
    "superseded",
    "unchanged",
}
MEMORY_CHANGE_OBJECT_TYPES = {
    "event",
    "state_change",
    "relationship_change",
    "memory_record",
}
DEPENDENT_SCENE_DEPENDENCY_TYPES = {
    "provisional_scene",
    "provisional_memory",
    "superseded_memory",
    "changed_event",
}
DEPENDENT_SCENE_ACTIONS = {
    "continuity_recheck",
    "needs_review",
    "needs_regeneration",
}


class MemoryChangeItem(BaseModel):
    change_id: str
    change_type: str = "unchanged"
    object_type: str = "memory_record"
    old_object_id: str = ""
    new_object_id: str = ""
    old_summary: str = ""
    new_summary: str = ""
    severity: str = "low"
    reason: str = ""
    requires_user_confirmation: bool = False

    @validator("change_type")
    def change_type_must_be_known(cls, value: str) -> str:
        return value if value in MEMORY_CHANGE_TYPES else "unchanged"

    @validator("object_type")
    def object_type_must_be_known(cls, value: str) -> str:
        return value if value in MEMORY_CHANGE_OBJECT_TYPES else "memory_record"


class DependentSceneAction(BaseModel):
    dependent_scene_id: str
    dependency_type: str = "superseded_memory"
    source_scene_id: str = ""
    source_memory_ids: list[str] = Field(default_factory=list)
    action: str = "continuity_recheck"
    reason: str = ""

    @validator("dependency_type")
    def dependency_type_must_be_known(cls, value: str) -> str:
        return value if value in DEPENDENT_SCENE_DEPENDENCY_TYPES else "superseded_memory"

    @validator("action")
    def action_must_be_known(cls, value: str) -> str:
        return value if value in DEPENDENT_SCENE_ACTIONS else "continuity_recheck"


class MemoryUpdatePlan(BaseModel):
    memory_update_plan_id: str
    project_id: str = "local_project"
    scene_id: str
    chapter_id: str = ""
    source_revision_id: str = ""
    status: str = "draft"
    old_scene_version_id: str = ""
    revised_scene_version_id: str = ""
    changed_events: list[MemoryChangeItem] = Field(default_factory=list)
    changed_state_changes: list[MemoryChangeItem] = Field(default_factory=list)
    changed_relationship_changes: list[MemoryChangeItem] = Field(default_factory=list)
    superseded_memory_ids: list[str] = Field(default_factory=list)
    new_memory_records: list[MemoryRecord] = Field(default_factory=list)
    affected_character_ids: list[str] = Field(default_factory=list)
    affected_relationship_ids: list[str] = Field(default_factory=list)
    affected_event_ids: list[str] = Field(default_factory=list)
    affected_scene_ids: list[str] = Field(default_factory=list)
    dependent_scene_actions: list[DependentSceneAction] = Field(default_factory=list)
    affected_memory_pack_ids: list[str] = Field(default_factory=list)
    memory_pack_refresh_recommended: bool = False
    requires_user_confirmation: bool = True
    confirmation_reasons: list[str] = Field(default_factory=list)
    user_facing_summary: str = ""
    technical_summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str = MEMORY_UPDATE_PLAN_VERSION_ID

    @validator("status")
    def status_must_be_known(cls, value: str) -> str:
        return value if value in MEMORY_UPDATE_PLAN_STATUSES else "draft"


class MemoryUpdatePlanFromRevisionRequest(BaseModel):
    revision_id: str
    dry_run: bool = False


class MemoryUpdatePlanDecisionRequest(BaseModel):
    user_input: Optional[str] = None


class MemoryUpdatePlanResponse(BaseModel):
    success: bool = True
    plan: MemoryUpdatePlan
    decision: Optional[Any] = None
