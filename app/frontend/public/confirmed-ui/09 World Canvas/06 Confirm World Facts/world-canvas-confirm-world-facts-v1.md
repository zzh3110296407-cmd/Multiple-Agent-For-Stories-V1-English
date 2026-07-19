# 09 世界画布 / 06 确认世界事实 UI V1

## 页面定位

该页是世界画布流程的最终确认页。

用户在这里确认草案已审阅、缺口与冲突已处理，并允许后续模块读取当前世界画布作为事实底座。确认成功后，世界画布状态变为已确认。

该页不生成角色、章节或场景正文，也不重新生成世界画布。

## 用户侧结构

1. 顶部
   - 返回总览。
   - 面包屑：主页 / 当前项目 / 世界画布。
   - 状态：待确认 / 确认中 / 已确认。
2. 局部阶段条
   - 来源前提。
   - 生成草案。
   - 审阅确认。
   - 事实底座。
   - 确认成功后，激活“事实底座”。
3. 主体左侧：最终核对
   - 事实总览。
   - 规则分层。
   - 下游读取。
   - 世界方向、确认范围、规则状态摘要。
4. 主体右侧：确认清单
   - 我已审阅世界事实草案。
   - 缺口与冲突已经处理。
   - 确认后允许下游模块读取。
   - 确认说明。
   - 写入范围。
5. 右侧辅助栏
   - 确认状态。
   - 下游读取。
   - 下一步。
6. 底部动作
   - 返回草案审阅。
   - 继续修订。
   - 确认世界事实 / 进入事实底座。

## 前端状态映射

建议状态：

```ts
type WorldCanvasConfirmState = {
  worldCanvas: WorldCanvas;
  validation: WorldCanvasValidationResult;
  confirmChecklist: {
    reviewed: boolean;
    issuesResolved: boolean;
    downstreamAllowed: boolean;
  };
  confirmationText: string;
  actionState: "idle" | "confirming" | "confirmed" | "error";
};
```

确认按钮启用条件：

```ts
const canConfirm =
  backendReady &&
  !worldCanvasAction &&
  Boolean(worldCanvas) &&
  validation.passed &&
  validation.blocking_issues.length === 0 &&
  confirmChecklist.reviewed &&
  confirmChecklist.issuesResolved &&
  confirmChecklist.downstreamAllowed &&
  Boolean(confirmationText.trim());
```

## 对应接口

确认世界画布：

```ts
confirmWorldCanvas(userInput)
// POST /api/world-canvas/confirm
// body: { user_input?: string }
```

推荐传入：

```ts
{
  user_input: confirmationText
}
```

返回：

```ts
{
  world_canvas: WorldCanvas,
  validation: WorldCanvasValidationResult,
  decision?: Decision | null
}
```

确认成功后，前端应：

- 更新世界画布为已确认状态。
- 激活事实底座阶段。
- 禁止把旧草案当作可确认草案再次确认。
- 允许后续模块读取已确认版本。

## 页面展示字段

最终核对使用：

```ts
worldCanvas.story_direction
worldCanvas.scope
worldCanvas.tone
worldCanvas.world_structure
worldCanvas.history_summary
worldCanvas.geography_summary
worldCanvas.culture_summary
worldCanvas.special_rules_summary
worldCanvas.hard_rules
worldCanvas.soft_rules
worldCanvas.unknown_rules
worldCanvas.logic_conflicts
worldCanvas.user_confirmation_needed
worldCanvas.version_id
```

用户侧不展示字段名，只展示中文业务概念。

## 禁用与错误处理

确认按钮禁用条件：

- 草案缺失。
- 校验未通过。
- 仍有阻塞问题。
- 仍有必处理确认项。
- 三项确认清单未完成。
- 确认说明为空。
- 当前存在后端动作进行中。
- 后端暂不可用。

用户侧错误文案：

- 草案缺失，无法确认。
- 草案仍有阻塞问题。
- 待确认项尚未处理。
- 确认说明为空。
- 确认失败，请稍后重试。
- 草案版本已变化，请刷新后重试。
- 后端暂不可用。

失败后操作：

- 保留勾选状态和确认说明。
- 提供重新确认。
- 提供返回草案审阅。
- 提供继续修订。

## 视觉与交互原则

- 确认页必须显得慎重、清晰，不让用户误点。
- 写入范围与不会写入的内容必须并列展示。
- 确认前状态仍处于“审阅确认”；确认成功后切换到“事实底座”。
- 确认成功后，下游读取状态从“等待”变为“可读”。
- 不使用右侧创作路线组件。
- 不在用户界面展示 raw API 字段名。

## 视觉稿

- HTML：`visual-drafts/world-canvas-confirm-world-facts-v1.html`
- PNG：`visual-drafts/world-canvas-confirm-world-facts-v1.png`
- 可确认状态 PNG：`visual-drafts/world-canvas-confirm-world-facts-v1-ready.png`
- 完成状态 PNG：`visual-drafts/world-canvas-confirm-world-facts-v1-complete.png`
- 响应式 PNG：`visual-drafts/world-canvas-confirm-world-facts-v1-responsive-1366x768.png`
- 背景：`visual-drafts/assets/world-canvas-cartography-background-v1.png`
