import json
from typing import Any

from app.backend.prompts.scene_generation_prompts import (
    QUALITY_CHECK_SYSTEM_PROMPT,
    build_quality_check_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


class QualityCheckAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def check_scene(
        self,
        scene: dict[str, Any],
        approved_context: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": QUALITY_CHECK_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_quality_check_prompt(
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
                "kind": "scene_quality",
                "scene": scene,
                "approved_context": approved_context,
            },
        )
        return result.data
