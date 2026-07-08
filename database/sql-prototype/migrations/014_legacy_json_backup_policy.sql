-- Phase 8.75 M7 legacy JSON import/export/backup policy prototype.
-- Scope: Database session only. This file must not be treated as a main backend migration yet.

\set ON_ERROR_STOP on
\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto;

ALTER TABLE backup_manifests
  ADD COLUMN IF NOT EXISTS manifest_schema_version text NOT NULL DEFAULT 'phase8_75_m7_json_backup_manifest_v1',
  ADD COLUMN IF NOT EXISTS content_hash_algorithm text NOT NULL DEFAULT 'SHA256',
  ADD COLUMN IF NOT EXISTS export_format text NOT NULL DEFAULT 'LEGACY_JSON_TOP_LEVEL',
  ADD COLUMN IF NOT EXISTS recovery_policy text NOT NULL DEFAULT 'INSPECTABLE_BACKUP_ONLY',
  ADD COLUMN IF NOT EXISTS downgrade_supported boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS restore_supported boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS recovery_limitations jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_backup_manifests_m7_hash_required'
  ) THEN
    ALTER TABLE backup_manifests
      ADD CONSTRAINT ck_backup_manifests_m7_hash_required
      CHECK (
        backup_kind NOT IN ('JSON_EXPORT', 'PRE_IMPORT_BACKUP', 'FIXTURE_SNAPSHOT')
        OR manifest_hash <> ''
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_backup_manifests_m7_schema_required'
  ) THEN
    ALTER TABLE backup_manifests
      ADD CONSTRAINT ck_backup_manifests_m7_schema_required
      CHECK (manifest_schema_version <> '' AND content_hash_algorithm = 'SHA256');
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_backup_manifests_m7_export_format'
  ) THEN
    ALTER TABLE backup_manifests
      ADD CONSTRAINT ck_backup_manifests_m7_export_format
      CHECK (export_format IN ('LEGACY_JSON_TOP_LEVEL', 'LEGACY_JSON_ARCHIVE', 'POSTGRESQL_FIXTURE_JSON'));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_backup_manifests_m7_recovery_policy'
  ) THEN
    ALTER TABLE backup_manifests
      ADD CONSTRAINT ck_backup_manifests_m7_recovery_policy
      CHECK (recovery_policy IN ('INSPECTABLE_BACKUP_ONLY', 'MANUAL_RESTORE_REQUIRED', 'DOWNGRADE_UNSUPPORTED'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS legacy_json_import_acceptance_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  acceptance_check_id text NOT NULL,
  import_batch_id uuid NOT NULL,
  storage_assignment_id uuid NOT NULL,
  backend_id uuid NOT NULL,
  check_kind text NOT NULL,
  check_result text NOT NULL DEFAULT 'PENDING',
  checked_object_count integer NOT NULL DEFAULT 0,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  schema_version text NOT NULL DEFAULT 'phase8_75_m7',
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
  CONSTRAINT uq_legacy_json_import_acceptance_checks_business_id UNIQUE (project_id, acceptance_check_id),
  CONSTRAINT uq_legacy_json_import_acceptance_checks_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_legacy_json_import_acceptance_batch_project
    FOREIGN KEY (import_batch_id, project_id) REFERENCES json_import_batches(id, project_id),
  CONSTRAINT fk_legacy_json_import_acceptance_assignment_project
    FOREIGN KEY (storage_assignment_id, project_id, backend_id) REFERENCES project_storage_assignments(id, project_id, backend_id),
  CONSTRAINT ck_legacy_json_import_acceptance_kind
    CHECK (check_kind IN ('IMPORT_BATCH_APPLIED', 'SHADOW_VALIDATION_PASS', 'POSTGRES_PRIMARY_ASSIGNMENT', 'BACKUP_MANIFEST_READY')),
  CONSTRAINT ck_legacy_json_import_acceptance_result
    CHECK (check_result IN ('PENDING', 'PASS', 'WARN', 'FAIL')),
  CONSTRAINT ck_legacy_json_import_acceptance_count_nonnegative CHECK (checked_object_count >= 0)
);

CREATE INDEX IF NOT EXISTS ix_legacy_json_import_acceptance_project_result
  ON legacy_json_import_acceptance_checks (project_id, check_kind, check_result, status, lifecycle_state);

CREATE TABLE IF NOT EXISTS legacy_json_export_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  export_run_id text NOT NULL,
  backup_manifest_id uuid NOT NULL,
  export_mode text NOT NULL DEFAULT 'BACKUP',
  export_result text NOT NULL DEFAULT 'PENDING',
  artifact_root text NOT NULL DEFAULT '',
  file_count integer NOT NULL DEFAULT 0,
  object_count integer NOT NULL DEFAULT 0,
  package_hash text NOT NULL DEFAULT '',
  manifest_schema_version text NOT NULL DEFAULT 'phase8_75_m7_json_backup_manifest_v1',
  content_hash_algorithm text NOT NULL DEFAULT 'SHA256',
  export_format text NOT NULL DEFAULT 'LEGACY_JSON_TOP_LEVEL',
  downgrade_supported boolean NOT NULL DEFAULT false,
  restore_supported boolean NOT NULL DEFAULT false,
  recovery_limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
  schema_version text NOT NULL DEFAULT 'phase8_75_m7',
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
  CONSTRAINT uq_legacy_json_export_runs_business_id UNIQUE (project_id, export_run_id),
  CONSTRAINT uq_legacy_json_export_runs_id_project UNIQUE (id, project_id),
  CONSTRAINT uq_legacy_json_export_runs_id_project_manifest UNIQUE (id, project_id, backup_manifest_id),
  CONSTRAINT fk_legacy_json_export_runs_backup_project
    FOREIGN KEY (backup_manifest_id, project_id) REFERENCES backup_manifests(id, project_id),
  CONSTRAINT ck_legacy_json_export_runs_mode
    CHECK (export_mode IN ('BACKUP', 'FIXTURE', 'DOWNGRADE_ATTEMPT')),
  CONSTRAINT ck_legacy_json_export_runs_result
    CHECK (export_result IN ('PENDING', 'PASS', 'WARN', 'FAIL')),
  CONSTRAINT ck_legacy_json_export_runs_counts_nonnegative CHECK (file_count >= 0 AND object_count >= 0),
  CONSTRAINT ck_legacy_json_export_runs_schema_nonempty CHECK (manifest_schema_version <> '' AND content_hash_algorithm = 'SHA256'),
  CONSTRAINT ck_legacy_json_export_runs_pass_hash CHECK (export_result <> 'PASS' OR package_hash <> '')
);

