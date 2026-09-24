/* Logical menu selection is independent of native touch focus. Stock code owns gestures. */
#include "offsets.inc"
#include "stock.h"
#define STOP 11
#define GLIDE_MS 300
#define SCROLL_MARGIN 12
#define DOUBLE_CLICK_MS 300
#define HOME_WHEEL_MS 200
#define ACCEL_MS 140
#define ACCEL_DIV 3
#define ACCEL_MAX 8
#define SHORT_LIST_MAX 16
#define MAX_ENTRIES 512
#define POS_MEM 64
/* RADIUS, FILL_RGB, FILL_ALPHA and SHADE_ALPHA come from offsets.inc; the colors pack their bytes
 * at compile time (little-endian r,g,b,a). The outline is opaque neutral white, never the playing
 * red, seated on a dark shade of the stock surface so bright album art cannot wash it out. */
#define FILL_COLOR ((FILL_ALPHA << 24) | FILL_RGB)
#define SHADE_COLOR ((SHADE_ALPHA << 24) | FILL_RGB)
#define OUTLINE_COLOR 0xffffffffu
#define I(p, o) (*(int *)((char *)(p) + (o)))
#define P(p, o) (*(void **)((char *)(p) + (o)))
#define B(p, o) (*(unsigned char *)((char *)(p) + (o)))

typedef struct {
    int ctx, id; /* logical row + 1; 0 = unused */
    unsigned scope, hash, hash2;
} position_t;

/* Writable state lives in the zero-filled page the builder maps past the payload text.
 * center_timer defers confirmation; wheel_* scale repeated fast detents; pos_* remember
 * the selected row per audited context across page recreation; reveal_* pin the recall glide so
 * an interruption cannot silently rewrite that memory. */
typedef struct {
    unsigned last_center; /* release time of the pending selection press */
    unsigned center_timer, center_token, center_scope, center_hash, center_hash2;
    int center_id, center_ctx, center_rows;
    unsigned last_home;
    int home_dir;
    void *home_surface;   /* non-null also marks a step accepted at time zero */
    void *center_top;     /* top window of that press */
    void *center_surface; /* navigation surface of that press */
    unsigned last_wheel;  /* time of the previous wheel detent */
    int wheel_dir;        /* direction of that detent */
    unsigned wheel_run;   /* consecutive fast detents in that direction */
    void *wheel_top, *wheel_surface;
    unsigned wheel_scope;
    position_t pos[POS_MEM]; /* most recently selected first; keyed by context and scope */
    void *reveal_surface;    /* surface of the interrupted recall glide, 0 when none */
    int reveal_id;           /* logical row that glide was bringing into view */
} scratch_t;
static scratch_t st __attribute__((section(".scratch")));

typedef struct {
    int x, y, w, h;
} rect_t;
typedef struct {
    void *w, *at[MAX_ENTRIES];
    int id[MAX_ENTRIES], n, kind, rows, row, height, ctx;
    unsigned scope;
} menu_t;
/* Single shared view: no entry point keeps a menu live across a nested load(). */
static menu_t g_menu __attribute__((section(".scratch")));

/* Audited top windows, each tagged with its content-identity class. The index is remembered
 * instead of the name pointer: AWTK owns and frees the window's name string. */
enum { CTX_DYNAMIC, CTX_FIXED, CTX_FOLDER, CTX_LOCAL };
typedef struct {
    const char *name;
    unsigned char kind;
} context_t;
static const context_t contexts[] = {
#include "contexts.inc"
};

static int context_id(const char *name) {
    if (!name) return -1;
    for (unsigned i = 0; i < sizeof(contexts) / sizeof(*contexts); ++i)
        if (!tk_strcmp(name, contexts[i].name)) return (int)i;
    return -1;
}

/* The view kinds load() actually navigates: a vertical scroll view, a table client or a slide
 * menu. A horizontal or page-snapping scroll view is not a candidate, so it cannot make a page
 * look like it has two panes. */
static int kind(void *w) {
    const char *t = widget_get_type(w);
    if (!tk_strcmp(t, "slide_menu")) return 3;
    if (!tk_strcmp(t, "table_client")) return 2;
    return !tk_strcmp(t, "scroll_view") && B(w, VIEW_VERTICAL) && !B(w, VIEW_HORIZONTAL) &&
                   !B(w, VIEW_SNAP)
               ? 1
               : 0;
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
    offset = offset < 0 ? 0 : offset > maximum ? maximum : offset;
    if (delta > maximum - offset) return maximum;
    if (delta < -offset) return 0;
    return offset + delta;
}

