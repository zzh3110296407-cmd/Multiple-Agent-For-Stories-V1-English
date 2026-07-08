from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import re

from pydantic import ValidationError

from .arcs.arc_store import arc_candidates_path, arc_review_path, read_json, write_json
from .arcs.review_service import confirm_arc_candidates, validate_arc_candidates
from .config import SOURCE_MANIFEST_FILENAME
from .ingestion.source_manifest_builder import load_source_manifest
from .models.arcs import ArcCandidate, ArcReview, ArcUserEdit
from .state.pipeline_state import invalidate_for_change, record_pipeline_step


ARC_REVIEW_EDITOR_SCHEMA_VERSION = "story_analyzer.arc_review_editor.v1"
ArcEditOperation = Literal["split", "merge", "move_boundary", "rename", "change_parent"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


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


def _chapter_numbers_for_v2_arc(chapters: list[dict[str, Any]], arc: dict[str, Any]) -> list[int]:
    source_numbers = set(_range_numbers(arc.get("source_chapter_range")))
    if source_numbers:
        matched = [
            int(chapter["chapter_index"])
            for chapter in chapters
            if int(chapter.get("original_chapter_index") or chapter["chapter_index"]) in source_numbers
        ]
        if matched:
            return sorted(matched)

    analysis_numbers = set(_range_numbers(arc.get("analysis_unit_range")))
    if analysis_numbers:
        existing = {int(chapter["chapter_index"]) for chapter in chapters}
        matched = sorted(number for number in analysis_numbers if number in existing)
        if matched:
            return matched
    return []


def _candidate_from_v2_arc(
    arc: dict[str, Any],
    *,
    arc_level: str,
    candidate_id: str,
    parent_candidate_id: str | None,
    chapters_included: list[int],
) -> dict[str, Any]:
    title = str(
        arc.get("major_arc_title")
        or arc.get("arc_title")
        or arc.get("sub_arc_title")
        or arc.get("title")
        or candidate_id
    )
    return _normalise_candidate(
        {
            "arc_candidate_id": candidate_id,
            "parent_candidate_id": parent_candidate_id,
            "chapters_included": chapters_included,
            "stage_goal": title,
            "stage_question": "Imported from v2 generation_profiles.arc_hierarchy",
            "dominant_conflict": str(arc.get("turning_point") or arc.get("dominant_stage") or ""),
            "dominant_reader_experience": str(arc.get("pacing_summary") or arc.get("pacing") or ""),
            "turning_points": [
                {"description": str(point.get("turning_point") or point)}
                for point in (arc.get("turning_points") or [])
            ],
            "why_boundary_starts_here": "Imported from v2 generation_profiles.arc_hierarchy",
            "why_boundary_ends_here": "Imported from v2 generation_profiles.arc_hierarchy",
            "boundary_score": 0.85,
            "boundary_signals": ["imported_v2_arc_hierarchy"],
            "confidence_score": 0.9,
        },
        arc_level,
    ).model_dump(mode="json")


def _bootstrap_v2_arc_candidates(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir)
    profiles = _read_json_or_empty(run_path / "generation_profiles.json")
    hierarchy = profiles.get("arc_hierarchy") if isinstance(profiles, dict) else None
    if not isinstance(hierarchy, dict):
        return {}
    major_arcs = hierarchy.get("major_arcs") or []
    sub_arcs = hierarchy.get("sub_arcs") or []
    if not major_arcs or not sub_arcs:
        return {}

    chapters = _chapters_for_editor(run_path)
    if not chapters:
        return {}

    major_id_map: dict[str, str] = {}
    major_candidates: list[dict[str, Any]] = []
    for index, arc in enumerate(major_arcs, start=1):
        chapters_included = _chapter_numbers_for_v2_arc(chapters, arc)
        if not chapters_included:
            return {}
        candidate_id = f"major_arc_candidate_{index:03d}"
        major_id_map[str(arc.get("major_arc_id") or candidate_id)] = candidate_id
        major_candidates.append(
            _candidate_from_v2_arc(
                arc,
                arc_level="major_arc",
                candidate_id=candidate_id,
                parent_candidate_id=None,
                chapters_included=chapters_included,
            )
        )

    sub_candidates: list[dict[str, Any]] = []
    for index, arc in enumerate(sub_arcs, start=1):
        chapters_included = _chapter_numbers_for_v2_arc(chapters, arc)
        if not chapters_included:
            return {}
        parent_id = major_id_map.get(str(arc.get("major_arc_id") or ""))
        if not parent_id:
            return {}
        sub_candidates.append(
            _candidate_from_v2_arc(
                arc,
                arc_level="sub_arc",
                candidate_id=f"sub_arc_candidate_{index:03d}",
                parent_candidate_id=parent_id,
                chapters_included=chapters_included,
            )
        )

    payload = {
        "schema_version": "story_analyzer.arc_candidates.v1",
        "status": "pending_user_review",
        "candidate_version": 1,
        "candidate_source": "v2_generation_profiles.arc_hierarchy",
        "source_chapter_count": len(chapters),
        "major_arcs": major_candidates,
        "sub_arcs": sub_candidates,
    }
    write_json(arc_candidates_path(run_path), payload)
    write_json(arc_review_path(run_path), ArcReview().model_dump(mode="json"))
    return payload


def _load_candidates_payload(run_dir: str | Path) -> dict[str, Any]:
    candidates_path = arc_candidates_path(run_dir)
    if not candidates_path.exists():
        payload = _bootstrap_v2_arc_candidates(run_dir)
    else:
        payload = read_json(candidates_path)
    if payload.get("schema_version") != "story_analyzer.arc_candidates.v1":
        raise ValueError("Invalid arc_candidates schema_version")
    return payload


def _load_review(run_dir: str | Path) -> ArcReview:
    path = arc_review_path(run_dir)
    if not path.exists():
        return ArcReview()
    try:
        return ArcReview.model_validate(read_json(path))
    except ValidationError as exc:
        raise ValueError(f"Invalid arc review file: {exc}") from exc


def _chapters_for_editor(run_dir: str | Path) -> list[dict[str, Any]]:
    try:
        manifest = load_source_manifest(run_dir)
        return [
            {
                "chapter_id": chapter.chapter_id,
                "chapter_index": chapter.chapter_index,
                "title": chapter.normalized_title or chapter.source_title,
                "source_title": chapter.source_title,
            }
            for chapter in sorted(manifest.chapters, key=lambda item: item.chapter_index)
        ]
    except Exception:
        source = _read_json_or_empty(Path(run_dir) / SOURCE_MANIFEST_FILENAME)
        chapters = source.get("chapters", [])
        if isinstance(chapters, list) and chapters:
            result: list[dict[str, Any]] = []
            for index, chapter in enumerate(chapters, start=1):
                if not isinstance(chapter, dict):
                    continue
                chapter_index = int(chapter.get("chapter_index") or index)
                result.append(
                    {
                        "chapter_id": chapter.get("chapter_id") or f"chapter_{chapter_index:03d}",
                        "chapter_index": chapter_index,
                        "title": chapter.get("normalized_title") or chapter.get("source_title") or f"Chapter {chapter_index}",
                        "source_title": chapter.get("source_title", ""),
                    }
                )
            if result:
                return sorted(result, key=lambda item: item["chapter_index"])

    manifest = _read_json_or_empty(Path(run_dir) / "run_manifest.json")
    chapters = manifest.get("chapters", [])
    if not isinstance(chapters, list):
        return []
    result: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters, start=1):
        if not isinstance(chapter, dict):
            continue
        chapter_index = int(chapter.get("chapter_index") or index)
        result.append(
            {
                "chapter_id": chapter.get("chapter_id") or f"chapter_{chapter_index:03d}",
                "chapter_index": chapter_index,
                "title": chapter.get("input_title") or chapter.get("title") or f"Chapter {chapter_index}",
                "source_title": chapter.get("original_title") or chapter.get("input_title") or "",
                "original_chapter_index": chapter.get("original_chapter_index"),
                "part_index": chapter.get("part_index"),
                "part_count": chapter.get("part_count"),
            }
        )
    return sorted(result, key=lambda item: item["chapter_index"])


