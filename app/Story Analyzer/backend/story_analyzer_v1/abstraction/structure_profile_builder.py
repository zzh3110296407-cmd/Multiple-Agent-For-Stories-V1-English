"""Build generator-ready structure-only profiles from abstract mechanisms."""

from __future__ import annotations

import json
import re

from .mechanism_abstractor import build_abstract_mechanism_catalog, mechanism_for_macros, stage_from_macros
from .source_entity_inventory import build_source_entity_inventory, entity_placeholder_map
from .source_leak_validator import replace_source_entities, validate_source_leaks


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _source_range(item: dict) -> str:
    return item.get("source_chapter_range") or item.get("arc_chapter_range") or ""


def _abstract_major_arcs(arc_hierarchy: dict) -> list[dict]:
    result = []
    for major in arc_hierarchy.get("major_arcs", []) or []:
        macros = major.get("macro_components") or []
        mechanism = mechanism_for_macros(macros)
        result.append(
            {
                "major_arc_id": major.get("major_arc_id"),
                "major_arc_index": major.get("major_arc_index"),
                "dominant_stage": major.get("dominant_stage") or stage_from_macros(macros),
                "source_chapter_range": major.get("source_chapter_range"),
                "analysis_unit_range": major.get("analysis_unit_range"),
                "sub_arc_ids": major.get("sub_arc_ids", []),
                "mechanism": mechanism,
            }
        )
    return result


def _abstract_sub_arcs(arcs: list[dict], arc_hierarchy: dict) -> list[dict]:
    sub_by_index = {
        sub.get("sub_arc_index"): sub
        for sub in arc_hierarchy.get("sub_arcs", []) or []
        if isinstance(sub, dict)
    }
    result = []
    for arc in arcs or []:
        index = arc.get("arc_index")
        sub = sub_by_index.get(index, {})
        macros = arc.get("arc_macros") or sub.get("macro_components") or []
        mechanism = mechanism_for_macros(macros)
        result.append(
            {
                "sub_arc_id": sub.get("sub_arc_id") or f"sub_arc_{int(index or len(result) + 1):03d}",
                "sub_arc_index": index,
                "major_arc_id": sub.get("major_arc_id"),
                "source_chapter_range": _source_range(arc),
                "analysis_unit_range": arc.get("analysis_unit_range") or _source_range(arc),
                "macro_components": macros,
                "mechanism": mechanism,
            }
        )
    return result


def _abstract_chapter_blueprint(chapters: list[dict]) -> list[dict]:
    blueprints = []
    for chapter in chapters or []:
        report = chapter.get("analysis_report") or {}
        analysis = report.get("chapter_analysis") or {}
        function = _abstract_chapter_function(str(analysis.get("chapter_function") or "structural_step"))
        reader = str(analysis.get("reader_emotion") or report.get("reader_emotion") or "controlled attention")
        blueprints.append(
            {
                "chapter_number": chapter.get("chapter_number"),
                "source_chapter_range": chapter.get("source_chapter_range"),
                "original_chapter_index": chapter.get("original_chapter_index"),
                "part_index": chapter.get("part_index"),
                "chapter_function": function,
                "reader_experience": _strip_source_like_phrases(reader),
                "mechanism": {
                    "input_state": "chapter starts from the previous state of pressure",
                    "pressure": "new information or conflict changes what the reader expects",
                    "transition": "the scene converts setup into changed stakes",
                    "output_state": "the next unit inherits a clearer desire, risk, or question",
                },
            }
        )
    return blueprints


def _abstract_chapter_function(function: str) -> str:
    text = str(function or "").lower()
    if any(term in text for term in ("reveal", "information", "truth", "信息", "揭示", "真相")):
        return "information_release_step"
    if any(term in text for term in ("climax", "crisis", "battle", "危机", "高潮", "对抗")):
        return "pressure_peak_step"
    if any(term in text for term in ("aftermath", "resolution", "余波", "收束", "结尾")):
        return "aftermath_reframe_step"
    if any(term in text for term in ("opening", "setup", "铺垫", "开端")):
        return "baseline_setup_step"
    return "structural_transition_step"


def _strip_source_like_phrases(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)+\b", "source-specific asset", text)
    return text


