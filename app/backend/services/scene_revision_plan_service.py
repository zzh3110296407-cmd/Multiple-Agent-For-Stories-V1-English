from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.backend.models.scene_gate_repair import (
    SCENE_REVISION_PLAN_SCHEMA_VERSION,
    SceneGateAnalysisReport,
    SceneGateRootCauseGroup,
    SceneRevisionPlan,
    SceneRevisionPlanAction,
)


SHANGHAI_TZ = timezone(timedelta(hours=8))
UNSAFE_TEXT_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_\-]+"),
    re.compile(r"\b(raw_prompt|raw_response|hidden_reasoning|hidden_prompt)\b", re.I),
    re.compile(r"\b(chain[-_ ]of[-_ ]thought|provider raw|traceback)\b", re.I),
]
FORBIDDEN_CHANGES_BASE = [
    "do_not_change_user_premise",
    "do_not_change_world_hard_rules_without_confirmation",
    "do_not_change_character_identity_without_confirmation",
    "do_not_change_character_goal_without_confirmation",
    "do_not_create_or_confirm_characters",
    "do_not_write_memory",
    "do_not_resolve_continuity_issues",
    "do_not_confirm_scene",
    "do_not_commit_canon_facts",
    "do_not_replace_prompt_first_content_with_demo_or_fallback_content",
]
CONTENT_AFFECTING_ACTION_TYPES = {
    "rewrite_scene_prose",
    "refresh_scene_information",
    "refresh_story_information_package",
    "regenerate_memory_extraction_candidates",
}
MACHINE_ACTION_TYPES = {
    "rewrite_scene_prose",
    "refresh_scene_information",
    "refresh_story_information_package",
    "refresh_memory_retrieval",
    "regenerate_memory_extraction_candidates",
    "refresh_scene_participation",
}
USER_CONTENT_TOUCH_CATEGORIES = {
    "world_hard_rule_direct_conflict",
    "forbidden_knowledge",
    "complete_prior_story",
    "mark_as_subjective_claim",
    "subjective_claim_conversion",
    "abcd_runtime_requires_user_confirmation",
}
SCENE_PATTERN_REPAIR_CATEGORIES = {
    "scene_pattern_similarity_warning",
    "scene_pattern_similarity_too_high",
}


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def model_to_dict(model: Any) -> dict[str, Any]:
    if isinstance(model, dict):
        return dict(model)
    if hasattr(model, "model_dump") and callable(model.model_dump):
        return model.model_dump(mode="json")
    if hasattr(model, "dict") and callable(model.dict):
        return model.dict()
    raise TypeError(f"Unsupported model type: {type(model)!r}")


