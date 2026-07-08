CHAPTER_SYSTEM_PROMPT = """
You are the Chapter Planning Agent for Multiple Agent For Stories.

Create a lightweight chapter route and a current chapter brief.

Do not write story prose.
Do not generate scene prose.
Do not create full future chapter modules/components.
Do not create full future scene plans.
Do not lock future character deaths, betrayals, endings, awakenings, or exact reveals.
Do not violate confirmed World Canvas hard rules.
Do not give characters knowledge they should not have.

Return only valid JSON. Do not include markdown.
Story-facing field values must be written in Simplified Chinese.
Use English JSON keys exactly as requested by the schema.
"""


CHAPTER_SCHEMA_INSTRUCTIONS = """
Return a JSON object with this shape:

{
  "story_goal": "Chinese story goal",
  "chapter_routes": [
    {
      "chapter_index": 1,
      "temporary_title": "Chinese temporary title",
      "linked_macro_component_ids": ["macro_opening"],
      "macro_component_label": "Chinese macro label",
      "light_route_summary": "Chinese light route summary",
      "narrative_function": "Chinese narrative function",
      "expected_focus_character_ids": ["A-tier char_id only"],
      "expected_supporting_role_ids": ["B-tier char_id only"],
      "cd_role_function_need_hints": [
        {
          "need_id": "cd_need_001",
          "scene_index": null,
          "tier_preference": "C_or_D",
          "function_type": "local_witness",
          "function_summary": "Chinese role function summary",
          "reason": "Chinese reason",
          "location_hint": "Chinese location hint",
          "relationship_hint": "",
          "knowledge_need": "Chinese knowledge need",
          "reuse_existing_preferred": true,
          "must_not_bind_specific_character_id": true,
          "resolved_by_scene_agent": true
        }
      ],
      "expected_conflict_hint": "Chinese conflict hint",
      "detail_level": "light",
      "future_lock_level": "low"
    }
  ],
  "current_chapter_brief": {
    "chapter_index": 1,
    "title": "Chinese current chapter title",
    "linked_macro_component_ids": ["macro_opening"],
    "chapter_framework_id": "chapter_fw_001",
    "chapter_goal": "Chinese chapter goal",
    "reader_emotion_goal": ["Chinese reader emotion"],
    "participating_character_ids": ["A/B explicit chapter participant char_id"],
    "main_cast_character_ids": ["A-tier char_id only"],
    "supporting_role_ids": ["B-tier char_id only"],
    "supporting_role_refs": [
      {
        "character_id": "B-tier char_id only",
        "tier": "B",
        "role_in_chapter": "Chinese supporting role function",
        "participation_reason": "Chinese reason",
        "related_main_cast_ids": ["A-tier char_id only"],
        "expected_scene_indices": [1],
        "context_depth": "medium"
      }
    ],
    "supporting_role_function_focus": [
      {
        "character_id": "B-tier char_id only",
        "function_focus": "Chinese B-tier function focus",
        "relationship_pressure": "Chinese relationship pressure",
        "expected_chapter_effect": "Chinese expected effect"
      }
    ],
    "cd_role_function_needs": [
      {
        "need_id": "cd_need_001",
        "scene_index": null,
        "tier_preference": "C_or_D",
        "function_type": "local_witness",
        "function_summary": "Chinese role function summary",
        "reason": "Chinese reason",
        "location_hint": "Chinese location hint",
        "relationship_hint": "",
        "knowledge_need": "Chinese knowledge need",
        "reuse_existing_preferred": true,
        "must_not_bind_specific_character_id": true,
        "resolved_by_scene_agent": true
      }
    ],
    "main_conflict": "Chinese main conflict",
    "character_desire_or_arc_focus": [
      {
        "character_id": "A-tier char_id only",
        "desire": "Chinese current desire",
        "arc_focus": "Chinese current arc focus"
      }
    ],
    "world_rules_to_respect": ["Chinese hard rule statement"],
    "forbidden_moves": ["Chinese forbidden move"],
    "recommended_scene_count": 3,
    "user_selected_scene_count": null,
    "chapter_scene_beats": [
      {
        "beat_id": "chapter_001_scene_beat_001",
        "chapter_id": "chapter_001",
        "scene_index": 1,
        "scene_count": 3,
        "scene_function": "Chinese scene responsibility, not scene prose",
        "function_family": "open",
        "required_progression_delta": {
          "new_information": "Chinese new information delta",
          "character_state_delta": "Chinese pressure, choice, relationship, or knowledge-boundary delta",
          "conflict_turn": "Chinese conflict turn",
          "cost_or_risk_delta": "Chinese cost or risk delta"
        },
        "continuity_anchors": {
          "carry_forward_threads": ["Chinese thread summary"],
          "allowed_returning_characters": ["A/B explicit chapter participant char_id only"],
          "allowed_returning_locations": [],
          "required_memory_refs": []
        },
        "stage_strategy": {
          "location_strategy": "open",
          "time_delta": "must_make_time_relation_clear",
          "action_mode": "open",
          "atmosphere_delta": "optional"
        },
        "autonomy_space": {
          "character_action_freedom": "high",
          "optional_detours_allowed": true,
          "cd_role_slots_open": true
        },
        "avoid_repetition_axes": ["scene_function", "new_information", "conflict_turn", "ending_hook"],
        "ending_hook_requirement": "Chinese next-scene hook responsibility",
        "source_refs": ["chapter_plan_agent"]
      }
    ],
    "summary_for_scene_generation": "Chinese executable summary for scene generation"
  }
}

The chapter_routes array must have exactly chapter_count items.
Future chapters must stay light: no scene list, no full chapter module list, no full component list.
Only the current chapter may use the supplied current chapter framework draft.
participating_character_ids must contain only A/B explicit chapter participants and at least one A-tier id.
main_cast_character_ids and character_desire_or_arc_focus are A-tier only.
supporting_role_ids, supporting_role_refs, and supporting_role_function_focus are B-tier only.
C/D roles must appear only as cd_role_function_needs or route cd_role_function_need_hints.
Never output concrete C/D character ids, character_id, selected_character_id, or role_id inside any C/D function need.
chapter_scene_beats must contain exactly one entry per current chapter scene.
Each chapter_scene_beats scene_function must be unique within the current chapter.
Adjacent chapter_scene_beats must differ in at least one of required_progression_delta.new_information, required_progression_delta.character_state_delta, required_progression_delta.conflict_turn, required_progression_delta.cost_or_risk_delta, ending_hook_requirement, or function_family.
Reusing the same A/B characters, same thread, same location, or same atmosphere is allowed only when the beat explains a new progression delta.
chapter_scene_beats define scene responsibility only; do not write scene prose, exact dialogue, or exact fixed character actions.
chapter_scene_beats must not lock exact future reveals, exact future solutions, or exact future action order.
chapter_scene_beats continuity_anchors.allowed_returning_characters may contain only A/B explicit current-chapter participant ids.
Do not bind concrete C/D character ids anywhere in chapter_scene_beats.
C/D roles must stay as unbound function needs or route hints, never concrete ids inside chapter_scene_beats.
Use story-facing Simplified Chinese for chapter_scene_beats values except structural enum-like fields such as function_family, action_mode, and character_action_freedom.
"""


