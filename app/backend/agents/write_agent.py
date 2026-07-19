import json
import re
from typing import Any

from app.backend.prompts.scene_generation_prompts import (
    WRITE_AGENT_SYSTEM_PROMPT,
    build_write_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


WRITE_CONTEXT_STRING_LIMIT = 1200
WRITE_CONTEXT_LIST_LIMIT = 12
WRITE_CONTEXT_DEPTH_LIMIT = 5
WRITE_AGENT_MAX_OUTPUT_TOKENS = 2200
WRITE_AGENT_TIMEOUT_SECONDS = 90
WRITE_AGENT_MAX_ATTEMPTS = 2
WRITE_CONTEXT_REQUIRED_KEYS = (
    "project_id",
    "output_language",
    "chapter_id",
    "scene_id",
    "scene_index",
    "scene_count",
    "project_intent_summary",
    "project_story_premise",
    "prompt_fidelity_contract",
    "world_canvas",
    "characters",
    "relationships",
    "chapter",
    "current_chapter_framework",
    "scene_writing_context",
    "scene_progression_statement",
    "scene_information",
    "authorial_intent",
    "m12_context_pack",
)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
SCENE_WRITING_CONTEXT_KEYS = (
    "project_id",
    "chapter_id",
    "scene_id",
    "scene_index",
    "scene_count",
    "chapter_goal",
    "current_chapter_brief_summary",
    "chapter_scene_beat",
    "chapter_scene_beat_history",
    "resolved_scene_goal",
    "previous_scene_summary",
    "confirmed_scene_summaries",
    "chapter_state_so_far",
    "selected_abcd_participants",
    "scene_participation_package",
    "tiered_character_context_package",
    "tiered_character_intent_package",
    "scene_memory_pack",
    "authorial_intent",
    "forbidden_repetition_patterns",
    "source_refs",
)


class WriteAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def write_scene(
        self,
        ordered_story_information_package: dict[str, Any],
        approved_context: dict[str, Any],
    ) -> dict[str, Any]:
        compact_ordered_package = self._compact_json_value(
            ordered_story_information_package,
        )
        compact_context = self._compact_approved_context(approved_context)
        output_language = self._normalize_output_language(
            compact_context.get("output_language"),
        )
        prompt = build_write_prompt(
            ordered_package_json=json.dumps(
                compact_ordered_package,
                ensure_ascii=False,
                indent=2,
            ),
            approved_context_json=json.dumps(
                compact_context,
                ensure_ascii=False,
                indent=2,
            ),
            output_language=output_language,
        )
        messages = [
            {"role": "system", "content": WRITE_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = self.model_gateway.generate_json(
            messages=messages,
            schema_hint={
                "kind": "scene_write",
                "scene_index": approved_context.get("scene_index"),
                "ordered_story_information_package": compact_ordered_package,
                "approved_context": compact_context,
            },
            options={
                "max_output_tokens": WRITE_AGENT_MAX_OUTPUT_TOKENS,
                "timeout_seconds": WRITE_AGENT_TIMEOUT_SECONDS,
                "max_attempts": WRITE_AGENT_MAX_ATTEMPTS,
            },
            service_name="WriteAgent",
            operation_name="write_scene",
        )
        if not self._matches_output_language(result.data, output_language):
            result = self.model_gateway.generate_json(
                messages=[
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Your previous JSON used the wrong story language. "
                            + (
                                "Return the same scene as valid JSON, but rewrite both synopsis "
                                "and prose_text entirely in English."
                                if output_language == "en"
                                else "Return the same scene as valid JSON, but rewrite both synopsis "
                                "and prose_text entirely in Simplified Chinese."
                            )
                            + " Do not add or remove story facts."
                        ),
                    },
                ],
                schema_hint={
                    "kind": "scene_write",
                    "operation": "language_retry",
                    "output_language": output_language,
                    "scene_index": approved_context.get("scene_index"),
                },
                options={
                    "max_output_tokens": WRITE_AGENT_MAX_OUTPUT_TOKENS,
                    "timeout_seconds": WRITE_AGENT_TIMEOUT_SECONDS,
                    "max_attempts": 1,
                    "temperature": 0.2,
                },
                service_name="WriteAgent",
                operation_name="write_scene_language_retry",
            )
        return result.data

    def _normalize_output_language(self, value: Any) -> str:
        language = str(value or "zh").strip().lower()
        return "en" if language.startswith("en") else "zh"

    def _matches_output_language(
        self,
        data: dict[str, Any],
        output_language: str,
    ) -> bool:
        text = " ".join(
            str(data.get(key) or "")
            for key in ("synopsis", "prose_text")
        ).strip()
        if not text:
            return False
        cjk_count = len(CJK_RE.findall(text))
        latin_count = len(LATIN_RE.findall(text))
        if output_language == "en":
            return latin_count >= 40 and latin_count >= cjk_count * 2
        return cjk_count >= 24 and cjk_count >= latin_count

    def _compact_approved_context(self, approved_context: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in WRITE_CONTEXT_REQUIRED_KEYS:
            if key not in approved_context:
                continue
            value = approved_context.get(key)
            if key == "scene_writing_context" and isinstance(value, dict):
                compact[key] = self._compact_scene_writing_context(value)
            elif key == "m12_context_pack" and isinstance(value, dict):
                compact[key] = self._compact_m12_context_pack(value)
            elif key == "characters":
                compact[key] = self._compact_characters(value)
            elif key == "relationships":
                compact[key] = self._compact_relationships(value)
            elif key == "world_canvas":
                compact[key] = self._compact_world_canvas(value)
            else:
                compact[key] = self._compact_json_value(value)
        return compact

    def _compact_m12_context_pack(self, value: dict[str, Any]) -> dict[str, Any]:
        return self._compact_json_value(
            {
                "context_pack_id": value.get("context_pack_id"),
                "query_intent_id": value.get("query_intent_id"),
                "query_orchestration_run_id": value.get("query_orchestration_run_id"),
                "project_id": value.get("project_id"),
                "runtime_scene_generation_consumed": value.get("runtime_scene_generation_consumed"),
                "raw_candidates_consumed": value.get("raw_candidates_consumed"),
                "raw_retrieval_rows_consumed": value.get("raw_retrieval_rows_consumed"),
                "writer_agent_receives_gated_context_only": value.get("writer_agent_receives_gated_context_only"),
                "sections": value.get("sections"),
                "agent_consumers": value.get("agent_consumers"),
                "source_refs": value.get("source_refs"),
            }
        )

    def _compact_scene_writing_context(self, value: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in SCENE_WRITING_CONTEXT_KEYS:
            if key not in value:
                continue
            item = value.get(key)
            if key in {"confirmed_scene_summaries", "chapter_scene_beat_history"}:
                item = self._tail_list(item, 5)
            elif key in {"forbidden_repetition_patterns", "source_refs"}:
                item = self._tail_list(item, 10)
            compact[key] = self._compact_json_value(item)
        return compact

    def _compact_characters(self, value: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self._as_list(value)[:WRITE_CONTEXT_LIST_LIMIT]:
            if not isinstance(item, dict):
                continue
            result.append(
                self._compact_json_value(
                    {
                        "character_id": item.get("character_id"),
                        "name": item.get("name"),
                        "tier": item.get("tier"),
                        "role": item.get("role"),
                        "story_function": item.get("story_function"),
                        "identity": item.get("identity"),
                        "active_goal": item.get("active_goal"),
                        "current_desire": item.get("current_desire"),
                        "current_fear": item.get("current_fear"),
                        "hard_limits": item.get("hard_limits"),
                    }
                )
            )
        return result

    def _compact_relationships(self, value: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self._as_list(value)[:WRITE_CONTEXT_LIST_LIMIT]:
            if not isinstance(item, dict):
                continue
            result.append(
                self._compact_json_value(
                    {
                        "relationship_id": item.get("relationship_id"),
                        "source_character_id": item.get("source_character_id"),
                        "target_character_id": item.get("target_character_id"),
                        "relationship_type": item.get("relationship_type"),
                        "summary": item.get("summary"),
                        "status": item.get("status"),
                    }
                )
            )
        return result

    def _compact_world_canvas(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return self._compact_json_value(
            {
                "story_direction": value.get("story_direction"),
                "scope": value.get("scope"),
                "tone": value.get("tone"),
                "world_structure": value.get("world_structure"),
                "history": value.get("history"),
                "geography": value.get("geography"),
                "culture": value.get("culture"),
                "hard_rules": self._as_list(value.get("hard_rules"))[:10],
                "soft_rules": self._as_list(value.get("soft_rules"))[:10],
                "special_rules": self._as_list(value.get("special_rules"))[:10],
            }
        )

    def _compact_json_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth > WRITE_CONTEXT_DEPTH_LIMIT:
            return self._compact_leaf(value)
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 80:
                    compact["_truncated_keys"] = len(value) - index
                    break
                compact[str(key)] = self._compact_json_value(item, depth=depth + 1)
            return compact
        if isinstance(value, list):
            items = value[-WRITE_CONTEXT_LIST_LIMIT:] if len(value) > WRITE_CONTEXT_LIST_LIMIT else value
            result = [self._compact_json_value(item, depth=depth + 1) for item in items]
            if len(value) > WRITE_CONTEXT_LIST_LIMIT:
                result.insert(0, {"_truncated_items": len(value) - WRITE_CONTEXT_LIST_LIMIT})
            return result
        if isinstance(value, str):
            return self._trim_text(value)
        return value

    def _compact_leaf(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._trim_text(value)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return self._trim_text(str(value))

    def _trim_text(self, value: str) -> str:
        text = str(value or "")
        if len(text) <= WRITE_CONTEXT_STRING_LIMIT:
            return text
        half = WRITE_CONTEXT_STRING_LIMIT // 2
        return f"{text[:half]}\n...[trimmed {len(text) - WRITE_CONTEXT_STRING_LIMIT} chars]...\n{text[-half:]}"

    def _tail_list(self, value: Any, limit: int) -> list[Any]:
        items = self._as_list(value)
        return items[-limit:]

    def _as_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]
