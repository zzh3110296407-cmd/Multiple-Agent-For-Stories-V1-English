from fastapi import APIRouter, HTTPException

from ..api import formal_apply_execution as execution_api
from ..models.formal_apply_execution import (
    ChapterArchiveProposal,
    ChapterArchiveProposalListResponse,
    FormalApplyProposalListResponse,
    FormalApplyProposalStatusResponse,
    FrameworkApplyProposal,
    FrameworkApplyProposalListResponse,
    NarrativeDebtProposal,
    NarrativeDebtProposalListResponse,
)
from ..storage.json_store import StorageError


router = APIRouter()


def _raise_http(exc: StorageError) -> None:
    message = str(exc)
    if "UNSAFE_PAYLOAD_BLOCKED" in message:
        raise HTTPException(status_code=422, detail=message) from exc
    if "_NOT_FOUND" in message or "NOT_FOUND" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    raise HTTPException(status_code=500, detail=message) from exc


@router.get("/status", response_model=FormalApplyProposalStatusResponse)
def get_formal_apply_proposal_status() -> FormalApplyProposalStatusResponse:
    try:
        return execution_api.controlled_formal_apply_executor_service.get_proposal_status()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/", response_model=FormalApplyProposalListResponse)
def list_formal_apply_proposals() -> FormalApplyProposalListResponse:
    try:
        return execution_api.controlled_formal_apply_executor_service.list_all_proposals()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/framework", response_model=FrameworkApplyProposalListResponse)
def list_framework_apply_proposals() -> FrameworkApplyProposalListResponse:
    try:
        return execution_api.controlled_formal_apply_executor_service.list_framework_proposals()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/chapter-archive", response_model=ChapterArchiveProposalListResponse)
def list_chapter_archive_proposals() -> ChapterArchiveProposalListResponse:
    try:
        return execution_api.controlled_formal_apply_executor_service.list_chapter_archive_proposals()
    except StorageError as exc:
        _raise_http(exc)


@router.get("/narrative-debt", response_model=NarrativeDebtProposalListResponse)
def list_narrative_debt_proposals() -> NarrativeDebtProposalListResponse:
    try:
        return execution_api.controlled_formal_apply_executor_service.list_narrative_debt_proposals()
    except StorageError as exc:
        _raise_http(exc)


@router.get(
    "/items/{proposal_id}",
    response_model=FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal,
)
def get_formal_apply_proposal(
    proposal_id: str,
) -> FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal:
    try:
        return execution_api.controlled_formal_apply_executor_service.get_proposal(proposal_id)
    except StorageError as exc:
        _raise_http(exc)
