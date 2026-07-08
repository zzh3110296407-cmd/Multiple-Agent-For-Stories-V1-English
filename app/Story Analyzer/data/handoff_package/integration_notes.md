# 接入说明 — Framework 词库交付包

生成时间：2026-06-17 11:44

分析基础：3 部小说 · 88 个词条

## 文件说明

| 文件 | 用途 |
|------|------|
| `recommended_framework.json` | 核心交付：直接可用的 component_vocabulary，格式与现有 framework_package schema 完全兼容 |
| `vocabulary_export.json` | 完整词库，含每个词条的可靠性分级、使用统计和示例 |
| `cross_novel_patterns.md` | 跨作品规律报告，适合 review 和讨论 |
| `integration_notes.md` | 本文件 |

## 如何使用 recommended_framework.json

```python
import json

with open('recommended_framework.json') as f:
    fw = json.load(f)

# 获取章节模块（直接替换/补充你的 component_vocabulary.chapter_modules）
chapter_modules = fw['component_vocabulary']['chapter_modules']

# 获取宏观节点
macro_components = fw['component_vocabulary']['macro_components']

# 只取跨作品验证的词条作为强默认值
for module in chapter_modules:
    verified = [c for c in module['allowed_components']
                if c['reliability'] == 'verified']
    tentative = [c for c in module['allowed_components']
                 if c['reliability'] == 'tentative']
```

## reliability 字段说明

| 值 | 含义 | 建议处理 |
|-----|------|---------|
| `verified` | 已在 ≥1 部小说中出现，跨作品验证 | 作为 `system_default` 强约束 |
| `tentative` | 仅在 1 部小说中出现，待验证 | 作为候选池 |
| `defined` | 系统预定义，暂无分析数据 | 作为扩展备选 |

## reader_emotion 模块特别说明

该模块的词条附带 `valence`（情绪效价）和 `arousal`（唤起强度）字段：

```json
{
  "label": "紧张",
  "valence": "negative",
  "arousal": "high",
  "normalized_hint": "..."
}
```

生成器可利用这两个维度做情绪路径规划，而不只是依赖标签名。

## 词库持续更新说明

每分析一部新小说，运行：
```bash
python book_analyzer.py folder <章节目录>
python vocabulary_manager.py pending   # 审核新词条
python framework_synthesizer.py        # 重新生成交付包
```

词库会自动积累 `usage_count`，随着分析作品增多，`verified` 词条会越来越多。