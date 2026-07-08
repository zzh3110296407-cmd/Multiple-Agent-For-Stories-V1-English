from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..handoff.package_store import now_iso, read_json, write_json
from ..handoff.validator import validate_handoff_package
from ..models.common import evidence_claim_type
from ..models.handoff import HandoffPackageManifest
from ..models.modules import ModuleEnvelope


INPUT_SCHEMA_VERSION = "story_analyzer.cross_work_input_manifest.v1"
REPORT_SCHEMA_VERSION = "story_analyzer.cross_work_pattern_synthesis_report.v1"
REPORT_FILENAME = "cross_work_pattern_synthesis_report.json"
MODULE_REFS = [
    ("modules/chapter_modules.json", "chapter_modules"),
    ("modules/arc_modules.json", "arc_modules"),
    ("modules/book_modules.json", "book_modules"),
]
TRANSFERABLE_SOURCE_SPECIFICITIES = {"transferable", "hybrid"}
SAFE_STRUCTURAL_CONTENT_KEYS = {
    "boundary_signals",
    "chapter_function",
    "conflict_function",
    "curve",
    "dominant_reader_experience",
    "edges",
    "ending_hook_type",
    "escalation_steps",
    "information_release_method",
    "nodes",
    "pacing_density",
    "protagonist_arcs",
    "reader_expectation_shift",
    "relationship_dynamics",
    "release_points",
    "reusable_mechanism",
    "rhythm_nodes",
    "suspense_pressure",
    "theme_candidates",
}
MODULE_TYPE_TO_FAMILY = {
    "rhythm": "rhythm",
    "plot": "structure",
    "theme": "theme",
    "character": "character",
    "relationship": "relationship",
    "world": "world",
    "style": "style",
    "information": "information_release",
    "adaptation": "adaptation",
}


def _require_input_manifest(data: dict[str, Any]) -> None:
    if data.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise ValueError(f"cross-work manifest schema_version must be {INPUT_SCHEMA_VERSION}")
    works = data.get("works")
    if not isinstance(works, list):
        raise ValueError("cross-work manifest works must be a list")
    if len(works) < 2:
        raise ValueError("cross-work synthesis requires at least two handoff packages")
    min_source_count = data.get("min_source_count", 2)
    if not isinstance(min_source_count, int) or min_source_count < 2:
        raise ValueError("cross-work manifest min_source_count must be an integer >= 2")
    for index, work in enumerate(works, start=1):
        if not isinstance(work, dict):
            raise ValueError(f"works[{index}] must be an object")
        if not work.get("work_id"):
            raise ValueError(f"works[{index}].work_id is required")
        if not work.get("handoff_package_dir"):
            raise ValueError(f"works[{index}].handoff_package_dir is required")


def _load_manifest(package_dir: Path) -> HandoffPackageManifest:
    try:
        return HandoffPackageManifest.model_validate(read_json(package_dir / "package_manifest.json"))
    except ValidationError as exc:
        raise ValueError(f"Invalid handoff package manifest in {package_dir}: {exc}") from exc


def _load_package_modules(package_dir: Path) -> list[tuple[ModuleEnvelope, str]]:
    modules: list[tuple[ModuleEnvelope, str]] = []
    for rel, _artifact_name in MODULE_REFS:
        path = package_dir / rel
        if not path.exists():
            continue
        payload = read_json(path)
        try:
            modules.extend((ModuleEnvelope.model_validate(module), rel) for module in payload.get("modules", []))
        except ValidationError as exc:
            raise ValueError(f"Invalid module envelope in {path}: {exc}") from exc
    return modules


def _read_optional_json(package_dir: Path, rel: str) -> dict[str, Any]:
    path = package_dir / rel
    if not path.exists():
        return {}
    return read_json(path)


def _pattern_family(module: ModuleEnvelope) -> str:
    if "conflict" in module.module_id:
        return "conflict"
    if "release" in module.module_id or "question" in module.module_id:
        return "information_release"
    return MODULE_TYPE_TO_FAMILY.get(module.module_type, module.module_type)


def _recommended_modes(modules: list[ModuleEnvelope]) -> list[str]:
    modes: set[str] = set()
    for module in modules:
        modes.update(mode.value if hasattr(mode, "value") else str(mode) for mode in module.recommended_modes)
    return sorted(modes)


