from __future__ import annotations

from pathlib import Path
from typing import Any
from dataclasses import dataclass
import json
import re

from story_analyzer_utils import chapter_sort_key

from ..config import DEFAULT_ENCODING
from ..ingestion.source_manifest_builder import load_source_manifest
from ..models.canonical import (
    BoundarySignals,
    CanonicalChapterAnalysis,
    CanonicalSourceMeta,
    StoryFacts,
    StructuralAnalysis,
)
from ..models.common import sha256_text
from ..models.semantic import RawSemanticChapterInput
from ..models.source import ChapterSource, SourceInputManifest
from ..models.trackers import TrackerCandidate


SEMANTIC_INPUT_DIRNAME = "semantic_chapter_inputs"
SEMANTIC_PROVIDER_RUN_FILENAME = "semantic_provider_run.json"
LEGACY_V2_ADAPTER_REPORT_FILENAME = "legacy_v2_adapter_report.json"
RAW_SEMANTIC_SCHEMA_VERSION = "story_analyzer.raw_semantic_chapter.v1"

_MARKER_ALIASES = {
    "event": "event",
    "character change": "character_change",
    "relationship change": "relationship_change",
    "world fact": "world_fact",
    "information": "information",
    "foreshadowing": "foreshadowing",
    "mystery": "mystery",
    "chapter function": "chapter_function",
    "reader experience": "reader_experience",
    "conflict": "conflict",
    "pacing": "pacing",
    "ending hook": "ending_hook",
    "boundary signal": "boundary_signal",
}
_BOUNDARY_SIGNAL_FIELDS = set(BoundarySignals.model_fields)


@dataclass(frozen=True)
class RawSemanticLoadResult:
    raw: RawSemanticChapterInput
    semantic_source: str
    semantic_input_ref: str


def semantic_input_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / SEMANTIC_INPUT_DIRNAME


def _source_meta(chapter: ChapterSource) -> CanonicalSourceMeta:
    return CanonicalSourceMeta(
        input_fingerprint_id=f"input_{chapter.chapter_id}_{chapter.text_sha256[:8]}",
        input_title=chapter.source_title,
        normalized_title=chapter.normalized_title,
        title_source=chapter.title_source,
        text_sha256=chapter.text_sha256,
        text_length=chapter.text_length,
        original_chapter_id=chapter.original_chapter_id,
        original_chapter_index=chapter.original_chapter_index,
        original_chapter_title=chapter.original_chapter_title,
        part_index=chapter.part_index,
        part_count=chapter.part_count,
        part_start_char=chapter.part_start_char,
        part_end_char=chapter.part_end_char,
    )


