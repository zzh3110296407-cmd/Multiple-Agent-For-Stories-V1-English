from fastapi import APIRouter, HTTPException

from app.backend.models.story_setup import (
    AnswerStorySetupQuestionRequest,
    BootstrapStorySetupHandoffRequest,
    CreateStorySetupDecisionRequest,
    CreateStorySetupDraftBundleRequest,
    CreateStorySetupHandoffRequest,
    CreateStorySetupIntakeRequest,
    CreateStorySetupPromptFromProjectRequest,
    PatchStorySetupDraftBundleRequest,
    StorySetupCurrentState,
    StorySetupDecision,
    StorySetupDraftBundle,
    StorySetupHandoff,
    StorySetupIntake,
    StorySetupPrompt,
    StorySetupBootstrapResult,
    StorySetupQuestionsResponse,
    StorySetupQuestion,
    StorySetupSafetyReport,
)
from app.backend.services.story_setup_service import (
    StorySetupBlocked,
    StorySetupError,
    StorySetupNotFound,
    StorySetupSafetyError,
    StorySetupService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
story_setup_service = StorySetupService()


def _raise_story_setup_error(exc: Exception) -> None:
    if isinstance(exc, StorySetupNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, StorySetupSafetyError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, StorySetupBlocked):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, StorySetupError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, StorageError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


@router.post("/prompts/from-project", response_model=StorySetupPrompt)
def create_story_setup_prompt_from_project(
    request: CreateStorySetupPromptFromProjectRequest,
) -> StorySetupPrompt:
    try:
        return story_setup_service.create_prompt_from_project(request)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get("/current", response_model=StorySetupCurrentState)
def get_current_story_setup_state(project_id: str | None = None) -> StorySetupCurrentState:
    try:
        return story_setup_service.get_current_state(project_id=project_id)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get("/prompts/{story_setup_prompt_id}", response_model=StorySetupPrompt)
def get_story_setup_prompt(story_setup_prompt_id: str) -> StorySetupPrompt:
    try:
        return story_setup_service.get_prompt(story_setup_prompt_id)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.post("/intakes", response_model=StorySetupIntake)
def create_story_setup_intake(request: CreateStorySetupIntakeRequest) -> StorySetupIntake:
    try:
        return story_setup_service.create_intake(request)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get("/intakes/{story_setup_intake_id}", response_model=StorySetupIntake)
def get_story_setup_intake(story_setup_intake_id: str) -> StorySetupIntake:
    try:
        return story_setup_service.get_intake(story_setup_intake_id)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.post("/draft-bundles", response_model=StorySetupDraftBundle)
def create_story_setup_draft_bundle(
    request: CreateStorySetupDraftBundleRequest,
) -> StorySetupDraftBundle:
    try:
        return story_setup_service.create_draft_bundle(request)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.post("/prompts/{story_setup_prompt_id}/draft-bundle", response_model=StorySetupDraftBundle)
def create_story_setup_draft_bundle_from_prompt(
    story_setup_prompt_id: str,
) -> StorySetupDraftBundle:
    try:
        return story_setup_service.create_draft_bundle(
            CreateStorySetupDraftBundleRequest(
                story_setup_prompt_id=story_setup_prompt_id,
                story_setup_intake_id=None,
                selected_framework_composition_id=None,
            )
        )
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get("/draft-bundles", response_model=list[StorySetupDraftBundle])
def list_story_setup_draft_bundles() -> list[StorySetupDraftBundle]:
    try:
        return story_setup_service.list_draft_bundles()
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get("/draft-bundles/{story_setup_draft_bundle_id}", response_model=StorySetupDraftBundle)
def get_story_setup_draft_bundle(story_setup_draft_bundle_id: str) -> StorySetupDraftBundle:
    try:
        return story_setup_service.get_draft_bundle(story_setup_draft_bundle_id)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.patch("/draft-bundles/{story_setup_draft_bundle_id}", response_model=StorySetupDraftBundle)
def patch_story_setup_draft_bundle(
    story_setup_draft_bundle_id: str,
    request: PatchStorySetupDraftBundleRequest,
) -> StorySetupDraftBundle:
    try:
        return story_setup_service.patch_draft_bundle(story_setup_draft_bundle_id, request)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get(
    "/draft-bundles/{story_setup_draft_bundle_id}/questions",
    response_model=StorySetupQuestionsResponse,
)
def list_story_setup_questions(story_setup_draft_bundle_id: str) -> StorySetupQuestionsResponse:
    try:
        return StorySetupQuestionsResponse(
            questions=story_setup_service.list_questions(story_setup_draft_bundle_id)
        )
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.post("/questions/{question_id}/answer", response_model=StorySetupQuestion)
def answer_story_setup_question(
    question_id: str,
    request: AnswerStorySetupQuestionRequest,
) -> StorySetupQuestion:
    try:
        return story_setup_service.answer_question(question_id, request)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/draft-bundles/{story_setup_draft_bundle_id}/decisions",
    response_model=StorySetupDecision,
)
def create_story_setup_decision(
    story_setup_draft_bundle_id: str,
    request: CreateStorySetupDecisionRequest,
) -> StorySetupDecision:
    try:
        return story_setup_service.create_decision(story_setup_draft_bundle_id, request)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get("/decisions/{story_setup_decision_id}", response_model=StorySetupDecision)
def get_story_setup_decision(story_setup_decision_id: str) -> StorySetupDecision:
    try:
        return story_setup_service.get_decision(story_setup_decision_id)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.post("/decisions/{story_setup_decision_id}/handoff", response_model=StorySetupHandoff)
def create_story_setup_handoff(
    story_setup_decision_id: str,
    request: CreateStorySetupHandoffRequest | None = None,
) -> StorySetupHandoff:
    try:
        return story_setup_service.create_handoff(
            story_setup_decision_id,
            request or CreateStorySetupHandoffRequest(),
        )
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get("/handoffs/{story_setup_handoff_id}", response_model=StorySetupHandoff)
def get_story_setup_handoff(story_setup_handoff_id: str) -> StorySetupHandoff:
    try:
        return story_setup_service.get_handoff(story_setup_handoff_id)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/handoffs/{story_setup_handoff_id}/bootstrap-active-project",
    response_model=StorySetupBootstrapResult,
)
def bootstrap_story_setup_handoff(
    story_setup_handoff_id: str,
    request: BootstrapStorySetupHandoffRequest | None = None,
) -> StorySetupBootstrapResult:
    try:
        return story_setup_service.bootstrap_active_project_story_data(
            story_setup_handoff_id,
            request or BootstrapStorySetupHandoffRequest(),
        )
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")


@router.get(
    "/draft-bundles/{story_setup_draft_bundle_id}/safety-report",
    response_model=StorySetupSafetyReport,
)
def get_story_setup_safety_report(
    story_setup_draft_bundle_id: str,
) -> StorySetupSafetyReport:
    try:
        return story_setup_service.get_or_create_safety_report(story_setup_draft_bundle_id)
    except (StorySetupError, StorageError) as exc:
        _raise_story_setup_error(exc)
        raise AssertionError("unreachable")
