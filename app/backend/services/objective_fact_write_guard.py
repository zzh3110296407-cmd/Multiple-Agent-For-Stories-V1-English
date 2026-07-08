import json
import re
from typing import Any

from pydantic import BaseModel

from app.backend.models.scene import Scene
from app.backend.models.scene_generation import SceneMemoryExtraction
from app.backend.models.subjective_fact import (
    BlockedObjectiveFactCandidate,
    ObjectiveFactWriteDecision,
    SubjectiveFactExtractionResult,
)
from app.backend.services.subjective_fact_extraction_service import (
    CLAIM_MARKERS,
    PERCEPTION_MARKERS,
    PSYCHOLOGY_MARKERS,
    SUBJECTIVE_SOURCE_TYPES,
)


class ObjectiveFactWriteGuard:
    def filter_scene_memory_extraction(
        self,
        scene: Scene,
        extraction_result: SubjectiveFactExtractionResult | None = None,
    ) -> tuple[SceneMemoryExtraction, ObjectiveFactWriteDecision]:
        extraction = scene.memory_extraction
        blocked_by_ref = self._blocked_ref_set(extraction_result)
        decision = ObjectiveFactWriteDecision(
            blocked_objective_candidates=list(
                extraction_result.blocked_objective_candidates
                if extraction_result
                else []
            ),
            warnings=list(extraction_result.warnings if extraction_result else []),
        )

        allowed_events: list[dict[str, Any]] = []
        for index, candidate in enumerate(extraction.event_summary, start=1):
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(
                candidate.get("event_id") or f"event_{scene.scene_id}_{index:03d}"
            )
            block = self._block_reason(
                candidate_type="event",
                candidate_id=candidate_id,
                candidate=candidate,
                blocked_by_ref=blocked_by_ref,
            )
            if block:
                decision.blocked_objective_candidates.append(block)
            else:
                allowed_events.append(dict(candidate))

        allowed_state_changes: list[dict[str, Any]] = []
        for index, candidate in enumerate(
            extraction.proposed_state_changes,
            start=1,
        ):
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(
                candidate.get("state_change_id")
                or f"change_{scene.scene_id}_{index:03d}"
            )
            block = self._block_reason(
                candidate_type="state_change",
                candidate_id=candidate_id,
                candidate=candidate,
                blocked_by_ref=blocked_by_ref,
            )
            if block:
                decision.blocked_objective_candidates.append(block)
            else:
                allowed_state_changes.append(dict(candidate))

        allowed_memory_records: list[dict[str, Any]] = []
        for index, candidate in enumerate(extraction.memory_records, start=1):
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(
                candidate.get("memory_id") or f"memory_{scene.scene_id}_{index:03d}"
            )
            block = self._block_reason(
                candidate_type="memory_record",
                candidate_id=candidate_id,
                candidate=candidate,
                blocked_by_ref=blocked_by_ref,
            )
            if block:
                decision.blocked_objective_candidates.append(block)
            else:
                allowed_memory_records.append(dict(candidate))

        decision.allowed_event_candidates = allowed_events
        decision.allowed_state_change_candidates = allowed_state_changes
        decision.allowed_memory_record_candidates = allowed_memory_records
        decision.blocked_objective_candidates = _unique_blocks(
            decision.blocked_objective_candidates
        )
        if decision.blocked_objective_candidates:
            decision.warnings = _unique_strings(
                [
                    *decision.warnings,
                    "ObjectiveFactWriteGuard 已拦截主观候选，避免写入客观事实层。",
                ]
            )
        filtered = SceneMemoryExtraction(
            event_summary=allowed_events,
            proposed_state_changes=allowed_state_changes,
            relationship_changes=extraction.relationship_changes,
            memory_records=allowed_memory_records,
            no_event_reason=(
                extraction.no_event_reason
                or (
                    "No objective event remained after subjective fact guard."
                    if not allowed_events
                    and not allowed_state_changes
                    and not allowed_memory_records
                    and decision.blocked_objective_candidates
                    else ""
                )
            ),
        )
        return filtered, decision

    def filter_scene(
        self,
        scene: Scene,
        extraction_result: SubjectiveFactExtractionResult | None = None,
    ) -> tuple[Scene, ObjectiveFactWriteDecision]:
        filtered, decision = self.filter_scene_memory_extraction(
            scene,
            extraction_result,
        )
        data = _model_to_dict(scene)
        data["memory_extraction"] = _model_to_dict(filtered)
        return Scene(**data), decision

    def is_subjective_candidate(
        self,
        *,
        candidate_type: str,
        candidate: dict[str, Any],
    ) -> bool:
        return bool(
            self._block_reason(
                candidate_type=candidate_type,
                candidate_id=str(
                    candidate.get("event_id")
                    or candidate.get("state_change_id")
                    or candidate.get("memory_id")
                    or "candidate"
                ),
                candidate=candidate,
                blocked_by_ref=set(),
            )
        )

    def _block_reason(
        self,
        *,
        candidate_type: str,
        candidate_id: str,
        candidate: dict[str, Any],
        blocked_by_ref: set[tuple[str, str]],
    ) -> BlockedObjectiveFactCandidate | None:
        if (candidate_type, candidate_id) in blocked_by_ref:
            return BlockedObjectiveFactCandidate(
                candidate_type=candidate_type,
                original_candidate_id=candidate_id,
                reason="SubjectiveFactExtractionService 已将此候选分类为主观内容。",
                suggested_subjective_record_type=_suggested_type(candidate),
                source_text_summary=_safe_summary(_candidate_text(candidate)),
            )
        if _has_subjective_source(candidate):
            return BlockedObjectiveFactCandidate(
                candidate_type=candidate_type,
                original_candidate_id=candidate_id,
                reason="候选来源属于 Claim/Perception/Psychology/Expression 或 Authorial Intent，不能写入客观事实层。",
                suggested_subjective_record_type=_suggested_type(candidate),
                source_text_summary=_safe_summary(_candidate_text(candidate)),
            )
        truth_status = str(candidate.get("truth_status") or "").strip()
        if truth_status and truth_status != "objective_fact":
            return BlockedObjectiveFactCandidate(
                candidate_type=candidate_type,
                original_candidate_id=candidate_id,
                reason="非 objective_fact 的 truth_status 不能写入客观事实层。",
                suggested_subjective_record_type="claim",
                source_text_summary=_safe_summary(_candidate_text(candidate)),
            )
        if candidate.get("objective_truth") is False or candidate.get("objective_truth") is None and truth_status:
            return BlockedObjectiveFactCandidate(
                candidate_type=candidate_type,
                original_candidate_id=candidate_id,
                reason="缺少客观真实性支撑的候选不能写入客观事实层。",
                suggested_subjective_record_type=_suggested_type(candidate),
                source_text_summary=_safe_summary(_candidate_text(candidate)),
            )
        text = _candidate_text(candidate)
        lowered = f" {text.casefold()} "
        if _contains_any(lowered, CLAIM_MARKERS):
            return BlockedObjectiveFactCandidate(
                candidate_type=candidate_type,
                original_candidate_id=candidate_id,
                reason="角色陈述、传言或谎言不等于客观事实。",
                suggested_subjective_record_type="claim",
                source_text_summary=_safe_summary(text),
            )
        if _contains_any(lowered, PERCEPTION_MARKERS) or _looks_like_state_perception(
            lowered
        ):
            return BlockedObjectiveFactCandidate(
                candidate_type=candidate_type,
                original_candidate_id=candidate_id,
                reason="角色感知、梦境、幻觉或误认不等于场景客观状态。",
                suggested_subjective_record_type="perception",
                source_text_summary=_safe_summary(text),
            )
        if _contains_any(lowered, PSYCHOLOGY_MARKERS) or (
            ("left" in lowered and "right" in lowered)
            or ("向左" in lowered and "向右" in lowered)
        ):
            return BlockedObjectiveFactCandidate(
                candidate_type=candidate_type,
                original_candidate_id=candidate_id,
                reason="心理动机、言行差异或自我欺骗不应写成客观事件、状态或记忆。",
                suggested_subjective_record_type="psychology",
                source_text_summary=_safe_summary(text),
            )
        return None

    def _blocked_ref_set(
        self,
        extraction_result: SubjectiveFactExtractionResult | None,
    ) -> set[tuple[str, str]]:
        if extraction_result is None:
            return set()
        return {
            (
                block.candidate_type,
                block.original_candidate_id,
            )
            for block in extraction_result.blocked_objective_candidates
            if block.original_candidate_id
        }


