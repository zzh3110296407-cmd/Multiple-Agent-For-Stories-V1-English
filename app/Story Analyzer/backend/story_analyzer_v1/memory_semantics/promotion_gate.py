"""Memory semantics gate for foreshadowing promotion review."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


OPEN_TERMS = (
    "future",
    "unknown",
    "unresolved",
    "remains",
    "identity",
    "consequence",
    "hidden",
    "mystery",
    "secret",
    "后续",
    "未来",
    "未知",
    "未解",
    "悬念",
    "秘密",
    "身份",
)

WORLD_FACT_TERMS = (
    "exists",
    "explained",
    "rule",
    "rules",
    "constructed",
    "transit",
    "system",
    "academy",
    "class",
    "世界规则",
    "规则",
    "遵循",
    "构建",
    "系统",
    "学院",
    "存在",
    "说明",
)

PAYOFF_TERMS = ("payoff", "resolves", "resolved", "回收", "解决", "确认")

FUTURE_SETUP_TERMS = (
    "future",
    "will force",
    "will",
    "unknown",
    "unresolved",
    "mystery",
    "secret",
    "threat",
    "danger",
    "consequence",
    "cost",
    "risk",
    "后续",
    "未来",
    "未知",
    "未解",
    "悬念",
    "秘密",
    "威胁",
    "代价",
    "风险",
    "失控",
)

EXPLANATORY_REVEAL_TERMS = (
    "because",
    "was because",
    "is because",
    "revealed as",
    "confirmed as",
    "explained as",
    "这说明",
    "因为",
    "是因为",
    "实为",
    "原来",
    "真相是",
    "多为",
)


ABSTRACT_THEME_TERMS = ("主题", "宿命", "命运", "牺牲", "救赎", "觉醒", "成长", "自我", "悲剧性", "情感")

CONCRETE_FORESHADOWING_TERMS = (
    "身份",
    "计划",
    "档案",
    "隐藏区域",
    "领域",
    "胚胎",
    "契约",
    "活灵",
    "武器",
    "药物",
    "纯度",
    "失控",
    "未知",
    "门",
    "悬念",
    "unknown",
    "hidden",
    "plan",
    "identity",
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = str(text or "").lower()
    return any(term.lower() in lower for term in terms)


def _canonical(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").lower(), flags=re.UNICODE)


def _explicit_refs(content: str) -> list[str]:
    return sorted(set(re.findall(r"(?<![A-Za-z0-9])F\d{3,}(?![A-Za-z0-9])", str(content or ""), flags=re.I)))


def _looks_like_world_fact_statement(content: str, thread_type: str = "") -> bool:
    if not _contains_any(content, WORLD_FACT_TERMS):
        return False
    lower = str(content or "").lower()
    if thread_type == "world_rule_reveal":
        return True
    rule_shape = any(
        term in lower
        for term in (
            "rule",
            "rules",
            "constructed",
            "transit",
            "table-game",
            "system",
            "规则",
            "遵循",
            "构建",
            "自有领地",
        )
    )
    if not rule_shape:
        return False
    return not _contains_any(content, FUTURE_SETUP_TERMS)


def _looks_like_explanatory_reveal(content: str) -> bool:
    return _contains_any(content, EXPLANATORY_REVEAL_TERMS) and not _contains_any(content, FUTURE_SETUP_TERMS)


def _looks_like_abstract_theme_thread(content: str) -> bool:
    text = str(content or "").lower()
    if not _contains_any(text, ABSTRACT_THEME_TERMS):
        return False
    if re.search(r"个体通过.+(完成|实现).+(救赎|觉醒|成长)", text):
        return True
    return not _contains_any(text, CONCRETE_FORESHADOWING_TERMS)


def _semantic_key(content: str) -> str:
    text = str(content or "").lower()
    if "plan" in text or "计划" in text:
        return "long_horizon_plan"
    if ("weapon" in text or "artifact" in text or "武器" in text) and (
        "rule" in text or "规则" in text or "危险" in text
    ):
        return "dangerous_artifact_rule"
    if "bloodline" in text or "血统" in text:
        return "inherited_power_risk"
    if "identity" in text or "身份" in text:
        return "identity_mystery"
    if "patron" in text or "hidden" in text or "神秘" in text:
        return "hidden_patron"
    key = _canonical(content)
    return f"misc_{key[:24] or 'unknown'}"


def _tracked_overlap(content: str, tracked_contents: list[str]) -> bool:
    key = _canonical(content)
    candidate_semantic_key = _semantic_key(content)
    if len(key) < 8:
        return False
    for tracked in tracked_contents:
        tracked_key = _canonical(tracked)
        if not tracked_key:
            continue
        tracked_semantic_key = _semantic_key(tracked)
        if candidate_semantic_key == tracked_semantic_key and not candidate_semantic_key.startswith("misc_"):
            return True
        if key in tracked_key or tracked_key in key:
            return True
        if SequenceMatcher(None, key, tracked_key).ratio() >= 0.62:
            return True
    return False


def score_promotion_eligibility(item: dict, tracked_contents: list[str]) -> dict:
    content = str(item.get("content") or "")
    thread_type = str(item.get("thread_type") or "")
    reason_codes: list[str] = []
    score = 0.0

    if thread_type == "foreshadowing" or item.get("linked_foreshadowing_id"):
        return {"score": 0.0, "decision": "reject", "reason_codes": ["already_strict_foreshadowing"]}
    if _explicit_refs(content):
        return {"score": 0.0, "decision": "reject", "reason_codes": ["explicit_foreshadowing_ref"]}
    if _tracked_overlap(content, tracked_contents):
        return {"score": 0.0, "decision": "reject", "reason_codes": ["already_tracked_semantic_overlap"]}
    if _contains_any(content, PAYOFF_TERMS):
        return {"score": 0.0, "decision": "reject", "reason_codes": ["payoff_or_resolution_not_candidate"]}
    if _looks_like_abstract_theme_thread(content):
        return {"score": 0.0, "decision": "reject", "reason_codes": ["abstract_theme_statement"]}
    if _looks_like_world_fact_statement(content, thread_type):
        return {"score": 0.0, "decision": "reject", "reason_codes": ["world_fact_statement"]}
    if _looks_like_explanatory_reveal(content):
        return {"score": 0.0, "decision": "reject", "reason_codes": ["explanatory_reveal_not_future_setup"]}

    if item.get("status") == "partially_resolved" or item.get("open_questions"):
        score += 0.35
        reason_codes.append("has_open_question")
    if _contains_any(content, OPEN_TERMS):
        score += 0.35
        reason_codes.append("future_payoff_language")
    if thread_type == "mystery":
        score += 0.25
        reason_codes.append("mystery_lane")
    elif thread_type == "relationship_debt":
        score += 0.15
        reason_codes.append("relationship_debt_lane")
    elif thread_type == "world_rule_reveal":
        if _contains_any(content, WORLD_FACT_TERMS) and not item.get("open_questions"):
            score -= 0.3
            reason_codes.append("world_fact_without_open_question")
        else:
            score += 0.1
            reason_codes.append("world_rule_with_possible_payoff")
        if _semantic_key(content) in {
            "inherited_power_risk",
            "dangerous_artifact_rule",
            "long_horizon_plan",
            "identity_mystery",
            "hidden_patron",
        }:
            score += 0.5
            reason_codes.append("world_rule_has_payoff_semantic_key")
    else:
        reason_codes.append(f"{thread_type or 'unknown'}_lane")

    decision = "accept" if score >= 0.6 else "reject"
    if decision == "reject" and not reason_codes:
        reason_codes.append("below_priority_threshold")
    return {"score": round(max(0.0, score), 3), "decision": decision, "reason_codes": reason_codes}


def build_promotion_review_groups(promotions: list[dict], budget: int = 8) -> tuple[list[dict], list[dict]]:
    groups: dict[str, dict] = {}
    for promotion in promotions:
        key = _semantic_key(promotion.get("content", ""))
        if key not in groups:
            groups[key] = {
                "group_id": f"PG{len(groups) + 1:03d}",
                "semantic_key": key,
                "group_key": key,
                "group_label": key.replace("_", " ").title(),
                "review_status": "needs_review",
                "candidate_count": 0,
                "promotion_ids": [],
                "source_thread_ids": [],
                "source_thread_types": [],
                "representative_claim": promotion.get("content", ""),
                "representative_content": promotion.get("content", ""),
                "recommended_action": "promote_one_thread",
                "merge_strategy": "merge_as_single_strict_foreshadowing",
                "promotion_eligibility": promotion.get("promotion_eligibility", {}),
                "candidates": [],
            }
        group = groups[key]
        group["candidate_count"] += 1
        group["promotion_ids"].append(promotion.get("promotion_id"))
        group["source_thread_ids"].append(promotion.get("source_thread_id"))
        group["source_thread_types"].append(promotion.get("source_thread_type"))
        group["candidates"].append(promotion)
        if promotion.get("promotion_eligibility", {}).get("score", 0) > group["promotion_eligibility"].get("score", 0):
            group["promotion_eligibility"] = promotion["promotion_eligibility"]
            group["representative_claim"] = promotion.get("content", "")
            group["representative_content"] = promotion.get("content", "")

    ordered = sorted(
        groups.values(),
        key=lambda group: (-group.get("promotion_eligibility", {}).get("score", 0), group["group_id"]),
    )
    accepted = ordered[:budget]
    suppressed = []
    for group in ordered[budget:]:
        suppressed.append(
            {
                "group_id": group["group_id"],
                "semantic_key": group["semantic_key"],
                "reason": "below_promotion_group_budget",
                "score": group.get("promotion_eligibility", {}).get("score", 0),
                "candidate_count": group.get("candidate_count", 0),
            }
        )
    return accepted, suppressed


def apply_promotion_gate(registry: dict, *, budget: int = 8) -> dict:
    tracked_contents = [
        str(item.get("content") or item.get("canonical_content") or "")
        for item in registry.get("items", [])
        if item.get("thread_type") == "foreshadowing" or item.get("linked_foreshadowing_id")
    ]
    promotions: list[dict] = []
    suppressed: list[dict] = []
    already_tracked_count = int(registry.get("already_tracked_candidate_count") or 0)

    for item in registry.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("thread_type") == "foreshadowing" or item.get("linked_foreshadowing_id"):
            item["promotion_eligibility"] = {
                "score": 0.0,
                "decision": "reject",
                "reason_codes": ["already_strict_foreshadowing"],
            }
            continue
        content = str(item.get("content") or "")
        explicit_refs = _explicit_refs(content)
        if explicit_refs:
            item["promotion_eligibility"] = {
                "score": 0.0,
                "decision": "reject",
                "reason_codes": ["explicit_foreshadowing_ref"],
            }
            item["already_tracked_as"] = ",".join(explicit_refs)
            item["promotion_review_status"] = "already_tracked"
            already_tracked_count += 1
            suppressed.append(
                {
                    "source_thread_id": item.get("id"),
                    "source_thread_type": item.get("thread_type"),
                    "content": content,
                    "reason": "explicit_foreshadowing_ref",
                    "score": 0.0,
                    "already_tracked_as": ",".join(explicit_refs),
                }
            )
            continue
        eligibility = score_promotion_eligibility(item, tracked_contents)
        item["promotion_eligibility"] = eligibility
        if eligibility["decision"] != "accept":
            suppressed.append(
                {
                    "source_thread_id": item.get("id"),
                    "source_thread_type": item.get("thread_type"),
                    "content": item.get("content", ""),
                    "reason": ",".join(eligibility.get("reason_codes", [])),
                    "score": eligibility.get("score", 0),
                }
            )
            if "already_tracked" in ",".join(eligibility.get("reason_codes", [])):
                already_tracked_count += 1
            continue
        promotions.append(
            {
                "promotion_id": f"P{len(promotions) + 1:03d}",
                "source_thread_id": item.get("id"),
                "source_thread_type": item.get("thread_type"),
                "content": item.get("content", ""),
                "reason": "memory_semantics_gate_accepted",
                "review_status": "needs_review",
                "promotion_eligibility": eligibility,
                "evidence": item.get("evidence", []),
            }
        )

    groups, budget_suppressed = build_promotion_review_groups(promotions, budget=budget)
    registry["foreshadowing_candidate_promotions"] = promotions
    registry["promotion_candidate_count"] = len(promotions)
    registry["foreshadowing_promotion_groups"] = groups
    registry["promotion_review_groups"] = groups
    registry["promotion_group_count"] = len(groups)
    registry["suppressed_promotion_candidates"] = suppressed + budget_suppressed
    registry["already_tracked_candidate_count"] = already_tracked_count
    return registry
