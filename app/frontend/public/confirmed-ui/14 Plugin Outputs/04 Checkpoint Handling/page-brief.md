# 14 插件输出 / 04 检查点处理

## 页面目标

本页用于处理插件运行中产生的用户检查点。用户可以确认、要求修订、拒绝或延后检查点。页面只展示安全摘要、可审阅派生产物和公开状态，不展示 raw prompt、raw response、隐藏推理、调试证据或原始 payload。

## 已生成文件

- 动态稿 HTML：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\04 Checkpoint Handling\visual-drafts\plugin-checkpoint-handling-v1.html`
- 桌面截图：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\04 Checkpoint Handling\visual-drafts\plugin-checkpoint-handling-v1.png`
- 移动端截图：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\04 Checkpoint Handling\visual-drafts\plugin-checkpoint-handling-v1-mobile.png`

## 前端接口对接

进入本页时建议持有 `pluginRunId`，并优先加载：

- `getPluginRun(pluginRunId)`：读取运行状态和当前步骤。
- `getPluginRunCheckpoints(pluginRunId)`：读取待处理检查点队列。
- `getPluginRunArtifacts(pluginRunId)`：读取检查点关联派生产物。
- `getPluginRunSafetyReport(pluginRunId)`：读取安全边界和风险提示。

用户动作接口：

- `confirmPluginCheckpoint(pluginRunId, checkpointId, { safeUserNote })`
- `revisePluginCheckpoint(pluginRunId, checkpointId, { safeUserNote, requestedChanges })`
- `rejectPluginCheckpoint(pluginRunId, checkpointId, { safeUserNote })`
- `deferPluginCheckpoint(pluginRunId, checkpointId, { safeUserNote })`

## 数据映射

`PluginCheckpoint` 建议映射：

- `checkpoint_id`：右侧检查点详情。
- `checkpoint_status`：列表标签、顶部状态、底部按钮可用性。
- `safe_summary`：中间检查点说明。
- `output_artifact_id`：关联产物 ID。
- `created_at` / `updated_at`：可放入检查点详情或审计说明。

`PluginOutputArtifact` 建议映射：

- `output_artifact_id`：右侧产物字段。
- `artifact_status`：如果为 `checkpoint_pending`，进入本页处理。
- `safe_summary`：中间派生产物预览。
- `warnings`：安全边界或问题处理提示。

`PluginRunSafetyReport` 建议映射：

- `passed`：安全边界主状态。
- `live_story_state_access_blocked`：实时故事状态是否被拦截。
- `unconfirmed_draft_access_blocked`：未确认草稿是否被拦截。
- `no_raw_prompt` / `no_raw_response` / `no_hidden_reasoning`：右侧安全说明。
- `violations`：若非空，禁止确认，转入 06 输出问题处理。

## 状态规则

- `pending`：默认待确认，允许确认、修订、拒绝、延后。
- `confirmed`：当前检查点完成确认；只有所有必需检查点均为 `confirmed` 后，才启用“进入成果审阅”，跳转到 `14 Plugin Outputs / 05 Plugin Artifact Review`。
- `revision_requested`：调用修订接口后返回 03 插件运行中，等待插件重新处理。
- `rejected`：当前检查点拒绝；可根据后端状态进入 06 问题处理或回到插件选择。
- `deferred`：保持检查点等待状态，用户可稍后继续处理；若仍有 deferred / pending 检查点，不应进入成果审阅。
- 若运行状态为 `blocked` 或 `failed`，不应停留在本页，应进入 `06 Plugin Output Issue Handling`。

## 视觉与交互要求

- 继承 14 插件输出背景图和莫兰迪羊皮纸色系。
- 不使用创作路线。
- 阶段 `01-06` 是流程状态，不作为按钮。
- 左侧检查点队列可单击切换。
- 中间审阅区展示当前检查点的安全预览、决策边界、用户安全说明和修订要求输入。
- 底部动作区包含延后、拒绝、要求修订、确认、进入成果审阅。
- 移动端改为单列，底部动作按钮纵向排列。

## 实现备注

- 前端应使用接口状态驱动 UI，不依赖动态稿中的模拟数据。
- `safeUserNote` 可以为空，但字段应始终按接口要求传入。
- `requestedChanges` 只在用户选择“要求修订”时必填，前端封装要求 `string[]`；UI 文本框可按换行切分为数组后提交。
- 若 `PluginRunSafetyReport.violations` 非空，应禁用确认按钮，并提示进入问题处理。
- 确认、拒绝、延后建议加入二次确认或短暂撤销机制，避免误触。
