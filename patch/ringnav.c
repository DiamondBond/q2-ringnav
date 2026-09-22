/* Logical menu selection is independent of native touch focus. Stock code owns gestures. */
#include "offsets.inc"
#include "stock.h"
#define STOP 11
#define GLIDE_MS 300
#define DOUBLE_CLICK_MS 400
#define ACCEL_MS 140
#define ACCEL_DIV 3
#define ACCEL_MAX 8
#define MAX_ENTRIES 512
#define POS_MEM 128
/* RADIUS, FILL_RGB, FILL_ALPHA and SHADE_ALPHA come from offsets.inc; the colors pack their bytes
 * at compile time (little-endian r,g,b,a). The outline is opaque neutral white, never the playing
 * red, seated on a dark shade of the stock surface so bright album art cannot wash it out. */
#define FILL_COLOR ((FILL_ALPHA << 24) | FILL_RGB)
#define SHADE_COLOR ((SHADE_ALPHA << 24) | FILL_RGB)
#define OUTLINE_COLOR 0xffffffffu
#define I(p, o) (*(int *)((char *)(p) + (o)))
#define P(p, o) (*(void **)((char *)(p) + (o)))
#define B(p, o) (*(unsigned char *)((char *)(p) + (o)))

/* Writable state lives in the zero-filled page the builder maps past the payload text.
 * last_center arms the screen toggle pair; wheel_* scale repeated fast detents; pos_* remember
 * the selected row per audited context across page recreation; reveal_* pin the recall glide so
 * an interruption cannot silently rewrite that memory. */
typedef struct {
    unsigned last_center;       /* release time of the last selection press */
    void *center_top;           /* top window of that press */
    void *center_surface;       /* navigation surface of that press */
    unsigned last_wheel;        /* time of the previous wheel detent */
    int wheel_dir;              /* direction of that detent */
    unsigned wheel_run;         /* consecutive fast detents in that direction */
    int pos_id[POS_MEM];        /* last selected logical row + 1 per audited context; 0 = unused */
    unsigned pos_hash[POS_MEM]; /* that row's text hash; 0 when the row has no usable text */
    void *reveal_surface;       /* surface of the interrupted recall glide, 0 when none */
    int reveal_id;              /* logical row that glide was bringing into view */
} scratch_t;
static scratch_t st __attribute__((section(".scratch")));

typedef struct {
    int x, y, w, h;
} rect_t;
typedef struct {
    void *w, *at[MAX_ENTRIES];
    int id[MAX_ENTRIES], n, kind, rows, row, height;
} menu_t;
/* Single shared view: no entry point keeps a menu live across a nested load(). */
static menu_t g_menu __attribute__((section(".scratch")));

/* Index of an audited top-window name, or -1. The index is remembered instead of the name
 * pointer: AWTK owns and frees the window's name string. */
static int context_id(const char *name) {
    static const char *const names[] = {
#include "contexts.inc"
    };
    if (!name) return -1;
    for (unsigned i = 0; i < sizeof(names) / sizeof(*names); ++i)
        if (!tk_strcmp(name, names[i])) return (int)i;
    return -1;
}

/* The view kinds load() actually navigates: a vertical scroll view, a table client or a slide
 * menu. A horizontal or page-snapping scroll view is not a candidate, so it cannot make a page
 * look like it has two panes. */
static int kind(void *w) {
    const char *t = widget_get_type(w);
    if (!tk_strcmp(t, "slide_menu")) return 3;
    if (!tk_strcmp(t, "table_client")) return 2;
    return !tk_strcmp(t, "scroll_view") && B(w, VIEW_VERTICAL) && !B(w, VIEW_HORIZONTAL) ? 1 : 0;
}

/* Collect up to two candidate panes. ponytail: bounded tree walk per event; a persistent cache
 * would go stale because the tree changes without notification, so it waits for a measured
 * stutter. */
