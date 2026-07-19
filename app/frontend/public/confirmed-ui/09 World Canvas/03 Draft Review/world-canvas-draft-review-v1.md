# 09 世界画布 / 03 草案审阅 UI V1

## 页面定位

该页展示世界画布生成完成后的草案内容，允许用户审阅世界事实、规则分层、未知规则、逻辑冲突和待确认项。

该页不直接写入事实底座。只有在用户处理必要问题并点击“确认草案”后，才进入确认保存流程。

## 用户侧结构

1. 顶部
   - 返回总览。
   - 面包屑：主页 / 当前项目 / 世界画布。
   - 状态：待审阅。
2. 局部阶段条
   - 来源前提。
   - 生成草案。
   - 审阅确认。
   - 事实底座。
3. 主体：草案内容
   - 总览。
   - 世界结构。
   - 历史脉络。
   - 地理轮廓。
   - 文化秩序。
   - 特殊规则。
4. 草案摘要
   - 版本。
   - 故事方向。
   - 确认范围。
   - 规则分层。
5. 审查项
   - 全部。
   - 未知规则。
   - 逻辑冲突。
   - 待确认。
   - 点击审查项后展示对应详情。
6. 右侧辅助栏
   - 审阅状态。
   - 来源前提。
   - 下游影响。
7. 底部动作
   - 修订草案。
   - 处理问题。
   - 确认草案：当前有待确认项时禁用。

## 前端状态映射

该页消费生成接口返回的成功结果：

```ts
type WorldCanvasDraftReviewState = {
  worldCanvas: WorldCanvas;
  validation: WorldCanvasValidationResult;
  decision?: Decision | null;
  selectedSection:
    | "overview"
    | "world_structure"
    | "history"
    | "geography"
    | "culture"
    | "special_rules";
  selectedIssueType: "all" | "unknown_rules" | "logic_conflicts" | "confirmation";
  selectedIssueId?: string;
  canConfirm: boolean;
};
```

`canConfirm` 建议由以下条件共同决定：

```ts
validation.passed &&
validation.blocking_issues.length === 0 &&
worldCanvas.user_confirmation_needed.length === 0
```

如果产品允许带确认项进入确认页，则“确认草案”可用，但确认弹层必须再次列出确认项并要求用户输入确认说明。

## 对应接口

加载当前世界画布草案：

```ts
getCurrentWorldCanvas()
// GET /api/world-canvas/current
```

生成接口完成后也可直接进入本页：

```ts
generateWorldCanvas(storyIdea)
// POST /api/world-canvas/generate
// body: { story_idea: string }
```

返回核心结构：

```ts
{
  world_canvas: WorldCanvas,
  validation: WorldCanvasValidationResult,
  decision?: Decision | null
}
```

页面展示字段：

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

审查状态字段：

```ts
type WorldCanvasValidationResult = {
  passed: boolean;
  warnings: string[];
  blocking_issues: string[];
};
```

进入修订草案：

```ts
reviseWorldCanvas(revisionPrompt)
// POST /api/world-canvas/revise
// body: { revision_prompt: string }
```

确认草案：

```ts
confirmWorldCanvas(userInput)
// POST /api/world-canvas/confirm
// body: { user_input?: string }
```

## 禁用与错误处理

“确认草案”禁用条件：

- 有阻塞问题。
- 有必须处理的用户确认项。
- 当前后端不可用。
- 当前存在世界画布动作进行中。
- 世界画布草案缺失。

用户侧错误文案：

- 草案缺失。
- 草案仍有阻塞问题。
- 待确认项尚未处理。
- 当前操作尚未完成。
- 后端暂不可用。

## 视觉与交互原则

- 继续使用制图室背景，强调草案仍在“审阅桌面”上。
- 主体内容以文本审阅为主，避免把所有信息堆成同等权重卡片。
- 审查项独立成栏，用户可快速定位未知规则、逻辑冲突和待确认项。
- 不展示 raw API 字段名；用户侧只显示中文业务概念。
- 不使用右侧创作路线组件。
- 确认动作必须弱于“处理问题”，直到确认条件满足。

## 视觉稿

- HTML：`visual-drafts/world-canvas-draft-review-v1.html`
- PNG：`visual-drafts/world-canvas-draft-review-v1.png`
- 审查项筛选 PNG：`visual-drafts/world-canvas-draft-review-v1-issues.png`
- 响应式 PNG：`visual-drafts/world-canvas-draft-review-v1-responsive-1366x768.png`
- 背景：`visual-drafts/assets/world-canvas-cartography-background-v1.png`
