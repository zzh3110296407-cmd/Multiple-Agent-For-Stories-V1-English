# 07es Branch / 分析中 UI V1

Date: 2026-07-03

## 页面定位

分析中是导入源之后的处理中状态。它承接用户在导入源页点击“开始分析”后的过渡，展示 Analyze Stories 对导入记录进行解析、校验、报告提取和候选预检的过程。

该页不提供 Framework 回写入口。只有分析完成并进入后续结果页后，用户才会继续审阅报告、Framework 候选和导入编辑会话。

## 页面结构

1. 顶部
   - 返回导入源
   - 面包屑：主页 / 当前项目 / Framework 编排 / 导入源 / 分析中
   - 分析日志按钮

2. 左侧：导入记录
   - 作品名
   - 文件名
   - 识别类型
   - 导入 ID
   - 当前状态

3. 中间：分析核心
   - 进度百分比
   - 当前阶段标题
   - 动态扫描层
   - 阶段轨道：
     - 接收记录
     - 解析结构
     - 提取报告
     - 校验边界
     - 生成候选

4. 右侧：输出队列
   - 导入记录
   - 校验报告
   - 报告引用
   - Framework 候选
   - 底部动作：暂停 / 继续、后台继续、查看结果

5. 抽屉
   - 分析日志
   - 点击“分析日志”打开
   - 阶段推进时追加记录

## 交互

- 页面载入后进度自动推进。
- 阶段轨道可点击，点击后切换到对应阶段。
- “暂停”会停止进度，并切换为“继续”。
- “后台继续”只保留当前任务，返回 Framework 分支时不改变分析状态。
- “查看结果”在进度完成后解锁。
- “分析日志”抽屉可打开/关闭。

## Phase 8.5 接口映射

分析中本身不是独立后端实体，而是前端围绕导入动作和导入记录状态渲染的进行态。

触发来源：

```ts
POST /api/analyze-stories/imports
body: {
  declared_file_kind?: string | null;
  original_filename?: string | null;
  artifact: Record<string, unknown>;
}
```

前端当前动作：

```ts
analyzeStoriesAction === "import"
```

动作完成后刷新：

```ts
GET /api/analyze-stories/imports
GET /api/analyze-stories/imports/{import_id}
GET /api/analyze-stories/framework-candidates
GET /api/analyze-stories/report-viewers
GET /api/analyze-stories/bundles
GET /api/analyze-stories/adapter-derivations
GET /api/analyze-stories/adapter-candidates
```

页面主要读取字段：

```ts
type AnalyzingViewState = {
  action: "import" | "refresh" | "idle" | "error";
  importId?: string;
  sourceTitle?: string;
  originalFilename?: string;
  declaredFileKind?: string;
  progressStage:
    | "received"
    | "parsing"
    | "report_extracting"
    | "validating"
    | "candidate_preflight"
    | "complete"
    | "blocked";
  manifest?: {
    import_status: "received" | "parsed" | "validated_with_warnings" | "blocked" | "ready_for_m2";
    parse_status: "not_parsed" | "parsed" | "parse_failed";
    file_kinds: string[];
    story_analysis_report_ref_ids: string[];
  };
  artifact?: {
    file_kind: string;
    raw_storage_status: "stored" | "redacted" | "hash_only" | "blocked";
    parse_status: "not_parsed" | "parsed" | "parse_failed";
    content_length: number;
    safe_summary: string;
  };
  validationReport?: {
    passed: boolean;
    can_proceed_to_m2: boolean;
    blocking_issues: Array<{ code: string; message: string }>;
    warnings: Array<{ code: string; message: string }>;
    detected_file_kinds: string[];
    requires_user_confirmation: boolean;
  };
}
```

状态映射建议：

- `analyzeStoriesAction === "import"`：显示分析中。
- `manifest.import_status === "received"`：接收记录。
- `manifest.parse_status === "not_parsed"`：解析结构。
- `manifest.parse_status === "parsed"`：提取报告或校验边界。
- `validation_report.passed === true && can_proceed_to_m2 === true`：可进入结果页。
- `manifest.import_status === "validated_with_warnings"`：完成但带警告，结果页需要警告入口。
- `manifest.import_status === "blocked"` 或 `blocking_issues.length > 0`：进入问题处理层。
- `manifest.parse_status === "parse_failed"`：进入问题处理层。

## 可视化稿

- `visual-drafts/analyzing-v1.html`
- `visual-drafts/analyzing-v1.png`
