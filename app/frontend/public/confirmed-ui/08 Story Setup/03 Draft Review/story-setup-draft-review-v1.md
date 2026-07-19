# 08 Story Setup / 03 草案审阅 UI V1

## 页面定位

草案审阅承接 `02 Generating` 的“查看草案”。该页把 `StorySetupDraftBundle` 从调试 JSON 转成用户能理解的审阅界面，让用户逐项查看四类候选设定，并作出审阅决定。

该页仍然只处理故事设定草案，不写入最终故事事实。

## 用户侧结构

1. 顶部
   - 返回生成
   - 面包屑：主页 / 当前项目 / 故事设定 / 草案审阅
   - 模型状态提示
2. 主审阅区
   - 四类草案模块：世界画布建议、角色方向、Framework 建议、章节路线建议
   - 点击模块后右侧详情切换
   - 详情包含建议保留、需要确认、来源字段、写入状态、后续工作台
3. 右侧
   - 待补充问题：来自 `StorySetupQuestions`
   - 交接目标：选择后续目标工作台
   - 边界检查：明确不确认最终世界画布、角色、Framework 或章节计划
4. 底部动作
   - 请求修订
   - 延后
   - 拒绝
   - 确认为交接草案

## 对应接口

该页主要消费：

```ts
getStorySetupDraftBundle(storySetupDraftBundleId)
getStorySetupQuestions(storySetupDraftBundleId)
answerStorySetupQuestion(questionId, {
  answerText: string,
  safeUserNote?: string
})
createStorySetupDecision(storySetupDraftBundleId, {
  decisionType: "confirm_for_handoff" | "request_revision" | "defer" | "reject",
  safeUserNote?: string,
  requestedChanges?: string[]
})
getStorySetupSafetyReport(storySetupDraftBundleId)
```

确认后进入后续交接页时继续使用：

```ts
createStorySetupHandoff(storySetupDecisionId, {
  targetWorkspace:
    | "world_canvas_workspace"
    | "character_workspace"
    | "framework_workspace"
    | "chapter_planning_workspace",
  safeUserNote?: string
})
bootstrapStorySetupHandoff(storySetupHandoffId, {
  safeUserNote?: string
})
```

## 关键字段

`StorySetupDraftBundle`：

- `story_setup_draft_bundle_id`
- `bundle_status`
- `world_canvas_draft_suggestion`
- `main_cast_draft_direction`
- `framework_setup_suggestion`
- `chapter_route_suggestion`
- `selected_framework_composition_id`
- `generator_framework_context_ref`
- `question_ids`
- `decision_ids`
- `creates_final_story_facts_now`
- `requires_downstream_confirmation`
- `warnings`

`StorySetupQuestion`：

- `story_setup_question_id`
- `question_type`
- `question_text`
- `suggested_options`
- `answer_status`
- `safe_answer_summary`

`StorySetupDecision`：

- `decision_type`
- `decision_status`
- `decision_scope`
- `requested_changes`
- `does_not_write_story_facts`
- `does_not_confirm_world_canvas_final`
- `does_not_confirm_characters_final`
- `does_not_confirm_framework_final`
- `does_not_confirm_chapter_plan_final`

## 交互

- 点击四类草案卡片切换详情面板，带轻微纸面光扫过渡。
- 待补充问题可展开、填写、保存。
- 交接目标可选择目标工作台。
- `确认为交接草案` 记录 `decision_type: "confirm_for_handoff"`，下一步才创建 handoff。
- `请求修订` 记录 `decision_type: "request_revision"`，并带 `requested_changes`。
- `延后` 和 `拒绝` 分别记录 `defer` / `reject`。

## 视觉原则

- 继续沿用 01/02 的书桌与羊皮纸背景。
- 不再使用右侧“创作路线”组件。
- 四类草案以审阅卡片呈现，不直接暴露 JSON。
- 决策按钮集中在底部，避免用户误以为确认草案等于确认最终故事事实。
