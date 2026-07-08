from typing import Any

from pydantic import BaseModel

from app.backend.graph.phase1_graph_state import Phase1GraphState
from app.backend.models.world_canvas import WorldCanvas
from app.backend.services.model_gateway_service import ModelGatewayService
from app.backend.services.world_canvas_service import WorldCanvasService


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class CheckActiveModelNode:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        status = self.model_gateway.validate_model_config()
        state.active_model_ready = status.configured
        if not status.configured:
            state.blocking_issues.extend(status.issues)
        return state


class WorldCanvasNode:
    def __init__(self, service: WorldCanvasService | None = None) -> None:
        self.service = service or WorldCanvasService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.active_model_ready:
            state.blocking_issues.append("Active model is not configured.")
            return state
        if not state.user_input:
            state.blocking_issues.append("World Canvas user input is missing.")
            return state
        if state.user_action == "revise":
            response = self.service.revise_canvas(state.user_input)
        else:
            response = self.service.generate_from_idea(state.user_input)
        state.world_canvas = model_to_dict(response.world_canvas)
        state.warnings.extend(response.validation.warnings)
        state.blocking_issues.extend(response.validation.blocking_issues)
        return state


class WorldCanvasValidationNode:
    def __init__(self, service: WorldCanvasService | None = None) -> None:
        self.service = service or WorldCanvasService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.world_canvas:
            state.blocking_issues.append("World Canvas is missing.")
            return state
        validation = self.service.validate_canvas(WorldCanvas(**state.world_canvas))
        state.warnings.extend(validation.warnings)
        state.blocking_issues.extend(validation.blocking_issues)
        return state


class StorageNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.world_canvas and not state.blocking_issues:
            state.current_step = "world_canvas_draft"
        return state
