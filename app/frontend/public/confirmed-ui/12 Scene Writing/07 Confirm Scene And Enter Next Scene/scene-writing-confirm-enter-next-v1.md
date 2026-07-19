# 12 场景写作 / 07 确认场景与进入下一场景 V1

## 页面定位

该页位于“连续性与记忆写入”之后，是场景写作流程的收束页。用户在这里正式确认当前场景，并选择确认完成后的落点：生成下一幕、回项目总览、留在当前场景，或在章节末尾准备下一章。

该页将“正式确认当前幕”和“进入下一场景”拆成两个明确动作，避免用户点击下一步时隐式提交当前场景。

## 核心 UI

- 顶部：返回记忆写入、面包屑、模型连接状态。
- 页面标题：确认场景。
- 摘要条：当前场景、场景状态、记忆状态、下一步。
- 主面板左侧：最终确认清单，包括正文草案、质量结果、连续性、记忆写入。
- 主面板中部：当前场景锁定摘要，包括锁定摘要、下一场景继承、章节进度。
- 右侧：确认后的落点选择，包括生成下一幕、回项目总览、留在当前场景、准备下一章。
- 底部动作：临时确认、正式确认当前幕、进入下一场景。
- 右下：场景确认说明输入框，使用完整边框，不使用横线输入。

## 当前交互

- 点击最终确认清单卡片，会切换左侧说明。
- `锁定摘要 / 下一场景继承 / 章节进度` 可切换主视图。
- 点击右侧落点卡片，会切换下一步说明，并更新摘要条中的下一步。
- 未正式确认时点击“进入下一场景”，页面提示先正式确认当前幕。
- 点击“临时确认”会将场景状态变为临时确认，但不解锁进入下一场景。
- 点击“正式确认当前幕”会将场景状态变为正式确认，锁定标识改为已锁定。
- 正式确认后点击“进入下一场景”，根据右侧所选落点进入下一步状态。

## Phase 8.5 前端接口映射

该页后续接入时主要对应以下接口和动作：

- `GET /api/scenes/{sceneId}/gate-readiness`
  - 前端封装：`getSceneGateReadiness(sceneId)`。
  - 用于确认场景是否满足正式确认条件。
- `POST /api/scenes/{sceneId}/commit`
  - 前端封装：`commitScene(sceneId, commitType, userInput, revisionId, acceptedABCDRuntimeIssueIds)`。
  - 对应“正式确认当前幕”。
  - body: `{ commit_type, user_input, revision_id, accepted_abcd_runtime_issue_ids }`。
  - 推荐 `commit_type: "confirmed"`。
- `POST /api/scenes/{sceneId}/temporary-confirm`
  - 前端封装：`temporaryConfirmScene(sceneId, userInput)`。
  - 对应“临时确认”。
  - body: `{ user_input }`。
- `POST /api/scenes/generate-next`
  - 前端封装：`generateNextScene(chapterId, forceRefreshPacks, includeProvisional)`。
  - 对应“进入下一场景”中选择“生成下一幕”。
  - body: `{ chapter_id, force_refresh_packs, include_provisional }`。
- `GET /api/story-progress/current`
  - 前端封装：`getStoryProgressCurrent()`。
  - 用于判断当前章是否已完成、是否可生成下一幕。
- `POST /api/story-progress/prepare-next-chapter`
  - 前端封装：`prepareNextChapter(payload)`。
  - 仅在当前章已完成时对应“准备下一章”。
  - body: `{ latest_user_intent_summary, story_goal, scene_count_proposal, acknowledge_provisional_archive, force_rebuild }`。
- `POST /api/story-progress/confirm-next-chapter`
  - 前端封装：`confirmNextChapter(payload)`。
  - 用于下一章准备完成后的确认，不在本页直接触发。

## 建议数据类型

```ts
type SceneConfirmAndNextState = {
  project_id: string;
  chapter_id: string;
  scene_id: string;
  revision_id?: string | null;
  scene_index: number;
  total_scene_count: number;
  scene_status: "draft" | "revised" | "temporary_confirmed" | "confirmed" | "committed";
  prose_ready: boolean;
  memory_write_status: "not_written" | "written" | "failed";
  gate_readiness: {
    safe_to_confirm: boolean;
    requires_user_action: boolean;
    reason_codes: string[];
  };
  final_checks: Array<{
    check_id: "prose" | "quality" | "continuity" | "memory";
    status: "passed" | "warning" | "blocking" | "not_run";
    summary: string;
  }>;
  locked_scene_summary?: {
    prose_summary: string;
    memory_package_id?: string | null;
    open_clues: Array<{
      clue_id: string;
      summary: string;
      required_followup: boolean;
    }>;
    next_scene_inheritance: Array<{
      item_type: "event" | "character_state" | "relationship" | "object_clue" | "chapter_goal";
      summary: string;
    }>;
  };
  next_route: "generate_next_scene" | "project_overview" | "current_scene" | "prepare_next_chapter";
  next_route_enabled: boolean;
  current_chapter_final_complete: boolean;
  user_input: string;
};
```

## 接入规则

- “进入下一场景”必须先确认 `scene_status` 已经是 `confirmed` 或 `committed`。
- 如果 `gate_readiness.safe_to_confirm !== true`，应禁用或阻止正式确认，并引导用户回到问题处理或记忆写入流程。
- 如果当前章未完成，“准备下一章”只能作为灰度/说明选项，不应作为主路径调用接口。
- 正式确认当前幕不应自动调用 `generate-next`。
- `generate-next` 调用前应刷新或确认记忆写入结果，保证下一场景能读取最新上下文。
- 临时确认不能替代正式确认；临时确认后仍需正式确认才能进入下一场景主路径。

## 视觉决策

- 继续使用 `assets/scene-writing-background-v1.png`。
- 不显示创作路线。
- 不显示调试字段和后端原始 JSON。
- 页面视觉比 06 更收束，强调“锁定”和“去向选择”。
- 右侧落点选择保留“准备下一章”，但标注为章节末尾路径，避免当前章未完成时误用。
- 移动端底部动作按钮满宽，避免确认文案被压缩。

## 文件

- 动态稿：`visual-drafts/scene-writing-confirm-enter-next-v1.html`
- 桌面截图：`visual-drafts/scene-writing-confirm-enter-next-v1.png`
- 移动端截图：`visual-drafts/scene-writing-confirm-enter-next-v1-mobile.png`
