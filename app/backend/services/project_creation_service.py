import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.model_settings import ModelSettingsWorkbench
from app.backend.models.project_creation import (
    ActiveProjectSelection,
    ActiveProjectSelectionResponse,
    ConfirmProjectCreationDraftRequest,
    CreateProjectCreationRequest,
    DemoSeedProfile,
    DemoSeedProfilesResponse,
    ProjectCreationDecision,
    ProjectCreationDraft,
    ProjectCreationCurrentState,
    ProjectCreationMode,
    ProjectCreationModesResponse,
    ProjectCreationRequest,
    ProjectCreationSafetyScanReport,
    ProjectCreationValidationReport,
    ProjectOpenSummary,
    ProjectOriginMetadata,
    ProjectRegistryResponse,
    ProjectShell,
    SetActiveProjectSelectionRequest,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.model_settings_service import ModelSettingsService
from app.backend.storage.json_store import JsonStore, StorageError


PROJECT_CREATION_REQUESTS_FILE = "project_creation_requests.json"
PROJECT_CREATION_VALIDATION_REPORTS_FILE = "project_creation_validation_reports.json"
PROJECT_CREATION_DRAFTS_FILE = "project_creation_drafts.json"
PROJECT_CREATION_DECISIONS_FILE = "project_creation_decisions.json"
PROJECT_REGISTRY_FILE = "project_registry.json"
PROJECT_ORIGIN_METADATA_FILE = "project_origin_metadata.json"
DEMO_SEED_PROFILES_FILE = "demo_seed_profiles.json"
ACTIVE_PROJECT_SELECTION_FILE = "active_project_selection.json"

SAFE_PROJECT_ID_RE = re.compile(r"[^a-z0-9_]+")
SECRET_LIKE_RE = re.compile(
    r"(?<![A-Za-z])sk-[A-Za-z0-9_\-]{8,}|lsv2_[A-Za-z0-9_\-]{8,}|(?i:bearer\s+[A-Za-z0-9._\-]{8,})|(?i:authorization\s*:)"
)
UNSAFE_VALUE_MARKERS = (
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "provider_payload",
    "provider payload",
    "provider_response",
    "provider response",
)
FORBIDDEN_STORAGE_VALUE_MARKERS = UNSAFE_VALUE_MARKERS + ("api_key_ref",)
MODE_TYPES = {
    "blank_project",
    "prompt_first_project",
    "template_project",
    "analyze_stories_import_project",
    "demo_seed_project",
    "open_existing_project",
}


class ProjectCreationError(RuntimeError):
    """Base error for Phase 8 M2 project creation failures."""


class ProjectCreationNotFound(ProjectCreationError):
    """Raised when a project creation record is not found."""


class ProjectCreationBlocked(ProjectCreationError):
    """Raised when validation blocks a project creation operation."""


class ProjectCreationSafetyError(ProjectCreationError):
    """Raised when a payload violates the M2 safety contract."""


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, BaseModel):
        return model.dict()
    return dict(model)


def serialize_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return model_to_dict(value)
    if isinstance(value, list):
        return [serialize_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_jsonable(child) for key, child in value.items()}
    return value


