from __future__ import annotations

from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.framework_composition import (
    FRAMEWORK_COMPOSITION_SCHEMA_VERSION,
    FrameworkCompositionSlot,
)
from app.backend.services.framework_composition_service import (
    COMPOSITION_RULES_FILE,
    LIBRARY_ITEMS_FILE,
    PATTERNS_FILE,
    FrameworkCompositionService,
)
from app.backend.storage.json_store import JsonStore, StorageError


SCHEMA_VERSION = "story_generator.framework_context.v1"
SOURCE_BOUND = "source_bound"
SUPPORTED_FRAMEWORK_COMPOSITION_SCHEMA_VERSIONS = {
    FRAMEWORK_COMPOSITION_SCHEMA_VERSION,
}
SUPPORTED_ANALYZER_HANDOFF_VERSIONS = {"generator_handoff.v1"}
COMPATIBILITY_MATRIX = {
    "generator_framework_context_schema_version": SCHEMA_VERSION,
    "supported_framework_composition_schema_versions": sorted(
        SUPPORTED_FRAMEWORK_COMPOSITION_SCHEMA_VERSIONS
    ),
    "supported_analyzer_handoff_versions": sorted(SUPPORTED_ANALYZER_HANDOFF_VERSIONS),
}
CONSUMER_MODE_POLICIES = {
    "original_writing": {
        "allowed_source_dependence": ["source_free"],
        "source_bound_allowed": False,
        "source_fidelity_enabled": False,
        "description": "Original writing may consume abstract/source-free framework material only.",
    },
    "hybrid_adaptation": {
        "allowed_source_dependence": ["source_free", "adaptable"],
        "source_bound_allowed": False,
        "source_fidelity_enabled": False,
        "description": "Hybrid adaptation may consume reusable framework material; source-bound fidelity lanes stay out by default.",
    },
    "continuation_rewrite": {
        "allowed_source_dependence": ["source_free", SOURCE_BOUND],
        "source_bound_allowed": True,
        "source_fidelity_enabled": True,
        "description": "Continuation/rewrite may consume source-bound fidelity material with evidence refs.",
    },
}


