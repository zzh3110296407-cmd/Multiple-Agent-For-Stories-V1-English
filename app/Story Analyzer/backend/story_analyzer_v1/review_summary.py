from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVIEW_SUMMARY_SCHEMA_VERSION = "story_analyzer.review_summary.v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> tuple[str, dict[str, Any], str]:
    if not path.exists():
        return "missing", {}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return "invalid", {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return "invalid", {}, "JSON root is not an object"
    return "available", payload, ""


def _count_chapters(source_manifest: dict[str, Any]) -> int:
    explicit = source_manifest.get("chapter_count")
    if isinstance(explicit, int):
        return explicit
    chapters = source_manifest.get("chapters")
    if isinstance(chapters, list):
        return len(chapters)
    return 0


def _sample(items: Any, limit: int = 8) -> list[Any]:
    if not isinstance(items, list):
        return []
    return items[:limit]


def _status_from_report(state: str, report: dict[str, Any]) -> str:
    if state != "available":
        return state
    return str(report.get("status") or report.get("validation_status") or "unknown")


def _resolve_handoff_package(run_dir: Path, package_dir: str | Path | None) -> Path | None:
    if package_dir is not None:
        return Path(package_dir)

    for report_path in [
        run_dir / "pipeline" / "downstream_rebuild_report.json",
        run_dir / "pipeline" / "run_summary.json",
    ]:
        state, report, _ = _read_json(report_path)
        if state != "available":
            continue
        handoff = report.get("handoff")
        if isinstance(handoff, dict) and handoff.get("package_dir"):
            return Path(str(handoff["package_dir"]))

    rebuilds_dir = run_dir / "rebuilds"
    if rebuilds_dir.exists():
        candidates = [path for path in rebuilds_dir.glob("handoff_package_*") if path.is_dir()]
        if candidates:
            return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return None


def _build_source_summary(run_dir: Path) -> dict[str, Any]:
    source_path = run_dir / "source_input_manifest.json"
    state, source, error = _read_json(source_path)
    summary = {
        "state": state,
        "path": str(source_path),
        "work_title": run_dir.name,
        "chapter_count": 0,
    }
    if error:
        summary["error"] = error
    if state == "available":
        summary.update(
            {
                "work_title": source.get("work_title") or source.get("title") or run_dir.name,
                "chapter_count": _count_chapters(source),
                "schema_version": source.get("schema_version", ""),
                "source_sha256": source.get("source_sha256", ""),
            }
        )
    return summary


def _build_pipeline_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "pipeline" / "run_summary.json"
    state, report, error = _read_json(path)
    summary = {
        "state": state,
        "path": str(path),
        "status": _status_from_report(state, report),
        "current_stage": report.get("current_stage", "") if state == "available" else "",
        "next_action": report.get("next_action", "") if state == "available" else "",
    }
    if error:
        summary["error"] = error
    return summary


def _build_quality_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "quality" / "quality_report.json"
    state, report, error = _read_json(path)
    summary = {
        "state": state,
        "path": str(path),
        "status": _status_from_report(state, report),
        "chapter_count": int(report.get("chapter_count", 0) or 0) if state == "available" else 0,
        "blocking_issue_count": int(report.get("blocking_issue_count", 0) or 0) if state == "available" else 0,
        "warning_count": int(report.get("warning_count", 0) or 0) if state == "available" else 0,
        "semantic_sources": report.get("semantic_sources", {}) if state == "available" else {},
        "issue_preview": _sample(report.get("issues"), 8) if state == "available" else [],
    }
    if error:
        summary["error"] = error
    return summary


def _build_tracker_edit_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "trackers" / "tracker_edit_report.json"
    state, report, error = _read_json(path)
    summary = {
        "state": state,
        "path": str(path),
        "status": _status_from_report(state, report),
        "operation_count": int(report.get("operation_count", 0) or 0) if state == "available" else 0,
        "manual_override_item_count": int(report.get("manual_override_item_count", 0) or 0)
        if state == "available"
        else 0,
        "operations_by_type": report.get("operations_by_type", {}) if state == "available" else {},
        "operations_by_tracker_type": report.get("operations_by_tracker_type", {}) if state == "available" else {},
        "semantic_risk_level": report.get("semantic_risk_level", "unknown") if state == "available" else "missing",
        "semantic_review": report.get("semantic_review", {}) if state == "available" else {},
        "risk_reasons": report.get("risk_reasons", []) if state == "available" else [],
        "recommended_review_points": report.get("recommended_review_points", []) if state == "available" else [],
        "operation_preview": _sample(report.get("operations"), 8) if state == "available" else [],
        "manual_override_preview": _sample(report.get("manual_override_items"), 8) if state == "available" else [],
    }
    if error:
        summary["error"] = error
    return summary


def _build_manual_edit_audit_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "trackers" / "tracker_override_log.json"
    state, log, error = _read_json(path)
    events = log.get("events", []) if state == "available" else []
    summary = {
        "state": state,
        "path": str(path),
        "event_count": len(events) if isinstance(events, list) else 0,
        "event_preview": _sample(events, 8),
    }
    if error:
        summary["error"] = error
    return summary


def _build_downstream_rebuild_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "pipeline" / "downstream_rebuild_report.json"
    state, report, error = _read_json(path)
    summary = {
        "state": state,
        "path": str(path),
        "status": _status_from_report(state, report),
        "next_action": report.get("next_action", "") if state == "available" else "",
        "planned_stages": report.get("planned_stages", []) if state == "available" else [],
        "rebuilt_stages": report.get("rebuilt_stages", []) if state == "available" else [],
        "invalidated_step_ids": report.get("invalidated_step_ids", []) if state == "available" else [],
    }
    if error:
        summary["error"] = error
    return summary


def _build_generator_handoff_summary(run_dir: Path) -> dict[str, Any]:
    handoff_dir = run_dir / "generator_handoff"
    validation_state, validation, validation_error = _read_json(handoff_dir / "validation_report.json")
    history_state, history, history_error = _read_json(handoff_dir / "repair_history.json")
    failed_path = handoff_dir / "handoff_failed_report.json"
    failed_state, failed, failed_error = _read_json(failed_path)
    validated_path = handoff_dir / "unified_generator_handoff.validated.json"
    compiled_path = handoff_dir / "unified_generator_handoff.json"
    failed_is_current = failed_state == "available" and (
        not validated_path.exists() or failed_path.stat().st_mtime >= validated_path.stat().st_mtime
    )
    validated_is_current = validated_path.exists() and not failed_is_current

    if failed_is_current:
        repair_status = "failed"
    elif validated_is_current:
        repair_status = "passed"
    elif history_state == "available":
        repair_status = "attempted"
    elif validation_state == "available" and validation.get("validation_status") == "failed":
        repair_status = "validation_failed"
    elif validation_state == "available":
        repair_status = "validation_passed"
    elif compiled_path.exists():
        repair_status = "compiled"
    else:
        repair_status = "missing"

    summary = {
        "state": "available" if handoff_dir.exists() else "missing",
        "path": str(handoff_dir),
        "validation_path": str(handoff_dir / "validation_report.json"),
        "validation_status": _status_from_report(validation_state, validation),
        "repair_status": repair_status,
        "repair_attempt_count": int(history.get("attempt_count", len(history.get("attempts", []))) or 0)
        if history_state == "available"
        else 0,
        "applied_repair_count": int(history.get("applied_repair_count", 0) or 0)
        if history_state == "available"
        else 0,
        "validated_handoff_path": str(validated_path) if validated_is_current else "",
        "failed_report_path": str(failed_path) if failed_is_current else "",
        "failure_reason": failed.get("failure_reason", "") if failed_is_current else "",
        "history_state": history_state,
    }
    errors = {
        "validation_error": validation_error,
        "history_error": history_error,
        "failed_error": failed_error,
    }
    summary.update({key: value for key, value in errors.items() if value})
    return summary


def _build_handoff_summary(run_dir: Path, package_dir: str | Path | None) -> dict[str, Any]:
    generator_handoff = _build_generator_handoff_summary(run_dir)
    resolved_package = _resolve_handoff_package(run_dir, package_dir)
    if resolved_package is None:
        return {
            "state": "not_exported",
            "package_dir": "",
            "validation_path": "",
            "validation_status": "not_exported",
            "contract_version": "",
            "blocking_issue_count": 0,
            "warning_count": 0,
            "checks": {},
            "blocking_issue_preview": [],
            "warning_preview": [],
            "manifest_state": "missing",
            "manifest_work_title": "",
            "generator_handoff": generator_handoff,
        }

    package_path = Path(resolved_package)
    if not package_path.exists():
        return {
            "state": "missing_package",
            "package_dir": str(package_path),
            "validation_path": "",
            "validation_status": "missing_package",
            "contract_version": "",
            "blocking_issue_count": 1,
            "warning_count": 0,
            "checks": {},
            "blocking_issue_preview": [{"code": "PACKAGE_NOT_FOUND", "message": str(package_path)}],
            "warning_preview": [],
            "manifest_state": "missing",
            "manifest_work_title": "",
            "generator_handoff": generator_handoff,
        }

    validation_path = package_path / "validation_summary.json"
    state, validation, error = _read_json(validation_path)
    manifest_state, manifest, manifest_error = _read_json(package_path / "package_manifest.json")
    summary = {
        "state": state,
        "package_dir": str(package_path),
        "validation_path": str(validation_path),
        "validation_status": _status_from_report(state, validation),
        "blocking_issue_count": int(validation.get("blocking_issue_count", 0) or 0) if state == "available" else 0,
        "warning_count": int(validation.get("warning_count", 0) or 0) if state == "available" else 0,
        "checks": validation.get("checks", {}) if state == "available" else {},
        "blocking_issue_preview": _sample(validation.get("blocking_issues"), 8) if state == "available" else [],
        "warning_preview": _sample(validation.get("warnings"), 8) if state == "available" else [],
        "manifest_state": manifest_state,
        "contract_version": manifest.get("contract_version", "") if manifest_state == "available" else "",
        "manifest_work_title": manifest.get("work_title", "") if manifest_state == "available" else "",
        "generator_handoff": generator_handoff,
    }
    if error:
        summary["error"] = error
    if manifest_error:
        summary["manifest_error"] = manifest_error
    return summary


def build_review_summary(run_dir: str | Path, package_dir: str | Path | None = None) -> dict[str, Any]:
    """Build a read-only local review summary for a Story Analyzer v1 run."""

    run_path = Path(run_dir)
    source = _build_source_summary(run_path)
    return {
        "schema_version": REVIEW_SUMMARY_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "run_dir": str(run_path),
        "run": {
            "state": "available" if run_path.exists() else "missing",
            "name": run_path.name,
            "work_title": source["work_title"],
            "chapter_count": source["chapter_count"],
        },
        "source": source,
        "pipeline": _build_pipeline_summary(run_path),
        "quality": _build_quality_summary(run_path),
        "tracker_edit_report": _build_tracker_edit_summary(run_path),
        "manual_edit_audit": _build_manual_edit_audit_summary(run_path),
        "downstream_rebuild": _build_downstream_rebuild_summary(run_path),
        "handoff": _build_handoff_summary(run_path, package_dir),
    }
