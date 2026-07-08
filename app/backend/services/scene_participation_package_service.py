from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.character import (
    Character,
    CharacterContextBuildRequest,
)
from app.backend.models.scene_participants import (
    SceneCDRoleCreationCandidate,
    SceneParticipantSelection,
    SceneParticipantSelectionRequest,
)
from app.backend.models.scene_participation import (
    SceneParticipationPackage,
    SceneParticipationParticipant,
    SceneParticipationPrepareRequest,
    SceneParticipationPrepareResponse,
    SceneParticipationReadinessReport,
    TieredCharacterContextPackage,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.abcd_runtime_participation_policy_service import now_utc
from app.backend.services.character_context_builder import CharacterContextBuilder
from app.backend.services.role_tier_budget_service import RoleTierBudgetService
from app.backend.services.runtime_role_eligibility_service import RuntimeRoleEligibilityService
from app.backend.services.scene_memory_service import SceneMemoryService
from app.backend.services.scene_participant_selection_service import (
    SceneParticipantSelectionService,
)
from app.backend.storage.json_store import JsonStore, StorageError


SCENE_PARTICIPATION_PACKAGES_FILE_NAME = "scene_participation_packages.json"
TIERED_CHARACTER_CONTEXT_PACKAGES_FILE_NAME = "tiered_character_context_packages.json"
SCENE_PARTICIPATION_READINESS_FILE_NAME = "scene_participation_readiness_reports.json"


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class SceneParticipationPackageService:
    """Builds M4 runtime scene participation context without writing story facts."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        selection_service: SceneParticipantSelectionService | None = None,
        scene_memory_service: SceneMemoryService | None = None,
        character_context_builder: CharacterContextBuilder | None = None,
        role_tier_budget_service: RoleTierBudgetService | None = None,
        runtime_role_eligibility: RuntimeRoleEligibilityService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.selection_service = selection_service or SceneParticipantSelectionService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.scene_memory_service = scene_memory_service or SceneMemoryService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.character_context_builder = character_context_builder or CharacterContextBuilder(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.role_tier_budget_service = role_tier_budget_service or RoleTierBudgetService()
        self.runtime_role_eligibility = runtime_role_eligibility or RuntimeRoleEligibilityService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.packages_file = self.data_dir / SCENE_PARTICIPATION_PACKAGES_FILE_NAME
        self.tiered_context_packages_file = (
            self.data_dir / TIERED_CHARACTER_CONTEXT_PACKAGES_FILE_NAME
        )
        self.readiness_file = self.data_dir / SCENE_PARTICIPATION_READINESS_FILE_NAME
        self.chapters_file = self.data_dir / "chapters.json"
        self.characters_file = self.data_dir / "characters.json"

    def prepare_package(
        self,
        request: SceneParticipationPrepareRequest,
    ) -> SceneParticipationPrepareResponse:
        chapter = self._find_chapter(request.chapter_id)
        selection_response = self.selection_service.get_current_selection(
            chapter_id=chapter.chapter_id,
            scene_id=request.scene_id,
            scene_index=request.scene_index,
        )
        selection = selection_response.selection
        characters_by_id = self._confirmed_active_characters_by_id()
        if self._selection_should_refresh(
            selection_response=selection_response,
            characters_by_id=characters_by_id,
        ):
            selection_response = self.selection_service.refresh_selection(
                selection.selection_id if selection else ""
            )
            selection = selection_response.selection
        if selection is None:
            selection_response = self.selection_service.create_selection(
                SceneParticipantSelectionRequest(
                    chapter_id=chapter.chapter_id,
                    scene_index=request.scene_index,
                    scene_id=request.scene_id,
                    scene_goal=request.scene_goal,
                    scene_location=request.scene_location,
                    previous_scene_result="",
                    force_refresh=request.force_refresh,
                )
            )
            selection = selection_response.selection
        warnings: list[str] = []
        blocking_issues: list[str] = []
        pending_candidates: list[SceneCDRoleCreationCandidate] = []
        unresolved_required_need_ids: list[str] = []
        unresolved_optional_need_ids: list[str] = []
        if selection is not None and selection.status not in {
            "ready_for_scene_context",
            "needs_user_confirmation",
            "blocked",
        }:
            warnings.append(f"ignored_unready_scene_participant_selection:{selection.selection_id}")
            selection = None

        if selection is not None:
            selection_mode = "m3_selection"
            selected_a_ids = self._unique(selection.selected_a_ids)
            selected_b_ids = self._unique(selection.selected_b_ids)
            selected_c_ids = self._unique(selection.selected_c_ids)
            selected_d_ids = self._unique(selection.selected_d_ids)
            active_character_ids = self._unique(
                [*selected_a_ids, *selected_b_ids, *selected_c_ids, *selected_d_ids]
            )
            pending_candidates = [
                candidate
                for candidate in selection_response.creation_candidates
                if candidate.status == "pending"
            ]
            for candidate in pending_candidates:
                source_need_id = str(candidate.source_need_id or "").strip()
                if self._is_optional_need(chapter, source_need_id):
                    if source_need_id:
                        unresolved_optional_need_ids.append(source_need_id)
                    warnings.append(
                        f"optional_pending_cd_candidate:{candidate.creation_candidate_id}"
                    )
                else:
                    if source_need_id:
                        unresolved_required_need_ids.append(source_need_id)
                    blocking_issues.append(
                        f"required_pending_cd_candidate:{candidate.creation_candidate_id}"
                    )
            if selection.status == "blocked":
                blocking_issues.append("scene_participant_selection_blocked")
            if not active_character_ids:
                blocking_issues.append("scene_participant_selection_has_no_active_characters")
        else:
            selection_mode = "chapter_ab_or_legacy_a"
            selected_a_ids, selected_b_ids = self._fallback_ab_ids(chapter)
            selected_c_ids = []
            selected_d_ids = []
            active_character_ids = self._unique([*selected_a_ids, *selected_b_ids])
            if not active_character_ids:
                blocking_issues.append("chapter_ab_or_legacy_a_fallback_missing")

        invalid_ids = [
            character_id
            for character_id in active_character_ids
            if character_id not in characters_by_id
        ]
        if invalid_ids:
            blocking_issues.append(
                "active_character_ids_not_confirmed_or_archived:" + ",".join(invalid_ids)
            )
        active_character_ids = [
            character_id
            for character_id in active_character_ids
            if character_id in characters_by_id
        ]
        selected_a_ids = [item for item in selected_a_ids if item in active_character_ids]
        selected_b_ids = [item for item in selected_b_ids if item in active_character_ids]
        selected_c_ids = [item for item in selected_c_ids if item in active_character_ids]
        selected_d_ids = [item for item in selected_d_ids if item in active_character_ids]

        participants = self._build_participants(
            active_character_ids=active_character_ids,
            selected_a_ids=selected_a_ids,
            selected_b_ids=selected_b_ids,
            selected_c_ids=selected_c_ids,
            selected_d_ids=selected_d_ids,
            characters_by_id=characters_by_id,
            selection=selection,
            selection_mode=selection_mode,
        )
        status = self._status_for(blocking_issues, warnings)
        timestamp = now_utc()
        signature = self._signature(
            request=request,
            selection=selection,
            active_character_ids=active_character_ids,
            pending_candidates=pending_candidates,
            blocking_issues=blocking_issues,
            warnings=warnings,
        )
        package_id = f"scene_participation_{chapter.chapter_id}_{request.scene_index}_{signature[:12]}"
        package = SceneParticipationPackage(
            scene_participation_package_id=package_id,
            project_id=chapter.project_id,
            chapter_id=chapter.chapter_id,
            scene_index=request.scene_index,
            scene_id=request.scene_id,
            source_selection_id=selection.selection_id if selection else None,
            source_selection_status=selection.status if selection else "",
            selection_mode=selection_mode,
            status=status,
            active_character_ids=active_character_ids,
            selected_a_ids=selected_a_ids,
            selected_b_ids=selected_b_ids,
            selected_c_ids=selected_c_ids,
            selected_d_ids=selected_d_ids,
            participants=participants,
            pending_creation_candidate_ids=[
                candidate.creation_candidate_id for candidate in pending_candidates
            ],
            excluded_candidate_ids=[
                candidate.creation_candidate_id for candidate in pending_candidates
            ],
            unresolved_required_need_ids=self._unique(unresolved_required_need_ids),
            unresolved_optional_need_ids=self._unique(unresolved_optional_need_ids),
            blocking_issues=self._unique(blocking_issues),
            warnings=self._unique(warnings),
            source_query_signature={
                "signature": signature,
                "source": "phase85b_m4_scene_participation_package",
                "scene_goal": request.scene_goal,
                "scene_location": request.scene_location,
                "required_memory_refs": request.required_memory_refs,
                "include_provisional": request.include_provisional,
                "force_refresh": request.force_refresh,
            },
            created_at=timestamp,
            updated_at=timestamp,
        )
        readiness = SceneParticipationReadinessReport(
            readiness_report_id=f"readiness_{package_id}",
            project_id=package.project_id,
            chapter_id=package.chapter_id,
            scene_index=package.scene_index,
            scene_id=package.scene_id,
            scene_participation_package_id=package.scene_participation_package_id,
            source_selection_id=package.source_selection_id,
            selection_mode=package.selection_mode,
            ready=package.status in {"ready", "warning"},
            status=package.status,
            needs_user_confirmation=bool(unresolved_required_need_ids),
            active_character_ids=package.active_character_ids,
            unresolved_required_need_ids=package.unresolved_required_need_ids,
            unresolved_optional_need_ids=package.unresolved_optional_need_ids,
            pending_creation_candidate_ids=package.pending_creation_candidate_ids,
            blocking_issues=package.blocking_issues,
            warnings=package.warnings,
            created_at=timestamp,
        )

        scene_memory_pack = None
        tiered_package = None
        if readiness.ready and package.active_character_ids:
            scene_memory_pack = self.scene_memory_service.build_scene_pack(
                chapter_id=package.chapter_id,
                scene_index=package.scene_index,
                scene_id=request.scene_id,
                scene_goal=request.scene_goal or chapter.chapter_goal or chapter.summary,
                scene_location=request.scene_location,
                active_character_ids=package.active_character_ids,
                required_memory_refs=request.required_memory_refs,
                include_provisional=request.include_provisional,
                force_refresh=request.force_refresh,
                strict_active_character_ids=True,
            )
            package.scene_memory_pack_id = scene_memory_pack.scene_memory_pack_id
            tiered_package = self._build_tiered_context_package(
                package=package,
                scene_memory_pack_id=scene_memory_pack.scene_memory_pack_id,
                include_provisional=request.include_provisional,
                timestamp=timestamp,
            )
            package.tiered_character_context_package_id = (
                tiered_package.tiered_character_context_package_id
            )

        self._upsert_model(
            self.packages_file,
            package,
            "scene_participation_package_id",
        )
        self._upsert_model(self.readiness_file, readiness, "readiness_report_id")
        if tiered_package is not None:
            self._upsert_model(
                self.tiered_context_packages_file,
                tiered_package,
                "tiered_character_context_package_id",
            )

        return SceneParticipationPrepareResponse(
            package=package,
            tiered_character_context_package=tiered_package,
            scene_memory_pack=scene_memory_pack,
            readiness=readiness,
            warnings=package.warnings,
        )

    def get_current_package(
        self,
        *,
        chapter_id: str,
        scene_index: int,
        scene_id: str | None = None,
    ) -> SceneParticipationPrepareResponse:
        package = self._find_current_package(
            chapter_id=chapter_id,
            scene_index=scene_index,
            scene_id=scene_id,
        )
        if package is None:
            return SceneParticipationPrepareResponse()
        return self._response_for_package(package)

    def get_package(self, package_id: str) -> SceneParticipationPrepareResponse:
        clean_id = str(package_id or "").strip()
        for package in self._read_models(self.packages_file, SceneParticipationPackage):
            if package.scene_participation_package_id == clean_id:
                return self._response_for_package(package)
        raise StorageError("SCENE_PARTICIPATION_PACKAGE_NOT_FOUND: package does not exist.")

    def get_readiness(self, package_id: str) -> SceneParticipationReadinessReport:
        clean_id = str(package_id or "").strip()
        for report in self._read_models(
            self.readiness_file,
            SceneParticipationReadinessReport,
        ):
            if report.scene_participation_package_id == clean_id:
                return report
        raise StorageError("SCENE_PARTICIPATION_READINESS_NOT_FOUND: readiness report does not exist.")

    def _response_for_package(
        self,
        package: SceneParticipationPackage,
    ) -> SceneParticipationPrepareResponse:
        readiness = next(
            (
                item
                for item in self._read_models(
                    self.readiness_file,
                    SceneParticipationReadinessReport,
                )
                if item.scene_participation_package_id
                == package.scene_participation_package_id
            ),
            None,
        )
        tiered_package = next(
            (
                item
                for item in self._read_models(
                    self.tiered_context_packages_file,
                    TieredCharacterContextPackage,
                )
                if item.scene_participation_package_id
                == package.scene_participation_package_id
            ),
            None,
        )
        scene_memory_pack = None
        if package.scene_memory_pack_id:
            for pack in self.repositories.scene_memory_packs.list_packs():
                if not isinstance(pack, dict):
                    continue
                if pack.get("scene_memory_pack_id") == package.scene_memory_pack_id:
                    from app.backend.models.memory_pack import SceneMemoryPack

                    scene_memory_pack = SceneMemoryPack(**pack)
                    break
        return SceneParticipationPrepareResponse(
            package=package,
            tiered_character_context_package=tiered_package,
            scene_memory_pack=scene_memory_pack,
            readiness=readiness,
            warnings=package.warnings,
        )

    def _build_tiered_context_package(
        self,
        *,
        package: SceneParticipationPackage,
        scene_memory_pack_id: str,
        include_provisional: bool,
        timestamp: str,
    ) -> TieredCharacterContextPackage:
        response = self.character_context_builder.build_context(
            CharacterContextBuildRequest(
                character_ids=package.active_character_ids,
                chapter_id=package.chapter_id,
                scene_id=package.scene_id or "",
                scene_index=package.scene_index,
                scene_memory_pack_id=scene_memory_pack_id,
                include_provisional=include_provisional,
            )
        )
        active = set(package.active_character_ids)
        items = [
            item
            for item in response.items
            if item.character_id in active
        ]
        warnings = list(response.warnings)
        if len(items) != len(package.active_character_ids):
            warnings.append("tiered_context_missing_some_active_characters")
        return TieredCharacterContextPackage(
            tiered_character_context_package_id=(
                f"tiered_context_{package.scene_participation_package_id}"
            ),
            project_id=package.project_id,
            chapter_id=package.chapter_id,
            scene_index=package.scene_index,
            scene_id=package.scene_id,
            scene_participation_package_id=package.scene_participation_package_id,
            scene_memory_pack_id=scene_memory_pack_id,
            active_character_ids=package.active_character_ids,
            items=items,
            warnings=self._unique(warnings),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _build_participants(
        self,
        *,
        active_character_ids: list[str],
        selected_a_ids: list[str],
        selected_b_ids: list[str],
        selected_c_ids: list[str],
        selected_d_ids: list[str],
        characters_by_id: dict[str, Character],
        selection: SceneParticipantSelection | None,
        selection_mode: str,
    ) -> list[SceneParticipationParticipant]:
        reason_by_id = dict(selection.selection_reasons) if selection else {}
        tiers_by_id = {
            **{character_id: "A" for character_id in selected_a_ids},
            **{character_id: "B" for character_id in selected_b_ids},
            **{character_id: "C" for character_id in selected_c_ids},
            **{character_id: "D" for character_id in selected_d_ids},
        }
        participants: list[SceneParticipationParticipant] = []
        for character_id in active_character_ids:
            character = characters_by_id.get(character_id)
            if character is None:
                continue
            tier = tiers_by_id.get(character_id, character.tier)
            budget = self.role_tier_budget_service.budget_for_character(character)
            participants.append(
                SceneParticipationParticipant(
                    character_id=character.character_id,
                    name=character.name,
                    tier=tier,
                    role_label=character.role,
                    participation_source=(
                        "m3_selection"
                        if selection_mode == "m3_selection"
                        else (
                            "chapter_ab_fallback"
                            if character_id in [*selected_a_ids, *selected_b_ids]
                            else "legacy_a_fallback"
                        )
                    ),
                    selection_reason=reason_by_id.get(character_id, ""),
                    context_depth=self._context_depth(tier),
                    budget_applied=model_to_dict(budget),
                )
            )
        return participants

    def _fallback_ab_ids(self, chapter: Chapter) -> tuple[list[str], list[str]]:
        a_ids = self._unique(chapter.main_cast_character_ids)
        b_ids = self._unique(chapter.supporting_role_ids)
        if a_ids or b_ids:
            return a_ids, b_ids
        report = self.runtime_role_eligibility.build_report(project_id=chapter.project_id)
        participating = set(
            chapter.participating_character_ids
            or chapter.participant_character_ids
            or []
        )
        if participating:
            legacy_a = [item for item in report.confirmed_a_ids if item in participating]
            return self._unique(legacy_a), []
        return self._unique(report.confirmed_a_ids), []

    def _confirmed_active_characters_by_id(self) -> dict[str, Character]:
        result: dict[str, Character] = {}
        for raw in self.repositories.characters.list_all():
            if not isinstance(raw, dict):
                continue
            if str(raw.get("status") or "").strip() != "confirmed":
                continue
            if str(raw.get("archived_at") or "").strip():
                continue
            try:
                character = Character(**raw)
            except ValidationError:
                continue
            result[character.character_id] = character
        return result

    def _find_chapter(self, chapter_id: str) -> Chapter:
        clean_id = str(chapter_id or "").strip()
        if not clean_id:
            raise StorageError("SCENE_PARTICIPATION_CHAPTER_ID_REQUIRED: chapter_id is required.")
        for raw in self.repositories.chapters.list_all():
            if not isinstance(raw, dict):
                continue
            if str(raw.get("chapter_id") or "").strip() != clean_id:
                continue
            return Chapter(**raw)
        raise StorageError("SCENE_PARTICIPATION_CHAPTER_NOT_FOUND: chapter does not exist.")

    def _find_current_package(
        self,
        *,
        chapter_id: str,
        scene_index: int,
        scene_id: str | None = None,
    ) -> SceneParticipationPackage | None:
        clean_scene_id = str(scene_id or "").strip()
        matches = [
            package
            for package in self._read_models(self.packages_file, SceneParticipationPackage)
            if package.chapter_id == chapter_id
            and package.scene_index == int(scene_index)
            and (not clean_scene_id or str(package.scene_id or "").strip() == clean_scene_id)
            and package.status in {"ready", "warning", "blocked"}
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def _is_optional_need(self, chapter: Chapter, source_need_id: str) -> bool:
        if not source_need_id:
            return False
        for raw_need in chapter.cd_role_function_needs:
            if not isinstance(raw_need, dict):
                continue
            need_id = str(raw_need.get("need_id") or raw_need.get("source_need_id") or "").strip()
            if need_id != source_need_id:
                continue
            if raw_need.get("required") is False:
                return True
            if raw_need.get("optional") is True or raw_need.get("is_optional") is True:
                return True
            level = str(
                raw_need.get("priority")
                or raw_need.get("importance")
                or raw_need.get("need_level")
                or ""
            ).strip().casefold()
            return level in {"optional", "nice_to_have", "low"}
        return False

    def _selection_should_refresh(
        self,
        *,
        selection_response: Any,
        characters_by_id: dict[str, Character],
    ) -> bool:
        selection = getattr(selection_response, "selection", None)
        if selection is None:
            return False
        if selection.status not in {"needs_user_confirmation", "blocked"}:
            return False
        creation_candidates = list(getattr(selection_response, "creation_candidates", []) or [])
        pending_candidates = [
            candidate for candidate in creation_candidates if candidate.status == "pending"
        ]
        if not pending_candidates:
            return True
        return any(
            self._matching_confirmed_role_exists(candidate, characters_by_id)
            for candidate in pending_candidates
        )

    def _matching_confirmed_role_exists(
        self,
        candidate: SceneCDRoleCreationCandidate,
        characters_by_id: dict[str, Character],
    ) -> bool:
        target_tier = str(candidate.target_tier or "").upper()
        candidate_tokens = set(
            self._meaningful_tokens(
                " ".join(
                    [
                        candidate.role_label,
                        candidate.story_function,
                        candidate.required_scene_function,
                        candidate.source_need_id or "",
                        str(candidate.minimal_profile.get("description") or ""),
                        str(candidate.minimal_profile.get("story_function") or ""),
                    ]
                )
            )
        )
        if not candidate_tokens:
            return False
        for character in characters_by_id.values():
            if str(character.tier or "").upper() != target_tier:
                continue
            profile_text = " ".join(
                [
                    character.name,
                    character.role,
                    character.profile.description,
                    character.profile.identity,
                    character.profile.story_function,
                    character.profile.background_summary,
                    " ".join(character.profile.traits),
                    " ".join(character.profile.goals),
                    " ".join(character.profile.knowledge_scope),
                    character.current_state.location_id,
                    character.current_state.active_goal,
                    character.memory_summary.summary,
                ]
            )
            if candidate_tokens & set(self._meaningful_tokens(profile_text)):
                return True
        return False

    def _meaningful_tokens(self, text: str) -> list[str]:
        tokens: list[str] = []
        for token in str(text or "").casefold().replace("_", " ").replace("/", " ").split():
            clean = "".join(ch for ch in token if ch.isalnum())
            if len(clean) >= 3:
                tokens.append(clean)
        return tokens

    def _status_for(self, blocking_issues: list[str], warnings: list[str]) -> str:
        if blocking_issues:
            return "blocked"
        if warnings:
            return "warning"
        return "ready"

    def _context_depth(self, tier: str) -> str:
        return {
            "A": "full",
            "B": "medium",
            "C": "compact",
            "D": "minimal",
        }.get(str(tier or "").upper(), "minimal")

    def _signature(
        self,
        *,
        request: SceneParticipationPrepareRequest,
        selection: SceneParticipantSelection | None,
        active_character_ids: list[str],
        pending_candidates: list[SceneCDRoleCreationCandidate],
        blocking_issues: list[str],
        warnings: list[str],
    ) -> str:
        import hashlib
        import json

        payload = {
            "chapter_id": request.chapter_id,
            "scene_index": request.scene_index,
            "scene_id": request.scene_id,
            "scene_goal": request.scene_goal,
            "scene_location": request.scene_location,
            "include_provisional": request.include_provisional,
            "selection_id": selection.selection_id if selection else "",
            "selection_status": selection.status if selection else "",
            "active_character_ids": active_character_ids,
            "pending_candidate_ids": [
                candidate.creation_candidate_id for candidate in pending_candidates
            ],
            "blocking_issues": blocking_issues,
            "warnings": warnings,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _read_models(self, path: Path, model: type[BaseModel]) -> list[Any]:
        if not path.exists():
            return []
        raw = self.store.read_any(path)
        if not isinstance(raw, list):
            raise StorageError(f"SCENE_PARTICIPATION_INVALID_STORAGE: {path.name} must be a list.")
        result: list[Any] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(model(**item))
            except ValidationError as exc:
                raise StorageError(
                    f"SCENE_PARTICIPATION_INVALID_STORAGE: {path.name} schema is invalid."
                ) from exc
        return result

    def _upsert_model(self, path: Path, model: BaseModel, id_field: str) -> None:
        rows: list[dict[str, Any]] = []
        if path.exists():
            raw = self.store.read_any(path)
            if not isinstance(raw, list):
                raise StorageError(f"SCENE_PARTICIPATION_INVALID_STORAGE: {path.name} must be a list.")
            rows = [dict(item) for item in raw if isinstance(item, dict)]
        payload = model_to_dict(model)
        target_id = str(payload.get(id_field) or "")
        updated = False
        next_rows: list[dict[str, Any]] = []
        for row in rows:
            if str(row.get(id_field) or "") == target_id:
                next_rows.append(payload)
                updated = True
            else:
                next_rows.append(row)
        if not updated:
            next_rows.append(payload)
        self.store.write(path, next_rows)

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
