// widgets/w_shanimatedimage.c -- kit widget ShAnimatedImage (Basic, "Animated image").
//
// Spec: ui/qml/Shadcn/ShAnimatedImage.qml. A moving picture: an animated GIF
// from the bundle (`source`, e.g. "assets/truck.gif", resolved like Image's),
// decoded and played by LVGL's lv_gif. Properties (kit_schema.json): source,
// playing, speed, fillMode, opacity, visible. Default size 240x160. No signals.
//
//   playing   false pauses on the current frame, true resumes (a GIF whose
//             loop count ran out starts over).
//   speed     playback speed in percent. lv_gif has no speed setting, so the
//             frames are advanced here: lv_gif decodes the file and owns the
//             canvas, its own frame timer is kept paused, and ours steps the
//             decoder with every frame delay scaled by 100/speed. The timer
//             runs every 10 ms, so at most 100 frames a second are shown,
//             however high the speed.
//   fillMode  Image.PreserveAspectFit / PreserveAspectCrop / Stretch map to
//             lv_image's inner align CONTAIN / COVER / STRETCH. The picture
//             sits in a clipping box so a cropped frame never spills out.
//
// No source, a missing file or one that is not a GIF draws the placeholder
// the QML and the Designer canvas draw: a muted card, a framed play glyph and
// "GIF" -- never a crash.
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "src/libs/gif/lv_gif_private.h"

#define FRAME_TICK_MS 10

typedef struct {
    lv_obj_t *root;
    lv_obj_t *clip;         // clips a cropped picture to the widget's box
    lv_obj_t *gif;          // lv_gif (an lv_image)
    lv_obj_t *placeholder;  // shown when nothing could be loaded
    lv_obj_t *label;
    lv_timer_t *timer;      // steps the frames at `speed`
    uint32_t last;          // tick of the last frame shown
    int speed;              // percent, >= 1
    bool playing;
    bool loaded;
    bool finished;          // the GIF's own loop count ran out
} anim_state_t;

// -- placeholder geometry, shared with the QML ---------------------------------
typedef struct { int glyph, glyph_w, text_px, gap, top; } ph_geom_t;

static int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

static ph_geom_t ph_geom(int w, int h)
{
    ph_geom_t g;
    int s = w < h ? w : h;
    if (s < 1) s = 1;
    g.glyph = clampi(hmi_px(s * 0.30), 12, 64);
    g.glyph_w = hmi_px(g.glyph * 1.35);
    g.text_px = clampi(hmi_px(s * 0.11), 10, 18);
    g.gap = hmi_px(g.glyph * 0.18);
    g.top = hmi_px((h - (g.glyph + g.gap + g.text_px)) / 2.0);
    return g;
}

static void placeholder_draw_cb(lv_event_t *e)
{
    hmi_draw_t d = hmi_draw_begin(e);
    int w = lv_area_get_width(&d.coords), h = lv_area_get_height(&d.coords);
    ph_geom_t g = ph_geom(w, h);
    lv_color_t ink = hmi_colour("mutedForeground");

    // The frame: a 2 px outline, radius 3.
    double fx = hmi_px((w - g.glyph_w) / 2.0), fy = g.top;
    lv_draw_rect_dsc_t rect;
    lv_draw_rect_dsc_init(&rect);
    rect.bg_opa = LV_OPA_TRANSP;
    rect.border_color = ink;
    rect.border_width = 2;
    rect.border_opa = LV_OPA_COVER;
    rect.radius = 3;
    lv_area_t a = {(int32_t)(d.coords.x1 + fx), (int32_t)(d.coords.y1 + fy),
                   (int32_t)(d.coords.x1 + fx + g.glyph_w) - 1, (int32_t)(d.coords.y1 + fy + g.glyph) - 1};
    lv_draw_rect(d.layer, &rect, &a);

    // The play triangle, centred in the frame.
    double th = g.glyph * 0.45, tw = th * 0.85;
    double cx = d.coords.x1 + fx + g.glyph_w / 2.0, cy = d.coords.y1 + fy + g.glyph / 2.0;
    lv_draw_triangle_dsc_t tri;
    lv_draw_triangle_dsc_init(&tri);
    tri.p[0].x = (lv_value_precise_t)(cx - tw / 3); tri.p[0].y = (lv_value_precise_t)(cy - th / 2);
    tri.p[1].x = (lv_value_precise_t)(cx - tw / 3); tri.p[1].y = (lv_value_precise_t)(cy + th / 2);
    tri.p[2].x = (lv_value_precise_t)(cx + 2 * tw / 3); tri.p[2].y = (lv_value_precise_t)cy;
    tri.color = ink;
    tri.opa = LV_OPA_COVER;
    lv_draw_triangle(d.layer, &tri);
}

