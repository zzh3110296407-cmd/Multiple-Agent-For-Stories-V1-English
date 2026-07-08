from pathlib import Path
import re
from typing import Any

from app.backend.core.config import settings
from app.backend.models.memory_pack import MemoryPackSourceRef, RetrievalGap
from app.backend.models.memory_record import MemoryQuery, MemoryQueryResult
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.memory_query_service import MemoryQueryService
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore


class MemoryRetrievalService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        query_service: MemoryQueryService | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.query_service = query_service or MemoryQueryService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def retrieve_for_chapter(
        self,
        chapter: dict[str, Any],
        framework: dict[str, Any],
        characters: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        events: list[dict[str, Any]],
        world_canvas: dict[str, Any],
    ) -> dict[str, Any]:
        chapter_id = str(chapter.get("chapter_id") or "")
        participant_ids = self._unique(
            [
                *(chapter.get("participant_character_ids") or []),
                *(chapter.get("participating_character_ids") or []),
            ]
        )
        if not participant_ids:
            participant_ids = self._unique(
                [
                    str(character.get("character_id") or "")
                    for character in characters
                    if character.get("status", "confirmed") == "confirmed"
                ]
            )
        relationship_ids = self._relationship_ids_for_characters(
            participant_ids,
            relationships,
        )
        recent_events = [
            event
            for event in events
            if event.get("status", "confirmed") in {"confirmed", "revised", "temporary_confirmed"}
        ][-6:]
        recent_event_ids = self._unique(
            [str(event.get("event_id") or "") for event in recent_events]
        )
        locations = self._unique(
            [
                str(event.get("location_id") or "")
                for event in recent_events
                if event.get("location_id")
            ]
        )
        keywords = self._keyword_tokens(
            " ".join(
                [
                    str(chapter.get("chapter_goal") or ""),
                    str(chapter.get("main_conflict") or ""),
                    str(chapter.get("summary") or ""),
                    self._framework_text(framework),
                    self._world_rule_text(world_canvas),
                ]
            )
        )

        query_results: list[MemoryQueryResult] = []
        query_signature: dict[str, Any] = {
            "chapter_id": chapter_id,
            "participant_character_ids": participant_ids,
            "relationship_ids": relationship_ids,
            "locations": locations,
            "recent_event_ids": recent_event_ids,
            "keywords": keywords[:12],
            "queries": [],
        }

        query_results.extend(
            self._query(
                MemoryQuery(chapter_id=chapter_id, limit=60),
                "chapter_id",
                query_signature,
            )
        )
        if participant_ids:
            query_results.extend(
                self._query(
                    MemoryQuery(character_ids=participant_ids, limit=60),
                    "chapter_characters",
                    query_signature,
                )
            )
        if relationship_ids:
            query_results.extend(
                self._query(
                    MemoryQuery(relationship_ids=relationship_ids, limit=60),
                    "chapter_relationships",
                    query_signature,
                )
            )
        if recent_event_ids:
            query_results.extend(
                self._query(
                    MemoryQuery(event_ids=recent_event_ids, limit=60),
                    "recent_events",
                    query_signature,
                )
            )
        for location in locations[:6]:
            query_results.extend(
                self._query(
                    MemoryQuery(location=location, limit=40),
                    "chapter_location",
                    query_signature,
                )
            )
        if keywords:
            query_results.extend(
                self._query(
                    MemoryQuery(keywords=keywords[:12], limit=60),
                    "chapter_keywords",
                    query_signature,
                )
            )
        query_results.extend(
            self._query(
                MemoryQuery(memory_types=["world", "framework"], limit=40),
                "world_framework_memory_types",
                query_signature,
            )
        )

        merged = self._dedupe_results(query_results)
        gaps = self._chapter_gaps(
            chapter_id=chapter_id,
            participant_ids=participant_ids,
            relationship_ids=relationship_ids,
            locations=locations,
            world_canvas=world_canvas,
            framework=framework,
            results=merged,
        )
        split = self._split_chapter_refs(merged)
        split["retrieval_gaps"] = gaps
        split["source_query_signature"] = query_signature
        split["included_memory_ids"] = self._unique(
            [
                ref.memory_id
                for key in (
                    "world_context",
                    "character_context",
                    "relationship_context",
                    "event_context",
                    "framework_context",
                )
                for ref in split[key]
            ]
        )
        return split

    def retrieve_for_scene(
        self,
        chapter_pack,
        scene_index: int,
        scene_id: str | None,
        scene_goal: str,
        scene_location: str,
        active_character_ids: list[str],
        recent_events: list[dict[str, Any]],
        required_memory_refs: list[str] | None = None,
        include_provisional: bool = False,
    ) -> dict[str, Any]:
        chapter_id = chapter_pack.chapter_id
        active_character_ids = self._unique(active_character_ids)
        required_memory_refs = self._unique(required_memory_refs or [])
        scene_location = str(scene_location or "").strip()
        scene_goal_keywords = self._keyword_tokens(scene_goal)
        recent_events = [
            event
            for event in recent_events
            if event.get("status", "confirmed") in {"confirmed", "revised", "temporary_confirmed"}
        ][-5:]
        recent_event_ids = self._unique(
            [str(event.get("event_id") or "") for event in recent_events]
        )
        query_signature: dict[str, Any] = {
            "chapter_memory_pack_id": chapter_pack.chapter_memory_pack_id,
            "chapter_id": chapter_id,
            "scene_id": scene_id or "",
            "scene_index": scene_index,
            "scene_goal": self._short_text(scene_goal, max_len=160),
            "scene_location": scene_location,
            "active_character_ids": active_character_ids,
            "required_memory_refs": required_memory_refs,
            "include_provisional": include_provisional,
            "queries": [],
        }

        additional_results: list[MemoryQueryResult] = []
        if scene_id:
            additional_results.extend(
                self._query(
                    MemoryQuery(scene_id=scene_id, limit=40),
                    "scene_id",
                    query_signature,
                )
            )
        if scene_location:
            additional_results.extend(
                self._query(
                    MemoryQuery(chapter_id=chapter_id, location=scene_location, limit=40),
                    "scene_location",
                    query_signature,
                )
            )
        if active_character_ids:
            additional_results.extend(
                self._query(
                    MemoryQuery(
                        chapter_id=chapter_id,
                        character_ids=active_character_ids,
                        limit=50,
                    ),
                    "scene_active_characters",
                    query_signature,
                )
            )
        if recent_event_ids:
            additional_results.extend(
                self._query(
                    MemoryQuery(event_ids=recent_event_ids, limit=40),
                    "scene_recent_events",
                    query_signature,
                )
            )
        if scene_goal_keywords:
            additional_results.extend(
                self._query(
                    MemoryQuery(
                        chapter_id=chapter_id,
                        keywords=scene_goal_keywords[:8],
                        limit=40,
                    ),
                    "scene_goal_keywords",
                    query_signature,
                )
            )

        provisional_results = self._scoped_status_results(
            chapter_id=chapter_id,
            statuses=["provisional"],
            reason_prefix="provisional_scan",
            query_signature=query_signature,
            scene_id=scene_id,
            scene_location=scene_location,
            active_character_ids=active_character_ids,
            recent_event_ids=recent_event_ids,
            scene_goal_keywords=scene_goal_keywords,
            include_provisional=True,
        )
        conflict_results = [
            *self._scoped_status_results(
                chapter_id=chapter_id,
                statuses=["superseded"],
                reason_prefix="superseded_scan",
                query_signature=query_signature,
                scene_id=scene_id,
                scene_location=scene_location,
                active_character_ids=active_character_ids,
                recent_event_ids=recent_event_ids,
                scene_goal_keywords=scene_goal_keywords,
                include_superseded=True,
            ),
            *self._scoped_status_results(
                chapter_id=chapter_id,
                statuses=["rejected"],
                reason_prefix="rejected_scan",
                query_signature=query_signature,
                scene_id=scene_id,
                scene_location=scene_location,
                active_character_ids=active_character_ids,
                recent_event_ids=recent_event_ids,
                scene_goal_keywords=scene_goal_keywords,
            ),
        ]

        base_refs = self._chapter_pack_refs(chapter_pack)
        additional_refs = [
            self._result_to_ref(result, reason="scene_scoped_query")
            for result in self._dedupe_results(additional_results)
        ]
        provisional_refs = [
            self._result_to_ref(result, reason="explicit_provisional_dependency")
            for result in self._dedupe_results(provisional_results)
        ]
        conflict_refs = [
            self._result_to_ref(result, reason="excluded_or_conflicting_status")
            for result in self._dedupe_results(conflict_results)
        ]
        provisional_memory_ids = [ref.memory_id for ref in provisional_refs]
        provisional_dependency_scene_ids = self._unique(
            [
                str(result.record.scene_id or "")
                for result in provisional_results
                if result.record.scene_id
            ]
        )

        must_use = self._scene_must_use_refs(
            chapter_id=chapter_id,
            base_refs=base_refs,
            additional_refs=additional_refs,
            active_character_ids=active_character_ids,
            recent_event_ids=recent_event_ids,
        )
        if include_provisional:
            must_use = self._dedupe_refs([*must_use, *provisional_refs])
        should_use = self._scene_should_use_refs(
            chapter_id=chapter_id,
            base_refs=base_refs,
            additional_refs=additional_refs,
            must_use=must_use,
            scene_location=scene_location,
        )
        optional = self._dedupe_refs(
            [
                ref
                for ref in [*base_refs, *additional_refs]
                if ref.memory_id
                not in {
                    *[item.memory_id for item in must_use],
                    *[item.memory_id for item in should_use],
                }
            ]
        )
        forbidden = self._dedupe_refs(
            [
                *conflict_refs,
                *([] if include_provisional else provisional_refs),
            ]
        )
        normalized = self._normalize_scene_memory_context(
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            must_use=must_use,
            should_use=should_use,
            optional=optional,
            forbidden=forbidden,
            required_memory_refs=required_memory_refs,
        )
        must_use = normalized["must_use_context"]
        should_use = normalized["should_use_context"]
        optional = normalized["optional_context"]
        forbidden = normalized["forbidden_or_conflict_context"]
        continuity_anchor = normalized["continuity_anchor_context"]
        do_not_repeat = normalized["do_not_repeat_context"]

        gaps = [
            *chapter_pack.retrieval_gaps,
            *self._scene_gaps(
                chapter_id=chapter_id,
                scene_index=scene_index,
                scene_id=scene_id,
                scene_location=scene_location,
                active_character_ids=active_character_ids,
                recent_event_ids=recent_event_ids,
                location_results=additional_results,
            ),
        ]
        if include_provisional and provisional_refs:
            gaps.append(
                self._gap(
                    "provisional_dependency_warning",
                    chapter_id=chapter_id,
                    scene_id=scene_id,
                    character_ids=active_character_ids,
                    keywords=["provisional"],
                    message="SceneMemoryPack 包含 provisional 临时记忆，需要后续确认其事实状态。",
                    suggested_action="确认相关临时事实后再进入长期记忆或正式连续生成。",
                    severity="needs_user_confirmation",
                )
            )
        elif include_provisional and provisional_memory_ids and not provisional_dependency_scene_ids:
            gaps.append(
                self._gap(
                    "provisional_dependency_warning",
                    chapter_id=chapter_id,
                    scene_id=scene_id,
                    character_ids=active_character_ids,
                    keywords=["provisional"],
                    message="SceneMemoryPack 包含 provisional 临时记忆，但无法可靠推断来源场景。",
                    suggested_action="人工检查临时记忆来源，再决定是否纳入正式上下文。",
                    severity="warning",
                )
            )

        must_use = self._limit_refs(must_use, 10)
        should_use = self._limit_refs(should_use, 15)
        optional = self._limit_refs(optional, 10)
        forbidden = self._limit_refs(forbidden, 10)
        continuity_anchor = self._limit_refs(continuity_anchor, 12)
        do_not_repeat = self._limit_refs(do_not_repeat, 12)
        dedupe_report = {
            **normalized["memory_context_dedupe_report"],
            "final_counts": {
                "must_use_context": len(must_use),
                "should_use_context": len(should_use),
                "optional_context": len(optional),
                "forbidden_or_conflict_context": len(forbidden),
                "continuity_anchor_context": len(continuity_anchor),
                "do_not_repeat_context": len(do_not_repeat),
            },
        }

        return {
            "must_use_context": must_use,
            "should_use_context": should_use,
            "optional_context": optional,
            "forbidden_or_conflict_context": forbidden,
            "continuity_anchor_context": continuity_anchor,
            "do_not_repeat_context": do_not_repeat,
            "must_use_memory_ids": [ref.memory_id for ref in must_use],
            "should_use_memory_ids": [ref.memory_id for ref in should_use],
            "optional_memory_ids": [ref.memory_id for ref in optional],
            "forbidden_or_conflict_memory_ids": [ref.memory_id for ref in forbidden],
            "continuity_anchor_memory_ids": [ref.memory_id for ref in continuity_anchor],
            "do_not_repeat_memory_ids": [ref.memory_id for ref in do_not_repeat],
            "provisional_memory_ids": provisional_memory_ids if include_provisional else [],
            "provisional_dependency_scene_ids": provisional_dependency_scene_ids
            if include_provisional
            else [],
            "retrieval_gaps": self._dedupe_gaps(gaps),
            "source_query_signature": query_signature,
            "memory_context_dedupe_report": dedupe_report,
        }

    def _query(
        self,
        query: MemoryQuery,
        reason: str,
        query_signature: dict[str, Any],
    ) -> list[MemoryQueryResult]:
        query_signature.setdefault("queries", []).append(
            {
                "reason": reason,
                "chapter_id": query.chapter_id,
                "scene_id": query.scene_id,
                "character_ids": query.character_ids,
                "relationship_ids": query.relationship_ids,
                "location": query.location,
                "event_ids": query.event_ids,
                "keywords": query.keywords,
                "memory_types": query.memory_types,
                "statuses": query.statuses,
                "include_provisional": query.include_provisional,
                "include_superseded": query.include_superseded,
            }
        )
        return self.query_service.query(query).results

    def _scoped_status_results(
        self,
        *,
        chapter_id: str,
        statuses: list[str],
        reason_prefix: str,
        query_signature: dict[str, Any],
        scene_id: str | None,
        scene_location: str,
        active_character_ids: list[str],
        recent_event_ids: list[str],
        scene_goal_keywords: list[str],
        include_provisional: bool = False,
        include_superseded: bool = False,
    ) -> list[MemoryQueryResult]:
        results: list[MemoryQueryResult] = []
        if scene_id:
            results.extend(
                self._query(
                    MemoryQuery(
                        chapter_id=chapter_id,
                        scene_id=scene_id,
                        statuses=statuses,
                        include_provisional=include_provisional,
                        include_superseded=include_superseded,
                        limit=40,
                    ),
                    f"{reason_prefix}_scene",
                    query_signature,
                )
            )
        if active_character_ids:
            results.extend(
                self._query(
                    MemoryQuery(
                        chapter_id=chapter_id,
                        character_ids=active_character_ids,
                        statuses=statuses,
                        include_provisional=include_provisional,
                        include_superseded=include_superseded,
                        limit=40,
                    ),
                    f"{reason_prefix}_characters",
                    query_signature,
                )
            )
        if scene_location:
            results.extend(
                self._query(
                    MemoryQuery(
                        chapter_id=chapter_id,
                        location=scene_location,
                        statuses=statuses,
                        include_provisional=include_provisional,
                        include_superseded=include_superseded,
                        limit=40,
                    ),
                    f"{reason_prefix}_location",
                    query_signature,
                )
            )
        if recent_event_ids:
            results.extend(
                self._query(
                    MemoryQuery(
                        chapter_id=chapter_id,
                        event_ids=recent_event_ids,
                        statuses=statuses,
                        include_provisional=include_provisional,
                        include_superseded=include_superseded,
                        limit=40,
                    ),
                    f"{reason_prefix}_recent_events",
                    query_signature,
                )
            )
        if scene_goal_keywords:
            results.extend(
                self._query(
                    MemoryQuery(
                        chapter_id=chapter_id,
                        keywords=scene_goal_keywords[:8],
                        statuses=statuses,
                        include_provisional=include_provisional,
                        include_superseded=include_superseded,
                        limit=40,
                    ),
                    f"{reason_prefix}_keywords",
                    query_signature,
                )
            )
        if not any([scene_id, active_character_ids, scene_location, recent_event_ids, scene_goal_keywords]):
            results.extend(
                self._query(
                    MemoryQuery(
                        chapter_id=chapter_id,
                        statuses=statuses,
                        include_provisional=include_provisional,
                        include_superseded=include_superseded,
                        limit=40,
                    ),
                    f"{reason_prefix}_chapter_fallback",
                    query_signature,
                )
            )
        return self._dedupe_results(results)

    def _dedupe_results(
        self,
        results: list[MemoryQueryResult],
    ) -> list[MemoryQueryResult]:
        by_id: dict[str, MemoryQueryResult] = {}
        for result in results:
            existing = by_id.get(result.memory_id)
            if existing is None or result.score_hint > existing.score_hint:
                by_id[result.memory_id] = result
                continue
            if existing is not None and result.score_hint == existing.score_hint:
                existing.matched_by = self._unique(
                    [*existing.matched_by, *result.matched_by]
                )
        return sorted(
            by_id.values(),
            key=lambda item: (-item.score_hint, item.memory_id),
        )

    def _result_to_ref(self, result: MemoryQueryResult, reason: str) -> MemoryPackSourceRef:
        record = result.record
        return MemoryPackSourceRef(
            memory_id=record.memory_id,
            source_object_type=record.source_object_type,
            source_object_id=record.source_object_id,
            source_scene_id=str(record.scene_id or ""),
            memory_type=record.memory_type,
            summary=self._short_text(record.summary),
            keywords=record.keywords[:12],
            status=record.status,
            importance=record.importance,
            version_id=record.version_id,
            matched_by=result.matched_by,
            reason=self._short_text(result.explanation or reason, max_len=180),
        )

    def _split_chapter_refs(
        self,
        results: list[MemoryQueryResult],
    ) -> dict[str, list[MemoryPackSourceRef]]:
        grouped = {
            "world_context": [],
            "character_context": [],
            "relationship_context": [],
            "event_context": [],
            "framework_context": [],
        }
        for result in results:
            record = result.record
            ref = self._result_to_ref(result, reason="chapter_memory_pack")
            kind = (record.memory_type or record.source_object_type or "").casefold()
            if kind in {"world", "world_rule", "rule"}:
                grouped["world_context"].append(ref)
            elif kind == "framework":
                grouped["framework_context"].append(ref)
            elif kind == "character":
                grouped["character_context"].append(ref)
            elif kind in {"event", "scene", "state_change"}:
                grouped["event_context"].append(ref)
            elif record.relationship_ids or kind == "relationship":
                grouped["relationship_context"].append(ref)
            elif record.character_ids:
                grouped["character_context"].append(ref)
            else:
                grouped["event_context"].append(ref)
        grouped["world_context"] = self._limit_refs(grouped["world_context"], 8)
        grouped["character_context"] = self._limit_refs(grouped["character_context"], 20)
        grouped["relationship_context"] = self._limit_refs(grouped["relationship_context"], 8)
        grouped["event_context"] = self._limit_refs(grouped["event_context"], 12)
        grouped["framework_context"] = self._limit_refs(grouped["framework_context"], 6)
        return grouped

    def _chapter_gaps(
        self,
        *,
        chapter_id: str,
        participant_ids: list[str],
        relationship_ids: list[str],
        locations: list[str],
        world_canvas: dict[str, Any],
        framework: dict[str, Any],
        results: list[MemoryQueryResult],
    ) -> list[RetrievalGap]:
        gaps: list[RetrievalGap] = []
        for character_id in participant_ids:
            if not any(character_id in result.record.character_ids for result in results):
                gaps.append(
                    self._gap(
                        "missing_character_memory",
                        chapter_id=chapter_id,
                        character_ids=[character_id],
                        message="当前章节参与角色缺少 active character memory。",
                        suggested_action="补充或确认角色当前状态记忆。",
                    )
                )
        for relationship_id in relationship_ids:
            if not any(relationship_id in result.record.relationship_ids for result in results):
                gaps.append(
                    self._gap(
                        "missing_relationship_memory",
                        chapter_id=chapter_id,
                        keywords=[relationship_id],
                        message="当前章节参与角色关系缺少 relationship memory。",
                        suggested_action="补充或确认角色关系状态记忆。",
                    )
                )
        for location in locations:
            if not any(self._norm(result.record.location) == self._norm(location) for result in results):
                gaps.append(
                    self._gap(
                        "missing_location_memory",
                        chapter_id=chapter_id,
                        location=location,
                        message="当前章节地点缺少 location memory 或相关 event memory。",
                        suggested_action="补充地点相关记忆，或确认该地点没有历史依赖。",
                    )
                )
        if world_canvas.get("hard_rules") and not any(
            (result.record.memory_type or result.record.source_object_type).casefold()
            in {"world", "world_rule", "rule"}
            for result in results
        ):
            gaps.append(
                self._gap(
                    "missing_world_rule_memory",
                    chapter_id=chapter_id,
                    message="世界硬规则缺少对应 memory ref。",
                    suggested_action="为关键世界硬规则补充轻量记忆摘要。",
                )
            )
        if self._framework_text(framework) and not any(
            (result.record.memory_type or result.record.source_object_type).casefold()
            == "framework"
            for result in results
        ):
            gaps.append(
                self._gap(
                    "missing_framework_memory",
                    chapter_id=chapter_id,
                    message="章节框架目标或节点缺少对应 framework memory。",
                    suggested_action="为当前章节框架补充轻量记忆摘要。",
                )
            )
        return self._dedupe_gaps(gaps)

    def _scene_gaps(
        self,
        *,
        chapter_id: str,
        scene_index: int,
        scene_id: str | None,
        scene_location: str,
        active_character_ids: list[str],
        recent_event_ids: list[str],
        location_results: list[MemoryQueryResult],
    ) -> list[RetrievalGap]:
        gaps: list[RetrievalGap] = []
        if scene_location and not any(
            self._norm(result.record.location) == self._norm(scene_location)
            for result in location_results
        ):
            gaps.append(
                self._gap(
                    "missing_location_memory",
                    chapter_id=chapter_id,
                    scene_id=scene_id,
                    location=scene_location,
                    message="当前场景地点缺少可用 location memory 或相关 event memory。",
                    suggested_action="检查地点历史，必要时补充地点记忆。",
                )
            )
        if scene_index > 1 and not recent_event_ids:
            gaps.append(
                self._gap(
                    "missing_recent_event",
                    chapter_id=chapter_id,
                    scene_id=scene_id,
                    character_ids=active_character_ids,
                    message="当前场景需要上一幕连续性，但没有找到上一幕 confirmed/revised event。",
                    suggested_action="先确认上一幕事件，或人工提供连续性摘要。",
                )
            )
        return gaps

    def _scene_must_use_refs(
        self,
        *,
        chapter_id: str,
        base_refs: list[MemoryPackSourceRef],
        additional_refs: list[MemoryPackSourceRef],
        active_character_ids: list[str],
        recent_event_ids: list[str],
    ) -> list[MemoryPackSourceRef]:
        refs = []
        for ref in [*base_refs, *additional_refs]:
            if self._is_cross_chapter_ref(ref, chapter_id):
                continue
            kind = (ref.memory_type or ref.source_object_type).casefold()
            matched = " ".join(ref.matched_by).casefold()
            if kind in {"world", "world_rule", "rule"}:
                refs.append(ref)
            elif any(character_id.casefold() in matched for character_id in active_character_ids):
                refs.append(ref)
            elif any(event_id.casefold() in matched for event_id in recent_event_ids):
                refs.append(ref)
            elif kind in {"relationship", "character"} and ref.importance in {"critical", "high"}:
                refs.append(ref)
        return self._dedupe_refs(refs)

    def _scene_should_use_refs(
        self,
        *,
        chapter_id: str,
        base_refs: list[MemoryPackSourceRef],
        additional_refs: list[MemoryPackSourceRef],
        must_use: list[MemoryPackSourceRef],
        scene_location: str,
    ) -> list[MemoryPackSourceRef]:
        must_ids = {ref.memory_id for ref in must_use}
        refs = []
        for ref in [*additional_refs, *base_refs]:
            if ref.memory_id in must_ids:
                continue
            if self._is_cross_chapter_ref(ref, chapter_id):
                refs.append(self._background_continuity_ref(ref))
                continue
            matched = " ".join([*ref.matched_by, *ref.keywords]).casefold()
            if scene_location and scene_location.casefold() in matched:
                refs.append(ref)
            elif (ref.memory_type or ref.source_object_type).casefold() in {
                "event",
                "relationship",
                "character",
                "framework",
            }:
                refs.append(ref)
        return self._dedupe_refs(refs)

    def _normalize_scene_memory_context(
        self,
        *,
        chapter_id: str,
        scene_id: str | None,
        scene_index: int,
        must_use: list[MemoryPackSourceRef],
        should_use: list[MemoryPackSourceRef],
        optional: list[MemoryPackSourceRef],
        forbidden: list[MemoryPackSourceRef],
        required_memory_refs: list[str],
    ) -> dict[str, Any]:
        required_ids = {item.casefold() for item in self._unique(required_memory_refs)}
        buckets = {
            "must_use_context": must_use,
            "should_use_context": should_use,
            "optional_context": optional,
            "forbidden_or_conflict_context": forbidden,
        }
        original_counts = {name: len(refs) for name, refs in buckets.items()}
        role_priority = {
            "must_use_context": 0,
            "should_use_context": 1,
            "optional_context": 2,
            "forbidden_or_conflict_context": 3,
        }
        importance_priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        by_id: dict[str, tuple[MemoryPackSourceRef, str]] = {}
        duplicate_query_path_ids: list[str] = []
        for bucket_name, refs in buckets.items():
            for ref in refs:
                if not ref.memory_id:
                    continue
                key = ref.memory_id.casefold()
                prepared = self._ref_with_updates(
                    ref,
                    injection_role=self._role_from_bucket(bucket_name),
                )
                existing = by_id.get(key)
                if existing is None:
                    by_id[key] = (prepared, bucket_name)
                    continue
                duplicate_query_path_ids.append(ref.memory_id)
                existing_ref, existing_bucket = existing
                merged = self._merge_ref_metadata(existing_ref, prepared)
                if role_priority[bucket_name] < role_priority[existing_bucket]:
                    by_id[key] = (
                        self._ref_with_updates(
                            prepared,
                            matched_by=merged.matched_by,
                            duplicate_memory_ids=merged.duplicate_memory_ids,
                        ),
                        bucket_name,
                    )
                else:
                    by_id[key] = (merged, existing_bucket)

        grouped: list[list[tuple[MemoryPackSourceRef, str]]] = []
        consumed: set[str] = set()
        entries = list(by_id.values())
        for ref, bucket_name in entries:
            key = ref.memory_id.casefold()
            if key in consumed:
                continue
            group = [(ref, bucket_name)]
            consumed.add(key)
            for other_ref, other_bucket in entries:
                other_key = other_ref.memory_id.casefold()
                if other_key in consumed:
                    continue
                if self._near_duplicate_memory_ref(ref, other_ref):
                    group.append((other_ref, other_bucket))
                    consumed.add(other_key)
            grouped.append(group)

        output = {
            "must_use_context": [],
            "should_use_context": [],
            "optional_context": [],
            "forbidden_or_conflict_context": [],
            "continuity_anchor_context": [],
            "do_not_repeat_context": [],
        }
        dedupe_groups: list[dict[str, Any]] = []
        downranked_ids: list[str] = []
        repeat_risk_ids: list[str] = []
        previous_scene_anchor_ids: list[str] = []

        for group_index, group in enumerate(grouped, start=1):
            group_id = self._dedupe_group_id(chapter_id, scene_index, group_index, group)
            primary_ref, primary_bucket = self._select_primary_memory_ref(
                group,
                role_priority=role_priority,
                importance_priority=importance_priority,
                required_ids=required_ids,
            )
            duplicate_ids = [
                ref.memory_id
                for ref, _bucket in group
                if ref.memory_id != primary_ref.memory_id
            ]
            group_memory_ids = [ref.memory_id for ref, _bucket in group]
            primary_ref = self._ref_with_updates(
                primary_ref,
                dedupe_group_id=group_id,
                duplicate_memory_ids=duplicate_ids,
            )
            if primary_bucket == "forbidden_or_conflict_context":
                role = "forbidden_or_conflict"
                target_bucket = "forbidden_or_conflict_context"
                reason = primary_ref.downrank_reason
            elif primary_ref.memory_id.casefold() in required_ids:
                role = "must_use"
                target_bucket = "must_use_context"
                reason = primary_ref.downrank_reason
            elif self._previous_scene_ref(primary_ref, scene_id):
                role = "continuity_anchor"
                target_bucket = "continuity_anchor_context"
                reason = "previous_scene_continuity_anchor"
                previous_scene_anchor_ids.append(primary_ref.memory_id)
                downranked_ids.append(primary_ref.memory_id)
            else:
                target_bucket = primary_bucket
                role = self._role_from_bucket(primary_bucket)
                reason = primary_ref.downrank_reason
            repeat_risk = "high" if duplicate_ids else ("medium" if role == "continuity_anchor" else "low")
            if repeat_risk in {"high", "medium"}:
                repeat_risk_ids.append(primary_ref.memory_id)
            output[target_bucket].append(
                self._ref_with_updates(
                    primary_ref,
                    injection_role=role,
                    downrank_reason=reason,
                    repeat_risk=repeat_risk,
                )
            )
            for duplicate_ref, duplicate_bucket in group:
                if duplicate_ref.memory_id == primary_ref.memory_id:
                    continue
                duplicate_reason = (
                    "duplicate_near_same_source"
                    if duplicate_bucket != "forbidden_or_conflict_context"
                    else "duplicate_conflict_ref"
                )
                output["do_not_repeat_context"].append(
                    self._ref_with_updates(
                        duplicate_ref,
                        dedupe_group_id=group_id,
                        injection_role="do_not_repeat",
                        downrank_reason=duplicate_reason,
                        repeat_risk="high",
                        duplicate_memory_ids=[primary_ref.memory_id],
                    )
                )
            if duplicate_ids:
                output["do_not_repeat_context"].append(
                    self._ref_with_updates(
                        primary_ref,
                        injection_role="do_not_repeat",
                        downrank_reason="replay_risk_near_duplicate_group",
                        repeat_risk="high",
                    )
                )
            dedupe_groups.append(
                {
                    "dedupe_group_id": group_id,
                    "memory_ids": group_memory_ids,
                    "primary_memory_id": primary_ref.memory_id,
                    "duplicate_memory_ids": duplicate_ids,
                    "primary_injection_role": role,
                    "downrank_reason": reason,
                    "source_scene_ids": self._unique(
                        [ref.source_scene_id for ref, _bucket in group]
                    ),
                }
            )

        for key in output:
            output[key] = self._dedupe_refs(output[key])
        report = {
            "schema_version": "phase85_m5_scene_memory_context_dedupe_v1",
            "required_memory_refs": self._unique(required_memory_refs),
            "original_counts": original_counts,
            "duplicate_query_path_memory_ids": self._unique(
                [
                    *duplicate_query_path_ids,
                    *[
                        ref.memory_id
                        for ref, _bucket in by_id.values()
                        if self._matched_query_root_count(ref) > 1
                    ],
                ]
            ),
            "dedupe_groups": dedupe_groups,
            "downranked_memory_ids": self._unique(downranked_ids),
            "previous_scene_anchor_memory_ids": self._unique(previous_scene_anchor_ids),
            "repeat_risk_memory_ids": self._unique(repeat_risk_ids),
            "normalization_applied": True,
        }
        return {
            **output,
            "memory_context_dedupe_report": report,
        }

    def _select_primary_memory_ref(
        self,
        group: list[tuple[MemoryPackSourceRef, str]],
        *,
        role_priority: dict[str, int],
        importance_priority: dict[str, int],
        required_ids: set[str],
    ) -> tuple[MemoryPackSourceRef, str]:
        def sort_key(item: tuple[MemoryPackSourceRef, str]) -> tuple[int, int, str]:
            ref, bucket = item
            required_rank = 0 if ref.memory_id.casefold() in required_ids else 1
            return (
                required_rank,
                role_priority.get(bucket, 9),
                importance_priority.get(ref.importance, 2),
                ref.memory_id,
            )

        primary_ref, primary_bucket = sorted(group, key=sort_key)[0]
        merged = primary_ref
        for ref, _bucket in group:
            if ref.memory_id == primary_ref.memory_id:
                continue
            merged = self._merge_ref_metadata(merged, ref)
        return merged, primary_bucket

    def _merge_ref_metadata(
        self,
        base: MemoryPackSourceRef,
        other: MemoryPackSourceRef,
    ) -> MemoryPackSourceRef:
        return self._ref_with_updates(
            base,
            matched_by=self._unique([*base.matched_by, *other.matched_by]),
            keywords=self._unique([*base.keywords, *other.keywords])[:12],
            duplicate_memory_ids=self._unique(
                [
                    *base.duplicate_memory_ids,
                    *other.duplicate_memory_ids,
                    *(
                        [other.memory_id]
                        if other.memory_id and other.memory_id != base.memory_id
                        else []
                    ),
                ]
            ),
            source_scene_id=base.source_scene_id or other.source_scene_id,
        )

    def _near_duplicate_memory_ref(
        self,
        left: MemoryPackSourceRef,
        right: MemoryPackSourceRef,
    ) -> bool:
        if not left.memory_id or not right.memory_id or left.memory_id == right.memory_id:
            return False
        if (
            left.source_object_id
            and right.source_object_id
            and left.source_object_id == right.source_object_id
            and (left.source_object_type or "") == (right.source_object_type or "")
        ):
            return self._summary_similarity(left.summary, right.summary) >= 0.42
        if left.source_scene_id and left.source_scene_id == right.source_scene_id:
            return self._summary_similarity(left.summary, right.summary) >= 0.58
        return False

    def _matched_query_root_count(self, ref: MemoryPackSourceRef) -> int:
        roots: set[str] = set()
        for item in ref.matched_by:
            label = str(item or "").casefold()
            if label.startswith("character_ids:"):
                roots.add("character_ids")
            elif label.startswith("relationship_ids:"):
                roots.add("relationship_ids")
            elif label.startswith("event_ids:"):
                roots.add("event_ids")
            elif label.startswith("keyword:"):
                roots.add("keywords")
            elif label in {"scene_id", "location", "memory_type", "status"}:
                roots.add(label)
        return len(roots)

    def _summary_similarity(self, left: str, right: str) -> float:
        left_tokens = set(self._keyword_tokens(left))
        right_tokens = set(self._keyword_tokens(right))
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))

    def _previous_scene_ref(
        self,
        ref: MemoryPackSourceRef,
        current_scene_id: str | None,
    ) -> bool:
        source_scene_id = str(ref.source_scene_id or "").strip()
        if not source_scene_id:
            return False
        current = str(current_scene_id or "").strip()
        return bool(not current or source_scene_id != current)

    def _role_from_bucket(self, bucket_name: str) -> str:
        return {
            "must_use_context": "must_use",
            "should_use_context": "should_use",
            "optional_context": "optional",
            "forbidden_or_conflict_context": "forbidden_or_conflict",
        }.get(bucket_name, "optional")

    def _dedupe_group_id(
        self,
        chapter_id: str,
        scene_index: int,
        group_index: int,
        group: list[tuple[MemoryPackSourceRef, str]],
    ) -> str:
        stem = "_".join(
            self._unique(
                [
                    chapter_id,
                    str(scene_index),
                    str(group_index),
                    *[ref.memory_id for ref, _bucket in group],
                ]
            )
        )
        return f"memory_dedupe_{self._slug(stem)[:80]}"

    def _ref_with_updates(
        self,
        ref: MemoryPackSourceRef,
        **updates: Any,
    ) -> MemoryPackSourceRef:
        if hasattr(ref, "model_copy"):
            return ref.model_copy(update=updates)
        return ref.copy(update=updates)

    def _is_cross_chapter_ref(
        self,
        ref: MemoryPackSourceRef,
        current_chapter_id: str,
    ) -> bool:
        current = self._chapter_number_token(current_chapter_id)
        if not current:
            return False
        probe = " ".join(
            [
                ref.memory_id,
                ref.source_object_id,
                ref.reason,
                *ref.matched_by,
                *ref.keywords,
            ]
        )
        chapter_tokens = {
            token
            for token in (
                self._chapter_number_token(match.group(0))
                for match in re.finditer(r"chapter_(?:m6_)?\d+", probe, flags=re.IGNORECASE)
            )
            if token
        }
        return bool(chapter_tokens and current not in chapter_tokens)

    def _chapter_number_token(self, value: str) -> str:
        match = re.search(r"chapter_(?:m6_)?(\d+)", str(value or ""), flags=re.IGNORECASE)
        if not match:
            return ""
        digits = match.group(1).lstrip("0")
        return digits or "0"

    def _background_continuity_ref(
        self,
        ref: MemoryPackSourceRef,
    ) -> MemoryPackSourceRef:
        reason = ref.reason or ""
        if "background continuity only" not in reason.casefold():
            reason = self._short_text(
                f"{reason}; background continuity only - do not replay as current scene goal.",
                max_len=180,
            )
        try:
            if hasattr(ref, "model_copy"):
                return ref.model_copy(update={"reason": reason})
            return ref.copy(update={"reason": reason})
        except Exception:
            return MemoryPackSourceRef(**{**ref.dict(), "reason": reason})

    def _chapter_pack_refs(self, chapter_pack) -> list[MemoryPackSourceRef]:
        return self._dedupe_refs(
            [
                *chapter_pack.world_context,
                *chapter_pack.character_context,
                *chapter_pack.relationship_context,
                *chapter_pack.event_context,
                *chapter_pack.framework_context,
            ]
        )

    def _relationship_ids_for_characters(
        self,
        character_ids: list[str],
        relationships: list[dict[str, Any]],
    ) -> list[str]:
        characters = set(character_ids)
        return self._unique(
            [
                str(relationship.get("relationship_id") or "")
                for relationship in relationships
                if relationship.get("status", "confirmed") == "confirmed"
                and (
                    relationship.get("source_id") in characters
                    or relationship.get("target_id") in characters
                )
            ]
        )

    def _framework_text(self, framework: dict[str, Any]) -> str:
        chunks: list[str] = []
        for module in framework.get("modules") or []:
            chunks.append(str(module.get("label") or ""))
            for component in module.get("components") or []:
                chunks.append(str(component.get("label") or ""))
                chunks.append(str(component.get("normalized_hint") or ""))
        return " ".join(chunk for chunk in chunks if chunk)

    def _world_rule_text(self, world_canvas: dict[str, Any]) -> str:
        return " ".join(
            [
                str(rule.get("rule_id") or "") + " " + str(rule.get("statement") or "")
                for rule in world_canvas.get("hard_rules") or []
                if isinstance(rule, dict)
            ]
        )

    def _gap(
        self,
        gap_type: str,
        *,
        chapter_id: str = "",
        scene_id: str | None = None,
        character_ids: list[str] | None = None,
        location: str | None = None,
        keywords: list[str] | None = None,
        message: str,
        suggested_action: str,
        severity: str = "warning",
    ) -> RetrievalGap:
        stem = "_".join(
            self._unique(
                [
                    gap_type,
                    chapter_id,
                    scene_id or "",
                    location or "",
                    *(character_ids or []),
                    *(keywords or []),
                ]
            )
        )
        return RetrievalGap(
            gap_id=f"gap_{self._slug(stem)[:80]}",
            gap_type=gap_type,
            severity=severity,
            query_intent=gap_type,
            message=message,
            related_chapter_id=chapter_id or None,
            related_scene_id=scene_id,
            related_character_ids=character_ids or [],
            related_location=location,
            related_keywords=keywords or [],
            suggested_action=suggested_action,
            created_at=utc_now(),
        )

    def _dedupe_refs(self, refs: list[MemoryPackSourceRef]) -> list[MemoryPackSourceRef]:
        by_id: dict[str, MemoryPackSourceRef] = {}
        for ref in refs:
            if ref.memory_id and ref.memory_id not in by_id:
                by_id[ref.memory_id] = ref
        return list(by_id.values())

    def _dedupe_gaps(self, gaps: list[RetrievalGap]) -> list[RetrievalGap]:
        by_id: dict[str, RetrievalGap] = {}
        for gap in gaps:
            by_id.setdefault(gap.gap_id, gap)
        return list(by_id.values())

    def _limit_refs(
        self,
        refs: list[MemoryPackSourceRef],
        limit: int,
    ) -> list[MemoryPackSourceRef]:
        priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(
            self._dedupe_refs(refs),
            key=lambda ref: (
                priority.get(ref.importance, 2),
                ref.memory_id,
            ),
        )[:limit]

    def _keyword_tokens(self, text: str) -> list[str]:
        cleaned = "".join(
            char if char.isalnum() or char in {"_", "-"} else " "
            for char in str(text or "")
        )
        return self._unique(
            [
                token
                for token in cleaned.split()
                if len(token) >= 3 and len(token) <= 40
            ]
        )[:20]

    def _short_text(self, text: str, *, max_len: int = 240) -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) <= max_len:
            return clean
        return clean[: max_len - 3].rstrip() + "..."

    def _unique(self, values: list[Any]) -> list[str]:
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

    def _slug(self, value: str) -> str:
        return "".join(
            char if char.isalnum() or char in {"_", "-"} else "_"
            for char in value
        ).strip("_") or "unknown"

    def _norm(self, value: Any) -> str:
        return str(value or "").strip().casefold()
