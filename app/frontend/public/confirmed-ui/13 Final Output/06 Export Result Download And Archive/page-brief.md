# 13 最终输出 / 06 下载与归档

日期：2026-07-04

## 设计状态

V1 已生成。该页面承接 `05 导出生成` 成功后的结果状态，用户侧标题为 `下载与归档`。

视觉稿：

```text
visual-drafts/final-output-export-result-v1.html
visual-drafts/final-output-export-result-v1.png
visual-drafts/final-output-export-result-v1-mobile.png
```

背景素材：

```text
../assets/final-output-background-v1.png
```

## 页面目标

该页用于告诉用户最终故事包已经完成交付，并提供重新下载、查看归档索引、进入产品输出库和返回作品集索引的入口。

核心用户任务：

- 查看本次导出的文件名、格式、media type、文件大小。
- 重新下载 TXT、Markdown、JSON 格式。
- 查看最终故事包在产品输出库中的归档索引。
- 打开产品输出库查看最终故事包视图、权威标识、预览与安全摘要。
- 返回作品集索引或输出设置。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/backend/api/final_story_package.py
app/backend/services/final_story_package_export_service.py
```

主要下载 helper：

```ts
downloadFinalStoryPackageSnapshot(snapshotId, format = "txt")
```

主要下载接口：

```text
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=txt
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=markdown
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=json
```

下载成功返回：

```ts
{
  filename: string;
  mediaType: string;
  byteSize: number;
}
```

最终故事包与归档查看相关 helper：

```ts
getFinalStoryPackageExportRuns()
getFinalStoryPackageExportRun(exportRunId)
getFinalStoryPackageSnapshot(snapshotId)
getFinalStoryPackageSnapshotSections(snapshotId)
getFinalStoryPackageEvidenceIndex(snapshotId)
getFinalStoryPackageSafetyAudit(snapshotId)
getProductArtifactLibrary({ projectId })
getProductArtifactEntries({ projectId })
getProductArtifactEntry(artifactEntryId, { projectId })
getProductArtifactAuthorityBadge(artifactEntryId, { projectId })
getProductArtifactSafePreview(artifactEntryId, { projectId })
getProductArtifactSafetySummary(artifactEntryId, { projectId })
getFinalStoryPackageProductViews({ projectId })
getFinalStoryPackageProductView(viewId, { projectId })
```

## 关键数据字段

页面入口参数：

```ts
{
  snapshotId: string;
  exportRunId: string;
  artifactEntryId?: string;
  finalStoryPackageViewId?: string;
  selectedFormat: "txt" | "markdown" | "json";
  filename: string;
  mediaType: string;
  byteSize: number;
  packageType: "real_project_final_package" | "fixture_final_story_package";
}
```

归档状态建议由以下数据共同决定：

```ts
{
  exportRun: FinalStoryPackageExportRun;
  snapshot: FinalStoryPackageSnapshot;
  productArtifactLibrary: {
    final_story_package_views: FinalStoryPackageProductView[];
  };
  artifactEntry?: ProductArtifactEntry;
}
```

## UI 映射

- 顶部摘要：
  - 下载格式：当前选择或最近一次重新下载的格式。
  - 文件大小：`downloadFinalStoryPackageSnapshot` 返回的 `byteSize`。
  - 归档状态：当 `final_story_package_views` 存在对应 snapshot 时显示 `已入库`。
- 主文件卡片：
  - 文件名：`filename`。
  - media type：`mediaType`。
  - Snapshot ID：`snapshotId`。
  - Export Run：`exportRunId`。
  - Package Type：`packageType`。
- 重新下载按钮：
  - TXT 对应 `format = "txt"`。
  - Markdown 对应 `format = "markdown"`。
  - JSON 对应 `format = "json"`。
- 归档索引：
  - 产品输出库条目对应 `artifactEntryId`。
  - 最终故事包视图对应 `finalStoryPackageViewId`。
  - 只读交付边界说明提醒 Codes 不要把归档设计成新写入接口。
- 侧边栏：
  - 展示正文规模、章节数量、导出格式、快照状态。
  - 入口包括产品输出库、作品集索引、输出设置。

## 交互记录

V1 HTML 已实现：

- 点击 `下载 TXT`、`下载 Markdown`、`下载 JSON` 会切换当前格式、文件名、media type、文件大小和交付记录。
- 点击 `复制文件名` 会调用 Clipboard API，失败时给出本地提示。
- 点击 `打开产品输出库` 会提示正式接入时读取 final story package views 与 artifact entry。
- 点击 `返回作品集索引` 会提示正式接入时进入作品集或历史创作列表。
- 点击 `返回输出设置` 会提示正式接入时回到 04 输出设置页，并保留快照与格式选择。
- 阶段提示不是按钮。01-04 是最终输出主交付线；05 为导出生成中；06 为下载与归档结果；07 为异常分支。本页只突出 06。

## 设计边界

- 本页不出现 `创作路线`。
- 本页不重新生成故事正文。
- 本页不修改世界事实、角色事实、章节计划或场景正文。
- 本页不把 `归档` 设计成独立写入动作。归档是最终故事包导出后，在产品输出库和 final story package view 中可见的状态。
- 本页允许重新下载不同格式，但所有重新下载都应通过 `downloadFinalStoryPackageSnapshot(snapshotId, format)` 读取同一个已确认快照。
- 若重新下载失败，应展示错误原因，并允许用户返回 `04 输出设置` 或停留在本页重试。

## Codes 接入建议

建议把该页面作为 `FinalOutputDeliveryResult` 或最终输出工作台内的成功状态视图。

推荐状态机：

```ts
type FinalOutputDownloadState =
  | { status: "idle"; selectedFormat: "txt" | "markdown" | "json" }
  | { status: "downloading"; selectedFormat: "txt" | "markdown" | "json" }
  | {
      status: "success";
      selectedFormat: "txt" | "markdown" | "json";
      filename: string;
      mediaType: string;
      byteSize: number;
    }
  | {
      status: "error";
      selectedFormat: "txt" | "markdown" | "json";
      message: string;
      code?: string;
    };
```

推荐事件：

```ts
onDownload(format: "txt" | "markdown" | "json"): Promise<void>
onCopyFilename(filename: string): Promise<void>
onOpenProductOutputLibrary(): void
onOpenCollectionIndex(): void
onBackToOutputSettings(): void
```

无障碍要求：

- 所有交互必须使用 button。
- 重新下载过程中按钮应进入 `aria-busy` 或禁用态，避免重复触发。
- 文件名和 artifact id 必须允许自动换行，避免长 ID 撑破容器。
- 下载失败时错误提示要进入 `aria-live` 区域。
