from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import json
import uuid

from pydantic import BaseModel, ConfigDict, Field

from ..config import DEFAULT_ENCODING


STATE_SCHEMA_VERSION = "story_analyzer.pipeline_state.v1"
INVALIDATION_LOG_SCHEMA_VERSION = "story_analyzer.invalidation_log.v1"

StepStatus = Literal["pending", "running", "completed", "failed", "blocked", "invalidated"]
ChangeType = Literal[
    "source_chapter_text_changed",
    "chapter_title_manual_corrected",
    "canonical_schema_compatible_changed",
    "chapter_repair_succeeded",
    "arc_boundary_user_adjusted",
    "tracker_manual_override",
    "module_envelope_schema_changed",
    "generator_profile_rule_changed",
]


class PipelineStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    step_type: str
    status: StepStatus
    input_fingerprints: list[str] = Field(default_factory=list)
    dependency_fingerprints: list[str] = Field(default_factory=list)
    schema_version: str = ""
    prompt_version: str = ""
    model: str = ""
    started_at: str = ""
    finished_at: str = ""
    output_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    scope: dict[str, Any] = Field(default_factory=dict)
    invalidated_at: str = ""
    invalidated_by_event_id: str = ""
    invalidation_reason: str = ""


class PipelineState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = STATE_SCHEMA_VERSION
    steps: list[PipelineStepRecord] = Field(default_factory=list)


class InvalidationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    change_type: ChangeType
    scope: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    invalidated_step_ids: list[str] = Field(default_factory=list)
    recorded_at: str


class InvalidationLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = INVALIDATION_LOG_SCHEMA_VERSION
    events: list[InvalidationEvent] = Field(default_factory=list)


DOWNSTREAM_STEP_TYPES = {
    "foreshadowing_tracker",
    "mystery_tracker",
    "relationship_debt_tracker",
    "world_rule_reveal_tracker",
    "tracker_edit_report",
    "arc_candidates",
    "arc_confirmation",
    "major_arcs",
    "sub_arcs",
    "arc_modules",
    "book_modules",
    "module_catalog",
    "handoff_package",
    "handoff_validation",
}

MODULE_AND_HANDOFF_STEP_TYPES = {
    "arc_modules",
    "book_modules",
    "module_catalog",
    "handoff_package",
    "handoff_validation",
}

