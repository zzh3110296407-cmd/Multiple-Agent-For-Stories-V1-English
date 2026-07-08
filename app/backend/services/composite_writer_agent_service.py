import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.abcd_story_information import (
    ABCDStoryInformationPackage,
    CharacterIntentStoryInformationItem,
    WriterABCDContextView,
)
from app.backend.models.composite_agent import (
    CompositeAgentRunRequest,
    CompositeAgentRunResult,
    CompositeAgentRunTrace,
    CompositeAgentStoryFactDelta,
    GateReviewReceipt,
    GateReviewRequest,
    IntegratorReport,
    SubAgentTrace,
)
from app.backend.models.composite_gate import CompositeGatePipelineResult
from app.backend.models.composite_integrator import (
    CompositeIntegratedOutputBundle,
    CompositeIntegratorReport,
)
from app.backend.models.composite_writer import (
    PHASE85C_M6_WRITER_AGENT_VERSION,
    WriterCandidateDraft,
)
from app.backend.models.memory_pack import SceneMemoryPack
from app.backend.models.scene_participation import TieredCharacterContextPackage
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
from app.backend.services.writer_planner_layer_service import WriterPlannerLayerService
from app.backend.services.writer_prose_drafting_service import WriterProseDraftingService
from app.backend.services.writer_self_revision_service import WriterSelfRevisionService
from app.backend.storage.json_store import JsonStore, StorageError


WRITER_COMPOSITE_AGENT_NAME = "WriterAgent"
WRITER_COMPOSITE_WRAPPER_VERSION = PHASE85C_M6_WRITER_AGENT_VERSION
TARGET_SCOPE = "writer_candidate_draft"

SUB_AGENT_TRACE_ORDER = [
    "OrderedPackageAdapter",
    "KnowledgeBoundaryChecker",
    "ProseDraftSubAgent",
    "StyleRhythmSubAgent",
    "ContinuityPreservingEditor",
    "WriterOutputIntegrator",
    "PostDraftGateRequestBuilder",
]

POST_DRAFT_GATES = [
    "continuity_gate",
    "apparent_contradiction_gate",
    "quality_gate",
    "objective_fact_boundary",
    "user_confirmation_boundary",
]

UNSAFE_TEXT_MARKERS = {
    "forbidden knowledge",
    "forbidden_knowledge",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "raw_psychology_chain",
    "raw psychology chain",
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "禁忌知识",
    "禁止知识",
    "隐藏推理",
    "内部推理",
    "原始提示词",
    "原始响应",
    "心理链原文",
    "未经批准事实",
    "不应使用",
}

SUBJECTIVE_TRUTH_STATUSES = {"subjective_claim", "perception", "lie"}
SUBJECTIVE_LANGUAGE_MARKERS = {
    "claim",
    "claims",
    "claimed",
    "believ",
    "perceiv",
    "perceives",
    "perceived",
    "lie",
    "lies",
    "subjective",
    "may express",
    "not objective",
    "tentative",
    "hint",
    "认为",
    "以为",
    "感觉",
    "声称",
    "谎称",
    "可能",
    "似乎",
    "视为",
    "主观",
    "感知",
    "误以为",
}
OBJECTIFICATION_MARKERS = {
    "confirmed fact",
    "is true",
    "proves",
    "proved",
    "prove ",
    "definitely",
    "certainly",
    "事实是",
    "已证实",
    "已经证实",
    "已证明",
    "已经证明",
    "证明为事实",
    "已确定",
    "已经确定",
    "确定为事实",
    "可以确定",
    "事实已经确定",
    "一定是事实",
}
NEGATED_OBJECTIFICATION_MARKERS = {
    "不确定",
    "并不确定",
    "无法确定",
    "不能确定",
    "尚未确定",
    "未确定",
    "不一定",
    "不能证明",
    "无法证明",
}


class WriterResolvedInputs(BaseModel):
    package: ABCDStoryInformationPackage | None = None
    writer_view: WriterABCDContextView | None = None
    items: list[CharacterIntentStoryInformationItem] = []
    scene_memory_pack: SceneMemoryPack | None = None
    tiered_character_context: TieredCharacterContextPackage | None = None
    source_memory_curator_run_id: str = ""
    blocking_findings: list[str] = []
    warnings: list[str] = []


