-- Smoke checks for Phase 8.75 M5 shadow validation.
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
  'project_m5_smoke_001',
  'M5 Smoke Project',
  'zh',
  'POSTGRES_SHADOW',
  'DRAFT',
  'm5_smoke',
  'ACTIVE',
  'USER_CONFIRMED',
  'm5:project:001',
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
  'm5_smoke_batch_001',
  'C:\sample\local_project',
  'IMPORT',
  id,
  1,
  1,
  1,
  0,
  0,
  '{"mappedFiles":1}'::jsonb,
  'DRAFT',
  'm5_smoke',
  'ACTIVE',
  'MIGRATED_REFERENCE',
  'MIGRATION',
  'm5_smoke_batch_001',
  'batch_hash_m5'
FROM projects
WHERE project_id = 'project_m5_smoke_001'
ON CONFLICT (batch_id) DO UPDATE SET
  object_count = EXCLUDED.object_count,
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
  'file_hash_m5',
  'PARSED',
  'MAPPED',
  'narrative',
  'chapters',
  1,
  1,
  1,
  'chapter_id',
  '["chapter_m5_001"]'::jsonb,
  'DRAFT',
  'm5_smoke',
  'ACTIVE',
  'MIGRATED_REFERENCE',
  'MIGRATION',
  'chapters.json',
  'file_hash_m5'
FROM json_import_batches b
WHERE b.batch_id = 'm5_smoke_batch_001'
ON CONFLICT (batch_id, source_path) DO UPDATE SET
  mapped_object_count = EXCLUDED.mapped_object_count,
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
  'chapter_m5_001',
  '',
  'narrative',
  'chapters',
  'chapter_id',
  'MAPPED',
  'STAGE_ONLY',
  '{"chapter_id":"chapter_m5_001","title":"M5 smoke"}'::jsonb,
  f.source_hash,
  'object_hash_m5',
  'DRAFT',
  'm5_smoke',
  'ACTIVE',
  'MIGRATED_REFERENCE',
  'MIGRATION',
  'chapter_m5_001',
  jsonb_build_array(jsonb_build_object('source_path', f.source_path, 'source_hash', f.source_hash)),
  'm5:chapters.json:0'
FROM json_import_batches b
JOIN json_import_files f ON f.batch_id = b.id AND f.source_path = 'chapters.json'
WHERE b.batch_id = 'm5_smoke_batch_001'
ON CONFLICT (batch_id, source_path, source_index) DO UPDATE SET
  content_hash = EXCLUDED.content_hash,
  source_refs = EXCLUDED.source_refs,
  updated_at = now();

INSERT INTO shadow_validation_runs (
  project_id,
  shadow_run_id,
  import_batch_id,
  source_root,
  validation_mode,
  expected_object_count,
  postgres_object_count,
  mismatch_count,
  duplicate_write_count,
  result,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  source_refs,
  content_hash,
  completed_at
)
SELECT
  b.project_id,
  'm5_smoke_shadow_run_001',
  b.id,
  b.source_root,
  'SHADOW_IMPORT',
  1,
  1,
  0,
  0,
  'PASS',
  'CONFIRMED',
  'm5_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  'm5_smoke_shadow_run_001',
  jsonb_build_array(jsonb_build_object('batch_id', b.batch_id)),
  'run_hash_m5',
  now()
FROM json_import_batches b
WHERE b.batch_id = 'm5_smoke_batch_001'
ON CONFLICT (project_id, shadow_run_id) DO UPDATE SET
  postgres_object_count = EXCLUDED.postgres_object_count,
  mismatch_count = EXCLUDED.mismatch_count,
  result = EXCLUDED.result,
  completed_at = now(),
  updated_at = now();

INSERT INTO shadow_validation_domain_results (
  project_id,
  shadow_run_id,
  target_domain,
  target_table,
  expected_object_count,
  postgres_object_count,
  result,
  recommended_fix,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  content_hash
)
SELECT
  r.project_id,
  r.id,
  'narrative',
  'chapters',
  1,
  1,
  'PASS',
  'No action required.',
  'CONFIRMED',
  'm5_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  'm5_smoke_shadow_run_001:narrative:chapters',
  'domain_hash_m5'
FROM shadow_validation_runs r
WHERE r.shadow_run_id = 'm5_smoke_shadow_run_001'
ON CONFLICT (shadow_run_id, target_domain, target_table) DO UPDATE SET
  postgres_object_count = EXCLUDED.postgres_object_count,
  result = EXCLUDED.result,
  updated_at = now();

