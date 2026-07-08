"""M5 shadow validation planner and SQL renderer.

This module is a Database-session prototype. It reads the M4 import report and
generates SQL that compares JSON-derived expectations with PostgreSQL
admin/staging rows. It does not connect to PostgreSQL and does not modify the
main backend runtime.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from storage_foundation.json_import_runner import sql_jsonb, sql_literal, stable_json_hash


DEFAULT_DATE_STAMP = "2026-07-04"
SHADOW_VALIDATION_MODE = "SHADOW_IMPORT"


MISMATCH_CATEGORIES = [
    "DOMAIN_COUNT_MISMATCH",
    "MISSING_POSTGRES_OBJECT",
    "EXTRA_POSTGRES_OBJECT",
    "CONTENT_HASH_MISMATCH",
    "STATUS_DRIFT",
    "LIFECYCLE_DRIFT",
    "SOURCE_REF_MISSING",
    "DUPLICATE_IDEMPOTENCY_KEY",
    "FK_REFERENCE_MISSING",
    "ORDER_DRIFT",
    "CURRENT_POINTER_INVALID",
    "PROJECT_ID_MISSING",
]


@dataclass(frozen=True)
class ShadowDomainExpectation:
    target_domain: str
    target_table: str
    expected_object_count: int
    source_file_count: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.target_domain, self.target_table)

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "targetDomain": self.target_domain,
            "targetTable": self.target_table,
            "expectedObjectCount": self.expected_object_count,
            "sourceFileCount": self.source_file_count,
        }


@dataclass
class ShadowValidationPlan:
    shadow_run_id: str
    import_batch_id: str
    project_business_id: str
    source_root: str
    m4_report_path: Path
    expected_file_count: int
    expected_object_count: int
    mapped_file_count: int
    unmapped_file_count: int
    parse_error_count: int
    domain_expectations: list[ShadowDomainExpectation]
    created_at: str

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "shadowRunId": self.shadow_run_id,
            "validationMode": SHADOW_VALIDATION_MODE,
            "importBatchId": self.import_batch_id,
            "projectBusinessId": self.project_business_id,
            "sourceRoot": self.source_root,
            "m4ReportPath": str(self.m4_report_path),
            "createdAt": self.created_at,
            "totals": {
                "expectedFileCount": self.expected_file_count,
                "mappedFileCount": self.mapped_file_count,
                "unmappedFileCount": self.unmapped_file_count,
                "parseErrorCount": self.parse_error_count,
                "expectedObjectCount": self.expected_object_count,
                "domainCount": len(self.domain_expectations),
            },
            "domainExpectations": [item.to_report_dict() for item in self.domain_expectations],
            "mismatchCategories": MISMATCH_CATEGORIES,
            "status": "SQL_GENERATED",
            "note": "Live PASS/FAIL is determined by the generated SQL against PostgreSQL staging rows.",
        }


def load_m4_import_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("M4 import report root must be an object.")
    if not payload.get("batchId"):
        raise ValueError("M4 import report is missing batchId.")
    if payload.get("mode") != "IMPORT":
        raise ValueError("M5 shadow validation requires an M4 IMPORT report.")
    return payload


def build_shadow_validation_plan(
    report_path: Path,
    *,
    shadow_run_id: str | None = None,
) -> ShadowValidationPlan:
    report = load_m4_import_report(report_path)
    totals = report.get("totals") or {}
    domain_summaries = report.get("domainSummaries") or []
    if not isinstance(domain_summaries, list):
        raise ValueError("M4 import report domainSummaries must be a list.")

    expectations = [
        ShadowDomainExpectation(
            target_domain=str(item.get("targetDomain") or ""),
            target_table=str(item.get("targetTable") or ""),
            expected_object_count=int(item.get("mappedObjectCount") or 0),
            source_file_count=int(item.get("sourceFileCount") or 0),
        )
        for item in domain_summaries
        if isinstance(item, dict)
    ]
    expectations = [
        item
        for item in expectations
        if item.target_domain and item.target_table
    ]

    active_shadow_run_id = shadow_run_id or f"m5_shadow_{report['batchId']}"
    return ShadowValidationPlan(
        shadow_run_id=active_shadow_run_id,
        import_batch_id=str(report["batchId"]),
        project_business_id=str(report.get("projectBusinessId") or ""),
        source_root=str(report.get("sourceRoot") or ""),
        m4_report_path=report_path.resolve(),
        expected_file_count=int(totals.get("fileCount") or 0),
        expected_object_count=int(totals.get("objectCount") or 0),
        mapped_file_count=int(totals.get("mappedFileCount") or 0),
        unmapped_file_count=int(totals.get("unmappedFileCount") or 0),
        parse_error_count=int(totals.get("parseErrorCount") or 0),
        domain_expectations=sorted(expectations, key=lambda item: item.key),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def compare_domain_summaries(
    expected: list[ShadowDomainExpectation],
    observed_counts: dict[tuple[str, str], int],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for item in expected:
        observed = int(observed_counts.get(item.key, 0))
        if observed == item.expected_object_count:
            continue
        mismatches.append(
            {
                "mismatchCategory": "DOMAIN_COUNT_MISMATCH",
                "targetDomain": item.target_domain,
                "targetTable": item.target_table,
                "expectedObjectCount": item.expected_object_count,
                "postgresObjectCount": observed,
                "recommendedFix": "Re-run M4 import SQL for this batch, then rerun M5 shadow validation.",
            }
        )
    return mismatches


def render_shadow_validation_sql(plan: ShadowValidationPlan) -> str:
    report_payload = plan.to_report_dict()
    report_hash = stable_json_hash(report_payload)
    lines = [
        "-- Generated by storage_foundation.shadow_validator.",
        "-- M5 shadow validation compares M4 expected semantic counts with PostgreSQL staging rows.",
        "\\set ON_ERROR_STOP on",
        "SET search_path TO mas_phase875_proto;",
        "",
        "BEGIN;",
        "",
        "INSERT INTO shadow_validation_runs (",
        "  project_id, shadow_run_id, import_batch_id, source_root, validation_mode,",
        "  expected_object_count, postgres_object_count, mismatch_count, duplicate_write_count, result,",
        "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, source_refs, content_hash",
        ")",
        "SELECT",
        "  b.project_id,",
        f"  {sql_literal(plan.shadow_run_id)},",
        "  b.id,",
        "  b.source_root,",
        "  'SHADOW_IMPORT',",
        f"  {plan.expected_object_count},",
        "  0,",
        "  0,",
        "  0,",
        "  'PENDING',",
        "  'DRAFT',",
        "  'm5_shadow_validation',",
        "  'ACTIVE',",
        "  'SYSTEM_CONFIRMED',",
        "  'SYSTEM',",
        f"  {sql_literal(plan.shadow_run_id)},",
        f"  {sql_jsonb([{'m4ReportPath': str(plan.m4_report_path), 'importBatchId': plan.import_batch_id}])},",
        f"  {sql_literal(report_hash)}",
        "FROM json_import_batches b",
        f"WHERE b.batch_id = {sql_literal(plan.import_batch_id)}",
        "ON CONFLICT (project_id, shadow_run_id) DO UPDATE SET",
        "  import_batch_id = EXCLUDED.import_batch_id,",
        "  source_root = EXCLUDED.source_root,",
        "  expected_object_count = EXCLUDED.expected_object_count,",
        "  result = 'PENDING',",
        "  source_refs = EXCLUDED.source_refs,",
        "  content_hash = EXCLUDED.content_hash,",
        "  updated_at = now();",
        "",
    ]

    for expectation in plan.domain_expectations:
        lines.extend(render_domain_result_insert(plan, expectation))
        lines.append("")

    lines.extend(render_clear_shadow_mismatches(plan))
    lines.append("")
    lines.extend(render_domain_count_mismatch_insert(plan))
    lines.append("")
    for mismatch_category, count_column, expected_label, observed_label, fix in [
        (
            "CONTENT_HASH_MISMATCH",
            "content_hash_mismatch_count",
            "non_empty_content_hash",
            "empty_content_hash_count",
            "Regenerate M4 mapped object content hashes, rerun M4 import SQL, then rerun M5 shadow validation.",
        ),
        (
            "STATUS_DRIFT",
            "status_mismatch_count",
            "DRAFT",
            "non_draft_status_count",
            "Restore M4 staging rows to canonical DRAFT status, then rerun M5 shadow validation.",
        ),
        (
            "LIFECYCLE_DRIFT",
            "lifecycle_mismatch_count",
            "ACTIVE",
            "non_active_lifecycle_count",
            "Restore M4 staging rows to ACTIVE lifecycle state, then rerun M5 shadow validation.",
        ),
        (
            "SOURCE_REF_MISSING",
            "source_ref_mismatch_count",
            "non_empty_source_refs_array",
            "missing_or_invalid_source_ref_count",
            "Regenerate M4 source_refs for mapped objects, rerun M4 import SQL, then rerun M5 shadow validation.",
        ),
    ]:
        lines.extend(
            render_domain_metric_mismatch_insert(
                plan,
                mismatch_category=mismatch_category,
                count_column=count_column,
                expected_label=expected_label,
                observed_label=observed_label,
                recommended_fix=fix,
            )
        )
        lines.append("")
    lines.extend(render_shadow_write_receipts_insert(plan))
    lines.append("")
    lines.extend(render_duplicate_idempotency_mismatch_insert(plan))
    lines.append("")
    lines.extend(render_run_update(plan))
    lines.append("")
    lines.extend(render_storage_consistency_insert(plan))
    lines.append("")
    lines.extend(render_storage_health_insert(plan))
    lines.extend(["", "COMMIT;", ""])
    lines.extend(render_result_assertion(plan))
    lines.append("")
    return "\n".join(lines)


def render_domain_result_insert(plan: ShadowValidationPlan, expectation: ShadowDomainExpectation) -> list[str]:
    recommended_fix = "No action required."
    fail_fix = "Re-run M4 import SQL for this batch, then rerun M5 shadow validation."
    return [
        "WITH run_ref AS (",
        "  SELECT r.id AS shadow_run_uuid, r.project_id, r.import_batch_id",
        "  FROM shadow_validation_runs r",
        f"  WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        "), observed AS (",
        "  SELECT",
        "    count(o.id)::integer AS postgres_object_count,",
        "    count(o.id) FILTER (WHERE o.id IS NOT NULL AND o.content_hash = '')::integer AS content_hash_mismatch_count,",
        "    count(o.id) FILTER (WHERE o.id IS NOT NULL AND (o.source_refs = '[]'::jsonb OR jsonb_typeof(o.source_refs) <> 'array'))::integer AS source_ref_mismatch_count,",
        "    count(o.id) FILTER (WHERE o.id IS NOT NULL AND o.status <> 'DRAFT')::integer AS status_mismatch_count,",
        "    count(o.id) FILTER (WHERE o.id IS NOT NULL AND o.lifecycle_state <> 'ACTIVE')::integer AS lifecycle_mismatch_count",
        "  FROM run_ref rr",
        "  LEFT JOIN json_import_mapped_objects o",
        "    ON o.batch_id = rr.import_batch_id",
        f"   AND o.target_domain = {sql_literal(expectation.target_domain)}",
        f"   AND o.target_table = {sql_literal(expectation.target_table)}",
        "   AND o.project_id = rr.project_id",
        "   AND o.deleted_at IS NULL",
        ")",
        "INSERT INTO shadow_validation_domain_results (",
        "  project_id, shadow_run_id, target_domain, target_table, expected_object_count, postgres_object_count,",
        "  missing_in_postgres_count, extra_in_postgres_count, content_hash_mismatch_count, status_mismatch_count,",
        "  lifecycle_mismatch_count, source_ref_mismatch_count, duplicate_idempotency_count, result, recommended_fix,",
        "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, source_refs, content_hash",
        ")",
        "SELECT",
        "  rr.project_id,",
        "  rr.shadow_run_uuid,",
        f"  {sql_literal(expectation.target_domain)},",
        f"  {sql_literal(expectation.target_table)},",
        f"  {expectation.expected_object_count},",
        "  o.postgres_object_count,",
        f"  greatest({expectation.expected_object_count} - o.postgres_object_count, 0),",
        f"  greatest(o.postgres_object_count - {expectation.expected_object_count}, 0),",
        "  o.content_hash_mismatch_count,",
        "  o.status_mismatch_count,",
        "  o.lifecycle_mismatch_count,",
        "  o.source_ref_mismatch_count,",
        "  0,",
        "  CASE",
        f"    WHEN o.postgres_object_count = {expectation.expected_object_count}",
        "     AND o.content_hash_mismatch_count = 0",
        "     AND o.status_mismatch_count = 0",
        "     AND o.lifecycle_mismatch_count = 0",
        "     AND o.source_ref_mismatch_count = 0 THEN 'PASS'",
        "    ELSE 'FAIL'",
        "  END,",
        "  CASE",
        f"    WHEN o.postgres_object_count = {expectation.expected_object_count}",
        "     AND o.content_hash_mismatch_count = 0",
        "     AND o.status_mismatch_count = 0",
        "     AND o.lifecycle_mismatch_count = 0",
        f"     AND o.source_ref_mismatch_count = 0 THEN {sql_literal(recommended_fix)}",
        f"    ELSE {sql_literal(fail_fix)}",
        "  END,",
        "  'DRAFT',",
        "  'm5_shadow_validation',",
        "  'ACTIVE',",
        "  'SYSTEM_CONFIRMED',",
        "  'SYSTEM',",
        f"  {sql_literal(plan.shadow_run_id + ':' + expectation.target_domain + ':' + expectation.target_table)},",
        "  jsonb_build_array(jsonb_build_object('import_batch_id', rr.import_batch_id, 'target_domain', " + sql_literal(expectation.target_domain) + ", 'target_table', " + sql_literal(expectation.target_table) + ")),",
        f"  {sql_literal(stable_json_hash(expectation.to_report_dict()))}",
        "FROM run_ref rr",
        "CROSS JOIN observed o",
        "ON CONFLICT (shadow_run_id, target_domain, target_table) DO UPDATE SET",
        "  expected_object_count = EXCLUDED.expected_object_count,",
        "  postgres_object_count = EXCLUDED.postgres_object_count,",
        "  missing_in_postgres_count = EXCLUDED.missing_in_postgres_count,",
        "  extra_in_postgres_count = EXCLUDED.extra_in_postgres_count,",
        "  content_hash_mismatch_count = EXCLUDED.content_hash_mismatch_count,",
        "  status_mismatch_count = EXCLUDED.status_mismatch_count,",
        "  lifecycle_mismatch_count = EXCLUDED.lifecycle_mismatch_count,",
        "  source_ref_mismatch_count = EXCLUDED.source_ref_mismatch_count,",
        "  result = EXCLUDED.result,",
        "  recommended_fix = EXCLUDED.recommended_fix,",
        "  updated_at = now();",
    ]


def render_domain_count_mismatch_insert(plan: ShadowValidationPlan) -> list[str]:
    return [
        "INSERT INTO shadow_validation_mismatches (",
        "  project_id, shadow_run_id, shadow_mismatch_id, mismatch_category, severity, target_domain, target_table,",
        "  expected_value, postgres_value, recommended_fix, status, legacy_status_raw, lifecycle_state,",
        "  authority_level, source_type, source_id, source_refs, content_hash",
        ")",
        "SELECT",
        "  d.project_id,",
        "  d.shadow_run_id,",
        "  concat('m5:', r.shadow_run_id, ':', d.target_domain, ':', d.target_table, ':domain_count'),",
        "  'DOMAIN_COUNT_MISMATCH',",
        "  'ERROR',",
        "  d.target_domain,",
        "  d.target_table,",
        "  jsonb_build_object('expectedObjectCount', d.expected_object_count),",
        "  jsonb_build_object('postgresObjectCount', d.postgres_object_count),",
        "  d.recommended_fix,",
        "  'DRAFT',",
        "  'm5_shadow_validation',",
        "  'ACTIVE',",
        "  'SYSTEM_CONFIRMED',",
        "  'SYSTEM',",
        "  concat(r.shadow_run_id, ':', d.target_domain, ':', d.target_table),",
        "  jsonb_build_array(jsonb_build_object('domain_result_id', d.id)),",
        "  d.content_hash",
        "FROM shadow_validation_domain_results d",
        "JOIN shadow_validation_runs r ON r.id = d.shadow_run_id AND r.project_id = d.project_id",
        f"WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        "  AND (d.missing_in_postgres_count > 0 OR d.extra_in_postgres_count > 0)",
        "ON CONFLICT (project_id, shadow_mismatch_id) DO UPDATE SET",
        "  expected_value = EXCLUDED.expected_value,",
        "  postgres_value = EXCLUDED.postgres_value,",
        "  recommended_fix = EXCLUDED.recommended_fix,",
        "  updated_at = now();",
    ]


def render_clear_shadow_mismatches(plan: ShadowValidationPlan) -> list[str]:
    return [
        "DELETE FROM shadow_validation_mismatches m",
        "USING shadow_validation_runs r",
        "WHERE m.shadow_run_id = r.id",
        "  AND m.project_id = r.project_id",
        f"  AND r.shadow_run_id = {sql_literal(plan.shadow_run_id)};",
    ]


def render_domain_metric_mismatch_insert(
    plan: ShadowValidationPlan,
    *,
    mismatch_category: str,
    count_column: str,
    expected_label: str,
    observed_label: str,
    recommended_fix: str,
) -> list[str]:
    suffix = mismatch_category.lower()
    return [
        "INSERT INTO shadow_validation_mismatches (",
        "  project_id, shadow_run_id, shadow_mismatch_id, mismatch_category, severity, target_domain, target_table,",
        "  expected_value, postgres_value, recommended_fix, status, legacy_status_raw, lifecycle_state,",
        "  authority_level, source_type, source_id, source_refs, content_hash",
        ")",
        "SELECT",
        "  d.project_id,",
        "  d.shadow_run_id,",
        f"  concat('m5:', r.shadow_run_id, ':', d.target_domain, ':', d.target_table, ':{suffix}'),",
        f"  {sql_literal(mismatch_category)},",
        "  'ERROR',",
        "  d.target_domain,",
        "  d.target_table,",
        f"  jsonb_build_object('expected', {sql_literal(expected_label)}, 'requiredMismatchCount', 0),",
        f"  jsonb_build_object({sql_literal(observed_label)}, d.{count_column}),",
        f"  {sql_literal(recommended_fix)},",
        "  'DRAFT',",
        "  'm5_shadow_validation',",
        "  'ACTIVE',",
        "  'SYSTEM_CONFIRMED',",
        "  'SYSTEM',",
        f"  concat(r.shadow_run_id, ':', d.target_domain, ':', d.target_table, ':{suffix}'),",
        "  jsonb_build_array(jsonb_build_object('domain_result_id', d.id)),",
        "  d.content_hash",
        "FROM shadow_validation_domain_results d",
        "JOIN shadow_validation_runs r ON r.id = d.shadow_run_id AND r.project_id = d.project_id",
        f"WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        f"  AND d.{count_column} > 0",
        "ON CONFLICT (project_id, shadow_mismatch_id) DO UPDATE SET",
        "  expected_value = EXCLUDED.expected_value,",
        "  postgres_value = EXCLUDED.postgres_value,",
        "  recommended_fix = EXCLUDED.recommended_fix,",
        "  updated_at = now();",
    ]


def render_shadow_write_receipts_insert(plan: ShadowValidationPlan) -> list[str]:
    return [
        "WITH run_ref AS (",
        "  SELECT r.id AS shadow_run_uuid, r.project_id, r.shadow_run_id, r.import_batch_id",
        "  FROM shadow_validation_runs r",
        f"  WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        ")",
        "INSERT INTO shadow_write_receipts (",
        "  project_id, shadow_run_id, shadow_write_receipt_id, idempotency_key, target_domain, target_table,",
        "  source_business_id, generated_business_id, content_hash, write_mode, write_result, retry_count,",
        "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, source_refs",
        ")",
        "SELECT",
        "  rr.project_id,",
        "  rr.shadow_run_uuid,",
        "  concat('m5:', rr.shadow_run_id, ':receipt:', o.target_table, ':', o.source_path, ':', o.source_index),",
        "  concat('m5:', rr.shadow_run_id, ':', o.target_table, ':', o.source_path, ':', o.source_index),",
        "  o.target_domain,",
        "  o.target_table,",
        "  o.source_business_id,",
        "  o.generated_business_id,",
        "  o.content_hash,",
        "  'SHADOW_WRITE',",
        "  'ACCEPTED',",
        "  0,",
        "  'CONFIRMED',",
        "  'm5_shadow_validation',",
        "  'ACTIVE',",
        "  'SYSTEM_CONFIRMED',",
        "  'SYSTEM',",
        "  coalesce(nullif(o.source_business_id, ''), o.generated_business_id),",
        "  jsonb_build_array(jsonb_build_object('mapped_object_id', o.id, 'import_batch_id', rr.import_batch_id))",
        "FROM run_ref rr",
        "JOIN json_import_mapped_objects o ON o.batch_id = rr.import_batch_id AND o.project_id = rr.project_id",
        "WHERE o.deleted_at IS NULL",
        "ON CONFLICT (project_id, idempotency_key) DO UPDATE SET",
        "  retry_count = shadow_write_receipts.retry_count + 1,",
        "  write_result = 'RETRY_MERGED',",
        "  last_attempted_at = now(),",
        "  content_hash = EXCLUDED.content_hash,",
        "  source_refs = EXCLUDED.source_refs,",
        "  updated_at = now();",
    ]


def render_duplicate_idempotency_mismatch_insert(plan: ShadowValidationPlan) -> list[str]:
    return [
        "WITH run_ref AS (",
        "  SELECT r.id AS shadow_run_uuid, r.project_id, r.shadow_run_id",
        "  FROM shadow_validation_runs r",
        f"  WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        "), duplicate_keys AS (",
        "  SELECT w.project_id, w.shadow_run_id, w.idempotency_key, count(*)::integer AS duplicate_count",
        "  FROM shadow_write_receipts w",
        "  JOIN run_ref rr ON rr.shadow_run_uuid = w.shadow_run_id AND rr.project_id = w.project_id",
        "  GROUP BY w.project_id, w.shadow_run_id, w.idempotency_key",
        "  HAVING count(*) > 1",
        ")",
        "INSERT INTO shadow_validation_mismatches (",
        "  project_id, shadow_run_id, shadow_mismatch_id, mismatch_category, severity, target_domain, target_table,",
        "  expected_value, postgres_value, recommended_fix, status, legacy_status_raw, lifecycle_state,",
        "  authority_level, source_type, source_id, source_refs, content_hash",
        ")",
        "SELECT",
        "  dk.project_id,",
        "  dk.shadow_run_id,",
        "  concat('m5:', rr.shadow_run_id, ':duplicate_idempotency:', dk.idempotency_key),",
        "  'DUPLICATE_IDEMPOTENCY_KEY',",
        "  'ERROR',",
        "  'shadow_write',",
        "  'shadow_write_receipts',",
        "  jsonb_build_object('expectedDuplicateCount', 0),",
        "  jsonb_build_object('duplicateIdempotencyKeyCount', dk.duplicate_count),",
        "  'Fix duplicated shadow write idempotency keys before accepting the shadow validation run.',",
        "  'DRAFT',",
        "  'm5_shadow_validation',",
        "  'ACTIVE',",
        "  'SYSTEM_CONFIRMED',",
        "  'SYSTEM',",
        "  concat(rr.shadow_run_id, ':duplicate_idempotency:', dk.idempotency_key),",
        "  jsonb_build_array(jsonb_build_object('idempotency_key', dk.idempotency_key)),",
        "  ''",
        "FROM duplicate_keys dk",
        "JOIN run_ref rr ON rr.shadow_run_uuid = dk.shadow_run_id AND rr.project_id = dk.project_id",
        "ON CONFLICT (project_id, shadow_mismatch_id) DO UPDATE SET",
        "  postgres_value = EXCLUDED.postgres_value,",
        "  recommended_fix = EXCLUDED.recommended_fix,",
        "  updated_at = now();",
    ]


def render_run_update(plan: ShadowValidationPlan) -> list[str]:
    return [
        "WITH run_ref AS (",
        "  SELECT r.id AS shadow_run_uuid, r.project_id",
        "  FROM shadow_validation_runs r",
        f"  WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        "), domain_stats AS (",
        "  SELECT",
        "    coalesce(sum(postgres_object_count), 0)::integer AS postgres_object_count,",
        "    coalesce(sum(",
        "      missing_in_postgres_count + extra_in_postgres_count + content_hash_mismatch_count",
        "      + status_mismatch_count + lifecycle_mismatch_count + source_ref_mismatch_count",
        "      + duplicate_idempotency_count",
        "    ), 0)::integer AS mismatch_count",
        "  FROM shadow_validation_domain_results d",
        "  JOIN run_ref rr ON rr.shadow_run_uuid = d.shadow_run_id AND rr.project_id = d.project_id",
        "), duplicate_stats AS (",
        "  SELECT count(*)::integer AS duplicate_write_count",
        "  FROM (",
        "    SELECT w.idempotency_key",
        "    FROM shadow_write_receipts w",
        "    JOIN run_ref rr ON rr.shadow_run_uuid = w.shadow_run_id AND rr.project_id = w.project_id",
        "    GROUP BY w.project_id, w.idempotency_key",
        "    HAVING count(*) > 1",
        "  ) duplicates",
        ")",
        "UPDATE shadow_validation_runs r",
        "SET",
        "  postgres_object_count = ds.postgres_object_count,",
        "  mismatch_count = ds.mismatch_count + dup.duplicate_write_count,",
        "  duplicate_write_count = dup.duplicate_write_count,",
        "  result = CASE WHEN ds.mismatch_count + dup.duplicate_write_count = 0 THEN 'PASS' ELSE 'FAIL' END,",
        "  status = CASE WHEN ds.mismatch_count + dup.duplicate_write_count = 0 THEN 'CONFIRMED'::canonical_status_value ELSE 'PROVISIONAL'::canonical_status_value END,",
        "  completed_at = now(),",
        "  updated_at = now()",
        "FROM domain_stats ds, duplicate_stats dup",
        "WHERE r.id = (SELECT shadow_run_uuid FROM run_ref);",
    ]


def render_storage_consistency_insert(plan: ShadowValidationPlan) -> list[str]:
    report_id = f"{plan.shadow_run_id}:storage_consistency"
    return [
        "INSERT INTO storage_consistency_reports (",
        "  report_id, project_id, batch_id, report_kind, result, checked_object_count, mismatch_count, mismatches,",
        "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
        ")",
        "SELECT",
        f"  {sql_literal(report_id)},",
        "  r.project_id,",
        "  r.import_batch_id,",
        "  'SHADOW_COMPARE',",
        "  r.result,",
        "  r.postgres_object_count,",
        "  r.mismatch_count,",
        "  coalesce((",
        "    SELECT jsonb_agg(jsonb_build_object(",
        "      'mismatchCategory', m.mismatch_category,",
        "      'severity', m.severity,",
        "      'targetDomain', m.target_domain,",
        "      'targetTable', m.target_table,",
        "      'recommendedFix', m.recommended_fix",
        "    ) ORDER BY m.mismatch_category, m.target_domain, m.target_table)",
        "    FROM shadow_validation_mismatches m",
        "    WHERE m.shadow_run_id = r.id AND m.project_id = r.project_id",
        "  ), '[]'::jsonb),",
        "  CASE WHEN r.result = 'PASS' THEN 'CONFIRMED'::canonical_status_value ELSE 'PROVISIONAL'::canonical_status_value END,",
        "  'm5_shadow_validation',",
        "  'ACTIVE',",
        "  'SYSTEM_CONFIRMED',",
        "  'SYSTEM',",
        "  r.shadow_run_id,",
        "  r.content_hash",
        "FROM shadow_validation_runs r",
        f"WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        "ON CONFLICT (report_id) DO UPDATE SET",
        "  result = EXCLUDED.result,",
        "  checked_object_count = EXCLUDED.checked_object_count,",
        "  mismatch_count = EXCLUDED.mismatch_count,",
        "  mismatches = EXCLUDED.mismatches,",
        "  status = EXCLUDED.status,",
        "  content_hash = EXCLUDED.content_hash,",
        "  updated_at = now();",
    ]


def render_storage_health_insert(plan: ShadowValidationPlan) -> list[str]:
    health_check_id = f"{plan.shadow_run_id}:shadow_health"
    return [
        "INSERT INTO storage_health_checks (",
        "  project_id, health_check_id, check_kind, check_result, checked_table, checked_object_count,",
        "  issue_count, issues, status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
        ")",
        "SELECT",
        "  r.project_id,",
        f"  {sql_literal(health_check_id)},",
        "  'IMPORT_BATCH',",
        "  CASE WHEN r.result = 'PASS' THEN 'PASS' ELSE 'FAIL' END,",
        "  'shadow_validation_runs',",
        "  r.postgres_object_count,",
        "  r.mismatch_count,",
        "  jsonb_build_array(jsonb_build_object('shadowRunId', r.shadow_run_id, 'result', r.result)),",
        "  CASE WHEN r.result = 'PASS' THEN 'CONFIRMED'::canonical_status_value ELSE 'PROVISIONAL'::canonical_status_value END,",
        "  'm5_shadow_validation',",
        "  'ACTIVE',",
        "  'SYSTEM_CONFIRMED',",
        "  'SYSTEM',",
        "  r.shadow_run_id,",
        "  r.content_hash",
        "FROM shadow_validation_runs r",
        f"WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        "ON CONFLICT (project_id, health_check_id) DO UPDATE SET",
        "  check_result = EXCLUDED.check_result,",
        "  checked_object_count = EXCLUDED.checked_object_count,",
        "  issue_count = EXCLUDED.issue_count,",
        "  issues = EXCLUDED.issues,",
        "  status = EXCLUDED.status,",
        "  content_hash = EXCLUDED.content_hash,",
        "  updated_at = now();",
    ]


def render_result_assertion(plan: ShadowValidationPlan) -> list[str]:
    report_id = f"{plan.shadow_run_id}:storage_consistency"
    return [
        "DO $$",
        "DECLARE",
        "  run_result text;",
        "  run_mismatch_count integer;",
        "  run_duplicate_write_count integer;",
        "  report_result text;",
        "  report_mismatch_count integer;",
        "BEGIN",
        "  SELECT r.result, r.mismatch_count, r.duplicate_write_count",
        "  INTO run_result, run_mismatch_count, run_duplicate_write_count",
        "  FROM shadow_validation_runs r",
        f"  WHERE r.shadow_run_id = {sql_literal(plan.shadow_run_id)}",
        "    AND r.deleted_at IS NULL",
        "  ORDER BY r.updated_at DESC",
        "  LIMIT 1;",
        "",
        "  IF run_result IS NULL THEN",
        f"    RAISE EXCEPTION 'M5 shadow validation run not found: %', {sql_literal(plan.shadow_run_id)};",
        "  END IF;",
        "",
        "  IF run_result <> 'PASS' OR run_mismatch_count <> 0 OR run_duplicate_write_count <> 0 THEN",
        "    RAISE EXCEPTION 'M5 shadow validation did not pass: result=%, mismatch_count=%, duplicate_write_count=%',",
        "      run_result, run_mismatch_count, run_duplicate_write_count;",
        "  END IF;",
        "",
        "  SELECT c.result, c.mismatch_count",
        "  INTO report_result, report_mismatch_count",
        "  FROM storage_consistency_reports c",
        f"  WHERE c.report_id = {sql_literal(report_id)}",
        "  ORDER BY c.updated_at DESC",
        "  LIMIT 1;",
        "",
        "  IF report_result IS NULL THEN",
        f"    RAISE EXCEPTION 'M5 storage consistency report not found: %', {sql_literal(report_id)};",
        "  END IF;",
        "",
        "  IF report_result <> 'PASS' OR report_mismatch_count <> 0 THEN",
        "    RAISE EXCEPTION 'M5 storage consistency report did not pass: result=%, mismatch_count=%',",
        "      report_result, report_mismatch_count;",
        "  END IF;",
        "END $$;",
    ]


def write_outputs(
    plan: ShadowValidationPlan,
    output_dir: Path,
    *,
    date_stamp: str = DEFAULT_DATE_STAMP,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"m5-shadow-validation-report-{date_stamp}.json"
    status_path = output_dir / f"m5-shadow-validation-status-{date_stamp}.json"
    sql_path = output_dir / f"m5-shadow-validation-apply-{date_stamp}.sql"

    report_payload = plan.to_report_dict()
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sql_path.write_text(render_shadow_validation_sql(plan), encoding="utf-8")
    status_payload = {
        "status": "success",
        "shadowRunId": plan.shadow_run_id,
        "validationMode": SHADOW_VALIDATION_MODE,
        "reportPath": str(report_path),
        "sqlPath": str(sql_path),
        "importBatchId": plan.import_batch_id,
        "expectedObjectCount": plan.expected_object_count,
        "domainCount": len(plan.domain_expectations),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"report": report_path, "status": status_path, "sql": sql_path}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M5 shadow validation SQL generator.")
    parser.add_argument("--m4-report", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("06-validation"), type=Path)
    parser.add_argument("--shadow-run-id", default="")
    parser.add_argument("--date-stamp", default=DEFAULT_DATE_STAMP)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    plan = build_shadow_validation_plan(
        args.m4_report,
        shadow_run_id=args.shadow_run_id or None,
    )
    written = write_outputs(plan, args.output_dir, date_stamp=args.date_stamp)
    for key, path in written.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
