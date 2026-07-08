from __future__ import annotations

from pathlib import Path
from typing import Any

from app.backend.models.analyzer_material_selector import (
    AnalyzerMaterialSelectionIssue,
    AnalyzerMaterialSelectionResult,
    AnalyzerMaterialUserMode,
    AnalyzerSelectedMaterial,
)
from app.backend.services.analyzer_handoff_import_service import (
    AnalyzerHandoffImportService,
)
from app.backend.storage.json_store import JsonStore, StorageError


ORIGINAL_PRIORITY_MODULES = {
    "pacing_structure",
    "arc_structure",
    "chapter_progression",
    "emotion_curve",
    "narrative_mechanism",
}
CONTINUATION_PRIORITY_MODULES = {
    "source_fidelity",
    "foreshadowing_system",
    "worldbuilding",
    "relationship_dynamics",
    "core_conflict",
    "information_release",
}
HYBRID_PRIORITY_MODULES = {
    "worldbuilding",
    "relationship_dynamics",
    "core_conflict",
    "adaptable_setting",
    "emotion_curve",
    "arc_structure",
}
ORIGINAL_TAGS = {"original_writing", "structure_only"}
CONTINUATION_TAGS = {"continuation", "rewrite", "source_story", "continuation_rewrite"}
HYBRID_TAGS = {"hybrid_adaptation"}


def selection_issue(
    code: str,
    message: str,
    *,
    material_id: str | None = None,
    field_path: str | None = None,
    severity: str = "warning",
    safe_detail: str | None = None,
) -> AnalyzerMaterialSelectionIssue:
    return AnalyzerMaterialSelectionIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        material_id=material_id,
        field_path=field_path,
        message=message,
        safe_detail=safe_detail,
    )


