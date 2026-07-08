from fastapi import APIRouter, HTTPException

from app.backend.models.framework_package import (
    ChapterFramework,
    ChapterFrameworkBuildContext,
    ChapterFrameworkBuildCurrentRequest,
    ChapterFrameworkBuildReason,
    ChapterFrameworkBuildRequest,
    ChapterFrameworkBuildResult,
    ChapterFrameworkResponse,
    FrameworkPackage,
    FrameworkPackageSeedResponse,
    FrameworkPackageValidationResponse,
    FrameworkWorkbenchAssignmentUpdateRequest,
    FrameworkWorkbenchChapterCountRequest,
    FrameworkWorkbenchConfirmRequest,
    FrameworkWorkbenchRecommendRequest,
    FrameworkWorkbenchState,
    MacroAssignmentRequest,
    MacroAssignmentResponse,
)
from app.backend.api.story_workspace_scope import scoped_story_service
from app.backend.services.chapter_framework_builder_service import (
    ChapterFrameworkBuilderService,
)
from app.backend.services.active_project_boundary_service import ActiveProjectStoryDataBlocked
from app.backend.services.framework_package_service import FrameworkPackageService
from app.backend.storage.json_store import StorageError

router = APIRouter()
framework_package_service = FrameworkPackageService()
chapter_framework_builder_service = ChapterFrameworkBuilderService()


