import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.character import Character, CharacterContextItem
from app.backend.models.character_intent import (
    CharacterActionIntentionCandidate,
    CharacterIntentGenerationPolicy,
    CharacterIntentPackageBuildResponse,
    CharacterIntentPackageReadResponse,
    CharacterIntentRiskReport,
    CharacterPsychologyTraceRuntimeMeta,
    TieredCharacterIntentPackage,
)
from app.backend.models.memory_pack import ChapterMemoryPack, SceneMemoryPack
from app.backend.models.narrative_layer import (
    CharacterPsychologyTrace,
    NarrativeObjectReference,
)
from app.backend.models.scene_participation import (
    SceneParticipationPackage,
    TieredCharacterContextPackage,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.narrative_layer_service import NarrativeLayerService
from app.backend.storage.json_store import JsonStore, StorageError


CHARACTER_PSYCHOLOGY_TRACE_RUNTIME_META_FILE = (
    "character_psychology_trace_runtime_meta.json"
)
CHARACTER_ACTION_INTENTION_CANDIDATES_FILE = (
    "character_action_intention_candidates.json"
)
CHARACTER_INTENT_RISK_REPORTS_FILE = "character_intent_risk_reports.json"
TIERED_CHARACTER_INTENT_PACKAGES_FILE = "tiered_character_intent_packages.json"
CHARACTER_INTENT_GENERATION_POLICY_FILE = "character_intent_generation_policy.json"
SCENE_PARTICIPATION_PACKAGES_FILE = "scene_participation_packages.json"
TIERED_CHARACTER_CONTEXT_PACKAGES_FILE = "tiered_character_context_packages.json"

FORBIDDEN_STORY_FACT_FILES = [
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "characters.json",
    "relationships.json",
    "scenes.json",
    "story_information_items.json",
]


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class CharacterIntentGenerationPolicyService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.policy_file = self.data_dir / CHARACTER_INTENT_GENERATION_POLICY_FILE

    def get_policy(self, project_id: str = "local_project") -> CharacterIntentGenerationPolicy:
        if self.store.exists(self.policy_file):
            raw = self.store.read_any(self.policy_file)
            if not isinstance(raw, dict):
                raise StorageError("CHARACTER_INTENT_INVALID_POLICY_STORAGE")
            return CharacterIntentGenerationPolicy(**raw)
        timestamp = utc_now()
        policy = CharacterIntentGenerationPolicy(
            project_id=project_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.store.write(self.policy_file, model_to_dict(policy))
        return policy


class CharacterIntentSafetyGuard:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def snapshot(self) -> dict[str, str]:
        return {
            file_name: self._hash_file(self.data_dir / file_name)
            for file_name in FORBIDDEN_STORY_FACT_FILES
        }

    def assert_unchanged(self, before: dict[str, str]) -> None:
        after = self.snapshot()
        changed = [
            file_name
            for file_name in FORBIDDEN_STORY_FACT_FILES
            if before.get(file_name) != after.get(file_name)
        ]
        if changed:
            raise StorageError(
                "CHARACTER_INTENT_FORBIDDEN_STORY_FACT_MUTATION:"
                + ",".join(changed)
            )

    def _hash_file(self, path: Path) -> str:
        if not path.exists():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()


class TieredCharacterIntentPackageService:
    """Builds M6 candidate-only psychology and action-intention runtime artifacts."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        narrative_layer_service: NarrativeLayerService | None = None,
        policy_service: CharacterIntentGenerationPolicyService | None = None,
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
        self.policy_service = policy_service or CharacterIntentGenerationPolicyService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.safety_guard = CharacterIntentSafetyGuard(self.data_dir)
        self.runtime_meta_file = self.data_dir / CHARACTER_PSYCHOLOGY_TRACE_RUNTIME_META_FILE
        self.candidates_file = self.data_dir / CHARACTER_ACTION_INTENTION_CANDIDATES_FILE
        self.risk_reports_file = self.data_dir / CHARACTER_INTENT_RISK_REPORTS_FILE
        self.packages_file = self.data_dir / TIERED_CHARACTER_INTENT_PACKAGES_FILE
        self.scene_participation_file = self.data_dir / SCENE_PARTICIPATION_PACKAGES_FILE
        self.tiered_context_file = self.data_dir / TIERED_CHARACTER_CONTEXT_PACKAGES_FILE

    def build_for_scene_participation(
        self,
        scene_participation_package_id: str,
        force_refresh: bool = False,
    ) -> TieredCharacterIntentPackage:
        package_id = str(scene_participation_package_id or "").strip()
        if not package_id:
            raise StorageError("CHARACTER_INTENT_SCENE_PARTICIPATION_PACKAGE_ID_REQUIRED")
        existing = self._current_for_scene_participation(package_id)
        if existing is not None and not force_refresh:
            return existing

        before = self.safety_guard.snapshot()
        scene_participation = self._get_scene_participation_package(package_id)
        if scene_participation.status == "blocked":
            raise StorageError("CHARACTER_INTENT_SCENE_PARTICIPATION_PACKAGE_BLOCKED")
        if not scene_participation.active_character_ids:
            raise StorageError("CHARACTER_INTENT_ACTIVE_CHARACTER_IDS_REQUIRED")
        tiered_context = self._get_tiered_context_package(
            scene_participation.tiered_character_context_package_id,
            scene_participation.scene_participation_package_id,
        )
        scene_memory_pack = self._get_scene_memory_pack(
            scene_participation.scene_memory_pack_id
        )
        chapter_memory_pack = self._get_chapter_memory_pack(
            scene_memory_pack.chapter_memory_pack_id,
            scene_participation.chapter_id,
        )
        policy = self.policy_service.get_policy(scene_participation.project_id)
        characters_by_id = self._characters_by_id()
        timestamp = utc_now()
        warnings = self._unique(
            [
                *scene_participation.warnings,
                *tiered_context.warnings,
            ]
        )

        traces: list[CharacterPsychologyTrace] = []
        metas: list[CharacterPsychologyTraceRuntimeMeta] = []
        candidates: list[CharacterActionIntentionCandidate] = []
        risk_reports: list[CharacterIntentRiskReport] = []
        participants_by_id = {
            participant.character_id: participant
            for participant in scene_participation.participants
        }
        context_by_id = {
            item.character_id: item
            for item in tiered_context.items
            if item.character_id in scene_participation.active_character_ids
        }
        for character_id in scene_participation.active_character_ids:
            character = characters_by_id.get(character_id)
            participant = participants_by_id.get(character_id)
            context_item = context_by_id.get(character_id)
            if character is None:
                warnings.append(f"active_character_missing:{character_id}")
                continue
            tier = self._tier_for(character, participant)
            if tier not in {"A", "B", "C", "D"}:
                warnings.append(f"active_character_unknown_tier:{character_id}")
                continue
            depth = self._depth_for_tier(policy, tier)
            memory_refs = self._memory_refs_for_character(
                character_id=character_id,
                context_item=context_item,
                scene_memory_pack=scene_memory_pack,
            )
            trace = self._build_trace(
                scene_participation=scene_participation,
                character=character,
                participant=participant,
                context_item=context_item,
                memory_refs=memory_refs,
                tier=tier,
                depth=depth,
                timestamp=timestamp,
            )
            saved_trace = self.narrative_layer_service.create_psychology_trace(trace)
            traces.append(saved_trace)
            meta = self._build_runtime_meta(
                scene_participation=scene_participation,
                tiered_context=tiered_context,
                scene_memory_pack=scene_memory_pack,
                chapter_memory_pack=chapter_memory_pack,
                trace=saved_trace,
                character_id=character_id,
                tier=tier,
                depth=depth,
                context_item=context_item,
                memory_refs=memory_refs,
                timestamp=timestamp,
            )
            metas.append(meta)
            character_candidates = self._build_candidates(
                scene_participation=scene_participation,
                tiered_context=tiered_context,
                scene_memory_pack=scene_memory_pack,
                trace=saved_trace,
                character=character,
                participant=participant,
                context_item=context_item,
                memory_refs=memory_refs,
                tier=tier,
                policy=policy,
                timestamp=timestamp,
            )
            candidates.extend(character_candidates)
        for candidate in candidates:
            risk_reports.append(self._build_risk_report(candidate, timestamp))

        package = self._build_package(
            scene_participation=scene_participation,
            tiered_context=tiered_context,
            scene_memory_pack=scene_memory_pack,
            chapter_memory_pack=chapter_memory_pack,
            traces=traces,
            metas=metas,
            candidates=candidates,
            risk_reports=risk_reports,
            warnings=warnings,
            timestamp=timestamp,
        )
        self._upsert_models(self.runtime_meta_file, metas, "runtime_meta_id")
        self._upsert_models(
            self.candidates_file,
            candidates,
            "action_intention_candidate_id",
        )
        self._upsert_models(self.risk_reports_file, risk_reports, "risk_report_id")
        self._upsert_model(
            self.packages_file,
            package,
            "tiered_character_intent_package_id",
        )
        self.safety_guard.assert_unchanged(before)
        return package

    def build_response(
        self,
        scene_participation_package_id: str,
        force_refresh: bool = False,
    ) -> CharacterIntentPackageBuildResponse:
        package = self.build_for_scene_participation(
            scene_participation_package_id,
            force_refresh=force_refresh,
        )
        response = self._response_for_package(package)
        return CharacterIntentPackageBuildResponse(
            package=package,
            psychology_traces=response.psychology_traces,
            psychology_trace_runtime_meta=response.psychology_trace_runtime_meta,
            action_intention_candidates=response.action_intention_candidates,
            risk_reports=response.risk_reports,
            warnings=response.warnings,
        )

    def get_package(self, package_id: str) -> CharacterIntentPackageReadResponse:
        clean_id = str(package_id or "").strip()
        package = next(
            (
                item
                for item in self._read_models(
                    self.packages_file,
                    TieredCharacterIntentPackage,
                )
                if item.tiered_character_intent_package_id == clean_id
            ),
            None,
        )
        if package is None:
            raise StorageError("CHARACTER_INTENT_PACKAGE_NOT_FOUND")
        return self._response_for_package(package)

    def get_current_package(
        self,
        *,
        chapter_id: str,
        scene_index: int,
    ) -> CharacterIntentPackageReadResponse:
        packages = [
            package
            for package in self._read_models(
                self.packages_file,
                TieredCharacterIntentPackage,
            )
            if package.chapter_id == chapter_id
            and package.scene_index == int(scene_index)
            and package.status in {"ready", "warning", "blocked"}
        ]
        if not packages:
            return CharacterIntentPackageReadResponse()
        package = sorted(packages, key=lambda item: item.updated_at, reverse=True)[0]
        return self._response_for_package(package)

    def refresh_package(self, package_id: str) -> CharacterIntentPackageBuildResponse:
        response = self.get_package(package_id)
        if response.package is None:
            raise StorageError("CHARACTER_INTENT_PACKAGE_NOT_FOUND")
        return self.build_response(
            response.package.scene_participation_package_id,
            force_refresh=True,
        )

    def get_trace(self, trace_id: str) -> CharacterPsychologyTrace:
        trace = self.narrative_layer_service.get_psychology_trace(trace_id)
        if trace is None:
            raise StorageError("CHARACTER_INTENT_TRACE_NOT_FOUND")
        return trace

    def get_candidate(self, candidate_id: str) -> CharacterActionIntentionCandidate:
        candidate = next(
            (
                item
                for item in self._read_models(
                    self.candidates_file,
                    CharacterActionIntentionCandidate,
                )
                if item.action_intention_candidate_id == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise StorageError("CHARACTER_INTENT_CANDIDATE_NOT_FOUND")
        return candidate

    def get_risk_report_for_candidate(self, candidate_id: str) -> CharacterIntentRiskReport:
        report = next(
            (
                item
                for item in self._read_models(
                    self.risk_reports_file,
                    CharacterIntentRiskReport,
                )
                if item.action_intention_candidate_id == candidate_id
            ),
            None,
        )
        if report is None:
            raise StorageError("CHARACTER_INTENT_RISK_REPORT_NOT_FOUND")
        return report

    def get_policy(self) -> CharacterIntentGenerationPolicy:
        project_id = self._project_id_from_any_package() or "local_project"
        return self.policy_service.get_policy(project_id)

    def _build_trace(
        self,
        *,
        scene_participation: SceneParticipationPackage,
        character: Character,
        participant: Any,
        context_item: CharacterContextItem | None,
        memory_refs: list[dict[str, Any]],
        tier: str,
        depth: str,
        timestamp: str,
    ) -> CharacterPsychologyTrace:
        memory_trigger = self._memory_trigger(memory_refs, context_item)
        relationship_pressure = (
            context_item.relationship_summary
            if context_item and context_item.relationship_summary
            else "scene relationship pressure"
        )
        active_desire = (
            character.current_state.current_desire
            or character.current_state.active_goal
            or self._first(character.profile.goals)
            or f"serve the scene function as tier {tier}"
        )
        fear = (
            character.current_state.current_fear
            or self._first(character.profile.fears)
            or "losing agency under scene pressure"
        )
        inner_conflict = character.arc_state.inner_conflict or (
            "local hesitation" if tier in {"C", "D"} else "truth versus safety"
        )
        if tier == "A":
            surface = f"Actively pursues {active_desire} while testing the scene pressure."
            pressure = (
                f"Relationship pressure: {relationship_pressure}. "
                f"Internal conflict: {inner_conflict}. Memory trigger: {memory_trigger}."
            )
            tendency = "protect, question, and consider a major disclosure candidate"
            confidence = 0.82
        elif tier == "B":
            surface = f"Supports or challenges the A-tier lead around {active_desire}."
            pressure = f"Motive and relationship pressure: {relationship_pressure}. Trigger: {memory_trigger}."
            tendency = "support the lead while guarding a limited truth"
            confidence = 0.72
        elif tier == "C":
            surface = "Responds to the local scene function and immediate pressure."
            pressure = f"Local scene pressure with compact memory trigger: {memory_trigger}."
            tendency = "warn, observe, or provide local constraint"
            confidence = 0.64
        else:
            surface = "Minimal witness response to current pressure."
            pressure = f"Minimal tendency from current scene and memory trigger: {memory_trigger}."
            tendency = "hesitate or report one observed detail"
            confidence = 0.55
        return CharacterPsychologyTrace(
            psychology_trace_id=(
                f"psych_trace_{scene_participation.scene_participation_package_id}_"
                f"{character.character_id}"
            ),
            project_id=scene_participation.project_id,
            chapter_id=scene_participation.chapter_id,
            scene_id=scene_participation.scene_id or "",
            character_id=character.character_id,
            surface_intention=surface,
            inner_desire=active_desire,
            fear=fear,
            self_deception="" if tier == "D" else "may confuse caution with certainty",
            suppressed_motive="" if tier in {"C", "D"} else "avoid exposing vulnerability",
            psychological_pressure=pressure,
            action_tendency=tendency,
            interpretation_status="candidate",
            confidence=confidence,
            reader_visible_level="hidden",
            linked_refs=[
                NarrativeObjectReference(
                    object_type="scene_participation_package",
                    object_id=scene_participation.scene_participation_package_id,
                    relation="m6_runtime_source",
                ),
                *[
                    NarrativeObjectReference(
                        object_type="memory_ref",
                        object_id=str(ref.get("memory_id") or ref.get("source_object_id") or ""),
                        relation="psychology_trigger",
                    )
                    for ref in memory_refs[:3]
                    if str(ref.get("memory_id") or ref.get("source_object_id") or "")
                ],
            ],
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _build_runtime_meta(
        self,
        *,
        scene_participation: SceneParticipationPackage,
        tiered_context: TieredCharacterContextPackage,
        scene_memory_pack: SceneMemoryPack,
        chapter_memory_pack: ChapterMemoryPack | None,
        trace: CharacterPsychologyTrace,
        character_id: str,
        tier: str,
        depth: str,
        context_item: CharacterContextItem | None,
        memory_refs: list[dict[str, Any]],
        timestamp: str,
    ) -> CharacterPsychologyTraceRuntimeMeta:
        source_memory_ids = self._unique(
            [
                *(context_item.source_memory_ids if context_item else []),
                *[
                    str(ref.get("memory_id") or "")
                    for ref in memory_refs
                    if str(ref.get("memory_id") or "")
                ],
            ]
        )
        return CharacterPsychologyTraceRuntimeMeta(
            runtime_meta_id=f"psych_trace_meta_{trace.psychology_trace_id}",
            project_id=scene_participation.project_id,
            psychology_trace_id=trace.psychology_trace_id,
            scene_participation_package_id=scene_participation.scene_participation_package_id,
            tiered_character_context_package_id=tiered_context.tiered_character_context_package_id,
            scene_memory_pack_id=scene_memory_pack.scene_memory_pack_id,
            chapter_memory_pack_id=(
                chapter_memory_pack.chapter_memory_pack_id if chapter_memory_pack else ""
            ),
            chapter_id=scene_participation.chapter_id,
            scene_id=scene_participation.scene_id or "",
            scene_index=scene_participation.scene_index,
            character_id=character_id,
            tier=tier,
            trace_depth=depth,
            source_memory_ids=source_memory_ids,
            source_context_item_ids=[f"character_context:{character_id}"]
            if context_item
            else [],
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _build_candidates(
        self,
        *,
        scene_participation: SceneParticipationPackage,
        tiered_context: TieredCharacterContextPackage,
        scene_memory_pack: SceneMemoryPack,
        trace: CharacterPsychologyTrace,
        character: Character,
        participant: Any,
        context_item: CharacterContextItem | None,
        memory_refs: list[dict[str, Any]],
        tier: str,
        policy: CharacterIntentGenerationPolicy,
        timestamp: str,
    ) -> list[CharacterActionIntentionCandidate]:
        max_count = policy.max_action_candidates_by_tier.get(tier, 1)
        base = self._candidate_specs(
            tier=tier,
            character=character,
            scene_memory_pack=scene_memory_pack,
            trace=trace,
            active_character_ids=scene_participation.active_character_ids,
        )
        candidates: list[CharacterActionIntentionCandidate] = []
        for index, spec in enumerate(base[:max_count], start=1):
            candidate_id = (
                f"intent_candidate_{scene_participation.scene_participation_package_id}_"
                f"{character.character_id}_{index}"
            )
            warnings = self._unique(spec.get("warnings", []))
            candidates.append(
                CharacterActionIntentionCandidate(
                    action_intention_candidate_id=candidate_id,
                    project_id=scene_participation.project_id,
                    psychology_trace_id=trace.psychology_trace_id,
                    scene_participation_package_id=scene_participation.scene_participation_package_id,
                    tiered_character_context_package_id=tiered_context.tiered_character_context_package_id,
                    scene_memory_pack_id=scene_memory_pack.scene_memory_pack_id,
                    chapter_id=scene_participation.chapter_id,
                    scene_id=scene_participation.scene_id or "",
                    scene_index=scene_participation.scene_index,
                    character_id=character.character_id,
                    tier=tier,
                    intention_type=spec["intention_type"],
                    intention_summary=spec["intention_summary"],
                    psychological_reason=spec["psychological_reason"],
                    outward_expression_hint=spec["outward_expression_hint"],
                    target_character_ids=spec.get("target_character_ids", []),
                    target_object_ids=spec.get("target_object_ids", []),
                    target_location=scene_memory_pack.scene_location,
                    truth_status=spec.get("truth_status", "objective_candidate"),
                    expected_story_function=spec.get("expected_story_function", ""),
                    continuity_risk_level=spec.get("continuity_risk_level", "low"),
                    apparent_contradiction_possible=bool(
                        spec.get("apparent_contradiction_possible", False)
                    ),
                    requires_continuity_gate=bool(
                        spec.get("requires_continuity_gate", False)
                    ),
                    requires_apparent_gate=bool(spec.get("requires_apparent_gate", False)),
                    requires_quality_gate=bool(spec.get("requires_quality_gate", False)),
                    requires_user_confirmation_candidate=bool(
                        spec.get("requires_user_confirmation_candidate", False)
                    ),
                    can_be_used_by_writer=bool(spec.get("can_be_used_by_writer", True)),
                    can_write_objective_fact_directly=False,
                    candidate_only=True,
                    safe_summary=spec["safe_summary"],
                    warnings=warnings,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        return candidates

    def _candidate_specs(
        self,
        *,
        tier: str,
        character: Character,
        scene_memory_pack: SceneMemoryPack,
        trace: CharacterPsychologyTrace,
        active_character_ids: list[str],
    ) -> list[dict[str, Any]]:
        other_targets = [item for item in active_character_ids if item != character.character_id]
        primary_target = other_targets[:1]
        if tier == "A":
            return [
                {
                    "intention_type": "protective_action",
                    "intention_summary": f"{character.name} tries to control the immediate scene risk.",
                    "psychological_reason": trace.psychological_pressure,
                    "outward_expression_hint": "steps forward and asks a precise question",
                    "target_character_ids": primary_target,
                    "truth_status": "objective_candidate",
                    "expected_story_function": "drive protagonist pressure",
                    "continuity_risk_level": "low",
                    "requires_quality_gate": True,
                    "safe_summary": f"{character.name} may act protectively, but this is only a candidate.",
                },
                {
                    "intention_type": "subjective_claim",
                    "intention_summary": f"{character.name} may claim the lantern code means the gate is unsafe.",
                    "psychological_reason": trace.inner_desire,
                    "outward_expression_hint": "states a cautious interpretation rather than a fact",
                    "target_character_ids": primary_target,
                    "truth_status": "subjective_claim",
                    "expected_story_function": "surface subjective uncertainty",
                    "continuity_risk_level": "medium",
                    "apparent_contradiction_possible": True,
                    "requires_apparent_gate": True,
                    "requires_quality_gate": True,
                    "safe_summary": f"{character.name} may make a subjective claim about the gate.",
                },
                {
                    "intention_type": "major_state_change",
                    "intention_summary": f"{character.name} considers revealing a risky inner decision.",
                    "psychological_reason": trace.fear,
                    "outward_expression_hint": "hesitates before changing course",
                    "target_character_ids": primary_target,
                    "truth_status": "unknown",
                    "expected_story_function": "possible major character turn",
                    "continuity_risk_level": "high",
                    "requires_continuity_gate": True,
                    "requires_quality_gate": True,
                    "requires_user_confirmation_candidate": True,
                    "can_be_used_by_writer": False,
                    "safe_summary": f"{character.name} has a possible major state-change intention.",
                    "warnings": ["major_state_change"],
                },
            ]
        if tier == "B":
            return [
                {
                    "intention_type": "support_or_challenge",
                    "intention_summary": f"{character.name} supports the lead while guarding a personal doubt.",
                    "psychological_reason": trace.psychological_pressure,
                    "outward_expression_hint": "answers briefly but watches the lead",
                    "target_character_ids": primary_target,
                    "truth_status": "objective_candidate",
                    "expected_story_function": "relationship pressure",
                    "continuity_risk_level": "low",
                    "requires_quality_gate": True,
                    "safe_summary": f"{character.name} may support or challenge the lead.",
                },
                {
                    "intention_type": "withheld_claim",
                    "intention_summary": f"{character.name} may omit a memory-relevant detail.",
                    "psychological_reason": trace.suppressed_motive or trace.fear,
                    "outward_expression_hint": "pauses before answering",
                    "target_character_ids": primary_target,
                    "truth_status": "unknown",
                    "expected_story_function": "controlled omission",
                    "continuity_risk_level": "medium",
                    "requires_continuity_gate": True,
                    "requires_quality_gate": True,
                    "safe_summary": f"{character.name} may withhold a detail; this is not a fact.",
                },
            ]
        if tier == "C":
            return [
                {
                    "intention_type": "local_warning",
                    "intention_summary": f"{character.name} may warn about a local constraint.",
                    "psychological_reason": trace.psychological_pressure,
                    "outward_expression_hint": "points to the local hazard",
                    "target_character_ids": primary_target,
                    "truth_status": "perception",
                    "expected_story_function": "local scene constraint",
                    "continuity_risk_level": "medium",
                    "apparent_contradiction_possible": True,
                    "requires_apparent_gate": True,
                    "requires_quality_gate": True,
                    "safe_summary": f"{character.name} may report a perception, not an objective fact.",
                },
                {
                    "intention_type": "functional_assist",
                    "intention_summary": f"{character.name} may help move the scene toward the next clue.",
                    "psychological_reason": trace.action_tendency,
                    "outward_expression_hint": "offers one practical detail",
                    "target_character_ids": primary_target,
                    "truth_status": "objective_candidate",
                    "expected_story_function": "chapter-level local function",
                    "continuity_risk_level": "low",
                    "requires_quality_gate": True,
                    "safe_summary": f"{character.name} may provide a compact assist.",
                },
            ]
        return [
            {
                "intention_type": "minimal_witness_response",
                "intention_summary": f"{character.name} may hesitate and report one observed detail.",
                "psychological_reason": trace.psychological_pressure,
                "outward_expression_hint": "steps back or gives a short report",
                "target_character_ids": primary_target,
                "truth_status": "perception",
                "expected_story_function": "minimal persistent witness",
                "continuity_risk_level": "medium",
                "apparent_contradiction_possible": True,
                "requires_apparent_gate": True,
                "requires_quality_gate": True,
                "safe_summary": f"{character.name} may give one perception-level witness response.",
            }
        ]

    def _build_risk_report(
        self,
        candidate: CharacterActionIntentionCandidate,
        timestamp: str,
    ) -> CharacterIntentRiskReport:
        categories: list[str] = []
        gates: list[str] = []
        possible_forbidden_knowledge = False
        possible_location_conflict = False
        possible_relationship_conflict = False
        possible_world_rule_conflict = False
        possible_major_state_change = False
        possible_apparent_contradiction = False
        risk_level = candidate.continuity_risk_level
        if candidate.requires_continuity_gate:
            gates.append("continuity_gate")
            categories.append("continuity_precheck")
        if candidate.requires_apparent_gate or candidate.apparent_contradiction_possible:
            gates.append("apparent_gate")
            categories.append("apparent_contradiction_precheck")
            possible_apparent_contradiction = True
        if candidate.requires_quality_gate:
            gates.append("quality_gate")
            categories.append("quality_precheck")
        if candidate.requires_user_confirmation_candidate:
            gates.append("user_confirmation_candidate")
            categories.append("major_state_change_candidate")
            possible_major_state_change = True
            risk_level = "high"
        if "forbidden_knowledge" in candidate.warnings:
            possible_forbidden_knowledge = True
            categories.append("possible_forbidden_knowledge")
            gates.append("continuity_gate")
            risk_level = "high"
        if not gates:
            gates.append("none")
            risk_level = "none" if candidate.continuity_risk_level == "none" else risk_level
        gates = self._unique(gates)
        primary = "" if gates == ["none"] else gates[0]
        return CharacterIntentRiskReport(
            risk_report_id=f"intent_risk_{candidate.action_intention_candidate_id}",
            project_id=candidate.project_id,
            action_intention_candidate_id=candidate.action_intention_candidate_id,
            chapter_id=candidate.chapter_id,
            scene_id=candidate.scene_id,
            scene_index=candidate.scene_index,
            character_id=candidate.character_id,
            tier=candidate.tier,
            risk_level=risk_level,
            risk_categories=self._unique(categories),
            possible_forbidden_knowledge=possible_forbidden_knowledge,
            possible_location_conflict=possible_location_conflict,
            possible_relationship_conflict=possible_relationship_conflict,
            possible_world_rule_conflict=possible_world_rule_conflict,
            possible_major_state_change=possible_major_state_change,
            possible_apparent_contradiction=possible_apparent_contradiction,
            primary_next_gate=primary,
            recommended_next_gates=gates,
            safe_summary=(
                f"Candidate {candidate.action_intention_candidate_id} is a "
                f"{risk_level} pre-gate risk only; it resolves nothing."
            ),
            warnings=candidate.warnings,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _build_package(
        self,
        *,
        scene_participation: SceneParticipationPackage,
        tiered_context: TieredCharacterContextPackage,
        scene_memory_pack: SceneMemoryPack,
        chapter_memory_pack: ChapterMemoryPack | None,
        traces: list[CharacterPsychologyTrace],
        metas: list[CharacterPsychologyTraceRuntimeMeta],
        candidates: list[CharacterActionIntentionCandidate],
        risk_reports: list[CharacterIntentRiskReport],
        warnings: list[str],
        timestamp: str,
    ) -> TieredCharacterIntentPackage:
        high_or_blocking_ids = {
            report.action_intention_candidate_id
            for report in risk_reports
            if report.risk_level in {"high", "blocking"}
        }
        blocked_ids = [
            report.action_intention_candidate_id
            for report in risk_reports
            if report.risk_level == "blocking"
        ]
        needs_gate_ids = [
            candidate.action_intention_candidate_id
            for candidate in candidates
            if candidate.requires_continuity_gate
            or candidate.requires_apparent_gate
            or candidate.requires_quality_gate
            or candidate.requires_user_confirmation_candidate
        ]
        writer_ready_ids = [
            candidate.action_intention_candidate_id
            for candidate in candidates
            if candidate.can_be_used_by_writer
            and candidate.action_intention_candidate_id not in high_or_blocking_ids
        ]
        trace_counts = {tier: 0 for tier in ["A", "B", "C", "D"]}
        tier_by_character = {meta.character_id: meta.tier for meta in metas}
        for trace in traces:
            tier = tier_by_character.get(trace.character_id, "D")
            trace_counts[tier] = trace_counts.get(tier, 0) + 1
        status = "blocked" if blocked_ids else ("warning" if needs_gate_ids or warnings else "ready")
        return TieredCharacterIntentPackage(
            tiered_character_intent_package_id=(
                f"tiered_character_intent_{scene_participation.scene_participation_package_id}"
            ),
            project_id=scene_participation.project_id,
            scene_participation_package_id=scene_participation.scene_participation_package_id,
            tiered_character_context_package_id=tiered_context.tiered_character_context_package_id,
            scene_memory_pack_id=scene_memory_pack.scene_memory_pack_id,
            chapter_memory_pack_id=(
                chapter_memory_pack.chapter_memory_pack_id if chapter_memory_pack else ""
            ),
            chapter_id=scene_participation.chapter_id,
            scene_id=scene_participation.scene_id or "",
            scene_index=scene_participation.scene_index,
            active_character_ids=scene_participation.active_character_ids,
            psychology_trace_ids=[trace.psychology_trace_id for trace in traces],
            psychology_trace_runtime_meta_ids=[meta.runtime_meta_id for meta in metas],
            action_intention_candidate_ids=[
                candidate.action_intention_candidate_id for candidate in candidates
            ],
            risk_report_ids=[report.risk_report_id for report in risk_reports],
            a_trace_count=trace_counts.get("A", 0),
            b_trace_count=trace_counts.get("B", 0),
            c_trace_count=trace_counts.get("C", 0),
            d_trace_count=trace_counts.get("D", 0),
            writer_ready_candidate_ids=writer_ready_ids,
            blocked_candidate_ids=blocked_ids,
            needs_gate_candidate_ids=needs_gate_ids,
            warnings=self._unique(warnings),
            safe_summary=(
                "M6 candidate-only psychology/action-intention package for "
                f"{len(scene_participation.active_character_ids)} selected participants."
            ),
            status=status,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _response_for_package(
        self,
        package: TieredCharacterIntentPackage,
    ) -> CharacterIntentPackageReadResponse:
        trace_ids = set(package.psychology_trace_ids)
        meta_ids = set(package.psychology_trace_runtime_meta_ids)
        candidate_ids = set(package.action_intention_candidate_ids)
        risk_ids = set(package.risk_report_ids)
        traces = [
            trace
            for trace in self.narrative_layer_service.list_psychology_traces()
            if trace.psychology_trace_id in trace_ids
        ]
        metas = [
            meta
            for meta in self._read_models(
                self.runtime_meta_file,
                CharacterPsychologyTraceRuntimeMeta,
            )
            if meta.runtime_meta_id in meta_ids
        ]
        candidates = [
            candidate
            for candidate in self._read_models(
                self.candidates_file,
                CharacterActionIntentionCandidate,
            )
            if candidate.action_intention_candidate_id in candidate_ids
        ]
        risk_reports = [
            report
            for report in self._read_models(
                self.risk_reports_file,
                CharacterIntentRiskReport,
            )
            if report.risk_report_id in risk_ids
        ]
        return CharacterIntentPackageReadResponse(
            package=package,
            psychology_traces=traces,
            psychology_trace_runtime_meta=metas,
            action_intention_candidates=candidates,
            risk_reports=risk_reports,
            warnings=package.warnings,
        )

    def _current_for_scene_participation(
        self,
        scene_participation_package_id: str,
    ) -> TieredCharacterIntentPackage | None:
        matches = [
            package
            for package in self._read_models(
                self.packages_file,
                TieredCharacterIntentPackage,
            )
            if package.scene_participation_package_id == scene_participation_package_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def _get_scene_participation_package(
        self,
        package_id: str,
    ) -> SceneParticipationPackage:
        package = next(
            (
                item
                for item in self._read_models(
                    self.scene_participation_file,
                    SceneParticipationPackage,
                )
                if item.scene_participation_package_id == package_id
            ),
            None,
        )
        if package is None:
            raise StorageError("CHARACTER_INTENT_SCENE_PARTICIPATION_PACKAGE_NOT_FOUND")
        return package

    def _get_tiered_context_package(
        self,
        package_id: str,
        scene_participation_package_id: str,
    ) -> TieredCharacterContextPackage:
        packages = self._read_models(
            self.tiered_context_file,
            TieredCharacterContextPackage,
        )
        package = next(
            (
                item
                for item in packages
                if item.tiered_character_context_package_id == package_id
            ),
            None,
        )
        if package is None:
            package = next(
                (
                    item
                    for item in packages
                    if item.scene_participation_package_id == scene_participation_package_id
                ),
                None,
            )
        if package is None:
            raise StorageError("CHARACTER_INTENT_TIERED_CONTEXT_PACKAGE_NOT_FOUND")
        return package

    def _get_scene_memory_pack(self, pack_id: str) -> SceneMemoryPack:
        raw = self.repositories.scene_memory_packs.get_by_id(str(pack_id or "").strip())
        if raw is None:
            raise StorageError("CHARACTER_INTENT_SCENE_MEMORY_PACK_NOT_FOUND")
        return SceneMemoryPack(**raw)

    def _get_chapter_memory_pack(
        self,
        pack_id: str,
        chapter_id: str,
    ) -> ChapterMemoryPack | None:
        if pack_id:
            raw = self.repositories.chapter_memory_packs.get_by_id(pack_id)
            if raw is not None:
                return ChapterMemoryPack(**raw)
        candidates = [
            ChapterMemoryPack(**raw)
            for raw in self.repositories.chapter_memory_packs.list_packs()
            if isinstance(raw, dict)
            and raw.get("chapter_id") == chapter_id
            and raw.get("status", "active") == "active"
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.updated_at, reverse=True)[0]

    def _characters_by_id(self) -> dict[str, Character]:
        result: dict[str, Character] = {}
        for raw in self.repositories.characters.list_all():
            if not isinstance(raw, dict):
                continue
            try:
                character = Character(**raw)
            except ValidationError:
                continue
            result[character.character_id] = character
        return result

    def _project_id_from_any_package(self) -> str:
        package = next(
            iter(
                self._read_models(
                    self.scene_participation_file,
                    SceneParticipationPackage,
                )
            ),
            None,
        )
        return package.project_id if package else ""

    def _tier_for(self, character: Character, participant: Any) -> str:
        tier = str(getattr(participant, "tier", "") or character.tier or "D").upper()
        return tier if tier in {"A", "B", "C", "D"} else "D"

    def _depth_for_tier(
        self,
        policy: CharacterIntentGenerationPolicy,
        tier: str,
    ) -> str:
        return {
            "A": policy.a_trace_depth,
            "B": policy.b_trace_depth,
            "C": policy.c_trace_depth,
            "D": policy.d_trace_depth,
        }.get(tier, "minimal")

    def _memory_refs_for_character(
        self,
        *,
        character_id: str,
        context_item: CharacterContextItem | None,
        scene_memory_pack: SceneMemoryPack,
    ) -> list[dict[str, Any]]:
        context_memory_ids = set(context_item.source_memory_ids if context_item else [])
        refs: list[dict[str, Any]] = []
        for bucket in [
            scene_memory_pack.must_use_context,
            scene_memory_pack.should_use_context,
            scene_memory_pack.optional_context,
        ]:
            for ref in bucket:
                raw = model_to_dict(ref)
                if raw.get("source_object_id") == character_id:
                    refs.append(raw)
                    continue
                if raw.get("memory_id") and raw.get("memory_id") in context_memory_ids:
                    refs.append(raw)
        return refs

    def _memory_trigger(
        self,
        memory_refs: list[dict[str, Any]],
        context_item: CharacterContextItem | None,
    ) -> str:
        summaries = [
            str(ref.get("summary") or "").strip()
            for ref in memory_refs
            if str(ref.get("summary") or "").strip()
        ]
        if summaries:
            return summaries[0]
        if context_item and context_item.memory_summary:
            return context_item.memory_summary
        return "current scene context"

    def _read_models(self, path: Path, model: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        raw = self.store.read_any(path)
        if not isinstance(raw, list):
            raise StorageError(f"CHARACTER_INTENT_INVALID_STORAGE:{path.name}")
        result: list[Any] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(model(**item))
            except ValidationError as exc:
                raise StorageError(
                    f"CHARACTER_INTENT_INVALID_STORAGE:{path.name}"
                ) from exc
        return result

    def _upsert_model(self, path: Path, model: BaseModel, id_field: str) -> None:
        self._upsert_models(path, [model], id_field)

    def _upsert_models(self, path: Path, models: list[BaseModel], id_field: str) -> None:
        rows: list[dict[str, Any]] = []
        if self.store.exists(path):
            raw = self.store.read_any(path)
            if not isinstance(raw, list):
                raise StorageError(f"CHARACTER_INTENT_INVALID_STORAGE:{path.name}")
            rows = [dict(item) for item in raw if isinstance(item, dict)]
        by_id = {str(row.get(id_field) or ""): row for row in rows}
        for model in models:
            payload = model_to_dict(model)
            target_id = str(payload.get(id_field) or "")
            by_id[target_id] = payload
        self.store.write(path, list(by_id.values()))

    def _first(self, values: list[Any]) -> str:
        return str(values[0] if values else "").strip()

    def _unique(self, values: list[Any]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = str(value or "").strip()
            if not clean:
                continue
            key = clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(clean)
        return result
