# PLAN — Native AWTK scrolling for ring navigation (option B2)

Status: implemented and verified (build + 109-scenario emulation + reproducible package), released as
V1.4R; device test pending.

## Goal

Replace the hand-rolled scroll call in the `scroll_view` branch of `patch/ringnav.c` with the
firmware's own per-item animated scroll routine, so lists glide exactly like stock AWTK lists do.
Keep the existing focus/selection engine (ring moves a native focused entry, center Play/Pause
selects). Do **not** change `table_client`; it keeps the instant `table_client_set_yoffset` plus
immediate focus so the highlighted row is always correct (B2). `slide_menu` is already native.

## Research findings that shape this plan

- AWTK ships native animated, per-item scroll primitives, and the firmware's own list handlers call
  them:
  - `scroll_view_scroll_delta_to(widget, dx, dy, duration)` at `0x5f03e8`. It adds `dx`/`dy` to the
    current offsets and tail-calls `scroll_view_scroll_to` (which retargets a running animator).
    The stock `list_view` handler (`0x5ebb50`, `0x5eca9c`) calls it as
    `(w, 0, ±item_height, 300)`.
  - `table_client_scroll_delta_to(widget, delta, duration)` at `0x5ca904`. The stock `table_client`
    handler (`0x5caf74`) calls it as `(w, ±row_height, 300)`.
  - `slide_menu_scroll_to_next/prev` at `0x5f371c`/`0x5f3514` (already used by the patch).
- Raw `EVT_WHEEL` (`0x106`) dispatch is not usable for these widgets: `widget_on_wheel` exists
  (`0x662e94`) but the `on_wheel` vtable slot (vtable `+0x54`) is null for `scroll_view` and
  `table_client`, and no app path feeds wheel events. The native delta routines are the real
  native path.
- `table_client` rows are re-bound during animation, so native animated scrolling and immediate
  row-index focus do not compose cleanly. That is why B2 leaves `table_client` on the instant
  offset path (highlight always correct) and only switches `scroll_view` to the native glide.

## Why B2

- `scroll_view` entries are stable widgets (no re-binding), so focus can be set immediately and the
  native glide added on top: correct highlight + stock animation.
- `table_client` re-binds rows; the instant `set_yoffset` + immediate focus already gives the
  correct highlight, and switching it to animation would require re-implementing AWTK's
  index-driven focus callback (`config_focused_widget`), risking a collision with the app's own
  `on_create_row` callback. Not worth it.

## Changes

### 1. `tools/build.py`

Add one prototype to `FUNCTIONS`:

```python
'scroll_view_scroll_delta_to': ('int', 'void *, int, int, int'),   # 0x5f03e8
```

Keep `table_client_set_yoffset`, `table_client_stop_animator_scroll` and `slide_menu_*`. Remove
`scroll_view_scroll_to` only if it becomes unused; otherwise leave it.

### 2. `patch/ringnav.c`

Keep the existing structure (`find_surface`, `collect`, `list_nav`, `table_nav`, activation, flags,
contexts). Only the `scroll_view` (generic) branch changes from absolute to relative native scroll.

- `list_nav()` currently computes an absolute target `want` and calls `scroll_view_scroll_to`.
  Change it to move by the clamped relative delta instead:
  - `int delta = want - top;`
  - if `delta != 0`, call `scroll_view_scroll_delta_to(w, 0, delta, GLIDE_MS);`
  - focus is still applied immediately before the glide.
- Generic fallback (surface has no tap targets) currently calls `scroll_view_scroll_to` with a
  clamped absolute offset. Change to:
  - `int next = clamp_step(I(w, 0x84), I(w, 0x7c) - h, dir * RING_STEP);`
  - if `next != I(w, 0x84)`, call `scroll_view_scroll_delta_to(w, 0, next - I(w, 0x84), GLIDE_MS);`
  - The manual `clamp_step` is kept so the ring is consumed at the ends and volume is never
    changed.
- `table_client` branch: unchanged (`table_client_stop_animator_scroll` +
  `table_client_set_yoffset` + focus).
- `slide_menu` branch: unchanged.
- Update the file header comment to say `scroll_view` uses the stock animated delta scroll.

No new globals; the existing `GLIDE_MS 300` is kept and passed as the duration.

### 3. `tools/test_patch.py`

- Add a mock for `scroll_view_scroll_delta_to`: `self.word(a+0x80, x+b); self.word(a+0x84, y+c)`
  (relative add), then `ret=0`.
- `moved()` already includes `scroll_view_scroll_to`; add `scroll_view_scroll_delta_to`.
- Update the existing scroll_view scenarios:
  - "scrolling and clamping in both directions" still asserts the final offset, but the recorded
    call is now `scroll_view_scroll_delta_to`.
  - "retargeting an in-flight scroll" now asserts `scroll_view_scroll_delta_to` and that the glide
    animator field (`0xe8`) is left untouched.
  - Focus/glide scenario: assert `scroll_view_scroll_delta_to` was called with the expected relative
    `dy` (e.g. `+48`) and that focus moved to the target entry.
- Keep all `table_client`, `slide_menu`, flag, key-lock and `get_direction` scenarios unchanged.

## Verification

1. `python3 tools/build.py 'Q2 Firmware V1.32.zip' --out <fresh dir>` compiles and links with
   `-Werror`.
2. `tools/test_patch.py <outdir>` passes all scenarios (current 109, adjusted for the new call),
   including the stock-vs-patched key-lock parity loop.
3. Two fresh builds produce a byte-identical `update.tar`.
4. Repackage `dist/Q2 Firmware V1.4R.zip`, refresh `dist/manifest.json` and the `README.md`
   hashes/patch size.
5. Hardware caveat: the emulator mocks AWTK, so the real glide feel still needs a device test.

## Tasks

- [x] Add `scroll_view_scroll_delta_to` to `tools/build.py`.
- [x] Switch `list_nav()` and the generic fallback in `patch/ringnav.c` to relative native delta
      scroll; update the header comment.
- [x] Update `tools/test_patch.py` mocks and the affected scroll scenarios.
- [x] Build, run the emulation suite, verify a second fresh build is identical.
- [x] Package `dist/Q2 Firmware V1.4R.zip`, update `dist/manifest.json` and `README.md`.

## Risks

- If `scroll_view_scroll_delta_to` does not clamp internally, end-of-list overshoot must be avoided
  by the explicit `clamp_step` before computing the delta (already planned).
- `scroll_view_scroll_delta_to` passes the duration to the `onscroll` vtable callback and the stock
  animator uses a fixed 300 ms; `GLIDE_MS` matches that, so no behavior change.
- No change to `table_client`/`slide_menu`/activation, so the validated behavior and tests for those
  paths stay intact.
