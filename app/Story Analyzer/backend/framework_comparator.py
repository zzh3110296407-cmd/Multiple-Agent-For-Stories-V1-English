"""
framework_comparator.py — 跨作品 Framework 比较分析器
版本: 1.0

功能:
  读取多个 book_analyzer 输出目录，横向对比各作品的 framework 结构：
  1. 模块词条使用频率（哪些词是跨作品共有的，哪些是作品特有的）
  2. 大framework 结构序列对比（各章节用了哪些宏观节点）
  3. 模块词条共现分析（哪两个词条倾向于出现在同一章）
  4. 作品间相似度评分
  5. 输出 Markdown 报告 + JSON 数据

用法:
  # 指定多个输出目录
  python framework_comparator.py <输出目录1> <输出目录2> ...

  # 自动扫描根目录下所有有效输出
  python framework_comparator.py --scan <根目录>

  # 指定报告输出路径
  python framework_comparator.py --scan <根目录> --output report.md

示例:
  python framework_comparator.py 测试与输出/output_文章_A 测试与输出/output_文章_B
  python framework_comparator.py --scan 测试与输出/
"""

import json
import sys
import os
import argparse
from pathlib import Path
from collections import defaultdict, Counter
from itertools import combinations
from datetime import datetime
from typing import Optional

# ── 数据加载 ────────────────────────────────────────────────────────────────

def _guess_title(output_dir: Path, manifest: dict) -> str:
    """从目录名或 manifest 猜测作品标题。"""
    # 优先用目录名（去掉 output_ 前缀）
    name = output_dir.name
    for prefix in ["output_", "output-"]:
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
            break

    # 如果目录名本身有意义（非纯日期、非 clean 等通用名）就直接用
    generic = {"clean", "test", "output", "result", "latest"}
    if name and name.lower() not in generic and not name.isdigit():
        return name

    # 回退：从 manifest 第一章文件名里提取（去掉章节前缀"第X章_"）
    chapters = manifest.get("chapters", [])
    if chapters:
        fname = chapters[0].get("input_filename", "")
        # 去掉扩展名
        stem = Path(fname).stem
        # 去掉常见章节前缀
        import re
        stem = re.sub(r"^第\d+章[_\-\s]?", "", stem)
        if stem:
            return stem[:20]  # 截断，避免过长

    return output_dir.name or str(output_dir)


def load_work(output_dir: str | Path) -> Optional[dict]:
    """
    加载单个作品的分析结果。
    返回 dict 包含: title, chapters, book_framework, manifest
    """
    d = Path(output_dir)
    if not d.is_dir():
        print(f"⚠  目录不存在，跳过: {d}", file=sys.stderr)
        return None

    # 读 manifest
    manifest_path = d / "run_manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

    title = _guess_title(d, manifest)

    # 读所有章节 framework
    ch_dir = d / "chapters"
    chapter_data = []
    if ch_dir.is_dir():
        fw_files = sorted(ch_dir.glob("chapter_*_framework.json"))
        for fw_file in fw_files:
            with open(fw_file, encoding="utf-8") as f:
                fw = json.load(f)
            ch_idx = int(fw_file.stem.split("_")[1])
            chapter_data.append({
                "chapter_index": ch_idx,
                "framework": fw,
            })

    if not chapter_data:
        print(f"⚠  未找到章节数据，跳过: {d}", file=sys.stderr)
        return None

    # 读 book_framework
    book_fw = {}
    book_path = d / "book_framework.json"
    if book_path.exists():
        with open(book_path, encoding="utf-8") as f:
            book_fw = json.load(f)

    return {
        "title": title,
        "output_dir": str(d),
        "chapters": chapter_data,
        "book_framework": book_fw,
        "manifest": manifest,
        "total_chapters": len(chapter_data),
    }


def scan_output_dirs(root: str | Path) -> list[Path]:
    """在根目录下自动找所有含 run_manifest.json 的子目录。"""
    root = Path(root)
    found = []
    for subdir in sorted(root.iterdir()):
        if subdir.is_dir() and (subdir / "run_manifest.json").exists():
            found.append(subdir)
    return found


# ── 数据提取 ────────────────────────────────────────────────────────────────

