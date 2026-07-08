from __future__ import annotations

import re
from typing import Any

from app.backend.models.apparent_contradiction import (
    ApparentContradictionClassificationResult,
    ApparentContradictionContext,
    MatchedNarrativeEvidence,
)
from app.backend.models.continuity import ContinuityIssue
from app.backend.models.narrative_layer import (
    CharacterExpressionRecord,
    CharacterPsychologyTrace,
    ClaimRecord,
    NarrativeDebt,
    NarrativeIntentRecord,
    NarrativeObjectReference,
    PerceptionStateRecord,
)


HARD_BLOCK_CATEGORIES = {
    "world_hard_rule_direct_conflict",
    "forbidden_knowledge",
    "superseded_memory_used",
    "provisional_dependency_changed",
}
CLAIM_EXPLAINABLE_CATEGORIES = {
    "no_source_fact",
    "unverified_old_event",
    "chapter_memory_conflict",
    "premature_information_reveal",
}
PERCEPTION_EXPLAINABLE_CATEGORIES = {
    "location_scene_state_contradiction",
}
PSYCHOLOGY_EXPLAINABLE_CATEGORIES = {
    "no_source_fact",
    "relationship_contradiction",
    "chapter_memory_conflict",
}
FOLLOW_UP_DEVICE_TYPES = {
    "misdirection",
    "hallucination",
    "psychological_contradiction",
    "delayed_explanation",
    "delayed_reveal",
    "foreshadowing",
    "open_ambiguity",
    "symbolic_unresolved",
    "unreliable_claim",
    "unreliable_perception",
}
NON_OBJECTIVE_CLAIM_STATUSES = {
    "unverified_claim",
    "lie",
    "rumor",
    "misinformation",
    "exaggeration",
    "self_deception",
    "unknown",
}
LANGUAGE_ACTION_PATTERNS = (
    "says one thing",
    "does another",
    "action mismatch",
    "language action",
    "language/action",
    "contradicts their action",
    "left",
    "right",
    "言行",
    "口是心非",
    "向左",
    "向右",
    "说",
    "做",
)
WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
LOW_SIGNAL_OVERLAP_TOKENS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "another",
    "any",
    "appear",
    "appears",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "before",
    "by",
    "can",
    "category",
    "claim",
    "claimed",
    "claims",
    "conflict",
    "contradiction",
    "could",
    "current",
    "did",
    "do",
    "does",
    "evidence",
    "fact",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "in",
    "into",
    "is",
    "issue",
    "it",
    "its",
    "knows",
    "location",
    "looked",
    "looks",
    "me",
    "missing",
    "my",
    "of",
    "on",
    "or",
    "other",
    "record",
    "records",
    "said",
    "saw",
    "say",
    "saying",
    "says",
    "scene",
    "see",
    "seeing",
    "sees",
    "she",
    "source",
    "state",
    "story",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "thought",
    "thinks",
    "to",
    "told",
    "unrelated",
    "unsupported",
    "was",
    "we",
    "were",
    "while",
    "with",
    "without",
    "would",
    "you",
    "当前",
    "场景",
    "地点",
    "事实",
    "来源",
    "矛盾",
    "记录",
    "证据",
    "问题",
}
SPEECH_OR_PERCEPTION_VERBS = {
    "claim",
    "claimed",
    "claims",
    "feel",
    "feels",
    "felt",
    "heard",
    "hear",
    "hears",
    "know",
    "knows",
    "knew",
    "look",
    "looked",
    "looks",
    "said",
    "saw",
    "say",
    "saying",
    "says",
    "see",
    "seeing",
    "sees",
    "tell",
    "telling",
    "tells",
    "think",
    "thinking",
    "thinks",
    "thought",
}
ID_PREFIXES = (
    "apparent_",
    "chapter_",
    "char_",
    "claim_",
    "debt_",
    "event_",
    "expr_",
    "intent_",
    "issue_",
    "memory_",
    "perception_",
    "psy_",
    "scene_",
    "trace_",
)
OBJECT_DESCRIPTOR_TOKENS = {
    "altar",
    "arch",
    "atrium",
    "bridge",
    "building",
    "cabinet",
    "castle",
    "cellar",
    "chamber",
    "corridor",
    "cup",
    "desk",
    "door",
    "gate",
    "hall",
    "king",
    "mirror",
    "observatory",
    "palace",
    "passage",
    "roof",
    "room",
    "stair",
    "stairs",
    "street",
    "table",
    "tower",
    "vault",
    "wall",
    "window",
}


