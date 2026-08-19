# Hardware Abstraction Daemon (hmi-hwd)

Layer 1 of the BYOA HMI system for Toradex Verdin i.MX8M Plus.

The Hardware Abstraction Daemon (`hmi_hwd.py`) is the **sole process permitted to interact with physical hardware interfaces** (GPIO, IIO ADC, and UART). It runs as a systemd service (`hmi-hwd.service`) on the target root filesystem, isolates all driver and kernel interaction from user interface code, and exposes a decoupled UDP/JSON wire interface over local loopback (`127.0.0.1`).

---

## 1. Architecture and Wire Interface

```
+-----------------------------------------------------------------------+
|                            hmi_hwd.py                                 |
|                                                                       |
|   /dev/gpiochip*       /sys/bus/iio/devices/       /dev/verdin-uart*  |
|   (libgpiod v1/v2)     (IIO sysfs ADC)             (pyserial)         |
|          |                     |                          |           |
|          +---------------------+--------------------------+           |
|                                |                                      |
|                       Internal Tag Store                              |
|                          (sys.errors)                                 |
|                                |                                      |
|             +------------------+------------------+                   |
|             |                                     |                   |
|   UDP Server :5000                     UDP Publisher :5001            |
|   (Command Protocol & Acks)            (Telemetry Frames to Sinks)    |
+-------------+-------------------------------------+-------------------+
              ^                                     |
              | Commands                            | Telemetry
              | (JSON datagrams)                    | (100 ms default)
              |                                     v
+-------------+-------------------------------------+-------------------+
|                        Client (hmi-gui / scripts)                     |
+-----------------------------------------------------------------------+
```

### 1.1 Endpoints and Transport

* **Command Port:** `127.0.0.1:5000` (UDP, daemon binds here and listens for commands).
* **Static Telemetry Sink:** `127.0.0.1:5001` (UDP, daemon continuously broadcasts frames here).
* **Dynamic Subscribers:** Any client can send a `subscribe` command; the daemon records the client's reply address and transmits telemetry frames to it until the subscription TTL expires.
* **Datagram Limits:** UTF-8 encoded JSON objects. Maximum accepted datagram length is **8192 bytes** (`MAX_DGRAM_BYTES`). Datagrams exceeding 8192 bytes are dropped, counted in `sys.errors`, and answered with `{"t":"ack","ok":false,"err":"too_large"}` if an `id` can be parsed.

### 1.2 Telemetry Frame Format

The daemon publishes telemetry frames periodically (default every 100 ms, configured via `daemon.poll_interval_ms`):

```json
{
  "t": "tags",
  "seq": 4711,
  "ts": 1755600000.123,
  "src": "hmi-hwd",
  "tags": {
    "ai.pot": 1.842000,
    "ai.rail24": 23.950000,
    "di.button": false,
    "di.estop": false,
    "do.led": false,
    "do.relay1": true,
    "sys.errors": 0,
    "sys.uptime": 123.456,
    "uart.last": "",
    "uart.rx": 0
  }
}
```

* `t`: Fixed type identifier `"tags"`.
* `seq`: Integer sequence number, monotonically incremented on each broadcast, wrapping at $2^{31}$ (`SEQ_WRAP = 2147483648`).
* `ts`: Float timestamp in epoch seconds (`time.time()`).
* `src`: Fixed source identifier `"hmi-hwd"`.
* `tags`: Key-value map of all registered tag names to current values.
* **Degradation rule:** If an analog channel or hardware read fails, the tag is published as `null` (`None` in Python), **never omitted**. This ensures QML property bindings remain resolvable without throwing undefined property exceptions.
* `sys.uptime`: Float seconds elapsed since daemon start.
* `sys.errors`: Monotonic cumulative error counter.

### 1.3 Command Set (Client to Daemon)

Commands are sent as single JSON objects to `127.0.0.1:5000`:

#### 1. Set Digital Output (`set`)
Drives a configured digital output pin immediately.
```json
{"id": "c-101", "cmd": "set", "tag": "do.relay1", "value": 1}
```
* `tag`: Output tag name (must have prefix `do.`, exist in configuration, and be writable).
* `value`: `1`, `0`, `true`, or `false`.

