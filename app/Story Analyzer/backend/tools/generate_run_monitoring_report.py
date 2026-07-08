#!/usr/bin/env python3
"""Generate UTF-8 run monitoring reports for Story Analyzer web runs."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
CODE_DIR = BACKEND_DIR.parent
DATA_DIR = CODE_DIR / "data"
_PARENT_STORY_DIR = CODE_DIR.parent


def _has_story_workspace_layout(path: Path) -> bool:
    return all(
        (path / name).exists()
        for name in ("03_Analysis_Outputs", "04_Handoff_Packages", "05_Comparison_Reports")
    )


IS_PACKAGED_LAYOUT = not _has_story_workspace_layout(_PARENT_STORY_DIR)
STORY_DIR = CODE_DIR if IS_PACKAGED_LAYOUT else _PARENT_STORY_DIR
DEFAULT_REPORT_DIR = (
    DATA_DIR / "reports" / "Run_Monitoring"
    if IS_PACKAGED_LAYOUT
    else STORY_DIR / "05_Comparison_Reports" / "Run_Monitoring"
)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _registry_contract_issues(registry: dict) -> list[dict]:
    issues: list[dict] = []
    for item in registry.get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "resolved":
            continue
        bad_fields = [
            field
            for field in ("open_questions", "partial_resolution_chapters", "last_partial_resolution_chapter")
            if item.get(field)
        ]
        if item.get("resolution_scope") == "series":
            bad_fields.append("resolution_scope=series")
        if bad_fields:
            issues.append(
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "bad_fields": bad_fields,
                    "summary": item.get("summary") or item.get("canonical_content") or item.get("text") or "",
                }
            )
    return issues


def _bullet_lines(items: list, *, empty: str = "无") -> list[str]:
    if not items:
        return [f"- {empty}"]
    return [f"- `{item}`" if isinstance(item, str) else f"- `{json.dumps(item, ensure_ascii=False)}`" for item in items]


def build_run_monitoring_report(output_dir: str | Path) -> str:
    output = Path(output_dir)
    manifest = _read_json(output / "run_manifest.json")
    ledger = _read_json(output / "llm_calls" / "index.json")
    registry = _read_json(output / "foreshadowing_registry.json")
    contract_issues = _registry_contract_issues(registry)

    recovered_targets = manifest.get("llm_recovered_targets") or ledger.get("llm_recovered_targets") or []
    failed_targets = manifest.get("llm_failed_targets") or ledger.get("llm_failed_targets") or []
    missing_outputs = manifest.get("missing_required_outputs") or []
    failed_arcs = manifest.get("failed_arcs") or []

    lines = [
        f"# 运行质量监视报告",
        "",
        f"- 运行目录：`{output}`",
        f"- 生成时间：{_dt.datetime.now().isoformat(timespec='seconds')}",
        f"- 最终状态：`{manifest.get('run_status') or 'unknown'}`",
        f"- 模型：`{manifest.get('model_provider') or 'unknown'} / {manifest.get('model') or 'unknown'}`",
        f"- downstream：`{manifest.get('downstream_status') or 'unknown'}`",
        f"- downstream_blocked_reason：`{manifest.get('downstream_blocked_reason') or ''}`",
        "",
        "## 规模与完成度",
        "",
        f"- source_total_chapters：`{manifest.get('source_total_chapters')}`",
        f"- analysis_unit_count：`{manifest.get('analysis_unit_count')}`",
        f"- successful_chapter_count：`{manifest.get('successful_chapter_count')}`",
        f"- failed_chapter_count：`{manifest.get('failed_chapter_count')}`",
        f"- arc_count：`{manifest.get('arc_count')}`",
        f"- expected_arc_count：`{manifest.get('expected_arc_count')}`",
        f"- failed_arc_count：`{manifest.get('failed_arc_count')}`",
        "",
        "## LLM 调用恢复状态",
        "",
        f"- llm_attempt_failed_call_count：`{manifest.get('llm_attempt_failed_call_count', ledger.get('llm_attempt_failed_call_count'))}`",
        f"- recovered_retry_count：`{manifest.get('llm_recovered_target_count', ledger.get('llm_recovered_target_count'))}`",
        f"- failed_unrecovered_count：`{manifest.get('llm_unrecovered_failed_target_count', ledger.get('llm_unrecovered_failed_target_count'))}`",
        "",
        "### recovered_retry targets",
        "",
        *_bullet_lines(recovered_targets),
        "",
        "### failed_unrecovered targets",
        "",
        *_bullet_lines(failed_targets),
        "",
        "## 失败目标与缺失产物",
        "",
        "### failed_arcs",
        "",
        *_bullet_lines(failed_arcs),
        "",
        "### missing_required_outputs",
        "",
        *_bullet_lines(missing_outputs),
        "",
        "## 伏笔 Registry 契约检查",
        "",
        f"- items：`{len(registry.get('items') or [])}`",
        f"- semantic_contract_error_count：`{len(registry.get('semantic_contract_errors') or [])}`",
        f"- resolved_state_contradiction_count：`{len(contract_issues)}`",
        "",
    ]
    if contract_issues:
        lines.extend(_bullet_lines(contract_issues))
        lines.append("")
    lines.extend(
        [
            "## 状态口径",
            "",
            "- `recovered_retry`：中间调用失败但后续重试成功，不计入最终失败。",
            "- `failed_unrecovered`：该 target 最终仍失败，会阻断对应 downstream。",
            "- `missing_required_outputs`：本轮最终缺失、不能交给生成器消费的关键产物。",
            "",
        ]
    )
    return "\n".join(lines)


def write_run_monitoring_report(
    output_dir: str | Path,
    report_dir: str | Path | None = None,
    *,
    label: str | None = None,
) -> Path:
    output = Path(output_dir)
    target_dir = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    run_label = label or output.parent.name or output.name
    safe_label = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in run_label).strip("_") or "run"
    filename = f"{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label}_运行质量监视报告.md"
    report_path = target_dir / filename
    report_path.write_text(build_run_monitoring_report(output), encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a UTF-8 Story Analyzer run monitoring report.")
    parser.add_argument("output_dir", help="Path to a Story Analyzer output directory.")
    parser.add_argument("--report-dir", default=None, help="Directory for the generated Markdown report.")
    parser.add_argument("--label", default=None, help="Optional report filename label.")
    args = parser.parse_args()
    path = write_run_monitoring_report(args.output_dir, args.report_dir, label=args.label)
    print(path)


if __name__ == "__main__":
    main()
