from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.decision import Decision
from app.backend.models.memory_update_plan import MemoryUpdatePlan
from app.backend.models.modification_impact import (
    AffectedObjectRef,
    ModificationImpactChooseRequest,
    ModificationImpactPreview,
    ModificationImpactPreviewRequest,
    ModificationUserOption,
)
from app.backend.models.scene import Scene
from app.backend.models.scene_revision import SceneRevisionCandidate
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.memory_update_plan_service import MemoryUpdatePlanService
from app.backend.services.scene_revision_service import SceneRevisionService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
SECRET_MARKERS = ("sk-", "lsv2_")
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
    "prose_text",
    "prose text",
    "revised_prose_text",
    "revised prose text",
)
UNSAFE_KEYS = {
    "prompt",
    "raw_prompt",
    "raw_response",
    "hidden_reasoning",
    "internal_reasoning",
    "chain-of-thought",
    "chain_of_thought",
    "api_key",
    "api_key_ref",
    "prose_text",
    "revised_prose_text",
}


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class ModificationImpactService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        scene_revision_service: SceneRevisionService | None = None,
        memory_update_plan_service: MemoryUpdatePlanService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.scene_revision_service = scene_revision_service or SceneRevisionService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.memory_update_plan_service = (
            memory_update_plan_service
            or MemoryUpdatePlanService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.previews_file = self.data_dir / "modification_impact_previews.json"
        self.chapter_archives_file = self.data_dir / "chapter_archives.json"
        self.story_progress_file = self.data_dir / "story_progress.json"
        self.chapter_transitions_file = self.data_dir / "chapter_transitions.json"
        self.next_chapter_preparations_file = self.data_dir / "next_chapter_preparations.json"
        self.chapter_framework_build_contexts_file = (
            self.data_dir / "chapter_framework_build_contexts.json"
        )
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.chapter_plan_file = self.data_dir / "chapter_plan_draft.json"

    def create_preview(
        self,
        request: ModificationImpactPreviewRequest,
    ) -> ModificationImpactPreview:
        self._assert_safe_payload(
            model_to_dict(request),
            "modification_impact_request",
            allow_long_text=True,
        )
        source = self._resolve_source(request)
        source_scene = source.get("scene")
        source_archive = source.get("archive")
        source_candidate = source.get("candidate")
        source_dict = (
            source_archive
            or source.get("candidate_dict")
            or (model_to_dict(source_scene) if source_scene else {})
        )
        timestamp = now_iso()
        modification_summary = self._modification_summary(request)
        modification_hash_source = (
            request.modification_text
            or request.modification_summary
            or "; ".join(self._as_strings(request.change_summary))
            or modification_summary
        )
        preview = ModificationImpactPreview(
            preview_id=self._next_preview_id(),
            project_id=LOCAL_PROJECT_ID,
            source_object_type=request.source_object_type,
            source_object_id=request.source_object_id,
            source_status=str(source_dict.get("status") or source_dict.get("archive_status") or ""),
            source_summary=self._source_summary(source_dict, source_candidate),
            source_revision_id=str((source_candidate or {}).get("revision_id") or request.revision_id or ""),
            modification_source_type=request.modification_source_type,
            modification_summary=modification_summary,
            modification_hash=self._hash_text(modification_hash_source),
            affected_objects=self._affected_objects(
                source_object_type=request.source_object_type,
                source_dict=source_dict,
                scene=source_scene,
                archive=source_archive,
                candidate=source_candidate,
            ),
            dry_run_memory_plan_summary=self._dry_run_memory_plan_summary(
                source_scene,
                source_candidate,
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )
        preview = ModificationImpactPreview(
            **{
                **model_to_dict(preview),
                "impact_summary": self._impact_summary(preview.affected_objects),
                "warning_codes": self._warning_codes(preview),
                "warnings": self._warnings(preview),
                "recommended_options": [
                    model_to_dict(option)
                    for option in self._recommended_options(preview)
                ],
            }
        )
        self._assert_safe_payload(model_to_dict(preview), "modification_impact_preview")
        self._write_preview(preview)
        return preview

    def get_preview(self, preview_id: str) -> ModificationImpactPreview:
        for item in self._read_previews():
            if item.get("preview_id") != preview_id:
                continue
            try:
                return ModificationImpactPreview(**item)
            except ValidationError as exc:
                raise StorageError("ModificationImpactPreview JSON schema is invalid.") from exc
        raise StorageError("MODIFICATION_IMPACT_PREVIEW_MISSING: Preview does not exist.")

    def list_previews(
        self,
        *,
        source_object_type: str | None = None,
        source_object_id: str | None = None,
        status: str | None = None,
    ) -> list[ModificationImpactPreview]:
        result: list[ModificationImpactPreview] = []
        for item in self._read_previews():
            if source_object_type and item.get("source_object_type") != source_object_type:
                continue
            if source_object_id and item.get("source_object_id") != source_object_id:
                continue
            if status and item.get("status") != status:
                continue
            try:
                result.append(ModificationImpactPreview(**item))
            except ValidationError as exc:
                raise StorageError("ModificationImpactPreview JSON schema is invalid.") from exc
        return sorted(result, key=lambda item: item.updated_at or item.created_at, reverse=True)

    def choose_preview(
        self,
        preview_id: str,
        request: ModificationImpactChooseRequest,
    ) -> tuple[ModificationImpactPreview, Decision, dict[str, Any] | None, dict[str, Any] | None]:
        self._assert_safe_payload(
            model_to_dict(request),
            "modification_impact_choice_request",
            allow_long_text=True,
        )
        preview = self.get_preview(preview_id)
        option = next(
            (
                item
                for item in preview.recommended_options
                if item.action_type == request.action_type
            ),
            None,
        )
        if option is None:
            raise StorageError("MODIFICATION_IMPACT_OPTION_MISSING: Option is not available for this preview.")
        if not option.enabled:
            raise StorageError(
                f"MODIFICATION_IMPACT_OPTION_DISABLED: {option.disabled_reason or option.action_type}"
            )
        decision = self._write_decision(
            decision_type=request.action_type,
            target_id=preview.preview_id,
            user_input=(request.user_input or "").strip()
            or f"User selected {request.action_type} for modification impact preview.",
        )

        candidate: dict[str, Any] | None = None
        memory_plan: dict[str, Any] | None = None
        update: dict[str, Any] = {
            "chosen_action": request.action_type,
            "chosen_decision_id": decision.decision_id,
            "updated_at": now_iso(),
        }

        if request.action_type == "keep_current_change":
            update["status"] = "choice_recorded"
        elif request.action_type == "cancel_change":
            update["status"] = "rejected"
        elif request.action_type == "defer_to_phase4_premodify":
            update["status"] = "deferred_to_phase4"
        elif request.action_type == "declare_as_narrative_layer":
            update["status"] = "declared_as_narrative_layer"
        elif request.action_type == "rewrite_affected_current_scene":
            response = self.scene_revision_service.revise_scene(
                self._preview_scene_id(preview),
                revision_prompt=(request.revision_prompt or request.user_input or preview.modification_summary).strip(),
            )
            candidate = dict(response.candidate or {})
            update["status"] = "converted_to_revision_candidate"
            update["resulting_revision_id"] = str(candidate.get("revision_id") or "")
        elif request.action_type == "patch_local_memory":
            scene_id = self._preview_scene_id(preview)
            revision_id = preview.source_revision_id
            if not revision_id:
                raise StorageError(
                    "M6_MEMORY_PATCH_REQUIRES_REVISION_CANDIDATE: Local memory patch requires a revision candidate."
                )
            dry_run = self.memory_update_plan_service.create_plan_from_revision(
                scene_id=scene_id,
                revision_id=revision_id,
                dry_run=True,
            )
            if dry_run.status != "pending_user_confirmation":
                raise StorageError(
                    "M6_MEMORY_PATCH_DRY_RUN_NOT_CONFIRMABLE: Memory patch requires a pending_user_confirmation dry run."
                )
            persistent = self.memory_update_plan_service.create_plan_from_revision(
                scene_id=scene_id,
                revision_id=revision_id,
                dry_run=False,
            )
            if persistent.status != "pending_user_confirmation":
                raise StorageError(
                    "M6_MEMORY_PATCH_DRY_RUN_NOT_CONFIRMABLE: Persistent memory plan is not pending user confirmation."
                )
            memory_plan = model_to_dict(persistent)
            update["status"] = "memory_plan_pending"
            update["resulting_memory_plan_id"] = persistent.memory_update_plan_id

        updated = ModificationImpactPreview(**{**model_to_dict(preview), **update})
        self._assert_safe_payload(model_to_dict(updated), "modification_impact_preview")
        self._write_preview(updated)
        return updated, decision, candidate, memory_plan

    def debug_summary(self) -> dict[str, Any]:
        previews = self.list_previews()
        recent = previews[:8]
        status_counts: dict[str, int] = {}
        for preview in previews:
            status_counts[preview.status] = status_counts.get(preview.status, 0) + 1
        payload = {
            "available": True,
            "total": len(previews),
            "status_counts": status_counts,
            "recent_previews": [
                {
                    "preview_id": preview.preview_id,
                    "source_object_type": preview.source_object_type,
                    "source_object_id": preview.source_object_id,
                    "status": preview.status,
                    "chosen_action": preview.chosen_action,
                    "affected_count": len(preview.affected_objects),
                    "warning_codes": preview.warning_codes,
                    "modification_summary": self._short_text(preview.modification_summary, 180),
                    "updated_at": preview.updated_at,
                }
                for preview in recent
            ],
        }
        self._assert_safe_payload(payload, "modification_impact_debug")
        return payload

    def _resolve_source(self, request: ModificationImpactPreviewRequest) -> dict[str, Any]:
        if request.source_object_type in {"confirmed_scene", "scene_draft"}:
            scene = self._find_scene(request.source_object_id)
            if scene is None:
                raise StorageError("MODIFICATION_IMPACT_SOURCE_MISSING: Source scene does not exist.")
            if request.source_object_type == "confirmed_scene" and scene.status not in {
                "confirmed",
                "committed",
                "temporary_confirmed",
                "revised",
            }:
                raise StorageError("MODIFICATION_IMPACT_SOURCE_INVALID: Source scene is not confirmed.")
            if request.source_object_type == "scene_draft" and scene.status != "draft":
                raise StorageError("MODIFICATION_IMPACT_SOURCE_INVALID: scene_draft source must be an existing draft Scene.")
            return {"scene": scene}
        if request.source_object_type == "chapter_archive":
            archive = self._find_archive(request.source_object_id)
            if archive is None:
                raise StorageError("MODIFICATION_IMPACT_SOURCE_MISSING: Chapter archive does not exist.")
            return {"archive": archive}
        if request.source_object_type == "revision_candidate":
            scene, candidate = self._find_revision_candidate(
                request.source_object_id,
                request.revision_id,
            )
            if scene is None or candidate is None:
                raise StorageError("MODIFICATION_IMPACT_SOURCE_MISSING: Revision candidate does not exist.")
            return {
                "scene": scene,
                "candidate": model_to_dict(candidate),
                "candidate_dict": {
                    **model_to_dict(candidate),
                    "chapter_id": scene.chapter_id,
                    "scene_index": scene.scene_index,
                    "status": candidate.status,
                },
            }
        raise StorageError("MODIFICATION_IMPACT_SOURCE_INVALID: Source type is invalid.")

    def _affected_objects(
        self,
        *,
        source_object_type: str,
        source_dict: dict[str, Any],
        scene: Scene | None,
        archive: dict[str, Any] | None,
        candidate: dict[str, Any] | None,
    ) -> list[AffectedObjectRef]:
        refs: list[AffectedObjectRef] = []
        if scene is not None:
            refs.extend(self._scene_refs(scene, source_object_type == "scene_draft"))
        if archive is not None:
            refs.extend(self._archive_refs(archive))
        if candidate is not None and scene is not None:
            refs.extend(self._revision_candidate_refs(scene, candidate))
        return self._dedupe_refs(refs)

    def _scene_refs(self, scene: Scene, draft: bool) -> list[AffectedObjectRef]:
        scene_data = model_to_dict(scene)
        level = "low" if draft else "high"
        refs = [
            self._ref(
                object_type="scene",
                object_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                scene_id=scene.scene_id,
                status=scene.status,
                impact_area="current_scene",
                impact_level=level,
                relation="source_scene",
                reason="This is the scene being considered for modification.",
                summary=scene.synopsis or scene.goal,
            )
        ]
        memory_ids = self._scene_memory_ids(scene)
        for memory_id in memory_ids:
            refs.append(
                self._ref(
                    object_type="memory_record",
                    object_id=memory_id,
                    chapter_id=scene.chapter_id,
                    scene_id=scene.scene_id,
                    impact_area="memory",
                    impact_level="medium",
                    relation="scene_memory_ref",
                    reason="The scene uses or produced this memory reference.",
                )
            )
        refs.extend(self._memory_records_for_scene(scene.scene_id, scene.chapter_id))
        refs.extend(self._dependent_scene_refs(scene, memory_ids))
        refs.extend(self._archive_refs_for_scene(scene.scene_id, scene.chapter_id))
        refs.extend(self._story_progress_refs(scene.chapter_id, memory_ids))
        refs.extend(self._framework_refs(scene.chapter_id))
        refs.extend(self._memory_pack_refs(scene.scene_id, scene.chapter_id, memory_ids))
        refs.extend(self._narrative_refs(scene.scene_id, scene.chapter_id, memory_ids))
        return refs

    def _archive_refs(self, archive: dict[str, Any]) -> list[AffectedObjectRef]:
        archive_id = str(archive.get("archive_id") or "")
        chapter_id = str(archive.get("chapter_id") or "")
        refs = [
            self._ref(
                object_type="chapter_archive",
                object_id=archive_id,
                chapter_id=chapter_id,
                status=str(archive.get("archive_status") or ""),
                impact_area="chapter_archive",
                impact_level="high",
                relation="source_archive",
                reason="This archive is the source of the modification preview.",
                summary=archive.get("summary") or archive.get("outcome_summary", {}).get("user_visible_summary"),
            )
        ]
        scene_ids = self._as_strings(archive.get("scene_ids"))
        memory_ids = self._as_strings(archive.get("memory_refs")) + self._as_strings(
            archive.get("provisional_memory_ids")
        )
        for scene_id in scene_ids:
            refs.append(
                self._ref(
                    object_type="scene",
                    object_id=scene_id,
                    chapter_id=chapter_id,
                    scene_id=scene_id,
                    impact_area="archived_scene",
                    impact_level="high",
                    relation="archive_scene",
                    reason="This scene is included in the chapter archive.",
                )
            )
        for memory_id in memory_ids:
            refs.append(
                self._ref(
                    object_type="memory_record",
                    object_id=memory_id,
                    chapter_id=chapter_id,
                    impact_area="archive_memory",
                    impact_level="medium",
                    relation="archive_memory_ref",
                    reason="This memory is referenced by the chapter archive.",
                )
            )
        refs.extend(self._story_progress_refs(chapter_id, memory_ids, archive_id=archive_id))
        refs.extend(self._framework_refs(chapter_id, archive_id=archive_id))
        refs.extend(self._memory_pack_refs("", chapter_id, memory_ids))
        refs.extend(self._narrative_refs("", chapter_id, memory_ids))
        return refs

    def _revision_candidate_refs(
        self,
        scene: Scene,
        candidate: dict[str, Any],
    ) -> list[AffectedObjectRef]:
        revision_id = str(candidate.get("revision_id") or "")
        refs = [
            self._ref(
                object_type="scene_revision_candidate",
                object_id=revision_id,
                chapter_id=scene.chapter_id,
                scene_id=scene.scene_id,
                status=str(candidate.get("status") or ""),
                impact_area="revision_candidate",
                impact_level="high",
                relation="source_revision_candidate",
                reason="The modification targets a current scene revision candidate.",
                summary="; ".join(self._as_strings(candidate.get("change_summary"))) or candidate.get("revised_synopsis"),
            )
        ]
        for index, item in enumerate(candidate.get("possible_impacts") or [], start=1):
            if not isinstance(item, dict):
                continue
            refs.append(
                self._ref(
                    object_type=str(item.get("target_type") or "possible_impact"),
                    object_id=str(item.get("target_id") or f"{revision_id}_impact_{index:03d}"),
                    chapter_id=scene.chapter_id,
                    scene_id=scene.scene_id,
                    impact_area=str(item.get("impact_area") or "revision_possible_impact"),
                    impact_level=self._impact_level(item.get("impact_level") or "medium"),
                    relation="revision_possible_impact",
                    reason=str(item.get("reason") or "Revision candidate reported this possible impact."),
                    summary=item.get("summary"),
                )
            )
        dry_run = self._dry_run_memory_plan_summary(scene, candidate)
        for memory_id in self._as_strings(dry_run.get("superseded_memory_ids")):
            refs.append(
                self._ref(
                    object_type="memory_record",
                    object_id=memory_id,
                    chapter_id=scene.chapter_id,
                    scene_id=scene.scene_id,
                    impact_area="memory_sync",
                    impact_level="high",
                    relation="revision_memory_supersede",
                    reason="A dry-run memory plan would supersede this memory if explicitly created and later confirmed.",
                )
            )
        for scene_id in self._as_strings(dry_run.get("affected_scene_ids")):
            refs.append(
                self._ref(
                    object_type="scene",
                    object_id=scene_id,
                    chapter_id=scene.chapter_id,
                    scene_id=scene_id,
                    impact_area="future_scene_dependency",
                    impact_level="high",
                    relation="dry_run_dependent_scene",
                    reason="A dry-run memory plan reports this scene as dependent.",
                )
            )
        refs.extend(self._scene_refs(scene, False))
        return refs

    def _scene_memory_ids(self, scene: Scene) -> list[str]:
        extraction = scene.memory_extraction
        values = [
            *scene.input_memory_ids,
            *scene.event_ids,
            *scene.state_change_ids,
            *scene.depends_on_provisional_memory_ids,
        ]
        for memory in extraction.memory_records:
            if isinstance(memory, dict):
                values.append(memory.get("memory_id"))
        for event in extraction.event_summary:
            if isinstance(event, dict):
                values.append(event.get("event_id"))
        for change in extraction.proposed_state_changes:
            if isinstance(change, dict):
                values.append(change.get("state_change_id"))
        return self._unique_strings(values)

    def _memory_records_for_scene(
        self,
        scene_id: str,
        chapter_id: str,
    ) -> list[AffectedObjectRef]:
        refs: list[AffectedObjectRef] = []
        for memory in self.repositories.memory.list_all():
            if not self._record_mentions(memory, {scene_id}, {chapter_id}):
                continue
            refs.append(
                self._ref(
                    object_type="memory_record",
                    object_id=str(memory.get("memory_id") or ""),
                    chapter_id=str(memory.get("chapter_id") or chapter_id),
                    scene_id=str(memory.get("scene_id") or scene_id),
                    status=str(memory.get("status") or ""),
                    impact_area="memory",
                    impact_level="medium",
                    relation="persisted_memory_for_scene",
                    reason="Persisted memory references this scene or chapter.",
                    summary=memory.get("summary"),
                )
            )
        return refs

    def _dependent_scene_refs(
        self,
        scene: Scene,
        memory_ids: list[str],
    ) -> list[AffectedObjectRef]:
        refs: list[AffectedObjectRef] = []
        memory_set = set(memory_ids)
        for raw in self.repositories.scenes.list_all():
            scene_id = str(raw.get("scene_id") or "")
            if scene_id == scene.scene_id:
                continue
            if str(raw.get("chapter_id") or "") == scene.chapter_id and int(raw.get("scene_index") or 0) <= scene.scene_index:
                continue
            references_source = scene.scene_id in self._as_strings(raw.get("depends_on_provisional_scene_ids"))
            references_memory = bool(memory_set.intersection(self._as_strings(raw.get("input_memory_ids"))))
            references_provisional = bool(
                memory_set.intersection(self._as_strings(raw.get("depends_on_provisional_memory_ids")))
            )
            if not (references_source or references_memory or references_provisional):
                continue
            refs.append(
                self._ref(
                    object_type="scene",
                    object_id=scene_id,
                    chapter_id=str(raw.get("chapter_id") or ""),
                    scene_id=scene_id,
                    status=str(raw.get("status") or ""),
                    impact_area="future_scene_dependency",
                    impact_level="high",
                    relation="dependent_later_scene",
                    reason="A later scene references this scene or one of its memory ids.",
                    summary=raw.get("synopsis") or raw.get("goal"),
                )
            )
        return refs

    def _archive_refs_for_scene(
        self,
        scene_id: str,
        chapter_id: str,
    ) -> list[AffectedObjectRef]:
        refs: list[AffectedObjectRef] = []
        for archive in self._read_list_if_present(self.chapter_archives_file):
            if scene_id not in self._as_strings(archive.get("scene_ids")) and chapter_id != str(archive.get("chapter_id") or ""):
                continue
            refs.append(
                self._ref(
                    object_type="chapter_archive",
                    object_id=str(archive.get("archive_id") or ""),
                    chapter_id=str(archive.get("chapter_id") or chapter_id),
                    status=str(archive.get("archive_status") or ""),
                    impact_area="chapter_archive",
                    impact_level="high",
                    relation="archive_contains_or_summarizes_scene",
                    reason="A chapter archive contains or summarizes this scene.",
                    summary=archive.get("summary"),
                )
            )
        return refs

    def _story_progress_refs(
        self,
        chapter_id: str,
        memory_ids: list[str],
        *,
        archive_id: str = "",
    ) -> list[AffectedObjectRef]:
        refs: list[AffectedObjectRef] = []
        progress = self._read_dict_if_present(self.story_progress_file)
        if progress and (
            chapter_id in {
                str(progress.get("current_chapter_id") or ""),
                str(progress.get("next_chapter_id") or ""),
            }
            or archive_id
        ):
            refs.append(
                self._ref(
                    object_type="story_progress",
                    object_id=LOCAL_PROJECT_ID,
                    chapter_id=chapter_id,
                    status=str(progress.get("story_progress_status") or ""),
                    impact_area="story_progress",
                    impact_level="high",
                    relation="story_progress_current_or_next",
                    reason="Story progress may depend on the current chapter/archive state.",
                    summary=progress.get("next_recommended_action"),
                )
            )
        for transition in self._read_list_if_present(self.chapter_transitions_file):
            if archive_id and transition.get("from_archive_id") != archive_id:
                continue
            if not archive_id and chapter_id not in {
                str(transition.get("from_chapter_id") or ""),
                str(transition.get("to_chapter_id") or ""),
            }:
                continue
            refs.append(
                self._ref(
                    object_type="chapter_transition",
                    object_id=str(transition.get("transition_id") or ""),
                    chapter_id=chapter_id,
                    status=str(transition.get("transition_status") or ""),
                    impact_area="story_progress",
                    impact_level="high",
                    relation="chapter_transition_ref",
                    reason="A next-chapter transition references this chapter/archive.",
                )
            )
        for preparation in self._read_list_if_present(self.next_chapter_preparations_file):
            serialized = json.dumps(preparation, ensure_ascii=False, sort_keys=True)
            if archive_id and archive_id not in serialized:
                continue
            if not archive_id and chapter_id not in serialized and not any(memory_id in serialized for memory_id in memory_ids):
                continue
            refs.append(
                self._ref(
                    object_type="next_chapter_preparation",
                    object_id=str(preparation.get("preparation_id") or ""),
                    chapter_id=chapter_id,
                    status=str(preparation.get("preparation_status") or ""),
                    impact_area="story_progress",
                    impact_level="high",
                    relation="next_chapter_preparation_ref",
                    reason="A prepared next chapter references this chapter/archive/memory context.",
                )
            )
        return refs

    def _framework_refs(
        self,
        chapter_id: str,
        *,
        archive_id: str = "",
    ) -> list[AffectedObjectRef]:
        refs: list[AffectedObjectRef] = []
        for context in self._read_list_if_present(self.chapter_framework_build_contexts_file):
            serialized = json.dumps(context, ensure_ascii=False, sort_keys=True)
            if archive_id and archive_id not in serialized:
                continue
            if not archive_id and chapter_id and chapter_id not in serialized:
                continue
            refs.append(
                self._ref(
                    object_type="chapter_framework_build_context",
                    object_id=str(context.get("build_context_id") or ""),
                    chapter_id=str(context.get("chapter_id") or chapter_id),
                    impact_area="chapter_framework",
                    impact_level="medium",
                    relation="framework_context_ref",
                    reason="A chapter framework build context references this source.",
                    ref_ids=self._as_strings(context.get("linked_macro_component_ids")),
                )
            )
        package = self._read_dict_if_present(self.framework_package_file)
        if package:
            for assignment in package.get("chapter_macro_assignments") or []:
                if not isinstance(assignment, dict):
                    continue
                if chapter_id and str(assignment.get("chapter_id") or "") not in {"", chapter_id}:
                    continue
                refs.append(
                    self._ref(
                        object_type="framework_macro_mapping",
                        object_id=f"chapter_{assignment.get('chapter_index', '')}",
                        chapter_id=chapter_id,
                        impact_area="framework_macro",
                        impact_level="low",
                        relation="chapter_macro_assignment",
                        reason="Framework macro mapping may shape the affected chapter.",
                        ref_ids=self._as_strings(assignment.get("linked_macro_component_ids")),
                    )
                )
        return refs

    def _memory_pack_refs(
        self,
        scene_id: str,
        chapter_id: str,
        memory_ids: list[str],
    ) -> list[AffectedObjectRef]:
        refs: list[AffectedObjectRef] = []
        memory_set = set(memory_ids)
        for repository, object_type, id_field in [
            (self.repositories.chapter_memory_packs, "chapter_memory_pack", "chapter_memory_pack_id"),
            (self.repositories.scene_memory_packs, "scene_memory_pack", "scene_memory_pack_id"),
        ]:
            for pack in repository.list_packs():
                serialized = json.dumps(pack, ensure_ascii=False, sort_keys=True)
                if scene_id and scene_id not in serialized and chapter_id not in serialized and not memory_set.intersection(self._ids_in_text(serialized)):
                    continue
                if not scene_id and chapter_id not in serialized and not memory_set.intersection(self._ids_in_text(serialized)):
                    continue
                refs.append(
                    self._ref(
                        object_type=object_type,
                        object_id=str(pack.get(id_field) or ""),
                        chapter_id=str(pack.get("chapter_id") or chapter_id),
                        scene_id=str(pack.get("scene_id") or scene_id),
                        status=str(pack.get("status") or ""),
                        impact_area="memory_pack",
                        impact_level="medium",
                        relation="memory_pack_ref",
                        reason="A memory pack references this scene, chapter, or memory id.",
                    )
                )
        return refs

    def _narrative_refs(
        self,
        scene_id: str,
        chapter_id: str,
        memory_ids: list[str],
    ) -> list[AffectedObjectRef]:
        refs: list[AffectedObjectRef] = []
        repositories = [
            (self.repositories.claim_records, "claim_record", "claim_id"),
            (self.repositories.narrative_intent_records, "narrative_intent", "narrative_intent_id"),
            (self.repositories.perception_state_records, "perception_state", "perception_state_id"),
            (self.repositories.apparent_contradiction_records, "apparent_contradiction", "apparent_contradiction_id"),
            (self.repositories.narrative_debts, "narrative_debt", "narrative_debt_id"),
        ]
        for repository, object_type, id_field in repositories:
            for record in repository.list_all():
                if not self._record_mentions(record, {scene_id}, {chapter_id}, set(memory_ids)):
                    continue
                refs.append(
                    self._ref(
                        object_type=object_type,
                        object_id=str(record.get(id_field) or ""),
                        chapter_id=str(record.get("chapter_id") or chapter_id),
                        scene_id=str(record.get("scene_id") or record.get("source_scene_id") or scene_id),
                        status=str(record.get("status") or record.get("quality_gate_action") or ""),
                        impact_area="narrative_layer",
                        impact_level="medium",
                        relation="narrative_layer_ref",
                        reason="A narrative layer record references this source.",
                        summary=record.get("summary") or record.get("claim_text") or record.get("user_visible_summary"),
                    )
                )
        return refs

    def _dry_run_memory_plan_summary(
        self,
        scene: Scene | None,
        candidate: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if scene is None or not candidate:
            return {}
        revision_id = str(candidate.get("revision_id") or "")
        if not revision_id:
            return {}
        try:
            plan = self.memory_update_plan_service.create_plan_from_revision(
                scene_id=scene.scene_id,
                revision_id=revision_id,
                dry_run=True,
            )
        except Exception as exc:
            return {
                "available": False,
                "error_code": str(exc).split(":", 1)[0],
            }
        return self._plan_summary(plan)

    def _plan_summary(self, plan: MemoryUpdatePlan) -> dict[str, Any]:
        return {
            "available": True,
            "memory_update_plan_id": plan.memory_update_plan_id,
            "status": plan.status,
            "requires_user_confirmation": plan.requires_user_confirmation,
            "superseded_memory_ids": plan.superseded_memory_ids,
            "new_memory_count": len(plan.new_memory_records),
            "affected_scene_ids": plan.affected_scene_ids,
            "affected_memory_pack_ids": plan.affected_memory_pack_ids,
            "confirmation_reasons": [self._short_text(item, 180) for item in plan.confirmation_reasons],
            "user_facing_summary": self._short_text(plan.user_facing_summary, 240),
        }

    def _recommended_options(
        self,
        preview: ModificationImpactPreview,
    ) -> list[ModificationUserOption]:
        has_revision = bool(preview.source_revision_id)
        scene_id = self._preview_scene_id(preview, allow_missing=True)
        patch_disabled_reason = ""
        if not has_revision:
            patch_disabled_reason = "M6_MEMORY_PATCH_REQUIRES_REVISION_CANDIDATE"
        elif preview.dry_run_memory_plan_summary.get("status") != "pending_user_confirmation":
            patch_disabled_reason = "M6_MEMORY_PATCH_DRY_RUN_NOT_CONFIRMABLE"
        return [
            ModificationUserOption(
                option_id=f"{preview.preview_id}_keep",
                action_type="keep_current_change",
                label="Keep current change",
                enabled=True,
                recommended=True,
                expected_effect="Record the preview decision without mutating future scenes, archive, or memory.",
            ),
            ModificationUserOption(
                option_id=f"{preview.preview_id}_cancel",
                action_type="cancel_change",
                label="Cancel change",
                enabled=True,
                expected_effect="Mark this preview rejected. No story data is changed.",
            ),
            ModificationUserOption(
                option_id=f"{preview.preview_id}_defer",
                action_type="defer_to_phase4_premodify",
                label="Defer to Phase 4 pre-modify",
                enabled=True,
                expected_effect="Record that this should be handled by the full pre-modify flow later.",
            ),
            ModificationUserOption(
                option_id=f"{preview.preview_id}_rewrite",
                action_type="rewrite_affected_current_scene",
                label="Rewrite affected current scene",
                enabled=bool(scene_id),
                requires_user_input=True,
                requires_model_call=True,
                disabled_reason="" if scene_id else "M6_REWRITE_REQUIRES_SCENE_SOURCE",
                expected_effect="Create a scene revision candidate only. It will not be confirmed or synced automatically.",
            ),
            ModificationUserOption(
                option_id=f"{preview.preview_id}_memory",
                action_type="patch_local_memory",
                label="Patch local memory",
                enabled=not patch_disabled_reason,
                requires_user_input=True,
                disabled_reason=patch_disabled_reason,
                warning_codes=[patch_disabled_reason] if patch_disabled_reason else [],
                expected_effect="Create a pending memory update plan from an existing revision candidate. It will not apply.",
            ),
            ModificationUserOption(
                option_id=f"{preview.preview_id}_narrative",
                action_type="declare_as_narrative_layer",
                label="Declare as narrative layer",
                enabled=True,
                requires_user_input=True,
                expected_effect="Record a Decision only in M6 v1. It does not write objective facts.",
            ),
        ]

    def _impact_summary(self, refs: list[AffectedObjectRef]) -> list[str]:
        counts: dict[str, int] = {}
        high = 0
        for ref in refs:
            counts[ref.impact_area] = counts.get(ref.impact_area, 0) + 1
            if ref.impact_level == "high":
                high += 1
        result = [
            f"{area}: {count}"
            for area, count in sorted(counts.items())
        ]
        if high:
            result.insert(0, f"high impact refs: {high}")
        return result

    def _warning_codes(self, preview: ModificationImpactPreview) -> list[str]:
        codes: list[str] = []
        if any(ref.impact_area == "future_scene_dependency" for ref in preview.affected_objects):
            codes.append("M6_FUTURE_SCENE_DEPENDENCY_PRESENT")
        if any(ref.object_type == "chapter_archive" for ref in preview.affected_objects):
            codes.append("M6_ARCHIVE_REFERENCE_PRESENT")
        if any(ref.impact_area == "story_progress" for ref in preview.affected_objects):
            codes.append("M6_STORY_PROGRESS_REFERENCE_PRESENT")
        if not preview.source_revision_id:
            codes.append("M6_MEMORY_PATCH_REQUIRES_REVISION_CANDIDATE")
        return self._unique_strings(codes)

    def _warnings(self, preview: ModificationImpactPreview) -> list[str]:
        text = {
            "M6_FUTURE_SCENE_DEPENDENCY_PRESENT": "Later scenes or preparations may depend on this source. M6 preview will not mutate them.",
            "M6_ARCHIVE_REFERENCE_PRESENT": "A chapter archive references this source. M6 preview will not rewrite archives.",
            "M6_STORY_PROGRESS_REFERENCE_PRESENT": "Story progress or next-chapter preparation references this source. M6 preview will not rewrite it.",
            "M6_MEMORY_PATCH_REQUIRES_REVISION_CANDIDATE": "Local memory patch is disabled until a revision candidate exists.",
        }
        return [text[code] for code in preview.warning_codes if code in text]

    def _write_decision(
        self,
        *,
        decision_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        self._assert_safe_payload(
            {
                "decision_type": decision_type,
                "target_id": target_id,
                "user_input": user_input,
            },
            "modification_impact_decision_input",
            allow_long_text=True,
        )
        decisions = self.repositories.decisions.list_all()
        decision = Decision(
            decision_id=f"decision_modification_impact_{len(decisions) + 1:03d}",
            decision_type=decision_type,
            target_type="modification_impact_preview",
            target_id=target_id,
            user_input=self._short_text(user_input, 420),
            created_at=now_iso(),
        )
        decision_data = model_to_dict(decision)
        self._assert_safe_payload(decision_data, "modification_impact_decision")
        decisions.append(decision_data)
        self._assert_safe_payload(decisions, "modification_impact_decisions")
        self.repositories.decisions.write_all(decisions)
        return decision

    def _write_preview(self, preview: ModificationImpactPreview) -> None:
        records = self._read_previews()
        updated: list[dict[str, Any]] = []
        replaced = False
        preview_data = model_to_dict(preview)
        for item in records:
            if item.get("preview_id") == preview.preview_id:
                updated.append(preview_data)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(preview_data)
        self._assert_safe_payload(updated, "modification_impact_previews")
        self.store.write(self.previews_file, updated)

    def _read_previews(self) -> list[dict[str, Any]]:
        return self._read_list_if_present(self.previews_file)

    def _next_preview_id(self) -> str:
        return f"modification_impact_preview_{len(self._read_previews()) + 1:03d}"

    def _find_scene(self, scene_id: str) -> Scene | None:
        raw = self.repositories.scenes.get_by_id(scene_id)
        if raw is None:
            return None
        try:
            return Scene(**raw)
        except ValidationError as exc:
            raise StorageError("Scene JSON schema is invalid.") from exc

    def _find_archive(self, archive_id: str) -> dict[str, Any] | None:
        for archive in self._read_list_if_present(self.chapter_archives_file):
            if str(archive.get("archive_id") or "") == archive_id:
                return archive
        return None

    def _find_revision_candidate(
        self,
        scene_id: str,
        revision_id: str | None = None,
    ) -> tuple[Scene | None, SceneRevisionCandidate | None]:
        scene = self._find_scene(scene_id)
        if scene is None:
            return None, None
        candidate_id = revision_id or scene.active_revision_id
        if not candidate_id:
            return scene, None
        for candidate in scene.revision_history:
            if candidate.revision_id == candidate_id:
                return scene, candidate
        return scene, None

    def _preview_scene_id(
        self,
        preview: ModificationImpactPreview,
        *,
        allow_missing: bool = False,
    ) -> str:
        if preview.source_object_type in {"confirmed_scene", "scene_draft", "revision_candidate"}:
            return preview.source_object_id
        for ref in preview.affected_objects:
            if ref.object_type == "scene" and ref.scene_id:
                return ref.scene_id
        if allow_missing:
            return ""
        raise StorageError("M6_REWRITE_REQUIRES_SCENE_SOURCE: Preview does not have a scene source.")

    def _source_summary(
        self,
        source: dict[str, Any],
        candidate: dict[str, Any] | None = None,
    ) -> str:
        if candidate:
            return self._short_text("; ".join(self._as_strings(candidate.get("change_summary"))) or candidate.get("revised_synopsis"), 360)
        if "outcome_summary" in source and isinstance(source.get("outcome_summary"), dict):
            return self._short_text(
                source.get("outcome_summary", {}).get("user_visible_summary")
                or source.get("summary"),
                360,
            )
        content = source.get("content") if isinstance(source.get("content"), dict) else {}
        return self._short_text(
            source.get("synopsis")
            or content.get("synopsis")
            or source.get("goal")
            or source.get("summary"),
            360,
        )

    def _modification_summary(
        self,
        request: ModificationImpactPreviewRequest,
    ) -> str:
        return "User modification intent received; full text was not persisted."

    def _ref(self, **kwargs: Any) -> AffectedObjectRef:
        data = dict(kwargs)
        data["object_id"] = self._safe_id_text(data.get("object_id"))
        data["summary"] = self._short_text(data.get("summary"), 240)
        data["reason"] = self._short_text(data.get("reason"), 260)
        data["ref_ids"] = self._unique_strings(data.get("ref_ids") or [])
        data["impact_level"] = self._impact_level(data.get("impact_level") or "medium")
        return AffectedObjectRef(**data)

    def _impact_level(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"low", "medium", "high"} else "medium"

    def _dedupe_refs(self, refs: list[AffectedObjectRef]) -> list[AffectedObjectRef]:
        result: list[AffectedObjectRef] = []
        seen: set[tuple[str, str, str]] = set()
        for ref in refs:
            if not ref.object_id:
                continue
            key = (ref.object_type, ref.object_id, ref.relation)
            if key in seen:
                continue
            seen.add(key)
            result.append(ref)
        return result

    def _record_mentions(
        self,
        record: dict[str, Any],
        scene_ids: set[str],
        chapter_ids: set[str],
        memory_ids: set[str] | None = None,
    ) -> bool:
        memory_ids = memory_ids or set()
        direct_scene = {
            str(record.get("scene_id") or ""),
            str(record.get("source_scene_id") or ""),
            str(record.get("target_scene_id") or ""),
        }
        direct_chapter = {
            str(record.get("chapter_id") or ""),
            str(record.get("source_chapter_id") or ""),
        }
        if scene_ids.intersection(direct_scene - {""}):
            return True
        if chapter_ids.intersection(direct_chapter - {""}):
            return True
        if memory_ids:
            serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
            return any(memory_id and memory_id in serialized for memory_id in memory_ids)
        return False

    def _ids_in_text(self, text: str) -> set[str]:
        return set(re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{3,}", text or ""))

    def _read_list_if_present(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        return [
            dict(item)
            for item in self.store.read_list(path)
            if isinstance(item, dict)
        ]

    def _read_dict_if_present(self, path: Path) -> dict[str, Any]:
        if not self.store.exists(path):
            return {}
        data = self.store.read_any(path)
        return dict(data) if isinstance(data, dict) else {}

    def _as_strings(self, value: Any) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        return [
            str(item).strip()
            for item in values
            if str(item or "").strip()
        ]

    def _unique_strings(self, values: list[Any]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    def _safe_id_text(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return re.sub(r"[^A-Za-z0-9_.:-]", "_", text)[:160]

    def _short_text(self, value: Any, limit: int = 200) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        compact = " ".join(text.split())
        return compact[:limit]

    def _hash_text(self, value: str) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]

    def _assert_safe_payload(
        self,
        value: Any,
        path: str,
        *,
        allow_long_text: bool = False,
    ) -> None:
        issues = self._unsafe_payload_issues(
            value,
            path,
            allow_long_text=allow_long_text,
        )
        if issues:
            raise StorageError(
                "MODIFICATION_IMPACT_UNSAFE_PAYLOAD_BLOCKED: "
                + "; ".join(issues[:5])
            )

    def _unsafe_payload_issues(
        self,
        value: Any,
        path: str,
        *,
        allow_long_text: bool = False,
    ) -> list[str]:
        issues: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                key_lower = key_text.lower()
                child_path = f"{path}.{key_text}"
                if key_lower in UNSAFE_KEYS:
                    issues.append(f"unsafe_key:{child_path}")
                    continue
                issues.extend(
                    self._unsafe_payload_issues(
                        item,
                        child_path,
                        allow_long_text=allow_long_text,
                    )
                )
            return issues
        if isinstance(value, list):
            for index, item in enumerate(value):
                issues.extend(
                    self._unsafe_payload_issues(
                        item,
                        f"{path}[{index}]",
                        allow_long_text=allow_long_text,
                    )
                )
            return issues
        if isinstance(value, str):
            lowered = value.lower()
            if any(marker in lowered for marker in SECRET_MARKERS):
                issues.append(f"secret_value:{path}")
            if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                issues.append(f"unsafe_value:{path}")
            if not allow_long_text and len(value) > 1400:
                issues.append(f"text_too_long:{path}")
        return issues
