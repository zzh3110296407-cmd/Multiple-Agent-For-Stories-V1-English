from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..models.trackers import ManualOverride, TrackerItem, TrackerStatus, TrackerType
from ..state.pipeline_state import invalidate_for_change
from .tracker_store import (
    foreshadowing_tracker_path,
    mystery_tracker_path,
    override_log_path,
    read_json,
    relationship_debt_tracker_path,
    world_rule_reveal_tracker_path,
    write_json,
)

TRACKER_TYPES = {"foreshadowing", "mystery", "relationship_debt", "world_rule_reveal"}
TRACKER_STATUSES = {"open", "partially_resolved", "resolved", "abandoned", "uncertain"}
SPLIT_ITEM_ALLOWED_KEYS = {
    "tracker_item_id",
    "canonical_content",
    "status",
    "planted",
    "updates",
    "resolved",
    "candidate_history_refs",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tracker_path(run_dir: str | Path, tracker_type: TrackerType) -> Path:
    if tracker_type not in TRACKER_TYPES:
        raise ValueError(f"unknown tracker_type: {tracker_type}")
    return {
        "foreshadowing": foreshadowing_tracker_path,
        "mystery": mystery_tracker_path,
        "relationship_debt": relationship_debt_tracker_path,
        "world_rule_reveal": world_rule_reveal_tracker_path,
    }[tracker_type](run_dir)


def _load_tracker(run_dir: str | Path, tracker_type: TrackerType) -> tuple[Path, dict[str, Any]]:
    path = _tracker_path(run_dir, tracker_type)
    return path, read_json(path)


def _find_item(tracker: dict[str, Any], tracker_item_id: str) -> dict[str, Any]:
    for item in tracker.get("items", []):
        if item.get("tracker_item_id") == tracker_item_id:
            return item
    raise ValueError(f"Tracker item not found: {tracker_item_id}")


def _manual_override(
    *,
    status: TrackerStatus | None,
    resolved_chapter_index: int | None = None,
    resolution_method: str | None = None,
    reason: str | None = None,
    updated_at: str,
) -> dict[str, Any]:
    return ManualOverride(
        active=True,
        status=status,
        resolved_chapter_index=resolved_chapter_index,
        resolution_method=resolution_method,
        reason=reason,
        updated_at=updated_at,
    ).model_dump(mode="json")


def _append_log_event(run_dir: str | Path, event: dict[str, Any]) -> None:
    log_path = override_log_path(run_dir)
    if log_path.exists():
        log = read_json(log_path)
    else:
        log = {
            "schema_version": "story_analyzer.tracker_override_log.v1",
            "events": [],
        }
    log["events"].append(event)
    write_json(log_path, log)


def _invalidate_after_manual_edit(
    run_dir: str | Path,
    *,
    tracker_type: TrackerType,
    tracker_item_id: str,
    reason: str | None,
) -> None:
    invalidate_for_change(
        run_dir,
        change_type="tracker_manual_override",
        scope={"tracker_type": tracker_type, "tracker_item_id": tracker_item_id},
        reason=reason or "tracker manual edit",
    )


def _extend_unique(target: list[Any], additions: list[Any]) -> None:
    for value in additions:
        if value not in target:
            target.append(value)


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_text_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field}[{index}] must be a non-empty string")
        normalized.append(item.strip())
    return normalized


def _validate_source_item_ids(source_item_ids: list[str], target_item_id: str) -> list[str]:
    if not source_item_ids:
        raise ValueError("source_item_ids must not be empty")
    normalized = [_required_text(item_id, f"source_item_ids[{index}]") for index, item_id in enumerate(source_item_ids)]
    if len(normalized) != len(set(normalized)):
        raise ValueError("source_item_ids must be unique")
    if target_item_id in normalized:
        raise ValueError("target item cannot also be a source item")
    return normalized


