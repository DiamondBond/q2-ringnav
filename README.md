# Shanling Q2 Scroll Wheel Navigation

Firmware mod for the Shanling Q2 that lets you use the scroll wheel to move through menus and press the centre button to select things.

The touchscreen still works normally. Outside supported menus, the wheel still controls volume and the other buttons keep their normal behaviour.

**Latest firmware: V1.7R**

[**Download the latest release**](https://github.com/DiamondBond/q2-ringnav/releases/latest)

## Install

1. Download the firmware ZIP from the latest release.
2. Unzip it and copy `update.tar` to the root of your microSD card.
3. On the Q2, go to **System settings → System Update → TF card update**.
4. Confirm the update and wait for the player to restart.
5. Check **About** and make sure it shows `V1.7R`.

Make sure the Q2 is charged before updating, and don't remove the microSD card while the update is running.

This is for the **Shanling Q2 on stock V1.32 firmware**.

To go back to stock, just flash the official Shanling Q2 V1.32 firmware again.

[Shanling Q2 official firmware](https://en.shanling.com/download/150)

## Controls

- Turn the scroll wheel to move through menu items.
- Short press the centre button to open the highlighted item.
- Double-press the centre button to turn the screen off.
- Tap and swipe still work normally.
- Turning the wheel during a swipe stops the scrolling and takes over again.
- Outside supported menus, the wheel goes back to normal volume control.
- Play/Pause and long-press power are unchanged.

The selected item gets a small white outline so you can see what will open when you press the centre button. The home screen keeps its normal selected-card look without the extra outline.

If you find a menu where something behaves strangely, please open an issue and say which screen you were on and what you did.

## Changelog

- **V1.7R**: Added centre button double-press to toggle the screen on/off (awaiting hardware validation).
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

A centre release within 400 ms of the previous one is handed back to the stock key-up chain, whose short press toggles the screen through `screen_action`; the first press of the pair still opens the highlighted item. The payload maps its 64K window read/write and keeps the last release time in a zero-filled scratch cell at `0xb0f000`. A wheel detent clears the window.

The canvas hook intersects the existing clip with the viewport and restores both clip and stroke color; this firmware's `canvas_save/restore` do not save those properties.

Navigation requires a supported top-window name from `patch/contexts.inc`, screen-on and no lock/test/guide/power-off/USB-link/Bluetooth-receive screen, and exactly one visible enabled navigation surface. Only active `pages` children are searched. Horizontal and page-snapping scroll views remain native. The bounded walk collects at most 256 targets in a non-virtual list; virtual music tables navigate by total logical row count instead.

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

The suite executes the actual patched MIPS payload and stock key/touch filters. UI services are mocked; a separate scenario executes the stock canvas clip/color/rectangle code down to a mocked LCD sink.

Checks cover touch reselection, gesture suppression, momentum handoff, interrupted and reversed wheel glides, recycled rows, menu return, count changes, empty/oversized rows, preserved Play/Pause, power-release exclusions, the double-press window and stock key-lock parity. Every call checks preserved registers/stack, and native calls check the PIC `$t9` convention.

Two fresh builds must produce identical `update.tar` files. Packaging verifies MD5 entries, unchanged kernel and rootfs metadata, and a rootfs no larger than stock.

## Hardware validation

Before distributing a build as hardware-verified, check a Q2 on Home, Local Songs, folders and settings:

- wheel → tap another item → centre
- wheel → swipe → settle → centre
- swipe → wheel during momentum
- rapid wheel reversals
- return from a submenu
- double-press centre → screen off, then centre → wake
- single centre press → select, with no screen change
- screen-off wake
- Play/Pause
- long-press power

Confirm the outline follows the item actually opened and the physical centre button emits the expected key.
