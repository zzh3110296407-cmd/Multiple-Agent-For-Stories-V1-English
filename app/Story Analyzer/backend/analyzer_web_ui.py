#!/usr/bin/env python3
import argparse
import html
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from story_analyzer_utils import (
    decode_story_text_bytes as _shared_decode_story_text_bytes,
    validate_story_text_quality as _shared_validate_story_text_quality,
)
from story_analyzer_v1.arc_review_editor import (
    build_arc_review_editor,
    confirm_arc_review_edits,
    save_arc_review_edits,
)
from story_analyzer_v1.downstream_rebuild_controls import (
    build_downstream_rebuild_controls,
    run_downstream_rebuild_from_controls,
)
from story_analyzer_v1.evidence.raw_source_index_builder import build_raw_source_index
from story_analyzer_v1.generator_handoff.handoff_repair import repair_generator_handoff
from story_analyzer_v1.generator_handoff.handoff_validator import (
    is_generator_handoff_deliverable,
    validate_generator_handoff,
)
from story_analyzer_v1.handoff.compiler import compile_generator_handoff
from story_analyzer_v1.review_summary import build_review_summary
from story_analyzer_v1.review_reports import build_review_reports, discover_recent_runs
from story_analyzer_v1.audit.llm_call_logger import classify_llm_health


CODE_DIR = Path(__file__).resolve().parent
ANALYZER_CODE_DIR = CODE_DIR.parent
DATA_DIR = ANALYZER_CODE_DIR / "data"
_PARENT_STORY_DIR = ANALYZER_CODE_DIR.parent


def _has_story_workspace_layout(path: Path) -> bool:
    return all(
        (path / name).exists()
        for name in ("03_Analysis_Outputs", "04_Handoff_Packages", "05_Comparison_Reports")
    )


IS_PACKAGED_LAYOUT = not _has_story_workspace_layout(_PARENT_STORY_DIR)
STORY_DIR = ANALYZER_CODE_DIR if IS_PACKAGED_LAYOUT else _PARENT_STORY_DIR
ANALYSIS_RUNS_DIR = DATA_DIR / "analysis_runs" if IS_PACKAGED_LAYOUT else STORY_DIR / "03_Analysis_Outputs" / "analysis_runs"
WEB_RUNS_DIR = DATA_DIR / "web_runs" if IS_PACKAGED_LAYOUT else STORY_DIR / "03_Analysis_Outputs" / "web_runs"
MAX_TEXT_CHARS = 3_000_000
MAX_POST_BYTES = 80_000_000
AUTO_SPLIT_THRESHOLD_CHARS = 25_000
MAX_CONCURRENT_ANALYSIS_JOBS = 1
MODEL_PROVIDER_ENV = "STORY_ANALYZER_MODEL_PROVIDER"
DEEPSEEK_MODEL_NAME = "deepseek-chat"
QWEN_MODEL_NAME = "qwen3.6-35b-a3b-fp8"
SUPPORTED_MODEL_PROVIDERS = {"deepseek", "qwen"}
RUNNING_ANALYSIS_JOBS: dict[str, subprocess.Popen] = {}
RUNNING_ANALYSIS_JOBS_LOCK = threading.Lock()


def _model_key_env(provider: str) -> str:
    return "QWEN_API_KEY" if provider == "qwen" else "DEEPSEEK_API_KEY"


