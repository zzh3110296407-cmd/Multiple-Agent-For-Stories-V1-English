-- Phase 8.75 M2A PostgreSQL schema prototype.
-- Domain: events, state changes, decisions, formal apply, objective guards, and gates.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  event_id text NOT NULL,
  scene_id uuid,
  chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  event_type text NOT NULL DEFAULT '',
  event_summary text NOT NULL DEFAULT '',
  event_order integer NOT NULL DEFAULT 0,
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
  CONSTRAINT uq_events_business_id UNIQUE (project_id, event_id),
  CONSTRAINT uq_events_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_events_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_events_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_events_scene_order
  ON events (project_id, scene_id, event_order);

CREATE TABLE IF NOT EXISTS event_participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  event_participant_id text NOT NULL,
  event_id uuid,
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
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_event_participants_business_id UNIQUE (project_id, event_participant_id),
  CONSTRAINT fk_event_participants_event_project
    FOREIGN KEY (event_id, project_id) REFERENCES events(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS state_changes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  state_change_id text NOT NULL,
  event_id uuid,
  scene_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  target_entity_type text NOT NULL DEFAULT '',
  target_business_id text NOT NULL DEFAULT '',
  change_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
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
  CONSTRAINT uq_state_changes_business_id UNIQUE (project_id, state_change_id),
  CONSTRAINT fk_state_changes_event_project
    FOREIGN KEY (event_id, project_id) REFERENCES events(id, project_id),
  CONSTRAINT fk_state_changes_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE TABLE IF NOT EXISTS blocked_objective_fact_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  blocked_candidate_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  candidate_text text NOT NULL DEFAULT '',
  block_reason text NOT NULL DEFAULT '',
  source_entity_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'REJECTED',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ARCHIVED',
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
  CONSTRAINT uq_blocked_objective_fact_candidates_business_id UNIQUE (project_id, blocked_candidate_id)
);

CREATE TABLE IF NOT EXISTS decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  decision_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  decision_type text NOT NULL DEFAULT '',
  decision_text text NOT NULL DEFAULT '',
  rationale text NOT NULL DEFAULT '',
  target_entity_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
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
  CONSTRAINT uq_decisions_business_id UNIQUE (project_id, decision_id),
  CONSTRAINT uq_decisions_id_project UNIQUE (id, project_id)
);

CREATE TABLE IF NOT EXISTS formal_apply_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  check_id text NOT NULL,
  decision_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  check_result text NOT NULL DEFAULT 'PENDING',
  check_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_formal_apply_checks_business_id UNIQUE (project_id, check_id),
  CONSTRAINT fk_formal_apply_checks_decision_project
    FOREIGN KEY (decision_id, project_id) REFERENCES decisions(id, project_id)
);

CREATE TABLE IF NOT EXISTS formal_apply_executions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  execution_id text NOT NULL,
  decision_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  execution_result text NOT NULL DEFAULT 'PENDING',
  applied_entity_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'FORMAL_APPLIED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_formal_apply_executions_business_id UNIQUE (project_id, execution_id),
  CONSTRAINT fk_formal_apply_executions_decision_project
    FOREIGN KEY (decision_id, project_id) REFERENCES decisions(id, project_id)
);

CREATE TABLE IF NOT EXISTS objective_fact_write_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  fact_write_decision_id text NOT NULL,
  decision_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  candidate_fact_text text NOT NULL DEFAULT '',
  guard_result text NOT NULL DEFAULT 'PENDING',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_objective_fact_write_decisions_business_id UNIQUE (project_id, fact_write_decision_id),
  CONSTRAINT fk_objective_fact_write_decisions_decision_project
    FOREIGN KEY (decision_id, project_id) REFERENCES decisions(id, project_id)
);

CREATE TABLE IF NOT EXISTS gate_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  gate_run_id text NOT NULL,
  scene_id uuid,
  chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  gate_name text NOT NULL DEFAULT '',
  gate_result text NOT NULL DEFAULT 'PENDING',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_gate_runs_business_id UNIQUE (project_id, gate_run_id),
  CONSTRAINT uq_gate_runs_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_gate_runs_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_gate_runs_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id)
);

CREATE TABLE IF NOT EXISTS gate_findings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  finding_id text NOT NULL,
  gate_run_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  finding_type text NOT NULL DEFAULT '',
  severity text NOT NULL DEFAULT '',
  finding_text text NOT NULL DEFAULT '',
  target_entity_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_gate_findings_business_id UNIQUE (project_id, finding_id),
  CONSTRAINT fk_gate_findings_gate_run_project
    FOREIGN KEY (gate_run_id, project_id) REFERENCES gate_runs(id, project_id) ON DELETE CASCADE
);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('005_events_state_decisions_gates', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
