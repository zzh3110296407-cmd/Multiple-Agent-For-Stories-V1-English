from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.continuity import ContinuityIssue
from app.backend.models.quality import QualityReport
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import SceneQualityReport
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.continuity_resolution_refresh_service import (
    ContinuityResolutionRefreshService,
    continuity_issue_blocks_mode,
)
from app.backend.storage.json_store import JsonStore, StorageError


SHANGHAI_TZ = timezone(timedelta(hours=8))
FINAL_RELEASE_MODES = {
    "final_confirmation",
    "chapter_archive",
    "story_draft_complete",
    "final_story_package_export",
    "release",
}


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def model_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return {}


class SceneGateReadinessService:
    """Single release/confirmation contract for scene quality and continuity gates."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        continuity_refresh_service: ContinuityResolutionRefreshService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.continuity_refresh_service = continuity_refresh_service or (
            ContinuityResolutionRefreshService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )

    def evaluate(
        self,
        scene_id: str,
        *,
        mode: str = "final_confirmation",
    ) -> dict[str, Any]:
        clean_scene_id = str(scene_id or "").strip()
        scene = self._scene(clean_scene_id)
        quality_report = self._latest_quality_report(scene)
        continuity = self._continuity_state(scene, mode=mode)

        quality_blocking_ids, quality_user_action_ids, quality_reason_codes = (
            self._quality_gate_state(quality_report)
        )
        blocking_issue_ids = self._unique(
            [*quality_blocking_ids, *continuity["blocking_issue_ids"]]
        )
        user_action_issue_ids = self._unique(
            [*quality_user_action_ids, *continuity["user_action_issue_ids"]]
        )
        non_blocking_issue_ids = self._unique(continuity["non_blocking_issue_ids"])

        prose_ready = bool(str(scene.get("prose_text") or "").strip())
        quality_passed = bool(quality_report.get("passed")) and not (
            quality_blocking_ids or quality_user_action_ids
        )
        continuity_passed = not (
            continuity["blocking_issue_ids"] or continuity["user_action_issue_ids"]
        )
        reason_codes = self._unique(
            [
                "scene_prose_missing" if not prose_ready else "",
                *quality_reason_codes,
                *continuity["reason_codes"],
            ]
        )
        safe = bool(
            prose_ready
            and quality_passed
            and continuity_passed
            and not blocking_issue_ids
            and not user_action_issue_ids
        )

        return {
            "schema_version": "phase85_system_resilience_scene_gate_readiness_v1",
            "scene_id": clean_scene_id,
            "scene_status": str(scene.get("status") or ""),
            "prose_ready": prose_ready,
            "quality_passed": quality_passed,
            "continuity_passed": continuity_passed,
            "safe_to_release": safe,
            "safe_to_confirm": safe,
            "requires_user_action": bool(user_action_issue_ids or blocking_issue_ids),
            "open_blocking_issue_count": len(blocking_issue_ids),
            "open_user_action_issue_count": len(user_action_issue_ids),
            "open_non_blocking_issue_count": len(non_blocking_issue_ids),
            "latest_quality_report_id": str(
                quality_report.get("quality_report_id") or ""
            ),
            "latest_continuity_run_id": continuity["latest_continuity_run_id"],
            "blocking_issue_ids": blocking_issue_ids,
            "user_action_issue_ids": user_action_issue_ids,
            "non_blocking_issue_ids": non_blocking_issue_ids,
            "reason_codes": reason_codes,
            "checked_at": now_iso(),
        }

    def require_safe_to_confirm(
        self,
        scene_id: str,
        *,
        mode: str = "final_confirmation",
        boundary_code: str = "SCENE_GATE_READINESS_BLOCKED",
    ) -> dict[str, Any]:
        readiness = self.evaluate(scene_id, mode=mode)
        if readiness.get("safe_to_confirm") is True:
            return readiness
        reasons = ", ".join(readiness.get("reason_codes") or []) or "scene_gate_not_ready"
        raise StorageError(f"{boundary_code}: {reasons}")

    def require_scenes_safe_to_release(
        self,
        scene_ids: list[Any],
        *,
        boundary_code: str,
        mode: str = "release",
    ) -> list[dict[str, Any]]:
        results = []
        blocked: list[str] = []
        for scene_id in self._unique(scene_ids):
            readiness = self.evaluate(scene_id, mode=mode)
            results.append(readiness)
            if readiness.get("safe_to_release") is not True:
                reasons = ",".join(readiness.get("reason_codes") or [])
                blocked.append(f"{scene_id}({reasons or 'scene_gate_not_ready'})")
        if blocked:
            raise StorageError(f"{boundary_code}: {'; '.join(blocked)}")
        return results

    def _scene(self, scene_id: str) -> dict[str, Any]:
        raw = self.repositories.scenes.get_by_id(scene_id)
        if raw is None:
            raise StorageError(f"SCENE_GATE_READINESS_SCENE_MISSING: {scene_id}")
        try:
            return model_to_dict(Scene(**raw))
        except Exception:
            if isinstance(raw, dict):
                return dict(raw)
            raise StorageError("SCENE_GATE_READINESS_SCENE_SCHEMA_INVALID")

    def _latest_quality_report(self, scene: dict[str, Any]) -> dict[str, Any]:
        scene_id = str(scene.get("scene_id") or "")
        report_id = str(scene.get("quality_report_id") or "").strip()
        matches: list[dict[str, Any]] = []
        for raw in self.repositories.quality_reports.list_all():
            if not isinstance(raw, dict):
                continue
            if str(raw.get("target_type") or "") != "scene":
                continue
            if str(raw.get("target_id") or raw.get("scene_id") or "") != scene_id:
                continue
            matches.append(raw)
        if report_id:
            for raw in reversed(matches):
                if str(raw.get("quality_report_id") or "") == report_id:
                    return self._quality_report_dict(raw)
        if matches:
            return self._quality_report_dict(matches[-1])
        embedded = model_to_dict(scene.get("quality_report"))
        if embedded:
            return self._embedded_quality_report_dict(embedded)
        return {}

    def _quality_report_dict(self, raw: dict[str, Any]) -> dict[str, Any]:
        try:
            return model_to_dict(QualityReport(**raw))
        except Exception:
            return dict(raw)

    def _embedded_quality_report_dict(self, raw: dict[str, Any]) -> dict[str, Any]:
        try:
            return model_to_dict(SceneQualityReport(**raw))
        except Exception:
            return dict(raw)

    def _quality_gate_state(
        self,
        report: dict[str, Any],
    ) -> tuple[list[str], list[str], list[str]]:
        if not report:
            return [], [], ["quality_report_missing"]
        blocking_ids = self._quality_issue_ids(
            report.get("blocking_issues"),
            fallback_prefix="quality_blocking_issue",
        )
        user_action_ids: list[str] = []
        reason_codes: list[str] = []
        if blocking_ids:
            reason_codes.append("quality_blocking_issues")
        if bool(report.get("requires_user_confirmation")):
            user_action_ids.append(
                str(report.get("quality_report_id") or "quality_requires_user_confirmation")
            )
            reason_codes.append("quality_requires_user_confirmation")
        if not bool(report.get("passed")):
            reason_codes.append("quality_not_passed")
        return blocking_ids, self._unique(user_action_ids), self._unique(reason_codes)

    def _quality_issue_ids(self, issues: Any, *, fallback_prefix: str) -> list[str]:
        result: list[str] = []
        for index, issue in enumerate(issues if isinstance(issues, list) else []):
            if isinstance(issue, dict):
                result.append(str(issue.get("issue_id") or issue.get("message") or ""))
            else:
                result.append(str(issue or ""))
            if not result[-1]:
                result[-1] = f"{fallback_prefix}_{index + 1}"
        return self._unique(result)

    def _continuity_state(self, scene: dict[str, Any], *, mode: str) -> dict[str, Any]:
        scene_id = str(scene.get("scene_id") or "")
        latest_run_id = str(
            model_to_dict(scene.get("quality_report")).get("continuity_gate_run_id")
            or ""
        )
        try:
            snapshot = self.continuity_refresh_service.build_target_state_snapshot(
                "scene",
                scene_id,
                scene_id=scene_id,
                mode=mode,
            )
        except Exception:
            snapshot = None

        blocking_ids: list[str] = []
        user_action_ids: list[str] = []
        non_blocking_ids: list[str] = []
        reason_codes: list[str] = []
        for issue in self._continuity_issues_for_scene(scene_id):
            if issue.status != "open":
                continue
            if not latest_run_id and issue.updated_at:
                latest_run_id = str(issue.updated_at)
            if self._issue_requires_user_action(issue, mode=mode):
                user_action_ids.append(issue.issue_id)
                continue
            if continuity_issue_blocks_mode(issue, mode):
                blocking_ids.append(issue.issue_id)
                continue
            non_blocking_ids.append(issue.issue_id)
        if blocking_ids:
            reason_codes.append("continuity_blocking_issues")
        if user_action_ids:
            reason_codes.append("continuity_requires_user_action")
        if snapshot is not None and not latest_run_id:
            latest_run_id = str(getattr(snapshot, "refreshed_at", "") or "")
        if not latest_run_id:
            reason_codes.append("continuity_run_evidence_missing")
        return {
            "blocking_issue_ids": self._unique(blocking_ids),
            "user_action_issue_ids": self._unique(user_action_ids),
            "non_blocking_issue_ids": self._unique(non_blocking_ids),
            "latest_continuity_run_id": latest_run_id,
            "reason_codes": self._unique(reason_codes),
        }

    def _continuity_issues_for_scene(self, scene_id: str) -> list[ContinuityIssue]:
        issues: list[ContinuityIssue] = []
        for raw in self.repositories.continuity_issues.list_all():
            if not isinstance(raw, dict):
                continue
            if str(raw.get("target_type") or "scene") != "scene":
                continue
            if str(raw.get("target_id") or raw.get("scene_id") or "") != scene_id:
                continue
            try:
                issues.append(ContinuityIssue(**raw))
            except Exception as exc:
                raise StorageError("ContinuityIssue JSON schema is invalid.") from exc
        return issues

    def _issue_requires_user_action(self, issue: ContinuityIssue, *, mode: str) -> bool:
        if issue.status != "open":
            return False
        if issue.requires_explicit_acceptance:
            return True
        if issue.severity == "requires_user_confirmation":
            return mode in FINAL_RELEASE_MODES or mode == "revision_confirmation"
        return False

    def _unique(self, values: list[Any]) -> list[str]:
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
