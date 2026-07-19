# 10-09 Role Context Preview

Date: 2026-07-05

Status: accepted supplement for Phase 8.5 character management coverage.

## Files

```text
visual-drafts/role-context-preview-v1.html
visual-drafts/role-context-preview-v1.png
visual-drafts/role-context-preview-v1-mobile.png
```

## Purpose

This page previews the role context package before downstream Framework, Chapter Planning, or Scene Writing uses it.

## API Mapping

```ts
buildRoleContextPreview(payload)
```

Expected payload fields:

```ts
{
  target_workspace: "framework" | "chapter_plan" | "chapter_scene";
  chapter_id?: string;
  scene_id?: string;
  include_tiers?: Array<"A" | "B" | "C" | "D">;
  safe_user_note?: string;
}
```

## Interaction Rules

- User chooses target workspace and role tiers.
- Preview is read-only.
- Preview can be accepted as downstream context but does not write character facts.

