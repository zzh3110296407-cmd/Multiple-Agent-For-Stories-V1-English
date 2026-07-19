# Phase 8.5 Connected UI Flow Review

用途：把 `99 Complete` 中所有最终 UI HTML 原型与 SVG 静态稿连接成一个可点击的流程检查器，方便检查顺序、分支、交互跳转和接口映射是否通顺。

## 入口

```text
phase8-5-connected-ui-flow-v1.html
```

## 当前能力

- 左侧为完整流程目录，可按全部、主线、分支、子流程、静态稿、壳层、设置筛选。
- 右侧 iframe 预览当前 UI 页面。
- 顶部提供上一页、下一页、打开当前页。
- “本页交互”面板列出当前页面的用户动作、Phase 8.5 前端 action、对应 API 或 workspace，并可点击跳到目标页面锚点。
- 地址哈希会记录当前步骤，例如 `#step-23`。

## 接口契约

接口和工作区映射见：

```text
..\_Integration Contract\phase8-5-ui-interface-contract-2026-07-05.md
..\_Integration Contract\phase8-5-ui-interface-map-v1.json
```

## 连接原则

- 不修改单页最终稿，只用 iframe 引用现有 HTML/SVG。
- 开场动画保留在流程清单中，但默认打开“主页 / 开始创作弹出层”，方便检查主流程。
- `projects` 在 Phase 8.5 前端中与 `create_project` 共用 `route_key: project`，03 项目列表是 UI 设计侧拆出的用户体验页。
- `memory_continuity` 在 Phase 8.5 前端中使用 `route_key: scene`，设计上归入 12 场景写作。
- 重复标题跳转必须提供 `targetGroup`，例如“缺失信息处理”。

## 当前主线顺序

1. 开场动画
2. 主页 / 开始创作弹出层
3. 项目创建 / 项目列表
4. 当前项目总览
5. 模板与演示
6. Framework 编排
7. 导入故事 / 故事分析器分支
8. 故事设定
9. 世界画布
10. 角色主轴与角色管理子流
11. 章节计划
12. 场景写作与高级折叠子流
13. 最终输出
14. 插件输出
15. 设置
16. 全局产品壳层参考

## 后续调整方式

如果发现顺序不对、连接不顺或某页应调整为分支/主线，直接指出连接器左侧步骤编号、页面标题和目标调整即可。修改时同步更新 `FLOW`、`ACTIONS_BY_TITLE` 和 `_Integration Contract`。