def _quality_report(structure_only: dict, leak_report: dict) -> dict:
    quality_view = dict(structure_only)
    quality_view.pop("entity_placeholders", None)
    quality_view.pop("source_term_placeholders", None)
    quality_view.pop("source_entity_inventory_ref", None)
    quality_view.pop("source_leak_report", None)
    quality_view.pop("_source_entity_inventory", None)
    placeholder_mentions = _prose_placeholder_mentions(quality_view)
    mechanisms = structure_only.get("abstract_mechanism_catalog", {}).get("items", [])
    usable = 0
    for mechanism in mechanisms:
        if all(mechanism.get(key) for key in ("input_state", "pressure", "transition", "output_state")):
            usable += 1
    warnings = []
    if placeholder_mentions > max(8, len(mechanisms) * 2):
        warnings.append("placeholder_density_high")
    if leak_report.get("status") != "passed":
        warnings.append("source_leak_detected")
    if mechanisms and usable < len(mechanisms):
        warnings.append("incomplete_mechanism_fields")
    score = 1.0
    score -= min(0.4, placeholder_mentions * 0.02)
    if leak_report.get("status") != "passed":
        score -= 0.4
    if mechanisms:
        score -= (len(mechanisms) - usable) * 0.1
    return {
        "schema_version": "story_analyzer.abstraction_quality_report.v1",
        "status": "passed" if score >= 0.72 and not warnings else "warning",
        "abstraction_quality_score": round(max(0.0, score), 3),
        "mechanism_count": len(mechanisms),
        "complete_mechanism_count": usable,
        "placeholder_mentions": placeholder_mentions,
        "warnings": warnings,
    }


def _prose_placeholder_mentions(value, path: str = "") -> int:
    if isinstance(value, str):
        if any(part in path for part in ("_id", "_ref", "entity_ref", "source_chapter_range", "analysis_unit_range")):
            return 0
        return value.count("SOURCE_TERM_") + value.count("CHARACTER_")
    if isinstance(value, dict):
        return sum(
            _prose_placeholder_mentions(item, f"{path}.{key}" if path else str(key))
            for key, item in value.items()
        )
    if isinstance(value, list):
        return sum(_prose_placeholder_mentions(item, f"{path}[{index}]") for index, item in enumerate(value))
    return 0


def build_structure_only_profile(
    *,
    book_framework: dict,
    arcs: list[dict],
    chapters: list[dict],
    arc_hierarchy: dict,
    character_map: dict[str, str] | None = None,
    foreshadowing_registry: dict | None = None,
    narrative_thread_registry: dict | None = None,
) -> dict:
    inventory = build_source_entity_inventory(
        outputs=[book_framework, arcs, chapters, foreshadowing_registry or {}, narrative_thread_registry or {}],
        chapters=chapters,
        character_map=character_map or {},
    )
    catalog = build_abstract_mechanism_catalog(arcs, chapters)
    entity_map = entity_placeholder_map(inventory)
    structure = {
        "profile_type": "structure_only",
        "de_named": True,
        "source_abstraction_mode": "abstract_mechanism",
        "excludes": ["concrete_plot_summary", "proper_name_dependency", "source_story_continuation_constraints"],
        "entity_placeholders": _unique(
            [placeholder for surface, placeholder in entity_map.items() if placeholder.startswith("CHARACTER_")]
        ),
        "source_term_placeholders": _unique(
            [placeholder for surface, placeholder in entity_map.items() if not placeholder.startswith("CHARACTER_")]
        ),
        "source_entity_inventory_ref": {
            "schema_version": inventory["schema_version"],
            "entity_count": len(inventory.get("entities", [])),
            "counts_by_type": inventory.get("counts_by_type", {}),
        },
        "rhythm_framework": {
            "narrative_rhythm": "Baseline setup, threshold pressure, escalating tests, costly crisis, and aftermath debt.",
            "structural_pattern": "Each unit converts an input state into higher pressure, a transition choice, and a changed output state.",
        },
        "arc_blueprint": [],
        "major_arc_blueprint": _abstract_major_arcs(arc_hierarchy),
        "sub_arc_blueprint": _abstract_sub_arcs(arcs, arc_hierarchy),
        "chapter_blueprint": _abstract_chapter_blueprint(chapters),
        "character_arc_patterns": [
            {
                "entity_ref": placeholder,
                "arc_pattern": {
                    "input_state": "initial role or desire is incomplete",
                    "pressure": "external conflict tests the role",
                    "transition": "choice or revelation changes self-understanding",
                    "output_state": "role becomes more defined for later arcs",
                },
            }
            for placeholder in _unique(
                [placeholder for surface, placeholder in entity_map.items() if placeholder.startswith("CHARACTER_")]
            )
        ],
        "abstract_mechanism_catalog": catalog,
    }
    for arc in arcs or []:
        macros = arc.get("arc_macros") or []
        structure["arc_blueprint"].append(
            {
                "arc_index": arc.get("arc_index"),
                "source_chapter_range": _source_range(arc),
                "analysis_unit_range": arc.get("analysis_unit_range") or _source_range(arc),
                "macro_components": macros,
                "mechanism": mechanism_for_macros(macros),
            }
        )

    structure = replace_source_entities(structure, inventory)
    leak_report = validate_source_leaks(structure, inventory)
    structure["_source_entity_inventory"] = inventory
    structure["source_leak_report"] = leak_report
    structure["abstraction_quality_report"] = _quality_report(structure, leak_report)
    return structure
