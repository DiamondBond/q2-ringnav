# Plan: selection outline polish

Goal: the selected row should read at a glance on the dark stock theme and over album art, without fighting
playing/pressed styles or looking like a second theme.

## What the stock UI does (V1.32 assets)

- Music rows are `table_row` (`s_tablerow_black`) wrapping a `button` (`s_btn_listitem`); the pages override
  every row state's background/border to transparent, so there is no persistent row highlight to copy.
- The current item is marked with an icon, never a row background: rows carry a grey note circle
  (`list_song`) and the playing item shows a red play badge (`small_playing`, `home_playing`, `menu_playing`).
  Red means "playing", not "selected".
- Component language in `styles/default.bin`: dark surfaces `#2b2b2b`, accent red `#ff1448` (pressed `#7f0a24`,
  dark `#3d1920`), radius 14, border width 2. The row button does have focused states, so native focus painting
  is possible, but entering AWTK's focus system is more invasive than the current logical selection.

## What I would do

Keep the cursor neutral (white) so it does not read as "playing", but match the stock geometry instead of the
current double rail:

- Single 2 px rounded outline (radius ~8–10 on a 48 px row; stock uses 14 for cards) plus an optional
  low-alpha `#2b2b2b`-family fill so the row reads as one surface.
- Fallback shape: if rounded or alpha rendering is costly on the LCD, keep a square 2 px outline.

Maximum brand alignment is an option, not the default: use the stock pressed look (radius 14, 2 px `#ff1448`,
`#3d1920` fill) for the cursor, at the cost of conflating "selected" with "playing".

The needed primitives exist in the stock binary and must be audited into `FUNCTIONS` like the current canvas
calls: `canvas_stroke_rounded_rect`, `canvas_fill_rounded_rect`, `canvas_fill_rect`, `canvas_set_fill_color`,
`canvas_set_global_alpha`.

## Constraints

- Restore fill color, alpha (no getter, so restore 0xff), stroke color and clip after drawing; this canvas does
  not save them.
- Highlight only the active pane; home carousel, playing and pressed styles untouched.
- No animation, no chevrons, no runtime theme lookup. Tuning lives in two constants (`RADIUS`, `FILL_ALPHA`).

## Steps

1. Audit the new symbols and signatures; extend `FUNCTIONS`.
2. Rework the draw block in `ringnav_paint`, keeping the `kind == 3` skip.
3. Extend the canvas ABI test to assert geometry, fill/alpha/stroke order and full restoration.
4. Hardware check: light album art, settings list, playing row, pressed row, oversized row, two-pane page;
   watch frame pacing while scrolling.
5. Optional experiment: set native focus on the selected row button and compare with the drawn cursor.
