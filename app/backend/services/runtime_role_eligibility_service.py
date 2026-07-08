from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.runtime_participation import RuntimeRoleEligibilityReport
from app.backend.repositories import RepositoryBundle, create_repositories
from app.backend.services.abcd_runtime_participation_policy_service import now_utc
from app.backend.storage.json_store import JsonStore, StorageError


CONFIRMED_STATUS = "confirmed"
ROLE_TIERS = {"A", "B", "C", "D"}


class RuntimeRoleEligibilityService:
    """Computes M1 role participation eligibility without mutating story data."""

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
        self.characters_file = self.data_dir / "characters.json"
        self.project_file = self.data_dir / "project.json"

    def build_report(self, project_id: str | None = None) -> RuntimeRoleEligibilityReport:
        characters = self._read_characters()
        resolved_project_id = project_id or self._read_project_id() or "local_project"
        confirmed: dict[str, list[str]] = {tier: [] for tier in sorted(ROLE_TIERS)}
        archived_or_invalid: list[str] = []

        for character in characters:
            character_id = str(character.get("character_id") or "").strip()
            if not character_id:
                continue
            tier = str(character.get("tier") or "").strip().upper()
            status = str(character.get("status") or "").strip()
            archived_at = str(character.get("archived_at") or "").strip()
            if tier in ROLE_TIERS and status == CONFIRMED_STATUS and not archived_at:
                confirmed[tier].append(character_id)
            else:
                archived_or_invalid.append(character_id)

        chapter_explicit = self._unique([*confirmed["A"], *confirmed["B"]])
        scene_selection = self._unique(
            [*confirmed["A"], *confirmed["B"], *confirmed["C"], *confirmed["D"]]
        )
        return RuntimeRoleEligibilityReport(
            project_id=resolved_project_id,
            confirmed_a_ids=self._unique(confirmed["A"]),
            confirmed_b_ids=self._unique(confirmed["B"]),
            confirmed_c_ids=self._unique(confirmed["C"]),
            confirmed_d_ids=self._unique(confirmed["D"]),
            eligible_for_chapter_explicit_ids=chapter_explicit,
            eligible_for_scene_selection_ids=scene_selection,
            archived_or_invalid_ids=self._unique(archived_or_invalid),
            source_character_count=len(characters),
            safe_summary=(
                "Confirmed active A/B roles are chapter-explicit; confirmed active A/B/C/D roles are scene-selectable."
            ),
            created_at=now_utc(),
        )

    def _read_project_id(self) -> str:
        if not self.store.exists(self.project_file):
            return ""
        try:
            project = self.store.read(self.project_file)
        except StorageError:
            return ""
        return str(project.get("project_id") or "").strip()

    def _read_characters(self) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self.repositories.characters.list_all()
            if isinstance(item, dict)
        ]

    def _unique(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = str(value or "").strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            result.append(clean)
        return result
