#!/usr/bin/env python3
"""
hmi_hwd.py -- Hardware Abstraction Daemon (Layer 1)
===================================================

Part of the BYOA HMI system for Toradex Verdin i.MX8M Plus.
Implements CONTRACT.md sections 2.1-2.5, 5 (sd_notify), 7 (reliability), 8 (hw notes).

Inputs:  /etc/hmi/hwd.json (or --config PATH) -- tag-to-pin map
         /dev/gpiochipN      -- digital I/O via libgpiod (v1.x or v2.x)
         /sys/bus/iio/        -- analog inputs via IIO sysfs
         /dev/verdin-uartN    -- optional serial link via pyserial
Outputs: UDP telemetry frames on 127.0.0.1:5001 (and dynamic subscribers)
         UDP ack frames to command senders on 127.0.0.1:5000
         sd_notify READY=1 and WATCHDOG=1 to systemd

All errors are caught, counted, rate-limited in logs, and published as sys.errors.
No exception may escape the datagram handler or poll loop.
"""

import argparse
import asyncio
import json
import logging
import os
import pathlib
import re
import signal
import socket
import sys
import time
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum accepted UDP datagram size in bytes (CONTRACT 2).
MAX_DGRAM_BYTES: int = 8192

# Maximum length of an opaque command id string (CONTRACT 2.2).
MAX_ID_LEN: int = 64

# Sequence number wrap point (CONTRACT 2.4).
SEQ_WRAP: int = 2**31

# Minimum pulse width (ms) and maximum pulse width (ms) (CONTRACT 2.2).
PULSE_MIN_MS: int = 1
PULSE_MAX_MS: int = 10000

# Rate-limit window for logging: max 1 line per this many seconds per class.
LOG_RATE_LIMIT_S: float = 5.0

# Tag name validation regex (CONTRACT 2.5).
# Lowercase, dot-separated.  First segment starts with [a-z], subsequent
# segments allow leading digits and underscores per the regex in the contract.
TAG_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9_]+)+$")

# Closed set of error codes (CONTRACT 2.3).
ERR_BAD_JSON = "bad_json"
ERR_NOT_OBJ = "not_an_object"
ERR_TOO_LARGE = "too_large"
ERR_UNKNOWN_CMD = "unknown_cmd"
ERR_UNKNOWN_TAG = "unknown_tag"
ERR_NOT_WRITABLE = "not_writable"
ERR_BAD_VALUE = "bad_value"
ERR_HW_ERROR = "hw_error"
ERR_RATE_LIMITED = "rate_limited"

logger = logging.getLogger("hmi-hwd")

# ---------------------------------------------------------------------------
# sd_notify -- raw AF_UNIX, no libsystemd dependency
# ---------------------------------------------------------------------------

# Cached notification socket, opened on first use and kept for the process
# lifetime. WATCHDOG=1 is sent every poll cycle (10 Hz by default), so opening
# and closing a fresh socket per call churned ~864,000 file descriptors a day
# for no benefit -- the socket is connectionless and the peer address never
# changes.
_notify_sock: Optional[socket.socket] = None


def sd_notify(state: str) -> None:
    """Send a sd_notify datagram to systemd if NOTIFY_SOCKET is set.

    Args:
        state: notification string, e.g. "READY=1" or "WATCHDOG=1".

    Side effects:
        Sends a single datagram to the systemd notification socket, opening
        the cached socket on first use.  Silently does nothing when
        NOTIFY_SOCKET is unset (developer host, non-systemd environment) or on
        any socket error.

    The abstract namespace convention: if the path starts with '@', replace
    it with a NUL byte (Linux abstract socket namespace).
    """
    global _notify_sock

    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\x00" + addr[1:]
    try:
        if _notify_sock is None:
            _notify_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        _notify_sock.sendto(state.encode("utf-8"), addr)
    except OSError:
        # Drop the socket so the next call rebuilds it rather than retrying a
        # descriptor that has gone bad.
        if _notify_sock is not None:
            try:
                _notify_sock.close()
            except OSError:
                pass
            _notify_sock = None

# ---------------------------------------------------------------------------
# Rate-limited logger
# ---------------------------------------------------------------------------

class RateLimitedLogger:
    """Prevents a flooding client from filling the journal.

    Tracks the last-logged wallclock time per error class string. Only emits
    a log line if at least LOG_RATE_LIMIT_S seconds have elapsed since the
    previous emission for that class.
    """

    def __init__(self) -> None:
        # Maps error-class string -> monotonic timestamp of last emission (s).
        self._last: Dict[str, float] = {}

    def warning(self, err_class: str, msg: str, *args: Any) -> None:
        """Log msg at WARNING level if not rate-limited for err_class.

        Args:
            err_class: arbitrary key grouping related errors (e.g. "bad_json").
            msg:       printf-style format string.
            *args:     values interpolated into msg, exactly as logging does it.

        Side effects:
            Writes to the Python logging system at most once per
            LOG_RATE_LIMIT_S seconds per err_class.

        *args exists because every caller in this file passes them. Without it
        each of those ten call sites raised TypeError instead of logging, and
        because they sit before the ack, the caught exception also swallowed
        the CONTRACT 2.3 nack the handler was about to send. The formatting is
        deferred to the logging call so a rate-limited line costs nothing.
        """
        now = time.monotonic()
        prev = self._last.get(err_class, 0.0)
        if now - prev >= LOG_RATE_LIMIT_S:
            logger.warning("[%s] " + msg, err_class, *args)
            self._last[err_class] = now


_rl_log = RateLimitedLogger()

# ---------------------------------------------------------------------------
# GPIO backends -- auto-detected at import time
# ---------------------------------------------------------------------------

# Try to import gpiod and determine which API generation is available.
# On a developer host (or Windows) neither will succeed, so we set both
# flags to False and fall through to SimBackend.
_GPIOD_V1 = False
_GPIOD_V2 = False
_gpiod = None

try:
    import gpiod as _gpiod  # type: ignore[no-redef]
    if hasattr(_gpiod, "request_lines"):
        # v2.x API: module-level request_lines(), LineSettings, etc.
        _GPIOD_V2 = True
    elif hasattr(_gpiod, "Chip"):
        # v1.x API: gpiod.Chip, chip.get_line(), etc.
        _GPIOD_V1 = True
except ImportError:
    _gpiod = None


class GpioBackend:
    """Abstract interface for GPIO backends.

    Concrete subclasses wrap either libgpiod v1.x, v2.x, or a software
    simulation.  All methods document their contracts here; subclasses
    honour them.
    """

    def setup_output(self, offset: int, active_low: bool, initial: int) -> None:
        """Claim a GPIO line as an output.

        Args:
            offset:     line offset within the chip (0-based, board-specific).
            active_low: if True, logical 1 drives the pin electrically low.
            initial:    initial logical value to drive (0 or 1).

        Raises:
            OSError: if the kernel refuses the line request.
        """
        raise NotImplementedError

    def setup_input(self, offset: int, active_low: bool) -> None:
        """Claim a GPIO line as an input.

        Args:
            offset:     line offset within the chip.
            active_low: if True, the logical value is inverted from electrical.

        Raises:
            OSError: if the kernel refuses the line request.
        """
        raise NotImplementedError

    def write(self, offset: int, value: int) -> None:
        """Drive an output line to a logical value.

        Args:
            offset: line offset (must have been set up as an output).
            value:  0 or 1, logical.

        Raises:
            OSError: on kernel I/O error.
        """
        raise NotImplementedError

    def read(self, offset: int) -> int:
        """Read the logical value of an input line.

        Args:
            offset: line offset (must have been set up as an input).

        Returns:
            0 or 1, logical value (after active_low inversion by libgpiod).

        Raises:
            OSError: on kernel I/O error.
        """
        raise NotImplementedError

    def release(self) -> None:
        """Release all claimed GPIO lines.

        Called during clean shutdown.  After this call, no further read/write
        operations are valid.

        Side effects:
            Releases kernel line reservations so other processes can claim them.
        """
        raise NotImplementedError


