from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.background_thinking import ThinkingCandidate
from app.backend.models.modification_impact import AffectedObjectRef, ModificationImpactPreview
from app.backend.models.pre_modify import (
    PRE_MODIFY_EXECUTION_STRATEGIES,
    PreModifyAdjustmentItem,
    PreModifyAdjustmentPlan,
    PreModifyCandidate,
    PreModifyFromPreviewRequest,
    PreModifyImpactReason,
    PreModifyPipelineResult,
    PreModifySummaryResponse,
)
from app.backend.models.scene import Scene
from app.backend.models.scene_snapshot import SceneVersionSnapshot
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.background_thinking_service import BackgroundThinkingService
from app.backend.services.background_budget_service import BackgroundBudgetService
from app.backend.services.modification_impact_service import ModificationImpactService
from app.backend.services.scene_version_snapshot_service import SceneVersionSnapshotService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
MAX_SAFE_TEXT_LENGTH = 700
MAX_SAFE_LABEL_LENGTH = 260
MAX_LIST_ITEMS = 10
CANDIDATES_FILE_NAME = "pre_modify_candidates.json"
PLANS_FILE_NAME = "pre_modify_adjustment_plans.json"
REASONS_FILE_NAME = "pre_modify_impact_reasons.json"
STALE_OR_SUPERSEDED = {"stale", "superseded"}
CONFIRMED_SCENE_STATUSES = {"confirmed", "committed"}
FUTURE_SCENE_RELATIONS = {"dependent_later_scene", "dry_run_dependent_scene"}
SOURCE_REF_TYPE_BY_OBJECT_TYPE = {
    "confirmed_scene": "scene",
    "scene_draft": "scene",
    "revision_candidate": "scene_revision",
    "chapter_archive": "chapter_archive",
    "scene": "scene",
    "memory_record": "memory_record",
    "chapter_memory_pack": "chapter_memory_pack",
    "scene_memory_pack": "scene_memory_pack",
    "chapter_archive": "chapter_archive",
    "narrative_layer": "narrative_debt",
    "story_progress": "story_progress",
    "framework_package": "framework_package",
}
SOURCE_AFFECTED_REF_KEYS = (
    "object_type",
    "object_id",
    "chapter_id",
    "scene_id",
    "status",
    "impact_area",
    "impact_level",
    "relation",
    "reason",
    "summary",
    "ref_ids",
)
UNSAFE_KEY_NAMES = {
    "prompt",
    "messages",
    "raw_prompt",
    "raw_response",
    "raw_text",
    "hidden_reasoning",
    "internal_reasoning",
    "chain_of_thought",
    "chain-of-thought",
    "cot",
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "api_key",
    "api_key_ref",
    "authorization",
    "secret_key",
    "secret_token",
    "bearer_token",
}
UNSAFE_VALUE_MARKERS = {
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "prose_text",
    "prose text",
    "revised_prose_text",
    "revised prose text",
    "full_prose",
    "bearer ",
}
SECRET_LIKE_PATTERNS = [
    re.compile(r"(?i)(?:^|[^a-z0-9])sk-[a-z0-9][a-z0-9_\-]{8,}"),
    re.compile(r"(?i)(?:^|[^a-z0-9])lsv2_[a-z0-9][a-z0-9_\-]{8,}"),
    re.compile(
        r"(?i)(?:api[_\-\s]?key|secret[_\-\s]?(?:key|token)|authorization)\s*[:=]\s*[a-z0-9_\-]{8,}"
    ),
]


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


