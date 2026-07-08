-- Phase 8.75 M6 PostgreSQL primary mode readiness prototype.
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
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_project_storage_assignments_id_project'
  ) THEN
    ALTER TABLE project_storage_assignments
      ADD CONSTRAINT uq_project_storage_assignments_id_project UNIQUE (id, project_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_project_storage_assignments_id_project_backend'
  ) THEN
    ALTER TABLE project_storage_assignments
      ADD CONSTRAINT uq_project_storage_assignments_id_project_backend UNIQUE (id, project_id, backend_id);
  END IF;
END $$;

DROP INDEX IF EXISTS uq_project_storage_active_assignment;

CREATE UNIQUE INDEX uq_project_storage_active_assignment
  ON project_storage_assignments (project_id)
  WHERE lifecycle_state = 'ACTIVE'
    AND deactivated_at IS NULL
    AND deleted_at IS NULL
    AND status IN ('CONFIRMED', 'FORMAL_APPLIED');

COMMENT ON INDEX uq_project_storage_active_assignment IS
  'One confirmed/formal active non-deleted assignment per project. Soft-deleted assignments are excluded. Supersede by setting status=SUPERSEDED, deactivated_at, or deleted_at before inserting a replacement.';

CREATE OR REPLACE FUNCTION validate_project_storage_assignment_backend_type()
RETURNS trigger AS $$
DECLARE
  assigned_backend_type text;
  assigned_project_storage_mode text;
BEGIN
  SELECT p.storage_mode::text
  INTO assigned_project_storage_mode
  FROM projects p
  WHERE p.id = NEW.project_id
    AND p.deleted_at IS NULL;

  IF assigned_project_storage_mode IS NULL THEN
    RAISE EXCEPTION 'project % is missing or deleted', NEW.project_id
      USING ERRCODE = 'foreign_key_violation';
  END IF;

  SELECT backend_type::text
  INTO assigned_backend_type
  FROM storage_backends
  WHERE id = NEW.backend_id
    AND deleted_at IS NULL;

  IF assigned_backend_type IS NULL THEN
    RAISE EXCEPTION 'storage backend % is missing or deleted', NEW.backend_id
      USING ERRCODE = 'foreign_key_violation';
  END IF;

  IF NEW.mode IN ('POSTGRES_PRIMARY', 'POSTGRES_SHADOW')
     AND assigned_backend_type <> 'POSTGRES' THEN
    RAISE EXCEPTION 'storage assignment mode % requires POSTGRES backend, got %',
      NEW.mode, assigned_backend_type
      USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.mode IN ('JSON_PRIMARY', 'JSON_EXPORT_ONLY')
     AND assigned_backend_type <> 'JSON' THEN
    RAISE EXCEPTION 'storage assignment mode % requires JSON backend, got %',
      NEW.mode, assigned_backend_type
      USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.lifecycle_state = 'ACTIVE'
     AND NEW.deactivated_at IS NULL
     AND NEW.deleted_at IS NULL
     AND NEW.status IN ('CONFIRMED', 'FORMAL_APPLIED')
     AND NEW.mode <> assigned_project_storage_mode THEN
    RAISE EXCEPTION 'active storage assignment mode % must match project storage_mode %',
      NEW.mode, assigned_project_storage_mode
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_project_storage_assignment_backend_type
  ON project_storage_assignments;

CREATE TRIGGER trg_validate_project_storage_assignment_backend_type
  BEFORE INSERT OR UPDATE OF project_id, backend_id, mode, status, lifecycle_state, deactivated_at, deleted_at
  ON project_storage_assignments
  FOR EACH ROW
  EXECUTE FUNCTION validate_project_storage_assignment_backend_type();

CREATE OR REPLACE FUNCTION validate_project_storage_mode_active_assignments()
RETURNS trigger AS $$
DECLARE
  conflicting_assignment_id uuid;