class GpioV1(GpioBackend):
    """GPIO backend using libgpiod 1.x Python bindings (BSP 6 / libgpiod 1.6.x).

    Opens the chip by path once and keeps individual line objects.
    """

    def __init__(self, chip_path: str, consumer: str) -> None:
        """Open a gpiochip character device.

        Args:
            chip_path: path to the character device, e.g. "/dev/gpiochip3".
            consumer:  consumer label for line requests (shown by gpioinfo).

        Raises:
            OSError: if the chip device cannot be opened.
        """
        self._chip = _gpiod.Chip(chip_path, _gpiod.Chip.OPEN_BY_PATH)
        self._consumer = consumer
        # Maps line offset -> gpiod.Line object.
        self._lines: Dict[int, Any] = {}

    def setup_output(self, offset: int, active_low: bool, initial: int) -> None:
        """See GpioBackend.setup_output."""
        line = self._chip.get_line(offset)
        flags = _gpiod.LINE_REQ_FLAG_ACTIVE_LOW if active_low else 0
        line.request(
            consumer=self._consumer,
            type=_gpiod.LINE_REQ_DIR_OUT,
            flags=flags,
            default_vals=[initial],
        )
        self._lines[offset] = line

    def setup_input(self, offset: int, active_low: bool) -> None:
        """See GpioBackend.setup_input."""
        line = self._chip.get_line(offset)
        flags = _gpiod.LINE_REQ_FLAG_ACTIVE_LOW if active_low else 0
        line.request(
            consumer=self._consumer,
            type=_gpiod.LINE_REQ_DIR_IN,
            flags=flags,
        )
        self._lines[offset] = line

    def write(self, offset: int, value: int) -> None:
        """See GpioBackend.write."""
        self._lines[offset].set_value(value)

    def read(self, offset: int) -> int:
        """See GpioBackend.read."""
        return self._lines[offset].get_value()

    def release(self) -> None:
        """See GpioBackend.release."""
        for line in self._lines.values():
            try:
                line.release()
            except Exception:
                pass
        try:
            self._chip.close()
        except Exception:
            pass
        self._lines.clear()


class GpioV2(GpioBackend):
    """GPIO backend using libgpiod 2.x Python bindings (BSP 7 / libgpiod 2.x).

    Uses gpiod.request_lines() which returns a LineRequest object that
    manages multiple lines in a single kernel request.
    """

    def __init__(self, chip_path: str, consumer: str) -> None:
        """Prepare a v2 backend.

        Args:
            chip_path: path to the character device.
            consumer:  consumer label string.

        Note: actual line requests are deferred to setup_output/setup_input
        because each request_lines() call creates a separate LineRequest.
        """
        self._chip_path = chip_path
        self._consumer = consumer
        # Maps line offset -> gpiod.LineRequest handle.
        self._requests: Dict[int, Any] = {}

    def setup_output(self, offset: int, active_low: bool, initial: int) -> None:
        """See GpioBackend.setup_output."""
        settings = _gpiod.LineSettings(
            direction=_gpiod.line.Direction.OUTPUT,
            active_low=active_low,
            output_value=_gpiod.line.Value(initial),
        )
        req = _gpiod.request_lines(
            self._chip_path,
            consumer=self._consumer,
            config={offset: settings},
        )
        self._requests[offset] = req

    def setup_input(self, offset: int, active_low: bool) -> None:
        """See GpioBackend.setup_input."""
        settings = _gpiod.LineSettings(
            direction=_gpiod.line.Direction.INPUT,
            active_low=active_low,
        )
        req = _gpiod.request_lines(
            self._chip_path,
            consumer=self._consumer,
            config={offset: settings},
        )
        self._requests[offset] = req

    def write(self, offset: int, value: int) -> None:
        """See GpioBackend.write."""
        self._requests[offset].set_value(offset, _gpiod.line.Value(value))

    def read(self, offset: int) -> int:
        """See GpioBackend.read."""
        val = self._requests[offset].get_value(offset)
        return val.value if hasattr(val, "value") else int(val)

    def release(self) -> None:
        """See GpioBackend.release."""
        for req in self._requests.values():
            try:
                req.release()
            except Exception:
                pass
        self._requests.clear()


class GpioSim(GpioBackend):
    """Software simulation of GPIO for developer-host testing.

    Stores output values and returns configurable input values so the daemon
    can run on a machine (including Windows) without any hardware or libgpiod.
    Engages automatically when gpiod is unavailable or the chip node is missing.
    """

    def __init__(self) -> None:
        """Initialise empty line stores."""
        # Maps offset -> current logical value (int 0 or 1).
        self._outputs: Dict[int, int] = {}
        self._inputs: Dict[int, int] = {}

    def setup_output(self, offset: int, active_low: bool, initial: int) -> None:
        """See GpioBackend.setup_output.  Stores the initial value."""
        self._outputs[offset] = initial

    def setup_input(self, offset: int, active_low: bool) -> None:
        """See GpioBackend.setup_input.  Defaults to 0."""
        self._inputs[offset] = 0

    def write(self, offset: int, value: int) -> None:
        """See GpioBackend.write.  Updates the in-memory store."""
        self._outputs[offset] = value

    def read(self, offset: int) -> int:
        """See GpioBackend.read.  Returns the stored value (default 0)."""
        if offset in self._inputs:
            return self._inputs[offset]
        return self._outputs.get(offset, 0)

    def release(self) -> None:
        """See GpioBackend.release.  Clears the stores."""
        self._outputs.clear()
        self._inputs.clear()

# ---------------------------------------------------------------------------
# IIO ADC backend
# ---------------------------------------------------------------------------

