# 10 角色主轴 / 04 关系与冲突处理 V1

## 设计状态

- 状态：已采纳，并已完成 2026-07-04 全量审查。
- 页面定位：角色草案审阅后，用于处理关系来源、规则缺口、重复风险等待确认事项。
- 设计原则：本页只收集用户处理意见，不直接写入正式角色事实；所有正式写入仍发生在草案确认动作之后。

## 文件索引

- 交互 HTML：`visual-drafts/character-spine-conflict-handling-v1.html`
- 默认待处理态：`visual-drafts/character-spine-conflict-handling-v1.png`
- 规则缺口选中态：`visual-drafts/character-spine-conflict-handling-v1-rule-gap.png`
- 单项已处理态：`visual-drafts/character-spine-conflict-handling-v1-one-resolved.png`
- 全部已处理态：`visual-drafts/character-spine-conflict-handling-v1-all-resolved.png`
- 1366 响应式检查：`visual-drafts/character-spine-conflict-handling-v1-responsive-1366x768.png`
- 背景图：`visual-drafts/assets/character-spine-background-v1.png`

## 页面结构

1. 顶部导航区
   - 返回审阅。
   - 面包屑：主页 / 当前项目 / 角色主轴。
   - 状态胶囊：仍有待处理项，全部处理完成后变为可返回确认。

2. 顶部阶段条
   - 生成入口。
   - 生成草案。
   - 审阅确认。
   - 角色底座。
   - 当前高亮：审阅确认。

3. 主处理面板
   - 标题：先把草案里的疑点处理清楚。
   - 进度章：处理中 / 已处理。
   - 左侧待处理队列：展示需要用户处理的关系确认、规则缺口、重复风险。
   - 右侧详情区：展示当前问题、影响范围、标签、可选处理方案和补充说明。

4. 页面底部结果条
   - 当前角色。
   - 关系结果。
   - 下一步提示。

5. 右侧摘要区
   - 处理摘要：关系确认、规则缺口、重复风险、阻塞问题、完成度。
   - 写入边界：不改世界事实、不写入章节、作为确认说明。
   - 操作：返回审阅、回到草案确认。

## 交互说明

- 待处理队列：
  - 单击某个事项后，右侧详情和处理方案切换到对应内容。
  - 已处理事项保留在队列中，用弱化状态和勾选标记表示已完成，避免用户失去上下文。

- 处理方案：
  - 每个事项提供 3 个方案，用户单击后切换选中态。
  - 方案只形成确认说明，不立即改写角色档案。
  - 如果用户需要结构性修改，应从本页转入后续修订草案流程。

- 补充说明：
  - 可为空；为空时使用当前选中方案作为处理意见。
  - 有输入时，输入内容应随处理项一起进入后续确认或修订参数。

- 标记已处理：
  - 当前项从待处理变为已处理。
  - 自动跳到下一个未处理项。
  - 全部处理完成后，顶部状态变为可返回确认，进度为 100%，回到草案确认按钮解锁。

- 返回审阅：
  - 返回 03 草案审阅页，不提交处理结果。
  - 如果已有本地处理结果，正式实现时建议保存在前端临时状态中，避免误丢。

- 回到草案确认：
  - 仅在所有阻塞项处理完成后可用。
  - 返回 03 草案审阅页，并把处理结果带回确认说明区。

## 当前前端接口映射

04 关系与冲突处理页不是一个独立后端流程页，它是角色草案审阅和确认之间的 UI 处理层。

### A 级角色草案

- 数据来源：`CharacterWorkflowResponse.draft`
- 草案核心：

```ts
type CurrentCharacterDraft = {
  draft_id: string;
  source_world_canvas_id: string;
  character: Character;
  relationship_drafts: Relationship[];
  validation_report: CharacterValidationReport;
  latest_user_prompt: string;
  status: string;
};
```

- 可映射到本页的内容：
  - `relationship_drafts`：关系确认、关系强度、关系说明。
  - `validation_report.warnings`：可继续但建议处理的问题。
  - `validation_report.blocking_issues`：未处理前禁用确认的问题。
  - `validation_report.user_confirmation_needed`：需要用户明确选择的问题。

- 确认接口：

```ts
POST /api/characters/confirm
body: {
  user_input?: string;
}
```

- 修订接口：

```ts
POST /api/characters/revise
body: {
  revision_prompt: string;
}
```

- 接入规则：
  - 如果用户选择的是解释、保留、确认类方案，结果合并为 `user_input`，带回确认草案。
  - 如果用户选择的是改写、合并、拆分、重做类方案，应进入后续修订草案流程，并组合成 `revision_prompt`。
  - `blocking_issues.length > 0` 且未被用户处理时，确认按钮必须禁用。

### B/C/D 角色草案

- 数据来源：`RoleGenerationResponse.draft`
- 草案核心：

```ts
type CurrentRoleDraft = {
  draft_id: string;
  source_world_canvas_id: string;
  role: Character;
  complexity_profile: RoleComplexityProfile;
  validation_report: CharacterValidationReport;
  latest_user_prompt: string;
  status: string;
};
```

- 确认接口：

```ts
POST /api/roles/generated-draft/confirm
body: {
  user_input: string;
}
```

- 当前限制：
  - B/C/D 草案当前没有独立修订接口。
  - B/C/D 草案当前返回结构没有 `relationship_drafts`，不能假设一定有关系草稿数组。

- 接入规则：
  - 本页的关系事项应优先来自 `validation_report.user_confirmation_needed`、`validation_report.warnings`、`validation_report.blocking_issues`。
  - 如果未来 B/C/D 角色也返回关系候选，再把候选关系接入本页关系队列。
  - 如果用户处理结果只是确认说明，合并为 `user_input` 后进入确认。
  - 如果用户处理结果要求重新生成，应返回 01 角色主轴入口，或在后端新增修订接口后接入后续修订草案流程。

## 前端状态建议

```ts
type ResolvedConflictItem = {
  issueId: string;
  sourceType: "relationship" | "warning" | "blocking" | "confirmation";
  title: string;
  resolutionChoice: string;
  userNote?: string;
  status: "pending" | "resolved";
};
```

- `issueId`：前端可用来源类型加索引生成，不要求后端目前提供独立 ID。
- `sourceType`：用于决定是带入确认说明，还是转入修订流程。
- `resolutionChoice`：用户选择的方案。
- `userNote`：用户补充说明。
- `status`：控制本页队列、进度和确认按钮状态。

## 数据展示约束

- 正式 UI 不直接展示后端字段名、接口路径、debug、trace 或模型内部状态。
- 正式 UI 不展示旧版右侧创作路线。
- 本页不能承诺已经写入正式角色事实，只能表达“处理意见已形成”。
- 关系或冲突处理完后，仍需回到草案确认页完成最终确认。
- 用户未处理阻塞项时，确认动作必须被拦截。

## 检查记录

- 已检查默认待处理态。
- 已检查规则缺口选中态。
- 已检查单项已处理态。
- 已检查全部已处理态。
- 已检查 1366 响应式状态。
- 已检查控制台无错误。
- 已检查无横向溢出。
- 已检查按钮文字无裁切。
- 已检查 HTML 中没有旧的“创作路线”字样。
- 已检查 HTML 中没有暴露 debug、trace、backendReady、worldCanvas 等调试字段。
