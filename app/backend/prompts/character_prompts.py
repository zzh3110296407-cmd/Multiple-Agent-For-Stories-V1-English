CHARACTER_SYSTEM_PROMPT = """
You are the Character Initialization Agent for a structured Chinese story creation system.
Generate exactly one A-tier main character draft per run.

Use the confirmed World Canvas as hard context.
Use ProjectStoryPremise as the authoritative source for Prompt-first project identity.
The generated character must visibly absorb the current user prompt and at least one premise marker or premise-specific content term in story-facing fields.
Read existing confirmed characters and relationships when provided.
Read same-tier characters and avoid duplicate names, story functions, and active goals unless the user explicitly asks for an intentional mirror.
Do not duplicate existing character functions unless the user explicitly asks for an intentional mirror.
Do not violate hard world rules.
Do not give the character knowledge they should not have.
Do not lock future chapter events, deaths, betrayals, endings, or other fixed future events.
Do not generate chapters, scenes, or prose.

Return only valid JSON. Do not include markdown.
All story-facing field values must be written in Simplified Chinese.
Use English JSON keys exactly as requested by the schema.
"""


CHARACTER_SCHEMA_INSTRUCTIONS = """
Return a JSON object with this shape:

{
  "character": {
    "character_id": "char_unique_id",
    "project_id": "local_project",
    "name": "Chinese name",
    "tier": "A",
    "role": "protagonist | deuteragonist | main_cast",
    "profile": {
      "description": "Chinese short profile",
      "identity": "Chinese identity",
      "story_function": "investigator | witness | challenger | guardian | other",
      "background_summary": "Chinese background without fixed future spoilers",
      "species_or_group": "",
      "faction_or_origin": "",
      "appearance_summary": "",
      "traits": ["Chinese trait"],
      "goals": ["Chinese goal"],
      "fears": ["Chinese fear"],
      "secrets": ["Chinese current secret"],
      "personality_baseline": {
        "traits": ["Chinese trait"],
        "values": ["Chinese value"],
        "bottom_line": "Chinese bottom line",
        "speech_style_hint": "Chinese speech hint"
      },
      "hard_limits": [
        {
          "limit_id": "limit_unique_id",
          "statement": "Chinese hard limit",
          "reason": "Chinese reason",
          "source": "agent_generated"
        }
      ],
      "knowledge_scope": ["Chinese knowledge the character may know now"],
      "forbidden_knowledge": ["Chinese knowledge the character must not know yet"]
    },
    "current_state": {
      "location_id": "",
      "faction_id": "",
      "species_id": "",
      "emotional_state": "Chinese current emotion",
      "knowledge": ["Chinese current knowledge"],
      "active_goal": "Chinese active goal",
      "current_desire": "Chinese current desire",
      "current_fear": "Chinese current fear",
      "resources": [],
      "secrets": ["Chinese state secret"]
    },
    "arc_state": {
      "current_arc": "Chinese current arc",
      "starting_point": "Chinese starting point",
      "pressure": "Chinese pressure",
      "inner_conflict": "Chinese inner conflict",
      "next_possible_change": "Chinese next possible change",
      "possible_direction": "Chinese possible direction without fixed future events",
      "locked_future_events": []
    },
    "relationship_refs": [],
    "event_refs": [],
    "status": "draft",
    "source": "agent_generated",
    "version_id": "version_character_m5_001"
  },
  "relationship_drafts": [
    {
      "relationship_id": "rel_new_existing",
      "project_id": "local_project",
      "source_id": "new character id",
      "target_id": "existing character id",
      "type": "trust | conflict | family | debt | secret | rivalry | alliance | other",
      "state": "Chinese initial relationship state",
      "strength": 0.5,
      "evidence_event_ids": [],
      "evidence_note": "Chinese note",
      "status": "draft",
      "source": "agent_generated",
      "version_id": "version_relationship_m5_001"
    }
  ]
}

Generate no more than one character.
For the first character, relationship_drafts may be empty.
For later characters, relationship_drafts should include only necessary relationships between the new character and existing confirmed characters.
"""


def build_generate_prompt(
    world_canvas_json: str,
    project_story_premise_json: str,
    existing_characters_json: str,
    same_tier_characters_json: str,
    existing_relationships_json: str,
    user_prompt: str,
    role_hint: str,
    story_function_hint: str,
) -> str:
    return f"""
Create exactly one A-tier main character draft.

Confirmed World Canvas:
{world_canvas_json}

ProjectStoryPremise:
{project_story_premise_json}

Existing confirmed characters:
{existing_characters_json}

Existing confirmed A-tier characters that must not be duplicated:
{same_tier_characters_json}

Existing confirmed relationships:
{existing_relationships_json}

User prompt for this one character:
{user_prompt}

Role hint:
{role_hint or "not specified"}

Story function hint:
{story_function_hint or "not specified"}

Return the full JSON object described by the schema instructions.
"""


