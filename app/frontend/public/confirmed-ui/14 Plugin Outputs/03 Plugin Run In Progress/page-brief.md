# 14 插件输出 / 03 插件运行中

## 页面目标

本页用于展示插件运行已经创建后的实时进度。页面只呈现安全摘要、步骤状态、检查点预告和可公开的运行元数据，不展示 raw prompt、raw response、隐藏推理、调试证据或原始 payload。

## 已生成文件

- 动态稿 HTML：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\03 Plugin Run In Progress\visual-drafts\plugin-run-in-progress-v1.html`
- 桌面截图：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\03 Plugin Run In Progress\visual-drafts\plugin-run-in-progress-v1.png`
- 移动端截图：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\03 Plugin Run In Progress\visual-drafts\plugin-run-in-progress-v1-mobile.png`

## 前端接口对接

建议本页进入时持有 `pluginRunId`，并按运行状态轮询或手动刷新以下接口：

- `getPluginRun(pluginRunId)`：读取运行主体状态。
- `getPluginRunSteps(pluginRunId)`：读取运行步骤列表。
- `getPluginRunCheckpoints(pluginRunId)`：读取是否已生成待处理检查点。
- `getPluginRunArtifacts(pluginRunId)`：读取已生成或待审阅产物。
- `getPluginRunSafetyReport(pluginRunId)`：读取安全护栏结果。
- `cancelPluginRun(pluginRunId, { safeUserNote })`：取消当前插件运行。

## 数据映射

`PluginRun` 映射：

- `run_status`：顶部状态、摘要状态、底部按钮可用性。
- `plugin_id` / `manifest_id` / `plugin_version`：右侧运行详情。
- `final_story_package_snapshot_id`：快照说明。
- `current_step_id`：当前步骤高亮。
- `checkpoint_ids`：检查点数量和下一步入口。
- `output_artifact_ids`：产物数量。
- `warnings` / `safe_summary`：安全事件或说明。
- `created_at` / `updated_at`：可用于计算耗时或最近刷新时间。

`PluginRunStep` 映射：

- `step_status = completed`：步骤完成态。
- `step_status = running`：当前运行态。
- `step_status = waiting_for_checkpoint`：进入检查点准备态。
- `step_status = blocked | failed`：转入 06 输出问题处理。
- `safe_summary` / `warnings`：步骤卡片的公开摘要。

`PluginRunSafetyReport` 映射：

- `passed`：安全报告主状态。
- `live_story_state_access_blocked`、`unconfirmed_draft_access_blocked`、`phase6_proposal_as_truth_blocked`：右侧护栏卡片。
- `no_raw_prompt`、`no_raw_response`、`no_hidden_reasoning`、`no_api_key`：安全说明。
- `violations`：若非空，进入问题处理。
- `warnings`：保留在提醒标签页，不作为阻塞。
- `safe_summary`：安全报告摘要。

## 状态与交互

- `created | input_validated | running step`：显示运行中，允许刷新和取消，禁用进入检查点。
- `waiting_for_checkpoint`：启用“进入检查点”，跳转到 `14 Plugin Outputs / 04 Checkpoint Handling`。
- `completed | completed_with_warnings`：进入 `05 Plugin Artifact Review`。
- `cancelled`：停留在本页显示取消状态，可返回 02 重新选择插件。
- `blocked | failed`：进入 `06 Plugin Output Issue Handling`。

## 视觉与交互要求

- 继承 14 插件输出背景图和莫兰迪羊皮纸色系。
- 不使用创作路线。
- 阶段 `01-06` 是流程状态，不作为按钮，除非后续明确开放跨阶段跳转。
- 主动画只表达“运行中 / 等待检查点 / 已取消”等公开状态，不显示内部推理。
- 移动端改为单列，底部动作按钮纵向排列。

## 实现备注

- 前端应使用接口返回状态驱动页面，不依赖本动态稿内的模拟状态。
- 轮询间隔建议由后端运行成本决定，默认可用 2-5 秒；用户点击“刷新状态”时立即拉取一次。
- 取消运行需要二次确认或撤销提示，避免误触。
- 若 `PluginRunSafetyReport.violations` 非空，优先展示问题处理入口，不能继续进入检查点或产物审阅。
