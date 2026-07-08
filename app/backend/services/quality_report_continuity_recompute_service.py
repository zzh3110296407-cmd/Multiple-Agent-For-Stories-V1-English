from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.continuity import ContinuityTargetStateSnapshot
from app.backend.models.quality import QualityIssue, QualityReport, to_embedded_scene_quality_report
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.continuity_resolution_refresh_service import (
    ContinuityResolutionRefreshService,
)
from app.backend.storage.json_store import JsonStore, StorageError


CONFIRMATION_SEVERITIES = {"needs_user_confirmation", "requires_user_confirmation"}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class QualityReportContinuityRecomputeService:
    """Recompute QualityReport continuity fields from stored continuity state only."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        refresh_service: ContinuityResolutionRefreshService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.refresh_service = refresh_service or ContinuityResolutionRefreshService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def recompute_for_target(
        self,
        target_type: str,
        target_id: str,
        *,
        scene_id: str = "",
        revision_id: str = "",
        mode: str = "manual",
    ) -> QualityReport | None:
        snapshot = self.refresh_service.build_target_state_snapshot(
            target_type,
            target_id,
            scene_id=scene_id,
            revision_id=revision_id,
            mode=mode,
        )
        return self.recompute_for_snapshot(snapshot)

    def recompute_for_snapshot(
        self,
        snapshot: ContinuityTargetStateSnapshot,
    ) -> QualityReport | None:
        report = self._latest_quality_report(snapshot.target_type, snapshot.target_id)
        if report is None:
            return None
        continuity_issue_ids = self._target_continuity_issue_ids(snapshot)
        preserved_warnings = [
            issue
            for issue in report.warnings
            if not self._is_continuity_derived_issue(issue, continuity_issue_ids)
        ]
        preserved_blocking = [
            issue
            for issue in report.blocking_issues
            if not self._is_continuity_derived_issue(issue, continuity_issue_ids)
        ]
        non_continuity_requires_confirmation = any(
            issue.severity in CONFIRMATION_SEVERITIES
            for issue in [*preserved_warnings, *preserved_blocking]
        )
        active_continuity_issue_ids = [
            *snapshot.remaining_open_issue_ids,
            *snapshot.accepted_issue_ids,
        ]
        updated = QualityReport(
            **{
                **model_to_dict(report),
                "passed": not preserved_blocking and snapshot.continuity_passed,
                "warnings": [model_to_dict(issue) for issue in preserved_warnings],
                "blocking_issues": [model_to_dict(issue) for issue in preserved_blocking],
                "requires_user_confirmation": (
                    non_continuity_requires_confirmation
                    or snapshot.requires_user_confirmation
                ),
                "continuity_passed": snapshot.continuity_passed,
                "continuity_issue_ids": active_continuity_issue_ids,
                "blocking_continuity_issue_ids": snapshot.remaining_blocking_issue_ids,
                "accepted_continuity_issue_ids": snapshot.accepted_issue_ids,
                "summary": self._summary(
                    snapshot=snapshot,
                    preserved_blocking=preserved_blocking,
                    non_continuity_requires_confirmation=non_continuity_requires_confirmation,
                ),
            }
        )
        self._persist_report(updated)
        self._sync_embedded_report(updated)
        return updated

    def _latest_quality_report(
        self,
        target_type: str,
        target_id: str,
    ) -> QualityReport | None:
        matches = [
            item
            for item in self.repositories.quality_reports.list_all()
            if item.get("target_type") == target_type
            and item.get("target_id") == target_id
        ]
        if not matches:
            return None
        try:
            return QualityReport(**matches[-1])
        except ValidationError as exc:
            raise StorageError("QualityReport JSON schema is invalid.") from exc

    def _persist_report(self, report: QualityReport) -> None:
        report_data = model_to_dict(report)
        self.repositories.quality_reports.write_all(
            [
                report_data
                if item.get("quality_report_id") == report.quality_report_id
                else item
                for item in self.repositories.quality_reports.list_all()
            ]
        )

    def _sync_embedded_report(self, report: QualityReport) -> None:
        embedded = model_to_dict(to_embedded_scene_quality_report(report))
        embedded["quality_report_id"] = report.quality_report_id
        if report.target_type == "scene_revision":
            self._sync_revision_embedded_report(report, embedded)
            return
        self._sync_scene_embedded_report(report, embedded)

    def _sync_scene_embedded_report(
        self,
        report: QualityReport,
        embedded: dict[str, Any],
    ) -> None:
        target_scene_id = report.scene_id or report.target_id
        updated_scenes: list[dict[str, Any]] = []
        for raw in self.repositories.scenes.list_all():
            if raw.get("scene_id") != target_scene_id:
                updated_scenes.append(raw)
                continue
            item = dict(raw)
            item["quality_report"] = embedded
            item["quality_report_id"] = report.quality_report_id
            updated_scenes.append(item)
        self.repositories.scenes.write_all(updated_scenes)

    def _sync_revision_embedded_report(
        self,
        report: QualityReport,
        embedded: dict[str, Any],
    ) -> None:
        revision_id = report.revision_id or report.target_id
        updated_scenes: list[dict[str, Any]] = []
        for raw in self.repositories.scenes.list_all():
            item = dict(raw)
            history = []
            changed = False
            for candidate in item.get("revision_history") or []:
                candidate_data = dict(candidate)
                if candidate_data.get("revision_id") == revision_id:
                    candidate_data["quality_report"] = embedded
                    candidate_data["quality_report_id"] = report.quality_report_id
                    candidate_data["requires_user_confirmation"] = bool(
                        candidate_data.get("requires_user_confirmation")
                        or embedded.get("requires_user_confirmation")
                        or embedded.get("quality_degraded")
                        or embedded.get("semantic_check_status") == "failed"
                    )
                    confirmation_gate = dict(
                        candidate_data.get("confirmation_gate") or {}
                    )
                    confirmation_gate.update(
                        {
                            "requires_user_confirmation": candidate_data[
                                "requires_user_confirmation"
                            ],
                            "quality_report_id": report.quality_report_id,
                            "semantic_check_status": embedded.get(
                                "semantic_check_status",
                                "not_run",
                            ),
                            "quality_degraded": bool(
                                embedded.get("quality_degraded")
                            ),
                        }
                    )
                    candidate_data["confirmation_gate"] = confirmation_gate
                    changed = True
                history.append(candidate_data)
            if changed:
                item["revision_history"] = history
            updated_scenes.append(item)
        self.repositories.scenes.write_all(updated_scenes)

    def _target_continuity_issue_ids(
        self,
        snapshot: ContinuityTargetStateSnapshot,
    ) -> set[str]:
        return {
            issue.issue_id
            for issue in snapshot.active_issues
        } | set(snapshot.resolved_issue_ids) | set(snapshot.dismissed_issue_ids)

    def _is_continuity_derived_issue(
        self,
        issue: QualityIssue,
        target_continuity_issue_ids: set[str],
    ) -> bool:
        return (
            issue.related_object_type == "continuity_issue"
            and bool(issue.related_object_id)
            and issue.related_object_id in target_continuity_issue_ids
        )

    def _summary(
        self,
        *,
        snapshot: ContinuityTargetStateSnapshot,
        preserved_blocking: list[QualityIssue],
        non_continuity_requires_confirmation: bool,
    ) -> str:
        notes = [snapshot.summary]
        if preserved_blocking:
            notes.append("Non-continuity quality blockers remain.")
        elif non_continuity_requires_confirmation:
            notes.append("Non-continuity quality confirmation needs remain.")
        return " ".join(text for text in notes if text)
