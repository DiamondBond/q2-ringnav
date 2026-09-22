/* Logical menu selection is independent of native touch focus. Stock code owns gestures. */
#include "stock.h"
#define STOP 11
#define EVT_CLICK 0x10c
#define KEY_CENTER 218
#define KEY_PREV 172
#define KEY_NEXT 173
#define GLIDE_MS 300
#define DOUBLE_CLICK_MS 400
#define ACCEL_MS 140
#define ACCEL_DIV 3
#define ACCEL_MAX 8
#define MAX_ENTRIES 256
#define I(p, o) (*(int *)((char *)(p) + (o)))
#define P(p, o) (*(void **)((char *)(p) + (o)))
#define B(p, o) (*(unsigned char *)((char *)(p) + (o)))

/* Writable state lives in the zero-filled page the builder maps past the payload text.
 * last_center arms the screen toggle pair; wheel_* scale repeated fast detents. */
typedef struct {
    unsigned last_center; /* release time of the last selection press */
    void *center_top;     /* top window of that press */
    void *center_surface; /* navigation surface of that press */
    unsigned last_wheel;  /* time of the previous wheel detent */
    int wheel_dir;        /* direction of that detent */
    unsigned wheel_run;   /* consecutive fast detents in that direction */
} scratch_t;
static scratch_t st __attribute__((section(".scratch")));

static int allowed(const char *name) {
    static const char *const names[] = {
#include "contexts.inc"
    };
    for (unsigned i = 0; i < sizeof(names) / sizeof(*names); ++i)
        if (!tk_strcmp(name, names[i])) return 1;
    return 0;
}

/* Only one visible navigation surface: never guess between two panes.
 * ponytail: bounded tree walk per event; a persistent cache would go stale because the tree
 * changes without notification, so it waits for a measured stutter. */
static void find_surface(void *w, void **found, int *count, int depth, int *budget) {
    if (!w || !widget_get_visible(w) || !widget_get_prop_bool(w, "enable", 1)) return;
    if (depth == 16 || --*budget < 0) {
        *count = 2;
        return;
    }
    const char *type = widget_get_type(w);
    if (!tk_strcmp(type, "scroll_view") || !tk_strcmp(type, "table_client") ||
        !tk_strcmp(type, "slide_menu")) {
        *found = w;
        ++*count;
        return;
    }
    if (!tk_strcmp(type, "pages")) {
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
    int next = (offset < 0 ? 0 : offset > maximum ? maximum : offset) + delta;
    return next < 0 ? 0 : next > maximum ? maximum : next;
}

/* Consecutive detents closer than ACCEL_MS in one direction step further, like spinning
 * an iPod wheel: x2 every ACCEL_DIV detents, capped at ACCEL_MAX. A pause or reversal
 * starts over. Stock rate-limits wheel keys to roughly one per 80-200 ms, so real ticks
 * land inside the acceleration window. */
static int wheel_step(int dir, unsigned now) {
    if (st.last_wheel && now - st.last_wheel <= ACCEL_MS && st.wheel_dir == dir)
        ++st.wheel_run;
    else
        st.wheel_run = 1;
    st.last_wheel = now;
    st.wheel_dir = dir;
    int step = 1;
    for (unsigned run = st.wheel_run; run >= ACCEL_DIV && step < ACCEL_MAX; run -= ACCEL_DIV)
        step *= 2;
    return step;
}

/* A tap target has an EVT_CLICK handler. V1.32 widget emitter @0x60; emitter_on_with_tag items are
 * {ctx, id, type @8, handler, tag, working @0x14, pending_remove @0x15, next @0x20}. */
static int clickable(void *w) {
    void *emitter = P(w, 0x60);
    for (void *item = emitter ? P(emitter, 0) : (void *)0; item; item = P(item, 0x20))
        if (I(item, 8) == EVT_CLICK && !B(item, 0x15)) return 1;
    return 0;
}

typedef struct {
    void **at;
    int n, cap, budget;
} entries_t;

/* Visible, enabled tap targets in pre-order; a target's descendants belong to it.
 * ponytail: capped walk; raise MAX_ENTRIES if a real list outgrows it. */
static void collect(void *w, entries_t *s, int depth) {
    if (!w || !widget_get_visible(w) || !widget_get_prop_bool(w, "enable", 1)) return;
    if (depth == 16 || s->n == s->cap || --s->budget < 0) return;
    if (clickable(w)) {
        s->at[s->n++] = w;
        return;
    }
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) collect(widget_get_child(w, i), s, depth + 1);
}

