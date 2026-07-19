from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

from app.backend.core.config import settings
from app.backend.models.analyzer_handoff_import import (
    AnalyzerHandoffImportIssue,
    AnalyzerHandoffImportResult,
)
from app.backend.storage.json_store import JsonStore, StorageError


VALIDATED_HANDOFF_FILE = "unified_generator_handoff.validated.json"
GENERATOR_HANDOFF_DIR = "generator_handoff"
SOURCE_REFERENCE_INDEX_FILE = "source_reference_index.json"
SUPPORTED_HANDOFF_VERSIONS = {"generator_handoff.v1"}
APP_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    APP_ROOT
    / "backend"
    / "contracts"
    / "story_analyzer_handoff"
    / "generator_handoff.v1.schema.json"
)


def blocking_issue(
    code: str,
    message: str,
    *,
    field_path: str | None = None,
    safe_detail: str | None = None,
) -> AnalyzerHandoffImportIssue:
    return AnalyzerHandoffImportIssue(
        code=code,
        severity="blocking",
        field_path=field_path,
        message=message,
        safe_detail=safe_detail,
    )


class AnalyzerHandoffImportService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        schema_path: Path | None = None,
        allowed_roots: Sequence[Path] | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.schema_path = schema_path or SCHEMA_PATH
        configured_roots = allowed_roots or settings.analyzer_output_roots
        self.allowed_roots = tuple(
            dict.fromkeys(path.expanduser().resolve() for path in configured_roots)
        )
        if not self.allowed_roots:
            raise ValueError("At least one analyzer output root must be configured.")

    def import_output(self, output_dir: str | Path) -> AnalyzerHandoffImportResult:
        try:
            root = self._resolve_output_root(output_dir)
        except ValueError:
            return self._unsafe_path_result(
                output_dir,
                code="output_dir_outside_allowed_roots",
                message="Analyzer output directory is outside the configured import roots.",
            )
        files_read: list[str] = []
        try:
            expected_paths = [
                self._resolve_artifact_path(path)
                for path in self._expected_handoff_paths(root)
            ]
        except ValueError:
            return self._unsafe_path_result(
                root,
                code="handoff_path_outside_allowed_root",
                message="Analyzer handoff path escapes the configured import root.",
            )
        handoff_path = next((path for path in expected_paths if path.exists()), None)
        if handoff_path is None:
            return AnalyzerHandoffImportResult(
                import_status="missing_validated_handoff",
                output_dir=str(root),
                issues=[
                    blocking_issue(
                        "missing_validated_handoff",
                        "Validated analyzer handoff was not found.",
                        safe_detail=(
                            "Expected generator_handoff/"
                            f"{VALIDATED_HANDOFF_FILE} under the selected analyzer output."
                        ),
                    )
                ],
                safe_summary="Analyzer output cannot be imported until the validated handoff exists.",
            )

        issues: list[AnalyzerHandoffImportIssue] = []
        schema = self._read_json(self.schema_path, files_read, issues, "schema_read_failed")
        handoff = self._read_json(handoff_path, files_read, issues, "handoff_read_failed")
        if not isinstance(schema, dict):
            issues.append(
                blocking_issue(
                    "schema_validation_failed",
                    "Frozen handoff schema root must be a JSON object.",
                    field_path="$schema",
                )
            )
            schema = {}
        if not isinstance(handoff, dict):
            issues.append(
                blocking_issue(
                    "schema_validation_failed",
                    "Validated handoff root must be a JSON object.",
                    field_path="$",
                )
            )
            handoff = {}

        if handoff:
            issues.extend(self._handoff_version_issues(handoff))
        if schema and handoff:
            issues.extend(_SchemaSubsetValidator(schema).validate(handoff))
        issues.extend(self._quality_gate_issues(handoff))
        source_reference_index_path = self._resolve_source_reference_index(
            handoff,
            handoff_path,
            files_read,
            issues,
        )

        quality_gate = handoff.get("quality_gate") if isinstance(handoff, dict) else {}
        if not isinstance(quality_gate, dict):
            quality_gate = {}
        generator_materials = handoff.get("generator_materials", [])
        if not isinstance(generator_materials, list):
            generator_materials = []

        return AnalyzerHandoffImportResult(
            import_status="blocked" if issues else "ready",
            output_dir=str(root),
            handoff_path=str(handoff_path),
            source_reference_index_path=(
                str(source_reference_index_path) if source_reference_index_path else None
            ),
            files_read=files_read,
            quality_gate_summary=dict(quality_gate),
            material_count=len(generator_materials),
            source_total_chapters=_int_or_none(quality_gate.get("source_total_chapters")),
            analysis_unit_count=_int_or_none(quality_gate.get("analysis_unit_count")),
            arc_count=_int_or_none(quality_gate.get("arc_count")),
            expected_arc_count=_int_or_none(quality_gate.get("expected_arc_count")),
            issues=issues,
            safe_summary=(
                "Validated analyzer handoff is ready for generator-side material selection."
                if not issues
                else "Validated analyzer handoff is blocked before generator consumption."
            ),
        )

    def _resolve_output_root(self, output_dir: str | Path) -> Path:
        candidate = Path(output_dir).expanduser()
        if not candidate.is_absolute():
            candidate = self.allowed_roots[0] / candidate
        resolved = candidate.resolve()
        if not self._is_within_allowed_root(resolved):
            raise ValueError("Analyzer output directory is outside allowed roots.")
        return resolved

    def _resolve_artifact_path(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if not self._is_within_allowed_root(resolved):
            raise ValueError("Analyzer artifact path is outside allowed roots.")
        return resolved

    def _is_within_allowed_root(self, path: Path) -> bool:
        return any(
            path == root or path.is_relative_to(root)
            for root in self.allowed_roots
        )

    def _unsafe_path_result(
        self,
        output_dir: str | Path,
        *,
        code: str,
        message: str,
    ) -> AnalyzerHandoffImportResult:
        return AnalyzerHandoffImportResult(
            import_status="blocked",
            output_dir=str(output_dir),
            issues=[
                blocking_issue(
                    code,
                    message,
                    safe_detail="Configure MULTIPLE_AGENT_STORIES_ANALYZER_OUTPUT_ROOTS on the server.",
                )
            ],
            safe_summary="Analyzer output import was blocked by the path safety policy.",
        )

    def _handoff_version_issues(self, handoff: dict[str, Any]) -> list[AnalyzerHandoffImportIssue]:
        version = handoff.get("handoff_version")
        if version in SUPPORTED_HANDOFF_VERSIONS:
            return []
        return [
            blocking_issue(
                "unsupported_handoff_version",
                "Validated analyzer handoff version is not supported by this generator adapter.",
                field_path="handoff_version",
                safe_detail=(
                    f"received={version!r}; supported={sorted(SUPPORTED_HANDOFF_VERSIONS)}"
                ),
            )
        ]

    def _expected_handoff_paths(self, root: Path) -> list[Path]:
        if root.name.lower() == "output":
            candidates = [root / GENERATOR_HANDOFF_DIR / VALIDATED_HANDOFF_FILE]
        else:
            candidates = [
                root / "output" / GENERATOR_HANDOFF_DIR / VALIDATED_HANDOFF_FILE,
                root / GENERATOR_HANDOFF_DIR / VALIDATED_HANDOFF_FILE,
            ]
        unique: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path)
            if key not in seen:
                unique.append(path)
                seen.add(key)
        return unique

    def _read_json(
        self,
        path: Path,
        files_read: list[str],
        issues: list[AnalyzerHandoffImportIssue],
        failure_code: str,
    ) -> Any:
        files_read.append(str(path))
        try:
            return self.store.read_any(path)
        except StorageError as exc:
            issues.append(
                blocking_issue(
                    failure_code,
                    "Required JSON file could not be read.",
                    safe_detail=str(exc),
                )
            )
            return None

    def _quality_gate_issues(self, handoff: dict[str, Any]) -> list[AnalyzerHandoffImportIssue]:
        issues: list[AnalyzerHandoffImportIssue] = []
        quality_gate = handoff.get("quality_gate", {})
        if not isinstance(quality_gate, dict):
            return [
                blocking_issue(
                    "quality_gate_invalid",
                    "quality_gate must be a JSON object.",
                    field_path="quality_gate",
                )
            ]
        validator_summary = handoff.get("validator_summary", {})
        if not isinstance(validator_summary, dict):
            validator_summary = {}
        generator_materials = handoff.get("generator_materials", [])

        required_values = {
            "run_status": "completed",
            "source_leak_status": "passed",
            "abstraction_quality_status": "passed",
        }
        for field_name, expected in required_values.items():
            if quality_gate.get(field_name) != expected:
                issues.append(
                    blocking_issue(
                        f"quality_{field_name}_failed",
                        f"quality_gate.{field_name} must be {expected}.",
                        field_path=f"quality_gate.{field_name}",
                    )
                )
        if quality_gate.get("missing_required_outputs") not in ([], None):
            issues.append(
                blocking_issue(
                    "quality_missing_required_outputs",
                    "quality_gate.missing_required_outputs must be empty.",
                    field_path="quality_gate.missing_required_outputs",
                )
            )
        for field_name in ("failed_chapter_count", "llm_unrecovered_failed_target_count"):
            if _int_or_none(quality_gate.get(field_name)) != 0:
                issues.append(
                    blocking_issue(
                        f"quality_{field_name}_nonzero",
                        f"quality_gate.{field_name} must be 0.",
                        field_path=f"quality_gate.{field_name}",
                    )
                )
        if quality_gate.get("arc_count") != quality_gate.get("expected_arc_count"):
            issues.append(
                blocking_issue(
                    "quality_arc_count_mismatch",
                    "quality_gate.arc_count must equal quality_gate.expected_arc_count.",
                    field_path="quality_gate.arc_count",
                )
            )
        if validator_summary.get("validation_status") not in (
            "passed",
            "passed_with_warnings",
        ):
            issues.append(
                blocking_issue(
                    "validator_status_not_passed",
                    "validator_summary.validation_status must be passed or passed_with_warnings.",
                    field_path="validator_summary.validation_status",
                )
            )
        if _int_or_none(validator_summary.get("blocking_issue_count")) not in (0, None):
            issues.append(
                blocking_issue(
                    "validator_blocking_issues_present",
                    "validator_summary.blocking_issue_count must be 0.",
                    field_path="validator_summary.blocking_issue_count",
                )
            )
        if not isinstance(generator_materials, list) or not generator_materials:
            issues.append(
                blocking_issue(
                    "generator_materials_empty",
                    "generator_materials must contain at least one material.",
                    field_path="generator_materials",
                )
            )
        return issues

    def _resolve_source_reference_index(
        self,
        handoff: dict[str, Any],
        handoff_path: Path,
        files_read: list[str],
        issues: list[AnalyzerHandoffImportIssue],
    ) -> Path | None:
        ref = handoff.get("source_reference_index_ref")
        if not isinstance(ref, str) or not ref:
            issues.append(
                blocking_issue(
                    "source_reference_index_ref_missing",
                    "source_reference_index_ref must be present.",
                    field_path="source_reference_index_ref",
                )
            )
            return None
        ref_path = Path(ref)
        if ref_path.is_absolute() or ".." in ref_path.parts:
            issues.append(
                blocking_issue(
                    "source_reference_index_ref_unsafe",
                    "source_reference_index_ref must be a safe relative file path.",
                    field_path="source_reference_index_ref",
                )
            )
            return None
        try:
            source_index_path = self._resolve_artifact_path(
                handoff_path.parent / ref_path
            )
        except ValueError:
            issues.append(
                blocking_issue(
                    "source_reference_index_ref_unsafe",
                    "source_reference_index_ref escapes the configured analyzer root.",
                    field_path="source_reference_index_ref",
                )
            )
            return None
        source_index = self._read_json(
            source_index_path,
            files_read,
            issues,
            "source_reference_index_read_failed",
        )
        if source_index is not None and not isinstance(source_index, dict):
            issues.append(
                blocking_issue(
                    "source_reference_index_invalid",
                    "source reference index root must be a JSON object.",
                    field_path="source_reference_index_ref",
                )
            )
        return source_index_path