class PreModifyPipelineService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        modification_impact_service: ModificationImpactService | None = None,
        snapshot_service: SceneVersionSnapshotService | None = None,
        background_thinking_service: BackgroundThinkingService | None = None,
        background_budget_service: BackgroundBudgetService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.modification_impact_service = (
            modification_impact_service
            or ModificationImpactService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.snapshot_service = snapshot_service or SceneVersionSnapshotService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.background_thinking_service = (
            background_thinking_service
            or BackgroundThinkingService(
                store=self.store,
                data_dir=self.data_dir,
                snapshot_service=self.snapshot_service,
            )
        )
        self.background_budget_service = background_budget_service or BackgroundBudgetService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.candidates_file = self.data_dir / CANDIDATES_FILE_NAME
        self.plans_file = self.data_dir / PLANS_FILE_NAME
        self.reasons_file = self.data_dir / REASONS_FILE_NAME

    def create_candidates_from_preview(
        self,
        request: PreModifyFromPreviewRequest | dict[str, Any],
    ) -> PreModifyPipelineResult:
        normalized = (
            request
            if isinstance(request, PreModifyFromPreviewRequest)
            else PreModifyFromPreviewRequest(**request)
        )
        self._validate_request(normalized)
        preview = self._get_preview(normalized.preview_id)
        budget_response = self.background_budget_service.evaluate_task_execution(
            task_type="pre_modify_candidate",
            task_id=preview.preview_id,
            requested_profile_id="background_low",
            requested_execution_strategy="deterministic_fallback",
            snapshot_ids=[],
            source_object_type="modification_impact_preview",
            source_object_id=preview.preview_id,
        )
        budget_decision = budget_response.decision
        if not budget_decision.allowed or budget_decision.selected_execution_strategy == "blocked":
            result = PreModifyPipelineResult(
                source_preview_id=preview.preview_id,
                no_candidate_reason="BUDGET_BLOCKED",
                warnings=["PRE_MODIFY_BUDGET_BLOCKED"],
            )
            result.safety = self._safety(model_to_dict(result))
            self._guard_safe_payload(result)
            self.background_budget_service.record_task_usage(
                task_type="pre_modify_candidate",
                task_id=preview.preview_id,
                source_object_type="modification_impact_preview",
                source_object_id=preview.preview_id,
                decision=budget_decision,
                blocked=True,
                deterministic_used=True,
                status="blocked",
            )
            return result
        targets, skipped, warnings = self._select_target_scenes(preview, normalized)
        if not targets:
            result = PreModifyPipelineResult(
                source_preview_id=preview.preview_id,
                skipped_target_scene_ids=skipped,
                no_candidate_reason="NO_AFFECTED_FUTURE_SCENE",
                warnings=warnings,
            )
            result.safety = self._safety(model_to_dict(result))
            self._guard_safe_payload(result)
            self.background_budget_service.record_task_usage(
                task_type="pre_modify_candidate",
                task_id=preview.preview_id,
                source_object_type="modification_impact_preview",
                source_object_id=preview.preview_id,
                decision=budget_decision,
                deterministic_used=True,
                status="recorded",
            )
            return result

        candidates = self._read_candidates()
        plans = self._read_plans()
        reasons = self._read_reasons()
        created_candidate_ids: list[str] = []
        created_plan_ids: list[str] = []
        created_reason_ids: list[str] = []

        for target in targets:
            target_scene = target["scene"]
            existing = self._find_existing_candidate(candidates, preview, target_scene.scene_id)
            if existing:
                created_candidate_ids.append(existing.candidate_id)
                if existing.adjustment_plan_id:
                    created_plan_ids.append(existing.adjustment_plan_id)
                if existing.impact_reason_id:
                    created_reason_ids.append(existing.impact_reason_id)
                continue

            artifacts = self._build_artifacts_for_target(
                preview,
                target_scene,
                target["source_refs"],
                candidate_id=f"pre_modify_candidate_{len(candidates) + 1:03d}",
                plan_id=f"pre_modify_adjustment_plan_{len(plans) + 1:03d}",
                reason_id=f"pre_modify_impact_reason_{len(reasons) + 1:03d}",
            )
            candidates.append(artifacts["candidate"])
            plans.append(artifacts["plan"])
            reasons.append(artifacts["reason"])
            created_candidate_ids.append(artifacts["candidate"].candidate_id)
            created_plan_ids.append(artifacts["plan"].plan_id)
            created_reason_ids.append(artifacts["reason"].reason_id)

        self._write_all(candidates, plans, reasons)
        result = PreModifyPipelineResult(
            source_preview_id=preview.preview_id,
            created_candidate_ids=_unique_strings(created_candidate_ids),
            created_plan_ids=_unique_strings(created_plan_ids),
            created_reason_ids=_unique_strings(created_reason_ids),
            skipped_target_scene_ids=_unique_strings(skipped),
            warnings=_unique_strings(warnings),
        )
        result.safety = self._safety(model_to_dict(result))
        self._guard_safe_payload(result)
        self.background_budget_service.record_task_usage(
            task_type="pre_modify_candidate",
            task_id=preview.preview_id,
            source_object_type="modification_impact_preview",
            source_object_id=preview.preview_id,
            decision=budget_decision,
            deterministic_used=True,
            status="completed",
        )
        return result

    def get_candidate(self, candidate_id: str) -> PreModifyCandidate:
        clean_id = str(candidate_id or "").strip()
        for candidate in self._read_candidates():
            if candidate.candidate_id == clean_id:
                return candidate
        raise StorageError("PRE_MODIFY_CANDIDATE_NOT_FOUND: Candidate does not exist.")

    def list_candidates(
        self,
        status: str | None = None,
        source_preview_id: str | None = None,
        target_scene_id: str | None = None,
        limit: int = 50,
    ) -> list[PreModifyCandidate]:
        clean_status = str(status or "").strip()
        clean_preview_id = str(source_preview_id or "").strip()
        clean_scene_id = str(target_scene_id or "").strip()
        candidates = self._read_candidates()
        if clean_status:
            candidates = [item for item in candidates if item.status == clean_status]
        if clean_preview_id:
            candidates = [
                item for item in candidates if item.source_preview_id == clean_preview_id
            ]
        if clean_scene_id:
            candidates = [
                item for item in candidates if item.target_scene_id == clean_scene_id
            ]
        return sorted(candidates, key=lambda item: item.updated_at, reverse=True)[
            : max(1, limit)
        ]

    def get_adjustment_plan(self, plan_id: str) -> PreModifyAdjustmentPlan:
        clean_id = str(plan_id or "").strip()
        for plan in self._read_plans():
            if plan.plan_id == clean_id:
                return plan
        raise StorageError("PRE_MODIFY_PLAN_NOT_FOUND: Adjustment plan does not exist.")

    def get_impact_reason(self, reason_id: str) -> PreModifyImpactReason:
        clean_id = str(reason_id or "").strip()
        for reason in self._read_reasons():
            if reason.reason_id == clean_id:
                return reason
        raise StorageError("PRE_MODIFY_REASON_NOT_FOUND: Impact reason does not exist.")

    def summary(
        self,
        source_preview_id: str | None = None,
        target_scene_id: str | None = None,
    ) -> PreModifySummaryResponse:
        candidates = self.list_candidates(
            source_preview_id=source_preview_id,
            target_scene_id=target_scene_id,
            limit=500,
        )
        plans = self._read_plans()
        reasons = self._read_reasons()
        if source_preview_id:
            plans = [item for item in plans if item.source_preview_id == source_preview_id]
            reasons = [item for item in reasons if item.source_preview_id == source_preview_id]
        if target_scene_id:
            plans = [item for item in plans if item.target_scene_id == target_scene_id]
            reasons = [item for item in reasons if item.target_scene_id == target_scene_id]
        latest_warnings: list[str] = []
        for candidate in candidates[:8]:
            latest_warnings.extend(candidate.risk_warnings[:3])
        response = PreModifySummaryResponse(
            source_preview_id=str(source_preview_id or ""),
            target_scene_id=str(target_scene_id or ""),
            candidate_count=len(candidates),
            ready_count=sum(1 for item in candidates if item.status == "ready"),
            blocked_count=sum(1 for item in candidates if item.status == "blocked"),
            stale_count=sum(1 for item in candidates if item.status == "stale"),
            superseded_count=sum(1 for item in candidates if item.status == "superseded"),
            warning_only_count=sum(1 for item in candidates if item.status == "warning_only"),
            plan_count=len(plans),
            reason_count=len(reasons),
            recent_candidate_ids=[item.candidate_id for item in candidates[:8]],
            recent_source_preview_ids=_unique_strings(
                [item.source_preview_id for item in candidates[:8]]
            ),
            recent_target_scene_ids=_unique_strings(
                [item.target_scene_id for item in candidates[:8]]
            ),
            latest_warnings=_unique_strings(latest_warnings)[:MAX_LIST_ITEMS],
            recent_candidates=[
                {
                    "candidate_id": item.candidate_id,
                    "status": item.status,
                    "target_scene_id": item.target_scene_id,
                    "source_preview_id": item.source_preview_id,
                    "user_visible_reason": _short_text(
                        item.user_visible_reason,
                        MAX_SAFE_LABEL_LENGTH,
                    ),
                    "adjustment_summary": _short_text(
                        item.adjustment_summary,
                        MAX_SAFE_LABEL_LENGTH,
                    ),
                    "affected_snapshot_ids": item.affected_snapshot_ids[:MAX_LIST_ITEMS],
                    "thinking_candidate_ids": item.thinking_candidate_ids[:MAX_LIST_ITEMS],
                    "risk_warnings": item.risk_warnings[:MAX_LIST_ITEMS],
                }
                for item in candidates[:8]
            ],
        )
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def debug_summary(self) -> dict[str, Any]:
        summary = self.summary()
        payload = {
            "available": True,
            "candidate_count": summary.candidate_count,
            "ready_count": summary.ready_count,
            "blocked_count": summary.blocked_count,
            "stale_count": summary.stale_count,
            "superseded_count": summary.superseded_count,
            "warning_only_count": summary.warning_only_count,
            "plan_count": summary.plan_count,
            "reason_count": summary.reason_count,
            "recent_candidate_ids": summary.recent_candidate_ids,
            "recent_source_preview_ids": summary.recent_source_preview_ids,
            "recent_target_scene_ids": summary.recent_target_scene_ids,
            "latest_warnings": summary.latest_warnings,
            "recent_candidates": summary.recent_candidates,
            "storage_files": [
                CANDIDATES_FILE_NAME,
                PLANS_FILE_NAME,
                REASONS_FILE_NAME,
            ],
            "safety": summary.safety,
        }
        self._guard_safe_payload(payload)
        return payload

    def _validate_request(self, request: PreModifyFromPreviewRequest) -> None:
        if not str(request.preview_id or "").strip():
            raise StorageError("PRE_MODIFY_VALIDATION_ERROR: preview_id is required.")
        if request.execution_strategy not in PRE_MODIFY_EXECUTION_STRATEGIES:
            raise StorageError(
                "PRE_MODIFY_VALIDATION_ERROR: execution_strategy is not supported in M3."
            )

    def _get_preview(self, preview_id: str) -> ModificationImpactPreview:
        try:
            return self.modification_impact_service.get_preview(preview_id)
        except StorageError as exc:
            if str(exc).startswith("MODIFICATION_IMPACT_PREVIEW_MISSING"):
                raise StorageError("PRE_MODIFY_PREVIEW_NOT_FOUND: Preview does not exist.") from exc
            raise

    def _select_target_scenes(
        self,
        preview: ModificationImpactPreview,
        request: PreModifyFromPreviewRequest,
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        requested = set(_unique_strings(request.target_scene_ids))
        source_scene = self._find_scene(preview.source_object_id)
        targets_by_id: dict[str, dict[str, Any]] = {}
        skipped: list[str] = []
        warnings: list[str] = []

        for ref in preview.affected_objects:
            target_scene_id = str(ref.scene_id or ref.object_id or "").strip()
            if not target_scene_id:
                continue
            if requested and target_scene_id not in requested:
                continue
            if ref.object_type != "scene":
                continue
            if self._is_source_or_current_ref(ref, preview) and not request.include_current_scene:
                skipped.append(target_scene_id)
                continue
            if not self._is_future_scene_ref(ref):
                skipped.append(target_scene_id)
                continue
            target_scene = self._find_scene(target_scene_id)
            if target_scene is None:
                skipped.append(target_scene_id)
                warnings.append(f"TARGET_SCENE_NOT_FOUND:{target_scene_id}")
                continue
            if not self._is_later_scene(source_scene, target_scene):
                skipped.append(target_scene_id)
                continue
            if (
                target_scene.status in CONFIRMED_SCENE_STATUSES
                and not request.include_confirmed_targets
            ):
                skipped.append(target_scene_id)
                continue
            item = targets_by_id.setdefault(
                target_scene_id,
                {"scene": target_scene, "source_refs": []},
            )
            item["source_refs"].append(ref)

        return list(targets_by_id.values()), _unique_strings(skipped), _unique_strings(warnings)

    def _build_artifacts_for_target(
        self,
        preview: ModificationImpactPreview,
        target_scene: Scene,
        source_refs: list[AffectedObjectRef],
        *,
        candidate_id: str,
        plan_id: str,
        reason_id: str,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        target_snapshots = self.snapshot_service.list_snapshots(
            scene_id=target_scene.scene_id,
        )
        affected_snapshots = self._affected_snapshots(preview, source_refs, target_snapshots)
        related_thinking = self._related_thinking_candidates(preview, target_scene)
        target_snapshot_ids = [snapshot.snapshot_id for snapshot in target_snapshots]
        affected_snapshot_ids = _unique_strings(
            [snapshot.snapshot_id for snapshot in affected_snapshots]
        )
        thinking_candidate_ids = [candidate.candidate_id for candidate in related_thinking]
        risk_warnings = self._risk_warnings(target_scene, target_snapshots, related_thinking)
        candidate_status = "blocked" if target_scene.status in CONFIRMED_SCENE_STATUSES else "ready"
        if candidate_status == "ready" and risk_warnings:
            candidate_status = "warning_only"
        plan_status = "blocked" if candidate_status == "blocked" else "proposed"
        user_visible_reason = self._user_visible_reason(
            preview,
            target_scene,
            source_refs,
            related_thinking,
        )
        adjustment_summary = self._adjustment_summary(
            preview,
            target_scene,
            target_snapshots,
            related_thinking,
        )
        safe_summary = self._safe_candidate_summary(
            preview,
            target_scene,
            target_snapshots,
            related_thinking,
        )
        evidence_refs = self._evidence_refs(
            preview,
            source_refs,
            target_snapshots,
            affected_snapshots,
            related_thinking,
        )
        plan = PreModifyAdjustmentPlan(
            plan_id=plan_id,
            candidate_id=candidate_id,
            source_preview_id=preview.preview_id,
            target_scene_id=target_scene.scene_id,
            status=plan_status,
            safe_summary=safe_summary,
            items=self._adjustment_items(
                target_scene,
                target_snapshots,
                related_thinking,
                risk_warnings,
                evidence_refs,
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )
        reason = PreModifyImpactReason(
            reason_id=reason_id,
            candidate_id=candidate_id,
            source_preview_id=preview.preview_id,
            target_scene_id=target_scene.scene_id,
            impact_level=self._max_impact_level(source_refs),
            relation=self._relation_summary(source_refs),
            user_visible_reason=user_visible_reason,
            evidence_refs=evidence_refs,
            affected_snapshot_ids=affected_snapshot_ids,
            thinking_candidate_ids=thinking_candidate_ids,
            created_at=timestamp,
        )
        candidate = PreModifyCandidate(
            candidate_id=candidate_id,
            source_preview_id=preview.preview_id,
            source_object_type=preview.source_object_type,
            source_object_id=preview.source_object_id,
            source_modification_hash=preview.modification_hash,
            target_scene_id=target_scene.scene_id,
            target_chapter_id=target_scene.chapter_id,
            target_scene_index=target_scene.scene_index,
            target_scene_status=target_scene.status,
            target_snapshot_ids=target_snapshot_ids,
            affected_snapshot_ids=affected_snapshot_ids,
            thinking_candidate_ids=thinking_candidate_ids,
            adjustment_plan_id=plan_id,
            impact_reason_id=reason_id,
            status=candidate_status,
            safe_summary=safe_summary,
            user_visible_reason=user_visible_reason,
            adjustment_summary=adjustment_summary,
            source_affected_refs=[
                self._safe_affected_ref(ref) for ref in source_refs[:MAX_LIST_ITEMS]
            ],
            risk_warnings=risk_warnings,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._guard_safe_payload({"candidate": candidate, "plan": plan, "reason": reason})
        return {"candidate": candidate, "plan": plan, "reason": reason}

    def _find_existing_candidate(
        self,
        candidates: list[PreModifyCandidate],
        preview: ModificationImpactPreview,
        target_scene_id: str,
    ) -> PreModifyCandidate | None:
        for candidate in candidates:
            if candidate.status in STALE_OR_SUPERSEDED:
                continue
            if candidate.source_preview_id != preview.preview_id:
                continue
            if candidate.target_scene_id != target_scene_id:
                continue
            if candidate.source_modification_hash != preview.modification_hash:
                continue
            return candidate
        return None

    def _affected_snapshots(
        self,
        preview: ModificationImpactPreview,
        source_refs: list[AffectedObjectRef],
        target_snapshots: list[SceneVersionSnapshot],
    ) -> list[SceneVersionSnapshot]:
        snapshots_by_id = {snapshot.snapshot_id: snapshot for snapshot in target_snapshots}
        lookup_refs = [
            {
                "ref_type": SOURCE_REF_TYPE_BY_OBJECT_TYPE.get(preview.source_object_type, ""),
                "ref_id": preview.source_object_id,
            }
        ]
        for ref in source_refs:
            lookup_refs.append(
                {
                    "ref_type": SOURCE_REF_TYPE_BY_OBJECT_TYPE.get(ref.object_type, ref.object_type),
                    "ref_id": ref.object_id,
                }
            )
            for ref_id in ref.ref_ids:
                lookup_refs.append(
                    {
                        "ref_type": SOURCE_REF_TYPE_BY_OBJECT_TYPE.get(ref.object_type, ref.object_type),
                        "ref_id": ref_id,
                    }
                )
        for lookup in lookup_refs:
            ref_type = str(lookup.get("ref_type") or "").strip()
            ref_id = str(lookup.get("ref_id") or "").strip()
            if not ref_type or not ref_id:
                continue
            try:
                for snapshot in self.snapshot_service.list_snapshots_using_ref(
                    ref_type=ref_type,
                    ref_id=ref_id,
                ):
                    snapshots_by_id[snapshot.snapshot_id] = snapshot
            except (StorageError, ValueError):
                continue
        return list(snapshots_by_id.values())

    def _related_thinking_candidates(
        self,
        preview: ModificationImpactPreview,
        target_scene: Scene,
    ) -> list[ThinkingCandidate]:
        related: list[ThinkingCandidate] = []
        for candidate in self.background_thinking_service.list_candidates(
            status="ready",
            limit=500,
        ):
            if candidate.target_scene_id == target_scene.scene_id:
                related.append(candidate)
                continue
            if candidate.target_scene_index == target_scene.scene_index:
                related.append(candidate)
                continue
            if candidate.source_scene_id == preview.source_object_id:
                related.append(candidate)
        deduped: list[ThinkingCandidate] = []
        seen: set[str] = set()
        for candidate in related:
            if candidate.candidate_id in seen:
                continue
            seen.add(candidate.candidate_id)
            deduped.append(candidate)
        return deduped[:MAX_LIST_ITEMS]

    def _adjustment_items(
        self,
        target_scene: Scene,
        target_snapshots: list[SceneVersionSnapshot],
        thinking_candidates: list[ThinkingCandidate],
        risk_warnings: list[str],
        evidence_refs: list[dict[str, Any]],
    ) -> list[PreModifyAdjustmentItem]:
        snapshot_ids = [snapshot.snapshot_id for snapshot in target_snapshots]
        thinking_ids = [candidate.candidate_id for candidate in thinking_candidates]
        items = [
            PreModifyAdjustmentItem(
                item_id="pre_modify_adjustment_item_001",
                item_type="scene_focus",
                priority="high",
                target_field="scene_goal",
                proposed_change_summary=_short_text(
                    f"Review {target_scene.scene_id} focus against the source preview before future drafting.",
                    MAX_SAFE_LABEL_LENGTH,
                ),
                evidence_refs=evidence_refs[:MAX_LIST_ITEMS],
                source_snapshot_ids=snapshot_ids[:MAX_LIST_ITEMS],
                thinking_candidate_ids=thinking_ids[:MAX_LIST_ITEMS],
            ),
            PreModifyAdjustmentItem(
                item_id="pre_modify_adjustment_item_002",
                item_type="continuity_alignment",
                priority="medium",
                target_field="continuity_refs",
                proposed_change_summary="Re-check target snapshot refs and source affected refs before drafting or revising this scene.",
                evidence_refs=evidence_refs[:MAX_LIST_ITEMS],
                source_snapshot_ids=snapshot_ids[:MAX_LIST_ITEMS],
                thinking_candidate_ids=thinking_ids[:MAX_LIST_ITEMS],
            ),
        ]
        if thinking_candidates:
            items.append(
                PreModifyAdjustmentItem(
                    item_id="pre_modify_adjustment_item_003",
                    item_type="information_release",
                    priority="medium",
                    target_field="information_release_note",
                    proposed_change_summary="Use existing background thinking notes as safe planning evidence, not as canon facts.",
                    evidence_refs=[
                        self._thinking_evidence(candidate)
                        for candidate in thinking_candidates[:MAX_LIST_ITEMS]
                    ],
                    source_snapshot_ids=snapshot_ids[:MAX_LIST_ITEMS],
                    thinking_candidate_ids=thinking_ids[:MAX_LIST_ITEMS],
                )
            )
        for index, warning in enumerate(risk_warnings[:3], start=len(items) + 1):
            items.append(
                PreModifyAdjustmentItem(
                    item_id=f"pre_modify_adjustment_item_{index:03d}",
                    item_type="risk_warning",
                    priority="high" if "CONFIRMED" in warning else "medium",
                    target_field="review_gate",
                    proposed_change_summary=_short_text(warning, MAX_SAFE_LABEL_LENGTH),
                    evidence_refs=evidence_refs[:MAX_LIST_ITEMS],
                    source_snapshot_ids=snapshot_ids[:MAX_LIST_ITEMS],
                    thinking_candidate_ids=thinking_ids[:MAX_LIST_ITEMS],
                )
            )
        return items[:MAX_LIST_ITEMS]

    def _evidence_refs(
        self,
        preview: ModificationImpactPreview,
        source_refs: list[AffectedObjectRef],
        target_snapshots: list[SceneVersionSnapshot],
        affected_snapshots: list[SceneVersionSnapshot],
        thinking_candidates: list[ThinkingCandidate],
    ) -> list[dict[str, Any]]:
        refs = [
            {
                "object_type": "modification_impact_preview",
                "object_id": preview.preview_id,
                "status": preview.status,
                "relation": "source_preview",
                "summary": _short_text(preview.modification_summary or preview.source_summary, 240),
            }
        ]
        refs.extend(self._safe_affected_ref(ref) for ref in source_refs[:MAX_LIST_ITEMS])
        refs.extend(self._snapshot_evidence(snapshot, "target_snapshot") for snapshot in target_snapshots[:5])
        refs.extend(self._snapshot_evidence(snapshot, "affected_snapshot") for snapshot in affected_snapshots[:5])
        refs.extend(self._thinking_evidence(candidate) for candidate in thinking_candidates[:5])
        return [self._sanitize_payload(ref) for ref in refs[:MAX_LIST_ITEMS]]

    def _safe_candidate_summary(
        self,
        preview: ModificationImpactPreview,
        target_scene: Scene,
        snapshots: list[SceneVersionSnapshot],
        thinking_candidates: list[ThinkingCandidate],
    ) -> dict[str, Any]:
        snapshot_statuses = ", ".join(
            f"{snapshot.snapshot_id}:{snapshot.status}" for snapshot in snapshots[:4]
        )
        thinking_hint = ""
        if thinking_candidates:
            thinking_hint = _short_text(
                thinking_candidates[0].safe_summary.get("continuity_focus")
                or thinking_candidates[0].safe_summary.get("next_scene_focus"),
                220,
            )
        return self._sanitize_payload(
            {
                "next_adjustment_focus": _short_text(
                    target_scene.goal or target_scene.synopsis or target_scene.scene_id,
                    MAX_SAFE_TEXT_LENGTH,
                ),
                "continuity_alignment": _short_text(
                    f"Compare source preview {preview.preview_id} with target scene refs and snapshots.",
                    MAX_SAFE_TEXT_LENGTH,
                ),
                "memory_alignment": _short_text(
                    thinking_hint
                    or "Review memory and scene dependency refs before generating future prose.",
                    MAX_SAFE_TEXT_LENGTH,
                ),
                "information_release_note": (
                    "Planning-only candidate. Do not write new canon facts or full future prose in M3."
                ),
                "target_snapshot_statuses": snapshot_statuses,
            }
        )

    def _user_visible_reason(
        self,
        preview: ModificationImpactPreview,
        target_scene: Scene,
        source_refs: list[AffectedObjectRef],
        thinking_candidates: list[ThinkingCandidate],
    ) -> str:
        relation = self._relation_summary(source_refs) or "future scene dependency"
        thinking_note = " Existing background thinking is available." if thinking_candidates else ""
        return _short_text(
            f"{target_scene.scene_id} is marked as a later scene affected by {preview.preview_id} through {relation}.{thinking_note}",
            MAX_SAFE_LABEL_LENGTH,
        )

    def _adjustment_summary(
        self,
        preview: ModificationImpactPreview,
        target_scene: Scene,
        snapshots: list[SceneVersionSnapshot],
        thinking_candidates: list[ThinkingCandidate],
    ) -> str:
        return _short_text(
            (
                f"Review {target_scene.scene_id} against preview {preview.preview_id}; "
                f"use {len(snapshots)} snapshot refs and {len(thinking_candidates)} thinking candidates as planning evidence."
            ),
            MAX_SAFE_LABEL_LENGTH,
        )

    def _risk_warnings(
        self,
        target_scene: Scene,
        snapshots: list[SceneVersionSnapshot],
        thinking_candidates: list[ThinkingCandidate],
    ) -> list[str]:
        warnings: list[str] = []
        if target_scene.status in CONFIRMED_SCENE_STATUSES:
            warnings.append("TARGET_SCENE_CONFIRMED_NO_AUTO_APPLY")
        if not snapshots:
            warnings.append("TARGET_SCENE_HAS_NO_SNAPSHOT_EVIDENCE")
        if any(snapshot.status != "active" for snapshot in snapshots):
            warnings.append("TARGET_SCENE_HAS_STALE_SNAPSHOT_EVIDENCE")
        if not thinking_candidates:
            warnings.append("NO_READY_THINKING_CANDIDATE_FOR_TARGET")
        return _unique_strings(warnings)

    def _is_source_or_current_ref(
        self,
        ref: AffectedObjectRef,
        preview: ModificationImpactPreview,
    ) -> bool:
        return (
            ref.impact_area == "current_scene"
            or ref.relation == "source_scene"
            or ref.scene_id == preview.source_object_id
            or ref.object_id == preview.source_object_id
        )

    def _is_future_scene_ref(self, ref: AffectedObjectRef) -> bool:
        return (
            ref.impact_area == "future_scene_dependency"
            or ref.relation in FUTURE_SCENE_RELATIONS
        )

    def _is_later_scene(self, source_scene: Scene | None, target_scene: Scene) -> bool:
        if source_scene is None:
            return True
        if target_scene.scene_id == source_scene.scene_id:
            return False
        if target_scene.chapter_id == source_scene.chapter_id:
            return target_scene.scene_index > source_scene.scene_index
        return True

    def _find_scene(self, scene_id: str) -> Scene | None:
        raw = self.repositories.scenes.get_by_id(str(scene_id or "").strip())
        if raw is None:
            return None
        try:
            return Scene(**raw)
        except ValidationError as exc:
            raise StorageError("PRE_MODIFY_SCHEMA_INVALID: Scene JSON schema is invalid.") from exc

    def _safe_affected_ref(self, ref: AffectedObjectRef) -> dict[str, Any]:
        data = model_to_dict(ref)
        result = {
            key: data.get(key)
            for key in SOURCE_AFFECTED_REF_KEYS
            if key in data and data.get(key) not in (None, "", [])
        }
        if "reason" in result:
            result["reason"] = _short_text(result["reason"], MAX_SAFE_LABEL_LENGTH)
        if "summary" in result:
            result["summary"] = _short_text(result["summary"], MAX_SAFE_LABEL_LENGTH)
        if "ref_ids" in result:
            result["ref_ids"] = _unique_strings(result["ref_ids"])[:MAX_LIST_ITEMS]
        return self._sanitize_payload(result)

    def _snapshot_evidence(
        self,
        snapshot: SceneVersionSnapshot,
        relation: str,
    ) -> dict[str, Any]:
        return self._sanitize_payload(
            {
                "object_type": "scene_snapshot",
                "object_id": snapshot.snapshot_id,
                "scene_id": snapshot.target_scene_id or snapshot.subject_id,
                "chapter_id": snapshot.chapter_id,
                "status": snapshot.status,
                "relation": relation,
                "summary": _short_text(
                    snapshot.safe_summary.get("goal_summary")
                    or snapshot.safe_summary.get("synopsis_summary")
                    or snapshot.snapshot_type,
                    MAX_SAFE_LABEL_LENGTH,
                ),
                "snapshot_hash": snapshot.snapshot_hash,
            }
        )

    def _thinking_evidence(self, candidate: ThinkingCandidate) -> dict[str, Any]:
        return self._sanitize_payload(
            {
                "object_type": "thinking_candidate",
                "object_id": candidate.candidate_id,
                "scene_id": candidate.target_scene_id or candidate.source_scene_id,
                "status": candidate.status,
                "relation": "background_thinking_evidence",
                "summary": _short_text(
                    candidate.safe_summary.get("next_scene_focus")
                    or candidate.safe_summary.get("continuity_focus")
                    or candidate.candidate_id,
                    MAX_SAFE_LABEL_LENGTH,
                ),
                "ref_ids": candidate.based_on_snapshot_ids[:MAX_LIST_ITEMS],
            }
        )

    def _max_impact_level(self, refs: list[AffectedObjectRef]) -> str:
        levels = [ref.impact_level for ref in refs]
        if "high" in levels:
            return "high"
        if "medium" in levels:
            return "medium"
        return "low"

    def _relation_summary(self, refs: list[AffectedObjectRef]) -> str:
        return " / ".join(_unique_strings([ref.relation for ref in refs])[:3])

    def _read_candidates(self) -> list[PreModifyCandidate]:
        if not self.store.exists(self.candidates_file):
            return []
        result: list[PreModifyCandidate] = []
        for item in self.store.read_list(self.candidates_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(PreModifyCandidate(**item))
            except ValidationError as exc:
                raise StorageError("PRE_MODIFY_SCHEMA_INVALID: Candidate JSON schema is invalid.") from exc
        return result

    def _read_plans(self) -> list[PreModifyAdjustmentPlan]:
        if not self.store.exists(self.plans_file):
            return []
        result: list[PreModifyAdjustmentPlan] = []
        for item in self.store.read_list(self.plans_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(PreModifyAdjustmentPlan(**item))
            except ValidationError as exc:
                raise StorageError("PRE_MODIFY_SCHEMA_INVALID: Plan JSON schema is invalid.") from exc
        return result

    def _read_reasons(self) -> list[PreModifyImpactReason]:
        if not self.store.exists(self.reasons_file):
            return []
        result: list[PreModifyImpactReason] = []
        for item in self.store.read_list(self.reasons_file):
            if not isinstance(item, dict):
                continue
            try:
                result.append(PreModifyImpactReason(**item))
            except ValidationError as exc:
                raise StorageError("PRE_MODIFY_SCHEMA_INVALID: Reason JSON schema is invalid.") from exc
        return result

    def _write_all(
        self,
        candidates: list[PreModifyCandidate],
        plans: list[PreModifyAdjustmentPlan],
        reasons: list[PreModifyImpactReason],
    ) -> None:
        candidate_payload = [model_to_dict(item) for item in candidates]
        plan_payload = [model_to_dict(item) for item in plans]
        reason_payload = [model_to_dict(item) for item in reasons]
        self._guard_safe_payload(
            {
                "candidates": candidate_payload,
                "plans": plan_payload,
                "reasons": reason_payload,
            }
        )
        self.store.write(self.candidates_file, candidate_payload)
        self.store.write(self.plans_file, plan_payload)
        self.store.write(self.reasons_file, reason_payload)

    def _next_candidate_id(self) -> str:
        return f"pre_modify_candidate_{len(self._read_candidates()) + 1:03d}"

    def _next_plan_id(self) -> str:
        return f"pre_modify_adjustment_plan_{len(self._read_plans()) + 1:03d}"

    def _next_reason_id(self) -> str:
        return f"pre_modify_impact_reason_{len(self._read_reasons()) + 1:03d}"

    def _sanitize_payload(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            value = model_to_dict(value)
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if key_text.casefold() in UNSAFE_KEY_NAMES:
                    continue
                result[key_text] = self._sanitize_payload(item)
            return result
        if isinstance(value, list):
            return [self._sanitize_payload(item) for item in value[:MAX_LIST_ITEMS]]
        if isinstance(value, str):
            return _short_text(value, MAX_SAFE_TEXT_LENGTH)
        return value

    def _guard_safe_payload(self, value: Any) -> None:
        issues = self._scan_for_unsafe_payload(value)
        if issues:
            raise StorageError(
                "PRE_MODIFY_UNSAFE_PAYLOAD_BLOCKED: "
                + "; ".join(issues[:5])
            )

    def _safety(self, value: Any) -> dict[str, Any]:
        issues = self._scan_for_unsafe_payload(value)
        return {
            "safe": not issues,
            "issues": issues[:MAX_LIST_ITEMS],
        }

    def _scan_for_unsafe_payload(self, value: Any, path: str = "$") -> list[str]:
        issues: list[str] = []
        if isinstance(value, BaseModel):
            value = model_to_dict(value)
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                if key_text.casefold() in UNSAFE_KEY_NAMES:
                    issues.append(f"unsafe_key:{path}.{key_text}")
                    continue
                issues.extend(self._scan_for_unsafe_payload(item, f"{path}.{key_text}"))
            return issues
        if isinstance(value, list):
            for index, item in enumerate(value):
                issues.extend(self._scan_for_unsafe_payload(item, f"{path}[{index}]"))
            return issues
        if isinstance(value, str):
            text = value.strip()
            lower = text.casefold()
            if any(marker in lower for marker in UNSAFE_VALUE_MARKERS):
                issues.append(f"unsafe_value:{path}")
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
