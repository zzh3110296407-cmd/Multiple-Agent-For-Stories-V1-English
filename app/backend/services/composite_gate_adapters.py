from app.backend.models.abcd_runtime_gate import ABCDGateReviewResult
from app.backend.models.composite_agent import CompositeAgentStoryFactDelta
from app.backend.models.composite_gate import (
    CompositeGateBlockingFinding,
    CompositeGatePipelineResult,
    CompositeGateStepReceipt,
    CompositeNoWriteAuditReceipt,
    CompositeObjectiveFactBoundaryReceipt,
)
from app.backend.models.composite_integrator import (
    PHASE85C_M2_INTEGRATOR_GATE_PIPELINE_VERSION,
)
from app.backend.services.model_runtime_log_service import utc_now


COMPOSITE_ADAPTER_GATE_PIPELINE_ORDER = [
    "NoWriteGuard",
    "ObjectiveFactBoundaryGate",
    "ContinuityGateAdapter",
    "ApparentContradictionGateAdapter",
    "QualityGateAdapter",
    "UserConfirmationGateAdapter",
    "CompositeGateDecisionReducer",
]


class CompositeGateAdapterService:
    """Dry-review adapters around existing ABCD/M9 gate evidence."""

    def wrap_abcd_gate_result(
        self,
        result: ABCDGateReviewResult,
        *,
        run_id: str,
        bundle_id: str,
        agent_name: str,
        candidate_output_refs: list[str] | None = None,
    ) -> dict[str, object]:
        timestamp = utc_now()
        candidate_refs = _unique_strings(candidate_output_refs or [])
        no_write = self._no_write_from_abcd(
            result,
            run_id,
            bundle_id,
            candidate_refs,
            timestamp,
        )
        objective = self._objective_from_abcd(result, run_id, bundle_id, timestamp)
        receipts = [
            self._no_write_step(no_write, run_id, bundle_id, candidate_refs, timestamp),
            self._objective_step(objective, run_id, bundle_id, candidate_refs, timestamp),
            self._continuity_receipt(result, run_id, bundle_id, candidate_refs, timestamp),
            self._apparent_receipt(result, run_id, bundle_id, candidate_refs, timestamp),
            self._quality_receipt(result, run_id, bundle_id, candidate_refs, timestamp),
        ]
        receipts.append(
            self._user_confirmation_receipt(
                result,
                run_id,
                bundle_id,
                candidate_refs,
                timestamp,
            )
        )
        overall = self._overall_decision(receipts=receipts)
        receipts.append(
            self._reducer_receipt(
                result,
                run_id,
                bundle_id,
                candidate_refs,
                receipts,
                overall,
                timestamp,
            )
        )
        blocked_refs = candidate_refs if overall == "blocked" else []
        allowed_refs = [] if overall == "blocked" else candidate_refs
        requires_confirmation_refs = (
            candidate_refs
            if self._has_unaccepted_user_confirmation(result)
            else []
        )
        pipeline = CompositeGatePipelineResult(
            pipeline_result_id=f"pipeline_adapter_{bundle_id}_{result.mode}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            agent_name=agent_name,
            version_id=PHASE85C_M2_INTEGRATOR_GATE_PIPELINE_VERSION,
            overall_decision=overall,
            hard_block=overall == "blocked",
            dry_review=True,
            gate_step_receipts=receipts,
            no_write_audit_receipt=no_write,
            objective_fact_boundary_receipt=objective,
            candidate_outputs_allowed_for_downstream=allowed_refs,
            candidate_outputs_blocked=blocked_refs,
            requires_user_confirmation_candidate_ids=requires_confirmation_refs,
            requires_user_confirmation=bool(requires_confirmation_refs),
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "Composite adapter wrapped existing ABCD gate evidence for dry review."
            ),
            warnings=_unique_strings(result.warnings),
            blocking_findings=[
                finding
                for receipt in receipts
                for finding in receipt.blocking_findings
            ],
            created_at=timestamp,
        )
        return {
            "adapter_id": "phase85c_m2_abcd_gate_adapter",
            "agent_name": agent_name,
            "source_abcd_context_id": result.context.abcd_runtime_gate_context_id,
            "source_objective_report_id": (
                result.objective_fact_boundary_report.boundary_report_id
            ),
            "source_quality_report_id": (
                result.quality_runtime_report.quality_runtime_report_id
            ),
            "source_audit_id": result.audit.audit_id,
            "source_runtime_issue_ids": [
                issue.runtime_issue_id for issue in result.continuity_runtime_issues
            ],
            "source_apparent_link_ids": [link.link_id for link in result.apparent_links],
            "rewrote_abcd_logic": False,
            "dry_review_only": True,
            "pipeline_result": pipeline,
            "gate_step_receipts": receipts,
            "no_write_audit_receipt": no_write,
            "objective_fact_boundary_receipt": objective,
        }

    def _no_write_from_abcd(
        self,
        result: ABCDGateReviewResult,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        timestamp: str,
    ) -> CompositeNoWriteAuditReceipt:
        audit = result.audit
        violations: list[str] = []
        if not audit.no_unapproved_source_story_mutation:
            violations.append("unapproved_source_story_mutation")
        if not audit.no_auto_resolution:
            violations.append("auto_resolution")
        if not audit.no_prior_story_completion_candidate_auto_apply:
            violations.append("prior_story_completion_candidate_auto_apply")
        if not audit.no_writer_direct_fact_override:
            violations.append("writer_direct_fact_override")
        if not audit.passed and not (violations or audit.violations):
            violations.append("abcd_runtime_gate_audit_failed")
        findings = [
            CompositeGateBlockingFinding(
                finding_id=f"abcd_no_write_{audit.audit_id}_{_safe_id(violation)}",
                gate_name="ABCDNoWriteAdapter",
                severity="blocking",
                finding_type=violation,
                source_ref=audit.audit_id,
                safe_summary="Existing ABCD runtime audit reported a no-write violation.",
                evidence_refs=audit.checked_artifact_ids,
                created_at=timestamp,
            )
            for violation in _unique_strings([*violations, *audit.violations])
        ]
        return CompositeNoWriteAuditReceipt(
            receipt_id=f"abcd_no_write_receipt_{audit.audit_id}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            passed=not findings,
            dry_review=True,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=candidate_refs if findings else [],
            direct_write_attempt_count=_count_values(
                [*violations, *audit.violations],
                {
                    "unapproved_source_story_mutation",
                    "prior_story_completion_candidate_auto_apply",
                    "writer_direct_fact_override",
                },
            ),
            active_memory_write_attempt_count=0,
            confirmed_event_attempt_count=0,
            state_change_attempt_count=0,
            user_confirmation_acceptance_attempt_count=0,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            blocking_findings=findings,
            checked_forbidden_write_types=[
                "unapproved_source_story_mutation",
                "auto_resolution",
                "prior_story_completion_candidate_auto_apply",
                "writer_direct_fact_override",
            ],
            safe_summary=(
                "ABCD audit preserved no-write boundaries."
                if not findings
                else "ABCD audit reported no-write boundary violations."
            ),
            warnings=audit.warnings,
            created_at=timestamp,
        )

    def _no_write_step(
        self,
        receipt: CompositeNoWriteAuditReceipt,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        timestamp: str,
    ) -> CompositeGateStepReceipt:
        return CompositeGateStepReceipt(
            receipt_id=f"abcd_gate_step_{bundle_id}_no_write",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            gate_name="NoWriteGuard",
            decision="pass" if receipt.passed else "blocked",
            severity="info" if receipt.passed else "blocking",
            hard_block=not receipt.passed,
            dry_review=True,
            source_receipt_ids=[receipt.receipt_id],
            candidate_output_refs=candidate_refs,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=receipt.blocked_candidate_ids,
            blocking_findings=receipt.blocking_findings,
            safe_summary=receipt.safe_summary,
            warnings=receipt.warnings,
            created_at=timestamp,
        )

    def _objective_step(
        self,
        receipt: CompositeObjectiveFactBoundaryReceipt,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        timestamp: str,
    ) -> CompositeGateStepReceipt:
        return CompositeGateStepReceipt(
            receipt_id=f"abcd_gate_step_{bundle_id}_objective_boundary",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            gate_name="ObjectiveFactBoundaryGate",
            decision="pass" if receipt.passed else "blocked",
            severity="info" if receipt.passed else "blocking",
            hard_block=not receipt.passed,
            dry_review=True,
            source_receipt_ids=[receipt.receipt_id],
            candidate_output_refs=candidate_refs,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=receipt.blocked_candidate_ids,
            blocking_findings=receipt.blocking_findings,
            safe_summary=receipt.safe_summary,
            warnings=receipt.warnings,
            created_at=timestamp,
        )

    def _objective_from_abcd(
        self,
        result: ABCDGateReviewResult,
        run_id: str,
        bundle_id: str,
        timestamp: str,
    ) -> CompositeObjectiveFactBoundaryReceipt:
        report = result.objective_fact_boundary_report
        finding_types: list[str] = []
        if not report.subjective_claims_kept_subjective:
            finding_types.append("subjective_claim_as_objective_fact")
        if not report.perceptions_kept_subjective:
            finding_types.append("perception_as_objective_fact")
        if not report.lies_kept_non_objective:
            finding_types.append("lie_as_objective_fact")
        if not report.psychology_traces_not_written_as_events:
            finding_types.append("psychology_trace_as_objective_event")
        if not report.expressions_not_written_as_objective_facts:
            finding_types.append("expression_as_objective_fact")
        if not report.no_unapproved_event_write:
            finding_types.append("unapproved_event_write")
        if not report.no_unapproved_state_change_write:
            finding_types.append("unapproved_state_change_write")
        if not report.no_unapproved_memory_record_write:
            finding_types.append("unapproved_memory_record_write")
        if report.blocked_role_memory_artifact_ids:
            finding_types.append("blocked_role_memory_artifact")
        findings = [
            CompositeGateBlockingFinding(
                finding_id=f"abcd_objective_{report.boundary_report_id}_{_safe_id(item)}",
                gate_name="ABCDObjectiveFactBoundaryAdapter",
                severity="blocking",
                finding_type=item,
                source_ref=report.boundary_report_id,
                safe_summary="Existing ABCD objective fact boundary reported a violation.",
                evidence_refs=[
                    *report.checked_candidate_ids,
                    *report.checked_story_information_item_ids,
                    *report.checked_role_memory_entry_ids,
                ],
                created_at=timestamp,
            )
            for item in _unique_strings(finding_types)
        ]
        return CompositeObjectiveFactBoundaryReceipt(
            receipt_id=f"abcd_objective_receipt_{report.boundary_report_id}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            passed=not findings,
            dry_review=True,
            checked_candidate_ids=report.checked_candidate_ids,
            blocked_candidate_ids=[
                *report.blocked_candidate_ids,
                *report.blocked_role_memory_artifact_ids,
            ],
            subjective_claims_kept_subjective=report.subjective_claims_kept_subjective,
            perceptions_kept_subjective=report.perceptions_kept_subjective,
            lies_kept_non_objective=report.lies_kept_non_objective,
            psychology_traces_not_written_as_events=(
                report.psychology_traces_not_written_as_events
            ),
            intents_not_written_as_events=True,
            intents_not_written_as_occurred_facts=True,
            hard_rule_overrides_blocked=True,
            blocking_findings=findings,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=report.safe_summary
            or "ABCD objective fact boundary adapter dry review.",
            warnings=report.warnings,
            created_at=timestamp,
        )

    def _continuity_receipt(
        self,
        result: ABCDGateReviewResult,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        timestamp: str,
    ) -> CompositeGateStepReceipt:
        blocking = [
            issue
            for issue in result.continuity_runtime_issues
            if issue.severity == "blocking"
        ]
        requires = [
            issue
            for issue in result.continuity_runtime_issues
            if issue.severity == "requires_user_confirmation"
        ]
        warnings = [
            issue.runtime_issue_id
            for issue in result.continuity_runtime_issues
            if issue.severity == "warning"
        ]
        decision = "pass"
        severity = "info"
        if blocking:
            decision = "blocked"
            severity = "blocking"
        elif requires:
            decision = "needs_user_confirmation"
            severity = "requires_user_confirmation"
        elif warnings:
            decision = "pass_with_warnings"
            severity = "warning"
        findings = [
            CompositeGateBlockingFinding(
                finding_id=f"abcd_continuity_{issue.runtime_issue_id}",
                gate_name="ContinuityGateAdapter",
                severity=issue.severity,
                finding_type=issue.issue_category,
                source_ref=issue.runtime_issue_id,
                safe_summary=issue.safe_summary
                or "ABCD continuity runtime issue mapped into composite gate receipt.",
                evidence_refs=[issue.source_artifact_id, issue.continuity_issue_id],
                created_at=timestamp,
            )
            for issue in [*blocking, *requires]
        ]
        return CompositeGateStepReceipt(
            receipt_id=f"abcd_continuity_receipt_{result.context.abcd_runtime_gate_context_id}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            gate_name="ContinuityGateAdapter",
            decision=decision,
            severity=severity,
            hard_block=bool(blocking),
            dry_review=True,
            source_receipt_ids=[result.context.abcd_runtime_gate_context_id],
            candidate_output_refs=candidate_refs,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=candidate_refs if blocking else [],
            blocking_findings=findings,
            requires_user_confirmation_candidate_ids=candidate_refs if requires else [],
            safe_summary="ABCD continuity gate evidence wrapped for composite dry review.",
            warnings=warnings,
            created_at=timestamp,
        )

    def _apparent_receipt(
        self,
        result: ABCDGateReviewResult,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        timestamp: str,
    ) -> CompositeGateStepReceipt:
        link_ids = [link.link_id for link in result.apparent_links]
        return CompositeGateStepReceipt(
            receipt_id=f"abcd_apparent_receipt_{result.context.abcd_runtime_gate_context_id}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            gate_name="ApparentContradictionGateAdapter",
            decision="pass_with_warnings" if link_ids else "pass",
            severity="warning" if link_ids else "info",
            hard_block=False,
            dry_review=True,
            source_receipt_ids=link_ids,
            candidate_output_refs=candidate_refs,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=[],
            safe_summary="ABCD apparent contradiction links wrapped for composite dry review.",
            warnings=link_ids,
            created_at=timestamp,
        )

    def _quality_receipt(
        self,
        result: ABCDGateReviewResult,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        timestamp: str,
    ) -> CompositeGateStepReceipt:
        report = result.quality_runtime_report
        decision = "pass"
        severity = "info"
        if report.blocking_issue_ids:
            decision = "blocked"
            severity = "blocking"
        elif report.requires_user_confirmation_issue_ids:
            decision = "needs_user_confirmation"
            severity = "requires_user_confirmation"
        elif report.warning_issue_ids or not report.passed:
            decision = "pass_with_warnings"
            severity = "warning"
        findings = [
            CompositeGateBlockingFinding(
                finding_id=f"abcd_quality_{issue_id}",
                gate_name="QualityGateAdapter",
                severity="blocking",
                finding_type="quality_blocking_issue",
                source_ref=issue_id,
                safe_summary="ABCD quality runtime report contained a blocking issue.",
                evidence_refs=[report.quality_runtime_report_id],
                created_at=timestamp,
            )
            for issue_id in report.blocking_issue_ids
        ]
        return CompositeGateStepReceipt(
            receipt_id=f"abcd_quality_receipt_{report.quality_runtime_report_id}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            gate_name="QualityGateAdapter",
            decision=decision,
            severity=severity,
            hard_block=bool(report.blocking_issue_ids),
            dry_review=True,
            source_receipt_ids=[report.quality_runtime_report_id],
            candidate_output_refs=candidate_refs,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=candidate_refs if report.blocking_issue_ids else [],
            blocking_findings=findings,
            requires_user_confirmation_candidate_ids=(
                candidate_refs if report.requires_user_confirmation_issue_ids else []
            ),
            safe_summary=report.safe_summary
            or "ABCD quality gate report wrapped for composite dry review.",
            warnings=[*report.warning_issue_ids, *report.warnings],
            created_at=timestamp,
        )

    def _audit_receipt(
        self,
        result: ABCDGateReviewResult,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        timestamp: str,
    ) -> CompositeGateStepReceipt:
        audit = result.audit
        decision = "pass" if audit.passed else "blocked"
        return CompositeGateStepReceipt(
            receipt_id=f"abcd_audit_receipt_{audit.audit_id}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            gate_name="ABCDRuntimeGateAuditAdapter",
            decision=decision,
            severity="info" if audit.passed else "blocking",
            hard_block=not audit.passed,
            dry_review=True,
            source_receipt_ids=[audit.audit_id],
            candidate_output_refs=candidate_refs,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=candidate_refs if not audit.passed else [],
            blocking_findings=[
                CompositeGateBlockingFinding(
                    finding_id=f"abcd_audit_{audit.audit_id}_{_safe_id(violation)}",
                    gate_name="ABCDRuntimeGateAuditAdapter",
                    severity="blocking",
                    finding_type=violation,
                    source_ref=audit.audit_id,
                    safe_summary="ABCD runtime audit reported a violation.",
                    evidence_refs=audit.checked_artifact_ids,
                    created_at=timestamp,
                )
                for violation in audit.violations
            ],
            requires_user_confirmation_candidate_ids=(
                candidate_refs if audit.requires_user_confirmation_issue_ids else []
            ),
            safe_summary=audit.safe_summary
            or "ABCD runtime audit wrapped for composite dry review.",
            warnings=audit.warnings,
            created_at=timestamp,
        )

    def _user_confirmation_receipt(
        self,
        result: ABCDGateReviewResult,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        timestamp: str,
    ) -> CompositeGateStepReceipt:
        requires = self._has_unaccepted_user_confirmation(result)
        return CompositeGateStepReceipt(
            receipt_id=f"abcd_user_confirmation_receipt_{result.context.abcd_runtime_gate_context_id}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            gate_name="UserConfirmationGateAdapter",
            decision="needs_user_confirmation" if requires else "candidate_only",
            severity="requires_user_confirmation" if requires else "info",
            hard_block=False,
            dry_review=True,
            source_receipt_ids=[
                result.quality_runtime_report.quality_runtime_report_id,
                result.audit.audit_id,
            ],
            candidate_output_refs=candidate_refs,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=[],
            requires_user_confirmation_candidate_ids=candidate_refs if requires else [],
            safe_summary=(
                "ABCD gate evidence requires future user confirmation."
                if requires
                else "ABCD gate evidence has no unaccepted user confirmation requirement."
            ),
            warnings=result.quality_runtime_report.requires_user_confirmation_issue_ids,
            created_at=timestamp,
        )

    def _reducer_receipt(
        self,
        result: ABCDGateReviewResult,
        run_id: str,
        bundle_id: str,
        candidate_refs: list[str],
        receipts: list[CompositeGateStepReceipt],
        overall: str,
        timestamp: str,
    ) -> CompositeGateStepReceipt:
        return CompositeGateStepReceipt(
            receipt_id=f"abcd_decision_reducer_receipt_{result.context.abcd_runtime_gate_context_id}",
            run_id=run_id,
            bundle_id=bundle_id,
            input_bundle_id=bundle_id,
            gate_name="CompositeGateDecisionReducer",
            decision=overall,
            severity="blocking" if overall == "blocked" else "info",
            hard_block=overall == "blocked",
            dry_review=True,
            source_receipt_ids=[
                *[receipt.receipt_id for receipt in receipts],
                result.audit.audit_id,
            ],
            candidate_output_refs=candidate_refs,
            checked_candidate_ids=candidate_refs,
            blocked_candidate_ids=candidate_refs if overall == "blocked" else [],
            blocking_findings=[
                finding
                for receipt in receipts
                for finding in receipt.blocking_findings
            ],
            requires_user_confirmation_candidate_ids=(
                candidate_refs
                if self._has_unaccepted_user_confirmation(result)
                else []
            ),
            safe_summary="Composite adapter reduced ABCD dry-review receipts into an overall decision.",
            warnings=result.audit.warnings,
            created_at=timestamp,
        )

    def _overall_decision(
        self,
        *,
        receipts: list[CompositeGateStepReceipt],
    ) -> str:
        if any(receipt.hard_block for receipt in receipts):
            return "blocked"
        if any(receipt.decision == "needs_user_confirmation" for receipt in receipts):
            return "needs_user_confirmation"
        if any(receipt.decision == "pass_with_warnings" for receipt in receipts):
            return "pass_with_warnings"
        return "pass"

    def _has_unaccepted_user_confirmation(self, result: ABCDGateReviewResult) -> bool:
        quality = result.quality_runtime_report
        accepted = set(quality.accepted_user_confirmation_issue_ids)
        quality_requires = [
            issue_id
            for issue_id in quality.requires_user_confirmation_issue_ids
            if issue_id not in accepted
        ]
        audit_requires = [
            issue_id
            for issue_id in result.audit.requires_user_confirmation_issue_ids
            if issue_id not in set(result.audit.accepted_user_confirmation_issue_ids)
        ]
        return bool(quality_requires or audit_requires)


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value))[:80]


def _unique_strings(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _count_values(values: list[str], expected: set[str]) -> int:
    expected_normalized = {value.casefold() for value in expected}
    return sum(
        1
        for value in values
        if str(value or "").strip().casefold() in expected_normalized
    )