def _base_canonical(chapter: ChapterSource) -> CanonicalChapterAnalysis:
    return CanonicalChapterAnalysis(
        chapter_id=chapter.chapter_id,
        chapter_index=chapter.chapter_index,
        source=_source_meta(chapter),
        quality={
            "confidence_score": 1.0 if chapter.boundary_status == "ok" else 0.5,
            "chapter_boundary_status": chapter.boundary_status,
            "title_status": chapter.title_status,
            "schema_status": "ok",
            "character_consistency_status": "ok",
            "tracker_consistency_status": "ok",
            "requires_repair_pass": chapter.boundary_status == "failed" or chapter.title_status == "suspicious",
            "review_notes": [],
        },
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _relative_ref(path: Path, run_dir: str | Path | None) -> str:
    if run_dir is not None:
        try:
            return path.relative_to(Path(run_dir)).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _provider_manifest_marks_chapter(path: Path, chapter: ChapterSource) -> bool:
    manifest_path = path.parent / SEMANTIC_PROVIDER_RUN_FILENAME
    if not manifest_path.exists():
        return False
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return False
    for item in manifest.get("chapters", []):
        if item.get("chapter_id") == chapter.chapter_id and item.get("status") in {"produced", "skipped_existing"}:
            return True
    return False


def _legacy_adapter_report_marks_chapter(path: Path, chapter: ChapterSource) -> bool:
    report_path = path.parent / LEGACY_V2_ADAPTER_REPORT_FILENAME
    if not report_path.exists():
        return False
    try:
        report = _read_json(report_path)
    except (OSError, json.JSONDecodeError):
        return False
    if report.get("adapter_id") != "legacy_v2_adapter_v1":
        return False
    for item in report.get("chapters", []):
        if item.get("chapter_id") != chapter.chapter_id:
            continue
        if item.get("status") not in {"adapted", "skipped_existing"}:
            continue
        output_ref = item.get("output_ref", "")
        if output_ref and not output_ref.endswith(path.name):
            return False
        if item.get("status") == "adapted":
            return True
        try:
            raw = _read_json(path)
        except (OSError, json.JSONDecodeError):
            return False
        return raw.get("analyzer_id") == "legacy_v2_adapter_v1"
    return False


def _semantic_source_for_path(path: Path, chapter: ChapterSource) -> str:
    if _provider_manifest_marks_chapter(path, chapter):
        return "llm_provider"
    if _legacy_adapter_report_marks_chapter(path, chapter):
        return "legacy_v2_adapter"
    return "reviewed_json"


def _semantic_path_for_chapter(
    chapter: ChapterSource,
    semantic_input: str | Path | None,
    *,
    run_dir: str | Path | None = None,
) -> Path | None:
    root: Path | None
    if semantic_input is not None:
        root = Path(semantic_input)
    elif run_dir is not None and semantic_input_dir(run_dir).exists():
        root = semantic_input_dir(run_dir)
    else:
        root = None
    if root is None:
        return None
    if root.is_file():
        return root
    candidate = root / f"{chapter.chapter_id}.json"
    return candidate if candidate.exists() else None


def load_raw_semantic_input(
    chapter: ChapterSource,
    semantic_input: str | Path | None,
    *,
    run_dir: str | Path | None = None,
) -> RawSemanticChapterInput | None:
    result = load_raw_semantic_input_with_source(chapter, semantic_input, run_dir=run_dir)
    return result.raw if result is not None else None


def load_raw_semantic_input_with_source(
    chapter: ChapterSource,
    semantic_input: str | Path | None,
    *,
    run_dir: str | Path | None = None,
) -> RawSemanticLoadResult | None:
    path = _semantic_path_for_chapter(chapter, semantic_input, run_dir=run_dir)
    if path is None:
        return None
    data = _read_json(path)
    if "chapters" in data:
        matches = [item for item in data["chapters"] if item.get("chapter_id") == chapter.chapter_id]
        if not matches:
            return None
        data = matches[0]
    elif data.get("chapter_id") and data["chapter_id"] != chapter.chapter_id:
        return None
    data.setdefault("schema_version", RAW_SEMANTIC_SCHEMA_VERSION)
    data.setdefault("chapter_id", chapter.chapter_id)
    return RawSemanticLoadResult(
        raw=RawSemanticChapterInput.model_validate(data),
        semantic_source=_semantic_source_for_path(path, chapter),
        semantic_input_ref=_relative_ref(path, run_dir),
    )


def load_chapter_text(manifest: SourceInputManifest, chapter: ChapterSource) -> str:
    path = Path(chapter.source_file_path or manifest.source_path)
    if path.is_dir():
        files = sorted(
            [item for item in path.iterdir() if item.is_file() and item.suffix.lower() in {".txt", ".md"}],
            key=chapter_sort_key,
        )
        if chapter.chapter_index - 1 >= len(files):
            return ""
        path = files[chapter.chapter_index - 1]
    if not path.exists() or path.is_dir():
        return ""
    text = path.read_text(encoding=DEFAULT_ENCODING)
    if chapter.start_line is None or chapter.end_line is None:
        chapter_text = text.strip()
    else:
        lines = text.splitlines()
        start = max(0, chapter.start_line - 1)
        end = min(len(lines), chapter.end_line)
        chapter_text = "\n".join(lines[start:end]).strip()
    if chapter.part_start_char is not None or chapter.part_end_char is not None:
        start_char = chapter.part_start_char or 0
        end_char = chapter.part_end_char if chapter.part_end_char is not None else len(chapter_text)
        return chapter_text[start_char:end_char].strip()
    return chapter_text


def _evidence(chapter: ChapterSource, quote: str, line_number: int | None = None) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "chapter_id": chapter.chapter_id,
        "chapter_index": chapter.chapter_index,
        "quote": quote,
    }
    if line_number is not None:
        evidence["line_start"] = line_number
        evidence["line_end"] = line_number
    return evidence


