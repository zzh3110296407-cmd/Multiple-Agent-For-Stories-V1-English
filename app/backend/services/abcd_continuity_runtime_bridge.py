from typing import Any

from pydantic import BaseModel

from app.backend.models.abcd_runtime_gate import ABCDContinuityRuntimeIssue
from app.backend.models.character_intent import (
    CharacterActionIntentionCandidate,
    CharacterIntentRiskReport,
)
from app.backend.models.continuity import ContinuityIssue, IssueResolutionOption
from app.backend.models.role_memory_writeback import RoleSceneMemoryEntry
from app.backend.services.model_runtime_log_service import utc_now


ABCD_TO_CONTINUITY_CATEGORY = {
    "abcd_forbidden_knowledge": "forbidden_knowledge",
    "abcd_no_source_fact": "no_source_fact",
    "abcd_premature_reveal": "premature_information_reveal",
    "abcd_world_hard_rule_conflict": "world_hard_rule_direct_conflict",
    "abcd_relationship_contradiction": "relationship_contradiction",
    "abcd_location_presence_conflict": "location_scene_state_contradiction",
    "abcd_memory_pack_missing_or_stale": "missing_or_stale_memory_pack",
    "abcd_major_state_change_unconfirmed": "no_source_fact",
    "abcd_claim_or_perception_needs_apparent_gate": "no_source_fact",
}

