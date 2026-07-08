from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .evidence_packet import build_evidence_packet
from .raw_source_index_builder import load_raw_source_index, load_raw_source_segments, normalize_for_search


EVIDENCE_RETRIEVAL_VERSION = "story_analyzer.evidence_retrieval.v2_1"
_SEGMENT_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
_ENGLISH_STOPWORDS = {
    "the",
    "and",
    "with",
    "that",
    "this",
    "into",
    "from",
    "here",
    "there",
    "then",
    "than",
    "when",
    "where",
    "which",
    "while",
    "after",
    "before",
}
_CJK_ACTION_TERMS = {
    "收到",
    "拒绝",
    "接受",
    "进入",
    "离开",
    "前往",
    "返回",
    "加入",
    "发现",
    "确认",
    "揭示",
    "打开",
    "关闭",
    "获得",
    "失去",
    "使用",
    "释放",
    "唤醒",
    "击败",
    "保护",
    "救下",
    "袭击",
    "调查",
    "看见",
    "听见",
    "知道",
    "意识到",
    "暴露",
    "隐藏",
    "出现",
    "消失",
    "带回",
    "带走",
    "拿到",
    "拿走",
    "拿出",
    "找到",
    "寻找",
    "追踪",
    "逃离",
    "交换",
    "交给",
    "交出",
    "交还",
    "支付",
    "递给",
    "递交",
    "发送",
    "发出",
    "寄出",
    "送达",
    "领取",
    "接过",
    "签收",
    "牺牲",
    "承认",
    "隐瞒",
    "背负",
    "触发",
    "改变",
    "完成",
    "开始",
    "结束",
    "对抗",
    "连接",
    "绑定",
    "回收",
    "埋下",
    "杀死",
    "背叛",
}
_CJK_NEGATION_TERMS = (
    "并没有",
    "并未",
    "没有",
    "未能",
    "尚未",
    "从未",
    "不曾",
    "无法",
    "不能",
    "没能",
    "未",
    "没",
    "不",
)


def _parse_range_list(value: Any) -> set[int]:
    if value is None:
        return set()
    if isinstance(value, int):
        return {value}
    if isinstance(value, list):
        result: set[int] = set()
        for item in value:
            result.update(_parse_range_list(item))
        return result
    text = str(value).strip()
    if not text:
        return set()
    result: set[int] = set()
    for part in re.split(r"[,，;；]\s*", text):
        if not part:
            continue
        match = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if end < start:
                start, end = end, start
            result.update(range(start, end + 1))
        elif part.isdigit():
            result.add(int(part))
    return result


