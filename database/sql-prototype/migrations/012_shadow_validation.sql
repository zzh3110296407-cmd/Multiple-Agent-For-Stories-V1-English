-- Phase 8.75 M5 PostgreSQL schema prototype.
-- Domain: shadow import/write validation and semantic consistency reports.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

CREATE TABLE IF NOT EXISTS shadow_validation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  shadow_run_id text NOT NULL,
  import_batch_id uuid NOT NULL,
  source_root text NOT NULL DEFAULT '',
  validation_mode text NOT NULL DEFAULT 'SHADOW_IMPORT',
  expected_object_count integer NOT NULL DEFAULT 0,
  postgres_object_count integer NOT NULL DEFAULT 0,
  mismatch_count integer NOT NULL DEFAULT 0,
  duplicate_write_count integer NOT NULL DEFAULT 0,
  result text NOT NULL DEFAULT 'PENDING',
  schema_version text NOT NULL DEFAULT 'phase8_75_m5',
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
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_shadow_validation_runs_business_id UNIQUE (project_id, shadow_run_id),
  CONSTRAINT uq_shadow_validation_runs_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_shadow_validation_runs_import_batch_project
    FOREIGN KEY (import_batch_id, project_id) REFERENCES json_import_batches(id, project_id) ON DELETE CASCADE,
  CONSTRAINT ck_shadow_validation_runs_mode
    CHECK (validation_mode IN ('SHADOW_IMPORT', 'SHADOW_WRITE', 'SHADOW_COMPARE')),
  CONSTRAINT ck_shadow_validation_runs_result
    CHECK (result IN ('PENDING', 'PASS', 'WARN', 'FAIL')),
  CONSTRAINT ck_shadow_validation_runs_counts_nonnegative
    CHECK (
      expected_object_count >= 0
      AND postgres_object_count >= 0
      AND mismatch_count >= 0
      AND duplicate_write_count >= 0
    )
);

CREATE INDEX IF NOT EXISTS ix_shadow_validation_runs_project_result
  ON shadow_validation_runs (project_id, validation_mode, result, status, lifecycle_state);

CREATE TABLE IF NOT EXISTS shadow_validation_domain_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  shadow_run_id uuid NOT NULL,
  target_domain text NOT NULL,
  target_table text NOT NULL,
  expected_object_count integer NOT NULL DEFAULT 0,
  postgres_object_count integer NOT NULL DEFAULT 0,
  missing_in_postgres_count integer NOT NULL DEFAULT 0,
  extra_in_postgres_count integer NOT NULL DEFAULT 0,
  content_hash_mismatch_count integer NOT NULL DEFAULT 0,
  status_mismatch_count integer NOT NULL DEFAULT 0,
  lifecycle_mismatch_count integer NOT NULL DEFAULT 0,
  source_ref_mismatch_count integer NOT NULL DEFAULT 0,
  duplicate_idempotency_count integer NOT NULL DEFAULT 0,
  result text NOT NULL DEFAULT 'PENDING',
  recommended_fix text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m5',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_shadow_validation_domain_results_target UNIQUE (shadow_run_id, target_domain, target_table),
  CONSTRAINT uq_shadow_validation_domain_results_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_shadow_validation_domain_results_run_project
    FOREIGN KEY (shadow_run_id, project_id) REFERENCES shadow_validation_runs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT ck_shadow_validation_domain_results_result
    CHECK (result IN ('PENDING', 'PASS', 'WARN', 'FAIL')),
  CONSTRAINT ck_shadow_validation_domain_results_counts_nonnegative
    CHECK (
      expected_object_count >= 0
      AND postgres_object_count >= 0
      AND missing_in_postgres_count >= 0
      AND extra_in_postgres_count >= 0
      AND content_hash_mismatch_count >= 0
      AND status_mismatch_count >= 0
      AND lifecycle_mismatch_count >= 0
      AND source_ref_mismatch_count >= 0
      AND duplicate_idempotency_count >= 0
    )
);

CREATE INDEX IF NOT EXISTS ix_shadow_validation_domain_results_run_result
  ON shadow_validation_domain_results (project_id, shadow_run_id, result, target_domain, target_table);