#### 2. Pulse Digital Output (`pulse`)
Drives an output pin high (`1`), schedules an asynchronous, non-blocking timer (`asyncio.call_later`), and resets the pin low (`0`) after the specified duration.
```json
{"id": "c-102", "cmd": "pulse", "tag": "do.relay1", "ms": 250}
```
* `ms`: Pulse width in milliseconds, valid range: `1` to `10000` ms (`PULSE_MIN_MS` to `PULSE_MAX_MS`).

#### 3. Transmit UART Data (`uart_tx`)
Writes a string to the configured serial port.
```json
{"id": "c-103", "cmd": "uart_tx", "data": "PING\r\n"}
```
* `data`: String payload to transmit over UART.

#### 4. Dynamic Subscription (`subscribe`)
Registers the sender's UDP host and port to receive telemetry frames.
```json
{"id": "c-104", "cmd": "subscribe", "ttl": 10.0}
```
* `ttl`: (Optional) Float duration in seconds before subscription expires. If omitted, defaults to `daemon.subscriber_ttl_s` (5.0 s).

#### 5. Unsubscribe (`unsubscribe`)
Removes the sender from the dynamic telemetry distribution list.
```json
{"id": "c-105", "cmd": "unsubscribe"}
```

#### 6. List Registered Tags (`list`)
Queries all known tag names registered in the tag store.
```json
{"id": "c-106", "cmd": "list"}
```

#### 7. Ping (`ping`)
Health check command.
```json
{"id": "c-107", "cmd": "ping"}
```

### 1.4 Acknowledgements and Error Handling

When a command includes an `id` field (or is `ping` or `list`), the daemon responds to the sender address:

* **Success Ack:**
  ```json
  {"t": "ack", "id": "c-101", "ok": true}
  ```

* **Tag List Response:**
  ```json
  {"t": "ack", "id": "c-106", "ok": true, "tags": ["ai.pot", "ai.rail24", "di.button", "di.estop", "do.led", "do.relay1", "sys.errors", "sys.uptime", "uart.last", "uart.rx"]}
  ```

* **Failure Ack:**
  ```json
  {"t": "ack", "id": "c-101", "ok": false, "err": "unknown_tag"}
  ```

**Error Code Set (`err`):**
* `bad_json`: Payload could not be parsed as UTF-8 JSON.
* `not_an_object`: Top-level JSON entity is not an object/dictionary.
* `too_large`: Datagram exceeds 8192 bytes.
* `unknown_cmd`: Unrecognized or missing `"cmd"` property.
* `unknown_tag`: Specified tag is not registered in the tag store.
* `not_writable`: Tag is read-only (e.g. `di.*`, `ai.*`, `sys.*`).
* `bad_value`: Value is out of range or of the wrong type (e.g. non-boolean for `set`, out-of-range ms for `pulse`).
* `hw_error`: Kernel or peripheral I/O failure during operation.
* `rate_limited`: Operation suppressed by rate limiting.

---

## 2. Command-Line Interface

`hmi_hwd.py` supports the following execution arguments:

```
usage: hmi_hwd.py [-h] [--config CONFIG] [--sim] [--strict] [--selftest]
                  [--log-level {DEBUG,INFO,WARNING,ERROR}]
```

| Flag | Type / Default | Description |
|---|---|---|
| `--config PATH` | String (default `/etc/hmi/hwd.json`) | Path to the tag and hardware mapping JSON configuration file. |
| `--sim` | Boolean flag | Force software simulation backends. Disables direct access to `/dev/gpiochip*`, `/sys/bus/iio/`, and serial ports. Useful on developer workstations and Windows. |
| `--strict` | Boolean flag | Target mode: exits non-zero (`sys.exit(1)`) immediately if any specified hardware peripheral (`gpiod`, character device, or IIO node) cannot be claimed. |
| `--selftest` | Boolean flag | Executes initialization, performs exactly one poll of all configured inputs, outputs a single telemetry frame JSON string to `stdout`, cleanly shuts down hardware, and exits with code 0. |
| `--log-level LVL` | Choice: `DEBUG`, `INFO`, `WARNING`, `ERROR` (default `INFO`) | Configures Python logging verbosity to `stderr`. |