class ApparentContradictionClassifier:
    def classify(
        self,
        context: ApparentContradictionContext,
    ) -> list[ApparentContradictionClassificationResult]:
        return [self._classify_issue(context, issue) for issue in context.issues]

    def _classify_issue(
        self,
        context: ApparentContradictionContext,
        issue: ContinuityIssue,
    ) -> ApparentContradictionClassificationResult:
        if issue.category in HARD_BLOCK_CATEGORIES:
            return ApparentContradictionClassificationResult(
                issue_id=issue.issue_id,
                classification="true_continuity_error",
                device_type="hard_rule_conflict",
                quality_gate_action="block",
                evidence_strength="counter_evidence",
                safe_user_summary="该问题属于硬边界或已失效依赖，不能由表面矛盾证据放行。",
                internal_reason=f"Hard category {issue.category} must remain blocking.",
            )

        evidence = _EvidenceAccumulator()
        device_type = ""
        classification = "needs_user_confirmation"
        tracking_action = "none"

        matched_claims = self._match_claims(context, issue)
        for claim in matched_claims:
            evidence.add(
                evidence_type="claim",
                evidence_id=claim.claim_id,
                relation="non_objective_claim_explains_surface_fact",
                strength="strong" if _claim_has_direct_link(issue, claim) else "medium",
                reason="Subjective claim can explain an apparently unsupported fact.",
            )
        if matched_claims:
            device_type = "unreliable_claim"
            classification = "intentional_narrative_device"
            tracking_action = "create_narrative_debt"

        matched_perceptions = self._match_perceptions(context, issue)
        for perception in matched_perceptions:
            evidence.add(
                evidence_type="perception_state",
                evidence_id=perception.perception_state_id,
                relation="subjective_perception_explains_location_or_state_gap",
                strength="strong"
                if _perception_has_direct_link(issue, perception)
                else "medium",
                reason="Subjective perception can explain the apparent state conflict.",
            )
        if matched_perceptions and not device_type:
            device_type = "unreliable_perception"
            classification = "acceptable_ambiguity"
            tracking_action = (
                "create_narrative_debt"
                if any(
                    item.reader_explanation_policy in {"defer", "do_not_explain_yet"}
                    for item in matched_perceptions
                )
                else "none"
            )

        matched_psychology, matched_expressions = self._match_psychology_expression(
            context,
            issue,
        )
        for trace in matched_psychology:
            evidence.add(
                evidence_type="psychology_trace",
                evidence_id=trace.psychology_trace_id,
                relation="inner_state_explains_surface_behavior",
                strength="strong",
                reason="Psychology trace supports an intentional surface behavior gap.",
            )
        for expression in matched_expressions:
            evidence.add(
                evidence_type="expression_record",
                evidence_id=expression.expression_record_id,
                relation="expression_links_inner_state_to_visible_action",
                strength="strong",
                reason="Expression record links the hidden motive to the visible action.",
            )
        if matched_psychology and matched_expressions:
            device_type = device_type or "psychological_contradiction"
            classification = "intentional_narrative_device"
            tracking_action = "create_narrative_debt"

        matched_intents, intent_action, intent_device_type, intent_requires_debt = (
            self._match_valid_intents(context, issue)
        )
        for intent in matched_intents:
            evidence.add(
                evidence_type="narrative_intent",
                evidence_id=intent.narrative_intent_id,
                relation="pre_generation_intent_allows_apparent_contradiction",
                strength="strong",
                reason="Narrative intent was recorded before scene output in this trace.",
            )
        if matched_intents:
            device_type = device_type or intent_device_type or "other"
            classification = "intentional_narrative_device"
            if intent_requires_debt or device_type in FOLLOW_UP_DEVICE_TYPES:
                tracking_action = "create_narrative_debt"
            elif tracking_action == "none":
                tracking_action = "none"

        matched_debts = self._match_debts(
            context,
            issue,
            device_type,
            [intent.narrative_intent_id for intent in matched_intents],
        )
        for debt in matched_debts:
            evidence.add(
                evidence_type="narrative_debt",
                evidence_id=debt.narrative_debt_id,
                relation="existing_follow_up_obligation",
                strength="medium",
                reason="Existing narrative debt tracks the unresolved explanation.",
            )
        if matched_debts and tracking_action == "none":
            tracking_action = "update_narrative_debt"

        if not evidence.has_any:
            action = self._no_evidence_action(issue)
            return ApparentContradictionClassificationResult(
                issue_id=issue.issue_id,
                classification="true_continuity_error"
                if action == "block"
                else "needs_user_confirmation",
                device_type="",
                quality_gate_action=action,
                evidence_strength="weak",
                safe_user_summary="没有找到可解释该表面矛盾的主观事实、意图或叙事债证据。",
                internal_reason="No matching narrative-layer evidence.",
            )

        strength = evidence.strongest_strength
        action = self._gate_action_for_evidence(
            issue=issue,
            strength=strength,
            intent_action=intent_action,
            matched_intents=bool(matched_intents),
            matched_non_intent=evidence.has_non_intent,
        )
        if action == "do_not_block" and issue.category in HARD_BLOCK_CATEGORIES:
            action = "block"
        if action == "do_not_block" and not evidence.has_any:
            action = "require_user_confirmation"
        if tracking_action == "create_narrative_debt" and device_type == "delayed_reveal":
            device_type = "delayed_explanation"

        return ApparentContradictionClassificationResult(
            issue_id=issue.issue_id,
            classification=classification,
            device_type=device_type,
            quality_gate_action=action,
            matched_claim_ids=[claim.claim_id for claim in matched_claims],
            matched_narrative_intent_ids=[
                intent.narrative_intent_id for intent in matched_intents
            ],
            matched_psychology_trace_ids=[
                trace.psychology_trace_id for trace in matched_psychology
            ],
            matched_expression_record_ids=[
                expression.expression_record_id for expression in matched_expressions
            ],
            matched_perception_state_ids=[
                perception.perception_state_id for perception in matched_perceptions
            ],
            matched_narrative_debt_ids=[
                debt.narrative_debt_id for debt in matched_debts
            ],
            matched_refs=evidence.refs,
            matched_evidence=evidence.items,
            evidence_strength=strength,
            safe_user_summary=self._safe_summary(action, device_type),
            internal_reason=evidence.internal_reason,
            tracking_action=tracking_action,
        )

    def _match_claims(
        self,
        context: ApparentContradictionContext,
        issue: ContinuityIssue,
    ) -> list[ClaimRecord]:
        if issue.category not in CLAIM_EXPLAINABLE_CATEGORIES:
            return []
        result: list[ClaimRecord] = []
        issue_text = _issue_text(issue)
        for claim in context.claim_records:
            if claim.status != "active":
                continue
            if claim.truth_status not in NON_OBJECTIVE_CLAIM_STATUSES:
                continue
            if _claim_has_direct_link(issue, claim) or _claim_text_matches_issue(
                issue_text,
                claim.claim_text,
            ):
                result.append(claim)
        return _unique_by_id(result, "claim_id")

    def _match_perceptions(
        self,
        context: ApparentContradictionContext,
        issue: ContinuityIssue,
    ) -> list[PerceptionStateRecord]:
        if issue.category not in PERCEPTION_EXPLAINABLE_CATEGORIES:
            return []
        result: list[PerceptionStateRecord] = []
        issue_text = _issue_text(issue)
        for perception in context.perception_records:
            if perception.status != "active":
                continue
            if (
                _perception_has_direct_link(issue, perception)
                or _perception_text_matches_issue(issue_text, perception)
            ):
                result.append(perception)
        return _unique_by_id(result, "perception_state_id")

    def _match_psychology_expression(
        self,
        context: ApparentContradictionContext,
        issue: ContinuityIssue,
    ) -> tuple[list[CharacterPsychologyTrace], list[CharacterExpressionRecord]]:
        issue_text = _issue_text(issue)
        if issue.category not in PSYCHOLOGY_EXPLAINABLE_CATEGORIES and not any(
            marker in issue_text.casefold() for marker in LANGUAGE_ACTION_PATTERNS
        ):
            return [], []
        traces: list[CharacterPsychologyTrace] = []
        expressions: list[CharacterExpressionRecord] = []
        trace_ids = {
            expression.psychology_trace_id
            for expression in context.expression_records
            if expression.status == "active" and expression.psychology_trace_id
        }
        for trace in context.psychology_traces:
            if trace.status != "active":
                continue
            if trace.psychology_trace_id in trace_ids or _text_overlap(
                issue_text,
                " ".join(
                    [
                        trace.surface_intention,
                        trace.inner_desire,
                        trace.self_deception,
                        trace.suppressed_motive,
                        trace.action_tendency,
                    ]
                ),
            ):
                traces.append(trace)
        valid_trace_ids = {trace.psychology_trace_id for trace in traces}
        for expression in context.expression_records:
            if expression.status != "active":
                continue
            if expression.psychology_trace_id in valid_trace_ids or _text_overlap(
                issue_text,
                " ".join(
                    [
                        expression.actual_action,
                        expression.external_behavior,
                        expression.deception_or_concealment,
                        expression.reader_inference_hint,
                    ]
                ),
            ):
                expressions.append(expression)
        if not traces or not expressions:
            return [], []
        return (
            _unique_by_id(traces, "psychology_trace_id"),
            _unique_by_id(expressions, "expression_record_id"),
        )

    def _match_valid_intents(
        self,
        context: ApparentContradictionContext,
        issue: ContinuityIssue,
    ) -> tuple[list[NarrativeIntentRecord], str, str, bool]:
        matched: list[NarrativeIntentRecord] = []
        strongest_action = "warn"
        device_type = ""
        requires_debt = False
        issue_text = _issue_text(issue)
        for intent in context.narrative_intents:
            if intent.status != "active":
                continue
            if not _intent_is_pre_generation(intent, context):
                continue
            allowed_items = [
                item
                for item in intent.allowed_apparent_contradictions
                if _allowed_item_matches(item, issue, issue_text)
            ]
            if not allowed_items and not _text_overlap(issue_text, intent.summary):
                continue
            matched.append(intent)
            device_type = device_type or _intent_device_type(intent.intent_type)
            for allowed in allowed_items:
                strongest_action = _least_permissive_action(
                    strongest_action,
                    _normalize_intent_action(allowed.expected_gate_action),
                )
                requires_debt = requires_debt or bool(allowed.requires_narrative_debt)
            requires_debt = requires_debt or intent.payoff_required
        return _unique_by_id(matched, "narrative_intent_id"), strongest_action, device_type, requires_debt

    def _match_debts(
        self,
        context: ApparentContradictionContext,
        issue: ContinuityIssue,
        device_type: str,
        matched_intent_ids: list[str],
    ) -> list[NarrativeDebt]:
        result: list[NarrativeDebt] = []
        issue_text = _issue_text(issue)
        apparent_ids = {
            *issue.apparent_contradiction_ids,
            *[
                record.apparent_contradiction_id
                for record in context.existing_apparent_contradictions
                if record.source_issue_id == issue.issue_id
            ],
        }
        for debt in context.narrative_debts:
            if debt.status not in {"active", "intentionally_open"}:
                continue
            if debt.source_apparent_contradiction_id in apparent_ids:
                result.append(debt)
                continue
            if debt.source_narrative_intent_id in matched_intent_ids:
                result.append(debt)
                continue
            if _debt_has_source_ref(debt, issue):
                result.append(debt)
                continue
            if (
                device_type
                and debt.debt_type == _debt_type_for_device(device_type)
                and _text_overlap(issue_text, debt.summary)
            ):
                result.append(debt)
        return _unique_by_id(result, "narrative_debt_id")

    def _gate_action_for_evidence(
        self,
        *,
        issue: ContinuityIssue,
        strength: str,
        intent_action: str,
        matched_intents: bool,
        matched_non_intent: bool,
    ) -> str:
        if issue.category in HARD_BLOCK_CATEGORIES:
            return "block"
        if matched_intents and not matched_non_intent:
            if intent_action == "do_not_block":
                return "warn"
            return intent_action
        if strength == "strong":
            return "warn"
        if strength == "medium":
            return "warn"
        return "require_user_confirmation"

    def _no_evidence_action(self, issue: ContinuityIssue) -> str:
        if issue.category == "missing_or_stale_memory_pack":
            return "warn"
        if issue.category in {"location_scene_state_contradiction", "relationship_contradiction"}:
            return "require_user_confirmation"
        if issue.severity == "blocking":
            return "block"
        return "require_user_confirmation"

    def _safe_summary(self, action: str, device_type: str) -> str:
        label = _device_label(device_type)
        if action == "do_not_block":
            return f"已找到足够的叙事层证据，表面矛盾按「{label}」处理。"
        if action == "warn":
            return f"已找到叙事层证据，表面矛盾按「{label}」降级为提醒。"
        if action == "require_user_confirmation":
            return f"已找到部分叙事层证据，但「{label}」仍需要用户确认。"
        return "该表面矛盾仍按连续性错误处理。"