def _dedupe_terms(values: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for value in values:
        term = normalize_for_search(value)
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _cjk_ngrams(value: str, *, min_n: int = 2, max_n: int = 4) -> list[str]:
    grams: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", value):
        if 2 <= len(run) <= 12:
            grams.append(run)
        upper = min(max_n, len(run))
        for size in range(min_n, upper + 1):
            for start in range(0, len(run) - size + 1):
                grams.append(run[start : start + size])
    return grams


def _term_candidates(value: str, *, limit: int = 32) -> list[str]:
    normalized = normalize_for_search(value)
    english_terms = [
        term
        for term in re.findall(r"[a-z][a-z0-9_'-]{2,}", normalized)
        if term not in _ENGLISH_STOPWORDS
    ]
    cjk_terms = _cjk_ngrams(normalized)
    return _dedupe_terms([*english_terms, *cjk_terms], limit=limit)


def _cjk_action_candidates(run: str, explicit_action_terms: list[str] | None = None) -> list[str]:
    actions: list[str] = []
    for term in explicit_action_terms or []:
        normalized = normalize_for_search(term)
        if _has_cjk(normalized) and normalized in run:
            actions.append(normalized)
    for term in sorted(_CJK_ACTION_TERMS, key=len, reverse=True):
        if term in run:
            actions.append(term)
    return _dedupe_terms(actions, limit=8)


def _cjk_action_positions(run: str, action: str) -> list[int]:
    positions: list[int] = []
    start = run.find(action)
    while start >= 0:
        positions.append(start)
        start = run.find(action, start + len(action))
    return positions


def _cjk_action_is_negated(run: str, action_start: int) -> bool:
    prefix = run[max(0, action_start - 8) : action_start]
    return any(term in prefix for term in _CJK_NEGATION_TERMS)


def _cjk_object_key(value: str) -> str:
    text = normalize_for_search(value)
    for prefix in ("了", "过", "着"):
        while text.startswith(prefix):
            text = text[len(prefix) :]
    for prefix in ("来自", "一封", "一份", "一个", "这封", "那封", "该"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.replace("的", "")


def _cjk_subject_key_before_action(run: str, action_start: int) -> str:
    subject = run[:action_start]
    for marker in ("在", "于", "从", "向", "把", "将", "被", "对"):
        position = subject.find(marker)
        if position >= 2:
            subject = subject[:position]
            break
    for negation in sorted(_CJK_NEGATION_TERMS, key=len, reverse=True):
        if subject.endswith(negation):
            subject = subject[: -len(negation)]
            break
    return normalize_for_search(subject).replace("的", "")


def _cjk_object_text_after_action(run: str, action: str, *, action_start: int | None = None) -> str:
    if action_start is None:
        action_start = run.find(action)
    if action_start < 0:
        return ""
    action_end = action_start + len(action)
    object_text = run[action_end:]
    if len(object_text) < 2:
        return ""
    cut_positions = [
        object_text.find(marker)
        for marker in ("之后", "以后", "随后", "然后", "之前", "以前", "后", "前", "时", "并", "又", "再", "但", "却", "而")
        if object_text.find(marker) >= 2
    ]
    for next_action in sorted(_CJK_ACTION_TERMS, key=len, reverse=True):
        position = object_text.find(next_action)
        if position >= 2:
            cut_positions.append(position)
    if cut_positions:
        object_text = object_text[: min(cut_positions)]
    if len(object_text) < 2:
        return ""
    return object_text


def _cjk_object_terms_after_action(run: str, action: str, *, action_start: int | None = None) -> list[str]:
    object_text = _cjk_object_text_after_action(run, action, action_start=action_start)
    if not object_text:
        return []
    terms = [object_text] if len(object_text) <= 10 else []
    for size in range(min(8, len(object_text)), 1, -1):
        terms.append(object_text[-size:])
    return _dedupe_terms(terms, limit=8)


def _cjk_required_support_plans(
    value: str,
    *,
    explicit_action_terms: list[str] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", normalize_for_search(value)):
        if len(run) < 5:
            continue
        for action in _cjk_action_candidates(run, explicit_action_terms=explicit_action_terms):
            for action_start in _cjk_action_positions(run, action):
                object_text = _cjk_object_text_after_action(run, action, action_start=action_start)
                object_terms = _cjk_object_terms_after_action(run, action, action_start=action_start)
                if not object_terms:
                    continue
                plans.append(
                    {
                        "action_terms": [action],
                        "subject_key": _cjk_subject_key_before_action(run, action_start),
                        "object_text": object_text,
                        "object_terms": object_terms,
                        "negated": _cjk_action_is_negated(run, action_start),
                    }
                )
                if len(plans) >= limit:
                    return plans
    return plans


def _cjk_support_plan_status(normalized_text: str, plan: dict[str, Any]) -> str:
    wanted_negated = bool(plan.get("negated"))
    claim_subject_key = str(plan.get("subject_key") or "")
    claim_object_text = _cjk_object_key(str(plan.get("object_text") or ""))
    saw_negation_mismatch = False
    saw_subject_mismatch = False
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized_text):
        for action in plan.get("action_terms") or []:
            for action_start in _cjk_action_positions(run, action):
                source_object_text = _cjk_object_key(_cjk_object_text_after_action(run, action, action_start=action_start))
                if not claim_object_text or claim_object_text not in source_object_text:
                    continue
                source_subject_key = _cjk_subject_key_before_action(run, action_start)
                if claim_subject_key and claim_subject_key not in source_subject_key:
                    saw_subject_mismatch = True
                    continue
                if _cjk_action_is_negated(run, action_start) == wanted_negated:
                    return "supported"
                saw_negation_mismatch = True
    if saw_negation_mismatch:
        return "negation_mismatch"
    if saw_subject_mismatch:
        return "subject_mismatch"
    return "missing"


def _expanded_terms(values: Any, *, limit: int) -> list[str]:
    terms: list[str] = []
    for value in values or []:
        text = normalize_for_search(str(value))
        if not text:
            continue
        terms.append(text)
        terms.extend(_term_candidates(text, limit=12))
    return _dedupe_terms(terms, limit=limit)


def _claim_terms(claim: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    claim_text = normalize_for_search(str(claim.get("claim_text") or ""))
    source_terms = _expanded_terms(claim.get("source_terms"), limit=24)
    action_terms = _expanded_terms(claim.get("action_terms"), limit=16)
    state_terms = _expanded_terms(claim.get("state_terms"), limit=16)
    action_terms = _dedupe_terms([*action_terms, *state_terms], limit=24)
    if not source_terms:
        source_terms = _term_candidates(claim_text, limit=24)
    claim_words = _term_candidates(claim_text, limit=48)
    return source_terms, action_terms, claim_words


def _phrase_hit(text: str, phrase: str) -> bool:
    return bool(phrase and phrase in text)


def _coverage(hits: list[str], terms: list[str], *, denominator_cap: int | None = None) -> float:
    unique_hits = set(hits)
    unique_terms = set(terms)
    denominator = len(unique_terms)
    if denominator_cap is not None:
        denominator = min(denominator, denominator_cap)
    return min(1.0, len(unique_hits) / max(1, denominator))


def _score_segment(segment: dict[str, Any], claim: dict[str, Any]) -> tuple[float, str]:
    normalized = segment.get("normalized_text") or normalize_for_search(segment.get("text", ""))
    claim_text = normalize_for_search(str(claim.get("claim_text") or ""))
    source_terms, action_terms, claim_words = _claim_terms(claim)
    entity_hits = [term for term in source_terms if _phrase_hit(normalized, term)]
    action_hits = [term for term in action_terms if _phrase_hit(normalized, term)]
    word_hits = [term for term in claim_words if _phrase_hit(normalized, term)]

    entity_score = _coverage(entity_hits, source_terms, denominator_cap=8)
    action_score = _coverage(action_hits, action_terms, denominator_cap=6) if action_terms else 0.0
    word_score = _coverage(word_hits, claim_words, denominator_cap=10)
    longest_entity_hit = max((len(term) for term in entity_hits), default=0)
    rare_bonus = 0.1 if longest_entity_hit >= 8 else 0.0
    exact_claim_bonus = 0.15 if len(claim_text) >= 8 and _phrase_hit(normalized, claim_text) else 0.0
    cjk_hit_count = len({term for term in [*entity_hits, *word_hits] if _has_cjk(term)})
    cjk_bonus = 0.15 if cjk_hit_count >= 3 else 0.08 if cjk_hit_count >= 2 else 0.0
    score = 0.45 * entity_score + 0.2 * action_score + 0.2 * word_score + rare_bonus + exact_claim_bonus + cjk_bonus
    reasons: list[str] = []
    if entity_hits:
        reasons.append("entity_overlap")
    if action_hits:
        reasons.append("action_overlap")
    if word_hits:
        reasons.append("claim_word_overlap")
    if exact_claim_bonus:
        reasons.append("exact_claim_phrase")
    if cjk_bonus:
        reasons.append("cjk_ngram_overlap")
    return min(score, 1.0), ",".join(reasons) or "no_overlap"


def _requires_cjk_action_plan(claim: dict[str, Any]) -> bool:
    return str(claim.get("claim_type") or "event_fact") == "event_fact"


def _cjk_discriminative_status(segment: dict[str, Any], claim: dict[str, Any]) -> tuple[bool, str]:
    claim_text = normalize_for_search(str(claim.get("claim_text") or ""))
    if not _has_cjk(claim_text):
        return True, ""
    normalized = segment.get("normalized_text") or normalize_for_search(segment.get("text", ""))
    if len(claim_text) >= 8 and _phrase_hit(normalized, claim_text):
        return True, ""
    explicit_action_terms = [
        str(term)
        for term in [*(claim.get("action_terms") or []), *(claim.get("state_terms") or [])]
        if str(term).strip()
    ]
    support_plans = _cjk_required_support_plans(claim_text, explicit_action_terms=explicit_action_terms)
    if not support_plans:
        if _requires_cjk_action_plan(claim):
            return False, "cjk_action_unrecognized"
        return True, ""
    saw_negation_mismatch = False
    saw_subject_mismatch = False
    for plan in support_plans:
        plan_status = _cjk_support_plan_status(normalized, plan)
        if plan_status == "supported":
            return True, ""
        if plan_status == "negation_mismatch":
            saw_negation_mismatch = True
        if plan_status == "subject_mismatch":
            saw_subject_mismatch = True
    if saw_negation_mismatch:
        return False, "cjk_action_negation_mismatch"
    if saw_subject_mismatch:
        return False, "cjk_subject_mismatch"
    return False, "cjk_action_or_object_missing"


def _scope_filter(segment: dict[str, Any], retrieval_scope: dict[str, Any] | None) -> bool:
    if not retrieval_scope:
        return True
    segment_ids = set(retrieval_scope.get("segment_ids") or [])
    if segment_ids and segment.get("segment_id") not in segment_ids:
        return False
    source_chapters = _parse_range_list(retrieval_scope.get("source_chapter_range") or retrieval_scope.get("source_chapters"))
    if source_chapters and int(segment.get("source_chapter_index") or 0) not in source_chapters:
        return False
    analysis_units = _parse_range_list(retrieval_scope.get("analysis_unit_range") or retrieval_scope.get("analysis_units"))
    if analysis_units and int(segment.get("analysis_unit_index") or 0) not in analysis_units:
        return False
    return True


def _all_segments_for_run(run_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "evidence" / "raw_source_segments.jsonl"
    stat = path.stat()
    key = (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    cached = _SEGMENT_CACHE.get(key)
    if cached is not None:
        return cached
    segments = load_raw_source_segments(run_dir)
    _SEGMENT_CACHE.clear()
    _SEGMENT_CACHE[key] = segments
    return segments


def _segment_ids_for_scope(index: dict[str, Any], retrieval_scope: dict[str, Any] | None) -> set[str]:
    if not retrieval_scope:
        return set()
    explicit_ids = {str(item) for item in retrieval_scope.get("segment_ids") or [] if item}
    source_chapters = _parse_range_list(retrieval_scope.get("source_chapter_range") or retrieval_scope.get("source_chapters"))
    analysis_units = _parse_range_list(retrieval_scope.get("analysis_unit_range") or retrieval_scope.get("analysis_units"))
    if not source_chapters and not analysis_units:
        return explicit_ids
    scoped_ids: set[str] = set()
    chapters = index.get("chapters") if isinstance(index, dict) else []
    if not isinstance(chapters, list):
        return explicit_ids
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        source_index = int(chapter.get("source_chapter_index") or 0)
        analysis_index = int(chapter.get("analysis_unit_index") or 0)
        if source_chapters and source_index not in source_chapters:
            continue
        if analysis_units and analysis_index not in analysis_units:
            continue
        scoped_ids.update(str(item) for item in chapter.get("segment_ids") or [] if item)
    if explicit_ids and scoped_ids:
        return explicit_ids & scoped_ids
    return explicit_ids or scoped_ids


def _expanded_segment_ids(index: dict[str, Any], segment_ids: set[str]) -> set[str]:
    if not segment_ids:
        return set()
    expanded = set(segment_ids)
    chapters = index.get("chapters") if isinstance(index, dict) else []
    if not isinstance(chapters, list):
        return expanded
    for chapter in chapters:
        ids = [str(item) for item in chapter.get("segment_ids") or [] if item] if isinstance(chapter, dict) else []
        for position, segment_id in enumerate(ids):
            if segment_id not in segment_ids:
                continue
            if position > 0:
                expanded.add(ids[position - 1])
            if position + 1 < len(ids):
                expanded.add(ids[position + 1])
    return expanded


def _candidate_segments(
    run_dir: str | Path,
    index: dict[str, Any],
    retrieval_scope: dict[str, Any] | None,
    *,
    expand_adjacent: bool = True,
) -> list[dict[str, Any]]:
    scoped_ids = _segment_ids_for_scope(index, retrieval_scope)
    if scoped_ids:
        if expand_adjacent:
            scoped_ids = _expanded_segment_ids(index, scoped_ids)
        return load_raw_source_segments(run_dir, segment_ids=scoped_ids)
    return [segment for segment in _all_segments_for_run(run_dir) if _scope_filter(segment, retrieval_scope)]


def _quote_for_segment(segment: dict[str, Any], claim: dict[str, Any], *, quote_radius: int = 260) -> str:
    text = str(segment.get("text") or "")
    normalized = normalize_for_search(text)
    source_terms, action_terms, claim_words = _claim_terms(claim)
    anchors = [*source_terms, *action_terms, *claim_words]
    positions = [normalized.find(anchor) for anchor in anchors if anchor and normalized.find(anchor) >= 0]
    if not positions:
        return text[: quote_radius * 2].strip()
    start = max(0, min(positions) - quote_radius)
    end = min(len(text), min(positions) + quote_radius)
    return text[start:end].strip()


def retrieve_evidence_for_claim(
    run_dir: str | Path,
    claim: dict[str, Any],
    *,
    retrieval_scope: dict[str, Any] | None = None,
    top_k: int = 5,
    min_score: float = 0.35,
    expand_adjacent: bool = True,
) -> dict[str, Any]:
    index = load_raw_source_index(run_dir)
    candidates = _candidate_segments(run_dir, index, retrieval_scope, expand_adjacent=expand_adjacent)
    scored: list[dict[str, Any]] = []
    for segment in candidates:
        score, reason = _score_segment(segment, claim)
        if score <= 0:
            continue
        cjk_supported, cjk_reason = _cjk_discriminative_status(segment, claim)
        if not cjk_supported:
            score = min(score, max(0.0, min_score - 0.01))
            reason = f"{reason},{cjk_reason}"
        scored.append(
            {
                "segment_id": segment.get("segment_id", ""),
                "source_chapter_index": segment.get("source_chapter_index"),
                "analysis_unit_index": segment.get("analysis_unit_index"),
                "char_start": segment.get("char_start"),
                "char_end": segment.get("char_end"),
                "quote": _quote_for_segment(segment, claim),
                "score": score,
                "match_reason": reason,
                "_cjk_discriminative_supported": cjk_supported,
                "_cjk_discriminative_reason": cjk_reason,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    top_items = scored[:top_k]
    support_status = "supported" if top_items and top_items[0]["score"] >= min_score else "insufficient"
    support_reason = (
        f"scored {len(scored)}/{len(candidates)} matching segments; "
        f"top evidence score {top_items[0]['score']:.2f} from {top_items[0]['segment_id']}"
        if top_items
        else f"scored 0/{len(candidates)} matching segments; no segment matched claim terms within retrieval scope"
    )
    if top_items and not top_items[0].get("_cjk_discriminative_supported", True):
        support_reason += f"; {top_items[0].get('_cjk_discriminative_reason') or 'cjk_action_or_object_missing'}"
    scope = dict(retrieval_scope or {})
    scope.setdefault("raw_source_index", str(Path(run_dir) / "evidence" / "raw_source_index.json"))
    scope.setdefault("segment_count", index.get("segment_count", 0))
    scope.setdefault("retrieval_version", EVIDENCE_RETRIEVAL_VERSION)
    scope["candidate_segment_count"] = len(candidates)
    scope["matched_segment_count"] = len(scored)
    scoped_ids = _segment_ids_for_scope(index, retrieval_scope)
    if scoped_ids:
        scope["requested_segment_count"] = len(scoped_ids)
        scope["expanded_segment_count"] = len({str(item.get("segment_id") or "") for item in candidates if item.get("segment_id")})
    return build_evidence_packet(
        packet_id=f"EP_{claim.get('claim_id', 'CLAIM')}",
        target_path=str(claim.get("target_path") or ""),
        claim=claim,
        evidence_items=top_items,
        support_status=support_status,
        support_reason=support_reason,
        retrieval_scope=scope,
    )
