# 10-08 Role Library And Tier Management

Date: 2026-07-05

Status: accepted supplement for Phase 8.5 character management coverage.

## Files

```text
visual-drafts/role-library-tier-management-v1.html
visual-drafts/role-library-tier-management-v1.png
visual-drafts/role-library-tier-management-v1-mobile.png
```

## Purpose

This page covers the ordinary-user role management surfaces that sit beside the main Character Spine generation chain:

- A/B/C/D tier filter.
- role list and current role selection.
- manual B/C/D role creation.
- basic role edit.
- tier change with A-tier protection.
- archive role.

## API Mapping

```ts
getRoles({ tier, status, includeArchived })
createRole(payload)
patchRole(characterId, payload)
changeRoleTier(characterId, tier, userInput)
archiveRole(characterId, reason, userInput)
```

## Interaction Rules

- A-tier roles can be reviewed but cannot be downgraded or archived here.
- B/C/D roles can be manually created and edited.
- Tier change requires explicit user note.
- Archive requires reason text and should preserve the role as historical material.

