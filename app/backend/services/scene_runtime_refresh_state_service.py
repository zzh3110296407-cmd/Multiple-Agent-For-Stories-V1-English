from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.backend.core.config import settings
from app.backend.services.active_project_story_data import current_story_workspace_project_id
from app.backend.services.abcd_runtime_gate_integration_service import (
    ABCDRuntimeGateIntegrationService,
)
from app.backend.services.composite_runtime_read_service import CompositeRuntimeReadService
from app.backend.models.scene_participation import SceneParticipationPrepareRequest
from app.backend.services.scene_participation_package_service import (
    SceneParticipationPackageService,
)
from app.backend.storage.json_store import JsonStore, StorageError


SHANGHAI_TZ = timezone(timedelta(hours=8))
COMPOSITE_RUNTIME_RUNS_FILE = "composite_runtime_graph_runs.json"


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class SceneRuntimeRefreshStateService:
    """Current-scene runtime readiness evaluator for final scene confirmation."""

    STORY_FACT_FILES = {
        "events.json",
        "memory_records.json",
        "state_changes.json",
        "relationships.json",
        "chapter_archives.json",
        "final_story_package_readiness_bundles.json",
        "final_story_package_snapshots.json",
    }

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        composite_runtime_read_service: CompositeRuntimeReadService | None = None,
        composite_runtime_read_service_factory: Callable[[], CompositeRuntimeReadService] | None = None,
        abcd_runtime_gate_service: ABCDRuntimeGateIntegrationService | None = None,
        scene_participation_service: SceneParticipationPackageService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.scenes_file = self.data_dir / "scenes.json"
        self.scene_participation_packages_file = (
            self.data_dir / "scene_participation_packages.json"
        )
        self.abcd_audits_file = self.data_dir / "abcd_runtime_gate_integration_audits.json"
        self.abcd_quality_reports_file = self.data_dir / "abcd_quality_runtime_reports.json"
        self.composite_runtime_read_service = composite_runtime_read_service
        self.composite_runtime_read_service_factory = composite_runtime_read_service_factory
        self.abcd_runtime_gate_service = abcd_runtime_gate_service or (
            ABCDRuntimeGateIntegrationService(store=self.store, data_dir=self.data_dir)
        )
        self.scene_participation_service = scene_participation_service or (
            SceneParticipationPackageService(store=self.store, data_dir=self.data_dir)
        )

    def evaluate(
        self,
        scene_id: str,
        *,
        revision_id: str = "",
        user_confirmation_text: str | None = None,
        refresh_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        scene = self._find_scene(scene_id)
        if not scene:
            raise StorageError(f"SCENE_RUNTIME_SCENE_NOT_FOUND: {scene_id}")

        project_id = str(scene.get("project_id") or self._current_project_id())
        chapter_id = str(scene.get("chapter_id") or "")
        scene_index = self._int(scene.get("scene_index"), 0)
        gate_target = self._gate_evidence_target(scene, revision_id=revision_id)
        timestamp = now_iso()

        participation = self._participation_summary(
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            refresh_errors=refresh_errors,
        )
        abcd_gate = self._abcd_gate_summary(scene_id, refresh_errors=refresh_errors)
        composite = self._composite_summary(
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
        )
        quality = self._quality_gate_summary(
            gate_target["quality_report"],
            user_confirmation_text=user_confirmation_text,
            target_source_refs=gate_target["source_refs"],
        )
        continuity = self._continuity_gate_summary(
            gate_target["quality_report"],
            target_source_refs=gate_target["source_refs"],
        )

        steps = [
            self._step("scene_participation_refresh_pending", participation),
            self._step("abcd_runtime_refresh_pending", abcd_gate),
            self._step("composite_runtime_refresh_pending", composite),
            self._step("gates_refresh_pending", self._combined_gate_summary(quality, continuity)),
        ]
        blocking = self._unique(
            [
                *participation["blocking_reasons"],
                *abcd_gate["blocking_reasons"],
                *composite["blocking_reasons"],
                *quality["blocking_reasons"],
                *continuity["blocking_reasons"],
            ]
        )
        degraded = self._unique(
            [
                *participation["degraded_reasons"],
                *abcd_gate["degraded_reasons"],
                *composite["degraded_reasons"],
                *quality["degraded_reasons"],
                *continuity["degraded_reasons"],
            ]
        )
        state = self._state_for(
            participation=participation,
            abcd_gate=abcd_gate,
            composite=composite,
            quality=quality,
            continuity=continuity,
            blocking=blocking,
            degraded=degraded,
        )
        confirm_allowed = state == "confirm_enabled"
        return {
            "schema_version": "phase85_m7_scene_runtime_refresh_state_v1",
            "project_id": project_id,
            "chapter_id": chapter_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "target_type": gate_target["target_type"],
            "target_id": gate_target["target_id"],
            "revision_id": gate_target["revision_id"],
            "state": state,
            "confirm_allowed": confirm_allowed,
            "runtime_evidence_status": "ready" if confirm_allowed else self._overall_status(state),
            "runtime_evidence_scope": (
                "current_scene_revision"
                if gate_target["target_type"] == "scene_revision"
                else "current_scene"
            ),
            "graph_run_id": composite.get("graph_run_id", ""),
            "freshness_timestamp": self._latest_timestamp(
                [timestamp, composite.get("freshness_timestamp", "")]
            ),
            "blocking_reasons": blocking,
            "degraded_reasons": degraded,
            "source_refs": self._unique(
                [
                    *participation["source_refs"],
                    *abcd_gate["source_refs"],
                    *composite["source_refs"],
                    *quality["source_refs"],
                    *continuity["source_refs"],
                ]
            ),
            "steps": steps,
            "abcd_runtime_summary": {
                "status": self._least_ready_status(
                    [participation["status"], abcd_gate["status"]]
                ),
                "participant_count": participation["participant_count"],
                "participants_ready": participation["status"] == "ready",
                "gate_status": abcd_gate["status"],
                "current_scene_match": True,
                "blocking_reasons": self._unique(
                    [*participation["blocking_reasons"], *abcd_gate["blocking_reasons"]]
                ),
                "degraded_reasons": self._unique(
                    [*participation["degraded_reasons"], *abcd_gate["degraded_reasons"]]
                ),
            },
            "composite_runtime_summary": composite,
            "quality_gate_summary": quality,
            "continuity_gate_summary": continuity,
            "read_only": True,
        }

    def refresh(
        self,
        scene_id: str,
        *,
        revision_id: str = "",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        scene = self._find_scene(scene_id)
        if not scene:
            raise StorageError(f"SCENE_RUNTIME_SCENE_NOT_FOUND: {scene_id}")
        refresh_errors: list[str] = []
        try:
            if force_refresh or not self._latest_participation_package(
                project_id=str(scene.get("project_id") or self._current_project_id()),
                chapter_id=str(scene.get("chapter_id") or ""),
                scene_id=scene_id,
                scene_index=self._int(scene.get("scene_index"), 0),
            ):
                self.scene_participation_service.prepare_package(
                    SceneParticipationPrepareRequest(
                        chapter_id=str(scene.get("chapter_id") or ""),
                        scene_id=scene_id,
                        scene_index=self._int(scene.get("scene_index"), 0),
                        scene_goal=str(scene.get("scene_goal") or ""),
                        scene_location=str(scene.get("location") or ""),
                        force_refresh=force_refresh,
                    )
                )
        except Exception:
            # Evaluation will expose the missing/blocked state. Refresh must not hide it.
            refresh_errors.append("scene_participation_refresh_failed")
        try:
            self.abcd_runtime_gate_service.review_scene(
                scene_id,
                mode="draft_review",
                force_refresh=True,
            )
        except Exception:
            refresh_errors.append("abcd_runtime_refresh_failed")
        if force_refresh:
            try:
                self._refresh_composite_runtime_candidate_preview(scene)
            except Exception:
                refresh_errors.append("composite_runtime_refresh_failed")
        return self.evaluate(scene_id, revision_id=revision_id, refresh_errors=refresh_errors)

    def require_confirm_allowed(
        self,
        scene_id: str,
        *,
        revision_id: str = "",
        user_confirmation_text: str | None = None,
    ) -> dict[str, Any]:
        state = self.evaluate(
            scene_id,
            revision_id=revision_id,
            user_confirmation_text=user_confirmation_text,
        )
        if state.get("confirm_allowed") is not True and str(state.get("state") or "") in {
            "blocked_runtime_stale",
            "composite_runtime_refresh_pending",
        }:
            state = self.refresh(
                scene_id,
                revision_id=revision_id,
                force_refresh=True,
            )
        if state.get("confirm_allowed") is True:
            return state
        code = self._error_code_for_state(str(state.get("state") or ""))
        reasons = ", ".join(state.get("blocking_reasons") or []) or "runtime_confirm_not_ready"
        raise StorageError(f"{code}: {reasons}")

    def _find_scene(self, scene_id: str) -> dict[str, Any]:
        clean = str(scene_id or "").strip()
        for scene in self._read_list(self.scenes_file):
            if isinstance(scene, dict) and str(scene.get("scene_id") or "") == clean:
                return scene
        return {}

    def _gate_evidence_target(
        self,
        scene: dict[str, Any],
        *,
        revision_id: str = "",
    ) -> dict[str, Any]:
        requested_revision_id = str(revision_id or "").strip()
        active_revision_id = str(scene.get("active_revision_id") or "").strip()
        resolved_revision_id = requested_revision_id or active_revision_id
        if resolved_revision_id:
            candidate = self._find_revision_candidate(scene, resolved_revision_id)
            if not candidate and requested_revision_id:
                raise StorageError(
                    f"SCENE_RUNTIME_REVISION_NOT_FOUND: {resolved_revision_id}"
                )
            report = self._dict(candidate.get("quality_report")) if candidate else {}
            report_id = (
                str(candidate.get("quality_report_id") or report.get("quality_report_id") or "").strip()
                if candidate
                else ""
            )
            return {
                "target_type": "scene_revision",
                "target_id": resolved_revision_id,
                "revision_id": resolved_revision_id,
                "quality_report": report,
                "source_refs": self._unique(
                    [
                        f"scene_revision:{resolved_revision_id}",
                        f"quality_report:{report_id}" if report_id else "",
                    ]
                ),
            }
        report = self._dict(scene.get("quality_report"))
        report_id = str(scene.get("quality_report_id") or report.get("quality_report_id") or "").strip()
        return {
            "target_type": "scene",
            "target_id": str(scene.get("scene_id") or ""),
            "revision_id": "",
            "quality_report": report,
            "source_refs": self._unique(
                [
                    f"scene:{scene.get('scene_id') or ''}",
                    f"quality_report:{report_id}" if report_id else "",
                ]
            ),
        }

    def _find_revision_candidate(
        self,
        scene: dict[str, Any],
        revision_id: str,
    ) -> dict[str, Any]:
        clean = str(revision_id or "").strip()
        for candidate in scene.get("revision_history") or []:
            if isinstance(candidate, dict) and str(candidate.get("revision_id") or "") == clean:
                return candidate
        return {}

    def _participation_summary(
        self,
        *,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
        refresh_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        errors = set(refresh_errors or [])
        if "scene_participation_refresh_failed" in errors:
            return self._summary(
                status="blocked",
                blocking=["blocked_abcd_runtime", "scene_participation_refresh_failed"],
                degraded=["scene_participation_refresh_failed"],
                source_refs=["scene_participation_refresh:failed"],
            ) | {"participant_count": 0, "package_id": ""}
        package = self._latest_participation_package(
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
        )
        if not package:
            return self._summary(
                status="missing",
                blocking=["scene_participation_refresh_pending"],
            ) | {"participant_count": 0, "package_id": ""}
        active_ids = self._string_list(package.get("active_character_ids"))
        status = str(package.get("status") or "unknown")
        blocking = self._string_list(package.get("blocking_issues"))
        warnings = self._string_list(package.get("warnings"))
        if not active_ids:
            blocking.append("abcd_runtime_participants_missing")
        if status == "blocked":
            blocking.append("blocked_abcd_runtime")
        result_status = "ready" if not blocking else "blocked"
        return self._summary(
            status=result_status,
            blocking=blocking,
            degraded=warnings if result_status == "ready" else [],
            source_refs=[
                f"scene_participation_package:{package.get('package_id') or package.get('scene_participation_package_id') or ''}"
            ],
        ) | {
            "participant_count": len(active_ids),
            "package_id": str(
                package.get("package_id") or package.get("scene_participation_package_id") or ""
            ),
        }

    def _latest_participation_package(
        self,
        *,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
    ) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        for package in self._read_list(self.scene_participation_packages_file):
            if not isinstance(package, dict):
                continue
            if str(package.get("project_id") or project_id) != project_id:
                continue
            if str(package.get("chapter_id") or "") != chapter_id:
                continue
            if self._int(package.get("scene_index"), -1) != scene_index:
                continue
            package_scene_id = str(package.get("scene_id") or "").strip()
            if package_scene_id and package_scene_id != scene_id:
                continue
            matches.append(package)
        return self._latest(matches)

    def _abcd_gate_summary(
        self,
        scene_id: str,
        *,
        refresh_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        errors = set(refresh_errors or [])
        if "abcd_runtime_refresh_failed" in errors:
            return self._summary(
                status="blocked",
                blocking=["blocked_abcd_runtime", "abcd_runtime_refresh_failed"],
                degraded=["abcd_runtime_refresh_failed"],
                source_refs=["abcd_runtime_gate_refresh:failed"],
            )
        audit = self._latest(
            [
                item
                for item in self._read_list(self.abcd_audits_file)
                if isinstance(item, dict) and str(item.get("scene_id") or "") == scene_id
            ]
        )
        if not audit:
            return self._summary(status="missing", blocking=["abcd_runtime_gate_not_run"])
        blocking = self._string_list(audit.get("blocking_issue_ids"))
        requires = self._string_list(audit.get("requires_user_confirmation_issue_ids"))
        violations = self._string_list(audit.get("violations"))
        warnings = self._string_list(audit.get("warnings"))
        if blocking or requires or violations or audit.get("passed") is False:
            return self._summary(
                status="blocked",
                blocking=self._unique(
                    [
                        "blocked_abcd_runtime",
                        *blocking,
                        *requires,
                        *violations,
                    ]
                ),
                source_refs=[f"abcd_runtime_gate_audit:{audit.get('audit_id') or ''}"],
            )
        return self._summary(
            status="ready",
            degraded=warnings,
            source_refs=[f"abcd_runtime_gate_audit:{audit.get('audit_id') or ''}"],
        )

    def _composite_summary(
        self,
        *,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
    ) -> dict[str, Any]:
        try:
            payload = self._composite_read_service().latest_run(
                chapter_id=chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
                include_expert=False,
            )
        except Exception:
            return self._summary(
                status="unavailable",
                blocking=["composite_runtime_backend_unavailable"],
                degraded=["composite_runtime_backend_unavailable"],
            ) | {
                "graph_run_id": "",
                "current_scene_match": False,
                "source_kind": "live_project_runtime",
                "freshness_timestamp": "",
            }
        source_kind = str(payload.get("source_kind") or "")
        current_scene_match = payload.get("current_scene_match") is True
        status = str(payload.get("status") or payload.get("runtime_evidence_status") or "")
        blocking = self._string_list(payload.get("blocking_reasons"))
        degraded = self._string_list(payload.get("degraded_reasons"))
        if source_kind != "live_project_runtime":
            blocking.append("composite_runtime_current_scene_missing")
        if not current_scene_match:
            blocking.append("composite_runtime_scope_mismatch")
        if status in {"empty", "missing", "not_found"}:
            blocking.append("composite_runtime_current_scene_missing")
        if status in {"blocked", "failed"}:
            blocking.append("blocked_composite_runtime")
        if status in {"empty", "missing", "not_found"}:
            result_status = "missing"
        elif not current_scene_match:
            result_status = "stale"
        elif status in {"blocked", "failed"}:
            result_status = "blocked"
        else:
            result_status = "ready" if not blocking else "blocked"
        return self._summary(
            status=result_status,
            blocking=blocking,
            degraded=degraded if result_status == "ready" else [],
            source_refs=self._string_list(payload.get("source_refs")),
        ) | {
            "graph_run_id": str(payload.get("graph_run_id") or ""),
            "current_scene_match": current_scene_match,
            "source_kind": source_kind,
            "final_decision": str(payload.get("final_decision") or ""),
            "freshness_timestamp": str(payload.get("freshness_timestamp") or ""),
        }

    def _refresh_composite_runtime_candidate_preview(self, scene: dict[str, Any]) -> None:
        from app.backend.models.composite_runtime_graph import (
            CompositeRuntimeGraphInputRefs,
            CompositeRuntimeGraphRunRequest,
        )
        from app.backend.services.composite_runtime_orchestration_service import (
            CompositeRuntimeOrchestrationService,
        )

        request = CompositeRuntimeGraphRunRequest(
            project_id=str(scene.get("project_id") or self._current_project_id()),
            chapter_id=str(scene.get("chapter_id") or ""),
            scene_id=str(scene.get("scene_id") or ""),
            scene_index=self._int(scene.get("scene_index"), 0),
            scene_goal=str(scene.get("goal") or scene.get("synopsis") or ""),
            scene_location=str(scene.get("location") or ""),
            mode="candidate_preview",
            input_refs=CompositeRuntimeGraphInputRefs(),
            dry_run=True,
        )
        result = CompositeRuntimeOrchestrationService(
            store=self.store,
            data_dir=self.data_dir,
        ).run(request)
        payload = self._model_to_dict(result)
        if not self._dict(payload.get("candidate_scene_output")):
            payload["candidate_scene_output"] = self._composite_runtime_scene_ref(
                scene,
                graph_run_id=str(payload.get("graph_run_id") or request.graph_run_id),
            )
        payload["source_kind"] = "live_project_runtime"
        payload["read_only"] = True
        self._append_composite_runtime_run(payload)

    def _append_composite_runtime_run(self, payload: dict[str, Any]) -> None:
        path = self.data_dir / COMPOSITE_RUNTIME_RUNS_FILE
        rows: list[Any] = []
        if self.store.exists(path):
            existing = self.store.read_any(path)
            if isinstance(existing, list):
                rows = existing
            elif isinstance(existing, dict) and isinstance(existing.get("runs"), list):
                rows = existing.get("runs") or []
        graph_run_id = str(payload.get("graph_run_id") or "")
        rows = [
            item
            for item in rows
            if not isinstance(item, dict) or str(item.get("graph_run_id") or "") != graph_run_id
        ]
        rows.append(payload)
        self.store.write(path, rows[-50:])

    def _model_to_dict(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        return dict(value or {}) if isinstance(value, dict) else {}

    def _composite_runtime_scene_ref(
        self,
        scene: dict[str, Any],
        *,
        graph_run_id: str,
    ) -> dict[str, Any]:
        return {
            "candidate_scene_output_id": f"candidate_scene_output_{graph_run_id}",
            "graph_run_id": graph_run_id,
            "project_id": str(scene.get("project_id") or self._current_project_id()),
            "chapter_id": str(scene.get("chapter_id") or ""),
            "scene_id": str(scene.get("scene_id") or ""),
            "scene_index": self._int(scene.get("scene_index"), 0),
            "candidate_only": True,
            "can_write_scene_directly": False,
            "can_write_story_facts_directly": False,
            "story_fact_delta_empty": True,
        }

    def _quality_gate_summary(
        self,
        report: dict[str, Any],
        *,
        user_confirmation_text: str | None = None,
        target_source_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        if not report or (
            "passed" not in report
            and not report.get("blocking_issues")
            and not report.get("warnings")
        ):
            return self._summary(
                status="missing",
                blocking=["gates_refresh_pending"],
                source_refs=target_source_refs or [],
            )
        blocking = self._string_list(report.get("blocking_issues"))
        requires_confirmation = report.get("requires_user_confirmation") is True
        confirmation_supplied = bool(str(user_confirmation_text or "").strip())
        if requires_confirmation and not confirmation_supplied:
            blocking.append("quality_requires_user_confirmation")
        if report.get("passed") is False and blocking:
            status = "blocked"
        else:
            status = "ready" if not blocking else "blocked"
        degraded = self._string_list(report.get("warnings")) if status == "ready" else []
        if requires_confirmation and confirmation_supplied and status == "ready":
            degraded.append("quality_user_confirmation_supplied")
        return self._summary(
            status=status,
            blocking=blocking,
            degraded=degraded,
            source_refs=self._unique(
                [
                    *(target_source_refs or []),
                    f"quality_report:{report.get('quality_report_id') or 'embedded_scene_quality'}",
                ]
            ),
        ) | {
            "passed": bool(report.get("passed")),
            "requires_user_confirmation": requires_confirmation,
            "user_confirmation_supplied": confirmation_supplied,
        }

    def _continuity_gate_summary(
        self,
        report: dict[str, Any],
        *,
        target_source_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        if not report or "continuity_passed" not in report:
            return self._summary(
                status="missing",
                blocking=["gates_refresh_pending"],
                source_refs=target_source_refs or [],
            )
        continuity_gate_run_id = str(report.get("continuity_gate_run_id") or "").strip()
        continuity_checked_at = str(report.get("continuity_checked_at") or "").strip()
        continuity_checked = report.get("continuity_checked") is True
        explicit_run_evidence_present = (
            continuity_checked
            and bool(continuity_gate_run_id)
            and bool(continuity_checked_at)
        )
        blocking = self._string_list(report.get("blocking_continuity_issue_ids"))
        if not explicit_run_evidence_present:
            blocking.append("continuity_run_evidence_missing")
        if (
            report.get("continuity_passed") is False
            and "scene_continuity_not_passed" not in blocking
        ):
            blocking.append("scene_continuity_not_passed")
        source_refs = self._string_list(report.get("continuity_issue_ids"))
        if continuity_gate_run_id:
            source_refs.append(f"continuity_gate_run:{continuity_gate_run_id}")
        source_refs = self._unique([*(target_source_refs or []), *source_refs])
        return self._summary(
            status="ready" if not blocking else "blocked",
            blocking=blocking,
            source_refs=source_refs,
        ) | {
            "passed": bool(report.get("continuity_passed", True)),
            "continuity_checked": continuity_checked,
            "continuity_gate_run_id": continuity_gate_run_id,
            "continuity_checked_at": continuity_checked_at,
        }

    def _combined_gate_summary(
        self,
        quality: dict[str, Any],
        continuity: dict[str, Any],
    ) -> dict[str, Any]:
        status = self._least_ready_status([quality["status"], continuity["status"]])
        return self._summary(
            status=status,
            blocking=self._unique([*quality["blocking_reasons"], *continuity["blocking_reasons"]]),
            degraded=self._unique([*quality["degraded_reasons"], *continuity["degraded_reasons"]]),
            source_refs=self._unique([*quality["source_refs"], *continuity["source_refs"]]),
        )

    def _state_for(
        self,
        *,
        participation: dict[str, Any],
        abcd_gate: dict[str, Any],
        composite: dict[str, Any],
        quality: dict[str, Any],
        continuity: dict[str, Any],
        blocking: list[str],
        degraded: list[str],
    ) -> str:
        del blocking
        if quality["status"] == "blocked" or continuity["status"] == "blocked":
            return "blocked_quality_or_continuity"
        if participation["status"] in {"missing", "pending"}:
            return "scene_participation_refresh_pending"
        if participation["status"] == "blocked" or abcd_gate["status"] == "blocked":
            return "blocked_abcd_runtime"
        if abcd_gate["status"] in {"missing", "pending"}:
            return "abcd_runtime_refresh_pending"
        if composite["status"] == "unavailable":
            return "blocked_runtime_unavailable"
        if composite["status"] == "stale" or "composite_runtime_scope_mismatch" in composite["blocking_reasons"]:
            return "blocked_runtime_stale"
        if composite["status"] in {"missing", "pending"}:
            return "composite_runtime_refresh_pending"
        if composite["status"] == "blocked":
            return "blocked_composite_runtime"
        if quality["status"] in {"missing", "pending"} or continuity["status"] in {
            "missing",
            "pending",
        }:
            return "gates_refresh_pending"
        return "confirm_enabled"

    def _error_code_for_state(self, state: str) -> str:
        if state == "blocked_runtime_stale":
            return "SCENE_RUNTIME_EVIDENCE_STALE"
        if state == "blocked_runtime_unavailable":
            return "SCENE_COMPOSITE_RUNTIME_UNAVAILABLE"
        if state == "blocked_abcd_runtime":
            return "SCENE_ABCD_RUNTIME_NOT_READY"
        return "SCENE_RUNTIME_REFRESH_NOT_READY"

    def _composite_read_service(self) -> CompositeRuntimeReadService:
        if self.composite_runtime_read_service is not None:
            return self.composite_runtime_read_service
        if self.composite_runtime_read_service_factory is not None:
            return self.composite_runtime_read_service_factory()
        return CompositeRuntimeReadService(
            store=self.store,
            data_dir=self.data_dir,
            allow_static_fallback=False,
        )

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(self.store, self.data_dir, fallback="local_project")

    def _step(self, step_id: str, summary: dict[str, Any]) -> dict[str, Any]:
        completed = summary["status"] == "ready"
        return {
            "step_id": step_id,
            "status": summary["status"],
            "started_at": "",
            "completed_at": now_iso() if completed else "",
            "blocking_reasons": summary["blocking_reasons"],
            "source_refs": summary["source_refs"],
        }

    def _summary(
        self,
        *,
        status: str,
        blocking: list[str] | None = None,
        degraded: list[str] | None = None,
        source_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "blocking_reasons": self._unique(blocking or []),
            "degraded_reasons": self._unique(degraded or []),
            "source_refs": self._unique([ref for ref in (source_refs or []) if ref.strip(":")]),
        }

    def _overall_status(self, state: str) -> str:
        if "stale" in state:
            return "stale"
        if "missing" in state or state.endswith("_pending"):
            return "pending"
        if "unavailable" in state:
            return "unavailable"
        if state.startswith("blocked"):
            return "blocked"
        return "degraded"

    def _least_ready_status(self, values: list[str]) -> str:
        order = ["blocked", "unavailable", "missing", "pending", "degraded", "ready"]
        known = [value if value in order else "pending" for value in values]
        return min(known, key=order.index) if known else "missing"

    def _latest_timestamp(self, values: list[str]) -> str:
        return next((str(value) for value in values if str(value or "").strip()), "")

    def _latest(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {}
        return sorted(
            rows,
            key=lambda item: str(
                item.get("updated_at") or item.get("created_at") or item.get("completed_at") or ""
            ),
        )[-1]

    def _read_list(self, path: Path) -> list[Any]:
        if not self.store.exists(path):
            return []
        try:
            value = self.store.read_any(path)
        except StorageError:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("items", "records", "runs", "packages"):
                maybe = value.get(key)
                if isinstance(maybe, list):
                    return maybe
        return []

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        return self._unique([str(item or "").strip() for item in values if str(item or "").strip()])

    def _unique(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    def _int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