static void *first_entry(void *w) {
    void *one = (void *)0;
    entries_t s = { &one, 0, 1, 256 };
    collect(w, &s, 0);
    return one;
}

/* Widget-owned properties die with the surface; never retain recycled row pointers. */
#define SEL "_ringnav_index"
#define TOUCH "_ringnav_touch"
#define COUNT "_ringnav_count"

typedef struct {
    int x, y, w, h;
} rect_t;
typedef struct {
    void *w, *at[MAX_ENTRIES];
    int id[MAX_ENTRIES], n, kind, rows, row, top, height;
} menu_t;

static int usable(void) {
    return g_backlight_status && !g_lockscreen_pageflag && !g_testmode_flag && !g_guideflag &&
           !g_poweroff_state && g_usblink_status != 2 && !bt__recv_pageflag;
}

static int allowed_top(void *top) {
    return top && allowed(widget_get_prop_str(top, "name", (void *)0));
}

/* One visible navigation surface under an already allowlisted top window. */
static void *surface_under(void *top) {
    void *w = (void *)0;
    int count = 0, budget = 512;
    find_surface(top, &w, &count, 0, &budget);
    return count == 1 ? w : (void *)0;
}

static void *surface(void) {
    if (!usable()) return (void *)0;
    void *wm = window_manager();
    if (window_manager_is_animating(wm)) return (void *)0;
    void *top = window_manager_get_top_window(wm);
    return allowed_top(top) ? surface_under(top) : (void *)0;
}

static int kind(void *w) {
    const char *t = widget_get_type(w);
    if (!tk_strcmp(t, "slide_menu")) return 3;
    if (!tk_strcmp(t, "table_client")) return 2;
    return !tk_strcmp(t, "scroll_view") && B(w, 0x91) && !B(w, 0x92) ? 1 : 0;
}

static void prop(void *w, const char *name, int value) {
    if (widget_get_prop_int(w, name, -1) != value) widget_set_prop_int(w, name, value);
}

static int load(menu_t *m, void *w) {
    m->w = w;
    m->n = 0;
    m->kind = kind(w);
    m->height = I(w, 0x0c);
    if (!m->kind || m->height <= 0) return 0;
    m->top = m->kind == 3 ? 0 : I(w, m->kind == 2 ? 0x80 : 0x84);
    m->row = m->kind == 2 ? I(w, 0x78) : 0;
    m->rows = m->kind == 2 ? I(w, 0x7c) : 0;
    if (m->kind == 2 && (m->row <= 0 || m->rows < 0 || m->rows > 0x7fffffff / m->row)) return 0;
    if (m->kind == 1 && I(w, 0x7c) < 0) return 0;
    unsigned n = widget_count_children(w);
    if (m->kind == 1) {
        entries_t s = { m->at, 0, MAX_ENTRIES, 2048 };
        for (unsigned i = 0; i < n; ++i) collect(widget_get_child(w, i), &s, 1);
        m->n = s.n;
        m->rows = s.n;
        for (int i = 0; i < m->n; ++i) m->id[i] = i;
    } else {
        if (m->kind == 3) m->rows = (int)n;
        for (unsigned i = 0; i < n && m->n < MAX_ENTRIES; ++i) {
            void *r = widget_get_child(w, i), *e = first_entry(r);
            int id = m->kind == 2 ? I(r, 0x78) : (int)i;
            if (e && id >= 0 && id < m->rows) {
                m->at[m->n] = e;
                m->id[m->n++] = id;
            }
        }
    }
    if (widget_get_prop_int(w, COUNT, -1) != m->rows) {
        prop(w, SEL, -1);
        prop(w, COUNT, m->rows);
    }
    return 1;
}

static rect_t bounds(menu_t *m, int i) {
    void *e = m->at[i];
    rect_t r = { 0, 0, I(e, 8), I(e, 0x0c) };
    for (void *p = e; p && p != m->w; p = P(p, 0x48)) {
        r.x += I(p, 0);
        r.y += I(p, 4);
    }
    if (m->kind != 3) r.y -= m->top;
    if (m->kind == 1) r.x -= I(m->w, 0x80);
    return r;
}

static int index_of(menu_t *m, int id) {
    for (int i = 0; i < m->n; ++i)
        if (m->id[i] == id) return i;
    return -1;
}

static int moving(menu_t *m) {
    return m->kind == 1 ? P(m->w, 0xe8) != 0 : m->kind == 2 ? P(m->w, 0xd0) != 0 : 0;
}

