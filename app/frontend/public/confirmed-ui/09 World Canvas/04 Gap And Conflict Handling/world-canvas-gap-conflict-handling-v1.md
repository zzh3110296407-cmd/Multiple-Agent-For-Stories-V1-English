# 09 世界画布 / 04 缺口与冲突处理 UI V1

## 页面定位

该页用于处理世界画布草案审阅中发现的未知规则、逻辑冲突和用户确认项。

它不重新生成完整世界画布，也不直接确认事实底座。用户在这里逐项选择处理方案并保存，所有必处理项完成后，才能返回审阅确认并进入确认草案流程。

## 用户侧结构

1. 顶部
   - 返回总览。
   - 面包屑：主页 / 当前项目 / 世界画布。
   - 状态：问题处理中 / 处理完成。
2. 局部阶段条
   - 来源前提。
   - 生成草案。
   - 审阅确认。
   - 事实底座。
3. 主体左侧：处理队列
   - 全部。
   - 未知规则。
   - 逻辑冲突。
   - 待确认。
   - 每个条目展示标题、摘要、类型或已处理状态。
4. 主体右侧：当前问题处理
   - 当前问题标题与类型。
   - 处理判断。
   - 来源证据。
   - 影响范围。
   - 建议处理。
   - 三个处理方案。
   - 写入草案预览。
   - 下游影响预览。
   - 处理说明输入。
5. 右侧辅助栏
   - 处理进度。
   - 写入边界。
   - 下一步。
6. 底部动作
   - 返回草案审阅。
   - 保存处理。
   - 继续确认：所有必处理项完成后启用。

## 前端状态映射

建议把该页建模为草案审阅的子流程：

```ts
type WorldCanvasIssueType = "unknown_rule" | "logic_conflict" | "confirmation";

type WorldCanvasIssueResolution = {
  issue_id: string;
  issue_type: WorldCanvasIssueType;
  selected_resolution: string;
  resolution_note: string;
  draft_write_preview: string;
  downstream_impact_preview: string;
  resolved: boolean;
};

type WorldCanvasGapConflictHandlingState = {
  worldCanvas: WorldCanvas;
  validation: WorldCanvasValidationResult;
  issues: WorldCanvasIssueResolution[];
  selectedIssueId: string;
  filter: "all" | "unknown_rule" | "logic_conflict" | "confirmation";
  canContinueConfirm: boolean;
};
```

`canContinueConfirm` 建议由以下条件决定：

```ts
issues.every((issue) => issue.resolved) &&
validation.blocking_issues.length === 0
```

## 数据来源

本页的问题队列来自世界画布草案与校验结果：

```ts
worldCanvas.unknown_rules
worldCanvas.logic_conflicts
worldCanvas.user_confirmation_needed
validation.warnings
validation.blocking_issues
```

用户侧不展示这些字段名，只展示：

- 未知规则。
- 逻辑冲突。
- 待确认。
- 阻塞问题。

## 对应接口

当前前端已有世界画布修订与确认接口：

```ts
reviseWorldCanvas(revisionPrompt)
// POST /api/world-canvas/revise
// body: { revision_prompt: string }
```

```ts
confirmWorldCanvas(userInput)
// POST /api/world-canvas/confirm
// body: { user_input?: string }
```

如果后端暂时没有单独的“保存问题处理”接口，前端可将本页处理结果合成为修订说明，走修订接口：

```ts
type IssueResolutionRevisionPayload = {
  revision_prompt: string;
};
```

生成的修订说明应包含：

- 当前处理的问题。
- 用户选择的方案。
- 用户填写的处理说明。
- 需要写回草案的事实变化。
- 需要保留给下游的影响说明。

如果后续新增独立接口，建议为：

```ts
saveWorldCanvasIssueResolutions(payload)
// POST /api/world-canvas/issue-resolutions
```

```ts
type SaveWorldCanvasIssueResolutionsPayload = {
  world_canvas_version_id: string;
  resolutions: Array<{
    issue_id: string;
    issue_type: "unknown_rule" | "logic_conflict" | "confirmation";
    selected_resolution: string;
    resolution_note: string;
  }>;
};
```

## 禁用与错误处理

“继续确认”禁用条件：

- 仍有未处理的未知规则。
- 仍有未处理的逻辑冲突。
- 仍有未处理的待确认项。
- 当前存在后端动作进行中。
- 草案已失效或版本不一致。
- 后端暂不可用。

用户侧错误文案：

- 仍有问题未处理。
- 草案版本已变化，请刷新后重试。
- 保存处理失败。
- 当前操作尚未完成。
- 后端暂不可用。

## 视觉与交互原则

- 左侧队列用于快速定位问题，不和草案全文混在一起。
- 中间只处理当前选中问题，避免用户同时面对过多决策。
- 每个处理方案都必须展示“写入草案”和“下游影响”，让用户明白选择后果。
- 保存处理后自动跳到下一条未处理问题，减少重复操作。
- 所有问题处理完成后，页面状态变为“处理完成”，并解锁“继续确认”。
- 不使用右侧创作路线组件。
- 用户侧不展示 raw API 字段名。

## 视觉稿

- HTML：`visual-drafts/world-canvas-gap-conflict-handling-v1.html`
- PNG：`visual-drafts/world-canvas-gap-conflict-handling-v1.png`
- 完成状态 PNG：`visual-drafts/world-canvas-gap-conflict-handling-v1-complete.png`
- 响应式 PNG：`visual-drafts/world-canvas-gap-conflict-handling-v1-responsive-1366x768.png`
- 背景：`visual-drafts/assets/world-canvas-cartography-background-v1.png`
