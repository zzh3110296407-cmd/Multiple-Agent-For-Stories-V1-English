# 13 最终输出 / 04 输出设置

日期：2026-07-04

## 设计状态

V1 已生成。该页面是成稿审阅确认后的最终交付设置页，用户侧标题为 `输出设置`。

视觉稿：

```text
visual-drafts/final-output-output-settings-v1.html
visual-drafts/final-output-output-settings-v1.png
visual-drafts/final-output-output-settings-v1-mobile.png
```

背景素材：

```text
../assets/final-output-background-v1.png
```

## 页面目标

该页用于让用户选择最终故事包的下载格式，并确认本次交付文件的包含内容和安全边界。

核心用户任务：

- 选择下载格式：TXT、Markdown、JSON。
- 查看文件名预览、media type、快照 ID、包类型、正文 Hash 和安全审计状态。
- 查看当前格式会包含哪些内容。
- 点击 `下载所选格式` 触发最终故事快照下载。
- 查看本次前端会话的下载反馈记录。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/frontend/src/components/FinalStoryPackageProductView.jsx
app/backend/api/final_story_package.py
app/backend/models/final_story_package.py
app/backend/services/final_story_package_export_service.py
```

主要 helper：

```ts
downloadFinalStoryPackageSnapshot(snapshotId, format)
getFinalStoryPackageSnapshot(snapshotId)
getFinalStoryPackageEvidenceIndex(snapshotId)
getFinalStoryPackageSafetyAudit(snapshotId)
getFinalStoryPackageExportRuns()
getFinalStoryPackageExportRun(exportRunId)
```

主要后端接口：

```text
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=txt
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=markdown
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=json
GET /api/final-story-package/exports
GET /api/final-story-package/exports/{export_run_id}
```

当前 Phase 8.5 已实现下载格式：

```ts
type FinalStoryPackageDownloadFormat = "txt" | "markdown" | "json";
```

`exportFinalStoryPackage(...)` 的 `export_format` 当前模型只支持：

```ts
type ExportFormat = "json_snapshot";
```

因此本页不把 PDF、DOCX、EPUB 做成可点击正式格式。若未来支持，可在该页扩展格式选择区。

## 关键数据字段

`FinalStoryPackageSnapshot`：

```ts
{
  snapshot_id: string;
  project_id: string;
  package_type: "real_project_final_package" | "fixture_final_story_package";
  readiness_status: "ready" | "ready_with_warnings" | "blocked" | "fixture_only";
  snapshot_status: "created" | "fixture" | "blocked";
  complete_story_text: string;
  complete_story_text_hash: string;
  complete_story_text_char_count: number;
  known_residual_codes: string[];
  can_be_used_by_plugins: boolean;
  not_real_project_final_package: boolean;
  safe_summary: string;
}
```

`downloadFinalStoryPackageSnapshot(...)` 成功返回：

```ts
{
  filename: string;
  mediaType: string;
  byteSize: number;
}
```

下载前后端会校验：

```text
snapshot.project_id 必须属于当前项目
snapshot.package_type 必须是真实项目包
snapshot.snapshot_status 必须是 created
complete_story_text 必须存在
complete_story_text_hash 必须匹配正文
complete_story_text_char_count 必须匹配正文长度
```

## UI 映射

- 顶部摘要：
  - 快照类型：`snapshot.package_type`
  - 正文规模：`snapshot.complete_story_text_char_count`
  - 审阅状态：来自 03 页本地确认状态或 viewer state。
- 格式选择：
  - TXT：`downloadFinalStoryPackageSnapshot(snapshotId, "txt")`
  - Markdown：`downloadFinalStoryPackageSnapshot(snapshotId, "markdown")`
  - JSON：`downloadFinalStoryPackageSnapshot(snapshotId, "json")`
- 文件预览：
  - 文件名以下载接口返回的 `filename` 为准。
  - 视觉稿中的文件名只是占位预览。
- 包含内容：
  - TXT：完整正文。
  - Markdown：基础快照元信息 + 完整正文。
  - JSON：完整快照 + preview sections + evidence index + safety audit summary。
- 交付状态：
  - `ready / ready_with_warnings` 可进入下载。
  - `blocked / fixture_only` 应禁用下载，并显示阻塞原因。

## 交互记录

V1 HTML 已实现：

- 点击 TXT / Markdown / JSON 格式卡片切换选中状态。
- 文件名、文件图标、media type 描述和包含内容会随格式切换。
- `复制文件名` 按钮会尝试写入剪贴板，失败时给出前端提示。
- `下载所选格式` 会进入准备进度状态，并在完成后写入本次会话下载记录。
- 阶段提示不是可点击导航。01-04 是最终输出主交付线；05 为导出生成中；06 为下载与归档结果；07 为异常分支。本页只突出 04。
- 右侧展示交付状态、安全边界和下载反馈记录。

## 设计边界

- 本页不出现 `创作路线`。
- 本页不允许修改已确认快照内容。
- 本页不重新生成最终故事包。
- 本页不把下载行为写回故事事实。
- 本页不把 PDF、DOCX、EPUB 做成当前可用下载格式。
- 本页的 `下载所选格式` 接入时应调用下载接口，不应自行拼接或改写正文内容。
- 若后端下载失败，应在主操作区展示错误，并保留当前格式选择，方便用户重试或回到审阅页。
