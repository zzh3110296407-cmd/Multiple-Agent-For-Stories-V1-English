from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models.plugin_protocol import PluginInputValidationReport, PluginInputValidationRequest
from ..storage.json_store import JsonStore, StorageError
from .plugin_manifest_service import (
    INPUT_VALIDATION_REPORTS_FILE,
    MANIFESTS_FILE,
    M1_M2_PACKAGE_FILES,
    PluginManifestService,
    assert_safe_payload,
    model_to_dict,
    now_iso,
    sanitize_user_note,
)


SNAPSHOTS_FILE = "final_story_package_snapshots.json"
FINAL_PACKAGE_MANIFESTS_FILE = "final_story_package_manifests.json"
EVIDENCE_INDEXES_FILE = "final_story_package_evidence_indexes.json"
SAFETY_AUDITS_FILE = "final_story_package_safety_audits.json"


class PluginInputValidationService:
    """Validate M2 Final Story Package snapshots against inert M3 plugin input schemas."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        read_only_static: bool = False,
    ) -> None:
        self.store = store or JsonStore()
        self.manifest_service = PluginManifestService(
            store=self.store,
            data_dir=data_dir,
            read_only_static=read_only_static,
        )
        self.data_dir = self.manifest_service.data_dir

    def validate_input(self, plugin_id: str, request: PluginInputValidationRequest) -> PluginInputValidationReport:
        self.manifest_service._ensure_or_assert_static_records()
        if not request.snapshot_id.strip():
            raise StorageError("PLUGIN_INPUT_VALIDATION_SNAPSHOT_REQUIRED")
        safe_user_note = sanitize_user_note(request.safe_user_note)
        manifest = self.manifest_service.get_manifest(plugin_id)
        input_schema = self.manifest_service.get_input_schema(plugin_id)
        created_at = now_iso()
        snapshot = self._find_record(SNAPSHOTS_FILE, "snapshot_id", request.snapshot_id)
        if snapshot is None:
            report = self._build_missing_snapshot_report(
                plugin_id=plugin_id,
                manifest_id=manifest.manifest_id,
                input_schema_id=input_schema.input_schema_id,
                snapshot_id=request.snapshot_id,
                safe_user_note=safe_user_note,
                created_at=created_at,
            )
            assert_safe_payload(model_to_dict(report), context="plugin_missing_snapshot_report")
            return report

        package_manifest = self._find_record(FINAL_PACKAGE_MANIFESTS_FILE, "manifest_id", snapshot.get("manifest_id", ""))
        evidence_index = self._find_record(EVIDENCE_INDEXES_FILE, "snapshot_id", request.snapshot_id)
        safety_audit = self._find_record(SAFETY_AUDITS_FILE, "snapshot_id", request.snapshot_id)
        companion_checks = {
            "FinalStoryPackageSnapshot": True,
            "FinalStoryPackageManifest": package_manifest is not None,
            "FinalStoryPackageEvidenceIndex": evidence_index is not None,
            "FinalStoryPackageSafetyAudit": safety_audit is not None,
        }
        field_checks = {
            field: self._field_present(snapshot, field)
            for field in input_schema.required_snapshot_fields
        }
        missing_fields = [field for field, ok in field_checks.items() if not ok]
        blocked_reasons: list[str] = []
        warning_codes: list[str] = []

        if manifest.availability_status == "blocked":
            blocked_reasons.append("plugin_manifest_blocked")
        if manifest.runtime_available or manifest.can_create_plugin_run:
            blocked_reasons.append("m3_runtime_must_remain_disabled")
        if not manifest.requires_final_story_package_snapshot or not input_schema.requires_final_story_package_snapshot:
            blocked_reasons.append("snapshot_input_required")
        if manifest.allow_live_story_state_input or input_schema.allow_live_story_state_input:
            blocked_reasons.append("live_story_state_input_not_allowed")
        if manifest.allow_unconfirmed_draft_input or input_schema.allow_unconfirmed_draft_input:
            blocked_reasons.append("unconfirmed_draft_input_not_allowed")
        if manifest.allow_phase6_proposal_as_truth or input_schema.allow_phase6_proposal_as_truth:
            blocked_reasons.append("phase6_proposal_truth_not_allowed")
        if manifest.allow_fixture_input or input_schema.allow_fixture_input:
            blocked_reasons.append("fixture_input_not_allowed")
        if manifest.mutates_source_story:
            blocked_reasons.append("source_story_mutation_not_allowed")
        if missing_fields:
            blocked_reasons.append("required_snapshot_fields_missing")
        if not all(companion_checks.values()):
            blocked_reasons.append("required_companion_record_missing")
        blocked_reasons.extend(
            self._validate_snapshot_markers(
                snapshot=snapshot,
                compatible_schema_versions=input_schema.compatible_snapshot_schema_versions,
            )
        )
        blocked_reasons.extend(self._validate_package_manifest(snapshot, package_manifest))
        blocked_reasons.extend(self._validate_evidence_index(snapshot, evidence_index))
        blocked_reasons.extend(self._validate_safety_audit(snapshot, safety_audit))

        blocked_reasons = sorted(set(blocked_reasons))
        warning_codes = sorted(set(warning_codes))
        input_valid = not blocked_reasons
        report = PluginInputValidationReport(
            input_validation_report_id=self._report_id(plugin_id, request.snapshot_id, created_at),
            plugin_id=plugin_id,
            manifest_id=manifest.manifest_id,
            input_schema_id=input_schema.input_schema_id,
            snapshot_id=request.snapshot_id,
            project_id=str(snapshot.get("project_id") or ""),
            validation_status="valid_for_future_runtime" if input_valid else "blocked",
            input_valid=input_valid,
            plugin_runtime_available=False,
            can_create_plugin_run_now=False,
            can_create_plugin_run_later=input_valid,
            package_type=str(snapshot.get("package_type") or ""),
            snapshot_status=str(snapshot.get("snapshot_status") or ""),
            can_be_used_by_plugins=snapshot.get("can_be_used_by_plugins") is True,
            not_real_project_final_package=snapshot.get("not_real_project_final_package") is not False,
            required_record_checks=companion_checks,
            required_snapshot_field_checks=field_checks,
            missing_required_fields=missing_fields,
            blocked_reason_codes=blocked_reasons,
            warning_codes=warning_codes,
            evidence_index_id=str((evidence_index or {}).get("evidence_index_id") or ""),
            safety_audit_id=str((safety_audit or {}).get("safety_audit_id") or ""),
            source_ref_count=len(snapshot.get("source_ref_ids") or []),
            complete_story_text_hash=str(snapshot.get("complete_story_text_hash") or ""),
            complete_story_text_char_count=int(snapshot.get("complete_story_text_char_count") or 0),
            full_story_text_copied=False,
            safe_user_note=safe_user_note,
            created_at=created_at,
            safe_summary=(
                "Snapshot is eligible for future plugin runtime; M3 did not create a plugin run."
                if input_valid
                else "Snapshot is blocked for future plugin input until the listed reasons are resolved."
            ),
        )
        self._assert_no_full_story_copy(report, snapshot)
        assert_safe_payload(model_to_dict(report), context="plugin_input_validation_report")
        if request.persist_validation_report and input_valid:
            self._append_validation_report(report)
        return report

    def _build_missing_snapshot_report(
        self,
        *,
        plugin_id: str,
        manifest_id: str,
        input_schema_id: str,
        snapshot_id: str,
        safe_user_note: str,
        created_at: str,
    ) -> PluginInputValidationReport:
        return PluginInputValidationReport(
            input_validation_report_id=self._report_id(plugin_id, snapshot_id, created_at),
            plugin_id=plugin_id,
            manifest_id=manifest_id,
            input_schema_id=input_schema_id,
            snapshot_id=snapshot_id,
            validation_status="unsupported",
            input_valid=False,
            plugin_runtime_available=False,
            can_create_plugin_run_now=False,
            can_create_plugin_run_later=False,
            required_record_checks={
                "FinalStoryPackageSnapshot": False,
                "FinalStoryPackageManifest": False,
                "FinalStoryPackageEvidenceIndex": False,
                "FinalStoryPackageSafetyAudit": False,
            },
            required_snapshot_field_checks={},
            missing_required_fields=[],
            blocked_reason_codes=["snapshot_not_found"],
            warning_codes=[],
            full_story_text_copied=False,
            safe_user_note=safe_user_note,
            created_at=created_at,
            safe_summary="No M2 snapshot exists for this id; M3 does not create exports or read live story state.",
        )

    def _append_validation_report(self, report: PluginInputValidationReport) -> None:
        path = self.data_dir / INPUT_VALIDATION_REPORTS_FILE
        rows = self._read_list(INPUT_VALIDATION_REPORTS_FILE)
        rows.append(model_to_dict(report))
        assert_safe_payload(rows, context=INPUT_VALIDATION_REPORTS_FILE)
        self.store.write(path, rows)

    def _find_record(self, file_name: str, id_field: str, expected_id: str) -> dict[str, Any] | None:
        if not expected_id:
            return None
        for row in self._read_list(file_name):
            if isinstance(row, dict) and row.get(id_field) == expected_id:
                return row
        return None

    def _read_list(self, file_name: str) -> list[Any]:
        path = self.data_dir / file_name
        if not path.exists():
            return []
        data = self.store.read_any(path)
        if not isinstance(data, list):
            raise StorageError(f"PLUGIN_PROTOCOL_STORAGE_NOT_LIST:{file_name}")
        return data

    def _field_present(self, snapshot: dict[str, Any], field: str) -> bool:
        if field not in snapshot:
            return False
        value = snapshot.get(field)
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, dict)):
            return len(value) > 0
        return True

    def _validate_snapshot_markers(
        self,
        *,
        snapshot: dict[str, Any],
        compatible_schema_versions: list[str],
    ) -> list[str]:
        reasons: list[str] = []
        if snapshot.get("package_type") != "real_project_final_package":
            reasons.append("fixture_snapshot_blocked")
        if snapshot.get("snapshot_status") != "created":
            reasons.append("snapshot_status_not_created")
        if snapshot.get("can_be_used_by_plugins") is not True:
            reasons.append("snapshot_not_plugin_usable")
        if snapshot.get("not_real_project_final_package") is not False:
            reasons.append("snapshot_non_real_marker_invalid")
        if not snapshot.get("complete_story_text_hash"):
            reasons.append("complete_story_text_hash_missing")
        if snapshot.get("content_schema_version") not in compatible_schema_versions:
            reasons.append("snapshot_schema_version_incompatible")
        return reasons

    def _validate_package_manifest(
        self,
        snapshot: dict[str, Any],
        package_manifest: dict[str, Any] | None,
    ) -> list[str]:
        if package_manifest is None:
            return []
        reasons: list[str] = []
        identity_fields = [
            "final_story_package_id",
            "project_id",
            "readiness_status",
        ]
        if any(package_manifest.get(field) != snapshot.get(field) for field in identity_fields):
            reasons.append("manifest_snapshot_identity_mismatch")
        if package_manifest.get("package_type") != snapshot.get("package_type"):
            reasons.append("manifest_package_type_mismatch")
        if package_manifest.get("not_real_project_final_package") is not False:
            reasons.append("manifest_non_real_marker_invalid")
        return reasons

    def _validate_evidence_index(
        self,
        snapshot: dict[str, Any],
        evidence_index: dict[str, Any] | None,
    ) -> list[str]:
        if evidence_index is None:
            return []
        reasons: list[str] = []
        identity_fields = [
            "snapshot_id",
            "final_story_package_id",
            "project_id",
            "readiness_status",
        ]
        if any(evidence_index.get(field) != snapshot.get(field) for field in identity_fields):
            reasons.append("evidence_snapshot_identity_mismatch")
        if evidence_index.get("package_type") != snapshot.get("package_type"):
            reasons.append("evidence_package_type_mismatch")
        if evidence_index.get("not_real_project_final_package") is not False:
            reasons.append("evidence_non_real_marker_invalid")
        if evidence_index.get("can_be_used_by_plugins") is not True:
            reasons.append("evidence_index_not_plugin_usable")
        return reasons

    def _validate_safety_audit(
        self,
        snapshot: dict[str, Any],
        safety_audit: dict[str, Any] | None,
    ) -> list[str]:
        if safety_audit is None:
            return []
        reasons: list[str] = []
        if safety_audit.get("snapshot_id") != snapshot.get("snapshot_id"):
            reasons.append("safety_audit_snapshot_identity_mismatch")
        if safety_audit.get("passed") is not True:
            reasons.append("safety_audit_not_passed")
        return reasons

    def _report_id(self, plugin_id: str, snapshot_id: str, created_at: str) -> str:
        safe_snapshot = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in snapshot_id)[:72] or "missing"
        suffix = created_at.replace("-", "").replace(":", "").replace(".", "").replace("+", "_")
        return f"plugin_input_validation_report_{plugin_id}_{safe_snapshot}_{suffix}"

    def _assert_no_full_story_copy(self, report: PluginInputValidationReport, snapshot: dict[str, Any]) -> None:
        full_story = snapshot.get("complete_story_text") if isinstance(snapshot, dict) else ""
        if not isinstance(full_story, str) or not full_story:
            return
        report_text = str(model_to_dict(report))
        if full_story in report_text:
            raise StorageError("PLUGIN_PROTOCOL_FULL_STORY_TEXT_COPY_BLOCKED")


def guarded_m1_m2_files() -> list[str]:
    return list(M1_M2_PACKAGE_FILES)


def m3_manifest_file_name() -> str:
    return MANIFESTS_FILE
