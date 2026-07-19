# 12 场景写作 / 05 修订场景正文 V1

## 页面定位

该页位于“正文草案审阅”之后。用户在 04 中选择“要求修订”后进入这里，填写修订方向，查看当前草案与修订候选的对照，并确认这次修订对质量、连续性、记忆同步和后续场景的影响。

该页只生成修订候选与影响判断，不直接写入正式正文、不写入正式记忆、不推进下一场景。

## 核心 UI

- 顶部：返回草案审阅、面包屑、模型连接状态。
- 页面标题：修订场景正文。
- 摘要条：当前场景、修订状态、影响预览、安全边界。
- 主区域左侧：修订来源、修改意图、修订重点、不可越界边界。
- 主区域右侧：当前草案与修订候选对照、修订候选全文、影响预览。
- 右侧：修订安全检查，包含影响预览、质量复核、连续性、记忆同步、后续场景。
- 底部动作：影响预览、生成修订稿、放弃修订、采用修订。

## 当前交互

- 修订重点标签可开关。
- `对照 / 修订候选 / 影响预览` 可切换主视图。
- 点击右侧检查项会切换说明。
- `影响预览` 将状态改为低影响，并切换到影响预览视图。
- `生成修订稿` 将状态改为候选已生成，并回到对照视图。
- `放弃修订` 保持当前草案不变。
- `采用修订` 只进入采用意向状态；真实接入时应继续进入确认与记忆同步流程。

## Phase 8.5 前端接口映射

该页后续接入时主要对应以下接口和动作：

- `GET /api/scenes/current`：读取当前场景、正文、梗概、状态、`scene_id`、`active_revision_id`。
- `POST /api/scenes/regenerate-first`：按 `regeneration_hint` 重生成当前第一幕草案。当前前端已有 `onSceneAction("regenerate", { regenerationHint })`。
- `POST /api/modification-impact/preview`：生成修改影响预览。
  - body: `source_object_type`、`source_object_id`、`modification_source_type`、`modification_text`、`modification_summary`、`revision_id`、`change_summary`。
- `GET /api/modification-impact/previews/{previewId}`：读取某个影响预览。
- `POST /api/modification-impact/previews/{previewId}/choose`：选择影响处理方案。
  - body: `action_type`、`user_input`、`revision_prompt`、`accept_warnings`。
- `POST /api/quality-check/scene/{sceneId}/revision/{revisionId}`：复查修订候选质量。
- `POST /api/continuity/check/scene/{sceneId}/revision/{revisionId}?mode=manual`：复查修订候选连续性。
- `POST /api/scenes/{sceneId}/commit`：后续确认采用修订时传入 `revision_id`，不应在本页静默提交。
- `POST /api/memory-sync/scene/{sceneId}/plan-from-revision`：采用修订后生成记忆同步计划。

## 建议数据类型

```ts
type SceneProseRevisionWorkspaceState = {
  project_id: string;
  chapter_id: string;
  scene_id: string;
  scene_index: number;
  source: {
    source_object_type: "scene" | "scene_revision" | "confirmed_scene";
    source_object_id: string;
    revision_id?: string | null;
  };
  revision_prompt: string;
  focus_tags: string[];
  forbidden_changes: string[];
  current_prose_text: string;
  revision_candidate?: {
    revision_id: string;
    status: "draft" | "quality_checking" | "ready_for_review" | "blocked" | "accepted" | "rejected";
    revised_prose_text: string;
    revised_synopsis?: string;
    quality_status: "passed" | "warning" | "blocking" | "not_run";
    continuity_status: "passed" | "warning" | "blocking" | "not_run";
  };
  modification_preview?: {
    preview_id: string;
    status: "preview" | "chosen" | "rejected" | "expired";
    affected_objects: Array<{
      object_type: string;
      object_id: string;
      impact_area?: string;
      impact_level?: "low" | "medium" | "high";
      reason?: string;
    }>;
    warning_codes: string[];
    recommended_options: Array<{
      option_id: string;
      action_type: string;
      label: string;
      recommended: boolean;
      enabled: boolean;
    }>;
  };
  memory_sync_required: boolean;
};
```

## 视觉决策

- 继续使用 `assets/scene-writing-background-v1.png`。
- 主体为“修订方向 + 对照阅读”，让用户先看到改动本身，而不是调试字段。
- 影响预览放在右侧安全检查和主视图第三页签里，避免抢正文阅读焦点。
- “采用修订”不等于正式确认，文案明确后续仍需进入确认和记忆同步。
- 输入区使用完整边框，不使用横线输入。
- 不展示创作路线。

## 文件

- 动态稿：`visual-drafts/scene-writing-revising-prose-v1.html`
- 桌面截图：`visual-drafts/scene-writing-revising-prose-v1.png`
- 移动端截图：`visual-drafts/scene-writing-revising-prose-v1-mobile.png`
