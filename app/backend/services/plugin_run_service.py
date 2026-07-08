from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..models.plugin_protocol import PluginInputValidationRequest
from ..models.plugin_runtime import (
    PluginCheckpoint,
    PluginCheckpointDecision,
    PluginCheckpointDecisionRequest,
    PluginCheckpointDecisionResponse,
    PluginCheckpointListResponse,
    PluginOutputArtifact,
    PluginOutputArtifactListResponse,
    PluginOutputArtifactVersion,
    PluginOutputArtifactVersionListResponse,
    PluginRun,
    PluginRunCancelRequest,
    PluginRunCreateRequest,
    PluginRunCreateResponse,
    PluginRunSafetyReport,
    PluginRunStep,
    PluginRunStepListResponse,
    PluginRunListResponse,
)
from ..storage.json_store import JsonStore, StorageError
from .plugin_input_validation_service import SNAPSHOTS_FILE, PluginInputValidationService
from .plugin_manifest_service import PluginManifestService, model_to_dict, now_iso, sanitize_user_note
from .plugin_run_safety_service import (
    GUARDED_NO_MUTATION_FILES,
    PLUGIN_CHECKPOINT_DECISIONS_FILE,
    PLUGIN_CHECKPOINTS_FILE,
    PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE,
    PLUGIN_OUTPUT_ARTIFACTS_FILE,
    PLUGIN_RUN_ERRORS_FILE,
    PLUGIN_RUN_SAFETY_REPORTS_FILE,
    PLUGIN_RUN_STEPS_FILE,
    PLUGIN_RUNS_FILE,
    PluginRunSafetyService,
)