def _safe_mechanism(module: ModuleEnvelope) -> str:
    reusable = module.content.get("reusable_mechanism")
    if isinstance(reusable, dict):
        mechanism = reusable.get("mechanism")
        if isinstance(mechanism, str) and mechanism.strip():
            return mechanism.strip()
    return ""


def _safe_structural_keys(module: ModuleEnvelope) -> list[str]:
    return sorted(key for key in module.content if key in SAFE_STRUCTURAL_CONTENT_KEYS)


def _evidence_summary(modules: list[ModuleEnvelope]) -> dict[str, Any]:
    claim_type_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    total = 0
    for module in modules:
        scope_counts[module.scope] += 1
        total += len(module.evidence_refs)
        for evidence_ref in module.evidence_refs:
            claim_type_counts[evidence_claim_type(evidence_ref)] += 1
    return {
        "module_count": len(modules),
        "evidence_ref_count": total,
        "claim_type_counts": dict(sorted(claim_type_counts.items())),
        "scope_counts": dict(sorted(scope_counts.items())),
    }


def _common_mechanism_summary(
    *,
    module_id: str,
    module_type: str,
    source_count: int,
    mechanisms: list[str],
    structural_keys: list[str],
) -> str:
    if mechanisms:
        return (
            f"Shared {module_type} pattern '{module_id}' appears across {source_count} works. "
            f"Reusable mechanism: {mechanisms[0]}"
        )
    if structural_keys:
        return (
            f"Shared {module_type} pattern '{module_id}' appears across {source_count} works through "
            f"structural signals: {', '.join(structural_keys)}."
        )
    return f"Shared {module_type} pattern '{module_id}' appears across {source_count} works."


def _source_ref(
    *,
    work_index: int,
    work: dict[str, Any],
    module_entries: list[tuple[ModuleEnvelope, str]],
    validation_status: str,
    conflict_report: dict[str, Any],
) -> dict[str, Any]:
    modules = [module for module, _rel in module_entries]
    source_files = sorted({rel for _module, rel in module_entries})
    return {
        "source_index": work_index,
        "work_id": str(work["work_id"]),
        "module_instance_ids": sorted(module.module_instance_id for module in modules),
        "module_count": len(modules),
        "source_files": source_files,
        "evidence_summary": _evidence_summary(modules),
        "handoff_validation_status": validation_status,
        "module_conflict_status": conflict_report.get("status", "not_present"),
        "module_conflict_count": conflict_report.get("conflict_count", 0),
    }


