from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re

from pydantic import ValidationError

from ..analysis.canonical_builder import canonical_chapter_path
from ..config import DEFAULT_ENCODING, ensure_dir
from ..models.canonical import CanonicalChapterAnalysis
from ..quality.quality_gate import run_quality_gate
from ..state.pipeline_state import invalidate_for_change, record_pipeline_step


REPAIR_LOG_SCHEMA_VERSION = "story_analyzer.repair_log.v1"
REPAIR_DIRNAME = "repairs"
DEFAULT_MAX_ATTEMPTS = 2
SUPPORTED_ISSUE_CODES = {"NEW_TERM_POLLUTION"}
SEMANTIC_MANUAL_REPAIR_ACTION = "rerun_semantic_analysis_or_edit_raw_semantic_input"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repair_log_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "quality" / "repair_history.json"


def _repair_artifact_dir(run_dir: str | Path, chapter_id: str) -> Path:
    return Path(run_dir) / "quality" / REPAIR_DIRNAME / chapter_id


def _relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _load_log(run_dir: Path, max_attempts: int) -> dict[str, Any]:
    path = repair_log_path(run_dir)
    if not path.exists():
        return {
            "schema_version": REPAIR_LOG_SCHEMA_VERSION,
            "max_attempts_per_chapter": max_attempts,
            "attempts": [],
        }
    log = json.loads(path.read_text(encoding="utf-8-sig"))
    if log.get("schema_version") != REPAIR_LOG_SCHEMA_VERSION:
        raise ValueError(f"Unsupported repair log schema: {log.get('schema_version')}")
    log["max_attempts_per_chapter"] = max_attempts
    log.setdefault("attempts", [])
    return log


def _write_log(run_dir: Path, log: dict[str, Any]) -> None:
    path = repair_log_path(run_dir)
    ensure_dir(path.parent)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)


def _logged_attempt_count(log: dict[str, Any], chapter_id: str) -> int:
    return sum(1 for attempt in log.get("attempts", []) if attempt.get("chapter_id") == chapter_id)


def _repair_attempt_count(log: dict[str, Any], chapter_id: str) -> int:
    return sum(
        1
        for attempt in log.get("attempts", [])
        if attempt.get("chapter_id") == chapter_id and attempt.get("status") != "noop"
    )


def _next_attempt_number(log: dict[str, Any], chapter_id: str, max_attempts: int) -> int:
    repair_count = _repair_attempt_count(log, chapter_id)
    if repair_count >= max_attempts:
        raise ValueError(f"Repair attempt limit reached for {chapter_id}: {repair_count}/{max_attempts}")
    return _logged_attempt_count(log, chapter_id) + 1


def _chapter_report(report: dict[str, Any], chapter_id: str) -> dict[str, Any]:
    for chapter_report in report.get("chapter_reports", []):
        if chapter_report.get("chapter_id") == chapter_id:
            return chapter_report
    raise ValueError(f"Quality report does not contain {chapter_id}")


def _issue_codes(chapter_report: dict[str, Any]) -> list[str]:
    return [issue["code"] for issue in chapter_report.get("issues", []) if issue.get("severity") == "blocking"]