class IioAdc:
    """Reads analog channels from the Linux IIO sysfs interface.

    Resolves the IIO device by its 'name' attribute (never by index), then
    opens the *_raw sysfs file once and uses seek(0)+read() on each poll
    (the standard cheap sysfs read pattern).

    Value formula: volts = ((raw + offset) * scale_mv / 1000.0) * gain + transform_offset
    where scale is in mV (IIO convention for voltage channels).
    """

    # Base path for IIO device enumeration.
    IIO_BASE = pathlib.Path("/sys/bus/iio/devices")

    def __init__(self, device_name: str) -> None:
        """Locate the IIO device by name and prepare for channel reads.

        Args:
            device_name: value of the device's 'name' sysfs attribute,
                         e.g. "ads1015".

        Raises:
            FileNotFoundError: if no IIO device with that name exists.
        """
        self._device_path: Optional[pathlib.Path] = None
        self._device_name = device_name
        # Maps tag -> (raw_fd, offset_val, scale_val, gain, transform_offset).
        self._channels: Dict[str, Tuple[Any, float, float, float, float]] = {}
        self._resolve_device()

    def _resolve_device(self) -> None:
        """Walk /sys/bus/iio/devices/ and match the 'name' attribute.

        Raises:
            FileNotFoundError: when no matching device is found.
        """
        if not self.IIO_BASE.is_dir():
            raise FileNotFoundError(
                "IIO sysfs base %s does not exist" % self.IIO_BASE
            )
        for entry in self.IIO_BASE.iterdir():
            name_file = entry / "name"
            if name_file.is_file():
                try:
                    found = name_file.read_text().strip()
                except OSError:
                    continue
                if found == self._device_name:
                    self._device_path = entry
                    logger.info(
                        "IIO device '%s' found at %s",
                        self._device_name,
                        entry,
                    )
                    return
        raise FileNotFoundError(
            "No IIO device named '%s' under %s" % (self._device_name, self.IIO_BASE)
        )

    def add_channel(
        self,
        tag: str,
        channel_file: str,
        offset_file: str,
        scale_file: str,
        gain: float = 1.0,
        transform_offset: float = 0.0,
    ) -> None:
        """Register a channel for periodic polling.

        Args:
            tag:              tag name, e.g. "ai.pot".
            channel_file:     sysfs file for the raw reading, e.g. "in_voltage0_raw".
            offset_file:      sysfs file for the channel offset (may not exist;
                              defaults to 0 if missing).
            scale_file:       sysfs file for the channel scale in mV.
            gain:             optional linear-transform gain applied after
                              IIO conversion.  For a voltage divider with
                              ratio 1:11, set gain=11.0 so the published
                              value is in real volts.
            transform_offset: optional linear-transform offset (volts) added
                              after gain is applied.

        Raises:
            FileNotFoundError: if the raw channel file does not exist.

        Side effects:
            Opens the raw file descriptor and keeps it for the process lifetime.
        """
        assert self._device_path is not None
        raw_path = self._device_path / channel_file
        if not raw_path.is_file():
            raise FileNotFoundError("Channel file %s not found" % raw_path)

        # Read offset (default 0) and scale (must exist) once at init.
        offset_val = 0.0
        offset_path = self._device_path / offset_file
        if offset_path.is_file():
            try:
                offset_val = float(offset_path.read_text().strip())
            except (OSError, ValueError):
                pass

        scale_val = 1.0
        scale_path = self._device_path / scale_file
        if scale_path.is_file():
            try:
                scale_val = float(scale_path.read_text().strip())
            except (OSError, ValueError):
                logger.warning("Cannot read IIO scale for %s, defaulting to 1.0 mV", tag)

        raw_fd = open(raw_path, "r")
        self._channels[tag] = (raw_fd, offset_val, scale_val, gain, transform_offset)
        logger.info(
            "IIO channel %s: offset=%.3f, scale=%.3f mV, gain=%.3f, xform_offset=%.3f",
            tag, offset_val, scale_val, gain, transform_offset,
        )

    def read(self, tag: str) -> Optional[float]:
        """Read a channel and return the value in volts.

        Args:
            tag: tag name previously registered via add_channel().

        Returns:
            Voltage as float, or None if the read failed (fd error / parse).

        Side effects:
            Seeks the file descriptor to 0 and reads.  If the read fails,
            attempts to reopen the file once; if that also fails, returns None.
        """
        entry = self._channels.get(tag)
        if entry is None:
            return None
        raw_fd, offset_val, scale_val, gain, transform_offset = entry
        try:
            raw_fd.seek(0)
            raw_str = raw_fd.read().strip()
            raw = float(raw_str)
        except (OSError, ValueError):
            # Attempt reopen once (e.g. after a device re-enumeration).
            try:
                raw_fd.close()
            except OSError:
                pass
            try:
                raw_fd = open(raw_fd.name, "r")
                self._channels[tag] = (raw_fd, offset_val, scale_val, gain, transform_offset)
                raw_fd.seek(0)
                raw = float(raw_fd.read().strip())
            except (OSError, ValueError):
                return None
        # IIO voltage scale is in mV; convert to V.
        volts = ((raw + offset_val) * scale_val) / 1000.0
        # Apply optional per-tag linear transform for divider-scaled rails.
        volts = volts * gain + transform_offset
        return round(volts, 6)

    def channels(self) -> List[str]:
        """Return the tags registered for polling.

        Returns:
            A list of tag names, safe to iterate while read() reopens a
            channel's file descriptor (it is a copy, not a live view).

        Exists so the poll loop does not have to reach into _channels; the
        simulated backend offers the same method, so the caller needs no
        knowledge of which one it holds.
        """
        return list(self._channels.keys())

    def close(self) -> None:
        """Close all open file descriptors.

        Called during daemon shutdown.
        """
        for tag, (raw_fd, _, _, _, _) in self._channels.items():
            try:
                raw_fd.close()
            except OSError:
                pass
        self._channels.clear()


class IioSim:
    """Simulated IIO ADC for developer-host use.

    Returns deterministic ramp values so the GUI can exercise ADC-bound
    widgets without hardware.
    """

    def __init__(self) -> None:
        # Maps tag -> (gain, transform_offset) for simulation scaling.
        self._channels: Dict[str, Tuple[float, float]] = {}
        # Monotonic counter driving the simulated ramp.
        self._tick: int = 0

    def add_channel(
        self,
        tag: str,
        channel_file: str = "",
        offset_file: str = "",
        scale_file: str = "",
        gain: float = 1.0,
        transform_offset: float = 0.0,
    ) -> None:
        """Register a simulated channel.  See IioAdc.add_channel for args."""
        self._channels[tag] = (gain, transform_offset)

    def read(self, tag: str) -> Optional[float]:
        """Return a simulated voltage that ramps 0-3.3 V.

        The simulated raw ramps through 0-4095 (12-bit), with a fixed
        scale of ~0.805 mV/LSB (3.3 V / 4096).
        """
        if tag not in self._channels:
            return None
        gain, transform_offset = self._channels[tag]
        self._tick = (self._tick + 1) % 4096
        raw = self._tick
        volts = (raw * 0.8056640625) / 1000.0
        volts = volts * gain + transform_offset
        return round(volts, 6)

    def channels(self) -> List[str]:
        """Return the tags registered for polling.  See IioAdc.channels."""
        return list(self._channels.keys())

    def close(self) -> None:
        """No-op for simulation."""
        self._channels.clear()

# ---------------------------------------------------------------------------
# UART link (optional, pyserial)
# ---------------------------------------------------------------------------

