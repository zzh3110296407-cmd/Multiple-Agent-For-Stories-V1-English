-- M6 PostgreSQL primary mode smoke.
-- Verifies a new project can be assigned to POSTGRES_PRIMARY, write core generation rows,
-- keep JSON export/backup path, and reject invalid backend/mode pairs.

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
    'm6_postgres_backend',
    'POSTGRES',
    'M6 PostgreSQL Primary Backend',
    '{"secretRef":"local_pg_service"}'::jsonb,
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm6_smoke',
    'm6-postgres-backend'
  ),
  (
    'm6_json_export_backend',
    'JSON',
    'M6 JSON Export Backend',
    '{"rootRef":"local_json_export_fixture"}'::jsonb,
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm6_smoke',
    'm6-json-export-backend'
  );

WITH pg_backend AS (
  SELECT id FROM storage_backends WHERE backend_id = 'm6_postgres_backend'
), new_project AS (
  INSERT INTO projects (
    project_id, display_name, language, storage_mode,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash, metadata
  )
  VALUES (
    'project_m6_pg_primary_001',
    'M6 PostgreSQL Primary Smoke Project',
    'zh',
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED',
    'USER',
    'm6_smoke',
    'm6-project-hash',
    '{"m6":"postgres_primary"}'::jsonb
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
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm6_primary_assignment',
    'm6-primary-assignment-hash'
  FROM new_project p
  CROSS JOIN pg_backend b
  RETURNING id, project_id, backend_id
), registry AS (
  INSERT INTO project_registry_entries (
    project_id, project_business_id, display_name, origin_type,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    a.project_id,
    'project_m6_pg_primary_001',
    'M6 PostgreSQL Primary Smoke Project',
    'postgres_primary_new_project',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED',
    'SYSTEM',
    'm6_registry',
    'm6-registry-hash'
  FROM assignment a
), premise AS (
  INSERT INTO project_story_premises (
    project_id, premise_id, title, premise_text, language,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    a.project_id,
    'premise_m6_001',
    'M6 Primary Premise',
    'A database-primary smoke premise used to verify PostgreSQL-first writes.',
    'zh',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED',
    'USER',
    'm6_premise',
    'm6-premise-hash'
  FROM assignment a
  RETURNING project_id
), bible AS (
  INSERT INTO story_bibles (
    project_id, bible_id, title, bible_payload,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'bible_m6_001',
    'M6 Primary Bible',
    '{"theme":"postgres primary readiness"}'::jsonb,
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    'm6_bible',
    'm6-bible-hash'
  FROM premise
  RETURNING project_id
), world AS (
  INSERT INTO world_canvases (
    project_id, canvas_id, canvas_name, canvas_payload,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'world_m6_001',
    'M6 Primary World',
    '{"location":"PostgreSQL Harbor"}'::jsonb,
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    'm6_world',
    'm6-world-hash'
  FROM bible
  RETURNING project_id
), character_row AS (
  INSERT INTO characters (
    project_id, character_id, display_name, role_tier, short_description,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'character_m6_001',
    'M6 Character',
    'PROTAGONIST',
    'Character written through the PG-primary smoke path.',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    'm6_character',
    'm6-character-hash'
  FROM world
  RETURNING project_id
), chapter_row AS (
  INSERT INTO chapters (
    project_id, chapter_id, chapter_number, title, chapter_summary,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'chapter_m6_001',
    1,
    'M6 Chapter',
    'Chapter written through the PG-primary smoke path.',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    'm6_chapter',
    'm6-chapter-hash'
  FROM character_row
  RETURNING id, project_id
), scene_row AS (
  INSERT INTO scenes (
    project_id, scene_id, chapter_id, scene_order, scene_title, scene_summary, scene_purpose,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'scene_m6_001',
    id,
    1,
    'M6 Scene',
    'Scene written through the PG-primary smoke path.',
    'Verify PostgreSQL primary write path.',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    'm6_scene',
    'm6-scene-hash'
  FROM chapter_row
  RETURNING id, project_id
), draft_row AS (
  INSERT INTO scene_drafts (
    project_id, draft_id, scene_id, draft_title, draft_text, draft_kind,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'draft_m6_001',
    id,
    'M6 Draft',
    'M6 PostgreSQL primary draft text.',
    'PROSE',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    'm6_draft',
    'm6-draft-hash'
  FROM scene_row
  RETURNING project_id
), event_row AS (
  INSERT INTO events (
    project_id, event_id, scene_id, chapter_id, event_type, event_summary, event_order,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    s.project_id,
    'event_m6_001',
    s.id,
    c.id,
    'SMOKE_EVENT',
    'Event written through the PG-primary smoke path.',
    1,
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    'm6_event',
    'm6-event-hash'
  FROM scene_row s
  JOIN chapter_row c ON c.project_id = s.project_id
  RETURNING id, scene_id, chapter_id, project_id
), memory_row AS (
  INSERT INTO memory_records (
    project_id, memory_id, scene_id, chapter_id, event_id, memory_lane, memory_type,
    subject_entity_type, subject_business_id, memory_text, visibility_scope,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'memory_m6_001',
    scene_id,
    chapter_id,
    id,
    'OBJECTIVE',
    'SCENE_FACT',
    'scene',
    'scene_m6_001',
    'Memory written through the PG-primary smoke path.',
    'WRITER_VISIBLE',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    'm6_memory',
    'm6-memory-hash'
  FROM event_row
  RETURNING project_id
), backup AS (
  INSERT INTO backup_manifests (
    project_id, backup_manifest_id, backup_kind, source_root, artifact_root,
    file_count, object_count, manifest_hash,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    project_id,
    'backup_m6_json_export_001',
    'JSON_EXPORT',
    'postgres_primary',
    'json_export_fixture',
    1,
    8,
    'm6-json-export-manifest-hash',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm6_json_export',
    'm6-json-export-content-hash'
  FROM memory_row
  RETURNING id, project_id
), target_writes(repository_family, target_table, target_business_id, primary_write_id) AS (
  VALUES
    ('ProjectRepository', 'project_story_premises', 'premise_m6_001', 'm6_write_premise_001'),
    ('StoryBibleRepository', 'story_bibles', 'bible_m6_001', 'm6_write_bible_001'),
    ('WorldCanvasRepository', 'world_canvases', 'world_m6_001', 'm6_write_world_001'),
    ('CharacterRepository', 'characters', 'character_m6_001', 'm6_write_character_001'),
    ('ChapterRepository', 'chapters', 'chapter_m6_001', 'm6_write_chapter_001'),
    ('SceneRepository', 'scenes', 'scene_m6_001', 'm6_write_scene_001'),
    ('SceneDraftRepository', 'scene_drafts', 'draft_m6_001', 'm6_write_draft_001'),
    ('EventRepository', 'events', 'event_m6_001', 'm6_write_event_001'),
    ('MemoryRepository', 'memory_records', 'memory_m6_001', 'm6_write_memory_001')
), write_receipts AS (
  INSERT INTO postgres_primary_write_receipts (
    project_id, storage_assignment_id, backend_id, primary_write_id,
    repository_family, target_table, target_business_id,
    write_operation, write_result, idempotency_key, transaction_ref,
    json_export_required, backup_manifest_id,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    a.project_id,
    a.id,
    a.backend_id,
    tw.primary_write_id,
    tw.repository_family,
    tw.target_table,
    tw.target_business_id,
    'UPSERT',
    'ACCEPTED',
    concat('m6:', tw.primary_write_id),
    'm6_tx_001',
    true,
    b.id,
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'AGENT',
    tw.primary_write_id,
    concat('m6-write-', tw.target_table)
  FROM assignment a
  CROSS JOIN backup b
  CROSS JOIN target_writes tw
  RETURNING project_id
), readiness_kinds(readiness_check_id, check_kind, checked_table, checked_object_count) AS (
  VALUES
    ('m6_readiness_project_assignment', 'PROJECT_ASSIGNMENT', 'project_storage_assignments', 1),
    ('m6_readiness_route_factory', 'ROUTE_FACTORY', 'project_storage_assignments', 1),
    ('m6_readiness_core_generation_write', 'CORE_GENERATION_WRITE', 'postgres_primary_write_receipts', 9),
    ('m6_readiness_json_export_backup', 'JSON_EXPORT_BACKUP_PATH', 'backup_manifests', 1)
)
INSERT INTO postgres_primary_readiness_checks (
  project_id, readiness_check_id, storage_assignment_id, backend_id,
  check_kind, check_result, checked_table, checked_object_count, details,
  status, legacy_status_raw, lifecycle_state, authority_level,
  source_type, source_id, content_hash
)
SELECT
  a.project_id,
  rk.readiness_check_id,
  a.id,
  a.backend_id,
  rk.check_kind,
  'PASS',
  rk.checked_table,
  rk.checked_object_count,
  jsonb_build_object('storageMode', 'POSTGRES_PRIMARY', 'jsonExportPath', 'backup_manifests'),
  'CONFIRMED',
  'm6_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  rk.readiness_check_id,
  concat('m6-readiness-', lower(rk.check_kind))
FROM assignment a
CROSS JOIN readiness_kinds rk;

DO $$
DECLARE
  pg_project_id uuid;
  readiness_pass_count integer;
  write_receipt_count integer;
  backup_count integer;
BEGIN
  SELECT id INTO pg_project_id
  FROM projects
  WHERE project_id = 'project_m6_pg_primary_001'
    AND storage_mode = 'POSTGRES_PRIMARY';

  IF pg_project_id IS NULL THEN
    RAISE EXCEPTION 'Expected M6 PostgreSQL primary project to exist.';
  END IF;

  SELECT count(*)::integer INTO readiness_pass_count
  FROM postgres_primary_readiness_checks
  WHERE project_id = pg_project_id
    AND check_result = 'PASS';

  IF readiness_pass_count <> 4 THEN
    RAISE EXCEPTION 'Expected 4 M6 readiness PASS rows, got %.', readiness_pass_count;
  END IF;

  SELECT count(*)::integer INTO write_receipt_count
  FROM postgres_primary_write_receipts
  WHERE project_id = pg_project_id
    AND write_result = 'ACCEPTED';

  IF write_receipt_count <> 9 THEN
    RAISE EXCEPTION 'Expected 9 M6 primary write receipts, got %.', write_receipt_count;
  END IF;

  SELECT count(*)::integer INTO backup_count
  FROM backup_manifests
  WHERE project_id = pg_project_id
    AND backup_kind = 'JSON_EXPORT'
    AND status = 'CONFIRMED';

  IF backup_count <> 1 THEN
    RAISE EXCEPTION 'Expected one M6 JSON export backup manifest, got %.', backup_count;
  END IF;
END $$;

DO $$
DECLARE
  pg_project_id uuid;
  assignment_id uuid;
  json_backend_id uuid;
BEGIN
  SELECT id INTO pg_project_id FROM projects WHERE project_id = 'project_m6_pg_primary_001';
  SELECT id INTO assignment_id FROM project_storage_assignments WHERE project_id = pg_project_id AND mode = 'POSTGRES_PRIMARY';
  SELECT id INTO json_backend_id FROM storage_backends WHERE backend_id = 'm6_json_export_backend';

  BEGIN
    INSERT INTO postgres_primary_readiness_checks (
      project_id, readiness_check_id, storage_assignment_id, backend_id,
      check_kind, check_result, checked_table, checked_object_count,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      pg_project_id,
      'm6_invalid_readiness_backend_mismatch',
      assignment_id,
      json_backend_id,
      'PROJECT_ASSIGNMENT',
      'PASS',
      'project_storage_assignments',
      1,
      'CONFIRMED',
      'm6_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm6_invalid_readiness_backend_mismatch',
      'm6-invalid-readiness-backend-mismatch'
    );
    RAISE EXCEPTION 'Expected readiness backend_id mismatch rejection.';
  EXCEPTION
    WHEN foreign_key_violation THEN
      NULL;
  END;
END $$;

DO $$
DECLARE
  pg_project_id uuid;
  assignment_id uuid;
  json_backend_id uuid;
  backup_id uuid;
BEGIN
  SELECT id INTO pg_project_id FROM projects WHERE project_id = 'project_m6_pg_primary_001';
  SELECT id INTO assignment_id FROM project_storage_assignments WHERE project_id = pg_project_id AND mode = 'POSTGRES_PRIMARY';
  SELECT id INTO json_backend_id FROM storage_backends WHERE backend_id = 'm6_json_export_backend';
  SELECT id INTO backup_id FROM backup_manifests WHERE project_id = pg_project_id AND backup_manifest_id = 'backup_m6_json_export_001';

  BEGIN
    INSERT INTO postgres_primary_write_receipts (
      project_id, storage_assignment_id, backend_id, primary_write_id,
      repository_family, target_table, target_business_id,
      write_operation, write_result, idempotency_key, backup_manifest_id,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      pg_project_id,
      assignment_id,
      json_backend_id,
      'm6_invalid_write_receipt_backend_mismatch',
      'SceneRepository',
      'scenes',
      'scene_m6_001',
      'UPSERT',
      'ACCEPTED',
      'm6:invalid_write_receipt_backend_mismatch',
      backup_id,
      'CONFIRMED',
      'm6_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm6_invalid_write_receipt_backend_mismatch',
      'm6-invalid-write-receipt-backend-mismatch'
    );
    RAISE EXCEPTION 'Expected write receipt backend_id mismatch rejection.';
  EXCEPTION
    WHEN foreign_key_violation THEN
      NULL;
  END;
END $$;

WITH json_backend AS (
  SELECT id FROM storage_backends WHERE backend_id = 'm6_json_export_backend'
), invalid_project AS (
  INSERT INTO projects (project_id, display_name, storage_mode, status, legacy_status_raw, lifecycle_state, authority_level)
  VALUES (
    'project_m6_invalid_pg_on_json',
    'Invalid PG Primary On JSON Backend',
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED'
  )
  RETURNING id
)
SELECT 1;

DO $$
DECLARE
  invalid_project_id uuid;
  json_backend_id uuid;
BEGIN
  SELECT id INTO invalid_project_id FROM projects WHERE project_id = 'project_m6_invalid_pg_on_json';
  SELECT id INTO json_backend_id FROM storage_backends WHERE backend_id = 'm6_json_export_backend';

  BEGIN
    INSERT INTO project_storage_assignments (
      project_id, backend_id, mode,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      invalid_project_id,
      json_backend_id,
      'POSTGRES_PRIMARY',
      'CONFIRMED',
      'm6_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm6_invalid_pg_on_json',
      'm6-invalid-pg-on-json'
    );
    RAISE EXCEPTION 'Expected POSTGRES_PRIMARY assignment to JSON backend rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

WITH pg_backend AS (
  SELECT id FROM storage_backends WHERE backend_id = 'm6_postgres_backend'
), invalid_project AS (
  INSERT INTO projects (project_id, display_name, storage_mode, status, legacy_status_raw, lifecycle_state, authority_level)
  VALUES (
    'project_m6_invalid_assignment_activation_mismatch',
    'Invalid Assignment Activation Mode Mismatch',
    'JSON_PRIMARY',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED'
  )
  RETURNING id
), inactive_assignment AS (
  INSERT INTO project_storage_assignments (
    project_id, backend_id, mode,
    status, legacy_status_raw, lifecycle_state, deactivated_at, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    p.id,
    b.id,
    'POSTGRES_PRIMARY',
    'DRAFT',
    'm6_negative',
    'PROVISIONAL',
    now(),
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm6_invalid_assignment_activation_mismatch',
    'm6-invalid-assignment-activation-mismatch'
  FROM invalid_project p
  CROSS JOIN pg_backend b
  RETURNING id
)
SELECT 1;

DO $$
DECLARE
  inactive_assignment_id uuid;
BEGIN
  SELECT psa.id
  INTO inactive_assignment_id
  FROM project_storage_assignments psa
  JOIN projects p ON p.id = psa.project_id
  WHERE p.project_id = 'project_m6_invalid_assignment_activation_mismatch';

  BEGIN
    UPDATE project_storage_assignments
    SET
      status = 'CONFIRMED',
      lifecycle_state = 'ACTIVE',
      deactivated_at = NULL
    WHERE id = inactive_assignment_id;
    RAISE EXCEPTION 'Expected assignment activation mode mismatch rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

WITH pg_backend AS (
  SELECT id FROM storage_backends WHERE backend_id = 'm6_postgres_backend'
), invalid_project AS (
  INSERT INTO projects (project_id, display_name, storage_mode, status, legacy_status_raw, lifecycle_state, authority_level)
  VALUES (
    'project_m6_invalid_deleted_assignment_restore_mismatch',
    'Invalid Deleted Assignment Restore Mode Mismatch',
    'JSON_PRIMARY',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED'
  )
  RETURNING id
), deleted_assignment AS (
  INSERT INTO project_storage_assignments (
    project_id, backend_id, mode,
    status, legacy_status_raw, lifecycle_state, deactivated_at, deleted_at, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    p.id,
    b.id,
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm6_negative',
    'ACTIVE',
    NULL,
    now(),
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm6_invalid_deleted_assignment_restore_mismatch',
    'm6-invalid-deleted-assignment-restore-mismatch'
  FROM invalid_project p
  CROSS JOIN pg_backend b
  RETURNING id
)
SELECT 1;

DO $$
DECLARE
  deleted_assignment_id uuid;
BEGIN
  SELECT psa.id
  INTO deleted_assignment_id
  FROM project_storage_assignments psa
  JOIN projects p ON p.id = psa.project_id
  WHERE p.project_id = 'project_m6_invalid_deleted_assignment_restore_mismatch';

  BEGIN
    UPDATE project_storage_assignments
    SET deleted_at = NULL
    WHERE id = deleted_assignment_id;
    RAISE EXCEPTION 'Expected deleted assignment restore mode mismatch rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

WITH pg_backend AS (
  SELECT id FROM storage_backends WHERE backend_id = 'm6_postgres_backend'
), replacement_project AS (
  INSERT INTO projects (project_id, display_name, storage_mode, status, legacy_status_raw, lifecycle_state, authority_level)
  VALUES (
    'project_m6_soft_deleted_assignment_replacement',
    'Soft Deleted Assignment Replacement',
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED'
  )
  RETURNING id
), soft_deleted_assignment AS (
  INSERT INTO project_storage_assignments (
    project_id, backend_id, mode,
    status, legacy_status_raw, lifecycle_state, deleted_at, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    p.id,
    b.id,
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm6_positive',
    'ACTIVE',
    now(),
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm6_soft_deleted_assignment',
    'm6-soft-deleted-assignment'
  FROM replacement_project p
  CROSS JOIN pg_backend b
  RETURNING project_id
), active_replacement AS (
  INSERT INTO project_storage_assignments (
    project_id, backend_id, mode,
    status, legacy_status_raw, lifecycle_state, authority_level,
    source_type, source_id, content_hash
  )
  SELECT
    sda.project_id,
    b.id,
    'POSTGRES_PRIMARY',
    'CONFIRMED',
    'm6_positive',
    'ACTIVE',
    'SYSTEM_CONFIRMED',
    'SYSTEM',
    'm6_active_replacement_assignment',
    'm6-active-replacement-assignment'
  FROM soft_deleted_assignment sda
  CROSS JOIN pg_backend b
  RETURNING project_id
)
SELECT 1;

DO $$
DECLARE
  replacement_project_id uuid;
  active_assignment_count integer;
  soft_deleted_assignment_count integer;
BEGIN
  SELECT id
  INTO replacement_project_id
  FROM projects
  WHERE project_id = 'project_m6_soft_deleted_assignment_replacement';

  SELECT count(*)::integer
  INTO active_assignment_count
  FROM project_storage_assignments
  WHERE project_id = replacement_project_id
    AND lifecycle_state = 'ACTIVE'
    AND deactivated_at IS NULL
    AND deleted_at IS NULL
    AND status IN ('CONFIRMED', 'FORMAL_APPLIED');

  SELECT count(*)::integer
  INTO soft_deleted_assignment_count
  FROM project_storage_assignments
  WHERE project_id = replacement_project_id
    AND lifecycle_state = 'ACTIVE'
    AND deactivated_at IS NULL
    AND deleted_at IS NOT NULL
    AND status IN ('CONFIRMED', 'FORMAL_APPLIED');

  IF active_assignment_count <> 1 OR soft_deleted_assignment_count <> 1 THEN
    RAISE EXCEPTION 'Expected soft-deleted assignment replacement to be allowed.';
  END IF;
END $$;

DO $$
BEGIN
  BEGIN
    UPDATE projects
    SET storage_mode = 'JSON_PRIMARY'
    WHERE project_id = 'project_m6_pg_primary_001';
    RAISE EXCEPTION 'Expected project storage_mode update drift rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    UPDATE storage_backends
    SET backend_type = 'JSON'
    WHERE backend_id = 'm6_postgres_backend';
    RAISE EXCEPTION 'Expected backend_type drift rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    UPDATE storage_backends
    SET deleted_at = now()
    WHERE backend_id = 'm6_postgres_backend';
    RAISE EXCEPTION 'Expected active backend deletion rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

WITH pg_backend AS (
  SELECT id FROM storage_backends WHERE backend_id = 'm6_postgres_backend'
), invalid_project AS (
  INSERT INTO projects (project_id, display_name, storage_mode, status, legacy_status_raw, lifecycle_state, authority_level)
  VALUES (
    'project_m6_invalid_project_assignment_mode_mismatch',
    'Invalid Project Storage Mode Assignment Mismatch',
    'JSON_PRIMARY',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED'
  )
  RETURNING id
)
SELECT 1;

DO $$
DECLARE
  invalid_project_id uuid;
  pg_backend_id uuid;
BEGIN
  SELECT id INTO invalid_project_id FROM projects WHERE project_id = 'project_m6_invalid_project_assignment_mode_mismatch';
  SELECT id INTO pg_backend_id FROM storage_backends WHERE backend_id = 'm6_postgres_backend';

  BEGIN
    INSERT INTO project_storage_assignments (
      project_id, backend_id, mode,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      invalid_project_id,
      pg_backend_id,
      'POSTGRES_PRIMARY',
      'CONFIRMED',
      'm6_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm6_invalid_project_assignment_mode_mismatch',
      'm6-invalid-project-assignment-mode-mismatch'
    );
    RAISE EXCEPTION 'Expected active assignment mode to match project storage_mode rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

WITH pg_backend AS (
  SELECT id FROM storage_backends WHERE backend_id = 'm6_postgres_backend'
), invalid_project AS (
  INSERT INTO projects (project_id, display_name, storage_mode, status, legacy_status_raw, lifecycle_state, authority_level)
  VALUES (
    'project_m6_invalid_json_export_on_pg',
    'Invalid JSON Export On PostgreSQL Backend',
    'JSON_EXPORT_ONLY',
    'CONFIRMED',
    'm6_smoke',
    'ACTIVE',
    'USER_CONFIRMED'
  )
  RETURNING id
)
SELECT 1;

DO $$
DECLARE
  invalid_project_id uuid;
  pg_backend_id uuid;
BEGIN
  SELECT id INTO invalid_project_id FROM projects WHERE project_id = 'project_m6_invalid_json_export_on_pg';
  SELECT id INTO pg_backend_id FROM storage_backends WHERE backend_id = 'm6_postgres_backend';

  BEGIN
    INSERT INTO project_storage_assignments (
      project_id, backend_id, mode,
      status, legacy_status_raw, lifecycle_state, authority_level,
      source_type, source_id, content_hash
    )
    VALUES (
      invalid_project_id,
      pg_backend_id,
      'JSON_EXPORT_ONLY',
      'CONFIRMED',
      'm6_negative',
      'ACTIVE',
      'SYSTEM_CONFIRMED',
      'SYSTEM',
      'm6_invalid_json_export_on_pg',
      'm6-invalid-json-export-on-pg'
    );
    RAISE EXCEPTION 'Expected JSON_EXPORT_ONLY assignment to POSTGRES backend rejection.';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;
END $$;

ROLLBACK;
