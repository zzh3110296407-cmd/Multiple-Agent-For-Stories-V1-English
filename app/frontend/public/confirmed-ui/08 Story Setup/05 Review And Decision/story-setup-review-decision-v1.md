# 08 Story Setup / 05 审查与决策 UI V1

## 页面定位

审查与决策页承接 `03 草案审阅` 和 `04 缺失信息处理`。该页用于让用户在最终进入交接前记录一个明确决定。

该页只创建 `StorySetupDecision`，不创建 handoff，不初始化项目工作台，不写入最终故事事实。

## 用户侧结构

1. 顶部
   - 返回审阅
   - 面包屑：主页 / 当前项目 / 故事设定 / 审查与决策
   - 状态：等待决定 / 等待记录 / 确认已记录 / 修订已记录 / 延后已记录 / 拒绝已记录
2. 主面板
   - 决策前检查：草案完整、缺失信息补齐、安全报告通过、仍需下游确认
   - 决定类型四选一：
     - 确认为交接草案
     - 请求修订
     - 延后决定
     - 拒绝草案
   - 安全备注 / 修订说明
   - 记录决定
   - 确认交接决定记录后解锁“进入交接准备”
3. 右侧
   - 草案摘要
   - 安全边界
   - 决定记录 ID

## 对应接口

核心接口：

```ts
createStorySetupDecision(storySetupDraftBundleId, {
  decisionType:
    | "confirm_for_handoff"
    | "request_revision"
    | "defer"
    | "reject",
  safeUserNote?: string,
  requestedChanges?: string[]
})
```

该页可读取但不创建：

```ts
getStorySetupDraftBundle(storySetupDraftBundleId)
getStorySetupQuestions(storySetupDraftBundleId)
getStorySetupSafetyReport(storySetupDraftBundleId)
```

确认决定后的下一页才使用：

```ts
createStorySetupHandoff(storySetupDecisionId, {
  targetWorkspace: string,
  safeUserNote?: string
})
```

## 关键字段

`StorySetupDecision`：

- `story_setup_decision_id`
- `project_id`
- `story_setup_draft_bundle_id`
- `decision_type`
- `decision_status`
- `decision_scope`
- `safe_user_note`
- `requested_changes`
- `does_not_confirm_world_canvas_final`
- `does_not_confirm_characters_final`
- `does_not_confirm_framework_final`
- `does_not_confirm_chapter_plan_final`
- `does_not_write_story_facts`

## 交互

- 用户选择一个决定类型后，记录按钮解锁。
- 顶部状态卡和右侧草案摘要必须跟随决定类型变化：
  - `confirm_for_handoff`：通过 / 准备交接 / 已确认交接。
  - `request_revision`：需修订 / 不进入交接 / 修订请求。
  - `defer`：暂缓 / 等待后续审阅 / 延后决定。
  - `reject`：已拒绝 / 不进入交接 / 已拒绝。
- `request_revision` 显示修订说明语义，保存时应填入 `requested_changes`。
- `confirm_for_handoff` 记录后解锁“进入交接准备”。
- `defer` / `reject` 记录后不进入交接。
- 重选会清空当前页面上的决定状态。

## 视觉原则

- 继续沿用 01-04 的书桌与羊皮纸背景。
- 不使用右侧“创作路线”组件。
- 页面只聚焦“记录决定”，避免和下一页交接创建混在一起。
- 强调安全边界：确认草案不等于确认最终世界画布、角色、Framework 或章节计划。
