from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.backend.models.framework_module_library import (
    CopyrightSourceRecordListResponse,
    FrameworkLibraryActionRequest,
    FrameworkLibraryBuildFromAdapterDerivationRequest,
    FrameworkLibraryBuildFromConfirmedImportRequest,
    FrameworkLibraryBuildFromSelectedCandidatesRequest,
    FrameworkLibraryBuildFromVocabularyArtifactRequest,
    FrameworkLibraryBuildResult,
    FrameworkLibraryItemPatchRequest,
    FrameworkLibraryListResponse,
    FrameworkMaturityRecordListResponse,
    FrameworkModuleLibraryItem,
    FrameworkPatternListResponse,
    FrameworkPatternRecord,
    ModuleCompositionRule,
    ModuleCompositionRuleListResponse,
    SystemRecommendedFrameworkListResponse,
    UserPrivateFrameworkCreateRequest,
    UserPrivateFrameworkListResponse,
)
from app.backend.services.framework_module_library_service import (
    FrameworkModuleLibraryService,
)
from app.backend.storage.json_store import StorageError


router = APIRouter()
framework_library_service = FrameworkModuleLibraryService()


def model_to_response_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def storage_error_response(exc: StorageError) -> HTTPException:
    message = str(exc)
    if (
        "NOT_FOUND" in message
        or message.startswith("FRAMEWORK_LIBRARY_IMPORTED_DECISION_NOT_FOUND")
        or message.startswith("FRAMEWORK_LIBRARY_IMPORTED_SESSION_NOT_FOUND")
        or message.startswith("FRAMEWORK_LIBRARY_ADAPTER_DERIVATION_NOT_FOUND")
        or message.startswith("FRAMEWORK_LIBRARY_ADAPTER_CANDIDATE_NOT_FOUND")
    ):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("FRAMEWORK_LIBRARY_UNSAFE_PAYLOAD_BLOCKED"):
        return HTTPException(status_code=422, detail=message)
    if message.startswith("FRAMEWORK_LIBRARY_"):
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=500, detail=message)


def maybe_conflict(result: FrameworkLibraryBuildResult) -> FrameworkLibraryBuildResult | JSONResponse:
    if not result.success and result.build_report.build_status == "blocked":
        return JSONResponse(status_code=409, content=model_to_response_dict(result))
    return result


