# 09 世界画布 / 02 生成中 UI V1

## 页面定位

该页是用户点击“生成世界画布草案”后的等待与进度状态页。

它只表达“草案正在生成”，不提供再次提交生成、不提供确认保存，也不把草案写入正式事实底座。生成完成后，用户进入“草案审阅页”继续处理世界事实、未知规则、逻辑冲突和用户确认问题。

## 用户侧结构

1. 顶部
   - 返回总览。
   - 面包屑：主页 / 当前项目 / 世界画布。
   - 状态：生成中 / 草案完成。
2. 局部阶段条
   - 来源前提。
   - 生成草案。
   - 审阅确认。
   - 事实底座。
3. 主体左侧：事实轮廓绘制
   - 生成进度圆环。
   - 当前生成模块。
   - 当前模块说明。
   - 来源前提、写入范围、下一步信号。
4. 主体右侧：生成模块
   - 世界结构。
   - 历史脉络。
   - 地理轮廓。
   - 文化秩序。
   - 特殊规则。
   - 规则缺口。
5. 右侧辅助栏
   - 生成状态。
   - 前提一致性。
   - 安全边界。
6. 底部操作
   - 后台继续。
   - 查看草案：生成完成前禁用，完成后启用。

## 前端状态映射

该页对应世界画布生成动作进行中：

```ts
worldCanvasAction === "generate"
```

生成按钮在上一页提交后应进入本页，或在同一工作台内切换到该状态。用户侧状态建议：

```ts
type WorldCanvasGeneratingViewState = {
  action: "generate";
  progressMode: "indeterminate" | "estimated";
  estimatedProgress?: number;
  currentModule?: "world_structure" | "history" | "geography" | "culture" | "special_rules" | "gaps";
  canOpenDraft: false;
  canSubmitAgain: false;
};
```

说明：当前后端接口不一定返回真实分段进度。如果没有后端进度事件，前端可使用估算进度和模块轮播，只在接口返回后切换为 100% 并启用“查看草案”。

## 对应接口

生成请求来源于上一页：

```ts
generateWorldCanvas(storyIdea)
// POST /api/world-canvas/generate
// body: { story_idea: string }
```

请求完成后进入草案审阅页，核心返回：

```ts
{
  world_canvas: WorldCanvas,
  validation: WorldCanvasValidationResult,
  decision?: Decision | null
}
```

草案审阅页需要继续展示或处理的世界画布字段：

```ts
type WorldCanvas = {
  status: string;
  story_direction?: string;
  scope?: string;
  tone?: string;
  version_id?: string;
  world_structure?: string;
  history_summary?: string;
  geography_summary?: string;
  culture_summary?: string;
  special_rules_summary?: string;
  hard_rules?: string[];
  soft_rules?: string[];
  unknown_rules?: string[];
  logic_conflicts?: string[];
  user_confirmation_needed?: string[];
  locations?: unknown[];
  factions?: unknown[];
  species?: unknown[];
  source_story_idea?: string;
  latest_user_prompt?: string;
};
```

## 禁用与错误处理

生成中状态：

- 禁用再次生成。
- 禁用确认保存。
- 禁用“查看草案”，直到生成接口返回成功。
- 允许“后台继续”或返回项目总览。

失败时不应停留在静默等待状态，应展示中文错误原因：

- 生成失败。
- 模型未就绪。
- 前提不可用。
- 草案解析失败。
- 当前项目状态不可写入。

失败后提供两个主要入口：

- 返回来源前提。
- 重新生成。

## 视觉与交互原则

- 继续使用制图室背景，表达“世界正在被绘制”。
- 主体不使用右侧创作路线组件。
- 进度动画保持柔和，避免高亮、闪烁和强对比。
- 模块状态用“等待 / 生成中 / 完成”，不显示 raw API 字段名。
- “查看草案”只有完成后出现可用状态，减少用户误操作。

## 视觉稿

- HTML：`visual-drafts/world-canvas-generating-v1.html`
- PNG：`visual-drafts/world-canvas-generating-v1.png`
- 完成状态 PNG：`visual-drafts/world-canvas-generating-v1-complete.png`
- 响应式 PNG：`visual-drafts/world-canvas-generating-v1-responsive-1366x768.png`
- 背景：`visual-drafts/assets/world-canvas-cartography-background-v1.png`
