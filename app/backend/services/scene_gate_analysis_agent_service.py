from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.backend.models.scene_gate_repair import (
    GateFinding,
    GateRunReport,
    SCENE_GATE_ANALYSIS_SCHEMA_VERSION,
    SCENE_GATE_USER_ACTION_OPTION_ORDER,
    SceneGateAnalysisReport,
    SceneGateRootCauseGroup,
)
from app.backend.services.writer_gate_finding_bridge_service import (
    WRITER_GATE_HARD_LEAK_CATEGORIES,
    WRITER_GATE_REPAIRABLE_CATEGORIES,
)


SHANGHAI_TZ = timezone(timedelta(hours=8))
UNSAFE_TEXT_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_\-]+"),
    re.compile(r"\b(raw_prompt|raw_response|hidden_reasoning|chain[-_ ]of[-_ ]thought)\b", re.I),
]

MACHINE_ACTIONABLE_SYSTEMS = {
    "writer",
    "scene_information",
    "story_information_integrator",
    "character_intent",
    "memory_retrieval",
    "memory_extraction",
}

USER_CONFIRMATION_FIELDS = {
    "story_idea",
    "premise",
    "world_canvas",
    "character_goal",
    "identity",
    "hard_rules",
    "canon_fact",
}

USER_CONFIRMATION_CATEGORIES = {
    "complete_prior_story",
    "world_hard_rule_direct_conflict",
    "forbidden_knowledge",
}

