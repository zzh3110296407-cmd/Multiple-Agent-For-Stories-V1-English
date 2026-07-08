from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any
import json
import re

from .tracker_store import (
    foreshadowing_tracker_path,
    mystery_tracker_path,
    override_log_path,
    read_json,
    relationship_debt_tracker_path,
    tracker_semantic_recommendation_report_path,
    world_rule_reveal_tracker_path,
    write_json,
)


REPORT_SCHEMA_VERSION = "story_analyzer.tracker_semantic_recommendation_report.v1"
TRACKER_SPECS = {
    "foreshadowing": foreshadowing_tracker_path,
    "mystery": mystery_tracker_path,
    "relationship_debt": relationship_debt_tracker_path,
    "world_rule_reveal": world_rule_reveal_tracker_path,
}
RISK_RANK = {"low": 0, "medium": 1, "high": 2}
MERGE_THRESHOLD = 0.28


def _read_json_or_empty(path: Path, empty: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return empty
    return read_json(path)


def _tokens(text: str) -> set[str]:
    normalized = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalized))
    return {token for token in tokens if len(token) > 1 or "\u4e00" <= token <= "\u9fff"}


def _content_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = _tokens(str(left.get("canonical_content", "")))
    right_tokens = _tokens(str(right.get("canonical_content", "")))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens.intersection(right_tokens)
    union = left_tokens.union(right_tokens)
    return round(len(overlap) / len(union), 3)


def _chapter_index(item: dict[str, Any]) -> int | None:
    planted = item.get("planted")
    if isinstance(planted, dict) and isinstance(planted.get("chapter_index"), int):
        return planted["chapter_index"]
    return None


def _chapter_proximity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_chapter = _chapter_index(left)
    right_chapter = _chapter_index(right)
    if left_chapter is None or right_chapter is None:
        return 0.0
    distance = abs(left_chapter - right_chapter)
    if distance == 0:
        return 0.18
    if distance == 1:
        return 0.14
    if distance <= 3:
        return 0.08
    return 0.0


def _shared_history_score(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, list[str]]:
    left_refs = {str(ref) for ref in left.get("candidate_history_refs", []) if ref}
    right_refs = {str(ref) for ref in right.get("candidate_history_refs", []) if ref}
    shared = sorted(left_refs.intersection(right_refs))
    return (0.2 if shared else 0.0, shared)


def _merge_score(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, list[str]]:
    content = _content_similarity(left, right)
    proximity = _chapter_proximity(left, right)
    history, shared = _shared_history_score(left, right)
    score = round(min(1.0, content + proximity + history), 3)
    reasons = []
    if content >= 0.2:
        reasons.append("canonical_content_overlap")
    if proximity:
        reasons.append("nearby_planted_chapters")
    if shared:
        reasons.append("shared_candidate_history_refs")
    return score, reasons


