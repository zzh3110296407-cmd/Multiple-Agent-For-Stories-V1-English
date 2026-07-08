from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


PROMPT_MACHINE_MARKER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,}\b")
CJK_TEXT_RE = re.compile(r"[\u4e00-\u9fff]{2,32}")
ASCII_TEXT_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_\-]{2,}\b")
NAME_CUE_RE = re.compile(
    r"(?:\u4e3b\u89d2|\u89d2\u8272|\u4eba\u7269|\u8bb0\u5f55\u5458|\u5bfc\u5e08|\u770b\u5b88|\u59d3\u540d|\u540d\u5b57)?"
    r"(?:\u540d\u4e3a|\u53eb\u4f5c|\u53eb|\u540d\u5b57\u662f|\u59d3\u540d\u662f)([\u4e00-\u9fff]{2,8})"
)

NEGATIVE_MARKERS = (
    "\u4e0d\u5f97",
    "\u4e0d\u80fd",
    "\u4e0d\u8981",
    "\u7981\u6b62",
    "\u4e0d\u53ef",
    "\u907f\u514d",
    "\u6392\u9664",
    "\u4e0d\u5e94\u5305\u542b",
    "\u4e0d\u8981\u52a0\u5165",
    "\u4e0d\u80fd\u51fa\u73b0",
    "\u4e0d\u5f97\u628a",
    "\u4e0d\u8981\u4f7f\u7528",
    "\u4e0d\u8981\u5199\u6210",
    "do not include",
    "don't include",
    "must not include",
    "should not include",
    "never include",
    "not allowed",
    "must not be",
    "exclude",
    "avoid",
    "without",
    "forbid",
)

GENERIC_ASCII_TERMS = {
    "and",
    "about",
    "are",
    "but",
    "can",
    "chapter",
    "chapters",
    "character",
    "characters",
    "create",
    "draft",
    "format",
    "generate",
    "generated",
    "generation",
    "include",
    "language",
    "marker",
    "markers",
    "must",
    "not",
    "never",
    "output",
    "phase85",
    "project",
    "prompt",
    "required",
    "scene",
    "scenes",
    "story",
    "style",
    "template",
    "test",
    "user",
    "without",
    "with",
    "world",
    "write",
}

GENERIC_CJK_TERMS = {
    "\u4e00\u4e2a",
    "\u4e00\u90e8",
    "\u4e3b\u89d2",
    "\u4eba\u7269",
    "\u89d2\u8272",
    "\u6545\u4e8b",
    "\u4e16\u754c",
    "\u89c4\u5219",
    "\u6838\u5fc3",
    "\u5730\u70b9",
    "\u8eab\u4efd",
    "\u7ebf\u7d22",
    "\u573a\u666f",
    "\u7ae0\u8282",
    "\u5f53\u524d",
    "\u771f\u5b9e",
    "\u6e05\u6670",
    "\u63a8\u8fdb",
    "\u4e2d\u6587",
    "\u8bb0\u5fc6",
    "\u63d0\u793a",
    "\u7528\u6237",
    "\u9879\u76ee",
    "\u6d41\u7a0b",
    "\u9a8c\u6536",
    "\u521b\u4f5c",
    "\u751f\u6210",
}

META_CONTROL_SUBSTRINGS = {
    "\u524d\u7aef",
    "\u9a8c\u6536",
    "\u6d41\u7a0b",
    "\u6d4b\u8bd5",
    "\u521b\u5efa",
    "\u751f\u6210",
    "\u521b\u4f5c",
    "\u8981\u6c42",
    "\u4fdd\u6301",
    "\u77ed\u6d41\u7a0b",
    "\u77ed\u7bc7",
    "\u7ae0\u8282",
    "\u6bcf\u7ae0",
    "\u6bcf\u5e55",
    "\u63d0\u793a",
    "\u63d0\u793a\u8bcd",
    "\u539f\u5178\u63d0\u793a",
    "\u7528\u6237\u63d0\u4f9b",
    "\u7528\u6237\u8f93\u5165",
    "\u9879\u76ee",
    "\u5de5\u4f5c\u53f0",
    "\u786e\u8ba4",
    "\u5bfc\u51fa",
    "\u957f\u7bc7\u4e2d\u6587\u6545\u4e8b",
    "\u6545\u4e8b\u4eba\u7269",
    "\u53ea\u80fd\u6765\u81ea",
    "frontend",
    "verification",
    "workflow",
    "test",
    "prompt",
    "output",
    "format",
    "chapter count",
    "scene count",
}

