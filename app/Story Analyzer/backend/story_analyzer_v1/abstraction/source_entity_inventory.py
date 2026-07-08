"""Build a source entity inventory before generator profile compilation."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from .proper_noun_detector import classify_surface, detect_source_terms, iter_strings, normalize_surface


PLACEHOLDER_PREFIX = {
    "character": "CHARACTER",
    "organization": "SOURCE_ORG",
    "institution": "SOURCE_INSTITUTION",
    "location": "SOURCE_LOCATION",
    "world_rule_term": "SOURCE_RULE",
    "artifact": "SOURCE_ARTIFACT",
    "ability_or_power": "SOURCE_POWER",
    "mythic_figure": "SOURCE_MYTHIC",
    "species_or_race": "SOURCE_SPECIES",
    "plan_or_project": "SOURCE_PLAN",
    "event_name": "SOURCE_EVENT",
    "title_or_rank": "SOURCE_TITLE",
    "slogan_or_quote": "SOURCE_QUOTE",
    "family_or_clan": "SOURCE_CLAN",
    "unknown_source_term": "SOURCE_TERM",
}


def _all_texts(values: Iterable) -> list[str]:
    texts: list[str] = []
    for value in values:
        texts.extend(iter_strings(value))
    return [text for text in texts if text]


def _chapter_numbers_for_surface(surface: str, chapters: list[dict]) -> list[int]:
    result: list[int] = []
    for chapter in chapters or []:
        number = chapter.get("chapter_number")
        text = " ".join(iter_strings(chapter))
        if surface in text and number not in result:
            try:
                result.append(int(number))
            except (TypeError, ValueError):
                continue
    return result


def build_source_entity_inventory(
    *,
    work_id: str = "",
    source_text: str = "",
    outputs: list | None = None,
    chapters: list[dict] | None = None,
    character_map: dict[str, str] | None = None,
) -> dict:
    texts = _all_texts([source_text, *(outputs or [])])
    combined = "\n".join(texts)
    detected: dict[str, str] = {}

    for surface, entity_type in detect_source_terms(combined).items():
        detected[normalize_surface(surface)] = entity_type

    for surface in (character_map or {}).keys():
        normalized = normalize_surface(surface)
        if normalized:
            detected.setdefault(normalized, "character")

    counters: defaultdict[str, int] = defaultdict(int)
    entities: list[dict] = []
    for surface in sorted(detected, key=lambda item: (-len(item), item.lower())):
        entity_type = detected[surface] or classify_surface(surface)
        counters[entity_type] += 1
        prefix = PLACEHOLDER_PREFIX.get(entity_type, "SOURCE_TERM")
        placeholder = f"{prefix}_{counters[entity_type]:02d}"
        confidence = 0.9 if entity_type != "unknown_source_term" else 0.68
        if entity_type == "character":
            confidence = 0.95
        entities.append(
            {
                "entity_id": f"E{len(entities) + 1:03d}",
                "surface": surface,
                "aliases": [surface],
                "entity_type": entity_type,
                "source_specificity": "source_specific",
                "appears_in_chapters": _chapter_numbers_for_surface(surface, chapters or []),
                "confidence": confidence,
                "replace_policy": "block_in_structure_only",
                "placeholder": placeholder,
                "requires_review": entity_type == "unknown_source_term",
            }
        )

    counts = Counter(entity["entity_type"] for entity in entities)
    return {
        "schema_version": "story_analyzer.source_entity_inventory.v1",
        "work_id": work_id,
        "entities": entities,
        "counts_by_type": dict(sorted(counts.items())),
        "detector_sources": [
            "deterministic_pattern_detector",
            "cross_output_entity_collector",
        ],
    }


def entity_placeholder_map(inventory: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entity in inventory.get("entities", []):
        placeholder = str(entity.get("placeholder") or "")
        if not placeholder:
            continue
        for surface in [entity.get("surface"), *(entity.get("aliases") or [])]:
            surface = normalize_surface(str(surface or ""))
            if surface:
                mapping.setdefault(surface, placeholder)
    return mapping
