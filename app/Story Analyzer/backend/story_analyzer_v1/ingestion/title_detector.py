from __future__ import annotations

from dataclasses import dataclass, field
import re


_CN_NUM = "零〇一二两三四五六七八九十百千万\\d"
_BODY_CLAUSE_PATTERNS = [
    re.compile(rf"^第[{_CN_NUM}]+章第[{_CN_NUM}]+条"),
    re.compile(rf"^第[{_CN_NUM}]+章的"),
    re.compile(rf"^第[{_CN_NUM}]+节"),
]
_HEADING_PATTERNS = [
    re.compile(rf"^第[{_CN_NUM}]+[章节回幕](?:\s+|\s*[：:])?.{{0,24}}$"),
    re.compile(r"^(序幕|楔子|前言|序章|尾声|后记|结语)(?:\s+.{0,24})?$"),
    re.compile(r"^Chapter\s+\d+(?:\s+.{1,32})?$", flags=re.IGNORECASE),
]


@dataclass(frozen=True)
class TitleCandidate:
    line_number: int
    raw_line: str
    normalized_title: str
    score: int
    accepted: bool
    suspicious: bool
    reasons: list[str] = field(default_factory=list)


def normalize_heading_line(line: str) -> tuple[str, bool]:
    stripped = " ".join(line.lstrip("\ufeff").strip().split())
    if not stripped:
        return "", False
    markdown = bool(re.match(r"^#{1,6}\s+", stripped))
    if markdown:
        stripped = re.sub(r"^#{1,6}\s+", "", stripped).strip()
    return stripped, markdown


def is_body_like_heading(line: str) -> bool:
    if any(pattern.search(line) for pattern in _BODY_CLAUSE_PATTERNS):
        return True
    if re.search(r"[。！？；]", line):
        return True
    if len(line) > 64:
        return True
    return False


def score_title_candidate(
    raw_line: str,
    *,
    line_number: int,
    previous_blank: bool,
    next_blank: bool,
) -> TitleCandidate:
    normalized, markdown = normalize_heading_line(raw_line)
    reasons: list[str] = []
    score = 0

    if not normalized:
        return TitleCandidate(line_number, raw_line, normalized, 0, False, False, ["blank_line"])

    if markdown:
        score += 2
        reasons.append("markdown_heading")

    if any(pattern.match(normalized) for pattern in _HEADING_PATTERNS):
        score += 4
        reasons.append("heading_pattern")

    if previous_blank:
        score += 1
        reasons.append("previous_blank")
    if next_blank:
        score += 1
        reasons.append("next_blank")
    if len(normalized) <= 32:
        score += 1
        reasons.append("short_line")

    if is_body_like_heading(normalized):
        score -= 10
        reasons.append("body_like_or_rejected_pattern")

    accepted = score >= 4 and "heading_pattern" in reasons and "body_like_or_rejected_pattern" not in reasons
    suspicious = score >= 3 and not accepted
    return TitleCandidate(line_number, raw_line, normalized, score, accepted, suspicious, reasons)
