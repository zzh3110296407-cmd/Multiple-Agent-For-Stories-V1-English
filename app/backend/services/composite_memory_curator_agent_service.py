import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

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
from app.backend.models.memory_pack import SceneMemoryPack
from app.backend.models.memory_retrieval_promotion import (
    ChapterMemoryPromotionCandidate,
    ChapterMemoryPromotionDecision,
    ChapterMemoryPromotionReport,
    MemoryRetrievalUsageRecord,
)
from app.backend.models.role_memory_writeback import (
    RoleSceneMemoryEntry,
    TieredSceneMemoryWritePlan,
)
from app.backend.models.scene import Scene
from app.backend.models.scene_participation import (
    SceneParticipationPackage,
    SceneParticipationPrepareRequest,
    SceneParticipationPrepareResponse,
    TieredCharacterContextPackage,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.chapter_memory_service import ChapterMemoryService
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
from app.backend.services.memory_retrieval_promotion_service import (
    ChapterMemoryPromotionService,
    MemoryRetrievalUsageService,
    TieredMemoryRetrievalPolicyService,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.scene_memory_service import SceneMemoryService
from app.backend.services.scene_participation_package_service import (
    SceneParticipationPackageService,
)
from app.backend.services.tiered_scene_memory_writeback_service import (
    TieredSceneMemoryWritebackService,
)
from app.backend.storage.json_store import JsonStore, StorageError


MEMORY_CURATOR_COMPOSITE_AGENT_NAME = "MemoryCuratorAgent"
MEMORY_CURATOR_COMPOSITE_WRAPPER_VERSION = (
    "phase85c_m5_memory_curator_composite_agent_v1"
)

TARGET_SCOPES = {
    "memory_scene_context",
    "memory_promotion_inspection",
    "memory_writeback_plan",
}

SUB_AGENT_TRACE_ORDER = [
    "ChapterMemoryPackReaderSubAgent",
    "SceneMemoryPackBuilderSubAgent",
    "MemoryRetrievalSubAgent",
    "RetrievalUsageTrackerSubAgent",
    "ChapterPromotionInspectorSubAgent",
    "TieredWritebackPlanSubAgent",
    "MemoryAuthorityGuardSubAgent",
]


class MemoryCuratorResolvedInputs(BaseModel):
    package: SceneParticipationPackage | None = None
    tiered_context: TieredCharacterContextPackage | None = None
    scene_memory_pack: SceneMemoryPack | None = None
    usage_records: list[MemoryRetrievalUsageRecord] = []
    promotion_report: ChapterMemoryPromotionReport | None = None
    promotion_candidates: list[ChapterMemoryPromotionCandidate] = []
    promotion_decisions: list[ChapterMemoryPromotionDecision] = []
    writeback_plans: list[TieredSceneMemoryWritePlan] = []
    writeback_entries: list[RoleSceneMemoryEntry] = []
    writeback_projection_ref: str = ""
    warnings: list[str] = []
    blocking_findings: list[str] = []


class MemoryCuratorAgentCompositeService:
    """M5 candidate-only Composite Agent wrapper for memory context evidence."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        registry_service: CompositeAgentRegistryService | None = None,
        participation_service: SceneParticipationPackageService | None = None,
        scene_memory_service: SceneMemoryService | None = None,
        chapter_memory_service: ChapterMemoryService | None = None,
        usage_service: MemoryRetrievalUsageService | None = None,
        promotion_service: ChapterMemoryPromotionService | None = None,
        writeback_service: TieredSceneMemoryWritebackService | None = None,
        integrator_service: CompositeIntegratorService | None = None,
        gate_pipeline_service: CompositeGatePipelineService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.registry_service = registry_service or CompositeAgentRegistryService()
        self.chapter_memory_service = chapter_memory_service or ChapterMemoryService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.scene_memory_service = scene_memory_service or SceneMemoryService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            chapter_memory_service=self.chapter_memory_service,
        )
        self.participation_service = (
            participation_service
            or SceneParticipationPackageService(
                store=self.store,
                data_dir=self.data_dir,
            )
        )
        policy_service = TieredMemoryRetrievalPolicyService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.usage_service = usage_service or MemoryRetrievalUsageService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            policy_service=policy_service,
        )
        self.promotion_service = promotion_service or ChapterMemoryPromotionService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            usage_service=self.usage_service,
            policy_service=policy_service,
        )
        self.writeback_service = writeback_service or TieredSceneMemoryWritebackService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.integrator_service = integrator_service or CompositeIntegratorService()
        self.gate_pipeline_service = gate_pipeline_service or CompositeGatePipelineService()

        self.last_resolved_inputs: MemoryCuratorResolvedInputs | None = None
        self.last_preliminary_result: CompositeAgentRunResult | None = None
        self.last_integrated_bundle: CompositeIntegratedOutputBundle | None = None
        self.last_integrator_report: CompositeIntegratorReport | None = None
        self.last_gate_pipeline_result: CompositeGatePipelineResult | None = None

    def run(self, request: CompositeAgentRunRequest) -> CompositeAgentRunResult:
        normalized = self.normalize_and_validate_request(request)
        resolved = self.resolve_memory_curator_inputs(normalized)
        self.assert_m5_runtime_contract(normalized, resolved)
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

    def run_for_scene_context(
        self,
        request: CompositeAgentRunRequest,
    ) -> CompositeAgentRunResult:
        return self.run(request.copy(update={"target_scope": "memory_scene_context"}))

    def inspect_promotion_candidates(
        self,
        request: CompositeAgentRunRequest,
    ) -> CompositeAgentRunResult:
        return self.run(
            request.copy(update={"target_scope": "memory_promotion_inspection"})
        )

    def plan_writeback_after_commit(
        self,
        request: CompositeAgentRunRequest,
    ) -> CompositeAgentRunResult:
        return self.run(request.copy(update={"target_scope": "memory_writeback_plan"}))

    def normalize_and_validate_request(
        self,
        request: CompositeAgentRunRequest,
    ) -> CompositeAgentRunRequest:
        normalized = self.registry_service.normalize_run_request(request)
        if normalized.agent_name != MEMORY_CURATOR_COMPOSITE_AGENT_NAME:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_WRONG_AGENT")
        if not normalized.dry_run:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_DRY_RUN_REQUIRED")
        if normalized.requested_authority_level not in {"read_only", "candidate"}:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_UNSAFE_AUTHORITY_LEVEL")
        if normalized.target_scope not in TARGET_SCOPES:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_TARGET_SCOPE_UNSUPPORTED")
        if not str(normalized.project_id or "").strip():
            raise StorageError("COMPOSITE_MEMORY_CURATOR_PROJECT_ID_REQUIRED")
        if not str(normalized.chapter_id or "").strip():
            raise StorageError("COMPOSITE_MEMORY_CURATOR_CHAPTER_ID_REQUIRED")
        if (
            normalized.requested_output_contract_id
            and normalized.requested_output_contract_id != COMPOSITE_AGENT_OUTPUT_CONTRACT_ID
        ):
            raise StorageError("COMPOSITE_MEMORY_CURATOR_OUTPUT_CONTRACT_MISMATCH")
        if normalized.target_scope in {"memory_scene_context", "memory_writeback_plan"}:
            if int(normalized.scene_index or 0) < 1:
                raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_INDEX_REQUIRED")
            if not str(normalized.scene_id or "").strip():
                raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_ID_REQUIRED")
        return normalized

    def resolve_memory_curator_inputs(
        self,
        request: CompositeAgentRunRequest,
    ) -> MemoryCuratorResolvedInputs:
        if request.target_scope == "memory_scene_context":
            return self.run_scene_context_resolution(request)
        if request.target_scope == "memory_promotion_inspection":
            return self.run_promotion_inspection_resolution(request)
        return self.run_writeback_plan_resolution(request)

    def run_scene_context_resolution(
        self,
        request: CompositeAgentRunRequest,
    ) -> MemoryCuratorResolvedInputs:
        response = self._resolve_scene_participation_package(request)
        package = response.package
        if package is None:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_PACKAGE_NOT_FOUND")
        package = self._assert_package_matches_request(request, package)
        scene_pack = self._resolve_or_build_scene_memory_pack(request, response)
        self._assert_scene_pack_matches_package(request, package, scene_pack)
        usage_records = self.usage_service.list_usage(request.chapter_id)
        promotion_report, promotion_candidates, promotion_decisions = (
            self.promotion_service.evaluate_chapter_promotions(request.chapter_id)
        )
        usage_records = self.usage_service.list_usage(request.chapter_id)
        return MemoryCuratorResolvedInputs(
            package=package,
            tiered_context=response.tiered_character_context_package,
            scene_memory_pack=scene_pack,
            usage_records=usage_records,
            promotion_report=promotion_report,
            promotion_candidates=promotion_candidates,
            promotion_decisions=promotion_decisions,
            warnings=response.warnings,
            blocking_findings=package.blocking_issues,
        )

    def run_promotion_inspection_resolution(
        self,
        request: CompositeAgentRunRequest,
    ) -> MemoryCuratorResolvedInputs:
        package_response = self._try_resolve_scene_participation_package(request)
        package = package_response.package if package_response else None
        scene_pack = None
        if package_response and package_response.package:
            package = self._assert_package_matches_request(request, package_response.package)
            scene_pack = self._resolve_or_build_scene_memory_pack(request, package_response)
        elif request.scene_index > 0:
            scene_pack = self._try_get_active_scene_pack(request)
        promotion_report, promotion_candidates, promotion_decisions = (
            self.promotion_service.evaluate_chapter_promotions(request.chapter_id)
        )
        usage_records = self.usage_service.list_usage(request.chapter_id)
        return MemoryCuratorResolvedInputs(
            package=package,
            tiered_context=(
                package_response.tiered_character_context_package
                if package_response
                else None
            ),
            scene_memory_pack=scene_pack,
            usage_records=usage_records,
            promotion_report=promotion_report,
            promotion_candidates=promotion_candidates,
            promotion_decisions=promotion_decisions,
            warnings=[],
        )

    def run_writeback_plan_resolution(
        self,
        request: CompositeAgentRunRequest,
    ) -> MemoryCuratorResolvedInputs:
        response = self._try_resolve_scene_participation_package(request)
        package = response.package if response else None
        if package is not None:
            package = self._assert_package_matches_request(request, package)
        plans = self._resolve_writeback_plans(request, package=package)
        entries: list[RoleSceneMemoryEntry] = []
        for plan in plans:
            for entry_id in plan.role_memory_entry_ids:
                try:
                    entries.append(self.writeback_service.get_entry(entry_id))
                except StorageError:
                    continue
        projection_ref = ""
        warnings: list[str] = []
        if not plans:
            if not self._has_persisted_committed_scene_evidence(
                request
            ) and not self._has_commit_boundary_preview_receipt(request):
                raise StorageError("COMPOSITE_MEMORY_CURATOR_COMMIT_RECEIPT_REQUIRED")
            projection_ref = self._writeback_projection_ref(request)
            warnings.append("writeback_plan_projection_only_no_persisted_plan")
        return MemoryCuratorResolvedInputs(
            package=package,
            tiered_context=(response.tiered_character_context_package if response else None),
            scene_memory_pack=(response.scene_memory_pack if response else None),
            writeback_plans=plans,
            writeback_entries=entries,
            writeback_projection_ref=projection_ref,
            warnings=warnings,
        )

    def assert_m5_runtime_contract(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> None:
        if request.target_scope == "memory_scene_context":
            if resolved.package is None or resolved.scene_memory_pack is None:
                raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_CONTEXT_UNRESOLVED")
        if request.target_scope == "memory_promotion_inspection":
            if any(
                not candidate.reference_only
                or candidate.creates_new_fact
                or str(candidate.safe_summary or "").casefold().find("raw_prompt") >= 0
                for candidate in resolved.promotion_candidates
            ):
                raise StorageError("COMPOSITE_MEMORY_CURATOR_PROMOTION_NOT_REFERENCE_ONLY")
        if request.target_scope == "memory_writeback_plan":
            for plan in resolved.writeback_plans:
                if not plan.no_pre_commit_write:
                    raise StorageError("COMPOSITE_MEMORY_CURATOR_WRITEBACK_PLAN_UNSAFE")
            for entry in resolved.writeback_entries:
                if entry.tier == "D" and entry.memory_density != "minimal":
                    raise StorageError("COMPOSITE_MEMORY_CURATOR_D_TIER_PLAN_NOT_MINIMAL")

    def project_sub_agent_traces(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> list[SubAgentTrace]:
        now = utc_now()
        package = resolved.package
        scene_pack = resolved.scene_memory_pack
        promotion_ids = [item.promotion_candidate_id for item in resolved.promotion_candidates]
        usage_ids = [item.usage_record_id for item in resolved.usage_records]
        write_plan_ids = [
            *[plan.tiered_scene_memory_write_plan_id for plan in resolved.writeback_plans],
            resolved.writeback_projection_ref,
        ]
        trace_specs = [
            (
                "ChapterMemoryPackReaderSubAgent",
                "chapter_memory_pack_projection",
                "evidence",
                "read_only",
                [scene_pack.chapter_memory_pack_id if scene_pack else ""],
                "Chapter memory pack reference was projected as read-only evidence.",
            ),
            (
                "SceneMemoryPackBuilderSubAgent",
                "scene_memory_pack_projection",
                "evidence",
                "read_only",
                [
                    scene_pack.scene_memory_pack_id if scene_pack else "",
                    package.scene_participation_package_id if package else "",
                ],
                "Scene memory pack was built or reused for selected participants.",
            ),
            (
                "MemoryRetrievalSubAgent",
                "memory_retrieval_bucket_projection",
                "memory_reference",
                "read_only",
                self._scene_memory_source_ids(scene_pack),
                "Memory retrieval buckets were projected as read-only references.",
            ),
            (
                "RetrievalUsageTrackerSubAgent",
                "retrieval_usage_projection",
                "evidence",
                "read_only",
                usage_ids,
                "Retrieval usage records were referenced as derived runtime evidence.",
            ),
            (
                "ChapterPromotionInspectorSubAgent",
                "chapter_promotion_projection",
                "candidate",
                "candidate",
                promotion_ids,
                "Chapter memory promotion candidates were inspected as reference-only candidates.",
            ),
            (
                "TieredWritebackPlanSubAgent",
                "tiered_writeback_plan_projection",
                "candidate",
                "candidate",
                write_plan_ids,
                "Tiered memory writeback plans were exposed as plan-only evidence.",
            ),
            (
                "MemoryAuthorityGuardSubAgent",
                "memory_authority_guard_projection",
                "gate_request",
                "candidate",
                self._unique(
                    [
                        *(item.memory_id for item in resolved.usage_records),
                        *promotion_ids,
                        *write_plan_ids,
                    ]
                ),
                "Memory authority guard preserved candidate-only memory boundaries.",
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
            result.append(
                SubAgentTrace(
                    sub_agent_name=sub_agent_name,
                    node_kind=node_kind,
                    output_type=output_type,
                    authority_level=authority_level,
                    confidence=0.84,
                    source_ids=self._unique(source_ids),
                    input_fingerprint=self._fingerprint(
                        request.run_id,
                        request.target_scope,
                        sub_agent_name,
                        str(order),
                    ),
                    output_summary=summary,
                    warnings=[],
                    created_at=now,
                )
            )
        return result

    def project_candidate_outputs(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        if resolved.scene_memory_pack is not None:
            outputs.extend(self._scene_memory_candidate_outputs(request, resolved))
        outputs.extend(self._usage_candidate_outputs(request, resolved))
        outputs.extend(self._promotion_candidate_outputs(request, resolved))
        outputs.extend(self._writeback_candidate_outputs(request, resolved))
        outputs.append(self._gate_request_candidate_output(request, resolved))
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
            version_id=MEMORY_CURATOR_COMPOSITE_WRAPPER_VERSION,
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
            safe_summary="MemoryCuratorAgent composite wrapper produced a dry-run trace.",
            warnings=result.warnings,
            created_at=utc_now(),
        )

    def _resolve_scene_participation_package(
        self,
        request: CompositeAgentRunRequest,
    ) -> SceneParticipationPrepareResponse:
        response = self._try_resolve_scene_participation_package(request)
        if response and response.package:
            return response
        current = self.participation_service.get_current_package(
            chapter_id=request.chapter_id,
            scene_index=request.scene_index,
        )
        if current.package is not None:
            return current
        prepared = self.participation_service.prepare_package(
            SceneParticipationPrepareRequest(
                chapter_id=request.chapter_id,
                scene_index=request.scene_index,
                scene_id=request.scene_id,
                force_refresh=False,
            )
        )
        if prepared.package is None:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_PACKAGE_NOT_FOUND")
        return prepared

    def _try_resolve_scene_participation_package(
        self,
        request: CompositeAgentRunRequest,
    ) -> SceneParticipationPrepareResponse | None:
        refs = self._unique([*request.input_refs, *request.source_context_ids])
        for ref in refs:
            try:
                response = self.participation_service.get_package(ref)
            except StorageError as exc:
                if "SCENE_PARTICIPATION_PACKAGE_NOT_FOUND" in str(exc):
                    continue
                raise
            if response.package:
                return response
        return None

    def _assert_package_matches_request(
        self,
        request: CompositeAgentRunRequest,
        package: SceneParticipationPackage,
    ) -> SceneParticipationPackage:
        if package.project_id != request.project_id:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_PROJECT_MISMATCH")
        if package.chapter_id != request.chapter_id:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_CHAPTER_MISMATCH")
        if request.scene_id and str(package.scene_id or "") != request.scene_id:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_MISMATCH")
        if request.scene_index > 0 and int(package.scene_index or 0) != request.scene_index:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_INDEX_MISMATCH")
        if package.status not in {"ready", "warning"}:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_PACKAGE_UNREADY")
        if not package.active_character_ids:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_ACTIVE_CHARACTERS_REQUIRED")
        return package

    def _resolve_or_build_scene_memory_pack(
        self,
        request: CompositeAgentRunRequest,
        response: SceneParticipationPrepareResponse,
    ) -> SceneMemoryPack:
        package = response.package
        if package is None:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_PACKAGE_NOT_FOUND")
        for ref in self._unique([*request.input_refs, *request.source_context_ids]):
            pack = self._try_get_scene_memory_pack(ref)
            if pack is not None and pack.status == "active":
                return pack
        if response.scene_memory_pack is not None:
            if response.scene_memory_pack.status == "active":
                return response.scene_memory_pack
        if package.scene_memory_pack_id:
            pack = self._try_get_scene_memory_pack(package.scene_memory_pack_id)
            if pack is not None and pack.status == "active":
                return pack
        active = self.scene_memory_service.get_active_scene_pack(
            request.chapter_id,
            request.scene_index,
        )
        if active is not None and set(active.active_character_ids) == set(
            package.active_character_ids
        ):
            return active
        return self.scene_memory_service.build_scene_pack(
            chapter_id=request.chapter_id,
            scene_index=request.scene_index,
            scene_id=request.scene_id,
            active_character_ids=package.active_character_ids,
            force_refresh=False,
            strict_active_character_ids=True,
        )

    def _try_get_active_scene_pack(
        self,
        request: CompositeAgentRunRequest,
    ) -> SceneMemoryPack | None:
        if request.scene_index < 1:
            return None
        return self.scene_memory_service.get_active_scene_pack(
            request.chapter_id,
            request.scene_index,
        )

    def _try_get_scene_memory_pack(self, pack_id: str) -> SceneMemoryPack | None:
        clean_id = str(pack_id or "").strip()
        if not clean_id:
            return None
        for raw in self.repositories.scene_memory_packs.list_packs():
            if not isinstance(raw, dict):
                continue
            if raw.get("scene_memory_pack_id") != clean_id:
                continue
            try:
                return SceneMemoryPack(**raw)
            except ValidationError as exc:
                raise StorageError("SceneMemoryPack JSON schema is invalid.") from exc
        return None

    def _assert_scene_pack_matches_package(
        self,
        request: CompositeAgentRunRequest,
        package: SceneParticipationPackage,
        pack: SceneMemoryPack,
    ) -> None:
        if pack.project_id != request.project_id:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_PROJECT_MISMATCH")
        if pack.chapter_id != request.chapter_id:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_CHAPTER_MISMATCH")
        if request.scene_id and str(pack.scene_id or "") != request.scene_id:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_MISMATCH")
        if int(pack.scene_index or 0) != request.scene_index:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_INDEX_MISMATCH")
        if set(pack.active_character_ids) != set(package.active_character_ids):
            raise StorageError("COMPOSITE_MEMORY_CURATOR_SCENE_MEMORY_ACTIVE_ID_MISMATCH")

    def _resolve_writeback_plans(
        self,
        request: CompositeAgentRunRequest,
        *,
        package: SceneParticipationPackage | None,
    ) -> list[TieredSceneMemoryWritePlan]:
        refs = self._unique([*request.input_refs, *request.source_context_ids])
        plans: list[TieredSceneMemoryWritePlan] = []
        for ref in refs:
            try:
                plan = self.writeback_service.get_plan(ref)
            except StorageError as exc:
                if "TIERED_MEMORY_WRITEBACK_PLAN_NOT_FOUND" in str(exc):
                    continue
                raise
            self._assert_writeback_plan_matches_request(
                request,
                plan,
                package=package,
            )
            plans.append(plan)
        if plans:
            return plans
        return [
            plan
            for plan in self.writeback_service.list_plans(scene_id=request.scene_id)
            if self._writeback_plan_matches_request(
                request,
                plan,
                package=package,
            )
        ]

    def _assert_writeback_plan_matches_request(
        self,
        request: CompositeAgentRunRequest,
        plan: TieredSceneMemoryWritePlan,
        *,
        package: SceneParticipationPackage | None,
    ) -> None:
        if plan.project_id != request.project_id:
            raise StorageError(
                "COMPOSITE_MEMORY_CURATOR_WRITEBACK_PLAN_PROJECT_MISMATCH"
            )
        if plan.chapter_id != request.chapter_id:
            raise StorageError(
                "COMPOSITE_MEMORY_CURATOR_WRITEBACK_PLAN_CHAPTER_MISMATCH"
            )
        if plan.scene_id != request.scene_id:
            raise StorageError("COMPOSITE_MEMORY_CURATOR_WRITEBACK_PLAN_SCENE_MISMATCH")
        if int(plan.scene_index or 0) != request.scene_index:
            raise StorageError(
                "COMPOSITE_MEMORY_CURATOR_WRITEBACK_PLAN_SCENE_INDEX_MISMATCH"
            )
        if (
            package is not None
            and plan.scene_participation_package_id
            != package.scene_participation_package_id
        ):
            raise StorageError(
                "COMPOSITE_MEMORY_CURATOR_WRITEBACK_PLAN_PACKAGE_MISMATCH"
            )

    def _writeback_plan_matches_request(
        self,
        request: CompositeAgentRunRequest,
        plan: TieredSceneMemoryWritePlan,
        *,
        package: SceneParticipationPackage | None,
    ) -> bool:
        try:
            self._assert_writeback_plan_matches_request(
                request,
                plan,
                package=package,
            )
        except StorageError:
            return False
        return True

    def _has_persisted_committed_scene_evidence(
        self,
        request: CompositeAgentRunRequest,
    ) -> bool:
        scene_payload = self.repositories.scenes.get_by_id(request.scene_id)
        if not isinstance(scene_payload, dict):
            return False
        try:
            scene = Scene(**scene_payload)
        except ValidationError:
            return False
        return (
            scene.project_id == request.project_id
            and scene.chapter_id == request.chapter_id
            and scene.scene_id == request.scene_id
            and int(scene.scene_index or 0) == request.scene_index
            and scene.status in {"confirmed", "revised", "temporary_confirmed"}
        )

    def _has_commit_boundary_preview_receipt(
        self,
        request: CompositeAgentRunRequest,
    ) -> bool:
        return any(
            str(ref or "").startswith("commit_boundary_preview_")
            for ref in self._unique([*request.input_refs, *request.source_context_ids])
        )

    def _writeback_projection_ref(self, request: CompositeAgentRunRequest) -> str:
        return (
            f"writeback_plan_projection_{self._short_hash(request.run_id + ':' + request.scene_id)}"
        )

    def _scene_memory_candidate_outputs(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> list[dict[str, Any]]:
        pack = resolved.scene_memory_pack
        if pack is None:
            return []
        outputs = [
            self._candidate_payload(
                request=request,
                candidate_id=f"{request.run_id}_scene_memory_pack_reference",
                source_sub_agent="SceneMemoryPackBuilderSubAgent",
                source_object_type="scene_memory_pack",
                source_object_id=pack.scene_memory_pack_id,
                semantic_key=f"scene_memory_pack:{pack.scene_memory_pack_id}",
                output_type="memory_reference",
                truth_status="evidence",
                authority_level="read_only",
                tier="scene",
                budget_scope="scene_memory_pack_reference",
                evidence_refs=[pack.scene_memory_pack_id, pack.chapter_memory_pack_id],
                source_ids=[pack.scene_memory_pack_id, pack.chapter_memory_pack_id],
                safe_summary="Scene memory pack reference is available for downstream writer context.",
                extra={
                    "active_character_ids": pack.active_character_ids,
                    "chapter_memory_pack_id": pack.chapter_memory_pack_id,
                },
            ),
            self._candidate_payload(
                request=request,
                candidate_id=f"{request.run_id}_retrieval_bucket_summary",
                source_sub_agent="MemoryRetrievalSubAgent",
                source_object_type="retrieval_bucket_summary",
                source_object_id=pack.scene_memory_pack_id,
                semantic_key=f"retrieval_buckets:{pack.scene_memory_pack_id}",
                output_type="memory_reference",
                truth_status="evidence",
                authority_level="read_only",
                tier="scene",
                budget_scope="retrieval_bucket_summary",
                evidence_refs=self._scene_memory_source_ids(pack),
                source_ids=[pack.scene_memory_pack_id],
                warnings=self._scene_memory_bucket_warnings(pack),
                safe_summary="Scene memory retrieval buckets were projected without changing story facts.",
                extra={
                    "must_use_memory_ids": pack.must_use_memory_ids,
                    "should_use_memory_ids": pack.should_use_memory_ids,
                    "optional_memory_ids": pack.optional_memory_ids,
                    "forbidden_or_conflict_memory_ids": pack.forbidden_or_conflict_memory_ids,
                    "provisional_memory_ids": pack.provisional_memory_ids,
                    "retrieval_gaps": [model_to_dict(gap) for gap in pack.retrieval_gaps],
                },
            ),
        ]
        return outputs

    def _usage_candidate_outputs(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for record in resolved.usage_records:
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_usage_{self._safe_id(record.usage_record_id)}",
                    source_sub_agent="RetrievalUsageTrackerSubAgent",
                    source_object_type="memory_retrieval_usage_record",
                    source_object_id=record.usage_record_id,
                    semantic_key=f"retrieval_usage:{record.canonical_key}",
                    output_type="evidence",
                    truth_status="evidence",
                    authority_level="read_only",
                    tier="memory",
                    budget_scope="retrieval_usage_record",
                    evidence_refs=[record.usage_record_id, record.memory_id],
                    source_ids=[record.usage_record_id, record.memory_id],
                    warnings=(
                        [f"blocked_promotion:{record.block_reason}"]
                        if record.blocked_from_normal_promotion
                        else []
                    ),
                    safe_summary="Retrieval usage was recorded as derived runtime evidence.",
                    extra={
                        "retrieval_count_in_chapter": record.retrieval_count_in_chapter,
                        "retrieved_by": record.retrieved_by,
                        "context_buckets_seen": record.context_buckets_seen,
                        "blocked_from_normal_promotion": record.blocked_from_normal_promotion,
                    },
                )
            )
        return outputs

    def _promotion_candidate_outputs(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for candidate in resolved.promotion_candidates:
            warnings = []
            if candidate.status == "blocked":
                warnings.append(f"blocked_promotion:{candidate.block_reason}")
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_promotion_{self._safe_id(candidate.promotion_candidate_id)}",
                    source_sub_agent="ChapterPromotionInspectorSubAgent",
                    source_object_type="chapter_memory_promotion_candidate",
                    source_object_id=candidate.promotion_candidate_id,
                    semantic_key=f"chapter_memory_promotion:{candidate.canonical_key}",
                    output_type="candidate",
                    truth_status="evidence",
                    authority_level="candidate",
                    tier="chapter",
                    budget_scope="chapter_promotion_candidate",
                    evidence_refs=[
                        candidate.promotion_candidate_id,
                        candidate.usage_record_id,
                        candidate.memory_id,
                    ],
                    source_ids=[
                        candidate.promotion_candidate_id,
                        candidate.usage_record_id,
                        candidate.memory_id,
                    ],
                    warnings=warnings,
                    blocking_findings=[],
                    safe_summary="Chapter memory promotion candidate is reference-only evidence.",
                    extra={
                        "promotion_status": candidate.status,
                        "reference_only_promotion": candidate.reference_only,
                        "creates_new_fact": candidate.creates_new_fact,
                        "copies_full_text": False,
                        "target_context_bucket": candidate.target_context_bucket,
                    },
                )
            )
        for decision in resolved.promotion_decisions:
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_promotion_decision_{self._safe_id(decision.promotion_decision_id)}",
                    source_sub_agent="ChapterPromotionInspectorSubAgent",
                    source_object_type="chapter_memory_promotion_decision",
                    source_object_id=decision.promotion_decision_id,
                    semantic_key=f"chapter_memory_promotion_decision:{decision.promotion_candidate_id}",
                    output_type="evidence",
                    truth_status="evidence",
                    authority_level="read_only",
                    tier="chapter",
                    budget_scope="chapter_promotion_decision_reference",
                    evidence_refs=[
                        decision.promotion_decision_id,
                        decision.promotion_candidate_id,
                    ],
                    source_ids=[
                        decision.promotion_decision_id,
                        decision.promotion_candidate_id,
                    ],
                    safe_summary="Chapter memory promotion decision was referenced without copying facts.",
                )
            )
        return outputs

    def _writeback_candidate_outputs(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for plan in resolved.writeback_plans:
            plan_entries = [
                entry
                for entry in resolved.writeback_entries
                if entry.role_scene_memory_entry_id in set(plan.role_memory_entry_ids)
            ]
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_writeback_plan_{self._safe_id(plan.tiered_scene_memory_write_plan_id)}",
                    source_sub_agent="TieredWritebackPlanSubAgent",
                    source_object_type="tiered_scene_memory_write_plan",
                    source_object_id=plan.tiered_scene_memory_write_plan_id,
                    semantic_key=f"tiered_writeback_plan:{plan.tiered_scene_memory_write_plan_id}",
                    output_type="candidate",
                    truth_status="evidence",
                    authority_level="candidate",
                    tier="scene",
                    budget_scope="writeback_plan_reference",
                    evidence_refs=[
                        plan.tiered_scene_memory_write_plan_id,
                        *plan.role_memory_entry_ids,
                    ],
                    source_ids=[
                        plan.tiered_scene_memory_write_plan_id,
                        *plan.role_memory_entry_ids,
                    ],
                    warnings=plan.warnings,
                    safe_summary="Tiered scene memory writeback plan was referenced as plan-only evidence.",
                    extra={
                        "plan_only": True,
                        "can_write_active_memory_directly": False,
                        "requires_scene_commit_receipt": True,
                        "requires_gate_receipt": True,
                        "entry_counts_by_tier": self._entry_counts_by_tier(plan_entries),
                        "d_tier_plan_depth": "minimal",
                        "target_memory_record_ids": plan.target_memory_record_ids,
                    },
                )
            )
            for entry in plan_entries:
                outputs.append(
                    self._candidate_payload(
                        request=request,
                        candidate_id=f"{request.run_id}_role_memory_entry_{self._safe_id(entry.role_scene_memory_entry_id)}",
                        source_sub_agent="TieredWritebackPlanSubAgent",
                        source_object_type="role_scene_memory_entry_plan",
                        source_object_id=entry.role_scene_memory_entry_id,
                        semantic_key=f"role_memory_entry_plan:{entry.role_scene_memory_entry_id}",
                        output_type="candidate",
                        truth_status=(
                            "subjective_claim"
                            if entry.truth_status != "objective_fact"
                            else "evidence"
                        ),
                        authority_level="candidate",
                        tier=entry.tier,
                        budget_scope="role_memory_entry_plan",
                        evidence_refs=[
                            entry.role_scene_memory_entry_id,
                            plan.tiered_scene_memory_write_plan_id,
                            *entry.source_story_information_item_ids,
                        ],
                        source_ids=[
                            entry.role_scene_memory_entry_id,
                            plan.tiered_scene_memory_write_plan_id,
                        ],
                        warnings=entry.warnings,
                        safe_summary="Role memory entry was referenced as plan-only evidence.",
                        extra={
                            "memory_density": entry.memory_density,
                            "entry_status": entry.status,
                            "plan_only": True,
                            "target_memory_record_id": entry.target_memory_record_id,
                        },
                    )
                )
        if resolved.writeback_projection_ref:
            outputs.append(
                self._candidate_payload(
                    request=request,
                    candidate_id=f"{request.run_id}_writeback_plan_projection",
                    source_sub_agent="TieredWritebackPlanSubAgent",
                    source_object_type="writeback_plan_projection",
                    source_object_id=resolved.writeback_projection_ref,
                    semantic_key=f"writeback_plan_projection:{request.scene_id}",
                    output_type="candidate",
                    truth_status="evidence",
                    authority_level="candidate",
                    tier="scene",
                    budget_scope="writeback_plan_projection",
                    evidence_refs=[resolved.writeback_projection_ref],
                    source_ids=[resolved.writeback_projection_ref],
                    warnings=["projection_only_no_persisted_plan"],
                    safe_summary="Writeback plan projection was produced without persisting memory writes.",
                    extra={
                        "plan_only": True,
                        "can_write_active_memory_directly": False,
                        "requires_scene_commit_receipt": True,
                        "requires_gate_receipt": True,
                        "d_tier_plan_depth": "minimal",
                    },
                )
            )
        return outputs

    def _gate_request_candidate_output(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> dict[str, Any]:
        warnings = self._unique(
            [
                *resolved.warnings,
                *[
                    f"blocked_memory:{record.block_reason}"
                    for record in resolved.usage_records
                    if record.blocked_from_normal_promotion
                ],
            ]
        )
        return self._candidate_payload(
            request=request,
            candidate_id=f"{request.run_id}_memory_authority_gate_request",
            source_sub_agent="MemoryAuthorityGuardSubAgent",
            source_object_type="memory_authority_guard",
            source_object_id=request.run_id,
            semantic_key=f"memory_authority_guard:{request.run_id}",
            output_type="gate_request",
            truth_status="warning",
            authority_level="candidate",
            tier="memory",
            budget_scope="memory_authority_guard",
            evidence_refs=self._unique(
                [
                    *(record.usage_record_id for record in resolved.usage_records),
                    *(
                        candidate.promotion_candidate_id
                        for candidate in resolved.promotion_candidates
                    ),
                    *(
                        plan.tiered_scene_memory_write_plan_id
                        for plan in resolved.writeback_plans
                    ),
                    resolved.writeback_projection_ref,
                ]
            ),
            source_ids=[],
            warnings=warnings,
            blocking_findings=resolved.blocking_findings,
            safe_summary="Memory authority guard requires downstream gate review before use.",
        )

    def _build_preliminary_result(
        self,
        *,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
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
            output_refs=self._output_refs(request, resolved),
            blocking_findings=resolved.blocking_findings,
            warnings=resolved.warnings,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "MemoryCuratorAgent wrapper projected memory context and writeback "
                "plans into candidate-only composite outputs."
            ),
            created_at=utc_now(),
        )

    def _build_final_result(
        self,
        *,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
        preliminary: CompositeAgentRunResult,
        bundle: CompositeIntegratedOutputBundle,
        detailed_integrator_report: CompositeIntegratorReport,
        gate_pipeline_result: CompositeGatePipelineResult,
    ) -> CompositeAgentRunResult:
        integrator_report = IntegratorReport(
            integrator_report_id=f"m5_integrator_{self._short_hash(bundle.bundle_id)}",
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
            safe_summary="M5 wrapper integrated memory outputs through M2 dry review.",
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
                *resolved.blocking_findings,
                *bundle.blocking_findings,
                *[
                    finding.finding_code or finding.finding_type
                    for finding in gate_pipeline_result.blocking_findings
                ],
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
                ]
            ),
            blocking_findings=blocking_findings,
            warnings=self._unique(
                [
                    *resolved.warnings,
                    *bundle.warnings,
                    *gate_pipeline_result.warnings,
                    f"m2_overall_decision:{gate_pipeline_result.overall_decision}",
                ]
            ),
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary=(
                "MemoryCuratorAgent wrapper completed a candidate-only M2 dry-review pass."
            ),
            created_at=utc_now(),
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

    def _output_refs(
        self,
        request: CompositeAgentRunRequest,
        resolved: MemoryCuratorResolvedInputs,
    ) -> list[str]:
        return self._unique(
            [
                resolved.package.scene_participation_package_id
                if resolved.package
                else "",
                resolved.tiered_context.tiered_character_context_package_id
                if resolved.tiered_context
                else "",
                resolved.scene_memory_pack.scene_memory_pack_id
                if resolved.scene_memory_pack
                else "",
                resolved.scene_memory_pack.chapter_memory_pack_id
                if resolved.scene_memory_pack
                else "",
                *(record.usage_record_id for record in resolved.usage_records),
                *(
                    candidate.promotion_candidate_id
                    for candidate in resolved.promotion_candidates
                ),
                *(decision.promotion_decision_id for decision in resolved.promotion_decisions),
                resolved.promotion_report.promotion_report_id
                if resolved.promotion_report
                else "",
                *(
                    plan.tiered_scene_memory_write_plan_id
                    for plan in resolved.writeback_plans
                ),
                *(entry.role_scene_memory_entry_id for entry in resolved.writeback_entries),
                resolved.writeback_projection_ref,
            ]
        )

    def _scene_memory_source_ids(self, pack: SceneMemoryPack | None) -> list[str]:
        if pack is None:
            return []
        return self._unique(
            [
                *pack.must_use_memory_ids,
                *pack.should_use_memory_ids,
                *pack.optional_memory_ids,
                *pack.forbidden_or_conflict_memory_ids,
                *pack.provisional_memory_ids,
                pack.scene_memory_pack_id,
                pack.chapter_memory_pack_id,
            ]
        )

    def _scene_memory_bucket_warnings(self, pack: SceneMemoryPack) -> list[str]:
        warnings: list[str] = []
        if pack.forbidden_or_conflict_memory_ids:
            warnings.append("forbidden_or_conflict_memory_reference_present")
        if pack.provisional_memory_ids:
            warnings.append("provisional_memory_reference_present")
        if pack.retrieval_gaps:
            warnings.append("retrieval_gap_present")
        return warnings

    def _entry_counts_by_tier(
        self,
        entries: list[RoleSceneMemoryEntry],
    ) -> dict[str, int]:
        counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        for entry in entries:
            if entry.tier in counts:
                counts[entry.tier] += 1
        return counts

    def _average_confidence(self, bundle: CompositeIntegratedOutputBundle) -> float:
        values = [candidate.confidence for candidate in bundle.integrated_candidates]
        if not values:
            return 1.0
        return round(sum(values) / len(values), 4)

    def _fingerprint(self, *parts: str) -> str:
        return f"m5_{self._short_hash(':'.join(str(part or '') for part in parts))}"

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
