from __future__ import annotations

from typing import Any

from app.backend.core.config import STORAGE_MODE_POSTGRES_PRIMARY, settings
from app.backend.models.library_retrieval import (
    LibraryPack,
    LibraryPackBuildRequest,
    LibraryPackItem,
    LibraryPackStaleRequest,
    LibraryPackStaleResponse,
    LibraryRelationshipExpansionRequest,
    LibraryRetrievalCandidate,
    LibraryRetrievalFilters,
    LibraryRetrievalGapRecord,
    LibraryRetrievalGapRequest,
    LibraryRetrievalScope,
    LibraryRetrievalSearchRequest,
    LibraryRetrievalSearchResponse,
    LibraryRetrievalTaskSpec,
    LibraryRetrievalTaskSpecPayload,
    LibraryRetrievalUsageLogRequest,
    LibraryRetrievalUsageRecord,
    LibrarySemanticRetrievalBoundary,
    LibraryTextRetrievalRequest,
)
from app.backend.repositories.postgres_normalized_repositories import PostgresConnectionFactory
from app.backend.services.runtime_project_mapping import resolve_runtime_project_mapping, validate_runtime_project_id
from app.backend.storage.json_store import StorageError


WRITER_SAFE_AUTHORITY_LEVELS = ("USER_LOCKED", "USER_CONFIRMED", "FORMAL_APPLIED", "SYSTEM_CONFIRMED")
WRITER_SAFE_VISIBILITY_STATUSES = ("KNOWN", "RESTORED")
ACTIVE_STATUS_EXCLUSIONS = ("SUPERSEDED", "ARCHIVED", "DELETED", "REJECTED")
MAX_STRUCTURED_RETRIEVAL_ITEMS = 100
MAX_STRUCTURED_RETRIEVAL_TOKEN_BUDGET = 20_000
TEXT_RETRIEVAL_MODES = ("EXACT", "ALIAS", "KEYWORD", "TAG", "FULL_TEXT")
DEFAULT_RELATIONSHIP_LINK_TYPES = (
    "RELATES_TO",
    "SAME_LOCATION",
    "FORESHADOWING",
    "CONTINUITY_RELATED",
    "SUPPORTS",
    "CONTRADICTS",
)
PROSE_FALLBACK_WARNING = "M11_PROSE_FALLBACK_WARNING_NOT_PRIMARY_PATH"
PROSE_FALLBACK_GAP_TYPE = "ACCEPTED_PROSE_FALLBACK"
RETRIEVAL_GAP_TYPES = (
    "MISSING_EVENT_CONTEXT",
    "MISSING_STATE_CONTEXT",
    "MISSING_RELATIONSHIP_CONTEXT",
    "MISSING_SOURCE_CONTEXT",
    PROSE_FALLBACK_GAP_TYPE,
)
SEMANTIC_RETRIEVAL_MODE = "optional_hook_only"
SEMANTIC_RETRIEVAL_ALLOWED_MODES = ("deferred", "optional_hook_only", "ready", "unsupported_in_this_slice")
SEMANTIC_RETRIEVAL_EMBEDDING_REF_STORAGE = "search_documents.metadata.embedding_ref/search_memory_cards.metadata.embedding_ref"
SEMANTIC_RETRIEVAL_WARNING = (
    "M11 semantic hook is optional metadata only; semantic score cannot override M10/M12 hard gates."
)


