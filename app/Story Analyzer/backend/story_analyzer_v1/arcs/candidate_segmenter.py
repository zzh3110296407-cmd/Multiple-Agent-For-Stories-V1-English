from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from ..analysis.canonical_builder import load_canonical_chapters
from ..models.arcs import ArcCandidate, ArcReview
from ..models.canonical import CanonicalChapterAnalysis
from .arc_store import (
    arc_candidates_path,
    arc_review_markdown_path,
    arc_review_path,
    write_json,
)
from .boundary_signals import active_boundary_signals, boundary_score, starts_major_arc
from .v2_hierarchy_import import build_candidates_from_imported_v2_hierarchy


_STRUCTURAL_ARC_TITLE_RE = re.compile(
    r"^(序幕|楔子|尾声|终章|第[一二三四五六七八九十百千万零〇两\d]+[幕卷部]|"
    r"prologue|epilogue|part\s+\d+|book\s+\d+)\b",
    re.IGNORECASE,
)


def _chapter_numbers(chapters: list[CanonicalChapterAnalysis], start: int, end: int) -> list[int]:
    return [chapter.chapter_index for chapter in chapters[start : end + 1]]


def _format_range(chapter_numbers: list[int]) -> str:
    if not chapter_numbers:
        return ""
    if len(chapter_numbers) == 1:
        return f"第{chapter_numbers[0]}章"
    return f"第{chapter_numbers[0]}-{chapter_numbers[-1]}章"


def _structural_title_boundary_signals(chapter: CanonicalChapterAnalysis) -> list[str]:
    if chapter.source.part_index not in (None, 1):
        return []
    title = chapter.source.original_chapter_title or chapter.source.normalized_title or chapter.source.input_title
    if _STRUCTURAL_ARC_TITLE_RE.match(str(title).strip()):
        return ["structural_title_boundary"]
    return []


def _build_segments(chapters: list[CanonicalChapterAnalysis]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    start = 0
    start_signals: list[str] = []

    for index, chapter in enumerate(chapters[1:], start=1):
        signals = active_boundary_signals(chapter.boundary_signals) or _structural_title_boundary_signals(chapter)
        if not signals:
            continue
        segments.append(
            {
                "start": start,
                "end": index - 1,
                "start_signals": start_signals,
                "next_start_signals": signals,
            }
        )
        start = index
        start_signals = signals

    segments.append(
        {
            "start": start,
            "end": len(chapters) - 1,
            "start_signals": start_signals,
            "next_start_signals": [],
        }
    )
    return segments


def _major_groups(segments: list[dict[str, Any]]) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] = []
    for index, segment in enumerate(segments):
        if index > 0 and starts_major_arc(segment["start_signals"]):
            groups.append(current)
            current = []
        current.append(index)
    if current:
        groups.append(current)
    return groups


def _build_sub_candidates(
    chapters: list[CanonicalChapterAnalysis],
    segments: list[dict[str, Any]],
    parent_by_segment: dict[int, str],
) -> list[ArcCandidate]:
    candidates: list[ArcCandidate] = []
    for index, segment in enumerate(segments, start=1):
        chapter_numbers = _chapter_numbers(chapters, segment["start"], segment["end"])
        start_signals = segment["start_signals"]
        next_signals = segment["next_start_signals"]
        start_reason = "从首章开始" if index == 1 else f"{_format_range([chapter_numbers[0]])}出现边界信号: {', '.join(start_signals)}"
        end_reason = "到最后一章结束" if not next_signals else f"下一章出现边界信号: {', '.join(next_signals)}"
        candidates.append(
            ArcCandidate(
                arc_candidate_id=f"sub_arc_candidate_{index:03d}",
                arc_level="sub_arc",
                parent_candidate_id=parent_by_segment[index - 1],
                chapters_included=chapter_numbers,
                stage_goal=f"待分析：{_format_range(chapter_numbers)}阶段目标",
                stage_question=f"待分析：{_format_range(chapter_numbers)}阶段问题",
                dominant_conflict=f"待分析：{_format_range(chapter_numbers)}主导冲突",
                dominant_reader_experience=f"待分析：{_format_range(chapter_numbers)}读者体验",
                why_boundary_starts_here=start_reason,
                why_boundary_ends_here=end_reason,
                boundary_score=boundary_score(start_signals),
                boundary_signals=start_signals,
                confidence_score=0.45 + min(boundary_score(start_signals), 0.45),
            )
        )
    return candidates


