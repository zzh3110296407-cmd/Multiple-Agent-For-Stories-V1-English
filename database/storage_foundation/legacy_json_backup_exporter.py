"""M7 legacy JSON backup/fixture export renderer.

This module is Database-session prototype code. It writes inspectable JSON
files, a manifest with per-file SHA256 hashes, and SQL rows for the M7
backup-policy tables. It does not connect to PostgreSQL or switch runtime
storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any


DEFAULT_MANIFEST_SCHEMA_VERSION = "phase8_75_m7_json_backup_manifest_v1"
DEFAULT_EXPORT_FORMAT = "LEGACY_JSON_TOP_LEVEL"
DEFAULT_HASH_ALGORITHM = "SHA256"
_SAFE_EXPORT_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class LegacyJsonExportRecord:
    relative_path: str
    payload: Any


@dataclass(frozen=True)
class LegacyJsonExportPackage:
    project_id: str
    export_run_id: str
    backup_manifest_id: str
    records: list[LegacyJsonExportRecord]
    schema_version: str = DEFAULT_MANIFEST_SCHEMA_VERSION
    export_format: str = DEFAULT_EXPORT_FORMAT
    export_mode: str = "BACKUP"
    limitations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class LegacyJsonExportResult:
    export_root: Path
    manifest_path: Path
    sql_path: Path
    package_hash: str
    file_count: int
    object_count: int


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_legacy_json_export(package: LegacyJsonExportPackage, output_root: Path) -> LegacyJsonExportResult:
    if not package.records:
        raise ValueError("legacy JSON export package must include at least one record")

    export_root_name = _safe_export_run_dir(package.export_run_id)
    output_root_resolved = output_root.resolve()
    export_root = (output_root_resolved / export_root_name).resolve()
    if not _is_relative_to(export_root, output_root_resolved):
        raise ValueError(f"unsafe export root path: {package.export_run_id}")
    export_root.mkdir(parents=True, exist_ok=True)

    file_entries: list[dict[str, Any]] = []
    object_count = 0

    for record in sorted(package.records, key=lambda item: item.relative_path.casefold()):
        relative_path = _safe_relative_path(record.relative_path)
        file_path = (export_root / relative_path).resolve()
        if not _is_relative_to(file_path, export_root):
            raise ValueError(f"unsafe export relative path: {record.relative_path}")
        file_path.parent.mkdir(parents=True, exist_ok=True)

        text = json.dumps(record.payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        file_path.write_text(text, encoding="utf-8")
        text_bytes = text.encode("utf-8")

        item_count = _count_json_objects(record.payload)
        object_count += item_count
        file_entries.append(
            {
                "relativePath": relative_path.as_posix(),
                "schemaVersion": package.schema_version,
                "exportFormat": package.export_format,
                "objectCount": item_count,
                "byteCount": len(text_bytes),
                "contentHash": hashlib.sha256(text_bytes).hexdigest(),
                "canonicalContentHash": stable_json_hash(record.payload),
            }
        )

    manifest_payload = {
        "projectId": package.project_id,
        "exportRunId": package.export_run_id,
        "backupManifestId": package.backup_manifest_id,
        "schemaVersion": package.schema_version,
        "exportFormat": package.export_format,
        "contentHashAlgorithm": DEFAULT_HASH_ALGORITHM,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": len(file_entries),
        "objectCount": object_count,
        "files": file_entries,
        "recoveryPolicy": "INSPECTABLE_BACKUP_ONLY",
        "downgradeSupported": False,
        "restoreSupported": False,
        "limitations": package.limitations,
    }
    package_hash = stable_json_hash({key: value for key, value in manifest_payload.items() if key != "createdAt"})
    manifest_payload["packageHash"] = package_hash

    manifest_path = export_root / "backup_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    sql_path = export_root / "m7_legacy_json_export_manifest.sql"
    sql_path.write_text(_render_manifest_sql(package, manifest_payload), encoding="utf-8")

    return LegacyJsonExportResult(
        export_root=export_root,
        manifest_path=manifest_path,
        sql_path=sql_path,
        package_hash=package_hash,
        file_count=len(file_entries),
        object_count=object_count,
    )


def _safe_relative_path(raw_path: str) -> Path:
    if not raw_path or raw_path.startswith(("/", "\\")) or "\\" in raw_path or ":" in raw_path:
        raise ValueError(f"unsafe export relative path: {raw_path}")

    candidate = PurePosixPath(raw_path)
    if candidate.is_absolute() or candidate.name == "":
        raise ValueError(f"unsafe export relative path: {raw_path}")
    if any(part in ("", ".", "..") for part in candidate.parts):
        raise ValueError(f"unsafe export relative path: {raw_path}")
    if candidate.suffix.casefold() != ".json":
        raise ValueError(f"legacy JSON export path must end with .json: {raw_path}")
    return Path(*candidate.parts)


def _safe_export_run_dir(raw_id: str) -> str:
    if not _SAFE_EXPORT_RUN_ID.fullmatch(raw_id):
        raise ValueError(f"unsafe export run id for filesystem path: {raw_id}")
    return raw_id


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _count_json_objects(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return 1
    return 0


def _render_manifest_sql(package: LegacyJsonExportPackage, manifest: dict[str, Any]) -> str:
    project_literal = _sql_literal(package.project_id)
    manifest_literal = _sql_literal(package.backup_manifest_id)
    export_run_literal = _sql_literal(package.export_run_id)
    package_hash_literal = _sql_literal(manifest["packageHash"])
    schema_version_literal = _sql_literal(package.schema_version)
    export_format_literal = _sql_literal(package.export_format)

    lines = [
        "-- Generated by storage_foundation.legacy_json_backup_exporter.",
        "-- M7 export writes backup-policy metadata only; it does not switch runtime storage.",
        "\\set ON_ERROR_STOP on",
        "SET search_path TO mas_phase875_proto;",
        "",
        "WITH project_row AS (",
        "  INSERT INTO projects (project_id, display_name, storage_mode, status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash)",
        f"  VALUES ({project_literal}, {project_literal}, 'POSTGRES_PRIMARY', 'CONFIRMED', 'm7_export', 'ACTIVE', 'USER_CONFIRMED', 'SYSTEM', 'm7_export', {package_hash_literal})",
        "  ON CONFLICT (project_id) DO UPDATE SET updated_at = now()",
        "  RETURNING id",
        "), manifest_row AS (",
        "  INSERT INTO backup_manifests (",
        "    project_id, backup_manifest_id, backup_kind, source_root, artifact_root, file_count, object_count, manifest_hash,",
        "    manifest_schema_version, content_hash_algorithm, export_format, recovery_policy, downgrade_supported, restore_supported, recovery_limitations,",
        "    status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
        "  )",
        "  SELECT",
        "    id,",
        f"    {manifest_literal}, 'JSON_EXPORT', 'postgresql_primary', {export_run_literal}, {manifest['fileCount']}, {manifest['objectCount']}, {package_hash_literal},",
        f"    {schema_version_literal}, 'SHA256', {export_format_literal}, 'INSPECTABLE_BACKUP_ONLY', false, false, {_sql_jsonb(manifest['limitations'])},",
        "    'CONFIRMED', 'm7_export', 'ACTIVE', 'SYSTEM_CONFIRMED', 'SYSTEM', 'm7_export',",
        f"    {package_hash_literal}",
        "  FROM project_row",
        "  ON CONFLICT (project_id, backup_manifest_id) DO UPDATE SET",
        "    file_count = EXCLUDED.file_count,",
        "    object_count = EXCLUDED.object_count,",
        "    manifest_hash = EXCLUDED.manifest_hash,",
        "    manifest_schema_version = EXCLUDED.manifest_schema_version,",
        "    content_hash = EXCLUDED.content_hash,",
        "    updated_at = now()",
        "  RETURNING id, project_id",
        ")",
        "INSERT INTO legacy_json_export_runs (",
        "  project_id, export_run_id, backup_manifest_id, export_mode, export_result, artifact_root, file_count, object_count, package_hash,",
        "  manifest_schema_version, export_format, status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
        ")",
        "SELECT",
        f"  project_id, {export_run_literal}, id, {_sql_literal(package.export_mode)}, 'PASS', {export_run_literal},",
        f"  {manifest['fileCount']}, {manifest['objectCount']}, {package_hash_literal}, {schema_version_literal}, {export_format_literal},",
        "  'CONFIRMED', 'm7_export', 'ACTIVE', 'SYSTEM_CONFIRMED', 'SYSTEM', 'm7_export',",
        f"  {package_hash_literal}",
        "FROM manifest_row",
        "ON CONFLICT (project_id, export_run_id) DO UPDATE SET",
        "  backup_manifest_id = EXCLUDED.backup_manifest_id,",
        "  export_result = EXCLUDED.export_result,",
        "  file_count = EXCLUDED.file_count,",
        "  object_count = EXCLUDED.object_count,",
        "  package_hash = EXCLUDED.package_hash,",
        "  updated_at = now();",
        "",
    ]

    file_values = []
    for file_entry in manifest["files"]:
        file_values.append(
            "  ("
            + ", ".join(
                [
                    _sql_literal(file_entry["relativePath"]),
                    "'TOP_LEVEL_JSON'",
                    str(file_entry["objectCount"]),
                    str(file_entry["byteCount"]),
                    _sql_literal(file_entry["contentHash"]),
                    _sql_literal(file_entry["canonicalContentHash"]),
                ]
            )
            + ")"
        )

    lines.extend(
        [
            "WITH files_to_export(relative_path, json_shape, object_count, byte_count, file_content_hash, content_hash) AS (",
            "  VALUES",
            ",\n".join(file_values),
            "), export_run AS (",
            "  SELECT r.id, r.project_id, r.backup_manifest_id",
            "  FROM legacy_json_export_runs r",
            "  JOIN projects p ON p.id = r.project_id",
            f"  WHERE p.project_id = {project_literal}",
            f"    AND r.export_run_id = {export_run_literal}",
            ")",
            "INSERT INTO legacy_json_export_files (",
            "  project_id, export_run_id, backup_manifest_id, relative_path, json_shape, object_count, byte_count, file_content_hash,",
            "  manifest_schema_version, export_format, status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
            ")",
            "SELECT",
            "  r.project_id, r.id, r.backup_manifest_id, f.relative_path, f.json_shape, f.object_count, f.byte_count, f.file_content_hash,",
            f"  {schema_version_literal}, {export_format_literal}, 'CONFIRMED', 'm7_export', 'ACTIVE', 'SYSTEM_CONFIRMED', 'SYSTEM', 'm7_export',",
            "  f.content_hash",
            "FROM export_run r",
            "CROSS JOIN files_to_export f",
            "ON CONFLICT (project_id, export_run_id, relative_path) DO UPDATE SET",
            "  backup_manifest_id = EXCLUDED.backup_manifest_id,",
            "  object_count = EXCLUDED.object_count,",
            "  byte_count = EXCLUDED.byte_count,",
            "  file_content_hash = EXCLUDED.file_content_hash,",
            "  content_hash = EXCLUDED.content_hash,",
            "  updated_at = now();",
        ]
    )

    if package.limitations:
        limitation_values = []
        for index, limitation in enumerate(package.limitations):
            limitation_id = limitation.get("limitationId", f"{package.export_run_id}:limitation:{index + 1}")
            limitation_values.append(
                "  ("
                + ", ".join(
                    [
                        _sql_literal(str(limitation_id)),
                        _sql_literal(str(limitation.get("kind", "MANUAL_REVIEW_REQUIRED"))),
                        _sql_literal(str(limitation.get("severity", "WARN"))),
                        _sql_literal(str(limitation.get("text", "Manual recovery review is required."))),
                        _sql_literal(str(limitation.get("recommendedAction", "Inspect exported JSON before recovery."))),
                        _sql_literal(stable_json_hash(limitation)),
                    ]
                )
                + ")"
            )

        lines.extend(
            [
                "",
                "WITH limitations_to_record(limitation_id, limitation_kind, severity, limitation_text, recommended_action, content_hash) AS (",
                "  VALUES",
                ",\n".join(limitation_values),
                "), export_run AS (",
                "  SELECT r.project_id, r.backup_manifest_id",
                "  FROM legacy_json_export_runs r",
                "  JOIN projects p ON p.id = r.project_id",
                f"  WHERE p.project_id = {project_literal}",
                f"    AND r.export_run_id = {export_run_literal}",
                ")",
                "INSERT INTO legacy_json_recovery_limitations (",
                "  project_id, backup_manifest_id, limitation_id, limitation_kind, severity, limitation_text, recommended_action,",
                "  status, legacy_status_raw, lifecycle_state, authority_level, source_type, source_id, content_hash",
                ")",
                "SELECT",
                "  r.project_id, r.backup_manifest_id, l.limitation_id, l.limitation_kind, l.severity, l.limitation_text, l.recommended_action,",
                "  'CONFIRMED', 'm7_export', 'ACTIVE', 'SYSTEM_CONFIRMED', 'SYSTEM', 'm7_export',",
                "  l.content_hash",
                "FROM export_run r",
                "CROSS JOIN limitations_to_record l",
                "ON CONFLICT (project_id, backup_manifest_id, limitation_id) DO UPDATE SET",
                "  limitation_kind = EXCLUDED.limitation_kind,",
                "  severity = EXCLUDED.severity,",
                "  limitation_text = EXCLUDED.limitation_text,",
                "  recommended_action = EXCLUDED.recommended_action,",
                "  content_hash = EXCLUDED.content_hash,",
                "  updated_at = now();",
            ]
        )

    return "\n".join(lines) + "\n"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_jsonb(value: Any) -> str:
    return _sql_literal(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) + "::jsonb"
