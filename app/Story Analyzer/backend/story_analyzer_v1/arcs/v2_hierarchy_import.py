from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from ..models.arcs import ArcCandidate
from ..models.canonical import CanonicalChapterAnalysis
from .arc_store import arcs_dir, read_json, write_json


IMPORTED_V2_ARC_HIERARCHY_FILENAME = "imported_v2_arc_hierarchy.json"
IMPORTED_V2_ARC_HIERARCHY_SOURCE = "v2_generation_profiles.arc_hierarchy"


def imported_v2_arc_hierarchy_path(run_dir: str | Path) -> Path:
    return arcs_dir(run_dir) / IMPORTED_V2_ARC_HIERARCHY_FILENAME


def _load_generation_profiles(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    path = Path(source)
    if not path.exists():
        return {}
    return read_json(path)


def import_v2_arc_hierarchy(run_dir: str | Path, generation_profiles: str | Path | dict[str, Any]) -> dict[str, Any]:
    profiles = _load_generation_profiles(generation_profiles)
    hierarchy = profiles.get("arc_hierarchy") if isinstance(profiles, dict) else None
    if not isinstance(hierarchy, dict):
        return {"status": "missing", "reason": "arc_hierarchy_not_found"}

    major_arcs = hierarchy.get("major_arcs") or []
    sub_arcs = hierarchy.get("sub_arcs") or []
    if not major_arcs or not sub_arcs:
        return {"status": "missing", "reason": "arc_hierarchy_empty"}

    payload = {
        "schema_version": "story_analyzer.imported_v2_arc_hierarchy.v1",
        "source": IMPORTED_V2_ARC_HIERARCHY_SOURCE,
        "source_schema_version": hierarchy.get("schema_version", ""),
        "major_arcs": major_arcs,
        "sub_arcs": sub_arcs,
    }
    write_json(imported_v2_arc_hierarchy_path(run_dir), payload)
    return {
        "status": "imported",
        "source": IMPORTED_V2_ARC_HIERARCHY_SOURCE,
        "major_arc_count": len(major_arcs),
        "sub_arc_count": len(sub_arcs),
        "output_ref": f"arcs/{IMPORTED_V2_ARC_HIERARCHY_FILENAME}",
    }


def _range_numbers(value: Any) -> list[int]:
    numbers = [int(match) for match in re.findall(r"\d+", str(value or ""))]
    if not numbers:
        return []
    if len(numbers) == 1:
        return [numbers[0]]
    start, end = numbers[0], numbers[1]
    if start > end:
        start, end = end, start
    return list(range(start, end + 1))


def _effective_source_indexes(chapters: list[CanonicalChapterAnalysis]) -> dict[int, int]:
    by_chapter: dict[int, int] = {}
    current_source_index = 0
    active_original_index: int | None = None
    active_part_count: int | None = None
    for chapter in sorted(chapters, key=lambda item: item.chapter_index):
        original_index = chapter.source.original_chapter_index
        if original_index:
            source_index = int(original_index)
            current_source_index = max(current_source_index, source_index)
            active_original_index = source_index
            active_part_count = chapter.source.part_count
        elif (
            chapter.source.part_index
            and chapter.source.part_index > 1
            and active_original_index is not None
            and active_part_count
            and chapter.source.part_index <= active_part_count
        ):
            source_index = active_original_index
        else:
            current_source_index += 1
            source_index = current_source_index
            active_original_index = source_index if chapter.source.part_count else None
            active_part_count = chapter.source.part_count
        by_chapter[chapter.chapter_index] = source_index
    return by_chapter


def _chapter_numbers_for_arc(chapters: list[CanonicalChapterAnalysis], arc: dict[str, Any]) -> list[int]:
    source_numbers = set(_range_numbers(arc.get("source_chapter_range")))
    if source_numbers:
        effective_source_indexes = _effective_source_indexes(chapters)
        matched = [
            chapter.chapter_index
            for chapter in chapters
            if effective_source_indexes.get(chapter.chapter_index) in source_numbers
        ]
        if matched:
            return sorted(matched)

    analysis_numbers = set(_range_numbers(arc.get("analysis_unit_range")))
    if analysis_numbers:
        existing = {chapter.chapter_index for chapter in chapters}
        matched = sorted(number for number in analysis_numbers if number in existing)
        if matched:
            return matched
    return []


def _candidate_id(level: str, index: int) -> str:
    return f"{level}_candidate_{index:03d}"


def _candidate_from_imported_arc(
    arc: dict[str, Any],
    *,
    arc_level: str,
    candidate_id: str,
    parent_candidate_id: str | None,
    chapters_included: list[int],
) -> ArcCandidate:
    title = str(
        arc.get("major_arc_title")
        or arc.get("arc_title")
        or arc.get("sub_arc_title")
        or candidate_id
    )
    return ArcCandidate(
        arc_candidate_id=candidate_id,
        arc_level=arc_level,  # type: ignore[arg-type]
        parent_candidate_id=parent_candidate_id,
        chapters_included=chapters_included,
        stage_goal=title,
        stage_question="Imported from v2 generation_profiles.arc_hierarchy",
        dominant_conflict=str(arc.get("turning_point") or arc.get("dominant_stage") or ""),
        dominant_reader_experience=str(arc.get("pacing_summary") or arc.get("pacing") or ""),
        turning_points=[
            {
                "description": str(point.get("turning_point") or point)
            }
            for point in (arc.get("turning_points") or [])
        ],
        why_boundary_starts_here="Imported from v2 generation_profiles.arc_hierarchy",
        why_boundary_ends_here="Imported from v2 generation_profiles.arc_hierarchy",
        boundary_score=0.85,
        boundary_signals=["imported_v2_arc_hierarchy"],
        confidence_score=0.9,
    )


def build_candidates_from_imported_v2_hierarchy(
    run_dir: str | Path,
    chapters: list[CanonicalChapterAnalysis],
) -> tuple[list[ArcCandidate], list[ArcCandidate]] | None:
    path = imported_v2_arc_hierarchy_path(run_dir)
    if not path.exists():
        return None
    payload = read_json(path)
    if payload.get("schema_version") != "story_analyzer.imported_v2_arc_hierarchy.v1":
        return None

    major_id_map: dict[str, str] = {}
    major_candidates: list[ArcCandidate] = []
    for index, arc in enumerate(payload.get("major_arcs", []) or [], start=1):
        chapters_included = _chapter_numbers_for_arc(chapters, arc)
        if not chapters_included:
            return None
        candidate_id = _candidate_id("major_arc", index)
        major_id_map[str(arc.get("major_arc_id") or candidate_id)] = candidate_id
        major_candidates.append(
            _candidate_from_imported_arc(
                arc,
                arc_level="major_arc",
                candidate_id=candidate_id,
                parent_candidate_id=None,
                chapters_included=chapters_included,
            )
        )

    sub_candidates: list[ArcCandidate] = []
    assigned: list[int] = []
    for index, arc in enumerate(payload.get("sub_arcs", []) or [], start=1):
        chapters_included = _chapter_numbers_for_arc(chapters, arc)
        if not chapters_included:
            return None
        parent_id = major_id_map.get(str(arc.get("major_arc_id") or ""))
        if not parent_id:
            return None
        assigned.extend(chapters_included)
        sub_candidates.append(
            _candidate_from_imported_arc(
                arc,
                arc_level="sub_arc",
                candidate_id=_candidate_id("sub_arc", index),
                parent_candidate_id=parent_id,
                chapters_included=chapters_included,
            )
        )

    expected = [chapter.chapter_index for chapter in chapters]
    if sorted(assigned) != expected or len(assigned) != len(set(assigned)):
        return None

    return major_candidates, sub_candidates
