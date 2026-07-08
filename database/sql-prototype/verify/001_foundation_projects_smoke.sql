-- Smoke checks for 001_foundation_projects.sql.
-- The data writes are rolled back; schema objects remain from the migration.

\set ON_ERROR_STOP on

SET search_path TO mas_phase875_proto;

BEGIN;

INSERT INTO storage_backends (
  backend_id,
  backend_type,
  display_name,
  status,
  lifecycle_state,
  authority_level
) VALUES
  ('json_local_files', 'JSON', 'Local JSON files', 'CONFIRMED', 'ACTIVE', 'SYSTEM_CONFIRMED'),
  ('postgres_shadow_local', 'POSTGRES', 'Local PostgreSQL shadow', 'CONFIRMED', 'ACTIVE', 'SYSTEM_CONFIRMED')
ON CONFLICT (backend_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  updated_at = now();

INSERT INTO projects (
  project_id,
  display_name,
  language,
  storage_mode,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  idempotency_key,
  source_type
) VALUES (
  'project_smoke_001',
  'Smoke Project',
  'zh',
  'POSTGRES_SHADOW',
  'DRAFT',
  'project_shell_created',
  'ACTIVE',
  'USER_CONFIRMED',
  'smoke:project:001',
  'SYSTEM'
)
ON CONFLICT (project_id) DO UPDATE SET
  storage_mode = EXCLUDED.storage_mode,
  status = EXCLUDED.status,
  legacy_status_raw = EXCLUDED.legacy_status_raw,
  lifecycle_state = EXCLUDED.lifecycle_state,
  authority_level = EXCLUDED.authority_level,
  updated_at = now();

INSERT INTO project_origins (
  project_id,
  origin_type,
  is_real_user_project,
  is_demo_project,
  safety_status,
  authority_level
)
SELECT
  p.id,
  'prompt_first',
  true,
  false,
  'SAFE_REFERENCE_ONLY',
  'USER_CONFIRMED'
FROM projects p
WHERE p.project_id = 'project_smoke_001'
ON CONFLICT (project_id, origin_type, origin_ref_id) DO UPDATE SET
  safety_status = EXCLUDED.safety_status,
  updated_at = now();

INSERT INTO project_registry_entries (
  project_id,
  project_business_id,
  display_name,
  origin_type,
  status,
  lifecycle_state,
  authority_level
)
SELECT
  p.id,
  p.project_id,
  p.display_name,
  'prompt_first',
  'CONFIRMED',
  'ACTIVE',
  'USER_CONFIRMED'
FROM projects p
WHERE p.project_id = 'project_smoke_001'
ON CONFLICT (project_id, project_business_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  updated_at = now();

INSERT INTO project_storage_assignments (
  project_id,
  backend_id,
  mode,
  status,
  lifecycle_state,
  authority_level
)
SELECT
  p.id,
  b.id,
  'POSTGRES_SHADOW',
  'CONFIRMED',
  'ACTIVE',
  'SYSTEM_CONFIRMED'
FROM projects p
JOIN storage_backends b ON b.backend_id = 'postgres_shadow_local'
WHERE p.project_id = 'project_smoke_001';

DO $$
DECLARE
  project_rows integer;
  assignment_rows integer;
  legacy_rows integer;
BEGIN
  SELECT count(*) INTO project_rows
  FROM projects
  WHERE project_id = 'project_smoke_001'
    AND storage_mode = 'POSTGRES_SHADOW'
    AND status = 'DRAFT'
    AND lifecycle_state = 'ACTIVE'
    AND authority_level = 'USER_CONFIRMED';

  IF project_rows <> 1 THEN
    RAISE EXCEPTION 'Expected one smoke project row, got %', project_rows;
  END IF;

  SELECT count(*) INTO assignment_rows
  FROM project_storage_assignments psa
  JOIN projects p ON p.id = psa.project_id
  WHERE p.project_id = 'project_smoke_001'
    AND psa.mode = 'POSTGRES_SHADOW'
    AND psa.lifecycle_state = 'ACTIVE';

  IF assignment_rows <> 1 THEN
    RAISE EXCEPTION 'Expected one active storage assignment row, got %', assignment_rows;
  END IF;

  SELECT count(*) INTO legacy_rows
  FROM projects
  WHERE project_id = 'project_smoke_001'
    AND legacy_status_raw = 'project_shell_created';

  IF legacy_rows <> 1 THEN
    RAISE EXCEPTION 'Expected preserved legacy_status_raw, got %', legacy_rows;
  END IF;
END $$;

ROLLBACK;

