# 10 角色主轴 / 01 角色主轴入口 V1

## 设计状态

- 状态：已采纳，并已完成 2026-07-04 全量审查。
- 页面定位：角色主轴的第一步，用于让用户自由描述想创建的角色，并选择目标等级进入生成流程。
- 设计原则：不显示右侧创作路线；不限制用户必须填写身份、气质或故事作用；这些内容应由模型在生成后提取并进入草案审阅。

## 文件索引

- 入口 HTML：`visual-drafts/character-spine-entry-v1.html`
- 默认预览：`visual-drafts/character-spine-entry-v1.png`
- 等级下拉状态：`visual-drafts/character-spine-entry-v1-tier-menu.png`
- 点击生成后的状态：`visual-drafts/character-spine-entry-v1-submitted.png`
- 1366 响应式检查：`visual-drafts/character-spine-entry-v1-responsive-1366x768.png`
- 背景图：`visual-drafts/assets/character-spine-background-v1.png`

## 页面结构

1. 顶部导航区
   - 返回工作台。
   - 面包屑：主页 / 工作台 / 角色主轴。
   - 当前页标题：角色主轴。
   - 页面说明：角色事实、关系草案、叙事承重点会在生成后进入审阅。

2. 顶部阶段条
   - 生成入口。
   - 生成草案。
   - 审阅确认。
   - 角色底座。
   - 这是横向阶段提示，不是创作路线；后续页面可以保持同一位置。

3. 输入主面板
   - 主问题：先写你想要怎样的角色。
   - 用户输入：角色构想。
   - 等级选择：A / B / C / D，下拉选择。
   - 操作：清空、生成角色主轴草案。

4. 生成后预览区
   - 角色档案。
   - 叙事功能。
   - 关系草案。
   - 确认问题。
   - 这些只作为生成结果结构预告，不在入口页提前填写具体内容。

5. 右侧边界说明
   - 生成条件：世界画布需要已确认。
   - 写入边界：生成前不写入正式角色事实。
   - 下一步：进入生成中状态。

## 交互说明

- 等级下拉：
  - 点击等级按钮展开 A/B/C/D。
  - 点击选项后更新当前等级。
  - 点击外部或按 Escape 关闭。
  - A 级表示主轴角色；B/C/D 表示不同叙事权重的角色，不在入口页写死数量限制。

- 输入状态：
  - 输入框显示字数。
  - 为空时生成按钮禁用。
  - 清空按钮会清除输入并恢复默认提示。

- 生成按钮：
  - 点击后进入轻量提交状态，视觉稿里显示“进入生成中”和提示浮层。
  - 真实接入时应切换到 10 / 02 生成中页面。

- 阶段按钮：
  - 当前视觉稿中做轻量提示，不进行真实跳转。
  - 后续接入时可绑定工作台内的页面状态。

## 当前前端接口映射

当前 Phase 8.5 前端中，角色入口已经存在 A/B/C/D 等级选择，但 A 级和 B/C/D 级使用不同动作。

### A 级角色

- 前端动作：`onCharacterAction("generate", { userPrompt, roleHint, storyFunctionHint })`
- API 封装：`generateCharacter(userPrompt, roleHint, storyFunctionHint)`
- 请求：

```ts
POST /api/characters/generate
body: {
  user_prompt: string;
  role_hint?: string;
  story_function_hint?: string;
}
```

- 返回：

```ts
type CharacterWorkflowResponse = {
  draft?: CurrentCharacterDraft | null;
  characters: Character[];
  relationships: Relationship[];
  validation?: CharacterValidationReport | null;
  decision?: Decision | null;
  main_cast_finished: boolean;
};
```

- 入口页接入规则：
  - 用户输入映射到 `user_prompt`。
  - 等级为 A 时，`role_hint` 可传 `"main_cast"` 或沿用当前前端默认逻辑。
  - `story_function_hint` 在新 UI 中不作为必填输入；如果后续保留隐藏高级字段，需要默认空字符串。

### B/C/D 级角色

- 前端动作：`onRoleAction("generate-role-draft", { userPrompt, targetTier, roleHint, storyFunctionHint })`
- API 封装：`generateRoleDraft(payload)`
- 请求：

```ts
POST /api/roles/generate
body: {
  user_prompt: string;
  target_tier: "B" | "C" | "D";
  role_hint?: string;
  story_function_hint?: string;
}
```

- 返回：

```ts
type RoleGenerationResponse = {
  draft?: CurrentRoleDraft | null;
  roles: Character[];
  validation?: CharacterValidationReport | null;
  decision?: Decision | null;
  cleared: boolean;
};
```

- 入口页接入规则：
  - 等级为 B/C/D 时必须走 Role Generation，不应走 `/api/characters/generate`。
  - `targetTier` 需要转换为后端字段 `target_tier`。
  - 后续草案确认应进入 `/api/roles/generated-draft/confirm`。

## 数据展示约束

- 入口页不展示原始后端字段名，例如 `profile`、`current_state`、`relationship_drafts`。
- 入口页不展示校验报告正文，校验、警告、阻塞问题留到 03/04 审阅与问题处理页。
- 世界画布未确认时，生成按钮真实接入应禁用，并显示中文原因：请先确认世界画布，再创建角色。
- A 级数量限制已在 Phase 8.5 中解除，UI 不应出现“仅支持 3 个 A 级角色”等旧文案。

## 视觉规则

- 背景使用角色主轴专属背景，不复用旧角色创建背景。
- 面板采用羊皮纸、旧书页、淡陶土和灰绿莫兰迪色。
- 主输入区保持宽松，给用户自由表达空间。
- 操作按钮集中在输入面板底部，主按钮颜色更深，次按钮保持低对比。
- 所有输入框无横线式装饰，保持完整柔和边框。

## 响应式与可访问性

- 1440 视口：主面板与右侧边界并列。
- 1366 视口：布局无横向溢出，右侧说明仍可见。
- 小屏：主面板、预览、边界说明纵向排列。
- 交互元素使用 button / textarea，不使用不可聚焦的 div 替代按钮。
- 等级下拉需要支持键盘关闭，后续正式实现建议补充方向键选择。

## 后续页面衔接

- 02 生成中：展示角色档案、叙事功能、关系草案、校验报告正在生成。
- 03 草案审阅：展示 `draft.character`、关系草案、校验 warnings/blocking issues。
- 04 关系与冲突处理：处理关系来源、冲突、警告与确认问题。
- 05 缺失信息处理：补齐 `validation.blocking_issues`、`validation.warnings`、`user_confirmation_needed` 中需要用户判断的缺口。
- 06 修订角色草案：提交 `revision_prompt`；B/C/D 当前无独立修订接口时回到入口重新生成。
- 07 确认角色主轴：A 级走 `/api/characters/confirm`，B/C/D 走 `/api/roles/generated-draft/confirm`；`/api/characters/finish-main-cast` 作为确认后的后续全局动作，不作为确认当前草案的主按钮。

## 检查记录

- 已检查 HTML 无横向溢出。
- 已检查默认态、等级下拉态、提交态、1366 响应式态。
- 已检查页面中没有旧的“创作路线”字样。
- 已检查页面中没有暴露英文原始字段名。
