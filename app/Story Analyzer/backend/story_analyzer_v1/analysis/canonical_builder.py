from __future__ import annotations

from pathlib import Path
import json

from ..config import DEFAULT_ENCODING, ensure_dir
from ..models.canonical import CanonicalChapterAnalysis
from .semantic_normalizer import build_all_canonical_chapters


CANONICAL_DIRNAME = "canonical_chapter_analysis"


def canonical_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / CANONICAL_DIRNAME


def canonical_chapter_path(run_dir: str | Path, chapter_id: str) -> Path:
    return canonical_dir(run_dir) / f"{chapter_id}.json"


def write_canonical_chapter(
    chapter: CanonicalChapterAnalysis,
    run_dir: str | Path,
) -> Path:
    out_dir = ensure_dir(canonical_dir(run_dir))
    out_path = out_dir / f"{chapter.chapter_id}.json"
    out_path.write_text(
        json.dumps(chapter.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding=DEFAULT_ENCODING,
    )
    return out_path


def build_canonical_chapters(
    run_dir: str | Path,
    *,
    semantic_input: str | Path | None = None,
) -> list[Path]:
    paths: list[Path] = []
    for canonical in build_all_canonical_chapters(run_dir, semantic_input=semantic_input):
        paths.append(write_canonical_chapter(canonical, run_dir))
    return paths


def load_canonical_chapters(run_dir: str | Path) -> list[CanonicalChapterAnalysis]:
    root = canonical_dir(run_dir)
    if not root.exists():
        raise FileNotFoundError(root)
    chapters = []
    for path in sorted(root.glob("chapter_*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        chapters.append(CanonicalChapterAnalysis.model_validate(data))
    if not chapters:
        raise ValueError(f"No canonical chapter files found in {root}")
    return chapters