CREATE INDEX IF NOT EXISTS ix_legacy_json_export_runs_project_result
  ON legacy_json_export_runs (project_id, export_mode, export_result, status, lifecycle_state);

CREATE TABLE IF NOT EXISTS legacy_json_export_files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  export_run_id uuid NOT NULL,
  backup_manifest_id uuid NOT NULL,
  relative_path text NOT NULL,
  json_shape text NOT NULL DEFAULT 'TOP_LEVEL_JSON',
  source_table text NOT NULL DEFAULT '',
  source_business_id text NOT NULL DEFAULT '',
  object_count integer NOT NULL DEFAULT 0,
  byte_count integer NOT NULL DEFAULT 0,
  file_content_hash text NOT NULL,
  manifest_schema_version text NOT NULL DEFAULT 'phase8_75_m7_json_backup_manifest_v1',
  content_hash_algorithm text NOT NULL DEFAULT 'SHA256',
  export_format text NOT NULL DEFAULT 'LEGACY_JSON_TOP_LEVEL',
  is_required boolean NOT NULL DEFAULT true,
  schema_version text NOT NULL DEFAULT 'phase8_75_m7',
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
  CONSTRAINT uq_legacy_json_export_files_path UNIQUE (project_id, export_run_id, relative_path),
  CONSTRAINT uq_legacy_json_export_files_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_legacy_json_export_files_run_project
    FOREIGN KEY (export_run_id, project_id, backup_manifest_id) REFERENCES legacy_json_export_runs(id, project_id, backup_manifest_id) ON DELETE CASCADE,
  CONSTRAINT fk_legacy_json_export_files_backup_project
    FOREIGN KEY (backup_manifest_id, project_id) REFERENCES backup_manifests(id, project_id),
  CONSTRAINT ck_legacy_json_export_files_path CHECK (
    relative_path <> ''
    AND relative_path LIKE '%.json'
    AND position('..' in relative_path) = 0
  ),
  CONSTRAINT ck_legacy_json_export_files_shape
    CHECK (json_shape IN ('TOP_LEVEL_JSON', 'ARRAY_OF_OBJECTS', 'OBJECT')),
  CONSTRAINT ck_legacy_json_export_files_counts_nonnegative CHECK (object_count >= 0 AND byte_count >= 0),
  CONSTRAINT ck_legacy_json_export_files_hash_required CHECK (file_content_hash <> '' AND content_hash_algorithm = 'SHA256'),
  CONSTRAINT ck_legacy_json_export_files_schema_nonempty CHECK (manifest_schema_version <> '')
);

