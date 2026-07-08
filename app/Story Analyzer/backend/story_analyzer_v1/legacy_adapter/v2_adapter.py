from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re

from ..analysis.semantic_normalizer import RAW_SEMANTIC_SCHEMA_VERSION, semantic_input_dir
from ..arcs.v2_hierarchy_import import import_v2_arc_hierarchy
from ..config import DEFAULT_ENCODING, ensure_dir
from ..ingestion.source_manifest_builder import load_source_manifest
from ..models.semantic import RawSemanticChapterInput
from ..models.source import ChapterSource


LEGACY_ADAPTER_REPORT_SCHEMA_VERSION = "story_analyzer.legacy_v2_adapter_report.v1"
LEGACY_ADAPTER_ID = "legacy_v2_adapter_v1"
LEGACY_ADAPTER_REPORT_FILENAME = "legacy_v2_adapter_report.json"

SUPPORTED_FIELDS = [
    "run_manifest.chapters[].content_sha256",
    "chapter_analysis.summary",
    "chapter_analysis.plot_nodes",
    "chapter_analysis.chapter_function",
    "chapter_analysis.reader_emotion",
    "chapter_analysis.reader_emotion_intensity",
    "chapter_analysis.conflict",
    "chapter_analysis.information_release",
    "chapter_analysis.character_arc",
    "chapter_analysis.style_pacing",
    "chapter_analysis.identified_macros",
    "foreshadowing",
    "built_chapter_frameworks[].modules",
    "next_chapter_pack.previous_summary",
]

