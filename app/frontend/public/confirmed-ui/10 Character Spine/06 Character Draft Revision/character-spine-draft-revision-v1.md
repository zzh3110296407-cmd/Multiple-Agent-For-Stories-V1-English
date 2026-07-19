# 10 角色主轴 / 06 修订角色草案 V1

## 设计状态

- 状态：已采纳，并已完成 2026-07-04 全量审查。
- 页面定位：角色草案审阅后，当用户决定草案需要结构性调整时，用于整理修订要求。
- 设计原则：本页提交的是修订请求，会生成新的角色草案；不直接写入角色底座，也不直接确认当前草案。

## 文件索引

- 交互 HTML：`visual-drafts/character-spine-draft-revision-v1.html`
- 默认待整理态：`visual-drafts/character-spine-draft-revision-v1.png`
- 关系焦点选中态：`visual-drafts/character-spine-draft-revision-v1-relation-focus.png`
- 可提交态：`visual-drafts/character-spine-draft-revision-v1-ready.png`
- 提交后弹窗态：`visual-drafts/character-spine-draft-revision-v1-submitted.png`
- 1366 响应式检查：`visual-drafts/character-spine-draft-revision-v1-responsive-1366x768.png`
- 背景图：`visual-drafts/assets/character-spine-background-v1.png`

## 页面结构

1. 顶部导航区
   - 返回审阅。
   - 面包屑：主页 / 当前项目 / 角色主轴。
   - 状态胶囊：等待修订要求、可提交修订、修订已提交。

2. 顶部阶段条
   - 生成入口。
   - 生成草案。
   - 审阅确认。
   - 角色底座。
   - 当前高亮：审阅确认。

3. 主修订面板
   - 标题：先限定改动，再提交修订。
   - 状态章：待整理 / 已整理 / 修订中。
   - 左侧修订焦点：能力边界、关系来源、行动底线、身份气质、故事作用。
   - 右侧修订详情：当前问题、修订目标、改动强度、建议修订方向、保护内容、修订要求输入框。

4. 页面底部结果条
   - 当前角色。
   - 修订状态。
   - 下一步提示。

5. 右侧摘要区
   - 修订摘要：已选焦点、改动强度、保护内容、提交状态。
   - 已整理要求：展示会被合并进修订请求的内容。
   - 提交边界：不写入底座、生成新草案、B/C/D 需回入口。
   - 操作：返回审阅、提交修订。

6. 提交后弹窗
   - 文案说明新的角色草案正在生成。
   - 正式接入后应跳转到 02 生成中状态，而不是留在当前页。

## 交互说明

- 修订焦点：
  - 单击左侧焦点后，中间详情区切换到对应问题。
  - 已加入修订要求的焦点保留勾选状态。

- 改动强度：
  - 轻微调整：只改语义、限制或表达。
  - 局部重写：允许改写一个角色模块。
  - 重做方向：保留保护项，其余允许大幅重构。

- 建议修订方向：
  - 单击候选后会把候选内容写入修订要求输入框。
  - 用户仍可继续编辑。

- 保护内容：
  - 默认保护角色等级、核心气质、已确认关系、世界事实。
  - 用户可手动取消或恢复保护。
  - 保护内容应拼入修订请求，避免模型把已确认内容一起改掉。

- 加入修订要求：
  - 把当前焦点、改动强度、保护内容和输入框文本加入右侧已整理要求。
  - 至少加入一项后，提交修订按钮解锁。

- 提交修订：
  - 视觉稿中展示提交弹窗。
  - 正式产品中应触发修订接口，然后进入 02 生成中状态。
  - 修订完成后进入 03 草案审阅，用户重新审阅后才能确认写入。

## 当前前端接口映射

06 修订角色草案页不是确认页，它是 `revision_prompt` 构建页。

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

- 修订接口：

```ts
POST /api/characters/revise
body: {
  revision_prompt: string;
}
```

- 接入规则：
  - 页面提交时，把已整理要求合并为 `revision_prompt`。
  - `revision_prompt` 至少应包含：修订焦点、改动强度、用户要求、保护内容。
  - 当前后端使用当前草案上下文进行修订，前端不应私自假设接口支持传 `draft_id`，除非后端后续扩展。
  - 提交后设置角色动作状态为修订中，并复用 02 生成中的等待 UI。
  - 修订返回新 `draft` 后进入 03 草案审阅。

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

- 当前确认接口：

```ts
POST /api/roles/generated-draft/confirm
body: {
  user_input: string;
}
```

- 当前限制：
  - B/C/D 草案当前没有独立修订接口。
  - 如果用户要修订 B/C/D 草案，正式 UI 应提示返回 01 角色主轴入口调整构想后重新生成，或等待后端新增 B/C/D 修订接口。

- 接入规则：
  - 如果当前草案来源是 B/C/D，提交修订按钮不应直接调用 A 级修订接口。
  - 可把本页作为“重新生成要求整理页”，最终跳回入口并预填用户修订要求。
  - 当后端新增 B/C/D 修订接口后，再把本页的修订请求接入对应接口。

## 前端状态建议

```ts
type CharacterRevisionFocus = {
  focusId: string;
  category: "ability" | "relationship" | "boundary" | "identity" | "story_function";
  title: string;
  currentIssue: string;
  revisionGoal: string;
  suggestions: Array<{
    title: string;
    text: string;
  }>;
};

type CharacterRevisionDraft = {
  sourceKind: "main_cast" | "generated_role";
  sourceDraftId?: string;
  items: Array<{
    focusId: string;
    changeStrength: "light" | "partial" | "strong";
    userText: string;
  }>;
  protectedItems: string[];
};
```

- `sourceKind`：区分 A 级主轴草案和 B/C/D 角色草案。
- `sourceDraftId`：可用于前端本地追踪；当前 A 级修订接口不要求传入。
- `items`：用户实际加入的修订要求。
- `protectedItems`：拼入修订请求的保护内容。

## revision_prompt 组合建议

正式接入时可以把用户整理内容组合为中文 prompt：

```text
请修订当前角色草案。
修订焦点：
1. {焦点标题} / 改动强度：{轻微调整|局部重写|重做方向}
   用户要求：{用户输入}

请保护以下内容不被改写：{保护内容}
不要写入角色底座；只返回新的角色草案供用户重新审阅。
```

## 数据展示约束

- 正式 UI 不直接展示后端字段名、接口路径、debug、trace 或模型内部状态。
- 正式 UI 不展示旧版右侧创作路线。
- 输入区域使用完整边框，不使用横线式输入。
- 本页不能承诺已经完成写入，只能表达“修订请求已提交”或“新草案正在生成”。
- 修订完成后必须重新进入草案审阅，不可直接确认写入。

## 检查记录

- 已检查默认待整理态。
- 已检查关系焦点选中态。
- 已检查可提交态。
- 已检查提交后弹窗态。
- 已检查 1366 响应式状态。
- 已检查控制台无错误。
- 已检查无横向溢出。
- 已检查按钮文字无裁切。
- 已检查提交后状态能变为“修订中”。
- 已检查 HTML 中没有旧的“创作路线”字样。
- 已检查 HTML 中没有暴露 debug、trace、backendReady、worldCanvas 等调试字段。
