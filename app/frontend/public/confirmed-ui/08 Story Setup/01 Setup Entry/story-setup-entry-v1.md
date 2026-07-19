# 08 Story Setup / 01 设定入口 UI V1

## 页面定位

故事设定入口是 Prompt-first 项目进入故事工作台前的第一步。用户在这里自由描述故事方向，系统后续会整理为可审阅的设定草案。

该页不直接确认最终世界画布、角色、Framework 或章节计划。

## 用户侧结构

1. 顶部
   - 返回项目
   - 面包屑：主页 / 当前项目 / 故事设定
   - 模型状态提示
2. 主输入区
   - 当前项目
   - Framework 参考
   - 语言
   - 设定构想大输入区
   - 载入项目提示词
   - 生成设定草案
3. 右侧
   - 交接目标：世界画布、角色主轴、Framework、章节计划
   - 边界提示：本页只生成和确认设定草案

## 对应接口

创建 prompt：

```ts
createStorySetupPromptFromProject({
  projectId: string,
  creationRequestId?: string | null,
  promptText?: string | null,
  safeUserNote?: string
})
```

后续 02 生成中会继续调用：

```ts
createStorySetupIntake(storySetupPromptId)
createStorySetupDraftBundle({
  storySetupPromptId: string,
  storySetupIntakeId?: string | null,
  selectedFrameworkCompositionId?: string | null
})
```

## 关键字段

- `project_id`
- `creation_request_id`
- `prompt_text`
- `safe_user_note`
- `selected_framework_composition_id`
- `language`
- `active_model_selection_id`
- `model_health_status_at_creation`

## 交互

- 输入区实时统计字数。
- 空输入点击生成时提示用户补充设定构想。
- 点击阶段条展示对应状态提示，不跳转到未完成页面。
- 交接目标可切换，并更新右侧说明。
- 生成按钮进入短暂 loading，随后显示“草案待审阅”状态。
- 不再使用“创作路线”组件；后续故事设定页面也不再加入创作路线。

## 视觉原则

- 背景使用安静书桌、羊皮纸、墨水和星图线稿，弱化叙事冲击，突出设定草稿感。
- 主面板占页面主要宽度，保证用户自由输入。
- 安全边界和模型状态保持轻量，不进入主视觉。