def build_generate_prompt(
    world_canvas_json: str,
    confirmed_main_cast_json: str,
    confirmed_supporting_roles_json: str,
    cd_role_function_policy_json: str,
    confirmed_relationships_json: str,
    framework_package_json: str,
    macro_assignments_json: str,
    current_chapter_framework_json: str,
    generator_framework_context_json: str,
    project_story_premise_json: str,
    story_goal: str,
    chapter_count: int,
    current_chapter_index: int,
) -> str:
    return f"""
Create a lightweight chapter route and an executable current chapter brief.

Confirmed World Canvas:
{world_canvas_json}

Confirmed A-tier main cast:
{confirmed_main_cast_json}

Confirmed B-tier supporting roles:
{confirmed_supporting_roles_json}

C/D role function policy:
{cd_role_function_policy_json}

C/D policy rules:
- Do not select concrete C/D character ids.
- Do not mention C/D profile, memory, psychology, or past behavior.
- You may propose cd_role_function_needs.
- These needs will be resolved later by SceneAgent.

Confirmed relationships:
{confirmed_relationships_json}

Framework package:
{framework_package_json}

Chapter macro assignments:
{macro_assignments_json}

Current chapter framework draft:
{current_chapter_framework_json}

Confirmed generator framework context:
{generator_framework_context_json}

Generator framework context rules:
- Use chapter_framework_context.items as confirmed composition guidance for the current chapter.
- Use global_framework_context.items only as high-level pressure/rhythm guidance.
- Do not read or infer from analyzer handoff files directly.
- Do not add generator_framework_context fields to the returned JSON; the service records composition refs.

Authoritative ProjectStoryPremise:
{project_story_premise_json}

ProjectStoryPremise rules:
- Treat ProjectStoryPremise as the authoritative source for premise, setting, conflict, and required story elements.
- story_goal can focus the current task, but it must not replace or dilute ProjectStoryPremise.
- Every chapter route and current chapter brief must preserve at least one concrete premise marker or term.
- A/B participants must use confirmed character ids only.
- C/D roles must remain function needs only; do not bind concrete C/D ids.

Story goal:
{story_goal}

chapter_count:
{chapter_count}

current_chapter_index:
{current_chapter_index}

Return the full JSON object described by the schema instructions.
"""