class AnalyzerMaterialSelectorService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        importer: AnalyzerHandoffImportService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.importer = importer or AnalyzerHandoffImportService(store=self.store)

    def select_from_output(
        self,
        output_dir: str | Path,
        user_mode: str,
    ) -> AnalyzerMaterialSelectionResult:
        normalized_mode = normalize_user_mode(user_mode)
        import_result = self.importer.import_output(output_dir)
        if import_result.import_status != "ready" or not import_result.handoff_path:
            return AnalyzerMaterialSelectionResult(
                selection_status="blocked",
                user_mode=normalized_mode,
                files_read=list(import_result.files_read),
                issues=[
                    selection_issue(
                        "handoff_import_not_ready",
                        "Analyzer handoff import must be ready before material selection.",
                        severity="blocking",
                        safe_detail=import_result.import_status,
                    )
                ],
                import_status=import_result.import_status,
                safe_summary="Material selection is blocked until analyzer handoff import is ready.",
            )

        files_read = list(import_result.files_read)
        handoff_path = Path(import_result.handoff_path)
        files_read.append(str(handoff_path))
        try:
            handoff = self.store.read(handoff_path)
        except StorageError as exc:
            return AnalyzerMaterialSelectionResult(
                selection_status="blocked",
                user_mode=normalized_mode,
                files_read=files_read,
                issues=[
                    selection_issue(
                        "handoff_read_failed",
                        "Validated analyzer handoff could not be read for material selection.",
                        severity="blocking",
                        safe_detail=str(exc),
                    )
                ],
                import_status=import_result.import_status,
                safe_summary="Material selection is blocked because the validated handoff could not be read.",
            )

        result = self.select_from_handoff(handoff, normalized_mode)
        result.files_read = files_read
        result.import_status = import_result.import_status
        return result

    def select_from_handoff(
        self,
        handoff: dict[str, Any],
        user_mode: str,
    ) -> AnalyzerMaterialSelectionResult:
        normalized_mode = normalize_user_mode(user_mode)
        raw_materials = handoff.get("generator_materials", [])
        issues: list[AnalyzerMaterialSelectionIssue] = []
        if not isinstance(raw_materials, list):
            return AnalyzerMaterialSelectionResult(
                selection_status="blocked",
                user_mode=normalized_mode,
                issues=[
                    selection_issue(
                        "generator_materials_invalid",
                        "generator_materials must be a list.",
                        field_path="generator_materials",
                        severity="blocking",
                    )
                ],
                safe_summary="Material selection is blocked because generator_materials is invalid.",
            )

        selected: list[tuple[int, AnalyzerSelectedMaterial]] = []
        excluded_count = 0
        for index, material in enumerate(raw_materials):
            if not isinstance(material, dict):
                excluded_count += 1
                issues.append(
                    selection_issue(
                        "material_invalid",
                        "Material entry must be an object.",
                        field_path=f"generator_materials[{index}]",
                    )
                )
                continue
            material_id = _material_id(material, index)
            source_refs = material.get("source_refs")
            if not isinstance(source_refs, list) or not source_refs:
                excluded_count += 1
                issues.append(
                    selection_issue(
                        "material_missing_source_refs",
                        "Material is excluded because source_refs is required.",
                        material_id=material_id,
                        field_path=f"generator_materials[{index}].source_refs",
                    )
                )
                continue

            evaluation = evaluate_material_for_mode(material, normalized_mode)
            if not evaluation["include"]:
                excluded_count += 1
                continue
            selected.append(
                (
                    index,
                    AnalyzerSelectedMaterial(
                        material_id=material_id,
                        material=dict(material),
                        selection_score=int(evaluation["score"]),
                        selection_bucket=evaluation["bucket"],  # type: ignore[arg-type]
                        selection_reasons=list(evaluation["reasons"]),
                    ),
                )
            )

        selected_items = [
            item
            for _, item in sorted(
                selected,
                key=lambda entry: (-entry[1].selection_score, entry[0]),
            )
        ]
        return AnalyzerMaterialSelectionResult(
            selection_status="ready",
            user_mode=normalized_mode,
            selected_materials=selected_items,
            excluded_material_count=excluded_count,
            source_material_count=len(raw_materials),
            issues=issues,
            safe_summary=(
                f"Selected {len(selected_items)} analyzer materials for {normalized_mode}."
            ),
        )


def normalize_user_mode(user_mode: str) -> AnalyzerMaterialUserMode:
    normalized = user_mode.strip().lower()
    if normalized in {"continuation", "rewrite", "source_story"}:
        return "continuation_rewrite"
    if normalized in {"original", "structure_only"}:
        return "original_writing"
    if normalized == "hybrid":
        return "hybrid_adaptation"
    if normalized in {"original_writing", "continuation_rewrite", "hybrid_adaptation"}:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"Unsupported analyzer material user mode: {user_mode}")


def evaluate_material_for_mode(
    material: dict[str, Any],
    user_mode: AnalyzerMaterialUserMode,
) -> dict[str, Any]:
    if user_mode == "original_writing":
        return _evaluate_original(material)
    if user_mode == "continuation_rewrite":
        return _evaluate_continuation(material)
    return _evaluate_hybrid(material)


def _evaluate_original(material: dict[str, Any]) -> dict[str, Any]:
    source_dependence = _string(material.get("source_dependence"))
    abstraction_level = _string(material.get("abstraction_level"))
    module_type = _string(material.get("module_type"))
    tags = _tags(material)
    if (
        source_dependence == "source_bound"
        or abstraction_level == "source_specific"
        or module_type == "source_fidelity"
    ):
        return _excluded("excluded_source_bound_or_source_specific")

    score = 10
    reasons = ["compatible_with_original_writing"]
    if source_dependence == "source_free":
        score += 25
        reasons.append("source_free")
    if source_dependence == "adaptable":
        score += 15
        reasons.append("adaptable")
    if abstraction_level == "abstract":
        score += 20
        reasons.append("abstract")
    if abstraction_level == "semi_abstract":
        score += 10
        reasons.append("semi_abstract")
    if tags & ORIGINAL_TAGS:
        score += 35
        reasons.append("original_or_structure_tag")
    if module_type in ORIGINAL_PRIORITY_MODULES:
        score += 30
        reasons.append("original_priority_module")
    return _included(score, reasons, preferred=score >= 70)