class GeneratorFrameworkContextService:
    """Compile a confirmed framework composition into generator runtime context."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.compositions = FrameworkCompositionService(store=self.store, data_dir=self.data_dir)

    def build_context(self, composition_id: str) -> dict[str, Any]:
        draft = self.compositions.get_draft(composition_id)
        if draft.composition_status != "confirmed":
            raise StorageError(
                "GENERATOR_FRAMEWORK_CONTEXT_COMPOSITION_NOT_CONFIRMED:"
                f"{composition_id}:{draft.composition_status}"
            )
        composition_schema_version = (
            getattr(draft, "schema_version", None) or FRAMEWORK_COMPOSITION_SCHEMA_VERSION
        )
        if composition_schema_version not in SUPPORTED_FRAMEWORK_COMPOSITION_SCHEMA_VERSIONS:
            raise StorageError(
                "GENERATOR_FRAMEWORK_CONTEXT_UNSUPPORTED_COMPOSITION_SCHEMA:"
                f"{composition_id}:{composition_schema_version}"
            )

        evidence_refs: list[str] = []
        policy_issues: list[dict[str, Any]] = []
        global_items: list[dict[str, Any]] = []
        chapter_items: list[dict[str, Any]] = []
        source_fidelity_items: list[dict[str, Any]] = []
        consumer_mode_policy = self._consumer_mode_policy(str(draft.user_mode))
        continuation_mode = bool(consumer_mode_policy["source_fidelity_enabled"])

        for context_name, slot in self._iter_slots(
            draft.full_book_framework_slots,
            "global_framework_context",
        ):
            item = self._compile_slot(slot, context_name)
            if not self._item_allowed_by_policy(item, consumer_mode_policy):
                policy_issues.append(
                    self._consumer_whitelist_exclusion_issue(
                        slot,
                        context_name,
                        item,
                        consumer_mode_policy,
                    )
                )
                continue
            if self._is_source_bound_item(item):
                source_fidelity_items.append(self._source_fidelity_projection(item, context_name))
            global_items.append(item)
            self._extend_unique(evidence_refs, item.get("evidence_refs", []))

        for context_name, slot in self._iter_slots(
            draft.chapter_framework_slots,
            "chapter_framework_context",
        ):
            item = self._compile_slot(slot, context_name)
            if not self._item_allowed_by_policy(item, consumer_mode_policy):
                policy_issues.append(
                    self._consumer_whitelist_exclusion_issue(
                        slot,
                        context_name,
                        item,
                        consumer_mode_policy,
                    )
                )
                continue
            if self._is_source_bound_item(item):
                source_fidelity_items.append(self._source_fidelity_projection(item, context_name))
            chapter_items.append(item)
            self._extend_unique(evidence_refs, item.get("evidence_refs", []))

        source_fidelity_context = {
            "enabled": continuation_mode,
            "items": source_fidelity_items if continuation_mode else [],
        }
        if continuation_mode:
            for item in source_fidelity_items:
                self._extend_unique(evidence_refs, item.get("evidence_refs", []))

        return {
            "schema_version": SCHEMA_VERSION,
            "compatibility_contract": {
                **COMPATIBILITY_MATRIX,
                "framework_composition_schema_version": composition_schema_version,
                "compatible": True,
            },
            "consumer_mode_policy": consumer_mode_policy,
            "composition_ref": {
                "composition_id": draft.composition_id,
                "project_id": draft.project_id,
                "title": draft.title,
                "user_mode": draft.user_mode,
                "composition_status": draft.composition_status,
            },
            "global_framework_context": {
                "items": global_items,
            },
            "chapter_framework_context": {
                "items": chapter_items,
            },
            "source_fidelity_context": source_fidelity_context,
            "evidence_refs": evidence_refs,
            "policy_issues": policy_issues,
            "safe_summary": (
                "Generator framework context compiled from confirmed composition "
                f"{draft.composition_id}; global_items={len(global_items)}, "
                f"chapter_items={len(chapter_items)}, "
                f"source_fidelity_items={len(source_fidelity_context['items'])}."
            ),
        }

    def _iter_slots(
        self,
        slots: list[FrameworkCompositionSlot],
        context_name: str,
    ) -> list[tuple[str, FrameworkCompositionSlot]]:
        return [
            (context_name, slot)
            for slot in sorted(slots, key=lambda item: (item.order_index, item.slot_id))
        ]

    def _compile_slot(self, slot: FrameworkCompositionSlot, context_name: str) -> dict[str, Any]:
        resolved = self._resolve_reference(slot)
        evidence_refs: list[str] = []
        self._extend_unique(evidence_refs, list(slot.source_refs))
        self._extend_unique(evidence_refs, self._record_source_refs(resolved))
        source_dependence = slot.source_dependence or resolved.get("source_dependence") or "source_free"
        item = {
            "context_item_id": slot.slot_id,
            "target_context": context_name,
            "order_index": slot.order_index,
            "reference_type": slot.reference_type,
            "reference_id": slot.reference_id,
            "source_dependence": source_dependence,
            "label": resolved.get("label") or resolved.get("title") or slot.reference_id,
            "item_type": (
                resolved.get("item_type")
                or resolved.get("pattern_type")
                or resolved.get("relation_type")
                or slot.reference_type
            ),
            "safe_summary": slot.safe_summary or resolved.get("safe_summary") or "",
            "description": resolved.get("description") or "",
            "resolution_status": resolved.get("_resolution_status", "resolved"),
            "evidence_refs": evidence_refs,
        }
        if resolved.get("_resolution_status") == "unresolved_reference":
            item["resolution_note"] = "Reference was not found; slot-level safe_summary was preserved."
        return item

    def _resolve_reference(self, slot: FrameworkCompositionSlot) -> dict[str, Any]:
        if slot.reference_type == "library_item":
            return self._find_record(
                LIBRARY_ITEMS_FILE,
                ("library_item_id", "item_id", "id"),
                slot.reference_id,
            ) or self._unresolved_record()
        if slot.reference_type == "pattern":
            return self._find_record(
                PATTERNS_FILE,
                ("pattern_id", "id"),
                slot.reference_id,
            ) or self._unresolved_record()
        if slot.reference_type == "composition_rule":
            return self._find_record(
                COMPOSITION_RULES_FILE,
                ("rule_id", "composition_rule_id", "id"),
                slot.reference_id,
            ) or self._unresolved_record()
        if slot.reference_type == "analyzer_material":
            return {
                "_resolution_status": "slot_only",
                "label": slot.reference_id,
                "item_type": "analyzer_material",
                "source_dependence": slot.source_dependence or SOURCE_BOUND,
                "safe_summary": slot.safe_summary,
                "source_refs": list(slot.source_refs),
            }
        return self._unresolved_record()

    def _find_record(
        self,
        file_name: str,
        id_fields: tuple[str, ...],
        reference_id: str,
    ) -> dict[str, Any] | None:
        for record in self._read_records(file_name):
            if any(record.get(field_name) == reference_id for field_name in id_fields):
                return record
        return None

    def _read_records(self, file_name: str) -> list[dict[str, Any]]:
        path = self.data_dir / file_name
        if not path.exists():
            return []
        try:
            data = self.store.read_any(path)
        except StorageError:
            return []
        if not isinstance(data, list):
            return []
        return [record for record in data if isinstance(record, dict)]

    def _record_source_refs(self, record: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        raw_refs = record.get("source_refs", [])
        if not isinstance(raw_refs, list):
            return refs
        for raw_ref in raw_refs:
            if isinstance(raw_ref, str):
                refs.append(raw_ref)
            elif isinstance(raw_ref, dict):
                for field_name in ("source_ref_id", "source_id", "ref_id", "id"):
                    value = raw_ref.get(field_name)
                    if isinstance(value, str) and value.strip():
                        refs.append(value)
                        break
        return refs

    def _is_source_bound_item(self, item: dict[str, Any]) -> bool:
        return (
            item.get("source_dependence") == SOURCE_BOUND
            or item.get("item_type") in {"source_fidelity", "source_bound"}
            or (
                item.get("reference_type") == "analyzer_material"
                and item.get("source_dependence") == SOURCE_BOUND
            )
        )

    def _consumer_mode_policy(self, user_mode: str) -> dict[str, Any]:
        policy = CONSUMER_MODE_POLICIES.get(
            user_mode,
            CONSUMER_MODE_POLICIES["original_writing"],
        )
        return {
            "user_mode": user_mode,
            "allowed_source_dependence": list(policy["allowed_source_dependence"]),
            "source_bound_allowed": bool(policy["source_bound_allowed"]),
            "source_fidelity_enabled": bool(policy["source_fidelity_enabled"]),
            "description": str(policy["description"]),
        }

    def _item_allowed_by_policy(
        self,
        item: dict[str, Any],
        consumer_mode_policy: dict[str, Any],
    ) -> bool:
        allowed_source_dependence = set(
            consumer_mode_policy.get("allowed_source_dependence", [])
        )
        source_dependence = item.get("source_dependence") or "source_free"
        if source_dependence not in allowed_source_dependence:
            return False
        if self._is_source_bound_item(item) and not consumer_mode_policy.get(
            "source_bound_allowed",
            False,
        ):
            return False
        return True

    def _source_fidelity_projection(
        self,
        item: dict[str, Any],
        source_context: str,
    ) -> dict[str, Any]:
        return {
            "context_item_id": item["context_item_id"],
            "source_context": source_context,
            "reference_type": item["reference_type"],
            "reference_id": item["reference_id"],
            "source_dependence": item["source_dependence"],
            "safe_summary": item.get("safe_summary", ""),
            "evidence_refs": list(item.get("evidence_refs", [])),
        }

    def _consumer_whitelist_exclusion_issue(
        self,
        slot: FrameworkCompositionSlot,
        context_name: str,
        item: dict[str, Any],
        consumer_mode_policy: dict[str, Any],
    ) -> dict[str, Any]:
        code = (
            "source_bound_excluded_from_original_context"
            if self._is_source_bound_item(item)
            else "consumer_whitelist_excluded_item"
        )
        return {
            "code": code,
            "severity": "warning",
            "slot_id": slot.slot_id,
            "reference_type": slot.reference_type,
            "reference_id": slot.reference_id,
            "target_context": context_name,
            "source_dependence": item.get("source_dependence"),
            "consumer_mode": consumer_mode_policy.get("user_mode"),
            "allowed_source_dependence": list(
                consumer_mode_policy.get("allowed_source_dependence", [])
            ),
            "message": "Framework material was excluded by generator consumer whitelist.",
        }

    def _unresolved_record(self) -> dict[str, Any]:
        return {"_resolution_status": "unresolved_reference"}

    def _extend_unique(self, target: list[str], refs: list[str]) -> None:
        for ref in refs:
            if isinstance(ref, str) and ref.strip() and ref not in target:
                target.append(ref)

__all__ = [
    "COMPATIBILITY_MATRIX",
    "CONSUMER_MODE_POLICIES",
    "GeneratorFrameworkContextService",
    "SCHEMA_VERSION",
    "SUPPORTED_ANALYZER_HANDOFF_VERSIONS",
    "SUPPORTED_FRAMEWORK_COMPOSITION_SCHEMA_VERSIONS",
]