static void find_surface(void *w, void **found, int *count, int *aborted, int depth, int *budget) {
    if (!w || !widget_get_visible(w) || !widget_get_prop_bool(w, "enable", 1)) return;
    if (depth == 16 || --*budget < 0) {
        *aborted = 1;
        return;
    }
    if (kind(w)) {
        if (*count < 2) found[*count] = w;
        ++*count;
        return;
    }
    if (!tk_strcmp(widget_get_type(w), "pages")) {
        int active = widget_get_prop_int(w, "active", -1);
        if (active >= 0)
            find_surface(widget_get_child(w, active), found, count, aborted, depth + 1, budget);
        return;
    }
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n && *count < 2; ++i)
        find_surface(widget_get_child(w, i), found, count, aborted, depth + 1, budget);
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
    unsigned run = st.wheel_run / ACCEL_DIV;
    return run < 3 ? 1 << run : ACCEL_MAX; /* 3 = log2(ACCEL_MAX) */
}

/* A tap target has an EVT_CLICK handler. V1.32 widget emitter @0x60; emitter_on_with_tag items are
 * {ctx, id, type @8, handler, tag, working @0x14, pending_remove @0x15, next @0x20}. */
static int clickable(void *w) {
    void *emitter = P(w, W_EMITTER);
    for (void *item = emitter ? P(emitter, 0) : (void *)0; item; item = P(item, EMIT_NEXT))
        if (I(item, EMIT_TYPE) == EVT_CLICK && !B(item, EMIT_PENDING_REMOVE)) return 1;
    return 0;
}

typedef struct {
    void **at;
    int n, cap, budget;
} entries_t;

/* Visible, enabled tap targets in pre-order; a target's descendants belong to it.
 * ponytail: capped walk; raise MAX_ENTRIES if a real list outgrows 512. */
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

static int usable(void) {
    return g_backlight_status && !g_lockscreen_pageflag && !g_testmode_flag && !g_guideflag &&
           !g_poweroff_state && g_usblink_status != 2 && !bt__recv_pageflag;
}

static int allowed_top(void *top) {
    return top && context_id(widget_get_prop_str(top, "name", (void *)0)) >= 0;
}

/* The navigable pane under an already allowlisted top window. With two visible panes, only the
 * one that already holds the selection is used; anything else stays untouched, never guessed. */
static void *surface_under(void *top) {
    void *found[2] = { (void *)0, (void *)0 };
    int count = 0, aborted = 0, budget = 512;
    find_surface(top, found, &count, &aborted, 0, &budget);
    if (aborted || count == 0) return (void *)0;
    if (count == 1) return found[0];
    int first = widget_get_prop_int(found[0], SEL, -1) >= 0;
    int second = widget_get_prop_int(found[1], SEL, -1) >= 0;
    return first == second ? (void *)0 : (first ? found[0] : found[1]);
}

static void *surface(void) {
    if (!usable()) return (void *)0;
    void *wm = window_manager();
    if (window_manager_is_animating(wm)) return (void *)0;
    void *top = window_manager_get_top_window(wm);
    return allowed_top(top) ? surface_under(top) : (void *)0;
}

static void prop(void *w, const char *name, int value) {
    if (widget_get_prop_int(w, name, -1) != value) widget_set_prop_int(w, name, value);
}

/* FNV-1a of the first non-empty text property in a small row subtree; 0 means "no identity". */
static const char *row_text(void *w, int depth, int *budget) {
    if (!w || depth == 4 || --*budget < 0) return (void *)0;
    const char *s = widget_get_prop_str(w, "text", (void *)0);
    if (s && *s) return s;
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) {
        const char *found = row_text(widget_get_child(w, i), depth + 1, budget);
        if (found) return found;
    }
    return (void *)0;
}

static unsigned row_hash(void *w) {
    int budget = 32;
    const char *s = row_text(w, 0, &budget);
    if (!s) return 0;
    unsigned h = 2166136261u;
    for (; *s; ++s) h = (h ^ (unsigned char)*s) * 16777619u;
    return h;
}

static int recall(int ctx, unsigned *hash) {
    if (ctx < 0 || ctx >= POS_MEM) return -1;
    if (hash) *hash = st.pos_hash[ctx];
    return st.pos_id[ctx] - 1;
}