def _parse_chapters(value: Any) -> list[int]:
    if isinstance(value, list):
        return sorted({int(item) for item in value})
    if isinstance(value, str):
        chapters: set[int] = set()
        for raw_part in value.replace("，", ",").split(","):
            part = raw_part.strip()
            if not part:
                continue
            if "-" in part:
                left, right = part.split("-", 1)
                start = int(left.strip())
                end = int(right.strip())
                if end < start:
                    raise ValueError("chapter range end must be >= start")
                chapters.update(range(start, end + 1))
            else:
                chapters.add(int(part))
        return sorted(chapters)
    raise ValueError("chapters_included must be a list or range string")


def _normalise_candidate(raw: dict[str, Any], arc_level: str) -> ArcCandidate:
    payload = dict(raw)
    payload["arc_level"] = arc_level
    payload["chapters_included"] = _parse_chapters(payload.get("chapters_included", []))
    payload["review_status"] = "pending_user_review"
    if arc_level == "major_arc":
        payload["parent_candidate_id"] = None
    return ArcCandidate.model_validate(payload)


def _candidate_payload(
    run_dir: str | Path,
    *,
    major_arcs: list[dict[str, Any]],
    sub_arcs: list[dict[str, Any]],
    candidate_version: int,
) -> tuple[dict[str, Any], list[ArcCandidate], list[ArcCandidate]]:
    major_models = [_normalise_candidate(item, "major_arc") for item in major_arcs]
    sub_models = [_normalise_candidate(item, "sub_arc") for item in sub_arcs]
    validate_arc_candidates(run_dir, major_models, sub_models)
    chapters = _chapters_for_editor(run_dir)
    payload = {
        "schema_version": "story_analyzer.arc_candidates.v1",
        "status": "pending_user_review",
        "candidate_version": candidate_version,
        "source_chapter_count": len(chapters),
        "major_arcs": [arc.model_dump(mode="json") for arc in major_models],
        "sub_arcs": [arc.model_dump(mode="json") for arc in sub_models],
    }
    return payload, major_models, sub_models