PROVIDER_CATEGORIES = {"provider_degraded", "provider_fallback", "provider_http_error"}
RUNTIME_EVIDENCE_CATEGORIES = {
    "continuity_check_evidence_missing",
    "continuity_run_evidence_missing",
    "runtime_evidence_stale",
    "runtime_refresh_not_allowed",
    "runtime_confirm_not_allowed",
    "composite_current_scene_mismatch",
    "composite_runtime_scope_mismatch",
}
WRITER_CATEGORIES = {
    "demo_default_leak",
    "scene_repetition_too_high",
    "scene_progression_missing",
    "prose_generation_failure",
    "story_information_coverage",
    "do_not_include_violation",
    "scene_pattern_similarity_warning",
    "scene_pattern_similarity_too_high",
} | WRITER_GATE_REPAIRABLE_CATEGORIES
SCENE_INFORMATION_CATEGORIES = {
    "scene_progression_statement_missing",
    "scene_objective_repeated",
    "chapter_goal_drift",
}
STORY_INFORMATION_CATEGORIES = {
    "scene_previous_summary_missing",
    "prompt_fidelity_missing",
    "prompt_fidelity_weak",
}
CHARACTER_INTENT_CATEGORIES = {"character_uniqueness_violation"}
MEMORY_PACK_CATEGORIES = {"missing_source_fact", "no_source_fact", "unverified_old_event"}
MEMORY_EXTRACTION_CATEGORIES = {
    "mark_as_subjective_claim",
    "subjective_claim_conversion",
    "canon_status_change",
}
MEMORY_EXTRACTION_REPAIRABLE_CATEGORIES = {
    "memory extraction integrity",
    "memory_extraction_integrity",
    "memory_extraction_completeness",
}
ABCD_RUNTIME_PARTICIPATION_CATEGORIES = {
    "abcd_runtime_blocking_issue",
    "abcd_runtime_failed",
    "abcd_runtime_stale",
    "abcd_runtime_missing_participation",
}
ABCD_RUNTIME_USER_CONFIRMATION_CATEGORIES = {"abcd_runtime_requires_user_confirmation"}
ABCD_RUNTIME_EXPERT_REVIEW_CATEGORIES = {"abcd_runtime_policy_violation"}
AUTO_REPAIR_ALLOWED_RUNTIME_BLOCKING_REASONS = {
    "quality_requires_user_confirmation",
    "quality_blocking_issues",
    "continuity_blocking_issues",
    "quality_or_continuity_not_passed",
    "scene_gate_pipeline_blocked",
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


class SceneGateAnalysisAgentService:
    """Deterministic, rule-first analyzer over GateRunReport.

    This service is intentionally pure: no storage writes, no provider calls, and no
    repair execution. M4 consumes this output to decide whether a revision plan can
    be safely considered.
    """

    def analyze_gate_run_report(
        self,
        gate_run_report: GateRunReport | dict[str, Any],
        *,
        previous_analysis_reports: list[SceneGateAnalysisReport | dict[str, Any]] | None = None,
    ) -> SceneGateAnalysisReport:
        gate_run = self._coerce_gate_run(gate_run_report)
        previous_reports = [
            self._coerce_analysis_report(report)
            for report in previous_analysis_reports or []
        ]
        previous_signatures = self._previous_finding_signatures(previous_reports)

        prioritized_findings = sorted(gate_run.findings, key=self._finding_sort_key)
        repeated_signatures = self._unique_strings(
            [
                finding.finding_signature
                for finding in prioritized_findings
                if finding.finding_signature in previous_signatures
            ]
        )
        groups = self._build_groups(prioritized_findings)
        repeated_stop_signatures = self._repeated_signatures_requiring_stop(
            findings=prioritized_findings,
            repeated_signatures=repeated_signatures,
        )
        repeated_blocking_or_confirmation = bool(repeated_stop_signatures)

        blocking_finding_ids = [
            finding.finding_id
            for finding in prioritized_findings
            if finding.blocks_final_output or finding.severity == "blocking"
        ]
        confirmation_required_finding_ids = [
            finding.finding_id
            for finding in prioritized_findings
            if finding.requires_user_confirmation
            or finding.severity == "requires_user_confirmation"
        ]
        degraded_finding_ids = [
            finding.finding_id
            for finding in prioritized_findings
            if finding.severity == "degraded"
        ]
        user_confirmation_reasons = self._user_confirmation_reasons(groups)
        requires_user_confirmation = bool(
            confirmation_required_finding_ids or user_confirmation_reasons
        )

        auto_repair_allowed, auto_repair_blocking_reasons = self._auto_repair_decision(
            gate_run=gate_run,
            groups=groups,
            requires_user_confirmation=requires_user_confirmation,
            repeated_stop_signatures=repeated_stop_signatures,
        )
        recommended_next_action, recommended_stop_reason = self._recommended_report_action(
            groups=groups,
            findings=prioritized_findings,
            repeated_blocking_or_confirmation=repeated_blocking_or_confirmation,
            auto_repair_allowed=auto_repair_allowed,
        )
        risk_level = self._report_risk_level(groups, prioritized_findings)
        priority_basis = self._priority_basis(groups, prioritized_findings)
        user_intent_notes = self._user_intent_preservation_notes(groups)
        source_refs = self._unique_strings(
            [
                *gate_run.source_refs,
                *[
                    f"gate_finding:{finding.finding_id}"
                    for finding in prioritized_findings
                ],
            ]
        )
        analysis_id = self._analysis_id(
            gate_run=gate_run,
            groups=groups,
            repeated_signatures=repeated_signatures,
            recommended_next_action=recommended_next_action,
        )
        user_visibility = self._report_user_visibility(groups)

        return SceneGateAnalysisReport(
            schema_version=SCENE_GATE_ANALYSIS_SCHEMA_VERSION,
            analysis_id=analysis_id,
            gate_run_id=gate_run.gate_run_id,
            project_id=gate_run.project_id,
            chapter_id=gate_run.chapter_id,
            scene_id=gate_run.scene_id,
            candidate_id=gate_run.candidate_id,
            revision_id=gate_run.revision_id,
            round_index=gate_run.round_index,
            generated_at=now_iso(),
            root_cause_groups=groups,
            merged_finding_ids=[finding.finding_id for finding in prioritized_findings],
            prioritized_finding_ids=[finding.finding_id for finding in prioritized_findings],
            blocking_finding_ids=blocking_finding_ids,
            confirmation_required_finding_ids=confirmation_required_finding_ids,
            degraded_finding_ids=degraded_finding_ids,
            auto_repair_allowed=auto_repair_allowed,
            auto_repair_blocking_reasons=auto_repair_blocking_reasons,
            requires_user_confirmation=requires_user_confirmation,
            user_confirmation_reasons=user_confirmation_reasons,
            risk_level=risk_level,
            analysis_summary=self._analysis_summary(
                groups=groups,
                recommended_next_action=recommended_next_action,
            ),
            priority_basis=priority_basis,
            user_intent_preservation_notes=user_intent_notes,
            auto_repair_confidence="medium" if auto_repair_allowed else "none",
            same_issue_repeated=bool(repeated_signatures),
            repeated_finding_signatures=repeated_signatures,
            new_blocking_risk=bool(blocking_finding_ids) and not repeated_signatures,
            recommended_next_action=recommended_next_action,
            recommended_stop_reason=recommended_stop_reason,
            source_refs=source_refs,
            user_visible_required=user_visibility["user_visible_required"],
            user_action_required=user_visibility["user_action_required"],
            user_visible_group_ids=user_visibility["user_visible_group_ids"],
            user_action_required_group_ids=user_visibility["user_action_required_group_ids"],
            user_action_options=user_visibility["user_action_options"],
            user_facing_status_summary=user_visibility["user_facing_status_summary"],
        )

    def _coerce_gate_run(self, value: GateRunReport | dict[str, Any]) -> GateRunReport:
        if isinstance(value, GateRunReport):
            return value
        return GateRunReport(**model_to_dict(value))

    def _coerce_analysis_report(
        self,
        value: SceneGateAnalysisReport | dict[str, Any],
    ) -> SceneGateAnalysisReport:
        if isinstance(value, SceneGateAnalysisReport):
            return value
        return SceneGateAnalysisReport(**model_to_dict(value))

    def _build_groups(self, findings: list[GateFinding]) -> list[SceneGateRootCauseGroup]:
        grouped: dict[tuple[str, str], list[GateFinding]] = {}
        for finding in findings:
            layer, target = self._classify_finding(finding)
            grouped.setdefault((layer, target), []).append(finding)

        groups = [
            self._group_from_findings(layer, target, sorted(items, key=self._finding_sort_key))
            for (layer, target), items in grouped.items()
        ]
        return sorted(groups, key=lambda group: (group.priority, group.group_signature))

    def _group_from_findings(
        self,
        layer: str,
        target: str,
        findings: list[GateFinding],
    ) -> SceneGateRootCauseGroup:
        categories = self._unique_strings([finding.category for finding in findings])
        gate_types = self._unique_strings([finding.gate_type for finding in findings])
        severities = self._unique_strings([finding.severity for finding in findings])
        affected_fields = self._unique_strings(
            [field for finding in findings for field in finding.affected_fields]
        )
        suggested_repair_types = self._unique_strings(
            [item for finding in findings for item in finding.suggested_repair_types]
        )
        evidence_refs = self._unique_strings(
            [ref for finding in findings for ref in finding.evidence_refs]
        )
        finding_ids = self._unique_strings([finding.finding_id for finding in findings])
        finding_signatures = self._unique_strings(
            [finding.finding_signature for finding in findings]
        )
        priority = min(self._finding_priority(finding) for finding in findings) if findings else 100
        blocks_final_output = any(
            finding.blocks_final_output or finding.severity == "blocking"
            for finding in findings
        )
        blocks_auto_repair = any(finding.blocks_auto_repair for finding in findings)
        requires_user_confirmation = any(
            finding.requires_user_confirmation
            or finding.severity == "requires_user_confirmation"
            for finding in findings
        ) or self._requires_user_confirmation(categories, affected_fields, suggested_repair_types)
        risk_level = self._group_risk_level(
            layer=layer,
            categories=categories,
            severities=severities,
            blocks_final_output=blocks_final_output,
            requires_user_confirmation=requires_user_confirmation,
        )
        recommended_next_action = self._group_next_action(
            layer=layer,
            target=target,
            categories=categories,
            requires_user_confirmation=requires_user_confirmation,
        )
        user_visible_required = self._group_user_visible_required(
            blocks_final_output=blocks_final_output,
            severities=severities,
            requires_user_confirmation=requires_user_confirmation,
            recommended_next_action=recommended_next_action,
        )
        user_action_required = self._group_user_action_required(
            layer=layer,
            target=target,
            categories=categories,
            blocks_final_output=blocks_final_output,
            requires_user_confirmation=requires_user_confirmation,
            recommended_next_action=recommended_next_action,
        )
        user_action_options = self._group_user_action_options(
            layer=layer,
            target=target,
            categories=categories,
            affected_fields=affected_fields,
            suggested_repair_types=suggested_repair_types,
        )
        user_action_reason = self._group_user_action_reason(
            layer=layer,
            target=target,
            categories=categories,
            user_action_required=user_action_required,
            recommended_next_action=recommended_next_action,
        )
        user_facing_safe_summary = self._group_user_facing_summary(
            layer=layer,
            target=target,
            categories=categories,
            affected_fields=affected_fields,
            user_visible_required=user_visible_required,
            user_action_required=user_action_required,
            user_action_options=user_action_options,
            reason=user_action_reason,
        )
        group_signature = self._stable_id(
            "scene_gate_group",
            {
                "layer": layer,
                "target": target,
                "finding_signatures": finding_signatures,
                "categories": categories,
                "affected_fields": affected_fields,
            },
        )
        return SceneGateRootCauseGroup(
            group_id=f"group_{group_signature[-16:]}",
            group_signature=group_signature,
            root_cause_layer=layer,
            target_repair_system=target,
            finding_ids=finding_ids,
            finding_signatures=finding_signatures,
            gate_types=gate_types,
            categories=categories,
            severities=severities,
            affected_fields=affected_fields,
            suggested_repair_types=suggested_repair_types,
            evidence_refs=evidence_refs,
            priority=priority,
            risk_level=risk_level,
            blocks_final_output=blocks_final_output,
            blocks_auto_repair=blocks_auto_repair,
            requires_user_confirmation=requires_user_confirmation,
            safe_summary=self._group_summary(layer, target, findings),
            priority_basis=self._group_priority_basis(layer, target, findings),
            recommended_next_action=recommended_next_action,
            recommended_stop_reason=self._group_stop_reason(
                recommended_next_action,
                categories=categories,
                layer=layer,
            ),
            user_visible_required=user_visible_required,
            user_action_required=user_action_required,
            user_action_options=user_action_options,
            user_facing_safe_summary=user_facing_safe_summary,
            user_action_reason=user_action_reason,
        )

    def _classify_finding(self, finding: GateFinding) -> tuple[str, str]:
        category = finding.category
        affected_fields = {field.casefold() for field in finding.affected_fields}
        suggested = {item.casefold() for item in finding.suggested_repair_types}
        if category in PROVIDER_CATEGORIES or finding.gate_type == "provider":
            return "provider_degraded", "provider_retry"
        if category in RUNTIME_EVIDENCE_CATEGORIES or finding.gate_type in {
            "runtime_refresh",
            "composite_runtime",
        }:
            return "runtime_evidence", "runtime_refresh"
        if category in ABCD_RUNTIME_USER_CONFIRMATION_CATEGORIES:
            if not finding.requires_user_confirmation and finding.severity != "requires_user_confirmation":
                return "character_intent", "character_intent"
            return "user_intent_conflict", "user_confirmation"
        if category in ABCD_RUNTIME_EXPERT_REVIEW_CATEGORIES:
            return "unknown", "expert_review"
        if category in ABCD_RUNTIME_PARTICIPATION_CATEGORIES or (
            finding.gate_type == "abcd_runtime"
            and ("participation" in category or "participant" in category)
        ):
            return "scene_participation", "scene_participation"
        if category in WRITER_GATE_HARD_LEAK_CATEGORIES:
            return "writer_prose_output", "expert_review"
        if category in WRITER_CATEGORIES:
            return "writer_prose_output", "writer"
        if category in SCENE_INFORMATION_CATEGORIES:
            return "scene_information", "scene_information"
        if category in STORY_INFORMATION_CATEGORIES:
            return "ordered_story_information_package", "story_information_integrator"
        if category in CHARACTER_INTENT_CATEGORIES:
            return "character_intent", "character_intent"
        if category in MEMORY_PACK_CATEGORIES:
            return "memory_pack", "memory_retrieval"
        if category == "world_hard_rule_direct_conflict":
            return "world_canvas", "user_confirmation"
        if category == "forbidden_knowledge":
            return "memory_pack", "user_confirmation"
        if category.casefold() in MEMORY_EXTRACTION_REPAIRABLE_CATEGORIES:
            return "memory_extraction_candidate", "memory_extraction"
        if (
            category in MEMORY_EXTRACTION_CATEGORIES
            or "mark_as_subjective_claim" in suggested
            or "canon_fact" in affected_fields
        ):
            return "memory_extraction_candidate", "user_confirmation"
        if category in USER_CONFIRMATION_CATEGORIES or "complete_prior_story" in suggested:
            return "memory_pack", "user_confirmation"
        if affected_fields & USER_CONFIRMATION_FIELDS:
            return "user_intent_conflict", "user_confirmation"
        if finding.root_cause_layer == "runtime_evidence":
            return "runtime_evidence", "runtime_refresh"
        return "unknown", "expert_review"

    def _finding_priority(self, finding: GateFinding) -> int:
        category = finding.category
        if finding.gate_type == "provider" or category in PROVIDER_CATEGORIES:
            return 10
        if category in {
            "continuity_check_evidence_missing",
            "continuity_run_evidence_missing",
            "runtime_evidence_stale",
        }:
            return 20
        if finding.requires_user_confirmation or finding.severity == "requires_user_confirmation":
            return 30
        if category in {"world_hard_rule_direct_conflict", "forbidden_knowledge"}:
            return 40
        if finding.gate_type in {"runtime_refresh", "composite_runtime", "abcd_runtime"}:
            return 50
        if finding.gate_type == "continuity" and (
            finding.severity == "blocking" or finding.blocks_final_output
        ):
            return 60
        if finding.gate_type == "quality" and (
            finding.severity == "blocking" or finding.blocks_final_output
        ):
            return 70
        if finding.severity == "degraded":
            return 75
        return 80

    def _finding_sort_key(self, finding: GateFinding) -> tuple[int, str, str, str, str, str]:
        return (
            self._finding_priority(finding),
            finding.gate_type,
            finding.category,
            finding.target_type,
            finding.target_id,
            finding.finding_signature,
        )

    def _group_next_action(
        self,
        *,
        layer: str,
        target: str,
        categories: list[str],
        requires_user_confirmation: bool,
    ) -> str:
        if layer == "provider_degraded":
            return "retry_provider_or_stop"
        if layer == "runtime_evidence" or target in {"runtime_refresh", "continuity_gate"}:
            return "refresh_runtime_or_gate_evidence"
        if requires_user_confirmation or target == "user_confirmation":
            return "stop_for_user_confirmation"
        if target == "expert_review" or layer == "unknown":
            return "stop_for_expert_review"
        if layer == "world_canvas":
            return "stop_for_user_confirmation"
        if target in MACHINE_ACTIONABLE_SYSTEMS:
            return "proceed_to_revision_plan"
        return "blocked_unsafe_for_auto_repair" if categories else "no_repair_needed"

    def _group_user_visible_required(
        self,
        *,
        blocks_final_output: bool,
        severities: list[str],
        requires_user_confirmation: bool,
        recommended_next_action: str,
    ) -> bool:
        return bool(
            blocks_final_output
            or "blocking" in severities
            or requires_user_confirmation
            or recommended_next_action
            in {
                "stop_for_user_confirmation",
                "stop_for_expert_review",
                "blocked_unsafe_for_auto_repair",
            }
        )

    def _group_user_action_required(
        self,
        *,
        layer: str,
        target: str,
        categories: list[str],
        blocks_final_output: bool,
        requires_user_confirmation: bool,
        recommended_next_action: str,
    ) -> bool:
        lowered_categories = {category.casefold() for category in categories}
        if requires_user_confirmation:
            return True
        if blocks_final_output and lowered_categories & {
            "missing_source_fact",
            "no_source_fact",
            "scene_previous_summary_missing",
            "complete_prior_story",
        }:
            return True
        if recommended_next_action in {
            "stop_for_user_confirmation",
            "stop_for_expert_review",
            "blocked_unsafe_for_auto_repair",
        } and (
            blocks_final_output
            or requires_user_confirmation
            or "blocking" in lowered_categories
            or target == "user_confirmation"
        ):
            return True
        return bool(
            blocks_final_output
            and layer in {"world_canvas", "user_intent_conflict", "unknown"}
            and target in {"user_confirmation", "expert_review"}
        )

    def _group_user_action_options(
        self,
        *,
        layer: str,
        target: str,
        categories: list[str],
        affected_fields: list[str],
        suggested_repair_types: list[str],
    ) -> list[str]:
        options: list[str] = []
        base_mapping: dict[tuple[str, str], list[str]] = {
            ("writer_prose_output", "writer"): ["modify"],
            ("scene_information", "scene_information"): ["modify"],
            ("ordered_story_information_package", "story_information_integrator"): [
                "modify",
                "complete",
            ],
            ("memory_pack", "memory_retrieval"): ["complete"],
            ("memory_pack", "user_confirmation"): ["complete", "confirm_keep"],
            ("memory_extraction_candidate", "user_confirmation"): ["confirm_keep"],
            ("world_canvas", "user_confirmation"): ["modify", "confirm_keep"],
            ("world_canvas", "expert_review"): ["expert_review"],
            ("user_intent_conflict", "user_confirmation"): ["modify", "confirm_keep"],
            ("scene_participation", "scene_participation"): ["modify", "delete"],
            ("character_intent", "character_intent"): ["modify"],
            ("provider_degraded", "provider_retry"): ["expert_review"],
            ("unknown", "expert_review"): ["expert_review"],
        }
        options.extend(base_mapping.get((layer, target), []))
        if layer == "runtime_evidence" and target == "runtime_refresh":
            lowered_categories = {category.casefold() for category in categories}
            if lowered_categories & {
                "runtime_refresh_not_allowed",
                "runtime_confirm_not_allowed",
                "runtime_evidence_stale",
            }:
                options.append("expert_review")

        lowered_categories = {category.casefold() for category in categories}
        lowered_fields = {field.casefold() for field in affected_fields}
        lowered_suggested = {item.casefold() for item in suggested_repair_types}
        if lowered_categories & {
            "missing_source_fact",
            "no_source_fact",
            "scene_previous_summary_missing",
        }:
            options.append("complete")
        if lowered_categories & {"prompt_fidelity_missing", "prompt_fidelity_weak"}:
            options.extend(["modify", "complete"])
        if lowered_categories & {"scene_repetition_too_high", "scene_progression_missing"}:
            options.append("modify")
        if "world_hard_rule_direct_conflict" in lowered_categories:
            options.extend(["modify", "expert_review"])
        if "forbidden_knowledge" in lowered_categories:
            options.extend(["delete", "expert_review"])
        if "complete_prior_story" in lowered_categories or "complete_prior_story" in lowered_suggested:
            options.extend(["complete", "confirm_keep"])
        if lowered_categories & {"mark_as_subjective_claim", "subjective_claim_conversion"} or (
            "mark_as_subjective_claim" in lowered_suggested
        ):
            options.append("confirm_keep")
        if "abcd_runtime_requires_user_confirmation" in lowered_categories:
            options.extend(["modify", "confirm_keep"])
        if "abcd_runtime_policy_violation" in lowered_categories:
            options.append("expert_review")
        stale_or_invalid_reference = any(
            ("stale" in category or "invalid" in category)
            and (
                "role" in category
                or "scene" in category
                or "reference" in category
                or "ref" in category
            )
            for category in lowered_categories
        ) or any(
            ("stale" in field or "invalid" in field)
            and (
                "role" in field
                or "scene" in field
                or "reference" in field
                or "ref" in field
            )
            for field in lowered_fields
        )
        if stale_or_invalid_reference:
            options.extend(["modify", "delete"])
        return self._ordered_user_action_options(options)

    def _group_user_action_reason(
        self,
        *,
        layer: str,
        target: str,
        categories: list[str],
        user_action_required: bool,
        recommended_next_action: str,
    ) -> str:
        if not user_action_required:
            if recommended_next_action == "proceed_to_revision_plan":
                return "machine_repair_path_available"
            return ""
        if target == "user_confirmation":
            return "user_confirmation_required_before_safe_progress"
        if target == "expert_review":
            return "expert_review_required_before_safe_progress"
        if recommended_next_action == "blocked_unsafe_for_auto_repair":
            return "automatic_repair_is_not_safe_for_this_gate_finding"
        category_text = ",".join(categories) or layer
        return f"user_action_required_for:{category_text}"

    def _group_user_facing_summary(
        self,
        *,
        layer: str,
        target: str,
        categories: list[str],
        affected_fields: list[str],
        user_visible_required: bool,
        user_action_required: bool,
        user_action_options: list[str],
        reason: str,
    ) -> str:
        if not user_visible_required:
            return ""
        area = self._friendly_area(layer, target)
        category_text = ", ".join(categories[:3]) or "gate finding"
        field_text = ""
        safe_fields = self._unique_strings(affected_fields)[:3]
        if safe_fields:
            field_text = f" Affected area: {', '.join(safe_fields)}."
        options_text = self._format_user_action_options(user_action_options)
        if user_action_required:
            action_sentence = (
                f"The system cannot safely auto-repair it because {reason or 'manual confirmation is required'}."
            )
        else:
            action_sentence = (
                "The automated repair path may try to address it, but the issue must remain visible until it is cleared."
            )
        summary = (
            f"The current scene is blocked or at risk because {area} reported {category_text}."
            f"{field_text} {action_sentence}"
        )
        if options_text:
            summary = f"{summary} Suggested user options: {options_text}."
        return self._sanitize_text(summary, limit=500)

    def _report_user_visibility(
        self,
        groups: list[SceneGateRootCauseGroup],
    ) -> dict[str, Any]:
        visible_groups = [group for group in groups if group.user_visible_required]
        action_groups = [group for group in groups if group.user_action_required]
        options = self._ordered_user_action_options(
            [option for group in visible_groups for option in group.user_action_options]
        )
        return {
            "user_visible_required": bool(visible_groups),
            "user_action_required": bool(action_groups),
            "user_visible_group_ids": [group.group_id for group in visible_groups],
            "user_action_required_group_ids": [group.group_id for group in action_groups],
            "user_action_options": options,
            "user_facing_status_summary": self._report_user_facing_status_summary(
                visible_groups=visible_groups,
                action_groups=action_groups,
                options=options,
            ),
        }

    def _report_user_facing_status_summary(
        self,
        *,
        visible_groups: list[SceneGateRootCauseGroup],
        action_groups: list[SceneGateRootCauseGroup],
        options: list[str],
    ) -> str:
        if not visible_groups:
            return ""
        first = visible_groups[0]
        count = len(visible_groups)
        action_count = len(action_groups)
        area = self._friendly_area(first.root_cause_layer, first.target_repair_system)
        option_text = self._format_user_action_options(options)
        if action_count:
            summary = (
                f"{action_count} blocking gate issue(s) require user action before the scene can be approved. "
                f"The highest-priority issue affects {area}."
            )
        else:
            summary = (
                f"{count} blocking gate issue(s) must remain visible while automated repair is considered. "
                f"The highest-priority issue affects {area}."
            )
        if option_text:
            summary = f"{summary} Available options: {option_text}."
        if count > 1:
            summary = f"{summary} {count - 1} additional visible issue group(s) exist."
        return self._sanitize_text(summary, limit=800)

    def _ordered_user_action_options(self, options: list[str]) -> list[str]:
        normalized = {str(option or "").strip() for option in options}
        return [
            option
            for option in SCENE_GATE_USER_ACTION_OPTION_ORDER
            if option in normalized
        ]

    def _format_user_action_options(self, options: list[str]) -> str:
        return ", ".join(self._ordered_user_action_options(options))

    def _friendly_area(self, layer: str, target: str) -> str:
        labels = {
            "writer_prose_output": "scene prose",
            "scene_information": "scene information",
            "ordered_story_information_package": "story information",
            "character_intent": "character intent",
            "scene_participation": "scene participation",
            "memory_pack": "memory context",
            "memory_extraction_candidate": "memory extraction",
            "chapter_framework": "chapter framework",
            "world_canvas": "world rules",
            "runtime_evidence": "runtime evidence",
            "provider_degraded": "model provider availability",
            "user_intent_conflict": "user intent",
            "unknown": "expert review",
        }
        return labels.get(layer) or labels.get(target) or "the current scene"

    def _recommended_report_action(
        self,
        *,
        groups: list[SceneGateRootCauseGroup],
        findings: list[GateFinding],
        repeated_blocking_or_confirmation: bool,
        auto_repair_allowed: bool,
    ) -> tuple[str, str]:
        if not findings:
            return "no_repair_needed", ""
        if repeated_blocking_or_confirmation:
            return "stop_for_expert_review", "blocking_or_confirmation_signature_repeated"
        for action in [
            "retry_provider_or_stop",
            "stop_for_expert_review",
            "stop_for_user_confirmation",
        ]:
            if any(
                group.recommended_next_action == action
                and self._group_requires_immediate_stop(group)
                for group in groups
            ):
                return action, self._report_stop_reason(action, groups)
        if auto_repair_allowed or any(
            group.recommended_next_action == "proceed_to_revision_plan"
            for group in groups
        ):
            return "proceed_to_revision_plan", ""
        if any(
            group.recommended_next_action == "refresh_runtime_or_gate_evidence"
            for group in groups
        ):
            return "refresh_runtime_or_gate_evidence", self._report_stop_reason(
                "refresh_runtime_or_gate_evidence",
                groups,
            )
        return "blocked_unsafe_for_auto_repair", "auto_repair_safety_contract_not_met"

    def _auto_repair_decision(
        self,
        *,
        gate_run: GateRunReport,
        groups: list[SceneGateRootCauseGroup],
        requires_user_confirmation: bool,
        repeated_stop_signatures: list[str],
    ) -> tuple[bool, list[str]]:
        if not groups:
            return False, []
        reasons: list[str] = []
        if not gate_run.safe_for_auto_repair_loop:
            reasons.append("gate_run_not_safe_for_auto_repair_loop")
        if gate_run.provider_degraded:
            reasons.append("provider_degraded")
        if not (
            gate_run.continuity_checked
            and gate_run.continuity_gate_run_id
            and gate_run.continuity_checked_at
        ):
            reasons.append("continuity_evidence_missing")
        if not gate_run.runtime_refresh_checked or self._runtime_blocks_auto_repair(gate_run):
            reasons.append("runtime_not_confirmable")
        if requires_user_confirmation:
            reasons.append("user_confirmation_required")
        unsafe_layers = {
            group.root_cause_layer
            for group in groups
            if self._group_requires_immediate_stop(group)
            and group.root_cause_layer
            in {
                "world_canvas",
                "provider_degraded",
                "user_intent_conflict",
                "unknown",
            }
        }
        reasons.extend([f"unsafe_root_cause_layer:{layer}" for layer in sorted(unsafe_layers)])
        if repeated_stop_signatures:
            reasons.append("repeated_finding_signature")
        if not any(group.target_repair_system in MACHINE_ACTIONABLE_SYSTEMS for group in groups):
            reasons.append("no_machine_actionable_group")
        return not reasons and bool(groups), self._unique_strings(reasons)

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

    def _repeated_signatures_requiring_stop(
        self,
        *,
        findings: list[GateFinding],
        repeated_signatures: list[str],
    ) -> list[str]:
        repeated = set(repeated_signatures)
        if not repeated:
            return []
        stop_signatures: list[str] = []
        for finding in findings:
            if finding.finding_signature not in repeated:
                continue
            if not (
                finding.blocks_final_output
                or finding.severity == "blocking"
                or finding.requires_user_confirmation
                or finding.severity == "requires_user_confirmation"
            ):
                continue
            if self._repeated_finding_can_continue_auto_repair(finding):
                continue
            stop_signatures.append(finding.finding_signature)
        return self._unique_strings(stop_signatures)

    def _repeated_finding_can_continue_auto_repair(self, finding: GateFinding) -> bool:
        if finding.requires_user_confirmation or finding.severity == "requires_user_confirmation":
            return False
        if finding.blocks_auto_repair:
            return False
        if finding.category in WRITER_GATE_HARD_LEAK_CATEGORIES:
            return False
        layer, target = self._classify_finding(finding)
        return (
            layer == "writer_prose_output"
            and target == "writer"
            and finding.category in WRITER_CATEGORIES
        )

    def _runtime_blocks_auto_repair(self, gate_run: GateRunReport) -> bool:
        if gate_run.runtime_confirm_allowed is True:
            return False
        if gate_run.safe_for_auto_repair_loop:
            return False
        quality_or_continuity_release_blocker = any(
            finding.gate_type in {"quality", "continuity"} and finding.blocks_final_output
            for finding in gate_run.findings
        )
        runtime_auto_blocker = any(
            finding.gate_type == "runtime_refresh" and finding.blocks_auto_repair
            for finding in gate_run.findings
        )
        if quality_or_continuity_release_blocker and not runtime_auto_blocker:
            return False
        normalized = {
            str(reason or "").strip().casefold()
            for reason in gate_run.runtime_blocking_reasons
            if str(reason or "").strip()
        }
        if not normalized:
            return gate_run.runtime_confirm_allowed is False
        return not normalized.issubset(AUTO_REPAIR_ALLOWED_RUNTIME_BLOCKING_REASONS)

    def _requires_user_confirmation(
        self,
        categories: list[str],
        affected_fields: list[str],
        suggested_repair_types: list[str],
    ) -> bool:
        normalized_fields = {field.casefold() for field in affected_fields}
        normalized_suggested = {item.casefold() for item in suggested_repair_types}
        return bool(
            set(categories) & USER_CONFIRMATION_CATEGORIES
            or set(categories) & MEMORY_EXTRACTION_CATEGORIES
            or (
                set(categories) & ABCD_RUNTIME_USER_CONFIRMATION_CATEGORIES
                and "request_user_confirmation" in normalized_suggested
            )
            or normalized_fields & USER_CONFIRMATION_FIELDS
            or "complete_prior_story" in normalized_suggested
            or "mark_as_subjective_claim" in normalized_suggested
        )

    def _user_confirmation_reasons(
        self,
        groups: list[SceneGateRootCauseGroup],
    ) -> list[str]:
        reasons: list[str] = []
        for group in groups:
            if group.requires_user_confirmation:
                reasons.append(f"group_requires_user_confirmation:{group.group_id}")
            if group.target_repair_system == "user_confirmation":
                reasons.append(f"user_confirmation_target:{group.group_id}")
        return self._unique_strings(reasons)

    def _user_intent_preservation_notes(
        self,
        groups: list[SceneGateRootCauseGroup],
    ) -> list[str]:
        if not groups:
            return ["No gate findings require user intent changes."]
        notes: list[str] = []
        for group in groups:
            fields = {field.casefold() for field in group.affected_fields}
            if (
                group.requires_user_confirmation
                or fields & USER_CONFIRMATION_FIELDS
                or group.root_cause_layer in {"world_canvas", "user_intent_conflict"}
            ):
                notes.append(
                    f"{group.group_id}: user confirmation or expert review is required before changing user intent or canon status."
                )
            elif group.root_cause_layer in {
                "writer_prose_output",
                "scene_information",
                "ordered_story_information_package",
            }:
                notes.append(
                    f"{group.group_id}: later M4 planning can target delivery while preserving the confirmed premise and user intent."
                )
            else:
                notes.append(
                    f"{group.group_id}: analysis only; no user intent mutation is authorized in M3."
                )
        return self._unique_strings(notes)

    def _group_risk_level(
        self,
        *,
        layer: str,
        categories: list[str],
        severities: list[str],
        blocks_final_output: bool,
        requires_user_confirmation: bool,
    ) -> str:
        if layer == "provider_degraded":
            return "critical"
        if layer in {"world_canvas", "unknown"}:
            return "high"
        if categories and set(categories) & {"world_hard_rule_direct_conflict", "forbidden_knowledge"}:
            return "high"
        if blocks_final_output or "blocking" in severities:
            return "high"
        if requires_user_confirmation:
            return "medium"
        if "degraded" in severities:
            return "medium"
        return "low"

    def _report_risk_level(
        self,
        groups: list[SceneGateRootCauseGroup],
        findings: list[GateFinding],
    ) -> str:
        if not findings:
            return "none"
        order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        return max([group.risk_level for group in groups] or ["none"], key=lambda item: order[item])

    def _group_priority_basis(
        self,
        layer: str,
        target: str,
        findings: list[GateFinding],
    ) -> list[str]:
        basis = [f"root_cause_layer:{layer}", f"target_repair_system:{target}"]
        if any(finding.blocks_final_output for finding in findings):
            basis.append("blocks_final_output")
        if any(finding.requires_user_confirmation for finding in findings):
            basis.append("requires_user_confirmation")
        if any(finding.severity == "degraded" for finding in findings):
            basis.append("provider_or_runtime_degraded")
        return self._unique_strings(basis)

    def _priority_basis(
        self,
        groups: list[SceneGateRootCauseGroup],
        findings: list[GateFinding],
    ) -> list[str]:
        if not findings:
            return ["no_findings"]
        basis = [f"{group.group_id}:{group.priority}" for group in groups]
        if any(finding.blocks_final_output for finding in findings):
            basis.append("has_final_output_blocker")
        if any(finding.requires_user_confirmation for finding in findings):
            basis.append("has_user_confirmation_requirement")
        return self._unique_strings(basis)

    def _group_summary(
        self,
        layer: str,
        target: str,
        findings: list[GateFinding],
    ) -> str:
        categories = ", ".join(self._unique_strings([finding.category for finding in findings]))
        excerpt = next(
            (
                self._sanitize_text(finding.safe_source_excerpt, limit=220)
                for finding in findings
                if finding.safe_source_excerpt
            ),
            "",
        )
        summary = f"{layer} routed to {target}; categories={categories or 'none'}."
        if excerpt:
            summary = f"{summary} Evidence: {excerpt}"
        return self._sanitize_text(summary, limit=500)

    def _group_stop_reason(
        self,
        action: str,
        *,
        categories: list[str],
        layer: str,
    ) -> str:
        if action == "stop_for_user_confirmation":
            return f"user_confirmation_required_for:{','.join(categories) or layer}"
        if action == "stop_for_expert_review":
            return f"expert_review_required_for:{','.join(categories) or layer}"
        if action == "retry_provider_or_stop":
            return "provider_degraded_or_unavailable"
        if action == "refresh_runtime_or_gate_evidence":
            return "runtime_or_gate_evidence_not_ready"
        return ""

    def _report_stop_reason(
        self,
        action: str,
        groups: list[SceneGateRootCauseGroup],
    ) -> str:
        reasons = [
            group.recommended_stop_reason
            for group in groups
            if group.recommended_next_action == action and group.recommended_stop_reason
        ]
        return "; ".join(self._unique_strings(reasons))[:800]

    def _analysis_summary(
        self,
        *,
        groups: list[SceneGateRootCauseGroup],
        recommended_next_action: str,
    ) -> str:
        if not groups:
            return "No gate findings require repair analysis."
        categories = self._unique_strings(
            [category for group in groups for category in group.categories]
        )
        return self._sanitize_text(
            f"{len(groups)} root-cause group(s) found; next_action={recommended_next_action}; categories={', '.join(categories)}.",
            limit=800,
        )

    def _previous_finding_signatures(
        self,
        previous_reports: list[SceneGateAnalysisReport],
    ) -> set[str]:
        signatures: set[str] = set()
        for report in previous_reports:
            signatures.update(report.repeated_finding_signatures)
            for group in report.root_cause_groups:
                signatures.update(group.finding_signatures)
        return signatures

    def _analysis_id(
        self,
        *,
        gate_run: GateRunReport,
        groups: list[SceneGateRootCauseGroup],
        repeated_signatures: list[str],
        recommended_next_action: str,
    ) -> str:
        return self._stable_id(
            "scene_gate_analysis",
            {
                "gate_run_id": gate_run.gate_run_id,
                "project_id": gate_run.project_id,
                "chapter_id": gate_run.chapter_id,
                "scene_id": gate_run.scene_id,
                "candidate_id": gate_run.candidate_id,
                "revision_id": gate_run.revision_id,
                "round_index": gate_run.round_index,
                "group_signatures": [group.group_signature for group in groups],
                "repeated_signatures": repeated_signatures,
                "recommended_next_action": recommended_next_action,
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
