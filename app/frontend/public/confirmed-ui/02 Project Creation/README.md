# 02 Project Creation

日期：2026-07-05

状态：已采纳

## 定稿内容

本页是用户在主页点击 `开始创作 -> 新创作` 后进入的项目创建页，页面暂定名为 `新故事档案`。

定稿方向：

- 采用“打开新故事档案”的书页式布局。
- 左侧填写项目名称、语言和可选初始构想。
- 右侧选择创作起点：`空白故事` 或 `从构想开始`。
- 语言选择需要可交互，并同步当前创建摘要。
- 创建流程显示 `请求 -> 草案 -> 确认` 三段状态。
- 本页不再显示右侧流程提示。
- 本页不放 `导入故事 / 故事分析器`、Framework 编排、模板与演示。

## 当前文件

- `project-creation-final-v1.md`
- `visual-drafts/project-creation-final-v1.html`
- `visual-drafts/project-creation-final-v1.png`
- `visual-drafts/project-creation-final-v1-mobile.png`

## 接口方向

本页主要对应：

- `getProjectCreationModes()`
- `createProjectCreationRequest(payload)`
- `validateProjectCreationRequest(creationRequestId)`
- `createProjectCreationDraft(creationRequestId)`
- `confirmProjectCreationDraft(creationDraftId, payload)`

当前 UI 只使用：

- `modeType: "blank_project"`
- `modeType: "prompt_first_project"`