RISK_CATEGORY_MAP = {
    "forbidden_knowledge": "abcd_forbidden_knowledge",
    "premature_reveal": "abcd_premature_reveal",
    "world_rule_conflict": "abcd_world_hard_rule_conflict",
    "hard_rule_conflict": "abcd_world_hard_rule_conflict",
    "relationship_contradiction": "abcd_relationship_contradiction",
    "location_conflict": "abcd_location_presence_conflict",
    "major_state_change": "abcd_major_state_change_unconfirmed",
}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ABCDContinuityRuntimeBridge:
    def build_runtime_issues(
        self,
        bundle: dict[str, Any],
    ) -> tuple[list[ABCDContinuityRuntimeIssue], list[ContinuityIssue]]:
        context = bundle["context"]
        timestamp = utc_now()
        runtime_issues: list[ABCDContinuityRuntimeIssue] = []

        for warning in context.warnings:
            if "missing" in warning or "stale" in warning:
                runtime_issues.append(
                    self._issue(
                        context=context,
                        issue_category="abcd_memory_pack_missing_or_stale",
                        severity="warning",
                        source_artifact_type="runtime_context",
                        source_artifact_id=context.abcd_runtime_gate_context_id,
                        safe_summary=warning,
                        timestamp=timestamp,
                    )
                )

        risk_by_candidate = {
            report.action_intention_candidate_id: report
            for report in bundle.get("risk_reports") or []
        }
        for candidate in bundle.get("intent_candidates") or []:
            report = risk_by_candidate.get(candidate.action_intention_candidate_id)
            runtime_issues.extend(
                self._issues_for_candidate(
                    context=context,
                    candidate=candidate,
                    report=report,
                    timestamp=timestamp,
                )
            )

        for entry in bundle.get("role_scene_memory_entries") or []:
            runtime_issues.extend(
                self._issues_for_role_entry(
                    context=context,
                    entry=entry,
                    timestamp=timestamp,
                )
            )

        deduped = self._dedupe(runtime_issues)
        continuity_issues = [self._to_continuity_issue(issue) for issue in deduped]
        return deduped, continuity_issues

    def _issues_for_candidate(
        self,
        *,
        context: Any,
        candidate: CharacterActionIntentionCandidate,
        report: CharacterIntentRiskReport | None,
        timestamp: str,
    ) -> list[ABCDContinuityRuntimeIssue]:
        issues: list[ABCDContinuityRuntimeIssue] = []
        candidate_id = candidate.action_intention_candidate_id
        risk_categories = set(report.risk_categories if report else [])
        if report and report.possible_forbidden_knowledge:
            risk_categories.add("forbidden_knowledge")
        if report and report.possible_world_rule_conflict:
            risk_categories.add("world_rule_conflict")
        if report and report.possible_relationship_conflict:
            risk_categories.add("relationship_contradiction")
        if report and report.possible_location_conflict:
            risk_categories.add("location_conflict")
        if report and report.possible_major_state_change:
            risk_categories.add("major_state_change")
        if candidate.requires_continuity_gate and not risk_categories:
            risk_categories.add("no_source_fact")
        if candidate.requires_apparent_gate or candidate.apparent_contradiction_possible:
            issues.append(
                self._issue(
                    context=context,
                    character_id=candidate.character_id,
                    tier=candidate.tier,
                    issue_category="abcd_claim_or_perception_needs_apparent_gate",
                    severity=_candidate_confirmation_severity(candidate),
                    source_artifact_type="character_action_intention_candidate",
                    source_artifact_id=candidate_id,
                    safe_summary=candidate.safe_summary,
                    timestamp=timestamp,
                )
            )
        if candidate.truth_status in {"perception", "unknown"}:
            issues.append(
                self._issue(
                    context=context,
                    character_id=candidate.character_id,
                    tier=candidate.tier,
                    issue_category="abcd_claim_or_perception_needs_apparent_gate",
                    severity=_candidate_confirmation_severity(candidate),
                    source_artifact_type="character_action_intention_candidate",
                    source_artifact_id=candidate_id,
                    safe_summary=candidate.safe_summary,
                    timestamp=timestamp,
                )
            )
        if (
            candidate.truth_status in {"subjective_claim", "lie", "misinformation"}
            and candidate.can_write_objective_fact_directly
        ):
            issues.append(
                self._issue(
                    context=context,
                    character_id=candidate.character_id,
                    tier=candidate.tier,
                    issue_category="abcd_no_source_fact",
                    severity="warning",
                    source_artifact_type="character_action_intention_candidate",
                    source_artifact_id=candidate_id,
                    safe_summary=candidate.safe_summary,
                    timestamp=timestamp,
                )
            )
        if candidate.tier == "D" and (
            candidate.requires_continuity_gate
            or (report and report.risk_level in {"high", "blocking"})
        ):
            issues.append(
                self._issue(
                    context=context,
                    character_id=candidate.character_id,
                    tier=candidate.tier,
                    issue_category="abcd_forbidden_knowledge",
                    severity="blocking",
                    source_artifact_type="character_action_intention_candidate",
                    source_artifact_id=candidate_id,
                    safe_summary=candidate.safe_summary,
                    timestamp=timestamp,
                )
            )
        for risk_category in risk_categories:
            issue_category = RISK_CATEGORY_MAP.get(risk_category, "abcd_no_source_fact")
            severity = "warning"
            if issue_category in {
                "abcd_forbidden_knowledge",
                "abcd_world_hard_rule_conflict",
            }:
                severity = "blocking"
            elif issue_category == "abcd_major_state_change_unconfirmed":
                severity = (
                    "requires_user_confirmation"
                    if candidate.tier in {"A", "B"}
                    and not _is_candidate_only_non_fact(candidate)
                    else "warning"
                )
            issues.append(
                self._issue(
                    context=context,
                    character_id=candidate.character_id,
                    tier=candidate.tier,
                    issue_category=issue_category,
                    severity=severity,
                    source_artifact_type="character_action_intention_candidate",
                    source_artifact_id=candidate_id,
                    safe_summary=report.safe_summary if report else candidate.safe_summary,
                    timestamp=timestamp,
                )
            )
        if candidate.requires_user_confirmation_candidate:
            issues.append(
                self._issue(
                    context=context,
                    character_id=candidate.character_id,
                    tier=candidate.tier,
                    issue_category="abcd_major_state_change_unconfirmed",
                    severity=_candidate_confirmation_severity(candidate),
                    source_artifact_type="character_action_intention_candidate",
                    source_artifact_id=candidate_id,
                    safe_summary=candidate.safe_summary,
                    timestamp=timestamp,
                )
            )
        return issues

    def _issues_for_role_entry(
        self,
        *,
        context: Any,
        entry: RoleSceneMemoryEntry,
        timestamp: str,
    ) -> list[ABCDContinuityRuntimeIssue]:
        if entry.truth_status == "objective_fact" or entry.objective_truth is False:
            return []
        return [
            self._issue(
                context=context,
                character_id=entry.character_id,
                tier=entry.tier,
                issue_category="abcd_no_source_fact",
                severity="blocking",
                source_artifact_type="role_scene_memory_entry",
                source_artifact_id=entry.role_scene_memory_entry_id,
                safe_summary=entry.safe_summary or entry.memory_summary,
                timestamp=timestamp,
                warnings=["non_objective_role_memory_has_objective_truth"],
            )
        ]

    def _issue(
        self,
        *,
        context: Any,
        issue_category: str,
        severity: str,
        source_artifact_type: str,
        source_artifact_id: str,
        safe_summary: str,
        timestamp: str,
        character_id: str = "",
        tier: str = "",
        warnings: list[str] | None = None,
    ) -> ABCDContinuityRuntimeIssue:
        mapped = ABCD_TO_CONTINUITY_CATEGORY.get(issue_category, "no_source_fact")
        runtime_issue_id = _safe_id(
            f"abcd_runtime_issue_{context.scene_id}_{source_artifact_type}_{source_artifact_id}_{issue_category}"
        )
        return ABCDContinuityRuntimeIssue(
            runtime_issue_id=runtime_issue_id,
            project_id=context.project_id,
            scene_id=context.scene_id,
            chapter_id=context.chapter_id,
            scene_index=context.scene_index,
            character_id=character_id,
            tier=tier,
            issue_category=issue_category,
            mapped_continuity_category=mapped,
            severity=severity,
            source_artifact_type=source_artifact_type,
            source_artifact_id=source_artifact_id,
            continuity_issue_id=f"continuity_{runtime_issue_id}",
            suggested_resolution_option_types=_suggested_options(issue_category),
            safe_summary=_short_text(safe_summary, 320),
            warnings=warnings or [],
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _to_continuity_issue(self, issue: ABCDContinuityRuntimeIssue) -> ContinuityIssue:
        is_blocking = issue.severity == "blocking"
        requires_confirmation = issue.severity == "requires_user_confirmation"
        return ContinuityIssue(
            issue_id=issue.continuity_issue_id,
            project_id=issue.project_id,
            target_type="scene",
            target_id=issue.scene_id,
            chapter_id=issue.chapter_id,
            scene_id=issue.scene_id,
            category=issue.mapped_continuity_category,
            severity=issue.severity,
            status="open",
            acceptance_policy=(
                "forbidden"
                if is_blocking
                else "requires_strong_confirmation"
                if requires_confirmation
                else "allowed"
            ),
            user_visible_message=issue.safe_summary,
            technical_summary=(
                f"ABCD runtime issue {issue.issue_category} mapped to "
                f"{issue.mapped_continuity_category}."
            ),
            evidence_text=issue.safe_summary,
            source_character_ids=[issue.character_id] if issue.character_id else [],
            suggested_options=[
                _option(issue.continuity_issue_id, option_type)
                for option_type in issue.suggested_resolution_option_types
                if option_type in {
                    "complete_prior_story",
                    "revise_current_scene",
                    "mark_as_misinformation_or_lie",
                }
            ],
            blocks_final_confirmation=is_blocking,
            blocks_state_changing_revision_confirmation=is_blocking,
            requires_explicit_acceptance=is_blocking or requires_confirmation,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
        )

    def _dedupe(
        self,
        issues: list[ABCDContinuityRuntimeIssue],
    ) -> list[ABCDContinuityRuntimeIssue]:
        result: list[ABCDContinuityRuntimeIssue] = []
        seen: set[str] = set()
        for issue in issues:
            if issue.runtime_issue_id in seen:
                continue
            seen.add(issue.runtime_issue_id)
            result.append(issue)
        return result


def _option(issue_id: str, action_type: str) -> IssueResolutionOption:
    return IssueResolutionOption(
        option_id=f"{issue_id}_{action_type}",
        issue_id=issue_id,
        action_type=action_type,
        label=action_type,
        description="ABCD runtime issue should be reviewed through existing continuity resolution options.",
        requires_user_input=True,
        requires_model_call=action_type == "revise_current_scene",
        expected_effect="Keep ABCD runtime evidence under the existing continuity gate.",
    )


def _suggested_options(issue_category: str) -> list[str]:
    if issue_category == "abcd_claim_or_perception_needs_apparent_gate":
        return ["mark_as_misinformation_or_lie", "revise_current_scene"]
    if issue_category in {"abcd_forbidden_knowledge", "abcd_world_hard_rule_conflict"}:
        return ["revise_current_scene"]
    if issue_category == "abcd_major_state_change_unconfirmed":
        return ["revise_current_scene"]
    return ["complete_prior_story", "revise_current_scene"]


def _is_candidate_only_non_fact(candidate: CharacterActionIntentionCandidate) -> bool:
    return bool(
        candidate.candidate_only
        and candidate.can_write_objective_fact_directly is False
    )


def _candidate_confirmation_severity(
    candidate: CharacterActionIntentionCandidate,
) -> str:
    if _is_candidate_only_non_fact(candidate):
        return "warning"
    return "requires_user_confirmation"


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)[:180]


def _short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]
