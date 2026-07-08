-- Phase 8.75 M2A PostgreSQL schema prototype.
-- Domain: model metadata, story setup, and user intent.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS model_providers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  provider_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  provider_name text NOT NULL,
  provider_family text NOT NULL DEFAULT '',
  secret_ref text NOT NULL DEFAULT '',
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
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
  CONSTRAINT uq_model_providers_business_id UNIQUE (project_id, provider_id),
  CONSTRAINT uq_model_providers_id_project UNIQUE (id, project_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_model_providers_idempotency_key
  ON model_providers (project_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS model_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  profile_id text NOT NULL,
  provider_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  profile_name text NOT NULL,
  model_name text NOT NULL,
  agent_role text NOT NULL DEFAULT '',
  model_parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
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
  CONSTRAINT uq_model_profiles_business_id UNIQUE (project_id, profile_id),
  CONSTRAINT uq_model_profiles_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_model_profiles_provider_project
    FOREIGN KEY (provider_id, project_id) REFERENCES model_providers(id, project_id)
);

CREATE TABLE IF NOT EXISTS agent_model_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  assignment_id text NOT NULL,
  profile_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  agent_role text NOT NULL,
  assignment_scope text NOT NULL DEFAULT 'PROJECT',
  priority integer NOT NULL DEFAULT 100,
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
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
  CONSTRAINT uq_agent_model_assignments_business_id UNIQUE (project_id, assignment_id),
  CONSTRAINT fk_agent_model_assignments_profile_project
    FOREIGN KEY (profile_id, project_id) REFERENCES model_profiles(id, project_id)
);

CREATE TABLE IF NOT EXISTS trace_refs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  trace_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  trace_type text NOT NULL DEFAULT '',
  redacted_summary text NOT NULL DEFAULT '',
  external_ref text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
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
  CONSTRAINT uq_trace_refs_business_id UNIQUE (project_id, trace_id)
);

CREATE TABLE IF NOT EXISTS project_story_premises (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  premise_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  title text NOT NULL DEFAULT '',
  premise_text text NOT NULL,
  language text NOT NULL DEFAULT 'zh',
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
  CONSTRAINT uq_project_story_premises_business_id UNIQUE (project_id, premise_id),
  CONSTRAINT uq_project_story_premises_id_project UNIQUE (id, project_id)
);

CREATE TABLE IF NOT EXISTS prompt_fidelity_contracts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  contract_id text NOT NULL,
  premise_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  contract_text text NOT NULL DEFAULT '',
  acceptance_checks jsonb NOT NULL DEFAULT '[]'::jsonb,
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
  CONSTRAINT uq_prompt_fidelity_contracts_business_id UNIQUE (project_id, contract_id),
  CONSTRAINT fk_prompt_fidelity_contracts_premise_project
    FOREIGN KEY (premise_id, project_id) REFERENCES project_story_premises(id, project_id)
);

CREATE TABLE IF NOT EXISTS story_setup_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  session_id text NOT NULL,
  premise_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  session_stage text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_story_setup_sessions_business_id UNIQUE (project_id, session_id),
  CONSTRAINT uq_story_setup_sessions_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_story_setup_sessions_premise_project
    FOREIGN KEY (premise_id, project_id) REFERENCES project_story_premises(id, project_id)
);

CREATE TABLE IF NOT EXISTS story_setup_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  question_id text NOT NULL,
  session_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  question_text text NOT NULL,
  answer_text text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_story_setup_questions_business_id UNIQUE (project_id, question_id),
  CONSTRAINT fk_story_setup_questions_session_project
    FOREIGN KEY (session_id, project_id) REFERENCES story_setup_sessions(id, project_id)
);

CREATE TABLE IF NOT EXISTS story_setup_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  decision_id text NOT NULL,
  session_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  decision_text text NOT NULL,
  rationale text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_story_setup_decisions_business_id UNIQUE (project_id, decision_id),
  CONSTRAINT fk_story_setup_decisions_session_project
    FOREIGN KEY (session_id, project_id) REFERENCES story_setup_sessions(id, project_id)
);

CREATE TABLE IF NOT EXISTS story_setup_handoffs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  handoff_id text NOT NULL,
  session_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  handoff_type text NOT NULL DEFAULT '',
  handoff_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
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
  CONSTRAINT uq_story_setup_handoffs_business_id UNIQUE (project_id, handoff_id),
  CONSTRAINT fk_story_setup_handoffs_session_project
    FOREIGN KEY (session_id, project_id) REFERENCES story_setup_sessions(id, project_id)
);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('002_model_setup_story_intent', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
