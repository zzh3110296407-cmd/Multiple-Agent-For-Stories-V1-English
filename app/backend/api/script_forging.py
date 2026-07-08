from fastapi import APIRouter, HTTPException

from ..models.script_forging import (
    CharacterAssetListResponse,
    CostumeContinuityListResponse,
    DigitalAssetPackageResponse,
    KeyStoryboardArtifactListResponse,
    LocationAssetListResponse,
    MotifAssetListResponse,
    PropAssetListResponse,
    SceneOutlineArtifactResponse,
    SceneStoryboardArtifactListResponse,
    ScreenplayDraftArtifactResponse,
    ScreenplayRevisionCandidateListResponse,
    ScreenplayRevisionCandidateResponse,
    ScreenplaySelfCheckReportResponse,
    ShotListArtifactResponse,
    ScriptAdaptationPromptPackageResponse,
    ScriptForgingContextResponse,
    ScriptForgingDecisionRequest,
    ScriptForgingDecisionResponse,
    ScriptForgingRiskNoteResponse,
    ScriptShapePackageResponse,
    StoryboardPackageResponse,
)
from ..services.script_forging_service import ScriptForgingService
from ..storage.json_store import StorageError


router = APIRouter()
script_forging_service = ScriptForgingService()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message or "LIVE_STORY_REF_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    if (
        "BLOCKED" in message
        or "REQUIRED" in message
        or "NOT_CONFIRMED" in message
        or "NOT_PENDING" in message
        or "NOT_ALLOWED" in message
        or "NOT_SELF_CHECKABLE" in message
        or "NOT_REVISION_CANDIDATE_ELIGIBLE" in message
        or "MISMATCH" in message
        or "FORBIDDEN" in message
        or "NON_REAL" in message
        or "FIXTURE" in message
        or "NOT_PLUGIN_USABLE" in message
    ):
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.post("/{plugin_run_id}/script-forging/context", response_model=ScriptForgingContextResponse)
def create_script_forging_context(plugin_run_id: str) -> ScriptForgingContextResponse:
    try:
        return script_forging_service.create_context(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/context", response_model=ScriptForgingContextResponse)
def get_script_forging_context(plugin_run_id: str) -> ScriptForgingContextResponse:
    try:
        return script_forging_service.get_context(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/shape-package", response_model=ScriptShapePackageResponse)
def create_script_shape_package(plugin_run_id: str) -> ScriptShapePackageResponse:
    try:
        return script_forging_service.create_shape_package(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/shape-package", response_model=ScriptShapePackageResponse)
def get_script_shape_package(plugin_run_id: str) -> ScriptShapePackageResponse:
    try:
        return script_forging_service.get_shape_package(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/shape-package/checkpoint/confirm", response_model=ScriptForgingDecisionResponse)
def confirm_script_shape_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_shape_checkpoint_decision(plugin_run_id, "confirm", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/shape-package/checkpoint/revise", response_model=ScriptForgingDecisionResponse)
def revise_script_shape_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_shape_checkpoint_decision(plugin_run_id, "request_revision", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/shape-package/checkpoint/reject", response_model=ScriptForgingDecisionResponse)
def reject_script_shape_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_shape_checkpoint_decision(plugin_run_id, "reject", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/shape-package/checkpoint/defer", response_model=ScriptForgingDecisionResponse)
def defer_script_shape_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_shape_checkpoint_decision(plugin_run_id, "defer", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/adaptation-prompt-package", response_model=ScriptAdaptationPromptPackageResponse)
def create_script_adaptation_prompt_package(plugin_run_id: str) -> ScriptAdaptationPromptPackageResponse:
    try:
        return script_forging_service.create_adaptation_prompt_package(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/adaptation-prompt-package", response_model=ScriptAdaptationPromptPackageResponse)
def get_script_adaptation_prompt_package(plugin_run_id: str) -> ScriptAdaptationPromptPackageResponse:
    try:
        return script_forging_service.get_adaptation_prompt_package(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/adaptation-prompt-package/checkpoint/confirm", response_model=ScriptForgingDecisionResponse)
def confirm_script_adaptation_prompt_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_prompt_package_checkpoint_decision(plugin_run_id, "confirm", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/adaptation-prompt-package/checkpoint/revise", response_model=ScriptForgingDecisionResponse)
def revise_script_adaptation_prompt_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_prompt_package_checkpoint_decision(plugin_run_id, "request_revision", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/adaptation-prompt-package/checkpoint/reject", response_model=ScriptForgingDecisionResponse)
def reject_script_adaptation_prompt_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_prompt_package_checkpoint_decision(plugin_run_id, "reject", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/adaptation-prompt-package/checkpoint/defer", response_model=ScriptForgingDecisionResponse)
def defer_script_adaptation_prompt_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_prompt_package_checkpoint_decision(plugin_run_id, "defer", request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/risk-note", response_model=ScriptForgingRiskNoteResponse)
def get_script_forging_risk_note(plugin_run_id: str) -> ScriptForgingRiskNoteResponse:
    try:
        return script_forging_service.get_risk_note(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/scene-outline", response_model=SceneOutlineArtifactResponse)
def create_scene_outline(plugin_run_id: str) -> SceneOutlineArtifactResponse:
    try:
        return script_forging_service.create_scene_outline(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/scene-outline", response_model=SceneOutlineArtifactResponse)
def get_scene_outline(plugin_run_id: str) -> SceneOutlineArtifactResponse:
    try:
        return script_forging_service.get_scene_outline(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/scene-outline/checkpoint/confirm", response_model=ScriptForgingDecisionResponse)
def confirm_scene_outline(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_scene_outline_checkpoint_decision(plugin_run_id, "confirm", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/scene-outline/checkpoint/revise", response_model=ScriptForgingDecisionResponse)
def revise_scene_outline(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_scene_outline_checkpoint_decision(plugin_run_id, "request_revision", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/scene-outline/checkpoint/reject", response_model=ScriptForgingDecisionResponse)
def reject_scene_outline(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_scene_outline_checkpoint_decision(plugin_run_id, "reject", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/scene-outline/checkpoint/defer", response_model=ScriptForgingDecisionResponse)
def defer_scene_outline(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_scene_outline_checkpoint_decision(plugin_run_id, "defer", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/screenplay-draft", response_model=ScreenplayDraftArtifactResponse)
def create_screenplay_draft(plugin_run_id: str) -> ScreenplayDraftArtifactResponse:
    try:
        return script_forging_service.create_screenplay_draft(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/screenplay-draft", response_model=ScreenplayDraftArtifactResponse)
def get_screenplay_draft(plugin_run_id: str) -> ScreenplayDraftArtifactResponse:
    try:
        return script_forging_service.get_screenplay_draft(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/screenplay-draft/checkpoint/confirm", response_model=ScriptForgingDecisionResponse)
def confirm_screenplay_draft(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_screenplay_draft_checkpoint_decision(plugin_run_id, "confirm", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/screenplay-draft/checkpoint/revise", response_model=ScriptForgingDecisionResponse)
def revise_screenplay_draft(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_screenplay_draft_checkpoint_decision(plugin_run_id, "request_revision", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/screenplay-draft/checkpoint/reject", response_model=ScriptForgingDecisionResponse)
def reject_screenplay_draft(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_screenplay_draft_checkpoint_decision(plugin_run_id, "reject", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/screenplay-draft/checkpoint/defer", response_model=ScriptForgingDecisionResponse)
def defer_screenplay_draft(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_screenplay_draft_checkpoint_decision(plugin_run_id, "defer", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/screenplay-self-check", response_model=ScreenplaySelfCheckReportResponse)
def create_screenplay_self_check(plugin_run_id: str) -> ScreenplaySelfCheckReportResponse:
    try:
        return script_forging_service.create_screenplay_self_check(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/screenplay-self-check", response_model=ScreenplaySelfCheckReportResponse)
def get_screenplay_self_check(plugin_run_id: str) -> ScreenplaySelfCheckReportResponse:
    try:
        return script_forging_service.get_screenplay_self_check(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/screenplay-revision-candidate", response_model=ScreenplayRevisionCandidateResponse)
def create_screenplay_revision_candidate(plugin_run_id: str) -> ScreenplayRevisionCandidateResponse:
    try:
        return script_forging_service.create_screenplay_revision_candidate(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/screenplay-revision-candidates", response_model=ScreenplayRevisionCandidateListResponse)
def list_screenplay_revision_candidates(plugin_run_id: str) -> ScreenplayRevisionCandidateListResponse:
    try:
        return script_forging_service.list_screenplay_revision_candidates(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/storyboard-package", response_model=StoryboardPackageResponse)
def create_storyboard_package(plugin_run_id: str) -> StoryboardPackageResponse:
    try:
        return script_forging_service.create_storyboard_package(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/storyboard-package", response_model=StoryboardPackageResponse)
def get_storyboard_package(plugin_run_id: str) -> StoryboardPackageResponse:
    try:
        return script_forging_service.get_storyboard_package(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/storyboard-package/checkpoint/confirm", response_model=ScriptForgingDecisionResponse)
def confirm_storyboard_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_storyboard_package_checkpoint_decision(plugin_run_id, "confirm", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/storyboard-package/checkpoint/revise", response_model=ScriptForgingDecisionResponse)
def revise_storyboard_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_storyboard_package_checkpoint_decision(plugin_run_id, "request_revision", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/storyboard-package/checkpoint/reject", response_model=ScriptForgingDecisionResponse)
def reject_storyboard_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_storyboard_package_checkpoint_decision(plugin_run_id, "reject", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/storyboard-package/checkpoint/defer", response_model=ScriptForgingDecisionResponse)
def defer_storyboard_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_storyboard_package_checkpoint_decision(plugin_run_id, "defer", request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/key-storyboards", response_model=KeyStoryboardArtifactListResponse)
def list_key_storyboards(plugin_run_id: str) -> KeyStoryboardArtifactListResponse:
    try:
        return script_forging_service.list_key_storyboard_artifacts(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/scene-storyboards", response_model=SceneStoryboardArtifactListResponse)
def list_scene_storyboards(plugin_run_id: str) -> SceneStoryboardArtifactListResponse:
    try:
        return script_forging_service.list_scene_storyboard_artifacts(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/shot-list", response_model=ShotListArtifactResponse)
def get_shot_list(plugin_run_id: str) -> ShotListArtifactResponse:
    try:
        return script_forging_service.get_shot_list_artifact(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/digital-asset-package", response_model=DigitalAssetPackageResponse)
def create_digital_asset_package(plugin_run_id: str) -> DigitalAssetPackageResponse:
    try:
        return script_forging_service.create_digital_asset_package(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/digital-asset-package", response_model=DigitalAssetPackageResponse)
def get_digital_asset_package(plugin_run_id: str) -> DigitalAssetPackageResponse:
    try:
        return script_forging_service.get_digital_asset_package(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/digital-asset-package/checkpoint/confirm", response_model=ScriptForgingDecisionResponse)
def confirm_digital_asset_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_digital_asset_package_checkpoint_decision(plugin_run_id, "confirm", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/digital-asset-package/checkpoint/revise", response_model=ScriptForgingDecisionResponse)
def revise_digital_asset_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_digital_asset_package_checkpoint_decision(plugin_run_id, "request_revision", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/digital-asset-package/checkpoint/reject", response_model=ScriptForgingDecisionResponse)
def reject_digital_asset_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_digital_asset_package_checkpoint_decision(plugin_run_id, "reject", request)
    except StorageError as exc:
        _raise_http(exc)


@router.post("/{plugin_run_id}/script-forging/digital-asset-package/checkpoint/defer", response_model=ScriptForgingDecisionResponse)
def defer_digital_asset_package(
    plugin_run_id: str,
    request: ScriptForgingDecisionRequest,
) -> ScriptForgingDecisionResponse:
    try:
        return script_forging_service.submit_digital_asset_package_checkpoint_decision(plugin_run_id, "defer", request)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/asset-lists/characters", response_model=CharacterAssetListResponse)
def get_character_asset_list(plugin_run_id: str) -> CharacterAssetListResponse:
    try:
        return script_forging_service.get_character_asset_list(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/asset-lists/locations", response_model=LocationAssetListResponse)
def get_location_asset_list(plugin_run_id: str) -> LocationAssetListResponse:
    try:
        return script_forging_service.get_location_asset_list(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/asset-lists/props", response_model=PropAssetListResponse)
def get_prop_asset_list(plugin_run_id: str) -> PropAssetListResponse:
    try:
        return script_forging_service.get_prop_asset_list(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/asset-lists/motifs", response_model=MotifAssetListResponse)
def get_motif_asset_list(plugin_run_id: str) -> MotifAssetListResponse:
    try:
        return script_forging_service.get_motif_asset_list(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)


@router.get("/{plugin_run_id}/script-forging/asset-lists/costume-continuity", response_model=CostumeContinuityListResponse)
def get_costume_continuity_list(plugin_run_id: str) -> CostumeContinuityListResponse:
    try:
        return script_forging_service.get_costume_continuity_list(plugin_run_id)
    except StorageError as exc:
        _raise_http(exc)
