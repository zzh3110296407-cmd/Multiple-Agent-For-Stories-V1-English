from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ValidationError

from app.backend.models.narrative_layer import (
    ApparentContradictionCreateRequest,
    ApparentContradictionRecord,
    CharacterExpressionRecord,
    CharacterExpressionRecordCreateRequest,
    CharacterPsychologyTrace,
    CharacterPsychologyTraceCreateRequest,
    ClaimRecord,
    ClaimRecordCreateRequest,
    NarrativeDebt,
    NarrativeDebtCreateRequest,
    NarrativeDebtListResponse,
    NarrativeIntentCreateRequest,
    NarrativeIntentRecord,
    NarrativeLayerSceneRecords,
    NarrativeRecordUpdateRequest,
    PerceptionStateRecord,
    PerceptionStateRecordCreateRequest,
)
from app.backend.services.narrative_layer_service import NarrativeLayerService
from app.backend.services.narrative_debt_service import NarrativeDebtService
from app.backend.storage.json_store import StorageError


router = APIRouter()
narrative_layer_service = NarrativeLayerService()
narrative_debt_service = NarrativeDebtService()


class NarrativeDebtActionRequest(BaseModel):
    user_input: str = ""
    payoff_scene_id: str = ""
    note: str = ""


@router.get("/scene/{scene_id}/records", response_model=NarrativeLayerSceneRecords)
def get_scene_records(scene_id: str) -> NarrativeLayerSceneRecords:
    try:
        return narrative_layer_service.get_scene_records(scene_id)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/debts", response_model=NarrativeDebtListResponse)
