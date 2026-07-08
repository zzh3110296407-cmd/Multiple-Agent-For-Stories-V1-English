-- Smoke checks for Phase 8.75 M4 JSON import admin and staging.
-- The data writes are rolled back; schema objects remain from migrations.

\set ON_ERROR_STOP on

SET search_path TO mas_phase875_proto;

BEGIN;

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
  'project_m4_smoke_001',
  'M4 Smoke Project',
  'zh',
  'POSTGRES_SHADOW',
  'DRAFT',
  'm4_smoke',
  'ACTIVE',
  'USER_CONFIRMED',
  'm4:project:001',
  'SYSTEM'
)
ON CONFLICT (project_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  updated_at = now();

INSERT INTO json_import_batches (
  batch_id,
  source_root,
  mode,
  project_id,
  file_count,
  object_count,
  mapped_file_count,
  unmapped_file_count,
  parse_error_count,
  mapping_report,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  content_hash
)
SELECT
  'm4_smoke_batch_001',
  './sample/local_project',
  'IMPORT',
  id,
  2,
  1,
  1,
  1,
  0,
  '{"mappedFiles":1,"unmappedFiles":1}'::jsonb,
  'DRAFT',
  'm4_smoke',
  'ACTIVE',
  'MIGRATED_REFERENCE',
  'MIGRATION',
  'm4_smoke_batch_001',
  'batch_hash'
FROM projects
WHERE project_id = 'project_m4_smoke_001'
ON CONFLICT (batch_id) DO UPDATE SET
  file_count = EXCLUDED.file_count,
  object_count = EXCLUDED.object_count,
  mapped_file_count = EXCLUDED.mapped_file_count,
  unmapped_file_count = EXCLUDED.unmapped_file_count,
  parse_error_count = EXCLUDED.parse_error_count,
  mapping_report = EXCLUDED.mapping_report,
  updated_at = now();

INSERT INTO json_import_files (
  batch_id,
  source_path,
  source_hash,
  parse_status,
  mapping_status,
  target_domain,
  target_table,
  row_count,
  source_object_count,
  mapped_object_count,
  unmapped_reason,
  id_field,
  sample_source_ids,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  content_hash
)
SELECT
  b.id,
  'chapters.json',
  'file_hash_chapters',
  'PARSED',
  'MAPPED',
  'narrative',
  'chapters',
  1,
  1,
  1,
  '',
  'chapter_id',
  '["chapter_m4_001"]'::jsonb,
  'DRAFT',
  'm4_smoke',
  'ACTIVE',
  'MIGRATED_REFERENCE',
  'MIGRATION',
  'chapters.json',
  'file_hash_chapters'
FROM json_import_batches b
WHERE b.batch_id = 'm4_smoke_batch_001'
ON CONFLICT (batch_id, source_path) DO UPDATE SET
  row_count = EXCLUDED.row_count,
  source_object_count = EXCLUDED.source_object_count,
  mapped_object_count = EXCLUDED.mapped_object_count,
  mapping_status = EXCLUDED.mapping_status,
  updated_at = now();

INSERT INTO json_import_files (
  batch_id,
  source_path,
  source_hash,
  parse_status,
  mapping_status,
  target_domain,
  target_table,
  row_count,
  source_object_count,
  mapped_object_count,
  unmapped_reason,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  content_hash
)
SELECT
  b.id,
  'plugin_manifests.json',
  'file_hash_plugins',
  'PARSED',
  'UNMAPPED',
  '',
  '',
  0,
  3,
  0,
  'No M4 repository mapping.',
  'DRAFT',
  'm4_smoke',
  'ACTIVE',
  'MIGRATED_REFERENCE',
  'MIGRATION',
  'plugin_manifests.json',
  'file_hash_plugins'
FROM json_import_batches b
WHERE b.batch_id = 'm4_smoke_batch_001'
ON CONFLICT (batch_id, source_path) DO UPDATE SET
  source_object_count = EXCLUDED.source_object_count,
  unmapped_reason = EXCLUDED.unmapped_reason,
  updated_at = now();

INSERT INTO json_import_mapped_objects (
  batch_id,
  file_id,
  project_id,
  source_path,
  source_index,
  source_business_id,
  generated_business_id,
  target_domain,
  target_table,
  id_field,
  mapping_status,
  import_action,
  source_payload,
  source_hash,
  content_hash,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  source_refs,
  idempotency_key
)
SELECT
  b.id,
  f.id,
  b.project_id,
  f.source_path,
  0,
  'chapter_m4_001',
  '',
  'narrative',
  'chapters',
  'chapter_id',
  'MAPPED',
  'STAGE_ONLY',
  '{"chapter_id":"chapter_m4_001","title":"M4 smoke"}'::jsonb,
  f.source_hash,
  'object_hash_chapter',
  'DRAFT',
  'm4_smoke',
  'ACTIVE',
  'MIGRATED_REFERENCE',
  'MIGRATION',
  'chapter_m4_001',
  jsonb_build_array(jsonb_build_object('source_path', f.source_path, 'source_hash', f.source_hash)),
  'm4:chapters.json:0'
FROM json_import_batches b
JOIN json_import_files f ON f.batch_id = b.id AND f.source_path = 'chapters.json'
WHERE b.batch_id = 'm4_smoke_batch_001'
ON CONFLICT (batch_id, source_path, source_index) DO UPDATE SET
  source_payload = EXCLUDED.source_payload,
  content_hash = EXCLUDED.content_hash,
  updated_at = now();

INSERT INTO json_import_domain_summaries (
  batch_id,
  project_id,
  target_domain,
  target_table,
  source_file_count,
  source_object_count,
  mapped_object_count,
  imported_object_count,
  unmapped_object_count,
  parse_error_count,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  content_hash
)
SELECT
  b.id,
  b.project_id,
  'narrative',
  'chapters',
  1,
  1,
  1,
  1,
  0,
  0,
  'DRAFT',
  'm4_smoke',
  'ACTIVE',
  'MIGRATED_REFERENCE',
  'MIGRATION',
  'm4_smoke_batch_001:narrative:chapters',
  'summary_hash'
FROM json_import_batches b
WHERE b.batch_id = 'm4_smoke_batch_001'
ON CONFLICT (batch_id, target_domain, target_table) DO UPDATE SET
  source_file_count = EXCLUDED.source_file_count,
  source_object_count = EXCLUDED.source_object_count,
  mapped_object_count = EXCLUDED.mapped_object_count,
  imported_object_count = EXCLUDED.imported_object_count,
  updated_at = now();

INSERT INTO storage_consistency_reports (
  report_id,
  project_id,
  batch_id,
  report_kind,
  result,
  checked_object_count,
  mismatch_count,
  mismatches,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  content_hash
)
SELECT
  'm4_smoke_mapping_report_001',
  b.project_id,
  b.id,
  'MAPPING',
  'MAPPED_WITH_UNMAPPED',
  1,
  1,
  '[{"source_path":"plugin_manifests.json","reason":"No M4 repository mapping."}]'::jsonb,
  'CONFIRMED',
  'm4_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  'm4_smoke_batch_001',
  'report_hash'
FROM json_import_batches b
WHERE b.batch_id = 'm4_smoke_batch_001'
ON CONFLICT (report_id) DO UPDATE SET
  result = EXCLUDED.result,
  checked_object_count = EXCLUDED.checked_object_count,
  mismatch_count = EXCLUDED.mismatch_count,
  mismatches = EXCLUDED.mismatches,
  updated_at = now();

INSERT INTO backup_manifests (
  project_id,
  backup_manifest_id,
  backup_kind,
  source_batch_id,
  source_root,
  artifact_root,
  file_count,
  object_count,
  manifest_hash,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  content_hash
)
SELECT
  b.project_id,
  'backup_m4_smoke_001',
  'PRE_IMPORT_BACKUP',
  b.id,
  b.source_root,
  './sample/backup',
  2,
  1,
  'backup_manifest_hash',
  'DRAFT',
  'm4_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  'backup_m4_smoke_001',
  'backup_manifest_hash'
FROM json_import_batches b
WHERE b.batch_id = 'm4_smoke_batch_001'
ON CONFLICT (project_id, backup_manifest_id) DO UPDATE SET
  file_count = EXCLUDED.file_count,
  object_count = EXCLUDED.object_count,
  updated_at = now();

INSERT INTO storage_health_checks (
  project_id,
  health_check_id,
  check_kind,
  check_result,
  checked_table,
  checked_object_count,
  issue_count,
  issues,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  content_hash
)
SELECT
  b.project_id,
  'health_m4_smoke_001',
  'IMPORT_BATCH',
  'WARN',
  'json_import_files',
  2,
  1,
  '[{"source_path":"plugin_manifests.json","status":"UNMAPPED"}]'::jsonb,
  'DRAFT',
  'm4_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  'health_m4_smoke_001',
  'health_hash'
FROM json_import_batches b
WHERE b.batch_id = 'm4_smoke_batch_001'
ON CONFLICT (project_id, health_check_id) DO UPDATE SET
  check_result = EXCLUDED.check_result,
  checked_object_count = EXCLUDED.checked_object_count,
  issue_count = EXCLUDED.issue_count,
  issues = EXCLUDED.issues,
  updated_at = now();

DO $$
BEGIN
  INSERT INTO json_import_files (
    batch_id,
    source_path,
    source_hash,
    parse_status,
    mapping_status
  )
  SELECT
    id,
    'bad_mapping_status.json',
    'bad_hash',
    'PARSED',
    'BAD_STATUS'
  FROM json_import_batches
  WHERE batch_id = 'm4_smoke_batch_001';

  RAISE EXCEPTION 'Expected invalid json_import_files mapping_status CHECK rejection';
EXCEPTION
  WHEN check_violation THEN
    RAISE NOTICE 'Expected invalid json_import_files mapping_status CHECK rejection';
END $$;

DO $$
BEGIN
  INSERT INTO json_import_mapped_objects (
    batch_id,
    file_id,
    project_id,
    source_path,
    source_index,
    source_business_id,
    target_domain,
    target_table,
    source_payload,
    source_hash,
    content_hash
  )
  SELECT
    b.id,
    f.id,
    b.project_id,
    f.source_path,
    0,
    'chapter_m4_001',
    'narrative',
    'chapters',
    '{"chapter_id":"chapter_m4_001"}'::jsonb,
    f.source_hash,
    'duplicate_hash'
  FROM json_import_batches b
  JOIN json_import_files f ON f.batch_id = b.id AND f.source_path = 'chapters.json'
  WHERE b.batch_id = 'm4_smoke_batch_001';

  RAISE EXCEPTION 'Expected duplicate json_import_mapped_objects source rejection';
EXCEPTION
  WHEN unique_violation THEN
    RAISE NOTICE 'Expected duplicate json_import_mapped_objects source rejection';
END $$;

ROLLBACK;