CJK_SPLITTER = re.compile(
    r"(?:"
    r"\u4e3b\u89d2|\u4eba\u7269|\u89d2\u8272|\u4e16\u754c\u6838\u5fc3\u89c4\u5219|\u4e16\u754c\u89c4\u5219|\u6838\u5fc3\u89c4\u5219|"
    r"\u5730\u70b9|\u8eab\u4efd|\u540d\u4e3a|\u53eb\u4f5c|\u53eb|\u662f|\u53d1\u751f\u5728|\u4f4d\u4e8e|\u7528\u4e8e|"
    r"\u7528\u6765|\u521b\u5efa|\u521b\u4f5c|\u751f\u6210|\u5199|\u4fdd\u6301|\u63a8\u8fdb|\u9a8c\u6536|\u6d41\u7a0b|"
    r"\u53ea\u6709|\u4e00\u7ae0|\u4e24\u5e55|\u77ed\u7bc7|\u4e2d\u6587|\u6545\u4e8b|\u89c4\u5219|\u8981\u6c42|"
    r"\u5fc5\u987b|\u9700\u8981|\u4f1a|\u628a|\u88ab|\u8ba9|\u5c06|\u52a0\u5165|\u5305\u542b|\u51fa\u73b0|"
    r"\u627e\u5230|\u5bfb\u627e|\u6539\u5199|\u6307\u5411|\u56f4\u7ed5|\u4fdd\u7559|\u5173\u4e8e|\u4ee5\u53ca|\u5e76\u4e14|"
    r"\u800c\u4e14|\u548c|\u4e0e|\u53ca|\u6216|\u7684|\u5728|\u91cc|\u4e2d"
    r")"
)

POSITIVE_LEAD_BOUNDARY_RE = re.compile(
    r"(?:[\uff0c,]\s*)"
    r"(?:"
    r"\u6545\u4e8b\u56f4\u7ed5|\u4e3b\u7ebf\u56f4\u7ed5|\u5267\u60c5\u56f4\u7ed5|\u60c5\u8282\u56f4\u7ed5|\u53d9\u4e8b\u56f4\u7ed5|"
    r"\u6545\u4e8b\u805a\u7126|\u4e3b\u7ebf\u805a\u7126|\u5267\u60c5\u805a\u7126|\u60c5\u8282\u805a\u7126|"
    r"\u5fc5\u987b\u4fdd\u7559|\u9700\u8981\u4fdd\u7559|\u5e94\u5f53\u4fdd\u7559|\u8bf7\u4fdd\u7559|"
    r"\u5199\u6210|\u6539\u5199\u6210|\u521b\u4f5c\u6210|"
    r"\u4ee5[\u4e00-\u9fffA-Za-z0-9_\-\s]{1,32}\u4e3a\u6838\u5fc3|"
    r"\u56f4\u7ed5[\u4e00-\u9fffA-Za-z0-9_\-\s]{1,32}\u5c55\u5f00|"
    r"write\s+(?:a\s+)?(?:story\s+)?about|focus\s+on|cent(?:er|re)\s+on|"
    r"make\s+(?:it|the\s+story)\s+about|"
    r"must\s+(?:keep|preserve|retain)|should\s+(?:keep|preserve|retain)|"
    r"keep|preserve|retain|include|use"
    r")",
    re.IGNORECASE,
)
SENTENCE_BOUNDARY_RE = re.compile(r"[\n\r.;!?\u3002\uff1b\uff01\uff1f]+")
TRANSITION_BOUNDARY_RE = re.compile(
    r"(?:\bbut\b|\bhowever\b|\bexcept\b|\binstead\b|\u4f46|\u4f46\u662f|\u800c\u662f|\u4e0d\u8fc7)",
    re.IGNORECASE,
)


class PromptAnchorClassification(BaseModel):
    positive_required_anchors: list[str] = Field(default_factory=list)
    forbidden_anchors: list[str] = Field(default_factory=list)
    meta_control_terms: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    source_notes: list[dict[str, str]] = Field(default_factory=list)


