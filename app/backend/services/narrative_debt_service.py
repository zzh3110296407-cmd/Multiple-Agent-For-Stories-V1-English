from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.decision import Decision
from app.backend.models.narrative_layer import NarrativeDebt
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.narrative_debt_visibility_service import (
    NarrativeDebtVisibilityService,
)
from app.backend.services.narrative_layer_service import (
    NarrativeLayerService,
    model_to_dict,
    utc_now,
)
from app.backend.storage.json_store import JsonStore, StorageError


ALLOWED_DEBT_PATCH_FIELDS = {
    "summary",
    "payoff_required",
    "open_ambiguity_allowed",
    "symbolic_unresolved",
    "payoff_deadline_type",
    "payoff_deadline_chapter_id",
    "payoff_deadline_scene_index",
    "payoff_deadline_note",
    "payoff_scene_id",
    "source_refs",
}


class NarrativeDebtService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        narrative_layer_service: NarrativeLayerService | None = None,
        visibility_service: NarrativeDebtVisibilityService | None = None,
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
        self.visibility_service = visibility_service or NarrativeDebtVisibilityService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def list_debts(
        self,
        *,
        status: str | None = None,
        scene_id: str | None = None,
        chapter_id: str | None = None,
    ) -> list[NarrativeDebt]:
        return self.narrative_layer_service.list_debts(
            status=status,
            scene_id=scene_id,
            chapter_id=chapter_id,
        )

    def get_debt(self, narrative_debt_id: str) -> NarrativeDebt:
        debt = self.narrative_layer_service.get_narrative_debt(narrative_debt_id)
        if debt is None:
            raise StorageError(f"Narrative debt not found: {narrative_debt_id}")
        return debt

    def patch_debt(
        self,
        narrative_debt_id: str,
        patch: dict[str, Any],
    ) -> NarrativeDebt:
        clean_patch = self._clean_patch(patch)
        return self.narrative_layer_service.update_narrative_debt(
            narrative_debt_id,
            clean_patch,
        )

    def mark_paid_off(
        self,
        narrative_debt_id: str,
        *,
        user_input: str = "",
        payoff_scene_id: str = "",
        note: str = "",
    ) -> NarrativeDebt:
        debt = self.get_debt(narrative_debt_id)
        clean_scene_id = str(payoff_scene_id or "").strip()
        clean_note = str(note or "").strip()
        clean_user_input = str(user_input or "").strip()
        if not clean_scene_id and not clean_note and not clean_user_input:
            raise StorageError("标记已 payoff 需要提供 payoff 场景或说明。")
        decision = self._write_decision(
            decision_type="narrative_debt_paid_off",
            target_id=debt.narrative_debt_id,
            user_input=(
                clean_user_input
                or clean_note
                or f"确认叙事债务 {debt.narrative_debt_id} 已完成 payoff。"
            ),
        )
        patch: dict[str, Any] = {
            "status": "paid_off",
            "user_decision_id": decision.decision_id,
        }
        if clean_scene_id:
            patch["payoff_scene_id"] = clean_scene_id
        if clean_note:
            patch["payoff_deadline_note"] = clean_note
        return self.narrative_layer_service.update_narrative_debt(
            debt.narrative_debt_id,
            patch,
        )

    def mark_intentionally_open(
        self,
        narrative_debt_id: str,
        *,
        user_input: str = "",
        note: str = "",
    ) -> NarrativeDebt:
        debt = self.get_debt(narrative_debt_id)
        clean_note = str(note or "").strip()
        decision = self._write_decision(
            decision_type="narrative_debt_intentionally_open",
            target_id=debt.narrative_debt_id,
            user_input=(
                str(user_input or "").strip()
                or clean_note
                or f"确认叙事债务 {debt.narrative_debt_id} 保持开放歧义。"
            ),
        )
        patch: dict[str, Any] = {
            "status": "intentionally_open",
            "open_ambiguity_allowed": True,
            "user_decision_id": decision.decision_id,
        }
        if debt.debt_type == "symbolic_unresolved":
            patch["symbolic_unresolved"] = True
        if clean_note:
            patch["payoff_deadline_note"] = clean_note
        return self.narrative_layer_service.update_narrative_debt(
            debt.narrative_debt_id,
            patch,
        )

    def reject(
        self,
        narrative_debt_id: str,
        *,
        user_input: str = "",
        note: str = "",
    ) -> NarrativeDebt:
        debt = self.get_debt(narrative_debt_id)
        decision = self._write_decision(
            decision_type="narrative_debt_rejected",
            target_id=debt.narrative_debt_id,
            user_input=(
                str(user_input or "").strip()
                or str(note or "").strip()
                or f"拒绝叙事债务 {debt.narrative_debt_id}。"
            ),
        )
        patch: dict[str, Any] = {
            "status": "rejected",
            "user_decision_id": decision.decision_id,
        }
        if note:
            patch["payoff_deadline_note"] = str(note).strip()
        return self.narrative_layer_service.update_narrative_debt(
            debt.narrative_debt_id,
            patch,
        )

    def visibility_summary(
        self,
        *,
        scene_id: str | None = None,
        chapter_id: str | None = None,
    ) -> dict[str, Any]:
        return self.visibility_service.visibility_summary(
            scene_id=scene_id,
            chapter_id=chapter_id,
        )

    def safe_debt_detail(self, narrative_debt_id: str) -> dict[str, Any]:
        return {
            "success": True,
            "debt": self.visibility_service.safe_debt_summary(
                self.get_debt(narrative_debt_id)
            ),
        }

    def _clean_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        raw = dict(patch or {})
        disallowed = sorted(set(raw) - ALLOWED_DEBT_PATCH_FIELDS)
        if disallowed:
            raise StorageError(
                "叙事债务只能轻量更新以下字段："
                + ", ".join(sorted(ALLOWED_DEBT_PATCH_FIELDS))
            )
        return {key: raw[key] for key in ALLOWED_DEBT_PATCH_FIELDS if key in raw}

    def _write_decision(
        self,
        *,
        decision_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decision = Decision(
            decision_id=self._next_decision_id(decision_type, target_id),
            decision_type=decision_type,
            target_type="narrative_debt",
            target_id=target_id,
            user_input=user_input,
            created_at=utc_now(),
        )
        self.repositories.decisions.upsert(
            model_to_dict(decision),
            id_field="decision_id",
        )
        return decision

    def _next_decision_id(self, decision_type: str, target_id: str) -> str:
        slug = _slug(f"{decision_type}_{target_id}")
        existing = {
            str(decision.get("decision_id") or "")
            for decision in self.repositories.decisions.list_all()
        }
        index = 1
        while True:
            candidate = f"decision_{slug}_{index:03d}"
            if candidate not in existing:
                return candidate
            index += 1


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return text[:96] or "narrative_debt"
