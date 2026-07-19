# 12 场景写作 / 01 来源前提与场景入口 V1

## 页面定位

该页是场景写作模块的入口页，负责选择当前章中的目标场景，展示场景写作前必须读取或确认的来源前提，并把用户导向正文生成流程。

## 核心 UI

- 顶部：返回总览、面包屑、模型连接状态。
- 页面标题：场景写作。
- 摘要条：当前章、场景位置、正文状态。
- 主区域：横向可滑动场景轨道、当前场景 Brief、正文前检查、出场角色、记忆引用。
- 右侧：来源前提列表，可点击查看来源细节。
- 右下角动作：刷新来源、确认参与者、生成场景正文。

## 当前交互

- 场景轨道支持左右按钮和鼠标滚轮横向滑动。
- 点击场景卡切换 Brief、参与者、检查项与当前动作提示。
- 点击来源前提卡切换右下来源细节。
- 点击确认参与者后，参与者候选状态变为已确认，并解锁当前场景正文生成态。
- 点击生成场景正文后出现进入生成状态反馈。

## Phase 8.5 前端接口映射

后续接入时，该页主要对应以下接口和状态：

- `GET /api/scenes/progress?chapter_id=...`：读取当前章场景推进、下一场景索引、场景完成状态。
- `GET /api/scenes/current`：读取当前场景草稿和状态。
- `GET /api/scene-participants/selections/current?chapter_id=...&scene_index=...`：读取当前场景参与者选择和候选确认状态。
- `POST /api/scene-participants/creation-candidates/{candidateId}/confirm`：确认参与者候选。
- `POST /api/scene-participants/creation-candidates/{candidateId}/reject`：拒绝参与者候选。
- `POST /api/scenes/generate-first`：生成当前章第一场景正文。
- `POST /api/scenes/generate-next`：生成下一场景正文。
- `GET /api/scenes/{sceneId}/gate-readiness`：读取场景门控就绪状态。
- `GET /api/continuity/state?...`：读取连续性状态，后续页面会展开处理。
- `GET /api/scenes/{sceneId}/writer-quality-surface?...`：读取写作质量面板，后续草案审阅页会展开。

## 数据字段预留

- `chapter_id`
- `chapter_index`
- `scene_id`
- `scene_index`
- `scene_count`
- `scene.status`
- `scene.active_revision_id`
- `participant_selection.selection_id`
- `creation_candidate_id`
- `gate_readiness.status`
- `continuity_status`
- `memory_pack_id`
- `writer_quality_surface`

## 视觉决策

- 使用 `assets/scene-writing-background-v1.png` 作为模块背景。
- 视觉重心保留在“正文前入口”，不提前展示完整正文编辑器。
- 不使用创作路线。
- 操作按钮集中在右下角，延续 08-11 模块的行为习惯。