/* Context of the active top window; every caller already holds a navigation surface. */
static int context_now(void) {
    void *top = window_manager_get_top_window(window_manager());
    return top ? context_id(widget_get_prop_str(top, "name", (void *)0)) : -1;
}

static int index_of(menu_t *m, int id);
static void reveal(menu_t *m, int id, int cancel);

/* Remember where the user was. Widget props die with a recreated page; this survives it.
 * Non-virtual lists also remember the row text, so a reordered list restores the same item. */
static void select(menu_t *m, int id) {
    unsigned hash = 0;
    if (id >= 0) {
        int ctx = context_now();
        if (m->kind == 1) {
            int i = index_of(m, id);
            if (i >= 0) hash = row_hash(m->at[i]);
        }
        if (ctx >= 0 && ctx < POS_MEM) {
            st.pos_id[ctx] = id + 1;
            st.pos_hash[ctx] = hash;
        }
    }
    prop(m->w, SEL, id);
}

static int load(menu_t *m, void *w) {
    m->w = w;
    m->n = 0;
    m->kind = kind(w);
    m->height = I(w, W_H);
    if (!m->kind || m->height <= 0) return 0;
    m->row = m->kind == 2 ? I(w, ROW_HEIGHT) : 0;
    m->rows = m->kind == 2 ? I(w, TABLE_ROWS) : 0;
    if (m->kind == 2 && (m->row <= 0 || m->rows < 0 || m->rows > 0x7fffffff / m->row)) return 0;
    unsigned n = widget_count_children(w);
    if (m->kind == 1) {
        if (I(w, VIEW_CONTENT_H) < 0) return 0;
        entries_t s = { m->at, 0, MAX_ENTRIES, 4096 };
        for (unsigned i = 0; i < n; ++i) collect(widget_get_child(w, i), &s, 1);
        m->n = s.n;
        m->rows = s.n;
        for (int i = 0; i < m->n; ++i) m->id[i] = i;
    } else {
        if (m->kind == 3) m->rows = (int)n;
        for (unsigned i = 0; i < n && m->n < MAX_ENTRIES; ++i) {
            void *r = widget_get_child(w, i), *e = first_entry(r);
            int id = m->kind == 2 ? I(r, ROW_INDEX) : (int)i;
            if (e && id >= 0 && id < m->rows) {
                m->at[m->n] = e;
                m->id[m->n++] = id;
            }
        }
    }
    int count = widget_get_prop_int(w, COUNT, -1);
    if (count != m->rows) {
        prop(w, SEL, -1);
        prop(w, COUNT, m->rows);
    }
    /* A recreated page has never seen this surface (COUNT unset) and lost its selection: put the
     * user back where they left off. A live page whose count changed resets the selection but
     * keeps its viewport, so it does not re-read the table. A non-virtual list prefers the row
     * with the remembered text and falls back to the remembered index. */
    if (m->kind != 3 && count < 0) {
        unsigned hash = 0;
        int id = recall(context_now(), &hash);
        if (id >= 0 && m->kind == 1 && hash) {
            for (int i = 0; i < m->n; ++i)
                if (row_hash(m->at[i]) == hash) {
                    id = m->id[i];
                    break;
                }
        }
        if (id >= 0 && id < m->rows) {
            prop(w, SEL, id);
            reveal(m, id, 0);
            if (m->kind == 1) {
                st.reveal_surface = m->w;
                st.reveal_id = id;
            }
        }
    }
    return 1;
}

/* Live viewport offset. reveal glides are relative, so every delta is computed against the
 * position the widget is actually at, never an intended one. */
static int view_top(menu_t *m) { return m->kind == 2 ? I(m->w, TABLE_TOP) : I(m->w, SCROLL_Y); }

/* Largest viewport top that still shows content; the clamp bound for every glide. */
static int max_top(menu_t *m) {
    return (m->kind == 2 ? m->rows * m->row : I(m->w, VIEW_CONTENT_H)) - m->height;
}

