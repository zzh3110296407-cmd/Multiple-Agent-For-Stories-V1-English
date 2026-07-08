from typing import Any

from app.backend.models.abcd_runtime_gate import (
    ABCDContinuityRuntimeIssue,
    ABCDObjectiveFactBoundaryReport,
    ABCDQualityGateRuntimeReport,
)
from app.backend.models.apparent_contradiction import ApparentContradictionGateResult
from app.backend.services.model_runtime_log_service import utc_now


class ABCDQualityGateBridge:
    def build_report(
        self,
        *,
        bundle: dict[str, Any],
        runtime_issues: list[ABCDContinuityRuntimeIssue],
        apparent_result: ApparentContradictionGateResult,
        objective_report: ABCDObjectiveFactBoundaryReport,
        accepted_issue_ids: set[str] | None = None,
        accept_all_requires_user_confirmation: bool = False,
    ) -> ABCDQualityGateRuntimeReport:
        context = bundle["context"]
        timestamp = utc_now()
        accepted = {str(item or "").strip() for item in accepted_issue_ids or set() if str(item or "").strip()}
        confirmation_exempt_issue_ids = _candidate_only_non_fact_issue_ids(
            bundle,
            runtime_issues,
        )
        blocking_ids = _unique(
            [
                issue.runtime_issue_id
                for issue in runtime_issues
                if issue.severity == "blocking"
            ]
            + [
                _runtime_id_for_continuity_id(runtime_issues, issue_id)
                for issue_id in apparent_result.issues_to_block
            ]
        )
        requires_confirmation_ids = _unique(
            [
                issue.runtime_issue_id
                for issue in runtime_issues
                if issue.severity == "requires_user_confirmation"
                and issue.runtime_issue_id not in confirmation_exempt_issue_ids
            ]
            + [
                _runtime_id_for_continuity_id(runtime_issues, issue_id)
                for issue_id in apparent_result.issues_requiring_user_confirmation
                if _runtime_id_for_continuity_id(runtime_issues, issue_id)
                not in confirmation_exempt_issue_ids
            ]
        )
        if accept_all_requires_user_confirmation:
            accepted.update(requires_confirmation_ids)
        accepted_confirmation_ids = _unique(
            [issue_id for issue_id in requires_confirmation_ids if issue_id in accepted]
        )
        unresolved_requires_confirmation_ids = _unique(
            [
                issue_id
                for issue_id in requires_confirmation_ids
                if issue_id not in set(accepted_confirmation_ids)
            ]
        )
        warning_ids = _unique(
            [
                issue.runtime_issue_id
                for issue in runtime_issues
                if issue.severity == "warning"
            ]
            + [
                _runtime_id_for_continuity_id(runtime_issues, issue_id)
                for issue_id in apparent_result.issues_to_warn
            ]
            + [
                issue_id
                for issue_id in confirmation_exempt_issue_ids
                if issue_id
            ]
        )
        character_knowledge_passed = not any(
            issue.issue_category == "abcd_forbidden_knowledge"
            and issue.severity == "blocking"
            for issue in runtime_issues
        )
        role_presence_passed = bool(context.selected_character_ids)
        subjective_fact_boundary_passed = (
            objective_report.subjective_claims_kept_subjective
            and objective_report.perceptions_kept_subjective
            and objective_report.lies_kept_non_objective
        )
        memory_write_scope_passed = (
            objective_report.no_unapproved_memory_record_write
            and objective_report.no_unapproved_event_write
            and objective_report.no_unapproved_state_change_write
            and not objective_report.blocked_role_memory_artifact_ids
        )
        major_state_change_confirmation_passed = not any(
            issue.issue_category == "abcd_major_state_change_unconfirmed"
            for issue in runtime_issues
            if issue.severity == "blocking"
            or (
                issue.severity == "requires_user_confirmation"
                and issue.runtime_issue_id not in confirmation_exempt_issue_ids
                and issue.runtime_issue_id not in set(accepted_confirmation_ids)
            )
        )
        passed = (
            character_knowledge_passed
            and role_presence_passed
            and subjective_fact_boundary_passed
            and memory_write_scope_passed
            and major_state_change_confirmation_passed
            and not blocking_ids
            and not unresolved_requires_confirmation_ids
        )
        warnings = []
        if not role_presence_passed:
            warnings.append("scene_participation_package_has_no_selected_characters")
        if objective_report.blocked_role_memory_artifact_ids:
            warnings.append("role_memory_objective_fact_boundary_blocked")
        return ABCDQualityGateRuntimeReport(
            quality_runtime_report_id=f"abcd_quality_runtime_{context.scene_id}_{context.mode}",
            project_id=context.project_id,
            scene_id=context.scene_id,
            passed=passed,
            character_knowledge_boundary_passed=character_knowledge_passed,
            role_presence_passed=role_presence_passed,
            subjective_fact_boundary_passed=subjective_fact_boundary_passed,
            memory_write_scope_passed=memory_write_scope_passed,
            major_state_change_confirmation_passed=major_state_change_confirmation_passed,
            blocking_issue_ids=blocking_ids,
            warning_issue_ids=warning_ids,
            requires_user_confirmation_issue_ids=unresolved_requires_confirmation_ids,
            accepted_user_confirmation_issue_ids=accepted_confirmation_ids,
            safe_summary=(
                "ABCD runtime quality gate passed."
                if passed
                else "ABCD runtime quality gate found blocking or confirmation-required issues."
            ),
            warnings=warnings,
            created_at=timestamp,
            updated_at=timestamp,
        )


def _runtime_id_for_continuity_id(
    runtime_issues: list[ABCDContinuityRuntimeIssue],
    continuity_issue_id: str,
) -> str:
    for issue in runtime_issues:
        if issue.continuity_issue_id == continuity_issue_id:
            return issue.runtime_issue_id
    return continuity_issue_id


def _candidate_only_non_fact_issue_ids(
    bundle: dict[str, Any],
    runtime_issues: list[ABCDContinuityRuntimeIssue],
) -> set[str]:
    candidate_ids = {
        candidate.action_intention_candidate_id
        for candidate in bundle.get("intent_candidates") or []
        if getattr(candidate, "candidate_only", False)
        and getattr(candidate, "can_write_objective_fact_directly", True) is False
    }
    hard_issue_categories = {
        "abcd_forbidden_knowledge",
        "abcd_world_hard_rule_conflict",
    }
    return {
        issue.runtime_issue_id
        for issue in runtime_issues
        if issue.source_artifact_type == "character_action_intention_candidate"
        and issue.source_artifact_id in candidate_ids
        and issue.issue_category not in hard_issue_categories
    }


def _unique(values: list[str]) -> list[str]:
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
