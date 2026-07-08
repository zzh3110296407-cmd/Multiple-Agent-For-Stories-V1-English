import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.product_navigation import (
    CurrentProjectHeader,
    PatchUserWorkspacePreferenceRequest,
    ProductNavigationGroup,
    ProductNavigationGroupsResponse,
    ProductNavigationState,
    ProductWorkspaceDefinition,
    ProductWorkspaceDefinitionsResponse,
    UserWorkspacePreference,
    WorkspaceAvailabilityItem,
    WorkspaceAvailabilityReport,
    WorkspaceModeProfile,
)
from app.backend.services.active_project_story_data import (
    story_data_dir_for_project,
    story_data_dir_has_project,
)
from app.backend.services.active_project_boundary_service import ActiveProjectBoundaryService
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.model_settings_service import ModelSettingsService
from app.backend.services.project_creation_service import ProjectCreationService
from app.backend.services.template_demo_seed_service import TemplateDemoSeedService
from app.backend.storage.json_store import JsonStore, StorageError


PRODUCT_NAVIGATION_PREFERENCES_FILE = "product_navigation_preferences.json"
SCHEMA_VERSION = "phase8_m5_product_navigation_v1"

KNOWN_ORIGIN_TYPES = {
    "blank",
    "prompt_first",
    "template",
    "demo_seed",
    "analyze_stories_import",
    "legacy_debug",
    "unknown_origin",
}

GENERATION_HEAVY_WORKSPACES = {
    "story_setup",
    "world_canvas",
    "characters",
    "framework",
    "chapter_scene",
    "memory_continuity",
    "formal_apply",
}

SETUP_GATED_STORY_WORKSPACES = {
    "world_canvas",
    "characters",
    "framework",
    "chapter_plan",
    "chapter_scene",
    "memory_continuity",
}

PHASE7_FINAL_PACKAGE_FILES = (
    "final_story_package_readiness_reports.json",
    "final_story_package_snapshots.json",
    "final_story_package_export_runs.json",
)

PHASE7_PLUGIN_ARTIFACT_FILES = (
    "plugin_runs.json",
    "plugin_output_artifacts.json",
    "plugin_output_artifact_versions.json",
)

UNSAFE_TEXT_MARKERS = (
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "raw provider response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "api_key_ref",
    "full_screenplay_text",
    "full story prose",
)

SECRET_LIKE_RE = re.compile(
    r"(?<![A-Za-z])sk-[A-Za-z0-9_\-]{8,}|lsv2_[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,}|Authorization\s*:",
    re.I,
)


class ProductNavigationError(RuntimeError):
    """Base error for Phase 8 M5 product navigation."""


class ProductNavigationNotFound(ProductNavigationError):
    """Raised when a workspace is not registered."""


class ProductNavigationSafetyError(ProductNavigationError):
    """Raised when a navigation payload violates the safe view-model boundary."""


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, BaseModel):
        return model.dict()
    return dict(model)