BEGIN
  IF NEW.deleted_at IS NULL THEN
    SELECT psa.id
    INTO conflicting_assignment_id
    FROM project_storage_assignments psa
    WHERE psa.project_id = NEW.id
      AND psa.lifecycle_state = 'ACTIVE'
      AND psa.deactivated_at IS NULL
      AND psa.deleted_at IS NULL
      AND psa.status IN ('CONFIRMED', 'FORMAL_APPLIED')
      AND psa.mode <> NEW.storage_mode
    LIMIT 1;

    IF conflicting_assignment_id IS NOT NULL THEN
      RAISE EXCEPTION 'project storage_mode % conflicts with active assignment %',
        NEW.storage_mode, conflicting_assignment_id
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_project_storage_mode_active_assignments
  ON projects;

CREATE TRIGGER trg_validate_project_storage_mode_active_assignments
  BEFORE UPDATE OF storage_mode, deleted_at
  ON projects
  FOR EACH ROW
  EXECUTE FUNCTION validate_project_storage_mode_active_assignments();

CREATE OR REPLACE FUNCTION validate_storage_backend_active_assignments()
RETURNS trigger AS $$
DECLARE
  active_assignment_count integer;
  conflicting_assignment_id uuid;
BEGIN
  SELECT count(*)::integer
  INTO active_assignment_count
  FROM project_storage_assignments psa
  WHERE psa.backend_id = NEW.id
    AND psa.lifecycle_state = 'ACTIVE'
    AND psa.deactivated_at IS NULL
    AND psa.deleted_at IS NULL
    AND psa.status IN ('CONFIRMED', 'FORMAL_APPLIED');

  IF active_assignment_count > 0 AND NEW.deleted_at IS NOT NULL THEN
    RAISE EXCEPTION 'storage backend % cannot be deleted while active assignments reference it',
      NEW.id
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT psa.id
  INTO conflicting_assignment_id
  FROM project_storage_assignments psa
  WHERE psa.backend_id = NEW.id
    AND psa.lifecycle_state = 'ACTIVE'
    AND psa.deactivated_at IS NULL
    AND psa.deleted_at IS NULL
    AND psa.status IN ('CONFIRMED', 'FORMAL_APPLIED')
    AND (
      (psa.mode IN ('POSTGRES_PRIMARY', 'POSTGRES_SHADOW') AND NEW.backend_type <> 'POSTGRES')
      OR (psa.mode IN ('JSON_PRIMARY', 'JSON_EXPORT_ONLY') AND NEW.backend_type <> 'JSON')
    )
  LIMIT 1;

  IF conflicting_assignment_id IS NOT NULL THEN
    RAISE EXCEPTION 'storage backend_type % conflicts with active assignment %',
      NEW.backend_type, conflicting_assignment_id
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_storage_backend_active_assignments
  ON storage_backends;

CREATE TRIGGER trg_validate_storage_backend_active_assignments
  BEFORE UPDATE OF backend_type, deleted_at
  ON storage_backends
  FOR EACH ROW
  EXECUTE FUNCTION validate_storage_backend_active_assignments();

CREATE TABLE IF NOT EXISTS postgres_primary_readiness_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  readiness_check_id text NOT NULL,
  storage_assignment_id uuid NOT NULL,
  backend_id uuid NOT NULL REFERENCES storage_backends(id),
  check_kind text NOT NULL,
  check_result text NOT NULL DEFAULT 'PENDING',
  checked_table text NOT NULL DEFAULT '',
  checked_object_count integer NOT NULL DEFAULT 0,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  schema_version text NOT NULL DEFAULT 'phase8_75_m6',
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
  CONSTRAINT uq_postgres_primary_readiness_checks_business_id UNIQUE (project_id, readiness_check_id),
  CONSTRAINT uq_postgres_primary_readiness_checks_id_project UNIQUE (id, project_id),
  CONSTRAINT fk_postgres_primary_readiness_assignment_project
    FOREIGN KEY (storage_assignment_id, project_id, backend_id) REFERENCES project_storage_assignments(id, project_id, backend_id),
  CONSTRAINT ck_postgres_primary_readiness_kind
    CHECK (check_kind IN ('PROJECT_ASSIGNMENT', 'ROUTE_FACTORY', 'CORE_GENERATION_WRITE', 'JSON_EXPORT_BACKUP_PATH')),
  CONSTRAINT ck_postgres_primary_readiness_result
    CHECK (check_result IN ('PENDING', 'PASS', 'WARN', 'FAIL')),
  CONSTRAINT ck_postgres_primary_readiness_count_nonnegative CHECK (checked_object_count >= 0)
);