/* Consecutive detents closer than ACCEL_MS in one direction step further, like spinning
 * an iPod wheel: x2 every ACCEL_DIV detents, capped at ACCEL_MAX. A pause or reversal
 * starts over. Stock rate-limits wheel keys to roughly one per 80-200 ms, so real ticks
 * land inside the acceleration window. */
static int wheel_step(menu_t *m, void *top, int dir, unsigned now) {
    if (m->rows <= SHORT_LIST_MAX) {
        st.wheel_run = 0;
        return 1;
    }
    if (st.wheel_run && now - st.last_wheel <= ACCEL_MS && st.wheel_dir == dir &&
        st.wheel_top == top && st.wheel_surface == m->w && st.wheel_scope == m->scope)
        st.wheel_run += st.wheel_run < 3 * ACCEL_DIV;
    else
        st.wheel_run = 1;
    st.last_wheel = now;
    st.wheel_dir = dir;
    st.wheel_top = top;
    st.wheel_surface = m->w;
    st.wheel_scope = m->scope;
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
    /* A pages widget exposes only its active child; inactive tabs must not look tappable. */
    if (!tk_strcmp(widget_get_type(w), "pages")) {
        int active = widget_get_prop_int(w, "active", -1);
        if (active >= 0) collect(widget_get_child(w, active), s, depth + 1);
        return;
    }
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) collect(widget_get_child(w, i), s, depth + 1);
}

/* Widget-owned properties die with the surface; never retain recycled row pointers. */
#define SEL "_ringnav_index"
#define TOUCH "_ringnav_touch"
#define COUNT "_ringnav_count"
#define SCOPE "_ringnav_scope"

static void cancel_center(void) {
    unsigned timer = st.center_timer;
    st.center_timer = 0;
    st.center_top = st.center_surface = (void *)0;
    if (timer) timer_remove(timer);
}

static int is_home(void *top, void *w) {
    return top && w && kind(w) == 3 &&
           !tk_strcmp(widget_get_prop_str(top, "name", ""), "home_page");
}

static int usable(void) {
    return g_backlight_status && !g_lockscreen_pageflag && !g_testmode_flag && !g_guideflag &&
           !g_poweroff_state && g_usblink_status != 2 && !bt__recv_pageflag;
}

static int allowed_top(void *top) {
    return top && context_id(widget_get_prop_str(top, "name", (void *)0)) >= 0;
}

/* A click identifies its pane by ancestry. On the first wheel turn, an unowned pair starts
 * with the first pane in UI order; painting and touch never choose one implicitly. */
static void *surface_under(void *top, void *target, void **other, int wheel) {
    void *found[2] = { (void *)0, (void *)0 };
    int count = 0, aborted = 0, budget = 512;
    find_surface(top, found, &count, &aborted, 0, &budget);
    if (aborted || count == 0) return (void *)0;
    if (count == 1) return found[0];
    if (target) {
        for (int depth = 0; target && depth < 32; ++depth) {
            for (int i = 0; i < count; ++i)
                if (target == found[i]) {
                    if (other) *other = found[1 - i];
                    return found[i];
                }
            if (target == top) break;
            target = P(target, W_PARENT);
        }
        return (void *)0;
    }
    int first = widget_get_prop_int(found[0], SEL, -1) >= 0;
    int second = widget_get_prop_int(found[1], SEL, -1) >= 0;
    if (wheel && !first && !second) return found[0];
    return first == second ? (void *)0 : (first ? found[0] : found[1]);
}

static void *surface(void *target, void **other) {
    void *wm = window_manager(), *top = window_manager_get_top_window(wm);
    void *w = usable() && !window_manager_is_animating(wm) && allowed_top(top)
                  ? surface_under(top, target, other, 0)
                  : (void *)0;
    if (st.center_timer && (top != st.center_top || w != st.center_surface)) cancel_center();
    if (!is_home(top, w) || w != st.home_surface) st.home_surface = (void *)0;
    return w;
}

static void prop(void *w, const char *name, int value) {
    if (widget_get_prop_int(w, name, -1) != value) widget_set_prop_int(w, name, value);
}

/* FNV-1a of the first two non-empty text properties in a small row subtree: the item's own name
 * and an optional subtitle, in pre-order. Each stays 0 while its text has not been seen. No stock
 * list row carries a stable id: emitter tags and pointer props are unused by the app rows (only
 * ROW_INDEX, which a re-sort rewrites), so these hashes are the identity available to restore. */
