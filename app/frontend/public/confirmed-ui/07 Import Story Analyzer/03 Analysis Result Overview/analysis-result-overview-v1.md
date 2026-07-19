# 07es Branch / 分析结果总览 UI V1

Date: 2026-07-03

## 页面定位

分析结果总览是 Analyze Stories 分支在分析完成后的第一张审阅页。它承接“分析中”状态，向用户展示导入记录、校验报告、报告引用和 Framework 候选准备状态。

该页的重点是“结果是否能继续”和“下一步该做什么”。它不直接回写 Framework，也不直接激活任何导入内容。

## 页面结构

1. 顶部
   - 返回分析中
   - 面包屑：主页 / 当前项目 / Framework 编排 / 分析结果
   - 问题记录按钮

2. 左侧：结果状态
   - 作品名
   - 导入 ID
   - 文件类型
   - 导入状态
   - 校验状态
   - 当前结论

3. 中间：结果总览
   - 四个结果卡：
     - 导入记录
     - 校验报告
     - 报告引用
     - Framework 候选
   - 分区切换：
     - 总览
     - 校验
     - 报告
     - 候选
   - 分区内容随点击切换

4. 右侧：下一步
   - 可继续条件
   - 用户确认要求
   - 可执行动作：
     - 重新验证
     - 打开报告 Viewer
     - 生成 Framework 候选
     - 进入候选审阅

5. 抽屉
   - 问题记录
   - 展示 warnings、blocking issues、missing recommended fields

## 交互

- 点击结果卡或分区按钮会切换中间详情。
- 点击“问题记录”打开右侧抽屉。
- 点击“重新验证”会刷新校验状态并显示轻量反馈。
- 点击“打开报告 Viewer”跳转到报告 Viewer 原型。
- 点击“生成 Framework 候选”会把候选状态从“待生成”切换为“可审阅”，并解锁“进入候选审阅”。
- 点击“进入候选审阅”跳转到 `04 Framework Candidate Selection`。

## Phase 8.5 接口映射

分析结果总览直接读取 Analyze Stories import result/detail，并联动 report viewer 与 framework candidate。

读取导入详情：

```ts
GET /api/analyze-stories/imports/{import_id}
```

核心字段：

```ts
type AnalyzeStoriesImportDetail = {
  manifest: {
    import_id: string;
    import_status: "received" | "parsed" | "validated_with_warnings" | "blocked" | "ready_for_m2";
    parse_status: "not_parsed" | "parsed" | "parse_failed";
    file_kinds: string[];
    artifact_ids: string[];
    validation_report_id?: string | null;
    story_analysis_report_ref_ids: string[];
  };
  artifacts: Array<{
    artifact_id: string;
    file_kind: "framework_package" | "story_analysis_report" | "full_book_bundle" | "cross_chapter_state_package" | "unknown";
    original_filename?: string | null;
    content_length: number;
    raw_storage_status: "stored" | "redacted" | "hash_only" | "blocked";
    parse_status: "not_parsed" | "parsed" | "parse_failed";
    safe_summary: string;
  }>;
  input_fingerprints: Array<{
    fingerprint_id: string;
    input_title?: string | null;
    chapter_index?: number | null;
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
  validation_report?: {
    passed: boolean;
    can_proceed_to_m2: boolean;
    blocking_issues: Array<{ code: string; message: string; safe_detail?: string | null }>;
    warnings: Array<{ code: string; message: string; safe_detail?: string | null }>;
    detected_file_kinds: string[];
    missing_recommended_fields: string[];
    requires_user_confirmation: boolean;
    safe_summary: string;
  } | null;
}
```

重新验证：

```ts
POST /api/analyze-stories/imports/{import_id}/revalidate
```

打开报告 Viewer：

```ts
POST /api/analyze-stories/report-viewers
body: { report_ref_id: string }

GET /api/analyze-stories/reports/{report_ref_id}/viewer-state
GET /api/analyze-stories/report-viewers/{viewer_state_id}
```

生成 Framework 候选：

```ts
POST /api/analyze-stories/imports/{import_id}/framework-candidates
GET /api/analyze-stories/framework-candidates/{candidate_id}
```

候选结果关键字段：

```ts
type FrameworkPackageCandidateResult = {
  success: boolean;
  candidate: {
    candidate_id: string;
    candidate_status: "created" | "normalized_with_warnings" | "blocked" | "ready_for_workbench_review";
    requires_user_confirmation: boolean;
    can_proceed_to_m4_workbench: boolean;
  };
  normalization_report: {
    passed: boolean;
    can_proceed_to_m4_workbench: boolean;
    blocking_issues: Array<{ code: string; message: string }>;
    warnings: Array<{ code: string; message: string }>;
    normalized_diffs: Array<{
      field_path: string;
      change_type: string;
      reason: string;
      severity: "info" | "warning" | "blocking";
    }>;
    detected_counts: Record<string, number>;
    requires_user_confirmation: boolean;
    safe_summary: string;
  };
}
```

状态判断建议：

- `validation_report.passed && validation_report.can_proceed_to_m2`：总览显示可继续。
- `validation_report.warnings.length > 0`：显示警告入口，但不阻塞。
- `validation_report.blocking_issues.length > 0`：主按钮切到问题处理层。
- `story_analysis_report_refs.length > 0`：可打开报告 Viewer。
- `candidate.can_proceed_to_m4_workbench`：可进入导入编辑会话。

## 可视化稿

- `visual-drafts/analysis-result-overview-v1.html`
- `visual-drafts/analysis-result-overview-v1.png`