> [!IMPORTANT]
> The `--sim` and `--strict` flags are mutually exclusive. If both are passed, the daemon logs an error and exits immediately with code 1.

---

## 3. Configuration File (`hwd.json`)

The configuration file defines network parameters and maps symbolic tag names to hardware pins and channels.

### 3.1 Schema Reference

```json
{
  "daemon": {
    "poll_interval_ms": 100,
    "cmd_port": 5000,
    "telemetry_sink": "127.0.0.1:5001",
    "subscriber_ttl_s": 5,
    "log_level": "INFO"
  },
  "gpio": {
    "chip": "/dev/gpiochip3",
    "consumer": "hmi-hwd",
    "outputs": {
      "do.relay1": {
        "offset": 1,
        "active_low": false,
        "safe_state": 0
      },
      "do.led": {
        "offset": 6,
        "active_low": false,
        "safe_state": 0
      }
    },
    "inputs": {
      "di.estop": {
        "offset": 5,
        "active_low": true
      },
      "di.button": {
        "offset": 0,
        "active_low": true
      }
    }
  },
  "adc": {
    "iio_device_name": "ads1015",
    "channels": {
      "ai.pot": {
        "channel_file": "in_voltage0_raw",
        "offset_file": "in_voltage0_offset",
        "scale_file": "in_voltage0_scale",
        "gain": 1.0,
        "transform_offset": 0.0
      },
      "ai.rail24": {
        "channel_file": "in_voltage1_raw",
        "offset_file": "in_voltage1_offset",
        "scale_file": "in_voltage1_scale",
        "gain": 11.0,
        "transform_offset": 0.0
      }
    }
  },
  "uart": {
    "port": "/dev/verdin-uart3",
    "baudrate": 115200,
    "bytesize": 8,
    "parity": "N",
    "stopbits": 1,
    "timeout_s": 0.1
  }
}
```

### 3.2 Key Descriptions

#### Section: `daemon`
* `poll_interval_ms`: Integer (milliseconds). Polling cycle time for reading inputs and publishing telemetry.
* `cmd_port`: Integer UDP port on which the daemon accepts client commands.
* `telemetry_sink`: String `"HOST:PORT"`. Default static recipient for telemetry datagrams.
* `subscriber_ttl_s`: Float or integer (seconds). Default lifespan of dynamic subscriptions created without an explicit `ttl`.
* `log_level`: Default logging level (`"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`).

#### Section: `gpio`
* `chip`: Path to the character device node (e.g. `/dev/gpiochip3`).
* `consumer`: Consumer label assigned to claimed lines (visible in `gpioinfo`).
* `outputs`: Map of output tags. Each entry specifies:
  * `offset`: Integer line offset within the chip.
  * `active_low`: Boolean. If `true`, logical 1 drives the electrical line low.
  * `safe_state`: Integer (`0` or `1`). State driven to the line upon process initialization and during graceful shutdown (`SIGTERM`/`SIGINT`).
* `inputs`: Map of input tags. Each entry specifies:
  * `offset`: Integer line offset within the chip.
  * `active_low`: Boolean. If `true`, electrical low is interpreted as logical `true`.

#### Section: `adc`
* `iio_device_name`: String matching the sysfs `name` file under `/sys/bus/iio/devices/iio:deviceN/name` (e.g. `"ads1015"`).
* `channels`: Map of analog input tags. Each entry specifies:
  * `channel_file`: Sysfs attribute for the raw reading (e.g. `"in_voltage0_raw"`).
  * `offset_file`: Sysfs attribute for ADC offset (e.g. `"in_voltage0_offset"`). If absent, defaults to 0.0.
  * `scale_file`: Sysfs attribute for scaling in mV (e.g. `"in_voltage0_scale"`).
  * `gain`: Float multiplier applied after raw-to-volts conversion (e.g. `11.0` for a 1:11 resistor divider monitoring a 24 V rail).
  * `transform_offset`: Float voltage offset added after gain is applied.
  * **Formula:** $\text{Volts} = \left(\frac{(\text{raw} + \text{offset}) \times \text{scale\_mv}}{1000.0}\right) \times \text{gain} + \text{transform\_offset}$

