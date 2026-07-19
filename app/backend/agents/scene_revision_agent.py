import json
import re
from typing import Any

from app.backend.prompts.scene_revision_prompts import (
    SCENE_REVISION_SYSTEM_PROMPT,
    build_scene_revision_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


REVISION_CONTEXT_STRING_LIMIT = 1600
REVISION_SOURCE_PROSE_LIMIT = 7000
REVISION_CONTEXT_LIST_LIMIT = 12
REVISION_CONTEXT_DEPTH_LIMIT = 5
REVISION_AGENT_MAX_OUTPUT_TOKENS = 2400
REVISION_AGENT_TIMEOUT_SECONDS = 120
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
REVISION_CONTEXT_KEYS = (
    "project_id",
    "output_language",
    "scene_index",
    "scene_count",
    "world_canvas",
    "characters",
    "allowed_revision_character_ids",
    "allowed_revision_characters",
    "relationships",
    "chapter",
    "current_chapter_framework",
    "recent_events",
    "memory_records",
    "scene_information",
    "current_scene",
    "revision_prompt",
    "revision_intent",
    "force_hard_rule_override",
    "output_safety_repair",
    "hard_rule_repair",
    "structured_repair_entry",
)


class SceneRevisionAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def revise_scene(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        compact_context = self._compact_revision_context(context)
        output_language = self._normalize_output_language(
            compact_context.get("output_language"),
        )
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": SCENE_REVISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_scene_revision_prompt(
                        context_json=json.dumps(
                            compact_context,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        output_language=output_language,
                    ),
                },
            ],
            schema_hint={
                "kind": "scene_revision",
                "scene_id": (compact_context.get("current_scene") or {}).get("scene_id"),
                "scene_index": compact_context.get("scene_index"),
                "output_language": output_language,
                "revision_prompt": context.get("revision_prompt") or "",
                "revision_intent": context.get("revision_intent") or "",
                "force_hard_rule_override": bool(
                    context.get("force_hard_rule_override")
                ),
            },
            options={
                "max_output_tokens": REVISION_AGENT_MAX_OUTPUT_TOKENS,
                "timeout_seconds": REVISION_AGENT_TIMEOUT_SECONDS,
                "max_attempts": 2,
                "temperature": 0.25,
            },
            service_name="SceneRevisionAgent",
            operation_name=(
                "revise_scene_safety_repair"
                if context.get("output_safety_repair")
                else "revise_scene"
            ),
        )
        return result.data

    def _compact_revision_context(self, context: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in REVISION_CONTEXT_KEYS:
            if key not in context:
                continue
            value = context.get(key)
            if key == "current_scene" and isinstance(value, dict):
                compact[key] = self._compact_current_scene(value)
            elif key in {"recent_events", "memory_records"} and isinstance(value, list):
                compact[key] = self._compact_json_value(value[-8:])
            elif key == "characters" and isinstance(value, list):
                compact[key] = [
                    self._compact_character(item)
                    for item in value[:REVISION_CONTEXT_LIST_LIMIT]
                    if isinstance(item, dict)
                ]
            elif key == "world_canvas" and isinstance(value, dict):
                compact[key] = self._compact_world_canvas(value)
            else:
                compact[key] = self._compact_json_value(value)
        compact.setdefault("output_language", "zh")
        return compact

    def _compact_current_scene(self, scene: dict[str, Any]) -> dict[str, Any]:
        compact = {
            key: scene.get(key)
            for key in (
                "scene_id",
                "chapter_id",
                "scene_index",
                "status",
                "location",
                "story_time",
                "goal",
                "synopsis",
                "prose_text",
                "linked_character_ids",
                "linked_relationship_ids",
                "quality_report",
            )
            if key in scene
        }
        content = scene.get("content")
        if isinstance(content, dict):
            compact["content"] = {
                "synopsis": content.get("synopsis"),
                "prose_text": content.get("prose_text"),
            }
        for container_key in ("prose_text",):
            if isinstance(compact.get(container_key), str):
                compact[container_key] = compact[container_key][:REVISION_SOURCE_PROSE_LIMIT]
        if isinstance(compact.get("content"), dict):
            prose = compact["content"].get("prose_text")
            if isinstance(prose, str):
                compact["content"]["prose_text"] = prose[:REVISION_SOURCE_PROSE_LIMIT]
        return self._compact_json_value(compact, preserve_long_strings=True)

    def _compact_character(self, character: dict[str, Any]) -> dict[str, Any]:
        profile = character.get("profile") if isinstance(character.get("profile"), dict) else {}
        current_state = (
            character.get("current_state")
            if isinstance(character.get("current_state"), dict)
            else {}
        )
        return self._compact_json_value(
            {
                "character_id": character.get("character_id"),
                "name": character.get("name"),
                "tier": character.get("tier"),
                "role": character.get("role"),
                "profile": {
                    "identity": profile.get("identity"),
                    "story_function": profile.get("story_function"),
                    "traits": profile.get("traits"),
                    "goals": profile.get("goals"),
                    "hard_limits": profile.get("hard_limits"),
                    "knowledge_scope": profile.get("knowledge_scope"),
                    "forbidden_knowledge": profile.get("forbidden_knowledge"),
                },
                "current_state": {
                    "emotional_state": current_state.get("emotional_state"),
                    "knowledge": current_state.get("knowledge"),
                    "active_goal": current_state.get("active_goal"),
                    "resources": current_state.get("resources"),
                },
            }
        )

    def _compact_world_canvas(self, canvas: dict[str, Any]) -> dict[str, Any]:
        return self._compact_json_value(
            {
                key: canvas.get(key)
                for key in (
                    "world_canvas_id",
                    "title",
                    "scope",
                    "tone",
                    "world_structure",
                    "geography",
                    "culture",
                    "history",
                    "hard_rules",
                    "soft_rules",
                    "unknown_rules",
                )
                if key in canvas
            }
        )

    def _compact_json_value(
        self,
        value: Any,
        depth: int = 0,
        *,
        preserve_long_strings: bool = False,
    ) -> Any:
        if depth >= REVISION_CONTEXT_DEPTH_LIMIT:
            if isinstance(value, dict):
                return {"summary": "nested context omitted"}
            if isinstance(value, list):
                return ["nested context omitted"]
        if isinstance(value, dict):
            return {
                str(key): self._compact_json_value(
                    item,
                    depth + 1,
                    preserve_long_strings=preserve_long_strings,
                )
                for key, item in list(value.items())[:REVISION_CONTEXT_LIST_LIMIT]
            }
        if isinstance(value, list):
            return [
                self._compact_json_value(
                    item,
                    depth + 1,
                    preserve_long_strings=preserve_long_strings,
                )
                for item in value[:REVISION_CONTEXT_LIST_LIMIT]
            ]
        if isinstance(value, str) and not preserve_long_strings:
            return value[:REVISION_CONTEXT_STRING_LIMIT]
        return value

    def _normalize_output_language(self, value: Any) -> str:
        language = str(value or "zh").strip().lower()
        return "en" if language.startswith("en") else "zh"