CREATE TABLE IF NOT EXISTS shadow_validation_mismatches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  shadow_run_id uuid NOT NULL,
  shadow_mismatch_id text NOT NULL,
  mismatch_category text NOT NULL,
  severity text NOT NULL DEFAULT 'ERROR',
  target_domain text NOT NULL DEFAULT '',
  target_table text NOT NULL DEFAULT '',
  source_path text NOT NULL DEFAULT '',
  source_index integer,
  source_business_id text NOT NULL DEFAULT '',
  generated_business_id text NOT NULL DEFAULT '',
  expected_value jsonb NOT NULL DEFAULT '{}'::jsonb,
  postgres_value jsonb NOT NULL DEFAULT '{}'::jsonb,
  expected_hash text NOT NULL DEFAULT '',
  postgres_hash text NOT NULL DEFAULT '',
  recommended_fix text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m5',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_shadow_validation_mismatches_business_id UNIQUE (project_id, shadow_mismatch_id),
  CONSTRAINT uq_shadow_validation_mismatches_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_shadow_validation_mismatches_run_project
    FOREIGN KEY (shadow_run_id, project_id) REFERENCES shadow_validation_runs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT ck_shadow_validation_mismatches_category CHECK (
    mismatch_category IN (
      'DOMAIN_COUNT_MISMATCH',
      'MISSING_POSTGRES_OBJECT',
      'EXTRA_POSTGRES_OBJECT',
      'CONTENT_HASH_MISMATCH',
      'STATUS_DRIFT',
      'LIFECYCLE_DRIFT',
      'SOURCE_REF_MISSING',
      'DUPLICATE_IDEMPOTENCY_KEY',
      'FK_REFERENCE_MISSING',
      'ORDER_DRIFT',
      'CURRENT_POINTER_INVALID',
      'PROJECT_ID_MISSING'
    )
  ),
  CONSTRAINT ck_shadow_validation_mismatches_severity
    CHECK (severity IN ('INFO', 'WARN', 'ERROR', 'BLOCKER')),
  CONSTRAINT ck_shadow_validation_mismatches_source_index
    CHECK (source_index IS NULL OR source_index >= 0)
);

CREATE INDEX IF NOT EXISTS ix_shadow_validation_mismatches_run_category
  ON shadow_validation_mismatches (project_id, shadow_run_id, mismatch_category, severity);

CREATE TABLE IF NOT EXISTS shadow_write_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  shadow_run_id uuid NOT NULL,
  shadow_write_receipt_id text NOT NULL,
  idempotency_key text NOT NULL,
  target_domain text NOT NULL,
  target_table text NOT NULL,
  source_business_id text NOT NULL DEFAULT '',
  generated_business_id text NOT NULL DEFAULT '',
  content_hash text NOT NULL DEFAULT '',
  write_mode text NOT NULL DEFAULT 'SHADOW_WRITE',
  write_result text NOT NULL DEFAULT 'ACCEPTED',
  retry_count integer NOT NULL DEFAULT 0,
  first_attempted_at timestamptz NOT NULL DEFAULT now(),
  last_attempted_at timestamptz NOT NULL DEFAULT now(),
  schema_version text NOT NULL DEFAULT 'phase8_75_m5',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_shadow_write_receipts_business_id UNIQUE (project_id, shadow_write_receipt_id),
  CONSTRAINT uq_shadow_write_receipts_idempotency_key UNIQUE (project_id, idempotency_key),
  CONSTRAINT uq_shadow_write_receipts_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_shadow_write_receipts_run_project
    FOREIGN KEY (shadow_run_id, project_id) REFERENCES shadow_validation_runs(id, project_id) ON DELETE CASCADE,
  CONSTRAINT ck_shadow_write_receipts_idempotency_key CHECK (idempotency_key <> ''),
  CONSTRAINT ck_shadow_write_receipts_mode
    CHECK (write_mode IN ('SHADOW_IMPORT', 'SHADOW_WRITE', 'SHADOW_COMPARE')),
  CONSTRAINT ck_shadow_write_receipts_result
    CHECK (write_result IN ('ACCEPTED', 'RETRY_MERGED', 'REJECTED', 'SKIPPED')),
  CONSTRAINT ck_shadow_write_receipts_retry_count CHECK (retry_count >= 0)
);

CREATE INDEX IF NOT EXISTS ix_shadow_write_receipts_run_target
  ON shadow_write_receipts (project_id, shadow_run_id, target_domain, target_table);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('012_shadow_validation', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
