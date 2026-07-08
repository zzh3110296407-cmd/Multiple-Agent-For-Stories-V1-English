from app.backend.models.composite_agent import CompositeAgentStoryFactDelta
from app.backend.models.composite_gate import (
    CompositeGateBlockingFinding,
    CompositeGatePipelineResult,
    CompositeGateStepReceipt,
    CompositeObjectiveFactBoundaryReceipt,
)
from app.backend.models.composite_integrator import (
    PHASE85C_M2_INTEGRATOR_GATE_PIPELINE_VERSION,
    CompositeCandidateItem,
    CompositeIntegratedOutputBundle,
)
from app.backend.services.composite_no_write_guard_service import (
    CompositeNoWriteGuardService,
)
from app.backend.services.model_runtime_log_service import utc_now


COMPOSITE_GATE_PIPELINE_ORDER = [
    "NoWriteGuard",
    "ObjectiveFactBoundaryGate",
    "ContinuityGateAdapter",
    "ApparentContradictionGateAdapter",
    "QualityGateAdapter",
    "UserConfirmationGateAdapter",
    "CompositeGateDecisionReducer",
]


class CompositeGatePipelineService:
    def __init__(
        self,
        *,
        no_write_guard: CompositeNoWriteGuardService | None = None,
    ) -> None:
        self.no_write_guard = no_write_guard or CompositeNoWriteGuardService()

    def run_dry_review(
        self,
        bundle: CompositeIntegratedOutputBundle,
    ) -> CompositeGatePipelineResult:
        timestamp = utc_now()
        no_write = self.no_write_guard.inspect_bundle(bundle)
        objective = self._objective_fact_boundary(bundle)

        receipts: list[CompositeGateStepReceipt] = [
            CompositeGateStepReceipt(
                receipt_id=f"gate_step_{bundle.bundle_id}_no_write",
                run_id=bundle.run_id,
                bundle_id=bundle.bundle_id,
                input_bundle_id=bundle.bundle_id,
                gate_name="NoWriteGuard",
                decision="pass" if no_write.passed else "blocked",
                severity="info" if no_write.passed else "blocking",
                hard_block=not no_write.passed,
                dry_review=True,
                source_receipt_ids=[no_write.receipt_id],
                candidate_output_refs=no_write.checked_candidate_ids,
                checked_candidate_ids=no_write.checked_candidate_ids,
                blocked_candidate_ids=no_write.blocked_candidate_ids,
                blocking_findings=no_write.blocking_findings,
                safe_summary=no_write.safe_summary,
                warnings=no_write.warnings,
                created_at=timestamp,
            ),
            CompositeGateStepReceipt(
                receipt_id=f"gate_step_{bundle.bundle_id}_objective_boundary",
                run_id=bundle.run_id,
                bundle_id=bundle.bundle_id,
                input_bundle_id=bundle.bundle_id,
                gate_name="ObjectiveFactBoundaryGate",
                decision="pass" if objective.passed else "blocked",
                severity="info" if objective.passed else "blocking",
                hard_block=not objective.passed,
                dry_review=True,
                source_receipt_ids=[objective.receipt_id],
                candidate_output_refs=objective.checked_candidate_ids,
                checked_candidate_ids=objective.checked_candidate_ids,
                blocked_candidate_ids=objective.blocked_candidate_ids,
                blocking_findings=objective.blocking_findings,
                safe_summary=objective.safe_summary,
                warnings=objective.warnings,
                created_at=timestamp,
            ),
        ]
        receipts.extend(self._adapter_receipts(bundle, timestamp))

        requires_confirmation = [
            candidate.candidate_id
            for candidate in bundle.integrated_candidates
            if (
                candidate.objective_fact_risk
                or any("user_confirmation" in item for item in candidate.warnings)
                or any(
                    "user_confirmation" in item
                    for item in candidate.blocking_findings
                )
            )
        ]
        receipts.append(
            CompositeGateStepReceipt(
                receipt_id=f"gate_step_{bundle.bundle_id}_user_confirmation",
                run_id=bundle.run_id,
                bundle_id=bundle.bundle_id,
                input_bundle_id=bundle.bundle_id,
                gate_name="UserConfirmationGateAdapter",
                decision=(
                    "needs_user_confirmation"
                    if requires_confirmation
                    else "candidate_only"
                ),
                severity=(
                    "requires_user_confirmation"
                    if requires_confirmation
                    else "info"
                ),
                hard_block=False,
                dry_review=True,
                candidate_output_refs=[
                    candidate.candidate_id for candidate in bundle.integrated_candidates
                ],
                checked_candidate_ids=[
                    candidate.candidate_id for candidate in bundle.integrated_candidates
                ],
                blocked_candidate_ids=[],
                requires_user_confirmation_candidate_ids=requires_confirmation,
                safe_summary=(
                    "Composite candidates require future user confirmation."
                    if requires_confirmation
                    else "No composite candidates requested user confirmation."
                ),
                created_at=timestamp,
            )
        )

        blocked_ids = _unique_strings(
            [
                *no_write.blocked_candidate_ids,
                *objective.blocked_candidate_ids,
            ]
        )
        allowed_ids = [
            candidate.candidate_id
            for candidate in bundle.integrated_candidates
            if candidate.candidate_id not in set(blocked_ids)
        ]
        overall_decision = self._overall_decision(
            receipts=receipts,
            conflicts=bool(bundle.conflict_groups),
            requires_confirmation=bool(requires_confirmation),
        )
        reducer = CompositeGateStepReceipt(
            receipt_id=f"gate_step_{bundle.bundle_id}_decision_reducer",
            run_id=bundle.run_id,
            bundle_id=bundle.bundle_id,
            input_bundle_id=bundle.bundle_id,
            gate_name="CompositeGateDecisionReducer",
            decision=overall_decision,
            severity="blocking" if overall_decision == "blocked" else "info",
            hard_block=overall_decision == "blocked",
            dry_review=True,
            source_receipt_ids=[receipt.receipt_id for receipt in receipts],
            candidate_output_refs=[
                candidate.candidate_id for candidate in bundle.integrated_candidates
            ],
            checked_candidate_ids=[
                candidate.candidate_id for candidate in bundle.integrated_candidates
            ],
            blocked_candidate_ids=blocked_ids if overall_decision == "blocked" else [],
            blocking_findings=[
                finding
                for receipt in receipts
                for finding in receipt.blocking_findings
            ],
            safe_summary="Composite Gate Pipeline reduced dry-review receipts into an overall decision.",
            created_at=timestamp,
        )
        receipts.append(reducer)
        return CompositeGatePipelineResult(
            pipeline_result_id=f"pipeline_{bundle.bundle_id}",
            run_id=bundle.run_id,
            bundle_id=bundle.bundle_id,
            input_bundle_id=bundle.bundle_id,
            agent_name=bundle.agent_name,
            version_id=PHASE85C_M2_INTEGRATOR_GATE_PIPELINE_VERSION,
            overall_decision=overall_decision,
            hard_block=overall_decision == "blocked",
            dry_review=True,
            gate_step_receipts=receipts,
            no_write_audit_receipt=no_write,
            objective_fact_boundary_receipt=objective,
            candidate_outputs_allowed_for_downstream=allowed_ids,
            candidate_outputs_blocked=blocked_ids,
            requires_user_confirmation_candidate_ids=requires_confirmation,
            requires_user_confirmation=bool(requires_confirmation),
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "Composite Gate Pipeline completed a deterministic dry review."
            ),
            warnings=_unique_strings(bundle.warnings),
            blocking_findings=[
                finding
                for receipt in receipts
                for finding in receipt.blocking_findings
            ],
            created_at=timestamp,
        )

    def _objective_fact_boundary(
        self,
        bundle: CompositeIntegratedOutputBundle,
    ) -> CompositeObjectiveFactBoundaryReceipt:
        timestamp = utc_now()
        findings: list[CompositeGateBlockingFinding] = []
        for candidate in bundle.integrated_candidates:
            finding_types = self._objective_boundary_finding_types(candidate)
            for finding_type in finding_types:
                findings.append(
                    CompositeGateBlockingFinding(
                        finding_id=(
                            f"objective_boundary_{candidate.candidate_id}_{finding_type}"
                        ),
                        gate_name="ObjectiveFactBoundaryGate",
                        severity="blocking",
                        candidate_id=candidate.candidate_id,
                        finding_type=finding_type,
                        source_ref=candidate.source_object_id
                        or candidate.semantic_key,
                        safe_summary=(
                            "Candidate cannot be promoted as objective fact in dry review."
                        ),
                        evidence_refs=candidate.evidence_refs,
                        created_at=timestamp,
                    )
                )
        blocked_ids = _unique_strings(
            finding.candidate_id for finding in findings if finding.candidate_id
        )
        return CompositeObjectiveFactBoundaryReceipt(
            receipt_id=f"objective_boundary_receipt_{bundle.bundle_id}",
            run_id=bundle.run_id,
            bundle_id=bundle.bundle_id,
            input_bundle_id=bundle.bundle_id,
            passed=not findings,
            dry_review=True,
            checked_candidate_ids=[
                candidate.candidate_id for candidate in bundle.integrated_candidates
            ],
            blocked_candidate_ids=blocked_ids,
            subjective_claims_kept_subjective=not any(
                finding.finding_type == "subjective_claim_as_objective_fact"
                for finding in findings
            ),
            perceptions_kept_subjective=not any(
                finding.finding_type == "perception_as_objective_fact"
                for finding in findings
            ),
            lies_kept_non_objective=not any(
                finding.finding_type == "lie_as_objective_fact"
                for finding in findings
            ),
            psychology_traces_not_written_as_events=not any(
                finding.finding_type == "psychology_trace_as_objective_event"
                for finding in findings
            ),
            intents_not_written_as_events=not any(
                finding.finding_type == "intent_as_objective_event"
                for finding in findings
            ),
            intents_not_written_as_occurred_facts=not any(
                finding.finding_type == "intent_as_objective_event"
                for finding in findings
            ),
            hard_rule_overrides_blocked=not any(
                finding.finding_type == "authorial_intent_hard_rule_override"
                for finding in findings
            ),
            blocking_findings=findings,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "Objective fact boundary accepted composite candidates."
                if not findings
                else "Objective fact boundary blocked unsafe objective fact candidates."
            ),
            warnings=[],
            created_at=timestamp,
        )

    def _objective_boundary_finding_types(
        self,
        candidate: CompositeCandidateItem,
    ) -> list[str]:
        if candidate.truth_status != "objective_fact":
            return []
        marker_text = " ".join(
            [
                candidate.source_object_type,
                candidate.semantic_key,
                candidate.safe_summary,
                *candidate.warnings,
                *candidate.blocking_findings,
            ]
        ).casefold()
        findings: list[str] = []
        if "subjective_claim" in marker_text or candidate.source_object_type == "subjective_claim":
            findings.append("subjective_claim_as_objective_fact")
        if "perception" in marker_text:
            findings.append("perception_as_objective_fact")
        if "lie" in marker_text:
            findings.append("lie_as_objective_fact")
        if "psychology" in marker_text:
            findings.append("psychology_trace_as_objective_event")
        if "intent" in marker_text or "action_intention" in marker_text:
            findings.append("intent_as_objective_event")
        if "hard_rule_override" in marker_text or "authorialintent" in marker_text:
            findings.append("authorial_intent_hard_rule_override")
        if candidate.objective_fact_risk:
            findings.append("objective_fact_risk_requires_review")
        return _unique_strings(findings)

    def _adapter_receipts(
        self,
        bundle: CompositeIntegratedOutputBundle,
        timestamp: str,
    ) -> list[CompositeGateStepReceipt]:
        has_conflict = bool(bundle.conflict_groups)
        has_warnings = bool(bundle.warnings or bundle.gate_review_requests)
        candidate_ids = [
            candidate.candidate_id for candidate in bundle.integrated_candidates
        ]
        continuity_decision = "pass_with_warnings" if has_conflict else "pass"
        apparent_decision = "pass_with_warnings" if has_conflict else "pass"
        quality_decision = "pass_with_warnings" if has_warnings or has_conflict else "pass"
        return [
            CompositeGateStepReceipt(
                receipt_id=f"gate_step_{bundle.bundle_id}_continuity_adapter",
                run_id=bundle.run_id,
                bundle_id=bundle.bundle_id,
                input_bundle_id=bundle.bundle_id,
                gate_name="ContinuityGateAdapter",
                decision=continuity_decision,
                severity="warning" if has_conflict else "info",
                hard_block=False,
                dry_review=True,
                candidate_output_refs=candidate_ids,
                checked_candidate_ids=candidate_ids,
                blocked_candidate_ids=[],
                safe_summary="Continuity gate adapter dry-reviewed composite candidate conflicts.",
                warnings=["candidate_conflict_requires_continuity_review"]
                if has_conflict
                else [],
                created_at=timestamp,
            ),
            CompositeGateStepReceipt(
                receipt_id=f"gate_step_{bundle.bundle_id}_apparent_adapter",
                run_id=bundle.run_id,
                bundle_id=bundle.bundle_id,
                input_bundle_id=bundle.bundle_id,
                gate_name="ApparentContradictionGateAdapter",
                decision=apparent_decision,
                severity="warning" if has_conflict else "info",
                hard_block=False,
                dry_review=True,
                candidate_output_refs=candidate_ids,
                checked_candidate_ids=candidate_ids,
                blocked_candidate_ids=[],
                safe_summary="Apparent contradiction gate adapter dry-reviewed composite candidates.",
                warnings=["candidate_conflict_requires_apparent_contradiction_review"]
                if has_conflict
                else [],
                created_at=timestamp,
            ),
            CompositeGateStepReceipt(
                receipt_id=f"gate_step_{bundle.bundle_id}_quality_adapter",
                run_id=bundle.run_id,
                bundle_id=bundle.bundle_id,
                input_bundle_id=bundle.bundle_id,
                gate_name="QualityGateAdapter",
                decision=quality_decision,
                severity="warning" if quality_decision == "pass_with_warnings" else "info",
                hard_block=False,
                dry_review=True,
                candidate_output_refs=candidate_ids,
                checked_candidate_ids=candidate_ids,
                blocked_candidate_ids=[],
                safe_summary="Quality gate adapter dry-reviewed composite candidates.",
                warnings=["candidate_bundle_requires_quality_review"]
                if quality_decision == "pass_with_warnings"
                else [],
                created_at=timestamp,
            ),
        ]

    def _overall_decision(
        self,
        *,
        receipts: list[CompositeGateStepReceipt],
        conflicts: bool,
        requires_confirmation: bool,
    ) -> str:
        if any(receipt.hard_block for receipt in receipts):
            return "blocked"
        if requires_confirmation:
            return "needs_user_confirmation"
        if conflicts or any(receipt.decision == "pass_with_warnings" for receipt in receipts):
            return "pass_with_warnings"
        return "candidate_only"


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
