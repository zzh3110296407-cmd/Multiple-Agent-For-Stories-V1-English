# W-I-02 Genre Filter

日期：2026-06-19

## 当前状态

已采纳定稿 v1。此交互已收入 `99 Complete`。

## 交互目标

用户点击左侧 `题材` 分类后，作品集页面在当前页面内完成题材筛选，不跳转新页面。

本次先实现代表题材：

```text
城市悬疑
```

四个题材共用同一套交互规则：

- 奇幻史诗
- 城市悬疑
- 温柔日常
- 科幻远征

## 当前视觉稿

```text
genre-filter-active-city-mystery-final-v1.svg
genre-filter-active-city-mystery-final-v1.png
```

## v1 视觉规则

- `城市悬疑` 进入选中态：浅纸色底、左侧竖向色条、低亮灰褐描边。
- 状态区仍保留 `全部故事` 选中，表示没有额外状态筛选。
- 页面副标题同步变为 `筛选：城市悬疑 · 四部故事藏在雾里`。
- 不再显示卡片区左上方的筛选摘要小标题。
- 中间卡片区只显示 `城市悬疑` 题材作品。
- 卡片状态可以混合出现：进行中、已完成、暂停、归档都可以留在结果里。
- 第一张作品卡默认被选中，使用更明显的描边和阴影。
- 右侧 `当前选中` 自动同步为筛选结果中的第一部作品。
- 右侧 `最近节点` 和 `进度元数据` 仍保持展示状态，不做可点击入口。

## 交互规则

| 操作 | 页面反应 |
| --- | --- |
| 点击 `城市悬疑` | 激活该题材筛选，中间卡片只保留城市悬疑作品，右侧选择第一条结果 |
| 点击其它题材 | 替换当前题材筛选，复用同一视觉规则 |
| 点击 `全部故事` | 只清除状态筛选；如果题材仍被选中，继续保留题材筛选 |
| 再次点击已选题材 | 建议清除题材筛选，恢复当前状态筛选下的作品列表 |
| 单击作品卡片 | 选中作品，右侧预览更新 |
| 双击作品卡片 | 进入作品详情页 |
| 点击右侧 `详情` | 进入作品详情页 |
| 点击右侧 `继续` | 进入对应作品工作台 |

## 与状态筛选的组合关系

题材筛选和状态筛选可以组合。比如：

```text
状态：进行中
题材：城市悬疑
```

此时中间卡片只显示 `进行中 + 城市悬疑` 的交集结果。

## 数据行为

复用 W-I-01 的 `WorksFilterState`，其中 `genre` 从 `null` 变为具体题材：

```ts
interface WorksFilterState {
  status: "all" | "active" | "completed" | "paused" | "archived";
  genre: "奇幻史诗" | "城市悬疑" | "温柔日常" | "科幻远征" | null;
  searchQuery: string;
  selectedStoryId: string | null;
}
```

筛选逻辑仍保持组合过滤：

```ts
const visibleStories = stories.filter((story) => {
  const statusMatched = filter.status === "all" || story.status === filter.status;
  const genreMatched = !filter.genre || story.genre === filter.genre;
  return statusMatched && genreMatched;
});

const selectedStory =
  visibleStories.find((story) => story.id === filter.selectedStoryId) ??
  visibleStories[0] ??
  null;
```

## 空状态预留

当题材筛选或组合筛选没有作品时，中间卡片区显示纸面空状态：

```text
这里还没有符合条件的故事
```

空状态可提供两个轻量入口：

- 清除筛选
- 新故事

## 已确认

- 已删除 `城市悬疑 · 4 部` 筛选摘要小标题。
- 再次点击已选题材时，直接清除题材筛选。
- 题材筛选和状态筛选同时存在时，暂不在卡片区左上方显示额外小标题，保持作品区干净。
