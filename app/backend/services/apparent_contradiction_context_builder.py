from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.apparent_contradiction import ApparentContradictionContext
from app.backend.models.continuity import ContinuityIssue
from app.backend.models.narrative_layer import NarrativeObjectReference
from app.backend.models.scene import Scene
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.narrative_layer_service import NarrativeLayerService
from app.backend.storage.json_store import JsonStore


class ApparentContradictionContextBuilder:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        narrative_layer_service: NarrativeLayerService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.narrative_layer_service = narrative_layer_service or NarrativeLayerService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def build(
        self,
        *,
        continuity_context: dict[str, Any],
        issues: list[ContinuityIssue],
    ) -> ApparentContradictionContext:
        scene = continuity_context.get("scene")
        if isinstance(scene, dict):
            scene = Scene(**scene)
        if not isinstance(scene, Scene):
            scene = None
        scene_id = str(continuity_context.get("scene_id") or "")
        chapter_id = str(continuity_context.get("chapter_id") or "")
        target_type = str(continuity_context.get("target_type") or "scene")
        target_id = str(continuity_context.get("target_id") or scene_id)
        generation_trace_id = ""
        if scene is not None:
            generation_trace_id = scene.generation_trace.generation_trace_id
        candidate = continuity_context.get("candidate")
        if candidate is not None and hasattr(candidate, "revision_id"):
            target_id = str(candidate.revision_id or target_id)

        scene_records = self.narrative_layer_service.get_scene_records(scene_id)
        existing_contradictions = [
            record
            for record in self.narrative_layer_service.list_apparent_contradictions()
            if record.scene_id == scene_id
            or record.source_issue_id in {issue.issue_id for issue in issues}
        ]
        debts = self.narrative_layer_service.list_debts(scene_id=scene_id)
        objective_refs = self._objective_refs(continuity_context)
        return ApparentContradictionContext(
            scene_id=scene_id,
            chapter_id=chapter_id,
            target_type=target_type,
            target_id=target_id,
            revision_id=str(continuity_context.get("revision_id") or ""),
            generation_trace_id=generation_trace_id,
            issues=issues,
            claim_records=scene_records.claim_records,
            perception_records=scene_records.perception_state_records,
            psychology_traces=scene_records.character_psychology_traces,
            expression_records=scene_records.character_expression_records,
            narrative_intents=scene_records.narrative_intent_records,
            narrative_debts=debts,
            existing_apparent_contradictions=existing_contradictions,
            user_decisions=self._decision_refs(continuity_context),
            objective_refs=objective_refs,
            safe_scene_summary=self._safe_scene_summary(continuity_context, scene),
        )

    def _objective_refs(
        self,
        continuity_context: dict[str, Any],
    ) -> list[NarrativeObjectReference]:
        refs: list[NarrativeObjectReference] = []
        for issue in continuity_context.get("source_memory_ids") or []:
            refs.append(
                NarrativeObjectReference(
                    object_type="memory_record",
                    object_id=str(issue),
                    relation="continuity source memory",
                )
            )
        for event in continuity_context.get("events") or []:
            if isinstance(event, dict) and event.get("event_id"):
                refs.append(
                    NarrativeObjectReference(
                        object_type="event",
                        object_id=str(event.get("event_id") or ""),
                        relation="objective event",
                    )
                )
        for memory in continuity_context.get("memory_records") or []:
            if isinstance(memory, dict) and memory.get("memory_id"):
                refs.append(
                    NarrativeObjectReference(
                        object_type="memory_record",
                        object_id=str(memory.get("memory_id") or ""),
                        relation="objective memory",
                    )
                )
        return _unique_refs(refs)

    def _decision_refs(
        self,
        continuity_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        scene_id = str(continuity_context.get("scene_id") or "")
        target_id = str(continuity_context.get("target_id") or "")
        result: list[dict[str, Any]] = []
        for decision in self.repositories.decisions.list_all():
            if not isinstance(decision, dict):
                continue
            decision_target = str(decision.get("target_id") or "")
            if decision_target not in {scene_id, target_id}:
                continue
            result.append(
                {
                    "decision_id": decision.get("decision_id", ""),
                    "decision_type": decision.get("decision_type", ""),
                    "target_type": decision.get("target_type", ""),
                    "target_id": decision_target,
                    "created_at": decision.get("created_at", ""),
                }
            )
        return result

    def _safe_scene_summary(
        self,
        continuity_context: dict[str, Any],
        scene: Scene | None,
    ) -> str:
        summary = str(continuity_context.get("target_text_excerpt") or "").strip()
        if not summary and scene is not None:
            summary = scene.synopsis or scene.goal or ""
        return _short_text(summary, 220)


def _short_text(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}..."


def _unique_refs(
    refs: list[NarrativeObjectReference],
) -> list[NarrativeObjectReference]:
    result: list[NarrativeObjectReference] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in refs:
        identity = (ref.object_type, ref.object_id, ref.relation)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(ref)
    return result


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()