INSERT INTO shadow_write_receipts (
  project_id,
  shadow_run_id,
  shadow_write_receipt_id,
  idempotency_key,
  target_domain,
  target_table,
  source_business_id,
  generated_business_id,
  content_hash,
  write_mode,
  write_result,
  retry_count,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type,
  source_id,
  source_refs
)
SELECT
  r.project_id,
  r.id,
  'm5_smoke_receipt_001',
  'm5:shadow:receipt:001',
  'narrative',
  'chapters',
  'chapter_m5_001',
  '',
  'object_hash_m5',
  'SHADOW_WRITE',
  'ACCEPTED',
  0,
  'CONFIRMED',
  'm5_smoke',
  'ACTIVE',
  'SYSTEM_CONFIRMED',
  'SYSTEM',
  'chapter_m5_001',
  jsonb_build_array(jsonb_build_object('shadow_run_id', r.shadow_run_id))
FROM shadow_validation_runs r
WHERE r.shadow_run_id = 'm5_smoke_shadow_run_001'
ON CONFLICT (project_id, idempotency_key) DO UPDATE SET
  retry_count = shadow_write_receipts.retry_count + 1,
  write_result = 'RETRY_MERGED',
  last_attempted_at = now(),
  updated_at = now();

INSERT INTO shadow_write_receipts (
  project_id,
  shadow_run_id,
  shadow_write_receipt_id,
  idempotency_key,
  target_domain,
  target_table,
  content_hash,
  write_mode,
  write_result,
  retry_count
)
SELECT
  r.project_id,
  r.id,
  'm5_smoke_receipt_001_retry',
  'm5:shadow:receipt:001',
  'narrative',
  'chapters',
  'object_hash_m5',
  'SHADOW_WRITE',
  'ACCEPTED',
  0
FROM shadow_validation_runs r
WHERE r.shadow_run_id = 'm5_smoke_shadow_run_001'
ON CONFLICT (project_id, idempotency_key) DO UPDATE SET
  retry_count = shadow_write_receipts.retry_count + 1,
  write_result = 'RETRY_MERGED',
  last_attempted_at = now(),
  updated_at = now();

DO $$
DECLARE
  receipt_rows integer;
  receipt_retries integer;
BEGIN
  SELECT count(*), max(retry_count)
  INTO receipt_rows, receipt_retries
  FROM shadow_write_receipts
  WHERE idempotency_key = 'm5:shadow:receipt:001';

  IF receipt_rows <> 1 OR receipt_retries <> 1 THEN
    RAISE EXCEPTION 'Expected retry to merge into one shadow_write_receipts row';
  END IF;
END $$;

DO $$
BEGIN
  INSERT INTO shadow_write_receipts (
    project_id,
    shadow_run_id,
    shadow_write_receipt_id,
    idempotency_key,
    target_domain,
    target_table
  )
  SELECT
    r.project_id,
    r.id,
    'm5_smoke_receipt_duplicate',
    'm5:shadow:receipt:001',
    'narrative',
    'chapters'
  FROM shadow_validation_runs r
  WHERE r.shadow_run_id = 'm5_smoke_shadow_run_001';

  RAISE EXCEPTION 'Expected duplicate shadow_write_receipts idempotency rejection';
EXCEPTION
  WHEN unique_violation THEN
    RAISE NOTICE 'Expected duplicate shadow_write_receipts idempotency rejection';
END $$;

DO $$
BEGIN
  INSERT INTO shadow_validation_mismatches (
    project_id,
    shadow_run_id,
    shadow_mismatch_id,
    mismatch_category,
    severity,
    recommended_fix
  )
  SELECT
    r.project_id,
    r.id,
    'm5_bad_mismatch_category',
    'BAD_CATEGORY',
    'ERROR',
    'Use a supported mismatch category.'
  FROM shadow_validation_runs r
  WHERE r.shadow_run_id = 'm5_smoke_shadow_run_001';

  RAISE EXCEPTION 'Expected invalid shadow mismatch category CHECK rejection';
EXCEPTION
  WHEN check_violation THEN
    RAISE NOTICE 'Expected invalid shadow mismatch category CHECK rejection';
END $$;

INSERT INTO projects (
  project_id,
  display_name,
  language,
  storage_mode,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  source_type
) VALUES (
  'project_m5_smoke_other',
  'M5 Other Project',
  'zh',
  'POSTGRES_SHADOW',
  'DRAFT',
  'm5_smoke_other',
  'ACTIVE',
  'USER_CONFIRMED',
  'SYSTEM'
)
ON CONFLICT (project_id) DO UPDATE SET updated_at = now();

DO $$
BEGIN
  INSERT INTO shadow_validation_domain_results (
    project_id,
    shadow_run_id,
    target_domain,
    target_table,
    expected_object_count,
    postgres_object_count
  )
  SELECT
    p_other.id,
    r.id,
    'narrative',
    'events',
    1,
    1
  FROM shadow_validation_runs r
  CROSS JOIN projects p_other
  WHERE r.shadow_run_id = 'm5_smoke_shadow_run_001'
    AND p_other.project_id = 'project_m5_smoke_other';

  RAISE EXCEPTION 'Expected cross-project shadow domain result FK rejection';
EXCEPTION
  WHEN foreign_key_violation THEN
    RAISE NOTICE 'Expected cross-project shadow domain result FK rejection';
END $$;

ROLLBACK;
