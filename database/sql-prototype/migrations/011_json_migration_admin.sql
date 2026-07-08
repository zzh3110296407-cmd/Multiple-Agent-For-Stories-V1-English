-- Phase 8.75 M4 PostgreSQL schema prototype.
-- Domain: JSON import runner admin, mapped-object staging, backup and health records.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

ALTER TABLE json_import_batches
  ADD COLUMN IF NOT EXISTS schema_version text NOT NULL DEFAULT 'phase8_75_m4',
  ADD COLUMN IF NOT EXISTS mapped_file_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS unmapped_file_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS parse_error_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS mapping_report jsonb NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_json_import_batches_id_project'
  ) THEN
    ALTER TABLE json_import_batches
      ADD CONSTRAINT uq_json_import_batches_id_project UNIQUE (id, project_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_json_import_batches_counts_nonnegative'
  ) THEN
    ALTER TABLE json_import_batches
      ADD CONSTRAINT ck_json_import_batches_counts_nonnegative
      CHECK (
        file_count >= 0
        AND object_count >= 0
        AND mapped_file_count >= 0
        AND unmapped_file_count >= 0
        AND parse_error_count >= 0
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_json_import_batches_import_project_required'
  ) THEN
    ALTER TABLE json_import_batches
      ADD CONSTRAINT ck_json_import_batches_import_project_required
      CHECK (mode <> 'IMPORT' OR project_id IS NOT NULL);
  END IF;
END $$;

ALTER TABLE json_import_files
  ADD COLUMN IF NOT EXISTS schema_version text NOT NULL DEFAULT 'phase8_75_m4',
  ADD COLUMN IF NOT EXISTS mapping_status text NOT NULL DEFAULT 'UNMAPPED',
  ADD COLUMN IF NOT EXISTS source_object_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS mapped_object_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS unmapped_reason text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS id_field text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS sample_source_ids jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_json_import_files_id_batch'
  ) THEN
    ALTER TABLE json_import_files
      ADD CONSTRAINT uq_json_import_files_id_batch UNIQUE (id, batch_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_json_import_files_mapping_status'
  ) THEN
    ALTER TABLE json_import_files
      ADD CONSTRAINT ck_json_import_files_mapping_status
      CHECK (mapping_status IN ('MAPPED', 'UNMAPPED', 'PARSE_ERROR', 'UNSUPPORTED_SHAPE'));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_json_import_files_counts_nonnegative'
  ) THEN
    ALTER TABLE json_import_files
      ADD CONSTRAINT ck_json_import_files_counts_nonnegative
      CHECK (row_count >= 0 AND source_object_count >= 0 AND mapped_object_count >= 0);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_json_import_files_mapping_status
  ON json_import_files (batch_id, mapping_status, target_domain, target_table);

ALTER TABLE storage_consistency_reports
  ADD COLUMN IF NOT EXISTS schema_version text NOT NULL DEFAULT 'phase8_75_m4',
  ADD COLUMN IF NOT EXISTS report_kind text NOT NULL DEFAULT 'MAPPING',
  ADD COLUMN IF NOT EXISTS checked_object_count integer NOT NULL DEFAULT 0;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_storage_consistency_checked_count_nonnegative'
  ) THEN
    ALTER TABLE storage_consistency_reports
      ADD CONSTRAINT ck_storage_consistency_checked_count_nonnegative
      CHECK (checked_object_count >= 0 AND mismatch_count >= 0);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_storage_consistency_batch_project_required'
  ) THEN
    ALTER TABLE storage_consistency_reports
      ADD CONSTRAINT ck_storage_consistency_batch_project_required
      CHECK (batch_id IS NULL OR project_id IS NOT NULL);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_storage_consistency_reports_batch_project'
  ) THEN
    ALTER TABLE storage_consistency_reports
      ADD CONSTRAINT fk_storage_consistency_reports_batch_project
      FOREIGN KEY (batch_id, project_id) REFERENCES json_import_batches(id, project_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS json_import_mapped_objects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL,
  file_id uuid NOT NULL,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_path text NOT NULL,
  source_index integer NOT NULL DEFAULT 0,
  source_business_id text NOT NULL DEFAULT '',
  generated_business_id text NOT NULL DEFAULT '',
  target_domain text NOT NULL,
  target_table text NOT NULL,
  id_field text NOT NULL DEFAULT '',
  mapping_status text NOT NULL DEFAULT 'MAPPED',
  import_action text NOT NULL DEFAULT 'STAGE_ONLY',
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_hash text NOT NULL DEFAULT '',
  content_hash text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m4',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'MIGRATED_REFERENCE',
  version integer NOT NULL DEFAULT 1,
  revision integer NOT NULL DEFAULT 1,
  idempotency_key text,
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_json_import_mapped_objects_source UNIQUE (batch_id, source_path, source_index),
  CONSTRAINT uq_json_import_mapped_objects_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_json_import_mapped_objects_batch_project
    FOREIGN KEY (batch_id, project_id) REFERENCES json_import_batches(id, project_id) ON DELETE CASCADE,
  CONSTRAINT fk_json_import_mapped_objects_file_batch
    FOREIGN KEY (file_id, batch_id) REFERENCES json_import_files(id, batch_id) ON DELETE CASCADE,
  CONSTRAINT ck_json_import_mapped_objects_source_index CHECK (source_index >= 0),
  CONSTRAINT ck_json_import_mapped_objects_mapping_status CHECK (mapping_status = 'MAPPED'),
  CONSTRAINT ck_json_import_mapped_objects_import_action
    CHECK (import_action IN ('DRY_RUN_ONLY', 'STAGE_ONLY', 'UPSERT_TARGET', 'SKIP_UNMAPPED')),
  CONSTRAINT ck_json_import_mapped_objects_business_id_available
    CHECK (source_business_id <> '' OR generated_business_id <> '')
);

