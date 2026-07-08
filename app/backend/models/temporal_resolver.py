from typing import Any, Optional

from pydantic import BaseModel, Field, validator


class TemporalResolverScope(BaseModel):
    project_id: str
    storage_mode: str
    mapping_source: str = ""
    compatibility_selection_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class CharacterVisibleMemoryResult(BaseModel):
    character_memory_node_id: str
    character_id: str
    timeline_id: str
    memory_type: str = ""
    visibility_status: str = ""
    content: str = ""
    summary: str = ""
    experienced_at: str = ""
    experienced_at_sort_key: int = 0
    known_at: str = ""
    known_at_sort_key: int = 0
    narrative_recorded_at: str = ""
    narrative_recorded_at_sort_key: int = 0
    valid_from: str = ""
    valid_from_sort_key: int = 0
    valid_to: str = ""
    valid_to_sort_key: Optional[int] = None
    status: str = ""
    authority_level: str = ""
    source_refs: list[Any] = Field(default_factory=list)
    usable_for_writer: bool = True


class CharacterVisibleMemoryResponse(BaseModel):
    scope: TemporalResolverScope
    character_id: str
    timeline_id: str
    world_time_sort_key: int
    knowledge_time_sort_key: int
    narrative_sequence_key: int
    result_count: int
    memories: list[CharacterVisibleMemoryResult] = Field(default_factory=list)
    filters_applied: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class LocationChangeDeltaResult(BaseModel):
    location_change_delta_id: str
    location_id: str
    from_node_id: str = ""
    to_node_id: str = ""
    source_event_id: str = ""
    change_summary: str = ""
    change_detail: str = ""
    visibility_status: str = ""
    status: str = ""
    authority_level: str = ""
    usable_for_writer: bool = True


class LocationStateAtTimeResult(BaseModel):
    location_state_node_id: str
    location_id: str
    timeline_id: str
    time_anchor: str = ""
    time_anchor_sort_key: int = 0
    valid_from: str = ""
    valid_from_sort_key: int = 0
    valid_to: str = ""
    valid_to_sort_key: Optional[int] = None
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    known_by_character_refs: list[Any] = Field(default_factory=list)
    revealed_to_reader_at: str = ""
    visibility_status: str = ""
    status: str = ""
    authority_level: str = ""
    change_from_previous: Optional[LocationChangeDeltaResult] = None
    usable_for_writer: bool = True


class LocationStateAtTimeResponse(BaseModel):
    scope: TemporalResolverScope
    location_id: str
    timeline_id: str
    world_time_sort_key: int
    state: Optional[LocationStateAtTimeResult] = None
    result_count: int = 0
    filters_applied: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class LocationStateVersionedInsertRequest(BaseModel):
    timeline_id: str
    location_state_node_id: str
    time_anchor: str
    time_anchor_sort_key: int = Field(..., ge=0)
    valid_from: str = ""
    valid_from_sort_key: int = Field(..., ge=0)
    valid_to: str = ""
    valid_to_sort_key: Optional[int] = None
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    known_by_character_refs: list[Any] = Field(default_factory=list)
    revealed_to_reader_at: str = ""
    revealed_to_reader_at_sort_key: Optional[int] = None
    visibility_status: str = "KNOWN"
    status: str = "CONFIRMED"
    authority_level: str = "SYSTEM_CONFIRMED"
    source_event_id: str = ""
    change_summary: str = ""
    change_detail: str = ""
    source_refs: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LocationStateVersionedInsertResponse(BaseModel):
    scope: TemporalResolverScope
    location_id: str
    timeline_id: str
    inserted_location_state_node_id: str
    inserted_node_uuid: str = ""
    superseded_location_state_node_ids: list[str] = Field(default_factory=list)
    successor_location_state_node_ids: list[str] = Field(default_factory=list)
    recomputed_location_change_delta_ids: list[str] = Field(default_factory=list)
    affected_downstream_refs: list[dict[str, Any]] = Field(default_factory=list)
    invalidated_context_pack_build_ids: list[str] = Field(default_factory=list)
    old_records_overwritten: bool = False
    versioned_insert_applied: bool = True
    gaps: list[str] = Field(default_factory=list)


class ReaderDisclosureStatusResponse(BaseModel):
    scope: TemporalResolverScope
    entity_type: str
    entity_id: str
    narrative_sequence_key: int
    disclosed_to_reader: bool
    usable_for_writer: bool
    evidence_count: int = 0
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    filters_applied: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class TimelineNodeVersionStatusResponse(BaseModel):
    scope: TemporalResolverScope
    node_type: str
    node_id: str
    current: bool
    status: str = ""
    lifecycle_state: str = ""
    authority_level: str = ""
    visibility_status: str = ""
    superseded_by_id: str = ""
    deleted: bool = False
    usable_for_writer: bool = False
    gaps: list[str] = Field(default_factory=list)

    @validator("node_type")
    def node_type_must_be_supported(cls, value: str) -> str:
        return str(value or "").strip()
