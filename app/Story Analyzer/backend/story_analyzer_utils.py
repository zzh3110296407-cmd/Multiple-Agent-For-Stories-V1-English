import re
from pathlib import Path


STORY_TEXT_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-32",
    "utf-32-le",
    "utf-32-be",
    "gb18030",
    "gbk",
    "big5",
    "cp950",
)


def _ordered_story_text_encodings(content: bytes) -> list[str]:
    if content.startswith(b"\xef\xbb\xbf"):
        preferred = ["utf-8-sig"]
    elif content.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        preferred = ["utf-32"]
    elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
        preferred = ["utf-16"]
    else:
        preferred = []
    ordered: list[str] = []
    for encoding in [*preferred, *STORY_TEXT_ENCODINGS]:
        if encoding not in ordered:
            ordered.append(encoding)
    return ordered


def story_text_quality_metrics(text: str) -> dict[str, float | int]:
    length = len(text)
    if length == 0:
        return {
            "length": 0,
            "nul_count": 0,
            "replacement_count": 0,
            "control_count": 0,
            "private_use_count": 0,
            "surrogate_count": 0,
            "cjk_count": 0,
            "ascii_text_count": 0,
            "printable_count": 0,
            "nul_ratio": 0.0,
            "replacement_ratio": 0.0,
            "control_ratio": 0.0,
            "private_use_ratio": 0.0,
            "surrogate_ratio": 0.0,
            "cjk_ratio": 0.0,
            "ascii_text_ratio": 0.0,
            "printable_ratio": 0.0,
        }

    nul_count = 0
    replacement_count = 0
    control_count = 0
    private_use_count = 0
    surrogate_count = 0
    cjk_count = 0
    ascii_text_count = 0
    printable_count = 0
    for ch in text:
        codepoint = ord(ch)
        if ch == "\x00":
            nul_count += 1
            continue
        if ch == "\ufffd":
            replacement_count += 1
        if codepoint < 32 and ch not in "\r\n\t":
            control_count += 1
        if 0xE000 <= codepoint <= 0xF8FF:
            private_use_count += 1
        if 0xD800 <= codepoint <= 0xDFFF:
            surrogate_count += 1
        if (0x3400 <= codepoint <= 0x4DBF) or (0x4E00 <= codepoint <= 0x9FFF):
            cjk_count += 1
        if ch.isascii() and (ch.isalnum() or ch.isspace() or ch in ".,;:!?'-_()[]{}<>/\\\""):
            ascii_text_count += 1
        if ch in "\r\n\t" or ch.isprintable():
            printable_count += 1

    def ratio(count: int) -> float:
        return count / length if length else 0.0

    return {
        "length": length,
        "nul_count": nul_count,
        "replacement_count": replacement_count,
        "control_count": control_count,
        "private_use_count": private_use_count,
        "surrogate_count": surrogate_count,
        "cjk_count": cjk_count,
        "ascii_text_count": ascii_text_count,
        "printable_count": printable_count,
        "nul_ratio": ratio(nul_count),
        "replacement_ratio": ratio(replacement_count),
        "control_ratio": ratio(control_count),
        "private_use_ratio": ratio(private_use_count),
        "surrogate_ratio": ratio(surrogate_count),
        "cjk_ratio": ratio(cjk_count),
        "ascii_text_ratio": ratio(ascii_text_count),
        "printable_ratio": ratio(printable_count),
    }


def story_text_quality_score(metrics: dict[str, float | int]) -> float:
    return (
        float(metrics["printable_ratio"]) * 100.0
        + min(float(metrics["cjk_ratio"]), 0.9) * 30.0
        + min(float(metrics["ascii_text_ratio"]), 0.9) * 8.0
        - float(metrics["nul_ratio"]) * 2000.0
        - float(metrics["replacement_ratio"]) * 1500.0
        - float(metrics["control_ratio"]) * 800.0
        - float(metrics["private_use_ratio"]) * 500.0
        - float(metrics["surrogate_ratio"]) * 1200.0
    )


def story_text_quality_errors(text: str) -> list[str]:
    metrics = story_text_quality_metrics(text)
    length = int(metrics["length"])
    if length == 0:
        return []
    errors: list[str] = []
    if int(metrics["nul_count"]) > 0:
        errors.append(f"contains {int(metrics['nul_count'])} NUL characters")
    replacement_limit = max(3, int(length * 0.001))
    if int(metrics["replacement_count"]) > replacement_limit:
        errors.append(f"contains {int(metrics['replacement_count'])} replacement characters")
    control_limit = max(8, int(length * 0.001))
    if int(metrics["control_count"]) > control_limit:
        errors.append(f"contains {int(metrics['control_count'])} control characters")
    if float(metrics["private_use_ratio"]) > 0.02 and int(metrics["private_use_count"]) > 1:
        errors.append(f"contains {int(metrics['private_use_count'])} private-use characters")
    if int(metrics["surrogate_count"]) > 0:
        errors.append(f"contains {int(metrics['surrogate_count'])} isolated surrogate characters")
    if float(metrics["printable_ratio"]) < 0.96:
        errors.append(f"printable ratio is {float(metrics['printable_ratio']):.2%}")
    return errors


