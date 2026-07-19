# 10 角色主轴 / 03 角色草案审阅 V1

## 设计状态

- 状态：已采纳，并已完成 2026-07-04 全量审查。
- 页面定位：生成完成后的草案审阅页，用于判断角色草案是否成立。
- 设计原则：用户先审阅，再决定修订、处理缺口或确认写入；确认前不写入正式角色事实。

## 文件索引

- 草案审阅 HTML：`visual-drafts/character-spine-draft-review-v1.html`
- 默认档案页：`visual-drafts/character-spine-draft-review-v1.png`
- 关系页：`visual-drafts/character-spine-draft-review-v1-relations.png`
- 关系选中态：`visual-drafts/character-spine-draft-review-v1-relation-selected.png`
- 审查页：`visual-drafts/character-spine-draft-review-v1-checks.png`
- 修订面板：`visual-drafts/character-spine-draft-review-v1-revision.png`
- 确认态：`visual-drafts/character-spine-draft-review-v1-confirmed.png`
- 1366 响应式检查：`visual-drafts/character-spine-draft-review-v1-responsive-1366x768.png`
- 背景图：`visual-drafts/assets/character-spine-background-v1.png`

## 页面结构

1. 顶部导航区
   - 返回生成。
   - 面包屑：主页 / 当前项目 / 角色主轴。
   - 状态胶囊：草案待审阅。

2. 顶部阶段条
   - 生成入口。
   - 生成草案。
   - 审阅确认。
   - 角色底座。
   - 当前高亮：审阅确认。

3. 草案来源切换
   - A 级主轴草案。
   - B/C/D 角色草案。
   - 视觉稿默认展示 B 级角色草案，正式接入时根据当前草案来源自动选中。

4. 草案档案
   - 角色名称。
   - 等级徽标。
   - 角色摘要。
   - 身份、气质、目标、秘密。

5. 审阅面板
   - 档案：故事作用、当前状态、性格底线、记忆摘要。
   - 关系：关系草案、关系强度、关系说明、关系图。
   - 审查：结构可用、关系确认、缺口处理、阻塞问题。

6. 操作区
   - 修订草案。
   - 处理缺口。
   - 确认草案。

7. 右侧摘要
   - 审查摘要。
   - 写入边界。
   - 确认说明。

## 交互说明

- 审阅内容切换：
  - 点击“档案 / 关系 / 审查”切换主审阅面板。
  - 切换只影响当前页面展示，不触发后端请求。

- 关系选择：
  - 点击关系卡片后更新关系说明。
  - 用于让用户快速判断某条关系是否需要修改或确认。

- 草案来源切换：
  - 用于表达 A 级草案和 B/C/D 草案的接入差异。
  - 正式产品中如果当前只有一种草案来源，可不展示手动切换，只展示当前来源标签。

- 修订草案：
  - 展开修订说明输入区。
  - A 级草案可直接提交修订。
  - B/C/D 草案当前后端没有单独修订接口，应引导用户返回入口调整构想，或清除当前草案后重新生成。

- 处理缺口：
  - 进入 04 缺口与冲突处理页。
  - 如果存在阻塞问题，确认按钮应禁用，并优先引导处理缺口。

- 确认草案：
  - 没有阻塞问题时可确认。
  - 点击后进入待写入状态。

## 当前前端接口映射

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

- 修订：

```ts
POST /api/characters/revise
body: {
  revision_prompt: string;
}
```

- 确认：

```ts
POST /api/characters/confirm
body: {
  user_input?: string;
}
```

- 接入规则：
  - `character` 映射到草案档案与档案审阅面板。
  - `relationship_drafts` 映射到关系面板。
  - `validation_report` 映射到审查摘要和审查面板。
  - `blocking_issues.length > 0` 时禁用确认草案。

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

- 确认：

```ts
POST /api/roles/generated-draft/confirm
body: {
  user_input: string;
}
```

- 清除当前草案：

```ts
DELETE /api/roles/generated-draft
```

- 接入规则：
  - `role` 映射到草案档案与档案审阅面板。
  - 当前 B/C/D 草案返回结构没有 `relationship_drafts`，关系页应展示模型生成的关系候选、复杂度提示或空态，不应假设一定有关系草案数组。
  - 当前 B/C/D 草案没有独立修订接口；修订行为应回到入口重新生成，或等待后端新增修订接口后再接入。
  - `validation_report.blocking_issues.length > 0` 时禁用确认草案。

## Character 展示映射

- 名称：`name`
- 等级：`tier`
- 角色功能：`role` 或档案中的故事作用。
- 档案摘要：`profile.description`
- 身份：`profile.identity`
- 故事作用：`profile.story_function`
- 背景：`profile.background_summary`
- 外观：`profile.appearance_summary`
- 特质：`profile.traits`
- 目标：`profile.goals`
- 恐惧：`profile.fears`
- 秘密：`profile.secrets`
- 当前状态：`current_state`
- 角色弧线：`arc_state`
- 记忆摘要：`memory_summary`

正式 UI 展示时应使用中文标签，不直接显示上述字段名。

## 校验与按钮状态

- 通过：展示可读、可确认。
- 警告：展示为黄色提示，不一定禁用确认。
- 需要用户确认：展示为待确认，并引导用户进入 04 或在确认说明中补充。
- 阻塞问题：展示为高优先级问题，确认按钮禁用。
- 草案已确认：确认按钮禁用，并切换到已写入状态。

## 检查记录

- 已检查默认档案页。
- 已检查关系页与关系选中态。
- 已检查审查页。
- 已检查修订面板。
- 已检查确认态。
- 已检查 1366 响应式状态。
- 已检查控制台无错误。
- 已检查无横向溢出。
- 已检查按钮文字无裁切。
- 已检查页面中没有旧的“创作路线”字样。
