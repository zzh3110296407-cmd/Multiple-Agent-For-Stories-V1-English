# 03 Projects And Works - Final V1

日期：2026-07-02

## 定稿结论

`03 Projects And Works` 已采纳为 `继续创作 / 历史创作 / 作品集` 的统一项目档案页。

三个入口不再分别设计三套页面，而是共用同一底层页面：

- `继续创作`：默认显示进行中项目，按最近编辑排序，主操作偏向继续进入当前进度。
- `历史创作`：默认显示全部项目，包含进行中、已完成、暂停、归档。
- `作品集`：默认显示可展示的项目档案，偏浏览和详情查看。

## 已归档文件

- `projects-and-works-final-v1.md`
- `visual-drafts/projects-and-works-final-v1.html`
- `visual-drafts/projects-and-works-final-v1.png`

## 接口方向

后续 Codes 接入时以 Phase 8.5 当前接口为准：

- `getProjects()`
- `openProject(projectId)`
- `getActiveProjectSelection()`
- `setActiveProjectSelection(payload)`
- `getProductProgressState(params)`
- `getProductProgressNextActions(params)`

单击项目只选中，双击项目进入当前项目总览。
