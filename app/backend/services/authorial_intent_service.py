import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.agents.authorial_intent_agent import AuthorialIntentAgent
from app.backend.core.config import settings
from app.backend.models.authorial_intent import (
    AUTHORIAL_INTENT_CONSTRAINT_STRENGTHS,
    AuthorialIntentAgentOutput,
    AuthorialIntentContext,
    AuthorialIntentResult,
)
from app.backend.models.narrative_layer import (
    LOCAL_PROJECT_ID,
    NarrativeIntentRecord,
    NarrativeObjectReference,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.narrative_layer_service import NarrativeLayerService
from app.backend.services.model_gateway_service import ModelGatewayService
from app.backend.services.runtime_error_sanitizer import RuntimeErrorSanitizer
from app.backend.storage.json_store import JsonStore, StorageError


CJK_RE = re.compile(r"[\u3400-\u9fff]")
FORBIDDEN_EXTRA_KEYS = {
    "event",
    "events",
    "event_summary",
    "objective_event",
    "objective_events",
    "memory",
    "memories",
    "memory_record",
    "memory_records",
    "objective_memory",
    "objective_memories",
    "state_change",
    "state_changes",
    "character_patch",
    "character_patches",
    "character_update",
    "character_updates",
    "world_rule_change",
    "world_rule_changes",
    "confirmed_fact_change",
    "confirmed_fact_changes",
    "override_user_decision",
    "override_user_decisions",
    "prose_text",
    "full_prose",
    "full_prompt",
    "raw_response",
    "internal_reasoning",
}
FORBIDDEN_TEXT_MARKERS = {
    "override user decision",
    "change confirmed fact",
    "change world hard rule",
    "create objective event",
    "create memory record",
    "write state change",
    "patch character",
    "覆盖用户决定",
    "改写用户决定",
    "改写世界硬设定",
    "修改世界硬设定",
    "改写已确认事实",
    "创建客观事件",
    "写入客观记忆",
    "写入状态变化",
    "修改角色状态",
}


class AuthorialIntentService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        model_gateway: ModelGatewayService | None = None,
        agent: AuthorialIntentAgent | None = None,
        narrative_layer_service: NarrativeLayerService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.agent = agent or AuthorialIntentAgent(model_gateway=model_gateway)
        self.narrative_layer_service = narrative_layer_service or NarrativeLayerService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.error_sanitizer = RuntimeErrorSanitizer()

    def create_generation_trace_id(
        self,
        *,
        chapter_id: str,
        scene_index: int,
    ) -> str:
        safe_chapter = _safe_id(chapter_id or "chapter")
        return f"scene_trace_{safe_chapter}_{scene_index:03d}_{uuid4().hex[:12]}"

    def create_or_skip_for_scene_generation(
        self,
        scene_generation_context: dict[str, Any],
        *,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
        generation_trace_id: str,
        regeneration_hint: str = "",
    ) -> AuthorialIntentResult:
        snapshot_before = self._objective_snapshot()
        context = self.build_context(
            scene_generation_context,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            generation_trace_id=generation_trace_id,
            regeneration_hint=regeneration_hint,
        )
        try:
            output = self.agent.generate(context)
        except Exception as exc:
            return self._failed_result(exc)

        result = self._save_or_skip_output(
            output=output,
            context=context,
        )
        if self._objective_snapshot() != snapshot_before:
            return AuthorialIntentResult(
                status="failed",
                failure_reason="Authorial Intent 调用改变了客观事实层，已拒绝作为有效结果。",
            )
        return result

    def build_context(
        self,
        scene_generation_context: dict[str, Any],
        *,
        chapter_id: str,
        scene_id: str,
        scene_index: int,
        generation_trace_id: str,
        regeneration_hint: str = "",
    ) -> AuthorialIntentContext:
        context = dict(scene_generation_context or {})
        chapter = context.get("chapter") or {}
        framework = context.get("current_chapter_framework") or {}
        package = context.get("framework_package") or {}
        scene_pack = context.get("scene_memory_pack") or {}
        pack_context = context.get("memory_pack_context") or {}
        character_context = context.get("character_context") or {}
        recent_events = context.get("recent_events") or []

        return AuthorialIntentContext(
            project_id=str(context.get("project_id") or LOCAL_PROJECT_ID),
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            generation_trace_id=generation_trace_id,
            chapter_goal=self._short(
                chapter.get("chapter_goal")
                or chapter.get("summary")
                or chapter.get("title")
                or ""
            ),
            chapter_framework_summary=self._framework_summary(framework),
            scene_goal=self._short(
                regeneration_hint
                or context.get("resolved_scene_goal")
                or chapter.get("chapter_goal")
                or chapter.get("main_conflict")
                or ""
            ),
            scene_memory_pack_summary=self._scene_pack_summary(scene_pack),
            must_use_memory_summaries=self._memory_ref_summaries(
                pack_context.get("must_use_context") or []
            ),
            forbidden_or_conflict_summaries=self._memory_ref_summaries(
                pack_context.get("forbidden_or_conflict_context") or []
            ),
            active_character_summaries=self._character_summaries(
                context.get("characters") or [],
                character_context,
            ),
            relationship_summaries=self._relationship_summaries(
                context.get("relationships") or []
            ),
            style_profile=self._style_profile(package, framework),
            user_intent=self._short(regeneration_hint),
            previous_scene_summary=self._short(
                (
                    self._recent_event_summary(recent_events)
                    + " Previous chapter and previous scene material is background continuity only; do not replay it as the current scene goal."
                ).strip()
            ),
            provisional_dependency_summary=self._provisional_dependency_summary(
                scene_pack
            ),
        )

    def _save_or_skip_output(
        self,
        *,
        output: AuthorialIntentAgentOutput,
        context: AuthorialIntentContext,
    ) -> AuthorialIntentResult:
        if not output.should_create_intent:
            skip_reason = self._short(output.skip_reason)
            if not skip_reason or not _has_cjk(skip_reason):
                return AuthorialIntentResult(
                    status="failed",
                    failure_reason="Authorial Intent Agent 跳过原因缺失或不是中文。",
                )
            return AuthorialIntentResult(status="skipped", skip_reason=skip_reason)

        policy_reason = self._policy_rejection_reason(output)
        if policy_reason:
            return AuthorialIntentResult(
                status="policy_rejected",
                failure_reason=policy_reason,
            )

        summary = self._short(output.summary)
        if not summary or not _has_cjk(summary):
            return AuthorialIntentResult(
                status="failed",
                failure_reason="Authorial Intent Agent 没有给出可保存的中文叙事意图摘要。",
            )

        try:
            record = NarrativeIntentRecord(
                narrative_intent_id=self._intent_id(
                    context.scene_id,
                    context.generation_trace_id,
                ),
                project_id=context.project_id,
                chapter_id=context.chapter_id,
                scene_id=context.scene_id,
                source_type="authorial_intent_agent",
                intent_type=output.intent_type,
                summary=summary,
                constraint_strength=output.constraint_strength,
                allowed_apparent_contradictions=output.allowed_apparent_contradictions,
                reader_explanation_policy=output.reader_explanation_policy,
                payoff_required=output.payoff_required,
                open_ambiguity_allowed=output.open_ambiguity_allowed,
                symbolic_unresolved=output.symbolic_unresolved,
                payoff_deadline_type=output.payoff_deadline_type,
                payoff_deadline_chapter_id=output.payoff_deadline_chapter_id,
                payoff_deadline_scene_index=output.payoff_deadline_scene_index,
                payoff_deadline_note=output.payoff_deadline_note,
                created_before_scene_output=True,
                generation_trace_id=context.generation_trace_id,
                source_refs=[
                    NarrativeObjectReference(
                        object_type="scene_generation_trace",
                        object_id=context.generation_trace_id,
                        relation="created_before_scene_output",
                    ),
                    NarrativeObjectReference(
                        object_type="scene",
                        object_id=context.scene_id,
                        relation="target_scene",
                    ),
                ],
            )
            saved = self.narrative_layer_service.create_narrative_intent(record)
        except (StorageError, ValidationError, ValueError) as exc:
            safe = self.error_sanitizer.sanitize(
                exc,
                stage="schema_validation",
                error_type="schema_validation_error",
            )
            return AuthorialIntentResult(
                status="policy_rejected",
                failure_reason=safe.user_visible_message,
            )

        return AuthorialIntentResult(
            status="created",
            narrative_intent_id=saved.narrative_intent_id,
            narrative_intent_summary=self._short(saved.summary),
            record=saved,
        )

    def _policy_rejection_reason(
        self,
        output: AuthorialIntentAgentOutput,
    ) -> str:
        if output.constraint_strength not in AUTHORIAL_INTENT_CONSTRAINT_STRENGTHS:
            return "Authorial Intent Agent 输出了被禁止的 hard_constraint 或非法约束强度。"

        payload = model_to_dict(output)
        forbidden_key = self._find_forbidden_key(payload)
        if forbidden_key:
            return f"Authorial Intent Agent 输出包含禁止字段 {forbidden_key}，已拒绝保存。"

        text = json.dumps(payload, ensure_ascii=False).casefold()
        for marker in FORBIDDEN_TEXT_MARKERS:
            if marker.casefold() in text:
                return "Authorial Intent Agent 输出企图覆盖用户决定、世界硬设定或客观事实，已拒绝保存。"
        return ""

    def _find_forbidden_key(self, value: Any) -> str:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key or "").strip().casefold()
                if normalized in FORBIDDEN_EXTRA_KEYS:
                    return str(key)
                nested = self._find_forbidden_key(item)
                if nested:
                    return nested
        elif isinstance(value, list):
            for item in value:
                nested = self._find_forbidden_key(item)
                if nested:
                    return nested
        return ""

    def _failed_result(self, exc: Exception) -> AuthorialIntentResult:
        safe = self.error_sanitizer.sanitize(exc)
        return AuthorialIntentResult(
            status="failed",
            failure_reason=safe.user_visible_message,
        )

    def _objective_snapshot(self) -> str:
        payload = {
            "events": self.repositories.events.list_all(),
            "memory_records": self.repositories.memory.list_all(),
            "state_changes": self.repositories.state_changes.list_all(),
            "characters": self.repositories.characters.list_all(),
            "narrative_debts": self.repositories.narrative_debts.list_all(),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _framework_summary(self, framework: dict[str, Any]) -> str:
        chunks: list[str] = []
        for key in ("chapter_goal", "summary", "narrative_function"):
            if framework.get(key):
                chunks.append(str(framework[key]))
        for module in (framework.get("modules") or [])[:6]:
            if not isinstance(module, dict):
                continue
            label = str(module.get("label") or module.get("module_id") or "").strip()
            components = [
                str(component.get("label") or component.get("component_id") or "")
                for component in (module.get("components") or [])[:5]
                if isinstance(component, dict)
            ]
            text = " / ".join([label, *[item for item in components if item]])
            if text.strip(" /"):
                chunks.append(text)
        return self._short(" | ".join(chunks), max_len=600)

    def _scene_pack_summary(self, scene_pack: dict[str, Any]) -> str:
        if not isinstance(scene_pack, dict) or not scene_pack:
            return ""
        parts = [
            f"pack={scene_pack.get('scene_memory_pack_id') or ''}",
            f"status={scene_pack.get('status') or ''}",
        ]
        gaps = scene_pack.get("retrieval_gaps") or []
        gap_messages = [
            str(gap.get("message") or gap.get("gap_type") or "")
            for gap in gaps[:3]
            if isinstance(gap, dict)
        ]
        if gap_messages:
            parts.append("gaps=" + " / ".join(gap_messages))
        return self._short(" ; ".join(part for part in parts if part), max_len=360)

    def _memory_ref_summaries(self, refs: list[Any]) -> list[str]:
        summaries: list[str] = []
        for ref in refs[:12]:
            if not isinstance(ref, dict):
                ref = model_to_dict(ref) if hasattr(ref, "dict") else {}
            memory_id = str(ref.get("memory_id") or "").strip()
            summary = self._short(ref.get("summary") or "", max_len=180)
            status = str(ref.get("status") or "").strip()
            if not summary:
                continue
            prefix = f"{memory_id}: " if memory_id else ""
            suffix = f" ({status})" if status else ""
            summaries.append(f"{prefix}{summary}{suffix}")
        return summaries

    def _character_summaries(
        self,
        characters: list[Any],
        character_context: dict[str, Any],
    ) -> list[str]:
        summaries: list[str] = []
        for item in (character_context.get("items") or [])[:8]:
            if not isinstance(item, dict):
                continue
            chunks = [
                item.get("name") or item.get("character_id") or "",
                item.get("current_state_summary") or "",
                item.get("personality_summary") or "",
                item.get("arc_summary") or "",
            ]
            text = self._short(" | ".join(str(part) for part in chunks if part), max_len=260)
            if text:
                summaries.append(text)
        if summaries:
            return summaries

        for character in characters[:8]:
            if not isinstance(character, dict):
                continue
            state = character.get("current_state") or {}
            profile = character.get("profile") or {}
            chunks = [
                character.get("name") or character.get("character_id") or "",
                state.get("active_goal") or "",
                state.get("current_desire") or "",
                state.get("current_fear") or "",
                profile.get("story_function") or "",
            ]
            text = self._short(" | ".join(str(part) for part in chunks if part), max_len=260)
            if text:
                summaries.append(text)
        return summaries

    def _relationship_summaries(self, relationships: list[Any]) -> list[str]:
        summaries: list[str] = []
        for relationship in relationships[:10]:
            if not isinstance(relationship, dict):
                continue
            text = " | ".join(
                str(part)
                for part in [
                    relationship.get("relationship_id"),
                    relationship.get("source_id"),
                    relationship.get("target_id"),
                    relationship.get("type"),
                    relationship.get("state"),
                    relationship.get("evidence_note"),
                ]
                if part
            )
            if text:
                summaries.append(self._short(text, max_len=220))
        return summaries

    def _style_profile(
        self,
        package: dict[str, Any],
        framework: dict[str, Any],
    ) -> str:
        for source in (package, framework):
            for key in ("style_profile", "tone", "prose_style", "narrative_style"):
                value = source.get(key) if isinstance(source, dict) else ""
                if isinstance(value, str) and value.strip():
                    return self._short(value, max_len=240)
                if isinstance(value, dict):
                    return self._short(json.dumps(value, ensure_ascii=False), max_len=240)
        return ""

    def _recent_event_summary(self, recent_events: list[Any]) -> str:
        summaries = [
            self._short(event.get("summary") or "", max_len=160)
            for event in recent_events[-3:]
            if isinstance(event, dict) and event.get("summary")
        ]
        return self._short(" / ".join(summaries), max_len=420)

    def _provisional_dependency_summary(self, scene_pack: dict[str, Any]) -> str:
        if not isinstance(scene_pack, dict):
            return ""
        scene_ids = scene_pack.get("provisional_dependency_scene_ids") or []
        memory_ids = scene_pack.get("provisional_memory_ids") or []
        chunks = []
        if scene_ids:
            chunks.append("provisional scenes: " + ", ".join(map(str, scene_ids[:8])))
        if memory_ids:
            chunks.append("provisional memories: " + ", ".join(map(str, memory_ids[:8])))
        return self._short(" ; ".join(chunks), max_len=320)

    def _intent_id(self, scene_id: str, generation_trace_id: str) -> str:
        return f"intent_{_safe_id(scene_id)}_{_safe_id(generation_trace_id)[-16:]}"

    def _short(self, value: Any, *, max_len: int = 240) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, BaseModel):
        return model.dict()
    return dict(model)


def _safe_id(value: str) -> str:
    text = str(value or "").strip()
    safe = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in text)
    return safe.strip("_") or "unknown"


def _has_cjk(value: str) -> bool:
    return bool(CJK_RE.search(str(value or "")))