def extract_module_labels(chapter_fw: dict) -> dict[str, list[str]]:
    """
    从章节 framework_package 提取各模块的词条标签。
    返回 {module_id: [label, ...]}
    """
    result = defaultdict(list)
    cv = chapter_fw.get("component_vocabulary", {})
    chapter_modules = cv.get("chapter_modules", [])
    for mod in chapter_modules:
        module_id = mod.get("module_id", "")
        for comp in mod.get("allowed_components", []):
            label = comp.get("label", "").strip()
            if label:
                result[module_id].append(label)
    return dict(result)


def extract_macro_nodes(chapter_fw: dict) -> list[str]:
    """
    提取章节使用的大 framework 宏观节点标签列表。
    """
    cv = chapter_fw.get("component_vocabulary", {})
    macro_comps = cv.get("macro_components", [])
    return [c.get("label", "") for c in macro_comps if c.get("label")]


# ── 统计计算 ────────────────────────────────────────────────────────────────

def compute_stats(works: list[dict]) -> dict:
    """
    对所有作品进行横向统计，返回完整统计结果。
    """
    n_works = len(works)

    # ── 1. 各模块词条频率 ──────────────────────────────────────────────────
    # term_work_count[module][label] = 使用该词条的作品数
    term_work_count: dict[str, Counter] = defaultdict(Counter)
    # term_chapter_count[work_title][module][label] = 出现章节数
    work_term_chapters: dict[str, dict[str, Counter]] = {}
    # 每部作品每章的词条集合（用于共现分析）
    work_chapter_labels: dict[str, list[dict[str, list[str]]]] = {}

    for work in works:
        title = work["title"]
        work_term_chapters[title] = defaultdict(Counter)
        work_chapter_labels[title] = []

        for ch in work["chapters"]:
            fw = ch["framework"]
            module_labels = extract_module_labels(fw)
            work_chapter_labels[title].append(module_labels)

            for mod_id, labels in module_labels.items():
                for label in labels:
                    work_term_chapters[title][mod_id][label] += 1

        # 标记该作品用了哪些词条
        for mod_id, counter in work_term_chapters[title].items():
            for label in counter:
                term_work_count[mod_id][label] += 1

    # ── 2. 分类词条 ────────────────────────────────────────────────────────
    universal_terms: dict[str, list[str]] = {}    # 所有作品都有
    common_terms: dict[str, list[str]] = {}        # 超过一半作品有
    unique_terms: dict[str, dict[str, list[str]]] = {}  # 只有一部作品有

    all_modules = set(term_work_count.keys())
    for mod_id in all_modules:
        univ, comm = [], []
        for label, cnt in term_work_count[mod_id].most_common():
            if cnt == n_works:
                univ.append(label)
            elif cnt > n_works / 2:
                comm.append(label)

        universal_terms[mod_id] = univ
        common_terms[mod_id] = comm

        # 唯一词条：按作品分组
        for work in works:
            t = work["title"]
            for label, cnt in term_work_count[mod_id].items():
                if cnt == 1 and label in work_term_chapters[t].get(mod_id, {}):
                    unique_terms.setdefault(t, {}).setdefault(mod_id, []).append(label)

    # ── 3. 大 framework 宏观节点序列 ──────────────────────────────────────
    macro_sequences: dict[str, list[list[str]]] = {}
    macro_node_work_count: Counter = Counter()

    for work in works:
        title = work["title"]
        seq = []
        used_nodes: set[str] = set()
        for ch in work["chapters"]:
            nodes = extract_macro_nodes(ch["framework"])
            seq.append(nodes)
            used_nodes.update(nodes)
        macro_sequences[title] = seq
        for node in used_nodes:
            macro_node_work_count[node] += 1

    # ── 4. 模块词条共现分析（同一章内跨模块） ──────────────────────────────
    # cooccur[(mod_a:label_a, mod_b:label_b)] = 共现章节数
    cooccur: Counter = Counter()
    total_chapters_analyzed = 0

    for work in works:
        for ch_labels in work_chapter_labels[work["title"]]:
            total_chapters_analyzed += 1
            # 把所有模块词条打平，带模块前缀
            tagged = []
            for mod_id, labels in ch_labels.items():
                for label in labels:
                    tagged.append(f"{mod_id}:{label}")
            # 统计两两共现（跨模块）
            for a, b in combinations(sorted(set(tagged)), 2):
                mod_a = a.split(":")[0]
                mod_b = b.split(":")[0]
                if mod_a != mod_b:
                    cooccur[(a, b)] += 1

    top_cooccur = cooccur.most_common(20)

    # ── 5. 作品相似度（基于词条 Jaccard） ─────────────────────────────────
    work_label_sets: dict[str, set[str]] = {}
    for work in works:
        title = work["title"]
        labels: set[str] = set()
        for mod_id, counter in work_term_chapters[title].items():
            for label in counter:
                labels.add(f"{mod_id}:{label}")
        work_label_sets[title] = labels

    similarity_matrix: dict[tuple[str, str], float] = {}
    for (t1, s1), (t2, s2) in combinations(work_label_sets.items(), 2):
        inter = len(s1 & s2)
        union = len(s1 | s2)
        sim = inter / union if union > 0 else 0.0
        similarity_matrix[(t1, t2)] = round(sim, 3)

    # ── 6. 各模块词条完整频率表 ───────────────────────────────────────────
    module_frequency_table: dict[str, list[dict]] = {}
    for mod_id in sorted(all_modules):
        rows = []
        for label, work_cnt in term_work_count[mod_id].most_common():
            # 统计每部作品出现次数
            per_work = {
                w["title"]: work_term_chapters[w["title"]].get(mod_id, {}).get(label, 0)
                for w in works
            }
            rows.append({
                "label": label,
                "works_count": work_cnt,
                "per_work": per_work,
            })
        module_frequency_table[mod_id] = rows

    return {
        "meta": {
            "works_analyzed": n_works,
            "work_titles": [w["title"] for w in works],
            "total_chapters": sum(w["total_chapters"] for w in works),
            "generated_at": datetime.now().isoformat(),
        },
        "module_frequency_table": module_frequency_table,
        "universal_terms": universal_terms,
        "common_terms": common_terms,
        "unique_terms": unique_terms,
        "macro_sequences": macro_sequences,
        "macro_node_work_count": dict(macro_node_work_count),
        "top_cooccurrence": [
            {"pair": list(pair), "count": cnt}
            for pair, cnt in top_cooccur
        ],
        "similarity_matrix": {
            f"{t1} × {t2}": sim
            for (t1, t2), sim in similarity_matrix.items()
        },
    }


