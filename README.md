# Shanling Q2 Scroll Wheel Navigation

Firmware mod for the Shanling Q2 that lets you use the scroll wheel to move through menus and press the centre button to select things.

The touchscreen still works normally. Outside supported menus, the wheel still controls volume.

**Latest firmware: V2.6R**

[**Download the latest release**](https://github.com/DiamondBond/q2-ringnav/releases/latest)

## Install

Make sure the Q2 is charged before updating, and don't remove the microSD card while the update is running.

1. Download the firmware ZIP from the latest release.
2. Unzip it and copy `update.tar` to the root of your microSD card.
3. On the Q2, go to **System settings → System Update → TF card update**.
4. Confirm the update and wait for the player to restart.
5. Check **About** and make sure it shows `V2.6R`.

To restore stock firmware via the UI; flash the [Shanling Q2 official firmware](https://en.shanling.com/download/150) through **System settings → System Update → TF card update**.

If the UI is not working, use [Shanling's recovery package](https://drive.google.com/file/d/1aINQfJu6n0JTQ4hOzzD1uSpSj3TS_NJj/view?usp=drive_link):

1. Copy the complete `recovery-update` folder to the root of the microSD card.
2. Hold the previous-song button, then power on the Q2 with the centre button.
3. The player will automatically check for a firmware update.

## Controls

- Turn the scroll wheel to move through menu items; lists of 16 or fewer items move one row per detent, while a fast spin skips further in longer lists. Home cards move at most once every 200 ms in the same direction; reversing the wheel responds immediately so you can correct an overshoot.
- Short press the centre button to open the highlighted item after a 300 ms confirmation delay.
- Double-press the centre button within 300 ms to turn the screen off without opening an item. Touch or wheel input cancels a pending confirmation.
- Tap and swipe still work normally; a tap always opens the row you touched, even in a rebuilt or still-settling list, and tapping a row in another visible pane moves wheel control there.
- Turning the wheel during a swipe stops the scrolling and takes over again.
- Wheel selection and restored positions leave a small margin around the selected row where space allows, keeping it clear of the screen edge.
- Returning to a recently visited folder, album, query or settings menu restores its selection and brings it into view. The 64 most recently selected browsing positions are remembered until power-off; unseen lists start from their own viewport.
- Recreated non-virtual lists in the same remembered context find the selected row by its text after a re-sort.
- Swiping a list and letting it settle puts the highlight on the row nearest the middle of the list.
- Outside supported menus, the wheel goes back to normal volume control.
- Play/Pause and long-press power are unchanged.

The selected item gets a single rounded white outline seated on a dark separator line, over a subtle dark fill, so it stays readable over bright album art. The home screen keeps its normal selected-card look without the extra outline.

If you find a menu where something behaves strangely, please open an issue and say which screen you were on and what you did.

## Changelog

- **V2.6R**: Wheel input replaces an unfinished scroll-view animation so reversing a glide toward a list boundary takes effect immediately. Native clicks also reset wheel acceleration and the home wheel interval when no touch-down event was delivered.
- **V2.5R**: Native clicks cancel pending centre confirmation even without a touch-down event. Rejected confirmations leave changed lists and their remembered positions untouched. Double-press still turns the screen off after interrupting a recalled list with touch. Custom boot logos must use the stock renderer's supported JPEG frame format; packaging uses a snapshot of the validated image.
- **V2.4R**: Taps and centre presses stay bound to the row they started on, so a rebuilt or still-settling list cannot move the row under your finger or open a different one. Page-snapping views no longer capture the wheel, and a failed rounded outline stroke falls back to the square outline.
- **V2.3R**: Wheel selection and restored positions keep a small margin from the screen edge, and reversing the home wheel responds immediately to correct an overshoot.
- **V2.2R**: Remembers the 64 most recently selected browsing positions, restoring folders and music queries on return. Lists of 16 or fewer items stay at one row per wheel detent, even during quick turns.
- **V2.1R**: Fast-spin acceleration stays within the current menu and resets after a folder/query change, list resize, interrupted gesture or sleep. Oversized rows reveal their title consistently when selected or restored.
- **V2.0R**: Centre presses now confirm after 300 ms, allowing a second press within that window to turn the screen off. Home carousel wheel input is paced to make cards easier to select. Includes an orientation fixed boot logo.
- **V1.9R**: The selection outline is now one crisp white line over a dark separator and the subtle dark fill, so it stays readable over bright album art. A canvas that declines rounded drawing keeps the square outline.
- **V1.8R**: Wheel acceleration, gliding music tables, a scoped double-press screen toggle, nested tap-target selection, per-context position memory with row-text identity, multi-pane surface selection, a centre-nearest swipe settle and a build-time context audit.
- **V1.7R**: Added centre button double-press to toggle the screen on/off.
- **V1.6R**: Home screen now keeps the stock selected-card highlight without any extra outline.
- **V1.5R**: Added menu item highlighting, centre-button selection, and music selection features.

---

# Technical details

`release/bin/demo` and the boot logo inside `rootfs.squashfs` change. The kernel is byte-identical, and the builder checks every other inode's name, type, mtime, mode, uid and gid against stock.

Four checked MIPS prologues redirect into a payload at `0xb00000`, using the final unused `PT_NULL` program header. Trampolines restore the stock GOT base and resume each original function after its PIC setup:

| Stock callback            | Address    | Purpose                                                       |
| ------------------------- | ---------- | ------------------------------------------------------------- |
| `on_wm_keyup_before_fun`  | `0x4e85c8` | Stock lock filter first, then wheel/centre navigation         |
| `on_wm_tsdown_before_fun` | `0x4e8bd0` | Preserve stock touch processing and interrupt wheel glide     |
| `widget_on_paint_border`  | `0x6596a0` | Draw the selected entry outline after native children         |
| `widget_dispatch`         | `0x65e0ec` | Observe a native click before its app callback changes the UI |

Selection is stored in widget-owned integer properties on the navigation surface, independently of AWTK's focused flag. The outline and centre action resolve that same logical selection against the current entries. Centre dispatches a synchronous native `EVT_CLICK`, so a queued click cannot hit a row rebound between selection and delivery. It never dereferences the target after delivery.

Position memory is a bounded 64-entry table keyed by the audited top-window context in `patch/contexts.inc` and a content fingerprint. Selecting a row updates its entry and moves it to the front; a full table evicts the least recently selected entry. Restoration alone does not promote an entry. Local folders use the full bounded `g_folder_path`; local music lists use the stock browsing class, saved query and artist/album modes (`g_class_type`, `g_local_classinfo_save`, `g_artist_type`, `album_modetype`). These are the inputs used by the stock folder and local-list loaders, not playback metadata. The builder verifies each object's size against the stock ELF. A changed fingerprint resets selection even if a surviving surface has the same row count, then restores the matching recent position and reveals it, or keeps the stock viewport if none is remembered. Fixed settings menus can restore by window name alone; multi-pane and other dynamic pages without an audited content identity keep their live widget selection but do not restore across recreation. Memory lasts until power-off, with no filesystem writes. The table occupies 1,280 bytes, just 256 bytes more than the previous per-window arrays. Ordinary paints do not search it; repeated selections in the current scope match its first entry and shift nothing. Lookup and promotion are bounded by `POS_MEM` (64), which can also be tuned at build time.

Non-virtual lists also remember hashes of the selected row's first two text values, read through the stock `widget_get_text` UTF-32 accessor. A matching second text outranks proximity; equal matches choose the occurrence nearest the remembered index. Rows without text fall back to the index within the same content scope. The stock rows expose no stable item id. Both scroll views and virtual music tables protect an interrupted recall glide from silently replacing the remembered selection with a currently visible row. A real tap cancels the glide and selects its target; a wheel detent advances from the remembered logical row. Pointer-down and synchronous click delivery load rows without recall, so native touch sees the widget it pressed and a rebuilt list cannot move or rebind that row first. Synchronous table rebinds discard the old row-pool snapshot before resolving the selected entry.

Lists with at most `SHORT_LIST_MAX` (16) logical entries always move one row per detent. This named constant in `patch/ringnav.c` can be tuned for the hardware; virtual tables use their total logical count, not the recycled row pool size. Longer lists accelerate: consecutive detents at most 140 ms apart in the same direction double the step every third detent, up to eight entries. A pause, a reversal, a touch or a centre press starts the count over. Acceleration belongs to the current window, pane and browsing scope; a list resize or rejected navigation input also resets it. Music tables glide with the stock `table_client_scroll_to` animator instead of jumping, so both list kinds settle the same way. Selected and restored rows use a `SCROLL_MARGIN` of 12 pixels above and below, reduced to half the spare viewport height in tight lists and clamped at content boundaries. Rows taller than the viewport align their top edge when selected or restored, keeping their title visible.

A centre release arms a stock UI timer for `DOUBLE_CLICK_MS` (300 ms). A second release before expiry on the same live selection cancels confirmation and passes through the stock downstream key-up handler to turn the screen off. A single release dispatches exactly one synchronous click at expiry. Touch, wheel input and invalid navigation state cancel pending confirmation. The timer resolves the target from the live menu and requires the original window, surface, content scope, logical selection, row count and row-text identity to match. Widget-owned tokens also reject reused window/surface addresses, and an ordinary list requires the armed row widget's own token; virtual tables resolve recycled pool widgets by logical index. An overdue confirmation runs before the power and lock gates that follow it. No delayed row pointer is retained; pending state clears before dispatch. Timer allocation failure consumes the press without activating anything.

The home carousel uses `HOME_WHEEL_MS` (200 ms) between accepted wheel steps in the same direction. The first step and reversals are immediate after stock input checks; each accepted step starts a fresh interval. Intermediate same-direction events are consumed without queuing or extending the interval. Touch, centre press and leaving home reset the interval. Both timing constants are in `patch/ringnav.c` for hardware tuning. Writable input and position state is mapped at `0xb0f000`.

A native click chooses its pane from the actual target before walking up to the nearest collected ancestor. A successful selection clears the other pane’s selection and invalidates both panes, so the outline, wheel and centre follow the row that owns the tap. Hidden, disabled and inactive-page panes remain excluded.

The canvas hook intersects the existing clip with the viewport and restores the clip, the LCD fill color and the LCD stroke color; this firmware's `canvas_save/restore` do not save those properties. The outline is one translucent fill (`0x402b2b2b`, a per-color alpha) plus two concentric one-pixel `canvas_stroke_rounded_rect` calls, a dark separator at radius 9 and the white line at radius 8, with `bg_r = NULL`. The separator is the stock dark surface at `0xb32b2b2b`, so it disappears on the dark theme and only shows over bright artwork. It never calls `canvas_set_global_alpha`, so the shared alpha is untouched. A rounded call that reports failure — either stroke — or a row too small for the corner radius, keeps the square separator-plus-white outline instead.

Navigation requires a supported top-window name from `patch/contexts.inc`, screen-on and no lock/test/guide/power-off/USB-link/Bluetooth-receive screen, and a navigable pane: a vertical `scroll_view`, a `table_client` or a `slide_menu`. Horizontal and page-snapping scroll views are not candidates, so they cannot make a page look like it has two panes. When two panes are visible and neither owns the selection, the first wheel turn chooses the first pane in UI order. Later turns follow the selected pane, and tapping a row switches ownership. If both panes already hold a selection, the wheel event is left alone. Only active `pages` children are searched. The bounded walk collects at most 512 targets in a non-virtual list; virtual music tables navigate by total logical row count instead.

## Custom boot logo

Rebuilt firmware uses `assets/logo.jpg` as the boot splash by default. Pass another 320x375 JPEG with `--logo` to use your own — see [docs/boot-logo.md](docs/boot-logo.md).

## Build and validation

Requires clang/lld/llvm-objcopy, squashfs-tools 4.7 (tested 4.7.5), the test harness dependencies in `requirements.txt`, and the original ZIP:

```text
154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00
```

SHA-256 of the stock Shanling Q2 V1.32 firmware ZIP.

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-build
python3 tools/test_build.py  # JPEG header checks; no emulator required
python3 tools/test_build.py 'Q2 Firmware V1.32.zip'  # optional packaging/reproducibility checks
python3 tools/test_patch.py /tmp/q2-build  # after: pip install -r requirements.txt
```

The suite executes the actual patched MIPS payload and stock key/touch filters. UI services are mocked; separate scenarios execute the stock canvas clip/color/rectangle code and the stock rounded fill/stroke entry points down to mocked LCD and vgcanvas sinks.

Checks cover touch reselection, gesture suppression, momentum handoff, interrupted and reversed wheel glides, acceleration steps and resets, recycled rows, menu return, count changes, empty/oversized rows, 64-entry recent-position eviction and selection recency, nested folder and query returns on recreated/reused surfaces, 0/1/16/17-entry fast turns, re-sorted lists, duplicate-text rows through the real stock UTF-32 accessor, stale remembered rows, folder/query scope changes, interrupted table and scroll-view restore glides, touch-driven multi-pane ownership, centre-nearest swipe settle, preserved Play/Pause, power-release exclusions, deterministic confirmation timers, deadline boundaries, cancellation, allocation failure, changed/recycled targets, the real stock downstream screen-off/wake handler and home wheel interval/reset boundaries, nested tap targets and stock key-lock parity. The outline checks cover draw order, rectangle and radius arguments, the separator and white line colors, clip intersection, state restore (including unusual saved colors and untouched alpha bytes) and the square fallback for small rows and for a backend that declines the rounded stroke. Every call checks preserved registers/stack, and native calls check the PIC `$t9` convention.

The CPU-LCD fill path runs end to end down to mocked LCD sinks, including radius clamping, the `radius <= 2` decline and allocation balance. The stock rounded vgcanvas branch could not be executed end to end under Unicorn 2.1.4: the stock binary is built `-mfp64` and Unicorn's MIPS32 FPU only implements `FR=0`, so its 64-bit conversions trap. The test harness runs the branch up to the first such instruction and asserts the vgcanvas color and line-width calls that precede it.

The builder also rejects any `patch/contexts.inc` name that is not a window name in the stock rootfs UI assets, so an allowlist typo cannot silently disable a screen. Widget field offsets and shared ABI constants live in `patch/offsets.inc`; the payload and the test mocks read the same file.

The test runner refuses a `manifest.json` whose `source_sha256` does not match the current patch sources, and verifies the stock executable, patched executable and payload hashes against that manifest, so stale or mixed artifacts cannot pass as the current build.

Additional regression checks cover inactive tabs nested inside a navigation surface, pointer-down and painting during a tap before a recreated list has restored, saturation of large table offsets and selections without integer overflow, power-state changes during an overdue confirmation callback, and failure of either rounded outline stroke. Stock scroll-view setters verify the horizontal, vertical and page-snap field offsets independently of the mocks. Delayed confirmation rejects replaced ordinary rows even with identical or missing text, while virtual tables still resolve recycled rows by logical index. Missing key events cancel pending input before reaching the stock filter.

A MIPS instruction-count regression check verifies that filling the position table does not increase steady paint or wheel work in the current scope. In the published V2.4R build, painting the 20-row folder fixture executes 3,830 payload instructions, up from 3,369 in V2.3R, and a warm wheel turn executes 4,118 versus 3,653 previously; the increase is the inactive-page filter in the tap-target walk, not position memory. Inserting an unseen scope into a full table adds 2,448 instructions over the previous implementation. These are mocked-service instruction counts, not hardware latency measurements.

Two fresh builds must produce identical `update.tar` files. Packaging verifies MD5 entries, unchanged kernel and rootfs metadata, and a rootfs no larger than stock.

For on-device acceptance, check the selected-row margin in ordinary and music lists, including their ends and tall rows; spin the home wheel then reverse to correct an overshoot. Tap a row as soon as a list appears, and again while a long list is still settling, and confirm the touched row opens. Also browse parent → child → grandchild folders, return to each selected folder, and check quick turns on short menus. Also revisit albums/queries and confirm their selections remain separate. Emulator checks do not replace this hardware check.
