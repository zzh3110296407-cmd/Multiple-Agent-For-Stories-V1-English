from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ListRepository(Protocol):
    def list_all(self) -> list[dict[str, Any]]:
        ...

    def write_all(self, records: list[dict[str, Any]]) -> None:
        ...

    def append(self, record: dict[str, Any]) -> None:
        ...

    def upsert(self, record: dict[str, Any], id_field: str) -> None:
        ...


@runtime_checkable
class MemoryRepository(ListRepository, Protocol):
    def get_by_id(self, memory_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class SceneRepository(ListRepository, Protocol):
    def get_by_id(self, scene_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class EventRepository(ListRepository, Protocol):
    def get_by_id(self, event_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class StateChangeRepository(ListRepository, Protocol):
    def get_by_id(self, state_change_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class CharacterRepository(ListRepository, Protocol):
    def get_by_id(self, character_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class RelationshipRepository(ListRepository, Protocol):
    def get_by_id(self, relationship_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class WorldCanvasRepository(ListRepository, Protocol):
    def get_by_id(self, world_canvas_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class FrameworkPackageRepository(ListRepository, Protocol):
    def get_by_id(self, framework_package_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class DecisionRepository(ListRepository, Protocol):
    def get_by_id(self, decision_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class QualityReportRepository(ListRepository, Protocol):
    def get_by_id(self, quality_report_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class ContinuityIssueRepository(ListRepository, Protocol):
    def get_by_id(self, issue_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class PriorStoryCompletionCandidateRepository(ListRepository, Protocol):
    def get_by_id(self, candidate_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class ChapterRepository(ListRepository, Protocol):
    def get_by_id(self, chapter_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class PackRepository(Protocol):
    def read_envelope(self) -> dict[str, Any]:
        ...

    def write_envelope(self, envelope: dict[str, Any]) -> None:
        ...

    def list_packs(self) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class ChapterMemoryPackRepository(PackRepository, Protocol):
    def get_by_id(self, chapter_memory_pack_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class SceneMemoryPackRepository(PackRepository, Protocol):
    def get_by_id(self, scene_memory_pack_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class PendingCharacterStateChangeRepository(ListRepository, Protocol):
    def get_by_id(self, change_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class MemoryUpdatePlanRepository(ListRepository, Protocol):
    def get_by_id(self, plan_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class ClaimRecordRepository(ListRepository, Protocol):
    def get_by_id(self, claim_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class NarrativeIntentRepository(ListRepository, Protocol):
    def get_by_id(self, narrative_intent_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class CharacterPsychologyTraceRepository(ListRepository, Protocol):
    def get_by_id(self, psychology_trace_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class CharacterExpressionRecordRepository(ListRepository, Protocol):
    def get_by_id(self, expression_record_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class PerceptionStateRepository(ListRepository, Protocol):
    def get_by_id(self, perception_state_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class ApparentContradictionRepository(ListRepository, Protocol):
    def get_by_id(self, apparent_contradiction_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class NarrativeDebtRepository(ListRepository, Protocol):
    def get_by_id(self, narrative_debt_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class TimelineRepository(ListRepository, Protocol):
    def get_by_id(self, timeline_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class CharacterMemoryNodeRepository(ListRepository, Protocol):
    def get_by_id(self, character_memory_node_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class LocationStateNodeRepository(ListRepository, Protocol):
    def get_by_id(self, location_state_node_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class LocationChangeDeltaRepository(ListRepository, Protocol):
    def get_by_id(self, location_change_delta_id: str) -> dict[str, Any] | None:
        ...
