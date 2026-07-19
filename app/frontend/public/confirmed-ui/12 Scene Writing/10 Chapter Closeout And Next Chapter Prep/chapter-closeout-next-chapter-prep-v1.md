# 12-10 Chapter Closeout And Next Chapter Prep

Date: 2026-07-05

Status: accepted supplement for Phase 8.5 SceneWorkspace advanced surfaces.

## Files

```text
visual-drafts/chapter-closeout-next-chapter-prep-v1.html
visual-drafts/chapter-closeout-next-chapter-prep-v1.png
visual-drafts/chapter-closeout-next-chapter-prep-v1-mobile.png
```

## Purpose

This page covers chapter end behavior inside SceneWorkspace: archive preview, stable/provisional archive, next chapter preview, prepare next chapter, confirm next chapter, and story draft completion.

## API Mapping

```ts
previewChapterArchive(chapterId, chapterIndex)
archiveChapter(payload)
previewNextChapter()
prepareNextChapter(payload)
confirmNextChapter(payload)
confirmStoryDraftComplete(acknowledgeCompletion)
```

## Interaction Rules

- Only show this as a primary path when the current chapter has reached its planned scene count.
- Provisional archive requires explicit acknowledgement before preparing next chapter.
- Confirming story complete is separate from confirming next chapter.