class _EvidenceAccumulator:
    def __init__(self) -> None:
        self.items: list[MatchedNarrativeEvidence] = []
        self.refs: list[NarrativeObjectReference] = []

    @property
    def has_any(self) -> bool:
        return bool(self.items)

    @property
    def has_non_intent(self) -> bool:
        return any(item.evidence_type != "narrative_intent" for item in self.items)

    @property
    def strongest_strength(self) -> str:
        if any(item.strength == "strong" for item in self.items):
            return "strong"
        if any(item.strength == "medium" for item in self.items):
            return "medium"
        if any(item.strength == "counter_evidence" for item in self.items):
            return "counter_evidence"
        return "weak"

    @property
    def internal_reason(self) -> str:
        ids = [f"{item.evidence_type}:{item.evidence_id}" for item in self.items]
        return "Matched " + ", ".join(ids)

    def add(
        self,
        *,
        evidence_type: str,
        evidence_id: str,
        relation: str,
        strength: str,
        reason: str,
    ) -> None:
        if not evidence_id:
            return
        key = (evidence_type, evidence_id)
        if any((item.evidence_type, item.evidence_id) == key for item in self.items):
            return
        self.items.append(
            MatchedNarrativeEvidence(
                evidence_type=evidence_type,
                evidence_id=evidence_id,
                relation=relation,
                strength=strength,
                reason=reason,
            )
        )
        self.refs.append(
            NarrativeObjectReference(
                object_type=evidence_type,
                object_id=evidence_id,
                relation=relation,
            )
        )


