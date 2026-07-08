from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from ..config import DEFAULT_ENCODING, ensure_dir


ARCS_DIRNAME = "arcs"
ARC_CANDIDATES_FILENAME = "arc_candidates.json"
ARC_REVIEW_FILENAME = "arc_review.json"
ARC_REVIEW_MARKDOWN_FILENAME = "arc_review.md"
MAJOR_ARCS_FILENAME = "major_arcs.json"
SUB_ARCS_FILENAME = "sub_arcs.json"


def arcs_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / ARCS_DIRNAME


def ensure_arcs_dir(run_dir: str | Path) -> Path:
    return ensure_dir(arcs_dir(run_dir))


def arc_candidates_path(run_dir: str | Path) -> Path:
    return arcs_dir(run_dir) / ARC_CANDIDATES_FILENAME


def arc_review_path(run_dir: str | Path) -> Path:
    return arcs_dir(run_dir) / ARC_REVIEW_FILENAME


def arc_review_markdown_path(run_dir: str | Path) -> Path:
    return arcs_dir(run_dir) / ARC_REVIEW_MARKDOWN_FILENAME


def major_arcs_path(run_dir: str | Path) -> Path:
    return arcs_dir(run_dir) / MAJOR_ARCS_FILENAME


def sub_arcs_path(run_dir: str | Path) -> Path:
    return arcs_dir(run_dir) / SUB_ARCS_FILENAME


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_review_file(run_dir: str | Path, review_file: str | Path | None) -> Path:
    if review_file is None:
        return arc_review_path(run_dir)
    path = Path(review_file)
    return path if path.is_absolute() else Path(run_dir) / path
