import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.backend.models.analyze_stories_import import (
    AnalyzeStoriesImportDetail,
    AnalyzeStoriesImportListResponse,
    AnalyzeStoriesImportManifest,
    AnalyzeStoriesImportResult,
    AnalyzeStoriesImportValidationReport,
)
from app.backend.models.analyze_stories_adapter import (
    AnalyzeStoriesAdapterCandidateActionRequest,
    AnalyzeStoriesAdapterCandidateActionResult,
    AnalyzeStoriesAdapterCandidateDetail,
    AnalyzeStoriesAdapterCandidateListResponse,
    AnalyzeStoriesAdapterDerivationListResponse,
    AnalyzeStoriesAdapterDerivationReport,
    AnalyzeStoriesAdapterDerivationRequest,
    AnalyzeStoriesAdapterDerivationResult,
)
from app.backend.models.analysis_report_viewer import (
    AnalysisReportViewerActionRequest,
    AnalysisReportViewerDetail,
    AnalysisReportViewerListResponse,
    AnalysisReportViewerResult,
    AnalysisReportViewerReviewResult,
)
from app.backend.models.framework_package_candidate import (
    FrameworkPackageCandidateDetail,
    FrameworkPackageCandidateListResponse,
    FrameworkPackageCandidateResult,
    FrameworkPackageNormalizationReport,
)
from app.backend.models.full_book_bundle_validation import (
    BundleChapterInventory,
    CrossChapterStateReferenceCheck,
    FullBookBundleDetail,
    FullBookBundleListResponse,
    FullBookBundleValidationReport,
    FullBookBundleValidationRequest,
    FullBookBundleValidationResult,
)
from app.backend.models.imported_framework_workbench import (
    ImportedFrameworkActionRequest,
    ImportedFrameworkDecisionResult,
    ImportedFrameworkListResponse,
    ImportedFrameworkPlanResult,
    ImportedFrameworkSessionResult,
    ImportedFrameworkWorkbenchState,
)
from app.backend.services.analyze_stories_import_service import (
    AnalyzeStoriesImportService,
)
from app.backend.services.analyze_stories_adapter_service import (
    AnalyzeStoriesAdapterService,
)
from app.backend.services.analysis_report_viewer_service import (
    AnalysisReportViewerService,
)
from app.backend.services.framework_package_candidate_service import (
    FrameworkPackageCandidateService,
)
from app.backend.services.full_book_bundle_validation_service import (
    FullBookBundleValidationService,
)
from app.backend.services.imported_framework_workbench_service import (
    ImportedFrameworkWorkbenchService,
)
from app.backend.storage.json_store import StorageError
from app.backend.core.config import settings
from app.backend.core.request_limits import read_limited_request_body


router = APIRouter()
analyze_stories_import_service = AnalyzeStoriesImportService()
framework_package_candidate_service = FrameworkPackageCandidateService(
    analyze_import_service=analyze_stories_import_service,
)
analysis_report_viewer_service = AnalysisReportViewerService(
    analyze_import_service=analyze_stories_import_service,
    framework_candidate_service=framework_package_candidate_service,
)
imported_framework_workbench_service = ImportedFrameworkWorkbenchService(
    framework_candidate_service=framework_package_candidate_service,
    analysis_report_viewer_service=analysis_report_viewer_service,
)
full_book_bundle_validation_service = FullBookBundleValidationService(
    analyze_import_service=analyze_stories_import_service,
    framework_candidate_service=framework_package_candidate_service,
    analysis_report_viewer_service=analysis_report_viewer_service,
)
analyze_stories_adapter_service = AnalyzeStoriesAdapterService(
    bundle_service=full_book_bundle_validation_service,
    analysis_report_viewer_service=analysis_report_viewer_service,
    imported_framework_workbench_service=imported_framework_workbench_service,
)


class CreateAnalysisReportViewerRequest(BaseModel):
    report_ref_id: str


