# Start Creation Popout Animation v5

日期：2026-06-19

## 状态

讨论稿，等待用户确认。确认后再归档到 `05 Page Records/99 Complete`。

## 本轮修改目标

根据用户反馈，对 v4 做三处修正：

- 三个按钮再白一些。
- 三个按钮最终落在同一水平线上。
- 移除动画中额外出现的 `开始创作` 按钮。

## 动效设计

- 三个按钮仍从同一个原点弹出。
- `新创作` 从原点向左上弹出。
- `继续创作` 从原点向上弹出。
- `历史创作` 从原点向右上弹出。
- 三个按钮按左、中、右顺序错峰出现。
- 终态三个按钮同一水平线，避免中心按钮过高。
- 原 `开始创作` 不再作为可见按钮出现，只通过原点光圈暗示来源。

## 配色与层级

```text
按钮顶部：#F2EDE4
按钮中段：#E8DFD2
按钮底部：#D9CDBB
文字：#34312E / #5F524B
描边：rgba(255, 250, 240, 0.56)
阴影：rgba(79, 64, 58, 0.20-0.30)
```

## 文件

```text
visual-drafts/start-creation-expanded-v7.svg
visual-drafts/start-creation-expanded-v7.png
visual-drafts/start-creation-popout-animation-v5.html
visual-drafts/start-creation-popout-animation-v5-final.png
```

## 备注

- `start-creation-popout-animation-v5.html` 可直接打开查看动画。
- 点击画面可以重播动画。
- 当前未进入最终归档，仍用于讨论与微调。
