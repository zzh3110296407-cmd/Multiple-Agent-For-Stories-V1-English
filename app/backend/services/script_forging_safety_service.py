from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..storage.json_store import JsonStore, StorageError
from .plugin_manifest_service import M1_M2_PACKAGE_FILES, model_to_dict
from .plugin_run_safety_service import (
    FORBIDDEN_STORY_FACT_FILES,
    M3_STATIC_PROTOCOL_FILES,
    PLUGIN_CHECKPOINT_DECISIONS_FILE,
    PLUGIN_CHECKPOINTS_FILE,
    PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
    PLUGIN_OUTPUT_ARTIFACTS_FILE,
    PLUGIN_RUN_SAFETY_REPORTS_FILE,
    PLUGIN_RUN_STEPS_FILE,
    PLUGIN_RUNS_FILE,
    PluginRunSafetyService,
)


SCRIPT_FORGING_CONTEXTS_FILE = "script_forging_run_contexts.json"
SCRIPT_SHAPE_PACKAGES_FILE = "script_shape_packages.json"
SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE = "script_adaptation_prompt_packages.json"
SCRIPT_FORGING_CHECKPOINTS_FILE = "script_forging_checkpoints.json"
SCRIPT_FORGING_RISK_NOTES_FILE = "script_forging_risk_notes.json"
SCENE_OUTLINE_ARTIFACTS_FILE = "scene_outline_artifacts.json"
SCREENPLAY_DRAFT_ARTIFACTS_FILE = "screenplay_draft_artifacts.json"
SCREENPLAY_SELF_CHECK_REPORTS_FILE = "screenplay_self_check_reports.json"
SCREENPLAY_REVISION_CANDIDATES_FILE = "screenplay_revision_candidates.json"
STORYBOARD_PACKAGES_FILE = "storyboard_packages.json"
KEY_STORYBOARD_ARTIFACTS_FILE = "key_storyboard_artifacts.json"
SCENE_STORYBOARD_ARTIFACTS_FILE = "scene_storyboard_artifacts.json"
SHOT_LIST_ARTIFACTS_FILE = "shot_list_artifacts.json"
DIGITAL_ASSET_PACKAGES_FILE = "digital_asset_packages.json"
CHARACTER_ASSET_LISTS_FILE = "character_asset_lists.json"
LOCATION_ASSET_LISTS_FILE = "location_asset_lists.json"
PROP_ASSET_LISTS_FILE = "prop_asset_lists.json"
MOTIF_ASSET_LISTS_FILE = "motif_asset_lists.json"
COSTUME_CONTINUITY_LISTS_FILE = "costume_continuity_lists.json"

ALLOWED_M5_STORAGE_FILES = [
    SCRIPT_FORGING_CONTEXTS_FILE,
    SCRIPT_SHAPE_PACKAGES_FILE,
    SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE,
    SCRIPT_FORGING_CHECKPOINTS_FILE,
    SCRIPT_FORGING_RISK_NOTES_FILE,
    PLUGIN_RUNS_FILE,
    PLUGIN_RUN_STEPS_FILE,
    PLUGIN_CHECKPOINTS_FILE,
    PLUGIN_CHECKPOINT_DECISIONS_FILE,
    PLUGIN_OUTPUT_ARTIFACTS_FILE,
    PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
    PLUGIN_RUN_SAFETY_REPORTS_FILE,
]

FORBIDDEN_M5_BUSINESS_FILES = [
    SCENE_OUTLINE_ARTIFACTS_FILE,
    SCREENPLAY_DRAFT_ARTIFACTS_FILE,
    SCREENPLAY_SELF_CHECK_REPORTS_FILE,
    SCREENPLAY_REVISION_CANDIDATES_FILE,
    STORYBOARD_PACKAGES_FILE,
    KEY_STORYBOARD_ARTIFACTS_FILE,
    SCENE_STORYBOARD_ARTIFACTS_FILE,
    SHOT_LIST_ARTIFACTS_FILE,
    DIGITAL_ASSET_PACKAGES_FILE,
    CHARACTER_ASSET_LISTS_FILE,
    LOCATION_ASSET_LISTS_FILE,
    PROP_ASSET_LISTS_FILE,
    MOTIF_ASSET_LISTS_FILE,
    COSTUME_CONTINUITY_LISTS_FILE,
    "video_prompt_packages.json",
]

GUARDED_M5_NO_MUTATION_FILES = (
    FORBIDDEN_STORY_FACT_FILES
    + M1_M2_PACKAGE_FILES
    + M3_STATIC_PROTOCOL_FILES
    + ["plugin_input_validation_reports.json"]
)

ALLOWED_M6_STORAGE_FILES = [
    SCENE_OUTLINE_ARTIFACTS_FILE,
    SCREENPLAY_DRAFT_ARTIFACTS_FILE,
    SCREENPLAY_SELF_CHECK_REPORTS_FILE,
    SCREENPLAY_REVISION_CANDIDATES_FILE,
    SCRIPT_FORGING_CHECKPOINTS_FILE,
    PLUGIN_RUNS_FILE,
    PLUGIN_RUN_STEPS_FILE,
    PLUGIN_CHECKPOINTS_FILE,
    PLUGIN_CHECKPOINT_DECISIONS_FILE,
    PLUGIN_OUTPUT_ARTIFACTS_FILE,
    PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
    PLUGIN_RUN_SAFETY_REPORTS_FILE,
]

