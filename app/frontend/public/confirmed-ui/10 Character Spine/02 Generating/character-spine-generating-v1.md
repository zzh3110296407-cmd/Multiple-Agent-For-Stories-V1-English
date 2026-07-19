# 10 角色主轴 / 02 生成中 V1

## 设计状态

- 状态：已采纳，并已完成 2026-07-04 全量审查。
- 页面定位：用户在 01 入口页点击生成后进入的等待状态。
- 设计原则：不展示调试信息；不新增右侧创作路线；不让用户在生成中填写额外字段。

## 文件索引

- 生成中 HTML：`visual-drafts/character-spine-generating-v1.html`
- 生成中预览：`visual-drafts/character-spine-generating-v1.png`
- 准备审阅状态：`visual-drafts/character-spine-generating-v1-ready.png`
- 1366 响应式检查：`visual-drafts/character-spine-generating-v1-responsive-1366x768.png`
- 背景图：`visual-drafts/assets/character-spine-background-v1.png`

## 页面结构

1. 顶部导航区
   - 返回入口。
   - 面包屑：主页 / 当前项目 / 角色主轴。
   - 状态胶囊：草案生成中，完成后变为准备审阅。

2. 顶部阶段条
   - 生成入口。
   - 生成草案。
   - 审阅确认。
   - 角色底座。
   - 当前高亮：生成草案。

3. 主生成面板
   - 当前标题：角色正在从构想里浮现。
   - 左侧保留已提交的角色构想摘要。
   - 右侧展示角色核心、秘密、关系、世界事实之间的生成关系。
   - 生成项：档案轮廓、关系草案、叙事承重点、确认问题。

4. 结果预告
   - 角色档案。
   - 关系草案。
   - 叙事功能。
   - 审阅问题。
   - 使用骨架条表现内容即将形成，不提前展示虚构结果。

5. 右侧状态区
   - 生成状态。
   - 写入边界。
   - 下一步。

## 交互说明

- 页面进入时：
  - 顶部状态显示草案生成中。
  - 整体进度从中段开始推进，用于表现请求已提交。
  - 主按钮显示等待草案并禁用。

- 生成完成后：
  - 顶部状态切换为准备审阅。
  - 状态章切换为已成形。
  - 右侧整体进度停在 100%。
  - 主按钮切换为进入草案审阅。

- 返回修改：
  - 视觉稿中作为轻量交互存在。
  - 正式接入时如果后端请求已发出，不应承诺取消请求；可作为返回入口查看构想，或在产品层加确认提示。

## 当前前端接口映射

02 生成中页不对应独立后端接口，它是 01 入口页发出生成请求后的中间 UI 状态。

### A 级角色生成中

- 触发来源：01 入口页选择 A 级并点击生成。
- 前端动作：`onCharacterAction("generate", { userPrompt, roleHint, storyFunctionHint })`
- 请求：

```ts
POST /api/characters/generate
body: {
  user_prompt: string;
  role_hint?: string;
  story_function_hint?: string;
}
```

- 生成中判定：

```ts
characterAction === "generate"
```

- 请求完成后：
  - 有 `draft`：进入 03 草案审阅。
  - 有 `validation.blocking_issues`：03 显示审阅结果，必要时进入 04 缺口与冲突处理。
  - 请求失败：应显示错误状态或返回入口保留用户构想。

### B/C/D 级角色生成中

- 触发来源：01 入口页选择 B/C/D 并点击生成。
- 前端动作：`onRoleAction("generate-role-draft", { userPrompt, targetTier, roleHint, storyFunctionHint })`
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

- 生成中判定：

```ts
roleAction === "generate-role-draft"
```

- 请求完成后：
  - 有 `draft`：进入 03 草案审阅。
  - 有阻塞问题：进入 04 缺口与冲突处理。
  - 请求失败：应保留入口页构想并展示中文错误。

## 数据展示约束

- 不展示原始后端字段名。
- 不展示模型调用、trace、debug 状态或接口路径。
- 不展示“仅支持 3 个 A 级角色”等旧限制。
- 生成中只显示结构化方向，不提前给出不可确认的正式角色事实。

## 接入建议

- 此页应由生成请求的 pending 状态驱动。
- 不需要额外轮询接口，除非后续后端改为异步任务。
- 如果请求时间很短，可以保证此页至少停留 700 到 1000ms，让转场更丝滑。
- 如果请求超过预期，应保持同一页面并显示较低干扰的等待状态，不要跳回入口页。
- 如果未来支持取消生成，应增加明确的取消接口后再把“取消”作为主交互。

## 检查记录

- 已检查 HTML 无横向溢出。
- 已检查 1440 默认生成中状态。
- 已检查 1440 准备审阅状态。
- 已检查 1366 响应式状态。
- 已检查控制台无错误。
- 已检查按钮文字无裁切。
- 已检查页面中没有旧的“创作路线”字样。
