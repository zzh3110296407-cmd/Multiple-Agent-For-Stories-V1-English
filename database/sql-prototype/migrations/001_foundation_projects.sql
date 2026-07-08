-- Phase 8.75 M0/M1 PostgreSQL foundation prototype.
-- Scope: Database session only. This file must not be treated as main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

CREATE SCHEMA IF NOT EXISTS mas_phase875_proto;
SET search_path TO mas_phase875_proto;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'canonical_status_value'
      AND n.nspname = current_schema()
  ) THEN
    EXECUTE 'CREATE DOMAIN canonical_status_value AS text CHECK (VALUE IN (
      ''DRAFT'',
      ''CANDIDATE'',
      ''PROVISIONAL'',
      ''TEMPORARY_CONFIRMED'',
      ''CONFIRMED'',
      ''FORMAL_APPLIED'',
      ''SUPERSEDED'',
      ''REJECTED'',
      ''ARCHIVED'',
      ''DELETED''
    ))';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'lifecycle_state_value'
      AND n.nspname = current_schema()
  ) THEN
    EXECUTE 'CREATE DOMAIN lifecycle_state_value AS text CHECK (VALUE IN (
      ''ACTIVE'',
      ''PROVISIONAL'',
      ''ARCHIVED'',
      ''DELETED''
    ))';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'authority_level_value'
      AND n.nspname = current_schema()
  ) THEN
    EXECUTE 'CREATE DOMAIN authority_level_value AS text CHECK (VALUE IN (
      ''USER_LOCKED'',
      ''USER_CONFIRMED'',
      ''FORMAL_APPLIED'',
      ''SYSTEM_CONFIRMED'',
      ''GENERATED_CANDIDATE'',
      ''ANALYZER_REFERENCE'',
      ''MIGRATED_REFERENCE'',
      ''PLUGIN_REFERENCE'',
      ''UNKNOWN''
    ))';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'storage_mode_value'
      AND n.nspname = current_schema()
  ) THEN
    EXECUTE 'CREATE DOMAIN storage_mode_value AS text CHECK (VALUE IN (
      ''JSON_PRIMARY'',
      ''POSTGRES_SHADOW'',
      ''POSTGRES_PRIMARY'',
      ''JSON_EXPORT_ONLY''
    ))';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'backend_type_value'
      AND n.nspname = current_schema()
  ) THEN
    EXECUTE 'CREATE DOMAIN backend_type_value AS text CHECK (VALUE IN (
      ''JSON'',
      ''POSTGRES''
    ))';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'json_import_mode_value'
      AND n.nspname = current_schema()
  ) THEN
    EXECUTE 'CREATE DOMAIN json_import_mode_value AS text CHECK (VALUE IN (
      ''DRY_RUN'',
      ''IMPORT'',
      ''SHADOW_COMPARE'',
      ''EXPORT''
    ))';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS schema_migrations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  migration_name text NOT NULL UNIQUE,
  checksum_sha256 text NOT NULL DEFAULT 'prototype-not-computed',
  status text NOT NULL DEFAULT 'APPLIED',
  applied_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE schema_migrations
  ADD COLUMN IF NOT EXISTS checksum_sha256 text NOT NULL DEFAULT 'prototype-not-computed';

COMMENT ON COLUMN schema_migrations.checksum_sha256 IS
  'Prototype migration checksum. Pass -v migration_checksum_sha256=<sha256> from an external wrapper for a real file hash.';

