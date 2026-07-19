# 08 Story Setup / 02 生成中 UI V1

## 页面定位

生成中状态承接 `01 Setup Entry` 的“生成设定草案”。该页用于展示系统正在把用户的初始构想整理为设定草案。

该页不提供正式确认动作，也不写入最终故事事实。

## 用户侧结构

1. 顶部
   - 返回设定
   - 面包屑：主页 / 当前项目 / 故事设定 / 生成中
   - 模型状态提示
2. 主画布
   - 草案浮现画布
   - 四类模块：世界画布建议、角色方向、Framework 建议、章节路线
   - 进度圆环
   - 阶段列表
3. 右侧
   - 总进度
   - 本次草案摘要
4. 底部动作
   - 后台继续
   - 查看草案：生成完成前禁用

## 对应接口

生成中状态在真实前端中由以下接口串联：

```ts
createStorySetupIntake(storySetupPromptId)
createStorySetupDraftBundle({
  storySetupPromptId: string,
  storySetupIntakeId?: string | null,
  selectedFrameworkCompositionId?: string | null
})
getStorySetupQuestions(storySetupDraftBundleId)
```

## 关键返回字段

`StorySetupIntake`：

- `intake_status`
- `detected_genre_tags`
- `detected_tone_tags`
- `detected_world_scope`
- `detected_core_conflict`
- `detected_protagonist_hint`
- `detected_story_length_hint`
- `missing_information_codes`
- `question_ids`
- `warnings`

`StorySetupDraftBundle`：

- `bundle_status`
- `world_canvas_draft_suggestion`
- `main_cast_draft_direction`
- `framework_setup_suggestion`
- `chapter_route_suggestion`
- `selected_framework_composition_id`
- `generator_framework_context_ref`
- `requires_downstream_confirmation`
- `creates_final_story_facts_now`
- `warnings`

## 状态映射

- 创建 intake 中：识别构想
- 创建 draft bundle 中：整理草案
- questions 返回中：检查缺口
- draft bundle ready：准备审阅

## 交互

- 页面自动推进视觉阶段。
- 四类草案模块随着进度逐步浮现。
- `后台继续` 可切换为暂停式后台状态。
- `查看草案` 在完成前禁用，完成后可点击并提示进入草案审阅。
- 不再使用“创作路线”组件；后续故事设定页面也不再加入创作路线。

## 视觉原则

- 继续沿用 01 的书桌与羊皮纸背景。
- 中央使用纸页扫描和墨迹浮现动效，强化“草案正在形成”。
- 用户看到的是故事设定层面的进度，不看到后端调试字段。
