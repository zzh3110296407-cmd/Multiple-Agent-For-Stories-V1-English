# 13 最终输出 / 03 成稿审阅

日期：2026-07-04

## 设计状态

V1 已生成。该页面是最终故事包快照创建后的审阅页，用户侧标题为 `成稿审阅`。

视觉稿：

```text
visual-drafts/final-output-manuscript-review-v1.html
visual-drafts/final-output-manuscript-review-v1.png
visual-drafts/final-output-manuscript-review-v1-mobile.png
```

背景素材：

```text
../assets/final-output-background-v1.png
```

## 页面目标

该页用于让用户在导出交付前审阅最终故事包快照。

核心用户任务：

- 查看最终正文预览。
- 切换查看目录、角色表、世界摘要、关键事件、用户锁定约束。
- 查看保留警告和来源边界。
- 完成审阅确认后进入后续导出交付。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/frontend/src/components/FinalStoryPackageProductView.jsx
app/backend/models/final_story_package.py
```

主要 helper：

```text
getFinalStoryPackageSnapshot(snapshotId)
getFinalStoryPackageSnapshotSections(snapshotId)
getFinalStoryPackageEvidenceIndex(snapshotId)
getFinalStoryPackageSafetyAudit(snapshotId)
createFinalStoryPackageViewerState({
  snapshotId,
  selectedSectionType,
  visiblePanels,
  showSourceLineage,
  showEvidenceIndex,
  showSafetyAudit
})
```

本页暂不触发：

```text
downloadFinalStoryPackageSnapshot(...)
exportFinalStoryPackage(...)
```

下载和格式选择放到后续 `04 导出交付`。

## 关键数据字段

`FinalStoryPackageSnapshot`：

```ts
{
  snapshot_id: string;
  package_type: "real_project_final_package" | "fixture_final_story_package";
  readiness_status: "ready" | "ready_with_warnings" | "blocked" | "fixture_only";
  snapshot_status: "created" | "fixture" | "blocked";
  complete_story_text: string;
  complete_story_text_hash: string;
  complete_story_text_char_count: number;
  chapter_scene_index: Array<Record<string, unknown>>;
  character_table: Array<Record<string, unknown>>;
  world_canvas_summary: Record<string, unknown>;
  relationship_state_summary: Array<Record<string, unknown>>;
  key_event_timeline: Array<Record<string, unknown>>;
  user_locked_constraints: Array<Record<string, unknown>>;
  style_and_tone: Record<string, unknown>;
  known_residual_codes: string[];
  can_be_used_by_plugins: boolean;
  not_real_project_final_package: boolean;
  safe_summary: string;
}
```

`FinalStoryPackagePreviewSection`：

```ts
{
  preview_section_id: string;
  snapshot_id: string;
  section_type:
    | "complete_story_text"
    | "chapter_scene_index"
    | "character_table"
    | "world_canvas_summary"
    | "relationship_state_summary"
    | "key_event_timeline"
    | "user_locked_constraints"
    | "style_and_tone"
    | "source_lineage"
    | "known_residuals"
    | "other";
  display_order: number;
  title: string;
  content_mode: "full_text" | "table" | "summary" | "lineage" | "audit";
  safe_preview: string;
  item_count: number;
  source_ref_ids: string[];
}
```

## UI 映射

- 顶部摘要：
  - 包类型：`snapshot.package_type`
  - 正文规模：`snapshot.complete_story_text_char_count`
  - 审阅状态：本地审阅状态或 viewer state
- 分区 tabs：
  - 正文：`complete_story_text`
  - 目录：`chapter_scene_index`
  - 角色表：`character_table` + `relationship_state_summary`
  - 世界摘要：`world_canvas_summary`
  - 事件线：`key_event_timeline`
  - 锁定约束：`user_locked_constraints`
- 右侧警告：
  - `known_residual_codes`
  - readiness warning issue ids
  - safety audit 中的用户可见警告
- 审阅确认：
  - 用户必须确认已审阅成稿内容。
  - 用户必须确认接受保留警告。
  - 两项确认后才能启用 `确认成稿`。

## 交互记录

V1 HTML 已实现：

- 成稿分区切换：正文、目录、角色表、世界摘要、事件线、锁定约束。
- 点击警告项更新警告详情。
- `标记已读` 自动勾选保留警告确认。
- 两个审阅确认勾选后，`确认成稿` 才启用。
- 确认成稿后页面状态变为 `已确认`，下一步进入导出交付。
- 正文、目录、角色表、世界摘要、事件线、锁定约束六个分区内容统一使用内部滚动容器，内容增多时只在阅读区内滚动，不撑开页面主体。
- 分区切换统一由上方六个按钮承担；旧版右侧分区摘要卡片已删除，主阅读区扩宽以突出正文审阅。

## 设计边界

- 本页不出现 `创作路线`。
- 阶段提示不是可点击导航。01-04 是最终输出主交付线；05 为导出生成中；06 为下载与归档结果；07 为异常分支。本页只突出 03。
- 本页不提供下载入口。
- 本页不做导出格式选择。
- 本页不允许用户直接编辑正文。
- 主阅读区必须保持固定视觉框架；分区内容过长时进入内部滚动，不允许压缩右侧审阅面板或撑出整页。
- 主阅读区内部不再重复展示分区摘要卡片，避免与上方分区按钮形成冗余。
- 本页不把插件输出、候选提案或调试证据写回故事事实。
- 若用户要求修订，应回到对应模块或进入专门修订入口，不在本页内直接修改快照内容。