static void stop_scroll(menu_t *m) {
    if (m->kind == 2)
        table_client_stop_animator_scroll(m->w);
    else if (m->kind == 1 && P(m->w, 0xe8)) {
        /* Same pause/destroy/null sequence as stock table_client_stop_animator_scroll. */
        void *a = P(m->w, 0xe8);
        widget_animator_pause(a);
        widget_animator_destroy(a);
        P(m->w, 0xe8) = (void *)0;
    }
}

/* Keep selection during native momentum and wheel glides. Once settled, repair an offscreen
 * selection using the first fully visible target (partially visible only for oversized rows). */
static int reconcile(menu_t *m, int settle) {
    int id = m->kind == 3 ? I(m->w, 0x78) : widget_get_prop_int(m->w, SEL, -1);
    int cur = index_of(m, id), first = -1, partial = -1;
    if (m->kind == 3) return cur;
    for (int i = 0; i < m->n; ++i) {
        rect_t r = bounds(m, i);
        if (r.y < m->height && r.y + r.h > 0) {
            if (partial < 0) partial = i;
            if (r.y >= 0 && r.y + r.h <= m->height) {
                first = i;
                break;
            }
        }
    }
    if (cur >= 0) {
        rect_t r = bounds(m, cur);
        if ((r.y < m->height && r.y + r.h > 0) || !settle) return cur;
    } else if (id >= 0 && id < m->rows && !settle)
        return -1;
    cur = first >= 0 ? first : partial;
    prop(m->w, SEL, cur >= 0 ? m->id[cur] : -1);
    return cur;
}

/* Stock paints children first and calls this with the surface's canvas origin restored.
 * Explicit outline avoids theme-dependent focus and doesn't overwrite playing/pressed styles. */
int ringnav_paint(void *w, void *canvas) {
    int result = stock_paint(w, canvas);
    if (!w || !canvas || !kind(w) || surface() != w) return result;
    menu_t m;
    if (!load(&m, w) || m.kind == 3) return result; /* Home already shows its selected card. */
    int i = reconcile(&m, !moving(&m) && !window_manager_get_pointer_pressed(window_manager()));
    if (i < 0) return result;
    rect_t r = bounds(&m, i), old, clip;
    if (r.w < 5 || r.h < 5 || !P(canvas, 0x38)) return result;
    canvas_get_clip_rect(canvas, &old);
    int x = I(canvas, 0), y = I(canvas, 4);
    clip.x = old.x > x ? old.x : x;
    clip.y = old.y > y ? old.y : y;
    int right = old.x + old.w < x + I(w, 8) ? old.x + old.w : x + I(w, 8);
    int bottom = old.y + old.h < y + m.height ? old.y + old.h : y + m.height;
    clip.w = right - clip.x;
    clip.h = bottom - clip.y;
    if (clip.w <= 0 || clip.h <= 0) return result;
    unsigned color = (unsigned)I(P(canvas, 0x38), 0xc0);
    canvas_set_clip_rect(canvas, &clip);
    canvas_set_stroke_color(canvas, 0xffffffffu);
    canvas_stroke_rect(canvas, r.x + 1, r.y + 1, r.w - 2, r.h - 2);
    canvas_stroke_rect(canvas, r.x + 2, r.y + 2, r.w - 4, r.h - 4);
    canvas_set_stroke_color(canvas, color);
    canvas_set_clip_rect(canvas, &old);
    return result;
}

int ringnav_touch(void *ctx, void *event) {
    int result = stock_touch(ctx, event);
    /* A tap is a fresh interaction: it cancels a pending screen-toggle pair and any spin. */
    st.last_center = 0;
    st.center_top = st.center_surface = (void *)0;
    st.last_wheel = 0;
    st.wheel_run = 0;
    void *w = surface();
    menu_t m;
    if (!result && w && load(&m, w)) {
        stop_scroll(&m);
        prop(w, TOUCH, 1);
        widget_invalidate_force(w, (void *)0);
    }
    return result; /* The very same touch continues through the stock tap/drag handlers. */
}

/* Nearest collected ancestor of a tap: a clickable child selects the row that owns it. */
static int selects(menu_t *m, void *target) {
    for (int depth = 0; target && depth < 32; ++depth) {
        for (int i = 0; i < m->n; ++i)
            if (m->at[i] == target) return i;
        if (target == m->w) break;
        target = P(target, 0x48);
    }
    return -1;
}

/* Observe actual clicks BEFORE app callbacks can navigate or destroy/rebind their widgets.
 * Do not turn pointer-down into selection: a swipe is not a tap. */
