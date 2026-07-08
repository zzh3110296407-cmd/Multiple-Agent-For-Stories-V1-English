from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from pydantic import ValidationError

from ..analysis.canonical_builder import canonical_dir
from ..config import DEFAULT_ENCODING, ensure_dir
from ..models.canonical import CanonicalChapterAnalysis


QUALITY_DIRNAME = "quality"
MIN_TRACKER_CONFIDENCE = 0.5
SEMANTIC_ISSUE_CODES = {
    "SEMANTIC_EVENTS_MISSING",
    "SEMANTIC_SUMMARY_MISSING",
    "CHAPTER_FUNCTION_MISSING",
    "READER_EXPERIENCE_MISSING",
    "TRACKER_CANDIDATE_MISSING_EVIDENCE",
    "TRACKER_CANDIDATE_LOW_CONFIDENCE",
    "CHARACTER_CHANGE_MISSING_CHARACTER",
    "RELATIONSHIP_CHANGE_INCOMPLETE_PARTICIPANTS",
}


def _contains_new_term(value: Any) -> bool:
    if isinstance(value, str):
        return "[NEW_TERM]" in value
    if isinstance(value, list):
        return any(_contains_new_term(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_new_term(item) for item in value.values())
    return False


def _chapter_quality_path(run_dir: Path, chapter_id: str) -> Path:
    return run_dir / QUALITY_DIRNAME / f"{chapter_id}_quality.json"


def _quality_report_path(run_dir: Path) -> Path:
    return run_dir / QUALITY_DIRNAME / "quality_report.json"


def _issue(severity: str, code: str, message: str, *, path: str = "") -> dict[str, Any]:
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
        "category": "semantic" if code in SEMANTIC_ISSUE_CODES else "deterministic",
    }
    if path:
        issue["path"] = path
    return issue


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    if isinstance(value, dict):
        return not value or all(_is_blank(item) for item in value.values())
    return False


def _check_semantic_quality(chapter: CanonicalChapterAnalysis) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    facts = chapter.story_facts
    structural = chapter.structural_analysis

    if chapter.source.text_length > 0 and not facts.events:
        issues.append(
            _issue(
                "blocking",
                "SEMANTIC_EVENTS_MISSING",
                "chapter has source text but no canonical story events",
                path="story_facts.events",
            )
        )

    if not facts.chapter_summary.strip():
        issues.append(
            _issue(
                "warning",
                "SEMANTIC_SUMMARY_MISSING",
                "chapter summary is missing",
                path="story_facts.chapter_summary",
            )
        )

    if _is_blank(structural.chapter_function):
        issues.append(
            _issue(
                "warning",
                "CHAPTER_FUNCTION_MISSING",
                "chapter function is missing",
                path="structural_analysis.chapter_function",
            )
        )

    if _is_blank(structural.dominant_reader_experience):
        issues.append(
            _issue(
                "warning",
                "READER_EXPERIENCE_MISSING",
                "dominant reader experience is missing",
                path="structural_analysis.dominant_reader_experience",
            )
        )

    for index, candidate in enumerate(chapter.tracker_candidates):
        path = f"tracker_candidates[{index}]"
        evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate, dict) else []
        confidence = candidate.get("confidence_score", 0.0) if isinstance(candidate, dict) else 0.0
        if not evidence_refs:
            issues.append(
                _issue(
                    "warning",
                    "TRACKER_CANDIDATE_MISSING_EVIDENCE",
                    "tracker candidate has no evidence refs",
                    path=f"{path}.evidence_refs",
                )
            )
        if confidence < MIN_TRACKER_CONFIDENCE:
            issues.append(
                _issue(
                    "warning",
                    "TRACKER_CANDIDATE_LOW_CONFIDENCE",
                    f"tracker candidate confidence is below {MIN_TRACKER_CONFIDENCE}",
                    path=f"{path}.confidence_score",
                )
            )

    for index, change in enumerate(facts.character_state_changes):
        if not isinstance(change, dict) or not str(change.get("character", "")).strip():
            issues.append(
                _issue(
                    "blocking",
                    "CHARACTER_CHANGE_MISSING_CHARACTER",
                    "character state change is missing character",
                    path=f"story_facts.character_state_changes[{index}].character",
                )
            )

    for index, change in enumerate(facts.relationship_changes):
        participants = change.get("participants", []) if isinstance(change, dict) else []
        if not isinstance(participants, list) or len([item for item in participants if str(item).strip()]) < 2:
            issues.append(
                _issue(
                    "blocking",
                    "RELATIONSHIP_CHANGE_INCOMPLETE_PARTICIPANTS",
                    "relationship change needs at least two participants",
                    path=f"story_facts.relationship_changes[{index}].participants",
                )
            )

    return issues


