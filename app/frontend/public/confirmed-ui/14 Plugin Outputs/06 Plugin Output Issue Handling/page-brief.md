# 14 插件输出 / 06 插件输出问题处理

## 页面目标

本页用于处理插件输出流程中出现的问题，包括安全违规、成果缺失、检查点未处理、运行失败和格式警告。页面职责是定位问题来源并引导用户回到正确处理节点，不直接修改故事正文、源故事、最终故事包或插件原始产物。

本页不展示 raw prompt、raw response、隐藏推理、调试证据、API key 或原始 payload。

## 已生成文件

- 动态稿 HTML：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\06 Plugin Output Issue Handling\visual-drafts\plugin-output-issue-handling-v1.html`
- 桌面截图：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\06 Plugin Output Issue Handling\visual-drafts\plugin-output-issue-handling-v1.png`
- 移动端截图：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\06 Plugin Output Issue Handling\visual-drafts\plugin-output-issue-handling-v1-mobile.png`

## 前端接口对接

进入本页时建议持有 `pluginRunId`，并读取：

- `getPluginRun(pluginRunId)`：判断 `run_status`、错误数量、当前步骤。
- `getPluginRunSteps(pluginRunId)`：定位失败或阻塞发生在哪个步骤。
- `getPluginRunCheckpoints(pluginRunId)`：判断是否仍有 `pending` 检查点。
- `getPluginRunArtifacts(pluginRunId)`：判断成果缺失、`checkpoint_pending`、`rejected` 或警告状态。
- `getPluginRunSafetyReport(pluginRunId)`：判断 `violations` 和 `warnings`。

可触发的后续动作：

- 返回 02 插件选择 / 输入确认：重新选择插件或调整输入边界。
- 返回 03 插件运行中：重新创建运行后查看运行过程。
- 返回 04 检查点处理：处理未确认检查点。
- 返回 05 插件成果审阅：查看非阻塞警告或可审阅成果。
- 如用户需要取消当前运行，可调用 `cancelPluginRun(pluginRunId, { safeUserNote })`。
- 如用户需要重新运行，可基于 02 已确认输入调用 `createPluginRun(pluginId, { snapshotId, safeUserNote })`。

当前接口集中没有专门的“创建问题记录”或“修复 artifact”接口，因此本页不要假设存在新的写接口。

## 问题类型映射

安全违规：

- 来源：`PluginRunSafetyReport.violations.length > 0`
- 页面状态：阻塞
- 主动作：返回 02 插件选择
- 说明：受影响成果不得作为可交付结果使用。

成果缺失：

- 来源：`PluginRun.output_artifact_ids` 缺少必需成果，或 `getPluginRunArtifacts` 返回不完整。
- 页面状态：需修复
- 主动作：重新运行插件，进入 03。
- 说明：如果只是刷新延迟，先刷新状态。

检查点未处理：

- 来源：`PluginCheckpoint.status = pending` 或成果 `artifact_status = checkpoint_pending`
- 页面状态：待确认
- 主动作：返回 04 检查点处理。
- 说明：确认后进入 05；修订后回到 03；拒绝后留在 06。

导出格式警告：

- 来源：`PluginOutputArtifact.warnings` 或 `PluginRunSafetyReport.warnings`
- 页面状态：警告
- 主动作：返回 05 成果审阅。
- 说明：非阻塞警告可以继续审阅，但需要在成果信息中提示。

运行失败：

- 来源：`PluginRun.run_status = failed | blocked`
- 页面状态：阻塞或需修复
- 主动作：根据失败步骤返回 02 或 03。

## 状态规则

- `run_status = blocked`：默认进入本页，主按钮根据问题来源决定。
- `run_status = failed`：进入本页，展示失败步骤和可重试路径。
- `run_status = completed_with_warnings`：进入本页或 05；如果是非阻塞警告，可返回 05。
- `run_status = waiting_for_checkpoint`：本页只做提示，主动作返回 04。
- `run_status = completed` 且无 warning / violation：不应进入本页，直接进入 05。

## 视觉与交互要求

- 继承 14 插件输出背景图和莫兰迪羊皮纸色系。
- 不使用创作路线。
- 阶段 `01-06` 是流程状态，不作为按钮。
- 左侧问题清单可单击切换。
- 中间问题详情包含三个标签：问题摘要、处理路径、记录信息。
- 中间内容区可滚动，避免记录信息过长时溢出。
- 右侧展示影响范围、运行详情、下一步。
- 底部动作根据当前问题变化：刷新状态、返回上一审阅节点、进入主处理节点。
- 移动端改为单列，底部动作按钮纵向排列。

## 实现备注

- 问题数据应由运行状态、成果状态、检查点状态和安全报告组合推导，不需要后端新增问题实体。
- `safeUserNote` 可用于取消运行或重新创建运行时传递用户备注。
- 安全违规优先级最高；只要 `violations` 非空，就禁止打开成果包、下载归档或将成果标记为可交付。
- 页面上的“返回插件选择 / 重新运行插件 / 返回检查点 / 返回成果审阅”应接入真实路由，不在本页直接修复数据。
