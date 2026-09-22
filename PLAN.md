# Plan: selection outline polish

Goal: the selected row should read at a glance on the dark stock theme and over album art, without fighting
playing/pressed styles or looking like a second theme.

Current: two parallel 1 px white rect strokes inset 1–2 px (`ringnav_paint`). It works, but it is fussy and
disappears on light artwork.

## What I would do

Replace the two rails with one soft highlight:

- Fill the row with white at ~18% alpha (inset 1 px) via `canvas_set_global_alpha` + `canvas_set_fill_color`
  + `canvas_fill_rect`. Content stays legible, dark rows lift gently, art gets a calm tint.
- Stroke a single 1 px white rect on the same rect, full alpha, to keep a crisp edge.
- Try a 4 px corner radius with `canvas_fill_rounded_rect` / `canvas_stroke_rounded_rect` only if it renders
  at menu-repaint cost on hardware; otherwise square corners are fine.

If white-on-white is a problem on real artwork, add one companion 1 px black stroke at ~35% alpha just outside
the white one (a two-tone edge) rather than reintroducing the double rail.

Not a solid inverted bar (the true iPod look): we cannot recolor the row's text, and an opaque fill would hide
artwork, so a low-alpha tint is the honest approximation.

All symbols exist in the stock binary and would be added to `FUNCTIONS` in `tools/build.py` like the current
canvas calls: `canvas_set_fill_color`, `canvas_fill_rect`, `canvas_set_global_alpha` (plus the rounded variants).

## Constraints

- Restore fill color, alpha (no getter, so restore 0xff), stroke color and clip after drawing; this canvas does
  not save them.
- Highlight only the active pane; home carousel and pressed/playing styles untouched.
- No animation, no chevrons, no theme lookup. Tuning lives in two constants (`FILL_ALPHA`, `RADIUS`).

## Steps

1. Audit the new symbols and signatures; extend `FUNCTIONS`.
2. Rework the draw block in `ringnav_paint`, keeping the `kind == 3` skip.
3. Extend the canvas ABI test to assert fill/alpha/stroke order and full restoration.
4. Hardware check: light album art, settings list, playing row, pressed row, oversized row, two-pane page;
   watch frame pacing while scrolling.
