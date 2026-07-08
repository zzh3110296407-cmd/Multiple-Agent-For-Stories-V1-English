import hashlib
import json
from typing import Any

from pydantic import BaseModel

from app.backend.models.composite_agent import (
    COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES,
    COMPOSITE_AGENT_AUTHORITY_LEVELS,
    COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES,
    CompositeAgentRunResult,
    CompositeAgentStoryFactDelta,
    GateReviewRequest,
)
from app.backend.models.composite_integrator import (
    COMPOSITE_CANDIDATE_TRUTH_STATUSES,
    PHASE85C_M2_INTEGRATOR_GATE_PIPELINE_VERSION,
    CompositeCandidateItem,
    CompositeCandidatePool,
    CompositeConflictGroup,
    CompositeIntegratedOutputBundle,
    CompositeIntegratorReport,
)
from app.backend.services.model_runtime_log_service import utc_now


UNSAFE_SAFE_SUMMARY_MARKERS = {
    "raw_prompt",
    "raw response",
    "raw_response",
    "hidden_reasoning",
    "internal_reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
}

DIRECT_WRITE_MARKERS = {
    "active_memory_write",
    "confirmed_event",
    "committed_fact",
    "state_change_write",
    "relationship_write",
    "scene_prose_mutation",
    "user_confirmation_accepted",
    "resolved_continuity_issue",
    "narrative_debt_payoff",
}


