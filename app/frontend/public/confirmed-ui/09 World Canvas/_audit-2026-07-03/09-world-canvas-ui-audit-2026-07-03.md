# 09 世界画布 UI 审查记录

审查日期：2026-07-03

审查对象：`09 World Canvas` 已确认的 6 个页面与关键交互状态。

## 审查结论

09 世界画布 UI 当前可以通过。

已检查并确认：

- 信息流程和 Phase 8.5 的世界画布流程一致：来源前提、生成草案、草案审阅、缺口与冲突处理、修订草案、确认世界事实。
- 页面不再使用旧版右侧创作路线组件。
- 用户可见文本没有泄露后端调试字段或 raw API 字段。
- 1440x1100 与 1366x768 视口下没有横向溢出。
- 关键按钮、Tab、筛选、确认勾选、完成态切换均可触发。
- 视觉风格保持统一：制图桌面背景、米白纸面、墨绿色状态、陶土色主按钮。

## 本次修复

修复了 `02 Generating` 页面的一处动态稿脚本问题：

- 文件：`02 Generating/visual-drafts/world-canvas-generating-v1.html`
- 问题：生成进度到达最后一步后，定时器仍可能继续推进，导致读取不存在的步骤并触发运行错误。
- 处理：增加定时器边界检查，到达最后一步后立即停止；测试辅助函数设置到完成态时也会停止定时器。

## 接口与数据对齐

后续接入时应继续对齐现有世界画布接口：

- 生成草案：`POST /api/world-canvas/generate`
  - body：`{ story_idea: string }`
- 读取当前画布：`GET /api/world-canvas/current`
- 修订草案：`POST /api/world-canvas/revise`
  - body：`{ revision_prompt: string }`
- 确认保存：`POST /api/world-canvas/confirm`
  - body：`{ user_input?: string }`

UI 需要读取或映射的核心结果：

- `world_canvas`
- `validation`
- `decision`

UI 展示层应把后端字段翻译成用户可理解内容，不直接显示字段名。

## 审查覆盖

| 页面 | 默认状态 | 关键交互状态 | 结果 |
| --- | --- | --- | --- |
| 01 来源前提与生成入口 | 已审 | Tab 切换、输入、生成提交态 | 通过 |
| 02 生成中 | 已审 | 自动进度、完成态、查看草案入口 | 修复后通过 |
| 03 草案审阅 | 已审 | 模块切换、规则筛选、冲突筛选 | 通过 |
| 04 缺口与冲突处理 | 已审 | 问题筛选、问题详情、全部处理完成态 | 通过 |
| 05 修订草案 | 已审 | 上下文切换、修订范围、修订重点、完成态 | 通过 |
| 06 确认世界事实 | 已审 | 规则分层、下游读取、确认清单、写入完成态 | 通过 |

## 审查证据

自动审查结果：

- `playwright-audit-results.json`

截图证据目录：

- `screenshots/01-default-1440.png`
- `screenshots/01-terms-1440.png`
- `screenshots/01-submitted-1440.png`
- `screenshots/01-responsive-1366.png`
- `screenshots/02-default-1440.png`
- `screenshots/02-complete-1440.png`
- `screenshots/02-responsive-1366.png`
- `screenshots/03-default-1440.png`
- `screenshots/03-rules-conflict-1440.png`
- `screenshots/03-responsive-1366.png`
- `screenshots/04-default-1440.png`
- `screenshots/04-logic-detail-1440.png`
- `screenshots/04-resolved-1440.png`
- `screenshots/04-responsive-1366.png`
- `screenshots/05-default-1440.png`
- `screenshots/05-configured-1440.png`
- `screenshots/05-complete-1440.png`
- `screenshots/05-responsive-1366.png`
- `screenshots/06-default-1440.png`
- `screenshots/06-rules-1440.png`
- `screenshots/06-downstream-1440.png`
- `screenshots/06-ready-1440.png`
- `screenshots/06-complete-1440.png`
- `screenshots/06-responsive-1366.png`

## 残余风险

- 当前审查对象是 UI 设计静态稿和本地交互动效，不是已经接入后端的真实 React 页面。
- 键盘焦点顺序和屏幕阅读器体验只做了基础结构检查，正式接入时还需要在项目真实组件中做一次可访问性复核。
- 页面跳转现在以 toast 或静态状态表达，正式接入时需要 Codes 把这些动作接到实际路由和接口状态机。

## 交接建议

Codes 接入时应按 6 个状态拆分世界画布 UI 状态机，而不是把所有内容塞进单页长表单：

1. 来源前提可编辑。
2. 生成中锁定重复提交。
3. 草案审阅按模块展示。
4. 缺口与冲突处理只写回草案审阅结果。
5. 修订草案只影响当前草案版本。
6. 确认世界事实后才允许下游模块读取。
