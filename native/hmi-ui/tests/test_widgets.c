// tests/test_widgets.c -- widget behaviour that a still render cannot show:
// what a tap does. Widgets are built headless from a one-widget project, the
// way `hmi-ui --render-widget` builds them.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "check.h"
#include "compat.h"
#include "display.h"
#include "model.h"
#include "registry.h"
#include "theme.h"
#include "src/libs/gif/lv_gif_private.h"
#include "src/core/lv_obj_draw_private.h"
#include "widgets/draw_util.h"

static hmi_project_t *one_widget_sized(const char *type, const char *props_json, int width, int height)
{
    char path[512], err[256];
    FILE *f = hmi_tmpfile(path, sizeof path);
    if (!f) return NULL;
    fprintf(f, "{\"name\":\"t\",\"screen\":{\"width\":320,\"height\":120,\"theme\":\"dark\"},"
               "\"pages\":[{\"id\":\"main\",\"widgets\":[{\"type\":\"%s\",\"id\":\"sample\","
               "\"geometry\":{\"x\":0,\"y\":0,\"width\":%d,\"height\":%d},\"properties\":%s}]}]}",
            type, width, height, props_json);
    fclose(f);
    hmi_project_t *p = hmi_project_load(path, err, sizeof err);
    hmi_remove(path);
    if (!p) fprintf(stderr, "load: %s\n", err);
    return p;
}

static hmi_project_t *one_widget(const char *type, const char *props_json)
{
    return one_widget_sized(type, props_json, 160, 40);
}

static hmi_widget_t *build(hmi_project_t *p)
{
    hmi_widget_t *w = p->pages[0]->widgets[0];
    const hmi_widget_ops_t *ops = hmi_registry_find(w->type);
    w->native = ops->create(w, lv_screen_active());
    hmi_widget_apply_common(w);
    lv_obj_update_layout(lv_screen_active());
    return w;
}

// The knob is the track's only child; its x says which side it is on.
static int32_t knob_x(hmi_widget_t *w)
{
    lv_obj_t *row = lv_obj_get_child(w->native, 0);
    lv_obj_t *track = lv_obj_get_child(row, 0);
    lv_obj_update_layout(lv_screen_active());
    return lv_obj_get_x(lv_obj_get_child(track, 0));
}

