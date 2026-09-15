/* Q2 V1.32: run on the UI thread, after the stock key-up lock filter. */
#include "stock.h"
#define STOP 11
#define I(p, o) (*(int *)((char *)(p) + (o)))
#define P(p, o) (*(void **)((char *)(p) + (o)))

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

int ringnav(void *ctx, void *event) {
    int result = stock_keyup(ctx, event);
    if (result || !event) return result;
    unsigned key = (unsigned)I(event, 0x18);
    if (key != 172 && key != 173) return result;
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
    if (count != 1) return STOP;
    const char *type = widget_get_type(w);
    int delta = key == 173 ? RING_STEP : -RING_STEP;
    if (eq(type, "slide_menu")) {
        if (key == 173) slide_menu_scroll_to_next(w);
        else slide_menu_scroll_to_prev(w);
    } else if (eq(type, "table_client")) {
        /* Verified V1.32 fields: row height, rows, yoffset, widget height. */
        int row = I(w, 0x78), rows = I(w, 0x7c), h = I(w, 0x0c);
        if (row <= 0 || rows < 0 || h <= 0 || rows > 0x7fffffff / row) return STOP;
        table_client_stop_animator_scroll(w);
        table_client_set_yoffset(w, clamp_step(I(w, 0x80), row * rows - h, delta));
    } else {
        /* Leave horizontal and page-snapping controls to stock touch input. */
        if (!*((unsigned char *)w + 0x91) || *((unsigned char *)w + 0x92)) return STOP;
        int vh = I(w, 0x7c), h = I(w, 0x0c);
        if (vh < 0 || h <= 0) return STOP;
        void *animator = P(w, 0xe8);
        if (animator) {
            widget_animator_pause(animator);
            widget_animator_destroy(animator);
            P(w, 0xe8) = (void *)0;
        }
        scroll_view_set_offset(w, I(w, 0x80), clamp_step(I(w, 0x84), vh - h, delta));
    }
    return STOP;
}
