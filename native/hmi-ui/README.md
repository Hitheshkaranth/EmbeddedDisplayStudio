# hmi-ui — the Qt-free panel runtime (C11 + LVGL 9.3)

Phase 3 of the native port. Loads a bundle's `project.edsui` (the Designer's
own model, already in every deployed bundle) and draws it with LVGL straight
to DRM/KMS — no Qt, no compositor — while speaking the CONTRACT section 2
wire protocol to `hmi-hwd`. The kit contract (`schema/kit_schema.json`,
`src/gen/`) is generated from the Studio's widget registry and `Theme.qml`
by `schema/gen_schema.py`; `--check` proves it is current.

```
bash native/hmi-ui/build.sh --test              # WSL/Linux x86, headless
bash native/hmi-ui/arm64/build.sh               # aarch64 in the bookworm root
bash native/hmi-ui/win64/build.sh               # Windows exe (mingw-w64), headless only
native/hmi-ui/out/hmi-ui --apps-dir <bundle> --headless page.png
native/hmi-ui/out/hmi-ui --render-widget ShClusterGauge --headless w.png
native/hmi-ui/out/hmi-ui --apps-dir /opt/hmi_apps/current --display /dev/dri/card1   # the panel
```

Gates: `ctest` (C unit tests), `tests/ui/test_conformance_ui.py` (protocol,
through a real process with `HMI_GUI_CMD=native/hmi-ui/out/hmi-ui`),
`tests/ui/test_widget_parity.py` (each kit type against the QML kit; PNGs in
`swarm/qc/ui-parity`). Swarm plan and briefs: `swarm/briefs/ui/`.

The headless Windows build (`win64/`) is the Studio's preview renderer: the
same sources cross-compiled with `HMI_UI_WITH_DRM=OFF`, which drops the
DRM/KMS display and evdev input (`lv_conf.h` switches `LV_USE_LINUX_DRM` and
`LV_USE_EVDEV` off with it) and leaves the PNG paths. The operating system
shows through `src/compat.h` only (exe directory, file existence, local time,
temp file, sleep and ticks, the UDP socket); `src/compat.c` has the POSIX and
Windows branches. `win64/check.sh` is its gate: the Windows renders must
match the Linux ones pixel for pixel (they do), and `--display` must be
refused with a message naming the headless build.

## A picture of the glass

`kill -USR1 $(pidof hmi-ui)` makes the running panel write the screen it is
showing — live tag values included — to `/run/hmi/screen.png`
(`$HMI_UI_SNAPSHOT` overrides the path). It is LVGL's own snapshot of the
active screen, so it works whatever the display is; the DRM scanout buffer is
not readable through `/dev/fb0`, which only holds the kernel console.
