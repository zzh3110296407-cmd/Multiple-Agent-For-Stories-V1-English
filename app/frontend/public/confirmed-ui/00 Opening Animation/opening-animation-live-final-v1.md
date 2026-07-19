# Opening Animation Live v1

Date: 2026-07-05

Status: accepted on 2026-07-05 and copied into `99 Complete/00 Opening Animation`.

## Files

```text
visual-drafts/opening-animation-live-v1.html
visual-drafts/opening-animation-live-v1-frame-dark.png
visual-drafts/opening-animation-live-v1-frame-paper.png
visual-drafts/opening-animation-live-v1-frame-dragon.png
visual-drafts/opening-animation-live-v1-frame-title.png
visual-drafts/opening-animation-live-v1-frame-home.png
visual-drafts/opening-animation-live-v1-final.png
visual-drafts/opening-animation-live-v1-mobile-title.png
visual-drafts/opening-animation-live-v1-mobile-home.png
```

## Direction

This draft turns the accepted storyboard into a playable browser animation.

The sequence is:

1. Dark parchment surface.
2. Paper texture wakes from the center.
3. The upper-right dragon trace settles into the parchment.
4. Brand mark and `Multiple Agent / For Stories` appear.
5. Overlay fades out and lands on the homepage.

## Timing

```text
0.00-0.35s  dark parchment
0.35-0.95s  paper reveal
0.95-1.55s  dragon trace settles
1.55-2.15s  brand title enters
2.15-2.85s  homepage landing
```

## Interaction

- `Esc` skips the intro.
- A visible `跳过` button appears after roughly `0.4s`.
- Reduced motion should crossfade to the homepage in roughly `420ms`.
- If assets fail to load, Codes should bypass this overlay and show the homepage.

## Frame Preview Params

The HTML supports fixed review frames:

```text
?frame=dark
?frame=paper
?frame=dragon
?frame=title
?frame=home
```

## Implementation Notes

- Desktop final frame uses the confirmed homepage landing reference image for this design draft.
- Mobile final frame uses a responsive simulated homepage layer so the draft does not crop the title.
- In production, Codes should fade from the overlay into the real homepage component instead of a screenshot.
- The background asset is `main-page-story-workbench-background-v5.png`.
- The overlay should expose an `onIntroComplete()` callback.
- Settings can later connect to:

```ts
type OpeningAnimationSettings = {
  enabled: boolean;
  playMode: "every_visit" | "first_session" | "manual_only";
  reducedMotion: boolean;
};
```

## Review Notes

- The hard oval edge from the first dragon trace draft was removed.
- Debug-only replay controls were removed from the user-facing surface.
- Desktop and mobile preview screenshots were rendered with Playwright.
