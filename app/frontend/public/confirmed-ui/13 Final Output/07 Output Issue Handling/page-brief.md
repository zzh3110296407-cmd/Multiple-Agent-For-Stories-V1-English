# 13 最终输出 / 07 输出问题处理

日期：2026-07-04

## 设计状态

V1 已生成。该页面是最终输出模块的统一问题处理层，用户侧标题为 `输出问题处理`。

视觉稿：

```text
visual-drafts/final-output-issue-handling-v1.html
visual-drafts/final-output-issue-handling-v1.png
visual-drafts/final-output-issue-handling-v1-mobile.png
```

背景素材：

```text
../assets/final-output-background-v1.png
```

## 页面目标

该页用于承接最终输出流程中不能继续前进的异常状态，并把用户导回正确的修复入口。

覆盖场景：

- 完成度阻塞：最终故事包 readiness gate 未通过。
- 导出封装失败：最终故事包快照无法生成。
- 下载失败：已确认快照无法生成下载文件。
- 归档索引缺失：下载可能成功，但产品输出库没有找到对应 view。

## 对应 Phase 8.5 接口

前端事实源：

```text
app/frontend/src/api/projectApi.js
app/backend/api/final_story_package.py
app/backend/services/final_story_package_readiness_service.py
app/backend/services/final_story_package_export_service.py
app/backend/api/product_artifacts.py
```

主要 helper：

```ts
getFinalStoryPackageReadiness()
evaluateFinalStoryPackageReadiness(...)
getFinalStoryPackageReadinessGate(readinessGateId)
getFinalStoryPackageReadinessIssues(readinessGateId)
exportFinalStoryPackage({ readinessGateId, allowFixtureExport, exportFormat, safeUserNote })
getFinalStoryPackageExportRuns()
getFinalStoryPackageExportRun(exportRunId)
getFinalStoryPackageSnapshot(snapshotId)
getFinalStoryPackageSnapshotSections(snapshotId)
getFinalStoryPackageEvidenceIndex(snapshotId)
getFinalStoryPackageSafetyAudit(snapshotId)
downloadFinalStoryPackageSnapshot(snapshotId, format)
getProductArtifactLibrary({ projectId })
getProductArtifactEntries({ projectId })
getFinalStoryPackageProductViews({ projectId })
getFinalStoryPackageProductView(viewId, { projectId })
```

## 关键错误语义

完成度阻塞：

```text
FINAL_STORY_PACKAGE_GATE_READINESS_BLOCKED
FINAL_STORY_PACKAGE_READINESS_GATE_NOT_FOUND
FINAL_STORY_PACKAGE_UNSAFE_PAYLOAD_BLOCKED
```

导出封装失败：

```text
FINAL_STORY_PACKAGE_EXPORT_GATE_REQUIRED
FINAL_STORY_PACKAGE_EXPORT_FORMAT_UNSUPPORTED
FINAL_STORY_PACKAGE_EXPORT_SAFETY_AUDIT_FAILED
FINAL_STORY_PACKAGE_EXPORT_FORBIDDEN_STORY_FACT_MUTATION
FINAL_STORY_PACKAGE_EXPORT_BLOCKED
FINAL_STORY_PACKAGE_REAL_EXPORT_NOT_AUTHORIZED
FINAL_STORY_PACKAGE_REAL_EXPORT_WRONG_PACKAGE_TYPE
FINAL_STORY_PACKAGE_EXPORT_NON_TRUTH_SOURCE_REF
FINAL_STORY_PACKAGE_EXPORT_NO_TRUTH_SOURCE_REFS
FINAL_STORY_PACKAGE_EXPORT_COMPLETE_STORY_TEXT_MISSING
FINAL_STORY_PACKAGE_EXPORT_SCENE_NOT_CONFIRMED
FINAL_STORY_PACKAGE_FIXTURE_EXPORT_NOT_ALLOWED
```

下载失败：

```text
FINAL_STORY_PACKAGE_DOWNLOAD_FORMAT_UNSUPPORTED
FINAL_STORY_PACKAGE_DOWNLOAD_NOT_AUTHORIZED
FINAL_STORY_PACKAGE_DOWNLOAD_NOT_REAL_PROJECT_PACKAGE
FINAL_STORY_PACKAGE_DOWNLOAD_SNAPSHOT_NOT_CREATED
FINAL_STORY_PACKAGE_DOWNLOAD_COMPLETE_STORY_TEXT_MISSING
FINAL_STORY_PACKAGE_DOWNLOAD_TEXT_HASH_MISMATCH
FINAL_STORY_PACKAGE_DOWNLOAD_TEXT_COUNT_MISMATCH
```

