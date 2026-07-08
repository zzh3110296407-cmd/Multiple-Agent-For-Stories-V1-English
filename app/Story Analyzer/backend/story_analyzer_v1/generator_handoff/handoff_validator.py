from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import json
import os
import re
import urllib.error
import urllib.request

from ..evidence.claim_extraction import extract_claims_from_value
from ..evidence.evidence_retrieval import retrieve_evidence_for_claim
from ..evidence.raw_source_index_builder import raw_source_index_path
from ..handoff.package_store import now_iso, write_json


SemanticValidator = Callable[[dict[str, Any]], dict[str, Any]]


VALIDATION_SCHEMA_VERSION = "generator_handoff.validation_report.v1"
SEMANTIC_VALIDATION_ADAPTER_ID = "source_fidelity_semantic_adapter.v1"
HANDOFF_VERSION = "generator_handoff.v1"
HANDOFF_DIRNAME = "generator_handoff"
REPAIR_REQUIRED_WARNING_CODES = {"EVIDENCE_INSUFFICIENT", "SEMANTIC_VALIDATION_INSUFFICIENT"}
NON_DELIVERABLE_WARNING_CODES = {
    "SOURCE_EVIDENCE_INSUFFICIENT",
    "FORESHADOWING_STATE_EVIDENCE_INSUFFICIENT",
}
REQUIRED_TOP_LEVEL_FIELDS = {
    "handoff_version",
    "handoff_status",
    "quality_gate",
    "source_map",
    "book_framework",
    "arc_hierarchy",
    "chapter_blueprints",
    "foreshadowing_registry",
    "generator_materials",
    "selection_metadata",
}
REQUIRED_MATERIAL_FIELDS = {
    "material_id",
    "module_type",
    "abstraction_level",
    "source_dependence",
    "granularity",
    "content",
    "selection_tags",
    "source_refs",
}
VALID_MODULE_TYPES = {
    "pacing_structure",
    "arc_structure",
    "chapter_progression",
    "character_growth",
    "relationship_dynamics",
    "worldbuilding",
    "core_conflict",
    "foreshadowing_system",
    "emotion_curve",
    "information_release",
    "scene_function",
    "narrative_mechanism",
    "adaptable_setting",
    "source_fidelity",
}
VALID_ABSTRACTION_LEVELS = {"abstract", "semi_abstract", "source_specific"}
VALID_SOURCE_DEPENDENCE = {"source_free", "adaptable", "source_bound"}
VALID_FORESHADOWING_STATUS = {"planted", "partially_resolved", "resolved"}
INTERNAL_MARKERS = ("[NEW_TERM]", "source_model_id", "llm_call_id")
MECHANISM_TERMS = {
    "mechanism",
    "structure",
    "rhythm",
    "pacing",
    "pressure",
    "conflict",
    "turning",
    "choice",
    "arc",
    "chapter",
    "progression",
    "pattern",
}
SOURCE_FIDELITY_STOPWORDS = {
    "content",
    "description",
    "fact",
    "framework",
    "material",
    "module",
    "source",
    "story",
    "summary",
    "the",
    "and",
    "with",
    "from",
    "into",
    "while",
    "through",
    "this",
    "that",
}
GENERIC_PROPER_TERMS = {
    "Hero",
    "Protagonist",
    "Mentor",
    "Mission",
    "Chapter",
    "Arc",
}
SOURCE_FIDELITY_CLAIM_TERMS = {
    "become",
    "becomes",
    "became",
    "becoming",
    "betrays",
    "controls",
    "daughter",
    "defeats",
    "dies",
    "enemy",
    "father",
    "kills",
    "king",
    "leader",
    "lover",
    "mother",
    "murders",
    "owns",
    "parent",
    "queen",
    "reveals",
    "ruler",
    "sister",
    "son",
    "transforms",
}
SOURCE_FIDELITY_CJK_CLAIM_TERMS = {
    "成为",
    "变成",
    "杀死",
    "杀害",
    "击败",
    "打败",
    "背叛",
    "控制",
    "统治",
    "确认",
    "证实",
    "证明",
    "揭示",
    "揭露",
    "暴露",
    "发现",
    "拥有",
    "持有",
    "属于",
    "来自",
    "进入",
    "逃离",
    "苏醒",
    "觉醒",
    "死亡",
    "死去",
    "复活",
    "牺牲",
    "契约",
    "父亲",
    "母亲",
    "儿子",
    "女儿",
    "兄弟",
    "姐妹",
    "恋人",
    "仇人",
    "敌人",
    "身份",
    "真相",
    "代价",
    "血统",
    "规则",
    "计划",
}


class HttpSemanticValidator:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key_env: str = "",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not endpoint.strip():
            raise ValueError("semantic validator endpoint is required")
        self.endpoint = endpoint
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "contract_version": "generator_handoff.semantic_source_fidelity_request.v1",
            **request,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key_env:
            api_key = os.environ.get(self.api_key_env)
            if not api_key:
                raise ValueError(f"missing semantic validator API key env: {self.api_key_env}")
            headers["Authorization"] = f"Bearer {api_key}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_obj = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request_obj, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise ValueError(f"semantic validator request failed: {exc}") from exc
        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"semantic validator returned invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("semantic validator response must be an object")
        return data


def build_http_semantic_validator(
    endpoint: str,
    *,
    api_key_env: str = "",
    timeout_seconds: float = 60.0,
) -> SemanticValidator:
    return HttpSemanticValidator(
        endpoint=endpoint,
        api_key_env=api_key_env,
        timeout_seconds=timeout_seconds,
    )


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}, "file is missing"
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    except (OSError, UnicodeDecodeError) as exc:
        return {}, f"could not read JSON: {exc}"
    if not isinstance(payload, dict):
        return {}, "JSON root must be an object"
    return payload, None


def _handoff_dir(path: str | Path) -> Path:
    root = Path(path)
    if root.name == HANDOFF_DIRNAME:
        return root
    return root / HANDOFF_DIRNAME


def _output_dir(path: str | Path) -> Path:
    root = Path(path)
    if root.name == HANDOFF_DIRNAME:
        return root.parent
    return root


def _clip(value: Any, limit: int = 360) -> str:
    text = _content_text(value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key, child in value.items():
            parts.append(str(key))
            parts.append(_content_text(child))
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        return " ".join(_content_text(item) for item in value)
    return str(value)


def _content_value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_content_value_text(child) for child in value.values())
    if isinstance(value, list):
        return " ".join(_content_value_text(item) for item in value)
    return str(value)


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_range(value: Any) -> set[int]:
    text = str(value or "").strip()
    if not text:
        return set()
    if "-" in text:
        start_text, _, end_text = text.partition("-")
        start = _as_int(start_text)
        end = _as_int(end_text, start)
    else:
        start = _as_int(text)
        end = start
    if not start:
        return set()
    if end < start:
        start, end = end, start
    return set(range(start, end + 1))


def _source_ref_from_unit(index: int) -> str:
    return f"REF_CH_{index:03d}"


def _issue(
    *,
    code: str,
    severity: str,
    category: str,
    target_path: str,
    message: str,
    source_refs: list[str] | None = None,
    near_source_evidence: list[dict[str, Any]] | None = None,
    evidence_packets: list[dict[str, Any]] | None = None,
    current_value: Any = None,
    expected_constraint: str = "",
    repair_hint: str = "",
    repairable: bool | None = None,
) -> dict[str, Any]:
    issue = {
        "code": code,
        "severity": severity,
        "category": category,
        "target_path": target_path,
        "message": message,
        "source_refs": source_refs or [],
        "near_source_evidence": near_source_evidence or [],
        "evidence_packets": evidence_packets or [],
        "current_value": current_value,
        "expected_constraint": expected_constraint,
        "repair_hint": repair_hint,
    }
    if repairable is not None:
        issue["repairable"] = repairable
    return issue


