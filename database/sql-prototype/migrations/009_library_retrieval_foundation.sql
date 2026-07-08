-- Phase 8.75 M3 PostgreSQL schema prototype.
-- Domain: library-style retrieval catalog, packs, usage, gaps and freshness.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS retrieval_task_specs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  retrieval_task_id text NOT NULL,
  chapter_id uuid,
  scene_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  agent_role text NOT NULL DEFAULT '',
  task_type text NOT NULL DEFAULT '',
  query_text text NOT NULL DEFAULT '',
  filters_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  required_entity_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  max_items integer NOT NULL DEFAULT 50,
  token_budget integer NOT NULL DEFAULT 0,
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
  CONSTRAINT uq_retrieval_task_specs_business_id UNIQUE (project_id, retrieval_task_id),
  CONSTRAINT uq_retrieval_task_specs_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_retrieval_task_specs_limits CHECK (max_items >= 0 AND token_budget >= 0),
  CONSTRAINT fk_retrieval_task_specs_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id),
  CONSTRAINT fk_retrieval_task_specs_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_retrieval_task_specs_scope
  ON retrieval_task_specs (project_id, agent_role, task_type, status, lifecycle_state);

CREATE TABLE IF NOT EXISTS search_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  search_document_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  entity_type text NOT NULL,
  entity_business_id text NOT NULL DEFAULT '',
  entity_physical_id uuid,
  title text NOT NULL DEFAULT '',
  summary text NOT NULL DEFAULT '',
  search_text text NOT NULL DEFAULT '',
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(summary, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(search_text, '')), 'C')
  ) STORED,
  importance numeric(7, 3) NOT NULL DEFAULT 0,
  indexed_at timestamptz NOT NULL DEFAULT now(),
  indexed_content_hash text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_search_documents_business_id UNIQUE (project_id, search_document_id),
  CONSTRAINT uq_search_documents_entity UNIQUE (project_id, entity_type, entity_business_id),
  CONSTRAINT uq_search_documents_id_project UNIQUE (id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_search_documents_entity_status
  ON search_documents (project_id, entity_type, status, lifecycle_state, authority_level);

CREATE INDEX IF NOT EXISTS ix_search_documents_search_vector
  ON search_documents USING gin (search_vector);

CREATE TABLE IF NOT EXISTS entity_aliases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  entity_alias_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  entity_type text NOT NULL,
  entity_business_id text NOT NULL DEFAULT '',
  alias_text text NOT NULL,
  alias_type text NOT NULL DEFAULT '',
  locale text NOT NULL DEFAULT '',
  confidence numeric(5, 3) NOT NULL DEFAULT 1,
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
  CONSTRAINT uq_entity_aliases_business_id UNIQUE (project_id, entity_alias_id),
  CONSTRAINT uq_entity_aliases_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_entity_aliases_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX IF NOT EXISTS ix_entity_aliases_lookup
  ON entity_aliases (project_id, alias_text, entity_type, status);

CREATE TABLE IF NOT EXISTS entity_keywords (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  entity_keyword_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  entity_type text NOT NULL,
  entity_business_id text NOT NULL DEFAULT '',
  keyword text NOT NULL,
  keyword_type text NOT NULL DEFAULT '',
  weight numeric(7, 3) NOT NULL DEFAULT 1,
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
  CONSTRAINT uq_entity_keywords_business_id UNIQUE (project_id, entity_keyword_id),
  CONSTRAINT uq_entity_keywords_id_project UNIQUE (id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_entity_keywords_lookup
  ON entity_keywords (project_id, keyword, entity_type, status);

CREATE TABLE IF NOT EXISTS entity_tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  entity_tag_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  entity_type text NOT NULL,
  entity_business_id text NOT NULL DEFAULT '',
  tag text NOT NULL,
  tag_type text NOT NULL DEFAULT '',
  confidence numeric(5, 3) NOT NULL DEFAULT 1,
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
  CONSTRAINT uq_entity_tags_business_id UNIQUE (project_id, entity_tag_id),
  CONSTRAINT uq_entity_tags_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_entity_tags_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX IF NOT EXISTS ix_entity_tags_lookup
  ON entity_tags (project_id, tag_type, tag, status);

CREATE TABLE IF NOT EXISTS entity_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  entity_link_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  source_entity_type text NOT NULL,
  source_business_id text NOT NULL DEFAULT '',
  target_entity_type text NOT NULL,
  target_business_id text NOT NULL DEFAULT '',
  link_type text NOT NULL DEFAULT '',
  directionality text NOT NULL DEFAULT 'DIRECTED',
  weight numeric(7, 3) NOT NULL DEFAULT 1,
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
  CONSTRAINT uq_entity_links_business_id UNIQUE (project_id, entity_link_id),
  CONSTRAINT uq_entity_links_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_entity_links_directionality CHECK (directionality IN ('DIRECTED', 'BIDIRECTIONAL'))
);

CREATE INDEX IF NOT EXISTS ix_entity_links_source
  ON entity_links (project_id, source_entity_type, source_business_id, link_type, status);

CREATE INDEX IF NOT EXISTS ix_entity_links_target
  ON entity_links (project_id, target_entity_type, target_business_id, link_type, status);

CREATE TABLE IF NOT EXISTS memory_entity_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  memory_entity_link_id text NOT NULL,
  memory_id uuid NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  entity_type text NOT NULL,
  entity_business_id text NOT NULL DEFAULT '',
  link_role text NOT NULL DEFAULT '',
  weight numeric(7, 3) NOT NULL DEFAULT 1,
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
  CONSTRAINT uq_memory_entity_links_business_id UNIQUE (project_id, memory_entity_link_id),
  CONSTRAINT uq_memory_entity_links_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_memory_entity_links_memory_project
    FOREIGN KEY (memory_id, project_id) REFERENCES memory_records(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_memory_entity_links_entity
  ON memory_entity_links (project_id, entity_type, entity_business_id, status);

CREATE TABLE IF NOT EXISTS memory_tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  memory_tag_id text NOT NULL,
  memory_id uuid NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  tag text NOT NULL,
  tag_type text NOT NULL DEFAULT '',
  confidence numeric(5, 3) NOT NULL DEFAULT 1,
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
  CONSTRAINT uq_memory_tags_business_id UNIQUE (project_id, memory_tag_id),
  CONSTRAINT uq_memory_tags_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_memory_tags_confidence CHECK (confidence >= 0 AND confidence <= 1),
  CONSTRAINT fk_memory_tags_memory_project
    FOREIGN KEY (memory_id, project_id) REFERENCES memory_records(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_memory_tags_lookup
  ON memory_tags (project_id, tag_type, tag, status);

CREATE TABLE IF NOT EXISTS chapter_memory_packs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  chapter_memory_pack_id text NOT NULL,
  chapter_id uuid NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  pack_purpose text NOT NULL DEFAULT '',
  max_items integer NOT NULL DEFAULT 250,
  token_budget integer NOT NULL DEFAULT 0,
  dependency_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  dependency_hash text NOT NULL DEFAULT '',
  freshness_status text NOT NULL DEFAULT 'FRESH',
  last_built_at timestamptz,
  invalidated_at timestamptz,
  invalidated_reason text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_chapter_memory_packs_business_id UNIQUE (project_id, chapter_memory_pack_id),
  CONSTRAINT uq_chapter_memory_packs_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_chapter_memory_packs_freshness CHECK (freshness_status IN ('FRESH', 'STALE', 'INVALIDATED', 'REBUILD_REQUIRED')),
  CONSTRAINT fk_chapter_memory_packs_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_chapter_memory_packs_freshness
  ON chapter_memory_packs (project_id, chapter_id, freshness_status, status);

CREATE TABLE IF NOT EXISTS scene_memory_packs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  scene_memory_pack_id text NOT NULL,
  chapter_pack_id uuid,
  scene_id uuid NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  pack_purpose text NOT NULL DEFAULT '',
  max_items integer NOT NULL DEFAULT 80,
  token_budget integer NOT NULL DEFAULT 0,
  dependency_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  dependency_hash text NOT NULL DEFAULT '',
  freshness_status text NOT NULL DEFAULT 'FRESH',
  last_built_at timestamptz,
  invalidated_at timestamptz,
  invalidated_reason text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_scene_memory_packs_business_id UNIQUE (project_id, scene_memory_pack_id),
  CONSTRAINT uq_scene_memory_packs_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_scene_memory_packs_freshness CHECK (freshness_status IN ('FRESH', 'STALE', 'INVALIDATED', 'REBUILD_REQUIRED')),
  CONSTRAINT fk_scene_memory_packs_chapter_pack_project
    FOREIGN KEY (chapter_pack_id, project_id) REFERENCES chapter_memory_packs(id, project_id),
  CONSTRAINT fk_scene_memory_packs_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_scene_memory_packs_freshness
  ON scene_memory_packs (project_id, scene_id, freshness_status, status);

CREATE TABLE IF NOT EXISTS agent_context_packs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  agent_context_pack_id text NOT NULL,
  scene_pack_id uuid,
  retrieval_task_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  agent_role text NOT NULL DEFAULT '',
  pack_purpose text NOT NULL DEFAULT '',
  max_items integer NOT NULL DEFAULT 60,
  token_budget integer NOT NULL DEFAULT 0,
  dependency_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  dependency_hash text NOT NULL DEFAULT '',
  freshness_status text NOT NULL DEFAULT 'FRESH',
  last_built_at timestamptz,
  invalidated_at timestamptz,
  invalidated_reason text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_agent_context_packs_business_id UNIQUE (project_id, agent_context_pack_id),
  CONSTRAINT uq_agent_context_packs_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_agent_context_packs_freshness CHECK (freshness_status IN ('FRESH', 'STALE', 'INVALIDATED', 'REBUILD_REQUIRED')),
  CONSTRAINT fk_agent_context_packs_scene_pack_project
    FOREIGN KEY (scene_pack_id, project_id) REFERENCES scene_memory_packs(id, project_id),
  CONSTRAINT fk_agent_context_packs_retrieval_task_project
    FOREIGN KEY (retrieval_task_id, project_id) REFERENCES retrieval_task_specs(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_agent_context_packs_freshness
  ON agent_context_packs (project_id, agent_role, freshness_status, status);

CREATE TABLE IF NOT EXISTS pack_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pack_item_id text NOT NULL,
  chapter_pack_id uuid,
  scene_pack_id uuid,
  agent_context_pack_id uuid,
  search_document_id uuid,
  memory_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  pack_type text NOT NULL,
  item_order integer NOT NULL DEFAULT 0,
  entity_type text NOT NULL DEFAULT '',
  entity_business_id text NOT NULL DEFAULT '',
  reason text NOT NULL DEFAULT '',
  rank_score numeric(9, 4) NOT NULL DEFAULT 0,
  token_estimate integer NOT NULL DEFAULT 0,
  required_for_generation boolean NOT NULL DEFAULT false,
  access_label text NOT NULL DEFAULT 'USABLE_NOW',
  source_status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  included_in_writer_context boolean NOT NULL DEFAULT true,
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
  CONSTRAINT uq_pack_items_business_id UNIQUE (project_id, pack_item_id),
  CONSTRAINT uq_pack_items_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_pack_items_one_pack_root CHECK (num_nonnulls(chapter_pack_id, scene_pack_id, agent_context_pack_id) = 1),
  CONSTRAINT ck_pack_items_access_label CHECK (access_label IN (
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
  CONSTRAINT ck_pack_items_writer_context_allowlist CHECK (included_in_writer_context = false OR access_label = 'USABLE_NOW'),
  CONSTRAINT fk_pack_items_chapter_pack_project
    FOREIGN KEY (chapter_pack_id, project_id) REFERENCES chapter_memory_packs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_pack_items_scene_pack_project
    FOREIGN KEY (scene_pack_id, project_id) REFERENCES scene_memory_packs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_pack_items_agent_context_pack_project
    FOREIGN KEY (agent_context_pack_id, project_id) REFERENCES agent_context_packs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_pack_items_search_document_project
    FOREIGN KEY (search_document_id, project_id) REFERENCES search_documents(id, project_id),
  CONSTRAINT fk_pack_items_memory_project
    FOREIGN KEY (memory_id, project_id) REFERENCES memory_records(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_pack_items_pack_scope
  ON pack_items (project_id, pack_type, item_order, access_label, included_in_writer_context);

CREATE TABLE IF NOT EXISTS memory_update_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  memory_update_plan_id text NOT NULL,
  retrieval_task_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  plan_type text NOT NULL DEFAULT '',
  affected_entity_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  planned_changes jsonb NOT NULL DEFAULT '[]'::jsonb,
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
  CONSTRAINT uq_memory_update_plans_business_id UNIQUE (project_id, memory_update_plan_id),
  CONSTRAINT uq_memory_update_plans_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_memory_update_plans_retrieval_task_project
    FOREIGN KEY (retrieval_task_id, project_id) REFERENCES retrieval_task_specs(id, project_id)
);

CREATE TABLE IF NOT EXISTS retrieval_usage_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  retrieval_usage_id text NOT NULL,
  retrieval_task_id uuid,
  chapter_pack_id uuid,
  scene_pack_id uuid,
  agent_context_pack_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  query_text text NOT NULL DEFAULT '',
  candidate_count integer NOT NULL DEFAULT 0,
  selected_count integer NOT NULL DEFAULT 0,
  used_entity_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  ignored_entity_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  missing_requirements jsonb NOT NULL DEFAULT '[]'::jsonb,
  latency_ms integer NOT NULL DEFAULT 0,
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
  CONSTRAINT uq_retrieval_usage_records_business_id UNIQUE (project_id, retrieval_usage_id),
  CONSTRAINT uq_retrieval_usage_records_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_retrieval_usage_records_retrieval_task_project
    FOREIGN KEY (retrieval_task_id, project_id) REFERENCES retrieval_task_specs(id, project_id),
  CONSTRAINT fk_retrieval_usage_records_chapter_pack_project
    FOREIGN KEY (chapter_pack_id, project_id) REFERENCES chapter_memory_packs(id, project_id),
  CONSTRAINT fk_retrieval_usage_records_scene_pack_project
    FOREIGN KEY (scene_pack_id, project_id) REFERENCES scene_memory_packs(id, project_id),
  CONSTRAINT fk_retrieval_usage_records_agent_context_pack_project
    FOREIGN KEY (agent_context_pack_id, project_id) REFERENCES agent_context_packs(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_retrieval_usage_records_task_status
  ON retrieval_usage_records (project_id, retrieval_task_id, status, created_at);

CREATE TABLE IF NOT EXISTS retrieval_gap_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  retrieval_gap_id text NOT NULL,
  retrieval_task_id uuid,
  scene_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m3',
  gap_type text NOT NULL DEFAULT '',
  claim_text text NOT NULL DEFAULT '',
  searched_scopes jsonb NOT NULL DEFAULT '[]'::jsonb,
  recommended_resolution text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'ANALYZER_REFERENCE',
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
  CONSTRAINT uq_retrieval_gap_records_business_id UNIQUE (project_id, retrieval_gap_id),
  CONSTRAINT uq_retrieval_gap_records_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_retrieval_gap_records_retrieval_task_project
    FOREIGN KEY (retrieval_task_id, project_id) REFERENCES retrieval_task_specs(id, project_id),
  CONSTRAINT fk_retrieval_gap_records_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_retrieval_gap_records_status
  ON retrieval_gap_records (project_id, gap_type, status, lifecycle_state);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('009_library_retrieval_foundation', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