class SceneRevisionPlanService:
    """Build deterministic SceneRevisionPlan objects from M3 analysis reports.

    This is a planning-only layer. It does not execute repairs, refresh runtime
    evidence, rerun gates, call providers, create candidates, or mutate storage.
    """

    def build_revision_plan(
        self,
        analysis_report: SceneGateAnalysisReport | dict[str, Any],
    ) -> SceneRevisionPlan:
        report = self._coerce_analysis_report(analysis_report)
        groups = sorted(
            report.root_cause_groups,
            key=lambda group: (group.priority, group.group_signature, group.group_id),
        )

        actions: list[SceneRevisionPlanAction] = []
        for group in groups:
            actions.extend(self._actions_for_group(group))
        actions = sorted(
            actions,
            key=lambda action: (
                action.priority,
                action.action_type,
                action.root_cause_layer,
                action.target_repair_system,
                action.action_signature,
            ),
        )

        if not actions and report.recommended_next_action == "no_repair_needed":
            plan_status = "no_repair_needed"
            recommended_next_step = "no_repair_needed"
            stop_reason = ""
        else:
            plan_status, recommended_next_step, stop_reason = self._plan_status(
                actions=actions,
                report=report,
            )

        auto_repair_plan_allowed = self._auto_repair_plan_allowed(
            report=report,
            actions=actions,
        )
        action_signatures = [action.action_signature for action in actions]
        revision_plan_signature = self._stable_id(
            "scene_revision_plan_signature",
            {
                "analysis_id": report.analysis_id,
                "gate_run_id": report.gate_run_id,
                "scene_id": report.scene_id,
                "candidate_id": report.candidate_id,
                "revision_id": report.revision_id,
                "group_signatures": [group.group_signature for group in groups],
                "action_signatures": action_signatures,
                "recommended_next_step": recommended_next_step,
            },
        )

        plan = SceneRevisionPlan(
            schema_version=SCENE_REVISION_PLAN_SCHEMA_VERSION,
            revision_plan_id=f"scene_revision_plan_{revision_plan_signature[-16:]}",
            revision_plan_signature=revision_plan_signature,
            analysis_id=report.analysis_id,
            gate_run_id=report.gate_run_id,
            project_id=report.project_id,
            chapter_id=report.chapter_id,
            scene_id=report.scene_id,
            candidate_id=report.candidate_id,
            revision_id=report.revision_id,
            round_index=report.round_index,
            generated_at=now_iso(),
            plan_status=plan_status,
            recommended_next_step=recommended_next_step,
            root_cause_group_ids=[group.group_id for group in groups],
            finding_ids=[
                finding_id
                for group in groups
                for finding_id in group.finding_ids
            ],
            finding_signatures=[
                signature
                for group in groups
                for signature in group.finding_signatures
            ],
            repair_actions=actions,
            blocked_group_ids=self._blocked_group_ids(groups),
            user_visible_group_ids=[
                group.group_id for group in groups if group.user_visible_required
            ],
            user_action_required_group_ids=[
                group.group_id for group in groups if group.user_action_required
            ],
            requires_user_confirmation=any(
                action.requires_user_confirmation for action in actions
            ),
            requires_expert_review=any(action.requires_expert_review for action in actions),
            auto_repair_plan_allowed=auto_repair_plan_allowed,
            may_touch_user_requested_content=any(
                action.may_touch_user_requested_content for action in actions
            ),
            requires_fresh_story_information=any(
                action.requires_fresh_story_information for action in actions
            ),
            requires_fresh_memory_retrieval=any(
                action.requires_fresh_memory_retrieval for action in actions
            ),
            requires_fresh_memory_extraction=any(
                action.requires_fresh_memory_extraction for action in actions
            ),
            requires_fresh_quality_check=any(
                action.requires_fresh_quality_check for action in actions
            ),
            requires_fresh_continuity_check=any(
                action.requires_fresh_continuity_check for action in actions
            ),
            requires_runtime_refresh_after_repair=any(
                action.requires_runtime_refresh_after_repair for action in actions
            ),
            user_intent_preservation_notes=report.user_intent_preservation_notes,
            forbidden_changes=[
                forbidden
                for action in actions
                for forbidden in action.forbidden_changes
            ],
            plan_summary=self._plan_summary(
                plan_status=plan_status,
                recommended_next_step=recommended_next_step,
                actions=actions,
            ),
            safe_user_summary=self._plan_safe_user_summary(
                report=report,
                actions=actions,
            ),
            stop_reason=stop_reason,
            source_refs=self._unique_strings(
                [
                    *report.source_refs,
                    f"scene_gate_analysis:{report.analysis_id}",
                    *[f"scene_gate_group:{group.group_id}" for group in groups],
                ]
            ),
        )
        return plan

    def _coerce_analysis_report(
        self,
        value: SceneGateAnalysisReport | dict[str, Any],
    ) -> SceneGateAnalysisReport:
        if isinstance(value, SceneGateAnalysisReport):
            return value
        return SceneGateAnalysisReport(**model_to_dict(value))

    def _actions_for_group(
        self,
        group: SceneGateRootCauseGroup,
    ) -> list[SceneRevisionPlanAction]:
        if (
            group.target_repair_system == "expert_review"
            or group.recommended_next_action == "stop_for_expert_review"
        ) and self._group_requires_immediate_stop(group):
            return [self._stop_action(group, expert=True)]
        if (
            group.user_action_required or group.requires_user_confirmation
        ) and self._group_requires_immediate_stop(group):
            return [self._stop_action(group, expert=False)]
        if (
            group.target_repair_system in {"expert_review", "user_confirmation"}
            or group.recommended_next_action
            in {"stop_for_expert_review", "stop_for_user_confirmation"}
        ):
            return []

        layer = group.root_cause_layer
        target = group.target_repair_system
        categories = {category.casefold() for category in group.categories}
        if layer == "writer_prose_output" and target == "writer":
            is_pattern_repair = bool(categories & SCENE_PATTERN_REPAIR_CATEGORIES)
            return [
                self._repair_action(
                    group,
                    action_type="rewrite_scene_prose",
                    instruction=(
                        self._pattern_writer_repair_instruction(group)
                        if is_pattern_repair
                        else (
                            "Rewrite only the scene prose to address the listed quality issue while "
                            "preserving user premise, confirmed facts, active participants, scene objective, "
                            "and hard world rules."
                        )
                    ),
                    required_inputs=[
                        "current_scene_draft",
                        "scene_gate_analysis_report",
                        "active_scene_participants",
                        "confirmed_story_facts",
                    ],
                    expected_outputs=["scene_prose_revision_candidate"],
                    allowed_change_scope=(
                        [
                            "current_scene_synopsis",
                            "current_scene_prose",
                            "current_scene_draft_content",
                        ]
                        if is_pattern_repair
                        else ["scene_prose_only"]
                    ),
                    requires_fresh_quality_check=True,
                    requires_fresh_continuity_check=True,
                    requires_runtime_refresh_after_repair=True,
                    requires_fresh_memory_extraction=True,
                )
            ]
        if layer == "scene_information" and target == "scene_information":
            may_touch = bool(
                categories
                & {"scene_objective_repeated", "scene_progression_statement_missing"}
            )
            return [
                self._repair_action(
                    group,
                    action_type="refresh_scene_information",
                    instruction=(
                        "Refresh only scene information needed to remove the gate finding. Preserve "
                        "confirmed story facts and do not rewrite prose in M4."
                    ),
                    required_inputs=["current_scene_information", "scene_gate_analysis_report"],
                    expected_outputs=["refreshed_scene_information"],
                    allowed_change_scope=["scene_information_only"],
                    may_touch_user_requested_content=may_touch,
                    requires_user_confirmation=may_touch,
                    requires_fresh_quality_check=True,
                    requires_fresh_continuity_check=True,
                    requires_runtime_refresh_after_repair=True,
                )
            ]
        if layer == "ordered_story_information_package" and target == "story_information_integrator":
            return [
                self._repair_action(
                    group,
                    action_type="refresh_story_information_package",
                    instruction=(
                        "Refresh the ordered StoryInformation package while preserving the user's premise. "
                        "Do not replace prompt-first content with fallback or demo content."
                    ),
                    required_inputs=[
                        "project_story_premise",
                        "current_story_information_package",
                        "scene_gate_analysis_report",
                    ],
                    expected_outputs=["refreshed_story_information_package"],
                    allowed_change_scope=["story_information_package_only"],
                    requires_fresh_story_information=True,
                    requires_fresh_quality_check=True,
                    requires_fresh_continuity_check=True,
                    requires_runtime_refresh_after_repair=True,
                )
            ]
        if layer == "memory_pack" and target == "memory_retrieval":
            return [
                self._repair_action(
                    group,
                    action_type="refresh_memory_retrieval",
                    instruction=(
                        "Refresh scene memory retrieval evidence only. Do not write memory or resolve "
                        "continuity issues in M4."
                    ),
                    required_inputs=["scene_memory_pack", "scene_gate_analysis_report"],
                    expected_outputs=["refreshed_memory_retrieval_plan"],
                    allowed_change_scope=["memory_retrieval_context_only"],
                    requires_fresh_memory_retrieval=True,
                    requires_fresh_quality_check=True,
                    requires_fresh_continuity_check=True,
                )
            ]
        if layer == "memory_extraction_candidate":
            return [
                self._repair_action(
                    group,
                    action_type="regenerate_memory_extraction_candidates",
                    instruction=(
                        "Regenerate memory extraction candidates later from confirmed scene content. "
                        "Do not write memory or canon facts in M4."
                    ),
                    required_inputs=["current_scene_draft", "scene_gate_analysis_report"],
                    expected_outputs=["memory_extraction_candidate_plan"],
                    allowed_change_scope=["memory_extraction_candidates_only"],
                    requires_fresh_memory_extraction=True,
                    requires_fresh_quality_check=True,
                    requires_fresh_continuity_check=True,
                )
            ]
        if layer == "scene_participation" and target == "scene_participation":
            return [
                self._repair_action(
                    group,
                    action_type="refresh_scene_participation",
                    instruction=(
                        "Refresh the scene participation package later. Do not create, confirm, or "
                        "change characters in M4."
                    ),
                    required_inputs=["scene_participation_package", "scene_gate_analysis_report"],
                    expected_outputs=["refreshed_scene_participation_package"],
                    allowed_change_scope=["scene_participation_package_only"],
                    requires_fresh_quality_check=True,
                    requires_fresh_continuity_check=True,
                    requires_runtime_refresh_after_repair=True,
                )
            ]
        if layer == "runtime_evidence" and target == "runtime_refresh":
            return [
                self._repair_action(
                    group,
                    action_type="refresh_runtime_evidence",
                    instruction=(
                        "Refresh runtime and gate evidence later. M4 only records that refresh is required."
                    ),
                    required_inputs=["runtime_evidence_refs", "scene_gate_analysis_report"],
                    expected_outputs=["fresh_runtime_evidence"],
                    allowed_change_scope=["runtime_evidence_only"],
                    requires_runtime_refresh_after_repair=True,
                )
            ]
        if layer == "provider_degraded" and target == "provider_retry":
            return [self._stop_action(group, expert=True)]
        return [self._stop_action(group, expert=True)]

    def _repair_action(
        self,
        group: SceneGateRootCauseGroup,
        *,
        action_type: str,
        instruction: str,
        required_inputs: list[str],
        expected_outputs: list[str],
        allowed_change_scope: list[str],
        may_touch_user_requested_content: bool = False,
        requires_user_confirmation: bool = False,
        requires_expert_review: bool = False,
        requires_fresh_story_information: bool = False,
        requires_fresh_memory_retrieval: bool = False,
        requires_fresh_memory_extraction: bool = False,
        requires_fresh_quality_check: bool = False,
        requires_fresh_continuity_check: bool = False,
        requires_runtime_refresh_after_repair: bool = False,
    ) -> SceneRevisionPlanAction:
        categories = {category.casefold() for category in group.categories}
        may_touch_user_requested_content = may_touch_user_requested_content or bool(
            categories & USER_CONTENT_TOUCH_CATEGORIES
        )
        requires_user_confirmation = requires_user_confirmation or may_touch_user_requested_content
        action_signature = self._action_signature(group, action_type)
        forbidden_changes = self._forbidden_changes(action_type, group)
        return SceneRevisionPlanAction(
            action_id=f"scene_revision_action_{action_signature[-16:]}",
            action_signature=action_signature,
            action_type=action_type,
            target_repair_system=group.target_repair_system,
            root_cause_layer=group.root_cause_layer,
            source_group_ids=[group.group_id],
            source_finding_ids=group.finding_ids,
            source_finding_signatures=group.finding_signatures,
            source_categories=group.categories,
            priority=group.priority,
            risk_level=group.risk_level,
            action_summary=self._action_summary(group, action_type),
            repair_instruction=self._sanitize_text(instruction, limit=900),
            safe_user_summary=self._action_safe_user_summary(group, action_type),
            required_inputs=required_inputs,
            expected_outputs=expected_outputs,
            forbidden_changes=forbidden_changes,
            allowed_change_scope=allowed_change_scope,
            may_touch_user_requested_content=may_touch_user_requested_content,
            requires_user_confirmation=requires_user_confirmation,
            requires_expert_review=requires_expert_review,
            requires_fresh_story_information=requires_fresh_story_information,
            requires_fresh_memory_retrieval=requires_fresh_memory_retrieval,
            requires_fresh_memory_extraction=requires_fresh_memory_extraction,
            requires_fresh_quality_check=requires_fresh_quality_check,
            requires_fresh_continuity_check=requires_fresh_continuity_check,
            requires_runtime_refresh_after_repair=requires_runtime_refresh_after_repair,
            stop_reason="",
        )

    def _stop_action(
        self,
        group: SceneGateRootCauseGroup,
        *,
        expert: bool,
    ) -> SceneRevisionPlanAction:
        action_type = "stop_for_expert_review" if expert else "stop_for_user_confirmation"
        action_signature = self._action_signature(group, action_type)
        reason = (
            "expert_review_required_before_safe_repair"
            if expert
            else group.user_action_reason
            or group.recommended_stop_reason
            or "user_confirmation_required_before_safe_repair"
        )
        return SceneRevisionPlanAction(
            action_id=f"scene_revision_action_{action_signature[-16:]}",
            action_signature=action_signature,
            action_type=action_type,
            target_repair_system=group.target_repair_system,
            root_cause_layer=group.root_cause_layer,
            source_group_ids=[group.group_id],
            source_finding_ids=group.finding_ids,
            source_finding_signatures=group.finding_signatures,
            source_categories=group.categories,
            priority=group.priority,
            risk_level=group.risk_level,
            action_summary=self._action_summary(group, action_type),
            repair_instruction=(
                "Stop planning for automatic repair. A user or expert must review the affected "
                "content before any later milestone may execute changes."
            ),
            safe_user_summary=self._action_safe_user_summary(group, action_type),
            required_inputs=["user_confirmation"] if not expert else ["expert_review"],
            expected_outputs=["user_decision"] if not expert else ["expert_decision"],
            forbidden_changes=self._forbidden_changes(action_type, group),
            allowed_change_scope=[],
            may_touch_user_requested_content=not expert or self._may_touch_user_content(group),
            requires_user_confirmation=not expert,
            requires_expert_review=expert,
            requires_fresh_story_information=False,
            requires_fresh_memory_retrieval=False,
            requires_fresh_memory_extraction=False,
            requires_fresh_quality_check=False,
            requires_fresh_continuity_check=False,
            requires_runtime_refresh_after_repair=False,
            stop_reason=self._sanitize_text(reason, limit=900),
        )

    def _plan_status(
        self,
        *,
        actions: list[SceneRevisionPlanAction],
        report: SceneGateAnalysisReport,
    ) -> tuple[str, str, str]:
        if any(action.requires_expert_review for action in actions):
            return "requires_expert_review", "stop_for_expert_review", self._stop_reason(actions)
        if any(action.requires_user_confirmation for action in actions):
            return (
                "requires_user_confirmation",
                "stop_for_user_confirmation",
                self._stop_reason(actions),
            )
        if any(action.action_type == "refresh_runtime_evidence" for action in actions):
            return "refresh_required", "refresh_runtime_or_gate_evidence_later", ""
        if actions and all(action.action_type in MACHINE_ACTION_TYPES for action in actions):
            return "ready_for_repair", "execute_repair_plan_later", ""
        if report.recommended_next_action == "refresh_runtime_or_gate_evidence":
            return "refresh_required", "refresh_runtime_or_gate_evidence_later", ""
        return (
            "blocked_no_safe_plan",
            "blocked_unsafe_for_auto_repair",
            "no_safe_scene_revision_plan_available",
        )

    def _auto_repair_plan_allowed(
        self,
        *,
        report: SceneGateAnalysisReport,
        actions: list[SceneRevisionPlanAction],
    ) -> bool:
        return bool(
            report.auto_repair_allowed
            and not report.user_action_required
            and actions
            and any(action.action_type in MACHINE_ACTION_TYPES for action in actions)
            and all(
                not action.requires_user_confirmation
                and not action.requires_expert_review
                and not action.may_touch_user_requested_content
                and action.action_type
                not in {"stop_for_user_confirmation", "stop_for_expert_review"}
                for action in actions
            )
        )

    def _blocked_group_ids(self, groups: list[SceneGateRootCauseGroup]) -> list[str]:
        return [
            group.group_id
            for group in groups
            if self._group_requires_immediate_stop(group)
        ]

    def _group_requires_immediate_stop(self, group: SceneGateRootCauseGroup) -> bool:
        return bool(
            group.blocks_final_output
            or group.blocks_auto_repair
            or group.requires_user_confirmation
            or group.user_action_required
            or "blocking" in group.severities
            or "requires_user_confirmation" in group.severities
            or group.risk_level == "critical"
        )

    def _forbidden_changes(
        self,
        action_type: str,
        group: SceneGateRootCauseGroup,
    ) -> list[str]:
        forbidden = list(FORBIDDEN_CHANGES_BASE)
        if action_type == "refresh_scene_participation":
            forbidden.extend(
                [
                    "do_not_create_characters",
                    "do_not_confirm_characters",
                    "do_not_change_character_tiers",
                ]
            )
        if group.root_cause_layer in {"world_canvas", "user_intent_conflict"}:
            forbidden.append("do_not_change_user_intent_without_confirmation")
        if set(group.categories) & {
            "complete_prior_story",
            "missing_source_fact",
            "no_source_fact",
        }:
            forbidden.append("do_not_invent_prior_story_facts")
        if set(group.categories) & {"mark_as_subjective_claim", "subjective_claim_conversion"}:
            forbidden.append("do_not_mark_subjective_claim_as_objective_fact")
        return self._unique_strings(forbidden)

    def _pattern_writer_repair_instruction(
        self,
        group: SceneGateRootCauseGroup,
    ) -> str:
        focus = ", ".join(group.suggested_repair_types[:6]) or "scene progression"
        evidence = ", ".join(group.evidence_refs[:8])
        parts = [
            "Rewrite only the current scene draft text to repair repeated scene pattern structure; do not paraphrase the same dramatic function.",
            "Preserve current project premise, confirmed prior facts, world hard rules, confirmed characters, active participants, legitimate continuity anchors, and current chapter_scene_beat responsibility.",
            "Add or strengthen real new_information, character_state_delta, conflict_turn, and cost_or_risk_delta when the beat requires it.",
            "Differentiate repeated action mode where possible and change a repeated ending hook into a new question, choice, danger, evidence, or consequence.",
            "Do not invent unsupported prior-story-completion facts, delete user-confirmed story elements, write events, write memory, confirm permanent facts, change world rules, change character canon, or write final output.",
            f"Use pattern repair focus: {focus}.",
        ]
        if evidence:
            parts.append(f"Use hidden pattern evidence refs only for repair targeting: {evidence}.")
        return self._sanitize_text(" ".join(parts), limit=900)

    def _action_summary(
        self,
        group: SceneGateRootCauseGroup,
        action_type: str,
    ) -> str:
        categories = ", ".join(group.categories[:3]) or "gate finding"
        return self._sanitize_text(
            f"{action_type} planned for {group.root_cause_layer}/{group.target_repair_system}: {categories}.",
            limit=900,
        )

    def _action_safe_user_summary(
        self,
        group: SceneGateRootCauseGroup,
        action_type: str,
    ) -> str:
        source_summary = (
            group.user_facing_safe_summary
            or group.safe_summary
            or self._action_summary(group, action_type)
        )
        options = ""
        if group.user_action_options:
            options = f" Available user options: {', '.join(group.user_action_options)}."
        return self._sanitize_text(
            f"{source_summary} Planned next action: {action_type}.{options}",
            limit=900,
        )

    def _plan_summary(
        self,
        *,
        plan_status: str,
        recommended_next_step: str,
        actions: list[SceneRevisionPlanAction],
    ) -> str:
        if not actions:
            return "No scene repair is needed."
        action_types = self._unique_strings([action.action_type for action in actions])
        return self._sanitize_text(
            f"{len(actions)} scene revision planning action(s) generated; status={plan_status}; "
            f"next_step={recommended_next_step}; action_types={', '.join(action_types)}.",
            limit=1000,
        )

    def _plan_safe_user_summary(
        self,
        *,
        report: SceneGateAnalysisReport,
        actions: list[SceneRevisionPlanAction],
    ) -> str:
        if report.user_facing_status_summary:
            base = report.user_facing_status_summary
        elif not actions:
            base = "No blocking gate issue requires a scene revision plan."
        else:
            base = actions[0].safe_user_summary
        if actions:
            action_types = ", ".join(
                self._unique_strings([action.action_type for action in actions])[:3]
            )
            base = f"{base} Planned action category: {action_types}."
        return self._sanitize_text(base, limit=1000)

    def _stop_reason(self, actions: list[SceneRevisionPlanAction]) -> str:
        reasons = [
            action.stop_reason
            for action in actions
            if action.stop_reason
            and action.action_type in {"stop_for_user_confirmation", "stop_for_expert_review"}
        ]
        return self._sanitize_text("; ".join(self._unique_strings(reasons)), limit=1000)

    def _may_touch_user_content(self, group: SceneGateRootCauseGroup) -> bool:
        return bool(
            group.root_cause_layer in {"world_canvas", "user_intent_conflict"}
            or set(group.categories) & USER_CONTENT_TOUCH_CATEGORIES
            or set(group.user_action_options) & {"modify", "confirm_keep"}
        )

    def _action_signature(
        self,
        group: SceneGateRootCauseGroup,
        action_type: str,
    ) -> str:
        return self._stable_id(
            "scene_revision_action_signature",
            {
                "action_type": action_type,
                "target_repair_system": group.target_repair_system,
                "root_cause_layer": group.root_cause_layer,
                "source_group_ids": [group.group_id],
                "source_finding_signatures": group.finding_signatures,
            },
        )

    def _stable_id(self, prefix: str, payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        return f"{prefix}_{digest}"

    def _sanitize_text(self, value: str, *, limit: int) -> str:
        text = str(value or "").strip()
        for pattern in UNSAFE_TEXT_PATTERNS:
            text = pattern.sub("[redacted]", text)
        return text[:limit]

    def _unique_strings(self, values: list[Any]) -> list[str]:
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
