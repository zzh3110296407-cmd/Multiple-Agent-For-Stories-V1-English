#!/usr/bin/env python3
"""
网页文本提取器
从网页或网页目录页批量提取正文内容，保存为纯文本文件。

用法:
  # 单页提取
  python web_extractor.py https://example.com/article.html -o output.txt

  # 目录页批量提取（每页一个文件）
  python web_extractor.py https://example.com/book/ --index --split -o ./output_dir/

  # 目录页批量提取（合并为一个文件）
  python web_extractor.py https://example.com/book/ --index --merge -o ./output_dir/全文.txt

  # 目录页 + 只抓匹配的链接
  python web_extractor.py https://example.com/book/ --index --split --filter "第.*幕|序幕" -o ./output_dir/

  # 目录页 + 指定页码范围
  python web_extractor.py https://example.com/book/ --index --merge --range 1-47 -o ./全文.txt

选项:
  -o, --output      输出路径（文件或目录，默认当前目录）
  --index           目录页模式：从目录页提取链接，逐页抓取
  --split           每页保存为单独文件（默认，需配合 --index）
  --merge           所有页合并为一个文件（需配合 --index）
  --filter REGEX    只抓取链接文本匹配正则的页面
  --range N-M       只抓取第N到第M个链接（从1开始）
  --selector CSS    自定义正文区域 CSS 选择器（如 .content, #article）
  --delay N         请求间隔秒数（默认1）
  --encoding ENC    强制指定编码（默认自动检测）
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    raise RuntimeError("缺少依赖 beautifulsoup4。请先运行：python -m pip install -r requirements.txt")


# ── 核心函数 ──────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

SKIP_LINE_PATTERNS = re.compile(
    r"^(首页|上一页|下一页|上一篇|下一篇|目录|返回|©|版权|备案|ICP|"
    r"广告|关于我们|联系|分享|点赞|收藏|举报|评论|登录|注册|"
    r"Copyright|All Rights Reserved)"
)

CONTENT_SELECTORS = [
    "article",
    ".article-content",
    ".post-content",
    ".entry-content",
    ".content",
    ".text",
    "#content",
    "#article",
    "main",
    ".main-content",
    ".book-content",
    ".chapter-content",
    ".read-content",
]


def fetch_page(url: str, encoding: str | None = None, max_retry: int = 5, delay: float = 3) -> str:
    """抓取单个页面，返回 HTML 文本"""
    for attempt in range(max_retry):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if encoding:
                resp.encoding = encoding
            else:
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as e:
            if attempt < max_retry - 1:
                print(f" 重试({attempt+1})...", end="", flush=True)
                time.sleep(delay)
            else:
                raise RuntimeError(f"抓取失败（{max_retry}次重试）: {e}")


def extract_text(html: str, selector: str | None = None) -> str:
    """从 HTML 中提取正文文本"""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "aside"]):
        tag.decompose()

    content = None

    if selector:
        content = soup.select_one(selector)
        if not content:
            print(f"  ⚠ 选择器 '{selector}' 未匹配，回退自动检测", flush=True)

    if not content:
        for sel in CONTENT_SELECTORS:
            content = soup.select_one(sel)
            if content:
                break

    if not content:
        body = soup.find("body")
        if body:
            divs = body.find_all("div")
            if divs:
                content = max(divs, key=lambda d: len(d.get_text(strip=True)))
            else:
                content = body

    if not content:
        return ""

    raw_text = content.get_text("\n", strip=True)

    lines = []
    for line in raw_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if SKIP_LINE_PATTERNS.match(line):
            continue
        if len(line) < 3 and re.match(r"^\d+$", line):
            continue
        lines.append(line)

    return "\n".join(lines)


def extract_links(html: str, base_url: str, filter_regex: str | None = None) -> list[dict]:
    """从目录页提取内容链接"""
    soup = BeautifulSoup(html, "html.parser")

    links = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not text or len(text) > 100:
            continue

        full_url = urljoin(base_url, href)

        if full_url == base_url or full_url in seen_urls:
            continue
        if not full_url.startswith(("http://", "https://")):
            continue
        # 排除明显的非内容链接
        if any(kw in href.lower() for kw in ["javascript:", "mailto:", "#", "login", "register", "search"]):
            continue

        seen_urls.add(full_url)
        links.append({"title": text, "url": full_url})

    if filter_regex:
        pat = re.compile(filter_regex)
        links = [l for l in links if pat.search(l["title"])]

    return links


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name[:80] if name else "untitled"


# ── 主流程 ────────────────────────────────────────────

def run_single(url: str, output: str, selector: str | None, encoding: str | None):
    """单页模式"""
    print(f"抓取: {url}")
    html = fetch_page(url, encoding=encoding)
    text = extract_text(html, selector=selector)

    out_path = Path(output)
    if out_path.is_dir():
        out_path = out_path / "extracted.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    print(f"✅ 完成：{len(text)} 字 → {out_path}")


def run_index(url: str, output: str, merge: bool, selector: str | None,
              filter_regex: str | None, page_range: str | None,
              delay: float, encoding: str | None):
    """目录页模式"""
    print(f"抓取目录页: {url}")
    html = fetch_page(url, encoding=encoding)
    links = extract_links(html, url, filter_regex=filter_regex)

    if not links:
        print("❌ 未找到任何内容链接")
        print("  提示：尝试用 --filter 指定链接文本的正则匹配")
        return

    if page_range:
        m = re.match(r"(\d+)-(\d+)", page_range)
        if m:
            start, end = int(m.group(1)) - 1, int(m.group(2))
            links = links[start:end]

    print(f"找到 {len(links)} 个链接:")
    for i, l in enumerate(links[:10], 1):
        print(f"  [{i}] {l['title']}")
    if len(links) > 10:
        print(f"  ... 共 {len(links)} 个")

    out_path = Path(output)
    if merge:
        if out_path.suffix not in (".txt", ".md"):
            out_path = out_path / "全文.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path.mkdir(parents=True, exist_ok=True)

    all_texts = []
    total = len(links)
    success = 0

    for i, link in enumerate(links):
        idx = i + 1
        title = link["title"]
        print(f"[{idx:>3}/{total}] {title[:30]}  ...", end="", flush=True)

        try:
            page_html = fetch_page(link["url"], encoding=encoding)
            text = extract_text(page_html, selector=selector)
        except Exception as e:
            print(f"  ❌ {e}")
            continue

        if merge:
            all_texts.append(f"{'='*40}\n{title}\n{'='*40}\n\n{text}")
        else:
            filename = f"{idx:03d}_{sanitize_filename(title)}.txt"
            file_path = out_path / filename
            file_path.write_text(text, encoding="utf-8")

        success += 1
        print(f"  ✓ {len(text)} 字")

        if idx < total:
            time.sleep(delay)

    if merge:
        full_text = "\n\n\n".join(all_texts)
        out_path.write_text(full_text, encoding="utf-8")
        print(f"\n✅ 完成：{success}/{total} 页，共 {len(full_text)} 字 → {out_path}")
    else:
        print(f"\n✅ 完成：{success}/{total} 页，文件保存在 {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="网页文本提取器 — 从网页或目录页批量提取正文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="目标网页 URL")
    parser.add_argument("-o", "--output", default=".", help="输出路径（文件或目录）")
    parser.add_argument("--index", action="store_true", help="目录页模式：提取链接并逐页抓取")
    parser.add_argument("--split", action="store_true", help="每页单独保存（默认）")
    parser.add_argument("--merge", action="store_true", help="所有页合并为一个文件")
    parser.add_argument("--filter", dest="filter_regex", help="链接文本的正则过滤器")
    parser.add_argument("--range", dest="page_range", help="链接范围，如 1-47")
    parser.add_argument("--selector", help="正文区域的 CSS 选择器")
    parser.add_argument("--delay", type=float, default=1.0, help="请求间隔秒数（默认1）")
    parser.add_argument("--encoding", help="强制指定编码（默认自动检测）")

    args = parser.parse_args()

    if args.index:
        run_index(
            url=args.url,
            output=args.output,
            merge=args.merge,
            selector=args.selector,
            filter_regex=args.filter_regex,
            page_range=args.page_range,
            delay=args.delay,
            encoding=args.encoding,
        )
    else:
        run_single(
            url=args.url,
            output=args.output,
            selector=args.selector,
            encoding=args.encoding,
        )


if __name__ == "__main__":
    main()
