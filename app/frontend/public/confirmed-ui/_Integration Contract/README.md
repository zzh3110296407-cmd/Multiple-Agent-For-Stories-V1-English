# Phase 8.5 UI Integration Contract

用途：记录当前 UI 最终稿与 Phase 8.5 项目前端接口的对接关系，后续 Codes 接入项目主体时以这里为 UI 侧交接入口。

## 文件

- `phase8-5-ui-interface-contract-2026-07-05.md`：人工可读的完整对接契约。
- `phase8-5-ui-interface-map-v1.json`：按工作区整理的机器可读接口索引。

## 源码依据

本契约只读取项目最新版源码，不修改项目主体：

- `app/frontend/src/App.jsx`
- `app/frontend/src/api/projectApi.js`
- `app/frontend/src/views/*.jsx`
- `app/backend/services/product_navigation_service.py`

总流程可视化入口：

```text
..\_Flow Connection Review\phase8-5-connected-ui-flow-v1.html
```

该连接器已加入“本页交互”面板，按钮会按 UI 流程跳转到对应页面锚点，并显示 Phase 8.5 的前端 action/API 对应关系。