class PluginRunService:
    """Phase 7 M4 generic plugin run/checkpoint/output-artifact runtime."""

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.manifest_service = PluginManifestService(
            store=self.store,
            data_dir=self.data_dir,
            read_only_static=True,
        )
        self.validation_service = PluginInputValidationService(
            store=self.store,
            data_dir=self.data_dir,
            read_only_static=True,
        )
        self.safety_service = PluginRunSafetyService(store=self.store, data_dir=self.data_dir)

    def create_run(self, plugin_id: str, request: PluginRunCreateRequest) -> PluginRunCreateResponse:
        self.safety_service.assert_safe_request_payload(model_to_dict(request), context="plugin_run_create_request")
        snapshot_id = request.snapshot_id.strip()
        if not snapshot_id:
            raise StorageError("PLUGIN_RUN_SNAPSHOT_REQUIRED")
        safe_user_note = sanitize_user_note(request.safe_user_note)

        guarded_before = self.safety_service.selected_hashes(GUARDED_NO_MUTATION_FILES)
        self.manifest_service.assert_static_records_ready()
        self.safety_service.assert_hashes_unchanged(guarded_before, context="plugin_run_static_preflight")
        preflight_report = self.validation_service.validate_input(
            plugin_id,
            PluginInputValidationRequest(
                snapshot_id=snapshot_id,
                persist_validation_report=False,
                safe_user_note=safe_user_note,
            ),
        )
        self._require_valid_future_runtime(preflight_report)
        snapshot = self._find_record(SNAPSHOTS_FILE, "snapshot_id", snapshot_id)
        if snapshot is None:
            raise StorageError(f"PLUGIN_RUN_SNAPSHOT_NOT_FOUND:{snapshot_id}")
        self._assert_snapshot_still_bound(preflight_report, snapshot)
        full_story_text = str(snapshot.get("complete_story_text") or "")

        self.safety_service.assert_no_forbidden_business_files()
        validation_report = self.validation_service.validate_input(
            plugin_id,
            PluginInputValidationRequest(
                snapshot_id=snapshot_id,
                persist_validation_report=True,
                safe_user_note=safe_user_note,
            ),
        )
        self._require_valid_future_runtime(validation_report)

        manifest = self.manifest_service.get_manifest(plugin_id)
        input_schema = self.manifest_service.get_input_schema(plugin_id)
        risk = self.manifest_service.get_risk_declaration(plugin_id)
        version = self.manifest_service.get_version_record(plugin_id)
        created_at = now_iso()
        plugin_run_id = self._id("plugin_run", plugin_id, snapshot_id, created_at)
        input_step_id = f"{plugin_run_id}_step_input"
        checkpoint_step_id = f"{plugin_run_id}_step_checkpoint"
        safety_step_id = f"{plugin_run_id}_step_safety_initial"
        checkpoint_id = f"{plugin_run_id}_checkpoint_input"
        safety_report_id = f"{plugin_run_id}_safety_initial"
        final_story_package_id = str(snapshot.get("final_story_package_id") or "")

        steps = [
            PluginRunStep(
                step_id=input_step_id,
                plugin_run_id=plugin_run_id,
                step_type="input_binding",
                step_status="completed",
                input_refs=[snapshot_id, validation_report.input_validation_report_id],
                output_refs=[checkpoint_id],
                safe_summary="Bound a validated FinalStoryPackageSnapshot as read-only plugin input.",
                warnings=[],
                created_at=created_at,
                updated_at=created_at,
            ),
            PluginRunStep(
                step_id=checkpoint_step_id,
                plugin_run_id=plugin_run_id,
                step_type="checkpoint",
                step_status="waiting_for_checkpoint",
                input_refs=[input_step_id],
                output_refs=[checkpoint_id],
                checkpoint_id=checkpoint_id,
                safe_summary="Waiting for a plugin-step-only input confirmation checkpoint.",
                warnings=[],
                created_at=created_at,
                updated_at=created_at,
            ),
            PluginRunStep(
                step_id=safety_step_id,
                plugin_run_id=plugin_run_id,
                step_type="safety_check",
                step_status="completed",
                input_refs=[snapshot_id],
                output_refs=[safety_report_id],
                safe_summary="Initial runtime boundary check completed without source-story mutation.",
                warnings=[],
                created_at=created_at,
                updated_at=created_at,
            ),
        ]
        checkpoint = PluginCheckpoint(
            checkpoint_id=checkpoint_id,
            plugin_run_id=plugin_run_id,
            step_id=checkpoint_step_id,
            checkpoint_type="input_confirmation",
            checkpoint_status="pending",
            checkpoint_prompt=(
                "Confirm this plugin runtime may proceed using only the validated FinalStoryPackageSnapshot."
            ),
            user_visible_summary=(
                "This checkpoint confirms plugin runtime input only. It does not modify the final package or source story."
            ),
            source_artifact_ids=[],
            created_at=created_at,
            updated_at=created_at,
        )
        safety_report = self.safety_service.build_safety_report(
            plugin_run_id=plugin_run_id,
            safety_report_id=safety_report_id,
            final_story_package_snapshot_used=True,
            no_final_story_package_mutation=True,
            no_m2_package_record_mutation=True,
            no_m3_static_protocol_record_mutation=True,
            warnings=[],
        )
        run = PluginRun(
            plugin_run_id=plugin_run_id,
            project_id=validation_report.project_id,
            plugin_id=plugin_id,
            manifest_id=manifest.manifest_id,
            input_schema_id=input_schema.input_schema_id,
            risk_declaration_id=risk.risk_declaration_id,
            version_record_id=version.version_record_id,
            plugin_protocol_version=version.plugin_protocol_version,
            plugin_version=version.plugin_semver,
            final_story_package_id=final_story_package_id,
            final_story_package_snapshot_id=snapshot_id,
            input_validation_report_id=validation_report.input_validation_report_id,
            run_status="waiting_for_checkpoint",
            current_step_id=checkpoint_step_id,
            step_ids=[step.step_id for step in steps],
            checkpoint_ids=[checkpoint_id],
            output_artifact_ids=[],
            safety_report_id=safety_report_id,
            reads_only_final_story_package_snapshot=True,
            mutates_source_story=False,
            safe_user_note=safe_user_note,
            safe_summary="Created generic M4 plugin run from a validated M2 FinalStoryPackageSnapshot.",
            warnings=[],
            created_at=created_at,
            updated_at=created_at,
            version_id=f"{plugin_run_id}_v1",
        )
        payload = {
            "run": model_to_dict(run),
            "steps": [model_to_dict(step) for step in steps],
            "checkpoint": model_to_dict(checkpoint),
            "safety_report": model_to_dict(safety_report),
        }
        self.safety_service.assert_safe_runtime_payload(payload, context="plugin_run_create_payload", full_story_text=full_story_text)
        self._append_model(PLUGIN_RUNS_FILE, run)
        for step in steps:
            self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        self._append_model(PLUGIN_CHECKPOINTS_FILE, checkpoint)
        self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety_service.assert_hashes_unchanged(guarded_before, context="plugin_run_create")
        self.safety_service.assert_no_forbidden_business_files()
        return PluginRunCreateResponse(
            plugin_run=run,
            input_validation_report=validation_report,
            steps=steps,
            checkpoints=[checkpoint],
            safety_report=safety_report,
            safe_summary="Plugin run created and paused at an input confirmation checkpoint.",
        )

    def get_run(self, plugin_run_id: str) -> PluginRun:
        return self._load_run(plugin_run_id)

    def list_runs(self) -> PluginRunListResponse:
        runs = [PluginRun(**row) for row in self._read_list(PLUGIN_RUNS_FILE)]
        runs.sort(key=lambda item: item.created_at, reverse=True)
        return PluginRunListResponse(
            plugin_runs=runs,
            total_count=len(runs),
            safe_summary="M4 plugin runs are runtime audit records and do not mutate source story facts.",
        )

    def cancel_run(self, plugin_run_id: str, request: PluginRunCancelRequest) -> PluginRun:
        self.safety_service.assert_safe_request_payload(model_to_dict(request), context="plugin_run_cancel_request")
        run = self._load_run(plugin_run_id)
        if run.run_status in {"completed", "completed_with_warnings", "cancelled", "blocked", "failed"}:
            raise StorageError(f"PLUGIN_RUN_TERMINAL_STATE_BLOCKED:{plugin_run_id}:{run.run_status}")
        safe_note = sanitize_user_note(request.safe_user_note)
        now = now_iso()
        guarded_before = self.safety_service.selected_hashes(GUARDED_NO_MUTATION_FILES)
        cancellation_step = PluginRunStep(
            step_id=f"{plugin_run_id}_step_cancel_{self._time_suffix(now)}",
            plugin_run_id=plugin_run_id,
            step_type="cancellation",
            step_status="completed",
            input_refs=[run.current_step_id],
            output_refs=[],
            safe_summary="Plugin run cancelled by user; no source story or final package record was modified.",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        run.run_status = "cancelled"
        run.current_step_id = cancellation_step.step_id
        run.step_ids.append(cancellation_step.step_id)
        run.safe_user_note = safe_note
        run.updated_at = now
        self.safety_service.assert_safe_runtime_payload(
            {"run": model_to_dict(run), "step": model_to_dict(cancellation_step)},
            context="plugin_run_cancel_payload",
            full_story_text=self._full_story_text_for_run(run),
        )
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._append_model(PLUGIN_RUN_STEPS_FILE, cancellation_step)
        self.safety_service.assert_hashes_unchanged(guarded_before, context="plugin_run_cancel")
        return run

    def list_steps(self, plugin_run_id: str) -> PluginRunStepListResponse:
        self._load_run(plugin_run_id)
        steps = [PluginRunStep(**row) for row in self._read_list(PLUGIN_RUN_STEPS_FILE) if row.get("plugin_run_id") == plugin_run_id]
        return PluginRunStepListResponse(plugin_run_id=plugin_run_id, steps=steps, total_count=len(steps))

    def list_checkpoints(self, plugin_run_id: str) -> PluginCheckpointListResponse:
        self._load_run(plugin_run_id)
        checkpoints = [
            PluginCheckpoint(**row)
            for row in self._read_list(PLUGIN_CHECKPOINTS_FILE)
            if row.get("plugin_run_id") == plugin_run_id
        ]
        return PluginCheckpointListResponse(
            plugin_run_id=plugin_run_id,
            checkpoints=checkpoints,
            total_count=len(checkpoints),
        )

    def list_artifacts(self, plugin_run_id: str) -> PluginOutputArtifactListResponse:
        self._load_run(plugin_run_id)
        artifacts = [
            PluginOutputArtifact(**row)
            for row in self._read_list(PLUGIN_OUTPUT_ARTIFACTS_FILE)
            if row.get("plugin_run_id") == plugin_run_id
        ]
        return PluginOutputArtifactListResponse(
            plugin_run_id=plugin_run_id,
            artifacts=artifacts,
            total_count=len(artifacts),
            safe_summary="Output artifacts are derivative M4 runtime records with separate versions.",
        )

    def get_safety_report(self, plugin_run_id: str) -> PluginRunSafetyReport:
        run = self._load_run(plugin_run_id)
        for row in self._read_list(PLUGIN_RUN_SAFETY_REPORTS_FILE):
            if row.get("safety_report_id") == run.safety_report_id:
                return PluginRunSafetyReport(**row)
        raise StorageError(f"PLUGIN_RUN_SAFETY_REPORT_NOT_FOUND:{run.safety_report_id}")

    def submit_checkpoint_decision(
        self,
        plugin_run_id: str,
        checkpoint_id: str,
        decision_type: str,
        request: PluginCheckpointDecisionRequest,
    ) -> PluginCheckpointDecisionResponse:
        if decision_type not in {"confirm", "request_revision", "reject", "defer", "cancel_run"}:
            raise StorageError(f"PLUGIN_CHECKPOINT_DECISION_NOT_ALLOWED:{decision_type}")
        self.safety_service.assert_safe_request_payload(
            {"decision_type": decision_type, **model_to_dict(request)},
            context="plugin_checkpoint_decision_request",
        )
        run = self._load_run(plugin_run_id)
        checkpoint = self._load_checkpoint(plugin_run_id, checkpoint_id)
        if checkpoint.checkpoint_status != "pending":
            raise StorageError(f"PLUGIN_CHECKPOINT_NOT_PENDING:{checkpoint_id}:{checkpoint.checkpoint_status}")
        if run.run_status not in {"waiting_for_checkpoint", "input_validated", "created"}:
            raise StorageError(f"PLUGIN_RUN_NOT_WAITING_FOR_CHECKPOINT:{plugin_run_id}:{run.run_status}")

        full_story_text = self._full_story_text_for_run(run)
        now = now_iso()
        safe_note = sanitize_user_note(request.safe_user_note)
        requested_changes = [sanitize_user_note(item, max_length=180) for item in request.requested_changes]
        guarded_before = self.safety_service.selected_hashes(GUARDED_NO_MUTATION_FILES)
        decision = PluginCheckpointDecision(
            checkpoint_decision_id=f"{checkpoint_id}_decision_{decision_type}_{self._time_suffix(now)}",
            plugin_run_id=plugin_run_id,
            checkpoint_id=checkpoint_id,
            decision_type=decision_type,  # type: ignore[arg-type]
            user_note=safe_note,
            requested_changes=requested_changes,
            decision_scope="plugin_step_only",
            does_not_modify_final_story_package=True,
            does_not_modify_source_story=True,
            created_at=now,
            version_id=f"{checkpoint_id}_decision_{self._time_suffix(now)}_v1",
        )
        output_artifact: PluginOutputArtifact | None = None
        output_version: PluginOutputArtifactVersion | None = None
        safety_report: PluginRunSafetyReport | None = None
        new_steps: list[PluginRunStep] = []

        if decision_type == "confirm":
            checkpoint.checkpoint_status = "confirmed"
            checkpoint.decision_id = decision.checkpoint_decision_id
            checkpoint.updated_at = now
            run.run_status = "completed"
            run.updated_at = now
            artifact_step_id = f"{plugin_run_id}_step_artifact_{self._time_suffix(now)}"
            safety_step_id = f"{plugin_run_id}_step_safety_confirm_{self._time_suffix(now)}"
            completion_step_id = f"{plugin_run_id}_step_completion_{self._time_suffix(now)}"
            artifact_id = f"{plugin_run_id}_artifact_runtime_test"
            artifact_version_id = f"{artifact_id}_version_001"
            content_payload = self._artifact_content_payload(run, decision)
            content_hash = hashlib.sha256(json.dumps(content_payload, sort_keys=True).encode("utf-8")).hexdigest()
            output_version = PluginOutputArtifactVersion(
                artifact_version_id=artifact_version_id,
                artifact_id=artifact_id,
                plugin_run_id=plugin_run_id,
                version_number=1,
                content_ref=f"plugin_run:{plugin_run_id}:artifact:{artifact_id}:snapshot:{run.final_story_package_snapshot_id}",
                content_hash=content_hash,
                safe_preview=(
                    "Runtime test artifact derived from snapshot hash "
                    f"{content_payload['complete_story_text_hash'][:12]} and {content_payload['source_ref_count']} source refs."
                ),
                structured_summary=content_payload,
                created_from_step_id=artifact_step_id,
                created_after_checkpoint_id=checkpoint_id,
                no_source_story_mutation=True,
                created_at=now,
            )
            output_artifact = PluginOutputArtifact(
                artifact_id=artifact_id,
                project_id=run.project_id,
                plugin_run_id=plugin_run_id,
                plugin_id=run.plugin_id,
                artifact_type="runtime_test_artifact",
                artifact_status="confirmed",
                current_version_id=artifact_version_id,
                version_ids=[artifact_version_id],
                source_package_snapshot_id=run.final_story_package_snapshot_id,
                source_manifest_id=run.manifest_id,
                is_derivative_artifact=True,
                mutates_source_story=False,
                safe_title="M4 Runtime Test Artifact",
                safe_summary=(
                    "Generic derivative artifact proving checkpoint and version storage; it contains only ids, hashes, and counts."
                ),
                warnings=[],
                created_at=now,
                updated_at=now,
                version_id=f"{artifact_id}_v1",
            )
            safety_report = self.safety_service.build_safety_report(
                plugin_run_id=plugin_run_id,
                safety_report_id=f"{plugin_run_id}_safety_confirm_{self._time_suffix(now)}",
                final_story_package_snapshot_used=True,
                no_final_story_package_mutation=True,
                no_m2_package_record_mutation=True,
                no_m3_static_protocol_record_mutation=True,
                warnings=[],
            )
            run.current_step_id = completion_step_id
            run.step_ids.extend([artifact_step_id, safety_step_id, completion_step_id])
            run.output_artifact_ids.append(artifact_id)
            run.safety_report_id = safety_report.safety_report_id
            new_steps = [
                PluginRunStep(
                    step_id=artifact_step_id,
                    plugin_run_id=plugin_run_id,
                    step_type="artifact_creation",
                    step_status="completed",
                    input_refs=[checkpoint_id, decision.checkpoint_decision_id],
                    output_refs=[artifact_id, artifact_version_id],
                    output_artifact_id=artifact_id,
                    safe_summary="Created a generic derivative runtime test artifact with separate version storage.",
                    warnings=[],
                    created_at=now,
                    updated_at=now,
                ),
                PluginRunStep(
                    step_id=safety_step_id,
                    plugin_run_id=plugin_run_id,
                    step_type="safety_check",
                    step_status="completed",
                    input_refs=[artifact_id, artifact_version_id],
                    output_refs=[safety_report.safety_report_id],
                    safe_summary="Confirmed artifact boundary check completed without source-story mutation.",
                    warnings=[],
                    created_at=now,
                    updated_at=now,
                ),
                PluginRunStep(
                    step_id=completion_step_id,
                    plugin_run_id=plugin_run_id,
                    step_type="completion",
                    step_status="completed",
                    input_refs=[artifact_id, safety_report.safety_report_id],
                    output_refs=[],
                    safe_summary="Plugin run completed after checkpoint confirmation and derivative artifact versioning.",
                    warnings=[],
                    created_at=now,
                    updated_at=now,
                ),
            ]
        else:
            status_map = {
                "request_revision": ("revision_requested", "blocked"),
                "reject": ("rejected", "blocked"),
                "defer": ("deferred", "blocked"),
                "cancel_run": ("cancelled", "cancelled"),
            }
            checkpoint_status, run_status = status_map[decision_type]
            checkpoint.checkpoint_status = checkpoint_status  # type: ignore[assignment]
            checkpoint.decision_id = decision.checkpoint_decision_id
            checkpoint.updated_at = now
            run.run_status = run_status  # type: ignore[assignment]
            run.updated_at = now
            step_type = "cancellation" if decision_type == "cancel_run" else "checkpoint"
            step_id = f"{plugin_run_id}_step_{decision_type}_{self._time_suffix(now)}"
            run.current_step_id = step_id
            run.step_ids.append(step_id)
            new_steps = [
                PluginRunStep(
                    step_id=step_id,
                    plugin_run_id=plugin_run_id,
                    step_type=step_type,  # type: ignore[arg-type]
                    step_status="completed",
                    input_refs=[checkpoint_id, decision.checkpoint_decision_id],
                    output_refs=[],
                    checkpoint_id=checkpoint_id,
                    safe_summary="Checkpoint decision recorded as plugin-step-only runtime audit evidence.",
                    warnings=[],
                    created_at=now,
                    updated_at=now,
                )
            ]

        payload = {
            "run": model_to_dict(run),
            "checkpoint": model_to_dict(checkpoint),
            "decision": model_to_dict(decision),
            "steps": [model_to_dict(step) for step in new_steps],
            "output_artifact": model_to_dict(output_artifact) if output_artifact else None,
            "output_version": model_to_dict(output_version) if output_version else None,
            "safety_report": model_to_dict(safety_report) if safety_report else None,
        }
        self.safety_service.assert_safe_runtime_payload(payload, context="plugin_checkpoint_decision_payload", full_story_text=full_story_text)
        self._replace_model(PLUGIN_RUNS_FILE, "plugin_run_id", run.plugin_run_id, run)
        self._replace_model(PLUGIN_CHECKPOINTS_FILE, "checkpoint_id", checkpoint.checkpoint_id, checkpoint)
        self._append_model(PLUGIN_CHECKPOINT_DECISIONS_FILE, decision)
        for step in new_steps:
            self._append_model(PLUGIN_RUN_STEPS_FILE, step)
        if output_artifact and output_version:
            self._append_model(PLUGIN_OUTPUT_ARTIFACTS_FILE, output_artifact)
            self._append_model(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, output_version)
        if safety_report:
            self._append_model(PLUGIN_RUN_SAFETY_REPORTS_FILE, safety_report)
        self.safety_service.assert_hashes_unchanged(guarded_before, context="plugin_checkpoint_decision")
        self.safety_service.assert_no_forbidden_business_files()
        return PluginCheckpointDecisionResponse(
            plugin_run=run,
            checkpoint=checkpoint,
            decision=decision,
            output_artifact=output_artifact,
            output_artifact_version=output_version,
            safety_report=safety_report,
            safe_summary="Checkpoint decision recorded as plugin-step-only evidence.",
        )

    def get_artifact(self, artifact_id: str) -> PluginOutputArtifact:
        for row in self._read_list(PLUGIN_OUTPUT_ARTIFACTS_FILE):
            if row.get("artifact_id") == artifact_id:
                return PluginOutputArtifact(**row)
        raise StorageError(f"PLUGIN_OUTPUT_ARTIFACT_NOT_FOUND:{artifact_id}")

    def list_artifact_versions(self, artifact_id: str) -> PluginOutputArtifactVersionListResponse:
        self.get_artifact(artifact_id)
        versions = [
            PluginOutputArtifactVersion(**row)
            for row in self._read_list(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE)
            if row.get("artifact_id") == artifact_id
        ]
        versions.sort(key=lambda item: item.version_number)
        return PluginOutputArtifactVersionListResponse(
            artifact_id=artifact_id,
            versions=versions,
            total_count=len(versions),
        )

    def get_artifact_version(self, artifact_id: str, artifact_version_id: str) -> PluginOutputArtifactVersion:
        self.get_artifact(artifact_id)
        for row in self._read_list(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE):
            if row.get("artifact_id") == artifact_id and row.get("artifact_version_id") == artifact_version_id:
                return PluginOutputArtifactVersion(**row)
        raise StorageError(f"PLUGIN_OUTPUT_ARTIFACT_VERSION_NOT_FOUND:{artifact_version_id}")

    def _require_valid_future_runtime(self, report: Any) -> None:
        if report.input_valid is not True:
            raise StorageError(f"PLUGIN_RUN_INPUT_VALIDATION_FAILED:{','.join(report.blocked_reason_codes)}")
        if report.validation_status != "valid_for_future_runtime":
            raise StorageError(f"PLUGIN_RUN_VALIDATION_STATUS_BLOCKED:{report.validation_status}")
        if report.can_create_plugin_run_later is not True:
            raise StorageError("PLUGIN_RUN_FUTURE_RUNTIME_ELIGIBILITY_BLOCKED")
        if report.can_create_plugin_run_now is not False or report.plugin_runtime_available is not False:
            raise StorageError("PLUGIN_RUN_M3_RUNTIME_FLAG_MUST_REMAIN_FALSE")

    def _assert_snapshot_still_bound(self, report: Any, snapshot: dict[str, Any]) -> None:
        if report.snapshot_id != snapshot.get("snapshot_id"):
            raise StorageError("PLUGIN_RUN_SNAPSHOT_BINDING_MISMATCH")
        if report.complete_story_text_hash != snapshot.get("complete_story_text_hash"):
            raise StorageError("PLUGIN_RUN_SNAPSHOT_HASH_MISMATCH")
        if int(report.complete_story_text_char_count or 0) != int(snapshot.get("complete_story_text_char_count") or 0):
            raise StorageError("PLUGIN_RUN_SNAPSHOT_CHAR_COUNT_MISMATCH")
        if report.can_be_used_by_plugins is not True or snapshot.get("can_be_used_by_plugins") is not True:
            raise StorageError("PLUGIN_RUN_SNAPSHOT_NOT_PLUGIN_USABLE")
        if report.not_real_project_final_package is not False or snapshot.get("not_real_project_final_package") is not False:
            raise StorageError("PLUGIN_RUN_FIXTURE_SNAPSHOT_BLOCKED")

    def _artifact_content_payload(self, run: PluginRun, decision: PluginCheckpointDecision) -> dict[str, Any]:
        snapshot = self._find_record(SNAPSHOTS_FILE, "snapshot_id", run.final_story_package_snapshot_id) or {}
        return {
            "artifact_contract": "phase7_m4_runtime_test_artifact_v1",
            "plugin_run_id": run.plugin_run_id,
            "plugin_id": run.plugin_id,
            "snapshot_id": run.final_story_package_snapshot_id,
            "input_validation_report_id": run.input_validation_report_id,
            "checkpoint_decision_id": decision.checkpoint_decision_id,
            "complete_story_text_hash": str(snapshot.get("complete_story_text_hash") or ""),
            "complete_story_text_char_count": int(snapshot.get("complete_story_text_char_count") or 0),
            "source_ref_count": len(snapshot.get("source_ref_ids") or []),
            "mutates_source_story": False,
            "is_derivative_artifact": True,
        }

    def _full_story_text_for_run(self, run: PluginRun) -> str:
        snapshot = self._find_record(SNAPSHOTS_FILE, "snapshot_id", run.final_story_package_snapshot_id) or {}
        return str(snapshot.get("complete_story_text") or "")

    def _load_run(self, plugin_run_id: str) -> PluginRun:
        for row in self._read_list(PLUGIN_RUNS_FILE):
            if row.get("plugin_run_id") == plugin_run_id:
                return PluginRun(**row)
        raise StorageError(f"PLUGIN_RUN_NOT_FOUND:{plugin_run_id}")

    def _load_checkpoint(self, plugin_run_id: str, checkpoint_id: str) -> PluginCheckpoint:
        for row in self._read_list(PLUGIN_CHECKPOINTS_FILE):
            if row.get("plugin_run_id") == plugin_run_id and row.get("checkpoint_id") == checkpoint_id:
                return PluginCheckpoint(**row)
        raise StorageError(f"PLUGIN_CHECKPOINT_NOT_FOUND:{checkpoint_id}")

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
        replaced = False
        for index, row in enumerate(rows):
            if isinstance(row, dict) and row.get(id_field) == expected_id:
                rows[index] = model_to_dict(model)
                replaced = True
                break
        if not replaced:
            raise StorageError(f"PLUGIN_RUN_STORAGE_RECORD_NOT_FOUND:{file_name}:{expected_id}")
        self._write_list(file_name, rows)

    def _read_list(self, file_name: str) -> list[dict[str, Any]]:
        path = self.data_dir / file_name
        if not path.exists():
            if file_name == PLUGIN_RUN_ERRORS_FILE:
                return []
            return []
        data = self.store.read_any(path)
        if not isinstance(data, list):
            raise StorageError(f"PLUGIN_RUN_STORAGE_NOT_LIST:{file_name}")
        return data

    def _write_list(self, file_name: str, rows: list[dict[str, Any]]) -> None:
        self.safety_service.assert_safe_runtime_payload(rows, context=file_name, full_story_text="")
        self.store.write(self.data_dir / file_name, rows)

    def _id(self, prefix: str, plugin_id: str, snapshot_id: str, created_at: str) -> str:
        safe_plugin = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in plugin_id)[:48] or "plugin"
        safe_snapshot = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in snapshot_id)[:72] or "snapshot"
        return f"{prefix}_{safe_plugin}_{safe_snapshot}_{self._time_suffix(created_at)}"

    def _time_suffix(self, value: str) -> str:
        return value.replace("-", "").replace(":", "").replace(".", "").replace("+", "_")
