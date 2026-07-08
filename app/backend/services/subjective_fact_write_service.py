import re
from pathlib import Path

from app.backend.core.config import settings
from app.backend.models.narrative_layer import (
    CharacterExpressionRecord,
    CharacterPsychologyTrace,
    ClaimRecord,
    PerceptionStateRecord,
)
from app.backend.models.subjective_fact import (
    SubjectiveFactExtractionResult,
    SubjectiveFactWriteResult,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.narrative_layer_service import NarrativeLayerService
from app.backend.storage.json_store import JsonStore


class SubjectiveFactWriteService:
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

    def write_from_extraction(
        self,
        extraction: SubjectiveFactExtractionResult,
        *,
        status: str = "active",
        project_id: str | None = None,
    ) -> SubjectiveFactWriteResult:
        active_project_id = str(project_id or "").strip() or self._current_project_id()
        claim_id_by_candidate: dict[str, str] = {}
        psychology_id_by_candidate: dict[str, str] = {}
        expression_id_by_candidate: dict[str, str] = {}
        warnings = list(extraction.warnings)

        for candidate in extraction.psychology_trace_candidates:
            record_id = _record_id(
                "psy",
                extraction.scene_id,
                candidate.candidate_id,
            )
            record = self.narrative_layer_service.create_psychology_trace(
                CharacterPsychologyTrace(
                    psychology_trace_id=record_id,
                    project_id=active_project_id,
                    chapter_id=candidate.chapter_id or extraction.chapter_id,
                    scene_id=candidate.scene_id or extraction.scene_id,
                    status=status,
                    character_id=candidate.character_id,
                    surface_intention=candidate.surface_intention,
                    inner_desire=candidate.inner_desire,
                    fear=candidate.fear,
                    self_deception=candidate.self_deception,
                    suppressed_motive=candidate.suppressed_motive,
                    psychological_pressure=candidate.psychological_pressure,
                    action_tendency=candidate.action_tendency,
                    interpretation_status="candidate",
                    confidence=candidate.confidence,
                    reader_visible_level="hidden",
                    source_narrative_intent_id=(
                        candidate.source_narrative_intent_id
                        or _first(extraction.source_narrative_intent_ids)
                    ),
                    linked_refs=candidate.source_refs,
                )
            )
            psychology_id_by_candidate[candidate.candidate_id] = record.psychology_trace_id

        for candidate in extraction.claim_candidates:
            record_id = _record_id(
                "claim",
                extraction.scene_id,
                candidate.candidate_id,
            )
            record = self.narrative_layer_service.create_claim(
                ClaimRecord(
                    claim_id=record_id,
                    project_id=active_project_id,
                    chapter_id=candidate.chapter_id or extraction.chapter_id,
                    scene_id=candidate.scene_id or extraction.scene_id,
                    status=status,
                    character_id=candidate.character_id,
                    claim_text=candidate.claim_text,
                    truth_status=candidate.truth_status,
                    objective_truth=candidate.objective_truth,
                    reader_visible=candidate.reader_visible,
                    speaker_intent=candidate.speaker_intent,
                    source_expression_record_id="",
                    objective_source_refs=[],
                )
            )
            claim_id_by_candidate[candidate.candidate_id] = record.claim_id

        for candidate in extraction.expression_record_candidates:
            record_id = _record_id(
                "expr",
                extraction.scene_id,
                candidate.candidate_id,
            )
            spoken_claim_ids = [
                claim_id_by_candidate[claim_candidate_id]
                for claim_candidate_id in candidate.spoken_claim_candidate_ids
                if claim_candidate_id in claim_id_by_candidate
            ]
            psychology_trace_id = psychology_id_by_candidate.get(
                candidate.psychology_candidate_id,
                "",
            )
            record = self.narrative_layer_service.create_expression_record(
                CharacterExpressionRecord(
                    expression_record_id=record_id,
                    project_id=active_project_id,
                    chapter_id=candidate.chapter_id or extraction.chapter_id,
                    scene_id=candidate.scene_id or extraction.scene_id,
                    status=status,
                    character_id=candidate.character_id,
                    psychology_trace_id=psychology_trace_id,
                    spoken_claim_ids=spoken_claim_ids,
                    actual_action=candidate.actual_action,
                    external_behavior=candidate.external_behavior,
                    silence_or_omission=candidate.silence_or_omission,
                    deception_or_concealment=candidate.deception_or_concealment,
                    reader_inference_hint=candidate.reader_inference_hint,
                    linked_refs=candidate.source_refs,
                )
            )
            expression_id_by_candidate[candidate.candidate_id] = record.expression_record_id

        for candidate in extraction.claim_candidates:
            if not candidate.source_expression_candidate_id:
                continue
            claim_id = claim_id_by_candidate.get(candidate.candidate_id)
            expression_id = expression_id_by_candidate.get(
                candidate.source_expression_candidate_id
            )
            if not claim_id or not expression_id:
                continue
            self.narrative_layer_service.update_claim(
                claim_id,
                {"source_expression_record_id": expression_id},
            )

        perception_ids: list[str] = []
        for candidate in extraction.perception_candidates:
            record_id = _record_id(
                "perception",
                extraction.scene_id,
                candidate.candidate_id,
            )
            record = self.narrative_layer_service.create_perception_state(
                PerceptionStateRecord(
                    perception_state_id=record_id,
                    project_id=active_project_id,
                    chapter_id=candidate.chapter_id or extraction.chapter_id,
                    scene_id=candidate.scene_id or extraction.scene_id,
                    status=status,
                    character_id=candidate.character_id,
                    perceived_object_type=candidate.perceived_object_type,
                    perceived_object_id=candidate.perceived_object_id,
                    objective_state_summary=candidate.objective_state_summary,
                    perceived_state_summary=candidate.perceived_state_summary,
                    perception_type=candidate.perception_type,
                    reader_explanation_policy=candidate.reader_explanation_policy,
                    linked_narrative_intent_id=(
                        candidate.linked_narrative_intent_id
                        or _first(extraction.source_narrative_intent_ids)
                    ),
                    perceived_state_refs=candidate.source_refs,
                )
            )
            perception_ids.append(record.perception_state_id)

        return SubjectiveFactWriteResult(
            scene_id=extraction.scene_id,
            chapter_id=extraction.chapter_id,
            generation_trace_id=extraction.generation_trace_id,
            claim_record_ids=list(claim_id_by_candidate.values()),
            perception_state_record_ids=perception_ids,
            psychology_trace_ids=list(psychology_id_by_candidate.values()),
            expression_record_ids=list(expression_id_by_candidate.values()),
            blocked_objective_candidates=extraction.blocked_objective_candidates,
            warnings=warnings,
            source_narrative_intent_ids=extraction.source_narrative_intent_ids,
        )

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback="local_project",
        )


def _record_id(prefix: str, scene_id: str, candidate_id: str) -> str:
    raw = f"{prefix}_{scene_id}_{candidate_id}"
    text = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")
    return text[:180] if len(text) > 180 else text


def _first(values: list[str]) -> str:
    return values[0] if values else ""