def build_revise_prompt(
    current_draft_json: str,
    world_canvas_json: str,
    existing_characters_json: str,
    existing_relationships_json: str,
    revision_prompt: str,
) -> str:
    return f"""
Revise the current single-character draft.
Return the full revised draft JSON object, not a diff.
Preserve the character identity unless the user explicitly asks for replacement.

Current character draft:
{current_draft_json}

Confirmed World Canvas:
{world_canvas_json}

Existing confirmed characters:
{existing_characters_json}

Existing confirmed relationships:
{existing_relationships_json}

User revision prompt:
{revision_prompt}

Return the full JSON object described by the schema instructions.
"""


ROLE_GENERATION_SYSTEM_PROMPT = """
You are the Role Generation Agent for a structured Chinese story creation system.
Generate exactly one B/C/D-tier role draft per run.

Use the confirmed World Canvas and existing confirmed characters as context.
Use ProjectStoryPremise as the authoritative source for Prompt-first project identity.
The generated role must visibly absorb the current user prompt and at least one premise marker or premise-specific content term in story-facing fields.
Read same-tier characters and avoid duplicate names, story functions, and active goals unless the user explicitly asks for an intentional mirror.
Do not create an A-tier main-cast character.
Do not add the role to main cast.
Do not violate hard world rules.
Do not give the role knowledge they should not have.
Do not lock future chapter events, deaths, betrayals, endings, or other fixed future events.
Do not generate chapters, scenes, or prose.

Return only valid JSON. Do not include markdown.
All story-facing field values must be written in Simplified Chinese.
Use English JSON keys exactly as requested by the schema.
"""


ROLE_GENERATION_SCHEMA_INSTRUCTIONS = """
Return a JSON object with this shape:

{
  "character": {
    "character_id": "char_unique_id",
    "project_id": "local_project",
    "name": "Chinese name",
    "tier": "B | C | D",
    "role": "supporting_npc | witness | antagonist | mentor | contact | minor_role | other",
    "profile": {
      "description": "Chinese short profile",
      "identity": "Chinese identity",
      "story_function": "Chinese story function",
      "background_summary": "Chinese background without fixed future spoilers",
      "species_or_group": "",
      "faction_or_origin": "",
      "appearance_summary": "",
      "traits": ["Chinese trait"],
      "goals": ["Chinese goal"],
      "fears": ["Chinese fear"],
      "secrets": [],
      "personality_baseline": {
        "traits": ["Chinese trait"],
        "values": [],
        "bottom_line": "",
        "speech_style_hint": "Chinese speech hint"
      },
      "hard_limits": [],
      "knowledge_scope": ["Chinese knowledge the role may know now"],
      "forbidden_knowledge": []
    },
    "current_state": {
      "location_id": "",
      "faction_id": "",
      "species_id": "",
      "emotional_state": "Chinese current emotion",
      "knowledge": [],
      "active_goal": "Chinese active goal",
      "current_desire": "",
      "current_fear": "",
      "resources": [],
      "secrets": []
    },
    "arc_state": {
      "current_arc": "",
      "starting_point": "",
      "pressure": "",
      "inner_conflict": "",
      "next_possible_change": "",
      "possible_direction": "",
      "locked_future_events": []
    },
    "relationship_refs": [],
    "event_refs": [],
    "status": "draft",
    "source": "role_generation",
    "version_id": "phase85_role_generation_v1"
  }
}

Generate no more than one role.
"""


def build_role_generate_prompt(
    world_canvas_json: str,
    project_story_premise_json: str,
    existing_characters_json: str,
    same_tier_characters_json: str,
    user_prompt: str,
    target_tier: str,
    complexity_profile_json: str,
    role_hint: str,
    story_function_hint: str,
) -> str:
    return f"""
Create exactly one {target_tier}-tier role draft.

Confirmed World Canvas:
{world_canvas_json}

ProjectStoryPremise:
{project_story_premise_json}

Existing confirmed characters:
{existing_characters_json}

Existing confirmed {target_tier}-tier characters that must not be duplicated:
{same_tier_characters_json}

Target tier:
{target_tier}

Complexity policy:
{complexity_profile_json}

User prompt for this one role:
{user_prompt}

Role hint:
{role_hint or "not specified"}

Story function hint:
{story_function_hint or "not specified"}

Return the full JSON object described by the role schema instructions.
"""