class CompositeIntegratorService:
    """Normalizes M1 CompositeAgentRunResult candidates into a dry-review bundle."""

    def normalize_inputs(
        self,
        run_result: CompositeAgentRunResult,
    ) -> CompositeCandidatePool:
        timestamp = utc_now()
        candidates: list[CompositeCandidateItem] = []
        for index, trace in enumerate(run_result.sub_agent_traces):
            payload = model_to_dict(trace)
            payload.update(
                {
                    "candidate_id": f"{run_result.run_id}_trace_{index + 1:03d}",
                    "run_id": run_result.run_id,
                    "agent_name": run_result.agent_name,
                    "source_sub_agent_trace_id": trace.input_fingerprint
                    or f"{trace.sub_agent_name}_{index + 1:03d}",
                    "source_object_type": trace.node_kind,
                    "source_object_id": trace.input_fingerprint,
                    "semantic_key": trace.input_fingerprint
                    or f"{trace.sub_agent_name}:{trace.node_kind}",
                    "safe_summary": trace.output_summary,
                    "evidence_refs": trace.source_ids,
                    "target_scope": "",
                    "tier": "",
                    "budget_scope": "sub_agent_trace",
                    "truth_status": _truth_status_for_output_type(trace.output_type),
                    "candidate_only": True,
                    "can_write_story_facts_directly": False,
                    "created_at": trace.created_at or timestamp,
                }
            )
            candidates.append(self._candidate_from_payload(payload, index=index))

        for index, payload in enumerate(run_result.candidate_outputs):
            if not isinstance(payload, dict):
                payload = {
                    "safe_summary": "Ignored non-object candidate output.",
                    "blocking_findings": ["invalid_candidate_payload_shape"],
                }
            candidates.append(
                self._candidate_from_payload(
                    {
                        **payload,
                        "run_id": run_result.run_id,
                        "agent_name": run_result.agent_name,
                    },
                    index=index + len(run_result.sub_agent_traces),
                )
            )

        return CompositeCandidatePool(
            candidate_pool_id=f"candidate_pool_{_short_hash(run_result.run_id)}",
            run_id=run_result.run_id,
            agent_name=run_result.agent_name,
            source_context_ids=run_result.output_refs,
            candidates=candidates,
            input_candidate_count=len(candidates),
            safe_summary="Composite Integrator normalized M1 candidate outputs for dry review.",
            warnings=run_result.warnings,
            created_at=timestamp,
        )

    def dedupe_candidates(
        self,
        pool: CompositeCandidatePool,
    ) -> tuple[list[CompositeCandidateItem], list[str]]:
        accepted: list[CompositeCandidateItem] = []
        seen: dict[tuple[str, str, str, str, str, str], str] = {}
        duplicate_ids: list[str] = []
        for candidate in pool.candidates:
            key = (
                candidate.semantic_key,
                candidate.source_object_type,
                candidate.source_object_id,
                candidate.truth_status,
                candidate.safe_summary,
                candidate.output_type,
            )
            if key in seen:
                duplicate_ids.append(candidate.candidate_id)
                continue
            seen[key] = candidate.candidate_id
            accepted.append(candidate)
        return accepted, _unique_strings(duplicate_ids)

    def group_conflicts(
        self,
        candidates: list[CompositeCandidateItem],
    ) -> list[CompositeConflictGroup]:
        by_semantic_key: dict[str, list[CompositeCandidateItem]] = {}
        for candidate in candidates:
            if not candidate.semantic_key:
                continue
            by_semantic_key.setdefault(candidate.semantic_key, []).append(candidate)

        conflicts: list[CompositeConflictGroup] = []
        for semantic_key, group in sorted(by_semantic_key.items()):
            if len(group) < 2:
                continue
            signatures = {
                (
                    candidate.safe_summary,
                    candidate.truth_status,
                    candidate.output_type,
                    bool(candidate.blocking_findings),
                    candidate.objective_fact_risk,
                )
                for candidate in group
            }
            if len(signatures) < 2:
                continue
            conflict_id = f"conflict_{_short_hash(semantic_key + ':' + ','.join(item.candidate_id for item in group))}"
            conflicts.append(
                CompositeConflictGroup(
                    conflict_group_id=conflict_id,
                    run_id=group[0].run_id,
                    agent_name=group[0].agent_name,
                    semantic_key=semantic_key,
                    candidate_ids=[item.candidate_id for item in group],
                    conflict_type="semantic_candidate_disagreement",
                    severity="warning",
                    requires_gate_review=True,
                    safe_summary="Composite Integrator found conflicting candidate interpretations for the same semantic key.",
                    warnings=["requires_gate_review_before_downstream_use"],
                )
            )
        return conflicts

    def build_integrated_bundle(
        self,
        run_result: CompositeAgentRunResult,
    ) -> CompositeIntegratedOutputBundle:
        pool = self.normalize_inputs(run_result)
        candidates, duplicate_ids = self.dedupe_candidates(pool)
        conflicts = self.group_conflicts(candidates)
        gate_requests = self._gate_review_requests(
            run_result=run_result,
            candidates=candidates,
            conflicts=conflicts,
        )
        evidence_refs: list[str] = []
        for candidate in candidates:
            evidence_refs.extend(candidate.evidence_refs)
            evidence_refs.extend(candidate.source_ids)
        warnings = _unique_strings(
            [
                *pool.warnings,
                *[f"deduped_candidate:{candidate_id}" for candidate_id in duplicate_ids],
            ]
        )
        blocking_findings = _unique_strings(
            finding
            for candidate in candidates
            for finding in candidate.blocking_findings
        )
        return CompositeIntegratedOutputBundle(
            bundle_id=f"bundle_{_short_hash(run_result.run_id + ':' + str(len(candidates)))}",
            run_id=run_result.run_id,
            agent_name=run_result.agent_name,
            target_scope=next(
                (candidate.target_scope for candidate in candidates if candidate.target_scope),
                "scene",
            ),
            integrated_candidates=candidates,
            evidence_refs=evidence_refs,
            conflict_groups=conflicts,
            gate_review_requests=gate_requests,
            requires_gate_review=bool(conflicts or gate_requests or blocking_findings),
            requires_user_confirmation_candidate=any(
                "user_confirmation" in finding
                for candidate in candidates
                for finding in candidate.blocking_findings + candidate.warnings
            ),
            candidate_only=True,
            can_write_story_facts_directly=False,
            authority_level="candidate",
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "Composite Integrator produced a candidate-only bundle for gate pipeline dry review."
            ),
            warnings=warnings,
            blocking_findings=blocking_findings,
            created_at=utc_now(),
        )

    def build_integrator_report(
        self,
        *,
        run_result: CompositeAgentRunResult,
        bundle: CompositeIntegratedOutputBundle,
    ) -> CompositeIntegratorReport:
        accepted = bundle.integrated_candidates
        confidence_values = [candidate.confidence for candidate in accepted]
        source_trace_ids = [
            candidate.source_sub_agent_trace_id
            for candidate in accepted
            if candidate.source_sub_agent_trace_id
        ]
        return CompositeIntegratorReport(
            integrator_report_id=f"integrator_report_{_short_hash(bundle.bundle_id)}",
            run_id=run_result.run_id,
            agent_name=run_result.agent_name,
            source_sub_agent_trace_ids=source_trace_ids,
            input_candidate_count=len(run_result.sub_agent_traces)
            + len(run_result.candidate_outputs),
            accepted_candidate_count=len(accepted),
            deduped_candidate_count=max(
                0,
                len(run_result.sub_agent_traces)
                + len(run_result.candidate_outputs)
                - len(accepted),
            ),
            rejected_candidate_count=0,
            conflict_group_count=len(bundle.conflict_groups),
            confidence_summary=_confidence_summary(confidence_values),
            budget_summary=_budget_summary(accepted),
            authority_summary=_authority_summary(accepted),
            warnings=bundle.warnings,
            blocking_findings=bundle.blocking_findings,
            safe_summary="Composite Integrator report summarizes normalized candidate-only outputs.",
            created_at=utc_now(),
        )

    def _candidate_from_payload(
        self,
        payload: dict[str, Any],
        *,
        index: int,
    ) -> CompositeCandidateItem:
        now = utc_now()
        findings = _unique_strings(_as_list(payload.get("blocking_findings")))
        warnings = _unique_strings(_as_list(payload.get("warnings")))
        output_type = str(payload.get("output_type") or "candidate").strip()
        if output_type in COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES:
            findings.append(f"unsafe_output_type:{output_type}")
            output_type = "warning"
        elif output_type not in COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES:
            findings.append(f"unknown_output_type:{output_type}")
            output_type = "warning"

        authority_level = str(payload.get("authority_level") or "candidate").strip()
        if authority_level not in COMPOSITE_AGENT_AUTHORITY_LEVELS:
            findings.append(f"unknown_authority_level:{authority_level}")
            authority_level = "candidate"
        elif authority_level in {"user_confirmed", "committed"}:
            findings.append(f"unsafe_authority_claim:{authority_level}")
            authority_level = "candidate"

        if payload.get("can_write_story_facts_directly") is True:
            findings.append("direct_story_fact_write_claim")
        if payload.get("candidate_only") is False:
            findings.append("non_candidate_output_claim")

        truth_status = str(payload.get("truth_status") or "unknown").strip() or "unknown"
        if truth_status not in COMPOSITE_CANDIDATE_TRUTH_STATUSES:
            findings.append(f"unknown_truth_status:{truth_status}")
            truth_status = "unknown"

        source_object_type = str(payload.get("source_object_type") or payload.get("node_kind") or "").strip()
        source_object_id = str(payload.get("source_object_id") or payload.get("input_fingerprint") or "").strip()
        semantic_key = str(payload.get("semantic_key") or "").strip()
        if not semantic_key:
            semantic_key = _semantic_key(payload, source_object_type, source_object_id)

        candidate_id = str(payload.get("candidate_id") or "").strip()
        if not candidate_id:
            candidate_id = f"{payload.get('run_id', 'run')}_candidate_{index + 1:03d}_{_short_hash(semantic_key)}"

        summary, summary_findings = _safe_summary(payload.get("safe_summary") or payload.get("output_summary") or "")
        findings.extend(summary_findings)

        for marker in DIRECT_WRITE_MARKERS:
            if payload.get(marker) is True or marker in _normalized_marker_text(payload):
                findings.append(marker)

        return CompositeCandidateItem(
            candidate_id=candidate_id,
            run_id=str(payload.get("run_id") or "").strip(),
            agent_name=str(payload.get("agent_name") or "").strip(),
            source_sub_agent_trace_id=str(
                payload.get("source_sub_agent_trace_id")
                or payload.get("input_fingerprint")
                or ""
            ).strip(),
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            semantic_key=semantic_key,
            output_type=output_type,
            target_scope=str(payload.get("target_scope") or "").strip(),
            tier=str(payload.get("tier") or "").strip(),
            budget_scope=str(payload.get("budget_scope") or "").strip(),
            authority_level=authority_level,
            candidate_only=True,
            can_write_story_facts_directly=False,
            truth_status=truth_status,
            objective_fact_risk=bool(payload.get("objective_fact_risk")),
            confidence=_safe_confidence(payload.get("confidence")),
            evidence_refs=payload.get("evidence_refs") or payload.get("source_ids") or [],
            source_ids=payload.get("source_ids") or [],
            warnings=warnings,
            blocking_findings=findings,
            safe_summary=summary,
            created_at=str(payload.get("created_at") or now),
        )

    def _gate_review_requests(
        self,
        *,
        run_result: CompositeAgentRunResult,
        candidates: list[CompositeCandidateItem],
        conflicts: list[CompositeConflictGroup],
    ) -> list[GateReviewRequest]:
        requests: list[GateReviewRequest] = []
        for conflict in conflicts:
            requests.append(
                GateReviewRequest(
                    gate_review_request_id=f"gate_request_{conflict.conflict_group_id}",
                    agent_name=run_result.agent_name,
                    requested_gates=[
                        "ContinuityGateAdapter",
                        "ApparentContradictionGateAdapter",
                        "QualityGateAdapter",
                    ],
                    candidate_output_refs=conflict.candidate_ids,
                    reason="conflicting_candidate_outputs_require_gate_review",
                    does_not_mark_gate_passed=True,
                    candidate_only=True,
                    safe_summary=conflict.safe_summary,
                )
            )
        for candidate in candidates:
            if not (candidate.blocking_findings or candidate.objective_fact_risk):
                continue
            requests.append(
                GateReviewRequest(
                    gate_review_request_id=f"gate_request_{candidate.candidate_id}",
                    agent_name=run_result.agent_name,
                    requested_gates=[
                        "NoWriteGuard",
                        "ObjectiveFactBoundaryGate",
                        "QualityGateAdapter",
                    ],
                    candidate_output_refs=[candidate.candidate_id],
                    reason="candidate_requires_safety_review",
                    does_not_mark_gate_passed=True,
                    candidate_only=True,
                    safe_summary="Candidate requires dry-review before downstream use.",
                )
            )
        return requests


