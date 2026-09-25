# Shanling Q2 Scroll Wheel Navigation

Firmware mod for the Shanling Q2 that lets you use the scroll wheel to move through menus and press the centre button to select things.

The touchscreen still works normally. Outside supported menus, the wheel still controls volume.

**Build variants: V3.2R (normal), V3.2C (compact)**

[**Download the latest release**](https://github.com/DiamondBond/q2-ringnav/releases/latest)

## Install

Make sure the Q2 is charged before updating, and don't remove the microSD card while the update is running.

1. Download the firmware ZIP from the latest release.
2. Unzip it and copy `update.tar` to the root of your microSD card.
3. On the Q2, go to **System settings → System Update → TF card update**.
4. Confirm the update and wait for the player to restart.
5. Check **About** and make sure it shows `V3.2R` for normal or `V3.2C` for compact.

To restore stock firmware via the UI; flash the [Shanling Q2 official firmware](https://en.shanling.com/download/150) through **System settings → System Update → TF card update**.

If the UI is not working, use [Shanling's recovery package](https://drive.google.com/file/d/1aINQfJu6n0JTQ4hOzzD1uSpSj3TS_NJj/view?usp=drive_link):

1. Copy the complete `recovery-update` folder to the root of the microSD card.
2. Hold the previous-song button, then power on the Q2 with the centre button.
3. The player will automatically check for a firmware update.

## Variants

`Q2.Firmware.V3.2.zip` keeps the normal UI and existing controls, including long Return → Home.
`Q2.Firmware.V3.2-compact.zip` hides the primary toolbar in Folder and Local Songs browsing and
uses 72-pixel rows with the stock artwork drawn at its natural size and an even eight-pixel
inset: ordinary lists fit four complete rows with stock fonts. Separate action bars, Play All/sort, tabs, editing controls and album grid modes remain;
these can show fewer entries. Settings, online services, Now Playing, home and dialogs keep
their stock layouts. The folder artwork setting and saved preferences remain intact.

Compact long Return opens Now Playing without restarting playback, including when already
playing; its release is consumed. Short Return keeps stock Back and nested folder traversal.
Other long presses are unchanged. The proposed short Return shortcut on Home remains deferred.

## Controls

- Turn the scroll wheel to move through menu items; vertical lists update immediately, one row per accepted tick. Lists longer than 16 rows accelerate while you keep spinning: each 100 ms of continuous same-direction ticks spaced at most 140 ms apart adds a row to the step, up to eight rows per tick. Pausing, reversing or reaching an end returns to one-row steps.
- Each home wheel tick accepted by the stock input filter advances one icon: isolated ticks use a 200 ms slide, and consecutive same-direction ticks within 200 ms use 120 ms slides. Reversing immediately heads back from the current visual position at normal speed, canceling the unfinished destination.
- Short press the centre button to open the highlighted item after a 200 ms confirmation delay.
- Double-press the centre button within 200 ms to turn the screen off without opening an item. Touch or wheel input cancels a pending confirmation.
- Tap and swipe still work normally; a tap always opens the row you touched, even in a rebuilt or still-settling list, and tapping a row in another visible pane moves wheel control there.
- Turning the wheel during a swipe stops the scrolling and takes over again.
- Wheel selection and restored positions leave a small margin around the selected row where space allows, keeping it clear of the screen edge.
- Returning to a recently visited folder, album, query or settings menu restores its selection and brings it into view. The 64 most recently selected browsing positions are remembered until power-off; unseen lists start from their own viewport.
- Recreated non-virtual lists in the same remembered context find the selected row by its text after a re-sort.
- Touching anywhere hides the custom outline until accepted wheel or centre input resumes, including across page changes. Swiping and settling still selects the row nearest the middle of the list, ready for wheel or centre use.
- Outside supported menus, the wheel goes back to normal volume control.
- Play/Pause and long-press power are unchanged.

During wheel/centre use, the selected item gets a single rounded translucent-white outline seated on a dark separator line, over a subtle dark fill, so it stays readable over bright album art. The home screen keeps its normal selected-card look without the extra outline.

If you find a menu where something behaves strangely, please open an issue and say which screen you were on and what you did.

## Changelog

- **V3.2R / V3.2C**: Compact rows now fill the client area with 72-pixel rows, so the stock artwork keeps its natural size with an even eight-pixel inset instead of being scaled down. Navigation and all other behavior are unchanged.

- **V3.1R / V3.1C**: Shared normal and compact builds, compact local lists and long Return to Now Playing, and a reproducible dual-variant release procedure.

- **V3.0R**: Long lists accelerate smoothly again: each 100 ms of sustained same-direction spin adds a row to the step, up to eight rows per tick, replacing the V2.7R/V2.8R three-speed ladder. Stopping, reversing or easing off still drops back to one row immediately. The selected-row outline is now a softer translucent white line, so it sits better against the dark theme while the dark separator still keeps it readable over bright album art. The shipped `config.ini` is no longer modified, so a fresh install keeps the stock key tone default; a device that already ran V2.9R keeps its saved setting and can change it in the system settings.
- **V2.9R**: Restores the stock wheel and button input path, removing the V2.8R 25 ms detent hold. The key tone now ships disabled, so wheel and button feedback is silent by default; enable **Key Tone** in the system settings to bring the clicks back. The three-speed wheel acceleration from V2.8R is unchanged.
- **V2.8R**: Wheel acceleration adds a third speed: longer lists step two rows after 300 ms and three rows after 600 ms of continuous same-direction turns. A wheel button press no longer plays a second tick from the capacitive touch, drops the phantom step with it, and the wheel is ready again as soon as the button is released.
- **V2.7R**: Wheel turns move the list immediately instead of animating, and lists longer than 16 rows step two rows after 450 ms of continuous same-direction turns. Touching the screen hides the selection outline until the next accepted wheel or centre action, including across page changes. Centre confirmation and the double-press screen toggle now use a 200 ms window.
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

`release/bin/demo` and the boot logo inside `rootfs.squashfs` change. Compact additionally changes only the nine audited local UI assets in `patch/compact.json`. The kernel is byte-identical, and the builder checks every other inode's name, type, mtime, mode, uid and gid against stock.

Four checked MIPS prologues redirect into a payload at `0xb00000`, using the final unused `PT_NULL` program header. Trampolines restore the stock GOT base and resume each original function after its PIC setup:

| Stock callback            | Address    | Purpose                                                       |
| ------------------------- | ---------- | ------------------------------------------------------------- |
| `on_wm_keyup_before_fun`  | `0x4e85c8` | Stock lock filter first, then wheel/centre navigation         |
| `on_wm_tsdown_before_fun` | `0x4e8bd0` | Preserve stock touch processing and interrupt wheel glide     |
| `widget_on_paint_border`  | `0x6596a0` | Draw the selected entry outline after native children         |
| `widget_dispatch`         | `0x65e0ec` | Observe a native click before its app callback changes the UI |

Stock V1.32 turns the encoder knob into key releases 172/173: `encoderknob_thread_run` (`0x6256a0`) is the sysfs notifier thread, and the rotation handler after it (`0x6258e0`, unnamed in the symbol table) calls `get_direction` (`0x62587c`) and posts them into the main loop. The payload only sees those releases at `on_wm_keyup_before_fun`.

Selection is stored in widget-owned integer properties on the navigation surface, independently of AWTK's focused flag. The outline and centre action resolve that same logical selection against the current entries. Centre dispatches a synchronous native `EVT_CLICK`, so a queued click cannot hit a row rebound between selection and delivery. It never dereferences the target after delivery.

Position memory is a bounded 64-entry table keyed by the audited top-window context in `patch/contexts.inc` and a content fingerprint. Selecting a row updates its entry and moves it to the front; a full table evicts the least recently selected entry. Restoration alone does not promote an entry. Local folders use the full bounded `g_folder_path`; local music lists use the stock browsing class, saved query and artist/album modes (`g_class_type`, `g_local_classinfo_save`, `g_artist_type`, `album_modetype`). These are the inputs used by the stock folder and local-list loaders, not playback metadata. The builder verifies each object's size against the stock ELF. A changed fingerprint resets selection even if a surviving surface has the same row count, then restores the matching recent position and reveals it, or keeps the stock viewport if none is remembered. Fixed settings menus can restore by window name alone; multi-pane and other dynamic pages without an audited content identity keep their live widget selection but do not restore across recreation. Memory lasts until power-off, with no filesystem writes. The table occupies 1,280 bytes, just 256 bytes more than the previous per-window arrays. Ordinary paints do not search it; repeated selections in the current scope match its first entry and shift nothing. Lookup and promotion are bounded by `POS_MEM` (64), which can also be tuned at build time.

Non-virtual lists also remember hashes of the selected row's first two text values, read through the stock `widget_get_text` UTF-32 accessor. A matching second text outranks proximity; equal matches choose the occurrence nearest the remembered index. Rows without text fall back to the index within the same content scope. The stock rows expose no stable item id. Both scroll views and virtual music tables protect an interrupted recall glide from silently replacing the remembered selection with a currently visible row. A real tap cancels the glide and selects its target; a wheel detent advances from the remembered logical row. Pointer-down and synchronous click delivery load rows without recall, so native touch sees the widget it pressed and a rebuilt list cannot move or rebind that row first. Synchronous table rebinds discard the old row-pool snapshot before resolving the selected entry.

Lists with at most `SHORT_LIST_MAX` (16) logical entries always move one row per detent. This named constant in `patch/ringnav.c` can be tuned for the hardware; virtual tables use their total logical count, not the recycled row pool size. Longer lists use a continuous ramp: a same-direction tick spaced at most `WHEEL_RUN_MS` (140 ms) from the previous one extends a spin run, and the step is `1 + run / WHEEL_RAMP_MS` (100 ms), capped at `WHEEL_MAX_STEP` (8) rows. The step therefore passes smoothly through 2, 3, 4 and so on instead of jumping between fixed speeds. These named constants remain available for hardware tuning; the ramp is provisional until checked on the Q2. A pause, reversal, touch, native click, centre press, list boundary or rejected navigation resets the run. Acceleration belongs to the current window, pane and browsing scope; a list resize also resets it. Wheel movement cancels existing momentum and uses the stock `scroll_view_set_offset` / `table_client_set_yoffset` setters immediately, reloading table row references after synchronous rebinding. Remembered-position restoration retains its separate glide. This follows the row-based approach of Rockbox's [H2/Eros Q wheel mapping](https://github.com/Rockbox/rockbox/blob/master/apps/keymaps/keymap-erosq.c) and [list implementation](https://github.com/Rockbox/rockbox/blob/master/apps/gui/list.c). Selected and restored rows use a `SCROLL_MARGIN` of 12 pixels above and below, reduced to half the spare viewport height in tight lists and clamped at content boundaries. Rows taller than the viewport align their top edge when selected or restored, keeping their title visible.

A centre release arms a stock UI timer for `DOUBLE_CLICK_MS` (200 ms). A second release before expiry on the same live selection cancels confirmation and passes through the stock downstream key-up handler to turn the screen off. A single release dispatches exactly one synchronous click at expiry. Touch, wheel input and invalid navigation state cancel pending confirmation. The timer resolves the target from the live menu and requires the original window, surface, content scope, logical selection, row count and row-text identity to match. Widget-owned tokens also reject reused window/surface addresses, and an ordinary list requires the armed row widget's own token; virtual tables resolve recycled pool widgets by logical index. An overdue confirmation runs before the power and lock gates that follow it. No delayed row pointer is retained; pending state clears before dispatch. Timer allocation failure consumes the press without activating anything.

The home carousel uses `HOME_SLIDE_MS` (200 ms) for isolated ticks and `HOME_FAST_SLIDE_MS` (120 ms) when consecutive same-direction ticks arrive at most `HOME_FAST_WINDOW_MS` (200 ms) apart. These named constants in `patch/ringnav.c` remain available for hardware tuning. There is no extra home input gate; stock filtering and audible ticks stay stock-controlled. Each accepted tick retargets one animator from its live offset, extending the intended destination by one icon. Reversal discards that destination and heads toward the adjacent card in the new direction at normal speed. Stock completion handles wrapping and card selection; centre confirmation follows the intended final icon. Touch, native clicks, centre presses, leaving home and unavailable navigation reset speed tracking; wheel input cancels pending centre confirmation. Allocation failure settles on the requested icon without retaining an animator. Writable input and position state is mapped at `0xb0f000`.

A session-wide touch-mode flag suppresses only custom drawing, independently of logical selection and gesture state. Touch-down and native clicks (including clicks without touch-down) set it and invalidate the visible window. It persists through settling and page changes. Accepted wheel input, including a turn at a boundary, or centre selection restores drawing; synchronous centre-generated clicks bypass the native-click observer.

A native click chooses its pane from the actual target before walking up to the nearest collected ancestor. A successful selection clears the other pane’s selection and invalidates both panes, so the outline, wheel and centre follow the row that owns the tap. Hidden, disabled and inactive-page panes remain excluded.

The canvas hook intersects the existing clip with the viewport and restores the clip, the LCD fill color and the LCD stroke color; this firmware's `canvas_save/restore` do not save those properties. The outline is one translucent fill (`0x402b2b2b`, a per-color alpha) plus two concentric one-pixel `canvas_stroke_rounded_rect` calls, a dark separator at radius 9 and the 70%-opaque white line at radius 8, with `bg_r = NULL`. The separator is the stock dark surface at `0xb32b2b2b`, so it disappears on the dark theme and only shows over bright artwork. It never calls `canvas_set_global_alpha`, so the shared alpha is untouched. A rounded call that reports failure — either stroke — or a row too small for the corner radius, keeps the square separator-plus-white outline instead.

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
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-compact --compact
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-dev --compact --dev  # V3.3C test build
python3 tools/test_build.py  # JPEG header checks; no emulator required
python3 tools/test_build.py 'Q2 Firmware V1.32.zip'  # optional packaging/reproducibility checks
python3 tools/test_patch.py /tmp/q2-build  # after: pip install -r requirements.txt
```

`--dev` tags a build with the temporary higher version `V3.3R`/`V3.3C` so a test unit is
distinguishable from the released `V3.2R`/`V3.2C` it replaces. It applies to that build only:
the release procedure never passes `--dev`, and the manifest records `dev: true`.

The suite executes the actual patched MIPS payload and stock key/touch filters. UI services are mocked; carousel checks execute native animator parameter writes and stock completion, with a deterministic animation scheduler, and audit the stock creation path. Separate scenarios execute the stock canvas clip/color/rectangle code and the stock rounded fill/stroke entry points down to mocked LCD and vgcanvas sinks.

Checks cover touch reselection, gesture suppression, momentum handoff, immediate wheel offsets and animator cancellation, sustained wheel ramp boundaries and resets, persistent touch hiding and wheel/centre restoration, recycled rows, menu return, count changes, empty/oversized rows, 64-entry recent-position eviction and selection recency, nested folder and query returns on recreated/reused surfaces, 0/1/16/17-entry fast turns, re-sorted lists, duplicate-text rows through the real stock UTF-32 accessor, stale remembered rows, folder/query scope changes, interrupted table and scroll-view restore glides, touch-driven multi-pane ownership, centre-nearest swipe settle, preserved Play/Pause, power-release exclusions, deterministic confirmation timers, deadline boundaries, cancellation, allocation failure, changed/recycled targets, the real stock downstream screen-off/wake handler and home slide timing/reset boundaries, 3–5-tick bursts, live-position reversals at both speeds, bidirectional wrapping, empty/single-icon carousels and final-icon activation, nested tap targets and stock key-lock parity. The outline checks cover draw order, rectangle and radius arguments, the separator and white line colors, clip intersection, state restore (including unusual saved colors and untouched alpha bytes) and the square fallback for small rows and for a backend that declines the rounded stroke. Every call checks preserved registers/stack, and native calls check the PIC `$t9` convention.

The CPU-LCD fill path runs end to end down to mocked LCD sinks, including radius clamping, the `radius <= 2` decline and allocation balance. The stock rounded vgcanvas branch could not be executed end to end under Unicorn 2.1.4: the stock binary is built `-mfp64` and Unicorn's MIPS32 FPU only implements `FR=0`, so its 64-bit conversions trap. The test harness runs the branch up to the first such instruction and asserts the vgcanvas color and line-width calls that precede it.

The builder also rejects any `patch/contexts.inc` name that is not a window name in the stock rootfs UI assets, so an allowlist typo cannot silently disable a screen. Widget field offsets and shared ABI constants live in `patch/offsets.inc`; the payload and the test mocks read the same file.

The test runner refuses a `manifest.json` whose `source_sha256` does not match the current patch sources, and verifies the stock executable, patched executable and payload hashes against that manifest, so stale or mixed artifacts cannot pass as the current build.

Additional regression checks cover inactive tabs nested inside a navigation surface, pointer-down and painting during a tap before a recreated list has restored, saturation of large table offsets and selections without integer overflow, power-state changes during an overdue confirmation callback, and failure of either rounded outline stroke. Stock scroll-view setters verify the horizontal, vertical and page-snap field offsets independently of the mocks. Delayed confirmation rejects replaced ordinary rows even with identical or missing text, while virtual tables still resolve recycled rows by logical index. Missing key events cancel pending input before reaching the stock filter.

A MIPS instruction-count regression check verifies that filling the position table does not increase steady paint or wheel work in the current scope. In the published V2.4R build, painting the 20-row folder fixture executes 3,830 payload instructions, up from 3,369 in V2.3R, and a warm wheel turn executes 4,118 versus 3,653 previously; the increase is the inactive-page filter in the tap-target walk, not position memory. Inserting an unseen scope into a full table adds 2,448 instructions over the previous implementation. These are mocked-service instruction counts, not hardware latency measurements.

Two fresh builds must produce identical `update.tar` files. Packaging verifies MD5 entries, unchanged kernel and rootfs metadata, and a rootfs no larger than stock.

For on-device acceptance, browse a long list and confirm immediate response, a smooth pull up to eight rows per tick and precise reversal. Tap and swipe across panes and pages and confirm no outline lingers or returns until wheel/centre input; also try a wheel turn at a list end. Tune `WHEEL_RUN_MS`, `WHEEL_RAMP_MS` and `WHEEL_MAX_STEP` if needed. Check the selected-row margin in ordinary and music lists, including their ends and tall rows; spin the home wheel and confirm rapid turns visibly advance through multiple icons, reverse midway through both slow and fast slides, and check that no unwanted movement remains after the final slide settles. Tap a row as soon as a list appears, and again while a long list is still settling, and confirm the touched row opens. Also browse parent → child → grandchild folders, return to each selected folder, and check quick turns on short menus. Also revisit albums/queries and confirm their selections remain separate. Emulator checks do not replace this hardware check.

## Standard release procedure

Keep the proprietary stock ZIP local. Use the Python environment with `requirements.txt`
installed for these commands:

```sh
python3 tools/release.py package 'Q2 Firmware V1.32.zip' --out /tmp/q2-v32-release
python3 tools/test_release.py
# Create or update the release with both validated ZIPs and verify remote bytes.
python3 tools/release.py upload /tmp/q2-v32-release
# Same, then publish after verification.
python3 tools/release.py upload /tmp/q2-v32-release --publish
```

Packaging requires a fresh output directory, builds each variant twice, runs the shared MIPS
suite and asset checks on each build, and compares update.tar and ZIP bytes. It writes both
ZIPs, manifests, SHA256SUMS, release notes and source revision/hash. Normal is the default for
direct builds; a single direct build is never a release input. Upload revalidates both variants
and refuses stale, missing or changed artifacts and published releases. An upload/download
failure leaves the release unpublished; rerun upload to repair the draft. Packaging uses no
GitHub credentials or network. The [compact checklist](docs/compact.md) is a device test guide,
not a release gate.
