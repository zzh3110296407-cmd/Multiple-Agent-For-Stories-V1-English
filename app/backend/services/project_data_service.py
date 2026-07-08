from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.character import Character
from app.backend.models.decision import Decision
from app.backend.models.event import Event
from app.backend.models.framework import Framework, FrameworkNode
from app.backend.models.framework_package import FrameworkPackage
from app.backend.models.issue import Issue
from app.backend.models.memory_record import MemoryRecord
from app.backend.models.project import ProjectState
from app.backend.models.project_data import ProjectDataBundle, SeedDataResponse
from app.backend.models.quality import QualityCheckResult, QualityIssue, QualityReport
from app.backend.models.relationship import Relationship
from app.backend.models.scene import Scene
from app.backend.models.state_change import StateChange
from app.backend.models.story_bible import StoryBible
from app.backend.models.world_canvas import WorldCanvas
from app.backend.services.active_project_story_data import (
    active_project_story_data_dir,
    active_project_without_story_data,
)
from app.backend.services.framework_package_service import FrameworkPackageService
from app.backend.storage.json_store import JsonStore, StorageError


SEED_CREATED_AT = "2026-06-04T00:00:00+08:00"
SEED_VERSION_ID = "version_debug_seed_001"
LOCAL_PROJECT_ID = "local_project"
ACTIVE_PROJECT_SELECTION_FILE = "active_project_selection.json"
PROJECT_REGISTRY_FILE = "project_registry.json"
PROJECT_ORIGIN_METADATA_FILE = "project_origin_metadata.json"
STORY_FACT_FILE_KEYS = [
    "project",
    "story_bible",
    "world_canvas",
    "characters",
    "relationships",
    "framework",
    "chapters",
    "scenes",
    "events",
    "state_changes",
    "memory_records",
    "decisions",
    "issues",
    "quality_reports",
]


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def serialize_jsonable(data: Any) -> Any:
    if isinstance(data, BaseModel):
        return model_to_dict(data)
    if isinstance(data, list):
        return [serialize_jsonable(item) for item in data]
    return data


