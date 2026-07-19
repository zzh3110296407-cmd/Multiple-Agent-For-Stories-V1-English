# 13 最终输出 / 01 输出入口与完成度检查

日期：2026-07-04

## 设计状态

V1 已生成。该页面是 `13 最终输出` 的入口页，用户侧标题暂定为 `成稿交付`。

视觉稿：

```text
visual-drafts/final-output-entry-completion-check-v1.html
visual-drafts/final-output-entry-completion-check-v1.png
visual-drafts/final-output-entry-completion-check-v1-mobile.png
```

背景素材：

```text
../assets/final-output-background-v1.png
```

## 页面目标

该页只承担最终故事包创建前的完成度判断，不承担导出格式设置，也不展示下载结果。

核心用户任务：

- 查看当前故事是否可进入成稿组装。
- 理解是否存在阻塞项或警告项。
- 在没有阻塞项时进入 `02 成稿组装中`。
- 在有阻塞项时返回对应模块处理。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/frontend/src/views/ProductOutputsWorkspace.jsx
app/backend/models/final_story_package.py
```

主要 helper：

```text
getFinalStoryPackageReadiness()
evaluateFinalStoryPackageReadiness({ allowFixture, persist, safeUserNote })
getFinalStoryPackageReadinessGate(readinessGateId)
getFinalStoryPackageReadinessIssues(readinessGateId)
```

本页暂不触发：

```text
exportFinalStoryPackage(...)
downloadFinalStoryPackageSnapshot(...)
createFinalStoryPackageViewerState(...)
```

这些动作放入后续成稿组装、成稿审阅、导出结果页面。

## 关键数据字段

`FinalStoryPackageReadinessStatusResponse`：

```ts
{
  gate_count: number;
  package_count: number;
  latest_readiness_gate_id?: string | null;
  latest_final_story_package_id?: string | null;
  latest_validation_report_id?: string | null;
  latest_readiness_status?: "ready" | "ready_with_warnings" | "blocked" | "fixture_only" | null;
  latest_package_type?: "real_project_final_package" | "fixture_final_story_package" | null;
  latest_not_real_project_final_package: boolean;
  latest_blocking_issue_count: number;
  latest_warning_issue_count: number;
  final_story_package_is_only_future_plugin_input: boolean;
  plugins_cannot_read_unconfirmed_drafts: boolean;
  plugin_output_must_not_write_original_story_facts: boolean;
  safe_summary: string;
}
```

`FinalStoryPackageReadinessGate`：

```ts
{
  readiness_gate_id: string;
  readiness_status: "ready" | "ready_with_warnings" | "blocked" | "fixture_only";
  can_create_real_final_story_package: boolean;
  final_confirmation_exists: boolean;
  story_draft_complete_exists: boolean;
  unresolved_blocking_continuity_issue_exists: boolean;
  pending_formal_apply_proposal_exists: boolean;
  pending_propagation_review_that_blocks_final_confirmation_exists: boolean;
  depends_on_unconfirmed_draft_or_candidate: boolean;
  depends_on_proposal_as_truth: boolean;
  blocking_issue_ids: string[];
  warning_issue_ids: string[];
  recommended_next_step:
    | "export_final_story_package_in_m2"
    | "resolve_blocking_issues"
    | "complete_story_draft_confirmation"
    | "resolve_pending_proposals"
    | "review_propagation_tasks"
    | "use_fixture_only"
    | "not_ready";
  safe_summary: string;
}
```

`FinalStoryPackageReadinessIssue`：

```ts
{
  issue_id: string;
  readiness_gate_id: string;
  severity: "blocking" | "warning" | "info";
  code: string;
  user_visible_message: string;
  recommended_resolution: string;
  source_refs: string[];
  created_at: string;
}
```

## UI 映射

- 顶部状态：来自 `latest_readiness_status`。
- 完成度卡片：由核心布尔项、阻塞数、警告数转换为用户可读进度。
- 检查结果列表：来自 `FinalStoryPackageReadinessIssue[]`，按 `blocking / warning / info` 映射为阻塞、警告、已通过/信息。
- 右侧交付边界：来自安全布尔项和产品规则，不展示调试证据。
- 主按钮：
  - 无阻塞：`进入成稿组装`。
  - 有阻塞：改为禁用或显示 `处理阻塞项`。

## 交互记录

V1 HTML 已实现：

- 筛选检查结果：全部、阻塞、警告、已通过。
- 点击检查项后，右侧显示详情和推荐处理。
- `重新检查` 模拟 readiness gate 重新执行。
- `进入成稿组装` 模拟进入下一页。

## 设计边界

- 本页不出现 `创作路线`。
- 阶段提示不是可点击导航。01-04 是最终输出主交付线；05 为导出生成中；06 为下载与归档结果；07 为异常分支。本页只突出 01。
- 本页不做导出格式选择。
- 本页不提供下载入口。
- 本页不把插件输出、调试证据、未确认草稿展示为正式故事事实。
- 警告项可以继续进入成稿组装，但必须在后续成稿审阅中保留提示。
