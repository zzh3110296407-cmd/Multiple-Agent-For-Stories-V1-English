# 13 最终输出 / 02 成稿组装中

日期：2026-07-04

## 设计状态

V1 已生成。该页面是完成度检查通过后的处理中页面，用户侧标题为 `成稿组装中`。

视觉稿：

```text
visual-drafts/final-output-manuscript-assembly-v1.html
visual-drafts/final-output-manuscript-assembly-v1.png
visual-drafts/final-output-manuscript-assembly-v1-mobile.png
```

背景素材：

```text
../assets/final-output-background-v1.png
```

## 页面目标

该页用于表现系统正在把已确认故事内容组装为最终故事包快照。

用户看到的是“成稿组装”，不是技术导出日志。页面应保持安静、明确、不可误操作。

核心用户任务：

- 确认系统正在组装成稿。
- 看到组装进度和当前处理步骤。
- 理解哪些来源会进入最终快照。
- 组装完成后进入 `03 成稿审阅`。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/frontend/src/views/ProductOutputsWorkspace.jsx
app/backend/models/final_story_package.py
```

主要 helper：

```text
exportFinalStoryPackage({
  readinessGateId,
  allowFixtureExport,
  exportFormat,
  safeUserNote
})

getFinalStoryPackageExportRuns()
getFinalStoryPackageExportRun(exportRunId)
getFinalStoryPackageSnapshot(snapshotId)
getFinalStoryPackageSnapshotSections(snapshotId)
```

下载和 Viewer State 不属于本页主动作：

```text
downloadFinalStoryPackageSnapshot(...)
createFinalStoryPackageViewerState(...)
```

这些动作放到后续成稿审阅和导出交付页面。

## 关键数据字段

`FinalStoryPackageExportRequest`：

```ts
{
  readiness_gate_id: string;
  allow_fixture_export: boolean;
  export_format: "json_snapshot";
  safe_user_note: string;
}
```

`FinalStoryPackageExportRun`：

```ts
{
  export_run_id: string;
  project_id: string;
  readiness_gate_id: string;
  validation_report_id: string;
  final_story_package_id: string;
  manifest_id: string;
  snapshot_id: string;
  evidence_index_id: string;
  safety_audit_id: string;
  export_format: "json_snapshot";
  export_status: "created" | "blocked" | "fixture_created" | "failed";
  package_type: "real_project_final_package" | "fixture_final_story_package";
  readiness_status: "ready" | "ready_with_warnings" | "blocked" | "fixture_only";
  can_be_used_by_plugins: boolean;
  not_real_project_final_package: boolean;
  blocked_issue_ids: string[];
  warning_issue_ids: string[];
  safe_summary: string;
}
```

`FinalStoryPackageSnapshot`：

```ts
{
  snapshot_id: string;
  final_story_package_id: string;
  readiness_gate_id: string;
  validation_report_id: string;
  manifest_id: string;
  snapshot_status: "created" | "fixture" | "blocked";
  complete_story_text: string;
  complete_story_text_char_count: number;
  chapter_scene_index: Array<Record<string, unknown>>;
  character_table: Array<Record<string, unknown>>;
  world_canvas_summary: Record<string, unknown>;
  relationship_state_summary: Array<Record<string, unknown>>;
  key_event_timeline: Array<Record<string, unknown>>;
  user_locked_constraints: Array<Record<string, unknown>>;
  style_and_tone: Record<string, unknown>;
  known_residual_codes: string[];
  can_be_used_by_plugins: boolean;
  not_real_project_final_package: boolean;
  safe_summary: string;
}
```

## UI 映射

- 顶部状态：来自导出请求状态或 `export_status`。
- 进度条：前端本地进度反馈，用于表现请求进行中；真实后端没有必要逐帧返回每一步。
- 步骤列表：
  - 收集完整正文。
  - 建立章节场景索引。
  - 汇入角色表与世界摘要。
  - 固化来源边界。
  - 生成预览段落。
  - 完成成稿快照。
- 右侧“本次组装”：映射 `package_type`、`readiness_status`、`warning_issue_ids`、`not_real_project_final_package`。
- 右侧“写入快照的分区”：映射 `FinalStoryPackageSnapshot` 的主要 section 字段。
- 主按钮：
  - 请求进行中：`进入成稿审阅` 禁用。
  - `export_status === "created"`：启用 `进入成稿审阅`。
  - `export_status === "blocked" | "failed"`：后续进入问题处理页。

## 交互记录

V1 HTML 已实现：

- 组装进度自动推进。
- 中央动画为 `来源分区汇入 -> 成稿装订`：正文、目录、角色、世界、事件、约束从两侧汇入装订台，纸页形成最终成稿快照。
- 步骤状态从等待、进行中、完成逐项变化。
- 组装完成后启用 `进入成稿审阅`。
- 阶段提示不是可点击导航。01-04 是最终输出主交付线；05 为导出生成中；06 为下载与归档结果；07 为异常分支。本页只突出 02。

## 设计边界

- 本页不出现 `创作路线`。
- 本页不做导出格式选择。
- 本页不提供下载入口。
- 本页不展示完整技术日志。
- 本页不允许用户把插件输出、候选提案或调试证据写回故事事实。
- 组装完成前主动作不可点击，避免用户进入没有快照数据的审阅页。
