from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.continuity import (
    CONTINUITY_VERSION_ID,
    ContinuityCheckResponse,
    ContinuityIssue,
    IssueResolutionOption,
)
from app.backend.models.quality import QualityIssue, QualityReport
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import SceneQualityReport
from app.backend.models.scene_revision import SceneRevisionCandidate
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.apparent_contradiction_gate_service import (
    ApparentContradictionGateService,
)
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.scene_content_quality_signal_service import (
    DEMO_DEFAULT_LEAK,
    PROMPT_FIDELITY_MISSING,
    SCENE_OBJECTIVE_REPEATED,
    SCENE_PREVIOUS_SUMMARY_MISSING,
    SCENE_PROGRESSION_MISSING,
    SCENE_PROGRESSION_STATEMENT_MISSING,
    SCENE_REPETITION_TOO_HIGH,
    SceneContentQualitySignalService,
)
from app.backend.storage.json_store import JsonStore, StorageError


SEMANTIC_CONTINUITY_MAX_OUTPUT_TOKENS = 900
SEMANTIC_CONTINUITY_TIMEOUT_SECONDS = 45
SEMANTIC_CONTINUITY_MAX_ATTEMPTS = 1


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
SECRET_MARKERS = ["s" + "k-", "lsv2_pt", "API_KEY", "LANGSMITH", "DEEPSEEK"]
MEMORY_ID_PATTERN = re.compile(r"\bmemory_[A-Za-z0-9_\-]+")

