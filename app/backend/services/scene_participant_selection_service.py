import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.character import Character, CharacterProfile
from app.backend.models.scene_participants import (
    SceneCDRoleCreationCandidate,
    SceneCDRoleReuseDecision,
    SceneParticipantSelection,
    SceneParticipantSelectionReport,
    SceneParticipantSelectionRequest,
    SceneParticipantSelectionResponse,
    SceneRoleCandidate,
    SceneRoleFunctionNeedRef,
)
from app.backend.services.abcd_runtime_participation_policy_service import now_utc
from app.backend.services.runtime_role_eligibility_service import RuntimeRoleEligibilityService
from app.backend.services.scene_cd_role_candidate_factory import SceneCDRoleCandidateFactory
from app.backend.services.scene_participant_selection_guard import SceneParticipantSelectionGuard
from app.backend.services.scene_role_candidate_search_service import SceneRoleCandidateSearchService
from app.backend.services.scene_role_need_resolver_service import SceneRoleNeedResolverService
from app.backend.storage.json_store import JsonStore, StorageError


SELECTIONS_FILE_NAME = "scene_participant_selections.json"
ROLE_CANDIDATES_FILE_NAME = "scene_role_candidates.json"
CREATION_CANDIDATES_FILE_NAME = "scene_cd_role_creation_candidates.json"
REUSE_DECISIONS_FILE_NAME = "scene_cd_role_reuse_decisions.json"
REPORTS_FILE_NAME = "scene_participant_selection_reports.json"


