# 05 模板与演示 UI V1

日期：2026-07-02

## 状态

V1 可视化稿。

## 页面定位

`05 模板与演示` 是模板和演示样本的安全中转页。它承接当前项目总览里的 `模板与演示` 工作区，并与后续 `Framework` 编排衔接。

本页重点不是展示大量模板，而是让用户明确：

- 模板可以成为真实项目的结构起点。
- 模板实例化只生成起始材料、实例化报告和交接信息，不直接确认故事事实。
- 演示样本只在隔离区运行，不能直接转换成真实故事项目。

## V1 页面结构

- 顶部：返回当前项目、面包屑、当前项目来源状态。
- 左侧：模板馆，展示可选模板、状态、推荐入口和安全预览。
- 中部：模板实例化流程，展示 `选择模板 -> 创建请求 -> 验证 -> 起始材料 -> Framework`。
- 右侧：演示隔离柜，展示演示样本、运行记录和隔离审计。
- 底部：安全边界提示，说明模板和演示不会直接写入已确认故事事实。

## 交互

- 点击模板卡：切换模板详情、适用方向和流程状态。
- 点击实例化流程节点：聚焦当前阶段。
- 点击演示样本：切换演示隔离信息。
- 点击主 CTA：提示进入 `Framework`，后续 Codes 接入 `onNavigateWorkspace("framework")`。

## 接口对接方向

后续 Codes 接入时：

- 模板列表来自 `getProjectTemplates()`。
- 模板详情来自 `ProjectTemplate`。
- 实例化请求来自 `createTemplateInstantiationRequest(templateId, payload)`。
- 验证来自 `validateTemplateInstantiationRequest(templateInstantiationRequestId)`。
- 起始材料生成来自 `instantiateTemplateRequest(templateInstantiationRequestId)`。
- 实例化结果来自 `TemplateInstantiationReport`。
- 演示列表来自 `getDemoSeeds()`。
- 演示运行来自 `runDemoSeed(demoSeedId, payload)`。
- 隔离审计来自 `createDemoSeedIsolationAudit(demoSeedRunId)`。
- 项目来源来自 `getProjectOriginBadge(projectId)`。

## 关键约束

- 默认目标工作区应对齐最新主线：`Framework` 在 `世界画布` 之前。
- 演示区不能表现成真实项目模板。
- 普通用户 UI 不显示 raw payload、trace、hidden reasoning、provider response。
- 若 `TemplateInstantiationValidationReport.can_instantiate` 为 `false`，生成起始材料按钮必须禁用，并显示阻塞原因。

## 可视化稿

- `visual-drafts/template-demo-v1.html`
- `visual-drafts/template-demo-v1.png`
