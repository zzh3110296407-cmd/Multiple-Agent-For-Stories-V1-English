from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import re

from ..evidence.raw_source_index_builder import (
    build_raw_source_index,
    load_raw_source_index,
    raw_source_index_path,
)
from .package_store import now_iso, write_json


HANDOFF_VERSION = "generator_handoff.v1"
SOURCE_REFERENCE_INDEX_VERSION = "generator_handoff.source_reference_index.v1"
SOURCE_REFERENCE_INDEX_V2_VERSION = "generator_handoff.source_reference_index.v2"
COMPILER_REPORT_VERSION = "generator_handoff.compiler_report.v1"
DEFAULT_OUTPUT_DIRNAME = "generator_handoff"
REQUIRED_JSON_INPUTS = (
    "run_manifest.json",
    "book_framework.json",
    "generation_profiles.json",
    "foreshadowing_registry.json",
    "source_leak_report.json",
    "abstraction_quality_report.json",
)
MODULE_PACK_TYPE_MAP = {
    "core_conflict_module": "core_conflict",
    "emotional_rhythm_module": "emotion_curve",
    "narrative_thread_module": "narrative_mechanism",
    "power_item_system_module": "adaptable_setting",
    "relationship_network_module": "relationship_dynamics",
    "worldbuilding_module": "worldbuilding",
}
GENERATOR_INTERNAL_FIELD_MARKERS = (
    "source_model_id",
    "llm_call_id",
    "raw_prompt",
    "raw_response",
    "hidden_reasoning",
)


def _read_json_payload(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    except (OSError, UnicodeDecodeError) as exc:
        return {}, f"could not read JSON: {exc}"
    if not isinstance(payload, dict):
        return {}, "JSON root must be an object"
    return payload, None


def _sanitize_generator_content(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in GENERATOR_INTERNAL_FIELD_MARKERS):
                continue
            sanitized[key] = _sanitize_generator_content(child)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_generator_content(item) for item in value]
    return value


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clip(value: Any, limit: int = 360) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _range_text(start: int, end: int) -> str:
    if not start and not end:
        return ""
    if start == end:
        return str(start)
    return f"{start}-{end}"


def _list_json_files(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.glob(pattern) if path.is_file())


