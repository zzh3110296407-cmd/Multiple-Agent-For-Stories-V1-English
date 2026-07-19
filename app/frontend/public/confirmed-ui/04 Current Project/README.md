# 04 Current Project - Final V1

日期：2026-07-02

## 定稿结论

`04 Current Project` 已采纳为当前项目总览页。

该页承接 `03 Projects And Works` 中双击或继续项目后的入口，定位为 active project 的状态中枢，不重复项目列表。

## 已确认主线顺序

```text
故事设定 -> Framework -> 世界画布 -> 角色 -> 章节计划 -> 场景写作 -> 最终输出
```

其中 Framework 位于世界画布之前。

## 已归档文件

- `current-project-overview-final-v1.md`
- `current-project-overview-proposal-final-v1.md`
- `visual-drafts/current-project-overview-final-v1.html`
- `visual-drafts/current-project-overview-final-v1.png`

## 接口方向

后续 Codes 接入时以 Phase 8.5 当前接口为准：

- `getProductNavigationState(params)`
- `getProductWorkspaceAccess(workspaceId, params)`
- `getProductProgressState(params)`
- `getProductProgressNextActions(params)`
- `getProductProgressDecisionSurfaces(params)`
- `getProductProgressBlockingIssues(params)`
- `getActiveProjectSelection()`
- `openProject(projectId)`

普通用户 UI 不展示 expert evidence、raw payload、trace 或完整故事正文。
