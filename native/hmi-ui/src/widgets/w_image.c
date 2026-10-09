// widgets/w_image.c -- kit widget Image (Basic, "Image").
//
// Spec: ui/qml/Shadcn/Image.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): source, fillMode, smooth, opacity, visible.
// Default size 160x120. Signals: none.
#include <string.h>
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *img;
    lv_obj_t *hint;     // the placeholder's caption, while there is no picture
} image_state_t;

// No picture yet (an AI design's "put the truck here"): a framed, faintly
// filled box with a caption, as the Designer canvas draws it, rather than
// nothing on the glass. A source set later takes the frame away.
static void placeholder(image_state_t *st, bool on)
{
    lv_obj_t *img = st->img;
    lv_obj_set_style_border_width(img, on ? 1 : 0, 0);
    lv_obj_set_style_border_color(img, hmi_colour("border"), 0);
    lv_obj_set_style_border_opa(img, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(img, on ? 12 : 0, 0);
    lv_obj_set_style_bg_color(img, hmi_colour("muted"), 0);
    lv_obj_set_style_bg_opa(img, on ? LV_OPA_40 : LV_OPA_TRANSP, 0);
    if (on && !st->hint) {
        st->hint = lv_label_create(img);
        lv_label_set_text(st->hint, "Image");
        lv_obj_set_style_text_font(st->hint, hmi_font(hmi_font_size("fontSizeSm"), 500), 0);
        lv_obj_set_style_text_color(st->hint, hmi_colour("mutedForeground"), 0);
        lv_obj_center(st->hint);
    } else if (!on && st->hint) {
        lv_obj_delete(st->hint);
        st->hint = NULL;
    }
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w;
    lv_obj_t *img = lv_image_create(parent);
    lv_obj_remove_style_all(img);

    image_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->img = img;

    // Try to load the image source
    const char *src = hmi_widget_str(w, "source", "");
    if (src && *src) {
        char pathbuf[512];
        const char *fullpath = hmi_widget_asset_path(w, src, pathbuf, sizeof pathbuf);
        lv_image_set_src(img, fullpath);

        // Auto-scale based on fillMode
        const char *fill = hmi_widget_str(w, "fillMode", "Image.PreserveAspectFit");
        int iw = lv_image_get_src_width(img);
        int ih = lv_image_get_src_height(img);
        int ow = (int)w->width, oh = (int)w->height;
        if (iw > 0 && ih > 0 && ow > 0 && oh > 0) {
            // QML fillMode: PreserveAspectFit scales by min(ow/iw, oh/ih),
            // PreserveAspectCrop by max(...), Stretch to both, Pad not at all.
            double sx = (double)ow / iw, sy = (double)oh / ih;
            double s = 1.0;
            if (strcmp(fill, "Image.PreserveAspectCrop") == 0) s = sx > sy ? sx : sy;
            else if (strcmp(fill, "Image.Stretch") == 0) s = sx;   // LVGL scales uniformly; width wins
            else if (strcmp(fill, "Image.Pad") == 0) s = 1.0;
            else s = sx < sy ? sx : sy;
            lv_image_set_scale(img, (uint32_t)(256.0 * s + 0.5));
            lv_image_set_inner_align(img, LV_IMAGE_ALIGN_CENTER);
            lv_obj_set_size(img, ow, oh);
        }
    } else {
        placeholder(st, true);
    }

    w->state = st;
    return img;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w;
    image_state_t *st = w->state;
    if (!st) return;
    lv_obj_t *img = st->img;

    if (strcmp(prop, "source") == 0) {
        const char *src = hmi_value_as_str(value, "");
        if (src && *src) {
            char pathbuf[512];
            const char *fullpath = hmi_widget_asset_path(w, src, pathbuf, sizeof pathbuf);
            lv_image_set_src(img, fullpath);
        }
        placeholder(st, !(src && *src));
    }
}

static void destroy(hmi_widget_t *w)
{
    image_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_image = {"Image", create, set_prop, destroy};