import json
from typing import Any

from app.backend.prompts.scene_revision_prompts import (
    SCENE_REVISION_SYSTEM_PROMPT,
    build_scene_revision_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


class SceneRevisionAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def revise_scene(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": SCENE_REVISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_scene_revision_prompt(
                        context_json=json.dumps(
                            context,
                            ensure_ascii=False,
                            indent=2,
                        )
                    ),
                },
            ],
            schema_hint={
                "kind": "scene_revision",
                "context": context,
                "revision_prompt": context.get("revision_prompt") or "",
                "revision_intent": context.get("revision_intent") or "",
                "force_hard_rule_override": bool(
                    context.get("force_hard_rule_override")
                ),
            },
        )
        return result.data
