from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.core.story_capacity import CHAPTER_COUNT_MAX, CHAPTER_COUNT_MIN
from app.backend.models.framework import Framework
from app.backend.models.decision import Decision
from app.backend.models.framework_package import (
    BuiltFromStateVersion,
    BuiltChapterFrameworkSummary,
    ChapterFramework,
    ChapterMacroAssignment,
    ChapterModule,
    ChapterModuleVocabulary,
    ComponentVocabulary,
    FrameworkMappingIssue,
    FrameworkMappingValidationReport,
    FrameworkPackage,
    FrameworkPackageSeedResponse,
    FrameworkPackageValidationResponse,
    FrameworkWorkbenchState,
    MacroAssignmentResponse,
    MacroComponent,
    MacroFramework,
    ModuleComponent,
)
from app.backend.models.story_bible import StoryBible
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.repositories import RepositoryBundle, create_repositories
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
DEFAULT_FRAMEWORK_ID = "framework_strong_basic"
DEFAULT_FRAMEWORK_PACKAGE_ID = "fw_pkg_default_strong"
FRAMEWORK_PACKAGE_VERSION_ID = "version_framework_pkg_001"
FRAMEWORK_PACKAGE_CREATED_AT = "2026-06-05T00:00:00+08:00"

ALLOWED_PACKAGE_SOURCES = {"system_default", "user_manual", "analyze_stories"}
ALLOWED_COMPONENT_SOURCES = {
    "system_default",
    "user_manual",
    "analyze_stories",
    "user_custom",
}
ALLOWED_ASSIGNMENT_TYPES = {
    "system_default",
    "user_manual",
    "analyze_stories_recommended",
}
ALLOWED_SCOPES = {"story", "chapter", "scene", "character", "cross_chapter", "macro"}
ALLOWED_PERSISTENCE = {
    "ephemeral",
    "chapter_local",
    "writes_character_state",
    "writes_story_fact",
    "long_running_tracker",
}
ALLOWED_OWNERS = {
    "macro_framework",
    "chapter_framework",
    "character_state",
    "tracker_system",
}
ALLOWED_WRITE_POLICIES = {
    "no_memory_write",
    "propose_state_change",
    "auto_write_after_confirmation",
}
MIN_WORKBENCH_CHAPTER_COUNT = CHAPTER_COUNT_MIN
MAX_WORKBENCH_CHAPTER_COUNT = CHAPTER_COUNT_MAX
FRAMEWORK_MAPPING_TARGET_TYPE = "framework_macro_mapping"


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class FrameworkPackageService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.framework_file = self.data_dir / "framework.json"
        self.story_bible_file = self.data_dir / "story_bible.json"
        self.project_file = self.data_dir / "project.json"
        self.decisions_file = self.data_dir / "decisions.json"
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def get_framework_package(self) -> FrameworkPackage:
        return self._read_framework_package()

    def ensure_default_framework_package(self) -> FrameworkPackageSeedResponse:
        created_files: list[str] = []
        existing_files: list[str] = []
        updated_files: list[str] = []

        default_package = self._build_default_package()
        package_existed = bool(self.repositories.framework_packages.list_all())
        package_changed = self._upsert_framework_package(default_package)
        if package_changed:
            updated_files.append(self.framework_package_file.name)
        elif package_existed:
            existing_files.append(self.framework_package_file.name)
        else:
            created_files.append(self.framework_package_file.name)

        framework_result = self._upsert_framework()
        if framework_result == "created":
            created_files.append(self.framework_file.name)
        elif framework_result == "updated":
            updated_files.append(self.framework_file.name)
        else:
            existing_files.append(self.framework_file.name)

        story_bible_result = self._upsert_story_bible()
        if story_bible_result == "created":
            created_files.append(self.story_bible_file.name)
        elif story_bible_result == "updated":
            updated_files.append(self.story_bible_file.name)
        elif story_bible_result == "existing":
            existing_files.append(self.story_bible_file.name)

        package = self._read_framework_package()
        validation = self.validate_framework_package()
        return FrameworkPackageSeedResponse(
            ready=validation.valid,
            created_files=created_files,
            existing_files=existing_files,
            updated_files=updated_files,
            validation_issues=validation.issues,
            package=package,
        )

    def assign_macro_components(self, chapter_count: int) -> MacroAssignmentResponse:
        state = self.recommend_mapping(chapter_count=chapter_count)
        package = self._read_framework_package()
        return MacroAssignmentResponse(
            chapter_count=chapter_count,
            assignments=package.chapter_macro_assignments,
            package=package,
            validation_report=state.validation_report,
        )

    def get_workbench_state(
        self,
        validation_report: FrameworkMappingValidationReport | None = None,
    ) -> FrameworkWorkbenchState:
        package = self._read_framework_package()
        report = validation_report or self.validate_workbench_mapping(package=package)
        confirmed = self._mapping_confirmed(package)
        requires_reconfirm = self._mapping_requires_reconfirm(package)
        return FrameworkWorkbenchState(
            project_id=package.project_id,
            framework_package_id=package.framework_package_id,
            macro_components=sorted(
                package.macro_framework.components,
                key=lambda component: component.order,
            ),
            chapter_count=self._chapter_count(package),
            chapter_macro_assignments=sorted(
                package.chapter_macro_assignments,
                key=lambda assignment: assignment.chapter_index,
            ),
            built_chapter_frameworks_summary=[
                self._built_chapter_framework_summary(chapter_framework)
                for chapter_framework in sorted(
                    package.built_chapter_frameworks,
                    key=lambda framework: framework.chapter_index,
                )
            ],
            validation_report=report,
            confirmed=confirmed,
            requires_reconfirm=requires_reconfirm,
            last_decision_id=self._last_framework_mapping_decision_id(),
        )

    def recommend_mapping(
        self,
        chapter_count: int,
        strategy: str = "balanced",
        accept_warnings: bool = False,
    ) -> FrameworkWorkbenchState:
        self._validate_workbench_chapter_count(chapter_count)
        package = self._read_framework_package()
        components = self._macro_components(package)
        was_confirmed = self._mapping_confirmed(package)
        next_status = "requires_reconfirm" if was_confirmed else "draft"
        assignments = self._build_assignments(chapter_count, components)
        for assignment in assignments:
            assignment.status = next_status
            assignment.assignment_type = "system_default"
            assignment.reason = (
                assignment.reason
                or f"System recommended {strategy} macro mapping for chapter {assignment.chapter_index}."
            )
        recompute_warnings = self._detect_recompute_warnings(
            package=package,
            proposed_assignments=assignments,
        )
        if recompute_warnings and not accept_warnings:
            return self._workbench_state_with_extra_warnings(package, recompute_warnings)
        if recompute_warnings:
            self._append_decision(
                decision_type="accept_warning",
                target_id=package.framework_package_id,
                user_input=f"System recommended {strategy} macro mapping.",
            )
        package.chapter_macro_assignments = assignments
        self._write_framework_package(package)
        return self._workbench_state_with_extra_warnings(package, recompute_warnings)

    def update_chapter_count(
        self,
        chapter_count: int,
        recompute_mapping: bool = True,
        accept_warnings: bool = False,
    ) -> FrameworkWorkbenchState:
        self._validate_workbench_chapter_count(chapter_count)
        package = self._read_framework_package()
        components = self._macro_components(package)
        was_confirmed = self._mapping_confirmed(package)
        next_status = "requires_reconfirm" if was_confirmed else "draft"
        if recompute_mapping:
            assignments = self._build_assignments(chapter_count, components)
        else:
            assignments = [
                assignment
                for assignment in package.chapter_macro_assignments
                if 1 <= assignment.chapter_index <= chapter_count
            ]
            existing_indexes = {assignment.chapter_index for assignment in assignments}
            recommended = self._build_assignments(chapter_count, components)
            assignments.extend(
                assignment
                for assignment in recommended
                if assignment.chapter_index not in existing_indexes
            )
        for assignment in assignments:
            assignment.status = next_status
            if assignment.assignment_type != "user_manual":
                assignment.assignment_type = "system_default"
        recompute_warnings = self._detect_recompute_warnings(
            package=package,
            proposed_assignments=assignments,
        )
        if recompute_warnings and not accept_warnings:
            return self._workbench_state_with_extra_warnings(package, recompute_warnings)
        if recompute_warnings:
            self._append_decision(
                decision_type="accept_warning",
                target_id=package.framework_package_id,
                user_input=f"User updated framework workbench chapter count to {chapter_count}.",
            )
        package.chapter_macro_assignments = sorted(
            assignments,
            key=lambda assignment: assignment.chapter_index,
        )
        self._write_framework_package(package)
        return self._workbench_state_with_extra_warnings(package, recompute_warnings)

    def update_assignment(
        self,
        chapter_index: int,
        linked_macro_component_ids: list[str],
        accept_warnings: bool = False,
        user_input: str = "",
    ) -> FrameworkWorkbenchState:
        if chapter_index <= 0:
            raise StorageError("chapter_index must be greater than 0.")
        package = self._read_framework_package()
        component_ids = self._normalize_component_ids(linked_macro_component_ids)
        self._validate_known_macro_component_ids(package, component_ids)
        assignment = self._find_assignment(package, chapter_index)
        if assignment is None:
            raise StorageError("No chapter macro assignment exists for this chapter_index.")

        built_warning = self._built_mapping_warning(
            package=package,
            chapter_index=chapter_index,
            proposed_component_ids=component_ids,
        )
        if built_warning and not accept_warnings:
            report = self.validate_workbench_mapping(package=package)
            report.warnings.append(built_warning)
            report.requires_user_confirmation = True
            return self.get_workbench_state(validation_report=report)

        was_confirmed = self._mapping_confirmed(package)
        assignment.linked_macro_component_ids = component_ids
        assignment.assignment_type = "user_manual"
        assignment.status = "requires_reconfirm" if was_confirmed else "draft"
        assignment.reason = (
            user_input.strip()
            or f"User manually updated macro mapping for chapter {chapter_index}."
        )
        self._write_framework_package(package)
        if built_warning and accept_warnings:
            self._append_decision(
                decision_type="accept_warning",
                target_id=package.framework_package_id,
                user_input=(
                    user_input.strip()
                    or f"User accepted built chapter mapping warning for chapter {chapter_index}."
                ),
            )
        return self.get_workbench_state()

    def validate_workbench_mapping(
        self,
        package: FrameworkPackage | None = None,
    ) -> FrameworkMappingValidationReport:
        package = package or self._read_framework_package()
        warnings: list[FrameworkMappingIssue] = []
        blocking_issues: list[FrameworkMappingIssue] = []
        chapter_count = self._chapter_count(package)
        component_by_id = {
            component.component_id: component
            for component in package.macro_framework.components
        }
        known_component_ids = set(component_by_id)

        if (
            chapter_count < MIN_WORKBENCH_CHAPTER_COUNT
            or chapter_count > MAX_WORKBENCH_CHAPTER_COUNT
        ):
            blocking_issues.append(
                FrameworkMappingIssue(
                    code="invalid_chapter_count",
                    message=(
                        f"Chapter count must be between {MIN_WORKBENCH_CHAPTER_COUNT} "
                        f"and {MAX_WORKBENCH_CHAPTER_COUNT} for M1."
                    ),
                )
            )

        assignments_by_index = {
            assignment.chapter_index: assignment
            for assignment in package.chapter_macro_assignments
        }
        expected_indexes = set(range(1, chapter_count + 1))
        for chapter_index in range(1, chapter_count + 1):
            assignment = assignments_by_index.get(chapter_index)
            if assignment is None:
                blocking_issues.append(
                    FrameworkMappingIssue(
                        code="missing_chapter_assignment",
                        message=f"Chapter {chapter_index} has no macro assignment.",
                        chapter_index=chapter_index,
                    )
                )
                continue
            if not assignment.linked_macro_component_ids:
                blocking_issues.append(
                    FrameworkMappingIssue(
                        code="empty_chapter_assignment",
                        message=f"Chapter {chapter_index} must link at least one macro component.",
                        chapter_index=chapter_index,
                    )
                )
            for component_id in assignment.linked_macro_component_ids:
                if component_id not in known_component_ids:
                    blocking_issues.append(
                        FrameworkMappingIssue(
                            code="unknown_macro_component",
                            message=(
                                f"Chapter {chapter_index} references unknown macro component "
                                f"{component_id}."
                            ),
                            chapter_index=chapter_index,
                            component_id=component_id,
                        )
                    )
        for assignment in package.chapter_macro_assignments:
            if assignment.chapter_index not in expected_indexes:
                blocking_issues.append(
                    FrameworkMappingIssue(
                        code="unexpected_chapter_assignment",
                        message=(
                            f"Chapter assignment {assignment.chapter_index} is outside "
                            f"1..{chapter_count}."
                        ),
                        chapter_index=assignment.chapter_index,
                    )
                )

        component_usage: dict[str, int] = {component_id: 0 for component_id in known_component_ids}
        previous_order = 0
        for assignment in sorted(
            package.chapter_macro_assignments,
            key=lambda item: item.chapter_index,
        ):
            orders = [
                component_by_id[component_id].order
                for component_id in assignment.linked_macro_component_ids
                if component_id in component_by_id
            ]
            for component_id in assignment.linked_macro_component_ids:
                if component_id in component_usage:
                    component_usage[component_id] += 1
            if orders:
                current_order = min(orders)
                if previous_order and current_order < previous_order:
                    warnings.append(
                        FrameworkMappingIssue(
                            code="macro_order_inversion",
                            message=(
                                f"Chapter {assignment.chapter_index} maps to an earlier "
                                "macro component than the previous chapter."
                            ),
                            chapter_index=assignment.chapter_index,
                        )
                    )
                previous_order = max(previous_order, current_order)

        for component in package.macro_framework.components:
            usage_count = component_usage.get(component.component_id, 0)
            if usage_count == 0:
                warnings.append(
                    FrameworkMappingIssue(
                        code="macro_component_unused",
                        message=f"Macro component {component.label} is not used.",
                        component_id=component.component_id,
                    )
                )
            elif usage_count > 1:
                warnings.append(
                    FrameworkMappingIssue(
                        code="macro_component_reused",
                        message=f"Macro component {component.label} is used {usage_count} times.",
                        component_id=component.component_id,
                    )
                )

        for chapter_framework in package.built_chapter_frameworks:
            assignment = assignments_by_index.get(chapter_framework.chapter_index)
            if assignment and (
                assignment.linked_macro_component_ids
                != chapter_framework.linked_macro_component_ids
            ):
                warnings.append(
                    self._built_mapping_warning(
                        package=package,
                        chapter_index=chapter_framework.chapter_index,
                        proposed_component_ids=assignment.linked_macro_component_ids,
                    )
                )
            if chapter_framework.chapter_index > chapter_count:
                blocking_issues.append(
                    FrameworkMappingIssue(
                        code="built_framework_outside_chapter_count",
                        message=(
                            f"Built chapter framework {chapter_framework.chapter_index} "
                            f"is outside 1..{chapter_count}."
                        ),
                        chapter_index=chapter_framework.chapter_index,
                    )
                )

        warnings = [warning for warning in warnings if warning is not None]
        requires_user_confirmation = any(
            warning.code in {"built_chapter_mapping_changed", "macro_order_inversion"}
            for warning in warnings
        )
        return FrameworkMappingValidationReport(
            passed=not blocking_issues,
            warnings=warnings,
            blocking_issues=blocking_issues,
            requires_user_confirmation=requires_user_confirmation,
        )

    def confirm_mapping(
        self,
        user_input: str = "",
        accept_warnings: bool = False,
    ) -> FrameworkWorkbenchState:
        package = self._read_framework_package()
        report = self.validate_workbench_mapping(package=package)
        if report.blocking_issues:
            raise StorageError("WORKBENCH_CONFIRM_BLOCKED: mapping has blocking issues.")
        if report.requires_user_confirmation and not accept_warnings:
            raise StorageError(
                "WORKBENCH_CONFIRM_REQUIRES_WARNING_ACCEPTANCE: mapping warnings require explicit acceptance."
            )
        for assignment in package.chapter_macro_assignments:
            assignment.status = "confirmed"
        self._write_framework_package(package)
        decision = self._append_decision(
            decision_type="confirm",
            target_id=package.framework_package_id,
            user_input=(
                user_input.strip()
                or f"User confirmed {self._chapter_count(package)} chapter macro framework mapping."
            ),
        )
        state = self.get_workbench_state()
        state.last_decision_id = decision.decision_id
        return state

    def build_chapter_framework(
        self,
        chapter_index: int,
        chapter_id: str | None = None,
        user_intent_snapshot: str = "",
    ) -> ChapterFramework:
        raise StorageError(
            "LEGACY_CHAPTER_FRAMEWORK_WRITE_DISABLED: Use ChapterFrameworkBuilderService.build_for_current_chapter for audited Phase 3 M2 builds."
        )

    def build_chapter_framework_draft(
        self,
        chapter_index: int,
        chapter_id: str | None = None,
        user_intent_snapshot: str = "",
    ) -> ChapterFramework:
        if chapter_index <= 0:
            raise StorageError("chapter_index must be greater than 0.")

        self.ensure_default_framework_package()
        package = self._read_framework_package()
        assignment = self._find_assignment(package, chapter_index)
        if assignment is None:
            raise StorageError(
                "No chapter macro assignment exists for this chapter_index."
            )

        chapter_framework = ChapterFramework(
            chapter_framework_id=f"chapter_fw_{chapter_index:03d}",
            chapter_index=chapter_index,
            chapter_id=chapter_id,
            build_status="built",
            built_from_state_version=BuiltFromStateVersion(),
            built_after_event_ids=[],
            user_intent_snapshot=(
                user_intent_snapshot
                or "系统默认即时构建：读取当前世界、角色、关系、记忆和 macro component。"
            ),
            linked_macro_component_ids=assignment.linked_macro_component_ids,
            modules=self._build_default_chapter_modules(
                assignment.linked_macro_component_ids,
                package.component_vocabulary,
            ),
            created_at=FRAMEWORK_PACKAGE_CREATED_AT,
            updated_at=FRAMEWORK_PACKAGE_CREATED_AT,
        )

        return chapter_framework

    def get_chapter_framework(self, chapter_index: int) -> ChapterFramework:
        package = self._read_framework_package()
        for chapter_framework in package.built_chapter_frameworks:
            if chapter_framework.chapter_index == chapter_index:
                return chapter_framework
        raise StorageError("Chapter framework does not exist for this chapter_index.")

    def validate_framework_package(self) -> FrameworkPackageValidationResponse:
        try:
            package = self._read_framework_package()
        except StorageError as exc:
            return FrameworkPackageValidationResponse(valid=False, issues=[str(exc)])

        issues: list[str] = []
        if not package.framework_package_id:
            issues.append("FrameworkPackage.framework_package_id must not be empty.")
        if package.source not in ALLOWED_PACKAGE_SOURCES:
            issues.append("FrameworkPackage.source is not allowed.")

        macro_components = package.macro_framework.components
        macro_ids = [component.component_id for component in macro_components]
        duplicate_macro_ids = {
            component_id for component_id in macro_ids if macro_ids.count(component_id) > 1
        }
        if duplicate_macro_ids:
            issues.append("Macro component ids must be unique.")

        for component in macro_components:
            self._validate_component_metadata(
                issues,
                label=f"Macro component {component.component_id}",
                source=component.source,
                scope=component.scope,
                persistence=None,
                owner=None,
                write_policy=None,
            )
            if not isinstance(component.order, int):
                issues.append("Macro component order must be sortable.")

        known_macro_ids = set(macro_ids)
        for assignment in package.chapter_macro_assignments:
            if assignment.assignment_type not in ALLOWED_ASSIGNMENT_TYPES:
                issues.append("Chapter macro assignment type is not allowed.")
            for component_id in assignment.linked_macro_component_ids:
                if component_id not in known_macro_ids:
                    issues.append(
                        "Chapter macro assignments must point to existing macro components."
                    )
                    break

        for chapter_framework in package.built_chapter_frameworks:
            for component_id in chapter_framework.linked_macro_component_ids:
                if component_id not in known_macro_ids:
                    issues.append(
                        "Chapter frameworks must point to existing macro components."
                    )
                    break
            for module in chapter_framework.modules:
                self._validate_module_metadata(issues, module)

        for module in package.component_vocabulary.chapter_modules:
            self._validate_vocabulary_module_metadata(issues, module)

        for component in package.component_vocabulary.macro_components:
            self._validate_component_metadata(
                issues,
                label=f"Vocabulary macro component {component.component_id}",
                source=component.source,
                scope=component.scope,
                persistence=None,
                owner=None,
                write_policy=None,
            )
            if not isinstance(component.order, int):
                issues.append("Vocabulary macro component order must be sortable.")

        for component in package.component_vocabulary.module_components:
            self._validate_component_metadata(
                issues,
                label=f"Vocabulary module component {component.component_id}",
                source=component.source,
                scope=component.scope,
                persistence=component.persistence,
                owner=component.owner,
                write_policy=component.write_policy,
            )
            if not isinstance(component.order, int):
                issues.append("Vocabulary module component order must be sortable.")

        if self.store.exists(self.framework_file):
            framework = self._read_framework()
            if framework.framework_package_id != package.framework_package_id:
                issues.append(
                    "Framework.framework_package_id must point to FrameworkPackage.framework_package_id."
                )

        return FrameworkPackageValidationResponse(valid=len(issues) == 0, issues=issues)

    def _validate_workbench_chapter_count(self, chapter_count: int) -> None:
        if (
            chapter_count < MIN_WORKBENCH_CHAPTER_COUNT
            or chapter_count > MAX_WORKBENCH_CHAPTER_COUNT
        ):
            raise StorageError(
                f"chapter_count must be between {MIN_WORKBENCH_CHAPTER_COUNT} and {MAX_WORKBENCH_CHAPTER_COUNT}."
            )

    def _macro_components(self, package: FrameworkPackage) -> list[MacroComponent]:
        components = sorted(
            package.macro_framework.components,
            key=lambda component: component.order,
        )
        if not components:
            raise StorageError("Framework package has no macro components.")
        return components

    def _chapter_count(self, package: FrameworkPackage) -> int:
        if package.chapter_macro_assignments:
            return max(
                assignment.chapter_index
                for assignment in package.chapter_macro_assignments
            )
        component_count = len(package.macro_framework.components)
        if MIN_WORKBENCH_CHAPTER_COUNT <= component_count <= MAX_WORKBENCH_CHAPTER_COUNT:
            return component_count
        return MAX_WORKBENCH_CHAPTER_COUNT

    def _mapping_confirmed(self, package: FrameworkPackage) -> bool:
        if not package.chapter_macro_assignments:
            return False
        has_confirm_decision = bool(self._last_framework_mapping_decision_id())
        return has_confirm_decision and all(
            assignment.status == "confirmed"
            for assignment in package.chapter_macro_assignments
        )

    def _mapping_requires_reconfirm(self, package: FrameworkPackage) -> bool:
        return any(
            assignment.status == "requires_reconfirm"
            for assignment in package.chapter_macro_assignments
        )

    def _built_chapter_framework_summary(
        self,
        chapter_framework: ChapterFramework,
    ) -> BuiltChapterFrameworkSummary:
        return BuiltChapterFrameworkSummary(
            chapter_index=chapter_framework.chapter_index,
            chapter_framework_id=chapter_framework.chapter_framework_id,
            chapter_id=chapter_framework.chapter_id,
            build_status=chapter_framework.build_status,
            linked_macro_component_ids=chapter_framework.linked_macro_component_ids,
        )

    def _last_framework_mapping_decision_id(self) -> str:
        if not self.store.exists(self.decisions_file):
            return ""
        decisions = self.store.read_list(self.decisions_file)
        matching = [
            decision
            for decision in decisions
            if isinstance(decision, dict)
            and decision.get("target_type") == FRAMEWORK_MAPPING_TARGET_TYPE
        ]
        if not matching:
            return ""
        matching.sort(key=lambda decision: str(decision.get("created_at") or ""))
        return str(matching[-1].get("decision_id") or "")

    def _normalize_component_ids(self, component_ids: list[str]) -> list[str]:
        normalized: list[str] = []
        for component_id in component_ids:
            text = str(component_id or "").strip()
            if text and text not in normalized:
                normalized.append(text)
        if not normalized:
            raise StorageError("linked_macro_component_ids must not be empty.")
        return normalized

    def _validate_known_macro_component_ids(
        self,
        package: FrameworkPackage,
        component_ids: list[str],
    ) -> None:
        known_ids = {
            component.component_id
            for component in package.macro_framework.components
        }
        unknown_ids = [
            component_id
            for component_id in component_ids
            if component_id not in known_ids
        ]
        if unknown_ids:
            raise StorageError(
                f"Unknown macro component id: {', '.join(unknown_ids)}"
            )

    def _built_mapping_warning(
        self,
        *,
        package: FrameworkPackage,
        chapter_index: int,
        proposed_component_ids: list[str],
    ) -> FrameworkMappingIssue | None:
        for chapter_framework in package.built_chapter_frameworks:
            if (
                chapter_framework.chapter_index == chapter_index
                and chapter_framework.linked_macro_component_ids
                != proposed_component_ids
            ):
                return FrameworkMappingIssue(
                    code="built_chapter_mapping_changed",
                    message=(
                        f"Chapter {chapter_index} already has a built chapter framework; "
                        "changing its macro mapping requires explicit user confirmation and does not rebuild it."
                    ),
                    chapter_index=chapter_index,
                )
        return None

    def _detect_recompute_warnings(
        self,
        *,
        package: FrameworkPackage,
        proposed_assignments: list[ChapterMacroAssignment],
    ) -> list[FrameworkMappingIssue]:
        if not package.built_chapter_frameworks:
            return []

        existing_by_index = {
            assignment.chapter_index: assignment
            for assignment in package.chapter_macro_assignments
        }
        proposed_by_index = {
            assignment.chapter_index: assignment
            for assignment in proposed_assignments
        }
        warnings: list[FrameworkMappingIssue] = []

        for chapter_framework in package.built_chapter_frameworks:
            chapter_index = chapter_framework.chapter_index
            existing = existing_by_index.get(chapter_index)
            proposed = proposed_by_index.get(chapter_index)
            if proposed is None:
                warnings.append(
                    FrameworkMappingIssue(
                        code="built_chapter_mapping_changed",
                        message=(
                            f"Chapter {chapter_index} already has a built chapter framework; "
                            "recomputing chapter count would remove its macro mapping."
                        ),
                        chapter_index=chapter_index,
                    )
                )
                continue
            current_component_ids = (
                existing.linked_macro_component_ids
                if existing
                else chapter_framework.linked_macro_component_ids
            )
            if current_component_ids != proposed.linked_macro_component_ids:
                warnings.append(
                    FrameworkMappingIssue(
                        code="built_chapter_mapping_changed",
                        message=(
                            f"Chapter {chapter_index} already has a built chapter framework; "
                            "recomputing would change its macro mapping and requires explicit warning acceptance."
                        ),
                        chapter_index=chapter_index,
                    )
                )
        return warnings

    def _workbench_state_with_extra_warnings(
        self,
        package: FrameworkPackage,
        extra_warnings: list[FrameworkMappingIssue],
    ) -> FrameworkWorkbenchState:
        report = self.validate_workbench_mapping(package=package)
        if extra_warnings:
            existing_keys = {
                (
                    warning.code,
                    warning.chapter_index,
                    warning.component_id,
                    warning.message,
                )
                for warning in report.warnings
            }
            for warning in extra_warnings:
                key = (
                    warning.code,
                    warning.chapter_index,
                    warning.component_id,
                    warning.message,
                )
                if key not in existing_keys:
                    report.warnings.append(warning)
            report.requires_user_confirmation = True
        return self.get_workbench_state(validation_report=report)

    def _append_decision(
        self,
        *,
        decision_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decisions = (
            self.store.read_list(self.decisions_file)
            if self.store.exists(self.decisions_file)
            else []
        )
        decision = Decision(
            decision_id=self._next_decision_id(decisions),
            decision_type=decision_type,
            target_type=FRAMEWORK_MAPPING_TARGET_TYPE,
            target_id=target_id,
            user_input=user_input,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        decisions.append(model_to_dict(decision))
        self.store.write(self.decisions_file, decisions)
        return decision

    def _next_decision_id(self, decisions: list[Any]) -> str:
        existing_ids = {
            str(decision.get("decision_id") or "")
            for decision in decisions
            if isinstance(decision, dict)
        }
        index = len(existing_ids) + 1
        while True:
            decision_id = f"decision_framework_macro_mapping_{index:03d}"
            if decision_id not in existing_ids:
                return decision_id
            index += 1

    def _ensure_chapter_framework_commit_allowed(self) -> None:
        if not self.store.exists(self.project_file):
            raise StorageError(
                "CHAPTER_FRAMEWORK_COMMIT_NOT_ALLOWED: Project is missing."
            )

        project = self.store.read(self.project_file)
        if (
            project.get("current_step") != "chapter_plan_confirmed"
            and project.get("status") != "chapter_plan_confirmed"
        ):
            raise StorageError(
                "CHAPTER_FRAMEWORK_COMMIT_NOT_ALLOWED: Chapter plan must be confirmed before writing built chapter frameworks."
            )

        if not self.store.exists(self.decisions_file):
            raise StorageError(
                "CHAPTER_FRAMEWORK_COMMIT_NOT_ALLOWED: Chapter plan confirmation Decision is missing."
            )

        decisions = self.store.read_list(self.decisions_file)
        has_chapter_plan_decision = any(
            isinstance(decision, dict)
            and decision.get("decision_type") == "confirm"
            and decision.get("target_type") == "chapter_plan"
            for decision in decisions
        )
        if not has_chapter_plan_decision:
            raise StorageError(
                "CHAPTER_FRAMEWORK_COMMIT_NOT_ALLOWED: Chapter plan confirmation Decision is missing."
            )

    def _read_framework_package(self) -> FrameworkPackage:
        records = self.repositories.framework_packages.list_all()
        if not records:
            raise StorageError(
                f"JSON document does not exist: {self.framework_package_file}"
            )
        data = records[0]
        try:
            return FrameworkPackage(**data)
        except ValidationError as exc:
            raise StorageError(
                f"JSON schema is invalid: {self.framework_package_file}"
            ) from exc

    def _write_framework_package(self, package: FrameworkPackage) -> None:
        record = model_to_dict(package)
        self.repositories.framework_packages.upsert(record, "framework_package_id")

    def _read_framework(self) -> Framework:
        data = self.store.read(self.framework_file)
        try:
            return Framework(**data)
        except ValidationError as exc:
            raise StorageError(f"JSON schema is invalid: {self.framework_file}") from exc

    def _upsert_framework_package(self, default_package: FrameworkPackage) -> bool:
        existing_records = self.repositories.framework_packages.list_all()
        if not existing_records:
            self._write_framework_package(default_package)
            return False

        existing = existing_records[0]
        package = FrameworkPackage(**existing)
        current_project_id = self._current_project_id()
        changed = False
        if package.framework_package_id != DEFAULT_FRAMEWORK_PACKAGE_ID:
            package.framework_package_id = DEFAULT_FRAMEWORK_PACKAGE_ID
            changed = True
        if package.project_id != current_project_id:
            package.project_id = current_project_id
            changed = True
        if package.source not in ALLOWED_PACKAGE_SOURCES:
            package.source = default_package.source
            changed = True
        if not package.macro_framework.components:
            package.macro_framework = default_package.macro_framework
            changed = True
        if not package.component_vocabulary.macro_components:
            package.component_vocabulary.macro_components = (
                default_package.component_vocabulary.macro_components
            )
            changed = True
        if not package.component_vocabulary.chapter_modules:
            package.component_vocabulary.chapter_modules = (
                default_package.component_vocabulary.chapter_modules
            )
            changed = True
        if not package.component_vocabulary.module_components:
            package.component_vocabulary.module_components = (
                default_package.component_vocabulary.module_components
            )
            changed = True
        if changed:
            self._write_framework_package(package)
        return changed

    def _upsert_framework(self) -> str:
        current_project_id = self._current_project_id()
        default_framework = Framework(
            framework_id=DEFAULT_FRAMEWORK_ID,
            project_id=current_project_id,
            name="默认强约束 framework",
            constraint_strength="strong",
            maturity="System",
            source="system_default",
            framework_package_id=DEFAULT_FRAMEWORK_PACKAGE_ID,
            module_ids=[],
            stage_ids=[],
            beat_ids=[],
            nodes=[],
        )
        if not self.store.exists(self.framework_file):
            self.store.write(self.framework_file, model_to_dict(default_framework))
            return "created"

        existing = self.store.read(self.framework_file)
        updated = dict(existing)
        updated["framework_id"] = updated.get("framework_id") or DEFAULT_FRAMEWORK_ID
        updated["project_id"] = current_project_id
        updated["constraint_strength"] = (
            updated.get("constraint_strength") or "strong"
        )
        updated["maturity"] = "System"
        updated["source"] = updated.get("source") or "system_default"
        updated["framework_package_id"] = DEFAULT_FRAMEWORK_PACKAGE_ID
        if "name" not in updated or not updated["name"]:
            updated["name"] = default_framework.name
        if updated != existing:
            self.store.write(self.framework_file, updated)
            return "updated"
        return "existing"

    def _upsert_story_bible(self) -> str:
        if not self.store.exists(self.story_bible_file):
            return "missing"

        existing = self.store.read(self.story_bible_file)
        updated = dict(existing)
        updated["project_id"] = self._current_project_id()
        updated["active_framework_id"] = self._current_framework_id()
        if updated != existing:
            self.store.write(self.story_bible_file, updated)
            return "updated"
        return "existing"

    def _current_framework_id(self) -> str:
        if not self.store.exists(self.framework_file):
            return DEFAULT_FRAMEWORK_ID
        framework = self.store.read(self.framework_file)
        return str(framework.get("framework_id") or DEFAULT_FRAMEWORK_ID)

    def _build_assignments(
        self, chapter_count: int, components: list[MacroComponent]
    ) -> list[ChapterMacroAssignment]:
        component_count = len(components)
        assignments: list[ChapterMacroAssignment] = []
        for chapter_index in range(1, chapter_count + 1):
            linked_components: list[MacroComponent]
            if chapter_count == component_count:
                linked_components = [components[chapter_index - 1]]
            elif chapter_count < component_count:
                start = (chapter_index - 1) * component_count // chapter_count
                end = chapter_index * component_count // chapter_count
                linked_components = components[start:end] or [components[start]]
            else:
                if chapter_index == 1:
                    linked_components = [components[0]]
                elif chapter_index == chapter_count:
                    linked_components = [components[-1]]
                else:
                    middle_components = components[1:-1] or components
                    linked_components = [
                        middle_components[(chapter_index - 2) % len(middle_components)]
                    ]

            labels = "、".join(component.label for component in linked_components)
            assignments.append(
                ChapterMacroAssignment(
                    chapter_index=chapter_index,
                    linked_macro_component_ids=[
                        component.component_id for component in linked_components
                    ],
                    assignment_type="system_default",
                    status="planned",
                    reason=f"第 {chapter_index} 章承担 {labels} 功能。",
                )
            )
        return assignments

    def _find_assignment(
        self, package: FrameworkPackage, chapter_index: int
    ) -> ChapterMacroAssignment | None:
        for assignment in package.chapter_macro_assignments:
            if assignment.chapter_index == chapter_index:
                return assignment
        return None

    def _build_default_chapter_modules(
        self,
        linked_macro_component_ids: list[str],
        vocabulary: ComponentVocabulary,
    ) -> list[ChapterModule]:
        macro_component_id = linked_macro_component_ids[0]
        component_ids_by_module = self._module_component_plan(macro_component_id)
        modules: list[ChapterModule] = []
        for module_order, vocab_module in enumerate(
            vocabulary.chapter_modules, start=1
        ):
            selected_ids = component_ids_by_module.get(vocab_module.module_id, [])
            selected_components = [
                component
                for component in vocab_module.allowed_components
                if component.component_id in selected_ids
            ]
            components = [
                component.copy(update={"order": index})
                for index, component in enumerate(selected_components, start=1)
            ]
            modules.append(
                ChapterModule(
                    module_id=vocab_module.module_id,
                    label=vocab_module.label,
                    scope=vocab_module.scope,
                    persistence=vocab_module.persistence,
                    owner=vocab_module.owner,
                    write_policy=vocab_module.write_policy,
                    order=module_order,
                    components=components,
                )
            )
        return modules

    def _module_component_plan(self, macro_component_id: str) -> dict[str, list[str]]:
        base_plan = {
            "chapter_function": ["chapter_world_setup", "chapter_character_establish"],
            "reader_emotion": ["emotion_curiosity", "emotion_unease"],
            "character_desire": ["desire_seek_truth"],
            "character_arc": ["arc_observer_to_actor"],
            "conflict": ["conflict_person_vs_institution", "conflict_person_vs_unknown"],
            "information_release": ["info_partial_truth"],
            "style_pacing": ["style_slow_suspense"],
        }
        if macro_component_id == "macro_inciting_incident":
            base_plan["chapter_function"] = ["chapter_inciting_push"]
            base_plan["reader_emotion"] = ["emotion_tension", "emotion_expectation"]
        elif macro_component_id == "macro_development_escalation":
            base_plan["chapter_function"] = ["chapter_conflict_escalation"]
            base_plan["conflict"] = ["conflict_pressure_growth"]
        elif macro_component_id == "macro_crisis_local_climax":
            base_plan["chapter_function"] = ["chapter_crisis_choice"]
            base_plan["reader_emotion"] = ["emotion_tension", "emotion_shock"]
        elif macro_component_id == "macro_resolution_aftermath":
            base_plan["chapter_function"] = ["chapter_aftermath_new_state"]
            base_plan["reader_emotion"] = ["emotion_relief", "emotion_unease"]
        return base_plan

    def _validate_module_metadata(
        self, issues: list[str], module: ChapterModule
    ) -> None:
        self._validate_component_metadata(
            issues,
            label=f"Chapter module {module.module_id}",
            source=None,
            scope=module.scope,
            persistence=module.persistence,
            owner=module.owner,
            write_policy=module.write_policy,
        )
        if not isinstance(module.order, int):
            issues.append("Chapter module order must be sortable.")
        for component in module.components:
            self._validate_component_metadata(
                issues,
                label=f"Module component {component.component_id}",
                source=component.source,
                scope=component.scope,
                persistence=component.persistence,
                owner=component.owner,
                write_policy=component.write_policy,
            )
            if not isinstance(component.order, int):
                issues.append("Module component order must be sortable.")

    def _validate_vocabulary_module_metadata(
        self, issues: list[str], module: ChapterModuleVocabulary
    ) -> None:
        self._validate_component_metadata(
            issues,
            label=f"Vocabulary module {module.module_id}",
            source=None,
            scope=module.scope,
            persistence=module.persistence,
            owner=module.owner,
            write_policy=module.write_policy,
        )
        for component in module.allowed_components:
            self._validate_component_metadata(
                issues,
                label=f"Vocabulary component {component.component_id}",
                source=component.source,
                scope=component.scope,
                persistence=component.persistence,
                owner=component.owner,
                write_policy=component.write_policy,
            )

    def _validate_component_metadata(
        self,
        issues: list[str],
        label: str,
        source: str | None,
        scope: str | None,
        persistence: str | None,
        owner: str | None,
        write_policy: str | None,
    ) -> None:
        if source is not None and source not in ALLOWED_COMPONENT_SOURCES:
            issues.append(f"{label} source is not allowed.")
        if scope is not None and scope not in ALLOWED_SCOPES:
            issues.append(f"{label} scope is not allowed.")
        if persistence is not None and persistence not in ALLOWED_PERSISTENCE:
            issues.append(f"{label} persistence is not allowed.")
        if owner is not None and owner not in ALLOWED_OWNERS:
            issues.append(f"{label} owner is not allowed.")
        if write_policy is not None and write_policy not in ALLOWED_WRITE_POLICIES:
            issues.append(f"{label} write_policy is not allowed.")

    def _build_default_package(self) -> FrameworkPackage:
        macro_components = [
            MacroComponent(
                component_id="macro_opening",
                label="开端",
                order=1,
                instruction="建立世界、主角、基调和初始缺口。",
            ),
            MacroComponent(
                component_id="macro_inciting_incident",
                label="触发事件",
                order=2,
                instruction="让故事真正进入运动，并迫使角色回应核心问题。",
            ),
            MacroComponent(
                component_id="macro_development_escalation",
                label="发展/升级",
                order=3,
                instruction="推进目标、扩大冲突、引入更复杂的压力。",
            ),
            MacroComponent(
                component_id="macro_crisis_local_climax",
                label="危机/局部高潮",
                order=4,
                instruction="让角色面对关键选择，并形成局部强度峰值。",
            ),
            MacroComponent(
                component_id="macro_resolution_aftermath",
                label="结尾/余波",
                order=5,
                instruction="呈现选择后果，形成阶段性落点和新状态。",
            ),
        ]
        return FrameworkPackage(
            framework_package_id=DEFAULT_FRAMEWORK_PACKAGE_ID,
            project_id=self._current_project_id(),
            source="system_default",
            language="zh",
            constraint_strength="strong",
            maturity="System",
            macro_framework=MacroFramework(components=macro_components),
            component_vocabulary=ComponentVocabulary(
                macro_components=macro_components,
                chapter_modules=self._build_default_chapter_module_vocabulary(),
                module_components=[
                    ModuleComponent(
                        component_id="custom_001",
                        label="让读者感觉胜利背后有一点不安",
                        source="user_custom",
                        scope="chapter",
                        persistence="chapter_local",
                        owner="chapter_framework",
                        write_policy="no_memory_write",
                        normalized_hint="正向胜利 + 潜在不安",
                        order=1,
                    )
                ],
            ),
            chapter_macro_assignments=[],
            built_chapter_frameworks=[],
            version_id=FRAMEWORK_PACKAGE_VERSION_ID,
        )

    def _build_default_chapter_module_vocabulary(
        self,
    ) -> list[ChapterModuleVocabulary]:
        return [
            ChapterModuleVocabulary(
                module_id="chapter_function",
                label="篇章功能模块",
                scope="chapter",
                persistence="chapter_local",
                owner="chapter_framework",
                write_policy="no_memory_write",
                order=1,
                allowed_components=[
                    ModuleComponent(
                        component_id="chapter_world_setup",
                        label="世界铺垫",
                        normalized_hint="建立世界范围、规则、基调和初始缺口。",
                    ),
                    ModuleComponent(
                        component_id="chapter_character_establish",
                        label="角色建立",
                        normalized_hint="让主角的身份、欲望和限制清晰可见。",
                    ),
                    ModuleComponent(
                        component_id="chapter_inciting_push",
                        label="触发推进",
                        normalized_hint="用事件迫使角色进入主线运动。",
                    ),
                    ModuleComponent(
                        component_id="chapter_conflict_escalation",
                        label="冲突升级",
                        normalized_hint="扩大压力、误解或风险。",
                    ),
                    ModuleComponent(
                        component_id="chapter_crisis_choice",
                        label="危机选择",
                        normalized_hint="让角色必须做出有代价的关键选择。",
                    ),
                    ModuleComponent(
                        component_id="chapter_aftermath_new_state",
                        label="余波与新状态",
                        normalized_hint="展示选择后果和阶段性落点。",
                    ),
                ],
            ),
            ChapterModuleVocabulary(
                module_id="reader_emotion",
                label="读者情绪模块",
                scope="chapter",
                persistence="ephemeral",
                owner="chapter_framework",
                write_policy="no_memory_write",
                order=2,
                allowed_components=[
                    ModuleComponent(
                        component_id="emotion_curiosity",
                        label="好奇",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="引发读者想知道更多。",
                    ),
                    ModuleComponent(
                        component_id="emotion_unease",
                        label="不安",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="让读者感觉真相背后仍有危险。",
                    ),
                    ModuleComponent(
                        component_id="emotion_tension",
                        label="紧张",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="提高冲突压力和阅读期待。",
                    ),
                    ModuleComponent(
                        component_id="emotion_expectation",
                        label="期待",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="让读者等待角色行动后的变化。",
                    ),
                    ModuleComponent(
                        component_id="emotion_shock",
                        label="震惊",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="让局势意义发生突然变化。",
                    ),
                    ModuleComponent(
                        component_id="emotion_relief",
                        label="释然",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="让阶段性压力暂时落下。",
                    ),
                ],
            ),
            ChapterModuleVocabulary(
                module_id="character_desire",
                label="角色欲望模块",
                scope="character",
                persistence="writes_character_state",
                owner="character_state",
                write_policy="propose_state_change",
                order=3,
                allowed_components=[
                    ModuleComponent(
                        component_id="desire_seek_truth",
                        label="确认关键事实",
                        scope="character",
                        persistence="writes_character_state",
                        owner="character_state",
                        write_policy="propose_state_change",
                        normalized_hint="角色开始把关键事实和行动责任置于便利或回避之上。",
                    ),
                    ModuleComponent(
                        component_id="desire_confirm_responsibility_boundary",
                        label="确认责任边界",
                        scope="character",
                        persistence="writes_character_state",
                        owner="character_state",
                        write_policy="propose_state_change",
                        normalized_hint="角色开始把技术、制度或行动责任置于便利之上。",
                    )
                ],
            ),
            ChapterModuleVocabulary(
                module_id="character_arc",
                label="人物弧光模块",
                scope="cross_chapter",
                persistence="writes_character_state",
                owner="character_state",
                write_policy="propose_state_change",
                order=4,
                allowed_components=[
                    ModuleComponent(
                        component_id="arc_observer_to_actor",
                        label="从观察到行动",
                        scope="cross_chapter",
                        persistence="writes_character_state",
                        owner="character_state",
                        write_policy="propose_state_change",
                        normalized_hint="角色从记录、观察或回避转向主动行动并承担代价。",
                    )
                ],
            ),
            ChapterModuleVocabulary(
                module_id="conflict",
                label="冲突模块",
                scope="chapter",
                persistence="writes_story_fact",
                owner="chapter_framework",
                write_policy="propose_state_change",
                order=5,
                allowed_components=[
                    ModuleComponent(
                        component_id="conflict_person_vs_institution",
                        label="人与制度冲突",
                        persistence="writes_story_fact",
                        write_policy="propose_state_change",
                        normalized_hint="角色与城市机构、规则或权威发生对抗。",
                    ),
                    ModuleComponent(
                        component_id="conflict_person_vs_unknown",
                        label="人与未明规则冲突",
                        persistence="writes_story_fact",
                        write_policy="propose_state_change",
                        normalized_hint="角色面对尚未解释清楚的世界规则、系统边界或异常现象。",
                    ),
                    ModuleComponent(
                        component_id="conflict_pressure_growth",
                        label="压力增长",
                        persistence="writes_story_fact",
                        write_policy="propose_state_change",
                        normalized_hint="风险、误解或代价持续扩大。",
                    ),
                    ModuleComponent(
                        component_id="conflict_person_vs_algorithmic_system",
                        label="人与算法系统冲突",
                        persistence="writes_story_fact",
                        write_policy="propose_state_change",
                        normalized_hint="角色与算法判断、自动化流程或技术治理系统发生对抗。",
                    ),
                    ModuleComponent(
                        component_id="conflict_public_efficiency_vs_individual_dignity",
                        label="效率与尊严冲突",
                        persistence="writes_story_fact",
                        write_policy="propose_state_change",
                        normalized_hint="公共效率诉求与个体尊严、申诉权或真实处境发生冲突。",
                    ),
                ],
            ),
            ChapterModuleVocabulary(
                module_id="information_release",
                label="信息释放模块",
                scope="chapter",
                persistence="writes_story_fact",
                owner="chapter_framework",
                write_policy="propose_state_change",
                order=6,
                allowed_components=[
                    ModuleComponent(
                        component_id="info_partial_truth",
                        label="释放阶段性事实",
                        persistence="writes_story_fact",
                        write_policy="propose_state_change",
                        normalized_hint="释放一部分可确认事实，同时保留更深层原因或后果。",
                    ),
                    ModuleComponent(
                        component_id="info_audit_chain",
                        label="揭示审计链",
                        persistence="writes_story_fact",
                        write_policy="propose_state_change",
                        normalized_hint="释放一段可复查的责任链、数据来源或人工复核记录。",
                    )
                ],
            ),
            ChapterModuleVocabulary(
                module_id="style_pacing",
                label="风格与节奏模块",
                scope="chapter",
                persistence="ephemeral",
                owner="chapter_framework",
                write_policy="no_memory_write",
                order=7,
                allowed_components=[
                    ModuleComponent(
                        component_id="style_slow_suspense",
                        label="慢热张力",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="低速推进，用细节、缺口和选择压力积累阅读张力。",
                    ),
                    ModuleComponent(
                        component_id="style_rational_warm",
                        label="理性温暖",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="用清晰逻辑推进，同时保留角色和读者能感到的人情温度。",
                    ),
                    ModuleComponent(
                        component_id="style_social_issue_tension",
                        label="社会议题张力",
                        persistence="ephemeral",
                        write_policy="no_memory_write",
                        normalized_hint="让制度、技术和个人处境之间的张力成为章节表达重点。",
                    )
                ],
            ),
        ]