def _issue_text(issue: ContinuityIssue) -> str:
    return " ".join(
        [
            issue.category,
            issue.user_visible_message,
            issue.technical_summary,
            issue.evidence_text,
            " ".join(issue.source_memory_ids),
            " ".join(issue.source_event_ids),
            " ".join(issue.source_scene_ids),
            " ".join(issue.source_character_ids),
            " ".join(issue.source_relationship_ids),
        ]
    ).casefold()


def _claim_has_direct_link(issue: ContinuityIssue, claim: ClaimRecord) -> bool:
    return bool(
        set(issue.source_event_ids).intersection(claim.linked_event_ids)
        or set(issue.source_memory_ids).intersection(claim.linked_memory_ids)
    )


def _perception_has_direct_link(
    issue: ContinuityIssue,
    perception: PerceptionStateRecord,
) -> bool:
    ref_ids = {
        ref.object_id
        for ref in [
            *perception.objective_state_refs,
            *perception.perceived_state_refs,
        ]
        if ref.object_id
    }
    return bool(
        set(issue.source_event_ids).intersection(ref_ids)
        or set(issue.source_memory_ids).intersection(ref_ids)
        or (
            perception.perceived_object_id
            and perception.perceived_object_id
            in {
                *issue.source_scene_ids,
                *issue.source_event_ids,
                *issue.source_memory_ids,
            }
        )
    )


