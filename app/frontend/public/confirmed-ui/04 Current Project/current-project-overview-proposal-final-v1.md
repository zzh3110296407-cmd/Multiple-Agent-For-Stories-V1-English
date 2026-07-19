# 04 Current Project Overview - Proposal V1

日期：2026-07-02

## 页面定位

`04 Current Project` 是用户选中或打开某个项目后进入的当前项目总览页。它不再展示作品列表，而是回答三个问题：

- 这个项目是谁、从哪里来、当前是否可继续真实创作。
- 项目现在处于哪一个创作阶段，下一步最应该去哪里。
- 有哪些需要用户确认或处理的阻塞项。

## 与 03 Projects And Works 的关系

`03 Projects And Works` 负责选择项目。

`04 Current Project` 负责进入项目后的总览和导航。

推荐交互：

- 在 `03` 单击项目：只更新右侧选中详情。
- 在 `03` 双击项目或点击继续：调用打开项目逻辑，并进入 `04`。
- `04` 左上保留返回项目档案馆入口，但不再重复完整项目列表。

## 当前代码与接口事实

前端对应：

```text
frontend\src\views\ProductHomeWorkspace.jsx
frontend\src\components\ProductAppShell.jsx
frontend\src\api\projectApi.js
```

主要接口：

- `getProductNavigationState({ projectId, workspaceId, modeProfileId })`
- `getProductWorkspaceAccess(workspaceId, params)`
- `patchProductNavigationPreferences(payload)`
- `getProductProgressState({ projectId, modeProfileId })`
- `getProductProgressSummary(params)`
- `getProductProgressNextActions(params)`
- `getProductProgressDecisionSurfaces(params)`
- `getProductProgressBlockingIssues(params)`
- `getActiveProjectSelection()`
- `openProject(projectId)`

关键数据：

- `navigationState.current_project_header`
- `navigationState.origin_badge`
- `navigationState.availability.items[]`
- `productProgressState.summary`
- `productProgressState.next_actions[]`
- `productProgressState.decision_surfaces[]`
- `productProgressState.blocking_issues[]`
- `productProgressState.safety_report`

## 页面结构建议

### 1. 项目身份区

左上展示当前项目标题、项目来源、语言、最近更新时间和当前模型状态。

来源 badge 应该温和但清晰：

- 空白项目
- 从构想开始
- 模板项目
- 演示项目
- 故事分析导入

如果 `origin_requires_review` 为 true，需要显示“需要先确认来源”的提示，并把主要下一步指向来源处理位置。

### 2. 创作进度地图

中部使用横向或轻弧形路线，把 Phase 8.5 用户主线展示为可扫描进度：

```text
故事设定 -> Framework -> 世界画布 -> 角色 -> 章节计划 -> 场景写作 -> 最终输出
```

每个节点有四种状态：

- 已完成
- 当前阶段
- 可进入
- 暂不可用

状态来源优先用：

- `productProgressState.summary.current_stage_id`
- `productProgressState.summary.current_stage_label`
- `navigationState.availability.items[]`

### 3. 下一步主行动

右侧或右下固定一个主要行动区，只显示 1 个主 CTA：

- 来自 `productProgressState.next_actions[0].title`
- 点击后进入 `target_workspace_id`
- 若 `blocked` 为 true，按钮变成处理阻塞，并显示 `blocked_reason`
- 若 `required_confirmation` 为 true，在按钮旁显示需要确认的轻提示

这个区是页面的行动核心，不要把所有工作台按钮都放成同等权重。

### 4. 决策与阻塞

下方或右侧第二层展示：

- `decision_surfaces[]`：例如确认世界画布、确认主角团、确认框架映射、确认章节计划、确认场景候选。
- `blocking_issues[]`：例如模型未配置、演示项目不能真实创作、场景质量阻断。

普通用户界面只显示标题、原因和去处理按钮，不展示 raw payload、trace、expert evidence。

### 5. 快速入口

可放在底部或右侧窄栏：

- 故事设定
- Framework
- 世界画布
- 角色
- 章节计划
- 场景写作
- 最终输出
- 设置

入口状态必须读 `availability.items[]`，不可访问时显示锁定态和安全跳转目标。

## 视觉方向

我建议这页继续使用羊皮卷莫兰迪基调，但不使用主页飞龙背景。

背景可以设计成“项目地图桌面”：

- 低对比羊皮纸桌面纹理。
- 模糊的墨线地图、路线点、旧纸标签。
- 当前项目像被打开的故事档案，不做重卡片堆叠。
- 中部进度路线有轻微流动感，用户进入页面时节点依次点亮。

这样它和 03 档案馆有连续性，又能明显告诉用户：现在已经进入某个故事内部。

## 不做的内容

- 不展示完整作品列表。
- 不展示专家诊断、raw evidence、trace、完整 story prose。
- 不在本页直接生成故事事实。
- 不把所有后续工作台的详细操作压进本页。

## 后续可视化重点

V1 可视化应优先表现：

- 当前项目标题与来源。
- 中央创作进度地图。
- 右侧下一步主行动。
- 决策/阻塞轻量列表。
- 左下返回项目档案馆。
