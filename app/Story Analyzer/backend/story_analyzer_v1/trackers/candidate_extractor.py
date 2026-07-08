from __future__ import annotations

from pathlib import Path
import re

from ..analysis.canonical_builder import load_canonical_chapters
from ..models.common import EvidenceClaimType, ensure_evidence_claim_type
from ..models.trackers import TrackerCandidate
from .tracker_store import ensure_candidates_dir, write_json


def _candidate_file_name(chapter_id: str) -> str:
    return f"{chapter_id}_candidates.json"


_RESERVED_TRACKER_ITEM_ID_RE = re.compile(r"^[FMRW]\d{3,}$")


def _safe_candidate_id(
    *,
    chapter_id: str,
    candidate_type: str,
    candidate_id: str,
    candidate_index: int,
    seen_candidate_ids: set[str],
) -> tuple[str, str]:
    if not candidate_id or _RESERVED_TRACKER_ITEM_ID_RE.match(candidate_id) or candidate_id in seen_candidate_ids:
        base = f"{chapter_id}_{candidate_type}_{candidate_index:03d}"
        safe_id = base
        suffix = 2
        while safe_id in seen_candidate_ids:
            safe_id = f"{base}_{suffix}"
            suffix += 1
        return safe_id, candidate_id
    return candidate_id, ""


def _candidate_claim_type(candidate: TrackerCandidate) -> EvidenceClaimType:
    if candidate.candidate_type == "mystery":
        return EvidenceClaimType.MYSTERY_STATE_CHANGE
    if candidate.candidate_type == "relationship_debt":
        return EvidenceClaimType.RELATIONSHIP_SHIFT
    if candidate.candidate_type == "world_rule_reveal":
        return EvidenceClaimType.WORLD_RULE_REVEAL
    if candidate.candidate_action in {"surface", "resolve"}:
        return EvidenceClaimType.FORESHADOWING_PAYOFF
    return EvidenceClaimType.SCENE_TURN


def extract_tracker_candidates(run_dir: str | Path) -> list[Path]:
    """Extract validated tracker candidates from canonical chapter files.

    This step only writes observations. It does not decide final tracker state.
    """

    out_dir = ensure_candidates_dir(run_dir)
    paths: list[Path] = []
    seen_candidate_ids: set[str] = set()
    for chapter in load_canonical_chapters(run_dir):
        candidates = []
        for candidate_index, raw_candidate in enumerate(chapter.tracker_candidates, start=1):
            candidate = TrackerCandidate.model_validate(raw_candidate)
            data = candidate.model_dump(mode="json")
            safe_id, source_id = _safe_candidate_id(
                chapter_id=chapter.chapter_id,
                candidate_type=candidate.candidate_type,
                candidate_id=data.get("candidate_id", ""),
                candidate_index=candidate_index,
                seen_candidate_ids=seen_candidate_ids,
            )
            if source_id:
                data["source_candidate_id"] = source_id
                data["candidate_id"] = safe_id
            seen_candidate_ids.add(data["candidate_id"])
            data["evidence_refs"] = ensure_evidence_claim_type(
                data["evidence_refs"],
                _candidate_claim_type(candidate),
            )
            candidates.append(data)

        payload = {
            "schema_version": "story_analyzer.tracker_candidates.v1",
            "chapter_id": chapter.chapter_id,
            "chapter_index": chapter.chapter_index,
            "candidates": candidates,
        }
        out_path = write_json(out_dir / _candidate_file_name(chapter.chapter_id), payload)
        paths.append(out_path)
    return paths
