from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.agents.chapter_framework_builder_agent import (
    ChapterFrameworkBuilderAgent,
)
from app.backend.core.config import settings
from app.backend.models.character import Character
from app.backend.models.chapter import Chapter
from app.backend.models.framework_package import (
    BuiltFromStateVersion,
    ChapterFramework,
    ChapterFrameworkBuildContext,
    ChapterFrameworkBuildIssue,
    ChapterFrameworkBuildReason,
    ChapterFrameworkBuildResult,
    ChapterFrameworkBuildValidationReport,
    ChapterMacroAssignment,
    ChapterModule,
    ChapterModuleVocabulary,
    FrameworkPackage,
    MacroComponent,
    ModuleComponent,
)
from app.backend.models.memory_pack import ChapterMemoryPack
from app.backend.models.relationship import Relationship
from app.backend.models.world_canvas import WorldCanvas
from app.backend.services.framework_package_service import FrameworkPackageService
from app.backend.services.model_gateway_service import ModelGatewayService
from app.backend.services.chapter_memory_service import ChapterMemoryService
from app.backend.services.active_project_story_data import current_story_workspace_project_id
from app.backend.services.character_prompt_fidelity_service import (
    premise_required_terms,
    project_requires_story_premise,
    require_project_story_premise_for_generation,
    try_read_project_story_premise,
)
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
BUILD_CONTEXT_VERSION_ID = "version_phase3_m2_build_context_001"
BUILD_REASON_VERSION_ID = "version_phase3_m2_build_reason_001"
CHAPTER_FRAMEWORK_BUILD_VERSION_ID = "version_phase3_m2_chapter_framework_001"
CHAPTER_FRAMEWORK_PROJECT_STORY_PREMISE_MISSING = "chapter_framework_project_story_premise_missing"
CHAPTER_MEMORY_PACK_MISSING = "chapter_memory_pack_missing"
CHAPTER_MEMORY_PACK_CREATED_MINIMAL = "chapter_memory_pack_created_minimal"
FRAMEWORK_BUILDER_CONTRACT_ERROR = "framework_builder_contract_error"
MODEL_FALLBACK_USED = "model_fallback_used"
CHAPTER_FRAMEWORK_M4_CONTEXT_MISSING = "CHAPTER_FRAMEWORK_M4_CONTEXT_MISSING"


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class DeterministicChapterFrameworkFallbackBuilder:
    def build(
        self,
        *,
        package: FrameworkPackage,
        assignment: ChapterMacroAssignment,
        warning_message: str,
    ) -> tuple[dict[str, Any], ChapterFrameworkBuildIssue]:
        selected_modules: list[dict[str, Any]] = []
        linked_labels = _macro_labels(package, assignment.linked_macro_component_ids)
        reason_base = (
            f"Fallback selected deterministic module components for linked macro components: "
            f"{', '.join(linked_labels) or ', '.join(assignment.linked_macro_component_ids)}."
        )
        for module in sorted(
            package.component_vocabulary.chapter_modules,
            key=lambda item: item.order,
        ):
            component_ids = [
                component.component_id
                for component in sorted(module.allowed_components, key=lambda item: item.order)
                if component.component_id
            ][:2]
            if not component_ids:
                continue
            selected_modules.append(
                {
                    "module_id": module.module_id,
                    "component_ids": component_ids,
                    "reason_summary": reason_base,
                    "confidence": 0.55,
                }
            )
        return (
            {
                "chapter_function": "fallback_current_chapter_framework",
                "chapter_goal": reason_base,
                "reader_emotion_goal": ["clarity", "controlled tension"],
                "main_conflict": "Use confirmed framework mapping and current safe story context.",
                "participating_character_ids": [],
                "relationship_focus": [],
                "information_release_policy": "Respect confirmed world rules and do not reveal future-only information.",
                "forbidden_reveals": ["Do not reveal unconfirmed future chapter outcomes."],
                "world_rule_focus": [],
                "selected_modules": selected_modules,
                "warnings": [warning_message],
            },
            ChapterFrameworkBuildIssue(
                code="model_fallback_used",
                message=warning_message,
                severity="warning",
                chapter_index=assignment.chapter_index,
            ),
        )