def _dict_with_label(value: str, chapter: ChapterSource, line_number: int) -> dict[str, Any]:
    return {"label": value, "evidence_refs": [_evidence(chapter, value, line_number)]}


def _fallback_structural_value(label: str, chapter: ChapterSource, quote: str, line_number: int) -> dict[str, Any]:
    return {
        "label": label,
        "source": "deterministic_fallback",
        "confidence_score": 0.35,
        "evidence_refs": [_evidence(chapter, quote, line_number)],
    }


def _split_marker(line: str) -> tuple[str, str] | None:
    match = re.match(r"^\s*([A-Za-z ]{3,32})\s*:\s*(.+?)\s*$", line)
    if not match:
        return None
    key = " ".join(match.group(1).lower().split())
    marker = _MARKER_ALIASES.get(key)
    if marker is None:
        return None
    return marker, match.group(2).strip()


def _parts(value: str) -> list[str]:
    return [part.strip() for part in value.split("|")]


def extract_raw_semantics_from_text(chapter: ChapterSource, text: str) -> RawSemanticChapterInput:
    events: list[dict[str, Any]] = []
    character_changes: list[dict[str, Any]] = []
    relationship_changes: list[dict[str, Any]] = []
    world_facts: list[dict[str, Any]] = []
    information_changes: list[dict[str, Any]] = []
    tracker_candidates: list[dict[str, Any]] = []
    structural: dict[str, Any] = {}
    boundary_signals: dict[str, bool] = {}
    narrative_lines: list[tuple[int, str]] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=chapter.start_line or 1):
        line = raw_line.strip()
        if not line or line == chapter.normalized_title:
            continue
        marker = _split_marker(line)
        if marker is None:
            narrative_lines.append((line_number, line))
            continue
        kind, value = marker
        if kind == "event":
            events.append(
                {
                    "event_id": f"{chapter.chapter_id}_event_{len(events) + 1:03d}",
                    "summary": value,
                    "evidence_refs": [_evidence(chapter, value, line_number)],
                }
            )
        elif kind == "character_change":
            fields = _parts(value)
            character_changes.append(
                {
                    "character": fields[0] if len(fields) > 0 else "",
                    "before_state": fields[1] if len(fields) > 1 else "",
                    "after_state": fields[2] if len(fields) > 2 else "",
                    "trigger": fields[3] if len(fields) > 3 else "",
                    "evidence_refs": [_evidence(chapter, value, line_number)],
                }
            )
        elif kind == "relationship_change":
            fields = _parts(value)
            participants = [part.strip() for part in fields[0].split(",")] if fields else []
            relationship_changes.append(
                {
                    "participants": participants,
                    "from_state": fields[1] if len(fields) > 1 else "",
                    "to_state": fields[2] if len(fields) > 2 else "",
                    "trigger": fields[3] if len(fields) > 3 else "",
                    "evidence_refs": [_evidence(chapter, value, line_number)],
                }
            )
        elif kind == "world_fact":
            world_facts.append({"fact": value, "evidence_refs": [_evidence(chapter, value, line_number)]})
        elif kind == "information":
            information_changes.append({"content": value, "evidence_refs": [_evidence(chapter, value, line_number)]})
        elif kind in {"foreshadowing", "mystery"}:
            tracker_candidates.append(
                {
                    "candidate_type": kind,
                    "content": value,
                    "candidate_action": "plant",
                    "evidence_refs": [_evidence(chapter, value, line_number)],
                    "confidence_score": 0.65,
                }
            )
        elif kind == "chapter_function":
            structural["chapter_function"] = _dict_with_label(value, chapter, line_number)
        elif kind == "reader_experience":
            structural["dominant_reader_experience"] = _dict_with_label(value, chapter, line_number)
        elif kind == "conflict":
            structural["conflict_function"] = _dict_with_label(value, chapter, line_number)
        elif kind == "pacing":
            structural["pacing_density"] = _dict_with_label(value, chapter, line_number)
        elif kind == "ending_hook":
            structural["ending_hook_type"] = _dict_with_label(value, chapter, line_number)
        elif kind == "boundary_signal":
            for signal in re.split(r"[,，]\s*", value):
                normalized = signal.strip()
                if normalized in _BOUNDARY_SIGNAL_FIELDS:
                    boundary_signals[normalized] = True

    if not events:
        for line_number, line in narrative_lines[:5]:
            events.append(
                {
                    "event_id": f"{chapter.chapter_id}_event_{len(events) + 1:03d}",
                    "summary": line,
                    "evidence_refs": [_evidence(chapter, line, line_number)],
                    "extraction_method": "fallback_narrative_line",
                }
            )

    fallback_line_number, fallback_quote = narrative_lines[0] if narrative_lines else (1, chapter.normalized_title)
    if events and not structural.get("chapter_function"):
        structural["chapter_function"] = _fallback_structural_value(
            "fallback_context_progression",
            chapter,
            fallback_quote,
            fallback_line_number,
        )
    if events and not structural.get("dominant_reader_experience"):
        structural["dominant_reader_experience"] = _fallback_structural_value(
            "fallback_baseline_attention",
            chapter,
            fallback_quote,
            fallback_line_number,
        )

    summary = events[0]["summary"] if events else ""
    confidence = 0.65 if tracker_candidates or structural or character_changes else 0.35
    return RawSemanticChapterInput.model_validate(
        {
            "schema_version": RAW_SEMANTIC_SCHEMA_VERSION,
            "chapter_id": chapter.chapter_id,
            "chapter_index": chapter.chapter_index,
            "analyzer_id": "deterministic_marker_extractor_v1",
            "source_text_sha256": sha256_text(text),
            "chapter_summary": summary,
            "story_facts": {
                "events": events,
                "character_state_changes": character_changes,
                "relationship_changes": relationship_changes,
                "world_facts_added": world_facts,
                "information_state_changes": information_changes,
            },
            "structural_analysis": structural,
            "tracker_candidates": tracker_candidates,
            "boundary_signals": boundary_signals,
            "confidence_score": confidence,
        }
    )