class LibraryRetrievalService:
    def __init__(self, *, connection_factory: PostgresConnectionFactory | None = None) -> None:
        self._connection_factory = connection_factory
        self.schema_name = connection_factory.schema_name if connection_factory is not None else "mas_phase875_proto"

    def search_library_cards(self, request: LibraryRetrievalSearchRequest) -> LibraryRetrievalSearchResponse:
        project_id = self._resolve_project_id(request.project_id)
        self._ensure_postgres_primary_mode()
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, project_id)
            task_spec = self._load_task_spec(conn, project_uuid, request.retrieval_task_id) if request.retrieval_task_id else None
            base_filters = task_spec.filters if task_spec else None
            if request.task_spec:
                base_filters = self._merge_filters(base_filters, request.task_spec.filters)
            effective_filters = self._merge_filters(base_filters, request.filters)
            effective_max_items = self._bounded_max_items(
                request.max_items,
                task_spec.max_items if task_spec else None,
                request.task_spec.max_items if request.task_spec else None,
            )
            effective_token_budget = self._bounded_token_budget(
                request.token_budget,
                task_spec.token_budget if task_spec else None,
                request.task_spec.token_budget if request.task_spec else None,
            )
            sql, params, filters_applied = self._search_candidates_sql_and_params(
                project_uuid=project_uuid,
                filters=effective_filters,
                max_items=effective_max_items,
                include_cards=request.include_cards,
                include_documents=request.include_documents,
            )
            rows = self._fetchall(conn.execute(sql, params))
        candidates, total_tokens, truncated_by_token_budget = self._candidates_within_budget(
            [self._candidate_from_row(row) for row in rows],
            effective_token_budget,
        )
        return LibraryRetrievalSearchResponse(
            scope=self._scope(project_id),
            retrieval_task_id=request.retrieval_task_id or (request.task_spec.retrieval_task_id if request.task_spec else ""),
            effective_max_items=effective_max_items,
            effective_token_budget=effective_token_budget,
            candidate_count=len(candidates),
            total_token_estimate=total_tokens,
            truncated_by_max_items=len(rows) >= effective_max_items,
            truncated_by_token_budget=truncated_by_token_budget,
            candidates=candidates,
            filters_applied=filters_applied
            + [
                "project_id",
                "active_status",
                "active_lifecycle",
                "authority_allowlist",
                "visibility_allowlist",
                "parameterized_sql",
                "m10_temporal_resolver_hard_gate",
            ],
            gaps=[] if candidates else ["NO_STRUCTURED_RETRIEVAL_CANDIDATES_MATCHED"],
        )

    def search_library_text(self, request: LibraryTextRetrievalRequest) -> LibraryRetrievalSearchResponse:
        project_id = self._resolve_project_id(request.project_id)
        self._ensure_postgres_primary_mode()
        full_text_gap = "FULL_TEXT_MODE_DISABLED_BY_REQUEST" if "FULL_TEXT" in request.modes and not request.allow_full_text else ""
        full_text_mode = (
            "postgres_tsvector"
            if "FULL_TEXT" in request.modes and request.allow_full_text
            else "disabled_by_request"
            if "FULL_TEXT" in request.modes
            else "not_requested"
        )
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, project_id)
            task_spec = self._load_task_spec(conn, project_uuid, request.retrieval_task_id) if request.retrieval_task_id else None
            effective_filters = self._merge_filters(task_spec.filters if task_spec else None, request.filters)
            effective_max_items = self._bounded_max_items(request.max_items, task_spec.max_items if task_spec else None)
            effective_token_budget = self._bounded_token_budget(
                request.token_budget,
                task_spec.token_budget if task_spec else None,
            )
            sql, params, filters_applied = self._text_candidates_sql_and_params(
                project_uuid=project_uuid,
                query_text=request.query_text,
                modes=request.modes,
                allow_full_text=request.allow_full_text,
                filters=effective_filters,
                max_items=effective_max_items,
            )
            rows = self._fetchall(conn.execute(sql, params))
        candidates, total_tokens, truncated_by_token_budget = self._candidates_within_budget(
            [self._candidate_from_row(row) for row in rows],
            effective_token_budget,
        )
        gaps = []
        if full_text_gap:
            gaps.append(full_text_gap)
        if not candidates:
            gaps.append("NO_TEXT_RETRIEVAL_CANDIDATES_MATCHED")
        return LibraryRetrievalSearchResponse(
            scope=self._scope(project_id),
            retrieval_task_id=request.retrieval_task_id,
            effective_max_items=effective_max_items,
            effective_token_budget=effective_token_budget,
            candidate_count=len(candidates),
            total_token_estimate=total_tokens,
            truncated_by_max_items=len(rows) >= effective_max_items,
            truncated_by_token_budget=truncated_by_token_budget,
            candidates=candidates,
            filters_applied=filters_applied
            + [
                "project_id",
                "active_status",
                "active_lifecycle",
                "authority_allowlist",
                "parameterized_sql",
                "m10_temporal_resolver_hard_gate",
                "dedupe_by_stable_source_identity",
                "top_k_before_source_expansion",
            ],
            retrieval_modes=request.modes,
            full_text_mode=full_text_mode,
            gaps=gaps,
        )

    def search_library_relationships(
        self,
        request: LibraryRelationshipExpansionRequest,
    ) -> LibraryRetrievalSearchResponse:
        project_id = self._resolve_project_id(request.project_id)
        self._ensure_postgres_primary_mode()
        full_text_gap = "FULL_TEXT_MODE_DISABLED_BY_REQUEST" if "FULL_TEXT" in request.modes and not request.allow_full_text else ""
        full_text_mode = (
            "postgres_tsvector"
            if "FULL_TEXT" in request.modes and request.allow_full_text
            else "disabled_by_request"
            if "FULL_TEXT" in request.modes
            else "not_requested"
        )
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, project_id)
            task_spec = self._load_task_spec(conn, project_uuid, request.retrieval_task_id) if request.retrieval_task_id else None
            effective_filters = self._merge_filters(task_spec.filters if task_spec else None, request.filters)
            effective_max_items = self._bounded_max_items(request.max_items, task_spec.max_items if task_spec else None)
            effective_token_budget = self._bounded_token_budget(
                request.token_budget,
                task_spec.token_budget if task_spec else None,
            )
            sql, params, filters_applied = self._expanded_candidates_sql_and_params(
                project_uuid=project_uuid,
                query_text=request.query_text,
                modes=request.modes,
                allow_full_text=request.allow_full_text,
                filters=effective_filters,
                max_items=effective_max_items,
                link_types=request.link_types,
                max_graph_distance=request.max_graph_distance,
            )
            rows = self._fetchall(conn.execute(sql, params))
        candidates, total_tokens, truncated_by_token_budget = self._candidates_within_budget(
            [self._candidate_from_row(row) for row in rows],
            effective_token_budget,
        )
        gaps = []
        if full_text_gap:
            gaps.append(full_text_gap)
        if request.max_graph_distance == 0:
            gaps.append("RELATIONSHIP_EXPANSION_DISABLED_BY_GRAPH_DISTANCE")
        if not candidates:
            gaps.append("NO_RELATIONSHIP_EXPANSION_CANDIDATES_MATCHED")
        return LibraryRetrievalSearchResponse(
            scope=self._scope(project_id),
            retrieval_task_id=request.retrieval_task_id,
            effective_max_items=effective_max_items,
            effective_token_budget=effective_token_budget,
            candidate_count=len(candidates),
            total_token_estimate=total_tokens,
            truncated_by_max_items=len(rows) >= effective_max_items,
            truncated_by_token_budget=truncated_by_token_budget,
            candidates=candidates,
            filters_applied=filters_applied
            + [
                "project_id",
                "active_status",
                "active_lifecycle",
                "authority_allowlist",
                "parameterized_sql",
                "m10_temporal_resolver_hard_gate",
                "seed_top_k_before_relationship_expansion",
                "relationship_link_type_allowlist",
                "relationship_weighted_ranking",
                "dedupe_by_stable_source_identity",
            ],
            retrieval_modes=list(request.modes) + ["RELATIONSHIP_EXPANSION"],
            full_text_mode=full_text_mode,
            gaps=gaps,
        )

    def create_or_refresh_pack(self, request: LibraryPackBuildRequest) -> LibraryPack:
        project_id = self._resolve_project_id(request.project_id)
        self._ensure_postgres_primary_mode()
        jsonb = self._active_connection_factory().jsonb_adapter()
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, project_id)
            root_id = self._upsert_pack_root(conn, project_uuid, request, jsonb)
            self._soft_delete_existing_pack_items(conn, project_uuid, request.pack_type, root_id)
            for index, item in enumerate(request.items, start=1):
                self._upsert_pack_item(conn, project_uuid, request, root_id, item, index, jsonb)
            return self._load_pack(conn, project_id, project_uuid, request.pack_type, request.pack_id)

    def get_pack(self, *, project_id: str = "", pack_type: str, pack_id: str) -> LibraryPack:
        active_project_id = self._resolve_project_id(project_id)
        self._ensure_postgres_primary_mode()
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, active_project_id)
            return self._load_pack(conn, active_project_id, project_uuid, str(pack_type or "").strip().upper(), pack_id)

    def mark_packs_stale(self, request: LibraryPackStaleRequest) -> LibraryPackStaleResponse:
        project_id = self._resolve_project_id(request.project_id)
        self._ensure_postgres_primary_mode()
        jsonb = self._active_connection_factory().jsonb_adapter()
        stale_count = 0
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, project_id)
            for pack_type in request.pack_types:
                stale_count += self._mark_pack_type_stale(
                    conn,
                    project_uuid,
                    pack_type,
                    jsonb([request.dependency_ref]),
                    request.stale_reason,
                )
        return LibraryPackStaleResponse(
            scope=self._scope(project_id),
            dependency_ref=request.dependency_ref,
            stale_reason=request.stale_reason,
            stale_pack_count=stale_count,
            rebuilt_pack_count=0,
            pack_types=request.pack_types,
        )

    def record_retrieval_usage(self, request: LibraryRetrievalUsageLogRequest) -> LibraryRetrievalUsageRecord:
        project_id = self._resolve_project_id(request.project_id)
        self._ensure_postgres_primary_mode()
        jsonb = self._active_connection_factory().jsonb_adapter()
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, project_id)
            retrieval_task_uuid = self._resolve_optional_business_uuid(
                conn,
                project_uuid,
                "retrieval_task_specs",
                "retrieval_task_id",
                request.retrieval_task_id,
            )
            chapter_pack_uuid, scene_pack_uuid, agent_context_pack_uuid = self._resolve_optional_usage_pack_uuid(
                conn,
                project_uuid,
                request.pack_type,
                request.pack_id,
            )
            row = conn.execute(
                f"""
                INSERT INTO {self.schema_name}.retrieval_usage_records (
                  project_id, retrieval_usage_id, schema_version, retrieval_task_id,
                  chapter_pack_id, scene_pack_id, agent_context_pack_id, query_text,
                  candidate_count, selected_count, used_entity_refs, ignored_entity_refs,
                  missing_requirements, latency_ms, token_estimate, status,
                  legacy_status_raw, lifecycle_state, authority_level, source_type,
                  source_id, source_refs, metadata, updated_at, deleted_at
                )
                VALUES (
                  %s, %s, 'phase9_m11_task7', %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, 'CONFIRMED', 'ACTIVE', 'ACTIVE',
                  'SYSTEM_CONFIRMED', 'LIBRARY_RETRIEVAL_API', %s, %s, %s,
                  now(), NULL
                )
                ON CONFLICT (project_id, retrieval_usage_id) DO UPDATE
                SET retrieval_task_id = EXCLUDED.retrieval_task_id,
                    chapter_pack_id = EXCLUDED.chapter_pack_id,
                    scene_pack_id = EXCLUDED.scene_pack_id,
                    agent_context_pack_id = EXCLUDED.agent_context_pack_id,
                    query_text = EXCLUDED.query_text,
                    candidate_count = EXCLUDED.candidate_count,
                    selected_count = EXCLUDED.selected_count,
                    used_entity_refs = EXCLUDED.used_entity_refs,
                    ignored_entity_refs = EXCLUDED.ignored_entity_refs,
                    missing_requirements = EXCLUDED.missing_requirements,
                    latency_ms = EXCLUDED.latency_ms,
                    token_estimate = EXCLUDED.token_estimate,
                    status = 'CONFIRMED',
                    lifecycle_state = 'ACTIVE',
                    source_refs = EXCLUDED.source_refs,
                    metadata = EXCLUDED.metadata,
                    updated_at = now(),
                    deleted_at = NULL
                RETURNING retrieval_usage_id, candidate_count, selected_count,
                          ignored_entity_refs, missing_requirements, latency_ms, token_estimate
                """,
                (
                    project_uuid,
                    request.retrieval_usage_id,
                    retrieval_task_uuid,
                    chapter_pack_uuid,
                    scene_pack_uuid,
                    agent_context_pack_uuid,
                    request.query_text,
                    request.candidate_count,
                    request.selected_count,
                    jsonb(request.used_entity_refs),
                    jsonb(request.ignored_entity_refs),
                    jsonb(request.missing_requirements),
                    request.latency_ms,
                    request.token_estimate,
                    request.retrieval_usage_id,
                    jsonb(request.source_refs),
                    jsonb(request.metadata),
                ),
            ).fetchone()
        return LibraryRetrievalUsageRecord(
            scope=self._scope(project_id),
            retrieval_usage_id=str(row[0] or ""),
            candidate_count=int(row[1] or 0),
            selected_count=int(row[2] or 0),
            ignored_entity_refs=row[3] if isinstance(row[3], list) else [],
            missing_requirements=row[4] if isinstance(row[4], list) else [],
            latency_ms=int(row[5] or 0),
            token_estimate=int(row[6] or 0),
        )

    def record_retrieval_gap(self, request: LibraryRetrievalGapRequest) -> LibraryRetrievalGapRecord:
        project_id = self._resolve_project_id(request.project_id)
        self._ensure_postgres_primary_mode()
        jsonb = self._active_connection_factory().jsonb_adapter()
        gap_type = PROSE_FALLBACK_GAP_TYPE if request.prose_fallback_accepted else request.gap_type
        warning = PROSE_FALLBACK_WARNING if request.prose_fallback_accepted else ""
        metadata = dict(request.metadata)
        if request.prose_fallback_accepted:
            metadata["proseFallbackAccepted"] = True
            metadata["warning"] = warning
            metadata["candidateBoundary"] = "prose fallback is logged as a gap, not a primary retrieval surface"
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, project_id)
            retrieval_task_uuid = self._resolve_optional_business_uuid(
                conn,
                project_uuid,
                "retrieval_task_specs",
                "retrieval_task_id",
                request.retrieval_task_id,
            )
            scene_uuid = self._resolve_optional_business_uuid(
                conn,
                project_uuid,
                "scenes",
                "scene_id",
                request.scene_id,
            )
            row = conn.execute(
                f"""
                INSERT INTO {self.schema_name}.retrieval_gap_records (
                  project_id, retrieval_gap_id, schema_version, retrieval_task_id,
                  scene_id, gap_type, claim_text, searched_scopes,
                  recommended_resolution, status, legacy_status_raw, lifecycle_state,
                  authority_level, source_type, source_id, source_refs, metadata,
                  updated_at, deleted_at
                )
                VALUES (
                  %s, %s, 'phase9_m11_task7', %s, %s, %s, %s, %s, %s,
                  'CANDIDATE', 'OPEN', 'ACTIVE', 'SYSTEM_CONFIRMED',
                  'LIBRARY_RETRIEVAL_API', %s, %s, %s, now(), NULL
                )
                ON CONFLICT (project_id, retrieval_gap_id) DO UPDATE
                SET retrieval_task_id = EXCLUDED.retrieval_task_id,
                    scene_id = EXCLUDED.scene_id,
                    gap_type = EXCLUDED.gap_type,
                    claim_text = EXCLUDED.claim_text,
                    searched_scopes = EXCLUDED.searched_scopes,
                    recommended_resolution = EXCLUDED.recommended_resolution,
                    status = 'CANDIDATE',
                    lifecycle_state = 'ACTIVE',
                    source_refs = EXCLUDED.source_refs,
                    metadata = EXCLUDED.metadata,
                    updated_at = now(),
                    deleted_at = NULL
                RETURNING retrieval_gap_id, gap_type, claim_text,
                          searched_scopes, recommended_resolution, metadata
                """,
                (
                    project_uuid,
                    request.retrieval_gap_id,
                    retrieval_task_uuid,
                    scene_uuid,
                    gap_type,
                    request.claim_text,
                    jsonb(request.searched_scopes),
                    request.recommended_resolution,
                    request.retrieval_gap_id,
                    jsonb(request.source_refs),
                    jsonb(metadata),
                ),
            ).fetchone()
        returned_metadata = row[5] if isinstance(row[5], dict) else {}
        return LibraryRetrievalGapRecord(
            scope=self._scope(project_id),
            retrieval_gap_id=str(row[0] or ""),
            gap_type=str(row[1] or ""),
            claim_text=str(row[2] or ""),
            searched_scopes=row[3] if isinstance(row[3], list) else [],
            recommended_resolution=str(row[4] or ""),
            warning=str(returned_metadata.get("warning") or warning),
        )

    def get_semantic_retrieval_boundary(self) -> LibrarySemanticRetrievalBoundary:
        return LibrarySemanticRetrievalBoundary(
            semantic_retrieval_mode=SEMANTIC_RETRIEVAL_MODE,
            allowed_modes=list(SEMANTIC_RETRIEVAL_ALLOWED_MODES),
            embedding_ref_storage=SEMANTIC_RETRIEVAL_EMBEDDING_REF_STORAGE,
            production_pgvector_required_for_m11_pass=False,
            semantic_score_can_override_hard_gates=False,
            semantic_hook_ready=False,
            warning=SEMANTIC_RETRIEVAL_WARNING,
        )

    def get_retrieval_task_spec(self, *, project_id: str = "", retrieval_task_id: str) -> LibraryRetrievalTaskSpec:
        active_project_id = self._resolve_project_id(project_id)
        self._ensure_postgres_primary_mode()
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, active_project_id)
            return self._load_task_spec(conn, project_uuid, retrieval_task_id)

    def create_retrieval_task_spec(
        self,
        *,
        project_id: str = "",
        payload: LibraryRetrievalTaskSpecPayload,
    ) -> LibraryRetrievalTaskSpec:
        active_project_id = self._resolve_project_id(project_id)
        self._ensure_postgres_primary_mode()
        jsonb = self._active_connection_factory().jsonb_adapter()
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, active_project_id)
            row = conn.execute(
                self._upsert_task_spec_sql(),
                (
                    project_uuid,
                    payload.retrieval_task_id,
                    payload.agent_role,
                    payload.task_type,
                    payload.query_text,
                    jsonb(payload.filters.dict()),
                    jsonb(payload.required_entity_refs),
                    payload.max_items,
                    payload.token_budget,
                    payload.status,
                    payload.status,
                    payload.authority_level,
                    "LIBRARY_RETRIEVAL_API",
                    payload.retrieval_task_id,
                    jsonb(payload.source_refs),
                    jsonb(payload.metadata),
                ),
            ).fetchone()
        return self._task_spec_from_row(row)

    def _upsert_pack_root(self, conn: Any, project_uuid: Any, request: LibraryPackBuildRequest, jsonb: Any) -> Any:
        if request.pack_type == "CHAPTER_MEMORY_PACK":
            chapter_uuid = self._resolve_business_uuid(conn, project_uuid, "chapters", "chapter_id", request.chapter_id)
            row = conn.execute(
                f"""
                INSERT INTO {self.schema_name}.chapter_memory_packs (
                  project_id, chapter_memory_pack_id, schema_version, chapter_id, pack_purpose,
                  max_items, token_budget, dependency_refs, dependency_hash, freshness_status,
                  last_built_at, invalidated_at, invalidated_reason, status, legacy_status_raw,
                  lifecycle_state, authority_level, source_type, source_id, source_refs,
                  content_hash, metadata, updated_at, deleted_at
                )
                VALUES (
                  %s, %s, 'phase9_m11_task6', %s, %s, %s, %s, %s, %s, 'FRESH',
                  now(), NULL, '', 'CONFIRMED', 'ACTIVE', 'ACTIVE', 'SYSTEM_CONFIRMED',
                  'LIBRARY_RETRIEVAL_API', %s, '[]'::jsonb, %s, '{{}}'::jsonb, now(), NULL
                )
                ON CONFLICT (project_id, chapter_memory_pack_id) DO UPDATE
                SET pack_purpose = EXCLUDED.pack_purpose,
                    max_items = EXCLUDED.max_items,
                    token_budget = EXCLUDED.token_budget,
                    dependency_refs = EXCLUDED.dependency_refs,
                    dependency_hash = EXCLUDED.dependency_hash,
                    freshness_status = 'FRESH',
                    last_built_at = now(),
                    invalidated_at = NULL,
                    invalidated_reason = '',
                    status = 'CONFIRMED',
                    lifecycle_state = 'ACTIVE',
                    content_hash = EXCLUDED.content_hash,
                    updated_at = now(),
                    deleted_at = NULL
                RETURNING id
                """,
                (
                    project_uuid,
                    request.pack_id,
                    chapter_uuid,
                    request.pack_purpose,
                    request.max_items,
                    request.token_budget,
                    jsonb(request.dependency_refs),
                    request.dependency_hash,
                    request.pack_id,
                    request.content_hash,
                ),
            ).fetchone()
            return row[0]

        if request.pack_type == "SCENE_MEMORY_PACK":
            scene_uuid = self._resolve_business_uuid(conn, project_uuid, "scenes", "scene_id", request.scene_id)
            row = conn.execute(
                f"""
                INSERT INTO {self.schema_name}.scene_memory_packs (
                  project_id, scene_memory_pack_id, schema_version, scene_id, pack_purpose,
                  max_items, token_budget, dependency_refs, dependency_hash, freshness_status,
                  last_built_at, invalidated_at, invalidated_reason, status, legacy_status_raw,
                  lifecycle_state, authority_level, source_type, source_id, source_refs,
                  content_hash, metadata, updated_at, deleted_at
                )
                VALUES (
                  %s, %s, 'phase9_m11_task6', %s, %s, %s, %s, %s, %s, 'FRESH',
                  now(), NULL, '', 'CONFIRMED', 'ACTIVE', 'ACTIVE', 'SYSTEM_CONFIRMED',
                  'LIBRARY_RETRIEVAL_API', %s, '[]'::jsonb, %s, '{{}}'::jsonb, now(), NULL
                )
                ON CONFLICT (project_id, scene_memory_pack_id) DO UPDATE
                SET pack_purpose = EXCLUDED.pack_purpose,
                    max_items = EXCLUDED.max_items,
                    token_budget = EXCLUDED.token_budget,
                    dependency_refs = EXCLUDED.dependency_refs,
                    dependency_hash = EXCLUDED.dependency_hash,
                    freshness_status = 'FRESH',
                    last_built_at = now(),
                    invalidated_at = NULL,
                    invalidated_reason = '',
                    status = 'CONFIRMED',
                    lifecycle_state = 'ACTIVE',
                    content_hash = EXCLUDED.content_hash,
                    updated_at = now(),
                    deleted_at = NULL
                RETURNING id
                """,
                (
                    project_uuid,
                    request.pack_id,
                    scene_uuid,
                    request.pack_purpose,
                    request.max_items,
                    request.token_budget,
                    jsonb(request.dependency_refs),
                    request.dependency_hash,
                    request.pack_id,
                    request.content_hash,
                ),
            ).fetchone()
            return row[0]

        retrieval_task_uuid = self._resolve_optional_business_uuid(
            conn,
            project_uuid,
            "retrieval_task_specs",
            "retrieval_task_id",
            request.retrieval_task_id,
        )
        row = conn.execute(
            f"""
            INSERT INTO {self.schema_name}.agent_context_packs (
              project_id, agent_context_pack_id, schema_version, retrieval_task_id, agent_role,
              pack_purpose, max_items, token_budget, dependency_refs, dependency_hash,
              freshness_status, last_built_at, invalidated_at, invalidated_reason, status,
              legacy_status_raw, lifecycle_state, authority_level, source_type, source_id,
              source_refs, content_hash, metadata, updated_at, deleted_at
            )
            VALUES (
              %s, %s, 'phase9_m11_task6', %s, %s, %s, %s, %s, %s, %s,
              'FRESH', now(), NULL, '', 'CONFIRMED', 'ACTIVE', 'ACTIVE',
              'SYSTEM_CONFIRMED', 'LIBRARY_RETRIEVAL_API', %s, '[]'::jsonb, %s,
              '{{}}'::jsonb, now(), NULL
            )
            ON CONFLICT (project_id, agent_context_pack_id) DO UPDATE
            SET retrieval_task_id = EXCLUDED.retrieval_task_id,
                agent_role = EXCLUDED.agent_role,
                pack_purpose = EXCLUDED.pack_purpose,
                max_items = EXCLUDED.max_items,
                token_budget = EXCLUDED.token_budget,
                dependency_refs = EXCLUDED.dependency_refs,
                dependency_hash = EXCLUDED.dependency_hash,
                freshness_status = 'FRESH',
                last_built_at = now(),
                invalidated_at = NULL,
                invalidated_reason = '',
                status = 'CONFIRMED',
                lifecycle_state = 'ACTIVE',
                content_hash = EXCLUDED.content_hash,
                updated_at = now(),
                deleted_at = NULL
            RETURNING id
            """,
            (
                project_uuid,
                request.pack_id,
                retrieval_task_uuid,
                request.agent_role,
                request.pack_purpose,
                request.max_items,
                request.token_budget,
                jsonb(request.dependency_refs),
                request.dependency_hash,
                request.pack_id,
                request.content_hash,
            ),
        ).fetchone()
        return row[0]

    def _soft_delete_existing_pack_items(self, conn: Any, project_uuid: Any, pack_type: str, root_id: Any) -> None:
        root_column = self._pack_item_root_column(pack_type)
        conn.execute(
            f"""
            UPDATE {self.schema_name}.pack_items
            SET lifecycle_state = 'DELETED',
                deleted_at = now(),
                included_in_writer_context = false,
                updated_at = now()
            WHERE project_id = %s
              AND {root_column} = %s
              AND deleted_at IS NULL
            """,
            (project_uuid, root_id),
        )

    def _upsert_pack_item(
        self,
        conn: Any,
        project_uuid: Any,
        request: LibraryPackBuildRequest,
        root_id: Any,
        item: Any,
        item_order: int,
        jsonb: Any,
    ) -> None:
        root_column = self._pack_item_root_column(request.pack_type)
        root_values = {
            "chapter_pack_id": None,
            "scene_pack_id": None,
            "agent_context_pack_id": None,
        }
        root_values[root_column] = root_id
        search_document_uuid = self._resolve_optional_business_uuid(
            conn,
            project_uuid,
            "search_documents",
            "search_document_id",
            item.search_document_id,
        )
        memory_uuid = self._resolve_optional_business_uuid(
            conn,
            project_uuid,
            "memory_records",
            "memory_id",
            item.memory_id,
        )
        pack_item_id = item.pack_item_id or f"{request.pack_id}:item:{item_order}"
        conn.execute(
            f"""
            INSERT INTO {self.schema_name}.pack_items (
              project_id, pack_item_id, schema_version, pack_type, chapter_pack_id,
              scene_pack_id, agent_context_pack_id, search_document_id, memory_id,
              item_order, entity_type, entity_business_id, reason, rank_score,
              token_estimate, required_for_generation, access_label, source_status,
              included_in_writer_context, status, legacy_status_raw, lifecycle_state,
              authority_level, source_type, source_id, source_refs, metadata,
              updated_at, deleted_at
            )
            VALUES (
              %s, %s, 'phase9_m11_task6', %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, 'CONFIRMED', 'ACTIVE',
              'ACTIVE', 'SYSTEM_CONFIRMED', 'LIBRARY_RETRIEVAL_API', %s,
              %s, %s, now(), NULL
            )
            ON CONFLICT (project_id, pack_item_id) DO UPDATE
            SET chapter_pack_id = EXCLUDED.chapter_pack_id,
                scene_pack_id = EXCLUDED.scene_pack_id,
                agent_context_pack_id = EXCLUDED.agent_context_pack_id,
                search_document_id = EXCLUDED.search_document_id,
                memory_id = EXCLUDED.memory_id,
                item_order = EXCLUDED.item_order,
                entity_type = EXCLUDED.entity_type,
                entity_business_id = EXCLUDED.entity_business_id,
                reason = EXCLUDED.reason,
                rank_score = EXCLUDED.rank_score,
                token_estimate = EXCLUDED.token_estimate,
                required_for_generation = EXCLUDED.required_for_generation,
                access_label = EXCLUDED.access_label,
                source_status = EXCLUDED.source_status,
                included_in_writer_context = EXCLUDED.included_in_writer_context,
                status = 'CONFIRMED',
                lifecycle_state = 'ACTIVE',
                source_refs = EXCLUDED.source_refs,
                metadata = EXCLUDED.metadata,
                updated_at = now(),
                deleted_at = NULL
            """,
            (
                project_uuid,
                pack_item_id,
                request.pack_type,
                root_values["chapter_pack_id"],
                root_values["scene_pack_id"],
                root_values["agent_context_pack_id"],
                search_document_uuid,
                memory_uuid,
                item_order,
                item.entity_type,
                item.entity_business_id,
                item.reason,
                item.rank_score,
                item.token_estimate,
                item.required_for_generation,
                item.access_label,
                item.source_status,
                item.access_label == "USABLE_NOW",
                pack_item_id,
                jsonb(item.source_refs),
                jsonb(item.metadata),
            ),
        )

    def _load_pack(self, conn: Any, project_id: str, project_uuid: Any, pack_type: str, pack_id: str) -> LibraryPack:
        root_sql = self._select_pack_root_sql(pack_type)
        row = conn.execute(root_sql, (project_uuid, pack_id)).fetchone()
        if row is None:
            raise StorageError("LIBRARY_RETRIEVAL_PACK_NOT_FOUND: pack was not found.")
        item_rows = self._fetchall(
            conn.execute(
                f"""
                SELECT
                  pack_item_id, entity_type, entity_business_id, reason, rank_score,
                  token_estimate, required_for_generation, access_label, source_status,
                  source_refs, metadata
                FROM {self.schema_name}.pack_items
                WHERE project_id = %s
                  AND {self._pack_item_root_column(pack_type)} = %s
                  AND deleted_at IS NULL
                  AND lifecycle_state <> 'DELETED'
                ORDER BY item_order, pack_item_id
                """,
                (project_uuid, row[0]),
            )
        )
        return LibraryPack(
            scope=self._scope(project_id),
            pack_type=pack_type,
            pack_id=str(row[1] or ""),
            chapter_id=str(row[2] or ""),
            scene_id=str(row[3] or ""),
            agent_role=str(row[4] or ""),
            pack_purpose=str(row[5] or ""),
            max_items=int(row[6] or 0),
            token_budget=int(row[7] or 0),
            dependency_refs=row[8] if isinstance(row[8], list) else [],
            dependency_hash=str(row[9] or ""),
            freshness_status=str(row[10] or ""),
            invalidated_reason=str(row[11] or ""),
            version=int(row[12] or 1),
            revision=int(row[13] or 1),
            content_hash=str(row[14] or ""),
            items=[self._pack_item_from_row(item_row) for item_row in item_rows],
        )

    def _select_pack_root_sql(self, pack_type: str) -> str:
        if pack_type == "CHAPTER_MEMORY_PACK":
            return f"""
            SELECT pack.id, pack.chapter_memory_pack_id, chapter.chapter_id, '', '', pack.pack_purpose,
                   pack.max_items, pack.token_budget, pack.dependency_refs, pack.dependency_hash,
                   pack.freshness_status, pack.invalidated_reason, pack.version, pack.revision,
                   pack.content_hash
            FROM {self.schema_name}.chapter_memory_packs pack
            JOIN {self.schema_name}.chapters chapter
              ON chapter.id = pack.chapter_id AND chapter.project_id = pack.project_id
            WHERE pack.project_id = %s
              AND pack.chapter_memory_pack_id = %s
              AND pack.deleted_at IS NULL
            """
        if pack_type == "SCENE_MEMORY_PACK":
            return f"""
            SELECT pack.id, pack.scene_memory_pack_id, '', scene.scene_id, '', pack.pack_purpose,
                   pack.max_items, pack.token_budget, pack.dependency_refs, pack.dependency_hash,
                   pack.freshness_status, pack.invalidated_reason, pack.version, pack.revision,
                   pack.content_hash
            FROM {self.schema_name}.scene_memory_packs pack
            JOIN {self.schema_name}.scenes scene
              ON scene.id = pack.scene_id AND scene.project_id = pack.project_id
            WHERE pack.project_id = %s
              AND pack.scene_memory_pack_id = %s
              AND pack.deleted_at IS NULL
            """
        if pack_type == "AGENT_CONTEXT_PACK":
            return f"""
            SELECT pack.id, pack.agent_context_pack_id, '', '', pack.agent_role, pack.pack_purpose,
                   pack.max_items, pack.token_budget, pack.dependency_refs, pack.dependency_hash,
                   pack.freshness_status, pack.invalidated_reason, pack.version, pack.revision,
                   pack.content_hash
            FROM {self.schema_name}.agent_context_packs pack
            WHERE pack.project_id = %s
              AND pack.agent_context_pack_id = %s
              AND pack.deleted_at IS NULL
            """
        raise StorageError("LIBRARY_RETRIEVAL_PACK_TYPE_INVALID: unsupported pack_type.")

    def _mark_pack_type_stale(self, conn: Any, project_uuid: Any, pack_type: str, dependency_jsonb: Any, stale_reason: str) -> int:
        table = self._pack_root_table(pack_type)
        cursor = conn.execute(
            f"""
            UPDATE {self.schema_name}.{table}
            SET freshness_status = 'STALE',
                invalidated_at = now(),
                invalidated_reason = %s,
                updated_at = now()
            WHERE project_id = %s
              AND dependency_refs @> %s
              AND freshness_status = 'FRESH'
              AND deleted_at IS NULL
            """,
            (stale_reason, project_uuid, dependency_jsonb),
        )
        return int(getattr(cursor, "rowcount", 0) or 0)

    def _resolve_business_uuid(
        self,
        conn: Any,
        project_uuid: Any,
        table_name: str,
        business_id_column: str,
        business_id: str,
    ) -> Any:
        row = conn.execute(
            f"""
            SELECT id
            FROM {self.schema_name}.{table_name}
            WHERE project_id = %s
              AND {business_id_column} = %s
              AND deleted_at IS NULL
            """,
            (project_uuid, str(business_id or "").strip()),
        ).fetchone()
        if row is None:
            raise StorageError("LIBRARY_RETRIEVAL_PACK_REF_NOT_FOUND: referenced business id was not found.")
        return row[0]

    def _resolve_optional_business_uuid(
        self,
        conn: Any,
        project_uuid: Any,
        table_name: str,
        business_id_column: str,
        business_id: str,
    ) -> Any:
        cleaned = str(business_id or "").strip()
        if not cleaned:
            return None
        return self._resolve_business_uuid(conn, project_uuid, table_name, business_id_column, cleaned)

    def _pack_item_root_column(self, pack_type: str) -> str:
        if pack_type == "CHAPTER_MEMORY_PACK":
            return "chapter_pack_id"
        if pack_type == "SCENE_MEMORY_PACK":
            return "scene_pack_id"
        if pack_type == "AGENT_CONTEXT_PACK":
            return "agent_context_pack_id"
        raise StorageError("LIBRARY_RETRIEVAL_PACK_TYPE_INVALID: unsupported pack_type.")

    def _pack_root_table(self, pack_type: str) -> str:
        if pack_type == "CHAPTER_MEMORY_PACK":
            return "chapter_memory_packs"
        if pack_type == "SCENE_MEMORY_PACK":
            return "scene_memory_packs"
        if pack_type == "AGENT_CONTEXT_PACK":
            return "agent_context_packs"
        raise StorageError("LIBRARY_RETRIEVAL_PACK_TYPE_INVALID: unsupported pack_type.")

    def _pack_item_from_row(self, row: Any) -> LibraryPackItem:
        source_refs = row[9] or []
        metadata = row[10] or {}
        return LibraryPackItem(
            pack_item_id=str(row[0] or ""),
            entity_type=str(row[1] or ""),
            entity_business_id=str(row[2] or ""),
            reason=str(row[3] or ""),
            rank_score=float(row[4] or 0),
            token_estimate=int(row[5] or 0),
            required_for_generation=bool(row[6]),
            access_label=str(row[7] or ""),
            source_status=str(row[8] or ""),
            source_refs=source_refs if isinstance(source_refs, list) else [],
            metadata=dict(metadata),
        )

    def _resolve_optional_usage_pack_uuid(
        self,
        conn: Any,
        project_uuid: Any,
        pack_type: str,
        pack_id: str,
    ) -> tuple[Any, Any, Any]:
        cleaned_type = str(pack_type or "").strip().upper()
        cleaned_id = str(pack_id or "").strip()
        if not cleaned_type or not cleaned_id:
            return None, None, None
        if cleaned_type == "CHAPTER_MEMORY_PACK":
            return (
                self._resolve_business_uuid(conn, project_uuid, "chapter_memory_packs", "chapter_memory_pack_id", cleaned_id),
                None,
                None,
            )
        if cleaned_type == "SCENE_MEMORY_PACK":
            return (
                None,
                self._resolve_business_uuid(conn, project_uuid, "scene_memory_packs", "scene_memory_pack_id", cleaned_id),
                None,
            )
        if cleaned_type == "AGENT_CONTEXT_PACK":
            return (
                None,
                None,
                self._resolve_business_uuid(conn, project_uuid, "agent_context_packs", "agent_context_pack_id", cleaned_id),
            )
        raise StorageError("LIBRARY_RETRIEVAL_PACK_TYPE_INVALID: unsupported pack_type.")

    def _resolve_project_id(self, project_id: str) -> str:
        cleaned = str(project_id or "").strip()
        if cleaned:
            return validate_runtime_project_id(cleaned)
        return resolve_runtime_project_mapping().project_id

    def _ensure_postgres_primary_mode(self) -> None:
        if self._connection_factory is not None:
            return
        if settings.storage_mode != STORAGE_MODE_POSTGRES_PRIMARY:
            raise StorageError(
                "LIBRARY_RETRIEVAL_POSTGRES_PRIMARY_REQUIRED: "
                "structured retrieval is available only in explicit postgres_primary mode."
            )

    def _connect(self) -> Any:
        return self._active_connection_factory().connect()

    def _active_connection_factory(self) -> PostgresConnectionFactory:
        if self._connection_factory is not None:
            return self._connection_factory
        return PostgresConnectionFactory(database_url=settings.database_url)

    def _scope(self, project_id: str) -> LibraryRetrievalScope:
        mapping = resolve_runtime_project_mapping()
        return LibraryRetrievalScope(
            project_id=project_id,
            storage_mode=settings.storage_mode,
            mapping_source=mapping.source,
            compatibility_selection_used=mapping.compatibility_selection_used,
            warnings=mapping.warnings,
        )

    def _resolve_project_uuid(self, conn: Any, project_id: str) -> Any:
        row = conn.execute(
            f"""
            SELECT id
            FROM {self.schema_name}.projects
            WHERE project_id = %s
              AND deleted_at IS NULL
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            raise StorageError("LIBRARY_RETRIEVAL_PROJECT_NOT_FOUND: project_id was not found.")
        return row[0]

    def _load_task_spec(self, conn: Any, project_uuid: Any, retrieval_task_id: str) -> LibraryRetrievalTaskSpec:
        cleaned = str(retrieval_task_id or "").strip()
        if not cleaned:
            raise StorageError("LIBRARY_RETRIEVAL_TASK_SPEC_ID_REQUIRED: retrieval_task_id is required.")
        row = conn.execute(
            self._select_task_spec_sql(),
            (project_uuid, cleaned),
        ).fetchone()
        if row is None:
            raise StorageError("LIBRARY_RETRIEVAL_TASK_SPEC_NOT_FOUND: retrieval task spec was not found.")
        return self._task_spec_from_row(row)

    def _select_task_spec_sql(self) -> str:
        return f"""
        SELECT
          retrieval_task_id,
          agent_role,
          task_type,
          query_text,
          filters_json,
          required_entity_refs,
          max_items,
          token_budget,
          status,
          lifecycle_state,
          authority_level,
          source_refs,
          metadata
        FROM {self.schema_name}.retrieval_task_specs
        WHERE project_id = %s
          AND retrieval_task_id = %s
          AND deleted_at IS NULL
          AND status NOT IN ('SUPERSEDED', 'ARCHIVED', 'DELETED', 'REJECTED')
          AND lifecycle_state <> 'DELETED'
        """

    def _upsert_task_spec_sql(self) -> str:
        return f"""
        INSERT INTO {self.schema_name}.retrieval_task_specs (
          project_id,
          retrieval_task_id,
          schema_version,
          agent_role,
          task_type,
          query_text,
          filters_json,
          required_entity_refs,
          max_items,
          token_budget,
          status,
          legacy_status_raw,
          lifecycle_state,
          authority_level,
          source_type,
          source_id,
          source_refs,
          metadata,
          updated_at,
          deleted_at
        )
        VALUES (
          %s, %s, 'phase9_m11_task3', %s, %s, %s, %s, %s, %s, %s, %s, %s,
          'ACTIVE', %s, %s, %s, %s, %s, now(), NULL
        )
        ON CONFLICT (project_id, retrieval_task_id) DO UPDATE
        SET schema_version = EXCLUDED.schema_version,
            agent_role = EXCLUDED.agent_role,
            task_type = EXCLUDED.task_type,
            query_text = EXCLUDED.query_text,
            filters_json = EXCLUDED.filters_json,
            required_entity_refs = EXCLUDED.required_entity_refs,
            max_items = EXCLUDED.max_items,
            token_budget = EXCLUDED.token_budget,
            status = EXCLUDED.status,
            legacy_status_raw = EXCLUDED.legacy_status_raw,
            lifecycle_state = EXCLUDED.lifecycle_state,
            authority_level = EXCLUDED.authority_level,
            source_type = EXCLUDED.source_type,
            source_id = EXCLUDED.source_id,
            source_refs = EXCLUDED.source_refs,
            metadata = EXCLUDED.metadata,
            updated_at = now(),
            deleted_at = NULL
        RETURNING
          retrieval_task_id,
          agent_role,
          task_type,
          query_text,
          filters_json,
          required_entity_refs,
          max_items,
          token_budget,
          status,
          lifecycle_state,
          authority_level,
          source_refs,
          metadata
        """

    def _expanded_candidates_sql_and_params(
        self,
        *,
        project_uuid: Any,
        query_text: str,
        modes: list[str],
        allow_full_text: bool,
        filters: LibraryRetrievalFilters,
        max_items: int,
        link_types: list[str],
        max_graph_distance: int,
    ) -> tuple[str, tuple[Any, ...], list[str]]:
        seed_sql, seed_params, seed_filters = self._text_candidates_sql_and_params(
            project_uuid=project_uuid,
            query_text=query_text,
            modes=modes,
            allow_full_text=allow_full_text,
            filters=filters,
            max_items=max_items,
        )
        branches = [self._direct_seed_candidate_sql()]
        params: list[Any] = list(seed_params)
        filters_applied = list(seed_filters) + ["direct_entity_match", "seed_top_k_before_expansion"]
        if max_graph_distance > 0:
            doc_where_sql, doc_where_params, doc_applied = self._document_where_clause(project_uuid, filters)
            effective_link_types = self._relationship_link_types(link_types)
            branches.append(self._linked_candidate_sql(doc_where_sql))
            params.extend(
                [
                    project_uuid,
                    self._writer_safe_authority_levels(filters.authority_levels)
                    or list(WRITER_SAFE_AUTHORITY_LEVELS),
                    effective_link_types,
                    project_uuid,
                ]
            )
            params.extend(doc_where_params)
            filters_applied.extend(
                doc_applied
                + [
                    "linked_entity",
                    "same_location",
                    "foreshadowing",
                    "continuity_related",
                    "relationship_link_type_allowlist",
                    "graph_distance:1",
                ]
            )
        else:
            filters_applied.append("graph_distance:0")

        params.append(max_items)
        sql = f"""
        WITH seed_candidates AS (
          {seed_sql}
        ),
        expanded_candidates AS (
          {' UNION ALL '.join(branches)}
        ),
        ranked_candidates AS (
          SELECT
            expanded_candidates.*,
            row_number() OVER (
              PARTITION BY dedupe_key
              ORDER BY final_score DESC, graph_distance ASC, candidate_id
            ) AS dedupe_rank
          FROM expanded_candidates
        )
        SELECT
          candidate_id,
          candidate_kind,
          search_memory_card_id,
          search_document_id,
          entity_type,
          entity_business_id,
          source_type,
          title,
          text_summary,
          source_refs,
          access_label,
          visibility_status,
          authority_level,
          status,
          lifecycle_state,
          final_score,
          score_components,
          token_estimate,
          explanation
        FROM ranked_candidates
        WHERE dedupe_rank = 1
        ORDER BY final_score DESC, graph_distance ASC, candidate_id
        LIMIT %s
        """
        return sql, tuple(params), sorted(set(filters_applied))

    def _direct_seed_candidate_sql(self) -> str:
        return """
        SELECT
          CASE WHEN seed.entity_business_id <> ''
            THEN seed.entity_type || ':' || seed.entity_business_id
            ELSE seed.candidate_id
          END AS dedupe_key,
          seed.candidate_id,
          seed.candidate_kind,
          seed.search_memory_card_id,
          seed.search_document_id,
          seed.entity_type,
          seed.entity_business_id,
          seed.source_type,
          seed.title,
          seed.text_summary,
          seed.source_refs,
          seed.access_label,
          seed.visibility_status,
          seed.authority_level,
          seed.status,
          seed.lifecycle_state,
          seed.final_score,
          seed.score_components || jsonb_build_object(
            'graph_distance', 0.0,
            'direct_entity_match', CASE WHEN seed.candidate_kind = 'EXACT_ENTITY_OR_DOCUMENT' THEN 1.0 ELSE 0.0 END,
            'alias_match', CASE WHEN seed.candidate_kind = 'ENTITY_ALIAS' THEN 1.0 ELSE 0.0 END,
            'tag_match', CASE WHEN seed.candidate_kind = 'ENTITY_TAG' THEN 1.0 ELSE 0.0 END
          ) AS score_components,
          seed.token_estimate,
          CASE seed.candidate_kind
            WHEN 'EXACT_ENTITY_OR_DOCUMENT' THEN 'direct_entity_match: '
            WHEN 'ENTITY_ALIAS' THEN 'alias_match: '
            WHEN 'ENTITY_TAG' THEN 'tag_match: '
            ELSE 'direct_entity_match: '
          END || seed.explanation AS explanation,
          0 AS graph_distance
        FROM seed_candidates seed
        """

    def _linked_candidate_sql(self, doc_where_sql: str) -> str:
        return f"""
        SELECT
          CASE WHEN doc.entity_business_id <> ''
            THEN doc.entity_type || ':' || doc.entity_business_id
            ELSE 'document:' || doc.search_document_id
          END AS dedupe_key,
          'linked:' || link.entity_link_id || ':' || doc.search_document_id AS candidate_id,
          'ENTITY_LINK_EXPANSION' AS candidate_kind,
          '' AS search_memory_card_id,
          doc.search_document_id,
          doc.entity_type,
          doc.entity_business_id,
          doc.entity_type AS source_type,
          doc.title,
          doc.summary AS text_summary,
          seed.source_refs || link.source_refs || doc.source_refs AS source_refs,
          'USABLE_NOW' AS access_label,
          'DOCUMENT_ONLY' AS visibility_status,
          doc.authority_level,
          doc.status,
          doc.lifecycle_state,
          (
            seed.final_score * 0.75
            + COALESCE(link.weight, 0)
            + COALESCE(doc.importance, 0)
            + CASE doc.authority_level
                WHEN 'USER_LOCKED' THEN 4.0
                WHEN 'USER_CONFIRMED' THEN 3.0
                WHEN 'FORMAL_APPLIED' THEN 2.5
                WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                ELSE 0.0
              END
            - 0.5
          )::float AS final_score,
          jsonb_build_object(
            'seed_score_weighted', seed.final_score * 0.75,
            'link_weight', COALESCE(link.weight, 0),
            'document_importance', COALESCE(doc.importance, 0),
            'graph_distance', 1.0,
            'linked_entity', 1.0,
            'same_location', CASE WHEN link.link_type = 'SAME_LOCATION' THEN 1.0 ELSE 0.0 END,
            'foreshadowing', CASE WHEN link.link_type = 'FORESHADOWING' THEN 1.0 ELSE 0.0 END,
            'continuity_related', CASE WHEN link.link_type = 'CONTINUITY_RELATED' THEN 1.0 ELSE 0.0 END,
            'authority_weight',
              CASE doc.authority_level
                WHEN 'USER_LOCKED' THEN 4.0
                WHEN 'USER_CONFIRMED' THEN 3.0
                WHEN 'FORMAL_APPLIED' THEN 2.5
                WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                ELSE 0.0
              END
          ) AS score_components,
          GREATEST(1, CEIL(length(COALESCE(doc.summary, doc.title))::numeric / 4))::integer AS token_estimate,
          CASE link.link_type
            WHEN 'SAME_LOCATION' THEN 'same_location'
            WHEN 'FORESHADOWING' THEN 'foreshadowing'
            WHEN 'CONTINUITY_RELATED' THEN 'continuity_related'
            ELSE 'linked_entity'
          END || ': ' || link.link_type || ' from ' || seed.entity_type || ':' || seed.entity_business_id AS explanation,
          1 AS graph_distance
        FROM seed_candidates seed
        JOIN {self.schema_name}.entity_links link
          ON link.project_id = %s
         AND (
           (
             link.source_entity_type = seed.entity_type
             AND link.source_business_id = seed.entity_business_id
           )
           OR (
             link.directionality = 'BIDIRECTIONAL'
             AND link.target_entity_type = seed.entity_type
             AND link.target_business_id = seed.entity_business_id
           )
         )
        JOIN {self.schema_name}.search_documents doc
          ON doc.project_id = link.project_id
         AND (
           (
             link.source_entity_type = seed.entity_type
             AND link.source_business_id = seed.entity_business_id
             AND doc.entity_type = link.target_entity_type
             AND doc.entity_business_id = link.target_business_id
           )
           OR (
             link.directionality = 'BIDIRECTIONAL'
             AND link.target_entity_type = seed.entity_type
             AND link.target_business_id = seed.entity_business_id
             AND doc.entity_type = link.source_entity_type
             AND doc.entity_business_id = link.source_business_id
           )
         )
        WHERE link.deleted_at IS NULL
          AND link.status NOT IN ('SUPERSEDED', 'ARCHIVED', 'DELETED', 'REJECTED')
          AND link.lifecycle_state <> 'DELETED'
          AND link.authority_level = ANY(%s)
          AND link.link_type = ANY(%s)
          AND link.project_id = %s
          AND {doc_where_sql}
        """

    def _text_candidates_sql_and_params(
        self,
        *,
        project_uuid: Any,
        query_text: str,
        modes: list[str],
        allow_full_text: bool,
        filters: LibraryRetrievalFilters,
        max_items: int,
    ) -> tuple[str, tuple[Any, ...], list[str]]:
        requested_modes = [mode for mode in modes if mode in TEXT_RETRIEVAL_MODES]
        if not requested_modes:
            raise StorageError("LIBRARY_RETRIEVAL_TEXT_MODE_REQUIRED: at least one text retrieval mode is required.")
        cleaned_query = str(query_text or "").strip()
        if not cleaned_query:
            raise StorageError("LIBRARY_RETRIEVAL_TEXT_QUERY_REQUIRED: query_text is required.")

        branches: list[str] = []
        params: list[Any] = []
        filters_applied: list[str] = []

        if "EXACT" in requested_modes:
            where_sql, where_params, applied = self._document_where_clause(project_uuid, filters)
            branches.append(
                f"""
                SELECT
                  CASE WHEN doc.entity_business_id <> ''
                    THEN doc.entity_type || ':' || doc.entity_business_id
                    ELSE 'document:' || doc.search_document_id
                  END AS dedupe_key,
                  'exact:' || doc.search_document_id AS candidate_id,
                  'EXACT_ENTITY_OR_DOCUMENT' AS candidate_kind,
                  '' AS search_memory_card_id,
                  doc.search_document_id,
                  doc.entity_type,
                  doc.entity_business_id,
                  doc.entity_type AS source_type,
                  doc.title,
                  doc.summary AS text_summary,
                  doc.source_refs,
                  'USABLE_NOW' AS access_label,
                  'DOCUMENT_ONLY' AS visibility_status,
                  doc.authority_level,
                  doc.status,
                  doc.lifecycle_state,
                  (
                    5.0
                    + COALESCE(doc.importance, 0)
                    + CASE doc.authority_level
                        WHEN 'USER_LOCKED' THEN 4.0
                        WHEN 'USER_CONFIRMED' THEN 3.0
                        WHEN 'FORMAL_APPLIED' THEN 2.5
                        WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                        ELSE 0.0
                      END
                  )::float AS final_score,
                  jsonb_build_object(
                    'mode_exact', 5.0,
                    'document_importance', COALESCE(doc.importance, 0),
                    'authority_weight',
                      CASE doc.authority_level
                        WHEN 'USER_LOCKED' THEN 4.0
                        WHEN 'USER_CONFIRMED' THEN 3.0
                        WHEN 'FORMAL_APPLIED' THEN 2.5
                        WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                        ELSE 0.0
                      END
                  ) AS score_components,
                  GREATEST(1, CEIL(length(COALESCE(doc.summary, doc.title))::numeric / 4))::integer AS token_estimate,
                  'exact id/name lookup via search document' AS explanation
                FROM {self.schema_name}.search_documents doc
                WHERE {where_sql}
                  AND (
                    lower(doc.search_document_id) = lower(%s)
                    OR lower(doc.entity_business_id) = lower(%s)
                    OR lower(doc.title) = lower(%s)
                  )
                """
            )
            params.extend(where_params + [cleaned_query, cleaned_query, cleaned_query])
            filters_applied.extend(applied + ["exact_id_name_lookup"])

        if "ALIAS" in requested_modes:
            branch_sql, branch_params, applied = self._lookup_table_text_branch(
                table_name="entity_aliases",
                table_alias="alias",
                business_id_column="entity_alias_id",
                text_column="alias_text",
                type_column="alias_type",
                match_mode="ALIAS",
                score_column="confidence",
                project_uuid=project_uuid,
                query_text=cleaned_query,
                filters=filters,
            )
            branches.append(branch_sql)
            params.extend(branch_params)
            filters_applied.extend(applied + ["alias_lookup"])

        if "KEYWORD" in requested_modes:
            branch_sql, branch_params, applied = self._lookup_table_text_branch(
                table_name="entity_keywords",
                table_alias="keyword",
                business_id_column="entity_keyword_id",
                text_column="keyword",
                type_column="keyword_type",
                match_mode="KEYWORD",
                score_column="weight",
                project_uuid=project_uuid,
                query_text=cleaned_query,
                filters=filters,
            )
            branches.append(branch_sql)
            params.extend(branch_params)
            filters_applied.extend(applied + ["keyword_lookup"])

        if "TAG" in requested_modes:
            branch_sql, branch_params, applied = self._lookup_table_text_branch(
                table_name="entity_tags",
                table_alias="tag",
                business_id_column="entity_tag_id",
                text_column="tag",
                type_column="tag_type",
                match_mode="TAG",
                score_column="confidence",
                project_uuid=project_uuid,
                query_text=cleaned_query,
                filters=filters,
            )
            branches.append(branch_sql)
            params.extend(branch_params)
            filters_applied.extend(applied + ["tag_lookup"])

        if "FULL_TEXT" in requested_modes and allow_full_text:
            where_sql, where_params, applied = self._document_where_clause(project_uuid, filters)
            branches.append(
                f"""
                SELECT
                  CASE WHEN doc.entity_business_id <> ''
                    THEN doc.entity_type || ':' || doc.entity_business_id
                    ELSE 'document:' || doc.search_document_id
                  END AS dedupe_key,
                  'full_text:' || doc.search_document_id AS candidate_id,
                  'SEARCH_DOCUMENT_FULL_TEXT' AS candidate_kind,
                  '' AS search_memory_card_id,
                  doc.search_document_id,
                  doc.entity_type,
                  doc.entity_business_id,
                  doc.entity_type AS source_type,
                  doc.title,
                  doc.summary AS text_summary,
                  doc.source_refs,
                  'USABLE_NOW' AS access_label,
                  'DOCUMENT_ONLY' AS visibility_status,
                  doc.authority_level,
                  doc.status,
                  doc.lifecycle_state,
                  (
                    2.0
                    + COALESCE(doc.importance, 0)
                    + ts_rank(doc.search_vector, plainto_tsquery('simple', %s))
                    + CASE doc.authority_level
                        WHEN 'USER_LOCKED' THEN 4.0
                        WHEN 'USER_CONFIRMED' THEN 3.0
                        WHEN 'FORMAL_APPLIED' THEN 2.5
                        WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                        ELSE 0.0
                      END
                  )::float AS final_score,
                  jsonb_build_object(
                    'mode_full_text', 2.0,
                    'full_text_rank', ts_rank(doc.search_vector, plainto_tsquery('simple', %s)),
                    'document_importance', COALESCE(doc.importance, 0),
                    'authority_weight',
                      CASE doc.authority_level
                        WHEN 'USER_LOCKED' THEN 4.0
                        WHEN 'USER_CONFIRMED' THEN 3.0
                        WHEN 'FORMAL_APPLIED' THEN 2.5
                        WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                        ELSE 0.0
                      END
                  ) AS score_components,
                  GREATEST(1, CEIL(length(COALESCE(doc.summary, doc.search_text, doc.title))::numeric / 4))::integer AS token_estimate,
                  'PostgreSQL full-text lookup over search_vector' AS explanation
                FROM {self.schema_name}.search_documents doc
                WHERE {where_sql}
                  AND doc.search_vector @@ plainto_tsquery('simple', %s)
                """
            )
            params.extend([cleaned_query, cleaned_query] + where_params + [cleaned_query])
            filters_applied.extend(applied + ["full_text_lookup", "full_text_mode:postgres_tsvector"])
        elif "FULL_TEXT" in requested_modes:
            filters_applied.append("full_text_mode:disabled_by_request")

        if not branches:
            params.append(max_items)
            return (
                """
                SELECT
                  '' AS candidate_id,
                  '' AS candidate_kind,
                  '' AS search_memory_card_id,
                  '' AS search_document_id,
                  '' AS entity_type,
                  '' AS entity_business_id,
                  '' AS source_type,
                  '' AS title,
                  '' AS text_summary,
                  '[]'::jsonb AS source_refs,
                  'USABLE_NOW' AS access_label,
                  'DOCUMENT_ONLY' AS visibility_status,
                  'SYSTEM_CONFIRMED' AS authority_level,
                  'CONFIRMED' AS status,
                  'ACTIVE' AS lifecycle_state,
                  0.0::float AS final_score,
                  '{{}}'::jsonb AS score_components,
                  0 AS token_estimate,
                  'no enabled deterministic text retrieval source' AS explanation
                WHERE FALSE
                LIMIT %s
                """,
                tuple(params),
                sorted(set(filters_applied)),
            )

        params.append(max_items)
        sql = f"""
        WITH raw_candidates AS (
          {' UNION ALL '.join(branches)}
        ),
        ranked_candidates AS (
          SELECT
            raw_candidates.*,
            row_number() OVER (
              PARTITION BY dedupe_key
              ORDER BY final_score DESC, candidate_id
            ) AS dedupe_rank
          FROM raw_candidates
        )
        SELECT
          candidate_id,
          candidate_kind,
          search_memory_card_id,
          search_document_id,
          entity_type,
          entity_business_id,
          source_type,
          title,
          text_summary,
          source_refs,
          access_label,
          visibility_status,
          authority_level,
          status,
          lifecycle_state,
          final_score,
          score_components,
          token_estimate,
          explanation
        FROM ranked_candidates
        WHERE dedupe_rank = 1
        ORDER BY final_score DESC, candidate_id
        LIMIT %s
        """
        return sql, tuple(params), sorted(set(filters_applied))

    def _lookup_table_text_branch(
        self,
        *,
        table_name: str,
        table_alias: str,
        business_id_column: str,
        text_column: str,
        type_column: str,
        match_mode: str,
        score_column: str,
        project_uuid: Any,
        query_text: str,
        filters: LibraryRetrievalFilters,
    ) -> tuple[str, list[Any], list[str]]:
        where_sql, where_params, applied = self._lookup_where_clause(
            table_alias,
            project_uuid,
            filters,
        )
        safe_authorities = self._writer_safe_authority_levels(filters.authority_levels) or list(
            WRITER_SAFE_AUTHORITY_LEVELS
        )
        sql = f"""
        SELECT
          CASE WHEN {table_alias}.entity_business_id <> ''
            THEN {table_alias}.entity_type || ':' || {table_alias}.entity_business_id
            ELSE lower('{match_mode}:') || {table_alias}.{business_id_column}
          END AS dedupe_key,
          lower('{match_mode}:') || {table_alias}.{business_id_column} AS candidate_id,
          'ENTITY_{match_mode}' AS candidate_kind,
          '' AS search_memory_card_id,
          COALESCE(doc.search_document_id, '') AS search_document_id,
          {table_alias}.entity_type,
          {table_alias}.entity_business_id,
          {table_alias}.entity_type AS source_type,
          COALESCE(NULLIF(doc.title, ''), {table_alias}.{text_column}) AS title,
          COALESCE(NULLIF(doc.summary, ''), {table_alias}.{text_column}) AS text_summary,
          COALESCE(doc.source_refs, '[]'::jsonb) || {table_alias}.source_refs AS source_refs,
          'USABLE_NOW' AS access_label,
          'DOCUMENT_ONLY' AS visibility_status,
          {table_alias}.authority_level,
          {table_alias}.status,
          {table_alias}.lifecycle_state,
          (
            3.0
            + COALESCE(doc.importance, 0)
            + COALESCE({table_alias}.{score_column}, 0)
            + CASE {table_alias}.authority_level
                WHEN 'USER_LOCKED' THEN 4.0
                WHEN 'USER_CONFIRMED' THEN 3.0
                WHEN 'FORMAL_APPLIED' THEN 2.5
                WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                ELSE 0.0
              END
          )::float AS final_score,
          jsonb_build_object(
            'mode_{match_mode.lower()}', 3.0,
            'lookup_weight', COALESCE({table_alias}.{score_column}, 0),
            'document_importance', COALESCE(doc.importance, 0),
            'authority_weight',
              CASE {table_alias}.authority_level
                WHEN 'USER_LOCKED' THEN 4.0
                WHEN 'USER_CONFIRMED' THEN 3.0
                WHEN 'FORMAL_APPLIED' THEN 2.5
                WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                ELSE 0.0
              END
          ) AS score_components,
          GREATEST(1, CEIL(length(COALESCE(NULLIF(doc.summary, ''), {table_alias}.{text_column}))::numeric / 4))::integer AS token_estimate,
          lower('{match_mode}') || ' lookup via ' || COALESCE(NULLIF({table_alias}.{type_column}, ''), {table_alias}.entity_type) AS explanation
        FROM {self.schema_name}.{table_name} {table_alias}
        LEFT JOIN {self.schema_name}.search_documents doc
          ON doc.project_id = {table_alias}.project_id
         AND doc.entity_type = {table_alias}.entity_type
         AND doc.entity_business_id = {table_alias}.entity_business_id
         AND doc.deleted_at IS NULL
         AND doc.status NOT IN ('SUPERSEDED', 'ARCHIVED', 'DELETED', 'REJECTED')
         AND doc.lifecycle_state <> 'DELETED'
         AND doc.authority_level = ANY(%s)
        WHERE {where_sql}
          AND lower({table_alias}.{text_column}) = lower(%s)
        """
        return sql, [safe_authorities] + where_params + [query_text], applied

    def _lookup_where_clause(
        self,
        table_alias: str,
        project_uuid: Any,
        filters: LibraryRetrievalFilters,
    ) -> tuple[str, list[Any], list[str]]:
        clauses = [
            f"{table_alias}.project_id = %s",
            f"{table_alias}.deleted_at IS NULL",
            f"{table_alias}.status NOT IN ('SUPERSEDED', 'ARCHIVED', 'DELETED', 'REJECTED')",
            f"{table_alias}.lifecycle_state <> 'DELETED'",
        ]
        params: list[Any] = [project_uuid]
        authority_levels = self._writer_safe_authority_levels(filters.authority_levels)
        if authority_levels:
            clauses.append(f"{table_alias}.authority_level = ANY(%s)")
            params.append(authority_levels)
        else:
            clauses.append("FALSE")
        applied = ["text_lookup"]
        self._add_any_filter(clauses, params, applied, f"{table_alias}.entity_type", filters.entity_types, "entity_types")
        self._add_any_filter(clauses, params, applied, f"{table_alias}.entity_type", filters.source_types, "source_types")
        self._add_any_filter(clauses, params, applied, f"{table_alias}.entity_business_id", filters.memory_ids, "memory_ids")
        return "\n          AND ".join(clauses), params, applied

    def _search_candidates_sql_and_params(
        self,
        *,
        project_uuid: Any,
        filters: LibraryRetrievalFilters,
        max_items: int,
        include_cards: bool,
        include_documents: bool,
    ) -> tuple[str, tuple[Any, ...], list[str]]:
        if not include_cards and not include_documents:
            raise StorageError("LIBRARY_RETRIEVAL_SOURCE_REQUIRED: at least one source family must be included.")
        branches: list[str] = []
        params: list[Any] = []
        filters_applied: list[str] = []
        if include_cards:
            where_sql, where_params, applied = self._card_where_clause(project_uuid, filters)
            branches.append(self._card_candidate_sql(where_sql))
            params.extend(where_params)
            filters_applied.extend(applied)
        if include_documents:
            where_sql, where_params, applied = self._document_where_clause(project_uuid, filters)
            branches.append(self._document_candidate_sql(where_sql))
            params.extend(where_params)
            filters_applied.extend(applied)
        params.append(max_items)
        sql = f"""
        SELECT *
        FROM (
          {' UNION ALL '.join(branches)}
        ) candidates
        ORDER BY final_score DESC, candidate_id
        LIMIT %s
        """
        return sql, tuple(params), sorted(set(filters_applied))

    def _card_candidate_sql(self, where_sql: str) -> str:
        return f"""
        SELECT
          'card:' || card.search_memory_card_id AS candidate_id,
          'SEARCH_MEMORY_CARD' AS candidate_kind,
          card.search_memory_card_id,
          COALESCE(doc.search_document_id, '') AS search_document_id,
          COALESCE(doc.entity_type, card.source_type) AS entity_type,
          card.source_id AS entity_business_id,
          card.source_type,
          COALESCE(doc.title, card.memory_lane, card.source_type) AS title,
          card.text_summary,
          card.source_refs,
          'USABLE_NOW' AS access_label,
          card.visibility_status,
          card.authority_level,
          card.status,
          card.lifecycle_state,
          (
            1.0
            + COALESCE(doc.importance, 0)
            + CASE card.authority_level
                WHEN 'USER_LOCKED' THEN 4.0
                WHEN 'USER_CONFIRMED' THEN 3.0
                WHEN 'FORMAL_APPLIED' THEN 2.5
                WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                ELSE 0.0
              END
          )::float AS final_score,
          jsonb_build_object(
            'base_score', 1.0,
            'document_importance', COALESCE(doc.importance, 0),
            'authority_weight',
              CASE card.authority_level
                WHEN 'USER_LOCKED' THEN 4.0
                WHEN 'USER_CONFIRMED' THEN 3.0
                WHEN 'FORMAL_APPLIED' THEN 2.5
                WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                ELSE 0.0
              END
          ) AS score_components,
          GREATEST(1, CEIL(length(card.text_summary)::numeric / 4))::integer AS token_estimate,
          'structured card match via ' || card.source_type AS explanation
        FROM {self.schema_name}.search_memory_cards card
        LEFT JOIN {self.schema_name}.search_documents doc
          ON doc.id = card.source_search_document_id
         AND doc.project_id = card.project_id
         AND doc.deleted_at IS NULL
        LEFT JOIN {self.schema_name}.scenes scene
          ON scene.id = card.source_scene_id
         AND scene.project_id = card.project_id
         AND scene.deleted_at IS NULL
        LEFT JOIN {self.schema_name}.chapters chapter
          ON chapter.id = scene.chapter_id
         AND chapter.project_id = card.project_id
         AND chapter.deleted_at IS NULL
        WHERE {where_sql}
        """

    def _document_candidate_sql(self, where_sql: str) -> str:
        return f"""
        SELECT
          'document:' || doc.search_document_id AS candidate_id,
          'SEARCH_DOCUMENT' AS candidate_kind,
          '' AS search_memory_card_id,
          doc.search_document_id,
          doc.entity_type,
          doc.entity_business_id,
          doc.entity_type AS source_type,
          doc.title,
          doc.summary AS text_summary,
          doc.source_refs,
          'USABLE_NOW' AS access_label,
          'DOCUMENT_ONLY' AS visibility_status,
          doc.authority_level,
          doc.status,
          doc.lifecycle_state,
          (
            0.5
            + COALESCE(doc.importance, 0)
            + CASE doc.authority_level
                WHEN 'USER_LOCKED' THEN 4.0
                WHEN 'USER_CONFIRMED' THEN 3.0
                WHEN 'FORMAL_APPLIED' THEN 2.5
                WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                ELSE 0.0
              END
          )::float AS final_score,
          jsonb_build_object(
            'base_score', 0.5,
            'document_importance', COALESCE(doc.importance, 0),
            'authority_weight',
              CASE doc.authority_level
                WHEN 'USER_LOCKED' THEN 4.0
                WHEN 'USER_CONFIRMED' THEN 3.0
                WHEN 'FORMAL_APPLIED' THEN 2.5
                WHEN 'SYSTEM_CONFIRMED' THEN 2.0
                ELSE 0.0
              END
          ) AS score_components,
          GREATEST(1, CEIL(length(doc.summary)::numeric / 4))::integer AS token_estimate,
          'structured document match via ' || doc.entity_type AS explanation
        FROM {self.schema_name}.search_documents doc
        WHERE {where_sql}
        """

    def _card_where_clause(
        self,
        project_uuid: Any,
        filters: LibraryRetrievalFilters,
    ) -> tuple[str, list[Any], list[str]]:
        clauses = [
            "card.project_id = %s",
            "card.deleted_at IS NULL",
            "card.status NOT IN ('SUPERSEDED', 'ARCHIVED', 'DELETED', 'REJECTED')",
            "card.lifecycle_state <> 'DELETED'",
        ]
        params: list[Any] = [project_uuid]
        authority_levels = self._writer_safe_authority_levels(filters.authority_levels)
        visibility_statuses = self._writer_safe_visibility_statuses(filters.visibility_statuses)
        if authority_levels:
            clauses.append("card.authority_level = ANY(%s)")
            params.append(authority_levels)
        else:
            clauses.append("FALSE")
        if visibility_statuses:
            clauses.append("card.visibility_status = ANY(%s)")
            params.append(visibility_statuses)
        else:
            clauses.append("FALSE")
        applied = ["cards"]
        self._add_any_filter(clauses, params, applied, "COALESCE(doc.entity_type, card.source_type)", filters.entity_types, "entity_types")
        self._add_any_filter(clauses, params, applied, "card.source_type", filters.source_types, "source_types")
        self._add_any_filter(clauses, params, applied, "chapter.chapter_id", filters.chapter_ids, "chapter_ids")
        self._add_any_filter(clauses, params, applied, "scene.scene_id", filters.scene_ids, "scene_ids")
        self._add_any_filter(clauses, params, applied, "card.memory_lane", filters.memory_lanes, "memory_lanes")
        self._add_any_filter(clauses, params, applied, "card.source_id", filters.memory_ids, "memory_ids")
        if filters.character_ids:
            clauses.append(
                "EXISTS (SELECT 1 FROM jsonb_array_elements(card.character_refs) ref WHERE ref->>'id' = ANY(%s))"
            )
            params.append(filters.character_ids)
            applied.append("character_ids")
        if filters.location_ids:
            clauses.append(
                "EXISTS (SELECT 1 FROM jsonb_array_elements(card.location_refs) ref WHERE ref->>'id' = ANY(%s))"
            )
            params.append(filters.location_ids)
            applied.append("location_ids")
        return "\n          AND ".join(clauses), params, applied

    def _document_where_clause(
        self,
        project_uuid: Any,
        filters: LibraryRetrievalFilters,
    ) -> tuple[str, list[Any], list[str]]:
        clauses = [
            "doc.project_id = %s",
            "doc.deleted_at IS NULL",
            "doc.status NOT IN ('SUPERSEDED', 'ARCHIVED', 'DELETED', 'REJECTED')",
            "doc.lifecycle_state <> 'DELETED'",
        ]
        params: list[Any] = [project_uuid]
        authority_levels = self._writer_safe_authority_levels(filters.authority_levels)
        if authority_levels:
            clauses.append("doc.authority_level = ANY(%s)")
            params.append(authority_levels)
        else:
            clauses.append("FALSE")
        applied = ["documents"]
        self._add_any_filter(clauses, params, applied, "doc.entity_type", filters.entity_types, "entity_types")
        self._add_any_filter(clauses, params, applied, "doc.entity_type", filters.source_types, "source_types")
        self._add_any_filter(clauses, params, applied, "doc.entity_business_id", filters.memory_ids, "memory_ids")
        if filters.chapter_ids:
            clauses.append(
                "((doc.entity_type = 'CHAPTER_SUMMARY' AND doc.entity_business_id = ANY(%s)) OR doc.metadata->>'chapter_id' = ANY(%s))"
            )
            params.extend([filters.chapter_ids, filters.chapter_ids])
            applied.append("chapter_ids")
        if filters.scene_ids:
            clauses.append(
                "((doc.entity_type = 'SCENE_SUMMARY' AND doc.entity_business_id = ANY(%s)) OR doc.metadata->>'scene_id' = ANY(%s))"
            )
            params.extend([filters.scene_ids, filters.scene_ids])
            applied.append("scene_ids")
        if filters.framework_ids:
            clauses.append("doc.entity_type LIKE 'FRAMEWORK_%' AND doc.entity_business_id = ANY(%s)")
            params.append(filters.framework_ids)
            applied.append("framework_ids")
        return "\n          AND ".join(clauses), params, applied

    def _add_any_filter(
        self,
        clauses: list[str],
        params: list[Any],
        applied: list[str],
        sql_expression: str,
        values: list[str],
        label: str,
    ) -> None:
        if not values:
            return
        clauses.append(f"{sql_expression} = ANY(%s)")
        params.append(values)
        applied.append(label)

    def _writer_safe_authority_levels(self, requested: list[str]) -> list[str]:
        if not requested:
            return list(WRITER_SAFE_AUTHORITY_LEVELS)
        return [level for level in requested if level in WRITER_SAFE_AUTHORITY_LEVELS]

    def _writer_safe_visibility_statuses(self, requested: list[str]) -> list[str]:
        if not requested:
            return list(WRITER_SAFE_VISIBILITY_STATUSES)
        return [status for status in requested if status in WRITER_SAFE_VISIBILITY_STATUSES]

    def _relationship_link_types(self, requested: list[str]) -> list[str]:
        if not requested:
            return list(DEFAULT_RELATIONSHIP_LINK_TYPES)
        return [link_type for link_type in requested if link_type in DEFAULT_RELATIONSHIP_LINK_TYPES]

    def _merge_filters(
        self,
        task_filters: LibraryRetrievalFilters | None,
        request_filters: LibraryRetrievalFilters,
    ) -> LibraryRetrievalFilters:
        if task_filters is None:
            return request_filters
        merged: dict[str, list[str]] = {}
        for field in LibraryRetrievalFilters.__fields__:
            merged[field] = sorted(set(getattr(task_filters, field)) | set(getattr(request_filters, field)))
        return LibraryRetrievalFilters(**merged)

    def _bounded_max_items(self, *values: int | None) -> int:
        effective = min(value for value in values if value)
        return max(1, min(int(effective), MAX_STRUCTURED_RETRIEVAL_ITEMS))

    def _bounded_token_budget(self, *values: int | None) -> int:
        effective = min(value for value in values if value)
        return max(1, min(int(effective), MAX_STRUCTURED_RETRIEVAL_TOKEN_BUDGET))

    def _candidate_from_row(self, row: Any) -> LibraryRetrievalCandidate:
        source_refs = row[9] or []
        score_components = row[16] or {}
        return LibraryRetrievalCandidate(
            candidate_id=str(row[0] or ""),
            candidate_kind=str(row[1] or ""),
            search_memory_card_id=str(row[2] or ""),
            search_document_id=str(row[3] or ""),
            entity_type=str(row[4] or ""),
            entity_business_id=str(row[5] or ""),
            source_type=str(row[6] or ""),
            title=str(row[7] or ""),
            text_summary=str(row[8] or ""),
            source_refs=source_refs if isinstance(source_refs, list) else [],
            access_label=str(row[10] or ""),
            visibility_status=str(row[11] or ""),
            authority_level=str(row[12] or ""),
            status=str(row[13] or ""),
            lifecycle_state=str(row[14] or ""),
            score=float(row[15] or 0),
            score_components={key: float(value or 0) for key, value in dict(score_components).items()},
            token_estimate=int(row[17] or 0),
            explanation=str(row[18] or ""),
            m10_eligible=True,
            writer_agent_fact_ready=False,
        )

    def _candidates_within_budget(
        self,
        candidates: list[LibraryRetrievalCandidate],
        token_budget: int,
    ) -> tuple[list[LibraryRetrievalCandidate], int, bool]:
        selected: list[LibraryRetrievalCandidate] = []
        total = 0
        truncated = False
        for candidate in candidates:
            next_total = total + max(1, candidate.token_estimate)
            if next_total > token_budget:
                truncated = True
                break
            selected.append(candidate)
            total = next_total
        return selected, total, truncated

    def _task_spec_from_row(self, row: Any) -> LibraryRetrievalTaskSpec:
        filters = row[4] or {}
        required_entity_refs = row[5] or []
        source_refs = row[11] or []
        metadata = row[12] or {}
        return LibraryRetrievalTaskSpec(
            retrieval_task_id=str(row[0] or ""),
            agent_role=str(row[1] or ""),
            task_type=str(row[2] or ""),
            query_text=str(row[3] or ""),
            filters=LibraryRetrievalFilters(**dict(filters)),
            required_entity_refs=required_entity_refs if isinstance(required_entity_refs, list) else [],
            max_items=int(row[6] or 20),
            token_budget=int(row[7] or 1200),
            status=str(row[8] or ""),
            lifecycle_state=str(row[9] or ""),
            authority_level=str(row[10] or ""),
            source_refs=source_refs if isinstance(source_refs, list) else [],
            metadata=dict(metadata),
        )

    @staticmethod
    def _fetchall(cursor: Any) -> list[Any]:
        fetchall = getattr(cursor, "fetchall", None)
        if callable(fetchall):
            return list(fetchall())
        rows: list[Any] = []
        while True:
            row = cursor.fetchone()
            if row is None:
                break
            rows.append(row)
        return rows
