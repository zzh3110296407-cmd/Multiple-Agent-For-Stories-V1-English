from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.continuity import (
    ContinuityCheckResponse,
    ContinuityIssue,
    ContinuityResolutionRefreshResult,
    ContinuityTargetStateSnapshot,
)
from app.backend.models.quality import QualityReport
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.storage.json_store import JsonStore, StorageError


SHANGHAI_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ContinuityResolutionRefreshService:
    """Build continuity refresh payloads from stored state without re-running checks."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )

    def build_target_state_snapshot(
        self,
        target_type: str,
        target_id: str,
        *,
        scene_id: str = "",
        revision_id: str = "",
        mode: str = "manual",
    ) -> ContinuityTargetStateSnapshot:
        clean_target_type = target_type if target_type in {"scene", "scene_revision"} else "scene"
        clean_target_id = (target_id or scene_id or revision_id or "").strip()
        issues = self._issues_for_target(
            clean_target_type,
            clean_target_id,
            scene_id=scene_id,
            revision_id=revision_id,
        )
        open_issues = [issue for issue in issues if issue.status == "open"]
        accepted = [issue for issue in issues if issue.status == "accepted"]
        resolved = [issue for issue in issues if issue.status == "resolved"]
        dismissed = [issue for issue in issues if issue.status == "dismissed"]
        blocking = [
            issue
            for issue in open_issues
            if continuity_issue_blocks_mode(issue, mode)
        ]
        blocking_ids = {issue.issue_id for issue in blocking}
        warning = [
            issue
            for issue in open_issues
            if issue.issue_id not in blocking_ids
            and issue.severity in {"warning", "requires_user_confirmation"}
        ]
        requires_user_confirmation = bool(
            blocking
            or any(issue.requires_explicit_acceptance for issue in warning)
        )
        return ContinuityTargetStateSnapshot(
            target_type=clean_target_type,
            target_id=clean_target_id,
            scene_id=scene_id,
            revision_id=revision_id,
            mode=mode,
            active_issues=[*open_issues, *accepted],
            open_issues=open_issues,
            accepted_issue_ids=[issue.issue_id for issue in accepted],
            resolved_issue_ids=[issue.issue_id for issue in resolved],
            dismissed_issue_ids=[issue.issue_id for issue in dismissed],
            remaining_open_issue_ids=[issue.issue_id for issue in open_issues],
            remaining_blocking_issue_ids=[issue.issue_id for issue in blocking],
            remaining_warning_issue_ids=[issue.issue_id for issue in warning],
            continuity_passed=not blocking,
            requires_user_confirmation=requires_user_confirmation,
            summary=_summary(blocking, warning, accepted),
            refreshed_at=now_iso(),
        )

    def continuity_response_from_snapshot(
        self,
        snapshot: ContinuityTargetStateSnapshot,
    ) -> ContinuityCheckResponse:
        return ContinuityCheckResponse(
            success=True,
            target_type=snapshot.target_type,
            target_id=snapshot.target_id,
            mode=snapshot.mode,
            passed=snapshot.continuity_passed,
            continuity_passed=snapshot.continuity_passed,
            issues=snapshot.active_issues,
            blocking_issue_ids=snapshot.remaining_blocking_issue_ids,
            warning_issue_ids=snapshot.remaining_warning_issue_ids,
            accepted_issue_ids=snapshot.accepted_issue_ids,
            requires_user_confirmation=snapshot.requires_user_confirmation,
            summary=snapshot.summary,
        )

    def build_refresh_for_target(
        self,
        *,
        action_type: str,
        action_status: str,
        target_type: str,
        target_id: str,
        scene_id: str = "",
        revision_id: str = "",
        mode: str = "manual",
        affected_issue_ids: list[str] | None = None,
        recompute_quality_report: bool = False,
    ) -> ContinuityResolutionRefreshResult:
        clean_affected_issue_ids = _unique_strings(affected_issue_ids or [])
        snapshot = self.build_target_state_snapshot(
            target_type,
            target_id,
            scene_id=scene_id,
            revision_id=revision_id,
            mode=mode,
        )
        quality_report = self._latest_quality_report(snapshot.target_type, snapshot.target_id)
        if recompute_quality_report:
            from app.backend.services.quality_report_continuity_recompute_service import (
                QualityReportContinuityRecomputeService,
            )

            recomputed = QualityReportContinuityRecomputeService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
                refresh_service=self,
            ).recompute_for_snapshot(snapshot)
            if recomputed is not None:
                quality_report = recomputed
        affected_by_status = self._affected_issue_ids_by_status(clean_affected_issue_ids)
        return ContinuityResolutionRefreshResult(
            success=True,
            action_type=action_type,
            action_status=action_status,
            target_type=snapshot.target_type,
            target_id=snapshot.target_id,
            scene_id=snapshot.scene_id,
            revision_id=snapshot.revision_id,
            mode=snapshot.mode,
            affected_issue_ids=clean_affected_issue_ids,
            resolved_issue_ids=affected_by_status["resolved"],
            accepted_issue_ids=affected_by_status["accepted"],
            dismissed_issue_ids=affected_by_status["dismissed"],
            remaining_open_issue_ids=snapshot.remaining_open_issue_ids,
            remaining_blocking_issue_ids=snapshot.remaining_blocking_issue_ids,
            remaining_warning_issue_ids=snapshot.remaining_warning_issue_ids,
            refreshed_continuity_response=self.continuity_response_from_snapshot(snapshot),
            quality_report_id=quality_report.quality_report_id if quality_report else None,
            quality_report_snapshot=model_to_dict(quality_report) if quality_report else None,
            quality_report_recompute_required=(
                False if recompute_quality_report and quality_report is not None else True
            ),
            safe_summary=snapshot.summary,
            refreshed_at=snapshot.refreshed_at,
        )

    def build_refresh_after_issue_action(
        self,
        *,
        action_type: str,
        action_status: str,
        issue_id: str,
        affected_issue_ids: list[str] | None = None,
        mode: str = "manual",
        recompute_quality_report: bool = False,
    ) -> ContinuityResolutionRefreshResult:
        issue = self._issue(issue_id)
        return self.build_refresh_for_target(
            action_type=action_type,
            action_status=action_status,
            target_type=issue.target_type,
            target_id=issue.target_id,
            scene_id=issue.scene_id,
            revision_id=issue.revision_id,
            mode=mode,
            affected_issue_ids=affected_issue_ids or [issue.issue_id],
            recompute_quality_report=recompute_quality_report,
        )

    def _issues_for_target(
        self,
        target_type: str,
        target_id: str,
        *,
        scene_id: str = "",
        revision_id: str = "",
    ) -> list[ContinuityIssue]:
        issues: list[ContinuityIssue] = []
        for raw in self.repositories.continuity_issues.list_all():
            try:
                issue = ContinuityIssue(**raw)
            except ValidationError as exc:
                raise StorageError("ContinuityIssue JSON schema is invalid.") from exc
            if issue.target_type != target_type:
                continue
            if target_id and issue.target_id != target_id:
                continue
            if scene_id and issue.scene_id != scene_id:
                continue
            if revision_id and issue.revision_id != revision_id:
                continue
            issues.append(issue)
        return issues

    def _issue(self, issue_id: str) -> ContinuityIssue:
        raw = self.repositories.continuity_issues.get_by_id(issue_id)
        if raw is None:
            raise StorageError("CONTINUITY_ISSUE_MISSING: Continuity issue does not exist.")
        try:
            return ContinuityIssue(**raw)
        except ValidationError as exc:
            raise StorageError("ContinuityIssue JSON schema is invalid.") from exc

    def _affected_issue_ids_by_status(
        self,
        affected_issue_ids: list[str],
    ) -> dict[str, list[str]]:
        result = {
            "resolved": [],
            "accepted": [],
            "dismissed": [],
        }
        for issue_id in affected_issue_ids:
            raw = self.repositories.continuity_issues.get_by_id(issue_id)
            if raw is None:
                continue
            status = str(raw.get("status") or "")
            if status in result:
                result[status].append(issue_id)
        return result

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


def continuity_issue_blocks_mode(issue: ContinuityIssue, mode: str) -> bool:
    if issue.status in {"resolved", "accepted", "dismissed"}:
        return False
    if mode == "manual":
        return issue.severity == "blocking"
    if mode == "temporary_confirmation":
        return issue.category in {
            "forbidden_knowledge",
            "world_hard_rule_direct_conflict",
        } and issue.severity == "blocking"
    if mode == "revision_confirmation":
        return (
            issue.blocks_state_changing_revision_confirmation
            or issue.requires_explicit_acceptance
            or issue.severity in {"blocking", "requires_user_confirmation"}
        )
    return (
        issue.blocks_final_confirmation
        or issue.requires_explicit_acceptance
        or issue.severity in {"blocking", "requires_user_confirmation"}
    )


def _summary(
    blocking: list[ContinuityIssue],
    warning: list[ContinuityIssue],
    accepted: list[ContinuityIssue],
) -> str:
    if blocking:
        return f"Continuity state has {len(blocking)} open blocking issue(s)."
    if warning:
        return f"Continuity state has {len(warning)} open warning issue(s)."
    if accepted:
        return f"Continuity state has {len(accepted)} accepted issue(s) and no blockers."
    return "Continuity state has no open blocking issue."


def _unique_strings(values: list[Any]) -> list[str]:
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
