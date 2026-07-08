"""Leak validation for structure-only profiles."""

from __future__ import annotations

import re

from .proper_noun_detector import detect_source_terms, iter_strings
from .source_entity_inventory import entity_placeholder_map


def _walk_strings(value, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            yield from _walk_strings(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")


def _is_ignorable_inventory_term(term: str) -> bool:
    normalized = str(term or "").strip()
    return bool(re.fullmatch(r"\d+", normalized))


def replace_source_entities(value, inventory: dict):
    mapping = entity_placeholder_map(inventory)
    if isinstance(value, str):
        output = value
        for surface, placeholder in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
            if not surface:
                continue
            if re.fullmatch(r"[A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)*", surface):
                output = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(surface)}(?![A-Za-z0-9_])", placeholder, output)
            else:
                output = output.replace(surface, placeholder)
        return output
    if isinstance(value, list):
        return [replace_source_entities(item, inventory) for item in value]
    if isinstance(value, dict):
        return {key: replace_source_entities(item, inventory) for key, item in value.items()}
    return value


def validate_source_leaks(structure_only: dict, inventory: dict) -> dict:
    leaks: list[dict] = []
    entities = inventory.get("entities", []) if isinstance(inventory, dict) else []

    for field_path, text in _walk_strings(structure_only):
        if field_path.endswith("source_entity_inventory_ref") or "placeholders" in field_path:
            continue
        for entity in entities:
            surface_terms = [entity.get("surface"), *(entity.get("aliases") or [])]
            for term in surface_terms:
                term = str(term or "").strip()
                if _is_ignorable_inventory_term(term):
                    continue
                if term and term in text:
                    leaks.append(
                        {
                            "term": term,
                            "entity_id": entity.get("entity_id"),
                            "entity_type": entity.get("entity_type"),
                            "field_path": field_path,
                            "severity": "blocking",
                            "suggested_fix": "regenerate_abstract_mechanism",
                        }
                    )

        unknown_terms = detect_source_terms(text)
        for term, entity_type in unknown_terms.items():
            if term.startswith("SOURCE_") or term.startswith("CHARACTER_"):
                continue
            leaks.append(
                {
                    "term": term,
                    "entity_id": "",
                    "entity_type": entity_type,
                    "field_path": field_path,
                    "severity": "warning",
                    "suggested_fix": "add_to_source_entity_inventory_or_regenerate",
                }
            )

    blocking = [leak for leak in leaks if leak.get("severity") == "blocking"]
    return {
        "schema_version": "story_analyzer.source_leak_report.v1",
        "status": "failed" if blocking else "passed",
        "blocking_leak_count": len(blocking),
        "warning_leak_count": len(leaks) - len(blocking),
        "leaks": leaks,
    }


def unknown_source_terms_in_profile(structure_only: dict) -> set[str]:
    found: set[str] = set()
    for _, text in _walk_strings(structure_only):
        found.update(detect_source_terms(text).keys())
    return found
