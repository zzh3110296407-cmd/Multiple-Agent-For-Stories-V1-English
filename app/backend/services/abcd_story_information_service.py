import copy
import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.abcd_story_information import (
    ABCDStoryInformationIntegrationReport,
    ABCDStoryInformationMergePreviewResponse,
    ABCDStoryInformationPackage,
    ABCDStoryInformationPackageBuildResponse,
    ABCDStoryInformationPackageReadResponse,
    CharacterIntentStoryInformationItem,
    WriterABCDContextView,
)
from app.backend.models.character_intent import (
    CharacterActionIntentionCandidate,
    CharacterIntentRiskReport,
)
from app.backend.models.scene_generation import (
    OrderedStoryInformationPackage,
    StoryInformationItem,
)
from app.backend.services.character_intent_service import (
    TieredCharacterIntentPackageService,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.scene_generation_service import SceneGenerationService
from app.backend.storage.json_store import JsonStore, StorageError


CHARACTER_INTENT_STORY_INFORMATION_ITEMS_FILE = (
    "character_intent_story_information_items.json"
)
ABCD_STORY_INFORMATION_PACKAGES_FILE = "abcd_story_information_packages.json"
WRITER_ABCD_CONTEXT_VIEWS_FILE = "writer_abcd_context_views.json"
ABCD_STORY_INFORMATION_INTEGRATION_REPORTS_FILE = (
    "abcd_story_information_integration_reports.json"
)
FORBIDDEN_STORY_FACT_FILES = [
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "characters.json",
    "relationships.json",
    "scenes.json",
    "story_information_items.json",
]
NON_OBJECTIVE_TRUTH_STATUSES = {
    "subjective_claim",
    "perception",
    "lie",
    "misinformation",
    "unknown",
}
HIGH_RISK_LEVELS = {"high", "blocking"}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ABCDStoryInformationSafetyGuard:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def snapshot(self) -> dict[str, str]:
        return {
            file_name: self._hash_file(self.data_dir / file_name)
            for file_name in FORBIDDEN_STORY_FACT_FILES
        }

    def delta(self, before: dict[str, str]) -> dict[str, dict[str, str]]:
        after = self.snapshot()
        return {
            file_name: {
                "before": before.get(file_name, ""),
                "after": after.get(file_name, ""),
            }
            for file_name in FORBIDDEN_STORY_FACT_FILES
            if before.get(file_name, "") != after.get(file_name, "")
        }

    def assert_unchanged(self, before: dict[str, str]) -> dict[str, dict[str, str]]:
        delta = self.delta(before)
        if delta:
            raise StorageError(
                "ABCD_STORY_INFORMATION_FORBIDDEN_STORY_FACT_MUTATION:"
                + ",".join(sorted(delta))
            )
        return delta

    def _hash_file(self, path: Path) -> str:
        if not path.exists():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()


class ABCDStoryInformationService:
    """Adapts M6 candidate-only psychology outputs into writer-safe story information."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        character_intent_service: TieredCharacterIntentPackageService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.character_intent_service = (
            character_intent_service
            or TieredCharacterIntentPackageService(
                store=self.store,
                data_dir=self.data_dir,
            )
        )
        self.safety_guard = ABCDStoryInformationSafetyGuard(self.data_dir)
        self.items_file = self.data_dir / CHARACTER_INTENT_STORY_INFORMATION_ITEMS_FILE
        self.packages_file = self.data_dir / ABCD_STORY_INFORMATION_PACKAGES_FILE
        self.writer_views_file = self.data_dir / WRITER_ABCD_CONTEXT_VIEWS_FILE
        self.integration_reports_file = (
            self.data_dir / ABCD_STORY_INFORMATION_INTEGRATION_REPORTS_FILE
        )
        self.characters_file = self.data_dir / "characters.json"

    def build_package(
        self,
        tiered_character_intent_package_id: str,
        *,
        force_refresh: bool = False,
    ) -> ABCDStoryInformationPackageBuildResponse:
        clean_id = str(tiered_character_intent_package_id or "").strip()
        if not clean_id:
            raise StorageError("ABCD_STORY_INFORMATION_INTENT_PACKAGE_ID_REQUIRED")
        existing = self._current_for_intent_package(clean_id)
        if existing is not None and not force_refresh:
            response = self._response_for_package(existing)
            if response.package is None or response.writer_view is None or response.integration_report is None:
                raise StorageError("ABCD_STORY_INFORMATION_PACKAGE_INCOMPLETE")
            return ABCDStoryInformationPackageBuildResponse(
                package=response.package,
                items=response.items,
                writer_view=response.writer_view,
                integration_report=response.integration_report,
                warnings=response.warnings,
            )

        before = self.safety_guard.snapshot()
        source_response = self.character_intent_service.get_package(clean_id)
        source_package = source_response.package
        if source_package is None:
            raise StorageError("ABCD_STORY_INFORMATION_SOURCE_PACKAGE_NOT_FOUND")
        if source_package.candidate_only is not True or source_package.no_story_fact_written is not True:
            raise StorageError("ABCD_STORY_INFORMATION_SOURCE_PACKAGE_NOT_SAFE")

        timestamp = utc_now()
        package_id = f"abcd_story_info_{source_package.tiered_character_intent_package_id}"
        risks_by_candidate_id = {
            risk.action_intention_candidate_id: risk
            for risk in source_response.risk_reports
        }
        character_names = self._character_names_by_id()
        character_tiers = self._character_tiers_by_id()
        candidate_tiers = self._tier_by_character(
            source_response.action_intention_candidates
        )
        tier_by_character = {**character_tiers, **candidate_tiers}
        items = self._items_from_candidates(
            package_id=package_id,
            source_package_id=source_package.tiered_character_intent_package_id,
            candidates=source_response.action_intention_candidates,
            risks_by_candidate_id=risks_by_candidate_id,
            active_character_ids=source_package.active_character_ids,
            character_names=character_names,
            timestamp=timestamp,
        )
        items.extend(
            self._fallback_constraints_for_missing_active_characters(
                package_id=package_id,
                source_package_id=source_package.tiered_character_intent_package_id,
                source_scene_participation_package_id=source_package.scene_participation_package_id,
                project_id=source_package.project_id,
                chapter_id=source_package.chapter_id,
                scene_id=source_package.scene_id,
                scene_index=source_package.scene_index,
                active_character_ids=source_package.active_character_ids,
                represented_character_ids=[
                    item.character_id
                    for item in items
                    if item.safe_for_writer
                ],
                tier_by_character=tier_by_character,
                trace_id_by_character=self._trace_id_by_character(
                    source_response.action_intention_candidates
                ),
                character_names=character_names,
                timestamp=timestamp,
            )
        )
        ordered = self._order_story_information(
            [item.base_story_information_item for item in items]
        )
        writer_view_id = f"writer_view_{package_id}"
        integration_report_id = f"integration_report_{package_id}"
        priority_counts = self._count_by(
            [item.base_story_information_item.priority for item in items]
        )
        tier_counts = self._count_by([item.tier for item in items])
        semantic_type_counts = self._count_by([item.m7_semantic_type for item in items])
        writer_ready_item_ids = [
            item.item_id
            for item in items
            if item.safe_for_writer
            and item.base_story_information_item.priority != "do_not_use"
        ]
        do_not_use_item_ids = [
            item.item_id
            for item in items
            if item.base_story_information_item.priority == "do_not_use"
        ]
        constraint_item_ids = [
            item.item_id
            for item in items
            if item.m7_semantic_type == "participant_continuity_constraint"
        ]
        status = "ready" if writer_ready_item_ids else "blocked"
        if status == "ready" and do_not_use_item_ids:
            status = "warning"

        package = ABCDStoryInformationPackage(
            abcd_story_information_package_id=package_id,
            project_id=source_package.project_id,
            source_tiered_character_intent_package_id=source_package.tiered_character_intent_package_id,
            source_scene_participation_package_id=source_package.scene_participation_package_id,
            source_scene_memory_pack_id=source_package.scene_memory_pack_id,
            source_tiered_character_context_package_id=source_package.tiered_character_context_package_id,
            chapter_id=source_package.chapter_id,
            scene_id=source_package.scene_id,
            scene_index=source_package.scene_index,
            active_character_ids=source_package.active_character_ids,
            related_character_ids=source_package.active_character_ids,
            item_ids=[item.item_id for item in items],
            writer_ready_item_ids=writer_ready_item_ids,
            do_not_use_item_ids=do_not_use_item_ids,
            constraint_item_ids=constraint_item_ids,
            tier_counts=tier_counts,
            priority_counts=priority_counts,
            semantic_type_counts=semantic_type_counts,
            writer_ready=bool(writer_ready_item_ids),
            ordered_story_information_package=ordered,
            writer_view_id=writer_view_id,
            integration_report_id=integration_report_id,
            status=status,
            safe_summary=(
                "M7 writer-safe ABCD StoryInformation package adapted from "
                "candidate-only character intent outputs."
            ),
            warnings=self._unique(source_response.warnings),
            created_at=timestamp,
            updated_at=timestamp,
        )
        writer_view = self._build_writer_view(
            package=package,
            ordered=ordered,
            timestamp=timestamp,
        )
        story_delta = self.safety_guard.delta(before)
        integration_report = self._build_integration_report(
            package=package,
            source_candidate_count=len(source_response.action_intention_candidates),
            items=items,
            risks_by_candidate_id=risks_by_candidate_id,
            story_delta=story_delta,
            timestamp=timestamp,
        )

        self._upsert_models(self.items_file, items, "item_id")
        self._upsert_models(
            self.packages_file,
            [package],
            "abcd_story_information_package_id",
        )
        self._upsert_models(self.writer_views_file, [writer_view], "writer_view_id")
        self._upsert_models(
            self.integration_reports_file,
            [integration_report],
            "integration_report_id",
        )
        self.safety_guard.assert_unchanged(before)
        return ABCDStoryInformationPackageBuildResponse(
            package=package,
            items=items,
            writer_view=writer_view,
            integration_report=integration_report,
            warnings=package.warnings,
        )

    def get_package(self, package_id: str) -> ABCDStoryInformationPackageReadResponse:
        clean_id = str(package_id or "").strip()
        package = next(
            (
                item
                for item in self._read_models(
                    self.packages_file,
                    ABCDStoryInformationPackage,
                )
                if item.abcd_story_information_package_id == clean_id
            ),
            None,
        )
        if package is None:
            raise StorageError("ABCD_STORY_INFORMATION_PACKAGE_NOT_FOUND")
        return self._response_for_package(package)

    def get_current_package(
        self,
        *,
        chapter_id: str,
        scene_index: int,
    ) -> ABCDStoryInformationPackageReadResponse:
        packages = [
            package
            for package in self._read_models(
                self.packages_file,
                ABCDStoryInformationPackage,
            )
            if package.chapter_id == str(chapter_id or "").strip()
            and package.scene_index == int(scene_index)
        ]
        if not packages:
            return ABCDStoryInformationPackageReadResponse()
        package = sorted(packages, key=lambda item: item.updated_at, reverse=True)[0]
        return self._response_for_package(package)

    def get_writer_view(self, package_id: str) -> WriterABCDContextView:
        response = self.get_package(package_id)
        if response.writer_view is None:
            raise StorageError("ABCD_STORY_INFORMATION_WRITER_VIEW_NOT_FOUND")
        return response.writer_view

    def get_integration_report(
        self,
        package_id: str,
    ) -> ABCDStoryInformationIntegrationReport:
        response = self.get_package(package_id)
        if response.integration_report is None:
            raise StorageError("ABCD_STORY_INFORMATION_INTEGRATION_REPORT_NOT_FOUND")
        return response.integration_report

    def merge_preview(
        self,
        package_id: str,
        *,
        base_scene_information: dict[str, Any],
    ) -> ABCDStoryInformationMergePreviewResponse:
        response = self.get_package(package_id)
        if response.package is None:
            raise StorageError("ABCD_STORY_INFORMATION_PACKAGE_NOT_FOUND")
        merged = copy.deepcopy(base_scene_information or {})
        raw_items = copy.deepcopy(merged.get("story_information_list") or [])
        base_items: list[StoryInformationItem] = []
        for index, raw_item in enumerate(raw_items, start=1):
            normalized = self._normalize_story_information_item(raw_item, index)
            try:
                base_items.append(StoryInformationItem(**normalized))
            except ValidationError:
                continue
        added_items = [item.base_story_information_item for item in response.items]
        all_items = [*base_items, *added_items]
        merged["story_information_list"] = [model_to_dict(item) for item in all_items]
        ordered = self._order_story_information(all_items)
        return ABCDStoryInformationMergePreviewResponse(
            abcd_story_information_package_id=response.package.abcd_story_information_package_id,
            merged_scene_information=merged,
            added_story_information_item_ids=[item.item_id for item in added_items],
            ordered_story_information_package=ordered,
            no_write=True,
            warnings=response.warnings,
        )

    def _items_from_candidates(
        self,
        *,
        package_id: str,
        source_package_id: str,
        candidates: list[CharacterActionIntentionCandidate],
        risks_by_candidate_id: dict[str, CharacterIntentRiskReport],
        active_character_ids: list[str],
        character_names: dict[str, str],
        timestamp: str,
    ) -> list[CharacterIntentStoryInformationItem]:
        items: list[CharacterIntentStoryInformationItem] = []
        active_set = set(active_character_ids)
        usable_count_by_character: dict[str, int] = {}
        for candidate in candidates:
            if candidate.character_id not in active_set:
                continue
            risk = risks_by_candidate_id.get(candidate.action_intention_candidate_id)
            is_blocked = self._candidate_should_be_do_not_use(candidate, risk)
            semantic_type = self._semantic_type(candidate, risk, is_blocked)
            priority = self._priority_for_candidate(
                candidate,
                risk,
                is_blocked,
                usable_count_by_character.get(candidate.character_id, 0),
            )
            base_type = self._base_type_for_semantic(semantic_type)
            writer_bucket = self._writer_bucket_for(base_type, priority)
            content = self._content_for_candidate(
                candidate=candidate,
                risk=risk,
                semantic_type=semantic_type,
                priority=priority,
                character_name=character_names.get(candidate.character_id, candidate.character_id),
            )
            base_item = StoryInformationItem(
                item_id=f"story_info_{candidate.action_intention_candidate_id}",
                type=base_type,
                content=content,
                source_node="CharacterIntentStoryInformationAdapter",
                priority=priority,
                related_character_ids=[candidate.character_id],
                order_hint=self._order_hint(candidate, priority),
            )
            item = CharacterIntentStoryInformationItem(
                item_id=f"abcd_story_info_item_{candidate.action_intention_candidate_id}",
                project_id=candidate.project_id,
                abcd_story_information_package_id=package_id,
                source_tiered_character_intent_package_id=source_package_id,
                source_scene_participation_package_id=candidate.scene_participation_package_id,
                source_psychology_trace_id=candidate.psychology_trace_id,
                source_action_intention_candidate_id=candidate.action_intention_candidate_id,
                source_risk_report_id=risk.risk_report_id if risk is not None else "",
                chapter_id=candidate.chapter_id,
                scene_id=candidate.scene_id,
                scene_index=candidate.scene_index,
                character_id=candidate.character_id,
                tier=candidate.tier,
                truth_status=candidate.truth_status,
                risk_level=risk.risk_level if risk is not None else candidate.continuity_risk_level,
                m7_semantic_type=semantic_type,
                writer_bucket=writer_bucket,
                base_story_information_item=base_item,
                safe_summary=self._truncate(candidate.safe_summary, 220),
                writer_instruction=content,
                safe_for_writer=priority != "do_not_use",
                warnings=self._unique([*candidate.warnings, *((risk.warnings if risk else []) or [])]),
                created_at=timestamp,
                updated_at=timestamp,
            )
            items.append(item)
            if item.safe_for_writer:
                usable_count_by_character[candidate.character_id] = (
                    usable_count_by_character.get(candidate.character_id, 0) + 1
                )
        return items

    def _fallback_constraints_for_missing_active_characters(
        self,
        *,
        package_id: str,
        source_package_id: str,
        source_scene_participation_package_id: str,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
        active_character_ids: list[str],
        represented_character_ids: list[str],
        tier_by_character: dict[str, str],
        trace_id_by_character: dict[str, str],
        character_names: dict[str, str],
        timestamp: str,
    ) -> list[CharacterIntentStoryInformationItem]:
        represented = set(represented_character_ids)
        items: list[CharacterIntentStoryInformationItem] = []
        for character_id in active_character_ids:
            if character_id in represented:
                continue
            character_name = character_names.get(character_id, character_id)
            content = (
                f"Continuity constraint: keep {character_name} present only as an "
                "approved selected participant. Do not invent new actions, memory, "
                "or objective facts for this character from this package."
            )
            base_item = StoryInformationItem(
                item_id=f"story_info_abcd_constraint_{character_id}",
                type="world_rule",
                content=content,
                source_node="CharacterIntentStoryInformationAdapter",
                priority="should_use",
                related_character_ids=[character_id],
                order_hint=850,
            )
            items.append(
                CharacterIntentStoryInformationItem(
                    item_id=f"abcd_story_info_item_constraint_{character_id}",
                    project_id=project_id,
                    abcd_story_information_package_id=package_id,
                    source_tiered_character_intent_package_id=source_package_id,
                    source_scene_participation_package_id=source_scene_participation_package_id,
                    source_psychology_trace_id=trace_id_by_character.get(character_id, ""),
                    chapter_id=chapter_id,
                    scene_id=scene_id,
                    scene_index=scene_index,
                    character_id=character_id,
                    tier=self._valid_tier(tier_by_character.get(character_id)),
                    truth_status="unknown",
                    risk_level="medium",
                    m7_semantic_type="participant_continuity_constraint",
                    writer_bucket="opening_context",
                    base_story_information_item=base_item,
                    safe_summary=f"{character_name} has no writer-safe M6 candidate.",
                    writer_instruction=content,
                    safe_for_writer=True,
                    warnings=["fallback_participant_constraint"],
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        return items

    def _candidate_should_be_do_not_use(
        self,
        candidate: CharacterActionIntentionCandidate,
        risk: CharacterIntentRiskReport | None,
    ) -> bool:
        risk_level = risk.risk_level if risk is not None else candidate.continuity_risk_level
        if candidate.can_be_used_by_writer is not True:
            return True
        if risk_level in HIGH_RISK_LEVELS or candidate.continuity_risk_level in HIGH_RISK_LEVELS:
            return True
        if candidate.requires_user_confirmation_candidate:
            return True
        if risk is None:
            return False
        return any(
            [
                risk.possible_forbidden_knowledge,
                risk.possible_major_state_change,
                risk.risk_level in HIGH_RISK_LEVELS,
            ]
        )

    def _semantic_type(
        self,
        candidate: CharacterActionIntentionCandidate,
        risk: CharacterIntentRiskReport | None,
        is_blocked: bool,
    ) -> str:
        if is_blocked:
            return "do_not_use"
        if candidate.truth_status in NON_OBJECTIVE_TRUTH_STATUSES:
            return "subjective_claim_hint"
        risk_level = risk.risk_level if risk is not None else candidate.continuity_risk_level
        if (
            risk_level == "medium"
            or candidate.requires_continuity_gate
            or candidate.requires_apparent_gate
            or candidate.requires_quality_gate
        ):
            return "participant_continuity_constraint"
        return "character_expression"

    def _priority_for_candidate(
        self,
        candidate: CharacterActionIntentionCandidate,
        risk: CharacterIntentRiskReport | None,
        is_blocked: bool,
        usable_count_for_character: int,
    ) -> str:
        if is_blocked:
            return "do_not_use"
        if candidate.truth_status in NON_OBJECTIVE_TRUTH_STATUSES:
            return "should_use"
        risk_level = risk.risk_level if risk is not None else candidate.continuity_risk_level
        if risk_level == "medium":
            return "should_use"
        return "should_use" if usable_count_for_character == 0 else "optional"

    def _base_type_for_semantic(self, semantic_type: str) -> str:
        if semantic_type == "participant_continuity_constraint":
            return "world_rule"
        return "character_turn"

    def _writer_bucket_for(self, base_type: str, priority: str) -> str:
        if priority == "do_not_use":
            return "do_not_include"
        if base_type == "world_rule":
            return "opening_context"
        if base_type == "character_turn":
            return "character_turns"
        return "scene_progression"

    def _content_for_candidate(
        self,
        *,
        candidate: CharacterActionIntentionCandidate,
        risk: CharacterIntentRiskReport | None,
        semantic_type: str,
        priority: str,
        character_name: str,
    ) -> str:
        expression = self._safe_expression(candidate)
        if priority == "do_not_use":
            return self._truncate(
                f"Do not use for drafting: {character_name} candidate "
                f"'{candidate.intention_type}' requires confirmation or gate review. "
                "Do not turn it into scene action or objective fact. "
                "Do not present it as objective fact.",
                260,
            )
        if semantic_type == "subjective_claim_hint":
            truth_label = candidate.truth_status.replace("_", " ")
            return self._truncate(
                f"{character_name} may express this only as {truth_label}: "
                f"{expression}. Do not present it as objective fact.",
                240 if candidate.tier == "D" else 320,
            )
        if semantic_type == "participant_continuity_constraint":
            gates = []
            if risk is not None:
                gates = [gate for gate in risk.recommended_next_gates if gate != "none"]
            gate_text = ", ".join(gates) if gates else "quality/continuity review"
            return self._truncate(
                f"Constraint for {character_name}: use as a tentative behavior hint "
                f"only; keep it consistent with {gate_text}. {expression}",
                240 if candidate.tier == "D" else 320,
            )
        return self._truncate(
            f"{character_name}: {expression}. Use as a character action/intention hint, "
            "not as a new objective fact.",
            240 if candidate.tier == "D" else 320,
        )

    def _safe_expression(self, candidate: CharacterActionIntentionCandidate) -> str:
        text = (
            candidate.outward_expression_hint
            or candidate.intention_summary
            or candidate.safe_summary
        )
        return self._truncate(str(text or "").strip(), 180)

    def _order_hint(
        self,
        candidate: CharacterActionIntentionCandidate,
        priority: str,
    ) -> int:
        tier_order = {"A": 100, "B": 200, "C": 300, "D": 400}.get(candidate.tier, 900)
        if priority == "do_not_use":
            return tier_order + 90
        return tier_order + 10

    def _build_writer_view(
        self,
        *,
        package: ABCDStoryInformationPackage,
        ordered: OrderedStoryInformationPackage,
        timestamp: str,
    ) -> WriterABCDContextView:
        guardrails = [
            "Use these ABCD hints as candidate-only context.",
            "Do not convert subjective claims, perceptions, lies, or unknowns into objective facts.",
            "Do not add unselected characters from this package.",
        ]
        return WriterABCDContextView(
            writer_view_id=package.writer_view_id,
            abcd_story_information_package_id=package.abcd_story_information_package_id,
            project_id=package.project_id,
            chapter_id=package.chapter_id,
            scene_id=package.scene_id,
            scene_index=package.scene_index,
            related_character_ids=package.related_character_ids,
            opening_context=ordered.opening_context,
            scene_progression=ordered.scene_progression,
            character_turns=ordered.character_turns,
            required_reveals=ordered.required_reveals,
            emotional_beats=ordered.emotional_beats,
            ending_beat=ordered.ending_beat,
            do_not_include=ordered.do_not_include,
            guardrails=guardrails,
            safe_summary=(
                "Writer view exposes ordered ABCD participant hints without raw psychology chains."
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _build_integration_report(
        self,
        *,
        package: ABCDStoryInformationPackage,
        source_candidate_count: int,
        items: list[CharacterIntentStoryInformationItem],
        risks_by_candidate_id: dict[str, CharacterIntentRiskReport],
        story_delta: dict[str, dict[str, str]],
        timestamp: str,
    ) -> ABCDStoryInformationIntegrationReport:
        represented = self._unique(
            [
                item.character_id
                for item in items
                if item.safe_for_writer
                or item.base_story_information_item.priority == "do_not_use"
            ]
        )
        blocked_candidate_ids = [
            item.source_action_intention_candidate_id
            for item in items
            if item.base_story_information_item.priority == "do_not_use"
            and item.source_action_intention_candidate_id
        ]
        issues: list[str] = []
        if story_delta:
            issues.append("forbidden_story_fact_file_delta_detected")
        if (self.data_dir / "story_information_items.json").exists():
            issues.append("generic_story_information_items_file_exists")
        return ABCDStoryInformationIntegrationReport(
            integration_report_id=package.integration_report_id,
            abcd_story_information_package_id=package.abcd_story_information_package_id,
            project_id=package.project_id,
            source_tiered_character_intent_package_id=package.source_tiered_character_intent_package_id,
            chapter_id=package.chapter_id,
            scene_id=package.scene_id,
            scene_index=package.scene_index,
            source_candidate_count=source_candidate_count,
            converted_item_count=len(items),
            selected_character_ids=package.active_character_ids,
            represented_character_ids=represented,
            blocked_candidate_ids=blocked_candidate_ids,
            do_not_use_item_ids=package.do_not_use_item_ids,
            truth_status_counts=self._count_by([item.truth_status for item in items]),
            priority_counts=package.priority_counts,
            semantic_type_counts=package.semantic_type_counts,
            story_fact_file_delta=story_delta,
            no_story_fact_file_mutation=not story_delta,
            no_generic_story_information_write=not (
                self.data_dir / "story_information_items.json"
            ).exists(),
            no_writer_invocation=True,
            status="ready" if not issues else "blocked",
            issues=issues,
            warnings=package.warnings,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _response_for_package(
        self,
        package: ABCDStoryInformationPackage,
    ) -> ABCDStoryInformationPackageReadResponse:
        item_ids = set(package.item_ids)
        items = [
            item
            for item in self._read_models(
                self.items_file,
                CharacterIntentStoryInformationItem,
            )
            if item.item_id in item_ids
        ]
        writer_view = next(
            (
                view
                for view in self._read_models(
                    self.writer_views_file,
                    WriterABCDContextView,
                )
                if view.writer_view_id == package.writer_view_id
            ),
            None,
        )
        integration_report = next(
            (
                report
                for report in self._read_models(
                    self.integration_reports_file,
                    ABCDStoryInformationIntegrationReport,
                )
                if report.integration_report_id == package.integration_report_id
            ),
            None,
        )
        return ABCDStoryInformationPackageReadResponse(
            package=package,
            items=items,
            writer_view=writer_view,
            integration_report=integration_report,
            warnings=package.warnings,
        )

    def _current_for_intent_package(
        self,
        intent_package_id: str,
    ) -> ABCDStoryInformationPackage | None:
        matches = [
            package
            for package in self._read_models(
                self.packages_file,
                ABCDStoryInformationPackage,
            )
            if package.source_tiered_character_intent_package_id == intent_package_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def _order_story_information(
        self,
        items: list[StoryInformationItem],
    ) -> OrderedStoryInformationPackage:
        return SceneGenerationService.order_story_information(None, items)

    def _normalize_story_information_item(self, item: Any, index: int) -> dict[str, Any]:
        if isinstance(item, dict):
            normalized = dict(item)
        else:
            normalized = {"content": str(item or "")}
        normalized.setdefault("item_id", f"base_story_info_{index:03d}")
        normalized.setdefault("type", "scene_goal")
        normalized.setdefault("source_node", "SceneInformationAgent")
        normalized.setdefault("priority", "should_use")
        normalized.setdefault("content", "")
        normalized.setdefault("order_hint", index * 10)
        return normalized

    def _character_names_by_id(self) -> dict[str, str]:
        if not self.store.exists(self.characters_file):
            return {}
        raw = self.store.read_any(self.characters_file)
        if isinstance(raw, dict):
            raw_items = raw.get("characters") or raw.get("items") or []
        elif isinstance(raw, list):
            raw_items = raw
        else:
            raw_items = []
        names: dict[str, str] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            character_id = str(item.get("character_id") or "").strip()
            name = str(item.get("name") or character_id).strip()
            if character_id:
                names[character_id] = name
        return names

    def _character_tiers_by_id(self) -> dict[str, str]:
        if not self.store.exists(self.characters_file):
            return {}
        raw = self.store.read_any(self.characters_file)
        if isinstance(raw, dict):
            raw_items = raw.get("characters") or raw.get("items") or []
        elif isinstance(raw, list):
            raw_items = raw
        else:
            raw_items = []
        tiers: dict[str, str] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            character_id = str(item.get("character_id") or "").strip()
            tier = str(item.get("tier") or "").strip().upper()
            if character_id and tier in {"A", "B", "C", "D"}:
                tiers[character_id] = tier
        return tiers

    def _tier_by_character(
        self,
        candidates: list[CharacterActionIntentionCandidate],
    ) -> dict[str, str]:
        tiers: dict[str, str] = {}
        for candidate in candidates:
            if candidate.character_id and candidate.tier:
                tiers.setdefault(candidate.character_id, candidate.tier)
        return tiers

    def _trace_id_by_character(
        self,
        candidates: list[CharacterActionIntentionCandidate],
    ) -> dict[str, str]:
        trace_ids: dict[str, str] = {}
        for candidate in candidates:
            if candidate.character_id and candidate.psychology_trace_id:
                trace_ids.setdefault(candidate.character_id, candidate.psychology_trace_id)
        return trace_ids

    def _valid_tier(self, value: str | None) -> str:
        tier = str(value or "").strip().upper()
        if tier not in {"A", "B", "C", "D"}:
            raise StorageError("ABCD_STORY_INFORMATION_ACTIVE_CHARACTER_TIER_REQUIRED")
        return tier

    def _read_models(self, path: Path, model_cls: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        raw = self.store.read_any(path)
        if isinstance(raw, dict):
            if isinstance(raw.get("items"), list):
                raw_items = raw["items"]
            elif isinstance(raw.get("packages"), list):
                raw_items = raw["packages"]
            else:
                raw_items = []
        elif isinstance(raw, list):
            raw_items = raw
        else:
            raw_items = []
        models: list[Any] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                models.append(model_cls(**item))
            except ValidationError:
                continue
        return models

    def _upsert_models(
        self,
        path: Path,
        models: list[BaseModel],
        key_field: str,
    ) -> None:
        existing = self._read_raw_list(path)
        by_id: dict[str, dict[str, Any]] = {}
        for item in existing:
            if not isinstance(item, dict):
                continue
            key = str(item.get(key_field) or "").strip()
            if key:
                by_id[key] = item
        for model in models:
            payload = model_to_dict(model)
            key = str(payload.get(key_field) or "").strip()
            if not key:
                continue
            by_id[key] = payload
        self.store.write(path, list(by_id.values()))

    def _read_raw_list(self, path: Path) -> list[Any]:
        if not self.store.exists(path):
            return []
        raw = self.store.read_any(path)
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            for key in ("items", "packages", "records"):
                value = raw.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _count_by(self, values: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            key = str(value or "").strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _unique(self, values: list[Any]) -> list[str]:
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

    def _truncate(self, text: str, max_length: int) -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) <= max_length:
            return clean
        return clean[: max_length - 3].rstrip() + "..."