def _assign_issue_ids(issues: list[dict[str, Any]]) -> None:
    for index, issue in enumerate(issues, start=1):
        issue["issue_id"] = f"VAL{index:03d}"


def repair_required_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in report.get("issues", [])
        if issue.get("severity") == "blocking" or issue.get("code") in REPAIR_REQUIRED_WARNING_CODES
    ]


def non_deliverable_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in report.get("issues", [])
        if issue.get("severity") == "blocking"
        or issue.get("code") in REPAIR_REQUIRED_WARNING_CODES
        or issue.get("code") in NON_DELIVERABLE_WARNING_CODES
    ]


def is_generator_handoff_deliverable(report: dict[str, Any]) -> bool:
    if report.get("validation_status") == "passed":
        return True
    if report.get("validation_status") != "passed_with_warnings":
        return False
    return not non_deliverable_issues(report)


def _source_references(source_index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = source_index.get("references")
    return refs if isinstance(refs, dict) else {}


def _evidence_for_refs(source_refs: list[str], source_references: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for ref_id in source_refs:
        ref = _dict_value(source_references.get(ref_id))
        spans = _list_value(ref.get("evidence_spans"))
        for span in spans:
            if not isinstance(span, dict):
                continue
            text = span.get("evidence_text") or span.get("text") or span.get("near_source_summary") or ""
            if text:
                evidence.append(
                    {
                        "ref_id": ref_id,
                        "evidence_text": _clip(text),
                        "evidence_type": span.get("evidence_type", "source_evidence"),
                    }
                )
        summary = ref.get("near_source_summary")
        if summary and not any(item["ref_id"] == ref_id for item in evidence):
            evidence.append(
                {
                    "ref_id": ref_id,
                    "evidence_text": _clip(summary),
                    "evidence_type": "near_source_summary",
                }
            )
    return evidence


def _raw_scope_for_refs(source_refs: list[str], source_references: dict[str, dict[str, Any]]) -> dict[str, Any]:
    segment_ids: list[str] = []
    source_ranges: list[str] = []
    analysis_ranges: list[str] = []
    for ref_id in source_refs:
        ref = _dict_value(source_references.get(ref_id))
        raw_scope = _dict_value(ref.get("raw_source_scope"))
        for segment_id in _list_value(raw_scope.get("segment_ids")):
            if segment_id and segment_id not in segment_ids:
                segment_ids.append(str(segment_id))
        if raw_scope.get("source_chapter_range"):
            source_ranges.append(str(raw_scope["source_chapter_range"]))
        if raw_scope.get("analysis_unit_range"):
            analysis_ranges.append(str(raw_scope["analysis_unit_range"]))
    scope: dict[str, Any] = {}
    if segment_ids:
        scope["segment_ids"] = segment_ids
    if source_ranges:
        scope["source_chapter_range"] = ",".join(source_ranges)
    if analysis_ranges:
        scope["analysis_unit_range"] = ",".join(analysis_ranges)
    return scope


def _near_source_evidence_from_packets(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for packet in packets:
        for item in packet.get("evidence_items") or []:
            quote = item.get("quote")
            if not quote:
                continue
            evidence.append(
                {
                    "ref_id": item.get("segment_id", ""),
                    "evidence_text": quote,
                    "evidence_type": "raw_source_segment",
                }
            )
    return evidence


def _v2_evidence_enabled(run_dir: str | Path, evidence_mode: str) -> bool:
    mode = (evidence_mode or "auto").lower()
    if mode == "v1":
        return False
    return raw_source_index_path(_output_dir(run_dir)).exists()


def _v2_source_bound_issue(
    *,
    run_dir: str | Path,
    material: dict[str, Any],
    target: str,
    source_refs: list[str],
    source_references: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    raw_scope = _raw_scope_for_refs(source_refs, source_references)
    if not raw_scope:
        return None
    packets: list[dict[str, Any]] = []
    insufficient_claims: list[str] = []
    contradicted_claims: list[str] = []
    ambiguous_claims: list[str] = []
    for claim in extract_claims_from_value(material.get("content"), target_path=f"{target}.content", max_claims=8):
        packet = retrieve_evidence_for_claim(_output_dir(run_dir), claim, retrieval_scope=raw_scope, top_k=5)
        packets.append(packet)
        status = str(packet.get("support_status") or "")
        if status == "contradicted":
            contradicted_claims.append(str(claim.get("claim_text", "")))
        elif status == "ambiguous":
            ambiguous_claims.append(str(claim.get("claim_text", "")))
        elif status != "supported":
            insufficient_claims.append(str(claim.get("claim_text", "")))
    if contradicted_claims:
        return _issue(
            code="SOURCE_BOUND_EVIDENCE_MISMATCH",
            severity="blocking",
            category="source_fidelity",
            target_path=f"{target}.content",
            message="source_bound material contains claims contradicted by raw source evidence",
            source_refs=source_refs,
            near_source_evidence=_near_source_evidence_from_packets(packets),
            evidence_packets=packets,
            current_value={
                "contradicted_claims": contradicted_claims,
                "content": material.get("content"),
            },
            expected_constraint="source_bound materials must not introduce facts contradicted by raw source evidence.",
            repair_hint="Rewrite this material using only the supplied evidence_packets.",
            repairable=True,
        )
    if insufficient_claims or ambiguous_claims:
        return _issue(
            code="SOURCE_EVIDENCE_INSUFFICIENT",
            severity="warning",
            category="source_fidelity",
            target_path=f"{target}.content",
            message="source_bound material has claims that could not be fully grounded in raw source evidence",
            source_refs=source_refs,
            near_source_evidence=_near_source_evidence_from_packets(packets),
            evidence_packets=packets,
            current_value={
                "insufficient_claims": insufficient_claims,
                "ambiguous_claims": ambiguous_claims,
                "content": material.get("content"),
            },
            expected_constraint="source_bound materials need raw source evidence before automated repair or generator import.",
            repair_hint="Review source_refs or enrich evidence; do not rewrite automatically from insufficient evidence.",
            repairable=False,
        )
    if not packets:
        return None
    return None


def _v2_foreshadowing_evidence_issue(
    *,
    run_dir: str | Path,
    item: dict[str, Any],
    target: str,
    source_refs: list[str],
    source_references: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    raw_scope = _raw_scope_for_refs(source_refs, source_references)
    if not raw_scope:
        return None
    packets: list[dict[str, Any]] = []
    insufficient_claims: list[str] = []
    claim_source = {
        "canonical_content": item.get("canonical_content") or item.get("summary") or item.get("text") or "",
    }
    for claim in extract_claims_from_value(claim_source, target_path=target, max_claims=4):
        packet = retrieve_evidence_for_claim(_output_dir(run_dir), claim, retrieval_scope=raw_scope, top_k=5)
        packets.append(packet)
        if packet.get("support_status") != "supported":
            insufficient_claims.append(str(claim.get("claim_text", "")))
    if not insufficient_claims:
        return None
    return _issue(
        code="FORESHADOWING_STATE_EVIDENCE_INSUFFICIENT",
        severity="warning",
        category="foreshadowing_registry",
        target_path=target,
        message="foreshadowing item state/content could not be fully grounded in raw source evidence",
        source_refs=source_refs,
        near_source_evidence=_near_source_evidence_from_packets(packets),
        evidence_packets=packets,
        current_value={
            "id": item.get("id", ""),
            "status": item.get("status", ""),
            "insufficient_claims": insufficient_claims,
        },
        expected_constraint="Foreshadowing state must be backed by raw source evidence before automated status repair.",
        repair_hint="Review planted/resolution source_refs or rerun analyzer; do not invent a status change.",
        repairable=False,
    )


def _collect_source_terms(value: Any) -> set[str]:
    terms: set[str] = set()

    def visit(node: Any, key: str = "") -> None:
        normalized_key = key.lower()
        if isinstance(node, dict):
            if normalized_key in {"source_entity_inventory", "entity_inventory"}:
                for child in node.values():
                    visit(child, "source_terms")
            for child_key, child_value in node.items():
                visit(child_value, str(child_key))
            return
        if isinstance(node, list):
            if normalized_key in {"source_terms", "proper_nouns", "source_entities", "world_terms"}:
                for item in node:
                    if isinstance(item, str) and item.strip():
                        terms.add(item.strip())
                    elif isinstance(item, dict):
                        for candidate_key in ("source_term", "term", "name", "canonical_name"):
                            candidate = item.get(candidate_key)
                            if isinstance(candidate, str) and candidate.strip():
                                terms.add(candidate.strip())
            for item in node:
                visit(item, key)
            return
        if isinstance(node, str) and normalized_key in {"source_term", "original_term", "canonical_name"} and node.strip():
            terms.add(node.strip())

    visit(value)
    return {term for term in terms if len(term) >= 2}


def _text_contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    return term.lower() in text.lower()


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9_]{4,}", lowered))
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    for chunk in cjk:
        if len(chunk) == 1:
            continue
        if len(chunk) == 2:
            tokens.add(chunk)
        else:
            tokens.update(chunk[index : index + 2] for index in range(0, len(chunk) - 1))
    return tokens


def _significant_tokens(text: str) -> set[str]:
    return {token for token in _tokenize(text) if token not in SOURCE_FIDELITY_STOPWORDS}


def _proper_like_terms(text: str) -> set[str]:
    terms = set(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", text))
    return {
        term
        for term in terms
        if term not in GENERIC_PROPER_TERMS
        and not re.fullmatch(r"F\d{3,}", term)
        and not re.fullmatch(r"REF_CH_\d{3,}", term)
        and not re.fullmatch(r"REF_ARC_\d{3,}", term)
        and not re.fullmatch(r"SOURCE_TERM_\d{2,}", term)
    }


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _source_terms_in_text(text: str, source_terms: set[str]) -> set[str]:
    return {
        term
        for term in source_terms
        if len(term.strip()) >= 2 and _text_contains_term(text, term)
    }


def _unsupported_cjk_claim_terms(content_text: str, evidence_text: str) -> list[str]:
    return sorted(
        term
        for term in SOURCE_FIDELITY_CJK_CLAIM_TERMS
        if term in content_text and term not in evidence_text
    )


def _source_fidelity_mismatch_reason(
    content: Any,
    evidence: list[dict[str, Any]],
    source_terms: set[str] | None = None,
) -> str:
    content_text = _content_value_text(content)
    evidence_text = " ".join(item.get("evidence_text", "") for item in evidence)
    content_tokens = _significant_tokens(content_text)
    evidence_tokens = _significant_tokens(evidence_text)
    if not content_tokens or not evidence_tokens:
        return ""
    supported_tokens = content_tokens.intersection(evidence_tokens)
    unsupported_tokens = content_tokens - evidence_tokens
    support_ratio = len(supported_tokens) / max(1, len(content_tokens))
    unsupported_names = sorted(
        term for term in _proper_like_terms(content_text) if term.lower() not in evidence_text.lower()
    )
    unsupported_claim_terms = sorted(unsupported_tokens.intersection(SOURCE_FIDELITY_CLAIM_TERMS))
    unsupported_cjk_claim_terms = _unsupported_cjk_claim_terms(content_text, evidence_text)
    cjk_content_tokens = {token for token in content_tokens if _has_cjk(token)}
    cjk_supported_tokens = cjk_content_tokens.intersection(evidence_tokens)
    cjk_support_ratio = len(cjk_supported_tokens) / max(1, len(cjk_content_tokens))
    known_source_terms = source_terms or set()
    unsupported_source_terms = sorted(
        _source_terms_in_text(content_text, known_source_terms)
        - _source_terms_in_text(evidence_text, known_source_terms),
        key=len,
        reverse=True,
    )
    if unsupported_source_terms and (
        unsupported_claim_terms
        or unsupported_cjk_claim_terms
        or support_ratio < 0.75
    ):
        return (
            "unsupported source-specific terms or conclusions: "
            f"terms={unsupported_source_terms}, claim_terms={unsupported_claim_terms + unsupported_cjk_claim_terms}, "
            f"support_ratio={support_ratio:.2f}, cjk_support_ratio={cjk_support_ratio:.2f}"
        )
    if unsupported_names and (unsupported_claim_terms or support_ratio < 0.65):
        return (
            "unsupported named terms or source-specific conclusions: "
            f"terms={unsupported_names}, claim_terms={unsupported_claim_terms}, support_ratio={support_ratio:.2f}"
        )
    if unsupported_cjk_claim_terms and cjk_support_ratio < 0.7:
        return (
            "unsupported Chinese relation/state claim terms: "
            f"{unsupported_cjk_claim_terms}, support_ratio={support_ratio:.2f}, cjk_support_ratio={cjk_support_ratio:.2f}"
        )
    if _has_cjk(content_text) and len(cjk_content_tokens) >= 4 and cjk_support_ratio < 0.35:
        return (
            "low Chinese evidence overlap for source_bound material: "
            f"support_ratio={support_ratio:.2f}, cjk_support_ratio={cjk_support_ratio:.2f}"
        )
    if unsupported_claim_terms and support_ratio < 0.5:
        return f"unsupported relation/state claim terms: {unsupported_claim_terms}, support_ratio={support_ratio:.2f}"
    return ""


def _is_empty_content(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def _check_schema(handoff: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    if handoff.get("handoff_version") != HANDOFF_VERSION:
        issues.append(
            _issue(
                code="INVALID_HANDOFF_VERSION",
                severity="blocking",
                category="schema",
                target_path="handoff_version",
                message="handoff_version must be generator_handoff.v1",
                current_value=handoff.get("handoff_version"),
                expected_constraint=HANDOFF_VERSION,
                repair_hint="Regenerate the unified generator handoff with the current compiler.",
            )
        )
    for field in sorted(REQUIRED_TOP_LEVEL_FIELDS - set(handoff)):
        issues.append(
            _issue(
                code="MISSING_TOP_LEVEL_FIELD",
                severity="blocking",
                category="schema",
                target_path=field,
                message=f"required top-level field is missing: {field}",
                expected_constraint="All required generator handoff top-level fields must exist.",
                repair_hint="Recompile the generator handoff after all analyzer outputs are present.",
            )
        )
    if not isinstance(handoff.get("generator_materials"), list):
        issues.append(
            _issue(
                code="INVALID_GENERATOR_MATERIALS",
                severity="blocking",
                category="schema",
                target_path="generator_materials",
                message="generator_materials must be a list",
                current_value=type(handoff.get("generator_materials")).__name__,
                expected_constraint="generator_materials must be an array.",
                repair_hint="Recompile generator_materials from validated analyzer modules.",
            )
        )


def _check_source_map(handoff: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    source_map = _dict_value(handoff.get("source_map"))
    source_chapters = _list_value(source_map.get("source_chapters"))
    source_total = _as_int(source_map.get("source_total_chapters"))
    if source_total and source_total != len(source_chapters):
        issues.append(
            _issue(
                code="SOURCE_TOTAL_CHAPTERS_MISMATCH",
                severity="blocking",
                category="source_map",
                target_path="source_map.source_total_chapters",
                message="source_total_chapters does not match source_chapters length",
                current_value={"source_total_chapters": source_total, "source_chapters_length": len(source_chapters)},
                expected_constraint="Source chapter count must use source-chapter basis, not internal analysis-unit count.",
                repair_hint="Rebuild source_map from run_manifest source chapters.",
            )
        )
    units_from_map: set[int] = set()
    source_chapter_indexes: set[int] = set()
    for chapter in source_chapters:
        if not isinstance(chapter, dict):
            continue
        source_chapter_indexes.add(_as_int(chapter.get("source_chapter_index")))
        for part in _list_value(chapter.get("parts")):
            if isinstance(part, dict):
                unit = _as_int(part.get("analysis_unit_index"))
                if unit:
                    units_from_map.add(unit)
        units_from_map.update(_parse_range(chapter.get("analysis_unit_range")))
    analysis_unit_count = _as_int(source_map.get("analysis_unit_count"))
    expected_units = set(range(1, analysis_unit_count + 1)) if analysis_unit_count else set()
    if expected_units and units_from_map != expected_units:
        issues.append(
            _issue(
                code="SOURCE_MAP_ANALYSIS_UNIT_COVERAGE",
                severity="blocking",
                category="source_map",
                target_path="source_map.source_chapters",
                message="source_map does not cover all analysis units exactly",
                current_value={"covered_units": sorted(units_from_map), "expected_units": sorted(expected_units)},
                expected_constraint="All internal analysis units must map back to source chapters.",
                repair_hint="Rebuild source_map and preserve original chapter-to-part mapping.",
            )
        )
    blueprint_units = {
        _as_int(item.get("analysis_unit_index"))
        for item in _list_value(handoff.get("chapter_blueprints"))
        if isinstance(item, dict) and _as_int(item.get("analysis_unit_index"))
    }
    if expected_units and blueprint_units != expected_units:
        issues.append(
            _issue(
                code="CHAPTER_BLUEPRINT_ANALYSIS_UNIT_COVERAGE",
                severity="blocking",
                category="coverage",
                target_path="chapter_blueprints",
                message="chapter_blueprints do not cover every analysis unit",
                current_value={"covered_units": sorted(blueprint_units), "expected_units": sorted(expected_units)},
                expected_constraint="Each analysis unit must have one chapter blueprint.",
                repair_hint="Regenerate missing chapter blueprints from chapter analysis evidence.",
            )
        )
    blueprint_source_chapters = {
        _as_int(item.get("source_chapter_index"))
        for item in _list_value(handoff.get("chapter_blueprints"))
        if isinstance(item, dict) and _as_int(item.get("source_chapter_index"))
    }
    source_chapter_indexes.discard(0)
    if source_chapter_indexes and not source_chapter_indexes.issubset(blueprint_source_chapters):
        issues.append(
            _issue(
                code="SOURCE_CHAPTER_BLUEPRINT_COVERAGE",
                severity="blocking",
                category="coverage",
                target_path="chapter_blueprints",
                message="some source chapters have no chapter blueprint coverage",
                current_value={"missing_source_chapters": sorted(source_chapter_indexes - blueprint_source_chapters)},
                expected_constraint="All source chapters must be represented through chapter blueprints.",
                repair_hint="Regenerate chapter blueprints for the missing source chapters.",
            )
        )
    for index, arc_range in enumerate(_list_value(source_map.get("arc_source_ranges") or source_map.get("arc_ranges")), start=1):
        if not isinstance(arc_range, dict):
            continue
        if not arc_range.get("source_chapter_range") or not arc_range.get("analysis_unit_range"):
            issues.append(
                _issue(
                    code="ARC_SOURCE_RANGE_MISSING",
                    severity="blocking",
                    category="source_map",
                    target_path=f"source_map.arc_source_ranges[{index - 1}]",
                    message="arc source range must include source_chapter_range and analysis_unit_range",
                    current_value=arc_range,
                    expected_constraint="Every arc must preserve both source chapter and analysis unit ranges.",
                    repair_hint="Rebuild arc source ranges from run_manifest arc_ranges.",
                )
            )


def _check_quality_gate(handoff: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    gate = _dict_value(handoff.get("quality_gate"))
    checks = [
        ("run_status", gate.get("run_status") == "completed", "run_status must be completed"),
        ("missing_required_outputs", not gate.get("missing_required_outputs"), "missing_required_outputs must be empty"),
        (
            "llm_unrecovered_failed_target_count",
            _as_int(gate.get("llm_unrecovered_failed_target_count")) == 0,
            "llm_unrecovered_failed_target_count must be 0",
        ),
        (
            "failed_chapter_count",
            _as_int(gate.get("failed_chapter_count")) == 0,
            "failed_chapter_count must be 0",
        ),
        ("source_leak_status", gate.get("source_leak_status") == "passed", "source_leak_status must be passed"),
        (
            "abstraction_quality_status",
            gate.get("abstraction_quality_status") == "passed",
            "abstraction_quality_status must be passed",
        ),
    ]
    for field, passed, message in checks:
        if not passed:
            issues.append(
                _issue(
                    code="QUALITY_GATE_FAILED",
                    severity="blocking",
                    category="quality_gate",
                    target_path=f"quality_gate.{field}",
                    message=message,
                    current_value=gate.get(field),
                    expected_constraint="Generator handoff can only be consumed after analyzer quality gate passes.",
                    repair_hint="Fix upstream analyzer quality issues, then recompile the generator handoff.",
                )
            )
    expected_arc_count = _as_int(gate.get("expected_arc_count"))
    arc_count = _as_int(gate.get("arc_count"))
    if expected_arc_count and arc_count != expected_arc_count:
        issues.append(
            _issue(
                code="QUALITY_GATE_ARC_COUNT_MISMATCH",
                severity="blocking",
                category="quality_gate",
                target_path="quality_gate.arc_count",
                message="arc_count must equal expected_arc_count",
                current_value={"arc_count": arc_count, "expected_arc_count": expected_arc_count},
                expected_constraint="Arc count must match the expected analyzer arc ranges.",
                repair_hint="Rebuild arc hierarchy and generator handoff from validated arc files.",
            )
        )
    if gate.get("llm_health_status") == "recovered_with_retries":
        issues.append(
            _issue(
                code="LLM_RETRY_RECOVERED",
                severity="warning",
                category="quality_gate",
                target_path="quality_gate.llm_health_status",
                message="LLM/API failures were recovered by retry",
                current_value=gate.get("llm_health_status"),
                expected_constraint="Recovered retries are allowed but should be visible to downstream systems.",
                repair_hint="No repair required unless retries correlate with low-quality materials.",
            )
        )


def _check_arc_coverage(handoff: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    hierarchy = _dict_value(handoff.get("arc_hierarchy"))
    sub_arcs = [item for item in _list_value(hierarchy.get("sub_arcs")) if isinstance(item, dict)]
    major_arcs = [item for item in _list_value(hierarchy.get("major_arcs")) if isinstance(item, dict)]
    sub_ids = {str(item.get("sub_arc_id")) for item in sub_arcs if item.get("sub_arc_id")}
    for index, major in enumerate(major_arcs):
        unknown = [sub_id for sub_id in _list_value(major.get("sub_arc_ids")) if str(sub_id) not in sub_ids]
        if unknown:
            issues.append(
                _issue(
                    code="MAJOR_ARC_UNKNOWN_SUB_ARC",
                    severity="blocking",
                    category="coverage",
                    target_path=f"arc_hierarchy.major_arcs[{index}].sub_arc_ids",
                    message="major arc references unknown sub arcs",
                    current_value=unknown,
                    expected_constraint="Major arcs may only reference existing sub arcs.",
                    repair_hint="Rebuild arc_hierarchy from validated sub arcs.",
                )
            )
    source_map = _dict_value(handoff.get("source_map"))
    expected_units = set(range(1, _as_int(source_map.get("analysis_unit_count")) + 1))
    sub_arc_units: set[int] = set()
    for sub_arc in sub_arcs:
        sub_arc_units.update(_parse_range(sub_arc.get("analysis_unit_range")))
        if not sub_arc.get("source_chapter_range") or not sub_arc.get("analysis_unit_range"):
            issues.append(
                _issue(
                    code="SUB_ARC_RANGE_MISSING",
                    severity="blocking",
                    category="coverage",
                    target_path=f"arc_hierarchy.sub_arcs[{sub_arcs.index(sub_arc)}]",
                    message="sub arc must preserve source and analysis ranges",
                    current_value=sub_arc,
                    expected_constraint="Each sub arc must be traceable to source chapters and analysis units.",
                    repair_hint="Regenerate arc_hierarchy from source_map arc ranges.",
                )
            )
    if expected_units and sub_arc_units and not expected_units.issubset(sub_arc_units):
        issues.append(
            _issue(
                code="ARC_ANALYSIS_UNIT_COVERAGE",
                severity="blocking",
                category="coverage",
                target_path="arc_hierarchy.sub_arcs",
                message="sub arcs do not cover every analysis unit",
                current_value={"covered_units": sorted(sub_arc_units), "expected_units": sorted(expected_units)},
                expected_constraint="Sub arcs must cover the chapter blueprint analysis units.",
                repair_hint="Repair arc boundaries or rebuild arc_hierarchy from confirmed arcs.",
            )
        )


def _check_materials(
    handoff: dict[str, Any],
    source_references: dict[str, dict[str, Any]],
    source_terms: set[str],
    issues: list[dict[str, Any]],
    *,
    run_dir: str | Path,
    evidence_mode: str = "auto",
    semantic_validator: SemanticValidator | None = None,
    semantic_audit: dict[str, Any] | None = None,
) -> None:
    materials = _list_value(handoff.get("generator_materials"))
    if not materials:
        issues.append(
            _issue(
                code="EMPTY_GENERATOR_MATERIALS",
                severity="blocking",
                category="generator_materials",
                target_path="generator_materials",
                message="generator_materials must not be empty",
                expected_constraint="Generator must receive at least one validated material.",
                repair_hint="Recompile generator handoff after upstream module extraction succeeds.",
            )
        )
        return
    seen_content: dict[str, str] = {}
    for index, material in enumerate(materials):
        target = f"generator_materials[{index}]"
        if not isinstance(material, dict):
            issues.append(
                _issue(
                    code="INVALID_MATERIAL",
                    severity="blocking",
                    category="schema",
                    target_path=target,
                    message="material must be an object",
                    current_value=material,
                    expected_constraint="Every generator material must be an object.",
                    repair_hint="Recompile generator materials from structured module outputs.",
                )
            )
            continue
        material_id = str(material.get("material_id") or f"material_{index}")
        source_refs = [str(ref) for ref in _list_value(material.get("source_refs")) if ref]
        evidence = _evidence_for_refs(source_refs, source_references)
        missing_fields = sorted(REQUIRED_MATERIAL_FIELDS - set(material))
        if missing_fields:
            issues.append(
                _issue(
                    code="MATERIAL_SCHEMA_MISSING_FIELD",
                    severity="blocking",
                    category="schema",
                    target_path=target,
                    message=f"material is missing required fields: {missing_fields}",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value={"material_id": material_id, "missing_fields": missing_fields},
                    expected_constraint="Every material must satisfy the generator material contract.",
                    repair_hint="Recompile this material from the corresponding analyzer module.",
                )
            )
        module_type = material.get("module_type")
        if module_type not in VALID_MODULE_TYPES:
            issues.append(
                _issue(
                    code="INVALID_MATERIAL_MODULE_TYPE",
                    severity="blocking",
                    category="generator_materials",
                    target_path=f"{target}.module_type",
                    message="material module_type is not in the allowed enum",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value=module_type,
                    expected_constraint=f"module_type must be one of {sorted(VALID_MODULE_TYPES)}.",
                    repair_hint="Map the module to a supported generator-facing module_type.",
                )
            )
        abstraction_level = material.get("abstraction_level")
        if abstraction_level not in VALID_ABSTRACTION_LEVELS:
            issues.append(
                _issue(
                    code="INVALID_ABSTRACTION_LEVEL",
                    severity="blocking",
                    category="generator_materials",
                    target_path=f"{target}.abstraction_level",
                    message="material abstraction_level is not in the allowed enum",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value=abstraction_level,
                    expected_constraint=f"abstraction_level must be one of {sorted(VALID_ABSTRACTION_LEVELS)}.",
                    repair_hint="Normalize abstraction_level before sending to generator.",
                )
            )
        source_dependence = material.get("source_dependence")
        if source_dependence not in VALID_SOURCE_DEPENDENCE:
            issues.append(
                _issue(
                    code="INVALID_SOURCE_DEPENDENCE",
                    severity="blocking",
                    category="generator_materials",
                    target_path=f"{target}.source_dependence",
                    message="material source_dependence is not in the allowed enum",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value=source_dependence,
                    expected_constraint=f"source_dependence must be one of {sorted(VALID_SOURCE_DEPENDENCE)}.",
                    repair_hint="Normalize source_dependence before sending to generator.",
                )
            )
        if _is_empty_content(material.get("content")):
            issues.append(
                _issue(
                    code="EMPTY_MATERIAL_CONTENT",
                    severity="blocking",
                    category="generator_materials",
                    target_path=f"{target}.content",
                    message="material content must not be empty",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    expected_constraint="Generator materials must contain usable content.",
                    repair_hint="Regenerate this material from source evidence.",
                )
            )
        if not material.get("selection_tags"):
            issues.append(
                _issue(
                    code="MISSING_SELECTION_TAGS",
                    severity="blocking",
                    category="generator_materials",
                    target_path=f"{target}.selection_tags",
                    message="material must include selection_tags",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    expected_constraint="Generator selection must be driven by explicit tags.",
                    repair_hint="Add selection_tags according to the material usage profile.",
                )
            )
        if not source_refs:
            issues.append(
                _issue(
                    code="MISSING_MATERIAL_SOURCE_REFS",
                    severity="blocking",
                    category="generator_materials",
                    target_path=f"{target}.source_refs",
                    message="material must include source_refs",
                    current_value=material.get("source_refs"),
                    expected_constraint="Every generator material must be traceable to near-source evidence.",
                    repair_hint="Attach source_refs from the chapter, arc, or book module that produced this material.",
                )
            )
        unknown_refs = [ref for ref in source_refs if ref not in source_references]
        if unknown_refs:
            issues.append(
                _issue(
                    code="MISSING_SOURCE_REFERENCE",
                    severity="blocking",
                    category="source_evidence",
                    target_path=f"{target}.source_refs",
                    message="material references source refs missing from source_reference_index",
                    source_refs=unknown_refs,
                    current_value=unknown_refs,
                    expected_constraint="All source_refs must resolve inside source_reference_index.",
                    repair_hint="Repair source_refs or regenerate source_reference_index.",
                )
            )
        content_text = _content_text(material.get("content"))
        for marker in INTERNAL_MARKERS:
            if marker.lower() in content_text.lower():
                issues.append(
                    _issue(
                        code="INTERNAL_MARKER_LEAK",
                        severity="blocking",
                        category="source_leak",
                        target_path=f"{target}.content",
                        message=f"internal marker leaked into generator material: {marker}",
                        source_refs=source_refs,
                        near_source_evidence=evidence,
                        current_value=marker,
                        expected_constraint="Generator-facing content must not contain internal analyzer markers.",
                        repair_hint="Remove internal markers and regenerate the affected material.",
                    )
                )
        if source_dependence == "source_free":
            for term in sorted(source_terms, key=len, reverse=True):
                if _text_contains_term(content_text, term):
                    issues.append(
                        _issue(
                            code="SOURCE_FREE_SOURCE_TERM_LEAK",
                            severity="blocking",
                            category="source_leak",
                            target_path=f"{target}.content",
                            message="source_free material contains source-specific term",
                            source_refs=source_refs,
                            near_source_evidence=evidence,
                            current_value=term,
                            expected_constraint="source_free materials must be de-named and reusable without source setting contamination.",
                            repair_hint="Replace source-specific terms with structural roles or placeholders.",
                        )
                    )
                    break
        if source_dependence in {"source_free", "adaptable"}:
            mechanism_text = content_text.lower()
            if mechanism_text and not any(term in mechanism_text for term in MECHANISM_TERMS):
                issues.append(
                    _issue(
                        code="ABSTRACTION_MECHANISM_WEAK",
                        severity="warning",
                        category="abstraction_quality",
                        target_path=f"{target}.content",
                        message="abstract/adaptable material may be restating plot without explicit mechanism language",
                        source_refs=source_refs,
                        near_source_evidence=evidence,
                        current_value=_clip(material.get("content")),
                        expected_constraint="Reusable materials should expose rhythm, conflict, structure, or information-release mechanisms.",
                        repair_hint="Rewrite the material as a reusable narrative mechanism.",
                    )
                )
        if source_dependence == "source_bound" and source_refs and not unknown_refs:
            if _v2_evidence_enabled(run_dir, evidence_mode):
                v2_issue = _v2_source_bound_issue(
                    run_dir=run_dir,
                    material=material,
                    target=target,
                    source_refs=source_refs,
                    source_references=source_references,
                )
                if v2_issue:
                    issues.append(v2_issue)
                    continue
            if not evidence:
                issues.append(
                    _issue(
                        code="EVIDENCE_INSUFFICIENT",
                        severity="warning",
                        category="source_fidelity",
                        target_path=f"{target}.source_refs",
                        message="source_bound material has source_refs but no usable evidence text",
                        source_refs=source_refs,
                        current_value=source_refs,
                        expected_constraint="Source fidelity checks must be grounded in near-source evidence.",
                        repair_hint="Regenerate source_reference_index with near_source_summary or evidence_spans.",
                    )
                )
            else:
                semantic_result = _run_semantic_source_fidelity_check(
                    content=material.get("content"),
                    source_refs=source_refs,
                    evidence=evidence,
                    source_terms=source_terms,
                    semantic_validator=semantic_validator,
                )
                if semantic_audit is not None:
                    semantic_audit["semantic_adapter_id"] = semantic_result["adapter_id"]
                    semantic_audit["semantic_source_fidelity_check_count"] = (
                        semantic_audit.get("semantic_source_fidelity_check_count", 0) + 1
                    )
                    if semantic_result.get("prompt_built"):
                        semantic_audit["semantic_prompt_built_count"] = (
                            semantic_audit.get("semantic_prompt_built_count", 0) + 1
                        )
                    if semantic_result.get("external_validator_called"):
                        semantic_audit["semantic_validator_call_count"] = (
                            semantic_audit.get("semantic_validator_call_count", 0) + 1
                        )
                if semantic_result["status"] == "supported":
                    continue
                if semantic_result["status"] == "evidence_insufficient":
                    issues.append(
                        _issue(
                            code="SEMANTIC_VALIDATION_INSUFFICIENT",
                            severity="warning",
                            category="source_fidelity",
                            target_path=f"{target}.content",
                            message="semantic source fidelity validator could not make a grounded decision",
                            source_refs=source_refs,
                            near_source_evidence=evidence,
                            current_value=f"{_clip(material.get('content'))}; {semantic_result['reason']}",
                            expected_constraint="Semantic validation must return supported or mismatch using only supplied evidence.",
                            repair_hint="Review the source evidence or rerun semantic validation with a stable validator.",
                        )
                    )
                    continue
                mismatch_reason = semantic_result["reason"]
                if not mismatch_reason:
                    continue
                issues.append(
                    _issue(
                        code="SOURCE_BOUND_EVIDENCE_MISMATCH",
                        severity="blocking",
                        category="source_fidelity",
                        target_path=f"{target}.content",
                        message="source_bound material is not supported by its source evidence",
                        source_refs=source_refs,
                        near_source_evidence=evidence,
                        current_value=f"{_clip(material.get('content'))}; {mismatch_reason}",
                        expected_constraint="source_bound materials must not introduce facts absent from near-source evidence.",
                        repair_hint="Rewrite this material using only the supplied source_refs and evidence_text.",
                    )
                )
        content_key = re.sub(r"\s+", " ", content_text.lower()).strip()
        if content_key:
            previous = seen_content.get(content_key)
            if previous and previous != material_id:
                issues.append(
                    _issue(
                        code="DUPLICATE_GENERATOR_MATERIAL",
                        severity="warning",
                        category="generator_materials",
                        target_path=target,
                        message="material appears semantically duplicated by exact normalized content",
                        source_refs=source_refs,
                        near_source_evidence=evidence,
                        current_value={"material_id": material_id, "duplicates": previous},
                        expected_constraint="Generator materials should avoid duplicate memory pressure.",
                        repair_hint="Merge duplicate materials or keep one canonical copy.",
                    )
                )
            seen_content[content_key] = material_id


def _check_foreshadowing_registry(
    handoff: dict[str, Any],
    source_references: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
    *,
    run_dir: str | Path,
    evidence_mode: str,
) -> None:
    registry = _dict_value(handoff.get("foreshadowing_registry"))
    items = _list_value(registry.get("items"))
    seen_ids: set[str] = set()
    seen_content: dict[str, str] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        target = f"foreshadowing_registry.items[{index}]"
        item_id = str(item.get("id") or "")
        source_refs = [str(ref) for ref in _list_value(item.get("source_refs")) if ref]
        if not source_refs:
            for key in ("planted_chapter", "resolved_in_chapter"):
                chapter_index = _as_int(item.get(key))
                if chapter_index:
                    source_refs.append(_source_ref_from_unit(chapter_index))
            for chapter_index in _list_value(item.get("partial_resolution_chapters")):
                parsed = _as_int(chapter_index)
                if parsed:
                    source_refs.append(_source_ref_from_unit(parsed))
        evidence = _evidence_for_refs(source_refs, source_references)
        if not item_id:
            issues.append(
                _issue(
                    code="FORESHADOWING_ID_MISSING",
                    severity="blocking",
                    category="foreshadowing_registry",
                    target_path=f"{target}.id",
                    message="foreshadowing item id is required",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    expected_constraint="Every strict foreshadowing item must have a stable id.",
                    repair_hint="Assign a stable registry id after canonical deduplication.",
                )
            )
        elif item_id in seen_ids:
            issues.append(
                _issue(
                    code="FORESHADOWING_ID_DUPLICATE",
                    severity="blocking",
                    category="foreshadowing_registry",
                    target_path=f"{target}.id",
                    message="foreshadowing id is duplicated",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value=item_id,
                    expected_constraint="Foreshadowing ids must be unique.",
                    repair_hint="Merge duplicate items or allocate a new stable id only for distinct semantic content.",
                )
            )
        seen_ids.add(item_id)
        status = item.get("status")
        if status not in VALID_FORESHADOWING_STATUS:
            issues.append(
                _issue(
                    code="FORESHADOWING_STATUS_INVALID",
                    severity="blocking",
                    category="foreshadowing_registry",
                    target_path=f"{target}.status",
                    message="foreshadowing status is not in the allowed enum",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value=status,
                    expected_constraint=f"status must be one of {sorted(VALID_FORESHADOWING_STATUS)}.",
                    repair_hint="Normalize status before handoff.",
                )
            )
        if status == "resolved" and item.get("open_questions"):
            issues.append(
                _issue(
                    code="FORESHADOWING_STATUS_CONFLICT",
                    severity="blocking",
                    category="foreshadowing_registry",
                    target_path=target,
                    message="resolved foreshadowing item must not keep open_questions",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value={"status": status, "open_questions": item.get("open_questions")},
                    expected_constraint="resolved means no remaining open questions.",
                    repair_hint="Change status to partially_resolved or clear open_questions if fully closed.",
                )
            )
        if status == "planted" and item.get("resolved_in_chapter"):
            issues.append(
                _issue(
                    code="FORESHADOWING_STATUS_CONFLICT",
                    severity="blocking",
                    category="foreshadowing_registry",
                    target_path=target,
                    message="planted foreshadowing item must not include resolved_in_chapter",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value={"status": status, "resolved_in_chapter": item.get("resolved_in_chapter")},
                    expected_constraint="planted means not yet resolved.",
                    repair_hint="Change status to resolved or remove resolved_in_chapter.",
                )
            )
        if status == "partially_resolved" and item.get("resolved_in_chapter") and not item.get("partial_resolution_chapters"):
            issues.append(
                _issue(
                    code="FORESHADOWING_STATUS_CONFLICT",
                    severity="blocking",
                    category="foreshadowing_registry",
                    target_path=target,
                    message="partially_resolved should use partial_resolution_chapters",
                    source_refs=source_refs,
                    near_source_evidence=evidence,
                    current_value={"resolved_in_chapter": item.get("resolved_in_chapter")},
                    expected_constraint="partial resolution must not be encoded as final resolved_in_chapter.",
                    repair_hint="Move partial reveal chapters into partial_resolution_chapters.",
                )
            )
        if not source_refs:
            issues.append(
                _issue(
                    code="FORESHADOWING_SOURCE_REF_MISSING",
                    severity="blocking",
                    category="foreshadowing_registry",
                    target_path=target,
                    message="foreshadowing item has no source_refs or chapter trace",
                    current_value=item_id,
                    expected_constraint="Every foreshadowing item must trace back to source evidence.",
                    repair_hint="Attach planted/resolution chapter refs or remove untraceable item.",
                )
            )
        unknown_refs = [ref for ref in source_refs if ref not in source_references]
        if unknown_refs:
            issues.append(
                _issue(
                    code="FORESHADOWING_SOURCE_REF_UNKNOWN",
                    severity="blocking",
                    category="foreshadowing_registry",
                    target_path=target,
                    message="foreshadowing item references unknown source refs",
                    source_refs=unknown_refs,
                    current_value=unknown_refs,
                    expected_constraint="Foreshadowing source refs must resolve in source_reference_index.",
                    repair_hint="Repair source_refs or regenerate source_reference_index.",
                )
            )
        elif source_refs and _v2_evidence_enabled(run_dir, evidence_mode):
            v2_issue = _v2_foreshadowing_evidence_issue(
                run_dir=run_dir,
                item=item,
                target=target,
                source_refs=source_refs,
                source_references=source_references,
            )
            if v2_issue:
                issues.append(v2_issue)
        canonical = re.sub(r"\s+", " ", _content_text(item.get("canonical_content") or item.get("summary") or item.get("text")).lower()).strip()
        if canonical:
            previous = seen_content.get(canonical)
            if previous and previous != item_id:
                issues.append(
                    _issue(
                        code="FORESHADOWING_DUPLICATE_SEMANTIC_ITEM",
                        severity="warning",
                        category="foreshadowing_registry",
                        target_path=target,
                        message="foreshadowing items have duplicate normalized content",
                        source_refs=source_refs,
                        near_source_evidence=evidence,
                        current_value={"id": item_id, "duplicates": previous},
                        expected_constraint="The registry should keep one canonical item per semantic foreshadowing thread.",
                        repair_hint="Merge duplicate registry items and preserve state_updates.",
                    )
                )
            seen_content[canonical] = item_id


def _build_repair_plan(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    action_by_category = {
        "schema": "recompile_generator_handoff",
        "source_map": "rebuild_source_map",
        "quality_gate": "rerun_upstream_quality_gate",
        "source_leak": "rewrite_material_de_named",
        "abstraction_quality": "rewrite_material_as_mechanism",
        "source_fidelity": "rewrite_material_from_source_evidence",
        "foreshadowing_registry": "repair_foreshadowing_registry",
        "coverage": "rebuild_arc_chapter_coverage",
        "generator_materials": "repair_generator_material_contract",
        "source_evidence": "repair_source_reference_index",
    }
    for issue in issues:
        if issue.get("severity") != "blocking":
            continue
        actions.append(
            {
                "repair_action": action_by_category.get(issue.get("category"), "repair_handoff_issue"),
                "target_path": issue.get("target_path", ""),
                "source_refs": issue.get("source_refs", []),
                "issue_code": issue.get("code", ""),
                "repair_constraints": [
                    "Do not introduce facts outside source evidence.",
                    "Preserve source_refs after repair.",
                    issue.get("expected_constraint", ""),
                ],
            }
        )
    return actions


def _build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Generator Handoff Validation Report",
        "",
        f"- status: {report['validation_status']}",
        f"- blocking issues: {report['blocking_issue_count']}",
        f"- warnings: {report['warning_count']}",
        "",
        "## Issues",
    ]
    if not report["issues"]:
        lines.append("")
        lines.append("No issues found.")
    for issue in report["issues"]:
        lines.extend(
            [
                "",
                f"### {issue['issue_id']} {issue['code']}",
                "",
                f"- severity: {issue['severity']}",
                f"- category: {issue['category']}",
                f"- target: {issue['target_path']}",
                f"- message: {issue['message']}",
                f"- source_refs: {', '.join(issue.get('source_refs') or []) or 'none'}",
                f"- repair_hint: {issue.get('repair_hint') or 'none'}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def build_semantic_validation_prompt(
    *,
    content: Any,
    source_refs: list[str],
    evidence_items: list[dict[str, Any]],
    question: str,
) -> str:
    evidence_text = "\n".join(
        f"- {item.get('ref_id', '')}: {item.get('evidence_text', '')}" for item in evidence_items
    )
    return (
        "Only use the provided source evidence.\n"
        "Do not use external knowledge, memory of the original work, or common-sense additions.\n"
        "If the evidence is insufficient, return evidence_insufficient instead of guessing.\n\n"
        f"Question: {question}\n"
        f"Source refs: {', '.join(source_refs)}\n"
        f"Evidence:\n{evidence_text}\n\n"
        f"Material:\n{json.dumps(content, ensure_ascii=False, indent=2)}"
    )


def _run_semantic_source_fidelity_check(
    *,
    content: Any,
    source_refs: list[str],
    evidence: list[dict[str, Any]],
    source_terms: set[str],
    semantic_validator: SemanticValidator | None,
) -> dict[str, Any]:
    prompt = build_semantic_validation_prompt(
        content=content,
        source_refs=source_refs,
        evidence_items=evidence,
        question="Does this source_bound material introduce any fact, relationship, state, or setting absent from the evidence?",
    )
    deterministic_reason = _source_fidelity_mismatch_reason(content, evidence, source_terms)
    result = {
        "adapter_id": SEMANTIC_VALIDATION_ADAPTER_ID,
        "status": "mismatch" if deterministic_reason else "supported",
        "reason": deterministic_reason,
        "decision_source": "deterministic_rules",
        "prompt_built": True,
        "external_validator_called": False,
    }
    if deterministic_reason or semantic_validator is None:
        return result

    request = {
        "adapter_id": SEMANTIC_VALIDATION_ADAPTER_ID,
        "prompt": prompt,
        "content": content,
        "source_refs": source_refs,
        "evidence_items": evidence,
        "allowed_decisions": ["supported", "mismatch", "evidence_insufficient"],
    }
    result["external_validator_called"] = True
    try:
        semantic_response = semantic_validator(request)
    except Exception as exc:
        result.update(
            {
                "status": "evidence_insufficient",
                "reason": f"semantic validator failed: {exc}",
                "decision_source": "external_semantic_validator",
            }
        )
        return result
    if not isinstance(semantic_response, dict):
        result.update(
            {
                "status": "evidence_insufficient",
                "reason": "semantic validator returned a non-object response",
                "decision_source": "external_semantic_validator",
            }
        )
        return result

    decision = str(semantic_response.get("decision") or semantic_response.get("status") or "").strip().lower()
    reason = str(semantic_response.get("reason") or semantic_response.get("message") or "").strip()
    if decision in {"mismatch", "unsupported", "failed"}:
        result.update(
            {
                "status": "mismatch",
                "reason": reason or "semantic validator reported unsupported source-bound content",
                "decision_source": "external_semantic_validator",
            }
        )
    elif decision in {"evidence_insufficient", "insufficient", "unknown"}:
        result.update(
            {
                "status": "evidence_insufficient",
                "reason": reason or "semantic validator reported insufficient evidence",
                "decision_source": "external_semantic_validator",
            }
        )
    elif decision == "supported":
        result.update(
            {
                "status": "supported",
                "reason": reason,
                "decision_source": "external_semantic_validator",
            }
        )
    else:
        invalid_decision = decision or "<missing>"
        result.update(
            {
                "status": "evidence_insufficient",
                "reason": (
                    f"unsupported semantic validator decision: {invalid_decision}"
                    + (f"; {reason}" if reason else "")
                ),
                "decision_source": "external_semantic_validator",
            }
        )
    return result


def validate_generator_handoff(
    run_dir: str | Path,
    *,
    attempt_index: int = 0,
    evidence_mode: str = "auto",
    semantic_validator: SemanticValidator | None = None,
) -> dict[str, Any]:
    handoff_dir = _handoff_dir(run_dir)
    unified_path = handoff_dir / "unified_generator_handoff.json"
    source_index_path = handoff_dir / "source_reference_index.json"
    handoff, handoff_error = _read_json(unified_path)
    source_index, source_index_error = _read_json(source_index_path)
    issues: list[dict[str, Any]] = []
    semantic_audit: dict[str, Any] = {
        "semantic_adapter_id": SEMANTIC_VALIDATION_ADAPTER_ID,
        "semantic_source_fidelity_check_count": 0,
        "semantic_prompt_built_count": 0,
        "semantic_validator_call_count": 0,
    }

    if handoff_error:
        issues.append(
            _issue(
                code="INVALID_OR_MISSING_HANDOFF",
                severity="blocking",
                category="schema",
                target_path="generator_handoff/unified_generator_handoff.json",
                message=handoff_error,
                expected_constraint="unified_generator_handoff.json must exist and be valid JSON.",
                repair_hint="Run compile-generator-handoff again after upstream outputs are valid.",
            )
        )
    if source_index_error:
        issues.append(
            _issue(
                code="INVALID_OR_MISSING_SOURCE_REFERENCE_INDEX",
                severity="blocking",
                category="source_evidence",
                target_path="generator_handoff/source_reference_index.json",
                message=source_index_error,
                expected_constraint="source_reference_index.json must exist and contain near-source evidence.",
                repair_hint="Run compile-generator-handoff again to rebuild source_reference_index.",
            )
        )

    source_references = _source_references(source_index)
    if handoff:
        _check_schema(handoff, issues)
        _check_source_map(handoff, issues)
        _check_quality_gate(handoff, issues)
        _check_arc_coverage(handoff, issues)
        source_terms = _collect_source_terms(handoff)
        _check_materials(
            handoff,
            source_references,
            source_terms,
            issues,
            run_dir=run_dir,
            evidence_mode=evidence_mode,
            semantic_validator=semantic_validator,
            semantic_audit=semantic_audit,
        )
        _check_foreshadowing_registry(
            handoff,
            source_references,
            issues,
            run_dir=run_dir,
            evidence_mode=evidence_mode,
        )

    _assign_issue_ids(issues)
    blocking_count = sum(1 for issue in issues if issue.get("severity") == "blocking")
    warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")
    validation_status = "failed" if blocking_count else "passed_with_warnings" if warning_count else "passed"
    report = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "validation_status": validation_status,
        "checked_at": now_iso(),
        "attempt_index": attempt_index,
        "blocking_issue_count": blocking_count,
        "warning_count": warning_count,
        "issues": issues,
        "evidence_audit": {
            "source_reference_count": len(source_references),
            "evidence_mode": evidence_mode,
            "v2_raw_source_index_available": raw_source_index_path(_output_dir(run_dir)).exists(),
            "material_count": len(_list_value(handoff.get("generator_materials"))) if handoff else 0,
            "materials_with_source_refs": sum(
                1 for material in _list_value(handoff.get("generator_materials")) if isinstance(material, dict) and material.get("source_refs")
            )
            if handoff
            else 0,
            **semantic_audit,
        },
        "recommended_repair_plan": _build_repair_plan(issues),
    }
    write_json(handoff_dir / "validation_report.json", report)
    (handoff_dir / "validation_report.md").write_text(_build_markdown_report(report), encoding="utf-8")
    return report