def classify_prompt_anchor_values(
    values: Any,
    *,
    forbidden_values: Any = None,
    limit: int = 64,
) -> PromptAnchorClassification:
    flat_values = _flatten_values(values)
    explicit_forbidden_values = _flatten_values(forbidden_values)
    joined_text = "\n".join(flat_values)
    forbidden = _unique_strings(
        [
            anchor
            for scope in _negative_scopes(joined_text)
            for anchor in anchor_terms_from_value(scope, include_meta=False)
        ]
        + [
            anchor
            for value in explicit_forbidden_values
            for anchor in anchor_terms_from_value(value, include_meta=False)
        ]
    )
    forbidden_keys = {_anchor_key(anchor) for anchor in forbidden}

    positive: list[str] = []
    meta: list[str] = []
    notes: list[dict[str, str]] = []
    for value in flat_values:
        local_negative_scopes = _negative_scopes(value)
        local_forbidden_keys = {
            _anchor_key(anchor)
            for scope in local_negative_scopes
            for anchor in anchor_terms_from_value(scope, include_meta=False)
        }
        for anchor in anchor_terms_from_value(value, include_meta=True):
            key = _anchor_key(anchor)
            if not key:
                continue
            if key in forbidden_keys or key in local_forbidden_keys or _is_negated_in_text(value, anchor):
                if anchor not in forbidden and _is_story_anchor_prompt_term(anchor):
                    forbidden.append(anchor)
                    forbidden_keys.add(key)
                notes.append({"term": anchor, "classification": "forbidden_or_excluded"})
                continue
            if _is_meta_control_term(anchor):
                meta.append(anchor)
                notes.append({"term": anchor, "classification": "meta_control"})
                continue
            if _is_story_anchor_prompt_term(anchor):
                positive.append(anchor)
                notes.append({"term": anchor, "classification": "positive_required"})

    forbidden = _unique_strings(forbidden)
    meta = _unique_strings(meta)
    positive = [
        anchor
        for anchor in _unique_strings(positive)
        if _anchor_key(anchor) not in {_anchor_key(item) for item in forbidden}
    ][:limit]
    excluded = _unique_strings([*forbidden, *meta])
    return PromptAnchorClassification(
        positive_required_anchors=positive,
        forbidden_anchors=forbidden,
        meta_control_terms=meta,
        excluded_terms=excluded,
        source_notes=notes[: max(limit * 2, 24)],
    )


def classify_project_story_premise(premise: Any, *, limit: int = 64) -> PromptAnchorClassification:
    if premise is None:
        return PromptAnchorClassification()
    contract = _get_value(premise, "prompt_fidelity_contract") or {}
    values = [
        _get_value(premise, "user_story_premise"),
        _get_value(premise, "safe_user_story_summary"),
        _get_value(premise, "core_terms"),
        _get_value(premise, "setting_terms"),
        _get_value(premise, "conflict_terms"),
        _get_value(premise, "role_terms"),
        _get_value(premise, "required_story_elements"),
        _get_value(premise, "prompt_markers_detected"),
        _get_value(contract, "required_markers"),
    ]
    classification = classify_prompt_anchor_values(
        values,
        forbidden_values=_get_value(contract, "forbidden_markers"),
        limit=limit,
    )
    explicit_forbidden = _flatten_values(_get_value(contract, "forbidden_markers"))
    if explicit_forbidden:
        merged_forbidden = _unique_strings(
            [
                *classification.forbidden_anchors,
                *[
                    anchor
                    for value in explicit_forbidden
                    for anchor in anchor_terms_from_value(value, include_meta=False)
                ],
            ]
        )
        forbidden_keys = {_anchor_key(item) for item in merged_forbidden}
        return classification.copy(
            update={
                "positive_required_anchors": [
                    item
                    for item in classification.positive_required_anchors
                    if _anchor_key(item) not in forbidden_keys
                ],
                "forbidden_anchors": merged_forbidden,
                "excluded_terms": _unique_strings([*merged_forbidden, *classification.meta_control_terms]),
            }
        )
    return classification


def extract_positive_prompt_terms(text: str, *, limit: int = 32) -> list[str]:
    return classify_prompt_anchor_values([text], limit=limit).positive_required_anchors[:limit]