UNSUPPORTED_FIELDS = [
    "precise source line evidence",
    "arc-level analysis",
    "book-level framework",
    "full cross-chapter tracker reconciliation",
    "generation profile package",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def _relative_ref(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_legacy_output_dir(legacy_run_dir: str | Path) -> Path:
    root = Path(legacy_run_dir)
    candidates = [root, root / "output", root / "output_clean"]
    for candidate in candidates:
        if (candidate / "run_manifest.json").exists() or (candidate / "full_book_bundle.json").exists():
            return candidate
    return root


def _import_legacy_arc_hierarchy(legacy_root: Path, run_path: Path) -> dict[str, Any]:
    profiles_path = legacy_root / "generation_profiles.json"
    if profiles_path.exists():
        return import_v2_arc_hierarchy(run_path, profiles_path)
    bundle_path = legacy_root / "full_book_bundle.json"
    if bundle_path.exists():
        try:
            bundle = _read_json(bundle_path)
        except (OSError, json.JSONDecodeError):
            return {"status": "missing", "reason": "full_book_bundle_unreadable"}
        profiles = bundle.get("generation_profiles") if isinstance(bundle, dict) else None
        if isinstance(profiles, dict):
            return import_v2_arc_hierarchy(run_path, profiles)
    return {"status": "missing", "reason": "generation_profiles_not_found"}


def _parse_maybe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _strip_new_term_marker(value: str) -> str:
    cleaned = value.replace("[NEW_TERM]", "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([，。；：、,.!?])", r"\1", cleaned)
    return cleaned.strip()


def _manifest_by_chapter(legacy_root: Path) -> dict[int, dict[str, Any]]:
    manifest_path = legacy_root / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return {}
    chapters = manifest.get("chapters", [])
    result = {}
    for item in chapters if isinstance(chapters, list) else []:
        try:
            index = int(item.get("chapter_index"))
        except (TypeError, ValueError):
            continue
        result[index] = item
    return result


def _legacy_chapter_path(legacy_root: Path, chapter_index: int, suffix: str) -> Path:
    filename = f"chapter_{chapter_index:03d}_{suffix}.json"
    chapters_path = legacy_root / "chapters" / filename
    if chapters_path.exists():
        return chapters_path
    return legacy_root / filename


def _load_legacy_chapter_payload(legacy_root: Path, chapter_index: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    analysis_path = _legacy_chapter_path(legacy_root, chapter_index, "analysis")
    framework_path = _legacy_chapter_path(legacy_root, chapter_index, "framework")
    next_pack_path = _legacy_chapter_path(legacy_root, chapter_index, "next_pack")
    if not analysis_path.exists():
        raise FileNotFoundError(analysis_path)

    analysis = _read_json(analysis_path)
    framework = _read_json(framework_path) if framework_path.exists() else {}
    next_pack = _read_json(next_pack_path) if next_pack_path.exists() else {}
    refs = {
        "analysis_ref": _relative_ref(analysis_path, legacy_root),
        "framework_ref": _relative_ref(framework_path, legacy_root) if framework_path.exists() else "",
        "next_pack_ref": _relative_ref(next_pack_path, legacy_root) if next_pack_path.exists() else "",
    }
    return analysis, framework, next_pack, refs


def _chapter_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    if isinstance(analysis.get("chapter_analysis"), dict):
        return analysis["chapter_analysis"]
    report = _parse_maybe_json(analysis.get("analysis_report_json")) or _parse_maybe_json(analysis.get("analysis_report"))
    if isinstance(report.get("chapter_analysis"), dict):
        return report["chapter_analysis"]
    if isinstance(analysis.get("chapter"), dict):
        return analysis["chapter"]
    return analysis


def _framework_package(framework: dict[str, Any]) -> dict[str, Any]:
    return _parse_maybe_json(framework.get("framework_package_json")) or _parse_maybe_json(framework.get("framework_package")) or framework


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _strip_new_term_marker(value)
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("summary", "content", "label", "surface", "deep", "change", "name"):
            if str(value.get(key, "")).strip():
                return _strip_new_term_marker(str(value[key]))
    return _strip_new_term_marker(json.dumps(value, ensure_ascii=False))


def _normalize_evidence_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _events_from_plot_nodes(chapter: ChapterSource, chapter_payload: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    event_sources = []
    for field in ("events", "plot_nodes", "plot_points"):
        event_sources.extend(_as_list(chapter_payload.get(field)))

    events = []
    for index, item in enumerate(event_sources, start=1):
        summary = _stringify(item)
        if not summary:
            continue
        evidence_refs = _normalize_evidence_refs(item.get("evidence_refs")) if isinstance(item, dict) else []
        if not evidence_refs and "legacy_missing_event_evidence" not in warnings:
            warnings.append("legacy_missing_event_evidence")
        events.append(
            {
                "event_id": f"{chapter.chapter_id}_legacy_event_{index:03d}",
                "summary": summary,
                "evidence_refs": evidence_refs,
                "source": "book_analyzer_v2",
            }
        )
    return events


def _character_changes(chapter_payload: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    changes = []
    for item in _as_list(chapter_payload.get("character_arc")):
        if not isinstance(item, dict):
            continue
        character = _stringify(item.get("character"))
        if not character:
            warnings.append("legacy_character_arc_missing_character")
            continue
        evidence_refs = _normalize_evidence_refs(item.get("evidence_refs"))
        changes.append(
            {
                "character": character,
                "before_state": _stringify(item.get("before_state")),
                "after_state": _stringify(item.get("change") or item.get("after_state") or item.get("arc_stage")),
                "trigger": _stringify(item.get("trigger") or item.get("arc_stage")),
                "evidence_refs": evidence_refs,
                "source": "book_analyzer_v2.character_arc",
            }
        )
    return changes


def _information_changes(chapter_payload: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    changes = []
    for index, item in enumerate(_as_list(chapter_payload.get("information_release")), start=1):
        if not isinstance(item, dict):
            content = _stringify(item)
            reveal_method = ""
            evidence_refs = []
        else:
            content = _stringify(item.get("content") or item.get("info_type"))
            reveal_method = _stringify(item.get("reveal_method"))
            evidence_refs = _normalize_evidence_refs(item.get("evidence_refs"))
        if not content:
            continue
        if not evidence_refs and "legacy_missing_information_evidence" not in warnings:
            warnings.append("legacy_missing_information_evidence")
        changes.append(
            {
                "information_id": f"legacy_info_{index:03d}",
                "content": content,
                "reveal_method": reveal_method,
                "evidence_refs": evidence_refs,
                "source": "book_analyzer_v2.information_release",
            }
        )
    return changes


def _label(value: Any) -> dict[str, Any]:
    text = _stringify(value)
    return {"label": text, "evidence_refs": []} if text else {}


def _conflict_label(chapter_payload: dict[str, Any]) -> dict[str, Any]:
    conflicts = _as_list(chapter_payload.get("conflict"))
    if not conflicts:
        return {}
    first = conflicts[0]
    if isinstance(first, dict):
        surface = _stringify(first.get("surface") or first.get("conflict_type"))
        deep = _stringify(first.get("deep"))
        label = " / ".join(part for part in [surface, deep] if part)
        return {"label": label, "evidence_refs": [], "legacy_payload": first}
    return _label(first)


def _pacing_label(chapter_payload: dict[str, Any]) -> dict[str, Any]:
    pacing = chapter_payload.get("style_pacing")
    if not isinstance(pacing, dict):
        return _label(pacing)
    label = _stringify(pacing.get("pacing"))
    result = {"label": label, "evidence_refs": []} if label else {}
    if "tension_level" in pacing:
        result["tension_level"] = pacing["tension_level"]
    if pacing.get("style_features"):
        result["style_features"] = pacing["style_features"]
    return result


def _information_method_label(chapter_payload: dict[str, Any]) -> dict[str, Any]:
    releases = _as_list(chapter_payload.get("information_release"))
    for item in releases:
        if isinstance(item, dict) and _stringify(item.get("reveal_method")):
            return {"label": _stringify(item.get("reveal_method")), "evidence_refs": [], "legacy_payload": item}
    return {}


def _structural_analysis(chapter_payload: dict[str, Any]) -> dict[str, Any]:
    structural = {
        "chapter_function": _label(chapter_payload.get("chapter_function")),
        "dominant_reader_experience": _label(chapter_payload.get("reader_emotion")),
        "conflict_function": _conflict_label(chapter_payload),
        "pacing_density": _pacing_label(chapter_payload),
        "information_release_method": _information_method_label(chapter_payload),
        "ending_hook_type": {},
        "macro_component_ids": [str(item) for item in _as_list(chapter_payload.get("identified_macros")) if str(item).strip()],
    }
    intensity = chapter_payload.get("reader_emotion_intensity")
    if intensity is not None and structural["dominant_reader_experience"]:
        structural["dominant_reader_experience"]["intensity"] = intensity
    return structural


def _transferable_patterns(framework: dict[str, Any]) -> list[dict[str, Any]]:
    package = _framework_package(framework)
    patterns = []
    for framework_item in _as_list(package.get("built_chapter_frameworks")):
        if not isinstance(framework_item, dict):
            continue
        for module in _as_list(framework_item.get("modules")):
            if not isinstance(module, dict):
                continue
            module_id = _stringify(module.get("module_id"))
            content = _stringify(module.get("content"))
            if not module_id or not content:
                continue
            patterns.append(
                {
                    "pattern_id": f"legacy_module_{module_id}",
                    "module_id": module_id,
                    "description": content,
                    "source": "book_analyzer_v2.framework_package",
                }
            )
    return patterns


def _candidate_action(status: str) -> str:
    normalized = status.lower().strip()
    if normalized in {"resolved", "resolve"}:
        return "resolve"
    if normalized in {"abandoned", "abandon"}:
        return "abandon"
    if normalized in {"surfaced", "surface"}:
        return "surface"
    if normalized in {"reinforced", "reinforce"}:
        return "reinforce"
    return "plant"


def _tracker_candidates(
    chapter: ChapterSource,
    analysis: dict[str, Any],
    chapter_payload: dict[str, Any],
    warnings: list[str],
) -> list[dict[str, Any]]:
    candidates = []
    foreshadowing = _as_list(analysis.get("foreshadowing")) + _as_list(chapter_payload.get("foreshadowing"))
    for index, item in enumerate(foreshadowing, start=1):
        if isinstance(item, dict):
            content = _stringify(item.get("content") or item.get("summary"))
            legacy_id = _stringify(item.get("id"))
            status = _stringify(item.get("status"))
            evidence_refs = _normalize_evidence_refs(item.get("evidence_refs"))
        else:
            content = _stringify(item)
            legacy_id = ""
            status = ""
            evidence_refs = []
        if not content:
            continue
        if not evidence_refs and "legacy_missing_tracker_evidence" not in warnings:
            warnings.append("legacy_missing_tracker_evidence")
        if legacy_id and "legacy_tracker_id_not_reused" not in warnings:
            warnings.append("legacy_tracker_id_not_reused")
        candidates.append(
            {
                "candidate_id": f"{chapter.chapter_id}_legacy_foreshadowing_{index:03d}",
                "candidate_type": "foreshadowing",
                "content": content,
                "candidate_action": _candidate_action(status),
                "possible_existing_item_refs": [],
                "evidence_refs": evidence_refs,
                "confidence_score": 0.45 if not evidence_refs else 0.6,
            }
        )

    if not candidates:
        warnings.append("legacy_tracker_candidates_missing")
    return candidates


def _summary(chapter_payload: dict[str, Any], next_pack: dict[str, Any], warnings: list[str]) -> str:
    summary = _stringify(chapter_payload.get("summary") or chapter_payload.get("chapter_summary"))
    if summary:
        return summary
    fallback = _stringify(next_pack.get("previous_summary"))
    if fallback:
        warnings.append("legacy_summary_from_next_pack")
        return fallback
    warnings.append("legacy_summary_missing")
    return ""


def _confidence(events: list[dict[str, Any]], summary: str, structural: dict[str, Any], warnings: list[str]) -> float:
    score = 0.35
    if events:
        score += 0.15
    if summary:
        score += 0.1
    if structural.get("chapter_function") and structural.get("dominant_reader_experience"):
        score += 0.1
    if "legacy_missing_event_evidence" in warnings:
        score -= 0.05
    if "legacy_summary_missing" in warnings:
        score -= 0.1
    return max(0.1, min(0.65, score))


def _raw_semantic_from_legacy(
    chapter: ChapterSource,
    analysis: dict[str, Any],
    framework: dict[str, Any],
    next_pack: dict[str, Any],
    manifest_entry: dict[str, Any],
    refs: dict[str, str],
) -> tuple[RawSemanticChapterInput, list[str]]:
    warnings: list[str] = ["legacy_adapter=v2", "legacy_low_confidence_without_source_evidence"]
    chapter_payload = _chapter_analysis(analysis)
    summary = _summary(chapter_payload, next_pack, warnings)
    events = _events_from_plot_nodes(chapter, chapter_payload, warnings)
    character_changes = _character_changes(chapter_payload, warnings)
    information_changes = _information_changes(chapter_payload, warnings)
    structural = _structural_analysis(chapter_payload)
    tracker_candidates = _tracker_candidates(chapter, analysis, chapter_payload, warnings)

    legacy_sha = _stringify(manifest_entry.get("content_sha256"))
    if legacy_sha:
        if legacy_sha != chapter.text_sha256:
            warnings.append("legacy_source_hash_mismatch_or_unverified")
    else:
        warnings.append("legacy_source_hash_unavailable")

    raw = RawSemanticChapterInput.model_validate(
        {
            "schema_version": RAW_SEMANTIC_SCHEMA_VERSION,
            "chapter_id": chapter.chapter_id,
            "chapter_index": chapter.chapter_index,
            "analyzer_id": LEGACY_ADAPTER_ID,
            "source_text_sha256": chapter.text_sha256,
            "chapter_summary": summary,
            "story_facts": {
                "events": events,
                "character_state_changes": character_changes,
                "relationship_changes": [],
                "world_facts_added": [],
                "information_state_changes": information_changes,
            },
            "structural_analysis": structural,
            "transferable_patterns": _transferable_patterns(framework),
            "tracker_candidates": tracker_candidates,
            "boundary_signals": {},
            "quality_notes": [*warnings, *(f"{key}={value}" for key, value in refs.items() if value)],
            "confidence_score": _confidence(events, summary, structural, warnings),
        }
    )
    return raw, warnings


def adapt_legacy_v2_outputs(
    legacy_run_dir: str | Path,
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    legacy_root = _resolve_legacy_output_dir(legacy_run_dir)
    manifest = load_source_manifest(run_path)
    legacy_manifest = _manifest_by_chapter(legacy_root)
    semantic_dir = ensure_dir(Path(output_dir) if output_dir is not None else semantic_input_dir(run_path))
    imported_arc_hierarchy = _import_legacy_arc_hierarchy(legacy_root, run_path)

    chapter_reports = []
    output_refs = []
    warning_count = 0
    adapted_count = 0
    skipped_count = 0
    missing_count = 0
    failed_count = 0

    for chapter in manifest.chapters:
        out_path = semantic_dir / f"{chapter.chapter_id}.json"
        if out_path.exists() and not overwrite:
            skipped_count += 1
            chapter_reports.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "chapter_index": chapter.chapter_index,
                    "status": "skipped_existing",
                    "output_ref": _relative_ref(out_path, run_path),
                    "warnings": ["semantic_input_exists"],
                }
            )
            output_refs.append(_relative_ref(out_path, run_path))
            warning_count += 1
            continue

        try:
            analysis, framework, next_pack, refs = _load_legacy_chapter_payload(legacy_root, chapter.chapter_index)
        except FileNotFoundError as exc:
            missing_count += 1
            warnings = ["legacy_analysis_file_missing"]
            chapter_reports.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "chapter_index": chapter.chapter_index,
                    "status": "missing",
                    "legacy_ref": _relative_ref(Path(exc.filename), legacy_root) if exc.filename else "",
                    "warnings": warnings,
                }
            )
            warning_count += len(warnings)
            continue
        except (OSError, json.JSONDecodeError) as exc:
            failed_count += 1
            chapter_reports.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "chapter_index": chapter.chapter_index,
                    "status": "failed",
                    "error": str(exc),
                    "warnings": [],
                }
            )
            continue

        try:
            raw, warnings = _raw_semantic_from_legacy(
                chapter,
                analysis,
                framework,
                next_pack,
                legacy_manifest.get(chapter.chapter_index, {}),
                refs,
            )
        except ValueError as exc:
            failed_count += 1
            chapter_reports.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "chapter_index": chapter.chapter_index,
                    "status": "failed",
                    "error": str(exc),
                    "warnings": [],
                }
            )
            continue

        _write_json(out_path, raw.model_dump(mode="json"))
        adapted_count += 1
        output_ref = _relative_ref(out_path, run_path)
        output_refs.append(output_ref)
        warning_count += len(warnings)
        chapter_reports.append(
            {
                "chapter_id": chapter.chapter_id,
                "chapter_index": chapter.chapter_index,
                "status": "adapted",
                "legacy_ref": refs.get("analysis_ref", ""),
                "output_ref": output_ref,
                "warnings": warnings,
            }
        )

    if failed_count:
        status = "failed" if adapted_count + skipped_count == 0 else "partial"
    elif missing_count:
        status = "partial"
    else:
        status = "completed"

    report = {
        "schema_version": LEGACY_ADAPTER_REPORT_SCHEMA_VERSION,
        "adapter_id": LEGACY_ADAPTER_ID,
        "status": status,
        "created_at": _utc_now(),
        "legacy_run_dir": str(legacy_root),
        "run_dir": str(run_path),
        "semantic_input_dir": str(semantic_dir),
        "chapter_count": len(manifest.chapters),
        "adapted_count": adapted_count,
        "skipped_count": skipped_count,
        "missing_count": missing_count,
        "failed_count": failed_count,
        "warning_count": warning_count,
        "supported_fields": SUPPORTED_FIELDS,
        "unsupported_fields": UNSUPPORTED_FIELDS,
        "imported_arc_hierarchy": imported_arc_hierarchy,
        "output_refs": output_refs,
        "chapters": chapter_reports,
    }
    report_path = semantic_dir / LEGACY_ADAPTER_REPORT_FILENAME
    _write_json(report_path, report)
    report["adapter_report_ref"] = _relative_ref(report_path, run_path)
    _write_json(report_path, report)
    return report
