from typing import Any

from pydantic import BaseModel

from app.backend.graph.phase1_graph_state import Phase1GraphState
from app.backend.models.character_workflow import CurrentCharacterDraft
from app.backend.services.character_service import CharacterService
from app.backend.storage.json_store import StorageError


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class CheckWorldCanvasConfirmedNode:
    def __init__(self, service: CharacterService | None = None) -> None:
        self.service = service or CharacterService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        try:
            world_canvas = self.service.load_confirmed_world_canvas()
        except StorageError as exc:
            state.blocking_issues.append(str(exc))
            state.world_canvas_confirmed = False
            return state
        state.world_canvas = model_to_dict(world_canvas)
        state.world_canvas_confirmed = True
        return state


class LoadConfirmedCharactersNode:
    def __init__(self, service: CharacterService | None = None) -> None:
        self.service = service or CharacterService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        response = self.service.get_current_characters()
        state.characters = [model_to_dict(character) for character in response.characters]
        state.relationships = [
            model_to_dict(relationship) for relationship in response.relationships
        ]
        return state


class UserCharacterIntentNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.user_input:
            state.blocking_issues.append("Character user input is missing.")
        return state


class CharacterNode:
    def __init__(self, service: CharacterService | None = None) -> None:
        self.service = service or CharacterService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        if state.user_action == "revise":
            response = self.service.revise_character(state.user_input or "")
        else:
            response = self.service.generate_character(state.user_input or "")
        if response.draft:
            state.character_draft = model_to_dict(response.draft)
        if response.validation:
            state.warnings.extend(response.validation.warnings)
            state.blocking_issues.extend(response.validation.blocking_issues)
        return state


class CharacterValidationNode:
    def __init__(self, service: CharacterService | None = None) -> None:
        self.service = service or CharacterService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.character_draft:
            state.blocking_issues.append("Character draft is missing.")
            return state
        validation = self.service.validate_character_draft(
            CurrentCharacterDraft(**state.character_draft)
        )
        state.warnings.extend(validation.warnings)
        state.blocking_issues.extend(validation.blocking_issues)
        return state


class RelationshipBuilderNode:
    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if not state.character_draft:
            state.blocking_issues.append("Relationship builder requires a character draft.")
        return state


class UserCharacterConfirmationNode:
    def __init__(self, service: CharacterService | None = None) -> None:
        self.service = service or CharacterService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.blocking_issues:
            return state
        response = self.service.confirm_character(state.user_input)
        if response.draft:
            state.character_draft = model_to_dict(response.draft)
        state.characters = [model_to_dict(character) for character in response.characters]
        state.relationships = [
            model_to_dict(relationship) for relationship in response.relationships
        ]
        state.current_step = "character_confirmed"
        return state


class AddNextCharacterOrFinishMainCast:
    def __init__(self, service: CharacterService | None = None) -> None:
        self.service = service or CharacterService()

    def run(self, state: Phase1GraphState) -> Phase1GraphState:
        if state.user_action == "finish_main_cast":
            response = self.service.finish_main_cast(state.user_input)
            state.main_cast_finished = response.main_cast_finished
            state.current_step = "characters_confirmed"
        elif not state.blocking_issues:
            state.current_step = "character_draft"
        return state
