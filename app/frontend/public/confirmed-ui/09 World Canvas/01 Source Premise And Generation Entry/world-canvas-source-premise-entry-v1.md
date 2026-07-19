# 09 World Canvas / 01 来源前提与生成入口 UI V1

## 页面定位

该页是世界画布工作台的入口页。它承接 `08 Story Setup` 的交接结果，把已确认的故事设定前提加载为世界画布生成依据。

该页只提交世界画布草案生成请求，不确认最终世界事实，不写入角色、Framework、章节或场景的正式事实。

## 用户侧结构

1. 顶部
   - 返回总览。
   - 面包屑：主页 / 当前项目 / 世界画布。
   - 状态：前提可用 / 草案生成已提交。
2. 局部阶段条
   - 来源前提。
   - 生成草案。
   - 审阅确认。
   - 事实底座。
3. 主体左侧：受控故事前提
   - 前提摘要。
   - 核心信息。
   - 一致性。
   - 核心词标签。
   - 来源、项目来源、写入范围。
4. 主体右侧：生成世界画布草案
   - 可编辑的世界画布生成依据。
   - 生成前检查：来源前提、一致性、生成动作。
   - 重新载入前提。
   - 生成世界画布草案。
5. 右侧辅助栏
   - 可用性检查。
   - 安全边界。
   - 下一步说明。

## 对应接口

加载来源前提：

```ts
getCurrentProjectStoryPremise()
// GET /api/project-story-premise/current
```

返回重点字段：

```ts
{
  active_project_id: string,
  readiness: {
    project_id: string,
    readiness_status: "missing" | "ready" | "blocked",
    source_status: string,
    blocking_issues: string[],
    warnings: string[],
    safe_summary: string
  },
  premise: {
    project_id: string,
    origin_type: string,
    source_status: string,
    user_story_premise: string,
    safe_user_story_summary: string,
    core_terms: string[],
    setting_terms: string[],
    conflict_terms: string[],
    role_terms: string[],
    required_story_elements: string[],
    prompt_markers_detected: string[],
    forbidden_demo_defaults: string[],
    demo_default_leak_detected: boolean,
    prompt_fidelity_contract: {
      required_markers: string[],
      marker_counts: Record<string, number>,
      forbidden_demo_defaults: string[],
      demo_default_count: number,
      required_terms_present: Record<string, boolean>
    },
    blocking_issues: string[],
    warnings: string[],
    version_id: string
  } | null,
  safe_summary: string,
  source_refs: Record<string, unknown>
}
```

生成世界画布草案：

```ts
generateWorldCanvas(storyIdea)
// POST /api/world-canvas/generate
// body: { story_idea: string }
```

返回：

```ts
{
  world_canvas: WorldCanvas,
  validation: WorldCanvasValidationResult,
  decision?: Decision | null
}
```

## 禁用条件

生成按钮禁用条件应与当前前端一致：

```ts
!backendReady ||
Boolean(worldCanvasAction) ||
premiseReadiness.readiness_status === "blocked" ||
(premiseReadiness.readiness_status === "missing" && !premise) ||
!storyIdea.trim()
```

普通用户 UI 应显示为中文原因：

- 模型未就绪。
- 前提缺失。
- 前提阻塞。
- 生成文本为空。
- 当前操作尚未完成。

## 关键设计原则

- 使用制图室背景，表达“世界正在被绘制”。
- 前提和事实之间要有清晰边界：来源前提可作为生成依据，但不是最终世界事实。
- 不展示 raw API 字段名；`prompt_fidelity_status` 用户侧显示为“前提一致性”。
- 不使用右侧创作路线组件。
- 该页只负责提交生成，生成中状态进入第 2 页。

## 视觉稿

- HTML：`visual-drafts/world-canvas-source-premise-entry-v1.html`
- 背景：`visual-drafts/assets/world-canvas-cartography-background-v1.png`
