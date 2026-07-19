# 14 插件输出 / 01 插件成果入口

日期：2026-07-04

## 设计状态

V1 已生成，等待确认。

视觉稿：

```text
visual-drafts/plugin-outputs-entry-v1.html
visual-drafts/plugin-outputs-entry-v1.png
visual-drafts/plugin-outputs-entry-v1-mobile.png
```

背景素材：

```text
../assets/plugin-outputs-background-v1.png
```

## 页面目标

该页是 `14 插件输出` 的入口页。它不展示原始插件控制台，而是展示已经产品化、可安全预览的插件成果，并提供进入新插件任务的入口。

核心用户任务：

- 查看当前项目已经产生的插件成果。
- 理解插件成果只是派生成果，不是源故事事实。
- 筛选可审阅、待检查点、已归档、有提醒的成果。
- 选择一个成果并打开受控视图。
- 进入 `02 插件选择 / 输入确认` 创建新的插件任务。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/frontend/src/views/ProductOutputsWorkspace.jsx
app/frontend/src/components/ProductArtifactLibrary.jsx
app/frontend/src/components/ProductArtifactCard.jsx
app/frontend/src/components/PluginOutputProductView.jsx
```

入口页主要读取：

```text
getProductArtifactLibrary({ projectId })
getProductArtifactEntries({ projectId })
getPluginOutputProductViews({ projectId })
getPluginOutputProductView(viewId, { projectId })
```

后续页面才触发：

```text
getPlugins()
getPlugin(pluginId)
getPluginManifest(pluginId)
getPluginInputSchema(pluginId)
getPluginOutputSchemas(pluginId)
getPluginRiskDeclaration(pluginId)
validatePluginInput(pluginId, payload)
createPluginRun(pluginId, payload)
getPluginRun(pluginRunId)
getPluginRunCheckpoints(pluginRunId)
confirmPluginCheckpoint(...)
revisePluginCheckpoint(...)
rejectPluginCheckpoint(...)
deferPluginCheckpoint(...)
```

## 关键数据字段

`PluginOutputProductView`：

```ts
{
  view_id: string;
  artifact_id: string;
  project_id: string;
  plugin_run_id: string;
  plugin_id: string;
  artifact_type: string;
  display_title: string;
  display_status: string;
  current_version_id: string;
  version_count: number;
  source_package_snapshot_id: string;
  authority_badge: ProductArtifactAuthorityBadge;
  safe_preview: ProductArtifactSafePreview;
  safety_summary: ProductArtifactSafetySummary;
  view_model_only: boolean;
  does_not_create_story_fact: boolean;
  does_not_mutate_source_story: boolean;
  does_not_mutate_source_artifact: boolean;
  does_not_apply_to_source_story: boolean;
  safe_reference_only: boolean;
  raw_payload_included: boolean;
  safe_summary: string;
}
```

`ProductArtifactAuthorityBadge`：

```ts
{
  authority_kind: string;
  authority_label: string;
  authority_scope: string;
  is_plugin_input_authority: boolean;
  is_derivative_output: boolean;
  not_source_story_fact: boolean;
  does_not_apply_to_source_story: boolean;
}
```

`ProductArtifactSafePreview`：

```ts
{
  preview_mode: string;
  safe_title: string;
  safe_excerpt: string;
  metadata: Record<string, unknown>;
  counts: Record<string, number>;
  source_ref_ids: string[];
  content_hash: string;
  bounded_char_count: number;
  raw_payload_included: boolean;
  safe_reference_only: boolean;
  safe_summary: string;
}
```

`ProductArtifactSafetySummary`：

```ts
{
  passed: boolean;
  blocking_codes: string[];
  warning_codes: string[];
  residual_risks: string[];
  no_source_story_write: boolean;
  no_final_package_mutation: boolean;
  no_plugin_output_mutation: boolean;
  does_not_apply_to_source_story: boolean;
}
```

## UI 映射

- 页面标题：固定为 `插件成果`。
- 成果库：来自 product artifact library 或 plugin output product views。
- 可见插件名：使用用户可读名称，例如 `剧本锻造`；真实 `plugin_id` 如 `script_forging` 放在接口层。
- 状态标签：
  - `completed / confirmed / ready` 映射为 `可审阅`。
  - `waiting_for_checkpoint / checkpoint_pending` 映射为 `检查点`。
  - `archived` 映射为 `已归档`。
  - `completed_with_warnings / warning` 映射为 `有提醒`。
- 右侧详情：展示 authority badge、safe preview、safety summary 的用户可读摘要。
- 原始 payload：入口页必须显示为隐藏，不暴露原始载荷。

## 交互记录

V1 HTML 已实现：

- 成果筛选：全部、可审阅、检查点、已归档、有提醒。
- 点击成果卡片后，右侧详情、安全摘要、计数和来源预览同步更新。
- `刷新成果` 模拟重新读取产品化插件成果视图。
- `选择插件任务` 模拟进入 `02 插件选择 / 输入确认`。
- `打开受控视图` 模拟进入 `05 插件成果审阅`。
- 安全预览内可在摘要、计数、来源之间切换。

## 设计边界

- 本页不出现 `创作路线`。
- 本页不出现 `Classic Morandi` 或主题胶囊。
- 本页不做插件运行参数输入，该功能放在 02。
- 本页不直接处理检查点，该功能放在 04。
- 本页不展示 raw payload、debug trace、runtime evidence。
- 插件成果不得被表达为源故事事实；所有成果都应明确为派生、只读或等待确认。
- 插件成果不能直接写回正文、角色、世界、章节计划或最终故事包。

## 验证记录

- 已生成桌面截图和移动端截图。
- 已静态检查页面未包含旧版 `创作路线`、`Classic Morandi`、`经典莫兰迪`。
- 已用 Playwright CLI 生成截图。
- 自动 DOM 交互脚本因当前 Windows `npx --package=playwright` 未能把模块注入给 stdin Node 进程而未完成；视觉和代码层面的交互逻辑已在 HTML 内实现。
