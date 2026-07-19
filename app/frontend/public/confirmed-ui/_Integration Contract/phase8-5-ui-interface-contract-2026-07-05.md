# Phase 8.5 UI 对接接口契约

日期：2026-07-05  
范围：`UI Design/05 Page Records/99 Complete` 全部最终 UI 页面。  
原则：UI 设计文件不直接改项目主体；接口名称、路由和动作均以 Phase 8.5 前端源码为准。

## 读取依据

- 前端入口：`app/frontend/src/App.jsx`
- API 封装：`app/frontend/src/api/projectApi.js`
- 工作区视图：`app/frontend/src/views/*.jsx`
- 产品导航服务：`app/backend/services/product_navigation_service.py`

## 全局路由与工作区

| UI 分类 | Phase 8.5 workspace_id | route_key | React 视图 |
|---|---:|---:|---|
| 01 主页 | `home` | `home` | `ProductHomeWorkspace` |
| 02 项目创建 | `create_project` | `project` | `ProjectCreationWorkspace` |
| 03 项目列表 | `projects` | `project` | `ProjectCreationWorkspace` 侧栏项目列表 |
| 04 当前项目总览 | `current_project` | `current_project` | `ProductHomeWorkspace` 当前项目态 |
| 05 模板与演示 | `template_demo` | `template_demo` | `TemplateDemoSeedWorkspace` |
| 06 Framework 编排 | `framework` | `framework` | `FrameworkWorkbenchWorkspace` |
| 07 导入故事 / 故事分析器 | `analyze_stories` | `analyze` | `FrameworkWorkbenchWorkspace` 内部分支 |
| 08 故事设定 | `story_setup` | `story_setup` | `StorySetupWorkspace` |
| 09 世界画布 | `world_canvas` | `world_canvas` | `WorldCanvasWorkspace` |
| 10 角色主轴 | `characters` | `characters` | `CharacterWorkspace` |
| 11 章节计划 | `chapter_plan` | `chapter_plan` | `ChapterPlanningWorkspace` |
| 12 场景写作 | `chapter_scene` | `scene` | `SceneWorkspace` |
| 12 连续性与记忆 | `memory_continuity` | `scene` | `SceneWorkspace` 折叠区域 |
| 13 最终输出 | `final_outputs` | `final_outputs` | `ProductOutputsWorkspace` |
| 14 插件输出 | `plugin_outputs` | `plugin_outputs` | `ProductOutputsWorkspace` |
| 15 设置 | `settings` | `settings` | `ModelSettingsWorkspace` |
| 16 壳层不可用/正常态 | 全部 workspace 共用 | 全部 route 共用 | `ProductAppShell` / `WorkspaceUnavailablePanel` |

注意：`projects` 和 `create_project` 在 Phase 8.5 都使用 `route_key: project`，项目列表不是单独 React 页面；我们的 03 UI 是面向用户的独立设计稿，接入时应复用 `getProjects/openProject` 和 `ProjectCreationWorkspace` 的项目列表数据。

注意：用户确认的产品主流程把 Framework 放在 Story Setup / World Canvas 之前；当前 `product_navigation_service.py` 的 registry sort order 不是最终 UI 阅读顺序。接入当前项目总览时应使用 UI 侧显式顺序，而不是直接按 registry sort_order 渲染。

## 全局壳层接口

- 导航状态：`getProductNavigationState({ workspaceId, projectId, modeProfileId })` -> `GET /api/product-navigation/state`
- 工作区权限：`getProductWorkspaceAccess(workspaceId, params)` -> `GET /api/product-navigation/workspaces/{workspaceId}/access`
- 导航偏好：`patchProductNavigationPreferences(payload)` -> `PATCH /api/product-navigation/preferences`
- 模式切换：`patchProductModeProfile(payload)` -> `PATCH /api/product-mode/profile`
- 进度状态：`getProductProgressState(params)` -> `GET /api/product-progress/state`

壳层必须处理：

- `can_access=false` 时渲染 `WorkspaceUnavailablePanel`
- 使用 `safe_redirect_workspace_id` 跳到安全工作区
- 普通模式隐藏 expert/debug 工作区
- `memory_continuity` 点击后仍进入 `scene` 路由中的连续性区域

## 模块接口

### 02 项目创建 / 03 项目列表

