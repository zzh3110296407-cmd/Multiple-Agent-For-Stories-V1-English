# 16-02 Normal Shell Navigation And Status

Date: 2026-07-05

Status: accepted supplement for Phase 8.5 global product shell coverage.

## Files

```text
visual-drafts/normal-shell-navigation-status-v1.html
visual-drafts/normal-shell-navigation-status-v1.png
visual-drafts/normal-shell-navigation-status-v1-mobile.png
```

## Purpose

This page defines the normal product shell behavior that wraps every ordinary workspace:

- global status bar
- current project header
- workspace sidebar groups
- selected / available / blocked / hidden states
- ordinary/expert mode toggle
- current workspace header
- progress header and next actions

## Source Alignment

```tsx
ProductAppShell.jsx
GlobalStatusBar.jsx
ProductModeToggle.jsx
ProductProgressHeader.jsx
StatusBadge.jsx
WarningPanel.jsx
```

## API Mapping

```ts
getProductNavigationState({ projectId, workspaceId, modeProfileId })
getProductNavigationAvailability(params)
getProductNavigationPreferences()
patchProductNavigationPreferences(payload)
getProductModeProfile(params)
patchProductModeProfile(payload)
getProductProgressState(params)
getProductProgressNextActions(params)
getProductProgressDecisionSurfaces(params)
getProductProgressBlockingIssues(params)
```

## Interaction Rules

- The shell does not mutate story facts.
- Locked workspaces remain visible in ordinary mode with reason text.
- Expert-only entries stay hidden unless expert mode is enabled.
- Sidebar state and mode profile are preferences, not story data.

