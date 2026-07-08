from typing import Any

from pydantic import BaseModel

from app.backend.models.character import (
    Character,
    CharacterContextBudget,
    CharacterContextItem,
)
from app.backend.models.relationship import Relationship


DEFAULT_ROLE_TIER_BUDGETS: dict[str, CharacterContextBudget] = {
    "A": CharacterContextBudget(
        max_character_tokens=1200,
        include_recent_events=8,
        include_relationships=True,
        include_memory_summary=True,
        include_arc_state=True,
        include_forbidden_knowledge=True,
        include_full_profile=True,
    ),
    "B": CharacterContextBudget(
        max_character_tokens=700,
        include_recent_events=5,
        include_relationships=True,
        include_memory_summary=True,
        include_arc_state=False,
        include_forbidden_knowledge=True,
        include_full_profile=False,
    ),
    "C": CharacterContextBudget(
        max_character_tokens=400,
        include_recent_events=3,
        include_relationships="current_scene_only",
        include_memory_summary="short",
        include_arc_state=False,
        include_forbidden_knowledge="critical_only",
        include_full_profile=False,
    ),
    "D": CharacterContextBudget(
        max_character_tokens=180,
        include_recent_events=1,
        include_relationships=False,
        include_memory_summary=False,
        include_arc_state=False,
        include_forbidden_knowledge="minimal",
        include_full_profile=False,
    ),
}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class RoleTierBudgetService:
    def default_budgets(self) -> dict[str, CharacterContextBudget]:
        return {
            tier: CharacterContextBudget(**model_to_dict(budget))
            for tier, budget in DEFAULT_ROLE_TIER_BUDGETS.items()
        }

    def budget_for_character(self, character: Character) -> CharacterContextBudget:
        base = self.default_budgets().get(character.tier, self.default_budgets()["A"])
        if character.context_budget.max_character_tokens <= 0:
            return base
        override = model_to_dict(character.context_budget)
        clean_override = {
            key: value
            for key, value in override.items()
            if value not in ("", 0, None, [], {})
        }
        if not clean_override:
            return base
        data = model_to_dict(base)
        data.update(clean_override)
        return CharacterContextBudget(**data)

    def build_context_item(
        self,
        *,
        character: Character,
        relationships: list[Relationship],
        recent_memory_refs: list[dict[str, Any]],
        omitted: list[str] | None = None,
    ) -> CharacterContextItem:
        budget = self.budget_for_character(character)
        omitted_due_to_budget = list(omitted or [])

        relationship_summary = self._relationship_summary(
            relationships,
            character.character_id,
            budget.include_relationships,
            omitted_due_to_budget,
        )
        memory_summary = self._memory_summary(
            character,
            budget.include_memory_summary,
            omitted_due_to_budget,
        )
        profile_summary = self._profile_summary(
            character,
            bool(budget.include_full_profile),
            omitted_due_to_budget,
        )
        arc_summary = self._arc_summary(
            character,
            budget.include_arc_state,
            omitted_due_to_budget,
        )
        forbidden_knowledge = self._forbidden_knowledge(
            character,
            budget.include_forbidden_knowledge,
            omitted_due_to_budget,
        )
        hard_limits = self._hard_limits(
            character,
            budget.include_forbidden_knowledge,
            omitted_due_to_budget,
        )
        recent_refs = recent_memory_refs[: max(0, int(budget.include_recent_events))]
        if len(recent_memory_refs) > len(recent_refs):
            omitted_due_to_budget.append("recent_memory_refs_truncated")

        item = CharacterContextItem(
            character_id=character.character_id,
            name=character.name,
            tier=character.tier,
            profile_summary=profile_summary,
            current_state_summary=self._current_state_summary(character),
            personality_summary=self._personality_summary(character),
            memory_summary=memory_summary,
            relationship_summary=relationship_summary,
            arc_summary=arc_summary,
            forbidden_knowledge=forbidden_knowledge,
            hard_limits=hard_limits,
            recent_memory_refs=recent_refs,
            source_memory_ids=self._unique(
                [str(ref.get("memory_id") or "") for ref in recent_refs]
            ),
            budget_applied=model_to_dict(budget),
            omitted_due_to_budget=self._unique(omitted_due_to_budget),
        )
        return self._enforce_size_budget(item, budget)

    def estimate_context_size(self, item: CharacterContextItem) -> int:
        text_parts = [
            item.profile_summary,
            item.current_state_summary,
            item.personality_summary,
            item.memory_summary,
            item.relationship_summary,
            item.arc_summary,
            " ".join(item.forbidden_knowledge),
            " ".join(item.hard_limits),
            " ".join(str(ref.get("summary") or "") for ref in item.recent_memory_refs),
        ]
        return max(1, len(" ".join(text_parts)) // 4)

    def _enforce_size_budget(
        self,
        item: CharacterContextItem,
        budget: CharacterContextBudget,
    ) -> CharacterContextItem:
        if self.estimate_context_size(item) <= budget.max_character_tokens:
            return item
        item.omitted_due_to_budget.append("estimated_context_trimmed")
        item.recent_memory_refs = item.recent_memory_refs[: max(0, len(item.recent_memory_refs) // 2)]
        item.source_memory_ids = self._unique(
            [str(ref.get("memory_id") or "") for ref in item.recent_memory_refs]
        )
        for field_name in ("profile_summary", "memory_summary", "relationship_summary"):
            value = getattr(item, field_name)
            if len(value) > 320:
                setattr(item, field_name, value[:317].rstrip() + "...")
        item.omitted_due_to_budget = self._unique(item.omitted_due_to_budget)
        return item

    def _profile_summary(
        self,
        character: Character,
        include_full_profile: bool,
        omitted: list[str],
    ) -> str:
        profile = character.profile
        if include_full_profile:
            return self._join(
                [
                    profile.identity or profile.description,
                    profile.story_function,
                    profile.background_summary,
                    profile.appearance_summary,
                    self._label("goals", profile.goals),
                    self._label("fears", profile.fears),
                ]
            )
        omitted.append("profile_full_details")
        return self._join(
            [
                profile.identity or profile.description,
                profile.story_function,
                self._label("traits", profile.traits[:3]),
            ]
        )

    def _current_state_summary(self, character: Character) -> str:
        state = character.current_state
        return self._join(
            [
                self._pair("location", state.location_id),
                self._pair("emotion", state.emotional_state),
                self._pair("active_goal", state.active_goal or state.current_desire),
                self._pair("fear", state.current_fear),
                self._label("knowledge", state.knowledge[:5]),
                self._label("resources", state.resources[:4]),
            ]
        )

    def _personality_summary(self, character: Character) -> str:
        baseline = character.profile.personality_baseline
        return self._join(
            [
                self._label("traits", baseline.traits[:4]),
                self._label("values", baseline.values[:4]),
                self._pair("bottom_line", baseline.bottom_line),
                self._pair("speech", baseline.speech_style_hint),
            ]
        )

    def _memory_summary(
        self,
        character: Character,
        include_memory_summary: bool | str,
        omitted: list[str],
    ) -> str:
        summary = character.memory_summary.summary
        if include_memory_summary is False:
            omitted.append("memory_summary")
            return ""
        if include_memory_summary == "short" and len(summary) > 180:
            omitted.append("memory_summary_long_form")
            return summary[:177].rstrip() + "..."
        return summary

    def _relationship_summary(
        self,
        relationships: list[Relationship],
        character_id: str,
        include_relationships: bool | str,
        omitted: list[str],
    ) -> str:
        if include_relationships is False:
            omitted.append("relationships")
            return ""
        selected = [
            relationship
            for relationship in relationships
            if character_id in {relationship.source_id, relationship.target_id}
        ]
        if include_relationships == "current_scene_only":
            selected = selected[:2]
            omitted.append("relationships_full_history")
        return " | ".join(
            self._join(
                [
                    relationship.relationship_id,
                    relationship.type,
                    relationship.state,
                    str(relationship.strength),
                ]
            )
            for relationship in selected
        )

    def _arc_summary(
        self,
        character: Character,
        include_arc_state: bool,
        omitted: list[str],
    ) -> str:
        if not include_arc_state:
            omitted.append("arc_state")
            return ""
        arc = character.arc_state
        return self._join(
            [
                arc.current_arc,
                arc.inner_conflict,
                arc.pressure,
                arc.next_possible_change,
                arc.possible_direction,
            ]
        )

    def _forbidden_knowledge(
        self,
        character: Character,
        include_forbidden_knowledge: bool | str,
        omitted: list[str],
    ) -> list[str]:
        items = character.profile.forbidden_knowledge
        if include_forbidden_knowledge is False:
            omitted.append("forbidden_knowledge")
            return []
        if include_forbidden_knowledge == "minimal":
            omitted.append("forbidden_knowledge_full_list")
            return items[:1]
        if include_forbidden_knowledge == "critical_only":
            omitted.append("forbidden_knowledge_full_list")
            return items[:2]
        return items

    def _hard_limits(
        self,
        character: Character,
        include_forbidden_knowledge: bool | str,
        omitted: list[str],
    ) -> list[str]:
        limits = [limit.statement for limit in character.profile.hard_limits if limit.statement]
        if include_forbidden_knowledge is False:
            omitted.append("hard_limits")
            return []
        if include_forbidden_knowledge in {"minimal", "critical_only"}:
            return limits[:1]
        return limits

    def _label(self, label: str, values: list[str]) -> str:
        clean = [str(value) for value in values if value]
        return f"{label}: {', '.join(clean)}" if clean else ""

    def _pair(self, label: str, value: str) -> str:
        return f"{label}: {value}" if value else ""

    def _join(self, values: list[str]) -> str:
        return " | ".join(str(value) for value in values if value)

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
