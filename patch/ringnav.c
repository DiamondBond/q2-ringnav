/* Q2 V1.32: run on the UI thread, after the stock key-up lock filter.
 *
 * Ring navigation keeps a native AWTK focused widget on the list entry the wheel is on, glides the
 * list with the stock animated per-item scroll so that entry stays fully visible, and lets a short
 * center Play/Pause press activate it with the same async EVT_CLICK that widget_on_keyup dispatches
 * for the focused widget. Everywhere else (playing, volume, ...) the center key keeps its stock
 * play/pause behaviour.
 */
#include "stock.h"
#define STOP 11
#define EVT_CLICK 0x10c
#define KEY_PLAY 171
#define KEY_PREV 172
#define KEY_NEXT 173
#define GLIDE_MS 300
#define MAX_ENTRIES 256
#define I(p, o) (*(int *)((char *)(p) + (o)))
#define P(p, o) (*(void **)((char *)(p) + (o)))
#define B(p, o) (*(unsigned char *)((char *)(p) + (o)))

static int eq(const char *a, const char *b) {
    if (!a || !b) return 0;
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}

static int allowed(const char *name) {
    static const char *const names[] = {
#include "contexts.inc"
    };
    for (unsigned i = 0; i < sizeof(names) / sizeof(*names); ++i)
        if (eq(name, names[i])) return 1;
    return 0;
}

/* Only one visible navigation surface: never guess between two panes.
 * ponytail: bounded tree walk per detent; cache only if measured UI cost warrants it. */
static void find_surface(void *w, void **found, int *count, int depth, int *budget) {
    if (!w || !widget_get_visible(w) || !widget_get_prop_bool(w, "enable", 1)) return;
    if (depth == 16 || --*budget < 0) { *count = 2; return; }
    const char *type = widget_get_type(w);
    if (eq(type, "scroll_view") || eq(type, "table_client") || eq(type, "slide_menu")) {
        *found = w;
        ++*count;
        return;
    }
    if (eq(type, "pages")) {
        int active = widget_get_prop_int(w, "active", -1);
        if (active >= 0) find_surface(widget_get_child(w, active), found, count, depth + 1, budget);
        return;
    }
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n && *count < 2; ++i)
        find_surface(widget_get_child(w, i), found, count, depth + 1, budget);
}

static int clamp_step(int offset, int maximum, int delta) {
    if (maximum < 0) maximum = 0;
    if (offset < 0) offset = 0;
    if (offset > maximum) offset = maximum;
    if (delta > 0) return maximum - offset < delta ? maximum : offset + delta;
    return offset < -delta ? 0 : offset + delta;
}

/* A tap target has an EVT_CLICK handler. V1.32 widget emitter @0x60; emitter_on_with_tag items are
 * {ctx, id, type @8, handler, tag, working @0x14, pending_remove @0x15, next @0x20}. */
static int clickable(void *w) {
    void *emitter = P(w, 0x60);
    for (void *item = emitter ? P(emitter, 0) : (void *)0; item; item = P(item, 0x20))
        if (I(item, 8) == EVT_CLICK && !B(item, 0x15)) return 1;
    return 0;
}

/* widget_set_focused_internal keeps the focused flag in bit 7 of the u16 at 0x24. */
static int focused(void *w) { return B(w, 0x24) & 0x80; }

typedef struct { void **at; int n, cap, budget; } entries_t;

/* Visible, enabled tap targets in pre-order; a target's descendants belong to it.
 * ponytail: capped walk; raise MAX_ENTRIES if a real list outgrows it. */
static void collect(void *w, entries_t *s, int depth) {
    if (!w || !widget_get_visible(w) || !widget_get_prop_bool(w, "enable", 1)) return;
    if (depth == 16 || s->n == s->cap || --s->budget < 0) return;
    if (clickable(w)) { s->at[s->n++] = w; return; }
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) collect(widget_get_child(w, i), s, depth + 1);
}

static void *first_entry(void *w) {
    void *one = (void *)0;
    entries_t s = { &one, 0, 1, 256 };
    collect(w, &s, 0);
    return one;
}

/* Exactly what V1.32 widget_on_keyup does for an activate key on the focused widget. */
static void activate(void *w) {
    char click[0x30];
    widget_dispatch_async(w, pointer_event_init(click, EVT_CLICK, w, 0, 0));
}

/* Focus without widget_ensure_visible_in_viewport's instant viewport jump; the surface glides below. */
static void set_focus(void *old, void *w) {
    if (old && old != w) widget_set_focused_internal(old, 0);
    widget_set_focused_internal(w, 1);
}

/* Top edge of w in the coordinate space of ancestor surface. */
static int widget_y(void *w, void *surface) {
    int y = 0;
    for (void *p = w; p && p != surface; p = P(p, 0x48)) y += I(p, 4);
    return y;
}

/* dir -1/+1 moves the selection and glides it into view, 0 activates it. Returns 0 when the
 * surface has no tap targets so the caller can fall through to a plain pixel scroll. */
