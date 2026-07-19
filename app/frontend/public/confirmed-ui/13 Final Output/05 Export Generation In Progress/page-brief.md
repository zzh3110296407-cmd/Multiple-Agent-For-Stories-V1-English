# 13 最终输出 / 05 导出生成中

日期：2026-07-04

## 设计状态

V1 已生成。该页面是用户在 `04 输出设置` 中点击下载后出现的过渡页，用户侧标题为 `导出生成中`。

视觉稿：

```text
visual-drafts/final-output-export-generation-v1.html
visual-drafts/final-output-export-generation-v1.png
visual-drafts/final-output-export-generation-v1-mobile.png
```

背景素材：

```text
../assets/final-output-background-v1.png
```

## 页面目标

该页用于让用户清楚知道最终交付文件正在生成和准备下载，避免点击下载后无反馈。

核心用户任务：

- 查看导出生成进度。
- 查看当前下载格式、快照 ID、media type 和预期文件名。
- 查看后端校验链路：读取快照、校验正文、组装文件、准备下载。
- 在等待期间可查看步骤说明。
- 生成完成后进入后续交付结果页；失败时返回输出设置页重试。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/backend/api/final_story_package.py
app/backend/services/final_story_package_export_service.py
```

主要 helper：

```ts
downloadFinalStoryPackageSnapshot(snapshotId, format)
```

主要后端接口：

```text
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=txt
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=markdown
GET /api/final-story-package/snapshots/{snapshot_id}/download?format=json
```

当前 Phase 8.5 的下载接口是同步请求并返回 blob，不是后端长任务。因此本页建议作为前端 promise 可视化层：

```ts
setExportUiState("generating");
try {
  const result = await downloadFinalStoryPackageSnapshot(snapshotId, selectedFormat);
  setExportUiState("success", result);
} catch (error) {
  setExportUiState("error", error);
}
```

## 关键数据字段

页面入口参数：

```ts
{
  snapshotId: string;
  selectedFormat: "txt" | "markdown" | "json";
  packageType: "real_project_final_package" | "fixture_final_story_package";
  storyCharCount: number;
  completeStoryTextHash: string;
}
```

下载成功返回：

```ts
{
  filename: string;
  mediaType: string;
  byteSize: number;
}
```

下载失败可见错误：

```ts
{
  message: string;
  status?: number;
  code?: string;
}
```

需要重点处理的后端失败语义：

```text
FINAL_STORY_PACKAGE_DOWNLOAD_FORMAT_UNSUPPORTED
FINAL_STORY_PACKAGE_DOWNLOAD_NOT_AUTHORIZED
FINAL_STORY_PACKAGE_DOWNLOAD_NOT_REAL_PROJECT_PACKAGE
FINAL_STORY_PACKAGE_DOWNLOAD_SNAPSHOT_NOT_CREATED
FINAL_STORY_PACKAGE_DOWNLOAD_COMPLETE_STORY_TEXT_MISSING
FINAL_STORY_PACKAGE_DOWNLOAD_TEXT_HASH_MISMATCH
FINAL_STORY_PACKAGE_DOWNLOAD_TEXT_COUNT_MISMATCH
```

## UI 映射

- 顶部摘要：
  - 导出格式：来自 04 页选择的 `selectedFormat`。
  - 正文规模：`snapshot.complete_story_text_char_count`。
  - 快照状态：由 03 页确认状态和 `snapshot.snapshot_status` 共同决定。
- 中央封装动画：
  - 表示下载请求正在进行。
  - 不表示模型正在重新写作。
- 进度条：
  - 当前动态稿为前端模拟。
  - 正式接入时可以映射为 promise 阶段：request sent / response headers / blob received / download triggered。
- 生成链路：
  - 读取快照：确认 snapshot_id。
  - 校验正文：校验正文存在、Hash 和字符数。
  - 组装文件：按 `txt / markdown / json` 生成下载内容。
  - 准备下载：读取 `Content-Disposition`、blob 和 media type。
- 右侧运行边界：
  - 只读快照。
  - 格式受限。
  - 失败可恢复。

## 交互记录

V1 HTML 已实现：

- 页面加载后自动推进导出生成进度。
- 中央文件封装动画和进度条同步变化。
- 生成链路步骤会根据进度自动切换。
- 点击任一步骤会显示该步骤的接口说明。
- 右侧生成日志随进度写入。
- 进度结束后主按钮从 `等待生成完成` 变为 `进入交付结果`。
- `返回设置` 和 `返回输出设置` 会给出前端提示。
- 阶段提示不是可点击导航。01-04 是最终输出主交付线；05 为导出生成中；06 为下载与归档结果；07 为异常分支。本页只突出 05。

## 设计边界

- 本页不出现 `创作路线`。
- 本页不重新生成最终故事包。
- 本页不修改已确认快照。
- 本页不修改故事正文、设定、角色或插件运行数据。
- 本页不提供格式选择；格式选择在 04 输出设置页完成。
- 本页的进度不应伪造后端真实百分比；若后端没有进度事件，应使用阶段型进度或不确定进度。
- 若下载成功，应进入后续交付结果页，展示 filename、mediaType、byteSize 和重新下载入口。
- 若下载失败，应展示错误原因，并允许用户返回 04 输出设置保留当前格式重新尝试。
