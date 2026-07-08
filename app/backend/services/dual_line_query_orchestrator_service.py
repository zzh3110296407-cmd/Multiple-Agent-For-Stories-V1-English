from __future__ import annotations

from typing import Any

from app.backend.models.dual_line_query import (
    CandidateFusionResult,
    CandidateFusionSource,
    ContextPackCacheInvalidationEvidence,
    ContextPackInvalidationEvidence,
    DualLineAdapterIntegrationResult,
    DualLineAdapterRequest,
    RuntimeSceneGenerationConsumptionEvidence,
    WriteAgentContextPack,
    build_context_pack_cache_invalidation_evidence,
    build_forbidden_usage_quality_gate_evidence,
    build_runtime_scene_generation_consumption_evidence,
    build_runtime_scene_generation_context_payload,
    build_write_agent_context_pack,
    fuse_and_gate_candidates,
)
from app.backend.models.library_retrieval import (
    LibraryRelationshipExpansionRequest,
    LibraryRetrievalFilters,
    LibraryRetrievalGapRequest,
    LibraryRetrievalSearchRequest,
    LibraryRetrievalUsageLogRequest,
    LibraryTextRetrievalRequest,
)
from app.backend.services.library_retrieval_indexing_service import LibraryRetrievalIndexingService
from app.backend.services.library_retrieval_service import LibraryRetrievalService
from app.backend.services.temporal_resolver_service import TemporalResolverService