// -- playback ------------------------------------------------------------------
static void frame_tick_cb(lv_timer_t *t)
{
    anim_state_t *st = lv_timer_get_user_data(t);
    if (!st || !st->loaded) return;
    lv_gif_t *g = (lv_gif_t *)st->gif;
    if (!g->gif) return;
    // The GIF states each frame's delay in 1/100 s (as lv_gif reads it).
    uint32_t delay = (uint32_t)g->gif->gce.delay * 10u * 100u / (uint32_t)st->speed;
    if (lv_tick_elaps(st->last) < delay) return;
    st->last = lv_tick_get();
    if (gd_get_frame(g->gif) == 0) {          // the last repeat: hold it
        st->finished = true;
        lv_timer_pause(t);
    }
    gd_render_frame(g->gif, (uint8_t *)g->imgdsc.data);
    lv_image_cache_drop(lv_image_get_src(st->gif));
    lv_obj_invalidate(st->gif);
}

static void apply_playing(anim_state_t *st)
{
    if (!st->timer) return;
    if (!st->loaded || !st->playing) {
        lv_timer_pause(st->timer);
        return;
    }
    if (st->finished) {                       // ran out: start over
        gd_rewind(((lv_gif_t *)st->gif)->gif);
        st->finished = false;
    }
    st->last = lv_tick_get();
    lv_timer_resume(st->timer);
}

static void apply_fill(anim_state_t *st, const char *fill)
{
    lv_image_align_t align = LV_IMAGE_ALIGN_CONTAIN;          // PreserveAspectFit
    if (fill && strcmp(fill, "Image.PreserveAspectCrop") == 0) align = LV_IMAGE_ALIGN_COVER;
    else if (fill && strcmp(fill, "Image.Stretch") == 0) align = LV_IMAGE_ALIGN_STRETCH;
    lv_image_set_inner_align(st->gif, align);
}