FORBIDDEN_ACCEPT_CATEGORIES = {
    "forbidden_knowledge",
    "world_hard_rule_direct_conflict",
    "superseded_memory_used",
    "provisional_dependency_changed",
    DEMO_DEFAULT_LEAK,
    SCENE_REPETITION_TOO_HIGH,
}
STRONG_CONFIRMATION_CATEGORIES = {
    "no_source_fact",
    "unverified_old_event",
    "relationship_contradiction",
    "location_scene_state_contradiction",
    "chapter_memory_conflict",
    "premature_information_reveal",
    "chapter_goal_drift",
    PROMPT_FIDELITY_MISSING,
    SCENE_PROGRESSION_MISSING,
    SCENE_PROGRESSION_STATEMENT_MISSING,
    SCENE_OBJECTIVE_REPEATED,
    SCENE_PREVIOUS_SUMMARY_MISSING,
}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class ContinuityContextBuilder:
    def __init__(
        self,
        *,
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
        self.world_canvas_file = self.data_dir / "world_canvas.json"

    def _current_project_id(self, scene: Scene | None = None) -> str:
        if scene is not None and scene.project_id:
            return scene.project_id
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def build_scene_context(self, scene_id: str) -> dict[str, Any]:
        scene = self._load_scene(scene_id)
        return self._build_context(scene=scene, candidate=None)

    def build_revision_context(self, scene_id: str, revision_id: str) -> dict[str, Any]:
        scene = self._load_scene(scene_id)
        candidate = self._find_candidate(scene, revision_id)
        if candidate is None:
            raise StorageError(
                "CONTINUITY_REVISION_MISSING: Scene revision candidate does not exist."
            )
        return self._build_context(scene=scene, candidate=candidate)

    def _build_context(
        self,
        *,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
    ) -> dict[str, Any]:
        target_type = "scene_revision" if candidate else "scene"
        target_id = candidate.revision_id if candidate else scene.scene_id
        target_text = self._target_text(scene, candidate)
        target_extraction = (
            candidate.memory_extraction
            if candidate is not None
            else scene.memory_extraction
        )
        scene_pack = (
            self.repositories.scene_memory_packs.get_by_id(scene.scene_memory_pack_id)
            if scene.scene_memory_pack_id
            else None
        )
        chapter_pack = (
            self.repositories.chapter_memory_packs.get_by_id(scene.chapter_memory_pack_id)
            if scene.chapter_memory_pack_id
            else None
        )
        memory_records = self.repositories.memory.list_all()
        memory_by_id = {
            str(memory.get("memory_id") or ""): dict(memory)
            for memory in memory_records
            if isinstance(memory, dict) and memory.get("memory_id")
        }
        source_memory_ids = self._source_memory_ids(scene, scene_pack, chapter_pack)
        return {
            "_store": self.store,
            "_data_dir": str(self.data_dir),
            "project_id": self._current_project_id(scene),
            "target_type": target_type,
            "target_id": target_id,
            "scene": scene,
            "candidate": candidate,
            "chapter_id": scene.chapter_id,
            "scene_id": scene.scene_id,
            "revision_id": candidate.revision_id if candidate else "",
            "target_text": target_text,
            "target_text_excerpt": self._safe_evidence(target_text, limit=500) or "",
            "target_extraction": model_to_dict(target_extraction),
            "scene_pack": scene_pack or {},
            "chapter_pack": chapter_pack or {},
            "memory_records": memory_records,
            "memory_by_id": memory_by_id,
            "source_memory_ids": source_memory_ids,
            "scenes": self.repositories.scenes.list_all(),
            "events": self.repositories.events.list_all(),
            "state_changes": self.repositories.state_changes.list_all(),
            "characters": self.repositories.characters.list_all(),
            "relationships": self.repositories.relationships.list_all(),
            "chapters": self.repositories.chapters.list_all(),
            "world_canvas": self._read_world_canvas_if_present(),
            "memory_update_plans": self.repositories.memory_update_plans.list_all(),
        }

    def _load_scene(self, scene_id: str) -> Scene:
        raw = self.repositories.scenes.get_by_id(scene_id)
        if raw is None:
            raise StorageError("CONTINUITY_SCENE_MISSING: Scene does not exist.")
        try:
            return Scene(**raw)
        except ValidationError as exc:
            raise StorageError("Scene JSON schema is invalid.") from exc

    def _find_candidate(
        self,
        scene: Scene,
        revision_id: str,
    ) -> SceneRevisionCandidate | None:
        for candidate in scene.revision_history:
            if candidate.revision_id == revision_id:
                return candidate
        return None

    def _target_text(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate | None,
    ) -> str:
        if candidate is not None:
            return "\n".join(
                [
                    candidate.revised_synopsis or "",
                    candidate.revised_prose_text or "",
                ]
            )
        content = scene.content
        synopsis = (content.synopsis if content else scene.synopsis) or scene.synopsis
        prose = (content.prose_text if content else scene.prose_text) or scene.prose_text
        return "\n".join([synopsis or "", prose or ""])

    def _source_memory_ids(
        self,
        scene: Scene,
        scene_pack: dict[str, Any] | None,
        chapter_pack: dict[str, Any] | None,
    ) -> list[str]:
        ids: list[str] = [
            *scene.input_memory_ids,
            *scene.depends_on_provisional_memory_ids,
        ]
        if scene_pack:
            ids.extend(scene_pack.get("must_use_memory_ids") or [])
            ids.extend(scene_pack.get("should_use_memory_ids") or [])
            ids.extend(scene_pack.get("optional_memory_ids") or [])
            ids.extend(scene_pack.get("provisional_memory_ids") or [])
            ids.extend(self._memory_ids_from_pack_context(scene_pack))
        trace = scene.generation_trace
        for item in trace.story_information_list:
            ids.extend(MEMORY_ID_PATTERN.findall(item.content or ""))
        ordered = trace.ordered_story_information_package
        if ordered is not None:
            for entries in [
                ordered.opening_context,
                ordered.scene_progression,
                ordered.character_turns,
                ordered.required_reveals,
                ordered.emotional_beats,
                ordered.ending_beat,
            ]:
                for text in entries:
                    ids.extend(MEMORY_ID_PATTERN.findall(text or ""))
        return _unique_strings(ids)

    def _memory_ids_from_pack_context(self, pack: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for key in [
            "world_context",
            "character_context",
            "relationship_context",
            "event_context",
            "framework_context",
            "must_use_context",
            "should_use_context",
            "optional_context",
        ]:
            for item in pack.get(key) or []:
                if isinstance(item, dict) and item.get("memory_id"):
                    ids.append(str(item["memory_id"]))
        return ids

    def _read_world_canvas_if_present(self) -> dict[str, Any]:
        if not self.store.exists(self.world_canvas_file):
            return {}
        data = self.store.read(self.world_canvas_file)
        return dict(data) if isinstance(data, dict) else {}

    def _safe_evidence(self, value: Any, limit: int = 200) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        for marker in SECRET_MARKERS:
            if marker in text:
                return "[redacted-secret-marker]"
        return text[:limit]


class RuleBasedContinuityChecker:
    def check(self, context: dict[str, Any], mode: str = "manual") -> list[ContinuityIssue]:
        issues: list[ContinuityIssue] = []
        issues.extend(self._memory_pack_issues(context))
        issues.extend(self._temporary_dependency_issues(context))
        issues.extend(self._superseded_memory_issues(context))
        issues.extend(self._provisional_dependency_changed_issues(context))
        issues.extend(self._forbidden_knowledge_issues(context))
        issues.extend(self._world_hard_rule_issues(context))
        issues.extend(self._relationship_issues(context))
        issues.extend(self._location_issues(context))
        issues.extend(self._chapter_memory_conflict_issues(context))
        issues.extend(self._content_quality_issues(context))
        return self._dedupe_issues(issues)

    def _memory_pack_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        scene: Scene = context["scene"]
        scene_pack = context.get("scene_pack") or {}
        issues: list[ContinuityIssue] = []
        if not scene.scene_memory_pack_id or not scene_pack:
            issues.append(
                self._issue(
                    context,
                    "missing_or_stale_memory_pack",
                    "warning",
                    "当前幕没有可用的 Scene Memory Pack，建议先刷新记忆包再确认。",
                    technical="Scene.scene_memory_pack_id is empty or missing from repository.",
                )
            )
            return issues
        if scene_pack.get("status") == "stale":
            issues.append(
                self._issue(
                    context,
                    "missing_or_stale_memory_pack",
                    "warning",
                    "当前 Scene Memory Pack 已过期，建议刷新后再确认。",
                    technical=f"SceneMemoryPack.status=stale: {scene.scene_memory_pack_id}",
                )
            )
        for gap in scene_pack.get("retrieval_gaps") or []:
            if not isinstance(gap, dict):
                continue
            if gap.get("gap_type") == "stale_pack_source":
                issues.append(
                    self._issue(
                        context,
                        "missing_or_stale_memory_pack",
                        "warning",
                        str(gap.get("message") or "记忆包引用了过期来源。"),
                        technical="SceneMemoryPack retrieval gap: stale_pack_source.",
                    )
                )
        return issues

    def _temporary_dependency_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        scene: Scene = context["scene"]
        if not (
            scene.depends_on_provisional_scene_ids
            or scene.depends_on_provisional_memory_ids
        ):
            return []
        return [
            self._issue(
                context,
                "temporary_confirmed_dependency_warning",
                "warning",
                "当前幕依赖临时确认的前序事实；正式确认前建议复核这些临时来源。",
                technical="Scene has provisional dependency ids.",
                source_scene_ids=scene.depends_on_provisional_scene_ids,
                source_memory_ids=scene.depends_on_provisional_memory_ids,
            )
        ]

    def _superseded_memory_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        memory_by_id = context.get("memory_by_id") or {}
        superseded = [
            memory_id
            for memory_id in context.get("source_memory_ids") or []
            if (memory_by_id.get(memory_id) or {}).get("status") == "superseded"
        ]
        if not superseded:
            return []
        return [
            self._issue(
                context,
                "superseded_memory_used",
                "blocking",
                "当前幕仍在使用已被替代的记忆，不能把它当作当前客观事实确认。",
                technical="Target source refs include MemoryRecord.status=superseded.",
                source_memory_ids=superseded,
            )
        ]

    def _provisional_dependency_changed_issues(
        self,
        context: dict[str, Any],
    ) -> list[ContinuityIssue]:
        scene: Scene = context["scene"]
        memory_by_id = context.get("memory_by_id") or {}
        scenes_by_id = {
            str(item.get("scene_id") or ""): item
            for item in context.get("scenes") or []
            if isinstance(item, dict)
        }
        changed_memory_ids = []
        for memory_id in scene.depends_on_provisional_memory_ids:
            memory = memory_by_id.get(memory_id) or {}
            status = str(memory.get("status") or "")
            if not memory or status in {"superseded", "rejected"}:
                changed_memory_ids.append(memory_id)
        changed_scene_ids = []
        for source_scene_id in scene.depends_on_provisional_scene_ids:
            source_scene = scenes_by_id.get(source_scene_id) or {}
            status = str(source_scene.get("status") or "")
            active_revision_id = str(source_scene.get("active_revision_id") or "")
            if status in {
                "revised",
                "rejected",
                "needs_review",
                "continuity_recheck",
            } or self._has_unconfirmed_active_revision(source_scene, active_revision_id):
                changed_scene_ids.append(source_scene_id)
        if scene.status == "continuity_recheck" and (
            scene.depends_on_provisional_scene_ids
            or scene.depends_on_provisional_memory_ids
        ):
            changed_scene_ids.extend(scene.depends_on_provisional_scene_ids)
            changed_memory_ids.extend(scene.depends_on_provisional_memory_ids)
        changed_memory_ids = _unique_strings(changed_memory_ids)
        changed_scene_ids = _unique_strings(changed_scene_ids)
        if not changed_memory_ids and not changed_scene_ids:
            return []
        return [
            self._issue(
                context,
                "provisional_dependency_changed",
                "blocking",
                "当前幕依赖的临时事实已经变化或被否定，需要先复核来源再确认。",
                technical="Provisional dependency source is superseded/rejected/revised or scene is marked continuity_recheck.",
                source_memory_ids=changed_memory_ids,
                source_scene_ids=changed_scene_ids,
            )
        ]

    def _has_unconfirmed_active_revision(
        self,
        source_scene: dict[str, Any],
        active_revision_id: str,
    ) -> bool:
        if not active_revision_id:
            return False
        for candidate in source_scene.get("revision_history") or []:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("revision_id") or "") != active_revision_id:
                continue
            return str(candidate.get("status") or "") != "confirmed"
        return True

    def _forbidden_knowledge_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        text = context.get("target_text") or ""
        scene: Scene = context["scene"]
        issues: list[ContinuityIssue] = []
        ordered = scene.generation_trace.ordered_story_information_package
        if ordered is not None:
            for forbidden in ordered.do_not_include:
                phrase = str(forbidden or "").strip()
                if phrase and phrase in text:
                    issues.append(
                        self._issue(
                            context,
                            "do_not_include_violation",
                            "blocking",
                            "正文包含本幕明确禁止提前出现的信息。",
                            technical="ordered_story_information_package.do_not_include matched target text.",
                            evidence=phrase,
                        )
                    )
        for character in context.get("characters") or []:
            if not isinstance(character, dict):
                continue
            profile = character.get("profile") or {}
            for forbidden in profile.get("forbidden_knowledge") or []:
                phrase = str(forbidden or "").strip()
                if phrase and phrase in text:
                    issues.append(
                        self._issue(
                            context,
                            "forbidden_knowledge",
                            "blocking",
                            "角色持有了当前设定中禁止获得的知识。",
                            technical="Character.profile.forbidden_knowledge matched target text.",
                            evidence=phrase,
                            source_character_ids=[str(character.get("character_id") or "")],
                        )
                    )
        return issues

    def _world_hard_rule_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        text = (context.get("target_text") or "").lower()
        hard_rules = [
            rule
            for rule in (context.get("world_canvas") or {}).get("hard_rules") or []
            if isinstance(rule, dict)
        ]
        hard_rule_texts = [
            f"{rule.get('rule_id', '')} {rule.get('statement', '')}".lower()
            for rule in hard_rules
        ]
        conflict = False
        if self._has_midnight_only_rule(hard_rule_texts) and self._claims_non_midnight_trigger(text):
            conflict = True
        if self._has_no_free_memory_creation_rule(hard_rule_texts) and self._claims_free_memory_creation(text):
            conflict = True
        if self._has_no_free_memory_reversal_rule(hard_rule_texts) and self._claims_free_memory_reversal(text):
            conflict = True
        from app.backend.services.world_rule_timing import (
            claims_premature_period_exchange,
            has_period_bound_exchange_rule,
        )

        if has_period_bound_exchange_rule(hard_rule_texts) and claims_premature_period_exchange(text):
            conflict = True
        if any(marker in text for marker in ["ignore hard rule", "break hard rule", "无视硬规则", "打破硬规则"]):
            conflict = True
        if not conflict:
            return []
        return [
            self._issue(
                context,
                "world_hard_rule_direct_conflict",
                "blocking",
                "当前内容与世界画布硬规则直接冲突，不能直接接受。",
                technical="Target text triggered hard-rule conflict markers.",
                evidence=hard_rules[0].get("statement") if hard_rules else "",
            )
        ]

    def _relationship_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        text = (context.get("target_text") or "").lower()
        extraction = context.get("target_extraction") or {}
        relationships = {
            str(item.get("relationship_id") or ""): item
            for item in context.get("relationships") or []
            if isinstance(item, dict) and item.get("status") == "confirmed"
        }
        issues: list[ContinuityIssue] = []
        marker_conflict = any(
            marker in text
            for marker in ["relationship contradiction", "relationship_conflict", "关系矛盾"]
        )
        if marker_conflict and relationships:
            first_id = next(iter(relationships))
            issues.append(
                self._issue(
                    context,
                    "relationship_contradiction",
                    "blocking",
                    "当前内容与已确认的关系状态明显冲突，需要解释或处理。",
                    technical="Target text includes relationship contradiction marker.",
                    source_relationship_ids=[first_id],
                )
            )
        for change in extraction.get("relationship_changes") or []:
            if not isinstance(change, dict):
                continue
            relationship_id = str(change.get("relationship_id") or "")
            current = relationships.get(relationship_id)
            if not current:
                continue
            next_state = str(
                change.get("state")
                or (change.get("after") or {}).get("state")
                or ""
            ).strip()
            reason = str(change.get("reason") or change.get("summary") or "").strip()
            if next_state and next_state != str(current.get("state") or "") and not reason:
                issues.append(
                    self._issue(
                        context,
                        "relationship_contradiction",
                        "blocking",
                        "关系状态变更缺少可见原因，和已确认关系状态冲突。",
                        technical="relationship_changes changed confirmed state without reason.",
                        source_relationship_ids=[relationship_id],
                    )
                )
        return issues

    def _location_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        scene: Scene = context["scene"]
        text = (context.get("target_text") or "").lower()
        extraction = context.get("target_extraction") or {}
        issues: list[ContinuityIssue] = []
        if any(marker in text for marker in ["location contradiction", "地点矛盾"]):
            issues.append(
                self._issue(
                    context,
                    "location_scene_state_contradiction",
                    "blocking",
                    "当前内容与本幕地点状态直接冲突，需要解释或处理。",
                    technical="Target text includes location contradiction marker.",
                )
            )
        scene_location = str(scene.location or "").strip()
        if not scene_location:
            return issues
        for event in extraction.get("event_summary") or []:
            if not isinstance(event, dict):
                continue
            location_id = str(event.get("location_id") or "").strip()
            cause = str(event.get("cause") or "").lower()
            if (
                location_id
                and location_id != scene_location
                and not any(marker in cause for marker in ["travel", "move", "moved", "移动", "转场"])
            ):
                issues.append(
                    self._issue(
                        context,
                        "location_scene_state_contradiction",
                        "blocking",
                        "事件地点与当前幕地点不一致，且没有转场原因。",
                        technical="event_summary.location_id differs from Scene.location without movement cause.",
                        source_event_ids=[str(event.get("event_id") or "")],
                    )
                )
        return issues

    def _chapter_memory_conflict_issues(
        self,
        context: dict[str, Any],
    ) -> list[ContinuityIssue]:
        text = context.get("target_text") or ""
        scene_pack = context.get("scene_pack") or {}
        issues: list[ContinuityIssue] = []
        for item in scene_pack.get("forbidden_or_conflict_context") or []:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or "").strip()
            if len(summary) >= 8 and summary in text:
                issues.append(
                    self._issue(
                        context,
                        "chapter_memory_conflict",
                        "blocking",
                        "当前内容使用了记忆包标记为冲突或禁用的上下文。",
                        technical="SceneMemoryPack.forbidden_or_conflict_context summary matched target text.",
                        evidence=summary,
                        source_memory_ids=[str(item.get("memory_id") or "")],
                    )
                )
        return issues

    def _content_quality_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        store = context.get("_store")
        data_dir_value = context.get("_data_dir")
        service = SceneContentQualitySignalService(
            store=store if isinstance(store, JsonStore) else None,
            data_dir=Path(data_dir_value) if data_dir_value else None,
        )
        report = service.evaluate_scene(
            scene=context["scene"],
            candidate=context.get("candidate"),
            project_id=str(context.get("project_id") or LOCAL_PROJECT_ID),
        )
        issues: list[ContinuityIssue] = []
        for signal in report.issues:
            if signal.severity != "blocking":
                continue
            if signal.code not in {
                PROMPT_FIDELITY_MISSING,
                DEMO_DEFAULT_LEAK,
                SCENE_REPETITION_TOO_HIGH,
                SCENE_PROGRESSION_MISSING,
                SCENE_PROGRESSION_STATEMENT_MISSING,
                SCENE_OBJECTIVE_REPEATED,
                SCENE_PREVIOUS_SUMMARY_MISSING,
            }:
                continue
            issues.append(
                self._issue(
                    context,
                    signal.code,
                    "blocking",
                    signal.user_visible_message or signal.code,
                    technical=signal.technical_summary or signal.code,
                    evidence=signal.evidence_excerpt,
                    source_scene_ids=[context.get("scene_id") or ""],
                )
            )
        return issues

    def _issue(
        self,
        context: dict[str, Any],
        category: str,
        severity: str,
        message: str,
        *,
        technical: str = "",
        evidence: Any = "",
        source_memory_ids: list[str] | None = None,
        source_event_ids: list[str] | None = None,
        source_scene_ids: list[str] | None = None,
        source_character_ids: list[str] | None = None,
        source_relationship_ids: list[str] | None = None,
    ) -> ContinuityIssue:
        source_memory_ids = _unique_strings(source_memory_ids or [])
        source_event_ids = _unique_strings(source_event_ids or [])
        source_scene_ids = _unique_strings(source_scene_ids or [])
        source_character_ids = _unique_strings(source_character_ids or [])
        source_relationship_ids = _unique_strings(source_relationship_ids or [])
        target_id = context.get("target_id") or ""
        digest = _stable_digest(
            [
                target_id,
                category,
                technical,
                "|".join(source_memory_ids),
                "|".join(source_event_ids),
                "|".join(source_scene_ids),
                "|".join(source_character_ids),
                "|".join(source_relationship_ids),
            ]
        )
        issue_id = f"continuity_{category}_{digest}"
        acceptance_policy = _acceptance_policy_for_category(category)
        is_blocking = severity == "blocking"
        timestamp = now_iso()
        issue = ContinuityIssue(
            issue_id=issue_id,
            project_id=str(context.get("project_id") or LOCAL_PROJECT_ID),
            target_type=context.get("target_type") or "scene",
            target_id=target_id,
            chapter_id=context.get("chapter_id") or "",
            scene_id=context.get("scene_id") or "",
            revision_id=context.get("revision_id") or "",
            category=category,
            severity=severity,
            status="open",
            acceptance_policy=acceptance_policy,
            user_visible_message=message,
            technical_summary=technical,
            evidence_text=self._safe_evidence(evidence) or "",
            source_memory_ids=source_memory_ids,
            source_event_ids=source_event_ids,
            source_scene_ids=source_scene_ids,
            source_character_ids=source_character_ids,
            source_relationship_ids=source_relationship_ids,
            blocks_final_confirmation=is_blocking,
            blocks_state_changing_revision_confirmation=is_blocking,
            requires_explicit_acceptance=(
                is_blocking or severity == "requires_user_confirmation"
            ),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=CONTINUITY_VERSION_ID,
        )
        return ContinuityIssue(
            **{
                **model_to_dict(issue),
                "suggested_options": [
                    model_to_dict(option)
                    for option in _resolution_options_for_issue(issue)
                ],
            }
        )

    def _dedupe_issues(self, issues: list[ContinuityIssue]) -> list[ContinuityIssue]:
        by_id: dict[str, ContinuityIssue] = {}
        for issue in issues:
            by_id[issue.issue_id] = issue
        return list(by_id.values())

    def _safe_evidence(self, value: Any, limit: int = 200) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        for marker in SECRET_MARKERS:
            if marker in text:
                return "[redacted-secret-marker]"
        return text[:limit]

    def _has_midnight_only_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "midnight" in text
            or "零点" in text
            or "午夜" in text
            for text in hard_rule_texts
        )

    def _claims_non_midnight_trigger(self, text: str) -> bool:
        trigger_markers = ["触发", "鸣响", "钟声", "异常", "trigger", "ring"]
        non_midnight_markers = [
            "随机触发",
            "随时触发",
            "任意时间触发",
            "白天触发",
            "非零点触发",
            "不需要零点",
            "daytime",
            "randomly trigger",
        ]
        return any(marker in text for marker in trigger_markers) and any(
            marker in text for marker in non_midnight_markers
        )

    def _has_no_free_memory_creation_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "memory_cost" in text
            or (
                "新记忆" in text
                and any(marker in text for marker in ["不会", "不能", "不允许"])
            )
            for text in hard_rule_texts
        )

    def _claims_free_memory_creation(self, text: str) -> bool:
        return any(
            marker in text
            for marker in [
                "凭空获得新记忆",
                "凭空创造新记忆",
                "创造新记忆",
                "植入新记忆",
                "free memory",
            ]
        )

    def _has_no_free_memory_reversal_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "no_free_reversal" in text
            or (
                "无代价" in text
                and any(marker in text for marker in ["撤销", "恢复", "找回", "记忆"])
            )
            for text in hard_rule_texts
        )

    def _claims_free_memory_reversal(self, text: str) -> bool:
        return any(
            marker in text
            for marker in [
                "无代价恢复",
                "无代价撤销",
                "直接恢复全部记忆",
                "完全找回记忆且没有代价",
                "restore memory without",
            ]
        )


class ContinuityCheckAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def check(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        status = self.model_gateway.validate_model_config()
        if not status.configured:
            return []
        semantic_context = self._semantic_context(context)
        try:
            result = self.model_gateway.generate_json(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a continuity checking agent. Return only JSON with "
                            "an issues array. Only use these semantic categories when "
                            "supported by evidence: no_source_fact, unverified_old_event, "
                            "premature_information_reveal, chapter_goal_drift. Do not "
                            "rewrite story prose or canon."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            semantic_context,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    },
                ],
                schema_hint={
                    "kind": "continuity_semantic_check",
                    "context": semantic_context,
                    "output_shape": {
                        "issues": [
                            {
                                "category": "no_source_fact",
                                "severity": "blocking",
                                "user_visible_message": "",
                                "technical_summary": "",
                                "evidence_text": "",
                                "source_memory_ids": [],
                                "source_event_ids": [],
                                "source_scene_ids": [],
                                "source_character_ids": [],
                                "source_relationship_ids": [],
                            }
                        ]
                    },
                },
                options={
                    "temperature": 0.0,
                    "max_output_tokens": SEMANTIC_CONTINUITY_MAX_OUTPUT_TOKENS,
                    "timeout_seconds": SEMANTIC_CONTINUITY_TIMEOUT_SECONDS,
                    "max_attempts": SEMANTIC_CONTINUITY_MAX_ATTEMPTS,
                },
                agent_role="quality_check",
                service_name="ContinuityCheckAgent",
                operation_name="semantic_scene_continuity_check",
            )
        except (ModelCallError, ModelJsonParseError, StorageError):
            return []
        issues: list[ContinuityIssue] = []
        checker = RuleBasedContinuityChecker()
        for item in result.data.get("issues") or []:
            if not isinstance(item, dict):
                continue
            if not self._semantic_issue_has_evidence(item):
                continue
            category = str(item.get("category") or "no_source_fact")
            severity = str(item.get("severity") or "warning")
            if severity not in {"info", "warning", "blocking", "requires_user_confirmation"}:
                severity = "warning"
            issues.append(
                checker._issue(
                    context,
                    category,
                    severity,
                    str(item.get("user_visible_message") or item.get("message") or "发现连续性疑点。"),
                    technical=str(item.get("technical_summary") or "Semantic continuity check."),
                    evidence=item.get("evidence_text") or "",
                    source_memory_ids=item.get("source_memory_ids") or [],
                    source_event_ids=item.get("source_event_ids") or [],
                    source_scene_ids=item.get("source_scene_ids") or [],
                    source_character_ids=item.get("source_character_ids") or [],
                    source_relationship_ids=item.get("source_relationship_ids") or [],
                )
            )
        return issues

    def _semantic_issue_has_evidence(self, item: dict[str, Any]) -> bool:
        if str(item.get("evidence_text") or item.get("evidence") or "").strip():
            return True
        for key in (
            "source_memory_ids",
            "source_event_ids",
            "source_scene_ids",
            "source_character_ids",
            "source_relationship_ids",
        ):
            values = item.get(key)
            if isinstance(values, list) and any(str(value or "").strip() for value in values):
                return True
        return False

    def _semantic_context(self, context: dict[str, Any]) -> dict[str, Any]:
        scene: Scene = context["scene"]
        return {
            "target_type": context.get("target_type"),
            "target_id": context.get("target_id"),
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "scene_index": scene.scene_index,
            "target_text_excerpt": context.get("target_text_excerpt", ""),
            "scene_goal": scene.goal,
            "location": scene.location,
            "source_memory_ids": context.get("source_memory_ids", [])[:20],
            "recent_event_summaries": [
                {
                    "event_id": event.get("event_id"),
                    "summary": str(event.get("summary") or "")[:160],
                    "status": event.get("status"),
                }
                for event in context.get("events", [])[:12]
                if isinstance(event, dict)
            ],
            "active_memory_summaries": [
                {
                    "memory_id": memory.get("memory_id"),
                    "summary": str(memory.get("summary") or "")[:180],
                    "status": memory.get("status"),
                    "truth_status": memory.get("truth_status"),
                    "objective_truth": memory.get("objective_truth"),
                }
                for memory in context.get("memory_records", [])[:24]
                if isinstance(memory, dict)
            ],
            "semantic_issue_categories": [
                "no_source_fact",
                "unverified_old_event",
                "premature_information_reveal",
                "chapter_goal_drift",
            ],
            "chapter": _current_chapter_context(context),
        }


