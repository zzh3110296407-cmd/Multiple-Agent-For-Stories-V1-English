# 07es Branch / Framework 候选选择 UI V1

Date: 2026-07-03

## 页面定位

Framework 候选选择是分析结果总览之后的候选审阅页。用户在这里选择一个从 Analyze Stories 导入记录生成的 Framework 候选，查看规范化摘要、差异、警告和可用性，再决定是否打开导入编辑会话。

此页不会激活候选，不会回写当前 Framework，也不会生成正文。进入导入编辑会话后仍需经过编辑、验证、激活计划和用户确认。

## 页面结构

1. 顶部
   - 返回分析结果
   - 面包屑：主页 / 当前项目 / Framework 编排 / Framework 候选
   - 差异与提醒按钮

2. 左侧：候选列表
   - 可审阅候选
   - 带提醒候选
   - 阻塞候选
   - 当前候选状态摘要

3. 中间：候选详情
   - 候选标题与状态
   - 组件计数
   - 规范化摘要
   - 分区：
     - 总览
     - 组件
     - 差异
     - 来源

4. 右侧：选择与会话
   - 可进入编辑会话条件
   - 用户确认要求
   - 动作：
     - 重新验证候选
     - 预览 Workbench
     - 选择此候选
     - 开始导入编辑会话

5. 抽屉
   - 差异与提醒
   - warnings、blocking issues、normalized_diffs

## 交互

- 点击候选卡会切换当前候选。
- 可审阅候选允许“选择此候选”和“开始导入编辑会话”。
- 带提醒候选允许继续，但右侧显示需要确认。
- 阻塞候选不可开始编辑会话，主按钮切为问题提示。
- 点击分区切换候选详情。
- 点击“差异与提醒”打开抽屉。
- 点击“重新验证候选”刷新候选状态并显示反馈。
- 点击“选择此候选”会将主按钮切换为“开始导入编辑会话”。
- 点击“开始导入编辑会话”会跳转到已有导入编辑会话原型。

## Phase 8.5 接口映射

候选列表：

```ts
GET /api/analyze-stories/framework-candidates
```

候选详情：

```ts
GET /api/analyze-stories/framework-candidates/{candidate_id}
```

候选重新验证：

```ts
POST /api/analyze-stories/framework-candidates/{candidate_id}/revalidate
```

打开候选 Workbench：

```ts
GET /api/analyze-stories/framework-candidates/{candidate_id}/imported-workbench
```

开始导入编辑会话：

```ts
POST /api/analyze-stories/framework-candidates/{candidate_id}/edit-sessions
```

后续编辑会话：

```ts
GET /api/analyze-stories/imported-framework-edit-sessions
GET /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}
PATCH /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}
POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/validate
POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/activation-plan
POST /api/analyze-stories/imported-framework-activation-plans/{plan_id}/confirm
POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/reject
```

核心类型：

```ts
type FrameworkPackageCandidateDetail = {
  candidate: {
    candidate_id: string;
    import_id: string;
    artifact_id: string;
    candidate_status:
      | "created"
      | "normalized_with_warnings"
      | "blocked"
      | "ready_for_workbench_review";
    normalized_framework_package?: Record<string, unknown> | null;
    normalization_report_id: string;
    requires_user_confirmation: boolean;
    can_proceed_to_m4_workbench: boolean;
  };
  normalization_report?: {
    passed: boolean;
    can_proceed_to_m4_workbench: boolean;
    blocking_issues: Array<{ code: string; message: string; safe_detail?: string | null }>;
    warnings: Array<{ code: string; message: string; safe_detail?: string | null }>;
    normalized_diffs: Array<{
      field_path: string;
      change_type:
        | "defaulted"
        | "normalized"
        | "downgraded"
        | "renamed"
        | "dropped"
        | "blocked"
        | "downscoped"
        | "moved_to_report_layer";
      before_summary?: string | null;
      after_summary?: string | null;
      reason: string;
      severity: "info" | "warning" | "blocking";
    }>;
    detected_counts: Record<string, number>;
    requires_user_confirmation: boolean;
    safe_summary: string;
  } | null;
}
```

Workbench 状态：

```ts
type ImportedFrameworkWorkbenchState = {
  candidate_id: string;
  candidate_status: string;
  can_start_edit_session: boolean;
  latest_edit_session_id?: string | null;
  candidate_summary: {
    framework_package_id: string;
    macro_component_count: number;
    chapter_assignment_count: number;
    built_chapter_framework_count: number;
    chapter_indexes: number[];
    safe_summary: string;
  };
  current_framework_summary: ImportedFrameworkSummary;
  warnings: Array<{ code: string; message: string }>;
  blocking_issues: Array<{ code: string; message: string }>;
}
```

状态判断建议：

- `candidate.can_proceed_to_m4_workbench === true`：允许开始导入编辑会话。
- `normalization_report.warnings.length > 0`：允许继续，但 UI 要显示需要用户确认。
- `normalization_report.blocking_issues.length > 0` 或 `candidate_status === "blocked"`：不允许开始编辑会话。
- `requires_user_confirmation === true`：右侧持续显示确认要求。
- `latest_edit_session_id` 存在时，主按钮可显示“继续编辑会话”。

## 可视化稿

- `visual-drafts/framework-candidate-selection-v1.html`
- `visual-drafts/framework-candidate-selection-v1.png`
