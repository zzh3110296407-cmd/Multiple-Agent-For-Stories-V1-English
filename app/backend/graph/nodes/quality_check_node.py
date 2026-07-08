from app.backend.graph.phase1_graph_state import Phase1GraphState
from app.backend.services.quality_check_service import QualityCheckService
from app.backend.storage.json_store import StorageError


class QualityGateNode:
    def __init__(self, service: QualityCheckService | None = None) -> None:
        self.service = service or QualityCheckService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        scene = state.current_scene or {}
        scene_id = scene.get("scene_id")
        if not scene_id:
            state.blocking_issues.append("QualityGateNode requires current_scene.scene_id.")
            return state
        candidate = state.scene_revision_candidate or {}
        try:
            if candidate.get("revision_id"):
                response = self.service.check_scene_revision(
                    scene_id,
                    candidate["revision_id"],
                )
            else:
                response = self.service.check_scene_draft(scene_id)
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            return state
        state.scene_quality_report = response.embedded_report.model_dump(
            mode="json"
        ) if hasattr(response.embedded_report, "model_dump") else response.embedded_report.dict()
        state.warnings.extend(response.embedded_report.warnings)
        state.blocking_issues.extend(response.embedded_report.blocking_issues)
        return state
