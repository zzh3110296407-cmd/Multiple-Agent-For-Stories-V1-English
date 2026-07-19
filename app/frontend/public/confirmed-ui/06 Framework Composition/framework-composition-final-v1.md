# 06 Framework 编排 UI V1

日期：2026-07-03

## 状态

V1 可视化稿，当前覆盖 `01 初始编排页`。

## 页面定位

`Framework 编排` 承接 `模板与演示`，也为后续 `世界画布`、`角色`、`章节计划` 提供结构路线。它不直接写入世界、角色或章节事实，而是让用户先确认故事骨架和章节映射。

## V1 设计重点

- 左侧为 `结构素材`，用户从模板、分析器候选、资料库、私有结构中选择可用素材。
- 中央为 `编排画布`，默认只显示可横向滑动的 `主骨架`。
- 点击主骨架中的某一章后，主骨架会淡出并切换为该章的 `章节结构`。
- 右侧为可上下滑动的 `章节路线`，章数通过单个下拉按钮选择 `1-20` 章，路线节点不使用竖向连接线。
- 右下角为动作 Dock，初始状态只启用 `生成编排`，`验证` 和 `确认 Framework` 暂不可用。

## 对接接口方向

后续 Codes 接入时：

- 当前 workbench 状态来自 `getFrameworkWorkbench()`。
- 初始草案创建来自 `createFrameworkCompositionDraft(payload)`。
- 草案列表来自 `getFrameworkCompositionDrafts()`。
- 验证来自 `validateFrameworkCompositionDraft(compositionId)` 与 `validateFrameworkWorkbenchMapping()`。
- 确认来自 `confirmFrameworkCompositionDraft(compositionId)` 与 `confirmFrameworkWorkbenchMapping(userInput, acceptWarnings)`。
- 章节数量与映射来自 `updateFrameworkWorkbenchChapterCount(...)`、`recommendFrameworkWorkbenchMapping(...)`、`updateFrameworkWorkbenchAssignment(...)`。
- 资料库来源来自 `FrameworkModuleLibraryItem`、`FrameworkPatternRecord`、`ModuleCompositionRule`、`UserPrivateFramework`。
- 分析器候选来源来自 Analyze Stories framework candidates；它作为素材栏分支，不作为普通主线首屏。

## V1 交互

- 点击结构素材标签：切换当前来源说明。
- 点击素材卡：切换选中素材，并同步到中央画布标题。
- 点击用户模式：切换原创、续写改编、混合改编。
- 点击章节路线节点：切换当前聚焦章节。
- 点击章数按钮：展开 `1-20` 章选择菜单，并同步主骨架与右侧章节路线。
- 点击主骨架章卡：主骨架动效淡出，对应章节结构动效浮现。
- 点击章节结构中的 `返回主骨架`：回到横向主骨架视图。
- 点击 `生成编排`：显示生成提示，代表后续接入 `createFrameworkCompositionDraft`。

## 可视化稿

- `visual-drafts/framework-composition-v1.html`
- `visual-drafts/framework-composition-v1.png`
