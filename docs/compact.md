# Compact audit and device acceptance

V3.1R and V3.1C share one navigation payload. `--compact` enables a single extra
payload function and build-time edits in `tools/compact.py`; normal receives no
compact executable sites or UI assets. `patch/compact.json` records the original
asset hashes and full MIPS instructions. The builder also pins the complete stock
ZIP and executable, rejects mismatches, and records every changed asset/site.

AWTK binary UI files contain a four-byte magic, recursive widgets with a 32-byte
type and four signed geometry fields, NUL-separated properties and child/end
markers. Decode/encode must round-trip exactly before editing. Only nine named
local assets are accepted. The primary `view_navbar` stays allocated but invisible
and disabled, including dynamically recreated children. Separate action bars are
moved into its space. The global status bar is outside these assets.

`PITCH = 65` is shared by all build-time row geometry edits, native row-height
resets and artwork offset divisors. Row bodies remain eight pixels shorter than
pitch. Font/style definitions are untouched. The 52-pixel artwork fits within the
57-pixel row body; its inset changes from nine to two pixels. The stock image draw
mode and cover loaders remain responsible for proportional artwork and missing
image fallback. Full-height text/icon containers are shortened with their button.
Titles and metadata keep their heights, with adjusted vertical positions.

Native local row-pool constructors are at 0x523038 (folder), 0x4aa2cc (songs),
0x4b0efc (local categories) and 0x4a4ae8 (album list/grid). The album grid branch
is unchanged. Album detail, artist track and playlist constructors have their own
explicit sites in the audit. Folder reset at 0x5217d4, return offset division at
0x521a84 and scrolling cover division at 0x5228f8 all use the same compact pitch.
The category cover callback originally divides by 120 despite using 78-pixel
rows; compact corrects its audited divisor at 0x4b0608 to 65. Rebinding and delayed
cover callbacks keep the same widget geometry and saved cover preferences.

The stock long-key function at 0x4e873c retains all instructions except the final
Home call at 0x4e8924. Stock power, lock, test and key-lock gates and its release
latch execute first. Compact cancels centre confirmation and spin state, checks
the shared screen/navigation restrictions, then calls the stock switch function
with `playing_page` and `{0, 0, 0xff, 2}`. The `0xff` context skips player_start.
The stock key-up filter consumes the following release. No short-Return callback
or other long-key destination changes.

## Device checklist (required for both exact ZIPs before publication)

Record results against the generated ZIP checksums. The generated acceptance JSON
starts with every check false; mark a category true only after completing it.

- **readability**: Browse Folder and Local Songs, artists, genres, albums, album
  tracks, artist tracks/albums and playlists. Check all four complete ordinary
  rows, long filenames, two-line metadata, non-Latin text and the selection
  outline. Touch and centre must activate the same item at every row and edge.
- **toolbar**: Compact hides the entire primary toolbar (including Home,
  search/multi-select and Now Playing icons), keeps the status bar, and reclaims
  its space after page recreation and nested folder returns. Normal stays stock.
- **artwork**: Toggle folder icons/covers off/on, restart to verify saved settings,
  and try missing covers, square/non-square art, fast scrolling and recycled rows.
  Check late-arriving covers, alignment, no overlap and correct artwork indexing
  after child/grandchild returns. Test both saved album display modes.
- **return**: Short Return traverses folders and other pages as stock. Hold Return
  and release, repeat holds, try already playing and an empty playback queue.
  Compact opens/stays on Now Playing without restarting audio; normal opens Home.
  Arm centre confirmation then hold Return; no delayed item should open. Repeat
  screen-off, locked, power-off/USB/BT restrictions and modal-blocked navigation.
  Other long keys must remain stock.
- **retained_controls**: Use tabs, Play All, sorting, playlist import/export,
  rename/delete and all separately retained action/editing controls. Verify
  remembered selection after sorting and folder/album/query returns.
- **excluded_screens**: Verify home carousel, Now Playing, settings, online
  services, dialogs and scanning/editing screens retain stock layouts and work.

Emulator tests validate native constructors, stock input gates and the shared
navigation behavior with mocked toolkit services. They do not establish visual
readability, actual touch hit-testing, rendering or playback behavior on hardware.
