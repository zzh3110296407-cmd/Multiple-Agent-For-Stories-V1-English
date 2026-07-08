-- Phase 9 M10 Task 5: Temporal Resolver reader-disclosure hardening.
-- Adds sortable Tn columns so location state and location delta disclosure
-- can use revealed_to_reader_at <= Tn without unsafe text ordering.

\if :{?migration_checksum_sha256}
\else
\set migration_checksum_sha256 'prototype-not-computed'
\endif

SET search_path TO mas_phase875_proto, public;

ALTER TABLE location_state_nodes
  ADD COLUMN IF NOT EXISTS revealed_to_reader_at_sort_key bigint;

ALTER TABLE location_change_deltas
  ADD COLUMN IF NOT EXISTS revealed_to_reader_at_sort_key bigint;

CREATE INDEX IF NOT EXISTS ix_location_state_nodes_reader_disclosure
  ON location_state_nodes (
    project_id,
    revealed_to_reader_at_sort_key,
    visibility_status,
    authority_level,
    status
  )
  WHERE deleted_at IS NULL
    AND superseded_by_id IS NULL
    AND revealed_to_reader_at_sort_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_location_change_deltas_reader_disclosure
  ON location_change_deltas (
    project_id,
    revealed_to_reader_at_sort_key,
    visibility_status,
    authority_level,
    status
  )
  WHERE deleted_at IS NULL
    AND superseded_by_id IS NULL
    AND revealed_to_reader_at_sort_key IS NOT NULL;

INSERT INTO schema_migrations (migration_name, checksum_sha256, status)
VALUES ('018_phase9_m10_temporal_resolver_reader_disclosure_hardening', :'migration_checksum_sha256', 'APPLIED')
ON CONFLICT (migration_name)
DO UPDATE SET
  checksum_sha256 = EXCLUDED.checksum_sha256,
  status = EXCLUDED.status,
  applied_at = now();
