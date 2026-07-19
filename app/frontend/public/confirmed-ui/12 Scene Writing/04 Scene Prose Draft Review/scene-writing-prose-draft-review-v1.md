# 12 场景写作 / 04 正文草案审阅 V1

## 页面定位

该页位于“正文生成中”之后。用户在这里阅读当前场景正文草案，查看梗概、抽取候选、质量检查、连续性状态、记忆候选和叙事债务，再决定要求修订、临时确认或进入确认流程。

该页是审阅与决策入口，不直接写入正式记忆，也不直接推进下一场景。用户选择确认方向后，应进入后续连续性 / 记忆写入 / 最终确认流程。

## 核心 UI

- 顶部：返回生成状态、面包屑、模型连接状态。
- 页面标题：正文草案审阅。
- 摘要条：当前场景、草案状态、质量、连续性。
- 主区域：正文阅读器、梗概视图、抽取候选视图、审阅意见视图。
- 主区域右栏：审阅焦点，展示当前需要用户理解的重点。
- 右侧：确认前状态，包含质量检查、连续性、记忆候选、叙事债务、后台门控。
- 底部动作：刷新检查、要求修订、临时确认、进入确认流程。
- 修订弹层：填写修订方向，提交后进入后续修订流程。

## 当前交互

- `正文 / 梗概 / 抽取候选 / 审阅意见` 可切换主阅读内容。
- 点击右侧检查项会切换下方详情说明。
- `刷新检查` 更新页面提示，真实接入时对应后台质量 / 门控刷新。
- `要求修订` 打开修订方向弹层；提交后标记为“待修订”。
- `临时确认` 只标记临时确认方向；真实接入时调用临时确认接口。
- `进入确认流程` 只标记确认方向；真实接入时应先进入连续性与记忆写入，再进入最终确认页。

## Phase 8.5 前端接口映射

该页后续接入时主要读取和触发以下接口：

- `GET /api/scenes/current`：读取当前场景正文、梗概、状态、`scene_id`、`prose_status`、`active_revision_id`。
- `GET /api/scenes/progress?chapter_id=...`：读取当前章场景进度和是否可继续生成下一场。
- `GET /api/scenes/{sceneId}/gate-readiness`：读取是否可以正式确认、是否需要用户处理。
- `GET /api/scenes/{sceneId}/writer-quality-surface?...`：读取面向作者的质量面板。
- `GET /api/quality-reports/current?scene_id=...`：读取完整质量报告。
- `POST /api/quality-check/scene/{sceneId}`：刷新场景质量检查。
- `GET /api/continuity/state?...`：读取连续性状态摘要。
- `POST /api/continuity/check/scene/{sceneId}?mode=manual`：运行连续性检查。
- `GET /api/continuity/issues?scene_id=...`：读取连续性问题列表。
- `POST /api/scenes/regenerate-first`：按用户修订方向重生成第一幕草案。
- `POST /api/scenes/{sceneId}/temporary-confirm`：临时确认当前场景。
- `POST /api/scenes/{sceneId}/commit`：最终确认页使用的正式提交接口，本页不应直接静默调用。
- `POST /api/memory-sync/scene/{sceneId}/plan-from-revision`：如果确认修订候选，后续生成记忆同步计划。

## 建议数据类型

```ts
type SceneProseDraftReviewState = {
  project_id: string;
  chapter_id: string;
  chapter_index: number;
  scene_id: string;
  scene_index: number;
  scene_count: number;
  title: string;
  status: "draft" | "revised" | "needs_review" | "continuity_recheck" | "temporary_confirmed" | "confirmed";
  prose_status: "generated" | "not_generated" | "needs_regeneration";
  content: {
    synopsis?: string;
    prose_text: string;
  };
  quality: {
    status: "passed" | "warning" | "blocking" | "not_run";
    warnings: string[];
    blocking_issues: string[];
    requires_user_confirmation: boolean;
  };
  continuity: {
    status: "passed" | "warning" | "blocking" | "not_run";
    open_issue_count: number;
    blocking_issue_count: number;
  };
  memory_extraction: {
    event_summary: Array<{ summary: string; participants?: string[]; status?: string }>;
    proposed_state_changes: Array<{ summary: string; target_id?: string; requires_user_confirmation?: boolean }>;
    relationship_changes: Array<{ summary: string; relationship_id?: string; requires_user_confirmation?: boolean }>;
    memory_records: Array<{ memory_id?: string; summary: string; object_type?: string; object_id?: string; tags?: string[] }>;
  };
  narrative_debt_summary?: {
    active_count: number;
    deadline_warning_count: number;
    intentionally_open_count: number;
  };
  gate_readiness: {
    safe_to_confirm: boolean;
    requires_user_action: boolean;
    reason_codes: string[];
  };
  active_revision_id?: string | null;
};
```

## 视觉决策

- 继续使用 `assets/scene-writing-background-v1.png`。
- 页面主视觉是正文阅读器，避免把用户放进调试表格。
- 检查项只保留用户决策需要理解的层级：质量、连续性、记忆、叙事债务、后台门控。
- 输入区使用完整边框，不使用横线输入。
- 不展示创作路线。
- “进入确认流程”按钮出现在右下角，页面文案明确正式提交和正式写入动作会在后续确认流程中再次呈现。

## 文件

- 动态稿：`visual-drafts/scene-writing-prose-draft-review-v1.html`
- 桌面截图：`visual-drafts/scene-writing-prose-draft-review-v1.png`
- 移动端截图：`visual-drafts/scene-writing-prose-draft-review-v1-mobile.png`
