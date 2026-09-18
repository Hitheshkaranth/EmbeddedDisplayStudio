# hmi-gui — Native Qt 6 GUI Loader

Panel GUI loader (Layer 2) replacing the Python/PySide6 `gui/hmi_loader`.

## Build

```bash
# WSL / Linux (from repo root)
bash native/hmi-gui/build.sh          # build only
bash native/hmi-gui/build.sh --test   # build + run ctest unit tests

# Windows (PowerShell)
powershell -File native/hmi-gui/build.ps1 --test
```

Binary output: `native/hmi-gui/out/hmi-gui`.

## Run

```bash
QT_QPA_PLATFORM=offscreen ./out/hmi-gui --apps-dir /opt/hmi_apps/current \
  --rx-port 5001 --daemon-host 127.0.0.1 --daemon-port 5000 \
  --ready-file /run/hmi/gui-ready --windowed --theme light --log-level INFO
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--apps-dir` | `/opt/hmi_apps/current` | Bundle directory |
| `--shell` | `<exe>/../shell/Shell.qml` | Shell QML path |
| `--rx-port` | `5001` | UDP telemetry receive port |
| `--daemon-host` | `127.0.0.1` | Hardware daemon address |
| `--daemon-port` | `5000` | Hardware daemon port |
| `--ready-file` | `/run/hmi/gui-ready` | Readiness marker file |
| `--windowed` | (off) | Desktop windowed mode |
| `--theme` | manifest / dark | `"light"` or `"dark"` |
| `--exit-after` | (hidden) | Quit after N ms (smoke tests) |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## File ↔ Python mapping

| C++ (native) | Python (`gui/hmi_loader`) |
|---|---|
| `src/log.cpp` | `main.py` `qml_log_handler` / `logging` |
| `src/manifest.cpp` | `main.py` `validate_manifest` / `resolve_theme` |
| `src/hmi.cpp` | `main.py` `class Hmi` |
| `src/busshim.cpp` | `tagengine.py` `BUS_QML` / `expose_to_qml` |
| `src/tagengine.cpp` | `tagengine.py` `class TagEngine` |

## Log format

`LEVEL - hmi-gui - message` — written to stdout, flushed per line.
`qCDebug` output: `DEBUG - hmi-gui - ...` (only at `--log-level DEBUG`).
QML/Qt messages: `WARNING - hmi-gui - QML Warning: ...`

## Tests

Unit tests (QTest, ctest): `bash native/hmi-gui/build.sh --test`

Conformance suite (Python): `python -m unittest discover -s tests/native -t . -v`