class ProjectCreationService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        model_settings_service: ModelSettingsService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.model_settings_service = model_settings_service or ModelSettingsService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.requests_file = self.data_dir / PROJECT_CREATION_REQUESTS_FILE
        self.validation_reports_file = self.data_dir / PROJECT_CREATION_VALIDATION_REPORTS_FILE
        self.drafts_file = self.data_dir / PROJECT_CREATION_DRAFTS_FILE
        self.decisions_file = self.data_dir / PROJECT_CREATION_DECISIONS_FILE
        self.registry_file = self.data_dir / PROJECT_REGISTRY_FILE
        self.origin_metadata_file = self.data_dir / PROJECT_ORIGIN_METADATA_FILE
        self.demo_seed_profiles_file = self.data_dir / DEMO_SEED_PROFILES_FILE
        self.active_project_selection_file = self.data_dir / ACTIVE_PROJECT_SELECTION_FILE
        self.legacy_project_file = self.data_dir / "project.json"

    def list_modes(self) -> ProjectCreationModesResponse:
        return ProjectCreationModesResponse(modes=self._mode_definitions())

    def list_demo_seed_profiles(self) -> DemoSeedProfilesResponse:
        return DemoSeedProfilesResponse(
            demo_seed_profiles=self._demo_seed_profiles_or_defaults()
        )

    def create_request(
        self,
        payload: CreateProjectCreationRequest,
    ) -> ProjectCreationRequest:
        self._guard_safe_payload(model_to_dict(payload), allow_prompt_text=True)
        mode = self._get_mode(payload.mode_type)
        now = utc_now()
        prompt_text = payload.prompt_text or ""
        if payload.mode_type == "prompt_first_project" and not prompt_text.strip():
            raise ProjectCreationError("prompt_text_required_for_prompt_first_project")
        prompt_text_ref = self._prompt_ref(prompt_text) if prompt_text else None
        prompt_safe_summary = (
            f"Prompt captured by hash only ({len(prompt_text)} characters)."
            if prompt_text
            else ""
        )
        model_hint = self._model_readiness_hint()
        warnings = list(model_hint["warnings"])
        if not mode.enabled:
            warnings.append("creation_mode_not_enabled")
        if payload.mode_type == "demo_seed_project" and not payload.explicit_user_selection:
            warnings.append("demo_seed_requires_explicit_selection")
        if payload.mode_type == "demo_seed_project" and not self._read_demo_seed_profiles():
            self._write_demo_seed_profiles(self._default_demo_seed_profiles())

        request = ProjectCreationRequest(
            creation_request_id=f"project_creation_request_{uuid4().hex[:12]}",
            mode_type=payload.mode_type,
            requested_title=self._safe_title(payload.requested_title),
            requested_language=(payload.requested_language or "zh").strip()[:16] or "zh",
            prompt_text_ref=prompt_text_ref,
            prompt_safe_summary=prompt_safe_summary,
            template_id=self._clean_optional_ref(payload.template_id),
            analyze_stories_import_ref=self._clean_optional_ref(payload.analyze_stories_import_ref),
            demo_seed_id=self._clean_optional_ref(payload.demo_seed_id),
            existing_project_id=self._clean_optional_ref(payload.existing_project_id),
            explicit_user_selection=payload.explicit_user_selection,
            active_model_selection_id=model_hint["active_model_selection_id"],
            active_model_provider_type=model_hint["provider_type"],
            active_model_name=model_hint["model_name"],
            model_health_status_at_request=model_hint["health_status"],
            request_status="created",
            safe_summary=self._request_safe_summary(payload.mode_type, payload.requested_title),
            warnings=warnings,
            created_at=now,
            updated_at=now,
        )
        requests = self._read_requests()
        requests.append(request)
        self._write_requests(requests)
        return request

    def get_request(self, creation_request_id: str) -> ProjectCreationRequest:
        return self._get_request(creation_request_id)

    def get_current_state(
        self,
        *,
        creation_request_id: str | None = None,
        creation_draft_id: str | None = None,
        project_id: str | None = None,
    ) -> ProjectCreationCurrentState:
        """Return the latest recoverable project creation flow state.

        This is intentionally read-only and request-local. It lets the frontend
        recover a pending request/draft after refresh without inferring from the
        global active project progress.
        """
        request_filter = (creation_request_id or "").strip()
        draft_filter = (creation_draft_id or "").strip()
        project_filter = (project_id or "").strip()
        warnings: list[str] = []

        requests = self._read_requests()
        validations = self._read_validation_reports()
        drafts = self._read_drafts()
        decisions = self._read_decisions()

        current_draft: ProjectCreationDraft | None = None
        if draft_filter:
            current_draft = next(
                (draft for draft in drafts if draft.creation_draft_id == draft_filter),
                None,
            )
            if current_draft is None:
                raise ProjectCreationNotFound(f"Project creation draft not found: {draft_filter}")
            request_filter = current_draft.creation_request_id

        current_request: ProjectCreationRequest | None = None
        if request_filter:
            current_request = next(
                (
                    request
                    for request in requests
                    if request.creation_request_id == request_filter
                ),
                None,
            )
            if current_request is None:
                raise ProjectCreationNotFound(
                    f"Project creation request not found: {request_filter}"
                )
        elif current_draft is not None:
            current_request = next(
                (
                    request
                    for request in requests
                    if request.creation_request_id == current_draft.creation_request_id
                ),
                None,
            )
        else:
            current_request = self._latest_recoverable_request(
                requests,
                drafts,
                decisions,
                project_id=project_filter,
            )
            if current_request is not None and not project_filter:
                warnings.append("latest_recoverable_project_creation_state_used")

        if current_request is not None and current_draft is None:
            request_drafts = [
                draft
                for draft in drafts
                if draft.creation_request_id == current_request.creation_request_id
            ]
            if project_filter:
                request_drafts = [
                    draft
                    for draft in request_drafts
                    if draft.proposed_project_id == project_filter
                ]
            current_draft = self._latest_preferred_draft(request_drafts)

        current_validation = None
        if current_request is not None:
            current_validation = self._latest_validation_for_request(
                current_request.creation_request_id
            )

        current_decision = None
        if current_draft is not None:
            draft_decisions = [
                decision
                for decision in decisions
                if decision.creation_draft_id == current_draft.creation_draft_id
            ]
            current_decision = draft_decisions[-1] if draft_decisions else None
        if current_decision is None and current_request is not None:
            request_decisions = [
                decision
                for decision in decisions
                if decision.creation_request_id == current_request.creation_request_id
            ]
            current_decision = request_decisions[-1] if request_decisions else None

        state_project_id = ""
        if current_decision and current_decision.created_project_id:
            state_project_id = current_decision.created_project_id
        elif current_draft:
            state_project_id = current_draft.proposed_project_id
        elif project_filter:
            state_project_id = project_filter

        state_status = "empty"
        if current_decision:
            state_status = current_decision.decision_status or "decision_recorded"
        elif current_draft:
            state_status = f"draft_{current_draft.draft_status}"
        elif current_validation:
            state_status = current_validation.validation_status
        elif current_request:
            state_status = current_request.request_status or "request_created"

        return ProjectCreationCurrentState(
            state_status=state_status,
            project_id=state_project_id,
            creation_request=current_request,
            validation_report=current_validation,
            creation_draft=current_draft,
            creation_decision=current_decision,
            warnings=self._dedupe(warnings),
        )

    def validate_request(
        self,
        creation_request_id: str,
    ) -> ProjectCreationValidationReport:
        request = self._get_request(creation_request_id)
        self._guard_safe_payload(model_to_dict(request), allow_prompt_text=False)
        mode = self._get_mode(request.mode_type)
        now = utc_now()
        blocking: list[str] = []
        warnings = list(request.warnings)
        model_hint = self._model_readiness_hint()

        active_model_available = bool(model_hint["active_model_selection_id"])
        active_model_warning = ""
        if not active_model_available:
            active_model_warning = "no_active_model_selection"
            warnings.append(active_model_warning)
        elif model_hint["health_status"] not in {"passed", "unknown"}:
            active_model_warning = f"model_health_{model_hint['health_status']}"
            warnings.append(active_model_warning)
        warnings.extend(model_hint["warnings"])

        can_create_real = bool(mode.creates_real_user_project)
        can_create_demo = bool(mode.creates_demo_project)
        demo_marker_required = request.mode_type == "demo_seed_project"
        if demo_marker_required and not request.explicit_user_selection:
            blocking.append("demo_seed_requires_explicit_user_selection")
        if demo_marker_required and not request.demo_seed_id:
            blocking.append("demo_seed_id_required")
        if demo_marker_required and request.demo_seed_id:
            demo_ids = {profile.demo_seed_id for profile in self._demo_seed_profiles_or_defaults()}
            if request.demo_seed_id not in demo_ids:
                blocking.append("demo_seed_profile_not_found")

        analyze_requires_gate = request.mode_type == "analyze_stories_import_project"
        if analyze_requires_gate and not request.analyze_stories_import_ref:
            blocking.append("analyze_stories_import_ref_required")

        template_requires_m4 = request.mode_type == "template_project"
        if template_requires_m4 and not request.template_id:
            blocking.append("template_id_required")

        prompt_requires_m3 = request.mode_type == "prompt_first_project"
        if prompt_requires_m3 and not request.prompt_text_ref:
            blocking.append("prompt_text_ref_required")

        if request.mode_type == "open_existing_project":
            can_create_real = False
            can_create_demo = False
            if not request.existing_project_id:
                blocking.append("existing_project_id_required")
            elif not self._project_shell_exists(request.existing_project_id):
                blocking.append("existing_project_not_found")

        can_create_shell = len(blocking) == 0
        report = ProjectCreationValidationReport(
            validation_report_id=f"project_creation_validation_{uuid4().hex[:12]}",
            creation_request_id=request.creation_request_id,
            validation_status="blocked" if blocking else "passed_with_warnings" if warnings else "passed",
            can_create_project_shell=can_create_shell,
            can_create_real_user_project=can_create_real and can_create_shell,
            can_create_demo_project=can_create_demo and can_create_shell,
            active_model_available=active_model_available,
            active_model_warning=active_model_warning,
            demo_seed_explicitly_selected=request.explicit_user_selection and demo_marker_required,
            demo_seed_marker_required=demo_marker_required,
            analyze_stories_requires_import_gate=analyze_requires_gate,
            analyze_stories_auto_activation_blocked=analyze_requires_gate,
            template_requires_m4_instantiation=template_requires_m4,
            prompt_first_requires_m3_setup=prompt_requires_m3,
            blocking_issues=blocking,
            warnings=self._dedupe(warnings),
            safe_summary=self._validation_safe_summary(request.mode_type, blocking),
            created_at=now,
            updated_at=now,
        )
        reports = self._read_validation_reports()
        reports.append(report)
        self._write_validation_reports(reports)
        return report

    def create_draft(self, creation_request_id: str) -> ProjectCreationDraft:
        request = self._get_request(creation_request_id)
        report = self._latest_validation_for_request(creation_request_id)
        if report is None or report.blocking_issues:
            report = self.validate_request(creation_request_id)
        if report.blocking_issues:
            raise ProjectCreationBlocked("; ".join(report.blocking_issues))
        mode = self._get_mode(request.mode_type)
        now = utc_now()
        origin_type = self._origin_type_for_mode(request.mode_type)
        proposed_project_id = (
            request.existing_project_id
            if request.mode_type == "open_existing_project" and request.existing_project_id
            else self._new_project_id(request.requested_title)
        )
        draft = ProjectCreationDraft(
            creation_draft_id=f"project_creation_draft_{uuid4().hex[:12]}",
            creation_request_id=request.creation_request_id,
            draft_status="draft",
            proposed_project_id=proposed_project_id,
            proposed_title=request.requested_title,
            proposed_language=request.requested_language,
            origin_type=origin_type,
            origin_metadata_id=f"project_origin_{uuid4().hex[:12]}",
            validation_report_id=report.validation_report_id,
            will_create_story_facts_now=False,
            will_create_demo_marker=request.mode_type == "demo_seed_project",
            will_require_followup_confirmation=mode.requires_followup_setup,
            recommended_next_step=mode.recommended_next_step,
            safe_summary=self._draft_safe_summary(origin_type, proposed_project_id),
            warnings=self._dedupe(report.warnings),
            created_at=now,
            updated_at=now,
        )
        self._assert_no_story_fact_creation(draft)
        drafts = self._read_drafts()
        drafts.append(draft)
        self._write_drafts(drafts)
        return draft

    def get_draft(self, creation_draft_id: str) -> ProjectCreationDraft:
        return self._get_draft(creation_draft_id)

    def confirm_draft(
        self,
        creation_draft_id: str,
        payload: ConfirmProjectCreationDraftRequest,
    ) -> ProjectCreationDecision:
        self._guard_safe_payload(model_to_dict(payload), allow_prompt_text=False)
        draft = self._get_draft(creation_draft_id)
        if draft.draft_status != "draft":
            raise ProjectCreationBlocked("creation_draft_is_not_confirmable")
        request = self._get_request(draft.creation_request_id)
        report = self._get_validation_report(draft.validation_report_id)
        if report.blocking_issues:
            raise ProjectCreationBlocked("; ".join(report.blocking_issues))
        self._assert_no_story_fact_creation(draft)
        now = utc_now()

        project_id = draft.proposed_project_id
        if request.mode_type != "open_existing_project":
            shell = ProjectShell(
                project_id=project_id,
                title=draft.proposed_title,
                language=draft.proposed_language,
                status="project_shell_created",
                current_step=draft.recommended_next_step,
                origin_metadata_id=draft.origin_metadata_id,
                origin_type=draft.origin_type,
                created_at=now,
                updated_at=now,
            )
            self._upsert_project_shell(shell)
            origin = self._build_origin_metadata(request, draft, now)
            self._upsert_origin_metadata(origin)
            self.set_active_project_selection(
                SetActiveProjectSelectionRequest(
                    project_id=project_id,
                    selected_by="creation_confirm",
                )
            )
        else:
            self.set_active_project_selection(
                SetActiveProjectSelectionRequest(project_id=project_id, selected_by="user")
            )

        decision = ProjectCreationDecision(
            creation_decision_id=f"project_creation_decision_{uuid4().hex[:12]}",
            creation_request_id=request.creation_request_id,
            creation_draft_id=draft.creation_draft_id,
            decision_type="confirm_creation_draft",
            decision_status="confirmed",
            created_project_id=project_id,
            confirms_origin_metadata=request.mode_type != "open_existing_project",
            confirms_demo_seed_if_any=request.mode_type == "demo_seed_project",
            does_not_confirm_story_facts=True,
            safe_user_note=self._safe_note(payload.safe_user_note),
            created_at=now,
        )
        decisions = self._read_decisions()
        decisions.append(decision)
        self._write_decisions(decisions)
        self._update_draft_status(draft.creation_draft_id, "confirmed")
        return decision

    def cancel_draft(self, creation_draft_id: str) -> ProjectCreationDraft:
        draft = self._get_draft(creation_draft_id)
        if draft.draft_status != "draft":
            raise ProjectCreationBlocked("creation_draft_is_not_cancelable")
        return self._update_draft_status(creation_draft_id, "canceled")

    def list_projects(self) -> ProjectRegistryResponse:
        projects = self._read_project_registry()
        legacy = self._legacy_project_shell()
        if legacy and all(project.project_id != legacy.project_id for project in projects):
            projects.append(legacy)
        projects = sorted(projects, key=lambda item: (item.created_at or "", item.project_id))
        return ProjectRegistryResponse(projects=projects)

    def get_project(self, project_id: str) -> ProjectOpenSummary:
        project = self._get_project_shell(project_id)
        origin = self.get_project_origin(project_id)
        return ProjectOpenSummary(
            project=project,
            origin=origin,
            badges=self._origin_badges(origin),
            warnings=origin.warnings,
            safe_summary=f"Project {project.project_id} is classified as {origin.origin_type}.",
        )

    def get_project_origin(self, project_id: str) -> ProjectOriginMetadata:
        origin = self._find_origin_metadata(project_id)
        if origin:
            return origin
        if project_id == "local_project" and self.store.exists(self.legacy_project_file):
            now = utc_now()
            return ProjectOriginMetadata(
                origin_metadata_id="legacy_origin_local_project",
                project_id="local_project",
                origin_type="legacy_debug",
                is_real_user_project=False,
                is_demo_project=False,
                is_legacy_debug_project=True,
                created_by_user_action=False,
                explicit_user_selection_recorded=False,
                story_facts_created_at_project_creation=False,
                safe_summary=(
                    "Existing local_project has no Phase 8 M2 origin metadata and is treated as legacy/debug."
                ),
                warnings=["legacy_project_without_m2_origin_metadata"],
                created_at=now,
                updated_at=now,
            )
        return ProjectOriginMetadata(
            origin_metadata_id=f"unknown_origin_{project_id}",
            project_id=project_id,
            origin_type="unknown_origin",
            is_real_user_project=False,
            is_legacy_debug_project=True,
            created_by_user_action=False,
            explicit_user_selection_recorded=False,
            story_facts_created_at_project_creation=False,
            safe_summary="Project origin metadata is missing.",
            warnings=["project_origin_metadata_missing"],
            created_at=utc_now(),
            updated_at=utc_now(),
        )

    def open_project(self, project_id: str) -> ProjectOpenSummary:
        self.set_active_project_selection(
            SetActiveProjectSelectionRequest(project_id=project_id, selected_by="user")
        )
        return self.get_project(project_id)

    def set_active_project_selection(
        self,
        payload: SetActiveProjectSelectionRequest,
    ) -> ActiveProjectSelection:
        self._guard_safe_payload(model_to_dict(payload), allow_prompt_text=False)
        self._get_project_shell(payload.project_id)
        selection = ActiveProjectSelection(
            active_project_selection_id=f"active_project_selection_{uuid4().hex[:12]}",
            project_id=payload.project_id,
            selected_by=payload.selected_by or "user",
            opened_at=utc_now(),
            safe_summary="Active project selection changed by explicit user action.",
        )
        self.store.write(self.active_project_selection_file, model_to_dict(selection))
        return selection

    def get_active_project_selection(self) -> ActiveProjectSelectionResponse:
        if not self.store.exists(self.active_project_selection_file):
            return ActiveProjectSelectionResponse(active_project_selection=None)
        try:
            return ActiveProjectSelectionResponse(
                active_project_selection=ActiveProjectSelection(
                    **self.store.read(self.active_project_selection_file)
                )
            )
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError("Active project selection storage is invalid.") from exc

    def safety_scan(self) -> ProjectCreationSafetyScanReport:
        targets = [
            self.requests_file,
            self.validation_reports_file,
            self.drafts_file,
            self.decisions_file,
            self.registry_file,
            self.origin_metadata_file,
            self.demo_seed_profiles_file,
            self.active_project_selection_file,
        ]
        issues: list[str] = []
        scanned: list[str] = []
        for target in targets:
            if not target.exists():
                continue
            scanned.append(target.name)
            try:
                payload = self.store.read_any(target)
            except StorageError as exc:
                issues.append(f"{target.name}: {exc}")
                continue
            issues.extend(self._unsafe_payload_issues(payload, target.name, allow_prompt_text=False))
        return ProjectCreationSafetyScanReport(
            ok=len(issues) == 0,
            scanned_targets=scanned,
            issues=issues,
            samples={"file_count": len(scanned)},
        )

    def _mode_definitions(self) -> list[ProjectCreationMode]:
        return [
            ProjectCreationMode(
                mode_id="creation_mode_blank",
                mode_type="blank_project",
                display_name="Blank Project",
                creates_real_user_project=True,
                required_user_input=["requested_title", "requested_language"],
                recommended_next_step="story_setup_world_canvas",
                safe_summary="Create an empty project shell and choose story setup next.",
            ),
            ProjectCreationMode(
                mode_id="creation_mode_prompt_first",
                mode_type="prompt_first_project",
                display_name="Prompt First Project",
                creates_real_user_project=True,
                required_user_input=["requested_title", "prompt_text"],
                recommended_next_step="phase8_m3_prompt_first_setup",
                safe_summary="Capture a prompt reference only; story setup remains a follow-up step.",
            ),
            ProjectCreationMode(
                mode_id="creation_mode_template",
                mode_type="template_project",
                display_name="Template Project",
                creates_real_user_project=True,
                required_user_input=["requested_title", "template_id"],
                recommended_next_step="phase8_m4_template_instantiation",
                safe_summary="Record template intent without copying template content into story facts.",
            ),
            ProjectCreationMode(
                mode_id="creation_mode_analyze_stories",
                mode_type="analyze_stories_import_project",
                display_name="Analyze Stories Import Project",
                creates_real_user_project=True,
                required_user_input=["requested_title", "analyze_stories_import_ref"],
                recommended_next_step="analyze_stories_import_validation",
                safe_summary="Record import intent and require a later import validation gate.",
            ),
            ProjectCreationMode(
                mode_id="creation_mode_demo_seed",
                mode_type="demo_seed_project",
                display_name="Demo Seed Project",
                creates_demo_project=True,
                required_user_input=["requested_title", "demo_seed_id", "explicit_user_selection"],
                recommended_next_step="demo_review_only",
                safe_summary="Create an explicitly selected demo project shell with a demo marker only.",
            ),
            ProjectCreationMode(
                mode_id="creation_mode_open_existing",
                mode_type="open_existing_project",
                display_name="Open Existing Project",
                creates_real_user_project=False,
                creates_demo_project=False,
                requires_followup_setup=False,
                required_user_input=["existing_project_id"],
                recommended_next_step="open_project_summary",
                safe_summary="Open an existing shell by explicit POST without changing story facts.",
            ),
        ]

    def _default_demo_seed_profiles(self) -> list[DemoSeedProfile]:
        return [
            DemoSeedProfile(
                demo_seed_id="demo_seed_phase8_m2_default",
                display_name="Phase 8 Demo Seed",
                source_profile="phase8_m2_demo_seed_profile",
                safe_preview="A non-authoritative demo shell for product walkthroughs.",
                creates_demo_project_only=True,
                may_be_copied_to_real_project=False,
                required_marker="explicit_demo_seed_selection",
                safe_summary="Demo seed is isolated and cannot become a real project in M2.",
            )
        ]

    def _demo_seed_profiles_or_defaults(self) -> list[DemoSeedProfile]:
        profiles = self._read_demo_seed_profiles()
        return profiles if profiles else self._default_demo_seed_profiles()

    def _model_readiness_hint(self) -> dict[str, Any]:
        try:
            workbench: ModelSettingsWorkbench = self.model_settings_service.workbench()
        except Exception:
            return {
                "active_model_selection_id": None,
                "provider_type": None,
                "model_name": None,
                "health_status": "unknown",
                "warnings": ["model_settings_unavailable"],
            }
        latest_health = workbench.health_summary.latest_health_check
        warnings = self._safe_model_readiness_codes(workbench.warnings[:5], is_blocker=False)
        warnings.extend(self._safe_model_readiness_codes(workbench.blockers[:5], is_blocker=True))
        configured = bool(
            workbench.active_selection_id
            and workbench.current_provider
            and workbench.current_model
            and not workbench.blockers
        )
        if not workbench.active_selection_id:
            warnings.append("no_active_model_selection")
        return {
            "active_model_selection_id": workbench.active_selection_id,
            "provider_type": workbench.current_provider or None,
            "model_name": workbench.current_model or None,
            "health_status": "passed" if configured else latest_health.status if latest_health else "unknown",
            "warnings": self._dedupe(warnings),
        }

    def _safe_model_readiness_codes(
        self,
        values: list[str],
        is_blocker: bool,
    ) -> list[str]:
        return [
            self._safe_model_readiness_code(value, is_blocker=is_blocker)
            for value in values
        ]

    def _safe_model_readiness_code(self, value: str, is_blocker: bool) -> str:
        lowered = str(value or "").lower()
        if is_blocker:
            return "model_settings_blocker"
        if "no_active_model_selection" in lowered:
            return "no_active_model_selection"
        if "api_key" in lowered or "key_ref" in lowered:
            return "model_api_key_not_ready"
        if "gateway" in lowered:
            return "model_gateway_warning"
        if (
            "json file" in lowered
            or "storage" in lowered
            or "traceback" in lowered
            or "exception" in lowered
            or "error" in lowered
            or ":\\" in lowered
            or "/" in lowered
        ):
            return "model_settings_warning"
        normalized = re.sub(r"[^a-z0-9_]+", "_", lowered).strip("_")
        if not normalized:
            return "model_settings_warning"
        return f"model_warning_{normalized[:48]}"

    def _get_mode(self, mode_type: str) -> ProjectCreationMode:
        if mode_type not in MODE_TYPES:
            raise ProjectCreationError(f"Unsupported project creation mode: {mode_type}")
        return next(mode for mode in self._mode_definitions() if mode.mode_type == mode_type)

    def _origin_type_for_mode(self, mode_type: str) -> str:
        mapping = {
            "blank_project": "blank",
            "prompt_first_project": "prompt_first",
            "template_project": "template",
            "analyze_stories_import_project": "analyze_stories_import",
            "demo_seed_project": "demo_seed",
            "open_existing_project": "existing_project",
        }
        return mapping[mode_type]

    def _build_origin_metadata(
        self,
        request: ProjectCreationRequest,
        draft: ProjectCreationDraft,
        now: str,
    ) -> ProjectOriginMetadata:
        origin_type = draft.origin_type
        return ProjectOriginMetadata(
            origin_metadata_id=draft.origin_metadata_id,
            project_id=draft.proposed_project_id,
            origin_type=origin_type,
            is_real_user_project=origin_type not in {"demo_seed", "legacy_debug", "unknown_origin"},
            is_demo_project=origin_type == "demo_seed",
            is_template_derived=origin_type == "template",
            is_analyze_stories_derived=origin_type == "analyze_stories_import",
            is_prompt_first=origin_type == "prompt_first",
            is_legacy_debug_project=False,
            source_prompt_ref=request.prompt_text_ref,
            template_id=request.template_id,
            demo_seed_id=request.demo_seed_id,
            analyze_stories_import_ref=request.analyze_stories_import_ref,
            created_by_user_action=True,
            explicit_user_selection_recorded=request.explicit_user_selection,
            story_facts_created_at_project_creation=False,
            safe_summary=self._origin_safe_summary(origin_type),
            warnings=draft.warnings,
            created_at=now,
            updated_at=now,
        )

    def _origin_badges(self, origin: ProjectOriginMetadata) -> list[str]:
        badges: list[str] = []
        if origin.is_real_user_project:
            badges.append("real_user_project")
        if origin.is_demo_project:
            badges.append("demo_project")
        if origin.is_template_derived:
            badges.append("template_derived")
        if origin.is_analyze_stories_derived:
            badges.append("analyze_stories_import")
        if origin.is_prompt_first:
            badges.append("prompt_first")
        if origin.is_legacy_debug_project:
            badges.append("legacy_debug")
        if origin.origin_type == "unknown_origin":
            badges.append("unknown_origin")
        return badges

    def _latest_recoverable_request(
        self,
        requests: list[ProjectCreationRequest],
        drafts: list[ProjectCreationDraft],
        decisions: list[ProjectCreationDecision],
        *,
        project_id: str = "",
    ) -> ProjectCreationRequest | None:
        confirmed_request_ids = {
            decision.creation_request_id
            for decision in decisions
            if decision.decision_status == "confirmed"
        }
        candidate_request_ids: set[str] = set()
        for draft in drafts:
            if project_id and draft.proposed_project_id != project_id:
                continue
            if draft.draft_status == "draft":
                candidate_request_ids.add(draft.creation_request_id)
        for request in reversed(requests):
            if request.creation_request_id in candidate_request_ids:
                return request
        for request in reversed(requests):
            if request.creation_request_id in confirmed_request_ids:
                continue
            if project_id and request.existing_project_id != project_id:
                continue
            return request
        if project_id:
            for request in reversed(requests):
                if request.existing_project_id == project_id:
                    return request
        return requests[-1] if requests else None

    def _latest_preferred_draft(
        self,
        drafts: list[ProjectCreationDraft],
    ) -> ProjectCreationDraft | None:
        for draft in reversed(drafts):
            if draft.draft_status == "draft":
                return draft
        return drafts[-1] if drafts else None

    def _read_requests(self) -> list[ProjectCreationRequest]:
        return self._read_model_list(self.requests_file, ProjectCreationRequest)

    def _write_requests(self, records: list[ProjectCreationRequest]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_prompt_text=False)
        self.store.write(self.requests_file, [model_to_dict(item) for item in records])

    def _read_validation_reports(self) -> list[ProjectCreationValidationReport]:
        return self._read_model_list(self.validation_reports_file, ProjectCreationValidationReport)

    def _write_validation_reports(self, records: list[ProjectCreationValidationReport]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_prompt_text=False)
        self.store.write(self.validation_reports_file, [model_to_dict(item) for item in records])

    def _read_drafts(self) -> list[ProjectCreationDraft]:
        return self._read_model_list(self.drafts_file, ProjectCreationDraft)

    def _write_drafts(self, records: list[ProjectCreationDraft]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_prompt_text=False)
        self.store.write(self.drafts_file, [model_to_dict(item) for item in records])

    def _read_decisions(self) -> list[ProjectCreationDecision]:
        return self._read_model_list(self.decisions_file, ProjectCreationDecision)

    def _write_decisions(self, records: list[ProjectCreationDecision]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_prompt_text=False)
        self.store.write(self.decisions_file, [model_to_dict(item) for item in records])

    def _read_project_registry(self) -> list[ProjectShell]:
        if not self.store.exists(self.registry_file):
            return []
        try:
            data = self.store.read(self.registry_file)
            projects = data.get("projects", [])
            return [ProjectShell(**item) for item in projects]
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError("Project registry storage is invalid.") from exc

    def _write_project_registry(self, projects: list[ProjectShell]) -> None:
        payload = {"projects": [model_to_dict(item) for item in projects]}
        self._guard_safe_payload(payload, allow_prompt_text=False)
        self.store.write(self.registry_file, payload)

    def _read_origin_metadata(self) -> list[ProjectOriginMetadata]:
        return self._read_model_list(self.origin_metadata_file, ProjectOriginMetadata)

    def _write_origin_metadata(self, records: list[ProjectOriginMetadata]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_prompt_text=False)
        self.store.write(self.origin_metadata_file, [model_to_dict(item) for item in records])

    def _read_demo_seed_profiles(self) -> list[DemoSeedProfile]:
        return self._read_model_list(self.demo_seed_profiles_file, DemoSeedProfile)

    def _write_demo_seed_profiles(self, records: list[DemoSeedProfile]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_prompt_text=False)
        self.store.write(self.demo_seed_profiles_file, [model_to_dict(item) for item in records])

    def _read_model_list(self, path: Path, model_type: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        try:
            data = self.store.read_list(path)
            return [model_type(**item) for item in data]
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError(f"Storage file is invalid: {path.name}") from exc

    def _get_request(self, creation_request_id: str) -> ProjectCreationRequest:
        for record in self._read_requests():
            if record.creation_request_id == creation_request_id:
                return record
        raise ProjectCreationNotFound(f"Project creation request not found: {creation_request_id}")

    def _latest_validation_for_request(
        self,
        creation_request_id: str,
    ) -> ProjectCreationValidationReport | None:
        matches = [
            record
            for record in self._read_validation_reports()
            if record.creation_request_id == creation_request_id
        ]
        return matches[-1] if matches else None

    def _get_validation_report(self, validation_report_id: str) -> ProjectCreationValidationReport:
        for record in self._read_validation_reports():
            if record.validation_report_id == validation_report_id:
                return record
        raise ProjectCreationNotFound(f"Validation report not found: {validation_report_id}")

    def _get_draft(self, creation_draft_id: str) -> ProjectCreationDraft:
        for record in self._read_drafts():
            if record.creation_draft_id == creation_draft_id:
                return record
        raise ProjectCreationNotFound(f"Project creation draft not found: {creation_draft_id}")

    def _get_project_shell(self, project_id: str) -> ProjectShell:
        for project in self._read_project_registry():
            if project.project_id == project_id:
                return project
        legacy = self._legacy_project_shell()
        if legacy and legacy.project_id == project_id:
            return legacy
        raise ProjectCreationNotFound(f"Project not found: {project_id}")

    def _project_shell_exists(self, project_id: str) -> bool:
        try:
            self._get_project_shell(project_id)
            return True
        except ProjectCreationNotFound:
            return False

    def _upsert_project_shell(self, shell: ProjectShell) -> None:
        projects = self._read_project_registry()
        next_projects = [project for project in projects if project.project_id != shell.project_id]
        next_projects.append(shell)
        self._write_project_registry(next_projects)

    def _find_origin_metadata(self, project_id: str) -> ProjectOriginMetadata | None:
        for origin in self._read_origin_metadata():
            if origin.project_id == project_id:
                return origin
        return None

    def _upsert_origin_metadata(self, origin: ProjectOriginMetadata) -> None:
        records = self._read_origin_metadata()
        next_records = [record for record in records if record.project_id != origin.project_id]
        next_records.append(origin)
        self._write_origin_metadata(next_records)

    def _legacy_project_shell(self) -> ProjectShell | None:
        if not self.store.exists(self.legacy_project_file):
            return None
        now = utc_now()
        title = "Legacy Local Project"
        language = "zh"
        try:
            payload = self.store.read(self.legacy_project_file)
            title = str(payload.get("title") or payload.get("name") or title)
            language = str(payload.get("language") or language)
        except StorageError:
            pass
        return ProjectShell(
            project_id="local_project",
            title=title,
            language=language,
            status="legacy_debug",
            current_step="legacy_local_project",
            origin_metadata_id=None,
            origin_type="legacy_debug",
            created_at=now,
            updated_at=now,
        )

    def _update_draft_status(self, creation_draft_id: str, status: str) -> ProjectCreationDraft:
        drafts = self._read_drafts()
        updated: ProjectCreationDraft | None = None
        for index, draft in enumerate(drafts):
            if draft.creation_draft_id == creation_draft_id:
                updated = draft.copy(update={"draft_status": status, "updated_at": utc_now()})
                drafts[index] = updated
                break
        if updated is None:
            raise ProjectCreationNotFound(f"Project creation draft not found: {creation_draft_id}")
        self._write_drafts(drafts)
        return updated

    def _new_project_id(self, requested_title: str) -> str:
        base = SAFE_PROJECT_ID_RE.sub("_", requested_title.strip().lower()).strip("_")
        base = base[:40] or "story_project"
        return f"project_{base}_{uuid4().hex[:8]}"

    def _prompt_ref(self, prompt_text: str) -> str:
        digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        return f"prompt_input_sha256:{digest}"

    def _safe_title(self, title: str) -> str:
        cleaned = " ".join((title or "").split())
        return cleaned[:120] or "Untitled Story Project"

    def _safe_note(self, note: str) -> str:
        self._guard_safe_payload({"safe_user_note": note}, allow_prompt_text=False)
        return " ".join((note or "").split())[:240]

    def _clean_optional_ref(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(str(value).split())[:160]
        return cleaned or None

    def _request_safe_summary(self, mode_type: str, title: str) -> str:
        return f"Project creation request for {mode_type}; title captured as safe metadata."

    def _validation_safe_summary(self, mode_type: str, blocking: list[str]) -> str:
        if blocking:
            return f"{mode_type} validation is blocked by {len(blocking)} issue(s)."
        return f"{mode_type} validation passed without creating story facts."

    def _draft_safe_summary(self, origin_type: str, project_id: str) -> str:
        return f"Draft proposes project shell {project_id} with origin {origin_type}; no story facts."

    def _origin_safe_summary(self, origin_type: str) -> str:
        return f"Project origin recorded as {origin_type}; project creation did not confirm story facts."

    def _assert_no_story_fact_creation(self, draft: ProjectCreationDraft) -> None:
        if draft.will_create_story_facts_now:
            raise ProjectCreationSafetyError("M2 drafts cannot create story facts.")

    def _guard_safe_payload(self, payload: Any, allow_prompt_text: bool) -> None:
        issues = self._unsafe_payload_issues(payload, "payload", allow_prompt_text=allow_prompt_text)
        if issues:
            raise ProjectCreationSafetyError("; ".join(issues))

    def _unsafe_payload_issues(
        self,
        payload: Any,
        label: str,
        allow_prompt_text: bool,
    ) -> list[str]:
        issues: list[str] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = str(key).lower().replace("-", "_")
                    if normalized_key in {"authorization", "bearer", "api_key_plaintext", "raw_key"}:
                        issues.append(f"{label}:{path}.{key}:unsafe_key")
                    if normalized_key == "api_key_ref" and "origin" in label.lower():
                        issues.append(f"{label}:{path}.{key}:api_key_ref_forbidden")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if not isinstance(value, str):
                return
            if SECRET_LIKE_RE.search(value):
                issues.append(f"{label}:{path}:secret_like_value")
            lowered = value.lower()
            markers = UNSAFE_VALUE_MARKERS if allow_prompt_text else FORBIDDEN_STORAGE_VALUE_MARKERS
            for marker in markers:
                if marker in lowered:
                    issues.append(f"{label}:{path}:unsafe_marker:{marker}")

        visit(payload, "$")
        return self._dedupe(issues)

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result
