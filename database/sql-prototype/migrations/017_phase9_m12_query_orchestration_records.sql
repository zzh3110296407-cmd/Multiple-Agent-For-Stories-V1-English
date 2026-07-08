-- Phase 9 M12 Task 2: query intent, library query result and orchestration traceability records.
-- This migration is a static SQL prototype slice. It does not change runtime generation behavior.

\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto, public;

CREATE TABLE IF NOT EXISTS query_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  query_intent_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase9_m12_task2',
  query_mode text NOT NULL,
  agent_role text NOT NULL DEFAULT '',
  chapter_id text NOT NULL DEFAULT '',
  scene_id text NOT NULL DEFAULT '',
  narrative_time_ref text NOT NULL DEFAULT '',
  world_time_ref text NOT NULL DEFAULT '',
  knowledge_time_ref text NOT NULL DEFAULT '',
  timeline_id text NOT NULL DEFAULT '',
  characters jsonb NOT NULL DEFAULT '[]'::jsonb,
  locations jsonb NOT NULL DEFAULT '[]'::jsonb,
  scene_function jsonb NOT NULL DEFAULT '[]'::jsonb,
  required_entity_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  retrieval_task_business_id text NOT NULL DEFAULT '',
  max_items integer NOT NULL DEFAULT 20,
  token_budget integer NOT NULL DEFAULT 1200,
  debug_or_expert_mode boolean NOT NULL DEFAULT false,
  query_intent_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  gap_summary jsonb NOT NULL DEFAULT '[]'::jsonb,
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
  CONSTRAINT uq_query_intents_business_id UNIQUE (project_id, query_intent_id),
  CONSTRAINT uq_query_intents_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_query_intents_query_mode CHECK (query_mode IN (
    'SCENE_GENERATION',
    'SIMILARITY_EXPLORATION',
    'CONTINUITY_QUALITY_CHECK',
    'CHAPTER_PLANNING',
    'AGENT_CONTEXT_BUILD'
  )),
  CONSTRAINT ck_query_intents_scene_generation_tn_tw CHECK (
    query_mode <> 'SCENE_GENERATION'
    OR (narrative_time_ref <> '' AND world_time_ref <> '')
  ),
  CONSTRAINT ck_query_intents_bounds CHECK (max_items BETWEEN 1 AND 100 AND token_budget BETWEEN 1 AND 20000)
);

CREATE INDEX IF NOT EXISTS ix_query_intents_scope
  ON query_intents (project_id, query_mode, chapter_id, scene_id, status)
  WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS library_query_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  library_query_result_id text NOT NULL,
  query_intent_id uuid,
  retrieval_task_id uuid,
  schema_version text NOT NULL DEFAULT 'phase9_m12_task2',
  retrieval_modes jsonb NOT NULL DEFAULT '[]'::jsonb,
  candidate_count integer NOT NULL DEFAULT 0,
  selected_count integer NOT NULL DEFAULT 0,
  filtered_count integer NOT NULL DEFAULT 0,
  excluded_count integer NOT NULL DEFAULT 0,
  latency_ms integer NOT NULL DEFAULT 0,
  token_estimate integer NOT NULL DEFAULT 0,
  candidate_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  selected_candidate_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  filtered_candidate_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  excluded_candidate_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  explanation_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  writer_agent_fact_ready boolean NOT NULL DEFAULT false,
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
  CONSTRAINT uq_library_query_results_business_id UNIQUE (project_id, library_query_result_id),
  CONSTRAINT uq_library_query_results_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_library_query_results_counts CHECK (
    candidate_count >= 0
    AND selected_count >= 0
    AND filtered_count >= 0
    AND excluded_count >= 0
    AND selected_count + filtered_count + excluded_count <= candidate_count
  ),
  CONSTRAINT ck_library_query_results_no_writer_fact_claim CHECK (writer_agent_fact_ready = false),
  CONSTRAINT fk_library_query_results_query_intent_project
    FOREIGN KEY (query_intent_id, project_id) REFERENCES query_intents(id, project_id),
  CONSTRAINT fk_library_query_results_retrieval_task_project
    FOREIGN KEY (retrieval_task_id, project_id) REFERENCES retrieval_task_specs(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_library_query_results_scope
  ON library_query_results (project_id, query_intent_id, retrieval_task_id, status)
  WHERE deleted_at IS NULL;

ALTER TABLE query_orchestration_runs
  ADD COLUMN IF NOT EXISTS query_intent_id uuid,
  ADD COLUMN IF NOT EXISTS library_query_result_id uuid,
  ADD COLUMN IF NOT EXISTS selected_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS filtered_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS excluded_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS trace_summary jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS runtime_scene_generation_consumed boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS writer_agent_fact_ready boolean NOT NULL DEFAULT false;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_query_orchestration_runs_trace_counts'
  ) THEN
    ALTER TABLE query_orchestration_runs
      ADD CONSTRAINT ck_query_orchestration_runs_trace_counts CHECK (
        selected_count >= 0
        AND filtered_count >= 0
        AND excluded_count >= 0
        AND writer_agent_fact_ready = false
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_query_orchestration_runs_query_intent_project'
  ) THEN
    ALTER TABLE query_orchestration_runs
      ADD CONSTRAINT fk_query_orchestration_runs_query_intent_project
      FOREIGN KEY (query_intent_id, project_id) REFERENCES query_intents(id, project_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_query_orchestration_runs_library_query_result_project'
  ) THEN
    ALTER TABLE query_orchestration_runs
      ADD CONSTRAINT fk_query_orchestration_runs_library_query_result_project
      FOREIGN KEY (library_query_result_id, project_id) REFERENCES library_query_results(id, project_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_query_orchestration_runs_traceability
  ON query_orchestration_runs (project_id, query_intent_id, library_query_result_id, status)
  WHERE deleted_at IS NULL;

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('017_phase9_m12_query_orchestration_records', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
