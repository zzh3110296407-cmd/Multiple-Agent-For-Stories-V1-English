import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.app_progress import AppProgressResponse
from app.backend.models.product_navigation import PatchUserWorkspacePreferenceRequest
from app.backend.models.product_progress import (
    BlockingIssueSurface,
    ExpertEvidenceLink,
    NextRecommendedAction,
    PatchProductModeProfileRequest,
    ProductModeProfile,
    ProductProgressAggregateResponse,
    ProductProgressSafetyReport,
    ProductProgressSummary,
    UserDecisionSurface,
)
from app.backend.services.app_progress_service import AppProgressService
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.model_settings_service import ModelSettingsService
from app.backend.services.product_navigation_service import ProductNavigationService
from app.backend.services.project_creation_service import ProjectCreationService
from app.backend.storage.json_store import JsonStore, StorageError


SCHEMA_VERSION = "phase8_m6_product_progress_v1"
STORY_SETUP_HANDOFFS_FILE = "story_setup_handoffs.json"
STORY_SETUP_DECISIONS_FILE = "story_setup_decisions.json"
STORY_SETUP_DRAFT_BUNDLES_FILE = "story_setup_draft_bundles.json"
TEMPLATE_INSTANTIATION_REPORTS_FILE = "template_instantiation_reports.json"
DEMO_SEED_RUNS_FILE = "demo_seed_runs.json"

FINAL_PACKAGE_FILES = (
    "final_story_package_readiness_reports.json",
    "final_story_package_snapshots.json",
    "final_story_package_export_runs.json",
)
PLUGIN_OUTPUT_FILES = (
    "plugin_output_artifacts.json",
    "plugin_output_artifact_versions.json",
    "plugin_runs.json",
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
    "full story prose",
    "full_story_prose",
    "full screenplay text",
    "full_screenplay_text",
    "final story package full content",
    "plugin output full content",
    "debug mutation",
    "debug_mutation",
    "provider_payload",
    "provider payload",
    "provider_response",
    "provider response",
)
SECRET_LIKE_RE = re.compile(
    r"(?<![A-Za-z])sk-[A-Za-z0-9_\-]{8,}|lsv2_[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,}|Authorization\s*:",
    re.I,
)


class ProductProgressError(RuntimeError):
    """Base error for Phase 8 M6 product-safe progress."""


class ProductProgressSafetyError(ProductProgressError):
    """Raised when progress payload would expose unsafe content."""


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, BaseModel):
        return model.dict()
    return dict(model)


def _safe_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("items", "records", "runs", "reports", "snapshots", "artifacts"):
            child = value.get(key)
            if isinstance(child, list):
                return len(child)
        return len(value)
    return 0


