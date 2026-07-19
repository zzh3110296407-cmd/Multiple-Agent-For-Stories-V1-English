# 08 Story Setup / 06 交接与初始化 UI V1

## 页面定位

该页承接 `05 审查与决策` 中已经记录的 `confirm_for_handoff` 决定，用于完成两个动作：

1. 创建故事设定交接包。
2. 用交接包初始化当前项目草案工作区，并进入目标工作台继续确认。

该页不重新生成故事设定草案，不修改决定类型，不确认最终世界画布、角色、Framework 或章节计划，也不写入最终故事正文。

## 用户侧结构

顶部：

- 返回决策。
- 面包屑：主页 / 当前项目 / 故事设定 / 交接与初始化。
- 状态：等待交接 / 交接已就绪 / 初始化中 / 初始化完成。

主面板：

- 两步操作区：
  - 创建交接包。
  - 初始化当前项目。
- 交接目标：
  - 世界画布工作台。
  - 角色工作台。
  - Framework 工作台。
  - 章节计划工作台。
- 交接备注。
- 交接包清单：
  - 世界画布草案。
  - 角色主轴方向。
  - Framework 建议。
  - 章节路线建议。
- 初始化进度。
- 操作按钮：
  - 重置演示。
  - 创建交接包。
  - 初始化工作台。
  - 进入目标工作台。

右侧辅助信息：

- 交接状态。
- 安全边界。
- 初始化产物。

## 对应接口

创建交接包：

```ts
createStorySetupHandoff(storySetupDecisionId, {
  targetWorkspace:
    | "world_canvas_workspace"
    | "character_workspace"
    | "framework_workspace"
    | "chapter_planning_workspace",
  safeUserNote?: string
})
```

对应后端请求体：

```ts
{
  target_workspace: string,
  safe_user_note: string
}
```

初始化当前项目：

```ts
bootstrapStorySetupHandoff(storySetupHandoffId, {
  safeUserNote?: string
})
```

对应后端请求体：

```ts
{
  safe_user_note: string
}
```

可读接口：

```ts
getStorySetupHandoff(storySetupHandoffId)
getStorySetupSafetyReport(storySetupDraftBundleId)
getCurrentStorySetupState({ projectId })
```

## 启用条件

创建交接包按钮：

```ts
const canHandoff = Boolean(
  currentDecision.story_setup_decision_id
  && currentDecision.decision_type === "confirm_for_handoff"
)
```

初始化工作台按钮：

```ts
const canBootstrap = Boolean(
  currentHandoff.story_setup_handoff_id
  && currentHandoff.handoff_status === "ready"
)
```

进入目标工作台：

```ts
bootstrapStorySetupHandoff(...) 成功后启用
```

当前前端动作分发：

```ts
onStorySetupAction("create-handoff", {
  storySetupDecisionId,
  targetWorkspace,
  safeUserNote
})

onStorySetupAction("bootstrap-handoff", {
  storySetupHandoffId,
  safeUserNote: "Initialize active project draft workspace from Story Setup handoff."
})
```

## 返回字段

`StorySetupHandoff` 关键字段：

- `story_setup_handoff_id`
- `project_id`
- `story_setup_draft_bundle_id`
- `story_setup_decision_id`
- `handoff_status`
- `target_workspace`
- `world_canvas_draft_ref`
- `main_cast_direction_ref`
- `framework_suggestion_ref`
- `chapter_route_suggestion_ref`
- `selected_framework_composition_id`
- `generator_framework_context_ref`
- `requires_world_canvas_confirmation`
- `requires_character_confirmation`
- `requires_framework_confirmation`
- `requires_chapter_route_confirmation`
- `safe_summary`
- `warnings`

`StorySetupBootstrapResult` 关键字段：

- `story_setup_bootstrap_id`
- `project_id`
- `story_setup_handoff_id`
- `bootstrap_status`
- `story_bible_id`
- `world_canvas_id`
- `world_canvas_status`
- `story_data_scope`
- `created_files`
- `updated_files`
- `cleared_legacy_files`
- `setup_required_after_bootstrap`
- `next_workspace_id`
- `project_story_premise_status`
- `project_story_premise_ref`
- `project_story_premise_blocking_issues`
- `selected_framework_composition_id`
- `generator_framework_context_ref`
- `safe_summary`
- `warnings`

## 交互规则

- 创建交接包前，交接包清单显示为“等待交接”。
- 点击创建交接包后：
  - 状态变为“交接已就绪”。
  - 清单状态变为“已交接”。
  - 初始化按钮解锁。
  - 交接目标不锁定，用户仍可在初始化前调整。
- 点击初始化工作台后：
  - 交接目标锁定。
  - 初始化进入进度状态。
  - 完成后清单状态变为“已初始化”。
  - 显示初始化产物。
  - 解锁进入目标工作台。
- 初始化完成后进入目标工作台，真实项目中应调用现有工作台导航。
- 如果 `project_story_premise_blocking_issues` 非空，初始化结果区域应替换为阻塞状态，并给出返回故事设定或重新交接入口。

## 安全边界

该页必须明确以下边界：

- 不确认最终世界画布。
- 不确认最终角色档案。
- 不激活最终 Framework。
- 不确认章节计划。
- 不写入最终故事正文。
- 不展示原始提示词、原始模型响应、隐藏推理、密钥或授权头。

## 视觉原则

- 沿用 Story Setup 01-05 的书桌与羊皮纸视觉。
- 不使用右侧创作路线组件。
- 主体结构是“交接台 + 初始化清单”，而不是再次审查草案。
- 状态变化要清楚区分“交接包已创建”和“当前项目已初始化”。
- 所有下游模块都保持“仍需用户确认”的安全语义。