CREATE TABLE IF NOT EXISTS projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id text NOT NULL,
  schema_version text NOT NULL DEFAULT 'phase8_75_m0',
  display_name text NOT NULL,
  language text NOT NULL DEFAULT 'zh',
  storage_mode storage_mode_value NOT NULL DEFAULT 'JSON_PRIMARY',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'UNKNOWN',
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
  CONSTRAINT uq_projects_business_id UNIQUE (project_id),
  CONSTRAINT ck_projects_storage_mode CHECK (
    storage_mode IN (
      'JSON_PRIMARY',
      'POSTGRES_SHADOW',
      'POSTGRES_PRIMARY',
      'JSON_EXPORT_ONLY'
    )
  ),
  CONSTRAINT ck_projects_status CHECK (
    status IN (
      'DRAFT',
      'CANDIDATE',
      'PROVISIONAL',
      'TEMPORARY_CONFIRMED',
      'CONFIRMED',
      'FORMAL_APPLIED',
      'SUPERSEDED',
      'REJECTED',
      'ARCHIVED',
      'DELETED'
    )
  ),
  CONSTRAINT ck_projects_lifecycle_state CHECK (
    lifecycle_state IN ('ACTIVE', 'PROVISIONAL', 'ARCHIVED', 'DELETED')
  ),
  CONSTRAINT ck_projects_authority_level CHECK (
    authority_level IN (
      'USER_LOCKED',
      'USER_CONFIRMED',
      'FORMAL_APPLIED',
      'SYSTEM_CONFIRMED',
      'GENERATED_CANDIDATE',
      'ANALYZER_REFERENCE',
      'MIGRATED_REFERENCE',
      'PLUGIN_REFERENCE',
      'UNKNOWN'
    )
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_idempotency_key
  ON projects (idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_projects_status
  ON projects (status);

CREATE INDEX IF NOT EXISTS ix_projects_lifecycle_status
  ON projects (lifecycle_state, status);

CREATE TABLE IF NOT EXISTS project_registry_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  project_business_id text NOT NULL,
  display_name text NOT NULL,
  origin_type text NOT NULL DEFAULT 'unknown_origin',
  last_opened_at timestamptz,
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'MIGRATED_REFERENCE',
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_project_registry_business_id UNIQUE (project_id, project_business_id)
);

CREATE INDEX IF NOT EXISTS ix_project_registry_origin
  ON project_registry_entries (project_id, origin_type, status);

CREATE TABLE IF NOT EXISTS project_origins (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  origin_type text NOT NULL,
  origin_ref_id text NOT NULL DEFAULT '',
  is_real_user_project boolean NOT NULL DEFAULT true,
  is_demo_project boolean NOT NULL DEFAULT false,
  is_template_derived boolean NOT NULL DEFAULT false,
  is_analyze_stories_derived boolean NOT NULL DEFAULT false,
  safety_status text NOT NULL DEFAULT 'UNVERIFIED',
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'MIGRATED_REFERENCE',
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_project_origins_one_active UNIQUE (project_id, origin_type, origin_ref_id)
);

CREATE TABLE IF NOT EXISTS storage_backends (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  backend_id text NOT NULL UNIQUE,
  backend_type backend_type_value NOT NULL,
  display_name text NOT NULL,
  config_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT ck_storage_backend_type CHECK (backend_type IN ('JSON', 'POSTGRES'))
);

CREATE INDEX IF NOT EXISTS ix_storage_backends_type_status
  ON storage_backends (backend_type, status);

CREATE TABLE IF NOT EXISTS project_storage_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  backend_id uuid NOT NULL REFERENCES storage_backends(id),
  mode storage_mode_value NOT NULL,
  activated_at timestamptz NOT NULL DEFAULT now(),
  deactivated_at timestamptz,
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT ck_project_storage_mode CHECK (
    mode IN (
      'JSON_PRIMARY',
      'POSTGRES_SHADOW',
      'POSTGRES_PRIMARY',
      'JSON_EXPORT_ONLY'
    )
  )
);

DROP INDEX IF EXISTS uq_project_storage_active_assignment;

CREATE UNIQUE INDEX uq_project_storage_active_assignment
  ON project_storage_assignments (project_id)
  WHERE lifecycle_state = 'ACTIVE'
    AND deactivated_at IS NULL
    AND status IN ('CONFIRMED', 'FORMAL_APPLIED');

COMMENT ON INDEX uq_project_storage_active_assignment IS
  'One confirmed/formal active assignment per project. Supersede by setting status=SUPERSEDED or deactivated_at before inserting a replacement.';

CREATE INDEX IF NOT EXISTS ix_project_storage_mode_status
  ON project_storage_assignments (project_id, mode, status);

CREATE TABLE IF NOT EXISTS json_import_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id text NOT NULL UNIQUE,
  source_root text NOT NULL,
  mode json_import_mode_value NOT NULL DEFAULT 'DRY_RUN',
  project_id uuid REFERENCES projects(id),
  file_count integer NOT NULL DEFAULT 0,
  object_count integer NOT NULL DEFAULT 0,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'MIGRATED_REFERENCE',
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT ck_json_import_mode CHECK (mode IN ('DRY_RUN', 'IMPORT', 'SHADOW_COMPARE', 'EXPORT'))
);

CREATE TABLE IF NOT EXISTS json_import_files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL REFERENCES json_import_batches(id) ON DELETE CASCADE,
  source_path text NOT NULL,
  source_hash text NOT NULL,
  parse_status text NOT NULL DEFAULT 'PENDING',
  target_domain text NOT NULL DEFAULT '',
  target_table text NOT NULL DEFAULT '',
  row_count integer NOT NULL DEFAULT 0,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'MIGRATED_REFERENCE',
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_json_import_file_per_batch UNIQUE (batch_id, source_path)
);

CREATE INDEX IF NOT EXISTS ix_json_import_files_domain_status
  ON json_import_files (target_domain, parse_status, status);

CREATE TABLE IF NOT EXISTS storage_consistency_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id text NOT NULL UNIQUE,
  project_id uuid REFERENCES projects(id),
  batch_id uuid REFERENCES json_import_batches(id),
  result text NOT NULL DEFAULT 'PENDING',
  mismatch_count integer NOT NULL DEFAULT 0,
  mismatches jsonb NOT NULL DEFAULT '[]'::jsonb,
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  source_type text NOT NULL DEFAULT 'SYSTEM',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE INDEX IF NOT EXISTS ix_storage_consistency_project_result
  ON storage_consistency_reports (project_id, result, status);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('001_foundation_projects', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
