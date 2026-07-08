from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..models.handoff import HandoffPackageManifest
from ..models.modules import ModuleEnvelope
from .package_store import (
    PACKAGE_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
    now_iso,
    parse_checksums,
    read_json,
    relative_path,
    sha256_file,
)


KNOWN_SCHEMA_VERSIONS = {
    "story_analyzer_handoff.v1",
    "story_analyzer.run_manifest.v1",
    "story_analyzer.source_input.v1",
    "story_analyzer.source_input_manifest.v1",
    "story_analyzer.full_book_bundle.v1",
    "story_analyzer.canonical_chapter.v1",
    "story_analyzer.major_arcs.v1",
    "story_analyzer.sub_arcs.v1",
    "story_analyzer.foreshadowing_tracker.v1",
    "story_analyzer.mystery_tracker.v1",
    "story_analyzer.relationship_debt_tracker.v1",
    "story_analyzer.world_rule_reveal_tracker.v1",
    "story_analyzer.tracker_override_log.v1",
    "story_analyzer.tracker_edit_report.v1",
    "story_analyzer.tracker_semantic_recommendation_report.v1",
    "story_analyzer.chapter_modules.v1",
    "story_analyzer.arc_modules.v1",
    "story_analyzer.book_modules.v1",
    "story_analyzer.module_catalog.v1",
    "story_analyzer.module_conflict_report.v1",
    "story_analyzer.book_framework_package.v1",
    "story_analyzer.quality_report.v1",
    "story_analyzer.validation_summary.v1",
}

VALID_SOURCE_SPECIFICITY = {"transferable", "source_specific", "hybrid"}
RAW_FIELD_NAMES = {
    "raw_prompt",
    "_raw_prompt",
    "raw_response",
    "_raw_response",
    "_dify_raw",
    "_hidden_reasoning",
}
LARGE_TEXT_KEYS = {"text", "raw_text", "source_text", "full_text", "chapter_text"}
REQUIRED_CHAPTER_MODULE_IDS = {
    "chapter_event_beats",
    "chapter_function",
    "chapter_reader_experience",
}
CHAPTER_MODULE_REQUIRED_CONTENT_FIELDS = {
    "chapter_event_beats": {"chapter_id", "chapter_summary", "event_beats", "cross_reference_summary", "content_quality"},
    "chapter_function": {"chapter_id", "boundary_signals", "reusable_mechanism", "source_specific_elements", "content_quality"},
    "chapter_reader_experience": {
        "chapter_id",
        "reader_expectation_shift",
        "suspense_pressure",
        "reusable_mechanism",
        "content_quality",
    },
}


def _issue(code: str, message: str, path: str = "") -> dict[str, str]:
    issue = {"code": code, "message": message}
    if path:
        issue["path"] = path
    return issue


def _safe_read_json(path: Path, root: Path, issues: list[dict[str, str]]) -> dict[str, Any] | None:
    try:
        return read_json(path)
    except Exception as exc:  # noqa: BLE001 - validator must keep scanning where possible.
        issues.append(_issue("INVALID_JSON", str(exc), relative_path(path, root)))
        return None


