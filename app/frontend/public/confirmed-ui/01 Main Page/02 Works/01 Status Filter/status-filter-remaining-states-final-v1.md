# Status Filter Remaining States v1

日期：2026-06-19

## 当前状态

已采纳定稿 v1。用于补齐 W-I-01 `状态筛选` 中除 `进行中` 之外的三个状态：

- 已完成
- 暂停
- 归档

这些稿件已收入 `99 Complete/01 Main Page/02 Works/01 Status Filter`。

## 当前视觉稿

```text
visual-drafts/status-filter-active-completed-v1.svg
visual-drafts/status-filter-active-completed-v1.png
visual-drafts/status-filter-active-paused-v1.svg
visual-drafts/status-filter-active-paused-v1.png
visual-drafts/status-filter-active-archived-v1.svg
visual-drafts/status-filter-active-archived-v1.png
```

## 共同交互规则

三张稿件复用 W-I-01 已采纳的状态筛选规则：

- 点击某个状态后，左侧对应状态进入选中态。
- 中间作品卡片只显示该状态下的作品。
- 当前状态和数量只在页面副标题中呈现，不在卡片区左上方显示小标题。
- 第一条结果自动成为右侧 `当前选中`。
- 单击作品卡片更新右侧预览。
- 双击作品卡片进入作品详情。
- 点击 `全部故事` 清除状态筛选。

## 已完成状态

代表数据：

```text
已完成 · 3 部
```

视觉策略：

- 使用偏冷的灰绿色作为状态强调色。
- 显示 3 张已完成作品卡片。
- 第 4 个卡位显示低饱和占位：`已显示全部 3 部已完成故事`。
- 右侧预览展示完成度 100%、可导出、完结校订完成等信息。

## 暂停状态

代表数据：

```text
暂停 · 2 部
```

视觉策略：

- 使用低亮金褐色作为状态强调色。
- 显示 2 张暂停作品卡片。
- 后两个卡位保留柔和空白占位，避免两张卡之后页面突然空掉。
- 右侧预览强调暂停原因，例如冲突清单、角色关系待确认、时间线待校对。

## 归档状态

代表数据：

```text
归档 · 2 部
```

视觉策略：

- 使用低亮灰褐色作为状态强调色。
- 显示 2 张归档作品卡片。
- 后两个卡位保留柔和空白占位。
- 右侧预览保留 `详情` 入口；归档作品是否允许 `继续`，后续可在作品详情页策略中再定。

## 数据行为

三种状态都复用 W-I-01 的筛选逻辑：

```ts
type StoryStatus = "all" | "active" | "completed" | "paused" | "archived";

interface WorksFilterState {
  status: StoryStatus;
  genre: string | null;
  searchQuery: string;
  selectedStoryId: string | null;
}
```

状态映射建议：

```ts
const statusLabelMap: Record<Exclude<StoryStatus, "all">, string> = {
  active: "进行中",
  completed: "已完成",
  paused: "暂停",
  archived: "归档",
};
```

## 待讨论

- `暂停` 和 `归档` 数量较少时，是否保留柔和空白占位。
- `归档` 作品右侧主按钮是否仍显示 `继续`，还是改为 `恢复` / 禁用继续。
- `已完成` 作品是否仍允许 `继续`，还是主按钮改成 `查看`。
