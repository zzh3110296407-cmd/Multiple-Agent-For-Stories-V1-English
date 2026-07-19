# 12-08 Scene Gate Repair And Participant Candidates

Date: 2026-07-05

Status: accepted supplement for Phase 8.5 SceneWorkspace advanced surfaces.

## Files

```text
visual-drafts/scene-gate-repair-participant-candidates-v1.html
visual-drafts/scene-gate-repair-participant-candidates-v1.png
visual-drafts/scene-gate-repair-participant-candidates-v1-mobile.png
```

## Purpose

This page covers scene gate repair and participant creation candidates when the current scene cannot proceed cleanly.

## API Mapping

```ts
getSceneGateReadiness(sceneId)
runSceneGateRepair(sceneId, payload, options)
getCurrentSceneParticipantSelection(chapterId, sceneIndex)
refreshSceneParticipantSelection(selectionId)
confirmSceneParticipantCreationCandidate(candidateId)
rejectSceneParticipantCreationCandidate(candidateId)
```

## Interaction Rules

- Ordinary mode shows only readable repair summary and user actions.
- Expert evidence stays collapsed.
- Participant candidates require explicit confirm/reject before becoming usable roles.