typedef struct {
    unsigned one, two;
} row_id_t;

static unsigned hash_bytes(unsigned h, const unsigned char *s, unsigned n) {
    for (unsigned i = 0; i < n; ++i) h = (h ^ s[i]) * 16777619u;
    return h;
}

static void row_hash_text(const unsigned *s, unsigned *h) {
    unsigned n = 0;
    while (s[n]) ++n;
    /* Stock wchar_t is UTF-32; hash all four bytes, zero bytes inside a character included. */
    *h = hash_bytes(2166136261u, (const unsigned char *)s, 4 * n);
    if (!*h) *h = 1; /* zero denotes missing text */
}

static void row_id_walk(void *w, int depth, int *budget, row_id_t *id) {
    if (!w || depth == 4 || id->two || --*budget < 0) return;
    const unsigned *s = widget_get_text(w);
    if (s && *s) {
        if (!id->one)
            row_hash_text(s, &id->one);
        else {
            row_hash_text(s, &id->two);
            return;
        }
    }
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) row_id_walk(widget_get_child(w, i), depth + 1, budget, id);
}

static row_id_t row_id(void *w) {
    row_id_t id = { 0, 0 };
    int budget = 32;
    row_id_walk(w, 0, &budget, &id);
    return id;
}

/* The local list loaders use these browsing globals: folder_enter/back maintain g_folder_path;
 * load_localclass_list/load_album_detaillist use the class, saved query and artist/album modes.
 * Hash the bounded query object, including its flags, rather than a title or a freed pointer. */
static int context_now(unsigned *scope) {
    void *top = window_manager_get_top_window(window_manager());
    const char *name = top ? widget_get_prop_str(top, "name", (void *)0) : (void *)0;
    *scope = 0;
    if (!name) return -1;
    int ctx = context_id(name);
    if (ctx < 0) return -1;
    void *found[2];
    int count = 0, aborted = 0, budget = 512;
    find_surface(top, found, &count, &aborted, 0, &budget);
    if (contexts[ctx].kind == CTX_FOLDER) {
        unsigned n = 0;
        while (n < 1024 && g_folder_path[n]) ++n;
        if (!n || n == 1024) return -1;
        *scope = hash_bytes(2166136261u, g_folder_path, n);
    } else if (contexts[ctx].kind == CTX_LOCAL) {
        unsigned h = hash_bytes(2166136261u, g_class_type, 4);
        h = hash_bytes(h, g_local_classinfo_save, 912);
        h = hash_bytes(h, g_artist_type, 4);
        *scope = hash_bytes(h, album_modetype, 4);
    } else if (contexts[ctx].kind == CTX_FIXED) {
        *scope = 1;
    } else {
        /* Network/detail pages without an audited content key keep widget-owned selection, but
         * never import another page's row. */
        return -1;
    }
    if (!*scope) *scope = 1;
    return !aborted && count == 1 ? ctx : -1; /* no cross-pane position memory */
}

static int index_of(menu_t *m, int id);
static void reveal(menu_t *m, int id, int cancel);

/* Bounded recency order avoids a timestamp that could wrap during a long session. */
static int position(menu_t *m) {
    if (m->ctx >= 0)
        for (int i = 0; i < POS_MEM; ++i)
            if (st.pos[i].id && st.pos[i].ctx == m->ctx && st.pos[i].scope == m->scope) return i;
    return -1;
}

/* Remember where the user was. Widget props die with a recreated page; this survives it.
 * Non-virtual lists also remember the row's first two text values, so a reordered list restores
 * the same item and duplicate names can be told apart by their second line. */
static void select(menu_t *m, int id) {
    if (st.center_timer && (m->w != st.center_surface || id != st.center_id)) cancel_center();
    if (st.reveal_surface == m->w) st.reveal_surface = (void *)0;
    unsigned hash = 0, hash2 = 0;
    if (id >= 0) {
        int ctx = m->ctx;
        if (m->kind == 1) {
            int i = index_of(m, id);
            if (i >= 0) {
                row_id_t r = row_id(m->at[i]);
                hash = r.one;
                hash2 = r.two;
            }
        }
        if (ctx >= 0) {
            int p = position(m);
            if (p < 0) p = POS_MEM - 1;
            for (; p > 0; --p) {
                st.pos[p].ctx = st.pos[p - 1].ctx;
                st.pos[p].id = st.pos[p - 1].id;
                st.pos[p].scope = st.pos[p - 1].scope;
                st.pos[p].hash = st.pos[p - 1].hash;
                st.pos[p].hash2 = st.pos[p - 1].hash2;
            }
            st.pos[0] = (position_t){ ctx, id + 1, m->scope, hash, hash2 };
        }
    }
    prop(m->w, SEL, id);
}