def _build_major_candidates(
    chapters: list[CanonicalChapterAnalysis],
    segments: list[dict[str, Any]],
    groups: list[list[int]],
) -> tuple[list[ArcCandidate], dict[int, str]]:
    candidates: list[ArcCandidate] = []
    parent_by_segment: dict[int, str] = {}

    for group_index, segment_indexes in enumerate(groups, start=1):
        first_segment = segments[segment_indexes[0]]
        last_segment = segments[segment_indexes[-1]]
        chapter_numbers = _chapter_numbers(chapters, first_segment["start"], last_segment["end"])
        start_signals = first_segment["start_signals"] if group_index > 1 else []
        candidate_id = f"major_arc_candidate_{group_index:03d}"
        for segment_index in segment_indexes:
            parent_by_segment[segment_index] = candidate_id
        candidates.append(
            ArcCandidate(
                arc_candidate_id=candidate_id,
                arc_level="major_arc",
                parent_candidate_id=None,
                chapters_included=chapter_numbers,
                stage_goal=f"待分析：{_format_range(chapter_numbers)}主弧目标",
                stage_question=f"待分析：{_format_range(chapter_numbers)}主弧问题",
                dominant_conflict=f"待分析：{_format_range(chapter_numbers)}主弧冲突",
                dominant_reader_experience=f"待分析：{_format_range(chapter_numbers)}主弧读者体验",
                why_boundary_starts_here="从首个主弧开始" if group_index == 1 else f"{_format_range([chapter_numbers[0]])}出现强边界信号: {', '.join(start_signals)}",
                why_boundary_ends_here="覆盖到最后一个确认候选子弧",
                boundary_score=boundary_score(start_signals),
                boundary_signals=start_signals,
                confidence_score=0.45 + min(boundary_score(start_signals), 0.45),
            )
        )
    return candidates, parent_by_segment


def _write_review_markdown(run_dir: str | Path, proposal: dict[str, Any]) -> Path:
    lines = [
        "# Arc Boundary Review",
        "",
        f"status: {proposal['status']}",
        f"candidate_version: {proposal['candidate_version']}",
        "",
        "## Major Arcs",
        "",
    ]
    for arc in proposal["major_arcs"]:
        lines.append(f"- {arc['arc_candidate_id']}: {arc['chapters_included']}")
    lines.extend(["", "## Sub Arcs", ""])
    for arc in proposal["sub_arcs"]:
        lines.append(
            f"- {arc['arc_candidate_id']} -> {arc['parent_candidate_id']}: {arc['chapters_included']} signals={arc['boundary_signals']}"
        )
    lines.extend(
        [
            "",
            "## Confirm",
            "",
            "Edit arcs/arc_candidates.json if needed, then run:",
            "",
            "```powershell",
            "python -m story_analyzer_v1 confirm-arcs <run_dir> --review-file arcs/arc_review.json",
            "```",
            "",
        ]
    )
    path = arc_review_markdown_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def propose_arc_candidates(run_dir: str | Path) -> dict[str, Any]:
    chapters = sorted(load_canonical_chapters(run_dir), key=lambda chapter: chapter.chapter_index)
    imported = build_candidates_from_imported_v2_hierarchy(run_dir, chapters)
    if imported is not None:
        major_candidates, sub_candidates = imported
        candidate_source = "v2_generation_profiles.arc_hierarchy"
    else:
        segments = _build_segments(chapters)
        groups = _major_groups(segments)
        major_candidates, parent_by_segment = _build_major_candidates(chapters, segments, groups)
        sub_candidates = _build_sub_candidates(chapters, segments, parent_by_segment)
        candidate_source = "boundary_signals"

    proposal = {
        "schema_version": "story_analyzer.arc_candidates.v1",
        "status": "pending_user_review",
        "candidate_version": 1,
        "candidate_source": candidate_source,
        "source_chapter_count": len(chapters),
        "major_arcs": [candidate.model_dump(mode="json") for candidate in major_candidates],
        "sub_arcs": [candidate.model_dump(mode="json") for candidate in sub_candidates],
    }
    write_json(arc_candidates_path(run_dir), proposal)
    write_json(arc_review_path(run_dir), ArcReview().model_dump(mode="json"))
    _write_review_markdown(run_dir, proposal)
    return proposal
