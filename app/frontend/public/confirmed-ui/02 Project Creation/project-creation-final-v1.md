# Project Creation UI

日期：2026-07-05

状态：已采纳

## 当前定位

项目创建页承接主页的 `开始创作 -> 新创作`。它只负责创建新项目档案，不承担后续故事生产路线展示。

## 当前设计

- 页面采用书页式布局，左侧为档案信息，右侧为创建摘要与创建动作。
- 用户填写项目名称、选择语言，并可选填写初始构想。
- 用户选择 `空白故事` 或 `从构想开始`。
- 语言选择为真实交互，会同步摘要与占位文案。
- 创建摘要保留 `请求 -> 草案 -> 确认` 状态。
- 右下动作按钮根据标题、模式和输入内容更新。
- 右侧流程提示已从本页移除。

## 文件

- `visual-drafts/project-creation-final-v1.html`
- `visual-drafts/project-creation-final-v1.png`
- `visual-drafts/project-creation-final-v1-mobile.png`

## 后续连接

- `空白故事` 创建完成后进入 `04 Current Project`。
- `从构想开始` 创建完成后可以进入 `08 Story Setup`。
- 继续/历史/作品列表不属于本页，由 `03 Projects And Works` 承接。
