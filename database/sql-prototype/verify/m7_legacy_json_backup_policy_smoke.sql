-- M7 legacy JSON import/export/backup policy smoke.
-- Verifies import acceptance gates, JSON backup manifests, file-level hashes and recovery limits.

\set ON_ERROR_STOP on
SET search_path TO mas_phase875_proto;

BEGIN;

INSERT INTO storage_backends (
  backend_id, backend_type, display_name, config_ref,
  status, legacy_status_raw, lifecycle_state, authority_level,
  source_type, source_id, content_hash
)
VALUES
  (
    'm7_postgres_backend',
    'POSTGRES',
    'M7 PostgreSQL Backend',
    '{"secretRef":"local_pg_service"}'::jsonb,
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm7_smoke',
    'm7-postgres-backend'
  ),
  (
    'm7_json_export_backend',
    'JSON',
    'M7 JSON Export Backend',
    '{"rootRef":"local_json_export_fixture"}'::jsonb,
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm7_smoke',
    'm7-json-export-backend'
  );

WITH pg_backend AS (
  SELECT id FROM storage_backends WHERE backend_id = 'm7_postgres_backend'
), project_row AS (
  INSERT INTO projects (
    project_id, display_name, language, storage_mode,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  VALUES (
    'project_m7_legacy_json_001',
    'M7 Legacy JSON Imported Project',
    'zh',
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'USER_CONFIRMED',
    'USER',
    'm7_smoke',
    'm7-project-hash'
  )
  RETURNING id
), assignment AS (
  INSERT INTO project_storage_assignments (
    project_id, backend_id, mode,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    p.id,
    b.id,
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm7_pg_primary_assignment',
    'm7-pg-primary-assignment-hash'
  FROM project_row p
  CROSS JOIN pg_backend b
  RETURNING id, project_id, backend_id
), import_batch AS (
  INSERT INTO json_import_batches (
    batch_id, source_root, mode, project_id,
    file_count, object_count, mapped_file_count, unmapped_file_count, parse_error_count, mapping_report,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash, completed_at
  )
  SELECT
    'm7_legacy_import_batch_001',
    'legacy_json_fixture/project_m7',
    'IMPORT',
    project_id,
    4,
    8,
    4,
    0,
    0,
    '{"policy":"m7 legacy import accepted"}'::jsonb,
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'MIGRATED_REFERENCE',
    'MIGRATION',
    'm7_legacy_import',
    'm7-import-batch-hash',
    now()
  FROM assignment
  RETURNING id, project_id
), pre_import_backup AS (
  INSERT INTO backup_manifests (
    project_id, backup_manifest_id, backup_kind, source_batch_id, source_root, artifact_root,
    file_count, object_count, manifest_hash,
    manifest_schema_version, content_hash_algorithm, export_format, recovery_policy,
    downgrade_supported, restore_supported, recovery_limitations,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'm7_pre_import_backup_001',
    'PRE_IMPORT_BACKUP',
    id,
    'legacy_json_fixture/project_m7',
    'backup/pre_import/project_m7',
    4,
    8,
    'm7-pre-import-manifest-hash',
    'phase8_75_m7_json_backup_manifest_v1',
    'SHA256',
    'LEGACY_JSON_TOP_LEVEL',
    'INSPECTABLE_BACKUP_ONLY',
    false,
    false,
    '[{"kind":"MANUAL_REVIEW_REQUIRED"}]'::jsonb,
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm7_pre_import_backup',
    'm7-pre-import-backup-hash'
  FROM import_batch
  RETURNING id, project_id
), import_acceptance_kinds(acceptance_check_id, check_kind, checked_object_count) AS (
  VALUES
    ('m7_accept_import_batch_applied', 'IMPORT_BATCH_APPLIED', 8),
    ('m7_accept_shadow_validation_pass', 'SHADOW_VALIDATION_PASS', 8),
    ('m7_accept_pg_primary_assignment', 'POSTGRES_PRIMARY_ASSIGNMENT', 1),
    ('m7_accept_backup_manifest_ready', 'BACKUP_MANIFEST_READY', 1)
)
INSERT INTO legacy_json_import_acceptance_checks (
  project_id, acceptance_check_id, import_batch_id, storage_assignment_id, backend_id,
  check_kind, check_result, checked_object_count, details,
  status, legacy_status_raw, lifecycle_state, authority_level,
  source_type, source_id, content_hash
)
SELECT
  a.project_id,
  k.acceptance_check_id,
  b.id,
  a.id,
  a.backend_id,
  k.check_kind,
  'PASS',
  k.checked_object_count,
  jsonb_build_object('legacyJsonImport', 'accepted', 'postgresMode', 'POSTGRES_PRIMARY'),
  'CONFIRMED',
  'm7_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  k.acceptance_check_id,
  concat('m7-import-acceptance-', lower(k.check_kind))
FROM assignment a
CROSS JOIN import_batch b
CROSS JOIN import_acceptance_kinds k;

WITH project_row AS (
  SELECT id AS project_id FROM projects WHERE project_id = 'project_m7_legacy_json_001'
), backup AS (
  INSERT INTO backup_manifests (
    project_id, backup_manifest_id, backup_kind, source_root, artifact_root,
    file_count, object_count, manifest_hash,
    manifest_schema_version, content_hash_algorithm, export_format, recovery_policy,
    downgrade_supported, restore_supported, recovery_limitations,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'm7_json_export_backup_001',
    'JSON_EXPORT',
    'postgresql_primary',
    'json_export/project_m7',
    3,
    5,
    'm7-json-export-package-hash',
    'phase8_75_m7_json_backup_manifest_v1',
    'SHA256',
    'LEGACY_JSON_TOP_LEVEL',
    'INSPECTABLE_BACKUP_ONLY',
    false,
    false,
    '[{"kind":"SECRET_NOT_EXPORTED"},{"kind":"DOWNGRADE_UNSUPPORTED"}]'::jsonb,
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm7_json_export_backup',
    'm7-json-export-content-hash'
  FROM project_row
  RETURNING id, project_id
), export_run AS (
  INSERT INTO legacy_json_export_runs (
    project_id, export_run_id, backup_manifest_id, export_mode, export_result, artifact_root,
    file_count, object_count, package_hash,
    manifest_schema_version, content_hash_algorithm, export_format,
    downgrade_supported, restore_supported, recovery_limitations,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'm7_json_export_run_001',
    id,
    'BACKUP',
    'PASS',
    'json_export/project_m7',
    3,
    5,
    'm7-json-export-package-hash',
    'phase8_75_m7_json_backup_manifest_v1',
    'SHA256',
    'LEGACY_JSON_TOP_LEVEL',
    false,
    false,
    '[{"kind":"SECRET_NOT_EXPORTED"},{"kind":"DOWNGRADE_UNSUPPORTED"}]'::jsonb,
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm7_json_export_run',
    'm7-json-export-run-hash'
  FROM backup
  RETURNING id, project_id, backup_manifest_id
), export_files(relative_path, json_shape, source_table, source_business_id, object_count, byte_count, file_content_hash) AS (
  VALUES
    ('project.json', 'OBJECT', 'projects', 'project_m7_legacy_json_001', 1, 220, 'm7-project-json-hash'),
    ('scenes.json', 'ARRAY_OF_OBJECTS', 'scenes', 'scene_m7_001', 2, 640, 'm7-scenes-json-hash'),
    ('memory_records.json', 'ARRAY_OF_OBJECTS', 'memory_records', 'memory_m7_001', 2, 760, 'm7-memory-json-hash')
), inserted_files AS (
  INSERT INTO legacy_json_export_files (
    project_id, export_run_id, backup_manifest_id,
    relative_path, json_shape, source_table, source_business_id,
    object_count, byte_count, file_content_hash,
    manifest_schema_version, content_hash_algorithm, export_format,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    r.project_id,
    r.id,
    r.backup_manifest_id,
    f.relative_path,
    f.json_shape,
    f.source_table,
    f.source_business_id,
    f.object_count,
    f.byte_count,
    f.file_content_hash,
    'phase8_75_m7_json_backup_manifest_v1',
    'SHA256',
    'LEGACY_JSON_TOP_LEVEL',
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm7_json_export_file',
    f.file_content_hash
  FROM export_run r
  CROSS JOIN export_files f
  RETURNING project_id, backup_manifest_id
), limitations(limitation_id, limitation_kind, severity, limitation_text, recommended_action, blocks_downgrade) AS (
  VALUES
    ('m7_secret_not_exported', 'SECRET_NOT_EXPORTED', 'WARN', 'Secrets are exported only as secret_ref placeholders.', 'Resolve secrets from secure provider settings after restore.', false),
    ('m7_downgrade_unsupported', 'DOWNGRADE_UNSUPPORTED', 'BLOCKER', 'PostgreSQL-only lifecycle and authority state cannot be downgraded automatically.', 'Use exported JSON for inspection or fixture seeding, not automatic runtime downgrade.', true)
)
INSERT INTO legacy_json_recovery_limitations (
  project_id, backup_manifest_id, limitation_id, limitation_kind, severity,
  limitation_text, recommended_action, blocks_downgrade,
  status, legacy_status_raw, lifecycle_state, authority_level,
  source_type, source_id, content_hash
)
SELECT DISTINCT
  f.project_id,
  f.backup_manifest_id,
  l.limitation_id,
  l.limitation_kind,
  l.severity,
  l.limitation_text,
  l.recommended_action,
  l.blocks_downgrade,
  'CONFIRMED',
  'm7_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  l.limitation_id,
  concat('m7-limitation-', lower(l.limitation_kind))
FROM inserted_files f
CROSS JOIN limitations l;

DO $$
DECLARE
  m7_project_id uuid;
  acceptance_pass_count integer;
  export_file_hash_count integer;
  limitation_count integer;
BEGIN
  SELECT id INTO m7_project_id
  FROM projects
  WHERE project_id = 'project_m7_legacy_json_001'
    AND storage_mode = 'POSTGRES_PRIMARY';

  IF m7_project_id IS NULL THEN
    RAISE EXCEPTION 'Expected M7 PostgreSQL project to exist.';
  END IF;

  SELECT count(*)::integer INTO acceptance_pass_count
  FROM legacy_json_import_acceptance_checks
  WHERE project_id = m7_project_id
    AND check_result = 'PASS';

  IF acceptance_pass_count <> 4 THEN
    RAISE EXCEPTION 'Expected M7 import acceptance PASS checks, got %.', acceptance_pass_count;
  END IF;

  SELECT count(*)::integer INTO export_file_hash_count
  FROM legacy_json_export_files
  WHERE project_id = m7_project_id
    AND file_content_hash <> ''
    AND manifest_schema_version = 'phase8_75_m7_json_backup_manifest_v1';

  IF export_file_hash_count <> 3 THEN
    RAISE EXCEPTION 'Expected M7 JSON export files with hashes, got %.', export_file_hash_count;
  END IF;

  SELECT count(*)::integer INTO limitation_count
  FROM legacy_json_recovery_limitations
  WHERE project_id = m7_project_id
    AND status = 'CONFIRMED';

  IF limitation_count <> 2 THEN
    RAISE EXCEPTION 'Expected two M7 recovery limitations, got %.', limitation_count;
  END IF;
END $$;

DO $$
DECLARE
  m7_project_id uuid;
  backup_id uuid;
BEGIN
  SELECT id INTO m7_project_id FROM projects WHERE project_id = 'project_m7_legacy_json_001';
  SELECT id INTO backup_id FROM backup_manifests WHERE project_id = m7_project_id AND backup_manifest_id = 'm7_json_export_backup_001';

  BEGIN
    INSERT INTO legacy_json_export_runs (
      project_id, export_run_id, backup_manifest_id, export_mode, export_result,
      file_count, object_count, package_hash,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      m7_project_id,
      'm7_invalid_export_mode',
      backup_id,
      'JSON_PRIMARY',
      'PASS',
      1,
      1,
      'm7-invalid-export-mode-hash',
      'CONFIRMED',
      'm7_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm7_invalid_export_mode',
      'm7-invalid-export-mode'
    );
    RAISE EXCEPTION 'Expected invalid export_mode CHECK rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

WITH second_project AS (
  INSERT INTO projects (project_id, display_name, storage_mode, status, legacy_status_raw, lifecycle_state, authority_level)
  VALUES (
    'project_m7_cross_project_002',
    'M7 Cross Project',
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm7_smoke',
    'ACTIVE',
    'USER_CONFIRMED'
  )
  RETURNING id
)
SELECT 1;

DO $$
DECLARE
  source_project_id uuid;
  second_project_id uuid;
  source_export_run_pk uuid;
  backup_id uuid;
BEGIN
  SELECT id INTO source_project_id FROM projects WHERE project_id = 'project_m7_legacy_json_001';
  SELECT id INTO second_project_id FROM projects WHERE project_id = 'project_m7_cross_project_002';
  SELECT r.id, r.backup_manifest_id INTO source_export_run_pk, backup_id
  FROM legacy_json_export_runs r
  WHERE r.project_id = source_project_id
    AND r.export_run_id = 'm7_json_export_run_001';

  BEGIN
    INSERT INTO legacy_json_export_files (
      project_id, export_run_id, backup_manifest_id,
      relative_path, json_shape, object_count, byte_count, file_content_hash,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      second_project_id,
      source_export_run_pk,
      backup_id,
      'cross_project.json',
      'OBJECT',
      1,
      100,
      'm7-cross-project-hash',
      'CONFIRMED',
      'm7_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm7_cross_project_file',
      'm7-cross-project-file'
    );
    RAISE EXCEPTION 'Expected cross-project export file FK rejection.';
  EXCEPTION
    WHEN foreign_key_violation THEN
      NULL;
  END;
END $$;

DO $$
DECLARE
  m7_project_id uuid;
  source_export_run_pk uuid;
  wrong_backup_id uuid;
BEGIN
  SELECT id INTO m7_project_id FROM projects WHERE project_id = 'project_m7_legacy_json_001';
  SELECT id INTO source_export_run_pk
  FROM legacy_json_export_runs
  WHERE project_id = m7_project_id
    AND export_run_id = 'm7_json_export_run_001';

  INSERT INTO backup_manifests (
    project_id, backup_manifest_id, backup_kind, source_root, artifact_root,
    file_count, object_count, manifest_hash,
    manifest_schema_version, content_hash_algorithm, export_format, recovery_policy,
    downgrade_supported, restore_supported, recovery_limitations,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  VALUES (
    m7_project_id,
    'm7_json_export_backup_wrong_manifest_002',
    'JSON_EXPORT',
    'postgresql_primary',
    'json_export/project_m7_wrong_manifest',
    1,
    1,
    'm7-json-export-wrong-manifest-hash',
    'phase8_75_m7_json_backup_manifest_v1',
    'SHA256',
    'LEGACY_JSON_TOP_LEVEL',
    'INSPECTABLE_BACKUP_ONLY',
    false,
    false,
    '[]'::jsonb,
    'CONFIRMED',
    'm7_negative',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm7_wrong_manifest',
    'm7-wrong-manifest-content-hash'
  )
  RETURNING id INTO wrong_backup_id;

  BEGIN
    INSERT INTO legacy_json_export_files (
      project_id, export_run_id, backup_manifest_id,
      relative_path, json_shape, object_count, byte_count, file_content_hash,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      m7_project_id,
      source_export_run_pk,
      wrong_backup_id,
      'same_project_wrong_manifest.json',
      'OBJECT',
      1,
      100,
      'm7-same-project-wrong-manifest-hash',
      'CONFIRMED',
      'm7_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm7_same_project_wrong_manifest_file',
      'm7-same-project-wrong-manifest-file'
    );
    RAISE EXCEPTION 'Expected same-project export file backup manifest mismatch rejection.';
  EXCEPTION
    WHEN foreign_key_violation THEN
      NULL;
  END;
END $$;

DO $$
DECLARE
  m7_project_id uuid;
BEGIN
  SELECT id INTO m7_project_id FROM projects WHERE project_id = 'project_m7_legacy_json_001';

  BEGIN
    INSERT INTO backup_manifests (
      project_id, backup_manifest_id, backup_kind, source_root, artifact_root,
      file_count, object_count, manifest_hash,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      m7_project_id,
      'm7_invalid_empty_manifest_hash',
      'JSON_EXPORT',
      'postgresql_primary',
      'json_export/invalid',
      1,
      1,
      '',
      'CONFIRMED',
      'm7_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm7_invalid_empty_manifest_hash',
      'm7-invalid-empty-manifest-hash'
    );
    RAISE EXCEPTION 'Expected backup manifest without hash rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

ROLLBACK;
