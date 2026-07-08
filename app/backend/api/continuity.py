from typing import Any

from fastapi import APIRouter, HTTPException

from app.backend.models.continuity import (
    ContinuityCheckResponse,
    ContinuityIssueAcceptRequest,
    ContinuityIssueListResponse,
    ContinuityIssueResolveRequest,
    ContinuityResolutionRefreshResult,
    ContinuityResolutionOptionAvailabilityReport,
    ContinuityResolutionOptionExecutionRequest,
    ContinuityResolutionOptionExecutionResult,
    PriorStoryCompletionCandidateReviseRequest,
    PriorStoryCompletionCandidateDecisionRequest,
    PriorStoryCompletionCandidateResponse,
    PriorStoryCompletionCandidateWritePlan,
    PriorStoryCompletionLineage,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.continuity_gate_service import ContinuityGateService
from app.backend.services.continuity_resolution_refresh_service import (
    ContinuityResolutionRefreshService,
)
from app.backend.services.continuity_resolution_options_service import (
    ContinuityResolutionOptionExecutionService,
)
from app.backend.services.continuity_resolution_service import IssueResolutionService
from app.backend.storage.json_store import StorageError


router = APIRouter()
continuity_gate_service = ContinuityGateService()
issue_resolution_service = IssueResolutionService(
    continuity_gate_service=continuity_gate_service,
)


def continuity_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    message = str(exc)
    if message.startswith("CONTINUITY_SCENE_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "CONTINUITY_SCENE_MISSING",
                "message": "场景不存在，无法运行连续性检查。",
            },
        )
    if message.startswith("CONTINUITY_REVISION_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "CONTINUITY_REVISION_MISSING",
                "message": "场景修订候选不存在，无法运行连续性检查。",
            },
        )
    if message.startswith("CONTINUITY_ISSUE_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "CONTINUITY_ISSUE_MISSING",
                "message": "连续性问题不存在。",
            },
        )
    if message.startswith("CONTINUITY_TARGET_REQUIRED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CONTINUITY_TARGET_REQUIRED",
                "message": "Continuity state requires target_id, scene_id, or revision_id.",
            },
        )
    if message.startswith("CONTINUITY_RESOLUTION_OPTION_UNKNOWN"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CONTINUITY_RESOLUTION_OPTION_UNKNOWN",
                "message": "Unknown continuity resolution option.",
            },
        )
    if message.startswith("CONTINUITY_RESOLUTION_ACTION_INVALID"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CONTINUITY_RESOLUTION_ACTION_INVALID",
                "message": "Unknown continuity resolution action.",
            },
        )
    if message.startswith("CONTINUITY_RESOLUTION_OPTION_DISABLED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CONTINUITY_RESOLUTION_OPTION_DISABLED",
                "message": "This continuity resolution option is not executable for the current issue.",
            },
        )
    if message.startswith("CONTINUITY_RESOLUTION_ISSUE_NOT_OPEN"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CONTINUITY_RESOLUTION_ISSUE_NOT_OPEN",
                "message": "Continuity resolution options can only execute for open issues.",
            },
        )
    if message.startswith("CONTINUITY_RESOLUTION_OBJECTIVE_WRITE_BLOCKED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CONTINUITY_RESOLUTION_OBJECTIVE_WRITE_BLOCKED",
                "message": "Continuity resolution option attempted an unsafe objective write.",
            },
        )
    if message.startswith("CONTINUITY_ISSUE_ACCEPT_FORBIDDEN"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CONTINUITY_ISSUE_ACCEPT_FORBIDDEN",
                "message": "这个连续性问题不能直接接受，必须先处理来源或改成非客观事实。",
            },
        )
    if message.startswith("CONTINUITY_ACCEPT_REASON_REQUIRED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CONTINUITY_ACCEPT_REASON_REQUIRED",
                "message": "接受连续性问题必须填写理由。",
            },
        )
    if message.startswith("CONTINUITY_REVISION_PROMPT_REQUIRED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "CONTINUITY_REVISION_PROMPT_REQUIRED",
                "message": "修改当前幕需要填写修订提示。",
            },
        )
    if message.startswith("PRIOR_STORY_COMPLETION_CANDIDATE_MISSING"):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "PRIOR_STORY_COMPLETION_CANDIDATE_MISSING",
                "message": "前情补全候选不存在。",
            },
        )
    if message.startswith("PRIOR_STORY_COMPLETION_CANDIDATE_REJECTED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "PRIOR_STORY_COMPLETION_CANDIDATE_REJECTED",
                "message": "前情补全候选已拒绝。",
            },
        )
    if message.startswith("PRIOR_STORY_COMPLETION_CANDIDATE_CONFIRMED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "PRIOR_STORY_COMPLETION_CANDIDATE_CONFIRMED",
                "message": "已确认的前情补全候选不能拒绝。",
            },
        )
    if message.startswith("PRIOR_STORY_COMPLETION_CANDIDATE_STATUS_INVALID"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "PRIOR_STORY_COMPLETION_CANDIDATE_STATUS_INVALID",
                "message": "Old-story completion candidate cannot perform this action in its current status.",
            },
        )
    if message.startswith("PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID",
                "message": "Old-story completion candidate write scope is invalid.",
            },
        )
    if message.startswith("PRIOR_STORY_COMPLETION_CANDIDATE_SOURCE_ISSUE_NOT_ACTIONABLE"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "PRIOR_STORY_COMPLETION_CANDIDATE_SOURCE_ISSUE_NOT_ACTIONABLE",
                "message": "Old-story completion candidate source issue is not actionable.",
            },
        )
    if message.startswith("PRIOR_STORY_COMPLETION_CANDIDATE_REVISION_PROMPT_REQUIRED"):
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "PRIOR_STORY_COMPLETION_CANDIDATE_REVISION_PROMPT_REQUIRED",
                "message": "Old-story completion candidate revision requires user input.",
            },
        )
    if "schema is invalid" in message:
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_continuity_gate_service() -> ContinuityGateService:
    return scoped_story_service(continuity_gate_service, ContinuityGateService)