class ProductProgressService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        project_file: Path | None = None,
        product_navigation_service: ProductNavigationService | None = None,
        project_creation_service: ProjectCreationService | None = None,
        model_settings_service: ModelSettingsService | None = None,
        app_progress_service: AppProgressService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.project_file = project_file or settings.project_file
        self.project_creation_service = project_creation_service or ProjectCreationService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.model_settings_service = model_settings_service or ModelSettingsService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.product_navigation_service = product_navigation_service or ProductNavigationService(
            store=self.store,
            data_dir=self.data_dir,
            project_creation_service=self.project_creation_service,
            model_settings_service=self.model_settings_service,
        )
        self.app_progress_service = app_progress_service or AppProgressService(
            store=self.store,
            data_dir=self.data_dir,
            project_file=self.project_file,
        )

    def get_mode_profile(self, mode_profile_id: Optional[str] = None) -> ProductModeProfile:
        preference = self.product_navigation_service.preferences()
        resolved = mode_profile_id or preference.mode_profile_id
        if resolved not in {"ordinary", "expert"}:
            raise ProductProgressError("unsupported_mode_profile_id")
        profile = ProductModeProfile(
            mode_profile_id=resolved,
            display_name="专家模式" if resolved == "expert" else "普通模式",
            ordinary_mode=resolved == "ordinary",
            expert_mode=resolved == "expert",
            display_preference_only=True,
            permission_authority=False,
            debug_mutation_authority=False,
            source_preference_ref=preference.preference_id,
            safe_summary="Mode changes only affect product display preference.",
            warnings=[],
        )
        self._guard_safe_payload(model_to_dict(profile), label="product_mode_profile")
        return profile

    def patch_mode_profile(
        self,
        request: PatchProductModeProfileRequest,
    ) -> ProductModeProfile:
        if request.mode_profile_id not in {"ordinary", "expert"}:
            raise ProductProgressError("unsupported_mode_profile_id")
        current = self.product_navigation_service.preferences()
        self.product_navigation_service.patch_preferences(
            PatchUserWorkspacePreferenceRequest(
                mode_profile_id=request.mode_profile_id,
                last_workspace_id=current.last_workspace_id,
                collapsed_group_ids=current.collapsed_group_ids,
                pinned_workspace_ids=current.pinned_workspace_ids,
            )
        )
        return self.get_mode_profile(request.mode_profile_id)

    def state(
        self,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> ProductProgressAggregateResponse:
        navigation_state = self.product_navigation_service.state(
            project_id=project_id,
            mode_profile_id=mode_profile_id,
        )
        mode_profile = self.get_mode_profile(navigation_state.mode_profile.mode_profile_id)
        active_project_id = navigation_state.active_project_id
        selected_project_id = project_id or active_project_id
        project_summary = self._project_summary(selected_project_id)
        origin = project_summary.get("origin")
        badge = navigation_state.origin_badge or project_summary.get("badge") or {}
        model_workbench = self._model_workbench()
        app_progress = (
            self._safe_app_progress()
            if self._can_use_active_app_progress(selected_project_id, active_project_id)
            else None
        )

        summary = self._summary(
            selected_project_id=selected_project_id,
            active_project_id=active_project_id,
            origin=origin,
            badge=badge,
            model_workbench=model_workbench,
            app_progress=app_progress,
        )
        if selected_project_id and active_project_id and selected_project_id != active_project_id:
            summary.warnings = list(
                dict.fromkeys(
                    summary.warnings
                    + ["project_scoped_progress_does_not_use_active_app_progress"]
                )
            )
        next_actions = self._next_actions(
            summary=summary,
            origin=origin,
            app_progress=app_progress,
            model_workbench=model_workbench,
        )
        decision_surfaces = self._decision_surfaces(summary, app_progress)
        blocking_issues = self._blocking_issues(summary, app_progress, model_workbench)
        evidence_links = (
            self._expert_evidence_links(
                summary=summary,
                navigation_state=navigation_state,
                app_progress=app_progress,
                model_workbench=model_workbench,
            )
            if mode_profile.expert_mode
            else []
        )
        response = ProductProgressAggregateResponse(
            mode_profile=mode_profile,
            summary=summary,
            next_actions=next_actions,
            decision_surfaces=decision_surfaces,
            blocking_issues=blocking_issues,
            expert_evidence_links=evidence_links,
            safety_report=self._safety_report([], []),
            safe_summary="Product progress is a read-only navigation view model.",
            warnings=list(dict.fromkeys(summary.warnings)),
        )
        violations = self._unsafe_payload_issues(model_to_dict(response), label="product_progress")
        response.safety_report = self._safety_report(violations, summary.warnings)
        if violations:
            raise ProductProgressSafetyError(f"product_progress_unsafe_payload:{violations[0]}")
        return response

    def summary(
        self,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> ProductProgressSummary:
        return self.state(project_id=project_id, mode_profile_id=mode_profile_id).summary

    def next_actions(
        self,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> list[NextRecommendedAction]:
        return self.state(project_id=project_id, mode_profile_id=mode_profile_id).next_actions

    def decision_surfaces(
        self,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> list[UserDecisionSurface]:
        return self.state(project_id=project_id, mode_profile_id=mode_profile_id).decision_surfaces

    def blocking_issues(
        self,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> list[BlockingIssueSurface]:
        return self.state(project_id=project_id, mode_profile_id=mode_profile_id).blocking_issues

    def expert_evidence(
        self,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = "expert",
    ) -> list[ExpertEvidenceLink]:
        return self.state(project_id=project_id, mode_profile_id=mode_profile_id).expert_evidence_links

    def safety_report(
        self,
        project_id: Optional[str] = None,
        mode_profile_id: Optional[str] = None,
    ) -> ProductProgressSafetyReport:
        return self.state(project_id=project_id, mode_profile_id=mode_profile_id).safety_report

    def _summary(
        self,
        selected_project_id: Optional[str],
        active_project_id: Optional[str],
        origin: Any,
        badge: dict[str, Any],
        model_workbench: Any,
        app_progress: AppProgressResponse | None,
    ) -> ProductProgressSummary:
        no_project = selected_project_id is None
        origin_type = getattr(origin, "origin_type", "none") if origin else "none"
        demo_project = bool(getattr(origin, "is_demo_project", False)) or origin_type == "demo_seed"
        model_configured = bool(getattr(model_workbench, "active_selection_id", None))
        model_status = "configured" if model_configured else "missing"
        warnings: list[str] = []
        if model_workbench is None:
            model_status = "unknown"
            warnings.append("model_settings_unavailable")
        elif getattr(model_workbench, "blockers", []):
            model_status = "blocked"
            warnings.extend(getattr(model_workbench, "blockers", [])[:3])
        elif getattr(model_workbench, "warnings", []):
            warnings.extend(getattr(model_workbench, "warnings", [])[:3])

        app_progress_has_story_data = (
            self._app_progress_has_story_data(app_progress)
            if app_progress is not None
            else False
        )

        if no_project:
            stage_id = "create_project"
            stage_label = "创建或打开项目"
            status = "no_project"
            ordinary = "还没有选择项目。下一步是创建或打开一个项目。"
        elif demo_project:
            stage_id = "demo_project"
            stage_label = "演示项目"
            status = "demo_project"
            ordinary = "当前是演示项目。真实创作前应创建或打开真实用户项目。"
        elif (
            (app_progress is None or not app_progress_has_story_data)
            and origin_type in {"prompt_first", "template"}
            and self._has_project_setup_records(
                selected_project_id,
                origin_type,
            )
        ):
            stage_id = "story_setup"
            stage_label = "故事设定交接"
            status = "setup_handoff_ready"
            ordinary = "项目设定已有交接记录。下一步是继续确认世界观、角色和框架。"
        elif app_progress is None:
            stage_id = "current_project"
            stage_label = "项目状态"
            status = "project_shell_ready"
            ordinary = "项目壳已存在。下一步是进入故事设定。"
            warnings.append("app_progress_unavailable")
        else:
            action = app_progress.next_recommended_action or "review_project"
            stage_id = self._workspace_for_action(action, app_progress)
            stage_label = self._stage_label(stage_id, action)
            status = action
            ordinary = self._ordinary_summary_for_action(action)

        return ProductProgressSummary(
            project_id=selected_project_id,
            active_project_id=active_project_id,
            summary_status=status,
            current_stage_id=stage_id,
            current_stage_label=stage_label,
            ordinary_summary=ordinary,
            expert_summary_available=True,
            no_project=no_project,
            demo_project=demo_project,
            model_status=model_status,
            origin_type=origin_type,
            origin_badge_label=badge.get("badge_label", ""),
            source_authority_refs=[
                "phase8_m1_model_settings",
                "phase8_m2_project_creation",
                "phase8_m5_product_navigation",
                "app_progress_read_only",
            ],
            safe_summary="Summary is derived from read-only product and app progress state.",
            warnings=list(dict.fromkeys(warnings)),
        )

    def _next_actions(
        self,
        summary: ProductProgressSummary,
        origin: Any,
        app_progress: AppProgressResponse | None,
        model_workbench: Any,
    ) -> list[NextRecommendedAction]:
        if summary.no_project:
            return [
                self._action(
                    "create_project",
                    "创建或打开项目",
                    "还没有活动项目；该操作只导航到项目入口。",
                    "create_project",
                    priority=10,
                )
            ]
        if summary.demo_project:
            return [
                self._action(
                    "choose_real_project",
                    "创建或打开真实项目",
                    "当前项目带演示来源标记，真实创作应切换到用户项目。",
                    "create_project",
                    blocked=True,
                    blocked_reason="demo_project_not_for_real_authoring",
                    priority=15,
                )
            ]
        if summary.model_status in {"missing", "blocked"}:
            return [
                self._action(
                    "configure_active_model",
                    "配置模型",
                    "生成和设定步骤需要可用模型；创建项目本身不受此阻断。",
                    "settings",
                    blocked=True,
                    blocked_reason="active_model_required_for_generation",
                    priority=20,
                )
            ]
        origin_type = getattr(origin, "origin_type", "none") if origin else "none"
        if origin_type in {"prompt_first", "template"} and summary.summary_status == "setup_handoff_ready":
            return [
                self._action(
                    "continue_story_setup",
                    "继续故事设定",
                    "已有设定交接记录；下一步只导航到设定工作区等待用户确认。",
                    "story_setup",
                    required_confirmation=True,
                    priority=25,
                )
            ]
        if app_progress is None:
            return [
                self._action(
                    "continue_story_setup",
                    "进入故事设定",
                    "项目壳已经存在，但故事阶段状态还未建立。",
                    "story_setup",
                    priority=30,
                )
            ]
        action_id = app_progress.next_recommended_action or "review_project"
        workspace_id = self._workspace_for_action(action_id, app_progress)
        return [
            self._action(
                action_id,
                self._title_for_action(action_id),
                self._reason_for_action(action_id, app_progress),
                workspace_id,
                required_confirmation=self._requires_confirmation(action_id),
                priority=40,
            )
        ]

    def _decision_surfaces(
        self,
        summary: ProductProgressSummary,
        app_progress: AppProgressResponse | None,
    ) -> list[UserDecisionSurface]:
        if app_progress is None:
            return []
        surfaces: list[UserDecisionSurface] = []
        if app_progress.world_canvas.exists and app_progress.world_canvas.status != "confirmed":
            surfaces.append(
                self._decision_surface(
                    "confirm_world_canvas",
                    "确认世界画布",
                    "世界画布仍处于草稿状态，需要用户确认后才能作为故事事实。",
                    "world_canvas",
                    "world_canvas_decision",
                )
            )
        if app_progress.main_cast.confirmed_character_count > 0 and not app_progress.main_cast.finished:
            surfaces.append(
                self._decision_surface(
                    "confirm_main_cast",
                    "确认主投角",
                    "主投角需要独立 Decision；不能只依赖角色文件存在。",
                    "characters",
                    "main_cast_decision",
                )
            )
        if app_progress.framework.package_exists and not app_progress.framework.mapping_confirmed:
            surfaces.append(
                self._decision_surface(
                    "confirm_framework_mapping",
                    "确认框架映射",
                    "框架映射尚未确认，后续章节构建前需要用户确认。",
                    "framework",
                    app_progress.framework.last_decision_id,
                )
            )
        if app_progress.chapter_plan.exists and (
            not app_progress.chapter_plan.chapter_plan_decision_exists
            or app_progress.chapter_plan.status != "confirmed"
        ):
            surfaces.append(
                self._decision_surface(
                    "confirm_chapter_plan",
                    "确认章节计划",
                    "章节计划仍等待用户确认。",
                    "chapter_plan",
                    "chapter_plan_decision",
                )
            )
        if app_progress.scene.requires_user_confirmation:
            surfaces.append(
                self._decision_surface(
                    "scene_user_confirmation",
                    "确认场景候选",
                    "当前场景或修订候选需要用户确认。",
                    "chapter_scene",
                    app_progress.scene.quality_target_id or app_progress.scene.scene_id,
                )
            )
        return surfaces

    def _blocking_issues(
        self,
        summary: ProductProgressSummary,
        app_progress: AppProgressResponse | None,
        model_workbench: Any,
    ) -> list[BlockingIssueSurface]:
        issues: list[BlockingIssueSurface] = []
        if summary.demo_project:
            issues.append(
                self._blocking_issue(
                    "demo_project_real_authoring_block",
                    "演示项目不能直接作为真实创作入口",
                    "当前 origin 表示这是演示项目；请创建或打开真实项目。",
                    "create_project",
                    "warning",
                )
            )
        if summary.model_status in {"missing", "blocked"} and not summary.no_project:
            issues.append(
                self._blocking_issue(
                    "active_model_required",
                    "模型未配置",
                    "生成类工作区需要可用模型；项目创建本身仍可继续。",
                    "settings",
                    "blocking",
                )
            )
        if app_progress and app_progress.scene.blocking_issue_count > 0:
            issues.append(
                self._blocking_issue(
                    "scene_quality_blocking_issues",
                    "场景质量阻断",
                    f"当前场景质量门仍有 {app_progress.scene.blocking_issue_count} 个阻断项。",
                    "chapter_scene",
                    "blocking",
                )
            )
        if model_workbench is not None and getattr(model_workbench, "blockers", []):
            issues.append(
                self._blocking_issue(
                    "model_settings_blocker",
                    "模型设置阻断",
                    "模型设置存在阻断项，请到模型设置查看安全摘要。",
                    "settings",
                    "blocking",
                )
            )
        return issues

    def _expert_evidence_links(
        self,
        summary: ProductProgressSummary,
        navigation_state: Any,
        app_progress: AppProgressResponse | None,
        model_workbench: Any,
    ) -> list[ExpertEvidenceLink]:
        links = [
            self._evidence(
                "product_navigation_state",
                "phase8_m5_product_navigation_state",
                "导航状态",
                "Navigation state contributes workspace availability only.",
                self._count_navigation_items(navigation_state),
                "read_only",
                "expert_diagnostics",
            ),
            self._evidence(
                "project_origin",
                f"project_origin:{summary.project_id or 'none'}",
                "项目来源",
                f"Origin type: {summary.origin_type or 'none'}.",
                summary.origin_type or "none",
                summary.origin_type or "none",
                "current_project",
            ),
            self._evidence(
                "model_settings",
                getattr(model_workbench, "active_selection_id", "") or "no_active_model_selection",
                "模型设置",
                "Model settings evidence is status only.",
                getattr(model_workbench, "current_provider", "") or "none",
                summary.model_status,
                "settings",
            ),
            self._file_evidence(STORY_SETUP_HANDOFFS_FILE, "story_setup_handoff", "故事设定交接", "story_setup"),
            self._multi_file_evidence(FINAL_PACKAGE_FILES, "final_story_package", "最终故事包", "final_outputs"),
            self._multi_file_evidence(PLUGIN_OUTPUT_FILES, "plugin_output", "插件输出", "plugin_outputs"),
        ]
        if app_progress is not None:
            links.append(
                self._evidence(
                    "app_progress",
                    app_progress.next_recommended_action or "no_next_action",
                    "AppProgress",
                    "AppProgress contributes stage and main-cast authority without mutation.",
                    str(len(app_progress.steps)),
                    "read_only",
                    summary.current_stage_id,
                )
            )
            if app_progress.main_cast.confirmed_character_count and not app_progress.main_cast.finished:
                links.append(
                    self._evidence(
                        "main_cast_authority",
                        "Decision:main_cast_required",
                        "主投角确认证据",
                        "Confirmed A-tier characters alone do not finish main cast.",
                        str(app_progress.main_cast.confirmed_character_count),
                        "decision_required",
                        "characters",
                    )
                )
        return [link for link in links if link is not None]

    def _safety_report(
        self,
        violations: list[str],
        warnings: list[str],
    ) -> ProductProgressSafetyReport:
        return ProductProgressSafetyReport(
            passed=len(violations) == 0,
            audit_view_only=True,
            progress_is_view_model_only=True,
            no_story_fact_write=True,
            no_decision_auto_creation=True,
            no_issue_auto_creation=True,
            no_debug_raw_payload_in_ordinary_mode=True,
            no_raw_prompt=True,
            no_raw_response=True,
            no_hidden_reasoning=True,
            no_api_key=True,
            no_authorization_header=True,
            no_full_story_prose=True,
            no_full_screenplay_text=True,
            no_final_package_full_content=True,
            no_plugin_output_full_content=True,
            no_debug_mutation=True,
            violations=violations,
            warnings=list(dict.fromkeys(warnings)),
            safe_summary="Progress safety report is audit-only and created without story mutation.",
            created_at=utc_now(),
        )

    def _action(
        self,
        action_id: str,
        title: str,
        reason: str,
        workspace_id: str,
        blocked: bool = False,
        blocked_reason: str = "",
        required_confirmation: bool = False,
        priority: int = 50,
    ) -> NextRecommendedAction:
        return NextRecommendedAction(
            action_id=action_id,
            action_kind="navigate",
            title=title,
            reason=reason,
            target_workspace_id=workspace_id,
            target_route_path=self._route_for_workspace(workspace_id),
            blocked=blocked,
            blocked_reason=blocked_reason,
            required_confirmation=required_confirmation,
            priority=priority,
            source_authority_refs=["phase8_m6_product_progress", "app_progress_read_only"],
            safe_summary="Next action is navigation only and does not execute work.",
        )

    def _decision_surface(
        self,
        decision_kind: str,
        title: str,
        reason: str,
        workspace_id: str,
        existing_ref: str,
    ) -> UserDecisionSurface:
        return UserDecisionSurface(
            decision_surface_id=f"decision_surface_{decision_kind}",
            decision_kind=decision_kind,
            title=title,
            reason=reason,
            target_workspace_id=workspace_id,
            target_route_path=self._route_for_workspace(workspace_id),
            existing_decision_ref=existing_ref or "",
            required_confirmation=True,
            does_not_create_decision=True,
            safe_summary="Decision surface only points to the workspace where user confirmation can happen.",
            source_authority_refs=["phase8_m6_product_progress", "app_progress_read_only"],
        )

    def _blocking_issue(
        self,
        issue_kind: str,
        title: str,
        reason: str,
        workspace_id: str,
        severity: str,
    ) -> BlockingIssueSurface:
        return BlockingIssueSurface(
            blocking_issue_surface_id=f"blocking_issue_{issue_kind}",
            issue_kind=issue_kind,
            title=title,
            reason=reason,
            severity=severity,
            target_workspace_id=workspace_id,
            target_route_path=self._route_for_workspace(workspace_id),
            source_authority_refs=["phase8_m6_product_progress", "app_progress_read_only"],
            does_not_create_or_resolve_issue=True,
            safe_summary="Blocking issue surface is read-only and cannot resolve issues.",
        )

    def _evidence(
        self,
        source_kind: str,
        source_ref: str,
        label: str,
        safe_summary: str,
        hash_or_count: str,
        status: str,
        workspace_id: str,
    ) -> ExpertEvidenceLink:
        return ExpertEvidenceLink(
            evidence_link_id=f"evidence_{self._safe_id(source_kind)}_{self._short_hash(source_ref)}",
            source_kind=source_kind,
            source_ref=source_ref,
            source_label=label,
            safe_summary=safe_summary,
            hash_or_count=hash_or_count,
            status=status,
            target_workspace_id=workspace_id,
            safe_reference_only=True,
            raw_payload_included=False,
        )

    def _file_evidence(
        self,
        file_name: str,
        source_kind: str,
        label: str,
        workspace_id: str,
    ) -> ExpertEvidenceLink:
        count = self._record_count(file_name)
        return self._evidence(
            source_kind,
            file_name,
            label,
            f"{label} evidence is represented by record count only.",
            f"count:{count}",
            "present" if count else "missing",
            workspace_id,
        )

    def _multi_file_evidence(
        self,
        file_names: tuple[str, ...],
        source_kind: str,
        label: str,
        workspace_id: str,
    ) -> ExpertEvidenceLink:
        counts = [self._record_count(file_name) for file_name in file_names]
        return self._evidence(
            source_kind,
            ",".join(file_names),
            label,
            f"{label} is summarized by counts only; content is not included.",
            f"count:{sum(counts)}",
            "present" if sum(counts) else "missing",
            workspace_id,
        )

    def _project_summary(self, project_id: Optional[str]) -> dict[str, Any]:
        if not project_id:
            return {}
        try:
            project_summary = self.project_creation_service.get_project(project_id)
            badge = self.product_navigation_service.state(project_id=project_id).origin_badge
        except Exception:
            return {}
        return {
            "project": project_summary.project,
            "origin": project_summary.origin,
            "badge": badge or {},
        }

    def _model_workbench(self) -> Any:
        try:
            return self.model_settings_service.workbench()
        except Exception:
            return None

    def _safe_app_progress(self) -> AppProgressResponse | None:
        try:
            return self.app_progress_service.get_progress()
        except Exception:
            return None

    def _can_use_active_app_progress(
        self,
        selected_project_id: Optional[str],
        active_project_id: Optional[str],
    ) -> bool:
        return bool(selected_project_id and active_project_id and selected_project_id == active_project_id)

    def _workspace_for_action(
        self,
        action_id: str,
        app_progress: AppProgressResponse | None,
    ) -> str:
        mapping = {
            "initialize_project": "create_project",
            "configure_active_model": "settings",
            "generate_world_canvas": "world_canvas",
            "confirm_world_canvas": "world_canvas",
            "generate_character": "characters",
            "finish_main_cast": "characters",
            "setup_framework": "framework",
            "confirm_framework_mapping": "framework",
            "build_current_chapter_framework": "framework",
            "generate_chapter_plan": "chapter_plan",
            "set_scene_count": "chapter_plan",
            "confirm_chapter_plan": "chapter_plan",
            "generate_first_scene": "chapter_scene",
            "review_quality": "chapter_scene",
            "review_scene_gate": "chapter_scene",
            "review_revision_candidate": "chapter_scene",
            "confirm_revision": "chapter_scene",
            "confirm_scene": "chapter_scene",
            "generate_next_scene": "chapter_scene",
            "preview_next_chapter": "chapter_scene",
            "prepare_next_chapter": "chapter_scene",
            "confirm_next_chapter": "chapter_scene",
            "review_provisional_archive": "chapter_scene",
            "preview_chapter_archive": "chapter_scene",
            "story_draft_complete": "final_outputs",
        }
        return mapping.get(action_id, "current_project")

    def _title_for_action(self, action_id: str) -> str:
        if action_id == "review_scene_gate":
            return "Scene draft status"
        titles = {
            "initialize_project": "初始化项目",
            "configure_active_model": "配置模型",
            "generate_world_canvas": "生成世界画布",
            "confirm_world_canvas": "确认世界画布",
            "generate_character": "创建角色",
            "finish_main_cast": "确认主投角",
            "setup_framework": "设置框架",
            "confirm_framework_mapping": "确认框架映射",
            "build_current_chapter_framework": "构建当前章节框架",
            "generate_chapter_plan": "生成章节计划",
            "set_scene_count": "设置场景数量",
            "confirm_chapter_plan": "确认章节计划",
            "generate_first_scene": "生成第一场",
            "review_quality": "查看质量阻断",
            "review_revision_candidate": "查看修订候选",
            "confirm_revision": "确认修订",
            "confirm_scene": "确认场景",
            "generate_next_scene": "生成下一场",
            "preview_next_chapter": "预览下一章",
            "prepare_next_chapter": "准备下一章",
            "confirm_next_chapter": "确认下一章",
            "story_draft_complete": "查看最终输出",
        }
        return titles.get(action_id, "查看当前项目")

    def _reason_for_action(
        self,
        action_id: str,
        app_progress: AppProgressResponse,
    ) -> str:
        if action_id == "review_scene_gate":
            return "Current scene draft must pass the unified backend checks or receive user action before continuing."
        if action_id == "finish_main_cast":
            return "主投角需要 confirmed A-tier 角色和 main_cast Decision，两者缺一不可。"
        if action_id == "review_quality":
            return "当前场景存在质量或连续性阻断，需要先查看问题。"
        if action_id.startswith("confirm"):
            return "该阶段需要用户确认；进度卡只负责导航，不会代替确认。"
        return "根据当前 AppProgress，只导航到对应工作区。"

    def _ordinary_summary_for_action(self, action_id: str) -> str:
        if action_id == "review_scene_gate":
            return "Current scene draft needs backend checking or user action before continuing."
        if action_id == "finish_main_cast":
            return "角色已经存在，但主投角仍需要明确确认。"
        if action_id == "review_quality":
            return "当前场景还有阻断问题，需要先处理质量检查。"
        if action_id in {"confirm_scene", "confirm_revision", "confirm_world_canvas", "confirm_chapter_plan"}:
            return "当前阶段等待用户确认。"
        return f"下一步建议：{self._title_for_action(action_id)}。"

    def _requires_confirmation(self, action_id: str) -> bool:
        return action_id.startswith("confirm") or action_id in {
            "finish_main_cast",
            "review_revision_candidate",
        }

    def _stage_label(self, stage_id: str, action_id: str) -> str:
        labels = {
            "create_project": "项目入口",
            "settings": "模型设置",
            "story_setup": "故事设定",
            "world_canvas": "世界画布",
            "characters": "角色",
            "framework": "框架",
            "chapter_plan": "章节计划",
            "chapter_scene": "场景写作",
            "final_outputs": "最终输出",
            "current_project": "当前项目",
        }
        return labels.get(stage_id, self._title_for_action(action_id))

    def _route_for_workspace(self, workspace_id: str) -> str:
        return f"/workspaces/{workspace_id}"

    def _count_navigation_items(self, navigation_state: Any) -> str:
        return f"workspaces:{len(getattr(navigation_state, 'workspaces', []) or [])}"

    def _has_any_records(self, file_names: tuple[str, ...]) -> bool:
        return any(self._record_count(file_name) > 0 for file_name in file_names)

    def _has_project_setup_records(
        self,
        project_id: Optional[str],
        origin_type: str,
    ) -> bool:
        if not project_id:
            return False
        if origin_type == "prompt_first":
            file_names = (
                STORY_SETUP_HANDOFFS_FILE,
                STORY_SETUP_DECISIONS_FILE,
                STORY_SETUP_DRAFT_BUNDLES_FILE,
            )
        elif origin_type == "template":
            file_names = (
                TEMPLATE_INSTANTIATION_REPORTS_FILE,
                STORY_SETUP_HANDOFFS_FILE,
                STORY_SETUP_DRAFT_BUNDLES_FILE,
            )
        else:
            return False
        return any(
            self._project_record_count(file_name, project_id) > 0
            for file_name in file_names
        )

    def _app_progress_has_story_data(self, app_progress: AppProgressResponse) -> bool:
        story_progress_status = str(
            app_progress.story_progress.story_progress_status or ""
        ).strip()
        story_progress_action = str(
            app_progress.story_progress.next_recommended_action
            or app_progress.next_recommended_action
            or ""
        ).strip()
        return any(
            [
                app_progress.world_canvas.exists,
                app_progress.main_cast.confirmed_character_count > 0,
                app_progress.main_cast.finished,
                app_progress.framework.package_exists,
                app_progress.framework.mapping_exists,
                app_progress.chapter_plan.exists,
                app_progress.chapter_plan.chapter_plan_decision_exists,
                app_progress.scene.current_scene_exists,
                story_progress_status == "story_draft_complete",
                story_progress_action
                in {
                    "preview_next_chapter",
                    "prepare_next_chapter",
                    "confirm_next_chapter",
                    "story_draft_complete",
                },
            ]
        )

    def _record_count(self, file_name: str) -> int:
        path = self.data_dir / file_name
        if not self.store.exists(path):
            return 0
        try:
            return _safe_count(self.store.read_any(path))
        except StorageError:
            return 0

    def _project_record_count(self, file_name: str, project_id: str) -> int:
        path = self.data_dir / file_name
        if not self.store.exists(path):
            return 0
        try:
            payload = self.store.read_any(path)
        except StorageError:
            return 0
        return len(
            [
                record
                for record in self._iter_record_dicts(payload)
                if str(record.get("project_id") or "") == project_id
            ]
        )

    def _iter_record_dicts(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            records: list[dict[str, Any]] = []
            if "project_id" in payload:
                records.append(payload)
            for value in payload.values():
                if isinstance(value, list):
                    records.extend(item for item in value if isinstance(item, dict))
                elif isinstance(value, dict) and "project_id" in value:
                    records.append(value)
            return records
        return []

    def _safe_id(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")
        return cleaned[:48] or "item"

    def _short_hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]

    def _guard_safe_payload(self, payload: Any, label: str) -> None:
        issues = self._unsafe_payload_issues(payload, label)
        if issues:
            raise ProductProgressSafetyError(f"{label}_unsafe_payload:{issues[0]}")

    def _unsafe_payload_issues(self, payload: Any, label: str) -> list[str]:
        values = self._string_values(payload)
        text = "\n".join(values)
        lowered = text.lower()
        issues = [marker for marker in UNSAFE_VALUE_MARKERS if marker in lowered]
        if SECRET_LIKE_RE.search(text):
            issues.append("secret_like_value")
        return [f"{label}:{issue}" for issue in list(dict.fromkeys(issues))]

    def _string_values(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            values: list[str] = []
            for item in value:
                values.extend(self._string_values(item))
            return values
        if isinstance(value, dict):
            values: list[str] = []
            for child in value.values():
                values.extend(self._string_values(child))
            return values
        if isinstance(value, BaseModel):
            return self._string_values(model_to_dict(value))
        return []
