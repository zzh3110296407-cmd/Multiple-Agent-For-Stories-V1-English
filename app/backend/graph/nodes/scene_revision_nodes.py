from app.backend.graph.phase1_graph_state import Phase1GraphState
from app.backend.services.scene_revision_service import SceneRevisionService
from app.backend.storage.json_store import StorageError


class RevisionIntentClassifierNode:
    def __init__(self, service: SceneRevisionService | None = None) -> None:
        self.service = service or SceneRevisionService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        if not state.user_input:
            state.blocking_issues.append("SCENE_REVISION_PROMPT_REQUIRED")
            return state
        state.scene_revision_intent = self.service.classify_revision_intent(
            state.user_input,
            {
                "current_scene": state.current_scene or {},
                "world_canvas": state.world_canvas or {},
            },
        )
        return state


class SceneRevisionCandidateNode:
    def __init__(self, service: SceneRevisionService | None = None) -> None:
        self.service = service or SceneRevisionService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        scene = state.current_scene or {}
        scene_id = scene.get("scene_id")
        if not scene_id:
            state.blocking_issues.append("SceneRevisionCandidateNode requires current_scene.scene_id.")
            return state
        try:
            response = self.service.revise_scene(
                scene_id=scene_id,
                revision_prompt=state.user_input or "",
                force_hard_rule_override=False,
            )
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            return state
        state.current_scene = response.scene
        state.scene_revision_candidate = response.candidate
        state.scene_revision_intent = response.revision_intent
        if response.candidate:
            state.scene_quality_report = response.candidate.get("quality_report")
        return state


class ConfirmSceneRevisionNode:
    def __init__(self, service: SceneRevisionService | None = None) -> None:
        self.service = service or SceneRevisionService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        scene = state.current_scene or {}
        candidate = state.scene_revision_candidate or {}
        scene_id = scene.get("scene_id")
        revision_id = candidate.get("revision_id")
        if not scene_id or not revision_id:
            state.blocking_issues.append(
                "ConfirmSceneRevisionNode requires scene_id and revision_id."
            )
            return state
        try:
            response = self.service.confirm_revision(
                scene_id=scene_id,
                revision_id=revision_id,
                user_input=state.user_input,
            )
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            return state
        state.current_scene = response.scene
        state.scene_revision_candidate = response.candidate
        state.scene_revised = True
        scene_index = response.scene.get("scene_index") if isinstance(response.scene, dict) else None
        state.current_step = f"scene_{scene_index or 1}_revised"
        return state