def model_to_dict(model: Any) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()
    return dict(model or {})


def _safe_summary(value: Any) -> tuple[str, list[str]]:
    text = str(value or "").strip()
    findings: list[str] = []
    lowered = text.casefold()
    for marker in UNSAFE_SAFE_SUMMARY_MARKERS:
        if marker in lowered:
            findings.append(f"unsafe_safe_summary_marker:{marker}")
    if not text:
        text = "Composite candidate provided no safe summary."
        findings.append("missing_safe_summary")
    if findings:
        text = "Composite candidate summary redacted for safety review."
    return text[:500], findings


def _normalized_marker_text(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()
    except TypeError:
        return str(payload).casefold()


def _semantic_key(
    payload: dict[str, Any],
    source_object_type: str,
    source_object_id: str,
) -> str:
    raw = source_object_id or str(payload.get("safe_summary") or payload.get("output_summary") or "")
    prefix = source_object_type or str(payload.get("output_type") or "candidate")
    return f"{prefix}:{_short_hash(raw)}"


def _truth_status_for_output_type(output_type: str) -> str:
    mapping = {
        "evidence": "evidence",
        "warning": "warning",
        "constraint_hint": "constraint_hint",
        "gate_request": "warning",
        "writer_input_candidate": "unknown",
        "memory_reference": "evidence",
        "candidate": "unknown",
    }
    return mapping.get(output_type, "unknown")


def _safe_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, number))