def _check_canonical_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        raw = json.loads(path.read_text(encoding=DEFAULT_ENCODING))
        chapter = CanonicalChapterAnalysis.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        return (
            {
                "chapter_id": path.stem,
                "schema_status": "missing_required_field",
                "requires_repair_pass": True,
                "blocking_issue_count": 1,
                "warning_count": 0,
            },
            [
                {
                    "severity": "blocking",
                    "code": "INVALID_CANONICAL_SCHEMA",
                    "message": str(exc),
                }
            ],
        )

    if chapter.quality.chapter_boundary_status == "failed":
        issues.append(_issue("blocking", "CHAPTER_BOUNDARY_FAILED", "chapter boundary status is failed"))
    elif chapter.quality.chapter_boundary_status == "suspicious":
        issues.append(_issue("warning", "CHAPTER_BOUNDARY_SUSPICIOUS", "chapter boundary status is suspicious"))

    if chapter.quality.title_status == "suspicious":
        issues.append(_issue("warning", "TITLE_SUSPICIOUS", "chapter title status is suspicious"))

    if _contains_new_term(chapter.model_dump(mode="json")):
        issues.append(_issue("blocking", "NEW_TERM_POLLUTION", "canonical output contains [NEW_TERM]"))

    issues.extend(_check_semantic_quality(chapter))

    blocking_count = sum(1 for issue in issues if issue["severity"] == "blocking")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    chapter_report = {
        "chapter_id": chapter.chapter_id,
        "chapter_index": chapter.chapter_index,
        "semantic_source": chapter.quality.semantic_source,
        "semantic_analyzer_id": chapter.quality.semantic_analyzer_id,
        "semantic_input_ref": chapter.quality.semantic_input_ref,
        "schema_status": chapter.quality.schema_status,
        "requires_repair_pass": chapter.quality.requires_repair_pass or blocking_count > 0,
        "blocking_issue_count": blocking_count,
        "warning_count": warning_count,
        "issues": issues,
    }
    return chapter_report, issues


def _counts_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def run_quality_gate(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir)
    root = canonical_dir(run_path)
    if not root.exists():
        raise FileNotFoundError(root)

    quality_dir = ensure_dir(run_path / QUALITY_DIRNAME)
    chapter_reports: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []

    for canonical_path in sorted(root.glob("chapter_*.json")):
        chapter_report, issues = _check_canonical_file(canonical_path)
        chapter_reports.append(chapter_report)
        for issue in issues:
            enriched = {"chapter_id": chapter_report["chapter_id"], **issue}
            all_issues.append(enriched)
        _chapter_quality_path(run_path, chapter_report["chapter_id"]).write_text(
            json.dumps(chapter_report, ensure_ascii=False, indent=2),
            encoding=DEFAULT_ENCODING,
        )

    if not chapter_reports:
        raise ValueError(f"No canonical chapter files found in {root}")

    report = {
        "schema_version": "story_analyzer.quality_report.v1",
        "chapter_count": len(chapter_reports),
        "semantic_sources": _counts_by_key(chapter_reports, "semantic_source"),
        "blocking_issue_count": sum(report["blocking_issue_count"] for report in chapter_reports),
        "warning_count": sum(report["warning_count"] for report in chapter_reports),
        "status": "blocked"
        if any(report["blocking_issue_count"] for report in chapter_reports)
        else "passed",
        "chapter_reports": chapter_reports,
        "issues": all_issues,
    }
    _quality_report_path(run_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding=DEFAULT_ENCODING,
    )
    return report
