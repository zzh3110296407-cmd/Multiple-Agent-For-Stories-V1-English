# 12 场景写作 / 06 连续性与记忆写入 V1

## 页面定位

该页位于“修订场景正文”之后，是场景正式进入后续流程前的确认层。它把 Phase 8.5 前端中分散的连续性检查、记忆计划生成、记忆计划确认、记忆写入动作收拢为一个用户可理解的流程。

该页不负责生成正文、不修改章节计划、不自动覆盖已确认事实。用户必须在本页确认后，记忆计划才可以写入。

## 核心 UI

- 顶部：返回修订正文、面包屑、模型连接状态。
- 页面标题：连续性与记忆写入。
- 摘要条：当前场景、连续性、记忆计划、写入状态。
- 主面板左侧：连续性复核，包括世界事实、角色状态、章节目标、开放线索。
- 主面板中部：记忆写入计划，包括计划摘要、记忆条目、后续依赖。
- 右侧：写入影响，包括当前状态、新记忆、后续依赖、确认理由、回滚边界。
- 底部动作：运行连续性检查、生成记忆计划、拒绝写入、确认并写入。
- 右下：写入确认说明输入框，使用完整边框，不使用横线输入。

## 当前交互

- 点击连续性复核卡片，会切换左侧说明。
- `计划摘要 / 记忆条目 / 后续依赖` 可切换主视图。
- 点击记忆条目卡片，会切换记忆详情。
- 点击右侧影响卡片，会切换影响说明。
- `运行连续性检查` 将连续性状态刷新为已通过。
- `生成记忆计划` 将记忆计划状态刷新为已生成。
- `拒绝写入` 将写入状态改为已拒绝，不污染正式记忆。
- `确认并写入` 将记忆计划改为已确认，写入状态改为已写入，并把写入进度显示为 100%。

## Phase 8.5 前端接口映射

该页后续接入时主要对应以下接口：

- `GET /api/scenes/{sceneId}/gate-readiness`
  - 用于读取当前场景是否允许确认。
  - 前端封装：`getSceneGateReadiness(sceneId)`。
- `POST /api/continuity/check/scene/{sceneId}?mode=manual`
  - 用于检查当前场景连续性。
  - 前端动作可对应：`onSceneAction("continuity-scene", { sceneId, targetType, targetId, revisionId, mode })`。
- `POST /api/continuity/check/scene/{sceneId}/revision/{revisionId}?mode=manual`
  - 用于检查修订候选的连续性。
  - 本页通常接在修订后，应优先使用 revision 版本。
- `GET /api/continuity/state`
  - 参数：`scene_id`、`target_type`、`target_id`、`revision_id`、`mode`。
  - 用于刷新连续性状态、开放问题和候选解决方案。
- `GET /api/continuity/issues`
  - 参数：`scene_id`、`target_type`、`status`。
  - 用于列出阻塞、警告和需复核问题。
- `POST /api/continuity/issues/{issueId}/resolution-decisions`
  - 用于用户选择连续性问题处理方案。
- `POST /api/continuity/issues/{issueId}/accept`
  - 用于接受并记录某个可接受的连续性问题。
- `POST /api/continuity/issues/{issueId}/resolve`
  - 用于解决连续性问题。
- `POST /api/memory-sync/scene/{sceneId}/plan-from-revision`
  - body: `{ revision_id, dry_run }`
  - 用于根据修订候选生成记忆写入计划。
- `GET /api/memory-sync/plans/{planId}`
  - 用于读取记忆写入计划详情。
- `POST /api/memory-sync/plans/{planId}/confirm`
  - body: `{ user_input }`
  - 用于确认记忆计划，但不一定立即应用。
- `POST /api/memory-sync/plans/{planId}/apply`
  - 用于应用已确认的记忆计划。
- `POST /api/memory-sync/plans/{planId}/reject`
  - body: `{ user_input }`
  - 用于拒绝本次记忆计划。
