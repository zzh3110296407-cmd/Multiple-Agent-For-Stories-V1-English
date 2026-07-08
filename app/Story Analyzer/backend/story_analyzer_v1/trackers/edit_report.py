from __future__ import annotations

from pathlib import Path
from typing import Any

from .tracker_store import (
    foreshadowing_tracker_path,
    mystery_tracker_path,
    override_log_path,
    read_json,
    relationship_debt_tracker_path,
    tracker_edit_report_markdown_path,
    tracker_edit_report_path,
    world_rule_reveal_tracker_path,
    write_json,
)
from .semantic_recommendations import build_tracker_semantic_recommendation_report


REPORT_SCHEMA_VERSION = "story_analyzer.tracker_edit_report.v1"

TRACKER_REFS = {
    "foreshadowing": ("trackers/foreshadowing_tracker.json", foreshadowing_tracker_path),
    "mystery": ("trackers/mystery_tracker.json", mystery_tracker_path),
    "relationship_debt": ("trackers/relationship_debt_tracker.json", relationship_debt_tracker_path),
    "world_rule_reveal": ("trackers/world_rule_reveal_tracker.json", world_rule_reveal_tracker_path),
}


def _read_json_or_empty(path: Path, empty: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return empty
    return read_json(path)


def _operation_item_refs(event: dict[str, Any]) -> list[str]:
    operation = event.get("operation") or "override"
    if operation == "merge":
        return [str(event.get("target_item_id", "")), *[str(item_id) for item_id in event.get("source_item_ids", [])]]
    if operation == "split":
        return [str(event.get("source_item_id", "")), *[str(item_id) for item_id in event.get("created_item_ids", [])]]
    return [str(event.get("tracker_item_id", ""))]


def _operation_summary(index: int, event: dict[str, Any]) -> dict[str, Any]:
    operation = event.get("operation") or "override"
    item_refs = [item_ref for item_ref in _operation_item_refs(event) if item_ref]
    return {
        "operation_index": index,
        "operation": operation,
        "tracker_type": event.get("tracker_type", ""),
        "item_refs": item_refs,
        "reason": event.get("reason") or event.get("manual_override", {}).get("reason"),
        "logged_at": event.get("logged_at", ""),
        "audit_event_ref": f"trackers/tracker_override_log.json#events[{index - 1}]",
    }


def _manual_override_items(run_dir: str | Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for tracker_type, (ref, path_factory) in TRACKER_REFS.items():
        path = path_factory(run_dir)
        if not path.exists():
            continue
        tracker = read_json(path)
        for item in tracker.get("items", []):
            manual_override = item.get("manual_override") or {}
            if not manual_override.get("active"):
                continue
            items.append(
                {
                    "tracker_type": tracker_type,
                    "tracker_item_id": item.get("tracker_item_id", ""),
                    "status": item.get("status", ""),
                    "manual_status": manual_override.get("status"),
                    "resolution_method": manual_override.get("resolution_method"),
                    "reason": manual_override.get("reason"),
                    "updated_at": manual_override.get("updated_at"),
                    "canonical_content": item.get("canonical_content", ""),
                    "candidate_history_refs": item.get("candidate_history_refs", []),
                    "tracker_ref": ref,
                }
            )
    return sorted(items, key=lambda item: (item["tracker_type"], item["tracker_item_id"]))


def _counts_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, ""))
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _escape_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    risk_reason_lines = [f"- {_escape_cell(reason)}" for reason in report.get("risk_reasons", [])] or ["- none"]
    review_point_lines = [
        f"- {_escape_cell(point)}" for point in report.get("recommended_review_points", [])
    ] or ["- none"]
    lines = [
        "# Tracker Edit Report",
        "",
        f"Status: {report['status']}",
        f"Operations: {report['operation_count']}",
        f"Manual override items: {report['manual_override_item_count']}",
        f"Semantic risk: {str(report.get('semantic_risk_level', 'low')).title()}",
        "",
        "## Semantic Risk",
        "",
        f"Risk level: {str(report.get('semantic_risk_level', 'low')).title()}",
        f"Recommendation report: {report.get('semantic_review', {}).get('report_ref', 'trackers/tracker_semantic_recommendation_report.json')}",
        "",
        "### Risk Reasons",
        "",
        *risk_reason_lines,
        "",
        "### Recommended Review Points",
        "",
        *review_point_lines,
        "",
        "## Operations",
        "",
        "| # | Operation | Tracker Type | Item Refs | Semantic Risk | Reason | Logged At |",
        "|---|---|---|---|---|---|---|",
    ]
    if report["operations"]:
        for operation in report["operations"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_cell(operation["operation_index"]),
                        _escape_cell(operation["operation"]),
                        _escape_cell(operation["tracker_type"]),
                        _escape_cell(", ".join(operation["item_refs"])),
                        _escape_cell(operation.get("semantic_risk_level", "low")),
                        _escape_cell(operation.get("reason")),
                        _escape_cell(operation.get("logged_at")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | none | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Manual Override Items",
            "",
            "| Tracker Type | Item | Manual Status | Resolution Method | Reason |",
            "|---|---|---|---|---|",
        ]
    )
    if report["manual_override_items"]:
        for item in report["manual_override_items"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_cell(item["tracker_type"]),
                        _escape_cell(item["tracker_item_id"]),
                        _escape_cell(item.get("manual_status")),
                        _escape_cell(item.get("resolution_method")),
                        _escape_cell(item.get("reason")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | none | - | - | - |")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_tracker_edit_report(run_dir: str | Path) -> dict[str, Any]:
    log = _read_json_or_empty(
        override_log_path(run_dir),
        {
            "schema_version": "story_analyzer.tracker_override_log.v1",
            "events": [],
        },
    )
    semantic_report = build_tracker_semantic_recommendation_report(run_dir)
    operation_risks = {
        int(item["operation_index"]): item
        for item in semantic_report.get("operation_risks", [])
        if isinstance(item.get("operation_index"), int)
    }
    operations = []
    for index, event in enumerate(log.get("events", []), start=1):
        operation = _operation_summary(index, event)
        risk = operation_risks.get(index, {})
        operation["semantic_risk_level"] = risk.get("semantic_risk_level", "low")
        operation["risk_reasons"] = risk.get("risk_reasons", [])
        operation["recommended_review_points"] = risk.get("recommended_review_points", [])
        operations.append(operation)
    manual_items = _manual_override_items(run_dir)
    status = "manual_edits_present" if operations or manual_items else "no_manual_edits"
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "source_refs": {
            "audit_log_ref": "trackers/tracker_override_log.json",
            "tracker_refs": {tracker_type: ref for tracker_type, (ref, _factory) in TRACKER_REFS.items()},
        },
        "operation_count": len(operations),
        "operations_by_type": _counts_by_key(operations, "operation"),
        "operations_by_tracker_type": _counts_by_key(operations, "tracker_type"),
        "semantic_risk_level": semantic_report["semantic_risk_level"],
        "risk_reasons": semantic_report["risk_reasons"],
        "recommended_review_points": semantic_report["recommended_review_points"],
        "semantic_review": {
            "semantic_source_status": semantic_report["semantic_source_status"],
            "report_ref": "trackers/tracker_semantic_recommendation_report.json",
            "merge_candidate_count": semantic_report["merge_candidate_count"],
            "operation_risk_count": semantic_report["operation_risk_count"],
        },
        "operations": operations,
        "manual_override_item_count": len(manual_items),
        "manual_override_items": manual_items,
    }
    write_json(tracker_edit_report_path(run_dir), report)
    _write_markdown(tracker_edit_report_markdown_path(run_dir), report)
    return report