static rect_t bounds(menu_t *m, int i) {
    void *e = m->at[i];
    rect_t r = { 0, 0, I(e, W_W), I(e, W_H) };
    for (void *p = e; p && p != m->w; p = P(p, W_PARENT)) {
        r.x += I(p, W_X);
        r.y += I(p, W_Y);
    }
    if (m->kind != 3) r.y -= view_top(m);
    if (m->kind == 1) r.x -= I(m->w, SCROLL_X);
    return r;
}

static int index_of(menu_t *m, int id) {
    for (int i = 0; i < m->n; ++i)
        if (m->id[i] == id) return i;
    return -1;
}

static int moving(menu_t *m) {
    return m->kind == 1   ? P(m->w, VIEW_ANIMATOR) != 0
           : m->kind == 2 ? P(m->w, TABLE_ANIMATOR) != 0
                          : 0;
}

static void stop_scroll(menu_t *m) {
    if (m->kind == 2)
        table_client_stop_animator_scroll(m->w);
    else if (m->kind == 1 && P(m->w, VIEW_ANIMATOR)) {
        /* Same pause/destroy/null sequence as stock table_client_stop_animator_scroll. */
        void *a = P(m->w, VIEW_ANIMATOR);
        widget_animator_pause(a);
        widget_animator_destroy(a);
        P(m->w, VIEW_ANIMATOR) = (void *)0;
    }
}

/* Least viewport move that makes logical row id fully visible; no animator if already visible.
 * cancel stops a glide away from the live viewport, for a wheel reversal into it. */
static void reveal(menu_t *m, int id, int cancel) {
    int top = view_top(m);
    int y, h;
    if (m->kind == 2) {
        y = id * m->row;
        h = m->row;
    } else {
        int i = index_of(m, id);
        if (i < 0) return;
        rect_t r = bounds(m, i);
        y = r.y + top;
        h = r.h;
    }
    int want = y < top ? y : y + h > top + m->height ? y + h - m->height : top;
    want = clamp_step(want, max_top(m), 0);
    if (want == top) {
        if (cancel && moving(m)) stop_scroll(m);
        return;
    }
    if (m->kind == 2) {
        stop_scroll(m);
        table_client_scroll_to(m->w, want);
    } else
        scroll_view_scroll_delta_to(m->w, 0, want - top, GLIDE_MS);
}

/* Keep selection during native momentum and wheel glides. Once settled, repair an offscreen
 * selection with the visible row nearest the viewport centre (ties go to the earlier row), so a
 * swipe never leaves the highlight pinned to the top edge. An interrupted recall glide is
 * retried once instead: the remembered row must not be silently replaced by a visible one. */
static int reconcile(menu_t *m, int settle) {
    int id = m->kind == 3 ? I(m->w, SLIDE_INDEX) : widget_get_prop_int(m->w, SEL, -1);
    int cur = index_of(m, id);
    if (m->kind == 3) return cur;
    if (cur >= 0) {
        rect_t r = bounds(m, cur);
        if (r.y < m->height && r.y + r.h > 0) {
            st.reveal_surface = (void *)0; /* the glide arrived, or the user brought it back */
            return cur;
        }
        if (!settle) return cur;
    } else if (id >= 0 && id < m->rows && !settle)
        return -1;
    if (m->kind == 1 && st.reveal_surface == m->w && st.reveal_id == id) {
        st.reveal_surface = (void *)0;
        reveal(m, id, 0);
        return cur;
    }
    int best = -1, best_dist = 0, partial = -1, partial_dist = 0, had = id >= 0;
    for (int i = 0; i < m->n; ++i) {
        rect_t r = bounds(m, i);
        if (r.y >= m->height || r.y + r.h <= 0) continue;
        int dist = r.y + r.h / 2 - m->height / 2;
        if (dist < 0) dist = -dist;
        if (r.y >= 0 && r.y + r.h <= m->height) {
            if (best < 0 || (had && dist < best_dist)) {
                best = i;
                best_dist = dist;
            }
            if (!had) break; /* a fresh page starts on the first visible row */
        } else if (partial < 0 || (had && dist < partial_dist)) {
            partial = i;
            partial_dist = dist;
        }
    }
    cur = best >= 0 ? best : partial;
    st.reveal_surface = (void *)0;
    select(m, cur >= 0 ? m->id[cur] : -1);
    return cur;
}