static void test_toggle_starts_checked(void)
{
    hmi_project_t *p = one_widget("ShToggle", "{\"checked\":true}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(knob_x(w) > 2);                  // on the right, like the QML
    lv_obj_delete(w->native);
    hmi_project_free(p);
}

static void test_toggle_tap_flips_it(void)
{
    hmi_project_t *p = one_widget("ShToggle", "{\"checked\":false}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(knob_x(w) == 2);
    lv_obj_send_event(w->native, LV_EVENT_CLICKED, NULL);
    CHECK(knob_x(w) > 2);
    lv_obj_send_event(w->native, LV_EVENT_CLICKED, NULL);
    CHECK(knob_x(w) == 2);
    lv_obj_delete(w->native);
    hmi_project_free(p);
}

// -- ShAnimatedImage -----------------------------------------------------------
// root -> [clip -> gif, placeholder]
static lv_obj_t *anim_gif(hmi_widget_t *w) { return lv_obj_get_child(lv_obj_get_child(w->native, 0), 0); }
static lv_obj_t *anim_placeholder(hmi_widget_t *w) { return lv_obj_get_child(w->native, 1); }

static void anim_set(hmi_widget_t *w, const char *prop, hmi_value_t v)
{
    hmi_registry_find(w->type)->set_prop(w, prop, &v);
    hmi_value_free(&v);
}

static void anim_free(hmi_project_t *p, hmi_widget_t *w)
{
    hmi_registry_find(w->type)->destroy(w);
    lv_obj_delete(w->native);
    hmi_project_free(p);
}

// The first pixel of the frame on show: 'r' red, 'b' blue, '?' neither.
static char anim_frame(hmi_widget_t *w)
{
    lv_gif_t *g = (lv_gif_t *)anim_gif(w);
    if (!g->gif || !g->imgdsc.data) return '?';
    const uint8_t *px = g->imgdsc.data;            // ARGB8888: B, G, R, A
    if (px[2] > 150 && px[0] < 100) return 'r';
    if (px[0] > 150 && px[2] < 100) return 'b';
    return '?';
}

static void anim_advance(uint32_t ms)
{
    lv_tick_inc(ms);
    lv_timer_handler();
}

static void test_animated_image_missing_file_draws_placeholder(void)
{
    hmi_project_t *p = one_widget("ShAnimatedImage", "{\"source\":\"assets/no_such_truck.gif\"}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(!lv_gif_is_loaded(anim_gif(w)));
    CHECK(lv_obj_has_flag(anim_gif(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(!lv_obj_has_flag(anim_placeholder(w), LV_OBJ_FLAG_HIDDEN));
    lv_refr_now(NULL);                             // draws without crashing
    // Bindings reaching a widget with nothing loaded are harmless.
    anim_set(w, "playing", hmi_value_bool(false));
    anim_set(w, "playing", hmi_value_bool(true));
    anim_set(w, "speed", hmi_value_num(250));
    anim_set(w, "fillMode", hmi_value_str("Image.Stretch"));
    anim_advance(500);
    // A file that is not a GIF is a placeholder too.
    anim_set(w, "source", hmi_value_str(HMI_REPO_ROOT "/ui/qml/Shadcn/qmldir"));
    CHECK(!lv_gif_is_loaded(anim_gif(w)));
    CHECK(!lv_obj_has_flag(anim_placeholder(w), LV_OBJ_FLAG_HIDDEN));
    lv_refr_now(NULL);
    anim_free(p, w);
}

static void test_animated_image_plays_pauses_and_scales_speed(void)
{
    hmi_project_t *p = one_widget("ShAnimatedImage",
        "{\"source\":\"" HMI_REPO_ROOT "/tests/fixtures/animated/two_frames.gif\","
        "\"fillMode\":\"Image.PreserveAspectCrop\"}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(lv_gif_is_loaded(anim_gif(w)));
    CHECK(!lv_obj_has_flag(anim_gif(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_obj_has_flag(anim_placeholder(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_image_get_inner_align(anim_gif(w)) == LV_IMAGE_ALIGN_COVER);
    CHECK(anim_frame(w) == 'r');                   // frame 1 shows at once
    anim_advance(150);                             // frames are 100 ms
    CHECK(anim_frame(w) == 'b');
    lv_refr_now(NULL);

    anim_set(w, "playing", hmi_value_bool(false)); // holds the frame
    anim_advance(150);
    anim_advance(150);
    CHECK(anim_frame(w) == 'b');
    anim_set(w, "playing", hmi_value_bool(true));
    anim_advance(150);
    CHECK(anim_frame(w) == 'r');                   // loops

    anim_set(w, "speed", hmi_value_num(50));       // 100 ms frames last 200 ms
    anim_advance(150);
    CHECK(anim_frame(w) == 'r');
    anim_advance(100);
    CHECK(anim_frame(w) == 'b');

    anim_set(w, "fillMode", hmi_value_str("Image.Stretch"));
    CHECK(lv_image_get_inner_align(anim_gif(w)) == LV_IMAGE_ALIGN_STRETCH);

    anim_set(w, "source", hmi_value_str("assets/gone.gif"));   // the file went away
    CHECK(!lv_gif_is_loaded(anim_gif(w)));
    CHECK(!lv_obj_has_flag(anim_placeholder(w), LV_OBJ_FLAG_HIDDEN));
    anim_advance(300);
    lv_refr_now(NULL);
    anim_free(p, w);
}

// The page can be torn down before destroy() runs; the frame timer goes too.
static void test_animated_image_deleted_before_destroy(void)
{
    hmi_project_t *p = one_widget("ShAnimatedImage",
        "{\"source\":\"" HMI_REPO_ROOT "/tests/fixtures/animated/two_frames.gif\"}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    lv_obj_delete(w->native);
    anim_advance(300);                             // no timer left on a dead object
    hmi_registry_find(w->type)->destroy(w);
    CHECK(w->state == NULL);
    hmi_project_free(p);
}

// An Image with no picture yet is a framed placeholder, not nothing.
static void test_image_without_source_is_a_placeholder(void)
{
    hmi_project_t *p = one_widget("Image", "{\"source\":\"\"}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(lv_obj_get_style_border_width(w->native, 0) > 0);
    CHECK(lv_obj_get_child_count(w->native) == 1);       // the caption
    lv_obj_delete(w->native);
    hmi_project_free(p);
}

// -- ShProcessValue ------------------------------------------------------------
// root -> [label, spark box, value box, value, unit]
static lv_obj_t *pv_label(hmi_widget_t *w) { return lv_obj_get_child(w->native, 0); }
static lv_obj_t *pv_spark(hmi_widget_t *w) { return lv_obj_get_child(w->native, 1); }
static lv_obj_t *pv_box(hmi_widget_t *w) { return lv_obj_get_child(w->native, 2); }
static lv_obj_t *pv_value(hmi_widget_t *w) { return lv_obj_get_child(w->native, 3); }
static lv_obj_t *pv_unit(hmi_widget_t *w) { return lv_obj_get_child(w->native, 4); }
static const char *pv_text(hmi_widget_t *w) { return lv_label_get_text(pv_value(w)); }
static uint32_t pv_rgb(lv_obj_t *o) { return lv_color_to_u32(lv_obj_get_style_text_color(o, 0)) & 0xffffff; }

static void test_process_value_defaults_and_values(void)
{
    hmi_project_t *p = one_widget_sized("ShProcessValue", "{\"label\":\"Hot Blast Temp\",\"value\":1185,\"unit\":\"\xc2\xb0" "C\"}", 280, 30);
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(lv_obj_get_child_count(w->native) == 5);
    CHECK_EQ_STR(lv_label_get_text(pv_label(w)), "Hot Blast Temp");
    CHECK_EQ_STR(pv_text(w), "1185");                       // decimals -1: as given
    CHECK(pv_rgb(pv_value(w)) == 0x3ee05a);                 // the default SCADA green
    CHECK(lv_obj_has_flag(pv_spark(w), LV_OBJ_FLAG_HIDDEN));  // trend off
    CHECK(!lv_obj_has_flag(pv_unit(w), LV_OBJ_FLAG_HIDDEN));
    // the value box sits left of the unit column and is >= 26 % of the width
    CHECK(lv_obj_get_width(pv_box(w)) >= (int32_t)lround(280 * 0.26));
    CHECK(lv_obj_get_x(pv_box(w)) + lv_obj_get_width(pv_box(w)) + 6 == lv_obj_get_x(pv_unit(w)));
    // the digits sit inside the box, right-aligned
    CHECK(lv_obj_get_x(pv_value(w)) + lv_obj_get_width(pv_value(w)) + 8 == lv_obj_get_x(pv_box(w)) + lv_obj_get_width(pv_box(w)));
    CHECK(lv_obj_get_style_text_align(pv_value(w), 0) == LV_TEXT_ALIGN_RIGHT);

    // with the sparkline in, the label shrinks to fit rather than elide at 280 px
    anim_set(w, "trend", hmi_value_bool(true));
    CHECK_EQ_STR(lv_label_get_text(pv_label(w)), "Hot Blast Temp");
    anim_set(w, "trend", hmi_value_bool(false));

    anim_set(w, "value", hmi_value_num(3.14159));
    CHECK_EQ_STR(pv_text(w), "3.14159");
    anim_set(w, "decimals", hmi_value_num(2));
    CHECK_EQ_STR(pv_text(w), "3.14");
    anim_set(w, "value", hmi_value_str("76,600"));            // not a number: shown as is
    CHECK_EQ_STR(pv_text(w), "76,600");
    anim_set(w, "value", hmi_value_str("12.5"));              // a numeric string is formatted
    CHECK_EQ_STR(pv_text(w), "12.50");
    anim_set(w, "decimals", hmi_value_num(0));
    anim_set(w, "value", hmi_value_num(1184.6));
    CHECK_EQ_STR(pv_text(w), "1185");
    anim_free(p, w);
}

static void test_process_value_warn_colour(void)
{
    hmi_project_t *p = one_widget("ShProcessValue", "{\"value\":50,\"warnAbove\":100,\"warnBelow\":10,"
                                                     "\"valueColor\":\"#ffd84a\"}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    uint32_t warn = lv_color_to_u32(hmi_colour("warning")) & 0xffffff;
    CHECK(pv_rgb(pv_value(w)) == 0xffd84a);
    anim_set(w, "value", hmi_value_num(120));
    CHECK(pv_rgb(pv_value(w)) == warn);
    anim_set(w, "value", hmi_value_num(60));
    CHECK(pv_rgb(pv_value(w)) == 0xffd84a);
    anim_set(w, "value", hmi_value_num(5));
    CHECK(pv_rgb(pv_value(w)) == warn);
    anim_set(w, "value", hmi_value_str("n/a"));               // no number, no warning
    CHECK(pv_rgb(pv_value(w)) == 0xffd84a);
    anim_set(w, "warnBelow", hmi_value_num(0));               // 0 turns a limit off
    anim_set(w, "value", hmi_value_num(5));
    CHECK(pv_rgb(pv_value(w)) == 0xffd84a);
    anim_free(p, w);
}

static void test_process_value_trend_and_unit_column(void)
{
    hmi_project_t *p = one_widget_sized("ShProcessValue", "{\"label\":\"Blast Vol\",\"value\":\"76,600\",\"unit\":\"Nm\xc2\xb3/min\"}", 280, 30);
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    int32_t boxX = lv_obj_get_x(pv_box(w));
    int32_t labelW = lv_obj_get_width(pv_label(w));
    CHECK(labelW == boxX - 6);
    // trend on: the sparkline box takes 18 % between the label and the box
    anim_set(w, "trend", hmi_value_bool(true));
    lv_obj_update_layout(lv_screen_active());
    CHECK(!lv_obj_has_flag(pv_spark(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_obj_get_width(pv_spark(w)) == (int32_t)lround(280 * 0.18));
    CHECK(lv_obj_get_x(pv_spark(w)) + lv_obj_get_width(pv_spark(w)) + 6 == boxX);
    CHECK(lv_obj_get_width(pv_label(w)) == lv_obj_get_x(pv_spark(w)) - 6);
    CHECK(lv_obj_get_height(pv_spark(w)) == lv_obj_get_height(pv_box(w)));
    // numeric updates feed the sparkline and draw without trouble
    for (int i = 0; i < 40; ++i) anim_set(w, "value", hmi_value_num(1000 + (i % 7) * 10));
    lv_obj_invalidate(w->native);
    lv_refr_now(NULL);
    CHECK_EQ_STR(pv_text(w), "1040");
    // trend off again: the label gets its room back
    anim_set(w, "trend", hmi_value_bool(false));
    lv_obj_update_layout(lv_screen_active());
    CHECK(lv_obj_has_flag(pv_spark(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_obj_get_width(pv_label(w)) == lv_obj_get_x(pv_box(w)) - 6);
    // an empty unit collapses its column: the box ends at the right edge
    anim_set(w, "unit", hmi_value_str(""));
    lv_obj_update_layout(lv_screen_active());
    CHECK(lv_obj_has_flag(pv_unit(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_obj_get_x(pv_box(w)) + lv_obj_get_width(pv_box(w)) == 280);
    CHECK(lv_obj_get_x(pv_box(w)) > boxX);
    anim_free(p, w);
}

// ShButton.qml's designer overrides (a navigation row's highlighted tab:
// green text and border) win over the variant; unset, the variant's stay.
static void test_button_colour_overrides(void)
{
    hmi_project_t *p = one_widget("ShButton", "{\"text\":\"FURNACE\",\"variant\":\"secondary\","
                                  "\"textColor\":\"#22c55e\",\"borderColor\":\"#22c55e\",\"borderWidth\":2}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    lv_obj_t *label = lv_obj_get_child(w->native, 0);
    CHECK((lv_color_to_u32(lv_obj_get_style_text_color(label, 0)) & 0xffffff) == 0x22c55e);
    CHECK((lv_color_to_u32(lv_obj_get_style_border_color(w->native, 0)) & 0xffffff) == 0x22c55e);
    CHECK(lv_obj_get_style_border_width(w->native, 0) == 2);
    lv_obj_delete(w->native);
    hmi_project_free(p);

    p = one_widget("ShButton", "{\"text\":\"TRENDS\",\"variant\":\"secondary\"}");
    CHECK(p != NULL);
    if (!p) return;
    w = build(p);
    label = lv_obj_get_child(w->native, 0);
    uint32_t want = lv_color_to_u32(hmi_colour("secondaryForeground")) & 0xffffff;
    CHECK((lv_color_to_u32(lv_obj_get_style_text_color(label, 0)) & 0xffffff) == want);
    CHECK(lv_obj_get_style_border_width(w->native, 0) == 0);
    lv_obj_delete(w->native);
    hmi_project_free(p);
}

// -- style options: header band, gradients, glow, bevel ----------------------

static uint32_t rgb(lv_color_t c) { return lv_color_to_u32(c) & 0xffffff; }


// Unset, a card is the flat card it always was: no band, no gradient.
static void test_card_style_defaults_are_flat(void)
{
    hmi_project_t *p = one_widget_sized("ShCard", "{}", 280, 150);
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(lv_obj_has_flag(lv_obj_get_child(w->native, 0), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_obj_get_style_bg_grad_dir(w->native, 0) == LV_GRAD_DIR_NONE);
    CHECK(rgb(lv_obj_get_style_bg_color(w->native, 0)) == 0x18181b);
    CHECK(lv_obj_get_style_border_width(w->native, 0) == 1);
    anim_free(p, w);
}

// headerHeight 30: a band inside the 1 px border, 29 px high, its fill the
// card colour 12 % lighter, cut square at the bottom, and a 1 px divider in
// the border colour as its last row (outer y 29).
static void test_card_header_band(void)
{
    hmi_project_t *p = one_widget_sized("ShCard", "{\"headerHeight\":30,\"color\":\"#141a21\","
                                        "\"borderColor\":\"#2c3640\",\"radius\":6}", 280, 150);
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    lv_obj_t *clip = lv_obj_get_child(w->native, 0);
    lv_obj_t *band = lv_obj_get_child(clip, 0), *divider = lv_obj_get_child(clip, 1);
    CHECK(!lv_obj_has_flag(clip, LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_obj_get_height(clip) == 29);
    CHECK(lv_obj_get_width(clip) == 278);
    lv_area_t a;
    lv_obj_get_coords(clip, &a);
    lv_area_t card;
    lv_obj_get_coords(w->native, &card);
    CHECK(a.x1 - card.x1 == 1 && a.y1 - card.y1 == 1);
    CHECK(lv_obj_get_height(band) == 29 + 5);          // + the inner radius, clipped off
    CHECK(lv_obj_get_style_radius(band, 0) == 5);
    CHECK(rgb(lv_obj_get_style_bg_color(band, 0)) == rgb(hmi_shade(lv_color_hex(0x141a21), 12)));
    CHECK(lv_obj_get_style_bg_opa(band, 0) == LV_OPA_COVER);
    lv_obj_get_coords(divider, &a);
    CHECK(a.y1 - card.y1 == 29 && lv_area_get_height(&a) == 1);
    CHECK(rgb(lv_obj_get_style_bg_color(divider, 0)) == 0x2c3640);
    // headerColor wins over the derived shade; 0 takes the band away again.
    anim_set(w, "headerColor", hmi_value_str("#334155"));
    CHECK(rgb(lv_obj_get_style_bg_color(band, 0)) == 0x334155);
    anim_set(w, "headerHeight", hmi_value_num(0));
    CHECK(lv_obj_has_flag(clip, LV_OBJ_FLAG_HIDDEN));
    // the band draws without trouble
    anim_set(w, "headerHeight", hmi_value_num(30));
    lv_obj_invalidate(w->native);
    lv_refr_now(NULL);
    anim_free(p, w);
}

// gradient: 6 % lighter at the top to the card colour at the bottom.
static void test_card_gradient(void)
{
    hmi_project_t *p = one_widget_sized("ShCard", "{\"gradient\":true,\"color\":\"#1f2937\"}", 280, 150);
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(lv_obj_get_style_bg_grad_dir(w->native, 0) == LV_GRAD_DIR_VER);
    CHECK(rgb(lv_obj_get_style_bg_color(w->native, 0)) == rgb(hmi_shade(lv_color_hex(0x1f2937), 6)));
    CHECK(rgb(lv_obj_get_style_bg_grad_color(w->native, 0)) == 0x1f2937);
    anim_set(w, "gradient", hmi_value_bool(false));
    CHECK(lv_obj_get_style_bg_grad_dir(w->native, 0) == LV_GRAD_DIR_NONE);
    CHECK(rgb(lv_obj_get_style_bg_color(w->native, 0)) == 0x1f2937);
    anim_free(p, w);
}

static void test_shade_helper(void)
{
    CHECK(rgb(hmi_shade(lv_color_hex(0x000000), 50)) == 0x808080);
    CHECK(rgb(hmi_shade(lv_color_hex(0x804020), -50)) == 0x402010);
    CHECK(rgb(hmi_shade(lv_color_hex(0x123456), 0)) == 0x123456);
    CHECK(rgb(hmi_shade(lv_color_hex(0x808080), 200)) == 0xffffff);
}

// gradient: a raised key around the fill; glowColor: a shadow of that colour.
static void test_button_gradient_and_glow(void)
{
    hmi_project_t *p = one_widget_sized("ShButton", "{\"text\":\"FURNACE\",\"variant\":\"secondary\","
                                        "\"backgroundColor\":\"#2a2f36\",\"gradient\":true,"
                                        "\"glowColor\":\"#22c55e\"}", 136, 48);
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    lv_color_t fill = lv_color_hex(0x2a2f36);
    CHECK(lv_obj_get_style_bg_grad_dir(w->native, 0) == LV_GRAD_DIR_VER);
    CHECK(rgb(lv_obj_get_style_bg_color(w->native, 0)) == rgb(hmi_shade(fill, 12)));
    CHECK(rgb(lv_obj_get_style_bg_grad_color(w->native, 0)) == rgb(hmi_shade(fill, -12)));
    CHECK(lv_obj_get_style_shadow_width(w->native, 0) == HMI_GLOW_BLUR);
    CHECK(rgb(lv_obj_get_style_shadow_color(w->native, 0)) == 0x22c55e);
    CHECK(lv_obj_get_style_shadow_opa(w->native, 0) == HMI_GLOW_OPA);
    CHECK(lv_obj_get_style_shadow_offset_y(w->native, 0) == 0);
    // the glow needs room outside the box: widget roots let it out
    CHECK(lv_obj_has_flag(w->native, LV_OBJ_FLAG_OVERFLOW_VISIBLE));
    CHECK(lv_obj_get_ext_draw_size(w->native) >= HMI_GLOW_BLUR / 2 + HMI_GLOW_SPREAD);
    lv_obj_invalidate(w->native);
    lv_refr_now(NULL);
    // a variant change keeps the gradient and does not compound it
    anim_set(w, "variant", hmi_value_str("default"));
    anim_set(w, "variant", hmi_value_str("secondary"));
    CHECK(rgb(lv_obj_get_style_bg_color(w->native, 0)) == rgb(hmi_shade(fill, 12)));
    // off again
    anim_set(w, "glowColor", hmi_value_str(""));
    anim_set(w, "gradient", hmi_value_bool(false));
    CHECK(lv_obj_get_style_shadow_width(w->native, 0) == 0);
    CHECK(lv_obj_get_style_bg_grad_dir(w->native, 0) == LV_GRAD_DIR_NONE);
    CHECK(rgb(lv_obj_get_style_bg_color(w->native, 0)) == 0x2a2f36);
    anim_free(p, w);

    // an outline button has no fill to shade; unset, no glow
    p = one_widget("ShButton", "{\"variant\":\"outline\",\"gradient\":true}");
    CHECK(p != NULL);
    if (!p) return;
    w = build(p);
    CHECK(lv_obj_get_style_bg_grad_dir(w->native, 0) == LV_GRAD_DIR_NONE);
    CHECK(lv_obj_get_style_shadow_width(w->native, 0) == 0);
    anim_free(p, w);
}

// litColor replaces the severity's colour; glow lights a shadow only when lit.
static void test_annunciator_lit_colour_and_glow(void)
{
    hmi_project_t *p = one_widget_sized("ShAnnunciator", "{\"text\":\"BLOWER RUNNING\",\"lit\":true,"
                                        "\"litColor\":\"#22d34a\",\"glow\":true}", 600, 36);
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(rgb(lv_obj_get_style_bg_color(w->native, 0)) == 0x22d34a);
    CHECK(rgb(lv_obj_get_style_border_color(w->native, 0)) == 0x22d34a);
    CHECK(lv_obj_get_style_shadow_width(w->native, 0) == HMI_GLOW_BLUR);
    CHECK(rgb(lv_obj_get_style_shadow_color(w->native, 0)) == 0x22d34a);
    CHECK(lv_obj_get_style_shadow_opa(w->native, 0) == HMI_GLOW_OPA);
    lv_obj_invalidate(w->native);
    lv_refr_now(NULL);
    anim_set(w, "lit", hmi_value_bool(false));
    CHECK(lv_obj_get_style_shadow_opa(w->native, 0) == LV_OPA_TRANSP);
    CHECK(lv_obj_get_style_shadow_width(w->native, 0) == 0);
    // unlit, the caption is still drawn in the lit colour
    CHECK(rgb(lv_obj_get_style_text_color(lv_obj_get_child(w->native, 0), 0)) == 0x22d34a);
    anim_set(w, "litColor", hmi_value_str(""));
    anim_set(w, "lit", hmi_value_bool(true));
    CHECK(rgb(lv_obj_get_style_bg_color(w->native, 0)) == rgb(hmi_colour("efisCaution")));
    anim_free(p, w);

    p = one_widget("ShAnnunciator", "{\"lit\":true}");
    CHECK(p != NULL);
    if (!p) return;
    w = build(p);
    CHECK(lv_obj_get_style_shadow_width(w->native, 0) == 0);
    anim_free(p, w);
}

// bevel: in each box, a 1 px darker line along the top and a 1 px lighter one
// along the bottom, inside the border (outer x 2 .. w-3, y 1 and h-2).
static void test_process_value_bevel(void)
{
    hmi_project_t *p = one_widget_sized("ShProcessValue", "{\"label\":\"Hot Blast Temp\",\"value\":1185,"
                                        "\"unit\":\"\xc2\xb0" "C\",\"trend\":true}", 280, 30);
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    lv_obj_t *box = pv_box(w);
    CHECK(lv_obj_has_flag(lv_obj_get_child(box, 0), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_obj_has_flag(lv_obj_get_child(box, 1), LV_OBJ_FLAG_HIDDEN));
    anim_set(w, "bevel", hmi_value_bool(true));
    lv_obj_update_layout(lv_screen_active());
    lv_obj_t *boxes[2] = {pv_box(w), pv_spark(w)};
    for (int b = 0; b < 2; ++b) {
        lv_obj_t *o = boxes[b];
        lv_area_t outer, top, bottom;
        lv_obj_get_coords(o, &outer);
        lv_obj_get_coords(lv_obj_get_child(o, 0), &top);
        lv_obj_get_coords(lv_obj_get_child(o, 1), &bottom);
        CHECK(!lv_obj_has_flag(lv_obj_get_child(o, 0), LV_OBJ_FLAG_HIDDEN));
        CHECK(!lv_obj_has_flag(lv_obj_get_child(o, 1), LV_OBJ_FLAG_HIDDEN));
        CHECK(top.y1 - outer.y1 == 1 && lv_area_get_height(&top) == 1);
        CHECK(outer.y2 - bottom.y2 == 1 && lv_area_get_height(&bottom) == 1);
        CHECK(top.x1 - outer.x1 == 2 && outer.x2 - top.x2 == 2);
        CHECK(rgb(lv_obj_get_style_bg_color(lv_obj_get_child(o, 0), 0)) == rgb(hmi_shade(lv_color_hex(0x0a0d0b), -70)));
        CHECK(rgb(lv_obj_get_style_bg_color(lv_obj_get_child(o, 1), 0)) == rgb(hmi_shade(lv_color_hex(0x0a0d0b), 20)));
    }
    // the root's children are unchanged (label, spark, box, value, unit)
    CHECK(lv_obj_get_child_count(w->native) == 5);
    CHECK_EQ_STR(pv_text(w), "1185");
    lv_obj_invalidate(w->native);
    lv_refr_now(NULL);
    anim_set(w, "bevel", hmi_value_bool(false));
    CHECK(lv_obj_has_flag(lv_obj_get_child(pv_box(w), 0), LV_OBJ_FLAG_HIDDEN));
    anim_free(p, w);
}

int main(void)
{
    lv_init();
    hmi_kit_register_all();
    hmi_theme_init(HMI_REPO_ROOT "/ui/qml/Shadcn", true);
    hmi_display_headless(320, 120);
    test_toggle_starts_checked();
    test_toggle_tap_flips_it();
    test_image_without_source_is_a_placeholder();
    test_animated_image_missing_file_draws_placeholder();
    test_animated_image_plays_pauses_and_scales_speed();
    test_animated_image_deleted_before_destroy();
    test_process_value_defaults_and_values();
    test_process_value_warn_colour();
    test_process_value_trend_and_unit_column();
    test_button_colour_overrides();
    test_shade_helper();
    test_card_style_defaults_are_flat();
    test_card_header_band();
    test_card_gradient();
    test_button_gradient_and_glow();
    test_annunciator_lit_colour_and_glow();
    test_process_value_bevel();
    return check_summary("test_widgets");
}