class DualLineQueryOrchestratorService:
    """Thin M12 adapter layer over M10 and M11 contracts.

    The service intentionally does not expose WriterAgent-ready facts. Runtime
    consumption is opt-in and only accepts the final gated context pack.
    """

    def __init__(
        self,
        *,
        temporal_resolver_service: Any | None = None,
        library_retrieval_service: Any | None = None,
        library_indexing_service: Any | None = None,
    ) -> None:
        self.temporal_resolver_service = temporal_resolver_service or TemporalResolverService()
        self.library_retrieval_service = library_retrieval_service or LibraryRetrievalService()
        self.library_indexing_service = library_indexing_service or LibraryRetrievalIndexingService()

    def collect_adapter_context(self, request: DualLineAdapterRequest) -> DualLineAdapterIntegrationResult:
        intent = request.intent
        project_id = intent.project_id
        temporal_call_names: list[str] = []
        library_call_names: list[str] = []
        gaps: list[str] = []
        temporal_result_count = 0
        library_candidate_count = 0
        pack_item_count = 0

        for character_id in intent.characters:
            temporal_call_names.append("get_character_visible_memory")
            response = self.temporal_resolver_service.get_character_visible_memory(
                project_id=project_id,
                character_id=character_id,
                timeline_id=intent.timeline_id,
                world_time_sort_key=request.world_time_sort_key,
                knowledge_time_sort_key=request.knowledge_time_sort_key,
                narrative_sequence_key=request.narrative_sequence_key,
                limit=intent.max_items,
            )
            temporal_result_count += _result_count(response, "memories")
            gaps.extend(_response_gaps(response))

        for location_id in intent.locations:
            temporal_call_names.append("get_location_state_at_time")
            response = self.temporal_resolver_service.get_location_state_at_time(
                project_id=project_id,
                location_id=location_id,
                timeline_id=intent.timeline_id,
                world_time_sort_key=request.world_time_sort_key,
            )
            temporal_result_count += _result_count(response, "state")
            gaps.extend(_response_gaps(response))

        for ref in request.reader_disclosure_refs:
            temporal_call_names.append("get_reader_disclosure_status")
            response = self.temporal_resolver_service.get_reader_disclosure_status(
                project_id=project_id,
                entity_type=_ref_value(ref, "entity_type"),
                entity_id=_ref_value(ref, "entity_id"),
                narrative_sequence_key=request.narrative_sequence_key,
            )
            temporal_result_count += _result_count(response, "evidence")
            gaps.extend(_response_gaps(response))

        for ref in request.version_status_refs:
            temporal_call_names.append("get_timeline_node_version_status")
            response = self.temporal_resolver_service.get_timeline_node_version_status(
                project_id=project_id,
                node_type=_ref_value(ref, "node_type"),
                node_id=_ref_value(ref, "node_id"),
            )
            temporal_result_count += 1 if getattr(response, "usable_for_writer", False) else 0
            gaps.extend(_response_gaps(response))

        filters = LibraryRetrievalFilters(
            chapter_ids=[intent.chapter_id] if intent.chapter_id else [],
            scene_ids=[intent.scene_id] if intent.scene_id else [],
            character_ids=list(intent.characters),
            location_ids=list(intent.locations),
        )
        library_call_names.append("search_library_cards")
        structured_response = self.library_retrieval_service.search_library_cards(
            LibraryRetrievalSearchRequest(
                project_id=project_id,
                retrieval_task_id=intent.retrieval_task_id,
                filters=filters,
                max_items=intent.max_items,
                token_budget=intent.token_budget,
                include_cards=True,
                include_documents=True,
            )
        )
        library_candidate_count += _result_count(structured_response, "candidates")
        gaps.extend(_response_gaps(structured_response))

        if request.query_text:
            library_call_names.append("search_library_text")
            text_response = self.library_retrieval_service.search_library_text(
                LibraryTextRetrievalRequest(
                    project_id=project_id,
                    retrieval_task_id=intent.retrieval_task_id,
                    query_text=request.query_text,
                    filters=filters,
                    max_items=intent.max_items,
                    token_budget=intent.token_budget,
                )
            )
            library_candidate_count += _result_count(text_response, "candidates")
            gaps.extend(_response_gaps(text_response))

            library_call_names.append("search_library_relationships")
            relationship_response = self.library_retrieval_service.search_library_relationships(
                LibraryRelationshipExpansionRequest(
                    project_id=project_id,
                    retrieval_task_id=intent.retrieval_task_id,
                    query_text=request.query_text,
                    filters=filters,
                    max_items=intent.max_items,
                    token_budget=intent.token_budget,
                )
            )
            library_candidate_count += _result_count(relationship_response, "candidates")
            gaps.extend(_response_gaps(relationship_response))
        else:
            gaps.append("M12_ADAPTER_QUERY_TEXT_MISSING")

        for ref in request.pack_refs:
            library_call_names.append("get_pack")
            pack = self.library_retrieval_service.get_pack(
                project_id=project_id,
                pack_type=_ref_value(ref, "pack_type"),
                pack_id=_ref_value(ref, "pack_id"),
            )
            pack_item_count += len(getattr(pack, "items", []) or [])

        usage_logged = False
        if request.log_usage:
            library_call_names.append("record_retrieval_usage")
            self.library_retrieval_service.record_retrieval_usage(
                LibraryRetrievalUsageLogRequest(
                    project_id=project_id,
                    retrieval_usage_id=f"m12_adapter_usage_{intent.query_intent_id}",
                    retrieval_task_id=intent.retrieval_task_id,
                    query_text=request.query_text,
                    candidate_count=library_candidate_count,
                    selected_count=0,
                    used_entity_refs=[],
                    ignored_entity_refs=[],
                    missing_requirements=list(gaps),
                    source_refs=list(intent.source_refs),
                    metadata={
                        "m12Task": "Task 3",
                        "boundary": "adapter_usage_only_not_runtime_consumption",
                    },
                )
            )
            usage_logged = True

        gap_logged = False
        if request.log_gap_for_missing_context and gaps:
            library_call_names.append("record_retrieval_gap")
            self.library_retrieval_service.record_retrieval_gap(
                LibraryRetrievalGapRequest(
                    project_id=project_id,
                    retrieval_gap_id=f"m12_adapter_gap_{intent.query_intent_id}",
                    retrieval_task_id=intent.retrieval_task_id,
                    scene_id=intent.scene_id,
                    gap_type="M12_CONTEXT_MISSING",
                    claim_text="M12 adapter observed missing temporal or retrieval context.",
                    searched_scopes=[
                        "M10 Temporal Resolver",
                        "M11 Library Retriever",
                    ],
                    recommended_resolution="Keep gap explicit until Task 4/5 can gate and package context.",
                    source_refs=list(intent.source_refs),
                    metadata={
                        "m12Task": "Task 3",
                        "boundary": "gap_logging_hook_only",
                    },
                )
            )
            gap_logged = True

        library_call_names.append("get_semantic_retrieval_boundary")
        semantic_boundary = self.library_retrieval_service.get_semantic_retrieval_boundary()

        return DualLineAdapterIntegrationResult(
            project_id=project_id,
            query_intent_id=intent.query_intent_id,
            temporal_resolver_adapter_ready=all(
                name in temporal_call_names
                for name in [
                    "get_character_visible_memory",
                    "get_location_state_at_time",
                    "get_reader_disclosure_status",
                    "get_timeline_node_version_status",
                ]
            ),
            library_retriever_adapter_ready=all(
                name in library_call_names
                for name in [
                    "search_library_cards",
                    "search_library_text",
                    "search_library_relationships",
                    "get_pack",
                    "record_retrieval_usage",
                    "record_retrieval_gap",
                    "get_semantic_retrieval_boundary",
                ]
            ),
            temporal_call_names=temporal_call_names,
            library_call_names=library_call_names,
            temporal_result_count=temporal_result_count,
            library_candidate_count=library_candidate_count,
            pack_item_count=pack_item_count,
            usage_logged=usage_logged,
            gap_logged=gap_logged,
            semantic_boundary_checked=True,
            semantic_retrieval_mode=str(getattr(semantic_boundary, "semantic_retrieval_mode", "optional_hook_only") or ""),
            semantic_score_can_override_hard_gates=bool(
                getattr(semantic_boundary, "semantic_score_can_override_hard_gates", False)
            ),
            m10_hard_gate_preserved=True,
            m11_candidates_are_writer_facts=False,
            writer_agent_fact_ready=False,
            runtime_scene_generation_consumed=False,
            raw_database_rows_exposed=False,
            gaps=sorted(set(gaps)),
        )

    def run_controlled_library_index_live_refresh_smoke(self, *, project_id: str = "") -> dict[str, Any]:
        result = self.library_indexing_service.refresh_catalog_and_cards(project_id=project_id)
        return {
            "projectId": result.project_id,
            "searchDocumentSourceCount": len(result.search_document_sources),
            "searchMemoryCardSourceCount": len(result.search_memory_card_sources),
            "searchDocumentsUpserted": result.search_documents_upserted,
            "searchDocumentsArchived": result.search_documents_archived,
            "searchMemoryCardsUpserted": result.search_memory_cards_upserted,
            "searchMemoryCardsArchived": result.search_memory_cards_archived,
            "rawLongProsePrimarySurface": result.raw_long_prose_primary_surface,
            "writerAgentFactReady": result.writer_agent_fact_ready,
        }

    def fuse_and_gate_candidates(
        self,
        *,
        project_id: str,
        query_intent_id: str,
        candidates: list[CandidateFusionSource],
        max_items: int = 20,
    ) -> CandidateFusionResult:
        return fuse_and_gate_candidates(
            project_id=project_id,
            query_intent_id=query_intent_id,
            candidates=candidates,
            max_items=max_items,
        )

    def build_write_agent_context_pack(
        self,
        *,
        project_id: str,
        query_intent_id: str,
        query_orchestration_run_id: str,
        fusion_result: CandidateFusionResult,
        context_pack_id: str = "",
        token_budget: int = 1200,
        max_items: int = 20,
    ) -> WriteAgentContextPack:
        return build_write_agent_context_pack(
            project_id=project_id,
            query_intent_id=query_intent_id,
            query_orchestration_run_id=query_orchestration_run_id,
            fusion_result=fusion_result,
            context_pack_id=context_pack_id,
            token_budget=token_budget,
            max_items=max_items,
        )

    def build_runtime_scene_generation_approved_context_payload(
        self,
        *,
        context_pack: WriteAgentContextPack,
    ) -> dict[str, Any]:
        return build_runtime_scene_generation_context_payload(context_pack)

    def consume_context_pack_for_runtime_scene_generation(
        self,
        *,
        project_id: str,
        scene_id: str,
        context_pack: WriteAgentContextPack,
    ) -> RuntimeSceneGenerationConsumptionEvidence:
        return build_runtime_scene_generation_consumption_evidence(
            project_id=project_id,
            scene_id=scene_id,
            context_pack=context_pack,
        )

    def run_forbidden_usage_quality_gate(
        self,
        *,
        project_id: str,
        scene_id: str,
        context_pack: WriteAgentContextPack,
        generated_prose_text: str,
        story_information_texts: list[str] | None = None,
        missing_required_context: list[str] | None = None,
        prose_fallback_used: bool = False,
        prose_fallback_reason: str = "",
    ) -> Any:
        return build_forbidden_usage_quality_gate_evidence(
            project_id=project_id,
            scene_id=scene_id,
            context_pack=context_pack,
            generated_prose_text=generated_prose_text,
            story_information_texts=story_information_texts,
            missing_required_context=missing_required_context,
            prose_fallback_used=prose_fallback_used,
            prose_fallback_reason=prose_fallback_reason,
        )

    def build_context_pack_cache_invalidation_evidence(
        self,
        *,
        project_id: str,
        scene_id: str,
        context_pack: WriteAgentContextPack,
        prewarm_scene_ids: list[str] | None = None,
        invalidation_events: list[ContextPackInvalidationEvidence] | None = None,
    ) -> ContextPackCacheInvalidationEvidence:
        return build_context_pack_cache_invalidation_evidence(
            project_id=project_id,
            scene_id=scene_id,
            context_pack=context_pack,
            prewarm_scene_ids=prewarm_scene_ids,
            invalidation_events=invalidation_events,
        )


def _ref_value(ref: dict[str, Any], key: str) -> str:
    return str(ref.get(key) or "").strip()


def _response_gaps(response: Any) -> list[str]:
    gaps = getattr(response, "gaps", []) or []
    return [str(gap).strip() for gap in gaps if str(gap).strip()]


def _result_count(response: Any, collection_field: str) -> int:
    if hasattr(response, "result_count"):
        try:
            return int(getattr(response, "result_count") or 0)
        except (TypeError, ValueError):
            return 0
    if hasattr(response, "candidate_count"):
        try:
            return int(getattr(response, "candidate_count") or 0)
        except (TypeError, ValueError):
            return 0
    value = getattr(response, collection_field, None)
    if isinstance(value, list):
        return len(value)
    return 1 if value is not None else 0
