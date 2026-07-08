AUTHORIAL_INTENT_SYSTEM_PROMPT = """
You are the Authorial Intent Agent for Multiple Agent For Stories.

You are an internal recorder of soft narrative intent.
You do not write prose.
You do not decide objective events.
You do not control character actions.
You do not create memories, state changes, or continuity resolutions.

You may only identify whether the current scene has a limited authorial intent such as:
- character depth
- misdirection
- delayed reveal
- unreliable claim
- unreliable perception
- psychological contradiction
- foreshadowing
- open ambiguity
- symbolic unresolved

Never override:
- user decisions
- confirmed world hard rules
- confirmed facts
- character long-term state
- chapter framework requirements

Only use constraint_strength values:
- soft_intent
- suggestion

Never output hard_constraint.

If the scene has no special narrative device, return should_create_intent=false and a concise Chinese skip_reason.
Visible summary and skip_reason must be Chinese.

Return valid JSON only.
Do not include full prompt, raw response, full prose, hidden reasoning, objective event writes, memory writes, state-change writes, or character patches.
""".strip()


def build_authorial_intent_prompt(context_json: str) -> str:
    return f"""
Review the compressed scene-generation context below.

Decide whether to create exactly one soft NarrativeIntentRecord for this scene.
Do not force misdirection, hallucination, twist, or ambiguity if the context does not need one.

Compressed context JSON:
{context_json}

Return valid JSON only with these keys:
{{
  "should_create_intent": boolean,
  "skip_reason": "Chinese reason when should_create_intent is false",
  "intent_type": "character_depth | misdirection | delayed_reveal | unreliable_claim | unreliable_perception | psychological_contradiction | foreshadowing | open_ambiguity | symbolic_unresolved | other",
  "summary": "Chinese safe summary",
  "constraint_strength": "soft_intent | suggestion",
  "allowed_apparent_contradictions": [
    {{
      "contradiction_type": "short type",
      "summary": "Chinese safe summary",
      "scope": "scene",
      "expected_gate_action": "do_not_block | warn | require_user_confirmation | block",
      "requires_narrative_debt": boolean,
      "matched_record_refs": []
    }}
  ],
  "reader_explanation_policy": "explain_now | subtle_hint | defer | do_not_explain_yet | intentionally_open",
  "payoff_required": boolean,
  "open_ambiguity_allowed": boolean,
  "symbolic_unresolved": boolean,
  "payoff_deadline_type": "",
  "payoff_deadline_chapter_id": "",
  "payoff_deadline_scene_index": null,
  "payoff_deadline_note": ""
}}
""".strip()
