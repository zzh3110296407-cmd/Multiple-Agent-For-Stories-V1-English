from pathlib import Path
import inspect
from typing import TypeVar

from app.backend.services.active_project_boundary_service import ActiveProjectBoundaryService


ServiceT = TypeVar("ServiceT")

GLOBAL_RUNTIME_DEPENDENCIES = (
    "model_gateway",
    "agent",
    "scene_information_agent",
    "write_agent",
    "memory_curator_agent",
    "quality_check_agent",
    "scene_revision_agent",
    "fallback_builder",
    "semantic_agent",
)


def active_story_data_dir_for_service(service: object) -> Path:
    store = getattr(service, "store")
    data_dir = getattr(service, "data_dir")
    return ActiveProjectBoundaryService(
        store=store,
        data_dir=data_dir,
    ).ensure_story_workspace_available()


def scoped_story_service(service: ServiceT, service_type: type[ServiceT]) -> ServiceT:
    story_data_dir = active_story_data_dir_for_service(service)
    if story_data_dir == getattr(service, "data_dir"):
        return service
    kwargs = {
        "store": getattr(service, "store"),
        "data_dir": story_data_dir,
    }
    parameters = inspect.signature(service_type.__init__).parameters
    for dependency_name in GLOBAL_RUNTIME_DEPENDENCIES:
        if dependency_name in parameters and hasattr(service, dependency_name):
            dependency = getattr(service, dependency_name)
            if _can_reuse_scoped_dependency(dependency):
                kwargs[dependency_name] = dependency
    return service_type(**kwargs)


def _can_reuse_scoped_dependency(dependency: object) -> bool:
    return not (
        hasattr(dependency, "data_dir")
        or hasattr(dependency, "model_gateway")
        or dependency.__class__.__name__ == "ModelGatewayService"
    )