def _debt_has_source_ref(debt: NarrativeDebt, issue: ContinuityIssue) -> bool:
    ref_ids = {
        ref.object_id
        for ref in debt.source_refs
        if ref.object_id
    }
    if issue.issue_id in ref_ids:
        return True
    if issue.issue_id and issue.issue_id in debt.summary:
        return True
    source_ids = {
        *issue.source_memory_ids,
        *issue.source_event_ids,
        *issue.source_scene_ids,
        *issue.source_character_ids,
        *issue.source_relationship_ids,
        *issue.apparent_contradiction_ids,
    }
    return bool(source_ids.intersection(ref_ids))


def _intent_is_pre_generation(
    intent: NarrativeIntentRecord,
    context: ApparentContradictionContext,
) -> bool:
    if not intent.created_before_scene_output:
        return False
    if not context.generation_trace_id or not intent.generation_trace_id:
        return False
    return intent.generation_trace_id == context.generation_trace_id


def _allowed_item_matches(item: Any, issue: ContinuityIssue, issue_text: str) -> bool:
    fields = " ".join(
        [
            getattr(item, "contradiction_type", ""),
            getattr(item, "summary", ""),
            getattr(item, "scope", ""),
            " ".join(
                [
                    ref.object_id
                    for ref in getattr(item, "matched_record_refs", []) or []
                    if ref.object_id
                ]
            ),
        ]
    ).casefold()
    if not fields:
        return False
    if issue.category.casefold() in fields:
        return True
    return _text_overlap(issue_text, fields)