def _changed_arc_ids(before_payload: dict[str, Any], after_payload: dict[str, Any]) -> list[str]:
    before_arcs = {
        item.get("arc_candidate_id"): item
        for item in [*before_payload.get("major_arcs", []), *before_payload.get("sub_arcs", [])]
        if isinstance(item, dict)
    }
    after_arcs = {
        item.get("arc_candidate_id"): item
        for item in [*after_payload.get("major_arcs", []), *after_payload.get("sub_arcs", [])]
        if isinstance(item, dict)
    }
    changed = set(before_arcs).symmetric_difference(after_arcs)
    for arc_id in set(before_arcs).intersection(after_arcs):
        if json.dumps(before_arcs[arc_id], ensure_ascii=False, sort_keys=True) != json.dumps(
            after_arcs[arc_id],
            ensure_ascii=False,
            sort_keys=True,
        ):
            changed.add(str(arc_id))
    return sorted(str(arc_id) for arc_id in changed if arc_id)


def build_arc_review_editor(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir)
    candidates = _load_candidates_payload(run_path)
    review = _load_review(run_path)
    return {
        "schema_version": ARC_REVIEW_EDITOR_SCHEMA_VERSION,
        "run_dir": str(run_path),
        "candidate_version": candidates.get("candidate_version", 1),
        "source_chapter_count": candidates.get("source_chapter_count", len(_chapters_for_editor(run_path))),
        "chapters": _chapters_for_editor(run_path),
        "review": review.model_dump(mode="json"),
        "major_arcs": candidates.get("major_arcs", []),
        "sub_arcs": candidates.get("sub_arcs", []),
        "artifacts": {
            "arc_candidates": "arcs/arc_candidates.json",
            "arc_review": "arcs/arc_review.json",
            "major_arcs": "arcs/major_arcs.json",
            "sub_arcs": "arcs/sub_arcs.json",
        },
    }


def save_arc_review_edits(
    run_dir: str | Path,
    *,
    major_arcs: list[dict[str, Any]],
    sub_arcs: list[dict[str, Any]],
    operation: ArcEditOperation = "move_boundary",
    reason: str = "",
) -> dict[str, Any]:
    run_path = Path(run_dir)
    before_payload = _load_candidates_payload(run_path)
    candidate_version = int(before_payload.get("candidate_version", 1)) + 1
    after_payload, _major_models, _sub_models = _candidate_payload(
        run_path,
        major_arcs=major_arcs,
        sub_arcs=sub_arcs,
        candidate_version=candidate_version,
    )
    changed_arc_ids = _changed_arc_ids(before_payload, after_payload)
    edit = ArcUserEdit(
        operation=operation,
        target_arc_id=changed_arc_ids[0] if changed_arc_ids else "arc_candidates",
        before={
            "candidate_version": before_payload.get("candidate_version", 1),
            "changed_arc_ids": changed_arc_ids,
            "major_arc_count": len(before_payload.get("major_arcs", [])),
            "sub_arc_count": len(before_payload.get("sub_arcs", [])),
        },
        after={
            "candidate_version": candidate_version,
            "changed_arc_ids": changed_arc_ids,
            "major_arc_count": len(after_payload.get("major_arcs", [])),
            "sub_arc_count": len(after_payload.get("sub_arcs", [])),
        },
        reason=reason,
        edited_at=_utc_now(),
    )

    write_json(arc_candidates_path(run_path), after_payload)
    review = _load_review(run_path)
    review_payload = review.model_copy(
        update={
            "status": "pending_user_review",
            "candidate_version": candidate_version,
            "user_edits": [*review.user_edits, edit],
        }
    ).model_dump(mode="json")
    write_json(arc_review_path(run_path), review_payload)
    record_pipeline_step(
        run_path,
        step_id="arc_candidates",
        step_type="arc_candidates",
        status="completed",
        schema_version=after_payload["schema_version"],
        output_refs=["arcs/arc_candidates.json", "arcs/arc_review.json"],
    )
    event = invalidate_for_change(
        run_path,
        change_type="arc_boundary_user_adjusted",
        scope={"arc_ids": changed_arc_ids, "operation": operation},
        reason=reason or operation,
    )
    return {
        **build_arc_review_editor(run_path),
        "user_edit": edit.model_dump(mode="json"),
        "invalidation_event": event,
    }


def confirm_arc_review_edits(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir)
    review = confirm_arc_candidates(run_path)
    record_pipeline_step(
        run_path,
        step_id="arc_confirmation",
        step_type="arc_confirmation",
        status="completed",
        schema_version=review.get("schema_version", ""),
        output_refs=["arcs/major_arcs.json", "arcs/sub_arcs.json", "arcs/arc_review.json"],
    )
    record_pipeline_step(
        run_path,
        step_id="major_arcs",
        step_type="major_arcs",
        status="completed",
        output_refs=["arcs/major_arcs.json"],
    )
    record_pipeline_step(
        run_path,
        step_id="sub_arcs",
        step_type="sub_arcs",
        status="completed",
        output_refs=["arcs/sub_arcs.json"],
    )
    return {**build_arc_review_editor(run_path), "review": review}