| UI 动作 | 前端 action | API |
|---|---|---|
| 加载模式 | 初始化数据 | `GET /api/project-creation/modes` |
| 加载演示种子 | 初始化数据 | `GET /api/project-creation/demo-seeds` |
| 创建请求 | `create-request` | `POST /api/project-creation/requests` |
| 验证请求 | `validate-request` | `POST /api/project-creation/requests/{creationRequestId}/validate` |
| 创建草稿 | `create-draft` | `POST /api/project-creation/requests/{creationRequestId}/draft` |
| 确认项目 Shell | `confirm-draft` | `POST /api/project-creation/drafts/{creationDraftId}/confirm` |
| 取消草稿 | `cancel-draft` | `POST /api/project-creation/drafts/{creationDraftId}/cancel` |
| 加载项目列表 | 初始化/刷新 | `GET /api/projects` |
| 打开已有项目 | `open-project` | `POST /api/projects/{projectId}/open` |

请求 payload 关键字段：`modeType/mode_type`、`requestedTitle/requested_title`、`requestedLanguage/requested_language`、`promptText/prompt_text`、`templateId/template_id`、`analyzeStoriesImportRef/analyze_stories_import_ref`、`demoSeedId/demo_seed_id`、`existingProjectId/existing_project_id`、`explicitUserSelection/explicit_user_selection`。

### 05 模板与演示

| UI 动作 | 前端 action | API |
|---|---|---|
| 加载模板 | `refresh` | `GET /api/project-templates` |
| 加载演示种子 | `refresh` | `GET /api/demo-seeds` |
| 创建模板实例请求 | `template-request` | `POST /api/project-templates/{templateId}/instantiation-requests` |
| 验证模板实例 | `template-validate` | `POST /api/template-instantiation/requests/{requestId}/validate` |
| 实例化模板 | `template-instantiate` | `POST /api/template-instantiation/requests/{requestId}/instantiate` |
| 运行演示种子 | `demo-run` | `POST /api/demo-seeds/{demoSeedId}/run` |
| 演示隔离审计 | `demo-audit` | `POST /api/demo-seeds/runs/{runId}/isolation-audit` |

### 06 Framework 编排

| UI 动作 | 前端 action | API |
|---|---|---|
| 刷新 workbench | `workbench-refresh` | `GET /api/framework-package/workbench` |
| 推荐映射 | `workbench-recommend` | `POST /api/framework-package/workbench/recommend` |
| 更新章节数 | `workbench-chapter-count` | `POST /api/framework-package/workbench/chapter-count` |
| 更新章节分配 | `workbench-assignment` | `PATCH /api/framework-package/workbench/assignments/{chapterIndex}` |
| 验证映射 | `workbench-validate` | `GET /api/framework-package/workbench/validate` |
| 确认映射 | `workbench-confirm` | `POST /api/framework-package/workbench/confirm` |
| 保存 Framework composition | `composition-save` | `POST /api/framework-compositions/drafts` |
| 验证 composition | `composition-validate` | `POST /api/framework-compositions/drafts/{compositionId}/validate` |
| 确认 composition | `composition-confirm` | `POST /api/framework-compositions/drafts/{compositionId}/confirm` |
| 生成器上下文 | `composition-generator-context` | `GET /api/framework-compositions/drafts/{compositionId}/generator-context` |

### 07 Analyze Stories 分支

| UI 动作 | 前端 action | API |
|---|---|---|
| 导入分析源 | `import` | `POST /api/analyze-stories/imports` |
| 刷新导入/候选/报告 | `refresh` | `GET /api/analyze-stories/imports` 等读接口 |
| 验证 bundle | `bundle-validate` | `POST /api/analyze-stories/imports/{importId}/bundle-validation` |
| 读取 bundle | `bundle-detail` | `GET /api/analyze-stories/bundles/{bundleManifestId}` |
| 重新验证 bundle | `bundle-revalidate` | `POST /api/analyze-stories/bundles/{bundleManifestId}/revalidate` |
| 派生 adapter 候选 | `adapter-derive` | `POST /api/analyze-stories/bundles/{bundleManifestId}/adapter-derivations` |
| 创建 Framework 候选 | `candidate-create` | `POST /api/analyze-stories/imports/{importId}/framework-candidates` |
| 创建报告 Viewer | `report-viewer-create` | `POST /api/analyze-stories/report-viewers` |
| 打开导入编辑会话 | `imported-session-start` | `POST /api/analyze-stories/framework-candidates/{candidateId}/edit-sessions` |
| 验证/激活导入编辑 | `imported-session-validate` / `imported-plan-confirm` | `POST /api/analyze-stories/imported-framework-edit-sessions/{id}/validate` / `POST /api/analyze-stories/imported-framework-activation-plans/{id}/confirm` |

### 08 故事设定

