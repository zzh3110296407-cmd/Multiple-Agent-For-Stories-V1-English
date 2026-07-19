# 10 角色主轴 / 07 确认角色主轴 V1

## 设计状态

- 状态：已采纳，并已完成 2026-07-04 全量审查。
- 页面定位：角色草案经过审阅、补缺、冲突处理或修订后，最终确认写入角色底座。
- 设计原则：本页只执行确认写入，不生成新草案，不修订草案，不生成章节正文。

## 文件索引

- 交互 HTML：`visual-drafts/character-spine-confirmation-v1.html`
- 默认待确认态：`visual-drafts/character-spine-confirmation-v1.png`
- 关系清单态：`visual-drafts/character-spine-confirmation-v1-relations.png`
- 可写入态：`visual-drafts/character-spine-confirmation-v1-ready.png`
- 写入完成态：`visual-drafts/character-spine-confirmation-v1-confirmed.png`
- 1366 响应式检查：`visual-drafts/character-spine-confirmation-v1-responsive-1366x768.png`
- 背景图：`visual-drafts/assets/character-spine-background-v1.png`

## 页面结构

1. 顶部导航区
   - 返回审阅。
   - 面包屑：主页 / 当前项目 / 角色主轴。
   - 状态胶囊：待确认写入、可确认写入、已写入角色底座。

2. 顶部阶段条
   - 生成入口。
   - 生成草案。
   - 审阅确认。
   - 角色底座。
   - 当前高亮：角色底座。

3. 主确认面板
   - 标题：确认这些事实写入角色底座。
   - 状态章：待确认 / 可写入 / 已写入。
   - 左侧写入清单：角色档案、关系草稿、缺口与修订结果、确认写入范围。
   - 右侧确认详情：摘要、事实、边界、确认门槛、确认说明。

4. 页面底部结果条
   - 当前角色。
   - 写入状态。
   - 下一步提示。

5. 右侧摘要区
   - 确认摘要：档案审阅、关系审阅、边界确认、写入状态。
   - 写入边界：不生成正文、不改世界事实、写入角色底座、按草案来源分流。
   - 后续动作：返回审阅、确认写入。

6. 写入完成弹窗
   - 表示角色底座已经写入。
   - 正式接入后可跳转到角色底座、继续创建下一个角色或返回项目总览。

## 交互说明

- 写入清单：
  - 单击左侧清单项，右侧展示对应写入摘要、影响范围和具体事实。
  - 清单切换只影响展示，不触发后端请求。

- 详情切换：
  - 摘要：展示当前清单项的主要写入内容。
  - 事实：展示当前清单项下的具体事实。
  - 边界：统一展示本次确认动作的写入边界。

- 确认门槛：
  - 档案已审阅。
  - 关系已审阅。
  - 写入边界已确认。
  - 三项全部确认后，确认写入按钮才启用。

- 确认说明：
  - 用户可编辑。
  - 正式接入时作为 `user_input` 传给确认接口。

- 确认写入：
  - 视觉稿中展示写入完成弹窗。
  - 正式产品中应根据当前草案来源调用对应确认接口。
  - 写入成功后当前草案成为正式角色事实。

## 当前前端接口映射

07 确认角色主轴页是确认写入页，不是修订页。

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

- 确认接口：

```ts
POST /api/characters/confirm
body: {
  user_input?: string;
}
```

- 接入规则：
  - 页面主按钮调用 `onCharacterAction("confirm", { userInput })`。
  - `userInput` 来自确认说明输入框，也可以合并 04、05、06 页面带回的处理说明。
  - 如果 `validation_report.blocking_issues.length > 0`，确认写入按钮必须禁用。
  - 如果 `draft.status === "confirmed"`，确认写入按钮应禁用，并展示已写入状态。
  - 写入成功后进入角色底座展示或返回 03 草案审阅的已确认态。

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

- 接入规则：
  - 页面主按钮调用 `onRoleAction("confirm-generated-draft", { userInput })`。
  - 当前 B/C/D 草案没有独立修订接口；如用户需要修改，应回到 01 入口或 06 修订要求整理后回入口重新生成。
  - B/C/D 确认成功后，该角色进入正式角色列表。

### 完成主角团设置

当前前端还有独立动作：

```ts
POST /api/characters/finish-main-cast
body: {
  user_input: string;
}
```

- 此动作不等同于确认当前角色草案。
- 只有在至少一个 A 级角色确认后才可使用。
- 建议作为 07 写入成功后的后续动作或角色底座页中的全局动作，不放在确认当前草案的主按钮上。

## 前端状态建议

```ts
type CharacterConfirmationState = {
  sourceKind: "main_cast" | "generated_role";
  sourceDraftId?: string;
  reviewGates: {
    profileReviewed: boolean;
    relationshipsReviewed: boolean;
    writeBoundaryAccepted: boolean;
  };
  userInput: string;
};
```

- `sourceKind`：决定调用 A 级确认接口还是 B/C/D 确认接口。
- `sourceDraftId`：仅用于前端本地追踪；当前确认接口不要求传入。
- `reviewGates`：控制确认按钮是否启用。
- `userInput`：确认说明，传给后端确认接口。

## 数据展示约束

- 正式 UI 不直接展示后端字段名、接口路径、debug、trace 或模型内部状态。
- 正式 UI 不展示旧版右侧创作路线。
- 输入区域使用完整边框，不使用横线式输入。
- 本页不能承诺生成新内容，只能表达“确认写入角色底座”。
- 写入前必须完成确认门槛。

## 检查记录

- 已检查默认待确认态。
- 已检查关系清单态。
- 已检查可写入态。
- 已检查写入完成态。
- 已检查 1366 响应式状态。
- 已检查控制台无错误。
- 已检查无横向溢出。
- 已检查按钮文字无裁切。
- 已检查确认门槛完成后按钮解锁。
- 已检查确认后状态能变为“已写入角色底座”。
- 已检查 HTML 中没有旧的“创作路线”字样。
- 已检查 HTML 中没有暴露 debug、trace、backendReady、worldCanvas 等调试字段。