def _confidence_summary(values: list[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "min": None, "max": None, "average": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "average": round(sum(values) / len(values), 4),
    }


def _budget_summary(candidates: list[CompositeCandidateItem]) -> dict[str, object]:
    by_tier: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    by_budget_scope: dict[str, int] = {}
    for candidate in candidates:
        by_tier[candidate.tier or "unspecified"] = by_tier.get(candidate.tier or "unspecified", 0) + 1
        by_scope[candidate.target_scope or "unspecified"] = (
            by_scope.get(candidate.target_scope or "unspecified", 0) + 1
        )
        by_budget_scope[candidate.budget_scope or "unspecified"] = (
            by_budget_scope.get(candidate.budget_scope or "unspecified", 0) + 1
        )
    return {
        "by_tier": dict(sorted(by_tier.items())),
        "by_target_scope": dict(sorted(by_scope.items())),
        "by_budget_scope": dict(sorted(by_budget_scope.items())),
    }


def _authority_summary(candidates: list[CompositeCandidateItem]) -> dict[str, object]:
    by_authority: dict[str, int] = {}
    downgrade_findings: list[str] = []
    for candidate in candidates:
        by_authority[candidate.authority_level] = (
            by_authority.get(candidate.authority_level, 0) + 1
        )
        downgrade_findings.extend(
            finding
            for finding in candidate.blocking_findings
            if finding.startswith("unsafe_authority_claim")
        )
    return {
        "by_authority_level": dict(sorted(by_authority.items())),
        "authority_downgrade_findings": _unique_strings(downgrade_findings),
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique_strings(values: Any) -> list[str]:
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


def _short_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]
