# 99 Complete UI Designs

本目录用于存放已经采纳、后续可作为 Codes 接入参考的最终 UI 设计归档。

Updated: 2026-07-05

## 当前结构

当前最终归档包含：

- 16 个主线分类：`00 Opening Animation` 到 `15 Settings`。
- 1 个共享产品壳层分类：`16 Global Product Shell`。
- 1 个共享资源目录：`assets`。
- 1 个流程检查工具目录：`_Flow Connection Review`。

旧版 `04 Workbench World Canvas` 已从本目录移除。当前正式世界画布归档以 `09 World Canvas` 为准。

## 当前主分类

| 序号 | 文件夹 | 状态 |
| --- | --- | --- |
| 00 | `00 Opening Animation` | 已采纳 |
| 01 | `01 Main Page` | 已采纳，包含主页与开始创作弹出层 |
| 02 | `02 Project Creation` | 已采纳 |
| 03 | `03 Projects And Works` | 已采纳 |
| 04 | `04 Current Project` | 已采纳 |
| 05 | `05 Template Demo` | 已采纳 |
| 06 | `06 Framework Composition` | 已采纳 |
| 07 | `07 Import Story Analyzer` | 已采纳，作为 Framework 内部分支 |
| 08 | `08 Story Setup` | 已采纳 |
| 09 | `09 World Canvas` | 已采纳 |
| 10 | `10 Character Spine` | 已采纳，包含角色管理补充子流 08-10 |
| 11 | `11 Chapter Planning` | 已采纳 |
| 12 | `12 Scene Writing` | 已采纳，包含高级折叠子流 08-10 |
| 13 | `13 Final Output` | 已采纳 |
| 14 | `14 Plugin Outputs` | 已采纳 |
| 15 | `15 Settings` | 已采纳 |

## 共享壳层

`16 Global Product Shell` 不属于故事生产主线步骤，但属于 Codes 接入时必须参考的全局包装设计：

- `01 Workspace Unavailable State`
- `02 Normal Shell Navigation And Status`

## 使用规则

- 检查全部 UI 顺序和连接时，打开 `_Flow Connection Review/phase8-5-connected-ui-flow-v1.html`。
- 后续 Codes 交接时，以本目录的 00-15 主分类作为最终视觉归档入口。
- 全局导航、模式切换、工作区锁定/不可用等共享行为参考 `16 Global Product Shell`。
- 若主目录中的某页后续继续修改，采纳后需要同步复制到本目录对应分类。
- 专家诊断、Debug Center、Formal Apply、Evidence、Verifier 等内部调试页暂不放入本目录。
- `导入故事 / 故事分析器` 不作为独立主线页；它属于 `06 Framework Composition` 的分支，并归档在 `07 Import Story Analyzer`。
- `记忆与连续性` 不作为独立主线页；它属于 `12 Scene Writing` 的内部锚点/子流程。