def _load_tracker_items(run_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    items_by_type: dict[str, list[dict[str, Any]]] = {}
    for tracker_type, path_factory in TRACKER_SPECS.items():
        path = path_factory(run_dir)
        if not path.exists():
            items_by_type[tracker_type] = []
            continue
        tracker = read_json(path)
        normalized = []
        for item in tracker.get("items", []):
            candidate = dict(item)
            candidate["tracker_type"] = tracker_type
            normalized.append(candidate)
        items_by_type[tracker_type] = normalized
    return items_by_type


def _is_active_item(item: dict[str, Any]) -> bool:
    manual_override = item.get("manual_override") or {}
    resolution_method = str(manual_override.get("resolution_method") or "")
    if item.get("status") == "abandoned":
        return False
    if manual_override.get("active") and (
        resolution_method.startswith("merged_into:") or resolution_method.startswith("split_into:")
    ):
        return False
    return True


def _merge_candidates(items_by_type: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for tracker_type, items in items_by_type.items():
        active_items = [item for item in items if _is_active_item(item)]
        for left, right in combinations(active_items, 2):
            score, reasons = _merge_score(left, right)
            if score < MERGE_THRESHOLD:
                continue
            left_id = str(left.get("tracker_item_id", ""))
            right_id = str(right.get("tracker_item_id", ""))
            target_id, candidate_id = sorted([left_id, right_id])
            candidates.append(
                {
                    "tracker_type": tracker_type,
                    "target_item_id": target_id,
                    "candidate_item_id": candidate_id,
                    "similarity_score": score,
                    "recommendation": "review_for_possible_merge",
                    "reasons": reasons or ["weak_similarity_above_threshold"],
                    "recommended_review_points": [
                        "Check whether both tracker items refer to the same setup, question, debt, or world rule.",
                        "Confirm the merged item would preserve planted chapter and later update history.",
                    ],
                }
            )
    return sorted(
        candidates,
        key=lambda item: (-item["similarity_score"], item["tracker_type"], item["target_item_id"], item["candidate_item_id"]),
    )


def _risk(level: str, reasons: list[str], points: list[str]) -> dict[str, Any]:
    return {
        "semantic_risk_level": level,
        "risk_reasons": sorted(set(reasons)),
        "recommended_review_points": points,
    }


def _merge_operation_risk(index: int, event: dict[str, Any]) -> dict[str, Any]:
    before_items = event.get("before", [])
    target = before_items[0] if before_items else {}
    sources = before_items[1:] if isinstance(before_items, list) else []
    scores = [_merge_score(target, source)[0] for source in sources if isinstance(source, dict)]
    min_score = min(scores) if scores else 0.0
    if min_score < 0.18:
        risk = _risk(
            "high",
            ["merge_low_semantic_similarity"],
            ["Re-check that merged tracker items express the same narrative setup or unresolved question."],
        )
    elif min_score < MERGE_THRESHOLD:
        risk = _risk(
            "medium",
            ["merge_similarity_below_recommendation_threshold"],
            ["Review whether merge loses distinct evidence or timing."],
        )
    else:
        risk = _risk("low", [], ["Confirm the target item keeps source candidate history references."])
    return {
        "operation_index": index,
        "operation": "merge",
        "tracker_type": event.get("tracker_type", ""),
        "item_refs": [event.get("target_item_id"), *event.get("source_item_ids", [])],
        "similarity_score": round(min_score, 3),
        **risk,
    }


def _split_operation_risk(index: int, event: dict[str, Any]) -> dict[str, Any]:
    source = event.get("before", {})
    created = event.get("after", {}).get("created", []) if isinstance(event.get("after"), dict) else []
    reasons: list[str] = []
    points: list[str] = []
    if any(not item.get("candidate_history_refs") for item in created if isinstance(item, dict)):
        reasons.append("created_items_missing_candidate_history_refs")
        points.append("Attach candidate history refs or evidence refs to each split item before generator import.")
    for item in created:
        if isinstance(item, dict) and _content_similarity(source, item) >= 0.65:
            reasons.append("split_items_too_similar_to_source")
            points.append("Check whether the split creates truly separate narrative threads.")
            break
    if len(created) > 3:
        reasons.append("split_created_many_items")
        points.append("Review whether this should be a hierarchy instead of many sibling tracker items.")
    level = "high" if "created_items_missing_candidate_history_refs" in reasons else "medium" if reasons else "low"
    return {
        "operation_index": index,
        "operation": "split",
        "tracker_type": event.get("tracker_type", ""),
        "item_refs": [event.get("source_item_id"), *event.get("created_item_ids", [])],
        **_risk(level, reasons, points or ["Confirm each split item has distinct content and evidence."]),
    }


def _override_operation_risk(index: int, event: dict[str, Any]) -> dict[str, Any]:
    override = event.get("manual_override") or {}
    reasons: list[str] = []
    points: list[str] = []
    if override.get("status") == "uncertain":
        reasons.append("override_status_uncertain")
        points.append("Resolve the uncertain tracker status before using it as a hard generation constraint.")
    if not override.get("reason"):
        reasons.append("override_missing_reason")
        points.append("Add a concise reason so generator-side reviewers can audit the change.")
    if override.get("status") == "resolved" and not override.get("resolved_chapter_index"):
        reasons.append("resolved_override_missing_chapter")
        points.append("Confirm which chapter resolves the tracker item.")
    level = "medium" if reasons else "low"
    return {
        "operation_index": index,
        "operation": "override",
        "tracker_type": event.get("tracker_type", ""),
        "item_refs": [event.get("tracker_item_id")],
        **_risk(level, reasons, points or ["Confirm manual override is intentional and evidence-backed."]),
    }


def _operation_risks(run_dir: str | Path) -> list[dict[str, Any]]:
    log = _read_json_or_empty(
        override_log_path(run_dir),
        {"schema_version": "story_analyzer.tracker_override_log.v1", "events": []},
    )
    risks = []
    for index, event in enumerate(log.get("events", []), start=1):
        operation = event.get("operation") or "override"
        if operation == "merge":
            risks.append(_merge_operation_risk(index, event))
        elif operation == "split":
            risks.append(_split_operation_risk(index, event))
        else:
            risks.append(_override_operation_risk(index, event))
    return risks


def _aggregate_risk(operation_risks: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    if not operation_risks:
        return "low", [], ["No manual tracker edits require semantic risk review."]
    max_level = max(operation_risks, key=lambda item: RISK_RANK[item["semantic_risk_level"]])["semantic_risk_level"]
    reasons: list[str] = []
    points: list[str] = []
    for item in operation_risks:
        reasons.extend(item.get("risk_reasons", []))
        points.extend(item.get("recommended_review_points", []))
    return max_level, sorted(set(reasons)), sorted(set(points))


def _semantic_source_status(run_dir: str | Path) -> str:
    quality_path = Path(run_dir) / "quality" / "quality_report.json"
    if quality_path.exists():
        try:
            quality = json.loads(quality_path.read_text(encoding="utf-8-sig"))
            sources = quality.get("semantic_sources", {})
            if any(key not in {"", "deterministic_fallback"} and count for key, count in sources.items()):
                return "semantic_sources_available"
        except json.JSONDecodeError:
            return "deterministic_fallback"
    return "deterministic_fallback"


def build_tracker_semantic_recommendation_report(run_dir: str | Path) -> dict[str, Any]:
    items_by_type = _load_tracker_items(run_dir)
    merge_candidates = _merge_candidates(items_by_type)
    operation_risks = _operation_risks(run_dir)
    risk_level, risk_reasons, review_points = _aggregate_risk(operation_risks)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "available",
        "semantic_source_status": _semantic_source_status(run_dir),
        "authority": "advisory_only",
        "can_write_formal_state": False,
        "source_refs": {
            "tracker_refs": {
                tracker_type: f"trackers/{path_factory(run_dir).name}"
                for tracker_type, path_factory in TRACKER_SPECS.items()
            },
            "audit_log_ref": "trackers/tracker_override_log.json",
        },
        "semantic_risk_level": risk_level,
        "risk_reasons": risk_reasons,
        "recommended_review_points": review_points,
        "merge_candidate_count": len(merge_candidates),
        "merge_candidates": merge_candidates,
        "operation_risk_count": len(operation_risks),
        "operation_risks": operation_risks,
    }
    write_json(tracker_semantic_recommendation_report_path(run_dir), report)
    return report
