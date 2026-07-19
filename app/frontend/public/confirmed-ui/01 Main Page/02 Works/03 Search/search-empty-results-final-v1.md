# W-I-03 Search

日期：2026-06-20

## 当前状态

基础搜索结果态已采纳 v1；无结果状态为讨论稿 v1。用于设计作品集页面顶部搜索框的聚焦态、搜索结果浮层和搜索无结果浮层。

## 交互目标

用户在作品集顶部搜索框中输入关键词后，不跳转页面，而是在当前作品集页面上方展开轻量搜索浮层。搜索结果覆盖三类内容：

- 故事
- 角色
- 世界

## 当前视觉稿

```text
visual-drafts/search-focus-results-v1.svg
visual-drafts/search-focus-results-v1.png
visual-drafts/search-empty-results-v1.svg
visual-drafts/search-empty-results-v1.png
99 Complete/01 Main Page/02 Works/03 Search/search-focus-results-final-v1.svg
99 Complete/01 Main Page/02 Works/03 Search/search-focus-results-final-v1.png
```

## v1 视觉规则

- 搜索框聚焦后从原顶部位置轻微放大，成为当前最高层级输入控件。
- 搜索框和搜索浮层均按页面 720px 中心线对齐，避免右偏。
- 页面背景保留作品集结构，但整体降低透明度，让用户仍知道自己停留在作品集内。
- 搜索浮层采用米白羊皮纸质感，边缘和阴影保持柔和，不使用强烈纯白弹窗。
- 删除浮层顶部的 `搜索：关键词`、结果数量和范围切换胶囊，减少重复信息。
- 结果按 `故事`、`角色`、`世界` 分组展示。
- 第一条结果默认进入高亮态，使用左侧细色条和浅棕描边。
- 六条搜索结果全部收纳在浮层边界内，不允许底部内容溢出。
- 不在页面中新建独立搜索页，W3 属于作品集页内状态。

## 无结果状态 v1

- 复用同一个搜索聚焦层级，不跳转页面。
- 搜索框中保留用户输入的关键词，示例为 `月蚀剧场`。
- 浮层高度缩短，避免空状态显得笨重。
- 中央显示 `没有找到相关内容`。
- 辅助文案说明当前作品集内没有匹配的故事、角色或世界条目。
- 不在空状态面板底部放置 `清除搜索` 和 `新故事` 按钮，保持空状态更轻、更对称。

## 交互规则

| 操作 | 页面反应 |
| --- | --- |
| 点击搜索框 | 搜索框进入聚焦态，若输入为空，可显示最近搜索或空浮层 |
| 输入关键词 | 展开搜索浮层，按故事、角色、世界返回分组结果 |
| 单击故事结果 | 选中对应作品，右侧 `当前选中` 同步更新 |
| 双击故事结果 | 进入该作品详情页 |
| 单击角色结果 | 选中角色所属作品，并在后续作品详情页中定位到角色 |
| 单击世界结果 | 选中世界条目所属作品，并在后续作品详情页中定位到世界画布 |
| 点击清除 | 清空关键词，保留搜索框聚焦 |
| 搜索框失焦或按取消 | 关闭搜索浮层，恢复作品集默认层级 |

## 数据行为

```ts
type WorksSearchScope = "all" | "story" | "character" | "world";

interface WorksSearchState {
  isOpen: boolean;
  query: string;
  scope?: WorksSearchScope;
  selectedResultId: string | null;
}

type WorksSearchResultType = "story" | "character" | "world";

interface WorksSearchResult {
  id: string;
  type: WorksSearchResultType;
  title: string;
  subtitle: string;
  storyId: string;
  storyTitle: string;
  status?: "active" | "completed" | "paused" | "archived";
  target?: {
    module: "storyDetail" | "character" | "worldCanvas";
    entityId?: string;
  };
}
```

## 空状态预留

当没有搜索结果时，浮层内部显示纸面空状态：

```text
没有找到相关内容
```

空状态本身不放额外按钮。用户仍可通过搜索框右侧的 `清除` 清空关键词，也可使用作品集页顶部原有 `新故事` 入口。

## 待讨论

- 搜索框聚焦但没有输入时，是显示最近搜索，还是只显示空浮层。
- 角色和世界结果被单击后，当前阶段是只同步右侧作品预览，还是提前设计更深的定位反馈。
- 是否需要为搜索结果增加键盘高亮态。
- 当前 v1 删除了范围切换胶囊；如果后续搜索结果非常多，再讨论是否恢复轻量范围切换。
