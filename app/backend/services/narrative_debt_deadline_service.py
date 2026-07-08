from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.narrative_layer import NarrativeDebt
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.storage.json_store import JsonStore


DEADLINE_TYPES = {"", "none", "within_current_chapter", "by_chapter", "by_scene"}
NO_PRESSURE_DEBT_STATUSES = {"paid_off", "rejected", "intentionally_open"}


@dataclass(frozen=True)
class NarrativeDebtDeadlineState:
    deadline_state: str = "none"
    deadline_warning: str = ""
    is_expired: bool = False


class NarrativeDebtDeadlineService:
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

    def derive_deadline_state(self, debt: NarrativeDebt) -> NarrativeDebtDeadlineState:
        if debt.status in NO_PRESSURE_DEBT_STATUSES or not debt.payoff_required:
            return NarrativeDebtDeadlineState()

        deadline_type = str(debt.payoff_deadline_type or "none").strip()
        if deadline_type not in DEADLINE_TYPES or deadline_type in {"", "none"}:
            return NarrativeDebtDeadlineState(
                deadline_state="ok",
                deadline_warning="该叙事债务需要 payoff，但尚未设置明确截止点。",
            )

        current_chapter = self._current_chapter()
        current_scene = self._current_scene(current_chapter)
        current_chapter_index = _safe_int((current_chapter or {}).get("chapter_index"))
        current_scene_index = _safe_int((current_scene or {}).get("scene_index"))

        if deadline_type == "within_current_chapter":
            source_chapter_index = self._chapter_index(debt.chapter_id)
            if (
                source_chapter_index
                and current_chapter_index
                and current_chapter_index > source_chapter_index
            ):
                return NarrativeDebtDeadlineState(
                    deadline_state="expired",
                    deadline_warning="该叙事债务要求在当前章节内 payoff，但当前进度已越过来源章节。",
                    is_expired=True,
                )
            return NarrativeDebtDeadlineState(
                deadline_state="due_soon",
                deadline_warning="该叙事债务要求在当前章节内 payoff。",
            )

        if deadline_type == "by_chapter":
            deadline_chapter_index = self._chapter_index(debt.payoff_deadline_chapter_id)
            if not deadline_chapter_index:
                return NarrativeDebtDeadlineState(
                    deadline_state="due_soon",
                    deadline_warning="该叙事债务设置了章节截止，但目标章节无法解析。",
                )
            if current_chapter_index and current_chapter_index > deadline_chapter_index:
                return NarrativeDebtDeadlineState(
                    deadline_state="expired",
                    deadline_warning="该叙事债务已超过章节 payoff 截止点。",
                    is_expired=True,
                )
            if current_chapter_index == deadline_chapter_index:
                return NarrativeDebtDeadlineState(
                    deadline_state="due_soon",
                    deadline_warning="该叙事债务已到达目标章节，需要关注 payoff。",
                )
            return NarrativeDebtDeadlineState(deadline_state="ok")

        if deadline_type == "by_scene":
            deadline_scene_index = debt.payoff_deadline_scene_index
            if deadline_scene_index is None:
                return NarrativeDebtDeadlineState(
                    deadline_state="due_soon",
                    deadline_warning="该叙事债务设置了场景截止，但缺少目标场景序号。",
                )
            deadline_chapter_index = (
                self._chapter_index(debt.payoff_deadline_chapter_id)
                if debt.payoff_deadline_chapter_id
                else self._chapter_index(debt.chapter_id)
            )
            if (
                deadline_chapter_index
                and current_chapter_index
                and current_chapter_index > deadline_chapter_index
            ):
                return NarrativeDebtDeadlineState(
                    deadline_state="expired",
                    deadline_warning="该叙事债务已超过场景 payoff 截止点。",
                    is_expired=True,
                )
            same_chapter = not deadline_chapter_index or current_chapter_index == deadline_chapter_index
            if same_chapter and current_scene_index > int(deadline_scene_index):
                return NarrativeDebtDeadlineState(
                    deadline_state="expired",
                    deadline_warning="该叙事债务已超过目标场景序号。",
                    is_expired=True,
                )
            if same_chapter and current_scene_index == int(deadline_scene_index):
                return NarrativeDebtDeadlineState(
                    deadline_state="due_soon",
                    deadline_warning="该叙事债务已到达目标场景，需要关注 payoff。",
                )
            return NarrativeDebtDeadlineState(deadline_state="ok")

        return NarrativeDebtDeadlineState(deadline_state="ok")

    def _current_chapter(self) -> dict[str, Any] | None:
        chapters = self.repositories.chapters.list_all()
        return (
            next((item for item in chapters if item.get("detail_level") == "current_chapter_brief"), None)
            or next((item for item in chapters if item.get("status") == "active"), None)
            or next((item for item in chapters if item.get("chapter_framework_id")), None)
            or (chapters[0] if chapters else None)
        )

    def _current_scene(self, current_chapter: dict[str, Any] | None) -> dict[str, Any] | None:
        chapter_id = str((current_chapter or {}).get("chapter_id") or "")
        scenes = [
            scene
            for scene in self.repositories.scenes.list_all()
            if not chapter_id or scene.get("chapter_id") == chapter_id
        ]
        if not scenes:
            return None
        return sorted(
            scenes,
            key=lambda scene: (
                _safe_int(scene.get("scene_index")),
                str(scene.get("updated_at") or scene.get("created_at") or ""),
            ),
            reverse=True,
        )[0]

    def _chapter_index(self, chapter_id: str) -> int:
        if not chapter_id:
            return 0
        for chapter in self.repositories.chapters.list_all():
            if str(chapter.get("chapter_id") or "") == chapter_id:
                return _safe_int(chapter.get("chapter_index"))
        return 0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