# ── 报告生成 ────────────────────────────────────────────────────────────────

def _module_display_name(module_id: str) -> str:
    names = {
        "chapter_function":     "篇章功能",
        "reader_emotion":       "读者情绪",
        "character_desire":     "角色欲望",
        "character_arc":        "人物弧光",
        "conflict":             "冲突",
        "information_release":  "信息释放",
        "style_pacing":         "风格节奏",
        "macro_framework_basic":"大框架基础节点",
        "macro_framework_graph":"大框架图结构",
    }
    return names.get(module_id, module_id)


def generate_markdown_report(stats: dict, works: list[dict]) -> str:
    meta = stats["meta"]
    titles = meta["work_titles"]
    n = meta["works_analyzed"]
    lines = []

    lines.append("# 跨作品 Framework 比较报告")
    lines.append(f"\n生成时间：{meta['generated_at'][:19]}")
    lines.append(f"\n**分析作品**：{'、'.join(titles)}（共 {n} 部，{meta['total_chapters']} 章）\n")

    # ── 作品概览 ──────────────────────────────────────────────────────────
    lines.append("---\n## 一、作品概览\n")
    lines.append("| 作品 | 章节数 | 总词条数 |")
    lines.append("|------|--------|----------|")
    for work in works:
        t = work["title"]
        total_labels = sum(
            len(labels)
            for ch in work["chapters"]
            for labels in extract_module_labels(ch["framework"]).values()
        )
        lines.append(f"| {t} | {work['total_chapters']} | {total_labels} |")

    # ── 作品相似度 ────────────────────────────────────────────────────────
    if stats["similarity_matrix"]:
        lines.append("\n---\n## 二、作品相似度（词条 Jaccard 系数）\n")
        lines.append("> 0 = 完全不同，1 = 完全相同；0.3 以上视为风格相近\n")
        lines.append("| 作品对 | 相似度 | 判断 |")
        lines.append("|--------|--------|------|")
        for pair_key, sim in stats["similarity_matrix"].items():
            judge = "风格相近" if sim >= 0.3 else ("有共性" if sim >= 0.15 else "差异显著")
            lines.append(f"| {pair_key} | {sim:.3f} | {judge} |")

    # ── 普遍规律（所有作品共有词条） ─────────────────────────────────────
    lines.append("\n---\n## 三、跨作品普遍规律\n")
    lines.append("> 以下词条在**所有**分析作品中均出现，是叙事的通用构件。\n")
    has_universal = False
    for mod_id, labels in stats["universal_terms"].items():
        if labels:
            has_universal = True
            lines.append(f"**{_module_display_name(mod_id)}**：{'、'.join(labels)}")
    if not has_universal:
        lines.append("_（目前只有一部作品，需分析更多作品后才能找出普遍规律）_")

    # 超过半数出现
    half_terms = {m: l for m, l in stats["common_terms"].items() if l}
    if half_terms and n >= 3:
        lines.append("\n**超过半数作品共有**：")
        for mod_id, labels in half_terms.items():
            if labels:
                lines.append(f"- {_module_display_name(mod_id)}：{'、'.join(labels)}")

    # ── 大 framework 宏观节点 ──────────────────────────────────────────────
    lines.append("\n---\n## 四、大 Framework 宏观节点结构\n")

    for work in works:
        t = work["title"]
        seq = stats["macro_sequences"][t]
        lines.append(f"### {t}\n")
        lines.append("| 章节 | 宏观节点 |")
        lines.append("|------|----------|")
        for i, nodes in enumerate(seq, 1):
            lines.append(f"| 第 {i} 章 | {'→'.join(nodes) if nodes else '（无）'} |")
        lines.append("")

    if n >= 2:
        lines.append("**跨作品出现的宏观节点**：\n")
        lines.append("| 节点 | 出现作品数 |")
        lines.append("|------|-----------|")
        for node, cnt in sorted(stats["macro_node_work_count"].items(),
                                key=lambda x: -x[1]):
            lines.append(f"| {node} | {cnt}/{n} |")

    # ── 各模块词条频率表 ──────────────────────────────────────────────────
    lines.append("\n---\n## 五、各模块词条频率表\n")

    CHAPTER_MODULES = [
        "chapter_function", "reader_emotion", "character_desire",
        "character_arc", "conflict", "information_release", "style_pacing"
    ]

    for mod_id in CHAPTER_MODULES:
        rows = stats["module_frequency_table"].get(mod_id, [])
        if not rows:
            continue
        lines.append(f"### {_module_display_name(mod_id)}\n")
        header = "| 词条 | 出现作品数 |" + "".join(f" {t} |" for t in titles)
        sep    = "|------|-----------|" + "".join("-----|" for _ in titles)
        lines.append(header)
        lines.append(sep)
        for row in rows:
            per = "".join(f" {row['per_work'].get(t, 0)} |" for t in titles)
            lines.append(f"| {row['label']} | {row['works_count']}/{n} |{per}")
        lines.append("")

    # ── 作品特有词条 ──────────────────────────────────────────────────────
    if stats["unique_terms"] and n >= 2:
        lines.append("\n---\n## 六、各作品特有词条\n")
        lines.append("> 只出现在单一作品中，反映该作品独特的叙事选择。\n")
        for title, mods in stats["unique_terms"].items():
            lines.append(f"### {title}\n")
            for mod_id, labels in mods.items():
                if labels:
                    lines.append(f"- **{_module_display_name(mod_id)}**：{'、'.join(labels)}")
            lines.append("")

    # ── 词条共现 ──────────────────────────────────────────────────────────
    if stats["top_cooccurrence"] and n >= 2:
        lines.append("\n---\n## 七、高频词条共现（同章出现）\n")
        lines.append("> 反映叙事策略的组合规律。\n")
        lines.append("| 词条 A | 词条 B | 共现章节数 |")
        lines.append("|--------|--------|-----------|")
        for item in stats["top_cooccurrence"][:15]:
            a, b = item["pair"]
            # 去掉模块前缀，只显示标签
            a_label = a.split(":", 1)[1] if ":" in a else a
            b_label = b.split(":", 1)[1] if ":" in b else b
            a_mod   = _module_display_name(a.split(":")[0])
            b_mod   = _module_display_name(b.split(":")[0])
            lines.append(f"| {a_label}（{a_mod}）| {b_label}（{b_mod}）| {item['count']} |")

    # ── 单作品模式（只有1部时的特别输出） ────────────────────────────────
    if n == 1:
        lines.append("\n---\n## 补充：单作品章节对比\n")
        lines.append("> 目前只有一部作品，以下展示章节间的词条差异。\n")
        work = works[0]
        all_module_ids = sorted({
            mod_id
            for ch in work["chapters"]
            for mod_id in extract_module_labels(ch["framework"]).keys()
        })
        for mod_id in all_module_ids:
            if mod_id not in CHAPTER_MODULES:
                continue
            lines.append(f"\n**{_module_display_name(mod_id)}**\n")
            lines.append("| 章节 | 使用词条 |")
            lines.append("|------|----------|")
            for ch in work["chapters"]:
                labels = extract_module_labels(ch["framework"]).get(mod_id, [])
                lines.append(f"| 第 {ch['chapter_index']} 章 | {'、'.join(labels) if labels else '—'} |")

    lines.append("\n---\n_报告由 framework_comparator.py 自动生成_")
    return "\n".join(lines)


