import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.narrative_layer import (
    ApparentContradictionRecord,
    CharacterExpressionRecord,
    CharacterPsychologyTrace,
    ClaimRecord,
    NarrativeDebt,
    NarrativeDebtListResponse,
    NarrativeIntentRecord,
    NarrativeLayerSceneRecords,
    PerceptionStateRecord,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.storage.json_store import JsonStore, StorageError


RecordModel = TypeVar("RecordModel", bound=BaseModel)


class NarrativeLayerService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )

    def create_claim(self, record: ClaimRecord) -> ClaimRecord:
        before_events = self._stable_json(self.repositories.events.list_all())
        before_memory = self._stable_json(self.repositories.memory.list_all())
        saved = self._persist(
            repository=self.repositories.claim_records,
            record=self._stamp(record, ClaimRecord),
            id_field="claim_id",
        )
        self._assert_same(
            before_events,
            self._stable_json(self.repositories.events.list_all()),
            "ClaimRecord must not create or update Event records.",
        )
        self._assert_same(
            before_memory,
            self._stable_json(self.repositories.memory.list_all()),
            "ClaimRecord must not create objective Memory records.",
        )
        return saved

    def create_narrative_intent(
        self,
        record: NarrativeIntentRecord,
    ) -> NarrativeIntentRecord:
        if record.constraint_strength not in {"soft_intent", "suggestion"}:
            raise StorageError("NarrativeIntentRecord does not allow hard_constraint.")
        return self._persist(
            repository=self.repositories.narrative_intent_records,
            record=self._stamp(record, NarrativeIntentRecord),
            id_field="narrative_intent_id",
        )

    def create_psychology_trace(
        self,
        record: CharacterPsychologyTrace,
    ) -> CharacterPsychologyTrace:
        before_characters = self._stable_json(self.repositories.characters.list_all())
        saved = self._persist(
            repository=self.repositories.character_psychology_traces,
            record=self._stamp(record, CharacterPsychologyTrace),
            id_field="psychology_trace_id",
        )
        self._assert_same(
            before_characters,
            self._stable_json(self.repositories.characters.list_all()),
            "CharacterPsychologyTrace must not modify Character state.",
        )
        return saved

    def create_expression_record(
        self,
        record: CharacterExpressionRecord,
    ) -> CharacterExpressionRecord:
        return self._persist(
            repository=self.repositories.character_expression_records,
            record=self._stamp(record, CharacterExpressionRecord),
            id_field="expression_record_id",
        )

    def create_perception_state(
        self,
        record: PerceptionStateRecord,
    ) -> PerceptionStateRecord:
        before_scenes = self._stable_json(self.repositories.scenes.list_all())
        saved = self._persist(
            repository=self.repositories.perception_state_records,
            record=self._stamp(record, PerceptionStateRecord),
            id_field="perception_state_id",
        )
        self._assert_same(
            before_scenes,
            self._stable_json(self.repositories.scenes.list_all()),
            "PerceptionStateRecord must not modify Scene or location state.",
        )
        return saved

    def create_apparent_contradiction(
        self,
        record: ApparentContradictionRecord,
    ) -> ApparentContradictionRecord:
        before_statuses = self._continuity_issue_statuses()
        saved = self._persist(
            repository=self.repositories.apparent_contradiction_records,
            record=self._stamp(record, ApparentContradictionRecord),
            id_field="apparent_contradiction_id",
        )
        self._assert_same(
            before_statuses,
            self._continuity_issue_statuses(),
            "ApparentContradictionRecord must not alter ContinuityIssue status.",
        )
        return saved

    def create_narrative_debt(self, record: NarrativeDebt) -> NarrativeDebt:
        before_statuses = self._continuity_issue_statuses()
        saved = self._persist(
            repository=self.repositories.narrative_debts,
            record=self._stamp(record, NarrativeDebt),
            id_field="narrative_debt_id",
        )
        self._assert_same(
            before_statuses,
            self._continuity_issue_statuses(),
            "NarrativeDebt must not resolve ContinuityIssue records.",
        )
        return saved

    def get_claim(self, claim_id: str) -> ClaimRecord | None:
        return self._get(
            self.repositories.claim_records,
            ClaimRecord,
            claim_id,
        )

    def get_narrative_intent(
        self,
        narrative_intent_id: str,
    ) -> NarrativeIntentRecord | None:
        return self._get(
            self.repositories.narrative_intent_records,
            NarrativeIntentRecord,
            narrative_intent_id,
        )

    def get_psychology_trace(
        self,
        psychology_trace_id: str,
    ) -> CharacterPsychologyTrace | None:
        return self._get(
            self.repositories.character_psychology_traces,
            CharacterPsychologyTrace,
            psychology_trace_id,
        )

    def get_expression_record(
        self,
        expression_record_id: str,
    ) -> CharacterExpressionRecord | None:
        return self._get(
            self.repositories.character_expression_records,
            CharacterExpressionRecord,
            expression_record_id,
        )

    def get_perception_state(
        self,
        perception_state_id: str,
    ) -> PerceptionStateRecord | None:
        return self._get(
            self.repositories.perception_state_records,
            PerceptionStateRecord,
            perception_state_id,
        )

    def get_apparent_contradiction(
        self,
        apparent_contradiction_id: str,
    ) -> ApparentContradictionRecord | None:
        return self._get(
            self.repositories.apparent_contradiction_records,
            ApparentContradictionRecord,
            apparent_contradiction_id,
        )

    def get_narrative_debt(self, narrative_debt_id: str) -> NarrativeDebt | None:
        return self._get(
            self.repositories.narrative_debts,
            NarrativeDebt,
            narrative_debt_id,
        )

    def list_claims(self) -> list[ClaimRecord]:
        return self._list(self.repositories.claim_records, ClaimRecord)

    def list_narrative_intents(self) -> list[NarrativeIntentRecord]:
        return self._list(
            self.repositories.narrative_intent_records,
            NarrativeIntentRecord,
        )

    def list_psychology_traces(self) -> list[CharacterPsychologyTrace]:
        return self._list(
            self.repositories.character_psychology_traces,
            CharacterPsychologyTrace,
        )

    def list_expression_records(self) -> list[CharacterExpressionRecord]:
        return self._list(
            self.repositories.character_expression_records,
            CharacterExpressionRecord,
        )

    def list_perception_states(self) -> list[PerceptionStateRecord]:
        return self._list(
            self.repositories.perception_state_records,
            PerceptionStateRecord,
        )

    def list_apparent_contradictions(self) -> list[ApparentContradictionRecord]:
        return self._list(
            self.repositories.apparent_contradiction_records,
            ApparentContradictionRecord,
        )

    def list_debts(
        self,
        *,
        status: str | None = None,
        scene_id: str | None = None,
        chapter_id: str | None = None,
    ) -> list[NarrativeDebt]:
        debts = self._list(self.repositories.narrative_debts, NarrativeDebt)
        if status:
            debts = [debt for debt in debts if debt.status == status]
        if scene_id:
            debts = [
                debt
                for debt in debts
                if scene_id in {debt.scene_id, debt.source_scene_id, debt.payoff_scene_id}
            ]
        if chapter_id:
            debts = [debt for debt in debts if debt.chapter_id == chapter_id]
        return debts

    def list_narrative_debts(
        self,
        *,
        status: str | None = None,
        scene_id: str | None = None,
        chapter_id: str | None = None,
    ) -> NarrativeDebtListResponse:
        debts = self.list_debts(
            status=status,
            scene_id=scene_id,
            chapter_id=chapter_id,
        )
        return NarrativeDebtListResponse(debts=debts, count=len(debts))

    def update_claim(self, claim_id: str, patch: dict[str, Any]) -> ClaimRecord:
        return self._update(
            self.repositories.claim_records,
            ClaimRecord,
            claim_id,
            patch,
            "claim_id",
        )

    def update_narrative_intent(
        self,
        narrative_intent_id: str,
        patch: dict[str, Any],
    ) -> NarrativeIntentRecord:
        return self._update(
            self.repositories.narrative_intent_records,
            NarrativeIntentRecord,
            narrative_intent_id,
            patch,
            "narrative_intent_id",
        )

    def update_psychology_trace(
        self,
        psychology_trace_id: str,
        patch: dict[str, Any],
    ) -> CharacterPsychologyTrace:
        before_characters = self._stable_json(self.repositories.characters.list_all())
        updated = self._update(
            self.repositories.character_psychology_traces,
            CharacterPsychologyTrace,
            psychology_trace_id,
            patch,
            "psychology_trace_id",
        )
        self._assert_same(
            before_characters,
            self._stable_json(self.repositories.characters.list_all()),
            "CharacterPsychologyTrace must not modify Character state.",
        )
        return updated

    def update_expression_record(
        self,
        expression_record_id: str,
        patch: dict[str, Any],
    ) -> CharacterExpressionRecord:
        return self._update(
            self.repositories.character_expression_records,
            CharacterExpressionRecord,
            expression_record_id,
            patch,
            "expression_record_id",
        )

    def update_perception_state(
        self,
        perception_state_id: str,
        patch: dict[str, Any],
    ) -> PerceptionStateRecord:
        before_scenes = self._stable_json(self.repositories.scenes.list_all())
        updated = self._update(
            self.repositories.perception_state_records,
            PerceptionStateRecord,
            perception_state_id,
            patch,
            "perception_state_id",
        )
        self._assert_same(
            before_scenes,
            self._stable_json(self.repositories.scenes.list_all()),
            "PerceptionStateRecord must not modify Scene or location state.",
        )
        return updated

    def update_apparent_contradiction(
        self,
        apparent_contradiction_id: str,
        patch: dict[str, Any],
    ) -> ApparentContradictionRecord:
        before_statuses = self._continuity_issue_statuses()
        updated = self._update(
            self.repositories.apparent_contradiction_records,
            ApparentContradictionRecord,
            apparent_contradiction_id,
            patch,
            "apparent_contradiction_id",
        )
        self._assert_same(
            before_statuses,
            self._continuity_issue_statuses(),
            "ApparentContradictionRecord must not alter ContinuityIssue status.",
        )
        return updated

    def update_narrative_debt(
        self,
        narrative_debt_id: str,
        patch: dict[str, Any],
    ) -> NarrativeDebt:
        before_statuses = self._continuity_issue_statuses()
        updated = self._update(
            self.repositories.narrative_debts,
            NarrativeDebt,
            narrative_debt_id,
            patch,
            "narrative_debt_id",
        )
        self._assert_same(
            before_statuses,
            self._continuity_issue_statuses(),
            "NarrativeDebt must not resolve ContinuityIssue records.",
        )
        return updated

    def get_scene_records(self, scene_id: str) -> NarrativeLayerSceneRecords:
        return NarrativeLayerSceneRecords(
            scene_id=scene_id,
            claim_records=[
                record for record in self.list_claims() if record.scene_id == scene_id
            ],
            narrative_intent_records=[
                record
                for record in self.list_narrative_intents()
                if record.scene_id == scene_id
            ],
            character_psychology_traces=[
                record
                for record in self.list_psychology_traces()
                if record.scene_id == scene_id
            ],
            character_expression_records=[
                record
                for record in self.list_expression_records()
                if record.scene_id == scene_id
            ],
            perception_state_records=[
                record
                for record in self.list_perception_states()
                if record.scene_id == scene_id
            ],
            apparent_contradiction_records=[
                record
                for record in self.list_apparent_contradictions()
                if record.scene_id == scene_id
            ],
            narrative_debts=self.list_debts(scene_id=scene_id),
        )

    def _get(
        self,
        repository: Any,
        model_cls: type[RecordModel],
        record_id: str,
    ) -> RecordModel | None:
        data = repository.get_by_id(record_id)
        if data is None:
            return None
        return model_cls(**data)

    def _list(
        self,
        repository: Any,
        model_cls: type[RecordModel],
    ) -> list[RecordModel]:
        return [model_cls(**record) for record in repository.list_all()]

    def _update(
        self,
        repository: Any,
        model_cls: type[RecordModel],
        record_id: str,
        patch: dict[str, Any],
        id_field: str,
    ) -> RecordModel:
        existing = repository.get_by_id(record_id)
        if existing is None:
            raise StorageError(f"Narrative layer record was not found: {record_id}")
        data = {**existing, **dict(patch or {})}
        data[id_field] = record_id
        return self._persist(
            repository=repository,
            record=self._stamp(model_cls(**data), model_cls, preserve_created_at=True),
            id_field=id_field,
        )

    def _persist(
        self,
        *,
        repository: Any,
        record: RecordModel,
        id_field: str,
    ) -> RecordModel:
        repository.upsert(model_to_dict(record), id_field=id_field)
        return record

    def _stamp(
        self,
        record: RecordModel,
        model_cls: type[RecordModel],
        *,
        preserve_created_at: bool = False,
    ) -> RecordModel:
        data = model_to_dict(record)
        timestamp = utc_now()
        if not preserve_created_at or not data.get("created_at"):
            data["created_at"] = data.get("created_at") or timestamp
        data["updated_at"] = timestamp
        return model_cls(**data)

    def _continuity_issue_statuses(self) -> str:
        statuses = {
            str(issue.get("issue_id") or ""): str(issue.get("status") or "")
            for issue in self.repositories.continuity_issues.list_all()
            if issue.get("issue_id")
        }
        return self._stable_json(statuses)

    def _assert_same(self, before: str, after: str, message: str) -> None:
        if before != after:
            raise StorageError(message)

    def _stable_json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
