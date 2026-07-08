from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.backend.core.config import settings
from app.backend.models.project_story_premise import ProjectStoryPremise
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import (
    SceneDraftContent,
    SceneProgressionStatement,
    SceneWritingContext,
)
from app.backend.models.scene_pattern_similarity import (
    SCENE_PATTERN_SIMILARITY_TOO_HIGH,
    SCENE_PATTERN_SIMILARITY_WARNING,
    ScenePatternSimilarityReport,
)
from app.backend.models.scene_revision import SceneRevisionCandidate
from app.backend.services.character_prompt_fidelity_service import (
    try_read_project_story_premise,
)
from app.backend.services.prompt_anchor_classification_service import (
    anchor_terms_from_value,
    classify_project_story_premise,
    classify_prompt_anchor_values,
    is_prompt_anchor_candidate,
)
from app.backend.services.project_story_premise_service import FORBIDDEN_DEMO_DEFAULTS
from app.backend.services.scene_pattern_similarity_gate_service import (
    ScenePatternSimilarityGateService,
)
from app.backend.storage.json_store import JsonStore


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))

PROMPT_FIDELITY_MISSING = "prompt_fidelity_missing"
PROMPT_FIDELITY_WEAK = "prompt_fidelity_weak"
DEMO_DEFAULT_LEAK = "demo_default_leak"
SCENE_REPETITION_TOO_HIGH = "scene_repetition_too_high"
SCENE_PROGRESSION_MISSING = "scene_progression_missing"
SCENE_PROGRESSION_STATEMENT_MISSING = "scene_progression_statement_missing"
SCENE_OBJECTIVE_REPEATED = "scene_objective_repeated"
SCENE_PREVIOUS_SUMMARY_MISSING = "scene_previous_summary_missing"
CHARACTER_UNIQUENESS_VIOLATION = "character_uniqueness_violation"
RUNTIME_EVIDENCE_STALE = "runtime_evidence_stale"

CONTENT_SIGNAL_BLOCKING_CODES = {
    PROMPT_FIDELITY_MISSING,
    DEMO_DEFAULT_LEAK,
    SCENE_REPETITION_TOO_HIGH,
    SCENE_PROGRESSION_MISSING,
    SCENE_PROGRESSION_STATEMENT_MISSING,
    SCENE_OBJECTIVE_REPEATED,
    SCENE_PREVIOUS_SUMMARY_MISSING,
}
CONTENT_SIGNAL_WARNING_CODES = {
    PROMPT_FIDELITY_WEAK,
    CHARACTER_UNIQUENESS_VIOLATION,
    RUNTIME_EVIDENCE_STALE,
}
SCENE_ADJACENT_SIMILARITY_BLOCK_THRESHOLD = 0.72
SCENE_LAST_THREE_SIMILARITY_BLOCK_THRESHOLD = 0.78
SCENE_NEAR_COPY_SIMILARITY_BLOCK_THRESHOLD = 0.96
SCENE_EXACT_COPY_SIMILARITY_BLOCK_THRESHOLD = 0.995
PROMPT_FIDELITY_MACHINE_MARKER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,}\b")
PROMPT_FIDELITY_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,24}")
PROMPT_FIDELITY_ASCII_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_\-]{2,}\b")
PROMPT_FIDELITY_NAME_CUE_RE = re.compile(
    r"(?:主角|角色|人物|记录员|导师|看守|姓名|名字)?(?:名为|叫作|叫|名字是|姓名是)([\u4e00-\u9fff]{2,8})"
)
PROMPT_FIDELITY_CONTROL_SUBSTRINGS = {
    "前端",
    "验收",
    "流程",
    "测试",
    "创建",
    "生成",
    "要求",
    "保持",
    "清晰",
    "短流程",
    "短篇",
    "章节",
    "一章",
    "两幕",
    "每章",
    "每幕",
    "提示",
    "用户",
    "项目",
    "工作台",
    "确认",
    "导出",
}
PROMPT_FIDELITY_GENERIC_CJK_ANCHORS = {
    "一个",
    "一部",
    "主角",
    "人物",
    "角色",
    "故事",
    "世界",
    "规则",
    "核心",
    "地点",
    "身份",
    "线索",
    "场景",
    "章节",
    "当前",
    "真实",
    "清晰",
    "推进",
    "奇幻",
    "中文",
    "记忆",
    "笔记",
}
PROMPT_FIDELITY_NEGATION_MARKERS = (
    "no ",
    "without ",
    "missing ",
    "lacks ",
    "lack of ",
    "not ",
    "没有",
    "沒有",
    "无",
    "無",
    "缺少",
    "未出现",
    "不包含",
)
PROMPT_FIDELITY_CJK_SEPARATORS = re.compile(
    r"(?:"
    r"主角|人物|角色|世界核心规则|世界规则|核心规则|地点|身份|"
    r"名为|叫作|叫|是|用于|用来|创建|生成|写|保持|推进|验收|流程|"
    r"只有|一章|两幕|短篇|中文|奇幻|故事|规则|清晰|要求|必须|需要|"
    r"会|把|被|让|将|找到|寻找|吞掉|吞没|夺走|失去|改写|留下|指向|围绕|关于|以及|并且|而且|和|与|及|或|的|在|里|中"
    r")"
)


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, BaseModel):
        return model.dict()
    if isinstance(model, dict):
        return dict(model)
    return {}


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class SceneContentQualitySignalIssue(BaseModel):
    code: str
    severity: str = "warning"
    user_visible: bool = True
    user_visible_message: str = ""
    technical_summary: str = ""
    evidence_excerpt: str = ""
    source_refs: list[str] = Field(default_factory=list)
    suggested_repair_types: list[str] = Field(default_factory=list)
    technical_metadata: dict[str, Any] = Field(default_factory=dict)


