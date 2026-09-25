# Build and validation

Rebuilt firmware uses `assets/logo.jpg` as the boot splash by default. Pass another 320x375 JPEG with `--logo` to use your own — see [boot-logo.md](boot-logo.md).

Requires clang/lld/llvm-objcopy, squashfs-tools 4.7 (tested 4.7.5), the test harness dependencies in `requirements.txt`, and the original ZIP:

```text
154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00
```

SHA-256 of the stock Shanling Q2 V1.32 firmware ZIP.

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-build
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-compact --compact
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-dev --compact --dev  # V3.4C test build
python3 tools/test_build.py  # JPEG header checks; no emulator required
python3 tools/test_build.py 'Q2 Firmware V1.32.zip'  # optional packaging/reproducibility checks
python3 tools/test_patch.py /tmp/q2-build  # after: pip install -r requirements.txt
```

`--dev` tags a build with the temporary higher version `V3.4R`/`V3.4C` so a test unit is
distinguishable from the released `V3.3R`/`V3.3C` it replaces. It applies to that build only:
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
