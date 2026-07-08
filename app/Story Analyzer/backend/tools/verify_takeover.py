#!/usr/bin/env python3
import ast
import json
import re
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
CODE_DIR = BACKEND_DIR.parent
STORY_DIR = CODE_DIR.parent
PROJECT_DIR = next((path for path in [CODE_DIR, *CODE_DIR.parents] if (path / ".gitignore").exists()), STORY_DIR)


EXPECTED_TOP_LEVEL_DIRS = {
    "00_START_HERE",
    "01_Analyzer_Code",
    "02_Source_Materials",
    "03_Analysis_Outputs",
    "04_Handoff_Packages",
    "05_Comparison_Reports",
    "06_External_References",
}

PACKAGED_TOP_LEVEL_DIRS = {
    "backend",
    "data",
    "docs",
    "frontend",
}

OLD_TOP_LEVEL_DIRS = {
    "交付包",
    "分析输出",
    "同事提供",
    "拆解器_代码与文档",
    "春蚕",
    "比较报告",
    "素材",
}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"app-[A-Za-z0-9_-]{8,}"),
]


def fail(message: str) -> None:
    print("[FAIL] " + message)
    raise SystemExit(1)


def ok(message: str) -> None:
    print("[OK] " + message)


def _has_original_story_layout(path: Path) -> bool:
    return EXPECTED_TOP_LEVEL_DIRS.issubset({p.name for p in path.iterdir() if p.is_dir()})


def _is_packaged_layout() -> bool:
    return PACKAGED_TOP_LEVEL_DIRS.issubset({p.name for p in CODE_DIR.iterdir() if p.is_dir()})


def check_directory_layout() -> None:
    if _is_packaged_layout() and not _has_original_story_layout(STORY_DIR):
        existing = {p.name for p in CODE_DIR.iterdir() if p.is_dir()}
        missing = sorted(PACKAGED_TOP_LEVEL_DIRS - existing)
        if missing:
            fail("packaged analyzer missing dirs: " + ", ".join(missing))
        ok("packaged analyzer directory layout")
        return

    existing = {p.name for p in STORY_DIR.iterdir() if p.is_dir()}
    missing = sorted(EXPECTED_TOP_LEVEL_DIRS - existing)
    if missing:
        fail("story top-level missing dirs: " + ", ".join(missing))
    unexpected_old = sorted(OLD_TOP_LEVEL_DIRS & existing)
    if unexpected_old:
        fail("old top-level dirs still present: " + ", ".join(unexpected_old))
    ok("story top-level directory layout")


def check_gitignore() -> None:
    gitignore_files = [path / ".gitignore" for path in [CODE_DIR, *CODE_DIR.parents] if (path / ".gitignore").exists()]
    if not gitignore_files:
        fail(".gitignore missing")
    text = "\n".join(gitignore.read_text(encoding="utf-8") for gitignore in gitignore_files)
    for required in [".env", ".env.*", "!.env.example"]:
        if required not in text:
            fail(".gitignore missing required rule: " + required)
    ok(".gitignore protects local env files and allows .env.example")


def check_no_secrets() -> None:
    scanned = 0
    scan_roots = [CODE_DIR]
    start_here = STORY_DIR / "00_START_HERE"
    if start_here.exists():
        scan_roots.append(start_here)
    for path in scan_roots:
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.name == ".env":
                fail("real .env file is inside tracked analyzer tree: " + str(file_path))
            if file_path.suffix.lower() not in {".py", ".md", ".json", ".txt", ".example"}:
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            scanned += 1
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    fail("secret-like token found in " + str(file_path.relative_to(STORY_DIR)))
    ok(f"secret scan over {scanned} text files")


def check_python_syntax() -> None:
    parsed = 0
    for py_file in CODE_DIR.rglob("*.py"):
        ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        parsed += 1
    ok(f"python syntax parse for {parsed} files")


def check_handoff_package() -> None:
    sys.path.insert(0, str(BACKEND_DIR))
    sys.path.insert(0, str(CODE_DIR))
    from framework_package_normalizer import normalize_framework_package, validate_rich_like

    package_dir = STORY_DIR / "04_Handoff_Packages" / "handoff_package_clean_20260617_v4"
    if not package_dir.exists():
        packaged_package_dir = CODE_DIR / "data" / "handoff_package"
        required = {
            "recommended_framework.json",
            "vocabulary_export.json",
            "cross_novel_patterns.md",
            "integration_notes.md",
        }
        if packaged_package_dir.exists() and required.issubset({p.name for p in packaged_package_dir.iterdir()}):
            ok("packaged handoff sample data")
            return
        fail("baseline handoff package missing: " + str(package_dir))

    packages = sorted(package_dir.glob("novels/*/chapters/*/framework_package.json"))
    if len(packages) != 18:
        fail(f"expected 18 baseline framework_package files, found {len(packages)}")

    shape_counts = {}
    normalized_compact = 0
    for package in packages:
        data = json.loads(package.read_text(encoding="utf-8"))
        shape = data.get("shape_variant", "")
        shape_counts[shape] = shape_counts.get(shape, 0) + 1
        if shape == "compact_content_only":
            normalized = normalize_framework_package(data)
            issues = validate_rich_like(normalized)
            if issues:
                fail("normalizer issues in " + str(package.relative_to(STORY_DIR)) + ": " + "; ".join(issues))
            normalized_compact += 1

    expected = {"rich_components": 9, "compact_content_only": 9}
    if shape_counts != expected:
        fail("unexpected baseline shape counts: " + json.dumps(shape_counts, ensure_ascii=False))

    for summary_path in package_dir.glob("novels/*/validation_summary.json"):
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        if data.get("blocking_issues"):
            fail("blocking issues in " + str(summary_path.relative_to(STORY_DIR)))
    ok(f"baseline handoff package integrity; compact normalized={normalized_compact}")


def check_sorting_utility() -> None:
    sys.path.insert(0, str(BACKEND_DIR))
    sys.path.insert(0, str(CODE_DIR))
    from story_analyzer_utils import chapter_sort_key, clean_chapter_title

    files = [Path("第四幕.txt"), Path("第二幕.txt"), Path("第一幕.txt"), Path("第三幕.txt"), Path("序幕.txt")]
    ordered = [p.name for p in sorted(files, key=chapter_sort_key)]
    expected = ["序幕.txt", "第一幕.txt", "第二幕.txt", "第三幕.txt", "第四幕.txt"]
    if ordered != expected:
        fail("drama chapter ordering failed: " + str(ordered))

    long_title = "连续工作了两个多月，我实在累了，便请求主任给我两天假，出去短暂旅游一下散散心。主任答应了，条件是我再带一双眼睛去。"
    if clean_chapter_title(long_title, 1) != "第1章":
        fail("long body title cleanup failed")
    ok("chapter sorting and title cleanup utility")


def main() -> None:
    check_directory_layout()
    check_gitignore()
    check_no_secrets()
    check_python_syntax()
    check_handoff_package()
    check_sorting_utility()
    print("TAKEOVER_VERIFICATION_PASSED")


if __name__ == "__main__":
    main()