def list_narrative_debts(
    status: str | None = Query(default=None),
    scene_id: str | None = Query(default=None),
    chapter_id: str | None = Query(default=None),
) -> NarrativeDebtListResponse:
    try:
        return narrative_layer_service.list_narrative_debts(
            status=status,
            scene_id=scene_id,
            chapter_id=chapter_id,
        )
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/debts/visibility-summary")
def get_narrative_debt_visibility_summary(
    scene_id: str | None = Query(default=None),
    chapter_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        return narrative_debt_service.visibility_summary(
            scene_id=scene_id,
            chapter_id=chapter_id,
        )
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/debts/{narrative_debt_id}")
def get_narrative_debt(narrative_debt_id: str) -> dict[str, Any]:
    try:
        return narrative_debt_service.safe_debt_detail(narrative_debt_id)
    except StorageError as exc:
        status_code = 404 if "not found" in str(exc).casefold() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/claims", response_model=ClaimRecord)
def create_claim(request: ClaimRecordCreateRequest) -> ClaimRecord:
    return _run_create(lambda: narrative_layer_service.create_claim(request.record))


@router.patch("/claims/{claim_id}", response_model=ClaimRecord)
def update_claim(
    claim_id: str,
    request: NarrativeRecordUpdateRequest,
) -> ClaimRecord:
    return _run_update(
        lambda: narrative_layer_service.update_claim(claim_id, request.record)
    )


@router.post("/intents", response_model=NarrativeIntentRecord)
def create_narrative_intent(
    request: NarrativeIntentCreateRequest,
) -> NarrativeIntentRecord:
    return _run_create(
        lambda: narrative_layer_service.create_narrative_intent(request.record)
    )


@router.patch("/intents/{narrative_intent_id}", response_model=NarrativeIntentRecord)
def update_narrative_intent(
    narrative_intent_id: str,
    request: NarrativeRecordUpdateRequest,
) -> NarrativeIntentRecord:
    return _run_update(
        lambda: narrative_layer_service.update_narrative_intent(
            narrative_intent_id,
            request.record,
        )
    )


@router.post("/psychology-traces", response_model=CharacterPsychologyTrace)
def create_psychology_trace(
    request: CharacterPsychologyTraceCreateRequest,
) -> CharacterPsychologyTrace:
    return _run_create(
        lambda: narrative_layer_service.create_psychology_trace(request.record)
    )


@router.patch(
    "/psychology-traces/{psychology_trace_id}",
    response_model=CharacterPsychologyTrace,
)
def update_psychology_trace(
    psychology_trace_id: str,
    request: NarrativeRecordUpdateRequest,
) -> CharacterPsychologyTrace:
    return _run_update(
        lambda: narrative_layer_service.update_psychology_trace(
            psychology_trace_id,
            request.record,
        )
    )


@router.post("/expression-records", response_model=CharacterExpressionRecord)
def create_expression_record(
    request: CharacterExpressionRecordCreateRequest,
) -> CharacterExpressionRecord:
    return _run_create(
        lambda: narrative_layer_service.create_expression_record(request.record)
    )


@router.patch(
    "/expression-records/{expression_record_id}",
    response_model=CharacterExpressionRecord,
)
def update_expression_record(
    expression_record_id: str,
    request: NarrativeRecordUpdateRequest,
) -> CharacterExpressionRecord:
    return _run_update(
        lambda: narrative_layer_service.update_expression_record(
            expression_record_id,
            request.record,
        )
    )


@router.post("/perceptions", response_model=PerceptionStateRecord)
def create_perception_state(
    request: PerceptionStateRecordCreateRequest,
) -> PerceptionStateRecord:
    return _run_create(
        lambda: narrative_layer_service.create_perception_state(request.record)
    )


@router.patch("/perceptions/{perception_state_id}", response_model=PerceptionStateRecord)
def update_perception_state(
    perception_state_id: str,
    request: NarrativeRecordUpdateRequest,
) -> PerceptionStateRecord:
    return _run_update(
        lambda: narrative_layer_service.update_perception_state(
            perception_state_id,
            request.record,
        )
    )


@router.post(
    "/apparent-contradictions",
    response_model=ApparentContradictionRecord,
)
def create_apparent_contradiction(
    request: ApparentContradictionCreateRequest,
) -> ApparentContradictionRecord:
    return _run_create(
        lambda: narrative_layer_service.create_apparent_contradiction(request.record)
    )


@router.patch(
    "/apparent-contradictions/{apparent_contradiction_id}",
    response_model=ApparentContradictionRecord,
)
def update_apparent_contradiction(
    apparent_contradiction_id: str,
    request: NarrativeRecordUpdateRequest,
) -> ApparentContradictionRecord:
    return _run_update(
        lambda: narrative_layer_service.update_apparent_contradiction(
            apparent_contradiction_id,
            request.record,
        )
    )


@router.post("/debts", response_model=NarrativeDebt)
def create_narrative_debt(request: NarrativeDebtCreateRequest) -> NarrativeDebt:
    return _run_create(
        lambda: narrative_layer_service.create_narrative_debt(request.record)
    )


@router.patch("/debts/{narrative_debt_id}", response_model=NarrativeDebt)
def update_narrative_debt(
    narrative_debt_id: str,
    request: NarrativeRecordUpdateRequest,
) -> NarrativeDebt:
    return _run_update(
        lambda: narrative_debt_service.patch_debt(
            narrative_debt_id,
            request.record,
        )
    )


@router.post("/debts/{narrative_debt_id}/mark-paid-off", response_model=NarrativeDebt)
def mark_narrative_debt_paid_off(
    narrative_debt_id: str,
    request: NarrativeDebtActionRequest,
) -> NarrativeDebt:
    return _run_update(
        lambda: narrative_debt_service.mark_paid_off(
            narrative_debt_id,
            user_input=request.user_input,
            payoff_scene_id=request.payoff_scene_id,
            note=request.note,
        )
    )


@router.post(
    "/debts/{narrative_debt_id}/mark-intentionally-open",
    response_model=NarrativeDebt,
)
def mark_narrative_debt_intentionally_open(
    narrative_debt_id: str,
    request: NarrativeDebtActionRequest,
) -> NarrativeDebt:
    return _run_update(
        lambda: narrative_debt_service.mark_intentionally_open(
            narrative_debt_id,
            user_input=request.user_input,
            note=request.note,
        )
    )


@router.post("/debts/{narrative_debt_id}/reject", response_model=NarrativeDebt)
def reject_narrative_debt(
    narrative_debt_id: str,
    request: NarrativeDebtActionRequest,
) -> NarrativeDebt:
    return _run_update(
        lambda: narrative_debt_service.reject(
            narrative_debt_id,
            user_input=request.user_input,
            note=request.note,
        )
    )


def _run_create(operation):
    try:
        return operation()
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _run_update(operation):
    try:
        return operation()
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        status_code = 404 if "not found" in str(exc).casefold() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
