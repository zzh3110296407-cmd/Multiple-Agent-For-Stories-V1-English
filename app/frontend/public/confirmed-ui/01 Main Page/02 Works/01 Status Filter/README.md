# 01 Status Filter - Final v1

Confirmed date: 2026-06-19

Status: visually confirmed direction.

## Files

- `status-filter-active-ongoing-final-v1.svg` - editable source layout.
- `status-filter-active-ongoing-final-v1.png` - rendered preview.
- `status-filter-active-ongoing-final-v1.md` - interaction and implementation notes.
- `status-filter-active-completed-final-v1.svg` - editable completed-state layout.
- `status-filter-active-completed-final-v1.png` - rendered completed-state preview.
- `status-filter-active-paused-final-v1.svg` - editable paused-state layout.
- `status-filter-active-paused-final-v1.png` - rendered paused-state preview.
- `status-filter-active-archived-final-v1.svg` - editable archived-state layout.
- `status-filter-active-archived-final-v1.png` - rendered archived-state preview.
- `status-filter-remaining-states-final-v1.md` - notes for completed, paused, and archived states.
- `assets/homepage-final-v1.png` - blurred homepage background asset.
- `assets/main-page-story-workbench-background-v5.png` - story cover texture asset.

## Confirmed Design

- `进行中`, `已完成`, `暂停`, and `归档` are confirmed active states for W-I-01.
- Status filtering happens inside the works page, without navigation.
- The selected status uses a quiet paper panel, left accent strip, and low-brightness Morandi rose-brown outline.
- The visible story grid updates to matching works only.
- The first filtered work becomes the selected preview by default.
- `全部故事` remains the clear-filter entry.
- Card-area filter summary chips are removed; the current filter is expressed through the page subtitle and left rail selection.

## Implementation Notes

- The same behavior applies to `全部故事`, `进行中`, `已完成`, `暂停`, and `归档`.
- Empty results should show a paper-style empty state with `清除筛选` and `新故事`.
- Process drafts remain under `05 Page Records/01 Main Page/02 Works/01 Status Filter`.