def print_console_summary(stats: dict) -> None:
    meta = stats["meta"]
    titles = meta["work_titles"]
    n = meta["works_analyzed"]

    print(f"\n{'='*60}")
    print(f"  跨作品 Framework 比较  |  {n} 部作品  {meta['total_chapters']} 章")
    print(f"{'='*60}")
    print(f"  作品：{' / '.join(titles)}")

    if stats["similarity_matrix"]:
        print("\n  作品相似度：")
        for pair, sim in stats["similarity_matrix"].items():
            print(f"    {pair} = {sim:.3f}")

    print("\n  跨作品共有词条（所有作品均出现）：")
    has = False
    for mod_id, labels in stats["universal_terms"].items():
        if labels:
            has = True
            print(f"    [{_module_display_name(mod_id)}] {' / '.join(labels)}")
    if not has:
        print("    （需更多作品才能统计）")

    print("\n  大框架宏观节点分布：")
    for node, cnt in sorted(stats["macro_node_work_count"].items(), key=lambda x: -x[1]):
        print(f"    {node:20s}  {cnt}/{n} 部作品")

    if stats["top_cooccurrence"] and n >= 2:
        print("\n  Top-5 词条共现：")
        for item in stats["top_cooccurrence"][:5]:
            a, b = item["pair"]
            a_l = a.split(":", 1)[1] if ":" in a else a
            b_l = b.split(":", 1)[1] if ":" in b else b
            print(f"    {a_l} + {b_l}  ({item['count']} 次)")

    print(f"{'='*60}\n")


