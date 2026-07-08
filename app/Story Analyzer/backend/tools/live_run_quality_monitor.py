#!/usr/bin/env python3
"""Live quality monitor for a Story Analyzer web run.

This tool is intentionally read-only for analyzer outputs. It writes a separate
Markdown monitoring report under 05_Comparison_Reports/Run_Monitoring.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
CODE_DIR = BACKEND_DIR.parent
for import_root in (str(BACKEND_DIR), str(CODE_DIR)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from story_analyzer_v1.audit.llm_call_logger import classify_llm_health
from story_analyzer_v1.abstraction.source_leak_validator import validate_source_leaks


INTERNAL_MARKERS = ("[NEW_TERM]", "NEW_TERM")
STANDARD_FORESHADOWING_STATUSES = {"planted", "partially_resolved", "resolved"}
REQUIRED_CHAPTER_FIELDS = ("summary", "chapter_function")
READER_FIELDS = ("reader_emotion", "reader_experience")


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _compact(obj: Any, limit: int = 1200) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(obj)
    return text if len(text) <= limit else text[:limit] + "..."


def _first_present(*values, default=0):
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _llm_health_from_manifest_or_ledger(manifest: dict, ledger: dict, final_state: bool) -> dict:
    if manifest.get("llm_health_status") == "recovered_with_fallback":
        return {
            "status": "recovered_with_fallback",
            "label": manifest.get("llm_health_label") or "已降级恢复",
            "severity": manifest.get("llm_health_severity") or "warning",
            "css_class": "warn",
            "message": manifest.get("llm_health_message") or "LLM target 失败后已用本地降级产物恢复。",
        }
    return classify_llm_health(
        recovered_target_count=_first_present(
            manifest.get("llm_recovered_target_count"), ledger.get("llm_recovered_target_count")
        ),
        unrecovered_failed_target_count=_first_present(
            manifest.get("llm_unrecovered_failed_target_count"), ledger.get("llm_unrecovered_failed_target_count")
        ),
        attempt_failed_call_count=_first_present(
            manifest.get("llm_attempt_failed_call_count"), ledger.get("llm_attempt_failed_call_count")
        ),
        final_state=final_state,
    )


class RunQualityMonitor:
    def __init__(self, run_root: Path, report_dir: Path, poll_seconds: int = 25) -> None:
        self.run_root = run_root
        self.output_dir = run_root / "output"
        self.report_dir = report_dir
        self.poll_seconds = poll_seconds
        self.started_at = _now()
        self.last_seen_sizes: dict[str, int] = {}
        self.seen_files: set[str] = set()
        self.issues: list[dict[str, Any]] = []
        self.issue_keys: set[tuple[str, str, str, str]] = set()
        self.events: list[dict[str, str]] = []
        self.event_keys: set[tuple[str, str]] = set()
        self.last_report_path = ""

    def event(self, kind: str, message: str) -> None:
        item = {"time": _now(), "kind": kind, "message": message}
        self.events.append(item)
        print(f"[{item['time']}] {kind}: {message}", flush=True)

    def event_once(self, kind: str, message: str) -> None:
        key = (kind, message[:500])
        if key in self.event_keys:
            return
        self.event_keys.add(key)
        self.event(kind, message)

    def issue(
        self,
        severity: str,
        category: str,
        title: str,
        evidence: str = "",
        root_cause: str = "",
        recommendation: str = "",
    ) -> None:
        rolling_log_categories = {"external_api_retry", "failure_log_signal"}
        evidence_key = "" if category in rolling_log_categories else evidence[:500]
        key = (severity, category, title, evidence_key)
        if key in self.issue_keys:
            return
        self.issue_keys.add(key)
        item = {
            "time": _now(),
            "severity": severity,
            "category": category,
            "title": title,
            "evidence": evidence,
            "root_cause": root_cause,
            "recommendation": recommendation,
        }
        self.issues.append(item)
        print(f"[{item['time']}] ISSUE {severity}/{category}: {title}", flush=True)

    def read_json(self, path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.issue(
                "P1",
                "json_parse_error",
                f"JSON 读取失败：{path.name}",
                f"{path}\n{exc!r}",
                "文件可能正在写入中、被截断，或分析器落盘未采用原子写。",
            )
            return None

    @staticmethod
    def read_text(path: Path, max_chars: int | None = None) -> str:
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[-max_chars:] if max_chars else text
        except Exception as exc:
            return f"<read failed: {exc}>"

    def counts(self) -> dict[str, Any]:
        chapters = self.output_dir / "chapters"
        arcs = self.output_dir / "arcs"
        return {
            "chapter_analysis": len(list(chapters.glob("chapter_*_analysis.json"))) if chapters.exists() else 0,
            "chapter_framework": len(list(chapters.glob("chapter_*_framework.json"))) if chapters.exists() else 0,
            "chapter_next_pack": len(list(chapters.glob("chapter_*_next_pack.json"))) if chapters.exists() else 0,
            "arcs": len(list(arcs.glob("arc_*.json"))) if arcs.exists() else 0,
            "manifest": (self.output_dir / "run_manifest.json").exists(),
            "book": (self.output_dir / "book_framework.json").exists(),
            "profiles": (self.output_dir / "generation_profiles.json").exists(),
            "bundle": (self.output_dir / "full_book_bundle.json").exists(),
        }

    def inspect_logs(self) -> None:
        manifest = self.read_json(self.output_dir / "run_manifest.json") or {}
        web_job = self.read_json(self.output_dir / "web_job.json") or {}
        ledger = self.read_json(self.output_dir / "llm_calls" / "index.json") or {}
        run_status = str(manifest.get("run_status") or "").lower()
        job_status = str(web_job.get("status") or "").lower()
        final_state = run_status in {"completed", "partial", "failed"} or job_status in {
            "completed",
            "partial",
            "failed",
            "finished",
            "stale",
        }
        llm_health = _llm_health_from_manifest_or_ledger(manifest, ledger, final_state)
        for name in ("progress.log", "web_stdout.log", "web_stderr.log"):
            path = self.output_dir / name
            if not path.exists():
                continue
            size = path.stat().st_size
            old = self.last_seen_sizes.get(str(path), 0)
            if size <= old:
                continue
            self.last_seen_sizes[str(path)] = size
            tail = self.read_text(path, 12000)
            lower = tail.lower()
            if any(token in lower for token in ("traceback", "jsondecodeerror", "exception")):
                self.issue(
                    "P1",
                    "runtime_exception",
                    f"{name} 出现异常堆栈/解析错误",
                    tail[-2500:],
                    "运行期异常可能来自 JSON repair、输出文件解析、或模型响应结构变化。",
                )
            if any(
                token in lower
                for token in ("502", "bad gateway", "proxyerror", "remotedisconnected", "connection reset", "timeout")
            ):
                if final_state and llm_health["status"] in {"healthy", "recovered_with_retries", "recovered_with_fallback"}:
                    self.event_once(
                        "external_api_retry_recovered",
                        f"{name} 出现外部 API/网络失败信号，但最终 LLM health={llm_health['status']}。",
                    )
                else:
                    self.issue(
                        "P2",
                        "external_api_retry",
                        f"{name} 出现外部 API/网络失败信号",
                        tail[-2500:],
                        "外部模型或代理稳定性问题；如果最终恢复，应作为 recovered_retry 而不是最终失败。",
                        "继续观察 llm ledger 是否存在 failed_unrecovered target。",
                    )
            if "failed" in lower or "失败" in tail:
                if final_state and llm_health["status"] in {"healthy", "recovered_with_retries", "recovered_with_fallback"}:
                    self.event_once(
                        "failure_log_signal_recovered",
                        f"{name} 出现失败字样，但最终 LLM health={llm_health['status']}。",
                    )
                else:
                    self.issue(
                        "P2",
                        "failure_log_signal",
                        f"{name} 出现失败字样",
                        tail[-2500:],
                        "需要结合 manifest/ledger 判断是中间重试、最终失败，还是普通日志文本。",
                    )

    def inspect_web_job_and_manifest(self) -> tuple[dict[str, Any], dict[str, Any]]:
        web_job = self.read_json(self.output_dir / "web_job.json") or {}
        manifest = self.read_json(self.output_dir / "run_manifest.json") or {}
        if manifest:
            status = str(manifest.get("run_status") or "")
            if status in {"partial", "failed"}:
                self.issue(
                    "P0" if status == "failed" else "P1",
                    "run_incomplete",
                    f"run_manifest 显示 {status}",
                    _compact(
                        {
                            key: manifest.get(key)
                            for key in (
                                "run_status",
                                "downstream_status",
                                "downstream_blocked_reason",
                                "failed_chapter_count",
                                "failed_arc_count",
                                "missing_required_outputs",
                                "failed_stage_targets",
                            )
                        },
                        2500,
                    ),
                    "完整 downstream 产物未生成或流程被阻断。",
                )
            if manifest.get("run_status") in {"completed", "partial"} and web_job.get("status") == "running":
                self.issue(
                    "P1",
                    "web_job_stale",
                    "web_job 仍 running，但 manifest 已结束",
                    _compact({"web_job": web_job, "manifest_status": manifest.get("run_status")}, 2500),
                    "后台 watcher 同步失效会导致前端一直加载。",
                )
        return web_job, manifest

    def inspect_llm(self) -> dict[str, Any]:
        ledger = self.read_json(self.output_dir / "llm_calls" / "index.json") or {}
        if not ledger:
            return ledger
        web_job = self.read_json(self.output_dir / "web_job.json") or {}
        manifest = self.read_json(self.output_dir / "run_manifest.json") or {}
        run_status = str(manifest.get("run_status") or "").lower()
        job_status = str(web_job.get("status") or "").lower()
        final_state = run_status in {"completed", "partial", "failed"} or job_status in {
            "completed",
            "partial",
            "failed",
            "finished",
            "stale",
        }
        failed = ledger.get("llm_failed_targets") or []
        recovered = ledger.get("llm_recovered_targets") or []
        if failed:
            if final_state:
                self.issue(
                    "P0",
                    "llm_unrecovered_failure",
                    "存在最终未恢复 LLM target",
                    _compact(failed, 2500),
                    "某个章节/弧段/全书 target 最终未成功，会导致 partial 或产物缺失。",
                    "同目录 resume 应只补失败 target。",
                )
            else:
                self.issue(
                    "P2",
                    "llm_pending_failed_attempt",
                    "运行中存在待恢复 LLM failed target",
                    _compact(failed, 2500),
                    "ledger 在运行中会把当前失败尝试记为 failed；后续重试可能恢复，不能提前当成最终 P0。",
                    "最终以 run_manifest 和 llm_unrecovered_failed_target_count 为准。",
                )
        if recovered:
            self.event_once(
                "llm_recovered_retry",
                _compact({"count": len(recovered), "targets": recovered[:30]}, 2500),
            )
        return ledger

    def new_files(self, pattern: str) -> list[Path]:
        files = sorted(self.output_dir.glob(pattern))
        new: list[Path] = []
        for path in files:
            key = str(path)
            if key not in self.seen_files:
                self.seen_files.add(key)
                new.append(path)
        return new

    def inspect_chapter(self, path: Path) -> None:
        data = self.read_json(path)
        if not isinstance(data, dict):
            return
        text = json.dumps(data, ensure_ascii=False)
        hits = [marker for marker in INTERNAL_MARKERS if marker in text]
        if hits:
            self.issue(
                "P1",
                "internal_marker_leak",
                f"章节输出泄露内部标记：{path.name}",
                ", ".join(hits),
                "内部术语标记清理未覆盖该输出层。",
            )
        chapter = data.get("chapter_analysis") or data.get("chapter") or {}
        if not isinstance(chapter, dict):
            self.issue(
                "P1",
                "chapter_schema_missing",
                f"章节缺少 chapter_analysis：{path.name}",
                _compact(list(data.keys())),
                "章节适配器或 JSON repair 未统一 schema。",
            )
            return
        missing = [field for field in REQUIRED_CHAPTER_FIELDS if not chapter.get(field)]
        if not any(chapter.get(field) for field in READER_FIELDS):
            missing.append("reader_emotion|reader_experience")
        if missing:
            self.issue(
                "P1",
                "chapter_core_fields_missing",
                f"章节核心字段缺失：{path.name}",
                ", ".join(missing),
                "章节 prompt/fallback 未稳定产出生成器需要的核心字段。",
            )
        foreshadowing = data.get("foreshadowing")
        delta = data.get("foreshadowing_delta")
        snapshot = data.get("known_foreshadowing_snapshot")
        if (
            isinstance(foreshadowing, list)
            and isinstance(snapshot, list)
            and len(snapshot) >= 20
            and len(foreshadowing) >= len(snapshot) * 0.8
        ):
            self.issue(
                "P1",
                "foreshadowing_cumulative_field",
                f"章节 foreshadowing 疑似累计：{path.name}",
                _compact(
                    {
                        "foreshadowing": len(foreshadowing),
                        "snapshot": len(snapshot),
                        "delta": len(delta) if isinstance(delta, list) else None,
                    }
                ),
                "章节级字段可能混入 snapshot，生成器会误判每章都有大量新伏笔。",
            )
        summary = str(chapter.get("summary") or "")
        if len(summary) > 300 and not chapter.get("plot_nodes"):
            self.issue(
                "P2",
                "chapter_summary_no_plot_nodes",
                f"章节摘要较长但 plot_nodes 为空：{path.name}",
                summary[:800],
                "章节分析偏概括，缺少事件节点，篇章 framework 可执行性下降。",
            )

    def inspect_arc(self, path: Path) -> None:
        data = self.read_json(path)
        if not isinstance(data, dict):
            return
        text = json.dumps(data, ensure_ascii=False)
        hits = [marker for marker in INTERNAL_MARKERS if marker in text]
        if hits:
            self.issue(
                "P1",
                "internal_marker_leak",
                f"弧段输出泄露内部标记：{path.name}",
                ", ".join(hits),
                "弧段层清理未覆盖。",
            )
        if not data.get("source_chapter_range") and not data.get("source_chapters"):
            self.issue(
                "P1",
                "arc_source_mapping_missing",
                f"弧段缺少源章节归属：{path.name}",
                _compact(
                    {
                        key: data.get(key)
                        for key in ("arc_index", "arc_chapter_range", "analysis_unit_range", "source_chapter_range")
                    }
                ),
                "弧段层可能仍用内部 analysis unit 口径，对 UI 和生成器不友好。",
            )
        if not (data.get("arc_summary") or data.get("summary")):
            self.issue(
                "P1",
                "arc_summary_missing",
                f"弧段缺少摘要：{path.name}",
                _compact(list(data.keys())),
                "弧段 prompt/适配器未稳定输出核心字段。",
            )

    def inspect_registry(self) -> None:
        registry = self.read_json(self.output_dir / "foreshadowing_registry.json")
        if not isinstance(registry, dict):
            return
        items = registry.get("items") or []
        if registry.get("semantic_contract_errors"):
            self.issue(
                "P1",
                "foreshadowing_contract_errors",
                "伏笔 registry 存在 semantic_contract_errors",
                _compact(registry.get("semantic_contract_errors")[:30], 3000),
                "最终一致性 pass 没有完全兜住模型/合并层的语义矛盾。",
            )
        bad_status = [
            {"id": item.get("id"), "status": item.get("status")}
            for item in items
            if isinstance(item, dict) and item.get("status") not in STANDARD_FORESHADOWING_STATUSES
        ]
        if bad_status:
            self.issue(
                "P1",
                "foreshadowing_status_enum",
                "伏笔 registry 存在非标准状态",
                _compact(bad_status[:30]),
                "状态枚举归一不足。",
            )
        contradictions = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "resolved":
                bad = [
                    key
                    for key in ("open_questions", "partial_resolution_chapters", "last_partial_resolution_chapter")
                    if item.get(key)
                ]
                if item.get("resolution_scope") == "series":
                    bad.append("resolution_scope=series")
                if bad:
                    contradictions.append(
                        {
                            "id": item.get("id"),
                            "bad_fields": bad,
                            "summary": item.get("summary") or item.get("canonical_content"),
                        }
                    )
        if contradictions:
            self.issue(
                "P1",
                "foreshadowing_state_contradiction",
                "resolved 伏笔仍带阶段性字段",
                _compact(contradictions[:30], 3000),
                "registry 落盘前一致性 pass 或后续 bundle 合并层重新引入矛盾。",
            )
        groups: dict[str, list[Any]] = defaultdict(list)
        for item in items:
            if not isinstance(item, dict):
                continue
            content = str(item.get("canonical_content") or item.get("summary") or item.get("text") or "").lower().strip()
            norm = re.sub(r"[\s，。、“”‘’：:,.!！?？\-—_]+", "", content)
            if len(norm) > 8:
                groups[norm].append(item.get("id"))
        dupes = [{"ids": ids, "norm_prefix": norm[:80]} for norm, ids in groups.items() if len(ids) > 1]
        if dupes:
            self.issue(
                "P2",
                "foreshadowing_duplicate",
                "伏笔 registry 存在近完全重复项",
                _compact(dupes[:20], 2500),
                "canonical 去重仍有缺口，生成器记忆可能膨胀。",
            )

    def _current_registry_bad_status(self) -> list[dict[str, Any]]:
        registry = self.read_json(self.output_dir / "foreshadowing_registry.json")
        if not isinstance(registry, dict):
            return []
        items = registry.get("items") or []
        return [
            {"id": item.get("id"), "status": item.get("status")}
            for item in items
            if isinstance(item, dict) and item.get("status") not in STANDARD_FORESHADOWING_STATUSES
        ]

    def _final_report_issues(
        self,
        *,
        final_state: bool,
        manifest: dict[str, Any],
        ledger: dict[str, Any],
        llm_health: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues = list(self.issues)
        if not final_state:
            return issues

        unrecovered_count = int(
            _first_present(
                manifest.get("llm_unrecovered_failed_target_count"),
                ledger.get("llm_unrecovered_failed_target_count"),
                default=0,
            )
            or 0
        )
        failed_targets = manifest.get("llm_failed_targets") or ledger.get("llm_failed_targets") or []
        if unrecovered_count == 0 and not failed_targets:
            recovered_categories = {"llm_pending_failed_attempt", "external_api_retry"}
            issues = [item for item in issues if item.get("category") not in recovered_categories]

        if not self._current_registry_bad_status():
            issues = [item for item in issues if item.get("category") != "foreshadowing_status_enum"]

        if llm_health.get("status") in {"healthy", "recovered_with_retries", "recovered_with_fallback"}:
            issues = [item for item in issues if item.get("category") != "failure_log_signal"]

        return issues

    @staticmethod
    def _recovered_retry_summary(manifest: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
        recovered_targets = manifest.get("llm_recovered_targets") or ledger.get("llm_recovered_targets") or []
        if not isinstance(recovered_targets, list):
            recovered_targets = []
        recovered_count = _first_present(
            manifest.get("llm_recovered_target_count"),
            ledger.get("llm_recovered_target_count"),
            default=len(recovered_targets),
        )
        attempt_failed_count = _first_present(
            manifest.get("llm_attempt_failed_call_count"),
            ledger.get("llm_attempt_failed_call_count"),
            default=0,
        )
        stages = sorted(
            {
                str(item.get("stage"))
                for item in recovered_targets
                if isinstance(item, dict) and item.get("stage")
            }
        )
        target_ids = [
            str(item.get("target_id"))
            for item in recovered_targets
            if isinstance(item, dict) and item.get("target_id")
        ]
        return {
            "llm_recovered_target_count": int(recovered_count or 0),
            "llm_attempt_failed_call_count": int(attempt_failed_count or 0),
            "recovered_stages": stages,
            "recovered_target_ids": target_ids,
        }

    def _revalidate_structure_source_leak(self, profiles: dict) -> dict | None:
        usage_profiles = profiles.get("usage_profiles") or {}
        structure_only = usage_profiles.get("structure_only") or {}
        if not isinstance(structure_only, dict):
            return None
        inventory = self.read_json(self.output_dir / "source_entity_inventory.json")
        if not isinstance(inventory, dict):
            inventory = structure_only.get("_source_entity_inventory")
        if not isinstance(inventory, dict):
            return None
        return validate_source_leaks(structure_only, inventory)

    def inspect_final_outputs(self) -> None:
        manifest = self.read_json(self.output_dir / "run_manifest.json") or {}
        book = self.read_json(self.output_dir / "book_framework.json")
        if isinstance(book, dict) and manifest:
            if book.get("total_chapters") != manifest.get("source_total_chapters"):
                self.issue(
                    "P1",
                    "book_chapter_count_basis",
                    "book_framework.total_chapters 与源章节数不一致",
                    _compact(
                        {
                            "book_total_chapters": book.get("total_chapters"),
                            "source_total_chapters": manifest.get("source_total_chapters"),
                            "analysis_unit_count": manifest.get("analysis_unit_count"),
                        }
                    ),
                    "全书层可能误用 analysis unit 口径。",
                )
        profiles = self.read_json(self.output_dir / "generation_profiles.json")
        if isinstance(profiles, dict):
            text = json.dumps(profiles, ensure_ascii=False)
            hits = [marker for marker in INTERNAL_MARKERS if marker in text]
            if hits:
                self.issue(
                    "P1",
                    "generation_profile_marker_leak",
                    "generation_profiles 泄露内部标记",
                    ", ".join(hits),
                    "最终 profile 清理未覆盖。",
                )
            if not profiles.get("arc_hierarchy"):
                self.issue(
                    "P1",
                    "arc_hierarchy_missing",
                    "generation_profiles 缺少 arc_hierarchy",
                    _compact(list(profiles.keys())),
                    "major/sub arc 层级未落地，生成器宏观结构输入不足。",
                )
            leak = profiles.get("source_leak_report") or (profiles.get("usage_profiles") or {}).get(
                "structure_only", {}
            ).get("source_leak_report") or {}
            if isinstance(leak, dict):
                count = (
                    leak.get("total_leak_count")
                    or leak.get("leak_count")
                    or (
                        int(leak.get("blocking_leak_count") or 0)
                        + int(leak.get("warning_leak_count") or 0)
                    )
                    or len(leak.get("leaks") or [])
                )
                try:
                    leak_count = int(count)
                except Exception:
                    leak_count = 0
                if leak_count > 0 or str(leak.get("status") or "").lower() == "failed":
                    leak_revalidated = False
                    revalidated = self._revalidate_structure_source_leak(profiles)
                    if isinstance(revalidated, dict) and str(revalidated.get("status") or "").lower() == "passed":
                        self.event_once(
                            "structure_only_source_leak_revalidated",
                            "历史嵌入 source_leak_report 为 failed，但当前检测器只读重算已通过。",
                        )
                        leak_revalidated = True
                    if not leak_revalidated:
                        self.issue(
                            "P1",
                            "structure_only_source_leak",
                            "structure_only 存在专名/源文本泄露",
                            _compact(leak, 3000),
                            "去专名化/抽象机制不足，会污染第一类原创用户的结构框架。",
                        )
        bundle = self.read_json(self.output_dir / "full_book_bundle.json")
        if isinstance(bundle, dict):
            missing = [
                key
                for key in ("book_framework", "generation_profiles", "foreshadowing_registry", "chapters", "arcs")
                if key not in bundle
            ]
            if missing:
                self.issue(
                    "P1",
                    "bundle_contract_missing",
                    "full_book_bundle 缺少关键字段",
                    _compact(missing),
                    "handoff bundle 契约不完整。",
                )

    def write_report(self, final: bool = False) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        web_job = self.read_json(self.output_dir / "web_job.json") or {}
        manifest = self.read_json(self.output_dir / "run_manifest.json") or {}
        ledger = self.read_json(self.output_dir / "llm_calls" / "index.json") or {}
        run_status = str(manifest.get("run_status") or "").lower()
        job_status = str(web_job.get("status") or "").lower()
        final_state = run_status in {"completed", "partial", "failed"} or job_status in {
            "completed",
            "partial",
            "failed",
            "finished",
            "stale",
        }
        llm_health = _llm_health_from_manifest_or_ledger(manifest, ledger, final_state)
        recovered_summary = self._recovered_retry_summary(manifest, ledger)
        report_issues = self._final_report_issues(
            final_state=final_state,
            manifest=manifest,
            ledger=ledger,
            llm_health=llm_health,
        )
        issue_counts = Counter(item["severity"] for item in report_issues)
        run_label = self.run_root.name or "story_analyzer_run"
        safe_label = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", run_label).strip("_")[:80]
        report_path = self.report_dir / (
            f"{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label or 'story_analyzer_run'}_quality_monitor.md"
        )
        lines = [
            f"# {run_label} 运行质量监视记录",
            "",
            f"- 运行目录：`{self.run_root}`",
            f"- 输出目录：`{self.output_dir}`",
            f"- 监视开始：`{self.started_at}`",
            f"- 报告生成：`{_now()}`",
            f"- final：`{final}`",
            "",
            "## 当前状态",
            "",
            f"- web_job.status：`{web_job.get('status', '')}`",
            f"- pid：`{web_job.get('pid', '')}`",
            f"- model_provider：`{web_job.get('model_provider', '')}`",
            f"- text_length：`{web_job.get('text_length', '')}`",
            f"- run_manifest.run_status：`{manifest.get('run_status', '')}`",
            f"- downstream_status：`{manifest.get('downstream_status', '')}`",
            f"- downstream_blocked_reason：`{manifest.get('downstream_blocked_reason', '')}`",
            f"- source_total_chapters：`{manifest.get('source_total_chapters', '')}`",
            f"- analysis_unit_count：`{manifest.get('analysis_unit_count', '')}`",
            f"- 文件计数：`{json.dumps(self.counts(), ensure_ascii=False)}`",
            "",
            "## LLM 状态",
            "",
        ]
        for key in (
            "llm_call_count",
            "llm_attempt_failed_call_count",
            "llm_recovered_target_count",
            "llm_unrecovered_failed_target_count",
            "source_model_id_conflict_count",
            "source_model_id_alias_collision_count",
        ):
            lines.append(f"- {key}：`{manifest.get(key, ledger.get(key, ''))}`")
        lines.append(f"- llm_health_status：`{llm_health['status']}`")
        lines.append(f"- llm_health_label：`{llm_health['label']}`")
        lines.append(f"- llm_health_message：{llm_health['message']}")
        lines.extend(["", "## 恢复型风险统计", ""])
        lines.append(f"- llm_recovered_target_count：`{recovered_summary['llm_recovered_target_count']}`")
        lines.append(f"- llm_attempt_failed_call_count：`{recovered_summary['llm_attempt_failed_call_count']}`")
        lines.append(f"- recovered_stages：`{', '.join(recovered_summary['recovered_stages'])}`")
        lines.append(f"- recovered_targets：`{', '.join(recovered_summary['recovered_target_ids'][:30])}`")
        if recovered_summary["llm_recovered_target_count"]:
            lines.append("- user_facing_status：`已重试恢复，不是最终失败，但仍是稳定性风险。`")
        else:
            lines.append("- user_facing_status：`未记录恢复型重试。`")
        lines.extend(
            [
                "",
                "## 问题统计",
                "",
                f"- P0：`{issue_counts.get('P0', 0)}`",
                f"- P1：`{issue_counts.get('P1', 0)}`",
                f"- P2：`{issue_counts.get('P2', 0)}`",
                "",
                "## 发现的问题",
                "",
            ]
        )
        if not report_issues:
            if recovered_summary["llm_recovered_target_count"]:
                lines.append("- 未发现阻塞性问题；存在已恢复的 LLM 重试，见「恢复型风险统计」。")
            else:
                lines.append("- 暂未发现明确问题。")
        else:
            for index, item in enumerate(report_issues, start=1):
                lines.extend(
                    [
                        f"### {index}. [{item['severity']}] {item['title']}",
                        "",
                        f"- 时间：`{item['time']}`",
                        f"- 分类：`{item['category']}`",
                    ]
                )
                if item.get("evidence"):
                    lines.extend(["- 证据：", "", "```text", str(item["evidence"])[:5000], "```"])
                if item.get("root_cause"):
                    lines.append(f"- 根因指向：{item['root_cause']}")
                if item.get("recommendation"):
                    lines.append(f"- 建议：{item['recommendation']}")
                lines.append("")
        lines.extend(["## 监视事件", ""])
        for event in self.events[-250:]:
            lines.append(f"- `{event['time']}` `{event['kind']}` {event['message']}")
        lines.append("")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        self.last_report_path = str(report_path)
        return report_path

    @staticmethod
    def process_alive(pid: Any) -> bool:
        if not pid:
            return False
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False

    def finished(self, web_job: dict[str, Any], manifest: dict[str, Any]) -> bool:
        run_status = str((manifest or {}).get("run_status") or "").lower()
        job_status = str((web_job or {}).get("status") or "").lower()
        if run_status in {"completed", "partial", "failed"}:
            return True
        if job_status in {"completed", "partial", "failed", "finished", "stale"}:
            return True
        pid = web_job.get("pid") if web_job else None
        if job_status == "running" and pid and not self.process_alive(pid) and (self.output_dir / "run_manifest.json").exists():
            self.issue(
                "P1",
                "web_job_process_dead",
                "web_job 显示 running 但 PID 不存在",
                _compact(web_job),
                "后台 watcher 可能没有及时同步状态，前端可能一直加载。",
            )
            return True
        return False

    def pass_once(self) -> tuple[dict[str, Any], dict[str, Any]]:
        web_job, manifest = self.inspect_web_job_and_manifest()
        self.inspect_logs()
        self.inspect_llm()
        for path in self.new_files("chapters/chapter_*_analysis.json"):
            self.inspect_chapter(path)
        for path in self.new_files("arcs/arc_*.json"):
            self.inspect_arc(path)
        self.inspect_registry()
        self.inspect_final_outputs()
        return web_job, manifest

    def run(self) -> Path:
        self.event("monitor_bound", f"绑定运行目录 {self.run_root}")
        last_progress = 0.0
        while True:
            web_job, manifest = self.pass_once()
            if time.time() - last_progress > 60:
                self.event(
                    "progress",
                    _compact(
                        {
                            "counts": self.counts(),
                            "web_status": web_job.get("status"),
                            "run_status": manifest.get("run_status"),
                            "issues": Counter(item["severity"] for item in self.issues),
                        },
                        1000,
                    ),
                )
                self.write_report(final=False)
                last_progress = time.time()
            if self.finished(web_job, manifest):
                self.event(
                    "run_finished",
                    _compact(
                        {
                            "counts": self.counts(),
                            "web_status": web_job.get("status"),
                            "run_status": manifest.get("run_status"),
                        },
                        1000,
                    ),
                )
                time.sleep(8)
                self.pass_once()
                path = self.write_report(final=True)
                self.event("report_written", str(path))
                print(f"FINAL_REPORT={path}", flush=True)
                return path
            time.sleep(self.poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor a Story Analyzer web run and write a quality report.")
    parser.add_argument("--run-root", required=True, help="Path to web run root directory.")
    parser.add_argument("--report-dir", required=True, help="Directory to write monitoring reports.")
    parser.add_argument("--poll-seconds", type=int, default=25)
    args = parser.parse_args()
    monitor = RunQualityMonitor(Path(args.run_root), Path(args.report_dir), poll_seconds=args.poll_seconds)
    monitor.run()


if __name__ == "__main__":
    main()
