# Q2 ring navigation (V1.32 → V1.3R)

Lets the Shanling Q2 touch ring scroll lists and the home carousel. Volume control
stays wherever navigation isn't suitable.

Release: `dist/Q2 Firmware V1.3R.zip` (same layout as the stock ZIP).

| file | sha256 |
|---|---|
| `Q2 Firmware V1.3R.zip` | `4190d16a07fe055b129af7f56a1cf8b78350ce29effa873974aa95f5d39f2c29` |
| `update.tar` | `84b1c2d7bb894d79a7f283e6b49f2b5097bff4bfd19e95bda56cf0fc464a90e4` |

Every other hash, address and tool version is in `dist/manifest.json`.

Install it the same way as a stock update. To go back, flash the stock V1.32 package. The version
label changed from `V1.32` to `V1.3R` because the updater refuses to install a package whose version
equals the one already installed.

## What changed

Only `release/bin/demo` inside `rootfs.squashfs` changed. The kernel (`xImage`) is byte-identical.
The build checks that every other inode keeps its stock name, type, mtime, mode, uid and gid.

In `demo`:

1. **Hook:** `on_wm_keyup_before_fun` (0x4e85c8) is AWTK's key-up filter. Its first two
   instructions become `j ringnav; nop`. `patch/trampoline.S` re-creates the `$gp` value they set
   up, then resumes at 0x4e85d4, so the stock filter still runs first and unchanged.
2. **Payload:** `patch/ringnav.c` (5640 bytes, loaded at 0xb00000) goes in the unused final
   `PT_NULL` program header, which becomes a new R+X `PT_LOAD`. It calls stock AWTK functions by
   address via `$t9`.
3. **Version:** the single `V1.32\0` literal becomes `V1.3R\0`. The About screen and the updater
   share it.

The ring driver already turns motion into key codes 172/173 (volume). `ringnav` intercepts them
only when all of these hold:
- the stock filter didn't consume the key
- the screen is on, and no lock, test, guide, power-off, USB-link or Bluetooth-receive screen is showing
- the top window's name is in `patch/contexts.inc` (settings, library, folders, queue, Tidal, home)
- exactly one visible, enabled `slide_menu`, `table_client` or vertical non-snapping `scroll_view` exists.
  For `pages` widgets, only the active page is searched.

When those hold it walks the list one entry per detent, keeps a native AWTK focused widget on the
entry the wheel is on, and glides the list (300 ms) so that entry stays fully visible. Tap targets
are the widgets that carry an `EVT_CLICK` handler, the same ones a finger would hit. A short center
Play/Pause press then activates the focused entry with the same async `EVT_CLICK` that
`widget_on_keyup` dispatches (`pointer_event_init` + `widget_dispatch_async`), so menus, lists and
the home carousel are selected without faking touch coordinates. The home `slide_menu` uses its
native `value` (index @0x78); `table_client` rows are selected by row index (@0x78) because the
visible rows are re-bound on every scroll. If a `scroll_view`/`table_client` has no tap targets or
no entry is focused yet, the center key still falls through to stock play/pause.

The ring is consumed at list ends, so hitting the end never changes volume, and it is also consumed
during window animation and touch drags. All other screens get stock volume behaviour, including
playing, volume, EQ and screensaver, and play/pause from the center key is untouched everywhere
outside `patch/contexts.inc` — in particular on Now Playing.

## Build

Needs clang/lld/llvm-objcopy, squashfs-tools 4.7 (tested 4.7.5) and the original ZIP
(sha256 `154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00`). The build refuses any other input.

    python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2   # fresh dir required

## Validation

- **Emulation test:** `tools/test_patch.py <outdir>` (needs `unicorn==2.1.4`) runs the real
  patched `demo` machine code in Unicorn with mocked AWTK services. It covers 109 scenarios:
  - scrolling and clamping in both directions
  - empty lists
  - blocked screens and flags
  - animation/touch
  - ambiguous or hidden panes
  - one-entry-at-a-time focus tracking and the 300 ms glide target
  - a short center press dispatching the native async `EVT_CLICK` to the focused entry
  - center falling through to stock play/pause until something is focused
  - `table_client` row-index selection across a re-bound row
  - `slide_menu` value selection
  - retargeting an in-flight scroll instead of tearing it down
  - non-ring keys
  - the stock `get_direction` wraparound
  - stock vs patched results for every key-lock mode × backlight × key

  It also asserts that PIC calls get `$t9` and that callee-saved registers and the stack survive.
- **Reproducibility:** two fresh builds gave byte-identical `update.tar` files.
- **Package checks:** the MD5 list in `firmware_v20.info` matches the files. The rootfs listing
  differs from stock only in `demo`'s size. The rootfs (50434048 B) is no larger than stock
  (50442240 B), and the NAND rootfs partition is 247 MiB.
- **Not done:** no test on real hardware. The emulation mocks AWTK instead of running the full UI.
