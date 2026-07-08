from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import copy
import re

from ..handoff.package_store import now_iso, read_json, write_json
from .handoff_validator import (
    SemanticValidator,
    is_generator_handoff_deliverable,
    repair_required_issues,
    validate_generator_handoff,
)


RepairAdapter = Callable[[dict[str, Any]], dict[str, Any]]

REPAIR_HISTORY_SCHEMA_VERSION = "generator_handoff.repair_history.v1"
REPAIR_ATTEMPT_SCHEMA_VERSION = "generator_handoff.repair_attempt.v1"
HANDOFF_DIRNAME = "generator_handoff"
MAX_REPAIR_ATTEMPTS = 5
INTERNAL_MARKERS = ("[NEW_TERM]", "source_model_id", "llm_call_id")
STATUS_ALIASES = {
    "active": "planted",
    "open": "planted",
    "pending": "planted",
    "partial": "partially_resolved",
    "partially_open": "partially_resolved",
    "partially-resolved": "partially_resolved",
    "closed": "resolved",
    "complete": "resolved",
    "completed": "resolved",
}


def _handoff_dir(path: str | Path) -> Path:
    root = Path(path)
    if root.name == HANDOFF_DIRNAME:
        return root
    return root / HANDOFF_DIRNAME


def _handoff_path(handoff_dir: Path) -> Path:
    return handoff_dir / "unified_generator_handoff.json"


def _history_path(handoff_dir: Path) -> Path:
    return handoff_dir / "repair_history.json"


def _load_history(handoff_dir: Path, max_attempts: int) -> dict[str, Any]:
    path = _history_path(handoff_dir)
    if path.exists():
        history = read_json(path)
        history.setdefault("attempts", [])
        history["max_attempts"] = max_attempts
        return history
    return {
        "schema_version": REPAIR_HISTORY_SCHEMA_VERSION,
        "max_attempts": max_attempts,
        "attempt_count": 0,
        "applied_repair_count": 0,
        "attempts": [],
    }


def _write_history(handoff_dir: Path, history: dict[str, Any]) -> None:
    history["attempt_count"] = len(history.get("attempts", []))
    history["applied_repair_count"] = sum(
        1
        for attempt in history.get("attempts", [])
        for repair in attempt.get("repairs", [])
        if repair.get("repair_status") == "applied"
    )
    write_json(_history_path(handoff_dir), history)


def _target_tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for part in path.split("."):
        if not part:
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(.*)$", part)
        if not match:
            raise KeyError(f"unsupported target path segment: {part}")
        tokens.append(match.group(1))
        for index_text in re.findall(r"\[(\d+)\]", match.group(2)):
            tokens.append(int(index_text))
    return tokens


def _get_value(root: Any, path: str) -> Any:
    node = root
    for token in _target_tokens(path):
        node = node[token]
    return node


def _set_value(root: Any, path: str, value: Any) -> None:
    tokens = _target_tokens(path)
    if not tokens:
        raise KeyError("empty target path")
    node = root
    for token in tokens[:-1]:
        node = node[token]
    node[tokens[-1]] = value


def _delete_value(root: Any, path: str) -> Any:
    tokens = _target_tokens(path)
    if not tokens:
        raise KeyError("empty target path")
    node = root
    for token in tokens[:-1]:
        node = node[token]
    token = tokens[-1]
    if isinstance(node, list) and isinstance(token, int):
        return node.pop(token)
    if isinstance(node, dict) and isinstance(token, str):
        return node.pop(token)
    raise KeyError(f"cannot delete target path: {path}")


def _target_parent_material_path(path: str) -> str:
    match = re.match(r"^(generator_materials\[\d+\])(?:\.|$)", path)
    if not match:
        raise KeyError(f"target is not a generator material: {path}")
    return match.group(1)


def _target_material_index(path: str) -> int:
    match = re.match(r"^generator_materials\[(\d+)\](?:\.|$)", path)
    if not match:
        raise KeyError(f"target is not a generator material: {path}")
    return int(match.group(1))


def _target_parent_foreshadowing_path(path: str) -> str:
    match = re.match(r"^(foreshadowing_registry\.items\[\d+\])(?:\.|$)", path)
    if not match:
        raise KeyError(f"target is not a foreshadowing item: {path}")
    return match.group(1)


