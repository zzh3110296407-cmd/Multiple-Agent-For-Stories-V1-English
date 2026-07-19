# Projects And Works UI V1

日期：2026-07-02

状态：已采纳。该页作为 `继续创作 / 历史创作 / 作品集` 的统一项目档案页，后续不再单独维护旧作品集页面。

## 页面定位

`03 Projects And Works` 是 `继续创作 / 历史创作 / 作品集` 的统一项目选择页。它复用旧作品集的档案馆视觉方向，但功能上对齐 Phase 8.5 的项目列表、active project 和下一步进入逻辑。

## 设计目标

- `继续创作` 默认展示进行中项目，并自动选中最近编辑项目。
- `历史创作` 默认展示全部项目，包含完成、暂停、归档。
- `作品集` 默认按最近更新展示项目档案。
- 三个入口共用同一底层页面，只改变默认筛选、排序和主按钮语义。
- 用户可以搜索、筛选状态、切换网格/列表、选择项目并继续。
- 单击项目卡片只选中；双击项目卡片进入项目。

## 接口方向

主要对接：

- `getProjects()`
- `openProject(projectId)`
- `getActiveProjectSelection()`
- `setActiveProjectSelection(payload)`
- 后续联动 `getProductProgressState(params)`
- 后续联动 `getProductProgressNextActions(params)`

## 可视化稿

- `visual-drafts/projects-and-works-v1.html`
- `visual-drafts/projects-and-works-v1.png`
