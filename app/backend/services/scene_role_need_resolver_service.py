from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.scene_participants import SceneRoleFunctionNeedRef
from app.backend.storage.json_store import JsonStore


class SceneRoleNeedResolverService:
    """Resolves M2 C/D function needs that apply to a scene."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir

    def resolve_for_scene(
        self,
        *,
        chapter: Chapter,
        scene_index: int,
        scene_goal: str = "",
        scene_location: str = "",
        previous_scene_result: str = "",
    ) -> list[SceneRoleFunctionNeedRef]:
        exact: list[SceneRoleFunctionNeedRef] = []
        contextual: list[SceneRoleFunctionNeedRef] = []
        generic: list[SceneRoleFunctionNeedRef] = []
        query_text = " ".join([scene_goal, scene_location, previous_scene_result]).casefold()
        for raw_need in chapter.cd_role_function_needs:
            if not isinstance(raw_need, dict):
                continue
            need = self._normalize_need(chapter, raw_need)
            if need.scene_index == int(scene_index):
                exact.append(need)
                continue
            if need.scene_index is None:
                generic.append(need)
                if self._matches_scene_text(need, query_text):
                    contextual.append(need)
        if exact:
            return self._unique_by_source_need_id(exact)
        if contextual:
            return self._unique_by_source_need_id(contextual)
        return self._unique_by_source_need_id(generic)

    def _normalize_need(
        self,
        chapter: Chapter,
        raw_need: dict[str, Any],
    ) -> SceneRoleFunctionNeedRef:
        source_need_id = str(raw_need.get("need_id") or raw_need.get("source_need_id") or "").strip()
        if not source_need_id:
            source_need_id = f"{chapter.chapter_id}_cd_need_{len(str(raw_need))}"
        raw_scene_index = raw_need.get("scene_index")
        try:
            scene_index = int(raw_scene_index) if raw_scene_index not in {None, ""} else None
        except (TypeError, ValueError):
            scene_index = None
        return SceneRoleFunctionNeedRef(
            need_ref_id=f"need_ref_{chapter.chapter_id}_{source_need_id}",
            source_need_id=source_need_id,
            project_id=chapter.project_id,
            chapter_id=chapter.chapter_id,
            scene_index=scene_index,
            tier_preference=str(raw_need.get("tier_preference") or "C_or_D"),
            function_type=str(raw_need.get("function_type") or "other"),
            function_summary=str(raw_need.get("function_summary") or ""),
            reason=str(raw_need.get("reason") or ""),
            location_hint=str(raw_need.get("location_hint") or ""),
            relationship_hint=str(raw_need.get("relationship_hint") or ""),
            knowledge_need=str(raw_need.get("knowledge_need") or ""),
            reuse_existing_preferred=bool(raw_need.get("reuse_existing_preferred", True)),
        )

    def _matches_scene_text(
        self,
        need: SceneRoleFunctionNeedRef,
        query_text: str,
    ) -> bool:
        if not query_text.strip():
            return False
        for text in [
            need.function_type,
            need.function_summary,
            need.reason,
            need.location_hint,
            need.relationship_hint,
            need.knowledge_need,
        ]:
            for token in _meaningful_tokens(text):
                if token in query_text:
                    return True
        return False

    def _unique_by_source_need_id(
        self,
        needs: list[SceneRoleFunctionNeedRef],
    ) -> list[SceneRoleFunctionNeedRef]:
        result: list[SceneRoleFunctionNeedRef] = []
        seen: set[str] = set()
        for need in needs:
            if need.source_need_id in seen:
                continue
            seen.add(need.source_need_id)
            result.append(need)
        return result


def _meaningful_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in str(text or "").casefold().replace("_", " ").split():
        clean = "".join(ch for ch in token if ch.isalnum())
        if len(clean) >= 3:
            tokens.append(clean)
    return tokens
