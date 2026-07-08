from __future__ import annotations

from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.narrative_layer import NarrativeDebt
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.narrative_debt_deadline_service import (
    NarrativeDebtDeadlineService,
)
from app.backend.storage.json_store import JsonStore


SAFE_TEXT_LIMIT = 240


class NarrativeDebtVisibilityService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        deadline_service: NarrativeDebtDeadlineService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.deadline_service = deadline_service or NarrativeDebtDeadlineService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def visibility_summary(
        self,
        *,
        scene_id: str | None = None,
        chapter_id: str | None = None,
    ) -> dict[str, Any]:
        debts = self._filtered_debts(scene_id=scene_id, chapter_id=chapter_id)
        safe_debts = [self.safe_debt_summary(debt) for debt in debts]
        status_counts = self._status_counts(safe_debts)
        active_debts = [
            debt for debt in safe_debts if debt.get("status") == "active"
        ]
        intentionally_open_debts = [
            debt for debt in safe_debts if debt.get("status") == "intentionally_open"
        ]
        expired_warnings = [
            debt for debt in safe_debts if debt.get("deadline_state") == "expired"
        ]
        deadline_warning_count = sum(
            1 for debt in safe_debts if debt.get("deadline_warning")
        )
        counts = {
            "total": len(safe_debts),
            "active": len(active_debts),
            "active_required_payoff": sum(
                1 for debt in active_debts if debt.get("payoff_required")
            ),
            "intentionally_open": len(intentionally_open_debts),
            "paid_off": status_counts.get("paid_off", 0),
            "rejected": status_counts.get("rejected", 0),
            "expired_warnings": len(expired_warnings),
            "deadline_warnings": deadline_warning_count,
        }
        return {
            "success": True,
            "scene_id": scene_id or "",
            "chapter_id": chapter_id or "",
            "counts": counts,
            "status_counts": status_counts,
            "deadline_warning_count": deadline_warning_count,
            "active_debts": active_debts,
            "intentionally_open_debts": intentionally_open_debts,
            "expired_warnings": expired_warnings,
            "safe_debts": safe_debts,
        }

    def safe_debt_summary(self, debt: NarrativeDebt) -> dict[str, Any]:
        deadline = self.deadline_service.derive_deadline_state(debt)
        return {
            "narrative_debt_id": debt.narrative_debt_id,
            "debt_type": debt.debt_type,
            "status": debt.status,
            "summary": _short_text(debt.summary, SAFE_TEXT_LIMIT),
            "source_scene_id": debt.source_scene_id,
            "source_apparent_contradiction_id": debt.source_apparent_contradiction_id,
            "source_narrative_intent_id": debt.source_narrative_intent_id,
            "payoff_required": debt.payoff_required,
            "open_ambiguity_allowed": debt.open_ambiguity_allowed,
            "symbolic_unresolved": debt.symbolic_unresolved,
            "payoff_deadline_type": debt.payoff_deadline_type,
            "payoff_deadline_chapter_id": debt.payoff_deadline_chapter_id,
            "payoff_deadline_scene_index": debt.payoff_deadline_scene_index,
            "payoff_deadline_note": _short_text(
                debt.payoff_deadline_note,
                SAFE_TEXT_LIMIT,
            ),
            "payoff_scene_id": debt.payoff_scene_id,
            "user_decision_id": debt.user_decision_id,
            "deadline_state": deadline.deadline_state,
            "deadline_warning": _short_text(
                deadline.deadline_warning,
                SAFE_TEXT_LIMIT,
            ),
            "available_actions": self._available_actions(debt),
        }

    def _filtered_debts(
        self,
        *,
        scene_id: str | None,
        chapter_id: str | None,
    ) -> list[NarrativeDebt]:
        debts = [
            NarrativeDebt(**record)
            for record in self.repositories.narrative_debts.list_all()
        ]
        if scene_id:
            debts = [
                debt
                for debt in debts
                if scene_id
                in {debt.scene_id, debt.source_scene_id, debt.payoff_scene_id}
            ]
        if chapter_id:
            debts = [debt for debt in debts if debt.chapter_id == chapter_id]
        return sorted(
            debts,
            key=lambda debt: (
                debt.status != "active",
                debt.status != "intentionally_open",
                debt.updated_at or debt.created_at,
                debt.narrative_debt_id,
            ),
        )

    def _status_counts(self, safe_debts: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {
            "active": 0,
            "paid_off": 0,
            "expired": 0,
            "intentionally_open": 0,
            "rejected": 0,
        }
        for debt in safe_debts:
            status = str(debt.get("status") or "")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _available_actions(self, debt: NarrativeDebt) -> list[str]:
        if debt.status == "active":
            return [
                "mark_paid_off",
                "mark_intentionally_open",
                "reject",
                "update",
            ]
        if debt.status == "intentionally_open":
            return ["mark_paid_off", "reject", "update"]
        if debt.status == "expired":
            return [
                "mark_paid_off",
                "mark_intentionally_open",
                "reject",
                "update",
            ]
        return ["update"] if debt.status == "paid_off" else []


def _short_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = " ".join(text.split())
    return compact[:limit]
