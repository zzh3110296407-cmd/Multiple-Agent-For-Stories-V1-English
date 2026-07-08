from __future__ import annotations

from dataclasses import dataclass

from .title_detector import TitleCandidate, score_title_candidate


@dataclass(frozen=True)
class ChapterSlice:
    source_title: str
    normalized_title: str
    title_source: str
    boundary_status: str
    title_status: str
    boundary_reason: list[str]
    text: str
    start_line: int | None
    end_line: int | None


def _is_blank(line: str) -> bool:
    return not line.strip()


def find_title_candidates(text: str) -> list[TitleCandidate]:
    lines = text.splitlines()
    candidates: list[TitleCandidate] = []
    for index, line in enumerate(lines):
        previous_blank = index == 0 or _is_blank(lines[index - 1])
        next_blank = index == len(lines) - 1 or _is_blank(lines[index + 1])
        candidate = score_title_candidate(
            line,
            line_number=index + 1,
            previous_blank=previous_blank,
            next_blank=next_blank,
        )
        if candidate.accepted or candidate.suspicious:
            candidates.append(candidate)
    return candidates


def split_text_into_chapters(text: str) -> list[ChapterSlice]:
    lines = text.splitlines()
    accepted = [candidate for candidate in find_title_candidates(text) if candidate.accepted]

    if not accepted:
        stripped = text.strip()
        return [
            ChapterSlice(
                source_title="",
                normalized_title="第1章",
                title_source="fallback",
                boundary_status="ok",
                title_status="inferred_title",
                boundary_reason=["no_accepted_heading_found"],
                text=stripped,
                start_line=1 if stripped else None,
                end_line=len(lines) if stripped else None,
            )
        ]

    chapters: list[ChapterSlice] = []
    for position, candidate in enumerate(accepted):
        start_index = candidate.line_number - 1
        end_index = accepted[position + 1].line_number - 1 if position + 1 < len(accepted) else len(lines)
        chapter_text = "\n".join(lines[start_index:end_index]).strip()
        if not chapter_text:
            continue
        chapters.append(
            ChapterSlice(
                source_title=candidate.normalized_title,
                normalized_title=candidate.normalized_title,
                title_source="source",
                boundary_status="ok",
                title_status="source_title",
                boundary_reason=candidate.reasons,
                text=chapter_text,
                start_line=candidate.line_number,
                end_line=end_index,
            )
        )
    return chapters
