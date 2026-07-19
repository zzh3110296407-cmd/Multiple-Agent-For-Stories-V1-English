# 12 场景写作 / 02 场景简述审阅 V1

## 页面定位

该页位于“来源前提与场景入口”之后、“正文生成中”之前。用户在这里审阅并微调当前场景简述，确认场景目标、角色行动、事实边界和用户补充要求，再进入正文生成。

## 核心 UI

- 顶部：返回入口、面包屑、模型连接状态。
- 页面标题：场景简述审阅。
- 摘要条：当前场景、参与者、简述状态。
- 主区域：当前场景标题、场景简述审阅分区、可编辑文本框、写作侧重标签、审阅项卡片、来源锚点。
- 右侧：审阅清单，可点击切换详情。
- 右下角动作：恢复来源、保存简述、开始生成正文。

## 当前交互

- 场景简述分区支持 `目标 / 行动 / 边界 / 补充` 切换。
- 写作侧重标签可开关，用于后续生成参数。
- 审阅项卡片可点击确认，默认有一个“待用户确认”项；该卡片徽标显示“点击确认”。
- 右侧清单可点击查看来源说明。
- `开始生成正文` 在仍有待确认项时会提示用户先确认。
- `保存简述` 只表示保存当前审阅稿，不写入正式场景正文或记忆。

## Phase 8.5 前端接口映射

该页后续接入时主要读取以下数据：

- `GET /api/scenes/progress?chapter_id=...`：当前章场景推进状态、下一场景位置。
- `GET /api/scenes/current`：当前场景草稿、状态、`scene_id`、`scene_index`、`chapter_id`。
- `GET /api/scene-participants/selections/current?chapter_id=...&scene_index=...`：参与者选择与候选确认状态。
- `GET /api/scenes/{sceneId}/gate-readiness`：正文生成前的门控就绪状态。
- `GET /api/continuity/state?...`：连续性状态摘要。
- `GET /api/scenes/{sceneId}/writer-quality-surface?...`：后续正文审阅页会展开的写作质量数据。
- `POST /api/scenes/generate-first` 或 `POST /api/scenes/generate-next`：用户确认场景简述后进入正文生成。

当前 Phase 8.5 前端没有从源码中看到独立的“保存场景简述”正式接口；接入时可先作为前端本地草稿状态，或由 Codes 增补轻量接口。

## 建议数据类型

```ts
type SceneBriefReviewDraft = {
  project_id: string;
  chapter_id: string;
  chapter_index: number;
  scene_id?: string;
  scene_index: number;
  scene_count: number;
  title: string;
  goal: string;
  required_beats: string[];
  forbidden_beats: string[];
  participant_ids: string[];
  source_anchor_ids: string[];
  continuity_status: "passed" | "warning" | "blocked" | "not_run";
  user_notes?: string;
  focus_tags: string[];
  review_status: "draft" | "needs_user_confirmation" | "reviewed";
};
```

## 视觉决策

- 继续使用 `assets/scene-writing-background-v1.png`。
- 不展示创作路线。
- 该页不放完整正文编辑器，避免与后续正文草案审阅页职责重叠。
- 输入区使用完整边框，不使用横线输入。
- 主动作固定在右下角，和 12-01 保持一致。