def _load_local_env() -> dict:
    env = dict(os.environ)
    for env_path in (CODE_DIR / ".env", ANALYZER_CODE_DIR / ".env"):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in env:
                env[key] = value
    return env


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #172033;
      --muted: #647084;
      --border: #d8dee8;
      --accent: #1c6b5a;
      --accent-dark: #155145;
      --danger: #a23a3a;
      --code: #f0f3f6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(1120px, calc(100vw - 32px));
      margin: 28px auto 48px;
    }}
    header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .subtle {{ color: var(--muted); margin: 6px 0 0; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 320px;
      gap: 16px;
      align-items: start;
    }}
    label {{
      display: block;
      font-weight: 650;
      margin: 0 0 6px;
    }}
    textarea, input[type="text"], input[type="password"], input[type="file"], select {{
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 12px;
      font: inherit;
      color: var(--text);
      background: white;
    }}
    textarea {{
      min-height: 440px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      line-height: 1.45;
    }}
    .field {{ margin-bottom: 14px; }}
    .hint {{ color: var(--muted); font-size: 12px; margin-top: 5px; }}
    button {{
      width: 100%;
      border: 0;
      border-radius: 6px;
      padding: 11px 14px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }}
    button:hover {{ background: var(--accent-dark); }}
    code, pre {{
      background: var(--code);
      border-radius: 6px;
    }}
    code {{ padding: 2px 5px; }}
    pre {{
      overflow: auto;
      padding: 12px;
      white-space: pre-wrap;
    }}
    .status {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      background: var(--code);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
    }}
    .status.ok {{ background: #d9f0e8; color: #155145; }}
    .status.warn {{ background: #fff0ce; color: #76520f; }}
    .status.bad {{ background: #f8dddd; color: var(--danger); }}
    .status.missing {{ background: #e8edf4; color: var(--muted); }}
    .error {{ color: var(--danger); }}
    .actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .actions .status {{ white-space: nowrap; }}
    .button-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 12px 0;
    }}
    .button-row button {{
      width: auto;
      min-width: 120px;
    }}
    .button-row button.secondary {{ background: #415066; }}
    .button-row button.danger {{ background: var(--danger); }}
    .review-form {{
      display: grid;
      grid-template-columns: 1fr 1fr 160px;
      gap: 12px;
      align-items: end;
      margin-bottom: 16px;
    }}
    .review-form button {{ height: 40px; }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .metric {{
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      padding: 14px;
      min-height: 92px;
    }}
    .metric strong {{
      display: block;
      font-size: 20px;
      line-height: 1.25;
      margin: 6px 0 0;
      overflow-wrap: anywhere;
    }}
    .stack {{
      display: grid;
      gap: 16px;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      align-items: start;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
    }}
    th, td {{
      border-top: 1px solid var(--border);
      padding: 8px 0;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      width: 190px;
      color: var(--muted);
      font-weight: 650;
    }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .empty {{
      color: var(--muted);
      margin: 10px 0 0;
    }}
    .arc-table {{
      min-width: 980px;
    }}
    .arc-table th, .arc-table td {{
      padding: 8px;
      border-top: 1px solid var(--border);
    }}
    .arc-table th {{
      width: auto;
      white-space: nowrap;
    }}
    .arc-table input, .arc-table textarea, .arc-table select {{
      min-width: 120px;
      padding: 7px 8px;
      font-size: 12px;
    }}
    .arc-table textarea {{
      min-height: 64px;
      resize: vertical;
      font-family: inherit;
    }}
    .table-scroll {{
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    ul {{ padding-left: 18px; }}
    @media (max-width: 820px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .review-form, .two-col, .summary-grid {{ grid-template-columns: 1fr; }}
      textarea {{ min-height: 300px; }}
    }}
  </style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>""".encode("utf-8")


def _home(message: str = "") -> bytes:
    env = _load_local_env()
    deepseek_key_status = "configured" if env.get("DEEPSEEK_API_KEY") else "missing"
    qwen_key_status = "configured" if env.get("QWEN_API_KEY") else "missing"
    safe_message = f"<div class='panel'><pre>{html.escape(message)}</pre></div>" if message else ""
    body = f"""
<header>
  <div>
    <h1>故事分析器</h1>
    <p class="subtle">本地运行入口。输出会保存到 <code>{html.escape(str(WEB_RUNS_DIR))}</code>。</p>
  </div>
  <div class="actions">
    <a href="/review" class="status">Review</a>
    <span class="status">DeepSeek {html.escape(DEEPSEEK_MODEL_NAME)}: {html.escape(deepseek_key_status)}</span>
    <span class="status">Qwen {html.escape(QWEN_MODEL_NAME)}: {html.escape(qwen_key_status)}</span>
  </div>
</header>
{safe_message}
<form class="grid" method="post" action="/analyze" enctype="multipart/form-data">
  <section class="panel">
    <div class="field">
      <label for="story_file">上传文本文件</label>
      <input id="story_file" name="story_file" type="file" accept=".txt,.md,text/plain,text/markdown">
      <div class="hint">推荐三百万字长篇使用 .txt/.md 上传。支持 UTF-8、UTF-16、UTF-32、GB18030、GBK、Big5；疑似乱码会在分析前阻止。</div>
    </div>
    <div class="field">
      <label for="story_text">故事文本</label>
      <textarea id="story_text" name="story_text" maxlength="{MAX_TEXT_CHARS}" placeholder="也可以在这里粘贴章节或整本书文本"></textarea>
      <div class="hint">最多 {MAX_TEXT_CHARS:,} 字符。长篇会以后台任务运行，页面会自动轮询 progress.log 和 run_manifest.json。</div>
    </div>
  </section>
  <aside class="panel">
    <div class="field">
      <label for="work_title">作品名</label>
      <input id="work_title" name="work_title" type="text" value="web_input_story">
    </div>
    <div class="field">
      <label for="model_provider">模型</label>
      <select id="model_provider" name="model_provider">
        <option value="deepseek">DeepSeek ({html.escape(DEEPSEEK_MODEL_NAME)})</option>
        <option value="qwen">Qwen ({html.escape(QWEN_MODEL_NAME)})</option>
      </select>
      <div class="hint">Qwen 使用故事生成器同款模型；选择模型后使用下方对应 API Key。</div>
    </div>
    <div class="field">
      <label for="mode">分析模式</label>
      <select id="mode" name="mode">
        <option value="split" selected>自动切分（推荐）</option>
        <option value="single">短文本单章分析</option>
      </select>
      <div class="hint">超过 {AUTO_SPLIT_THRESHOLD_CHARS:,} 字符时会强制进入自动切分，避免超长 prompt。</div>
    </div>
    <div class="field">
      <label for="deepseek_api_key">DeepSeek API Key</label>
      <input id="deepseek_api_key" name="deepseek_api_key" type="password" autocomplete="off" placeholder="可留空，优先使用 .env 中的 DEEPSEEK_API_KEY">
      <div class="hint">选择 DeepSeek 时使用，只写入本次子进程环境。</div>
    </div>
    <div class="field">
      <label for="qwen_api_key">Qwen API Key</label>
      <input id="qwen_api_key" name="qwen_api_key" type="password" autocomplete="off" placeholder="可留空，优先使用 .env 中的 QWEN_API_KEY">
      <div class="hint">选择 Qwen 时使用，模型为 {html.escape(QWEN_MODEL_NAME)}。</div>
      <div class="hint">只用于本次请求，不写入磁盘。</div>
    </div>
    <button type="submit">开始后台分析</button>
  </aside>
</form>
"""
    return _page("故事分析器", body)


def _message_page(title: str, message: str) -> bytes:
    body = f"""
<header>
  <div>
    <h1>{html.escape(title)}</h1>
    <p class="subtle">本地故事分析器</p>
  </div>
  <a href="/" class="status">返回</a>
</header>
<section class="panel">
  <pre>{html.escape(message)}</pre>
</section>
"""
    return _page(title, body)


def _status_class(value: str) -> str:
    low = (value or "").lower()
    if any(token in low for token in ["failed", "blocked", "invalid", "missing_package"]):
        return "bad"
    if any(token in low for token in ["warning", "manual_edits_present", "awaiting", "partial"]):
        return "warn"
    if any(token in low for token in ["missing", "not_exported", "noop", "unknown"]):
        return "missing"
    if any(token in low for token in ["passed", "completed", "finished", "available", "ready"]):
        return "ok"
    return "missing"


def _badge(value: str) -> str:
    safe = html.escape(value or "unknown")
    return f"<span class='status {_status_class(value)}'>{safe}</span>"


def _model_runtime_summary_html(output_dir: Path) -> str:
    manifest_path = output_dir / "run_manifest.json"
    if not manifest_path.exists():
        return ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    provider = str(manifest.get("model_provider") or "unknown")
    model = str(manifest.get("model") or "unknown")
    base_url = str(manifest.get("model_base_url") or "")
    api_key_env = str(manifest.get("model_api_key_env") or "")
    configured = "yes" if manifest.get("model_api_key_configured") else "no"
    return f"""
  <div class="summary-grid">
    <div class="metric"><span class="subtle">Model Provider</span><strong>{html.escape(provider)}</strong>{_badge(provider)}</div>
    <div class="metric"><span class="subtle">Model</span><strong>{html.escape(model)}</strong></div>
    <div class="metric"><span class="subtle">API Key Env</span><strong>{html.escape(api_key_env)}</strong>{_badge('configured' if configured == 'yes' else 'missing')}</div>
    <div class="metric"><span class="subtle">Base URL</span><strong>{html.escape(base_url)}</strong></div>
  </div>
"""


def _load_run_manifest(output_dir: Path) -> dict:
    manifest_path = output_dir / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _analysis_status_from_manifest(output_dir: Path, returncode: int) -> tuple[str, int, dict]:
    manifest = _load_run_manifest(output_dir)
    run_status = str(manifest.get("run_status") or "").lower()
    failed_count = int(manifest.get("failed_chapter_count") or 0)
    if run_status == "partial" or failed_count > 0 or returncode == 2:
        return "部分失败", 500, manifest
    if returncode == 0:
        return "完成", 200, manifest
    return "失败", 500, manifest


def _resolve_output_dir(run_dir: str | Path) -> Path:
    path = Path(str(run_dir)).expanduser()
    if path.name == "output":
        return path
    if (path / "output").exists() or path.suffix == "":
        return path / "output"
    return path


def _safe_work_title(work_title: str) -> str:
    return "".join(
        ch
        if ch.isalnum() or ch in "-_一二三四五六七八九十百千万章节回幕序尾声楔子"
        else "_"
        for ch in work_title
    )[:60] or "web_input_story"

def _validate_story_text_quality(text: str, source_label: str = "故事文本") -> None:
    _shared_validate_story_text_quality(text, source_label)


def _decode_uploaded_text(content: bytes) -> str:
    return _shared_decode_story_text_bytes(content, source_label="上传文件")


def _parse_content_disposition(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if "=" not in part:
            result.setdefault("type", part.lower())
            continue
        key, raw = part.split("=", 1)
        result[key.strip().lower()] = raw.strip().strip('"')
    return result


def _parse_multipart_form(content_type: str, body: bytes) -> dict[str, str]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("multipart boundary is required")
    boundary = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    if not boundary:
        raise ValueError("multipart boundary is empty")
    delimiter = ("--" + boundary).encode("utf-8")
    fields: dict[str, str] = {}
    for raw_part in body.split(delimiter):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].rstrip(b"\r\n")
        header_blob, separator, payload = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers: dict[str, str] = {}
        for raw_header in header_blob.decode("utf-8", errors="replace").split("\r\n"):
            if ":" not in raw_header:
                continue
            key, value = raw_header.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        disposition = _parse_content_disposition(headers.get("content-disposition", ""))
        name = disposition.get("name", "")
        if not name:
            continue
        payload = payload.rstrip(b"\r\n")
        filename = disposition.get("filename", "")
        if filename:
            if name == "story_file" and payload:
                fields["story_text"] = _decode_uploaded_text(payload).strip()
                fields["uploaded_filename"] = filename
            continue
        value = _decode_uploaded_text(payload).strip()
        if name == "story_text" and not value and fields.get("story_text"):
            continue
        fields[name] = value
    return fields


def _parse_form_fields(content_type: str, body: bytes) -> dict[str, str]:
    low = (content_type or "").lower()
    if low.startswith("multipart/form-data"):
        return _parse_multipart_form(content_type, body)
    parsed = urllib.parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _effective_analysis_mode(requested_mode: str, text_length: int) -> str:
    normalized = (requested_mode or "split").strip().lower()
    if normalized == "single" and text_length <= AUTO_SPLIT_THRESHOLD_CHARS:
        return "single"
    return "split"


def _analysis_env_for_provider(fields: dict[str, str], model_provider: str) -> dict:
    env = _load_local_env()
    key_env = _model_key_env(model_provider)
    legacy_temporary_key = fields.get("api_key", "").strip()
    deepseek_temporary_key = fields.get("deepseek_api_key", "").strip()
    qwen_temporary_key = fields.get("qwen_api_key", "").strip()
    temporary_key = qwen_temporary_key if model_provider == "qwen" else deepseek_temporary_key
    temporary_key = temporary_key or legacy_temporary_key
    if temporary_key:
        env[key_env] = temporary_key
    env[MODEL_PROVIDER_ENV] = model_provider
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if not env.get(key_env):
        raise ValueError(f"Missing {key_env}. Enter a temporary key or configure .env.")
    return env


def _analysis_command_for_input(
    *,
    input_dir: Path,
    output_dir: Path,
    input_file: Path,
    mode: str,
    model_provider: str,
) -> list[str]:
    command_mode = "split" if mode == "split" else "folder"
    source_path = input_file if command_mode == "split" else input_dir
    return [
        sys.executable,
        str(CODE_DIR / "book_analyzer_v2.py"),
        command_mode,
        str(source_path),
        str(output_dir),
        "--model-provider",
        model_provider,
    ]


def _prepare_analysis_job(fields: dict[str, str]) -> dict:
    story_text = fields.get("story_text", "").strip()
    work_title = fields.get("work_title", "web_input_story").strip() or "web_input_story"
    requested_mode = fields.get("mode", "split")
    model_provider = fields.get("model_provider", "deepseek").strip().lower() or "deepseek"

    if not story_text:
        raise ValueError("故事文本不能为空。请粘贴文本或上传 .txt/.md 文件。")
    if len(story_text) > MAX_TEXT_CHARS:
        raise ValueError(f"文本过长，当前 {len(story_text)} 字符，限制 {MAX_TEXT_CHARS} 字符。")
    _validate_story_text_quality(story_text)
    if model_provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ValueError(f"Unsupported model provider: {model_provider}")

    mode = _effective_analysis_mode(requested_mode, len(story_text))
    env = _analysis_env_for_provider(fields, model_provider)

    run_id = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
    run_root = WEB_RUNS_DIR / f"{run_id}_{_safe_work_title(work_title)}"
    input_dir = run_root / "input"
    output_dir = run_root / "output"
    input_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)

    input_file = input_dir / ("book.txt" if mode == "split" else "001_web_input.txt")
    input_file.write_text(story_text, encoding="utf-8")
    cmd = _analysis_command_for_input(
        input_dir=input_dir,
        output_dir=output_dir,
        input_file=input_file,
        mode=mode,
        model_provider=model_provider,
    )
    return {
        "run_id": run_id,
        "run_root": run_root,
        "input_dir": input_dir,
        "output_dir": output_dir,
        "input_file": input_file,
        "cmd": cmd,
        "env": env,
        "mode": mode,
        "requested_mode": requested_mode,
        "model_provider": model_provider,
        "text_length": len(story_text),
        "work_title": work_title,
        "uploaded_filename": fields.get("uploaded_filename", ""),
        "resume": False,
    }


def _prune_finished_jobs() -> None:
    with RUNNING_ANALYSIS_JOBS_LOCK:
        finished = [key for key, proc in RUNNING_ANALYSIS_JOBS.items() if proc.poll() is not None]
        for key in finished:
            RUNNING_ANALYSIS_JOBS.pop(key, None)


def _assert_can_start_job(output_dir: Path) -> None:
    _prune_finished_jobs()
    with RUNNING_ANALYSIS_JOBS_LOCK:
        running = [key for key, proc in RUNNING_ANALYSIS_JOBS.items() if proc.poll() is None]
    if str(output_dir) in running:
        raise ValueError("该分析任务已经在运行中。")
    if len(running) >= MAX_CONCURRENT_ANALYSIS_JOBS:
        raise ValueError("已有分析任务正在运行。请等待完成后再启动新的三百万字任务。")


def _start_analysis_process(job: dict) -> subprocess.Popen:
    output_dir = Path(job["output_dir"])
    _assert_can_start_job(output_dir)
    stdout_path = output_dir / "web_stdout.log"
    stderr_path = output_dir / "web_stderr.log"
    metadata_path = output_dir / "web_job.json"
    try:
        previous_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        previous_metadata = {}
    metadata = dict(previous_metadata) if job.get("resume") else {}
    metadata.update({
        "schema_version": "story_analyzer.web_async_job.v1",
        "run_id": job["run_id"],
        "status": "running",
        "mode": job["mode"],
        "requested_mode": job.get("requested_mode", job["mode"]),
        "model_provider": job["model_provider"],
        "text_length": job["text_length"],
        "work_title": job["work_title"],
        "uploaded_filename": job.get("uploaded_filename", ""),
        "input_file": str(job["input_file"]),
        "output_dir": str(output_dir),
        "started_at": previous_metadata.get("started_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stdout_log": stdout_path.name,
        "stderr_log": stderr_path.name,
        "resume_count": int(previous_metadata.get("resume_count") or 0) + (1 if job.get("resume") else 0),
    })
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    log_mode = "a" if job.get("resume") else "w"
    stdout_handle = stdout_path.open(log_mode, encoding="utf-8", errors="replace")
    stderr_handle = stderr_path.open(log_mode, encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            job["cmd"],
            cwd=str(CODE_DIR),
            env=job["env"],
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    metadata["pid"] = getattr(proc, "pid", None)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    with RUNNING_ANALYSIS_JOBS_LOCK:
        RUNNING_ANALYSIS_JOBS[str(output_dir)] = proc
    _start_analysis_watcher(output_dir, proc)
    return proc


def _queue_analysis_job(fields: dict[str, str]) -> dict:
    job = _prepare_analysis_job(fields)
    proc = _start_analysis_process(job)
    return {
        "run_id": job["run_id"],
        "run_root": str(job["run_root"]),
        "output_dir": str(job["output_dir"]),
        "pid": getattr(proc, "pid", None),
        "status_url": "/analyze/run?" + urllib.parse.urlencode({"run_dir": str(job["output_dir"])}),
        "api_status_url": "/api/analyze-status?" + urllib.parse.urlencode({"run_dir": str(job["output_dir"])}),
    }


def _prepare_resume_job(fields: dict[str, str]) -> dict:
    run_dir = fields.get("run_dir", "").strip()
    if not run_dir:
        raise ValueError("run_dir is required")
    output_dir = _resolve_output_dir(run_dir)
    if not output_dir.exists():
        raise ValueError(f"run_dir does not exist: {output_dir}")
    try:
        metadata = json.loads((output_dir / "web_job.json").read_text(encoding="utf-8"))
    except Exception:
        metadata = {}
    input_file = Path(str(metadata.get("input_file") or ""))
    if not input_file.exists():
        candidates = [output_dir.parent / "input" / "book.txt", output_dir.parent / "input" / "001_web_input.txt"]
        input_file = next((candidate for candidate in candidates if candidate.exists()), Path())
    if not input_file.exists():
        raise ValueError("无法恢复：找不到原始输入文件。")
    requested_mode = str(metadata.get("requested_mode") or metadata.get("mode") or "split")
    mode = "split" if input_file.name == "book.txt" else str(metadata.get("mode") or "single")
    model_provider = fields.get("model_provider", "").strip().lower() or str(metadata.get("model_provider") or "deepseek")
    if model_provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ValueError(f"Unsupported model provider: {model_provider}")
    env = _analysis_env_for_provider(fields, model_provider)
    input_dir = input_file.parent
    command = _analysis_command_for_input(
        input_dir=input_dir,
        output_dir=output_dir,
        input_file=input_file,
        mode=mode,
        model_provider=model_provider,
    )
    return {
        "run_id": metadata.get("run_id") or output_dir.parent.name,
        "run_root": output_dir.parent,
        "input_dir": input_dir,
        "output_dir": output_dir,
        "input_file": input_file,
        "cmd": command,
        "env": env,
        "mode": mode,
        "requested_mode": requested_mode,
        "model_provider": model_provider,
        "text_length": int(metadata.get("text_length") or 0),
        "work_title": metadata.get("work_title") or output_dir.parent.name,
        "uploaded_filename": metadata.get("uploaded_filename", ""),
        "resume": True,
    }


def _queue_resume_job(fields: dict[str, str]) -> dict:
    job = _prepare_resume_job(fields)
    proc = _start_analysis_process(job)
    return {
        "run_id": job["run_id"],
        "run_root": str(job["run_root"]),
        "output_dir": str(job["output_dir"]),
        "pid": getattr(proc, "pid", None),
        "status_url": "/analyze/run?" + urllib.parse.urlencode({"run_dir": str(job["output_dir"])}),
        "api_status_url": "/api/analyze-status?" + urllib.parse.urlencode({"run_dir": str(job["output_dir"])}),
    }


def _tail_text(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-max_chars:]


def _pid_exists(pid) -> bool:
    try:
        pid_int = int(pid)
    except Exception:
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _first_present(*values, default=0):
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _sync_web_job_from_manifest(
    output_dir: Path,
    *,
    returncode=None,
    fallback_status: str | None = None,
    persist: bool = True,
) -> dict:
    web_job_path = output_dir / "web_job.json"
    try:
        job = json.loads(web_job_path.read_text(encoding="utf-8"))
    except Exception:
        job = {}
    manifest = _load_run_manifest(output_dir)
    run_status = str(manifest.get("run_status") or "").lower()
    if run_status in {"completed", "partial"}:
        status = run_status
    elif returncode not in (None, 0):
        status = "failed"
    elif returncode == 0:
        status = "completed" if manifest else "finished"
    else:
        status = fallback_status or str(job.get("status") or "unknown")

    job["status"] = status
    if returncode is not None:
        job["returncode"] = returncode
    elif status == "completed":
        job["returncode"] = 0
    elif status == "partial":
        job["returncode"] = int(job.get("returncode") or 2)
    if manifest.get("run_finished_at"):
        job["finished_at"] = manifest.get("run_finished_at")
    elif status in {"completed", "partial", "failed", "finished", "stale"}:
        job.setdefault("finished_at", time.strftime("%Y-%m-%dT%H:%M:%S"))

    for key in (
        "downstream_status",
        "downstream_blocked_reason",
        "failed_arc_count",
        "failed_arcs",
        "failed_stage_targets",
        "missing_required_outputs",
        "llm_target_status_counts",
        "llm_recovered_target_count",
        "llm_unrecovered_failed_target_count",
        "llm_recovered_targets",
        "llm_failed_targets",
        "degraded_arc_count",
        "fallback_arcs",
        "llm_failed_targets_raw",
        "llm_failed_targets_handled_by_fallback",
        "llm_fallback_recovered_target_count",
    ):
        if key in manifest:
            job[key] = manifest.get(key)

    health = classify_llm_health(
        recovered_target_count=_first_present(
            manifest.get("llm_recovered_target_count"), job.get("llm_recovered_target_count")
        ),
        unrecovered_failed_target_count=_first_present(
            manifest.get("llm_unrecovered_failed_target_count"), job.get("llm_unrecovered_failed_target_count")
        ),
        attempt_failed_call_count=_first_present(
            manifest.get("llm_attempt_failed_call_count"), job.get("llm_attempt_failed_call_count")
        ),
        final_state=status in {"completed", "partial", "failed", "finished", "stale"},
    )
    if manifest.get("llm_health_status") == "recovered_with_fallback":
        health = {
            "status": "recovered_with_fallback",
            "label": manifest.get("llm_health_label") or "已降级恢复",
            "severity": manifest.get("llm_health_severity") or "warning",
            "css_class": "warn",
            "message": manifest.get("llm_health_message") or "LLM target 失败后已用本地降级产物恢复。",
        }
    job["llm_health_status"] = health["status"]
    job["llm_health_label"] = health["label"]
    job["llm_health_severity"] = health["severity"]
    job["llm_health_message"] = health["message"]

    if persist:
        try:
            web_job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return job


def _run_generator_handoff_v2_postprocess(output_dir: Path) -> dict:
    report_path = output_dir / "web_handoff_postprocess.json"
    report = {
        "schema_version": "story_analyzer.web_handoff_postprocess.v1",
        "status": "skipped",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evidence_mode": "v2",
        "steps": [],
    }
    manifest = _load_run_manifest(output_dir)
    if str(manifest.get("run_status") or "").lower() != "completed":
        report["skip_reason"] = "run_status_not_completed"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    try:
        raw_report = build_raw_source_index(output_dir)
        report["steps"].append({"step": "build_raw_source_index", "status": raw_report.get("status", "completed")})
        compile_report = compile_generator_handoff(output_dir)
        report["steps"].append(
            {
                "step": "compile_generator_handoff",
                "status": compile_report.get("compiler_status", "unknown"),
                "blocking_errors": compile_report.get("blocking_error_count", 0),
                "warnings": compile_report.get("warning_count", 0),
            }
        )
        validation_report = validate_generator_handoff(output_dir, evidence_mode="v2")
        report["validation_status"] = validation_report.get("validation_status", "")
        report["steps"].append(
            {
                "step": "validate_generator_handoff",
                "status": validation_report.get("validation_status", "unknown"),
                "blocking_issues": validation_report.get("blocking_issue_count", 0),
                "warnings": validation_report.get("warning_count", 0),
            }
        )
        if not is_generator_handoff_deliverable(validation_report):
            repair_report = repair_generator_handoff(output_dir, evidence_mode="v2", max_attempts=5)
            report["repair_status"] = repair_report.get("repair_status", "")
            report["steps"].append(
                {
                    "step": "repair_generator_handoff",
                    "status": repair_report.get("repair_status", "unknown"),
                    "validation_status": repair_report.get("validation_status", ""),
                    "attempts": repair_report.get("attempt_count", 0),
                }
            )
        else:
            report["repair_status"] = "not_needed"
        report["status"] = "completed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _watch_analysis_process(output_dir: Path, proc: subprocess.Popen) -> None:
    if not hasattr(proc, "wait"):
        return
    try:
        returncode = proc.wait()
    except Exception:
        return
    with RUNNING_ANALYSIS_JOBS_LOCK:
        if RUNNING_ANALYSIS_JOBS.get(str(output_dir)) is proc:
            RUNNING_ANALYSIS_JOBS.pop(str(output_dir), None)
    _sync_web_job_from_manifest(output_dir, returncode=returncode)
    _run_generator_handoff_v2_postprocess(output_dir)


def _start_analysis_watcher(output_dir: Path, proc: subprocess.Popen) -> None:
    if not hasattr(proc, "wait"):
        return
    thread = threading.Thread(target=_watch_analysis_process, args=(output_dir, proc), daemon=True)
    thread.start()


def _analysis_status_payload(run_dir: str | Path) -> dict:
    output_dir = _resolve_output_dir(run_dir)
    key = str(output_dir)
    web_job_path = output_dir / "web_job.json"
    try:
        web_job = json.loads(web_job_path.read_text(encoding="utf-8"))
    except Exception:
        web_job = {}
    proc = None
    returncode = web_job.get("returncode")
    with RUNNING_ANALYSIS_JOBS_LOCK:
        proc = RUNNING_ANALYSIS_JOBS.get(key)
    if proc is not None:
        returncode = proc.poll()
        if returncode is not None:
            with RUNNING_ANALYSIS_JOBS_LOCK:
                RUNNING_ANALYSIS_JOBS.pop(key, None)

    manifest = _load_run_manifest(output_dir)
    run_status = str(manifest.get("run_status") or "").lower()
    web_job_status = str(web_job.get("status") or "").lower()
    if proc is not None and returncode is None:
        state = "running"
    elif run_status == "completed":
        state = "completed"
    elif run_status == "partial":
        state = "partial"
    elif returncode not in (None, 0):
        state = "failed"
    elif returncode == 0:
        state = "completed" if manifest else "finished"
    elif web_job_status == "running" and web_job.get("pid"):
        state = "detached_running" if _pid_exists(web_job.get("pid")) else "stale"
    elif web_job_status in {"failed", "completed", "partial", "finished", "stale"}:
        state = web_job_status
    elif web_job_path.exists():
        state = "starting"
    else:
        state = "unknown"

    if proc is not None and returncode is not None:
        web_job = _sync_web_job_from_manifest(output_dir, returncode=returncode, fallback_status=state)
    elif run_status in {"completed", "partial"} and web_job_path.exists() and web_job_status != run_status:
        web_job = _sync_web_job_from_manifest(output_dir, returncode=returncode, fallback_status=state, persist=False)

    chapter_done = len(list((output_dir / "chapters").glob("chapter_*_analysis.json"))) if output_dir.exists() else 0
    arc_done = len(list((output_dir / "arcs").glob("arc_*.json"))) if output_dir.exists() else 0
    final_state = state in {"completed", "partial", "failed", "finished", "stale"}
    llm_health = classify_llm_health(
        recovered_target_count=_first_present(
            manifest.get("llm_recovered_target_count"), web_job.get("llm_recovered_target_count")
        ),
        unrecovered_failed_target_count=_first_present(
            manifest.get("llm_unrecovered_failed_target_count"), web_job.get("llm_unrecovered_failed_target_count")
        ),
        attempt_failed_call_count=_first_present(
            manifest.get("llm_attempt_failed_call_count"), web_job.get("llm_attempt_failed_call_count")
        ),
        final_state=final_state,
    )
    if manifest.get("llm_health_status") == "recovered_with_fallback":
        llm_health = {
            "status": "recovered_with_fallback",
            "label": manifest.get("llm_health_label") or "已降级恢复",
            "severity": manifest.get("llm_health_severity") or "warning",
            "css_class": "warn",
            "message": manifest.get("llm_health_message") or "LLM target 失败后已用本地降级产物恢复。",
        }
    return {
        "schema_version": "story_analyzer.web_analysis_status.v1",
        "state": state,
        "returncode": returncode,
        "output_dir": str(output_dir),
        "run_root": str(output_dir.parent),
        "manifest": manifest,
        "counts": {
            "chapter_analysis_files": chapter_done,
            "arc_files": arc_done,
            "successful_chapter_count": manifest.get("successful_chapter_count"),
            "analysis_unit_count": manifest.get("analysis_unit_count"),
            "source_total_chapters": manifest.get("source_total_chapters"),
            "failed_chapter_count": manifest.get("failed_chapter_count"),
            "arc_count": manifest.get("arc_count"),
            "expected_arc_count": manifest.get("expected_arc_count"),
            "failed_arc_count": manifest.get("failed_arc_count"),
        },
        "llm": {
            "target_status_counts": manifest.get("llm_target_status_counts") or {},
            "recovered_retry_count": manifest.get("llm_recovered_target_count") or 0,
            "failed_unrecovered_count": manifest.get("llm_unrecovered_failed_target_count") or 0,
            "recovered_retry_targets": manifest.get("llm_recovered_targets") or [],
            "failed_unrecovered_targets": manifest.get("llm_failed_targets") or [],
            "health_status": llm_health["status"],
            "health_label": llm_health["label"],
            "health_severity": llm_health["severity"],
            "health_class": llm_health["css_class"],
            "health_message": llm_health["message"],
        },
        "logs": {
            "progress_log_tail": _tail_text(output_dir / "progress.log", 8000),
            "stdout_tail": _tail_text(output_dir / "web_stdout.log", 5000),
            "stderr_tail": _tail_text(output_dir / "web_stderr.log", 5000),
        },
        "links": {
            "review": "/review?" + urllib.parse.urlencode({"run_dir": str(output_dir)}),
            "arc_review": "/review/arcs?" + urllib.parse.urlencode({"run_dir": str(output_dir)}),
            "reports": "/review/reports?" + urllib.parse.urlencode({"run_dir": str(output_dir)}),
        },
        "process": {
            "pid": web_job.get("pid"),
            "tracked_by_current_server": proc is not None,
        },
        "job": {
            "model_provider": web_job.get("model_provider") or manifest.get("model_provider"),
            "mode": web_job.get("mode"),
            "requested_mode": web_job.get("requested_mode"),
            "uploaded_filename": web_job.get("uploaded_filename"),
            "resume_count": web_job.get("resume_count"),
        },
        "files": {
            "run_manifest": str(output_dir / "run_manifest.json"),
            "full_book_bundle": str(output_dir / "full_book_bundle.json"),
            "generation_profiles": str(output_dir / "generation_profiles.json"),
        },
    }


def _analysis_progress_script() -> str:
    return """
<script>
const analyzeRunData = JSON.parse(document.getElementById("analyze-run-data").textContent);

function stateClass(state) {
  if (["failed"].includes(state)) return "bad";
  if (["partial", "unknown", "starting", "stale"].includes(state)) return "warn";
  if (["completed", "finished"].includes(state)) return "ok";
  if (state === "running" || state === "detached_running") return "missing";
  return "missing";
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value == null || value === "" ? "-" : String(value);
}

function renderStatus(payload) {
  const state = payload.state || "unknown";
  const stateNode = document.getElementById("run-state");
  stateNode.textContent = state;
  stateNode.className = `status ${stateClass(state)}`;

  setText("output-dir", payload.output_dir || "");
  setText("chapter-count", payload.counts?.chapter_analysis_files);
  setText("arc-count", payload.counts?.arc_files);
  setText("source-total-chapters", payload.counts?.source_total_chapters);
  setText("analysis-unit-count", payload.counts?.analysis_unit_count);
  setText("failed-chapter-count", payload.counts?.failed_chapter_count);
  setText("failed-arc-count", payload.counts?.failed_arc_count);
  setText("llm-recovered-retry-count", payload.llm?.recovered_retry_count);
  setText("llm-failed-unrecovered-count", payload.llm?.failed_unrecovered_count);
  const llmHealthNode = document.getElementById("llm-health-status");
  if (llmHealthNode) {
    llmHealthNode.textContent = payload.llm?.health_label || "-";
    llmHealthNode.className = `status ${payload.llm?.health_class || "missing"}`;
  }
  setText("llm-health-note", payload.llm?.health_message || "");
  setText("manifest-status", payload.manifest?.run_status || state);
  setText("progress-log", payload.logs?.progress_log_tail || "progress.log not written yet.");
  setText("stdout-log", payload.logs?.stdout_tail || "");
  setText("stderr-log", payload.logs?.stderr_tail || "");

  const reviewLink = document.getElementById("review-link");
  const arcReviewLink = document.getElementById("arc-review-link");
  const reportsLink = document.getElementById("reports-link");
  if (payload.links?.review) reviewLink.href = payload.links.review;
  if (payload.links?.arc_review) arcReviewLink.href = payload.links.arc_review;
  if (payload.links?.reports) reportsLink.href = payload.links.reports;
}

async function resumeRun() {
  const button = document.getElementById("resume-run");
  const keyInput = document.getElementById("resume-api-key");
  const providerInput = document.getElementById("resume-model-provider");
  if (!button) return;
  button.disabled = true;
  button.textContent = "正在恢复...";
  try {
    const response = await fetch("/api/analyze-resume", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        run_dir: analyzeRunData.output_dir,
        model_provider: providerInput ? providerInput.value : "",
        api_key: keyInput ? keyInput.value : "",
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "resume failed");
    if (keyInput) keyInput.value = "";
    renderStatus({state: "running", output_dir: payload.output_dir, counts: {}, llm: {}, logs: {}, links: {}});
    window.setTimeout(pollStatus, 1000);
  } catch (error) {
    setText("resume-status", String(error));
  } finally {
    button.disabled = false;
    button.textContent = "继续此任务";
  }
}

async function pollStatus() {
  try {
    const response = await fetch(analyzeRunData.api_status_url, {cache: "no-store"});
    const payload = await response.json();
    renderStatus(payload);
    if (!["completed", "partial", "failed", "finished", "stale"].includes(payload.state)) {
      window.setTimeout(pollStatus, 3000);
    }
  } catch (error) {
    setText("manifest-status", `status poll failed: ${error}`);
    window.setTimeout(pollStatus, 5000);
  }
}

const resumeButton = document.getElementById("resume-run");
if (resumeButton) resumeButton.addEventListener("click", resumeRun);
pollStatus();
</script>
"""


def _analysis_progress_page(query_string: str = "") -> bytes:
    query = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    run_dir = (query.get("run_dir", [""])[0] or "").strip()
    if not run_dir:
        return _message_page("分析任务缺少 run_dir", "无法定位后台分析任务。")

    output_dir = _resolve_output_dir(run_dir)
    payload = _analysis_status_payload(output_dir)
    data_json = html.escape(
        json.dumps(
            {
                "api_status_url": "/api/analyze-status?"
                + urllib.parse.urlencode({"run_dir": str(output_dir)}),
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        )
    )
    state = str(payload.get("state") or "unknown")
    counts = payload.get("counts") or {}
    logs = payload.get("logs") or {}
    links = payload.get("links") or {}
    job_meta = payload.get("job") or {}
    resume_provider = str(
        job_meta.get("model_provider") or (payload.get("manifest") or {}).get("model_provider") or "deepseek"
    ).lower()
    if resume_provider not in SUPPORTED_MODEL_PROVIDERS:
        resume_provider = "deepseek"
    deepseek_selected = " selected" if resume_provider == "deepseek" else ""
    qwen_selected = " selected" if resume_provider == "qwen" else ""
    llm_payload = payload.get("llm") or {}
    llm_health_label = html.escape(str(llm_payload.get("health_label") or "-"))
    llm_health_class = html.escape(str(llm_payload.get("health_class") or "missing"))
    llm_health_message = html.escape(str(llm_payload.get("health_message") or ""))
    body = f"""
<header>
  <div>
    <h1>故事分析任务</h1>
    <p class="subtle">后台运行中。三百万字级别文本会持续写入 progress.log，页面每 3 秒刷新一次状态。</p>
  </div>
  <div class="actions">
    <a href="/" class="status">分析入口</a>
    <a id="review-link" href="{html.escape(links.get("review", "#"))}" class="status">Review</a>
    <a id="arc-review-link" href="{html.escape(links.get("arc_review", "#"))}" class="status">Arc Review</a>
    <a id="reports-link" href="{html.escape(links.get("reports", "#"))}" class="status">Reports</a>
  </div>
</header>
<section class="summary-grid" aria-label="analysis progress">
  <div class="metric"><span class="subtle">State</span><strong id="run-state" class="status {_status_class(state)}">{html.escape(state)}</strong></div>
  <div class="metric"><span class="subtle">Chapter Files</span><strong id="chapter-count">{html.escape(str(counts.get("chapter_analysis_files") or 0))}</strong></div>
  <div class="metric"><span class="subtle">Arc Files</span><strong id="arc-count">{html.escape(str(counts.get("arc_files") or 0))}</strong></div>
  <div class="metric"><span class="subtle">Manifest Status</span><strong id="manifest-status">{html.escape(str((payload.get("manifest") or {}).get("run_status") or state))}</strong></div>
</section>
<section class="summary-grid" aria-label="analysis scale">
  <div class="metric"><span class="subtle">Source Chapters</span><strong id="source-total-chapters">{html.escape(str(counts.get("source_total_chapters") or "-"))}</strong></div>
  <div class="metric"><span class="subtle">Analysis Units</span><strong id="analysis-unit-count">{html.escape(str(counts.get("analysis_unit_count") or "-"))}</strong></div>
  <div class="metric"><span class="subtle">Failed Chapters</span><strong id="failed-chapter-count">{html.escape(str(counts.get("failed_chapter_count") or 0))}</strong></div>
  <div class="metric"><span class="subtle">Failed Arcs</span><strong id="failed-arc-count">{html.escape(str(counts.get("failed_arc_count") or 0))}</strong></div>
</section>
<section class="summary-grid" aria-label="llm retry diagnostics">
  <div class="metric"><span class="subtle">Recovered Retries</span><strong id="llm-recovered-retry-count">{html.escape(str((payload.get("llm") or {}).get("recovered_retry_count") or 0))}</strong></div>
  <div class="metric"><span class="subtle">Unrecovered Failures</span><strong id="llm-failed-unrecovered-count">{html.escape(str((payload.get("llm") or {}).get("failed_unrecovered_count") or 0))}</strong></div>
  <div class="metric"><span class="subtle">LLM Health</span><strong id="llm-health-status" class="status {llm_health_class}">{llm_health_label}</strong><p id="llm-health-note" class="hint">{llm_health_message}</p></div>
  <div class="metric"><span class="subtle">Status API</span><strong>3s poll</strong></div>
</section>
<div class="stack">
  <section class="panel">
    <h2>输出目录</h2>
    <pre id="output-dir">{html.escape(str(output_dir))}</pre>
  </section>
  <section class="panel">
    <h2>恢复任务</h2>
    <div class="two-col">
      <div class="field">
        <label for="resume-model-provider">模型</label>
        <select id="resume-model-provider">
          <option value="deepseek"{deepseek_selected}>DeepSeek</option>
          <option value="qwen"{qwen_selected}>Qwen</option>
        </select>
      </div>
      <div class="field">
        <label for="resume-api-key">临时 API Key</label>
        <input id="resume-api-key" type="password" autocomplete="off" placeholder="可留空，优先使用 .env">
      </div>
    </div>
    <button type="button" id="resume-run">继续此任务</button>
    <p id="resume-status" class="subtle"></p>
  </section>
  <section class="panel">
    <h2>progress.log</h2>
    <pre id="progress-log">{html.escape(logs.get("progress_log_tail") or "progress.log not written yet.")}</pre>
  </section>
  <section class="panel">
    <h2>stdout</h2>
    <pre id="stdout-log">{html.escape(logs.get("stdout_tail") or "")}</pre>
  </section>
  <section class="panel">
    <h2>stderr</h2>
    <pre id="stderr-log">{html.escape(logs.get("stderr_tail") or "")}</pre>
  </section>
</div>
<script id="analyze-run-data" type="application/json">{data_json}</script>
{_analysis_progress_script()}
"""
    return _page("故事分析任务", body)


def _analysis_issue_summary_html(manifest: dict) -> str:
    if not manifest:
        return ""
    failed_count = int(manifest.get("failed_chapter_count") or 0)
    blocked_reason = str(manifest.get("downstream_blocked_reason") or "")
    if failed_count <= 0 and not blocked_reason:
        return ""
    failed_items = []
    for item in manifest.get("failed_chapters") or []:
        index = item.get("chapter_index", "?")
        title = item.get("input_title") or item.get("original_title") or item.get("title") or ""
        error = item.get("error") or ""
        failed_items.append(
            "<li>"
            + html.escape(f"chapter_{int(index):03d}" if isinstance(index, int) else str(index))
            + (f"：{html.escape(str(title))}" if title else "")
            + (f"<br><span class='subtle'>{html.escape(str(error)[:300])}</span>" if error else "")
            + "</li>"
        )
    failed_list = f"<ul>{''.join(failed_items)}</ul>" if failed_items else ""
    return f"""
  <div>
    <strong class="error">本次输出不完整，已阻断弧段/全书/交接包导出。</strong>
    <p>失败章节：{failed_count}；阻断原因：<code>{html.escape(blocked_reason or 'unknown')}</code></p>
    {failed_list}
  </div>
"""


def _common_files_html(output_dir: Path) -> str:
    candidates = [
        "chapters/chapter_001_framework.json",
        "chapters/chapter_001_analysis.json",
        "book_framework.json",
        "generation_profiles.json",
        "full_book_bundle.json",
        "run_manifest.json",
    ]
    existing = [rel for rel in candidates if (output_dir / rel).exists()]
    if not existing:
        return "<p>常用文件：<span class='empty'>暂无完整输出文件</span></p>"
    items = "\n".join(f"<li><code>{html.escape(rel)}</code></li>" for rel in existing)
    return f"<p>常用文件：</p>\n  <ul>\n    {items}\n  </ul>"


def _format_value(value) -> str:
    if value is None or value == "":
        return "<span class='empty'>-</span>"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2)
        return f"<pre>{html.escape(text)}</pre>"
    return html.escape(str(value))


def _json_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _optional_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _rows(items: list[tuple[str, object]]) -> str:
    return "<table>" + "".join(
        f"<tr><th>{html.escape(label)}</th><td>{_format_value(value)}</td></tr>" for label, value in items
    ) + "</table>"


def _preview(title: str, items) -> str:
    if not items:
        return f"<p class='empty'>{html.escape(title)}：暂无。</p>"
    return f"<h3>{html.escape(title)}</h3><pre>{html.escape(json.dumps(items, ensure_ascii=False, indent=2))}</pre>"


def _review_form(run_dir: str = "", package_dir: str = "") -> str:
    return f"""
<form class="review-form" method="get" action="/review">
  <div>
    <label for="run_dir">Run 目录</label>
    <input id="run_dir" name="run_dir" type="text" value="{html.escape(run_dir)}" placeholder="例如：.../03_Analysis_Outputs/analysis_runs/xxx">
  </div>
  <div>
    <label for="package_dir">Handoff Package 目录</label>
    <input id="package_dir" name="package_dir" type="text" value="{html.escape(package_dir)}" placeholder="可留空，自动读取 pipeline 报告">
  </div>
  <button type="submit">查看</button>
</form>
"""


def _review_api_href(run_dir: str, package_dir: str) -> str:
    query = urllib.parse.urlencode({"run_dir": run_dir, "package_dir": package_dir})
    return "/api/review-summary?" + query


def _review_page(query_string: str = "") -> bytes:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    run_dir = (params.get("run_dir", [""])[0] or "").strip()
    package_dir = (params.get("package_dir", [""])[0] or "").strip()
    api_link = _review_api_href(run_dir, package_dir) if run_dir else ""

    header_actions = f"""
  <div class="actions">
    <a href="/" class="status">分析入口</a>
    <a href="/review/runs" class="status">Runs</a>
    {f'<a href="/review/arcs?{html.escape(urllib.parse.urlencode({"run_dir": run_dir}))}" class="status">Arc Review</a>' if run_dir else ''}
    {f'<a href="/review/rebuild?{html.escape(urllib.parse.urlencode({"run_dir": run_dir}))}" class="status">Rebuild</a>' if run_dir else ''}
    {f'<a href="/review/reports?{html.escape(urllib.parse.urlencode({"run_dir": run_dir, "package_dir": package_dir}))}" class="status">Reports</a>' if run_dir else ''}
    {f'<a href="{html.escape(api_link)}" class="status">JSON</a>' if api_link else ''}
  </div>
"""
    if not run_dir:
        body = f"""
<header>
  <div>
    <h1>Story Analyzer Review</h1>
    <p class="subtle">查看单次分析 run 的质量、人工编辑、重建和 handoff 状态。</p>
  </div>
  {header_actions}
</header>
{_review_form()}
<section class="panel">
  <p class="empty">请输入 run 目录。页面不会触发分析、重建或导出，只读取已有报告。</p>
</section>
"""
        return _page("Story Analyzer Review", body)

    try:
        summary = build_review_summary(run_dir, package_dir=package_dir or None)
    except Exception as exc:
        return _message_page("Review 读取失败", f"{type(exc).__name__}: {exc}")

    quality = summary["quality"]
    tracker = summary["tracker_edit_report"]
    audit = summary["manual_edit_audit"]
    rebuild = summary["downstream_rebuild"]
    handoff = summary["handoff"]
    generator_handoff = handoff.get("generator_handoff", {})
    pipeline = summary["pipeline"]
    source = summary["source"]
    run = summary["run"]

    body = f"""
<header>
  <div>
    <h1>Story Analyzer Review</h1>
    <p class="subtle mono">{html.escape(run_dir)}</p>
  </div>
  {header_actions}
</header>
{_review_form(run_dir, package_dir)}
<section class="summary-grid" aria-label="review summary">
  <div class="metric"><span class="subtle">Quality Gate</span><strong>{html.escape(quality["status"])}</strong>{_badge(quality["state"])}</div>
  <div class="metric"><span class="subtle">Tracker Edit</span><strong>{html.escape(tracker["status"])}</strong>{_badge(tracker["state"])}</div>
  <div class="metric"><span class="subtle">Handoff</span><strong>{html.escape(handoff["validation_status"])}</strong>{_badge(handoff["state"])}</div>
  <div class="metric"><span class="subtle">Next Action</span><strong>{html.escape(pipeline["next_action"] or rebuild["next_action"] or "-")}</strong>{_badge(pipeline["status"] or rebuild["status"])}</div>
</section>
<div class="stack">
  <section class="panel">
    <h2>Run 与 Pipeline</h2>
    {_rows([
        ("Run 状态", run["state"]),
        ("作品名", run["work_title"]),
        ("章节数", run["chapter_count"]),
        ("Source Manifest", source["state"]),
        ("Pipeline 状态", pipeline["status"]),
        ("当前阶段", pipeline["current_stage"]),
        ("下一步", pipeline["next_action"]),
    ])}
  </section>
  <div class="two-col">
    <section class="panel">
      <h2>Quality Report</h2>
      {_rows([
          ("状态", quality["status"]),
          ("章节数", quality["chapter_count"]),
          ("Blocking", quality["blocking_issue_count"]),
          ("Warnings", quality["warning_count"]),
          ("Semantic Sources", quality["semantic_sources"]),
          ("路径", quality["path"]),
      ])}
      {_preview("Issue Preview", quality["issue_preview"])}
    </section>
    <section class="panel">
      <h2>Tracker Edit Report</h2>
      {_rows([
          ("状态", tracker["status"]),
          ("操作数", tracker["operation_count"]),
          ("人工覆盖项", tracker["manual_override_item_count"]),
          ("操作类型", tracker["operations_by_type"]),
          ("Tracker 类型", tracker["operations_by_tracker_type"]),
          ("Semantic Risk", tracker["semantic_risk_level"]),
          ("Semantic Source", tracker["semantic_review"].get("semantic_source_status", "")),
          ("Semantic Review", tracker["semantic_review"]),
          ("路径", tracker["path"]),
      ])}
      {_preview("Risk Reasons", tracker["risk_reasons"])}
      {_preview("Review Points", tracker["recommended_review_points"])}
      {_preview("Operation Preview", tracker["operation_preview"])}
      {_preview("Manual Override Preview", tracker["manual_override_preview"])}
    </section>
  </div>
  <div class="two-col">
    <section class="panel">
      <h2>Manual Edit Audit</h2>
      {_rows([
          ("状态", audit["state"]),
          ("事件数", audit["event_count"]),
          ("路径", audit["path"]),
      ])}
      {_preview("Audit Event Preview", audit["event_preview"])}
    </section>
    <section class="panel">
      <h2>Downstream Rebuild</h2>
      {_rows([
          ("状态", rebuild["status"]),
          ("下一步", rebuild["next_action"]),
          ("计划阶段", rebuild["planned_stages"]),
          ("已重建阶段", rebuild["rebuilt_stages"]),
          ("失效 Step", rebuild["invalidated_step_ids"]),
          ("路径", rebuild["path"]),
      ])}
    </section>
  </div>
  <section class="panel">
    <h2>Handoff Package</h2>
    {_rows([
        ("状态", handoff["validation_status"]),
        ("Package", handoff["package_dir"]),
        ("Contract", handoff["contract_version"]),
        ("Blocking", handoff["blocking_issue_count"]),
        ("Warnings", handoff["warning_count"]),
        ("Checks", handoff["checks"]),
        ("Validation", handoff.get("validation_path", "")),
        ("Generator Handoff", generator_handoff.get("state", "")),
        ("Generator Validation", generator_handoff.get("validation_status", "")),
        ("Repair Status", generator_handoff.get("repair_status", "")),
        ("Repair Attempts", generator_handoff.get("repair_attempt_count", 0)),
        ("Applied Repairs", generator_handoff.get("applied_repair_count", 0)),
        ("Validated Generator Handoff", generator_handoff.get("validated_handoff_path", "")),
        ("Repair Failed Report", generator_handoff.get("failed_report_path", "")),
    ])}
    {_preview("Blocking Issue Preview", handoff["blocking_issue_preview"])}
    {_preview("Warning Preview", handoff["warning_preview"])}
  </section>
</div>
"""
    return _page("Story Analyzer Review", body)


def _reports_form(run_dir: str = "", package_dir: str = "", pattern_report: str = "") -> str:
    return f"""
<form class="review-form" method="get" action="/review/reports">
  <div>
    <label for="run_dir">Run 目录</label>
    <input id="run_dir" name="run_dir" type="text" value="{html.escape(run_dir)}" placeholder="例如：.../03_Analysis_Outputs/analysis_runs/xxx">
  </div>
  <div>
    <label for="package_dir">Handoff Package</label>
    <input id="package_dir" name="package_dir" type="text" value="{html.escape(package_dir)}" placeholder="可留空，优先读取 run/modules">
  </div>
  <div>
    <label for="pattern_report">Pattern Report</label>
    <input id="pattern_report" name="pattern_report" type="text" value="{html.escape(pattern_report)}" placeholder="可留空，读取 run/synthesis">
  </div>
  <button type="submit">查看</button>
</form>
"""


def _reports_api_href(run_dir: str, package_dir: str, pattern_report: str) -> str:
    query = urllib.parse.urlencode(
        {"run_dir": run_dir, "package_dir": package_dir, "pattern_report": pattern_report}
    )
    return "/api/review-reports?" + query


def _report_panel(title: str, report: dict) -> str:
    return f"""
<section class="panel">
  <h2>{html.escape(title)}</h2>
  {_rows([
      ("状态", report.get("status", "")),
      ("文件状态", report.get("state", "")),
      ("路径", report.get("path", "")),
      ("数量", report.get("conflict_count", report.get("pattern_count", 0))),
      ("最高严重度", report.get("max_severity", "")),
      ("作品数", report.get("work_count", "")),
  ])}
  {_preview("Preview", report.get("preview", []))}
</section>
"""


def _read_json_file(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _list_count(value) -> int:
    return len(value) if isinstance(value, list) else 0


def _story_output_file_rows(output_dir: Path) -> str:
    rows = []
    for rel in [
        "run_manifest.json",
        "book_framework.json",
        "generation_profiles.json",
        "full_book_bundle.json",
        "foreshadowing_registry.json",
        "narrative_thread_registry.json",
        "source_leak_report.json",
        "abstraction_quality_report.json",
    ]:
        path = output_dir / rel
        state = "available" if path.exists() else "missing"
        size = path.stat().st_size if path.exists() else ""
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(rel)}</code></td>"
            f"<td>{_badge(state)}</td>"
            f"<td>{html.escape(str(size))}</td>"
            "</tr>"
        )
    return f"""
<div class="table-scroll">
  <table>
    <thead><tr><th>File</th><th>State</th><th>Bytes</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>
"""


def _story_analysis_report(run_dir: str) -> dict:
    output_dir = _resolve_output_dir(run_dir)
    manifest = _load_run_manifest(output_dir)
    book = _read_json_file(output_dir / "book_framework.json")
    profiles = _read_json_file(output_dir / "generation_profiles.json")
    leak = _read_json_file(output_dir / "source_leak_report.json")
    abstraction = _read_json_file(output_dir / "abstraction_quality_report.json")
    foreshadowing = _read_json_file(output_dir / "foreshadowing_registry.json")
    narrative_threads = _read_json_file(output_dir / "narrative_thread_registry.json")
    arc_hierarchy = profiles.get("arc_hierarchy") if isinstance(profiles, dict) else {}
    if not isinstance(arc_hierarchy, dict):
        arc_hierarchy = {}
    usage_profiles = profiles.get("usage_profiles") if isinstance(profiles, dict) else {}
    if not isinstance(usage_profiles, dict):
        usage_profiles = {}

    core_files = [
        output_dir / "run_manifest.json",
        output_dir / "book_framework.json",
        output_dir / "generation_profiles.json",
        output_dir / "full_book_bundle.json",
    ]
    available_core_count = sum(1 for path in core_files if path.exists())
    return {
        "schema_version": "story_analyzer.web_story_analysis_report.v1",
        "status": str(manifest.get("run_status") or ("available" if available_core_count else "missing")),
        "state": "available" if available_core_count else "missing",
        "model_provider": manifest.get("model_provider", ""),
        "model": manifest.get("model", ""),
        "downstream_status": manifest.get("downstream_status", ""),
        "source_total_chapters": manifest.get("source_total_chapters", book.get("source_total_chapters", "")),
        "analysis_unit_count": manifest.get("analysis_unit_count", book.get("analysis_unit_count", "")),
        "successful_chapter_count": manifest.get("successful_chapter_count", ""),
        "failed_chapter_count": manifest.get("failed_chapter_count", ""),
        "total_arcs": book.get("total_arcs", ""),
        "major_arc_count": _list_count(arc_hierarchy.get("major_arcs")),
        "sub_arc_count": _list_count(arc_hierarchy.get("sub_arcs")),
        "source_leak_status": leak.get("status", "missing") if leak else "missing",
        "abstraction_quality_status": abstraction.get("status", "missing") if abstraction else "missing",
        "abstraction_quality_score": abstraction.get("abstraction_quality_score", ""),
        "foreshadowing_item_count": _list_count(foreshadowing.get("items")),
        "narrative_thread_count": _list_count(narrative_threads.get("items")),
        "usage_profiles": sorted(usage_profiles.keys()),
    }


def _story_analysis_report_html(report: dict, output_dir: Path) -> str:
    return f"""
<section class="panel">
  <h2>Story Analysis Report</h2>
  <p class="subtle mono">{html.escape(str(output_dir))}</p>
  <section class="summary-grid" aria-label="story analysis report summary">
    <div class="metric"><span class="subtle">Run Status</span><strong>{html.escape(str(report.get("status") or ""))}</strong>{_badge(str(report.get("status") or ""))}</div>
    <div class="metric"><span class="subtle">Analysis Units</span><strong>{html.escape(str(report.get("analysis_unit_count") or "-"))}</strong>{_badge("available" if report.get("analysis_unit_count") else "missing")}</div>
    <div class="metric"><span class="subtle">Arcs</span><strong>{html.escape(str(report.get("total_arcs") or "-"))}</strong>{_badge("available" if report.get("total_arcs") else "missing")}</div>
    <div class="metric"><span class="subtle">Source Leak</span><strong>{html.escape(str(report.get("source_leak_status") or "missing"))}</strong>{_badge(str(report.get("source_leak_status") or "missing"))}</div>
  </section>
  {_rows([
      ("Model Provider", report.get("model_provider", "")),
      ("Model", report.get("model", "")),
      ("Downstream Status", report.get("downstream_status", "")),
      ("Source Chapters", report.get("source_total_chapters", "")),
      ("Successful Chapters", report.get("successful_chapter_count", "")),
      ("Failed Chapters", report.get("failed_chapter_count", "")),
      ("Major Arcs", report.get("major_arc_count", "")),
      ("Sub Arcs", report.get("sub_arc_count", "")),
      ("Abstraction Quality", report.get("abstraction_quality_status", "")),
      ("Abstraction Score", report.get("abstraction_quality_score", "")),
      ("Foreshadowing Items", report.get("foreshadowing_item_count", "")),
      ("Narrative Threads", report.get("narrative_thread_count", "")),
      ("Usage Profiles", ", ".join(report.get("usage_profiles") or [])),
  ])}
  <h3>Generated Files</h3>
  {_story_output_file_rows(output_dir)}
</section>
"""


def _reports_page(query_string: str = "") -> bytes:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    run_dir = (params.get("run_dir", [""])[0] or "").strip()
    package_dir = (params.get("package_dir", [""])[0] or "").strip()
    pattern_report = (params.get("pattern_report", [""])[0] or "").strip()
    header_actions = f"""
  <div class="actions">
    <a href="/review" class="status">Review</a>
    <a href="/review/runs" class="status">Runs</a>
    {f'<a href="/review/arcs?{html.escape(urllib.parse.urlencode({"run_dir": run_dir}))}" class="status">Arc Review</a>' if run_dir else ''}
    {f'<a href="/review/rebuild?{html.escape(urllib.parse.urlencode({"run_dir": run_dir}))}" class="status">Rebuild</a>' if run_dir else ''}
    {f'<a href="{html.escape(_reports_api_href(run_dir, package_dir, pattern_report))}" class="status">JSON</a>' if run_dir else ''}
  </div>
"""
    if not run_dir:
        body = f"""
<header>
  <div>
    <h1>Report Hub</h1>
    <p class="subtle">只读预览 analyzer 报告，包含 module conflict 和 cross-work pattern synthesis。</p>
  </div>
  {header_actions}
</header>
{_reports_form()}
<section class="panel"><p class="empty">请输入 run 目录。页面只读取已有报告，不触发分析、重建或生成器写入。</p></section>
"""
        return _page("Report Hub", body)

    try:
        reports = build_review_reports(
            run_dir,
            package_dir=package_dir or None,
            pattern_report=pattern_report or None,
        )
        story_report = _story_analysis_report(run_dir)
    except Exception as exc:
        return _message_page("Reports 读取失败", f"{type(exc).__name__}: {exc}")

    review_link = "/review?" + urllib.parse.urlencode({"run_dir": run_dir, "package_dir": package_dir})
    output_dir = _resolve_output_dir(run_dir)
    body = f"""
<header>
  <div>
    <h1>Report Hub</h1>
    <p class="subtle mono">{html.escape(run_dir)}</p>
  </div>
  {header_actions}
</header>
{_reports_form(run_dir, package_dir, pattern_report)}
{_story_analysis_report_html(story_report, output_dir)}
<section class="summary-grid" aria-label="report hub summary">
  <div class="metric"><span class="subtle">Module Conflict</span><strong>{html.escape(reports["module_conflict_report"]["status"])}</strong>{_badge(reports["module_conflict_report"]["status"])}</div>
  <div class="metric"><span class="subtle">Conflicts</span><strong>{reports["module_conflict_report"]["conflict_count"]}</strong>{_badge(reports["module_conflict_report"]["state"])}</div>
  <div class="metric"><span class="subtle">Cross-work Pattern</span><strong>{html.escape(reports["cross_work_pattern_report"]["status"])}</strong>{_badge(reports["cross_work_pattern_report"]["status"])}</div>
  <div class="metric"><span class="subtle">Patterns</span><strong>{reports["cross_work_pattern_report"]["pattern_count"]}</strong>{_badge(reports["cross_work_pattern_report"]["state"])}</div>
</section>
<div class="stack">
  <section class="panel">
    <h2>Navigation</h2>
    <div class="actions" style="justify-content:flex-start">
      <a href="{html.escape(review_link)}" class="status">Run Review</a>
      <a href="/review/runs" class="status">Recent Runs</a>
    </div>
  </section>
  <div class="two-col">
    {_report_panel("Module Conflict Report", reports["module_conflict_report"])}
    {_report_panel("Cross-work Pattern Report", reports["cross_work_pattern_report"])}
  </div>
</div>
"""
    return _page("Report Hub", body)


def _runs_page() -> bytes:
    recent = discover_recent_runs(
        [
            ANALYSIS_RUNS_DIR,
            WEB_RUNS_DIR,
        ]
    )
    if recent:
        rows = "".join(
            "<tr>"
            f"<td class='mono'>{html.escape(item['name'])}</td>"
            f"<td class='mono'>{html.escape(item['path'])}</td>"
            f"<td>{html.escape(item['modified_at'])}</td>"
            f"<td><a class='status' href='/review?{html.escape(urllib.parse.urlencode({'run_dir': item['path']}))}'>Review</a></td>"
            "</tr>"
            for item in recent
        )
        table = f"<table><tr><th>Name</th><th>Path</th><th>Modified</th><th>Open</th></tr>{rows}</table>"
    else:
        table = "<p class='empty'>暂无可显示的 run。请先运行分析，或在 Review 页手动输入 run 目录。</p>"
    body = f"""
<header>
  <div>
    <h1>Recent Runs</h1>
    <p class="subtle">最近的本地分析 run，只读入口。</p>
  </div>
  <div class="actions"><a href="/review" class="status">Review</a><a href="/" class="status">分析入口</a></div>
</header>
<section class="panel">{table}</section>
"""
    return _page("Recent Runs", body)


def _arc_review_form(run_dir: str = "") -> str:
    return f"""
<form class="review-form" method="get" action="/review/arcs">
  <div>
    <label for="run_dir">Run 目录</label>
    <input id="run_dir" name="run_dir" type="text" value="{html.escape(run_dir)}" placeholder="例如：.../03_Analysis_Outputs/analysis_runs/xxx">
  </div>
  <div>
    <label for="unused_package_dir">状态</label>
    <input id="unused_package_dir" type="text" value="Arc review uses arcs/arc_candidates.json" disabled>
  </div>
  <button type="submit">打开</button>
</form>
"""


def _arc_review_script() -> str:
    return """
<script>
const arcReviewData = JSON.parse(document.getElementById("arc-review-data").textContent);
const state = {
  major_arcs: JSON.parse(JSON.stringify(arcReviewData.major_arcs || [])),
  sub_arcs: JSON.parse(JSON.stringify(arcReviewData.sub_arcs || [])),
};

function chaptersToText(chapters) {
  return Array.isArray(chapters) ? chapters.join(",") : "";
}

function textToChapters(value) {
  const chapters = new Set();
  String(value || "").replaceAll("，", ",").split(",").forEach((part) => {
    const text = part.trim();
    if (!text) return;
    if (text.includes("-")) {
      const pieces = text.split("-");
      const start = Number.parseInt(pieces[0].trim(), 10);
      const end = Number.parseInt(pieces[1].trim(), 10);
      for (let chapter = start; chapter <= end; chapter += 1) chapters.add(chapter);
    } else {
      chapters.add(Number.parseInt(text, 10));
    }
  });
  return Array.from(chapters).filter((item) => Number.isFinite(item)).sort((a, b) => a - b);
}

function defaultArc(level) {
  const stamp = Date.now();
  const firstChapter = arcReviewData.chapters?.[0]?.chapter_index || 1;
  const firstMajor = state.major_arcs[0]?.arc_candidate_id || "";
  return {
    arc_candidate_id: `${level}_manual_${stamp}`,
    arc_level: level,
    parent_candidate_id: level === "sub_arc" ? firstMajor : null,
    chapters_included: [firstChapter],
    stage_goal: "",
    stage_question: "",
    dominant_conflict: "",
    dominant_reader_experience: "",
    entry_state: {},
    exit_state: {},
    turning_points: [],
    why_boundary_starts_here: "",
    why_boundary_ends_here: "",
    boundary_score: 0,
    boundary_signals: [],
    review_status: "pending_user_review",
    confidence_score: 0.5,
  };
}

function field(value) {
  return value == null ? "" : String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function renderChapters() {
  const root = document.getElementById("chapters");
  root.innerHTML = "";
  (arcReviewData.chapters || []).forEach((chapter) => {
    const li = document.createElement("li");
    li.textContent = `${chapter.chapter_index}. ${chapter.title || chapter.source_title || chapter.chapter_id}`;
    root.appendChild(li);
  });
}

function renderArcTable(level, rows) {
  const tbody = document.getElementById(level === "major_arc" ? "major-body" : "sub-body");
  tbody.innerHTML = "";
  rows.forEach((arc, index) => {
    const parentCell = level === "sub_arc"
      ? `<input data-field="parent_candidate_id" value="${field(arc.parent_candidate_id)}">`
      : "<span class='empty'>-</span>";
    const tr = document.createElement("tr");
    tr.dataset.index = String(index);
    tr.innerHTML = `
      <td><input data-field="arc_candidate_id" value="${field(arc.arc_candidate_id)}"></td>
      <td>${parentCell}</td>
      <td><input data-field="chapters_included" value="${field(chaptersToText(arc.chapters_included))}" placeholder="1,2 or 1-3"></td>
      <td><textarea data-field="stage_goal">${field(arc.stage_goal)}</textarea></td>
      <td><textarea data-field="stage_question">${field(arc.stage_question)}</textarea></td>
      <td><textarea data-field="dominant_conflict">${field(arc.dominant_conflict)}</textarea></td>
      <td><textarea data-field="dominant_reader_experience">${field(arc.dominant_reader_experience)}</textarea></td>
      <td><input data-field="boundary_signals" value="${field((arc.boundary_signals || []).join(","))}"></td>
      <td><button type="button" class="danger" data-remove="${level}" data-index="${index}">Remove</button></td>
    `;
    tbody.appendChild(tr);
  });
}

function collectArcTable(level) {
  const rows = level === "major_arc" ? state.major_arcs : state.sub_arcs;
  const tbody = document.getElementById(level === "major_arc" ? "major-body" : "sub-body");
  Array.from(tbody.querySelectorAll("tr")).forEach((tr) => {
    const index = Number.parseInt(tr.dataset.index, 10);
    const arc = rows[index] || defaultArc(level);
    tr.querySelectorAll("[data-field]").forEach((input) => {
      const name = input.dataset.field;
      if (name === "chapters_included") {
        arc[name] = textToChapters(input.value);
      } else if (name === "boundary_signals") {
        arc[name] = String(input.value || "").split(",").map((item) => item.trim()).filter(Boolean);
      } else {
        arc[name] = input.value;
      }
    });
    arc.arc_level = level;
    if (level === "major_arc") arc.parent_candidate_id = null;
    arc.review_status = "pending_user_review";
    rows[index] = arc;
  });
}

function renderAll() {
  renderChapters();
  renderArcTable("major_arc", state.major_arcs);
  renderArcTable("sub_arc", state.sub_arcs);
}

function setStatus(message, kind = "missing") {
  const status = document.getElementById("arc-status");
  status.textContent = message;
  status.className = `status ${kind}`;
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.dataset.remove) {
    collectArcTable("major_arc");
    collectArcTable("sub_arc");
    const rows = target.dataset.remove === "major_arc" ? state.major_arcs : state.sub_arcs;
    rows.splice(Number.parseInt(target.dataset.index, 10), 1);
    renderAll();
    return;
  }
  if (target.id === "add-major") {
    collectArcTable("major_arc");
    collectArcTable("sub_arc");
    state.major_arcs.push(defaultArc("major_arc"));
    renderAll();
    return;
  }
  if (target.id === "add-sub") {
    collectArcTable("major_arc");
    collectArcTable("sub_arc");
    state.sub_arcs.push(defaultArc("sub_arc"));
    renderAll();
    return;
  }
  if (target.id === "save-review") {
    collectArcTable("major_arc");
    collectArcTable("sub_arc");
    setStatus("Saving...", "missing");
    const response = await fetch("/api/arc-review/save", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        run_dir: arcReviewData.run_dir,
        major_arcs: state.major_arcs,
        sub_arcs: state.sub_arcs,
        operation: document.getElementById("operation").value,
        reason: document.getElementById("reason").value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setStatus(payload.error || "Save failed", "bad");
      return;
    }
    arcReviewData.candidate_version = payload.candidate_version;
    arcReviewData.review = payload.review;
    setStatus(`Saved candidate_version=${payload.candidate_version}`, "ok");
    return;
  }
  if (target.id === "confirm-arcs") {
    setStatus("Confirming...", "missing");
    const response = await fetch("/api/arc-review/confirm", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({run_dir: arcReviewData.run_dir}),
    });
    const payload = await response.json();
    if (!response.ok) {
      setStatus(payload.error || "Confirm failed", "bad");
      return;
    }
    arcReviewData.review = payload.review;
    setStatus(`Confirmed version=${payload.review.confirmed_version}`, "ok");
  }
});

renderAll();
</script>
"""


def _arc_review_page(query_string: str = "") -> bytes:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    run_dir = (params.get("run_dir", [""])[0] or "").strip()
    if not run_dir:
        body = f"""
<header>
  <div>
    <h1>Arc Boundary Review</h1>
    <p class="subtle">调整 major/sub arc 边界，然后复用现有确认服务写出 confirmed arcs。</p>
  </div>
  <div class="actions"><a href="/review" class="status">Review</a></div>
</header>
{_arc_review_form()}
<section class="panel"><p class="empty">请输入 run 目录。</p></section>
"""
        return _page("Arc Boundary Review", body)

    try:
        payload = build_arc_review_editor(run_dir)
    except Exception as exc:
        return _message_page("Arc Review 读取失败", f"{type(exc).__name__}: {exc}")

    data_json = html.escape(json.dumps(payload, ensure_ascii=False))
    review_link = "/review?" + urllib.parse.urlencode({"run_dir": run_dir})
    rebuild_link = "/review/rebuild?" + urllib.parse.urlencode({"run_dir": run_dir})
    body = f"""
<header>
  <div>
    <h1>Arc Boundary Review</h1>
    <p class="subtle mono">{html.escape(run_dir)}</p>
  </div>
  <div class="actions">
    <a href="{html.escape(review_link)}" class="status">Run Review</a>
    <a href="{html.escape(rebuild_link)}" class="status">Rebuild</a>
    <a href="/" class="status">分析入口</a>
  </div>
</header>
{_arc_review_form(run_dir)}
<section class="summary-grid" aria-label="arc review status">
  <div class="metric"><span class="subtle">Review Status</span><strong>{html.escape(payload["review"].get("status", "unknown"))}</strong>{_badge(payload["review"].get("status", "unknown"))}</div>
  <div class="metric"><span class="subtle">Candidate Version</span><strong>{html.escape(str(payload["candidate_version"]))}</strong>{_badge("available")}</div>
  <div class="metric"><span class="subtle">Major Arcs</span><strong>{len(payload["major_arcs"])}</strong>{_badge("available")}</div>
  <div class="metric"><span class="subtle">Sub Arcs</span><strong>{len(payload["sub_arcs"])}</strong>{_badge("available")}</div>
</section>
<section class="panel">
  <h2>Chapters</h2>
  <ul id="chapters"></ul>
</section>
<section class="panel">
  <h2>Major Arcs</h2>
  <div class="table-scroll">
    <table class="arc-table">
      <thead><tr><th>ID</th><th>Parent</th><th>Chapters</th><th>Goal</th><th>Question</th><th>Conflict</th><th>Reader Experience</th><th>Signals</th><th>Action</th></tr></thead>
      <tbody id="major-body"></tbody>
    </table>
  </div>
</section>
<section class="panel">
  <h2>Sub Arcs</h2>
  <div class="table-scroll">
    <table class="arc-table">
      <thead><tr><th>ID</th><th>Parent</th><th>Chapters</th><th>Goal</th><th>Question</th><th>Conflict</th><th>Reader Experience</th><th>Signals</th><th>Action</th></tr></thead>
      <tbody id="sub-body"></tbody>
    </table>
  </div>
</section>
<section class="panel">
  <h2>Review Actions</h2>
  <div class="field">
    <label for="operation">操作类型</label>
    <select id="operation">
      <option value="move_boundary">move_boundary</option>
      <option value="split">split</option>
      <option value="merge">merge</option>
      <option value="rename">rename</option>
      <option value="change_parent">change_parent</option>
    </select>
  </div>
  <div class="field">
    <label for="reason">原因</label>
    <input id="reason" type="text" value="browser arc review">
  </div>
  <div class="button-row">
    <button type="button" id="add-major" class="secondary">Add Major Arc</button>
    <button type="button" id="add-sub" class="secondary">Add Sub Arc</button>
    <button type="button" id="save-review">Save Review</button>
    <button type="button" id="confirm-arcs">Confirm Arcs</button>
  </div>
  <span id="arc-status" class="status missing">Ready</span>
</section>
<script id="arc-review-data" type="application/json">{data_json}</script>
{_arc_review_script()}
"""
    return _page("Arc Boundary Review", body)


def _rebuild_form(run_dir: str = "", package_out: str = "") -> str:
    return f"""
<form class="review-form" method="get" action="/review/rebuild">
  <div>
    <label for="run_dir">Run 目录</label>
    <input id="run_dir" name="run_dir" type="text" value="{html.escape(run_dir)}" placeholder="例如：.../03_Analysis_Outputs/analysis_runs/xxx">
  </div>
  <div>
    <label for="package_out">New Handoff Package</label>
    <input id="package_out" name="package_out" type="text" value="{html.escape(package_out)}" placeholder="可留空，默认写入 run/rebuilds">
  </div>
  <button type="submit">打开</button>
</form>
"""


def _rebuild_script() -> str:
    return """
<script>
const rebuildData = JSON.parse(document.getElementById("rebuild-data").textContent);

function statusClass(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("blocked") || text.includes("failed") || text.includes("invalid")) return "bad";
  if (text.includes("awaiting") || text.includes("warning")) return "warn";
  if (text.includes("ready") || text.includes("completed") || text.includes("passed")) return "ok";
  return "missing";
}

function setRebuildStatus(message, kind = "missing") {
  const status = document.getElementById("rebuild-status");
  status.textContent = message;
  status.className = `status ${kind}`;
}

function showPayload(payload) {
  const output = document.getElementById("rebuild-output");
  output.textContent = JSON.stringify(payload, null, 2);
}

async function runRebuild(dryRun) {
  const packageOut = document.getElementById("package_out").value.trim();
  setRebuildStatus(dryRun ? "Dry run running..." : "Resume running...", "missing");
  const response = await fetch("/api/downstream-rebuild/resume", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      run_dir: rebuildData.run_dir,
      package_out: packageOut,
      dry_run: dryRun,
    }),
  });
  const payload = await response.json();
  showPayload(payload);
  if (!response.ok) {
    setRebuildStatus(payload.error || "Request failed", "bad");
    return;
  }
  const status = payload.result?.status || "unknown";
  setRebuildStatus(`${dryRun ? "Dry run" : "Resume"}: ${status}`, statusClass(status));
}

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.id === "dry-run") {
    runRebuild(true);
  }
  if (target.id === "run-resume") {
    runRebuild(false);
  }
});
</script>
"""


def _rebuild_page(query_string: str = "") -> bytes:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    run_dir = (params.get("run_dir", [""])[0] or "").strip()
    package_out = (params.get("package_out", [""])[0] or "").strip()
    if not run_dir:
        body = f"""
<header>
  <div>
    <h1>Downstream Rebuild Controls</h1>
    <p class="subtle">查看 invalidated downstream plan，并手动触发 dry-run 或 resume。</p>
  </div>
  <div class="actions"><a href="/review" class="status">Review</a></div>
</header>
{_rebuild_form()}
<section class="panel"><p class="empty">请输入 run 目录。打开页面只读取计划，不会触发重建。</p></section>
"""
        return _page("Downstream Rebuild Controls", body)

    try:
        controls = build_downstream_rebuild_controls(run_dir)
    except Exception as exc:
        return _message_page("Rebuild 读取失败", f"{type(exc).__name__}: {exc}")

    plan = controls["plan"]
    latest_report = controls["latest_report"]
    review_link = "/review?" + urllib.parse.urlencode({"run_dir": run_dir})
    arc_link = "/review/arcs?" + urllib.parse.urlencode({"run_dir": run_dir})
    api_link = "/api/downstream-rebuild-plan?" + urllib.parse.urlencode({"run_dir": run_dir})
    data_json = html.escape(json.dumps({"run_dir": run_dir}, ensure_ascii=False))
    disabled = "" if controls["can_run"] else " disabled"
    disabled_note = "" if controls["can_run"] else "<p class='empty'>当前没有 invalidated step，Run Resume 按钮已禁用。</p>"

    body = f"""
<header>
  <div>
    <h1>Downstream Rebuild Controls</h1>
    <p class="subtle mono">{html.escape(run_dir)}</p>
  </div>
  <div class="actions">
    <a href="{html.escape(review_link)}" class="status">Run Review</a>
    <a href="{html.escape(arc_link)}" class="status">Arc Review</a>
    <a href="{html.escape(api_link)}" class="status">JSON</a>
    <a href="/" class="status">分析入口</a>
  </div>
</header>
{_rebuild_form(run_dir, package_out)}
<section class="summary-grid" aria-label="downstream rebuild status">
  <div class="metric"><span class="subtle">Plan Status</span><strong>{html.escape(plan["status"])}</strong>{_badge(plan["status"])}</div>
  <div class="metric"><span class="subtle">Next Action</span><strong>{html.escape(plan["next_action"])}</strong>{_badge(plan["next_action"])}</div>
  <div class="metric"><span class="subtle">Invalidated Steps</span><strong>{len(plan["invalidated_step_ids"])}</strong>{_badge("ready" if controls["can_run"] else "noop")}</div>
  <div class="metric"><span class="subtle">Planned Stages</span><strong>{len(plan["planned_stages"])}</strong>{_badge("ready" if plan["planned_stages"] else "noop")}</div>
</section>
<div class="stack">
  <section class="panel">
    <h2>Plan</h2>
    {_rows([
        ("Status", plan["status"]),
        ("Next Action", plan["next_action"]),
        ("Planned Stages", plan["planned_stages"]),
        ("Invalidated Step IDs", plan["invalidated_step_ids"]),
        ("Invalidated Step Types", plan["invalidated_step_types"]),
    ])}
  </section>
  <section class="panel">
    <h2>Actions</h2>
    <p class="subtle">Dry Run 只返回计划，不写报告、不导出 handoff。Run Resume 会复用 v1 resume 流程并写入 downstream rebuild report。</p>
    {disabled_note}
    <div class="button-row">
      <button type="button" id="dry-run" class="secondary">Dry Run</button>
      <button type="button" id="run-resume"{disabled}>Run Resume</button>
    </div>
    <span id="rebuild-status" class="status missing">Ready</span>
    <pre id="rebuild-output">{html.escape(json.dumps(latest_report or {}, ensure_ascii=False, indent=2))}</pre>
  </section>
  <section class="panel">
    <h2>Latest Report</h2>
    {_format_value(latest_report)}
  </section>
</div>
<script id="rebuild-data" type="application/json">{data_json}</script>
{_rebuild_script()}
"""
    return _page("Downstream Rebuild Controls", body)


def _run_analysis(fields: dict[str, str]) -> tuple[int, bytes]:
    story_text = fields.get("story_text", "").strip()
    work_title = fields.get("work_title", "web_input_story").strip() or "web_input_story"
    mode = fields.get("mode", "single")
    model_provider = fields.get("model_provider", "deepseek").strip().lower() or "deepseek"
    legacy_temporary_key = fields.get("api_key", "").strip()
    deepseek_temporary_key = fields.get("deepseek_api_key", "").strip()
    qwen_temporary_key = fields.get("qwen_api_key", "").strip()

    if not story_text:
        return 400, _home("错误：故事文本不能为空。")
    if len(story_text) > MAX_TEXT_CHARS:
        return 400, _home(f"错误：文本过长，当前 {len(story_text)} 字符，限制 {MAX_TEXT_CHARS} 字符。")

    if model_provider not in SUPPORTED_MODEL_PROVIDERS:
        return 400, _home(f"Unsupported model provider: {model_provider}")

    env = _load_local_env()
    key_env = _model_key_env(model_provider)
    temporary_key = qwen_temporary_key if model_provider == "qwen" else deepseek_temporary_key
    temporary_key = temporary_key or legacy_temporary_key
    if temporary_key:
        env[key_env] = temporary_key
    env[MODEL_PROVIDER_ENV] = model_provider
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if not env.get(key_env):
        return 400, _home(f"Missing {key_env}. Enter a temporary key or configure .env.")

    safe_work_title = "".join(ch if ch.isalnum() or ch in "-_一二三四五六七八九十百千万章节回幕序尾声楔子" else "_" for ch in work_title)[:60]
    run_id = time.strftime("%Y%m%d_%H%M%S")
    run_root = WEB_RUNS_DIR / f"{run_id}_{safe_work_title}"
    input_dir = run_root / "input"
    output_dir = run_root / "output"
    input_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)

    if mode == "split":
        input_file = input_dir / "book.txt"
        input_file.write_text(story_text, encoding="utf-8")
        cmd = [
            sys.executable,
            str(CODE_DIR / "book_analyzer_v2.py"),
            "split",
            str(input_file),
            str(output_dir),
            "--model-provider",
            model_provider,
        ]
    else:
        input_file = input_dir / "001_web_input.txt"
        input_file.write_text(story_text, encoding="utf-8")
        cmd = [
            sys.executable,
            str(CODE_DIR / "book_analyzer_v2.py"),
            "folder",
            str(input_dir),
            str(output_dir),
            "--model-provider",
            model_provider,
        ]

    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(CODE_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    elapsed = time.time() - started

    stdout = (proc.stdout or "")[-6000:]
    stderr = (proc.stderr or "")[-4000:]
    status, http_status, manifest = _analysis_status_from_manifest(output_dir, proc.returncode)
    summary_html = ""
    model_summary_html = _model_runtime_summary_html(output_dir)
    issue_summary_html = _analysis_issue_summary_html(manifest)
    common_files_html = _common_files_html(output_dir)
    bundle_path = output_dir / "full_book_bundle.json"
    if bundle_path.exists():
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            chapter_count = len(bundle.get("chapters", []))
            arc_count = len(bundle.get("arcs", []))
            summary_html = f"<p>章节：{chapter_count}；弧段：{arc_count}</p>"
        except Exception:
            summary_html = ""

    body = f"""
<header>
  <div>
    <h1>分析{html.escape(status)}</h1>
    <p class="subtle">耗时 {elapsed:.1f} 秒</p>
  </div>
  <a href="/" class="status">返回</a>
</header>
  <section class="panel">
    {summary_html}
    {model_summary_html}
    {issue_summary_html}
    <p>输出目录：</p>
    <pre>{html.escape(str(output_dir))}</pre>
  {common_files_html}
  <h2>运行日志</h2>
  <pre>{html.escape(stdout)}</pre>
  {"<h2 class='error'>错误输出</h2><pre>" + html.escape(stderr) + "</pre>" if stderr else ""}
</section>
"""
    return http_status, _page("故事分析结果", body)


class AnalyzerHandler(BaseHTTPRequestHandler):
    server_version = "StoryAnalyzerUI/0.1"

    def _send(self, status: int, content: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, status: int, payload: dict) -> None:
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_POST_BYTES:
            raise ValueError("request body is too large")
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        payload = json.loads(body or "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html", "/analyze"}:
            self._send(200, _home())
            return
        if parsed.path == "/analyze/run":
            self._send(200, _analysis_progress_page(parsed.query))
            return
        if parsed.path == "/api/analyze-status":
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            run_dir = (query.get("run_dir", [""])[0] or "").strip()
            if not run_dir:
                self._send_json(400, {"error": "run_dir is required"})
                return
            try:
                self._send_json(200, _analysis_status_payload(run_dir))
            except Exception as exc:
                self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path == "/review":
            self._send(200, _review_page(parsed.query))
            return
        if parsed.path == "/review/runs":
            self._send(200, _runs_page())
            return
        if parsed.path == "/review/reports":
            self._send(200, _reports_page(parsed.query))
            return
        if parsed.path == "/review/arcs":
            self._send(200, _arc_review_page(parsed.query))
            return
        if parsed.path == "/review/rebuild":
            self._send(200, _rebuild_page(parsed.query))
            return
        if parsed.path == "/api/review-summary":
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            run_dir = (query.get("run_dir", [""])[0] or "").strip()
            package_dir = (query.get("package_dir", [""])[0] or "").strip()
            if not run_dir:
                self._send_json(400, {"error": "run_dir is required"})
                return
            try:
                self._send_json(200, build_review_summary(run_dir, package_dir=package_dir or None))
            except Exception as exc:
                self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path == "/api/review-reports":
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            run_dir = (query.get("run_dir", [""])[0] or "").strip()
            package_dir = (query.get("package_dir", [""])[0] or "").strip()
            pattern_report = (query.get("pattern_report", [""])[0] or "").strip()
            if not run_dir:
                self._send_json(400, {"error": "run_dir is required"})
                return
            try:
                payload = build_review_reports(
                    run_dir,
                    package_dir=package_dir or None,
                    pattern_report=pattern_report or None,
                )
                payload["story_analysis_report"] = _story_analysis_report(run_dir)
                self._send_json(200, payload)
            except Exception as exc:
                self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path == "/api/downstream-rebuild-plan":
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            run_dir = (query.get("run_dir", [""])[0] or "").strip()
            if not run_dir:
                self._send_json(400, {"error": "run_dir is required"})
                return
            try:
                self._send_json(200, build_downstream_rebuild_controls(run_dir))
            except Exception as exc:
                self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path == "/api/arc-review":
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            run_dir = (query.get("run_dir", [""])[0] or "").strip()
            if not run_dir:
                self._send_json(400, {"error": "run_dir is required"})
                return
            try:
                self._send_json(200, build_arc_review_editor(run_dir))
            except Exception as exc:
                self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        else:
            self._send(404, _page("Not Found", "<section class='panel'>Not Found</section>"))
            return

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/arc-review/save":
            try:
                payload = self._read_json_body()
                run_dir = str(payload.get("run_dir", "")).strip()
                if not run_dir:
                    raise ValueError("run_dir is required")
                result = save_arc_review_edits(
                    run_dir,
                    major_arcs=payload.get("major_arcs", []),
                    sub_arcs=payload.get("sub_arcs", []),
                    operation=payload.get("operation", "move_boundary"),
                    reason=str(payload.get("reason", "")),
                )
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(400, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path == "/api/arc-review/confirm":
            try:
                payload = self._read_json_body()
                run_dir = str(payload.get("run_dir", "")).strip()
                if not run_dir:
                    raise ValueError("run_dir is required")
                self._send_json(200, confirm_arc_review_edits(run_dir))
            except Exception as exc:
                self._send_json(400, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path == "/api/downstream-rebuild/resume":
            try:
                payload = self._read_json_body()
                run_dir = _optional_text(payload.get("run_dir", ""))
                if not run_dir:
                    raise ValueError("run_dir is required")
                result = run_downstream_rebuild_from_controls(
                    run_dir,
                    package_out=_optional_text(payload.get("package_out", "")) or None,
                    dry_run=_json_bool(payload.get("dry_run", False)),
                )
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(400, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path == "/api/analyze-resume":
            try:
                payload = self._read_json_body()
                fields = {key: str(value) if value is not None else "" for key, value in payload.items()}
                api_key = fields.get("api_key", "").strip()
                model_provider = fields.get("model_provider", "").strip().lower()
                if api_key and model_provider == "qwen":
                    fields["qwen_api_key"] = api_key
                elif api_key:
                    fields["deepseek_api_key"] = api_key
                self._send_json(200, _queue_resume_job(fields))
            except Exception as exc:
                self._send_json(400, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path != "/analyze":
            self._send(404, _page("Not Found", "<section class='panel'>Not Found</section>"))
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_POST_BYTES:
            self._send(
                413,
                _message_page(
                    "输入过长",
                    "请求体过大。当前网页入口支持最多 3,000,000 字符；中文文本提交时会被 URL 编码，体积会放大。\n"
                    "如果仍然超限，请先拆分文本，或使用命令行 folder/split 模式批处理。",
                ),
            )
            return
        body = self.rfile.read(length)
        try:
            fields = _parse_form_fields(self.headers.get("Content-Type", ""), body)
        except ValueError as exc:
            self._send(400, _home(f"错误：{exc}"))
            return
        try:
            job = _queue_analysis_job(fields)
        except ValueError as exc:
            self._send(400, _home(f"错误：{exc}"))
            return
        except Exception as exc:
            self._send(
                500,
                _message_page(
                "分析请求失败",
                    "服务端启动后台分析任务时发生错误，但服务仍在运行。\n"
                    f"{type(exc).__name__}: {exc}",
                ),
            )
            return
        target = job["status_url"]
        self.send_response(303)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        safe = fmt % args
        if "api_key" not in safe.lower():
            sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), safe))


def main() -> None:
    parser = argparse.ArgumentParser(description="Start local Story Analyzer web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    WEB_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), AnalyzerHandler)
    print(f"Story Analyzer UI running at http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