# ── 主入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="跨作品 Framework 比较分析器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("dirs", nargs="*", help="book_analyzer 输出目录")
    parser.add_argument("--scan", metavar="ROOT", help="自动扫描根目录下所有有效输出目录")
    parser.add_argument("--titles", nargs="*", metavar="TITLE",
                        help="手动指定各目录对应的作品标题（顺序与 dirs 一致）")
    parser.add_argument("--output", metavar="FILE", default="",
                        help="Markdown 报告输出路径（默认：comparison_report_YYYYMMDD.md）")
    parser.add_argument("--json", metavar="FILE", default="",
                        help="JSON 数据输出路径（默认：comparison_data_YYYYMMDD.json）")
    args = parser.parse_args()

    # 收集目录
    dirs: list[Path] = []
    if args.scan:
        dirs = scan_output_dirs(args.scan)
        if not dirs:
            print(f"⚠  在 {args.scan} 下未找到任何有效输出目录", file=sys.stderr)
            sys.exit(1)
        print(f"🔍 扫描到 {len(dirs)} 个输出目录：{[d.name for d in dirs]}")
    for d in args.dirs:
        dirs.append(Path(d))

    if not dirs:
        parser.print_help()
        sys.exit(0)

    # 加载作品
    works = []
    custom_titles = args.titles or []
    for i, d in enumerate(dirs):
        work = load_work(d)
        if work:
            if i < len(custom_titles):
                work["title"] = custom_titles[i]
            works.append(work)
            print(f"✅ 加载：{work['title']}  ({work['total_chapters']} 章)")

    if not works:
        print("❌ 没有有效作品数据", file=sys.stderr)
        sys.exit(1)

    # 计算统计
    print(f"\n📊 正在计算 {len(works)} 部作品的 framework 比较...")
    stats = compute_stats(works)

    # 控制台摘要
    print_console_summary(stats)

    # 输出报告
    today = datetime.now().strftime("%Y%m%d")
    output_dir = Path(works[0]["output_dir"]).parent

    md_path = Path(args.output) if args.output else output_dir / f"comparison_report_{today}.md"
    json_path = Path(args.json) if args.json else output_dir / f"comparison_data_{today}.json"

    report = generate_markdown_report(stats, works)
    md_path.write_text(report, encoding="utf-8")
    print(f"📄 Markdown 报告：{md_path}")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"📦 JSON 数据：{json_path}")


if __name__ == "__main__":
    main()