CREATE INDEX IF NOT EXISTS ix_postgres_primary_readiness_project_result
  ON postgres_primary_readiness_checks (project_id, check_kind, check_result, status, lifecycle_state);

CREATE TABLE IF NOT EXISTS postgres_primary_write_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  storage_assignment_id uuid NOT NULL,
  backend_id uuid NOT NULL REFERENCES storage_backends(id),
  primary_write_id text NOT NULL,
  repository_family text NOT NULL,
  target_table text NOT NULL,
  target_business_id text NOT NULL DEFAULT '',
  write_operation text NOT NULL DEFAULT 'UPSERT',
  write_result text NOT NULL DEFAULT 'ACCEPTED',
  idempotency_key text NOT NULL,
  transaction_ref text NOT NULL DEFAULT '',
  json_export_required boolean NOT NULL DEFAULT true,
  backup_manifest_id uuid,
  schema_version text NOT NULL DEFAULT 'phase8_75_m6',
  status canonical_status_value NOT NULL DEFAULT 'CONFIRMED',
  legacy_status_raw text NOT NULL DEFAULT '',
  lifecycle_state lifecycle_state_value NOT NULL DEFAULT 'ACTIVE',
  authority_level authority_level_value NOT NULL DEFAULT 'SYSTEM_CONFIRMED',
  source_type text NOT NULL DEFAULT 'AGENT',
  source_id text NOT NULL DEFAULT '',
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT uq_postgres_primary_write_receipts_business_id UNIQUE (project_id, primary_write_id),
  CONSTRAINT uq_postgres_primary_write_receipts_id_project UNIQUE (id, project_id),
  CONSTRAINT uq_postgres_primary_write_receipts_idempotency UNIQUE (project_id, idempotency_key),
  CONSTRAINT fk_postgres_primary_write_receipts_assignment_project
    FOREIGN KEY (storage_assignment_id, project_id, backend_id) REFERENCES project_storage_assignments(id, project_id, backend_id),
  CONSTRAINT fk_postgres_primary_write_receipts_backup_project
    FOREIGN KEY (backup_manifest_id, project_id) REFERENCES backup_manifests(id, project_id),
  CONSTRAINT ck_postgres_primary_write_receipts_operation
    CHECK (write_operation IN ('INSERT', 'UPSERT', 'UPDATE', 'APPEND')),
  CONSTRAINT ck_postgres_primary_write_receipts_result
    CHECK (write_result IN ('ACCEPTED', 'RETRY_MERGED', 'REJECTED')),
  CONSTRAINT ck_postgres_primary_write_receipts_idempotency_key CHECK (idempotency_key <> '')
);

CREATE INDEX IF NOT EXISTS ix_postgres_primary_write_receipts_target
  ON postgres_primary_write_receipts (project_id, repository_family, target_table, write_result);

DO $$
BEGIN
  ALTER TABLE postgres_primary_readiness_checks
    DROP CONSTRAINT IF EXISTS fk_postgres_primary_readiness_assignment_project;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_postgres_primary_readiness_assignment_project'
  ) THEN
    ALTER TABLE postgres_primary_readiness_checks
      ADD CONSTRAINT fk_postgres_primary_readiness_assignment_project
      FOREIGN KEY (storage_assignment_id, project_id, backend_id)
      REFERENCES project_storage_assignments(id, project_id, backend_id);
  END IF;

  ALTER TABLE postgres_primary_write_receipts
    DROP CONSTRAINT IF EXISTS fk_postgres_primary_write_receipts_assignment_project;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_postgres_primary_write_receipts_assignment_project'
  ) THEN
    ALTER TABLE postgres_primary_write_receipts
      ADD CONSTRAINT fk_postgres_primary_write_receipts_assignment_project
      FOREIGN KEY (storage_assignment_id, project_id, backend_id)
      REFERENCES project_storage_assignments(id, project_id, backend_id);
  END IF;
END $$;

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('013_postgres_primary_mode', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
