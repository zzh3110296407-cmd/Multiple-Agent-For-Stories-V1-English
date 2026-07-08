from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.backend.core.config import STORAGE_MODE_POSTGRES_PRIMARY, settings
from app.backend.repositories.postgres_normalized_repositories import PostgresConnectionFactory
from app.backend.services.runtime_project_mapping import resolve_runtime_project_mapping, validate_runtime_project_id
from app.backend.storage.json_store import StorageError


ACTIVE_SOURCE_STATUS_EXCLUSIONS = ("SUPERSEDED", "ARCHIVED", "DELETED", "REJECTED")
INDEXER_SOURCE_TYPE = "M11_CATALOG_INDEX"
CARD_SOURCE_TYPES = ("CHARACTER_MEMORY_NODE", "LOCATION_STATE_NODE", "LOCATION_CHANGE_DELTA")


@dataclass(frozen=True)
class CatalogDocumentSourceSpec:
    entity_type: str
    table_name: str
    business_id_column: str
    title_sql: str
    summary_sql: str
    source_coverage: str
    superseded_column: str = ""


@dataclass(frozen=True)
class CatalogIndexRefreshResult:
    project_id: str
    search_document_sources: list[str]
    search_memory_card_sources: list[str]
    search_documents_upserted: int
    search_documents_archived: int
    search_memory_cards_upserted: int
    search_memory_cards_archived: int
    raw_long_prose_primary_surface: bool
    writer_agent_fact_ready: bool


CATALOG_DOCUMENT_SOURCE_SPECS = (
    CatalogDocumentSourceSpec(
        entity_type="CHAPTER_SUMMARY",
        table_name="chapters",
        business_id_column="chapter_id",
        title_sql="title",
        summary_sql="chapter_summary",
        source_coverage="chapter summaries",
    ),
    CatalogDocumentSourceSpec(
        entity_type="SCENE_SUMMARY",
        table_name="scenes",
        business_id_column="scene_id",
        title_sql="scene_title",
        summary_sql="scene_summary",
        source_coverage="scene summaries",
    ),
    CatalogDocumentSourceSpec(
        entity_type="EVENT_SUMMARY",
        table_name="events",
        business_id_column="event_id",
        title_sql="event_type",
        summary_sql="event_summary",
        source_coverage="event summaries",
    ),
    CatalogDocumentSourceSpec(
        entity_type="RELATIONSHIP_RECORD",
        table_name="relationships",
        business_id_column="relationship_id",
        title_sql="relationship_type",
        summary_sql="relationship_summary",
        source_coverage="relationship records",
    ),
    CatalogDocumentSourceSpec(
        entity_type="QUALITY_FINDING",
        table_name="quality_reports",
        business_id_column="quality_report_id",
        title_sql="report_type",
        summary_sql="summary",
        source_coverage="quality findings",
    ),
    CatalogDocumentSourceSpec(
        entity_type="CONTINUITY_FINDING",
        table_name="continuity_issues",
        business_id_column="continuity_issue_id",
        title_sql="issue_type",
        summary_sql="issue_text",
        source_coverage="continuity findings",
    ),
    CatalogDocumentSourceSpec(
        entity_type="FORESHADOWING_ITEM",
        table_name="prior_story_completion_candidates",
        business_id_column="candidate_id",
        title_sql="candidate_type",
        summary_sql="candidate_text",
        source_coverage="foreshadowing items",
    ),
    CatalogDocumentSourceSpec(
        entity_type="RELATIONSHIP_DEBT",
        table_name="narrative_debts",
        business_id_column="debt_id",
        title_sql="debt_type",
        summary_sql="debt_text",
        source_coverage="relationship debts or narrative debts",
    ),
    CatalogDocumentSourceSpec(
        entity_type="FRAMEWORK_ROLE_CANDIDATE",
        table_name="role_generation_candidates",
        business_id_column="role_candidate_id",
        title_sql="'role generation candidate'",
        summary_sql="left(candidate_payload::text, 500)",
        source_coverage="framework candidates or framework components",
    ),
    CatalogDocumentSourceSpec(
        entity_type="FRAMEWORK_PACKAGE",
        table_name="framework_packages",
        business_id_column="framework_package_id",
        title_sql="package_name",
        summary_sql="left(package_payload::text, 500)",
        source_coverage="framework candidates or framework components",
    ),
    CatalogDocumentSourceSpec(
        entity_type="FRAMEWORK_COMPONENT",
        table_name="macro_framework_components",
        business_id_column="component_id",
        title_sql="component_type",
        summary_sql="left(component_payload::text, 500)",
        source_coverage="framework candidates or framework components",
    ),
    CatalogDocumentSourceSpec(
        entity_type="CHARACTER_MEMORY_NODE",
        table_name="character_memory_nodes",
        business_id_column="character_memory_node_id",
        title_sql="memory_type",
        summary_sql="summary",
        source_coverage="character_memory_nodes",
        superseded_column="superseded_by_id",
    ),
    CatalogDocumentSourceSpec(
        entity_type="LOCATION_STATE_NODE",
        table_name="location_state_nodes",
        business_id_column="location_state_node_id",
        title_sql="'location state'",
        summary_sql="left(state_snapshot::text, 500)",
        source_coverage="location_state_nodes",
        superseded_column="superseded_by_id",
    ),
    CatalogDocumentSourceSpec(
        entity_type="LOCATION_CHANGE_DELTA",
        table_name="location_change_deltas",
        business_id_column="location_change_delta_id",
        title_sql="'location change'",
        summary_sql="change_summary",
        source_coverage="location_change_deltas",
        superseded_column="superseded_by_id",
    ),
)