def _walk_json(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, key, child
            yield from _walk_json(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, str(index), child
            yield from _walk_json(child, child_path)


def _scan_json_safety(rel: str, data: dict[str, Any], issues: list[dict[str, str]]) -> None:
    for path, key, value in _walk_json(data):
        if key in RAW_FIELD_NAMES:
            issues.append(_issue("RAW_PROMPT_OR_RESPONSE", f"raw field is not allowed: {path}", rel))
        if key in LARGE_TEXT_KEYS and isinstance(value, str) and len(value) > 500:
            issues.append(_issue("LARGE_SOURCE_TEXT", f"large source text field is not allowed: {path}", rel))
        if isinstance(value, str) and "[NEW_TERM]" in value:
            issues.append(_issue("NEW_TERM_POLLUTION", f"[NEW_TERM] found at {path}", rel))
        if key == "authority" and not path.startswith("checks.") and value != "advisory_only":
            issues.append(_issue("NON_ADVISORY_AUTHORITY", f"authority must be advisory_only at {path}", rel))
        if key == "can_write_formal_state" and value is True:
            issues.append(_issue("FORMAL_WRITE_PERMISSION", f"formal write permission found at {path}", rel))
        if key == "source_specificity" and value not in VALID_SOURCE_SPECIFICITY:
            issues.append(_issue("INVALID_SOURCE_SPECIFICITY", f"invalid source_specificity at {path}", rel))


def _validate_checksums(package_dir: Path, issues: list[dict[str, str]]) -> None:
    checksum_path = package_dir / "checksums.sha256"
    if not checksum_path.exists():
        issues.append(_issue("MISSING_CHECKSUMS", "checksums.sha256 is missing"))
        return
    try:
        expected = parse_checksums(checksum_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        issues.append(_issue("INVALID_CHECKSUMS", str(exc), "checksums.sha256"))
        return

    actual_payload_files = {
        relative_path(path, package_dir)
        for path in package_dir.rglob("*")
        if path.is_file() and relative_path(path, package_dir) not in {"checksums.sha256", "validation_summary.json"}
    }
    for rel in sorted(actual_payload_files - set(expected)):
        issues.append(_issue("CHECKSUM_MISSING_ENTRY", f"missing checksum entry for {rel}", "checksums.sha256"))
    for rel in sorted(set(expected) - actual_payload_files):
        issues.append(_issue("CHECKSUM_UNKNOWN_ENTRY", f"checksum references missing file {rel}", "checksums.sha256"))
    for rel in sorted(actual_payload_files.intersection(expected)):
        digest = sha256_file(package_dir / rel)
        if digest != expected[rel]:
            issues.append(_issue("CHECKSUM_MISMATCH", f"checksum mismatch for {rel}", "checksums.sha256"))


def _validate_manifest(package_dir: Path, json_by_rel: dict[str, dict[str, Any]], issues: list[dict[str, str]]) -> HandoffPackageManifest | None:
    manifest_data = json_by_rel.get("package_manifest.json")
    if manifest_data is None:
        issues.append(_issue("MISSING_PACKAGE_MANIFEST", "package_manifest.json is missing"))
        return None
    try:
        manifest = HandoffPackageManifest.model_validate(manifest_data)
    except ValidationError as exc:
        issues.append(_issue("INVALID_PACKAGE_MANIFEST", str(exc), "package_manifest.json"))
        return None

    if manifest.schema_version != PACKAGE_SCHEMA_VERSION:
        issues.append(_issue("UNKNOWN_SCHEMA_VERSION", "invalid package manifest schema", "package_manifest.json"))
    if manifest.authority.value != "advisory_only":
        issues.append(_issue("NON_ADVISORY_AUTHORITY", "package authority must be advisory_only", "package_manifest.json"))
    if manifest.can_write_formal_state:
        issues.append(_issue("FORMAL_WRITE_PERMISSION", "package must not write formal state", "package_manifest.json"))

    artifacts = manifest.artifacts.model_dump(mode="json")
    for name, rel in artifacts.items():
        if not rel:
            continue
        path = package_dir / rel
        if not path.exists():
            issues.append(_issue("MISSING_REFERENCE", f"artifact {name} points to missing path {rel}", "package_manifest.json"))
    return manifest


def _chapter_indexes(source_manifest: dict[str, Any], issues: list[dict[str, str]]) -> list[int]:
    chapters = source_manifest.get("chapters", [])
    indexes = [chapter.get("chapter_index") for chapter in chapters]
    if any(not isinstance(index, int) for index in indexes):
        issues.append(_issue("INCONSISTENT_CHAPTER_INDEX", "source manifest contains non-integer chapter indexes", "source_input_manifest.json"))
        return []
    if sorted(indexes) != list(range(1, len(indexes) + 1)):
        issues.append(_issue("INCONSISTENT_CHAPTER_INDEX", "source manifest chapter indexes must be contiguous from 1", "source_input_manifest.json"))
    return indexes


def _validate_canonical_chapter_files(package_dir: Path, source_manifest: dict[str, Any], issues: list[dict[str, str]]) -> None:
    for chapter in source_manifest.get("chapters", []):
        chapter_id = chapter.get("chapter_id")
        if not chapter_id:
            issues.append(_issue("INCONSISTENT_CHAPTER_INDEX", "chapter_id is missing", "source_input_manifest.json"))
            continue
        canonical_path = package_dir / "canonical" / "chapters" / f"{chapter_id}.json"
        if not canonical_path.exists():
            issues.append(_issue("MISSING_REFERENCE", f"canonical chapter file is missing: {canonical_path.relative_to(package_dir).as_posix()}", "source_input_manifest.json"))


def _ensure_contiguous(chapters: list[int], arc_id: str, rel: str, issues: list[dict[str, str]]) -> None:
    if not chapters:
        issues.append(_issue("ILLEGAL_ARC_CHAPTER_RANGE", f"{arc_id} has no chapters", rel))
        return
    if chapters != list(range(chapters[0], chapters[-1] + 1)):
        issues.append(_issue("ILLEGAL_ARC_CHAPTER_RANGE", f"{arc_id} chapters must be contiguous", rel))


def _validate_arcs(json_by_rel: dict[str, dict[str, Any]], source_indexes: list[int], issues: list[dict[str, str]]) -> None:
    major_payload = json_by_rel.get("arcs/major_arcs.json")
    sub_payload = json_by_rel.get("arcs/sub_arcs.json")
    if not major_payload or not sub_payload:
        issues.append(_issue("MISSING_REFERENCE", "confirmed major/sub arc files are required"))
        return

    major_arcs = major_payload.get("arcs", [])
    sub_arcs = sub_payload.get("arcs", [])
    major_by_id = {arc.get("arc_candidate_id"): arc for arc in major_arcs}
    assigned: list[int] = []
    children_by_major: dict[str, list[dict[str, Any]]] = {str(arc_id): [] for arc_id in major_by_id}

    for arc in [*major_arcs, *sub_arcs]:
        _ensure_contiguous(arc.get("chapters_included", []), arc.get("arc_candidate_id", ""), "arcs/major_arcs.json" if arc in major_arcs else "arcs/sub_arcs.json", issues)

    for sub_arc in sub_arcs:
        parent = sub_arc.get("parent_candidate_id")
        if parent not in major_by_id:
            issues.append(_issue("INVALID_ARC_PARENT", f"sub arc has invalid parent {parent}", "arcs/sub_arcs.json"))
            continue
        children_by_major.setdefault(parent, []).append(sub_arc)
        assigned.extend(sub_arc.get("chapters_included", []))

    if sorted(assigned) != source_indexes:
        issues.append(_issue("CHAPTER_ARC_COVERAGE", "every chapter must belong to exactly one sub arc", "arcs/sub_arcs.json"))
    if len(assigned) != len(set(assigned)):
        issues.append(_issue("CHAPTER_ASSIGNED_MULTIPLE_SUB_ARCS", "chapter assigned to multiple sub arcs", "arcs/sub_arcs.json"))

    for major in major_arcs:
        arc_id = major.get("arc_candidate_id")
        children = children_by_major.get(arc_id, [])
        child_chapters = sorted({chapter for child in children for chapter in child.get("chapters_included", [])})
        if child_chapters != major.get("chapters_included", []):
            issues.append(_issue("MAJOR_ARC_CHILD_COVERAGE", f"major arc {arc_id} does not match child sub arcs", "arcs/major_arcs.json"))


def _validate_one_tracker(
    json_by_rel: dict[str, dict[str, Any]],
    *,
    rel: str,
    required: bool,
    source_indexes: set[int],
    issues: list[dict[str, str]],
) -> None:
    tracker = json_by_rel.get(rel)
    if not tracker:
        if required:
            issues.append(_issue("MISSING_REFERENCE", f"{rel} is required", rel))
        return
    for item in tracker.get("items", []):
        planted = item.get("planted", {})
        chapter_index = planted.get("chapter_index")
        if chapter_index is not None and chapter_index not in source_indexes:
            issues.append(_issue("TRACKER_MISSING_CHAPTER_REF", f"tracker planted chapter missing: {chapter_index}", rel))
        for update in item.get("updates", []):
            update_chapter = update.get("chapter_index")
            if update_chapter is not None and update_chapter not in source_indexes:
                issues.append(_issue("TRACKER_MISSING_CHAPTER_REF", f"tracker update chapter missing: {update_chapter}", rel))


def _validate_tracker_refs(json_by_rel: dict[str, dict[str, Any]], source_indexes: set[int], issues: list[dict[str, str]]) -> None:
    _validate_one_tracker(
        json_by_rel,
        rel="trackers/foreshadowing_tracker.json",
        required=True,
        source_indexes=source_indexes,
        issues=issues,
    )
    _validate_one_tracker(
        json_by_rel,
        rel="trackers/mystery_tracker.json",
        required=False,
        source_indexes=source_indexes,
        issues=issues,
    )
    _validate_one_tracker(
        json_by_rel,
        rel="trackers/relationship_debt_tracker.json",
        required=False,
        source_indexes=source_indexes,
        issues=issues,
    )
    _validate_one_tracker(
        json_by_rel,
        rel="trackers/world_rule_reveal_tracker.json",
        required=False,
        source_indexes=source_indexes,
        issues=issues,
    )


def _known_tracker_candidate_refs(json_by_rel: dict[str, dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for rel in [
        "trackers/foreshadowing_tracker.json",
        "trackers/mystery_tracker.json",
        "trackers/relationship_debt_tracker.json",
        "trackers/world_rule_reveal_tracker.json",
    ]:
        tracker = json_by_rel.get(rel)
        if not tracker:
            continue
        for item in tracker.get("items", []):
            refs.update(str(ref) for ref in item.get("candidate_history_refs", []) if ref)
    return refs


def _load_modules(json_by_rel: dict[str, dict[str, Any]], issues: list[dict[str, str]]) -> list[ModuleEnvelope]:
    modules: list[ModuleEnvelope] = []
    for rel in ["modules/chapter_modules.json", "modules/arc_modules.json", "modules/book_modules.json"]:
        payload = json_by_rel.get(rel)
        if not payload:
            continue
        for raw_module in payload.get("modules", []):
            try:
                modules.append(ModuleEnvelope.model_validate(raw_module))
            except ValidationError as exc:
                issues.append(_issue("INVALID_MODULE_ENVELOPE", str(exc), rel))
    return modules


def _validate_chapter_modules(
    json_by_rel: dict[str, dict[str, Any]],
    source_indexes: set[int],
    issues: list[dict[str, str]],
) -> None:
    payload = json_by_rel.get("modules/chapter_modules.json")
    if not payload:
        issues.append(_issue("MISSING_REFERENCE", "modules/chapter_modules.json is required", "modules/chapter_modules.json"))
        return
    if payload.get("status") != "built_from_canonical_chapters":
        issues.append(
            _issue(
                "CHAPTER_MODULES_NOT_BUILT",
                "chapter_modules.json must be built from canonical chapters",
                "modules/chapter_modules.json",
            )
        )
    modules = payload.get("modules", [])
    if payload.get("module_count") != len(modules):
        issues.append(
            _issue(
                "MODULE_COUNT_MISMATCH",
                "chapter module_count must match modules length",
                "modules/chapter_modules.json",
            )
        )
    covered: set[int] = set()
    module_ids_by_chapter: dict[int, set[str]] = {index: set() for index in source_indexes}
    known_tracker_refs = _known_tracker_candidate_refs(json_by_rel)
    for module in modules:
        if module.get("scope") != "chapter":
            continue
        module_id = module.get("module_id", "")
        content = module.get("content", {})
        chapter_index = content.get("chapter_index")
        if isinstance(chapter_index, int):
            covered.add(chapter_index)
            module_ids_by_chapter.setdefault(chapter_index, set()).add(module_id)
        else:
            for evidence in module.get("evidence_refs", []):
                evidence_index = evidence.get("chapter_index")
                if isinstance(evidence_index, int):
                    covered.add(evidence_index)
                    module_ids_by_chapter.setdefault(evidence_index, set()).add(module_id)

        required_fields = CHAPTER_MODULE_REQUIRED_CONTENT_FIELDS.get(str(module_id), set())
        missing_fields = sorted(field for field in required_fields if not content.get(field))
        content_quality = content.get("content_quality")
        sparse_quality = not isinstance(content_quality, dict) or content_quality.get("status") != "usable"
        if missing_fields or sparse_quality:
            issues.append(
                _issue(
                    "CHAPTER_MODULE_CONTENT_DENSITY",
                    f"{module.get('module_instance_id', module_id)} has sparse content; missing={missing_fields}",
                    "modules/chapter_modules.json",
                )
            )

        tracker_refs = set(str(ref) for ref in content.get("tracker_candidate_refs", []) if ref)
        cross_refs = content.get("cross_reference_summary", {})
        if isinstance(cross_refs, dict):
            tracker_refs.update(str(ref) for ref in cross_refs.get("tracker_candidate_refs", []) if ref)
        unknown_tracker_refs = sorted(ref for ref in tracker_refs if ref not in known_tracker_refs)
        if unknown_tracker_refs:
            issues.append(
                _issue(
                    "CHAPTER_MODULE_TRACKER_REF",
                    f"{module.get('module_instance_id', module_id)} references unknown tracker candidates: {unknown_tracker_refs}",
                    "modules/chapter_modules.json",
                )
            )
    if covered != source_indexes:
        missing = sorted(source_indexes - covered)
        extra = sorted(covered - source_indexes)
        issues.append(
            _issue(
                "CHAPTER_MODULE_COVERAGE",
                f"chapter modules must cover every source chapter; missing={missing}, extra={extra}",
                "modules/chapter_modules.json",
            )
        )
    for chapter_index in sorted(source_indexes):
        missing_module_ids = sorted(REQUIRED_CHAPTER_MODULE_IDS - module_ids_by_chapter.get(chapter_index, set()))
        if missing_module_ids:
            issues.append(
                _issue(
                    "CHAPTER_MODULE_TYPE_COVERAGE",
                    f"chapter {chapter_index} is missing required chapter module types: {missing_module_ids}",
                    "modules/chapter_modules.json",
                )
            )


def _validate_module_refs(modules: list[ModuleEnvelope], source_indexes: set[int], issues: list[dict[str, str]]) -> None:
    module_ids = {module.module_instance_id for module in modules}
    for module in modules:
        for dependency in module.depends_on:
            if dependency not in module_ids:
                issues.append(_issue("UNKNOWN_MODULE_DEPENDENCY", f"{module.module_instance_id} depends on {dependency}"))
        for evidence in module.evidence_refs:
            if evidence.get("ref_type") == "canonical_chapter":
                chapter_index = evidence.get("chapter_index")
                if chapter_index not in source_indexes:
                    issues.append(_issue("MODULE_EVIDENCE_MISSING_SOURCE", f"{module.module_instance_id} references missing chapter {chapter_index}"))


def _validate_module_conflict_report(json_by_rel: dict[str, dict[str, Any]], issues: list[dict[str, str]]) -> None:
    rel = "modules/module_conflict_report.json"
    report = json_by_rel.get(rel)
    if not report:
        return
    if report.get("schema_version") != "story_analyzer.module_conflict_report.v1":
        issues.append(_issue("UNKNOWN_SCHEMA_VERSION", "invalid module conflict report schema", rel))
    if report.get("authority") != "advisory_only":
        issues.append(_issue("NON_ADVISORY_AUTHORITY", "module conflict report must be advisory_only", rel))
    if report.get("can_write_formal_state") is True:
        issues.append(_issue("FORMAL_WRITE_PERMISSION", "module conflict report must not write formal state", rel))
    conflicts = report.get("conflicts", [])
    if not isinstance(conflicts, list):
        issues.append(_issue("INVALID_MODULE_CONFLICT_REPORT", "conflicts must be a list", rel))
        return
    if report.get("conflict_count") != len(conflicts):
        issues.append(_issue("INVALID_MODULE_CONFLICT_REPORT", "conflict_count must match conflicts length", rel))
    for index, conflict in enumerate(conflicts, start=1):
        if not isinstance(conflict, dict):
            issues.append(_issue("INVALID_MODULE_CONFLICT_REPORT", f"conflict {index} must be an object", rel))
            continue
        missing = [
            field
            for field in ["conflict_id", "conflict_type", "rule_id", "severity", "module_instance_ids", "reason", "suggested_handling"]
            if not conflict.get(field)
        ]
        if missing:
            issues.append(_issue("INVALID_MODULE_CONFLICT_REPORT", f"conflict {index} missing fields: {missing}", rel))


def _validate_quality(json_by_rel: dict[str, dict[str, Any]], issues: list[dict[str, str]]) -> None:
    report = json_by_rel.get("quality_report.json")
    if not report:
        issues.append(_issue("MISSING_REFERENCE", "quality_report.json is required", "quality_report.json"))
        return
    if report.get("status") == "blocked" or report.get("blocking_issue_count", 0) > 0:
        issues.append(_issue("BLOCKING_QUALITY_ISSUE", "quality report contains blocking issues", "quality_report.json"))


def validate_handoff_package(package_dir: str | Path) -> dict[str, Any]:
    root = Path(package_dir)
    blocking_issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    json_by_rel: dict[str, dict[str, Any]] = {}

    if not root.exists():
        return {
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "validation_status": "failed",
            "checked_at": now_iso(),
            "blocking_issue_count": 1,
            "warning_count": 0,
            "blocking_issues": [_issue("PACKAGE_NOT_FOUND", f"package not found: {root}")],
            "warnings": [],
        }

    for path in sorted(root.rglob("*.json")):
        rel = relative_path(path, root)
        data = _safe_read_json(path, root, blocking_issues)
        if data is not None:
            json_by_rel[rel] = data
            schema = data.get("schema_version")
            if schema and schema not in KNOWN_SCHEMA_VERSIONS:
                blocking_issues.append(_issue("UNKNOWN_SCHEMA_VERSION", f"unknown schema_version {schema}", rel))
            _scan_json_safety(rel, data, blocking_issues)

    _validate_checksums(root, blocking_issues)
    _validate_manifest(root, json_by_rel, blocking_issues)

    source_manifest = json_by_rel.get("source_input_manifest.json", {})
    source_indexes = _chapter_indexes(source_manifest, blocking_issues) if source_manifest else []
    if source_manifest:
        _validate_canonical_chapter_files(root, source_manifest, blocking_issues)
    source_index_set = set(source_indexes)
    _validate_arcs(json_by_rel, source_indexes, blocking_issues)
    _validate_tracker_refs(json_by_rel, source_index_set, blocking_issues)
    _validate_chapter_modules(json_by_rel, source_index_set, blocking_issues)
    modules = _load_modules(json_by_rel, blocking_issues)
    _validate_module_refs(modules, source_index_set, blocking_issues)
    _validate_module_conflict_report(json_by_rel, blocking_issues)
    _validate_quality(json_by_rel, blocking_issues)

    status = "failed" if blocking_issues else "passed_with_warnings" if warnings else "passed"
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "validation_status": status,
        "checked_at": now_iso(),
        "blocking_issue_count": len(blocking_issues),
        "warning_count": len(warnings),
        "checks": {
            "json_parse": "passed" if not any(issue["code"] == "INVALID_JSON" for issue in blocking_issues) else "failed",
            "checksums": "passed" if not any(issue["code"].startswith("CHECKSUM") for issue in blocking_issues) else "failed",
            "authority": "passed" if not any(issue["code"] in {"NON_ADVISORY_AUTHORITY", "FORMAL_WRITE_PERMISSION"} for issue in blocking_issues) else "failed",
            "module_dependencies": "passed" if not any(issue["code"] == "UNKNOWN_MODULE_DEPENDENCY" for issue in blocking_issues) else "failed",
            "quality": "passed" if not any(issue["code"] == "BLOCKING_QUALITY_ISSUE" for issue in blocking_issues) else "failed",
        },
        "blocking_issues": blocking_issues,
        "warnings": warnings,
    }
