# 14 插件输出 / 02 插件选择与输入确认

日期：2026-07-04

## 设计状态

V1 已生成，等待确认。

视觉稿：

```text
visual-drafts/plugin-selection-input-confirmation-v1.html
visual-drafts/plugin-selection-input-confirmation-v1.png
visual-drafts/plugin-selection-input-confirmation-v1-mobile.png
```

背景素材：

```text
../assets/plugin-outputs-background-v1.png
```

## 页面目标

该页是插件运行前的安全门禁。它不生成插件成果，也不展示原始运行日志；它只负责让用户选择插件、选择受控输入快照、填写安全备注、执行输入校验，并在校验通过后创建插件运行。

核心用户任务：

- 选择一个可运行插件。
- 确认插件读取的是受控最终故事包快照。
- 查看输入契约和风险声明。
- 填写本次运行的安全备注。
- 执行输入校验。
- 校验通过后进入 `03 插件运行中`。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/backend/models/plugin_protocol.py
app/backend/models/plugin_runtime.py
```

本页读取：

```text
getPlugins()
getPlugin(pluginId)
getPluginManifest(pluginId)
getPluginInputSchema(pluginId)
getPluginOutputSchemas(pluginId)
getPluginRiskDeclaration(pluginId)
```

本页提交：

```text
validatePluginInput(pluginId, {
  snapshotId,
  persistValidationReport,
  safeUserNote
})

createPluginRun(pluginId, {
  snapshotId,
  safeUserNote
})
```

## 关键数据字段

`PluginManifest`：

```ts
{
  manifest_id: string;
  plugin_id: string;
  display_name: string;
  description: string;
  input_schema_id: string;
  output_schema_ids: string[];
  risk_declaration_id: string;
  availability_status: string;
  runtime_available: boolean;
  can_create_plugin_run: boolean;
  requires_final_story_package_snapshot: boolean;
  allow_live_story_state_input: boolean;
  allow_unconfirmed_draft_input: boolean;
  mutates_source_story: boolean;
  checkpoint_templates: object[];
  safe_summary: string;
}
```

`PluginInputValidationRequest`：

```ts
{
  snapshot_id: string;
  persist_validation_report: boolean;
  safe_user_note: string;
}
```

`PluginInputValidationReport`：

```ts
{
  input_validation_report_id: string;
  plugin_id: string;
  manifest_id: string;
  input_schema_id: string;
  snapshot_id: string;
  project_id: string;
  validation_status: string;
  input_valid: boolean;
  plugin_runtime_available: boolean;
  can_create_plugin_run_now: boolean;
  can_create_plugin_run_later: boolean;
  can_be_used_by_plugins: boolean;
  required_record_checks: Record<string, boolean>;
  required_snapshot_field_checks: Record<string, boolean>;
  missing_required_fields: string[];
  blocked_reason_codes: string[];
  warning_codes: string[];
  safe_user_note: string;
  safe_summary: string;
}
```

`PluginRunCreateRequest`：

```ts
{
  snapshot_id: string;
  safe_user_note: string;
}
```

`PluginRunCreateResponse`：

```ts
{
  plugin_run: PluginRun;
  input_validation_report: PluginInputValidationReport;
  steps: PluginRunStep[];
  checkpoints: PluginCheckpoint[];
  safety_report: PluginRunSafetyReport;
  safe_summary: string;
}
```

## UI 映射

- 左侧插件列表：
  - `PluginRegistryEntry.visible_in_selector`
  - `PluginManifest.display_name`
  - `PluginManifest.can_create_plugin_run`
  - `PluginManifest.availability_status`
- 中间输入快照：
  - 当前真实接口只提交 `snapshot_id`，所以页面不做逐项参数编辑。
  - “完整正文 / 角色表 / 世界摘要 / 事件线 / 锁定约束”等只作为只读确认，来自快照内容。
- 安全备注：
  - 对应 `safe_user_note`。
  - 备注不是故事事实，不写入源故事。
- 右侧风险声明：
  - 来自 `PluginRiskDeclaration` 与 `PluginCapabilityDeclaration`。
  - 重点显示是否可读快照、是否允许未确认草稿、是否会修改源故事、是否需要检查点。
- 输入校验：
  - 成功时 `input_valid === true` 且 `can_create_plugin_run_now === true`，启用 `创建插件运行`。
  - 阻塞时显示 `blocked_reason_codes` 和 `missing_required_fields`。

## 交互记录

V1 HTML 已实现：

- 选择插件；预留插件可被点选但会提示暂不可创建真实运行。
- 选择正式快照或归档快照。
- 修改安全备注后自动回到待校验状态。
- `校验输入` 模拟插件清单、输入快照、安全备注三项校验。
- 安全备注为空时显示阻塞状态。
- 校验通过后启用 `创建插件运行`。
- `创建插件运行` 模拟进入 `03 插件运行中`。
- 右侧可切换摘要、契约、阻塞说明。

## 设计边界

- 本页不出现 `创作路线`。
- 本页不出现 `Classic Morandi` 或主题胶囊。
- 本页不展示 raw payload、debug trace、runtime evidence。
- 本页不允许用户直接编辑快照里的正文、角色、世界、事件或约束。
- 本页不处理插件检查点；检查点进入 04。
- 本页不展示插件成果；成果审阅进入 05。
- `script_forging` 只作为真实 `plugin_id` 显示在接口详情区域，用户侧主要名称使用 `剧本锻造`。

## 验证记录

- 已生成桌面截图和移动端截图。
- 已静态检查页面未包含旧版 `创作路线`、`Classic Morandi`、`经典莫兰迪`。
- 已用 Playwright CLI 生成截图。
