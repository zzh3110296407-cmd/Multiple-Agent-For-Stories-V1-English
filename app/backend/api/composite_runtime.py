from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.backend.services.active_project_boundary_service import (
    ActiveProjectStoryDataBlocked,
    ActiveProjectBoundaryService,
)
from app.backend.services.composite_runtime_read_service import CompositeRuntimeReadService
from app.backend.storage.json_store import JsonStore


router = APIRouter(tags=["composite-runtime"])


def composite_runtime_read_service() -> CompositeRuntimeReadService:
    store = JsonStore()
    try:
        data_dir = ActiveProjectBoundaryService(store=store).ensure_story_workspace_available()
    except ActiveProjectStoryDataBlocked:
        return CompositeRuntimeReadService(
            store=store,
            data_dir=None,
            allow_default_data_dir=False,
            allow_static_fallback=False,
            blocked_reason=(
                "Story workspace data is not available for the active project. "
                "Composite Runtime evidence is scoped to the active project."
            ),
        )
    return CompositeRuntimeReadService(store=store, data_dir=data_dir)


@router.get("/runs/latest")
def get_latest_composite_runtime_run(
    chapter_id: str | None = None,
    scene_id: str | None = None,
    scene_index: int | None = None,
    include_expert: bool = False,
) -> dict[str, Any]:
    return composite_runtime_read_service().latest_run(
        chapter_id=chapter_id,
        scene_id=scene_id,
        scene_index=scene_index,
        include_expert=include_expert,
    )


@router.get("/runs/{graph_run_id}")
def get_composite_runtime_run(
    graph_run_id: str,
    include_expert: bool = False,
) -> dict[str, Any]:
    return composite_runtime_read_service().get_run(graph_run_id, include_expert=include_expert)


@router.get("/runs/{graph_run_id}/node-receipts")
def get_composite_runtime_node_receipts(graph_run_id: str) -> dict[str, Any]:
    return composite_runtime_read_service().node_receipts(graph_run_id)


@router.get("/runs/{graph_run_id}/authority-audit")
def get_composite_runtime_authority_audit(graph_run_id: str) -> dict[str, Any]:
    return composite_runtime_read_service().authority_audit(graph_run_id)


@router.get("/runs/{graph_run_id}/expert-summary")
def get_composite_runtime_expert_summary(graph_run_id: str) -> dict[str, Any]:
    return composite_runtime_read_service().expert_summary(graph_run_id)
