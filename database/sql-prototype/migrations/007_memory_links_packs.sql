-- Phase 8.75 M2B PostgreSQL schema prototype.
-- Domain: memory links and memory packs.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_chapters_id_project'
      AND conrelid = 'chapters'::regclass
  ) THEN
    ALTER TABLE chapters
      ADD CONSTRAINT uq_chapters_id_project UNIQUE (id, project_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_scenes_id_project'
      AND conrelid = 'scenes'::regclass
  ) THEN
    ALTER TABLE scenes
      ADD CONSTRAINT uq_scenes_id_project UNIQUE (id, project_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_memory_records_id_project'
      AND conrelid = 'memory_records'::regclass
  ) THEN
    ALTER TABLE memory_records
      ADD CONSTRAINT uq_memory_records_id_project UNIQUE (id, project_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS memory_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  memory_link_id text NOT NULL,
  memory_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  linked_entity_type text NOT NULL DEFAULT '',
  linked_business_id text NOT NULL DEFAULT '',
  link_role text NOT NULL DEFAULT '',
  link_strength numeric(6,3) NOT NULL DEFAULT 1,
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
  CONSTRAINT uq_memory_links_business_id UNIQUE (project_id, memory_link_id),
  CONSTRAINT uq_memory_links_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_memory_links_memory_project
    FOREIGN KEY (memory_id, project_id) REFERENCES memory_records(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_memory_links_entity
  ON memory_links (project_id, linked_entity_type, linked_business_id, status);

CREATE TABLE IF NOT EXISTS memory_packs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  memory_pack_id text NOT NULL,
  chapter_id uuid,
  scene_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  pack_type text NOT NULL DEFAULT '',
  pack_scope text NOT NULL DEFAULT '',
  freshness_status text NOT NULL DEFAULT 'FRESH',
  built_from_hash text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_memory_packs_business_id UNIQUE (project_id, memory_pack_id),
  CONSTRAINT uq_memory_packs_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_memory_packs_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id),
  CONSTRAINT fk_memory_packs_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_memory_packs_scope
  ON memory_packs (project_id, pack_type, chapter_id, scene_id, status);

CREATE TABLE IF NOT EXISTS memory_pack_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  memory_pack_item_id text NOT NULL,
  memory_pack_id uuid,
  memory_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  item_order integer NOT NULL DEFAULT 0,
  item_role text NOT NULL DEFAULT '',
  inclusion_reason text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_memory_pack_items_business_id UNIQUE (project_id, memory_pack_item_id),
  CONSTRAINT uq_memory_pack_items_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_memory_pack_items_pack_project
    FOREIGN KEY (memory_pack_id, project_id) REFERENCES memory_packs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_memory_pack_items_memory_project
    FOREIGN KEY (memory_id, project_id) REFERENCES memory_records(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_memory_pack_items_pack_order
  ON memory_pack_items (project_id, memory_pack_id, item_order);

CREATE TABLE IF NOT EXISTS memory_pack_dependencies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  memory_pack_dependency_id text NOT NULL,
  memory_pack_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  dependency_entity_type text NOT NULL DEFAULT '',
  dependency_business_id text NOT NULL DEFAULT '',
  dependency_reason text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_memory_pack_dependencies_business_id UNIQUE (project_id, memory_pack_dependency_id),
  CONSTRAINT uq_memory_pack_dependencies_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_memory_pack_dependencies_pack_project
    FOREIGN KEY (memory_pack_id, project_id) REFERENCES memory_packs(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_memory_pack_dependencies_entity
  ON memory_pack_dependencies (project_id, dependency_entity_type, dependency_business_id, status);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('007_memory_links_packs', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