def _normalize_events(chapter: ChapterSource, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, event in enumerate(events, start=1):
        item = dict(event)
        item.setdefault("event_id", f"{chapter.chapter_id}_event_{index:03d}")
        item.setdefault("chapter_index", chapter.chapter_index)
        item.setdefault("evidence_refs", [])
        normalized.append(item)
    return normalized


def _normalize_tracker_candidates(chapter: ChapterSource, candidates: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for index, candidate in enumerate(candidates, start=1):
        data = candidate.model_dump(mode="json") if hasattr(candidate, "model_dump") else dict(candidate)
        candidate_type = data.get("candidate_type", "foreshadowing")
        if not data.get("candidate_id"):
            data["candidate_id"] = f"{chapter.chapter_id}_{candidate_type}_{index:03d}"
        data.setdefault("candidate_action", "plant")
        data.setdefault("possible_existing_item_refs", [])
        data.setdefault("evidence_refs", [])
        data.setdefault("confidence_score", 0.0)
        normalized.append(TrackerCandidate.model_validate(data).model_dump(mode="json"))
    return normalized


def canonical_from_raw_semantic(
    chapter: ChapterSource,
    raw: RawSemanticChapterInput,
    *,
    semantic_source: str = "reviewed_json",
    semantic_input_ref: str = "",
) -> CanonicalChapterAnalysis:
    canonical = _base_canonical(chapter)
    facts = raw.story_facts
    canonical.story_facts = StoryFacts(
        chapter_summary=raw.chapter_summary,
        events=_normalize_events(chapter, facts.events),
        character_state_changes=facts.character_state_changes,
        relationship_changes=facts.relationship_changes,
        world_facts_added=facts.world_facts_added,
        information_state_changes=facts.information_state_changes,
        reader_known_information=facts.reader_known_information,
        character_known_information=facts.character_known_information,
    )
    canonical.structural_analysis = StructuralAnalysis.model_validate(raw.structural_analysis.model_dump(mode="json"))
    canonical.transferable_patterns = raw.transferable_patterns
    canonical.tracker_candidates = _normalize_tracker_candidates(chapter, raw.tracker_candidates)
    canonical.boundary_signals = BoundarySignals.model_validate(raw.boundary_signals)

    notes = list(raw.quality_notes)
    notes.append(f"semantic_input={raw.analyzer_id}")
    notes.append(f"semantic_source={semantic_source}")
    hash_mismatch = bool(raw.source_text_sha256 and raw.source_text_sha256 != chapter.text_sha256)
    if hash_mismatch:
        notes.append("semantic_source_hash_mismatch")
    canonical.quality.confidence_score = min(canonical.quality.confidence_score, raw.confidence_score)
    canonical.quality.requires_repair_pass = canonical.quality.requires_repair_pass or hash_mismatch
    canonical.quality.review_notes = notes
    canonical.quality.semantic_source = semantic_source  # type: ignore[assignment]
    canonical.quality.semantic_analyzer_id = raw.analyzer_id
    canonical.quality.semantic_input_ref = semantic_input_ref
    return canonical


def canonical_from_source_text(chapter: ChapterSource, text: str) -> CanonicalChapterAnalysis:
    if not text.strip():
        canonical = _base_canonical(chapter)
        canonical.quality.confidence_score = min(canonical.quality.confidence_score, 0.2)
        canonical.quality.requires_repair_pass = True
        canonical.quality.review_notes.append("semantic_input=missing_source_text")
        canonical.quality.review_notes.append("semantic_source=deterministic_fallback")
        canonical.quality.semantic_source = "deterministic_fallback"
        canonical.quality.semantic_analyzer_id = "missing_source_text"
        return canonical
    raw = extract_raw_semantics_from_text(chapter, text)
    canonical = canonical_from_raw_semantic(
        chapter,
        raw,
        semantic_source="deterministic_fallback",
    )
    canonical.quality.review_notes = [
        note if note != "semantic_input=deterministic_marker_extractor_v1" else "semantic_input=deterministic_text"
        for note in canonical.quality.review_notes
    ]
    canonical.quality.semantic_analyzer_id = "deterministic_marker_extractor_v1"
    return canonical


def build_canonical_for_chapter(
    manifest: SourceInputManifest,
    chapter: ChapterSource,
    *,
    semantic_input: str | Path | None = None,
    run_dir: str | Path | None = None,
) -> CanonicalChapterAnalysis:
    raw_result = load_raw_semantic_input_with_source(chapter, semantic_input, run_dir=run_dir)
    if raw_result is not None:
        return canonical_from_raw_semantic(
            chapter,
            raw_result.raw,
            semantic_source=raw_result.semantic_source,
            semantic_input_ref=raw_result.semantic_input_ref,
        )
    text = load_chapter_text(manifest, chapter)
    return canonical_from_source_text(chapter, text)


def build_all_canonical_chapters(
    run_dir: str | Path,
    *,
    semantic_input: str | Path | None = None,
) -> list[CanonicalChapterAnalysis]:
    manifest = load_source_manifest(run_dir)
    return [
        build_canonical_for_chapter(manifest, chapter, semantic_input=semantic_input, run_dir=run_dir)
        for chapter in manifest.chapters
    ]
