from __future__ import annotations

from pathlib import Path
from typing import Any

from ..analysis.canonical_builder import load_canonical_chapters
from ..models.canonical import CanonicalChapterAnalysis
from ..models.common import EvidenceClaimType, GenerationMode, SourceSpecificity, make_evidence_ref
from ..models.modules import ModuleEnvelope
from .catalog_builder import build_module_catalog
from .module_store import chapter_modules_path, write_json


CHAPTER_MODULE_SPECS = [
    ("chapter_event_beats", "plot", SourceSpecificity.SOURCE_SPECIFIC),
    ("chapter_function", "plot", SourceSpecificity.HYBRID),
    ("chapter_reader_experience", "rhythm", SourceSpecificity.HYBRID),
]
PACKAGED_TRACKER_TYPES = {"foreshadowing", "mystery", "relationship_debt", "world_rule_reveal"}

ALL_MODES = [
    GenerationMode.ORIGINAL_WRITING,
    GenerationMode.CONTINUATION_OR_REVISION,
    GenerationMode.HYBRID_ADAPTATION,
]


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _content_quality(content: dict[str, Any], required_fields: list[str]) -> dict[str, Any]:
    filled = [field for field in required_fields if _has_content(content.get(field))]
    missing = [field for field in required_fields if field not in filled]
    return {
        "status": "usable" if not missing else "sparse",
        "required_fields": required_fields,
        "filled_required_fields": filled,
        "missing_required_fields": missing,
        "filled_required_field_count": len(filled),
    }


def _tracker_candidate_refs(
    chapter: CanonicalChapterAnalysis,
    candidate_type: str | None = None,
    *,
    packaged_only: bool = False,
) -> list[str]:
    refs = []
    for candidate in chapter.tracker_candidates:
        if not isinstance(candidate, dict):
            continue
        if packaged_only and candidate.get("candidate_type") not in PACKAGED_TRACKER_TYPES:
            continue
        if candidate_type is not None and candidate.get("candidate_type") != candidate_type:
            continue
        candidate_id = candidate.get("candidate_id")
        if candidate_id:
            refs.append(candidate_id)
    return refs


def _cross_reference_summary(chapter: CanonicalChapterAnalysis) -> dict[str, Any]:
    return {
        "tracker_candidate_refs": _tracker_candidate_refs(chapter, packaged_only=True),
        "foreshadowing_candidate_refs": _tracker_candidate_refs(chapter, "foreshadowing"),
        "mystery_candidate_refs": _tracker_candidate_refs(chapter, "mystery"),
        "relationship_debt_candidate_refs": _tracker_candidate_refs(chapter, "relationship_debt"),
        "world_rule_reveal_candidate_refs": _tracker_candidate_refs(chapter, "world_rule_reveal"),
        "relationship_change_count": len(chapter.story_facts.relationship_changes),
        "world_fact_count": len(chapter.story_facts.world_facts_added),
        "information_change_count": len(chapter.story_facts.information_state_changes),
    }


def _reader_expectation_shift(chapter: CanonicalChapterAnalysis) -> dict[str, Any]:
    signals = chapter.boundary_signals
    drivers = []
    if signals.new_question_launched:
        drivers.append("new_question_launched")
    if signals.major_question_answered:
        drivers.append("major_question_answered")
    if signals.reader_experience_shifted:
        drivers.append("reader_experience_shifted")
    if signals.dominant_conflict_changed:
        drivers.append("dominant_conflict_changed")
    if _tracker_candidate_refs(chapter, packaged_only=True):
        drivers.append("tracker_candidate_present")
    if chapter.structural_analysis.ending_hook_type:
        drivers.append("ending_hook_present")

    if signals.new_question_launched:
        shift_type = "new_question_pressure"
    elif signals.major_question_answered:
        shift_type = "answer_or_reframe"
    elif signals.reader_experience_shifted or signals.dominant_conflict_changed:
        shift_type = "experience_reorientation"
    elif chapter.structural_analysis.ending_hook_type or _tracker_candidate_refs(chapter, packaged_only=True):
        shift_type = "sustained_curiosity"
    else:
        shift_type = "steady_continuity"

    return {
        "shift_type": shift_type,
        "drivers": drivers,
        "source": "boundary_signals_tracker_candidates_and_ending_hook",
    }


