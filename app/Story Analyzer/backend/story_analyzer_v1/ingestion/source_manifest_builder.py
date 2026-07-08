from __future__ import annotations

from pathlib import Path
import json

from story_analyzer_utils import chapter_sort_key

from ..config import DEFAULT_ENCODING, SOURCE_MANIFEST_FILENAME, ensure_dir
from ..models.common import sha256_file, sha256_text
from ..models.source import ChapterSource, SourceInputManifest
from .chapter_boundary_detector import ChapterSlice, split_text_into_chapters

MAX_ANALYSIS_UNIT_CHARS = 25_000


def _chapter_id(index: int) -> str:
    return f"chapter_{index:03d}"


def _part_chapter_id(original_index: int, part_index: int) -> str:
    return f"{_chapter_id(original_index)}_part_{part_index:02d}"


def _trimmed_span(text: str, start: int, end: int) -> tuple[str, int, int]:
    raw = text[start:end]
    left_trimmed = len(raw) - len(raw.lstrip())
    right_trimmed = len(raw.rstrip())
    trimmed = raw.strip()
    return trimmed, start + left_trimmed, start + right_trimmed


def split_text_part_spans(text: str, max_chars: int = MAX_ANALYSIS_UNIT_CHARS) -> list[tuple[str, int, int]]:
    if len(text) <= max_chars:
        return [(text.strip(), 0, len(text.strip()))]

    part_count = (len(text) + max_chars - 1) // max_chars
    target_size = (len(text) + part_count - 1) // part_count
    min_part_chars = max(1, min(max_chars // 2, target_size // 2))
    spans: list[tuple[str, int, int]] = []
    start = 0
    length = len(text)
    while start < length and len(spans) < part_count:
        remaining_parts = part_count - len(spans)
        if remaining_parts == 1:
            limit = length
        else:
            remaining_after = remaining_parts - 1
            min_limit = min(length, start + min_part_chars)
            max_limit = min(start + max_chars, length - remaining_after * min_part_chars)
            if max_limit <= min_limit:
                max_limit = min(start + max_chars, length)
            target = min(max(start + target_size, min_limit), max_limit)
            candidates: list[int] = []
            for marker in ("\n\n", "\n", " ", "\t"):
                before = text.rfind(marker, min_limit, target)
                after = text.find(marker, target, max_limit)
                if before > start:
                    candidates.append(before)
                if after > start:
                    candidates.append(after)
            limit = min(candidates, key=lambda pos: abs(pos - target)) if candidates else target
        part_text, part_start, part_end = _trimmed_span(text, start, limit)
        if part_text:
            spans.append((part_text, part_start, part_end))
        start = max(limit, start + 1)
    return spans


def _split_part_spans(text: str, max_chars: int = MAX_ANALYSIS_UNIT_CHARS) -> list[tuple[str, int, int]]:
    return split_text_part_spans(text, max_chars=max_chars)


def _chapter_from_slice(
    index: int,
    chapter: ChapterSlice,
    source_file_path: Path,
    *,
    chapter_id: str | None = None,
) -> ChapterSource:
    return ChapterSource(
        chapter_id=chapter_id or _chapter_id(index),
        chapter_index=index,
        source_title=chapter.source_title,
        normalized_title=chapter.normalized_title,
        title_source=chapter.title_source,  # type: ignore[arg-type]
        boundary_status=chapter.boundary_status,  # type: ignore[arg-type]
        title_status=chapter.title_status,  # type: ignore[arg-type]
        boundary_reason=chapter.boundary_reason,
        text_sha256=sha256_text(chapter.text),
        text_length=len(chapter.text),
        source_file_path=str(source_file_path),
        start_line=chapter.start_line,
        end_line=chapter.end_line,
    )


def _chapter_sources_from_slice(
    *,
    original_index: int,
    next_index: int,
    chapter: ChapterSlice,
    source_file_path: Path,
) -> tuple[list[ChapterSource], int]:
    spans = _split_part_spans(chapter.text)
    if len(spans) == 1:
        return [
            _chapter_from_slice(
                next_index,
                chapter,
                source_file_path,
                chapter_id=_chapter_id(original_index),
            )
        ], next_index + 1

    original_id = _chapter_id(original_index)
    sources: list[ChapterSource] = []
    for part_index, (part_text, part_start, part_end) in enumerate(spans, start=1):
        title = f"{chapter.normalized_title} part {part_index:02d}"
        sources.append(
            ChapterSource(
                chapter_id=_part_chapter_id(original_index, part_index),
                chapter_index=next_index,
                source_title=title,
                normalized_title=title,
                title_source=chapter.title_source,  # type: ignore[arg-type]
                boundary_status=chapter.boundary_status,  # type: ignore[arg-type]
                title_status=chapter.title_status,  # type: ignore[arg-type]
                boundary_reason=[*chapter.boundary_reason, "auto_split_long_chapter"],
                text_sha256=sha256_text(part_text),
                text_length=len(part_text),
                source_file_path=str(source_file_path),
                start_line=chapter.start_line,
                end_line=chapter.end_line,
                original_chapter_id=original_id,
                original_chapter_index=original_index,
                original_chapter_title=chapter.normalized_title or chapter.source_title,
                part_index=part_index,
                part_count=len(spans),
                part_start_char=part_start,
                part_end_char=part_end,
            )
        )
        next_index += 1
    return sources, next_index


def _manifest_from_file(path: Path, work_title: str | None = None) -> SourceInputManifest:
    text = path.read_text(encoding=DEFAULT_ENCODING)
    chapters: list[ChapterSource] = []
    next_index = 1
    for original_index, chapter in enumerate(split_text_into_chapters(text), start=1):
        chapter_sources, next_index = _chapter_sources_from_slice(
            original_index=original_index,
            next_index=next_index,
            chapter=chapter,
            source_file_path=path,
        )
        chapters.extend(chapter_sources)
    return SourceInputManifest(
        work_title=work_title or path.stem,
        source_path=str(path),
        source_sha256=sha256_file(path),
        chapters=chapters,
    )


def _manifest_from_directory(path: Path, work_title: str | None = None) -> SourceInputManifest:
    files = sorted(
        [item for item in path.iterdir() if item.is_file() and item.suffix.lower() in {".txt", ".md"}],
        key=chapter_sort_key,
    )
    if not files:
        raise ValueError(f"No .txt or .md files found in {path}")

    chapters: list[ChapterSource] = []
    source_hash_parts: list[str] = []
    next_index = 1
    for original_index, file_path in enumerate(files, start=1):
        text = file_path.read_text(encoding=DEFAULT_ENCODING).strip()
        title = file_path.stem
        source_hash_parts.append(sha256_file(file_path))
        chapter = ChapterSlice(
            source_title=title,
            normalized_title=title,
            title_source="filename",
            boundary_status="ok",
            title_status="source_title",
            boundary_reason=["directory_file_boundary"],
            text=text,
            start_line=1 if text else None,
            end_line=len(text.splitlines()) if text else None,
        )
        chapter_sources, next_index = _chapter_sources_from_slice(
            original_index=original_index,
            next_index=next_index,
            chapter=chapter,
            source_file_path=file_path,
        )
        chapters.extend(chapter_sources)

    return SourceInputManifest(
        work_title=work_title or path.name,
        source_path=str(path),
        source_sha256=sha256_text("\n".join(source_hash_parts)),
        chapters=chapters,
    )


def build_source_manifest(input_path: str | Path, work_title: str | None = None) -> SourceInputManifest:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_dir():
        return _manifest_from_directory(path, work_title)
    return _manifest_from_file(path, work_title)


def write_source_manifest(
    manifest: SourceInputManifest,
    output_dir: str | Path,
    *,
    filename: str = SOURCE_MANIFEST_FILENAME,
) -> Path:
    out_dir = ensure_dir(Path(output_dir))
    out_path = out_dir / filename
    out_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding=DEFAULT_ENCODING,
    )
    return out_path


def load_source_manifest(run_dir: str | Path) -> SourceInputManifest:
    manifest_path = Path(run_dir) / SOURCE_MANIFEST_FILENAME
    data = json.loads(manifest_path.read_text(encoding=DEFAULT_ENCODING))
    return SourceInputManifest.model_validate(data)