class CompositeWriterAgentService:
    """M6 candidate-only Composite Agent wrapper for WriterAgent drafting.

    The wrapper intentionally avoids persistence-oriented writer paths. It projects
    already reviewed B-M7 and M5 context into a candidate draft and sends that
    candidate through the M2 dry-review gate pipeline.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        registry_service: CompositeAgentRegistryService | None = None,
        integrator_service: CompositeIntegratorService | None = None,
        gate_pipeline_service: CompositeGatePipelineService | None = None,
        writer_planner_service: WriterPlannerLayerService | None = None,
        writer_prose_drafting_service: WriterProseDraftingService | None = None,
        writer_self_revision_service: WriterSelfRevisionService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.registry_service = registry_service or CompositeAgentRegistryService()
        self.integrator_service = integrator_service or CompositeIntegratorService()
        self.gate_pipeline_service = gate_pipeline_service or CompositeGatePipelineService()
        self.writer_planner_service = writer_planner_service or WriterPlannerLayerService()
        self.writer_prose_drafting_service = (
            writer_prose_drafting_service or WriterProseDraftingService()
        )
        self.writer_self_revision_service = (
            writer_self_revision_service or WriterSelfRevisionService(
                writer_prose_drafting_service=self.writer_prose_drafting_service,
            )
        )

        self.last_resolved_inputs: WriterResolvedInputs | None = None
        self.last_preliminary_result: CompositeAgentRunResult | None = None
        self.last_integrated_bundle: CompositeIntegratedOutputBundle | None = None
        self.last_integrator_report: CompositeIntegratorReport | None = None
        self.last_gate_pipeline_result: CompositeGatePipelineResult | None = None

    def run(self, request: CompositeAgentRunRequest) -> CompositeAgentRunResult:
        normalized = self.normalize_and_validate_request(request)
        resolved = self.resolve_writer_inputs(normalized)
        traces = self.project_sub_agent_traces(normalized, resolved)
        candidate_outputs = self.project_candidate_outputs(normalized, resolved)
        preliminary = self._build_preliminary_result(
            request=normalized,
            resolved=resolved,
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
            request=normalized,
            resolved=resolved,
            preliminary=preliminary,
            bundle=bundle,
            detailed_integrator_report=detailed_integrator_report,
            gate_pipeline_result=gate_pipeline_result,
        )

        self.last_resolved_inputs = resolved
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
        if normalized.agent_name != WRITER_COMPOSITE_AGENT_NAME:
            raise StorageError("COMPOSITE_WRITER_WRONG_AGENT")
        if normalized.target_scope != TARGET_SCOPE:
            raise StorageError("COMPOSITE_WRITER_TARGET_SCOPE_UNSUPPORTED")
        if not normalized.dry_run:
            raise StorageError("COMPOSITE_WRITER_DRY_RUN_REQUIRED")
        if normalized.requested_authority_level != "candidate":
            raise StorageError("COMPOSITE_WRITER_CANDIDATE_AUTHORITY_REQUIRED")
        if not str(normalized.project_id or "").strip():
            raise StorageError("COMPOSITE_WRITER_PROJECT_ID_REQUIRED")
        if not str(normalized.chapter_id or "").strip():
            raise StorageError("COMPOSITE_WRITER_CHAPTER_ID_REQUIRED")
        if not str(normalized.scene_id or "").strip():
            raise StorageError("COMPOSITE_WRITER_SCENE_ID_REQUIRED")
        if int(normalized.scene_index or 0) < 1:
            raise StorageError("COMPOSITE_WRITER_SCENE_INDEX_REQUIRED")
        if (
            normalized.requested_output_contract_id
            and normalized.requested_output_contract_id != COMPOSITE_AGENT_OUTPUT_CONTRACT_ID
        ):
            raise StorageError("COMPOSITE_WRITER_OUTPUT_CONTRACT_MISMATCH")
        if any(not isinstance(ref, str) for ref in normalized.input_refs):
            raise StorageError("COMPOSITE_WRITER_INPUT_REFS_MUST_BE_STRINGS")
        return normalized

    def resolve_writer_inputs(
        self,
        request: CompositeAgentRunRequest,
    ) -> WriterResolvedInputs:
        refs = _unique_strings([*request.input_refs, *request.source_context_ids])
        blocking: list[str] = []
        warnings: list[str] = []

        package = self._resolve_package(request, refs)
        writer_view = self._resolve_writer_view(package, refs) if package else None
        items = self._resolve_items(package) if package else []
        scene_memory_pack = self._resolve_scene_memory_pack(package, refs)
        tiered_context = self._resolve_tiered_context(package, refs)
        source_memory_curator_run_id = self._resolve_memory_curator_run_id(
            refs=refs,
            scene_memory_pack=scene_memory_pack,
            tiered_context=tiered_context,
        )

        if package is None:
            blocking.append("missing_abcd_story_information_package")
        else:
            blocking.extend(self._validate_package(request, package))
        if writer_view is None:
            blocking.append("missing_writer_abcd_context_view")
        else:
            blocking.extend(self._validate_writer_view(request, package, writer_view))
        if package is not None and not items:
            blocking.append("missing_abcd_story_information_items")
        if scene_memory_pack is None and tiered_context is None:
            blocking.append("missing_m5_memory_context")
        if scene_memory_pack is not None:
            blocking.extend(self._validate_scene_memory_pack(request, package, scene_memory_pack))
        if tiered_context is not None:
            blocking.extend(self._validate_tiered_context(request, package, tiered_context))
        if package is not None and writer_view is not None:
            blocking.extend(self._validate_story_information_boundary(package, writer_view, items))

        return WriterResolvedInputs(
            package=package,
            writer_view=writer_view,
            items=items,
            scene_memory_pack=scene_memory_pack,
            tiered_character_context=tiered_context,
            source_memory_curator_run_id=source_memory_curator_run_id,
            blocking_findings=_unique_strings(blocking),
            warnings=_unique_strings(warnings),
        )

    def project_sub_agent_traces(
        self,
        request: CompositeAgentRunRequest,
        resolved: WriterResolvedInputs,
    ) -> list[SubAgentTrace]:
        source_ids = _unique_strings(
            [
                *(request.input_refs or []),
                *(request.source_context_ids or []),
                resolved.package.abcd_story_information_package_id
                if resolved.package
                else "",
                resolved.writer_view.writer_view_id if resolved.writer_view else "",
                resolved.scene_memory_pack.scene_memory_pack_id
                if resolved.scene_memory_pack
                else "",
                resolved.tiered_character_context.tiered_character_context_package_id
                if resolved.tiered_character_context
                else "",
            ]
        )
        now = utc_now()
        traces: list[SubAgentTrace] = []
        for index, name in enumerate(SUB_AGENT_TRACE_ORDER, start=1):
            output_type = "gate_request" if name == "PostDraftGateRequestBuilder" else "candidate"
            if name == "KnowledgeBoundaryChecker":
                output_type = "constraint_hint"
            authority = "read_only" if name in {"OrderedPackageAdapter", "KnowledgeBoundaryChecker"} else "candidate"
            traces.append(
                SubAgentTrace(
                    sub_agent_name=name,
                    node_kind="writer_composite_trace",
                    output_type=output_type,
                    authority_level=authority,
                    confidence=1.0,
                    source_ids=source_ids,
                    input_fingerprint=_hash_json(
                        {
                            "run_id": request.run_id,
                            "sub_agent": name,
                            "index": index,
                            "sources": source_ids,
                        }
                    ),
                    output_summary=f"{name} projected WriterAgent candidate-only drafting context.",
                    warnings=[],
                    created_at=now,
                )
            )
        return traces

    def project_candidate_outputs(
        self,
        request: CompositeAgentRunRequest,
        resolved: WriterResolvedInputs,
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        if resolved.package and resolved.writer_view and not resolved.blocking_findings:
            draft = self._build_writer_candidate_draft(request, resolved)
            draft_findings = self._validate_candidate_draft(
                draft=draft,
                package=resolved.package,
                writer_view=resolved.writer_view,
                items=resolved.items,
            )
            outputs.append(
                {
                    **model_to_dict(draft),
                    "candidate_id": draft.writer_candidate_draft_id,
                    "source_sub_agent_trace_id": "WriterOutputIntegrator",
                    "source_object_type": "writer_candidate_draft",
                    "source_object_id": draft.writer_candidate_draft_id,
                    "semantic_key": f"writer_candidate_draft:{draft.scene_id}",
                    "output_type": "candidate",
                    "target_scope": TARGET_SCOPE,
                    "tier": "scene",
                    "budget_scope": "writer_candidate_draft",
                    "authority_level": "candidate",
                    "truth_status": "unknown",
                    "candidate_only": True,
                    "can_write_story_facts_directly": False,
                    "objective_fact_risk": False,
                    "evidence_refs": _unique_strings(
                        [
                            draft.source_abcd_story_information_package_id,
                            draft.source_writer_abcd_context_view_id,
                            draft.source_ordered_story_information_package_id,
                            draft.source_memory_curator_run_id,
                        ]
                    ),
                    "source_ids": _unique_strings(
                        [
                            draft.source_abcd_story_information_package_id,
                            draft.source_writer_abcd_context_view_id,
                            draft.source_memory_curator_run_id,
                        ]
                    ),
                    "warnings": [],
                    "blocking_findings": draft_findings,
                    "safe_summary": "WriterAgent composite wrapper generated a candidate-only draft.",
                }
            )
        if resolved.blocking_findings:
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_writer_input_boundary_blocked",
                    source_object_type="writer_input_boundary",
                    source_object_id="writer_input_boundary",
                    semantic_key=f"writer_boundary:{request.scene_id}",
                    output_type="warning",
                    truth_status="warning",
                    safe_summary="Writer input boundary failed before candidate drafting.",
                    warnings=resolved.warnings,
                    blocking_findings=resolved.blocking_findings,
                )
            )
        outputs.append(self._post_draft_gate_request_payload(request, resolved))
        return outputs

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
            version_id=WRITER_COMPOSITE_WRAPPER_VERSION,
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
            safe_summary="WriterAgent composite wrapper produced a dry-run trace.",
            warnings=result.warnings,
            created_at=utc_now(),
        )

    def _build_writer_candidate_draft(
        self,
        request: CompositeAgentRunRequest,
        resolved: WriterResolvedInputs,
    ) -> WriterCandidateDraft:
        if not resolved.package or not resolved.writer_view:
            raise StorageError("COMPOSITE_WRITER_INPUTS_INCOMPLETE")
        package = resolved.package
        writer_view = resolved.writer_view
        item_by_id = {item.item_id: item for item in resolved.items}
        used_ids = [
            item_id
            for item_id in package.writer_ready_item_ids
            if item_id in item_by_id
        ]
        used_items = [item_by_id[item_id] for item_id in used_ids]
        ignored_do_not_use = [
            item_id for item_id in package.do_not_use_item_ids if item_id in item_by_id
        ]
        planner_snapshot = self.writer_planner_service.build_input_snapshot_from_writer_inputs(
            request=request,
            package=package,
            writer_view=writer_view,
            items=used_items,
        )
        planner_output = self.writer_planner_service.build_planner_output(planner_snapshot)
        prose_package = self.writer_prose_drafting_service.draft_from_planner_output(
            planner_output,
            do_not_use_texts=writer_view.do_not_include,
            used_story_information_item_ids=used_ids,
            ignored_do_not_use_item_ids=ignored_do_not_use,
        )
        prose_report = self.writer_prose_drafting_service.validate_draft_package(
            prose_package,
            source_planner_output=planner_output,
        )
        if not prose_report.passed:
            raise StorageError("COMPOSITE_WRITER_PROSE_DRAFT_PACKAGE_INVALID")
        revision_result = self.writer_self_revision_service.revise(
            prose_package,
            planner_output,
        )
        if not revision_result.m4_validation_report.passed:
            raise StorageError("COMPOSITE_WRITER_SELF_REVISION_PROSE_INVALID")
        prose_package = revision_result.revised_draft_package
        final_bundle = revision_result.final_inspection_bundle
        synopsis = prose_package.candidate_synopsis
        prose = prose_package.candidate_prose
        draft_id = f"writer_candidate_draft_{_short_hash(request.run_id + ':' + package.abcd_story_information_package_id)}"
        gate_request_id = f"gate_request_{draft_id}"
        return WriterCandidateDraft(
            writer_candidate_draft_id=draft_id,
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            scene_id=request.scene_id,
            scene_index=request.scene_index,
            source_abcd_story_information_package_id=package.abcd_story_information_package_id,
            source_writer_abcd_context_view_id=writer_view.writer_view_id,
            source_ordered_story_information_package_id=(
                f"ordered_story_information_package:{package.abcd_story_information_package_id}"
            ),
            source_memory_curator_run_id=resolved.source_memory_curator_run_id,
            source_writer_planner_output_id=planner_output.planner_output_id,
            source_scene_prose_plan_id=planner_output.scene_prose_plan.scene_prose_plan_id,
            source_psychology_visibility_plan_id=(
                planner_output.psychology_visibility_plan.psychology_visibility_plan_id
            ),
            source_beat_sheet_id=planner_output.beat_sheet.beat_sheet_id,
            source_prose_draft_package_id=prose_package.draft_package_id,
            source_reader_experience_report_id=(
                final_bundle.reader_experience_report.reader_experience_report_id
            ),
            source_psychology_overexposure_report_id=(
                final_bundle.psychology_overexposure_report.psychology_overexposure_report_id
            ),
            source_prose_style_inspection_report_id=(
                final_bundle.prose_style_report.prose_style_inspection_report_id
            ),
            source_hook_payoff_inspection_report_id=(
                final_bundle.hook_payoff_report.hook_payoff_inspection_report_id
            ),
            source_subtext_balance_inspection_report_id=(
                final_bundle.subtext_balance_report.subtext_balance_inspection_report_id
            ),
            source_writer_self_revision_report_id=(
                revision_result.revision_report.writer_self_revision_report_id
            ),
            writer_self_revision_applied=revision_result.writer_self_revision_applied,
            writer_quality_issue_codes=final_bundle.issue_codes,
            candidate_synopsis=synopsis,
            candidate_prose=prose,
            used_story_information_item_ids=used_ids,
            ignored_do_not_use_item_ids=ignored_do_not_use,
            character_ids_present=package.active_character_ids,
            truth_boundary_notes=[
                "Candidate draft cannot write scene prose directly.",
                "Subjective claims, perceptions, lies, and unknowns remain non-objective.",
                "Do-not-use items are excluded from candidate prose.",
                (
                    "M5 reader-experience/self-revision issues: "
                    + (", ".join(final_bundle.issue_codes) if final_bundle.issue_codes else "none")
                ),
            ],
            candidate_only=True,
            can_write_scene_prose_directly=False,
            can_write_story_facts_directly=False,
            requires_post_draft_gate_review=True,
            post_draft_gate_request_id=gate_request_id,
            post_draft_gate_receipt_ids=[],
            eligible_for_commit_service_review=revision_result.ready_for_downstream_gates,
            created_at=utc_now(),
        )

    def _safe_item_line(
        self,
        item: CharacterIntentStoryInformationItem,
        *,
        limit: int = 280,
    ) -> str:
        content = item.writer_instruction or item.base_story_information_item.content
        if item.truth_status in SUBJECTIVE_TRUTH_STATUSES and not _contains_any(
            content,
            SUBJECTIVE_LANGUAGE_MARKERS,
        ):
            content = (
                f"{item.character_id} may express this as a subjective claim or "
                f"perception, not objective fact: {content}"
            )
        return _truncate(content, limit)

    def _validate_candidate_draft(
        self,
        *,
        draft: WriterCandidateDraft,
        package: ABCDStoryInformationPackage,
        writer_view: WriterABCDContextView,
        items: list[CharacterIntentStoryInformationItem],
    ) -> list[str]:
        findings: list[str] = []
        text = f"{draft.candidate_synopsis}\n{draft.candidate_prose}"
        lowered = text.casefold()
        findings.extend(
            f"unsafe_writer_candidate_marker:{marker}"
            for marker in _matched_markers(text, UNSAFE_TEXT_MARKERS)
        )
        for blocked_text in writer_view.do_not_include:
            if blocked_text and blocked_text.casefold() in lowered:
                findings.append("do_not_use_content_leaked")
        findings.extend(
            f"unselected_character_text_leak:{character_id}"
            for character_id in _unselected_character_refs_in_text(
                text,
                package.active_character_ids,
            )
        )
        item_by_id = {item.item_id: item for item in items}
        for item_id in draft.used_story_information_item_ids:
            item = item_by_id.get(item_id)
            if item is None:
                findings.append(f"used_item_missing:{item_id}")
                continue
            content = item.writer_instruction or item.base_story_information_item.content
            if item.base_story_information_item.priority == "do_not_use" or not item.safe_for_writer:
                findings.append(f"do_not_use_item_used:{item_id}")
            final_line = self._safe_item_line(item)
            if not _subjective_boundary_preserved(
                final_line,
                item.truth_status,
            ):
                findings.append(f"subjective_claim_objectified:{item_id}")
            if _contains_any(content, {"major_state_change", "major state change"}):
                findings.append(f"major_state_change_without_confirmation:{item_id}")
        active = set(package.active_character_ids)
        if not set(draft.character_ids_present).issubset(active):
            findings.append("unselected_cd_active_participant")
        return _unique_strings(findings)

    def _validate_package(
        self,
        request: CompositeAgentRunRequest,
        package: ABCDStoryInformationPackage,
    ) -> list[str]:
        findings: list[str] = []
        if package.project_id != request.project_id:
            findings.append("wrong_project_package")
        if package.chapter_id != request.chapter_id:
            findings.append("wrong_chapter_package")
        if package.scene_id != request.scene_id:
            findings.append("wrong_scene_package")
        if int(package.scene_index or 0) != request.scene_index:
            findings.append("wrong_scene_index_package")
        if package.status == "blocked":
            findings.append("blocked_abcd_story_information_package")
        if package.writer_ready is not True:
            findings.append("non_writer_ready_package")
        if package.candidate_only is not True:
            findings.append("package_not_candidate_only")
        if package.no_story_fact_written is not True:
            findings.append("package_story_fact_written")
        if package.does_not_write_generic_story_information is not True:
            findings.append("package_generic_story_information_write")
        if package.no_writer_invocation is not True:
            findings.append("package_already_invoked_writer")
        if not package.ordered_story_information_package:
            findings.append("missing_ordered_story_information_package")
        return findings

    def _validate_writer_view(
        self,
        request: CompositeAgentRunRequest,
        package: ABCDStoryInformationPackage | None,
        writer_view: WriterABCDContextView,
    ) -> list[str]:
        findings: list[str] = []
        if writer_view.project_id != request.project_id:
            findings.append("wrong_project_writer_view")
        if writer_view.chapter_id != request.chapter_id:
            findings.append("wrong_chapter_writer_view")
        if writer_view.scene_id != request.scene_id:
            findings.append("wrong_scene_writer_view")
        if int(writer_view.scene_index or 0) != request.scene_index:
            findings.append("wrong_scene_index_writer_view")
        if package and writer_view.abcd_story_information_package_id != package.abcd_story_information_package_id:
            findings.append("writer_view_package_mismatch")
        if writer_view.no_raw_psychology_chain is not True:
            findings.append("raw_psychology_chain")
        if writer_view.no_unapproved_fact_write is not True:
            findings.append("writer_view_unapproved_fact_write")
        active = set(package.active_character_ids if package else [])
        if active and not set(writer_view.related_character_ids).issubset(active):
            findings.append("unselected_cd_active_participant")
        return findings

    def _validate_story_information_boundary(
        self,
        package: ABCDStoryInformationPackage,
        writer_view: WriterABCDContextView,
        items: list[CharacterIntentStoryInformationItem],
    ) -> list[str]:
        findings: list[str] = []
        active = set(package.active_character_ids)
        item_ids = {item.item_id for item in items}
        if not set(package.writer_ready_item_ids).issubset(item_ids):
            findings.append("writer_ready_item_missing")
        if not set(package.do_not_use_item_ids).issubset(item_ids):
            findings.append("do_not_use_item_missing")
        used_text = "\n".join(
            [
                *writer_view.opening_context,
                *writer_view.scene_progression,
                *writer_view.character_turns,
                *writer_view.required_reveals,
                *writer_view.emotional_beats,
                *writer_view.ending_beat,
                *writer_view.guardrails,
            ]
        )
        findings.extend(
            f"unsafe_writer_input_marker:{marker}"
            for marker in _matched_markers(used_text, UNSAFE_TEXT_MARKERS)
        )
        findings.extend(
            f"unselected_character_text_leak:{character_id}"
            for character_id in _unselected_character_refs_in_text(
                used_text,
                package.active_character_ids,
            )
        )
        for blocked_text in writer_view.do_not_include:
            if blocked_text and blocked_text.casefold() in used_text.casefold():
                findings.append("do_not_use_leak")
        for item in items:
            if item.project_id != package.project_id:
                findings.append(f"wrong_project_story_item:{item.item_id}")
            if item.chapter_id != package.chapter_id or item.scene_id != package.scene_id:
                findings.append(f"wrong_scene_story_item:{item.item_id}")
            if int(item.scene_index or 0) != int(package.scene_index or 0):
                findings.append(f"wrong_scene_index_story_item:{item.item_id}")
            if item.character_id and item.character_id not in active:
                findings.append(f"unselected_cd_story_item:{item.item_id}")
            item_text = item.writer_instruction or item.base_story_information_item.content
            if item.item_id in package.writer_ready_item_ids and item.base_story_information_item.priority == "do_not_use":
                findings.append(f"do_not_use_item_marked_writer_ready:{item.item_id}")
            if item.item_id in package.writer_ready_item_ids and not item.safe_for_writer:
                findings.append(f"unsafe_item_marked_writer_ready:{item.item_id}")
            if item.item_id not in package.writer_ready_item_ids:
                continue
            if _contains_any(item_text, UNSAFE_TEXT_MARKERS):
                findings.append(f"unsafe_story_item_marker:{item.item_id}")
            findings.extend(
                f"unselected_character_text_leak:{character_id}"
                for character_id in _unselected_character_refs_in_text(
                    item_text,
                    package.active_character_ids,
                )
            )
            if not _subjective_boundary_preserved(
                self._safe_item_line(item),
                item.truth_status,
            ):
                findings.append(f"subjective_claim_objectified:{item.item_id}")
            if _contains_any(item_text, {"major_state_change", "major state change"}):
                findings.append(f"major_state_change_without_confirmation:{item.item_id}")
        return _unique_strings(findings)

    def _validate_scene_memory_pack(
        self,
        request: CompositeAgentRunRequest,
        package: ABCDStoryInformationPackage | None,
        pack: SceneMemoryPack,
    ) -> list[str]:
        findings: list[str] = []
        if pack.project_id != request.project_id:
            findings.append("wrong_project_memory_context")
        if pack.chapter_id != request.chapter_id:
            findings.append("wrong_chapter_memory_context")
        if pack.scene_id and pack.scene_id != request.scene_id:
            findings.append("wrong_scene_memory_context")
        if int(pack.scene_index or 0) != request.scene_index:
            findings.append("wrong_scene_index_memory_context")
        if package and set(pack.active_character_ids) != set(package.active_character_ids):
            findings.append("memory_context_active_ids_mismatch")
        if pack.status != "active":
            findings.append("memory_context_not_active")
        return findings

    def _validate_tiered_context(
        self,
        request: CompositeAgentRunRequest,
        package: ABCDStoryInformationPackage | None,
        context: TieredCharacterContextPackage,
    ) -> list[str]:
        findings: list[str] = []
        if context.project_id != request.project_id:
            findings.append("wrong_project_memory_context")
        if context.chapter_id != request.chapter_id:
            findings.append("wrong_chapter_memory_context")
        if context.scene_id and context.scene_id != request.scene_id:
            findings.append("wrong_scene_memory_context")
        if int(context.scene_index or 0) != request.scene_index:
            findings.append("wrong_scene_index_memory_context")
        if package and set(context.active_character_ids) != set(package.active_character_ids):
            findings.append("tiered_context_active_ids_mismatch")
        return findings

    def _resolve_package(
        self,
        request: CompositeAgentRunRequest,
        refs: list[str],
    ) -> ABCDStoryInformationPackage | None:
        packages = self._read_models(
            "abcd_story_information_packages.json",
            ABCDStoryInformationPackage,
        )
        ref_set = set(refs)
        for package in packages:
            if package.abcd_story_information_package_id in ref_set:
                return package
        matches = [
            package
            for package in packages
            if package.project_id == request.project_id
            and package.chapter_id == request.chapter_id
            and package.scene_id == request.scene_id
            and int(package.scene_index or 0) == request.scene_index
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at or item.created_at, reverse=True)[0]

    def _resolve_writer_view(
        self,
        package: ABCDStoryInformationPackage | None,
        refs: list[str],
    ) -> WriterABCDContextView | None:
        views = self._read_models("writer_abcd_context_views.json", WriterABCDContextView)
        ref_set = set(refs)
        for view in views:
            if view.writer_view_id in ref_set:
                return view
        if not package:
            return None
        return next(
            (
                view
                for view in views
                if view.writer_view_id == package.writer_view_id
                or view.abcd_story_information_package_id == package.abcd_story_information_package_id
            ),
            None,
        )

    def _resolve_items(
        self,
        package: ABCDStoryInformationPackage,
    ) -> list[CharacterIntentStoryInformationItem]:
        wanted = set(package.item_ids)
        return [
            item
            for item in self._read_models(
                "character_intent_story_information_items.json",
                CharacterIntentStoryInformationItem,
            )
            if item.item_id in wanted
            or item.abcd_story_information_package_id
            == package.abcd_story_information_package_id
        ]

    def _resolve_scene_memory_pack(
        self,
        package: ABCDStoryInformationPackage | None,
        refs: list[str],
    ) -> SceneMemoryPack | None:
        packs = self._read_models("scene_memory_packs.json", SceneMemoryPack)
        ref_set = set(refs)
        for pack in packs:
            if pack.scene_memory_pack_id in ref_set:
                return pack
        if not package:
            return None
        return next(
            (
                pack
                for pack in packs
                if pack.scene_memory_pack_id == package.source_scene_memory_pack_id
            ),
            None,
        )

    def _resolve_tiered_context(
        self,
        package: ABCDStoryInformationPackage | None,
        refs: list[str],
    ) -> TieredCharacterContextPackage | None:
        contexts = self._read_models(
            "tiered_character_context_packages.json",
            TieredCharacterContextPackage,
        )
        ref_set = set(refs)
        for context in contexts:
            if context.tiered_character_context_package_id in ref_set:
                return context
        if not package:
            return None
        return next(
            (
                context
                for context in contexts
                if context.tiered_character_context_package_id
                == package.source_tiered_character_context_package_id
            ),
            None,
        )

    def _resolve_memory_curator_run_id(
        self,
        *,
        refs: list[str],
        scene_memory_pack: SceneMemoryPack | None,
        tiered_context: TieredCharacterContextPackage | None,
    ) -> str:
        for ref in refs:
            if "memory_curator" in ref.casefold() or ref.startswith("m5_"):
                return ref
        if scene_memory_pack is not None:
            return f"memory_curator_context:{scene_memory_pack.scene_memory_pack_id}"
        if tiered_context is not None:
            return f"memory_curator_context:{tiered_context.tiered_character_context_package_id}"
        return ""

    def _read_models(self, file_name: str, model: type[BaseModel]) -> list[Any]:
        path = self.data_dir / file_name
        if not self.store.exists(path):
            return []
        raw = self.store.read_any(path)
        if isinstance(raw, dict):
            rows = raw.get("items") or raw.get("packages") or raw.get("views") or raw.get("packs") or []
        elif isinstance(raw, list):
            rows = raw
        else:
            rows = []
        result: list[Any] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                result.append(model(**row))
            except ValidationError as exc:
                raise StorageError(f"{model.__name__} JSON schema is invalid.") from exc
        return result

    def _post_draft_gate_request_payload(
        self,
        request: CompositeAgentRunRequest,
        resolved: WriterResolvedInputs,
    ) -> dict[str, Any]:
        package_id = (
            resolved.package.abcd_story_information_package_id
            if resolved.package
            else "missing_package"
        )
        return self._candidate_payload(
            request=request,
            candidate_id=f"{request.run_id}_post_draft_gate_request",
            source_object_type="post_draft_gate_request",
            source_object_id=package_id,
            semantic_key=f"post_draft_gate:{request.scene_id}",
            output_type="gate_request",
            truth_status="warning",
            safe_summary="Writer candidate draft requires post-draft gate review.",
            warnings=[],
            blocking_findings=[],
            extra={"requested_gates": POST_DRAFT_GATES},
        )

    def _candidate_payload(
        self,
        *,
        request: CompositeAgentRunRequest,
        candidate_id: str,
        source_object_type: str,
        source_object_id: str,
        semantic_key: str,
        output_type: str,
        truth_status: str,
        safe_summary: str,
        warnings: list[str] | None = None,
        blocking_findings: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "candidate_id": candidate_id,
            "run_id": request.run_id,
            "agent_name": request.agent_name,
            "source_sub_agent_trace_id": "PostDraftGateRequestBuilder",
            "source_object_type": source_object_type,
            "source_object_id": source_object_id,
            "semantic_key": semantic_key,
            "output_type": output_type,
            "target_scope": request.target_scope,
            "tier": "scene",
            "budget_scope": request.target_scope,
            "authority_level": "candidate",
            "truth_status": truth_status,
            "candidate_only": True,
            "can_write_story_facts_directly": False,
            "objective_fact_risk": False,
            "evidence_refs": _unique_strings([source_object_id, *request.input_refs]),
            "source_ids": _unique_strings([source_object_id]),
            "warnings": warnings or [],
            "blocking_findings": blocking_findings or [],
            "safe_summary": safe_summary,
            "created_at": utc_now(),
        }
        if extra:
            payload.update(extra)
        return payload

    def _build_preliminary_result(
        self,
        *,
        request: CompositeAgentRunRequest,
        resolved: WriterResolvedInputs,
        traces: list[SubAgentTrace],
        candidate_outputs: list[dict[str, Any]],
    ) -> CompositeAgentRunResult:
        output_refs = [
            str(output.get("candidate_id") or output.get("writer_candidate_draft_id") or "")
            for output in candidate_outputs
            if output.get("candidate_id") or output.get("writer_candidate_draft_id")
        ]
        return CompositeAgentRunResult(
            run_id=request.run_id,
            agent_name=request.agent_name,
            status="blocked" if resolved.blocking_findings else "candidate_ready_for_gate_review",
            authority_level="candidate",
            candidate_only=True,
            can_write_story_facts_directly=False,
            sub_agent_traces=traces,
            integrator_report=IntegratorReport(
                integrator_report_id=f"integrator_{request.run_id}",
                agent_name=request.agent_name,
                merged_output_types=["candidate", "gate_request"],
                source_trace_ids=[trace.input_fingerprint for trace in traces],
                conflict_categories=[],
                confidence=1.0,
                candidate_only=True,
                can_write_story_facts_directly=False,
                safe_summary="WriterAgent preliminary integrator placeholder before M2 dry review.",
                warnings=[],
            ),
            gate_review_requests=[
                GateReviewRequest(
                    gate_review_request_id=f"gate_request_{request.run_id}_post_draft",
                    agent_name=request.agent_name,
                    requested_gates=POST_DRAFT_GATES,
                    candidate_output_refs=output_refs,
                    reason="writer_candidate_requires_post_draft_gate_review",
                    does_not_mark_gate_passed=True,
                    candidate_only=True,
                    safe_summary="Post-draft gate request for candidate-only WriterAgent output.",
                )
            ],
            gate_review_receipts=[],
            candidate_outputs=candidate_outputs,
            output_refs=output_refs,
            blocking_findings=resolved.blocking_findings,
            warnings=resolved.warnings,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary="WriterAgent composite wrapper projected candidate-only output for dry review.",
            created_at=utc_now(),
        )

    def _build_final_result(
        self,
        *,
        request: CompositeAgentRunRequest,
        resolved: WriterResolvedInputs,
        preliminary: CompositeAgentRunResult,
        bundle: CompositeIntegratedOutputBundle,
        detailed_integrator_report: CompositeIntegratorReport,
        gate_pipeline_result: CompositeGatePipelineResult,
    ) -> CompositeAgentRunResult:
        receipts = [
            GateReviewReceipt(
                gate_review_receipt_id=receipt.receipt_id,
                gate_name=receipt.gate_name,
                decision=receipt.decision,
                source_request_id=f"gate_request_{request.run_id}_post_draft",
                issued_by="phase85c_m6_writeragent_composite_wrapper",
                does_not_commit_story_facts=True,
                safe_summary=receipt.safe_summary,
                warnings=receipt.warnings,
            )
            for receipt in gate_pipeline_result.gate_step_receipts
        ]
        candidate_outputs = [
            self._with_post_draft_receipts(output, receipts)
            for output in preliminary.candidate_outputs
        ]
        blocking = _unique_strings(
            [
                *resolved.blocking_findings,
                *bundle.blocking_findings,
                *[
                    finding.finding_code or finding.finding_type
                    for finding in gate_pipeline_result.blocking_findings
                ],
            ]
        )
        status = (
            "blocked"
            if blocking or gate_pipeline_result.hard_block
            else "candidate_gate_reviewed"
        )
        return CompositeAgentRunResult(
            run_id=request.run_id,
            agent_name=request.agent_name,
            status=status,
            authority_level="candidate",
            candidate_only=True,
            can_write_story_facts_directly=False,
            sub_agent_traces=preliminary.sub_agent_traces,
            integrator_report=IntegratorReport(
                integrator_report_id=detailed_integrator_report.integrator_report_id,
                agent_name=request.agent_name,
                merged_output_types=["candidate", "gate_request"],
                source_trace_ids=detailed_integrator_report.source_sub_agent_trace_ids,
                conflict_categories=[
                    f"conflict_count:{detailed_integrator_report.conflict_group_count}"
                ]
                if detailed_integrator_report.conflict_group_count
                else [],
                confidence=1.0,
                candidate_only=True,
                can_write_story_facts_directly=False,
                safe_summary=detailed_integrator_report.safe_summary,
                warnings=detailed_integrator_report.warnings,
            ),
            gate_review_requests=preliminary.gate_review_requests,
            gate_review_receipts=receipts,
            candidate_outputs=candidate_outputs,
            output_refs=preliminary.output_refs,
            blocking_findings=blocking,
            warnings=_unique_strings(
                [
                    *preliminary.warnings,
                    *bundle.warnings,
                    *gate_pipeline_result.warnings,
                ]
            ),
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "WriterAgent composite wrapper produced a gated candidate draft."
                if status != "blocked"
                else "WriterAgent composite wrapper blocked unsafe or incomplete input."
            ),
            created_at=utc_now(),
        )

    def _with_post_draft_receipts(
        self,
        output: dict[str, Any],
        receipts: list[GateReviewReceipt],
    ) -> dict[str, Any]:
        if output.get("source_object_type") != "writer_candidate_draft":
            return output
        updated = dict(output)
        updated["post_draft_gate_receipt_ids"] = [
            receipt.gate_review_receipt_id for receipt in receipts
        ]
        return updated


def model_to_dict(model: Any) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()
    return dict(model or {})


def _contains_any(text: Any, markers: set[str]) -> bool:
    lowered = str(text or "").casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _matched_markers(text: Any, markers: set[str]) -> list[str]:
    lowered = str(text or "").casefold()
    return _unique_strings(
        [marker for marker in markers if marker.casefold() in lowered]
    )


def _subjective_boundary_preserved(text: Any, truth_status: str) -> bool:
    if str(truth_status or "").strip() not in SUBJECTIVE_TRUTH_STATUSES:
        return True
    lowered = str(text or "").casefold()
    has_subjective_marker = any(
        marker.casefold() in lowered for marker in SUBJECTIVE_LANGUAGE_MARKERS
    )
    has_objectification_marker = _contains_objectification_marker(lowered)
    return has_subjective_marker and not has_objectification_marker


def _contains_objectification_marker(text: Any) -> bool:
    lowered = str(text or "").casefold()
    scan_text = lowered
    for marker in NEGATED_OBJECTIFICATION_MARKERS:
        scan_text = scan_text.replace(marker.casefold(), " ")
    return any(marker.casefold() in scan_text for marker in OBJECTIFICATION_MARKERS)


def _unselected_character_refs_in_text(
    text: Any,
    active_character_ids: list[str],
) -> list[str]:
    active = {str(character_id or "").casefold() for character_id in active_character_ids}
    refs = re.findall(r"\bchar_[A-Za-z0-9_]+\b", str(text or ""))
    return _unique_strings(
        [ref for ref in refs if ref.casefold() not in active]
    )


def _first_non_empty(values: list[str], fallback: str) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return fallback


def _hash_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _short_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _truncate(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _unique_strings(values: list[Any]) -> list[str]:
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
