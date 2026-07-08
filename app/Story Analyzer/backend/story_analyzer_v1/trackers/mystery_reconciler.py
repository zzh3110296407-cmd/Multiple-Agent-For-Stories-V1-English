from __future__ import annotations

from pathlib import Path
from typing import Any

from .reconciler import reconcile_tracker
from .tracker_store import mystery_tracker_path


def reconcile_mystery_tracker(run_dir: str | Path) -> dict[str, Any]:
    return reconcile_tracker(
        run_dir,
        tracker_type="mystery",
        item_prefix="M",
        schema_version="story_analyzer.mystery_tracker.v1",
        output_path=mystery_tracker_path(run_dir),
    )

