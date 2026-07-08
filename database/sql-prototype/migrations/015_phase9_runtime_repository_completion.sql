-- Phase 9 M2 runtime repository completion.
-- Scope: Database session prototype plus Phase 9 backend integration smoke.
-- This file only adds a missing normalized table for an existing runtime
-- RepositoryBundle authoritative domain.

\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS prior_story_completion_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  candidate_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase9_m2',
  candidate_type text NOT NULL DEFAULT '',
  candidate_text text NOT NULL DEFAULT '',
  target_issue_id text NOT NULL DEFAULT '',
  candidate_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'RUNTIME',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_prior_story_completion_candidates_business_id UNIQUE (project_id, candidate_id),
  CONSTRAINT uq_prior_story_completion_candidates_id_project UNIQUE (id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_prior_story_completion_candidates_target
  ON prior_story_completion_candidates (project_id, target_issue_id, status);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('015_phase9_runtime_repository_completion', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