/* Stock paints children first and calls this with the surface's canvas origin restored.
 * The selected row gets one neutral white outline seated on a dark shade line: the shade is the
 * stock dark surface at an alpha high enough to hold the white over bright album art, and being
 * the same color as the dark rows it vanishes on the stock theme. The translucent fill keeps the
 * row readable over artwork without borrowing the red "playing" language or the native focus
 * flag. Small rows and degenerate geometry keep the square fallback. */
int ringnav_paint(void *w, void *canvas) {
    int result = stock_paint(w, canvas);
    if (!w || !canvas || !kind(w) || surface() != w) return result;
    if (!load(&g_menu, w) || g_menu.kind == 3) return result; /* Home shows its selected card. */
    int i = reconcile(&g_menu,
                      !moving(&g_menu) && !window_manager_get_pointer_pressed(window_manager()));
    if (i < 0) return result;
    rect_t r = bounds(&g_menu, i), old, clip;
    if (r.w < 5 || r.h < 5 || !P(canvas, CANVAS_LCD)) return result;
    canvas_get_clip_rect(canvas, &old);
    int x = I(canvas, CANVAS_X), y = I(canvas, CANVAS_Y);
    clip.x = old.x > x ? old.x : x;
    clip.y = old.y > y ? old.y : y;
    int right = old.x + old.w < x + I(w, W_W) ? old.x + old.w : x + I(w, W_W);
    int bottom = old.y + old.h < y + g_menu.height ? old.y + old.h : y + g_menu.height;
    clip.w = right - clip.x;
    clip.h = bottom - clip.y;
    if (clip.w <= 0 || clip.h <= 0) return result;
    void *lcd = P(canvas, CANVAS_LCD);
    unsigned fill_color = (unsigned)I(lcd, LCD_FILL_COLOR);
    unsigned stroke_color = (unsigned)I(lcd, LCD_STROKE_COLOR);
    canvas_set_clip_rect(canvas, &clip);
    rect_t outer = { r.x + 1, r.y + 1, r.w - 2, r.h - 2 };
    rect_t inner = { outer.x + 1, outer.y + 1, outer.w - 2, outer.h - 2 };
    int drawn = 0;
    /* Two concentric one-pixel rounded strokes, shade outside and white inside, not one
     * border_width=2 call: the effect then does not depend on how a canvas backend interprets
     * the width argument. Geometry is checked before the call, and radius 9/8 both stay above
     * the stock "square at <= 2" cutoff. The stock rounded stroke returns non-zero when its
     * backend cannot draw (for example a canvas without a vgcanvas), and the safe square
     * fallback then keeps the outline visible. */
    if (outer.w > 2 * RADIUS && outer.h > 2 * RADIUS) {
        unsigned fill = FILL_COLOR;
        canvas_fill_rounded_rect(canvas, &outer, (void *)0, &fill, RADIUS);
        unsigned shade = SHADE_COLOR;
        unsigned white = OUTLINE_COLOR;
        drawn = canvas_stroke_rounded_rect(canvas, &outer, (void *)0, &shade, RADIUS, 1) == 0;
        if (drawn) canvas_stroke_rounded_rect(canvas, &inner, (void *)0, &white, RADIUS - 1, 1);
    }
    if (!drawn) {
        canvas_set_stroke_color(canvas, SHADE_COLOR);
        canvas_stroke_rect(canvas, outer.x, outer.y, outer.w, outer.h);
        canvas_set_stroke_color(canvas, OUTLINE_COLOR);
        canvas_stroke_rect(canvas, inner.x, inner.y, inner.w, inner.h);
    }
    /* Save/restore explicitly: this firmware's canvas_save/restore cover neither clip nor
     * either color, and the global alpha is deliberately never touched. */
    canvas_set_fill_color(canvas, fill_color);
    canvas_set_stroke_color(canvas, stroke_color);
    canvas_set_clip_rect(canvas, &old);
    return result;
}

