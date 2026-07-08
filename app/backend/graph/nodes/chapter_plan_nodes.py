from typing import Any

from pydantic import BaseModel

from app.backend.core.story_capacity import DEFAULT_CHAPTER_COUNT
from app.backend.graph.phase1_graph_state import Phase1GraphState
from app.backend.services.chapter_plan_service import ChapterPlanService
from app.backend.storage.json_store import StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class CheckFoundationReadyNode:
    def __init__(self, service: ChapterPlanService | None = None) -> None:
        self.service = service or ChapterPlanService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        foundation = self.service.check_foundation_ready()
        state.active_model_ready = foundation.active_model_configured
        state.world_canvas_confirmed = foundation.world_canvas_confirmed
        state.main_cast_finished = foundation.main_cast_finished
        if not foundation.ready:
            state.blocking_issues.extend(foundation.issues)
        return state


class LoadFrameworkPackageNode:
    def __init__(self, service: ChapterPlanService | None = None) -> None:
        self.service = service or ChapterPlanService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        try:
            self.service.load_and_validate_framework_package()
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
        return state


class ChapterMacroAssignmentNode:
    def __init__(self, service: ChapterPlanService | None = None) -> None:
        self.service = service or ChapterPlanService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        try:
            package = self.service.load_and_validate_framework_package()
            if not package.chapter_macro_assignments:
                raise StorageError("Confirmed framework macro mapping is missing.")
            if any(
                assignment.status != "confirmed"
                for assignment in package.chapter_macro_assignments
            ):
                raise StorageError("Framework macro mapping must be confirmed.")
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
        return state


class CurrentChapterFrameworkBuilderNode:
    def __init__(self, service: ChapterPlanService | None = None) -> None:
        self.service = service or ChapterPlanService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        try:
            framework = self.service.build_current_chapter_framework_draft(
                current_chapter_index=1,
                story_goal=state.user_input or "",
            )
            state.current_chapter_framework = model_to_dict(framework)
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
        return state


class ChapterAgentNode:
    def __init__(self, service: ChapterPlanService | None = None) -> None:
        self.service = service or ChapterPlanService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        try:
            response = self.service.generate_chapter_plan(
                story_goal=state.user_input or "",
                chapter_count=DEFAULT_CHAPTER_COUNT,
                current_chapter_index=1,
            )
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            return state
        if response.draft:
            state.chapter_plan_draft = model_to_dict(response.draft)
        if response.current_chapter_framework:
            state.current_chapter_framework = response.current_chapter_framework
        return state


class ChapterPlanValidationNode:
    def __init__(self, service: ChapterPlanService | None = None) -> None:
        self.service = service or ChapterPlanService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        response = self.service.get_current_plan()
        if not response.draft or not response.validation:
            state.blocking_issues.append("Chapter plan draft is missing.")
            return state
        state.chapter_plan_draft = model_to_dict(response.draft)
        state.warnings.extend(response.validation.warnings)
        state.blocking_issues.extend(response.validation.blocking_issues)
        return state


class ChapterDraftStorageNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.chapter_plan_draft:
            state.blocking_issues.append("Chapter draft storage requires a draft.")
        return state


class LoadChapterPlanDraftNode:
    def __init__(self, service: ChapterPlanService | None = None) -> None:
        self.service = service or ChapterPlanService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        response = self.service.get_current_plan()
        if response.draft:
            state.chapter_plan_draft = model_to_dict(response.draft)
            state.current_chapter_framework = response.current_chapter_framework
        else:
            state.blocking_issues.append("Chapter plan draft is missing.")
        return state


class ConfirmChapterPlanNode:
    def __init__(self, service: ChapterPlanService | None = None) -> None:
        self.service = service or ChapterPlanService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        try:
            response = self.service.confirm_chapter_plan(state.user_input)
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            return state
        if response.draft:
            state.chapter_plan_draft = model_to_dict(response.draft)
        state.chapters = [model_to_dict(chapter) for chapter in response.chapters]
        state.current_chapter_framework = response.current_chapter_framework
        state.chapter_plan_confirmed = True
        state.current_step = "chapter_plan_confirmed"
        return state


class SaveChaptersNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.chapters:
            state.blocking_issues.append("SaveChaptersNode requires chapters.")
        return state


class SaveBuiltChapterFrameworkNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.current_chapter_framework:
            state.blocking_issues.append("SaveBuiltChapterFrameworkNode requires current chapter framework.")
        return state


class SaveDecisionNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.chapter_plan_confirmed:
            state.blocking_issues.append("SaveDecisionNode requires confirmed chapter plan.")
        return state


class UpdateProjectStepNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.chapter_plan_confirmed:
            state.current_step = "chapter_plan_confirmed"
        return state
