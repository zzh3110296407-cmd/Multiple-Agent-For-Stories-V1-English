from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.plugin_protocol import (
    PluginCapabilityDeclaration,
    PluginInputSchema,
    PluginManifest,
    PluginOutputSchema,
    PluginOutputSchemaListResponse,
    PluginRegistryDetailResponse,
    PluginRegistryEntry,
    PluginRegistryListResponse,
    PluginRiskDeclaration,
    PluginVersionRecord,
)
from ..storage.json_store import JsonStore, StorageError


PLUGIN_PROTOCOL_VERSION = "phase7_m3_plugin_protocol_v1"
SCHEMA_VERSION = "phase7_m3_plugin_manifest_registry_v1"
STATIC_CREATED_AT = "2026-06-20T00:00:00+00:00"

MANIFESTS_FILE = "plugin_manifests.json"
REGISTRY_ENTRIES_FILE = "plugin_registry_entries.json"
INPUT_SCHEMAS_FILE = "plugin_input_schemas.json"
OUTPUT_SCHEMAS_FILE = "plugin_output_schemas.json"
CAPABILITY_DECLARATIONS_FILE = "plugin_capability_declarations.json"
RISK_DECLARATIONS_FILE = "plugin_risk_declarations.json"
VERSION_RECORDS_FILE = "plugin_version_records.json"
INPUT_VALIDATION_REPORTS_FILE = "plugin_input_validation_reports.json"

ALLOWED_M3_STORAGE_FILES = [
    MANIFESTS_FILE,
    REGISTRY_ENTRIES_FILE,
    INPUT_SCHEMAS_FILE,
    OUTPUT_SCHEMAS_FILE,
    CAPABILITY_DECLARATIONS_FILE,
    RISK_DECLARATIONS_FILE,
    VERSION_RECORDS_FILE,
    INPUT_VALIDATION_REPORTS_FILE,
]

FORBIDDEN_STORY_FACT_FILES = [
    "scenes.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "chapter_archives.json",
    "narrative_debts.json",
    "story_bible.json",
    "decisions.json",
]

M1_M2_PACKAGE_FILES = [
    "final_story_package_snapshots.json",
    "final_story_package_manifests.json",
    "final_story_package_evidence_indexes.json",
    "final_story_package_safety_audits.json",
]

FORBIDDEN_PLUGIN_RUNTIME_FILES = [
    "plugin_runs.json",
    "plugin_run_steps.json",
    "plugin_checkpoints.json",
    "plugin_checkpoint_decisions.json",
    "plugin_output_artifacts.json",
    "plugin_output_artifact_versions.json",
    "plugin_run_safety_reports.json",
    "script_forging_runs.json",
    "script_shape_packages.json",
    "screenplay_draft_artifacts.json",
    "storyboard_artifacts.json",
    "digital_asset_packages.json",
]

REQUIRED_RECORD_TYPES = ["FinalStoryPackageSnapshot"]
REQUIRED_COMPANION_RECORD_TYPES = [
    "FinalStoryPackageManifest",
    "FinalStoryPackageEvidenceIndex",
    "FinalStoryPackageSafetyAudit",
]
BLOCKED_INPUT_RECORD_TYPES = [
    "Scene",
    "Event",
    "MemoryRecord",
    "StateChange",
    "ChapterArchive",
    "NarrativeDebt",
    "StoryBible",
    "Phase6Proposal",
    "Candidate",
    "UnconfirmedDraft",
]
REQUIRED_SNAPSHOT_FIELDS = [
    "snapshot_id",
    "project_id",
    "final_story_package_id",
    "readiness_gate_id",
    "validation_report_id",
    "manifest_id",
    "package_type",
    "snapshot_status",
    "content_schema_version",
    "source_ref_ids",
    "source_version_ids",
    "complete_story_text_hash",
    "complete_story_text_char_count",
    "chapter_scene_index",
    "character_table",
    "world_canvas_summary",
    "relationship_state_summary",
    "key_event_timeline",
    "user_locked_constraints",
    "style_and_tone",
    "can_be_used_by_plugins",
    "not_real_project_final_package",
]
COMPATIBLE_SNAPSHOT_SCHEMA_VERSIONS = ["phase7_m2_final_story_package_exporter_v1"]

UNSAFE_VALUE_MARKERS = (
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "api_key",
    "authorization",
    "bearer ",
    "langsmith key",
    "provider secret",
)
SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()
    return dict(model)


def sanitize_user_note(value: str, *, max_length: int = 240) -> str:
    note = (value or "").strip()
    if len(note) > max_length:
        note = note[:max_length]
    assert_safe_payload({"safe_user_note": note}, context="plugin_safe_user_note")
    return note


