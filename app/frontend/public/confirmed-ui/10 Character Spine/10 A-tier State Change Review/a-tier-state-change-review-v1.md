# 10-10 A-tier State Change Review

Date: 2026-07-05

Status: accepted supplement for Phase 8.5 character management coverage.

## Files

```text
visual-drafts/a-tier-state-change-review-v1.html
visual-drafts/a-tier-state-change-review-v1.png
visual-drafts/a-tier-state-change-review-v1-mobile.png
```

## Purpose

This page covers pending A-tier major state changes. A-tier changes are not simple edits because they can affect long-term story direction, relationships, memory, and future scene context.

## API Mapping

```ts
getPendingRoleStateChanges()
proposeRoleStateChange(payload)
confirmRoleStateChange(changeId, userInput)
rejectRoleStateChange(changeId, userInput)
```

## Interaction Rules

- User reviews one pending change at a time.
- Confirm requires visible impact and user note.
- Reject preserves audit trail but does not mutate role state.
- The page should not offer archive/downgrade actions for A-tier roles.