class _SchemaSubsetValidator:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema

    def validate(self, payload: Any) -> list[AnalyzerHandoffImportIssue]:
        return self._validate(payload, self.schema, "$")

    def _validate(
        self,
        value: Any,
        schema: dict[str, Any],
        field_path: str,
    ) -> list[AnalyzerHandoffImportIssue]:
        if "$ref" in schema:
            resolved = self._resolve_ref(str(schema["$ref"]))
            if resolved is None:
                return [
                    self._issue(
                        field_path,
                        f"Unsupported schema reference: {schema['$ref']}",
                    )
                ]
            return self._validate(value, resolved, field_path)

        issues: list[AnalyzerHandoffImportIssue] = []
        expected_type = schema.get("type")
        if expected_type is not None and not _matches_json_type(value, expected_type):
            return [
                self._issue(
                    field_path,
                    f"Expected type {expected_type}, got {type(value).__name__}.",
                )
            ]

        if "const" in schema and value != schema["const"]:
            issues.append(
                self._issue(field_path, f"Expected constant value {schema['const']!r}.")
            )
        if "enum" in schema and value not in schema["enum"]:
            issues.append(self._issue(field_path, "Value is not in the allowed enum."))

        if isinstance(value, dict):
            required = schema.get("required", [])
            if isinstance(required, list):
                for field_name in required:
                    if field_name not in value:
                        issues.append(
                            self._issue(
                                _join_path(field_path, str(field_name)),
                                "Required field is missing.",
                            )
                        )
            properties = schema.get("properties", {})
            if isinstance(properties, dict):
                for field_name, field_schema in properties.items():
                    if field_name in value and isinstance(field_schema, dict):
                        issues.extend(
                            self._validate(
                                value[field_name],
                                field_schema,
                                _join_path(field_path, field_name),
                            )
                        )

        if isinstance(value, list):
            min_items = schema.get("minItems")
            max_items = schema.get("maxItems")
            if isinstance(min_items, int) and len(value) < min_items:
                issues.append(self._issue(field_path, f"Expected at least {min_items} items."))
            if isinstance(max_items, int) and len(value) > max_items:
                issues.append(self._issue(field_path, f"Expected at most {max_items} items."))
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    issues.extend(
                        self._validate(item, item_schema, f"{field_path}[{index}]")
                    )

        if isinstance(value, str):
            min_length = schema.get("minLength")
            pattern = schema.get("pattern")
            if isinstance(min_length, int) and len(value) < min_length:
                issues.append(
                    self._issue(field_path, f"Expected string length >= {min_length}.")
                )
            if isinstance(pattern, str) and not re.search(pattern, value):
                issues.append(self._issue(field_path, f"String does not match {pattern}."))

        if isinstance(value, int) and not isinstance(value, bool):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, int) and value < minimum:
                issues.append(self._issue(field_path, f"Expected value >= {minimum}."))
            if isinstance(maximum, int) and value > maximum:
                issues.append(self._issue(field_path, f"Expected value <= {maximum}."))

        any_of = schema.get("anyOf")
        if isinstance(any_of, list):
            branch_results = [
                self._validate(value, branch, field_path)
                for branch in any_of
                if isinstance(branch, dict)
            ]
            if branch_results and not any(not result for result in branch_results):
                issues.append(self._issue(field_path, "Value does not match anyOf."))

        return issues

    def _resolve_ref(self, ref: str) -> dict[str, Any] | None:
        if ref == "#/$defs/sourceRefs":
            defs = self.schema.get("$defs", {})
            source_refs = defs.get("sourceRefs") if isinstance(defs, dict) else None
            return source_refs if isinstance(source_refs, dict) else None
        return None

    def _issue(self, field_path: str, message: str) -> AnalyzerHandoffImportIssue:
        return blocking_issue(
            "schema_validation_failed",
            message,
            field_path=field_path,
        )


def _matches_json_type(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_json_type(value, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(
            value,
            bool,
        )
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _join_path(base: str, field_name: str) -> str:
    return f"{base}.{field_name}" if base else field_name


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
