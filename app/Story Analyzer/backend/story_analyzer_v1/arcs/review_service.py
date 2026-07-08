from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..analysis.canonical_builder import load_canonical_chapters
from ..models.arcs import ArcCandidate, ArcReview
from .arc_store import (
    arc_candidates_path,
    arc_review_path,
    major_arcs_path,
    read_json,
    resolve_review_file,
    sub_arcs_path,
    write_json,
)


def _load_candidates(run_dir: str | Path) -> tuple[dict[str, Any], list[ArcCandidate], list[ArcCandidate]]:
    payload = read_json(arc_candidates_path(run_dir))
    if payload.get("schema_version") != "story_analyzer.arc_candidates.v1":
        raise ValueError("Invalid arc_candidates schema_version")

    major_arcs = [ArcCandidate.model_validate(item) for item in payload.get("major_arcs", [])]
    sub_arcs = [ArcCandidate.model_validate(item) for item in payload.get("sub_arcs", [])]
    if not major_arcs:
        raise ValueError("arc_candidates must include at least one major_arc")
    if not sub_arcs:
        raise ValueError("arc_candidates must include at least one sub_arc")
    return payload, major_arcs, sub_arcs


def _ensure_unique_ids(arcs: list[ArcCandidate]) -> None:
    ids = [arc.arc_candidate_id for arc in arcs]
    if len(ids) != len(set(ids)):
        raise ValueError("arc candidate ids must be unique")


def _ensure_contiguous(chapters: list[int], arc_id: str) -> None:
    if not chapters:
        raise ValueError(f"{arc_id} has no chapters")
    expected = list(range(chapters[0], chapters[-1] + 1))
    if chapters != expected:
        raise ValueError(f"{arc_id} chapters_included must be sorted and contiguous")


def _expected_chapter_indexes(run_dir: str | Path) -> list[int]:
    try:
        canonical_chapters = sorted(load_canonical_chapters(run_dir), key=lambda chapter: chapter.chapter_index)
        expected = [chapter.chapter_index for chapter in canonical_chapters]
        if expected:
            return expected
    except Exception:
        pass

    run_path = Path(run_dir)
    for filename in ("source_input_manifest.json", "run_manifest.json"):
        path = run_path / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        chapters = payload.get("chapters", [])
        if not isinstance(chapters, list):
            continue
        expected = []
        for index, chapter in enumerate(chapters, start=1):
            if not isinstance(chapter, dict):
                continue
            expected.append(int(chapter.get("chapter_index") or index))
        if expected:
            return sorted(expected)
    return []


def _validate_arc_structure(
    run_dir: str | Path,
    major_arcs: list[ArcCandidate],
    sub_arcs: list[ArcCandidate],
) -> None:
    expected_chapters = _expected_chapter_indexes(run_dir)
    if not expected_chapters:
        raise ValueError("Cannot validate arc candidates without chapter metadata")
    major_by_id = {arc.arc_candidate_id: arc for arc in major_arcs}

    _ensure_unique_ids([*major_arcs, *sub_arcs])
    for arc in [*major_arcs, *sub_arcs]:
        _ensure_contiguous(arc.chapters_included, arc.arc_candidate_id)

    assigned_chapters: list[int] = []
    children_by_major: dict[str, list[ArcCandidate]] = {arc_id: [] for arc_id in major_by_id}
    for sub_arc in sub_arcs:
        if sub_arc.arc_level != "sub_arc":
            raise ValueError(f"{sub_arc.arc_candidate_id} must use arc_level=sub_arc")
        if sub_arc.parent_candidate_id not in major_by_id:
            raise ValueError(f"{sub_arc.arc_candidate_id} has invalid parent_candidate_id")
        assigned_chapters.extend(sub_arc.chapters_included)
        children_by_major[sub_arc.parent_candidate_id].append(sub_arc)

    if sorted(assigned_chapters) != expected_chapters:
        raise ValueError("Every canonical chapter must belong to exactly one sub_arc")
    if len(assigned_chapters) != len(set(assigned_chapters)):
        raise ValueError("A canonical chapter cannot belong to more than one sub_arc")

    for major_arc in major_arcs:
        if major_arc.arc_level != "major_arc":
            raise ValueError(f"{major_arc.arc_candidate_id} must use arc_level=major_arc")
        children = children_by_major.get(major_arc.arc_candidate_id, [])
        if not children:
            raise ValueError(f"{major_arc.arc_candidate_id} has no sub_arc children")
        child_chapters = sorted({chapter for child in children for chapter in child.chapters_included})
        if child_chapters != major_arc.chapters_included:
            raise ValueError(f"{major_arc.arc_candidate_id} chapters must equal its sub_arc children")


def validate_arc_candidates(
    run_dir: str | Path,
    major_arcs: list[ArcCandidate],
    sub_arcs: list[ArcCandidate],
) -> None:
    _validate_arc_structure(run_dir, major_arcs, sub_arcs)


def _confirmed_candidates(arcs: list[ArcCandidate]) -> list[dict[str, Any]]:
    return [
        arc.model_copy(update={"review_status": "user_confirmed"}).model_dump(mode="json")
        for arc in arcs
    ]


def confirm_arc_candidates(
    run_dir: str | Path,
    review_file: str | Path | None = None,
) -> dict[str, Any]:
    try:
        review_payload = read_json(resolve_review_file(run_dir, review_file))
        review = ArcReview.model_validate(review_payload)
    except FileNotFoundError:
        review = ArcReview()
    except ValidationError as exc:
        raise ValueError(f"Invalid arc review file: {exc}") from exc

    candidate_payload, major_arcs, sub_arcs = _load_candidates(run_dir)
    _validate_arc_structure(run_dir, major_arcs, sub_arcs)

    candidate_version = int(candidate_payload.get("candidate_version", review.candidate_version))
    confirmed_major_arcs = _confirmed_candidates(major_arcs)
    confirmed_sub_arcs = _confirmed_candidates(sub_arcs)

    write_json(
        major_arcs_path(run_dir),
        {
            "schema_version": "story_analyzer.major_arcs.v1",
            "status": "user_confirmed",
            "source_candidate_version": candidate_version,
            "arcs": confirmed_major_arcs,
        },
    )
    write_json(
        sub_arcs_path(run_dir),
        {
            "schema_version": "story_analyzer.sub_arcs.v1",
            "status": "user_confirmed",
            "source_candidate_version": candidate_version,
            "arcs": confirmed_sub_arcs,
        },
    )

    confirmed_review = review.model_copy(
        update={
            "status": "user_confirmed",
            "candidate_version": candidate_version,
            "confirmed_version": candidate_version,
        }
    )
    review_data = confirmed_review.model_dump(mode="json")
    write_json(arc_review_path(run_dir), review_data)
    return review_data
