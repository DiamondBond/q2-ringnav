# Shanling Q2 Scroll Wheel Navigation

Firmware mod for the Shanling Q2 that lets you use the scroll wheel to move through menus and press the centre button to select things.

The touchscreen still works normally. Outside supported menus, the wheel still controls volume and the other buttons keep their normal behaviour.

**Latest firmware: V1.9R**

[**Download the latest release**](https://github.com/DiamondBond/q2-ringnav/releases/latest)

## Install

1. Download the firmware ZIP from the latest release.
2. Unzip it and copy `update.tar` to the root of your microSD card.
3. On the Q2, go to **System settings → System Update → TF card update**.
4. Confirm the update and wait for the player to restart.
5. Check **About** and make sure it shows `V1.9R`.

Make sure the Q2 is charged before updating, and don't remove the microSD card while the update is running.

This is for the **Shanling Q2 on stock V1.32 firmware**.

To go back to stock, just flash the official Shanling Q2 V1.32 firmware again.

[Shanling Q2 official firmware](https://en.shanling.com/download/150)

## Controls

- Turn the scroll wheel to move through menu items; a fast spin skips further.
- Short press the centre button to open the highlighted item.
- Double-press the centre button to turn the screen off.
- Tap and swipe still work normally.
- Turning the wheel during a swipe stops the scrolling and takes over again.
- Leaving a menu and coming back selects the row you left, not the first row.
- A list that has been re-sorted selects the remembered row by its text, not its old position.
- Swiping a list and letting it settle puts the highlight on the row nearest the middle of the list.
- Outside supported menus, the wheel goes back to normal volume control.
- Play/Pause and long-press power are unchanged.

The selected item gets a rounded white outline with a subtle dark fill, so it stays readable over bright album art. The home screen keeps its normal selected-card look without the extra outline.

If you find a menu where something behaves strangely, please open an issue and say which screen you were on and what you did.

## Changelog

- **V1.9R**: The selection outline is now a rounded white double stroke over a subtle dark fill, so it stays readable over bright album art. A canvas that declines rounded drawing falls back to the square outline.
- **V1.8R**: Wheel acceleration, gliding music tables, a scoped double-press screen toggle, nested tap-target selection, per-context position memory with row-text identity, multi-pane surface selection, a centre-nearest swipe settle and a build-time context audit.
- **V1.7R**: Added centre button double-press to toggle the screen on/off.
- **V1.6R**: Home screen now keeps the stock selected-card highlight without any extra outline.
- **V1.5R**: Added menu item highlighting, centre-button selection, and music selection features. Tested on real Q2 hardware.

---

# Technical details

Only `release/bin/demo` inside `rootfs.squashfs` changes. The kernel is byte-identical, and the builder checks every other inode's name, type, mtime, mode, uid and gid against stock.

Four checked MIPS prologues redirect into a payload at `0xb00000`, using the final unused `PT_NULL` program header. Trampolines restore the stock GOT base and resume each original function after its PIC setup:

| Stock callback            | Address    | Purpose                                                       |
| ------------------------- | ---------- | ------------------------------------------------------------- |
| `on_wm_keyup_before_fun`  | `0x4e85c8` | Stock lock filter first, then wheel/centre navigation         |
| `on_wm_tsdown_before_fun` | `0x4e8bd0` | Preserve stock touch processing and interrupt wheel glide     |
| `widget_on_paint_border`  | `0x6596a0` | Draw the selected entry outline after native children         |
| `widget_dispatch`         | `0x65e0ec` | Observe a native click before its app callback changes the UI |

Selection is stored in widget-owned integer properties on the navigation surface, independently of AWTK's focused flag. The outline and centre action resolve that same logical selection against the current entries. Centre dispatches a synchronous native `EVT_CLICK`, so a queued click cannot hit a row rebound between selection and delivery. It never dereferences the target after delivery.

A per-context slot array in the same scratch page remembers the selected row, indexed by the audited top-window index into `patch/contexts.inc` — not by name pointer, because AWTK owns and frees the window name string. A recreated page restores that row and moves the viewport the least amount that makes it visible; a page that survives navigation keeps its widget property and never reads the array. Non-virtual lists also store an FNV-1a hash of the selected row's first text property, so a re-sorted list restores the same item and only falls back to the remembered index when the text is gone. A page whose row count changes while it is open resets its selection but keeps its viewport, and a touch or wheel event that interrupts a restore glide retries it instead of storing the row that happened to be visible. The memory dies with the scratch page at power-off.

Wheel detents accelerate: consecutive detents less than 140 ms apart in the same direction double the step every third detent, up to eight entries. A pause, a reversal, a touch or a centre press starts the count over. Music tables glide with the stock `table_client_scroll_to` animator instead of jumping, so both list kinds settle the same way.

A centre release within 400 ms of the previous one is handed back to the stock key-up chain, whose short press toggles the screen through `screen_action`; the first press of the pair still opens the highlighted item. The pair only counts when both releases land on the same top window and navigation surface, and any touch or wheel detent clears it. The payload maps writable state at `0xb0f000` for the last release, the window/surface identity and the detent timing.

A native click may land on a clickable child of a collected target; selection then walks up to the nearest collected ancestor, so the outline and centre stay on the row that actually owns the tap.

The canvas hook intersects the existing clip with the viewport and restores the clip, the LCD fill color and the LCD stroke color; this firmware's `canvas_save/restore` do not save those properties. The outline is one translucent fill (`0x402b2b2b`, a per-color alpha) plus two one-pixel `canvas_stroke_rounded_rect` calls at radius 9 and 8, with `bg_r = NULL`; it never calls `canvas_set_global_alpha`, so the shared alpha is untouched. A rounded call that reports failure, or a row too small for the corner radius, keeps the square double-stroke outline instead.

Navigation requires a supported top-window name from `patch/contexts.inc`, screen-on and no lock/test/guide/power-off/USB-link/Bluetooth-receive screen, and a navigable pane: a vertical `scroll_view`, a `table_client` or a `slide_menu`. Horizontal and page-snapping scroll views are not candidates, so they cannot make a page look like it has two panes. When two panes are visible at once, only the pane that already holds the selection is navigated; otherwise the event is left alone rather than guessed. Only active `pages` children are searched. The bounded walk collects at most 512 targets in a non-virtual list; virtual music tables navigate by total logical row count instead.

## Build and validation

Requires clang/lld/llvm-objcopy, squashfs-tools 4.7 (tested 4.7.5), and the original ZIP:

```text
154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00
```

SHA-256 of the stock Shanling Q2 V1.32 firmware ZIP.

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-build
python3 tools/test_patch.py /tmp/q2-build  # requires unicorn==2.1.4
```

The suite executes the actual patched MIPS payload and stock key/touch filters. UI services are mocked; separate scenarios execute the stock canvas clip/color/rectangle code and the stock rounded fill/stroke entry points down to mocked LCD and vgcanvas sinks.

Checks cover touch reselection, gesture suppression, momentum handoff, interrupted and reversed wheel glides, acceleration steps and resets, recycled rows, menu return, count changes, empty/oversized rows, per-context position memory, re-sorted lists, stale remembered rows, interrupted restore glides, multi-pane surface selection, centre-nearest swipe settle, preserved Play/Pause, power-release exclusions, the double-press window and its touch/page-change exclusions, nested tap targets and stock key-lock parity. The outline checks cover draw order, rectangle and radius arguments, clip intersection, state restore (including unusual saved colors and untouched alpha bytes) and the square fallback for small rows and for a backend that declines the rounded stroke. Every call checks preserved registers/stack, and native calls check the PIC `$t9` convention.

The CPU-LCD fill path runs end to end down to mocked LCD sinks, including radius clamping, the `radius <= 2` decline and allocation balance. The stock rounded vgcanvas branch could not be executed end to end under Unicorn 2.1.4: the stock binary is built `-mfp64` and Unicorn's MIPS32 FPU only implements `FR=0`, so its 64-bit conversions trap. The test harness runs the branch up to the first such instruction (asserting the vgcanvas color and line-width calls that precede it) and covers the rest on hardware.

The builder also rejects any `patch/contexts.inc` name that is not a window name in the stock rootfs UI assets, so an allowlist typo cannot silently disable a screen. Widget field offsets and shared ABI constants live in `patch/offsets.inc`; the payload and the test mocks read the same file.

The test runner refuses a `manifest.json` whose `source_sha256` does not match the current patch sources, so a stale output directory cannot pass as the current build.

Two fresh builds must produce identical `update.tar` files. Packaging verifies MD5 entries, unchanged kernel and rootfs metadata, and a rootfs no larger than stock.

## Hardware validation

Before distributing a build as hardware-verified, check a Q2 on Home, Local Songs, folders and settings:

- wheel → tap another item → centre
- wheel → swipe → settle → centre
- swipe → wheel during momentum
- rapid wheel reversals
- fast wheel spin (multiple rows per detent) then slow spin (one row)
- return from a submenu
- leave a long list and return: previous row is selected and scrolled into view
- leave a list, re-sort it, return: the same item is selected
- swipe a long list and let it settle: the highlight lands near the middle, not the top edge
- a screen with two visible lists (for example the equalizer): only the pane holding the highlight moves
- leave a settings page and return: check whether the cached page already keeps its row
- power cycle: returning to a page starts at the first row again
- double-press centre → screen off, then centre → wake
- centre → tap → centre within 400 ms: selects twice, screen stays on
- centre → submenu → centre within 400 ms: selects, screen stays on
- single centre press → select, with no screen change
- dark settings list and a bright album-art track: the rounded outline and its fill stay readable, and the red playing badge is still distinct from the selection
- selected row that is also playing, and a pressed/touched row: text, icons and scrollbars are not hidden
- first/last, partly clipped and recycled rows on a music table: the outline tracks the item centre opens
- rapid wheel scrolling and swipe momentum: outline drawing adds no visible hitching
- screen-off wake
- Play/Pause
- long-press power

Confirm the outline follows the item actually opened and the physical centre button emits the expected key.
