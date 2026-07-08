from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from ..config import DEFAULT_ENCODING, ensure_dir


TRACKERS_DIRNAME = "trackers"
CANDIDATES_DIRNAME = "candidates"
FORESHADOWING_TRACKER_FILENAME = "foreshadowing_tracker.json"
MYSTERY_TRACKER_FILENAME = "mystery_tracker.json"
RELATIONSHIP_DEBT_TRACKER_FILENAME = "relationship_debt_tracker.json"
WORLD_RULE_REVEAL_TRACKER_FILENAME = "world_rule_reveal_tracker.json"
OVERRIDE_LOG_FILENAME = "tracker_override_log.json"
TRACKER_EDIT_REPORT_FILENAME = "tracker_edit_report.json"
TRACKER_EDIT_REPORT_MARKDOWN_FILENAME = "tracker_edit_report.md"
TRACKER_SEMANTIC_RECOMMENDATION_REPORT_FILENAME = "tracker_semantic_recommendation_report.json"


def trackers_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / TRACKERS_DIRNAME


def candidates_dir(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / CANDIDATES_DIRNAME


def ensure_trackers_dir(run_dir: str | Path) -> Path:
    return ensure_dir(trackers_dir(run_dir))


def ensure_candidates_dir(run_dir: str | Path) -> Path:
    return ensure_dir(candidates_dir(run_dir))


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def foreshadowing_tracker_path(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / FORESHADOWING_TRACKER_FILENAME


def mystery_tracker_path(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / MYSTERY_TRACKER_FILENAME


def relationship_debt_tracker_path(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / RELATIONSHIP_DEBT_TRACKER_FILENAME


def world_rule_reveal_tracker_path(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / WORLD_RULE_REVEAL_TRACKER_FILENAME


def override_log_path(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / OVERRIDE_LOG_FILENAME


def tracker_edit_report_path(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / TRACKER_EDIT_REPORT_FILENAME


def tracker_edit_report_markdown_path(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / TRACKER_EDIT_REPORT_MARKDOWN_FILENAME


def tracker_semantic_recommendation_report_path(run_dir: str | Path) -> Path:
    return trackers_dir(run_dir) / TRACKER_SEMANTIC_RECOMMENDATION_REPORT_FILENAME