def _suspense_pressure(chapter: CanonicalChapterAnalysis) -> dict[str, Any]:
    signals = chapter.boundary_signals
    drivers = []
    score = 0
    if signals.new_question_launched:
        score += 2
        drivers.append("new_question_launched")
    if signals.major_question_answered:
        score += 1
        drivers.append("major_question_answered")
    if signals.dominant_conflict_changed:
        score += 1
        drivers.append("dominant_conflict_changed")
    if chapter.structural_analysis.ending_hook_type:
        score += 1
        drivers.append("ending_hook_present")
    tracker_refs = _tracker_candidate_refs(chapter, packaged_only=True)
    if tracker_refs:
        score += min(2, len(tracker_refs))
        drivers.append("tracker_candidate_present")

    if score >= 4:
        level = "high"
    elif score >= 2:
        level = "medium"
    elif score >= 1:
        level = "low"
    else:
        level = "none"

    return {
        "level": level,
        "score": score,
        "drivers": drivers,
        "source": "deterministic_boundary_and_tracker_summary",
    }


def _chapter_evidence(
    chapter: CanonicalChapterAnalysis,
    claim_type: EvidenceClaimType = EvidenceClaimType.CANONICAL_CHAPTER,
) -> list[dict[str, Any]]:
    return [
        make_evidence_ref(
            claim_type=claim_type,
            ref_type="canonical_chapter",
            chapter_id=chapter.chapter_id,
            chapter_index=chapter.chapter_index,
        )
    ]


def _module_claim_type(module_id: str) -> EvidenceClaimType:
    if module_id == "chapter_reader_experience":
        return EvidenceClaimType.MYSTERY_STATE_CHANGE
    return EvidenceClaimType.SCENE_TURN


def _canonical_ref(chapter: CanonicalChapterAnalysis) -> str:
    return f"canonical_chapter_analysis/{chapter.chapter_id}.json"


def _base_content(chapter: CanonicalChapterAnalysis) -> dict[str, Any]:
    return {
        "chapter_id": chapter.chapter_id,
        "chapter_index": chapter.chapter_index,
        "normalized_title": chapter.source.normalized_title,
        "canonical_ref": _canonical_ref(chapter),
        "chapter_summary": chapter.story_facts.chapter_summary,
        "cross_reference_summary": _cross_reference_summary(chapter),
    }


def _event_beats_content(chapter: CanonicalChapterAnalysis) -> dict[str, Any]:
    events = []
    for index, event in enumerate(chapter.story_facts.events, start=1):
        events.append(
            {
                "position": index,
                "event_id": event.get("event_id", f"{chapter.chapter_id}_event_{index:03d}"),
                "summary": event.get("summary", ""),
                "participants": event.get("participants", []),
                "evidence_refs": event.get("evidence_refs", []),
            }
        )
    content = _base_content(chapter)
    content.update(
        {
            "event_beats": events,
            "world_facts_added": chapter.story_facts.world_facts_added,
            "character_state_changes": chapter.story_facts.character_state_changes,
            "relationship_changes": chapter.story_facts.relationship_changes,
            "source_specific_elements": [
                {"element_type": "event", "value": event.get("summary", "")}
                for event in chapter.story_facts.events
            ],
            "replacement_required": True,
        }
    )
    content["content_quality"] = _content_quality(
        content,
        ["chapter_id", "chapter_summary", "event_beats", "cross_reference_summary"],
    )
    return content