归档与产品输出库：

```text
FINAL_STORY_PACKAGE_PRODUCT_VIEW_NOT_FOUND
PRODUCT_ARTIFACT_NOT_FOUND
artifact entry missing
```

## UI 映射

- 顶部摘要：
  - 当前问题：由选中的问题类型或当前错误码映射。
  - 影响范围：只影响下载、阻止导出、影响快照生成、只影响入口。
  - 推荐动作：重新下载、回到完成度检查、返回成稿审阅、刷新产品输出库。
- 问题类型列表：
  - 下载校验异常。
  - 完成度阻塞。
  - 导出封装失败。
  - 归档索引缺失。
- 问题详情：
  - 错误码。
  - 严重程度。
  - 影响范围。
  - 可恢复性。
  - 用户可理解的解释。
- 证据与定位：
  - 对应 API。
  - 常见错误。
  - 前端状态来源。
- 处理路径：
  - 保留当前上下文重试。
  - 返回对应页面修复。
  - 重新拉取快照、导出记录或产品输出库索引。
- 右侧建议动作：
  - 主动作：根据问题类型变化。
  - 次动作：保留状态返回。
  - 查看导出记录：读取 `getFinalStoryPackageExportRuns()`。

## 交互记录

V1 HTML 已实现：

- 点击 `下载校验异常 / 完成度阻塞 / 导出封装失败 / 归档索引缺失` 会切换问题详情、证据、处理路径和右侧建议动作。
- 点击 `复制诊断信息` 会复制当前问题标题、错误码和影响范围。
- 点击主动作按钮会根据当前问题展示对应动作提示。
- 点击次动作按钮会根据当前问题展示对应动作提示。
- 点击 `查看导出记录` 会提示正式接入时读取 `getFinalStoryPackageExportRuns()`。
- 顶部 `01 / 02 / 03 / 04 / 05 / 06 / 07` 是流程阶段提示，不是按钮。

## 设计边界

- 本页不出现 `创作路线`。
- 本页不直接修复故事事实。
- 本页不自动重写正文、不自动确认场景、不自动修改世界/角色/章节计划。
- 本页只负责定位问题、解释影响、提供回到正确修复入口的动作。
- 下载类错误可以留在最终输出模块内重试。
- readiness 阻塞必须回到完成度检查或对应源模块处理。
- 归档索引缺失不是独立写入动作，优先重新读取产品输出库索引。

## Codes 接入建议

推荐组件名：

```ts
FinalOutputIssueHandlingView
```

推荐问题类型：

```ts
type FinalOutputIssueKind =
  | "download_validation"
  | "readiness_blocked"
  | "export_failed"
  | "archive_index_missing";
```

推荐状态：

```ts
type FinalOutputIssueState = {
  kind: FinalOutputIssueKind;
  code: string;
  message: string;
  source:
    | "readiness"
    | "export"
    | "download"
    | "product_artifact";
  severity: "low" | "medium" | "high";
  snapshotId?: string;
  exportRunId?: string;
  readinessGateId?: string;
  artifactEntryId?: string;
  productViewId?: string;
  selectedFormat?: "txt" | "markdown" | "json";
  recoverable: boolean;
};
```

推荐事件：

```ts
onSelectIssue(kind: FinalOutputIssueKind): void
onRetryDownload(format?: "txt" | "markdown" | "json"): Promise<void>
onReevaluateReadiness(readinessGateId?: string): Promise<void>
onBackToCompletionCheck(): void
onBackToManuscriptReview(): void
onBackToOutputSettings(): void
onRefreshProductOutputLibrary(): Promise<void>
onOpenExportRuns(): void
onCopyDiagnostic(issue: FinalOutputIssueState): Promise<void>
```

错误码到问题类型的建议映射：

```ts
function mapFinalOutputIssue(code: string): FinalOutputIssueKind {
  if (code.includes("DOWNLOAD")) return "download_validation";
  if (code.includes("READINESS") || code.includes("GATE")) return "readiness_blocked";
  if (code.includes("PRODUCT_VIEW") || code.includes("ARTIFACT")) return "archive_index_missing";
  return "export_failed";
}
```

无障碍要求：

- 问题类型必须使用 button 或 listbox option，并支持键盘焦点。
- 错误变化区域应使用 `aria-live` 或由状态提示承接。
- 所有错误码、snapshot id、artifact id 必须允许换行。
- 主动作按钮必须根据问题类型改变文案，避免用户误以为所有问题都能靠重试解决。