int ringnav_touch(void *ctx, void *event) {
    int result = stock_touch(ctx, event);
    /* A tap is a fresh interaction: it cancels a pending screen-toggle pair and any spin. */
    st.last_center = 0;
    st.center_top = st.center_surface = (void *)0;
    st.last_wheel = 0;
    void *w = surface();
    if (!result && w && load(&g_menu, w)) {
        stop_scroll(&g_menu);
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
        target = P(target, W_PARENT);
    }
    return -1;
}

/* Observe actual clicks BEFORE app callbacks can navigate or destroy/rebind their widgets.
 * Do not turn pointer-down into selection: a swipe is not a tap. */
int ringnav_dispatch(void *target, void *event) {
    if (target && event && I(event, EVENT_TYPE) == EVT_CLICK) {
        void *w = surface();
        if (w && load(&g_menu, w)) {
            int i = selects(&g_menu, target);
            if (i >= 0) {
                select(&g_menu, g_menu.id[i]);
                widget_invalidate_force(w, (void *)0);
            }
        }
    }
    return stock_dispatch(target, event);
}

int ringnav(void *ctx, void *event) {
    int result = stock_keyup(ctx, event);
    if (result || !event) return result;
    unsigned key = (unsigned)I(event, EVENT_KEY);
    if (key != KEY_CENTER && key != KEY_PREV && key != KEY_NEXT) return result;
    if (!usable()) return result;
    /* Match the stock power-key release exclusions, including release after long press. */
    if (key == KEY_CENTER &&
        (g_power_longkey || g_ingore_bootkey_flag || *(volatile unsigned char *)BOOT_KEY_GUARD))
        return result;
    void *wm = window_manager(), *top = window_manager_get_top_window(wm);
    if (!allowed_top(top)) return result;
    if (window_manager_is_animating(wm) || window_manager_get_pointer_pressed(wm)) return STOP;
    void *w = surface_under(top);
    int dir = key == KEY_NEXT ? 1 : key == KEY_PREV ? -1 : 0;
    if (!w) return dir ? STOP : result;
    if (!load(&g_menu, w)) return dir ? STOP : result;
    int touch = widget_get_prop_int(w, TOUCH, 0);
    if (touch) stop_scroll(&g_menu);
    int cur = reconcile(&g_menu, touch || !moving(&g_menu));
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
        select(&g_menu, g_menu.id[cur]);
        widget_invalidate_force(w, (void *)0);
        char click[0x30];
        /* Synchronous native click: no queued recycled row can change the activated item. */
        stock_dispatch(g_menu.at[cur], pointer_event_init(click, EVT_CLICK, g_menu.at[cur], 0, 0));
        return STOP; /* No widget access after the app callback. */
    }
    st.last_center = 0; /* A wheel detent ends the double-click window. */
    st.center_top = st.center_surface = (void *)0;
    prop(w, TOUCH, 0);
    int step = wheel_step(dir, now);
    if (g_menu.kind == 3) {
        if (dir > 0)
            slide_menu_scroll_to_next(w);
        else
            slide_menu_scroll_to_prev(w);
    } else if (g_menu.n) {
        int id = widget_get_prop_int(w, SEL, -1);
        int next = clamp_step(id < 0 ? (cur >= 0 ? g_menu.id[cur] : 0) : id + dir * step,
                              g_menu.rows - 1, 0);
        if (next == id) return STOP;
        select(&g_menu, next);
        /* Reversing into the current viewport must cancel the previous glide away from it. */
        reveal(&g_menu, next, 1);
    } else {
        int top = view_top(&g_menu);
        int next = clamp_step(top, max_top(&g_menu), dir * RING_STEP * step);
        if (g_menu.kind == 2) {
            stop_scroll(&g_menu);
            table_client_scroll_to(w, next);
        } else if (next != top)
            scroll_view_scroll_delta_to(w, 0, next - top, GLIDE_MS);
    }
    widget_invalidate_force(w, (void *)0);
    return STOP;
}