M7_STORAGE_FILES = [
    STORYBOARD_PACKAGES_FILE,
    KEY_STORYBOARD_ARTIFACTS_FILE,
    SCENE_STORYBOARD_ARTIFACTS_FILE,
    SHOT_LIST_ARTIFACTS_FILE,
    DIGITAL_ASSET_PACKAGES_FILE,
    CHARACTER_ASSET_LISTS_FILE,
    LOCATION_ASSET_LISTS_FILE,
    PROP_ASSET_LISTS_FILE,
    MOTIF_ASSET_LISTS_FILE,
    COSTUME_CONTINUITY_LISTS_FILE,
]

FORBIDDEN_M6_M7_FILES = M7_STORAGE_FILES + [
    "storyboard_artifacts.json",
    "video_prompt_packages.json",
    "image_prompt_packages.json",
    "external_media_outputs.json",
    "generated_media_outputs.json",
]

FORBIDDEN_M7_M8_AND_MEDIA_FILES = [
    "video_prompt_packages.json",
    "image_prompt_packages.json",
    "external_media_outputs.json",
    "generated_media_outputs.json",
    "phase" + str(8) + "_close" + "out.json",
]

GUARDED_M6_NO_MUTATION_FILES = (
    FORBIDDEN_STORY_FACT_FILES
    + M1_M2_PACKAGE_FILES
    + M3_STATIC_PROTOCOL_FILES
    + [
        "plugin_input_validation_reports.json",
        SCRIPT_FORGING_CONTEXTS_FILE,
        SCRIPT_SHAPE_PACKAGES_FILE,
        SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE,
        SCRIPT_FORGING_RISK_NOTES_FILE,
    ]
)

ALLOWED_M7_STORAGE_FILES = (
    M7_STORAGE_FILES
    + [
        SCRIPT_FORGING_CHECKPOINTS_FILE,
        PLUGIN_RUNS_FILE,
        PLUGIN_RUN_STEPS_FILE,
        PLUGIN_CHECKPOINTS_FILE,
        PLUGIN_CHECKPOINT_DECISIONS_FILE,
        PLUGIN_OUTPUT_ARTIFACTS_FILE,
        PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
        PLUGIN_RUN_SAFETY_REPORTS_FILE,
    ]
)

GUARDED_M7_NO_MUTATION_FILES = (
    FORBIDDEN_STORY_FACT_FILES
    + M1_M2_PACKAGE_FILES
    + M3_STATIC_PROTOCOL_FILES
    + [
        "plugin_input_validation_reports.json",
        SCRIPT_FORGING_CONTEXTS_FILE,
        SCRIPT_SHAPE_PACKAGES_FILE,
        SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE,
        SCRIPT_FORGING_RISK_NOTES_FILE,
        SCENE_OUTLINE_ARTIFACTS_FILE,
        SCREENPLAY_DRAFT_ARTIFACTS_FILE,
        SCREENPLAY_SELF_CHECK_REPORTS_FILE,
        SCREENPLAY_REVISION_CANDIDATES_FILE,
    ]
)


class ScriptForgingSafetyService:
    """M5 script-forging safety boundary helper."""

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.runtime_safety = PluginRunSafetyService(store=self.store, data_dir=self.data_dir)

    def assert_safe_request_payload(self, payload: Any, *, context: str) -> None:
        self.runtime_safety.assert_safe_request_payload(payload, context=context)

    def assert_safe_record_payload(self, payload: Any, *, context: str, full_story_text: str = "") -> None:
        self.runtime_safety.assert_safe_runtime_payload(payload, context=context, full_story_text=full_story_text)
        serialized = json.dumps(payload, ensure_ascii=False)
        forbidden_field_names = [
            "raw_prompt",
            "raw_response",
            "hidden_reasoning",
            "chain_of_thought",
            "provider_secret",
        ]
        leaked = [field for field in forbidden_field_names if f'"{field}"' in serialized]
        if leaked:
            raise StorageError(f"SCRIPT_FORGING_FORBIDDEN_FIELD_NAME_BLOCKED:{context}:{','.join(leaked)}")

    def selected_hashes(self, file_names: list[str]) -> dict[str, str | None]:
        return self.runtime_safety.selected_hashes(file_names)

    def assert_hashes_unchanged(self, before: dict[str, str | None], *, context: str) -> None:
        self.runtime_safety.assert_hashes_unchanged(before, context=context)

    def assert_no_forbidden_m5_files(self) -> None:
        created = [file_name for file_name in FORBIDDEN_M5_BUSINESS_FILES if (self.data_dir / file_name).exists()]
        if created:
            raise StorageError(f"SCRIPT_FORGING_FORBIDDEN_FILE_PRESENT:{','.join(created)}")

    def assert_no_forbidden_m6_files(self) -> None:
        created = [file_name for file_name in FORBIDDEN_M6_M7_FILES if (self.data_dir / file_name).exists()]
        if created:
            raise StorageError(f"SCRIPT_FORGING_M6_FORBIDDEN_FILE_PRESENT:{','.join(created)}")

    def assert_no_forbidden_m7_files(self) -> None:
        created = [file_name for file_name in FORBIDDEN_M7_M8_AND_MEDIA_FILES if (self.data_dir / file_name).exists()]
        if created:
            raise StorageError(f"SCRIPT_FORGING_M7_FORBIDDEN_FILE_PRESENT:{','.join(created)}")

    def model_dict(self, model: Any) -> dict[str, Any]:
        return model_to_dict(model)
