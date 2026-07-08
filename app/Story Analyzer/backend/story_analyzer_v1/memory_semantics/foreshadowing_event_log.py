"""Event-sourced foreshadowing state reconciliation."""

from __future__ import annotations

from collections import Counter


MEMORY_LANES = (
    "strict_foreshadowing",
    "plot_setup",
    "world_fact",
    "character_state",
    "quote_or_signal",
)

TRACKING_SCOPES = ("arc", "book", "local", "series")


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique(values: list) -> list:
    result = []
    for value in values:
        if value not in result and value is not None:
            result.append(value)
    return result


def _event_type_from_status(status: str) -> str:
    status = str(status or "planted")
    if status == "resolved":
        return "final_reveal"
    if status == "partially_resolved":
        return "partial_reveal"
    if status == "state_update":
        return "state_update"
    return "planted"


def _thread_events(item: dict) -> list[dict]:
    events = []
    for index, event in enumerate(item.get("history") or [], start=1):
        status = str(event.get("status") or "planted")
        events.append(
            {
                "event_id": f"{item.get('id', 'F000')}_EV{index:03d}",
                "event_type": event.get("event_type") or _event_type_from_status(status),
                "chapter_index": event.get("chapter_number"),
                "status": status,
                "content": event.get("content", ""),
                "source_model_id": event.get("source_model_id", ""),
                "source": event.get("source", ""),
            }
        )
    if not events:
        events.append(
            {
                "event_id": f"{item.get('id', 'F000')}_EV001",
                "event_type": _event_type_from_status(str(item.get("status") or "planted")),
                "chapter_index": item.get("planted_chapter") or item.get("resolved_in_chapter"),
                "status": item.get("status", "planted"),
                "content": item.get("canonical_content") or item.get("content") or "",
                "source_model_id": "",
                "source": "registry_item",
            }
        )
    return events


def _has_open_semantics(item: dict) -> bool:
    return bool(item.get("open_questions")) or bool(item.get("partial_resolution_chapters"))


def _has_series_semantics(item: dict) -> bool:
    return item.get("resolution_scope") == "series" or item.get("tracking_scope") == "series"


def _force_partial(item: dict, reason: str, adjustments: list[dict]) -> None:
    if item.get("status") != "partially_resolved":
        adjustments.append({"id": item.get("id"), "action": "status_to_partially_resolved", "reason": reason})
    item["status"] = "partially_resolved"
    partial_chapters = _unique(
        _as_list(item.get("partial_resolution_chapters"))
        + _as_list(item.get("last_partial_resolution_chapter"))
        + _as_list(item.get("resolved_in_chapter"))
    )
    if partial_chapters:
        item["partial_resolution_chapters"] = partial_chapters
        item["last_partial_resolution_chapter"] = partial_chapters[-1]
    item.pop("resolved_in_chapter", None)
    item["resolution_scope"] = "series" if _has_series_semantics(item) else item.get("resolution_scope", "book")
    item["tracking_scope"] = "series" if item["resolution_scope"] == "series" else item.get("tracking_scope", "book")
    if item["tracking_scope"] == "series" and not item.get("open_questions"):
        item["open_questions"] = ["long_horizon_thread_requires_future_confirmation_or_consequence"]


def _normalize_item(item: dict, adjustments: list[dict]) -> None:
    status = str(item.get("status") or "planted").strip().lower()
    if status in {"reinforced", "reiterated", "observed", "confirmed", "pending"}:
        status = "planted"
    if status in {"closed", "complete", "completed"}:
        status = "resolved"
    item["status"] = status

    if status == "resolved" and (_has_open_semantics(item) or _has_series_semantics(item)):
        _force_partial(item, "resolved_with_open_or_series_semantics", adjustments)
    elif status == "partially_resolved":
        partial_chapters = _unique(
            _as_list(item.get("partial_resolution_chapters"))
            + _as_list(item.get("last_partial_resolution_chapter"))
            + _as_list(item.get("resolved_in_chapter"))
        )
        item.pop("resolved_in_chapter", None)
        if partial_chapters:
            item["partial_resolution_chapters"] = partial_chapters
            item["last_partial_resolution_chapter"] = partial_chapters[-1]
        item.setdefault("resolution_scope", "series")
    elif status == "resolved":
        item.pop("open_questions", None)
        item.pop("partial_resolution_chapters", None)
        item.pop("last_partial_resolution_chapter", None)
        if item.get("resolution_scope") == "series":
            item["resolution_scope"] = "book"

    if item.get("memory_lane") not in MEMORY_LANES:
        item["memory_lane"] = "strict_foreshadowing" if item.get("tracking_scope") == "series" else "plot_setup"
    if item.get("tracking_scope") not in TRACKING_SCOPES:
        item["tracking_scope"] = "series" if item.get("resolution_scope") == "series" else "book"


def _contract_errors(items: list[dict]) -> list[dict]:
    errors: list[dict] = []
    for item in items:
        status = item.get("status")
        if status == "resolved":
            for field in ("open_questions", "partial_resolution_chapters"):
                if item.get(field):
                    errors.append({"id": item.get("id"), "field": field, "error": "resolved_must_not_have_field"})
            if item.get("resolution_scope") == "series":
                errors.append({"id": item.get("id"), "field": "resolution_scope", "error": "resolved_must_not_be_series"})
        if status == "partially_resolved" and item.get("resolved_in_chapter"):
            errors.append({"id": item.get("id"), "field": "resolved_in_chapter", "error": "partial_must_not_have_final_chapter"})
    return errors


def _views(items: list[dict]) -> dict[str, list[dict]]:
    views = {lane: [] for lane in MEMORY_LANES}
    for item in items:
        lane = item.get("memory_lane")
        if lane in views:
            views[lane].append(item)
    return views


def apply_foreshadowing_semantic_contract(registry: dict) -> dict:
    registry.setdefault("items", [])
    adjustments: list[dict] = []
    for item in registry.get("items", []):
        if isinstance(item, dict):
            _normalize_item(item, adjustments)

    items = [item for item in registry.get("items", []) if isinstance(item, dict)]
    registry["event_log"] = {
        "schema_version": "story_analyzer.foreshadowing_event_log.v1",
        "threads": [
            {
                "thread_id": item.get("id"),
                "events": _thread_events(item),
                "computed_state": {
                    "status": item.get("status"),
                    "tracking_scope": item.get("tracking_scope"),
                    "memory_lane": item.get("memory_lane"),
                    "open_question_count": len(item.get("open_questions") or []),
                },
            }
            for item in items
        ],
    }
    registry["semantic_contract_adjustments"] = adjustments
    registry["semantic_contract_errors"] = _contract_errors(items)
    registry["views"] = _views(items)

    scope_counts = Counter(item.get("tracking_scope") for item in items)
    lane_counts = Counter(item.get("memory_lane") for item in items)
    registry["counts_by_tracking_scope"] = {scope: scope_counts.get(scope, 0) for scope in TRACKING_SCOPES}
    registry["counts_by_memory_lane"] = {lane: lane_counts.get(lane, 0) for lane in MEMORY_LANES}
    registry["strict_foreshadowing_item_count"] = len(registry["views"]["strict_foreshadowing"])
    return registry