@router.post(
    "/items/from-confirmed-import",
    response_model=FrameworkLibraryBuildResult,
)
def build_items_from_confirmed_import(
    request: FrameworkLibraryBuildFromConfirmedImportRequest,
) -> FrameworkLibraryBuildResult | JSONResponse:
    try:
        return maybe_conflict(framework_library_service.build_from_confirmed_import(request))
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/items/from-adapter-derivation",
    response_model=FrameworkLibraryBuildResult,
)
def build_items_from_adapter_derivation(
    request: FrameworkLibraryBuildFromAdapterDerivationRequest,
) -> FrameworkLibraryBuildResult | JSONResponse:
    try:
        return maybe_conflict(framework_library_service.build_from_adapter_derivation(request))
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/items/from-selected-candidates",
    response_model=FrameworkLibraryBuildResult,
)
def build_items_from_selected_candidates(
    request: FrameworkLibraryBuildFromSelectedCandidatesRequest,
) -> FrameworkLibraryBuildResult | JSONResponse:
    try:
        return maybe_conflict(framework_library_service.build_from_selected_candidates(request))
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/items/from-vocabulary-artifact",
    response_model=FrameworkLibraryBuildResult,
)
def build_items_from_vocabulary_artifact(
    request: FrameworkLibraryBuildFromVocabularyArtifactRequest,
) -> FrameworkLibraryBuildResult | JSONResponse:
    try:
        return maybe_conflict(framework_library_service.build_from_vocabulary_artifact(request))
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/items", response_model=FrameworkLibraryListResponse)
def list_framework_library_items(
    item_type: str | None = None,
    source_type: str | None = None,
    visibility: str | None = None,
    maturity_level: str | None = None,
    risk_level: str | None = None,
) -> FrameworkLibraryListResponse:
    try:
        return framework_library_service.list_items(
            item_type=item_type,
            source_type=source_type,
            visibility=visibility,
            maturity_level=maturity_level,
            risk_level=risk_level,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/items/{library_item_id}", response_model=FrameworkModuleLibraryItem)
def get_framework_library_item(library_item_id: str) -> FrameworkModuleLibraryItem:
    try:
        return framework_library_service.get_item(library_item_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.patch("/items/{library_item_id}", response_model=FrameworkModuleLibraryItem)
def patch_framework_library_item(
    library_item_id: str,
    request: FrameworkLibraryItemPatchRequest,
) -> FrameworkModuleLibraryItem:
    try:
        return framework_library_service.patch_item(library_item_id, request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post("/items/{library_item_id}/archive", response_model=FrameworkModuleLibraryItem)
def archive_framework_library_item(
    library_item_id: str,
    request: FrameworkLibraryActionRequest | None = None,
) -> FrameworkModuleLibraryItem:
    try:
        return framework_library_service.archive_item(library_item_id, request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/patterns", response_model=FrameworkPatternListResponse)
def list_framework_library_patterns(
    pattern_type: str | None = None,
    source_type: str | None = None,
) -> FrameworkPatternListResponse:
    try:
        return framework_library_service.list_patterns(pattern_type=pattern_type, source_type=source_type)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/patterns/{pattern_id}", response_model=FrameworkPatternRecord)
def get_framework_library_pattern(pattern_id: str) -> FrameworkPatternRecord:
    try:
        return framework_library_service.get_pattern(pattern_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/composition-rules", response_model=ModuleCompositionRuleListResponse)
def list_framework_library_composition_rules(
    status: str | None = None,
) -> ModuleCompositionRuleListResponse:
    try:
        return framework_library_service.list_composition_rules(status=status)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/composition-rules/{rule_id}", response_model=ModuleCompositionRule)
def get_framework_library_composition_rule(rule_id: str) -> ModuleCompositionRule:
    try:
        return framework_library_service.get_composition_rule(rule_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post("/composition-rules/{rule_id}/mark-reviewed", response_model=ModuleCompositionRule)
def mark_framework_library_composition_rule_reviewed(
    rule_id: str,
    request: FrameworkLibraryActionRequest | None = None,
) -> ModuleCompositionRule:
    try:
        return framework_library_service.mark_composition_rule_reviewed(rule_id, request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post("/composition-rules/{rule_id}/reject", response_model=ModuleCompositionRule)
def reject_framework_library_composition_rule(
    rule_id: str,
    request: FrameworkLibraryActionRequest | None = None,
) -> ModuleCompositionRule:
    try:
        return framework_library_service.reject_composition_rule(rule_id, request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/maturity-records", response_model=FrameworkMaturityRecordListResponse)
def list_framework_library_maturity_records() -> FrameworkMaturityRecordListResponse:
    try:
        return framework_library_service.list_maturity_records()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/copyright-sources", response_model=CopyrightSourceRecordListResponse)
def list_framework_library_copyright_sources(
    risk_level: str | None = None,
) -> CopyrightSourceRecordListResponse:
    try:
        return framework_library_service.list_copyright_sources(risk_level=risk_level)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post("/private-frameworks", response_model=FrameworkLibraryBuildResult)
def create_framework_library_private_framework(
    request: UserPrivateFrameworkCreateRequest,
) -> FrameworkLibraryBuildResult:
    try:
        return framework_library_service.create_private_framework(request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/private-frameworks", response_model=UserPrivateFrameworkListResponse)
def list_framework_library_private_frameworks() -> UserPrivateFrameworkListResponse:
    try:
        return framework_library_service.list_private_frameworks()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/system-recommendations", response_model=SystemRecommendedFrameworkListResponse)
def list_framework_library_system_recommendations() -> SystemRecommendedFrameworkListResponse:
    try:
        return framework_library_service.list_system_recommendations()
    except StorageError as exc:
        raise storage_error_response(exc) from exc
