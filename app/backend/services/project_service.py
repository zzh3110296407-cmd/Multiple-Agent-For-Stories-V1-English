from pathlib import Path

from app.backend.core.config import settings
from app.backend.models.project import ProjectState, ProjectStatusResponse
from app.backend.storage.json_store import JsonStore


class ProjectService:
    def __init__(self, store: JsonStore | None = None, project_file: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.project_file = project_file or settings.project_file

    def get_status(self) -> ProjectStatusResponse:
        if not self.store.exists(self.project_file):
            return ProjectStatusResponse(
                initialized=False,
                message="Local project has not been initialized.",
            )

        project = ProjectState(**self.store.read(self.project_file))
        return ProjectStatusResponse(initialized=True, project=project)

    def initialize_project(self) -> ProjectStatusResponse:
        default_project = ProjectState()
        project_data = (
            default_project.model_dump()
            if hasattr(default_project, "model_dump")
            else default_project.dict()
        )
        created = self.store.write_if_missing(
            self.project_file,
            project_data,
        )

        if created:
            return ProjectStatusResponse(
                initialized=True,
                message="Local project initialized.",
                project=default_project,
            )

        project = ProjectState(**self.store.read(self.project_file))
        return ProjectStatusResponse(
            initialized=True,
            message="Local project already exists.",
            project=project,
        )
