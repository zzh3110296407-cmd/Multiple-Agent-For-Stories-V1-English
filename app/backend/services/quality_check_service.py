import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.character import Character
from app.backend.models.framework_package import ChapterFramework, FrameworkPackage
from app.backend.models.quality import (
    QualityCheckResponse,
    QualityCheckResult,
    QualityIssue,
    QualityReport,
    to_embedded_scene_quality_report,
)
from app.backend.models.relationship import Relationship
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import SceneMemoryExtraction, SceneQualityReport
from app.backend.models.scene_revision import SceneRevisionCandidate
from app.backend.models.world_canvas import WorldCanvas
from app.backend.prompts.quality_check_prompts import (
    QUALITY_GATE_SYSTEM_PROMPT,
    build_quality_gate_prompt,
)
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.framework_package_service import FrameworkPackageService
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.scene_content_quality_signal_service import (
    SceneContentQualitySignalService,
)
from app.backend.services.tracing_service import traceable_operation
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
QUALITY_VERSION_ID = "quality_m9_001"
SHANGHAI_TZ = timezone(timedelta(hours=8))
SECRET_MARKERS = ["s" + "k-", "lsv2_pt", "API_KEY", "LANGSMITH", "DEEPSEEK"]
VALID_SCENE_CHARACTER_TIERS = {"A", "B", "C", "D"}
NON_STORY_PROSE_FAILURE_MARKERS = (
    "MODEL_FALLBACK_PLACEHOLDER",
    "External model output was not valid story prose",
    "diagnostic placeholder",
    "Failure summary:",
    "外部模型未能生成正式修订散文",
)
NON_STORY_PROSE_ERROR_MARKERS = (
    "Provider HTTP error",
    "ModelCallError",
    "model service call failed",
    "失败阶段摘要：",
)


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class QualityCheckService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        model_gateway: ModelGatewayService | None = None,
        framework_service: FrameworkPackageService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.project_file = self.data_dir / "project.json"
        self.world_canvas_file = self.data_dir / "world_canvas.json"
        self.characters_file = self.data_dir / "characters.json"
        self.relationships_file = self.data_dir / "relationships.json"
        self.chapters_file = self.data_dir / "chapters.json"
        self.scenes_file = self.data_dir / "scenes.json"
        self.quality_reports_file = self.data_dir / "quality_reports.json"
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_service = framework_service or FrameworkPackageService(
            store=self.store,
            data_dir=self.data_dir,
        )

    def _current_project_id(self, scene: Scene | None = None) -> str:
        if scene is not None and scene.project_id:
            return scene.project_id
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def get_current_quality_report(self) -> QualityCheckResponse:
        scene = self._find_current_scene()
        if scene is None:
            raise StorageError("QUALITY_TARGET_SCENE_MISSING: Current scene does not exist.")
        candidate = self._active_candidate(scene)
        if candidate is not None:
            report = self._find_latest_report("scene_revision", candidate.revision_id)
            if report is None:
                return self.check_scene_revision(scene.scene_id, candidate.revision_id)
            return QualityCheckResponse(
                success=True,
                report=report,
                embedded_report=to_embedded_scene_quality_report(report),
                target_type="scene_revision",
                target_id=candidate.revision_id,
            )

        report = self._find_latest_report("scene", scene.scene_id)
        if report is None:
            return self.check_scene_draft(scene.scene_id)
        return QualityCheckResponse(
            success=True,
            report=report,
            embedded_report=to_embedded_scene_quality_report(report),
            target_type="scene",
            target_id=scene.scene_id,
        )

    @traceable_operation("QualityCheckService.check_scene_draft", tags=["quality_check"])
    def check_scene_draft(self, scene_id: str) -> QualityCheckResponse:
        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("QUALITY_TARGET_SCENE_MISSING: Scene does not exist.")
        context = self.load_quality_context(scene)
        response = self.check_scene_object(scene, context=context, persist_scene=True)
        return response

    @traceable_operation("QualityCheckService.check_scene_revision", tags=["quality_check"])
    def check_scene_revision(
        self,
        scene_id: str,
        revision_id: str,
    ) -> QualityCheckResponse:
        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("QUALITY_TARGET_SCENE_MISSING: Scene does not exist.")
        candidate = self._find_revision_candidate(scene, revision_id)
        if candidate is None:
            raise StorageError(
                "QUALITY_TARGET_REVISION_MISSING: Scene revision candidate does not exist."
            )
        context = self.load_quality_context(scene)
        return self.check_revision_candidate_object(
            scene=scene,
            candidate=candidate,
            context=context,
            persist_scene=True,
        )

    def check_scene_object(
        self,
        scene: Scene,
        context: dict[str, Any] | None = None,
        persist_scene: bool = False,
    ) -> QualityCheckResponse:
        scene = self._normalize_scene_memory_scope(scene)
        context = context or self.load_quality_context(scene)
        report = self.run_quality_gate(
            target_type="scene",
            target_id=scene.scene_id,
            scene=scene,
            candidate=None,
            context=context,
        )
        self._append_report(report)
        embedded = to_embedded_scene_quality_report(report)
        if persist_scene:
            updated = Scene(
                **{
                    **model_to_dict(scene),
                    "quality_report": model_to_dict(embedded),
                    "quality_report_id": report.quality_report_id,
                    "updated_at": now_iso(),
                }
            )
            self._upsert_scene(updated)
        return QualityCheckResponse(
            success=True,
            report=report,
            embedded_report=embedded,
            target_type="scene",
            target_id=scene.scene_id,
        )

    def _normalize_scene_memory_scope(self, scene: Scene) -> Scene:
        visible_character_ids = self._visible_character_ids_from_scene_text(scene)
        if not visible_character_ids:
            return scene
        visible = set(visible_character_ids)
        extraction = model_to_dict(scene.memory_extraction)
        changed = False

        event_summary = []
        for event in extraction.get("event_summary") or []:
            if not isinstance(event, dict):
                event_summary.append(event)
                continue
            participants = self._unique_strings(
                [str(value) for value in event.get("participants") or [] if value]
            )
            filtered = [character_id for character_id in participants if character_id in visible]
            if participants and filtered != participants:
                event = {**event, "participants": filtered}
                changed = True
            event_summary.append(event)
        extraction["event_summary"] = event_summary

        memory_records = []
        for record in extraction.get("memory_records") or []:
            if not isinstance(record, dict):
                memory_records.append(record)
                continue
            source_character_id = str(record.get("source_object_id") or "")
            character_ids = self._unique_strings(
                [str(value) for value in record.get("character_ids") or [] if value]
            )
            if source_character_id in visible and character_ids != [source_character_id]:
                record = {**record, "character_ids": [source_character_id]}
                changed = True
            elif character_ids:
                filtered_ids = [
                    character_id for character_id in character_ids if character_id in visible
                ]
                if filtered_ids != character_ids:
                    record = {**record, "character_ids": filtered_ids}
                    changed = True
            memory_records.append(record)
        extraction["memory_records"] = memory_records

        if not changed:
            return scene
        return Scene(
            **{
                **model_to_dict(scene),
                "memory_extraction": model_to_dict(SceneMemoryExtraction(**extraction)),
                "updated_at": now_iso(),
            }
        )

    def _visible_character_ids_from_scene_text(self, scene: Scene) -> list[str]:
        candidate_ids = self._unique_strings(
            [
                *scene.linked_character_ids,
                *scene.character_context_ids,
                *[
                    str(character_id)
                    for event in scene.memory_extraction.event_summary
                    for character_id in (event.get("participants") or [])
                    if isinstance(event, dict)
                ],
            ]
        )
        if not candidate_ids:
            return []
        content = scene.content
        text = " ".join(
            str(value or "")
            for value in [
                getattr(content, "synopsis", ""),
                getattr(content, "prose_text", ""),
                scene.synopsis,
                scene.prose_text,
            ]
        )
        if not text.strip():
            return []
        characters_by_id = {
            character.character_id: character
            for character in self._read_characters()
            if character.character_id in candidate_ids
            and character.status == "confirmed"
            and not character.archived_at
        }
        visible: list[str] = []
        for character_id in candidate_ids:
            character = characters_by_id.get(character_id)
            if character is None:
                continue
            names = self._unique_strings(
                [
                    character.character_id,
                    character.name,
                    character.profile.identity,
                ]
            )
            if any(name and name in text for name in names):
                visible.append(character_id)
        return self._unique_strings(visible)

    def check_revision_candidate_object(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate,
        context: dict[str, Any] | None = None,
        persist_scene: bool = False,
    ) -> QualityCheckResponse:
        if candidate.scene_id != scene.scene_id:
            raise StorageError(
                "QUALITY_TARGET_INVALID: Revision candidate does not belong to scene."
            )
        context = context or self.load_quality_context(scene)
        report = self.run_quality_gate(
            target_type="scene_revision",
            target_id=candidate.revision_id,
            scene=scene,
            candidate=candidate,
            context=context,
        )
        self._append_report(report)
        embedded = to_embedded_scene_quality_report(report)
        if persist_scene:
            updated_history = []
            for item in scene.revision_history:
                if item.revision_id == candidate.revision_id:
                    updated_history.append(
                        SceneRevisionCandidate(
                            **{
                                **model_to_dict(item),
                                "quality_report": model_to_dict(embedded),
                                "quality_report_id": report.quality_report_id,
                                "requires_user_confirmation": (
                                    item.requires_user_confirmation
                                    or embedded.requires_user_confirmation
                                    or embedded.quality_degraded
                                    or embedded.semantic_check_status == "failed"
                                ),
                                "confirmation_gate": {
                                    "requires_user_confirmation": (
                                        item.requires_user_confirmation
                                        or embedded.requires_user_confirmation
                                        or embedded.quality_degraded
                                        or embedded.semantic_check_status == "failed"
                                    ),
                                    "quality_report_id": report.quality_report_id,
                                    "semantic_check_status": embedded.semantic_check_status,
                                    "quality_degraded": embedded.quality_degraded,
                                },
                                "updated_at": now_iso(),
                            }
                        )
                    )
                else:
                    updated_history.append(item)
            updated_scene = Scene(
                **{
                    **model_to_dict(scene),
                    "revision_history": [
                        model_to_dict(item) for item in updated_history
                    ],
                    "updated_at": now_iso(),
                }
            )
            self._upsert_scene(updated_scene)
        return QualityCheckResponse(
            success=True,
            report=report,
            embedded_report=embedded,
            target_type="scene_revision",
            target_id=candidate.revision_id,
        )

    def run_quality_gate(
        self,
        target_type: str,
        target_id: str,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
        context: dict[str, Any],
    ) -> QualityReport:
        rule_results = self._run_rule_checks(
            target_type=target_type,
            target_id=target_id,
            scene=scene,
            candidate=candidate,
            context=context,
        )
        semantic_result, semantic_status = self._run_semantic_check(
            target_type=target_type,
            target_id=target_id,
            scene=scene,
            candidate=candidate,
            context=context,
            rule_results=rule_results,
        )
        check_results = [*rule_results, semantic_result]
        if candidate is not None and candidate.force_hard_rule_override:
            check_results = self._downgrade_forced_hard_rule_blocks(check_results)
        issues = [
            issue
            for result in check_results
            for issue in result.issues
        ]
        warnings = [
            issue
            for issue in issues
            if issue.severity in {"warning", "needs_user_confirmation"}
        ]
        blocking_issues = [
            issue for issue in issues if issue.severity == "blocking"
        ]
        requires_user_confirmation = any(
            issue.severity == "needs_user_confirmation" for issue in issues
        )
        semantic_failed = semantic_status == "failed"
        if semantic_failed:
            requires_user_confirmation = True
        if candidate is not None:
            requires_user_confirmation = (
                requires_user_confirmation
                or candidate.requires_user_confirmation
                or candidate.force_hard_rule_override
            )
        report = QualityReport(
            quality_report_id=self._next_report_id(target_type, target_id),
            project_id=self._current_project_id(scene),
            target_type=target_type,
            target_id=target_id,
            scene_id=scene.scene_id,
            revision_id=candidate.revision_id if candidate else "",
            passed=len(blocking_issues) == 0,
            warnings=warnings,
            blocking_issues=blocking_issues,
            requires_user_confirmation=requires_user_confirmation,
            check_results=check_results,
            semantic_check_status=semantic_status,
            summary=self._quality_summary(blocking_issues, warnings, semantic_status),
            quality_degraded=semantic_failed,
            confirmation_block_reason=(
                "semantic_quality_unavailable" if semantic_failed else ""
            ),
            generated_by="quality_check_service",
            version_id=QUALITY_VERSION_ID,
            created_at=now_iso(),
        )
        return report

    def _downgrade_forced_hard_rule_blocks(
        self,
        check_results: list[QualityCheckResult],
    ) -> list[QualityCheckResult]:
        updated_results: list[QualityCheckResult] = []
        for result in check_results:
            updated_issues = []
            for issue in result.issues:
                if issue.category == "world_hard_rule" and issue.severity == "blocking":
                    updated_issues.append(
                        QualityIssue(
                            **{
                                **model_to_dict(issue),
                                "severity": "needs_user_confirmation",
                            }
                        )
                    )
                else:
                    updated_issues.append(issue)
            updated_results.append(
                QualityCheckResult(
                    **{
                        **model_to_dict(result),
                        "issues": [model_to_dict(item) for item in updated_issues],
                        "passed": not any(
                            item.severity == "blocking" for item in updated_issues
                        ),
                    }
                )
            )
        return updated_results

    def load_quality_context(self, scene: Scene) -> dict[str, Any]:
        world_canvas = self._try_read_world_canvas()
        chapters = self._read_chapters_if_present()
        chapter = self._find_chapter(scene.chapter_id, chapters)
        package = self._try_read_framework_package()
        framework = (
            self._find_built_chapter_framework(package, chapter)
            if package is not None and chapter is not None
            else None
        )
        return {
            "project_id": self._current_project_id(scene),
            "world_canvas": model_to_dict(world_canvas) if world_canvas else {},
            "characters": [
                model_to_dict(character)
                for character in self._read_characters()
                if character.status == "confirmed"
            ],
            "relationships": [
                model_to_dict(relationship)
                for relationship in self._read_relationships()
                if relationship.status == "confirmed"
            ],
            "chapter": model_to_dict(chapter) if chapter else {},
            "current_chapter_framework": (
                model_to_dict(framework) if framework else {}
            ),
            "framework_package": model_to_dict(package) if package else {},
        }

    def _run_rule_checks(
        self,
        target_type: str,
        target_id: str,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
        context: dict[str, Any],
    ) -> list[QualityCheckResult]:
        target = self._target_data(scene, candidate)
        content = target.get("content") or {}
        synopsis = str(content.get("synopsis") or target.get("synopsis") or "")
        prose_text = str(content.get("prose_text") or target.get("prose_text") or "")
        memory = target.get("memory_extraction") or {}
        trace = target.get("generation_trace") or model_to_dict(scene.generation_trace)
        ordered_package = trace.get("ordered_story_information_package") or {}
        results = [
            self._required_fields_check(
                target_type,
                target_id,
                scene,
                candidate,
                synopsis,
                prose_text,
                memory,
                trace,
            ),
            self._reference_integrity_check(scene, candidate, context),
            self._memory_check(target_type, target_id, memory, context),
            self._story_information_check(
                target_type,
                target_id,
                prose_text,
                trace,
                ordered_package,
            ),
            self._world_hard_rule_check(
                target_type,
                target_id,
                prose_text,
                candidate,
                context,
            ),
            self._character_motivation_check(target_type, target_id, prose_text, context),
            self._causal_completeness_check(target_type, target_id, prose_text, memory),
            self._chapter_framework_alignment_check(
                target_type,
                target_id,
                prose_text,
                context,
            ),
            self._content_quality_signal_check(
                target_type,
                target_id,
                scene,
                candidate,
                context,
            ),
        ]
        return results

    def _required_fields_check(
        self,
        target_type: str,
        target_id: str,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
        synopsis: str,
        prose_text: str,
        memory: dict[str, Any],
        trace: dict[str, Any],
    ) -> QualityCheckResult:
        issues: list[QualityIssue] = []
        if not scene.scene_id:
            issues.append(self._issue("schema_completeness", "blocking", "Scene.scene_id is missing.", target_type, target_id))
        if not scene.chapter_id:
            issues.append(self._issue("schema_completeness", "blocking", "Scene.chapter_id is missing.", target_type, target_id))
        if not synopsis.strip():
            issues.append(self._issue("schema_completeness", "blocking", "Scene synopsis is empty.", target_type, target_id))
        if not prose_text.strip():
            issues.append(self._issue("schema_completeness", "blocking", "Scene prose_text is empty.", target_type, target_id))
        if self._is_non_story_failure_prose(prose_text):
            issues.append(
                self._issue(
                    "prose_generation_failure",
                    "blocking",
                    (
                        "Scene prose_text contains diagnostic fallback/provider failure "
                        "text instead of story prose; regenerate the draft before release."
                    ),
                    target_type,
                    target_id,
                    suggested_repair_types=["revise_current_scene"],
                    technical_metadata={"affected_fields": ["prose_text"]},
                )
            )
        if not trace.get("story_information_list") and target_type == "scene":
            issues.append(self._issue("schema_completeness", "warning", "Scene generation trace story_information_list is missing.", target_type, target_id))
        if not memory:
            issues.append(self._issue("memory_extraction_completeness", "blocking", "Scene memory_extraction is missing.", target_type, target_id))
        if candidate is not None and candidate.scene_id != scene.scene_id:
            issues.append(self._issue("schema_completeness", "blocking", "Revision candidate belongs to a different scene.", target_type, target_id))
        return self._result("rule_required_fields", "Schema / Completeness", issues)

    def _is_non_story_failure_prose(self, prose_text: str) -> bool:
        text = str(prose_text or "")
        if not text.strip():
            return False
        if any(marker in text for marker in NON_STORY_PROSE_FAILURE_MARKERS):
            return True
        return "Failure summary:" in text and any(
            marker in text for marker in NON_STORY_PROSE_ERROR_MARKERS
        )

    def _reference_integrity_check(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
        context: dict[str, Any],
    ) -> QualityCheckResult:
        target_type = "scene_revision" if candidate else "scene"
        target_id = candidate.revision_id if candidate else scene.scene_id
        issues: list[QualityIssue] = []
        chapter = context.get("chapter") or {}
        if not chapter or chapter.get("chapter_id") != scene.chapter_id:
            issues.append(self._issue("reference_integrity", "blocking", "Current Chapter reference is missing or invalid.", target_type, target_id))
        framework = context.get("current_chapter_framework") or {}
        if not framework or framework.get("chapter_framework_id") != scene.linked_chapter_framework_id:
            issues.append(self._issue("reference_integrity", "blocking", "Current chapter framework reference is missing or invalid.", target_type, target_id))
        character_by_id = {
            character.get("character_id"): character
            for character in context.get("characters", [])
            if isinstance(character, dict)
        }
        for character_id in scene.linked_character_ids:
            character = character_by_id.get(character_id)
            if not character:
                issues.append(self._issue("reference_integrity", "blocking", f"Linked character does not exist: {character_id}", target_type, target_id))
                continue
            status = str(character.get("status") or "").strip()
            tier = str(character.get("tier") or "").strip().upper()
            if status != "confirmed":
                issues.append(self._issue("reference_integrity", "blocking", f"Linked character is not confirmed: {character_id}", target_type, target_id))
            elif tier not in VALID_SCENE_CHARACTER_TIERS:
                issues.append(self._issue("reference_integrity", "blocking", f"Linked character has invalid tier: {character_id}", target_type, target_id))
        return self._result("rule_reference_integrity", "Reference Integrity", issues)

    def _memory_check(
        self,
        target_type: str,
        target_id: str,
        memory: dict[str, Any],
        context: dict[str, Any],
    ) -> QualityCheckResult:
        issues: list[QualityIssue] = []
        if not memory:
            issues.append(self._issue("memory_extraction_completeness", "blocking", "Memory extraction is missing.", target_type, target_id))
            return self._result("rule_memory_extraction", "Memory Extraction Completeness", issues)
        if not memory.get("event_summary") and not memory.get("no_event_reason"):
            issues.append(self._issue("memory_extraction_completeness", "blocking", "Memory extraction has no event summary or no_event_reason.", target_type, target_id))
        for index, change in enumerate(memory.get("proposed_state_changes") or [], start=1):
            if isinstance(change, dict) and not self._state_change_target_id(change):
                issues.append(self._issue("memory_extraction_completeness", "blocking", f"State change #{index} is missing target_id.", target_type, target_id))
        relationship_ids = {
            relationship.get("relationship_id")
            for relationship in context.get("relationships", [])
            if isinstance(relationship, dict)
        }
        for change in memory.get("relationship_changes") or []:
            if isinstance(change, dict):
                relationship_id = change.get("relationship_id")
                if relationship_id and relationship_ids and relationship_id not in relationship_ids:
                    issues.append(self._issue("memory_extraction_completeness", "warning", f"Relationship change references unknown relationship: {relationship_id}", target_type, target_id))
        for index, record in enumerate(memory.get("memory_records") or [], start=1):
            if not isinstance(record, dict):
                continue
            object_type = record.get("object_type") or record.get("source_object_type")
            object_id = record.get("object_id") or record.get("source_object_id")
            if not object_type or not object_id or not record.get("summary"):
                issues.append(self._issue("memory_extraction_completeness", "blocking", f"Memory record #{index} is missing object_type, object_id, or summary.", target_type, target_id))
        return self._result("rule_memory_extraction", "Memory Extraction Completeness", issues)

    def _state_change_target_id(self, change: dict[str, Any]) -> str:
        return str(
            change.get("target_id")
            or change.get("character_id")
            or change.get("relationship_id")
            or change.get("scene_id")
            or ""
        ).strip()

    def _story_information_check(
        self,
        target_type: str,
        target_id: str,
        prose_text: str,
        trace: dict[str, Any],
        ordered_package: dict[str, Any],
    ) -> QualityCheckResult:
        issues: list[QualityIssue] = []
        if not ordered_package:
            issues.append(self._issue("story_information_coverage", "warning", "Ordered story information package is missing.", target_type, target_id))
        for item in ordered_package.get("do_not_include") or []:
            text = str(item).strip()
            if text and text in prose_text:
                issues.append(
                    self._issue(
                        "story_information_coverage",
                        "blocking",
                        "Scene prose includes do_not_use story information.",
                        target_type,
                        target_id,
                        evidence=self._safe_evidence(text),
                        suggested_action="rewrite_scene_prose_without_do_not_include",
                        suggested_repair_types=[
                            "rewrite_scene_prose",
                            "remove_do_not_include_content",
                        ],
                        technical_metadata={
                            "source": "ordered_story_information_package.do_not_include",
                        },
                    )
                )
        for reveal in ordered_package.get("required_reveals") or []:
            text = str(reveal).strip()
            if text and len(text) <= 80 and text not in prose_text:
                issues.append(self._issue("story_information_coverage", "warning", "Required reveal may not be represented in the prose.", target_type, target_id, evidence=self._safe_evidence(text)))
        must_use_items = [
            item.get("content")
            for item in trace.get("story_information_list") or []
            if isinstance(item, dict) and item.get("priority") == "must_use"
        ]
        for item in must_use_items:
            text = str(item or "").strip()
            if text and len(text) <= 80 and text not in prose_text:
                issues.append(self._issue("story_information_coverage", "warning", "Must-use story information may not be represented in the prose.", target_type, target_id, evidence=self._safe_evidence(text)))
        return self._result("rule_story_information", "Story Information Coverage", issues)

    def _world_hard_rule_check(
        self,
        target_type: str,
        target_id: str,
        prose_text: str,
        candidate: SceneRevisionCandidate | None,
        context: dict[str, Any],
    ) -> QualityCheckResult:
        issues: list[QualityIssue] = []
        hard_conflict = self._hard_rule_conflict_marker(prose_text)
        if candidate and candidate.hard_rule_warnings:
            severity = "needs_user_confirmation" if candidate.force_hard_rule_override else "blocking"
            for warning in candidate.hard_rule_warnings:
                issues.append(self._issue("world_hard_rule", severity, str(warning.get("summary") or "Revision candidate has hard-rule warning."), target_type, target_id, evidence=self._safe_evidence(warning.get("statement") or "")))
        elif hard_conflict:
            issues.append(self._issue("world_hard_rule", "blocking", "Scene appears to violate a World Canvas hard rule.", target_type, target_id, evidence=self._safe_evidence(hard_conflict)))
        for marker in SECRET_MARKERS:
            if marker in prose_text:
                issues.append(self._issue("schema_completeness", "blocking", "Target text contains a plaintext secret-like marker.", target_type, target_id))
                break
        return self._result("rule_world_hard_rule", "World Hard Rule", issues)

    def _hard_rule_conflict_marker(self, prose_text: str) -> str | None:
        lowered = prose_text.lower()
        for marker in [
            "hard-rule conflict",
            "ignore hard rule",
            "sun rises at noon",
            "daytime trigger",
            "free memory",
            "without cost",
        ]:
            start = 0
            while True:
                index = lowered.find(marker, start)
                if index < 0:
                    break
                if not self._has_english_negation_before(lowered, index):
                    return marker
                start = index + len(marker)
        for marker in ["无代价", "没有代价"]:
            start = 0
            while True:
                index = prose_text.find(marker, start)
                if index < 0:
                    break
                if not self._has_chinese_negation_before(prose_text, index):
                    return marker
                start = index + len(marker)
        return None

    def _has_english_negation_before(self, lowered_text: str, index: int) -> bool:
        prefix = lowered_text[max(0, index - 32):index]
        return any(
            negation in prefix
            for negation in [
                "not ",
                "never ",
                "is not ",
                "does not ",
                "do not ",
                "cannot ",
                "can't ",
                "isn't ",
            ]
        )

    def _has_chinese_negation_before(self, text: str, index: int) -> bool:
        prefix = text[max(0, index - 8):index]
        return any(
            negation in prefix
            for negation in [
                "并非",
                "并不是",
                "不是",
                "并不",
                "绝非",
                "不能",
                "不可",
                "不应",
            ]
        )

    def _character_motivation_check(
        self,
        target_type: str,
        target_id: str,
        prose_text: str,
        context: dict[str, Any],
    ) -> QualityCheckResult:
        issues: list[QualityIssue] = []
        for character in context.get("characters") or []:
            if not isinstance(character, dict):
                continue
            profile = character.get("profile") or {}
            for forbidden in profile.get("forbidden_knowledge") or []:
                text = str(forbidden).strip()
                if text and text in prose_text:
                    issues.append(self._issue("character_motivation", "blocking", f"Character appears to use forbidden knowledge: {character.get('name') or character.get('character_id')}", target_type, target_id, evidence=self._safe_evidence(text)))
            for hard_limit in profile.get("hard_limits") or []:
                statement = str((hard_limit or {}).get("statement") or "").strip()
                if statement and f"break hard limit:{statement}" in prose_text:
                    issues.append(self._issue("character_motivation", "blocking", "Character appears to break a hard limit.", target_type, target_id, evidence=self._safe_evidence(statement)))
        return self._result("rule_character_motivation", "Character Motivation", issues)

    def _causal_completeness_check(
        self,
        target_type: str,
        target_id: str,
        prose_text: str,
        memory: dict[str, Any],
    ) -> QualityCheckResult:
        issues: list[QualityIssue] = []
        lowered = prose_text.lower()
        if "impossible sudden knowledge" in lowered or "sudden knowledge" in lowered:
            issues.append(self._issue("causal_completeness", "warning", "Scene contains sudden knowledge without a visible source.", target_type, target_id))
        for event in memory.get("event_summary") or []:
            if isinstance(event, dict) and event.get("result") and not event.get("cause"):
                issues.append(self._issue("causal_completeness", "warning", "Event summary has an outcome without a visible cause.", target_type, target_id))
        return self._result("rule_causal_completeness", "Causal Completeness", issues)

    def _chapter_framework_alignment_check(
        self,
        target_type: str,
        target_id: str,
        prose_text: str,
        context: dict[str, Any],
    ) -> QualityCheckResult:
        issues: list[QualityIssue] = []
        if "framework mismatch" in prose_text.lower():
            issues.append(self._issue("framework_alignment", "warning", "Scene may not align with the current chapter framework.", target_type, target_id))
        chapter = context.get("chapter") or {}
        if chapter and "chapter goal mismatch" in prose_text.lower():
            issues.append(self._issue("chapter_goal_progress", "warning", "Scene may not advance the current chapter goal.", target_type, target_id, evidence=self._safe_evidence(chapter.get("chapter_goal") or chapter.get("summary") or "")))
        return self._result("rule_chapter_framework_alignment", "Chapter Goal / Framework Alignment", issues)

    def _content_quality_signal_check(
        self,
        target_type: str,
        target_id: str,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
        context: dict[str, Any],
    ) -> QualityCheckResult:
        signal_report = SceneContentQualitySignalService(
            store=self.store,
            data_dir=self.data_dir,
        ).evaluate_scene(
            scene=scene,
            candidate=candidate,
            project_id=str(context.get("project_id") or scene.project_id or ""),
        )
        issues = [
            QualityIssue(
                issue_id=(
                    f"issue_{signal.code}_"
                    f"{abs(hash((signal.code, target_id, signal.evidence_excerpt))) % 1000000:06d}"
                ),
                category=signal.code,
                severity=signal.severity,
                message=signal.code,
                evidence=self._safe_evidence(signal.evidence_excerpt),
                related_object_type=target_type,
                related_object_id=target_id,
                suggested_action="revise_or_regenerate_scene",
                user_visible=signal.user_visible,
                technical_summary=signal.technical_summary,
                source_refs=signal.source_refs,
                suggested_repair_types=signal.suggested_repair_types,
                technical_metadata=signal.technical_metadata,
            )
            for signal in signal_report.issues
        ]
        return self._result(
            "rule_content_quality_signal",
            "M6 Content Quality Signal",
            issues,
        )

    def _run_semantic_check(
        self,
        target_type: str,
        target_id: str,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
        context: dict[str, Any],
        rule_results: list[QualityCheckResult],
    ) -> tuple[QualityCheckResult, str]:
        status = self.model_gateway.validate_model_config()
        if not status.configured:
            return (
                QualityCheckResult(
                    check_id="semantic_llm_check",
                    check_name="Semantic LLM Quality Check",
                    passed=True,
                    status="skipped",
                    issues=[],
                    summary="Active model is not configured; semantic check was skipped. Rule checks still ran.",
                ),
                "skipped_model_unavailable",
            )
        schema_kind = (
            "quality_semantic_revision"
            if candidate is not None
            else "quality_semantic_scene"
        )
        semantic_context = {
            "target_type": target_type,
            "target_id": target_id,
            "scene": self._minimal_scene_context(scene),
            "candidate": model_to_dict(candidate) if candidate else None,
            "quality_context": self._minimal_quality_context(context),
            "rule_report_summary": [
                {
                    "check_id": result.check_id,
                    "passed": result.passed,
                    "issue_count": len(result.issues),
                }
                for result in rule_results
            ],
        }
        try:
            result = self.model_gateway.generate_json(
                messages=[
                    {"role": "system", "content": QUALITY_GATE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": build_quality_gate_prompt(
                            json.dumps(
                                semantic_context,
                                ensure_ascii=False,
                                indent=2,
                            )
                        ),
                    },
                ],
                schema_hint={
                    "kind": schema_kind,
                    "target_type": target_type,
                    "target_id": target_id,
                    "context": semantic_context,
                },
            )
        except (ModelCallError, ModelJsonParseError, StorageError) as exc:
            issue = self._issue(
                "semantic_quality",
                "warning",
                "Semantic quality check failed; rule checks still ran.",
                target_type,
                target_id,
                evidence=str(exc)[:120],
            )
            return (
                QualityCheckResult(
                    check_id="semantic_llm_check",
                    check_name="Semantic LLM Quality Check",
                    passed=True,
                    status="failed",
                    issues=[issue],
                    summary="Semantic check failed; rule checks still ran.",
                ),
                "failed",
            )
        issues = self._semantic_issues_from_output(result.data, target_type, target_id)
        return (
            QualityCheckResult(
                check_id="semantic_llm_check",
                check_name="Semantic LLM Quality Check",
                passed=not any(issue.severity == "blocking" for issue in issues),
                status="completed",
                issues=issues,
                summary=str(result.data.get("summary") or "Semantic check completed."),
            ),
            "completed",
        )

    def _semantic_issues_from_output(
        self,
        data: dict[str, Any],
        target_type: str,
        target_id: str,
    ) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for item in data.get("issues") or []:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "warning")
            if severity not in {"info", "warning", "blocking", "needs_user_confirmation"}:
                severity = "warning"
            issues.append(
                self._issue(
                    category=str(item.get("category") or "semantic_quality"),
                    severity=severity,
                    message=str(item.get("message") or "Semantic quality issue."),
                    related_object_type=target_type,
                    related_object_id=target_id,
                    evidence=self._safe_evidence(item.get("evidence") or ""),
                    suggested_action=str(item.get("suggested_action") or "") or None,
                )
            )
        return issues

    def _target_data(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
    ) -> dict[str, Any]:
        if candidate is None:
            return model_to_dict(scene)
        content = {
            "synopsis": candidate.revised_synopsis,
            "prose_text": candidate.revised_prose_text,
        }
        return {
            **model_to_dict(scene),
            "content": content,
            "synopsis": candidate.revised_synopsis,
            "prose_text": candidate.revised_prose_text,
            "memory_extraction": model_to_dict(candidate.memory_extraction),
        }

    def _issue(
        self,
        category: str,
        severity: str,
        message: str,
        related_object_type: str,
        related_object_id: str,
        evidence: str | None = None,
        suggested_action: str | None = None,
        suggested_repair_types: list[str] | None = None,
        technical_metadata: dict[str, Any] | None = None,
    ) -> QualityIssue:
        return QualityIssue(
            issue_id=f"issue_{category}_{abs(hash((category, severity, message, related_object_id))) % 1000000:06d}",
            category=category,
            severity=severity,
            message=message,
            evidence=evidence or None,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
            suggested_action=suggested_action,
            suggested_repair_types=suggested_repair_types or [],
            technical_metadata=technical_metadata or {},
            user_visible=True,
        )

    def _result(
        self,
        check_id: str,
        check_name: str,
        issues: list[QualityIssue],
    ) -> QualityCheckResult:
        return QualityCheckResult(
            check_id=check_id,
            check_name=check_name,
            passed=not any(issue.severity == "blocking" for issue in issues),
            status="completed",
            issues=issues,
            summary=f"{len(issues)} issue(s) found." if issues else "No rule issues found.",
        )

    def _quality_summary(
        self,
        blocking_issues: list[QualityIssue],
        warnings: list[QualityIssue],
        semantic_status: str,
    ) -> str:
        if blocking_issues:
            return f"Quality gate found {len(blocking_issues)} blocking issue(s). Semantic check: {semantic_status}."
        if warnings:
            return f"Quality gate passed with {len(warnings)} warning/confirmation issue(s). Semantic check: {semantic_status}."
        return f"Quality gate passed. Semantic check: {semantic_status}."

    def _next_report_id(self, target_type: str, target_id: str) -> str:
        prefix = "quality_revision" if target_type == "scene_revision" else "quality_scene"
        existing = [
            item
            for item in self._read_report_dicts()
            if item.get("target_type") == target_type and item.get("target_id") == target_id
        ]
        return f"{prefix}_{target_id}_{len(existing) + 1:03d}"

    def _append_report(self, report: QualityReport) -> None:
        reports = self._read_report_dicts()
        reports.append(model_to_dict(report))
        self.store.write(self.quality_reports_file, reports)

    def _find_latest_report(
        self,
        target_type: str,
        target_id: str,
    ) -> QualityReport | None:
        reports = [
            item
            for item in self._read_report_dicts()
            if item.get("target_type") == target_type and item.get("target_id") == target_id
        ]
        if not reports:
            return None
        try:
            return QualityReport(**reports[-1])
        except ValidationError as exc:
            raise StorageError("QualityReport JSON schema is invalid.") from exc

    def _read_report_dicts(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.quality_reports_file):
            return []
        return [
            dict(item)
            for item in self.store.read_list(self.quality_reports_file)
            if isinstance(item, dict)
        ]

    def _find_current_scene(self) -> Scene | None:
        chapters = self._read_chapters_if_present()
        chapter = self._select_current_chapter(chapters)
        if chapter is None:
            return None
        chapter_scenes = [
            scene for scene in self._read_scenes()
            if scene.chapter_id == chapter.chapter_id
        ]
        if not chapter_scenes:
            return None
        return sorted(
            chapter_scenes,
            key=lambda scene: (
                scene.scene_index,
                scene.updated_at or scene.created_at or "",
            ),
            reverse=True,
        )[0]

    def _find_scene_by_id(self, scene_id: str) -> Scene | None:
        for scene in self._read_scenes():
            if scene.scene_id == scene_id:
                return scene
        return None

    def _read_scenes(self) -> list[Scene]:
        if not self.store.exists(self.scenes_file):
            return []
        try:
            return [
                Scene(**item)
                for item in self.store.read_list(self.scenes_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("Scenes JSON schema is invalid.") from exc

    def _upsert_scene(self, scene: Scene) -> None:
        scenes = [
            model_to_dict(item)
            if isinstance(item, Scene)
            else dict(item)
            for item in self._read_list_if_present(self.scenes_file)
        ]
        scene_data = model_to_dict(scene)
        replaced = False
        updated = []
        for item in scenes:
            if item.get("scene_id") == scene.scene_id:
                updated.append(scene_data)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(scene_data)
        self.store.write(self.scenes_file, updated)

    def _unique_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _find_revision_candidate(
        self,
        scene: Scene,
        revision_id: str,
    ) -> SceneRevisionCandidate | None:
        for candidate in scene.revision_history:
            if candidate.revision_id == revision_id:
                return candidate
        return None

    def _active_candidate(self, scene: Scene) -> SceneRevisionCandidate | None:
        if not scene.active_revision_id:
            return None
        candidate = self._find_revision_candidate(scene, scene.active_revision_id)
        if candidate and candidate.status == "candidate":
            return candidate
        return None

    def _try_read_world_canvas(self) -> WorldCanvas | None:
        if not self.store.exists(self.world_canvas_file):
            return None
        try:
            return WorldCanvas(**self.store.read(self.world_canvas_file))
        except ValidationError as exc:
            raise StorageError("WorldCanvas JSON schema is invalid.") from exc

    def _read_characters(self) -> list[Character]:
        if not self.store.exists(self.characters_file):
            return []
        try:
            return [
                Character(**item)
                for item in self.store.read_list(self.characters_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("Characters JSON schema is invalid.") from exc

    def _read_relationships(self) -> list[Relationship]:
        if not self.store.exists(self.relationships_file):
            return []
        try:
            return [
                Relationship(**item)
                for item in self.store.read_list(self.relationships_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("Relationships JSON schema is invalid.") from exc

    def _read_chapters_if_present(self) -> list[Chapter]:
        if not self.store.exists(self.chapters_file):
            return []
        try:
            return [
                Chapter(**item)
                for item in self.store.read_list(self.chapters_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("Chapters JSON schema is invalid.") from exc

    def _select_current_chapter(
        self,
        chapters: list[Chapter],
    ) -> Chapter | None:
        for chapter in chapters:
            if chapter.detail_level == "current_chapter_brief":
                return chapter
        for chapter in chapters:
            if chapter.status == "active":
                return chapter
        for chapter in chapters:
            if chapter.chapter_framework_id and chapter.scene_count >= 1:
                return chapter
        return None

    def _find_chapter(
        self,
        chapter_id: str,
        chapters: list[Chapter],
    ) -> Chapter | None:
        for chapter in chapters:
            if chapter.chapter_id == chapter_id:
                return chapter
        return None

    def _try_read_framework_package(self) -> FrameworkPackage | None:
        if not self.store.exists(self.framework_package_file):
            return None
        try:
            return self.framework_service.get_framework_package()
        except StorageError:
            return None

    def _find_built_chapter_framework(
        self,
        package: FrameworkPackage,
        chapter: Chapter,
    ) -> ChapterFramework | None:
        for framework in package.built_chapter_frameworks:
            if framework.chapter_framework_id != chapter.chapter_framework_id:
                continue
            return framework
        return None

    def _read_list_if_present(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        return [
            dict(item)
            for item in self.store.read_list(path)
            if isinstance(item, dict)
        ]

    def _minimal_scene_context(self, scene: Scene) -> dict[str, Any]:
        return {
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "scene_index": scene.scene_index,
            "synopsis": scene.synopsis,
            "prose_text": scene.prose_text[:1200],
            "generation_trace": model_to_dict(scene.generation_trace),
            "memory_extraction": model_to_dict(scene.memory_extraction),
        }

    def _minimal_quality_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "world_hard_rules": (context.get("world_canvas") or {}).get("hard_rules") or [],
            "chapter": context.get("chapter") or {},
            "current_chapter_framework": context.get("current_chapter_framework") or {},
            "characters": [
                {
                    "character_id": character.get("character_id"),
                    "name": character.get("name"),
                    "current_state": character.get("current_state") or {},
                    "profile": {
                        "personality_baseline": (character.get("profile") or {}).get("personality_baseline") or {},
                        "hard_limits": (character.get("profile") or {}).get("hard_limits") or [],
                        "forbidden_knowledge": (character.get("profile") or {}).get("forbidden_knowledge") or [],
                    },
                }
                for character in context.get("characters", [])
                if isinstance(character, dict)
            ],
        }

    def _safe_evidence(self, value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        for marker in SECRET_MARKERS:
            if marker in text:
                return "[redacted-secret-marker]"
        return text[:200]
