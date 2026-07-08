from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from ..analysis.semantic_normalizer import load_chapter_text
from ..config import DEFAULT_ENCODING, SOURCE_MANIFEST_FILENAME, ensure_dir
from ..ingestion.source_manifest_builder import build_source_manifest, load_source_manifest
from ..models.common import sha256_text
from ..models.source import SourceInputManifest


RAW_SOURCE_INDEX_VERSION = "story_analyzer.raw_source_index.v2"
RAW_SOURCE_SEGMENTS_FILENAME = "raw_source_segments.jsonl"
RAW_SOURCE_INDEX_FILENAME = "raw_source_index.json"


def evidence_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / "evidence"


def raw_source_index_path(run_dir: str | Path) -> Path:
    return evidence_dir(run_dir) / RAW_SOURCE_INDEX_FILENAME


def raw_source_segments_path(run_dir: str | Path) -> Path:
    return evidence_dir(run_dir) / RAW_SOURCE_SEGMENTS_FILENAME


def _clip(value: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def normalize_for_search(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _trimmed_bounds(text: str) -> tuple[int, int]:
    start = len(text) - len(text.lstrip())
    end = len(text.rstrip())
    return start, end


def _token_hints(text: str, *, limit: int = 24) -> list[str]:
    normalized = normalize_for_search(text)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_'-]{2,}|[\u4e00-\u9fff]{2,8}", normalized)
    stopwords = {"the", "and", "with", "that", "this", "into", "from", "here", "there"}
    seen: set[str] = set()
    hints: list[str] = []
    for token in tokens:
        if token in stopwords or token in seen:
            continue
        seen.add(token)
        hints.append(token)
        if len(hints) >= limit:
            break
    return hints


def _find_boundary(text: str, start: int, target: int, max_end: int, min_size: int) -> int:
    if max_end >= len(text):
        return len(text)
    min_end = min(len(text), start + min_size)
    target = min(max(target, min_end), max_end)
    candidates: list[int] = []
    for marker in ("\n\n", "\n", "。", "！", "？", ".", "!", "?", " "):
        before = text.rfind(marker, min_end, target)
        after = text.find(marker, target, max_end)
        if before > start:
            candidates.append(before + len(marker))
        if after > start:
            candidates.append(after + len(marker))
    if not candidates:
        return target
    return min(candidates, key=lambda pos: abs(pos - target))


def split_text_segments(
    text: str,
    *,
    segment_chars: int = 2200,
    overlap_chars: int = 200,
    min_segment_chars: int = 600,
) -> list[tuple[str, int, int]]:
    text_start, text_end = _trimmed_bounds(text)
    if text_end <= text_start:
        return []
    if text_end - text_start <= segment_chars:
        return [(text[text_start:text_end], text_start, text_end)]

    segments: list[tuple[str, int, int]] = []
    start = text_start
    while start < text_end:
        max_end = min(text_end, start + segment_chars)
        if text_end - start <= segment_chars:
            end = text_end
        else:
            end = _find_boundary(
                text,
                start,
                min(text_end, start + segment_chars),
                max_end,
                min(min_segment_chars, max(1, segment_chars // 3)),
            )
        segment_text = text[start:end].strip()
        if segment_text:
            window = text[start:end]
            left_trim = len(window) - len(window.lstrip())
            right_trimmed = len(window.rstrip())
            segments.append((segment_text, start + left_trim, start + right_trimmed))
        if end >= text_end:
            break
        next_start = max(0, end - overlap_chars)
        if next_start <= start:
            next_start = end
        start = next_start
    return segments


def _manifest_candidates(run_dir: Path) -> list[Path]:
    return [
        run_dir / SOURCE_MANIFEST_FILENAME,
        run_dir.parent / SOURCE_MANIFEST_FILENAME,
    ]


def _input_candidates(run_dir: Path) -> list[Path]:
    return [
        run_dir / "input" / "book.txt",
        run_dir.parent / "input" / "book.txt",
        run_dir / "input",
        run_dir.parent / "input",
    ]


def resolve_source_manifest(run_dir: str | Path) -> tuple[SourceInputManifest, str]:
    root = Path(run_dir)
    for candidate in _manifest_candidates(root):
        if candidate.exists():
            return load_source_manifest(candidate.parent), str(candidate)
    for candidate in _input_candidates(root):
        if candidate.exists():
            return build_source_manifest(candidate), str(candidate)
    raise FileNotFoundError(
        f"No {SOURCE_MANIFEST_FILENAME} or sibling input/book.txt found for {root}"
    )


def _chapter_record(
    *,
    chapter: Any,
    char_start: int,
    char_end: int,
    segment_ids: list[str],
) -> dict[str, Any]:
    source_chapter_index = chapter.original_chapter_index or chapter.chapter_index
    return {
        "source_chapter_index": source_chapter_index,
        "analysis_unit_index": chapter.chapter_index,
        "chapter_id": chapter.chapter_id,
        "source_title": chapter.original_chapter_title or chapter.normalized_title or chapter.source_title,
        "analysis_unit_title": chapter.normalized_title or chapter.source_title,
        "char_start": char_start,
        "char_end": char_end,
        "segment_ids": segment_ids,
        "part_index": chapter.part_index,
        "part_count": chapter.part_count,
    }


def build_raw_source_index(
    run_dir: str | Path,
    *,
    segment_chars: int = 2200,
    overlap_chars: int = 200,
) -> dict[str, Any]:
    root = Path(run_dir)
    manifest, source_ref = resolve_source_manifest(root)
    out_dir = ensure_dir(evidence_dir(root))
    segments_path = out_dir / RAW_SOURCE_SEGMENTS_FILENAME
    index_path = out_dir / RAW_SOURCE_INDEX_FILENAME

    segments: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    global_offset = 0
    source_hash_parts: list[str] = []

    for chapter in sorted(manifest.chapters, key=lambda item: item.chapter_index):
        chapter_text = load_chapter_text(manifest, chapter)
        chapter_start = global_offset
        chapter_segment_ids: list[str] = []
        for segment_index, (segment_text, local_start, local_end) in enumerate(
            split_text_segments(
                chapter_text,
                segment_chars=segment_chars,
                overlap_chars=overlap_chars,
            ),
            start=1,
        ):
            segment_id = f"SEG_CH{chapter.chapter_index:03d}_{segment_index:04d}"
            chapter_segment_ids.append(segment_id)
            source_chapter_index = chapter.original_chapter_index or chapter.chapter_index
            segment = {
                "segment_id": segment_id,
                "source_chapter_index": source_chapter_index,
                "analysis_unit_index": chapter.chapter_index,
                "source_title": chapter.original_chapter_title or chapter.normalized_title or chapter.source_title,
                "analysis_unit_title": chapter.normalized_title or chapter.source_title,
                "segment_index_in_chapter": segment_index,
                "char_start": chapter_start + local_start,
                "char_end": chapter_start + local_end,
                "text": segment_text,
                "normalized_text": normalize_for_search(segment_text),
                "token_hints": _token_hints(segment_text),
                "overlap_prev_chars": overlap_chars if segment_index > 1 else 0,
                "overlap_next_chars": overlap_chars,
            }
            segments.append(segment)
        chapter_end = chapter_start + len(chapter_text)
        chapters.append(
            _chapter_record(
                chapter=chapter,
                char_start=chapter_start,
                char_end=chapter_end,
                segment_ids=chapter_segment_ids,
            )
        )
        source_hash_parts.append(chapter_text)
        global_offset = chapter_end + 1

    unique_source_chapters = {
        chapter.original_chapter_index or chapter.chapter_index for chapter in manifest.chapters
    }
    source_total_text = "\n".join(source_hash_parts)
    index = {
        "schema_version": RAW_SOURCE_INDEX_VERSION,
        "work_id": manifest.source_sha256,
        "work_title": manifest.work_title,
        "source_ref": source_ref,
        "source_encoding": DEFAULT_ENCODING,
        "source_total_chars": len(source_total_text),
        "source_total_chapters": len(unique_source_chapters),
        "analysis_unit_count": len(manifest.chapters),
        "segment_count": len(segments),
        "segment_file": RAW_SOURCE_SEGMENTS_FILENAME,
        "source_sha256": sha256_text(source_total_text),
        "normalization": {
            "line_endings": "preserved_per_loader",
            "fullwidth_halfwidth": "preserved",
            "traditional_simplified": "preserved",
            "whitespace": "collapsed_for_search_only",
        },
        "chapters": chapters,
    }
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    with segments_path.open("w", encoding=DEFAULT_ENCODING) as handle:
        for segment in segments:
            handle.write(json.dumps(segment, ensure_ascii=False) + "\n")

    return {
        "status": "completed",
        "raw_source_index": str(index_path),
        "raw_source_segments": str(segments_path),
        "source_total_chapters": index["source_total_chapters"],
        "analysis_unit_count": index["analysis_unit_count"],
        "segment_count": index["segment_count"],
    }


def load_raw_source_index(run_dir: str | Path) -> dict[str, Any]:
    return json.loads(raw_source_index_path(run_dir).read_text(encoding=DEFAULT_ENCODING))


def iter_raw_source_segments(run_dir: str | Path) -> Iterator[dict[str, Any]]:
    path = raw_source_segments_path(run_dir)
    with path.open("r", encoding=DEFAULT_ENCODING) as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_raw_source_segments(
    run_dir: str | Path,
    *,
    segment_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    remaining = set(segment_ids or [])
    for segment in iter_raw_source_segments(run_dir):
        if segment_ids and segment.get("segment_id") not in segment_ids:
            continue
        matched.append(segment)
        if remaining:
            remaining.discard(str(segment.get("segment_id") or ""))
            if not remaining:
                break
    return matched