def assert_safe_payload(payload: Any, *, context: str) -> None:
    def scan(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                scan(child, f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")
            return
        if isinstance(value, str):
            lowered = value.lower()
            if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                raise StorageError(f"PLUGIN_PROTOCOL_UNSAFE_PAYLOAD_BLOCKED:{context}:{path}")
            if SECRET_LIKE_RE.search(value):
                raise StorageError(f"PLUGIN_PROTOCOL_UNSAFE_PAYLOAD_BLOCKED:{context}:{path}")

    scan(payload, context)


class PluginManifestService:
    """Phase 7 M3 first-party plugin protocol metadata service."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        read_only_static: bool = False,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.read_only_static = read_only_static

    def list_plugins(self) -> PluginRegistryListResponse:
        self._ensure_or_assert_static_records()
        entries = sorted(self._load_registry_entries(), key=lambda item: item.display_order)
        manifests = sorted(self._load_manifests(), key=lambda item: self._entry_for(item.plugin_id).display_order)
        return PluginRegistryListResponse(
            registry_entries=entries,
            manifests=manifests,
            total_count=len(entries),
            safe_summary="Phase 7 M3 lists first-party plugin protocol metadata only; no plugin runtime is available.",
        )

    def get_plugin(self, plugin_id: str) -> PluginRegistryDetailResponse:
        self._ensure_or_assert_static_records()
        entry = self._entry_for(plugin_id)
        manifest = self.get_manifest(plugin_id)
        input_schema = self.get_input_schema(plugin_id)
        output_schemas = self.get_output_schemas(plugin_id).output_schemas
        capability = self.get_capability_declaration(plugin_id)
        risk = self.get_risk_declaration(plugin_id)
        version = self.get_version_record(plugin_id)
        return PluginRegistryDetailResponse(
            registry_entry=entry,
            manifest=manifest,
            input_schema=input_schema,
            output_schemas=output_schemas,
            capability_declaration=capability,
            risk_declaration=risk,
            version_record=version,
            safe_summary="M3 detail exposes protocol, manifest, schema, capability, risk, and version metadata only.",
        )

    def get_manifest(self, plugin_id: str) -> PluginManifest:
        self._ensure_or_assert_static_records()
        for manifest in self._load_manifests():
            if manifest.plugin_id == plugin_id:
                return manifest
        raise StorageError(f"PLUGIN_MANIFEST_NOT_FOUND:{plugin_id}")

    def get_input_schema(self, plugin_id: str) -> PluginInputSchema:
        self._ensure_or_assert_static_records()
        for schema in self._load_input_schemas():
            if schema.plugin_id == plugin_id:
                return schema
        raise StorageError(f"PLUGIN_INPUT_SCHEMA_NOT_FOUND:{plugin_id}")

    def get_output_schemas(self, plugin_id: str) -> PluginOutputSchemaListResponse:
        self._ensure_or_assert_static_records()
        schemas = [schema for schema in self._load_output_schemas() if schema.plugin_id == plugin_id]
        if not schemas and not self._plugin_exists(plugin_id):
            raise StorageError(f"PLUGIN_NOT_FOUND:{plugin_id}")
        return PluginOutputSchemaListResponse(plugin_id=plugin_id, output_schemas=schemas, total_count=len(schemas))

    def get_capability_declaration(self, plugin_id: str) -> PluginCapabilityDeclaration:
        self._ensure_or_assert_static_records()
        for declaration in self._load_capability_declarations():
            if declaration.plugin_id == plugin_id:
                return declaration
        raise StorageError(f"PLUGIN_CAPABILITY_DECLARATION_NOT_FOUND:{plugin_id}")

    def get_risk_declaration(self, plugin_id: str) -> PluginRiskDeclaration:
        self._ensure_or_assert_static_records()
        for declaration in self._load_risk_declarations():
            if declaration.plugin_id == plugin_id:
                return declaration
        raise StorageError(f"PLUGIN_RISK_DECLARATION_NOT_FOUND:{plugin_id}")

    def get_version_record(self, plugin_id: str) -> PluginVersionRecord:
        self._ensure_or_assert_static_records()
        for record in self._load_version_records():
            if record.plugin_id == plugin_id:
                return record
        raise StorageError(f"PLUGIN_VERSION_RECORD_NOT_FOUND:{plugin_id}")

    def ensure_seeded(self) -> None:
        builtins = self._builtin_records()
        self._write_static_list(MANIFESTS_FILE, [model_to_dict(item) for item in builtins["manifests"]])
        self._write_static_list(REGISTRY_ENTRIES_FILE, [model_to_dict(item) for item in builtins["registry_entries"]])
        self._write_static_list(INPUT_SCHEMAS_FILE, [model_to_dict(item) for item in builtins["input_schemas"]])
        self._write_static_list(OUTPUT_SCHEMAS_FILE, [model_to_dict(item) for item in builtins["output_schemas"]])
        self._write_static_list(
            CAPABILITY_DECLARATIONS_FILE,
            [model_to_dict(item) for item in builtins["capability_declarations"]],
        )
        self._write_static_list(RISK_DECLARATIONS_FILE, [model_to_dict(item) for item in builtins["risk_declarations"]])
        self._write_static_list(VERSION_RECORDS_FILE, [model_to_dict(item) for item in builtins["version_records"]])
        reports_path = self.data_dir / INPUT_VALIDATION_REPORTS_FILE
        if not self.store.exists(reports_path):
            self.store.write(reports_path, [])
        elif not isinstance(self.store.read_any(reports_path), list):
            raise StorageError(f"PLUGIN_PROTOCOL_STORAGE_NOT_LIST:{INPUT_VALIDATION_REPORTS_FILE}")

    def assert_static_records_ready(self) -> None:
        builtins = self._builtin_records()
        expected_by_file = {
            MANIFESTS_FILE: [model_to_dict(item) for item in builtins["manifests"]],
            REGISTRY_ENTRIES_FILE: [model_to_dict(item) for item in builtins["registry_entries"]],
            INPUT_SCHEMAS_FILE: [model_to_dict(item) for item in builtins["input_schemas"]],
            OUTPUT_SCHEMAS_FILE: [model_to_dict(item) for item in builtins["output_schemas"]],
            CAPABILITY_DECLARATIONS_FILE: [model_to_dict(item) for item in builtins["capability_declarations"]],
            RISK_DECLARATIONS_FILE: [model_to_dict(item) for item in builtins["risk_declarations"]],
            VERSION_RECORDS_FILE: [model_to_dict(item) for item in builtins["version_records"]],
        }
        for file_name, expected_rows in expected_by_file.items():
            path = self.data_dir / file_name
            if not self.store.exists(path):
                raise StorageError(f"PLUGIN_PROTOCOL_STATIC_RECORD_MISSING:{file_name}")
            existing = self.store.read_any(path)
            if not isinstance(existing, list):
                raise StorageError(f"PLUGIN_PROTOCOL_STORAGE_NOT_LIST:{file_name}")
            if existing != expected_rows:
                raise StorageError(f"PLUGIN_PROTOCOL_STATIC_RECORD_DRIFTED:{file_name}")

    def _ensure_or_assert_static_records(self) -> None:
        if self.read_only_static:
            self.assert_static_records_ready()
            return
        self.ensure_seeded()

    def _write_static_list(self, file_name: str, rows: list[dict[str, Any]]) -> None:
        path = self.data_dir / file_name
        assert_safe_payload(rows, context=file_name)
        if self.store.exists(path):
            existing = self.store.read_any(path)
            if not isinstance(existing, list):
                raise StorageError(f"PLUGIN_PROTOCOL_STORAGE_NOT_LIST:{file_name}")
            if existing == rows:
                return
        self.store.write(path, rows)

    def _read_list(self, file_name: str) -> list[Any]:
        path = self.data_dir / file_name
        if not self.store.exists(path):
            return []
        data = self.store.read_any(path)
        if not isinstance(data, list):
            raise StorageError(f"PLUGIN_PROTOCOL_STORAGE_NOT_LIST:{file_name}")
        return data

    def _load_manifests(self) -> list[PluginManifest]:
        return [PluginManifest(**row) for row in self._read_list(MANIFESTS_FILE)]

    def _load_registry_entries(self) -> list[PluginRegistryEntry]:
        return [PluginRegistryEntry(**row) for row in self._read_list(REGISTRY_ENTRIES_FILE)]

    def _load_input_schemas(self) -> list[PluginInputSchema]:
        return [PluginInputSchema(**row) for row in self._read_list(INPUT_SCHEMAS_FILE)]

    def _load_output_schemas(self) -> list[PluginOutputSchema]:
        return [PluginOutputSchema(**row) for row in self._read_list(OUTPUT_SCHEMAS_FILE)]

    def _load_capability_declarations(self) -> list[PluginCapabilityDeclaration]:
        return [PluginCapabilityDeclaration(**row) for row in self._read_list(CAPABILITY_DECLARATIONS_FILE)]

    def _load_risk_declarations(self) -> list[PluginRiskDeclaration]:
        return [PluginRiskDeclaration(**row) for row in self._read_list(RISK_DECLARATIONS_FILE)]

    def _load_version_records(self) -> list[PluginVersionRecord]:
        return [PluginVersionRecord(**row) for row in self._read_list(VERSION_RECORDS_FILE)]

    def _entry_for(self, plugin_id: str) -> PluginRegistryEntry:
        for entry in self._load_registry_entries():
            if entry.plugin_id == plugin_id:
                return entry
        raise StorageError(f"PLUGIN_REGISTRY_ENTRY_NOT_FOUND:{plugin_id}")

    def _plugin_exists(self, plugin_id: str) -> bool:
        return any(manifest.plugin_id == plugin_id for manifest in self._load_manifests())

    def _builtin_records(self) -> dict[str, list[BaseModel]]:
        plugin_specs = [
            {
                "plugin_id": "script_forging",
                "display_name": "Script Forging",
                "description": "Future derivative script package protocol for a completed final story snapshot.",
                "family": "script",
                "display_order": 1,
                "availability_status": "planned",
                "future_milestone": "Phase 7 M5/M6",
                "risk_level": "medium",
                "data_exposure": "controlled_final_story_snapshot",
                "outputs": [
                    ("script_shape_package", "Phase 7 M5"),
                    ("scene_outline_package", "Phase 7 M5"),
                    ("screenplay_draft_package", "Phase 7 M6"),
                ],
                "warnings": ["derivative_template_review_required"],
            },
            {
                "plugin_id": "storyboard",
                "display_name": "Storyboard",
                "description": "Future derivative storyboard and shot-list protocol for a completed final story snapshot.",
                "family": "storyboard",
                "display_order": 2,
                "availability_status": "experimental",
                "future_milestone": "Phase 7 M7",
                "risk_level": "medium",
                "data_exposure": "controlled_final_story_snapshot",
                "outputs": [("storyboard_package", "Phase 7 M7"), ("shot_list_package", "Phase 7 M7")],
                "warnings": ["visual_adaptation_review_required"],
            },
            {
                "plugin_id": "digital_asset_package",
                "display_name": "Digital Asset Package",
                "description": "Future derivative digital asset package protocol for a completed final story snapshot.",
                "family": "asset_package",
                "display_order": 3,
                "availability_status": "planned",
                "future_milestone": "Phase 7 M7",
                "risk_level": "high",
                "data_exposure": "controlled_final_story_snapshot",
                "outputs": [("digital_asset_package", "Phase 7 M7")],
                "warnings": ["asset_license_review_required", "external_platform_review_required"],
            },
        ]
        records: dict[str, list[BaseModel]] = {
            "manifests": [],
            "registry_entries": [],
            "input_schemas": [],
            "output_schemas": [],
            "capability_declarations": [],
            "risk_declarations": [],
            "version_records": [],
        }
        for spec in plugin_specs:
            plugin_id = spec["plugin_id"]
            manifest_id = f"plugin_manifest_{plugin_id}"
            registry_entry_id = f"plugin_registry_entry_{plugin_id}"
            input_schema_id = f"plugin_input_schema_{plugin_id}"
            capability_id = f"plugin_capability_{plugin_id}"
            risk_id = f"plugin_risk_{plugin_id}"
            version_id = f"plugin_version_{plugin_id}"
            output_ids = [f"plugin_output_schema_{plugin_id}_{artifact_type}" for artifact_type, _ in spec["outputs"]]
            unavailable_reason = "M3 defines protocol only; plugin runtime starts in M4 or later."
            records["registry_entries"].append(
                PluginRegistryEntry(
                    registry_entry_id=registry_entry_id,
                    plugin_id=plugin_id,
                    manifest_id=manifest_id,
                    display_order=spec["display_order"],
                    visibility="visible",
                    visible_in_selector=True,
                    availability_status=spec["availability_status"],
                    unavailable_reason=unavailable_reason,
                    created_at=STATIC_CREATED_AT,
                    updated_at=STATIC_CREATED_AT,
                    safe_summary=f"{spec['display_name']} is visible as future protocol metadata only.",
                )
            )
            records["manifests"].append(
                PluginManifest(
                    manifest_id=manifest_id,
                    plugin_id=plugin_id,
                    display_name=spec["display_name"],
                    description=spec["description"],
                    plugin_family=spec["family"],
                    registry_entry_id=registry_entry_id,
                    input_schema_id=input_schema_id,
                    output_schema_ids=output_ids,
                    capability_declaration_id=capability_id,
                    risk_declaration_id=risk_id,
                    version_record_id=version_id,
                    visibility="visible",
                    availability_status=spec["availability_status"],
                    runtime_available=False,
                    can_create_plugin_run=False,
                    requires_final_story_package_snapshot=True,
                    allow_live_story_state_input=False,
                    allow_unconfirmed_draft_input=False,
                    allow_phase6_proposal_as_truth=False,
                    allow_fixture_input=False,
                    mutates_source_story=False,
                    checkpoint_templates=[],
                    created_at=STATIC_CREATED_AT,
                    updated_at=STATIC_CREATED_AT,
                    safe_summary=f"{spec['display_name']} requires a FinalStoryPackageSnapshot and has no M3 runtime.",
                )
            )
            records["input_schemas"].append(
                PluginInputSchema(
                    input_schema_id=input_schema_id,
                    plugin_id=plugin_id,
                    requires_final_story_package_snapshot=True,
                    required_record_types=REQUIRED_RECORD_TYPES,
                    required_snapshot_fields=REQUIRED_SNAPSHOT_FIELDS,
                    required_companion_record_types=REQUIRED_COMPANION_RECORD_TYPES,
                    compatible_snapshot_schema_versions=COMPATIBLE_SNAPSHOT_SCHEMA_VERSIONS,
                    blocked_input_record_types=BLOCKED_INPUT_RECORD_TYPES,
                    allow_live_story_state_input=False,
                    allow_unconfirmed_draft_input=False,
                    allow_phase6_proposal_as_truth=False,
                    allow_fixture_input=False,
                    created_at=STATIC_CREATED_AT,
                    safe_summary="Only FinalStoryPackageSnapshot plus M2 companion records are valid future input.",
                )
            )
            for output_id, (artifact_type, future_milestone) in zip(output_ids, spec["outputs"]):
                records["output_schemas"].append(
                    PluginOutputSchema(
                        output_schema_id=output_id,
                        plugin_id=plugin_id,
                        artifact_type=artifact_type,
                        artifact_schema_version=SCHEMA_VERSION,
                        future_milestone=future_milestone,
                        derivative_only=True,
                        mutates_source_story=False,
                        requires_plugin_run=True,
                        created_at=STATIC_CREATED_AT,
                        safe_summary=f"{artifact_type} is a future derivative artifact contract only.",
                    )
                )
            records["capability_declarations"].append(
                PluginCapabilityDeclaration(
                    capability_declaration_id=capability_id,
                    plugin_id=plugin_id,
                    can_read_final_story_package_snapshot=True,
                    can_read_live_story_state=False,
                    can_read_unconfirmed_drafts=False,
                    can_read_phase6_proposals_as_truth=False,
                    can_create_plugin_run=False,
                    can_create_checkpoint=False,
                    can_create_output_artifact=False,
                    can_call_external_provider=False,
                    can_mutate_source_story=False,
                    requires_user_checkpoint_in_future=True,
                    runtime_required_milestone=spec["future_milestone"],
                    created_at=STATIC_CREATED_AT,
                    safe_summary="M3 capability declaration is read-only protocol metadata.",
                )
            )
            records["risk_declarations"].append(
                PluginRiskDeclaration(
                    risk_declaration_id=risk_id,
                    plugin_id=plugin_id,
                    risk_level=spec["risk_level"],
                    data_exposure_level=spec["data_exposure"],
                    license_template_risks=["future_derivative_output_template_review_required"],
                    external_service_risks=["none_in_m3", "future_runtime_must_declare_external_platforms"],
                    source_mutation_risk=False,
                    requires_provider_secret=False,
                    requires_user_confirmation_before_runtime=True,
                    blocked_reason_codes=[],
                    warning_codes=spec["warnings"],
                    created_at=STATIC_CREATED_AT,
                    safe_summary="Risk declaration records future derivative and data exposure boundaries only.",
                )
            )
            records["version_records"].append(
                PluginVersionRecord(
                    version_record_id=version_id,
                    plugin_id=plugin_id,
                    plugin_semver="0.1.0",
                    plugin_protocol_version=PLUGIN_PROTOCOL_VERSION,
                    manifest_schema_version=SCHEMA_VERSION,
                    input_schema_version=SCHEMA_VERSION,
                    output_schema_version=SCHEMA_VERSION,
                    compatible_snapshot_schema_versions=COMPATIBLE_SNAPSHOT_SCHEMA_VERSIONS,
                    status=spec["availability_status"],
                    created_at=STATIC_CREATED_AT,
                    safe_summary="Version record binds this first-party plugin to the Phase 7 M3 protocol.",
                )
            )
        # Validate deterministic static payloads before they are written.
        assert_safe_payload(json.loads(json.dumps({key: [model_to_dict(item) for item in value] for key, value in records.items()})), context="builtin_plugin_records")
        return records