REQUIRED_TASK2_SOURCE_COVERAGE = (
    "character_memory_nodes",
    "location_state_nodes",
    "location_change_deltas",
    "scene summaries",
    "chapter summaries",
    "framework candidates or framework components",
    "relationship debts or relationship records",
    "event summaries",
    "foreshadowing items",
    "quality or continuity findings where present",
)


class LibraryRetrievalIndexingService:
    def __init__(self, *, connection_factory: PostgresConnectionFactory | None = None) -> None:
        self._connection_factory = connection_factory
        self.schema_name = connection_factory.schema_name if connection_factory is not None else "mas_phase875_proto"

    def refresh_catalog_and_cards(
        self,
        *,
        project_id: str = "",
    ) -> CatalogIndexRefreshResult:
        active_project_id = self._resolve_project_id(project_id)
        self._ensure_postgres_primary_mode()
        with self._connect() as conn:
            project_uuid = self._resolve_project_uuid(conn, active_project_id)
            search_documents_upserted = sum(
                self._rowcount(conn.execute(self._upsert_search_documents_sql(spec), (project_uuid,)))
                for spec in CATALOG_DOCUMENT_SOURCE_SPECS
            )
            search_memory_cards_upserted = (
                self._rowcount(conn.execute(self._upsert_character_memory_cards_sql(), (project_uuid,)))
                + self._rowcount(conn.execute(self._upsert_location_state_cards_sql(), (project_uuid,)))
                + self._rowcount(conn.execute(self._upsert_location_change_delta_cards_sql(), (project_uuid,)))
            )
            search_documents_archived = sum(
                self._rowcount(conn.execute(self._archive_stale_search_documents_sql(spec), (project_uuid,)))
                for spec in CATALOG_DOCUMENT_SOURCE_SPECS
            )
            search_memory_cards_archived = (
                self._rowcount(conn.execute(self._archive_stale_character_memory_cards_sql(), (project_uuid,)))
                + self._rowcount(conn.execute(self._archive_stale_location_state_cards_sql(), (project_uuid,)))
                + self._rowcount(conn.execute(self._archive_stale_location_change_delta_cards_sql(), (project_uuid,)))
            )
        return CatalogIndexRefreshResult(
            project_id=active_project_id,
            search_document_sources=[spec.source_coverage for spec in CATALOG_DOCUMENT_SOURCE_SPECS],
            search_memory_card_sources=list(CARD_SOURCE_TYPES),
            search_documents_upserted=search_documents_upserted,
            search_documents_archived=search_documents_archived,
            search_memory_cards_upserted=search_memory_cards_upserted,
            search_memory_cards_archived=search_memory_cards_archived,
            raw_long_prose_primary_surface=False,
            writer_agent_fact_ready=False,
        )

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
                "LIBRARY_RETRIEVAL_INDEXING_POSTGRES_PRIMARY_REQUIRED: "
                "catalog/card indexing refresh is available only in explicit postgres_primary mode."
            )

    def _connect(self) -> Any:
        return self._active_connection_factory().connect()

    def _active_connection_factory(self) -> PostgresConnectionFactory:
        if self._connection_factory is not None:
            return self._connection_factory
        return PostgresConnectionFactory(database_url=settings.database_url)

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
            raise StorageError("LIBRARY_RETRIEVAL_INDEXING_PROJECT_NOT_FOUND: project_id was not found.")
        return row[0]

    def _upsert_search_documents_sql(self, spec: CatalogDocumentSourceSpec) -> str:
        active_filter = self._active_source_filter("src", spec.superseded_column)
        return f"""
        INSERT INTO {self.schema_name}.search_documents (
          project_id,
          search_document_id,
          schema_version,
          entity_type,
          entity_business_id,
          entity_physical_id,
          title,
          summary,
          search_text,
          importance,
          indexed_at,
          indexed_content_hash,
          status,
          legacy_status_raw,
          lifecycle_state,
          authority_level,
          version,
          revision,
          source_type,
          source_id,
          source_refs,
          content_hash,
          metadata,
          updated_at,
          deleted_at
        )
        SELECT
          src.project_id,
          'search_document:{spec.entity_type}:' || src.{spec.business_id_column},
          'phase9_m11_task2',
          '{spec.entity_type}',
          src.{spec.business_id_column},
          src.id,
          left(coalesce(nullif({spec.title_sql}, ''), '{spec.entity_type}'), 180),
          left(coalesce(nullif({spec.summary_sql}, ''), ''), 500),
          left(coalesce(nullif({spec.summary_sql}, ''), ''), 500),
          0,
          now(),
          src.content_hash,
          src.status,
          src.legacy_status_raw,
          src.lifecycle_state,
          src.authority_level,
          src.version,
          src.revision,
          '{INDEXER_SOURCE_TYPE}',
          src.{spec.business_id_column},
          src.source_refs || jsonb_build_array(jsonb_build_object(
            'source_table', '{spec.table_name}',
            'source_business_id', src.{spec.business_id_column}
          )),
          src.content_hash,
          jsonb_build_object(
            'm11_index_source', '{spec.source_coverage}',
            'raw_long_prose_primary_surface', false,
            'writer_agent_fact_ready', false
          ),
          now(),
          NULL
        FROM {self.schema_name}.{spec.table_name} src
        WHERE src.project_id = %s
          AND {active_filter}
        ON CONFLICT (project_id, search_document_id) DO UPDATE
        SET schema_version = EXCLUDED.schema_version,
            entity_type = EXCLUDED.entity_type,
            entity_business_id = EXCLUDED.entity_business_id,
            entity_physical_id = EXCLUDED.entity_physical_id,
            title = EXCLUDED.title,
            summary = EXCLUDED.summary,
            search_text = EXCLUDED.search_text,
            indexed_at = EXCLUDED.indexed_at,
            indexed_content_hash = EXCLUDED.indexed_content_hash,
            status = EXCLUDED.status,
            legacy_status_raw = EXCLUDED.legacy_status_raw,
            lifecycle_state = EXCLUDED.lifecycle_state,
            authority_level = EXCLUDED.authority_level,
            version = EXCLUDED.version,
            revision = EXCLUDED.revision,
            source_type = EXCLUDED.source_type,
            source_id = EXCLUDED.source_id,
            source_refs = EXCLUDED.source_refs,
            content_hash = EXCLUDED.content_hash,
            metadata = EXCLUDED.metadata,
            updated_at = now(),
            deleted_at = NULL
        """

    def _archive_stale_search_documents_sql(self, spec: CatalogDocumentSourceSpec) -> str:
        active_filter = self._active_source_filter("src", spec.superseded_column)
        return f"""
        UPDATE {self.schema_name}.search_documents doc
        SET status = 'SUPERSEDED',
            lifecycle_state = 'ARCHIVED',
            metadata = doc.metadata || jsonb_build_object('m11_index_archived_stale_source', true),
            updated_at = now(),
            deleted_at = COALESCE(doc.deleted_at, now())
        WHERE doc.project_id = %s
          AND doc.entity_type = '{spec.entity_type}'
          AND doc.source_type = '{INDEXER_SOURCE_TYPE}'
          AND NOT EXISTS (
            SELECT 1
            FROM {self.schema_name}.{spec.table_name} src
            WHERE src.project_id = doc.project_id
              AND src.{spec.business_id_column} = doc.entity_business_id
              AND {active_filter}
          )
        """

    def _upsert_character_memory_cards_sql(self) -> str:
        return f"""
        INSERT INTO {self.schema_name}.search_memory_cards (
          project_id, search_memory_card_id, source_search_document_id, timeline_id, source_scene_id,
          character_memory_node_id, schema_version, source_type, text_summary, keywords, entity_refs,
          character_refs, location_refs, world_time_range, narrative_range, known_by_refs,
          revealed_to_reader_at, visibility_status, memory_lane, status, legacy_status_raw,
          lifecycle_state, authority_level, version, revision, source_id, source_refs, content_hash,
          metadata, updated_at, deleted_at
        )
        SELECT
          cmn.project_id,
          'search_memory_card:character_memory_node:' || cmn.character_memory_node_id,
          sd.id,
          cmn.timeline_id,
          cmn.source_scene_id,
          cmn.id,
          'phase9_m11_task2',
          'CHARACTER_MEMORY_NODE',
          left(coalesce(nullif(cmn.summary, ''), nullif(cmn.content, ''), ''), 500),
          '[]'::jsonb,
          jsonb_build_array(jsonb_build_object('type', 'character_memory_node', 'id', cmn.character_memory_node_id)),
          jsonb_build_array(jsonb_build_object('type', 'character', 'id', ch.character_id)),
          '[]'::jsonb,
          jsonb_build_object(
            'experienced_at_sort_key', cmn.experienced_at_sort_key,
            'valid_from_sort_key', cmn.valid_from_sort_key,
            'valid_to_sort_key', cmn.valid_to_sort_key
          ),
          jsonb_build_object('narrative_recorded_at_sort_key', cmn.narrative_recorded_at_sort_key),
          jsonb_build_array(jsonb_build_object('type', 'character', 'id', ch.character_id)),
          cmn.narrative_recorded_at,
          cmn.visibility_status,
          cmn.memory_type,
          cmn.status,
          cmn.legacy_status_raw,
          cmn.lifecycle_state,
          cmn.authority_level,
          cmn.version,
          cmn.revision,
          cmn.character_memory_node_id,
          cmn.source_refs || jsonb_build_array(jsonb_build_object(
            'source_table', 'character_memory_nodes',
            'source_business_id', cmn.character_memory_node_id
          )),
          cmn.content_hash,
          jsonb_build_object('writer_agent_fact_ready', false),
          now(),
          NULL
        FROM {self.schema_name}.character_memory_nodes cmn
        JOIN {self.schema_name}.characters ch
          ON ch.id = cmn.character_id
         AND ch.project_id = cmn.project_id
         AND ch.deleted_at IS NULL
        LEFT JOIN {self.schema_name}.search_documents sd
          ON sd.project_id = cmn.project_id
         AND sd.entity_type = 'CHARACTER_MEMORY_NODE'
         AND sd.entity_business_id = cmn.character_memory_node_id
         AND sd.deleted_at IS NULL
        WHERE cmn.project_id = %s
          AND {self._active_source_filter("cmn", "superseded_by_id")}
        ON CONFLICT (project_id, search_memory_card_id) DO UPDATE
        SET source_search_document_id = EXCLUDED.source_search_document_id,
            timeline_id = EXCLUDED.timeline_id,
            source_scene_id = EXCLUDED.source_scene_id,
            character_memory_node_id = EXCLUDED.character_memory_node_id,
            text_summary = EXCLUDED.text_summary,
            entity_refs = EXCLUDED.entity_refs,
            character_refs = EXCLUDED.character_refs,
            world_time_range = EXCLUDED.world_time_range,
            narrative_range = EXCLUDED.narrative_range,
            known_by_refs = EXCLUDED.known_by_refs,
            revealed_to_reader_at = EXCLUDED.revealed_to_reader_at,
            visibility_status = EXCLUDED.visibility_status,
            memory_lane = EXCLUDED.memory_lane,
            status = EXCLUDED.status,
            legacy_status_raw = EXCLUDED.legacy_status_raw,
            lifecycle_state = EXCLUDED.lifecycle_state,
            authority_level = EXCLUDED.authority_level,
            version = EXCLUDED.version,
            revision = EXCLUDED.revision,
            source_refs = EXCLUDED.source_refs,
            content_hash = EXCLUDED.content_hash,
            metadata = EXCLUDED.metadata,
            updated_at = now(),
            deleted_at = NULL
        """

    def _upsert_location_state_cards_sql(self) -> str:
        return f"""
        INSERT INTO {self.schema_name}.search_memory_cards (
          project_id, search_memory_card_id, source_search_document_id, timeline_id, location_state_node_id,
          schema_version, source_type, text_summary, keywords, entity_refs, character_refs, location_refs,
          world_time_range, narrative_range, known_by_refs, revealed_to_reader_at, visibility_status,
          memory_lane, status, legacy_status_raw, lifecycle_state, authority_level, version, revision,
          source_id, source_refs, content_hash, metadata, updated_at, deleted_at
        )
        SELECT
          lsn.project_id,
          'search_memory_card:location_state_node:' || lsn.location_state_node_id,
          sd.id,
          lsn.timeline_id,
          lsn.id,
          'phase9_m11_task2',
          'LOCATION_STATE_NODE',
          left(lsn.state_snapshot::text, 500),
          '[]'::jsonb,
          jsonb_build_array(jsonb_build_object('type', 'location_state_node', 'id', lsn.location_state_node_id)),
          '[]'::jsonb,
          jsonb_build_array(jsonb_build_object('type', 'location', 'id', wl.location_id)),
          jsonb_build_object(
            'time_anchor_sort_key', lsn.time_anchor_sort_key,
            'valid_from_sort_key', lsn.valid_from_sort_key,
            'valid_to_sort_key', lsn.valid_to_sort_key
          ),
          '{{}}'::jsonb,
          lsn.known_by_character_refs,
          lsn.revealed_to_reader_at,
          lsn.visibility_status,
          'LOCATION_STATE',
          lsn.status,
          lsn.legacy_status_raw,
          lsn.lifecycle_state,
          lsn.authority_level,
          lsn.version,
          lsn.revision,
          lsn.location_state_node_id,
          lsn.source_refs || jsonb_build_array(jsonb_build_object(
            'source_table', 'location_state_nodes',
            'source_business_id', lsn.location_state_node_id
          )),
          lsn.content_hash,
          jsonb_build_object('writer_agent_fact_ready', false),
          now(),
          NULL
        FROM {self.schema_name}.location_state_nodes lsn
        JOIN {self.schema_name}.world_locations wl
          ON wl.id = lsn.location_id
         AND wl.project_id = lsn.project_id
         AND wl.deleted_at IS NULL
        LEFT JOIN {self.schema_name}.search_documents sd
          ON sd.project_id = lsn.project_id
         AND sd.entity_type = 'LOCATION_STATE_NODE'
         AND sd.entity_business_id = lsn.location_state_node_id
         AND sd.deleted_at IS NULL
        WHERE lsn.project_id = %s
          AND {self._active_source_filter("lsn", "superseded_by_id")}
        ON CONFLICT (project_id, search_memory_card_id) DO UPDATE
        SET source_search_document_id = EXCLUDED.source_search_document_id,
            timeline_id = EXCLUDED.timeline_id,
            location_state_node_id = EXCLUDED.location_state_node_id,
            text_summary = EXCLUDED.text_summary,
            entity_refs = EXCLUDED.entity_refs,
            location_refs = EXCLUDED.location_refs,
            world_time_range = EXCLUDED.world_time_range,
            known_by_refs = EXCLUDED.known_by_refs,
            revealed_to_reader_at = EXCLUDED.revealed_to_reader_at,
            visibility_status = EXCLUDED.visibility_status,
            memory_lane = EXCLUDED.memory_lane,
            status = EXCLUDED.status,
            legacy_status_raw = EXCLUDED.legacy_status_raw,
            lifecycle_state = EXCLUDED.lifecycle_state,
            authority_level = EXCLUDED.authority_level,
            version = EXCLUDED.version,
            revision = EXCLUDED.revision,
            source_refs = EXCLUDED.source_refs,
            content_hash = EXCLUDED.content_hash,
            metadata = EXCLUDED.metadata,
            updated_at = now(),
            deleted_at = NULL
        """

    def _upsert_location_change_delta_cards_sql(self) -> str:
        return f"""
        INSERT INTO {self.schema_name}.search_memory_cards (
          project_id, search_memory_card_id, source_search_document_id, location_change_delta_id,
          schema_version, source_type, text_summary, keywords, entity_refs, character_refs, location_refs,
          world_time_range, narrative_range, known_by_refs, revealed_to_reader_at, visibility_status,
          memory_lane, status, legacy_status_raw, lifecycle_state, authority_level, version, revision,
          source_id, source_refs, content_hash, metadata, updated_at, deleted_at
        )
        SELECT
          lcd.project_id,
          'search_memory_card:location_change_delta:' || lcd.location_change_delta_id,
          sd.id,
          lcd.id,
          'phase9_m11_task2',
          'LOCATION_CHANGE_DELTA',
          left(coalesce(nullif(lcd.change_summary, ''), nullif(lcd.change_detail, ''), ''), 500),
          '[]'::jsonb,
          jsonb_build_array(jsonb_build_object('type', 'location_change_delta', 'id', lcd.location_change_delta_id)),
          '[]'::jsonb,
          jsonb_build_array(jsonb_build_object('type', 'location', 'id', wl.location_id)),
          '{{}}'::jsonb,
          '{{}}'::jsonb,
          lcd.known_by_character_refs,
          lcd.revealed_to_reader_at,
          lcd.visibility_status,
          'LOCATION_CHANGE_DELTA',
          lcd.status,
          lcd.legacy_status_raw,
          lcd.lifecycle_state,
          lcd.authority_level,
          lcd.version,
          lcd.revision,
          lcd.location_change_delta_id,
          lcd.source_refs || jsonb_build_array(jsonb_build_object(
            'source_table', 'location_change_deltas',
            'source_business_id', lcd.location_change_delta_id
          )),
          lcd.content_hash,
          jsonb_build_object('writer_agent_fact_ready', false),
          now(),
          NULL
        FROM {self.schema_name}.location_change_deltas lcd
        JOIN {self.schema_name}.world_locations wl
          ON wl.id = lcd.location_id
         AND wl.project_id = lcd.project_id
         AND wl.deleted_at IS NULL
        LEFT JOIN {self.schema_name}.search_documents sd
          ON sd.project_id = lcd.project_id
         AND sd.entity_type = 'LOCATION_CHANGE_DELTA'
         AND sd.entity_business_id = lcd.location_change_delta_id
         AND sd.deleted_at IS NULL
        WHERE lcd.project_id = %s
          AND {self._active_source_filter("lcd", "superseded_by_id")}
        ON CONFLICT (project_id, search_memory_card_id) DO UPDATE
        SET source_search_document_id = EXCLUDED.source_search_document_id,
            location_change_delta_id = EXCLUDED.location_change_delta_id,
            text_summary = EXCLUDED.text_summary,
            entity_refs = EXCLUDED.entity_refs,
            location_refs = EXCLUDED.location_refs,
            known_by_refs = EXCLUDED.known_by_refs,
            revealed_to_reader_at = EXCLUDED.revealed_to_reader_at,
            visibility_status = EXCLUDED.visibility_status,
            memory_lane = EXCLUDED.memory_lane,
            status = EXCLUDED.status,
            legacy_status_raw = EXCLUDED.legacy_status_raw,
            lifecycle_state = EXCLUDED.lifecycle_state,
            authority_level = EXCLUDED.authority_level,
            version = EXCLUDED.version,
            revision = EXCLUDED.revision,
            source_refs = EXCLUDED.source_refs,
            content_hash = EXCLUDED.content_hash,
            metadata = EXCLUDED.metadata,
            updated_at = now(),
            deleted_at = NULL
        """

    def _archive_stale_character_memory_cards_sql(self) -> str:
        return self._archive_stale_cards_sql(
            source_type="CHARACTER_MEMORY_NODE",
            source_table="character_memory_nodes",
            business_id_column="character_memory_node_id",
            superseded_column="superseded_by_id",
        )

    def _archive_stale_location_state_cards_sql(self) -> str:
        return self._archive_stale_cards_sql(
            source_type="LOCATION_STATE_NODE",
            source_table="location_state_nodes",
            business_id_column="location_state_node_id",
            superseded_column="superseded_by_id",
        )

    def _archive_stale_location_change_delta_cards_sql(self) -> str:
        return self._archive_stale_cards_sql(
            source_type="LOCATION_CHANGE_DELTA",
            source_table="location_change_deltas",
            business_id_column="location_change_delta_id",
            superseded_column="superseded_by_id",
        )

    def _archive_stale_cards_sql(
        self,
        *,
        source_type: str,
        source_table: str,
        business_id_column: str,
        superseded_column: str,
    ) -> str:
        return f"""
        UPDATE {self.schema_name}.search_memory_cards card
        SET status = 'SUPERSEDED',
            lifecycle_state = 'ARCHIVED',
            metadata = card.metadata || jsonb_build_object('m11_index_archived_stale_source', true),
            updated_at = now(),
            deleted_at = COALESCE(card.deleted_at, now())
        WHERE card.project_id = %s
          AND card.source_type = '{source_type}'
          AND NOT EXISTS (
            SELECT 1
            FROM {self.schema_name}.{source_table} src
            WHERE src.project_id = card.project_id
              AND src.{business_id_column} = card.source_id
              AND {self._active_source_filter("src", superseded_column)}
          )
        """

    def _active_source_filter(self, alias: str, superseded_column: str = "") -> str:
        superseded_filter = f" AND {alias}.{superseded_column} IS NULL" if superseded_column else ""
        excluded = ", ".join(f"'{status}'" for status in ACTIVE_SOURCE_STATUS_EXCLUSIONS)
        return (
            f"{alias}.deleted_at IS NULL"
            f" AND {alias}.status NOT IN ({excluded})"
            f" AND {alias}.lifecycle_state <> 'DELETED'"
            f"{superseded_filter}"
        )

    @staticmethod
    def _rowcount(cursor: Any) -> int:
        value = getattr(cursor, "rowcount", 0)
        return int(value if value is not None and value > 0 else 0)