#### Section: `uart`
* `port`: Device path (e.g. `/dev/verdin-uart3` or `/dev/ttymxc3`).
* `baudrate`: Integer baud rate (e.g. `115200`).
* `bytesize`: Integer data bits (`5`, `6`, `7`, `8`).
* `parity`: String (`"N"`, `"E"`, `"O"`).
* `stopbits`: Integer (`1`, `2`).
* `timeout_s`: Float serial read timeout in seconds.

### 3.3 Tag Naming Rules

All tag names must conform to `TAG_RE` (`^[a-z][a-z0-9]*(\.[a-z0-9_]+)+$`):
* Lowercase alphanumeric characters, separated into segments by dots.
* Standard prefixes:
  * `ai.*`: Analog inputs (read-only float or `null`).
  * `di.*`: Digital inputs (read-only boolean).
  * `do.*`: Digital outputs (writable boolean).
  * `sys.*`: Daemon diagnostics (`sys.uptime`, `sys.errors`).
  * `uart.*`: Serial link status (`uart.rx`, `uart.last`).

---

## 4. Hardware Discovery on Verdin i.MX8M Plus

### 4.1 GPIO Lines (`gpioinfo`)

On Linux BSPs, sysfs GPIO (`/sys/class/gpio`) is deprecated. `hmi_hwd.py` uses character device nodes (`/dev/gpiochipN`) and supports both `libgpiod` 1.x (Toradex BSP 5 / 6) and 2.x (Toradex BSP 7).

To identify GPIO chips and line offsets on the Verdin SoM and carrier board:

```bash
# List all available GPIO chips and line counts
gpiodetect

# Query line names, offsets, directions, and consumers on gpiochip3
gpioinfo gpiochip3

# Inspect a specific line offset (e.g., offset 5 on gpiochip3)
gpioget gpiochip3 5
```

When `hmi_hwd.py` claims lines, `gpioinfo` displays `[used]` with the configured consumer name (`hmi-hwd`).

### 4.2 IIO ADC Channels (`iio_info`)

The Verdin i.MX8M Plus typically reads analog inputs through an I2C ADC on the carrier board (such as the Texas Instruments ADS1015 on the Dahlia or Development Board) or an on-chip ADC.

Because device node indices (`iio:device0`, `iio:device1`) depend on probe ordering, **`hmi_hwd.py` resolves the device by its `name` attribute**, not by index:

```bash
# Scan IIO devices and channels using libiio tools
iio_info

# Manual sysfs inspection
cat /sys/bus/iio/devices/iio:device*/name

# Example: if ads1015 is iio:device0, verify attributes:
ls -l /sys/bus/iio/devices/iio:device0/
cat /sys/bus/iio/devices/iio:device0/in_voltage0_raw
cat /sys/bus/iio/devices/iio:device0/in_voltage0_scale
```

### 4.3 Serial UART Aliases

Toradex udev rules create stable symlinks under `/dev/verdin-uart*`. Prefer these over raw `/dev/ttymxc*` paths:

```bash
ls -l /dev/verdin-uart*
# Output maps verdin-uart1, verdin-uart2, verdin-uart3 to /dev/ttymxcN
```

---

## 5. Device-Tree Overlays and Pinmux Caveats

On the Toradex Verdin i.MX8M Plus, peripheral pins on the 260-pin SODIMM connector are assigned default functions (such as CSI camera, DSI display, SPI, or PWM) in the base device tree.

If a pin is claimed by a kernel driver, requesting it via `libgpiod` or opening its UART device node will fail with `EBUSY` (Device or resource busy) or `EPERM`.

### Freeing Pins via Overlays
1. Identify the pinmux group conflicting with your required GPIO or UART pins in the carrier board device tree source (`imx8mp-verdin-*.dts`).
2. Apply or author a device-tree overlay (`.dtbo`) that disables conflicting nodes and muxes the pins as GPIO (`MX8MP_IOMUXC_*_GPIO*`).
3. Deploy the overlay to `/boot/overlays/` and register it in `/boot/overlays.txt`:
   ```ini
   fdt_overlays=verdin-imx8mp_hmi_overlay.dtbo
   ```
