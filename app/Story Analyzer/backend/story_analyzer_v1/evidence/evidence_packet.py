from __future__ import annotations

import re
from typing import Any


EVIDENCE_PACKET_VERSION = "story_analyzer.evidence_packet.v2"
VALID_SUPPORT_STATUS = {"supported", "contradicted", "insufficient", "ambiguous"}


def _clip_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: max(0, limit - 3)].rstrip() + "..."


def build_evidence_packet(
    *,
    packet_id: str,
    target_path: str,
    claim: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    support_status: str,
    support_reason: str = "",
    retrieval_scope: dict[str, Any] | None = None,
    quote_limit: int = 500,
    max_items: int = 5,
) -> dict[str, Any]:
    status = support_status if support_status in VALID_SUPPORT_STATUS else "ambiguous"
    bounded_items: list[dict[str, Any]] = []
    for index, item in enumerate(evidence_items[:max_items], start=1):
        bounded_items.append(
            {
                "evidence_id": f"EV{index:03d}",
                "segment_id": item.get("segment_id", ""),
                "source_chapter_index": item.get("source_chapter_index"),
                "analysis_unit_index": item.get("analysis_unit_index"),
                "char_start": item.get("char_start"),
                "char_end": item.get("char_end"),
                "quote": _clip_text(item.get("quote") or item.get("text") or "", quote_limit),
                "match_reason": item.get("match_reason", ""),
                "score": round(float(item.get("score") or 0.0), 4),
            }
        )
    return {
        "schema_version": EVIDENCE_PACKET_VERSION,
        "packet_id": packet_id,
        "target_path": target_path,
        "claim_id": claim.get("claim_id", ""),
        "claim_text": claim.get("claim_text", ""),
        "claim_type": claim.get("claim_type", "event_fact"),
        "retrieval_scope": retrieval_scope or {},
        "evidence_items": bounded_items,
        "support_status": status,
        "support_reason": support_reason,
    }