class ContinuityGateService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        model_gateway: ModelGatewayService | None = None,
        repositories: RepositoryBundle | None = None,
        context_builder: ContinuityContextBuilder | None = None,
        rule_checker: RuleBasedContinuityChecker | None = None,
        apparent_contradiction_gate_service: ApparentContradictionGateService | None = None,
        semantic_agent: Any | None = None,
        enable_semantic_agent: bool = True,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.context_builder = context_builder or ContinuityContextBuilder(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.rule_checker = rule_checker or RuleBasedContinuityChecker()
        self.apparent_contradiction_gate_service = (
            apparent_contradiction_gate_service
            or ApparentContradictionGateService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.semantic_agent = semantic_agent
        if self.semantic_agent is None and enable_semantic_agent:
            self.semantic_agent = ContinuityCheckAgent(self.model_gateway)

    def check_scene(self, scene_id: str, mode: str = "manual") -> ContinuityCheckResponse:
        context = self.context_builder.build_scene_context(scene_id)
        return self._check_context(context, mode=mode)

    def check_scene_revision(
        self,
        scene_id: str,
        revision_id: str,
        mode: str = "manual",
    ) -> ContinuityCheckResponse:
        context = self.context_builder.build_revision_context(scene_id, revision_id)
        return self._check_context(context, mode=mode)

    def list_issues(
        self,
        *,
        scene_id: str | None = None,
        target_type: str | None = None,
        status: str | None = None,
    ) -> list[ContinuityIssue]:
        issues: list[ContinuityIssue] = []
        for raw in self.repositories.continuity_issues.list_all():
            try:
                issue = ContinuityIssue(**raw)
            except ValidationError as exc:
                raise StorageError("ContinuityIssue JSON schema is invalid.") from exc
            if scene_id and issue.scene_id != scene_id:
                continue
            if target_type and issue.target_type != target_type:
                continue
            if status and issue.status != status:
                continue
            issues.append(issue)
        return issues

    def get_issue(self, issue_id: str) -> ContinuityIssue:
        raw = self.repositories.continuity_issues.get_by_id(issue_id)
        if raw is None:
            raise StorageError("CONTINUITY_ISSUE_MISSING: Continuity issue does not exist.")
        try:
            return ContinuityIssue(**raw)
        except ValidationError as exc:
            raise StorageError("ContinuityIssue JSON schema is invalid.") from exc

    def accept_issue(self, issue_id: str, user_input: str) -> tuple[ContinuityIssue, dict[str, Any]]:
        issue = self.get_issue(issue_id)
        clean_input = (user_input or "").strip()
        if not clean_input:
            raise StorageError("CONTINUITY_ACCEPT_REASON_REQUIRED: 接受连续性问题必须填写理由。")
        if issue.acceptance_policy == "forbidden":
            raise StorageError(
                "CONTINUITY_ISSUE_ACCEPT_FORBIDDEN: 这个连续性问题不能直接接受，必须先处理来源或改成非客观事实。"
            )
        timestamp = now_iso()
        accepted = ContinuityIssue(
            **{
                **model_to_dict(issue),
                "status": "accepted",
                "updated_at": timestamp,
            }
        )
        self.repositories.continuity_issues.upsert(
            model_to_dict(accepted),
            "issue_id",
        )
        decision = self._write_decision(
            decision_type="accept_continuity_issue",
            target_type="continuity_issue",
            target_id=issue.issue_id,
            user_input=clean_input,
        )
        return accepted, decision

    def mark_issue_resolved(
        self,
        issue_id: str,
        user_input: str = "",
    ) -> ContinuityIssue:
        issue = self.get_issue(issue_id)
        resolved = ContinuityIssue(
            **{
                **model_to_dict(issue),
                "status": "resolved",
                "updated_at": now_iso(),
            }
        )
        self.repositories.continuity_issues.upsert(model_to_dict(resolved), "issue_id")
        self._write_decision(
            decision_type="resolve_continuity_issue",
            target_type="continuity_issue",
            target_id=issue.issue_id,
            user_input=user_input or "连续性问题已处理。",
        )
        return resolved

    def _check_context(
        self,
        context: dict[str, Any],
        mode: str,
    ) -> ContinuityCheckResponse:
        issues = [
            *self.rule_checker.check(context, mode=mode),
            *self._semantic_issues(context),
        ]
        gate_result = self.apparent_contradiction_gate_service.evaluate_issues(
            continuity_context=context,
            issues=issues,
            mode=mode,
        )
        issues = self._filter_unauditable_semantic_issues(gate_result.gated_issues)
        stored = self._persist_issues(context, issues)
        response = self._response_for_issues(
            context=context,
            issues=stored,
            mode=mode,
        )
        self._update_quality_fields(context, response)
        return response

    def _semantic_issues(self, context: dict[str, Any]) -> list[ContinuityIssue]:
        if self.semantic_agent is None:
            return []
        return self.semantic_agent.check(context)

    def _filter_unauditable_semantic_issues(
        self,
        issues: list[ContinuityIssue],
    ) -> list[ContinuityIssue]:
        return [
            issue
            for issue in issues
            if not self._is_unauditable_semantic_issue(issue)
        ]

    def _is_unauditable_semantic_issue(self, issue: ContinuityIssue) -> bool:
        technical = str(issue.technical_summary or "").strip().casefold()
        if not technical.startswith("semantic continuity check"):
            return False
        if str(issue.evidence_text or "").strip():
            return False
        return not any(
            [
                issue.source_memory_ids,
                issue.source_event_ids,
                issue.source_scene_ids,
                issue.source_character_ids,
                issue.source_relationship_ids,
            ]
        )

    def _persist_issues(
        self,
        context: dict[str, Any],
        detected: list[ContinuityIssue],
    ) -> list[ContinuityIssue]:
        existing_raw = self.repositories.continuity_issues.list_all()
        target_type = context.get("target_type") or "scene"
        target_id = context.get("target_id") or ""
        existing_by_id = {
            str(item.get("issue_id") or ""): dict(item)
            for item in existing_raw
            if isinstance(item, dict) and item.get("issue_id")
        }
        timestamp = now_iso()
        detected_ids = {issue.issue_id for issue in detected}
        for issue_id, current in list(existing_by_id.items()):
            if (
                current.get("target_type") == target_type
                and current.get("target_id") == target_id
                and current.get("status") == "open"
                and issue_id not in detected_ids
            ):
                current["status"] = "resolved"
                current["updated_at"] = timestamp
                current["resolution_lifecycle_status"] = (
                    current.get("resolution_lifecycle_status")
                    or "superseded_by_recheck"
                )
                current["resolution_lifecycle_message"] = (
                    current.get("resolution_lifecycle_message")
                    or "A later continuity gate run did not detect this issue for the same target."
                )
                existing_by_id[issue_id] = current
        for issue in detected:
            current = existing_by_id.get(issue.issue_id)
            if current and current.get("status") in {"resolved", "accepted", "dismissed"}:
                continue
            data = model_to_dict(issue)
            if current:
                data["created_at"] = current.get("created_at") or issue.created_at
            data["updated_at"] = timestamp
            existing_by_id[issue.issue_id] = data
        self.repositories.continuity_issues.write_all(list(existing_by_id.values()))
        return self.list_issues(
            scene_id=context.get("scene_id"),
            target_type=target_type,
        )

    def _response_for_issues(
        self,
        *,
        context: dict[str, Any],
        issues: list[ContinuityIssue],
        mode: str,
    ) -> ContinuityCheckResponse:
        checked_at = now_iso()
        continuity_gate_run_id = self._continuity_gate_run_id(
            context=context,
            mode=mode,
            checked_at=checked_at,
        )
        active = [
            issue
            for issue in issues
            if issue.status in {"open", "accepted"}
            and issue.target_type == context.get("target_type")
            and issue.target_id == context.get("target_id")
        ]
        blocking = [
            issue
            for issue in active
            if issue.status == "open" and self._blocks_mode(issue, mode)
        ]
        warning = [
            issue
            for issue in active
            if issue.status == "open"
            and issue.severity in {"warning", "requires_user_confirmation"}
            and issue.issue_id not in {item.issue_id for item in blocking}
        ]
        accepted = [issue for issue in active if issue.status == "accepted"]
        return ContinuityCheckResponse(
            success=True,
            target_type=context.get("target_type") or "scene",
            target_id=context.get("target_id") or "",
            mode=mode,
            passed=not blocking,
            continuity_passed=not blocking,
            continuity_checked=True,
            continuity_gate_run_id=continuity_gate_run_id,
            continuity_checked_at=checked_at,
            issues=active,
            blocking_issue_ids=[issue.issue_id for issue in blocking],
            warning_issue_ids=[issue.issue_id for issue in warning],
            accepted_issue_ids=[issue.issue_id for issue in accepted],
            requires_user_confirmation=bool(blocking),
            summary=self._summary(blocking, warning, accepted),
        )

    def _continuity_gate_run_id(
        self,
        *,
        context: dict[str, Any],
        mode: str,
        checked_at: str,
    ) -> str:
        target_type = str(context.get("target_type") or "scene")
        target_id = str(context.get("target_id") or context.get("scene_id") or "target")
        safe_target_id = re.sub(r"[^A-Za-z0-9_]+", "_", target_id).strip("_") or "target"
        digest = hashlib.sha256(
            json.dumps(
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "scene_id": context.get("scene_id") or "",
                    "revision_id": context.get("revision_id") or "",
                    "mode": mode,
                    "checked_at": checked_at,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        return f"continuity_gate_run_{target_type}_{safe_target_id}_{digest}"

    def _blocks_mode(self, issue: ContinuityIssue, mode: str) -> bool:
        if issue.status in {"resolved", "accepted", "dismissed"}:
            return False
        if mode == "manual":
            return issue.severity == "blocking"
        if mode == "temporary_confirmation":
            return issue.category in {
                "forbidden_knowledge",
                "world_hard_rule_direct_conflict",
            } and issue.severity == "blocking"
        if mode == "revision_confirmation":
            return (
                issue.blocks_state_changing_revision_confirmation
                or issue.requires_explicit_acceptance
                or issue.severity in {"blocking", "requires_user_confirmation"}
            )
        return (
            issue.blocks_final_confirmation
            or issue.requires_explicit_acceptance
            or issue.severity in {"blocking", "requires_user_confirmation"}
        )

    def _update_quality_fields(
        self,
        context: dict[str, Any],
        response: ContinuityCheckResponse,
    ) -> None:
        target_type = context.get("target_type") or "scene"
        target_id = context.get("target_id") or ""
        reports = self.repositories.quality_reports.list_all()
        report = self._latest_quality_report(reports, target_type, target_id)
        if report is None:
            report = QualityReport(
                quality_report_id=self._next_quality_report_id(reports, target_type, target_id),
                project_id=str(context.get("project_id") or LOCAL_PROJECT_ID),
                target_type=target_type,
                target_id=target_id,
                scene_id=context.get("scene_id") or "",
                revision_id=context.get("revision_id") or "",
                passed=response.continuity_passed,
                requires_user_confirmation=response.requires_user_confirmation,
                continuity_checked=response.continuity_checked,
                continuity_gate_run_id=response.continuity_gate_run_id,
                continuity_checked_at=response.continuity_checked_at,
                continuity_passed=response.continuity_passed,
                semantic_check_status="not_run",
                summary=response.summary,
                generated_by="continuity_gate_service",
                version_id="quality_m9_001",
                created_at=now_iso(),
            )
            reports.append(model_to_dict(report))
        updated = dict(model_to_dict(report))
        updated["continuity_passed"] = response.continuity_passed
        updated["continuity_checked"] = response.continuity_checked
        updated["continuity_gate_run_id"] = response.continuity_gate_run_id
        updated["continuity_checked_at"] = response.continuity_checked_at
        updated["continuity_issue_ids"] = [
            issue.issue_id
            for issue in response.issues
            if issue.status in {"open", "accepted"}
        ]
        updated["blocking_continuity_issue_ids"] = response.blocking_issue_ids
        updated["accepted_continuity_issue_ids"] = response.accepted_issue_ids
        target_continuity_issue_ids = {
            issue.issue_id
            for issue in response.issues
        } | set(updated.get("continuity_issue_ids") or []) | set(
            updated.get("blocking_continuity_issue_ids") or []
        ) | set(updated.get("accepted_continuity_issue_ids") or [])
        preserved_warnings = [
            issue
            for issue in report.warnings
            if not self._is_continuity_quality_issue(issue)
            and not (
                issue.related_object_type == "continuity_issue"
                and issue.related_object_id in target_continuity_issue_ids
            )
        ]
        preserved_blocking = [
            issue
            for issue in report.blocking_issues
            if not self._is_continuity_quality_issue(issue)
            and not (
                issue.related_object_type == "continuity_issue"
                and issue.related_object_id in target_continuity_issue_ids
            )
        ]
        non_continuity_requires_confirmation = any(
            issue.severity in {"needs_user_confirmation", "requires_user_confirmation"}
            for issue in [*preserved_warnings, *preserved_blocking]
        )
        updated["warnings"] = [model_to_dict(issue) for issue in preserved_warnings]
        updated["blocking_issues"] = [model_to_dict(issue) for issue in preserved_blocking]
        updated["requires_user_confirmation"] = (
            non_continuity_requires_confirmation or response.requires_user_confirmation
        )
        updated["passed"] = not preserved_blocking and response.continuity_passed
        updated["summary"] = response.summary
        self.repositories.quality_reports.write_all(
            [
                updated
                if item.get("quality_report_id") == updated["quality_report_id"]
                else item
                for item in reports
            ]
        )
        self._update_embedded_quality(context, QualityReport(**updated))

    def _is_continuity_quality_issue(self, issue: QualityIssue) -> bool:
        category = str(issue.category or "").casefold()
        return bool(
            issue.related_object_type == "continuity_issue"
            or category.startswith("continuity_")
        )

    def _refresh_quality_for_target(self, target_type: str, target_id: str) -> None:
        try:
            if target_type == "scene_revision":
                for raw in self.repositories.scenes.list_all():
                    if not isinstance(raw, dict):
                        continue
                    for candidate in raw.get("revision_history") or []:
                        if candidate.get("revision_id") == target_id:
                            self.check_scene_revision(
                                str(raw.get("scene_id") or ""),
                                target_id,
                                mode="manual",
                            )
                            return
            else:
                self.check_scene(target_id, mode="manual")
        except StorageError:
            return

    def _update_embedded_quality(
        self,
        context: dict[str, Any],
        report: QualityReport,
    ) -> None:
        scene: Scene = context["scene"]
        embedded = SceneQualityReport(
            quality_report_id=report.quality_report_id,
            passed=report.passed,
            warnings=[issue.message for issue in report.warnings if issue.user_visible],
            blocking_issues=[
                issue.message
                for issue in report.blocking_issues
                if issue.user_visible
            ],
            requires_user_confirmation=report.requires_user_confirmation,
            continuity_checked=report.continuity_checked,
            continuity_gate_run_id=report.continuity_gate_run_id,
            continuity_checked_at=report.continuity_checked_at,
            continuity_passed=report.continuity_passed,
            continuity_issue_ids=report.continuity_issue_ids,
            blocking_continuity_issue_ids=report.blocking_continuity_issue_ids,
            accepted_continuity_issue_ids=report.accepted_continuity_issue_ids,
            semantic_check_status=report.semantic_check_status,
            summary=report.summary or "",
            quality_degraded=report.quality_degraded,
            confirmation_block_reason=report.confirmation_block_reason,
        )
        if context.get("target_type") == "scene_revision":
            updated_scenes = []
            for raw in self.repositories.scenes.list_all():
                if raw.get("scene_id") != scene.scene_id:
                    updated_scenes.append(raw)
                    continue
                copy = dict(raw)
                history = []
                for candidate in copy.get("revision_history") or []:
                    item = dict(candidate)
                    if item.get("revision_id") == context.get("revision_id"):
                        item["quality_report"] = model_to_dict(embedded)
                        item["quality_report_id"] = report.quality_report_id
                        item["updated_at"] = now_iso()
                    history.append(item)
                copy["revision_history"] = history
                copy["updated_at"] = now_iso()
                updated_scenes.append(copy)
            self.repositories.scenes.write_all(updated_scenes)
            return
        updated_scene = Scene(
            **{
                **model_to_dict(scene),
                "quality_report": model_to_dict(embedded),
                "quality_report_id": report.quality_report_id,
                "updated_at": now_iso(),
            }
        )
        self.repositories.scenes.upsert(model_to_dict(updated_scene), "scene_id")

    def _latest_quality_report(
        self,
        reports: list[dict[str, Any]],
        target_type: str,
        target_id: str,
    ) -> QualityReport | None:
        matches = [
            item
            for item in reports
            if item.get("target_type") == target_type
            and item.get("target_id") == target_id
        ]
        if not matches:
            return None
        try:
            return QualityReport(**matches[-1])
        except ValidationError as exc:
            raise StorageError("QualityReport JSON schema is invalid.") from exc

    def _next_quality_report_id(
        self,
        reports: list[dict[str, Any]],
        target_type: str,
        target_id: str,
    ) -> str:
        prefix = "quality_revision" if target_type == "scene_revision" else "quality_scene"
        count = len(
            [
                item
                for item in reports
                if item.get("target_type") == target_type
                and item.get("target_id") == target_id
            ]
        )
        return f"{prefix}_{target_id}_{count + 1:03d}"

    def _write_decision(
        self,
        *,
        decision_type: str,
        target_type: str,
        target_id: str,
        user_input: str,
    ) -> dict[str, Any]:
        decisions = self.repositories.decisions.list_all()
        decision = {
            "decision_id": f"decision_continuity_{len(decisions) + 1:03d}",
            "decision_type": decision_type,
            "target_type": target_type,
            "target_id": target_id,
            "user_input": user_input,
            "created_at": now_iso(),
        }
        decisions.append(decision)
        self.repositories.decisions.write_all(decisions)
        return decision

    def _summary(
        self,
        blocking: list[ContinuityIssue],
        warning: list[ContinuityIssue],
        accepted: list[ContinuityIssue],
    ) -> str:
        if blocking:
            return f"连续性门发现 {len(blocking)} 个阻塞问题，需要先处理。"
        if warning:
            return f"连续性门通过，但有 {len(warning)} 个提醒建议复核。"
        if accepted:
            return f"连续性门通过，已有 {len(accepted)} 个问题被显式接受并记录。"
        return "连续性门通过，未发现阻塞问题。"


class SceneConfirmationGuard:
    def __init__(self, continuity_gate_service: ContinuityGateService) -> None:
        self.continuity_gate_service = continuity_gate_service

    def require_scene_confirmation_allowed(
        self,
        scene_id: str,
        mode: str = "final_confirmation",
    ) -> ContinuityCheckResponse:
        response = self.continuity_gate_service.check_scene(scene_id, mode=mode)
        if response.blocking_issue_ids:
            code = "SCENE_CONTINUITY_BLOCKING_ISSUES"
            raise StorageError(
                f"{code}: 当前幕存在连续性阻塞问题，请先处理或刷新检查。"
            )
        return response

    def require_revision_confirmation_allowed(
        self,
        scene_id: str,
        revision_id: str,
    ) -> ContinuityCheckResponse:
        response = self.continuity_gate_service.check_scene_revision(
            scene_id,
            revision_id,
            mode="revision_confirmation",
        )
        if response.blocking_issue_ids:
            code = "SCENE_REVISION_CONTINUITY_BLOCKING_ISSUES"
            raise StorageError(
                f"{code}: 当前修订存在连续性阻塞问题，请先处理或刷新检查。"
            )
        return response


def _resolution_options_for_issue(issue: ContinuityIssue) -> list[IssueResolutionOption]:
    return [
        IssueResolutionOption(
            option_id=f"{issue.issue_id}_complete_prior_story",
            issue_id=issue.issue_id,
            action_type="complete_prior_story",
            label="补全前情",
            description="先创建一个待确认的前情补全候选，用户确认后才写入正式事件和记忆。",
            requires_user_input=True,
            requires_model_call=False,
            expected_effect="为当前冲突补上来源事实，而不是直接改写当前幕。",
        ),
        IssueResolutionOption(
            option_id=f"{issue.issue_id}_revise_current_scene",
            issue_id=issue.issue_id,
            action_type="revise_current_scene",
            label="修改当前幕",
            description="创建场景修订候选，不自动确认，不自动应用记忆同步。",
            requires_user_input=True,
            requires_model_call=True,
            expected_effect="让当前幕与已确认事实重新对齐。",
        ),
        IssueResolutionOption(
            option_id=f"{issue.issue_id}_mark_misinformation",
            issue_id=issue.issue_id,
            action_type="mark_as_misinformation_or_lie",
            label="设为误传 / 谎言",
            description="把相关说法记录为非客观事实，避免下游当作 canon 使用。",
            requires_user_input=True,
            requires_model_call=False,
            expected_effect="保留叙事误导，同时保护客观连续性。",
        ),
    ]


def _acceptance_policy_for_category(category: str) -> str:
    if category in FORBIDDEN_ACCEPT_CATEGORIES:
        return "forbidden"
    if category in STRONG_CONFIRMATION_CATEGORIES:
        return "requires_strong_confirmation"
    return "allowed"


def _current_chapter_context(context: dict[str, Any]) -> dict[str, Any]:
    chapter_id = context.get("chapter_id") or ""
    for chapter in context.get("chapters") or []:
        if isinstance(chapter, dict) and chapter.get("chapter_id") == chapter_id:
            return {
                "chapter_id": chapter.get("chapter_id"),
                "chapter_goal": str(chapter.get("chapter_goal") or "")[:200],
                "main_conflict": str(chapter.get("main_conflict") or "")[:200],
                "summary": str(chapter.get("summary") or "")[:200],
            }
    return {}


def _stable_digest(parts: list[str]) -> str:
    text = "||".join(str(part or "") for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _unique_strings(values: list[Any]) -> list[str]:
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
