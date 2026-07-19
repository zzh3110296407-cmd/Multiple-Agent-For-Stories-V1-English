# 08 Story Setup / 04 缺失信息处理 UI V1

## 页面定位

缺失信息处理承接 `03 Draft Review` 中的待补充问题。该页集中处理 `StorySetupQuestions`，让用户逐项回答系统识别出的缺口，并把回答保存为故事设定草案的补充信息。

该页不直接写入最终故事事实，不确认最终世界画布、角色、Framework 或章节计划。

## 用户侧结构

1. 顶部
   - 返回审阅
   - 面包屑：主页 / 当前项目 / 故事设定 / 缺失信息处理
   - 状态：问题待补充 / 问题已补齐
2. 左侧问题队列
   - 问题类型
   - 问题文本
   - 影响摘要
   - 回答状态：未回答 / 已保存
3. 中央回答区
   - 当前问题详情
   - `answer_status` 显示
   - 回答输入框
   - 建议选项快速填入
   - 保存回答
   - 暂时跳过
   - 全部回答后回到草案审阅
4. 右侧影响预览
   - 当前答案影响的草案模块
   - 草案状态预览
   - 安全边界

## 对应接口

读取问题：

```ts
getStorySetupQuestions(storySetupDraftBundleId)
```

保存回答：

```ts
answerStorySetupQuestion(questionId, {
  answerText: string,
  safeUserNote?: string
})
```

保存后建议重新读取：

```ts
getStorySetupQuestions(storySetupDraftBundleId)
getStorySetupDraftBundle(storySetupDraftBundleId)
```

如果用户选择“请求修订”，后续仍由草案审阅页调用：

```ts
createStorySetupDecision(storySetupDraftBundleId, {
  decisionType: "request_revision",
  requestedChanges: string[],
  safeUserNote?: string
})
```

## 关键字段

`StorySetupQuestion`：

- `story_setup_question_id`
- `project_id`
- `story_setup_intake_id`
- `story_setup_draft_bundle_id`
- `question_type`
- `question_text`
- `suggested_options`
- `answer_status`
- `user_answer_ref`
- `safe_answer_summary`

`StorySetupIntake` 中用于入口摘要：

- `missing_information_codes`
- `question_ids`
- `detected_world_scope`
- `detected_protagonist_hint`
- `detected_tone_tags`

保存回答 payload：

- `answer_text`
- `safe_user_note`

## 交互

- 点击左侧问题卡切换当前问题。
- 点击建议选项会填入回答框，但仍需用户保存。
- 保存回答后当前问题状态变为“已保存”，进度条更新。
- 全部问题保存后，“回到草案审阅”可用。
- 暂时跳过只切换到下一个问题，不保存。

## 视觉原则

- 继续沿用 01-03 的书桌与羊皮纸背景。
- 不再使用右侧“创作路线”组件。
- 页面聚焦问题处理，不重复展示完整草案。
- 明确回答只补全草案，不写入最终故事事实。
