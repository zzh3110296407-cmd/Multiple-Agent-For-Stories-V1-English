from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from ..config import DEFAULT_ENCODING


METRICS_SCHEMA_VERSION = "story_analyzer.quality_metrics_report.v1"
METRICS_FILENAME = "quality_metrics_report.json"
TRACKER_FILES = [
    "foreshadowing_tracker.json",
    "mystery_tracker.json",
    "relationship_debt_tracker.json",
    "world_rule_reveal_tracker.json",
]
MODULE_FILES = ["chapter_modules.json", "arc_modules.json", "book_modules.json"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def _rate(numerator: int | None, denominator: int | None, *, reason: str = "") -> dict[str, Any]:
    if numerator is None or denominator is None or denominator <= 0:
        return {
            "value": None,
            "numerator": numerator,
            "denominator": denominator,
            "status": "unavailable",
            "reason": reason or "insufficient_data",
        }
    return {
        "value": round(numerator / denominator, 6),
        "numerator": numerator,
        "denominator": denominator,
        "status": "available",
        "reason": reason,
    }


def _chapters(source_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    chapters = source_manifest.get("chapters", [])
    return chapters if isinstance(chapters, list) else []


def _canonical_chapters(run_dir: Path) -> list[dict[str, Any]]:
    root = run_dir / "canonical_chapter_analysis"
    if not root.exists():
        root = run_dir / "canonical" / "chapters"
    if not root.exists():
        return []
    return [_read_json(path) for path in sorted(root.glob("chapter_*.json"))]


def _tracker_items(run_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    tracker_root = run_dir / "trackers"
    for filename in TRACKER_FILES:
        payload = _read_json(tracker_root / filename)
        raw_items = payload.get("items", [])
        if isinstance(raw_items, list):
            items.extend(item for item in raw_items if isinstance(item, dict))
    return items


def _modules(run_dir: Path) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    module_root = run_dir / "modules"
    for filename in MODULE_FILES:
        payload = _read_json(module_root / filename)
        raw_modules = payload.get("modules", [])
        if isinstance(raw_modules, list):
            modules.extend(module for module in raw_modules if isinstance(module, dict))
    return modules


def _suspicious_title_rate(source_manifest: dict[str, Any]) -> dict[str, Any]:
    chapters = _chapters(source_manifest)
    suspicious = sum(1 for chapter in chapters if chapter.get("title_status") == "suspicious")
    return _rate(suspicious, len(chapters), reason="source_input_manifest.title_status")


def _chapter_repair_rate(canonical_chapters: list[dict[str, Any]]) -> dict[str, Any]:
    requires_repair = 0
    for chapter in canonical_chapters:
        quality = chapter.get("quality", {})
        if isinstance(quality, dict) and quality.get("requires_repair_pass") is True:
            requires_repair += 1
    return _rate(requires_repair, len(canonical_chapters), reason="canonical.quality.requires_repair_pass")


def _tracker_duplicate_rates(items: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_content: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        content = str(item.get("canonical_content", "")).strip()
        if content:
            by_content[content].append(item)
    duplicate_items = sum(1 for group in by_content.values() if len(group) > 1)
    conflict_items = 0
    for group in by_content.values():
        statuses = {str(item.get("status", "")) for item in group if item.get("status") is not None}
        if len(group) > 1 and len(statuses) > 1:
            conflict_items += 1
    return (
        _rate(duplicate_items, len(items), reason="duplicate canonical_content across tracker items"),
        _rate(conflict_items, len(items), reason="duplicate tracker content with conflicting statuses"),
    )


def _arc_metrics(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = _read_json(run_dir / "arcs" / "arc_candidates.json")
    candidate_count = len(candidates.get("major_arcs", []) or []) + len(candidates.get("sub_arcs", []) or [])
    major = _read_json(run_dir / "arcs" / "major_arcs.json")
    sub = _read_json(run_dir / "arcs" / "sub_arcs.json")
    confirmed_count = len(major.get("arcs", []) or []) + len(sub.get("arcs", []) or [])
    review = _read_json(run_dir / "arcs" / "arc_review.json")
    user_edits = review.get("user_edits", [])
    edit_count = len(user_edits) if isinstance(user_edits, list) else 0
    return (
        _rate(confirmed_count, candidate_count, reason="confirmed major/sub arcs divided by candidate arcs"),
        _rate(edit_count, candidate_count, reason="arc_review.user_edits divided by candidate arcs"),
    )


def _module_missing_dependency_rate(run_dir: Path) -> dict[str, Any]:
    report = _read_json(run_dir / "modules" / "module_conflict_report.json")
    module_count = int(report.get("module_count", 0) or 0)
    conflicts = report.get("conflicts", [])
    missing_dependency_count = 0
    if isinstance(conflicts, list):
        missing_dependency_count = sum(
            1 for conflict in conflicts if isinstance(conflict, dict) and conflict.get("conflict_type") == "missing_dependency"
        )
    return _rate(missing_dependency_count, module_count, reason="module_conflict_report missing_dependency conflicts")


def _transferable_leak_rate(modules: list[dict[str, Any]]) -> dict[str, Any]:
    transferable = [module for module in modules if module.get("source_specificity") == "transferable"]
    leak_count = 0
    for module in transferable:
        content = module.get("content", {})
        content_text = json.dumps(content, ensure_ascii=False)
        if "source_specific_elements" in content_text:
            leak_count += 1
    return _rate(leak_count, len(transferable), reason="transferable module content contains source_specific_elements")


def _handoff_validation_pass_rate(package_dir: str | Path | None) -> dict[str, Any]:
    if not package_dir:
        return _rate(None, None, reason="package_dir_not_provided")
    validation = _read_json(Path(package_dir) / "validation_summary.json")
    status = validation.get("validation_status")
    if not status:
        return _rate(None, None, reason="validation_summary_missing")
    return _rate(1 if status == "passed" else 0, 1, reason=f"handoff validation_status={status}")


def build_quality_metrics_report(run_dir: str | Path, package_dir: str | Path | None = None) -> dict[str, Any]:
    run_path = Path(run_dir)
    source_manifest = _read_json(run_path / "source_input_manifest.json")
    canonical_chapters = _canonical_chapters(run_path)
    tracker_items = _tracker_items(run_path)
    modules = _modules(run_path)
    tracker_duplicate_rate, tracker_state_conflict_rate = _tracker_duplicate_rates(tracker_items)
    arc_acceptance_rate, arc_boundary_edit_rate = _arc_metrics(run_path)
    metrics = {
        "chapter_boundary_precision": _rate(None, None, reason="requires_labeled_boundary_baseline"),
        "chapter_boundary_recall": _rate(None, None, reason="requires_labeled_boundary_baseline"),
        "suspicious_title_rate": _suspicious_title_rate(source_manifest),
        "chapter_repair_rate": _chapter_repair_rate(canonical_chapters),
        "repair_success_rate": _rate(None, None, reason="requires_repair_history_outcome_counts"),
        "tracker_duplicate_rate": tracker_duplicate_rate,
        "tracker_state_conflict_rate": tracker_state_conflict_rate,
        "arc_candidate_user_acceptance_rate": arc_acceptance_rate,
        "arc_boundary_edit_rate": arc_boundary_edit_rate,
        "module_missing_dependency_rate": _module_missing_dependency_rate(run_path),
        "transferable_module_proper_noun_leak_rate": _transferable_leak_rate(modules),
        "handoff_validation_pass_rate": _handoff_validation_pass_rate(package_dir),
    }
    status_counts = Counter(metric["status"] for metric in metrics.values())
    report = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "status": "ready",
        "authority": "advisory_only",
        "can_write_formal_state": False,
        "generated_at": _now_iso(),
        "run_dir": str(run_path),
        "package_dir": str(package_dir or ""),
        "metric_count": len(metrics),
        "available_metric_count": status_counts.get("available", 0),
        "unavailable_metric_count": status_counts.get("unavailable", 0),
        "metrics": metrics,
    }
    _write_json(run_path / "quality" / METRICS_FILENAME, report)
    return report