def _normalize_intent_action(action: str) -> str:
    if action in {"do_not_block", "warn", "require_user_confirmation", "block"}:
        return action
    return "warn"


def _least_permissive_action(current: str, candidate: str) -> str:
    order = {
        "do_not_block": 0,
        "warn": 1,
        "require_user_confirmation": 2,
        "block": 3,
    }
    return candidate if order.get(candidate, 1) > order.get(current, 1) else current


def _intent_device_type(intent_type: str) -> str:
    if intent_type == "delayed_reveal":
        return "delayed_explanation"
    return intent_type or "other"


def _debt_type_for_device(device_type: str) -> str:
    if device_type == "delayed_reveal":
        return "delayed_explanation"
    if device_type in {
        "foreshadowing",
        "misdirection",
        "hallucination",
        "delayed_explanation",
        "psychological_contradiction",
        "unreliable_claim",
        "open_ambiguity",
        "symbolic_unresolved",
    }:
        return device_type
    if device_type == "unreliable_perception":
        return "hallucination"
    return "other"


def _device_label(device_type: str) -> str:
    labels = {
        "unreliable_claim": "非客观角色陈述",
        "unreliable_perception": "主观感知偏差",
        "psychological_contradiction": "心理层表面矛盾",
        "intention_action_divergence": "言行/意图差异",
        "misdirection": "误导",
        "hallucination": "幻觉",
        "delayed_explanation": "延迟解释",
        "foreshadowing": "伏笔",
        "open_ambiguity": "开放歧义",
        "symbolic_unresolved": "象征性未解",
        "other": "其他叙事装置",
    }
    return labels.get(device_type or "other", device_type or "其他叙事装置")


