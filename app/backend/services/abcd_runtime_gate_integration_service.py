import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.abcd_runtime_gate import (
    ABCDApparentContradictionLink,
    ABCDContinuityRuntimeIssue,
    ABCDGateReviewResult,
    ABCDObjectiveFactBoundaryReport,
    ABCDQualityGateRuntimeReport,
    ABCDRuntimeGateContext,
    ABCDRuntimeGateIntegrationAudit,
    ABCDRuntimeGateIssueAcceptance,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.abcd_apparent_contradiction_bridge import (
    ABCDApparentContradictionBridge,
)
from app.backend.services.abcd_continuity_runtime_bridge import (
    ABCDContinuityRuntimeBridge,
)
from app.backend.services.abcd_objective_fact_boundary_service import (
    ABCDObjectiveFactBoundaryService,
)
from app.backend.services.abcd_quality_gate_bridge import ABCDQualityGateBridge
from app.backend.services.abcd_runtime_gate_context_builder import (
    ABCDRuntimeGateContextBuilder,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore, StorageError


STORY_FACT_FILES = [
    "scenes.json",
    "events.json",
    "state_changes.json",
    "memory_records.json",
    "characters.json",
    "relationships.json",
    "world_canvas.json",
    "framework.json",
    "story_bible.json",
]


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ABCDRuntimeGateIntegrationService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        context_builder: ABCDRuntimeGateContextBuilder | None = None,
        continuity_bridge: ABCDContinuityRuntimeBridge | None = None,
        apparent_bridge: ABCDApparentContradictionBridge | None = None,
        objective_boundary_service: ABCDObjectiveFactBoundaryService | None = None,
        quality_bridge: ABCDQualityGateBridge | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.context_builder = context_builder or ABCDRuntimeGateContextBuilder(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.continuity_bridge = continuity_bridge or ABCDContinuityRuntimeBridge()
        self.apparent_bridge = apparent_bridge or ABCDApparentContradictionBridge(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.objective_boundary_service = (
            objective_boundary_service or ABCDObjectiveFactBoundaryService()
        )
        self.quality_bridge = quality_bridge or ABCDQualityGateBridge()
        self.contexts_file = self.data_dir / "abcd_runtime_gate_contexts.json"
        self.runtime_issues_file = self.data_dir / "abcd_continuity_runtime_issues.json"
        self.apparent_links_file = self.data_dir / "abcd_apparent_contradiction_links.json"
        self.objective_reports_file = (
            self.data_dir / "abcd_objective_fact_boundary_reports.json"
        )
        self.quality_reports_file = self.data_dir / "abcd_quality_runtime_reports.json"
        self.audits_file = self.data_dir / "abcd_runtime_gate_integration_audits.json"
        self.acceptances_file = self.data_dir / "abcd_runtime_gate_issue_acceptances.json"

    def review_scene(
        self,
        scene_id: str,
        *,
        mode: str = "draft_review",
        force_refresh: bool = False,
        accepted_issue_ids: list[str] | None = None,
        user_confirmation_text: str | None = None,
        acceptance_source: str = "review_request",
    ) -> ABCDGateReviewResult:
        del force_refresh
        before = self._hash_story_fact_files()
        bundle = self.context_builder.build_bundle(scene_id, mode=mode)
        context: ABCDRuntimeGateContext = bundle["context"]
        runtime_issues, continuity_issues = self.continuity_bridge.build_runtime_issues(
            bundle
        )
        apparent_links, apparent_result = self.apparent_bridge.evaluate(
            bundle=bundle,
            runtime_issues=runtime_issues,
            continuity_issues=continuity_issues,
            mode=mode,
        )
        objective_report = self.objective_boundary_service.build_report(bundle)
        accepted_ids = set(self._accepted_issue_ids_for_scene(context.scene_id))
        accepted_ids.update(_unique(accepted_issue_ids or []))
        accept_all_requires = (
            bool(str(user_confirmation_text or "").strip())
            and acceptance_source != "scene_final_confirmation"
        )
        quality_report = self.quality_bridge.build_report(
            bundle=bundle,
            runtime_issues=runtime_issues,
            apparent_result=apparent_result,
            objective_report=objective_report,
            accepted_issue_ids=accepted_ids,
            accept_all_requires_user_confirmation=accept_all_requires,
        )
        if quality_report.accepted_user_confirmation_issue_ids and (
            accepted_issue_ids or accept_all_requires
        ):
            self._write_acceptances(
                context=context,
                issue_ids=quality_report.accepted_user_confirmation_issue_ids,
                source=acceptance_source,
            )
        after = self._hash_story_fact_files()
        no_story_mutation = before == after
        if not no_story_mutation:
            objective_report = self._mark_story_mutation(objective_report)
            quality_report = self._mark_story_mutation_quality(quality_report)

        audit = self._build_audit(
            context=context,
            runtime_issues=runtime_issues,
            objective_report=objective_report,
            quality_report=quality_report,
            checked_artifact_ids=self._checked_artifact_ids(context, bundle),
            no_story_mutation=no_story_mutation,
        )
        self._write_outputs(
            context=context,
            runtime_issues=runtime_issues,
            apparent_links=apparent_links,
            objective_report=objective_report,
            quality_report=quality_report,
            audit=audit,
        )
        return ABCDGateReviewResult(
            success=True,
            mode=mode,
            passed=audit.passed,
            context=context,
            continuity_runtime_issues=runtime_issues,
            apparent_links=apparent_links,
            objective_fact_boundary_report=objective_report,
            quality_runtime_report=quality_report,
            audit=audit,
            warnings=_unique([*context.warnings, *audit.warnings]),
        )

    def require_final_confirmation_allowed(
        self,
        scene_id: str,
        *,
        user_confirmation_text: str | None = None,
        accepted_issue_ids: list[str] | None = None,
    ) -> ABCDGateReviewResult:
        result = self.review_scene(
            scene_id,
            mode="final_confirmation",
            force_refresh=True,
            accepted_issue_ids=accepted_issue_ids,
            user_confirmation_text=user_confirmation_text,
            acceptance_source="scene_final_confirmation",
        )
        if not result.audit.passed:
            raise StorageError(
                "ABCD_RUNTIME_GATE_BLOCKING_ISSUES: Final scene confirmation is blocked by ABCD runtime gate issues."
            )
        return result

    def latest_for_scene(self, scene_id: str) -> ABCDGateReviewResult:
        clean_scene_id = str(scene_id or "").strip()
        audits = [
            item
            for item in self._read_models(
                self.audits_file,
                ABCDRuntimeGateIntegrationAudit,
            )
            if item.scene_id == clean_scene_id
        ]
        audit = _latest(audits)
        if audit is None:
            raise StorageError(f"ABCD_RUNTIME_GATE_AUDIT_NOT_FOUND: {clean_scene_id}")
        context = self._get_model(
            self.contexts_file,
            ABCDRuntimeGateContext,
            "abcd_runtime_gate_context_id",
            f"abcd_gate_context_{clean_scene_id}_{audit.mode}",
        )
        runtime_issues = [
            item
            for item in self._read_models(
                self.runtime_issues_file,
                ABCDContinuityRuntimeIssue,
            )
            if item.scene_id == clean_scene_id
        ]
        apparent_links = [
            item
            for item in self._read_models(
                self.apparent_links_file,
                ABCDApparentContradictionLink,
            )
            if item.scene_id == clean_scene_id
        ]
        objective_report = self._get_model(
            self.objective_reports_file,
            ABCDObjectiveFactBoundaryReport,
            "boundary_report_id",
            f"abcd_objective_fact_boundary_{clean_scene_id}_{audit.mode}",
        )
        quality_report = self._get_model(
            self.quality_reports_file,
            ABCDQualityGateRuntimeReport,
            "quality_runtime_report_id",
            f"abcd_quality_runtime_{clean_scene_id}_{audit.mode}",
        )
        return ABCDGateReviewResult(
            success=True,
            mode=audit.mode,
            passed=audit.passed,
            context=context,
            continuity_runtime_issues=runtime_issues,
            apparent_links=apparent_links,
            objective_fact_boundary_report=objective_report,
            quality_runtime_report=quality_report,
            audit=audit,
            warnings=_unique([*context.warnings, *audit.warnings]),
        )

    def get_audit(self, audit_id: str) -> ABCDRuntimeGateIntegrationAudit:
        return self._get_model(
            self.audits_file,
            ABCDRuntimeGateIntegrationAudit,
            "audit_id",
            audit_id,
        )

    def get_objective_report(self, report_id: str) -> ABCDObjectiveFactBoundaryReport:
        return self._get_model(
            self.objective_reports_file,
            ABCDObjectiveFactBoundaryReport,
            "boundary_report_id",
            report_id,
        )

    def get_quality_report(self, report_id: str) -> ABCDQualityGateRuntimeReport:
        return self._get_model(
            self.quality_reports_file,
            ABCDQualityGateRuntimeReport,
            "quality_runtime_report_id",
            report_id,
        )

    def record_audit_failure(
        self,
        scene_id: str,
        *,
        mode: str,
        exc: Exception,
    ) -> ABCDGateReviewResult:
        timestamp = utc_now()
        scene_identity = self._scene_identity(scene_id)
        error_code = _safe_error_code(exc)
        context = ABCDRuntimeGateContext(
            abcd_runtime_gate_context_id=f"abcd_gate_context_{scene_identity['scene_id']}_{mode}",
            project_id=scene_identity["project_id"],
            chapter_id=scene_identity["chapter_id"],
            scene_id=scene_identity["scene_id"],
            scene_index=scene_identity["scene_index"],
            mode=mode,
            warnings=[f"abcd_runtime_gate_audit_failed:{error_code}"],
            safe_context_summary="ABCD runtime gate audit failed before context could be fully built.",
            created_at=timestamp,
            updated_at=timestamp,
        )
        objective_report = ABCDObjectiveFactBoundaryReport(
            boundary_report_id=f"abcd_objective_fact_boundary_{context.scene_id}_{context.mode}",
            project_id=context.project_id,
            scene_id=context.scene_id,
            no_unapproved_memory_record_write=False,
            warnings=[f"abcd_runtime_gate_audit_failed:{error_code}"],
            safe_summary="Objective fact boundary could not be audited.",
            created_at=timestamp,
            updated_at=timestamp,
        )
        quality_report = ABCDQualityGateRuntimeReport(
            quality_runtime_report_id=f"abcd_quality_runtime_{context.scene_id}_{context.mode}",
            project_id=context.project_id,
            scene_id=context.scene_id,
            passed=False,
            memory_write_scope_passed=False,
            warnings=[f"abcd_runtime_gate_audit_failed:{error_code}"],
            safe_summary="ABCD runtime quality gate audit failed.",
            created_at=timestamp,
            updated_at=timestamp,
        )
        audit = ABCDRuntimeGateIntegrationAudit(
            audit_id=f"abcd_runtime_gate_audit_{context.scene_id}_{context.mode}",
            project_id=context.project_id,
            scene_id=context.scene_id,
            mode=context.mode,
            passed=False,
            continuity_gate_checked_abcd_runtime=False,
            apparent_gate_checked_abcd_runtime=False,
            quality_gate_checked_abcd_runtime=False,
            objective_fact_guard_checked_abcd_runtime=False,
            m8_role_memory_checked=False,
            no_unapproved_source_story_mutation=True,
            violations=["abcd_runtime_gate_audit_failed"],
            warnings=[f"abcd_runtime_gate_audit_failed:{error_code}"],
            safe_summary="ABCD runtime gate audit failed and was recorded.",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._write_outputs(
            context=context,
            runtime_issues=[],
            apparent_links=[],
            objective_report=objective_report,
            quality_report=quality_report,
            audit=audit,
        )
        return ABCDGateReviewResult(
            success=False,
            mode=mode,
            passed=False,
            context=context,
            continuity_runtime_issues=[],
            apparent_links=[],
            objective_fact_boundary_report=objective_report,
            quality_runtime_report=quality_report,
            audit=audit,
            warnings=audit.warnings,
        )

    def _build_audit(
        self,
        *,
        context: ABCDRuntimeGateContext,
        runtime_issues: list[ABCDContinuityRuntimeIssue],
        objective_report: ABCDObjectiveFactBoundaryReport,
        quality_report: ABCDQualityGateRuntimeReport,
        checked_artifact_ids: list[str],
        no_story_mutation: bool,
    ) -> ABCDRuntimeGateIntegrationAudit:
        timestamp = utc_now()
        violations: list[str] = []
        if not no_story_mutation:
            violations.append("unapproved_story_fact_file_mutation")
        if not objective_report.subjective_claims_kept_subjective:
            violations.append("subjective_claim_polluted_objective_fact_boundary")
        if not objective_report.perceptions_kept_subjective:
            violations.append("perception_polluted_objective_fact_boundary")
        if not objective_report.lies_kept_non_objective:
            violations.append("lie_polluted_objective_fact_boundary")
        hard_conflict_downgraded = any(
            issue.issue_category == "abcd_world_hard_rule_conflict"
            and issue.runtime_issue_id not in quality_report.blocking_issue_ids
            for issue in runtime_issues
        )
        if hard_conflict_downgraded:
            violations.append("hard_rule_conflict_downgraded")
        passed = (
            quality_report.passed
            and no_story_mutation
            and not violations
        )
        warnings = [
            warning
            for warning in context.warnings
            if warning not in {"scene_participation_package_missing"}
        ]
        return ABCDRuntimeGateIntegrationAudit(
            audit_id=f"abcd_runtime_gate_audit_{context.scene_id}_{context.mode}",
            project_id=context.project_id,
            scene_id=context.scene_id,
            mode=context.mode,
            passed=passed,
            continuity_gate_checked_abcd_runtime=True,
            apparent_gate_checked_abcd_runtime=True,
            quality_gate_checked_abcd_runtime=True,
            objective_fact_guard_checked_abcd_runtime=True,
            m8_role_memory_checked=bool(
                context.tiered_scene_memory_write_plan_id
                or context.mode != "post_commit_audit"
            ),
            no_authorial_intent_override=not hard_conflict_downgraded,
            no_character_agent_rule_override=True,
            no_writer_direct_fact_override=True,
            no_unapproved_source_story_mutation=no_story_mutation,
            no_auto_resolution=True,
            no_prior_story_completion_candidate_auto_apply=True,
            checked_artifact_ids=checked_artifact_ids,
            blocking_issue_ids=quality_report.blocking_issue_ids,
            requires_user_confirmation_issue_ids=(
                quality_report.requires_user_confirmation_issue_ids
            ),
            accepted_user_confirmation_issue_ids=(
                quality_report.accepted_user_confirmation_issue_ids
            ),
            violations=violations,
            warnings=warnings,
            safe_summary=(
                "ABCD runtime gate integration audit passed."
                if passed
                else "ABCD runtime gate integration audit found unresolved gate issues."
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _write_outputs(
        self,
        *,
        context: ABCDRuntimeGateContext,
        runtime_issues: list[ABCDContinuityRuntimeIssue],
        apparent_links: list[ABCDApparentContradictionLink],
        objective_report: ABCDObjectiveFactBoundaryReport,
        quality_report: ABCDQualityGateRuntimeReport,
        audit: ABCDRuntimeGateIntegrationAudit,
    ) -> None:
        self._upsert_models(
            self.contexts_file,
            [context],
            "abcd_runtime_gate_context_id",
        )
        self._upsert_models(self.runtime_issues_file, runtime_issues, "runtime_issue_id")
        self._upsert_models(self.apparent_links_file, apparent_links, "link_id")
        self._upsert_models(
            self.objective_reports_file,
            [objective_report],
            "boundary_report_id",
        )
        self._upsert_models(
            self.quality_reports_file,
            [quality_report],
            "quality_runtime_report_id",
        )
        self._upsert_models(self.audits_file, [audit], "audit_id")

    def _checked_artifact_ids(
        self,
        context: ABCDRuntimeGateContext,
        bundle: dict[str, Any],
    ) -> list[str]:
        values = [
            context.abcd_runtime_gate_context_id,
            context.scene_participation_package_id,
            context.tiered_character_context_package_id,
            context.tiered_character_intent_package_id,
            context.abcd_story_information_package_id,
            context.tiered_scene_memory_write_plan_id,
        ]
        values.extend(context.subjective_candidate_ids)
        values.extend(context.writer_story_information_item_ids)
        values.extend(context.role_scene_memory_entry_ids)
        values.extend(
            item.memory_id for item in bundle.get("role_memory_records") or []
        )
        return _unique(values)

    def _mark_story_mutation(
        self,
        report: ABCDObjectiveFactBoundaryReport,
    ) -> ABCDObjectiveFactBoundaryReport:
        data = model_to_dict(report)
        data.update(
            {
                "no_unapproved_event_write": False,
                "no_unapproved_state_change_write": False,
                "no_unapproved_memory_record_write": False,
                "warnings": _unique(
                    [*report.warnings, "unapproved_story_fact_file_mutation"]
                ),
                "updated_at": utc_now(),
            }
        )
        return ABCDObjectiveFactBoundaryReport(**data)

    def _mark_story_mutation_quality(
        self,
        report: ABCDQualityGateRuntimeReport,
    ) -> ABCDQualityGateRuntimeReport:
        data = model_to_dict(report)
        data.update(
            {
                "passed": False,
                "memory_write_scope_passed": False,
                "warnings": _unique(
                    [*report.warnings, "unapproved_story_fact_file_mutation"]
                ),
                "updated_at": utc_now(),
            }
        )
        return ABCDQualityGateRuntimeReport(**data)

    def _accepted_issue_ids_for_scene(self, scene_id: str) -> list[str]:
        return [
            item.runtime_issue_id
            for item in self._read_models(
                self.acceptances_file,
                ABCDRuntimeGateIssueAcceptance,
            )
            if item.scene_id == scene_id and item.user_confirmation_present
        ]

    def _write_acceptances(
        self,
        *,
        context: ABCDRuntimeGateContext,
        issue_ids: list[str],
        source: str,
    ) -> None:
        timestamp = utc_now()
        models = [
            ABCDRuntimeGateIssueAcceptance(
                acceptance_id=f"abcd_runtime_gate_acceptance_{issue_id}",
                project_id=context.project_id,
                scene_id=context.scene_id,
                runtime_issue_id=issue_id,
                source=_safe_source(source),
                user_confirmation_present=True,
                created_at=timestamp,
                updated_at=timestamp,
            )
            for issue_id in _unique(issue_ids)
        ]
        self._upsert_models(self.acceptances_file, models, "acceptance_id")

    def _scene_identity(self, scene_id: str) -> dict[str, Any]:
        clean_scene_id = str(scene_id or "").strip()
        for row in self.repositories.scenes.list_all():
            if isinstance(row, dict) and str(row.get("scene_id") or "") == clean_scene_id:
                return {
                    "project_id": str(row.get("project_id") or "local_project"),
                    "chapter_id": str(row.get("chapter_id") or ""),
                    "scene_id": clean_scene_id,
                    "scene_index": int(row.get("scene_index") or 0),
                }
        return {
            "project_id": "local_project",
            "chapter_id": "",
            "scene_id": clean_scene_id or "unknown_scene",
            "scene_index": 0,
        }

    def _hash_story_fact_files(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for file_name in STORY_FACT_FILES:
            path = self.data_dir / file_name
            if not path.exists():
                result[file_name] = ""
                continue
            payload = path.read_bytes()
            result[file_name] = hashlib.sha256(payload).hexdigest()
        return result

    def _read_models(self, path: Path, model_type: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        try:
            rows = self.store.read_list(path)
            return [
                model_type(**row)
                for row in rows
                if isinstance(row, dict)
            ]
        except (TypeError, ValidationError) as exc:
            raise StorageError(f"ABCD_RUNTIME_GATE_STORAGE_INVALID: {path.name}") from exc

    def _get_model(
        self,
        path: Path,
        model_type: type[BaseModel],
        id_field: str,
        target_id: str,
    ) -> Any:
        clean_id = str(target_id or "").strip()
        for item in self._read_models(path, model_type):
            if str(getattr(item, id_field, "") or "") == clean_id:
                return item
        raise StorageError(f"ABCD_RUNTIME_GATE_ARTIFACT_NOT_FOUND: {clean_id}")

    def _upsert_models(
        self,
        path: Path,
        models: list[BaseModel],
        id_field: str,
    ) -> None:
        existing = self.store.read_list(path) if self.store.exists(path) else []
        by_id = {
            str(row.get(id_field) or ""): dict(row)
            for row in existing
            if isinstance(row, dict)
        }
        order = [
            str(row.get(id_field) or "")
            for row in existing
            if isinstance(row, dict) and row.get(id_field)
        ]
        for model in models:
            row = model_to_dict(model)
            row_id = str(row.get(id_field) or "")
            if not row_id:
                continue
            if row_id not in by_id:
                order.append(row_id)
            by_id[row_id] = row
        self.store.write(path, [by_id[row_id] for row_id in order if row_id in by_id])


def _latest(items: list[Any]) -> Any | None:
    if not items:
        return None
    return sorted(
        items,
        key=lambda item: (
            str(getattr(item, "updated_at", "") or ""),
            str(getattr(item, "created_at", "") or ""),
        ),
        reverse=True,
    )[0]


def _unique(values: list[Any]) -> list[str]:
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


def _safe_source(value: str) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    allowed = {"review_request", "scene_final_confirmation"}
    return text if text in allowed else "review_request"


def _safe_error_code(exc: Exception) -> str:
    text = str(exc or "").strip().split(":", 1)[0].strip()
    if not text:
        return exc.__class__.__name__
    safe = "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-"})
    return safe[:80] or exc.__class__.__name__
