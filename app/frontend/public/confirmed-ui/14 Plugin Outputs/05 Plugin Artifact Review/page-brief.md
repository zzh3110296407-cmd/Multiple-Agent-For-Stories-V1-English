# 14 插件输出 / 05 插件成果审阅

## 页面目标

本页用于审阅插件运行完成后生成的派生产物。页面展示成果清单、成果预览、文件元数据和安全摘要；如果成果存在缺失、格式错误或安全警告，用户从本页进入 06 输出问题处理。

本页不反写源故事，不修改最终故事包，不展示 raw prompt、raw response、隐藏推理、调试证据或原始 payload。

## 已生成文件

- 动态稿 HTML：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\05 Plugin Artifact Review\visual-drafts\plugin-artifact-review-v1.html`
- 桌面截图：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\05 Plugin Artifact Review\visual-drafts\plugin-artifact-review-v1.png`
- 移动端截图：`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\05 Plugin Artifact Review\visual-drafts\plugin-artifact-review-v1-mobile.png`

## 前端接口对接

进入本页时建议持有 `pluginRunId`，并读取：

- `getPluginRun(pluginRunId)`：读取运行状态、插件 ID、版本、快照来源。
- `getPluginRunArtifacts(pluginRunId)`：读取成果清单和成果状态。
- `getPluginRunSafetyReport(pluginRunId)`：读取安全边界和警告。
- `getPluginRunCheckpoints(pluginRunId)`：用于确认是否仍存在未处理检查点。

本页当前不设计新的 artifact 写接口。若后端未来增加确认归档、下载链接签发或收藏成果接口，可作为新增动作接入；当前 UI 的“打开成果包”应优先绑定已有 artifact 文件引用或路由。

## 数据映射

`PluginRun` 映射：

- `plugin_run_id`：右侧运行详情。
- `plugin_id`：当前插件。
- `plugin_version`：插件版本。
- `run_status`：顶部运行状态。
- `final_story_package_snapshot_id`：快照来源。
- `output_artifact_ids`：成果数量和清单加载依据。
- `warnings` / `safe_summary`：右侧安全说明。

`PluginOutputArtifact` 建议映射：

- `output_artifact_id`：文件信息中的成果 ID。
- `artifact_status`：成果卡片状态，支持 `draft`、`checkpoint_pending`、`confirmed`、`rejected`、`archived`。
- `safe_summary`：成果预览正文。
- `warnings`：若非空，在安全摘要中提示，并允许进入 06。
- 文件引用或下载引用：用于“打开成果包”。

`PluginRunSafetyReport` 映射：

- `passed`：成果安全主状态。
- `final_story_package_snapshot_used`：来源快照说明。
- `live_story_state_access_blocked`、`unconfirmed_draft_access_blocked`：读取边界。
- `no_scene_prose_write`、`no_event_write`、`no_memory_record_write`、`no_final_story_package_mutation`：写入边界。
- `no_raw_prompt`、`no_raw_response`、`no_hidden_reasoning`、`no_api_key`：不可见内容声明。
- `violations`：若非空，禁止当作可交付成果，进入 06。
- `warnings`：展示为警告，但不一定阻塞。

## 状态规则

- `run_status = completed`：展示成果审阅，允许打开成果包和报告问题。
- `run_status = completed_with_warnings`：展示成果审阅，同时突出安全或格式警告，并建议进入 06。
- `run_status = waiting_for_checkpoint`：应返回 04 检查点处理。
- `run_status = blocked | failed`：直接进入 06 输出问题处理。
- `artifact_status = checkpoint_pending`：该成果不应在 05 作为可审阅结果展示，应引导回 04。
- `artifact_status = rejected`：成果展示为问题项，建议进入 06。
- `artifact_status = archived`：可展示归档状态，并允许打开归档成果。

## 视觉与交互要求

- 继承 14 插件输出背景图和莫兰迪羊皮纸色系。
- 不使用创作路线。
- 阶段 `01-06` 是流程状态，不作为按钮。
- 左侧成果清单可单击切换。
- 中间成果预览支持三个标签：成果预览、文件信息、安全摘要。
- 中间预览区必须可滚动，避免长内容挤出边框。
- 右侧展示运行详情、安全报告和下一步。
- 底部动作：刷新成果、报告问题、打开成果包。
- 移动端改为单列，底部按钮纵向排列。

## 实现备注

- 前端应使用接口返回的成果数据驱动 UI，不依赖动态稿中的模拟数据。
- 不要在本页展示 raw payload、原始提示词、模型原始响应或隐藏推理。
- “报告问题”进入 `14 Plugin Outputs / 06 Plugin Output Issue Handling`。
- 如果 `PluginRunSafetyReport.violations` 非空，主按钮应改为问题处理，不应允许用户把成果当作最终可交付结果使用。
