# Q2 ring navigation (V1.32 → V1.6R)

Adds wheel selection to Shanling Q2 menus while keeping native touchscreen navigation.

Release candidate: `dist/Q2 Firmware V1.6R.zip` (same layout as the stock ZIP).
Device feedback on V1.5R confirms centre selection, highlighting and music selection work.
V1.6R removes the unnecessary outline from the home carousel; this tweak awaits device validation.

## Controls

- Lists show a two-pixel white outline around the selected entry, independent of the red
  currently-playing indication and native touch focus. Selection initializes on the first paint.
  The home carousel keeps its native selected-card appearance without an added outline.
- Turning the ring moves one entry at a time and keeps it visible. Ordinary lists use the stock
  300 ms glide; recycled `table_client` rows use immediate scrolling and logical row indices.
- A short centre press opens the selected entry. This uses key **218**, the stock screen-toggle
  key, rather than key 171 (the separate Play/Pause action used incorrectly by V1.4R).
- Tapping another entry updates selection **before** its native action runs. If the tap leaves
  the menu open, centre opens the entry just tapped. No extra tap is required.
- Swiping keeps native scrolling and momentum. Selection survives while visible; after settling,
  an offscreen selection moves to the first fully visible selectable entry. Oversized entries
  fall back to the first partially visible one.
- Turning the wheel during touch momentum stops it at its current position and resumes menu
  navigation. Wheel and centre input during an active finger gesture are consumed without
  queuing an action. Touch-down interrupts an outstanding wheel glide.
- Returning to a surviving menu preserves a valid selection. Recreated menus start with their
  first visible entry; changing the entry count resets selection. No widget pointers survive
  between events, so recycled table rows cannot carry selection to an unrelated logical row.
- Outside supported menus, centre retains stock screen toggle and the wheel retains stock volume
  behavior. Play/Pause and long-press power behavior remain stock. Empty supported menus consume
  centre without opening anything or turning the screen off.

## Install and compatibility

Install like a stock update. Flash stock V1.32 to revert. The About screen and updater share the
`V1.6R` version literal; changing it allows installation over V1.5R, since the updater refuses an
identical version label. Only the audited V1.32 base firmware is supported.

Release hashes and build details are in `dist/manifest.json`.

## Implementation

Only `release/bin/demo` inside `rootfs.squashfs` changes. The kernel is byte-identical, and the
builder checks every other inode's name, type, mtime, mode, uid and gid against stock.

Four checked MIPS prologues redirect into a read/execute payload at `0xb00000`, using the final
unused `PT_NULL` program header. Trampolines restore the stock GOT base and resume each original
function after its PIC setup:

| Stock callback | Address | Purpose |
|---|---|---|
| `on_wm_keyup_before_fun` | `0x4e85c8` | Stock lock filter first, then wheel/centre navigation |
| `on_wm_tsdown_before_fun` | `0x4e8bd0` | Preserve stock touch processing and interrupt wheel glide |
| `widget_on_paint_border` | `0x6596a0` | Draw the selected entry outline after native children |
| `widget_dispatch` | `0x65e0ec` | Observe a native click before its app callback changes the UI |

Selection is stored in widget-owned integer properties on the navigation surface, independently
of AWTK's focused flag. The outline and centre action resolve that same logical selection against
the current entries. Centre dispatches a synchronous native `EVT_CLICK`, so a queued click cannot
hit a row rebound between selection and delivery. It never dereferences the target after delivery.
The canvas hook intersects the existing clip with the viewport and restores both clip and stroke
color; this firmware's `canvas_save/restore` do not save those properties.

Navigation requires a supported top-window name from `patch/contexts.inc`, screen-on and no
lock/test/guide/power-off/USB-link/Bluetooth-receive screen, and exactly one visible enabled
navigation surface. Only active `pages` children are searched. Horizontal and page-snapping scroll
views remain native. The bounded walk collects at most 256 targets in a non-virtual list; virtual
music tables navigate by total logical row count instead.

## Build and validation

Requires clang/lld/llvm-objcopy, squashfs-tools 4.7 (tested 4.7.5), and the original ZIP:
`154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00` (SHA-256).

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-build
python3 tools/test_patch.py /tmp/q2-build  # requires unicorn==2.1.4
```

The suite executes the actual patched MIPS payload and stock key/touch filters. UI services are
mocked; a separate scenario executes the stock canvas clip/color/rectangle code down to a mocked
LCD sink. Checks cover touch reselection, gesture suppression, momentum handoff, interrupted and
reversed wheel glides, recycled rows, menu return, count changes, empty/oversized rows, preserved
Play/Pause, power-release exclusions and stock key-lock parity. Every call checks preserved
registers/stack, and native calls check the PIC `$t9` convention.

Two fresh builds must produce identical `update.tar` files. Packaging verifies MD5 entries,
unchanged kernel and rootfs metadata, and a rootfs no larger than stock.

Before distributing as hardware-verified, check a Q2 on Home, Local Songs, folders and settings:
wheel → tap another item → centre; wheel → swipe → settle → centre; swipe → wheel during momentum;
rapid wheel reversals; return from a submenu; and screen-off wake, Play/Pause and long-press power.
Confirm the outline follows the item actually opened and the physical centre emits the expected key.