def _build_pattern(
    *,
    index: int,
    key: tuple[str, str, str],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    module_id, scope, module_type = key
    entries_by_source: dict[int, list[tuple[ModuleEnvelope, str]]] = defaultdict(list)
    work_by_source: dict[int, dict[str, Any]] = {}
    validation_by_source: dict[int, str] = {}
    conflict_by_source: dict[int, dict[str, Any]] = {}
    for entry in entries:
        entries_by_source[entry["source_index"]].append((entry["module"], entry["source_file"]))
        work_by_source[entry["source_index"]] = entry["work"]
        validation_by_source[entry["source_index"]] = entry["validation_status"]
        conflict_by_source[entry["source_index"]] = entry["conflict_report"]

    modules = [entry["module"] for entry in entries]
    source_indexes = sorted(entries_by_source)
    mechanisms = sorted({mechanism for module in modules if (mechanism := _safe_mechanism(module))})
    structural_keys = sorted({key for module in modules for key in _safe_structural_keys(module)})
    family = _pattern_family(modules[0])
    source_refs = [
        _source_ref(
            work_index=source_index,
            work=work_by_source[source_index],
            module_entries=entries_by_source[source_index],
            validation_status=validation_by_source[source_index],
            conflict_report=conflict_by_source[source_index],
        )
        for source_index in source_indexes
    ]

    return {
        "pattern_id": f"CWP{index:03d}",
        "pattern_family": family,
        "module_id": module_id,
        "module_type": module_type,
        "scope": scope,
        "source_count": len(source_indexes),
        "source_indexes": source_indexes,
        "common_mechanism_summary": _common_mechanism_summary(
            module_id=module_id,
            module_type=module_type,
            source_count=len(source_indexes),
            mechanisms=mechanisms,
            structural_keys=structural_keys,
        ),
        "mechanism_variants": mechanisms,
        "structural_feature_keys": structural_keys,
        "recommended_generation_modes": _recommended_modes(modules),
        "evidence_summary": _evidence_summary(modules),
        "source_refs": source_refs,
        "source_specific_elements_excluded": True,
        "generator_import_policy": {
            "advisory_only": True,
            "does_not_write_generator_state": True,
            "requires_generator_side_selection": True,
        },
    }


def _source_index_item(
    *,
    work_index: int,
    work: dict[str, Any],
    package_dir: Path,
    manifest: HandoffPackageManifest,
    validation_summary: dict[str, Any],
    module_count: int,
    conflict_report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_index": work_index,
        "work_id": str(work["work_id"]),
        "work_title": str(work.get("work_title") or manifest.work_title or ""),
        "handoff_package_dir": str(package_dir),
        "handoff_run_id": manifest.run_id,
        "handoff_validation_status": validation_summary["validation_status"],
        "module_count": module_count,
        "module_conflict_status": conflict_report.get("status", "not_present"),
        "module_conflict_count": conflict_report.get("conflict_count", 0),
    }


def build_cross_work_pattern_synthesis(manifest_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    input_path = Path(manifest_path)
    manifest_data = read_json(input_path)
    _require_input_manifest(manifest_data)

    min_source_count = manifest_data.get("min_source_count", 2)
    comparable_dimensions = list(manifest_data.get("comparable_dimensions") or [])
    comparable_set = {str(item) for item in comparable_dimensions}
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    source_index: list[dict[str, Any]] = []

    for work_index, work in enumerate(manifest_data["works"], start=1):
        package_dir = Path(work["handoff_package_dir"])
        validation_summary = validate_handoff_package(package_dir)
        if validation_summary["validation_status"] != "passed":
            raise ValueError(
                f"handoff package {work.get('work_id', work_index)} failed validation: "
                f"{validation_summary['validation_status']}"
            )
        package_manifest = _load_manifest(package_dir)
        conflict_report = _read_optional_json(package_dir, "modules/module_conflict_report.json")
        modules = _load_package_modules(package_dir)
        source_index.append(
            _source_index_item(
                work_index=work_index,
                work=work,
                package_dir=package_dir,
                manifest=package_manifest,
                validation_summary=validation_summary,
                module_count=len(modules),
                conflict_report=conflict_report,
            )
        )
        for module, source_file in modules:
            if module.source_specificity.value not in TRANSFERABLE_SOURCE_SPECIFICITIES:
                continue
            family = _pattern_family(module)
            if comparable_set and family not in comparable_set:
                continue
            key = (module.module_id, module.scope, module.module_type)
            grouped[key].append(
                {
                    "source_index": work_index,
                    "work": work,
                    "module": module,
                    "source_file": source_file,
                    "validation_status": validation_summary["validation_status"],
                    "conflict_report": conflict_report,
                }
            )

    pattern_candidates = [
        (key, entries)
        for key, entries in grouped.items()
        if len({entry["source_index"] for entry in entries}) >= min_source_count
    ]
    pattern_candidates.sort(key=lambda item: (item[0][1], item[0][2], item[0][0]))
    patterns = [
        _build_pattern(index=index, key=key, entries=entries)
        for index, (key, entries) in enumerate(pattern_candidates, start=1)
    ]

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "ready" if patterns else "no_cross_work_patterns",
        "authority": "advisory_only",
        "can_write_formal_state": False,
        "generated_at": now_iso(),
        "input_manifest_ref": str(input_path),
        "work_count": len(manifest_data["works"]),
        "package_count": len(manifest_data["works"]),
        "min_source_count": min_source_count,
        "comparable_dimensions": comparable_dimensions,
        "pattern_count": len(patterns),
        "source_index": source_index,
        "patterns": patterns,
        "access_issues": [],
        "generator_import_policy": {
            "advisory_only": True,
            "does_not_write_generator_state": True,
            "requires_generator_side_selection": True,
            "requires_user_confirmation_before_formal_write": True,
        },
    }
    output_path = Path(output_dir) / REPORT_FILENAME
    write_json(output_path, report)
    return report
