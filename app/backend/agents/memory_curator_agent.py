import json
from typing import Any

from app.backend.prompts.scene_generation_prompts import (
    MEMORY_CURATOR_SYSTEM_PROMPT,
    build_memory_curator_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


MEMORY_CURATOR_MAX_OUTPUT_TOKENS = 1200
MEMORY_CURATOR_TIMEOUT_SECONDS = 45
MEMORY_CURATOR_MAX_ATTEMPTS = 1


class MemoryCuratorAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def extract_memory(
        self,
        scene: dict[str, Any],
        approved_context: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": MEMORY_CURATOR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_memory_curator_prompt(
                        scene_json=json.dumps(scene, ensure_ascii=False, indent=2),
                        context_json=json.dumps(
                            approved_context,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    ),
                },
            ],
            schema_hint={
                "kind": "scene_memory",
                "scene": scene,
                "approved_context": approved_context,
            },
            options={
                "max_output_tokens": MEMORY_CURATOR_MAX_OUTPUT_TOKENS,
                "timeout_seconds": MEMORY_CURATOR_TIMEOUT_SECONDS,
                "max_attempts": MEMORY_CURATOR_MAX_ATTEMPTS,
                "temperature": 0.1,
            },
            agent_role="memory_curator",
            service_name="MemoryCuratorAgent",
            operation_name="extract_scene_memory",
        )
        return result.data