def _validate_split_item_input(index: int, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"new_items[{index}] must be an object")
    unsupported = sorted(set(item) - SPLIT_ITEM_ALLOWED_KEYS)
    if unsupported:
        raise ValueError(f"new_items[{index}] contains unsupported keys: {unsupported}")

    normalized = {
        "tracker_item_id": _required_text(item.get("tracker_item_id"), f"new_items[{index}].tracker_item_id"),
        "canonical_content": _required_text(item.get("canonical_content"), f"new_items[{index}].canonical_content"),
    }
    if "status" in item:
        normalized["status"] = _required_text(item.get("status"), f"new_items[{index}].status")
        if normalized["status"] not in TRACKER_STATUSES:
            raise ValueError(f"new_items[{index}].status is not a valid tracker status")
    if "candidate_history_refs" in item:
        normalized["candidate_history_refs"] = _optional_text_list(
            item.get("candidate_history_refs"),
            f"new_items[{index}].candidate_history_refs",
        )
    for optional_key in ["planted", "updates", "resolved"]:
        if optional_key in item:
            normalized[optional_key] = item[optional_key]
    return normalized


def _validate_split_items(
    *,
    tracker_type: TrackerType,
    source: dict[str, Any],
    new_items: list[dict[str, Any]],
    existing_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(new_items, list) or not new_items:
        raise ValueError("new_items must not be empty")

    normalized_items = [_validate_split_item_input(index, item) for index, item in enumerate(new_items)]
    new_ids = [item["tracker_item_id"] for item in normalized_items]
    if len(new_ids) != len(set(new_ids)):
        raise ValueError("split item ids must be unique")
    conflicts = sorted(item_id for item_id in new_ids if item_id in existing_ids)
    if conflicts:
        raise ValueError(f"split item ids already exist: {conflicts}")

    for index, item in enumerate(normalized_items):
        candidate = {
            "tracker_item_id": item["tracker_item_id"],
            "tracker_type": tracker_type,
            "canonical_content": item["canonical_content"],
            "source_specificity": source.get("source_specificity", "source_specific"),
            "status": item.get("status", source.get("status", "open")),
            "planted": item.get("planted", deepcopy(source.get("planted", {}))),
            "updates": item.get("updates", []),
            "resolved": item.get("resolved"),
            "manual_override": ManualOverride().model_dump(mode="json"),
            "candidate_history_refs": item.get("candidate_history_refs", []),
        }
        try:
            TrackerItem.model_validate(candidate)
        except ValidationError as exc:
            raise ValueError(f"new_items[{index}] does not match tracker item contract: {exc}") from exc
    return normalized_items


def apply_tracker_manual_override(
    run_dir: str | Path,
    *,
    tracker_type: TrackerType = "foreshadowing",
    tracker_item_id: str,
    status: TrackerStatus | None = None,
    resolved_chapter_index: int | None = None,
    resolution_method: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    tracker_path, tracker = _load_tracker(run_dir, tracker_type)
    updated_at = _utc_now()
    override = _manual_override(
        status=status,  # type: ignore[arg-type]
        resolved_chapter_index=resolved_chapter_index,
        resolution_method=resolution_method,
        reason=reason,
        updated_at=updated_at,
    )

    item = _find_item(tracker, tracker_item_id)
    before = deepcopy(item)
    item["manual_override"] = override

    write_json(tracker_path, tracker)
    _append_log_event(
        run_dir,
        {
            "operation": "override",
            "tracker_type": tracker_type,
            "tracker_item_id": tracker_item_id,
            "manual_override": override,
            "before": before,
            "after": deepcopy(item),
            "logged_at": updated_at,
        },
    )
    _invalidate_after_manual_edit(
        run_dir,
        tracker_type=tracker_type,
        tracker_item_id=tracker_item_id,
        reason=reason,
    )
    return tracker


def merge_tracker_items(
    run_dir: str | Path,
    *,
    tracker_type: TrackerType,
    target_item_id: str,
    source_item_ids: list[str],
    reason: str | None = None,
) -> dict[str, Any]:
    target_item_id = _required_text(target_item_id, "target_item_id")
    source_item_ids = _validate_source_item_ids(source_item_ids, target_item_id)

    tracker_path, tracker = _load_tracker(run_dir, tracker_type)
    updated_at = _utc_now()
    target = _find_item(tracker, target_item_id)
    sources = [_find_item(tracker, source_item_id) for source_item_id in source_item_ids]
    before_items = [deepcopy(target), *[deepcopy(source) for source in sources]]

    for source in sources:
        _extend_unique(target.setdefault("candidate_history_refs", []), source.get("candidate_history_refs", []))
        _extend_unique(target.setdefault("updates", []), source.get("updates", []))
        if not target.get("resolved") and source.get("resolved"):
            target["resolved"] = source["resolved"]
        source["manual_override"] = _manual_override(
            status="abandoned",
            resolution_method=f"merged_into:{target_item_id}",
            reason=reason,
            updated_at=updated_at,
        )

    write_json(tracker_path, tracker)
    _append_log_event(
        run_dir,
        {
            "operation": "merge",
            "tracker_type": tracker_type,
            "target_item_id": target_item_id,
            "source_item_ids": source_item_ids,
            "before": before_items,
            "after": [deepcopy(target), *[deepcopy(source) for source in sources]],
            "reason": reason,
            "logged_at": updated_at,
        }
    )
    _invalidate_after_manual_edit(
        run_dir,
        tracker_type=tracker_type,
        tracker_item_id=target_item_id,
        reason=reason,
    )
    return tracker


def split_tracker_item(
    run_dir: str | Path,
    *,
    tracker_type: TrackerType,
    source_item_id: str,
    new_items: list[dict[str, Any]],
    reason: str | None = None,
) -> dict[str, Any]:
    source_item_id = _required_text(source_item_id, "source_item_id")

    tracker_path, tracker = _load_tracker(run_dir, tracker_type)
    source = _find_item(tracker, source_item_id)
    existing_ids = {str(item.get("tracker_item_id")) for item in tracker.get("items", [])}
    normalized_items = _validate_split_items(
        tracker_type=tracker_type,
        source=source,
        new_items=new_items,
        existing_ids=existing_ids,
    )
    new_ids = [item["tracker_item_id"] for item in normalized_items]

    updated_at = _utc_now()
    before = deepcopy(source)
    source["manual_override"] = _manual_override(
        status="abandoned",
        resolution_method=f"split_into:{','.join(new_ids)}",
        reason=reason,
        updated_at=updated_at,
    )

    created = []
    for item in normalized_items:
        created_item = {
            "tracker_item_id": item["tracker_item_id"],
            "tracker_type": tracker_type,
            "canonical_content": item["canonical_content"],
            "source_specificity": source.get("source_specificity", "source_specific"),
            "status": item.get("status", source.get("status", "open")),
            "planted": item.get("planted", deepcopy(source.get("planted", {}))),
            "updates": item.get("updates", []),
            "resolved": item.get("resolved"),
            "manual_override": ManualOverride().model_dump(mode="json"),
            "candidate_history_refs": item.get("candidate_history_refs", []),
        }
        tracker.setdefault("items", []).append(created_item)
        created.append(deepcopy(created_item))

    tracker["item_count"] = len(tracker.get("items", []))
    write_json(tracker_path, tracker)
    _append_log_event(
        run_dir,
        {
            "operation": "split",
            "tracker_type": tracker_type,
            "source_item_id": source_item_id,
            "created_item_ids": new_ids,
            "before": before,
            "after": {"source": deepcopy(source), "created": created},
            "reason": reason,
            "logged_at": updated_at,
        },
    )
    _invalidate_after_manual_edit(
        run_dir,
        tracker_type=tracker_type,
        tracker_item_id=source_item_id,
        reason=reason,
    )
    return tracker
