from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.backend.core.config import STORAGE_MODE_POSTGRES_PRIMARY, settings
from app.backend.repositories.base import (
    ApparentContradictionRepository,
    ChapterMemoryPackRepository,
    ChapterRepository,
    CharacterExpressionRecordRepository,
    CharacterPsychologyTraceRepository,
    CharacterRepository,
    ClaimRecordRepository,
    ContinuityIssueRepository,
    DecisionRepository,
    EventRepository,
    FrameworkPackageRepository,
    MemoryRepository,
    MemoryUpdatePlanRepository,
    NarrativeDebtRepository,
    NarrativeIntentRepository,
    PriorStoryCompletionCandidateRepository,
    PendingCharacterStateChangeRepository,
    PerceptionStateRepository,
    QualityReportRepository,
    RelationshipRepository,
    SceneMemoryPackRepository,
    SceneRepository,
    StateChangeRepository,
    WorldCanvasRepository,
)
from app.backend.repositories.json_repositories import (
    JsonApparentContradictionRepository,
    JsonChapterMemoryPackRepository,
    JsonChapterRepository,
    JsonCharacterExpressionRecordRepository,
    JsonCharacterPsychologyTraceRepository,
    JsonCharacterRepository,
    JsonClaimRecordRepository,
    JsonContinuityIssueRepository,
    JsonDecisionRepository,
    JsonEventRepository,
    JsonFrameworkPackageRepository,
    JsonMemoryRepository,
    JsonMemoryUpdatePlanRepository,
    JsonNarrativeDebtRepository,
    JsonNarrativeIntentRepository,
    JsonPriorStoryCompletionCandidateRepository,
    JsonPendingCharacterStateChangeRepository,
    JsonPerceptionStateRepository,
    JsonQualityReportRepository,
    JsonRelationshipRepository,
    JsonSceneMemoryPackRepository,
    JsonSceneRepository,
    JsonStateChangeRepository,
    JsonWorldCanvasRepository,
)
from app.backend.repositories.postgres_normalized_repositories import (
    PostgresConnectionFactory,
    create_postgres_normalized_repository,
)
from app.backend.storage.json_store import JsonStore
from app.backend.storage.postgres_json_store import PostgresJsonStore


@dataclass
class RepositoryBundle:
    memory: MemoryRepository
    scenes: SceneRepository
    events: EventRepository
    state_changes: StateChangeRepository
    characters: CharacterRepository
    relationships: RelationshipRepository
    world_canvases: WorldCanvasRepository
    framework_packages: FrameworkPackageRepository
    chapter_memory_packs: ChapterMemoryPackRepository
    scene_memory_packs: SceneMemoryPackRepository
    decisions: DecisionRepository
    quality_reports: QualityReportRepository
    continuity_issues: ContinuityIssueRepository
    prior_story_completion_candidates: PriorStoryCompletionCandidateRepository
    chapters: ChapterRepository
    pending_character_state_changes: PendingCharacterStateChangeRepository
    memory_update_plans: MemoryUpdatePlanRepository
    claim_records: ClaimRecordRepository
    narrative_intent_records: NarrativeIntentRepository
    character_psychology_traces: CharacterPsychologyTraceRepository
    character_expression_records: CharacterExpressionRecordRepository
    perception_state_records: PerceptionStateRepository
    apparent_contradiction_records: ApparentContradictionRepository
    narrative_debts: NarrativeDebtRepository


def create_json_repositories(
    *,
    store: JsonStore | None = None,
    data_dir: Path | None = None,
) -> RepositoryBundle:
    active_store = store or JsonStore()
    active_data_dir = data_dir or settings.data_dir
    return _create_repository_bundle(store=active_store, data_dir=active_data_dir)


def create_postgres_repositories(
    *,
    store: PostgresJsonStore | None = None,
    data_dir: Path | None = None,
    database_url: str | None = None,
) -> RepositoryBundle:
    active_data_dir = data_dir or settings.data_dir
    active_database_url = database_url or settings.database_url
    normalized_connection_factory = PostgresConnectionFactory(
        database_url=active_database_url,
    )
    repository_names = RepositoryBundle.__dataclass_fields__.keys()
    normalized_repositories = {
        name: create_postgres_normalized_repository(
            repository_name=name,
            connection_factory=normalized_connection_factory,
            data_dir=active_data_dir,
        )
        for name in repository_names
    }
    return RepositoryBundle(
        **normalized_repositories,
    )


def create_repositories(
    *,
    store: Any | None = None,
    data_dir: Path | None = None,
) -> RepositoryBundle:
    if settings.storage_mode == STORAGE_MODE_POSTGRES_PRIMARY:
        if store is not None:
            return create_postgres_repositories(store=store, data_dir=data_dir)
        return create_postgres_repositories(data_dir=data_dir)
    return create_json_repositories(store=store, data_dir=data_dir)


def _create_repository_bundle(
    *,
    store: Any,
    data_dir: Path,
) -> RepositoryBundle:
    return RepositoryBundle(
        memory=JsonMemoryRepository(store=store, data_dir=data_dir),
        scenes=JsonSceneRepository(store=store, data_dir=data_dir),
        events=JsonEventRepository(store=store, data_dir=data_dir),
        state_changes=JsonStateChangeRepository(
            store=store,
            data_dir=data_dir,
        ),
        characters=JsonCharacterRepository(store=store, data_dir=data_dir),
        relationships=JsonRelationshipRepository(
            store=store,
            data_dir=data_dir,
        ),
        world_canvases=JsonWorldCanvasRepository(store=store, data_dir=data_dir),
        framework_packages=JsonFrameworkPackageRepository(
            store=store,
            data_dir=data_dir,
        ),
        chapter_memory_packs=JsonChapterMemoryPackRepository(
            store=store,
            data_dir=data_dir,
        ),
        scene_memory_packs=JsonSceneMemoryPackRepository(
            store=store,
            data_dir=data_dir,
        ),
        decisions=JsonDecisionRepository(store=store, data_dir=data_dir),
        quality_reports=JsonQualityReportRepository(
            store=store,
            data_dir=data_dir,
        ),
        continuity_issues=JsonContinuityIssueRepository(
            store=store,
            data_dir=data_dir,
        ),
        prior_story_completion_candidates=JsonPriorStoryCompletionCandidateRepository(
            store=store,
            data_dir=data_dir,
        ),
        chapters=JsonChapterRepository(store=store, data_dir=data_dir),
        pending_character_state_changes=JsonPendingCharacterStateChangeRepository(
            store=store,
            data_dir=data_dir,
        ),
        memory_update_plans=JsonMemoryUpdatePlanRepository(
            store=store,
            data_dir=data_dir,
        ),
        claim_records=JsonClaimRecordRepository(
            store=store,
            data_dir=data_dir,
        ),
        narrative_intent_records=JsonNarrativeIntentRepository(
            store=store,
            data_dir=data_dir,
        ),
        character_psychology_traces=JsonCharacterPsychologyTraceRepository(
            store=store,
            data_dir=data_dir,
        ),
        character_expression_records=JsonCharacterExpressionRecordRepository(
            store=store,
            data_dir=data_dir,
        ),
        perception_state_records=JsonPerceptionStateRepository(
            store=store,
            data_dir=data_dir,
        ),
        apparent_contradiction_records=JsonApparentContradictionRepository(
            store=store,
            data_dir=data_dir,
        ),
        narrative_debts=JsonNarrativeDebtRepository(
            store=store,
            data_dir=data_dir,
        ),
    )
