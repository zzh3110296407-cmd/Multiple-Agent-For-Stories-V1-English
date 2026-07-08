from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..models.common import evidence_claim_type
from ..models.modules import ModuleEnvelope
from .module_store import (
    arc_modules_path,
    book_modules_path,
    chapter_modules_path,
    module_catalog_path,
    read_json,
    write_json,
)


def _load_module_envelopes(path: Path) -> list[ModuleEnvelope]:
    if not path.exists():
        return []
    payload = read_json(path)
    modules = payload.get("modules", [])
    try:
        return [ModuleEnvelope.model_validate(module) for module in modules]
    except ValidationError as exc:
        raise ValueError(f"Invalid module envelope in {path}: {exc}") from exc


def _module_summary(module: ModuleEnvelope, source_file: str) -> dict[str, Any]:
    data = module.model_dump(mode="json")
    claim_types = sorted({evidence_claim_type(ref) for ref in data["evidence_refs"]})
    return {
        "module_instance_id": data["module_instance_id"],
        "module_id": data["module_id"],
        "scope": data["scope"],
        "module_type": data["module_type"],
        "source_specificity": data["source_specificity"],
        "recommended_modes": data["recommended_modes"],
        "depends_on": data["depends_on"],
        "evidence_ref_count": len(data["evidence_refs"]),
        "evidence_claim_types": claim_types,
        "source_file": source_file,
    }


def _dependency_warnings(modules: list[ModuleEnvelope]) -> list[dict[str, Any]]:
    module_ids = {module.module_instance_id for module in modules}
    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for module in modules:
        if module.module_instance_id in seen:
            warnings.append(
                {
                    "type": "duplicate_module_instance_id",
                    "module_instance_id": module.module_instance_id,
                }
            )
        seen.add(module.module_instance_id)
        for dependency in module.depends_on:
            if dependency not in module_ids:
                warnings.append(
                    {
                        "type": "missing_dependency",
                        "module_instance_id": module.module_instance_id,
                        "missing_dependency": dependency,
                    }
                )
    return warnings


def _evidence_claim_type_counts(modules: list[ModuleEnvelope]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for module in modules:
        for evidence_ref in module.evidence_refs:
            counts[evidence_claim_type(evidence_ref)] += 1
    return dict(sorted(counts.items()))


def build_module_catalog(run_dir: str | Path) -> dict[str, Any]:
    chapter_path = chapter_modules_path(run_dir)
    arc_path = arc_modules_path(run_dir)
    book_path = book_modules_path(run_dir)
    chapter_modules = _load_module_envelopes(chapter_path)
    arc_modules = _load_module_envelopes(arc_path)
    book_modules = _load_module_envelopes(book_path)
    all_modules = [*chapter_modules, *arc_modules, *book_modules]
    warnings = _dependency_warnings(all_modules)
    catalog = {
        "schema_version": "story_analyzer.module_catalog.v1",
        "status": "warning" if warnings else "passed",
        "module_count": len(all_modules),
        "warning_count": len(warnings),
        "module_refs": {
            "chapter_modules": "modules/chapter_modules.json" if chapter_path.exists() else "",
            "arc_modules": "modules/arc_modules.json" if arc_path.exists() else "",
            "book_modules": "modules/book_modules.json" if book_path.exists() else "",
        },
        "evidence_claim_type_counts": _evidence_claim_type_counts(all_modules),
        "warnings": warnings,
        "modules": [
            *[_module_summary(module, "modules/chapter_modules.json") for module in chapter_modules],
            *[_module_summary(module, "modules/arc_modules.json") for module in arc_modules],
            *[_module_summary(module, "modules/book_modules.json") for module in book_modules],
        ],
    }
    write_json(module_catalog_path(run_dir), catalog)
    return catalog