def validate_story_text_quality(text: str, source_label: str = "story text") -> None:
    errors = story_text_quality_errors(text)
    if errors:
        detail = "; ".join(errors[:4])
        raise ValueError(
            f"{source_label} looks garbled / 疑似乱码，analysis was blocked. "
            f"Issues: {detail}. Save the file as UTF-8, UTF-16, UTF-32, GB18030, GBK, or Big5 and upload again."
        )


def decode_story_text_bytes(content: bytes, source_label: str = "uploaded file") -> str:
    if not content:
        return ""
    if b"\x00" not in content and all(byte < 0x80 for byte in content):
        decoded = content.decode("utf-8")
        validate_story_text_quality(decoded, source_label)
        return decoded

    candidates: list[tuple[float, str, str]] = []
    for encoding in _ordered_story_text_encodings(content):
        try:
            decoded = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        decoded = decoded.lstrip("\ufeff")
        metrics = story_text_quality_metrics(decoded)
        candidates.append((story_text_quality_score(metrics), encoding, decoded))

    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, _, decoded in candidates:
        if not story_text_quality_errors(decoded):
            return decoded

    if candidates:
        _, encoding, decoded = candidates[0]
        errors = "; ".join(story_text_quality_errors(decoded)[:4])
        raise ValueError(
            f"{source_label} looks garbled / 疑似乱码; best candidate encoding {encoding} failed quality checks. "
            f"Issues: {errors}. Save the file as UTF-8, UTF-16, UTF-32, GB18030, GBK, or Big5 and upload again."
        )
    raise ValueError(
        f"{source_label} cannot be decoded as UTF-8, UTF-16, UTF-32, GB18030, GBK, or Big5; garbled text suspected."
    )


def read_story_text_file(path: Path | str) -> str:
    file_path = Path(path)
    return decode_story_text_bytes(file_path.read_bytes(), source_label=str(file_path))


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def chinese_number_to_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[value]
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = _CHINESE_DIGITS.get(left, 1) if left else 1
        ones = _CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    total = 0
    for ch in value:
        if ch not in _CHINESE_DIGITS:
            return None
        total = total * 10 + _CHINESE_DIGITS[ch]
    return total


def chapter_sort_key(path: Path) -> tuple:
    name = path.stem if isinstance(path, Path) else Path(path).stem
    normalized = name.strip()

    leading_number = re.match(r"^(\d+)[_\-\s.]*", normalized)
    if leading_number:
        return (1, int(leading_number.group(1)), normalized)

    if normalized.startswith(("序幕", "楔子", "前言", "序章")):
        return (0, 0, normalized)

    chapter = re.search(r"第([零〇一二两三四五六七八九十百千万\d]+)[章节回幕]", normalized)
    if chapter:
        number = chinese_number_to_int(chapter.group(1))
        if number is not None:
            return (1, number, normalized)

    english = re.search(r"Chapter\s+(\d+)", normalized, flags=re.IGNORECASE)
    if english:
        return (1, int(english.group(1)), normalized)

    if normalized.startswith(("尾声", "后记", "结语")):
        return (2, 0, normalized)

    return (9, normalized)


def clean_chapter_title(text: str, chapter_index: int, max_chars: int = 80) -> str:
    first_line = ""
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if line:
            first_line = line
            break

    if not first_line:
        return f"第{chapter_index}章"

    heading = re.match(
        r"^(第[零〇一二两三四五六七八九十百千万\d]+[章节回幕](?:\s*[^\s，。！？；:：、]{1,16})?)",
        first_line,
    )
    if heading:
        return heading.group(1).strip()

    special = re.match(r"^(序幕|楔子|前言|序章|尾声|后记|结语)", first_line)
    if special:
        return special.group(1)

    english = re.match(r"^(Chapter\s+\d+(?:\s+[A-Za-z0-9_-]{1,24})?)", first_line, flags=re.IGNORECASE)
    if english:
        return english.group(1).strip()

    if re.search(r"[。！？；]", first_line):
        return f"第{chapter_index}章"

    if len(first_line) <= max_chars:
        return first_line

    return f"第{chapter_index}章"
