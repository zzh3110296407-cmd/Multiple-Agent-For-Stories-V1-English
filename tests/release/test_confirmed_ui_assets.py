import re
import unittest
from collections import deque
from pathlib import Path
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "app" / "frontend" / "public" / "confirmed-ui"
PAGE_MAP = (
    REPO_ROOT
    / "app"
    / "frontend"
    / "src"
    / "production-ui"
    / "data"
    / "confirmedPages.js"
)

PAGE_PATTERN = re.compile(
    r'page\(\s*"[^"]+"\s*,\s*"[^"]*"\s*,\s*"([^"]+\.html)"',
    re.DOTALL,
)
ATTRIBUTE_PATTERN = re.compile(
    r"""(?:src|href)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE | re.DOTALL,
)
CSS_URL_PATTERN = re.compile(
    r"""url\(\s*["']?([^)\"']+)["']?\s*\)""",
    re.IGNORECASE | re.DOTALL,
)
QUOTED_ASSET_PATTERN = re.compile(
    r"""["']([^"']+\.(?:html|css|js|png|jpe?g|webp|gif|svg|woff2?|ttf)(?:\?[^"']*)?)["']""",
    re.IGNORECASE | re.DOTALL,
)
TRAVERSABLE_SUFFIXES = {".html", ".css", ".js"}


def _resolve_reference(reference: str, source: Path) -> Path | None:
    value = reference.strip().strip("\"'")
    if not value or value.startswith(("#", "data:", "http:", "https:", "//", "javascript:")):
        return None

    value = unquote(re.split(r"[?#]", value, maxsplit=1)[0])
    if value.startswith("/confirmed-ui/"):
        candidate = UI_ROOT / value.removeprefix("/confirmed-ui/")
    elif value.startswith("/"):
        return None
    else:
        candidate = source.parent / value

    resolved = candidate.resolve()
    try:
        resolved.relative_to(UI_ROOT.resolve())
    except ValueError:
        return None
    return resolved


def collect_runtime_files() -> tuple[set[Path], list[str]]:
    page_map = PAGE_MAP.read_text(encoding="utf-8")
    page_paths = sorted(set(PAGE_PATTERN.findall(page_map)))
    if len(page_paths) != 75:
        raise AssertionError(
            f"Expected 75 registered confirmed UI pages, found {len(page_paths)}"
        )

    runtime_files: set[Path] = set()
    missing: list[str] = []
    queue: deque[Path] = deque()

    for relative_path in page_paths:
        entry = (UI_ROOT / relative_path).resolve()
        if not entry.is_file():
            missing.append(f"registered page: {relative_path}")
            continue
        runtime_files.add(entry)
        queue.append(entry)

    while queue:
        source = queue.popleft()
        text = source.read_text(encoding="utf-8")
        references = [
            *(match.group(1) for match in ATTRIBUTE_PATTERN.finditer(text)),
            *(match.group(1) for match in CSS_URL_PATTERN.finditer(text)),
            *(match.group(1) for match in QUOTED_ASSET_PATTERN.finditer(text)),
        ]
        for reference in references:
            dependency = _resolve_reference(reference, source)
            if dependency is None:
                continue
            if not dependency.is_file():
                missing.append(
                    f"{source.relative_to(UI_ROOT)} -> {reference}"
                )
                continue
            if dependency in runtime_files:
                continue
            runtime_files.add(dependency)
            if dependency.suffix.lower() in TRAVERSABLE_SUFFIXES:
                queue.append(dependency)

    return runtime_files, sorted(set(missing))


class ConfirmedUiReleaseTests(unittest.TestCase):
    def test_registered_pages_and_local_assets_exist(self) -> None:
        _, missing = collect_runtime_files()
        self.assertEqual([], missing)

    def test_public_confirmed_ui_contains_only_runtime_files(self) -> None:
        runtime_files, _ = collect_runtime_files()
        packaged_files = {
            path.resolve() for path in UI_ROOT.rglob("*") if path.is_file()
        }
        extras = sorted(
            str(path.relative_to(UI_ROOT))
            for path in packaged_files - runtime_files
        )
        self.assertEqual([], extras)


if __name__ == "__main__":
    unittest.main()