def model_to_response_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def model_json_response(model: Any, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=model_to_response_dict(model))


def storage_error_response(exc: StorageError) -> HTTPException:
    message = str(exc)
    if message.startswith("ANALYZE_STORIES_IMPORT_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("ANALYZE_STORIES_VALIDATION_REPORT_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("ANALYZE_STORIES_ARTIFACT_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("FRAMEWORK_PACKAGE_CANDIDATE_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("FRAMEWORK_PACKAGE_NORMALIZATION_REPORT_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("FRAMEWORK_PACKAGE_IMPORT_NOT_READY_FOR_M2"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("STORY_ANALYSIS_REPORT_REF_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("ANALYSIS_REPORT_VIEWER_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("ANALYSIS_REPORT_VIEWER_UNSAFE_NOTE_BLOCKED"):
        return HTTPException(status_code=422, detail=message)
    if message.startswith("FULL_BOOK_BUNDLE_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("FULL_BOOK_BUNDLE_VALIDATION_REPORT_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("FULL_BOOK_BUNDLE_ARTIFACT_NOT_READY"):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("FULL_BOOK_BUNDLE_UNSAFE_PAYLOAD_BLOCKED"):
        return HTTPException(status_code=422, detail=message)
    if message.startswith("FULL_BOOK_BUNDLE_"):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("IMPORTED_FRAMEWORK_EDIT_SESSION_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("IMPORTED_FRAMEWORK_ACTIVATION_PLAN_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("IMPORTED_FRAMEWORK_UNSAFE_PAYLOAD_BLOCKED"):
        return HTTPException(status_code=422, detail=message)
    if message.startswith("IMPORTED_FRAMEWORK_CONFIRM_REQUIRES_WARNING_ACCEPTANCE"):
        return HTTPException(status_code=409, detail=message)
    if (
        message.startswith("IMPORTED_FRAMEWORK_CANDIDATE_NOT_READY")
        or message.startswith("IMPORTED_FRAMEWORK_SESSION_CLOSED")
        or message.startswith("IMPORTED_FRAMEWORK_PLAN_NOT_CONFIRMABLE")
        or message.startswith("IMPORTED_FRAMEWORK_CONFIRM_BLOCKED")
        or message.startswith("IMPORTED_FRAMEWORK_SET_ACTIVE_NOT_READY")
    ):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("IMPORTED_FRAMEWORK_"):
        return HTTPException(status_code=400, detail=message)
    if message.startswith("ANALYZE_STORIES_ADAPTER_DERIVATION_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("ANALYZE_STORIES_ADAPTER_CANDIDATE_NOT_FOUND"):
        return HTTPException(status_code=404, detail=message)
    if message.startswith("ANALYZE_STORIES_ADAPTER_UNSAFE_NOTE_BLOCKED"):
        return HTTPException(status_code=422, detail=message)
    if (
        message.startswith("ANALYZE_STORIES_ADAPTER_CANDIDATE_BLOCKED")
        or message.startswith("ANALYZE_STORIES_ADAPTER_INVALID_STATUS_TRANSITION")
    ):
        return HTTPException(status_code=409, detail=message)
    if message.startswith("ANALYZE_STORIES_ADAPTER_"):
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


@router.post("/imports", response_model=AnalyzeStoriesImportResult)
async def import_analyze_stories_payload(request: Request) -> AnalyzeStoriesImportResult:
    body = await read_limited_request_body(
        request,
        max_bytes=settings.max_analyze_stories_body_bytes,
    )
    original_filename = request.headers.get("x-original-filename")
    verification_scope = request.headers.get("x-verification-scope") or "user_upload"
    try:
        payload: Any = json.loads(body.decode("utf-8") if body else "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return model_json_response(
            analyze_stories_import_service.import_parse_failure(
                body,
                original_filename=original_filename,
                verification_scope=verification_scope,
            ),
            status_code=400,
        )
    if not isinstance(payload, dict):
        return model_json_response(
            analyze_stories_import_service.import_parse_failure(
                body,
                original_filename=original_filename,
                verification_scope=verification_scope,
            ),
            status_code=400,
        )
    declared_file_kind = None
    artifact = payload
    if "artifact" in payload:
        declared_file_kind = (
            str(payload.get("declared_file_kind")).strip()
            if payload.get("declared_file_kind") is not None
            else None
        )
        original_filename = (
            str(payload.get("original_filename")).strip()
            if payload.get("original_filename") is not None
            else original_filename
        )
        artifact_value = payload.get("artifact")
        if not isinstance(artifact_value, dict):
            return model_json_response(
                analyze_stories_import_service.import_parse_failure(
                    body,
                    original_filename=original_filename,
                    verification_scope=verification_scope,
                ),
                status_code=400,
            )
        artifact = artifact_value
    try:
        return analyze_stories_import_service.import_json(
            artifact,
            declared_file_kind=declared_file_kind,
            original_filename=original_filename,
            verification_scope=verification_scope,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/imports", response_model=AnalyzeStoriesImportListResponse)
def list_analyze_stories_imports() -> AnalyzeStoriesImportListResponse:
    try:
        return analyze_stories_import_service.list_imports()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/imports/{import_id}", response_model=AnalyzeStoriesImportDetail)
def get_analyze_stories_import(import_id: str) -> AnalyzeStoriesImportDetail:
    try:
        return analyze_stories_import_service.get_detail(import_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/imports/{import_id}/manifest",
    response_model=AnalyzeStoriesImportManifest,
)
def get_analyze_stories_import_manifest(import_id: str) -> AnalyzeStoriesImportManifest:
    try:
        return analyze_stories_import_service.get_manifest(import_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/imports/{import_id}/validation-report",
    response_model=AnalyzeStoriesImportValidationReport,
)
def get_analyze_stories_import_validation_report(
    import_id: str,
) -> AnalyzeStoriesImportValidationReport:
    try:
        return analyze_stories_import_service.get_validation_report(import_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post("/imports/{import_id}/revalidate", response_model=AnalyzeStoriesImportResult)
def revalidate_analyze_stories_import(import_id: str) -> AnalyzeStoriesImportResult:
    try:
        return analyze_stories_import_service.revalidate(import_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/imports/{import_id}/bundle-validation",
    response_model=FullBookBundleValidationResult,
)
def validate_full_book_bundle_from_import(
    import_id: str,
    request: FullBookBundleValidationRequest | None = None,
) -> FullBookBundleValidationResult:
    try:
        return full_book_bundle_validation_service.validate_bundle_from_import(
            import_id,
            artifact_id=request.artifact_id if request else None,
            linked_framework_candidate_id=(
                request.linked_framework_candidate_id if request else None
            ),
            linked_story_analysis_report_ref_id=(
                request.linked_story_analysis_report_ref_id if request else None
            ),
            linked_framework_candidate_ids=(
                request.linked_framework_candidate_ids if request else None
            ),
            linked_story_analysis_report_ref_ids=(
                request.linked_story_analysis_report_ref_ids if request else None
            ),
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/bundles", response_model=FullBookBundleListResponse)
def list_full_book_bundles() -> FullBookBundleListResponse:
    try:
        return full_book_bundle_validation_service.list_bundles()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get("/bundles/{bundle_manifest_id}", response_model=FullBookBundleDetail)
def get_full_book_bundle(bundle_manifest_id: str) -> FullBookBundleDetail:
    try:
        return full_book_bundle_validation_service.get_bundle(bundle_manifest_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/bundles/{bundle_manifest_id}/validation-report",
    response_model=FullBookBundleValidationReport,
)
def get_full_book_bundle_validation_report(
    bundle_manifest_id: str,
) -> FullBookBundleValidationReport:
    try:
        return full_book_bundle_validation_service.get_validation_report(
            bundle_manifest_id
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/bundles/{bundle_manifest_id}/chapter-inventory",
    response_model=BundleChapterInventory,
)
def get_full_book_bundle_chapter_inventory(
    bundle_manifest_id: str,
) -> BundleChapterInventory:
    try:
        return full_book_bundle_validation_service.get_chapter_inventory(
            bundle_manifest_id
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/bundles/{bundle_manifest_id}/cross-chapter-ref-checks",
    response_model=CrossChapterStateReferenceCheck,
)
def get_full_book_bundle_cross_chapter_ref_checks(
    bundle_manifest_id: str,
) -> CrossChapterStateReferenceCheck:
    try:
        return full_book_bundle_validation_service.get_cross_chapter_reference_check(
            bundle_manifest_id
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/bundles/{bundle_manifest_id}/revalidate",
    response_model=FullBookBundleValidationResult,
)
def revalidate_full_book_bundle(
    bundle_manifest_id: str,
) -> FullBookBundleValidationResult:
    try:
        return full_book_bundle_validation_service.revalidate_bundle(bundle_manifest_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/bundles/{bundle_manifest_id}/adapter-derivations",
    response_model=AnalyzeStoriesAdapterDerivationResult,
)
def derive_adapter_candidates_from_bundle(
    bundle_manifest_id: str,
    request: AnalyzeStoriesAdapterDerivationRequest | None = None,
) -> AnalyzeStoriesAdapterDerivationResult | JSONResponse:
    try:
        result = analyze_stories_adapter_service.derive_from_bundle(
            bundle_manifest_id,
            request=request,
        )
        if not result.success and result.derivation_report.derivation_status == "blocked":
            return JSONResponse(
                status_code=409,
                content=model_to_response_dict(result),
            )
        return result
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/adapter-derivations",
    response_model=AnalyzeStoriesAdapterDerivationListResponse,
)
def list_adapter_derivations() -> AnalyzeStoriesAdapterDerivationListResponse:
    try:
        return analyze_stories_adapter_service.list_derivation_reports()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/adapter-derivations/{derivation_report_id}",
    response_model=AnalyzeStoriesAdapterDerivationReport,
)
def get_adapter_derivation(
    derivation_report_id: str,
) -> AnalyzeStoriesAdapterDerivationReport:
    try:
        return analyze_stories_adapter_service.get_derivation_report(derivation_report_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/adapter-candidates",
    response_model=AnalyzeStoriesAdapterCandidateListResponse,
)
def list_adapter_candidates(
    family: str | None = None,
    status: str | None = None,
    bundle_manifest_id: str | None = None,
    derivation_report_id: str | None = None,
) -> AnalyzeStoriesAdapterCandidateListResponse:
    try:
        return analyze_stories_adapter_service.list_candidates(
            family=family,
            status=status,
            bundle_manifest_id=bundle_manifest_id,
            derivation_report_id=derivation_report_id,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/adapter-candidates/{candidate_id}",
    response_model=AnalyzeStoriesAdapterCandidateDetail,
)
def get_adapter_candidate(candidate_id: str) -> AnalyzeStoriesAdapterCandidateDetail:
    try:
        return analyze_stories_adapter_service.get_candidate(candidate_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/adapter-candidates/{candidate_id}/mark-reviewed",
    response_model=AnalyzeStoriesAdapterCandidateActionResult,
)
def mark_adapter_candidate_reviewed(
    candidate_id: str,
    request: AnalyzeStoriesAdapterCandidateActionRequest | None = None,
) -> AnalyzeStoriesAdapterCandidateActionResult:
    try:
        return analyze_stories_adapter_service.mark_candidate_reviewed(
            candidate_id,
            request=request,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/adapter-candidates/{candidate_id}/defer",
    response_model=AnalyzeStoriesAdapterCandidateActionResult,
)
def defer_adapter_candidate(
    candidate_id: str,
    request: AnalyzeStoriesAdapterCandidateActionRequest | None = None,
) -> AnalyzeStoriesAdapterCandidateActionResult:
    try:
        return analyze_stories_adapter_service.defer_candidate(candidate_id, request=request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/adapter-candidates/{candidate_id}/reject",
    response_model=AnalyzeStoriesAdapterCandidateActionResult,
)
def reject_adapter_candidate(
    candidate_id: str,
    request: AnalyzeStoriesAdapterCandidateActionRequest | None = None,
) -> AnalyzeStoriesAdapterCandidateActionResult:
    try:
        return analyze_stories_adapter_service.reject_candidate(candidate_id, request=request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/imports/{import_id}/framework-candidates",
    response_model=FrameworkPackageCandidateResult,
)
def create_framework_candidate_from_import(
    import_id: str,
) -> FrameworkPackageCandidateResult:
    try:
        return framework_package_candidate_service.create_candidate_from_import(import_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/framework-candidates",
    response_model=FrameworkPackageCandidateListResponse,
)
def list_framework_candidates() -> FrameworkPackageCandidateListResponse:
    try:
        return framework_package_candidate_service.list_candidates()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/framework-candidates/{candidate_id}",
    response_model=FrameworkPackageCandidateDetail,
)
def get_framework_candidate(candidate_id: str) -> FrameworkPackageCandidateDetail:
    try:
        return framework_package_candidate_service.get_detail(candidate_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/framework-candidates/{candidate_id}/normalization-report",
    response_model=FrameworkPackageNormalizationReport,
)
def get_framework_candidate_normalization_report(
    candidate_id: str,
) -> FrameworkPackageNormalizationReport:
    try:
        return framework_package_candidate_service.get_normalization_report(candidate_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/framework-candidates/{candidate_id}/revalidate",
    response_model=FrameworkPackageCandidateResult,
)
def revalidate_framework_candidate(candidate_id: str) -> FrameworkPackageCandidateResult:
    try:
        return framework_package_candidate_service.revalidate_candidate(candidate_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/framework-candidates/{candidate_id}/imported-workbench",
    response_model=ImportedFrameworkWorkbenchState,
)
def get_imported_framework_workbench_state(
    candidate_id: str,
) -> ImportedFrameworkWorkbenchState:
    try:
        return imported_framework_workbench_service.get_imported_workbench_state(
            candidate_id
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/framework-candidates/{candidate_id}/edit-sessions",
    response_model=ImportedFrameworkSessionResult,
)
def start_imported_framework_edit_session(
    candidate_id: str,
) -> ImportedFrameworkSessionResult:
    try:
        return imported_framework_workbench_service.start_edit_session(candidate_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/imported-framework-edit-sessions",
    response_model=ImportedFrameworkListResponse,
)
def list_imported_framework_edit_sessions() -> ImportedFrameworkListResponse:
    try:
        return imported_framework_workbench_service.list_edit_sessions()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/imported-framework-edit-sessions/{edit_session_id}",
    response_model=ImportedFrameworkSessionResult,
)
def get_imported_framework_edit_session(
    edit_session_id: str,
) -> ImportedFrameworkSessionResult:
    try:
        return imported_framework_workbench_service.get_edit_session(edit_session_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.patch(
    "/imported-framework-edit-sessions/{edit_session_id}",
    response_model=ImportedFrameworkSessionResult,
)
def patch_imported_framework_edit_session(
    edit_session_id: str,
    request: ImportedFrameworkActionRequest,
) -> ImportedFrameworkSessionResult:
    try:
        return imported_framework_workbench_service.apply_patch(edit_session_id, request)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/imported-framework-edit-sessions/{edit_session_id}/validate",
    response_model=ImportedFrameworkSessionResult,
)
def validate_imported_framework_edit_session(
    edit_session_id: str,
) -> ImportedFrameworkSessionResult:
    try:
        return imported_framework_workbench_service.validate_edit_session(
            edit_session_id
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/imported-framework-edit-sessions/{edit_session_id}/activation-plan",
    response_model=ImportedFrameworkPlanResult,
)
def build_imported_framework_activation_plan(
    edit_session_id: str,
    request: ImportedFrameworkActionRequest | None = None,
) -> ImportedFrameworkPlanResult:
    try:
        return imported_framework_workbench_service.build_activation_plan(
            edit_session_id,
            activation_mode=request.activation_mode if request else None,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/imported-framework-activation-plans/{plan_id}/confirm",
    response_model=ImportedFrameworkDecisionResult,
)
def confirm_imported_framework_activation_plan(
    plan_id: str,
    request: ImportedFrameworkActionRequest | None = None,
) -> ImportedFrameworkDecisionResult:
    try:
        return imported_framework_workbench_service.confirm_activation_plan(
            plan_id,
            request=request,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/imported-framework-edit-sessions/{edit_session_id}/reject",
    response_model=ImportedFrameworkDecisionResult,
)
def reject_imported_framework_edit_session(
    edit_session_id: str,
    request: ImportedFrameworkActionRequest | None = None,
) -> ImportedFrameworkDecisionResult:
    try:
        return imported_framework_workbench_service.reject_edit_session(
            edit_session_id,
            request=request,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/reports/{report_ref_id}/viewer-state",
    response_model=AnalysisReportViewerResult,
)
def create_analysis_report_viewer_state(
    report_ref_id: str,
) -> AnalysisReportViewerResult:
    try:
        return analysis_report_viewer_service.create_viewer_state(report_ref_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/report-viewers",
    response_model=AnalysisReportViewerResult,
)
def create_analysis_report_viewer(
    request: CreateAnalysisReportViewerRequest,
) -> AnalysisReportViewerResult:
    try:
        return analysis_report_viewer_service.create_viewer_state(request.report_ref_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/reports/{report_ref_id}/viewer-state",
    response_model=AnalysisReportViewerDetail,
)
def get_analysis_report_viewer_state_for_report(
    report_ref_id: str,
) -> AnalysisReportViewerDetail:
    try:
        return analysis_report_viewer_service.get_viewer_state_for_report(report_ref_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/report-viewers",
    response_model=AnalysisReportViewerListResponse,
)
def list_analysis_report_viewers() -> AnalysisReportViewerListResponse:
    try:
        return analysis_report_viewer_service.list_viewer_states()
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.get(
    "/report-viewers/{viewer_state_id}",
    response_model=AnalysisReportViewerDetail,
)
def get_analysis_report_viewer(
    viewer_state_id: str,
) -> AnalysisReportViewerDetail:
    try:
        return analysis_report_viewer_service.get_viewer_state(viewer_state_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/report-viewers/{viewer_state_id}/mark-reviewed",
    response_model=AnalysisReportViewerReviewResult,
)
def mark_analysis_report_viewer_reviewed(
    viewer_state_id: str,
) -> AnalysisReportViewerReviewResult:
    try:
        return analysis_report_viewer_service.mark_reviewed(viewer_state_id)
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/report-viewers/{viewer_state_id}/flag",
    response_model=AnalysisReportViewerReviewResult,
)
def flag_analysis_report_viewer(
    viewer_state_id: str,
    request: AnalysisReportViewerActionRequest | None = None,
) -> AnalysisReportViewerReviewResult:
    try:
        return analysis_report_viewer_service.flag(
            viewer_state_id,
            note=request.note if request else None,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc


@router.post(
    "/report-viewers/{viewer_state_id}/dismiss",
    response_model=AnalysisReportViewerReviewResult,
)
def dismiss_analysis_report_viewer(
    viewer_state_id: str,
    request: AnalysisReportViewerActionRequest | None = None,
) -> AnalysisReportViewerReviewResult:
    try:
        return analysis_report_viewer_service.dismiss(
            viewer_state_id,
            note=request.note if request else None,
        )
    except StorageError as exc:
        raise storage_error_response(exc) from exc
