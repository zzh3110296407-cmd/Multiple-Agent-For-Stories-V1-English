from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.framework_composition import (
    FrameworkCompositionDraft,
    FrameworkCompositionDraftCreateRequest,
    FrameworkCompositionDraftListResponse,
    FrameworkCompositionReferenceType,
    FrameworkCompositionSlot,
    FrameworkCompositionValidationIssue,
    FrameworkCompositionValidationReport,
)
from app.backend.storage.json_store import JsonStore, StorageError


DRAFTS_FILE = "framework_composition_drafts.json"
LIBRARY_ITEMS_FILE = "framework_module_library_items.json"
PATTERNS_FILE = "framework_pattern_records.json"
COMPOSITION_RULES_FILE = "module_composition_rules.json"
COPYRIGHT_FILE = "copyright_source_records.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def copy_model(model: BaseModel, update: dict[str, Any]) -> Any:
    if hasattr(model, "model_copy"):
        return model.model_copy(update=update)
    return model.copy(update=update)


def validation_issue(
    code: str,
    message: str,
    *,
    severity: str = "warning",
    slot: FrameworkCompositionSlot | None = None,
    field_path: str | None = None,
    safe_detail: str | None = None,
) -> FrameworkCompositionValidationIssue:
    return FrameworkCompositionValidationIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        slot_id=slot.slot_id if slot else None,
        reference_type=slot.reference_type if slot else None,
        reference_id=slot.reference_id if slot else None,
        field_path=field_path,
        message=message,
        safe_detail=safe_detail,
    )