class ProductNavigationService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        project_creation_service: ProjectCreationService | None = None,
        template_demo_seed_service: TemplateDemoSeedService | None = None,
        model_settings_service: ModelSettingsService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.preferences_file = self.data_dir / PRODUCT_NAVIGATION_PREFERENCES_FILE
        self.project_creation_service = project_creation_service or ProjectCreationService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.template_demo_seed_service = template_demo_seed_service or TemplateDemoSeedService(
            store=self.store,
            data_dir=self.data_dir,
            project_creation_service=self.project_creation_service,
        )
        self.model_settings_service = model_settings_service or ModelSettingsService(
            store=self.store,
            data_dir=self.data_dir,
        )

    def workspaces(self) -> ProductWorkspaceDefinitionsResponse:
        payload = ProductWorkspaceDefinitionsResponse(workspaces=self._workspace_registry())
        self._guard_safe_payload(model_to_dict(payload))
        return payload

    def groups(self) -> ProductNavigationGroupsResponse:
        payload = ProductNavigationGroupsResponse(groups=self._navigation_groups())
        self._guard_safe_payload(model_to_dict(payload))
        return payload

    def availability(
        self,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> WorkspaceAvailabilityReport:
        mode_profile = self._mode_profile(mode_profile_id)
        active_project_id = self._active_project_id()
        selected_project_id = project_id or active_project_id
        project_summary = self._project_summary(selected_project_id)
        origin = project_summary.get("origin")
        badge = project_summary.get("badge")
        active_model_available, model_warning = self._active_model_available()
        story_data_dir = self._story_data_dir_for_project(selected_project_id)
        final_package_available = self._has_records(PHASE7_FINAL_PACKAGE_FILES, data_dir=story_data_dir)
        story_draft_complete_available = self._story_draft_complete_exists(story_data_dir)
        plugin_artifact_available = self._has_records(PHASE7_PLUGIN_ARTIFACT_FILES, data_dir=story_data_dir)
        story_data_setup_required = self._story_data_setup_required(
            selected_project_id=selected_project_id,
            active_project_id=active_project_id,
        )
        items = [
            self._availability_for_workspace(
                workspace=workspace,
                mode_profile=mode_profile,
                selected_project_id=selected_project_id,
                active_project_id=active_project_id,
                origin=origin,
                badge=badge,
                active_model_available=active_model_available,
                model_warning=model_warning,
                final_package_available=final_package_available,
                story_draft_complete_available=story_draft_complete_available,
                plugin_artifact_available=plugin_artifact_available,
                story_data_setup_required=story_data_setup_required,
            )
            for workspace in self._workspace_registry()
        ]
        report = WorkspaceAvailabilityReport(
            project_id=selected_project_id,
            active_project_id=active_project_id,
            mode_profile_id=mode_profile.mode_profile_id,
            items=items,
            generated_from_authorities=[
                "phase8_m1_model_settings",
                "phase8_m2_project_creation",
                "phase8_m4_project_origin_badge",
                "phase7_artifact_presence_read_only",
                "phase3_story_progress_read_only",
            ],
            safe_summary="Product navigation availability is a read-only view model.",
            warnings=[model_warning] if model_warning else [],
        )
        self._guard_safe_payload(model_to_dict(report))
        return report

    def access(
        self,
        workspace_id: str,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> WorkspaceAvailabilityItem:
        self._get_workspace(workspace_id)
        report = self.availability(project_id=project_id, mode_profile_id=mode_profile_id)
        for item in report.items:
            if item.workspace_id == workspace_id:
                return item
        raise ProductNavigationNotFound(f"workspace_not_registered:{workspace_id}")

    def state(
        self,
        project_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> ProductNavigationState:
        preference = self.preferences()
        resolved_mode_profile_id = mode_profile_id or preference.mode_profile_id
        mode_profile = self._mode_profile(resolved_mode_profile_id)
        active_project_id = self._active_project_id()
        selected_project_id = project_id or active_project_id
        active_workspace_id = workspace_id or preference.last_workspace_id or "home"
        if active_workspace_id not in {workspace.workspace_id for workspace in self._workspace_registry()}:
            active_workspace_id = "home"
        availability = self.availability(
            project_id=selected_project_id,
            mode_profile_id=mode_profile.mode_profile_id,
        )
        project_summary = self._project_summary(selected_project_id)
        header = self._current_project_header(project_summary)
        state = ProductNavigationState(
            active_workspace_id=active_workspace_id,
            selected_project_id=selected_project_id,
            active_project_id=active_project_id,
            groups=self._navigation_groups(),
            workspaces=self._workspace_registry(),
            availability=availability,
            mode_profile=mode_profile,
            preference=preference,
            current_project_header=header,
            origin_badge=project_summary.get("badge"),
            safe_summary="Product navigation state is read-only and does not create story facts.",
            warnings=availability.warnings,
        )
        self._guard_safe_payload(model_to_dict(state))
        return state

    def preferences(self) -> UserWorkspacePreference:
        if not self.store.exists(self.preferences_file):
            return UserWorkspacePreference(updated_at=utc_now())
        try:
            preference = UserWorkspacePreference(**self.store.read(self.preferences_file))
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError("Product navigation preference storage is invalid.") from exc
        self._guard_safe_payload(model_to_dict(preference))
        return preference

    def patch_preferences(
        self,
        request: PatchUserWorkspacePreferenceRequest,
    ) -> UserWorkspacePreference:
        self._guard_safe_payload(model_to_dict(request))
        current = self.preferences()
        workspace_ids = {workspace.workspace_id for workspace in self._workspace_registry()}
        mode_profile_id = request.mode_profile_id or current.mode_profile_id
        if mode_profile_id not in {"ordinary", "expert"}:
            raise ProductNavigationError("unsupported_mode_profile_id")
        last_workspace_id = request.last_workspace_id or current.last_workspace_id
        if last_workspace_id not in workspace_ids:
            raise ProductNavigationError("unknown_last_workspace_id")
        collapsed_group_ids = (
            request.collapsed_group_ids
            if request.collapsed_group_ids is not None
            else current.collapsed_group_ids
        )
        pinned_workspace_ids = (
            request.pinned_workspace_ids
            if request.pinned_workspace_ids is not None
            else current.pinned_workspace_ids
        )
        group_ids = {group.group_id for group in self._navigation_groups()}
        if any(group_id not in group_ids for group_id in collapsed_group_ids):
            raise ProductNavigationError("unknown_collapsed_group_id")
        if any(workspace_id not in workspace_ids for workspace_id in pinned_workspace_ids):
            raise ProductNavigationError("unknown_pinned_workspace_id")
        preference = UserWorkspacePreference(
            preference_id=current.preference_id,
            mode_profile_id=mode_profile_id,
            last_workspace_id=last_workspace_id,
            collapsed_group_ids=list(dict.fromkeys(collapsed_group_ids)),
            pinned_workspace_ids=list(dict.fromkeys(pinned_workspace_ids)),
            ui_preference_only=True,
            safe_summary="Product navigation preference only; no project or story data changed.",
            updated_at=utc_now(),
        )
        self._guard_safe_payload(model_to_dict(preference))
        self.store.write(self.preferences_file, model_to_dict(preference))
        return preference

    def _availability_for_workspace(
        self,
        workspace: ProductWorkspaceDefinition,
        mode_profile: WorkspaceModeProfile,
        selected_project_id: Optional[str],
        active_project_id: Optional[str],
        origin: Any,
        badge: Optional[dict[str, Any]],
        active_model_available: bool,
        model_warning: str,
        final_package_available: bool,
        story_draft_complete_available: bool,
        plugin_artifact_available: bool,
        story_data_setup_required: bool,
    ) -> WorkspaceAvailabilityItem:
        visibility = "ordinary_visible"
        if not workspace.ordinary_visible:
            visibility = "expert_only" if workspace.expert_visible else "hidden"
        if not workspace.expert_visible:
            visibility = "hidden"

        status = "available"
        can_access = True
        blocked_reason = ""
        required_next_step = ""
        redirect = workspace.workspace_id
        warnings = list(workspace.warnings)
        source_refs = list(workspace.source_authority_refs)
        origin_type = getattr(origin, "origin_type", "none") if origin else "none"
        origin_badge_label = badge.get("badge_label", "") if badge else ""
        requires_origin_review = bool(badge.get("requires_origin_review")) if badge else False
        origin_allows_story_setup_boundary = (
            not requires_origin_review
            and (not workspace.allowed_origin_types or origin_type in workspace.allowed_origin_types)
            and origin_type not in workspace.blocked_origin_types
        )

        if (
            story_data_setup_required
            and origin_allows_story_setup_boundary
            and workspace.workspace_id == "story_setup"
        ):
            status = "available"
            can_access = True
            blocked_reason = ""
            required_next_step = "story_setup_world_canvas"
            redirect = "story_setup"
            source_refs.append("phase8_5_active_project_story_setup_boundary")
        elif (
            story_data_setup_required
            and origin_allows_story_setup_boundary
            and workspace.workspace_id in SETUP_GATED_STORY_WORKSPACES
        ):
            status = "needs_setup"
            can_access = False
            blocked_reason = "story_data_setup_required_for_active_project"
            required_next_step = "story_setup_world_canvas"
            redirect = "story_setup"
            source_refs.append("phase8_5_active_project_story_setup_boundary")
        elif visibility == "hidden":
            status = "hidden"
            can_access = False
            blocked_reason = "workspace_hidden"
            redirect = "home"
        elif visibility == "expert_only" and mode_profile.mode_profile_id != "expert":
            status = "hidden"
            can_access = False
            blocked_reason = "expert_workspace_hidden_in_ordinary_mode"
            redirect = "home"
        elif workspace.requires_project and not selected_project_id:
            status = "needs_setup"
            can_access = False
            blocked_reason = "project_required"
            required_next_step = "create_or_open_project"
            redirect = "create_project"
        elif workspace.requires_origin_review_clear and requires_origin_review:
            status = "blocked"
            can_access = False
            blocked_reason = "origin_review_required"
            required_next_step = "review_project_origin"
            redirect = "current_project"
        elif workspace.allowed_origin_types and origin_type not in workspace.allowed_origin_types:
            status = "blocked"
            can_access = False
            blocked_reason = "origin_type_not_allowed"
            required_next_step = "choose_supported_project_origin"
            redirect = "current_project"
        elif workspace.blocked_origin_types and origin_type in workspace.blocked_origin_types:
            status = "blocked"
            can_access = False
            blocked_reason = "origin_type_blocked_for_workspace"
            required_next_step = "choose_real_user_project"
            redirect = "current_project"
        elif workspace.requires_active_model and not active_model_available:
            status = "needs_setup"
            can_access = False
            blocked_reason = "active_model_required"
            required_next_step = "configure_active_model"
            redirect = "settings"
            if model_warning:
                warnings.append(model_warning)
        elif workspace.requires_final_story_package and not (
            final_package_available or story_draft_complete_available
        ):
            status = "unavailable"
            can_access = False
            blocked_reason = "final_story_package_missing"
            required_next_step = "complete_final_story_package_export"
            redirect = "current_project"
        elif (
            workspace.requires_final_story_package
            and story_draft_complete_available
            and not final_package_available
        ):
            status = "available"
            can_access = True
            blocked_reason = ""
            required_next_step = "create_final_story_package_export"
            redirect = workspace.workspace_id
            warnings.append("final_story_package_missing")
            source_refs.append("phase3_story_progress_story_draft_complete")
        elif workspace.requires_plugin_artifact and not plugin_artifact_available:
            status = "unavailable"
            can_access = False
            blocked_reason = "plugin_output_artifact_missing"
            required_next_step = "run_plugin_and_create_artifact"
            redirect = "final_outputs"

        if workspace.workspace_id == "create_project" and not active_model_available and model_warning:
            warnings.append(model_warning)

        return WorkspaceAvailabilityItem(
            workspace_id=workspace.workspace_id,
            availability_status=status,
            visibility=visibility,
            can_access=can_access,
            blocked_reason=blocked_reason,
            required_next_step=required_next_step,
            safe_redirect_workspace_id=redirect,
            project_id=selected_project_id,
            origin_type=origin_type,
            origin_badge_label=origin_badge_label,
            source_authority_refs=source_refs,
            safe_summary=self._availability_summary(workspace.workspace_id, status),
            warnings=list(dict.fromkeys(warnings)),
        )

    def _current_project_header(self, project_summary: dict[str, Any]) -> CurrentProjectHeader:
        project = project_summary.get("project")
        origin = project_summary.get("origin")
        badge = project_summary.get("badge") or {}
        active_model_available, _ = self._active_model_available()
        return CurrentProjectHeader(
            project_id=getattr(project, "project_id", None) if project else None,
            title=getattr(project, "title", "") if project else "",
            origin_type=getattr(origin, "origin_type", "none") if origin else "none",
            origin_badge_label=badge.get("badge_label", ""),
            origin_requires_review=bool(badge.get("requires_origin_review")),
            active_model_status="configured" if active_model_available else "missing",
            safe_summary="Current project header is a lightweight navigation view model.",
        )

    def _project_summary(self, project_id: Optional[str]) -> dict[str, Any]:
        if not project_id:
            return {}
        try:
            summary = self.project_creation_service.get_project(project_id)
            badge_model = self.template_demo_seed_service.project_origin_badge(project_id)
        except Exception:
            return {}
        return {
            "project": summary.project,
            "origin": summary.origin,
            "badge": model_to_dict(badge_model),
        }

    def _active_project_id(self) -> Optional[str]:
        try:
            selection = self.project_creation_service.get_active_project_selection()
        except Exception:
            return None
        return selection.active_project_selection.project_id if selection.active_project_selection else None

    def _story_data_setup_required(
        self,
        *,
        selected_project_id: Optional[str],
        active_project_id: Optional[str],
    ) -> bool:
        if not selected_project_id or selected_project_id != active_project_id:
            return False
        try:
            blocked_project_id = ActiveProjectBoundaryService(
                store=self.store,
                data_dir=self.data_dir,
            ).non_legacy_active_project_id_without_story_scope()
        except Exception:
            return False
        return blocked_project_id == selected_project_id

    def _active_model_available(self) -> tuple[bool, str]:
        try:
            workbench = self.model_settings_service.workbench()
        except Exception:
            return False, "model_settings_unavailable"
        blockers = getattr(workbench, "blockers", []) or []
        warnings = getattr(workbench, "warnings", []) or []
        has_selection = bool(getattr(workbench, "active_selection_id", None))
        if not has_selection:
            return False, "no_active_model_selection"
        if blockers:
            return False, blockers[0]
        if getattr(workbench, "current_provider", "") and getattr(workbench, "current_provider", "") != "local":
            if any("api_key_missing" in warning or "api_key_invalid" in warning for warning in warnings):
                return False, "active_model_api_key_missing"
        return True, warnings[0] if warnings else ""

    def _has_records(self, file_names: tuple[str, ...], *, data_dir: Path | None = None) -> bool:
        record_dir = data_dir or self.data_dir
        for file_name in file_names:
            path = record_dir / file_name
            if not self.store.exists(path):
                continue
            try:
                payload = self.store.read_any(path)
            except StorageError:
                continue
            if isinstance(payload, list) and len(payload) > 0:
                return True
            if isinstance(payload, dict):
                if any(isinstance(value, list) and value for value in payload.values()):
                    return True
                if payload:
                    return True
        return False

    def _story_draft_complete_exists(self, story_data_dir: Path) -> bool:
        story_progress_path = story_data_dir / "story_progress.json"
        try:
            story_progress = (
                self.store.read_any(story_progress_path)
                if self.store.exists(story_progress_path)
                else {}
            )
        except StorageError:
            story_progress = {}
        if isinstance(story_progress, dict):
            if str(story_progress.get("story_progress_status") or "") == "story_draft_complete":
                return True

        decisions_path = story_data_dir / "decisions.json"
        try:
            decisions = (
                self.store.read_any(decisions_path)
                if self.store.exists(decisions_path)
                else []
            )
        except StorageError:
            decisions = []
        if not isinstance(decisions, list):
            return False
        for decision in reversed([item for item in decisions if isinstance(item, dict)]):
            if (
                str(decision.get("target_type") or "") == "story_progress"
                and str(decision.get("target_id") or "") == "story_draft_complete"
                and str(decision.get("decision_type") or "") in {"confirm", "approve", "complete"}
            ):
                return True
        return False

    def _story_data_dir_for_project(self, selected_project_id: Optional[str]) -> Path:
        project_id = str(selected_project_id or "").strip()
        if not project_id:
            return self.data_dir
        candidate = story_data_dir_for_project(project_id, self.data_dir)
        if candidate == self.data_dir:
            return self.data_dir
        if story_data_dir_has_project(self.store, candidate, project_id):
            return candidate
        return self.data_dir

    def _get_workspace(self, workspace_id: str) -> ProductWorkspaceDefinition:
        for workspace in self._workspace_registry():
            if workspace.workspace_id == workspace_id:
                return workspace
        raise ProductNavigationNotFound(f"workspace_not_registered:{workspace_id}")

    def _mode_profile(self, mode_profile_id: Optional[str]) -> WorkspaceModeProfile:
        if mode_profile_id == "expert":
            return WorkspaceModeProfile(
                mode_profile_id="expert",
                display_name="专家视图",
                ordinary_default=False,
                expert_discoverable=True,
                debug_routes_visible=True,
                safe_summary="Expert diagnostics are visible without changing story data.",
            )
        return WorkspaceModeProfile(
            mode_profile_id="ordinary",
            display_name="普通视图",
            ordinary_default=True,
            expert_discoverable=True,
            debug_routes_visible=False,
            safe_summary="Ordinary navigation hides debug clutter by default.",
        )

    def _workspace_registry(self) -> list[ProductWorkspaceDefinition]:
        refs = {
            "m1": ["phase8_m1_model_settings"],
            "m2": ["phase8_m2_project_creation"],
            "m4": ["phase8_m4_project_origin_badge"],
            "p7": ["phase7_read_only_artifact_presence"],
        }
        real_story_blocks = ["demo_seed"]
        definitions = [
            ProductWorkspaceDefinition(
                workspace_id="home",
                display_name="首页",
                group_id="home",
                route_key="home",
                workspace_kind="home",
                source_authority_refs=["phase8_m5_static_registry"],
                safe_summary="Product workbench home entry.",
                sort_order=10,
            ),
            ProductWorkspaceDefinition(
                workspace_id="projects",
                display_name="项目列表",
                group_id="creation",
                route_key="project",
                workspace_kind="project_registry",
                source_authority_refs=refs["m2"],
                safe_summary="Open or inspect project shells.",
                sort_order=20,
            ),
            ProductWorkspaceDefinition(
                workspace_id="create_project",
                display_name="创建项目",
                group_id="creation",
                route_key="project",
                workspace_kind="creation",
                source_authority_refs=refs["m2"] + refs["m1"],
                safe_summary="Create a project shell; does not confirm story facts.",
                sort_order=30,
            ),
            ProductWorkspaceDefinition(
                workspace_id="analyze_stories",
                display_name="故事分析器",
                group_id="creation",
                route_key="analyze",
                workspace_kind="analysis_import",
                source_authority_refs=["analyze_stories_import_pipeline"],
                safe_summary="Analyze existing stories, manage imports, and prepare framework candidates.",
                sort_order=35,
            ),
            ProductWorkspaceDefinition(
                workspace_id="current_project",
                display_name="当前项目",
                group_id="current_project",
                route_key="current_project",
                workspace_kind="project_view",
                requires_project=True,
                source_authority_refs=refs["m2"] + refs["m4"],
                safe_summary="Current project overview with origin badge.",
                sort_order=40,
            ),
            ProductWorkspaceDefinition(
                workspace_id="template_demo",
                display_name="模板与演示",
                group_id="current_project",
                route_key="template_demo",
                workspace_kind="origin_handoff",
                requires_project=True,
                source_authority_refs=refs["m2"] + refs["m4"],
                safe_summary="Template and demo handoff entry; no demo-to-real conversion.",
                sort_order=45,
            ),
            ProductWorkspaceDefinition(
                workspace_id="story_setup",
                display_name="故事设定",
                group_id="story_workspace",
                route_key="story_setup",
                workspace_kind="story_setup",
                requires_project=True,
                requires_active_model=True,
                requires_origin_review_clear=True,
                blocked_origin_types=real_story_blocks,
                source_authority_refs=refs["m1"] + refs["m2"] + refs["m4"],
                safe_summary="Prompt-first setup entry; downstream facts still need confirmation.",
                sort_order=50,
            ),
            ProductWorkspaceDefinition(
                workspace_id="world_canvas",
                display_name="世界画布",
                group_id="story_workspace",
                route_key="world_canvas",
                workspace_kind="story_workspace",
                requires_project=True,
                requires_active_model=True,
                requires_origin_review_clear=True,
                blocked_origin_types=real_story_blocks,
                source_authority_refs=refs["m1"] + refs["m2"] + refs["m4"],
                safe_summary="World canvas authoring workspace.",
                sort_order=60,
            ),
            ProductWorkspaceDefinition(
                workspace_id="characters",
                display_name="角色",
                group_id="story_workspace",
                route_key="characters",
                workspace_kind="story_workspace",
                requires_project=True,
                requires_active_model=True,
                requires_origin_review_clear=True,
                blocked_origin_types=real_story_blocks,
                source_authority_refs=refs["m1"] + refs["m2"] + refs["m4"],
                safe_summary="Character and role state workspace.",
                sort_order=70,
            ),
            ProductWorkspaceDefinition(
                workspace_id="framework",
                display_name="框架",
                group_id="story_workspace",
                route_key="framework",
                workspace_kind="story_workspace",
                requires_project=True,
                requires_active_model=True,
                requires_origin_review_clear=True,
                blocked_origin_types=real_story_blocks,
                source_authority_refs=refs["m1"] + refs["m2"] + refs["m4"],
                safe_summary="Framework workbench entry.",
                sort_order=80,
            ),
            ProductWorkspaceDefinition(
                workspace_id="chapter_plan",
                display_name="章节计划",
                group_id="story_workspace",
                route_key="chapter_plan",
                workspace_kind="story_workspace",
                requires_project=True,
                requires_active_model=True,
                requires_origin_review_clear=True,
                blocked_origin_types=real_story_blocks,
                source_authority_refs=refs["m1"] + refs["m2"] + refs["m4"],
                safe_summary="Chapter planning workspace.",
                sort_order=90,
            ),
            ProductWorkspaceDefinition(
                workspace_id="chapter_scene",
                display_name="场景写作",
                group_id="story_workspace",
                route_key="scene",
                workspace_kind="story_workspace",
                requires_project=True,
                requires_active_model=True,
                requires_origin_review_clear=True,
                blocked_origin_types=real_story_blocks,
                source_authority_refs=refs["m1"] + refs["m2"] + refs["m4"],
                safe_summary="Scene generation workspace.",
                sort_order=100,
            ),
            ProductWorkspaceDefinition(
                workspace_id="memory_continuity",
                display_name="记忆与连续性",
                group_id="story_workspace",
                route_key="scene",
                workspace_kind="story_workspace",
                requires_project=True,
                requires_active_model=True,
                requires_origin_review_clear=True,
                blocked_origin_types=real_story_blocks,
                source_authority_refs=refs["m1"] + refs["m2"] + refs["m4"],
                safe_summary="Memory and continuity surfaces inside scene workflow.",
                sort_order=110,
            ),
            ProductWorkspaceDefinition(
                workspace_id="formal_apply",
                display_name="正式应用",
                group_id="expert_diagnostics",
                route_key="debug",
                workspace_kind="expert_diagnostics",
                default_visibility="expert",
                ordinary_visible=False,
                expert_visible=True,
                requires_project=True,
                requires_active_model=True,
                requires_origin_review_clear=True,
                blocked_origin_types=real_story_blocks,
                source_authority_refs=["phase6_formal_apply_read_only_status"],
                safe_summary="Expert-only formal apply diagnostics entry.",
                sort_order=210,
            ),
            ProductWorkspaceDefinition(
                workspace_id="final_outputs",
                display_name="最终输出",
                group_id="outputs",
                route_key="final_outputs",
                workspace_kind="output_surface",
                requires_project=True,
                requires_final_story_package=True,
                source_authority_refs=refs["p7"],
                safe_summary="Read-only Final Story Package entry.",
                sort_order=120,
            ),
            ProductWorkspaceDefinition(
                workspace_id="plugin_outputs",
                display_name="插件输出",
                group_id="outputs",
                route_key="plugin_outputs",
                workspace_kind="output_surface",
                requires_project=True,
                requires_plugin_artifact=True,
                source_authority_refs=refs["p7"],
                safe_summary="Read-only Plugin Output Artifact entry.",
                sort_order=130,
            ),
            ProductWorkspaceDefinition(
                workspace_id="settings",
                display_name="模型设置",
                group_id="settings",
                route_key="settings",
                workspace_kind="settings",
                source_authority_refs=refs["m1"],
                safe_summary="Model provider management entry.",
                sort_order=140,
            ),
            ProductWorkspaceDefinition(
                workspace_id="expert_diagnostics",
                display_name="专家诊断",
                group_id="expert_diagnostics",
                route_key="debug",
                workspace_kind="expert_diagnostics",
                default_visibility="expert",
                ordinary_visible=False,
                expert_visible=True,
                requires_project=True,
                source_authority_refs=["phase6_phase7_read_only_diagnostics"],
                safe_summary="Expert diagnostics index; hidden in ordinary navigation.",
                sort_order=200,
            ),
            ProductWorkspaceDefinition(
                workspace_id="evidence_index",
                display_name="证据索引",
                group_id="expert_diagnostics",
                route_key="debug",
                workspace_kind="expert_diagnostics",
                default_visibility="expert",
                ordinary_visible=False,
                expert_visible=True,
                requires_project=True,
                source_authority_refs=["phase6_phase7_read_only_evidence_index"],
                safe_summary="Expert-only evidence index entry.",
                sort_order=220,
            ),
            ProductWorkspaceDefinition(
                workspace_id="verifier",
                display_name="验证器",
                group_id="expert_diagnostics",
                route_key="debug",
                workspace_kind="expert_diagnostics",
                default_visibility="expert",
                ordinary_visible=False,
                expert_visible=True,
                requires_project=True,
                source_authority_refs=["phase6_phase7_read_only_verifier_records"],
                safe_summary="Expert-only verifier records entry.",
                sort_order=230,
            ),
            ProductWorkspaceDefinition(
                workspace_id="storage_diagnostics",
                display_name="存储诊断",
                group_id="expert_diagnostics",
                route_key="debug",
                workspace_kind="expert_diagnostics",
                default_visibility="expert",
                ordinary_visible=False,
                expert_visible=True,
                requires_project=True,
                source_authority_refs=["phase6_phase7_read_only_storage_diagnostics"],
                safe_summary="Expert-only storage diagnostics entry.",
                sort_order=240,
            ),
            ProductWorkspaceDefinition(
                workspace_id="debug_center",
                display_name="调试中心",
                group_id="expert_diagnostics",
                route_key="debug",
                workspace_kind="expert_diagnostics",
                default_visibility="expert",
                ordinary_visible=False,
                expert_visible=True,
                requires_project=True,
                source_authority_refs=["phase2_phase7_debug_read_only_surfaces"],
                safe_summary="Expert-only debug center entry.",
                sort_order=250,
            ),
        ]
        return sorted(definitions, key=lambda item: item.sort_order)

    def _navigation_groups(self) -> list[ProductNavigationGroup]:
        workspace_ids_by_group: dict[str, list[str]] = {}
        for workspace in self._workspace_registry():
            workspace_ids_by_group.setdefault(workspace.group_id, []).append(workspace.workspace_id)
        groups = [
            ProductNavigationGroup(
                group_id="home",
                display_name="首页",
                group_kind="ordinary",
                workspace_ids=workspace_ids_by_group.get("home", []),
                safe_summary="Home group.",
                sort_order=10,
            ),
            ProductNavigationGroup(
                group_id="creation",
                display_name="项目创建",
                group_kind="ordinary",
                workspace_ids=workspace_ids_by_group.get("creation", []),
                safe_summary="Project creation and registry group.",
                sort_order=20,
            ),
            ProductNavigationGroup(
                group_id="current_project",
                display_name="当前项目",
                group_kind="ordinary",
                workspace_ids=workspace_ids_by_group.get("current_project", []),
                safe_summary="Current project group.",
                sort_order=30,
            ),
            ProductNavigationGroup(
                group_id="story_workspace",
                display_name="故事工作区",
                group_kind="ordinary",
                workspace_ids=workspace_ids_by_group.get("story_workspace", []),
                safe_summary="Story authoring workspaces.",
                sort_order=40,
            ),
            ProductNavigationGroup(
                group_id="outputs",
                display_name="输出",
                group_kind="ordinary",
                workspace_ids=workspace_ids_by_group.get("outputs", []),
                safe_summary="Read-only output entry surfaces.",
                sort_order=50,
            ),
            ProductNavigationGroup(
                group_id="settings",
                display_name="设置",
                group_kind="ordinary",
                workspace_ids=workspace_ids_by_group.get("settings", []),
                safe_summary="Configuration group.",
                sort_order=60,
            ),
            ProductNavigationGroup(
                group_id="expert_diagnostics",
                display_name="专家诊断",
                group_kind="expert_diagnostics",
                ordinary_visible=False,
                expert_visible=True,
                workspace_ids=workspace_ids_by_group.get("expert_diagnostics", []),
                safe_summary="Expert-only diagnostics entries.",
                sort_order=90,
            ),
        ]
        return sorted(groups, key=lambda item: item.sort_order)

    def _availability_summary(self, workspace_id: str, status: str) -> str:
        return f"Workspace {workspace_id} availability is {status}; navigation did not mutate story data."

    def _guard_safe_payload(self, payload: Any, label: str = "product_navigation") -> None:
        text = str(payload)
        lower_text = text.lower()
        issues = [marker for marker in UNSAFE_TEXT_MARKERS if marker in lower_text]
        if SECRET_LIKE_RE.search(text):
            issues.append("secret_like_value")
        if issues:
            raise ProductNavigationSafetyError(f"{label}_unsafe_payload:{issues[0]}")