| UI 动作 | 前端 action | API |
|---|---|---|
| 创建 prompt | `create-prompt` | `POST /api/story-setup/prompts/from-project` |
| 创建 intake | `create-intake` | `POST /api/story-setup/intakes` |
| 创建草案包 | `create-draft-bundle` | `POST /api/story-setup/draft-bundles` |
| 回答问题 | `answer-question` | `POST /api/story-setup/questions/{questionId}/answer` |
| 决策 | `create-decision` | `POST /api/story-setup/draft-bundles/{bundleId}/decisions` |
| 创建 handoff | `create-handoff` | `POST /api/story-setup/decisions/{decisionId}/handoff` |
| 初始化工作区 | `bootstrap-handoff` | `POST /api/story-setup/handoffs/{handoffId}/bootstrap-active-project` |
| 安全报告 | `safety-report` | `GET /api/story-setup/draft-bundles/{bundleId}/safety-report` |

### 09 世界画布

| UI 动作 | 前端 action | API |
|---|---|---|
| 读取当前 | `current` | `GET /api/world-canvas/current` |
| 生成 | `generate` | `POST /api/world-canvas/generate` body `{ story_idea }` |
| 修订 | `revise` | `POST /api/world-canvas/revise` body `{ revision_prompt }` |
| 确认 | `confirm` | `POST /api/world-canvas/confirm` body `{ user_input }` |

返回数据以 `world_canvas`、`validation`、`decision` 为核心。UI 需保留 `status`、`story_direction`、`scope`、`tone`、`world_structure`、`hard_rules`、`soft_rules`、`unknown_rules`、`logic_conflicts`、`user_confirmation_needed`。

### 10 角色主轴 / 角色管理

| UI 动作 | 前端 action | API |
|---|---|---|
| 生成角色草案 | `generate` | `POST /api/characters/generate` |
| 修订角色草案 | `revise` | `POST /api/characters/revise` |
| 确认角色草案 | `confirm` | `POST /api/characters/confirm` |
| 完成主角团 | `finish` | `POST /api/characters/finish-main-cast` |
| 读取当前角色 | `current` | `GET /api/characters/current` |
| 角色列表 | `refresh` | `GET /api/roles` |
| 生成角色档案草稿 | `generate-role-draft` | `POST /api/roles/generate` |
| 确认生成草稿 | `confirm-generated-draft` | `POST /api/roles/generated-draft/confirm` |
| 手动创建角色 | `create` | `POST /api/roles` |
| 编辑角色 | `patch` | `PATCH /api/roles/{characterId}` |
| 改分级 | `change-tier` | `POST /api/roles/{characterId}/change-tier` |
| 归档 | `archive` | `POST /api/roles/{characterId}/archive` |
| 上下文预览 | `context-preview` | `POST /api/roles/context-preview` |
| A-tier 状态变更 | `propose-state-change` / `confirm-state-change` / `reject-state-change` | `POST /api/roles/state-changes/*` |

### 11 章节计划

| UI 动作 | 前端 action | API |
|---|---|---|
| 构建当前章 Framework | `build-current` | `POST /api/framework-package/chapter-framework/build-current` |
| 读取当前章 Framework | `current` | `GET /api/framework-package/chapter-framework/current` |
| 生成章节计划 | `generate` | `POST /api/chapter-plan/generate` |
| 读取章节计划 | `current` | `GET /api/chapter-plan/current` |
| 修订章节计划 | `revise` | `POST /api/chapter-plan/revise` |
| 设置场景数 | `scene-count` | `POST /api/chapter-plan/set-scene-count` |
| 修复 supporting roles | `repair-supporting-roles` | `POST /api/chapter-plan/repair-supporting-role-references` |
| 确认章节计划 | `confirm` | `POST /api/chapter-plan/confirm` |

### 12 场景写作 / 连续性

| UI 动作 | 前端 action | API |
|---|---|---|
| 生成首场景 | `generate` | `POST /api/scenes/generate-first` |
| 生成下一场景 | `generate-next` | `POST /api/scenes/generate-next` |
| 重新生成首场景 | `regenerate` | `POST /api/scenes/regenerate-first` |
| 读取当前场景 | `current` | `GET /api/scenes/current` |
| 确认草稿 | `confirm` | `POST /api/scenes/confirm-draft` |
| 提交场景 | `commit-scene` | `POST /api/scenes/{sceneId}/commit` |
| 临时确认 | `temporary-confirm` | `POST /api/scenes/{sceneId}/temporary-confirm` |
| 运行质量检查 | `quality-scene` | `POST /api/quality-check/scene/{sceneId}` |
| runtime refresh | `runtime-refresh` | `POST /api/scenes/{sceneId}/runtime-refresh-state/refresh` |
| 场景门修复 | `scene-gate-repair-run` | `POST /api/scene-gate-repair/scenes/{sceneId}/runs` |
| 参与角色候选确认/拒绝 | `scene-participant-candidate-confirm/reject` | `POST /api/scene-participants/creation-candidates/{candidateId}/confirm` / `reject` |
| 修改影响预览 | `modification-preview` | `POST /api/modification-impact/previews` |
| 连续性检查 | `continuity-scene` | `POST /api/continuity/check/scene/{sceneId}` |
| 连续性接受/解决 | `continuity-accept/resolve` | `POST /api/continuity/issues/{issueId}/accept` / `resolve` |
| 叙事债务处理 | `debt-paid-off/intentionally-open/reject/update` | `POST/PATCH /api/narrative-layer/debts/*` |
| 章节归档预览 | `archive-preview` | `GET /api/chapter-archive/preview` |
| 准备/确认下一章 | `prepare-next/confirm-next` | `POST /api/story-progress/prepare-next-chapter` / `confirm-next-chapter` |
| 故事草稿完成 | `story-complete` | `POST /api/story-progress/confirm-story-draft-complete` |

