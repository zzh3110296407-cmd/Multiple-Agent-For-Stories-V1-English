from typing import Any

from pydantic import BaseModel

from app.backend.graph.phase1_graph_state import Phase1GraphState
from app.backend.services.scene_generation_service import SceneGenerationService
from app.backend.storage.json_store import StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class CheckSceneGenerationReadyNode:
    def __init__(self, service: SceneGenerationService | None = None) -> None:
        self.service = service or SceneGenerationService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        readiness = self.service.check_scene_generation_ready()
        state.active_model_ready = readiness.active_model_configured
        state.world_canvas_confirmed = readiness.world_canvas_confirmed
        state.main_cast_finished = readiness.main_cast_finished
        state.chapter_plan_confirmed = readiness.chapter_plan_confirmed
        state.scene_generation_ready = readiness.ready
        if not readiness.ready:
            state.blocking_issues.extend(readiness.issues)
        return state


class LoadSceneInputsNode:
    def __init__(self, service: SceneGenerationService | None = None) -> None:
        self.service = service or SceneGenerationService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        try:
            inputs = self.service.load_scene_inputs()
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            return state
        state.world_canvas = inputs.get("world_canvas")
        state.characters = inputs.get("characters") or []
        state.relationships = inputs.get("relationships") or []
        state.chapters = [inputs.get("chapter") or {}]
        state.current_chapter_framework = inputs.get("current_chapter_framework")
        return state


class ScenePlannerNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        if not state.current_chapter_framework:
            state.blocking_issues.append("ScenePlannerNode requires current chapter framework.")
        return state


class SceneEnvironmentNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        if not state.world_canvas:
            state.blocking_issues.append("SceneEnvironmentNode requires World Canvas.")
        return state


class RoleBeatNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        if not state.characters:
            state.blocking_issues.append("RoleBeatNode requires confirmed characters.")
        return state


class StoryInformationAssemblerNode:
    def __init__(self, service: SceneGenerationService | None = None) -> None:
        self.service = service or SceneGenerationService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        response = self.service.get_current_scene()
        scene = response.scene or {}
        trace = scene.get("generation_trace") or {}
        if not trace.get("story_information_list"):
            state.blocking_issues.append("Story information list is missing.")
            return state
        state.current_scene = scene
        state.scene_generation_trace = trace
        return state


class StoryTodoOrderingNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        trace = state.scene_generation_trace or {}
        package = trace.get("ordered_story_information_package")
        if not package:
            state.blocking_issues.append("Ordered story information package is missing.")
            return state
        state.ordered_story_information_package = package
        return state


class WriteAgentNode:
    def __init__(self, service: SceneGenerationService | None = None) -> None:
        self.service = service or SceneGenerationService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        try:
            response = self.service.generate_first_scene()
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            return state
        state.current_scene = response.scene
        if response.scene:
            trace = response.scene.get("generation_trace") or {}
            state.scene_generation_trace = trace
            state.ordered_story_information_package = trace.get(
                "ordered_story_information_package"
            )
            state.scene_quality_report = response.scene.get("quality_report")
        return state


class MemoryCuratorNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        scene = state.current_scene or {}
        if not scene.get("memory_extraction"):
            state.blocking_issues.append("Memory extraction is missing.")
        return state


class QualityCheckNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        scene = state.current_scene or {}
        quality = scene.get("quality_report") or {}
        state.scene_quality_report = quality
        state.warnings.extend(quality.get("warnings") or [])
        state.blocking_issues.extend(quality.get("blocking_issues") or [])
        return state


class SceneDraftStorageNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.current_scene:
            state.blocking_issues.append("SceneDraftStorageNode requires current scene.")
        return state


class ConfirmSceneDraftNode:
    def __init__(self, service: SceneGenerationService | None = None) -> None:
        self.service = service or SceneGenerationService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        try:
            response = self.service.confirm_scene_draft(state.user_input)
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            return state
        state.current_scene = response.scene
        state.scene_confirmed = True
        state.current_step = "scene_1_confirmed"
        return state
