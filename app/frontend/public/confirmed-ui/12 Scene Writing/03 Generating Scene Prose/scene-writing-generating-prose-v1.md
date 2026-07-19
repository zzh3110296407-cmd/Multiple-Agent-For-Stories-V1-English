# 12 场景写作 / 03 正文生成中 V1

## 页面定位

该页位于“场景 Brief 审阅”之后、“正文草案审阅”之前。用户点击“开始生成正文”后进入这里，系统把场景简述、角色行动、世界事实、记忆锚点和连续性边界合成为当前场景正文草案。

该页是生成等待与状态展示页，不是审阅页，也不承担正式确认、记忆写入或推进下一场景的职责。

## 核心 UI

- 顶部：返回场景简述、面包屑、模型连接状态。
- 页面标题：正文生成中。
- 摘要条：当前场景、当前阶段、草案状态。
- 主区域：当前场景标题、生成百分比、手稿生成动画、阶段序列、生成依据。
- 右侧：来源合流，展示场景简述、角色、世界事实、记忆、连续性、质量面读取状态。
- 底部动作：查看场景简述、加快演示、进入草案审阅。

## 当前交互

- 页面自动按阶段推进：读取场景简述、组装角色、读取记忆、连续性预检、正文成形、等待审阅。
- `加快演示` 用于动画稿预览，真实接入时可删除或仅在调试模式保留。
- `查看场景简述` 打开轻量弹层，方便用户确认当前生成依据。
- `进入草案审阅` 在生成完成前保持弱化状态；生成完成后变为可用。
- 点击未完成状态的 `进入草案审阅` 只提示等待，不应跳转。

## Phase 8.5 前端接口映射

该页后续接入时主要对应正文生成任务的执行与轮询：

- `POST /api/scenes/generate-first`：生成当前章第一场正文。
- `POST /api/scenes/generate-next`：生成当前章后续场景正文。
- `GET /api/scenes/current`：读取当前场景、`scene_id`、`chapter_id`、`scene_index`、正文草案状态。
- `GET /api/scenes/progress?chapter_id=...`：读取当前章场景进度。
- `GET /api/scenes/{sceneId}/gate-readiness`：读取生成前门控状态；若阻塞，应回到问题处理页而不是进入本页。
- `GET /api/scenes/{sceneId}/writer-quality-surface?...`：生成后进入草案审阅时使用的质量面数据。
- `GET /api/continuity/state?...`：读取连续性状态摘要。

如果后端提供异步任务事件流，该页可从轮询改为事件订阅，但 UI 状态仍保持同一套阶段模型。

## 建议数据类型

```ts
type SceneProseGenerationState = {
  project_id: string;
  chapter_id: string;
  chapter_index: number;
  scene_id: string;
  scene_index: number;
  scene_count: number;
  scene_title: string;
  status: "queued" | "generating" | "ready_for_review" | "blocked" | "failed";
  generation_stage:
    | "reading_brief"
    | "assembling_characters"
    | "reading_memory"
    | "continuity_precheck"
    | "drafting_prose"
    | "ready_for_review";
  progress_percent: number;
  source_flow: Array<{
    key: "brief" | "characters" | "world_facts" | "memory" | "continuity" | "quality_surface";
    label: string;
    status: "waiting" | "reading" | "done" | "warning" | "blocked";
    summary?: string;
  }>;
  active_revision_id?: string;
  error_message?: string;
};
```

## 视觉决策

- 继续使用 `assets/scene-writing-background-v1.png`，保持 12 场景写作模块的一致氛围。
- 不展示创作路线。
- 中央使用手稿生成动画，避免把后端日志或调试表格暴露给用户。
- 右侧来源合流只展示用户能理解的来源分类，不展示内部 agent 细节。
- 完成后只进入“正文草案审阅”，不在该页自动确认正文、不写入记忆、不推进下一场景。
- 全部文字保持中文展示，避免残留英文状态标签。

## 文件

- 动态稿：`visual-drafts/scene-writing-generating-prose-v1.html`
- 桌面截图：`visual-drafts/scene-writing-generating-prose-v1.png`
- 移动端截图：`visual-drafts/scene-writing-generating-prose-v1-mobile.png`
