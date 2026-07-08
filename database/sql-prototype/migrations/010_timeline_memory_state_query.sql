-- Phase 8.75 M3 PostgreSQL schema prototype.
-- Domain: timeline / memory-state query, access labels and context pack output.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS timelines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  timeline_id text NOT NULL,
  parent_timeline_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  timeline_type text NOT NULL DEFAULT 'MAIN',
  branch_point_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  timeline_summary text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_timelines_business_id UNIQUE (project_id, timeline_id),
  CONSTRAINT uq_timelines_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_timelines_type CHECK (timeline_type IN ('MAIN', 'FLASHBACK', 'PREDICTION', 'PARALLEL', 'DREAM', 'SIMULATION')),
  CONSTRAINT fk_timelines_parent_timeline_project
    FOREIGN KEY (parent_timeline_id, project_id) REFERENCES timelines(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_timelines_type_status
  ON timelines (project_id, timeline_type, status, lifecycle_state);

CREATE TABLE IF NOT EXISTS character_memory_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  character_memory_node_id text NOT NULL,
  character_id uuid NOT NULL,
  timeline_id uuid NOT NULL,
  source_scene_id uuid,
  source_event_id uuid,
  previous_node_id uuid,
  superseded_by_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  experienced_at text NOT NULL DEFAULT '',
  experienced_at_sort_key bigint NOT NULL DEFAULT 0,
  known_at text NOT NULL DEFAULT '',
  known_at_sort_key bigint NOT NULL DEFAULT 0,
  narrative_recorded_at text NOT NULL DEFAULT '',
  narrative_recorded_at_sort_key bigint NOT NULL DEFAULT 0,
  valid_from text NOT NULL DEFAULT '',
  valid_from_sort_key bigint NOT NULL DEFAULT 0,
  valid_to text NOT NULL DEFAULT '',
  valid_to_sort_key bigint,
  memory_type text NOT NULL DEFAULT 'OBJECTIVE_SEEN',
  visibility_status text NOT NULL DEFAULT 'KNOWN',
  content text NOT NULL DEFAULT '',
  summary text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_character_memory_nodes_business_id UNIQUE (project_id, character_memory_node_id),
  CONSTRAINT uq_character_memory_nodes_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_character_memory_nodes_visibility CHECK (visibility_status IN ('KNOWN', 'MASKED', 'FORGOTTEN', 'RESTORED', 'HIDDEN_FROM_READER')),
  CONSTRAINT fk_character_memory_nodes_character_project
    FOREIGN KEY (character_id, project_id) REFERENCES characters(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_character_memory_nodes_timeline_project
    FOREIGN KEY (timeline_id, project_id) REFERENCES timelines(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_character_memory_nodes_source_scene_project
    FOREIGN KEY (source_scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_character_memory_nodes_source_event_project
    FOREIGN KEY (source_event_id, project_id) REFERENCES events(id, project_id),
  CONSTRAINT fk_character_memory_nodes_previous_node_project
    FOREIGN KEY (previous_node_id, project_id) REFERENCES character_memory_nodes(id, project_id),
  CONSTRAINT fk_character_memory_nodes_superseded_by_project
    FOREIGN KEY (superseded_by_id, project_id) REFERENCES character_memory_nodes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_character_memory_nodes_timeline_query
  ON character_memory_nodes (project_id, character_id, timeline_id, known_at_sort_key, valid_from_sort_key, valid_to_sort_key, visibility_status, authority_level);

CREATE TABLE IF NOT EXISTS location_state_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  location_state_node_id text NOT NULL,
  location_id uuid NOT NULL,
  timeline_id uuid NOT NULL,
  previous_node_id uuid,
  next_node_id uuid,
  change_from_previous_id uuid,
  superseded_by_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  time_anchor text NOT NULL DEFAULT '',
  time_anchor_sort_key bigint NOT NULL DEFAULT 0,
  valid_from text NOT NULL DEFAULT '',
  valid_from_sort_key bigint NOT NULL DEFAULT 0,
  valid_to text NOT NULL DEFAULT '',
  valid_to_sort_key bigint,
  state_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  known_by_character_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  revealed_to_reader_at text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_location_state_nodes_business_id UNIQUE (project_id, location_state_node_id),
  CONSTRAINT uq_location_state_nodes_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_location_state_nodes_location_project
    FOREIGN KEY (location_id, project_id) REFERENCES world_locations(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_location_state_nodes_timeline_project
    FOREIGN KEY (timeline_id, project_id) REFERENCES timelines(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_location_state_nodes_previous_node_project
    FOREIGN KEY (previous_node_id, project_id) REFERENCES location_state_nodes(id, project_id),
  CONSTRAINT fk_location_state_nodes_next_node_project
    FOREIGN KEY (next_node_id, project_id) REFERENCES location_state_nodes(id, project_id),
  CONSTRAINT fk_location_state_nodes_superseded_by_project
    FOREIGN KEY (superseded_by_id, project_id) REFERENCES location_state_nodes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_location_state_nodes_timeline_query
  ON location_state_nodes (project_id, location_id, timeline_id, time_anchor_sort_key, valid_from_sort_key, valid_to_sort_key, authority_level, superseded_by_id);

CREATE TABLE IF NOT EXISTS location_change_deltas (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  location_change_delta_id text NOT NULL,
  location_id uuid NOT NULL,
  from_node_id uuid,
  to_node_id uuid,
  source_event_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  change_summary text NOT NULL DEFAULT '',
  change_detail text NOT NULL DEFAULT '',
  caused_by_event_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  participant_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  known_by_character_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  revealed_to_reader_at text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_location_change_deltas_business_id UNIQUE (project_id, location_change_delta_id),
  CONSTRAINT uq_location_change_deltas_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_location_change_deltas_location_project
    FOREIGN KEY (location_id, project_id) REFERENCES world_locations(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_location_change_deltas_from_node_project
    FOREIGN KEY (from_node_id, project_id) REFERENCES location_state_nodes(id, project_id),
  CONSTRAINT fk_location_change_deltas_to_node_project
    FOREIGN KEY (to_node_id, project_id) REFERENCES location_state_nodes(id, project_id),
  CONSTRAINT fk_location_change_deltas_source_event_project
    FOREIGN KEY (source_event_id, project_id) REFERENCES events(id, project_id)
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_location_state_nodes_change_from_previous_project'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE location_state_nodes
      ADD CONSTRAINT fk_location_state_nodes_change_from_previous_project
      FOREIGN KEY (change_from_previous_id, project_id) REFERENCES location_change_deltas(id, project_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS search_memory_cards (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  search_memory_card_id text NOT NULL,
  source_search_document_id uuid,
  timeline_id uuid,
  source_scene_id uuid,
  character_memory_node_id uuid,
  location_state_node_id uuid,
  location_change_delta_id uuid,
  superseded_by_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  source_type text NOT NULL DEFAULT '',
  text_summary text NOT NULL DEFAULT '',
  keywords jsonb NOT NULL DEFAULT '[]'::jsonb,
  embedding_ref text NOT NULL DEFAULT '',
  entity_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  character_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  location_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  world_time_range jsonb NOT NULL DEFAULT '{}'::jsonb,
  narrative_range jsonb NOT NULL DEFAULT '{}'::jsonb,
  known_by_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  revealed_to_reader_at text NOT NULL DEFAULT '',
  visibility_status text NOT NULL DEFAULT 'KNOWN',
  memory_lane text NOT NULL DEFAULT '',
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(text_summary, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(source_type, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(memory_lane, '')), 'C')
  ) STORED,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_search_memory_cards_business_id UNIQUE (project_id, search_memory_card_id),
  CONSTRAINT uq_search_memory_cards_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_search_memory_cards_visibility CHECK (visibility_status IN ('KNOWN', 'MASKED', 'FORGOTTEN', 'RESTORED', 'HIDDEN_FROM_READER')),
  CONSTRAINT fk_search_memory_cards_source_search_document_project
    FOREIGN KEY (source_search_document_id, project_id) REFERENCES search_documents(id, project_id),
  CONSTRAINT fk_search_memory_cards_timeline_project
    FOREIGN KEY (timeline_id, project_id) REFERENCES timelines(id, project_id),
  CONSTRAINT fk_search_memory_cards_source_scene_project
    FOREIGN KEY (source_scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_search_memory_cards_character_memory_node_project
    FOREIGN KEY (character_memory_node_id, project_id) REFERENCES character_memory_nodes(id, project_id),
  CONSTRAINT fk_search_memory_cards_location_state_node_project
    FOREIGN KEY (location_state_node_id, project_id) REFERENCES location_state_nodes(id, project_id),
  CONSTRAINT fk_search_memory_cards_location_change_delta_project
    FOREIGN KEY (location_change_delta_id, project_id) REFERENCES location_change_deltas(id, project_id),
  CONSTRAINT fk_search_memory_cards_superseded_by_project
    FOREIGN KEY (superseded_by_id, project_id) REFERENCES search_memory_cards(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_search_memory_cards_search_vector
  ON search_memory_cards USING gin (search_vector);

CREATE INDEX IF NOT EXISTS ix_search_memory_cards_time_visibility
  ON search_memory_cards (project_id, timeline_id, visibility_status, authority_level, status);

CREATE TABLE IF NOT EXISTS temporal_query_specs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  temporal_query_id text NOT NULL,
  timeline_id uuid,
  scene_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  query_type text NOT NULL DEFAULT '',
  world_time text NOT NULL DEFAULT '',
  world_time_sort_key bigint NOT NULL DEFAULT 0,
  narrative_ref text NOT NULL DEFAULT '',
  narrative_sequence_key bigint NOT NULL DEFAULT 0,
  knowledge_time text NOT NULL DEFAULT '',
  knowledge_time_sort_key bigint NOT NULL DEFAULT 0,
  character_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  location_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  allow_wrong_timeline boolean NOT NULL DEFAULT false,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_temporal_query_specs_business_id UNIQUE (project_id, temporal_query_id),
  CONSTRAINT uq_temporal_query_specs_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_temporal_query_specs_timeline_project
    FOREIGN KEY (timeline_id, project_id) REFERENCES timelines(id, project_id),
  CONSTRAINT fk_temporal_query_specs_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_temporal_query_specs_scope
  ON temporal_query_specs (project_id, query_type, timeline_id, world_time_sort_key, knowledge_time_sort_key, narrative_sequence_key);

CREATE TABLE IF NOT EXISTS temporal_query_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  temporal_query_result_id text NOT NULL,
  temporal_query_id uuid NOT NULL,
  search_memory_card_id uuid,
  character_memory_node_id uuid,
  location_state_node_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  source_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  access_label text NOT NULL DEFAULT 'USABLE_NOW',
  validity_reason text NOT NULL DEFAULT '',
  usable_for_writer boolean NOT NULL DEFAULT false,
  temporal_fit numeric(7, 4) NOT NULL DEFAULT 0,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_temporal_query_results_business_id UNIQUE (project_id, temporal_query_result_id),
  CONSTRAINT uq_temporal_query_results_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_temporal_query_results_access_label CHECK (access_label IN (
    'USABLE_NOW',
    'AUTHOR_ONLY',
    'CHARACTER_UNKNOWN',
    'READER_FORBIDDEN',
    'FUTURE_INFO',
    'CANDIDATE_ONLY',
    'SUPERSEDED',
    'CONFLICT_RISK',
    'WRONG_TIMELINE'
  )),
  CONSTRAINT ck_temporal_query_results_writer_allowlist CHECK (usable_for_writer = false OR access_label = 'USABLE_NOW'),
  CONSTRAINT fk_temporal_query_results_temporal_query_project
    FOREIGN KEY (temporal_query_id, project_id) REFERENCES temporal_query_specs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_temporal_query_results_search_memory_card_project
    FOREIGN KEY (search_memory_card_id, project_id) REFERENCES search_memory_cards(id, project_id),
  CONSTRAINT fk_temporal_query_results_character_memory_node_project
    FOREIGN KEY (character_memory_node_id, project_id) REFERENCES character_memory_nodes(id, project_id),
  CONSTRAINT fk_temporal_query_results_location_state_node_project
    FOREIGN KEY (location_state_node_id, project_id) REFERENCES location_state_nodes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_temporal_query_results_access
  ON temporal_query_results (project_id, temporal_query_id, access_label, usable_for_writer);

CREATE TABLE IF NOT EXISTS query_orchestration_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  query_orchestration_run_id text NOT NULL,
  temporal_query_id uuid,
  retrieval_task_id uuid,
  agent_context_pack_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  query_mode text NOT NULL DEFAULT '',
  library_query_id text NOT NULL DEFAULT '',
  context_pack_id text NOT NULL DEFAULT '',
  started_at timestamptz,
  completed_at timestamptz,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_query_orchestration_runs_business_id UNIQUE (project_id, query_orchestration_run_id),
  CONSTRAINT uq_query_orchestration_runs_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_query_orchestration_runs_temporal_query_project
    FOREIGN KEY (temporal_query_id, project_id) REFERENCES temporal_query_specs(id, project_id),
  CONSTRAINT fk_query_orchestration_runs_retrieval_task_project
    FOREIGN KEY (retrieval_task_id, project_id) REFERENCES retrieval_task_specs(id, project_id),
  CONSTRAINT fk_query_orchestration_runs_agent_context_pack_project
    FOREIGN KEY (agent_context_pack_id, project_id) REFERENCES agent_context_packs(id, project_id)
);

CREATE TABLE IF NOT EXISTS candidate_fusion_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  candidate_fusion_result_id text NOT NULL,
  orchestration_run_id uuid NOT NULL,
  search_document_id uuid,
  search_memory_card_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  candidate_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  access_label text NOT NULL DEFAULT 'CANDIDATE_ONLY',
  temporal_fit numeric(7, 4) NOT NULL DEFAULT 0,
  entity_fit numeric(7, 4) NOT NULL DEFAULT 0,
  semantic_fit numeric(7, 4) NOT NULL DEFAULT 0,
  authority_score numeric(7, 4) NOT NULL DEFAULT 0,
  narrative_relevance numeric(7, 4) NOT NULL DEFAULT 0,
  final_score numeric(9, 4) NOT NULL DEFAULT 0,
  dedupe_key text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_candidate_fusion_results_business_id UNIQUE (project_id, candidate_fusion_result_id),
  CONSTRAINT uq_candidate_fusion_results_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_candidate_fusion_results_access_label CHECK (access_label IN (
    'USABLE_NOW',
    'AUTHOR_ONLY',
    'CHARACTER_UNKNOWN',
    'READER_FORBIDDEN',
    'FUTURE_INFO',
    'CANDIDATE_ONLY',
    'SUPERSEDED',
    'CONFLICT_RISK',
    'WRONG_TIMELINE'
  )),
  CONSTRAINT ck_candidate_fusion_results_dedupe_key_required CHECK (dedupe_key <> ''),
  CONSTRAINT fk_candidate_fusion_results_orchestration_run_project
    FOREIGN KEY (orchestration_run_id, project_id) REFERENCES query_orchestration_runs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_candidate_fusion_results_search_document_project
    FOREIGN KEY (search_document_id, project_id) REFERENCES search_documents(id, project_id),
  CONSTRAINT fk_candidate_fusion_results_search_memory_card_project
    FOREIGN KEY (search_memory_card_id, project_id) REFERENCES search_memory_cards(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_candidate_fusion_results_rank
  ON candidate_fusion_results (project_id, orchestration_run_id, access_label, final_score DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_fusion_results_run_dedupe
  ON candidate_fusion_results (project_id, orchestration_run_id, dedupe_key)
  WHERE dedupe_key <> '' AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS authority_visibility_gate_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  authority_visibility_gate_result_id text NOT NULL,
  candidate_fusion_id uuid NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  access_label text NOT NULL DEFAULT 'CANDIDATE_ONLY',
  usable_for_writer boolean NOT NULL DEFAULT false,
  forbidden_reason text NOT NULL DEFAULT '',
  authority_reason text NOT NULL DEFAULT '',
  visibility_reason text NOT NULL DEFAULT '',
  temporal_reason text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_authority_visibility_gate_results_business_id UNIQUE (project_id, authority_visibility_gate_result_id),
  CONSTRAINT uq_authority_visibility_gate_results_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_authority_visibility_gate_results_access_label CHECK (access_label IN (
    'USABLE_NOW',
    'AUTHOR_ONLY',
    'CHARACTER_UNKNOWN',
    'READER_FORBIDDEN',
    'FUTURE_INFO',
    'CANDIDATE_ONLY',
    'SUPERSEDED',
    'CONFLICT_RISK',
    'WRONG_TIMELINE'
  )),
  CONSTRAINT ck_authority_visibility_gate_results_writer_allowlist CHECK (usable_for_writer = false OR access_label = 'USABLE_NOW'),
  CONSTRAINT fk_authority_visibility_gate_results_candidate_fusion_project
    FOREIGN KEY (candidate_fusion_id, project_id) REFERENCES candidate_fusion_results(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_authority_visibility_gate_results_label
  ON authority_visibility_gate_results (project_id, access_label, usable_for_writer, status);

CREATE TABLE IF NOT EXISTS context_pack_builds (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  context_pack_build_id text NOT NULL,
  orchestration_run_id uuid NOT NULL,
  agent_context_pack_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  must_use_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  may_use_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  avoid_revealing_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  character_visible_memory_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  location_current_state_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  continuity_warning_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_ref_summary jsonb NOT NULL DEFAULT '[]'::jsonb,
  allowed_label_count integer NOT NULL DEFAULT 0,
  forbidden_label_count integer NOT NULL DEFAULT 0,
  token_estimate integer NOT NULL DEFAULT 0,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_context_pack_builds_business_id UNIQUE (project_id, context_pack_build_id),
  CONSTRAINT uq_context_pack_builds_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_context_pack_builds_orchestration_run_project
    FOREIGN KEY (orchestration_run_id, project_id) REFERENCES query_orchestration_runs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_context_pack_builds_agent_context_pack_project
    FOREIGN KEY (agent_context_pack_id, project_id) REFERENCES agent_context_packs(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_context_pack_builds_run_status
  ON context_pack_builds (project_id, orchestration_run_id, status, created_at);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('010_timeline_memory_state_query', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
