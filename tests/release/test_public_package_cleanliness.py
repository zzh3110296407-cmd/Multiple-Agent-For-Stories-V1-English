import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {".git", "dist", "node_modules", "__pycache__"}

FORBIDDEN_PATTERNS = {
    "Windows user directory": re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    "local release directory": re.compile(
        r"D:\\Multiple Agent For Stories-V1", re.IGNORECASE
    ),
    "retired model proxy": re.compile(r"209\.54\.107\.24"),
    "source-specific public sample": re.compile(
        r"祝福|边城|祥林嫂|带上她的眼睛|龙族|卡塞尔|路明非|源稚生|"
        r"酒德麻衣|源稚女|王将|言灵|longzu|nibelungen|fenrisulfr",
        re.IGNORECASE,
    ),
}


def _text_files() -> list[Path]:
    return [
        path
        for path in REPO_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and not any(part in IGNORED_PARTS for part in path.parts)
        and path.resolve() != Path(__file__).resolve()
    ]


class PublicPackageCleanlinessTests(unittest.TestCase):
    def test_public_text_has_no_private_paths_or_source_specific_samples(self) -> None:
        findings: list[str] = []
        for path in _text_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for label, pattern in FORBIDDEN_PATTERNS.items():
                if pattern.search(text):
                    findings.append(f"{path.relative_to(REPO_ROOT)}: {label}")

        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