static int list_nav(void *w, int dir) {
    void *at[MAX_ENTRIES];
    entries_t s = { at, 0, MAX_ENTRIES, 2048 };
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) collect(widget_get_child(w, i), &s, 1);
    if (!s.n) return 0;
    int top = I(w, 0x84), h = I(w, 0x0c), cur = -1, first = -1;
    void *old = (void *)0;
    for (int i = 0; i < s.n; ++i) {
        int y = widget_y(at[i], w);
        int shown = y < top + h && y + I(at[i], 0x0c) > top;
        if (shown && first < 0) first = i;
        if (focused(at[i])) { old = at[i]; if (shown) cur = i; }
    }
    if (!dir) { if (cur >= 0) { activate(at[cur]); return STOP; } return 0; }
    int next = cur < 0 ? (first < 0 ? 0 : first) : cur + dir;
    if (next < 0 || next >= s.n) return STOP;
    int y = widget_y(at[next], w), eh = I(at[next], 0x0c);
    int want = y < top ? y : y + eh > top + h ? y + eh - h : top;
    set_focus(old, at[next]);
    if (want != top) scroll_view_scroll_delta_to(w, 0, want - top, GLIDE_MS);
    return STOP;
}

/* table_client re-binds a few table_row widgets (index @0x78) to the visible rows, so select by row
 * index. Rows rebind on every offset change, so scroll first and focus the freshly bound row after.
 * Returns 0 when there are no tap-target rows. */
static int table_nav(void *w, int dir, int row, int rows, int h) {
    int top = I(w, 0x80), cur = -1, any = 0;
    void *old = (void *)0;
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) {
        void *r = widget_get_child(w, i), *e = first_entry(r);
        if (!e) continue;
        any = 1;
        int k = I(r, 0x78);
        if (focused(e)) {
            old = e;
            if (k >= 0 && k < rows && k * row < top + h && (k + 1) * row > top) cur = k;
        }
    }
    if (!any) return 0;
    if (!dir) { if (cur >= 0) { activate(old); return STOP; } return 0; }
    int next = cur < 0 ? top / row + (top % row != 0) : cur + dir;
    if (cur < 0 && next >= rows) next = rows - 1;
    if (next < 0 || next >= rows) return STOP;
    int y = next * row;
    int want = clamp_step(y < top ? y : y + row > top + h ? y + row - h : top, row * rows - h, 0);
    if (want != top) {
        table_client_stop_animator_scroll(w);
        table_client_set_yoffset(w, want);
    }
    for (unsigned i = 0; i < widget_count_children(w); ++i) {
        void *r = widget_get_child(w, i), *e = first_entry(r);
        if (e && I(r, 0x78) == next) { set_focus(old, e); break; }
    }
    return STOP;
}

int ringnav(void *ctx, void *event) {
    int result = stock_keyup(ctx, event);
    if (result || !event) return result;
    unsigned key = (unsigned)I(event, 0x18);
    if (key != KEY_PLAY && key != KEY_PREV && key != KEY_NEXT) return result;
    if (!g_backlight_status || g_lockscreen_pageflag || g_testmode_flag ||
        g_guideflag || g_poweroff_state || g_usblink_status == 2 || bt__recv_pageflag)
        return result;
    void *wm = window_manager();
    void *top = window_manager_get_top_window(wm);
    if (!top || !allowed(widget_get_prop_str(top, "name", (void *)0))) return result;
    /* Consume navigation input during transitions/touch gestures, without changing volume. */
    if (window_manager_is_animating(wm) || window_manager_get_pointer_pressed(wm)) return STOP;
    void *w = (void *)0;
    int count = 0, budget = 512;
    find_surface(top, &w, &count, 0, &budget);
    int dir = key == KEY_NEXT ? 1 : key == KEY_PREV ? -1 : 0;
    /* Nothing to select: the center key stays play/pause; the ring never falls through to volume. */
    int fallback = dir ? STOP : result;
    if (count != 1) return fallback;
    const char *type = widget_get_type(w);
    if (eq(type, "slide_menu")) {
        if (dir > 0) slide_menu_scroll_to_next(w);
        else if (dir < 0) slide_menu_scroll_to_prev(w);
        else {
            int value = I(w, 0x78);
            void *e = value >= 0 ? first_entry(widget_get_child(w, value)) : (void *)0;
            if (!e) return result;
            activate(e);
        }
    } else if (eq(type, "table_client")) {
        /* Verified V1.32 fields: row height, rows, yoffset, widget height. */
        int row = I(w, 0x78), rows = I(w, 0x7c), h = I(w, 0x0c);
        if (row <= 0 || rows < 0 || h <= 0 || rows > 0x7fffffff / row) return fallback;
        if (table_nav(w, dir, row, rows, h)) return STOP;
        if (!dir) return result;
        table_client_stop_animator_scroll(w);
        table_client_set_yoffset(w, clamp_step(I(w, 0x80), row * rows - h, dir * RING_STEP));
    } else {
        /* Leave horizontal and page-snapping controls to stock touch input. */
        if (!*((unsigned char *)w + 0x91) || *((unsigned char *)w + 0x92)) return fallback;
        int vh = I(w, 0x7c), h = I(w, 0x0c);
        if (vh < 0 || h <= 0) return fallback;
        if (list_nav(w, dir)) return STOP;
        if (!dir) return result;
        int next = clamp_step(I(w, 0x84), vh - h, dir * RING_STEP);
        if (next != I(w, 0x84)) scroll_view_scroll_delta_to(w, 0, next - I(w, 0x84), GLIDE_MS);
    }
    return STOP;
}
