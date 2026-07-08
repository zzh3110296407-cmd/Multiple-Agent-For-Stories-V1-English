import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.decision import Decision
from app.backend.models.framework_package import (
    ChapterMacroAssignment,
    FrameworkMappingIssue,
    FrameworkPackage,
    MacroComponent,
)
from app.backend.models.imported_framework_workbench import (
    ImportedFrameworkActionRequest,
    ImportedFrameworkActivationPlan,
    ImportedFrameworkDecision,
    ImportedFrameworkDecisionResult,
    ImportedFrameworkEditPatch,
    ImportedFrameworkEditSession,
    ImportedFrameworkImpactSummary,
    ImportedFrameworkListResponse,
    ImportedFrameworkPlanResult,
    ImportedFrameworkSessionResult,
    ImportedFrameworkSourceRef,
    ImportedFrameworkSummary,
    ImportedFrameworkValidationIssue,
    ImportedFrameworkValidationReport,
    ImportedFrameworkWorkbenchState,
)
from app.backend.services.analysis_report_viewer_service import AnalysisReportViewerService
from app.backend.services.framework_package_candidate_service import (
    FrameworkPackageCandidateService,
)
from app.backend.services.framework_package_service import FrameworkPackageService
from app.backend.storage.json_store import JsonStore, StorageError


