-- Phase 8.75 M2A PostgreSQL schema prototype.
-- Domain: memory record destination only.
-- M3 owns search documents, entity links, tags, packs, freshness, and temporal query tables.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS memory_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  memory_id text NOT NULL,
  scene_id uuid,
  chapter_id uuid,
  event_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  memory_lane text NOT NULL DEFAULT 'OBJECTIVE',
  memory_type text NOT NULL DEFAULT '',
  subject_entity_type text NOT NULL DEFAULT '',
  subject_business_id text NOT NULL DEFAULT '',
  memory_text text NOT NULL DEFAULT '',
  visibility_scope text NOT NULL DEFAULT '',
  valid_from_chapter_id text NOT NULL DEFAULT '',
  valid_from_scene_id text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_memory_records_business_id UNIQUE (project_id, memory_id),
  CONSTRAINT uq_memory_records_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_memory_records_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_memory_records_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id),
  CONSTRAINT fk_memory_records_event_project
    FOREIGN KEY (event_id, project_id) REFERENCES events(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_memory_records_scope
  ON memory_records (project_id, memory_lane, subject_entity_type, subject_business_id);

CREATE INDEX IF NOT EXISTS ix_memory_records_scene_status
  ON memory_records (project_id, scene_id, status, lifecycle_state);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('006_memory_foundation', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
