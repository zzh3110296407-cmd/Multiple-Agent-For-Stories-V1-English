import json
import re
from typing import Any

from app.backend.models.narrative_layer import NarrativeObjectReference
from app.backend.models.scene import Scene
from app.backend.models.subjective_fact import (
    BlockedObjectiveFactCandidate,
    SubjectiveClaimCandidate,
    SubjectiveExpressionCandidate,
    SubjectiveFactExtractionResult,
    SubjectivePerceptionCandidate,
    SubjectivePsychologyCandidate,
)


CLAIM_MARKERS = (
    " says ",
    " said ",
    " claims ",
    " claimed ",
    " declares ",
    " declared ",
    " insists ",
    " insisted ",
    " tells ",
    " told ",
    "rumor",
    "rumour",
    "lie",
    "lies",
    "lying",
    "misinformation",
    "exaggeration",
    "self-deception",
    "说",
    "说道",
    "声称",
    "宣称",
    "坚称",
    "谎称",
    "传言",
    "谣言",
    "撒谎",
    "自欺",
)
PERCEPTION_MARKERS = (
    "perceives",
    "perceived",
    " vision ",
    "dream",
    "hallucination",
    "hallucinates",
    "misrecognition",
    "mistakes ",
    "unreliable perception",
    "magic influence",
    "trauma response",
    "以为",
    "误认",
    "幻觉",
    "梦见",
    "梦境",
    "幻视",
    "不可靠感知",
    "魔法影响",
    "创伤反应",
)
PSYCHOLOGY_MARKERS = (
    "but walks",
    "but goes",
    "but actually",
    "actually walks",
    "language-action",
    "contradiction",
    "self-deception",
    "suppressed motive",
    "inner desire",
    "fear vs behavior",
    "says they will go left",
    "go left",
    "walks right",
    "向左",
    "向右",
    "却",
    "实际",
    "内心",
    "压抑",
    "动机",
    "自欺",
    "恐惧",
    "言行不一",
)
SUBJECTIVE_SOURCE_TYPES = {
    "claim",
    "claim_record",
    "perception",
    "perception_state",
    "psychology",
    "psychology_trace",
    "expression",
    "expression_record",
    "narrative_intent",
    "authorial_intent",
}