class UartLink:
    """Optional serial link using pyserial in a background thread.

    Feeds two tags:
        uart.rx   -- cumulative count of received lines (int)
        uart.last -- last received line, stripped (str)

    If pyserial is not installed or the port does not exist, the feature
    disables itself with a warning; it never crashes the daemon.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
        timeout_s: float = 0.1,
    ) -> None:
        """Open the serial port and start the reader thread.

        Args:
            port:      device path, e.g. "/dev/verdin-uart3".
            baudrate:  baud rate (default 115200).
            bytesize:  data bits (5-8, default 8).
            parity:    "N", "E", "O" (default "N").
            stopbits:  1 or 2 (default 1).
            timeout_s: read timeout in seconds (default 0.1).

        Raises:
            ImportError: if pyserial is not installed (caller catches).
            serial.SerialException: if the port cannot be opened.
        """
        import serial  # type: ignore[import-untyped]
        self._serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=timeout_s,
        )
        # Cumulative count of received lines.
        self.rx_count: int = 0
        # Last received line (stripped of trailing whitespace).
        self.last_line: str = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._reader_loop, name="uart-reader", daemon=True
        )
        self._thread.start()
        logger.info("UART link opened on %s @ %d baud", port, baudrate)

    def _reader_loop(self) -> None:
        """Background thread: read lines from the serial port.

        Runs until _stop is set.  Each decoded line increments rx_count
        and overwrites last_line.  Decode errors are replaced with U+FFFD.
        """
        while not self._stop.is_set():
            try:
                raw = self._serial.readline()
                if raw:
                    self.last_line = raw.decode("utf-8", errors="replace").strip()
                    self.rx_count += 1
            except Exception:
                if not self._stop.is_set():
                    _rl_log.warning("uart_read", "UART read error")
                time.sleep(0.1)

    def transmit(self, data: str) -> bool:
        """Write a string to the serial port.

        Args:
            data: the string to transmit (may include \\r\\n).

        Returns:
            True on success, False on any I/O error.
        """
        try:
            self._serial.write(data.encode("utf-8"))
            return True
        except Exception:
            _rl_log.warning("uart_write", "UART write error")
            return False

    def close(self) -> None:
        """Stop the reader thread and close the serial port.

        Side effects:
            Joins the reader thread (with a 1-second timeout) and closes the
            underlying serial file descriptor.
        """
        self._stop.set()
        self._thread.join(timeout=1.0)
        try:
            self._serial.close()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Tag store
# ---------------------------------------------------------------------------

class TagStore:
    """Central store for all tag values.

    Tags are registered at startup and never added/removed at runtime.
    Values are typed: bool for di.*/do.*, float or None for ai.*, int/str
    for sys.* and uart.*.
    """

    def __init__(self) -> None:
        # Maps tag name -> current value (bool, float, int, str, or None).
        self._tags: Dict[str, Any] = {}
        # Set of writable tags (do.* outputs and uart.tx).
        self._writable: Set[str] = set()
        # Set of all tags for the list command.
        self._all_tags: Set[str] = set()

    def register(self, tag: str, initial: Any, writable: bool = False) -> None:
        """Register a tag with its initial value.

        Args:
            tag:      dotted tag name conforming to TAG_RE.
            initial:  initial value (type determines the tag's type).
            writable: if True, the tag accepts 'set' commands.
        """
        self._tags[tag] = initial
        self._all_tags.add(tag)
        if writable:
            self._writable.add(tag)

    def get(self, tag: str) -> Any:
        """Return the current value of a tag, or KeyError if not registered."""
        return self._tags[tag]

    def set(self, tag: str, value: Any) -> None:
        """Update a tag's value.

        Args:
            tag:   registered tag name.
            value: new value (caller ensures type compatibility).
        """
        self._tags[tag] = value

    def is_writable(self, tag: str) -> bool:
        """Return True if the tag accepts set/pulse commands."""
        return tag in self._writable

    def exists(self, tag: str) -> bool:
        """Return True if the tag is registered."""
        return tag in self._all_tags

    def snapshot(self) -> Dict[str, Any]:
        """Return a shallow copy of all tag values for telemetry."""
        return dict(self._tags)

    def tag_list(self) -> List[str]:
        """Return a sorted list of all tag names for the 'list' command."""
        return sorted(self._all_tags)

# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Load and validate the hwd.json configuration file.

    Args:
        path: filesystem path to the JSON config file.

    Returns:
        Parsed configuration dict with top-level keys: daemon, gpio, adc, uart.

    Raises:
        SystemExit: on missing file, invalid JSON, or missing required keys.

    Validates that every tag name in the config passes TAG_RE.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        logger.error("Config file not found: %s", path)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in config %s: %s", path, exc)
        sys.exit(1)

    required_sections = ("daemon", "gpio")
    for sec in required_sections:
        if sec not in cfg:
            logger.error("Config missing required section '%s'", sec)
            sys.exit(1)

    # Validate the daemon section's numeric fields before anything consumes
    # them. A poll_interval_ms of 0 turns the publisher into a busy loop that
    # saturates a core and floods every subscriber; a malformed
    # telemetry_sink used to raise ValueError out of __init__ as a traceback
    # rather than a diagnosable message.
    dcfg = cfg["daemon"]

    poll_ms = dcfg.get("poll_interval_ms", 100)
    if not isinstance(poll_ms, (int, float)) or poll_ms <= 0:
        logger.error(
            "daemon.poll_interval_ms must be a positive number, got %r", poll_ms
        )
        sys.exit(1)

    cmd_port = dcfg.get("cmd_port", 5000)
    if not isinstance(cmd_port, int) or not (1 <= cmd_port <= 65535):
        logger.error("daemon.cmd_port must be 1..65535, got %r", cmd_port)
        sys.exit(1)

    sink = dcfg.get("telemetry_sink", "127.0.0.1:5001")
    if not isinstance(sink, str) or ":" not in sink:
        logger.error(
            "daemon.telemetry_sink must be 'host:port', got %r", sink
        )
        sys.exit(1)
    sink_port = sink.rsplit(":", 1)[1]
    if not sink_port.isdigit() or not (1 <= int(sink_port) <= 65535):
        logger.error(
            "daemon.telemetry_sink port must be 1..65535, got %r", sink_port
        )
        sys.exit(1)

    # Validate tag names in gpio outputs and inputs, and adc channels.
    for section_key in ("outputs", "inputs"):
        section = cfg.get("gpio", {}).get(section_key, {})
        for tag in section:
            if not TAG_RE.match(tag):
                logger.error("Invalid tag name '%s' in gpio.%s", tag, section_key)
                sys.exit(1)

    if "adc" in cfg:
        for tag in cfg["adc"].get("channels", {}):
            if not TAG_RE.match(tag):
                logger.error("Invalid tag name '%s' in adc.channels", tag)
                sys.exit(1)

    return cfg

# ---------------------------------------------------------------------------
# Subscriber registry
# ---------------------------------------------------------------------------

class SubscriberRegistry:
    """Manages dynamic telemetry subscribers with TTL-based expiry.

    Each subscriber is identified by its (host, port) address.  The static
    sink (from config) is always included and never expires.
    """

    def __init__(self, static_sink: Tuple[str, int], default_ttl: float = 5.0) -> None:
        """Initialise with the static telemetry sink.

        Args:
            static_sink:  (host, port) that always receives telemetry.
            default_ttl:  default time-to-live for dynamic subscribers (seconds).
        """
        self._static_sink = static_sink
        self._default_ttl = default_ttl
        # Maps (host, port) -> expiry monotonic timestamp.
        self._dynamic: Dict[Tuple[str, int], float] = {}

    def subscribe(self, addr: Tuple[str, int], ttl: Optional[float] = None) -> None:
        """Register or refresh a dynamic subscriber.

        Args:
            addr: (host, port) of the subscriber.
            ttl:  time-to-live in seconds; uses default if None.
        """
        t = ttl if ttl is not None else self._default_ttl
        self._dynamic[addr] = time.monotonic() + t

    def unsubscribe(self, addr: Tuple[str, int]) -> None:
        """Remove a dynamic subscriber immediately.

        Args:
            addr: (host, port) to remove.
        """
        self._dynamic.pop(addr, None)

    def get_targets(self) -> List[Tuple[str, int]]:
        """Return all active subscriber addresses, including the static sink.

        Side effects:
            Prunes expired subscribers (silent expiry per CONTRACT).

        Returns:
            List of (host, port) tuples.
        """
        now = time.monotonic()
        # Prune expired entries.
        expired = [a for a, exp in self._dynamic.items() if now >= exp]
        for a in expired:
            del self._dynamic[a]
        targets = [self._static_sink]
        for addr in self._dynamic:
            if addr != self._static_sink:
                targets.append(addr)
        return targets

# ---------------------------------------------------------------------------
# Asyncio UDP command protocol
# ---------------------------------------------------------------------------

class CommandProtocol(asyncio.DatagramProtocol):
    """Handles incoming UDP commands on the daemon's command port.

    Implements CONTRACT section 2.2 (commands) and 2.3 (acks).
    Every code path is wrapped in try/except so no exception can escape
    the datagram handler (CONTRACT section 7).

    Args (constructor):
        daemon: reference to the HwDaemon instance for dispatching commands.
    """

    def __init__(self, daemon: "HwDaemon") -> None:
        self._daemon = daemon
        self._transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        """Called by asyncio when the socket is ready."""
        self._transport = transport

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Process one incoming datagram.

        Args:
            data: raw bytes from the network.
            addr: (host, port) of the sender.

        Side effects:
            May modify tag values, subscribe/unsubscribe callers, or
            transmit UART data.  Sends an ack datagram when the command
            contains an 'id' field (or for ping/list).

        Error handling:
            Oversized, non-UTF-8, non-JSON, non-object datagrams are
            counted, rate-limited logged, and answered with ack{ok:false}
            when an id can be extracted.
        """
        try:
            self._handle(data, addr)
        except Exception:
            # Absolute last-resort catch.  Should never fire because
            # _handle() has its own try/except, but the contract says
            # "no exception may escape the datagram handler".
            self._daemon.error_count += 1
            _rl_log.warning("internal", "Unhandled exception in datagram handler")

    def _handle(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Inner dispatch, separated for clarity.  All exceptions are caught."""
        # -- Size check (CONTRACT: >8192 B dropped + counted) --
        if len(data) > MAX_DGRAM_BYTES:
            self._daemon.error_count += 1
            _rl_log.warning(
                ERR_TOO_LARGE, "Oversized datagram (%d B) from %s", len(data), addr
            )
            # Cannot reliably parse an id from an oversized payload.
            # Try anyway for best-effort ack.
            msg_id = self._extract_id_best_effort(data)
            if msg_id:
                self._send_nack(msg_id, ERR_TOO_LARGE, addr)
            return

        # -- UTF-8 decode --
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            self._daemon.error_count += 1
            _rl_log.warning(ERR_BAD_JSON, "Non-UTF-8 datagram from %s", addr)
            return

        # -- JSON parse --
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            self._daemon.error_count += 1
            _rl_log.warning(ERR_BAD_JSON, "Malformed JSON from %s", addr)
            msg_id = self._extract_id_regex(text)
            if msg_id:
                self._send_nack(msg_id, ERR_BAD_JSON, addr)
            return

        # -- Must be a JSON object --
        # A well-formed array or scalar has no addressable "id" member, so the
        # regex extractor is the only way to correlate a reply. Without this
        # branch the not_an_object code in the CONTRACT 2.3 closed set was
        # unreachable: the daemon simply went silent and the sender learned
        # nothing about why its command was ignored.
        if not isinstance(msg, dict):
            self._daemon.error_count += 1
            _rl_log.warning(ERR_NOT_OBJ, "Non-object JSON from %s", addr)
            msg_id = self._extract_id_regex(text)
            if msg_id:
                self._send_nack(msg_id, ERR_NOT_OBJ, addr)
            return

        # -- Extract optional id (max 64 chars, must be string) --
        msg_id = msg.get("id")
        if msg_id is not None:
            if not isinstance(msg_id, str) or len(msg_id) > MAX_ID_LEN:
                msg_id = None

        cmd = msg.get("cmd")
        if not isinstance(cmd, str):
            self._daemon.error_count += 1
            _rl_log.warning(ERR_UNKNOWN_CMD, "Missing or non-string 'cmd' from %s", addr)
            if msg_id:
                self._send_nack(msg_id, ERR_UNKNOWN_CMD, addr)
            return

        # -- Dispatch --
        if cmd == "set":
            self._cmd_set(msg, msg_id, addr)
        elif cmd == "pulse":
            self._cmd_pulse(msg, msg_id, addr)
        elif cmd == "uart_tx":
            self._cmd_uart_tx(msg, msg_id, addr)
        elif cmd == "subscribe":
            self._cmd_subscribe(msg, msg_id, addr)
        elif cmd == "unsubscribe":
            self._cmd_unsubscribe(msg, msg_id, addr)
        elif cmd == "list":
            self._cmd_list(msg_id, addr)
        elif cmd == "ping":
            self._cmd_ping(msg_id, addr)
        else:
            self._daemon.error_count += 1
            _rl_log.warning(ERR_UNKNOWN_CMD, "Unknown command '%s' from %s", cmd, addr)
            if msg_id:
                self._send_nack(msg_id, ERR_UNKNOWN_CMD, addr)

    # -- Command handlers --

    def _cmd_set(self, msg: dict, msg_id: Optional[str], addr: Tuple[str, int]) -> None:
        """Handle the 'set' command: drive an output tag to a value.

        Validates the tag exists, is writable, and value is 0/1/true/false.
        """
        tag = msg.get("tag")
        if not isinstance(tag, str) or not self._daemon.tags.exists(tag):
            self._daemon.error_count += 1
            if msg_id:
                self._send_nack(msg_id, ERR_UNKNOWN_TAG, addr)
            return
        if not self._daemon.tags.is_writable(tag):
            self._daemon.error_count += 1
            if msg_id:
                self._send_nack(msg_id, ERR_NOT_WRITABLE, addr)
            return
        value = msg.get("value")
        if value not in (0, 1, True, False):
            self._daemon.error_count += 1
            if msg_id:
                self._send_nack(msg_id, ERR_BAD_VALUE, addr)
            return
        int_val = int(bool(value))
        try:
            self._daemon.gpio_write(tag, int_val)
            if msg_id:
                self._send_ack(msg_id, addr)
        except Exception:
            self._daemon.error_count += 1
            _rl_log.warning(ERR_HW_ERROR, "GPIO write error for %s", tag)
            if msg_id:
                self._send_nack(msg_id, ERR_HW_ERROR, addr)

    def _cmd_pulse(self, msg: dict, msg_id: Optional[str], addr: Tuple[str, int]) -> None:
        """Handle the 'pulse' command: drive output high for N ms then low.

        Validates the tag and pulse width (1..10000 ms).
        """
        tag = msg.get("tag")
        if not isinstance(tag, str) or not self._daemon.tags.exists(tag):
            self._daemon.error_count += 1
            if msg_id:
                self._send_nack(msg_id, ERR_UNKNOWN_TAG, addr)
            return
        if not self._daemon.tags.is_writable(tag):
            self._daemon.error_count += 1
            if msg_id:
                self._send_nack(msg_id, ERR_NOT_WRITABLE, addr)
            return
        ms = msg.get("ms")
        if not isinstance(ms, (int, float)) or ms < PULSE_MIN_MS or ms > PULSE_MAX_MS:
            self._daemon.error_count += 1
            if msg_id:
                self._send_nack(msg_id, ERR_BAD_VALUE, addr)
            return
        try:
            self._daemon.gpio_write(tag, 1)
            # Schedule the off-transition.  Using call_later keeps it
            # non-blocking (no thread, no sleep).
            loop = asyncio.get_running_loop()
            loop.call_later(ms / 1000.0, self._daemon.gpio_write_safe, tag, 0)
            if msg_id:
                self._send_ack(msg_id, addr)
        except Exception:
            self._daemon.error_count += 1
            _rl_log.warning(ERR_HW_ERROR, "GPIO pulse error for %s", tag)
            if msg_id:
                self._send_nack(msg_id, ERR_HW_ERROR, addr)

    def _cmd_uart_tx(self, msg: dict, msg_id: Optional[str], addr: Tuple[str, int]) -> None:
        """Handle the 'uart_tx' command: transmit data on the serial port."""
        if self._daemon.uart is None:
            self._daemon.error_count += 1
            if msg_id:
                self._send_nack(msg_id, ERR_HW_ERROR, addr)
            return
        data = msg.get("data")
        if not isinstance(data, str):
            self._daemon.error_count += 1
            if msg_id:
                self._send_nack(msg_id, ERR_BAD_VALUE, addr)
            return
        ok = self._daemon.uart.transmit(data)
        if msg_id:
            if ok:
                self._send_ack(msg_id, addr)
            else:
                self._daemon.error_count += 1
                self._send_nack(msg_id, ERR_HW_ERROR, addr)

    def _cmd_subscribe(self, msg: dict, msg_id: Optional[str], addr: Tuple[str, int]) -> None:
        """Handle the 'subscribe' command: register sender as telemetry sink."""
        ttl = msg.get("ttl")
        if ttl is not None and (not isinstance(ttl, (int, float)) or ttl <= 0):
            ttl = None
        self._daemon.subscribers.subscribe(addr, ttl)
        if msg_id:
            self._send_ack(msg_id, addr)

    def _cmd_unsubscribe(self, msg: dict, msg_id: Optional[str], addr: Tuple[str, int]) -> None:
        """Handle the 'unsubscribe' command: remove sender from dynamic sinks."""
        self._daemon.subscribers.unsubscribe(addr)
        if msg_id:
            self._send_ack(msg_id, addr)

    def _cmd_list(self, msg_id: Optional[str], addr: Tuple[str, int]) -> None:
        """Handle the 'list' command: return the tag catalogue.

        Always sends a response (CONTRACT 2.3: ping/list always get a reply).
        """
        reply: Dict[str, Any] = {
            "t": "ack",
            "ok": True,
            "tags": self._daemon.tags.tag_list(),
        }
        if msg_id:
            reply["id"] = msg_id
        self._send_raw(reply, addr)

    def _cmd_ping(self, msg_id: Optional[str], addr: Tuple[str, int]) -> None:
        """Handle the 'ping' command.

        Always sends a response (CONTRACT 2.3).
        """
        reply: Dict[str, Any] = {"t": "ack", "ok": True}
        if msg_id:
            reply["id"] = msg_id
        self._send_raw(reply, addr)

    # -- Ack/nack helpers --

    def _send_ack(self, msg_id: str, addr: Tuple[str, int]) -> None:
        """Send a positive acknowledgement."""
        self._send_raw({"t": "ack", "id": msg_id, "ok": True}, addr)

    def _send_nack(self, msg_id: str, err: str, addr: Tuple[str, int]) -> None:
        """Send a negative acknowledgement with an error code."""
        self._send_raw({"t": "ack", "id": msg_id, "ok": False, "err": err}, addr)

    def _send_raw(self, obj: dict, addr: Tuple[str, int]) -> None:
        """Serialize and send a JSON object as a UDP datagram.

        Args:
            obj:  dictionary to JSON-encode.
            addr: destination (host, port).

        Side effects:
            Writes to the UDP transport.  Silently drops if the transport
            is not available.
        """
        if self._transport is None:
            return
        try:
            payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
            self._transport.sendto(payload, addr)
        except Exception:
            pass

    @staticmethod
    def _extract_id_best_effort(data: bytes) -> Optional[str]:
        """Try to extract an 'id' from an oversized/corrupt datagram.

        Uses a regex on the first 512 bytes (enough to find a near-beginning id).
        Returns None if nothing usable is found.
        """
        try:
            head = data[:512].decode("utf-8", errors="replace")
            return CommandProtocol._extract_id_regex(head)
        except Exception:
            return None

    @staticmethod
    def _extract_id_regex(text: str) -> Optional[str]:
        """Try to extract an 'id' value from a JSON-like string via regex.

        This is a best-effort fallback for malformed JSON.
        """
        m = re.search(r'"id"\s*:\s*"([^"]{1,64})"', text)
        return m.group(1) if m else None

    def error_received(self, exc: Exception) -> None:
        """Called by asyncio when a previous send raised an ICMP error.

        Args:
            exc: the OSError asyncio recovered from the socket.

        An ICMP port-unreachable is the normal consequence of acking a client
        that has already exited; it says nothing about the daemon's health, so
        it is counted for diagnostics and rate-limited rather than logged per
        occurrence.  The method name matters: asyncio calls `error_received`,
        and the previous spelling (`error_datagram_received`) was never
        invoked by anything.
        """
        self._daemon.error_count += 1
        _rl_log.warning("icmp", "ICMP error on command socket: %s", exc)

# ---------------------------------------------------------------------------
# Main daemon
# ---------------------------------------------------------------------------

class HwDaemon:
    """The Hardware Abstraction Daemon -- Layer 1 of the BYOA HMI system.

    Owns the GPIO, ADC, and UART hardware (or their simulations), polls
    inputs at the configured interval, publishes telemetry frames, and
    serves commands over UDP.
    """

    def __init__(self, cfg: dict, force_sim: bool = False, strict: bool = False) -> None:
        """Initialise the daemon from a parsed configuration.

        Args:
            cfg:       parsed hwd.json dict.
            force_sim: if True, use simulation backends regardless of hardware.
            strict:    if True, exit non-zero instead of falling back to sim.

        Side effects:
            Opens GPIO character devices, IIO sysfs files, and optionally the
            serial port.  Registers signal handlers for SIGTERM and SIGINT.
        """
        self.cfg = cfg
        self.tags = TagStore()
        self.error_count: int = 0
        # Monotonic sequence number for telemetry frames, wraps at 2^31.
        self._seq: int = 0
        # Wallclock at daemon start for sys.uptime calculation.
        self._start_mono: float = time.monotonic()

        # -- Parse daemon section --
        dcfg = cfg["daemon"]
        # Poll interval in seconds (converted from ms in config).
        self._poll_s: float = dcfg.get("poll_interval_ms", 100) / 1000.0
        self._cmd_port: int = dcfg.get("cmd_port", 5000)
        sink_str: str = dcfg.get("telemetry_sink", "127.0.0.1:5001")
        host, port_s = sink_str.rsplit(":", 1)
        self._static_sink: Tuple[str, int] = (host, int(port_s))
        sub_ttl: float = dcfg.get("subscriber_ttl_s", 5.0)

        self.subscribers = SubscriberRegistry(self._static_sink, sub_ttl)

        # -- GPIO init --
        # Maps tag -> offset for fast lookup during poll/write.
        self._output_map: Dict[str, int] = {}
        self._input_map: Dict[str, int] = {}
        # Maps offset -> tag for reverse lookup.
        self._offset_to_output_tag: Dict[int, str] = {}
        # Maps tag -> safe_state value (int 0 or 1) for shutdown.
        self._safe_states: Dict[str, int] = {}

        self.gpio: GpioBackend = self._init_gpio(cfg["gpio"], force_sim, strict)

        # -- ADC init --
        self.adc: Any = self._init_adc(cfg.get("adc"), force_sim)

        # -- UART init --
        self.uart: Optional[UartLink] = self._init_uart(cfg.get("uart"), force_sim)

        # -- System tags --
        self.tags.register("sys.uptime", 0.0)
        self.tags.register("sys.errors", 0)

        # UART tags (always registered so the tag map is stable).
        self.tags.register("uart.rx", 0)
        self.tags.register("uart.last", "")

        # -- Command protocol and transport (set during run) --
        self._cmd_protocol: Optional[CommandProtocol] = None
        self._transport: Optional[asyncio.DatagramTransport] = None

    def _init_gpio(
        self, gpio_cfg: dict, force_sim: bool, strict: bool
    ) -> GpioBackend:
        """Create and configure the GPIO backend.

        Tries real hardware first (v2 then v1); falls back to sim unless
        --strict was given.

        Args:
            gpio_cfg:  the "gpio" section of hwd.json.
            force_sim: skip hardware entirely.
            strict:    exit non-zero if hardware is unavailable.

        Returns:
            Configured GpioBackend subclass.
        """
        chip_path: str = gpio_cfg.get("chip", "/dev/gpiochip0")
        consumer: str = gpio_cfg.get("consumer", "hmi-hwd")

        backend: Optional[GpioBackend] = None

        if not force_sim:
            if _gpiod is None:
                if strict:
                    logger.error("gpiod module not available and --strict is set")
                    sys.exit(1)
                logger.warning(
                    "gpiod module not available; engaging SimBackend. "
                    "Install python3-libgpiod on the target."
                )
            elif not os.path.exists(chip_path):
                if strict:
                    logger.error("GPIO chip %s not found and --strict is set", chip_path)
                    sys.exit(1)
                logger.warning(
                    "GPIO chip %s not found; engaging SimBackend. "
                    "Running on developer host.",
                    chip_path,
                )
            else:
                try:
                    if _GPIOD_V2:
                        backend = GpioV2(chip_path, consumer)
                        logger.info("Using libgpiod v2.x backend")
                    elif _GPIOD_V1:
                        backend = GpioV1(chip_path, consumer)
                        logger.info("Using libgpiod v1.x backend")
                except OSError as exc:
                    if strict:
                        logger.error("GPIO init failed: %s", exc)
                        sys.exit(1)
                    logger.warning("GPIO init failed (%s); engaging SimBackend", exc)

        if backend is None:
            backend = GpioSim()
            if not force_sim:
                # Warning already logged above for the specific reason.
                pass
            else:
                logger.warning(
                    "Simulation mode (--sim): GPIO operations are simulated"
                )

        # Configure outputs.
        for tag, ocfg in gpio_cfg.get("outputs", {}).items():
            offset: int = ocfg["offset"]
            active_low: bool = ocfg.get("active_low", False)
            safe_state: int = ocfg.get("safe_state", 0)
            try:
                backend.setup_output(offset, active_low, safe_state)
            except OSError as exc:
                logger.error("Cannot claim output %s (offset %d): %s", tag, offset, exc)
                if strict:
                    sys.exit(1)
            self._output_map[tag] = offset
            self._offset_to_output_tag[offset] = tag
            self._safe_states[tag] = safe_state
            self.tags.register(tag, bool(safe_state), writable=True)

        # Configure inputs.
        for tag, icfg in gpio_cfg.get("inputs", {}).items():
            offset = icfg["offset"]
            active_low = icfg.get("active_low", False)
            try:
                backend.setup_input(offset, active_low)
            except OSError as exc:
                logger.error("Cannot claim input %s (offset %d): %s", tag, offset, exc)
                if strict:
                    sys.exit(1)
            self._input_map[tag] = offset
            self.tags.register(tag, False)

        return backend

    def _init_adc(self, adc_cfg: Optional[dict], force_sim: bool) -> Any:
        """Create and configure the ADC backend.

        Falls back to IioSim if the IIO device is not found or we are in sim mode.

        Args:
            adc_cfg:   the "adc" section of hwd.json, or None.
            force_sim: skip hardware entirely.

        Returns:
            IioAdc or IioSim instance.
        """
        if adc_cfg is None:
            return IioSim()

        device_name: str = adc_cfg.get("iio_device_name", "")
        channels: dict = adc_cfg.get("channels", {})
        adc: Any = None

        if not force_sim:
            try:
                adc = IioAdc(device_name)
            except FileNotFoundError as exc:
                logger.warning("IIO ADC not available (%s); using simulated ADC", exc)

        if adc is None:
            adc = IioSim()

        for tag, ch_cfg in channels.items():
            try:
                adc.add_channel(
                    tag,
                    channel_file=ch_cfg.get("channel_file", ""),
                    offset_file=ch_cfg.get("offset_file", ""),
                    scale_file=ch_cfg.get("scale_file", ""),
                    gain=ch_cfg.get("gain", 1.0),
                    transform_offset=ch_cfg.get("transform_offset", 0.0),
                )
            except FileNotFoundError as exc:
                logger.warning("ADC channel %s unavailable: %s", tag, exc)
            # Register the tag regardless (publish None on read failure).
            self.tags.register(tag, None)

        return adc

    def _init_uart(self, uart_cfg: Optional[dict], force_sim: bool) -> Optional[UartLink]:
        """Open the optional UART link.

        Returns None (with a warning) if pyserial is not installed, the port
        does not exist, or we are in sim mode.

        Args:
            uart_cfg:  the "uart" section of hwd.json, or None.
            force_sim: skip hardware.

        Returns:
            UartLink instance, or None.
        """
        if uart_cfg is None or force_sim:
            if uart_cfg is not None and force_sim:
                logger.info("UART disabled in simulation mode")
            return None

        port = uart_cfg.get("port", "")
        try:
            return UartLink(
                port=port,
                baudrate=uart_cfg.get("baudrate", 115200),
                bytesize=uart_cfg.get("bytesize", 8),
                parity=uart_cfg.get("parity", "N"),
                stopbits=uart_cfg.get("stopbits", 1),
                timeout_s=uart_cfg.get("timeout_s", 0.1),
            )
        except ImportError:
            logger.warning(
                "pyserial not installed; UART feature disabled. "
                "Install with: pip install pyserial"
            )
            return None
        except Exception as exc:
            logger.warning("UART port %s unavailable (%s); feature disabled", port, exc)
            return None

    def gpio_write(self, tag: str, value: int) -> None:
        """Write a logical value to a GPIO output and update the tag store.

        Args:
            tag:   output tag name (must be in _output_map).
            value: 0 or 1, logical.

        Raises:
            OSError: on hardware I/O error (caller is responsible for counting).

        Side effects:
            Drives the physical GPIO line and updates the tag store.
        """
        offset = self._output_map[tag]
        self.gpio.write(offset, value)
        self.tags.set(tag, bool(value))

    def gpio_write_safe(self, tag: str, value: int) -> None:
        """gpio_write wrapped in try/except for use as a call_later callback.

        Errors are counted and rate-limited logged but never propagated,
        because call_later callbacks must not raise.
        """
        try:
            self.gpio_write(tag, value)
        except Exception:
            self.error_count += 1
            _rl_log.warning(ERR_HW_ERROR, "GPIO write error (deferred) for %s", tag)

    def _poll_inputs(self) -> None:
        """Read all GPIO inputs and ADC channels, update the tag store.

        Called once per poll cycle.  Errors degrade the tag to None (for ADC)
        or to the last known value (for GPIO), and increment the error counter.
        """
        # GPIO inputs.
        for tag, offset in self._input_map.items():
            try:
                val = self.gpio.read(offset)
                self.tags.set(tag, bool(val))
            except Exception:
                self.error_count += 1
                _rl_log.warning(ERR_HW_ERROR, "GPIO read error for %s", tag)
                # Tag retains its previous value (better than None for a bool).

        # ADC channels.  A failed read publishes None (CONTRACT 2.4) and is
        # counted, exactly as a failed GPIO read is: sys.errors is documented
        # as a cumulative hardware error count, so a channel that is failing
        # every cycle must be visible there rather than only in the journal.
        if self.adc is not None:
            for tag in self.adc.channels():
                val = self.adc.read(tag)
                if val is None:
                    self.error_count += 1
                    _rl_log.warning(ERR_HW_ERROR, "ADC read error for %s", tag)
                self.tags.set(tag, val)

        # UART tags.
        if self.uart is not None:
            self.tags.set("uart.rx", self.uart.rx_count)
            self.tags.set("uart.last", self.uart.last_line)

        # System tags.
        self.tags.set("sys.uptime", round(time.monotonic() - self._start_mono, 3))
        self.tags.set("sys.errors", self.error_count)

    def _build_telemetry_frame(self) -> bytes:
        """Build a single telemetry JSON frame per CONTRACT 2.4.

        Returns:
            UTF-8 encoded JSON bytes.
        """
        frame = {
            "t": "tags",
            "seq": self._seq,
            "ts": time.time(),
            "src": "hmi-hwd",
            "tags": self.tags.snapshot(),
        }
        self._seq = (self._seq + 1) % SEQ_WRAP
        return json.dumps(frame, separators=(",", ":")).encode("utf-8")

    def _safe_shutdown(self) -> None:
        """Drive all outputs to their configured safe states, release resources.

        Called on SIGTERM/SIGINT.  Errors are logged but never raised.

        Side effects:
            Drives GPIO outputs, releases GPIO lines, closes ADC fds and the
            UART port.
        """
        logger.info("Driving outputs to safe states and releasing resources")
        for tag, safe_val in self._safe_states.items():
            try:
                self.gpio_write(tag, safe_val)
            except Exception:
                logger.warning("Failed to set safe state for %s", tag)
        self.gpio.release()
        if self.adc is not None:
            self.adc.close()
        if self.uart is not None:
            self.uart.close()

    async def _publisher(self, send_sock: socket.socket) -> None:
        """Async task: poll inputs and publish telemetry at the configured rate.

        Args:
            send_sock: UDP socket used to send telemetry datagrams.

        Side effects:
            Reads all hardware, builds a frame, sends it to all subscribers.
            Sends WATCHDOG=1 to systemd each cycle.

        This task runs until cancelled.  It catches all exceptions internally
        to satisfy CONTRACT section 7.
        """
        while True:
            try:
                self._poll_inputs()
                frame = self._build_telemetry_frame()
                targets = self.subscribers.get_targets()
                for addr in targets:
                    try:
                        send_sock.sendto(frame, addr)
                    except OSError:
                        pass
                sd_notify("WATCHDOG=1")
            except Exception:
                self.error_count += 1
                _rl_log.warning("poll", "Error in poll/publish cycle")
            await asyncio.sleep(self._poll_s)

    async def run(self, selftest: bool = False) -> int:
        """Main entry point: bind the command socket, start the publisher.

        Args:
            selftest: if True, poll once, print one telemetry frame to stdout,
                      shut down cleanly, and return 0.

        Returns:
            Exit code (0 on success, non-zero on error).
        """
        loop = asyncio.get_running_loop()

        # Create the UDP command socket.
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: CommandProtocol(self),
            local_addr=("127.0.0.1", self._cmd_port),
        )
        self._cmd_protocol = protocol
        self._transport = transport

        # Sending socket for telemetry (separate from the command socket
        # to avoid port conflicts).
        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        if selftest:
            self._poll_inputs()
            frame_bytes = self._build_telemetry_frame()
            sys.stdout.write(frame_bytes.decode("utf-8") + "\n")
            sys.stdout.flush()
            transport.close()
            send_sock.close()
            self._safe_shutdown()
            return 0

        # Signal handling (Unix; on Windows SIGTERM is not available,
        # but SIGINT is -- sufficient for developer use).
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            """Set the stop event so the main loop exits cleanly."""
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows does not support add_signal_handler for SIGTERM.
                # Fall back to signal.signal for SIGINT.
                pass

        # On Windows, use signal.signal as a fallback for SIGINT.
        if sys.platform == "win32":
            def _win_handler(signum: int, frame: Any) -> None:
                stop_event.set()
            signal.signal(signal.SIGINT, _win_handler)

        sd_notify("READY=1")
        logger.info(
            "Hardware daemon ready -- cmd=127.0.0.1:%d, sink=%s:%d, poll=%dms",
            self._cmd_port,
            self._static_sink[0],
            self._static_sink[1],
            int(self._poll_s * 1000),
        )

        pub_task = asyncio.ensure_future(self._publisher(send_sock))

        await stop_event.wait()

        pub_task.cancel()
        try:
            await pub_task
        except asyncio.CancelledError:
            pass

        transport.close()
        send_sock.close()
        self._safe_shutdown()
        logger.info("Shutdown complete")
        return 0

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and run the daemon.

    CLI flags:
        --config PATH   Path to hwd.json (default /etc/hmi/hwd.json).
        --sim           Force simulation backends (no hardware access).
        --strict        Exit non-zero if hardware is unavailable (target mode).
        --selftest      Init, poll once, print one telemetry frame, exit 0.
        --log-level LVL Logging level: DEBUG, INFO, WARNING, ERROR (default INFO).
    """
    parser = argparse.ArgumentParser(
        description="HMI Hardware Abstraction Daemon (Layer 1)",
    )
    parser.add_argument(
        "--config",
        default="/etc/hmi/hwd.json",
        help="Path to hwd.json config file (default: /etc/hmi/hwd.json)",
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Force simulation backends, ignoring real hardware",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if hardware is unavailable (for target use)",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Init, poll once, print one JSON telemetry frame to stdout, exit 0",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    cfg = load_config(args.config)

    force_sim = args.sim
    strict = args.strict
    if force_sim and strict:
        logger.error("--sim and --strict are mutually exclusive")
        sys.exit(1)

    daemon = HwDaemon(cfg, force_sim=force_sim, strict=strict)

    exit_code = asyncio.run(daemon.run(selftest=args.selftest))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
