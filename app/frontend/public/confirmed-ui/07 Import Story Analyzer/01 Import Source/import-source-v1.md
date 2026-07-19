# 07es Branch / 导入源 UI V1

Date: 2026-07-03

## 页面定位

导入源是 Framework 编排里的 Analyze Stories 分支入口。用户从 Framework 编排选择“分析器”后先进入此页，完成故事源或分析器产物的导入，再进入后续的分析、报告查看、Framework 候选和导入编辑会话。

该页只负责“接收源内容”和“进入分析”。不在第一屏提前展示报告、候选、编辑会话或正式激活决策。

## 用户界面结构

1. 顶部
   - 返回 Framework
   - 面包屑：主页 / 当前项目 / Framework 编排 / 导入源
   - 导入记录入口

2. 左侧：导入来源
   - 粘贴故事
   - 上传文件
   - 章节包
   - 分析器输出
   - 来源信息：作品名、来源备注、文件名

3. 中间：源内容
   - 大面积编辑区
   - 类型选择：自动识别、完整书卷、故事分析报告、Framework 包、跨章节状态包
   - 摘要指标：字数、章节、源类型、状态

4. 右侧：导入边界
   - 当前状态
   - 导入边界
   - 后续路径
   - 主要动作：保存源草稿、开始分析

## 交互

- 点击导入来源，会切换中间编辑区标题、来源指标和选中状态。
- “选择文件”会打开本地文件选择器；txt、md、json 会在原型里直接读取预览，其它格式显示抽取占位状态。
- 编辑区支持拖拽文件导入。
- json 文件会尝试自动推断 `declared_file_kind`。
- 类型选择对应 `declared_file_kind`，默认空值代表后端自动识别。
- 编辑区输入后，字数、章节估计、状态会即时更新。
- “保存源草稿”会写入浏览器本地草稿并同步到导入记录抽屉，不写入正式 Framework。
- “导入记录”打开右侧抽屉，展示当前源草稿和历史示例记录。
- 顶部流程和右侧路径节点可点击，提供当前阶段反馈。
- “开始分析”会先做空内容校验和 JSON 格式校验，再进入 Analyze Stories 后续分析页。
- 开始分析时按钮进入“分析中”状态，并将流程高亮切到“分析”。

## 当前 Phase 8.5 接口映射

Phase 8.5 已有的直接接口是 Analyze Stories artifact 导入，当前可稳定对接分析器输出、完整书卷包、故事分析报告、Framework 包、跨章节状态包等 JSON 对象。

导入：

```ts
POST /api/analyze-stories/imports
body: {
  declared_file_kind?: "framework_package"
    | "story_analysis_report"
    | "full_book_bundle"
    | "cross_chapter_state_package"
    | "",
  original_filename?: string | null,
  artifact: Record<string, unknown>
}
```

前端封装：

```ts
importAnalyzeStoriesArtifact({
  artifact,
  declaredFileKind,
  originalFilename,
})
```

返回核心字段：

```ts
type AnalyzeStoriesImportResult = {
  success: boolean;
  import_id: string;
  manifest: {
    import_id: string;
    import_status: "received" | "parsed" | "validated_with_warnings" | "blocked" | "ready_for_m2";
    parse_status: "not_parsed" | "parsed" | "parse_failed";
    file_kinds: string[];
    story_analysis_report_ref_ids: string[];
  };
  artifact?: {
    artifact_id: string;
    file_kind: "framework_package" | "story_analysis_report" | "full_book_bundle" | "cross_chapter_state_package" | "unknown";
    original_filename?: string | null;
    content_length: number;
    raw_storage_status: "stored" | "redacted" | "hash_only" | "blocked";
    parse_status: "not_parsed" | "parsed" | "parse_failed";
    safe_summary: string;
  } | null;
  input_fingerprints: Array<{
    fingerprint_id: string;
    input_filename?: string | null;
    chapter_index?: number | null;
    input_title?: string | null;
    text_length?: number | null;
    completeness_status: "complete" | "partial" | "missing";
  }>;
  story_analysis_report_refs: Array<{
    story_analysis_report_ref_id: string;
    viewer_status: "available" | "missing" | "invalid" | "blocked";
    review_status: "not_reviewed";
    safe_title?: string | null;
    safe_summary?: string | null;
  }>;
  validation_report: {
    passed: boolean;
    can_proceed_to_m2: boolean;
    blocking_issues: Array<{ code: string; message: string; safe_detail?: string | null }>;
    warnings: Array<{ code: string; message: string; safe_detail?: string | null }>;
    detected_file_kinds: string[];
    missing_recommended_fields: string[];
    requires_user_confirmation: boolean;
    safe_summary: string;
  };
}
```

读取记录：

- `GET /api/analyze-stories/imports`
- `GET /api/analyze-stories/imports/{import_id}`
- `POST /api/analyze-stories/imports/{import_id}/revalidate`

## 原始故事文本说明

本页视觉上预留“粘贴故事 / 上传文件 / 章节包”的用户入口。若 Codes 需要在 Phase 8.5 当前接口上落地，建议分两层实现：

- 当前可接：导入 Analyze Stories JSON artifact，直接调用 `POST /api/analyze-stories/imports`。
- 后续增强：原始文本、docx、pdf、txt 先进入故事分析器执行层，生成 Analyze Stories artifact 后再调用上述导入接口。

在未加入原始文本分析执行接口前，不要把普通故事正文直接提交给 `POST /api/analyze-stories/imports`，否则后端会按 JSON artifact 解析，结果不可控。

## 可视化稿

- `visual-drafts/import-source-v1.html`
- `visual-drafts/import-source-v1.png`
