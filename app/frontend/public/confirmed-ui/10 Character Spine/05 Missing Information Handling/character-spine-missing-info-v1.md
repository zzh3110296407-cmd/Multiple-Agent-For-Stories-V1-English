# 10 角色主轴 / 05 缺失信息处理 V1

## 设计状态

- 状态：已采纳，并已完成 2026-07-04 全量审查。
- 页面定位：角色草案审阅后，用于补齐草案中仍需要用户明确的关键事实。
- 设计原则：本页只整理用户补充说明，不生成章节正文，不直接写入正式角色底座；正式写入仍发生在草案确认动作之后。

## 文件索引

- 交互 HTML：`visual-drafts/character-spine-missing-info-v1.html`
- 默认待补态：`visual-drafts/character-spine-missing-info-v1.png`
- 可留白项选中态：`visual-drafts/character-spine-missing-info-v1-optional.png`
- 单项已处理态：`visual-drafts/character-spine-missing-info-v1-one-complete.png`
- 全部已补齐态：`visual-drafts/character-spine-missing-info-v1-all-complete.png`
- 1366 响应式检查：`visual-drafts/character-spine-missing-info-v1-responsive-1366x768.png`
- 背景图：`visual-drafts/assets/character-spine-background-v1.png`

## 页面结构

1. 顶部导航区
   - 返回审阅。
   - 面包屑：主页 / 当前项目 / 角色主轴。
   - 状态胶囊：仍有缺失信息，全部处理完成后变为可返回确认。

2. 顶部阶段条
   - 生成入口。
   - 生成草案。
   - 审阅确认。
   - 角色底座。
   - 当前高亮：审阅确认。

3. 主处理面板
   - 标题：把角色成立前的空白补齐。
   - 进度章：补写中 / 已补齐。
   - 左侧待补信息队列：展示必填信息、建议补充、可留白项。
   - 右侧详情区：展示缺失内容、影响范围、补写方式、候选补充和补充说明输入框。

4. 页面底部结果条
   - 当前角色。
   - 补充状态。
   - 下一步提示。

5. 右侧摘要区
   - 信息摘要：必填信息、建议补充、可留白项、完成度。
   - 写入边界：不生成正文、不改世界事实、作为确认说明。
   - 操作：返回审阅、带回草案确认。

## 交互说明

- 待补信息队列：
  - 单击某个缺失项后，右侧详情区切换到对应内容。
  - 已处理事项保留在队列中，用弱化状态和勾选标记表示已完成。

- 补写方式：
  - 采用候选：用户选择系统整理出的候选补充，并可继续微调说明。
  - 自由补写：用户直接写自己的设定。
  - 只作说明：用于必填或建议项，仅把用户说明带回草案确认。
  - 暂时留白：只用于可留白项，把该项作为后续伏笔处理。

- 候选补充：
  - 单击候选卡片后，该候选内容写入补充说明输入框。
  - 候选内容只是前端展示与用户选择，不代表已经写入正式角色事实。

- 补齐当前项：
  - 当前项从待处理变为已处理。
  - 自动切换到下一个未处理项。
  - 全部处理完成后，顶部状态变为可返回确认，进度为 100%，带回草案确认按钮解锁。

- 返回审阅：
  - 返回 03 草案审阅页，不提交最终确认。
  - 如果已有本地补充内容，正式实现时应保存在前端临时状态中，避免误丢。

- 带回草案确认：
  - 仅在全部缺失项处理完成后可用。
  - 返回 03 草案审阅页，并把补充内容合并到确认说明区。

## 当前前端接口映射

05 缺失信息处理页不是独立后端流程页，它是角色草案审阅和确认之间的 UI 处理层。

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
  - `validation_report.user_confirmation_needed`：需要用户补齐或明确选择的缺失信息。
  - `validation_report.blocking_issues`：未处理前禁用确认的问题。
  - `validation_report.warnings`：建议补充但不一定阻塞确认的问题。
  - `character` 档案中为空或过短的关键展示字段：身份、故事作用、背景、目标、恐惧、秘密、记忆摘要等。

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
  - 如果用户补充只是明确事实、保留未知或确认说明，结果合并为 `user_input`，带回草案确认。
  - 如果用户补充要求重写角色结构、改变能力规则或重做关系，应转入后续修订草案流程，并组合成 `revision_prompt`。
  - 存在未处理阻塞项时，确认按钮必须禁用。

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
  - 如果用户补充内容需要重做角色，应返回 01 角色主轴入口重新生成，或等待后端新增修订接口后再接入。

- 接入规则：
  - 本页缺失项优先来自 `validation_report.user_confirmation_needed`、`validation_report.blocking_issues`、`validation_report.warnings`。
  - 也可根据 `role` 中为空或明显不足的字段生成前端待补项。
  - 用户补充结果合并为 `user_input` 后进入确认。
  - 不要把后端字段名展示给用户；正式 UI 使用“必填信息、建议补充、可留白项”等中文标签。

## 前端状态建议

```ts
type MissingInfoItem = {
  itemId: string;
  sourceType: "confirmation" | "blocking" | "warning" | "profile_gap";
  severity: "required" | "suggested" | "optional";
  title: string;
  detail: string;
  impact?: string;
  candidates?: Array<{
    title: string;
    text: string;
  }>;
};

type MissingInfoAnswer = {
  itemId: string;
  mode: "candidate" | "free" | "note" | "unknown";
  selectedCandidateTitle?: string;
  userText: string;
  status: "pending" | "completed";
};
```

- `itemId`：前端可用来源类型加索引生成，不要求后端目前提供独立 ID。
- `sourceType`：用于追踪来源是确认问题、阻塞问题、警告，还是角色档案缺口。
- `severity`：控制是否允许留白，以及确认按钮是否必须等待该项完成。
- `candidates`：前端可由模型返回内容、校验文案或本地转换策略生成。
- `userText`：最终合并到确认或修订参数中。

## 数据展示约束

- 正式 UI 不直接展示后端字段名、接口路径、debug、trace 或模型内部状态。
- 正式 UI 不展示旧版右侧创作路线。
- 输入区域使用完整边框，不使用横线式输入。
- 本页不能承诺已经写入正式角色事实，只能表达“补充说明已形成”。
- 缺失信息处理完后，仍需回到草案确认页完成最终确认。

## 检查记录

- 已检查默认待补态。
- 已检查可留白项选中态。
- 已检查单项已处理态。
- 已检查全部已补齐态。
- 已检查 1366 响应式状态。
- 已检查控制台无错误。
- 已检查无横向溢出。
- 已检查按钮文字无裁切。
- 已检查快速连续处理不会残留转场透明态。
- 已检查 HTML 中没有旧的“创作路线”字样。
- 已检查 HTML 中没有暴露 debug、trace、backendReady、worldCanvas 等调试字段。
