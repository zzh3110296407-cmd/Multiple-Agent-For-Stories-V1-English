# Genre Filter Remaining Genres v1

日期：2026-06-19

## 当前状态

已采纳 v1。用于补齐 W-I-02 `题材筛选` 中除已采纳 `城市悬疑` 之外的三个题材：

- 奇幻史诗
- 温柔日常
- 科幻远征

这些稿件已收入 `99 Complete/01 Main Page/02 Works/02 Genre Filter`。

## 当前视觉稿

```text
visual-drafts/genre-filter-active-fantasy-epic-v1.svg
visual-drafts/genre-filter-active-fantasy-epic-v1.png
visual-drafts/genre-filter-active-gentle-daily-v1.svg
visual-drafts/genre-filter-active-gentle-daily-v1.png
visual-drafts/genre-filter-active-sci-fi-expedition-v1.svg
visual-drafts/genre-filter-active-sci-fi-expedition-v1.png
```

## 完成版文件

```text
99 Complete/01 Main Page/02 Works/02 Genre Filter/genre-filter-active-fantasy-epic-final-v1.svg
99 Complete/01 Main Page/02 Works/02 Genre Filter/genre-filter-active-fantasy-epic-final-v1.png
99 Complete/01 Main Page/02 Works/02 Genre Filter/genre-filter-active-gentle-daily-final-v1.svg
99 Complete/01 Main Page/02 Works/02 Genre Filter/genre-filter-active-gentle-daily-final-v1.png
99 Complete/01 Main Page/02 Works/02 Genre Filter/genre-filter-active-sci-fi-expedition-final-v1.svg
99 Complete/01 Main Page/02 Works/02 Genre Filter/genre-filter-active-sci-fi-expedition-final-v1.png
99 Complete/01 Main Page/02 Works/02 Genre Filter/genre-filter-remaining-genres-final-v1.md
```

## 共同交互规则

三张稿件复用 W-I-02 已采纳的题材筛选规则：

- 点击某个题材后，左侧对应题材进入选中态。
- 状态区保持 `全部故事` 选中，表示没有额外状态筛选。
- 中间作品卡片只显示该题材下的作品。
- 题材筛选结果可以混合多种状态，例如进行中、已完成、暂停、归档。
- 第一条结果自动成为右侧 `当前选中`。
- 单击作品卡片更新右侧预览。
- 双击作品卡片进入作品详情。
- 不在卡片区左上方显示筛选摘要小标题。

## 奇幻史诗

代表数据：

```text
筛选：奇幻史诗 · 四部故事仍有龙影
```

视觉策略：

- 使用低亮玫瑰棕作为题材强调色。
- 显示 4 张作品卡片，状态混合为进行中、已完成、归档。
- 默认选中 `雨夜港口`，延续主页飞龙与羊皮卷气质。

## 温柔日常

代表数据：

```text
筛选：温柔日常 · 四部故事留着灯
```

视觉策略：

- 使用低亮金褐色作为题材强调色。
- 显示 4 张作品卡片，状态混合为暂停、已完成、进行中。
- 默认选中 `金色餐厅`，右侧预览强调暂停与修订状态。

## 科幻远征

代表数据：

```text
筛选：科幻远征 · 三部故事驶向深空
```

视觉策略：

- 使用偏冷的灰绿色作为题材强调色。
- 显示 3 张作品卡片。
- 第 4 个卡位显示低饱和占位：`已显示全部 3 部科幻远征故事`。
- 默认选中 `星环远征`，右侧预览强调星图、航线约束和 Framework 进度。

## 数据行为

复用 W-I-02 的组合筛选逻辑：

```ts
interface WorksFilterState {
  status: "all" | "active" | "completed" | "paused" | "archived";
  genre: "奇幻史诗" | "城市悬疑" | "温柔日常" | "科幻远征" | null;
  searchQuery: string;
  selectedStoryId: string | null;
}
```

题材映射建议：

```ts
const genreLabelMap = {
  fantasy: "奇幻史诗",
  mystery: "城市悬疑",
  daily: "温柔日常",
  scifi: "科幻远征",
} as const;
```

## 已确认

- 题材筛选结果不足 4 张时，保留柔和空白占位。
- 每个题材使用低调但可区分的强调色，避免过亮。
- 题材筛选和状态筛选同时存在时，暂不在卡片区左上方显示额外小标题，保持作品区干净。