### 13 最终输出

| UI 动作 | 前端 action | API |
|---|---|---|
| 完成度检查 | `evaluate` | `POST /api/final-story-package/readiness/evaluate` |
| 刷新 readiness | `refresh` | `GET /api/final-story-package/readiness` |
| 导出成稿 | `export` | `POST /api/final-story-package/export` |
| 导出运行列表 | `refresh-export` | `GET /api/final-story-package/exports` |
| 读取 snapshot | 选择 snapshot | `GET /api/final-story-package/snapshots/{snapshotId}` |
| 读取 sections | 选择 snapshot | `GET /api/final-story-package/snapshots/{snapshotId}/sections` |
| Viewer 状态 | `viewer-state` | `POST /api/final-story-package/viewer-states` |
| 下载 | `download-{format}` | `GET /api/final-story-package/snapshots/{snapshotId}/download?format={format}` |

### 14 插件输出

| UI 动作 | 前端 action | API |
|---|---|---|
| 插件列表 | `refresh` | `GET /api/plugins` |
| 插件详情 | `detail` | `GET /api/plugins/{pluginId}` + manifest/input/output/risk |
| 验证输入 | `validate` | `POST /api/plugins/{pluginId}/validate-input` |
| 创建运行 | `create-run` | `POST /api/plugins/{pluginId}/runs` |
| 运行详情 | `refresh` | `GET /api/plugin-runs/{pluginRunId}` |
| 检查点 | `confirm/revise/reject/defer` | `POST /api/plugin-runs/{runId}/checkpoints/{checkpointId}/{action}` |
| 取消运行 | `cancel` | `POST /api/plugin-runs/{pluginRunId}/cancel` |
| 产物详情 | `artifact` | `GET /api/plugin-artifacts/{artifactId}` |
| Script Forging 子流 | `create-* / confirm-* / revise-* / reject-* / defer-*` | `POST /api/plugin-runs/{runId}/script-forging/*` |

### 15 设置

| UI 动作 | 前端 action | API |
|---|---|---|
| 模型供应商列表 | 初始化 | `GET /api/settings/model/providers` |
| 设置工作台 | 初始化 | `GET /api/settings/model/workbench` |
| Provider profiles | 初始化 | `GET /api/settings/model/profiles` |
| 创建模型配置 | `create-profile` | `POST /api/settings/model/profiles` |
| 修改模型配置 | `patch-profile` | `PATCH /api/settings/model/profiles/{profileId}` |
| 健康检查 | `health-check` | `POST /api/settings/model/profiles/{profileId}/health-check` |
| 设为当前模型 | `set-active` | `POST /api/settings/model/active-selection` |
| 密钥策略 | 初始化 | `GET /api/settings/model/secret-policy` |

外观与主题、创作偏好目前是 UI 设计预留项。若 Phase 8.5 未提供专用后端偏好 API，接入时先作为前端本地状态或落到未来统一 preferences API，不能写入故事事实数据。

## 错误与加载状态

- 所有生成型动作必须设置对应 `*Action`，禁用重复提交按钮。
- API 错误沿用 `errorMessage(error)`，UI 以用户可读错误展示，不能泄露 raw prompt、hidden reasoning、密钥或完整内部响应。
- 每个主链路页面至少要有：入口、生成中、审阅、问题处理/修订、确认/交接。
- 列表类数据必须保留空状态、加载状态、错误状态。

## 交互连接

总连接器 `phase8-5-connected-ui-flow-v1.html` 已加入 `ACTIONS_BY_TITLE`。后续修改页面名称时，需要同步更新：

1. `FLOW` 中的 `title/group/path`
2. `ACTIONS_BY_TITLE` 中的 `target/targetGroup`
3. 本契约中的对应模块接口

重复标题必须使用 `targetGroup`，例如 08 与 10 都有“缺失信息处理”。