def _default_selection_tags(material: dict[str, Any]) -> list[str]:
    source_dependence = material.get("source_dependence")
    module_type = material.get("module_type")
    if source_dependence == "source_free":
        return ["original_writing"]
    if source_dependence == "source_bound":
        return ["continuation"]
    if module_type in {"arc_structure", "adaptable_setting"}:
        return ["hybrid_adaptation"]
    return ["hybrid_adaptation"]


def _default_abstraction_level(material: dict[str, Any]) -> str:
    source_dependence = material.get("source_dependence")
    if source_dependence == "source_free":
        return "abstract"
    if source_dependence == "source_bound":
        return "source_specific"
    return "semi_abstract"


def _evidence_text(issue: dict[str, Any]) -> str:
    texts = []
    for packet in issue.get("evidence_packets") or []:
        for item in packet.get("evidence_items") or []:
            text = item.get("quote") or item.get("evidence_text") or ""
            if text:
                texts.append(str(text).strip())
    for item in issue.get("near_source_evidence") or []:
        text = item.get("evidence_text") or item.get("text") or item.get("near_source_summary") or ""
        if text:
            texts.append(str(text).strip())
    return " ".join(texts).strip()


def _replace_term(value: Any, term: str, replacement: str) -> Any:
    if isinstance(value, str):
        return re.sub(re.escape(term), replacement, value, flags=re.IGNORECASE)
    if isinstance(value, list):
        return [_replace_term(item, term, replacement) for item in value]
    if isinstance(value, dict):
        return {key: _replace_term(item, term, replacement) for key, item in value.items()}
    return value


