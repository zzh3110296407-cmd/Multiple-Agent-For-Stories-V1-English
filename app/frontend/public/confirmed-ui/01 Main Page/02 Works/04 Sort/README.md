# 04 Sort Menu - Final v1

Confirmed date: 2026-06-20

Status: accepted interaction state.

## Files

- `sort-menu-recent-updated-final-v1.svg` - editable source visual.
- `sort-menu-recent-updated-final-v1.png` - rendered preview.
- `W-I-04-sort-menu.md` - interaction and implementation notes.

## Confirmed Design

- Clicking `最近更新` opens a same-width sort menu directly below the trigger.
- The trigger and menu use one connected popover shell in the open state.
- The join has no independent button bottom border, bottom radius, top menu arrow, or direction labels.
- Sort options are `最近更新`, `最近打开`, `创建时间`, `标题`, and `完成度`.

## Implementation Notes

- Treat the open state as one component shell, not a button plus a separate floating menu.
- The dropdown should slide down from the trigger with a short 180-220ms transition.
- Sorting changes the visible story order and must not clear filters or search state.