static void load(hmi_widget_t *w, anim_state_t *st, const char *src)
{
    st->loaded = false;
    st->finished = false;
    if (src && *src) {
        char pathbuf[512];
        const char *fullpath = hmi_widget_asset_path(w, src, pathbuf, sizeof pathbuf);
        lv_gif_set_src(st->gif, fullpath);    // a missing or non-GIF file: not loaded
        st->loaded = lv_gif_is_loaded(st->gif);
    }
    lv_gif_t *g = (lv_gif_t *)st->gif;
    if (g->timer) lv_timer_pause(g->timer);   // our timer steps the frames
    if (st->loaded) {
        lv_obj_remove_flag(st->gif, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(st->placeholder, LV_OBJ_FLAG_HIDDEN);
        apply_fill(st, hmi_widget_str(w, "fillMode", "Image.PreserveAspectFit"));
    } else {
        lv_obj_add_flag(st->gif, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(st->placeholder, LV_OBJ_FLAG_HIDDEN);
    }
    apply_playing(st);
}

// The LVGL objects can go before destroy() runs (a test deleting the widget,
// a page torn down): the frame timer goes with them.
static void gif_deleted_cb(lv_event_t *e)
{
    anim_state_t *st = lv_event_get_user_data(e);
    if (!st) return;
    if (st->timer) lv_timer_delete(st->timer);
    st->timer = NULL;
    st->loaded = false;
}

static int speed_of(double v)
{
    int s = (int)(v + 0.5);
    return s < 1 ? 1 : s;
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    int ow = (int)w->width, oh = (int)w->height;
    anim_state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;

    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_remove_style_all(root);
    lv_obj_set_size(root, ow, oh);
    st->root = root;

    lv_obj_t *clip = lv_obj_create(root);
    lv_obj_remove_style_all(clip);
    lv_obj_set_size(clip, ow, oh);
    lv_obj_remove_flag(clip, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(clip, LV_OBJ_FLAG_CLICKABLE);
    st->clip = clip;

    lv_obj_t *gif = lv_gif_create(clip);
    lv_obj_remove_style_all(gif);
    lv_obj_set_pos(gif, 0, 0);
    lv_obj_set_size(gif, ow, oh);
    st->gif = gif;

    lv_obj_t *ph = lv_obj_create(root);
    lv_obj_remove_style_all(ph);
    lv_obj_set_size(ph, ow, oh);
    lv_obj_remove_flag(ph, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(ph, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_radius(ph, 6, 0);
    lv_obj_set_style_bg_color(ph, hmi_colour("muted"), 0);
    lv_obj_set_style_bg_opa(ph, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(ph, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(ph, 1, 0);
    lv_obj_add_event_cb(ph, placeholder_draw_cb, LV_EVENT_DRAW_MAIN, NULL);
    st->placeholder = ph;

    ph_geom_t g = ph_geom(ow, oh);
    const lv_font_t *font = hmi_font(g.text_px, 600);
    st->label = hmi_make_label(ph, g.text_px, 600, hmi_colour("mutedForeground"), "GIF");
    lv_obj_set_width(st->label, ow);
    lv_obj_set_style_text_align(st->label, LV_TEXT_ALIGN_CENTER, 0);
    int line = font ? lv_font_get_line_height(font) : g.text_px;
    lv_obj_set_pos(st->label, 0, g.top + g.glyph + g.gap + hmi_px((g.text_px - line) / 2.0));

    st->speed = speed_of(hmi_widget_num(w, "speed", 100));
    st->playing = hmi_widget_bool(w, "playing", true);
    st->timer = lv_timer_create(frame_tick_cb, FRAME_TICK_MS, st);
    lv_timer_pause(st->timer);
    lv_obj_add_event_cb(gif, gif_deleted_cb, LV_EVENT_DELETE, st);

    load(w, st, hmi_widget_str(w, "source", ""));
    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    anim_state_t *st = w->state;
    if (!st || !st->timer) return;
    if (strcmp(prop, "source") == 0) {
        load(w, st, hmi_value_as_str(value, ""));
    } else if (strcmp(prop, "playing") == 0) {
        st->playing = hmi_value_as_bool(value, true);
        apply_playing(st);
    } else if (strcmp(prop, "speed") == 0) {
        st->speed = speed_of(hmi_value_as_num(value, 100));
    } else if (strcmp(prop, "fillMode") == 0) {
        if (st->loaded) apply_fill(st, hmi_value_as_str(value, "Image.PreserveAspectFit"));
    }
}

static void destroy(hmi_widget_t *w)
{
    anim_state_t *st = w->state;
    if (!st) return;
    if (st->timer) {
        lv_timer_delete(st->timer);
        st->timer = NULL;
        lv_obj_remove_event_cb_with_user_data(st->gif, gif_deleted_cb, st);
    }
    lv_free(st);
    w->state = NULL;
}

const hmi_widget_ops_t hmi_widget_shanimatedimage = {"ShAnimatedImage", create, set_prop, destroy};
