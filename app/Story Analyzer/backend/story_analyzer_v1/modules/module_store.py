from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from ..config import DEFAULT_ENCODING, ensure_dir


MODULES_DIRNAME = "modules"
CHAPTER_MODULES_FILENAME = "chapter_modules.json"
ARC_MODULES_FILENAME = "arc_modules.json"
BOOK_MODULES_FILENAME = "book_modules.json"
MODULE_CATALOG_FILENAME = "module_catalog.json"
MODULE_CONFLICT_REPORT_FILENAME = "module_conflict_report.json"


def modules_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / MODULES_DIRNAME


def ensure_modules_dir(run_dir: str | Path) -> Path:
    return ensure_dir(modules_dir(run_dir))


def chapter_modules_path(run_dir: str | Path) -> Path:
    return modules_dir(run_dir) / CHAPTER_MODULES_FILENAME


def arc_modules_path(run_dir: str | Path) -> Path:
    return modules_dir(run_dir) / ARC_MODULES_FILENAME


def book_modules_path(run_dir: str | Path) -> Path:
    return modules_dir(run_dir) / BOOK_MODULES_FILENAME


def module_catalog_path(run_dir: str | Path) -> Path:
    return modules_dir(run_dir) / MODULE_CATALOG_FILENAME


def module_conflict_report_path(run_dir: str | Path) -> Path:
    return modules_dir(run_dir) / MODULE_CONFLICT_REPORT_FILENAME


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))
