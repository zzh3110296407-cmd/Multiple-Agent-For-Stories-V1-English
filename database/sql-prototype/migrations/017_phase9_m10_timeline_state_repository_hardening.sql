-- Phase 9 M10 PostgreSQL schema prototype.
-- Domain: timeline/state node repository hardening.
-- Scope: Database session prototype only. This file does not implement Temporal Resolver read APIs.

\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

ALTER TABLE timelines
  ADD COLUMN IF NOT EXISTS calendar_system_ref text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS created_from_source_ref jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE character_memory_nodes
  ADD COLUMN IF NOT EXISTS superseded_by_id uuid;

ALTER TABLE location_state_nodes
  ADD COLUMN IF NOT EXISTS superseded_by_id uuid,
  ADD COLUMN IF NOT EXISTS visibility_status text NOT NULL DEFAULT 'KNOWN';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_character_memory_nodes_superseded_by_project'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE character_memory_nodes
      ADD CONSTRAINT fk_character_memory_nodes_superseded_by_project
      FOREIGN KEY (superseded_by_id, project_id) REFERENCES character_memory_nodes(id, project_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_location_state_nodes_visibility'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE location_state_nodes
      ADD CONSTRAINT ck_location_state_nodes_visibility CHECK (visibility_status IN (
        'KNOWN',
        'MASKED',
        'FORGOTTEN',
        'RESTORED',
        'HIDDEN_FROM_READER'
      ));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_location_state_nodes_superseded_by_project'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE location_state_nodes
      ADD CONSTRAINT fk_location_state_nodes_superseded_by_project
      FOREIGN KEY (superseded_by_id, project_id) REFERENCES location_state_nodes(id, project_id);
  END IF;
END $$;

ALTER TABLE location_change_deltas
  ADD COLUMN IF NOT EXISTS superseded_by_id uuid,
  ADD COLUMN IF NOT EXISTS visibility_status text NOT NULL DEFAULT 'KNOWN';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_location_change_deltas_visibility'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE location_change_deltas
      ADD CONSTRAINT ck_location_change_deltas_visibility CHECK (visibility_status IN (
        'KNOWN',
        'MASKED',
        'FORGOTTEN',
        'RESTORED',
        'HIDDEN_FROM_READER'
      ));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_location_change_deltas_superseded_by_project'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE location_change_deltas
      ADD CONSTRAINT fk_location_change_deltas_superseded_by_project
      FOREIGN KEY (superseded_by_id, project_id) REFERENCES location_change_deltas(id, project_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_character_memory_nodes_active
  ON character_memory_nodes (project_id, character_id, timeline_id, known_at_sort_key, valid_from_sort_key)
  WHERE superseded_by_id IS NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_location_state_nodes_active
  ON location_state_nodes (project_id, location_id, timeline_id, time_anchor_sort_key, valid_from_sort_key)
  WHERE superseded_by_id IS NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_location_change_deltas_active
  ON location_change_deltas (project_id, location_id, status)
  WHERE superseded_by_id IS NULL AND deleted_at IS NULL;

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('017_phase9_m10_timeline_state_repository_hardening', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
