from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any
import re

from ..models.common import SourceSpecificity
from ..models.trackers import TrackerItem, TrackerPlant, TrackerType, TrackerUpdate
from .tracker_store import candidates_dir, read_json, write_json


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", "", content).lower()


def _candidate_group_key(candidate: dict[str, Any]) -> str:
    refs = candidate.get("possible_existing_item_refs") or []
    if refs:
        return str(refs[0])
    return _normalize_content(candidate["content"])


def _item_id_for_group(index: int, group_key: str, prefix: str) -> str:
    if re.match(rf"^{re.escape(prefix)}\d+$", group_key):
        return group_key
    return f"{prefix}{index:03d}"


def _update_type(action: str) -> str:
    return {
        "reinforce": "reinforced",
        "surface": "surfaced",
        "resolve": "resolved",
        "abandon": "abandoned",
        "plant": "corrected",
    }[action]


def _status_for_candidates(candidates: list[dict[str, Any]]) -> str:
    actions = [candidate["candidate_action"] for candidate in candidates]
    if "abandon" in actions:
        return "abandoned"
    if "resolve" in actions:
        return "resolved"
    if "surface" in actions:
        return "partially_resolved"
    return "open"


def _load_candidate_observations(run_dir: str | Path) -> list[dict[str, Any]]:
    root = candidates_dir(run_dir)
    if not root.exists():
        raise FileNotFoundError(root)

    observations: list[dict[str, Any]] = []
    for path in sorted(root.glob("chapter_*_candidates.json")):
        record = read_json(path)
        for order, candidate in enumerate(record.get("candidates", [])):
            observations.append(
                {
                    "chapter_id": record["chapter_id"],
                    "chapter_index": record["chapter_index"],
                    "order": order,
                    "candidate": candidate,
                }
            )
    return observations


def _build_tracker_item(
    *,
    item_id: str,
    tracker_type: TrackerType,
    observations: list[dict[str, Any]],
) -> TrackerItem:
    sorted_observations = sorted(observations, key=lambda item: (item["chapter_index"], item["order"]))
    candidates = [observation["candidate"] for observation in sorted_observations]
    plant_position = next(
        (index for index, candidate in enumerate(candidates) if candidate["candidate_action"] == "plant"),
        0,
    )
    plant_candidate = candidates[plant_position]
    plant_observation = sorted_observations[plant_position]

    updates: list[TrackerUpdate] = []
    resolved_update: TrackerUpdate | None = None
    for index, observation in enumerate(sorted_observations):
        candidate = observation["candidate"]
        if index == plant_position and candidate["candidate_action"] == "plant":
            continue
        update = TrackerUpdate(
            chapter_index=observation["chapter_index"],
            update_type=_update_type(candidate["candidate_action"]),
            content=candidate["content"],
            evidence_refs=candidate.get("evidence_refs", []),
        )
        updates.append(update)
        if update.update_type == "resolved" and resolved_update is None:
            resolved_update = update

    return TrackerItem(
        tracker_item_id=item_id,
        tracker_type=tracker_type,
        canonical_content=plant_candidate["content"],
        source_specificity=SourceSpecificity.SOURCE_SPECIFIC,
        status=_status_for_candidates(candidates),
        planted=TrackerPlant(
            chapter_index=plant_observation["chapter_index"],
            evidence_refs=plant_candidate.get("evidence_refs", []),
            confidence_score=plant_candidate.get("confidence_score", 0.0),
        ),
        updates=updates,
        resolved=resolved_update,
        candidate_history_refs=[candidate["candidate_id"] for candidate in candidates],
    )


def reconcile_tracker(
    run_dir: str | Path,
    *,
    tracker_type: TrackerType,
    item_prefix: str,
    schema_version: str,
    output_path: Path,
) -> dict[str, Any]:
    observations = [
        observation
        for observation in _load_candidate_observations(run_dir)
        if observation["candidate"]["candidate_type"] == tracker_type
    ]

    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    referenced_observations: list[dict[str, Any]] = []
    for observation in observations:
        candidate = observation["candidate"]
        if candidate.get("possible_existing_item_refs"):
            referenced_observations.append(observation)
        else:
            group_key = _candidate_group_key(candidate)
            grouped.setdefault(group_key, []).append(observation)

    generated_id_to_group_key = {
        _item_id_for_group(index, group_key, item_prefix): group_key
        for index, group_key in enumerate(grouped.keys(), start=1)
    }
    for observation in referenced_observations:
        candidate = observation["candidate"]
        ref = str(candidate["possible_existing_item_refs"][0])
        group_key = generated_id_to_group_key.get(ref)
        if group_key is None:
            if re.match(rf"^{re.escape(item_prefix)}\d+$", ref):
                group_key = _normalize_content(candidate["content"])
                candidate["ignored_possible_existing_item_ref"] = ref
            else:
                group_key = ref
        grouped.setdefault(group_key, []).append(observation)

    items = []
    for index, (group_key, group_observations) in enumerate(grouped.items(), start=1):
        item = _build_tracker_item(
            item_id=_item_id_for_group(index, group_key, item_prefix),
            tracker_type=tracker_type,
            observations=group_observations,
        )
        items.append(item.model_dump(mode="json"))

    tracker = {
        "schema_version": schema_version,
        "tracker_type": tracker_type,
        "item_count": len(items),
        "items": items,
    }
    write_json(output_path, tracker)
    return tracker