4. Reboot the target before starting `hmi-hwd.service` in `--strict` mode.

---

## 6. Running the Self-Test

The `--selftest` flag executes a complete single-shot hardware read and prints the JSON frame to standard output. This can be used in manufacturing, CI, and boot-up diagnostics:

```bash
# Run self-test using real hardware configuration
python3 /usr/lib/hmi/hmi_hwd.py --config /etc/hmi/hwd.json --selftest

# Run self-test on development host in simulation mode
python3 daemon/hmi_hwd.py --config daemon/hwd.json --sim --selftest
```

**Expected stdout output (exit code 0):**
```json
{"t":"tags","seq":0,"ts":1755600123.456,"src":"hmi-hwd","tags":{"ai.pot":1.842,"ai.rail24":23.95,"di.button":false,"di.estop":false,"do.led":false,"do.relay1":false,"sys.errors":0,"sys.uptime":0.005,"uart.last":"","uart.rx":0}}
```

---

## 7. Python Client Example

Below is a complete, standalone Python script demonstrating how to subscribe to telemetry, listen on UDP `127.0.0.1:5001`, and send a `set` command to `127.0.0.1:5000`:

```python
#!/usr/bin/env python3
"""
client_example.py -- Connect to hmi-hwd, toggle a relay, and print telemetry.
"""

import json
import socket
import time

CMD_ADDR = ("127.0.0.1", 5000)
TELEMETRY_PORT = 5001

def main():
    # 1. Create telemetry listening socket on 127.0.0.1:5001
    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx_sock.bind(("127.0.0.1", TELEMETRY_PORT))
    rx_sock.settimeout(2.0)

    # 2. Create command client socket
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx_sock.settimeout(2.0)

    print(f"Listening for telemetry on 127.0.0.1:{TELEMETRY_PORT}...")

    # 3. Send command to turn do.relay1 ON
    cmd = {
        "id": "cmd-demo-1",
        "cmd": "set",
        "tag": "do.relay1",
        "value": 1
    }
    tx_sock.sendto(json.dumps(cmd).encode("utf-8"), CMD_ADDR)
    print(f"Sent: {cmd}")

    # 4. Receive acknowledgement on tx_sock
    try:
        ack_data, _ = tx_sock.recvfrom(4096)
        ack = json.loads(ack_data.decode("utf-8"))
        print(f"Received Ack: {ack}")
    except socket.timeout:
        print("Warning: Command ack timed out")

    # 5. Read incoming telemetry frames from rx_sock
    print("\nReading 3 telemetry frames:")
    for _ in range(3):
        try:
            data, addr = rx_sock.recvfrom(8192)
            frame = json.loads(data.decode("utf-8"))
            print(f"[{frame.get('seq')}] ts={frame.get('ts'):.2f} "
                  f"relay1={frame['tags'].get('do.relay1')} "
                  f"pot={frame['tags'].get('ai.pot')} V "
                  f"uptime={frame['tags'].get('sys.uptime')} s")
        except socket.timeout:
            print("Telemetry timeout")
            break

    # 6. Clean shutdown
    tx_sock.close()
    rx_sock.close()

if __name__ == "__main__":
    main()
```

---

## 8. Known Deviations and Implementation Notes

1. **ADC Linear Transformation (`gain` and `transform_offset`):**
   * *Contract Section 8* states ADC values are calculated as `(raw + offset) * scale`.
   * *Code Implementation (`hmi_hwd.py` & `hwd.json`):* Supports additional `gain` (multiplier) and `transform_offset` (volts) configuration fields to accommodate hardware voltage dividers (such as 24V industrial supply rails) directly within the daemon layer.
2. **Watchdog Notifications:**
   * In addition to calling `sd_notify("READY=1")` at startup, the publisher loop emits `sd_notify("WATCHDOG=1")` on every poll iteration, servicing systemd's `WatchdogSec=10` constraint in `hmi-hwd.service`.