class SceneParticipantSelectionService:
    """Builds M3 C/D selection candidates without building scene context."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        need_resolver: SceneRoleNeedResolverService | None = None,
        candidate_search: SceneRoleCandidateSearchService | None = None,
        candidate_factory: SceneCDRoleCandidateFactory | None = None,
        guard: SceneParticipantSelectionGuard | None = None,
        runtime_role_eligibility: RuntimeRoleEligibilityService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.need_resolver = need_resolver or SceneRoleNeedResolverService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.candidate_search = candidate_search or SceneRoleCandidateSearchService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.candidate_factory = candidate_factory or SceneCDRoleCandidateFactory(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.guard = guard or SceneParticipantSelectionGuard(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.runtime_role_eligibility = runtime_role_eligibility or RuntimeRoleEligibilityService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.chapters_file = self.data_dir / "chapters.json"
        self.characters_file = self.data_dir / "characters.json"
        self.selections_file = self.data_dir / SELECTIONS_FILE_NAME
        self.role_candidates_file = self.data_dir / ROLE_CANDIDATES_FILE_NAME
        self.creation_candidates_file = self.data_dir / CREATION_CANDIDATES_FILE_NAME
        self.reuse_decisions_file = self.data_dir / REUSE_DECISIONS_FILE_NAME
        self.reports_file = self.data_dir / REPORTS_FILE_NAME

    def create_selection(
        self,
        request: SceneParticipantSelectionRequest,
    ) -> SceneParticipantSelectionResponse:
        chapter = self._find_chapter(request.chapter_id)
        role_needs = self.need_resolver.resolve_for_scene(
            chapter=chapter,
            scene_index=request.scene_index,
            scene_goal=request.scene_goal,
            scene_location=request.scene_location,
            previous_scene_result=request.previous_scene_result,
        )
        signature = self._signature(request, chapter, role_needs)
        if not request.force_refresh:
            existing = self._find_current_selection(
                chapter_id=chapter.chapter_id,
                scene_index=request.scene_index,
                source_query_signature=signature,
            )
            if existing is not None:
                return self._response_for_selection(existing)

        selection_id = f"scene_selection_{chapter.chapter_id}_{request.scene_index}_{signature[:12]}"
        selected_a_ids, selected_b_ids = self._carry_in_ab_ids(chapter)
        warnings: list[str] = []
        if not selected_a_ids:
            warnings.append("missing A-tier chapter carry-in")

        candidates: list[SceneRoleCandidate] = []
        creation_candidates: list[SceneCDRoleCreationCandidate] = []
        reuse_decisions: list[SceneCDRoleReuseDecision] = []
        selected_c_ids: list[str] = []
        selected_d_ids: list[str] = []
        selection_reasons: dict[str, str] = {}
        rejected_candidate_reasons: dict[str, str] = {}

        for need in role_needs:
            search_results = self.candidate_search.search_candidates(
                need=need,
                scene_index=request.scene_index,
                scene_goal=request.scene_goal,
                scene_location=request.scene_location,
                previous_scene_result=request.previous_scene_result,
            )
            candidates.extend(search_results)
            selected_candidate = self._choose_reuse_candidate(
                need=need,
                candidates=search_results,
                already_selected=set([*selected_c_ids, *selected_d_ids]),
                scene_index=request.scene_index,
            )
            if selected_candidate is not None and self._within_budget(
                selected_candidate,
                selected_c_ids=selected_c_ids,
                selected_d_ids=selected_d_ids,
                max_c_count=request.max_c_count,
                max_d_count=request.max_d_count,
            ):
                assert selected_candidate.character_id is not None
                if selected_candidate.tier == "C":
                    selected_c_ids.append(selected_candidate.character_id)
                else:
                    selected_d_ids.append(selected_candidate.character_id)
                reason = "; ".join(selected_candidate.match_reasons)
                selection_reasons[selected_candidate.character_id] = (
                    f"{reason}; source_need_id={need.source_need_id}"
                )
                reuse_decisions.append(
                    SceneCDRoleReuseDecision(
                        reuse_decision_id=(
                            f"reuse_{selection_id}_{selected_candidate.character_id}_{need.source_need_id}"
                        ),
                        selection_id=selection_id,
                        project_id=chapter.project_id,
                        character_id=selected_candidate.character_id,
                        tier=selected_candidate.tier,
                        source_need_id=need.source_need_id,
                        reuse_reason=selection_reasons[selected_candidate.character_id],
                        matched_memory_ids=[],
                        matched_relationship_ids=[],
                        matched_location_refs=[need.location_hint] if need.location_hint else [],
                        continuity_notes=["M3 records lightweight selection evidence only."],
                        risk_warnings=list(selected_candidate.warnings),
                        created_at=now_utc(),
                    )
                )
                for candidate in search_results:
                    if candidate.candidate_id != selected_candidate.candidate_id:
                        rejected_candidate_reasons[candidate.candidate_id] = (
                            "not the best matching existing C/D role for this need"
                        )
                continue

            for candidate in search_results:
                rejected_candidate_reasons[candidate.candidate_id] = (
                    "low score, duplicate selection, or C/D budget unavailable"
                )
            if self._budget_available_for_need(
                need,
                selected_c_ids=selected_c_ids,
                selected_d_ids=selected_d_ids,
                max_c_count=request.max_c_count,
                max_d_count=request.max_d_count,
            ):
                creation, role_candidate = self.candidate_factory.create_pending_candidate(
                    selection_id=selection_id,
                    need=need,
                    scene_index=request.scene_index,
                )
                creation_candidates.append(creation)
                candidates.append(role_candidate)
            else:
                warnings.append(f"C/D budget unavailable for need {need.source_need_id}")

        now = now_utc()
        status = "ready_for_scene_context"
        requires_user_confirmation = False
        if creation_candidates:
            status = "needs_user_confirmation"
            requires_user_confirmation = True
        if not selected_a_ids:
            status = "blocked"
            requires_user_confirmation = True

        selection = SceneParticipantSelection(
            selection_id=selection_id,
            project_id=chapter.project_id,
            chapter_id=chapter.chapter_id,
            scene_index=request.scene_index,
            scene_id=request.scene_id,
            selected_a_ids=selected_a_ids,
            selected_b_ids=selected_b_ids,
            selected_c_ids=selected_c_ids,
            selected_d_ids=selected_d_ids,
            candidate_ids=[candidate.candidate_id for candidate in candidates],
            source_need_ids=[need.source_need_id for need in role_needs],
            selection_reasons=selection_reasons,
            rejected_candidate_reasons=rejected_candidate_reasons,
            max_c_count=max(0, int(request.max_c_count or 0)),
            max_d_count=max(0, int(request.max_d_count or 0)),
            status=status,
            requires_user_confirmation=requires_user_confirmation,
            does_not_write_story_facts=True,
            safe_summary=(
                "M3 SceneParticipantSelection carries A/B from Chapter and selects "
                "only confirmed C/D roles or pending C/D candidates."
            ),
            warnings=warnings,
            source_query_signature=signature,
            created_at=now,
            updated_at=now,
        )
        self.guard.validate_selection(
            selection=selection,
            chapter=chapter,
            creation_candidates=creation_candidates,
        )
        report = self._build_report(
            selection=selection,
            candidates=candidates,
            creation_candidates=creation_candidates,
            warnings=warnings,
        )
        self._persist_workflow_artifacts(
            selection=selection,
            candidates=candidates,
            creation_candidates=creation_candidates,
            reuse_decisions=reuse_decisions,
            report=report,
        )
        return SceneParticipantSelectionResponse(
            selection=selection,
            role_needs=role_needs,
            candidates=candidates,
            creation_candidates=creation_candidates,
            confirmed_character_ids=self._confirmed_character_ids_for_selection(
                selection,
                creation_candidates,
            ),
            reuse_decisions=reuse_decisions,
            report=report,
            warnings=warnings,
        )

    def get_selection(self, selection_id: str) -> SceneParticipantSelectionResponse:
        clean_id = str(selection_id or "").strip()
        for selection in self._read_selections():
            if selection.selection_id == clean_id:
                return self._response_for_selection(selection)
        raise StorageError("SCENE_PARTICIPANT_SELECTION_NOT_FOUND: selection does not exist.")

    def get_current_selection(
        self,
        *,
        chapter_id: str,
        scene_index: int,
        scene_id: str | None = None,
    ) -> SceneParticipantSelectionResponse:
        selection = self._find_current_selection(
            chapter_id=chapter_id,
            scene_index=scene_index,
            scene_id=scene_id,
        )
        if selection is None:
            return SceneParticipantSelectionResponse()
        return self._response_for_selection(selection)

    def list_role_needs(
        self,
        *,
        chapter_id: str,
        scene_index: int,
        scene_goal: str = "",
        scene_location: str = "",
        previous_scene_result: str = "",
    ) -> list[SceneRoleFunctionNeedRef]:
        chapter = self._find_chapter(chapter_id)
        return self.need_resolver.resolve_for_scene(
            chapter=chapter,
            scene_index=scene_index,
            scene_goal=scene_goal,
            scene_location=scene_location,
            previous_scene_result=previous_scene_result,
        )

    def list_candidates(
        self,
        *,
        chapter_id: str,
        scene_index: int,
    ) -> list[SceneRoleCandidate]:
        return [
            candidate
            for candidate in self._read_candidates()
            if candidate.chapter_id == chapter_id and candidate.scene_index == scene_index
        ]

    def confirm_creation_candidate(
        self,
        candidate_id: str,
    ) -> SceneParticipantSelectionResponse:
        candidate = self._find_creation_candidate(candidate_id)
        if candidate.status == "rejected":
            raise StorageError(
                "SCENE_PARTICIPANT_CREATION_CANDIDATE_REJECTED: rejected candidate cannot be confirmed."
            )
        selection = self._find_selection_by_id(candidate.selection_id)
        if candidate.status == "confirmed":
            return self._response_for_selection(selection)

        timestamp = now_utc()
        character = self._character_from_creation_candidate(candidate, timestamp)
        self._upsert_model(self.characters_file, character, "character_id")

        updated_candidate = candidate.copy(
            update={
                "status": "confirmed",
                "requires_user_confirmation": False,
                "does_not_enter_story_until_confirmed": False,
                "minimal_profile": {
                    **dict(candidate.minimal_profile or {}),
                    "confirmed_character_id": character.character_id,
                },
                "warnings": _unique(
                    [
                        *candidate.warnings,
                        f"confirmed_character_id:{character.character_id}",
                    ]
                ),
                "updated_at": timestamp,
            }
        )
        self._upsert_model(
            self.creation_candidates_file,
            updated_candidate,
            "creation_candidate_id",
        )

        if updated_candidate.target_tier == "C":
            selected_c_ids = _unique([*selection.selected_c_ids, character.character_id])
            selected_d_ids = list(selection.selected_d_ids)
        else:
            selected_c_ids = list(selection.selected_c_ids)
            selected_d_ids = _unique([*selection.selected_d_ids, character.character_id])

        remaining_pending = [
            item
            for item in self._read_creation_candidates()
            if item.selection_id == selection.selection_id
            and item.creation_candidate_id != updated_candidate.creation_candidate_id
            and item.status == "pending"
        ]
        selection_reasons = {
            **dict(selection.selection_reasons or {}),
            character.character_id: (
                f"User confirmed {updated_candidate.target_tier}-tier scene participant "
                f"candidate for source_need_id={updated_candidate.source_need_id or 'unknown'}."
            ),
        }
        updated_selection = selection.copy(
            update={
                "selected_c_ids": selected_c_ids,
                "selected_d_ids": selected_d_ids,
                "selection_reasons": selection_reasons,
                "status": "needs_user_confirmation"
                if remaining_pending
                else "ready_for_scene_context",
                "requires_user_confirmation": bool(remaining_pending),
                "warnings": _unique(
                    [
                        *selection.warnings,
                        f"confirmed_creation_candidate:{updated_candidate.creation_candidate_id}",
                    ]
                ),
                "updated_at": timestamp,
            }
        )
        self._upsert_model(self.selections_file, updated_selection, "selection_id")
        return self._response_for_selection(updated_selection)

    def reject_creation_candidate(
        self,
        candidate_id: str,
    ) -> SceneParticipantSelectionResponse:
        candidate = self._find_creation_candidate(candidate_id)
        selection = self._find_selection_by_id(candidate.selection_id)
        if candidate.status == "confirmed":
            raise StorageError(
                "SCENE_PARTICIPANT_CREATION_CANDIDATE_ALREADY_CONFIRMED: confirmed candidate cannot be rejected."
            )
        timestamp = now_utc()
        updated_candidate = candidate.copy(
            update={
                "status": "rejected",
                "requires_user_confirmation": False,
                "does_not_enter_story_until_confirmed": True,
                "updated_at": timestamp,
            }
        )
        self._upsert_model(
            self.creation_candidates_file,
            updated_candidate,
            "creation_candidate_id",
        )
        updated_selection = selection.copy(
            update={
                "status": "cancelled",
                "requires_user_confirmation": False,
                "warnings": _unique(
                    [
                        *selection.warnings,
                        f"rejected_creation_candidate:{updated_candidate.creation_candidate_id}",
                        "selection_cancelled_for_refresh_after_candidate_rejection",
                    ]
                ),
                "updated_at": timestamp,
            }
        )
        self._upsert_model(self.selections_file, updated_selection, "selection_id")
        return self.create_selection(
            SceneParticipantSelectionRequest(
                chapter_id=selection.chapter_id,
                scene_index=selection.scene_index,
                scene_id=selection.scene_id,
                force_refresh=True,
            )
        )

    def refresh_selection(self, selection_id: str) -> SceneParticipantSelectionResponse:
        selection = self._find_selection_by_id(selection_id)
        return self.create_selection(
            SceneParticipantSelectionRequest(
                chapter_id=selection.chapter_id,
                scene_index=selection.scene_index,
                scene_id=selection.scene_id,
                force_refresh=True,
            )
        )

    def get_report(self, report_id: str) -> SceneParticipantSelectionReport:
        clean_id = str(report_id or "").strip()
        for report in self._read_reports():
            if report.report_id == clean_id:
                return report
        raise StorageError("SCENE_PARTICIPANT_SELECTION_REPORT_NOT_FOUND: report does not exist.")

    def _choose_reuse_candidate(
        self,
        *,
        need: SceneRoleFunctionNeedRef,
        candidates: list[SceneRoleCandidate],
        already_selected: set[str],
        scene_index: int,
    ) -> SceneRoleCandidate | None:
        available = [
            candidate
            for candidate in candidates
            if candidate.candidate_source == "existing_confirmed_role"
            and candidate.character_id
            and candidate.character_id not in already_selected
        ]
        high = [candidate for candidate in available if candidate.match_score == "high"]
        if high:
            return self._rotated_candidate(
                high,
                chapter_id=need.chapter_id,
                scene_index=scene_index,
            )
        if need.reuse_existing_preferred:
            medium = [candidate for candidate in available if candidate.match_score == "medium"]
            if medium:
                return self._rotated_candidate(
                    medium,
                    chapter_id=need.chapter_id,
                    scene_index=scene_index,
                )
        return None

    def _rotated_candidate(
        self,
        candidates: list[SceneRoleCandidate],
        *,
        chapter_id: str,
        scene_index: int,
    ) -> SceneRoleCandidate:
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                str(candidate.tier or ""),
                str(candidate.character_id or ""),
                str(candidate.candidate_id or ""),
            ),
        )
        if not ordered:
            raise StorageError("SCENE_PARTICIPANT_SELECTION_NO_REUSE_CANDIDATES")
        offset = (
            _chapter_number(chapter_id)
            + max(1, int(scene_index or 1))
            - 2
        ) % len(ordered)
        return ordered[offset]

    def _within_budget(
        self,
        candidate: SceneRoleCandidate,
        *,
        selected_c_ids: list[str],
        selected_d_ids: list[str],
        max_c_count: int,
        max_d_count: int,
    ) -> bool:
        if candidate.tier == "C":
            return len(selected_c_ids) < max(0, int(max_c_count or 0))
        return len(selected_d_ids) < max(0, int(max_d_count or 0))

    def _budget_available_for_need(
        self,
        need: SceneRoleFunctionNeedRef,
        *,
        selected_c_ids: list[str],
        selected_d_ids: list[str],
        max_c_count: int,
        max_d_count: int,
    ) -> bool:
        max_c = max(0, int(max_c_count or 0))
        max_d = max(0, int(max_d_count or 0))
        if need.tier_preference == "C":
            return len(selected_c_ids) < max_c
        if need.tier_preference == "D":
            return len(selected_d_ids) < max_d
        return len(selected_c_ids) < max_c or len(selected_d_ids) < max_d

    def _carry_in_ab_ids(self, chapter: Chapter) -> tuple[list[str], list[str]]:
        a_ids = _unique(chapter.main_cast_character_ids)
        b_ids = _unique(chapter.supporting_role_ids)
        if a_ids and b_ids:
            return a_ids, b_ids
        report = self.runtime_role_eligibility.build_report(project_id=chapter.project_id)
        participating = set(chapter.participating_character_ids or chapter.participant_character_ids or [])
        fallback_a = [item for item in report.confirmed_a_ids if item in participating]
        fallback_b = [item for item in report.confirmed_b_ids if item in participating]
        if not a_ids:
            a_ids = _unique(fallback_a)
        if not b_ids:
            b_ids = _unique(fallback_b)
        return a_ids, b_ids

    def _find_chapter(self, chapter_id: str) -> Chapter:
        clean_id = str(chapter_id or "").strip()
        if not clean_id:
            raise StorageError("SCENE_PARTICIPANT_SELECTION_CHAPTER_ID_REQUIRED: chapter_id is required.")
        for chapter in self._read_chapters():
            if chapter.chapter_id == clean_id:
                return chapter
        raise StorageError("SCENE_PARTICIPANT_SELECTION_CHAPTER_NOT_FOUND: chapter does not exist.")

    def _read_chapters(self) -> list[Chapter]:
        if not self.store.exists(self.chapters_file):
            return []
        raw = self.store.read_any(self.chapters_file)
        if not isinstance(raw, list):
            raise StorageError("SCENE_PARTICIPANT_CHAPTERS_INVALID: chapters.json must be a list.")
        return [Chapter(**item) for item in raw if isinstance(item, dict)]

    def _build_report(
        self,
        *,
        selection: SceneParticipantSelection,
        candidates: list[SceneRoleCandidate],
        creation_candidates: list[SceneCDRoleCreationCandidate],
        warnings: list[str],
    ) -> SceneParticipantSelectionReport:
        selected_count = len(selection.selected_c_ids) + len(selection.selected_d_ids)
        selected_ids = set([*selection.selected_c_ids, *selection.selected_d_ids])
        all_selected_have_reasons = all(
            str(selection.selection_reasons.get(character_id) or "").strip()
            for character_id in selected_ids
        )
        total_cd = len(self._confirmed_cd_ids())
        return SceneParticipantSelectionReport(
            report_id=f"selection_report_{selection.selection_id}",
            project_id=selection.project_id,
            selection_id=selection.selection_id,
            chapter_id=selection.chapter_id,
            scene_index=selection.scene_index,
            selected_existing_count=selected_count,
            new_candidate_count=len(creation_candidates),
            rejected_candidate_count=len(selection.rejected_candidate_reasons),
            unselected_c_d_count=max(0, total_cd - selected_count),
            all_selected_have_reasons=all_selected_have_reasons,
            unselected_not_in_context=True,
            no_story_fact_written=True,
            safe_summary=(
                f"Selected {selected_count} existing C/D roles and proposed "
                f"{len(creation_candidates)} pending C/D candidates."
            ),
            warnings=warnings,
            created_at=now_utc(),
        )

    def _confirmed_cd_ids(self) -> list[str]:
        if not self.store.exists(self.characters_file):
            return []
        raw = self.store.read_any(self.characters_file)
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                character = Character(**item)
            except Exception:
                continue
            if str(character.status or "").strip() == "confirmed" and not character.archived_at:
                if str(character.tier or "").upper() in {"C", "D"}:
                    result.append(character.character_id)
        return _unique(result)

    def _persist_workflow_artifacts(
        self,
        *,
        selection: SceneParticipantSelection,
        candidates: list[SceneRoleCandidate],
        creation_candidates: list[SceneCDRoleCreationCandidate],
        reuse_decisions: list[SceneCDRoleReuseDecision],
        report: SceneParticipantSelectionReport,
    ) -> None:
        self._upsert_model(self.selections_file, selection, "selection_id")
        for candidate in candidates:
            self._upsert_model(self.role_candidates_file, candidate, "candidate_id")
        for candidate in creation_candidates:
            self._upsert_model(
                self.creation_candidates_file,
                candidate,
                "creation_candidate_id",
            )
        for decision in reuse_decisions:
            self._upsert_model(self.reuse_decisions_file, decision, "reuse_decision_id")
        self._upsert_model(self.reports_file, report, "report_id")

    def _response_for_selection(
        self,
        selection: SceneParticipantSelection,
    ) -> SceneParticipantSelectionResponse:
        candidates = [
            candidate
            for candidate in self._read_candidates()
            if candidate.candidate_id in set(selection.candidate_ids)
        ]
        creation_candidates = [
            candidate
            for candidate in self._read_creation_candidates()
            if candidate.selection_id == selection.selection_id
        ]
        reuse_decisions = [
            decision
            for decision in self._read_reuse_decisions()
            if decision.selection_id == selection.selection_id
        ]
        report = next(
            (
                item
                for item in self._read_reports()
                if item.selection_id == selection.selection_id
            ),
            None,
        )
        return SceneParticipantSelectionResponse(
            selection=selection,
            role_needs=[],
            candidates=candidates,
            creation_candidates=creation_candidates,
            confirmed_character_ids=self._confirmed_character_ids_for_selection(
                selection,
                creation_candidates,
            ),
            reuse_decisions=reuse_decisions,
            report=report,
            warnings=list(selection.warnings),
        )

    def _confirmed_character_ids_for_selection(
        self,
        selection: SceneParticipantSelection,
        creation_candidates: list[SceneCDRoleCreationCandidate],
    ) -> list[str]:
        character_ids: list[str] = []
        selected_ids = set([*selection.selected_c_ids, *selection.selected_d_ids])
        for candidate in creation_candidates:
            if candidate.selection_id != selection.selection_id or candidate.status != "confirmed":
                continue
            confirmed_id = str(
                (candidate.minimal_profile or {}).get("confirmed_character_id") or ""
            ).strip()
            if not confirmed_id:
                for warning in candidate.warnings:
                    if str(warning).startswith("confirmed_character_id:"):
                        confirmed_id = str(warning).split(":", 1)[1].strip()
                        break
            if not confirmed_id:
                fallback_id = self._candidate_character_id(candidate)
                if fallback_id in selected_ids:
                    confirmed_id = fallback_id
            if confirmed_id:
                character_ids.append(confirmed_id)
        return _unique(character_ids)

    def _find_current_selection(
        self,
        *,
        chapter_id: str,
        scene_index: int,
        scene_id: str | None = None,
        source_query_signature: str = "",
    ) -> SceneParticipantSelection | None:
        clean_scene_id = str(scene_id or "").strip()
        matches = [
            selection
            for selection in self._read_selections()
            if selection.chapter_id == chapter_id
            and selection.scene_index == int(scene_index)
            and (not clean_scene_id or str(selection.scene_id or "").strip() == clean_scene_id)
            and selection.status != "cancelled"
            and (
                not source_query_signature
                or selection.source_query_signature == source_query_signature
            )
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def _find_selection_by_id(self, selection_id: str) -> SceneParticipantSelection:
        clean_id = str(selection_id or "").strip()
        for selection in self._read_selections():
            if selection.selection_id == clean_id:
                return selection
        raise StorageError("SCENE_PARTICIPANT_SELECTION_NOT_FOUND: selection does not exist.")

    def _find_creation_candidate(self, candidate_id: str) -> SceneCDRoleCreationCandidate:
        clean_id = str(candidate_id or "").strip()
        for candidate in self._read_creation_candidates():
            if candidate.creation_candidate_id == clean_id:
                return candidate
        raise StorageError(
            "SCENE_PARTICIPANT_CREATION_CANDIDATE_NOT_FOUND: creation candidate does not exist."
        )

    def _character_from_creation_candidate(
        self,
        candidate: SceneCDRoleCreationCandidate,
        timestamp: str,
    ) -> Character:
        character_id = self._candidate_character_id(candidate)
        profile_payload = dict(candidate.minimal_profile or {})
        profile = CharacterProfile(
            description=str(
                profile_payload.get("description")
                or profile_payload.get("summary")
                or candidate.safe_summary
                or candidate.required_scene_function
            ),
            identity=str(
                profile_payload.get("identity")
                or candidate.role_label
                or f"{candidate.target_tier}-tier scene participant"
            ),
            story_function=str(
                profile_payload.get("story_function")
                or candidate.story_function
                or candidate.required_scene_function
            ),
            background_summary=str(
                profile_payload.get("background_summary")
                or candidate.required_scene_function
                or candidate.safe_summary
            ),
            traits=self._coerce_string_list(profile_payload.get("traits")),
            goals=self._coerce_string_list(profile_payload.get("goals")),
            knowledge_scope=self._coerce_string_list(
                profile_payload.get("knowledge_scope")
                or [candidate.required_scene_function]
            ),
        )
        return Character(
            character_id=character_id,
            project_id=candidate.project_id,
            name=str(candidate.role_label or character_id),
            tier=candidate.target_tier,
            role=str(candidate.story_function or "scene_participant"),
            profile=profile,
            status="confirmed",
            source="scene_participant_creation_candidate",
            version_id=f"{character_id}_v1",
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _candidate_character_id(self, candidate: SceneCDRoleCreationCandidate) -> str:
        seed = (
            f"{candidate.project_id}_{candidate.chapter_id}_{candidate.scene_index}_"
            f"{candidate.source_need_id or candidate.creation_candidate_id}_{candidate.target_tier}"
        )
        clean = re.sub(r"[^A-Za-z0-9_]+", "_", seed).strip("_").lower()
        return f"char_{clean[:90]}"

    def _coerce_string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return _unique([str(item) for item in value if str(item or "").strip()])
        clean = str(value or "").strip()
        return [clean] if clean else []

    def _read_selections(self) -> list[SceneParticipantSelection]:
        return self._read_model_list(self.selections_file, SceneParticipantSelection)

    def _read_candidates(self) -> list[SceneRoleCandidate]:
        return self._read_model_list(self.role_candidates_file, SceneRoleCandidate)

    def _read_creation_candidates(self) -> list[SceneCDRoleCreationCandidate]:
        return self._read_model_list(
            self.creation_candidates_file,
            SceneCDRoleCreationCandidate,
        )

    def _read_reuse_decisions(self) -> list[SceneCDRoleReuseDecision]:
        return self._read_model_list(self.reuse_decisions_file, SceneCDRoleReuseDecision)

    def _read_reports(self) -> list[SceneParticipantSelectionReport]:
        return self._read_model_list(self.reports_file, SceneParticipantSelectionReport)

    def _read_model_list(self, path: Path, model_type: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        raw = self.store.read_any(path)
        if not isinstance(raw, list):
            raise StorageError(f"SCENE_PARTICIPANT_WORKFLOW_FILE_INVALID: {path.name} must be a list.")
        return [model_type(**item) for item in raw if isinstance(item, dict)]

    def _upsert_model(self, path: Path, model: BaseModel, id_field: str) -> None:
        items = self._read_raw_list(path)
        payload = model_to_dict(model)
        clean_id = str(payload.get(id_field) or "")
        replaced = False
        for index, item in enumerate(items):
            if isinstance(item, dict) and str(item.get(id_field) or "") == clean_id:
                items[index] = payload
                replaced = True
                break
        if not replaced:
            items.append(payload)
        self.store.write(path, items)

    def _read_raw_list(self, path: Path) -> list[Any]:
        if not self.store.exists(path):
            return []
        raw = self.store.read_any(path)
        if not isinstance(raw, list):
            raise StorageError(f"SCENE_PARTICIPANT_WORKFLOW_FILE_INVALID: {path.name} must be a list.")
        return raw

    def _signature(
        self,
        request: SceneParticipantSelectionRequest,
        chapter: Chapter,
        role_needs: list[SceneRoleFunctionNeedRef],
    ) -> str:
        payload = {
            "chapter_id": chapter.chapter_id,
            "chapter_version_id": chapter.version_id,
            "scene_index": request.scene_index,
            "scene_id": request.scene_id,
            "scene_goal": request.scene_goal,
            "scene_location": request.scene_location,
            "previous_scene_result": request.previous_scene_result,
            "max_c_count": request.max_c_count,
            "max_d_count": request.max_d_count,
            "selected_a_ids": chapter.main_cast_character_ids,
            "selected_b_ids": chapter.supporting_role_ids,
            "participant_character_ids": chapter.participant_character_ids,
            "participating_character_ids": chapter.participating_character_ids,
            "source_need_ids": [need.source_need_id for need in role_needs],
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _chapter_number(chapter_id: str) -> int:
    match = re.search(r"(\d+)$", str(chapter_id or ""))
    return int(match.group(1)) if match else 1
