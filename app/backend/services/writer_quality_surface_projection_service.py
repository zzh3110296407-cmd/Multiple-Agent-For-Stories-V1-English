from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.writer_quality_surface import (
    WriterQualitySurfaceExpertView,
    WriterQualitySurfaceOrdinaryView,
    WriterQualitySurfaceResponse,
)
from app.backend.storage.json_store import JsonStore, StorageError


SCENES_FILE = "scenes.json"
COMPOSITE_RUNTIME_RUNS_FILE = "composite_runtime_graph_runs.json"

SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9._-]+"),
    re.compile(r"(?i)\blsv2_[A-Za-z0-9._-]+"),
)
UNSAFE_TEXT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\braw[_ -]?prompt\b",
        r"\braw[_ -]?response\b",
        r"\bhidden[_ -]?reasoning\b",
        r"\bchain[-_ ]of[-_ ]thought\b",
        r"\braw[_ -]?psychology[_ -]?chain\b",
        r"\bprovider raw\b",
        r"\btraceback\b",
        r"\bgatefinding\b",
        r"\bgaterunreport\b",
        r"\bscenerevisionplan\b",
        r"\bqualitygate\b",
        r"\bcontinuitygate\b",
    )
)

READER_EXPERIENCE_CODES = {
    "plot_turn_missing",
    "visible_action_missing",
    "dialogue_or_decision_missing",
    "ending_pull_missing",
    "scene_reader_value_missing",
    "reader_value_missing",
    "empty_mystery_too_high",
    "suspense_overexplained",
}
PSYCHOLOGY_VISIBILITY_CODES = {
    "raw_psychology_chain_leak",
    "hidden_reasoning_leak",
    "interior_monologue_not_earned",
    "action_replaced_by_explanation",
    "subtext_should_be_behavior",
    "minor_role_over_interiorized",
    "forbidden_psychology_channel_used",
    "character_depth_flattened_by_exposition",
}
PSYCHOLOGY_OVEREXPOSURE_CODES = {
    "psychology_overexposed",
    "interior_monologue_not_earned",
    "minor_role_over_interiorized",
    "action_replaced_by_explanation",
    "character_depth_flattened_by_exposition",
}
PROSE_STYLE_CODES = {
    "abstract_language_too_high",
    "abstract_language_density_high",
    "adjective_density_too_high",
    "adjective_density_high",
    "prose_too_literary_for_profile",
    "plain_language_profile_failed",
    "placeholder_or_instruction_text_leak",
    "internal_json_leak",
    "diagnostic_text_leak",
}
HOOK_PAYOFF_CODES = {
    "opening_hook_too_abstract",
    "ending_pull_too_abstract",
    "reader_question_not_advanced",
    "hook_payoff_missing",
}
SUBTEXT_BALANCE_CODES = {
    "subtext_balance_failed",
    "negative_space_leaked",
    "subtext_should_be_behavior",
}
HARD_BLOCKING_CODES = {
    "raw_psychology_chain_leak",
    "hidden_reasoning_leak",
    "provider_raw_leak",
    "internal_json_leak",
    "diagnostic_text_leak",
}
ALL_WRITER_QUALITY_CODES = (
    READER_EXPERIENCE_CODES
    | PSYCHOLOGY_VISIBILITY_CODES
    | PSYCHOLOGY_OVEREXPOSURE_CODES
    | PROSE_STYLE_CODES
    | HOOK_PAYOFF_CODES
    | SUBTEXT_BALANCE_CODES
    | HARD_BLOCKING_CODES
)
REPORT_REF_PREFIXES = {
    "source_scene_prose_plan_id": ("scene_prose_plan_", "scene_prose_plan:"),
    "source_psychology_visibility_plan_id": ("psych_visibility_plan_", "psychology_visibility_plan_"),
    "source_beat_sheet_id": ("beat_sheet_", "beat_sheet:"),
    "source_reader_experience_report_id": ("reader_experience_report_",),
    "source_psychology_overexposure_report_id": ("psychology_overexposure_report_",),
    "source_prose_style_inspection_report_id": ("prose_style_report_", "prose_style_inspection_report_"),
    "source_hook_payoff_inspection_report_id": ("hook_payoff_report_", "hook_payoff_inspection_report_"),
    "source_subtext_balance_inspection_report_id": ("subtext_balance_report_", "subtext_balance_inspection_report_"),
    "source_writer_self_revision_report_id": ("writer_self_revision_report_", "writer_self_revision:"),
}