def _strip_internal_markers(value: Any) -> Any:
    if isinstance(value, str):
        cleaned = value
        for marker in INTERNAL_MARKERS:
            cleaned = cleaned.replace(marker, "")
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned
    if isinstance(value, list):
        return [_strip_internal_markers(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_internal_markers(item) for key, item in value.items()}
    return value


def _repair_material_schema(handoff: dict[str, Any], issue: dict[str, Any]) -> tuple[str, Any, Any, str]:
    target = issue.get("target_path", "")
    material = _get_value(handoff, target)
    if not isinstance(material, dict):
        raise ValueError("target material is not an object")
    before = copy.deepcopy(material)
    missing = set((issue.get("current_value") or {}).get("missing_fields") or [])
    if "material_id" in missing and not material.get("material_id"):
        material["material_id"] = f"GM_REPAIRED_{_target_material_index(target) + 1:03d}"
    if "module_type" in missing and not material.get("module_type"):
        material["module_type"] = "narrative_mechanism"
    if "source_dependence" in missing and not material.get("source_dependence"):
        material["source_dependence"] = "adaptable"
    if "abstraction_level" in missing and not material.get("abstraction_level"):
        material["abstraction_level"] = _default_abstraction_level(material)
    if "granularity" in missing and not material.get("granularity"):
        material["granularity"] = "material"
    if "selection_tags" in missing and not material.get("selection_tags"):
        material["selection_tags"] = _default_selection_tags(material)
    if "content" in missing and not material.get("content"):
        evidence = _evidence_text(issue)
        if not evidence:
            raise ValueError("evidence_insufficient")
        material["content"] = {"source_supported_summary": evidence}
    if "source_refs" in missing and not material.get("source_refs"):
        raise ValueError("unsafe_repair_would_invent_content")
    return "rule_material_schema", before, copy.deepcopy(material), "filled safe material defaults"


def _repair_missing_selection_tags(handoff: dict[str, Any], issue: dict[str, Any]) -> tuple[str, Any, Any, str]:
    material_path = _target_parent_material_path(issue.get("target_path", ""))
    material = _get_value(handoff, material_path)
    before = copy.deepcopy(material.get("selection_tags"))
    material["selection_tags"] = _default_selection_tags(material)
    return "rule_selection_tags", before, copy.deepcopy(material["selection_tags"]), "filled selection_tags"


def _repair_material_enum(handoff: dict[str, Any], issue: dict[str, Any]) -> tuple[str, Any, Any, str]:
    path = issue.get("target_path", "")
    before = copy.deepcopy(_get_value(handoff, path))
    material = _get_value(handoff, _target_parent_material_path(path))
    if path.endswith(".module_type"):
        material["module_type"] = "narrative_mechanism"
        return "rule_material_enum", before, material["module_type"], "normalized module_type"
    if path.endswith(".abstraction_level"):
        material["abstraction_level"] = _default_abstraction_level(material)
        return "rule_material_enum", before, material["abstraction_level"], "normalized abstraction_level"
    if path.endswith(".source_dependence"):
        material["source_dependence"] = "adaptable"
        return "rule_material_enum", before, material["source_dependence"], "normalized source_dependence"
    raise ValueError("unsupported_material_enum")


def _repair_empty_material_content(handoff: dict[str, Any], issue: dict[str, Any]) -> tuple[str, Any, Any, str]:
    evidence = _evidence_text(issue)
    if evidence:
        path = issue.get("target_path", "")
        before = copy.deepcopy(_get_value(handoff, path))
        after = {"source_supported_summary": evidence}
        _set_value(handoff, path, after)
        return "evidence_content_fill", before, after, "filled content from near-source evidence"
    material_path = _target_parent_material_path(issue.get("target_path", ""))
    before = copy.deepcopy(_get_value(handoff, material_path))
    _delete_value(handoff, material_path)
    return "rule_remove_empty_material", before, None, "removed empty material"


def _repair_source_free_leak(handoff: dict[str, Any], issue: dict[str, Any]) -> tuple[str, Any, Any, str]:
    path = issue.get("target_path", "")
    term = str(issue.get("current_value") or "")
    if not term:
        raise ValueError("target_path_not_found")
    before = copy.deepcopy(_get_value(handoff, path))
    after = _replace_term(before, term, "source-specific role")
    _set_value(handoff, path, after)
    return "rule_de_name_source_free", before, copy.deepcopy(after), f"replaced leaked source term: {term}"


def _repair_internal_marker(handoff: dict[str, Any], issue: dict[str, Any]) -> tuple[str, Any, Any, str]:
    path = issue.get("target_path", "")
    before = copy.deepcopy(_get_value(handoff, path))
    after = _strip_internal_markers(before)
    _set_value(handoff, path, after)
    return "rule_remove_internal_marker", before, copy.deepcopy(after), "removed internal analyzer marker"


def _repair_source_bound_from_evidence(
    handoff: dict[str, Any],
    issue: dict[str, Any],
    repair_adapter: RepairAdapter | None,
) -> tuple[str, Any, Any, str]:
    evidence = _evidence_text(issue)
    if not evidence:
        raise ValueError("evidence_insufficient")
    path = issue.get("target_path", "")
    before = copy.deepcopy(_get_value(handoff, path))
    if repair_adapter is not None:
        response = repair_adapter(
            {
                "issue": issue,
                "target_path": path,
                "current_value": before,
                "near_source_evidence": issue.get("near_source_evidence") or [],
                "evidence_packets": issue.get("evidence_packets") or [],
                "repair_constraints": [
                    "Only use supplied evidence_packets or near_source_evidence.",
                    "Do not add facts, relationships, or settings absent from evidence.",
                    "Preserve source_refs.",
                ],
            }
        )
        if not isinstance(response, dict):
            raise ValueError("evidence_insufficient")
        if response.get("repair_status") == "evidence_insufficient":
            raise ValueError("evidence_insufficient")
        if "content" in response:
            after = response["content"]
        else:
            after = {"source_supported_summary": evidence}
    else:
        after = {"source_supported_summary": evidence}
    _set_value(handoff, path, after)
    return "evidence_source_bound_rewrite", before, copy.deepcopy(after), "rewrote content from near-source evidence"


def _repair_foreshadowing_status(handoff: dict[str, Any], issue: dict[str, Any]) -> tuple[str, Any, Any, str]:
    path = issue.get("target_path", "")
    before = copy.deepcopy(_get_value(handoff, path))
    normalized = STATUS_ALIASES.get(str(before).strip().lower(), "planted")
    _set_value(handoff, path, normalized)
    return "rule_foreshadowing_status", before, normalized, "normalized foreshadowing status enum"


def _repair_foreshadowing_conflict(handoff: dict[str, Any], issue: dict[str, Any]) -> tuple[str, Any, Any, str]:
    path = issue.get("target_path", "")
    item = _get_value(handoff, path)
    if not isinstance(item, dict):
        raise ValueError("target_path_not_found")
    before = copy.deepcopy(item)
    status = item.get("status")
    if status == "resolved" and item.get("open_questions"):
        item["status"] = "partially_resolved"
    elif status == "planted" and item.get("resolved_in_chapter"):
        chapter = item.pop("resolved_in_chapter")
        item["status"] = "partially_resolved"
        item.setdefault("partial_resolution_chapters", [])
        if chapter not in item["partial_resolution_chapters"]:
            item["partial_resolution_chapters"].append(chapter)
    elif status == "partially_resolved" and item.get("resolved_in_chapter") and not item.get("partial_resolution_chapters"):
        item["partial_resolution_chapters"] = [item.pop("resolved_in_chapter")]
    else:
        raise ValueError("unsupported_foreshadowing_conflict")
    return "rule_foreshadowing_status_conflict", before, copy.deepcopy(item), "normalized foreshadowing status fields"


def _apply_issue_repair(
    handoff: dict[str, Any],
    issue: dict[str, Any],
    *,
    attempt_index: int,
    repair_index: int,
    repair_adapter: RepairAdapter | None,
) -> dict[str, Any]:
    code = issue.get("code")
    target_path = issue.get("target_path", "")
    before: Any = None
    after: Any = None
    repair_type = "unsupported"
    notes = ""
    status = "blocked"
    try:
        if code == "MATERIAL_SCHEMA_MISSING_FIELD":
            repair_type, before, after, notes = _repair_material_schema(handoff, issue)
        elif code == "MISSING_SELECTION_TAGS":
            repair_type, before, after, notes = _repair_missing_selection_tags(handoff, issue)
        elif code in {"INVALID_MATERIAL_MODULE_TYPE", "INVALID_ABSTRACTION_LEVEL", "INVALID_SOURCE_DEPENDENCE"}:
            repair_type, before, after, notes = _repair_material_enum(handoff, issue)
        elif code == "EMPTY_MATERIAL_CONTENT":
            repair_type, before, after, notes = _repair_empty_material_content(handoff, issue)
        elif code == "SOURCE_FREE_SOURCE_TERM_LEAK":
            repair_type, before, after, notes = _repair_source_free_leak(handoff, issue)
        elif code == "INTERNAL_MARKER_LEAK":
            repair_type, before, after, notes = _repair_internal_marker(handoff, issue)
        elif code == "SOURCE_BOUND_EVIDENCE_MISMATCH":
            repair_type, before, after, notes = _repair_source_bound_from_evidence(handoff, issue, repair_adapter)
        elif code == "FORESHADOWING_STATUS_INVALID":
            repair_type, before, after, notes = _repair_foreshadowing_status(handoff, issue)
        elif code == "FORESHADOWING_STATUS_CONFLICT":
            repair_type, before, after, notes = _repair_foreshadowing_conflict(handoff, issue)
        elif code in {"EVIDENCE_INSUFFICIENT", "SEMANTIC_VALIDATION_INSUFFICIENT"}:
            status = "evidence_insufficient"
            notes = "near-source evidence is insufficient; repair did not invent content"
        elif code in {"MISSING_MATERIAL_SOURCE_REFS", "MISSING_SOURCE_REFERENCE"}:
            status = "unsafe_repair_would_invent_content"
            notes = "source_refs cannot be invented safely"
        else:
            status = "compiler_required"
            notes = f"unsupported repair code: {code}"
    except KeyError:
        status = "target_path_not_found"
        notes = "target_path could not be resolved"
    except ValueError as exc:
        status = str(exc) or "blocked"
        notes = status
    else:
        if status == "blocked":
            status = "applied"
    return {
        "attempt_index": attempt_index,
        "repair_id": f"REP{repair_index:03d}",
        "issue_id": issue.get("issue_id", ""),
        "issue_code": code,
        "repair_type": repair_type,
        "target_path": target_path,
        "source_refs": issue.get("source_refs") or [],
        "before": before,
        "after": after,
        "repair_status": status,
        "evidence_used": _evidence_used_ids(issue),
        "notes": notes,
    }


def _attempt_markdown(attempt: dict[str, Any]) -> str:
    lines = [
        f"# Handoff Repair Attempt {attempt['attempt_index']:03d}",
        "",
        f"- status before: {attempt.get('validation_status_before', '')}",
        f"- status after: {attempt.get('validation_status_after', '')}",
        f"- repairs: {len(attempt.get('repairs', []))}",
        "",
        "## Repairs",
    ]
    for repair in attempt.get("repairs", []):
        lines.extend(
            [
                "",
                f"### {repair.get('repair_id')} {repair.get('issue_code')}",
                "",
                f"- status: {repair.get('repair_status')}",
                f"- type: {repair.get('repair_type')}",
                f"- target: {repair.get('target_path')}",
                f"- issue: {repair.get('issue_id')}",
                f"- notes: {repair.get('notes')}",
            ]
        )
    return "\n".join(lines) + "\n"


def _failure_markdown(report: dict[str, Any]) -> str:
    return (
        "# Generator Handoff Repair Failed\n\n"
        f"- reason: {report['failure_reason']}\n"
        f"- attempts: {report['attempt_count']}\n"
        f"- last validation status: {report.get('last_validation_report', {}).get('validation_status', '')}\n\n"
        f"{report['user_message']}\n"
    )


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _clear_success_artifacts(handoff_dir: Path) -> None:
    _unlink_if_exists(handoff_dir / "unified_generator_handoff.validated.json")


def _clear_failure_artifacts(handoff_dir: Path) -> None:
    _unlink_if_exists(handoff_dir / "handoff_failed_report.json")
    _unlink_if_exists(handoff_dir / "handoff_failed_report.md")


def _write_attempt_artifacts(handoff_dir: Path, attempt: dict[str, Any], handoff: dict[str, Any]) -> None:
    attempt_index = attempt["attempt_index"]
    write_json(handoff_dir / f"repair_attempt_{attempt_index:03d}.json", attempt)
    (handoff_dir / f"repair_attempt_{attempt_index:03d}_report.md").write_text(
        _attempt_markdown(attempt),
        encoding="utf-8",
    )
    write_json(handoff_dir / "unified_generator_handoff.repaired.json", handoff)
    write_json(_handoff_path(handoff_dir), handoff)


def _finalize_passed(handoff_dir: Path, handoff: dict[str, Any], history: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    _clear_failure_artifacts(handoff_dir)
    validated_path = handoff_dir / "unified_generator_handoff.validated.json"
    history["repair_status"] = "passed"
    history["final_validation_status"] = report.get("validation_status")
    history["validated_handoff"] = str(validated_path)
    history["failed_report"] = ""
    history["completed_at"] = now_iso()
    _write_history(handoff_dir, history)
    handoff["handoff_status"] = "passed"
    handoff["validator_summary"] = {
        "validation_status": report.get("validation_status"),
        "blocking_issue_count": report.get("blocking_issue_count", 0),
        "warning_count": report.get("warning_count", 0),
        "checked_at": report.get("checked_at", ""),
    }
    handoff["repair_history"] = history
    write_json(_handoff_path(handoff_dir), handoff)
    write_json(validated_path, handoff)
    return {
        "repair_status": "passed",
        "attempt_count": len(history.get("attempts", [])),
        "validation_status": report.get("validation_status"),
        "validated_handoff": str(validated_path),
        "failed_report": "",
    }


def _write_failed_report(
    handoff_dir: Path,
    *,
    history: dict[str, Any],
    last_report: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    _clear_success_artifacts(handoff_dir)
    failed = {
        "handoff_status": "failed",
        "failure_reason": reason,
        "attempt_count": len(history.get("attempts", [])),
        "last_validation_report": last_report,
        "user_message": "交接包连续修正仍未通过，请尝试其它文章或人工检查源文本章节切分。",
    }
    json_path = handoff_dir / "handoff_failed_report.json"
    md_path = handoff_dir / "handoff_failed_report.md"
    history["repair_status"] = "failed"
    history["final_validation_status"] = last_report.get("validation_status")
    history["validated_handoff"] = ""
    history["failed_report"] = str(json_path)
    history["failure_reason"] = reason
    history["completed_at"] = now_iso()
    _write_history(handoff_dir, history)
    write_json(json_path, failed)
    md_path.write_text(_failure_markdown(failed), encoding="utf-8")
    return {
        "repair_status": "failed",
        "attempt_count": failed["attempt_count"],
        "validation_status": last_report.get("validation_status"),
        "validated_handoff": "",
        "failed_report": str(json_path),
        "failure_reason": reason,
    }


def _repairable_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    return repair_required_issues(report)


def _is_deleting_material_issue(issue: dict[str, Any]) -> bool:
    return issue.get("code") == "EMPTY_MATERIAL_CONTENT" and not _evidence_text(issue)


def _material_index_for_issue(issue: dict[str, Any]) -> int:
    try:
        return _target_material_index(issue.get("target_path", ""))
    except KeyError:
        return -1


def _ordered_repairable_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    def order(issue: dict[str, Any]) -> tuple[int, int]:
        if _is_deleting_material_issue(issue):
            return (1, -_material_index_for_issue(issue))
        return (0, 0)

    return sorted(_repairable_issues(report), key=order)


def _evidence_used_ids(issue: dict[str, Any]) -> list[str]:
    used: list[str] = []
    for packet in issue.get("evidence_packets") or []:
        for item in packet.get("evidence_items") or []:
            evidence_id = item.get("evidence_id")
            if evidence_id:
                used.append(str(evidence_id))
    for item in issue.get("near_source_evidence") or []:
        ref_id = item.get("ref_id")
        if ref_id:
            used.append(str(ref_id))
    return used


def _is_deliverable_validation(report: dict[str, Any]) -> bool:
    return is_generator_handoff_deliverable(report)


def repair_generator_handoff(
    run_dir: str | Path,
    *,
    max_attempts: int = MAX_REPAIR_ATTEMPTS,
    evidence_mode: str = "auto",
    repair_adapter: RepairAdapter | None = None,
    semantic_validator: SemanticValidator | None = None,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    handoff_dir = _handoff_dir(run_dir)
    handoff_path = _handoff_path(handoff_dir)
    handoff = read_json(handoff_path)
    history = _load_history(handoff_dir, max_attempts)

    report = validate_generator_handoff(
        handoff_dir,
        attempt_index=len(history.get("attempts", [])),
        evidence_mode=evidence_mode,
        semantic_validator=semantic_validator,
    )
    if _is_deliverable_validation(report):
        return _finalize_passed(handoff_dir, handoff, history, report)
    _clear_success_artifacts(handoff_dir)

    completed_attempts = len(history.get("attempts", []))
    if completed_attempts >= max_attempts:
        return _write_failed_report(
            handoff_dir,
            history=history,
            last_report=report,
            reason="max_attempts_exceeded",
        )

    for attempt_index in range(completed_attempts + 1, max_attempts + 1):
        repairable_issues = _ordered_repairable_issues(report)
        if not repairable_issues:
            return _write_failed_report(
                handoff_dir,
                history=history,
                last_report=report,
                reason="non_repairable_issues_present",
            )
        handoff = read_json(handoff_path)
        before_status = report.get("validation_status")
        repairs = [
            _apply_issue_repair(
                handoff,
                issue,
                attempt_index=attempt_index,
                repair_index=index,
                repair_adapter=repair_adapter,
            )
            for index, issue in enumerate(repairable_issues, start=1)
        ]
        attempt = {
            "schema_version": REPAIR_ATTEMPT_SCHEMA_VERSION,
            "attempt_index": attempt_index,
            "started_at": now_iso(),
            "validation_status_before": before_status,
            "repairs": repairs,
            "completed_at": now_iso(),
        }
        history["attempts"].append(attempt)
        _write_attempt_artifacts(handoff_dir, attempt, handoff)
        _write_history(handoff_dir, history)

        report = validate_generator_handoff(
            handoff_dir,
            attempt_index=attempt_index,
            evidence_mode=evidence_mode,
            semantic_validator=semantic_validator,
        )
        attempt["validation_status_after"] = report.get("validation_status")
        _write_attempt_artifacts(handoff_dir, attempt, handoff)
        _write_history(handoff_dir, history)
        if _is_deliverable_validation(report):
            return _finalize_passed(handoff_dir, handoff, history, report)

    return _write_failed_report(
        handoff_dir,
        history=history,
        last_report=report,
        reason="max_attempts_exceeded",
    )
