from __future__ import annotations

from pathlib import Path
from typing import Any

from .reconciler import reconcile_tracker
from .tracker_store import foreshadowing_tracker_path


def reconcile_foreshadowing_tracker(run_dir: str | Path) -> dict[str, Any]:
    return reconcile_tracker(
        run_dir,
        tracker_type="foreshadowing",
        item_prefix="F",
        schema_version="story_analyzer.foreshadowing_tracker.v1",
        output_path=foreshadowing_tracker_path(run_dir),
    )