class SubjectiveFactExtractionService:
    def extract_from_scene(self, scene: Scene) -> SubjectiveFactExtractionResult:
        intent_ids = _unique_strings(
            [
                *scene.narrative_intent_ids,
                *scene.generation_trace.narrative_intent_ids,
            ]
        )
        result = SubjectiveFactExtractionResult(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            generation_trace_id=scene.generation_trace.generation_trace_id,
            source_narrative_intent_ids=intent_ids,
            source_refs=[
                NarrativeObjectReference(
                    object_type="scene",
                    object_id=scene.scene_id,
                    relation="source scene",
                )
            ],
        )
        seen: set[tuple[str, str]] = set()
        for candidate_type, candidate_id, item in self._iter_candidate_items(scene):
            classification = self.classify_candidate(
                scene=scene,
                candidate_type=candidate_type,
                candidate_id=candidate_id,
                item=item,
                intent_ids=intent_ids,
            )
            self._merge_result(result, classification, seen)
        if not any(
            [
                result.claim_candidates,
                result.perception_candidates,
                result.psychology_trace_candidates,
                result.expression_record_candidates,
            ]
        ):
            text = _safe_summary(f"{scene.synopsis} {scene.prose_text}", limit=420)
            if text:
                classification = self.classify_candidate(
                    scene=scene,
                    candidate_type="scene_text",
                    candidate_id=f"scene_text_{scene.scene_id}",
                    item={
                        "summary": text,
                        "character_ids": scene.linked_character_ids,
                        "source_object_type": "scene",
                        "source_object_id": scene.scene_id,
                    },
                    intent_ids=intent_ids,
                )
                self._merge_result(result, classification, seen)
        if (
            not result.claim_candidates
            and not result.perception_candidates
            and not result.psychology_trace_candidates
            and not result.expression_record_candidates
        ):
            result.warnings = _unique_strings(
                [
                    *result.warnings,
                    "未检测到需要写入主观事实层的候选内容。",
                ]
            )
        return result

    def classify_candidate(
        self,
        *,
        scene: Scene,
        candidate_type: str,
        candidate_id: str,
        item: dict[str, Any],
        intent_ids: list[str],
    ) -> SubjectiveFactExtractionResult:
        text = _candidate_text(item)
        lowered = f" {text.casefold()} "
        source_summary = _safe_summary(text)
        source_ref = NarrativeObjectReference(
            object_type=candidate_type,
            object_id=candidate_id,
            relation="classified source",
        )
        character_id = _candidate_character_id(item, scene)
        result = SubjectiveFactExtractionResult(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            generation_trace_id=scene.generation_trace.generation_trace_id,
            source_narrative_intent_ids=intent_ids,
            source_refs=[source_ref],
        )
        intent_id = intent_ids[0] if intent_ids else ""
        expression_candidate_id = ""
        psychology_candidate_id = ""
        claim_candidate_id = ""

        if _looks_like_claim(lowered, text, item):
            claim_candidate_id = f"claim_{_safe_id(candidate_id)}"
            expression_candidate_id = f"expr_{_safe_id(candidate_id)}"
            truth_status = _claim_truth_status(lowered)
            result.claim_candidates.append(
                SubjectiveClaimCandidate(
                    candidate_id=claim_candidate_id,
                    scene_id=scene.scene_id,
                    chapter_id=scene.chapter_id,
                    character_id=character_id,
                    claim_text=_claim_text(text),
                    truth_status=truth_status,
                    objective_truth=None,
                    speaker_intent=_speaker_intent(lowered),
                    source_expression_candidate_id=expression_candidate_id,
                    linked_narrative_intent_id=intent_id,
                    source_text_summary=source_summary,
                    source_refs=[source_ref],
                )
            )
            if candidate_type in {"event", "state_change", "memory_record"}:
                result.blocked_objective_candidates.append(
                    BlockedObjectiveFactCandidate(
                        candidate_type=candidate_type,
                        original_candidate_id=candidate_id,
                        reason="角色陈述或传言必须先写入 ClaimRecord，不能直接写成客观事实。",
                        suggested_subjective_record_type="claim",
                        source_text_summary=source_summary,
                    )
                )

        if _looks_like_perception(lowered, item):
            perception_candidate_id = f"perception_{_safe_id(candidate_id)}"
            result.perception_candidates.append(
                SubjectivePerceptionCandidate(
                    candidate_id=perception_candidate_id,
                    scene_id=scene.scene_id,
                    chapter_id=scene.chapter_id,
                    character_id=character_id,
                    perceived_object_type=str(
                        item.get("perceived_object_type")
                        or item.get("target_type")
                        or item.get("object_type")
                        or "scene"
                    ),
                    perceived_object_id=str(
                        item.get("perceived_object_id")
                        or item.get("target_id")
                        or item.get("object_id")
                        or scene.scene_id
                    ),
                    objective_state_summary=_objective_state_summary(item),
                    perceived_state_summary=source_summary,
                    perception_type=_perception_type(lowered),
                    reader_explanation_policy="defer",
                    linked_narrative_intent_id=intent_id,
                    source_text_summary=source_summary,
                    source_refs=[source_ref],
                )
            )
            if candidate_type in {"event", "state_change", "memory_record"}:
                result.blocked_objective_candidates.append(
                    BlockedObjectiveFactCandidate(
                        candidate_type=candidate_type,
                        original_candidate_id=candidate_id,
                        reason="不可靠感知必须写入 PerceptionStateRecord，不能修改场景或地点客观状态。",
                        suggested_subjective_record_type="perception",
                        source_text_summary=source_summary,
                    )
                )

        if _looks_like_psychology(lowered):
            psychology_candidate_id = f"psy_{_safe_id(candidate_id)}"
            expression_candidate_id = expression_candidate_id or f"expr_{_safe_id(candidate_id)}"
            result.psychology_trace_candidates.append(
                SubjectivePsychologyCandidate(
                    candidate_id=psychology_candidate_id,
                    scene_id=scene.scene_id,
                    chapter_id=scene.chapter_id,
                    character_id=character_id,
                    surface_intention=_surface_intention(text),
                    inner_desire=_inner_desire(text),
                    fear=_fear(text),
                    self_deception=_self_deception(lowered),
                    suppressed_motive=_suppressed_motive(lowered),
                    psychological_pressure=_psychological_pressure(text),
                    action_tendency=_action_tendency(text),
                    confidence=0.72,
                    source_narrative_intent_id=intent_id,
                    linked_expression_candidate_id=expression_candidate_id,
                    source_text_summary=source_summary,
                    source_refs=[source_ref],
                )
            )
            if candidate_type in {"event", "state_change", "memory_record"}:
                result.blocked_objective_candidates.append(
                    BlockedObjectiveFactCandidate(
                        candidate_type=candidate_type,
                        original_candidate_id=candidate_id,
                        reason="言行差异或心理动机必须写入 CharacterPsychologyTrace，不能直接改写客观事实或角色长期状态。",
                        suggested_subjective_record_type="psychology",
                        source_text_summary=source_summary,
                    )
                )

        if _looks_like_expression(lowered, result):
            expression_candidate_id = expression_candidate_id or f"expr_{_safe_id(candidate_id)}"
            result.expression_record_candidates.append(
                SubjectiveExpressionCandidate(
                    candidate_id=expression_candidate_id,
                    scene_id=scene.scene_id,
                    chapter_id=scene.chapter_id,
                    character_id=character_id,
                    psychology_candidate_id=psychology_candidate_id,
                    spoken_claim_candidate_ids=[claim_candidate_id] if claim_candidate_id else [],
                    actual_action=_actual_action(text),
                    external_behavior=_external_behavior(text),
                    silence_or_omission=_silence_or_omission(lowered),
                    deception_or_concealment=_deception_or_concealment(lowered),
                    reader_inference_hint=_reader_inference_hint(result),
                    source_text_summary=source_summary,
                    source_refs=[source_ref],
                )
            )
            if candidate_type in {"event", "state_change", "memory_record"}:
                result.blocked_objective_candidates.append(
                    BlockedObjectiveFactCandidate(
                        candidate_type=candidate_type,
                        original_candidate_id=candidate_id,
                        reason="表达、沉默、回避或欺骗只能作为 CharacterExpressionRecord，不应自动制造客观事件。",
                        suggested_subjective_record_type="expression",
                        source_text_summary=source_summary,
                    )
                )

        if _source_type_is_subjective(item) and not result.blocked_objective_candidates:
            if candidate_type in {"event", "state_change", "memory_record"}:
                result.blocked_objective_candidates.append(
                    BlockedObjectiveFactCandidate(
                        candidate_type=candidate_type,
                        original_candidate_id=candidate_id,
                        reason="候选来源属于主观叙事对象，不能写入客观事实层。",
                        suggested_subjective_record_type="claim",
                        source_text_summary=source_summary,
                    )
                )
        return result

    def _iter_candidate_items(
        self,
        scene: Scene,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        items: list[tuple[str, str, dict[str, Any]]] = []
        for index, item in enumerate(scene.memory_extraction.event_summary, start=1):
            if isinstance(item, dict):
                items.append(
                    (
                        "event",
                        str(item.get("event_id") or f"event_{scene.scene_id}_{index:03d}"),
                        item,
                    )
                )
        for index, item in enumerate(
            scene.memory_extraction.proposed_state_changes,
            start=1,
        ):
            if isinstance(item, dict):
                items.append(
                    (
                        "state_change",
                        str(
                            item.get("state_change_id")
                            or f"change_{scene.scene_id}_{index:03d}"
                        ),
                        item,
                    )
                )
        for index, item in enumerate(scene.memory_extraction.memory_records, start=1):
            if isinstance(item, dict):
                items.append(
                    (
                        "memory_record",
                        str(item.get("memory_id") or f"memory_{scene.scene_id}_{index:03d}"),
                        item,
                    )
                )
        return items

    def _merge_result(
        self,
        target: SubjectiveFactExtractionResult,
        source: SubjectiveFactExtractionResult,
        seen: set[tuple[str, str]],
    ) -> None:
        for field_name in (
            "claim_candidates",
            "perception_candidates",
            "psychology_trace_candidates",
            "expression_record_candidates",
            "blocked_objective_candidates",
        ):
            current = list(getattr(target, field_name))
            for candidate in getattr(source, field_name):
                identity = (
                    field_name,
                    getattr(candidate, "candidate_id", "")
                    or getattr(candidate, "original_candidate_id", ""),
                )
                if identity in seen:
                    continue
                seen.add(identity)
                current.append(candidate)
            setattr(target, field_name, current)
        target.warnings = _unique_strings([*target.warnings, *source.warnings])
        target.source_narrative_intent_ids = _unique_strings(
            [
                *target.source_narrative_intent_ids,
                *source.source_narrative_intent_ids,
            ]
        )
        target.source_refs = _unique_refs([*target.source_refs, *source.source_refs])


def _candidate_text(item: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "summary",
        "result",
        "content",
        "description",
        "text",
        "claim_text",
        "perceived_state_summary",
        "objective_state_summary",
        "actual_action",
        "external_behavior",
    ):
        value = item.get(key)
        if value not in (None, "", [], {}):
            values.append(str(value))
    for key in ("after", "before"):
        value = item.get(key)
        if isinstance(value, dict) and value:
            values.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return " ".join(values).strip()


def _looks_like_claim(lowered: str, text: str, item: dict[str, Any]) -> bool:
    if str(item.get("truth_status") or "") in {
        "unverified_claim",
        "lie",
        "rumor",
        "misinformation",
        "exaggeration",
        "self_deception",
    }:
        return True
    if any(marker in lowered for marker in CLAIM_MARKERS):
        return True
    return bool(item.get("speaker_character_id")) and bool(
        re.search(r"[\"“”'].*?[\"“”']", text)
    )


def _looks_like_perception(lowered: str, item: dict[str, Any]) -> bool:
    if str(item.get("perception_type") or "").strip():
        return True
    if _looks_like_state_perception(lowered):
        return True
    return any(marker in lowered for marker in PERCEPTION_MARKERS)


def _looks_like_psychology(lowered: str) -> bool:
    if "left" in lowered and "right" in lowered and any(
        marker in lowered for marker in (" says ", " said ", "will", "but", "actually")
    ):
        return True
    if "向左" in lowered and "向右" in lowered:
        return True
    return any(marker in lowered for marker in PSYCHOLOGY_MARKERS)


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


def _looks_like_expression(
    lowered: str,
    result: SubjectiveFactExtractionResult,
) -> bool:
    if result.claim_candidates or result.psychology_trace_candidates:
        return True
    return any(
        marker in lowered
        for marker in (
            "silence",
            "silent",
            "omits",
            "avoids",
            "conceals",
            "deceives",
            "沉默",
            "遗漏",
            "回避",
            "隐瞒",
            "欺骗",
        )
    )


def _source_type_is_subjective(item: dict[str, Any]) -> bool:
    values = {
        str(item.get("source_object_type") or "").casefold(),
        str(item.get("object_type") or "").casefold(),
        str(item.get("related_object_type") or "").casefold(),
    }
    values.update(str(value).casefold() for value in item.get("tags") or [])
    values.update(str(value).casefold() for value in item.get("keywords") or [])
    return bool(values.intersection(SUBJECTIVE_SOURCE_TYPES))


def _claim_text(text: str) -> str:
    match = re.search(r"[\"“”']([^\"“”']{2,180})[\"“”']", text)
    if match:
        return _safe_summary(match.group(1), limit=180)
    for marker in ("says", "said", "claims", "declares", "说", "声称", "宣称", "坚称"):
        if marker in text:
            return _safe_summary(text.split(marker, 1)[-1], limit=180)
    return _safe_summary(text, limit=180)


def _claim_truth_status(lowered: str) -> str:
    if any(marker in lowered for marker in ("rumor", "rumour", "传言", "谣言")):
        return "rumor"
    if any(marker in lowered for marker in ("misinformation", "误导信息")):
        return "misinformation"
    if any(marker in lowered for marker in ("exaggeration", "夸大")):
        return "exaggeration"
    if any(marker in lowered for marker in ("lie", "lying", "谎", "撒谎")):
        return "lie"
    if any(marker in lowered for marker in ("self-deception", "自欺")):
        return "self_deception"
    return "unverified_claim"


def _perception_type(lowered: str) -> str:
    if any(marker in lowered for marker in ("hallucination", "幻觉", "幻视")):
        return "hallucination"
    if any(marker in lowered for marker in ("dream", "梦见", "梦境")):
        return "dream"
    if " vision " in lowered:
        return "vision"
    if any(marker in lowered for marker in ("misrecognition", "mistakes", "误认")):
        return "misrecognition"
    if any(marker in lowered for marker in ("magic influence", "魔法影响")):
        return "magic_influence"
    if any(marker in lowered for marker in ("trauma response", "创伤反应")):
        return "trauma_response"
    return "unreliable_perception"


def _speaker_intent(lowered: str) -> str:
    if any(marker in lowered for marker in ("conceal", "deceive", "隐瞒", "欺骗", "谎")):
        return "conceal or misdirect"
    if any(marker in lowered for marker in ("rumor", "传言", "谣言")):
        return "repeat unverified information"
    return "state a character-level claim"


def _surface_intention(text: str) -> str:
    return _safe_summary(text, limit=140)


def _inner_desire(text: str) -> str:
    return "The scene suggests an intention-action divergence." if text else ""


def _fear(text: str) -> str:
    return "Fear or pressure may be implied by the divergence." if text else ""


def _self_deception(lowered: str) -> str:
    if any(marker in lowered for marker in ("self-deception", "自欺")):
        return "The character may be protecting a self-deceptive belief."
    return ""


def _suppressed_motive(lowered: str) -> str:
    if any(marker in lowered for marker in ("suppressed motive", "压抑", "动机")):
        return "A suppressed motive is suggested but not confirmed."
    return ""


def _psychological_pressure(text: str) -> str:
    return _safe_summary(text, limit=120)


def _action_tendency(text: str) -> str:
    lowered = text.casefold()
    if "right" in lowered or "向右" in text:
        return "moves right despite stated direction"
    if "left" in lowered or "向左" in text:
        return "direction choice is psychologically loaded"
    return ""


def _actual_action(text: str) -> str:
    lowered = text.casefold()
    if "walks right" in lowered or "goes right" in lowered or "向右" in text:
        return "walks right"
    return _safe_summary(text, limit=140)


def _external_behavior(text: str) -> str:
    return _safe_summary(text, limit=140)


def _silence_or_omission(lowered: str) -> str:
    if any(marker in lowered for marker in ("silence", "silent", "omits", "沉默", "遗漏")):
        return "silence or omission"
    return ""


def _deception_or_concealment(lowered: str) -> str:
    if any(marker in lowered for marker in ("deceive", "conceal", "lie", "隐瞒", "欺骗", "谎")):
        return "possible deception or concealment"
    return ""


def _reader_inference_hint(result: SubjectiveFactExtractionResult) -> str:
    if result.psychology_trace_candidates:
        return "Reader may infer an intentional gap between words and action."
    if result.claim_candidates:
        return "Reader should treat the statement as a character claim."
    return ""


def _objective_state_summary(item: dict[str, Any]) -> str:
    before = item.get("before")
    if isinstance(before, dict) and before:
        return _safe_summary(json.dumps(before, ensure_ascii=False, sort_keys=True))
    return str(item.get("objective_state_summary") or "").strip()


def _candidate_character_id(item: dict[str, Any], scene: Scene) -> str:
    for key in ("character_id", "speaker_character_id", "actor_character_id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    for key in ("participants", "character_ids", "believed_by_character_ids"):
        values = item.get(key)
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
    return scene.linked_character_ids[0] if scene.linked_character_ids else ""


def _safe_summary(text: str, *, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}..."


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip())
    return text.strip("_") or "candidate"


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


def _unique_refs(
    refs: list[NarrativeObjectReference],
) -> list[NarrativeObjectReference]:
    result: list[NarrativeObjectReference] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in refs:
        identity = (ref.object_type, ref.object_id, ref.relation)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(ref)
    return result