static int load_rows(menu_t *m, void *w) {
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
            void *r = widget_get_child(w, i), *e = (void *)0;
            entries_t s = { &e, 0, 1, 256 };
            collect(r, &s, 0);
            int id = m->kind == 2 ? I(r, ROW_INDEX) : (int)i;
            if (e && id >= 0 && id < m->rows) {
                m->at[m->n] = e;
                m->id[m->n++] = id;
            }
        }
    }
    return 1;
}

static int load(menu_t *m, void *w, int recall) {
    if (!load_rows(m, w)) return 0;
    m->ctx = context_now(&m->scope);
    int count = widget_get_prop_int(w, COUNT, -1);
    unsigned scope = (unsigned)widget_get_prop_int(w, SCOPE, 0);
    if (scope != m->scope) {
        count = -1;
        prop(w, SCOPE, (int)m->scope);
        if (st.reveal_surface == w) st.reveal_surface = (void *)0;
    }
    if (count != m->rows) {
        if (st.wheel_surface == w) st.wheel_run = 0;
        prop(w, SEL, -1);
        prop(w, COUNT, m->rows);
    }
    /* A recreated page has never seen this surface (COUNT unset) and lost its selection: put the
     * user back where they left off. A live page whose count changed resets the selection but
     * keeps its viewport, so it does not re-read the table. A non-virtual list prefers the
     * remembered first text, breaks ties by the second text and then by the remembered index,
     * and falls back to the index when no text matches. */
    if (recall && m->kind != 3 && count < 0) {
        int p = position(m);
        int id = p < 0 ? -1 : st.pos[p].id - 1;
        unsigned hash = p < 0 ? 0 : st.pos[p].hash;
        unsigned hash2 = p < 0 ? 0 : st.pos[p].hash2;
        if (id >= 0 && m->kind == 1 && hash) {
            /* A secondary-text match outranks proximity; equal ranks keep the earlier row. */
            int best = -1, best_dist = 0, best_second = 0;
            for (int i = 0; i < m->n; ++i) {
                row_id_t r = row_id(m->at[i]);
                if (r.one != hash) continue;
                int dist = m->id[i] - id;
                if (dist < 0) dist = -dist;
                int second = hash2 && r.two == hash2;
                if (best < 0 || second > best_second ||
                    (second == best_second && dist < best_dist)) {
                    best = i;
                    best_dist = dist;
                    best_second = second;
                }
            }
            if (best >= 0) id = m->id[best];
        }
        if (id >= 0 && id < m->rows) {
            prop(w, SEL, id);
            reveal(m, id, 0);
            st.reveal_surface = m->w;
            st.reveal_id = id;
            /* A synchronous table rebind changes the row pool; discard the pre-scroll snapshot. */
            if (m->kind == 2) return load_rows(m, w);
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

/* Least viewport move that reveals logical row id with a small reading margin.
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
    /* A tall row cannot fit: show its title consistently instead of alternating edges. */
    int margin = clamp_step((m->height - h) / 2, SCROLL_MARGIN, 0);
    int want = h > m->height || y - top < margin  ? y - margin
               : y - top > m->height - h - margin ? y - (m->height - h - margin)
                                                  : top;
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
    if (st.reveal_surface == m->w && st.reveal_id == id) {
        st.reveal_surface = (void *)0;
        reveal(m, id, 0);
        if (m->kind == 2) return load_rows(m, m->w) ? index_of(m, id) : -1;
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

/* Resolve only live rows. Widget-owned tokens reject a recreated window/surface even when
 * the allocator reuses its address; text hashes reject a rebound item at the same index. */
#define CONFIRM "_ringnav_confirm"
static int pending_matches(void *top, menu_t *m) {
    int id = m->kind == 3 ? I(m->w, SLIDE_INDEX) : widget_get_prop_int(m->w, SEL, -1);
    int i = index_of(m, id);
    if (top != st.center_top || m->w != st.center_surface || m->scope != st.center_scope ||
        m->ctx != st.center_ctx || m->rows != st.center_rows || id != st.center_id || i < 0 ||
        (unsigned)widget_get_prop_int(top, CONFIRM, 0) != st.center_token ||
        (unsigned)widget_get_prop_int(m->w, CONFIRM, 0) != st.center_token)
        return 0;
    /* Ordinary rows must still be the armed widget, even with duplicate/missing text.
     * Virtual tables instead resolve the logical row across recycled pool widgets. */
    if (m->kind != 2 && (unsigned)widget_get_prop_int(m->at[i], CONFIRM, 0) != st.center_token)
        return 0;
    row_id_t r = row_id(m->at[i]);
    return r.one == st.center_hash && r.two == st.center_hash2;
}

static int confirm_center(const void *info) {
    (void)info;
    void *w = surface((void *)0, (void *)0);
    if (!st.center_timer) return 0;
    /* Stock removes this one-shot after return; never repeat (RET_REPEAT=8). */
    st.center_timer = 0;
    void *top = window_manager_get_top_window(window_manager());
    int valid = w && !window_manager_get_pointer_pressed(window_manager()) && !g_power_longkey &&
                !g_ingore_bootkey_flag && !*(volatile unsigned char *)BOOT_KEY_GUARD &&
                load(&g_menu, w, 1) && pending_matches(top, &g_menu);
    cancel_center(); /* Clear before any app callback can destroy or navigate the page. */
    if (valid) {
        void *target = g_menu.at[index_of(&g_menu, st.center_id)];
        char click[0x30];
        stock_dispatch(target, pointer_event_init(click, EVT_CLICK, target, 0, 0));
    }
    return 0;
}

/* Stock paints children first and calls this with the surface's canvas origin restored.
 * The selected row gets one neutral white outline seated on a dark shade line: the shade is the
 * stock dark surface at an alpha high enough to hold the white over bright album art, and being
 * the same color as the dark rows it vanishes on the stock theme. The translucent fill keeps the
 * row readable over artwork without borrowing the red "playing" language or the native focus
 * flag. Small rows and degenerate geometry keep the square fallback. */
int ringnav_paint(void *w, void *canvas) {
    int result = stock_paint(w, canvas);
    /* Even a page with no navigable pane must end pending input when it is painted. */
    if (st.center_timer || st.home_surface) {
        void *wm = window_manager(), *top = window_manager_get_top_window(wm);
        if (!usable() || window_manager_is_animating(wm) || top != st.center_top) cancel_center();
        if (!top || tk_strcmp(widget_get_prop_str(top, "name", ""), "home_page"))
            st.home_surface = (void *)0;
    }
    if (!w || !canvas || !kind(w) || surface((void *)0, (void *)0) != w) return result;
    if (!load(&g_menu, w, !window_manager_get_pointer_pressed(window_manager()))) {
        cancel_center();
        return result;
    }
    if (st.center_timer &&
        !pending_matches(window_manager_get_top_window(window_manager()), &g_menu))
        cancel_center();
    if (g_menu.kind == 3) return result; /* Home shows its selected card. */
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
        if (drawn)
            drawn =
                canvas_stroke_rounded_rect(canvas, &inner, (void *)0, &white, RADIUS - 1, 1) == 0;
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
    cancel_center();
    st.home_surface = (void *)0;
    st.wheel_run = 0;
    void *w = surface((void *)0, (void *)0);
    /* Pointer-down must not recall/rebind the row that native touch is about to hit. */
    if (!result && w && load_rows(&g_menu, w)) {
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
        void *other = (void *)0;
        void *w = surface(target, &other);
        /* A tap owns its live row: recall could scroll/rebind that row before delivery. */
        if (w && load(&g_menu, w, 0)) {
            int i = selects(&g_menu, target);
            if (i >= 0) {
                stop_scroll(&g_menu); /* an explicit tap replaces any pending recall glide */
                if (other) {
                    prop(other, SEL, -1);
                    widget_invalidate_force(other, (void *)0);
                }
                select(&g_menu, g_menu.id[i]);
                widget_invalidate_force(w, (void *)0);
            }
        }
    }
    return stock_dispatch(target, event);
}

int ringnav(void *ctx, void *event) {
    /* The stock filter dereferences the event before returning. */
    if (!event) {
        cancel_center();
        st.wheel_run = 0;
        st.home_surface = (void *)0;
        return 0;
    }
    int result = stock_keyup(ctx, event);
    if (result) {
        cancel_center();
        /* Stock debounce must not break a spin or restart the home interval. */
        if (I(event, EVENT_KEY) == KEY_CENTER || !usable()) {
            st.wheel_run = 0;
            st.home_surface = (void *)0;
        }
        return result;
    }
    unsigned key = (unsigned)I(event, EVENT_KEY);
    if (key != KEY_CENTER && key != KEY_PREV && key != KEY_NEXT) return result;
    if (key == KEY_CENTER) {
        st.wheel_run = 0;
        st.home_surface = (void *)0;
    } else
        cancel_center();
    if (st.center_timer && (unsigned)time_now_ms() - st.last_center >= DOUBLE_CLICK_MS) {
        unsigned timer = st.center_timer;
        confirm_center((void *)0);
        timer_remove(timer);
    }
    /* An overdue click may change power/lock state; inspect it after its callback. */
    if (!usable()) {
        cancel_center();
        st.wheel_run = 0;
        st.home_surface = (void *)0;
        return result;
    }
    /* Match the stock power-key release exclusions, including release after long press. */
    if (key == KEY_CENTER &&
        (g_power_longkey || g_ingore_bootkey_flag || *(volatile unsigned char *)BOOT_KEY_GUARD)) {
        cancel_center();
        return result;
    }
    void *wm = window_manager(), *top = window_manager_get_top_window(wm);
    if (!allowed_top(top)) {
        cancel_center();
        st.wheel_run = 0;
        st.home_surface = (void *)0;
        return result;
    }
    if (tk_strcmp(widget_get_prop_str(top, "name", ""), "home_page")) st.home_surface = (void *)0;
    if (window_manager_is_animating(wm) || window_manager_get_pointer_pressed(wm)) {
        cancel_center();
        st.wheel_run = 0;
        return STOP;
    }
    int dir = key == KEY_NEXT ? 1 : key == KEY_PREV ? -1 : 0;
    void *w = surface_under(top, (void *)0, (void *)0, dir != 0);
    if (!is_home(top, w) || w != st.home_surface) st.home_surface = (void *)0;
    if (!w || !load(&g_menu, w, 1)) {
        cancel_center();
        st.wheel_run = 0;
        return dir ? STOP : result;
    }
    if (st.center_timer && !pending_matches(top, &g_menu)) cancel_center();
    int touch = widget_get_prop_int(w, TOUCH, 0);
    if (touch) stop_scroll(&g_menu);
    int cur = reconcile(&g_menu, touch || !moving(&g_menu));
    unsigned now = (unsigned)time_now_ms();
    if (!dir) {
        if (st.center_timer && now - st.last_center < DOUBLE_CLICK_MS) {
            cancel_center();
            return result; /* Let the stock downstream short-press handler turn the screen off. */
        }
        cancel_center();
        if (cur < 0) return STOP;
        select(&g_menu, g_menu.id[cur]);
        widget_invalidate_force(w, (void *)0);
        st.last_center = now;
        st.center_top = top;
        st.center_surface = w;
        st.center_scope = g_menu.scope;
        st.center_ctx = g_menu.ctx;
        st.center_rows = g_menu.rows;
        st.center_id = g_menu.id[cur];
        row_id_t r = row_id(g_menu.at[cur]);
        st.center_hash = r.one;
        st.center_hash2 = r.two;
        st.center_timer = timer_add(confirm_center, (void *)0, DOUBLE_CLICK_MS);
        st.center_token = st.center_timer;
        if (st.center_timer) {
            prop(top, CONFIRM, (int)st.center_token);
            prop(w, CONFIRM, (int)st.center_token);
            if (g_menu.kind != 2) prop(g_menu.at[cur], CONFIRM, (int)st.center_token);
        } else
            cancel_center(); /* Allocation failure consumes the press without a click. */
        return STOP;
    }
    prop(w, TOUCH, 0);
    if (is_home(top, w)) {
        if (st.home_surface == w && st.home_dir == dir && now - st.last_home < HOME_WHEEL_MS)
            return STOP;
        st.home_surface = w;
        st.last_home = now;
        st.home_dir = dir;
    }
    int step = wheel_step(&g_menu, top, dir, now);
    if (g_menu.kind == 3) {
        if (dir > 0)
            slide_menu_scroll_to_next(w);
        else
            slide_menu_scroll_to_prev(w);
    } else if (g_menu.n) {
        int id = widget_get_prop_int(w, SEL, -1);
        int next = clamp_step(id < 0 ? (cur >= 0 ? g_menu.id[cur] : 0) : id, g_menu.rows - 1,
                              id < 0 ? 0 : dir * step);
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