class SceneContentQualitySignalReport(BaseModel):
    target_type: str
    target_id: str
    scene_id: str = ""
    revision_id: str = ""
    prompt_terms_required: list[str] = Field(default_factory=list)
    prompt_terms_seen: list[str] = Field(default_factory=list)
    prompt_fidelity_status: str = "not_applicable"
    demo_default_count: int = 0
    adjacent_similarity: float = 0.0
    last_three_similarity: float = 0.0
    progression_statement_present: bool = False
    progression_status: str = "unknown"
    issues: list[SceneContentQualitySignalIssue] = Field(default_factory=list)
    generated_at: str = ""


class SceneContentQualitySignalService:
    """Deterministic M6 content-signal evaluator.

    The service is read-only. It never rewrites prose, scenes, events, memory,
    characters, relationships, archives, or progress records.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.scenes_file = self.data_dir / "scenes.json"

    def evaluate_scene(
        self,
        *,
        scene: Scene,
        candidate: SceneRevisionCandidate | None = None,
        project_id: str = "",
        recent_scenes: list[Scene] | None = None,
    ) -> SceneContentQualitySignalReport:
        target_type = "scene_revision" if candidate else "scene"
        target_id = candidate.revision_id if candidate else scene.scene_id
        story_text = self._target_story_text(scene, candidate)
        trace = scene.generation_trace
        writing_context = trace.scene_writing_context
        progression = trace.scene_progression_statement
        project_id = project_id or scene.project_id or LOCAL_PROJECT_ID
        premise = try_read_project_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
        )
        prompt_terms = self._prompt_terms(
            premise=premise,
            writing_context=writing_context,
            progression=progression,
        )
        prompt_terms_seen = [
            term for term in prompt_terms if self._contains_term(story_text, term)
        ]
        issues: list[SceneContentQualitySignalIssue] = []

        if prompt_terms:
            if not prompt_terms_seen:
                issues.append(
                    self._issue(
                        PROMPT_FIDELITY_MISSING,
                        "blocking",
                        "Scene-facing text does not include any required active project premise marker or core term.",
                        evidence=", ".join(prompt_terms[:8]),
                        source_refs=self._source_refs(scene, premise),
                    )
                )
                prompt_status = "missing"
            elif len(prompt_terms_seen) < min(2, len(prompt_terms)):
                issues.append(
                    self._issue(
                        PROMPT_FIDELITY_WEAK,
                        "warning",
                        "Scene-facing text includes only weak active premise evidence.",
                        evidence=", ".join(prompt_terms_seen[:8]),
                        source_refs=self._source_refs(scene, premise),
                    )
                )
                prompt_status = "weak"
            else:
                prompt_status = "ready"
        else:
            prompt_status = "not_applicable"

        demo_default_count = self._demo_default_count(story_text, premise)
        if demo_default_count:
            issues.append(
                self._issue(
                    DEMO_DEFAULT_LEAK,
                    "blocking",
                    "Scene-facing text contains demo/default story text that is not part of the active premise.",
                    evidence=f"demo_default_count={demo_default_count}",
                    source_refs=self._source_refs(scene, premise),
                )
            )

        previous_scenes = self._previous_scenes(
            scene=scene,
            recent_scenes=recent_scenes,
        )
        existing_inspection = trace.progression_inspection if candidate is None else None
        if existing_inspection is not None:
            adjacent_similarity = float(existing_inspection.adjacent_similarity or 0.0)
            last_three_similarity = float(existing_inspection.last_three_similarity or 0.0)
        else:
            previous_texts = [self._scene_story_text(item) for item in previous_scenes[-3:]]
            adjacent_similarity = (
                self._text_similarity(story_text, previous_texts[-1])
                if previous_texts
                else 0.0
            )
            last_three_similarity = max(
                [self._text_similarity(story_text, text) for text in previous_texts],
                default=0.0,
            )
        existing_repetition_block = (
            existing_inspection is not None
            and SCENE_REPETITION_TOO_HIGH in existing_inspection.blocking_issues
        )
        pattern_report = self._pattern_report(
            scene=scene,
            candidate=candidate,
            recent_scenes=recent_scenes,
        )
        text_similarity_high = (
            adjacent_similarity > SCENE_ADJACENT_SIMILARITY_BLOCK_THRESHOLD
            or last_three_similarity > SCENE_LAST_THREE_SIMILARITY_BLOCK_THRESHOLD
            or existing_repetition_block
        )
        text_near_copy = (
            max(adjacent_similarity, last_three_similarity)
            >= SCENE_NEAR_COPY_SIMILARITY_BLOCK_THRESHOLD
        )
        text_exact_copy = (
            max(adjacent_similarity, last_three_similarity)
            >= SCENE_EXACT_COPY_SIMILARITY_BLOCK_THRESHOLD
        )
        text_similarity_should_block = text_similarity_high and (
            pattern_report.verdict == "block_auto_repair"
            or text_exact_copy
            or (
                text_near_copy
                and not self._pattern_report_has_meaningful_progression(pattern_report)
            )
        )
        if text_similarity_should_block and (
            adjacent_similarity > SCENE_ADJACENT_SIMILARITY_BLOCK_THRESHOLD
            or existing_repetition_block
        ):
            issues.append(
                self._issue(
                    SCENE_REPETITION_TOO_HIGH,
                    "blocking",
                    "Scene-facing text is too similar to the immediately previous confirmed scene.",
                    evidence=f"adjacent_similarity={adjacent_similarity:.4f}",
                    source_refs=[scene.scene_id, *[item.scene_id for item in previous_scenes[-1:]]],
                )
            )
        elif text_similarity_should_block and last_three_similarity > SCENE_LAST_THREE_SIMILARITY_BLOCK_THRESHOLD:
            issues.append(
                self._issue(
                    SCENE_REPETITION_TOO_HIGH,
                    "blocking",
                    "Scene-facing text is too similar to a recent confirmed scene.",
                    evidence=f"last_three_similarity={last_three_similarity:.4f}",
                    source_refs=[scene.scene_id, *[item.scene_id for item in previous_scenes[-3:]]],
                )
            )
        elif text_similarity_high:
            issues.append(
                self._issue(
                    SCENE_REPETITION_TOO_HIGH,
                    "warning",
                    "Scene-facing text similarity is high but structural progression evidence is sufficient.",
                    evidence=(
                        f"adjacent_similarity={adjacent_similarity:.4f}; "
                        f"last_three_similarity={last_three_similarity:.4f}; "
                        f"pattern_verdict={pattern_report.verdict}"
                    ),
                    source_refs=[scene.scene_id, *[item.scene_id for item in previous_scenes[-3:]]],
                    user_visible=False,
                )
            )
        if pattern_report.verdict == "block_auto_repair":
            issues.append(
                self._issue(
                    SCENE_PATTERN_SIMILARITY_TOO_HIGH,
                    "blocking",
                    "Scene structural pattern is too similar to a recent scene and needs machine repair.",
                    evidence=(
                        "structural_similarity="
                        f"{pattern_report.structural_similarity_score:.4f}; "
                        f"text_similarity={pattern_report.text_similarity_score:.4f}"
                    ),
                    source_refs=pattern_report.source_refs,
                    suggested_repair_types=self._pattern_repair_focus(pattern_report),
                    technical_metadata=self._pattern_report_metadata(pattern_report),
                    user_visible=False,
                )
            )
        elif pattern_report.verdict == "warn_auto_repair":
            issues.append(
                self._issue(
                    SCENE_PATTERN_SIMILARITY_WARNING,
                    "warning",
                    "Scene structural pattern repeats multiple axes and should be strengthened.",
                    evidence=(
                        "structural_similarity="
                        f"{pattern_report.structural_similarity_score:.4f}; "
                        f"text_similarity={pattern_report.text_similarity_score:.4f}"
                    ),
                    source_refs=pattern_report.source_refs,
                    suggested_repair_types=self._pattern_repair_focus(pattern_report),
                    technical_metadata=self._pattern_report_metadata(pattern_report),
                    user_visible=False,
                )
            )

        progression_present = progression is not None
        progression_status = "ready"
        if progression is None:
            issues.append(
                self._issue(
                    SCENE_PROGRESSION_STATEMENT_MISSING,
                    "blocking",
                    "Scene generation trace has no scene progression statement.",
                    source_refs=[scene.scene_id],
                )
            )
            issues.append(
                self._issue(
                    SCENE_PROGRESSION_MISSING,
                    "blocking",
                    "Scene has no reusable progression evidence.",
                    source_refs=[scene.scene_id],
                )
            )
            progression_status = "missing"
        else:
            progression_missing = False
            if not progression.scene_objective.strip():
                progression_missing = True
            if not progression.new_information.strip() and not progression.character_state_delta.strip():
                progression_missing = True
            if not progression.conflict_turn.strip():
                progression_missing = True
            if progression_missing:
                issues.append(
                    self._issue(
                        SCENE_PROGRESSION_MISSING,
                        "blocking",
                        "Scene progression statement is incomplete.",
                        source_refs=[scene.scene_id],
                    )
                )
                progression_status = "missing"
            if self._objective_repeated(
                scene=scene,
                progression=progression,
                writing_context=writing_context,
                previous_scenes=previous_scenes,
            ):
                issues.append(
                    self._issue(
                        SCENE_OBJECTIVE_REPEATED,
                        "blocking",
                        "Scene progression objective repeats a recent scene objective.",
                        evidence=progression.scene_objective,
                        source_refs=[scene.scene_id],
                    )
                )
                progression_status = "repeated"

        previous_summary = (
            writing_context.previous_scene_summary.strip()
            if writing_context is not None
            else ""
        )
        if scene.scene_index > 1 and not previous_summary:
            issues.append(
                self._issue(
                    SCENE_PREVIOUS_SUMMARY_MISSING,
                    "blocking",
                    "Scene 2+ has no previous-scene summary evidence in writing context.",
                    source_refs=[scene.scene_id],
                )
            )
            if progression_status == "ready":
                progression_status = "missing_previous_summary"

        issues = self._dedupe_issues(issues)
        return SceneContentQualitySignalReport(
            target_type=target_type,
            target_id=target_id,
            scene_id=scene.scene_id,
            revision_id=candidate.revision_id if candidate else "",
            prompt_terms_required=prompt_terms,
            prompt_terms_seen=prompt_terms_seen,
            prompt_fidelity_status=prompt_status,
            demo_default_count=demo_default_count,
            adjacent_similarity=round(adjacent_similarity, 4),
            last_three_similarity=round(last_three_similarity, 4),
            progression_statement_present=progression_present,
            progression_status=progression_status,
            issues=issues,
            generated_at=now_iso(),
        )

    def _pattern_report_has_meaningful_progression(
        self,
        pattern_report: ScenePatternSimilarityReport,
    ) -> bool:
        signature = pattern_report.current_signature
        return any(
            bool(getattr(signature, field, False))
            for field in (
                "has_new_information",
                "has_character_state_delta",
                "has_conflict_turn",
                "has_cost_or_risk_delta",
            )
        )

    def evaluate_final_sequence(
        self,
        *,
        scenes: list[Scene],
        project_id: str,
    ) -> SceneContentQualitySignalReport:
        ordered = sorted(scenes, key=lambda item: (item.chapter_id, item.scene_index, item.scene_id))
        premise = try_read_project_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
        )
        sequence_terms = self._prompt_terms(premise=premise, writing_context=None, progression=None)
        prompt_seen: list[str] = []
        issues: list[SceneContentQualitySignalIssue] = []
        max_adjacent = 0.0
        max_last_three = 0.0
        demo_count = 0
        for scene in ordered:
            report = self.evaluate_scene(
                scene=scene,
                project_id=project_id,
                recent_scenes=ordered,
            )
            prompt_seen.extend(report.prompt_terms_seen)
            max_adjacent = max(max_adjacent, report.adjacent_similarity)
            max_last_three = max(max_last_three, report.last_three_similarity)
            demo_count += report.demo_default_count
            for issue in report.issues:
                if issue.code == PROMPT_FIDELITY_MISSING:
                    continue
                if issue.code in {
                    DEMO_DEFAULT_LEAK,
                    SCENE_REPETITION_TOO_HIGH,
                    SCENE_PROGRESSION_MISSING,
                    SCENE_PROGRESSION_STATEMENT_MISSING,
                    SCENE_OBJECTIVE_REPEATED,
                    SCENE_PREVIOUS_SUMMARY_MISSING,
                }:
                    issues.append(issue)
        prompt_seen = self._unique_strings(prompt_seen)
        if sequence_terms and not prompt_seen:
            issues.append(
                self._issue(
                    PROMPT_FIDELITY_MISSING,
                    "blocking",
                    "Confirmed final story sequence contains no active premise marker or core term.",
                    evidence=", ".join(sequence_terms[:8]),
                    source_refs=[scene.scene_id for scene in ordered[:8]],
                )
            )
        issues = self._dedupe_issues(issues)
        return SceneContentQualitySignalReport(
            target_type="final_story_package",
            target_id="confirmed_scene_sequence",
            prompt_terms_required=sequence_terms,
            prompt_terms_seen=prompt_seen,
            prompt_fidelity_status=(
                "ready" if prompt_seen else ("missing" if sequence_terms else "not_applicable")
            ),
            demo_default_count=demo_count,
            adjacent_similarity=round(max_adjacent, 4),
            last_three_similarity=round(max_last_three, 4),
            progression_statement_present=not any(
                issue.code == SCENE_PROGRESSION_STATEMENT_MISSING for issue in issues
            ),
            progression_status="blocked" if issues else "ready",
            issues=issues,
            generated_at=now_iso(),
        )

    def _target_story_text(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
    ) -> str:
        if candidate is not None:
            return "\n".join([candidate.revised_synopsis or "", candidate.revised_prose_text or ""])
        return self._scene_story_text(scene)

    def _scene_story_text(self, scene: Scene) -> str:
        content = scene.content
        synopsis = (content.synopsis if content else scene.synopsis) or scene.synopsis
        prose = (content.prose_text if content else scene.prose_text) or scene.prose_text
        return "\n".join([synopsis or "", prose or ""])

    def _prompt_terms(
        self,
        *,
        premise: ProjectStoryPremise | None,
        writing_context: SceneWritingContext | None,
        progression: SceneProgressionStatement | None,
    ) -> list[str]:
        values: list[Any] = []
        if premise is not None:
            values.append(classify_project_story_premise(premise, limit=40).positive_required_anchors)
        if writing_context is not None:
            contract = writing_context.prompt_fidelity_contract or {}
            premise_payload = writing_context.project_story_premise or {}
            forbidden_values: list[Any] = [contract.get("forbidden_markers") or []]
            values.extend(
                [
                    premise_payload.get("user_story_premise"),
                    premise_payload.get("safe_user_story_summary"),
                    premise_payload.get("prompt_markers_detected"),
                    premise_payload.get("core_terms"),
                    premise_payload.get("setting_terms"),
                    premise_payload.get("conflict_terms"),
                    premise_payload.get("role_terms"),
                    premise_payload.get("required_story_elements"),
                    contract.get("required_markers") or [],
                ]
            )
        else:
            forbidden_values = []
        if progression is not None:
            values.extend(progression.required_prompt_terms)
        return classify_prompt_anchor_values(
            values,
            forbidden_values=forbidden_values,
            limit=40,
        ).positive_required_anchors

    def _previous_scenes(
        self,
        *,
        scene: Scene,
        recent_scenes: list[Scene] | None,
    ) -> list[Scene]:
        candidates = recent_scenes if recent_scenes is not None else self._read_scenes()
        return sorted(
            [
                item
                for item in candidates
                if item.chapter_id == scene.chapter_id
                and item.scene_id != scene.scene_id
                and item.scene_index < scene.scene_index
                and str(item.status or "").lower() == "confirmed"
            ],
            key=lambda item: (item.scene_index, item.updated_at or item.created_at or ""),
        )

    def _read_scenes(self) -> list[Scene]:
        if not self.store.exists(self.scenes_file):
            return []
        result: list[Scene] = []
        for item in self.store.read_list(self.scenes_file):
            if isinstance(item, dict):
                result.append(Scene(**item))
        return result

    def _objective_repeated(
        self,
        *,
        scene: Scene,
        progression: SceneProgressionStatement,
        writing_context: SceneWritingContext | None,
        previous_scenes: list[Scene],
    ) -> bool:
        objective_norm = self._normalize_progression_text(progression.scene_objective)
        if not objective_norm:
            return False
        previous: list[str] = []
        if writing_context is not None:
            state = writing_context.chapter_state_so_far or {}
            previous.extend(state.get("recent_scene_goals") or [])
            previous.extend(state.get("recent_scene_progression_objectives") or [])
        for previous_scene in previous_scenes[-3:]:
            statement = previous_scene.generation_trace.scene_progression_statement
            if statement is not None:
                previous.append(statement.scene_objective)
            if previous_scene.goal:
                previous.append(previous_scene.goal)
        return any(
            objective_norm == self._normalize_progression_text(item)
            for item in previous
        )

    def _demo_default_count(
        self,
        story_text: str,
        premise: ProjectStoryPremise | None,
    ) -> int:
        premise_text = ""
        if premise is not None:
            premise_text = "\n".join(
                [
                    premise.user_story_premise,
                    premise.safe_user_story_summary,
                    *premise.required_story_elements,
                ]
            )
        count = 0
        for default in FORBIDDEN_DEMO_DEFAULTS:
            marker = str(default or "").strip()
            if not marker:
                continue
            if marker in premise_text:
                continue
            count += story_text.count(marker)
        return count

    def _issue(
        self,
        code: str,
        severity: str,
        message: str,
        *,
        evidence: Any = "",
        source_refs: list[str] | None = None,
        user_visible: bool = True,
        suggested_repair_types: list[str] | None = None,
        technical_metadata: dict[str, Any] | None = None,
    ) -> SceneContentQualitySignalIssue:
        return SceneContentQualitySignalIssue(
            code=code,
            severity=severity,
            user_visible=user_visible,
            user_visible_message=message,
            technical_summary=message,
            evidence_excerpt=self._safe_excerpt(evidence),
            source_refs=self._unique_strings(source_refs or []),
            suggested_repair_types=self._unique_strings(suggested_repair_types or []),
            technical_metadata=technical_metadata or {},
        )

    def _pattern_repair_focus(
        self,
        pattern_report: ScenePatternSimilarityReport,
    ) -> list[str]:
        return self._unique_strings(
            [
                focus
                for finding in pattern_report.findings
                for focus in finding.suggested_repair_focus
            ]
        )

    def _pattern_report_metadata(
        self,
        pattern_report: ScenePatternSimilarityReport,
    ) -> dict[str, Any]:
        return {
            "scene_pattern_similarity_report_id": pattern_report.report_id,
            "current_signature_id": pattern_report.current_signature.signature_id,
            "compared_signature_ids": list(pattern_report.compared_signature_ids),
            "structural_similarity_score": pattern_report.structural_similarity_score,
            "text_similarity_score": pattern_report.text_similarity_score,
            "source_scene_ids": self._unique_strings(
                [
                    scene_id
                    for finding in pattern_report.findings
                    for scene_id in finding.source_scene_ids
                ]
            ),
        }

    def _pattern_report(
        self,
        *,
        scene: Scene,
        candidate: SceneRevisionCandidate | None = None,
        recent_scenes: list[Scene] | None,
    ) -> ScenePatternSimilarityReport:
        if candidate is not None:
            content = SceneDraftContent(
                synopsis=candidate.revised_synopsis,
                prose_text=candidate.revised_prose_text,
            )
            trace = scene.generation_trace
            if trace.scene_writing_context is not None:
                report = ScenePatternSimilarityGateService().inspect_draft(
                    content=content,
                    writing_context=trace.scene_writing_context,
                    progression=trace.scene_progression_statement,
                )
            else:
                candidate_scene = Scene(
                    **{
                        **model_to_dict(scene),
                        "content": model_to_dict(content),
                        "synopsis": candidate.revised_synopsis,
                        "prose_text": candidate.revised_prose_text,
                    }
                )
                report = ScenePatternSimilarityGateService().inspect_scene(
                    scene=candidate_scene,
                    recent_scenes=recent_scenes or self._read_scenes(),
                )
            return ScenePatternSimilarityReport(
                **{
                    **model_to_dict(report),
                    "target_type": "scene_revision",
                    "target_id": candidate.revision_id,
                    "scene_id": scene.scene_id,
                }
            )

        inspection = scene.generation_trace.progression_inspection
        if inspection is not None and inspection.scene_pattern_similarity_report:
            try:
                return ScenePatternSimilarityReport(
                    **inspection.scene_pattern_similarity_report
                )
            except Exception:
                pass
        return ScenePatternSimilarityGateService().inspect_scene(
            scene=scene,
            recent_scenes=recent_scenes or self._read_scenes(),
        )

    def _source_refs(self, scene: Scene, premise: ProjectStoryPremise | None) -> list[str]:
        refs = [f"scene:{scene.scene_id}"]
        if premise is not None:
            refs.append(f"project_story_premise:{premise.project_id}")
        if scene.generation_trace.generation_trace_id:
            refs.append(f"scene_generation_trace:{scene.generation_trace.generation_trace_id}")
        return refs

    def _dedupe_issues(
        self,
        issues: list[SceneContentQualitySignalIssue],
    ) -> list[SceneContentQualitySignalIssue]:
        by_code: dict[str, SceneContentQualitySignalIssue] = {}
        for issue in issues:
            current = by_code.get(issue.code)
            if current is None or current.severity != "blocking":
                by_code[issue.code] = issue
        return list(by_code.values())

    def _contains_term(self, text: str, term: str) -> bool:
        raw_term = str(term or "").strip()
        if not raw_term:
            return False
        if PROMPT_FIDELITY_MACHINE_MARKER_RE.fullmatch(raw_term):
            return raw_term in str(text or "")

        normalized_text = self._normalize_prompt_match_text(text)
        normalized_term = self._normalize_prompt_match_text(raw_term)
        if normalized_term and normalized_term in normalized_text and self._contains_anchor_not_negated(text, raw_term):
            return True

        anchors = [
            anchor
            for anchor in self._term_match_anchors(raw_term)
            if len(self._normalize_prompt_match_text(anchor)) >= 2
        ]
        if not anchors:
            return False
        seen = [
            anchor
            for anchor in anchors
            if self._contains_anchor_not_negated(text, anchor)
        ]
        if len(anchors) == 1:
            return bool(seen)
        required_count = min(2, len(anchors))
        return len(seen) >= required_count and (len(seen) / len(anchors)) >= 0.5

    def _prompt_anchor_terms(self, values: list[Any], limit: int) -> list[str]:
        return classify_prompt_anchor_values(values, limit=limit).positive_required_anchors[:limit]

    def _anchor_terms_from_value(self, value: str) -> list[str]:
        return anchor_terms_from_value(value, include_meta=False)

    def _split_cjk_prompt_anchor(self, value: str) -> list[str]:
        result: list[str] = []
        for part in PROMPT_FIDELITY_CJK_SEPARATORS.split(str(value or "")):
            clean = part.strip()
            if not clean:
                continue
            if len(clean) > 12:
                result.extend(
                    item.strip()
                    for item in re.split(r"[，。；：！？、,.!?;:\s]+", clean)
                    if item.strip()
                )
            else:
                result.append(clean)
        return result

    def _term_match_anchors(self, term: str) -> list[str]:
        anchors = [
            anchor
            for anchor in self._anchor_terms_from_value(term)
            if not PROMPT_FIDELITY_MACHINE_MARKER_RE.fullmatch(anchor)
        ]
        return anchors or [term]

    def _is_prompt_anchor_candidate(self, value: str) -> bool:
        return is_prompt_anchor_candidate(value)

    def _is_atomic_prompt_anchor(self, value: str) -> bool:
        return is_prompt_anchor_candidate(value)

    def _normalize_prompt_match_text(self, value: str) -> str:
        return re.sub(
            r"[\s\u3000,.;:!?，。；：！？、\"'`()\[\]{}<>《》“”‘’\-_/]+",
            "",
            str(value or "").casefold(),
        )

    def _contains_anchor_not_negated(self, text: str, anchor: str) -> bool:
        raw_text = str(text or "")
        raw_anchor = str(anchor or "").strip()
        normalized_text = self._normalize_prompt_match_text(raw_text)
        normalized_anchor = self._normalize_prompt_match_text(raw_anchor)
        if not normalized_anchor or normalized_anchor not in normalized_text:
            return False

        lower_text = raw_text.casefold()
        lower_anchor = raw_anchor.casefold()
        spans: list[int] = []
        search_from = 0
        while lower_anchor:
            index = lower_text.find(lower_anchor, search_from)
            if index < 0:
                break
            spans.append(index)
            search_from = index + max(1, len(lower_anchor))

        if not spans:
            return True
        for index in spans:
            prefix = lower_text[max(0, index - 36):index]
            if not any(marker in prefix for marker in PROMPT_FIDELITY_NEGATION_MARKERS):
                return True
        return False

    def _normalize_progression_text(self, value: str) -> str:
        return re.sub(
            r"[\s\u3000,.;:!?，。；：！？\"'`()\[\]{}<>《》]+",
            "",
            str(value or "").casefold(),
        )

    def _text_similarity(self, left: str, right: str) -> float:
        left_norm = self._normalize_progression_text(left)[:2400]
        right_norm = self._normalize_progression_text(right)[:2400]
        if not left_norm or not right_norm:
            return 0.0
        return SequenceMatcher(None, left_norm, right_norm).ratio()

    def _safe_excerpt(self, value: Any, limit: int = 160) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text[:limit]

    def _unique_strings(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result
