from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json

from ..config import DEFAULT_ENCODING


PACKAGE_SCHEMA_VERSION = "story_analyzer_handoff.v1"
GENERATOR_CONTRACT_VERSION = "story_generator_import.v1"
VALIDATION_SCHEMA_VERSION = "story_analyzer.validation_summary.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_handoff_output_dir(run_dir: str | Path) -> Path:
    date = datetime.now().strftime("%Y%m%d")
    analyzer_root = Path(__file__).resolve().parents[3]
    parent_story_root = analyzer_root.parent
    if all((parent_story_root / name).exists() for name in ("03_Analysis_Outputs", "04_Handoff_Packages")):
        package_root = parent_story_root / "04_Handoff_Packages"
    else:
        package_root = analyzer_root / "data" / "handoff_exports"
    run_name = Path(run_dir).name or "run"
    return package_root / f"handoff_package_v1_{date}_{run_name}"


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def checksum_excluded(path: Path, package_dir: Path) -> bool:
    rel = relative_path(path, package_dir)
    return rel in {"checksums.sha256", "validation_summary.json"}


def build_checksums(package_dir: str | Path) -> str:
    root = Path(package_dir)
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not checksum_excluded(path, root):
            lines.append(f"{sha256_file(path)}  {relative_path(path, root)}")
    return "\n".join(lines) + ("\n" if lines else "")


def parse_checksums(text: str) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        if not digest or not rel:
            raise ValueError(f"Invalid checksum line: {line}")
        checksums[rel] = digest
    return checksums
