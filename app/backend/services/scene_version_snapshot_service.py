import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.scene_snapshot import (
    ALLOWED_SCENE_SNAPSHOT_REF_TYPES,
    SCENE_SNAPSHOT_VERSION_ID,
    SNAPSHOT_INVALIDATION_VERSION_ID,
    SNAPSHOT_TYPES,
    SceneDependencyGraphSummaryResponse,
    SceneSnapshotRef,
    SceneVersionSnapshot,
    SnapshotInvalidationRecord,
    SnapshotInvalidationResponse,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
MAX_SAFE_TEXT_LENGTH = 700
MAX_SAFE_LABEL_LENGTH = 180
MAX_SAFE_METADATA_TEXT_LENGTH = 160
UNSAFE_VALUE_MARKERS = {
    "raw_prompt",
    "raw response",
    "raw_response",
    "hidden_reasoning",
    "hidden reasoning",
    "chain_of_thought",
    "chain-of-thought",
    "chain of thought",
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "api_key",
    "authorization",
}
SECRET_LIKE_PATTERNS = [
    re.compile(r"(?i)(?:^|[^a-z0-9])sk-[a-z0-9][a-z0-9_\-]{8,}"),
    re.compile(r"(?i)(?:^|[^a-z0-9])lsv2_[a-z0-9][a-z0-9_\-]{8,}"),
    re.compile(r"(?i)(?:api[_\-\s]?key|secret[_\-\s]?(?:key|token)|authorization)\s*[:=]\s*[a-z0-9_\-]{8,}"),
]
UNSAFE_SECRET_KEY_NAMES = {
    "secret",
    "secret_key",
    "secret_token",
    "api_secret",
    "authorization_token",
    "bearer_token",
}
UNSAFE_KEY_NAMES = {
    "raw_prompt",
    "raw_response",
    "hidden_reasoning",
    "chain_of_thought",
    "cot",
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "api_key",
    "authorization",
} | UNSAFE_SECRET_KEY_NAMES
SAFE_ID_FIELDS = {
    "event_id",
    "state_change_id",
    "memory_id",
    "chapter_memory_pack_id",
    "scene_memory_pack_id",
    "chapter_framework_id",
    "framework_package_id",
    "character_id",
    "relationship_id",
    "narrative_intent_id",
    "quality_report_id",
    "decision_id",
}


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


class SceneVersionSnapshotService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.snapshots_file = self.data_dir / "scene_version_snapshots.json"
        self.invalidations_file = self.data_dir / "snapshot_invalidation_records.json"

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def create_snapshot_for_scene(
        self,
        scene_id: str,
        snapshot_type: str = "confirmed_scene",
        target_scene_id: str = "",
        extra_refs: list[SceneSnapshotRef | dict[str, Any]] | None = None,
    ) -> SceneVersionSnapshot:
        clean_scene_id = str(scene_id or "").strip()
        if not clean_scene_id:
            raise StorageError("SCENE_SNAPSHOT_SCENE_ID_REQUIRED: scene_id must not be empty.")
        scene = self.repositories.scenes.get_by_id(clean_scene_id)
        if scene is None:
            raise StorageError("SCENE_SNAPSHOT_SCENE_NOT_FOUND: scene does not exist.")
        clean_snapshot_type = str(snapshot_type or "").strip()
        if clean_snapshot_type not in SNAPSHOT_TYPES:
            raise StorageError(
                "SCENE_SNAPSHOT_INVALID_SNAPSHOT_TYPE: snapshot_type is not supported."
            )

        timestamp = now_iso()
        refs = self._collect_scene_refs(scene)
        refs.extend(self._normalize_extra_refs(extra_refs or []))
        refs = self._dedupe_refs(refs)
        source_ref_counts = self._ref_counts(refs)
        safe_summary = self._safe_scene_summary(scene, refs)
        snapshot_id = self._next_snapshot_id()
        snapshot_payload = {
            "snapshot_id": snapshot_id,
            "project_id": str(scene.get("project_id") or LOCAL_PROJECT_ID),
            "snapshot_type": clean_snapshot_type,
            "subject_type": "scene",
            "subject_id": clean_scene_id,
            "subject_version_id": str(scene.get("version_id") or ""),
            "subject_status": str(scene.get("status") or ""),
            "target_scene_id": target_scene_id or clean_scene_id,
            "chapter_id": str(scene.get("chapter_id") or ""),
            "chapter_index": _safe_int(scene.get("chapter_index")),
            "source_refs": [model_to_dict(ref) for ref in refs],
            "source_ref_counts": source_ref_counts,
            "safe_summary": safe_summary,
            "snapshot_hash": "",
            "status": "active",
            "stale_reason": "",
            "created_at": timestamp,
            "updated_at": timestamp,
            "version_id": SCENE_SNAPSHOT_VERSION_ID,
        }
        snapshot_payload["snapshot_hash"] = self._snapshot_hash(snapshot_payload)
        self._guard_safe_payload(snapshot_payload)
        snapshot = SceneVersionSnapshot(**snapshot_payload)
        snapshots = self._read_snapshots()
        snapshots.append(snapshot)
        self._write_snapshots(snapshots)
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> SceneVersionSnapshot:
        clean_id = str(snapshot_id or "").strip()
        for snapshot in self._read_snapshots():
            if snapshot.snapshot_id == clean_id:
                return snapshot
        raise StorageError("SCENE_SNAPSHOT_NOT_FOUND: snapshot does not exist.")

    def list_snapshots(
        self,
        scene_id: str | None = None,
        status: str | None = None,
        snapshot_type: str | None = None,
    ) -> list[SceneVersionSnapshot]:
        clean_scene_id = str(scene_id or "").strip()
        clean_status = str(status or "").strip()
        clean_type = str(snapshot_type or "").strip()
        result = self._read_snapshots()
        if clean_scene_id:
            result = [
                snapshot
                for snapshot in result
                if snapshot.target_scene_id == clean_scene_id
                or snapshot.subject_id == clean_scene_id
            ]
        if clean_status:
            result = [snapshot for snapshot in result if snapshot.status == clean_status]
        if clean_type:
            result = [
                snapshot
                for snapshot in result
                if snapshot.snapshot_type == clean_type
            ]
        return sorted(result, key=lambda item: item.created_at, reverse=True)

    def list_snapshots_using_ref(
        self,
        ref_type: str,
        ref_id: str,
        status: str | None = None,
    ) -> list[SceneVersionSnapshot]:
        clean_type = self._validate_ref_type(ref_type)
        clean_id = str(ref_id or "").strip()
        if not clean_id:
            raise StorageError("SCENE_SNAPSHOT_REF_ID_REQUIRED: ref_id must not be empty.")
        clean_status = str(status or "").strip()
        snapshots = [
            snapshot
            for snapshot in self._read_snapshots()
            if any(
                ref.ref_type == clean_type and ref.ref_id == clean_id
                for ref in snapshot.source_refs
            )
        ]
        if clean_status:
            snapshots = [
                snapshot for snapshot in snapshots if snapshot.status == clean_status
            ]
        return sorted(snapshots, key=lambda item: item.created_at, reverse=True)

    def invalidate_by_changed_ref(
        self,
        changed_ref_type: str,
        changed_ref_id: str,
        old_version_id: str = "",
        new_version_id: str = "",
        reason: str = "",
    ) -> SnapshotInvalidationResponse:
        clean_type = self._validate_ref_type(changed_ref_type)
        clean_id = str(changed_ref_id or "").strip()
        if not clean_id:
            raise StorageError("SCENE_SNAPSHOT_REF_ID_REQUIRED: changed_ref_id must not be empty.")

        timestamp = now_iso()
        snapshots = self._read_snapshots()
        affected_ids: list[str] = []
        updated_snapshots: list[SceneVersionSnapshot] = []
        for snapshot in snapshots:
            if snapshot.status == "active" and any(
                ref.ref_type == clean_type and ref.ref_id == clean_id
                for ref in snapshot.source_refs
            ):
                affected_ids.append(snapshot.snapshot_id)
                snapshot = self._copy_snapshot(
                    snapshot,
                    status="stale",
                    stale_reason=_short_text(
                        reason
                        or f"{clean_type}:{clean_id} changed and invalidated this snapshot.",
                        MAX_SAFE_METADATA_TEXT_LENGTH,
                    ),
                    updated_at=timestamp,
                )
            updated_snapshots.append(snapshot)

        action = "mark_stale" if affected_ids else "no_action"
        invalidation = SnapshotInvalidationRecord(
            invalidation_id=self._next_invalidation_id(),
            project_id=self._current_project_id(),
            changed_ref_type=clean_type,
            changed_ref_id=clean_id,
            old_version_id=_short_text(old_version_id, MAX_SAFE_METADATA_TEXT_LENGTH),
            new_version_id=_short_text(new_version_id, MAX_SAFE_METADATA_TEXT_LENGTH),
            affected_snapshot_ids=affected_ids,
            affected_candidate_ids=[],
            invalidation_action=action,
            reason=_short_text(reason, MAX_SAFE_METADATA_TEXT_LENGTH),
            created_at=timestamp,
            version_id=SNAPSHOT_INVALIDATION_VERSION_ID,
        )
        payload = {
            "snapshots": [model_to_dict(snapshot) for snapshot in updated_snapshots],
            "invalidation": model_to_dict(invalidation),
        }
        self._guard_safe_payload(payload)
        self._write_snapshots(updated_snapshots)
        invalidations = self._read_invalidations()
        invalidations.append(invalidation)
        self._write_invalidations(invalidations)
        return SnapshotInvalidationResponse(
            success=True,
            invalidation=invalidation,
            stale_snapshot_ids=affected_ids,
        )

    def dependency_graph_summary(
        self,
        chapter_id: str | None = None,
        scene_id: str | None = None,
    ) -> SceneDependencyGraphSummaryResponse:
        clean_chapter_id = str(chapter_id or "").strip()
        clean_scene_id = str(scene_id or "").strip()
        snapshots = self.list_snapshots(scene_id=clean_scene_id or None)
        if clean_chapter_id:
            snapshots = [
                snapshot
                for snapshot in snapshots
                if snapshot.chapter_id == clean_chapter_id
            ]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()
        ref_type_counts: dict[str, int] = {}
        for snapshot in snapshots:
            snapshot_node_id = f"snapshot:{snapshot.snapshot_id}"
            if snapshot_node_id not in seen_nodes:
                nodes.append(
                    {
                        "node_id": snapshot_node_id,
                        "node_type": "scene_version_snapshot",
                        "snapshot_id": snapshot.snapshot_id,
                        "scene_id": snapshot.target_scene_id,
                        "status": snapshot.status,
                        "snapshot_type": snapshot.snapshot_type,
                    }
                )
                seen_nodes.add(snapshot_node_id)
            for ref in snapshot.source_refs:
                ref_node_id = f"{ref.ref_type}:{ref.ref_id}"
                ref_type_counts[ref.ref_type] = ref_type_counts.get(ref.ref_type, 0) + 1
                if ref_node_id not in seen_nodes:
                    nodes.append(
                        {
                            "node_id": ref_node_id,
                            "node_type": ref.ref_type,
                            "ref_id": ref.ref_id,
                            "status": ref.ref_status,
                            "safe_label": ref.safe_label,
                        }
                    )
                    seen_nodes.add(ref_node_id)
                edges.append(
                    {
                        "from": snapshot_node_id,
                        "to": ref_node_id,
                        "role": ref.role,
                    }
                )
        invalidation_ids = [
            item.invalidation_id
            for item in sorted(
                self._read_invalidations(),
                key=lambda record: record.created_at,
                reverse=True,
            )[:5]
        ]
        payload = {
            "nodes": nodes,
            "edges": edges,
            "ref_type_counts": ref_type_counts,
            "latest_invalidation_ids": invalidation_ids,
        }
        safety_issues = self._scan_for_unsafe_payload(payload)
        return SceneDependencyGraphSummaryResponse(
            success=True,
            project_id=self._current_project_id(),
            chapter_id=clean_chapter_id,
            scene_id=clean_scene_id,
            snapshot_count=len(snapshots),
            active_snapshot_count=sum(1 for item in snapshots if item.status == "active"),
            stale_snapshot_count=sum(1 for item in snapshots if item.status == "stale"),
            nodes=nodes,
            edges=edges,
            ref_type_counts=ref_type_counts,
            latest_invalidation_ids=invalidation_ids,
            safety={
                "safe": not safety_issues,
                "issues": safety_issues,
            },
        )

    def debug_summary(self) -> dict[str, Any]:
        snapshots = self._read_snapshots()
        invalidations = self._read_invalidations()
        ref_type_counts: dict[str, int] = {}
        for snapshot in snapshots:
            for ref_type, count in snapshot.source_ref_counts.items():
                ref_type_counts[ref_type] = ref_type_counts.get(ref_type, 0) + int(count)
        recent_snapshots = sorted(
            snapshots,
            key=lambda snapshot: snapshot.created_at,
            reverse=True,
        )[:8]
        latest_invalidations = sorted(
            invalidations,
            key=lambda record: record.created_at,
            reverse=True,
        )[:8]
        payload = {
            "available": True,
            "snapshot_count": len(snapshots),
            "active_count": sum(1 for item in snapshots if item.status == "active"),
            "stale_count": sum(1 for item in snapshots if item.status == "stale"),
            "recent_snapshot_ids": [item.snapshot_id for item in recent_snapshots],
            "stale_snapshot_ids": [
                item.snapshot_id for item in snapshots if item.status == "stale"
            ],
            "latest_invalidation_ids": [
                item.invalidation_id for item in latest_invalidations
            ],
            "ref_type_counts": dict(sorted(ref_type_counts.items())),
            "storage_files": [
                self.snapshots_file.name,
                self.invalidations_file.name,
            ],
            "recent_snapshots": [
                {
                    "snapshot_id": item.snapshot_id,
                    "snapshot_type": item.snapshot_type,
                    "target_scene_id": item.target_scene_id,
                    "chapter_id": item.chapter_id,
                    "status": item.status,
                    "ref_count": len(item.source_refs),
                    "snapshot_hash": item.snapshot_hash,
                    "created_at": item.created_at,
                }
                for item in recent_snapshots
            ],
            "latest_invalidations": [
                {
                    "invalidation_id": item.invalidation_id,
                    "changed_ref_type": item.changed_ref_type,
                    "changed_ref_id": item.changed_ref_id,
                    "invalidation_action": item.invalidation_action,
                    "affected_snapshot_ids": item.affected_snapshot_ids,
                    "created_at": item.created_at,
                }
                for item in latest_invalidations
            ],
        }
        safety_issues = self._scan_for_unsafe_payload(payload)
        payload["safety"] = {
            "safe": not safety_issues,
            "issues": safety_issues,
        }
        return payload

    def _collect_scene_refs(self, scene: dict[str, Any]) -> list[SceneSnapshotRef]:
        scene_id = str(scene.get("scene_id") or "")
        chapter_id = str(scene.get("chapter_id") or "")
        refs: list[SceneSnapshotRef] = [
            self._make_ref(
                "scene",
                scene_id,
                role="subject",
                ref_version_id=str(scene.get("version_id") or ""),
                ref_status=str(scene.get("status") or ""),
                safe_label=f"Scene {scene.get('scene_index') or ''}".strip(),
                chapter_id=chapter_id,
                scene_id=scene_id,
                metadata={
                    "scene_index": _safe_int(scene.get("scene_index")),
                    "content_status": str(scene.get("prose_status") or ""),
                    "is_provisional": bool(scene.get("is_provisional")),
                },
            )
        ]

        refs.extend(
            self._refs_from_ids(
                "event",
                scene.get("event_ids") or [],
                role="direct_source",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.events.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "state_change",
                scene.get("state_change_ids") or [],
                role="direct_source",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.state_changes.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "memory_record",
                scene.get("input_memory_ids") or [],
                role="context_source",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.memory.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "memory_record",
                self._memory_ids_for_scene(scene_id),
                role="direct_source",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.memory.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "chapter_memory_pack",
                [scene.get("chapter_memory_pack_id")],
                role="context_source",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.chapter_memory_packs.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "scene_memory_pack",
                [scene.get("scene_memory_pack_id")],
                role="context_source",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.scene_memory_packs.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "chapter_framework",
                [scene.get("linked_chapter_framework_id")],
                role="guardrail",
                chapter_id=chapter_id,
                scene_id=scene_id,
            )
        )
        refs.extend(
            self._refs_from_ids(
                "framework_package",
                [scene.get("linked_framework_package_id")],
                role="guardrail",
                chapter_id=chapter_id,
                scene_id=scene_id,
                file_lookup=self.data_dir / "framework_package.json",
                version_key="version_id",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "character_state",
                scene.get("linked_character_ids") or [],
                role="context_source",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.characters.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "relationship_state",
                scene.get("linked_relationship_ids") or [],
                role="context_source",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.relationships.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "narrative_intent",
                scene.get("narrative_intent_ids")
                or (scene.get("generation_trace") or {}).get("narrative_intent_ids")
                or [],
                role="audit_ref",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.narrative_intent_records.get_by_id,
                version_key="version_id",
                status_key="status",
            )
        )
        refs.extend(
            self._refs_from_ids(
                "quality_report",
                [scene.get("quality_report_id")],
                role="audit_ref",
                chapter_id=chapter_id,
                scene_id=scene_id,
                repository_getter=self.repositories.quality_reports.get_by_id,
                version_key="version_id",
            )
        )
        refs.extend(self._decision_refs_for_scene(scene_id, chapter_id))
        refs.extend(self._narrative_refs_for_scene(scene_id, chapter_id))
        return refs

    def _decision_refs_for_scene(
        self,
        scene_id: str,
        chapter_id: str,
    ) -> list[SceneSnapshotRef]:
        refs = []
        for decision in self.repositories.decisions.list_all():
            if (
                str(decision.get("target_type") or "") == "scene"
                and str(decision.get("target_id") or "") == scene_id
            ):
                refs.append(
                    self._make_ref(
                        "decision",
                        str(decision.get("decision_id") or ""),
                        role="audit_ref",
                        ref_status=str(decision.get("decision_type") or ""),
                        safe_label="Scene decision",
                        chapter_id=chapter_id,
                        scene_id=scene_id,
                    )
                )
        return refs

    def _narrative_refs_for_scene(
        self,
        scene_id: str,
        chapter_id: str,
    ) -> list[SceneSnapshotRef]:
        lookup = [
            (
                "claim_record",
                self.repositories.claim_records.list_all(),
                "claim_id",
            ),
            (
                "character_psychology_trace",
                self.repositories.character_psychology_traces.list_all(),
                "psychology_trace_id",
            ),
            (
                "character_expression_record",
                self.repositories.character_expression_records.list_all(),
                "expression_record_id",
            ),
            (
                "perception_state",
                self.repositories.perception_state_records.list_all(),
                "perception_state_id",
            ),
            (
                "apparent_contradiction",
                self.repositories.apparent_contradiction_records.list_all(),
                "apparent_contradiction_id",
            ),
            (
                "narrative_debt",
                self.repositories.narrative_debts.list_all(),
                "narrative_debt_id",
            ),
        ]
        refs: list[SceneSnapshotRef] = []
        for ref_type, records, id_field in lookup:
            for record in records:
                if str(record.get("scene_id") or record.get("source_scene_id") or "") != scene_id:
                    continue
                refs.append(
                    self._make_ref(
                        ref_type,
                        str(record.get(id_field) or ""),
                        role="audit_ref",
                        ref_version_id=str(record.get("version_id") or ""),
                        ref_status=str(record.get("status") or ""),
                        safe_label=ref_type,
                        chapter_id=chapter_id,
                        scene_id=scene_id,
                    )
                )
        return refs

    def _memory_ids_for_scene(self, scene_id: str) -> list[str]:
        ids = []
        for memory in self.repositories.memory.list_all():
            if str(memory.get("scene_id") or "") == scene_id:
                ids.append(str(memory.get("memory_id") or ""))
        return _unique_strings(ids)

    def _refs_from_ids(
        self,
        ref_type: str,
        ref_ids: list[Any],
        *,
        role: str,
        chapter_id: str,
        scene_id: str,
        repository_getter: Any | None = None,
        file_lookup: Path | None = None,
        version_key: str = "version_id",
        status_key: str = "status",
    ) -> list[SceneSnapshotRef]:
        refs: list[SceneSnapshotRef] = []
        for raw_id in _unique_strings(ref_ids):
            record = repository_getter(raw_id) if repository_getter else None
            if record is None and file_lookup and self.store.exists(file_lookup):
                data = self.store.read(file_lookup)
                if str(data.get(f"{ref_type}_id") or data.get("framework_package_id") or "") == raw_id:
                    record = data
            refs.append(
                self._make_ref(
                    ref_type,
                    raw_id,
                    role=role,
                    ref_version_id=str((record or {}).get(version_key) or ""),
                    ref_status=str((record or {}).get(status_key) or ""),
                    safe_label=self._safe_label_for_ref(ref_type, raw_id, record),
                    chapter_id=chapter_id,
                    scene_id=scene_id,
                    metadata=self._safe_metadata_for_record(record or {}),
                )
            )
        return refs

    def _make_ref(
        self,
        ref_type: str,
        ref_id: str,
        *,
        role: str,
        ref_version_id: str = "",
        ref_status: str = "",
        safe_label: str = "",
        chapter_id: str = "",
        scene_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SceneSnapshotRef:
        return SceneSnapshotRef(
            ref_type=ref_type,
            ref_id=str(ref_id or "").strip(),
            ref_version_id=_short_text(ref_version_id, MAX_SAFE_METADATA_TEXT_LENGTH),
            ref_status=_short_text(ref_status, MAX_SAFE_METADATA_TEXT_LENGTH),
            role=role,
            safe_label=_short_text(safe_label or ref_id, MAX_SAFE_LABEL_LENGTH),
            chapter_id=chapter_id,
            scene_id=scene_id,
            metadata=metadata or {},
        )

    def _safe_scene_summary(
        self,
        scene: dict[str, Any],
        refs: list[SceneSnapshotRef],
    ) -> dict[str, Any]:
        return {
            "scene_id": str(scene.get("scene_id") or ""),
            "chapter_id": str(scene.get("chapter_id") or ""),
            "scene_index": _safe_int(scene.get("scene_index")),
            "status": str(scene.get("status") or ""),
            "content_status": str(scene.get("prose_status") or ""),
            "is_provisional": bool(scene.get("is_provisional")),
            "goal_summary": _short_text(
                scene.get("goal") or _scene_goal_text(scene.get("scene_goal")),
                260,
            ),
            "synopsis_summary": _short_text(scene.get("synopsis"), 320),
            "location": _short_text(scene.get("location"), MAX_SAFE_METADATA_TEXT_LENGTH),
            "quality": {
                "passed": bool((scene.get("quality_report") or {}).get("passed")),
                "warning_count": len((scene.get("quality_report") or {}).get("warnings") or []),
                "blocking_count": len(
                    (scene.get("quality_report") or {}).get("blocking_issues") or []
                ),
                "requires_user_confirmation": bool(
                    (scene.get("quality_report") or {}).get("requires_user_confirmation")
                ),
            },
            "ref_count": len(refs),
            "ref_type_counts": self._ref_counts(refs),
        }

    def _safe_label_for_ref(
        self,
        ref_type: str,
        ref_id: str,
        record: dict[str, Any] | None,
    ) -> str:
        if not record:
            return f"{ref_type}:{ref_id}"
        for key in [
            "name",
            "title",
            "status",
            "memory_type",
            "decision_type",
            "target_type",
            "category",
        ]:
            value = str(record.get(key) or "").strip()
            if value:
                return f"{ref_type}:{value}"
        return f"{ref_type}:{ref_id}"

    def _safe_metadata_for_record(self, record: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if not record:
            return metadata
        for key in SAFE_ID_FIELDS:
            value = record.get(key)
            if value:
                metadata[key] = _short_text(value, MAX_SAFE_METADATA_TEXT_LENGTH)
        for key in ["chapter_id", "scene_id", "status", "truth_status", "source_object_type"]:
            value = record.get(key)
            if value:
                metadata[key] = _short_text(value, MAX_SAFE_METADATA_TEXT_LENGTH)
        for key in ["character_ids", "relationship_ids", "event_ids", "source_memory_ids"]:
            values = _unique_strings(record.get(key) or [])
            if values:
                metadata[f"{key}_count"] = len(values)
                metadata[f"{key}_sample"] = values[:5]
        return metadata

    def _normalize_extra_refs(
        self,
        extra_refs: list[SceneSnapshotRef | dict[str, Any]],
    ) -> list[SceneSnapshotRef]:
        refs = []
        for item in extra_refs:
            ref = item if isinstance(item, SceneSnapshotRef) else SceneSnapshotRef(**item)
            refs.append(ref)
        return refs

    def _dedupe_refs(self, refs: list[SceneSnapshotRef]) -> list[SceneSnapshotRef]:
        result: list[SceneSnapshotRef] = []
        seen: set[tuple[str, str, str]] = set()
        for ref in refs:
            if not ref.ref_id:
                continue
            key = (ref.ref_type, ref.ref_id, ref.role)
            if key in seen:
                continue
            seen.add(key)
            result.append(ref)
        return result

    def _ref_counts(self, refs: list[SceneSnapshotRef]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ref in refs:
            counts[ref.ref_type] = counts.get(ref.ref_type, 0) + 1
        return dict(sorted(counts.items()))

    def _snapshot_hash(self, payload: dict[str, Any]) -> str:
        hash_payload = {
            "project_id": payload.get("project_id"),
            "snapshot_type": payload.get("snapshot_type"),
            "subject_type": payload.get("subject_type"),
            "subject_id": payload.get("subject_id"),
            "subject_version_id": payload.get("subject_version_id"),
            "subject_status": payload.get("subject_status"),
            "target_scene_id": payload.get("target_scene_id"),
            "chapter_id": payload.get("chapter_id"),
            "chapter_index": payload.get("chapter_index"),
            "source_refs": [
                {
                    "ref_type": ref.get("ref_type"),
                    "ref_id": ref.get("ref_id"),
                    "ref_version_id": ref.get("ref_version_id"),
                    "ref_status": ref.get("ref_status"),
                    "role": ref.get("role"),
                    "chapter_id": ref.get("chapter_id"),
                    "scene_id": ref.get("scene_id"),
                }
                for ref in payload.get("source_refs", [])
            ],
            "source_ref_counts": payload.get("source_ref_counts"),
            "safe_summary": payload.get("safe_summary"),
            "status": payload.get("status"),
            "stale_reason": payload.get("stale_reason"),
            "version_id": payload.get("version_id"),
        }
        encoded = json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _read_snapshots(self) -> list[SceneVersionSnapshot]:
        if not self.store.exists(self.snapshots_file):
            return []
        raw_items = self.store.read_list(self.snapshots_file)
        result: list[SceneVersionSnapshot] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                result.append(SceneVersionSnapshot(**item))
            except ValidationError as exc:
                raise StorageError(
                    f"JSON schema is invalid: {self.snapshots_file}"
                ) from exc
        return result

    def _write_snapshots(self, snapshots: list[SceneVersionSnapshot]) -> None:
        payload = [model_to_dict(snapshot) for snapshot in snapshots]
        self._guard_safe_payload(payload)
        self.store.write(self.snapshots_file, payload)

    def _read_invalidations(self) -> list[SnapshotInvalidationRecord]:
        if not self.store.exists(self.invalidations_file):
            return []
        raw_items = self.store.read_list(self.invalidations_file)
        result: list[SnapshotInvalidationRecord] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                result.append(SnapshotInvalidationRecord(**item))
            except ValidationError as exc:
                raise StorageError(
                    f"JSON schema is invalid: {self.invalidations_file}"
                ) from exc
        return result

    def _write_invalidations(
        self,
        records: list[SnapshotInvalidationRecord],
    ) -> None:
        payload = [model_to_dict(record) for record in records]
        self._guard_safe_payload(payload)
        self.store.write(self.invalidations_file, payload)

    def _next_snapshot_id(self) -> str:
        return f"scene_snapshot_{len(self._read_snapshots()) + 1:03d}"

    def _next_invalidation_id(self) -> str:
        return f"snapshot_invalidation_{len(self._read_invalidations()) + 1:03d}"

    def _validate_ref_type(self, ref_type: str) -> str:
        clean_type = str(ref_type or "").strip()
        if clean_type not in ALLOWED_SCENE_SNAPSHOT_REF_TYPES:
            raise StorageError(
                "SCENE_SNAPSHOT_REF_TYPE_INVALID: ref_type is not supported."
            )
        return clean_type

    def _copy_snapshot(self, snapshot: SceneVersionSnapshot, **updates: Any) -> SceneVersionSnapshot:
        if hasattr(snapshot, "model_dump"):
            payload = snapshot.model_dump(mode="json")
        else:
            payload = snapshot.dict()
        payload.update(updates)
        payload["snapshot_hash"] = self._snapshot_hash(payload)
        return SceneVersionSnapshot(**payload)

    def _guard_safe_payload(self, payload: Any) -> None:
        issues = self._scan_for_unsafe_payload(payload)
        if issues:
            raise StorageError(
                "SCENE_SNAPSHOT_UNSAFE_PAYLOAD_BLOCKED: "
                + "; ".join(issues[:5])
            )

    def _scan_for_unsafe_payload(self, value: Any, path: str = "$") -> list[str]:
        issues: list[str] = []
        if isinstance(value, BaseModel):
            value = model_to_dict(value)
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                key_lower = key_text.casefold()
                if key_lower in UNSAFE_KEY_NAMES:
                    issues.append(f"unsafe_key:{path}.{key_text}")
                    continue
                issues.extend(
                    self._scan_for_unsafe_payload(item, f"{path}.{key_text}")
                )
            return issues
        if isinstance(value, list):
            for index, item in enumerate(value):
                issues.extend(self._scan_for_unsafe_payload(item, f"{path}[{index}]"))
            return issues
        if isinstance(value, str):
            text = value.strip()
            lower = text.casefold()
            for marker in UNSAFE_VALUE_MARKERS:
                if marker in lower:
                    issues.append(f"unsafe_value:{path}")
                    break
            if any(pattern.search(text) for pattern in SECRET_LIKE_PATTERNS):
                issues.append(f"secret_like_value:{path}")
            if len(text) > MAX_SAFE_TEXT_LENGTH:
                issues.append(f"long_text:{path}")
            return issues
        return issues


def _short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, list) else [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _scene_goal_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ["goal", "summary", "scene_goal", "description"]:
            if value.get(key):
                return str(value.get(key))
    return str(value or "")