def anchor_terms_from_value(value: str, *, include_meta: bool = True) -> list[str]:
    source = " ".join(str(value or "").split()).strip()
    if not source:
        return []
    anchors: list[str] = []
    anchors.extend(PROMPT_MACHINE_MARKER_RE.findall(source))
    anchors.extend(NAME_CUE_RE.findall(source))
    if _is_atomic_anchor(source, include_meta=include_meta):
        anchors.append(source)
    for chunk in CJK_TEXT_RE.findall(source):
        anchors.extend(_split_cjk_anchor(chunk))
    for term in ASCII_TEXT_RE.findall(source):
        if _is_story_anchor_prompt_term(term) or (include_meta and _is_meta_control_term(term)):
            anchors.append(term)
    return _unique_strings([anchor for anchor in anchors if is_prompt_anchor_candidate(anchor, include_meta=include_meta)])


def is_prompt_anchor_candidate(value: str, *, include_meta: bool = False) -> bool:
    clean = " ".join(str(value or "").split()).strip()
    if len(clean) < 2:
        return False
    if PROMPT_MACHINE_MARKER_RE.fullmatch(clean):
        return True
    if include_meta and _is_meta_control_term(clean):
        return True
    return _is_story_anchor_prompt_term(clean)


def _flatten_values(values: Any) -> list[str]:
    if values is None:
        return []
    if hasattr(values, "model_dump"):
        values = values.model_dump(mode="json")
    elif isinstance(values, BaseModel):
        values = values.dict()
    if isinstance(values, dict):
        result: list[str] = []
        for key, value in values.items():
            key_text = str(key or "")
            if key_text in {
                "forbidden_demo_defaults",
                "demo_default_count",
                "marker_counts",
                "required_terms_present",
                "source_refs",
                "created_at",
                "updated_at",
                "version_id",
            }:
                continue
            result.extend(_flatten_values(value))
        return result
    if isinstance(values, (list, tuple, set)):
        result: list[str] = []
        for item in values:
            result.extend(_flatten_values(item))
        return result
    text = " ".join(str(values or "").split()).strip()
    return [text] if text else []


def _negative_scopes(text: str) -> list[str]:
    raw_text = str(text or "")
    return [
        raw_text[start:end].strip()
        for start, end in _negative_spans(raw_text)
        if raw_text[start:end].strip()
    ]


def _legacy_negative_scopes(text: str) -> list[str]:
    result: list[str] = []
    for segment in re.split(r"[\n\r.;!?。！？；]+", str(text or "")):
        lowered = segment.casefold()
        best_index = -1
        best_marker = ""
        for marker in NEGATIVE_MARKERS:
            index = lowered.find(marker.casefold())
            if index >= 0 and (best_index < 0 or index < best_index):
                best_index = index
                best_marker = marker
        if best_index < 0:
            continue
        scope = segment[best_index + len(best_marker):]
        scope = _truncate_at_positive_lead_boundary(scope)
        scope = re.split(
            r"(?:\bbut\b|\bhowever\b|\bexcept\b|\binstead\b|\u4f46|\u4f46\u662f|\u800c\u662f|\u4e0d\u8fc7)",
            scope,
            maxsplit=1,
        )[0]
        if scope.strip():
            result.append(scope.strip())
    return result


def _negative_spans(text: str) -> list[tuple[int, int]]:
    raw_text = str(text or "")
    lowered = raw_text.casefold()
    spans: list[tuple[int, int]] = []
    for marker in NEGATIVE_MARKERS:
        marker_lower = marker.casefold()
        search_start = 0
        while True:
            marker_index = lowered.find(marker_lower, search_start)
            if marker_index < 0:
                break
            scope_start = marker_index + len(marker)
            scope_end = _negative_scope_end(raw_text, scope_start)
            if scope_end > scope_start:
                spans.append((scope_start, scope_end))
            search_start = marker_index + max(1, len(marker))
    return _merge_spans(sorted(spans))


