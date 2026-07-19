from __future__ import annotations

import re
from collections.abc import Iterable


def has_period_bound_exchange_rule(hard_rule_texts: Iterable[str]) -> bool:
    """Return true when confirmed rules bind an exchange to an eclipse period."""

    for value in hard_rule_texts:
        text = str(value or "").lower()
        has_eclipse = "月蚀" in text or "eclipse" in text
        has_exchange = "交换" in text or "exchange" in text
        has_period_boundary = any(marker in text for marker in ("期间", "月蚀时", "during", "when"))
        if has_eclipse and has_exchange and has_period_boundary:
            return True
    return False


def premature_period_exchange_claim(text: str) -> str:
    """Return the sentence that asserts an exchange before its eclipse trigger."""

    value = str(text or "")
    chinese_patterns = (
        r"月蚀(?:临近|将近|尚未开始|还未开始|未开始|之前|前).{0,80}(?:影子|名字|真名).{0,30}交换.{0,20}(?:随时|已经|开始|正在|发生)",
        r"月蚀(?:临近|将近|尚未开始|还未开始|未开始|之前|前).{0,80}(?:影子|名字|真名).{0,30}(?:随时|已经|开始|正在).{0,20}交换",
        r"月蚀(?:临近|将近).{0,80}交换.{0,20}随时可能发生",
    )
    chinese_sentences = [item for item in re.split(r"[。！？!?\n]+", value) if item.strip()]
    for sentence in chinese_sentences:
        explicitly_not_happened = any(
            marker in sentence
            for marker in (
                "交换也尚未发生",
                "交换尚未发生",
                "交换还未发生",
                "尚未交换",
                "没有发生交换",
                "并未发生交换",
            )
        )
        if explicitly_not_happened:
            continue
        if any(re.search(pattern, sentence) for pattern in chinese_patterns):
            return sentence.strip()

    english_patterns = (
        r"(?:before|ahead of|approaching)\s+(?:the\s+)?eclipse.{0,100}exchange.{0,30}(?:already|any time|underway|begins?)",
        r"eclipse\s+(?:has\s+)?not\s+(?:yet\s+)?begun.{0,100}exchange.{0,30}(?:already|underway|begins?)",
    )
    for sentence in re.split(r"[.!?\n]+", value.lower()):
        if not sentence.strip():
            continue
        if any(marker in sentence for marker in ("exchange has not", "exchange has not yet", "no exchange has")):
            continue
        if any(re.search(pattern, sentence) for pattern in english_patterns):
            return sentence.strip()
    return ""


def claims_premature_period_exchange(text: str) -> bool:
    """Return true when text asserts an exchange before its eclipse trigger."""

    return bool(premature_period_exchange_claim(text))
