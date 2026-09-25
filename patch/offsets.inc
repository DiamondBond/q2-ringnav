/* Stock V1.32 layout and ABI constants shared by patch/ringnav.c and tools/test_patch.py.
 * The test harness parses this file, so a field change cannot leave the mocks behind.
 * Fields marked "same slot" are class-specific views of one offset. */
#define W_X 0x00
#define W_Y 0x04
#define W_W 0x08
#define W_H 0x0c
#define W_FOCUS 0x24            /* stock focused flag byte (tests) */
#define W_PARENT 0x48
#define W_EMITTER 0x60
#define EMIT_TYPE 0x08
#define EMIT_PENDING_REMOVE 0x15
#define EMIT_NEXT 0x20
#define ROW_HEIGHT 0x78         /* table_client row height */
#define ROW_INDEX 0x78          /* table_row logical index (same slot) */
#define SLIDE_INDEX 0x78        /* slide_menu current index (same slot) */
#define TABLE_ROWS 0x7c         /* table_client logical row count */
#define VIEW_CONTENT_H 0x7c     /* scroll_view content height (same slot) */
#define SCROLL_X 0x80           /* scroll_view horizontal offset */
#define TABLE_TOP 0x80          /* table_client viewport top (same slot) */
#define SCROLL_Y 0x84           /* scroll_view viewport top */
#define VIEW_HORIZONTAL 0x90    /* scroll_view xslidable */
#define VIEW_VERTICAL 0x91      /* scroll_view yslidable */
#define VIEW_SNAP 0x92          /* scroll_view snap_to_page */
#define TABLE_ANIMATOR 0xd0
#define VIEW_ANIMATOR 0xe8
#define EVENT_TYPE 0x00
#define EVENT_KEY 0x18
#define EVT_CLICK 0x10c
#define CANVAS_X 0x00
#define CANVAS_Y 0x04
#define CANVAS_LCD 0x38
#define LCD_FILL_COLOR 0xbc
#define LCD_STROKE_COLOR 0xc0
/* Selection outline tuning. RADIUS > 2 or the stock rounded path squares off; tests read these.
 * The shade uses the same stock dark surface as the fill at an alpha that keeps the white
 * outline above 3:1 on pure white art (0x99 is the floor); on dark rows it matches the stock
 * background exactly and disappears. */
#define RADIUS 9
#define FILL_RGB 0x2b2b2b
#define FILL_ALPHA 0x40
#define SHADE_ALPHA 0xb3
#define KEY_CENTER 218
#define KEY_PREV 172
#define KEY_NEXT 173
#define KEY_PLAY 171
#define BOOT_KEY_GUARD 0xa37c8a /* raw flag address, no symbol in the audited binary */
/* Stock wheel lockout byte at 0xa37c89, no symbol in the audited binary: a key-down of Return,
 * Play/Pause, Centre, 222 or 223 writes 8, a 100 ms timer decrements it, and while it is positive
 * the stock key-up filter drops wheel releases. The payload reads it before holding a detent and
 * clears it when a button is released, so the wheel is not dead for up to 800 ms. */
#define WHEEL_LATCH 0xa37c89

/* slide_menu_scroll_to @0x5f3400 and completion @0x5f3654; animator
 * start @0x665ab0, time_elapse @0x6660d4, scroll_set_params @0x682124. */
#define SLIDE_SPACER 0x84
#define SLIDE_OFFSET 0x94
#define SLIDE_ANIMATOR 0xc8
#define ANIM_ELAPSED 0x10
#define ANIM_START_TIME 0x18
#define ANIM_DURATION 0x20
#define ANIM_X_TO 0x60
#define SLIDE_EASING 8          /* stock scroll_to easing */
#define EVT_ANIM_END 0x125
