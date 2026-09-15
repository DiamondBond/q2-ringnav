# Q2 ring navigation (V1.32 → V1.3R)

Lets the Shanling Q2 touch ring scroll lists and the home carousel. Volume control
stays wherever navigation isn't suitable.

Release: `dist/Q2 Firmware V1.3R.zip` (same layout as the stock ZIP).

| file | sha256 |
|---|---|
| `Q2 Firmware V1.3R.zip` | `4039428883fc85a08d5891d50e8dd6fdd3a720d357413ed37ad1094f634ef46c` |
| `update.tar` | `fa805b7b6cea189f9cf32ec97c008721d322023e137e4aca2f8a6a4657ab90ed` |

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
2. **Payload:** `patch/ringnav.c` (3256 bytes, loaded at 0xb00000) goes in the unused final
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

When those hold, it moves by `--step` pixels (default 48) or one carousel item, clamps at the list
ends, and consumes the key, so hitting the end of a list never changes volume. Ring input is also
consumed during window animation and touch drags. All other screens get stock volume behaviour,
including playing, volume, EQ and screensaver.

## Build

Needs clang/lld/llvm-objcopy, squashfs-tools 4.7 (tested 4.7.5) and the original ZIP
(sha256 `154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00`). The build refuses any other input.

    python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2   # fresh dir required

## Validation

- **Emulation test:** `tools/test_patch.py <outdir>` (needs `unicorn==2.1.4`) runs the real
  patched `demo` machine code in Unicorn with mocked AWTK services. It covers 104 scenarios:
  - scrolling and clamping in both directions
  - empty lists
  - blocked screens and flags
  - animation/touch
  - ambiguous or hidden panes
  - animator cleanup
  - non-ring keys
  - the stock `get_direction` wraparound
  - stock vs patched results for every key-lock mode × backlight × key

  It also asserts that PIC calls get `$t9` and that callee-saved registers and the stack survive.
- **Reproducibility:** two fresh builds gave byte-identical `update.tar` files.
- **Package checks:** the MD5 list in `firmware_v20.info` matches the files. The rootfs listing
  differs from stock only in `demo`'s size. The rootfs (50434048 B) is no larger than stock
  (50442240 B), and the NAND rootfs partition is 247 MiB.
- **Not done:** no test on real hardware. The emulation mocks AWTK instead of running the full UI.
