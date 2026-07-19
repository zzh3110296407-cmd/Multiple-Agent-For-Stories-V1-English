# 04 Current Project Overview UI V1

日期：2026-07-02

## 状态

V1 可视化稿。

## 设计定位

`当前项目总览` 是用户从 `03 Projects And Works` 打开某个故事项目后的第一屏。它不是项目列表，而是 active project 的状态中枢。

## V1 页面结构

- 顶部：返回档案馆、面包屑、主题标识。
- 项目身份：项目标题、来源、模型状态、当前阶段摘要。
- 中央：创作进度地图，展示 `故事设定 -> Framework -> 世界画布 -> 角色 -> 章节计划 -> 场景写作 -> 最终输出`。
- 右侧：下一步主行动，只突出一个最重要 CTA。
- 下方：决策与阻塞列表，以及工作区快速入口。

## 交互

- 点击工作区卡片或下一步行动：切换当前聚焦工作区，右侧主行动和详情随之变化。
- 点击快速入口：同样切换聚焦工作区；不可用入口保持锁定状态。
- 点击下一步：触发轻量提示，代表后续 Codes 接入时调用 `onNavigateWorkspace(target_workspace_id)`。

## 接口对接方向

后续 Codes 接入时：

- 项目身份来自 `navigationState.current_project_header` 和 `navigationState.origin_badge`。
- 进度路线状态来自 `productProgressState.summary` 与 `navigationState.availability.items[]`。
- 下一步主行动来自 `productProgressState.next_actions[0]`。
- 决策事项来自 `productProgressState.decision_surfaces[]`。
- 阻塞事项来自 `productProgressState.blocking_issues[]`。
- 普通 UI 不展示 `expert_evidence_links`、raw payload、trace 或完整故事正文。

## 可视化稿

- `visual-drafts/current-project-overview-v1.html`
- `visual-drafts/current-project-overview-v1.png`
