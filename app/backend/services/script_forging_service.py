from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..models.plugin_runtime import (
    PluginCheckpoint,
    PluginCheckpointDecision,
    PluginOutputArtifact,
    PluginOutputArtifactVersion,
    PluginRun,
    PluginRunSafetyReport,
    PluginRunStep,
)
from ..models.script_forging import (
    CharacterAssetList,
    CharacterAssetListResponse,
    CostumeContinuityList,
    CostumeContinuityListResponse,
    DigitalAssetPackage,
    DigitalAssetPackageResponse,
    KeyStoryboardArtifact,
    KeyStoryboardArtifactListResponse,
    LocationAssetList,
    LocationAssetListResponse,
    MotifAssetList,
    MotifAssetListResponse,
    PropAssetList,
    PropAssetListResponse,
    SceneOutlineArtifact,
    SceneOutlineArtifactResponse,
    SceneOutlineUnit,
    ScreenplayDialogueBlock,
    ScreenplayDraftArtifact,
    ScreenplayDraftArtifactResponse,
    ScreenplayRevisionCandidate,
    ScreenplayRevisionCandidateListResponse,
    ScreenplayRevisionCandidateResponse,
    ScreenplaySceneScriptUnit,
    ScreenplaySelfCheckReport,
    ScreenplaySelfCheckReportResponse,
    SceneStoryboardArtifact,
    SceneStoryboardArtifactListResponse,
    ShotListArtifact,
    ShotListArtifactResponse,
    StoryboardPackage,
    StoryboardPackageResponse,
    ScriptAdaptationPromptPackage,
    ScriptAdaptationPromptPackageResponse,
    ScriptForgingCheckpoint,
    ScriptForgingContextResponse,
    ScriptForgingDecisionRequest,
    ScriptForgingDecisionResponse,
    ScriptForgingRunContext,
    ScriptForgingRiskNoteResponse,
    ScriptForgingSelfRiskNote,
    ScriptForgingShapeSuggestion,
    ScriptShapePackage,
    ScriptShapePackageResponse,
)
from ..storage.json_store import JsonStore, StorageError
from .plugin_input_validation_service import SNAPSHOTS_FILE
from .plugin_manifest_service import model_to_dict, now_iso, sanitize_user_note
from .plugin_run_safety_service import (
    PLUGIN_CHECKPOINT_DECISIONS_FILE,
    PLUGIN_CHECKPOINTS_FILE,
    PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
    PLUGIN_OUTPUT_ARTIFACTS_FILE,
    PLUGIN_RUN_SAFETY_REPORTS_FILE,
    PLUGIN_RUN_STEPS_FILE,
    PLUGIN_RUNS_FILE,
)
from .script_forging_safety_service import (
    CHARACTER_ASSET_LISTS_FILE,
    COSTUME_CONTINUITY_LISTS_FILE,
    DIGITAL_ASSET_PACKAGES_FILE,
    GUARDED_M5_NO_MUTATION_FILES,
    GUARDED_M6_NO_MUTATION_FILES,
    GUARDED_M7_NO_MUTATION_FILES,
    KEY_STORYBOARD_ARTIFACTS_FILE,
    LOCATION_ASSET_LISTS_FILE,
    MOTIF_ASSET_LISTS_FILE,
    PROP_ASSET_LISTS_FILE,
    SCENE_OUTLINE_ARTIFACTS_FILE,
    SCENE_STORYBOARD_ARTIFACTS_FILE,
    SCREENPLAY_DRAFT_ARTIFACTS_FILE,
    SCREENPLAY_REVISION_CANDIDATES_FILE,
    SCREENPLAY_SELF_CHECK_REPORTS_FILE,
    SHOT_LIST_ARTIFACTS_FILE,
    SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE,
    SCRIPT_FORGING_CHECKPOINTS_FILE,
    SCRIPT_FORGING_CONTEXTS_FILE,
    SCRIPT_FORGING_RISK_NOTES_FILE,
    SCRIPT_SHAPE_PACKAGES_FILE,
    STORYBOARD_PACKAGES_FILE,
    ScriptForgingSafetyService,
)


