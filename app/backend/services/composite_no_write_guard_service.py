from app.backend.models.composite_agent import CompositeAgentStoryFactDelta
from app.backend.models.composite_gate import (
    CompositeGateBlockingFinding,
    CompositeNoWriteAuditReceipt,
)
from app.backend.models.composite_integrator import (
    CompositeCandidateItem,
    CompositeIntegratedOutputBundle,
)
from app.backend.services.model_runtime_log_service import utc_now


FORBIDDEN_WRITE_TYPES = [
    "active_memory_write",
    "committed_fact",
    "confirmed_event",
    "state_change_write",
    "relationship_write",
    "scene_prose_mutation",
    "user_confirmation_accepted",
    "resolved_continuity_issue",
    "narrative_debt_payoff",
    "direct_story_fact_write_claim",
    "non_candidate_output_claim",
    "unsafe_authority_claim",
]


class CompositeNoWriteGuardService:
    def inspect_bundle(
        self,
        bundle: CompositeIntegratedOutputBundle,
    ) -> CompositeNoWriteAuditReceipt:
        timestamp = utc_now()
        findings: list[CompositeGateBlockingFinding] = []
        for candidate in bundle.integrated_candidates:
            findings.extend(self._find_forbidden_write_claims(candidate, timestamp))
        if not bundle.story_fact_delta.is_empty():
            findings.append(
                CompositeGateBlockingFinding(
                    finding_id=f"no_write_{bundle.bundle_id}_story_fact_delta",
                    gate_name="NoWriteGuard",
                    severity="blocking",
                    finding_type="story_fact_delta_not_empty",
                    safe_summary="Composite bundle carried a story fact delta.",
                    created_at=timestamp,
                )
            )
        blocked_ids = _unique_strings(
            finding.candidate_id for finding in findings if finding.candidate_id
        )
        attempt_counts = _attempt_counts(findings)
        return CompositeNoWriteAuditReceipt(
            receipt_id=f"no_write_receipt_{bundle.bundle_id}",
            run_id=bundle.run_id,
            bundle_id=bundle.bundle_id,
            input_bundle_id=bundle.bundle_id,
            passed=not findings,
            dry_review=True,
            checked_candidate_ids=[
                candidate.candidate_id for candidate in bundle.integrated_candidates
            ],
            blocked_candidate_ids=blocked_ids,
            direct_write_attempt_count=attempt_counts["direct_write_attempt_count"],
            active_memory_write_attempt_count=attempt_counts[
                "active_memory_write_attempt_count"
            ],
            confirmed_event_attempt_count=attempt_counts[
                "confirmed_event_attempt_count"
            ],
            state_change_attempt_count=attempt_counts["state_change_attempt_count"],
            user_confirmation_acceptance_attempt_count=attempt_counts[
                "user_confirmation_acceptance_attempt_count"
            ],
            relationship_write_attempt_count=attempt_counts[
                "relationship_write_attempt_count"
            ],
            scene_prose_mutation_attempt_count=attempt_counts[
                "scene_prose_mutation_attempt_count"
            ],
            resolved_continuity_issue_attempt_count=attempt_counts[
                "resolved_continuity_issue_attempt_count"
            ],
            narrative_debt_payoff_attempt_count=attempt_counts[
                "narrative_debt_payoff_attempt_count"
            ],
            story_fact_delta=CompositeAgentStoryFactDelta(),
            blocking_findings=findings,
            checked_forbidden_write_types=FORBIDDEN_WRITE_TYPES,
            safe_summary=(
                "No direct story fact writes were found in the composite bundle."
                if not findings
                else "NoWriteGuard blocked composite candidates with direct write claims."
            ),
            warnings=[],
            created_at=timestamp,
        )

    def _find_forbidden_write_claims(
        self,
        candidate: CompositeCandidateItem,
        timestamp: str,
    ) -> list[CompositeGateBlockingFinding]:
        findings: list[CompositeGateBlockingFinding] = []
        markers = [
            candidate.output_type,
            candidate.source_object_type,
            candidate.source_object_id,
            candidate.semantic_key,
            *candidate.blocking_findings,
            *candidate.warnings,
        ]
        marker_text = " ".join(str(item or "") for item in markers).casefold()
        if candidate.can_write_story_facts_directly:
            findings.append(
                self._finding(
                    candidate,
                    "direct_story_fact_write_true",
                    "Candidate declared direct story fact write permission.",
                    timestamp,
                )
            )
        if not candidate.candidate_only:
            findings.append(
                self._finding(
                    candidate,
                    "candidate_only_false",
                    "Candidate declared non-candidate authority.",
                    timestamp,
                )
            )
        for marker in FORBIDDEN_WRITE_TYPES:
            if marker.casefold() not in marker_text:
                continue
            findings.append(
                self._finding(
                    candidate,
                    marker,
                    "Composite candidate contained a forbidden write or commit marker.",
                    timestamp,
                )
            )
        return findings

    def _finding(
        self,
        candidate: CompositeCandidateItem,
        finding_type: str,
        safe_summary: str,
        timestamp: str,
    ) -> CompositeGateBlockingFinding:
        return CompositeGateBlockingFinding(
            finding_id=f"no_write_{candidate.candidate_id}_{_safe_id(finding_type)}",
            gate_name="NoWriteGuard",
            severity="blocking",
            candidate_id=candidate.candidate_id,
            finding_type=finding_type,
            finding_code=finding_type,
            source_ref=candidate.source_object_id or candidate.semantic_key,
            source_refs=[candidate.source_object_id or candidate.semantic_key],
            safe_summary=safe_summary,
            evidence_refs=candidate.evidence_refs,
            created_at=timestamp,
        )


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)[:80]


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


def _attempt_counts(findings: list[CompositeGateBlockingFinding]) -> dict[str, int]:
    finding_codes = [finding.finding_code or finding.finding_type for finding in findings]
    return {
        "direct_write_attempt_count": _count_codes(
            finding_codes,
            {
                "direct_story_fact_write_true",
                "direct_story_fact_write_claim",
                "story_fact_delta_not_empty",
            },
        ),
        "active_memory_write_attempt_count": _count_codes(
            finding_codes,
            {"active_memory_write"},
        ),
        "confirmed_event_attempt_count": _count_codes(
            finding_codes,
            {"confirmed_event", "committed_fact"},
        ),
        "state_change_attempt_count": _count_codes(
            finding_codes,
            {"state_change_write"},
        ),
        "user_confirmation_acceptance_attempt_count": _count_codes(
            finding_codes,
            {"user_confirmation_accepted"},
        ),
        "relationship_write_attempt_count": _count_codes(
            finding_codes,
            {"relationship_write"},
        ),
        "scene_prose_mutation_attempt_count": _count_codes(
            finding_codes,
            {"scene_prose_mutation"},
        ),
        "resolved_continuity_issue_attempt_count": _count_codes(
            finding_codes,
            {"resolved_continuity_issue"},
        ),
        "narrative_debt_payoff_attempt_count": _count_codes(
            finding_codes,
            {"narrative_debt_payoff"},
        ),
    }


def _count_codes(codes: list[str], expected: set[str]) -> int:
    expected_normalized = {code.casefold() for code in expected}
    return sum(1 for code in codes if str(code or "").casefold() in expected_normalized)
