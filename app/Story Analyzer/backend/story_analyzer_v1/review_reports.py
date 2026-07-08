from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVIEW_REPORTS_SCHEMA_VERSION = "story_analyzer.review_reports.v1"


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


def _sample(items: Any, limit: int = 8) -> list[Any]:
    return items[:limit] if isinstance(items, list) else []


def _resolve_report_path(candidates: list[Path], explicit_path: str | Path | None = None) -> Path:
    if explicit_path:
        return Path(explicit_path)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _resolve_package_dir(run_dir: Path, package_dir: str | Path | None) -> Path | None:
    if package_dir:
        return Path(package_dir)
    for report_path in [
        run_dir / "pipeline" / "downstream_rebuild_report.json",
        run_dir / "pipeline" / "run_summary.json",
    ]:
        state, report, _error = _read_json(report_path)
        if state != "available":
            continue
        handoff = report.get("handoff")
        if isinstance(handoff, dict) and handoff.get("package_dir"):
            return Path(str(handoff["package_dir"]))
    return None


def _build_conflict_report_summary(run_dir: Path, package_dir: str | Path | None) -> dict[str, Any]:
    resolved_package = _resolve_package_dir(run_dir, package_dir)
    candidates = [run_dir / "modules" / "module_conflict_report.json"]
    if resolved_package is not None:
        candidates.append(Path(resolved_package) / "modules" / "module_conflict_report.json")
    path = _resolve_report_path(candidates)
    state, report, error = _read_json(path)
    summary = {
        "state": state,
        "path": str(path),
        "status": report.get("status", state) if state == "available" else state,
        "conflict_count": int(report.get("conflict_count", 0) or 0) if state == "available" else 0,
        "max_severity": report.get("max_severity", "") if state == "available" else "",
        "preview": _sample(report.get("conflicts"), 8) if state == "available" else [],
    }
    if error:
        summary["error"] = error
    return summary


def _build_pattern_report_summary(run_dir: Path, pattern_report: str | Path | None) -> dict[str, Any]:
    path = _resolve_report_path(
        [
            run_dir / "synthesis" / "cross_work_pattern_synthesis_report.json",
            run_dir / "cross_work_pattern_synthesis_report.json",
        ],
        explicit_path=pattern_report,
    )
    state, report, error = _read_json(path)
    summary = {
        "state": state,
        "path": str(path),
        "status": report.get("status", state) if state == "available" else state,
        "pattern_count": int(report.get("pattern_count", 0) or 0) if state == "available" else 0,
        "work_count": int(report.get("work_count", 0) or 0) if state == "available" else 0,
        "preview": _sample(report.get("patterns"), 8) if state == "available" else [],
    }
    if error:
        summary["error"] = error
    return summary


def discover_recent_runs(root_dirs: list[str | Path], limit: int = 12) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    for root in root_dirs:
        root_path = Path(root)
        if not root_path.exists():
            continue
        candidates.extend(path for path in root_path.iterdir() if path.is_dir())
    recent = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
    return [
        {
            "name": path.name,
            "path": str(path),
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        for path in recent
    ]


def build_review_reports(
    run_dir: str | Path,
    *,
    package_dir: str | Path | None = None,
    pattern_report: str | Path | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    return {
        "schema_version": REVIEW_REPORTS_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "authority": "advisory_only",
        "can_write_formal_state": False,
        "run_dir": str(run_path),
        "package_dir": str(package_dir or ""),
        "pattern_report": str(pattern_report or ""),
        "module_conflict_report": _build_conflict_report_summary(run_path, package_dir),
        "cross_work_pattern_report": _build_pattern_report_summary(run_path, pattern_report),
    }