class FrameworkCompositionService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.drafts_file = self.data_dir / DRAFTS_FILE

    def create_draft(
        self,
        request: FrameworkCompositionDraftCreateRequest | dict[str, Any],
    ) -> FrameworkCompositionDraft:
        parsed = self._parse_create_request(request)
        existing = self._read_drafts()
        timestamp = now_iso()
        draft = FrameworkCompositionDraft(
            composition_id=self._next_id(existing),
            project_id=parsed.project_id,
            title=parsed.title,
            user_mode=parsed.user_mode,
            composition_status="draft",
            full_book_framework_slots=list(parsed.full_book_framework_slots),
            chapter_framework_slots=list(parsed.chapter_framework_slots),
            validation_report=self.validate_slots(
                user_mode=parsed.user_mode,
                full_book_framework_slots=parsed.full_book_framework_slots,
                chapter_framework_slots=parsed.chapter_framework_slots,
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )
        existing.append(draft)
        self._write_drafts(existing)
        return draft

    def list_drafts(self) -> FrameworkCompositionDraftListResponse:
        drafts = self._read_drafts()
        return FrameworkCompositionDraftListResponse(
            drafts=drafts,
            total_count=len(drafts),
        )

    def get_draft(self, composition_id: str) -> FrameworkCompositionDraft:
        for draft in self._read_drafts():
            if draft.composition_id == composition_id:
                return draft
        raise StorageError(f"FRAMEWORK_COMPOSITION_DRAFT_NOT_FOUND:{composition_id}")

    def validate_draft(self, composition_id: str) -> FrameworkCompositionDraft:
        drafts = self._read_drafts()
        for index, draft in enumerate(drafts):
            if draft.composition_id == composition_id:
                updated = copy_model(
                    draft,
                    update={
                        "validation_report": self.validate_slots(
                            user_mode=draft.user_mode,
                            full_book_framework_slots=draft.full_book_framework_slots,
                            chapter_framework_slots=draft.chapter_framework_slots,
                        ),
                        "updated_at": now_iso(),
                    }
                )
                drafts[index] = updated
                self._write_drafts(drafts)
                return updated
        raise StorageError(f"FRAMEWORK_COMPOSITION_DRAFT_NOT_FOUND:{composition_id}")

    def confirm_draft(self, composition_id: str) -> FrameworkCompositionDraft:
        drafts = self._read_drafts()
        for index, draft in enumerate(drafts):
            if draft.composition_id == composition_id:
                validation_report = self.validate_slots(
                    user_mode=draft.user_mode,
                    full_book_framework_slots=draft.full_book_framework_slots,
                    chapter_framework_slots=draft.chapter_framework_slots,
                )
                updated = copy_model(
                    draft,
                    update={
                        "composition_status": (
                            "blocked"
                            if validation_report.blocking_issue_count
                            else "confirmed"
                        ),
                        "validation_report": validation_report,
                        "updated_at": now_iso(),
                    }
                )
                drafts[index] = updated
                self._write_drafts(drafts)
                return updated
        raise StorageError(f"FRAMEWORK_COMPOSITION_DRAFT_NOT_FOUND:{composition_id}")

    def validate_slots(
        self,
        *,
        user_mode: str,
        full_book_framework_slots: list[FrameworkCompositionSlot],
        chapter_framework_slots: list[FrameworkCompositionSlot],
    ) -> FrameworkCompositionValidationReport:
        issues: list[FrameworkCompositionValidationIssue] = []
        all_slots = [
            ("full_book_framework_slots", index, slot)
            for index, slot in enumerate(full_book_framework_slots)
        ] + [
            ("chapter_framework_slots", index, slot)
            for index, slot in enumerate(chapter_framework_slots)
        ]

        if not all_slots:
            issues.append(
                validation_issue(
                    "composition_has_no_slots",
                    "Composition draft must contain at least one framework slot.",
                    severity="blocking",
                    field_path="full_book_framework_slots",
                )
            )

        for slot_group, index, slot in all_slots:
            field_path = f"{slot_group}[{index}]"
            if slot.source_dependence == "source_bound" and user_mode != "continuation_rewrite":
                issues.append(
                    validation_issue(
                        "source_bound_material_in_non_continuation_mode",
                        "source_bound framework slots cannot be used in this mode by default.",
                        severity="blocking",
                        slot=slot,
                        field_path=f"{field_path}.source_dependence",
                    )
                )
            if slot.reference_type == "analyzer_material":
                issues.extend(self._validate_analyzer_material_slot(slot, user_mode, field_path))
            elif slot.reference_type == "library_item":
                issues.extend(self._validate_library_item_slot(slot, field_path))
            elif slot.reference_type == "pattern":
                issues.extend(
                    self._validate_reference_exists(
                        slot,
                        PATTERNS_FILE,
                        ("pattern_id", "id"),
                        field_path,
                    )
                )
            elif slot.reference_type == "composition_rule":
                issues.extend(self._validate_composition_rule_slot(slot, field_path))

        blocking_count = len([issue for issue in issues if issue.severity == "blocking"])
        warning_count = len([issue for issue in issues if issue.severity == "warning"])
        return FrameworkCompositionValidationReport(
            validation_status="blocked" if blocking_count else "passed",
            blocking_issue_count=blocking_count,
            warning_count=warning_count,
            issues=issues,
            safe_summary=(
                f"Framework composition validation found {blocking_count} blocking issues "
                f"and {warning_count} warnings."
            ),
        )

    def _validate_analyzer_material_slot(
        self,
        slot: FrameworkCompositionSlot,
        user_mode: str,
        field_path: str,
    ) -> list[FrameworkCompositionValidationIssue]:
        issues: list[FrameworkCompositionValidationIssue] = []
        if not slot.source_refs:
            issues.append(
                validation_issue(
                    "analyzer_material_missing_source_refs",
                    "Analyzer material slots must preserve source_refs.",
                    severity="blocking",
                    slot=slot,
                    field_path=f"{field_path}.source_refs",
                )
            )
        return issues

    def _validate_library_item_slot(
        self,
        slot: FrameworkCompositionSlot,
        field_path: str,
    ) -> list[FrameworkCompositionValidationIssue]:
        issues = self._validate_reference_exists(
            slot,
            LIBRARY_ITEMS_FILE,
            ("library_item_id", "item_id", "id"),
            field_path,
        )
        item = self._find_record(
            LIBRARY_ITEMS_FILE,
            ("library_item_id", "item_id", "id"),
            slot.reference_id,
        )
        if item:
            visibility = item.get("visibility")
            if visibility in {"archived", "blocked"}:
                issues.append(
                    validation_issue(
                        "blocked_or_archived_library_item",
                        "Blocked or archived library items cannot be confirmed.",
                        severity="blocking",
                        slot=slot,
                        field_path=f"{field_path}.reference_id",
                        safe_detail=f"visibility={visibility}",
                    )
                )
        for record in self._read_records(COPYRIGHT_FILE):
            if record.get("source_id") != slot.reference_id:
                continue
            risk_level = record.get("risk_level")
            visibility_limit = record.get("visibility_limit")
            if risk_level in {"high", "blocked"}:
                issues.append(
                    validation_issue(
                        "high_risk_library_item",
                        "High-risk or blocked copyright library items cannot be confirmed.",
                        severity="blocking",
                        slot=slot,
                        field_path=f"{field_path}.reference_id",
                        safe_detail=f"risk_level={risk_level}",
                    )
                )
            if visibility_limit in {"archived", "blocked"}:
                issues.append(
                    validation_issue(
                        "blocked_visibility_library_item",
                        "Library item visibility limit blocks confirmation.",
                        severity="blocking",
                        slot=slot,
                        field_path=f"{field_path}.reference_id",
                        safe_detail=f"visibility_limit={visibility_limit}",
                    )
                )
        return issues

    def _validate_composition_rule_slot(
        self,
        slot: FrameworkCompositionSlot,
        field_path: str,
    ) -> list[FrameworkCompositionValidationIssue]:
        issues = self._validate_reference_exists(
            slot,
            COMPOSITION_RULES_FILE,
            ("rule_id", "composition_rule_id", "id"),
            field_path,
        )
        rule = self._find_record(
            COMPOSITION_RULES_FILE,
            ("rule_id", "composition_rule_id", "id"),
            slot.reference_id,
        )
        if rule and rule.get("status") in {"rejected", "archived", "blocked"}:
            issues.append(
                validation_issue(
                    "inactive_composition_rule",
                    "Rejected, archived, or blocked composition rules cannot be confirmed.",
                    severity="blocking",
                    slot=slot,
                    field_path=f"{field_path}.reference_id",
                    safe_detail=f"status={rule.get('status')}",
                )
            )
        return issues

    def _validate_reference_exists(
        self,
        slot: FrameworkCompositionSlot,
        file_name: str,
        id_fields: tuple[str, ...],
        field_path: str,
    ) -> list[FrameworkCompositionValidationIssue]:
        if self._find_record(file_name, id_fields, slot.reference_id) is not None:
            return []
        return [
            validation_issue(
                f"{slot.reference_type}_reference_not_found",
                "Referenced framework library record was not found.",
                severity="warning",
                slot=slot,
                field_path=f"{field_path}.reference_id",
                safe_detail=f"file={file_name}",
            )
        ]

    def _find_record(
        self,
        file_name: str,
        id_fields: tuple[str, ...],
        reference_id: str,
    ) -> dict[str, Any] | None:
        for record in self._read_records(file_name):
            for field_name in id_fields:
                if record.get(field_name) == reference_id:
                    return record
        return None

    def _read_records(self, file_name: str) -> list[dict[str, Any]]:
        path = self.data_dir / file_name
        if not self.store.exists(path):
            return []
        try:
            data = self.store.read_any(path)
        except StorageError:
            return []
        if not isinstance(data, list):
            return []
        return [record for record in data if isinstance(record, dict)]

    def _read_drafts(self) -> list[FrameworkCompositionDraft]:
        if not self.store.exists(self.drafts_file):
            return []
        data = self.store.read_list(self.drafts_file)
        return [FrameworkCompositionDraft(**item) for item in data if isinstance(item, dict)]

    def _write_drafts(self, drafts: list[FrameworkCompositionDraft]) -> None:
        self.store.write(self.drafts_file, [model_to_dict(draft) for draft in drafts])

    def _parse_create_request(
        self,
        request: FrameworkCompositionDraftCreateRequest | dict[str, Any],
    ) -> FrameworkCompositionDraftCreateRequest:
        if isinstance(request, FrameworkCompositionDraftCreateRequest):
            return request
        return FrameworkCompositionDraftCreateRequest(**request)

    def _next_id(self, existing: list[FrameworkCompositionDraft]) -> str:
        used = {draft.composition_id for draft in existing}
        index = len(existing) + 1
        while True:
            candidate = f"framework_composition_{index:03d}"
            if candidate not in used:
                return candidate
            index += 1