STATES_FILE = "imported_framework_workbench_states.json"
SESSIONS_FILE = "imported_framework_edit_sessions.json"
PATCHES_FILE = "imported_framework_edit_patches.json"
PLANS_FILE = "imported_framework_activation_plans.json"
DECISIONS_FILE = "imported_framework_decisions.json"
GLOBAL_DECISIONS_FILE = "decisions.json"
SCHEMA_VERSION = "phase5_m4_imported_framework_workbench_v1"
LOCAL_PROJECT_ID = "local_project"
IMPORT_TARGET_TYPE = "analyze_stories_framework_import"
FRAMEWORK_MAPPING_TARGET_TYPE = "framework_macro_mapping"
UNTOUCHED_FORMAL_FILES = [
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "chapter_archives.json",
    "narrative_debts.json",
    "continuity_issues.json",
    "thinking_candidates.json",
    "pre_modify_candidates.json",
    "scene_candidate_cache.json",
    "cached_scene_candidates.json",
    "chapter_framework_build_contexts.json",
    "chapter_framework_build_reasons.json",
]
UNSAFE_NORMALIZED_KEYS = {
    "apikey",
    "authorization",
    "bearer",
    "rawprompt",
    "rawmodelprompt",
    "rawresponse",
    "rawmodelresponse",
    "hiddenreasoning",
    "internalreasoning",
    "chainofthought",
    "providersecret",
    "langsmithapikey",
    "secretkey",
    "fullprose",
    "prosetext",
    "revisedprosetext",
    "storytext",
    "chaptertext",
    "fullstorytext",
    "completestorytext",
}
UNSAFE_VALUE_MARKERS = [
    "RAW_PROMPT",
    "RAW_RESPONSE",
    "HIDDEN_REASONING",
    "INTERNAL_REASONING",
    "CHAIN_OF_THOUGHT",
    "chain-of-thought",
    "raw prompt",
    "raw response",
    "hidden reasoning",
    "internal reasoning",
]
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE),
]


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImportedFrameworkWorkbenchService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        framework_candidate_service: FrameworkPackageCandidateService | None = None,
        analysis_report_viewer_service: AnalysisReportViewerService | None = None,
        framework_package_service: FrameworkPackageService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.framework_candidate_service = framework_candidate_service or FrameworkPackageCandidateService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.analysis_report_viewer_service = analysis_report_viewer_service or AnalysisReportViewerService(
            store=self.store,
            data_dir=self.data_dir,
            framework_candidate_service=self.framework_candidate_service,
        )
        self.framework_package_service = framework_package_service or FrameworkPackageService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.states_file = self.data_dir / STATES_FILE
        self.sessions_file = self.data_dir / SESSIONS_FILE
        self.patches_file = self.data_dir / PATCHES_FILE
        self.plans_file = self.data_dir / PLANS_FILE
        self.decisions_file = self.data_dir / DECISIONS_FILE
        self.global_decisions_file = self.data_dir / GLOBAL_DECISIONS_FILE
        self.framework_package_file = self.data_dir / "framework_package.json"

    def get_imported_workbench_state(self, candidate_id: str) -> ImportedFrameworkWorkbenchState:
        candidate = self.framework_candidate_service.get_candidate(candidate_id)
        sessions = [
            session
            for session in self._read_sessions()
            if session.candidate_id == candidate_id
        ]
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        latest_session_id = sessions[0].edit_session_id if sessions else None
        source_refs = self._source_refs(candidate)
        warnings: list[ImportedFrameworkValidationIssue] = []
        blocking: list[ImportedFrameworkValidationIssue] = []
        if not candidate.can_proceed_to_m4_workbench:
            blocking.append(
                self._issue(
                    "candidate_not_ready_for_m4",
                    "blocking",
                    "Framework candidate is not ready for imported framework workbench review.",
                    "candidate.can_proceed_to_m4_workbench",
                )
            )
        state = ImportedFrameworkWorkbenchState(
            candidate_id=candidate_id,
            candidate_status=candidate.candidate_status,
            can_start_edit_session=candidate.can_proceed_to_m4_workbench,
            latest_edit_session_id=latest_session_id,
            candidate_summary=self._summary_from_package_dict(
                self._candidate_working_package(candidate),
                prefix=f"Candidate {candidate_id}",
            ),
            current_framework_summary=self._current_framework_summary(),
            source_refs=source_refs,
            viewer_state_ids=[
                ref.source_id
                for ref in source_refs
                if ref.source_type == "analysis_report_viewer"
            ],
            sessions=sessions,
            warnings=warnings,
            blocking_issues=blocking,
        )
        self._replace_or_append(self.states_file, "candidate_id", candidate_id, model_to_dict(state))
        return state

    def start_edit_session(self, candidate_id: str) -> ImportedFrameworkSessionResult:
        candidate = self.framework_candidate_service.get_candidate(candidate_id)
        if not candidate.can_proceed_to_m4_workbench:
            raise StorageError(
                f"IMPORTED_FRAMEWORK_CANDIDATE_NOT_READY: {candidate_id}"
            )
        working_package = self._candidate_working_package(candidate)
        self._guard_safe_payload(working_package)
        source_refs = self._source_refs(candidate)
        story_analysis_report_ref_ids = [
            ref.source_id
            for ref in source_refs
            if ref.source_type == "story_analysis_report"
        ]
        viewer_state_ids = [
            ref.source_id
            for ref in source_refs
            if ref.source_type == "analysis_report_viewer"
        ]
        timestamp = now_iso()
        edit_session = ImportedFrameworkEditSession(
            edit_session_id=self._next_id(self.sessions_file, "edit_session_id", "imported_fw_session"),
            candidate_id=candidate.candidate_id,
            import_id=candidate.import_id,
            artifact_id=candidate.artifact_id,
            normalization_report_id=candidate.normalization_report_id,
            source_ref_id=candidate.source_ref.source_ref_id if candidate.source_ref else "",
            story_analysis_report_ref_ids=story_analysis_report_ref_ids,
            viewer_state_ids=viewer_state_ids,
            session_status="draft",
            working_framework_package=working_package,
            original_candidate_summary=self._summary_from_package_dict(
                working_package,
                prefix=f"Candidate {candidate.candidate_id}",
            ),
            source_refs=source_refs,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        validation_report = self._validate_session(edit_session)
        self._attach_validation_report(edit_session, validation_report)
        edit_session.warning_count = len(validation_report.warnings)
        edit_session.blocking_issue_count = len(validation_report.blocking_issues)
        self._replace_or_append(
            self.sessions_file,
            "edit_session_id",
            edit_session.edit_session_id,
            model_to_dict(edit_session),
        )
        return ImportedFrameworkSessionResult(
            success=True,
            edit_session=edit_session,
            validation_report=validation_report,
            patches=[],
        )

    def list_edit_sessions(self) -> ImportedFrameworkListResponse:
        sessions = self._read_sessions()
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return ImportedFrameworkListResponse(edit_sessions=sessions)

    def get_edit_session(self, edit_session_id: str) -> ImportedFrameworkSessionResult:
        session = self._get_session(edit_session_id)
        patches = [
            patch for patch in self._read_patches() if patch.edit_session_id == edit_session_id
        ]
        patches.sort(key=lambda item: item.created_at)
        plan = None
        if session.latest_activation_plan_id:
            plan = self._get_plan(session.latest_activation_plan_id)
        return ImportedFrameworkSessionResult(
            success=True,
            edit_session=session,
            validation_report=session.latest_validation_report,
            activation_plan=plan,
            patches=patches,
        )

    def apply_patch(
        self,
        edit_session_id: str,
        request: ImportedFrameworkActionRequest,
    ) -> ImportedFrameworkSessionResult:
        session = self._get_session(edit_session_id)
        if session.session_status in {"confirmed", "rejected"}:
            raise StorageError(
                f"IMPORTED_FRAMEWORK_SESSION_CLOSED: {edit_session_id}"
            )
        operation = request.operation
        if operation is None:
            raise StorageError("IMPORTED_FRAMEWORK_PATCH_OPERATION_REQUIRED")
        before_summary = self._summary_text(session.working_framework_package)
        working = copy.deepcopy(session.working_framework_package)
        self._guard_safe_payload(request.user_input)

        if operation == "set_activation_mode":
            if request.activation_mode is None:
                raise StorageError("IMPORTED_FRAMEWORK_ACTIVATION_MODE_REQUIRED")
            session.activation_mode = request.activation_mode
        elif operation == "update_macro_component":
            self._update_macro_component(working, request)
        elif operation == "delete_macro_component":
            self._mark_macro_component_deleted(working, request.component_id, True)
        elif operation == "restore_macro_component":
            self._mark_macro_component_deleted(working, request.component_id, False)
        elif operation == "reorder_macro_components":
            self._reorder_macro_components(working, request)
        elif operation == "remap_chapter":
            self._remap_chapter(working, request)
        elif operation == "update_chapter_count":
            self._update_chapter_count(working, request.chapter_count)
        else:
            raise StorageError(f"IMPORTED_FRAMEWORK_PATCH_UNKNOWN_OPERATION: {operation}")

        self._guard_safe_payload(working)
        session.working_framework_package = working
        session.session_status = "draft"
        session.updated_at = now_iso()
        validation_report = self._validate_session(session)
        self._attach_validation_report(session, validation_report)
        session.warning_count = len(validation_report.warnings)
        session.blocking_issue_count = len(validation_report.blocking_issues)
        patch = ImportedFrameworkEditPatch(
            patch_id=self._next_id(self.patches_file, "patch_id", "imported_fw_patch"),
            edit_session_id=edit_session_id,
            candidate_id=session.candidate_id,
            operation=operation,
            field_path=self._patch_field_path(operation, request),
            component_id=request.component_id,
            chapter_index=request.chapter_index,
            before_summary=before_summary,
            after_summary=self._summary_text(session.working_framework_package),
            user_input=self._safe_user_input(request.user_input),
            created_at=session.updated_at,
            version_id=SCHEMA_VERSION,
        )
        self._replace_or_append(self.patches_file, "patch_id", patch.patch_id, model_to_dict(patch))
        session.patch_ids.append(patch.patch_id)
        self._replace_or_append(
            self.sessions_file,
            "edit_session_id",
            edit_session_id,
            model_to_dict(session),
        )
        return ImportedFrameworkSessionResult(
            success=True,
            edit_session=session,
            validation_report=validation_report,
            patches=[patch],
        )

    def validate_edit_session(self, edit_session_id: str) -> ImportedFrameworkSessionResult:
        session = self._get_session(edit_session_id)
        validation_report = self._validate_session(session)
        self._attach_validation_report(session, validation_report)
        session.session_status = "validated" if validation_report.passed else "blocked"
        session.warning_count = len(validation_report.warnings)
        session.blocking_issue_count = len(validation_report.blocking_issues)
        session.updated_at = now_iso()
        self._replace_or_append(
            self.sessions_file,
            "edit_session_id",
            edit_session_id,
            model_to_dict(session),
        )
        return ImportedFrameworkSessionResult(
            success=validation_report.passed,
            edit_session=session,
            validation_report=validation_report,
        )

    def build_activation_plan(
        self,
        edit_session_id: str,
        activation_mode: str | None = None,
    ) -> ImportedFrameworkPlanResult:
        session = self._get_session(edit_session_id)
        if session.session_status in {"confirmed", "rejected"}:
            raise StorageError(
                f"IMPORTED_FRAMEWORK_SESSION_CLOSED: {edit_session_id}"
            )
        if activation_mode:
            if activation_mode not in {"reference_only", "merge", "set_active"}:
                raise StorageError(
                    f"IMPORTED_FRAMEWORK_INVALID_ACTIVATION_MODE: {activation_mode}"
                )
            session.activation_mode = activation_mode  # type: ignore[assignment]
        if session.activation_mode is None:
            raise StorageError("IMPORTED_FRAMEWORK_ACTIVATION_MODE_REQUIRED")
        validation_report = self._validate_session(session)
        plan_status = "draft"
        if session.activation_mode == "set_active":
            validation_report.blocking_issues.append(
                self._issue(
                    "set_active_not_ready",
                    "blocking",
                    "M4 blocks set_active until a later active framework pointer migration exists.",
                    "activation_mode",
                )
            )
            validation_report.passed = False
            validation_report.safe_summary = self._validation_summary(validation_report)
            plan_status = "blocked"
        elif validation_report.blocking_issues:
            plan_status = "blocked"
        impact = self._build_impact_summary(session, validation_report)
        plan = ImportedFrameworkActivationPlan(
            plan_id=self._next_id(self.plans_file, "plan_id", "imported_fw_plan"),
            edit_session_id=session.edit_session_id,
            candidate_id=session.candidate_id,
            activation_mode=session.activation_mode,
            plan_status=plan_status,  # type: ignore[arg-type]
            validation_report=validation_report,
            impact_summary=impact,
            accept_warnings_required=validation_report.requires_user_confirmation,
            warning_count=len(validation_report.warnings),
            blocking_issue_count=len(validation_report.blocking_issues),
            created_at=now_iso(),
            updated_at=now_iso(),
            version_id=SCHEMA_VERSION,
        )
        self._attach_validation_report(session, validation_report)
        session.latest_activation_plan_id = plan.plan_id
        session.session_status = "plan_ready" if plan_status == "draft" else "blocked"
        session.warning_count = plan.warning_count
        session.blocking_issue_count = plan.blocking_issue_count
        session.updated_at = now_iso()
        self._replace_or_append(self.plans_file, "plan_id", plan.plan_id, model_to_dict(plan))
        self._replace_or_append(
            self.sessions_file,
            "edit_session_id",
            session.edit_session_id,
            model_to_dict(session),
        )
        return ImportedFrameworkPlanResult(
            success=plan.plan_status == "draft",
            activation_plan=plan,
            edit_session=session,
        )

    def confirm_activation_plan(
        self,
        plan_id: str,
        request: ImportedFrameworkActionRequest | None = None,
    ) -> ImportedFrameworkDecisionResult:
        request = request or ImportedFrameworkActionRequest()
        self._guard_safe_payload(request.user_input)
        plan = self._get_plan(plan_id)
        session = self._get_session(plan.edit_session_id)
        if plan.plan_status != "draft":
            raise StorageError(
                f"IMPORTED_FRAMEWORK_PLAN_NOT_CONFIRMABLE: {plan_id}"
            )
        validation_report = self._validate_session(session)
        if validation_report.blocking_issues:
            raise StorageError(
                "IMPORTED_FRAMEWORK_CONFIRM_BLOCKED: validation has blocking issues."
            )
        if validation_report.requires_user_confirmation and not request.accept_warnings:
            raise StorageError(
                "IMPORTED_FRAMEWORK_CONFIRM_REQUIRES_WARNING_ACCEPTANCE"
            )

        decision = self._append_import_decision(
            decision_type=f"confirm_{plan.activation_mode}",
            target_id=session.candidate_id,
            edit_session_id=session.edit_session_id,
            plan_id=plan.plan_id,
            activation_mode=plan.activation_mode,
            user_input=request.user_input,
            safe_summary=plan.impact_summary.safe_summary,
        )
        if plan.activation_mode == "merge":
            merged_package = self._merge_into_active_framework(session)
            self._write_framework_package(merged_package)
            self._append_global_decision(
                decision_type="confirm",
                target_type=FRAMEWORK_MAPPING_TARGET_TYPE,
                target_id=merged_package.framework_package_id,
                user_input=(
                    request.user_input.strip()
                    or f"User merged Analyze Stories framework candidate {session.candidate_id}."
                ),
            )
        elif plan.activation_mode == "reference_only":
            pass
        else:
            raise StorageError("IMPORTED_FRAMEWORK_SET_ACTIVE_NOT_READY")

        plan.plan_status = "confirmed"
        plan.validation_report = validation_report
        plan.updated_at = now_iso()
        session.session_status = "confirmed"
        self._attach_validation_report(session, validation_report)
        session.warning_count = len(validation_report.warnings)
        session.blocking_issue_count = 0
        session.updated_at = now_iso()
        self._replace_or_append(self.plans_file, "plan_id", plan.plan_id, model_to_dict(plan))
        self._replace_or_append(
            self.sessions_file,
            "edit_session_id",
            session.edit_session_id,
            model_to_dict(session),
        )
        return ImportedFrameworkDecisionResult(
            success=True,
            decision=decision,
            edit_session=session,
            activation_plan=plan,
        )

    def reject_edit_session(
        self,
        edit_session_id: str,
        request: ImportedFrameworkActionRequest | None = None,
    ) -> ImportedFrameworkDecisionResult:
        request = request or ImportedFrameworkActionRequest()
        self._guard_safe_payload(request.user_input)
        session = self._get_session(edit_session_id)
        if session.session_status == "confirmed":
            raise StorageError(f"IMPORTED_FRAMEWORK_SESSION_ALREADY_CONFIRMED: {edit_session_id}")
        plan = self._get_plan(session.latest_activation_plan_id) if session.latest_activation_plan_id else None
        if plan and plan.plan_status == "draft":
            plan.plan_status = "rejected"
            plan.updated_at = now_iso()
            self._replace_or_append(self.plans_file, "plan_id", plan.plan_id, model_to_dict(plan))
        session.session_status = "rejected"
        session.updated_at = now_iso()
        self._replace_or_append(
            self.sessions_file,
            "edit_session_id",
            edit_session_id,
            model_to_dict(session),
        )
        decision = self._append_import_decision(
            decision_type="reject",
            target_id=session.candidate_id,
            edit_session_id=edit_session_id,
            plan_id=plan.plan_id if plan else None,
            activation_mode=session.activation_mode,
            user_input=request.user_input,
            safe_summary=f"User rejected imported framework edit session {edit_session_id}.",
        )
        return ImportedFrameworkDecisionResult(
            success=True,
            decision=decision,
            edit_session=session,
            activation_plan=plan,
        )

    def _candidate_working_package(self, candidate: Any) -> dict[str, Any]:
        normalized = copy.deepcopy(candidate.normalized_framework_package or {})
        if not normalized:
            return {}
        macro_framework = normalized.get("macro_framework")
        if not isinstance(macro_framework, dict):
            macro_framework = {}
        package = {
            "framework_package_id": (
                self._first_str(macro_framework.get("framework_id"))
                or f"imported_{candidate.candidate_id}"
            ),
            "project_id": LOCAL_PROJECT_ID,
            "source": "analyze_stories",
            "language": self._first_str(normalized.get("language")) or "zh",
            "constraint_strength": self._first_str(
                macro_framework.get("constraint_strength"),
                normalized.get("constraint_strength"),
            )
            or "weak",
            "maturity": "Imported Candidate",
            "macro_framework": {
                "components": copy.deepcopy(macro_framework.get("components") or []),
            },
            "component_vocabulary": copy.deepcopy(
                normalized.get("component_vocabulary") or {}
            ),
            "chapter_macro_assignments": copy.deepcopy(
                normalized.get("chapter_macro_assignments") or []
            ),
            "built_chapter_frameworks": [],
            "version_id": SCHEMA_VERSION,
        }
        for component in package["macro_framework"]["components"]:
            if isinstance(component, dict):
                component.setdefault("source", "analyze_stories")
                component.setdefault("scope", "macro")
                component.setdefault("deleted", False)
        for assignment in package["chapter_macro_assignments"]:
            if isinstance(assignment, dict):
                assignment.setdefault("assignment_type", "analyze_stories_recommended")
                assignment.setdefault("status", "draft")
                assignment.setdefault("reason", "Imported Analyze Stories recommendation.")
        return package

    def _validate_session(
        self,
        session: ImportedFrameworkEditSession,
    ) -> ImportedFrameworkValidationReport:
        issues: list[ImportedFrameworkValidationIssue] = []
        warnings: list[ImportedFrameworkValidationIssue] = []
        package_dict = copy.deepcopy(session.working_framework_package)
        try:
            self._guard_safe_payload(package_dict)
        except StorageError as exc:
            issues.append(
                self._issue(
                    "unsafe_payload_blocked",
                    "blocking",
                    "Imported framework working copy contains unsafe raw or secret-like data.",
                    "$",
                    str(exc),
                )
            )
        components = self._macro_components(package_dict)
        component_ids: set[str] = set()
        deleted_ids: set[str] = set()
        orders: dict[int, str] = {}
        for index, component in enumerate(components):
            component_id = self._first_str(component.get("component_id"))
            label = self._first_str(component.get("label"))
            instruction = self._first_str(component.get("instruction"))
            order = self._safe_int(component.get("order"))
            if not component_id:
                issues.append(self._issue("macro_component_id_missing", "blocking", "Macro component id is required.", f"macro_framework.components[{index}].component_id"))
                continue
            if component_id in component_ids:
                issues.append(self._issue("macro_component_id_duplicate", "blocking", "Macro component ids must be unique.", f"macro_framework.components[{index}].component_id", component_id))
            component_ids.add(component_id)
            if component.get("deleted") is True:
                deleted_ids.add(component_id)
            if not label:
                issues.append(self._issue("macro_component_label_missing", "blocking", "Macro component label is required.", f"macro_framework.components[{index}].label", component_id))
            if not instruction:
                warnings.append(self._issue("macro_component_instruction_missing", "warning", "Macro component instruction is empty.", f"macro_framework.components[{index}].instruction", component_id))
            if order is None:
                issues.append(self._issue("macro_component_order_missing", "blocking", "Macro component order is required.", f"macro_framework.components[{index}].order", component_id))
            elif order in orders:
                warnings.append(self._issue("macro_component_order_duplicate", "warning", "Macro component order is duplicated.", f"macro_framework.components[{index}].order", component_id))
            else:
                orders[order] = component_id

        assignments = self._chapter_assignments(package_dict)
        if not assignments:
            issues.append(self._issue("chapter_assignments_missing", "blocking", "At least one chapter macro assignment is required.", "chapter_macro_assignments"))
        for index, assignment in enumerate(assignments):
            chapter_index = self._safe_int(assignment.get("chapter_index"))
            linked_ids = [
                str(component_id).strip()
                for component_id in assignment.get("linked_macro_component_ids", [])
                if str(component_id).strip()
            ] if isinstance(assignment.get("linked_macro_component_ids"), list) else []
            if chapter_index is None or chapter_index <= 0:
                issues.append(self._issue("chapter_index_invalid", "blocking", "Chapter assignment index must be positive.", f"chapter_macro_assignments[{index}].chapter_index"))
            if not linked_ids:
                issues.append(self._issue("chapter_mapping_empty", "blocking", "Chapter assignment must link at least one macro component.", f"chapter_macro_assignments[{index}].linked_macro_component_ids"))
            for component_id in linked_ids:
                if component_id not in component_ids:
                    issues.append(self._issue("unknown_macro_component", "blocking", "Chapter assignment references an unknown macro component.", f"chapter_macro_assignments[{index}].linked_macro_component_ids", component_id))
                if component_id in deleted_ids:
                    issues.append(self._issue("deleted_macro_component_referenced", "blocking", "Chapter assignment references a deleted macro component.", f"chapter_macro_assignments[{index}].linked_macro_component_ids", component_id))

        active_package = self._read_active_framework_package(optional=True)
        if session.activation_mode == "merge" and active_package is None:
            issues.append(
                self._issue(
                    "active_framework_package_missing",
                    "blocking",
                    "Merge requires an existing active framework package.",
                    "framework_package.json",
                )
            )
        package_for_mapping = self._package_for_validation(package_dict, active_package)
        if package_for_mapping is not None:
            mapping_report = self.framework_package_service.validate_workbench_mapping(
                package=package_for_mapping,
            )
            issues.extend(
                self._from_mapping_issue(item, "blocking")
                for item in mapping_report.blocking_issues
            )
            warnings.extend(
                self._from_mapping_issue(item, "warning")
                for item in mapping_report.warnings
            )
        if session.activation_mode == "merge" and active_package and active_package.built_chapter_frameworks:
            warnings.append(
                self._issue(
                    "built_chapter_frameworks_may_be_stale",
                    "warning",
                    "Existing built chapter frameworks are preserved and may need later rebuild review.",
                    "built_chapter_frameworks",
                    f"count={len(active_package.built_chapter_frameworks)}",
                )
            )
        if session.activation_mode is None:
            warnings.append(
                self._issue(
                    "activation_mode_not_selected",
                    "warning",
                    "Choose reference_only, merge, or set_active before confirming.",
                    "activation_mode",
                )
            )
        issues = self._dedupe_issues(issues)
        warnings = self._dedupe_issues(warnings)
        report = ImportedFrameworkValidationReport(
            passed=not issues,
            warnings=warnings,
            blocking_issues=issues,
            requires_user_confirmation=bool(warnings),
            safe_summary="",
        )
        report.safe_summary = self._validation_summary(report)
        return report

    def _build_impact_summary(
        self,
        session: ImportedFrameworkEditSession,
        validation_report: ImportedFrameworkValidationReport,
    ) -> ImportedFrameworkImpactSummary:
        active_package = self._read_active_framework_package(optional=True)
        stale_warning_count = 0
        for warning in validation_report.warnings:
            if warning.code in {
                "built_chapter_frameworks_may_be_stale",
                "built_chapter_mapping_changed",
            }:
                stale_warning_count += 1
        warnings = [warning.message for warning in validation_report.warnings]
        mode = session.activation_mode or "reference_only"
        return ImportedFrameworkImpactSummary(
            activation_mode=mode,  # type: ignore[arg-type]
            current_framework_package_id=active_package.framework_package_id if active_package else "",
            imported_candidate_id=session.candidate_id,
            will_write_framework_package=mode == "merge" and validation_report.passed,
            will_write_import_decision=True,
            will_write_framework_macro_mapping_decision=mode == "merge" and validation_report.passed,
            will_rebuild_built_chapter_frameworks=False,
            built_chapter_frameworks_stale_warning_count=stale_warning_count,
            untouched_files=UNTOUCHED_FORMAL_FILES,
            warnings=warnings,
            safe_summary=(
                f"Activation mode {mode}: "
                f"framework_package_write={mode == 'merge' and validation_report.passed}; "
                "built_chapter_framework_rebuild=false; formal story data untouched."
            ),
        )

    def _merge_into_active_framework(
        self,
        session: ImportedFrameworkEditSession,
    ) -> FrameworkPackage:
        current = self._read_active_framework_package(optional=False)
        imported = self._package_for_validation(session.working_framework_package, current)
        if imported is None:
            raise StorageError("IMPORTED_FRAMEWORK_PACKAGE_INVALID")
        current.source = "analyze_stories"
        current.constraint_strength = imported.constraint_strength
        current.maturity = "Imported Candidate"
        current.macro_framework = imported.macro_framework
        current.component_vocabulary = imported.component_vocabulary
        current.chapter_macro_assignments = [
            ChapterMacroAssignment(
                chapter_index=assignment.chapter_index,
                linked_macro_component_ids=list(assignment.linked_macro_component_ids),
                assignment_type="analyze_stories_recommended",
                status="confirmed",
                reason=assignment.reason or f"Merged from {session.candidate_id}.",
            )
            for assignment in imported.chapter_macro_assignments
        ]
        current.version_id = SCHEMA_VERSION
        return current

    def _package_for_validation(
        self,
        package_dict: dict[str, Any],
        active_package: FrameworkPackage | None,
    ) -> FrameworkPackage | None:
        candidate_dict = copy.deepcopy(package_dict)
        candidate_dict["macro_framework"]["components"] = [
            component
            for component in self._macro_components(candidate_dict)
            if component.get("deleted") is not True
        ]
        if active_package is not None:
            candidate_dict["built_chapter_frameworks"] = [
                model_to_dict(item) for item in active_package.built_chapter_frameworks
            ]
            candidate_dict["framework_package_id"] = active_package.framework_package_id
        else:
            candidate_dict["built_chapter_frameworks"] = []
        try:
            return FrameworkPackage(**candidate_dict)
        except ValidationError:
            return None

    def _source_refs(self, candidate: Any) -> list[ImportedFrameworkSourceRef]:
        refs = [
            ImportedFrameworkSourceRef(
                source_ref_id=f"{candidate.candidate_id}_candidate",
                source_type="framework_candidate",
                source_id=candidate.candidate_id,
                relationship="supports",
                safe_summary=f"Normalized M2 framework candidate {candidate.candidate_id}.",
            ),
            ImportedFrameworkSourceRef(
                source_ref_id=f"{candidate.candidate_id}_normalization_report",
                source_type="normalization_report",
                source_id=candidate.normalization_report_id,
                relationship="warns_about",
                safe_summary="M2 normalization report and validation context.",
            ),
        ]
        if candidate.source_ref:
            refs.append(
                ImportedFrameworkSourceRef(
                    source_ref_id=f"{candidate.candidate_id}_import",
                    source_type="import",
                    source_id=candidate.import_id,
                    relationship="supports",
                    safe_summary=f"Analyze Stories import {candidate.import_id}.",
                )
            )
        try:
            viewers = self.analysis_report_viewer_service.list_viewer_states().viewer_states
        except StorageError:
            viewers = []
        for viewer in viewers:
            if viewer.linked_framework_package_id in {
                candidate.candidate_id,
                (candidate.normalized_framework_package or {}).get("framework_package_id"),
                ((candidate.normalized_framework_package or {}).get("macro_framework") or {}).get("framework_id"),
            }:
                refs.append(
                    ImportedFrameworkSourceRef(
                        source_ref_id=f"{candidate.candidate_id}_{viewer.story_analysis_report_ref_id}",
                        source_type="story_analysis_report",
                        source_id=viewer.story_analysis_report_ref_id,
                        relationship="explains",
                        safe_summary=viewer.safe_title or viewer.safe_summary,
                    )
                )
                refs.append(
                    ImportedFrameworkSourceRef(
                        source_ref_id=f"{candidate.candidate_id}_{viewer.viewer_state_id}",
                        source_type="analysis_report_viewer",
                        source_id=viewer.viewer_state_id,
                        relationship="explains",
                        safe_summary=viewer.safe_title or viewer.safe_summary,
                    )
                )
        return refs

    def _patch_field_path(
        self,
        operation: str,
        request: ImportedFrameworkActionRequest,
    ) -> str:
        if operation == "set_activation_mode":
            return "activation_mode"
        if operation == "update_macro_component":
            suffix = ""
            fields = sorted(request.patch.keys()) if isinstance(request.patch, dict) else []
            if fields:
                suffix = "." + ",".join(str(field) for field in fields)
            return f"macro_framework.components[{request.component_id or '*'}]{suffix}"
        if operation == "delete_macro_component":
            return f"macro_framework.components[{request.component_id or '*'}].deleted"
        if operation == "restore_macro_component":
            return f"macro_framework.components[{request.component_id or '*'}].deleted"
        if operation == "reorder_macro_components":
            if request.component_id:
                return f"macro_framework.components[{request.component_id}].order"
            return "macro_framework.components[*].order"
        if operation == "remap_chapter":
            chapter = request.chapter_index if request.chapter_index is not None else "*"
            return f"chapter_macro_assignments[{chapter}].linked_macro_component_ids"
        if operation == "update_chapter_count":
            return "chapter_macro_assignments"
        return "$"

    def _update_macro_component(
        self,
        package: dict[str, Any],
        request: ImportedFrameworkActionRequest,
    ) -> None:
        component = self._find_macro_component(package, request.component_id)
        patch = request.patch or {}
        for field in ("label", "instruction"):
            if field in patch:
                value = self._first_str(patch.get(field)) or ""
                self._guard_safe_payload(value)
                component[field] = value[:2400]
        if "order" in patch:
            order = self._safe_int(patch.get("order"))
            if order is None:
                raise StorageError("IMPORTED_FRAMEWORK_COMPONENT_ORDER_INVALID")
            component["order"] = order

    def _mark_macro_component_deleted(
        self,
        package: dict[str, Any],
        component_id: str | None,
        deleted: bool,
    ) -> None:
        component = self._find_macro_component(package, component_id)
        component["deleted"] = deleted

    def _reorder_macro_components(
        self,
        package: dict[str, Any],
        request: ImportedFrameworkActionRequest,
    ) -> None:
        component_orders = request.patch.get("component_orders")
        if isinstance(component_orders, dict):
            for component_id, order_value in component_orders.items():
                component = self._find_macro_component(package, str(component_id))
                order = self._safe_int(order_value)
                if order is None:
                    raise StorageError("IMPORTED_FRAMEWORK_COMPONENT_ORDER_INVALID")
                component["order"] = order
            return
        component = self._find_macro_component(package, request.component_id)
        order = self._safe_int(request.patch.get("order"))
        if order is None:
            raise StorageError("IMPORTED_FRAMEWORK_COMPONENT_ORDER_INVALID")
        component["order"] = order

    def _remap_chapter(
        self,
        package: dict[str, Any],
        request: ImportedFrameworkActionRequest,
    ) -> None:
        chapter_index = request.chapter_index
        if chapter_index is None or chapter_index <= 0:
            raise StorageError("IMPORTED_FRAMEWORK_CHAPTER_INDEX_INVALID")
        linked_ids = [
            str(component_id).strip()
            for component_id in request.linked_macro_component_ids
            if str(component_id).strip()
        ]
        if not linked_ids:
            raise StorageError("IMPORTED_FRAMEWORK_LINKED_COMPONENTS_REQUIRED")
        assignments = self._chapter_assignments(package)
        assignment = next(
            (item for item in assignments if item.get("chapter_index") == chapter_index),
            None,
        )
        if assignment is None:
            assignment = {
                "chapter_index": chapter_index,
                "linked_macro_component_ids": linked_ids,
                "assignment_type": "analyze_stories_recommended",
                "status": "draft",
                "reason": "Imported framework workbench chapter remap.",
            }
            assignments.append(assignment)
        else:
            assignment["linked_macro_component_ids"] = linked_ids
            assignment["assignment_type"] = "analyze_stories_recommended"
            assignment["status"] = "draft"
            assignment["reason"] = request.user_input or "Imported framework workbench chapter remap."
        assignments.sort(key=lambda item: int(item.get("chapter_index") or 0))
        package["chapter_macro_assignments"] = assignments

    def _update_chapter_count(
        self,
        package: dict[str, Any],
        chapter_count: int | None,
    ) -> None:
        if chapter_count is None or chapter_count < 1 or chapter_count > 20:
            raise StorageError("IMPORTED_FRAMEWORK_CHAPTER_COUNT_INVALID")
        assignments = [
            item
            for item in self._chapter_assignments(package)
            if self._safe_int(item.get("chapter_index")) is not None
            and 1 <= int(item.get("chapter_index")) <= chapter_count
        ]
        existing_indexes = {int(item.get("chapter_index")) for item in assignments}
        fallback_id = self._first_available_component_id(package)
        for chapter_index in range(1, chapter_count + 1):
            if chapter_index in existing_indexes:
                continue
            assignments.append(
                {
                    "chapter_index": chapter_index,
                    "linked_macro_component_ids": [fallback_id] if fallback_id else [],
                    "assignment_type": "analyze_stories_recommended",
                    "status": "draft",
                    "reason": "Imported framework workbench chapter count expansion.",
                }
            )
        assignments.sort(key=lambda item: int(item.get("chapter_index") or 0))
        package["chapter_macro_assignments"] = assignments

    def _append_import_decision(
        self,
        *,
        decision_type: str,
        target_id: str,
        edit_session_id: str,
        plan_id: str | None,
        activation_mode: str | None,
        user_input: str,
        safe_summary: str,
    ) -> ImportedFrameworkDecision:
        decision = ImportedFrameworkDecision(
            decision_id=self._next_id(self.decisions_file, "decision_id", "decision_imported_framework"),
            decision_type=decision_type,
            target_id=target_id,
            edit_session_id=edit_session_id,
            plan_id=plan_id,
            activation_mode=activation_mode,  # type: ignore[arg-type]
            user_input=self._safe_user_input(user_input),
            safe_summary=self._summary_text(safe_summary, 500),
            created_at=now_iso(),
            version_id=SCHEMA_VERSION,
        )
        self._replace_or_append(self.decisions_file, "decision_id", decision.decision_id, model_to_dict(decision))
        self._append_global_decision(
            decision_type=decision_type,
            target_type=IMPORT_TARGET_TYPE,
            target_id=target_id,
            user_input=decision.user_input or decision.safe_summary,
        )
        return decision

    def _append_global_decision(
        self,
        *,
        decision_type: str,
        target_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decisions = self._read_list(self.global_decisions_file)
        decision = Decision(
            decision_id=self._next_decision_id(decisions, target_type),
            decision_type=decision_type,
            target_type=target_type,
            target_id=target_id,
            user_input=self._safe_user_input(user_input),
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.store.write(self.global_decisions_file, decisions)
        return decision

    def _read_active_framework_package(
        self,
        *,
        optional: bool,
    ) -> FrameworkPackage | None:
        if not self.store.exists(self.framework_package_file):
            if optional:
                return None
            raise StorageError("IMPORTED_FRAMEWORK_ACTIVE_PACKAGE_MISSING")
        try:
            return FrameworkPackage(**self.store.read(self.framework_package_file))
        except ValidationError as exc:
            raise StorageError("IMPORTED_FRAMEWORK_ACTIVE_PACKAGE_INVALID") from exc

    def _write_framework_package(self, package: FrameworkPackage) -> None:
        self.store.write(self.framework_package_file, model_to_dict(package))

    def _summary_from_package_dict(
        self,
        package: dict[str, Any],
        *,
        prefix: str,
    ) -> ImportedFrameworkSummary:
        assignments = self._chapter_assignments(package)
        return ImportedFrameworkSummary(
            framework_package_id=self._first_str(package.get("framework_package_id")) or "",
            source=self._first_str(package.get("source")) or "",
            macro_component_count=len(self._macro_components(package)),
            chapter_assignment_count=len(assignments),
            built_chapter_framework_count=len(package.get("built_chapter_frameworks") or []),
            chapter_indexes=[
                int(item.get("chapter_index"))
                for item in assignments
                if self._safe_int(item.get("chapter_index")) is not None
            ],
            safe_summary=(
                f"{prefix}: macro_components={len(self._macro_components(package))}; "
                f"chapter_assignments={len(assignments)}."
            ),
        )

    def _current_framework_summary(self) -> ImportedFrameworkSummary:
        active = self._read_active_framework_package(optional=True)
        if active is None:
            return ImportedFrameworkSummary(safe_summary="No active framework package found.")
        return ImportedFrameworkSummary(
            framework_package_id=active.framework_package_id,
            source=active.source,
            macro_component_count=len(active.macro_framework.components),
            chapter_assignment_count=len(active.chapter_macro_assignments),
            built_chapter_framework_count=len(active.built_chapter_frameworks),
            chapter_indexes=[
                assignment.chapter_index for assignment in active.chapter_macro_assignments
            ],
            safe_summary=(
                f"Current framework {active.framework_package_id}: "
                f"macro_components={len(active.macro_framework.components)}; "
                f"chapter_assignments={len(active.chapter_macro_assignments)}; "
                f"built_chapter_frameworks={len(active.built_chapter_frameworks)}."
            ),
        )

    def _macro_components(self, package: dict[str, Any]) -> list[dict[str, Any]]:
        macro_framework = package.get("macro_framework")
        if not isinstance(macro_framework, dict):
            macro_framework = {}
            package["macro_framework"] = macro_framework
        components = macro_framework.get("components")
        if not isinstance(components, list):
            components = []
            macro_framework["components"] = components
        return [item for item in components if isinstance(item, dict)]

    def _chapter_assignments(self, package: dict[str, Any]) -> list[dict[str, Any]]:
        assignments = package.get("chapter_macro_assignments")
        if not isinstance(assignments, list):
            assignments = []
            package["chapter_macro_assignments"] = assignments
        return [item for item in assignments if isinstance(item, dict)]

    def _find_macro_component(
        self,
        package: dict[str, Any],
        component_id: str | None,
    ) -> dict[str, Any]:
        if not component_id:
            raise StorageError("IMPORTED_FRAMEWORK_COMPONENT_ID_REQUIRED")
        for component in self._macro_components(package):
            if component.get("component_id") == component_id:
                return component
        raise StorageError(f"IMPORTED_FRAMEWORK_COMPONENT_NOT_FOUND: {component_id}")

    def _first_available_component_id(self, package: dict[str, Any]) -> str:
        for component in sorted(
            self._macro_components(package),
            key=lambda item: self._safe_int(item.get("order")) or 0,
        ):
            if component.get("deleted") is not True and self._first_str(component.get("component_id")):
                return str(component.get("component_id"))
        return ""

    def _read_sessions(self) -> list[ImportedFrameworkEditSession]:
        return [
            ImportedFrameworkEditSession(**self._normalize_session_record(item))
            for item in self._read_list(self.sessions_file)
        ]

    def _read_patches(self) -> list[ImportedFrameworkEditPatch]:
        return [ImportedFrameworkEditPatch(**item) for item in self._read_list(self.patches_file)]

    def _read_plans(self) -> list[ImportedFrameworkActivationPlan]:
        return [ImportedFrameworkActivationPlan(**item) for item in self._read_list(self.plans_file)]

    def _get_session(self, edit_session_id: str) -> ImportedFrameworkEditSession:
        for session in self._read_sessions():
            if session.edit_session_id == edit_session_id:
                return session
        raise StorageError(f"IMPORTED_FRAMEWORK_EDIT_SESSION_NOT_FOUND: {edit_session_id}")

    def _normalize_session_record(self, item: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(item)
        if record.get("session_status") == "planned":
            record["session_status"] = "plan_ready"
        latest_report = record.get("latest_validation_report")
        if record.get("validation_report") is None and latest_report is not None:
            record["validation_report"] = latest_report
        if latest_report is None and record.get("validation_report") is not None:
            record["latest_validation_report"] = record.get("validation_report")
        if not isinstance(record.get("source_refs"), list):
            record["source_refs"] = []
        source_refs = record["source_refs"]
        if not record.get("story_analysis_report_ref_ids"):
            record["story_analysis_report_ref_ids"] = [
                str(ref.get("source_id"))
                for ref in source_refs
                if isinstance(ref, dict) and ref.get("source_type") == "story_analysis_report"
            ]
        if not record.get("viewer_state_ids"):
            record["viewer_state_ids"] = [
                str(ref.get("source_id"))
                for ref in source_refs
                if isinstance(ref, dict) and ref.get("source_type") == "analysis_report_viewer"
            ]
        if not record.get("original_candidate_summary"):
            summary = self._summary_from_package_dict(
                record.get("working_framework_package") if isinstance(record.get("working_framework_package"), dict) else {},
                prefix=f"Candidate {record.get('candidate_id') or ''}",
            )
            record["original_candidate_summary"] = model_to_dict(summary)
        return record

    def _get_plan(self, plan_id: str | None) -> ImportedFrameworkActivationPlan:
        if not plan_id:
            raise StorageError("IMPORTED_FRAMEWORK_ACTIVATION_PLAN_NOT_FOUND")
        for plan in self._read_plans():
            if plan.plan_id == plan_id:
                return plan
        raise StorageError(f"IMPORTED_FRAMEWORK_ACTIVATION_PLAN_NOT_FOUND: {plan_id}")

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        data = self.store.read_list(path)
        return [item for item in data if isinstance(item, dict)]

    def _replace_or_append(
        self,
        path: Path,
        id_field: str,
        id_value: str,
        item: dict[str, Any],
    ) -> None:
        items = self._read_list(path)
        replaced = False
        for index, existing in enumerate(items):
            if existing.get(id_field) == id_value:
                items[index] = item
                replaced = True
                break
        if not replaced:
            items.append(item)
        self.store.write(path, items)

    def _next_id(self, path: Path, id_field: str, prefix: str) -> str:
        existing = {
            str(item.get(id_field) or "")
            for item in self._read_list(path)
            if isinstance(item, dict)
        }
        index = len(existing) + 1
        while True:
            value = f"{prefix}_{index:03d}"
            if value not in existing:
                return value
            index += 1

    def _next_decision_id(self, decisions: list[Any], target_type: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", target_type.lower()).strip("_") or "decision"
        existing = {
            str(item.get("decision_id") or "")
            for item in decisions
            if isinstance(item, dict)
        }
        index = len(existing) + 1
        while True:
            value = f"decision_{normalized}_{index:03d}"
            if value not in existing:
                return value
            index += 1

    def _issue(
        self,
        code: str,
        severity: str,
        message: str,
        field_path: str | None = None,
        safe_detail: str | None = None,
    ) -> ImportedFrameworkValidationIssue:
        return ImportedFrameworkValidationIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            field_path=field_path,
            safe_detail=self._summary_text(safe_detail, 180) if safe_detail else None,
        )

    def _from_mapping_issue(
        self,
        issue: FrameworkMappingIssue,
        severity: str,
    ) -> ImportedFrameworkValidationIssue:
        field_path = (
            f"chapter_macro_assignments[{issue.chapter_index}]"
            if issue.chapter_index is not None
            else issue.component_id
            if issue.component_id
            else None
        )
        return self._issue(
            issue.code,
            severity,
            issue.message,
            field_path,
            issue.component_id or None,
        )

    def _dedupe_issues(
        self,
        issues: list[ImportedFrameworkValidationIssue],
    ) -> list[ImportedFrameworkValidationIssue]:
        deduped: dict[tuple[str, str | None, str | None], ImportedFrameworkValidationIssue] = {}
        for issue in issues:
            deduped[(issue.code, issue.field_path, issue.safe_detail)] = issue
        return list(deduped.values())

    def _validation_summary(self, report: ImportedFrameworkValidationReport) -> str:
        return (
            f"Imported framework validation passed={report.passed}; "
            f"blocking={len(report.blocking_issues)}; warnings={len(report.warnings)}; "
            f"requires_user_confirmation={bool(report.warnings)}."
        )

    def _attach_validation_report(
        self,
        session: ImportedFrameworkEditSession,
        report: ImportedFrameworkValidationReport,
    ) -> None:
        session.latest_validation_report = report
        session.validation_report = report

    def _guard_safe_payload(self, value: Any) -> None:
        def walk(node: Any, path: str) -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    normalized = self._normalize_key(str(key))
                    if normalized in UNSAFE_NORMALIZED_KEYS:
                        raise StorageError(f"IMPORTED_FRAMEWORK_UNSAFE_PAYLOAD_BLOCKED: {path}.[redacted]")
                    walk(child, f"{path}.{key}")
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    walk(child, f"{path}[{index}]")
            elif isinstance(node, str):
                if any(pattern.search(node) for pattern in SECRET_PATTERNS):
                    raise StorageError(f"IMPORTED_FRAMEWORK_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if any(marker in node for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"IMPORTED_FRAMEWORK_UNSAFE_PAYLOAD_BLOCKED: {path}")

        walk(value, "$")

    def _safe_user_input(self, value: str) -> str:
        self._guard_safe_payload(value)
        return self._summary_text(value, 500)

    def _summary_text(self, value: Any, limit: int = 300) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            text = str(value)
        text = " ".join(text.split())
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[redacted]", text)
        for marker in UNSAFE_VALUE_MARKERS:
            text = text.replace(marker, "[redacted]")
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _first_str(self, *values: Any) -> str | None:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if value is not None and not isinstance(value, (dict, list)):
                return str(value).strip()
        return None

    def _safe_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _normalize_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())
