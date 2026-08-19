# meta-hmi

Yocto/OpenEmbedded layer that packages the BYOA (Bring Your Own App) HMI
stack for Toradex Verdin i.MX8M Plus targets running the **native** Toradex
Yocto Reference Multimedia Image (Wayland/Weston, systemd).

This layer is NOT for Torizon OS or any container-based deployment.

## Recipes

| Recipe | Package | Purpose |
|---|---|---|
| recipes-hmi/hmi-core | hmi-core | Hardware daemon, installer, systemd units |
| recipes-hmi/hmi-gui | hmi-gui | Python/PySide6 GUI loader and shell QML |
| recipes-hmi/hmi-ui-kit | hmi-ui-kit | Shadcn QML component kit, icon registry |
| recipes-hmi/packagegroups | packagegroup-hmi | Aggregates the three packages + runtime extras |
| recipes-images | tdx-reference-multimedia-image.bbappend | Adds packagegroup-hmi to the image |

## Layer Dependencies

- `core` (meta)
- `openembedded-layer` (meta-openembedded/meta-oe)
- `qt6-layer` (meta-qt6) - required for hmi-gui; see the integrator guide in
  `yocto/README.md` for the exact branch and fetch instructions.

## Compatibility

Validated against Yocto releases: kirkstone, mickledore, nanbield, scarthgap,
styhead.  See `conf/layer.conf` for the Toradex BSP mapping.

## Maintainer

Project: BYOA HMI
Layer contact: set this to your team distribution list or ticket queue.

## License

MIT - see COPYING.MIT.