def active_issue_resolution_service() -> IssueResolutionService:
    gate_service = active_continuity_gate_service()
    if gate_service is continuity_gate_service:
        return issue_resolution_service
    return IssueResolutionService(
        store=gate_service.store,
        data_dir=gate_service.data_dir,
        continuity_gate_service=gate_service,
    )


def active_continuity_refresh_service() -> ContinuityResolutionRefreshService:
    gate_service = active_continuity_gate_service()
    return ContinuityResolutionRefreshService(
        store=gate_service.store,
        data_dir=gate_service.data_dir,
        repositories=gate_service.repositories,
    )


def active_continuity_option_service() -> ContinuityResolutionOptionExecutionService:
    gate_service = active_continuity_gate_service()
    resolution_service = active_issue_resolution_service()
    return ContinuityResolutionOptionExecutionService(
        store=gate_service.store,
        data_dir=gate_service.data_dir,
        repositories=gate_service.repositories,
        continuity_gate_service=gate_service,
        issue_resolution_service=resolution_service,
    )


def legacy_resolution_option_type(action_type: str) -> str:
    mapping = {
        "complete_prior_story": "complete_prior_story",
        "revise_current_scene": "revise_current_scene",
        "mark_as_misinformation_or_lie": "mark_as_claim_or_misinformation",
    }
    try:
        return mapping[action_type]
    except KeyError as exc:
        raise StorageError("CONTINUITY_RESOLUTION_ACTION_INVALID: Unsupported continuity resolution action.") from exc