class ScriptForgingService:
    """Phase 7 M5 deterministic script-forging shape and adaptation package service."""

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.safety = ScriptForgingSafetyService(store=self.store, data_dir=self.data_dir)

    def create_context(self, plugin_run_id: str) -> ScriptForgingContextResponse:
        run = self._eligible_run(plugin_run_id)
        existing = self._context_for_run(plugin_run_id)
        if existing:
            return ScriptForgingContextResponse(
                context=existing,
                plugin_run=run,
                safe_summary="Existing script-forging context loaded.",
            )
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        before = self.safety.selected_hashes(GUARDED_M5_NO_MUTATION_FILES)
        now = now_iso()
        checkpoint = self._confirmed_input_checkpoint(run)
        chapter_scene_index = snapshot.get("chapter_scene_index") or []
        chapter_ids = {
            str(item.get("chapter_id") or item.get("chapter_index") or "")
            for item in chapter_scene_index
            if isinstance(item, dict)
        }
        style_summary = self._style_summary(snapshot.get("style_and_tone") or {})
        context = ScriptForgingRunContext(
            script_forging_run_context_id=f"script_forging_context_{plugin_run_id}",
            plugin_run_id=plugin_run_id,
            project_id=run.project_id,
            plugin_id=run.plugin_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            m4_input_checkpoint_id=checkpoint.checkpoint_id,
            m4_input_checkpoint_decision_id=checkpoint.decision_id,
            source_manifest_id=run.manifest_id,
            source_package_snapshot_hash=str(snapshot.get("complete_story_text_hash") or ""),
            complete_story_text_hash=str(snapshot.get("complete_story_text_hash") or ""),
            complete_story_text_char_count=int(snapshot.get("complete_story_text_char_count") or 0),
            source_ref_count=len(snapshot.get("source_ref_ids") or []),
            chapter_count=len([item for item in chapter_ids if item]) or 1,
            scene_count=len(chapter_scene_index),
            character_count=len(snapshot.get("character_table") or []),
            relationship_count=len(snapshot.get("relationship_state_summary") or []),
            key_event_count=len(snapshot.get("key_event_timeline") or []),
            style_and_tone_summary=style_summary,
            world_canvas_summary_keys=sorted((snapshot.get("world_canvas_summary") or {}).keys()),
            known_residual_codes=list(snapshot.get("known_residual_codes") or []),
            reads_only_final_story_package_snapshot=True,
            mutates_source_story=False,
            created_at=now,
            safe_summary=(
                "Script-forging context binds the confirmed plugin run to snapshot ids, hashes, counts, and safe summaries only."
            ),
            warnings=[],
        )
        self._assert_safe_write(context, "script_forging_context", full_story_text)
        self._append_model(SCRIPT_FORGING_CONTEXTS_FILE, context)
        self.safety.assert_hashes_unchanged(before, context="script_forging_context_create")
        self.safety.assert_no_forbidden_m5_files()
        return ScriptForgingContextResponse(
            context=context,
            plugin_run=run,
            safe_summary="Script-forging context created.",
        )

    def get_context(self, plugin_run_id: str) -> ScriptForgingContextResponse:
        run = self._load_run(plugin_run_id)
        context = self._context_for_run(plugin_run_id)
        if context is None:
            raise StorageError(f"SCRIPT_FORGING_CONTEXT_NOT_FOUND:{plugin_run_id}")
        return ScriptForgingContextResponse(context=context, plugin_run=run, safe_summary="Script-forging context loaded.")

    def create_shape_package(self, plugin_run_id: str) -> ScriptShapePackageResponse:
        run = self._eligible_run(plugin_run_id)
        context = self._context_for_run(plugin_run_id)
        if context is None:
            context = self.create_context(plugin_run_id).context
        existing = self._shape_package_for_run(plugin_run_id)
        if existing:
            return self._shape_response(run, existing)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        before = self.safety.selected_hashes(GUARDED_M5_NO_MUTATION_FILES)
        now = now_iso()
        suggestions = self._shape_suggestions(snapshot)
        if len(suggestions) < 2 or len(suggestions) > 4:
            raise StorageError("SCRIPT_FORGING_SHAPE_SUGGESTION_COUNT_BLOCKED")
        step_id = f"{plugin_run_id}_step_script_shape_{self._time_suffix(now)}"
        checkpoint_id = f"{plugin_run_id}_checkpoint_script_shape_{self._time_suffix(now)}"
        artifact_id = f"{plugin_run_id}_artifact_script_shape"
        version_id = f"{artifact_id}_version_001"
        package_id = f"script_shape_package_{plugin_run_id}"
        structured_summary = {
            "derivative_artifact_kind": "script_shape_package",
            "package_id": package_id,
            "plugin_run_id": plugin_run_id,
            "snapshot_id": run.final_story_package_snapshot_id,
            "complete_story_text_hash": context.complete_story_text_hash,
            "source_ref_count": context.source_ref_count,
            "suggestion_count": len(suggestions),
            "recommended_shape_id": suggestions[0].shape_id,
            "mutates_source_story": False,
        }
        output_version = self._artifact_version(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_id=version_id,
            structured_summary=structured_summary,
            safe_preview=f"Script shape package with {len(suggestions)} safe adaptation directions.",
            step_id=step_id,
            checkpoint_id=checkpoint_id,
            now=now,
        )
        output_artifact = self._artifact(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            plugin_id=run.plugin_id,
            project_id=run.project_id,
            snapshot_id=run.final_story_package_snapshot_id,
            manifest_id=run.manifest_id,
            version_id=version_id,
            safe_title="Script Forging Shape Package",
            safe_summary="Derivative structured artifact containing adaptation shape options only.",
            now=now,
            status="checkpoint_pending",
        )
        plugin_checkpoint = PluginCheckpoint(
            checkpoint_id=checkpoint_id,
            plugin_run_id=plugin_run_id,
            step_id=step_id,
            checkpoint_type="generic_confirmation",
            checkpoint_status="pending",
            checkpoint_prompt="Confirm the adaptation shape direction before creating the M6 instruction package.",
            user_visible_summary="This checkpoint confirms adaptation direction only and does not modify the source story.",
            source_artifact_ids=[artifact_id],
            confirms_plugin_step_only=True,
            mutates_source_story=False,
            created_at=now,
            updated_at=now,
        )
        script_checkpoint = ScriptForgingCheckpoint(
            script_forging_checkpoint_id=f"script_forging_checkpoint_shape_{plugin_run_id}",
            plugin_run_id=plugin_run_id,
            checkpoint_kind="shape_direction_confirmation",
            plugin_checkpoint_id=checkpoint_id,
            source_domain_artifact_id=package_id,
            created_at=now,
            updated_at=now,
            safe_summary="Shape direction checkpoint wrapper for M4 plugin checkpoint.",
        )
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="artifact_creation",
            step_status="waiting_for_checkpoint",
            input_refs=[context.script_forging_run_context_id],
            output_refs=[package_id, artifact_id, version_id, checkpoint_id],
            checkpoint_id=checkpoint_id,
            output_artifact_id=artifact_id,
            safe_summary="Created derivative script shape package and waiting for plugin-step checkpoint confirmation.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        package = ScriptShapePackage(
            script_shape_package_id=package_id,
            plugin_run_id=plugin_run_id,
            context_id=context.script_forging_run_context_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            package_status="checkpoint_pending",
            suggestions=suggestions,
            recommended_shape_id=suggestions[0].shape_id,
            checkpoint_id=checkpoint_id,
            output_artifact_id=artifact_id,
            output_artifact_version_id=version_id,
            is_derivative_artifact=True,
            mutates_source_story=False,
            created_at=now,
            updated_at=now,
            safe_summary="Script shape package proposes adaptation direction options without writing script body.",
            warnings=[],
        )
        safety_report = self._safety_report(plugin_run_id, "shape", now)
        run.run_status = "waiting_for_checkpoint"
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        self._append_unique(run.checkpoint_ids, checkpoint_id)
        self._append_unique(run.output_artifact_ids, artifact_id)
        run.safety_report_id = safety_report.safety_report_id
        self._assert_safe_write(
            {
                "run": model_to_dict(run),
                "package": model_to_dict(package),
                "checkpoint": model_to_dict(plugin_checkpoint),
                "script_checkpoint": model_to_dict(script_checkpoint),
                "artifact": model_to_dict(output_artifact),
                "version": model_to_dict(output_version),
                "step": model_to_dict(step),
                "safety_report": model_to_dict(safety_report),
            },
            "script_shape_package_create",
            full_story_text,
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(SCRIPT_SHAPE_PACKAGES_FILE, package)
        self._append_model(SCRIPT_FORGING_CHECKPOINTS_FILE, script_checkpoint)
        self._append_model(PLUGIN_CHECKPOINTS_FILE, plugin_checkpoint)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
        self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context="script_shape_package_create")
        self.safety.assert_no_forbidden_m5_files()
        return ScriptShapePackageResponse(
            shape_package=package,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            step=step,
            safety_report=safety_report,
            safe_summary="Script shape package created and checkpointed.",
        )

    def get_shape_package(self, plugin_run_id: str) -> ScriptShapePackageResponse:
        run = self._load_run(plugin_run_id)
        package = self._shape_package_for_run(plugin_run_id)
        if package is None:
            raise StorageError(f"SCRIPT_SHAPE_PACKAGE_NOT_FOUND:{plugin_run_id}")
        return self._shape_response(run, package)

    def submit_shape_checkpoint_decision(
        self,
        plugin_run_id: str,
        decision_type: str,
        request: ScriptForgingDecisionRequest,
    ) -> ScriptForgingDecisionResponse:
        package = self._shape_package_for_run(plugin_run_id)
        if package is None:
            raise StorageError(f"SCRIPT_SHAPE_PACKAGE_NOT_FOUND:{plugin_run_id}")
        return self._submit_domain_checkpoint_decision(
            plugin_run_id=plugin_run_id,
            decision_type=decision_type,
            request=request,
            script_checkpoint_kind="shape_direction_confirmation",
            domain_artifact_id=package.script_shape_package_id,
            status_setter=lambda status, now: self._set_shape_status(package, status, now),
            confirmed_run_status="checkpoint_confirmed",
            completion_stage="shape",
        )

    def create_adaptation_prompt_package(self, plugin_run_id: str) -> ScriptAdaptationPromptPackageResponse:
        run = self._eligible_run(plugin_run_id, require_completed=False)
        context = self._context_for_run(plugin_run_id)
        if context is None:
            raise StorageError(f"SCRIPT_FORGING_CONTEXT_NOT_FOUND:{plugin_run_id}")
        shape_package = self._shape_package_for_run(plugin_run_id)
        if shape_package is None:
            raise StorageError(f"SCRIPT_SHAPE_PACKAGE_NOT_FOUND:{plugin_run_id}")
        if shape_package.package_status != "confirmed":
            raise StorageError(f"SCRIPT_SHAPE_PACKAGE_NOT_CONFIRMED:{shape_package.package_status}")
        existing = self._prompt_package_for_run(plugin_run_id)
        if existing:
            return self._prompt_response(run, existing)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        selected_shape = self._shape_by_id(shape_package, shape_package.recommended_shape_id)
        before = self.safety.selected_hashes(GUARDED_M5_NO_MUTATION_FILES)
        now = now_iso()
        step_id = f"{plugin_run_id}_step_script_prompt_{self._time_suffix(now)}"
        checkpoint_id = f"{plugin_run_id}_checkpoint_script_prompt_{self._time_suffix(now)}"
        artifact_id = f"{plugin_run_id}_artifact_script_adaptation_prompt"
        version_id = f"{artifact_id}_version_001"
        package_id = f"script_adaptation_prompt_package_{plugin_run_id}"
        prompt_package = ScriptAdaptationPromptPackage(
            script_adaptation_prompt_package_id=package_id,
            plugin_run_id=plugin_run_id,
            context_id=context.script_forging_run_context_id,
            script_shape_package_id=shape_package.script_shape_package_id,
            selected_shape_id=selected_shape.shape_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            package_status="checkpoint_pending",
            m6_input_contract={
                "contract_version": "phase7_m5_to_m6_script_adaptation_instruction_v1",
                "requires_confirmed_prompt_package": True,
                "source_snapshot_id": run.final_story_package_snapshot_id,
                "complete_story_text_hash": context.complete_story_text_hash,
            },
            adaptation_brief={
                "adaptation_form": selected_shape.adaptation_form,
                "target_runtime_band": selected_shape.target_runtime_band,
                "structure_strategy": selected_shape.structure_strategy,
                "point_of_view_strategy": selected_shape.point_of_view_strategy,
                "source_ref_count": context.source_ref_count,
                "chapter_count": context.chapter_count,
                "scene_count": context.scene_count,
            },
            preserve_instructions=list(selected_shape.preserve_elements),
            compression_instructions=list(selected_shape.compress_elements),
            omission_and_forbidden_instructions=list(selected_shape.omit_or_forbid_elements),
            format_constraints=[
                "Return structured M6 screenplay planning records only after M6 approval.",
                "Do not create a full screenplay body in M5.",
                "Keep every output derivative and source-referenced.",
            ],
            source_reference_policy={
                "use_snapshot_hash": context.complete_story_text_hash,
                "use_source_ref_ids": True,
                "do_not_copy_complete_story_text": True,
            },
            safety_instructions=[
                "Do not mutate source story facts.",
                "Do not add unverified canon.",
                "Do not store provider prompt text or provider response text.",
                "Do not call external media providers.",
            ],
            checkpoint_id=checkpoint_id,
            output_artifact_id=artifact_id,
            output_artifact_version_id=version_id,
            is_derivative_artifact=True,
            mutates_source_story=False,
            created_at=now,
            updated_at=now,
            safe_summary="M6-ready structured instruction package; not provider prompt text and not a screenplay.",
            warnings=[],
        )
        structured_summary = {
            "derivative_artifact_kind": "script_adaptation_prompt_package",
            "package_id": package_id,
            "plugin_run_id": plugin_run_id,
            "snapshot_id": run.final_story_package_snapshot_id,
            "selected_shape_id": selected_shape.shape_id,
            "complete_story_text_hash": context.complete_story_text_hash,
            "source_ref_count": context.source_ref_count,
            "mutates_source_story": False,
        }
        output_version = self._artifact_version(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_id=version_id,
            structured_summary=structured_summary,
            safe_preview=f"M6-ready adaptation instruction package for {selected_shape.title}.",
            step_id=step_id,
            checkpoint_id=checkpoint_id,
            now=now,
        )
        output_artifact = self._artifact(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            plugin_id=run.plugin_id,
            project_id=run.project_id,
            snapshot_id=run.final_story_package_snapshot_id,
            manifest_id=run.manifest_id,
            version_id=version_id,
            safe_title="Script Adaptation Prompt Package",
            safe_summary="Derivative structured M6 instruction package, not provider prompt text.",
            now=now,
            status="checkpoint_pending",
        )
        plugin_checkpoint = PluginCheckpoint(
            checkpoint_id=checkpoint_id,
            plugin_run_id=plugin_run_id,
            step_id=step_id,
            checkpoint_type="generic_confirmation",
            checkpoint_status="pending",
            checkpoint_prompt="Confirm this structured adaptation package as M6 input.",
            user_visible_summary="This checkpoint confirms the M6 instruction package only and does not modify source story.",
            source_artifact_ids=[artifact_id],
            confirms_plugin_step_only=True,
            mutates_source_story=False,
            created_at=now,
            updated_at=now,
        )
        script_checkpoint = ScriptForgingCheckpoint(
            script_forging_checkpoint_id=f"script_forging_checkpoint_prompt_{plugin_run_id}",
            plugin_run_id=plugin_run_id,
            checkpoint_kind="adaptation_prompt_package_confirmation",
            plugin_checkpoint_id=checkpoint_id,
            source_domain_artifact_id=package_id,
            created_at=now,
            updated_at=now,
            safe_summary="Prompt package checkpoint wrapper for M4 plugin checkpoint.",
        )
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="artifact_creation",
            step_status="waiting_for_checkpoint",
            input_refs=[shape_package.script_shape_package_id, shape_package.checkpoint_id],
            output_refs=[package_id, artifact_id, version_id, checkpoint_id],
            checkpoint_id=checkpoint_id,
            output_artifact_id=artifact_id,
            safe_summary="Created derivative adaptation prompt package and waiting for plugin-step checkpoint confirmation.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        risk_note = self._risk_note(run, context, shape_package, prompt_package, selected_shape, now)
        safety_report = self._safety_report(plugin_run_id, "prompt", now)
        run.run_status = "waiting_for_checkpoint"
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        self._append_unique(run.checkpoint_ids, checkpoint_id)
        self._append_unique(run.output_artifact_ids, artifact_id)
        run.safety_report_id = safety_report.safety_report_id
        self._assert_safe_write(
            {
                "run": model_to_dict(run),
                "prompt_package": model_to_dict(prompt_package),
                "checkpoint": model_to_dict(plugin_checkpoint),
                "script_checkpoint": model_to_dict(script_checkpoint),
                "artifact": model_to_dict(output_artifact),
                "version": model_to_dict(output_version),
                "step": model_to_dict(step),
                "risk_note": model_to_dict(risk_note),
                "safety_report": model_to_dict(safety_report),
            },
            "script_adaptation_prompt_package_create",
            full_story_text,
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE, prompt_package)
        self._append_model(SCRIPT_FORGING_CHECKPOINTS_FILE, script_checkpoint)
        self._append_model(PLUGIN_CHECKPOINTS_FILE, plugin_checkpoint)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
        self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        self._replace_or_append_model(SCRIPT_FORGING_RISK_NOTES_FILE, "script_forging_risk_note_id", risk_note.script_forging_risk_note_id, risk_note)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context="script_adaptation_prompt_package_create")
        self.safety.assert_no_forbidden_m5_files()
        return ScriptAdaptationPromptPackageResponse(
            prompt_package=prompt_package,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            step=step,
            risk_note=risk_note,
            safety_report=safety_report,
            safe_summary="Script adaptation prompt package created and checkpointed.",
        )

    def get_adaptation_prompt_package(self, plugin_run_id: str) -> ScriptAdaptationPromptPackageResponse:
        run = self._load_run(plugin_run_id)
        package = self._prompt_package_for_run(plugin_run_id)
        if package is None:
            raise StorageError(f"SCRIPT_ADAPTATION_PROMPT_PACKAGE_NOT_FOUND:{plugin_run_id}")
        return self._prompt_response(run, package)

    def submit_prompt_package_checkpoint_decision(
        self,
        plugin_run_id: str,
        decision_type: str,
        request: ScriptForgingDecisionRequest,
    ) -> ScriptForgingDecisionResponse:
        package = self._prompt_package_for_run(plugin_run_id)
        if package is None:
            raise StorageError(f"SCRIPT_ADAPTATION_PROMPT_PACKAGE_NOT_FOUND:{plugin_run_id}")
        return self._submit_domain_checkpoint_decision(
            plugin_run_id=plugin_run_id,
            decision_type=decision_type,
            request=request,
            script_checkpoint_kind="adaptation_prompt_package_confirmation",
            domain_artifact_id=package.script_adaptation_prompt_package_id,
            status_setter=lambda status, now: self._set_prompt_status(package, status, now),
            confirmed_run_status="completed",
            completion_stage="prompt",
        )

    def get_risk_note(self, plugin_run_id: str) -> ScriptForgingRiskNoteResponse:
        note = self._risk_note_for_run(plugin_run_id)
        if note is None:
            raise StorageError(f"SCRIPT_FORGING_RISK_NOTE_NOT_FOUND:{plugin_run_id}")
        return ScriptForgingRiskNoteResponse(
            risk_note=note,
            safe_summary="Script-forging self-risk note loaded.",
        )

    def create_scene_outline(self, plugin_run_id: str) -> SceneOutlineArtifactResponse:
        run, context, prompt_package = self._m6_gate(plugin_run_id)
        existing = self._scene_outline_for_run(plugin_run_id)
        if existing:
            return self._scene_outline_response(run, existing)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        before = self.safety.selected_hashes(GUARDED_M6_NO_MUTATION_FILES)
        now = now_iso()
        outline_id = f"scene_outline_{plugin_run_id}"
        step_id = f"{plugin_run_id}_step_scene_outline_{self._time_suffix(now)}"
        checkpoint_id = f"{plugin_run_id}_checkpoint_scene_outline_{self._time_suffix(now)}"
        artifact_id = f"{plugin_run_id}_artifact_scene_outline"
        version_id = f"{artifact_id}_version_001"
        outline_units = self._scene_outline_units(context, prompt_package, snapshot)
        structured_summary = {
            "derivative_artifact_kind": "scene_outline_artifact",
            "scene_outline_id": outline_id,
            "plugin_run_id": plugin_run_id,
            "snapshot_id": run.final_story_package_snapshot_id,
            "selected_shape_id": prompt_package.selected_shape_id,
            "outline_unit_count": len(outline_units),
            "complete_story_text_hash": context.complete_story_text_hash,
            "mutates_source_story": False,
        }
        output_version = self._artifact_version(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_id=version_id,
            structured_summary=structured_summary,
            safe_preview=f"Scene outline artifact with {len(outline_units)} bounded outline units.",
            step_id=step_id,
            checkpoint_id=checkpoint_id,
            now=now,
        )
        output_artifact = self._artifact(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            plugin_id=run.plugin_id,
            project_id=run.project_id,
            snapshot_id=run.final_story_package_snapshot_id,
            manifest_id=run.manifest_id,
            version_id=version_id,
            safe_title="Script Forging Scene Outline",
            safe_summary="Derivative scene outline artifact from confirmed M5 prompt package.",
            now=now,
            status="checkpoint_pending",
        )
        plugin_checkpoint = PluginCheckpoint(
            checkpoint_id=checkpoint_id,
            plugin_run_id=plugin_run_id,
            step_id=step_id,
            checkpoint_type="generic_confirmation",
            checkpoint_status="pending",
            checkpoint_prompt="Confirm the scene outline before creating the screenplay draft.",
            user_visible_summary="This checkpoint confirms only the M6 scene outline artifact.",
            source_artifact_ids=[artifact_id],
            confirms_plugin_step_only=True,
            mutates_source_story=False,
            created_at=now,
            updated_at=now,
        )
        script_checkpoint = ScriptForgingCheckpoint(
            script_forging_checkpoint_id=f"script_forging_checkpoint_scene_outline_{plugin_run_id}",
            plugin_run_id=plugin_run_id,
            checkpoint_kind="scene_outline_confirmation",
            plugin_checkpoint_id=checkpoint_id,
            source_domain_artifact_id=outline_id,
            created_at=now,
            updated_at=now,
            safe_summary="Scene outline checkpoint wrapper for M4 plugin checkpoint.",
        )
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="artifact_creation",
            step_status="waiting_for_checkpoint",
            input_refs=[prompt_package.script_adaptation_prompt_package_id],
            output_refs=[outline_id, artifact_id, version_id, checkpoint_id],
            checkpoint_id=checkpoint_id,
            output_artifact_id=artifact_id,
            safe_summary="Created M6 scene outline and waiting for checkpoint confirmation.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        outline = SceneOutlineArtifact(
            scene_outline_id=outline_id,
            plugin_run_id=plugin_run_id,
            script_forging_run_context_id=context.script_forging_run_context_id,
            script_shape_package_id=prompt_package.script_shape_package_id,
            script_adaptation_prompt_package_id=prompt_package.script_adaptation_prompt_package_id,
            selected_shape_id=prompt_package.selected_shape_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            outline_status="checkpoint_pending",
            outline_units=outline_units,
            checkpoint_id=checkpoint_id,
            plugin_output_artifact_id=artifact_id,
            plugin_output_artifact_version_id=version_id,
            created_at=now,
            updated_at=now,
            safe_summary="Scene outline artifact created from confirmed M5 prompt package.",
            warnings=[],
        )
        safety_report = self._safety_report(plugin_run_id, "scene_outline", now)
        run.run_status = "waiting_for_checkpoint"
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        self._append_unique(run.checkpoint_ids, checkpoint_id)
        self._append_unique(run.output_artifact_ids, artifact_id)
        run.safety_report_id = safety_report.safety_report_id
        self._assert_safe_write(
            {
                "run": model_to_dict(run),
                "outline": model_to_dict(outline),
                "plugin_checkpoint": model_to_dict(plugin_checkpoint),
                "script_checkpoint": model_to_dict(script_checkpoint),
                "artifact": model_to_dict(output_artifact),
                "version": model_to_dict(output_version),
                "step": model_to_dict(step),
                "safety_report": model_to_dict(safety_report),
            },
            "scene_outline_create",
            full_story_text,
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(SCENE_OUTLINE_ARTIFACTS_FILE, outline)
        self._append_model(SCRIPT_FORGING_CHECKPOINTS_FILE, script_checkpoint)
        self._append_model(PLUGIN_CHECKPOINTS_FILE, plugin_checkpoint)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
        self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context="scene_outline_create")
        self.safety.assert_no_forbidden_m6_files()
        return SceneOutlineArtifactResponse(
            scene_outline=outline,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            step=step,
            safety_report=safety_report,
            safe_summary="Scene outline artifact created and checkpointed.",
        )

    def get_scene_outline(self, plugin_run_id: str) -> SceneOutlineArtifactResponse:
        run = self._load_run(plugin_run_id)
        outline = self._scene_outline_for_run(plugin_run_id)
        if outline is None:
            raise StorageError(f"SCENE_OUTLINE_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        return self._scene_outline_response(run, outline)

    def submit_scene_outline_checkpoint_decision(
        self,
        plugin_run_id: str,
        decision_type: str,
        request: ScriptForgingDecisionRequest,
    ) -> ScriptForgingDecisionResponse:
        outline = self._scene_outline_for_run(plugin_run_id)
        if outline is None:
            raise StorageError(f"SCENE_OUTLINE_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        return self._submit_domain_checkpoint_decision(
            plugin_run_id=plugin_run_id,
            decision_type=decision_type,
            request=request,
            script_checkpoint_kind="scene_outline_confirmation",
            domain_artifact_id=outline.scene_outline_id,
            status_setter=lambda status, now: self._set_scene_outline_status(outline, status, now),
            confirmed_run_status="checkpoint_confirmed",
            completion_stage="scene_outline",
            guard_files=GUARDED_M6_NO_MUTATION_FILES,
            forbidden_scope="m6",
        )

    def create_screenplay_draft(self, plugin_run_id: str) -> ScreenplayDraftArtifactResponse:
        run, context, prompt_package = self._m6_gate(plugin_run_id)
        outline = self._scene_outline_for_run(plugin_run_id)
        if outline is None:
            raise StorageError(f"SCENE_OUTLINE_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        if outline.outline_status != "confirmed":
            raise StorageError(f"SCENE_OUTLINE_ARTIFACT_NOT_CONFIRMED:{outline.outline_status}")
        existing = self._screenplay_draft_for_run(plugin_run_id)
        if existing:
            return self._screenplay_draft_response(run, existing)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        before = self.safety.selected_hashes(GUARDED_M6_NO_MUTATION_FILES)
        now = now_iso()
        draft_id = f"screenplay_draft_{plugin_run_id}"
        step_id = f"{plugin_run_id}_step_screenplay_draft_{self._time_suffix(now)}"
        checkpoint_id = f"{plugin_run_id}_checkpoint_screenplay_draft_{self._time_suffix(now)}"
        artifact_id = f"{plugin_run_id}_artifact_screenplay_draft"
        version_id = f"{artifact_id}_version_001"
        script_units = self._screenplay_script_units(outline, prompt_package)
        structured_summary = {
            "derivative_artifact_kind": "screenplay_draft_artifact",
            "screenplay_draft_id": draft_id,
            "plugin_run_id": plugin_run_id,
            "snapshot_id": run.final_story_package_snapshot_id,
            "scene_outline_id": outline.scene_outline_id,
            "script_unit_count": len(script_units),
            "complete_story_text_hash": context.complete_story_text_hash,
            "mutates_source_story": False,
        }
        output_version = self._artifact_version(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_id=version_id,
            structured_summary=structured_summary,
            safe_preview=f"Screenplay draft artifact with {len(script_units)} bounded script units.",
            step_id=step_id,
            checkpoint_id=checkpoint_id,
            now=now,
        )
        output_artifact = self._artifact(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            plugin_id=run.plugin_id,
            project_id=run.project_id,
            snapshot_id=run.final_story_package_snapshot_id,
            manifest_id=run.manifest_id,
            version_id=version_id,
            safe_title="Script Forging Screenplay Draft",
            safe_summary="Derivative screenplay draft artifact from confirmed scene outline.",
            now=now,
            status="checkpoint_pending",
        )
        plugin_checkpoint = PluginCheckpoint(
            checkpoint_id=checkpoint_id,
            plugin_run_id=plugin_run_id,
            step_id=step_id,
            checkpoint_type="generic_confirmation",
            checkpoint_status="pending",
            checkpoint_prompt="Confirm the screenplay draft artifact after reviewing the self-check.",
            user_visible_summary="This checkpoint confirms only the M6 screenplay draft artifact.",
            source_artifact_ids=[artifact_id],
            confirms_plugin_step_only=True,
            mutates_source_story=False,
            created_at=now,
            updated_at=now,
        )
        script_checkpoint = ScriptForgingCheckpoint(
            script_forging_checkpoint_id=f"script_forging_checkpoint_screenplay_draft_{plugin_run_id}",
            plugin_run_id=plugin_run_id,
            checkpoint_kind="screenplay_draft_confirmation",
            plugin_checkpoint_id=checkpoint_id,
            source_domain_artifact_id=draft_id,
            created_at=now,
            updated_at=now,
            safe_summary="Screenplay draft checkpoint wrapper for M4 plugin checkpoint.",
        )
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="artifact_creation",
            step_status="waiting_for_checkpoint",
            input_refs=[outline.scene_outline_id, prompt_package.script_adaptation_prompt_package_id],
            output_refs=[draft_id, artifact_id, version_id, checkpoint_id],
            checkpoint_id=checkpoint_id,
            output_artifact_id=artifact_id,
            safe_summary="Created M6 screenplay draft and waiting for checkpoint confirmation.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        draft = ScreenplayDraftArtifact(
            screenplay_draft_id=draft_id,
            plugin_run_id=plugin_run_id,
            script_forging_run_context_id=context.script_forging_run_context_id,
            script_shape_package_id=prompt_package.script_shape_package_id,
            script_adaptation_prompt_package_id=prompt_package.script_adaptation_prompt_package_id,
            scene_outline_id=outline.scene_outline_id,
            selected_shape_id=prompt_package.selected_shape_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            draft_status="checkpoint_pending",
            script_units=script_units,
            checkpoint_id=checkpoint_id,
            plugin_output_artifact_id=artifact_id,
            plugin_output_artifact_version_id=version_id,
            created_at=now,
            updated_at=now,
            safe_summary="Screenplay draft artifact created as bounded script units.",
            warnings=[],
        )
        safety_report = self._safety_report(plugin_run_id, "screenplay_draft", now)
        run.run_status = "waiting_for_checkpoint"
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        self._append_unique(run.checkpoint_ids, checkpoint_id)
        self._append_unique(run.output_artifact_ids, artifact_id)
        run.safety_report_id = safety_report.safety_report_id
        self._assert_safe_write(
            {
                "run": model_to_dict(run),
                "draft": model_to_dict(draft),
                "plugin_checkpoint": model_to_dict(plugin_checkpoint),
                "script_checkpoint": model_to_dict(script_checkpoint),
                "artifact": model_to_dict(output_artifact),
                "version": model_to_dict(output_version),
                "step": model_to_dict(step),
                "safety_report": model_to_dict(safety_report),
            },
            "screenplay_draft_create",
            full_story_text,
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(SCREENPLAY_DRAFT_ARTIFACTS_FILE, draft)
        self._append_model(SCRIPT_FORGING_CHECKPOINTS_FILE, script_checkpoint)
        self._append_model(PLUGIN_CHECKPOINTS_FILE, plugin_checkpoint)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
        self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context="screenplay_draft_create")
        self.safety.assert_no_forbidden_m6_files()
        return ScreenplayDraftArtifactResponse(
            screenplay_draft=draft,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            step=step,
            safety_report=safety_report,
            safe_summary="Screenplay draft artifact created and checkpointed.",
        )

    def get_screenplay_draft(self, plugin_run_id: str) -> ScreenplayDraftArtifactResponse:
        run = self._load_run(plugin_run_id)
        draft = self._screenplay_draft_for_run(plugin_run_id)
        if draft is None:
            raise StorageError(f"SCREENPLAY_DRAFT_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        return self._screenplay_draft_response(run, draft)

    def submit_screenplay_draft_checkpoint_decision(
        self,
        plugin_run_id: str,
        decision_type: str,
        request: ScriptForgingDecisionRequest,
    ) -> ScriptForgingDecisionResponse:
        draft = self._screenplay_draft_for_run(plugin_run_id)
        if draft is None:
            raise StorageError(f"SCREENPLAY_DRAFT_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        if decision_type == "confirm":
            self._self_check_for_draft(plugin_run_id, draft)
        return self._submit_domain_checkpoint_decision(
            plugin_run_id=plugin_run_id,
            decision_type=decision_type,
            request=request,
            script_checkpoint_kind="screenplay_draft_confirmation",
            domain_artifact_id=draft.screenplay_draft_id,
            status_setter=lambda status, now: self._set_screenplay_draft_status(draft, status, now),
            confirmed_run_status="completed",
            completion_stage="screenplay_draft",
            guard_files=GUARDED_M6_NO_MUTATION_FILES,
            forbidden_scope="m6",
        )

    def create_screenplay_self_check(self, plugin_run_id: str) -> ScreenplaySelfCheckReportResponse:
        run, context, prompt_package = self._m6_gate(plugin_run_id)
        outline = self._scene_outline_for_run(plugin_run_id)
        draft = self._screenplay_draft_for_run(plugin_run_id)
        if outline is None:
            raise StorageError(f"SCENE_OUTLINE_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        if draft is None:
            raise StorageError(f"SCREENPLAY_DRAFT_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        if draft.draft_status != "checkpoint_pending":
            raise StorageError(f"SCREENPLAY_DRAFT_NOT_SELF_CHECKABLE:{draft.draft_status}")
        existing = self._self_check_for_run(plugin_run_id)
        if existing:
            return self._self_check_response(run, existing)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        before = self.safety.selected_hashes(GUARDED_M6_NO_MUTATION_FILES)
        now = now_iso()
        report_id = f"screenplay_self_check_{plugin_run_id}"
        step_id = f"{plugin_run_id}_step_screenplay_self_check_{self._time_suffix(now)}"
        artifact_id = f"{plugin_run_id}_artifact_screenplay_self_check"
        version_id = f"{artifact_id}_version_001"
        report = ScreenplaySelfCheckReport(
            self_check_report_id=report_id,
            plugin_run_id=plugin_run_id,
            script_forging_run_context_id=context.script_forging_run_context_id,
            script_adaptation_prompt_package_id=prompt_package.script_adaptation_prompt_package_id,
            scene_outline_id=outline.scene_outline_id,
            screenplay_draft_id=draft.screenplay_draft_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            report_status="needs_revision",
            preserved_element_coverage=self._coverage_checks(prompt_package, draft),
            forbidden_change_checks=[{"check": "no_unverified_outcomes", "status": "pass"}, {"check": "no_source_story_writeback", "status": "pass"}],
            continuity_checks=[{"check": "scene_order_matches_outline", "status": "pass"}, {"check": "source_ref_policy_present", "status": "pass"}],
            drift_checks=[{"check": "shape_strategy_retained", "status": "pass"}, {"check": "compression_scope_review", "status": "warn"}],
            format_checks=[{"check": "bounded_script_units", "status": "pass"}, {"check": "revision_candidate_recommended", "status": "warn"}],
            safety_checks=[{"check": "no_raw_provider_payload", "status": "pass"}, {"check": "no_secret_marker", "status": "pass"}],
            issue_codes=["tighten_transition_language"],
            requires_revision_candidate=True,
            plugin_output_artifact_id=artifact_id,
            plugin_output_artifact_version_id=version_id,
            created_at=now,
            safe_summary="Self-check report recommends one bounded revision candidate without applying it.",
            warnings=["One format tightening candidate is recommended."],
        )
        structured_summary = {
            "derivative_artifact_kind": "screenplay_self_check_report",
            "self_check_report_id": report_id,
            "screenplay_draft_id": draft.screenplay_draft_id,
            "issue_count": len(report.issue_codes),
            "requires_revision_candidate": report.requires_revision_candidate,
            "mutates_source_story": False,
        }
        output_version = self._artifact_version(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_id=version_id,
            structured_summary=structured_summary,
            safe_preview="Screenplay self-check report with bounded issue codes and status groups.",
            step_id=step_id,
            checkpoint_id="",
            now=now,
        )
        output_artifact = self._artifact(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            plugin_id=run.plugin_id,
            project_id=run.project_id,
            snapshot_id=run.final_story_package_snapshot_id,
            manifest_id=run.manifest_id,
            version_id=version_id,
            safe_title="Script Forging Screenplay Self-Check",
            safe_summary="Derivative self-check report for the M6 screenplay draft.",
            now=now,
            status="confirmed",
        )
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="artifact_creation",
            step_status="completed",
            input_refs=[draft.screenplay_draft_id, outline.scene_outline_id],
            output_refs=[report_id, artifact_id, version_id],
            output_artifact_id=artifact_id,
            safe_summary="Created M6 screenplay self-check report.",
            warnings=list(report.warnings),
            created_at=now,
            updated_at=now,
        )
        safety_report = self._safety_report(plugin_run_id, "screenplay_self_check", now)
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        self._append_unique(run.output_artifact_ids, artifact_id)
        run.safety_report_id = safety_report.safety_report_id
        self._assert_safe_write(
            {
                "run": model_to_dict(run),
                "report": model_to_dict(report),
                "artifact": model_to_dict(output_artifact),
                "version": model_to_dict(output_version),
                "step": model_to_dict(step),
                "safety_report": model_to_dict(safety_report),
            },
            "screenplay_self_check_create",
            full_story_text,
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(SCREENPLAY_SELF_CHECK_REPORTS_FILE, report)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
        self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context="screenplay_self_check_create")
        self.safety.assert_no_forbidden_m6_files()
        return ScreenplaySelfCheckReportResponse(
            self_check_report=report,
            plugin_run=run,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            step=step,
            safety_report=safety_report,
            safe_summary="Screenplay self-check report created.",
        )

    def get_screenplay_self_check(self, plugin_run_id: str) -> ScreenplaySelfCheckReportResponse:
        run = self._load_run(plugin_run_id)
        report = self._self_check_for_run(plugin_run_id)
        if report is None:
            raise StorageError(f"SCREENPLAY_SELF_CHECK_REPORT_NOT_FOUND:{plugin_run_id}")
        return self._self_check_response(run, report)

    def create_screenplay_revision_candidate(self, plugin_run_id: str) -> ScreenplayRevisionCandidateResponse:
        run, context, prompt_package = self._m6_gate(plugin_run_id)
        outline = self._scene_outline_for_run(plugin_run_id)
        draft = self._screenplay_draft_for_run(plugin_run_id)
        if outline is None:
            raise StorageError(f"SCENE_OUTLINE_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        if draft is None:
            raise StorageError(f"SCREENPLAY_DRAFT_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        if draft.draft_status != "checkpoint_pending":
            raise StorageError(f"SCREENPLAY_DRAFT_NOT_REVISION_CANDIDATE_ELIGIBLE:{draft.draft_status}")
        report = self._self_check_for_draft(plugin_run_id, draft, require_revision_candidate=True)
        existing = self._revision_candidate_for_run(plugin_run_id)
        if existing:
            return self._revision_candidate_response(run, existing)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        before = self.safety.selected_hashes(GUARDED_M6_NO_MUTATION_FILES)
        now = now_iso()
        candidate_id = f"screenplay_revision_candidate_{plugin_run_id}"
        step_id = f"{plugin_run_id}_step_screenplay_revision_candidate_{self._time_suffix(now)}"
        artifact_id = f"{plugin_run_id}_artifact_screenplay_revision_candidate"
        version_id = f"{artifact_id}_version_001"
        candidate = ScreenplayRevisionCandidate(
            revision_candidate_id=candidate_id,
            plugin_run_id=plugin_run_id,
            script_forging_run_context_id=context.script_forging_run_context_id,
            script_adaptation_prompt_package_id=prompt_package.script_adaptation_prompt_package_id,
            scene_outline_id=outline.scene_outline_id,
            screenplay_draft_id=draft.screenplay_draft_id,
            self_check_report_id=report.self_check_report_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            candidate_status="created",
            proposed_changes=[
                {
                    "change_id": "revise_transition_language",
                    "target": draft.script_units[-1].script_unit_id if draft.script_units else draft.screenplay_draft_id,
                    "safe_summary": "Tighten transition language while preserving outline order.",
                    "does_not_apply_automatically": True,
                }
            ],
            plugin_output_artifact_id=artifact_id,
            plugin_output_artifact_version_id=version_id,
            created_at=now,
            safe_summary="Revision candidate proposes bounded changes and does not overwrite the draft.",
            warnings=[],
        )
        structured_summary = {
            "derivative_artifact_kind": "screenplay_revision_candidate",
            "revision_candidate_id": candidate_id,
            "screenplay_draft_id": draft.screenplay_draft_id,
            "self_check_report_id": report.self_check_report_id,
            "proposed_change_count": len(candidate.proposed_changes),
            "does_not_overwrite_screenplay_draft": True,
            "mutates_source_story": False,
        }
        output_version = self._artifact_version(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_id=version_id,
            structured_summary=structured_summary,
            safe_preview="Screenplay revision candidate with bounded proposed change metadata.",
            step_id=step_id,
            checkpoint_id="",
            now=now,
        )
        output_artifact = self._artifact(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            plugin_id=run.plugin_id,
            project_id=run.project_id,
            snapshot_id=run.final_story_package_snapshot_id,
            manifest_id=run.manifest_id,
            version_id=version_id,
            safe_title="Script Forging Screenplay Revision Candidate",
            safe_summary="Derivative revision candidate; not applied automatically.",
            now=now,
            status="confirmed",
        )
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="artifact_creation",
            step_status="completed",
            input_refs=[draft.screenplay_draft_id, report.self_check_report_id],
            output_refs=[candidate_id, artifact_id, version_id],
            output_artifact_id=artifact_id,
            safe_summary="Created non-applying M6 screenplay revision candidate.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        safety_report = self._safety_report(plugin_run_id, "screenplay_revision_candidate", now)
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        self._append_unique(run.output_artifact_ids, artifact_id)
        run.safety_report_id = safety_report.safety_report_id
        self._assert_safe_write(
            {
                "run": model_to_dict(run),
                "candidate": model_to_dict(candidate),
                "artifact": model_to_dict(output_artifact),
                "version": model_to_dict(output_version),
                "step": model_to_dict(step),
                "safety_report": model_to_dict(safety_report),
            },
            "screenplay_revision_candidate_create",
            full_story_text,
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(SCREENPLAY_REVISION_CANDIDATES_FILE, candidate)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
        self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context="screenplay_revision_candidate_create")
        self.safety.assert_no_forbidden_m6_files()
        return ScreenplayRevisionCandidateResponse(
            revision_candidate=candidate,
            plugin_run=run,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            step=step,
            safety_report=safety_report,
            safe_summary="Screenplay revision candidate created without applying it.",
        )

    def list_screenplay_revision_candidates(self, plugin_run_id: str) -> ScreenplayRevisionCandidateListResponse:
        candidates = [
            ScreenplayRevisionCandidate(**row)
            for row in self._read_list(SCREENPLAY_REVISION_CANDIDATES_FILE)
            if row.get("plugin_run_id") == plugin_run_id
        ]
        return ScreenplayRevisionCandidateListResponse(
            plugin_run_id=plugin_run_id,
            revision_candidates=candidates,
            total_count=len(candidates),
            safe_summary="Screenplay revision candidates loaded.",
        )

    def create_storyboard_package(self, plugin_run_id: str) -> StoryboardPackageResponse:
        run, outline, draft, report, revision_candidate = self._m7_gate(plugin_run_id)
        existing = self._storyboard_package_for_run(plugin_run_id)
        if existing:
            self._assert_storyboard_package_source_binding(existing, run, outline, draft, report, revision_candidate)
            return self._storyboard_package_response(run, existing)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        before = self.safety.selected_hashes(GUARDED_M7_NO_MUTATION_FILES)
        now = now_iso()
        package_id = f"storyboard_package_{plugin_run_id}"
        step_id = f"{plugin_run_id}_step_storyboard_package_{self._time_suffix(now)}"
        checkpoint_id = f"{plugin_run_id}_checkpoint_storyboard_package_{self._time_suffix(now)}"
        artifact_id = f"{plugin_run_id}_artifact_storyboard_package"
        version_id = f"{artifact_id}_version_001"
        revision_id = revision_candidate.revision_candidate_id if revision_candidate else ""
        key_storyboards = self._key_storyboards_for_sources(package_id, run, outline, draft, report, revision_id, now)
        scene_storyboards = self._scene_storyboards_for_sources(package_id, run, outline, draft, report, revision_id, key_storyboards, now)
        shot_list = self._shot_list_for_sources(package_id, run, outline, draft, report, revision_id, key_storyboards, now)
        package = StoryboardPackage(
            storyboard_package_id=package_id,
            plugin_run_id=plugin_run_id,
            source_scene_outline_artifact_id=outline.scene_outline_id,
            source_screenplay_draft_artifact_id=draft.screenplay_draft_id,
            source_screenplay_self_check_report_id=report.self_check_report_id,
            source_revision_candidate_id=revision_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            package_status="checkpoint_pending",
            key_storyboard_artifact_ids=[item.key_storyboard_artifact_id for item in key_storyboards],
            scene_storyboard_artifact_ids=[item.scene_storyboard_artifact_id for item in scene_storyboards],
            shot_list_artifact_id=shot_list.shot_list_artifact_id,
            checkpoint_id=checkpoint_id,
            plugin_output_artifact_id=artifact_id,
            plugin_output_artifact_version_id=version_id,
            provenance=self._m7_provenance(outline, draft, report, revision_id),
            created_at=now,
            updated_at=now,
            safe_summary="Storyboard package created from confirmed M6 screenplay basis.",
            warnings=[],
        )
        structured_summary = {
            "derivative_artifact_kind": "storyboard_package",
            "storyboard_package_id": package_id,
            "source_scene_outline_artifact_id": outline.scene_outline_id,
            "source_screenplay_draft_artifact_id": draft.screenplay_draft_id,
            "source_screenplay_self_check_report_id": report.self_check_report_id,
            "source_revision_candidate_id": revision_id,
            "key_storyboard_count": len(key_storyboards),
            "scene_storyboard_count": len(scene_storyboards),
            "shot_count": len(shot_list.shots),
            "mutates_source_story": False,
            "external_media_provider_called": False,
        }
        output_version = self._artifact_version(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_id=version_id,
            structured_summary=structured_summary,
            safe_preview="Storyboard package with bounded key panels, scene panels, and shot list metadata.",
            step_id=step_id,
            checkpoint_id=checkpoint_id,
            now=now,
        )
        output_artifact = self._artifact(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            plugin_id=run.plugin_id,
            project_id=run.project_id,
            snapshot_id=run.final_story_package_snapshot_id,
            manifest_id=run.manifest_id,
            version_id=version_id,
            safe_title="Script Forging Storyboard Package",
            safe_summary="Derivative storyboard package from confirmed M6 screenplay artifacts.",
            now=now,
            status="checkpoint_pending",
        )
        plugin_checkpoint = PluginCheckpoint(
            checkpoint_id=checkpoint_id,
            plugin_run_id=plugin_run_id,
            step_id=step_id,
            checkpoint_type="generic_confirmation",
            checkpoint_status="pending",
            checkpoint_prompt="Confirm the storyboard package before creating the digital asset package.",
            user_visible_summary="This checkpoint confirms only the M7 storyboard package.",
            source_artifact_ids=[artifact_id],
            confirms_plugin_step_only=True,
            mutates_source_story=False,
            created_at=now,
            updated_at=now,
        )
        script_checkpoint = ScriptForgingCheckpoint(
            script_forging_checkpoint_id=f"script_forging_checkpoint_storyboard_package_{plugin_run_id}",
            plugin_run_id=plugin_run_id,
            checkpoint_kind="storyboard_package_confirmation",
            plugin_checkpoint_id=checkpoint_id,
            source_domain_artifact_id=package_id,
            created_at=now,
            updated_at=now,
            safe_summary="Storyboard package checkpoint wrapper for M4 plugin checkpoint.",
        )
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="artifact_creation",
            step_status="waiting_for_checkpoint",
            input_refs=[outline.scene_outline_id, draft.screenplay_draft_id, report.self_check_report_id],
            output_refs=[package_id, artifact_id, version_id, checkpoint_id],
            checkpoint_id=checkpoint_id,
            output_artifact_id=artifact_id,
            safe_summary="Created M7 storyboard package and waiting for checkpoint confirmation.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        safety_report = self._safety_report(plugin_run_id, "storyboard_package", now)
        run.run_status = "waiting_for_checkpoint"
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        self._append_unique(run.checkpoint_ids, checkpoint_id)
        self._append_unique(run.output_artifact_ids, artifact_id)
        run.safety_report_id = safety_report.safety_report_id
        self._assert_safe_write(
            {
                "run": model_to_dict(run),
                "storyboard_package": model_to_dict(package),
                "key_storyboards": [model_to_dict(item) for item in key_storyboards],
                "scene_storyboards": [model_to_dict(item) for item in scene_storyboards],
                "shot_list": model_to_dict(shot_list),
                "plugin_checkpoint": model_to_dict(plugin_checkpoint),
                "script_checkpoint": model_to_dict(script_checkpoint),
                "artifact": model_to_dict(output_artifact),
                "version": model_to_dict(output_version),
                "step": model_to_dict(step),
                "safety_report": model_to_dict(safety_report),
            },
            "storyboard_package_create",
            full_story_text,
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(STORYBOARD_PACKAGES_FILE, package)
        for item in key_storyboards:
            self._append_model(KEY_STORYBOARD_ARTIFACTS_FILE, item)
        for item in scene_storyboards:
            self._append_model(SCENE_STORYBOARD_ARTIFACTS_FILE, item)
        self._append_model(SHOT_LIST_ARTIFACTS_FILE, shot_list)
        self._append_model(SCRIPT_FORGING_CHECKPOINTS_FILE, script_checkpoint)
        self._append_model(PLUGIN_CHECKPOINTS_FILE, plugin_checkpoint)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
        self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context="storyboard_package_create")
        self.safety.assert_no_forbidden_m7_files()
        return StoryboardPackageResponse(
            storyboard_package=package,
            key_storyboards=key_storyboards,
            scene_storyboards=scene_storyboards,
            shot_list=shot_list,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            step=step,
            safety_report=safety_report,
            safe_summary="Storyboard package created and checkpointed.",
        )

    def get_storyboard_package(self, plugin_run_id: str) -> StoryboardPackageResponse:
        run = self._load_run(plugin_run_id)
        package = self._storyboard_package_for_run(plugin_run_id)
        if package is None:
            raise StorageError(f"STORYBOARD_PACKAGE_NOT_FOUND:{plugin_run_id}")
        return self._storyboard_package_response(run, package)

    def submit_storyboard_package_checkpoint_decision(
        self,
        plugin_run_id: str,
        decision_type: str,
        request: ScriptForgingDecisionRequest,
    ) -> ScriptForgingDecisionResponse:
        run, outline, draft, report, revision_candidate = self._m7_gate(plugin_run_id)
        package = self._storyboard_package_for_run(plugin_run_id)
        if package is None:
            raise StorageError(f"STORYBOARD_PACKAGE_NOT_FOUND:{plugin_run_id}")
        self._assert_storyboard_package_source_binding(package, run, outline, draft, report, revision_candidate)
        return self._submit_domain_checkpoint_decision(
            plugin_run_id=plugin_run_id,
            decision_type=decision_type,
            request=request,
            script_checkpoint_kind="storyboard_package_confirmation",
            domain_artifact_id=package.storyboard_package_id,
            status_setter=lambda status, now: self._set_storyboard_package_status(package, status, now),
            confirmed_run_status="checkpoint_confirmed",
            completion_stage="storyboard_package",
            guard_files=GUARDED_M7_NO_MUTATION_FILES,
            forbidden_scope="m7",
        )

    def list_key_storyboard_artifacts(self, plugin_run_id: str) -> KeyStoryboardArtifactListResponse:
        items = [
            KeyStoryboardArtifact(**row)
            for row in self._read_list(KEY_STORYBOARD_ARTIFACTS_FILE)
            if row.get("plugin_run_id") == plugin_run_id
        ]
        return KeyStoryboardArtifactListResponse(
            plugin_run_id=plugin_run_id,
            key_storyboards=items,
            total_count=len(items),
            safe_summary="Key storyboard artifacts loaded.",
        )

    def list_scene_storyboard_artifacts(self, plugin_run_id: str) -> SceneStoryboardArtifactListResponse:
        items = [
            SceneStoryboardArtifact(**row)
            for row in self._read_list(SCENE_STORYBOARD_ARTIFACTS_FILE)
            if row.get("plugin_run_id") == plugin_run_id
        ]
        return SceneStoryboardArtifactListResponse(
            plugin_run_id=plugin_run_id,
            scene_storyboards=items,
            total_count=len(items),
            safe_summary="Scene storyboard artifacts loaded.",
        )

    def get_shot_list_artifact(self, plugin_run_id: str) -> ShotListArtifactResponse:
        shot_list = self._shot_list_for_run(plugin_run_id)
        if shot_list is None:
            raise StorageError(f"SHOT_LIST_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        return ShotListArtifactResponse(shot_list=shot_list, safe_summary="Shot list artifact loaded.")

    def create_digital_asset_package(self, plugin_run_id: str) -> DigitalAssetPackageResponse:
        run, outline, draft, report, revision_candidate = self._m7_gate(plugin_run_id)
        storyboard = self._storyboard_package_for_run(plugin_run_id)
        if storyboard is None:
            raise StorageError(f"STORYBOARD_PACKAGE_NOT_FOUND:{plugin_run_id}")
        if storyboard.package_status != "confirmed":
            raise StorageError(f"STORYBOARD_PACKAGE_NOT_CONFIRMED:{storyboard.package_status}")
        self._assert_storyboard_package_source_binding(storyboard, run, outline, draft, report, revision_candidate)
        existing = self._digital_asset_package_for_run(plugin_run_id)
        if existing:
            self._assert_digital_asset_package_source_binding(existing, run, storyboard, outline, draft, report, revision_candidate)
            return self._digital_asset_package_response(run, existing)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        before = self.safety.selected_hashes(GUARDED_M7_NO_MUTATION_FILES)
        now = now_iso()
        package_id = f"digital_asset_package_{plugin_run_id}"
        step_id = f"{plugin_run_id}_step_digital_asset_package_{self._time_suffix(now)}"
        checkpoint_id = f"{plugin_run_id}_checkpoint_digital_asset_package_{self._time_suffix(now)}"
        artifact_id = f"{plugin_run_id}_artifact_digital_asset_package"
        version_id = f"{artifact_id}_version_001"
        revision_id = revision_candidate.revision_candidate_id if revision_candidate else ""
        character_assets = self._asset_list_record(CharacterAssetList, package_id, storyboard, run, outline, draft, report, revision_id, now, "character")
        location_assets = self._asset_list_record(LocationAssetList, package_id, storyboard, run, outline, draft, report, revision_id, now, "location")
        prop_assets = self._asset_list_record(PropAssetList, package_id, storyboard, run, outline, draft, report, revision_id, now, "prop")
        motif_assets = self._asset_list_record(MotifAssetList, package_id, storyboard, run, outline, draft, report, revision_id, now, "motif")
        costume_assets = self._asset_list_record(CostumeContinuityList, package_id, storyboard, run, outline, draft, report, revision_id, now, "costume_continuity")
        package = DigitalAssetPackage(
            digital_asset_package_id=package_id,
            plugin_run_id=plugin_run_id,
            source_storyboard_package_id=storyboard.storyboard_package_id,
            source_scene_outline_artifact_id=outline.scene_outline_id,
            source_screenplay_draft_artifact_id=draft.screenplay_draft_id,
            source_screenplay_self_check_report_id=report.self_check_report_id,
            source_revision_candidate_id=revision_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            package_status="checkpoint_pending",
            character_asset_list_id=character_assets.character_asset_list_id,
            location_asset_list_id=location_assets.location_asset_list_id,
            prop_asset_list_id=prop_assets.prop_asset_list_id,
            motif_asset_list_id=motif_assets.motif_asset_list_id,
            costume_continuity_list_id=costume_assets.costume_continuity_list_id,
            checkpoint_id=checkpoint_id,
            plugin_output_artifact_id=artifact_id,
            plugin_output_artifact_version_id=version_id,
            provenance=self._m7_provenance(outline, draft, report, revision_id),
            created_at=now,
            updated_at=now,
            safe_summary="Digital asset package plan created from confirmed storyboard package.",
            warnings=[],
        )
        structured_summary = {
            "derivative_artifact_kind": "digital_asset_package",
            "digital_asset_package_id": package_id,
            "source_storyboard_package_id": storyboard.storyboard_package_id,
            "asset_list_families": ["characters", "locations", "props", "motifs", "costume_continuity"],
            "mutates_source_story": False,
            "external_media_provider_called": False,
        }
        output_version = self._artifact_version(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_id=version_id,
            structured_summary=structured_summary,
            safe_preview="Digital asset package with bounded character, location, prop, motif, and costume continuity lists.",
            step_id=step_id,
            checkpoint_id=checkpoint_id,
            now=now,
        )
        output_artifact = self._artifact(
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            plugin_id=run.plugin_id,
            project_id=run.project_id,
            snapshot_id=run.final_story_package_snapshot_id,
            manifest_id=run.manifest_id,
            version_id=version_id,
            safe_title="Script Forging Digital Asset Package",
            safe_summary="Derivative digital asset planning package; no media is generated.",
            now=now,
            status="checkpoint_pending",
        )
        plugin_checkpoint = PluginCheckpoint(
            checkpoint_id=checkpoint_id,
            plugin_run_id=plugin_run_id,
            step_id=step_id,
            checkpoint_type="generic_confirmation",
            checkpoint_status="pending",
            checkpoint_prompt="Confirm the digital asset package planning record.",
            user_visible_summary="This checkpoint confirms only the M7 digital asset package.",
            source_artifact_ids=[artifact_id],
            confirms_plugin_step_only=True,
            mutates_source_story=False,
            created_at=now,
            updated_at=now,
        )
        script_checkpoint = ScriptForgingCheckpoint(
            script_forging_checkpoint_id=f"script_forging_checkpoint_digital_asset_package_{plugin_run_id}",
            plugin_run_id=plugin_run_id,
            checkpoint_kind="digital_asset_package_confirmation",
            plugin_checkpoint_id=checkpoint_id,
            source_domain_artifact_id=package_id,
            created_at=now,
            updated_at=now,
            safe_summary="Digital asset package checkpoint wrapper for M4 plugin checkpoint.",
        )
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="artifact_creation",
            step_status="waiting_for_checkpoint",
            input_refs=[storyboard.storyboard_package_id, draft.screenplay_draft_id, report.self_check_report_id],
            output_refs=[package_id, artifact_id, version_id, checkpoint_id],
            checkpoint_id=checkpoint_id,
            output_artifact_id=artifact_id,
            safe_summary="Created M7 digital asset package and waiting for checkpoint confirmation.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        safety_report = self._safety_report(plugin_run_id, "digital_asset_package", now)
        run.run_status = "waiting_for_checkpoint"
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        self._append_unique(run.checkpoint_ids, checkpoint_id)
        self._append_unique(run.output_artifact_ids, artifact_id)
        run.safety_report_id = safety_report.safety_report_id
        self._assert_safe_write(
            {
                "run": model_to_dict(run),
                "digital_asset_package": model_to_dict(package),
                "character_assets": model_to_dict(character_assets),
                "location_assets": model_to_dict(location_assets),
                "prop_assets": model_to_dict(prop_assets),
                "motif_assets": model_to_dict(motif_assets),
                "costume_assets": model_to_dict(costume_assets),
                "plugin_checkpoint": model_to_dict(plugin_checkpoint),
                "script_checkpoint": model_to_dict(script_checkpoint),
                "artifact": model_to_dict(output_artifact),
                "version": model_to_dict(output_version),
                "step": model_to_dict(step),
                "safety_report": model_to_dict(safety_report),
            },
            "digital_asset_package_create",
            full_story_text,
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(DIGITAL_ASSET_PACKAGES_FILE, package)
        self._append_model(CHARACTER_ASSET_LISTS_FILE, character_assets)
        self._append_model(LOCATION_ASSET_LISTS_FILE, location_assets)
        self._append_model(PROP_ASSET_LISTS_FILE, prop_assets)
        self._append_model(MOTIF_ASSET_LISTS_FILE, motif_assets)
        self._append_model(COSTUME_CONTINUITY_LISTS_FILE, costume_assets)
        self._append_model(SCRIPT_FORGING_CHECKPOINTS_FILE, script_checkpoint)
        self._append_model(PLUGIN_CHECKPOINTS_FILE, plugin_checkpoint)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
        self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context="digital_asset_package_create")
        self.safety.assert_no_forbidden_m7_files()
        return DigitalAssetPackageResponse(
            digital_asset_package=package,
            character_asset_list=character_assets,
            location_asset_list=location_assets,
            prop_asset_list=prop_assets,
            motif_asset_list=motif_assets,
            costume_continuity_list=costume_assets,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            step=step,
            safety_report=safety_report,
            safe_summary="Digital asset package created and checkpointed.",
        )

    def get_digital_asset_package(self, plugin_run_id: str) -> DigitalAssetPackageResponse:
        run = self._load_run(plugin_run_id)
        package = self._digital_asset_package_for_run(plugin_run_id)
        if package is None:
            raise StorageError(f"DIGITAL_ASSET_PACKAGE_NOT_FOUND:{plugin_run_id}")
        return self._digital_asset_package_response(run, package)

    def submit_digital_asset_package_checkpoint_decision(
        self,
        plugin_run_id: str,
        decision_type: str,
        request: ScriptForgingDecisionRequest,
    ) -> ScriptForgingDecisionResponse:
        run, outline, draft, report, revision_candidate = self._m7_gate(plugin_run_id)
        storyboard = self._storyboard_package_for_run(plugin_run_id)
        if storyboard is None:
            raise StorageError(f"STORYBOARD_PACKAGE_NOT_FOUND:{plugin_run_id}")
        self._assert_storyboard_package_source_binding(storyboard, run, outline, draft, report, revision_candidate)
        package = self._digital_asset_package_for_run(plugin_run_id)
        if package is None:
            raise StorageError(f"DIGITAL_ASSET_PACKAGE_NOT_FOUND:{plugin_run_id}")
        self._assert_digital_asset_package_source_binding(package, run, storyboard, outline, draft, report, revision_candidate)
        return self._submit_domain_checkpoint_decision(
            plugin_run_id=plugin_run_id,
            decision_type=decision_type,
            request=request,
            script_checkpoint_kind="digital_asset_package_confirmation",
            domain_artifact_id=package.digital_asset_package_id,
            status_setter=lambda status, now: self._set_digital_asset_package_status(package, status, now),
            confirmed_run_status="completed",
            completion_stage="digital_asset_package",
            guard_files=GUARDED_M7_NO_MUTATION_FILES,
            forbidden_scope="m7",
        )

    def get_character_asset_list(self, plugin_run_id: str) -> CharacterAssetListResponse:
        record = self._asset_list_for_run(CHARACTER_ASSET_LISTS_FILE, CharacterAssetList, plugin_run_id)
        return CharacterAssetListResponse(character_asset_list=record, safe_summary="Character asset list loaded.")

    def get_location_asset_list(self, plugin_run_id: str) -> LocationAssetListResponse:
        record = self._asset_list_for_run(LOCATION_ASSET_LISTS_FILE, LocationAssetList, plugin_run_id)
        return LocationAssetListResponse(location_asset_list=record, safe_summary="Location asset list loaded.")

    def get_prop_asset_list(self, plugin_run_id: str) -> PropAssetListResponse:
        record = self._asset_list_for_run(PROP_ASSET_LISTS_FILE, PropAssetList, plugin_run_id)
        return PropAssetListResponse(prop_asset_list=record, safe_summary="Prop asset list loaded.")

    def get_motif_asset_list(self, plugin_run_id: str) -> MotifAssetListResponse:
        record = self._asset_list_for_run(MOTIF_ASSET_LISTS_FILE, MotifAssetList, plugin_run_id)
        return MotifAssetListResponse(motif_asset_list=record, safe_summary="Motif asset list loaded.")

    def get_costume_continuity_list(self, plugin_run_id: str) -> CostumeContinuityListResponse:
        record = self._asset_list_for_run(COSTUME_CONTINUITY_LISTS_FILE, CostumeContinuityList, plugin_run_id)
        return CostumeContinuityListResponse(costume_continuity_list=record, safe_summary="Costume continuity list loaded.")

    def _submit_domain_checkpoint_decision(
        self,
        *,
        plugin_run_id: str,
        decision_type: str,
        request: ScriptForgingDecisionRequest,
        script_checkpoint_kind: str,
        domain_artifact_id: str,
        status_setter: Any,
        confirmed_run_status: str,
        completion_stage: str,
        guard_files: list[str] | None = None,
        forbidden_scope: str = "m5",
    ) -> ScriptForgingDecisionResponse:
        if decision_type not in {"confirm", "request_revision", "reject", "defer"}:
            raise StorageError(f"SCRIPT_FORGING_DECISION_NOT_ALLOWED:{decision_type}")
        self.safety.assert_safe_request_payload(
            {"decision_type": decision_type, **model_to_dict(request)},
            context="script_forging_decision_request",
        )
        run = self._load_run(plugin_run_id)
        snapshot = self._snapshot_for_run(run)
        full_story_text = str(snapshot.get("complete_story_text") or "")
        script_checkpoint = self._script_checkpoint(plugin_run_id, script_checkpoint_kind, domain_artifact_id)
        plugin_checkpoint = self._plugin_checkpoint(run.plugin_run_id, script_checkpoint.plugin_checkpoint_id)
        if plugin_checkpoint.checkpoint_status != "pending":
            raise StorageError(f"SCRIPT_FORGING_CHECKPOINT_NOT_PENDING:{plugin_checkpoint.checkpoint_status}")
        before = self.safety.selected_hashes(guard_files or GUARDED_M5_NO_MUTATION_FILES)
        now = now_iso()
        safe_note = sanitize_user_note(request.safe_user_note)
        requested_changes = [sanitize_user_note(item, max_length=180) for item in request.requested_changes]
        decision = PluginCheckpointDecision(
            checkpoint_decision_id=f"{plugin_checkpoint.checkpoint_id}_decision_{decision_type}_{self._time_suffix(now)}",
            plugin_run_id=plugin_run_id,
            checkpoint_id=plugin_checkpoint.checkpoint_id,
            decision_type=decision_type,  # type: ignore[arg-type]
            user_note=safe_note,
            requested_changes=requested_changes,
            decision_scope="plugin_step_only",
            does_not_modify_final_story_package=True,
            does_not_modify_source_story=True,
            created_at=now,
            version_id=f"{plugin_checkpoint.checkpoint_id}_decision_{self._time_suffix(now)}_v1",
        )
        checkpoint_status_map = {
            "confirm": "confirmed",
            "request_revision": "revision_requested",
            "reject": "rejected",
            "defer": "deferred",
        }
        package_status_map = {
            "confirm": "confirmed",
            "request_revision": "revision_requested",
            "reject": "rejected",
            "defer": "checkpoint_pending",
        }
        plugin_checkpoint.checkpoint_status = checkpoint_status_map[decision_type]  # type: ignore[assignment]
        plugin_checkpoint.decision_id = decision.checkpoint_decision_id
        plugin_checkpoint.updated_at = now
        script_checkpoint.plugin_checkpoint_decision_id = decision.checkpoint_decision_id
        script_checkpoint.updated_at = now
        updated_domain = status_setter(package_status_map[decision_type], now)
        step_id = f"{plugin_run_id}_step_script_{completion_stage}_{decision_type}_{self._time_suffix(now)}"
        step_status = "completed"
        if decision_type == "confirm":
            run.run_status = confirmed_run_status  # type: ignore[assignment]
        elif decision_type in {"request_revision", "reject"}:
            run.run_status = "blocked"
        else:
            run.run_status = "blocked"
        run.current_step_id = step_id
        run.updated_at = now
        self._append_unique(run.step_ids, step_id)
        step = PluginRunStep(
            step_id=step_id,
            plugin_run_id=plugin_run_id,
            step_type="checkpoint",
            step_status=step_status,
            input_refs=[plugin_checkpoint.checkpoint_id, decision.checkpoint_decision_id],
            output_refs=[domain_artifact_id],
            checkpoint_id=plugin_checkpoint.checkpoint_id,
            safe_summary="Script-forging checkpoint decision recorded as plugin-step-only evidence.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        safety_report = self._safety_report(plugin_run_id, f"{completion_stage}_{decision_type}", now)
        run.safety_report_id = safety_report.safety_report_id
        risk_note = self._risk_note_for_run(plugin_run_id)
        payload = {
            "run": model_to_dict(run),
            "plugin_checkpoint": model_to_dict(plugin_checkpoint),
            "script_checkpoint": model_to_dict(script_checkpoint),
            "decision": model_to_dict(decision),
            "domain": model_to_dict(updated_domain),
            "step": model_to_dict(step),
            "risk_note": model_to_dict(risk_note) if risk_note else None,
            "safety_report": model_to_dict(safety_report),
        }
        self._assert_safe_write(payload, f"script_forging_{completion_stage}_decision", full_story_text)
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._replace_model(PLUGIN_CHECKPOINTS_FILE, "checkpoint_id", plugin_checkpoint.checkpoint_id, plugin_checkpoint)
        self._replace_model(SCRIPT_FORGING_CHECKPOINTS_FILE, "script_forging_checkpoint_id", script_checkpoint.script_forging_checkpoint_id, script_checkpoint)
        self._append_model(PLUGIN_CHECKPOINT_DECISIONS_FILE, decision)
        self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety.assert_hashes_unchanged(before, context=f"script_forging_{completion_stage}_decision")
        if forbidden_scope == "m7":
            self.safety.assert_no_forbidden_m7_files()
        elif forbidden_scope == "m6":
            self.safety.assert_no_forbidden_m6_files()
        else:
            self.safety.assert_no_forbidden_m5_files()
        shape_package = updated_domain if isinstance(updated_domain, ScriptShapePackage) else self._shape_package_for_run(plugin_run_id)
        prompt_package = updated_domain if isinstance(updated_domain, ScriptAdaptationPromptPackage) else self._prompt_package_for_run(plugin_run_id)
        scene_outline = updated_domain if isinstance(updated_domain, SceneOutlineArtifact) else self._scene_outline_for_run(plugin_run_id)
        screenplay_draft = updated_domain if isinstance(updated_domain, ScreenplayDraftArtifact) else self._screenplay_draft_for_run(plugin_run_id)
        storyboard_package = updated_domain if isinstance(updated_domain, StoryboardPackage) else self._storyboard_package_for_run(plugin_run_id)
        digital_asset_package = updated_domain if isinstance(updated_domain, DigitalAssetPackage) else self._digital_asset_package_for_run(plugin_run_id)
        return ScriptForgingDecisionResponse(
            plugin_run=run,
            plugin_checkpoint=plugin_checkpoint,
            decision=decision,
            script_checkpoint=script_checkpoint,
            shape_package=shape_package,
            prompt_package=prompt_package,
            scene_outline=scene_outline,
            screenplay_draft=screenplay_draft,
            storyboard_package=storyboard_package,
            digital_asset_package=digital_asset_package,
            risk_note=risk_note,
            step=step,
            safety_report=safety_report,
            safe_summary="Script-forging checkpoint decision recorded.",
        )

    def _m6_gate(self, plugin_run_id: str) -> tuple[PluginRun, ScriptForgingRunContext, ScriptAdaptationPromptPackage]:
        run = self._eligible_run(plugin_run_id, require_completed=False)
        context = self._context_for_run(plugin_run_id)
        if context is None:
            raise StorageError(f"SCRIPT_FORGING_CONTEXT_NOT_FOUND:{plugin_run_id}")
        prompt_package = self._prompt_package_for_run(plugin_run_id)
        if prompt_package is None:
            raise StorageError(f"SCRIPT_ADAPTATION_PROMPT_PACKAGE_NOT_FOUND:{plugin_run_id}")
        if prompt_package.package_status != "confirmed":
            raise StorageError(f"SCRIPT_ADAPTATION_PROMPT_PACKAGE_NOT_CONFIRMED:{prompt_package.package_status}")
        script_checkpoint = self._script_checkpoint(
            plugin_run_id,
            "adaptation_prompt_package_confirmation",
            prompt_package.script_adaptation_prompt_package_id,
        )
        plugin_checkpoint = self._plugin_checkpoint(plugin_run_id, script_checkpoint.plugin_checkpoint_id)
        if plugin_checkpoint.checkpoint_status != "confirmed" or not plugin_checkpoint.decision_id:
            raise StorageError("SCRIPT_ADAPTATION_PROMPT_PACKAGE_CHECKPOINT_NOT_CONFIRMED")
        decision = self._checkpoint_decision(plugin_run_id, plugin_checkpoint.decision_id)
        if decision.decision_type != "confirm":
            raise StorageError(f"SCRIPT_ADAPTATION_PROMPT_PACKAGE_DECISION_NOT_CONFIRM:{decision.decision_type}")
        return run, context, prompt_package

    def _m7_gate(
        self,
        plugin_run_id: str,
    ) -> tuple[PluginRun, SceneOutlineArtifact, ScreenplayDraftArtifact, ScreenplaySelfCheckReport, ScreenplayRevisionCandidate | None]:
        run, _context, _prompt_package = self._m6_gate(plugin_run_id)
        outline = self._scene_outline_for_run(plugin_run_id)
        if outline is None:
            raise StorageError(f"SCENE_OUTLINE_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        if outline.outline_status != "confirmed":
            raise StorageError(f"SCENE_OUTLINE_ARTIFACT_NOT_CONFIRMED:{outline.outline_status}")
        draft = self._screenplay_draft_for_run(plugin_run_id)
        if draft is None:
            raise StorageError(f"SCREENPLAY_DRAFT_ARTIFACT_NOT_FOUND:{plugin_run_id}")
        if draft.draft_status != "confirmed":
            raise StorageError(f"SCREENPLAY_DRAFT_ARTIFACT_NOT_CONFIRMED:{draft.draft_status}")
        if draft.scene_outline_id != outline.scene_outline_id:
            raise StorageError(f"SCREENPLAY_DRAFT_OUTLINE_MISMATCH:{draft.scene_outline_id}:{outline.scene_outline_id}")
        report = self._self_check_for_draft(plugin_run_id, draft)
        if report.scene_outline_id != outline.scene_outline_id:
            raise StorageError(f"SCREENPLAY_SELF_CHECK_OUTLINE_MISMATCH:{report.scene_outline_id}:{outline.scene_outline_id}")
        revision_candidate = None
        if report.requires_revision_candidate:
            revision_candidate = self._revision_candidate_for_run(plugin_run_id)
            if revision_candidate is None:
                raise StorageError(f"SCREENPLAY_REVISION_CANDIDATE_REQUIRED_FOR_M7:{plugin_run_id}")
            if revision_candidate.screenplay_draft_id != draft.screenplay_draft_id:
                raise StorageError(f"SCREENPLAY_REVISION_CANDIDATE_DRAFT_MISMATCH:{revision_candidate.screenplay_draft_id}:{draft.screenplay_draft_id}")
            if revision_candidate.self_check_report_id != report.self_check_report_id:
                raise StorageError(f"SCREENPLAY_REVISION_CANDIDATE_SELF_CHECK_MISMATCH:{revision_candidate.self_check_report_id}:{report.self_check_report_id}")
            if not revision_candidate.does_not_overwrite_screenplay_draft:
                raise StorageError(f"SCREENPLAY_REVISION_CANDIDATE_OVERWRITE_FORBIDDEN:{revision_candidate.revision_candidate_id}")
            if revision_candidate.candidate_status == "rejected":
                raise StorageError(f"SCREENPLAY_REVISION_CANDIDATE_REJECTED:{revision_candidate.revision_candidate_id}")
        return run, outline, draft, report, revision_candidate

    def _m7_provenance(
        self,
        outline: SceneOutlineArtifact,
        draft: ScreenplayDraftArtifact,
        report: ScreenplaySelfCheckReport,
        revision_candidate_id: str,
    ) -> dict[str, Any]:
        return {
            "generation_mode": "deterministic_phase7_m7_planning",
            "source_scene_outline_artifact_id": outline.scene_outline_id,
            "source_screenplay_draft_artifact_id": draft.screenplay_draft_id,
            "source_screenplay_self_check_report_id": report.self_check_report_id,
            "source_revision_candidate_id": revision_candidate_id,
            "external_media_provider_called": False,
            "source_story_mutated": False,
        }

    def _assert_storyboard_package_source_binding(
        self,
        storyboard: StoryboardPackage,
        run: PluginRun,
        outline: SceneOutlineArtifact,
        draft: ScreenplayDraftArtifact,
        report: ScreenplaySelfCheckReport,
        revision_candidate: ScreenplayRevisionCandidate | None,
    ) -> None:
        expected_revision_id = revision_candidate.revision_candidate_id if revision_candidate else ""
        expected_values: dict[str, Any] = {
            "plugin_run_id": run.plugin_run_id,
            "project_id": run.project_id,
            "final_story_package_snapshot_id": run.final_story_package_snapshot_id,
            "source_scene_outline_artifact_id": outline.scene_outline_id,
            "source_screenplay_draft_artifact_id": draft.screenplay_draft_id,
            "source_screenplay_self_check_report_id": report.self_check_report_id,
            "source_revision_candidate_id": expected_revision_id,
            "mutates_source_story": False,
            "is_derivative_artifact": True,
        }
        for field_name, expected in expected_values.items():
            actual = getattr(storyboard, field_name)
            if actual != expected:
                raise StorageError(
                    "STORYBOARD_PACKAGE_SOURCE_BINDING_MISMATCH:"
                    f"{storyboard.storyboard_package_id}:{field_name}:{actual}:{expected}"
                )

    def _assert_digital_asset_package_source_binding(
        self,
        digital_asset_package: DigitalAssetPackage,
        run: PluginRun,
        storyboard: StoryboardPackage,
        outline: SceneOutlineArtifact,
        draft: ScreenplayDraftArtifact,
        report: ScreenplaySelfCheckReport,
        revision_candidate: ScreenplayRevisionCandidate | None,
    ) -> None:
        expected_revision_id = revision_candidate.revision_candidate_id if revision_candidate else ""
        expected_values: dict[str, Any] = {
            "plugin_run_id": run.plugin_run_id,
            "project_id": run.project_id,
            "final_story_package_snapshot_id": run.final_story_package_snapshot_id,
            "source_storyboard_package_id": storyboard.storyboard_package_id,
            "source_scene_outline_artifact_id": outline.scene_outline_id,
            "source_screenplay_draft_artifact_id": draft.screenplay_draft_id,
            "source_screenplay_self_check_report_id": report.self_check_report_id,
            "source_revision_candidate_id": expected_revision_id,
            "mutates_source_story": False,
            "is_derivative_artifact": True,
        }
        for field_name, expected in expected_values.items():
            actual = getattr(digital_asset_package, field_name)
            if actual != expected:
                raise StorageError(
                    "DIGITAL_ASSET_PACKAGE_SOURCE_BINDING_MISMATCH:"
                    f"{digital_asset_package.digital_asset_package_id}:{field_name}:{actual}:{expected}"
                )

    def _key_storyboards_for_sources(
        self,
        package_id: str,
        run: PluginRun,
        outline: SceneOutlineArtifact,
        draft: ScreenplayDraftArtifact,
        report: ScreenplaySelfCheckReport,
        revision_id: str,
        now: str,
    ) -> list[KeyStoryboardArtifact]:
        items: list[KeyStoryboardArtifact] = []
        for unit in draft.script_units[:6]:
            source_refs = list(unit.source_ref_ids[:3])
            items.append(
                KeyStoryboardArtifact(
                    key_storyboard_artifact_id=f"{package_id}_key_{unit.scene_number:03d}",
                    plugin_run_id=run.plugin_run_id,
                    source_storyboard_package_id=package_id,
                    source_scene_outline_artifact_id=outline.scene_outline_id,
                    source_screenplay_draft_artifact_id=draft.screenplay_draft_id,
                    source_screenplay_self_check_report_id=report.self_check_report_id,
                    source_revision_candidate_id=revision_id,
                    project_id=run.project_id,
                    final_story_package_snapshot_id=run.final_story_package_snapshot_id,
                    artifact_status="checkpoint_pending",
                    scene_number=unit.scene_number,
                    panel_label=f"Scene {unit.scene_number} key frame",
                    visual_function="establish_source_backed_turning_point",
                    camera_intent="Readable composition plan; no image generation prompt.",
                    composition_summary=f"Frame the source-backed decision beat for scene {unit.scene_number}.",
                    continuity_refs=[unit.script_unit_id],
                    source_ref_ids=source_refs,
                    provenance=self._m7_provenance(outline, draft, report, revision_id),
                    created_at=now,
                    safe_summary=f"Key storyboard frame plan for scene {unit.scene_number}.",
                )
            )
        return items

    def _scene_storyboards_for_sources(
        self,
        package_id: str,
        run: PluginRun,
        outline: SceneOutlineArtifact,
        draft: ScreenplayDraftArtifact,
        report: ScreenplaySelfCheckReport,
        revision_id: str,
        key_storyboards: list[KeyStoryboardArtifact],
        now: str,
    ) -> list[SceneStoryboardArtifact]:
        key_by_scene = {item.scene_number: item for item in key_storyboards}
        items: list[SceneStoryboardArtifact] = []
        for unit in outline.outline_units[:6]:
            key = key_by_scene.get(unit.scene_number)
            items.append(
                SceneStoryboardArtifact(
                    scene_storyboard_artifact_id=f"{package_id}_scene_{unit.scene_number:03d}",
                    plugin_run_id=run.plugin_run_id,
                    source_storyboard_package_id=package_id,
                    source_scene_outline_artifact_id=outline.scene_outline_id,
                    source_screenplay_draft_artifact_id=draft.screenplay_draft_id,
                    source_screenplay_self_check_report_id=report.self_check_report_id,
                    source_revision_candidate_id=revision_id,
                    project_id=run.project_id,
                    final_story_package_snapshot_id=run.final_story_package_snapshot_id,
                    artifact_status="checkpoint_pending",
                    scene_number=unit.scene_number,
                    beat_label=unit.dramatic_function,
                    panel_ids=[key.key_storyboard_artifact_id] if key else [],
                    visual_continuity_notes=[f"Preserve source-backed location hint for scene {unit.scene_number}."],
                    source_ref_ids=list(unit.source_ref_ids[:3]),
                    provenance=self._m7_provenance(outline, draft, report, revision_id),
                    created_at=now,
                    safe_summary=f"Scene storyboard continuity plan for scene {unit.scene_number}.",
                )
            )
        return items

    def _shot_list_for_sources(
        self,
        package_id: str,
        run: PluginRun,
        outline: SceneOutlineArtifact,
        draft: ScreenplayDraftArtifact,
        report: ScreenplaySelfCheckReport,
        revision_id: str,
        key_storyboards: list[KeyStoryboardArtifact],
        now: str,
    ) -> ShotListArtifact:
        shots = [
            {
                "shot_id": f"shot_{item.scene_number:03d}_001",
                "scene_number": item.scene_number,
                "shot_type": "source_backed_key_frame",
                "panel_id": item.key_storyboard_artifact_id,
                "safe_summary": f"Capture key visual decision beat for scene {item.scene_number}.",
                "source_ref_ids": list(item.source_ref_ids[:2]),
            }
            for item in key_storyboards[:8]
        ]
        return ShotListArtifact(
            shot_list_artifact_id=f"{package_id}_shot_list",
            plugin_run_id=run.plugin_run_id,
            source_storyboard_package_id=package_id,
            source_scene_outline_artifact_id=outline.scene_outline_id,
            source_screenplay_draft_artifact_id=draft.screenplay_draft_id,
            source_screenplay_self_check_report_id=report.self_check_report_id,
            source_revision_candidate_id=revision_id,
            project_id=run.project_id,
            final_story_package_snapshot_id=run.final_story_package_snapshot_id,
            artifact_status="checkpoint_pending",
            shots=shots,
            provenance=self._m7_provenance(outline, draft, report, revision_id),
            created_at=now,
            safe_summary=f"Limited shot list with {len(shots)} source-backed shot plans.",
        )

    def _asset_list_record(
        self,
        model_class: Any,
        package_id: str,
        storyboard: StoryboardPackage,
        run: PluginRun,
        outline: SceneOutlineArtifact,
        draft: ScreenplayDraftArtifact,
        report: ScreenplaySelfCheckReport,
        revision_id: str,
        now: str,
        family: str,
    ) -> Any:
        id_field = {
            "character": "character_asset_list_id",
            "location": "location_asset_list_id",
            "prop": "prop_asset_list_id",
            "motif": "motif_asset_list_id",
            "costume_continuity": "costume_continuity_list_id",
        }[family]
        list_id = f"{package_id}_{family}_assets"
        assets = [
            {
                "asset_key": f"{family}_{index + 1:03d}",
                "safe_label": f"{family.replace('_', ' ').title()} planning item {index + 1}",
                "source_binding": draft.script_units[index].script_unit_id if index < len(draft.script_units) else draft.screenplay_draft_id,
                "external_generation_allowed": False,
            }
            for index in range(min(3, max(1, len(draft.script_units))))
        ]
        payload = {
            id_field: list_id,
            "plugin_run_id": run.plugin_run_id,
            "source_digital_asset_package_id": package_id,
            "source_storyboard_package_id": storyboard.storyboard_package_id,
            "source_scene_outline_artifact_id": outline.scene_outline_id,
            "source_screenplay_draft_artifact_id": draft.screenplay_draft_id,
            "source_screenplay_self_check_report_id": report.self_check_report_id,
            "source_revision_candidate_id": revision_id,
            "project_id": run.project_id,
            "final_story_package_snapshot_id": run.final_story_package_snapshot_id,
            "artifact_status": "checkpoint_pending",
            "assets": assets,
            "provenance": self._m7_provenance(outline, draft, report, revision_id),
            "created_at": now,
            "safe_summary": f"{family.replace('_', ' ')} asset list with {len(assets)} bounded planning items.",
        }
        return model_class(**payload)

    def _scene_outline_units(
        self,
        context: ScriptForgingRunContext,
        prompt_package: ScriptAdaptationPromptPackage,
        snapshot: dict[str, Any],
    ) -> list[SceneOutlineUnit]:
        source_refs = list(snapshot.get("source_ref_ids") or [])[:6]
        unit_count = max(2, min(4, context.scene_count or 3))
        functions = ["setup_source_problem", "pressure_and_reversal", "choice_and_consequence", "resolution_pressure"]
        units: list[SceneOutlineUnit] = []
        for index in range(unit_count):
            units.append(
                SceneOutlineUnit(
                    outline_unit_id=f"scene_outline_unit_{index + 1:03d}",
                    scene_number=index + 1,
                    title=f"Source-backed dramatic unit {index + 1}",
                    dramatic_function=functions[index % len(functions)],
                    location_hint="Use a source-supported location cluster.",
                    character_focus_ids=[],
                    preserved_element_refs=list(prompt_package.preserve_instructions[:2]),
                    compression_notes=list(prompt_package.compression_instructions[:2]),
                    source_ref_ids=source_refs[index : index + 2] or source_refs[:2],
                )
            )
        return units

    def _screenplay_script_units(
        self,
        outline: SceneOutlineArtifact,
        prompt_package: ScriptAdaptationPromptPackage,
    ) -> list[ScreenplaySceneScriptUnit]:
        units: list[ScreenplaySceneScriptUnit] = []
        for unit in outline.outline_units:
            units.append(
                ScreenplaySceneScriptUnit(
                    script_unit_id=f"screenplay_unit_{unit.scene_number:03d}",
                    scene_number=unit.scene_number,
                    scene_heading=f"SCENE {unit.scene_number} - SOURCE-BACKED DRAMATIC SPACE",
                    action_lines=[
                        f"Externalize {unit.dramatic_function} through visible choice and pressure.",
                        "Keep the beat traceable to the confirmed final package snapshot.",
                    ],
                    dialogue_blocks=[
                        ScreenplayDialogueBlock(
                            speaker_hint="Lead character",
                            line="We only keep what the source can support.",
                            source_ref_ids=list(unit.source_ref_ids[:2]),
                        )
                    ],
                    transition_hint="Cut on a source-backed consequence.",
                    source_ref_ids=list(unit.source_ref_ids),
                )
            )
        if prompt_package.omission_and_forbidden_instructions:
            units[0].action_lines.append("Do not introduce unverified outcomes or unsupported reveals.")
        return units

    def _coverage_checks(
        self,
        prompt_package: ScriptAdaptationPromptPackage,
        draft: ScreenplayDraftArtifact,
    ) -> list[dict[str, Any]]:
        return [
            {
                "instruction_index": index + 1,
                "status": "covered" if draft.script_units else "missing",
                "safe_summary": instruction[:140],
            }
            for index, instruction in enumerate(prompt_package.preserve_instructions[:4])
        ] or [{"instruction_index": 1, "status": "covered", "safe_summary": "No explicit preserve instruction was available."}]

    def _self_check_for_draft(
        self,
        plugin_run_id: str,
        draft: ScreenplayDraftArtifact,
        *,
        require_revision_candidate: bool = False,
    ) -> ScreenplaySelfCheckReport:
        report = self._self_check_for_run(plugin_run_id)
        if report is None:
            raise StorageError(f"SCREENPLAY_SELF_CHECK_REQUIRED_BEFORE_DRAFT_CONFIRM:{plugin_run_id}")
        if report.screenplay_draft_id != draft.screenplay_draft_id:
            raise StorageError(f"SCREENPLAY_SELF_CHECK_DRAFT_MISMATCH:{report.screenplay_draft_id}:{draft.screenplay_draft_id}")
        if report.report_status == "blocked":
            raise StorageError(f"SCREENPLAY_SELF_CHECK_BLOCKED:{report.self_check_report_id}")
        if require_revision_candidate and not report.requires_revision_candidate:
            raise StorageError(f"SCREENPLAY_REVISION_CANDIDATE_NOT_REQUIRED:{report.self_check_report_id}")
        return report

    def _set_scene_outline_status(self, outline: SceneOutlineArtifact, status: str, now: str) -> SceneOutlineArtifact:
        outline.outline_status = status  # type: ignore[assignment]
        outline.updated_at = now
        self._replace_model(SCENE_OUTLINE_ARTIFACTS_FILE, "scene_outline_id", outline.scene_outline_id, outline)
        artifact = self._output_artifact(outline.plugin_output_artifact_id)
        artifact.artifact_status = "confirmed" if status == "confirmed" else "checkpoint_pending" if status == "checkpoint_pending" else "rejected" if status == "rejected" else "draft"  # type: ignore[assignment]
        artifact.updated_at = now
        self._replace_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, "artifact_id", artifact.artifact_id, artifact)
        return outline

    def _set_screenplay_draft_status(self, draft: ScreenplayDraftArtifact, status: str, now: str) -> ScreenplayDraftArtifact:
        draft.draft_status = status  # type: ignore[assignment]
        draft.updated_at = now
        self._replace_model(SCREENPLAY_DRAFT_ARTIFACTS_FILE, "screenplay_draft_id", draft.screenplay_draft_id, draft)
        artifact = self._output_artifact(draft.plugin_output_artifact_id)
        artifact.artifact_status = "confirmed" if status == "confirmed" else "checkpoint_pending" if status == "checkpoint_pending" else "rejected" if status == "rejected" else "draft"  # type: ignore[assignment]
        artifact.updated_at = now
        self._replace_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, "artifact_id", artifact.artifact_id, artifact)
        return draft

    def _set_storyboard_package_status(self, package: StoryboardPackage, status: str, now: str) -> StoryboardPackage:
        package.package_status = status  # type: ignore[assignment]
        package.updated_at = now
        self._replace_model(STORYBOARD_PACKAGES_FILE, "storyboard_package_id", package.storyboard_package_id, package)
        artifact = self._output_artifact(package.plugin_output_artifact_id)
        artifact.artifact_status = "confirmed" if status == "confirmed" else "checkpoint_pending" if status == "checkpoint_pending" else "rejected" if status == "rejected" else "draft"  # type: ignore[assignment]
        artifact.updated_at = now
        self._replace_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, "artifact_id", artifact.artifact_id, artifact)
        return package

    def _set_digital_asset_package_status(self, package: DigitalAssetPackage, status: str, now: str) -> DigitalAssetPackage:
        package.package_status = status  # type: ignore[assignment]
        package.updated_at = now
        self._replace_model(DIGITAL_ASSET_PACKAGES_FILE, "digital_asset_package_id", package.digital_asset_package_id, package)
        artifact = self._output_artifact(package.plugin_output_artifact_id)
        artifact.artifact_status = "confirmed" if status == "confirmed" else "checkpoint_pending" if status == "checkpoint_pending" else "rejected" if status == "rejected" else "draft"  # type: ignore[assignment]
        artifact.updated_at = now
        self._replace_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, "artifact_id", artifact.artifact_id, artifact)
        return package

    def _scene_outline_response(self, run: PluginRun, outline: SceneOutlineArtifact) -> SceneOutlineArtifactResponse:
        script_checkpoint = self._script_checkpoint(run.plugin_run_id, "scene_outline_confirmation", outline.scene_outline_id)
        plugin_checkpoint = self._plugin_checkpoint(run.plugin_run_id, script_checkpoint.plugin_checkpoint_id)
        artifact = self._output_artifact(outline.plugin_output_artifact_id)
        version = self._output_artifact_version(outline.plugin_output_artifact_id, outline.plugin_output_artifact_version_id)
        step = self._step_for_artifact(run.plugin_run_id, outline.plugin_output_artifact_id)
        return SceneOutlineArtifactResponse(
            scene_outline=outline,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=artifact,
            output_artifact_version=version,
            step=step,
            safety_report=self._latest_safety_report(run),
            safe_summary="Scene outline artifact loaded.",
        )

    def _screenplay_draft_response(self, run: PluginRun, draft: ScreenplayDraftArtifact) -> ScreenplayDraftArtifactResponse:
        script_checkpoint = self._script_checkpoint(run.plugin_run_id, "screenplay_draft_confirmation", draft.screenplay_draft_id)
        plugin_checkpoint = self._plugin_checkpoint(run.plugin_run_id, script_checkpoint.plugin_checkpoint_id)
        artifact = self._output_artifact(draft.plugin_output_artifact_id)
        version = self._output_artifact_version(draft.plugin_output_artifact_id, draft.plugin_output_artifact_version_id)
        step = self._step_for_artifact(run.plugin_run_id, draft.plugin_output_artifact_id)
        return ScreenplayDraftArtifactResponse(
            screenplay_draft=draft,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=artifact,
            output_artifact_version=version,
            step=step,
            safety_report=self._latest_safety_report(run),
            safe_summary="Screenplay draft artifact loaded.",
        )

    def _self_check_response(self, run: PluginRun, report: ScreenplaySelfCheckReport) -> ScreenplaySelfCheckReportResponse:
        artifact = self._output_artifact(report.plugin_output_artifact_id)
        version = self._output_artifact_version(report.plugin_output_artifact_id, report.plugin_output_artifact_version_id)
        step = self._step_for_artifact(run.plugin_run_id, report.plugin_output_artifact_id)
        return ScreenplaySelfCheckReportResponse(
            self_check_report=report,
            plugin_run=run,
            output_artifact=artifact,
            output_artifact_version=version,
            step=step,
            safety_report=self._latest_safety_report(run),
            safe_summary="Screenplay self-check report loaded.",
        )

    def _revision_candidate_response(self, run: PluginRun, candidate: ScreenplayRevisionCandidate) -> ScreenplayRevisionCandidateResponse:
        artifact = self._output_artifact(candidate.plugin_output_artifact_id)
        version = self._output_artifact_version(candidate.plugin_output_artifact_id, candidate.plugin_output_artifact_version_id)
        step = self._step_for_artifact(run.plugin_run_id, candidate.plugin_output_artifact_id)
        return ScreenplayRevisionCandidateResponse(
            revision_candidate=candidate,
            plugin_run=run,
            output_artifact=artifact,
            output_artifact_version=version,
            step=step,
            safety_report=self._latest_safety_report(run),
            safe_summary="Screenplay revision candidate loaded.",
        )

    def _storyboard_package_response(self, run: PluginRun, package: StoryboardPackage) -> StoryboardPackageResponse:
        script_checkpoint = self._script_checkpoint(run.plugin_run_id, "storyboard_package_confirmation", package.storyboard_package_id)
        plugin_checkpoint = self._plugin_checkpoint(run.plugin_run_id, script_checkpoint.plugin_checkpoint_id)
        artifact = self._output_artifact(package.plugin_output_artifact_id)
        version = self._output_artifact_version(package.plugin_output_artifact_id, package.plugin_output_artifact_version_id)
        step = self._step_for_artifact(run.plugin_run_id, package.plugin_output_artifact_id)
        key_storyboards = [
            KeyStoryboardArtifact(**row)
            for row in self._read_list(KEY_STORYBOARD_ARTIFACTS_FILE)
            if row.get("plugin_run_id") == run.plugin_run_id
        ]
        scene_storyboards = [
            SceneStoryboardArtifact(**row)
            for row in self._read_list(SCENE_STORYBOARD_ARTIFACTS_FILE)
            if row.get("plugin_run_id") == run.plugin_run_id
        ]
        shot_list = self._shot_list_for_run(run.plugin_run_id)
        if shot_list is None:
            raise StorageError(f"SHOT_LIST_ARTIFACT_NOT_FOUND:{run.plugin_run_id}")
        return StoryboardPackageResponse(
            storyboard_package=package,
            key_storyboards=key_storyboards,
            scene_storyboards=scene_storyboards,
            shot_list=shot_list,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=artifact,
            output_artifact_version=version,
            step=step,
            safety_report=self._latest_safety_report(run),
            safe_summary="Storyboard package loaded.",
        )

    def _digital_asset_package_response(self, run: PluginRun, package: DigitalAssetPackage) -> DigitalAssetPackageResponse:
        script_checkpoint = self._script_checkpoint(run.plugin_run_id, "digital_asset_package_confirmation", package.digital_asset_package_id)
        plugin_checkpoint = self._plugin_checkpoint(run.plugin_run_id, script_checkpoint.plugin_checkpoint_id)
        artifact = self._output_artifact(package.plugin_output_artifact_id)
        version = self._output_artifact_version(package.plugin_output_artifact_id, package.plugin_output_artifact_version_id)
        step = self._step_for_artifact(run.plugin_run_id, package.plugin_output_artifact_id)
        return DigitalAssetPackageResponse(
            digital_asset_package=package,
            character_asset_list=self._asset_list_for_run(CHARACTER_ASSET_LISTS_FILE, CharacterAssetList, run.plugin_run_id),
            location_asset_list=self._asset_list_for_run(LOCATION_ASSET_LISTS_FILE, LocationAssetList, run.plugin_run_id),
            prop_asset_list=self._asset_list_for_run(PROP_ASSET_LISTS_FILE, PropAssetList, run.plugin_run_id),
            motif_asset_list=self._asset_list_for_run(MOTIF_ASSET_LISTS_FILE, MotifAssetList, run.plugin_run_id),
            costume_continuity_list=self._asset_list_for_run(COSTUME_CONTINUITY_LISTS_FILE, CostumeContinuityList, run.plugin_run_id),
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=artifact,
            output_artifact_version=version,
            step=step,
            safety_report=self._latest_safety_report(run),
            safe_summary="Digital asset package loaded.",
        )

    def _eligible_run(self, plugin_run_id: str, *, require_completed: bool = True) -> PluginRun:
        run = self._load_run(plugin_run_id)
        if run.plugin_id != "script_forging":
            raise StorageError(f"SCRIPT_FORGING_PLUGIN_RUN_REQUIRED:{run.plugin_id}")
        if not run.final_story_package_snapshot_id:
            raise StorageError("SCRIPT_FORGING_SNAPSHOT_REQUIRED")
        if run.reads_only_final_story_package_snapshot is not True or run.mutates_source_story is not False:
            raise StorageError("SCRIPT_FORGING_RUN_BOUNDARY_BLOCKED")
        checkpoint = self._confirmed_input_checkpoint(run)
        if not checkpoint.decision_id:
            raise StorageError("SCRIPT_FORGING_INPUT_CHECKPOINT_DECISION_REQUIRED")
        safety_report = self._latest_safety_report(run)
        if safety_report.passed is not True:
            raise StorageError(f"SCRIPT_FORGING_M4_SAFETY_REPORT_BLOCKED:{safety_report.safety_report_id}")
        if require_completed and run.run_status not in {"completed", "completed_with_warnings", "checkpoint_confirmed"}:
            raise StorageError(f"SCRIPT_FORGING_M4_INPUT_RUN_NOT_CONFIRMED:{run.run_status}")
        snapshot = self._snapshot_for_run(run)
        if snapshot.get("package_type") != "real_project_final_package":
            raise StorageError("SCRIPT_FORGING_FIXTURE_SNAPSHOT_BLOCKED")
        if snapshot.get("not_real_project_final_package") is not False:
            raise StorageError("SCRIPT_FORGING_NON_REAL_SNAPSHOT_BLOCKED")
        if snapshot.get("can_be_used_by_plugins") is not True:
            raise StorageError("SCRIPT_FORGING_SNAPSHOT_NOT_PLUGIN_USABLE")
        return run

    def _confirmed_input_checkpoint(self, run: PluginRun) -> PluginCheckpoint:
        for row in self._read_list(PLUGIN_CHECKPOINTS_FILE):
            if row.get("plugin_run_id") == run.plugin_run_id and row.get("checkpoint_type") == "input_confirmation":
                checkpoint = PluginCheckpoint(**row)
                if checkpoint.checkpoint_status == "confirmed":
                    return checkpoint
        raise StorageError("SCRIPT_FORGING_INPUT_CHECKPOINT_NOT_CONFIRMED")

    def _latest_safety_report(self, run: PluginRun) -> PluginRunSafetyReport:
        if run.safety_report_id:
            for row in self._read_list(PLUGIN_RUN_SAFETY_REPORTS_FILE):
                if row.get("safety_report_id") == run.safety_report_id:
                    return PluginRunSafetyReport(**row)
        rows = [row for row in self._read_list(PLUGIN_RUN_SAFETY_REPORTS_FILE) if row.get("plugin_run_id") == run.plugin_run_id]
        if not rows:
            raise StorageError("SCRIPT_FORGING_M4_SAFETY_REPORT_NOT_FOUND")
        return PluginRunSafetyReport(**rows[-1])

    def _snapshot_for_run(self, run: PluginRun) -> dict[str, Any]:
        snapshot = self._find_record(SNAPSHOTS_FILE, "snapshot_id", run.final_story_package_snapshot_id)
        if snapshot is None:
            raise StorageError(f"SCRIPT_FORGING_SNAPSHOT_NOT_FOUND:{run.final_story_package_snapshot_id}")
        return snapshot

    def _shape_suggestions(self, snapshot: dict[str, Any]) -> list[ScriptForgingShapeSuggestion]:
        source_refs = list(snapshot.get("source_ref_ids") or [])[:8]
        scene_count = len(snapshot.get("chapter_scene_index") or [])
        character_count = len(snapshot.get("character_table") or [])
        key_event_count = len(snapshot.get("key_event_timeline") or [])
        base_preserve = [
            f"Preserve confirmed character motivations for {character_count} tracked characters.",
            f"Preserve {key_event_count} key event beats by source reference rather than adding new canon.",
            "Preserve the declared style and tone as adaptation guidance.",
        ]
        base_compress = [
            f"Compress {scene_count} prose scenes into medium-sized dramatic beats.",
            "Merge repeated exposition into visual or dialogue-efficient moments.",
        ]
        base_forbid = [
            "Do not add unverified events or character outcomes.",
            "Do not copy complete story prose into the script package.",
            "Do not use external screenplay templates as source authority.",
        ]
        return [
            ScriptForgingShapeSuggestion(
                shape_id="shape_focused_feature_arc",
                title="Focused Feature Arc",
                adaptation_form="single feature-length dramatic adaptation",
                target_runtime_band="80-110 minutes",
                structure_strategy="Compress chapters into a central objective, midpoint reversal, and final consequence chain.",
                point_of_view_strategy="Primary protagonist-forward perspective with restrained ensemble cutaways.",
                preserve_elements=base_preserve,
                compress_elements=base_compress,
                omit_or_forbid_elements=base_forbid,
                rationale="Best fit when the source needs a clear central emotional and causal spine.",
                risk_codes=["compression_risk", "secondary_thread_loss"],
                source_ref_ids=source_refs,
            ),
            ScriptForgingShapeSuggestion(
                shape_id="shape_limited_series_pilot",
                title="Limited Series Pilot And Season Spine",
                adaptation_form="pilot plus season-spine package",
                target_runtime_band="pilot 45-60 minutes plus season arc",
                structure_strategy="Use the first act as a pilot hook while preserving later turns as season promises.",
                point_of_view_strategy="Multi-character perspective, anchored by the most source-supported protagonist thread.",
                preserve_elements=base_preserve,
                compress_elements=["Compress backstory into pilot-relevant conflicts.", "Group secondary reveals by episode-scale turns."],
                omit_or_forbid_elements=base_forbid,
                rationale="Best fit when relationship and world-state changes need room without creating new canon.",
                risk_codes=["scope_expansion_risk", "payoff_delay_risk"],
                source_ref_ids=source_refs,
            ),
            ScriptForgingShapeSuggestion(
                shape_id="shape_chamber_tension",
                title="Chamber Tension Adaptation",
                adaptation_form="contained dramatic adaptation",
                target_runtime_band="60-90 minutes",
                structure_strategy="Prioritize a constrained location/goal chain and convert broad events into immediate pressure.",
                point_of_view_strategy="Close subjective perspective with source-backed reveals only.",
                preserve_elements=base_preserve,
                compress_elements=["Compress travel and broad world exposition into dialogue, props, and conflict pressure."],
                omit_or_forbid_elements=base_forbid,
                rationale="Best fit when budget or clarity benefits from fewer locations and higher scene pressure.",
                risk_codes=["world_scale_reduction_risk", "tone_narrowing_risk"],
                source_ref_ids=source_refs,
            ),
        ]

    def _shape_by_id(self, package: ScriptShapePackage, shape_id: str) -> ScriptForgingShapeSuggestion:
        for suggestion in package.suggestions:
            if suggestion.shape_id == shape_id:
                return suggestion
        raise StorageError(f"SCRIPT_FORGING_SELECTED_SHAPE_NOT_FOUND:{shape_id}")

    def _risk_note(
        self,
        run: PluginRun,
        context: ScriptForgingRunContext,
        shape_package: ScriptShapePackage,
        prompt_package: ScriptAdaptationPromptPackage,
        selected_shape: ScriptForgingShapeSuggestion,
        now: str,
    ) -> ScriptForgingSelfRiskNote:
        risks = sorted(set(selected_shape.risk_codes + ["source_fidelity_risk", "prompt_boundary_risk"]))
        return ScriptForgingSelfRiskNote(
            script_forging_risk_note_id=f"script_forging_risk_note_{run.plugin_run_id}",
            plugin_run_id=run.plugin_run_id,
            context_id=context.script_forging_run_context_id,
            script_shape_package_id=shape_package.script_shape_package_id,
            script_adaptation_prompt_package_id=prompt_package.script_adaptation_prompt_package_id,
            risk_codes=risks,
            license_template_risks=["Do not import third-party screenplay templates as source authority."],
            compression_risks=["Some secondary details may be compressed when moving from prose to script direction."],
            source_fidelity_risks=["Every adaptation decision should remain traceable to snapshot ids, hashes, and source refs."],
            medium_mismatch_risks=["Internal prose may need transformation into externalized action, dialogue, or visual beats."],
            prompt_safety_risks=["M6 must treat this package as structured instructions, not provider prompt text."],
            mitigations=[
                "Use source refs and snapshot hash in downstream M6 records.",
                "Require a confirmed prompt package before M6 consumption.",
                "Keep all generated screenplay content out of M5.",
            ],
            created_at=now,
            safe_summary="Risk note records adaptation compression, fidelity, medium, and prompt-boundary risks.",
        )

    def _safety_report(self, plugin_run_id: str, stage: str, now: str) -> PluginRunSafetyReport:
        return self.safety.runtime_safety.build_safety_report(
            plugin_run_id=plugin_run_id,
            safety_report_id=f"{plugin_run_id}_safety_script_forging_{stage}_{self._time_suffix(now)}",
            final_story_package_snapshot_used=True,
            no_final_story_package_mutation=True,
            no_m2_package_record_mutation=True,
            no_m3_static_protocol_record_mutation=True,
            warnings=[],
        )

    def _artifact(
        self,
        *,
        artifact_id: str,
        plugin_run_id: str,
        plugin_id: str,
        project_id: str,
        snapshot_id: str,
        manifest_id: str,
        version_id: str,
        safe_title: str,
        safe_summary: str,
        now: str,
        status: str,
    ) -> PluginOutputArtifact:
        return PluginOutputArtifact(
            artifact_id=artifact_id,
            project_id=project_id,
            plugin_run_id=plugin_run_id,
            plugin_id=plugin_id,
            artifact_type="generic_structured_artifact",
            artifact_status=status,  # type: ignore[arg-type]
            current_version_id=version_id,
            version_ids=[version_id],
            source_package_snapshot_id=snapshot_id,
            source_manifest_id=manifest_id,
            is_derivative_artifact=True,
            mutates_source_story=False,
            safe_title=safe_title,
            safe_summary=safe_summary,
            warnings=[],
            created_at=now,
            updated_at=now,
            version_id=f"{artifact_id}_v1",
        )

    def _artifact_version(
        self,
        *,
        artifact_id: str,
        plugin_run_id: str,
        version_id: str,
        structured_summary: dict[str, Any],
        safe_preview: str,
        step_id: str,
        checkpoint_id: str,
        now: str,
    ) -> PluginOutputArtifactVersion:
        content_hash = hashlib.sha256(json.dumps(structured_summary, sort_keys=True).encode("utf-8")).hexdigest()
        return PluginOutputArtifactVersion(
            artifact_version_id=version_id,
            artifact_id=artifact_id,
            plugin_run_id=plugin_run_id,
            version_number=1,
            content_ref=f"plugin_run:{plugin_run_id}:artifact:{artifact_id}",
            content_hash=content_hash,
            safe_preview=safe_preview,
            structured_summary=structured_summary,
            created_from_step_id=step_id,
            created_after_checkpoint_id=checkpoint_id,
            no_source_story_mutation=True,
            created_at=now,
        )

    def _style_summary(self, style: dict[str, Any]) -> str:
        parts = []
        for key in ["style", "tone", "voice", "pacing"]:
            value = style.get(key)
            if value:
                parts.append(f"{key}:{str(value)[:80]}")
        return "; ".join(parts) or "No explicit style summary recorded."

    def _set_shape_status(self, package: ScriptShapePackage, status: str, now: str) -> ScriptShapePackage:
        package.package_status = status  # type: ignore[assignment]
        package.updated_at = now
        self._replace_model(SCRIPT_SHAPE_PACKAGES_FILE, "script_shape_package_id", package.script_shape_package_id, package)
        artifact = self._output_artifact(package.output_artifact_id)
        artifact.artifact_status = "confirmed" if status == "confirmed" else "checkpoint_pending" if status == "checkpoint_pending" else "rejected" if status == "rejected" else "draft"  # type: ignore[assignment]
        artifact.updated_at = now
        self._replace_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, "artifact_id", artifact.artifact_id, artifact)
        return package

    def _set_prompt_status(self, package: ScriptAdaptationPromptPackage, status: str, now: str) -> ScriptAdaptationPromptPackage:
        package.package_status = status  # type: ignore[assignment]
        package.updated_at = now
        self._replace_model(
            SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE,
            "script_adaptation_prompt_package_id",
            package.script_adaptation_prompt_package_id,
            package,
        )
        artifact = self._output_artifact(package.output_artifact_id)
        artifact.artifact_status = "confirmed" if status == "confirmed" else "checkpoint_pending" if status == "checkpoint_pending" else "rejected" if status == "rejected" else "draft"  # type: ignore[assignment]
        artifact.updated_at = now
        self._replace_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, "artifact_id", artifact.artifact_id, artifact)
        if status == "confirmed":
            risk_note = self._risk_note_for_run(package.plugin_run_id)
            if risk_note:
                self._replace_or_append_model(
                    SCRIPT_FORGING_RISK_NOTES_FILE,
                    "script_forging_risk_note_id",
                    risk_note.script_forging_risk_note_id,
                    risk_note,
                )
        return package

    def _shape_response(self, run: PluginRun, package: ScriptShapePackage) -> ScriptShapePackageResponse:
        script_checkpoint = self._script_checkpoint(run.plugin_run_id, "shape_direction_confirmation", package.script_shape_package_id)
        plugin_checkpoint = self._plugin_checkpoint(run.plugin_run_id, script_checkpoint.plugin_checkpoint_id)
        artifact = self._output_artifact(package.output_artifact_id)
        version = self._output_artifact_version(package.output_artifact_id, package.output_artifact_version_id)
        step = self._step_for_artifact(run.plugin_run_id, package.output_artifact_id)
        return ScriptShapePackageResponse(
            shape_package=package,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=artifact,
            output_artifact_version=version,
            step=step,
            safety_report=self._latest_safety_report(run),
            safe_summary="Script shape package loaded.",
        )

    def _prompt_response(self, run: PluginRun, package: ScriptAdaptationPromptPackage) -> ScriptAdaptationPromptPackageResponse:
        script_checkpoint = self._script_checkpoint(
            run.plugin_run_id,
            "adaptation_prompt_package_confirmation",
            package.script_adaptation_prompt_package_id,
        )
        plugin_checkpoint = self._plugin_checkpoint(run.plugin_run_id, script_checkpoint.plugin_checkpoint_id)
        artifact = self._output_artifact(package.output_artifact_id)
        version = self._output_artifact_version(package.output_artifact_id, package.output_artifact_version_id)
        step = self._step_for_artifact(run.plugin_run_id, package.output_artifact_id)
        risk_note = self._risk_note_for_run(run.plugin_run_id)
        if risk_note is None:
            raise StorageError(f"SCRIPT_FORGING_RISK_NOTE_NOT_FOUND:{run.plugin_run_id}")
        return ScriptAdaptationPromptPackageResponse(
            prompt_package=package,
            plugin_run=run,
            checkpoint=script_checkpoint,
            plugin_checkpoint=plugin_checkpoint,
            output_artifact=artifact,
            output_artifact_version=version,
            step=step,
            risk_note=risk_note,
            safety_report=self._latest_safety_report(run),
            safe_summary="Script adaptation prompt package loaded.",
        )

    def _context_for_run(self, plugin_run_id: str) -> ScriptForgingRunContext | None:
        for row in self._read_list(SCRIPT_FORGING_CONTEXTS_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return ScriptForgingRunContext(**row)
        return None

    def _shape_package_for_run(self, plugin_run_id: str) -> ScriptShapePackage | None:
        for row in self._read_list(SCRIPT_SHAPE_PACKAGES_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return ScriptShapePackage(**row)
        return None

    def _prompt_package_for_run(self, plugin_run_id: str) -> ScriptAdaptationPromptPackage | None:
        for row in self._read_list(SCRIPT_ADAPTATION_PROMPT_PACKAGES_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return ScriptAdaptationPromptPackage(**row)
        return None

    def _scene_outline_for_run(self, plugin_run_id: str) -> SceneOutlineArtifact | None:
        for row in self._read_list(SCENE_OUTLINE_ARTIFACTS_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return SceneOutlineArtifact(**row)
        return None

    def _screenplay_draft_for_run(self, plugin_run_id: str) -> ScreenplayDraftArtifact | None:
        for row in self._read_list(SCREENPLAY_DRAFT_ARTIFACTS_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return ScreenplayDraftArtifact(**row)
        return None

    def _self_check_for_run(self, plugin_run_id: str) -> ScreenplaySelfCheckReport | None:
        for row in self._read_list(SCREENPLAY_SELF_CHECK_REPORTS_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return ScreenplaySelfCheckReport(**row)
        return None

    def _revision_candidate_for_run(self, plugin_run_id: str) -> ScreenplayRevisionCandidate | None:
        for row in self._read_list(SCREENPLAY_REVISION_CANDIDATES_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return ScreenplayRevisionCandidate(**row)
        return None

    def _storyboard_package_for_run(self, plugin_run_id: str) -> StoryboardPackage | None:
        for row in self._read_list(STORYBOARD_PACKAGES_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return StoryboardPackage(**row)
        return None

    def _shot_list_for_run(self, plugin_run_id: str) -> ShotListArtifact | None:
        for row in self._read_list(SHOT_LIST_ARTIFACTS_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return ShotListArtifact(**row)
        return None

    def _digital_asset_package_for_run(self, plugin_run_id: str) -> DigitalAssetPackage | None:
        for row in self._read_list(DIGITAL_ASSET_PACKAGES_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return DigitalAssetPackage(**row)
        return None

    def _asset_list_for_run(self, file_name: str, model_class: Any, plugin_run_id: str) -> Any:
        for row in self._read_list(file_name):
            if row.get("plugin_run_id") == plugin_run_id:
                return model_class(**row)
        raise StorageError(f"SCRIPT_FORGING_ASSET_LIST_NOT_FOUND:{file_name}:{plugin_run_id}")

    def _risk_note_for_run(self, plugin_run_id: str) -> ScriptForgingSelfRiskNote | None:
        for row in self._read_list(SCRIPT_FORGING_RISK_NOTES_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return ScriptForgingSelfRiskNote(**row)
        return None

    def _script_checkpoint(self, plugin_run_id: str, kind: str, domain_artifact_id: str) -> ScriptForgingCheckpoint:
        for row in self._read_list(SCRIPT_FORGING_CHECKPOINTS_FILE):
            if (
                row.get("plugin_run_id") == plugin_run_id
                and row.get("checkpoint_kind") == kind
                and row.get("source_domain_artifact_id") == domain_artifact_id
            ):
                return ScriptForgingCheckpoint(**row)
        raise StorageError(f"SCRIPT_FORGING_CHECKPOINT_NOT_FOUND:{kind}:{domain_artifact_id}")

    def _plugin_checkpoint(self, plugin_run_id: str, checkpoint_id: str) -> PluginCheckpoint:
        for row in self._read_list(PLUGIN_CHECKPOINTS_FILE):
            if row.get("plugin_run_id") == plugin_run_id and row.get("checkpoint_id") == checkpoint_id:
                return PluginCheckpoint(**row)
        raise StorageError(f"PLUGIN_CHECKPOINT_NOT_FOUND:{checkpoint_id}")

    def _checkpoint_decision(self, plugin_run_id: str, decision_id: str) -> PluginCheckpointDecision:
        for row in self._read_list(PLUGIN_CHECKPOINT_DECISIONS_FILE):
            if row.get("plugin_run_id") == plugin_run_id and row.get("checkpoint_decision_id") == decision_id:
                return PluginCheckpointDecision(**row)
        raise StorageError(f"PLUGIN_CHECKPOINT_DECISION_NOT_FOUND:{decision_id}")

    def _output_artifact(self, artifact_id: str) -> PluginOutputArtifact:
        for row in self._read_list(PLUGIN_OUTPUT_ARTIFACTS_FILE):
            if row.get("artifact_id") == artifact_id:
                return PluginOutputArtifact(**row)
        raise StorageError(f"PLUGIN_OUTPUT_ARTIFACT_NOT_FOUND:{artifact_id}")

    def _output_artifact_version(self, artifact_id: str, artifact_version_id: str) -> PluginOutputArtifactVersion:
        for row in self._read_list(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE):
            if row.get("artifact_id") == artifact_id and row.get("artifact_version_id") == artifact_version_id:
                return PluginOutputArtifactVersion(**row)
        raise StorageError(f"PLUGIN_OUTPUT_ARTIFACT_VERSION_NOT_FOUND:{artifact_version_id}")

    def _step_for_artifact(self, plugin_run_id: str, artifact_id: str) -> PluginRunStep:
        for row in self._read_list(PLUGIN_RUN_STEPS_FILE):
            if row.get("plugin_run_id") == plugin_run_id and row.get("output_artifact_id") == artifact_id:
                return PluginRunStep(**row)
        raise StorageError(f"PLUGIN_RUN_ARTIFACT_STEP_NOT_FOUND:{artifact_id}")

    def _load_run(self, plugin_run_id: str) -> PluginRun:
        for row in self._read_list(PLUGIN_RUNS_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return PluginRun(**row)
        raise StorageError(f"PLUGIN_RUN_NOT_FOUND:{plugin_run_id}")

    def _find_record(self, file_name: str, id_field: str, expected_id: str) -> dict[str, Any] | None:
        if not expected_id:
            return None
        for row in self._read_list(file_name):
            if isinstance(row, dict) and row.get(id_field) == expected_id:
                return row
        return None

    def _append_model(self, file_name: str, model: Any) -> None:
        rows = self._read_list(file_name)
        rows.append(model_to_dict(model))
        self._write_list(file_name, rows)

    def _replace_model(self, file_name: str, id_field: str, expected_id: str, model: Any) -> None:
        rows = self._read_list(file_name)
        for index, row in enumerate(rows):
            if isinstance(row, dict) and row.get(id_field) == expected_id:
                rows[index] = model_to_dict(model)
                self._write_list(file_name, rows)
                return
        raise StorageError(f"SCRIPT_FORGING_STORAGE_RECORD_NOT_FOUND:{file_name}:{expected_id}")

    def _replace_or_append_model(self, file_name: str, id_field: str, expected_id: str, model: Any) -> None:
        rows = self._read_list(file_name)
        for index, row in enumerate(rows):
            if isinstance(row, dict) and row.get(id_field) == expected_id:
                rows[index] = model_to_dict(model)
                self._write_list(file_name, rows)
                return
        rows.append(model_to_dict(model))
        self._write_list(file_name, rows)

    def _read_list(self, file_name: str) -> list[dict[str, Any]]:
        path = self.data_dir / file_name
        if not path.exists():
            return []
        data = self.store.read_any(path)
        if not isinstance(data, list):
            raise StorageError(f"SCRIPT_FORGING_STORAGE_NOT_LIST:{file_name}")
        return data

    def _write_list(self, file_name: str, rows: list[dict[str, Any]]) -> None:
        self.safety.assert_safe_record_payload(rows, context=file_name)
        self.store.write(self.data_dir / file_name, rows)

    def _assert_safe_write(self, payload: Any, context: str, full_story_text: str) -> None:
        safe_payload = model_to_dict(payload) if hasattr(payload, "dict") or hasattr(payload, "model_dump") else payload
        self.safety.assert_safe_record_payload(safe_payload, context=context, full_story_text=full_story_text)

    def _append_unique(self, values: list[str], item: str) -> None:
        if item not in values:
            values.append(item)

    def _time_suffix(self, value: str) -> str:
        return value.replace("-", "").replace(":", "").replace(".", "").replace("+", "_")
