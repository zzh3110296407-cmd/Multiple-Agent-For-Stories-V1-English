import json
from typing import Any

from app.backend.services.model_gateway_service import ModelGatewayService


CHAPTER_FRAMEWORK_BUILDER_SYSTEM_PROMPT = """
You are ChapterFrameworkBuilderAgent.
Build the current chapter framework only.
Do not build future chapter frameworks.
Do not generate scene plans.
Do not write prose.
Do not override user decisions, world hard rules, confirmed story facts, or framework macro mapping.
Use only the provided component vocabulary.
Output valid JSON only.
""".strip()


CHAPTER_FRAMEWORK_BUILDER_SCHEMA_INSTRUCTIONS = """
Return a JSON object with:
- chapter_function: string
- chapter_goal: string
- reader_emotion_goal: array of strings
- main_conflict: string
- participating_character_ids: array of strings
- relationship_focus: array of strings
- information_release_policy: string
- forbidden_reveals: array of strings
- world_rule_focus: array of strings
- selected_modules: array of objects
- warnings: array of strings

Each selected_modules item must contain:
- module_id: string
- component_ids: array of strings
- reason_summary: string
- confidence: number between 0 and 1
""".strip()


class ChapterFrameworkBuilderAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def build_current_chapter_framework(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {
                    "role": "system",
                    "content": CHAPTER_FRAMEWORK_BUILDER_SYSTEM_PROMPT,
                },
                {
                    "role": "system",
                    "content": CHAPTER_FRAMEWORK_BUILDER_SCHEMA_INSTRUCTIONS,
                },
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False, indent=2),
                },
            ],
            schema_hint={
                "kind": "chapter_framework_builder",
                "operation": "build_current",
                "context": context,
            },
            agent_role="chapter",
            service_name="ChapterFrameworkBuilderAgent.build_current_chapter_framework",
            operation_name="build_current_chapter_framework",
        )
        return result.data
