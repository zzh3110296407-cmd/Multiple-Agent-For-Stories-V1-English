-- Phase 8.75 M2A PostgreSQL schema prototype.
-- Domain: chapters, scenes, drafts, and Phase 9 editor preparation.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS chapters (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  chapter_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  chapter_number integer NOT NULL DEFAULT 0,
  title text NOT NULL DEFAULT '',
  chapter_summary text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_chapters_business_id UNIQUE (project_id, chapter_id),
  CONSTRAINT uq_chapters_id_project UNIQUE (id, project_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chapters_number_when_known
  ON chapters (project_id, chapter_number)
  WHERE chapter_number > 0;

CREATE TABLE IF NOT EXISTS chapter_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  chapter_plan_id text NOT NULL,
  chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  plan_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_chapter_plans_business_id UNIQUE (project_id, chapter_plan_id),
  CONSTRAINT fk_chapter_plans_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chapter_scene_beats (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  beat_id text NOT NULL,
  chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  beat_order integer NOT NULL DEFAULT 0,
  beat_text text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_chapter_scene_beats_business_id UNIQUE (project_id, beat_id),
  CONSTRAINT fk_chapter_scene_beats_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chapter_transitions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  transition_id text NOT NULL,
  from_chapter_id uuid,
  to_chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  transition_text text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_chapter_transitions_business_id UNIQUE (project_id, transition_id),
  CONSTRAINT fk_chapter_transitions_from_chapter_project
    FOREIGN KEY (from_chapter_id, project_id) REFERENCES chapters(id, project_id),
  CONSTRAINT fk_chapter_transitions_to_chapter_project
    FOREIGN KEY (to_chapter_id, project_id) REFERENCES chapters(id, project_id)
);

CREATE TABLE IF NOT EXISTS chapter_archives (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  archive_id text NOT NULL,
  chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  archive_reason text NOT NULL DEFAULT '',
  archive_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'ARCHIVED',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ARCHIVED',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_chapter_archives_business_id UNIQUE (project_id, archive_id),
  CONSTRAINT fk_chapter_archives_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scenes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  scene_id text NOT NULL,
  chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  scene_order integer NOT NULL DEFAULT 0,
  scene_title text NOT NULL DEFAULT '',
  scene_summary text NOT NULL DEFAULT '',
  scene_purpose text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_scenes_business_id UNIQUE (project_id, scene_id),
  CONSTRAINT uq_scenes_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_scenes_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_scenes_chapter_order
  ON scenes (project_id, chapter_id, scene_order);

CREATE TABLE IF NOT EXISTS scene_participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  participant_id text NOT NULL,
  scene_id uuid,
  character_business_id text NOT NULL DEFAULT '',
  participant_role text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_scene_participants_business_id UNIQUE (project_id, participant_id),
  CONSTRAINT fk_scene_participants_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  draft_id text NOT NULL,
  scene_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  draft_title text NOT NULL DEFAULT '',
  draft_text text NOT NULL DEFAULT '',
  draft_kind text NOT NULL DEFAULT 'PROSE',
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
  CONSTRAINT uq_scene_drafts_business_id UNIQUE (project_id, draft_id),
  CONSTRAINT uq_scene_drafts_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_scene_drafts_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_draft_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  draft_version_id text NOT NULL,
  draft_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  version_number integer NOT NULL DEFAULT 1,
  draft_text text NOT NULL DEFAULT '',
  change_summary text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_scene_draft_versions_business_id UNIQUE (project_id, draft_version_id),
  CONSTRAINT fk_scene_draft_versions_draft_project
    FOREIGN KEY (draft_id, project_id) REFERENCES scene_drafts(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_revision_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  revision_request_id text NOT NULL,
  scene_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  request_text text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'USER_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'USER',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_scene_revision_requests_business_id UNIQUE (project_id, revision_request_id),
  CONSTRAINT uq_scene_revision_requests_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_scene_revision_requests_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_revision_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  revision_plan_id text NOT NULL,
  revision_request_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  plan_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
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
  CONSTRAINT uq_scene_revision_plans_business_id UNIQUE (project_id, revision_plan_id),
  CONSTRAINT fk_scene_revision_plans_revision_request_project
    FOREIGN KEY (revision_request_id, project_id) REFERENCES scene_revision_requests(id, project_id)
);

CREATE TABLE IF NOT EXISTS scene_confirmations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  confirmation_id text NOT NULL,
  scene_id uuid,
  draft_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  confirmed_by text NOT NULL DEFAULT '',
  confirmation_note text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'USER_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'USER',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_scene_confirmations_business_id UNIQUE (project_id, confirmation_id),
  CONSTRAINT fk_scene_confirmations_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_scene_confirmations_draft_project
    FOREIGN KEY (draft_id, project_id) REFERENCES scene_drafts(id, project_id)
);

CREATE TABLE IF NOT EXISTS story_information_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  info_item_id text NOT NULL,
  scene_id uuid,
  chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  info_type text NOT NULL DEFAULT '',
  info_text text NOT NULL DEFAULT '',
  visibility_scope text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_story_information_items_business_id UNIQUE (project_id, info_item_id),
  CONSTRAINT fk_story_information_items_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_story_information_items_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id)
);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('004_chapters_scenes_drafts', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
