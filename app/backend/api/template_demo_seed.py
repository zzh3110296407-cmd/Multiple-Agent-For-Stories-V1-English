from fastapi import APIRouter, HTTPException

from app.backend.models.project_creation import DemoSeedProfile, DemoSeedProfilesResponse
from app.backend.models.template_demo_seed import (
    CreateTemplateInstantiationRequest,
    DemoSeedIsolationAudit,
    DemoSeedRunRecord,
    ProjectOriginBadge,
    ProjectTemplate,
    ProjectTemplatesResponse,
    RunDemoSeedRequest,
    TemplateInstantiationReport,
    TemplateInstantiationRequest,
    TemplateInstantiationValidationReport,
)
from app.backend.services.template_demo_seed_service import (
    TemplateDemoSeedBlocked,
    TemplateDemoSeedError,
    TemplateDemoSeedNotFound,
    TemplateDemoSeedSafetyError,
    TemplateDemoSeedService,
)
from app.backend.storage.json_store import StorageError


project_templates_router = APIRouter()
template_instantiation_router = APIRouter()
demo_seeds_router = APIRouter()
project_origin_badges_router = APIRouter()
template_demo_seed_service = TemplateDemoSeedService()


def _raise_template_demo_seed_error(exc: Exception) -> None:
    if isinstance(exc, TemplateDemoSeedNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, TemplateDemoSeedSafetyError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, TemplateDemoSeedBlocked):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, TemplateDemoSeedError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, StorageError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


@project_templates_router.get("", response_model=ProjectTemplatesResponse)
def list_project_templates() -> ProjectTemplatesResponse:
    try:
        return template_demo_seed_service.list_templates()
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@project_templates_router.get("/{template_id}", response_model=ProjectTemplate)
def get_project_template(template_id: str) -> ProjectTemplate:
    try:
        return template_demo_seed_service.get_template(template_id)
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@project_templates_router.post(
    "/{template_id}/instantiation-requests",
    response_model=TemplateInstantiationRequest,
)
def create_template_instantiation_request(
    template_id: str,
    request: CreateTemplateInstantiationRequest,
) -> TemplateInstantiationRequest:
    try:
        return template_demo_seed_service.create_template_instantiation_request(
            template_id,
            request,
        )
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@template_instantiation_router.get(
    "/requests/{template_instantiation_request_id}",
    response_model=TemplateInstantiationRequest,
)
def get_template_instantiation_request(
    template_instantiation_request_id: str,
) -> TemplateInstantiationRequest:
    try:
        return template_demo_seed_service.get_template_instantiation_request(
            template_instantiation_request_id,
        )
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@template_instantiation_router.post(
    "/requests/{template_instantiation_request_id}/validate",
    response_model=TemplateInstantiationValidationReport,
)
def validate_template_instantiation_request(
    template_instantiation_request_id: str,
) -> TemplateInstantiationValidationReport:
    try:
        return template_demo_seed_service.validate_template_instantiation(
            template_instantiation_request_id,
        )
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@template_instantiation_router.post(
    "/requests/{template_instantiation_request_id}/instantiate",
    response_model=TemplateInstantiationReport,
)
def instantiate_template_request(
    template_instantiation_request_id: str,
) -> TemplateInstantiationReport:
    try:
        return template_demo_seed_service.instantiate_template(
            template_instantiation_request_id,
        )
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@template_instantiation_router.get(
    "/reports/{template_instantiation_report_id}",
    response_model=TemplateInstantiationReport,
)
def get_template_instantiation_report(
    template_instantiation_report_id: str,
) -> TemplateInstantiationReport:
    try:
        return template_demo_seed_service.get_template_instantiation_report(
            template_instantiation_report_id,
        )
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@demo_seeds_router.get("", response_model=DemoSeedProfilesResponse)
def list_demo_seeds() -> DemoSeedProfilesResponse:
    try:
        return DemoSeedProfilesResponse(
            demo_seed_profiles=template_demo_seed_service.list_demo_seed_profiles()
        )
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@demo_seeds_router.get("/{demo_seed_id}", response_model=DemoSeedProfile)
def get_demo_seed(demo_seed_id: str) -> DemoSeedProfile:
    try:
        return template_demo_seed_service.get_demo_seed_profile(demo_seed_id)
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@demo_seeds_router.post("/{demo_seed_id}/run", response_model=DemoSeedRunRecord)
def run_demo_seed(
    demo_seed_id: str,
    request: RunDemoSeedRequest,
) -> DemoSeedRunRecord:
    try:
        return template_demo_seed_service.run_demo_seed(demo_seed_id, request)
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@demo_seeds_router.get("/runs/{demo_seed_run_id}", response_model=DemoSeedRunRecord)
def get_demo_seed_run(demo_seed_run_id: str) -> DemoSeedRunRecord:
    try:
        return template_demo_seed_service.get_demo_seed_run(demo_seed_run_id)
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@demo_seeds_router.post(
    "/runs/{demo_seed_run_id}/isolation-audit",
    response_model=DemoSeedIsolationAudit,
)
def create_demo_seed_isolation_audit(
    demo_seed_run_id: str,
) -> DemoSeedIsolationAudit:
    try:
        return template_demo_seed_service.create_demo_seed_isolation_audit(
            demo_seed_run_id,
        )
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@demo_seeds_router.get(
    "/isolation-audits/{demo_seed_isolation_audit_id}",
    response_model=DemoSeedIsolationAudit,
)
def get_demo_seed_isolation_audit(
    demo_seed_isolation_audit_id: str,
) -> DemoSeedIsolationAudit:
    try:
        return template_demo_seed_service.get_demo_seed_isolation_audit(
            demo_seed_isolation_audit_id,
        )
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")


@project_origin_badges_router.get("/{project_id}", response_model=ProjectOriginBadge)
def get_project_origin_badge(project_id: str) -> ProjectOriginBadge:
    try:
        return template_demo_seed_service.project_origin_badge(project_id)
    except (TemplateDemoSeedError, StorageError) as exc:
        _raise_template_demo_seed_error(exc)
        raise AssertionError("unreachable")
