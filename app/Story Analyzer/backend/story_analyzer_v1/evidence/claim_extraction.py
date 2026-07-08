from __future__ import annotations

import re
from typing import Any


CLAIM_TEXT_KEYS = {
    "canonical_content",
    "content",
    "summary",
    "description",
    "event",
    "text",
    "chapter_function",
    "arc_goal",
    "core_conflict",
    "resolution",
}
CLAIM_STATE_KEYS = {
    "status",
    "state",
    "resolution_scope",
    "tracking_scope",
    "memory_lane",
}
ACTION_TERMS = {
    "opens",
    "reveals",
    "confirms",
    "kills",
    "betrays",
    "discovers",
    "resolves",
    "plants",
    "opened",
    "revealed",
    "confirmed",
    "resolved",
    "planted",
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _terms(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_'-]{2,}|[\u4e00-\u9fff]{2,8}", text)
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        normalized = token.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(token)
    return result[:20]


def _claim_type_for_path(path: str, key: str, text: str) -> str:
    lowered = f"{path}.{key}.{text}".lower()
    if "foreshadow" in lowered or "伏笔" in lowered or key in CLAIM_STATE_KEYS:
        return "foreshadowing_state"
    if "relation" in lowered or "relationship" in lowered or "关系" in lowered:
        return "character_relation"
    if "world" in lowered or "rule" in lowered or "设定" in lowered:
        return "world_rule"
    if "emotion" in lowered or "情绪" in lowered:
        return "emotional_state"
    if "arc" in lowered or "chapter_function" in lowered:
        return "arc_function"
    return "event_fact"


def _build_claim(index: int, target_path: str, key: str, text: str) -> dict[str, Any]:
    action_terms = [term for term in _terms(text) if term.lower() in ACTION_TERMS]
    source_terms = [term for term in _terms(text) if term.lower() not in ACTION_TERMS]
    return {
        "claim_id": f"CLAIM_{index:03d}",
        "target_path": target_path,
        "claim_type": _claim_type_for_path(target_path, key, text),
        "claim_text": text,
        "source_terms": source_terms[:10],
        "action_terms": action_terms[:8],
        "state_terms": [text] if key in CLAIM_STATE_KEYS else [],
    }


def extract_claims_from_value(
    value: Any,
    *,
    target_path: str,
    max_claims: int = 12,
) -> list[dict[str, Any]]:
    raw_claims: list[tuple[str, str, str]] = []

    def visit(node: Any, path: str, key: str = "") -> None:
        if len(raw_claims) >= max_claims:
            return
        if isinstance(node, dict):
            for child_key, child_value in node.items():
                child_path = f"{path}.{child_key}" if path else str(child_key)
                if child_key in CLAIM_TEXT_KEYS or child_key in CLAIM_STATE_KEYS:
                    text = _normalize_text(child_value)
                    if text:
                        raw_claims.append((child_path, child_key, text))
                        if len(raw_claims) >= max_claims:
                            return
                    if not isinstance(child_value, (dict, list)):
                        continue
                visit(child_value, child_path, str(child_key))
            return
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]", key)
                if len(raw_claims) >= max_claims:
                    return
            return
        if isinstance(node, str) and key in CLAIM_TEXT_KEYS:
            text = _normalize_text(node)
            if text:
                raw_claims.append((path, key, text))

    visit(value, target_path)
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, key, text in raw_claims:
        normalized = text.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        claims.append(_build_claim(len(claims) + 1, path, key, text))
        if len(claims) >= max_claims:
            break
    return claims