- `POST /api/memory-sync/plans/{planId}/confirm-and-apply`
  - body: `{ user_input }`
  - 对应本页主按钮“确认并写入”。
- `POST /api/scenes/{sceneId}/commit`
  - body: `{ commit_type, user_input, revision_id, accepted_abcd_runtime_issue_ids }`
  - 用于后续正式确认场景，不应在本页静默触发。
- `POST /api/scenes/{sceneId}/temporary-confirm`
  - body: `{ user_input }`
  - 可用于需要临时确认但还不正式提交的流程。

## 建议数据类型

```ts
type SceneContinuityMemoryWriteState = {
  project_id: string;
  chapter_id: string;
  scene_id: string;
  revision_id?: string | null;
  scene_index: number;
  total_scene_count: number;
  gate_readiness?: {
    safe_to_confirm: boolean;
    requires_user_action: boolean;
    reason_codes: string[];
  };
  continuity: {
    status: "not_run" | "passed" | "warning" | "blocking" | "needs_review";
    target_type: "scene" | "scene_revision";
    target_id: string;
    mode: "manual" | "auto";
    blocking_issues: Array<SceneContinuityIssue>;
    warnings: Array<SceneContinuityIssue>;
    open_clues: Array<{
      clue_id: string;
      summary: string;
      required_followup_scene_id?: string | null;
    }>;
  };
  memory_plan?: {
    plan_id: string;
    status: "not_created" | "draft" | "pending_confirmation" | "confirmed" | "applied" | "rejected";
    source_revision_id?: string | null;
    new_memory_records: Array<SceneMemoryRecord>;
    replacement_memory_records: Array<SceneMemoryReplacement>;
    event_summary: string[];
    proposed_state_changes: string[];
    relationship_changes: string[];
    dependent_scene_actions: Array<{
      action_id: string;
      scene_id?: string | null;
      summary: string;
      required: boolean;
    }>;
    confirmation_reasons: string[];
    memory_pack_refresh_recommended: boolean;
  };
  write_status: "not_written" | "ready" | "rejected" | "writing" | "written" | "failed";
  user_input: string;
};

type SceneContinuityIssue = {
  issue_id: string;
  category?: string;
  severity: "warning" | "blocking";
  status: "open" | "accepted" | "resolved" | "rejected";
  user_visible_message: string;
  evidence_text?: string;
  recommended_action?: string;
};

type SceneMemoryRecord = {
  memory_id?: string;
  object_type: "scene" | "character" | "relationship" | "object" | "world" | string;
  object_id?: string;
  summary: string;
  tags: string[];
  confidence?: "low" | "medium" | "high";
  source_scene_id: string;
};

type SceneMemoryReplacement = {
  old_memory_id: string;
  new_memory_id?: string;
  reason: string;
};
```

## 接入规则

- “确认并写入”应先确保连续性没有阻塞项。
- 写入前必须存在 `plan_id`；如果没有，先调用 `plan-from-revision`。
- 如果用户只想保留正文但暂不写入记忆，应提供拒绝或返回审阅路径。
- 写入完成后刷新当前场景、记忆计划、连续性状态和下一场景可读取上下文包。
- 写入失败时不得把 UI 显示为已写入，应展示错误并允许重新应用或拒绝计划。

## 视觉决策

- 继续使用 `assets/scene-writing-background-v1.png`。
- 不显示创作路线。
- 不显示调试字段和后端原始 JSON。
- 不使用“经典莫兰迪”右上角标签。
- 右侧只保留用户必须理解的影响，不做专家模式展开。
- 记忆写入是用户确认后的显式动作，不做自动写入。

## 文件

- 动态稿：`visual-drafts/scene-writing-continuity-memory-write-v1.html`
- 桌面截图：`visual-drafts/scene-writing-continuity-memory-write-v1.png`
- 移动端截图：`visual-drafts/scene-writing-continuity-memory-write-v1-mobile.png`
