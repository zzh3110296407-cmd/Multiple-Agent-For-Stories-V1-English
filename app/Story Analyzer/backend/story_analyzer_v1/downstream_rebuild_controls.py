from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pipeline.resume import plan_downstream_rebuild, resume_from_invalidation


REBUILD_CONTROLS_SCHEMA_VERSION = "story_analyzer.downstream_rebuild_controls.v1"


def _latest_report_path(run_dir: Path) -> Path:
    return run_dir / "pipeline" / "downstream_rebuild_report.json"


def _read_latest_report(run_dir: Path) -> dict[str, Any] | None:
    path = _latest_report_path(run_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_downstream_rebuild_controls(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir)
    plan = plan_downstream_rebuild(run_path)
    return {
        "schema_version": REBUILD_CONTROLS_SCHEMA_VERSION,
        "run_dir": str(run_path),
        "plan": plan,
        "can_run": bool(plan.get("invalidated_step_ids")),
        "latest_report": _read_latest_report(run_path),
    }


def run_downstream_rebuild_from_controls(
    run_dir: str | Path,
    *,
    package_out: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    normalized_package_out = Path(package_out) if package_out else None
    result = resume_from_invalidation(
        run_path,
        package_out=normalized_package_out,
        dry_run=dry_run,
    )
    return {
        "schema_version": REBUILD_CONTROLS_SCHEMA_VERSION,
        "run_dir": str(run_path),
        "dry_run": bool(dry_run),
        "result": result,
        "plan_after": plan_downstream_rebuild(run_path),
        "latest_report": None if dry_run else _read_latest_report(run_path),
    }
