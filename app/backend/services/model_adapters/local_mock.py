import json
import re

from app.backend.models.model_gateway import ModelGatewayRequest
from app.backend.services.model_adapters.base import ModelAdapter


class LocalMockModelAdapter(ModelAdapter):
    def generate_text(self, request: ModelGatewayRequest) -> str:
        user_messages = [
            message.content for message in request.messages if message.role == "user"
        ]
        prompt_preview = (user_messages[-1] if user_messages else "").strip()
        if len(prompt_preview) > 120:
            prompt_preview = f"{prompt_preview[:117]}..."
        return (
            "Local mock model response. "
            f"model={request.model_name}; messages={len(request.messages)}; "
            f"last_user_message={prompt_preview!r}"
        )

    def generate_json(self, request: ModelGatewayRequest) -> str:
        if request.schema_hint and request.schema_hint.get("kind") == "world_canvas":
            return dump_mock_json(
                build_mock_world_canvas(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "character":
            return dump_mock_json(
                build_mock_character_draft(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "chapter_plan":
            return dump_mock_json(
                build_mock_chapter_plan(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "chapter_framework_builder":
            return dump_mock_json(
                build_mock_chapter_framework(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "scene_information":
            return dump_mock_json(
                build_mock_scene_information(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "authorial_intent":
            return dump_mock_json(
                build_mock_authorial_intent(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "scene_write":
            return dump_mock_json(
                build_mock_scene_write(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "scene_revision":
            return dump_mock_json(
                build_mock_scene_revision(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "scene_memory":
            return dump_mock_json(
                build_mock_scene_memory(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") == "scene_quality":
            return dump_mock_json(
                build_mock_scene_quality(request.schema_hint),
                request.schema_hint,
            )
        if request.schema_hint and request.schema_hint.get("kind") in {
            "quality_semantic_scene",
            "quality_semantic_revision",
        }:
            return dump_mock_json(
                build_mock_quality_semantic(request.schema_hint),
                request.schema_hint,
            )
        return json.dumps(
            {
                "ok": True,
                "adapter": "local_mock",
                "model": request.model_name,
                "message_count": len(request.messages),
            },
            ensure_ascii=False,
        )


def dump_mock_json(payload: dict, schema_hint: dict | None) -> str:
    return json.dumps(payload, ensure_ascii=False)


def project_story_context(schema_hint: dict | None) -> dict:
    schema_hint = schema_hint or {}
    text = _collect_context_text(schema_hint)
    style = _detect_story_style(text)
    core = _extract_focus_phrase(
        text,
        suffixes=["异常", "谜团", "案件", "事故", "危机", "秘密", "记录", "档案", "线索", "灯塔"],
        fallback=style["core_fallback"],
    )
    record_object = _extract_focus_phrase(
        text,
        suffixes=["记录", "档案", "案卷", "地图", "线索", "证词", "手稿", "名单"],
        fallback="关键记录",
    )
    main_location = _extract_focus_phrase(
        text,
        suffixes=[
            "图书馆",
            "观测站",
            "灯塔",
            "港口",
            "城市",
            "小镇",
            "学院",
            "剧院",
            "长安西市",
            "长安",
            "洛阳",
            "西市",
            "东市",
            "道观",
            "驿馆",
            "坊市",
            "宫城",
            "里坊",
            "岛",
            "塔",
            "区",
        ],
        fallback="核心调查区",
    )
    protagonist_role = _extract_character_role(schema_hint, text)
    investigation_object = record_object if record_object != "关键记录" else core
    signal_or_trigger = _extract_focus_phrase(
        text,
        suffixes=["信号", "变化", "回声", "裂缝", "警报", "触发", "鸣响"],
        fallback=f"{record_object}变化" if record_object != "关键记录" else "触发信号",
    )
    return {
        "core_phenomenon": core,
        "mystery_origin": f"{core}真正来源",
        "investigation_object": investigation_object,
        "signal_or_trigger": signal_or_trigger,
        "main_location": main_location,
        "record_object": record_object,
        "protagonist_role": protagonist_role,
        "style": style,
    }


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _detect_story_style(text: str) -> dict:
    source = text or ""
    lowered = source.lower()
    if _contains_any(source, ["唐代", "唐朝", "盛唐", "中唐", "晚唐", "长安", "洛阳", "传奇", "志怪", "进士", "胡商"]):
        return {
            "genre_label": "唐代传奇",
            "tone": "典雅、明朗、奇诡、带盛唐游侠余韵",
            "scene_atmosphere": "典雅奇诡、明暗有度",
            "story_pressure": "奇遇、礼法约束与人物选择",
            "core_fallback": "唐代奇遇",
            "time_label": "华灯初上的唐代坊市",
        }
    if _contains_any(source, ["仙侠", "修真", "宗门", "灵根", "飞升", "剑修"]):
        return {
            "genre_label": "仙侠",
            "tone": "清峻、宏阔、带修行代价",
            "scene_atmosphere": "清峻宏阔、灵气与人心并重",
            "story_pressure": "修行边界、门派规则与道心选择",
            "core_fallback": "修行试炼",
            "time_label": "山门晨钟之后",
        }
    if _contains_any(source, ["武侠", "江湖", "侠客", "镖局", "门派", "刀客"]):
        return {
            "genre_label": "武侠",
            "tone": "豪迈、克制、重信义",
            "scene_atmosphere": "江湖气、动作清楚、情义有重量",
            "story_pressure": "信义、门派恩怨与行动代价",
            "core_fallback": "江湖纠葛",
            "time_label": "风起客栈之前",
        }
    if _contains_any(source, ["爱情", "恋爱", "婚约", "重逢", "告白", "浪漫"]):
        return {
            "genre_label": "情感故事",
            "tone": "温柔、细腻、带克制拉扯",
            "scene_atmosphere": "温柔细腻、情绪递进",
            "story_pressure": "关系误解、选择和靠近",
            "core_fallback": "关系转折",
            "time_label": "一次重逢之后",
        }
    if _contains_any(source, ["科幻", "星际", "飞船", "机器人", "AI", "人工智能", "太空", "星球"]) or any(
        term in lowered for term in ["science fiction", "sci-fi", "spaceship", "robot"]
    ):
        return {
            "genre_label": "科幻",
            "tone": "冷峻、探索、带未知感",
            "scene_atmosphere": "清晰理性、保留未知边界",
            "story_pressure": "技术边界、认知风险与生存选择",
            "core_fallback": "未知技术事件",
            "time_label": "系统警报出现前",
        }
    if _contains_any(source, ["喜剧", "搞笑", "荒诞", "轻松", "日常"]):
        return {
            "genre_label": "轻喜剧",
            "tone": "轻快、荒诞、带温暖收束",
            "scene_atmosphere": "轻快有节奏、冲突不沉重",
            "story_pressure": "误会、反差和小规模选择",
            "core_fallback": "荒诞误会",
            "time_label": "热闹开场之后",
        }
    if _contains_any(source, ["悬疑", "推理", "侦探", "案件", "谋杀", "真相", "谜团"]) or any(
        term in lowered for term in ["mystery", "suspense", "detective", "thriller", "crime"]
    ):
        return {
            "genre_label": "悬疑",
            "tone": "克制、紧张、线索逐步显影",
            "scene_atmosphere": "克制紧张、线索清楚",
            "story_pressure": "线索遮蔽、信息差与调查代价",
            "core_fallback": "核心谜团",
            "time_label": "关键线索出现前",
        }
    return {
        "genre_label": "中文故事",
        "tone": "清晰、克制、随题材调整",
        "scene_atmosphere": "清晰可读、服务当前题材",
        "story_pressure": "目标、阻力与人物选择",
        "core_fallback": "核心事件",
        "time_label": "关键行动开始前",
    }


def project_story_premise_evidence(text: str) -> str:
    if "ProjectStoryPremise" not in (text or ""):
        return ""
    clean = re.sub(r"\s+", " ", text or "").strip()
    start = clean.find("User story premise:")
    if start >= 0:
        clean = clean[start : start + 700]
    return clean[:700]


def _premise_terms_from_payload(payload: dict) -> list[str]:
    if not isinstance(payload, dict):
        return []
    values: list[str] = []
    for key in [
        "prompt_markers_detected",
        "required_markers",
        "required_story_elements",
        "core_terms",
        "setting_terms",
        "conflict_terms",
        "role_terms",
    ]:
        raw = payload.get(key) or []
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item or "").strip())
    if payload.get("safe_user_story_summary"):
        values.append(str(payload.get("safe_user_story_summary")))
    seen: set[str] = set()
    terms: list[str] = []
    for value in values:
        clean = re.sub(r"\s+", " ", value).strip()
        if clean and clean not in seen:
            seen.add(clean)
            terms.append(clean)
    return terms[:16]


def _premise_phrase(schema_hint: dict, fallback: str = "") -> str:
    premise = schema_hint.get("project_story_premise") or {}
    if not isinstance(premise, dict):
        context = schema_hint.get("context") or {}
        premise = context.get("project_story_premise") or {}
    terms = _premise_terms_from_payload(premise)
    if terms:
        return " / ".join(terms[:5])
    return fallback


def _first_prompt_marker(text: str) -> str:
    match = re.search(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,}\b", text or "")
    return match.group(0) if match else ""


def _preferred_character_marker(text: str, target_tier: str = "") -> str:
    source = text or ""
    explicit = re.search(
        r"character\s+marker\s+(?:is|=|:)\s*([A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,})",
        source,
        flags=re.IGNORECASE,
    )
    if explicit:
        return explicit.group(1)
    tier = re.escape((target_tier or "").upper())
    if tier:
        tiered = re.search(
            rf"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_{tier}\d+_CHARACTER(?:_[A-Z0-9]+)+\b",
            source,
        )
        if tiered:
            return tiered.group(0)
    character_marker = re.search(
        r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_[A-D]\d+_CHARACTER(?:_[A-Z0-9]+)+\b",
        source,
    )
    return character_marker.group(0) if character_marker else ""


def _safe_marker_suffix(marker: str, fallback: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", marker or "").strip("_")
    if not clean:
        return fallback
    if len(clean) <= 48:
        return clean
    parts = clean.split("_")
    if len(parts) >= 6:
        return "_".join(parts[:3] + parts[-3:])[:48] or fallback
    return clean[:48] or fallback


def _collect_context_text(value) -> str:
    parts: list[str] = []

    def visit(node) -> None:
        if isinstance(node, str):
            text = node.strip()
            if text:
                parts.append(text)
            return
        if isinstance(node, dict):
            priority_keys = [
                "story_idea",
                "story_goal",
                "user_prompt",
                "story_direction",
                "chapter_goal",
                "main_conflict",
                "summary_for_scene_generation",
                "latest_user_intent_summary",
                "revision_prompt",
            ]
            for key in priority_keys:
                if key in node:
                    visit(node.get(key))
            for key, child in node.items():
                if key not in priority_keys:
                    visit(child)
            return
        if isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return "\n".join(parts)


def _extract_focus_phrase(text: str, *, suffixes: list[str], fallback: str) -> str:
    cleaned = re.sub(r"\s+", "", text or "")
    for suffix in suffixes:
        pattern = rf"[\u4e00-\u9fffA-Za-z0-9]{{1,14}}{re.escape(suffix)}"
        matches = re.findall(pattern, cleaned)
        if matches:
            return _trim_focus_phrase(matches[0], suffix)
    return fallback


def _trim_focus_phrase(value: str, suffix: str) -> str:
    separators = "，。；：、,.!?！？;:（）()[]【】《》\"'“”‘’"
    text = value.strip(separators)
    if len(text) <= 12:
        return _clean_focus_phrase(text)
    suffix_index = text.rfind(suffix)
    if suffix_index < 0:
        return _clean_focus_phrase(text[-12:])
    start = max(0, suffix_index + len(suffix) - 12)
    return _clean_focus_phrase(text[start : suffix_index + len(suffix)])


def _clean_focus_phrase(text: str) -> str:
    cleaned = (text or "").strip()
    if "真相必须被记录" in cleaned or "必须被记录" in cleaned:
        return "关键记录"
    for prefix in (
        "中存在",
        "中出现",
        "里存在",
        "里出现",
        "但近期",
        "但当前",
        "近期",
        "当前",
        "存在",
        "出现",
        "关于",
        "有关",
        "但是",
        "但",
        "然而",
        "不过",
    ):
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix) + 2:
            cleaned = cleaned[len(prefix) :]
    cleaned = re.sub(r"^[\u4e00-\u9fff]{2,4}在(?=[\u4e00-\u9fffA-Za-z0-9]{3,})", "", cleaned)
    return cleaned.strip("的之与和、，。；：,.!?！？;:") or text


def _extract_character_role(schema_hint: dict, text: str) -> str:
    for character in schema_hint.get("confirmed_characters") or []:
        if not isinstance(character, dict):
            continue
        profile = character.get("profile") or {}
        identity = str(profile.get("identity") or "").strip()
        if identity:
            return identity
    for character in schema_hint.get("existing_characters") or []:
        if not isinstance(character, dict):
            continue
        profile = character.get("profile") or {}
        identity = str(profile.get("identity") or "").strip()
        if identity:
            return identity
    return _extract_focus_phrase(
        text,
        suffixes=["调查员", "档案员", "记录员", "制图师", "学徒", "守夜人", "主角"],
        fallback="主角",
    )


def build_mock_world_canvas(schema_hint: dict) -> dict:
    story_context = project_story_context(schema_hint)
    style = story_context["style"]
    story_idea = schema_hint.get("story_idea") or "一个围绕异常规则展开的中文故事。"
    revision_prompt = schema_hint.get("revision_prompt") or ""
    current_canvas = schema_hint.get("current_canvas") or {}
    premise_evidence = project_story_premise_evidence(story_idea)
    combined_intent = f"{story_idea}\n{revision_prompt}"
    is_revision = schema_hint.get("operation") == "revise"
    is_multi_world = any(
        marker in combined_intent
        for marker in ["多世界", "多个世界", "维度", "平行", "星球"]
    )
    scope = story_context["main_location"]
    if is_multi_world:
        scope = "多世界结构"

    is_tang_legend = style.get("genre_label") == "唐代传奇"
    structure_type = "dimension_stack" if is_multi_world else "historical_city_district" if is_tang_legend else "single_city"
    structure_name = "镜面维度群" if is_multi_world else story_context["main_location"]
    if is_tang_legend and structure_name == "核心调查区":
        structure_name = "长安西市"
        scope = "长安西市"
    story_direction = (
        current_canvas.get("story_direction")
        if is_revision and current_canvas.get("story_direction")
        else f"{style['genre_label']}：围绕{story_context['core_phenomenon']}、{style['story_pressure']}展开。"
    )
    if revision_prompt:
        story_direction = f"{story_direction} 修订重点：{revision_prompt}"

    if premise_evidence:
        story_direction = f"{story_direction} Premise evidence: {premise_evidence}"

    hard_rules = [
        {
            "rule_id": "rule_trigger_condition_001",
            "statement": f"{story_context['core_phenomenon']}只会在明确触发条件下出现，并且每次触发都会留下可追溯的现实代价。",
            "category": "magic",
            "firmness": "hard",
            "source": "agent_generated",
            "applies_to": ["world"],
            "rationale": "固定触发条件可以稳定后续事件因果。",
            "risk_if_changed": "改变触发条件会影响事件因果和时间结构。",
            "version_id": "version_world_canvas_m4_mock",
        },
        {
            "rule_id": "rule_memory_cost_001",
            "statement": f"被{story_context['core_phenomenon']}影响的人可能短暂遗失一段最想隐藏的记忆，但不会凭空获得新记忆。",
            "category": "limitation",
            "firmness": "hard",
            "source": "agent_generated",
            "applies_to": ["character", "memory"],
            "rationale": "限制异常能力，避免它成为万能解释。",
            "risk_if_changed": "如果允许凭空创造记忆，后续证词和人物动机会变得不可靠。",
            "version_id": "version_world_canvas_m4_mock",
        },
        {
            "rule_id": "rule_no_free_reversal_001",
            "statement": "已经发生的记忆遗失不能无代价撤销，只能通过新的线索重新拼合。",
            "category": "limitation",
            "firmness": "hard",
            "source": "agent_generated",
            "applies_to": ["world", "memory"],
            "rationale": "确保调查过程有代价和持续张力。",
            "risk_if_changed": "无代价恢复会削弱冲突强度。",
            "version_id": "version_world_canvas_m4_mock",
        },
    ]
    soft_rules = [
        {
            "rule_id": "rule_rain_expands_range_001",
            "statement": f"特殊天气或压力场景会扩大{story_context['signal_or_trigger']}被感知的范围，但不会改变既定触发规则。",
            "category": "magic",
            "firmness": "soft",
            "source": "agent_generated",
            "applies_to": ["world"],
            "rationale": "给氛围与场景调度留下弹性。",
            "risk_if_changed": "如果雨夜变成独立触发条件，可能和硬规则冲突。",
            "version_id": "version_world_canvas_m4_mock",
        },
        {
            "rule_id": "rule_authority_records_001",
            "statement": "城市管理者保存着异常事件记录，但记录经过删改，不一定完整可信。",
            "category": "society",
            "firmness": "soft",
            "source": "agent_generated",
            "applies_to": ["faction", "history"],
            "rationale": "为行动阻力、信息差和权力遮掩提供基础。",
            "risk_if_changed": "如果记录完全透明，人物选择和信息阻力会明显下降。",
            "version_id": "version_world_canvas_m4_mock",
        },
    ]

    conflicts = []
    if "随机鸣响" in combined_intent or ("随机" in combined_intent and "触发" in combined_intent):
        conflicts.append(
            {
                "conflict_id": "conflict_unverified_random_trigger_001",
                "summary": f"用户输入中出现随机触发倾向，但当前硬规则规定{story_context['core_phenomenon']}只能在明确条件下触发。",
                "conflict_type": "contradiction",
                "related_rule_ids": ["rule_trigger_condition_001"],
                "severity": "medium",
                "suggested_fix": "明确随机现象只是误报、余波或传播范围变化，而不是新的触发时间。",
                "requires_user_decision": True,
            }
        )

    payload = {
        "world_canvas_id": "world_local_project",
        "project_id": "local_project",
        "status": "draft",
        "story_direction": story_direction,
        "scope": scope,
        "tone": style["tone"],
        "world_structure": {
            "structure_id": "structure_root_001",
            "name": structure_name,
            "structure_type": structure_type,
            "summary": (
                "多个现实层彼此重叠，异常规则在边界处最明显。"
                if is_multi_world
                else f"以{scope}为主要舞台，唐代坊市秩序、夜禁文书、胡商往来与道观古镜共同构成奇遇边界。"
                if is_tang_legend
                else f"以{story_context['main_location']}为主要舞台，异常规则集中在核心调查地带。"
            ),
            "children": [
                {
                    "structure_id": "structure_stage_001",
                    "name": scope,
                    "structure_type": "historical_market_district" if is_tang_legend else "city_district",
                    "summary": (
                        "青玉佩、胡商证词、女史文书与古镜异象交会的唐代传奇舞台。"
                        if is_tang_legend
                        else "主要事件发生地，保存着最密集的异常痕迹。"
                    ),
                    "relationship_to_parent": "main_stage",
                }
            ],
        },
        "history_summary": (
            "唐代长安的坊市、夜禁与官私文书留下多层传闻；青玉佩和古镜异象把旧案、胡商往来与女史记录牵连在一起。"
            if is_tang_legend
            else "十三年前发生过一次被官方抹去记录的异常事件，成为当前故事的深层伤口。"
        ),
        "geography_summary": (
            f"故事范围收束在{scope}，向道观、驿馆和夜禁边界延伸，便于控制奇遇线索、证词与行动成本。"
            if is_tang_legend
            else f"故事范围收束在{scope}，便于控制线索、证词和异常传播边界。"
        ),
        "culture_summary": (
            "礼法、侠义、人情与坊市秩序共同约束角色选择；公开传闻和私下证词可能互相矛盾。"
            if is_tang_legend
            else "居民习惯用传闻解释异常，但公开讨论会受到城市权力结构压制。"
        ),
        "special_rules_summary": (
            f"{story_context['core_phenomenon']}必须服务于唐代传奇的奇遇与抉择，不能把古镜、玉佩或异象写成无代价万能法器。"
            if is_tang_legend
            else f"{story_context['core_phenomenon']}与记忆、证词和触发条件有关，不能作为万能魔法使用。"
        ),
        "hard_rules": hard_rules,
        "soft_rules": soft_rules,
        "unknown_rules": [
            {
                "unknown_rule_id": "unknown_origin_001",
                "summary": f"{story_context['mystery_origin']}仍未确定。",
                "gap_type": "missing_origin",
                "why_it_matters": "异常来源会影响后续反派、制度或历史真相的解释。",
                "related_rule_ids": ["rule_trigger_condition_001"],
                "suggested_questions": [
                    "异常是人为制造、城市规则的一部分，还是某次事故留下的后果？"
                ],
                "severity": "medium",
                "status": "open",
            },
            {
                "unknown_rule_id": "unknown_full_cost_001",
                "summary": f"多次触发{story_context['core_phenomenon']}后的长期代价仍未完全确定。",
                "gap_type": "missing_cost",
                "why_it_matters": "长期代价会影响角色是否愿意继续调查。",
                "related_rule_ids": ["rule_memory_cost_001"],
                "suggested_questions": ["重复触发会伤害记忆、关系，还是改变现实记录？"],
                "severity": "medium",
                "status": "open",
            },
        ],
        "logic_conflicts": conflicts,
        "user_confirmation_needed": [
            f"确认{story_context['mystery_origin']}是否在当前阶段保持未知。",
            "确认记忆遗失是否允许在后续章节被部分找回。",
        ],
        "locations": [
            {
                "location_id": "loc_core_stage_001",
                "name": scope,
                "summary": (
                    f"{scope}是青玉佩、胡商证词、女史裴明珰与道观古镜线索最密集的地点，适合作为第一阶段奇遇中心。"
                    if is_tang_legend
                    else f"{story_context['core_phenomenon']}痕迹最集中的地点，适合作为第一阶段调查中心。"
                ),
            }
        ],
        "factions": [
            {
                "faction_id": "faction_city_records_001",
                "name": "城市记录署",
                "summary": "掌握异常记录的机构，公开说法和内部档案并不一致。",
            }
        ],
        "species": [],
        "source_story_idea": story_idea,
        "latest_user_prompt": revision_prompt,
        "version_id": "version_world_canvas_m4_mock",
    }
    return payload


def build_mock_character_draft(schema_hint: dict) -> dict:
    story_context = project_story_context(schema_hint)
    operation = schema_hint.get("operation") or "generate"
    revision_prompt = schema_hint.get("revision_prompt") or ""
    current_draft = schema_hint.get("current_draft") or {}
    existing_characters = schema_hint.get("existing_characters") or []
    existing_ids = [
        character.get("character_id")
        for character in existing_characters
        if isinstance(character, dict) and character.get("character_id")
    ]
    index = len(existing_ids) + 1

    if operation == "revise" and isinstance(current_draft, dict):
        character = dict(current_draft.get("character") or {})
        profile = dict(character.get("profile") or {})
        current_state = dict(character.get("current_state") or {})
        arc_state = dict(character.get("arc_state") or {})
        relationship_drafts = list(current_draft.get("relationship_drafts") or [])
        profile["background_summary"] = (
            f"{profile.get('background_summary') or '这个角色背负着尚未说出口的旧事。'} "
            f"修订重点：{revision_prompt}"
        ).strip()
        if "负罪感" in revision_prompt:
            profile.setdefault("fears", [])
            if "再次因为沉默伤害同伴" not in profile["fears"]:
                profile["fears"].append("再次因为沉默伤害同伴")
            arc_state["inner_conflict"] = "想要弥补旧错，却害怕承认真相会让同伴离开。"
        current_state["active_goal"] = (
            current_state.get("active_goal") or "确认自己能否承担调查代价"
        )
        character["profile"] = profile
        character["current_state"] = current_state
        character["arc_state"] = arc_state
        character["tier"] = "A"
        character["status"] = "draft"
        return {
            "character": character,
            "relationship_drafts": relationship_drafts,
        }

    user_prompt = schema_hint.get("user_prompt") or "生成一个与当前核心谜团有关的主角。"
    target_tier = str(schema_hint.get("target_tier") or "A").upper()
    if target_tier not in {"A", "B", "C", "D"}:
        target_tier = "A"
    role_hint = schema_hint.get("role_hint") or "protagonist"
    story_function_hint = schema_hint.get("story_function_hint") or "investigator"
    premise_payload = schema_hint.get("project_story_premise") or {}
    premise_evidence = ""
    if premise_payload:
        premise_contract = premise_payload.get("prompt_fidelity_contract") or {}
        premise_evidence = " ".join(
            str(item)
            for item in [
                premise_payload.get("user_story_premise") or "",
                premise_payload.get("safe_user_story_summary") or "",
                " ".join(premise_contract.get("required_markers") or []),
                " ".join(premise_payload.get("required_story_elements") or []),
            ]
            if item
        )[:700]
    marker_source_text = " ".join(
        [
            str(user_prompt or ""),
            str(role_hint or ""),
            str(story_function_hint or ""),
            json.dumps(premise_payload, ensure_ascii=False) if premise_payload else "",
        ]
    )
    prompt_marker = _preferred_character_marker(
        marker_source_text,
        target_tier=target_tier,
    ) or _first_prompt_marker(marker_source_text)
    uniqueness_suffix = _safe_marker_suffix(prompt_marker, f"{target_tier}_{index:03d}")
    is_guardian = any(marker in user_prompt for marker in ["守灯", "灯塔", "守夜"])
    is_student = any(marker in user_prompt for marker in ["学徒", "学生", "年轻"])
    character_id = (
        "char_m5_lantern_apprentice"
        if target_tier == "A" and (is_guardian or is_student)
        else f"char_m5_main_{index:03d}"
    )
    if target_tier != "A":
        character_id = f"char_{target_tier.lower()}_generated_{index:03d}"
    if character_id in existing_ids:
        character_id = f"{character_id}_{index:03d}"
    tier_name_pools = {
        "A": ["顾闻舟", "沈既白", "唐砚秋"],
        "B": ["林桥", "陆宜年", "秦照"],
        "C": ["周岚", "许青萝", "严泊"],
        "D": ["阿澈", "小满", "阿宁"],
    }
    if is_guardian or is_student:
        tier_name_pools["A"] = ["沈砚", "许明灯", "江照夜"]
    tier_start_index = {"A": 1, "B": 4, "C": 7, "D": 10}.get(target_tier, index)
    name_pool = tier_name_pools.get(target_tier) or tier_name_pools["A"]
    name = name_pool[(max(1, index) - tier_start_index) % len(name_pool)]
    name = f"{name}_{uniqueness_suffix}"
    is_tang_legend = story_context["style"].get("genre_label") == "唐代传奇"
    if "裴明珰" in marker_source_text or is_tang_legend:
        name = "裴明珰"
    identity = (
        story_context["protagonist_role"]
        if story_context["protagonist_role"] != "主角"
        else ("女史" if is_tang_legend else "守灯人学徒" if is_guardian or is_student else "关键记录整理员")
    )
    story_function = (
        f"{story_function_hint} {uniqueness_suffix}".strip()
        if story_function_hint
        else f"{'witness' if is_guardian else 'investigator'} {uniqueness_suffix}".strip()
    )
    prompt_evidence = f"{user_prompt} {premise_evidence}".strip()
    location_id = "loc_core_stage_001"
    faction_id = "faction_city_records_001"

    character = {
        "character_id": character_id,
        "project_id": "local_project",
        "name": name,
        "tier": target_tier,
        "role": role_hint or ("protagonist" if target_tier == "A" else "supporting_npc"),
        "profile": {
            "description": f"{identity}，被{story_context['core_phenomenon']}牵入当前调查。M3 evidence: {prompt_evidence[:220]}",
            "identity": identity,
            "story_function": story_function,
            "background_summary": (
                f"曾在长安西市追查青玉佩、胡商证词与道观古镜异象，必须在礼法、侠义、人情和异象之间做选择。"
                if is_tang_legend
                else f"曾目击{story_context['signal_or_trigger']}后的线索缺口，因此主动接近核心调查。User prompt evidence: {user_prompt[:240]} Premise evidence: {premise_evidence[:240]}"
            ),
            "species_or_group": "",
            "faction_or_origin": "城市记录署" if not is_guardian else "港口灯塔",
            "appearance_summary": (
                "衣饰素雅，随身带有夜禁文书副本与青玉佩拓纹，常在古镜异象前保持克制判断。"
                if is_tang_legend
                else "外表克制朴素，常携带记录本和一盏旧灯。"
            ),
            "traits": ["克制", "敏锐", "不轻易交出判断"],
            "goals": [
                "查清青玉佩、胡商证词和道观古镜之间的联系，避免长安夜禁文书被误用。"
                if is_tang_legend
                else f"查清{story_context['core_phenomenon']}与自己记忆缺口之间的关系 {uniqueness_suffix}"
            ],
            "fears": ["失去证明真相所需的关键记忆"],
            "secrets": [f"曾在{story_context['signal_or_trigger']}出现后短暂忘记最重要的证词"],
            "personality_baseline": {
                "traits": ["先观察再行动", "对权威保持距离"],
                "values": ["真相", "证据", "不让无辜者承担代价"],
                "bottom_line": "不会主动伪造证词或牺牲无关者换取答案。",
                "speech_style_hint": "短句、克制，先确认事实再表达情绪。",
            },
            "hard_limits": [
                {
                    "limit_id": "limit_no_core_origin_001",
                    "statement": f"不知道{story_context['mystery_origin']}。",
                    "reason": f"{story_context['mystery_origin']}仍是世界画布中的未知缺口。",
                    "source": "agent_generated",
                }
            ],
            "knowledge_scope": [f"知道{story_context['core_phenomenon']}与若干失忆证词有关"],
            "forbidden_knowledge": [
                f"不知道{story_context['mystery_origin']}",
                "不知道城市记录署最高层的真实动机",
            ],
        },
        "current_state": {
            "location_id": location_id,
            "faction_id": faction_id,
            "species_id": "",
            "emotional_state": "警惕但被真相吸引",
            "knowledge": [f"{story_context['core_phenomenon']}会在触发条件附近影响证词记忆"],
            "active_goal": f"确认下一次{story_context['signal_or_trigger']}会改变哪一段记忆 {uniqueness_suffix}",
            "current_desire": "查清自己遗失证词的原因",
            "current_fear": "再次失去关键记忆并误导同伴",
            "resources": [story_context["record_object"]],
            "secrets": [f"曾隐瞒一次{story_context['signal_or_trigger']}后的失忆"],
        },
        "arc_state": {
            "current_arc": "从旁观证词者转向主动承担真相代价",
            "starting_point": "只愿提供记录，不愿亲自卷入调查",
            "pressure": "越接近真相，越可能失去证明真相所需的记忆",
            "inner_conflict": "想要真相，但害怕真相必须用记忆交换",
            "next_possible_change": "愿意与另一名主角建立有条件合作",
            "possible_direction": "逐渐学会把个人恐惧转化为调查边界",
            "locked_future_events": [],
        },
        "relationship_refs": [],
        "event_refs": [],
        "status": "draft",
        "source": "agent_generated" if target_tier == "A" else "role_generation",
        "version_id": "version_character_m5_mock" if target_tier == "A" else "phase85_role_generation_v1",
    }
    if target_tier == "B":
        character["profile"]["traits"] = character["profile"]["traits"][:4]
        character["profile"]["goals"] = character["profile"]["goals"][:2]
        character["profile"]["fears"] = character["profile"]["fears"][:2]
        character["profile"]["secrets"] = character["profile"]["secrets"][:1]
        character["profile"]["hard_limits"] = character["profile"]["hard_limits"][:1]
        character["arc_state"]["current_arc"] = "围绕当前线索提供阶段性阻力或帮助"
        character["arc_state"]["locked_future_events"] = []
    elif target_tier == "C":
        character["profile"]["description"] = f"{identity}，只服务于当前章节线索。M3 evidence: {prompt_evidence[:220]}"
        character["profile"]["traits"] = character["profile"]["traits"][:3]
        character["profile"]["goals"] = character["profile"]["goals"][:1]
        character["profile"]["fears"] = character["profile"]["fears"][:1]
        character["profile"]["secrets"] = []
        character["profile"]["hard_limits"] = character["profile"]["hard_limits"][:1]
        character["profile"]["forbidden_knowledge"] = character["profile"]["forbidden_knowledge"][:1]
        character["arc_state"] = {
            "current_arc": "",
            "starting_point": "",
            "pressure": "只承受当前章节的局部压力",
            "inner_conflict": "",
            "next_possible_change": "",
            "possible_direction": "",
            "locked_future_events": [],
        }
    elif target_tier == "D":
        character["profile"]["description"] = f"{identity}，用于单场景功能。M3 evidence: {prompt_evidence[:220]}"
        character["profile"]["traits"] = character["profile"]["traits"][:2]
        character["profile"]["goals"] = character["profile"]["goals"][:1]
        character["profile"]["fears"] = []
        character["profile"]["secrets"] = []
        character["profile"]["hard_limits"] = []
        character["profile"]["forbidden_knowledge"] = []
        character["profile"]["knowledge_scope"] = character["profile"]["knowledge_scope"][:1]
        character["current_state"]["current_desire"] = ""
        character["current_state"]["current_fear"] = ""
        character["current_state"]["resources"] = []
        character["current_state"]["secrets"] = []
        character["arc_state"] = {
            "current_arc": "",
            "starting_point": "",
            "pressure": "",
            "inner_conflict": "",
            "next_possible_change": "",
            "possible_direction": "",
            "locked_future_events": [],
        }

    relationship_drafts = []
    if target_tier == "A" and existing_ids:
        target_id = existing_ids[0]
        relationship_drafts.append(
            {
                "relationship_id": f"rel_{character_id}_{target_id}",
                "project_id": "local_project",
                "source_id": character_id,
                "target_id": target_id,
                "type": "alliance",
                "state": f"愿意交换线索，但双方都保留与{story_context['core_phenomenon']}有关的关键隐瞒。",
                "strength": 0.52,
                "evidence_event_ids": [],
                "evidence_note": "这是主角初始化阶段的必要关系草案，不来自已生成事件。",
                "status": "draft",
                "source": "agent_generated",
                "version_id": "version_relationship_m5_mock",
            }
        )

    payload = {
        "character": character,
        "relationship_drafts": relationship_drafts,
    }
    return payload


def _mock_cd_role_function_needs(
    cd_policy: dict,
    chapter_index: int,
) -> list[dict]:
    counts = cd_policy.get("scene_only_role_counts") or {}
    if not counts.get("C") and not counts.get("D"):
        return []
    tier_preference = "C_or_D"
    if counts.get("C") and not counts.get("D"):
        tier_preference = "C"
    elif counts.get("D") and not counts.get("C"):
        tier_preference = "D"
    return [
        {
            "need_id": f"cd_need_ch{chapter_index:03d}_local_witness",
            "scene_index": None,
            "tier_preference": tier_preference,
            "function_type": "local_witness",
            "function_summary": "需要一位场景级当地见证者提供有限线索或现场反应。",
            "reason": "该功能帮助 SceneAgent 在具体场景中决定是否复用或创建 C/D 角色。",
            "location_hint": "当前章节主要调查地点",
            "relationship_hint": "",
            "knowledge_need": "只需要知道局部现场事实，不携带完整角色记忆。",
            "reuse_existing_preferred": True,
            "must_not_bind_specific_character_id": True,
            "resolved_by_scene_agent": True,
        }
    ]


def build_mock_chapter_framework(schema_hint: dict) -> dict:
    context = schema_hint.get("context") or {}
    vocabulary = context.get("component_vocabulary") or {}
    chapter_modules = vocabulary.get("chapter_modules") or []
    premise_phrase = _premise_phrase(
        context,
        fallback=context.get("latest_user_intent_summary") or "confirmed project premise",
    )
    selected_modules: list[dict] = []
    for module in chapter_modules:
        if not isinstance(module, dict):
            continue
        module_id = module.get("module_id") or ""
        allowed_components = module.get("allowed_components") or []
        component_ids = [
            component.get("component_id")
            for component in allowed_components
            if isinstance(component, dict) and component.get("component_id")
        ][:2]
        if not module_id or not component_ids:
            continue
        selected_modules.append(
            {
                "module_id": module_id,
                "component_ids": component_ids,
                "reason_summary": (
                    f"Local mock selects vocabulary-valid components for {premise_phrase} "
                    "and confirmed macro mapping."
                ),
                "confidence": 0.82,
            }
        )
    return {
        "chapter_function": "current_chapter_framework",
        "chapter_goal": f"Shape the current chapter around {premise_phrase}.",
        "reader_emotion_goal": ["curiosity", "pressure", "clarity"],
        "main_conflict": (
            f"The current chapter must preserve {premise_phrase} while moving only "
            "confirmed evidence into executable scene planning."
        ),
        "participating_character_ids": [],
        "relationship_focus": [],
        "information_release_policy": "Use confirmed facts and do not reveal future-only outcomes.",
        "forbidden_reveals": ["Do not reveal unconfirmed future chapter outcomes."],
        "world_rule_focus": context.get("world_hard_rules") or [],
        "selected_modules": selected_modules,
        "warnings": [],
    }


def build_mock_chapter_plan(schema_hint: dict) -> dict:
    story_context = project_story_context(schema_hint)
    premise_phrase = _premise_phrase(
        schema_hint,
        fallback=story_context["core_phenomenon"],
    )
    operation = schema_hint.get("operation") or "generate"
    current_draft = schema_hint.get("current_draft") or {}
    revision_prompt = schema_hint.get("revision_prompt") or ""
    chapter_count = int(
        schema_hint.get("chapter_count")
        or current_draft.get("chapter_count")
        or 5
    )
    current_chapter_index = int(
        schema_hint.get("current_chapter_index")
        or current_draft.get("current_chapter_index")
        or 1
    )
    story_goal = (
        schema_hint.get("story_goal")
        or current_draft.get("story_goal")
        or f"讲述{story_context['core_phenomenon']}如何把线索、记忆和权力压力连接起来。"
    )
    main_cast = schema_hint.get("confirmed_main_cast") or []
    supporting_roles = schema_hint.get("confirmed_supporting_roles") or []
    characters = schema_hint.get("confirmed_characters") or [
        *main_cast,
        *supporting_roles,
    ]
    cd_policy = schema_hint.get("cd_role_function_policy") or {}
    relationships = schema_hint.get("confirmed_relationships") or []
    assignments = (
        schema_hint.get("macro_assignments")
        or (schema_hint.get("framework_package") or {}).get("chapter_macro_assignments")
        or []
    )
    framework_package = schema_hint.get("framework_package") or {}
    macro_components = (
        (framework_package.get("macro_framework") or {}).get("components") or []
    )
    macro_label_by_id = {
        component.get("component_id"): component.get("label") or component.get("component_id")
        for component in macro_components
        if isinstance(component, dict)
    }
    current_framework = schema_hint.get("current_chapter_framework") or (
        current_draft.get("current_chapter_framework") or {}
    )
    main_cast_ids = [
        character.get("character_id")
        for character in main_cast
        if isinstance(character, dict) and character.get("character_id")
    ]
    supporting_role_ids = [
        character.get("character_id")
        for character in supporting_roles
        if isinstance(character, dict) and character.get("character_id")
    ]
    character_ids = [
        character.get("character_id")
        for character in characters
        if isinstance(character, dict) and character.get("character_id")
    ]
    first_character_id = (
        main_cast_ids[0]
        if main_cast_ids
        else character_ids[0] if character_ids else "char_m6_main_001"
    )
    relationship_ids = [
        relationship.get("relationship_id")
        for relationship in relationships
        if isinstance(relationship, dict) and relationship.get("relationship_id")
    ]
    assignment_by_index = {
        assignment.get("chapter_index"): assignment
        for assignment in assignments
        if isinstance(assignment, dict)
    }

    existing_routes = current_draft.get("chapter_routes") or []
    route_by_index = {
        route.get("chapter_index"): route
        for route in existing_routes
        if isinstance(route, dict)
    }

    def rotate_ids(ids: list[str], chapter_index: int, width: int = 1) -> list[str]:
        clean = [str(item or "").strip() for item in ids if str(item or "").strip()]
        if not clean:
            return []
        start = (max(1, int(chapter_index or 1)) - 1) % len(clean)
        rotated = clean[start:] + clean[:start]
        return rotated[: max(1, int(width or 1))]

    route_templates = [
        (f"{story_context['core_phenomenon']}回声", f"建立{story_context['core_phenomenon']}、线索缺口和主角的初始压力。", "建立世界规则与调查入口。"),
        ("线索裂缝", f"让第一条可靠线索把主角推向{story_context['investigation_object']}。", "触发主线行动。"),
        ("记录背面", "扩大制度阻力，并让关系中的隐瞒开始产生代价。", "升级冲突和信息缺口。"),
        ("边界选择", "让主角面对是否继续追查的阶段性选择。", "形成局部高潮。"),
        ("余波未息", f"收束阶段性结果，同时保留{story_context['mystery_origin']}的未知缺口。", "形成新状态和后续悬念。"),
    ]
    routes = []
    for chapter_index in range(1, chapter_count + 1):
        existing_route = route_by_index.get(chapter_index) or {}
        assignment = assignment_by_index.get(chapter_index) or {}
        linked_ids = (
            existing_route.get("linked_macro_component_ids")
            or assignment.get("linked_macro_component_ids")
            or []
        )
        labels = [
            macro_label_by_id.get(component_id, component_id)
            for component_id in linked_ids
        ]
        template = route_templates[(chapter_index - 1) % len(route_templates)]
        summary = existing_route.get("light_route_summary") or f"{template[1]} ProjectStoryPremise: {premise_phrase}."
        function = existing_route.get("narrative_function") or f"{template[2]} Premise focus: {premise_phrase}."
        if operation == "revise" and chapter_index == current_chapter_index and revision_prompt:
            summary = f"{summary} 修订后聚焦当前章可执行行动与因果边界。"
            function = f"{function} 当前章按用户修订加强执行重点。"
        route_focus_ids = rotate_ids(main_cast_ids, chapter_index, width=1)
        route_supporting_ids = rotate_ids(supporting_role_ids, chapter_index, width=1)
        routes.append(
            {
                "chapter_index": chapter_index,
                "temporary_title": existing_route.get("temporary_title")
                or f"第{chapter_index}章：{template[0]}",
                "linked_macro_component_ids": linked_ids,
                "macro_component_label": " / ".join(labels) if labels else "阶段功能",
                "light_route_summary": summary,
                "narrative_function": function,
                "expected_focus_character_ids": existing_route.get("expected_focus_character_ids")
                or route_focus_ids
                or [first_character_id],
                "expected_supporting_role_ids": existing_route.get("expected_supporting_role_ids")
                or route_supporting_ids,
                "cd_role_function_need_hints": existing_route.get("cd_role_function_need_hints")
                or _mock_cd_role_function_needs(cd_policy, chapter_index),
                "expected_conflict_hint": existing_route.get("expected_conflict_hint")
                or "调查真相的需要与记忆代价、城市权力压力发生冲突。",
                "detail_level": "light",
                "future_lock_level": "low",
            }
        )

    current_route = routes[current_chapter_index - 1]
    current_main_cast_ids = current_route.get("expected_focus_character_ids") or [first_character_id]
    current_supporting_ids = current_route.get("expected_supporting_role_ids") or supporting_role_ids[:1]
    current_character = next(
        (
            character
            for character in characters
            if isinstance(character, dict)
            and character.get("character_id") in set(current_main_cast_ids)
        ),
        characters[0] if characters else {},
    )
    current_state = current_character.get("current_state") or {}
    arc_state = current_character.get("arc_state") or {}
    profile = current_character.get("profile") or {}
    hard_rules = (schema_hint.get("world_canvas") or {}).get("hard_rules") or []
    hard_rule_statements = [
        rule.get("statement") if isinstance(rule, dict) else str(rule)
        for rule in hard_rules
    ]
    current_brief = current_draft.get("current_chapter_brief") or {}
    selected_scene_count = current_brief.get("user_selected_scene_count")
    brief = {
        "chapter_index": current_chapter_index,
        "title": current_brief.get("title") or current_route["temporary_title"],
        "linked_macro_component_ids": current_route["linked_macro_component_ids"],
        "chapter_framework_id": current_framework.get("chapter_framework_id")
        or f"chapter_fw_{current_chapter_index:03d}",
        "chapter_goal": current_brief.get("chapter_goal")
        or f"让主角在{story_context['core_phenomenon']}规则边界内获得第一条可执行线索，并付出继续调查的心理压力。",
        "reader_emotion_goal": current_brief.get("reader_emotion_goal")
        or ["好奇", "不安", "期待"],
        "participating_character_ids": current_brief.get("participating_character_ids")
        or [*current_main_cast_ids, *current_supporting_ids],
        "main_cast_character_ids": current_brief.get("main_cast_character_ids")
        or current_main_cast_ids,
        "supporting_role_ids": current_brief.get("supporting_role_ids")
        or current_supporting_ids,
        "supporting_role_refs": current_brief.get("supporting_role_refs")
        or [
            {
                "character_id": character_id,
                "tier": "B",
                "role_in_chapter": "在本章承担线索压力与关系对照。",
                "participation_reason": "该配角支撑主角决策压力，但不被提升为主角团。",
                "related_main_cast_ids": current_main_cast_ids,
                "expected_scene_indices": [1],
                "context_depth": "medium",
            }
            for character_id in current_supporting_ids
        ],
        "supporting_role_function_focus": current_brief.get("supporting_role_function_focus")
        or [
            {
                "character_id": character_id,
                "function_focus": "给主角提供可验证线索和关系压力。",
                "relationship_pressure": "迫使主角在信任与记忆代价之间做出选择。",
                "expected_chapter_effect": "增强本章调查的具体阻力。",
            }
            for character_id in current_supporting_ids
        ],
        "cd_role_function_needs": current_brief.get("cd_role_function_needs")
        or _mock_cd_role_function_needs(cd_policy, current_chapter_index),
        "main_conflict": current_brief.get("main_conflict")
        or f"主角需要验证{story_context['investigation_object']}，但越接近证据越可能失去关键记忆。",
        "character_desire_or_arc_focus": current_brief.get("character_desire_or_arc_focus")
        or [
            {
                "character_id": character_id,
                "desire": current_state.get("current_desire")
                or current_state.get("active_goal")
                or f"查清{story_context['core_phenomenon']}和线索缺口的关系",
                "arc_focus": arc_state.get("current_arc")
                or arc_state.get("next_possible_change")
                or "从旁观记录者转向主动承担真相代价",
            }
            for character_id in current_main_cast_ids
        ],
        "world_rules_to_respect": current_brief.get("world_rules_to_respect")
        or hard_rule_statements[:3],
        "forbidden_moves": current_brief.get("forbidden_moves")
        or [
            f"不要让角色提前知道{story_context['mystery_origin']}。",
            "不要无代价恢复已失去的记忆。",
            "不要锁死未来章节的死亡、背叛、觉醒或结局。",
        ],
        "recommended_scene_count": current_brief.get("recommended_scene_count") or 3,
        "user_selected_scene_count": selected_scene_count,
        "summary_for_scene_generation": current_brief.get("summary_for_scene_generation")
        or (
            f"{profile.get('identity') or story_context['protagonist_role']}围绕{story_context['investigation_object']}展开第一轮调查，"
            "必须在确认线索和保护记忆之间做出当前章选择。"
        ),
    }
    for key in ["chapter_goal", "main_conflict", "summary_for_scene_generation"]:
        if premise_phrase and premise_phrase not in str(brief.get(key) or ""):
            brief[key] = f"{brief.get(key) or ''} ProjectStoryPremise: {premise_phrase}."

    if operation == "revise" and revision_prompt:
        brief["chapter_goal"] = f"{brief['chapter_goal']} 修订后保持规则边界，并强化当前章可执行目标。"
        brief["summary_for_scene_generation"] = (
            f"{brief['summary_for_scene_generation']} 修订后执行：保持已确认规则边界，并让场景目标更清晰。"
        )

    payload = {
        "story_goal": story_goal,
        "source_relationship_ids": relationship_ids,
        "chapter_routes": routes,
        "current_chapter_brief": brief,
        "user_confirmation_needed": [],
    }
    return payload


def build_mock_authorial_intent(schema_hint: dict) -> dict:
    story_context = project_story_context(schema_hint)
    context = schema_hint.get("context") or {}
    scene_index = int(context.get("scene_index") or 1)
    user_intent = str(context.get("user_intent") or "")
    if "skip_authorial_intent" in user_intent:
        payload = {
            "should_create_intent": False,
            "skip_reason": "当前幕是过渡性推进，不需要额外叙事装置。",
            "intent_type": "other",
            "summary": "",
            "constraint_strength": "suggestion",
            "allowed_apparent_contradictions": [],
            "reader_explanation_policy": "defer",
            "payoff_required": False,
            "open_ambiguity_allowed": False,
            "symbolic_unresolved": False,
            "payoff_deadline_type": "",
            "payoff_deadline_chapter_id": "",
            "payoff_deadline_scene_index": None,
            "payoff_deadline_note": "",
        }
        return payload

    payload = {
        "should_create_intent": True,
        "skip_reason": "",
        "intent_type": "delayed_reveal",
        "summary": f"第 {scene_index} 幕保留{story_context['mystery_origin']}的延迟揭示，只让角色接触可追查线索，不提前解释全部真相。",
        "constraint_strength": "soft_intent",
        "allowed_apparent_contradictions": [
            {
                "contradiction_type": "delayed_explanation",
                "summary": f"线索看似指向{story_context['core_phenomenon']}，但真实来源暂时延后解释。",
                "scope": "scene",
                "expected_gate_action": "warn",
                "requires_narrative_debt": False,
                "matched_record_refs": [],
            }
        ],
        "reader_explanation_policy": "defer",
        "payoff_required": False,
        "open_ambiguity_allowed": True,
        "symbolic_unresolved": False,
        "payoff_deadline_type": "",
        "payoff_deadline_chapter_id": "",
        "payoff_deadline_scene_index": None,
        "payoff_deadline_note": "",
    }
    return payload


def build_mock_scene_information(schema_hint: dict) -> dict:
    story_context = project_story_context(schema_hint)
    style = story_context["style"]
    context = schema_hint.get("context") or {}
    chapter = context.get("chapter") or {}
    framework = context.get("current_chapter_framework") or {}
    world_canvas = context.get("world_canvas") or {}
    characters = context.get("characters") or []
    relationships = context.get("relationships") or []
    authorial_intent = context.get("authorial_intent") or {}
    scene_index = int(context.get("scene_index") or 1)
    scene_count = int(context.get("scene_count") or chapter.get("scene_count") or 1)
    regeneration_hint = schema_hint.get("regeneration_hint") or ""
    premise_phrase = _premise_phrase({"context": context}, story_context["core_phenomenon"])

    chapter_goal = chapter.get("chapter_goal") or "建立当前章的调查入口。"
    main_conflict = chapter.get("main_conflict") or "角色需要在真相和代价之间行动。"
    location = _mock_scene_location(world_canvas)
    time_label = style["time_label"]
    modules = framework.get("modules") or []
    component_labels = _mock_framework_component_labels(modules)
    character_ids = [
        character.get("character_id")
        for character in characters
        if isinstance(character, dict) and character.get("character_id")
    ]
    first_character = characters[0] if characters else {}
    first_character_id = (
        first_character.get("character_id") if isinstance(first_character, dict) else ""
    ) or (character_ids[0] if character_ids else "char_scene_main_001")
    first_character_name = (
        first_character.get("name") if isinstance(first_character, dict) else ""
    ) or "主角"

    scene_goal = {
        "summary": f"第 {scene_index} 幕让{first_character_name}进入当前章核心调查入口，并看见继续追查的代价。",
        "chapter_goal_alignment": chapter_goal,
        "main_conflict_alignment": main_conflict,
        "macro_component_alignment": framework.get("linked_macro_component_ids") or chapter.get("linked_macro_component_ids") or [],
        "ending_position": "以一个可继续追查但不能立刻解释全部真相的线索收束。",
    }
    if regeneration_hint:
        scene_goal["regeneration_hint"] = regeneration_hint

    environment = {
        "location": location.get("name") or "核心异常区",
        "location_id": location.get("location_id") or "",
        "time_label": time_label,
        "constraints": [
            "异常只能遵守已确认的世界硬规则。",
            f"第一幕只打开调查入口，不解释{story_context['mystery_origin']}。",
        ],
        "available_objects": [
            story_context["record_object"],
            "潮湿石阶",
            f"被遮盖的{story_context['signal_or_trigger']}记录",
        ],
        "forbidden_environment_moves": [
            "不要让异常在未确认条件下随机触发。",
            "不要凭空恢复或创造关键记忆。",
        ],
    }

    role_beats = []
    for index, character in enumerate(characters[:3], start=1):
        if not isinstance(character, dict):
            continue
        current_state = character.get("current_state") or {}
        arc_state = character.get("arc_state") or {}
        role_beats.append(
            {
                "character_id": character.get("character_id"),
                "name": character.get("name") or f"角色{index}",
                "action": current_state.get("active_goal") or "确认线索是否可信。",
                "reaction": current_state.get("emotional_state") or "克制但紧张。",
                "dialogue_focus": current_state.get("current_desire") or "把证据和代价说清楚。",
                "possible_state_change": arc_state.get("next_possible_change") or "从旁观转向有限行动。",
            }
        )
    if not role_beats:
        role_beats.append(
            {
                "character_id": first_character_id,
                "name": first_character_name,
                "action": "接近核心线索。",
                "reaction": "警惕但愿意继续。",
                "dialogue_focus": "确认线索来源。",
                "possible_state_change": "接受调查代价。",
            }
        )

    items = [
        {
            "item_id": "info_scene_goal_001",
            "type": "scene_goal",
            "content": scene_goal["summary"],
            "source_node": "ScenePlanner",
            "priority": "must_use",
            "related_character_ids": [first_character_id],
            "related_world_rule_ids": [],
            "related_framework_component_ids": [],
            "order_hint": 20,
        },
        {
            "item_id": "info_chapter_conflict_001",
            "type": "conflict",
            "content": main_conflict,
            "source_node": "ChapterFramework",
            "priority": "must_use",
            "related_character_ids": character_ids,
            "related_world_rule_ids": [],
            "related_framework_component_ids": [],
            "order_hint": 30,
        },
        {
            "item_id": "info_environment_001",
            "type": "environment",
            "content": f"{time_label}，地点是{environment['location']}，场面必须保持{style['scene_atmosphere']}。",
            "source_node": "SceneEnvironment",
            "priority": "should_use",
            "related_character_ids": [],
            "related_world_rule_ids": [],
            "related_framework_component_ids": [],
            "order_hint": 10,
        },
        {
            "item_id": "info_framework_components_001",
            "type": "framework_component",
            "content": " / ".join(component_labels) or "使用当前章框架模块推进第一幕。",
            "source_node": "ChapterFramework",
            "priority": "should_use",
            "related_character_ids": character_ids,
            "related_world_rule_ids": [],
            "related_framework_component_ids": [],
            "order_hint": 40,
        },
        {
            "item_id": "info_required_reveal_001",
            "type": "reveal",
            "content": (
                f"只释放一条可执行线索：{story_context['record_object']}与"
                f"{story_context['signal_or_trigger']}有关，但{story_context['mystery_origin']}仍保持未知。"
            ),
            "source_node": "StoryInformationAssembler",
            "priority": "must_use",
            "related_character_ids": character_ids,
            "related_world_rule_ids": [],
            "related_framework_component_ids": [],
            "order_hint": 50,
        },
        {
            "item_id": "info_ending_beat_001",
            "type": "ending",
            "content": "第一幕以角色决定暂时保留线索并继续调查收束。",
            "source_node": "StoryTodoOrdering",
            "priority": "must_use",
            "related_character_ids": character_ids,
            "related_world_rule_ids": [],
            "related_framework_component_ids": [],
            "order_hint": 80,
        },
    ]

    if premise_phrase:
        premise_story_variants = [
            "项目核心前提在本幕表现为一处可复查的物证，角色必须亲手确认它的来历。",
            "本幕把核心前提落到一次公开核验里，角色需要在旁人质疑前给出可见行动。",
            "核心前提不再只是解释，而变成一项会改变人物关系的现场选择。",
            "本幕让核心前提通过新的空间痕迹出现，角色必须承担错误判断的代价。",
            "核心前提在本幕被压缩成一个具体问题：谁愿意把证据带到下一处现场。",
        ]
        items.append(
            {
                "item_id": "info_project_story_premise_001",
                "type": "reveal",
                "content": premise_story_variants[(max(1, scene_index) - 1) % len(premise_story_variants)],
                "source_node": "ProjectStoryPremise",
                "priority": "must_use",
                "related_character_ids": character_ids,
                "related_world_rule_ids": [],
                "related_framework_component_ids": [],
                "order_hint": 45,
            }
        )

    authorial_summary = str(authorial_intent.get("summary") or "").strip()
    if authorial_intent.get("status") == "created" and authorial_summary:
        items.append(
            {
                "item_id": "info_authorial_intent_001",
                "type": "scene_goal",
                "content": f"叙事意图：{authorial_summary}",
                "source_node": "AuthorialIntentAgent",
                "priority": "should_use",
                "related_character_ids": character_ids,
                "related_world_rule_ids": [],
                "related_framework_component_ids": [],
                "order_hint": 25,
            }
        )

    hard_rules = world_canvas.get("hard_rules") or []
    if hard_rules:
        rule = hard_rules[0] if isinstance(hard_rules[0], dict) else {}
        items.append(
            {
                "item_id": "info_world_rule_001",
                "type": "world_rule",
                "content": rule.get("statement") or str(hard_rules[0]),
                "source_node": "WorldRules",
                "priority": "must_use",
                "related_character_ids": [],
                "related_world_rule_ids": [rule.get("rule_id") or "rule_001"],
                "related_framework_component_ids": [],
                "order_hint": 5,
            }
        )

    for index, beat in enumerate(role_beats, start=1):
        items.append(
            {
                "item_id": f"info_role_beat_{index:03d}",
                "type": "character_turn",
                "content": f"{beat['name']}：行动={beat['action']}；反应={beat['reaction']}；对话焦点={beat['dialogue_focus']}。",
                "source_node": "RoleBeat",
                "priority": "should_use",
                "related_character_ids": [beat.get("character_id") or ""],
                "related_world_rule_ids": [],
                "related_framework_component_ids": [],
                "order_hint": 35 + index,
            }
        )

    forbidden = []
    for character in characters:
        if not isinstance(character, dict):
            continue
        profile = character.get("profile") or {}
        forbidden.extend(profile.get("forbidden_knowledge") or [])
        for hard_limit in profile.get("hard_limits") or []:
            if isinstance(hard_limit, dict) and hard_limit.get("statement"):
                forbidden.append(hard_limit["statement"])
    forbidden.extend(environment["forbidden_environment_moves"])
    for index, forbidden_item in enumerate(forbidden[:5], start=1):
        items.append(
            {
                "item_id": f"info_do_not_use_{index:03d}",
                "type": "forbidden",
                "content": forbidden_item,
                "source_node": "WorldRules",
                "priority": "do_not_use",
                "related_character_ids": character_ids,
                "related_world_rule_ids": [],
                "related_framework_component_ids": [],
                "order_hint": 100 + index,
            }
        )

    payload = {
        "scene_goal": scene_goal,
        "environment": environment,
        "role_beats": role_beats,
        "story_information_list": items,
        "scene_index": scene_index,
        "scene_count": scene_count,
        "relationship_count": len(relationships),
    }
    return payload


def build_mock_scene_write(schema_hint: dict) -> dict:
    story_context = project_story_context(schema_hint)
    style = story_context["style"]
    package = schema_hint.get("ordered_story_information_package") or {}
    approved_context = schema_hint.get("approved_context") or {}
    writing_context = approved_context.get("scene_writing_context") or {}
    progression = approved_context.get("scene_progression_statement") or {}
    required_terms = (
        progression.get("required_prompt_terms")
        or _premise_terms_from_payload(approved_context.get("project_story_premise") or {})
        or _premise_terms_from_payload(writing_context.get("project_story_premise") or {})
    )
    required_terms = [
        str(term or "").strip()
        for term in required_terms
        if str(term or "").strip()
    ]
    premise_marker = (
        " / ".join(required_terms[:4])
        if required_terms
        else story_context["core_phenomenon"]
    )
    chapter = approved_context.get("chapter") or {}
    characters = approved_context.get("characters") or []
    scene_index = _mock_scene_index(schema_hint)
    scene_label = _mock_scene_label(scene_index)
    try:
        chapter_index = int(chapter.get("chapter_index") or 1)
    except (TypeError, ValueError):
        chapter_index = 1
    try:
        scene_count = int(
            approved_context.get("scene_count")
            or writing_context.get("scene_count")
            or chapter.get("scene_count")
            or 1
        )
    except (TypeError, ValueError):
        scene_count = 1
    prompt_terms_for_scene: list[str] = []
    if required_terms:
        start = (
            (max(1, chapter_index) - 1) * max(1, scene_count)
            + max(1, scene_index)
            - 1
        ) % len(required_terms)
        for offset in range(min(2, len(required_terms))):
            term = required_terms[(start + offset) % len(required_terms)]
            if term not in prompt_terms_for_scene:
                prompt_terms_for_scene.append(term)
    phrase_seed = max(1, chapter_index) + max(1, scene_index) - 2
    if len(prompt_terms_for_scene) >= 2:
        first_term, second_term = prompt_terms_for_scene[0], prompt_terms_for_scene[1]
        if style["genre_label"] == "唐代传奇":
            prompt_evidence_templates = [
                f"坊墙旧诗先写到「{first_term}」，驿书朱印又把它牵向「{second_term}」。",
                f"青玉佩上刻着「{first_term}」，胡商口中却反复提到「{second_term}」。",
                f"道观题壁露出「{first_term}」的旧名，灯市传闻又把众人引到「{second_term}」。",
                f"乐工残谱暗合「{first_term}」，一纸夜禁文书却把「{second_term}」推到众人面前。",
                f"古镜背面的细纹指向「{first_term}」，同伴带回的香囊又藏着「{second_term}」的线索。",
            ]
        else:
            prompt_evidence_templates = [
                f"缺页边缘留下「{first_term}」的残痕，另一份旁录把它和「{second_term}」并排放在同一时刻。",
                f"复查表先露出「{first_term}」，随后的口供却把注意力推向「{second_term}」。",
                f"现场留下的编号对上「{first_term}」，墙上新贴的纸条则提醒他们不能忽略「{second_term}」。",
                f"一段被划掉的记录提到「{first_term}」，而保管员的补注把它转向「{second_term}」。",
                f"旧档的折痕指向「{first_term}」，同伴带回的实物证据又把「{second_term}」放到桌面上。",
            ]
        prompt_evidence_sentence = prompt_evidence_templates[
            phrase_seed % len(prompt_evidence_templates)
        ]
    elif prompt_terms_for_scene:
        term = prompt_terms_for_scene[0]
        if style["genre_label"] == "唐代传奇":
            prompt_evidence_templates = [
                f"坊墙旧诗留下「{term}」的残痕。",
                f"驿书朱印先露出「{term}」。",
                f"青玉佩背面的纹路对上「{term}」。",
                f"道观题壁提到「{term}」。",
                f"古镜背光处浮出「{term}」。",
            ]
        else:
            prompt_evidence_templates = [
                f"缺页边缘留下「{term}」的残痕。",
                f"复查表先露出「{term}」。",
                f"现场留下的编号对上「{term}」。",
                f"一段被划掉的记录提到「{term}」。",
                f"旧档的折痕指向「{term}」。",
            ]
        prompt_evidence_sentence = prompt_evidence_templates[
            phrase_seed % len(prompt_evidence_templates)
        ]
    else:
        phenomenon = story_context["core_phenomenon"]
        prompt_evidence_templates = [
            f"缺页边缘把线索连回「{phenomenon}」。",
            f"复查表让「{phenomenon}」第一次有了可核对的位置。",
            f"现场编号把他们带回「{phenomenon}」的源头。",
            f"被划掉的记录仍保留着「{phenomenon}」的轮廓。",
            f"旧档折痕把新的问题推回「{phenomenon}」。",
        ]
        prompt_evidence_sentence = prompt_evidence_templates[
            phrase_seed % len(prompt_evidence_templates)
        ]
    first_character = characters[0] if characters else {}
    name = (
        first_character.get("name") if isinstance(first_character, dict) else ""
    ) or "主角"
    participant_names = [
        str(character.get("name") or "").strip()
        for character in characters
        if isinstance(character, dict) and str(character.get("name") or "").strip()
    ]
    if not participant_names:
        participant_names = [name]
    primary_name = participant_names[
        (max(1, chapter_index) + max(1, scene_index) - 2) % len(participant_names)
    ]
    supporting_names = [item for item in participant_names if item != primary_name][:3]
    participant_line = (
        f"{primary_name}与{'、'.join(supporting_names)}分头核对"
        if supporting_names
        else primary_name
    )
    chapter_focuses = [
        "源头发现",
        "现场核验",
        "关系代价",
        "权力压力",
        "移交后果",
        "公开风险",
        "私人记忆边界",
    ]
    chapter_focus = chapter_focuses[(max(1, chapter_index) - 1) % len(chapter_focuses)]
    opening = (
        package.get("opening_context")
        or [f"{style['time_label']}，{story_context['main_location']}还没有完全安静下来。"]
    )[0]
    reveal = (
        package.get("required_reveals")
        or [f"一条{story_context['record_object']}把线索指向{story_context['signal_or_trigger']}。"]
    )[0]
    ending = (package.get("ending_beat") or ["角色决定继续推进，但不立刻公开关键线索。"])[0]
    chapter_title = chapter.get("title") or chapter.get("summary") or "当前章"

    synopsis = (
        f"{chapter_title}的{scene_label}让{participant_line}，"
        f"围绕{story_context['record_object']}与{story_context['signal_or_trigger']}"
        f"作出一个新的可验证选择。{prompt_evidence_sentence}"
    )
    prose_text = (
        f"{scene_label}从{story_context['main_location']}的一处新痕迹开始。"
        f"{participant_line}，检查{story_context['record_object']}，"
        f"{story_context['signal_or_trigger']}留下了此前没有出现过的变化。"
        f"{prompt_evidence_sentence}\n\n"
        f"线索没有直接给出答案，却改变了{style['story_pressure']}的推进路线。{primary_name}把马上能确认的事实"
        f"和必须暂缓公开的部分分开，{'、'.join(participant_names)}各自承担不同风险。\n\n"
        "幕尾留下的是一条可继续追踪的痕迹、一个尚未结清的代价，以及继续向前的理由。"
    )
    if progression:
        def story_safe(value: object, fallback: str) -> str:
            text = str(value or "").strip()
            if not text:
                return fallback
            folded = text.casefold()
            internal_markers = [
                "current chapter",
                "chapter goal",
                "context json",
                "ordered story information",
                "scene_information",
                "memory_extraction",
                "narrative_intent",
                "prose_text",
                "provider_failure",
                "external model",
                "error=",
                "projectstorypremise marker",
                "previous confirmed scene",
                "must leave this scene",
                "current scene",
                "chapter focus",
                "active premise",
                "evidence gap",
                "must pursue",
                "scene 1 opens",
                "scene 2",
                "scene 3",
                "scene 4",
                "scene 5",
                "cannot solve the beat alone",
                "distinctive procedure",
                "move at least one a/b participant",
                "name the first practical question",
                "scene-specific evidence",
                "当前幕必须把",
                "establish the current chapter direction",
                "apply the first clear test",
                "test the chapter question",
                "turn the chapter problem",
                "make the cost of the chapter",
                "convert chapter progress",
                "compress chapter entry",
                "add a new constraint",
                "add a different piece",
                "reveal a structural change",
                "add consequence information",
                "add final chapter-level",
                "shift at least one",
                "force at least one",
                "make at least one",
                "leave at least one",
                "turn the opening intention",
                "introduce the chapter pressure",
                "convert uncertainty",
                "escalate or redirect",
                "translate prior progress",
                "close the current chapter",
                "show the first visible cost",
                "end by making",
                "end with a result",
                "end with the changed problem",
                "end with an unresolved cost",
                "end with a forward hook",
                "外部模型",
                "系统内部",
            ]
            if any(marker in folded for marker in internal_markers):
                return fallback
            return text

        scene_objective = story_safe(
            progression.get("scene_objective"),
            f"{primary_name}用{chapter_focus}方式追踪第{chapter_index}章第{scene_index}幕的具体线索。",
        )
        new_information = story_safe(
            progression.get("new_information"),
            reveal,
        )
        character_delta = progression.get("character_state_delta") or (
            f"{primary_name}在本幕结尾承担一个新的选择压力。"
        )
        character_delta = story_safe(
            character_delta,
            f"{primary_name}在本幕结尾把新的压力分给在场参与者。",
        )
        conflict_turn = story_safe(
            progression.get("conflict_turn"),
            scene_objective,
        )
        difference = story_safe(
            progression.get("difference_from_previous_scene"),
            f"{scene_label}通过新的{chapter_focus}后果改变调查路线。",
        )
        chapter_movements = [
            {
                "entry": "案桌上的缺页被重新排开，墨迹、折痕和缺口第一次连成可验证的顺序",
                "method": "他们先用最笨的办法逐项核对，把能确认的痕迹贴到墙上",
                "pressure": "问题从“有没有线索”变成“谁愿意先承认自己看见过线索”",
                "close": "源头没有完全显形，但调查已经不能再由一个人独自背着走",
            },
            {
                "entry": "现场的气味、脚印和错位物件把众人逼出室内推论",
                "method": "他们沿着三处停顿点复查，每走一步都要删掉一个旧解释",
                "pressure": "风险从解释转向行动，错误选择会直接暴露下一名参与者",
                "close": "路线被重新划出，下一幕必须去验证一个更窄、更危险的位置",
            },
            {
                "entry": "旧关系里的承诺变成证据，保护与真相第一次正面冲突",
                "method": "有人说出能证明的部分，也有人把不能公开的部分按在桌下",
                "pressure": "秘密仍在，但代价换了持有人，沉默不再只是拖延",
                "close": "信任被分层，接下来的选择取决于谁能接住不完整的记录",
            },
            {
                "entry": "官方口径切断了原来的调查路线，把线索逼到公开场合的阴影里",
                "method": "他们用反向排除法测试命令里的空白，寻找被刻意留白的人名",
                "pressure": "危险不再来自未知，而来自已经有人知道却要求大家装作不知道",
                "close": "线索成了一份风险账本，答案越近，公开它的代价越具体",
            },
            {
                "entry": "一次移交把边缘参与者推到中央，主角组看不见的入口被打开",
                "method": "他们不再抢同一条证据，而是把不同层级的见闻拼成临时地图",
                "pressure": "每个人都获得一部分权力，也因此必须承担一部分后果",
                "close": "调查向外扩散，最后留下的不是结论，而是必须交给下一人的责任",
            },
        ]
        scene_phase_moves = [
            {
                "hook": f"{scene_label}先抛出一个实际问题：{scene_objective}",
                "turn": f"新信息落在桌面上：{new_information}",
                "choice": f"{primary_name}必须立刻决定先查哪一处痕迹，不能再等别人替他确认。",
            },
            {
                "hook": f"{scene_label}从一次错误核对开始，上一幕的答案在这里失效。",
                "turn": f"冲突改变方向：{conflict_turn}",
                "choice": f"{primary_name}把可验证部分交给同伴，自己承担会暴露身份的那一步。",
            },
            {
                "hook": f"{scene_label}逼每个参与者说出一个能证明的事实和一个不敢公开的事实。",
                "turn": f"角色状态发生变化：{character_delta}",
                "choice": f"{primary_name}意识到真相不能只靠勇气推进，还需要有人承认代价。",
            },
            {
                "hook": f"{scene_label}把调查带到被阻断的位置，原计划在这里被迫改写。",
                "turn": f"这一幕不同于前一幕：{difference}",
                "choice": f"{primary_name}选择把线索藏进行动里，而不是急着给出解释。",
            },
            {
                "hook": f"{scene_label}让一个未被充分利用的入口打开，余波开始越过主角组。",
                "turn": f"新的推进不再是发现更多，而是决定哪些发现必须被带走。",
                "choice": f"{primary_name}把下一步交给更合适的人，自己留下处理已经产生的后果。",
            },
        ]
        movement = chapter_movements[(max(1, chapter_index) - 1) % len(chapter_movements)]
        phase = scene_phase_moves[(max(1, scene_index) - 1) % len(scene_phase_moves)]
        chapter_textures = [
            "这一章的叙事重心是从破损记录里找出第一条可复查的因果线。",
            "这一章把人物推到现场，让空间证据不断推翻室内推论。",
            "这一章专注关系代价，证词背后的保护、隐瞒和亏欠会逐步浮出。",
            "这一章让外部权力进入调查，命令、禁令和公开风险改变每个选择。",
            "这一章处理移交后的余波，边缘角色获得行动权，主角组必须让出部分控制。",
        ]
        chapter_texture = chapter_textures[
            (max(1, chapter_index) - 1) % len(chapter_textures)
        ]
        cast_sentence = "、".join(participant_names)
        scene_one_templates = [
            (
                f"{primary_name}把{story_context['record_object']}摊在案桌边缘，"
                f"第一眼先找缺口而不是找答案。{prompt_evidence_sentence}"
                f"{cast_sentence}用贴纸、折角和编号把线索分开，"
                f"{movement['entry']}。\n\n"
                f"第1章的开场只允许一个结论：{new_information}。"
                f"{primary_name}把能立刻复查的部分交给同伴，自己留下最容易出错的一段。\n\n"
                f"{movement['pressure']}。这一幕收在一条可执行路线，而不是谜底。"
            ),
            (
                f"第2章第1幕不从桌面开始，而从{story_context['main_location']}的地面痕迹开始。"
                f"{movement['entry']}。{prompt_evidence_sentence}\n\n"
                f"{primary_name}让{cast_sentence}各自站到一个检查点，"
                f"把{story_context['signal_or_trigger']}的残留和{story_context['record_object']}的缺损逐项对照。"
                f"{new_information}\n\n"
                f"{movement['pressure']}。结尾留下的是一个必须亲自抵达的位置。"
            ),
            (
                f"第3章第1幕先让关系开口。{cast_sentence}没有围成调查队形，"
                f"而是隔着{story_context['record_object']}确认谁在保护谁。{prompt_evidence_sentence}\n\n"
                f"{movement['entry']}。{primary_name}听见的不是解释，"
                f"而是一句会改变信任顺序的迟疑。{new_information}\n\n"
                f"{movement['pressure']}。幕尾把线索交给亏欠，而不是交给胆量。"
            ),
            (
                f"第4章第1幕被一条禁令切开。{primary_name}还没靠近证据，"
                f"{story_context['signal_or_trigger']}就已经被要求从公开记录里消失。{prompt_evidence_sentence}\n\n"
                f"{movement['method']}。{cast_sentence}必须在能说与不能说之间找出行动缝隙，"
                f"{new_information}\n\n"
                f"{movement['pressure']}。这一幕结束在一份不能公开署名的风险账本上。"
            ),
            (
                f"第5章第1幕把主动权交到边缘位置。{movement['entry']}。"
                f"{prompt_evidence_sentence}\n\n"
                f"{primary_name}没有抢回{story_context['record_object']}，"
                f"而是看着{cast_sentence}把证据分给更合适的人。{new_information}\n\n"
                f"{movement['pressure']}。收束时，故事得到的不是新答案，"
                f"而是一项必须转交出去的责任。"
            ),
        ]
        scene_one_template = scene_one_templates[
            (max(1, chapter_index) - 1) % len(scene_one_templates)
        ]
        synopsis = (
            f"{chapter_title}的{scene_label}让{participant_line}，"
            f"在{story_context['main_location']}把线索推进到新的{chapter_focus}。"
            f"{prompt_evidence_sentence}"
        )
        chapter_variant_seed = max(1, chapter_index) - 1
        scene_two_templates = [
            (
                f"{story_context['main_location']}的第二次核对没有沿用上一幕的答案。"
                f"{primary_name}先把{story_context['record_object']}按时间重新排开，"
                f"让每个人只指出自己亲眼确认过的一处缺口。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['method']}。{new_information}\n\n"
                f"真正的压力来自谁愿意先承认见过线索。{primary_name}留下最容易被质疑的证据，"
                f"把可复查的部分交给同伴带走，下一步因此变成一条公开核验路线。"
            ),
            (
                f"{scene_label}从室外的错位痕迹开始。{cast_sentence}分散到三个停顿点，"
                f"每个人负责排除一个旧解释，而不是重复上一幕的结论。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['method']}。{new_information}\n\n"
                f"{primary_name}把风险从纸面推到行动上：如果他们选错下一处位置，"
                f"被暴露的不是线索，而是正在帮他们的人。"
            ),
            (
                f"第3章的{scene_label}先让关系出错。{primary_name}没有急着追问事实，"
                f"而是请{cast_sentence}各自说出一件愿意证明的事和一件仍要保护的事。"
                f"{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['method']}。{new_information}\n\n"
                f"这一幕的转折不是找到更多证据，而是发现沉默本身也在改写证据的重量。"
            ),
            (
                f"{scene_label}被一条临时禁令截断。{primary_name}还没有碰到证据，"
                f"{story_context['signal_or_trigger']}就先被要求从公开记录中消失。"
                f"{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['method']}。{new_information}\n\n"
                f"他们不再问线索是否存在，而是判断谁已经知道、谁在命令别人装作不知道。"
            ),
            (
                f"{scene_label}把核对权交给边缘位置。{primary_name}退后一步，"
                f"让{cast_sentence}按各自能触及的层级拆分{story_context['record_object']}。"
                f"{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['method']}。{new_information}\n\n"
                f"这一幕结束时，证据不再属于最先发现它的人，而属于最能承担后果的人。"
            ),
        ]
        scene_three_templates = [
            (
                f"{scene_label}把线索从案桌推到人群里。{cast_sentence}围着同一处缺页，"
                f"说出的却是互相矛盾的证词。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{phase['turn']}\n\n"
                f"{primary_name}意识到继续推进需要一份共同承担的记录，"
                f"于是把{story_context['record_object']}分成可公开、待复查和必须保留的三栏。"
            ),
            (
                f"{scene_label}让现场开始反驳他们。脚印、气味和残留声响同时指向不同方向，"
                f"{cast_sentence}必须先删掉最顺手的解释。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{phase['turn']}\n\n"
                f"{primary_name}把行动路线缩到一个更窄的入口，逼所有人承认："
                f"下一次验证会直接改变他们能否继续接近真相。"
            ),
            (
                f"{scene_label}不靠新证物推进，而靠旧承诺裂开。"
                f"{primary_name}听见的每一句解释都带着保护别人的重量。"
                f"{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{phase['turn']}\n\n"
                f"幕尾没有给出结论，只让一段关系变成必须被记录的证据。"
            ),
            (
                f"{scene_label}进入公开场合的阴影。命令已经发出，"
                f"{cast_sentence}只能用旁证、沉默和缺席来拼出真实方向。"
                f"{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{phase['turn']}\n\n"
                f"{primary_name}把问题从“如何证明”改成“公开证明会伤到谁”，"
                f"下一步因此带上更明确的政治风险。"
            ),
            (
                f"{scene_label}让边缘参与者第一次决定证据去向。"
                f"{primary_name}没有接管局面，只负责确认每个人带走的部分不会互相抵消。"
                f"{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{phase['turn']}\n\n"
                f"收束时，故事得到的是一张临时地图，而不是单一答案。"
            ),
        ]
        scene_four_templates = [
            (
                f"阻断发生在第一条可执行路线之前。{primary_name}本想继续复查缺页，"
                f"却发现既有记录的排序本身已经被改动。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{difference}\n\n"
                f"{movement['close']}；{primary_name}只能把下一步压缩成一项更小但可验证的行动。"
            ),
            (
                f"{scene_label}把行动带到无法停留的位置。{story_context['signal_or_trigger']}短暂出现，"
                f"迫使{cast_sentence}边移动边判断哪条痕迹还能使用。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{difference}\n\n"
                f"他们离开时没有带走全部证据，只带走一个足够改变下一幕方向的位置。"
            ),
            (
                f"{scene_label}的阻断来自一个不能被公开的人名。{primary_name}必须在保护关系和推进调查之间"
                f"选择先伤害哪一种信任。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{difference}\n\n"
                f"这一幕把代价写清楚：真相可以继续走，但不能再假装没有牵连。"
            ),
            (
                f"{scene_label}被公开风险压住。命令的空白处比命令本身更危险，"
                f"{cast_sentence}只能把线索藏进行动顺序里。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{difference}\n\n"
                f"{primary_name}没有解释刚发现的内容，只安排下一次交接避开官方视线。"
            ),
            (
                f"{scene_label}让主动权继续外移。{primary_name}试图收束局面时，"
                f"边缘参与者已经带着关键碎片走向另一条路。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{difference}\n\n"
                f"这一幕留下的不是阻断，而是主角组必须接受的控制权损失。"
            ),
        ]
        scene_five_templates = [
            (
                f"{scene_label}收回到一条可执行路线。{primary_name}把能马上复查的痕迹封存，"
                f"把暂时不能公开的部分交给不同同伴保管。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['close']}。{phase['turn']}\n\n"
                f"章节结束时，问题没有被解开，但因果线第一次足够清楚，可以进入下一章的现场验证。"
            ),
            (
                f"{scene_label}把现场证据推向新的地点。{cast_sentence}不再争论解释，"
                f"而是确认下一章必须亲自抵达的坐标。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['close']}。{phase['turn']}\n\n"
                f"收束时，行动路线越窄，风险越具体。"
            ),
            (
                f"{scene_label}以一次关系选择收束。{primary_name}没有要求所有人立刻坦白，"
                f"只要求每个人承认自己正在保护什么。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['close']}。{phase['turn']}\n\n"
                f"章节留下的悬念不再是线索在哪，而是谁会为线索付出代价。"
            ),
            (
                f"{scene_label}把风险账本合上。公开命令仍在，"
                f"{primary_name}只能把下一步安排成一次不会留下署名的传递。"
                f"{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['close']}。{phase['turn']}\n\n"
                f"章节结束时，答案更近了，但公开答案的代价也第一次变得可计算。"
            ),
            (
                f"{scene_label}完成一次责任移交。{primary_name}把最后一份可复查记录交出去，"
                f"让{cast_sentence}决定各自能承担的后果。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['close']}。{phase['turn']}\n\n"
                f"故事没有停在结论上，而停在必须由下一位参与者继续执行的责任上。"
            ),
        ]
        phase_templates = [
            scene_one_template,
            scene_two_templates[chapter_variant_seed % len(scene_two_templates)],
            scene_three_templates[chapter_variant_seed % len(scene_three_templates)],
            scene_four_templates[chapter_variant_seed % len(scene_four_templates)],
            scene_five_templates[chapter_variant_seed % len(scene_five_templates)],
        ]
        normalized_scene_index = max(1, scene_index)
        if normalized_scene_index <= len(phase_templates):
            prose_text = phase_templates[normalized_scene_index - 1]
        else:
            extended_phase_steps = [
                "二次核验",
                "代价显形",
                "关系错位",
                "新入口打开",
                "局部失败",
                "证据转交",
                "公开压力",
                "隐瞒反噬",
                "行动分流",
                "短线回收",
                "误判修正",
                "关键选择",
                "风险扩大",
                "责任确认",
                "章节收束",
            ]
            phase_step = extended_phase_steps[min(normalized_scene_index, 20) - 6]
            prose_text = (
                f"{scene_label}进入{phase_step}阶段。{cast_sentence}没有重复上一幕的核对方式，"
                f"而是把{story_context['record_object']}拆成新的行动顺序。{prompt_evidence_sentence}\n\n"
                f"{chapter_texture}{movement['method']}。{new_information}\n\n"
                f"{primary_name}把这一幕的推进点限定为{phase_step}："
                f"{difference}。{movement['pressure']}。幕尾留下的不是同一个问题，"
                f"而是一项必须在下一幕承担的新后果。"
            )
    payload = {
        "synopsis": _mock_normalize_scene_index_text(synopsis, scene_index),
        "prose_text": _mock_normalize_scene_index_text(prose_text, scene_index),
    }
    return payload


def build_mock_scene_revision(schema_hint: dict) -> dict:
    story_context = project_story_context(schema_hint)
    style = story_context["style"]
    context = schema_hint.get("context") or {}
    prompt = schema_hint.get("revision_prompt") or context.get("revision_prompt") or ""
    intent = schema_hint.get("revision_intent") or context.get("revision_intent") or "detail_addition"
    current_scene = context.get("current_scene") or {}
    content = current_scene.get("content") or {}
    scene_index = _mock_scene_index(schema_hint)
    base_synopsis = _mock_normalize_scene_index_text(
        content.get("synopsis") or current_scene.get("synopsis") or "Current scene draft.",
        scene_index,
    )
    base_prose = _mock_normalize_scene_index_text(
        content.get("prose_text") or current_scene.get("prose_text") or "Current scene prose.",
        scene_index,
    )
    lower_prompt = prompt.lower()
    scene_label = _mock_scene_label(scene_index)
    revision_names = _mock_revision_character_names(schema_hint)
    lead_name = revision_names[0] if len(revision_names) > 0 else "角色A"
    second_name = revision_names[1] if len(revision_names) > 1 else "角色B"
    support_name = revision_names[2] if len(revision_names) > 2 else "角色C"
    collaborative_revision = (
        f"{lead_name}把阈值调整记录推到{second_name}面前，没有把推断当作结论，"
        "只标出能够被现有证据支撑的频率变化。"
        f"{support_name}压低声音提醒他们，消息源还不能暴露，"
        "远处安保主管的身影让这场临时合作带上被监视的压力。"
        "三人决定先保存证据副本，再沿着地下电台信号继续追查，"
        "核心谜团仍被留在下一步行动之后。"
    )
    clean_revision_core = "\n\n".join(
        [
            (
                f"{scene_label}开始时，{lead_name}没有再把{story_context['record_object']}握成一个答案。"
                f"他把记录摊开，让{second_name}逐项核对其中能够被证据支撑的变化。"
            ),
            (
                f"{story_context['signal_or_trigger']}只证明调查仍有入口，"
                f"{story_context['mystery_origin']}仍被留在阴影里。"
                f"{support_name}带来的地下电台线索让三人意识到，继续追查会暴露消息源，也会让他们进入被监视的范围。"
            ),
            collaborative_revision,
            (
                f"{scene_label}以三人保存证据副本并继续追查收束。"
                "他们没有宣布真相，只确认下一步必须沿着信号来源继续走下去。"
            ),
        ]
    )

    if intent == "event_outcome_change" or _mock_scene_releases_guard(prompt):
        revised_synopsis = (
            f"{base_synopsis} {scene_label}修订为保留活证人与后续后果。"
        )
        revised_prose_text = (
            "角色没有用致命结果结束冲突，而是放低武器，放走看守，并承认这个选择会让后续追查更困难。"
            f"\n\n{clean_revision_core}"
        )
        change_summary = ["将场景结果改为释放看守，并保留后续见证人与风险。"]
    elif intent in {"hard_rule_conflict", "world_rule_change"} or "sun rises" in lower_prompt:
        revised_synopsis = (
            f"{base_synopsis} {scene_label}修订仅把可能违反世界规则的内容保留为候选。"
        )
        revised_prose_text = (
            "被要求突破硬规则的动作没有直接写成既定事实；角色只记录到一个看似越界的候选现象，"
            "并等待后续确认它是否只是误读、传闻或需要人工确认的规则冲突。"
            f"\n\n{clean_revision_core}"
        )
        change_summary = ["将硬规则风险保留为候选，不直接写入正式事实。"]
    elif intent == "emotion_tone":
        revised_synopsis = f"{base_synopsis} {scene_label}修订为更克制、更压抑的情绪推进。"
        revised_prose_text = (
            "事实没有改变，但沉默变得更重。每一次确认线索都像是在把旧伤重新编号，"
            f"{lead_name}、{second_name}和{support_name}都明白，这次合作暂时成立，却远称不上安全。"
            f"\n\n{clean_revision_core}"
        )
        change_summary = ["调整情绪质感，不改变事件结果。"]
    elif intent == "style_only":
        revised_synopsis = f"{base_synopsis} {scene_label}修订为更清晰集中的表达。"
        revised_prose_text = clean_revision_core
        change_summary = ["润色表达，不改变承载记忆的事实。"]
    else:
        revised_synopsis = f"{base_synopsis} {scene_label}补强{style['scene_atmosphere']}的场面细节，但不越过已确认事实。"
        revised_prose_text = clean_revision_core
        change_summary = [f"补强{style['scene_atmosphere']}，不揭示受保护的未来信息。"]

    payload = {
        "revised_synopsis": _mock_normalize_scene_index_text(revised_synopsis, scene_index),
        "revised_prose_text": _mock_normalize_scene_index_text(revised_prose_text, scene_index),
        "change_summary": change_summary,
        "possible_impacts": [],
        "updated_story_information_notes": [
            "Revision candidate is complete text, not a patch.",
            f"Revision intent: {intent}.",
        ],
    }
    return payload


def build_mock_scene_memory(schema_hint: dict) -> dict:
    story_context = project_story_context(schema_hint)
    scene = schema_hint.get("scene") or {}
    approved_context = schema_hint.get("approved_context") or {}
    chapter = approved_context.get("chapter") or {}
    characters = approved_context.get("characters") or []
    relationships = approved_context.get("relationships") or []
    scene_index = _mock_scene_index(schema_hint)
    scene_label = _mock_scene_label(scene_index)
    scene_tag = _mock_scene_tag(scene_index)
    first_character_id = _mock_first_id(characters, "character_id", "char_scene_main_001")
    location_id = (
        ((approved_context.get("scene_information") or {}).get("environment") or {}).get("location_id")
        or _mock_scene_location(approved_context.get("world_canvas") or {}).get("location_id")
        or ""
    )
    relationship_id = _mock_first_id(relationships, "relationship_id", "")
    scene_id = scene.get("scene_id") or "scene_m7_001_001"
    content = scene.get("content") or {}
    revised_text = " ".join(
        [
            str(content.get("synopsis") or scene.get("synopsis") or ""),
            str(content.get("prose_text") or scene.get("prose_text") or ""),
        ]
    )

    event_summary = [
        {
            "summary": (
                f"角色在{story_context['record_object']}与{story_context['signal_or_trigger']}"
                "之间确认第一条可执行调查线索。"
            ),
            "participants": [first_character_id],
            "location_id": location_id,
            "cause": chapter.get("main_conflict") or "当前章需要建立调查入口。",
            "result": "角色决定暂时保留线索并继续调查。",
            "tags": [scene_tag, "first_clue", "memory_cost"],
            "status": "draft",
        }
    ]
    if _mock_scene_releases_guard(revised_text):
        event_summary[0]["summary"] = (
            "The revised scene changes the outcome: the protagonist releases the guard instead of killing them."
        )
        event_summary[0]["result"] = (
            "The guard survives and is released, leaving a living witness and future consequence."
        )
        event_summary[0]["tags"] = [scene_tag, "outcome_changed", "guard_released"]
    proposed_state_changes = [
        {
            "target_type": "character",
            "target_id": first_character_id,
            "before": {"active_goal": "确认线索是否可信"},
            "after": {
                "active_goal": (
                    f"继续追查{story_context['record_object']}与"
                    f"{story_context['signal_or_trigger']}的关系"
                )
            },
            "summary": "角色从旁观线索转向主动追查。",
            "requires_user_confirmation": False,
            "status": "confirmed",
        }
    ]
    relationship_changes = []
    if relationship_id:
        relationship_changes.append(
            {
                "relationship_id": relationship_id,
                "summary": "共同保留线索让双方出现有限信任。",
                "requires_user_confirmation": True,
            }
        )
        proposed_state_changes.append(
            {
                "target_type": "relationship",
                "target_id": relationship_id,
                "before": {"state": "互相试探"},
                "after": {"state": f"围绕{story_context['record_object']}形成有限合作"},
                "summary": "关系因共同线索出现有限信任。",
                "requires_user_confirmation": True,
                "status": "proposed",
            }
        )
    memory_records = [
        {
            "source_type": "scene_draft",
            "object_type": "scene",
            "object_id": scene_id,
            "summary": (
                f"{scene_label}确认{story_context['record_object']}与"
                f"{story_context['signal_or_trigger']}存在可追查关联，但"
                f"{story_context['mystery_origin']}仍未揭示。"
            ),
            "tags": [scene_tag, "source_record", "trigger_signal"],
        }
    ]
    payload = {
        "event_summary": event_summary,
        "proposed_state_changes": proposed_state_changes,
        "relationship_changes": relationship_changes,
        "memory_records": memory_records,
    }
    return payload


def build_mock_scene_quality(schema_hint: dict) -> dict:
    scene = schema_hint.get("scene") or {}
    content = scene.get("content") or {}
    synopsis = content.get("synopsis") or scene.get("synopsis") or ""
    prose_text = content.get("prose_text") or scene.get("prose_text") or ""
    warnings = []
    blocking_issues = []
    if not synopsis.strip():
        blocking_issues.append("Scene synopsis is empty.")
    if not prose_text.strip():
        blocking_issues.append("Scene prose_text is empty.")
    if "真正来源" in prose_text and "仍未" not in prose_text:
        blocking_issues.append("Scene appears to reveal a forbidden future world secret.")
    if "免费出现" in prose_text:
        warnings.append("Scene mentions memory/truth cost; keep this aligned with World Canvas hard rules.")
    return {
        "passed": len(blocking_issues) == 0,
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "requires_user_confirmation": False,
    }


def build_mock_quality_semantic(schema_hint: dict) -> dict:
    context = schema_hint.get("context") or {}
    scene = context.get("scene") or {}
    candidate = context.get("candidate") or {}
    content = {}
    if candidate:
        content = {
            "synopsis": candidate.get("revised_synopsis") or "",
            "prose_text": candidate.get("revised_prose_text") or "",
        }
    else:
        content = scene.get("content") or {}
    prose_text = " ".join(
        [
            str(content.get("synopsis") or scene.get("synopsis") or ""),
            str(content.get("prose_text") or scene.get("prose_text") or ""),
        ]
    )
    lowered = prose_text.lower()
    issues = []
    if "hard-rule conflict" in lowered or "sun rises at noon" in lowered:
        issues.append(
            {
                "category": "world_hard_rule",
                "severity": "blocking",
                "message": "场景明显触碰了已确认的世界硬规则。",
                "evidence": "hard-rule conflict marker",
                "suggested_action": "请调整修改提示，或使用显式硬规则 override 再由用户确认。",
            }
        )
    forbidden_truth_revealed = (
        "true source is" in lowered
        or "reveals forbidden truth" in lowered
        or "revealed forbidden truth" in lowered
        or "revealing forbidden truth" in lowered
        or "the forbidden truth is" in lowered
    )
    if forbidden_truth_revealed:
        issues.append(
            {
                "category": "character_motivation",
                "severity": "blocking",
                "message": "场景可能让角色提前知道了禁止知识。",
                "evidence": "forbidden truth marker",
                "suggested_action": "请保持该信息未知，或先更新角色知识范围。",
            }
        )
    if "impossible sudden knowledge" in lowered or "sudden knowledge" in lowered:
        issues.append(
            {
                "category": "causal_completeness",
                "severity": "warning",
                "message": "场景出现了缺少来源的突然知识。",
                "evidence": "sudden knowledge marker",
                "suggested_action": "补充线索来源或降低角色确定性。",
            }
        )
    if "story info missing" in lowered:
        issues.append(
            {
                "category": "story_information_coverage",
                "severity": "warning",
                "message": "场景可能遗漏了必须使用的故事信息。",
                "evidence": "story info missing marker",
                "suggested_action": "重新检查 ordered story information package。",
            }
        )
    if "framework mismatch" in lowered or "chapter goal mismatch" in lowered:
        issues.append(
            {
                "category": "framework_alignment",
                "severity": "warning",
                "message": "场景与当前章节目标或框架组件的对齐较弱。",
                "evidence": "alignment marker",
                "suggested_action": "确认这一幕是否仍服务于当前章节目标。",
            }
        )
    return {
        "issues": issues,
        "summary": "语义质量检查完成。" if issues else "语义质量检查未发现明显问题。",
    }


def _mock_framework_component_labels(modules: list) -> list[str]:
    labels = []
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_label = module.get("label") or module.get("module_id") or ""
        component_labels = [
            component.get("label") or component.get("component_id")
            for component in module.get("components") or []
            if isinstance(component, dict)
        ]
        if component_labels:
            labels.append(f"{module_label}: {' / '.join(component_labels)}")
        elif module_label:
            labels.append(module_label)
    return labels


def _mock_scene_location(world_canvas: dict) -> dict:
    locations = world_canvas.get("locations") or []
    if locations and isinstance(locations[0], dict):
        return locations[0]
    return {
        "location_id": "loc_core_stage_001",
        "name": "核心异常区",
        "summary": "当前场景可进入的核心舞台。",
    }


def _mock_first_id(items: list, key: str, fallback: str) -> str:
    for item in items:
        if isinstance(item, dict) and item.get(key):
            return item[key]
    return fallback


def _mock_scene_index(schema_hint: dict) -> int:
    if not isinstance(schema_hint, dict):
        return 1
    candidates = [
        schema_hint,
        schema_hint.get("approved_context") or {},
        schema_hint.get("context") or {},
        (schema_hint.get("context") or {}).get("current_scene") or {},
        ((schema_hint.get("context") or {}).get("current_scene") or {}).get("scene_information")
        or {},
        (schema_hint.get("approved_context") or {}).get("scene_information") or {},
        schema_hint.get("scene") or {},
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("scene_index", "index"):
            value = candidate.get(key)
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
    scene_id = str((schema_hint.get("scene") or {}).get("scene_id") or "")
    match = re.search(r"_(\d{3})$", scene_id)
    if match:
        parsed = int(match.group(1))
        if parsed > 0:
            return parsed
    return 1


def _mock_scene_label(scene_index: int) -> str:
    return f"第{max(1, scene_index)}幕"


def _mock_scene_tag(scene_index: int) -> str:
    return f"scene_{max(1, scene_index)}"


def _mock_normalize_scene_index_text(text: str, scene_index: int) -> str:
    if not isinstance(text, str):
        return ""
    scene_label = _mock_scene_label(scene_index)
    scene_tag = _mock_scene_tag(scene_index)
    normalized = text
    for marker in ("第一幕", "第 1 幕", "第1幕"):
        normalized = normalized.replace(marker, scene_label)
    normalized = normalized.replace("scene_1", scene_tag)
    malformed_replacements = {
        "手里的中存在人为调整阈值的记录": "手里的阈值调整记录",
        "手里的存在人为调整阈值的记录": "手里的阈值调整记录",
        "在中存在人为调整阈值的记录与": "在阈值调整记录与",
        "中存在人为调整阈值的记录与": "阈值调整记录与",
        "中存在人为调整阈值的记录": "人为调整阈值的记录",
    }
    for malformed, replacement in malformed_replacements.items():
        normalized = normalized.replace(malformed, replacement)
    return normalized


def _mock_revision_character_names(schema_hint: dict) -> list[str]:
    context = schema_hint.get("context") or {}
    characters = (
        context.get("allowed_revision_characters")
        or context.get("characters")
        or schema_hint.get("allowed_revision_characters")
        or schema_hint.get("characters")
        or []
    )
    names: list[str] = []
    for character in characters:
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or "").strip()
        character_id = str(character.get("character_id") or "").strip()
        if name:
            names.append(name)
        elif character_id:
            names.append(character_id)
    if names:
        return names
    return []


def _mock_scene_releases_guard(text: str) -> bool:
    lower_text = text.lower()
    if any(
        marker in lower_text
        for marker in [
            "release the guard",
            "releases the guard",
            "spare the guard",
            "spares the guard",
            "does not kill",
            "do not kill",
            "instead of killing the guard",
            "guard survives",
        ]
    ):
        return True
    guard_context = any(marker in text for marker in ["守卫", "看守", "卫兵"])
    outcome_context = any(marker in text for marker in ["放走", "释放", "不杀", "不要杀", "活下来"])
    return guard_context and outcome_context
