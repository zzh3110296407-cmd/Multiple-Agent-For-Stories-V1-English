from __future__ import annotations

from pathlib import Path
from typing import Any

from .reconciler import reconcile_tracker
from .tracker_store import relationship_debt_tracker_path


def reconcile_relationship_debt_tracker(run_dir: str | Path) -> dict[str, Any]:
    return reconcile_tracker(
        run_dir,
        tracker_type="relationship_debt",
        item_prefix="R",
        schema_version="story_analyzer.relationship_debt_tracker.v1",
        output_path=relationship_debt_tracker_path(run_dir),
    )