CREATE INDEX IF NOT EXISTS ix_json_import_mapped_objects_target
  ON json_import_mapped_objects (project_id, target_domain, target_table, mapping_status);

CREATE INDEX IF NOT EXISTS ix_json_import_mapped_objects_source_business_id
  ON json_import_mapped_objects (project_id, target_table, source_business_id)
  WHERE source_business_id <> '' AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS json_import_domain_summaries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  target_domain text NOT NULL,
  target_table text NOT NULL,
  source_file_count integer NOT NULL DEFAULT 0,
  source_object_count integer NOT NULL DEFAULT 0,
  mapped_object_count integer NOT NULL DEFAULT 0,
  imported_object_count integer NOT NULL DEFAULT 0,
  unmapped_object_count integer NOT NULL DEFAULT 0,
  parse_error_count integer NOT NULL DEFAULT 0,
  schema_version text NOT NULL DEFAULT 'phase8_75_m4',
  status canonical_status_value NOT NULL DEFAULT 'DRAFT',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'MIGRATED_REFERENCE',
  source_type text NOT NULL DEFAULT 'MIGRATION',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_json_import_domain_summaries_target UNIQUE (batch_id, target_domain, target_table),
  CONSTRAINT uq_json_import_domain_summaries_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_json_import_domain_summaries_batch_project
    FOREIGN KEY (batch_id, project_id) REFERENCES json_import_batches(id, project_id) ON DELETE CASCADE,
  CONSTRAINT ck_json_import_domain_summaries_counts_nonnegative CHECK (
    source_file_count >= 0
    AND source_object_count >= 0
    AND mapped_object_count >= 0
    AND imported_object_count >= 0
    AND unmapped_object_count >= 0
    AND parse_error_count >= 0
  )
);

CREATE INDEX IF NOT EXISTS ix_json_import_domain_summaries_batch
  ON json_import_domain_summaries (project_id, batch_id, target_domain, target_table);

CREATE TABLE IF NOT EXISTS backup_manifests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
  backup_manifest_id text NOT NULL,
  backup_kind text NOT NULL DEFAULT 'JSON_EXPORT',
  source_batch_id uuid,
  source_root text NOT NULL DEFAULT '',
  artifact_root text NOT NULL DEFAULT '',
  file_count integer NOT NULL DEFAULT 0,
  object_count integer NOT NULL DEFAULT 0,
  manifest_hash text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT 'phase8_75_m4',
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
  CONSTRAINT uq_backup_manifests_business_id UNIQUE (project_id, backup_manifest_id),
  CONSTRAINT uq_backup_manifests_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_backup_manifests_source_batch_project
    FOREIGN KEY (source_batch_id, project_id) REFERENCES json_import_batches(id, project_id),
  CONSTRAINT ck_backup_manifests_kind CHECK (backup_kind IN ('JSON_EXPORT', 'PRE_IMPORT_BACKUP', 'FIXTURE_SNAPSHOT')),
  CONSTRAINT ck_backup_manifests_counts_nonnegative CHECK (file_count >= 0 AND object_count >= 0)
);

CREATE INDEX IF NOT EXISTS ix_backup_manifests_project_kind
  ON backup_manifests (project_id, backup_kind, status, lifecycle_state);

CREATE TABLE IF NOT EXISTS storage_health_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
  health_check_id text NOT NULL,
  check_kind text NOT NULL DEFAULT 'MIGRATION_READINESS',
  check_result text NOT NULL DEFAULT 'PENDING',
  checked_table text NOT NULL DEFAULT '',
  checked_object_count integer NOT NULL DEFAULT 0,
  issue_count integer NOT NULL DEFAULT 0,
  issues jsonb NOT NULL DEFAULT '[]'::jsonb,
  schema_version text NOT NULL DEFAULT 'phase8_75_m4',
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
  CONSTRAINT uq_storage_health_checks_business_id UNIQUE (project_id, health_check_id),
  CONSTRAINT uq_storage_health_checks_id_project UNIQUE (id, project_id),
  CONSTRAINT ck_storage_health_checks_kind
    CHECK (check_kind IN ('MIGRATION_READINESS', 'IMPORT_BATCH', 'BACKUP_MANIFEST', 'STORAGE_MODE')),
  CONSTRAINT ck_storage_health_checks_result
    CHECK (check_result IN ('PENDING', 'PASS', 'WARN', 'FAIL')),
  CONSTRAINT ck_storage_health_checks_counts_nonnegative
    CHECK (checked_object_count >= 0 AND issue_count >= 0)
);

CREATE INDEX IF NOT EXISTS ix_storage_health_checks_project_result
  ON storage_health_checks (project_id, check_kind, check_result, status, lifecycle_state);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('011_json_migration_admin', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