def _negative_scope_end(text: str, scope_start: int) -> int:
    scope = text[scope_start:]
    end = len(text)
    for match in (
        SENTENCE_BOUNDARY_RE.search(scope),
        POSITIVE_LEAD_BOUNDARY_RE.search(scope),
        TRANSITION_BOUNDARY_RE.search(scope),
    ):
        if match:
            end = min(end, scope_start + match.start())
    return end


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _truncate_at_positive_lead_boundary(text: str) -> str:
    match = POSITIVE_LEAD_BOUNDARY_RE.search(str(text or ""))
    if match:
        return text[: match.start()]
    return text


def _split_cjk_anchor(value: str) -> list[str]:
    result: list[str] = []
    for part in CJK_SPLITTER.split(str(value or "")):
        for clean in re.split(r"[\s\u3000,.;:!?\uff0c\u3002\uff1b\uff1a\uff01\uff1f\u3001\u300a\u300b\"'()]+", part):
            clean = clean.strip()
            if not clean:
                continue
            if len(clean) > 12:
                continue
            result.append(clean)
    return result


def _is_atomic_anchor(value: str, *, include_meta: bool) -> bool:
    clean = " ".join(str(value or "").split()).strip()
    if PROMPT_MACHINE_MARKER_RE.fullmatch(clean):
        return True
    if include_meta and _is_meta_control_term(clean):
        return True
    if not _is_story_anchor_prompt_term(clean):
        return False
    if CJK_SPLITTER.search(clean):
        return False
    if NAME_CUE_RE.search(clean):
        return False
    if re.search(r"[\s,.;:!?\uff0c\u3002\uff1b\uff1a\uff01\uff1f\u3001]", clean):
        return False
    return True


def _is_story_anchor_prompt_term(value: str) -> bool:
    clean = " ".join(str(value or "").split()).strip()
    if not clean:
        return False
    lowered = clean.casefold()
    if lowered in GENERIC_ASCII_TERMS or clean in GENERIC_CJK_TERMS:
        return False
    if clean.startswith("-") or lowered.startswith(("do not ", "don't ", "avoid ", "exclude ")):
        return False
    if any(marker.casefold() in lowered for marker in NEGATIVE_MARKERS):
        return False
    if _is_meta_control_term(clean):
        return False
    if len(clean) > 24 and not PROMPT_MACHINE_MARKER_RE.fullmatch(clean):
        return False
    return True


def _is_meta_control_term(value: str) -> bool:
    clean = " ".join(str(value or "").split()).strip()
    if not clean:
        return False
    lowered = clean.casefold()
    if lowered in GENERIC_ASCII_TERMS or clean in GENERIC_CJK_TERMS:
        return True
    return any(marker.casefold() in lowered for marker in META_CONTROL_SUBSTRINGS)


def _is_negated_in_text(text: str, anchor: str) -> bool:
    raw_text = str(text or "")
    raw_anchor = str(anchor or "").strip()
    if not raw_text or not raw_anchor:
        return False
    lower_text = raw_text.casefold()
    lower_anchor = raw_anchor.casefold()
    negative_spans = _negative_spans(raw_text)
    start = 0
    while True:
        index = lower_text.find(lower_anchor, start)
        if index < 0:
            return False
        anchor_end = index + len(lower_anchor)
        if any(index >= span_start and anchor_end <= span_end for span_start, span_end in negative_spans):
            return True
        start = index + max(1, len(lower_anchor))


def _legacy_clause_prefix_for_audit(text_before_anchor: str) -> str:
    boundary_matches = list(
        re.finditer(
            r"[\n\r.;!?。；！？]|(?:\bbut\b|\bhowever\b|\bexcept\b|\binstead\b|但|但是|而是|不过)",
            text_before_anchor,
            flags=re.IGNORECASE,
        )
    )
    if boundary_matches:
        text_before_anchor = text_before_anchor[boundary_matches[-1].end():]
    positive_lead_matches = list(POSITIVE_LEAD_BOUNDARY_RE.finditer(text_before_anchor))
    if positive_lead_matches:
        text_before_anchor = text_before_anchor[positive_lead_matches[-1].end():]
    return text_before_anchor


def _anchor_key(value: str) -> str:
    return re.sub(
        r"[\s\u3000,.;:!?\uff0c\u3002\uff1b\uff1a\uff01\uff1f\u3001\"'`()\[\]{}<>\u300a\u300b\-_\/]+",
        "",
        str(value or "").casefold(),
    )


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            continue
        key = _anchor_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
