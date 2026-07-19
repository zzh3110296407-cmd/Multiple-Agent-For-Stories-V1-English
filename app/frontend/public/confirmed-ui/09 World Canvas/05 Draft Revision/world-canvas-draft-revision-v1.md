# 09 世界画布 / 05 修订草案 UI V1

## 页面定位

该页用于在世界画布确认前对草案进行受控修订。

它不是重新生成入口，也不是最终确认入口。用户在这里选择修订范围、修订重点并填写修订说明；系统基于当前草案生成新的草案版本。修订完成后，用户应回到草案审阅页重新审阅。

## 用户侧结构

1. 顶部
   - 返回总览。
   - 面包屑：主页 / 当前项目 / 世界画布。
   - 状态：待修订 / 修订中 / 修订完成。
2. 局部阶段条
   - 来源前提。
   - 生成草案。
   - 审阅确认。
   - 事实底座。
3. 主体左侧：草案上下文
   - 保护事实。
   - 可修订内容。
   - 已处理问题。
   - 当前版本、修订目标、来源状态、写入范围。
4. 主体右侧：修订说明
   - 修订范围：局部修订 / 模块重整 / 整体校准。
   - 修订重点：特殊规则、未知规则、历史脉络、地理轮廓、文化秩序、下游边界。
   - 修订内容输入。
   - 修订预览：会保留 / 会调整 / 不会写入。
   - 修订进度。
5. 右侧辅助栏
   - 修订安全。
   - 请求状态。
   - 下一步。
6. 底部动作
   - 返回草案审阅。
   - 恢复默认说明。
   - 提交修订 / 查看新草案。

## 前端状态映射

建议将该页建模为草案审阅的子流程：

```ts
type WorldCanvasRevisionScope = "local" | "module" | "broad";

type WorldCanvasDraftRevisionState = {
  worldCanvas: WorldCanvas;
  validation: WorldCanvasValidationResult;
  revisionScope: WorldCanvasRevisionScope;
  revisionFocus: string[];
  revisionPrompt: string;
  actionState: "idle" | "submitting" | "complete" | "error";
  revisedResult?: {
    world_canvas: WorldCanvas;
    validation: WorldCanvasValidationResult;
    decision?: Decision | null;
  };
};
```

UI 禁用建议：

```ts
const canSubmitRevision =
  backendReady &&
  !worldCanvasAction &&
  Boolean(worldCanvas) &&
  Boolean(revisionPrompt.trim());
```

## 对应接口

提交修订：

```ts
reviseWorldCanvas(revisionPrompt)
// POST /api/world-canvas/revise
// body: { revision_prompt: string }
```

返回：

```ts
{
  world_canvas: WorldCanvas,
  validation: WorldCanvasValidationResult,
  decision?: Decision | null
}
```

修订完成后，前端应进入新的草案审阅状态，读取新返回的 `world_canvas` 和 `validation`。

## 修订说明生成建议

如果 UI 拆分了“修订范围”和“修订重点”，前端可以把用户输入和 UI 选择合成为最终提交内容：

```ts
const finalRevisionPrompt = `
修订范围：${revisionScopeLabel}
修订重点：${revisionFocusLabels.join("、")}

用户修订说明：
${revisionPrompt}

保护边界：
- 保留来源前提。
- 保留已确认的故事方向与范围。
- 修订后仍保持草案状态，确认前不写入事实底座。
`;
```

## 页面需要保护的边界

修订页必须明确保护：

- 来源前提。
- 已处理的问题结论。
- 已确认的故事方向。
- 当前草案仍未写入事实底座。
- 角色、章节、场景正文不在本页生成。

用户侧可见文案应使用中文业务概念，不直接展示后端字段名。

## 错误处理

用户侧错误文案：

- 草案缺失，无法修订。
- 修订说明为空。
- 当前操作尚未完成。
- 修订失败，请稍后重试。
- 草案版本已变化，请刷新后重试。
- 后端暂不可用。

失败后操作：

- 保留用户输入。
- 提供重新提交。
- 提供返回草案审阅。

## 视觉与交互原则

- 修订页应强调“受控修改”，不是重新开始生成。
- 左侧展示保护事实和可修订边界，降低用户误改核心设定的风险。
- 右侧提供清晰的修订范围、修订重点和修订说明。
- 提交修订后展示修订中状态；完成后按钮变为“查看新草案”。
- 不使用右侧创作路线组件。
- 不在用户界面展示 raw API 字段名。

## 视觉稿

- HTML：`visual-drafts/world-canvas-draft-revision-v1.html`
- PNG：`visual-drafts/world-canvas-draft-revision-v1.png`
- 修订完成 PNG：`visual-drafts/world-canvas-draft-revision-v1-complete.png`
- 响应式 PNG：`visual-drafts/world-canvas-draft-revision-v1-responsive-1366x768.png`
- 背景：`visual-drafts/assets/world-canvas-cartography-background-v1.png`