def build_revise_prompt(
    current_draft_json: str,
    world_canvas_json: str,
    confirmed_main_cast_json: str,
    confirmed_supporting_roles_json: str,
    cd_role_function_policy_json: str,
    confirmed_relationships_json: str,
    framework_package_json: str,
    current_chapter_framework_json: str,
    generator_framework_context_json: str,
    project_story_premise_json: str,
    revision_prompt: str,
) -> str:
    return f"""
Revise the current chapter plan draft.
Return the full revised draft JSON object, not a diff.
Keep future chapters lightweight.

Current chapter plan draft:
{current_draft_json}

Confirmed World Canvas:
{world_canvas_json}

Confirmed A-tier main cast:
{confirmed_main_cast_json}

Confirmed B-tier supporting roles:
{confirmed_supporting_roles_json}

C/D role function policy:
{cd_role_function_policy_json}

C/D policy rules:
- Do not select concrete C/D character ids.
- Do not mention C/D profile, memory, psychology, or past behavior.
- You may propose cd_role_function_needs.
- These needs will be resolved later by SceneAgent.

Confirmed relationships:
{confirmed_relationships_json}

Framework package:
{framework_package_json}

Current chapter framework draft:
{current_chapter_framework_json}

Confirmed generator framework context:
{generator_framework_context_json}

Generator framework context rules:
- Use chapter_framework_context.items as confirmed composition guidance for the current chapter.
- Use global_framework_context.items only as high-level pressure/rhythm guidance.
- Do not read or infer from analyzer handoff files directly.
- Do not add generator_framework_context fields to the returned JSON; the service records composition refs.

Authoritative ProjectStoryPremise:
{project_story_premise_json}

ProjectStoryPremise rules:
- Treat ProjectStoryPremise as the authoritative source for premise, setting, conflict, and required story elements.
- revision_prompt can focus the change, but it must not replace or dilute ProjectStoryPremise.
- Routes and current chapter brief must preserve premise markers or terms.
- A/B participants must use confirmed character ids only.
- C/D roles must remain function needs only; do not bind concrete C/D ids.

User revision prompt:
{revision_prompt}

Return the full JSON object described by the schema instructions.
"""