class ChapterFrameworkBuilderService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        agent: ChapterFrameworkBuilderAgent | None = None,
        model_gateway: ModelGatewayService | None = None,
        framework_service: FrameworkPackageService | None = None,
        fallback_builder: DeterministicChapterFrameworkFallbackBuilder | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.project_file = self.data_dir / "project.json"
        self.decisions_file = self.data_dir / "decisions.json"
        self.world_canvas_file = self.data_dir / "world_canvas.json"
        self.characters_file = self.data_dir / "characters.json"
        self.relationships_file = self.data_dir / "relationships.json"
        self.chapters_file = self.data_dir / "chapters.json"
        self.chapter_memory_packs_file = self.data_dir / "chapter_memory_packs.json"
        self.build_contexts_file = self.data_dir / "chapter_framework_build_contexts.json"
        self.build_reasons_file = self.data_dir / "chapter_framework_build_reasons.json"
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_service = framework_service or FrameworkPackageService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.agent = agent or ChapterFrameworkBuilderAgent(
            model_gateway=self.model_gateway,
        )
        self.fallback_builder = fallback_builder or DeterministicChapterFrameworkFallbackBuilder()

    def build_for_current_chapter(
        self,
        chapter_id: str | None = None,
        chapter_index: int | None = None,
        latest_user_intent_summary: str = "",
        previous_chapter_archive_id: str = "",
        previous_chapter_archive_status: str = "",
        previous_chapter_outcome_summary: str = "",
        force_rebuild: bool = False,
    ) -> ChapterFrameworkBuildResult:
        package = self._read_framework_package()
        decisions = self._read_decision_dicts()
        source_decision_ids = self._validate_m1_mapping_confirmed(package, decisions)
        resolved_chapter_id, resolved_chapter_index = self._resolve_current_chapter(
            chapter_id=chapter_id,
            chapter_index=chapter_index,
        )
        project_id = current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=package.project_id or LOCAL_PROJECT_ID,
        )
        premise = require_project_story_premise_for_generation(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
            missing_code=CHAPTER_FRAMEWORK_PROJECT_STORY_PREMISE_MISSING,
            project_file=self.project_file,
        )
        chapter_memory_pack, memory_pack_status, memory_pack_issue_codes = (
            self._ensure_chapter_memory_pack(
                project_id=project_id,
                chapter_id=resolved_chapter_id,
                chapter_index=resolved_chapter_index,
            )
        )
        assignment = self._assignment_for_chapter(package, resolved_chapter_index)
        self._validate_assignment_components(package, assignment)
        self._validate_component_vocabulary(package)

        existing = self._find_built_chapter_framework(package, resolved_chapter_index)
        if existing is not None:
            if not force_rebuild:
                return self._existing_result(existing)
            package.built_chapter_frameworks = [
                framework
                for framework in package.built_chapter_frameworks
                if framework.chapter_index != resolved_chapter_index
            ]

        warnings = self._context_warnings(
            chapter_id=resolved_chapter_id,
            chapter_index=resolved_chapter_index,
            latest_user_intent_summary=latest_user_intent_summary,
            previous_chapter_archive_id=previous_chapter_archive_id,
            previous_chapter_archive_status=previous_chapter_archive_status,
            previous_chapter_outcome_summary=previous_chapter_outcome_summary,
            memory_pack_status=memory_pack_status,
            memory_pack_issue_codes=memory_pack_issue_codes,
        )
        context = self._build_context(
            package=package,
            project_id=project_id,
            chapter_id=resolved_chapter_id,
            chapter_index=resolved_chapter_index,
            assignment=assignment,
            source_decision_ids=source_decision_ids,
            project_story_premise=premise,
            chapter_memory_pack=chapter_memory_pack,
            memory_pack_status=memory_pack_status,
            memory_pack_issue_codes=memory_pack_issue_codes,
            latest_user_intent_summary=latest_user_intent_summary,
            previous_chapter_archive_id=previous_chapter_archive_id,
            previous_chapter_archive_status=previous_chapter_archive_status,
            previous_chapter_outcome_summary=previous_chapter_outcome_summary,
            build_mode="model",
        )
        agent_payload = self._agent_payload(
            package=package,
            assignment=assignment,
            context=context,
            project_story_premise=premise,
        )

        build_mode = "model"
        try:
            agent_data = self.agent.build_current_chapter_framework(agent_payload)
            selected_modules = self._selected_modules_from_agent(package, agent_data)
        except Exception as exc:
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code=FRAMEWORK_BUILDER_CONTRACT_ERROR,
                    message=(
                        "ChapterFrameworkBuilderAgent returned invalid or unusable "
                        f"selected_modules. {self._safe_text(str(exc), 180)}"
                    ),
                    chapter_index=resolved_chapter_index,
                )
            )
            agent_data, fallback_warning = self.fallback_builder.build(
                package=package,
                assignment=assignment,
                warning_message=(
                    "ChapterFrameworkBuilderAgent could not produce a valid current "
                    f"chapter framework; deterministic fallback was used. {self._safe_text(str(exc), 180)}"
                ),
            )
            build_mode = "fallback"
            warnings.append(fallback_warning)
            selected_modules = self._selected_modules_from_agent(package, agent_data)

        context.build_mode = build_mode
        chapter_framework = self._chapter_framework_from_selection(
            package=package,
            assignment=assignment,
            chapter_id=resolved_chapter_id,
            chapter_index=resolved_chapter_index,
            selected_modules=selected_modules,
            latest_user_intent_summary=latest_user_intent_summary,
        )
        reasons = self._build_reasons(
            chapter_framework=chapter_framework,
            context=context,
            selected_modules=selected_modules,
        )

        package.built_chapter_frameworks.append(chapter_framework)
        package.built_chapter_frameworks.sort(key=lambda item: item.chapter_index)
        self._write_framework_package(package)
        self._append_build_context(context)
        self._append_build_reasons(reasons)

        report = ChapterFrameworkBuildValidationReport(
            passed=build_mode != "fallback" and not [
                warning for warning in warnings if warning.code == CHAPTER_MEMORY_PACK_MISSING
            ],
            warnings=warnings,
            blocking_issues=[],
        )
        return ChapterFrameworkBuildResult(
            success=True,
            chapter_framework=chapter_framework,
            build_context=context,
            build_reasons=reasons,
            build_mode=build_mode,
            warnings=warnings,
            validation_report=report,
            user_visible_summary=(
                f"Built current chapter {resolved_chapter_index} framework with "
                f"{len(chapter_framework.modules)} modules using {build_mode} mode."
            ),
        )

    def get_current_chapter_framework(
        self,
        chapter_id: str | None = None,
        chapter_index: int | None = None,
    ) -> ChapterFrameworkBuildResult:
        package = self._read_framework_package()
        resolved_chapter_id, resolved_chapter_index = self._resolve_current_chapter(
            chapter_id=chapter_id,
            chapter_index=chapter_index,
        )
        chapter_framework = self._find_built_chapter_framework(
            package,
            resolved_chapter_index,
        )
        if chapter_framework is None:
            raise StorageError(
                "CURRENT_CHAPTER_FRAMEWORK_MISSING: Build the current chapter framework before chapter planning."
            )
        return self._existing_result(chapter_framework)

    def get_build_context(
        self,
        chapter_framework_id: str,
    ) -> ChapterFrameworkBuildContext:
        contexts = [
            context
            for context in self._read_contexts()
            if self._context_framework_id(context) == chapter_framework_id
        ]
        if not contexts:
            raise StorageError(
                "CHAPTER_FRAMEWORK_BUILD_CONTEXT_MISSING: No build context exists for this chapter framework."
            )
        return sorted(contexts, key=lambda item: item.created_at, reverse=True)[0]

    def get_build_reasons(
        self,
        chapter_framework_id: str,
    ) -> list[ChapterFrameworkBuildReason]:
        return [
            reason
            for reason in self._read_reasons()
            if reason.chapter_framework_id == chapter_framework_id
        ]

    def _existing_result(
        self,
        chapter_framework: ChapterFramework,
    ) -> ChapterFrameworkBuildResult:
        raw_context = self._latest_context_dict_for_chapter_framework(
            chapter_framework.chapter_framework_id
        )
        context = self._latest_context_for_chapter_framework(
            chapter_framework.chapter_framework_id
        )
        reasons = self.get_build_reasons(chapter_framework.chapter_framework_id)
        if context is None or not reasons:
            raise StorageError(
                "CHAPTER_FRAMEWORK_AUDIT_MISSING: Existing chapter framework has no Phase 3 M2 build context/reasons and cannot be treated as valid."
            )
        m4_issues = self._m4_context_contract_issues(raw_context)
        if m4_issues:
            raise StorageError(
                f"{CHAPTER_FRAMEWORK_M4_CONTEXT_MISSING}: {', '.join(m4_issues)}"
            )
        mode = context.build_mode if context else "existing"
        warnings = self._existing_context_warnings(context)
        report = ChapterFrameworkBuildValidationReport(
            passed=mode != "fallback" and not [
                warning for warning in warnings if warning.code == CHAPTER_MEMORY_PACK_MISSING
            ],
            warnings=warnings,
            blocking_issues=[],
        )
        return ChapterFrameworkBuildResult(
            success=True,
            chapter_framework=chapter_framework,
            build_context=context,
            build_reasons=reasons,
            build_mode=mode,
            warnings=warnings,
            validation_report=report,
            user_visible_summary=(
                f"Returned existing current chapter {chapter_framework.chapter_index} framework."
            ),
            returned_existing=True,
        )

    def _validate_m1_mapping_confirmed(
        self,
        package: FrameworkPackage,
        decisions: list[dict[str, Any]],
    ) -> list[str]:
        assignments = package.chapter_macro_assignments
        decision_ids = [
            str(decision.get("decision_id") or "")
            for decision in decisions
            if decision.get("decision_type") == "confirm"
            and decision.get("target_type") == "framework_macro_mapping"
        ]
        if not assignments or any(assignment.status != "confirmed" for assignment in assignments):
            raise StorageError(
                "M1_FRAMEWORK_MAPPING_NOT_CONFIRMED: Confirm framework macro mapping before building a chapter framework."
            )
        if not decision_ids:
            raise StorageError(
                "M1_FRAMEWORK_MAPPING_NOT_CONFIRMED: Decision(target_type=framework_macro_mapping) is required."
            )
        return [decision_id for decision_id in decision_ids if decision_id]

    def _resolve_current_chapter(
        self,
        *,
        chapter_id: str | None,
        chapter_index: int | None,
    ) -> tuple[str, int]:
        if chapter_index is not None and chapter_index < 1:
            raise StorageError(
                "CURRENT_CHAPTER_INDEX_INVALID: chapter_index must be greater than 0."
            )
        clean_chapter_id = (chapter_id or "").strip()
        if chapter_index is not None:
            if clean_chapter_id:
                matched_chapter = next(
                    (
                        chapter
                        for chapter in self._read_chapters()
                        if chapter.chapter_id == clean_chapter_id
                    ),
                    None,
                )
                if matched_chapter and matched_chapter.chapter_index != chapter_index:
                    raise StorageError(
                        "CURRENT_CHAPTER_ID_INDEX_MISMATCH: chapter_id points to a different chapter_index."
                    )
                inferred_index = self._chapter_index_from_id(clean_chapter_id)
                if inferred_index is not None and inferred_index != chapter_index:
                    raise StorageError(
                        "CURRENT_CHAPTER_ID_INDEX_MISMATCH: chapter_id suffix does not match chapter_index."
                    )
            return clean_chapter_id or self._chapter_id(chapter_index), chapter_index

        chapters = self._read_chapters()
        if clean_chapter_id:
            for chapter in chapters:
                if chapter.chapter_id == clean_chapter_id:
                    return chapter.chapter_id, chapter.chapter_index or 1
            inferred_index = self._chapter_index_from_id(clean_chapter_id)
            if inferred_index is not None:
                return clean_chapter_id, inferred_index
            return clean_chapter_id, 1
        current = (
            next((chapter for chapter in chapters if chapter.detail_level == "current_chapter_brief"), None)
            or next((chapter for chapter in chapters if chapter.status == "active"), None)
            or next((chapter for chapter in chapters if chapter.chapter_framework_id), None)
            or (chapters[0] if chapters else None)
        )
        if current:
            return current.chapter_id, current.chapter_index or 1
        return "chapter_001", 1

    def _assignment_for_chapter(
        self,
        package: FrameworkPackage,
        chapter_index: int,
    ) -> ChapterMacroAssignment:
        for assignment in package.chapter_macro_assignments:
            if assignment.chapter_index == chapter_index:
                return assignment
        raise StorageError(
            "CURRENT_CHAPTER_ASSIGNMENT_MISSING: No confirmed macro mapping exists for the current chapter."
        )

    def _validate_assignment_components(
        self,
        package: FrameworkPackage,
        assignment: ChapterMacroAssignment,
    ) -> None:
        macro_ids = {
            component.component_id
            for component in package.macro_framework.components
        }
        unknown = [
            component_id
            for component_id in assignment.linked_macro_component_ids
            if component_id not in macro_ids
        ]
        if unknown:
            raise StorageError(
                "LINKED_MACRO_COMPONENT_UNKNOWN: " + ", ".join(sorted(unknown))
            )

    def _validate_component_vocabulary(self, package: FrameworkPackage) -> None:
        if not package.component_vocabulary.chapter_modules:
            raise StorageError(
                "LOCAL_COMPONENT_VOCABULARY_CORRUPT: chapter_modules are missing."
            )
        for module in package.component_vocabulary.chapter_modules:
            if not module.module_id or not module.allowed_components:
                raise StorageError(
                    "LOCAL_COMPONENT_VOCABULARY_CORRUPT: each chapter module needs allowed components."
                )

    def _context_warnings(
        self,
        *,
        chapter_id: str,
        chapter_index: int,
        latest_user_intent_summary: str,
        previous_chapter_archive_id: str,
        previous_chapter_archive_status: str,
        previous_chapter_outcome_summary: str,
        memory_pack_status: str,
        memory_pack_issue_codes: list[str],
    ) -> list[ChapterFrameworkBuildIssue]:
        warnings: list[ChapterFrameworkBuildIssue] = []
        if not latest_user_intent_summary.strip():
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code="latest_user_intent_summary_empty",
                    message="Latest user intent summary is empty; build used existing safe context only.",
                    chapter_index=chapter_index,
                )
            )
        if chapter_index > 1 and not previous_chapter_outcome_summary.strip():
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code="previous_chapter_outcome_summary_missing",
                    message="Previous chapter outcome summary is missing for a later chapter.",
                    chapter_index=chapter_index,
                )
            )
        if chapter_index > 1 and not previous_chapter_archive_id.strip():
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code="previous_chapter_archive_id_missing",
                    message="Previous chapter archive id is missing for a later chapter.",
                    chapter_index=chapter_index,
                )
            )
        if chapter_index > 1 and not previous_chapter_archive_status.strip():
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code="previous_chapter_archive_status_missing",
                    message="Previous chapter archive status is missing for a later chapter.",
                    chapter_index=chapter_index,
                )
            )
        if (
            chapter_index > 1
            and previous_chapter_archive_status.strip()
            and previous_chapter_archive_status.strip() not in {"stable", "provisional"}
        ):
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code="previous_chapter_archive_status_unexpected",
                    message="Previous chapter archive status is neither stable nor provisional.",
                    chapter_index=chapter_index,
                )
            )
        if CHAPTER_MEMORY_PACK_CREATED_MINIMAL in memory_pack_issue_codes:
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code=CHAPTER_MEMORY_PACK_CREATED_MINIMAL,
                    message="A minimal ChapterMemoryPack was created so framework building can continue with explicit degraded evidence.",
                    chapter_index=chapter_index,
                )
            )
        if memory_pack_status == "missing_degraded" or CHAPTER_MEMORY_PACK_MISSING in memory_pack_issue_codes:
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code=CHAPTER_MEMORY_PACK_MISSING,
                    message="No active ChapterMemoryPack could be created; framework build is degraded and must not be treated as clean.",
                    chapter_index=chapter_index,
                )
            )
        return warnings

    def _existing_context_warnings(
        self,
        context: ChapterFrameworkBuildContext | None,
    ) -> list[ChapterFrameworkBuildIssue]:
        if context is None:
            return []
        warnings: list[ChapterFrameworkBuildIssue] = []
        if context.build_mode == "fallback":
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code=MODEL_FALLBACK_USED,
                    message=(
                        "Existing chapter framework was created through deterministic "
                        "fallback and must not be treated as a clean model build."
                    ),
                    chapter_index=context.chapter_index,
                )
            )
        if CHAPTER_MEMORY_PACK_CREATED_MINIMAL in context.memory_pack_issue_codes:
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code=CHAPTER_MEMORY_PACK_CREATED_MINIMAL,
                    message="Existing chapter framework used a minimal ChapterMemoryPack.",
                    chapter_index=context.chapter_index,
                )
            )
        if (
            context.memory_pack_status == "missing_degraded"
            or CHAPTER_MEMORY_PACK_MISSING in context.memory_pack_issue_codes
        ):
            warnings.append(
                ChapterFrameworkBuildIssue(
                    code=CHAPTER_MEMORY_PACK_MISSING,
                    message=(
                        "Existing chapter framework has missing or degraded memory pack "
                        "evidence and must not be treated as clean."
                    ),
                    chapter_index=context.chapter_index,
                )
            )
        return warnings

    def _ensure_chapter_memory_pack(
        self,
        *,
        project_id: str,
        chapter_id: str,
        chapter_index: int,
    ) -> tuple[ChapterMemoryPack | None, str, list[str]]:
        existing = self._active_chapter_memory_pack(chapter_id)
        if existing is not None:
            return existing, "ready", []
        try:
            pack = ChapterMemoryService(
                store=self.store,
                data_dir=self.data_dir,
            ).build_current_chapter_pack(chapter_id=chapter_id)
            return pack, "ready", []
        except Exception:
            # Chapter planning can still show a recoverable degraded state, but the
            # validation report must carry a stable issue code.
            timestamp = now_iso()
            pack = ChapterMemoryPack(
                chapter_memory_pack_id=f"chapter_pack_{chapter_id}_minimal_m4",
                project_id=project_id or LOCAL_PROJECT_ID,
                chapter_id=chapter_id,
                status="active",
                current_chapter_goal=f"Minimal safe context for chapter {chapter_index}.",
                retrieval_summary=(
                    "Minimal ChapterMemoryPack placeholder created because no prior "
                    "retrieval context was available."
                ),
                source_query_signature={
                    "source": "phase85_m4_framework_builder_minimal_pack",
                    "chapter_id": chapter_id,
                    "chapter_index": chapter_index,
                },
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._persist_minimal_chapter_memory_pack(pack)
            return pack, "created_minimal", [CHAPTER_MEMORY_PACK_CREATED_MINIMAL]

    def _build_context(
        self,
        *,
        package: FrameworkPackage,
        project_id: str,
        chapter_id: str,
        chapter_index: int,
        assignment: ChapterMacroAssignment,
        source_decision_ids: list[str],
        project_story_premise: Any,
        chapter_memory_pack: ChapterMemoryPack | None,
        memory_pack_status: str,
        memory_pack_issue_codes: list[str],
        latest_user_intent_summary: str,
        previous_chapter_archive_id: str,
        previous_chapter_archive_status: str,
        previous_chapter_outcome_summary: str,
        build_mode: str,
    ) -> ChapterFrameworkBuildContext:
        timestamp = now_iso()
        world_canvas = self._read_world_canvas()
        characters = self._read_characters()
        relationships = self._read_relationships()
        premise_terms = premise_required_terms(project_story_premise)
        return ChapterFrameworkBuildContext(
            build_context_id=self._next_context_id(),
            project_id=project_id or LOCAL_PROJECT_ID,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            framework_package_id=package.framework_package_id,
            linked_macro_component_ids=list(assignment.linked_macro_component_ids),
            source_decision_ids=source_decision_ids,
            world_canvas_ref=self._world_canvas_ref(world_canvas),
            world_hard_rules=[
                self._safe_text(rule.statement, 220)
                for rule in world_canvas.hard_rules
            ][:10]
            if world_canvas
            else [],
            character_state_refs=[
                self._character_state_ref(character)
                for character in characters
                if character.status == "confirmed"
            ],
            relationship_refs=[
                self._relationship_ref(relationship)
                for relationship in relationships
                if relationship.status == "confirmed"
            ],
            chapter_memory_pack_id=(
                chapter_memory_pack.chapter_memory_pack_id
                if chapter_memory_pack
                else ""
            ),
            memory_pack_status=memory_pack_status,
            memory_pack_issue_codes=list(memory_pack_issue_codes),
            project_story_premise_status=(
                "ready" if project_story_premise else "not_applicable"
            ),
            project_story_premise_ref=(
                f"project_story_premise:{project_story_premise.project_id}"
                if project_story_premise
                else ""
            ),
            project_story_premise_terms=premise_terms[:24],
            previous_chapter_archive_id=self._safe_text(
                previous_chapter_archive_id,
                160,
            ),
            previous_chapter_archive_status=self._safe_text(
                previous_chapter_archive_status,
                80,
            ),
            previous_chapter_outcome_summary=self._safe_text(
                previous_chapter_outcome_summary,
                600,
            ),
            latest_user_intent_summary=self._safe_text(latest_user_intent_summary, 600),
            component_vocabulary_version=package.version_id,
            existing_built_chapter_framework_ids=[
                framework.chapter_framework_id
                for framework in package.built_chapter_frameworks
            ],
            build_mode=build_mode,
            created_at=timestamp,
            version_id=BUILD_CONTEXT_VERSION_ID,
        )

    def _agent_payload(
        self,
        *,
        package: FrameworkPackage,
        assignment: ChapterMacroAssignment,
        context: ChapterFrameworkBuildContext,
        project_story_premise: Any,
    ) -> dict[str, Any]:
        world_canvas = self._read_world_canvas()
        characters = self._read_characters()
        relationships = self._read_relationships()
        chapter_memory_pack = self._active_chapter_memory_pack(context.chapter_id)
        return {
            "chapter_index": context.chapter_index,
            "chapter_id": context.chapter_id,
            "linked_macro_components": [
                model_to_dict(component)
                for component in package.macro_framework.components
                if component.component_id in assignment.linked_macro_component_ids
            ],
            "world_canvas_summary": self._world_canvas_summary(world_canvas),
            "world_hard_rules": context.world_hard_rules,
            "active_character_context_preview": [
                self._character_preview(character)
                for character in characters
                if character.status == "confirmed"
            ][:6],
            "relationship_summary": [
                self._relationship_preview(relationship)
                for relationship in relationships
                if relationship.status == "confirmed"
            ][:8],
            "chapter_memory_pack_summary": (
                self._safe_text(chapter_memory_pack.retrieval_summary, 600)
                if chapter_memory_pack
                else ""
            ),
            "memory_pack_status": context.memory_pack_status,
            "memory_pack_issue_codes": list(context.memory_pack_issue_codes),
            "project_story_premise": (
                {
                    "project_id": project_story_premise.project_id,
                    "safe_user_story_summary": project_story_premise.safe_user_story_summary,
                    "required_story_elements": project_story_premise.required_story_elements,
                    "core_terms": project_story_premise.core_terms,
                    "setting_terms": project_story_premise.setting_terms,
                    "conflict_terms": project_story_premise.conflict_terms,
                    "role_terms": project_story_premise.role_terms,
                    "prompt_markers_detected": project_story_premise.prompt_markers_detected,
                    "required_markers": project_story_premise.prompt_fidelity_contract.required_markers,
                }
                if project_story_premise
                else None
            ),
            "previous_chapter_outcome_summary": context.previous_chapter_outcome_summary,
            "latest_user_intent_summary": context.latest_user_intent_summary,
            "component_vocabulary": self._component_vocabulary_payload(package),
            "existing_story_progress_summary": self._chapter_progress_summary(),
        }

    def _selected_modules_from_agent(
        self,
        package: FrameworkPackage,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raw_modules = data.get("selected_modules")
        if not isinstance(raw_modules, list) or not raw_modules:
            raise ValueError("selected_modules must be a non-empty list.")
        module_by_id = {
            module.module_id: module
            for module in package.component_vocabulary.chapter_modules
        }
        selected: list[dict[str, Any]] = []
        for raw in raw_modules:
            if not isinstance(raw, dict):
                raise ValueError("selected_modules items must be objects.")
            module_id = str(raw.get("module_id") or "").strip()
            if module_id not in module_by_id:
                raise ValueError(f"Unknown module_id: {module_id}")
            component_ids = [
                str(component_id).strip()
                for component_id in (raw.get("component_ids") or [])
                if str(component_id).strip()
            ]
            allowed_ids = {
                component.component_id
                for component in module_by_id[module_id].allowed_components
            }
            unknown_components = [
                component_id
                for component_id in component_ids
                if component_id not in allowed_ids
            ]
            if not component_ids or unknown_components:
                raise ValueError(
                    f"Invalid component ids for {module_id}: {', '.join(unknown_components) or 'empty'}"
                )
            selected.append(
                {
                    "module_id": module_id,
                    "component_ids": component_ids,
                    "reason_summary": self._safe_text(
                        str(raw.get("reason_summary") or "Selected by builder."),
                        400,
                    ),
                    "confidence": self._confidence(raw.get("confidence")),
                }
            )
        return selected

    def _chapter_framework_from_selection(
        self,
        *,
        package: FrameworkPackage,
        assignment: ChapterMacroAssignment,
        chapter_id: str,
        chapter_index: int,
        selected_modules: list[dict[str, Any]],
        latest_user_intent_summary: str,
    ) -> ChapterFramework:
        module_by_id = {
            module.module_id: module
            for module in package.component_vocabulary.chapter_modules
        }
        modules: list[ChapterModule] = []
        for selected in selected_modules:
            module = module_by_id[selected["module_id"]]
            component_by_id = {
                component.component_id: component
                for component in module.allowed_components
            }
            modules.append(
                ChapterModule(
                    module_id=module.module_id,
                    label=module.label,
                    scope=module.scope,
                    persistence=module.persistence,
                    owner=module.owner,
                    write_policy=module.write_policy,
                    order=module.order,
                    components=[
                        ModuleComponent(**model_to_dict(component_by_id[component_id]))
                        for component_id in selected["component_ids"]
                    ],
                )
            )
        timestamp = now_iso()
        return ChapterFramework(
            chapter_framework_id=f"chapter_fw_{chapter_index:03d}",
            chapter_index=chapter_index,
            chapter_id=chapter_id,
            build_status="built",
            built_from_state_version=BuiltFromStateVersion(),
            built_after_event_ids=[],
            user_intent_snapshot=(
                self._safe_text(latest_user_intent_summary, 500)
                or "M2 current chapter framework build used confirmed macro mapping and safe context refs."
            ),
            linked_macro_component_ids=list(assignment.linked_macro_component_ids),
            modules=modules,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _build_reasons(
        self,
        *,
        chapter_framework: ChapterFramework,
        context: ChapterFrameworkBuildContext,
        selected_modules: list[dict[str, Any]],
    ) -> list[ChapterFrameworkBuildReason]:
        created_at = now_iso()
        reasons: list[ChapterFrameworkBuildReason] = []
        for index, selected in enumerate(selected_modules, start=1):
            reasons.append(
                ChapterFrameworkBuildReason(
                    build_reason_id=self._next_reason_id(offset=index - 1),
                    chapter_framework_id=chapter_framework.chapter_framework_id,
                    build_context_id=context.build_context_id,
                    chapter_id=context.chapter_id,
                    chapter_index=context.chapter_index,
                    selected_module_id=selected["module_id"],
                    selected_component_ids=list(selected["component_ids"]),
                    reason_summary=selected["reason_summary"],
                    input_refs=[
                        ref
                        for ref in [
                            context.world_canvas_ref,
                            context.chapter_memory_pack_id,
                            context.project_story_premise_ref,
                            *context.source_decision_ids,
                        ]
                        if ref
                    ],
                    confidence=selected["confidence"],
                    created_at=created_at,
                    version_id=BUILD_REASON_VERSION_ID,
                )
            )
        return reasons

    def _read_framework_package(self) -> FrameworkPackage:
        if not self.store.exists(self.framework_package_file):
            raise StorageError("FRAMEWORK_PACKAGE_MISSING: Framework package is missing.")
        try:
            return FrameworkPackage(**self.store.read(self.framework_package_file))
        except ValidationError as exc:
            raise StorageError("FRAMEWORK_PACKAGE_INVALID: FrameworkPackage schema is invalid.") from exc

    def _write_framework_package(self, package: FrameworkPackage) -> None:
        self.store.write(self.framework_package_file, model_to_dict(package))

    def _read_decision_dicts(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.decisions_file):
            return []
        return [
            decision
            for decision in self.store.read_list(self.decisions_file)
            if isinstance(decision, dict)
        ]

    def _read_world_canvas(self) -> WorldCanvas | None:
        if not self.store.exists(self.world_canvas_file):
            return None
        try:
            return WorldCanvas(**self.store.read(self.world_canvas_file))
        except ValidationError:
            return None

    def _read_characters(self) -> list[Character]:
        if not self.store.exists(self.characters_file):
            return []
        characters: list[Character] = []
        for raw in self.store.read_list(self.characters_file):
            try:
                characters.append(Character(**raw))
            except ValidationError:
                continue
        return characters

    def _read_relationships(self) -> list[Relationship]:
        if not self.store.exists(self.relationships_file):
            return []
        relationships: list[Relationship] = []
        for raw in self.store.read_list(self.relationships_file):
            try:
                relationships.append(Relationship(**raw))
            except ValidationError:
                continue
        return relationships

    def _read_chapters(self) -> list[Chapter]:
        if not self.store.exists(self.chapters_file):
            return []
        chapters: list[Chapter] = []
        for raw in self.store.read_list(self.chapters_file):
            try:
                chapters.append(Chapter(**raw))
            except ValidationError:
                continue
        return sorted(chapters, key=lambda item: item.chapter_index or 0)

    def _active_chapter_memory_pack(self, chapter_id: str) -> ChapterMemoryPack | None:
        if not self.store.exists(self.chapter_memory_packs_file):
            return None
        try:
            raw = self.store.read_any(self.chapter_memory_packs_file)
        except StorageError:
            return None
        if isinstance(raw, dict):
            candidates = raw.get("packs") or []
        elif isinstance(raw, list):
            candidates = raw
        else:
            candidates = []
        packs: list[ChapterMemoryPack] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            try:
                pack = ChapterMemoryPack(**item)
            except ValidationError:
                continue
            if pack.chapter_id == chapter_id and pack.status == "active":
                packs.append(pack)
        if not packs:
            return None
        return sorted(packs, key=lambda item: item.updated_at or item.created_at, reverse=True)[0]

    def _persist_minimal_chapter_memory_pack(self, pack: ChapterMemoryPack) -> None:
        try:
            raw = self.store.read_any(self.chapter_memory_packs_file) if self.store.exists(self.chapter_memory_packs_file) else {}
        except StorageError:
            raw = {}
        envelope = raw if isinstance(raw, dict) else {"packs": raw if isinstance(raw, list) else []}
        packs = [item for item in envelope.get("packs", []) if isinstance(item, dict)]
        updated: list[dict[str, Any]] = []
        for item in packs:
            try:
                existing = ChapterMemoryPack(**item)
            except ValidationError:
                updated.append(item)
                continue
            if existing.chapter_id == pack.chapter_id and existing.status == "active":
                existing.status = "superseded"
                existing.updated_at = pack.updated_at
                updated.append(model_to_dict(existing))
            else:
                updated.append(item)
        updated.append(model_to_dict(pack))
        envelope["packs"] = updated
        envelope["updated_at"] = pack.updated_at
        self.store.write(self.chapter_memory_packs_file, envelope)

    def _find_built_chapter_framework(
        self,
        package: FrameworkPackage,
        chapter_index: int,
    ) -> ChapterFramework | None:
        for framework in package.built_chapter_frameworks:
            if framework.chapter_index == chapter_index:
                return framework
        return None

    def _append_build_context(self, context: ChapterFrameworkBuildContext) -> None:
        records = self._read_context_dicts()
        records.append(model_to_dict(context))
        self.store.write(self.build_contexts_file, records)

    def _append_build_reasons(self, reasons: list[ChapterFrameworkBuildReason]) -> None:
        records = self._read_reason_dicts()
        records.extend(model_to_dict(reason) for reason in reasons)
        self.store.write(self.build_reasons_file, records)

    def _read_context_dicts(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.build_contexts_file):
            return []
        return [
            item
            for item in self.store.read_list(self.build_contexts_file)
            if isinstance(item, dict)
        ]

    def _read_reason_dicts(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.build_reasons_file):
            return []
        return [
            item
            for item in self.store.read_list(self.build_reasons_file)
            if isinstance(item, dict)
        ]

    def _read_contexts(self) -> list[ChapterFrameworkBuildContext]:
        contexts: list[ChapterFrameworkBuildContext] = []
        for item in self._read_context_dicts():
            try:
                contexts.append(ChapterFrameworkBuildContext(**item))
            except ValidationError:
                continue
        return contexts

    def _read_reasons(self) -> list[ChapterFrameworkBuildReason]:
        reasons: list[ChapterFrameworkBuildReason] = []
        for item in self._read_reason_dicts():
            try:
                reasons.append(ChapterFrameworkBuildReason(**item))
            except ValidationError:
                continue
        return reasons

    def _latest_context_for_chapter_framework(
        self,
        chapter_framework_id: str,
    ) -> ChapterFrameworkBuildContext | None:
        contexts = [
            context
            for context in self._read_contexts()
            if self._context_framework_id(context) == chapter_framework_id
        ]
        if not contexts:
            return None
        return sorted(contexts, key=lambda item: item.created_at, reverse=True)[0]

    def _latest_context_dict_for_chapter_framework(
        self,
        chapter_framework_id: str,
    ) -> dict[str, Any] | None:
        suffix = chapter_framework_id.rsplit("_", 1)[-1]
        expected_index = int(suffix) if suffix.isdigit() else 0
        contexts = [
            context
            for context in self._read_context_dicts()
            if context.get("chapter_framework_id") == chapter_framework_id
            or (
                expected_index
                and int(context.get("chapter_index") or 0) == expected_index
                and f"chapter_fw_{expected_index:03d}" == chapter_framework_id
            )
        ]
        if not contexts:
            return None
        return sorted(
            contexts,
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )[0]

    def _m4_context_contract_issues(
        self,
        context: dict[str, Any] | None,
    ) -> list[str]:
        if not context:
            return [CHAPTER_MEMORY_PACK_MISSING, CHAPTER_FRAMEWORK_PROJECT_STORY_PREMISE_MISSING]
        issues: list[str] = []
        memory_status = str(context.get("memory_pack_status") or "")
        if memory_status not in {"ready", "created_minimal"}:
            issues.append(CHAPTER_MEMORY_PACK_MISSING)
        project_id = current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=str(context.get("project_id") or LOCAL_PROJECT_ID),
        )
        premise_exists = try_read_project_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
        ) is not None
        if premise_exists or project_requires_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
            project_file=self.project_file,
        ):
            premise_status = str(context.get("project_story_premise_status") or "")
            premise_ref = str(context.get("project_story_premise_ref") or "")
            premise_terms = context.get("project_story_premise_terms") or []
            if premise_status != "ready" or not premise_ref or not premise_terms:
                issues.append(CHAPTER_FRAMEWORK_PROJECT_STORY_PREMISE_MISSING)
        return list(dict.fromkeys(issues))

    def _context_framework_id(self, context: ChapterFrameworkBuildContext) -> str:
        return f"chapter_fw_{context.chapter_index:03d}"

    def _next_context_id(self) -> str:
        return f"chapter_fw_ctx_{len(self._read_context_dicts()) + 1:03d}"

    def _next_reason_id(self, offset: int = 0) -> str:
        return f"chapter_fw_reason_{len(self._read_reason_dicts()) + offset + 1:03d}"

    def _chapter_id(self, chapter_index: int) -> str:
        return f"chapter_{chapter_index:03d}"

    def _chapter_index_from_id(self, chapter_id: str) -> int | None:
        suffix = chapter_id.rsplit("_", 1)[-1]
        if suffix.isdigit():
            index = int(suffix)
            return index if index > 0 else None
        return None

    def _world_canvas_ref(self, world_canvas: WorldCanvas | None) -> str:
        if not world_canvas:
            return ""
        return ":".join(
            item
            for item in [
                world_canvas.world_canvas_id,
                world_canvas.version_id,
                world_canvas.status,
            ]
            if item
        )

    def _world_canvas_summary(self, world_canvas: WorldCanvas | None) -> dict[str, Any]:
        if not world_canvas:
            return {}
        return {
            "world_canvas_id": world_canvas.world_canvas_id,
            "status": world_canvas.status,
            "scope": self._safe_text(world_canvas.scope, 120),
            "tone": self._safe_text(world_canvas.tone, 160),
            "story_direction": self._safe_text(world_canvas.story_direction, 260),
            "history_summary": self._safe_text(world_canvas.history_summary, 260),
            "geography_summary": self._safe_text(world_canvas.geography_summary, 260),
            "culture_summary": self._safe_text(world_canvas.culture_summary, 260),
            "special_rules_summary": self._safe_text(world_canvas.special_rules_summary, 260),
        }

    def _character_state_ref(self, character: Character) -> str:
        return ":".join(
            item
            for item in [
                character.character_id,
                character.version_id,
                character.status,
                character.tier,
            ]
            if item
        )

    def _relationship_ref(self, relationship: Relationship) -> str:
        return ":".join(
            item
            for item in [
                relationship.relationship_id,
                relationship.version_id,
                relationship.status,
            ]
            if item
        )

    def _character_preview(self, character: Character) -> dict[str, Any]:
        return {
            "character_id": character.character_id,
            "name": self._safe_text(character.name, 80),
            "tier": character.tier,
            "role": self._safe_text(character.role, 80),
            "active_goal": self._safe_text(character.current_state.active_goal, 180),
            "current_arc": self._safe_text(character.arc_state.current_arc, 180),
            "hard_limits": [
                self._safe_text(limit.statement, 160)
                for limit in character.profile.hard_limits
            ][:5],
        }

    def _relationship_preview(self, relationship: Relationship) -> dict[str, Any]:
        return {
            "relationship_id": relationship.relationship_id,
            "source_id": relationship.source_id,
            "target_id": relationship.target_id,
            "type": relationship.type,
            "state": self._safe_text(relationship.state, 180),
            "strength": relationship.strength,
        }

    def _component_vocabulary_payload(self, package: FrameworkPackage) -> dict[str, Any]:
        return {
            "chapter_modules": [
                {
                    "module_id": module.module_id,
                    "label": module.label,
                    "allowed_components": [
                        {
                            "component_id": component.component_id,
                            "label": component.label,
                            "normalized_hint": component.normalized_hint,
                        }
                        for component in module.allowed_components
                    ],
                }
                for module in sorted(
                    package.component_vocabulary.chapter_modules,
                    key=lambda item: item.order,
                )
            ]
        }

    def _chapter_progress_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "chapter_id": chapter.chapter_id,
                "chapter_index": chapter.chapter_index,
                "status": chapter.status,
                "summary": self._safe_text(chapter.summary, 240),
            }
            for chapter in self._read_chapters()
        ][:5]

    def _confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

    def _safe_text(self, value: Any, limit: int = 500) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        text = _redact_secret_like_text(text)
        if len(text) > limit:
            return text[: max(0, limit - 3)].rstrip() + "..."
        return text


def _macro_labels(
    package: FrameworkPackage,
    component_ids: list[str],
) -> list[str]:
    by_id: dict[str, MacroComponent] = {
        component.component_id: component
        for component in package.macro_framework.components
    }
    return [
        by_id[component_id].label
        for component_id in component_ids
        if component_id in by_id
    ]


def _redact_secret_like_text(text: str) -> str:
    words = []
    for word in text.split(" "):
        if word.startswith("sk-") or word.startswith("lsv2_"):
            words.append("[redacted_secret]")
        else:
            words.append(word)
    return " ".join(words)