TRACKER_STEP_TYPES = {
    "foreshadowing_tracker",
    "mystery_tracker",
    "relationship_debt_tracker",
    "world_rule_reveal_tracker",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / "run_state"


def pipeline_state_path(run_dir: str | Path) -> Path:
    return _state_dir(run_dir) / "pipeline_state.json"


def invalidation_log_path(run_dir: str | Path) -> Path:
    return _state_dir(run_dir) / "invalidation_log.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)


def _load_state_model(run_dir: str | Path) -> PipelineState:
    path = pipeline_state_path(run_dir)
    if not path.exists():
        return PipelineState()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return PipelineState.model_validate(data)


def _write_state(run_dir: str | Path, state: PipelineState) -> None:
    _write_json(pipeline_state_path(run_dir), state.model_dump(mode="json"))


def load_pipeline_state(run_dir: str | Path) -> dict[str, Any]:
    return _load_state_model(run_dir).model_dump(mode="json")


def _load_log_model(run_dir: str | Path) -> InvalidationLog:
    path = invalidation_log_path(run_dir)
    if not path.exists():
        return InvalidationLog()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return InvalidationLog.model_validate(data)


def _write_log(run_dir: str | Path, log: InvalidationLog) -> None:
    _write_json(invalidation_log_path(run_dir), log.model_dump(mode="json"))


def record_pipeline_step(
    run_dir: str | Path,
    *,
    step_id: str,
    step_type: str,
    status: StepStatus,
    input_fingerprints: list[str] | None = None,
    dependency_fingerprints: list[str] | None = None,
    schema_version: str = "",
    prompt_version: str = "",
    model: str = "",
    started_at: str = "",
    finished_at: str = "",
    output_refs: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _load_state_model(run_dir)
    record = PipelineStepRecord(
        step_id=step_id,
        step_type=step_type,
        status=status,
        input_fingerprints=input_fingerprints or [],
        dependency_fingerprints=dependency_fingerprints or [],
        schema_version=schema_version,
        prompt_version=prompt_version,
        model=model,
        started_at=started_at,
        finished_at=finished_at,
        output_refs=output_refs or [],
        warnings=warnings or [],
        errors=errors or [],
        scope=scope or {},
    )

    replaced = False
    for index, existing in enumerate(state.steps):
        if existing.step_id == record.step_id:
            state.steps[index] = record
            replaced = True
            break
    if not replaced:
        state.steps.append(record)

    _write_state(run_dir, state)
    return record.model_dump(mode="json")


def _scope_chapter_index(scope: dict[str, Any]) -> int | None:
    value = scope.get("chapter_index")
    if value is None:
        return None
    return int(value)


def _step_chapter_index(step: PipelineStepRecord) -> int | None:
    value = step.scope.get("chapter_index")
    if value is None:
        return None
    return int(value)


def _matches_source_chapter_change(step: PipelineStepRecord, scope: dict[str, Any]) -> bool:
    chapter_index = _scope_chapter_index(scope)
    if step.step_type in {"chapter_canonical_analysis", "tracker_candidate_extraction"}:
        return chapter_index is None or _step_chapter_index(step) == chapter_index
    return step.step_type in DOWNSTREAM_STEP_TYPES


def _matches_title_change(step: PipelineStepRecord, scope: dict[str, Any]) -> bool:
    chapter_index = _scope_chapter_index(scope)
    if step.step_type == "source_manifest":
        return True
    if step.step_type == "chapter_canonical_analysis":
        return chapter_index is None or _step_chapter_index(step) == chapter_index
    return step.step_type in {"arc_candidates", "handoff_package", "handoff_validation"}


def _matches_schema_change(step: PipelineStepRecord) -> bool:
    return step.step_type in {
        "chapter_canonical_analysis",
        "tracker_candidate_extraction",
        *TRACKER_STEP_TYPES,
        "arc_candidates",
        "arc_confirmation",
        "major_arcs",
        "sub_arcs",
        "arc_modules",
        "book_modules",
        "module_catalog",
        "tracker_edit_report",
        "handoff_package",
        "handoff_validation",
    }


def _matches_arc_change(step: PipelineStepRecord, scope: dict[str, Any]) -> bool:
    arc_id = scope.get("arc_id")
    if arc_id and step.scope.get("arc_id") == arc_id:
        return True
    return step.step_type in {
        "arc_confirmation",
        "major_arcs",
        "sub_arcs",
        *MODULE_AND_HANDOFF_STEP_TYPES,
    }


def _matches_tracker_change(step: PipelineStepRecord, scope: dict[str, Any]) -> bool:
    tracker_item_id = scope.get("tracker_item_id")
    if tracker_item_id and step.scope.get("tracker_item_id") == tracker_item_id:
        return True
    tracker_type = scope.get("tracker_type")
    if tracker_type and step.step_type == f"{tracker_type}_tracker":
        return True
    if not tracker_type and step.step_type in TRACKER_STEP_TYPES:
        return True
    return step.step_type in {
        "tracker_edit_report",
        "arc_modules",
        "book_modules",
        "module_catalog",
        "handoff_package",
        "handoff_validation",
    }


def _should_invalidate(step: PipelineStepRecord, change_type: ChangeType, scope: dict[str, Any]) -> bool:
    if change_type == "generator_profile_rule_changed":
        return False
    if change_type == "source_chapter_text_changed":
        return _matches_source_chapter_change(step, scope)
    if change_type == "chapter_title_manual_corrected":
        return _matches_title_change(step, scope)
    if change_type == "canonical_schema_compatible_changed":
        return _matches_schema_change(step)
    if change_type == "chapter_repair_succeeded":
        return _matches_source_chapter_change(step, scope)
    if change_type == "arc_boundary_user_adjusted":
        return _matches_arc_change(step, scope)
    if change_type == "tracker_manual_override":
        return _matches_tracker_change(step, scope)
    if change_type == "module_envelope_schema_changed":
        return step.step_type in MODULE_AND_HANDOFF_STEP_TYPES
    return False


def invalidate_for_change(
    run_dir: str | Path,
    *,
    change_type: ChangeType,
    scope: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    state = _load_state_model(run_dir)
    change_scope = scope or {}
    event_id = f"invalidation_{uuid.uuid4().hex[:12]}"
    recorded_at = _utc_now()
    invalidated_step_ids: list[str] = []

    for index, step in enumerate(state.steps):
        if step.status == "invalidated":
            continue
        if not _should_invalidate(step, change_type, change_scope):
            continue
        updated = step.model_copy(
            update={
                "status": "invalidated",
                "invalidated_at": recorded_at,
                "invalidated_by_event_id": event_id,
                "invalidation_reason": reason or change_type,
                "warnings": [*step.warnings, f"invalidated_by:{change_type}"],
            }
        )
        state.steps[index] = updated
        invalidated_step_ids.append(step.step_id)

    event = InvalidationEvent(
        event_id=event_id,
        change_type=change_type,
        scope=change_scope,
        reason=reason,
        invalidated_step_ids=invalidated_step_ids,
        recorded_at=recorded_at,
    )
    log = _load_log_model(run_dir)
    log.events.append(event)
    _write_state(run_dir, state)
    _write_log(run_dir, log)
    return event.model_dump(mode="json")
