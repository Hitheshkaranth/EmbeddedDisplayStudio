# hmi-ui for Windows: the Studio's headless preview binary

The same C sources as the panel runtime, cross-compiled with mingw-w64 and
`HMI_UI_WITH_DRM=OFF`: no DRM/KMS, no evdev, no daemon link in use; it only
renders `.edsui` pages and single widgets to PNG so the Studio previews with
the panel's own renderer. `src/compat.h` is the whole OS seam (exe path,
file existence, local time, temp file, sleep/ticks, one UDP socket);
everything else is plain C11, LVGL and cJSON.

```
bash native/hmi-ui/win64/build.sh        # WSL Ubuntu, root -> native/hmi-ui/out/win64/hmi-ui.exe
bash native/hmi-ui/win64/check.sh        # the gate: builds both, renders through interop, compares
```

`build.sh` installs `mingw-w64` on first use, writes a toolchain file into its
build directory (`/root/.cache/hmi-ui-build-win64/...`), links statically
(the exe depends on KERNEL32, msvcrt and WS2_32 only) and builds with
`__USE_MINGW_ANSI_STDIO=1` so number formatting matches glibc: the gate
demands renders within a mean difference of 1.0/255 of the Linux ones and
they come out identical.

```
hmi-ui.exe --render-widget TYPE --headless OUT.png [--size WxH] [--props JSON] [--kit DIR] [--theme dark|light]
hmi-ui.exe --apps-dir DIR --headless OUT.png [--kit DIR] [--theme dark|light]
```

Paths may use either separator and a drive letter (`--kit C:\...\ui\qml\Shadcn`);
without `--kit` the binary walks up from its own directory looking for
`ui/qml/Shadcn/fonts`, so it finds a checkout's kit from `out/win64/`.
`--display` prints "this is the headless build of hmi-ui (no display); use
--headless" and exits (status 0: `check.sh` pipes the exe into `grep -q`
under `pipefail`, which a non-zero exit would fail).