@router.post("/check/scene/{scene_id}", response_model=ContinuityCheckResponse)
def check_scene_continuity(
    scene_id: str,
    mode: str = "manual",
) -> ContinuityCheckResponse:
    try:
        return active_continuity_gate_service().check_scene(scene_id, mode=mode)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.post(
    "/check/scene/{scene_id}/revision/{revision_id}",
    response_model=ContinuityCheckResponse,
)
def check_scene_revision_continuity(
    scene_id: str,
    revision_id: str,
    mode: str = "manual",
) -> ContinuityCheckResponse:
    try:
        return active_continuity_gate_service().check_scene_revision(
            scene_id,
            revision_id,
            mode=mode,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get("/issues", response_model=ContinuityIssueListResponse)
def list_continuity_issues(
    scene_id: str | None = None,
    target_type: str | None = None,
    status: str | None = None,
) -> ContinuityIssueListResponse:
    try:
        issues = active_continuity_gate_service().list_issues(
            scene_id=scene_id,
            target_type=target_type,
            status=status,
        )
        return ContinuityIssueListResponse(issues=issues, count=len(issues))
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get("/state", response_model=ContinuityResolutionRefreshResult)
def get_continuity_state(
    target_type: str = "scene",
    target_id: str = "",
    scene_id: str = "",
    revision_id: str = "",
    mode: str = "manual",
) -> ContinuityResolutionRefreshResult:
    try:
        clean_target_type = target_type if target_type in {"scene", "scene_revision"} else "scene"
        clean_target_id = target_id.strip()
        if clean_target_type == "scene" and not clean_target_id:
            clean_target_id = scene_id.strip()
        if clean_target_type == "scene_revision" and not clean_target_id:
            clean_target_id = revision_id.strip()
        if not clean_target_id:
            raise StorageError("CONTINUITY_TARGET_REQUIRED: target_id, scene_id, or revision_id is required.")
        return active_continuity_refresh_service().build_refresh_for_target(
            action_type="read_continuity_state",
            action_status="current_state",
            target_type=clean_target_type,
            target_id=clean_target_id,
            scene_id=scene_id,
            revision_id=revision_id,
            mode=mode or "manual",
            affected_issue_ids=[],
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get("/issues/{issue_id}")
def get_continuity_issue(issue_id: str) -> dict[str, Any]:
    try:
        return {
            "success": True,
            "issue": active_continuity_gate_service().get_issue(issue_id),
        }
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get("/resolution-options/matrix")
def get_continuity_resolution_options_matrix() -> dict[str, Any]:
    try:
        return active_continuity_option_service().matrix()
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get(
    "/issues/{issue_id}/resolution-options",
    response_model=ContinuityResolutionOptionAvailabilityReport,
)
def get_continuity_issue_resolution_options(
    issue_id: str,
) -> ContinuityResolutionOptionAvailabilityReport:
    try:
        return active_continuity_option_service().report_for_issue_id(issue_id)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.post(
    "/issues/{issue_id}/resolution-decisions",
    response_model=ContinuityResolutionOptionExecutionResult,
)
def create_continuity_resolution_decision(
    issue_id: str,
    request: ContinuityResolutionOptionExecutionRequest,
) -> ContinuityResolutionOptionExecutionResult:
    try:
        return active_continuity_option_service().execute(issue_id, request)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.post("/issues/{issue_id}/accept")
def accept_continuity_issue(
    issue_id: str,
    request: ContinuityIssueAcceptRequest,
) -> dict[str, Any]:
    try:
        issue, decision = active_continuity_gate_service().accept_issue(
            issue_id,
            request.user_input,
        )
        refresh = active_continuity_refresh_service().build_refresh_after_issue_action(
            action_type="accept_issue",
            action_status="accepted_issue",
            issue_id=issue.issue_id,
            affected_issue_ids=[issue.issue_id],
            recompute_quality_report=True,
        )
        return {"success": True, "issue": issue, "decision": decision, "refresh": refresh}
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.post("/issues/{issue_id}/resolve")
def resolve_continuity_issue(
    issue_id: str,
    request: ContinuityIssueResolveRequest,
) -> dict[str, Any]:
    try:
        result = active_continuity_option_service().execute(
            issue_id,
            ContinuityResolutionOptionExecutionRequest(
                option_type=legacy_resolution_option_type(request.action_type),
                user_input=request.user_input or "",
                revision_prompt=request.revision_prompt or "",
                truth_status=request.truth_status or "misinformation",
            ),
        )
        return result.model_dump(mode="json")
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.post(
    "/prior-story-completion-candidates/{candidate_id}/confirm",
    response_model=PriorStoryCompletionCandidateResponse,
)
def confirm_prior_story_completion_candidate(
    candidate_id: str,
    request: PriorStoryCompletionCandidateDecisionRequest,
) -> PriorStoryCompletionCandidateResponse:
    try:
        service = active_issue_resolution_service()
        candidate, decision = service.confirm_prior_story_completion_candidate(
            candidate_id,
            request.user_input or "",
        )
        refresh = service.refresh_for_candidate_action(
            candidate,
            action_type="confirm_prior_story_completion_candidate",
            action_status="confirmed_candidate",
            recompute_quality_report=True,
        )
        response = service.prior_story_completion_candidate_response(
            candidate,
            decision=decision,
            action_type="confirm_prior_story_completion_candidate",
            action_status="confirmed_candidate",
        )
        response.refresh = refresh
        return response
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.post(
    "/prior-story-completion-candidates/{candidate_id}/reject",
    response_model=PriorStoryCompletionCandidateResponse,
)
def reject_prior_story_completion_candidate(
    candidate_id: str,
    request: PriorStoryCompletionCandidateDecisionRequest,
) -> PriorStoryCompletionCandidateResponse:
    try:
        service = active_issue_resolution_service()
        candidate, decision = service.reject_prior_story_completion_candidate(
            candidate_id,
            request.user_input or "",
        )
        refresh = service.refresh_for_candidate_action(
            candidate,
            action_type="reject_prior_story_completion_candidate",
            action_status="rejected_candidate",
            recompute_quality_report=True,
        )
        response = service.prior_story_completion_candidate_response(
            candidate,
            decision=decision,
            action_type="reject_prior_story_completion_candidate",
            action_status="rejected_candidate",
        )
        response.refresh = refresh
        return response
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get(
    "/prior-story-completion-candidates/{candidate_id}",
    response_model=PriorStoryCompletionCandidateResponse,
)
def get_prior_story_completion_candidate(candidate_id: str) -> PriorStoryCompletionCandidateResponse:
    try:
        service = active_issue_resolution_service()
        candidate = service.get_prior_story_completion_candidate(candidate_id)
        return service.prior_story_completion_candidate_response(candidate)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get("/issues/{issue_id}/prior-story-completion-candidates")
def list_prior_story_completion_candidates_for_issue(issue_id: str) -> dict[str, Any]:
    try:
        service = active_issue_resolution_service()
        candidates = service.list_prior_story_completion_candidates_for_issue(issue_id)
        return {
            "success": True,
            "issue_id": issue_id,
            "candidates": candidates,
            "count": len(candidates),
        }
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.post(
    "/prior-story-completion-candidates/{candidate_id}/revise",
    response_model=PriorStoryCompletionCandidateResponse,
)
def revise_prior_story_completion_candidate(
    candidate_id: str,
    request: PriorStoryCompletionCandidateReviseRequest,
) -> PriorStoryCompletionCandidateResponse:
    try:
        service = active_issue_resolution_service()
        candidate, decision = service.revise_prior_story_completion_candidate(
            candidate_id,
            user_input=request.user_input,
            revision_prompt=request.revision_prompt,
        )
        return service.prior_story_completion_candidate_response(
            candidate,
            decision=decision,
            action_type="revise_prior_story_completion_candidate",
            action_status="created_revision_candidate",
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get(
    "/prior-story-completion-candidates/{candidate_id}/lineage",
    response_model=PriorStoryCompletionLineage,
)
def get_prior_story_completion_candidate_lineage(candidate_id: str) -> PriorStoryCompletionLineage:
    try:
        service = active_issue_resolution_service()
        candidate = service.get_prior_story_completion_candidate(candidate_id)
        return service.lineage_for_candidate(candidate)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.get(
    "/prior-story-completion-candidates/{candidate_id}/write-plan",
    response_model=PriorStoryCompletionCandidateWritePlan,
)
def get_prior_story_completion_candidate_write_plan(candidate_id: str) -> PriorStoryCompletionCandidateWritePlan:
    try:
        service = active_issue_resolution_service()
        candidate = service.get_prior_story_completion_candidate(candidate_id)
        return service.write_plan_for_candidate(candidate)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc


@router.post(
    "/issues/{issue_id}/prior-story-completion-candidates",
    response_model=PriorStoryCompletionCandidateResponse,
)
def create_prior_story_completion_candidate_for_issue(
    issue_id: str,
    request: PriorStoryCompletionCandidateDecisionRequest,
) -> PriorStoryCompletionCandidateResponse:
    try:
        result = active_continuity_option_service().execute(
            issue_id,
            ContinuityResolutionOptionExecutionRequest(
                option_type="complete_prior_story",
                user_input=request.user_input or "",
            ),
        )
        return PriorStoryCompletionCandidateResponse(**result.model_dump(mode="json"))
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise continuity_error_response(exc) from exc
