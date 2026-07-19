# W-I-01 Status Filter

日期：2026-06-19

## 当前状态

已采纳定稿 v1。此交互已收入 `99 Complete`。

## 交互目标

用户点击左侧 `状态` 分类后，作品集页面在当前页面内完成筛选，不跳转新页面。

本次先实现代表状态：

```text
进行中
```

五个状态共用同一套交互规则：

- 全部故事
- 进行中
- 已完成
- 暂停
- 归档

## 当前视觉稿

```text
status-filter-active-ongoing-final-v1.svg
status-filter-active-ongoing-final-v1.png
```

## v1 视觉规则

- 左侧 `进行中` 进入选中态：浅纸色底、左侧竖向色条、低亮玫瑰棕描边。
- `全部故事` 退出选中态，但保留为清除筛选入口。
- 页面副标题同步变为 `筛选：进行中 · 五部故事正在推进`。
- 不再显示卡片区左上方的筛选摘要小标题。
- 中间卡片区只显示 `进行中` 状态作品。
- 首屏展示 4 部进行中作品，数量仍显示 5，代表还有 1 部可通过滚动或后续分页出现。
- 第一张作品卡默认被选中，使用更明显的描边和阴影。
- 右侧 `当前选中` 自动同步为筛选结果中的第一部作品。
- 右侧 `最近节点` 和 `进度元数据` 仍保持展示状态，不做可点击入口。

## 交互规则

| 操作 | 页面反应 |
| --- | --- |
| 点击 `进行中` | 激活该状态筛选，中间卡片只保留进行中作品，右侧选择第一条结果 |
| 点击 `全部故事` | 清除状态筛选，恢复作品集默认全部故事视图 |
| 点击其它状态 | 替换当前状态筛选，复用同一视觉规则 |
| 单击作品卡片 | 选中作品，右侧预览更新 |
| 双击作品卡片 | 进入作品详情页 |
| 点击右侧 `详情` | 进入作品详情页 |
| 点击右侧 `继续` | 进入对应作品工作台 |

## 数据行为

前端需要的最低数据结构：

```ts
type StoryStatus = "all" | "active" | "completed" | "paused" | "archived";

interface StorySummary {
  id: string;
  title: string;
  genre: string;
  status: Exclude<StoryStatus, "all">;
  statusLabel: string;
  chapterLabel: string;
  progressRatio: number;
  metadataLine: string;
  coverTone: "warm" | "cool" | "gold" | "muted";
  preview: {
    title: string;
    subtitle: string;
    worldCanvasProgress: number;
    frameworkStage: string;
    characterCount: number;
    sceneCount: number;
    recentNodes: string[];
  };
}

interface WorksFilterState {
  status: StoryStatus;
  genre: string | null;
  searchQuery: string;
  selectedStoryId: string | null;
}
```

筛选逻辑：

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

当某个状态筛选没有作品时，中间卡片区不显示空白网格，建议显示同风格的纸面空状态：

```text
这里还没有符合条件的故事
```

空状态可提供两个轻量入口：

- 清除筛选
- 新故事

## 已确认

- 已删除 `进行中 · 5 部` 筛选摘要小标题。
- 首屏进行中作品显示 4 部还是 5 部。
- 状态切换时是否加入卡片淡出淡入或纸页翻动感。
