"""Safe LLM call ledger.

The ledger records call metadata for auditability without storing API keys,
full prompts, or full source text.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import time
from collections import Counter, OrderedDict
from pathlib import Path


def _sha256(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _safe_file_part(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "unknown")).strip("_").lower()
    return value[:48] or "unknown"


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def classify_llm_health(
    *,
    recovered_target_count=0,
    unrecovered_failed_target_count=0,
    attempt_failed_call_count=0,
    final_state: bool = True,
) -> dict:
    recovered = _as_int(recovered_target_count)
    unrecovered = _as_int(unrecovered_failed_target_count)
    failed_attempts = _as_int(attempt_failed_call_count)
    if unrecovered > 0:
        if final_state:
            return {
                "status": "failed_unrecovered",
                "label": "未恢复失败",
                "severity": "error",
                "css_class": "bad",
                "message": f"{unrecovered} 个 LLM target 最终未恢复，需要续跑或人工处理。",
            }
        return {
            "status": "pending_retry",
            "label": "等待重试恢复",
            "severity": "warning",
            "css_class": "warn",
            "message": f"{unrecovered} 个 LLM target 当前失败，运行未结束，后续重试仍可能恢复。",
        }
    if recovered > 0:
        return {
            "status": "recovered_with_retries",
            "label": "已重试恢复",
            "severity": "warning",
            "css_class": "warn",
            "message": f"{recovered} 个 LLM target 曾失败但最终恢复，输出完整；这是稳定性信号，不是最终失败。",
        }
    if failed_attempts > 0 and not final_state:
        return {
            "status": "retrying",
            "label": "正在重试",
            "severity": "info",
            "css_class": "missing",
            "message": f"已记录 {failed_attempts} 次失败尝试，运行仍在继续。",
        }
    return {
        "status": "healthy",
        "label": "正常",
        "severity": "ok",
        "css_class": "ok",
        "message": "未发现 LLM 未恢复失败或已恢复重试。",
    }


class LlmCallLogger:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path = self.directory / "index.json"
        self.entries: list[dict] = []
        self._counter = 0
        self._write_index()

    def _next_id(self) -> str:
        self._counter += 1
        return f"call_{self._counter:04d}"

    def record_call(
        self,
        *,
        stage: str,
        target_id: str,
        provider: str,
        model: str,
        base_url: str,
        api_key_env: str,
        prompt_version: str,
        system_prompt: str,
        user_prompt: str,
        request: dict,
        response: dict | None,
        error: str | None,
        started_at: float | None = None,
        finished_at: float | None = None,
        repair_call_id: str | None = None,
    ) -> dict:
        started = started_at or time.time()
        finished = finished_at or time.time()
        call_id = self._next_id()
        file_name = f"{call_id}_{_safe_file_part(stage)}_{_safe_file_part(target_id)}.json"
        raw_text = str((response or {}).get("raw_text") or "")
        entry = {
            "call_id": call_id,
            "stage": stage,
            "target_id": target_id,
            "provider": provider,
            "model": model,
            "base_url_hash": _sha256(base_url),
            "api_key_env": api_key_env,
            "prompt_version": prompt_version,
            "system_prompt_sha256": _sha256(system_prompt),
            "system_prompt_length": len(str(system_prompt or "")),
            "user_prompt_sha256": _sha256(user_prompt),
            "user_prompt_length": len(str(user_prompt or "")),
            "request": {
                "temperature": request.get("temperature"),
                "max_tokens": request.get("max_tokens"),
            },
            "response": {
                "received": bool((response or {}).get("received")),
                "finish_reason": (response or {}).get("finish_reason", "unknown"),
                "raw_text_sha256": _sha256(raw_text) if raw_text else "",
                "raw_text_length": len(raw_text),
                "json_parse_status": (response or {}).get("json_parse_status", "unknown"),
                "repair_call_id": repair_call_id,
            },
            "timing": {
                "started_at": _dt.datetime.fromtimestamp(started).isoformat(),
                "finished_at": _dt.datetime.fromtimestamp(finished).isoformat(),
                "duration_ms": int(max(0, finished - started) * 1000),
            },
            "error": str(error) if error else None,
        }
        (self.directory / file_name).write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        index_entry = {
            "call_id": call_id,
            "file": file_name,
            "stage": stage,
            "target_id": target_id,
            "provider": provider,
            "model": model,
            "finish_reason": entry["response"]["finish_reason"],
            "json_parse_status": entry["response"]["json_parse_status"],
            "error": bool(error),
        }
        self.entries.append(index_entry)
        self._write_index()
        return index_entry

    def summary(self) -> dict:
        provider_counts: dict[str, int] = {}
        failed_attempts = repair = truncated = 0
        for entry in self.entries:
            provider = entry.get("provider") or "unknown"
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            if entry.get("error"):
                failed_attempts += 1
            if "repair" in str(entry.get("stage") or "") or entry.get("json_parse_status") == "repaired":
                repair += 1
            if entry.get("finish_reason") in {"length", "max_tokens"}:
                truncated += 1

        target_outcomes = self._target_outcomes()
        status_counts = Counter(outcome["status"] for outcome in target_outcomes)
        recovered_targets = [outcome for outcome in target_outcomes if outcome["status"] == "recovered"]
        failed_targets = [outcome for outcome in target_outcomes if outcome["status"] == "failed"]
        summary = {
            "llm_call_ledger_ref": "llm_calls/index.json",
            "llm_call_count": len(self.entries),
            "llm_attempt_failed_call_count": failed_attempts,
            "llm_failed_call_count": len(failed_targets),
            "llm_unrecovered_failed_target_count": len(failed_targets),
            "llm_recovered_target_count": len(recovered_targets),
            "llm_repair_call_count": repair,
            "llm_truncated_call_count": truncated,
            "provider_counts": provider_counts,
            "llm_target_status_counts": {
                "ok": status_counts.get("ok", 0),
                "recovered": status_counts.get("recovered", 0),
                "failed": status_counts.get("failed", 0),
            },
            "llm_recovered_targets": recovered_targets,
            "llm_failed_targets": failed_targets,
        }
        health = classify_llm_health(
            recovered_target_count=summary["llm_recovered_target_count"],
            unrecovered_failed_target_count=summary["llm_unrecovered_failed_target_count"],
            attempt_failed_call_count=summary["llm_attempt_failed_call_count"],
            final_state=True,
        )
        summary.update(
            {
                "llm_health_status": health["status"],
                "llm_health_label": health["label"],
                "llm_health_severity": health["severity"],
                "llm_health_message": health["message"],
            }
        )
        return summary

    def _target_outcomes(self) -> list[dict]:
        grouped: OrderedDict[tuple[str, str], list[dict]] = OrderedDict()
        for entry in self.entries:
            key = (str(entry.get("stage") or "unknown"), str(entry.get("target_id") or "unknown"))
            grouped.setdefault(key, []).append(entry)

        outcomes: list[dict] = []
        for (stage, target_id), entries in grouped.items():
            failed_entries = [entry for entry in entries if entry.get("error")]
            last = entries[-1]
            if last.get("error"):
                status = "failed"
            elif failed_entries:
                status = "recovered"
            else:
                status = "ok"
            outcomes.append(
                {
                    "stage": stage,
                    "target_id": target_id,
                    "status": status,
                    "attempt_count": len(entries),
                    "failed_attempt_count": len(failed_entries),
                    "final_call_id": last.get("call_id"),
                }
            )
        return outcomes

    def _write_index(self) -> None:
        index = {
            "schema_version": "story_analyzer.llm_call_ledger.v1",
            **self.summary(),
            "calls": self.entries,
        }
        self.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
