import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.character_intent import (
    CharacterActionIntentionCandidate,
    CharacterIntentPackageBuildResponse,
    CharacterIntentRiskReport,
    CharacterPsychologyTraceRuntimeMeta,
)
from app.backend.models.composite_agent import (
    PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION,
    CompositeAgentRunRequest,
    CompositeAgentRunResult,
    CompositeAgentRunTrace,
    CompositeAgentStoryFactDelta,
    GateReviewReceipt,
    IntegratorReport,
    SubAgentTrace,
)
from app.backend.models.composite_gate import CompositeGatePipelineResult
from app.backend.models.composite_integrator import (
    CompositeIntegratedOutputBundle,
    CompositeIntegratorReport,
)
from app.backend.models.narrative_layer import CharacterPsychologyTrace
from app.backend.models.scene_participation import SceneParticipationPackage
from app.backend.services.character_intent_service import (
    SCENE_PARTICIPATION_PACKAGES_FILE,
    TieredCharacterIntentPackageService,
)
from app.backend.services.composite_agent_registry_service import (
    COMPOSITE_AGENT_OUTPUT_CONTRACT_ID,
    CompositeAgentRegistryService,
)
from app.backend.services.composite_gate_pipeline_service import (
    CompositeGatePipelineService,
)
from app.backend.services.composite_integrator_service import (
    CompositeIntegratorService,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


CHARACTER_INTENT_COMPOSITE_AGENT_NAME = "CharacterPsychologyActionIntentAgent"
CHARACTER_INTENT_COMPOSITE_WRAPPER_VERSION = (
    "phase85c_m3_character_intent_composite_agent_v1"
)

SUB_AGENT_TRACE_ORDER = [
    "MemoryRetrievalSubAgent",
    "DesireFearSubAgent",
    "RelationshipPressureSubAgent",
    "ScenePerceptionSubAgent",
    "InnerConflictSubAgent",
    "ActionIntentionSubAgent",
    "RiskClassificationSubAgent",
    "GateRequestBuilderSubAgent",
]


class CharacterPsychologyActionIntentAgentService:
    """M3 candidate-only Composite Agent wrapper around the M6 intent package service."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        registry_service: CompositeAgentRegistryService | None = None,
        character_intent_service: TieredCharacterIntentPackageService | None = None,
        integrator_service: CompositeIntegratorService | None = None,
        gate_pipeline_service: CompositeGatePipelineService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.registry_service = registry_service or CompositeAgentRegistryService()
        self.character_intent_service = character_intent_service or (
            TieredCharacterIntentPackageService(store=self.store, data_dir=self.data_dir)
        )
        self.integrator_service = integrator_service or CompositeIntegratorService()
        self.gate_pipeline_service = gate_pipeline_service or CompositeGatePipelineService()
        self.scene_participation_file = self.data_dir / SCENE_PARTICIPATION_PACKAGES_FILE

        self.last_scene_participation_package_id = ""
        self.last_scene_participation_package: SceneParticipationPackage | None = None
        self.last_m6_response: CharacterIntentPackageBuildResponse | None = None
        self.last_preliminary_result: CompositeAgentRunResult | None = None
        self.last_integrated_bundle: CompositeIntegratedOutputBundle | None = None
        self.last_integrator_report: CompositeIntegratorReport | None = None
        self.last_gate_pipeline_result: CompositeGatePipelineResult | None = None

    def run(
        self,
        request: CompositeAgentRunRequest,
    ) -> CompositeAgentRunResult:
        normalized_request = self.normalize_and_validate_request(request)
        scene_participation = self.resolve_scene_participation_package(
            normalized_request
        )
        response = self.character_intent_service.build_response(
            scene_participation.scene_participation_package_id,
            force_refresh=False,
        )
        traces = self._project_sub_agent_traces(
            request=normalized_request,
            scene_participation=scene_participation,
            response=response,
        )
        candidate_outputs = self._project_candidate_outputs(
            request=normalized_request,
            response=response,
        )
        preliminary = self._build_preliminary_result(
            request=normalized_request,
            scene_participation=scene_participation,
            response=response,
            traces=traces,
            candidate_outputs=candidate_outputs,
        )
        bundle = self.integrator_service.build_integrated_bundle(preliminary)
        detailed_integrator_report = self.integrator_service.build_integrator_report(
            run_result=preliminary,
            bundle=bundle,
        )
        gate_pipeline_result = self.gate_pipeline_service.run_dry_review(bundle)
        final = self._build_final_result(
            request=normalized_request,
            scene_participation=scene_participation,
            response=response,
            preliminary=preliminary,
            bundle=bundle,
            detailed_integrator_report=detailed_integrator_report,
            gate_pipeline_result=gate_pipeline_result,
        )

        self.last_scene_participation_package_id = (
            scene_participation.scene_participation_package_id
        )
        self.last_scene_participation_package = scene_participation
        self.last_m6_response = response
        self.last_preliminary_result = preliminary
        self.last_integrated_bundle = bundle
        self.last_integrator_report = detailed_integrator_report
        self.last_gate_pipeline_result = gate_pipeline_result
        return final

    def normalize_and_validate_request(
        self,
        request: CompositeAgentRunRequest,
    ) -> CompositeAgentRunRequest:
        normalized = self.registry_service.normalize_run_request(request)
        if normalized.agent_name != CHARACTER_INTENT_COMPOSITE_AGENT_NAME:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_WRONG_AGENT")
        if not normalized.dry_run:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_DRY_RUN_REQUIRED")
        if normalized.requested_authority_level not in {"read_only", "candidate"}:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_UNSAFE_AUTHORITY_LEVEL")
        if not str(normalized.project_id or "").strip():
            raise StorageError("COMPOSITE_CHARACTER_INTENT_PROJECT_ID_REQUIRED")
        if (
            normalized.requested_output_contract_id
            and normalized.requested_output_contract_id != COMPOSITE_AGENT_OUTPUT_CONTRACT_ID
        ):
            raise StorageError("COMPOSITE_CHARACTER_INTENT_OUTPUT_CONTRACT_MISMATCH")
        return normalized

    def resolve_scene_participation_package(
        self,
        request: CompositeAgentRunRequest,
    ) -> SceneParticipationPackage:
        packages = self._read_scene_participation_packages()
        by_id = {package.scene_participation_package_id: package for package in packages}
        for ref in [*request.input_refs, *request.source_context_ids]:
            package = by_id.get(str(ref or "").strip())
            if package is not None:
                return self._assert_resolved_package(request, package)

        candidates = [
            package
            for package in packages
            if package.project_id == request.project_id
            and package.chapter_id == request.chapter_id
            and int(package.scene_index or 0) == int(request.scene_index or 0)
        ]
        candidates.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
        if not candidates:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_SCENE_PARTICIPATION_NOT_FOUND")
        return self._assert_resolved_package(request, candidates[0])

    def build_run_trace(
        self,
        *,
        request: CompositeAgentRunRequest,
        result: CompositeAgentRunResult,
    ) -> CompositeAgentRunTrace:
        return CompositeAgentRunTrace(
            run_trace_id=f"trace_{result.run_id}",
            run_id=result.run_id,
            agent_name=result.agent_name,
            version_id=CHARACTER_INTENT_COMPOSITE_WRAPPER_VERSION,
            source_context_ids=request.source_context_ids,
            input_refs=request.input_refs,
            sub_agent_traces=result.sub_agent_traces,
            integrator_report=result.integrator_report,
            gate_review_requests=result.gate_review_requests,
            gate_review_receipts=result.gate_review_receipts,
            authority_level=result.authority_level,
            candidate_only=True,
            can_write_story_facts_directly=False,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "Character intent composite wrapper produced a dry-run trace."
            ),
            warnings=result.warnings,
            created_at=utc_now(),
        )

    def _assert_resolved_package(
        self,
        request: CompositeAgentRunRequest,
        package: SceneParticipationPackage,
    ) -> SceneParticipationPackage:
        if package.project_id != request.project_id:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_PROJECT_MISMATCH")
        if (
            str(request.chapter_id or "").strip()
            and package.chapter_id != request.chapter_id
        ):
            raise StorageError("COMPOSITE_CHARACTER_INTENT_CHAPTER_MISMATCH")
        if str(request.scene_id or "").strip() and package.scene_id != request.scene_id:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_SCENE_MISMATCH")
        if (
            int(request.scene_index or 0) > 0
            and int(package.scene_index or 0) != int(request.scene_index or 0)
        ):
            raise StorageError("COMPOSITE_CHARACTER_INTENT_SCENE_INDEX_MISMATCH")
        if package.status not in {"ready", "warning"}:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_SCENE_PARTICIPATION_UNRESOLVED")
        if not package.active_character_ids:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_ACTIVE_CHARACTERS_REQUIRED")
        return package

    def _read_scene_participation_packages(self) -> list[SceneParticipationPackage]:
        if not self.store.exists(self.scene_participation_file):
            raise StorageError("COMPOSITE_CHARACTER_INTENT_SCENE_PARTICIPATION_STORAGE_MISSING")
        raw = self.store.read_any(self.scene_participation_file)
        rows: list[Any]
        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, dict):
            rows = (
                raw.get("packages")
                or raw.get("scene_participation_packages")
                or raw.get("items")
                or []
            )
        else:
            rows = []
        packages = [
            SceneParticipationPackage(**row)
            for row in rows
            if isinstance(row, dict)
        ]
        if not packages:
            raise StorageError("COMPOSITE_CHARACTER_INTENT_SCENE_PARTICIPATION_EMPTY")
        return packages

    def _project_sub_agent_traces(
        self,
        *,
        request: CompositeAgentRunRequest,
        scene_participation: SceneParticipationPackage,
        response: CharacterIntentPackageBuildResponse,
    ) -> list[SubAgentTrace]:
        now = utc_now()
        meta_by_trace_id = {
            meta.psychology_trace_id: meta
            for meta in response.psychology_trace_runtime_meta
        }
        trace_ids = [trace.psychology_trace_id for trace in response.psychology_traces]
        candidate_ids = [
            candidate.action_intention_candidate_id
            for candidate in response.action_intention_candidates
        ]
        risk_ids = [report.risk_report_id for report in response.risk_reports]
        memory_refs = self._unique(
            [
                scene_participation.scene_memory_pack_id,
                response.package.scene_memory_pack_id,
                response.package.chapter_memory_pack_id,
                *[
                    memory_id
                    for meta in response.psychology_trace_runtime_meta
                    for memory_id in meta.source_memory_ids
                ],
                *[
                    context_id
                    for meta in response.psychology_trace_runtime_meta
                    for context_id in meta.source_context_item_ids
                ],
            ]
        )
        trace_specs = [
            (
                "MemoryRetrievalSubAgent",
                "memory_retrieval_projection",
                "memory_reference",
                "read_only",
                memory_refs,
                "M6 runtime memory references were projected as read-only evidence.",
            ),
            (
                "DesireFearSubAgent",
                "desire_fear_projection",
                "candidate",
                "candidate",
                trace_ids,
                "M6 psychology traces were projected into desire/fear candidates.",
            ),
            (
                "RelationshipPressureSubAgent",
                "relationship_pressure_projection",
                "candidate",
                "candidate",
                trace_ids,
                "M6 psychology traces were projected into relationship pressure candidates.",
            ),
            (
                "ScenePerceptionSubAgent",
                "scene_perception_projection",
                "constraint_hint",
                "candidate",
                self._unique(
                    [
                        scene_participation.scene_participation_package_id,
                        *memory_refs,
                    ]
                ),
                "Scene participation and memory context were projected as constraint hints.",
            ),
            (
                "InnerConflictSubAgent",
                "inner_conflict_projection",
                "candidate",
                "candidate",
                trace_ids,
                "M6 psychology traces were projected into inner-conflict candidates.",
            ),
            (
                "ActionIntentionSubAgent",
                "action_intention_projection",
                "writer_input_candidate",
                "candidate",
                candidate_ids,
                "M6 action intentions were projected as writer-input candidates.",
            ),
            (
                "RiskClassificationSubAgent",
                "risk_classification_projection",
                "gate_request" if self._has_gate_risk(response.risk_reports) else "warning",
                "candidate",
                risk_ids,
                "M6 risk reports were projected into gate-review signals.",
            ),
            (
                "GateRequestBuilderSubAgent",
                "gate_request_projection",
                "gate_request",
                "candidate",
                self._unique([*candidate_ids, *risk_ids]),
                "M6 risk reports were converted into candidate-only gate requests.",
            ),
        ]
        result: list[SubAgentTrace] = []
        for order, (
            sub_agent_name,
            node_kind,
            output_type,
            authority_level,
            source_ids,
            summary,
        ) in enumerate(trace_specs, start=1):
            if sub_agent_name in {
                "DesireFearSubAgent",
                "RelationshipPressureSubAgent",
                "InnerConflictSubAgent",
            }:
                source_ids = self._trace_ids_with_meta(trace_ids, meta_by_trace_id)
            result.append(
                SubAgentTrace(
                    sub_agent_name=sub_agent_name,
                    node_kind=node_kind,
                    output_type=output_type,
                    authority_level=authority_level,
                    confidence=0.82,
                    source_ids=source_ids,
                    input_fingerprint=self._fingerprint(
                        request.run_id,
                        scene_participation.scene_participation_package_id,
                        sub_agent_name,
                        str(order),
                    ),
                    output_summary=summary,
                    warnings=[],
                    created_at=now,
                )
            )
        return result

    def _project_candidate_outputs(
        self,
        *,
        request: CompositeAgentRunRequest,
        response: CharacterIntentPackageBuildResponse,
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        meta_by_trace_id = {
            meta.psychology_trace_id: meta
            for meta in response.psychology_trace_runtime_meta
        }
        risk_by_candidate_id: dict[str, list[CharacterIntentRiskReport]] = {}
        for report in response.risk_reports:
            risk_by_candidate_id.setdefault(report.action_intention_candidate_id, []).append(report)

        for trace in response.psychology_traces:
            meta = meta_by_trace_id.get(trace.psychology_trace_id)
            outputs.append(
                self._trace_candidate_payload(
                    request=request,
                    trace=trace,
                    meta=meta,
                )
            )

        for candidate in response.action_intention_candidates:
            outputs.append(
                self._action_intention_candidate_payload(
                    request=request,
                    candidate=candidate,
                    risk_reports=risk_by_candidate_id.get(
                        candidate.action_intention_candidate_id,
                        [],
                    ),
                )
            )

        for report in response.risk_reports:
            outputs.append(self._risk_report_candidate_payload(request, report))

        outputs.append(
            {
                "candidate_id": f"{request.run_id}_m6_package_memory_refs",
                "source_sub_agent_trace_id": "MemoryRetrievalSubAgent",
                "source_object_type": "tiered_character_intent_package",
                "source_object_id": response.package.tiered_character_intent_package_id,
                "semantic_key": (
                    f"m6_package_memory_refs:{response.package.scene_participation_package_id}"
                ),
                "output_type": "memory_reference",
                "target_scope": request.target_scope,
                "tier": "package",
                "budget_scope": "memory_reference",
                "authority_level": "read_only",
                "candidate_only": True,
                "can_write_story_facts_directly": False,
                "truth_status": "evidence",
                "objective_fact_risk": False,
                "confidence": 0.84,
                "evidence_refs": self._unique(
                    [
                        response.package.scene_memory_pack_id,
                        response.package.chapter_memory_pack_id,
                    ]
                ),
                "source_ids": self._unique(
                    [
                        response.package.tiered_character_intent_package_id,
                        response.package.scene_participation_package_id,
                    ]
                ),
                "warnings": [],
                "blocking_findings": [],
                "safe_summary": (
                    "M6 character-intent package exposes memory refs as read-only evidence."
                ),
            }
        )
        return outputs

    def _trace_candidate_payload(
        self,
        *,
        request: CompositeAgentRunRequest,
        trace: CharacterPsychologyTrace,
        meta: CharacterPsychologyTraceRuntimeMeta | None,
    ) -> dict[str, Any]:
        trace_id = trace.psychology_trace_id
        tier = meta.tier if meta is not None else ""
        source_refs = self._unique(
            [
                trace_id,
                meta.runtime_meta_id if meta is not None else "",
                *([] if meta is None else meta.source_memory_ids),
                *([] if meta is None else meta.source_context_item_ids),
            ]
        )
        return {
            "candidate_id": f"{request.run_id}_psychology_{self._safe_id(trace_id)}",
            "source_sub_agent_trace_id": "DesireFearSubAgent",
            "source_object_type": "character_psychology_trace",
            "source_object_id": trace_id,
            "semantic_key": f"psychology_trace:{trace.character_id}:{trace_id}",
            "output_type": "candidate",
            "target_scope": request.target_scope,
            "tier": tier,
            "budget_scope": "character_psychology_trace",
            "authority_level": "candidate",
            "candidate_only": True,
            "can_write_story_facts_directly": False,
            "truth_status": "psychology_trace",
            "objective_fact_risk": False,
            "confidence": trace.confidence or 0.72,
            "evidence_refs": source_refs,
            "source_ids": source_refs,
            "warnings": [],
            "blocking_findings": [],
            "safe_summary": (
                f"Character {trace.character_id} has candidate psychology trace at tier {tier or 'unknown'}."
            ),
        }

    def _action_intention_candidate_payload(
        self,
        *,
        request: CompositeAgentRunRequest,
        candidate: CharacterActionIntentionCandidate,
        risk_reports: list[CharacterIntentRiskReport],
    ) -> dict[str, Any]:
        warning_refs = self._unique(
            [
                *candidate.warnings,
                *[
                    f"gate:{gate}"
                    for report in risk_reports
                    for gate in report.recommended_next_gates
                    if gate != "none"
                ],
                *[
                    "user_confirmation_candidate"
                    for report in risk_reports
                    if "user_confirmation_candidate" in report.recommended_next_gates
                ],
            ]
        )
        source_refs = self._unique(
            [
                candidate.action_intention_candidate_id,
                candidate.psychology_trace_id,
                candidate.scene_participation_package_id,
                candidate.tiered_character_context_package_id,
                candidate.scene_memory_pack_id,
                *[report.risk_report_id for report in risk_reports],
            ]
        )
        truth_status = self._truth_status_for_action_candidate(candidate.truth_status)
        return {
            "candidate_id": f"{request.run_id}_intent_{self._safe_id(candidate.action_intention_candidate_id)}",
            "source_sub_agent_trace_id": "ActionIntentionSubAgent",
            "source_object_type": "character_action_intention_candidate",
            "source_object_id": candidate.action_intention_candidate_id,
            "semantic_key": (
                f"action_intention:{candidate.character_id}:{candidate.intention_type}:"
                f"{candidate.action_intention_candidate_id}"
            ),
            "output_type": "writer_input_candidate",
            "target_scope": request.target_scope,
            "tier": candidate.tier,
            "budget_scope": "writer_input_candidate",
            "authority_level": "candidate",
            "candidate_only": True,
            "can_write_story_facts_directly": False,
            "truth_status": truth_status,
            "objective_fact_risk": False,
            "confidence": 0.72,
            "evidence_refs": source_refs,
            "source_ids": source_refs,
            "warnings": warning_refs,
            "blocking_findings": [],
            "safe_summary": (
                f"Character {candidate.character_id} has candidate action intention "
                f"{candidate.intention_type} for writer input."
            ),
        }

    def _risk_report_candidate_payload(
        self,
        request: CompositeAgentRunRequest,
        report: CharacterIntentRiskReport,
    ) -> dict[str, Any]:
        gate_refs = [gate for gate in report.recommended_next_gates if gate != "none"]
        return {
            "candidate_id": f"{request.run_id}_risk_{self._safe_id(report.risk_report_id)}",
            "source_sub_agent_trace_id": "RiskClassificationSubAgent",
            "source_object_type": "character_intent_risk_report",
            "source_object_id": report.risk_report_id,
            "semantic_key": f"risk_report:{report.action_intention_candidate_id}",
            "output_type": "gate_request" if gate_refs else "warning",
            "target_scope": request.target_scope,
            "tier": report.tier,
            "budget_scope": "gate_request",
            "authority_level": "candidate",
            "candidate_only": True,
            "can_write_story_facts_directly": False,
            "truth_status": "warning",
            "objective_fact_risk": False,
            "confidence": 0.72,
            "evidence_refs": self._unique(
                [report.risk_report_id, report.action_intention_candidate_id]
            ),
            "source_ids": self._unique(
                [report.risk_report_id, report.action_intention_candidate_id]
            ),
            "warnings": self._unique(
                [
                    f"risk_level:{report.risk_level}",
                    *[f"risk_category:{item}" for item in report.risk_categories],
                    *[f"gate:{gate}" for gate in gate_refs],
                    *report.warnings,
                ]
            ),
            "blocking_findings": [],
            "safe_summary": (
                f"Risk report for {report.action_intention_candidate_id} requests "
                f"{', '.join(gate_refs) if gate_refs else 'no extra gate'}."
            ),
        }

    def _build_preliminary_result(
        self,
        *,
        request: CompositeAgentRunRequest,
        scene_participation: SceneParticipationPackage,
        response: CharacterIntentPackageBuildResponse,
        traces: list[SubAgentTrace],
        candidate_outputs: list[dict[str, Any]],
    ) -> CompositeAgentRunResult:
        return CompositeAgentRunResult(
            run_id=request.run_id,
            agent_name=request.agent_name,
            status="candidate_ready_for_gate_review",
            authority_level=request.requested_authority_level,
            candidate_only=True,
            can_write_story_facts_directly=False,
            sub_agent_traces=traces,
            integrator_report=None,
            gate_review_requests=[],
            gate_review_receipts=[],
            candidate_outputs=candidate_outputs,
            output_refs=self._unique(
                [
                    scene_participation.scene_participation_package_id,
                    response.package.tiered_character_intent_package_id,
                    response.package.scene_memory_pack_id,
                    response.package.chapter_memory_pack_id,
                ]
            ),
            blocking_findings=[],
            warnings=response.warnings,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "Character intent composite wrapper projected M6 runtime artifacts "
                "into candidate-only composite outputs."
            ),
            created_at=utc_now(),
        )

    def _build_final_result(
        self,
        *,
        request: CompositeAgentRunRequest,
        scene_participation: SceneParticipationPackage,
        response: CharacterIntentPackageBuildResponse,
        preliminary: CompositeAgentRunResult,
        bundle: CompositeIntegratedOutputBundle,
        detailed_integrator_report: CompositeIntegratorReport,
        gate_pipeline_result: CompositeGatePipelineResult,
    ) -> CompositeAgentRunResult:
        integrator_report = IntegratorReport(
            integrator_report_id=f"m3_integrator_{self._short_hash(bundle.bundle_id)}",
            agent_name=request.agent_name,
            merged_output_types=self._unique(
                [candidate.output_type for candidate in bundle.integrated_candidates]
            ),
            source_trace_ids=[
                trace.input_fingerprint for trace in preliminary.sub_agent_traces
            ],
            conflict_categories=[
                conflict.conflict_type for conflict in bundle.conflict_groups
            ],
            confidence=self._average_confidence(bundle),
            candidate_only=True,
            can_write_story_facts_directly=False,
            safe_summary=(
                "M3 wrapper integrated M6 character-intent outputs through M2 dry review."
            ),
            warnings=self._unique(
                [
                    *bundle.warnings,
                    *detailed_integrator_report.warnings,
                    *gate_pipeline_result.warnings,
                ]
            ),
        )
        gate_review_receipts = [
            GateReviewReceipt(
                gate_review_receipt_id=receipt.receipt_id,
                gate_name=receipt.gate_name,
                decision=receipt.decision,
                source_request_id=(
                    receipt.source_receipt_ids[0]
                    if receipt.source_receipt_ids
                    else gate_pipeline_result.pipeline_result_id
                ),
                issued_by="phase85c_m2_gate_pipeline",
                does_not_commit_story_facts=True,
                safe_summary=receipt.safe_summary,
                warnings=receipt.warnings,
            )
            for receipt in gate_pipeline_result.gate_step_receipts
        ]
        blocking_findings = self._unique(
            [
                *bundle.blocking_findings,
                *[
                    finding.finding_code or finding.finding_type
                    for finding in gate_pipeline_result.blocking_findings
                ],
            ]
        )
        warnings = self._unique(
            [
                *response.warnings,
                *bundle.warnings,
                *gate_pipeline_result.warnings,
                f"m2_overall_decision:{gate_pipeline_result.overall_decision}",
            ]
        )
        status = (
            "blocked_by_gate_review"
            if gate_pipeline_result.hard_block
            else "candidate_gate_reviewed"
        )
        return CompositeAgentRunResult(
            run_id=request.run_id,
            agent_name=request.agent_name,
            status=status,
            authority_level=request.requested_authority_level,
            candidate_only=True,
            can_write_story_facts_directly=False,
            sub_agent_traces=preliminary.sub_agent_traces,
            integrator_report=integrator_report,
            gate_review_requests=bundle.gate_review_requests,
            gate_review_receipts=gate_review_receipts,
            candidate_outputs=preliminary.candidate_outputs,
            output_refs=self._unique(
                [
                    *preliminary.output_refs,
                    bundle.bundle_id,
                    detailed_integrator_report.integrator_report_id,
                    gate_pipeline_result.pipeline_result_id,
                    scene_participation.scene_participation_package_id,
                    response.package.tiered_character_intent_package_id,
                ]
            ),
            blocking_findings=blocking_findings,
            warnings=warnings,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "CharacterPsychologyActionIntentAgent wrapper completed a "
                "candidate-only M2 dry-review pass."
            ),
            created_at=utc_now(),
        )

    def _trace_ids_with_meta(
        self,
        trace_ids: list[str],
        meta_by_trace_id: dict[str, CharacterPsychologyTraceRuntimeMeta],
    ) -> list[str]:
        result: list[str] = []
        for trace_id in trace_ids:
            result.append(trace_id)
            meta = meta_by_trace_id.get(trace_id)
            if meta is not None:
                result.append(meta.runtime_meta_id)
        return self._unique(result)

    def _has_gate_risk(self, reports: list[CharacterIntentRiskReport]) -> bool:
        return any(
            report.risk_level in {"medium", "high", "blocking"}
            or any(gate != "none" for gate in report.recommended_next_gates)
            for report in reports
        )

    def _truth_status_for_action_candidate(self, value: str) -> str:
        if value in {"subjective_claim", "lie", "perception", "unknown"}:
            return value
        if value in {"misinformation"}:
            return "lie"
        return "intent"

    def _average_confidence(self, bundle: CompositeIntegratedOutputBundle) -> float:
        values = [candidate.confidence for candidate in bundle.integrated_candidates]
        if not values:
            return 1.0
        return round(sum(values) / len(values), 4)

    def _fingerprint(self, *parts: str) -> str:
        return f"m3_{self._short_hash(':'.join(str(part or '') for part in parts))}"

    def _short_hash(self, value: str) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]

    def _safe_id(self, value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value or ""))
        return safe[:90] or self._short_hash(value)

    def _unique(self, values: list[Any]) -> list[str]:
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


def model_to_dict(model: Any) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()
    return dict(model or {})