CREATE INDEX IF NOT EXISTS ix_legacy_json_export_files_manifest
  ON legacy_json_export_files (project_id, backup_manifest_id, relative_path);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_legacy_json_export_runs_id_project_manifest'
  ) THEN
    ALTER TABLE legacy_json_export_runs
      ADD CONSTRAINT uq_legacy_json_export_runs_id_project_manifest UNIQUE (id, project_id, backup_manifest_id);
  END IF;

  ALTER TABLE legacy_json_export_files
    DROP CONSTRAINT IF EXISTS fk_legacy_json_export_files_run_project;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_legacy_json_export_files_run_project'
  ) THEN
    ALTER TABLE legacy_json_export_files
      ADD CONSTRAINT fk_legacy_json_export_files_run_project
      FOREIGN KEY (export_run_id, project_id, backup_manifest_id)
      REFERENCES legacy_json_export_runs(id, project_id, backup_manifest_id)
      ON DELETE CASCADE;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS legacy_json_recovery_limitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  backup_manifest_id uuid NOT NULL,
  limitation_id text NOT NULL,
  limitation_kind text NOT NULL,
  severity text NOT NULL DEFAULT 'WARN',
  limitation_text text NOT NULL,
  recommended_action text NOT NULL DEFAULT '',
  blocks_downgrade boolean NOT NULL DEFAULT true,
  schema_version text NOT NULL DEFAULT 'phase8_75_m7',
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
  CONSTRAINT uq_legacy_json_recovery_limitations_business_id UNIQUE (project_id, backup_manifest_id, limitation_id),
  CONSTRAINT uq_legacy_json_recovery_limitations_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_legacy_json_recovery_limitations_backup_project
    FOREIGN KEY (backup_manifest_id, project_id) REFERENCES backup_manifests(id, project_id) ON DELETE CASCADE,
  CONSTRAINT ck_legacy_json_recovery_limitations_kind
    CHECK (limitation_kind IN (
      'DOWNGRADE_UNSUPPORTED',
      'RUNTIME_SWITCH_REQUIRED',
      'SECRET_NOT_EXPORTED',
      'UNMAPPED_OBJECTS',
      'SCHEMA_VERSION_LOSS',
      'MANUAL_REVIEW_REQUIRED'
    )),
  CONSTRAINT ck_legacy_json_recovery_limitations_severity
    CHECK (severity IN ('INFO', 'WARN', 'ERROR', 'BLOCKER')),
  CONSTRAINT ck_legacy_json_recovery_limitations_text CHECK (limitation_text <> '')
);

CREATE INDEX IF NOT EXISTS ix_legacy_json_recovery_limitations_manifest
  ON legacy_json_recovery_limitations (project_id, backup_manifest_id, severity, limitation_kind);

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('014_legacy_json_backup_policy', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