class WriterQualitySurfaceProjectionService:
    """Build safe user-facing WriterAgent quality projections without raw traces."""

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir

    def build_surface(
        self,
        scene_id: str,
        *,
        include_expert: bool = False,
    ) -> WriterQualitySurfaceResponse:
        scene_id = str(scene_id or "").strip()
        if not scene_id:
            raise ValueError("scene_id is required.")
        scene = self._load_scene(scene_id)
        run = self._latest_runtime_run_for_scene(scene)
        ordinary = self._ordinary_view(scene, run)
        expert = self._expert_view(scene, run) if include_expert else None
        return WriterQualitySurfaceResponse(
            scene_id=scene_id,
            ordinary=ordinary,
            expert=expert,
            read_only=True,
        )

    def _load_scene(self, scene_id: str) -> dict[str, Any]:
        path = self.data_dir / SCENES_FILE
        raw = self.store.read_any(path)
        scenes = raw if isinstance(raw, list) else raw.get("scenes", []) if isinstance(raw, dict) else []
        for scene in scenes:
            if isinstance(scene, dict) and str(scene.get("scene_id") or "").strip() == scene_id:
                return scene
        raise StorageError(f"Scene does not exist: {scene_id}")

    def _latest_runtime_run_for_scene(self, scene: dict[str, Any]) -> dict[str, Any]:
        path = self.data_dir / COMPOSITE_RUNTIME_RUNS_FILE
        if not path.exists():
            return {}
        try:
            raw = self.store.read_any(path)
        except StorageError:
            return {}
        runs = raw if isinstance(raw, list) else raw.get("runs", []) if isinstance(raw, dict) else []
        scene_id = str(scene.get("scene_id") or "")
        chapter_id = str(scene.get("chapter_id") or "")
        scene_index = _to_int(scene.get("scene_index"))
        for run in reversed([item for item in runs if isinstance(item, dict)]):
            candidate = _dict(run.get("candidate_scene_output"))
            if scene_id and str(candidate.get("scene_id") or "") == scene_id:
                return run
            if (
                chapter_id
                and str(candidate.get("chapter_id") or "") == chapter_id
                and _to_int(candidate.get("scene_index")) == scene_index
            ):
                return run
        return {}

    def _ordinary_view(self, scene: dict[str, Any], run: dict[str, Any]) -> WriterQualitySurfaceOrdinaryView:
        candidate = _dict(run.get("candidate_scene_output"))
        gate = self._scene_gate_pipeline(scene)
        issue_codes = self._issue_codes(scene, run)
        blocking_codes = sorted(set(issue_codes).intersection(HARD_BLOCKING_CODES))
        candidate_eligible = candidate.get("eligible_for_commit_service_review")
        visible_to_user = gate.get("visible_to_user", True) is not False
        user_action_required = bool(gate.get("user_action_required")) or not visible_to_user
        user_action_options = _as_list(gate.get("user_action_options"))
        auto_repair_applied = bool(
            gate.get("auto_repair_applied")
            or candidate.get("writer_self_revision_applied")
            or self._has_writer_self_revision_ref(run)
        )

        if not visible_to_user:
            status = "blocked"
            confirmability = "not_confirmable"
            background = "blocked"
            show_expert = True
        elif candidate and candidate_eligible is True and not issue_codes:
            status = "ready"
            confirmability = "confirmable"
            background = "completed"
            show_expert = False
        elif candidate and issue_codes:
            status = "needs_cleanup"
            confirmability = "not_confirmable" if blocking_codes else "needs_review"
            background = "needs_cleanup"
            show_expert = bool(blocking_codes)
        elif gate and str(gate.get("status") or "").startswith("passed"):
            status = "ready"
            confirmability = "confirmable"
            background = "completed"
            show_expert = False
        elif scene.get("prose_text") or _dict(scene.get("content")).get("prose_text"):
            status = "checking"
            confirmability = "needs_review"
            background = "checking"
            show_expert = False
        else:
            status = "not_available"
            confirmability = "unknown"
            background = "unknown"
            show_expert = False

        return WriterQualitySurfaceOrdinaryView(
            scene_id=str(scene.get("scene_id") or ""),
            project_id=str(scene.get("project_id") or candidate.get("project_id") or ""),
            chapter_id=str(scene.get("chapter_id") or candidate.get("chapter_id") or ""),
            scene_index=_to_int(scene.get("scene_index") or candidate.get("scene_index")),
            status=status,
            confirmability=confirmability,
            visible_to_user=visible_to_user,
            safe_user_summary=self._safe_summary(
                scene=scene,
                run=run,
                issue_codes=issue_codes,
                auto_repair_applied=auto_repair_applied,
                visible_to_user=visible_to_user,
            ),
            reader_experience_status=self._component_status(issue_codes, READER_EXPERIENCE_CODES, candidate),
            psychology_visibility_status=self._component_status(issue_codes, PSYCHOLOGY_VISIBILITY_CODES, candidate),
            psychology_overexposure_status=self._component_status(issue_codes, PSYCHOLOGY_OVEREXPOSURE_CODES, candidate),
            prose_style_status=self._component_status(issue_codes, PROSE_STYLE_CODES, candidate),
            hook_payoff_status=self._component_status(issue_codes, HOOK_PAYOFF_CODES, candidate),
            subtext_balance_status=self._component_status(issue_codes, SUBTEXT_BALANCE_CODES, candidate),
            self_revision_status=self._self_revision_status(candidate, run, issue_codes),
            issue_count=len(issue_codes),
            blocking_issue_count=len(blocking_codes) + len(_as_list(run.get("blocking_findings"))),
            auto_repair_applied=auto_repair_applied,
            user_action_required=user_action_required,
            user_action_options=[_safe_id(item) for item in user_action_options],
            show_expert_entry=show_expert or bool(gate.get("show_expert_entry")),
            background_check_state=background,
        )

    def _expert_view(self, scene: dict[str, Any], run: dict[str, Any]) -> WriterQualitySurfaceExpertView:
        candidate = _dict(run.get("candidate_scene_output"))
        refs = self._safe_refs(scene, run)
        source_ids = self._source_ids(candidate, refs)
        issue_codes = self._issue_codes(scene, run)
        status_summaries = self._expert_status_summaries(run)
        return WriterQualitySurfaceExpertView(
            scene_id=str(scene.get("scene_id") or candidate.get("scene_id") or ""),
            writer_candidate_draft_id=_safe_id(candidate.get("writer_candidate_draft_id")),
            graph_run_id=_safe_id(run.get("graph_run_id")),
            source_scene_prose_plan_id=source_ids["source_scene_prose_plan_id"],
            source_psychology_visibility_plan_id=source_ids["source_psychology_visibility_plan_id"],
            source_beat_sheet_id=source_ids["source_beat_sheet_id"],
            source_reader_experience_report_id=source_ids["source_reader_experience_report_id"],
            source_psychology_overexposure_report_id=source_ids[
                "source_psychology_overexposure_report_id"
            ],
            source_prose_style_inspection_report_id=source_ids[
                "source_prose_style_inspection_report_id"
            ],
            source_hook_payoff_inspection_report_id=source_ids[
                "source_hook_payoff_inspection_report_id"
            ],
            source_subtext_balance_inspection_report_id=source_ids[
                "source_subtext_balance_inspection_report_id"
            ],
            source_writer_self_revision_report_id=source_ids[
                "source_writer_self_revision_report_id"
            ],
            writer_quality_issue_codes=[_safe_id(code) for code in issue_codes],
            writer_self_revision_applied=bool(
                candidate.get("writer_self_revision_applied") or self._has_writer_self_revision_ref(run)
            ),
            eligible_for_commit_service_review=bool(candidate.get("eligible_for_commit_service_review")),
            candidate_only=candidate.get("candidate_only") is not False,
            can_write_scene_prose_directly=bool(
                candidate.get("can_write_scene_prose_directly")
                or candidate.get("can_write_scene_directly")
            ),
            can_write_story_facts_directly=bool(candidate.get("can_write_story_facts_directly")),
            requires_post_draft_gate_review=candidate.get("requires_post_draft_gate_review") is not False,
            safe_trace_refs=refs[:30],
            safe_status_summaries=status_summaries[:16],
            redaction_applied=True,
        )

    def _scene_gate_pipeline(self, scene: dict[str, Any]) -> dict[str, Any]:
        direct = _dict(scene.get("scene_gate_pipeline"))
        if direct:
            return direct
        trace = _dict(scene.get("generation_trace"))
        return _dict(trace.get("scene_gate_pipeline"))

    def _issue_codes(self, scene: dict[str, Any], run: dict[str, Any]) -> list[str]:
        codes: list[str] = []
        candidate = _dict(run.get("candidate_scene_output"))
        codes.extend(_as_list(candidate.get("writer_quality_issue_codes")))
        codes.extend(_as_list(candidate.get("issue_codes")))
        for item in _as_list(run.get("warnings")) + _as_list(run.get("blocking_findings")):
            codes.extend(self._codes_from_item(item))
        for node in _as_list(run.get("node_receipts")):
            if not isinstance(node, dict):
                continue
            codes.extend(_as_list(node.get("warnings")))
            codes.extend(_as_list(node.get("blocking_findings")))
        gate = self._scene_gate_pipeline(scene)
        codes.extend(_as_list(gate.get("writer_quality_issue_codes")))
        codes.extend(_as_list(gate.get("issue_codes")))
        normalized = [_normalize_issue_code(code) for code in codes if _normalize_issue_code(code)]
        return _unique_strings([code for code in normalized if code in ALL_WRITER_QUALITY_CODES])

    def _codes_from_item(self, item: Any) -> list[str]:
        if isinstance(item, str):
            return [_normalize_issue_code(item)]
        if isinstance(item, dict):
            return [
                _normalize_issue_code(
                    item.get("category")
                    or item.get("finding_code")
                    or item.get("issue_code")
                    or item.get("code")
                    or item.get("issue_id")
                )
            ]
        return []

    def _component_status(
        self,
        issue_codes: list[str],
        group_codes: set[str],
        candidate: dict[str, Any],
    ) -> str:
        matches = sorted(set(issue_codes).intersection(group_codes))
        if any(code in HARD_BLOCKING_CODES for code in matches):
            return "blocked"
        if matches:
            return "needs_cleanup"
        if candidate:
            return "passed"
        return "not_available"

    def _self_revision_status(
        self,
        candidate: dict[str, Any],
        run: dict[str, Any],
        issue_codes: list[str],
    ) -> str:
        if candidate.get("writer_self_revision_applied") or self._has_writer_self_revision_ref(run):
            return "auto_revised" if not issue_codes else "revision_needs_review"
        if candidate and not issue_codes:
            return "not_needed"
        if candidate:
            return "needs_cleanup"
        return "not_available"

    def _safe_summary(
        self,
        *,
        scene: dict[str, Any],
        run: dict[str, Any],
        issue_codes: list[str],
        auto_repair_applied: bool,
        visible_to_user: bool,
    ) -> str:
        gate = self._scene_gate_pipeline(scene)
        if not visible_to_user:
            return _safe_text(
                gate.get("safe_user_summary")
                or "当前草稿需要补充信息或用户处理后才能展示。",
                420,
            )
        if auto_repair_applied and not issue_codes:
            return "系统已自动整理当前草稿，写作质量检查未发现需要用户处理的问题。"
        if issue_codes:
            return "系统发现当前草稿还有写作质量提醒，请按提示处理或进入专家模式查看摘要。"
        if run:
            return _safe_text(
                run.get("safe_summary")
                or "后台写作质量检查已完成，当前草稿可以继续阅读。",
                420,
            )
        if scene.get("prose_text") or _dict(scene.get("content")).get("prose_text"):
            return "当前草稿已有正文，后台写作质量摘要暂不可用。"
        return "当前场景还没有可展示的写作质量摘要。"

    def _safe_refs(self, scene: dict[str, Any], run: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        if run.get("graph_run_id"):
            refs.append(f"composite_runtime_graph_run:{run.get('graph_run_id')}")
        candidate = _dict(run.get("candidate_scene_output"))
        for key in (
            "candidate_scene_output_id",
            "writer_candidate_draft_id",
            "source_scene_prose_plan_id",
            "source_psychology_visibility_plan_id",
            "source_beat_sheet_id",
            "source_reader_experience_report_id",
            "source_psychology_overexposure_report_id",
            "source_prose_style_inspection_report_id",
            "source_hook_payoff_inspection_report_id",
            "source_subtext_balance_inspection_report_id",
            "source_writer_self_revision_report_id",
        ):
            value = candidate.get(key)
            if value:
                refs.append(f"{key}:{value}")
        for node in _as_list(run.get("node_receipts")):
            if not isinstance(node, dict):
                continue
            refs.extend(_as_list(node.get("output_refs")))
            refs.extend(_as_list(node.get("gate_receipt_ids")))
        scene_id = scene.get("scene_id")
        if scene_id:
            refs.append(f"scene:{scene_id}")
        return _unique_strings([_safe_text(ref, 220) for ref in refs if ref])[:80]

    def _source_ids(self, candidate: dict[str, Any], refs: list[str]) -> dict[str, str]:
        source_ids: dict[str, str] = {}
        for field, prefixes in REPORT_REF_PREFIXES.items():
            direct = _safe_id(candidate.get(field))
            if direct:
                source_ids[field] = direct
                continue
            source_ids[field] = self._first_ref_with_prefix(refs, prefixes)
        return source_ids

    def _first_ref_with_prefix(self, refs: list[str], prefixes: tuple[str, ...]) -> str:
        for ref in refs:
            text = str(ref or "").strip()
            for prefix in prefixes:
                if prefix in text:
                    return _safe_id(text)
        return ""

    def _expert_status_summaries(self, run: dict[str, Any]) -> list[str]:
        summaries: list[str] = []
        if run.get("final_decision"):
            summaries.append(f"final_decision:{_safe_id(run.get('final_decision'))}")
        for node in _as_list(run.get("node_receipts")):
            if not isinstance(node, dict):
                continue
            node_id = _safe_id(node.get("node_id"))
            status = _safe_id(node.get("status"))
            if node_id or status:
                summaries.append(f"{node_id or 'node'}:{status or 'unknown'}")
        return _unique_strings(summaries)

    def _has_writer_self_revision_ref(self, run: dict[str, Any]) -> bool:
        refs = []
        for node in _as_list(run.get("node_receipts")):
            if isinstance(node, dict):
                refs.extend(_as_list(node.get("output_refs")))
                refs.extend(_as_list(node.get("input_refs")))
        return any("writer_self_revision" in str(ref) for ref in refs)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = " ".join(text.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_issue_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text:
        text = text.split(":", 1)[0]
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_").casefold()
    return text


def _safe_id(value: Any, limit: int = 220) -> str:
    return _safe_text(value, limit)


def _safe_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    for pattern in UNSAFE_TEXT_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text[:limit]
