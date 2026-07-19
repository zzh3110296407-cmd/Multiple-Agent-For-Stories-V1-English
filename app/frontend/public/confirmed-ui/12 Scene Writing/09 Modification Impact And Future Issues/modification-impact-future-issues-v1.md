# 12-09 Modification Impact And Future Issues

Date: 2026-07-05

Status: accepted supplement for Phase 8.5 SceneWorkspace advanced surfaces.

## Files

```text
visual-drafts/modification-impact-future-issues-v1.html
visual-drafts/modification-impact-future-issues-v1.png
visual-drafts/modification-impact-future-issues-v1-mobile.png
```

## Purpose

This page covers advanced revision safety: modification impact preview, pre-modify candidates, scene candidate cache, future issues, delayed questions, and future todos.

## API Mapping

```ts
createModificationImpactPreview(payload)
chooseModificationImpactOption(previewId, payload)
getPreModifyWorkspace(filters)
buildPreModifyApplyPlan(candidateId, payload)
acceptPreModifyCandidate(candidateId, payload)
rejectPreModifyCandidate(candidateId, payload)
deferPreModifyCandidate(candidateId, payload)
getSceneCandidateCache(sceneId, filters)
getReadyDelayedQuestions(filters)
answerDelayedQuestion(delayedQuestionId, payload)
```

## Interaction Rules

- Impact preview does not apply changes automatically.
- Candidate cache is read-only until the user accepts a candidate.
- Future questions are answered only in the matching future context.

