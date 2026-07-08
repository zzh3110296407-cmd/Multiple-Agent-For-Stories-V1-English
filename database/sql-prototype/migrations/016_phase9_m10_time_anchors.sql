-- Phase 9 M10 PostgreSQL schema prototype.
-- Domain: world and character time anchors.
-- Scope: Database session prototype only. This file does not implement Temporal Resolver read APIs.

\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS world_time_anchors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  anchor_id text NOT NULL,
  timeline_id uuid NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase9_m10',
  anchor_type text NOT NULL DEFAULT 'USER_DEFINED',
  world_time_value text NOT NULL DEFAULT '',
  world_time_sort_key bigint,
  world_time_label text NOT NULL DEFAULT '',
  narrative_position_ref text NOT NULL DEFAULT '',
  narrative_sequence_key bigint,
  precision text NOT NULL DEFAULT 'UNKNOWN',
  description text NOT NULL DEFAULT '',
  calendar_system_ref text NOT NULL DEFAULT '',
  time_granularity text NOT NULL DEFAULT 'UNKNOWN',
  time_zone_or_region_rule text NOT NULL DEFAULT '',
  time_uncertainty_policy text NOT NULL DEFAULT 'UNKNOWN_ALLOWED',
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
  CONSTRAINT uq_world_time_anchors_business_id UNIQUE (project_id, anchor_id),
  CONSTRAINT uq_world_time_anchors_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_world_time_anchors_anchor_type CHECK (anchor_type IN (
    'WORLD_CURRENT',
    'STORY_START',
    'CHAPTER_START',
    'SCENE_START',
    'USER_DEFINED'
  )),
  CONSTRAINT ck_world_time_anchors_precision CHECK (precision IN (
    'UNKNOWN',
    'APPROXIMATE',
    'EXACT',
    'RANGE',
    'RELATIVE',
    'CUSTOM_CALENDAR',
    'NONHUMAN_CUSTOM'
  )),
  CONSTRAINT ck_world_time_anchors_no_fake_exact CHECK (
    precision <> 'EXACT' OR (world_time_value <> '' AND world_time_sort_key IS NOT NULL)
  ),
  CONSTRAINT fk_world_time_anchors_timeline_project
    FOREIGN KEY (timeline_id, project_id) REFERENCES timelines(id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_world_time_anchors_lookup
  ON world_time_anchors (project_id, timeline_id, anchor_type, precision, world_time_sort_key);

ALTER TABLE world_canvases
  ADD COLUMN IF NOT EXISTS calendar_system text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS world_time_anchor_id uuid,
  ADD COLUMN IF NOT EXISTS story_start_world_time text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS story_start_world_time_anchor_id uuid,
  ADD COLUMN IF NOT EXISTS current_world_point_description text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS time_granularity text NOT NULL DEFAULT 'UNKNOWN',
  ADD COLUMN IF NOT EXISTS time_zone_or_region_rule text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS time_uncertainty_policy text NOT NULL DEFAULT 'UNKNOWN_ALLOWED';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_world_canvases_time_granularity'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE world_canvases
      ADD CONSTRAINT ck_world_canvases_time_granularity
      CHECK (time_granularity IN ('UNKNOWN', 'EXACT', 'APPROXIMATE', 'CUSTOM_CALENDAR', 'RELATIVE'));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_world_canvases_time_uncertainty_policy'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE world_canvases
      ADD CONSTRAINT ck_world_canvases_time_uncertainty_policy
      CHECK (time_uncertainty_policy IN ('UNKNOWN_ALLOWED', 'APPROXIMATE_ALLOWED', 'EXACT_REQUIRED', 'CUSTOM_CALENDAR_ALLOWED'));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_world_canvases_world_time_anchor_project'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE world_canvases
      ADD CONSTRAINT fk_world_canvases_world_time_anchor_project
      FOREIGN KEY (world_time_anchor_id, project_id) REFERENCES world_time_anchors(id, project_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_world_canvases_story_start_anchor_project'
      AND connamespace = current_schema()::regnamespace
  ) THEN
    ALTER TABLE world_canvases
      ADD CONSTRAINT fk_world_canvases_story_start_anchor_project
      FOREIGN KEY (story_start_world_time_anchor_id, project_id) REFERENCES world_time_anchors(id, project_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS character_life_anchors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  life_anchor_id text NOT NULL,
  character_id uuid NOT NULL,
  timeline_id uuid NOT NULL,
  birth_time_anchor_id uuid,
  age_anchor_time_id uuid,
  schema_version text NOT NULL DEFAULT 'phase9_m10',
  birth_time_anchor text NOT NULL DEFAULT '',
  birth_time_precision text NOT NULL DEFAULT 'UNKNOWN',
  age_at_story_start numeric(8, 2),
  age_anchor_time text NOT NULL DEFAULT '',
  age_anchor_sort_key bigint,
  apparent_age text NOT NULL DEFAULT '',
  lifespan_rule_ref text NOT NULL DEFAULT '',
  species_or_lifespan_rule_ref text NOT NULL DEFAULT '',
  uncertainty_policy text NOT NULL DEFAULT 'UNKNOWN_ALLOWED',
  age_uncertainty_policy text NOT NULL DEFAULT 'UNKNOWN_ALLOWED',
  age_derivation_ready boolean NOT NULL DEFAULT false,
  visibility_status text NOT NULL DEFAULT 'KNOWN',
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
  CONSTRAINT uq_character_life_anchors_business_id UNIQUE (project_id, life_anchor_id),
  CONSTRAINT uq_character_life_anchors_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_character_life_anchors_birth_precision CHECK (birth_time_precision IN (
    'UNKNOWN',
    'APPROXIMATE',
    'EXACT',
    'RANGE',
    'RELATIVE',
    'NONHUMAN_CUSTOM',
    'TIMELESS',
    'NOT_APPLICABLE'
  )),
  CONSTRAINT ck_character_life_anchors_age_uncertainty_policy CHECK (age_uncertainty_policy IN (
    'UNKNOWN_ALLOWED',
    'APPROXIMATE_ALLOWED',
    'EXACT_CONFIRMED',
    'NONHUMAN_CUSTOM',
    'TIMELESS',
    'NOT_APPLICABLE'
  )),
  CONSTRAINT ck_character_life_anchors_visibility CHECK (visibility_status IN (
    'KNOWN',
    'MASKED',
    'FORGOTTEN',
    'RESTORED',
    'HIDDEN_FROM_READER'
  )),
  CONSTRAINT ck_character_life_anchors_no_fake_exact_birth CHECK (
    birth_time_precision <> 'EXACT' OR (birth_time_anchor <> '' OR birth_time_anchor_id IS NOT NULL)
  ),
  CONSTRAINT ck_character_life_anchors_derivation_requires_anchor CHECK (
    age_derivation_ready = false OR (
      (birth_time_anchor <> '' OR birth_time_anchor_id IS NOT NULL OR age_at_story_start IS NOT NULL)
      AND (age_anchor_time <> '' OR age_anchor_time_id IS NOT NULL)
    )
  ),
  CONSTRAINT fk_character_life_anchors_character_project
    FOREIGN KEY (character_id, project_id) REFERENCES characters(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_character_life_anchors_timeline_project
    FOREIGN KEY (timeline_id, project_id) REFERENCES timelines(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_character_life_anchors_birth_anchor_project
    FOREIGN KEY (birth_time_anchor_id, project_id) REFERENCES world_time_anchors(id, project_id),
  CONSTRAINT fk_character_life_anchors_age_anchor_project
    FOREIGN KEY (age_anchor_time_id, project_id) REFERENCES world_time_anchors(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_character_life_anchors_character_timeline
  ON character_life_anchors (project_id, character_id, timeline_id, birth_time_precision, visibility_status);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('016_phase9_m10_time_anchors', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
