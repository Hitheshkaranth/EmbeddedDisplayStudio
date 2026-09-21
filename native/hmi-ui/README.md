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
native/hmi-ui/out/hmi-ui --apps-dir <bundle> --headless page.png
native/hmi-ui/out/hmi-ui --render-widget ShClusterGauge --headless w.png
native/hmi-ui/out/hmi-ui --apps-dir /opt/hmi_apps/current --display /dev/dri/card1   # the panel
```

Gates: `ctest` (C unit tests), `tests/ui/test_conformance_ui.py` (protocol,
through a real process with `HMI_GUI_CMD=native/hmi-ui/out/hmi-ui`),
`tests/ui/test_widget_parity.py` (each kit type against the QML kit; PNGs in
`swarm/qc/ui-parity`). Swarm plan and briefs: `swarm/briefs/ui/`.