def _blocking_issues(chapter_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [issue for issue in chapter_report.get("issues", []) if issue.get("severity") == "blocking"]


def _has_semantic_blocking_issue(chapter_report: dict[str, Any]) -> bool:
    return any(issue.get("category") == "semantic" for issue in _blocking_issues(chapter_report))


def _sanitize_new_term(value: Any, path: str = "$") -> tuple[Any, list[str]]:
    if isinstance(value, str):
        if "[NEW_TERM]" not in value:
            return value, []
        cleaned = value.replace("[NEW_TERM]", "")
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned, [path]

    if isinstance(value, list):
        changed_paths: list[str] = []
        cleaned_items: list[Any] = []
        for index, item in enumerate(value):
            cleaned_item, item_paths = _sanitize_new_term(item, f"{path}[{index}]")
            cleaned_items.append(cleaned_item)
            changed_paths.extend(item_paths)
        return cleaned_items, changed_paths

    if isinstance(value, dict):
        changed_paths = []
        cleaned_dict: dict[str, Any] = {}
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            cleaned_item, item_paths = _sanitize_new_term(item, next_path)
            cleaned_dict[key] = cleaned_item
            changed_paths.extend(item_paths)
        return cleaned_dict, changed_paths

    return value, []


def _append_attempt(run_dir: Path, log: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
    log["attempts"].append(attempt)
    _write_log(run_dir, log)
    return attempt


def _blocked_attempt(
    run_dir: Path,
    log: dict[str, Any],
    *,
    chapter_id: str,
    chapter_index: int | None,
    attempt_number: int,
    issue_codes: list[str],
    reason: str,
    recommended_action: str = "manual_review",
) -> dict[str, Any]:
    attempt = {
        "attempt_id": f"{chapter_id}_attempt_{attempt_number:03d}",
        "chapter_id": chapter_id,
        "chapter_index": chapter_index,
        "attempt_number": attempt_number,
        "status": "blocked",
        "issue_codes": issue_codes,
        "supported_issue_codes": sorted(SUPPORTED_ISSUE_CODES),
        "changed_fields": [],
        "backup_ref": "",
        "output_ref": "",
        "quality_status_after": "",
        "reason": reason,
        "recommended_action": recommended_action,
        "created_at": _utc_now(),
    }
    record_pipeline_step(
        run_dir,
        step_id=f"repair_{chapter_id}_attempt_{attempt_number:03d}",
        step_type="chapter_repair",
        status="blocked",
        output_refs=[_relative_to_run(run_dir, repair_log_path(run_dir))],
        errors=[reason],
        scope={"chapter_id": chapter_id, **({"chapter_index": chapter_index} if chapter_index else {})},
    )
    return _append_attempt(run_dir, log, attempt)


def repair_chapter(
    run_dir: str | Path,
    *,
    chapter_id: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Repair one canonical chapter for supported deterministic quality issues.

    The service is intentionally narrow: M11 only repairs NEW_TERM pollution.
    Unsupported blocking issues are logged and left for manual review.
    """

    run_path = Path(run_dir)
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    report = run_quality_gate(run_path)
    chapter_report = _chapter_report(report, chapter_id)
    issue_codes = _issue_codes(chapter_report)
    chapter_index = chapter_report.get("chapter_index")
    log = _load_log(run_path, max_attempts)
    attempt_number = _next_attempt_number(log, chapter_id, max_attempts)

    if not issue_codes:
        attempt = {
            "attempt_id": f"{chapter_id}_attempt_{attempt_number:03d}",
            "chapter_id": chapter_id,
            "chapter_index": chapter_index,
            "attempt_number": attempt_number,
            "status": "noop",
            "issue_codes": [],
            "supported_issue_codes": sorted(SUPPORTED_ISSUE_CODES),
            "changed_fields": [],
            "backup_ref": "",
            "output_ref": "",
            "quality_status_after": report["status"],
            "reason": "no_blocking_issue",
            "created_at": _utc_now(),
        }
        return _append_attempt(run_path, log, attempt)

    unsupported = [code for code in issue_codes if code not in SUPPORTED_ISSUE_CODES]
    if unsupported:
        if _has_semantic_blocking_issue(chapter_report):
            return _blocked_attempt(
                run_path,
                log,
                chapter_id=chapter_id,
                chapter_index=chapter_index,
                attempt_number=attempt_number,
                issue_codes=issue_codes,
                reason="semantic_quality_issue_requires_manual_or_upstream_repair",
                recommended_action=SEMANTIC_MANUAL_REPAIR_ACTION,
            )
        return _blocked_attempt(
            run_path,
            log,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            attempt_number=attempt_number,
            issue_codes=issue_codes,
            reason="unsupported_quality_issue",
        )

    canonical_path = canonical_chapter_path(run_path, chapter_id)
    try:
        original_data = json.loads(canonical_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return _blocked_attempt(
            run_path,
            log,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            attempt_number=attempt_number,
            issue_codes=issue_codes,
            reason=f"invalid_json:{exc}",
        )

    repaired_data, changed_fields = _sanitize_new_term(original_data)
    if not changed_fields:
        return _blocked_attempt(
            run_path,
            log,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            attempt_number=attempt_number,
            issue_codes=issue_codes,
            reason="supported_issue_not_found_in_canonical",
        )

    try:
        chapter = CanonicalChapterAnalysis.model_validate(repaired_data)
    except ValidationError as exc:
        return _blocked_attempt(
            run_path,
            log,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            attempt_number=attempt_number,
            issue_codes=issue_codes,
            reason=f"repaired_schema_invalid:{exc}",
        )

    artifact_dir = ensure_dir(_repair_artifact_dir(run_path, chapter_id))
    backup_path = artifact_dir / f"attempt_{attempt_number:03d}_before.json"
    after_path = artifact_dir / f"attempt_{attempt_number:03d}_after.json"
    backup_path.write_text(json.dumps(original_data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    after_path.write_text(
        json.dumps(chapter.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding=DEFAULT_ENCODING,
    )
    canonical_path.write_text(
        json.dumps(chapter.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding=DEFAULT_ENCODING,
    )

    after_report = run_quality_gate(run_path)
    attempt = {
        "attempt_id": f"{chapter_id}_attempt_{attempt_number:03d}",
        "chapter_id": chapter_id,
        "chapter_index": chapter.chapter_index,
        "attempt_number": attempt_number,
        "status": "applied",
        "issue_codes": issue_codes,
        "supported_issue_codes": sorted(SUPPORTED_ISSUE_CODES),
        "changed_fields": changed_fields,
        "backup_ref": str(backup_path),
        "output_ref": str(after_path),
        "quality_status_after": after_report["status"],
        "reason": "new_term_pollution_removed",
        "created_at": _utc_now(),
    }
    _append_attempt(run_path, log, attempt)

    record_pipeline_step(
        run_path,
        step_id=f"repair_{chapter_id}_attempt_{attempt_number:03d}",
        step_type="chapter_repair",
        status="completed",
        schema_version=REPAIR_LOG_SCHEMA_VERSION,
        output_refs=[
            _relative_to_run(run_path, backup_path),
            _relative_to_run(run_path, after_path),
            _relative_to_run(run_path, repair_log_path(run_path)),
            _relative_to_run(run_path, canonical_path),
        ],
        scope={"chapter_id": chapter_id, "chapter_index": chapter.chapter_index},
    )
    record_pipeline_step(
        run_path,
        step_id="quality_gate",
        step_type="quality_gate",
        status="blocked" if after_report["status"] == "blocked" else "completed",
        schema_version=after_report.get("schema_version", ""),
        output_refs=["quality/quality_report.json"],
        errors=[
            issue["message"]
            for issue in after_report.get("issues", [])
            if issue.get("severity") == "blocking"
        ],
        warnings=[
            issue["message"]
            for issue in after_report.get("issues", [])
            if issue.get("severity") == "warning"
        ],
    )
    invalidate_for_change(
        run_path,
        change_type="chapter_repair_succeeded",
        scope={"chapter_id": chapter_id, "chapter_index": chapter.chapter_index},
        reason=f"{chapter_id} targeted repair attempt {attempt_number:03d} applied",
    )
    return attempt