def _chapter_function_content(chapter: CanonicalChapterAnalysis) -> dict[str, Any]:
    content = _base_content(chapter)
    content.update(
        {
            "chapter_function": chapter.structural_analysis.chapter_function,
            "conflict_function": chapter.structural_analysis.conflict_function,
            "pacing_density": chapter.structural_analysis.pacing_density,
            "ending_hook_type": chapter.structural_analysis.ending_hook_type,
            "boundary_signals": chapter.boundary_signals.model_dump(mode="json"),
            "reusable_mechanism": {
                "module_id": "chapter_function",
                "mechanism": "Preserve the chapter's narrative job, transition pressure, and ending hook rather than copying surface events.",
            },
            "source_specific_elements": [
                {"element_type": "chapter_title", "value": chapter.source.normalized_title},
                {"element_type": "chapter_events", "value": [event.get("summary", "") for event in chapter.story_facts.events]},
            ],
            "replacement_required": True,
        }
    )
    content["content_quality"] = _content_quality(
        content,
        ["chapter_id", "boundary_signals", "reusable_mechanism", "source_specific_elements"],
    )
    return content


def _reader_experience_content(chapter: CanonicalChapterAnalysis) -> dict[str, Any]:
    content = _base_content(chapter)
    content.update(
        {
            "dominant_reader_experience": chapter.structural_analysis.dominant_reader_experience,
            "information_release_method": chapter.structural_analysis.information_release_method,
            "reader_known_information": chapter.story_facts.reader_known_information,
            "character_known_information": chapter.story_facts.character_known_information,
            "tracker_candidate_refs": _tracker_candidate_refs(chapter, packaged_only=True),
            "reader_expectation_shift": _reader_expectation_shift(chapter),
            "suspense_pressure": _suspense_pressure(chapter),
            "reusable_mechanism": {
                "module_id": "chapter_reader_experience",
                "mechanism": "Preserve the intended reader feeling and information-release posture at this chapter position.",
            },
            "replacement_required": True,
        }
    )
    content["content_quality"] = _content_quality(
        content,
        ["chapter_id", "reader_expectation_shift", "suspense_pressure", "reusable_mechanism"],
    )
    return content


def _content_for(module_id: str, chapter: CanonicalChapterAnalysis) -> dict[str, Any]:
    if module_id == "chapter_event_beats":
        return _event_beats_content(chapter)
    if module_id == "chapter_function":
        return _chapter_function_content(chapter)
    if module_id == "chapter_reader_experience":
        return _reader_experience_content(chapter)
    return _base_content(chapter)


def _make_module(
    *,
    chapter: CanonicalChapterAnalysis,
    module_id: str,
    module_type: str,
    source_specificity: SourceSpecificity,
) -> ModuleEnvelope:
    return ModuleEnvelope(
        module_id=module_id,
        module_instance_id=f"{chapter.chapter_id}_{module_id}",
        scope="chapter",
        module_type=module_type,
        source_specificity=source_specificity,
        recommended_modes=ALL_MODES,
        confidence_score=max(0.35, chapter.quality.confidence_score),
        evidence_refs=_chapter_evidence(chapter, _module_claim_type(module_id)),
        content=_content_for(module_id, chapter),
    )


def analyze_chapter_modules(run_dir: str | Path) -> dict[str, Any]:
    chapters = sorted(load_canonical_chapters(run_dir), key=lambda chapter: chapter.chapter_index)
    modules: list[ModuleEnvelope] = []
    for chapter in chapters:
        for module_id, module_type, source_specificity in CHAPTER_MODULE_SPECS:
            modules.append(
                _make_module(
                    chapter=chapter,
                    module_id=module_id,
                    module_type=module_type,
                    source_specificity=source_specificity,
                )
            )

    payload = {
        "schema_version": "story_analyzer.chapter_modules.v1",
        "status": "built_from_canonical_chapters",
        "source_refs": {
            "canonical_chapters_root": "canonical_chapter_analysis",
        },
        "chapter_count": len(chapters),
        "module_count": len(modules),
        "modules": [module.model_dump(mode="json") for module in modules],
    }
    write_json(chapter_modules_path(run_dir), payload)
    build_module_catalog(run_dir)
    return payload
