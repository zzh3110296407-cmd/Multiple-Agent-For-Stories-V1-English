from __future__ import annotations

from collections import defaultdict
from itertools import combinations
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
    module_conflict_report_path,
    read_json,
    write_json,
)


REPORT_SCHEMA_VERSION = "story_analyzer.module_conflict_report.v1"
MODULE_FILES = [
    ("modules/chapter_modules.json", chapter_modules_path),
    ("modules/arc_modules.json", arc_modules_path),
    ("modules/book_modules.json", book_modules_path),
]
SEVERITY_RANK = {"info": 0, "warning": 1, "review_required": 2}


def _load_modules(run_dir: str | Path) -> list[ModuleEnvelope]:
    modules: list[ModuleEnvelope] = []
    for _ref, path_factory in MODULE_FILES:
        path = path_factory(run_dir)
        if not path.exists():
            continue
        payload = read_json(path)
        try:
            modules.extend(ModuleEnvelope.model_validate(module) for module in payload.get("modules", []))
        except ValidationError as exc:
            raise ValueError(f"Invalid module envelope in {path}: {exc}") from exc
    return modules


def _issue(
    *,
    conflict_type: str,
    rule_id: str,
    severity: str,
    module_instance_ids: list[str],
    reason: str,
    suggested_handling: str,
    evidence_claim_types: list[str] | None = None,
    source_specificities: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue = {
        "conflict_id": "",
        "conflict_type": conflict_type,
        "rule_id": rule_id,
        "severity": severity,
        "module_instance_ids": sorted(module_instance_ids),
        "reason": reason,
        "suggested_handling": suggested_handling,
        "evidence_claim_types": sorted(set(evidence_claim_types or [])),
        "source_specificities": sorted(set(source_specificities or [])),
    }
    if extra:
        issue.update(extra)
    return issue


def _claim_types(module: ModuleEnvelope) -> list[str]:
    return [evidence_claim_type(ref) for ref in module.evidence_refs]


def _evidence_keys(module: ModuleEnvelope) -> set[tuple[str, Any]]:
    keys: set[tuple[str, Any]] = set()
    for evidence in module.evidence_refs:
        claim_type = evidence_claim_type(evidence)
        chapter_index = evidence.get("chapter_index")
        if isinstance(chapter_index, int):
            keys.add((claim_type, chapter_index))
        chapter_id = evidence.get("chapter_id")
        if chapter_id:
            keys.add((claim_type, str(chapter_id)))
    return keys


def _missing_dependency_issues(modules: list[ModuleEnvelope]) -> list[dict[str, Any]]:
    module_ids = {module.module_instance_id for module in modules}
    issues = []
    for module in modules:
        for dependency in module.depends_on:
            if dependency in module_ids:
                continue
            issues.append(
                _issue(
                    conflict_type="missing_dependency",
                    rule_id="module_dependency_exists",
                    severity="review_required",
                    module_instance_ids=[module.module_instance_id],
                    reason=f"{module.module_instance_id} depends on missing module {dependency}.",
                    suggested_handling="Add the missing module, remove the dependency, or keep the module out of the generator preview selection.",
                    evidence_claim_types=_claim_types(module),
                    source_specificities=[module.source_specificity.value],
                    extra={"missing_dependency": dependency},
                )
            )
    return issues


def _mutual_exclusion_issues(modules: list[ModuleEnvelope]) -> list[dict[str, Any]]:
    by_id = {module.module_instance_id: module for module in modules}
    seen_pairs: set[tuple[str, str]] = set()
    issues = []
    for module in modules:
        for blocked_id in module.conflicts_with:
            other = by_id.get(blocked_id)
            if other is None:
                continue
            pair = tuple(sorted([module.module_instance_id, other.module_instance_id]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            issues.append(
                _issue(
                    conflict_type="mutual_exclusion",
                    rule_id="conflicts_with_selected",
                    severity="review_required",
                    module_instance_ids=list(pair),
                    reason=f"{module.module_instance_id} declares a conflict with {other.module_instance_id}, and both modules are present.",
                    suggested_handling="Ask the user which module should remain selectable, or remove one module from the preview import set.",
                    evidence_claim_types=[*_claim_types(module), *_claim_types(other)],
                    source_specificities=[module.source_specificity.value, other.source_specificity.value],
                )
            )
    return issues


def _claim_assertions(module: ModuleEnvelope) -> list[dict[str, str]]:
    raw_claims = module.content.get("evidence_claims", [])
    if not isinstance(raw_claims, list):
        return []
    claims = []
    for raw in raw_claims:
        if not isinstance(raw, dict):
            continue
        claim_key = str(raw.get("claim_key", "")).strip()
        stance = str(raw.get("stance", "")).strip()
        if not claim_key or stance not in {"supports", "rejects"}:
            continue
        claim_type = str(raw.get("claim_type") or "canonical_chapter")
        claims.append({"claim_key": claim_key, "claim_type": claim_type, "stance": stance})
    return claims


def _evidence_chain_issues(modules: list[ModuleEnvelope]) -> list[dict[str, Any]]:
    by_claim: dict[tuple[str, str], list[tuple[ModuleEnvelope, str]]] = defaultdict(list)
    for module in modules:
        for claim in _claim_assertions(module):
            by_claim[(claim["claim_key"], claim["claim_type"])].append((module, claim["stance"]))

    issues = []
    for (claim_key, claim_type), entries in sorted(by_claim.items()):
        stances = {stance for _module, stance in entries}
        if not {"supports", "rejects"}.issubset(stances):
            continue
        modules_for_claim = [module for module, _stance in entries]
        issues.append(
            _issue(
                conflict_type="evidence_chain_conflict",
                rule_id="contradictory_evidence_claim_stance",
                severity="review_required",
                module_instance_ids=[module.module_instance_id for module in modules_for_claim],
                reason=f"Evidence claim {claim_key} has both supports and rejects stances.",
                suggested_handling="Review source evidence and keep only the module interpretation that matches the confirmed analysis.",
                evidence_claim_types=[claim_type],
                source_specificities=[module.source_specificity.value for module in modules_for_claim],
                extra={"claim_key": claim_key, "stances": sorted(stances)},
            )
        )
    return issues


def _source_specificity_issues(modules: list[ModuleEnvelope]) -> list[dict[str, Any]]:
    issues = []
    for left, right in combinations(modules, 2):
        if left.module_id != right.module_id or left.scope != right.scope:
            continue
        if not _evidence_keys(left).intersection(_evidence_keys(right)):
            continue
        specificities = {left.source_specificity.value, right.source_specificity.value}
        if not {"source_specific", "transferable"}.issubset(specificities):
            continue
        issues.append(
            _issue(
                conflict_type="source_specificity_conflict",
                rule_id="same_slot_mixed_specificity",
                severity="warning",
                module_instance_ids=[left.module_instance_id, right.module_instance_id],
                reason=f"{left.module_id} has source_specific and transferable variants over the same evidence slot.",
                suggested_handling="Confirm whether the transferable module should replace the source-specific one or both should remain separately selectable.",
                evidence_claim_types=[*_claim_types(left), *_claim_types(right)],
                source_specificities=list(specificities),
            )
        )
    return issues


def _status(conflicts: list[dict[str, Any]]) -> str:
    if not conflicts:
        return "advisory_clear"
    if any(issue["severity"] == "review_required" for issue in conflicts):
        return "advisory_issues_found"
    return "advisory_warnings"


def _max_severity(conflicts: list[dict[str, Any]]) -> str:
    if not conflicts:
        return "info"
    return max(conflicts, key=lambda issue: SEVERITY_RANK[issue["severity"]])["severity"]


def build_module_conflict_report(run_dir: str | Path) -> dict[str, Any]:
    modules = _load_modules(run_dir)
    conflicts = [
        *_missing_dependency_issues(modules),
        *_mutual_exclusion_issues(modules),
        *_evidence_chain_issues(modules),
        *_source_specificity_issues(modules),
    ]
    conflicts = sorted(
        conflicts,
        key=lambda issue: (
            -SEVERITY_RANK[issue["severity"]],
            issue["conflict_type"],
            issue["module_instance_ids"],
        ),
    )
    for index, conflict in enumerate(conflicts, start=1):
        conflict["conflict_id"] = f"MC{index:03d}"

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": _status(conflicts),
        "authority": "advisory_only",
        "can_write_formal_state": False,
        "source_refs": {
            "chapter_modules_ref": "modules/chapter_modules.json" if chapter_modules_path(run_dir).exists() else "",
            "arc_modules_ref": "modules/arc_modules.json" if arc_modules_path(run_dir).exists() else "",
            "book_modules_ref": "modules/book_modules.json" if book_modules_path(run_dir).exists() else "",
            "module_catalog_ref": "modules/module_catalog.json" if module_catalog_path(run_dir).exists() else "",
        },
        "rule_ids": [
            "module_dependency_exists",
            "conflicts_with_selected",
            "contradictory_evidence_claim_stance",
            "same_slot_mixed_specificity",
        ],
        "module_count": len(modules),
        "conflict_count": len(conflicts),
        "max_severity": _max_severity(conflicts),
        "conflicts": conflicts,
        "generator_import_policy": {
            "advisory_only": True,
            "requires_user_confirmation_before_formal_write": True,
            "does_not_include_final_generation_profile": True,
        },
    }
    write_json(module_conflict_report_path(run_dir), report)
    return report