class ProjectDataService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        project_file: Path | None = None,
        respect_active_project_selection: bool = False,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.respect_active_project_selection = respect_active_project_selection
        self.paths: dict[str, Path] = {
            "project": project_file or settings.project_file,
            "story_bible": self.data_dir / "story_bible.json",
            "world_canvas": self.data_dir / "world_canvas.json",
            "characters": self.data_dir / "characters.json",
            "relationships": self.data_dir / "relationships.json",
            "framework": self.data_dir / "framework.json",
            "chapters": self.data_dir / "chapters.json",
            "scenes": self.data_dir / "scenes.json",
            "events": self.data_dir / "events.json",
            "state_changes": self.data_dir / "state_changes.json",
            "memory_records": self.data_dir / "memory_records.json",
            "decisions": self.data_dir / "decisions.json",
            "issues": self.data_dir / "issues.json",
            "quality_reports": self.data_dir / "quality_reports.json",
        }
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.active_project_selection_file = self.data_dir / ACTIVE_PROJECT_SELECTION_FILE
        self.project_registry_file = self.data_dir / PROJECT_REGISTRY_FILE
        self.project_origin_metadata_file = self.data_dir / PROJECT_ORIGIN_METADATA_FILE

    def seed_data(self) -> SeedDataResponse:
        self._guard_debug_seed_allowed()
        payload = self._build_seed_payload()
        created_files: list[str] = []
        existing_files: list[str] = []
        updated_files: list[str] = []

        story_bible_existed = self._exists("story_bible")
        if self._upsert_story_bible(payload["story_bible"]):
            updated_files.append(self.paths["story_bible"].name)
        elif not story_bible_existed:
            created_files.append(self.paths["story_bible"].name)
        else:
            existing_files.append(self.paths["story_bible"].name)

        story_bible = self.read_story_bible()
        project_existed = self._exists("project")
        if self._upsert_project(payload["project"], story_bible):
            updated_files.append(self.paths["project"].name)
        elif not project_existed:
            created_files.append(self.paths["project"].name)
        else:
            existing_files.append(self.paths["project"].name)

        for key, data in payload.items():
            if key in {"project", "story_bible", "chapters"}:
                continue
            path = self.paths[key]
            if self.store.write_if_missing(path, serialize_jsonable(data)):
                created_files.append(path.name)
            else:
                existing_files.append(path.name)

        chapter_result = self._upsert_chapters(payload["chapters"], LOCAL_PROJECT_ID)
        if chapter_result == "created":
            created_files.append(self.paths["chapters"].name)
        elif chapter_result == "updated":
            updated_files.append(self.paths["chapters"].name)
        else:
            existing_files.append(self.paths["chapters"].name)

        bundle = self.get_project_data()
        return SeedDataResponse(
            seed_ready=bundle.seed_ready,
            created_files=created_files,
            existing_files=existing_files,
            updated_files=updated_files,
            data=bundle,
        )

    def get_project_data(self) -> ProjectDataBundle:
        scoped_dir = self._active_project_scoped_story_data_dir()
        if scoped_dir is not None:
            return self._active_project_scoped_bundle(scoped_dir)

        boundary = self._active_project_story_boundary()
        if boundary:
            return self._empty_active_project_bundle(boundary)

        missing_files = [
            path.name for path in self.paths.values() if not self.store.exists(path)
        ]
        project = self._read_optional_model("project", ProjectState)
        story_bible = self._read_optional_model("story_bible", StoryBible)
        world_canvas = self._read_optional_model("world_canvas", WorldCanvas)
        characters = self.read_characters() if self._exists("characters") else []
        relationships = (
            self.read_relationships() if self._exists("relationships") else []
        )
        framework = self._read_optional_model("framework", Framework)
        framework_package = self._read_optional_framework_package()
        framework_package_validation_issues = self._validate_framework_package()
        chapters = self.read_chapters() if self._exists("chapters") else []
        scenes = self.read_scenes() if self._exists("scenes") else []
        events = self.read_events() if self._exists("events") else []
        state_changes = (
            self.read_state_changes() if self._exists("state_changes") else []
        )
        memory_records = (
            self.read_memory_records() if self._exists("memory_records") else []
        )
        decisions = self.read_decisions() if self._exists("decisions") else []
        issues = self.read_issues() if self._exists("issues") else []
        quality_reports = (
            self.read_quality_reports() if self._exists("quality_reports") else []
        )
        validation_issues = self._validate_core_references(
            project=project,
            story_bible=story_bible,
            world_canvas=world_canvas,
            framework=framework,
            characters=characters,
            relationships=relationships,
            chapters=chapters,
        )
        active_project_id = project.project_id if project else None
        project_origin_type = "legacy_debug" if project and project.project_id == LOCAL_PROJECT_ID else ""
        story_data_scope = "local_project"
        if (
            self.respect_active_project_selection
            and project is not None
            and project.project_id != LOCAL_PROJECT_ID
        ):
            selection = self._read_active_project_selection()
            if selection and str(selection.get("project_id") or "") == project.project_id:
                project_origin_type = self._origin_type_for_project(project.project_id)
                story_data_scope = "active_project"

        return ProjectDataBundle(
            seed_ready=len(missing_files) == 0 and len(validation_issues) == 0,
            missing_files=missing_files,
            validation_issues=validation_issues,
            active_project_id=active_project_id,
            project_origin_type=project_origin_type,
            story_data_scope=story_data_scope,
            setup_required=False,
            project=project,
            story_bible=story_bible,
            world_canvas=world_canvas,
            characters=characters,
            relationships=relationships,
            framework=framework,
            framework_package=framework_package,
            framework_package_ready=(
                framework_package is not None
                and len(framework_package_validation_issues) == 0
            ),
            framework_package_validation_issues=framework_package_validation_issues,
            chapters=chapters,
            scenes=scenes,
            events=events,
            state_changes=state_changes,
            memory_records=memory_records,
            decisions=decisions,
            issues=issues,
            quality_reports=quality_reports,
        )

    def read_story_bible(self) -> StoryBible:
        self._guard_active_story_data_read()
        return self._read_model("story_bible", StoryBible)

    def read_world_canvas(self) -> WorldCanvas:
        self._guard_active_story_data_read()
        return self._read_model("world_canvas", WorldCanvas)

    def read_framework(self) -> Framework:
        self._guard_active_story_data_read()
        return self._read_model("framework", Framework)

    def read_framework_package(self) -> FrameworkPackage:
        self._guard_active_story_data_read()
        data = self.store.read(self.framework_package_file)
        try:
            return FrameworkPackage(**data)
        except ValidationError as exc:
            raise StorageError(
                f"JSON schema is invalid: {self.framework_package_file}"
            ) from exc

    def read_characters(self) -> list[Character]:
        self._guard_active_story_data_read()
        return self._read_model_list("characters", Character)

    def read_relationships(self) -> list[Relationship]:
        self._guard_active_story_data_read()
        return self._read_model_list("relationships", Relationship)

    def read_chapters(self) -> list[Chapter]:
        self._guard_active_story_data_read()
        return self._read_model_list("chapters", Chapter)

    def read_scenes(self) -> list[Scene]:
        self._guard_active_story_data_read()
        return self._read_model_list("scenes", Scene)

    def read_events(self) -> list[Event]:
        self._guard_active_story_data_read()
        return self._read_model_list("events", Event)

    def read_state_changes(self) -> list[StateChange]:
        self._guard_active_story_data_read()
        return self._read_model_list("state_changes", StateChange)

    def read_memory_records(self) -> list[MemoryRecord]:
        self._guard_active_story_data_read()
        return self._read_model_list("memory_records", MemoryRecord)

    def read_decisions(self) -> list[Decision]:
        self._guard_active_story_data_read()
        return self._read_model_list("decisions", Decision)

    def read_issues(self) -> list[Issue]:
        self._guard_active_story_data_read()
        return self._read_model_list("issues", Issue)

    def read_quality_reports(self) -> list[QualityReport]:
        self._guard_active_story_data_read()
        return self._read_model_list("quality_reports", QualityReport)

    def _guard_debug_seed_allowed(self) -> None:
        if not self.respect_active_project_selection:
            return
        boundary = self._active_project_story_boundary()
        if not boundary:
            return
        project_id = boundary["project"].project_id
        raise StorageError(
            "DEBUG_SEED_REQUIRES_LOCAL_DEBUG_PROJECT: "
            f"Debug seed data cannot be written while active project is {project_id}."
        )

    def _guard_active_story_data_read(self) -> None:
        boundary = self._active_project_story_boundary()
        if not boundary:
            return
        project_id = boundary["project"].project_id
        raise StorageError(
            "Story data does not exist for active project "
            f"{project_id}; legacy story data is not used as fallback."
        )

    def _active_project_story_boundary(self) -> dict[str, Any] | None:
        if not self.respect_active_project_selection:
            return None
        selection = self._read_active_project_selection()
        if not selection:
            return None
        project_id = active_project_without_story_data(self.store, self.data_dir)
        if not project_id:
            return None

        project = self._project_state_for_selection(project_id)
        origin_type = self._origin_type_for_project(project_id)
        return {
            "selection": selection,
            "project": project,
            "origin_type": origin_type,
        }

    def _active_project_scoped_story_data_dir(self) -> Path | None:
        if not self.respect_active_project_selection:
            return None
        scoped_dir = active_project_story_data_dir(self.store, self.data_dir)
        if scoped_dir is None or scoped_dir == self.data_dir:
            return None
        return scoped_dir

    def _active_project_scoped_bundle(self, scoped_dir: Path) -> ProjectDataBundle:
        selection = self._read_active_project_selection() or {}
        scoped_service = ProjectDataService(
            store=self.store,
            data_dir=scoped_dir,
            project_file=scoped_dir / "project.json",
            respect_active_project_selection=False,
        )
        bundle = scoped_service.get_project_data()
        if hasattr(bundle, "model_dump"):
            payload = bundle.model_dump(mode="json")
        else:
            payload = bundle.dict()
        project_id = str(selection.get("project_id") or payload.get("active_project_id") or "")
        payload["active_project_id"] = project_id or payload.get("active_project_id")
        payload["active_project_selection_id"] = selection.get("active_project_selection_id")
        payload["project_origin_type"] = self._origin_type_for_project(project_id) if project_id else ""
        payload["story_data_scope"] = "active_project"
        payload["setup_required"] = False
        return ProjectDataBundle(**payload)

    def _empty_active_project_bundle(self, boundary: dict[str, Any]) -> ProjectDataBundle:
        project = boundary["project"]
        selection = boundary["selection"]
        missing_files = [
            self.paths[key].name
            for key in STORY_FACT_FILE_KEYS
            if key != "project"
        ]
        if not self._local_story_project_id() or self._local_story_project_id() != project.project_id:
            missing_files.insert(0, self.paths["project"].name)
        return ProjectDataBundle(
            seed_ready=False,
            missing_files=missing_files,
            validation_issues=["story_data_setup_required_for_active_project"],
            active_project_id=project.project_id,
            active_project_selection_id=selection.get("active_project_selection_id"),
            project_origin_type=boundary.get("origin_type") or "",
            story_data_scope="active_project_setup_required",
            setup_required=True,
            project=project,
            framework_package_validation_issues=[],
        )

    def _read_active_project_selection(self) -> dict[str, Any] | None:
        if not self.store.exists(self.active_project_selection_file):
            return None
        try:
            payload = self.store.read(self.active_project_selection_file)
        except StorageError:
            return None
        return payload if isinstance(payload, dict) else None

    def _local_story_project_id(self) -> str | None:
        if not self.store.exists(self.paths["project"]):
            return None
        try:
            payload = self.store.read(self.paths["project"])
        except StorageError:
            return None
        if not isinstance(payload, dict):
            return None
        value = payload.get("project_id")
        return str(value) if value else None

    def _project_state_for_selection(self, project_id: str) -> ProjectState:
        shell = self._project_shell_payload(project_id)
        return ProjectState(
            project_id=project_id,
            title=str(shell.get("title") or "Untitled Story Project"),
            language=str(shell.get("language") or "zh"),
            phase="phase_8_5",
            current_phase="productized_workspace",
            current_step=str(shell.get("current_step") or "story_setup_required"),
            status=str(shell.get("status") or "project_shell_created"),
            story_bible_id=None,
            created_at=shell.get("created_at"),
            updated_at=shell.get("updated_at"),
        )

    def _project_shell_payload(self, project_id: str) -> dict[str, Any]:
        if self.store.exists(self.project_registry_file):
            try:
                registry = self.store.read(self.project_registry_file)
            except StorageError:
                registry = {}
            projects = registry.get("projects") if isinstance(registry, dict) else []
            if isinstance(projects, list):
                for item in projects:
                    if isinstance(item, dict) and item.get("project_id") == project_id:
                        return item
        return {
            "project_id": project_id,
            "title": "Untitled Story Project",
            "language": "zh",
            "status": "project_shell_selected",
            "current_step": "story_setup_required",
        }

    def _origin_type_for_project(self, project_id: str) -> str:
        if self.store.exists(self.project_origin_metadata_file):
            try:
                records = self.store.read_list(self.project_origin_metadata_file)
            except StorageError:
                records = []
            for item in records:
                if isinstance(item, dict) and item.get("project_id") == project_id:
                    return str(item.get("origin_type") or "")
        return "unknown_origin"

    def _exists(self, key: str) -> bool:
        return self.store.exists(self.paths[key])

    def _read_optional_model(
        self, key: str, model_type: type[BaseModel]
    ) -> BaseModel | None:
        if not self._exists(key):
            return None
        return self._read_model(key, model_type)

    def _read_optional_framework_package(self) -> FrameworkPackage | None:
        if not self.store.exists(self.framework_package_file):
            return None
        return self.read_framework_package()

    def _validate_framework_package(self) -> list[str]:
        if not self.store.exists(self.framework_package_file):
            return ["Framework package is missing."]
        validation = FrameworkPackageService(
            store=self.store,
            data_dir=self.data_dir,
        ).validate_framework_package()
        return validation.issues

    def _read_model(self, key: str, model_type: type[BaseModel]) -> BaseModel:
        path = self.paths[key]
        data = self.store.read(path)
        try:
            return model_type(**data)
        except ValidationError as exc:
            raise StorageError(f"JSON schema is invalid: {path}") from exc

    def _read_model_list(
        self, key: str, model_type: type[BaseModel]
    ) -> list[BaseModel]:
        path = self.paths[key]
        data = self.store.read_list(path)
        try:
            return [model_type(**item) for item in data]
        except TypeError as exc:
            raise StorageError(f"JSON list item must be an object: {path}") from exc
        except ValidationError as exc:
            raise StorageError(f"JSON schema is invalid: {path}") from exc

    def _upsert_project(self, seed_project: ProjectState, seed_bible: StoryBible) -> bool:
        path = self.paths["project"]
        if not self.store.exists(path):
            self.store.write(path, model_to_dict(seed_project))
            return False

        existing = self.store.read(path)
        updated = dict(existing)
        technical_updates = {
            "project_id": LOCAL_PROJECT_ID,
            "phase": existing.get("phase") or seed_project.phase,
            "current_phase": existing.get("current_phase") or seed_project.current_phase,
            "current_step": "seed_data_ready",
            "status": "seeded",
            "story_bible_id": seed_bible.story_bible_id,
            "created_at": existing.get("created_at") or seed_project.created_at,
            "updated_at": SEED_CREATED_AT,
        }
        updated.update(technical_updates)
        if "title" not in updated or not updated["title"]:
            updated["title"] = seed_project.title
        if "language" not in updated or not updated["language"]:
            updated["language"] = seed_project.language

        if updated != existing:
            self.store.write(path, updated)
            return True
        return False

    def _upsert_story_bible(self, seed_bible: StoryBible) -> bool:
        path = self.paths["story_bible"]
        if not self.store.exists(path):
            self.store.write(path, model_to_dict(seed_bible))
            return False

        existing = self.store.read(path)
        updated = dict(existing)
        updated["story_bible_id"] = (
            updated.get("story_bible_id") or seed_bible.story_bible_id
        )
        updated["project_id"] = LOCAL_PROJECT_ID
        updated["world_canvas_id"] = (
            updated.get("world_canvas_id") or seed_bible.world_canvas_id
        )
        updated["active_framework_id"] = (
            updated.get("active_framework_id") or seed_bible.active_framework_id
        )
        updated["main_character_ids"] = (
            updated.get("main_character_ids") or seed_bible.main_character_ids
        )
        updated["relationship_ids"] = (
            updated.get("relationship_ids") or seed_bible.relationship_ids
        )
        updated["version_id"] = updated.get("version_id") or seed_bible.version_id

        if updated != existing:
            self.store.write(path, updated)
            return True
        return False

    def _upsert_chapters(
        self, seed_chapters: list[Chapter], project_id: str
    ) -> str:
        path = self.paths["chapters"]
        if not self.store.exists(path):
            self.store.write(path, serialize_jsonable(seed_chapters))
            return "created"

        existing = self.store.read_list(path)
        updated = []
        changed = False
        for item in existing:
            if not isinstance(item, dict):
                raise StorageError(f"JSON list item must be an object: {path}")
            new_item = dict(item)
            if new_item.get("project_id") != project_id:
                new_item["project_id"] = project_id
                changed = True
            updated.append(new_item)
        if changed:
            self.store.write(path, updated)
            return "updated"
        return "existing"

    def _validate_core_references(
        self,
        project: ProjectState | None,
        story_bible: StoryBible | None,
        world_canvas: WorldCanvas | None,
        framework: Framework | None,
        characters: list[Character],
        relationships: list[Relationship],
        chapters: list[Chapter],
    ) -> list[str]:
        issues: list[str] = []
        if project is None:
            issues.append("Project is missing.")
            return issues
        if story_bible is None:
            issues.append("StoryBible is missing.")
            return issues

        if project.project_id != story_bible.project_id:
            issues.append("Project.project_id must match StoryBible.project_id.")
        if not project.story_bible_id:
            issues.append("Project.story_bible_id must not be empty.")
        elif project.story_bible_id != story_bible.story_bible_id:
            issues.append("Project.story_bible_id must match StoryBible.story_bible_id.")

        if not story_bible.world_canvas_id:
            issues.append("StoryBible.world_canvas_id must not be empty.")
        elif world_canvas is None:
            issues.append("WorldCanvas file is missing.")
        elif story_bible.world_canvas_id != world_canvas.world_canvas_id:
            issues.append("StoryBible.world_canvas_id must match WorldCanvas.world_canvas_id.")

        if not story_bible.active_framework_id:
            issues.append("StoryBible.active_framework_id must not be empty.")
        elif framework is None:
            issues.append("Framework file is missing.")
        elif story_bible.active_framework_id != framework.framework_id:
            issues.append("StoryBible.active_framework_id must match Framework.framework_id.")

        character_ids = {character.character_id for character in characters}
        missing_character_ids = [
            character_id
            for character_id in story_bible.main_character_ids
            if character_id not in character_ids
        ]
        if missing_character_ids:
            issues.append("StoryBible.main_character_ids must point to existing Characters.")

        relationship_ids = {
            relationship.relationship_id for relationship in relationships
        }
        missing_relationship_ids = [
            relationship_id
            for relationship_id in story_bible.relationship_ids
            if relationship_id not in relationship_ids
        ]
        if missing_relationship_ids:
            issues.append("StoryBible.relationship_ids must point to existing Relationships.")

        for chapter in chapters:
            if chapter.project_id != project.project_id:
                issues.append("Chapter.project_id must match Project.project_id.")
                break
        return issues

    def _build_seed_payload(self) -> dict[str, Any]:
        """Build a generic development fixture without story-specific legacy content."""
        project = ProjectState(
            project_id=LOCAL_PROJECT_ID,
            title="Development Seed Project",
            language="zh",
            phase="phase_1",
            current_phase="foundation",
            current_step="seed_data_ready",
            status="seeded",
            story_bible_id="bible_debug_seed",
            created_at=SEED_CREATED_AT,
            updated_at=SEED_CREATED_AT,
        )
        story_bible = StoryBible(
            story_bible_id="bible_debug_seed",
            project_id=LOCAL_PROJECT_ID,
            world_canvas_id="world_debug_seed",
            active_framework_id="framework_debug_basic",
            main_character_ids=["char_debug_mira", "char_debug_ren"],
            relationship_ids=["rel_debug_mira_ren"],
            version_id=SEED_VERSION_ID,
        )
        world_canvas = WorldCanvas(
            world_canvas_id="world_debug_seed",
            scope="coastal city",
            tone="restrained mystery adventure",
            hard_rules=[
                "Every public clue must have an observable source before it becomes canon.",
                "Memory records must cite the scene or event that produced them.",
            ],
            soft_rules=[
                "Rumors may mislead characters until verified by a later scene.",
                "Weather and public pressure can change how witnesses behave.",
            ],
            unknown_rules=[
                "The origin of the missing archive remains unconfirmed.",
                "The first witness may be mistaken or withholding context.",
            ],
            locations=[
                {
                    "location_id": "loc_debug_harbor_archive",
                    "name": "Harbor Archive",
                    "summary": "A public archive near the ferry terminal where several records conflict.",
                }
            ],
            factions=[
                {
                    "faction_id": "faction_debug_civic_watch",
                    "name": "Civic Watch",
                    "summary": "A municipal group that preserves witness statements and access logs.",
                }
            ],
            species=[],
            version_id=SEED_VERSION_ID,
        )
        characters = [
            Character(
                character_id="char_debug_mira",
                name="Mira",
                tier="A",
                role="protagonist",
                profile={
                    "description": "A careful investigator returning to a disputed civic archive.",
                    "traits": ["observant", "patient", "skeptical of convenient answers"],
                    "goals": ["verify which archive entry was altered"],
                    "fears": ["turning an unverified rumor into public fact"],
                    "secrets": ["once ignored a witness who later disappeared"],
                },
                current_state={
                    "location_id": "loc_debug_harbor_archive",
                    "emotional_state": "focused but uneasy",
                    "knowledge": ["two access logs disagree about the same night"],
                    "active_goal": "compare the paper register with the public copy",
                },
                relationship_refs=["rel_debug_mira_ren"],
                event_refs=["event_debug_archive_meeting"],
                arc_state={
                    "current_arc": "from cautious observer to accountable investigator",
                    "pressure": "public attention grows before facts are confirmed",
                    "next_possible_change": "share a limited finding while preserving uncertainty",
                },
                version_id=SEED_VERSION_ID,
            ),
            Character(
                character_id="char_debug_ren",
                name="Ren",
                tier="A",
                role="supporting investigator",
                profile={
                    "description": "A records technician who knows how the archive audit trail works.",
                    "traits": ["precise", "defensive", "loyal to procedure"],
                    "goals": ["protect the archive process from political misuse"],
                    "fears": ["being blamed for records altered before his shift"],
                    "secrets": ["kept a private copy of one disputed access log"],
                },
                current_state={
                    "location_id": "loc_debug_harbor_archive",
                    "emotional_state": "guarded and tired",
                    "knowledge": ["the missing signature was not removed by normal workflow"],
                    "active_goal": "decide how much to reveal to Mira",
                },
                relationship_refs=["rel_debug_mira_ren"],
                event_refs=["event_debug_archive_meeting"],
                arc_state={
                    "current_arc": "from procedure-bound witness to active collaborator",
                    "pressure": "revealing the copy could end his job",
                    "next_possible_change": "provide a partial copy with conditions",
                },
                version_id=SEED_VERSION_ID,
            ),
        ]
        relationships = [
            Relationship(
                relationship_id="rel_debug_mira_ren",
                source_id="char_debug_mira",
                target_id="char_debug_ren",
                type="conditional_trust",
                state="They can cooperate on evidence, but neither fully trusts the other's motive.",
                strength=0.55,
                evidence_event_ids=["event_debug_archive_meeting"],
            )
        ]
        framework = Framework(
            framework_id="framework_debug_basic",
            project_id=LOCAL_PROJECT_ID,
            name="Debug Baseline Framework",
            constraint_strength="strong",
            maturity="System",
            source="system_debug_fixture",
            framework_package_id="fw_pkg_default_strong",
            module_ids=["module_foundation"],
            stage_ids=["stage_incident", "stage_pressure"],
            beat_ids=["beat_archive_discrepancy", "beat_conditional_trust"],
            nodes=[
                FrameworkNode(
                    node_id="node_inciting_discrepancy",
                    name="Inciting discrepancy",
                    description="A public record conflicts with a private source and forces investigation.",
                    position=1,
                ),
                FrameworkNode(
                    node_id="node_cost_of_evidence",
                    name="Cost of evidence",
                    description="Clarify what each character risks by verifying the record.",
                    position=2,
                ),
            ],
        )
        chapters = [
            Chapter(
                chapter_id="chapter_debug_seed_001",
                project_id=LOCAL_PROJECT_ID,
                summary="Mira returns to the Harbor Archive and meets Ren beside conflicting records.",
                goals=[
                    "establish the evidence-source rule",
                    "create conditional trust between Mira and Ren",
                ],
                participant_character_ids=["char_debug_mira", "char_debug_ren"],
                scene_ids=["scene_debug_seed_001"],
                status="thinking",
            )
        ]
        scenes = [
            Scene(
                scene_id="scene_debug_seed_001",
                chapter_id="chapter_debug_seed_001",
                scene_index=1,
                goal="Make the first confirmed discrepancy visible without resolving its cause.",
                synopsis="Mira compares two archive entries while Ren decides whether to reveal a private copy.",
                prose_text="Rain tapped the archive windows while Mira held the public register beside Ren's private copy. The dates matched; the signature did not.",
                input_memory_ids=["memory_debug_archive_meeting"],
                event_ids=["event_debug_archive_meeting"],
                state_change_ids=["change_debug_trust"],
                status="outputs",
            )
        ]
        events = [
            Event(
                event_id="event_debug_archive_meeting",
                scene_id="scene_debug_seed_001",
                summary="Mira and Ren compare conflicting archive entries and agree to verify the source before naming a culprit.",
                participants=["char_debug_mira", "char_debug_ren"],
                location_id="loc_debug_harbor_archive",
                cause="The public register and private copy disagree on a key signature.",
                result="They form a limited partnership and leave the culprit unidentified.",
                tags=["evidence_source", "conditional_trust", "debug_seed"],
            )
        ]
        state_changes = [
            StateChange(
                state_change_id="change_debug_trust",
                target_type="relationship",
                target_id="rel_debug_mira_ren",
                before={"strength": 0.35, "state": "Professional distance and mutual suspicion."},
                after={"strength": 0.55, "state": "Limited cooperation around verified evidence."},
                reason_event_id="event_debug_archive_meeting",
                requires_user_confirmation=True,
                status="proposed",
            )
        ]
        decisions = [
            Decision(
                decision_id="decision_debug_evidence_rule_001",
                decision_type="confirm",
                target_type="world_rule",
                target_id="world_debug_seed",
                user_input="Keep the evidence-source rule: public claims need observable support before becoming canon.",
                created_at=SEED_CREATED_AT,
            )
        ]
        memory_records = [
            MemoryRecord(
                memory_id="memory_debug_archive_meeting",
                source_type="generated",
                object_type="event",
                object_id="event_debug_archive_meeting",
                summary="Mira and Ren found a signature mismatch and agreed not to treat rumors as canon without verification.",
                tags=["debug_seed", "evidence_source", "mira", "ren"],
                embedding_ref="",
                version_id=SEED_VERSION_ID,
            )
        ]
        issues = [
            Issue(
                issue_id="issue_debug_signature_origin",
                type="foreshadowing_todo",
                summary="Later chapters must identify why the signature changed or preserve it as unresolved uncertainty.",
                related_scene_id="scene_debug_seed_001",
                status="open",
                ask_user_when="chapter_planning_near_signature_origin",
            )
        ]
        quality_reports = [
            QualityReport(
                quality_report_id="quality_debug_seed_001",
                target_type="scene",
                target_id="scene_debug_seed_001",
                scene_id="scene_debug_seed_001",
                passed=True,
                warnings=[
                    QualityIssue(
                        issue_id="quality_debug_signature_origin_warning",
                        category="foreshadowing_todo",
                        severity="warning",
                        message="Debug seed leaves the signature origin as a later continuity todo.",
                        related_object_type="issue",
                        related_object_id="issue_debug_signature_origin",
                        suggested_action="Resolve or intentionally preserve this uncertainty during chapter planning.",
                    )
                ],
                check_results=[
                    QualityCheckResult(
                        check_id="quality_debug_seed_minimal_objects",
                        check_name="minimal_objects",
                        passed=True,
                        status="completed",
                        summary="Debug seed includes every minimal object category.",
                    ),
                    QualityCheckResult(
                        check_id="quality_debug_seed_continuity_placeholder",
                        check_name="continuity_placeholder",
                        passed=True,
                        status="completed",
                        summary="Debug seed leaves one explicit continuity todo for later planning.",
                    ),
                ],
                semantic_check_status="not_run",
                summary="Debug seed quality snapshot uses the current QualityReport schema.",
                generated_by="project_data_debug_seed",
                version_id=SEED_VERSION_ID,
                created_at=SEED_CREATED_AT,
            )
        ]
        return {
            "project": project,
            "story_bible": story_bible,
            "world_canvas": world_canvas,
            "characters": characters,
            "relationships": relationships,
            "framework": framework,
            "chapters": chapters,
            "scenes": scenes,
            "events": events,
            "state_changes": state_changes,
            "memory_records": memory_records,
            "decisions": decisions,
            "issues": issues,
            "quality_reports": quality_reports,
        }