def storage_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, ActiveProjectStoryDataBlocked):
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "STORY_DATA_SETUP_REQUIRED_FOR_ACTIVE_PROJECT",
                "message": "Story workspace data is not available for the active project.",
            },
        )
    message = str(exc)
    if message.startswith("M1_FRAMEWORK_MAPPING_NOT_CONFIRMED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CURRENT_CHAPTER_FRAMEWORK_ALREADY_EXISTS"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CURRENT_CHAPTER_FRAMEWORK_MISSING"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("CHAPTER_FRAMEWORK_BUILD_CONTEXT_MISSING"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("chapter_framework_project_story_premise_missing"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CHAPTER_FRAMEWORK_AUDIT_MISSING"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("CHAPTER_FRAMEWORK_M4_CONTEXT_MISSING"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("LEGACY_CHAPTER_FRAMEWORK_WRITE_DISABLED"):
        return HTTPException(status_code=409, detail=message)
    if (
        message.startswith("CURRENT_CHAPTER_ASSIGNMENT_MISSING")
        or message.startswith("CURRENT_CHAPTER_INDEX_INVALID")
        or message.startswith("CURRENT_CHAPTER_ID_INDEX_MISMATCH")
        or message.startswith("LINKED_MACRO_COMPONENT_UNKNOWN")
        or message.startswith("LOCAL_COMPONENT_VOCABULARY_CORRUPT")
        or message.startswith("FRAMEWORK_PACKAGE_MISSING")
        or message.startswith("FRAMEWORK_PACKAGE_INVALID")
    ):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("CHAPTER_FRAMEWORK_COMMIT_NOT_ALLOWED"):
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CHAPTER_FRAMEWORK_COMMIT_NOT_ALLOWED",
                "message": "Chapter plan must be confirmed before writing built chapter frameworks.",
            },
        )
    if message.startswith("WORKBENCH_CONFIRM_BLOCKED"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("WORKBENCH_CONFIRM_REQUIRES_WARNING_ACCEPTANCE"):
        return HTTPException(status_code=409, detail=message)
    if "does not exist" in message or "does not exist for this chapter_index" in message:
        return HTTPException(status_code=404, detail=message)
    if (
        "must be greater than 0" in message
        or "No chapter macro assignment" in message
        or "chapter_count must be between" in message
        or "Unknown macro component id" in message
        or "linked_macro_component_ids must not be empty" in message
    ):
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


def active_framework_package_service() -> FrameworkPackageService:
    return scoped_story_service(framework_package_service, FrameworkPackageService)


def active_chapter_framework_builder_service() -> ChapterFrameworkBuilderService:
    return scoped_story_service(
        chapter_framework_builder_service,
        ChapterFrameworkBuilderService,
    )


@router.get("", response_model=FrameworkPackage)
def get_framework_package() -> FrameworkPackage:
    try:
        return active_framework_package_service().get_framework_package()
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.post("/seed", response_model=FrameworkPackageSeedResponse)
def seed_framework_package() -> FrameworkPackageSeedResponse:
    try:
        return active_framework_package_service().ensure_default_framework_package()
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.post("/macro-assignments", response_model=MacroAssignmentResponse)
def assign_macro_components(
    request: MacroAssignmentRequest,
) -> MacroAssignmentResponse:
    try:
        return active_framework_package_service().assign_macro_components(
            chapter_count=request.chapter_count,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.get("/workbench", response_model=FrameworkWorkbenchState)
def get_framework_workbench() -> FrameworkWorkbenchState:
    try:
        return active_framework_package_service().get_workbench_state()
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.post("/workbench/recommend", response_model=FrameworkWorkbenchState)
def recommend_framework_workbench_mapping(
    request: FrameworkWorkbenchRecommendRequest,
) -> FrameworkWorkbenchState:
    try:
        return active_framework_package_service().recommend_mapping(
            chapter_count=request.chapter_count,
            strategy=request.strategy,
            accept_warnings=request.accept_warnings,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.post("/workbench/chapter-count", response_model=FrameworkWorkbenchState)
def update_framework_workbench_chapter_count(
    request: FrameworkWorkbenchChapterCountRequest,
) -> FrameworkWorkbenchState:
    try:
        return active_framework_package_service().update_chapter_count(
            chapter_count=request.chapter_count,
            recompute_mapping=request.recompute_mapping,
            accept_warnings=request.accept_warnings,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.patch("/workbench/assignments/{chapter_index}", response_model=FrameworkWorkbenchState)
def update_framework_workbench_assignment(
    chapter_index: int,
    request: FrameworkWorkbenchAssignmentUpdateRequest,
) -> FrameworkWorkbenchState:
    try:
        return active_framework_package_service().update_assignment(
            chapter_index=chapter_index,
            linked_macro_component_ids=request.linked_macro_component_ids,
            accept_warnings=request.accept_warnings,
            user_input=request.user_input,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.get("/workbench/validate", response_model=FrameworkWorkbenchState)
def validate_framework_workbench_mapping() -> FrameworkWorkbenchState:
    try:
        service = active_framework_package_service()
        report = service.validate_workbench_mapping()
        return service.get_workbench_state(validation_report=report)
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.post("/workbench/confirm", response_model=FrameworkWorkbenchState)
def confirm_framework_workbench_mapping(
    request: FrameworkWorkbenchConfirmRequest,
) -> FrameworkWorkbenchState:
    try:
        return active_framework_package_service().confirm_mapping(
            user_input=request.user_input,
            accept_warnings=request.accept_warnings,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.post("/chapter-framework", response_model=ChapterFrameworkResponse)
def build_chapter_framework(
    request: ChapterFrameworkBuildRequest,
) -> ChapterFrameworkResponse:
    try:
        result = active_chapter_framework_builder_service().build_for_current_chapter(
            chapter_index=request.chapter_index,
            chapter_id=request.chapter_id,
            latest_user_intent_summary=request.user_intent_snapshot,
            force_rebuild=False,
        )
        package = active_framework_package_service().get_framework_package()
        return ChapterFrameworkResponse(
            chapter_framework=result.chapter_framework,
            package=package,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/chapter-framework/build-current",
    response_model=ChapterFrameworkBuildResult,
)
def build_current_chapter_framework(
    request: ChapterFrameworkBuildCurrentRequest,
) -> ChapterFrameworkBuildResult:
    try:
        return active_chapter_framework_builder_service().build_for_current_chapter(
            chapter_id=request.chapter_id,
            chapter_index=request.chapter_index,
            latest_user_intent_summary=request.latest_user_intent_summary,
            previous_chapter_archive_id=request.previous_chapter_archive_id,
            previous_chapter_archive_status=request.previous_chapter_archive_status,
            previous_chapter_outcome_summary=request.previous_chapter_outcome_summary,
            force_rebuild=request.force_rebuild,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/chapter-framework/current",
    response_model=ChapterFrameworkBuildResult,
)
def get_current_chapter_framework_build(
    chapter_id: str | None = None,
    chapter_index: int | None = None,
) -> ChapterFrameworkBuildResult:
    try:
        return active_chapter_framework_builder_service().get_current_chapter_framework(
            chapter_id=chapter_id,
            chapter_index=chapter_index,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/chapter-framework/{chapter_framework_id}/build-context",
    response_model=ChapterFrameworkBuildContext,
)
def get_chapter_framework_build_context(
    chapter_framework_id: str,
) -> ChapterFrameworkBuildContext:
    try:
        return active_chapter_framework_builder_service().get_build_context(
            chapter_framework_id,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/chapter-framework/{chapter_framework_id}/build-reasons",
    response_model=list[ChapterFrameworkBuildReason],
)
def get_chapter_framework_build_reasons(
    chapter_framework_id: str,
) -> list[ChapterFrameworkBuildReason]:
    try:
        return active_chapter_framework_builder_service().get_build_reasons(
            chapter_framework_id,
        )
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.get("/chapter-framework/{chapter_index}", response_model=ChapterFramework)
def get_chapter_framework(chapter_index: int) -> ChapterFramework:
    try:
        result = active_chapter_framework_builder_service().get_current_chapter_framework(
            chapter_index=chapter_index,
        )
        return result.chapter_framework
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc


@router.get("/validate", response_model=FrameworkPackageValidationResponse)
def validate_framework_package() -> FrameworkPackageValidationResponse:
    try:
        return active_framework_package_service().validate_framework_package()
    except (ActiveProjectStoryDataBlocked, StorageError) as exc:
        raise storage_error_response(exc) from exc
