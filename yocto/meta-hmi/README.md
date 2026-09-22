# meta-hmi

Yocto/OpenEmbedded layer that packages the HMI stack for Toradex Verdin
i.MX8M Plus targets running the **native** Toradex Yocto Reference
Multimedia Image (systemd). The GUI draws to DRM/KMS itself: no Qt, no
compositor.

This layer is NOT for Torizon OS or any container-based deployment.

## Recipes

| Recipe | Package | Purpose |
|---|---|---|
| recipes-hmi/hmi-core | hmi-core | Hardware daemon, installer, systemd units |
| recipes-hmi/hmi-ui | hmi-ui | The panel GUI runtime (native/hmi-ui: C + LVGL on DRM/KMS) |
| recipes-hmi/hmi-ui-kit | hmi-ui-kit | Inter fonts and Tabler icon PNGs hmi-ui renders with |
| recipes-hmi/packagegroups | packagegroup-hmi | Aggregates the three packages + runtime extras |
| recipes-images | tdx-reference-multimedia-image.bbappend | Adds packagegroup-hmi to the image |

## Layer Dependencies

- `core` (meta)
- `openembedded-layer` (meta-openembedded/meta-oe)

## Compatibility

Validated against Yocto releases: kirkstone, mickledore, nanbield, scarthgap,
styhead.  See `conf/layer.conf` for the Toradex BSP mapping.

## Maintainer

Project: BYOA HMI
Layer contact: set this to your team distribution list or ticket queue.

## License

MIT - see COPYING.MIT.