from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import SceneProgressResponse
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.storage.json_store import JsonStore, StorageError


COMMITTED_SCENE_STATUSES = {"confirmed", "committed", "revised"}
NEXT_READY_SCENE_STATUSES = {
    "confirmed",
    "committed",
    "revised",
    "temporary_confirmed",
}
BLOCKING_SCENE_STATUSES = {
    "draft",
    "needs_review",
    "needs_regeneration",
    "continuity_recheck",
}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class SceneProgressService:
    def __init__(
        self,
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

    def get_progress(self, chapter_id: str | None = None) -> SceneProgressResponse:
        chapters = self._read_chapters()
        chapter = self._select_current_chapter(chapters, chapter_id)
        if chapter is None:
            return SceneProgressResponse(
                blocking_reason_codes=["current_chapter_missing"],
                blocking_reasons=["当前章不存在，无法计算场景进度。"],
            )

        scenes = self._read_scenes(chapter.chapter_id)
        scene_count = max(0, int(chapter.scene_count or 0))
        scene_by_index = {
            scene.scene_index: scene
            for scene in scenes
            if scene.scene_index >= 1
        }
        sorted_scenes = sorted(scenes, key=lambda scene: scene.scene_index)
        next_scene_index = self._next_scene_index(scene_by_index, scene_count)
        blocking_reasons: list[str] = []
        blocking_reason_codes: list[str] = []
        dependency_warnings = self._dependency_warnings(sorted_scenes)
        pending_major_changes = self._pending_a_tier_major_changes()
        if pending_major_changes:
            blocking_reason_codes.append("pending_major_state_changes")
            blocking_reasons.append(
                "仍有 A-tier 角色重大长期状态变更等待确认，不能生成下一幕。"
            )

        if scene_count < 1:
            blocking_reason_codes.append("scene_count_missing")
            blocking_reasons.append("当前章还没有设置 scene_count。")
        elif next_scene_index > scene_count:
            blocking_reason_codes.append("scene_count_reached")
            blocking_reasons.append("当前章已达到 scene_count，不能继续生成下一幕。")
        elif next_scene_index == 1:
            if scene_by_index.get(1) is None:
                pass
            elif scene_by_index[1].status in BLOCKING_SCENE_STATUSES:
                blocking_reason_codes.append("current_scene_draft_exists")
                blocking_reasons.append("第 1 幕仍未提交，不能继续推进。")
            else:
                blocking_reason_codes.append("first_scene_exists")
                blocking_reasons.append("第 1 幕已存在，请使用顺序下一幕入口。")
        else:
            previous = scene_by_index.get(next_scene_index - 1)
            if previous is None:
                blocking_reason_codes.append("previous_scene_missing")
                blocking_reasons.append(
                    f"第 {next_scene_index - 1} 幕不存在，不能跳幕生成。"
                )
            elif previous.status not in NEXT_READY_SCENE_STATUSES:
                blocking_reason_codes.append("previous_scene_not_committed")
                blocking_reasons.append(
                    f"第 {next_scene_index - 1} 幕状态为 {previous.status}，需要先正式确认或临时确认。"
                )
            existing_next = scene_by_index.get(next_scene_index)
            if existing_next and existing_next.status in BLOCKING_SCENE_STATUSES:
                blocking_reason_codes.append("current_scene_draft_exists")
                blocking_reasons.append(
                    f"第 {next_scene_index} 幕已有未提交草稿，需要先处理该草稿。"
                )
            elif existing_next and existing_next.status in NEXT_READY_SCENE_STATUSES:
                blocking_reason_codes.append("current_scene_already_committed")
                blocking_reasons.append(
                    f"第 {next_scene_index} 幕已经提交，不能覆盖。"
                )

        completion_status = self._completion_status(
            scene_count=scene_count,
            scene_by_index=scene_by_index,
            sorted_scenes=sorted_scenes,
        )
        can_generate_next = (
            scene_count >= 1
            and next_scene_index <= scene_count
            and not blocking_reasons
        )
        return SceneProgressResponse(
            chapter_id=chapter.chapter_id,
            scene_count=scene_count,
            next_scene_index=next_scene_index,
            can_generate_next=can_generate_next,
            completion_status=completion_status,
            scenes=[model_to_dict(scene) for scene in sorted_scenes],
            blocking_reasons=self._unique(blocking_reasons),
            blocking_reason_codes=self._unique(blocking_reason_codes),
            dependency_warnings=dependency_warnings,
        )

    def _next_scene_index(
        self,
        scene_by_index: dict[int, Scene],
        scene_count: int,
    ) -> int:
        if scene_count < 1:
            return 1
        for index in range(1, scene_count + 1):
            scene = scene_by_index.get(index)
            if scene is None:
                return index
            if scene.status in BLOCKING_SCENE_STATUSES:
                return index
        return scene_count + 1

    def _completion_status(
        self,
        *,
        scene_count: int,
        scene_by_index: dict[int, Scene],
        sorted_scenes: list[Scene],
    ) -> str:
        if not sorted_scenes:
            return "not_started"
        if scene_count < 1:
            return "in_progress"
        required = [scene_by_index.get(index) for index in range(1, scene_count + 1)]
        if any(scene is None for scene in required):
            return "in_progress"
        concrete = [scene for scene in required if scene is not None]
        if any(scene.status in BLOCKING_SCENE_STATUSES for scene in concrete):
            return "in_progress"
        if any(
            scene.status == "temporary_confirmed"
            or scene.is_provisional
            or scene.depends_on_provisional_scene_ids
            or scene.depends_on_provisional_memory_ids
            for scene in concrete
        ):
            return "provisional_complete"
        if all(scene.status in COMMITTED_SCENE_STATUSES for scene in concrete):
            return "final_complete"
        return "in_progress"

    def _dependency_warnings(self, scenes: list[Scene]) -> list[str]:
        warnings: list[str] = []
        for scene in scenes:
            if scene.status == "temporary_confirmed" or scene.is_provisional:
                warnings.append(f"第 {scene.scene_index} 幕仍是临时确认状态。")
            if scene.depends_on_provisional_scene_ids:
                warnings.append(
                    f"第 {scene.scene_index} 幕依赖临时场景："
                    + " / ".join(scene.depends_on_provisional_scene_ids)
                )
            if scene.depends_on_provisional_memory_ids:
                warnings.append(
                    f"第 {scene.scene_index} 幕依赖临时记忆："
                    + " / ".join(scene.depends_on_provisional_memory_ids)
                )
            if scene.needs_review_reason:
                warnings.append(f"第 {scene.scene_index} 幕需要复核：{scene.needs_review_reason}")
        return self._unique(warnings)

    def _pending_a_tier_major_changes(self) -> list[dict[str, Any]]:
        return [
            change
            for change in self.repositories.pending_character_state_changes.list_all()
            if str(change.get("status") or "").strip() == "pending"
            and str(change.get("tier") or "").strip().upper() == "A"
            and str(change.get("impact_level") or "").strip().lower() == "major"
        ]

    def _read_chapters(self) -> list[Chapter]:
        try:
            return [
                Chapter(**item)
                for item in self.repositories.chapters.list_all()
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("Chapters JSON schema is invalid.") from exc

    def _read_scenes(self, chapter_id: str) -> list[Scene]:
        scenes: list[Scene] = []
        try:
            for item in self.repositories.scenes.list_all():
                if not isinstance(item, dict) or item.get("chapter_id") != chapter_id:
                    continue
                scenes.append(Scene(**item))
        except ValidationError as exc:
            raise StorageError("Scene JSON schema is invalid.") from exc
        return scenes

    def _select_current_chapter(
        self,
        chapters: list[Chapter],
        chapter_id: str | None = None,
    ) -> Chapter | None:
        if chapter_id:
            return next((chapter for chapter in chapters if chapter.chapter_id == chapter_id), None)
        return (
            next((chapter for chapter in chapters if chapter.detail_level == "current_chapter_brief"), None)
            or next((chapter for chapter in chapters if chapter.status == "active"), None)
            or next((chapter for chapter in chapters if chapter.chapter_framework_id and chapter.scene_count >= 1), None)
        )

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
