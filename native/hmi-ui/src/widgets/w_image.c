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
} image_state_t;

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
    }
}

static void destroy(hmi_widget_t *w)
{
    image_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_image = {"Image", create, set_prop, destroy};