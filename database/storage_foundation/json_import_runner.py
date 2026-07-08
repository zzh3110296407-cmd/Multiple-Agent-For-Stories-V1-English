"""M4 JSON import scanner and admin SQL renderer.

This module is a Database-session prototype. It uses only the Python standard
library and writes import admin/staging SQL; it does not connect to PostgreSQL
and does not modify the main backend runtime.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATE_STAMP = "2026-07-04"
SCAN_POLICY = "TOP_LEVEL_JSON_ONLY"


@dataclass(frozen=True)
class JsonSourceMapping:
    file_name: str
    target_domain: str
    target_table: str
    id_field: str
    root_selector: str = "list"


@dataclass
class JsonImportObjectPlan:
    source_path: str
    source_index: int
    source_business_id: str
    generated_business_id: str
    target_domain: str
    target_table: str
    id_field: str
    source_payload: dict[str, Any]
    content_hash: str

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "sourcePath": self.source_path,
            "sourceIndex": self.source_index,
            "sourceBusinessId": self.source_business_id,
            "generatedBusinessId": self.generated_business_id,
            "targetDomain": self.target_domain,
            "targetTable": self.target_table,
            "idField": self.id_field,
            "contentHash": self.content_hash,
        }


@dataclass
class JsonImportFilePlan:
    source_path: str
    source_hash: str
    parse_status: str
    mapping_status: str
    target_domain: str = ""
    target_table: str = ""
    id_field: str = ""
    row_count: int = 0
    source_object_count: int = 0
    mapped_object_count: int = 0
    unmapped_reason: str = ""
    sample_source_ids: list[str] = field(default_factory=list)
    objects: list[JsonImportObjectPlan] = field(default_factory=list)

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "sourcePath": self.source_path,
            "sourceHash": self.source_hash,
            "parseStatus": self.parse_status,
            "mappingStatus": self.mapping_status,
            "targetDomain": self.target_domain,
            "targetTable": self.target_table,
            "idField": self.id_field,
            "rowCount": self.row_count,
            "sourceObjectCount": self.source_object_count,
            "mappedObjectCount": self.mapped_object_count,
            "unmappedReason": self.unmapped_reason,
            "sampleSourceIds": self.sample_source_ids,
        }


@dataclass
class JsonImportBatchPlan:
    batch_id: str
    mode: str
    source_root: Path
    project_business_id: str
    project_display_name: str
    files: list[JsonImportFilePlan]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def mapped_files(self) -> list[JsonImportFilePlan]:
        return [item for item in self.files if item.mapping_status == "MAPPED"]

    @property
    def unmapped_files(self) -> list[JsonImportFilePlan]:
        return [item for item in self.files if item.mapping_status in {"UNMAPPED", "UNSUPPORTED_SHAPE"}]

    @property
    def parse_error_files(self) -> list[JsonImportFilePlan]:
        return [item for item in self.files if item.mapping_status == "PARSE_ERROR"]

    @property
    def object_count(self) -> int:
        return sum(item.mapped_object_count for item in self.files)

    def domain_summaries(self) -> list[dict[str, Any]]:
        summaries: dict[tuple[str, str], dict[str, Any]] = {}
        for file_plan in self.files:
            if file_plan.mapping_status != "MAPPED":
                continue
            key = (file_plan.target_domain, file_plan.target_table)
            entry = summaries.setdefault(
                key,
                {
                    "targetDomain": file_plan.target_domain,
                    "targetTable": file_plan.target_table,
                    "sourceFileCount": 0,
                    "sourceObjectCount": 0,
                    "mappedObjectCount": 0,
                    "importedObjectCount": 0,
                    "unmappedObjectCount": 0,
                    "parseErrorCount": 0,
                },
            )
            entry["sourceFileCount"] += 1
            entry["sourceObjectCount"] += file_plan.source_object_count
            entry["mappedObjectCount"] += file_plan.mapped_object_count
            entry["importedObjectCount"] += file_plan.mapped_object_count if self.mode == "IMPORT" else 0

        return sorted(summaries.values(), key=lambda item: (item["targetDomain"], item["targetTable"]))

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "batchId": self.batch_id,
            "mode": self.mode,
            "scanPolicy": SCAN_POLICY,
            "sourceRoot": str(self.source_root),
            "projectBusinessId": self.project_business_id,
            "projectDisplayName": self.project_display_name,
            "createdAt": self.created_at,
            "totals": {
                "fileCount": len(self.files),
                "mappedFileCount": len(self.mapped_files),
                "unmappedFileCount": len(self.unmapped_files),
                "parseErrorCount": len(self.parse_error_files),
                "objectCount": self.object_count,
            },
            "domainSummaries": self.domain_summaries(),
            "files": [file_plan.to_report_dict() for file_plan in self.files],
        }


DEFAULT_SOURCE_MAPPINGS: dict[str, JsonSourceMapping] = {
    "chapters.json": JsonSourceMapping("chapters.json", "narrative", "chapters", "chapter_id"),
    "scenes.json": JsonSourceMapping("scenes.json", "narrative", "scenes", "scene_id"),
    "events.json": JsonSourceMapping("events.json", "narrative", "events", "event_id"),
    "state_changes.json": JsonSourceMapping("state_changes.json", "narrative", "state_changes", "state_change_id"),
    "characters.json": JsonSourceMapping("characters.json", "character", "characters", "character_id"),
    "relationships.json": JsonSourceMapping("relationships.json", "character", "relationships", "relationship_id"),
    "decisions.json": JsonSourceMapping("decisions.json", "governance", "decisions", "decision_id"),
    "quality_reports.json": JsonSourceMapping("quality_reports.json", "quality", "quality_reports", "quality_report_id"),
    "continuity_issues.json": JsonSourceMapping("continuity_issues.json", "quality", "continuity_issues", "issue_id"),
    "memory_records.json": JsonSourceMapping("memory_records.json", "memory", "memory_records", "memory_id"),
    "memory_update_plans.json": JsonSourceMapping("memory_update_plans.json", "memory", "memory_update_plans", "memory_update_plan_id"),
    "pending_character_state_changes.json": JsonSourceMapping(
        "pending_character_state_changes.json",
        "character",
        "pending_character_state_changes",
        "change_id",
        "changes",
    ),
    "claim_records.json": JsonSourceMapping("claim_records.json", "subjective", "claim_records", "claim_id"),
    "narrative_intent_records.json": JsonSourceMapping(
        "narrative_intent_records.json",
        "subjective",
        "narrative_intents",
        "narrative_intent_id",
    ),
    "character_psychology_traces.json": JsonSourceMapping(
        "character_psychology_traces.json",
        "subjective",
        "character_psychology_traces",
        "psychology_trace_id",
    ),
    "character_expression_records.json": JsonSourceMapping(
        "character_expression_records.json",
        "subjective",
        "character_expression_records",
        "expression_record_id",
    ),
    "perception_state_records.json": JsonSourceMapping(
        "perception_state_records.json",
        "subjective",
        "perception_states",
        "perception_state_id",
    ),
    "apparent_contradiction_records.json": JsonSourceMapping(
        "apparent_contradiction_records.json",
        "subjective",
        "apparent_contradictions",
        "apparent_contradiction_id",
    ),
    "narrative_debts.json": JsonSourceMapping("narrative_debts.json", "subjective", "narrative_debts", "narrative_debt_id"),
    "chapter_memory_packs.json": JsonSourceMapping(
        "chapter_memory_packs.json",
        "retrieval",
        "chapter_memory_packs",
        "chapter_memory_pack_id",
        "packs",
    ),
    "scene_memory_packs.json": JsonSourceMapping(
        "scene_memory_packs.json",
        "retrieval",
        "scene_memory_packs",
        "scene_memory_pack_id",
        "packs",
    ),
}


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def generated_business_id(file_name: str, source_index: int, payload: dict[str, Any]) -> str:
    short_hash = stable_json_hash(payload)[:16]
    stem = Path(file_name).stem
    return f"generated:{stem}:{source_index}:{short_hash}"


def scan_json_source(
    source_root: Path,
    *,
    batch_id: str | None = None,
    mode: str = "DRY_RUN",
    project_business_id: str = "project_m4_imported_local",
    project_display_name: str = "M4 Imported JSON Project",
    mappings: dict[str, JsonSourceMapping] | None = None,
) -> JsonImportBatchPlan:
    root = source_root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Source root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Source root must be a directory: {root}")

    normalized_mode = normalize_mode(mode)
    active_mappings = mappings or DEFAULT_SOURCE_MAPPINGS
    active_batch_id = batch_id or f"m4_json_import_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    file_plans = [
        scan_json_file(path, root, active_mappings)
        for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold())
    ]
    return JsonImportBatchPlan(
        batch_id=active_batch_id,
        mode=normalized_mode,
        source_root=root,
        project_business_id=project_business_id,
        project_display_name=project_display_name,
        files=file_plans,
    )


def scan_json_file(
    path: Path,
    source_root: Path,
    mappings: dict[str, JsonSourceMapping],
) -> JsonImportFilePlan:
    relative_path = path.relative_to(source_root).as_posix()
    raw_bytes = path.read_bytes()
    source_hash = stable_bytes_hash(raw_bytes)
    mapping = mappings.get(path.name)

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return JsonImportFilePlan(
            source_path=relative_path,
            source_hash=source_hash,
            parse_status="ERROR",
            mapping_status="PARSE_ERROR",
            source_object_count=0,
            unmapped_reason=f"JSON parse error: {exc}",
        )

    if mapping is None:
        return JsonImportFilePlan(
            source_path=relative_path,
            source_hash=source_hash,
            parse_status="PARSED",
            mapping_status="UNMAPPED",
            source_object_count=estimate_source_object_count(data),
            unmapped_reason="No M4 repository mapping.",
        )

    records, shape_error = extract_records(data, mapping.root_selector)
    if shape_error:
        return JsonImportFilePlan(
            source_path=relative_path,
            source_hash=source_hash,
            parse_status="PARSED",
            mapping_status="UNSUPPORTED_SHAPE",
            target_domain=mapping.target_domain,
            target_table=mapping.target_table,
            id_field=mapping.id_field,
            source_object_count=estimate_source_object_count(data),
            unmapped_reason=shape_error,
        )

    objects: list[JsonImportObjectPlan] = []
    sample_source_ids: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        source_business_id = str(record.get(mapping.id_field) or "")
        generated_id = "" if source_business_id else generated_business_id(path.name, index, record)
        if source_business_id and len(sample_source_ids) < 5:
            sample_source_ids.append(source_business_id)
        objects.append(
            JsonImportObjectPlan(
                source_path=relative_path,
                source_index=index,
                source_business_id=source_business_id,
                generated_business_id=generated_id,
                target_domain=mapping.target_domain,
                target_table=mapping.target_table,
                id_field=mapping.id_field,
                source_payload=record,
                content_hash=stable_json_hash(record),
            )
        )

    return JsonImportFilePlan(
        source_path=relative_path,
        source_hash=source_hash,
        parse_status="PARSED",
        mapping_status="MAPPED",
        target_domain=mapping.target_domain,
        target_table=mapping.target_table,
        id_field=mapping.id_field,
        row_count=len(objects),
        source_object_count=len(records),
        mapped_object_count=len(objects),
        sample_source_ids=sample_source_ids,
        objects=objects,
    )


def extract_records(data: Any, root_selector: str) -> tuple[list[Any], str]:
    if root_selector == "list":
        if isinstance(data, list):
            return data, ""
        return [], "Expected JSON root list."

    if root_selector == "object":
        if isinstance(data, dict):
            return [data], ""
        return [], "Expected JSON root object."

    if root_selector == "packs":
        if isinstance(data, list):
            return data, ""
        if isinstance(data, dict) and isinstance(data.get("packs"), list):
            return data["packs"], ""
        return [], "Expected JSON root list or object with packs list."

    if root_selector == "changes":
        if isinstance(data, list):
            return data, ""
        if isinstance(data, dict) and isinstance(data.get("changes"), list):
            return data["changes"], ""
        return [], "Expected JSON root list or object with changes list."

    return [], f"Unknown root selector: {root_selector}"


def estimate_source_object_count(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("packs", "changes", "items", "records"):
            if isinstance(data.get(key), list):
                return len(data[key])
        return 1
    return 0


def normalize_mode(mode: str) -> str:
    normalized = mode.upper().replace("-", "_")
    if normalized in {"DRYRUN", "DRY_RUN"}:
        return "DRY_RUN"
    if normalized == "IMPORT":
        return "IMPORT"
    raise ValueError(f"Unsupported M4 mode: {mode}")


def render_admin_sql(plan: JsonImportBatchPlan) -> str:
    mapping_report = plan.to_report_dict()
    report_id = f"{plan.batch_id}:mapping_report"
    health_check_id = f"{plan.batch_id}:import_health"
    backup_manifest_id = f"{plan.batch_id}:pre_import_backup"
    result = "MAPPED" if not plan.unmapped_files and not plan.parse_error_files else "MAPPED_WITH_UNMAPPED"
    mismatch_files = [
        {
            "sourcePath": item.source_path,
            "mappingStatus": item.mapping_status,
            "parseStatus": item.parse_status,
            "reason": item.unmapped_reason,
        }
        for item in [*plan.unmapped_files, *plan.parse_error_files]
    ]
    batch_hash = stable_json_hash(mapping_report)
    lines = [
        "-- Generated by storage_foundation.json_import_runner.",
        "-- M4 import writes admin/staging tables only; it does not switch runtime storage.",
        "\\set ON_ERROR_STOP on",
        "SET search_path TO mas_phase875_proto;",
        "",
        "BEGIN;",
        "",
        "INSERT INTO projects (",
        "  project_id, display_name, language, storage_mode, status, legacy_status_raw,",
        "  lifecycle_state, authority_level, idempotency_key, source_type, source_id, content_hash",
        ") VALUES (",
        f"  {sql_literal(plan.project_business_id)},",
        f"  {sql_literal(plan.project_display_name)},",
        "  'zh',",
        "  'POSTGRES_SHADOW',",
        "  'DRAFT',",
        "  'm4_json_import',",
        "  'ACTIVE',",
        "  'MIGRATED_REFERENCE',",
        f"  {sql_literal('m4:project:' + plan.project_business_id)},",
        "  'MIGRATION',",
        f"  {sql_literal(plan.batch_id)},",
        f"  {sql_literal(batch_hash)}",
        ")",
        "ON CONFLICT (project_id) DO UPDATE SET",
        "  display_name = EXCLUDED.display_name,",
        "  storage_mode = EXCLUDED.storage_mode,",
        "  updated_at = now();",
        "",
        "INSERT INTO json_import_batches (",
        "  batch_id, source_root, mode, project_id, file_count, object_count,",
        "  mapped_file_count, unmapped_file_count, parse_error_count, mapping_report,",
        "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
        ")",
        "SELECT",
        f"  {sql_literal(plan.batch_id)},",
        f"  {sql_literal(str(plan.source_root))},",
        f"  {sql_literal(plan.mode)},",
        "  p.id,",
        f"  {len(plan.files)},",
        f"  {plan.object_count},",
        f"  {len(plan.mapped_files)},",
        f"  {len(plan.unmapped_files)},",
        f"  {len(plan.parse_error_files)},",
        f"  {sql_jsonb(mapping_report)},",
        "  'DRAFT',",
        "  'm4_json_import',",
        "  'ACTIVE',",
        "  'MIGRATED_REFERENCE',",
        "  'MIGRATION',",
        f"  {sql_literal(plan.batch_id)},",
        f"  {sql_literal(batch_hash)}",
        "FROM projects p",
        f"WHERE p.project_id = {sql_literal(plan.project_business_id)}",
        "ON CONFLICT (batch_id) DO UPDATE SET",
        "  source_root = EXCLUDED.source_root,",
        "  mode = EXCLUDED.mode,",
        "  project_id = EXCLUDED.project_id,",
        "  file_count = EXCLUDED.file_count,",
        "  object_count = EXCLUDED.object_count,",
        "  mapped_file_count = EXCLUDED.mapped_file_count,",
        "  unmapped_file_count = EXCLUDED.unmapped_file_count,",
        "  parse_error_count = EXCLUDED.parse_error_count,",
        "  mapping_report = EXCLUDED.mapping_report,",
        "  content_hash = EXCLUDED.content_hash,",
        "  updated_at = now();",
        "",
    ]

    for file_plan in plan.files:
        lines.extend(render_file_insert(plan, file_plan))
        lines.append("")

    for file_plan in plan.mapped_files:
        for object_plan in file_plan.objects:
            lines.extend(render_object_insert(plan, file_plan, object_plan))
            lines.append("")

    for summary in plan.domain_summaries():
        lines.extend(render_domain_summary_insert(plan, summary))
        lines.append("")

    lines.extend(
        [
            "INSERT INTO storage_consistency_reports (",
            "  report_id, project_id, batch_id, report_kind, result, checked_object_count, mismatch_count,",
            "  mismatches, status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
            ")",
            "SELECT",
            f"  {sql_literal(report_id)},",
            "  b.project_id,",
            "  b.id,",
            "  'MAPPING',",
            f"  {sql_literal(result)},",
            f"  {plan.object_count},",
            f"  {len(mismatch_files)},",
            f"  {sql_jsonb(mismatch_files)},",
            "  'CONFIRMED',",
            "  'm4_json_import',",
            "  'ACTIVE',",
            "  'SYSTEM_CONFIRMED',",
            "  'SYSTEM',",
            f"  {sql_literal(plan.batch_id)},",
            f"  {sql_literal(stable_json_hash(mismatch_files))}",
            "FROM json_import_batches b",
            f"WHERE b.batch_id = {sql_literal(plan.batch_id)}",
            "ON CONFLICT (report_id) DO UPDATE SET",
            "  result = EXCLUDED.result,",
            "  checked_object_count = EXCLUDED.checked_object_count,",
            "  mismatch_count = EXCLUDED.mismatch_count,",
            "  mismatches = EXCLUDED.mismatches,",
            "  content_hash = EXCLUDED.content_hash,",
            "  updated_at = now();",
            "",
            "INSERT INTO backup_manifests (",
            "  project_id, backup_manifest_id, backup_kind, source_batch_id, source_root, artifact_root,",
            "  file_count, object_count, manifest_hash, status, legacy_status_raw, lifecycle_state,",
            "  authority_level, source_type, source_id, content_hash",
            ")",
            "SELECT",
            "  b.project_id,",
            f"  {sql_literal(backup_manifest_id)},",
            "  'PRE_IMPORT_BACKUP',",
            "  b.id,",
            "  b.source_root,",
            "  '',",
            "  b.file_count,",
            "  b.object_count,",
            f"  {sql_literal(batch_hash)},",
            "  'DRAFT',",
            "  'm4_json_import',",
            "  'ACTIVE',",
            "  'SYSTEM_CONFIRMED',",
            "  'SYSTEM',",
            f"  {sql_literal(plan.batch_id)},",
            f"  {sql_literal(batch_hash)}",
            "FROM json_import_batches b",
            f"WHERE b.batch_id = {sql_literal(plan.batch_id)}",
            "ON CONFLICT (project_id, backup_manifest_id) DO UPDATE SET",
            "  file_count = EXCLUDED.file_count,",
            "  object_count = EXCLUDED.object_count,",
            "  manifest_hash = EXCLUDED.manifest_hash,",
            "  content_hash = EXCLUDED.content_hash,",
            "  updated_at = now();",
            "",
            "INSERT INTO storage_health_checks (",
            "  project_id, health_check_id, check_kind, check_result, checked_table, checked_object_count,",
            "  issue_count, issues, status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
            ")",
            "SELECT",
            "  b.project_id,",
            f"  {sql_literal(health_check_id)},",
            "  'IMPORT_BATCH',",
            f"  {sql_literal('PASS' if not mismatch_files else 'WARN')},",
            "  'json_import_files',",
            "  b.file_count,",
            f"  {len(mismatch_files)},",
            f"  {sql_jsonb(mismatch_files)},",
            "  'CONFIRMED',",
            "  'm4_json_import',",
            "  'ACTIVE',",
            "  'SYSTEM_CONFIRMED',",
            "  'SYSTEM',",
            f"  {sql_literal(plan.batch_id)},",
            f"  {sql_literal(stable_json_hash(mismatch_files))}",
            "FROM json_import_batches b",
            f"WHERE b.batch_id = {sql_literal(plan.batch_id)}",
            "ON CONFLICT (project_id, health_check_id) DO UPDATE SET",
            "  check_result = EXCLUDED.check_result,",
            "  checked_object_count = EXCLUDED.checked_object_count,",
            "  issue_count = EXCLUDED.issue_count,",
            "  issues = EXCLUDED.issues,",
            "  content_hash = EXCLUDED.content_hash,",
            "  updated_at = now();",
            "",
            "COMMIT;",
            "",
        ]
    )
    return "\n".join(lines)


def render_file_insert(plan: JsonImportBatchPlan, file_plan: JsonImportFilePlan) -> list[str]:
    return [
        "INSERT INTO json_import_files (",
        "  batch_id, source_path, source_hash, parse_status, mapping_status, target_domain, target_table,",
        "  row_count, source_object_count, mapped_object_count, unmapped_reason, id_field, sample_source_ids,",
        "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
        ")",
        "SELECT",
        "  b.id,",
        f"  {sql_literal(file_plan.source_path)},",
        f"  {sql_literal(file_plan.source_hash)},",
        f"  {sql_literal(file_plan.parse_status)},",
        f"  {sql_literal(file_plan.mapping_status)},",
        f"  {sql_literal(file_plan.target_domain)},",
        f"  {sql_literal(file_plan.target_table)},",
        f"  {file_plan.row_count},",
        f"  {file_plan.source_object_count},",
        f"  {file_plan.mapped_object_count},",
        f"  {sql_literal(file_plan.unmapped_reason)},",
        f"  {sql_literal(file_plan.id_field)},",
        f"  {sql_jsonb(file_plan.sample_source_ids)},",
        "  'DRAFT',",
        "  'm4_json_import',",
        "  'ACTIVE',",
        "  'MIGRATED_REFERENCE',",
        "  'MIGRATION',",
        f"  {sql_literal(file_plan.source_path)},",
        f"  {sql_literal(file_plan.source_hash)}",
        "FROM json_import_batches b",
        f"WHERE b.batch_id = {sql_literal(plan.batch_id)}",
        "ON CONFLICT (batch_id, source_path) DO UPDATE SET",
        "  source_hash = EXCLUDED.source_hash,",
        "  parse_status = EXCLUDED.parse_status,",
        "  mapping_status = EXCLUDED.mapping_status,",
        "  target_domain = EXCLUDED.target_domain,",
        "  target_table = EXCLUDED.target_table,",
        "  row_count = EXCLUDED.row_count,",
        "  source_object_count = EXCLUDED.source_object_count,",
        "  mapped_object_count = EXCLUDED.mapped_object_count,",
        "  unmapped_reason = EXCLUDED.unmapped_reason,",
        "  id_field = EXCLUDED.id_field,",
        "  sample_source_ids = EXCLUDED.sample_source_ids,",
        "  content_hash = EXCLUDED.content_hash,",
        "  updated_at = now();",
    ]


def render_object_insert(
    plan: JsonImportBatchPlan,
    file_plan: JsonImportFilePlan,
    object_plan: JsonImportObjectPlan,
) -> list[str]:
    import_action = "STAGE_ONLY" if plan.mode == "IMPORT" else "DRY_RUN_ONLY"
    source_id = object_plan.source_business_id or object_plan.generated_business_id
    return [
        "INSERT INTO json_import_mapped_objects (",
        "  batch_id, file_id, project_id, source_path, source_index, source_business_id, generated_business_id,",
        "  target_domain, target_table, id_field, mapping_status, import_action, source_payload, source_hash, content_hash,",
        "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, source_refs, idempotency_key",
        ")",
        "SELECT",
        "  b.id,",
        "  f.id,",
        "  b.project_id,",
        f"  {sql_literal(object_plan.source_path)},",
        f"  {object_plan.source_index},",
        f"  {sql_literal(object_plan.source_business_id)},",
        f"  {sql_literal(object_plan.generated_business_id)},",
        f"  {sql_literal(object_plan.target_domain)},",
        f"  {sql_literal(object_plan.target_table)},",
        f"  {sql_literal(object_plan.id_field)},",
        "  'MAPPED',",
        f"  {sql_literal(import_action)},",
        f"  {sql_jsonb(object_plan.source_payload)},",
        f"  {sql_literal(file_plan.source_hash)},",
        f"  {sql_literal(object_plan.content_hash)},",
        "  'DRAFT',",
        "  'm4_json_import',",
        "  'ACTIVE',",
        "  'MIGRATED_REFERENCE',",
        "  'MIGRATION',",
        f"  {sql_literal(source_id)},",
        "  jsonb_build_array(jsonb_build_object(",
        "    'source_path', f.source_path,",
        "    'source_hash', f.source_hash,",
        f"    'source_index', {object_plan.source_index}",
        "  )),",
        f"  {sql_literal('m4:' + plan.batch_id + ':' + object_plan.source_path + ':' + str(object_plan.source_index))}",
        "FROM json_import_batches b",
        "JOIN json_import_files f ON f.batch_id = b.id",
        f"  AND f.source_path = {sql_literal(object_plan.source_path)}",
        f"WHERE b.batch_id = {sql_literal(plan.batch_id)}",
        "ON CONFLICT (batch_id, source_path, source_index) DO UPDATE SET",
        "  source_business_id = EXCLUDED.source_business_id,",
        "  generated_business_id = EXCLUDED.generated_business_id,",
        "  source_payload = EXCLUDED.source_payload,",
        "  source_hash = EXCLUDED.source_hash,",
        "  content_hash = EXCLUDED.content_hash,",
        "  source_refs = EXCLUDED.source_refs,",
        "  idempotency_key = EXCLUDED.idempotency_key,",
        "  updated_at = now();",
    ]


def render_domain_summary_insert(plan: JsonImportBatchPlan, summary: dict[str, Any]) -> list[str]:
    summary_hash = stable_json_hash(summary)
    source_id = f"{plan.batch_id}:{summary['targetDomain']}:{summary['targetTable']}"
    return [
        "INSERT INTO json_import_domain_summaries (",
        "  batch_id, project_id, target_domain, target_table, source_file_count, source_object_count,",
        "  mapped_object_count, imported_object_count, unmapped_object_count, parse_error_count,",
        "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
        ")",
        "SELECT",
        "  b.id,",
        "  b.project_id,",
        f"  {sql_literal(summary['targetDomain'])},",
        f"  {sql_literal(summary['targetTable'])},",
        f"  {int(summary['sourceFileCount'])},",
        f"  {int(summary['sourceObjectCount'])},",
        f"  {int(summary['mappedObjectCount'])},",
        f"  {int(summary['importedObjectCount'])},",
        f"  {int(summary['unmappedObjectCount'])},",
        f"  {int(summary['parseErrorCount'])},",
        "  'DRAFT',",
        "  'm4_json_import',",
        "  'ACTIVE',",
        "  'MIGRATED_REFERENCE',",
        "  'MIGRATION',",
        f"  {sql_literal(source_id)},",
        f"  {sql_literal(summary_hash)}",
        "FROM json_import_batches b",
        f"WHERE b.batch_id = {sql_literal(plan.batch_id)}",
        "ON CONFLICT (batch_id, target_domain, target_table) DO UPDATE SET",
        "  source_file_count = EXCLUDED.source_file_count,",
        "  source_object_count = EXCLUDED.source_object_count,",
        "  mapped_object_count = EXCLUDED.mapped_object_count,",
        "  imported_object_count = EXCLUDED.imported_object_count,",
        "  unmapped_object_count = EXCLUDED.unmapped_object_count,",
        "  parse_error_count = EXCLUDED.parse_error_count,",
        "  content_hash = EXCLUDED.content_hash,",
        "  updated_at = now();",
    ]


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_jsonb(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sql_literal(encoded) + "::jsonb"


def write_outputs(
    plan: JsonImportBatchPlan,
    output_dir: Path,
    *,
    date_stamp: str = DEFAULT_DATE_STAMP,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mode_name = "dry-run" if plan.mode == "DRY_RUN" else "import"
    report_path = output_dir / f"m4-json-import-{mode_name}-report-{date_stamp}.json"
    status_path = output_dir / f"m4-json-import-{mode_name}-status-{date_stamp}.json"
    report_payload = plan.to_report_dict()
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    written: dict[str, Path] = {"report": report_path, "status": status_path}
    sql_path: Path | None = None
    if plan.mode == "IMPORT":
        sql_path = output_dir / f"m4-json-import-admin-import-{date_stamp}.sql"
        sql_path.write_text(render_admin_sql(plan), encoding="utf-8")
        written["sql"] = sql_path

    status_payload = {
        "status": "success",
        "mode": plan.mode,
        "scanPolicy": SCAN_POLICY,
        "batchId": plan.batch_id,
        "reportPath": str(report_path),
        "sqlPath": str(sql_path) if sql_path else "",
        "fileCount": len(plan.files),
        "mappedFileCount": len(plan.mapped_files),
        "unmappedFileCount": len(plan.unmapped_files),
        "parseErrorCount": len(plan.parse_error_files),
        "objectCount": plan.object_count,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return written


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M4 JSON import scanner and admin SQL generator.")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("06-validation"), type=Path)
    parser.add_argument("--mode", choices=["dry-run", "import", "DRY_RUN", "IMPORT"], default="dry-run")
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--project-id", default="project_m4_imported_local")
    parser.add_argument("--project-name", default="M4 Imported JSON Project")
    parser.add_argument("--date-stamp", default=DEFAULT_DATE_STAMP)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    plan = scan_json_source(
        args.source_root,
        batch_id=args.batch_id or None,
        mode=args.mode,
        project_business_id=args.project_id,
        project_display_name=args.project_name,
    )
    written = write_outputs(plan, args.output_dir, date_stamp=args.date_stamp)
    for key, path in written.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
