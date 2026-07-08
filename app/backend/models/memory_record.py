from typing import Optional

from pydantic import BaseModel, Field, root_validator, validator


MEMORY_M2_VERSION_ID = "phase2_m2_memory_source_index_v1"
MEMORY_STATUSES = {"active", "draft", "provisional", "superseded", "rejected"}
MEMORY_TRUTH_STATUSES = {
    "objective_fact",
    "unverified_claim",
    "rumor",
    "lie",
    "misinformation",
}
NON_OBJECTIVE_TRUTH_STATUSES = {"rumor", "lie", "misinformation"}


class MemoryRecord(BaseModel):
    memory_id: str
    project_id: str = "local_project"

    source_object_type: str = ""
    source_object_id: str = ""
    source_revision_id: str = ""
    source_plan_id: str = ""
    chapter_id: Optional[str] = None
    scene_id: Optional[str] = None

    memory_type: str = "event"
    summary: str
    keywords: list[str] = Field(default_factory=list)

    character_ids: list[str] = Field(default_factory=list)
    relationship_ids: list[str] = Field(default_factory=list)
    location: Optional[str] = None
    event_ids: list[str] = Field(default_factory=list)

    importance: str = "medium"
    status: str = "active"
    superseded_by: Optional[str] = None
    truth_status: str = "objective_fact"
    objective_truth: bool = True
    source_issue_id: str = ""
    speaker_character_id: str = ""
    believed_by_character_ids: list[str] = Field(default_factory=list)
    known_false_by_character_ids: list[str] = Field(default_factory=list)
    version_id: str = MEMORY_M2_VERSION_ID
    created_at: str = ""
    updated_at: str = ""

    # Legacy compatibility fields.
    source_type: str = ""
    object_type: str = ""
    object_id: str = ""
    tags: list[str] = Field(default_factory=list)
    embedding_ref: str = ""

    @root_validator(pre=True)
    def map_legacy_fields(cls, values: dict) -> dict:
        data = dict(values or {})
        object_type = str(data.get("object_type") or "")
        object_id = str(data.get("object_id") or "")
        source_type = str(data.get("source_type") or "")

        if not data.get("source_object_type"):
            data["source_object_type"] = object_type or source_type
        if not data.get("source_object_id"):
            data["source_object_id"] = object_id
        if not data.get("object_type") and data.get("source_object_type"):
            data["object_type"] = data["source_object_type"]
        if not data.get("object_id") and data.get("source_object_id"):
            data["object_id"] = data["source_object_id"]

        tags = _as_list(data.get("tags"))
        keywords = _as_list(data.get("keywords"))
        data["keywords"] = _unique_strings([*keywords, *tags])
        data["tags"] = _unique_strings(tags)

        if not data.get("memory_type"):
            data["memory_type"] = _memory_type_from_source(
                str(data.get("source_object_type") or "")
            )
        if not data.get("status"):
            data["status"] = "active"
        if not data.get("truth_status"):
            data["truth_status"] = "objective_fact"
        if data.get("truth_status") in NON_OBJECTIVE_TRUTH_STATUSES:
            data["objective_truth"] = False
        elif "objective_truth" not in data:
            data["objective_truth"] = True
        if not data.get("version_id"):
            data["version_id"] = MEMORY_M2_VERSION_ID
        return data

    @validator(
        "keywords",
        "character_ids",
        "relationship_ids",
        "event_ids",
        "believed_by_character_ids",
        "known_false_by_character_ids",
        "tags",
        pre=True,
    )
    def list_values_must_be_strings(cls, value) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)] if str(value).strip() else []
        return _unique_strings(value)

    @validator("status")
    def status_must_be_supported(cls, value: str) -> str:
        status = (value or "active").strip()
        if status not in MEMORY_STATUSES:
            return "active"
        return status

    @validator("truth_status")
    def truth_status_must_be_supported(cls, value: str) -> str:
        status = (value or "objective_fact").strip()
        if status not in MEMORY_TRUTH_STATUSES:
            return "objective_fact"
        return status



class MemoryQuery(BaseModel):
    chapter_id: Optional[str] = None
    scene_id: Optional[str] = None
    character_ids: list[str] = Field(default_factory=list)
    relationship_ids: list[str] = Field(default_factory=list)
    location: Optional[str] = None
    event_ids: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    memory_types: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=lambda: ["active"])
    include_provisional: bool = False
    include_superseded: bool = False
    limit: int = 20

    @validator(
        "character_ids",
        "relationship_ids",
        "event_ids",
        "keywords",
        "memory_types",
        "statuses",
        pre=True,
    )
    def query_list_values_must_be_strings(cls, value) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)] if str(value).strip() else []
        return _unique_strings(value)

    @validator("limit")
    def limit_must_be_bounded(cls, value: int) -> int:
        return max(1, min(int(value or 20), 100))


class MemoryQueryResult(BaseModel):
    memory_id: str
    record: MemoryRecord
    matched_by: list[str] = Field(default_factory=list)
    score_hint: int = 0
    explanation: str = ""


class MemoryQueryResponse(BaseModel):
    query: MemoryQuery
    results: list[MemoryQueryResult] = Field(default_factory=list)
    count: int = 0


class MemoryRecordsResponse(BaseModel):
    records: list[MemoryRecord] = Field(default_factory=list)
    count: int = 0


class MemoryIndexes(BaseModel):
    by_chapter: dict[str, list[str]] = Field(default_factory=dict)
    by_scene: dict[str, list[str]] = Field(default_factory=dict)
    by_character: dict[str, list[str]] = Field(default_factory=dict)
    by_relationship: dict[str, list[str]] = Field(default_factory=dict)
    by_location: dict[str, list[str]] = Field(default_factory=dict)
    by_event: dict[str, list[str]] = Field(default_factory=dict)
    by_keyword: dict[str, list[str]] = Field(default_factory=dict)
    by_status: dict[str, list[str]] = Field(default_factory=dict)
    by_memory_type: dict[str, list[str]] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)


class MemoryReindexRequest(BaseModel):
    dry_run: bool = True


class MemoryMigrationReport(BaseModel):
    success: bool = True
    dry_run: bool = True
    records_seen: int = 0
    records_normalized: int = 0
    records_written: int = 0
    indexes_built: bool = False
    warnings: list[str] = Field(default_factory=list)


class MemoryReindexResponse(MemoryMigrationReport):
    pass


def _unique_strings(values: list) -> list[str]:
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


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _memory_type_from_source(source_type: str) -> str:
    source = source_type.strip().lower()
    if source in {"relationship", "state_change", "scene", "character"}:
        return source
    return "event"