def _text_overlap(left: str, right: str, *, minimum: int = 2) -> bool:
    left_tokens = _meaningful_tokens(left)
    right_tokens = _meaningful_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if len(left_tokens.intersection(right_tokens)) >= minimum:
        return True
    compact_left = _compact_meaningful_text(left)
    compact_right = _compact_meaningful_text(right)
    return bool(
        compact_left
        and compact_right
        and (compact_left in compact_right or compact_right in compact_left)
        and min(len(compact_left), len(compact_right)) >= 6
    )


def _claim_text_matches_issue(issue_text: str, claim_text: str) -> bool:
    return _meaningful_sequence_contains(issue_text, claim_text, minimum=2)


def _perception_text_matches_issue(
    issue_text: str,
    perception: PerceptionStateRecord,
) -> bool:
    summary_text = " ".join(
        [
            perception.perceived_state_summary,
            perception.objective_state_summary,
        ]
    )
    if _meaningful_sequence_contains(issue_text, summary_text, minimum=3):
        return True

    object_tokens = _object_identifier_tokens(perception.perceived_object_id)
    if not object_tokens:
        return False

    issue_tokens = _ordered_meaningful_tokens(issue_text)
    summary_tokens = _ordered_meaningful_tokens(summary_text)
    issue_token_set = set(issue_tokens)
    if not object_tokens.issubset(issue_token_set):
        return False

    issue_predicates = _predicate_tokens(issue_tokens, object_tokens)
    summary_predicates = _predicate_tokens(summary_tokens, object_tokens)
    return bool(issue_predicates.intersection(summary_predicates))


def _meaningful_sequence_contains(
    left: str,
    right: str,
    *,
    minimum: int,
) -> bool:
    left_tokens = _ordered_meaningful_tokens(left)
    right_tokens = _ordered_meaningful_tokens(right)
    if min(len(left_tokens), len(right_tokens)) < minimum:
        return False
    return _contains_contiguous_sequence(
        left_tokens,
        right_tokens,
    ) or _contains_contiguous_sequence(
        right_tokens,
        left_tokens,
    )


def _contains_contiguous_sequence(container: list[str], candidate: list[str]) -> bool:
    if not candidate or len(candidate) > len(container):
        return False
    window_size = len(candidate)
    return any(
        container[index : index + window_size] == candidate
        for index in range(0, len(container) - window_size + 1)
    )


def _object_identifier_tokens(value: str) -> set[str]:
    return set(_ordered_meaningful_tokens(re.sub(r"[_\-]+", " ", str(value or ""))))


def _predicate_tokens(tokens: list[str], object_tokens: set[str]) -> set[str]:
    return {
        token
        for token in tokens
        if token not in object_tokens and token not in OBJECT_DESCRIPTOR_TOKENS
    }


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in WORD_RE.findall(str(value or ""))
        if len(token) >= 2
    }


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token
        for token in _ordered_meaningful_tokens(value)
    }


def _ordered_meaningful_tokens(value: str) -> list[str]:
    raw_tokens = [token.casefold() for token in WORD_RE.findall(str(value or ""))]
    result: list[str] = []
    for index, token in enumerate(raw_tokens):
        if _is_low_signal_overlap_token(token):
            continue
        if _is_actor_intro_token(raw_tokens, index):
            continue
        result.append(token)
    return result


def _compact_meaningful_text(value: str) -> str:
    return "".join(_ordered_meaningful_tokens(value))


def _is_low_signal_overlap_token(token: str) -> bool:
    return (
        len(token) < 2
        or token.isdigit()
        or token in LOW_SIGNAL_OVERLAP_TOKENS
        or any(token.startswith(prefix) for prefix in ID_PREFIXES)
    )


def _is_actor_intro_token(tokens: list[str], index: int) -> bool:
    if index + 1 >= len(tokens):
        return False
    token = tokens[index]
    if _is_low_signal_overlap_token(token):
        return False
    return tokens[index + 1] in SPEECH_OR_PERCEPTION_VERBS


def _unique_by_id(items: list[Any], attr: str) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        item_id = str(getattr(item, attr, "") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result
