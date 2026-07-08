from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any
import hashlib


class AdvisoryAuthority(str, Enum):
    ADVISORY_ONLY = "advisory_only"


class SourceSpecificity(str, Enum):
    TRANSFERABLE = "transferable"
    SOURCE_SPECIFIC = "source_specific"
    HYBRID = "hybrid"


class GenerationMode(str, Enum):
    ORIGINAL_WRITING = "original_writing"
    CONTINUATION_OR_REVISION = "continuation_or_revision"
    HYBRID_ADAPTATION = "hybrid_adaptation"


class EvidenceClaimType(str, Enum):
    CANONICAL_CHAPTER = "canonical_chapter"
    SCENE_TURN = "scene_turn"
    CHARACTER_DECISION = "character_decision"
    RELATIONSHIP_SHIFT = "relationship_shift"
    WORLD_RULE_REVEAL = "world_rule_reveal"
    MYSTERY_STATE_CHANGE = "mystery_state_change"
    FORESHADOWING_PAYOFF = "foreshadowing_payoff"


VALID_EVIDENCE_CLAIM_TYPES = {item.value for item in EvidenceClaimType}


class EvidenceRef(dict):
    """Backward-compatible dict evidence ref.

    M29 formalizes claim_type, but existing artifacts may omit it. Missing
    claim_type is treated as canonical_chapter by validators and catalog stats.
    """


def evidence_claim_type(evidence_ref: dict[str, Any]) -> str:
    claim_type = evidence_ref.get("claim_type")
    if claim_type in (None, ""):
        ref_type = evidence_ref.get("ref_type")
        if ref_type in VALID_EVIDENCE_CLAIM_TYPES:
            return str(ref_type)
        return EvidenceClaimType.CANONICAL_CHAPTER.value
    if claim_type not in VALID_EVIDENCE_CLAIM_TYPES:
        raise ValueError(f"unknown evidence claim_type: {claim_type}")
    return str(claim_type)


def validate_evidence_refs(evidence_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, evidence_ref in enumerate(evidence_refs):
        if not isinstance(evidence_ref, dict):
            raise TypeError(f"evidence_refs[{index}] must be an object")
        evidence_claim_type(evidence_ref)
    return evidence_refs


def make_evidence_ref(
    *,
    claim_type: EvidenceClaimType | str = EvidenceClaimType.CANONICAL_CHAPTER,
    ref_type: str = "canonical_chapter",
    **fields: Any,
) -> dict[str, Any]:
    value = claim_type.value if isinstance(claim_type, EvidenceClaimType) else str(claim_type)
    evidence_ref = {"claim_type": value, "ref_type": ref_type, **fields}
    evidence_claim_type(evidence_ref)
    return evidence_ref


def ensure_evidence_claim_type(
    evidence_refs: list[dict[str, Any]],
    claim_type: EvidenceClaimType | str,
    *,
    ref_type: str = "canonical_chapter",
) -> list[dict[str, Any]]:
    value = claim_type.value if isinstance(claim_type, EvidenceClaimType) else str(claim_type)
    normalized = []
    for evidence_ref in evidence_refs:
        item = dict(evidence_ref)
        item.setdefault("claim_type", value)
        item.setdefault("ref_type", ref_type)
        evidence_claim_type(item)
        normalized.append(item)
    return normalized


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
