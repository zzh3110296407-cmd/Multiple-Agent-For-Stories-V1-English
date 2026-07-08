from typing import Any, Optional

from pydantic import BaseModel, Field, validator


SCENE_SNAPSHOT_VERSION_ID = "phase4_m1_scene_version_snapshot_v1"
SNAPSHOT_INVALIDATION_VERSION_ID = "phase4_m1_snapshot_invalidation_v1"

SNAPSHOT_STATUSES = {"active", "stale", "superseded", "rejected"}
SNAPSHOT_TYPES = {
    "confirmed_scene",
    "temporary_confirmed_scene",
    "revised_scene",
    "revision_candidate_input",
    "archive_input",
    "manual_validation",
    "thinking_input",
}
REF_ROLES = {
    "subject",
    "direct_source",
    "context_source",
    "dependency",
    "guardrail",
    "audit_ref",
}
INVALIDATION_ACTIONS = {"mark_stale", "warning_only", "no_action"}

ALLOWED_SCENE_SNAPSHOT_REF_TYPES = {
    "scene",
    "scene_revision",
    "event",
    "state_change",
    "memory_record",
    "chapter_memory_pack",
    "scene_memory_pack",
    "chapter_archive",
    "chapter_framework",
    "chapter_framework_build_context",
    "framework_package",
    "character_state",
    "relationship_state",
    "modification_impact_preview",
    "decision",
    "quality_report",
    "claim_record",
    "narrative_intent",
    "character_psychology_trace",
    "character_expression_record",
    "perception_state",
    "apparent_contradiction",
    "narrative_debt",
    "story_progress",
    "next_chapter_preparation",
}


class SceneSnapshotRef(BaseModel):
    ref_type: str
    ref_id: str
    ref_version_id: str = ""
    ref_status: str = ""
    role: str = "dependency"
    safe_label: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @validator("ref_type")
    def ref_type_must_be_supported(cls, value: str) -> str:
        ref_type = str(value or "").strip()
        if ref_type not in ALLOWED_SCENE_SNAPSHOT_REF_TYPES:
            raise ValueError("SceneSnapshotRef.ref_type is not supported.")
        return ref_type

    @validator("role")
    def role_must_be_supported(cls, value: str) -> str:
        role = str(value or "dependency").strip()
        if role not in REF_ROLES:
            return "dependency"
        return role


class SceneVersionSnapshot(BaseModel):
    snapshot_id: str
    project_id: str = "local_project"
    snapshot_type: str
    subject_type: str = "scene"
    subject_id: str
    subject_version_id: str = ""
    subject_status: str = ""
    target_scene_id: str = ""
    chapter_id: str = ""
    chapter_index: Optional[int] = None
    source_refs: list[SceneSnapshotRef] = Field(default_factory=list)
    source_ref_counts: dict[str, int] = Field(default_factory=dict)
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    snapshot_hash: str = ""
    status: str = "active"
    stale_reason: str = ""
    created_at: str
    updated_at: str
    version_id: str = SCENE_SNAPSHOT_VERSION_ID

    @validator("snapshot_type")
    def snapshot_type_must_be_supported(cls, value: str) -> str:
        snapshot_type = str(value or "").strip()
        if snapshot_type not in SNAPSHOT_TYPES:
            raise ValueError("SceneVersionSnapshot.snapshot_type is not supported.")
        return snapshot_type

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = str(value or "active").strip()
        return status if status in SNAPSHOT_STATUSES else "active"


class SnapshotInvalidationRecord(BaseModel):
    invalidation_id: str
    project_id: str = "local_project"
    changed_ref_type: str
    changed_ref_id: str
    old_version_id: str = ""
    new_version_id: str = ""
    affected_snapshot_ids: list[str] = Field(default_factory=list)
    affected_candidate_ids: list[str] = Field(default_factory=list)
    invalidation_action: str
    reason: str = ""
    created_at: str
    version_id: str = SNAPSHOT_INVALIDATION_VERSION_ID

    @validator("changed_ref_type")
    def changed_ref_type_must_be_supported(cls, value: str) -> str:
        ref_type = str(value or "").strip()
        if ref_type not in ALLOWED_SCENE_SNAPSHOT_REF_TYPES:
            raise ValueError("SnapshotInvalidationRecord.changed_ref_type is not supported.")
        return ref_type

    @validator("invalidation_action")
    def invalidation_action_must_be_supported(cls, value: str) -> str:
        action = str(value or "no_action").strip()
        return action if action in INVALIDATION_ACTIONS else "no_action"


class SceneSnapshotCreateForSceneRequest(BaseModel):
    scene_id: str
    snapshot_type: str = "manual_validation"
    target_scene_id: str = ""
    extra_refs: list[SceneSnapshotRef] = Field(default_factory=list)


class SceneSnapshotInvalidateByRefRequest(BaseModel):
    changed_ref_type: str
    changed_ref_id: str
    old_version_id: str = ""
    new_version_id: str = ""
    reason: str = ""


class SceneSnapshotResponse(BaseModel):
    success: bool = True
    snapshot: SceneVersionSnapshot


class SceneSnapshotListResponse(BaseModel):
    success: bool = True
    snapshots: list[SceneVersionSnapshot] = Field(default_factory=list)
    count: int = 0


class SnapshotInvalidationResponse(BaseModel):
    success: bool = True
    invalidation: SnapshotInvalidationRecord
    stale_snapshot_ids: list[str] = Field(default_factory=list)


class SceneDependencyGraphSummaryResponse(BaseModel):
    success: bool = True
    project_id: str = "local_project"
    chapter_id: str = ""
    scene_id: str = ""
    snapshot_count: int = 0
    active_snapshot_count: int = 0
    stale_snapshot_count: int = 0
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    ref_type_counts: dict[str, int] = Field(default_factory=dict)
    latest_invalidation_ids: list[str] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)
