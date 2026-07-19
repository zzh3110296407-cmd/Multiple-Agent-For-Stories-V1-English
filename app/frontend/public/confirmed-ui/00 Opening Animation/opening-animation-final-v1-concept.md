# Opening Animation Concept v1

Date: 2026-06-19

## Positioning

The opening animation is the first website experience before the homepage.
It should establish story atmosphere, then land smoothly on the confirmed homepage.
It must not feel like a game CG intro, a loading screen, or a debug state.

## Concept

Working title: `The Manuscript Wakes`

The screen begins as an old parchment surface in low light.
Fine paper dust and ink fibers drift into view.
The dragon shadow slowly emerges as if it has always been printed inside the parchment.
The product name appears with a restrained ink-and-focus reveal.
The camera settles, and the full homepage UI fades in.

## Timing

| Time | Moment | Visual Behavior | UI State |
| --- | --- | --- | --- |
| 0.00-0.35s | Dark parchment | Warm brown veil, faint fiber texture, tiny dust movement | No buttons |
| 0.35-0.95s | Paper reveal | Parchment brightens from center, edge stains become visible | No buttons |
| 0.95-1.55s | Dragon awakening | Dragon shadow becomes readable, slight parallax drift from upper right | No buttons |
| 1.55-2.15s | Title arrival | Brand mark and title appear with soft ink-focus reveal | Primary CTA still hidden |
| 2.15-2.85s | Homepage landing | Header, CTA, secondary buttons and footer metadata fade/slide into final positions | Full homepage |

Recommended total duration: `2.6s-2.9s`.

## Motion Principles

- Use slow ease-out and slight parallax, not bounce.
- Dust and ink particles should be subtle and sparse.
- Dragon movement should feel like a shadow settling on paper, not a flying creature animation.
- The final frame must match `99 Complete/01 Main Page/main-page-home-final-v1`.
- Skip should be available after the first `0.4s`.
- Reduced motion should replace the sequence with a `350ms-500ms` crossfade to homepage.

## Implementation Notes For Later Handoff

- Background asset: `main-page-story-workbench-background-v5.png`.
- Landing reference: `homepage-final-v1.png`.
- Preferred implementation path: CSS/Web Animations or Framer Motion-style sequence.
- Animation should expose a completion callback such as `onIntroComplete()`.
- User preference should allow disabling the opening animation in Settings later.
- If assets fail to load, fallback directly to homepage with no blocking state.

## Current Visual Draft

```text
visual-drafts/opening-animation-storyboard-v1.svg
visual-drafts/opening-animation-storyboard-v1.png
```