def _evaluate_continuation(material: dict[str, Any]) -> dict[str, Any]:
    source_dependence = _string(material.get("source_dependence"))
    abstraction_level = _string(material.get("abstraction_level"))
    module_type = _string(material.get("module_type"))
    tags = _tags(material)
    include = (
        source_dependence == "source_bound"
        or abstraction_level == "source_specific"
        or bool(tags & CONTINUATION_TAGS)
        or module_type in CONTINUATION_PRIORITY_MODULES
    )
    if not include:
        return _excluded("excluded_not_continuation_relevant")

    score = 10
    reasons = ["compatible_with_continuation_rewrite"]
    if source_dependence == "source_bound":
        score += 50
        reasons.append("source_bound")
    if abstraction_level == "source_specific":
        score += 40
        reasons.append("source_specific")
    if module_type == "source_fidelity":
        score += 35
        reasons.append("source_fidelity")
    if tags & CONTINUATION_TAGS:
        score += 30
        reasons.append("continuation_or_rewrite_tag")
    if module_type in CONTINUATION_PRIORITY_MODULES:
        score += 20
        reasons.append("continuation_priority_module")
    return _included(score, reasons, preferred=score >= 70)


def _evaluate_hybrid(material: dict[str, Any]) -> dict[str, Any]:
    source_dependence = _string(material.get("source_dependence"))
    abstraction_level = _string(material.get("abstraction_level"))
    module_type = _string(material.get("module_type"))
    tags = _tags(material)
    if source_dependence == "source_bound" or abstraction_level == "source_specific":
        return _excluded("excluded_source_specific_for_hybrid_default")
    if source_dependence not in {"adaptable", "source_free"}:
        return _excluded("excluded_not_adaptable_or_source_free")
    if abstraction_level not in {"semi_abstract", "abstract"}:
        return _excluded("excluded_not_abstract_enough")

    include = (
        bool(tags & HYBRID_TAGS)
        or module_type in HYBRID_PRIORITY_MODULES
        or source_dependence == "adaptable"
        or abstraction_level == "semi_abstract"
    )
    if not include:
        return _excluded("excluded_not_hybrid_relevant")

    score = 10
    reasons = ["compatible_with_hybrid_adaptation"]
    if source_dependence == "adaptable":
        score += 40
        reasons.append("adaptable")
    if abstraction_level == "semi_abstract":
        score += 30
        reasons.append("semi_abstract")
    if tags & HYBRID_TAGS:
        score += 30
        reasons.append("hybrid_adaptation_tag")
    if module_type in HYBRID_PRIORITY_MODULES:
        score += 20
        reasons.append("hybrid_priority_module")
    if source_dependence == "source_free":
        score += 10
        reasons.append("source_free")
    return _included(score, reasons, preferred=score >= 70)


def _included(score: int, reasons: list[str], *, preferred: bool) -> dict[str, Any]:
    return {
        "include": True,
        "score": score,
        "bucket": "preferred" if preferred else "compatible",
        "reasons": reasons,
    }


def _excluded(reason: str) -> dict[str, Any]:
    return {
        "include": False,
        "score": 0,
        "bucket": "compatible",
        "reasons": [reason],
    }


def _material_id(material: dict[str, Any], index: int) -> str:
    material_id = material.get("material_id")
    if isinstance(material_id, str) and material_id:
        return material_id
    return f"material_{index + 1:03d}"


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _tags(material: dict[str, Any]) -> set[str]:
    raw_tags = material.get("selection_tags", [])
    if not isinstance(raw_tags, list):
        return set()
    return {tag for tag in raw_tags if isinstance(tag, str)}