int ringnav_dispatch(void *target, void *event) {
    if (target && event && I(event, 0) == EVT_CLICK) {
        void *w = surface();
        menu_t m;
        if (w && load(&m, w)) {
            int i = selects(&m, target);
            if (i >= 0) {
                prop(w, SEL, m.id[i]);
                widget_invalidate_force(w, (void *)0);
            }
        }
    }
    return stock_dispatch(target, event);
}

int ringnav(void *ctx, void *event) {
    int result = stock_keyup(ctx, event);
    if (result || !event) return result;
    unsigned key = (unsigned)I(event, 0x18);
    if (key != KEY_CENTER && key != KEY_PREV && key != KEY_NEXT) return result;
    if (!usable()) return result;
    /* Match the stock power-key release exclusions, including release after long press. */
    if (key == KEY_CENTER &&
        (g_power_longkey || g_ingore_bootkey_flag || *(volatile unsigned char *)0xa37c8a))
        return result;
    void *wm = window_manager(), *top = window_manager_get_top_window(wm);
    if (!allowed_top(top)) return result;
    if (window_manager_is_animating(wm) || window_manager_get_pointer_pressed(wm)) return STOP;
    void *w = surface_under(top);
    int dir = key == KEY_NEXT ? 1 : key == KEY_PREV ? -1 : 0;
    if (!w) return dir ? STOP : result;
    menu_t m;
    if (!load(&m, w)) return dir ? STOP : result;
    int touch = widget_get_prop_int(w, TOUCH, 0);
    if (touch) stop_scroll(&m);
    int cur = reconcile(&m, touch || !moving(&m));
    unsigned now = (unsigned)time_now_ms();
    if (!dir) {
        /* Only a second release on the very same screen is a screen-toggle pair. */
        if (st.last_center && now - st.last_center <= DOUBLE_CLICK_MS && st.center_top == top &&
            st.center_surface == w) {
            st.last_center = 0;
            st.center_top = st.center_surface = (void *)0;
            /* Second release of a double click: the stock short press toggles the screen. */
            return result;
        }
        if (cur < 0) return STOP;
        st.last_center = now;
        st.center_top = top;
        st.center_surface = w;
        st.last_wheel = 0; /* A press ends any spin. */
        st.wheel_run = 0;
        prop(w, SEL, m.id[cur]);
        widget_invalidate_force(w, (void *)0);
        char click[0x30];
        /* Synchronous native click: no queued recycled row can change the activated item. */
        stock_dispatch(m.at[cur], pointer_event_init(click, EVT_CLICK, m.at[cur], 0, 0));
        return STOP; /* No widget access after the app callback. */
    }
    st.last_center = 0; /* A wheel detent ends the double-click window. */
    st.center_top = st.center_surface = (void *)0;
    prop(w, TOUCH, 0);
    int step = wheel_step(dir, now);
    if (m.kind == 3) {
        if (dir > 0)
            slide_menu_scroll_to_next(w);
        else
            slide_menu_scroll_to_prev(w);
    } else if (m.n) {
        int id = widget_get_prop_int(w, SEL, -1);
        int next = id < 0 ? (cur >= 0 ? m.id[cur] : 0) : id + dir * step;
        if (next < 0) next = 0;
        if (next >= m.rows) next = m.rows - 1;
        if (next == id) return STOP;
        int y, h;
        if (m.kind == 2) {
            y = next * m.row;
            h = m.row;
        } else {
            rect_t r = bounds(&m, next);
            y = r.y + m.top;
            h = r.h;
        }
        int want = y < m.top ? y : y + h > m.top + m.height ? y + h - m.height : m.top;
        want = clamp_step(want, (m.kind == 2 ? m.rows * m.row : I(w, 0x7c)) - m.height, 0);
        prop(w, SEL, next);
        /* Reversing into the current viewport must cancel the previous glide away from it. */
        if (want == m.top && moving(&m)) stop_scroll(&m);
        if (want != m.top) {
            if (m.kind == 2) {
                stop_scroll(&m);
                table_client_scroll_to(w, want);
            } else
                scroll_view_scroll_delta_to(w, 0, want - m.top, GLIDE_MS);
        }
    } else {
        int max = (m.kind == 2 ? m.rows * m.row : I(w, 0x7c)) - m.height;
        int next = clamp_step(m.top, max, dir * RING_STEP * step);
        if (m.kind == 2) {
            stop_scroll(&m);
            table_client_scroll_to(w, next);
        } else if (next != m.top)
            scroll_view_scroll_delta_to(w, 0, next - m.top, GLIDE_MS);
    }
    widget_invalidate_force(w, (void *)0);
    return STOP;
}