def _candidate_text(candidate: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "summary",
        "result",
        "content",
        "description",
        "text",
        "after",
        "before",
        "claim_text",
        "perceived_state_summary",
        "objective_state_summary",
    ):
        value = candidate.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            values.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
        else:
            values.append(str(value))
    return " ".join(values).strip()


def _has_subjective_source(candidate: dict[str, Any]) -> bool:
    values = [
        candidate.get("source_object_type"),
        candidate.get("object_type"),
        candidate.get("related_object_type"),
        candidate.get("source_type"),
        *_as_list(candidate.get("tags")),
        *_as_list(candidate.get("keywords")),
    ]
    for value in values:
        text = str(value or "").strip().casefold()
        if text in SUBJECTIVE_SOURCE_TYPES:
            return True
    return False


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _suggested_type(candidate: dict[str, Any]) -> str:
    text = _candidate_text(candidate).casefold()
    if _contains_any(text, PERCEPTION_MARKERS):
        return "perception"
    if _contains_any(text, PSYCHOLOGY_MARKERS):
        return "psychology"
    if _contains_any(text, CLAIM_MARKERS):
        return "claim"
    return "expression"


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _looks_like_state_perception(lowered: str) -> bool:
    see_markers = (" sees ", " saw ", " see ", "看到", "看见")
    state_markers = (
        "wall",
        "door",
        "intact",
        "destroyed",
        "broken",
        "unchanged",
        "墙",
        "门",
        "完好",
        "损毁",
        "破损",
    )
    return any(marker in lowered for marker in see_markers) and any(
        marker in lowered for marker in state_markers
    )


def _safe_summary(text: str, *, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}..."


def _unique_blocks(
    blocks: list[BlockedObjectiveFactCandidate],
) -> list[BlockedObjectiveFactCandidate]:
    result: list[BlockedObjectiveFactCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for block in blocks:
        identity = (
            block.candidate_type,
            block.original_candidate_id,
            block.suggested_subjective_record_type,
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(block)
    return result


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()
