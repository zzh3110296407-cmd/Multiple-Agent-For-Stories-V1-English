# 15 Settings / 06 创作偏好

## 页面定位

创作偏好页用于保存用户对默认创作行为的偏好：默认语言、创作节奏、章节与场景容量、草稿审阅习惯、默认写作取向和导出排版倾向。

该页不是故事内容生成页，也不应把偏好写成故事事实。偏好只影响后续页面的默认值、展示方式和询问策略；具体世界事实、角色事实、章节事实和正文仍必须通过对应页面的确认流程。

## 视觉方向

- 背景沿用 `15 Settings/assets/settings-background-v1.png`。
- 保持 Settings 模块现有结构：左侧设置分类，中间偏好控制台，右侧当前偏好预览与接入位置。
- 控件使用选择器、分段按钮、滑块、开关和底部动作按钮。
- 非交互性信息只做摘要块，不做按钮样式。
- 页面不使用旧式步骤轨道。

## 主要交互

- `默认语言`：选择中文、英文、双语草稿或跟随项目。
- `标点与排版`：选择中文出版格式、英文小说格式或轻量网络文格式。
- `创作节奏`：快节奏、均衡、细写。
- `默认章节数`：滑块，范围 1-20。
- `每章默认场景数`：滑块，范围 1-20。
- `生成后停在审阅页`：开关，默认开启。
- `自动保存草稿快照`：开关，默认开启。草稿快照不等同于确认。
- `显示阻塞原因摘要`：开关，默认开启。
- `允许批量进入下一步`：开关，默认关闭。
- `默认写作取向`：沉浸叙事、清晰推进、克制留白。
- `恢复默认`：回到系统默认偏好。
- `预览应用范围`：提示这些偏好影响哪些模块。
- `保存偏好`：保存为当前项目默认偏好。

## Phase 8.5 已有真实落点

来自 `backend/models/project_creation.py`：

```ts
type CreateProjectCreationRequest = {
  mode_type: string;
  requested_title: string;
  requested_language: string; // 默认 "zh"
  prompt_text?: string | null;
  template_id?: string | null;
  analyze_stories_import_ref?: string | null;
  demo_seed_id?: string | null;
  existing_project_id?: string | null;
  explicit_user_selection: boolean;
};
```

来自 `frontend/src/api/projectApi.js`：

```ts
createProjectCreationRequest(payload): Promise<ProjectCreationRequest>
```

对应 UI 字段：

```ts
requested_language = creativePreferences.defaultLanguage
```

来自 `frontend/src/utils/storyCapacity.js`：

```ts
STORY_CAPACITY = {
  chapterMin: 1,
  chapterMax: 20,
  defaultChapterCount: 5,
  sceneMin: 1,
  sceneMax: 20,
  defaultSceneCount: 5,
};
```

对应 UI 字段：

```ts
defaultChapterCount: number; // 1-20
defaultSceneCount: number; // 1-20
```

## 建议新增偏好契约

Phase 8.5 当前没有独立的创作偏好后端 API。建议 Codes 后续新增一个项目级设置端点，避免只存在 localStorage。

```ts
type CreativePreferences = {
  schemaVersion: "phase85_ui_creative_preferences_v1";
  projectId?: string;
  defaultLanguage: "zh" | "en" | "bilingual_draft" | "project_default";
  punctuationProfile: "zh_publishing" | "en_novel" | "light_web";
  paceProfile: "fast" | "balanced" | "detailed";
  defaultChapterCount: number;
  defaultSceneCount: number;
  draftReviewPolicy: {
    stopOnDraftReview: boolean;
    autoSaveDraftSnapshot: boolean;
    showBlockingReasonSummary: boolean;
    allowBatchAdvance: boolean;
  };
  proseStylePreference: "immersive" | "clear_progression" | "restrained";
  exportFormattingPreference: string;
  updatedAt: string;
};
```

建议接口：

```ts
GET /api/settings/creative-preferences
PUT /api/settings/creative-preferences
```

建议前端封装：

```ts
getCreativePreferences(): Promise<CreativePreferences>
updateCreativePreferences(payload: CreativePreferences): Promise<CreativePreferences>
```

## 状态规则

- 未保存：任意控件变化后显示 `偏好草案`。
- 已保存：保存成功后显示 `已应用`。
- 恢复默认：只重置 UI 偏好，不修改已确认故事数据。
- 容量校验：章节与场景必须保持在 1-20。
- 审阅安全：默认不允许批量进入下一步，默认生成后停在审阅页。

## Codes 接入注意

- 偏好只应作为默认值，不能覆盖用户在具体页面中的显式选择。
- `requested_language` 是目前最明确的真实落点，应接到项目创建入口。
- 章节数和场景数应复用 `storyCapacity.js` 的边界，不能在 UI 内另设上限。
- 草稿快照和用户确认必须区分；自动保存草稿不得触发事实写入。
- `allowBatchAdvance` 默认关闭，除非后续每个模块都有明确的确认与回滚边界。
- 默认写作取向是倾向，不是硬约束；实际生成仍以 Framework、世界设定、角色主轴和场景目标为上位来源。
