from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.abcd_story_information import ABCDStoryInformationPackageBuildResponse
from app.backend.models.composite_agent import (
    CompositeAgentRunRequest,
    CompositeAgentRunResult,
    CompositeAgentStoryFactDelta,
)
from app.backend.models.composite_runtime_graph import (
    COMPOSITE_RUNTIME_GRAPH_NODE_ORDER,
    COMPOSITE_RUNTIME_REQUIRED_EDGES,
    SCENE_GENERATION_CANDIDATE_GRAPH_ID,
    CandidateSceneOutput,
    CommitBoundaryPreviewReceipt,
    CompositeRuntimeEdge,
    CompositeRuntimeGraphAuthorityAudit,
    CompositeRuntimeGraphDefinition,
    CompositeRuntimeGraphRunRequest,
    CompositeRuntimeGraphRunResult,
    CompositeRuntimeGraphSequenceReport,
    CompositeRuntimeGraphTrace,
    CompositeRuntimeNode,
    CompositeRuntimeNodeReceipt,
    WritebackPlanPreviewRef,
)
from app.backend.services.abcd_story_information_service import ABCDStoryInformationService
from app.backend.services.composite_agent_registry_service import (
    COMPOSITE_AGENT_OUTPUT_CONTRACT_ID,
)
from app.backend.services.composite_character_intent_agent_service import (
    CHARACTER_INTENT_COMPOSITE_AGENT_NAME,
    CharacterPsychologyActionIntentAgentService,
)
from app.backend.services.composite_memory_curator_agent_service import (
    MEMORY_CURATOR_COMPOSITE_AGENT_NAME,
    MemoryCuratorAgentCompositeService,
)
from app.backend.services.composite_scene_agent_service import (
    SCENE_AGENT_COMPOSITE_AGENT_NAME,
    SceneAgentCompositeService,
)
from app.backend.services.composite_writer_agent_service import (
    TARGET_SCOPE as WRITER_TARGET_SCOPE,
    WRITER_COMPOSITE_AGENT_NAME,
    CompositeWriterAgentService,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


M7_PASS_MARKER = "PHASE85C_M7_COMPOSITE_RUNTIME_ORCHESTRATION_GRAPH: PASS"
M7_BLOCKED_SEQUENCE_MARKER = (
    "PHASE85C_M7_COMPOSITE_RUNTIME_ORCHESTRATION_GRAPH: BLOCKED_SEQUENCE_VIOLATION"
)
M7_BLOCKED_AUTHORITY_MARKER = (
    "PHASE85C_M7_COMPOSITE_RUNTIME_ORCHESTRATION_GRAPH: BLOCKED_AUTHORITY_GUARD"
)


class CompositeRuntimeOrchestrationService:
    """Backend-only M7 candidate graph over the verified M3-M6 wrappers."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        scene_agent: SceneAgentCompositeService | None = None,
        memory_curator: MemoryCuratorAgentCompositeService | None = None,
        character_intent: CharacterPsychologyActionIntentAgentService | None = None,
        story_information: ABCDStoryInformationService | None = None,
        writer_agent: CompositeWriterAgentService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.scene_agent = scene_agent or SceneAgentCompositeService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.memory_curator = memory_curator or MemoryCuratorAgentCompositeService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.character_intent = character_intent or CharacterPsychologyActionIntentAgentService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.story_information = story_information or ABCDStoryInformationService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.writer_agent = writer_agent or CompositeWriterAgentService(
            store=self.store,
            data_dir=self.data_dir,
        )

    def graph_definition(self) -> CompositeRuntimeGraphDefinition:
        nodes = [
            CompositeRuntimeNode(
                node_id=node_id,
                node_name=node_id.split(" ", 1)[1],
                order_index=index,
                agent_name=_agent_for_node(node_id),
                target_scope=_target_scope_for_node(node_id),
                safe_summary=f"{node_id} is part of the M7 candidate graph.",
            )
            for index, node_id in enumerate(COMPOSITE_RUNTIME_GRAPH_NODE_ORDER)
        ]
        edges = [
            CompositeRuntimeEdge(
                from_node_id=from_node,
                to_node_id=to_node,
                rule=f"{from_node} must run before {to_node}",
            )
            for from_node, to_node in COMPOSITE_RUNTIME_REQUIRED_EDGES
        ]
        return CompositeRuntimeGraphDefinition(
            nodes=nodes,
            edges=edges,
            safe_summary=(
                "M7 scene generation candidate graph orchestrates existing M3-M6 "
                "wrappers without live commit or writeback."
            ),
        )

    def run(
        self,
        request: CompositeRuntimeGraphRunRequest,
    ) -> CompositeRuntimeGraphRunResult:
        graph_run_id = request.graph_run_id or self._graph_run_id(request)
        timestamp = utc_now()
        receipts: list[CompositeRuntimeNodeReceipt] = []
        warnings: list[str] = []
        blocking: list[str] = []
        agent_run_ids: list[str] = []
        gate_receipt_ids: list[str] = []
        candidate_output: CandidateSceneOutput | None = None
        commit_boundary: CommitBoundaryPreviewReceipt | None = None
        writeback_ref: WritebackPlanPreviewRef | None = None
        status = "initialized"

        try:
            n0_receipt = self._node_receipt(
                graph_run_id=graph_run_id,
                node_id="N0 InputNormalizer",
                status="input_validated",
                output_refs=[
                    request.project_id,
                    request.chapter_id,
                    request.scene_id,
                    str(request.scene_index),
                ],
                safe_summary="Graph input normalized; wrapper refs remain list[str].",
                timestamp=timestamp,
            )
            receipts.append(n0_receipt)
            status = "input_validated"

            scene_refs = _unique_strings(
                [
                    request.input_refs.existing_scene_participation_package_id,
                    request.input_refs.chapter_plan_id,
                    *request.input_refs.scene_role_function_need_ids,
                ]
            )
            n1_request = self._wrapper_request(
                graph_run_id=graph_run_id,
                node_key="n1_scene",
                agent_name=SCENE_AGENT_COMPOSITE_AGENT_NAME,
                target_scope="scene_participation",
                request=request,
                input_refs=scene_refs,
                source_context_ids=[],
                authority="candidate",
            )
            n1_result = self.scene_agent.run(n1_request)
            agent_run_ids.append(n1_result.run_id)
            scene_package = (
                self.scene_agent.last_participation_response.package
                if self.scene_agent.last_participation_response
                else None
            )
            if scene_package is None:
                raise StorageError("M7_SCENE_PARTICIPATION_PACKAGE_MISSING")
            n1_receipt = self._receipt_from_result(
                graph_run_id=graph_run_id,
                node_id="N1 SceneAgent",
                status="scene_participation_ready",
                result=n1_result,
                input_refs=n1_request.input_refs,
                extra_output_refs=[scene_package.scene_participation_package_id],
                timestamp=timestamp,
            )
            receipts.append(n1_receipt)
            self._fail_if_blocked(n1_result, "N1 SceneAgent")
            status = "scene_participation_ready"

            n2_request = self._wrapper_request(
                graph_run_id=graph_run_id,
                node_key="n2_memory_context",
                agent_name=MEMORY_CURATOR_COMPOSITE_AGENT_NAME,
                target_scope="memory_scene_context",
                request=request,
                input_refs=[scene_package.scene_participation_package_id],
                source_context_ids=[scene_package.scene_participation_package_id],
                authority="candidate",
            )
            n2_result = self.memory_curator.run_for_scene_context(n2_request)
            agent_run_ids.append(n2_result.run_id)
            memory_inputs = self.memory_curator.last_resolved_inputs
            scene_memory_pack_id = (
                memory_inputs.scene_memory_pack.scene_memory_pack_id
                if memory_inputs and memory_inputs.scene_memory_pack
                else ""
            )
            tiered_context_id = (
                memory_inputs.tiered_context.tiered_character_context_package_id
                if memory_inputs and memory_inputs.tiered_context
                else ""
            )
            n2_receipt = self._receipt_from_result(
                graph_run_id=graph_run_id,
                node_id="N2 MemoryCuratorAgent.run_for_scene_context",
                status="memory_context_ready",
                result=n2_result,
                input_refs=n2_request.input_refs,
                extra_output_refs=[scene_memory_pack_id, tiered_context_id],
                timestamp=timestamp,
            )
            receipts.append(n2_receipt)
            self._fail_if_blocked(n2_result, "N2 MemoryCuratorAgent.run_for_scene_context")
            status = "memory_context_ready"

            n3_request = self._wrapper_request(
                graph_run_id=graph_run_id,
                node_key="n3_character_intent",
                agent_name=CHARACTER_INTENT_COMPOSITE_AGENT_NAME,
                target_scope="character_action_intention",
                request=request,
                input_refs=[scene_package.scene_participation_package_id],
                source_context_ids=[
                    scene_package.scene_participation_package_id,
                    scene_memory_pack_id,
                    tiered_context_id,
                ],
                authority="candidate",
            )
            n3_result = self.character_intent.run(n3_request)
            agent_run_ids.append(n3_result.run_id)
            intent_response = self.character_intent.last_m6_response
            intent_package_id = (
                intent_response.package.tiered_character_intent_package_id
                if intent_response and intent_response.package
                else ""
            )
            n3_receipt = self._receipt_from_result(
                graph_run_id=graph_run_id,
                node_id="N3 CharacterPsychologyActionIntentAgent",
                status="character_intent_ready",
                result=n3_result,
                input_refs=n3_request.input_refs,
                extra_output_refs=[intent_package_id],
                timestamp=timestamp,
            )
            receipts.append(n3_receipt)
            self._fail_if_blocked(n3_result, "N3 CharacterPsychologyActionIntentAgent")
            if not intent_package_id:
                raise StorageError("M7_CHARACTER_INTENT_PACKAGE_MISSING")
            status = "character_intent_ready"

            story_response = self.story_information.build_package(
                intent_package_id,
                force_refresh=request.force_refresh,
            )
            if story_response.package is None or story_response.writer_view is None:
                raise StorageError("M7_STORY_INFORMATION_PACKAGE_INCOMPLETE")
            n4_receipt = self._node_receipt(
                graph_run_id=graph_run_id,
                node_id="N4 ABCDStoryInformationIntegratorNode",
                status="story_information_ready",
                agent_name="ABCDStoryInformationService",
                wrapper_run_id=f"{graph_run_id}_n4_story_information",
                input_refs=[intent_package_id],
                output_refs=[
                    story_response.package.abcd_story_information_package_id,
                    story_response.package.writer_view_id,
                    story_response.package.integration_report_id,
                ],
                safe_summary="ABCDStoryInformation package built from candidate-only intent package.",
                timestamp=timestamp,
            )
            receipts.append(n4_receipt)
            status = "story_information_ready"

            n5_input_refs = _unique_strings(
                [
                    story_response.package.abcd_story_information_package_id,
                    scene_memory_pack_id,
                    tiered_context_id,
                ]
            )
            n5_source_context_ids = _unique_strings(
                [
                    story_response.writer_view.writer_view_id,
                    f"memory_curator_context:{n2_result.run_id}",
                    scene_memory_pack_id,
                    tiered_context_id,
                ]
            )
            n5_request = self._wrapper_request(
                graph_run_id=graph_run_id,
                node_key="n5_writer",
                agent_name=WRITER_COMPOSITE_AGENT_NAME,
                target_scope=WRITER_TARGET_SCOPE,
                request=request,
                input_refs=n5_input_refs,
                source_context_ids=n5_source_context_ids,
                authority="candidate",
            )
            n5_result = self.writer_agent.run(n5_request)
            agent_run_ids.append(n5_result.run_id)
            n5_receipt = self._receipt_from_result(
                graph_run_id=graph_run_id,
                node_id="N5 WriterAgent",
                status="writer_candidate_ready",
                result=n5_result,
                input_refs=n5_request.input_refs,
                timestamp=timestamp,
            )
            receipts.append(n5_receipt)
            self._fail_if_blocked(n5_result, "N5 WriterAgent")
            status = "writer_candidate_ready"

            gate_receipt_ids = [
                receipt.gate_review_receipt_id
                for receipt in n5_result.gate_review_receipts
            ]
            n6_blocking = self._validate_m6_gate_receipts(n5_result)
            n6_receipt = self._node_receipt(
                graph_run_id=graph_run_id,
                node_id="N6 PostDraftGateReceiptValidator",
                status="blocked" if n6_blocking else "gate_reviewed",
                agent_name="PostDraftGateReceiptValidator",
                wrapper_run_id=f"{graph_run_id}_n6_gate_receipt_validator",
                input_refs=[n5_result.run_id, *n5_result.output_refs],
                output_refs=gate_receipt_ids,
                gate_receipt_ids=gate_receipt_ids,
                blocking_findings=n6_blocking,
                safe_summary="M6 post-draft gate receipts validated without a second gate pass.",
                timestamp=timestamp,
            )
            receipts.append(n6_receipt)
            if n6_blocking:
                raise StorageError("M7_POST_DRAFT_GATE_RECEIPT_INVALID:" + ",".join(n6_blocking))
            status = "gate_reviewed"

            draft = self._writer_candidate_draft(n5_result)
            if draft is None:
                raise StorageError("M7_WRITER_CANDIDATE_DRAFT_MISSING")
            candidate_output = CandidateSceneOutput(
                candidate_scene_output_id=f"candidate_scene_output_{graph_run_id}",
                writer_candidate_draft_id=str(draft.get("writer_candidate_draft_id") or ""),
                graph_run_id=graph_run_id,
                project_id=request.project_id,
                chapter_id=request.chapter_id,
                scene_id=request.scene_id,
                scene_index=request.scene_index,
                candidate_synopsis=str(draft.get("candidate_synopsis") or ""),
                candidate_prose=str(draft.get("candidate_prose") or ""),
                source_scene_prose_plan_id=str(draft.get("source_scene_prose_plan_id") or ""),
                source_psychology_visibility_plan_id=str(
                    draft.get("source_psychology_visibility_plan_id") or ""
                ),
                source_beat_sheet_id=str(draft.get("source_beat_sheet_id") or ""),
                source_prose_draft_package_id=str(
                    draft.get("source_prose_draft_package_id") or ""
                ),
                source_reader_experience_report_id=str(
                    draft.get("source_reader_experience_report_id") or ""
                ),
                source_psychology_overexposure_report_id=str(
                    draft.get("source_psychology_overexposure_report_id") or ""
                ),
                source_prose_style_inspection_report_id=str(
                    draft.get("source_prose_style_inspection_report_id") or ""
                ),
                source_hook_payoff_inspection_report_id=str(
                    draft.get("source_hook_payoff_inspection_report_id") or ""
                ),
                source_subtext_balance_inspection_report_id=str(
                    draft.get("source_subtext_balance_inspection_report_id") or ""
                ),
                source_writer_self_revision_report_id=str(
                    draft.get("source_writer_self_revision_report_id") or ""
                ),
                writer_self_revision_applied=bool(draft.get("writer_self_revision_applied")),
                writer_quality_issue_codes=[
                    str(code or "")
                    for code in (draft.get("writer_quality_issue_codes") or [])
                    if str(code or "").strip()
                ],
                gate_receipt_ids=gate_receipt_ids,
                source_node_receipt_ids=[
                    receipt.node_receipt_id for receipt in receipts
                ],
                eligible_for_user_confirmation=True,
                eligible_for_commit_service_review=True,
                safe_summary="Candidate scene output assembled without committing scene prose.",
            )
            n7_receipt = self._node_receipt(
                graph_run_id=graph_run_id,
                node_id="N7 CandidateSceneOutputAssembler",
                status="candidate_output_ready",
                agent_name="CandidateSceneOutputAssembler",
                wrapper_run_id=f"{graph_run_id}_n7_candidate_output",
                input_refs=[n5_result.run_id, *gate_receipt_ids],
                output_refs=[candidate_output.candidate_scene_output_id],
                gate_receipt_ids=gate_receipt_ids,
                safe_summary="Candidate scene output assembled as candidate-only data.",
                timestamp=timestamp,
            )
            receipts.append(n7_receipt)
            status = "candidate_output_ready"

            if request.mode == "commit_boundary_preview":
                confirmation_ref = str(
                    request.input_refs.mock_user_confirmation_receipt_id or ""
                ).strip()
                if not confirmation_ref:
                    raise StorageError("M7_COMMIT_BOUNDARY_PREVIEW_RECEIPT_REQUIRED")
                commit_boundary = CommitBoundaryPreviewReceipt(
                    commit_boundary_receipt_id=f"commit_boundary_preview_{graph_run_id}",
                    graph_run_id=graph_run_id,
                    source_candidate_scene_output_id=candidate_output.candidate_scene_output_id,
                    source_user_confirmation_receipt_id=confirmation_ref,
                    safe_summary=(
                        "Fixture-only commit boundary preview verified; no scene commit executed."
                    ),
                    created_at=timestamp,
                )
                n8_receipt = self._node_receipt(
                    graph_run_id=graph_run_id,
                    node_id="N8 UserConfirmationCommitBoundaryPreview",
                    status="commit_boundary_verified",
                    agent_name="UserConfirmationCommitBoundaryPreview",
                    wrapper_run_id=commit_boundary.commit_boundary_receipt_id,
                    input_refs=[candidate_output.candidate_scene_output_id, confirmation_ref],
                    output_refs=[commit_boundary.commit_boundary_receipt_id],
                    safe_summary="Commit boundary preview used an explicit fixture receipt.",
                    timestamp=timestamp,
                )
                receipts.append(n8_receipt)
                status = "commit_boundary_verified"

                n9_request = self._wrapper_request(
                    graph_run_id=graph_run_id,
                    node_key="n9_writeback_plan",
                    agent_name=MEMORY_CURATOR_COMPOSITE_AGENT_NAME,
                    target_scope="memory_writeback_plan",
                    request=request,
                    input_refs=[
                        scene_package.scene_participation_package_id,
                        commit_boundary.commit_boundary_receipt_id,
                    ],
                    source_context_ids=[
                        scene_package.scene_participation_package_id,
                        commit_boundary.commit_boundary_receipt_id,
                    ],
                    authority="candidate",
                )
                n9_result = self.memory_curator.plan_writeback_after_commit(n9_request)
                agent_run_ids.append(n9_result.run_id)
                writeback_inputs = self.memory_curator.last_resolved_inputs
                plan_refs = (
                    [
                        plan.tiered_scene_memory_write_plan_id
                        for plan in writeback_inputs.writeback_plans
                    ]
                    if writeback_inputs
                    else []
                )
                if writeback_inputs and writeback_inputs.writeback_projection_ref:
                    plan_refs.append(writeback_inputs.writeback_projection_ref)
                writeback_ref = WritebackPlanPreviewRef(
                    writeback_plan_ref_id=f"writeback_plan_preview_{graph_run_id}",
                    graph_run_id=graph_run_id,
                    source_commit_boundary_receipt_id=commit_boundary.commit_boundary_receipt_id,
                    memory_curator_run_id=n9_result.run_id,
                    plan_refs=plan_refs,
                    safe_summary="Memory writeback plan preview created as plan-only evidence.",
                    warnings=n9_result.warnings,
                )
                n9_receipt = self._receipt_from_result(
                    graph_run_id=graph_run_id,
                    node_id="N9 MemoryCuratorAgent.plan_writeback_after_commit",
                    status="writeback_plan_ready",
                    result=n9_result,
                    input_refs=n9_request.input_refs,
                    extra_output_refs=[writeback_ref.writeback_plan_ref_id, *plan_refs],
                    timestamp=timestamp,
                )
                receipts.append(n9_receipt)
                self._fail_if_blocked(
                    n9_result,
                    "N9 MemoryCuratorAgent.plan_writeback_after_commit",
                )
                status = "writeback_plan_ready"
            else:
                status = "completed_candidate_graph"
        except Exception as exc:
            blocking.append(str(exc))
            status = "blocked" if not isinstance(exc, ValidationError) else "failed"

        sequence = self.validate_sequence(
            [receipt.node_id for receipt in receipts],
            graph_run_id=graph_run_id,
        )
        if not sequence.sequence_valid:
            blocking.extend(sequence.violations)
            status = "blocked"
        authority = self._authority_audit(
            graph_run_id=graph_run_id,
            node_receipts=receipts,
            sequence=sequence,
            candidate_output=candidate_output,
            commit_boundary=commit_boundary,
            writeback_ref=writeback_ref,
            extra_blocking=blocking,
        )
        n10_receipt = self._node_receipt(
            graph_run_id=graph_run_id,
            node_id="N10 GraphAuthorityAudit",
            status="blocked" if not authority.authority_audit_passed else "authority_audit_passed",
            agent_name="GraphAuthorityAudit",
            wrapper_run_id=f"{graph_run_id}_n10_authority_audit",
            input_refs=[receipt.node_receipt_id for receipt in receipts],
            output_refs=[f"authority_audit_{graph_run_id}"],
            blocking_findings=authority.blocking_findings,
            warnings=authority.warnings,
            safe_summary="Graph authority audit finalized candidate/gate/commit/writeback order.",
            timestamp=timestamp,
        )
        receipts.append(n10_receipt)
        node_order = [receipt.node_id for receipt in receipts]
        sequence = self.validate_sequence(node_order, graph_run_id=graph_run_id)
        if not sequence.sequence_valid:
            blocking.extend(sequence.violations)
        if not authority.authority_audit_passed:
            blocking.extend(authority.blocking_findings)
        blocking = _unique_strings(blocking)
        if blocking and status not in {"failed"}:
            status = "blocked"

        final_decision = (
            "pass"
            if not blocking
            and status in {"completed_candidate_graph", "writeback_plan_ready"}
            else "blocked"
        )
        trace = CompositeRuntimeGraphTrace(
            graph_trace_id=f"trace_{graph_run_id}",
            graph_run_id=graph_run_id,
            graph_id=SCENE_GENERATION_CANDIDATE_GRAPH_ID,
            mode=request.mode,
            node_receipt_ids=[receipt.node_receipt_id for receipt in receipts],
            agent_run_ids=agent_run_ids,
            gate_receipt_ids=gate_receipt_ids,
            candidate_scene_output_ref=(
                candidate_output.candidate_scene_output_id if candidate_output else ""
            ),
            commit_boundary_receipt_ref=(
                commit_boundary.commit_boundary_receipt_id if commit_boundary else ""
            ),
            writeback_plan_ref=(
                writeback_ref.writeback_plan_ref_id if writeback_ref else ""
            ),
            safe_summary="M7 graph trace links node receipts and wrapper run ids.",
            created_at=timestamp,
        )
        return CompositeRuntimeGraphRunResult(
            graph_id=SCENE_GENERATION_CANDIDATE_GRAPH_ID,
            graph_run_id=graph_run_id,
            mode=request.mode,
            status=status,
            final_decision=final_decision,
            node_receipts=receipts,
            node_order=node_order,
            agent_run_ids=agent_run_ids,
            gate_receipt_ids=gate_receipt_ids,
            candidate_scene_output=candidate_output,
            commit_boundary_preview_receipt=commit_boundary,
            writeback_plan_preview_ref=writeback_ref,
            sequence_report=sequence,
            authority_audit=authority,
            trace=trace,
            warnings=warnings,
            blocking_findings=blocking,
            safe_summary=(
                "M7 graph completed candidate preview safely."
                if final_decision == "pass"
                else "M7 graph blocked before unsafe authority transition."
            ),
            final_marker=M7_PASS_MARKER if final_decision == "pass" else M7_BLOCKED_AUTHORITY_MARKER,
            generated_at=timestamp,
        )

    def validate_sequence(
        self,
        node_order: list[str],
        *,
        graph_run_id: str = "sequence_validation",
    ) -> CompositeRuntimeGraphSequenceReport:
        positions = {node_id: index for index, node_id in enumerate(node_order)}
        violations: list[str] = []
        for node_id in node_order:
            if node_id not in COMPOSITE_RUNTIME_GRAPH_NODE_ORDER:
                violations.append(f"unknown_node:{node_id}")
        if (
            "N10 GraphAuthorityAudit" in positions
            and node_order
            and node_order[-1] != "N10 GraphAuthorityAudit"
        ):
            violations.append("graph_authority_audit_not_last")
        for earlier, later in COMPOSITE_RUNTIME_REQUIRED_EDGES:
            if earlier in positions and later in positions and positions[earlier] > positions[later]:
                violations.append(f"order_violation:{earlier}>{later}")
        if "N9 MemoryCuratorAgent.plan_writeback_after_commit" in positions and (
            "N8 UserConfirmationCommitBoundaryPreview" not in positions
        ):
            violations.append("writeback_without_commit_boundary")
        if "N8 UserConfirmationCommitBoundaryPreview" in positions and (
            "N7 CandidateSceneOutputAssembler" not in positions
        ):
            violations.append("commit_boundary_without_candidate_output")
        if "N7 CandidateSceneOutputAssembler" in positions and (
            "N6 PostDraftGateReceiptValidator" not in positions
        ):
            violations.append("candidate_output_without_gate_validation")
        if "N5 WriterAgent" in positions and (
            "N4 ABCDStoryInformationIntegratorNode" not in positions
        ):
            violations.append("writer_without_story_information")
        if "N4 ABCDStoryInformationIntegratorNode" in positions and (
            "N3 CharacterPsychologyActionIntentAgent" not in positions
        ):
            violations.append("story_information_without_character_intent")
        if any(node.startswith("N2 ") or node.startswith("N3 ") for node in node_order) and (
            "N1 SceneAgent" not in positions
        ):
            violations.append("downstream_without_scene_agent")
        return CompositeRuntimeGraphSequenceReport(
            graph_run_id=graph_run_id,
            sequence_valid=not violations,
            node_order=node_order,
            required_edges=[
                {"from": earlier, "to": later}
                for earlier, later in COMPOSITE_RUNTIME_REQUIRED_EDGES
            ],
            violations=_unique_strings(violations),
            safe_summary=(
                "Graph sequence is valid."
                if not violations
                else "Graph sequence contains blocked ordering violations."
            ),
        )

    def validate_post_draft_gate_receipts(
        self,
        writer_result: CompositeAgentRunResult,
    ) -> list[str]:
        """Validate M6 post-draft gate receipts without running the graph."""

        return self._validate_m6_gate_receipts(writer_result)

    def audit_graph_state(
        self,
        *,
        graph_run_id: str,
        node_order: list[str],
        node_receipts: list[CompositeRuntimeNodeReceipt] | None = None,
        candidate_output: CandidateSceneOutput | None = None,
        commit_boundary: CommitBoundaryPreviewReceipt | None = None,
        writeback_ref: WritebackPlanPreviewRef | None = None,
        extra_blocking: list[str] | None = None,
    ) -> CompositeRuntimeGraphAuthorityAudit:
        """Run the M7 authority audit over supplied graph state without side effects."""

        sequence = self.validate_sequence(node_order, graph_run_id=graph_run_id)
        return self._authority_audit(
            graph_run_id=graph_run_id,
            node_receipts=node_receipts or [],
            sequence=sequence,
            candidate_output=candidate_output,
            commit_boundary=commit_boundary,
            writeback_ref=writeback_ref,
            extra_blocking=extra_blocking or [],
        )

    def _wrapper_request(
        self,
        *,
        graph_run_id: str,
        node_key: str,
        agent_name: str,
        target_scope: str,
        request: CompositeRuntimeGraphRunRequest,
        input_refs: list[str],
        source_context_ids: list[str],
        authority: str,
    ) -> CompositeAgentRunRequest:
        return CompositeAgentRunRequest(
            run_id=f"{graph_run_id}_{node_key}",
            agent_name=agent_name,
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            scene_id=request.scene_id,
            scene_index=request.scene_index,
            target_scope=target_scope,
            source_context_ids=_unique_strings(source_context_ids),
            input_refs=_unique_strings(input_refs),
            requested_output_contract_id=COMPOSITE_AGENT_OUTPUT_CONTRACT_ID,
            requested_authority_level=authority,
            dry_run=True,
            caller="phase85c_m7_composite_runtime_graph",
            created_at=utc_now(),
        )

    def _receipt_from_result(
        self,
        *,
        graph_run_id: str,
        node_id: str,
        status: str,
        result: CompositeAgentRunResult,
        input_refs: list[str],
        timestamp: str,
        extra_output_refs: list[str] | None = None,
    ) -> CompositeRuntimeNodeReceipt:
        return self._node_receipt(
            graph_run_id=graph_run_id,
            node_id=node_id,
            status=status,
            agent_name=result.agent_name,
            wrapper_run_id=result.run_id,
            input_refs=input_refs,
            output_refs=_unique_strings([*result.output_refs, *(extra_output_refs or [])]),
            gate_receipt_ids=[
                receipt.gate_review_receipt_id
                for receipt in result.gate_review_receipts
            ],
            story_fact_delta_empty=result.story_fact_delta.is_empty(),
            blocking_findings=result.blocking_findings,
            warnings=result.warnings,
            safe_summary=result.safe_summary,
            timestamp=timestamp,
        )

    def _node_receipt(
        self,
        *,
        graph_run_id: str,
        node_id: str,
        status: str,
        timestamp: str,
        agent_name: str = "",
        wrapper_run_id: str = "",
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
        gate_receipt_ids: list[str] | None = None,
        story_fact_delta_empty: bool = True,
        blocking_findings: list[str] | None = None,
        warnings: list[str] | None = None,
        safe_summary: str = "",
    ) -> CompositeRuntimeNodeReceipt:
        order_index = (
            COMPOSITE_RUNTIME_GRAPH_NODE_ORDER.index(node_id)
            if node_id in COMPOSITE_RUNTIME_GRAPH_NODE_ORDER
            else -1
        )
        return CompositeRuntimeNodeReceipt(
            node_receipt_id=f"{graph_run_id}_{_safe_id(node_id)}_receipt",
            graph_run_id=graph_run_id,
            node_id=node_id,
            order_index=order_index,
            status=status,
            agent_name=agent_name,
            wrapper_run_id=wrapper_run_id,
            input_refs=input_refs or [],
            output_refs=output_refs or [],
            gate_receipt_ids=gate_receipt_ids or [],
            story_fact_delta_empty=story_fact_delta_empty,
            blocking_findings=blocking_findings or [],
            warnings=warnings or [],
            safe_summary=safe_summary,
            created_at=timestamp,
        )

    def _fail_if_blocked(self, result: CompositeAgentRunResult, node_id: str) -> None:
        if result.blocking_findings or result.status in {"blocked", "blocked_by_gate_review"}:
            raise StorageError(f"M7_{_safe_id(node_id).upper()}_BLOCKED:" + ",".join(result.blocking_findings))
        if not result.candidate_only or result.can_write_story_facts_directly:
            raise StorageError(f"M7_{_safe_id(node_id).upper()}_UNSAFE_AUTHORITY")
        if not result.story_fact_delta.is_empty():
            raise StorageError(f"M7_{_safe_id(node_id).upper()}_STORY_FACT_DELTA")

    def _validate_m6_gate_receipts(
        self,
        writer_result: CompositeAgentRunResult,
    ) -> list[str]:
        findings: list[str] = []
        if not writer_result.gate_review_receipts:
            findings.append("m6_gate_receipts_missing")
        gate_names = [receipt.gate_name for receipt in writer_result.gate_review_receipts]
        required = [
            "NoWriteGuard",
            "ObjectiveFactBoundaryGate",
            "ContinuityGateAdapter",
            "ApparentContradictionGateAdapter",
            "QualityGateAdapter",
            "UserConfirmationGateAdapter",
            "CompositeGateDecisionReducer",
        ]
        missing = [gate for gate in required if gate not in gate_names]
        if missing:
            findings.append("m6_gate_receipts_incomplete:" + ",".join(missing))
        for receipt in writer_result.gate_review_receipts:
            decision = str(receipt.decision or "").casefold()
            if "block" in decision:
                findings.append(f"m6_hard_block:{receipt.gate_name}")
            if receipt.does_not_commit_story_facts is not True:
                findings.append(f"m6_receipt_claims_commit:{receipt.gate_name}")
        return _unique_strings(findings)

    def _writer_candidate_draft(
        self,
        writer_result: CompositeAgentRunResult,
    ) -> dict[str, Any] | None:
        for output in writer_result.candidate_outputs:
            if output.get("source_object_type") == "writer_candidate_draft":
                return output
        return None

    def _authority_audit(
        self,
        *,
        graph_run_id: str,
        node_receipts: list[CompositeRuntimeNodeReceipt],
        sequence: CompositeRuntimeGraphSequenceReport,
        candidate_output: CandidateSceneOutput | None,
        commit_boundary: CommitBoundaryPreviewReceipt | None,
        writeback_ref: WritebackPlanPreviewRef | None,
        extra_blocking: list[str],
    ) -> CompositeRuntimeGraphAuthorityAudit:
        findings: list[str] = []
        if not sequence.sequence_valid:
            findings.append("sequence_invalid")
        if extra_blocking:
            findings.extend(extra_blocking)
        if any(not receipt.story_fact_delta_empty for receipt in node_receipts):
            findings.append("node_story_fact_delta_not_empty")
        if any(receipt.candidate_only is not True for receipt in node_receipts):
            findings.append("node_not_candidate_only")
        if any(receipt.can_write_story_facts_directly for receipt in node_receipts):
            findings.append("node_claims_story_fact_write")
        if any(_has_product_view_model_ref(receipt) for receipt in node_receipts):
            findings.append("product_view_model_used_as_authority_source")
        if candidate_output is not None and (
            not candidate_output.candidate_only
            or candidate_output.can_write_scene_directly
            or candidate_output.can_write_story_facts_directly
            or not candidate_output.story_fact_delta_empty
        ):
            findings.append("candidate_output_unsafe_authority")
        if commit_boundary is not None and (
            not commit_boundary.preview_only
            or not commit_boundary.does_not_commit_scene
            or not commit_boundary.does_not_write_story_facts
        ):
            findings.append("commit_boundary_claims_live_commit")
        if writeback_ref is not None and (
            not writeback_ref.writeback_plan_only
            or writeback_ref.active_memory_write_executed
        ):
            findings.append("writeback_preview_claims_active_write")
        receipt_ids = [receipt.node_receipt_id for receipt in node_receipts]
        passed = not findings
        return CompositeRuntimeGraphAuthorityAudit(
            graph_run_id=graph_run_id,
            authority_audit_passed=passed,
            candidate_gate_commit_writeback_order_preserved=sequence.sequence_valid,
            story_fact_delta_empty=not any(
                not receipt.story_fact_delta_empty for receipt in node_receipts
            ),
            all_node_story_fact_delta_empty=not any(
                not receipt.story_fact_delta_empty for receipt in node_receipts
            ),
            no_node_claims_committed_authority=not any(
                receipt.can_write_story_facts_directly for receipt in node_receipts
            ),
            candidate_output_candidate_only=(
                candidate_output is None or candidate_output.candidate_only
            ),
            checked_node_receipt_ids=receipt_ids,
            blocking_findings=_unique_strings(findings),
            safe_summary=(
                "M7 authority audit passed."
                if passed
                else "M7 authority audit blocked unsafe graph state."
            ),
        )

    def _graph_run_id(self, request: CompositeRuntimeGraphRunRequest) -> str:
        return (
            f"m7_graph_{_safe_id(request.project_id)}_"
            f"{_safe_id(request.chapter_id)}_{_safe_id(request.scene_id)}_"
            f"{request.scene_index}_{request.mode}"
        )


def _agent_for_node(node_id: str) -> str:
    mapping = {
        "N1 SceneAgent": "SceneAgent",
        "N2 MemoryCuratorAgent.run_for_scene_context": "MemoryCuratorAgent",
        "N3 CharacterPsychologyActionIntentAgent": "CharacterPsychologyActionIntentAgent",
        "N4 ABCDStoryInformationIntegratorNode": "ABCDStoryInformationService",
        "N5 WriterAgent": "WriterAgent",
        "N9 MemoryCuratorAgent.plan_writeback_after_commit": "MemoryCuratorAgent",
    }
    return mapping.get(node_id, "")


def _target_scope_for_node(node_id: str) -> str:
    mapping = {
        "N1 SceneAgent": "scene_participation",
        "N2 MemoryCuratorAgent.run_for_scene_context": "memory_scene_context",
        "N3 CharacterPsychologyActionIntentAgent": "character_action_intention",
        "N4 ABCDStoryInformationIntegratorNode": "abcd_story_information_package",
        "N5 WriterAgent": WRITER_TARGET_SCOPE,
        "N9 MemoryCuratorAgent.plan_writeback_after_commit": "memory_writeback_plan",
    }
    return mapping.get(node_id, "")


def _has_product_view_model_ref(receipt: CompositeRuntimeNodeReceipt) -> bool:
    refs = [*receipt.input_refs, *receipt.output_refs]
    for ref in refs:
        text = str(ref or "").strip().casefold()
        if text.startswith("product_view_model:") or text.startswith("product-workbench:"):
            return True
    return False


def model_to_dict(model: Any) -> dict[str, Any]:
    if model is None:
        return {}
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()
    if isinstance(model, dict):
        return dict(model)
    return dict(model)


def _safe_id(value: str) -> str:
    text = str(value or "").strip().lower()
    return "".join(ch if ch.isalnum() else "_" for ch in text).strip("_") or "empty"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    return [value]


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