def _sorted_manifest_chapters(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    chapters = manifest.get("chapters") or []
    if not isinstance(chapters, list):
        return []
    return sorted(chapters, key=lambda item: _coerce_int(item.get("chapter_index")))


def _source_title(entry: dict[str, Any], source_index: int) -> str:
    return (
        entry.get("original_title")
        or entry.get("original_chapter_title")
        or entry.get("source_title")
        or entry.get("input_title")
        or entry.get("normalized_title")
        or entry.get("title")
        or f"chapter_{source_index:03d}"
    )


def _chapter_lookup(manifest: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _coerce_int(entry.get("chapter_index")): entry
        for entry in _sorted_manifest_chapters(manifest)
        if _coerce_int(entry.get("chapter_index"))
    }


def _build_source_map(manifest: dict[str, Any]) -> dict[str, Any]:
    chapters = _sorted_manifest_chapters(manifest)
    grouped: dict[int, dict[str, Any]] = {}
    for entry in chapters:
        analysis_unit_index = _coerce_int(entry.get("chapter_index"))
        source_index = _coerce_int(entry.get("original_chapter_index"), analysis_unit_index)
        if not source_index:
            continue
        source_title = _source_title(entry, source_index)
        source_entry = grouped.setdefault(
            source_index,
            {
                "source_chapter_index": source_index,
                "source_title": source_title,
                "analysis_unit_start": analysis_unit_index,
                "analysis_unit_end": analysis_unit_index,
                "analysis_unit_range": str(analysis_unit_index),
                "part_count": _coerce_int(entry.get("part_count"), 1),
                "parts": [],
            },
        )
        source_entry["analysis_unit_start"] = min(source_entry["analysis_unit_start"], analysis_unit_index)
        source_entry["analysis_unit_end"] = max(source_entry["analysis_unit_end"], analysis_unit_index)
        source_entry["analysis_unit_range"] = _range_text(
            source_entry["analysis_unit_start"],
            source_entry["analysis_unit_end"],
        )
        source_entry["part_count"] = max(source_entry["part_count"], _coerce_int(entry.get("part_count"), 1))
        source_entry["parts"].append(
            {
                "analysis_unit_index": analysis_unit_index,
                "analysis_unit_title": entry.get("input_title") or entry.get("normalized_title") or entry.get("source_title") or entry.get("title") or "",
                "part_index": _coerce_int(entry.get("part_index"), 1),
                "part_count": _coerce_int(entry.get("part_count"), 1),
                "part_start_char": entry.get("part_start_char"),
                "part_end_char": entry.get("part_end_char"),
                "text_length": entry.get("text_length"),
                "status": entry.get("status", ""),
            }
        )

    source_chapters = [grouped[index] for index in sorted(grouped)]
    for source_entry in source_chapters:
        source_entry["parts"] = sorted(
            source_entry["parts"],
            key=lambda item: (item["analysis_unit_index"], item["part_index"]),
        )

    source_total = _coerce_int(manifest.get("source_total_chapters"), len(source_chapters))
    analysis_total = _coerce_int(manifest.get("analysis_unit_count"), len(chapters))
    arc_ranges = []
    for index, item in enumerate(manifest.get("arc_ranges") or [], start=1):
        if not isinstance(item, dict):
            continue
        start = _coerce_int(item.get("start"))
        end = _coerce_int(item.get("end"))
        arc_ranges.append(
            {
                "arc_id": f"arc_{index:03d}",
                "analysis_unit_range": item.get("analysis_unit_range") or _range_text(start, end),
                "source_chapter_range": item.get("source_chapter_range", ""),
                "analysis_unit_start": start,
                "analysis_unit_end": end,
            }
        )

    return {
        "source_total_chapters": source_total,
        "analysis_unit_count": analysis_total,
        "chapter_count_basis": manifest.get("chapter_count_basis", "source_chapters"),
        "source_chapters": source_chapters,
        "arc_source_ranges": arc_ranges,
        "arc_ranges": arc_ranges,
    }


def _analysis_unit_ref(index: int) -> str:
    return f"REF_CH_{index:03d}"


def _arc_ref(index: int) -> str:
    return f"REF_ARC_{index:03d}"


def _analysis_unit_source_info(index: int, chapter_meta: dict[int, dict[str, Any]]) -> dict[str, Any]:
    meta = chapter_meta.get(index, {})
    source_index = _coerce_int(meta.get("original_chapter_index"), index)
    return {
        "source_chapter_index": source_index,
        "analysis_unit_index": index,
        "source_title": _source_title(meta, source_index or index),
        "part_index": meta.get("part_index"),
        "part_count": meta.get("part_count"),
    }


def _chapter_body(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("chapter_analysis", "chapter", "analysis"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    story_facts = payload.get("story_facts") if isinstance(payload.get("story_facts"), dict) else {}
    structural = payload.get("structural_analysis") if isinstance(payload.get("structural_analysis"), dict) else {}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    if story_facts or structural:
        return {
            "summary": story_facts.get("chapter_summary", ""),
            "chapter_summary": story_facts.get("chapter_summary", ""),
            "plot_nodes": story_facts.get("events", []),
            "information_release": story_facts.get("information_state_changes", []),
            "character_state_after": story_facts.get("character_state_changes", []),
            "relationship_changes": story_facts.get("relationship_changes", []),
            "world_facts_added": story_facts.get("world_facts_added", []),
            "chapter_function": structural.get("chapter_function", {}),
            "conflict": structural.get("conflict_function", {}),
            "reader_experience": structural.get("dominant_reader_experience", {}),
            "pacing_role": structural.get("pacing_density", {}),
            "style_pacing": {"pacing": structural.get("pacing_density", {})},
            "source_title": source.get("input_title") or source.get("normalized_title") or "",
        }
    return payload


def _extract_text_list(value: Any, limit: int = 3) -> list[str]:
    results: list[str] = []
    if isinstance(value, str) and value.strip():
        return [_clip(value)]
    if isinstance(value, dict):
        for key in ("content", "event", "summary", "text", "description", "external", "internal"):
            if value.get(key):
                results.append(_clip(value.get(key)))
            if len(results) >= limit:
                return results
        for child in value.values():
            results.extend(_extract_text_list(child, limit=limit - len(results)))
            if len(results) >= limit:
                return results
    if isinstance(value, list):
        for child in value:
            results.extend(_extract_text_list(child, limit=limit - len(results)))
            if len(results) >= limit:
                return results
    return results


def _chapter_evidence_spans(body: dict[str, Any], source_ref_id: str) -> list[dict[str, str]]:
    spans: list[dict[str, str]] = []
    for field in ("plot_nodes", "information_release", "conflict", "reader_experience", "chapter_function"):
        for text in _extract_text_list(body.get(field), limit=2):
            if text:
                spans.append(_evidence_span(len(spans) + 1, field, text, source_ref_id))
            if len(spans) >= 6:
                return spans
    summary = body.get("summary") or body.get("chapter_summary")
    if summary and not spans:
        spans.append(_evidence_span(1, "summary", _clip(summary), source_ref_id))
    return spans


def _evidence_span(index: int, evidence_type: str, text: str, source_ref_id: str) -> dict[str, Any]:
    clipped = _clip(text, limit=300)
    return {
        "span_id": f"SP{index:03d}",
        "evidence_type": evidence_type,
        "text": clipped,
        "char_start": 0,
        "char_end": len(clipped),
        "offset_basis": "analysis_output_excerpt",
        "source_ref_id": source_ref_id,
    }


def _chapter_summary(body: dict[str, Any]) -> str:
    return _clip(body.get("summary") or body.get("chapter_summary") or body.get("chapter_function") or "")


def _invalid_json_error(*, code: str, path: Path, output_dir: Path, reason: str) -> dict[str, str]:
    return {
        "code": code,
        "message": f"{path.name} is invalid: {reason}",
        "path": path.relative_to(output_dir).as_posix(),
    }


def _numeric_file_suffix(path: Path, prefix: str) -> int:
    match = re.fullmatch(rf"{re.escape(prefix)}_(\d+)(?:_[a-z]+)?", path.stem)
    return _coerce_int(match.group(1)) if match else 0


def _load_chapter_analyses(output_dir: Path) -> tuple[list[tuple[int, Path, dict[str, Any]]], list[dict[str, str]]]:
    chapters: list[tuple[int, Path, dict[str, Any]]] = []
    errors: list[dict[str, str]] = []
    for path in _list_json_files(output_dir / "chapters", "chapter_*_analysis.json"):
        stem = path.stem.replace("_analysis", "")
        index = _coerce_int(stem.rsplit("_", 1)[-1])
        payload, error = _read_json_payload(path)
        if error:
            errors.append(_invalid_json_error(code="INVALID_CHAPTER_ANALYSIS", path=path, output_dir=output_dir, reason=error))
        chapters.append((index, path, payload))
    if chapters:
        return sorted(chapters, key=lambda item: item[0]), errors
    for path in _list_json_files(output_dir / "canonical_chapter_analysis", "chapter_*.json"):
        index = _numeric_file_suffix(path, "chapter")
        if not index:
            continue
        payload, error = _read_json_payload(path)
        if error:
            errors.append(_invalid_json_error(code="INVALID_CHAPTER_ANALYSIS", path=path, output_dir=output_dir, reason=error))
        chapters.append((index, path, payload))
    return sorted(chapters, key=lambda item: item[0]), errors


def _load_chapter_frameworks(output_dir: Path) -> tuple[list[tuple[int, Path, dict[str, Any]]], list[dict[str, str]]]:
    frameworks: list[tuple[int, Path, dict[str, Any]]] = []
    errors: list[dict[str, str]] = []
    for path in _list_json_files(output_dir / "chapters", "chapter_*_framework.json"):
        stem = path.stem.replace("_framework", "")
        index = _coerce_int(stem.rsplit("_", 1)[-1])
        payload, error = _read_json_payload(path)
        if error:
            errors.append(_invalid_json_error(code="INVALID_CHAPTER_FRAMEWORK", path=path, output_dir=output_dir, reason=error))
        frameworks.append((index, path, payload))
    if frameworks:
        return sorted(frameworks, key=lambda item: item[0]), errors
    for path in _list_json_files(output_dir / "canonical_chapter_analysis", "chapter_*.json"):
        index = _numeric_file_suffix(path, "chapter")
        if not index:
            continue
        payload, error = _read_json_payload(path)
        if error:
            errors.append(_invalid_json_error(code="INVALID_CHAPTER_FRAMEWORK", path=path, output_dir=output_dir, reason=error))
        frameworks.append((index, path, payload))
    return sorted(frameworks, key=lambda item: item[0]), errors


def _v1_arc_payload(raw: dict[str, Any], index: int) -> dict[str, Any]:
    chapters = [_coerce_int(item) for item in raw.get("chapters_included") or []]
    chapter_range = _range_label({item for item in chapters if item})
    arc_id = raw.get("arc_candidate_id") or raw.get("sub_arc_id") or f"sub_arc_{index:03d}"
    return {
        "arc_index": index,
        "sub_arc_id": arc_id,
        "parent_major_arc_id": raw.get("parent_candidate_id", ""),
        "arc_title": raw.get("arc_title") or raw.get("title") or raw.get("stage_goal") or arc_id,
        "source_chapter_range": raw.get("source_chapter_range") or chapter_range,
        "analysis_unit_range": raw.get("analysis_unit_range") or chapter_range,
        "arc_function": raw.get("stage_goal") or raw.get("structural_function") or "",
        "arc_goal": raw.get("stage_goal", ""),
        "core_conflict": raw.get("dominant_conflict", ""),
        "arc_turning_point": raw.get("turning_points", []),
        "arc_emotion_curve": raw.get("dominant_reader_experience", ""),
        "information_release": raw.get("information_release", []),
        "foreshadowing_summary": raw.get("foreshadowing_summary", []),
    }


def _load_arc_files(output_dir: Path) -> tuple[list[tuple[int, Path, dict[str, Any]]], list[dict[str, str]]]:
    arcs: list[tuple[int, Path, dict[str, Any]]] = []
    errors: list[dict[str, str]] = []
    for path in _list_json_files(output_dir / "arcs", "arc_*.json"):
        index = _numeric_file_suffix(path, "arc")
        if not index:
            continue
        payload, error = _read_json_payload(path)
        if error:
            errors.append(_invalid_json_error(code="INVALID_ARC_ANALYSIS", path=path, output_dir=output_dir, reason=error))
        arcs.append((index, path, payload))
    if arcs:
        return sorted(arcs, key=lambda item: item[0]), errors
    sub_arcs_path = output_dir / "arcs" / "sub_arcs.json"
    sub_arcs_payload, sub_arcs_error = _read_json_payload(sub_arcs_path)
    if sub_arcs_error and sub_arcs_path.exists():
        errors.append(_invalid_json_error(code="INVALID_ARC_ANALYSIS", path=sub_arcs_path, output_dir=output_dir, reason=sub_arcs_error))
    for index, raw in enumerate(sub_arcs_payload.get("arcs") or [], start=1):
        if isinstance(raw, dict):
            arcs.append((index, sub_arcs_path, _v1_arc_payload(raw, index)))
    return sorted(arcs, key=lambda item: item[0]), errors


def _expected_analysis_unit_indices(manifest: dict[str, Any]) -> set[int]:
    indices = {
        _coerce_int(entry.get("chapter_index"))
        for entry in _sorted_manifest_chapters(manifest)
        if _coerce_int(entry.get("chapter_index"))
    }
    if indices:
        return indices
    analysis_unit_count = _coerce_int(manifest.get("analysis_unit_count"))
    return set(range(1, analysis_unit_count + 1)) if analysis_unit_count else set()


def _expected_arc_indices(manifest: dict[str, Any]) -> set[int]:
    arc_ranges = manifest.get("arc_ranges") or []
    if isinstance(arc_ranges, list) and arc_ranges:
        return set(range(1, len(arc_ranges) + 1))
    expected_count = _coerce_int(manifest.get("expected_arc_count") or manifest.get("arc_count"))
    return set(range(1, expected_count + 1)) if expected_count else set()


def _file_index_set(indexed_files: list[tuple[int, Path, dict[str, Any]]]) -> set[int]:
    return {index for index, _, _ in indexed_files if index}


def _validate_expected_file_coverage(
    *,
    expected_indices: set[int],
    actual_indices: set[int],
    missing_code: str,
    extra_code: str,
    path: str,
    errors: list[dict[str, str]],
) -> None:
    if not expected_indices:
        return
    missing = sorted(expected_indices - actual_indices)
    extra = sorted(actual_indices - expected_indices)
    if missing:
        errors.append(
            {
                "code": missing_code,
                "message": f"missing expected files for indices={missing}",
                "path": path,
            }
        )
    if extra:
        errors.append(
            {
                "code": extra_code,
                "message": f"unexpected extra files for indices={extra}",
                "path": path,
            }
        )


def _build_source_reference_index(
    *,
    output_dir: Path,
    manifest: dict[str, Any],
    chapter_analyses: list[tuple[int, Path, dict[str, Any]]],
    arc_files: list[tuple[int, Path, dict[str, Any]]],
    raw_source_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chapter_meta = _chapter_lookup(manifest)
    references: dict[str, dict[str, Any]] = {}
    for index, path, payload in chapter_analyses:
        ref_id = _analysis_unit_ref(index)
        body = _chapter_body(payload)
        source_info = _analysis_unit_source_info(index, chapter_meta)
        entry = {
            "source_type": "chapter_analysis",
            "source_path": path.relative_to(output_dir).as_posix(),
            **source_info,
            "near_source_summary": _chapter_summary(body),
            "evidence_spans": _chapter_evidence_spans(body, ref_id),
        }
        raw_scope = _raw_scope_for_analysis_units(
            raw_source_index,
            {index},
            source_chapter_range=source_info.get("source_chapter_range") or source_info.get("source_chapter_index") or "",
            analysis_unit_range=str(index),
        )
        if raw_scope:
            entry["raw_source_scope"] = raw_scope
        references[ref_id] = entry

    for index, path, payload in arc_files:
        ref_id = _arc_ref(index)
        analysis_unit_range = payload.get("analysis_unit_range") or payload.get("arc_chapter_range", "")
        entry = {
            "source_type": "arc_analysis",
            "source_path": path.relative_to(output_dir).as_posix(),
            "arc_index": index,
            "source_chapter_range": payload.get("source_chapter_range") or payload.get("arc_chapter_range", ""),
            "analysis_unit_range": analysis_unit_range,
            "source_title": payload.get("arc_title") or payload.get("title") or f"arc_{index:03d}",
            "near_source_summary": _clip(payload.get("arc_summary") or payload.get("arc_goal") or payload.get("core_conflict") or ""),
            "evidence_spans": [
                _evidence_span(1, "arc_goal", _clip(payload.get("arc_goal")), ref_id)
            ]
            if payload.get("arc_goal")
            else [],
        }
        raw_scope = _raw_scope_for_analysis_units(
            raw_source_index,
            _parse_int_range(analysis_unit_range),
            source_chapter_range=entry["source_chapter_range"],
            analysis_unit_range=analysis_unit_range,
        )
        if raw_scope:
            entry["raw_source_scope"] = raw_scope
        references[ref_id] = entry
    return {
        "schema_version": SOURCE_REFERENCE_INDEX_V2_VERSION if raw_source_index else SOURCE_REFERENCE_INDEX_VERSION,
        "generated_at": now_iso(),
        "raw_source_index_ref": "evidence/raw_source_index.json" if raw_source_index else "",
        "references": references,
    }


def _first_status(*reports: dict[str, Any], default: str = "missing") -> str:
    for report in reports:
        if isinstance(report, dict) and report.get("status"):
            return str(report["status"])
    return default


def _build_quality_gate(
    *,
    manifest: dict[str, Any],
    source_leak_report: dict[str, Any],
    abstraction_quality_report: dict[str, Any],
    arc_count: int,
) -> dict[str, Any]:
    missing = manifest.get("missing_required_outputs")
    if not isinstance(missing, list):
        missing = []
    llm_health = manifest.get("llm_health") if isinstance(manifest.get("llm_health"), dict) else {}
    unrecovered = _coerce_int(
        llm_health.get("unrecovered_failed_target_count")
        or manifest.get("llm_unrecovered_failed_target_count")
        or manifest.get("unrecovered_failed_target_count")
    )
    return {
        "run_status": manifest.get("run_status", "unknown"),
        "downstream_status": manifest.get("downstream_status", ""),
        "source_leak_status": _first_status(source_leak_report),
        "source_leak_blocking_count": _coerce_int(
            source_leak_report.get("blocking_leak_count") or source_leak_report.get("blocking_issue_count")
        ),
        "abstraction_quality_status": _first_status(abstraction_quality_report),
        "abstraction_quality_score": abstraction_quality_report.get("abstraction_quality_score"),
        "llm_health_status": llm_health.get("status", "passed" if unrecovered == 0 else "recovered_with_failures"),
        "llm_unrecovered_failed_target_count": unrecovered,
        "missing_required_outputs": missing,
        "successful_chapter_count": _coerce_int(manifest.get("successful_chapter_count")),
        "failed_chapter_count": _coerce_int(manifest.get("failed_chapter_count")),
        "source_total_chapters": _coerce_int(manifest.get("source_total_chapters") or manifest.get("total_chapters")),
        "analysis_unit_count": _coerce_int(manifest.get("analysis_unit_count")),
        "arc_count": arc_count,
        "expected_arc_count": len(manifest.get("arc_ranges") or []),
    }


def _source_refs_for_range(analysis_unit_range: Any, chapter_count: int) -> list[str]:
    text = str(analysis_unit_range or "")
    if "-" in text:
        start_text, _, end_text = text.partition("-")
        start = _coerce_int(start_text)
        end = _coerce_int(end_text, start)
    else:
        start = _coerce_int(text)
        end = start
    if not start:
        return []
    end = max(start, end)
    return [_analysis_unit_ref(index) for index in range(start, min(end, chapter_count) + 1)]


def _parse_int_range(value: Any) -> set[int]:
    text = str(value or "").strip()
    if not text:
        return set()
    result: set[int] = set()
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, _, end_text = part.partition("-")
            start = _coerce_int(start_text)
            end = _coerce_int(end_text, start)
            if start:
                if end < start:
                    start, end = end, start
                result.update(range(start, end + 1))
        else:
            number = _coerce_int(part)
            if number:
                result.add(number)
    return result


def _raw_chapter_records(raw_source_index: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(raw_source_index, dict):
        return []
    chapters = raw_source_index.get("chapters")
    return [item for item in chapters if isinstance(item, dict)] if isinstance(chapters, list) else []


def _raw_scope_for_analysis_units(
    raw_source_index: dict[str, Any] | None,
    analysis_units: set[int],
    *,
    source_chapter_range: Any = "",
    analysis_unit_range: Any = "",
) -> dict[str, Any]:
    if not analysis_units:
        return {}
    matched = [
        chapter
        for chapter in _raw_chapter_records(raw_source_index)
        if _coerce_int(chapter.get("analysis_unit_index")) in analysis_units
    ]
    if not matched:
        return {}
    segment_ids: list[str] = []
    char_starts: list[int] = []
    char_ends: list[int] = []
    source_chapters: set[int] = set()
    for chapter in matched:
        for segment_id in chapter.get("segment_ids") or []:
            if segment_id and segment_id not in segment_ids:
                segment_ids.append(str(segment_id))
        start = _coerce_int(chapter.get("char_start"))
        end = _coerce_int(chapter.get("char_end"))
        if start or start == 0:
            char_starts.append(start)
        if end:
            char_ends.append(end)
        source_chapter = _coerce_int(chapter.get("source_chapter_index"))
        if source_chapter:
            source_chapters.add(source_chapter)
    return {
        "source_chapter_range": str(source_chapter_range or _range_label(source_chapters)),
        "analysis_unit_range": str(analysis_unit_range or _range_label(analysis_units)),
        "char_start": min(char_starts) if char_starts else 0,
        "char_end": max(char_ends) if char_ends else 0,
        "segment_ids": segment_ids,
    }


def _range_label(values: set[int]) -> str:
    if not values:
        return ""
    ordered = sorted(values)
    if len(ordered) == 1:
        return str(ordered[0])
    if ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{ordered[0]}-{ordered[-1]}"
    return ",".join(str(item) for item in ordered)


def _all_chapter_refs(chapter_analyses: list[tuple[int, Path, dict[str, Any]]]) -> list[str]:
    return [_analysis_unit_ref(index) for index, _, _ in chapter_analyses]


def _all_arc_refs(arc_files: list[tuple[int, Path, dict[str, Any]]]) -> list[str]:
    return [_arc_ref(index) for index, _, _ in arc_files]


def _build_chapter_blueprints(
    *,
    chapter_analyses: list[tuple[int, Path, dict[str, Any]]],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    chapter_meta = _chapter_lookup(manifest)
    blueprints: list[dict[str, Any]] = []
    for index, _, payload in chapter_analyses:
        body = _chapter_body(payload)
        source_info = _analysis_unit_source_info(index, chapter_meta)
        blueprints.append(
            {
                "chapter_blueprint_id": f"CB{index:03d}",
                **source_info,
                "chapter_function": body.get("chapter_function", ""),
                "pacing_role": body.get("pacing_role") or (body.get("style_pacing") or {}).get("pacing", ""),
                "conflict_progression": body.get("conflict", {}),
                "information_release_pattern": body.get("information_release", []),
                "character_state_changes": body.get("character_state_after") or body.get("character_arc") or {},
                "reader_experience_target": body.get("reader_experience") or body.get("reader_emotion", ""),
                "source_refs": [_analysis_unit_ref(index)],
            }
        )
    return blueprints


def _build_arc_hierarchy(
    *,
    profiles: dict[str, Any],
    arc_files: list[tuple[int, Path, dict[str, Any]]],
) -> dict[str, Any]:
    profile_hierarchy = profiles.get("arc_hierarchy") if isinstance(profiles.get("arc_hierarchy"), dict) else {}
    sub_arcs = []
    for index, _, payload in arc_files:
        analysis_range = payload.get("analysis_unit_range") or payload.get("arc_chapter_range", "")
        sub_arcs.append(
            {
                "sub_arc_id": payload.get("sub_arc_id") or f"sub_arc_{index:03d}",
                "arc_id": f"arc_{index:03d}",
                "arc_level": "sub",
                "arc_index": index,
                "title": payload.get("arc_title") or payload.get("title") or "",
                "arc_title": payload.get("arc_title") or payload.get("title") or "",
                "source_chapter_range": payload.get("source_chapter_range") or payload.get("arc_chapter_range", ""),
                "analysis_unit_range": analysis_range,
                "structural_function": payload.get("arc_function") or payload.get("arc_theme") or payload.get("arc_summary") or "",
                "arc_goal": payload.get("arc_goal", ""),
                "core_conflict": payload.get("core_conflict", ""),
                "turning_point": payload.get("arc_turning_point") or payload.get("turning_point", ""),
                "emotion_curve": payload.get("arc_emotion_curve") or payload.get("emotion_curve") or [],
                "information_release": payload.get("information_release", []),
                "foreshadowing_summary": payload.get("foreshadowing_summary", []),
                "source_refs": [_arc_ref(index)],
            }
        )
    raw_major_arcs = profile_hierarchy.get("major_arcs") if isinstance(profile_hierarchy.get("major_arcs"), list) else []
    major_arcs = _normalize_major_arcs(raw_major_arcs, sub_arcs)
    if not major_arcs:
        major_arcs = [
            {
                "major_arc_id": "major_arc_001",
                "arc_level": "major",
                "title": "compiled_arc_hierarchy",
                "major_arc_title": "compiled_arc_hierarchy",
                "structural_function": "compiled_from_sub_arcs",
                "arc_goal": "",
                "core_conflict": "",
                "turning_point": "",
                "emotion_curve": [],
                "information_release": [],
                "foreshadowing_summary": [],
                "source_chapter_range": _combine_ranges([arc.get("source_chapter_range") for arc in sub_arcs]),
                "analysis_unit_range": _combine_ranges([arc.get("analysis_unit_range") for arc in sub_arcs]),
                "sub_arc_ids": [arc["sub_arc_id"] for arc in sub_arcs],
                "source_refs": sorted({ref for arc in sub_arcs for ref in arc.get("source_refs", [])}),
            }
        ] if sub_arcs else []
    return {
        "schema_version": "generator_handoff.arc_hierarchy.v1",
        "major_arcs": major_arcs,
        "sub_arcs": sub_arcs,
        "arc_links": [],
    }


def _normalize_major_arcs(raw_major_arcs: list[dict[str, Any]], sub_arcs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sub_by_id = {str(arc.get("sub_arc_id")): arc for arc in sub_arcs}
    all_sub_refs = sorted({ref for arc in sub_arcs for ref in arc.get("source_refs", [])})
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_major_arcs, start=1):
        if not isinstance(raw, dict):
            continue
        sub_arc_ids = [str(item) for item in raw.get("sub_arc_ids", []) if item]
        source_refs = sorted(
            {
                ref
                for sub_arc_id in sub_arc_ids
                for ref in sub_by_id.get(sub_arc_id, {}).get("source_refs", [])
            }
        ) or all_sub_refs
        normalized_arc = dict(raw)
        normalized_arc.update(
            {
                "major_arc_id": raw.get("major_arc_id") or f"major_arc_{index:03d}",
                "arc_level": "major",
                "title": raw.get("major_arc_title") or raw.get("title") or f"major_arc_{index:03d}",
                "major_arc_title": raw.get("major_arc_title") or raw.get("title") or f"major_arc_{index:03d}",
                "structural_function": raw.get("structural_function") or raw.get("dominant_stage", ""),
                "arc_goal": raw.get("arc_goal", ""),
                "core_conflict": raw.get("core_conflict", ""),
                "turning_point": raw.get("turning_point") or raw.get("turning_points", []),
                "emotion_curve": raw.get("emotion_curve", []),
                "information_release": raw.get("information_release", []),
                "foreshadowing_summary": raw.get("foreshadowing_summary", []),
                "source_chapter_range": raw.get("source_chapter_range", ""),
                "analysis_unit_range": raw.get("analysis_unit_range", ""),
                "sub_arc_ids": sub_arc_ids,
                "source_refs": source_refs,
            }
        )
        normalized.append(normalized_arc)
    return normalized


def _combine_ranges(ranges: list[Any]) -> str:
    starts: list[int] = []
    ends: list[int] = []
    for item in ranges:
        text = str(item or "")
        if not text:
            continue
        if "-" in text:
            start_text, _, end_text = text.partition("-")
            start = _coerce_int(start_text)
            end = _coerce_int(end_text, start)
        else:
            start = _coerce_int(text)
            end = start
        if start:
            starts.append(start)
            ends.append(end or start)
    if not starts:
        return ""
    return _range_text(min(starts), max(ends))


def _normalize_foreshadowing_registry(registry: dict[str, Any]) -> dict[str, Any]:
    items = []
    for raw in registry.get("items") or []:
        if not isinstance(raw, dict):
            continue
        content = raw.get("canonical_content") or raw.get("summary") or raw.get("text") or raw.get("content") or ""
        item = {
            "id": raw.get("id", ""),
            "canonical_content": content,
            "summary": raw.get("summary") or content,
            "text": raw.get("text") or content,
            "status": raw.get("status", "planted"),
            "tracking_scope": raw.get("tracking_scope", ""),
            "memory_lane": raw.get("memory_lane", ""),
            "planted_chapter": raw.get("planted_chapter"),
            "resolved_in_chapter": raw.get("resolved_in_chapter"),
            "partial_resolution_chapters": raw.get("partial_resolution_chapters", []),
            "open_questions": raw.get("open_questions", []),
            "state_updates": raw.get("state_updates", []),
        }
        refs = []
        planted = _coerce_int(item.get("planted_chapter"))
        if planted:
            refs.append(_analysis_unit_ref(planted))
        for partial in item.get("partial_resolution_chapters") or []:
            partial_index = _coerce_int(partial)
            if partial_index:
                refs.append(_analysis_unit_ref(partial_index))
        resolved = _coerce_int(item.get("resolved_in_chapter"))
        if resolved:
            refs.append(_analysis_unit_ref(resolved))
        item["source_refs"] = sorted(set(refs))
        items.append(item)
    return {
        "schema_version": "generator_handoff.foreshadowing_registry.v1",
        "item_count": len(items),
        "items": items,
        "diagnostics": {
            "source_model_id_conflicts": registry.get("source_model_id_conflicts", []),
            "source_model_id_alias_collisions": registry.get("source_model_id_alias_collisions", []),
        },
    }


def _material(
    *,
    material_id: str,
    module_type: str,
    abstraction_level: str,
    source_dependence: str,
    granularity: str,
    content: Any,
    selection_tags: list[str],
    source_refs: list[str],
    evidence_strength: str = "compiled",
) -> dict[str, Any]:
    return {
        "material_id": material_id,
        "module_type": module_type,
        "abstraction_level": abstraction_level,
        "source_dependence": source_dependence,
        "granularity": granularity,
        "content": _sanitize_generator_content(content),
        "selection_tags": selection_tags,
        "source_refs": sorted(set(source_refs)),
        "evidence_strength": evidence_strength,
    }


def _evidence_texts_for_refs(
    source_reference_index: dict[str, Any],
    source_refs: list[str],
    *,
    max_items: int = 18,
) -> list[str]:
    references = source_reference_index.get("references") if isinstance(source_reference_index.get("references"), dict) else {}
    texts: list[str] = []
    seen: set[str] = set()
    for ref in source_refs:
        entry = references.get(ref)
        if not isinstance(entry, dict):
            continue
        candidates = []
        for span in entry.get("evidence_spans") or []:
            if isinstance(span, dict):
                text = span.get("text") or span.get("evidence_text")
                if text:
                    candidates.append(str(text))
        if not candidates:
            summary = entry.get("near_source_summary")
            if summary:
                candidates.append(str(summary))
        for text in candidates:
            clipped = _clip(text, limit=300)
            if clipped and clipped not in seen:
                seen.add(clipped)
                texts.append(clipped)
            if len(texts) >= max_items:
                return texts
    return texts


def _source_supported_content(
    *,
    purpose: str,
    source_refs: list[str],
    source_reference_index: dict[str, Any],
    fallback_content: Any = "",
) -> dict[str, Any]:
    evidence_texts = _evidence_texts_for_refs(source_reference_index, source_refs)
    if not evidence_texts:
        for text in _extract_text_list(fallback_content, limit=8):
            if text:
                evidence_texts.append(text)
    return {
        "source_supported_summary": " ".join(evidence_texts),
    }


def _status_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _foreshadowing_material_content(
    registry: dict[str, Any],
    *,
    source_refs: list[str],
    source_reference_index: dict[str, Any],
) -> dict[str, Any]:
    content = _source_supported_content(
        purpose="完整伏笔表见顶层 foreshadowing_registry；本材料只提供近源证据摘要。",
        source_refs=source_refs,
        source_reference_index=source_reference_index,
        fallback_content=registry,
    )
    items = [item for item in registry.get("items") or [] if isinstance(item, dict)]
    content.update(
        {
            "registry_ref": "foreshadowing_registry",
            "registry_item_count": len(items),
            "status_counts": _status_counts(items, "status"),
            "tracking_scope_counts": _status_counts(items, "tracking_scope"),
            "memory_lane_counts": _status_counts(items, "memory_lane"),
        }
    )
    return content


def _module_pack_variables(pack_content: Any) -> list[dict[str, str]]:
    variables: list[dict[str, str]] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            source_term = value.get("source_term") or value.get("term") or value.get("name")
            placeholder = value.get("placeholder") or value.get("entity_ref") or value.get("role")
            if source_term or placeholder:
                variables.append(
                    {
                        "source_term": str(source_term or ""),
                        "placeholder": str(placeholder or ""),
                    }
                )
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(pack_content)
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in variables:
        key = (item["source_term"], item["placeholder"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[:50]


def _mechanized_module_pack(pack_name: str, pack_content: Any) -> dict[str, Any]:
    module_type = MODULE_PACK_TYPE_MAP.get(pack_name, "narrative_mechanism")
    return {
        "transferable_mechanism": (
            f"Mechanism pattern for {module_type}: extract the module's reusable structure, "
            "pressure source, conflict function, information-release role, and pacing effect before substituting setting details."
        ),
        "generator_usage_notes": [
            "Use this as an adaptable mechanism, not as a fixed plot copy.",
            "Replace source-specific names, objects, and organizations with the user's selected variables.",
            "Preserve the module's narrative function, rhythm, and conflict pressure when adapting it.",
        ],
        "replaceable_variables": _module_pack_variables(pack_content),
        "source_module_snapshot": pack_content,
    }


def _build_generator_materials(
    *,
    book_framework: dict[str, Any],
    profiles: dict[str, Any],
    arc_hierarchy: dict[str, Any],
    chapter_blueprints: list[dict[str, Any]],
    foreshadowing_registry: dict[str, Any],
    source_reference_index: dict[str, Any],
    chapter_analyses: list[tuple[int, Path, dict[str, Any]]],
    arc_files: list[tuple[int, Path, dict[str, Any]]],
) -> list[dict[str, Any]]:
    usage_profiles = profiles.get("usage_profiles") if isinstance(profiles.get("usage_profiles"), dict) else {}
    structure_only = usage_profiles.get("structure_only") if isinstance(usage_profiles.get("structure_only"), dict) else {}
    hybrid = usage_profiles.get("hybrid_adaptation") if isinstance(usage_profiles.get("hybrid_adaptation"), dict) else {}
    module_packs = hybrid.get("module_packs") if isinstance(hybrid.get("module_packs"), dict) else {}
    chapter_refs = _all_chapter_refs(chapter_analyses)
    arc_refs = _all_arc_refs(arc_files)
    source_fidelity_refs = arc_refs or chapter_refs

    materials = [
        _material(
            material_id="GM001",
            module_type="pacing_structure",
            abstraction_level="abstract",
            source_dependence="source_free",
            granularity="book",
            content=structure_only,
            selection_tags=["original_writing", "structure_only", "rhythm"],
            source_refs=chapter_refs + arc_refs,
        ),
        _material(
            material_id="GM002",
            module_type="source_fidelity",
            abstraction_level="source_specific",
            source_dependence="source_bound",
            granularity="book",
            content=_source_supported_content(
                purpose="原作续写或修改的近源证据摘要；完整全书框架见顶层 book_framework.content。",
                source_refs=source_fidelity_refs,
                source_reference_index=source_reference_index,
                fallback_content=book_framework,
            ),
            selection_tags=["continuation", "revision", "source_story"],
            source_refs=source_fidelity_refs,
        ),
        _material(
            material_id="GM003",
            module_type="arc_structure",
            abstraction_level="semi_abstract",
            source_dependence="adaptable",
            granularity="arc",
            content=arc_hierarchy,
            selection_tags=["original_writing", "hybrid_adaptation", "continuation", "arc_structure"],
            source_refs=arc_refs,
        ),
        _material(
            material_id="GM004",
            module_type="chapter_progression",
            abstraction_level="semi_abstract",
            source_dependence="adaptable",
            granularity="chapter",
            content=chapter_blueprints,
            selection_tags=["chapter_progression", "pacing", "scene_function"],
            source_refs=chapter_refs,
        ),
        _material(
            material_id="GM005",
            module_type="foreshadowing_system",
            abstraction_level="source_specific",
            source_dependence="source_bound",
            granularity="thread",
            content=_foreshadowing_material_content(
                foreshadowing_registry,
                source_refs=chapter_refs,
                source_reference_index=source_reference_index,
            ),
            selection_tags=["continuation", "revision", "memory", "payoff"],
            source_refs=chapter_refs,
        ),
    ]
    for offset, (pack_name, pack_content) in enumerate(sorted(module_packs.items()), start=6):
        materials.append(
            _material(
                material_id=f"GM{offset:03d}",
                module_type=MODULE_PACK_TYPE_MAP.get(pack_name, "narrative_mechanism"),
                abstraction_level="semi_abstract",
                source_dependence="adaptable",
                granularity="module",
                content=_mechanized_module_pack(pack_name, pack_content),
                selection_tags=["hybrid_adaptation", pack_name],
                source_refs=chapter_refs + arc_refs,
            )
        )
    return materials


def _build_work_identity(manifest: dict[str, Any], book_framework: dict[str, Any], work_title: str) -> dict[str, Any]:
    return {
        "work_title": work_title or manifest.get("work_title") or book_framework.get("work_title") or "",
        "run_id": manifest.get("run_id", ""),
        "analyzer": manifest.get("analyzer", "book_analyzer_v2"),
        "model_provider": manifest.get("model_provider", ""),
        "model": manifest.get("model", ""),
    }


def _build_selection_metadata() -> dict[str, Any]:
    return {
        "selection_owner": "story_generator",
        "user_type_selection_stage": "generator_runtime",
        "available_dimensions": [
            "source_dependence",
            "abstraction_level",
            "granularity",
            "module_type",
            "selection_tags",
            "tracking_scope",
            "memory_lane",
        ],
        "recommended_filters": {
            "original_writing": {"prefer_source_dependence": ["source_free", "adaptable"]},
            "continuation_or_revision": {"prefer_source_dependence": ["source_bound", "adaptable"]},
            "hybrid_adaptation": {"prefer_source_dependence": ["source_free", "adaptable", "source_bound"]},
        },
    }


def _read_primary_or_v1(
    primary_path: Path,
    fallback_loader: Any,
) -> tuple[dict[str, Any], str | None]:
    if primary_path.exists():
        return _read_json_payload(primary_path)
    return fallback_loader()


def _v1_arc_ranges(run_path: Path) -> list[dict[str, Any]]:
    payload, error = _read_json_payload(run_path / "arcs" / "sub_arcs.json")
    if error:
        return []
    ranges: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("arcs") or [], start=1):
        if not isinstance(raw, dict):
            continue
        chapters = {_coerce_int(item) for item in raw.get("chapters_included") or [] if _coerce_int(item)}
        chapter_range = _range_label(chapters)
        start = min(chapters) if chapters else 0
        end = max(chapters) if chapters else 0
        ranges.append(
            {
                "arc_id": f"arc_{index:03d}",
                "start": start,
                "end": end,
                "analysis_unit_range": raw.get("analysis_unit_range") or chapter_range,
                "source_chapter_range": raw.get("source_chapter_range") or chapter_range,
            }
        )
    return ranges


def _load_v1_run_manifest(run_path: Path) -> tuple[dict[str, Any], str | None]:
    source_manifest_path = run_path / "source_input_manifest.json"
    if not source_manifest_path.exists():
        return {}, None
    source_manifest, source_error = _read_json_payload(source_manifest_path)
    if source_error:
        return {}, f"run_manifest.json is missing and v1 source_input_manifest fallback is unavailable: {source_error}"
    run_summary, _ = _read_json_payload(run_path / "pipeline" / "run_summary.json")
    chapters: list[dict[str, Any]] = []
    source_indices: set[int] = set()
    for entry in _sorted_manifest_chapters(source_manifest):
        analysis_index = _coerce_int(entry.get("chapter_index"))
        if not analysis_index:
            continue
        source_index = _coerce_int(entry.get("original_chapter_index"), analysis_index)
        source_indices.add(source_index)
        chapters.append(
            {
                "chapter_index": analysis_index,
                "input_title": entry.get("source_title") or entry.get("normalized_title") or entry.get("title") or "",
                "original_chapter_index": source_index,
                "original_title": _source_title(entry, source_index),
                "source_title": entry.get("source_title") or "",
                "normalized_title": entry.get("normalized_title") or "",
                "part_index": entry.get("part_index"),
                "part_count": entry.get("part_count"),
                "part_start_char": entry.get("part_start_char"),
                "part_end_char": entry.get("part_end_char"),
                "text_length": entry.get("text_length"),
                "status": entry.get("boundary_status") or entry.get("status", "ok"),
            }
        )
    pipeline_status = str(run_summary.get("status") or "unknown")
    quality = run_summary.get("quality") if isinstance(run_summary.get("quality"), dict) else {}
    return {
        "schema_version": "generator_handoff.v1_adapter.run_manifest",
        "run_id": run_path.name,
        "work_title": source_manifest.get("work_title", ""),
        "source_path": source_manifest.get("source_path", ""),
        "run_status": "completed" if pipeline_status == "completed" else pipeline_status,
        "downstream_status": run_summary.get("current_stage", ""),
        "analyzer": "story_analyzer_v1",
        "chapter_count_basis": "source_chapters",
        "source_total_chapters": len(source_indices) or len(chapters),
        "analysis_unit_count": len(chapters),
        "successful_chapter_count": len(chapters),
        "failed_chapter_count": 0,
        "missing_required_outputs": [],
        "llm_health": {"status": "passed", "unrecovered_failed_target_count": 0},
        "quality": quality,
        "chapters": chapters,
        "arc_ranges": _v1_arc_ranges(run_path),
    }, None


def _load_v1_book_framework(run_path: Path) -> tuple[dict[str, Any], str | None]:
    source_manifest_path = run_path / "source_input_manifest.json"
    if not source_manifest_path.exists():
        return {}, None
    source_manifest, source_error = _read_json_payload(source_manifest_path)
    if source_error:
        return {}, f"book_framework.json is missing and v1 source_input_manifest fallback is unavailable: {source_error}"
    book_modules, _ = _read_json_payload(run_path / "modules" / "book_modules.json")
    module_catalog, _ = _read_json_payload(run_path / "modules" / "module_catalog.json")
    chapters = _sorted_manifest_chapters(source_manifest)
    source_indices = {
        _coerce_int(entry.get("original_chapter_index"), _coerce_int(entry.get("chapter_index")))
        for entry in chapters
        if _coerce_int(entry.get("chapter_index"))
    }
    return {
        "schema_version": "generator_handoff.v1_adapter.book_framework",
        "work_title": source_manifest.get("work_title", ""),
        "source_total_chapters": len(source_indices) or len(chapters),
        "analysis_unit_count": len(chapters),
        "module_catalog_status": module_catalog.get("status", ""),
        "book_modules": book_modules.get("modules", []),
        "source_refs": ["modules/book_modules.json", "modules/module_catalog.json"],
    }, None


def _module_pack_name(module: dict[str, Any]) -> str:
    module_type = str(module.get("module_type") or "")
    module_id = str(module.get("module_id") or "")
    if module_type == "world":
        return "worldbuilding_module"
    if module_type == "relationship":
        return "relationship_network_module"
    if module_type == "rhythm":
        return "emotional_rhythm_module"
    if module_type in {"information", "theme"}:
        return "narrative_thread_module"
    if module_type in {"plot", "character"}:
        return "core_conflict_module"
    if "power" in module_id or "item" in module_id:
        return "power_item_system_module"
    return "narrative_thread_module"


def _load_v1_modules(run_path: Path) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for rel_path in ("modules/book_modules.json", "modules/arc_modules.json", "modules/chapter_modules.json"):
        payload, error = _read_json_payload(run_path / rel_path)
        if error:
            continue
        for module in payload.get("modules") or []:
            if isinstance(module, dict):
                snapshot = dict(module)
                snapshot["source_file"] = rel_path
                modules.append(snapshot)
    return modules


def _v1_module_packs(run_path: Path) -> dict[str, Any]:
    packs: dict[str, dict[str, Any]] = {}
    for module in _load_v1_modules(run_path):
        pack_name = _module_pack_name(module)
        pack = packs.setdefault(pack_name, {"source": "story_analyzer_v1.modules", "modules": []})
        if len(pack["modules"]) < 30:
            pack["modules"].append(module)
    return packs


def _load_v1_generation_profiles(run_path: Path) -> tuple[dict[str, Any], str | None]:
    major_payload, _ = _read_json_payload(run_path / "arcs" / "major_arcs.json")
    sub_arcs_path = run_path / "arcs" / "sub_arcs.json"
    if not sub_arcs_path.exists():
        return {}, None
    sub_payload, sub_error = _read_json_payload(sub_arcs_path)
    if sub_error:
        return {}, f"generation_profiles.json is missing and v1 sub_arcs fallback is unavailable: {sub_error}"
    sub_arcs_raw = [item for item in sub_payload.get("arcs") or [] if isinstance(item, dict)]
    sub_ids_by_parent: dict[str, list[str]] = {}
    for index, raw in enumerate(sub_arcs_raw, start=1):
        sub_id = raw.get("arc_candidate_id") or f"sub_arc_{index:03d}"
        parent_id = str(raw.get("parent_candidate_id") or "")
        sub_ids_by_parent.setdefault(parent_id, []).append(str(sub_id))
    major_arcs: list[dict[str, Any]] = []
    for index, raw in enumerate(major_payload.get("arcs") or [], start=1):
        if not isinstance(raw, dict):
            continue
        major_id = raw.get("arc_candidate_id") or f"major_arc_{index:03d}"
        chapters = {_coerce_int(item) for item in raw.get("chapters_included") or [] if _coerce_int(item)}
        chapter_range = _range_label(chapters)
        sub_arc_ids = sub_ids_by_parent.get(str(major_id), [])
        major_arcs.append(
            {
                "major_arc_id": major_id,
                "major_arc_title": raw.get("arc_title") or raw.get("stage_goal") or major_id,
                "source_chapter_range": raw.get("source_chapter_range") or chapter_range,
                "analysis_unit_range": raw.get("analysis_unit_range") or chapter_range,
                "sub_arc_ids": sub_arc_ids,
                "structural_function": raw.get("stage_goal", ""),
                "arc_goal": raw.get("stage_goal", ""),
                "core_conflict": raw.get("dominant_conflict", ""),
                "turning_point": raw.get("turning_points", []),
                "emotion_curve": raw.get("dominant_reader_experience", ""),
            }
        )
    if not major_arcs and sub_arcs_raw:
        major_arcs.append(
            {
                "major_arc_id": "major_arc_001",
                "major_arc_title": "v1_confirmed_arc_hierarchy",
                "source_chapter_range": _combine_ranges([
                    _range_label({_coerce_int(item) for item in raw.get("chapters_included") or [] if _coerce_int(item)})
                    for raw in sub_arcs_raw
                ]),
                "analysis_unit_range": _combine_ranges([
                    _range_label({_coerce_int(item) for item in raw.get("chapters_included") or [] if _coerce_int(item)})
                    for raw in sub_arcs_raw
                ]),
                "sub_arc_ids": [
                    str(raw.get("arc_candidate_id") or f"sub_arc_{index:03d}")
                    for index, raw in enumerate(sub_arcs_raw, start=1)
                ],
            }
        )
    modules = _load_v1_modules(run_path)
    return {
        "schema_version": "generator_handoff.v1_adapter.generation_profiles",
        "arc_hierarchy": {"major_arcs": major_arcs},
        "usage_profiles": {
            "structure_only": {
                "profile_type": "structure_only",
                "source": "story_analyzer_v1.modules",
                "module_count": len(modules),
                "transferable_modules": [
                    module
                    for module in modules
                    if module.get("source_specificity") in {"transferable", "hybrid"}
                ][:40],
            },
            "source_story_continuation": {"profile_type": "source_story_continuation"},
            "hybrid_adaptation": {
                "profile_type": "hybrid_adaptation",
                "module_packs": _v1_module_packs(run_path),
            },
        },
    }, None


def _load_v1_quality_report(run_path: Path, *, report_type: str) -> tuple[dict[str, Any], str | None]:
    quality_path = run_path / "quality" / "quality_report.json"
    if not quality_path.exists():
        return {}, None
    quality, quality_error = _read_json_payload(quality_path)
    if quality_error:
        return {}, f"{report_type} fallback quality report is unavailable: {quality_error}"
    status = str(quality.get("status") or "unknown")
    blocking_count = _coerce_int(quality.get("blocking_issue_count"))
    return {
        "schema_version": f"generator_handoff.v1_adapter.{report_type}",
        "status": status,
        "blocking_issue_count": blocking_count,
        "blocking_leak_count": blocking_count if report_type == "source_leak_report" else 0,
        "warning_count": _coerce_int(quality.get("warning_count")),
        "abstraction_quality_score": 1.0 if status == "passed" else 0.0,
        "source_quality_report_ref": "quality/quality_report.json",
    }, None


def _load_v1_registry(run_path: Path) -> tuple[dict[str, Any], str | None]:
    registry_path = run_path / "trackers" / "foreshadowing_tracker.json"
    if not registry_path.exists():
        return {}, None
    registry, registry_error = _read_json_payload(registry_path)
    if registry_error:
        return {}, f"foreshadowing_registry.json is missing and v1 tracker fallback is unavailable: {registry_error}"
    return registry, None


def _compiler_report(status: str, warnings: list[dict[str, str]], errors: list[dict[str, str]], output_files: list[str]) -> dict[str, Any]:
    return {
        "schema_version": COMPILER_REPORT_VERSION,
        "compiler_status": status,
        "compiled_at": now_iso(),
        "blocking_error_count": len(errors),
        "warning_count": len(warnings),
        "blocking_errors": errors,
        "warnings": warnings,
        "output_files": output_files,
    }


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _clear_stale_generator_handoff_outputs(handoff_dir: Path) -> None:
    stale_files = [
        "unified_generator_handoff.validated.json",
        "unified_generator_handoff.repaired.json",
        "validation_report.json",
        "validation_report.md",
        "repair_history.json",
        "handoff_failed_report.json",
        "handoff_failed_report.md",
    ]
    for name in stale_files:
        _unlink_if_exists(handoff_dir / name)
    for pattern in ("repair_attempt_*.json", "repair_attempt_*_report.md"):
        for path in handoff_dir.glob(pattern):
            if path.is_file():
                _unlink_if_exists(path)


def compile_generator_handoff(output_dir: str | Path, *, work_title: str = "") -> dict[str, Any]:
    """Compile analyzer outputs into one generator-facing handoff payload.

    The compiler is intentionally deterministic and file-bound: it does not call
    an LLM and it writes only under ``output_dir/generator_handoff``.
    """
    run_path = Path(output_dir)
    handoff_dir = run_path / DEFAULT_OUTPUT_DIRNAME
    handoff_dir.mkdir(parents=True, exist_ok=True)
    _clear_stale_generator_handoff_outputs(handoff_dir)

    manifest, manifest_error = _read_primary_or_v1(run_path / "run_manifest.json", lambda: _load_v1_run_manifest(run_path))
    book_framework, book_framework_error = _read_primary_or_v1(run_path / "book_framework.json", lambda: _load_v1_book_framework(run_path))
    profiles, profiles_error = _read_primary_or_v1(run_path / "generation_profiles.json", lambda: _load_v1_generation_profiles(run_path))
    source_leak_report, source_leak_report_error = _read_primary_or_v1(
        run_path / "source_leak_report.json",
        lambda: _load_v1_quality_report(run_path, report_type="source_leak_report"),
    )
    abstraction_quality_report, abstraction_quality_report_error = _read_primary_or_v1(
        run_path / "abstraction_quality_report.json",
        lambda: _load_v1_quality_report(run_path, report_type="abstraction_quality_report"),
    )
    raw_registry, raw_registry_error = _read_primary_or_v1(run_path / "foreshadowing_registry.json", lambda: _load_v1_registry(run_path))
    chapter_analyses, chapter_analysis_errors = _load_chapter_analyses(run_path)
    arc_files, arc_errors = _load_arc_files(run_path)
    chapter_frameworks, chapter_framework_errors = _load_chapter_frameworks(run_path)
    chapter_framework_files = [path for _, path, _ in chapter_frameworks]

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    errors.extend(chapter_analysis_errors)
    errors.extend(arc_errors)
    errors.extend(chapter_framework_errors)
    required_payloads = {
        "run_manifest.json": (manifest, manifest_error),
        "book_framework.json": (book_framework, book_framework_error),
        "generation_profiles.json": (profiles, profiles_error),
        "foreshadowing_registry.json": (raw_registry, raw_registry_error),
        "source_leak_report.json": (source_leak_report, source_leak_report_error),
        "abstraction_quality_report.json": (abstraction_quality_report, abstraction_quality_report_error),
    }
    for name in REQUIRED_JSON_INPUTS:
        payload, read_error = required_payloads[name]
        if read_error:
            errors.append({"code": "INVALID_REQUIRED_INPUT", "message": f"{name} is invalid: {read_error}", "path": name})
        elif not payload:
            errors.append({"code": "MISSING_REQUIRED_INPUT", "message": f"{name} is required", "path": name})
    if not chapter_analyses:
        errors.append({"code": "MISSING_CHAPTER_ANALYSES", "message": "chapter analysis files are required", "path": "chapters"})
    if not arc_files:
        errors.append({"code": "MISSING_ARC_ANALYSES", "message": "arc analysis files are required", "path": "arcs"})
    expected_analysis_indices = _expected_analysis_unit_indices(manifest)
    expected_arc_indices = _expected_arc_indices(manifest)
    analysis_indices = _file_index_set(chapter_analyses)
    framework_indices = _file_index_set(chapter_frameworks)
    arc_indices = _file_index_set(arc_files)
    _validate_expected_file_coverage(
        expected_indices=expected_analysis_indices,
        actual_indices=analysis_indices,
        missing_code="MISSING_CHAPTER_ANALYSIS",
        extra_code="UNEXPECTED_CHAPTER_ANALYSIS",
        path="chapters",
        errors=errors,
    )
    _validate_expected_file_coverage(
        expected_indices=expected_arc_indices,
        actual_indices=arc_indices,
        missing_code="MISSING_ARC_ANALYSIS",
        extra_code="UNEXPECTED_ARC_ANALYSIS",
        path="arcs",
        errors=errors,
    )
    _validate_expected_file_coverage(
        expected_indices=expected_analysis_indices,
        actual_indices=framework_indices,
        missing_code="MISSING_CHAPTER_FRAMEWORK",
        extra_code="UNEXPECTED_CHAPTER_FRAMEWORK",
        path="chapters",
        errors=errors,
    )
    missing_framework_indices = sorted(index for index in analysis_indices if index not in framework_indices)
    if not chapter_framework_files or missing_framework_indices:
        errors.append(
            {
                "code": "MISSING_CHAPTER_FRAMEWORK",
                "message": f"chapter framework files are required for every analysis unit; missing={missing_framework_indices}",
                "path": "chapters",
            }
        )

    raw_source_index: dict[str, Any] | None = None
    try:
        if not raw_source_index_path(run_path).exists():
            build_raw_source_index(run_path)
        raw_source_index = load_raw_source_index(run_path)
    except (OSError, ValueError) as exc:
        warnings.append(
            {
                "code": "RAW_SOURCE_INDEX_UNAVAILABLE",
                "message": f"raw source index unavailable; source_reference_index will use v1 fallback: {exc}",
                "path": "evidence/raw_source_index.json",
            }
        )

    source_map = _build_source_map(manifest)
    source_reference_index = _build_source_reference_index(
        output_dir=run_path,
        manifest=manifest,
        chapter_analyses=chapter_analyses,
        arc_files=arc_files,
        raw_source_index=raw_source_index,
    )
    chapter_blueprints = _build_chapter_blueprints(chapter_analyses=chapter_analyses, manifest=manifest)
    arc_hierarchy = _build_arc_hierarchy(profiles=profiles, arc_files=arc_files)
    registry = _sanitize_generator_content(_normalize_foreshadowing_registry(raw_registry))
    generator_book_framework = _sanitize_generator_content(book_framework)
    materials = _build_generator_materials(
        book_framework=generator_book_framework,
        profiles=profiles,
        arc_hierarchy=arc_hierarchy,
        chapter_blueprints=chapter_blueprints,
        foreshadowing_registry=registry,
        source_reference_index=source_reference_index,
        chapter_analyses=chapter_analyses,
        arc_files=arc_files,
    )
    quality_gate = _build_quality_gate(
        manifest=manifest,
        source_leak_report=source_leak_report,
        abstraction_quality_report=abstraction_quality_report,
        arc_count=len(arc_files),
    )
    if not materials:
        errors.append({"code": "EMPTY_GENERATOR_MATERIALS", "message": "generator_materials must not be empty", "path": "generator_materials"})
    for material in materials:
        if not material.get("source_refs"):
            errors.append(
                {
                    "code": "MATERIAL_WITHOUT_SOURCE_REFS",
                    "message": f"{material.get('material_id', 'unknown')} has no source_refs",
                    "path": "generator_materials",
                }
            )

    status = "failed" if errors else "compiled"
    unified = {
        "handoff_version": HANDOFF_VERSION,
        "handoff_status": status,
        "compiled_at": now_iso(),
        "work_identity": _build_work_identity(manifest, book_framework, work_title),
        "quality_gate": quality_gate,
        "source_map": source_map,
        "book_framework": {
            "schema_version": "generator_handoff.book_framework_ref.v1",
            "content": generator_book_framework,
            "source_refs": _all_arc_refs(arc_files) or _all_chapter_refs(chapter_analyses),
        },
        "arc_hierarchy": arc_hierarchy,
        "chapter_blueprints": chapter_blueprints,
        "foreshadowing_registry": registry,
        "generator_materials": materials,
        "selection_metadata": _build_selection_metadata(),
        "validator_summary": {
            "status": "not_run",
            "report_ref": "validator_report.json",
        },
        "repair_history": [],
        "source_reference_index_ref": "source_reference_index.json",
    }

    output_files = [
        "unified_generator_handoff.json",
        "source_reference_index.json",
        "compiler_report.json",
    ]
    report = _compiler_report(status, warnings, errors, output_files)
    write_json(handoff_dir / "unified_generator_handoff.json", unified)
    write_json(handoff_dir / "source_reference_index.json", source_reference_index)
    write_json(handoff_dir / "compiler_report.json", report)
    return report
