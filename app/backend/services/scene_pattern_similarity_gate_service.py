from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel

from app.backend.models.scene import Scene
from app.backend.models.scene_generation import (
    SceneDraftContent,
    SceneProgressionStatement,
    SceneWritingContext,
)
from app.backend.models.scene_pattern_similarity import (
    SCENE_PATTERN_SIMILARITY_TOO_HIGH,
    SCENE_PATTERN_SIMILARITY_WARNING,
    ScenePatternSignature,
    ScenePatternSimilarityAxisScore,
    ScenePatternSimilarityFinding,
    ScenePatternSimilarityReport,
)


STRUCTURAL_BLOCK_THRESHOLD = 0.72
STRUCTURAL_WARN_THRESHOLD = 0.48
CORE_REPEAT_THRESHOLD = 0.60
TEXT_AUXILIARY_BLOCK_FLOOR = 0.20


class ScenePatternSimilarityGateService:
    """Deterministic structural similarity gate for scene drafts.

    The service is read-only and has no provider dependency. It compares broad
    scene responsibilities and progression deltas, not project-specific nouns.
    """

    def inspect_draft(
        self,
        *,
        content: SceneDraftContent,
        writing_context: SceneWritingContext,
        progression: SceneProgressionStatement | None,
    ) -> ScenePatternSimilarityReport:
        current = self.signature_from_parts(
            content=content,
            writing_context=writing_context,
            progression=progression,
        )
        previous = self.signatures_from_context(writing_context)
        return self.compare(
            current_signature=current,
            previous_signatures=previous[-3:],
            target_type="scene",
            target_id=writing_context.scene_id,
        )

    def inspect_scene(
        self,
        *,
        scene: Scene,
        recent_scenes: list[Scene] | None = None,
    ) -> ScenePatternSimilarityReport:
        current = self.signature_from_scene(scene)
        previous = [
            self.signature_from_scene(item)
            for item in sorted(
                recent_scenes or [],
                key=lambda value: (value.scene_index, value.updated_at or ""),
            )
            if item.chapter_id == scene.chapter_id
            and item.scene_id != scene.scene_id
            and item.scene_index < scene.scene_index
            and str(item.status or "").lower() in {"confirmed", "temporary_confirmed"}
        ]
        return self.compare(
            current_signature=current,
            previous_signatures=previous[-3:],
            target_type="scene",
            target_id=scene.scene_id,
        )

    def signature_from_parts(
        self,
        *,
        content: SceneDraftContent,
        writing_context: SceneWritingContext,
        progression: SceneProgressionStatement | None,
    ) -> ScenePatternSignature:
        beat = _as_dict(writing_context.chapter_scene_beat)
        stage = _as_dict(beat.get("stage_strategy"))
        delta = _as_dict(beat.get("required_progression_delta"))
        anchors = _as_dict(beat.get("continuity_anchors"))
        progression = progression or SceneProgressionStatement()
        text = "\n".join(
            [
                beat.get("scene_function") or "",
                progression.scene_objective,
                progression.new_information,
                progression.character_state_delta,
                progression.conflict_turn,
                beat.get("ending_hook_requirement") or "",
                content.synopsis,
                content.prose_text,
            ]
        )
        new_information = _first_text(
            delta,
            "new_information",
        ) or progression.new_information
        character_delta = (
            _first_text(delta, "character_state_delta")
            or progression.character_state_delta
        )
        conflict_turn = _first_text(delta, "conflict_turn") or progression.conflict_turn
        cost_delta = _first_text(delta, "cost_or_risk_delta")
        ending_hook = str(beat.get("ending_hook_requirement") or "")
        cast = _unique_strings(
            [
                *writing_context.selected_abcd_participants,
                *progression.required_character_ids,
                *[str(value or "") for value in anchors.get("allowed_returning_characters", [])],
            ]
        )
        setting = _first_text(stage, "location_strategy") or _first_text(
            anchors,
            "allowed_returning_locations",
        )
        time_signature = _first_text(stage, "time_delta")
        return self._signature(
            project_id=writing_context.project_id,
            chapter_id=writing_context.chapter_id,
            scene_id=writing_context.scene_id,
            scene_index=writing_context.scene_index,
            source_target_type="scene",
            source_target_id=writing_context.scene_id,
            scene_function_family=(
                _normalize_label(str(beat.get("function_family") or ""))
                or self._classify_scene_function(
                    str(beat.get("scene_function") or progression.scene_objective)
                )
            ),
            action_mode=(
                _normalize_label(str(stage.get("action_mode") or ""))
                or self._classify_action_mode(text)
            ),
            setting_signature=_normalize_label(setting) or "unknown",
            time_signature=_normalize_label(time_signature) or "unknown",
            cast_signature=cast,
            cast_tier_signature=self._cast_tier_signature(writing_context),
            information_delta_type=self._classify_information_delta(new_information),
            character_state_delta_type=self._classify_character_delta(character_delta),
            conflict_turn_type=self._classify_conflict_turn(conflict_turn),
            ending_hook_type=self._classify_ending_hook(ending_hook),
            has_new_information=self._has_meaningful_delta(new_information),
            has_character_state_delta=self._has_meaningful_delta(character_delta),
            has_conflict_turn=self._has_meaningful_delta(conflict_turn),
            has_cost_or_risk_delta=self._has_meaningful_delta(cost_delta),
            has_distinct_ending_hook=self._has_meaningful_delta(ending_hook),
            text=text,
            source_refs=[
                *writing_context.source_refs,
                *[str(value or "") for value in beat.get("source_refs", [])],
            ],
        )

    def signatures_from_context(
        self,
        writing_context: SceneWritingContext,
    ) -> list[ScenePatternSignature]:
        signatures: list[ScenePatternSignature] = []
        for item in writing_context.confirmed_scene_summaries[-3:]:
            if not isinstance(item, dict):
                continue
            text = "\n".join(
                str(item.get(key) or "")
                for key in (
                    "progression_objective",
                    "goal",
                    "synopsis",
                    "event_summary",
                    "state_change_summary",
                    "prose_fragment",
                    "safe_summary",
                )
            )
            scene_index = _safe_int(item.get("scene_index"), default=1)
            signatures.append(
                self._signature(
                    project_id=writing_context.project_id,
                    chapter_id=str(item.get("chapter_id") or writing_context.chapter_id),
                    scene_id=str(item.get("scene_id") or f"scene_{scene_index:03d}"),
                    scene_index=scene_index,
                    source_target_type="scene",
                    source_target_id=str(item.get("scene_id") or ""),
                    scene_function_family=self._classify_scene_function(text),
                    action_mode=self._classify_action_mode(text),
                    setting_signature="unknown",
                    time_signature="unknown",
                    cast_signature=[],
                    cast_tier_signature=[],
                    information_delta_type=self._classify_information_delta(text),
                    character_state_delta_type=self._classify_character_delta(text),
                    conflict_turn_type=self._classify_conflict_turn(text),
                    ending_hook_type=self._classify_ending_hook(text),
                    has_new_information=self._has_meaningful_delta(
                        str(item.get("event_summary") or item.get("progression_objective") or "")
                    ),
                    has_character_state_delta=self._has_meaningful_delta(
                        str(item.get("state_change_summary") or "")
                    ),
                    has_conflict_turn=self._has_meaningful_delta(str(item.get("goal") or "")),
                    has_cost_or_risk_delta=_contains_any(
                        text,
                        {"cost", "risk", "danger", "loss", "pressure", "代价", "风险", "压力"},
                    ),
                    has_distinct_ending_hook=self._has_meaningful_delta(text),
                    text=text,
                    source_refs=[f"scene:{item.get('scene_id')}"] if item.get("scene_id") else [],
                )
            )
        return signatures

    def signature_from_scene(self, scene: Scene) -> ScenePatternSignature:
        trace = scene.generation_trace
        writing_context = trace.scene_writing_context
        progression = trace.scene_progression_statement
        if writing_context is not None:
            content = scene.content or SceneDraftContent(
                synopsis=scene.synopsis,
                prose_text=scene.prose_text,
            )
            return self.signature_from_parts(
                content=content,
                writing_context=writing_context,
                progression=progression,
            )
        content = scene.content or SceneDraftContent(
            synopsis=scene.synopsis,
            prose_text=scene.prose_text,
        )
        text = "\n".join([scene.goal, content.synopsis, content.prose_text])
        return self._signature(
            project_id=scene.project_id,
            chapter_id=scene.chapter_id,
            scene_id=scene.scene_id,
            scene_index=scene.scene_index,
            source_target_type="scene",
            source_target_id=scene.scene_id,
            scene_function_family=self._classify_scene_function(
                progression.scene_objective if progression else scene.goal
            ),
            action_mode=self._classify_action_mode(text),
            setting_signature=_normalize_label(scene.location) or "unknown",
            time_signature=_normalize_label(scene.time_label) or "unknown",
            cast_signature=_unique_strings(scene.linked_character_ids),
            cast_tier_signature=[],
            information_delta_type=self._classify_information_delta(
                progression.new_information if progression else text
            ),
            character_state_delta_type=self._classify_character_delta(
                progression.character_state_delta if progression else text
            ),
            conflict_turn_type=self._classify_conflict_turn(
                progression.conflict_turn if progression else text
            ),
            ending_hook_type=self._classify_ending_hook(text),
            has_new_information=self._has_meaningful_delta(
                progression.new_information if progression else text
            ),
            has_character_state_delta=self._has_meaningful_delta(
                progression.character_state_delta if progression else ""
            ),
            has_conflict_turn=self._has_meaningful_delta(
                progression.conflict_turn if progression else ""
            ),
            has_cost_or_risk_delta=_contains_any(
                text,
                {"cost", "risk", "danger", "loss", "pressure", "代价", "风险", "压力"},
            ),
            has_distinct_ending_hook=self._has_meaningful_delta(text),
            text=text,
            source_refs=[f"scene:{scene.scene_id}"],
        )

    def compare(
        self,
        *,
        current_signature: ScenePatternSignature,
        previous_signatures: list[ScenePatternSignature],
        target_type: str = "scene",
        target_id: str = "",
    ) -> ScenePatternSimilarityReport:
        if not previous_signatures:
            return self._report(
                current_signature=current_signature,
                compared=[],
                axis_scores=self._empty_axis_scores(),
                structural_score=0.0,
                text_score=0.0,
                verdict="pass",
                findings=[],
                target_type=target_type,
                target_id=target_id,
            )

        comparisons = [
            self._compare_pair(current_signature, previous)
            for previous in previous_signatures
        ]
        best_previous, axis_scores, structural_score, text_score = max(
            comparisons,
            key=lambda item: item[2],
        )
        repeated_core_axes = {
            score.axis
            for score in axis_scores
            if score.axis != "text_similarity" and score.score >= CORE_REPEAT_THRESHOLD
        }
        has_progression = (
            current_signature.has_new_information
            or current_signature.has_character_state_delta
            or current_signature.has_conflict_turn
            or current_signature.has_cost_or_risk_delta
        )
        distinct_hook = self._ending_hook_is_distinct(current_signature, best_previous)
        missing_all_progression = not has_progression and not distinct_hook
        block = (
            structural_score >= STRUCTURAL_BLOCK_THRESHOLD
            and missing_all_progression
            and len(repeated_core_axes) >= 5
        )
        warn = (
            not block
            and structural_score >= STRUCTURAL_WARN_THRESHOLD
            and bool(repeated_core_axes & {"function_similarity", "action_mode_similarity", "conflict_turn_similarity", "ending_hook_similarity"})
            and len(repeated_core_axes) >= 2
        )
        findings: list[ScenePatternSimilarityFinding] = []
        if block:
            findings.append(
                ScenePatternSimilarityFinding(
                    code=SCENE_PATTERN_SIMILARITY_TOO_HIGH,
                    severity="blocking",
                    verdict="block_auto_repair",
                    machine_repairable=True,
                    user_visible=False,
                    technical_summary=(
                        "Current scene repeats recent structural pattern without "
                        "new information, character movement, conflict turn, cost, "
                        "or distinct ending hook."
                    ),
                    evidence_refs=[
                        current_signature.signature_id,
                        best_previous.signature_id,
                    ],
                    source_scene_ids=[best_previous.scene_id],
                    suggested_repair_focus=[
                        "add_information_delta",
                        "add_character_state_delta",
                        "turn_or_escalate_conflict",
                        "change_ending_hook_role",
                    ],
                )
            )
            verdict = "block_auto_repair"
        elif warn:
            findings.append(
                ScenePatternSimilarityFinding(
                    code=SCENE_PATTERN_SIMILARITY_WARNING,
                    severity="warning",
                    verdict="warn_auto_repair",
                    machine_repairable=True,
                    user_visible=False,
                    technical_summary=(
                        "Current scene repeats multiple structural axes; progression "
                        "delta exists but should be strengthened."
                    ),
                    evidence_refs=[
                        current_signature.signature_id,
                        best_previous.signature_id,
                    ],
                    source_scene_ids=[best_previous.scene_id],
                    suggested_repair_focus=[
                        "strengthen_information_delta",
                        "clarify_character_state_delta",
                        "differentiate_action_mode",
                    ],
                )
            )
            verdict = "warn_auto_repair"
        else:
            verdict = "pass"
        return self._report(
            current_signature=current_signature,
            compared=previous_signatures,
            axis_scores=axis_scores,
            structural_score=structural_score,
            text_score=text_score,
            verdict=verdict,
            findings=findings,
            target_type=target_type,
            target_id=target_id,
        )

    def _compare_pair(
        self,
        current: ScenePatternSignature,
        previous: ScenePatternSignature,
    ) -> tuple[ScenePatternSignature, list[ScenePatternSimilarityAxisScore], float, float]:
        axis_scores = [
            self._axis("function_similarity", self._label_similarity(current.scene_function_family, previous.scene_function_family), 1.2),
            self._axis("action_mode_similarity", self._label_similarity(current.action_mode, previous.action_mode), 1.0),
            self._axis("setting_similarity", self._label_similarity(current.setting_signature, previous.setting_signature), 0.6),
            self._axis("cast_overlap", self._jaccard(current.cast_signature, previous.cast_signature), 0.6),
            self._axis("information_delta_absence", self._absence_or_same(current.information_delta_type, previous.information_delta_type, current.has_new_information), 1.2),
            self._axis("character_delta_absence", self._absence_or_same(current.character_state_delta_type, previous.character_state_delta_type, current.has_character_state_delta), 1.2),
            self._axis("conflict_turn_similarity", self._conflict_similarity(current, previous), 1.1),
            self._axis("ending_hook_similarity", self._hook_similarity(current, previous), 1.0),
            self._axis("text_similarity", self._fingerprint_similarity(current.text_fingerprint, previous.text_fingerprint), 0.35),
        ]
        structural_axes = [score for score in axis_scores if score.axis != "text_similarity"]
        total_weight = sum(score.weight for score in structural_axes) or 1.0
        structural_score = sum(score.score * score.weight for score in structural_axes) / total_weight
        text_score = next(
            (score.score for score in axis_scores if score.axis == "text_similarity"),
            0.0,
        )
        return previous, axis_scores, round(structural_score, 4), round(text_score, 4)

    def _report(
        self,
        *,
        current_signature: ScenePatternSignature,
        compared: list[ScenePatternSignature],
        axis_scores: list[ScenePatternSimilarityAxisScore],
        structural_score: float,
        text_score: float,
        verdict: str,
        findings: list[ScenePatternSimilarityFinding],
        target_type: str,
        target_id: str,
    ) -> ScenePatternSimilarityReport:
        report_id = "scene_pattern_report_" + _short_hash(
            {
                "current": current_signature.signature_id,
                "compared": [item.signature_id for item in compared],
                "verdict": verdict,
            },
            length=16,
        )
        return ScenePatternSimilarityReport(
            report_id=report_id,
            target_type=target_type,
            target_id=target_id or current_signature.source_target_id,
            scene_id=current_signature.scene_id,
            chapter_id=current_signature.chapter_id,
            scene_index=current_signature.scene_index,
            current_signature=current_signature,
            compared_signature_ids=[item.signature_id for item in compared],
            axis_scores=axis_scores,
            structural_similarity_score=round(structural_score, 4),
            text_similarity_score=round(text_score, 4),
            verdict=verdict,
            findings=findings,
            safe_to_show_user=False,
            source_refs=_unique_strings(
                [
                    *current_signature.source_refs,
                    *[ref for item in compared for ref in item.source_refs],
                ]
            ),
        )

    def _signature(
        self,
        *,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
        source_target_type: str,
        source_target_id: str,
        scene_function_family: str,
        action_mode: str,
        setting_signature: str,
        time_signature: str,
        cast_signature: list[str],
        cast_tier_signature: list[str],
        information_delta_type: str,
        character_state_delta_type: str,
        conflict_turn_type: str,
        ending_hook_type: str,
        has_new_information: bool,
        has_character_state_delta: bool,
        has_conflict_turn: bool,
        has_cost_or_risk_delta: bool,
        has_distinct_ending_hook: bool,
        text: str,
        source_refs: list[str],
    ) -> ScenePatternSignature:
        text_fingerprint = _normalized_text(text)[:2400]
        payload = {
            "project_id": project_id,
            "chapter_id": chapter_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "scene_function_family": scene_function_family or "unknown",
            "action_mode": action_mode or "unknown",
            "setting_signature": setting_signature or "unknown",
            "time_signature": time_signature or "unknown",
            "cast_signature": _unique_strings(cast_signature),
            "information_delta_type": information_delta_type,
            "character_state_delta_type": character_state_delta_type,
            "conflict_turn_type": conflict_turn_type,
            "ending_hook_type": ending_hook_type,
            "text_fingerprint": text_fingerprint,
        }
        return ScenePatternSignature(
            signature_id="scene_pattern_sig_" + _short_hash(payload, length=16),
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            source_target_type=source_target_type,
            source_target_id=source_target_id,
            scene_function_family=scene_function_family or "unknown",
            action_mode=action_mode or "unknown",
            setting_signature=setting_signature or "unknown",
            time_signature=time_signature or "unknown",
            cast_signature=_unique_strings(cast_signature),
            cast_tier_signature=_unique_strings(cast_tier_signature),
            information_delta_type=information_delta_type or "unknown",
            character_state_delta_type=character_state_delta_type or "unknown",
            conflict_turn_type=conflict_turn_type or "unknown",
            ending_hook_type=ending_hook_type or "unknown",
            has_new_information=has_new_information,
            has_character_state_delta=has_character_state_delta,
            has_conflict_turn=has_conflict_turn,
            has_cost_or_risk_delta=has_cost_or_risk_delta,
            has_distinct_ending_hook=has_distinct_ending_hook,
            text_fingerprint=text_fingerprint,
            source_refs=_unique_strings(source_refs),
        )

    def _classify_scene_function(self, text: str) -> str:
        lowered = text.casefold()
        if _contains_any(lowered, {"open", "establish", "introduce", "begin", "start", "开场", "建立"}):
            return "opening"
        if _contains_any(lowered, {"test", "verify", "confirm", "check", "验证", "测试"}):
            return "verification"
        if _contains_any(lowered, {"turn", "reverse", "complicate", "contradict", "转折", "反转"}):
            return "turn"
        if _contains_any(lowered, {"escalate", "pressure", "danger", "conflict", "升级", "压力"}):
            return "escalation"
        if _contains_any(lowered, {"decide", "choice", "commit", "决策", "选择"}):
            return "decision"
        if _contains_any(lowered, {"resolve", "payoff", "consequence", "结果", "后果"}):
            return "consequence"
        return "unknown" if not text.strip() else "open"

    def _classify_action_mode(self, text: str) -> str:
        lowered = text.casefold()
        for label, markers in {
            "investigate": {"investigate", "search", "trace", "inspect", "调查", "追查"},
            "confront": {"confront", "accuse", "challenge", "fight", "对峙", "冲突"},
            "escape": {"escape", "flee", "evade", "逃"},
            "negotiate": {"negotiate", "bargain", "persuade", "谈判", "说服"},
            "discover": {"discover", "reveal", "find", "learn", "发现", "揭示"},
            "verify": {"verify", "test", "confirm", "prove", "验证", "证实"},
            "decide": {"decide", "choose", "commit", "决定", "选择"},
            "recover": {"recover", "restore", "repair", "rescue", "恢复", "救"},
            "transition": {"move", "travel", "arrive", "leave", "转移", "抵达", "离开"},
        }.items():
            if _contains_any(lowered, markers):
                return label
        return "unknown" if not text.strip() else "investigate"

    def _classify_information_delta(self, text: str) -> str:
        if not self._has_meaningful_delta(text):
            return "none"
        lowered = text.casefold()
        if _contains_any(lowered, {"rule", "law", "constraint", "forbidden", "规则", "限制"}):
            return "new_rule"
        if _contains_any(lowered, {"relationship", "trust", "ally", "betray", "关系", "信任"}):
            return "new_relationship"
        if _contains_any(lowered, {"risk", "danger", "threat", "危", "风险"}):
            return "new_risk"
        if _contains_any(lowered, {"cost", "loss", "price", "sacrifice", "代价", "损失"}):
            return "new_cost"
        if _contains_any(lowered, {"location", "place", "state", "threshold", "地点", "状态"}):
            return "new_location_state"
        return "new_evidence"

    def _classify_character_delta(self, text: str) -> str:
        if not self._has_meaningful_delta(text):
            return "none"
        lowered = text.casefold()
        if _contains_any(lowered, {"goal", "want", "aim", "目标"}):
            return "goal_shift"
        if _contains_any(lowered, {"fear", "doubt", "panic", "恐惧", "怀疑"}):
            return "fear_deepens"
        if _contains_any(lowered, {"relationship", "trust", "ally", "关系", "信任"}):
            return "relationship_shift"
        if _contains_any(lowered, {"cost", "loss", "burden", "代价", "负担"}):
            return "cost_added"
        if _contains_any(lowered, {"know", "learn", "secret", "boundary", "知道", "秘密"}):
            return "knowledge_boundary_changed"
        return "goal_shift"

    def _classify_conflict_turn(self, text: str) -> str:
        if not self._has_meaningful_delta(text):
            return "none"
        lowered = text.casefold()
        if _contains_any(lowered, {"redirect", "shift", "turn", "转向", "改变"}):
            return "redirection"
        if _contains_any(lowered, {"escalate", "worse", "pressure", "升级", "加剧"}):
            return "escalation"
        if _contains_any(lowered, {"verify", "test", "confirm", "验证"}):
            return "verification"
        if _contains_any(lowered, {"pause", "stall", "wait", "暂停"}):
            return "pause"
        if _contains_any(lowered, {"consequence", "result", "cost", "后果", "结果"}):
            return "consequence"
        if _contains_any(lowered, {"choice", "decide", "must", "选择", "必须"}):
            return "choice_pressure"
        return "escalation"

    def _classify_ending_hook(self, text: str) -> str:
        if not self._has_meaningful_delta(text):
            return "none"
        lowered = text.casefold()
        if _contains_any(lowered, {"question", "unknown", "uncertain", "疑问", "未知"}):
            return "new_question"
        if _contains_any(lowered, {"danger", "threat", "risk", "危险", "威胁"}):
            return "new_danger"
        if _contains_any(lowered, {"choice", "decision", "choose", "选择", "决定"}):
            return "new_choice"
        if _contains_any(lowered, {"evidence", "clue", "proof", "线索", "证据"}):
            return "new_evidence"
        if _contains_any(lowered, {"repeat", "same", "again", "重复", "再次"}):
            return "repeated_old_question"
        return "new_question"

    def _has_meaningful_delta(self, value: str) -> bool:
        text = _normalized_text(value)
        if len(text) < 8:
            return False
        return text not in {"none", "unknown", "nochange", "nodelta", "notapplicable"}

    def _cast_tier_signature(self, writing_context: SceneWritingContext) -> list[str]:
        package = writing_context.scene_participation_package or {}
        tier_map = package.get("character_tier_by_id") or package.get("tier_by_character_id") or {}
        if not isinstance(tier_map, dict):
            return []
        return _unique_strings(
            [
                f"{character_id}:{tier_map.get(character_id)}"
                for character_id in writing_context.selected_abcd_participants
                if tier_map.get(character_id)
            ]
        )

    def _axis(self, axis: str, score: float, weight: float) -> ScenePatternSimilarityAxisScore:
        score = max(0.0, min(1.0, float(score or 0.0)))
        return ScenePatternSimilarityAxisScore(
            axis=axis,
            score=round(score, 4),
            weight=weight,
            reason=f"{axis}={score:.4f}",
        )

    def _label_similarity(self, left: str, right: str) -> float:
        left = _normalize_label(left)
        right = _normalize_label(right)
        if not left or not right or "unknown" in {left, right}:
            return 0.0
        return 1.0 if left == right else 0.0

    def _absence_or_same(
        self,
        current_type: str,
        previous_type: str,
        current_has_delta: bool,
    ) -> float:
        if not current_has_delta or current_type == "none":
            return 1.0
        if current_type == previous_type and current_type not in {"unknown", "none"}:
            return 0.55
        return 0.0

    def _conflict_similarity(
        self,
        current: ScenePatternSignature,
        previous: ScenePatternSignature,
    ) -> float:
        if not current.has_conflict_turn or current.conflict_turn_type == "none":
            return 1.0
        return self._label_similarity(current.conflict_turn_type, previous.conflict_turn_type) * 0.75

    def _hook_similarity(
        self,
        current: ScenePatternSignature,
        previous: ScenePatternSignature,
    ) -> float:
        if not current.has_distinct_ending_hook or current.ending_hook_type == "none":
            return 1.0
        return self._label_similarity(current.ending_hook_type, previous.ending_hook_type) * 0.75

    def _ending_hook_is_distinct(
        self,
        current: ScenePatternSignature,
        previous: ScenePatternSignature,
    ) -> bool:
        if not current.has_distinct_ending_hook:
            return False
        return current.ending_hook_type != previous.ending_hook_type

    def _jaccard(self, left: list[str], right: list[str]) -> float:
        left_set = {item.casefold() for item in left if item}
        right_set = {item.casefold() for item in right if item}
        if not left_set or not right_set:
            return 0.0
        return len(left_set & right_set) / len(left_set | right_set)

    def _fingerprint_similarity(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left[:2400], right[:2400]).ratio()

    def _empty_axis_scores(self) -> list[ScenePatternSimilarityAxisScore]:
        return [
            self._axis(axis, 0.0, 1.0)
            for axis in (
                "function_similarity",
                "action_mode_similarity",
                "setting_similarity",
                "cast_overlap",
                "information_delta_absence",
                "character_delta_absence",
                "conflict_turn_similarity",
                "ending_hook_similarity",
                "text_similarity",
            )
        ]


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump(mode="json")
    if isinstance(value, BaseModel):
        return value.dict()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    return {}


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            value = " ".join(str(item or "") for item in value)
        if isinstance(value, dict):
            value = " ".join(str(item or "") for item in value.values())
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _contains_any(text: str, markers: set[str]) -> bool:
    lowered = str(text or "").casefold()
    return any(str(marker or "").casefold() in lowered for marker in markers)


def _normalize_label(value: str) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^a-z0-9_\-\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text or text in {"open", "none", "null", "n_a", "na"}:
        return ""
    return text[:80]


def _normalized_text(value: str) -> str:
    return re.sub(
        r"[\s\u3000,.;:!?，。；：！？\"'`()\[\]{}<>《》]+",
        "",
        str(value or "").casefold(),
    )


def _unique_strings(values: list[Any]) -> list[str]:
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


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _short_hash(value: Any, *, length: int = 16) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]
