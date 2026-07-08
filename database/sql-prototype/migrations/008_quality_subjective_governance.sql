-- Phase 8.75 M2B PostgreSQL schema prototype.
-- Domain: quality, continuity, subjective reality, and narrative intent tables required for Schema V0.
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
    WHERE conname = 'uq_gate_runs_id_project'
      AND conrelid = 'gate_runs'::regclass
  ) THEN
    ALTER TABLE gate_runs
      ADD CONSTRAINT uq_gate_runs_id_project UNIQUE (id, project_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS quality_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  quality_report_id text NOT NULL,
  scene_id uuid,
  chapter_id uuid,
  gate_run_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  report_type text NOT NULL DEFAULT '',
  report_result text NOT NULL DEFAULT 'PENDING',
  score numeric(6,3),
  summary text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_quality_reports_business_id UNIQUE (project_id, quality_report_id),
  CONSTRAINT uq_quality_reports_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_quality_reports_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_quality_reports_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id),
  CONSTRAINT fk_quality_reports_gate_run_project
    FOREIGN KEY (gate_run_id, project_id) REFERENCES gate_runs(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_quality_reports_scope
  ON quality_reports (project_id, chapter_id, scene_id, report_result, status);

CREATE TABLE IF NOT EXISTS continuity_issues (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  continuity_issue_id text NOT NULL,
  quality_report_id uuid,
  scene_id uuid,
  chapter_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  issue_type text NOT NULL DEFAULT '',
  severity text NOT NULL DEFAULT '',
  issue_text text NOT NULL DEFAULT '',
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
  CONSTRAINT uq_continuity_issues_business_id UNIQUE (project_id, continuity_issue_id),
  CONSTRAINT uq_continuity_issues_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_continuity_issues_quality_report_project
    FOREIGN KEY (quality_report_id, project_id) REFERENCES quality_reports(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_continuity_issues_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_continuity_issues_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_continuity_issues_scope
  ON continuity_issues (project_id, chapter_id, scene_id, severity, status);

CREATE TABLE IF NOT EXISTS claim_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  claim_id text NOT NULL,
  scene_id uuid,
  speaker_entity_type text NOT NULL DEFAULT '',
  speaker_business_id text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  claim_text text NOT NULL DEFAULT '',
  truth_status text NOT NULL DEFAULT 'UNKNOWN',
  claim_scope text NOT NULL DEFAULT '',
  certainty_label text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
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
  CONSTRAINT uq_claim_records_business_id UNIQUE (project_id, claim_id),
  CONSTRAINT uq_claim_records_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_claim_records_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_claim_records_speaker
  ON claim_records (project_id, speaker_entity_type, speaker_business_id, status);

CREATE TABLE IF NOT EXISTS perception_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  perception_id text NOT NULL,
  source_scene_id uuid,
  character_business_id text NOT NULL DEFAULT '',
  target_entity_type text NOT NULL DEFAULT '',
  target_business_id text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  perceived_fact text NOT NULL DEFAULT '',
  confidence numeric(6,3),
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
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
  CONSTRAINT uq_perception_states_business_id UNIQUE (project_id, perception_id),
  CONSTRAINT uq_perception_states_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_perception_states_source_scene_project
    FOREIGN KEY (source_scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_perception_states_target
  ON perception_states (project_id, target_entity_type, target_business_id, status);

CREATE TABLE IF NOT EXISTS character_psychology_traces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  trace_id text NOT NULL,
  scene_id uuid,
  character_business_id text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  internal_state text NOT NULL DEFAULT '',
  visibility text NOT NULL DEFAULT '',
  trace_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
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
  CONSTRAINT uq_character_psychology_traces_business_id UNIQUE (project_id, trace_id),
  CONSTRAINT uq_character_psychology_traces_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_character_psychology_traces_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_character_psychology_traces_character
  ON character_psychology_traces (project_id, character_business_id, status);

CREATE TABLE IF NOT EXISTS character_expression_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  expression_id text NOT NULL,
  scene_id uuid,
  character_business_id text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  expression_text text NOT NULL DEFAULT '',
  expression_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
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
  CONSTRAINT uq_character_expression_records_business_id UNIQUE (project_id, expression_id),
  CONSTRAINT uq_character_expression_records_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_character_expression_records_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_character_expression_records_character
  ON character_expression_records (project_id, character_business_id, status);

CREATE TABLE IF NOT EXISTS narrative_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  intent_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  target_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  intent_type text NOT NULL DEFAULT '',
  description text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
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
  CONSTRAINT uq_narrative_intents_business_id UNIQUE (project_id, intent_id),
  CONSTRAINT uq_narrative_intents_id_project UNIQUE (id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_narrative_intents_type
  ON narrative_intents (project_id, intent_type, status);

CREATE TABLE IF NOT EXISTS apparent_contradictions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  contradiction_id text NOT NULL,
  scene_id uuid,
  narrative_intent_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  contradiction_text text NOT NULL DEFAULT '',
  related_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  classification text NOT NULL DEFAULT '',
  resolution_status text NOT NULL DEFAULT 'OPEN',
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
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
  CONSTRAINT uq_apparent_contradictions_business_id UNIQUE (project_id, contradiction_id),
  CONSTRAINT uq_apparent_contradictions_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_apparent_contradictions_scene_project
    FOREIGN KEY (scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_apparent_contradictions_narrative_intent_project
    FOREIGN KEY (narrative_intent_id, project_id) REFERENCES narrative_intents(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_apparent_contradictions_status
  ON apparent_contradictions (project_id, resolution_status, status);

CREATE TABLE IF NOT EXISTS narrative_debts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  debt_id text NOT NULL,
  chapter_id uuid,
  setup_scene_id uuid,
  payoff_scene_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m2',
  debt_type text NOT NULL DEFAULT '',
  debt_text text NOT NULL DEFAULT '',
  setup_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  payoff_plan text NOT NULL DEFAULT '',
  status canonical_status_value NOT NULL DEFAULT 'CANDIDATE',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'PROVISIONAL',
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
  CONSTRAINT uq_narrative_debts_business_id UNIQUE (project_id, debt_id),
  CONSTRAINT uq_narrative_debts_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_narrative_debts_chapter_project
    FOREIGN KEY (chapter_id, project_id) REFERENCES chapters(id, project_id),
  CONSTRAINT fk_narrative_debts_setup_scene_project
    FOREIGN KEY (setup_scene_id, project_id) REFERENCES scenes(id, project_id),
  CONSTRAINT fk_narrative_debts_payoff_scene_project
    FOREIGN KEY (payoff_scene_id, project_id) REFERENCES scenes(id, project_id)
);

CREATE INDEX IF NOT EXISTS ix_narrative_debts_chapter_status
  ON narrative_debts (project_id, chapter_id, status);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('008_quality_subjective_governance', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
