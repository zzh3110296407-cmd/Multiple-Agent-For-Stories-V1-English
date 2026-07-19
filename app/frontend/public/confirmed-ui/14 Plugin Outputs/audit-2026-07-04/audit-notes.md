# 14 插件输出 UI 审查记录

## 审查范围

审查对象为 `14 Plugin Outputs` 的 01-06 页面：

1. `01 Plugin Outputs Entry`
2. `02 Plugin Selection And Input Confirmation`
3. `03 Plugin Run In Progress`
4. `04 Checkpoint Handling`
5. `05 Plugin Artifact Review`
6. `06 Plugin Output Issue Handling`

审查内容包括信息准确性、视觉层级、交互可用性、流程连接、响应式布局、旧元素残留、字体和内容溢出风险。

## 审查证据

本次重新生成了 12 张审查截图：

- `01-entry-desktop.png`
- `01-entry-mobile.png`
- `02-selection-desktop.png`
- `02-selection-mobile.png`
- `03-run-desktop.png`
- `03-run-mobile.png`
- `04-checkpoint-desktop.png`
- `04-checkpoint-mobile.png`
- `05-review-desktop.png`
- `05-review-mobile.png`
- `06-issues-desktop.png`
- `06-issues-mobile.png`

截图均保存在：

`<source-workspace>\UI Design\05 Page Records\14 Plugin Outputs\audit-2026-07-04`

## 发现并修复的问题

### 1. 04 检查点处理的修订参数说明不够准确

实际 Phase 8.5 前端封装为：

`revisePluginCheckpoint(pluginRunId, checkpointId, { safeUserNote, requestedChanges })`

其中 `requestedChanges` 是 `string[]`，封装内部再转为后端 `requested_changes`。原动态稿容易理解为单段文本。

已修复：

- 04 HTML 中将修订说明改为“按行整理为 `requestedChanges: string[]`”。
- 04 交接文档明确 UI 文本框可按换行切分为数组后提交。

### 2. 04 检查点处理允许过早进入成果审阅

页面展示 3 个待处理检查点，但原逻辑在确认当前检查点后就启用“进入成果审阅”，与“每个检查点都需要独立决策”冲突。

已修复：

- 只有所有必需检查点均为 `confirmed` 后，才启用“进入成果审阅”。
- 当前检查点确认但仍有待处理项时，会提示剩余数量。
- 04 交接文档同步更新状态规则。

### 3. 01-06 顶部返回按钮缺少反馈

左上角返回按钮是可点击样式，但动态稿未绑定交互反馈。

已修复：

- 01 返回当前项目总览。
- 02 返回插件成果入口。
- 03 返回插件选择 / 输入确认。
- 04 返回插件运行页。
- 05 返回检查点处理。
- 06 返回插件成果审阅。

## 页面健康度

01 插件成果入口：通过。

- 入口、筛选、成果选择、安全摘要和下一步动作清晰。
- 桌面端信息量较大但分区明确；移动端内容长但无溢出。

02 插件选择 / 输入确认：通过。

- 校验输入、创建运行的前置关系清楚。
- 预留插件状态不会误导用户创建真实运行。
- 接口参数与 Phase 8.5 前端封装一致。

03 插件运行中：通过。

- 运行进度、步骤、安全事件和下一步检查点的层级清楚。
- 动画中心已无多余文字。
- 刷新、取消、进入检查点交互可用。

04 检查点处理：通过，已修复。

- 检查点队列、当前检查点详情、修订/确认/拒绝/延后动作清楚。
- 修订参数和多检查点进入 05 的规则已修正。

05 插件成果审阅：通过。

- 成果清单、成果预览、文件信息、安全摘要三类视图清楚。
- 中间成果内容可滚动，移动端无按钮或文本溢出。

06 插件输出问题处理：通过。

- 问题类型、处理路径、记录信息和下一步节点清楚。
- 安全违规优先级最高，能正确引导回 02 / 03 / 04 / 05。

## 残余限制

- 本次审查基于静态 HTML 动态稿和本地截图，不代表生产前端已完成真实路由接入。
- Playwright 截图验证了桌面和移动端视觉状态；键盘 Tab 顺序、屏幕阅读器语义、真实 API 错误分支仍需 Codes 接入后再做一轮实现级 QA。
- 14 模块当前 UI 不负责真实文件下载签发；若后端后续新增下载或归档写接口，需要在 05 文档和 UI 动作中补充。

## 结论

14 插件输出 UI 通过当前设计审查。已发现的问题均已在对应 HTML 和交接文档中修复。
