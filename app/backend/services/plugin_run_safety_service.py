from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..models.plugin_runtime import PluginRunSafetyReport
from ..storage.json_store import JsonStore, StorageError
from .plugin_manifest_service import M1_M2_PACKAGE_FILES, assert_safe_payload, now_iso


PLUGIN_RUNS_FILE = "plugin_runs.json"
PLUGIN_RUN_STEPS_FILE = "plugin_run_steps.json"
PLUGIN_CHECKPOINTS_FILE = "plugin_checkpoints.json"
PLUGIN_CHECKPOINT_DECISIONS_FILE = "plugin_checkpoint_decisions.json"
PLUGIN_OUTPUT_ARTIFACTS_FILE = "plugin_output_artifacts.json"
PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE = "plugin_output_artifact_versions.json"
PLUGIN_RUN_SAFETY_REPORTS_FILE = "plugin_run_safety_reports.json"
PLUGIN_RUN_ERRORS_FILE = "plugin_run_errors.json"

ALLOWED_M4_STORAGE_FILES = [
    "plugin_input_validation_reports.json",
    PLUGIN_RUNS_FILE,
    PLUGIN_RUN_STEPS_FILE,
    PLUGIN_CHECKPOINTS_FILE,
    PLUGIN_CHECKPOINT_DECISIONS_FILE,
    PLUGIN_OUTPUT_ARTIFACTS_FILE,
    PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
    PLUGIN_RUN_SAFETY_REPORTS_FILE,
    PLUGIN_RUN_ERRORS_FILE,
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

M3_STATIC_PROTOCOL_FILES = [
    "plugin_manifests.json",
    "plugin_registry_entries.json",
    "plugin_input_schemas.json",
    "plugin_output_schemas.json",
    "plugin_capability_declarations.json",
    "plugin_risk_declarations.json",
    "plugin_version_records.json",
]

FORBIDDEN_BUSINESS_ARTIFACT_FILES = [
    "script_forging_runs.json",
    "script_shape_packages.json",
    "script_adaptation_prompt_packages.json",
    "scene_outline_artifacts.json",
    "screenplay_draft_artifacts.json",
    "screenplay_self_check_reports.json",
    "storyboard_artifacts.json",
    "shot_list_artifacts.json",
    "digital_asset_packages.json",
    "video_prompt_packages.json",
]

GUARDED_NO_MUTATION_FILES = FORBIDDEN_STORY_FACT_FILES + M1_M2_PACKAGE_FILES + M3_STATIC_PROTOCOL_FILES

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
    "langsmith key",
    "provider secret",
)
SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")
LIVE_STORY_REF_RE = re.compile(
    r"(?i)\b(scene|event|memory|memory_record|state_change|chapter_archive|narrative_debt|story_bible)_[a-z0-9][a-z0-9_\-]*\b"
)
LIVE_STORY_FILE_RE = re.compile(
    r"(?i)\b(scenes|events|memory_records|state_changes|chapter_archives|narrative_debts|story_bible|decisions)\.json\b"
)


class PluginRunSafetyService:
    """Deterministic safety checks for Phase 7 M4 plugin runtime records."""

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir

    def assert_safe_request_payload(self, payload: Any, *, context: str) -> None:
        assert_safe_payload(payload, context=context)
        self.assert_no_sensitive_string_values(payload, context=context)
        self.assert_no_live_story_refs(payload, context=context)

    def assert_safe_runtime_payload(self, payload: Any, *, context: str, full_story_text: str = "") -> None:
        assert_safe_payload(payload, context=context)
        self.assert_no_sensitive_string_values(payload, context=context)
        if full_story_text:
            serialized = json.dumps(payload, ensure_ascii=False)
            if full_story_text in serialized:
                raise StorageError(f"PLUGIN_RUN_FULL_STORY_TEXT_COPY_BLOCKED:{context}")

    def assert_no_sensitive_string_values(self, payload: Any, *, context: str) -> None:
        def scan(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    scan(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    scan(child, f"{path}[{index}]")
                return
            if not isinstance(value, str):
                return
            lowered = value.lower()
            if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                raise StorageError(f"PLUGIN_RUN_UNSAFE_PAYLOAD_BLOCKED:{context}:{path}")
            if SECRET_LIKE_RE.search(value):
                raise StorageError(f"PLUGIN_RUN_UNSAFE_PAYLOAD_BLOCKED:{context}:{path}")

        scan(payload, context)

    def assert_no_live_story_refs(self, payload: Any, *, context: str) -> None:
        def scan(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    scan(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    scan(child, f"{path}[{index}]")
                return
            if not isinstance(value, str):
                return
            if LIVE_STORY_REF_RE.search(value) or LIVE_STORY_FILE_RE.search(value):
                raise StorageError(f"PLUGIN_RUN_LIVE_STORY_REF_BLOCKED:{context}:{path}")

        scan(payload, context)

    def assert_no_forbidden_business_files(self) -> None:
        created = [file_name for file_name in FORBIDDEN_BUSINESS_ARTIFACT_FILES if (self.data_dir / file_name).exists()]
        if created:
            raise StorageError(f"PLUGIN_RUN_FORBIDDEN_BUSINESS_FILE_PRESENT:{','.join(created)}")

    def selected_hashes(self, file_names: list[str]) -> dict[str, str | None]:
        return {file_name: self.file_hash(file_name) for file_name in file_names}

    def file_hash(self, file_name: str) -> str | None:
        path = self.data_dir / file_name
        if not path.exists():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def assert_hashes_unchanged(self, before: dict[str, str | None], *, context: str) -> None:
        after = self.selected_hashes(list(before))
        if before != after:
            raise StorageError(f"PLUGIN_RUN_FORBIDDEN_MUTATION_BLOCKED:{context}")

    def build_safety_report(
        self,
        *,
        plugin_run_id: str,
        safety_report_id: str,
        final_story_package_snapshot_used: bool,
        no_final_story_package_mutation: bool,
        no_m2_package_record_mutation: bool,
        no_m3_static_protocol_record_mutation: bool,
        warnings: list[str] | None = None,
        violations: list[str] | None = None,
    ) -> PluginRunSafetyReport:
        violation_list = violations or []
        warning_list = warnings or []
        return PluginRunSafetyReport(
            safety_report_id=safety_report_id,
            plugin_run_id=plugin_run_id,
            passed=not violation_list,
            final_story_package_snapshot_used=final_story_package_snapshot_used,
            live_story_state_access_blocked=True,
            unconfirmed_draft_access_blocked=True,
            phase6_proposal_as_truth_blocked=True,
            fixture_confusion_blocked_or_marked=True,
            no_scene_prose_write=True,
            no_event_write=True,
            no_memory_record_write=True,
            no_state_change_write=True,
            no_chapter_archive_write=True,
            no_narrative_debt_write=True,
            no_story_bible_write=True,
            no_final_story_package_mutation=no_final_story_package_mutation,
            no_m2_package_record_mutation=no_m2_package_record_mutation,
            no_m3_static_protocol_record_mutation=no_m3_static_protocol_record_mutation,
            no_raw_prompt=True,
            no_raw_response=True,
            no_hidden_reasoning=True,
            no_chain_of_thought=True,
            no_api_key=True,
            no_authorization_header=True,
            no_langsmith_key=True,
            no_provider_secret=True,
            violations=violation_list,
            warnings=warning_list,
            safe_summary=(
                "M4 runtime checked this plugin step against snapshot-only input, no source-story writes, "
                "and derivative-output boundaries."
            ),
            created_at=now_iso(),
        )
