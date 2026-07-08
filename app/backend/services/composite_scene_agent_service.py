import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.composite_agent import (
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
from app.backend.models.scene_participants import (
    SceneParticipantSelection,
    SceneParticipantSelectionRequest,
    SceneParticipantSelectionResponse,
)
from app.backend.models.scene_participation import (
    SceneParticipationPackage,
    SceneParticipationPrepareRequest,
    SceneParticipationPrepareResponse,
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
from app.backend.services.scene_participant_selection_service import (
    SceneParticipantSelectionService,
)
from app.backend.services.scene_participation_package_service import (
    SceneParticipationPackageService,
)
from app.backend.storage.json_store import JsonStore, StorageError


SCENE_AGENT_COMPOSITE_AGENT_NAME = "SceneAgent"
SCENE_AGENT_COMPOSITE_WRAPPER_VERSION = "phase85c_m4_sceneagent_composite_wrapper_v1"

SUB_AGENT_TRACE_ORDER = [
    "SceneFunctionSubAgent",
    "ABParticipantCarryoverSubAgent",
    "CDRoleFunctionNeedSubAgent",
    "CDRoleRetrievalSubAgent",
    "CDCandidateProposalSubAgent",
    "SceneParticipationAssemblerSubAgent",
    "TieredContextAdapterSubAgent",
    "GateRequestBuilderSubAgent",
]


class SceneAgentCompositeService:
    """M4 candidate-only Composite Agent wrapper for scene participation context."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        registry_service: CompositeAgentRegistryService | None = None,
        selection_service: SceneParticipantSelectionService | None = None,
        participation_service: SceneParticipationPackageService | None = None,
        integrator_service: CompositeIntegratorService | None = None,
        gate_pipeline_service: CompositeGatePipelineService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.registry_service = registry_service or CompositeAgentRegistryService()
        self.selection_service = selection_service or SceneParticipantSelectionService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.participation_service = (
            participation_service
            or SceneParticipationPackageService(
                store=self.store,
                data_dir=self.data_dir,
                selection_service=self.selection_service,
            )
        )
        self.integrator_service = integrator_service or CompositeIntegratorService()
        self.gate_pipeline_service = gate_pipeline_service or CompositeGatePipelineService()

        self.last_selection_response: SceneParticipantSelectionResponse | None = None
        self.last_participation_response: SceneParticipationPrepareResponse | None = None
        self.last_preliminary_result: CompositeAgentRunResult | None = None
        self.last_integrated_bundle: CompositeIntegratedOutputBundle | None = None
        self.last_integrator_report: CompositeIntegratorReport | None = None
        self.last_gate_pipeline_result: CompositeGatePipelineResult | None = None

    def run(self, request: CompositeAgentRunRequest) -> CompositeAgentRunResult:
        normalized_request = self.normalize_and_validate_request(request)
        selection_response, participation_response = self.resolve_scene_inputs(
            normalized_request
        )
        package = participation_response.package
        if package is None:
            raise StorageError("COMPOSITE_SCENE_AGENT_PACKAGE_NOT_FOUND")

        selection = selection_response.selection if selection_response else None
        traces = self._project_sub_agent_traces(
            request=normalized_request,
            selection=selection,
            selection_response=selection_response,
            participation_response=participation_response,
        )
        candidate_outputs = self._project_candidate_outputs(
            request=normalized_request,
            selection=selection,
            selection_response=selection_response,
            participation_response=participation_response,
        )
        preliminary = self._build_preliminary_result(
            request=normalized_request,
            package=package,
            traces=traces,
            candidate_outputs=candidate_outputs,
            warnings=participation_response.warnings,
        )
        bundle = self.integrator_service.build_integrated_bundle(preliminary)
        detailed_integrator_report = self.integrator_service.build_integrator_report(
            run_result=preliminary,
            bundle=bundle,
        )
        gate_pipeline_result = self.gate_pipeline_service.run_dry_review(bundle)
        final = self._build_final_result(
            request=normalized_request,
            package=package,
            preliminary=preliminary,
            bundle=bundle,
            detailed_integrator_report=detailed_integrator_report,
            gate_pipeline_result=gate_pipeline_result,
        )

        self.last_selection_response = selection_response
        self.last_participation_response = participation_response
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
        if normalized.agent_name != SCENE_AGENT_COMPOSITE_AGENT_NAME:
            raise StorageError("COMPOSITE_SCENE_AGENT_WRONG_AGENT")
        if not normalized.dry_run:
            raise StorageError("COMPOSITE_SCENE_AGENT_DRY_RUN_REQUIRED")
        if normalized.requested_authority_level not in {"read_only", "candidate"}:
            raise StorageError("COMPOSITE_SCENE_AGENT_UNSAFE_AUTHORITY_LEVEL")
        if not str(normalized.project_id or "").strip():
            raise StorageError("COMPOSITE_SCENE_AGENT_PROJECT_ID_REQUIRED")
        if not str(normalized.chapter_id or "").strip():
            raise StorageError("COMPOSITE_SCENE_AGENT_CHAPTER_ID_REQUIRED")
        if int(normalized.scene_index or 0) < 1:
            raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_INDEX_REQUIRED")
        if not str(normalized.scene_id or "").strip():
            raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_ID_REQUIRED")
        if (
            normalized.requested_output_contract_id
            and normalized.requested_output_contract_id != COMPOSITE_AGENT_OUTPUT_CONTRACT_ID
        ):
            raise StorageError("COMPOSITE_SCENE_AGENT_OUTPUT_CONTRACT_MISMATCH")
        return normalized

    def resolve_scene_inputs(
        self,
        request: CompositeAgentRunRequest,
    ) -> tuple[SceneParticipantSelectionResponse, SceneParticipationPrepareResponse]:
        refs = self._unique([*request.input_refs, *request.source_context_ids])

        for ref in refs:
            response = self._try_get_package(ref)
            if response and response.package:
                package = self._assert_resolved_package(request, response.package)
                self._assert_response_runtime_contract(response)
                selection_response = self._selection_response_for_package(package)
                return selection_response, response

        for ref in refs:
            selection_response = self._try_get_selection(ref)
            if selection_response and selection_response.selection:
                selection = self._assert_resolved_selection(
                    request,
                    selection_response.selection,
                )
                response = self._prepare_package(request)
                package = response.package
                if package is None:
                    raise StorageError("COMPOSITE_SCENE_AGENT_PACKAGE_NOT_FOUND")
                package = self._assert_resolved_package(request, package)
                if package.source_selection_id != selection.selection_id:
                    raise StorageError("COMPOSITE_SCENE_AGENT_SELECTION_PACKAGE_MISMATCH")
                self._assert_response_runtime_contract(response)
                return selection_response, response

        current = self.participation_service.get_current_package(
            chapter_id=request.chapter_id,
            scene_id=request.scene_id,
            scene_index=request.scene_index,
        )
        if current.package is not None:
            try:
                package = self._assert_resolved_package(request, current.package)
            except StorageError as exc:
                if "COMPOSITE_SCENE_AGENT_SCENE_MISMATCH" not in str(exc):
                    raise
            else:
                self._assert_response_runtime_contract(current)
                selection_response = self._selection_response_for_package(package)
                return selection_response, current

        response = self._prepare_package(request)
        if response.package is None:
            raise StorageError("COMPOSITE_SCENE_AGENT_PACKAGE_NOT_FOUND")
        package = self._assert_resolved_package(request, response.package)
        self._assert_response_runtime_contract(response)
        selection_response = self._selection_response_for_package(package)
        return selection_response, response

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
            version_id=SCENE_AGENT_COMPOSITE_WRAPPER_VERSION,
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
            safe_summary="SceneAgent composite wrapper produced a dry-run trace.",
            warnings=result.warnings,
            created_at=utc_now(),
        )

    def _try_get_package(self, ref: str) -> SceneParticipationPrepareResponse | None:
        clean = str(ref or "").strip()
        if not clean:
            return None
        try:
            return self.participation_service.get_package(clean)
        except StorageError as exc:
            if "SCENE_PARTICIPATION_PACKAGE_NOT_FOUND" in str(exc):
                return None
            raise

    def _try_get_selection(self, ref: str) -> SceneParticipantSelectionResponse | None:
        clean = str(ref or "").strip()
        if not clean:
            return None
        try:
            return self.selection_service.get_selection(clean)
        except StorageError as exc:
            if "SCENE_PARTICIPANT_SELECTION_NOT_FOUND" in str(exc):
                return None
            raise

    def _prepare_package(
        self,
        request: CompositeAgentRunRequest,
    ) -> SceneParticipationPrepareResponse:
        return self.participation_service.prepare_package(
            SceneParticipationPrepareRequest(
                chapter_id=request.chapter_id,
                scene_index=request.scene_index,
                scene_id=request.scene_id,
                force_refresh=False,
            )
        )

    def _selection_response_for_package(
        self,
        package: SceneParticipationPackage,
    ) -> SceneParticipantSelectionResponse:
        selection_id = str(package.source_selection_id or "").strip()
        if not selection_id:
            return SceneParticipantSelectionResponse()
        response = self.selection_service.get_selection(selection_id)
        if response.selection is None:
            return SceneParticipantSelectionResponse()
        self._assert_selection_matches_package(response.selection, package)
        return response

    def _assert_resolved_package(
        self,
        request: CompositeAgentRunRequest,
        package: SceneParticipationPackage,
    ) -> SceneParticipationPackage:
        if package.project_id != request.project_id:
            raise StorageError("COMPOSITE_SCENE_AGENT_PROJECT_MISMATCH")
        if package.chapter_id != request.chapter_id:
            raise StorageError("COMPOSITE_SCENE_AGENT_CHAPTER_MISMATCH")
        if str(package.scene_id or "").strip() != str(request.scene_id or "").strip():
            raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_MISMATCH")
        if int(package.scene_index or 0) != int(request.scene_index or 0):
            raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_INDEX_MISMATCH")
        if package.status not in {"ready", "warning", "blocked"}:
            raise StorageError("COMPOSITE_SCENE_AGENT_PACKAGE_UNREADY")
        if not package.active_character_ids:
            raise StorageError("COMPOSITE_SCENE_AGENT_ACTIVE_CHARACTERS_REQUIRED")
        return package

    def _assert_resolved_selection(
        self,
        request: CompositeAgentRunRequest,
        selection: SceneParticipantSelection,
    ) -> SceneParticipantSelection:
        if selection.project_id != request.project_id:
            raise StorageError("COMPOSITE_SCENE_AGENT_PROJECT_MISMATCH")
        if selection.chapter_id != request.chapter_id:
            raise StorageError("COMPOSITE_SCENE_AGENT_CHAPTER_MISMATCH")
        if str(selection.scene_id or "").strip() != str(request.scene_id or "").strip():
            raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_MISMATCH")
        if int(selection.scene_index or 0) != int(request.scene_index or 0):
            raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_INDEX_MISMATCH")
        if selection.status == "cancelled":
            raise StorageError("COMPOSITE_SCENE_AGENT_SELECTION_CANCELLED")
        if selection.status == "draft":
            raise StorageError("COMPOSITE_SCENE_AGENT_SELECTION_UNREADY")
        return selection

    def _assert_selection_matches_package(
        self,
        selection: SceneParticipantSelection,
        package: SceneParticipationPackage,
    ) -> None:
        if selection.project_id != package.project_id:
            raise StorageError("COMPOSITE_SCENE_AGENT_PROJECT_MISMATCH")
        if selection.chapter_id != package.chapter_id:
            raise StorageError("COMPOSITE_SCENE_AGENT_CHAPTER_MISMATCH")
        if str(selection.scene_id or "").strip() != str(package.scene_id or "").strip():
            raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_MISMATCH")
        if int(selection.scene_index or 0) != int(package.scene_index or 0):
            raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_INDEX_MISMATCH")

    def _assert_response_runtime_contract(
        self,
        response: SceneParticipationPrepareResponse,
    ) -> None:
        package = response.package
        if package is None:
            raise StorageError("COMPOSITE_SCENE_AGENT_PACKAGE_NOT_FOUND")
        active_ids = set(package.active_character_ids)
        for participant in package.participants:
            if participant.character_id not in active_ids:
                raise StorageError("COMPOSITE_SCENE_AGENT_UNSELECTED_CD_CONTEXT_LEAK")
            if participant.tier == "D" and participant.context_depth != "minimal":
                raise StorageError("COMPOSITE_SCENE_AGENT_D_TIER_CONTEXT_NOT_MINIMAL")
        tiered = response.tiered_character_context_package
        if tiered is not None:
            tiered_active = set(tiered.active_character_ids)
            item_ids = {item.character_id for item in tiered.items}
            if tiered_active != active_ids or not item_ids.issubset(active_ids):
                raise StorageError("COMPOSITE_SCENE_AGENT_UNSELECTED_CD_CONTEXT_LEAK")
        scene_memory_pack = response.scene_memory_pack
        if scene_memory_pack is not None:
            if set(scene_memory_pack.active_character_ids) != active_ids:
                raise StorageError("COMPOSITE_SCENE_AGENT_SCENE_MEMORY_ACTIVE_ID_MISMATCH")

    def _project_sub_agent_traces(
        self,
        *,
        request: CompositeAgentRunRequest,
        selection: SceneParticipantSelection | None,
        selection_response: SceneParticipantSelectionResponse,
        participation_response: SceneParticipationPrepareResponse,
    ) -> list[SubAgentTrace]:
        package = participation_response.package
        if package is None:
            return []
        readiness = participation_response.readiness
        pending_ids = package.pending_creation_candidate_ids
        source_need_ids = self._unique(
            [
                *(selection.source_need_ids if selection else []),
                *package.unresolved_required_need_ids,
                *package.unresolved_optional_need_ids,
            ]
        )
        specs = [
            (
                "SceneFunctionSubAgent",
                "scene_function_projection",
                "constraint_hint",
                "candidate",
                [request.chapter_id, request.scene_id, str(request.scene_index)],
                "Scene function context was projected from the current chapter and scene.",
            ),
            (
                "ABParticipantCarryoverSubAgent",
                "ab_participant_carryover_projection",
                "candidate",
                "candidate",
                [*package.selected_a_ids, *package.selected_b_ids],
                "A/B participants were carried from chapter-level runtime context.",
            ),
            (
                "CDRoleFunctionNeedSubAgent",
                "cd_role_function_need_projection",
                "constraint_hint",
                "read_only",
                source_need_ids,
                "C/D function needs were preserved as read-only evidence.",
            ),
            (
                "CDRoleRetrievalSubAgent",
                "cd_role_retrieval_projection",
                "candidate",
                "candidate",
                [*package.selected_c_ids, *package.selected_d_ids],
                "Confirmed C/D participants selected for this scene were projected.",
            ),
            (
                "CDCandidateProposalSubAgent",
                "cd_candidate_proposal_projection",
                "warning" if pending_ids else "candidate",
                "candidate",
                pending_ids,
                "Pending C/D candidates were kept out of active scene context.",
            ),
            (
                "SceneParticipationAssemblerSubAgent",
                "scene_participation_assembler_projection",
                "candidate",
                "candidate",
                self._unique(
                    [
                        package.scene_participation_package_id,
                        package.source_selection_id or "",
                        *(selection_response.report.report_id
                          if selection_response.report
                          else "",),
                    ]
                ),
                "Scene participation package was assembled as candidate-only runtime context.",
            ),
            (
                "TieredContextAdapterSubAgent",
                "tiered_context_adapter_projection",
                "memory_reference",
                "read_only",
                self._unique(
                    [
                        package.tiered_character_context_package_id,
                        package.scene_memory_pack_id,
                    ]
                ),
                "Tiered character context and scene memory references were exposed read-only.",
            ),
            (
                "GateRequestBuilderSubAgent",
                "gate_request_builder_projection",
                "gate_request",
                "candidate",
                self._unique(
                    [
                        package.scene_participation_package_id,
                        readiness.readiness_report_id if readiness else "",
                        *package.blocking_issues,
                        *package.warnings,
                    ]
                ),
                "Scene participation warnings and blockers were converted into gate signals.",
            ),
        ]
        now = utc_now()
        return [
            SubAgentTrace(
                sub_agent_name=name,
                node_kind=node_kind,
                output_type=output_type,
                authority_level=authority,
                confidence=0.84,
                source_ids=source_ids,
                input_fingerprint=self._fingerprint(
                    request.run_id,
                    package.scene_participation_package_id,
                    name,
                    str(index),
                ),
                output_summary=summary,
                warnings=[],
                created_at=now,
            )
            for index, (name, node_kind, output_type, authority, source_ids, summary)
            in enumerate(specs, start=1)
        ]

    def _project_candidate_outputs(
        self,
        *,
        request: CompositeAgentRunRequest,
        selection: SceneParticipantSelection | None,
        selection_response: SceneParticipantSelectionResponse,
        participation_response: SceneParticipationPrepareResponse,
    ) -> list[dict[str, Any]]:
        package = participation_response.package
        if package is None:
            return []
        readiness = participation_response.readiness
        tiered = participation_response.tiered_character_context_package
        scene_memory_pack = participation_response.scene_memory_pack
        outputs: list[dict[str, Any]] = []
        source_need_ids = self._unique(
            [
                *(selection.source_need_ids if selection else []),
                *package.unresolved_required_need_ids,
                *package.unresolved_optional_need_ids,
            ]
        )
        outputs.append(
            self._candidate_payload(
                request=request,
                candidate_id=f"{request.run_id}_scene_participant_selection",
                source_sub_agent="SceneParticipationAssemblerSubAgent",
                source_object_type="scene_participant_selection",
                source_object_id=package.source_selection_id or "chapter_ab_fallback",
                semantic_key=f"scene_selection:{package.chapter_id}:{package.scene_index}",
                output_type="candidate",
                truth_status="constraint_hint",
                tier="scene",
                budget_scope="scene_participant_selection",
                evidence_refs=[package.source_selection_id or "", *source_need_ids],
                source_ids=[package.source_selection_id or ""],
                safe_summary="Scene participant selection was projected as candidate-only context.",
                extra={
                    "selected_a_ids": package.selected_a_ids,
                    "selected_b_ids": package.selected_b_ids,
                    "selected_c_ids": package.selected_c_ids,
                    "selected_d_ids": package.selected_d_ids,
                    "source_need_ids": source_need_ids,
                    "selection_status": package.source_selection_status,
                },
            )
        )
        outputs.append(
            self._candidate_payload(
                request=request,
                candidate_id=f"{request.run_id}_scene_participation_package",
                source_sub_agent="SceneParticipationAssemblerSubAgent",
                source_object_type="scene_participation_package",
                source_object_id=package.scene_participation_package_id,
                semantic_key=(
                    f"scene_participation:{package.chapter_id}:{package.scene_index}"
                ),
                output_type="candidate",
                truth_status="constraint_hint",
                tier="scene",
                budget_scope="scene_participation_package",
                evidence_refs=[
                    package.scene_participation_package_id,
                    readiness.readiness_report_id if readiness else "",
                ],
                source_ids=[package.scene_participation_package_id],
                safe_summary="Scene participation package was projected for gate review.",
                warnings=package.warnings,
                blocking_findings=package.blocking_issues,
                extra={
                    "status": package.status,
                    "active_character_ids": package.active_character_ids,
                    "pending_creation_candidate_ids": package.pending_creation_candidate_ids,
                    "unresolved_required_need_ids": package.unresolved_required_need_ids,
                    "unresolved_optional_need_ids": package.unresolved_optional_need_ids,
                },
            )
        )
        outputs.append(
            self._active_participant_plan_payload(request, package)
        )
        if package.tiered_character_context_package_id or tiered is not None:
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_tiered_context_reference",
                    source_sub_agent="TieredContextAdapterSubAgent",
                    source_object_type="tiered_character_context_package",
                    source_object_id=package.tiered_character_context_package_id,
                    semantic_key=(
                        f"tiered_context:{package.scene_participation_package_id}"
                    ),
                    output_type="memory_reference",
                    truth_status="evidence",
                    authority_level="read_only",
                    tier="scene",
                    budget_scope="tiered_character_context_reference",
                    evidence_refs=[package.tiered_character_context_package_id],
                    source_ids=[
                        package.tiered_character_context_package_id,
                        package.scene_participation_package_id,
                    ],
                    safe_summary="Tiered character context package was referenced read-only.",
                    warnings=tiered.warnings if tiered else [],
                    extra={
                        "active_character_ids": (
                            tiered.active_character_ids if tiered else package.active_character_ids
                        ),
                        "item_character_ids": (
                            [item.character_id for item in tiered.items]
                            if tiered
                            else []
                        ),
                    },
                )
            )
        if package.scene_memory_pack_id or scene_memory_pack is not None:
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_scene_memory_pack_reference",
                    source_sub_agent="TieredContextAdapterSubAgent",
                    source_object_type="scene_memory_pack",
                    source_object_id=package.scene_memory_pack_id,
                    semantic_key=(
                        f"scene_memory_pack:{package.scene_participation_package_id}"
                    ),
                    output_type="memory_reference",
                    truth_status="evidence",
                    authority_level="read_only",
                    tier="scene",
                    budget_scope="scene_memory_pack_reference",
                    evidence_refs=[package.scene_memory_pack_id],
                    source_ids=[
                        package.scene_memory_pack_id,
                        package.scene_participation_package_id,
                    ],
                    safe_summary="Scene memory pack was referenced read-only.",
                    extra={
                        "active_character_ids": (
                            scene_memory_pack.active_character_ids
                            if scene_memory_pack
                            else package.active_character_ids
                        ),
                    },
                )
            )
        if package.pending_creation_candidate_ids:
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_pending_cd_candidate_warning",
                    source_sub_agent="CDCandidateProposalSubAgent",
                    source_object_type="scene_cd_role_creation_candidate",
                    source_object_id="pending_cd_candidates",
                    semantic_key=(
                        f"pending_cd:{package.scene_participation_package_id}"
                    ),
                    output_type="warning",
                    truth_status="warning",
                    tier="C_D",
                    budget_scope="pending_cd_candidate_warning",
                    evidence_refs=package.pending_creation_candidate_ids,
                    source_ids=package.pending_creation_candidate_ids,
                    warnings=["pending_cd_candidate_not_writer_runtime"],
                    safe_summary="Pending C/D candidates require confirmation and remain outside active context.",
                    extra={
                        "pending_creation_candidate_ids": package.pending_creation_candidate_ids,
                    },
                )
            )
        if package.unresolved_required_need_ids or package.unresolved_optional_need_ids:
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_unresolved_need_warning",
                    source_sub_agent="GateRequestBuilderSubAgent",
                    source_object_type="scene_role_function_need",
                    source_object_id="unresolved_scene_needs",
                    semantic_key=(
                        f"unresolved_need:{package.scene_participation_package_id}"
                    ),
                    output_type="warning",
                    truth_status="warning",
                    tier="scene",
                    budget_scope="unresolved_need_warning",
                    evidence_refs=[
                        *package.unresolved_required_need_ids,
                        *package.unresolved_optional_need_ids,
                    ],
                    source_ids=[
                        *package.unresolved_required_need_ids,
                        *package.unresolved_optional_need_ids,
                    ],
                    warnings=["unresolved_scene_role_need"],
                    blocking_findings=[
                        "unresolved_required_scene_role_need"
                        for _ in package.unresolved_required_need_ids[:1]
                    ],
                    safe_summary="Unresolved scene role needs were preserved for gate review.",
                    extra={
                        "unresolved_required_need_ids": package.unresolved_required_need_ids,
                        "unresolved_optional_need_ids": package.unresolved_optional_need_ids,
                    },
                )
            )
        outputs.append(
            self._candidate_payload(
                request=request,
                candidate_id=f"{request.run_id}_gate_request",
                source_sub_agent="GateRequestBuilderSubAgent",
                source_object_type="scene_participation_readiness",
                source_object_id=readiness.readiness_report_id if readiness else "",
                semantic_key=f"scene_gate_request:{package.scene_participation_package_id}",
                output_type="gate_request",
                truth_status="warning",
                tier="scene",
                budget_scope="gate_request",
                evidence_refs=[
                    package.scene_participation_package_id,
                    readiness.readiness_report_id if readiness else "",
                ],
                source_ids=[
                    package.scene_participation_package_id,
                    readiness.readiness_report_id if readiness else "",
                ],
                warnings=package.warnings,
                blocking_findings=package.blocking_issues,
                safe_summary="Scene participation readiness was converted into a gate request.",
                extra={
                    "readiness_status": readiness.status if readiness else package.status,
                    "needs_user_confirmation": (
                        readiness.needs_user_confirmation if readiness else False
                    ),
                },
            )
        )
        return outputs

    def _active_participant_plan_payload(
        self,
        request: CompositeAgentRunRequest,
        package: SceneParticipationPackage,
    ) -> dict[str, Any]:
        return self._candidate_payload(
            request=request,
            candidate_id=f"{request.run_id}_active_participant_plan",
            source_sub_agent="SceneParticipationAssemblerSubAgent",
            source_object_type="active_participant_plan",
            source_object_id=package.scene_participation_package_id,
            semantic_key=f"active_participant_plan:{package.scene_participation_package_id}",
            output_type="writer_input_candidate",
            truth_status="unknown",
            tier="scene",
            budget_scope="role_beat_candidate",
            evidence_refs=[package.scene_participation_package_id],
            source_ids=[package.scene_participation_package_id],
            safe_summary="Active participants were projected as role-beat candidates only.",
            extra={
                "active_character_ids": package.active_character_ids,
                "participants": [
                    {
                        "character_id": participant.character_id,
                        "tier": participant.tier,
                        "participation_source": participant.participation_source,
                        "selection_reason": participant.selection_reason,
                        "context_depth": participant.context_depth,
                    }
                    for participant in package.participants
                ],
            },
        )

    def _candidate_payload(
        self,
        *,
        request: CompositeAgentRunRequest,
        candidate_id: str,
        source_sub_agent: str,
        source_object_type: str,
        source_object_id: str,
        semantic_key: str,
        output_type: str,
        truth_status: str,
        tier: str,
        budget_scope: str,
        evidence_refs: list[Any],
        source_ids: list[Any],
        safe_summary: str,
        authority_level: str = "candidate",
        warnings: list[Any] | None = None,
        blocking_findings: list[Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "candidate_id": candidate_id,
            "source_sub_agent_trace_id": source_sub_agent,
            "source_object_type": source_object_type,
            "source_object_id": source_object_id,
            "semantic_key": semantic_key,
            "output_type": output_type,
            "target_scope": request.target_scope,
            "tier": tier,
            "budget_scope": budget_scope,
            "authority_level": authority_level,
            "candidate_only": True,
            "can_write_story_facts_directly": False,
            "truth_status": truth_status,
            "objective_fact_risk": False,
            "confidence": 0.84,
            "evidence_refs": self._unique(evidence_refs),
            "source_ids": self._unique(source_ids),
            "warnings": self._unique(warnings or []),
            "blocking_findings": self._unique(blocking_findings or []),
            "safe_summary": safe_summary,
        }
        if extra:
            payload.update(extra)
        return payload

    def _build_preliminary_result(
        self,
        *,
        request: CompositeAgentRunRequest,
        package: SceneParticipationPackage,
        traces: list[SubAgentTrace],
        candidate_outputs: list[dict[str, Any]],
        warnings: list[str],
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
                    package.scene_participation_package_id,
                    package.source_selection_id or "",
                    package.tiered_character_context_package_id,
                    package.scene_memory_pack_id,
                ]
            ),
            blocking_findings=package.blocking_issues,
            warnings=warnings,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "SceneAgent wrapper projected scene participation context into "
                "candidate-only composite outputs."
            ),
            created_at=utc_now(),
        )

    def _build_final_result(
        self,
        *,
        request: CompositeAgentRunRequest,
        package: SceneParticipationPackage,
        preliminary: CompositeAgentRunResult,
        bundle: CompositeIntegratedOutputBundle,
        detailed_integrator_report: CompositeIntegratorReport,
        gate_pipeline_result: CompositeGatePipelineResult,
    ) -> CompositeAgentRunResult:
        integrator_report = IntegratorReport(
            integrator_report_id=f"m4_integrator_{self._short_hash(bundle.bundle_id)}",
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
                "M4 wrapper integrated scene participation outputs through M2 dry review."
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
                *package.blocking_issues,
                *bundle.blocking_findings,
                *[
                    finding.finding_code or finding.finding_type
                    for finding in gate_pipeline_result.blocking_findings
                ],
            ]
        )
        warnings = self._unique(
            [
                *package.warnings,
                *bundle.warnings,
                *gate_pipeline_result.warnings,
                f"m2_overall_decision:{gate_pipeline_result.overall_decision}",
            ]
        )
        if package.status == "blocked" or package.blocking_issues:
            status = "blocked_by_scene_participation"
        elif gate_pipeline_result.hard_block:
            status = "blocked_by_gate_review"
        else:
            status = "candidate_gate_reviewed"
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
                    package.scene_participation_package_id,
                    package.tiered_character_context_package_id,
                    package.scene_memory_pack_id,
                ]
            ),
            blocking_findings=blocking_findings,
            warnings=warnings,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "SceneAgent wrapper completed a candidate-only M2 dry-review pass."
            ),
            created_at=utc_now(),
        )

    def _average_confidence(self, bundle: CompositeIntegratedOutputBundle) -> float:
        values = [candidate.confidence for candidate in bundle.integrated_candidates]
        if not values:
            return 1.0
        return round(sum(values) / len(values), 4)

    def _fingerprint(self, *parts: str) -> str:
        return f"m4_{self._short_hash(':'.join(str(part or '') for part in parts))}"

    def _short_hash(self, value: str) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]

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
