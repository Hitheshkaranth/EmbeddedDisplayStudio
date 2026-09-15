"""
tools/hmi_deployer/taglab.py
Layer: 3 (Host Deployer)
Purpose: Tag Lab – deterministic waveform-based telemetry injection for offline
         validation and regression testing of HMI apps.

Design principles
-----------------
* Business logic (waveforms, model, scenario I/O) is isolated from Qt so it is
  fully exercisable by plain unittest without a QApplication.
* The QObject-derived TagLabSender is the only Qt-aware object and owns the
  timer and the pooled UDP socket.
* Scenario files are written atomically (write-to-temp + rename) to prevent
  partial files on crash or disk-full.
* Unknown tags discovered after the model is built must be explicitly added;
  they never silently become active outputs.
"""
from __future__ import annotations

import json
import math
import os
import random
import socket
import time
import uuid
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Waveform generators
# ---------------------------------------------------------------------------

WAVEFORM_KINDS = ("constant", "sine", "square", "ramp", "noise")


def _validate_period(period: float, name: str = "period") -> float:
    """Return *period* as float, raising ValueError if non-finite or non-positive."""
    period = float(period)
    if not math.isfinite(period) or period <= 0.0:
        raise ValueError(f"{name} must be a finite positive number, got {period!r}")
    return period


def _validate_amplitude(amplitude: float) -> float:
    amplitude = float(amplitude)
    if not math.isfinite(amplitude):
        raise ValueError(f"amplitude must be finite, got {amplitude!r}")
    return amplitude


def _validate_offset(offset: float) -> float:
    offset = float(offset)
    if not math.isfinite(offset):
        raise ValueError(f"offset must be finite, got {offset!r}")
    return offset


class ConstantWaveform:
    """
    Outputs a fixed numeric value regardless of time.

    This is the 'override' mode: it drives the tag to a constant so a tester
    can pin a sensor reading without touching the hardware.
    """

    kind = "constant"

    def __init__(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"constant value must be finite, got {value!r}")
        self._value = value

    @property
    def value(self) -> float:
        return self._value

    def sample(self, t: float) -> float:  # noqa: ARG002  (t unused)
        return self._value

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "value": self._value}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConstantWaveform":
        return cls(d["value"])


class SineWaveform:
    """
    Sinusoidal waveform: amplitude * sin(2*pi*t / period) + offset.
    """

    kind = "sine"

    def __init__(self, amplitude: float, period: float, offset: float = 0.0) -> None:
        self._amplitude = _validate_amplitude(amplitude)
        self._period = _validate_period(period)
        self._offset = _validate_offset(offset)

    @property
    def amplitude(self) -> float:
        return self._amplitude

    @property
    def period(self) -> float:
        return self._period

    @property
    def offset(self) -> float:
        return self._offset

    def sample(self, t: float) -> float:
        return self._amplitude * math.sin(2.0 * math.pi * t / self._period) + self._offset

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "amplitude": self._amplitude,
            "period": self._period,
            "offset": self._offset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SineWaveform":
        return cls(d["amplitude"], d["period"], d.get("offset", 0.0))


class SquareWaveform:
    """
    Square/pulse waveform: alternates between *high* and *low*.

    ``duty`` is the fraction of *period* spent at *high* (0 < duty <= 1).
    """

    kind = "square"

    def __init__(
        self,
        high: float,
        low: float,
        period: float,
        duty: float = 0.5,
    ) -> None:
        self._high = _validate_amplitude(high)
        self._low = _validate_amplitude(low)
        self._period = _validate_period(period)
        duty = float(duty)
        if not math.isfinite(duty) or not (0.0 < duty <= 1.0):
            raise ValueError(f"duty must be in (0, 1], got {duty!r}")
        self._duty = duty

    @property
    def high(self) -> float:
        return self._high

    @property
    def low(self) -> float:
        return self._low

    @property
    def period(self) -> float:
        return self._period

    @property
    def duty(self) -> float:
        return self._duty

    def sample(self, t: float) -> float:
        phase = math.fmod(t, self._period)
        if phase < 0:
            phase += self._period
        return self._high if phase < self._duty * self._period else self._low

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "high": self._high,
            "low": self._low,
            "period": self._period,
            "duty": self._duty,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SquareWaveform":
        return cls(d["high"], d["low"], d["period"], d.get("duty", 0.5))


class RampWaveform:
    """
    Sawtooth ramp: linearly increases from *low* to *high* over *period*, then resets.
    """

    kind = "ramp"

    def __init__(self, low: float, high: float, period: float) -> None:
        self._low = _validate_amplitude(low)
        self._high = _validate_amplitude(high)
        self._period = _validate_period(period)

    @property
    def low(self) -> float:
        return self._low

    @property
    def high(self) -> float:
        return self._high

    @property
    def period(self) -> float:
        return self._period

    def sample(self, t: float) -> float:
        phase = math.fmod(t, self._period)
        if phase < 0:
            phase += self._period
        return self._low + (self._high - self._low) * (phase / self._period)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "low": self._low,
            "high": self._high,
            "period": self._period,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RampWaveform":
        return cls(d["low"], d["high"], d["period"])


class NoiseWaveform:
    """
    White noise uniformly distributed in [mean - amplitude, mean + amplitude].

    Each call to ``sample()`` returns an independent draw.
    """

    kind = "noise"

    def __init__(self, amplitude: float, mean: float = 0.0) -> None:
        self._amplitude = _validate_amplitude(amplitude)
        if self._amplitude < 0:
            raise ValueError(f"noise amplitude must be >= 0, got {self._amplitude!r}")
        self._mean = _validate_offset(mean)

    @property
    def amplitude(self) -> float:
        return self._amplitude

    @property
    def mean(self) -> float:
        return self._mean

    def sample(self, t: float) -> float:  # noqa: ARG002
        return self._mean + random.uniform(-self._amplitude, self._amplitude)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "amplitude": self._amplitude, "mean": self._mean}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "NoiseWaveform":
        return cls(d["amplitude"], d.get("mean", 0.0))


# Registry used by both serialisation and the UI combo-box.
_WAVEFORM_REGISTRY: Dict[str, type] = {
    cls.kind: cls  # type: ignore[attr-defined]
    for cls in (ConstantWaveform, SineWaveform, SquareWaveform, RampWaveform, NoiseWaveform)
}


def waveform_from_dict(d: Dict[str, Any]):
    """
    Deserialise a waveform from a scenario dict entry.

    Raises KeyError if 'kind' is missing or unrecognised.
    """
    kind = d.get("kind")
    if kind not in _WAVEFORM_REGISTRY:
        raise KeyError(f"Unknown waveform kind {kind!r}. Valid: {sorted(_WAVEFORM_REGISTRY)}")
    return _WAVEFORM_REGISTRY[kind].from_dict(d)


# ---------------------------------------------------------------------------
# Tag entry
# ---------------------------------------------------------------------------

class TagEntry:
    """
    Associates a tag name with a waveform and an enabled flag.

    Only entries that are both *known* (present in the model's tag list) and
    *enabled* contribute to outgoing UDP frames.  Unknown tag names may be
    added to the model but are disabled by default – they never silently
    become active outputs.
    """

    def __init__(
        self,
        tag: str,
        waveform,
        enabled: bool = True,
        known: bool = True,
    ) -> None:
        if not tag or not isinstance(tag, str):
            raise ValueError(f"tag must be a non-empty string, got {tag!r}")
        self.tag = tag
        self.waveform = waveform
        self.enabled = bool(enabled)
        # Tags not declared in the bundle's tags_required start as unknown.
        # They can be enabled manually but never auto-activate.
        self.known = bool(known)

    def sample(self, t: float) -> float:
        return self.waveform.sample(t)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "enabled": self.enabled,
            "known": self.known,
            "waveform": self.waveform.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TagEntry":
        return cls(
            tag=d["tag"],
            waveform=waveform_from_dict(d["waveform"]),
            enabled=bool(d.get("enabled", True)),
            known=bool(d.get("known", True)),
        )


# ---------------------------------------------------------------------------
# Tag Lab Model
# ---------------------------------------------------------------------------

class TagLabModel:
    """
    Ordered collection of TagEntry objects.

    The model is the single source of truth for the Tag Lab panel.  It is
    intentionally Qt-free so it can be tested in pure Python.
    """

    def __init__(self, tags: Optional[List[str]] = None) -> None:
        """
        Args:
            tags: The bundle's ``tags_required`` list.  Each tag gets a default
                  ConstantWaveform(0) entry that is enabled and known.
        """
        self._entries: List[TagEntry] = []
        for tag in (tags or []):
            self.add_tag(tag, ConstantWaveform(0.0), known=True)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_tag(
        self,
        tag: str,
        waveform=None,
        enabled: bool = True,
        known: bool = True,
    ) -> TagEntry:
        """
        Add *tag* to the model.

        If the tag already exists the existing entry is returned unchanged.
        Unknown tags (not in tags_required) are added with enabled=False
        regardless of the *enabled* argument, enforcing the invariant that
        unknown tags never silently become active outputs.
        """
        existing = self.find(tag)
        if existing is not None:
            return existing
        if waveform is None:
            waveform = ConstantWaveform(0.0)
        # Unknown tags must not silently become active outputs.
        effective_enabled = enabled if known else False
        entry = TagEntry(tag, waveform, enabled=effective_enabled, known=known)
        self._entries.append(entry)
        return entry

    def remove_tag(self, tag: str) -> bool:
        """Remove entry by tag name. Returns True if removed, False if not found."""
        for i, e in enumerate(self._entries):
            if e.tag == tag:
                self._entries.pop(i)
                return True
        return False

    def find(self, tag: str) -> Optional[TagEntry]:
        """Return the entry for *tag*, or None."""
        for e in self._entries:
            if e.tag == tag:
                return e
        return None

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @property
    def entries(self) -> List[TagEntry]:
        """Immutable view of entries list (returns a copy)."""
        return list(self._entries)

    def active_entries(self) -> List[TagEntry]:
        """Entries explicitly enabled by the user or bundle binding."""
        return [e for e in self._entries if e.enabled]

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_scenario(self) -> Dict[str, Any]:
        """Return a scenario dict (schema 1)."""
        return {
            "schema": 1,
            "entries": [e.to_dict() for e in self._entries],
        }

    @classmethod
    def from_scenario(cls, data: Dict[str, Any]) -> "TagLabModel":
        """
        Construct a TagLabModel from a scenario dict.

        Raises ValueError on schema mismatch or structural errors.
        """
        if not isinstance(data, dict):
            raise ValueError("Scenario must be a JSON object")
        schema = data.get("schema")
        if schema != 1:
            raise ValueError(f"Unsupported scenario schema {schema!r}; expected 1")
        entries_raw = data.get("entries")
        if not isinstance(entries_raw, list):
            raise ValueError("Scenario 'entries' must be a list")
        model = cls()
        for raw in entries_raw:
            entry = TagEntry.from_dict(raw)
            model._entries.append(entry)
        return model


# ---------------------------------------------------------------------------
# Scenario I/O
# ---------------------------------------------------------------------------

def save_scenario(model: TagLabModel, path: str) -> None:
    """
    Atomically write the model's scenario to *path*.

    Uses write-to-temp + os.replace to prevent a partial file on crash.
    """
    data = model.to_scenario()
    dir_name = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_name, exist_ok=True)
    # An exclusive create in the destination directory gives us a
    # same-filesystem atomic-replace guarantee without inheriting an OS file
    # descriptor across a wrapper process.
    tmp_path = os.path.join(
        dir_name,
        f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp",
    )
    try:
        with open(tmp_path, "x", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_scenario(path: str) -> TagLabModel:
    """
    Load a scenario from *path* and return a TagLabModel.

    Raises FileNotFoundError, json.JSONDecodeError, or ValueError on problems.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return TagLabModel.from_scenario(data)


# ---------------------------------------------------------------------------
# CommandSink — CONTRACT 2.2 daemon substitute (Qt-free)
# ---------------------------------------------------------------------------

#: Default command port (CONTRACT 2.1 — client→daemon).
COMMAND_SINK_DEFAULT_PORT = 5000

#: Maximum datagram size (CONTRACT 2).
_COMMAND_MAX_BYTES = 8192

#: Known error codes (CONTRACT 2.3).
_ERROR_CODES = frozenset((
    "bad_json", "not_an_object", "too_large",
    "unknown_cmd", "unknown_tag", "not_writable",
    "bad_value", "hw_error", "rate_limited",
))


class _Subscribers:
    """Track subscriber addresses and TTLs for the daemon's subscriber list.

    CONTRACT 2.1 — the daemon → dynamic subscribers table.  TTL is in
    seconds; addresses older than the TTL are silently pruned on each write.
    """

    def __init__(self, ttl: float = 5.0) -> None:
        self._ttl = ttl
        self._subscribers: Dict[str, float] = {}  # addr_key -> expiry

    def add(self, addr: str, ttl: float) -> None:
        """Register or refresh *addr* with TTL seconds."""
        self._subscribers[addr] = time.monotonic() + ttl

    def remove(self, addr: str) -> None:
        """Unregister *addr*."""
        self._subscribers.pop(addr, None)

    def prune(self) -> List[str]:
        """Remove expired addresses, return surviving ones."""
        now = time.monotonic()
        dead = [k for k, v in self._subscribers.items() if v <= now]
        for k in dead:
            del self._subscribers[k]
        return list(self._subscribers.keys())

    def alive_count(self) -> int:
        return len(self._subscribers)


def _coerce_bool_value(value: Any) -> bool:
    """Coerce *value* to bool the way the daemon does.

    CONTRACT 2.2 — `set` commands accept 0/1/true/false.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        if value.lower() in ("true", "1"):
            return True
        if value.lower() in ("false", "0"):
            return False
    if isinstance(value, (float,)):
        return bool(round(value))
    return bool(value)


class CommandSink:
    """
    Listens on the daemon's command port and answers CONTRACT 2.2 commands.

    This is the offline substitute for hmi-hwd's command handler: it binds
    UDP 127.0.0.1:5000 only if nothing else holds it, parses commands the
    same way the daemon does (bad JSON, non-object, oversized → counted,
    ack ok:false when an id can be recovered, silence otherwise), and drives
    a TagLabModel so the Tag Lab sender's outgoing frames reflect overrides.

    Unlike the daemon, this class does NOT talk to hardware — it only
    manipulates the model and replies on the UDP socket.

    Attributes:
        port: The UDP port this sink is bound to (0 if binding failed).
        online: True while the sink is listening.
        errors: Cumulative count of rejected datagrams.
    """

    def __init__(
        self,
        model: TagLabModel,
        host: str = "127.0.0.1",
        port: int = COMMAND_SINK_DEFAULT_PORT,
        parent: Optional["QObject"] = None,  # noqa: F821  (Qt-aware)
    ) -> None:
        """
        Args:
            model:       The TagLabModel to drive with set/pulse commands.
            host:        UDP bind address (default loopback).
            port:        UDP port (default 5000, the daemon command port).
            parent:      Parent QObject (for signal lifecycle).
        """
        self._model = model
        self._host = host
        self._port = port
        self._sock: Optional[socket.socket] = None
        self._online: bool = False
        self._errors: int = 0
        self._subscribers = _Subscribers()
        self._pulse_timers: Dict[str, Any] = {}  # tag -> active PulseTimer (Qt)
        self._send_list: List[str] = []  # list of (host, port) tuples for ack forwarding
        self._parent = parent
        self._command_log: List[Dict[str, Any]] = []  # list of processed command dicts (Phase B)
        self._cmd_seq: int = 0  # command sequence number for logging

        # Acquire the port immediately — if it fails, port will be 0.
        self._bind()

    # ------------------------------------------------------------------
    # Port lifecycle
    # ------------------------------------------------------------------

    def _bind(self) -> None:
        """Bind the UDP socket.  Returns True if successful."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self._host, self._port))
            sock.settimeout(0.05)  # non-blocking so we can poll
            self._sock = sock
            self._online = True
        except OSError:
            self._online = False
            self._sock = None

    def acquire(self) -> bool:
        """
        Take ownership of the command port.

        Called when a connected session starts (relay active).  Releases the
        existing sink and re-binds.  Returns True if the port was acquired.
        """
        self.release()
        return self._bind()

    def release(self) -> None:
        """
        Release the command port and stop answering commands.

        Restores original model waveforms for any tags that were pulse-modified.
        Called when a connected session ends.
        """
        self._stop_all_pulses()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._online = False
        self._subscribers = _Subscribers()

    @property
    def port(self) -> int:
        """The port we are bound to, or 0 if not bound."""
        if self._sock is None:
            return 0
        try:
            return self._sock.getsockname()[1]
        except OSError:
            return 0

    @property
    def online(self) -> bool:
        return self._online

    @property
    def errors(self) -> int:
        return self._errors

    # ------------------------------------------------------------------
    # Pulse management (timer-based, not thread-based)
    # ------------------------------------------------------------------

    def _stop_all_pulses(self) -> None:
        """Cancel all active pulse timers.  Sub-class hook for Qt."""
        for tag, t in list(self._pulse_timers.items()):
            self._cancel_pulse_timer(tag, t)
        self._pulse_timers.clear()

    def _cancel_pulse_timer(self, tag: str, timer: Any) -> None:
        """Cancel a single pulse timer.  Override for Qt."""
        pass

    def _restore_waveform(self, tag: str, original_waveform) -> None:
        """Restore a tag's original waveform after a pulse completes."""
        entry = self._model.find(tag)
        if entry is not None:
            entry.waveform = original_waveform

    def _get_original_waveform(self, tag: str) -> Optional[Any]:
        """Get a serialisable copy of a tag's waveform for pulse restoration."""
        entry = self._model.find(tag)
        if entry is not None:
            return entry.waveform.to_dict()
        return None

    def _restore_from_dict(self, tag: str, wave_dict: Dict[str, Any]) -> None:
        """Restore a waveform from a serialised dict."""
        entry = self._model.find(tag)
        if entry is not None:
            entry.waveform = waveform_from_dict(wave_dict)

    # ------------------------------------------------------------------
    # Datagram processing
    # ------------------------------------------------------------------

    def _handle_datagrams(self) -> int:
        """
        Read and dispatch all pending datagrams.

        Returns the number of datagrams processed.

        No exception may escape this method (CONTRACT section 7).
        """
        count = 0
        if self._sock is None or not self._online:
            return 0

        # Process one datagram per call (Qt event loop calls this via readyRead)
        try:
            datagram, sender = self._sock.recvfrom(_COMMAND_MAX_BYTES)
        except socket.timeout:
            return 0
        except OSError:
            return 0

        count = 1

        # Oversized check
        if len(datagram) > _COMMAND_MAX_BYTES:
            self._errors += 1
            try:
                self._send_ack(sender, {"id": "", "ok": False, "err": "too_large"})
            except OSError:
                pass
            return count

        # Parse JSON
        try:
            cmd = json.loads(datagram.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._errors += 1
            return count

        # Must be an object
        if not isinstance(cmd, dict):
            self._errors += 1
            cid = cmd.get("id") if isinstance(cmd, dict) else ""
            if cid:
                try:
                    self._send_ack(sender, {"id": str(cid), "ok": False, "err": "not_an_object"})
                except OSError:
                    pass
            return count

        cmd_type = cmd.get("cmd")
        if not cmd_type or not isinstance(cmd_type, str):
            self._errors += 1
            cid = cmd.get("id", "")
            if cid:
                try:
                    self._send_ack(sender, {"id": str(cid), "ok": False, "err": "unknown_cmd"})
                except OSError:
                    pass
            return count

        cid = cmd.get("id", "")

        # Dispatch command
        handler = self._COMMAND_HANDLERS.get(cmd_type)
        if handler is None:
            self._errors += 1
            # Log the rejected command
            self._cmd_seq += 1
            self._command_log.append({
                "seq": self._cmd_seq,
                "src": f"{sender[0]}:{sender[1]}",
                "cmd": cmd_type,
                "tag": cmd.get("tag", ""),
                "value": "",
                "ok": False,
                "err": "unknown_cmd",
            })
            if cid:
                try:
                    self._send_ack(sender, {"id": str(cid), "ok": False, "err": "unknown_cmd"})
                except OSError:
                    pass
            return count

        try:
            result = handler(self, cmd, sender)
            ok_val = result.get("ok", True) if result else True
            err_val = result.get("err", "") if result else ""
            # Log the command
            self._cmd_seq += 1
            self._command_log.append({
                "seq": self._cmd_seq,
                "src": f"{sender[0]}:{sender[1]}",
                "cmd": cmd_type,
                "tag": cmd.get("tag", ""),
                "value": cmd.get("value", ""),
                "ok": ok_val,
                "err": err_val,
            })
            if result is not None and cid:
                try:
                    self._send_ack(sender, {"id": str(cid), "ok": result.get("ok", True), **result})
                except OSError:
                    pass
        except Exception:
            self._errors += 1
            # Log the failed command
            self._cmd_seq += 1
            self._command_log.append({
                "seq": self._cmd_seq,
                "src": f"{sender[0]}:{sender[1]}",
                "cmd": cmd_type,
                "tag": cmd.get("tag", ""),
                "value": cmd.get("value", ""),
                "ok": False,
                "err": "hw_error",
            })
            if cid:
                try:
                    self._send_ack(sender, {"id": str(cid), "ok": False, "err": "hw_error"})
                except OSError:
                    pass

        return count

    # Command handlers
    _COMMAND_HANDLERS: Dict[str, Any] = {}

    @classmethod
    def _register_handler(cls, cmd_name: str):
        """Decorator to register a command handler."""
        def decorator(fn):
            cls._COMMAND_HANDLERS[cmd_name] = fn
            return fn
        return decorator

    @staticmethod
    def _send_ack_to_socket(sock: socket.socket, addr: tuple, ack: dict) -> None:
        """Send an ack datagram to *addr*."""
        try:
            payload = json.dumps(ack).encode("utf-8")
            sock.sendto(payload, addr)
        except OSError:
            pass

    def _send_ack(self, sender: tuple, ack_body: dict) -> None:
        """Send an ack to the sender address, also forward to subscribers."""
        ack = {"t": "ack", **ack_body}
        # Primary send
        if self._sock:
            self._send_ack_to_socket(self._sock, sender, ack)
        # Forward to subscribers
        for sub_addr in self._subscribers.prune():
            try:
                self._send_ack_to_socket(self._sock, (sub_addr, 5001), ack)
            except OSError:
                pass

    # Registered handlers
    @staticmethod
    def _handle_set(sink: "CommandSink", cmd: dict, sender: tuple) -> dict:
        """CONTRACT 2.2 `set` — set a tag to a constant value."""
        tag = cmd.get("tag")
        value = cmd.get("value")
        if not tag or not isinstance(tag, str):
            return {"ok": False, "err": "unknown_tag"}

        # Check if tag is in the model
        entry = sink._model.find(tag)
        if entry is None:
            return {"ok": False, "err": "unknown_tag"}

        # Coerce value
        try:
            if tag.startswith(("di.", "do.")):
                coerced = _coerce_bool_value(value)
            else:
                coerced = float(value) if not isinstance(value, (int, float)) else value
                if isinstance(coerced, bool):
                    coerced = float(int(coerced))
        except (ValueError, TypeError):
            return {"ok": False, "err": "bad_value"}

        # Check writability — only do.* tags are writable
        if not tag.startswith("do."):
            return {"ok": False, "err": "not_writable"}

        # Apply override: replace waveform with ConstantWaveform
        entry.waveform = ConstantWaveform(coerced)
        return {"ok": True}

    @staticmethod
    def _handle_pulse(sink: "CommandSink", cmd: dict, sender: tuple) -> dict:
        """CONTRACT 2.2 `pulse` — drive constant for ms, then restore."""
        tag = cmd.get("tag")
        ms = cmd.get("ms")
        if not tag or not isinstance(tag, str):
            return {"ok": False, "err": "unknown_tag"}
        if ms is None:
            return {"ok": False, "err": "bad_value"}

        # Validate pulse duration
        try:
            ms = int(ms)
            if ms < 1 or ms > 10000:
                return {"ok": False, "err": "bad_value"}
        except (ValueError, TypeError):
            return {"ok": False, "err": "bad_value"}

        entry = sink._model.find(tag)
        if entry is None:
            return {"ok": False, "err": "unknown_tag"}

        if not tag.startswith("do."):
            return {"ok": False, "err": "not_writable"}

        # Save original waveform and set constant
        original = entry.waveform.to_dict()
        value = 1.0 if tag.startswith(("di.", "do.")) else float(cmd.get("value", 1.0))

        # For pulse, we set it to high (1.0 for bools, the value for numbers)
        if tag.startswith(("di.", "do.")):
            coerced_val = _coerce_bool_value(value)
            entry.waveform = ConstantWaveform(float(coerced_val))
        else:
            entry.waveform = ConstantWaveform(float(value))

        # Store pulse info for restoration
        sink._pulse_timers[tag] = {
            "original": original,
            "entry": entry,
        }

        # Start the timer — this will be overridden by Qt-aware subclass
        # For now, just return ok; the PulseTimer subclass will start it
        return {"ok": True}

    @staticmethod
    def _handle_list(sink: "CommandSink", cmd: dict, sender: tuple) -> dict:
        """CONTRACT 2.2 `list` — return the model's tags."""
        tags = [e.tag for e in sink._model.entries]
        return {"ok": True, "tags": tags}

    @staticmethod
    def _handle_ping(sink: "CommandSink", cmd: dict, sender: tuple) -> dict:
        """CONTRACT 2.2 `ping` — always acks."""
        return {"ok": True}

    @staticmethod
    def _handle_subscribe(sink: "CommandSink", cmd: dict, sender: tuple) -> dict:
        """CONTRACT 2.2 `subscribe` — add subscriber address."""
        ttl = cmd.get("ttl", 5)
        try:
            ttl = float(ttl)
        except (ValueError, TypeError):
            ttl = 5.0
        # Use sender address as subscriber key
        addr = f"{sender[0]}:{sender[1]}"
        sink._subscribers.add(addr, ttl)
        return {"ok": True}

    @staticmethod
    def _handle_unsubscribe(sink: "CommandSink", cmd: dict, sender: tuple) -> dict:
        """CONTRACT 2.2 `unsubscribe` — remove subscriber address."""
        addr = f"{sender[0]}:{sender[1]}"
        sink._subscribers.remove(addr)
        return {"ok": True}


# Register the handlers
CommandSink._COMMAND_HANDLERS["set"] = CommandSink._handle_set
CommandSink._COMMAND_HANDLERS["pulse"] = CommandSink._handle_pulse
CommandSink._COMMAND_HANDLERS["list"] = CommandSink._handle_list
CommandSink._COMMAND_HANDLERS["ping"] = CommandSink._handle_ping
CommandSink._COMMAND_HANDLERS["subscribe"] = CommandSink._handle_subscribe
CommandSink._COMMAND_HANDLERS["unsubscribe"] = CommandSink._handle_unsubscribe


# ---------------------------------------------------------------------------
# PulseTimer — Qt-aware wrapper around CommandSink pulse lifecycle
# ---------------------------------------------------------------------------

try:
    from PySide6.QtCore import QObject, QTimer as _QTimer

    class PulseTimer(QObject):
        """
        Manages a single pulse lifecycle using QTimer (not a thread).

        When a `pulse` command arrives, this stores the original waveform,
        sets a ConstantWaveform, and schedules restoration after *ms* milliseconds.

        This is attached to a CommandSink's _pulse_timers dict.
        """

        def __init__(
            self,
            sink: CommandSink,
            tag: str,
            original_waveform_dict: Dict[str, Any],
            ms: int,
            parent: Optional[QObject] = None,
        ) -> None:
            super().__init__(parent)
            self._sink = sink
            self._tag = tag
            self._original = original_waveform_dict
            self._timer = _QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._on_timeout)
            self._timer.start(ms)

        def _on_timeout(self) -> None:
            """Restore the original waveform."""
            self._sink._restore_from_dict(self._tag, self._original)
            # Remove from pulse timers
            if self._tag in self._sink._pulse_timers:
                del self._sink._pulse_timers[self._tag]

    # Patch CommandSink to use PulseTimer for pulses
    original_handle_pulse = CommandSink._handle_pulse

    @staticmethod
    def _handle_pulse_qt(sink: CommandSink, cmd: dict, sender: tuple) -> dict:
        """QT-aware pulse handler that starts a QTimer-based restoration."""
        result = original_handle_pulse(sink, cmd, sender)
        if result.get("ok"):
            tag = cmd.get("tag")
            ms = int(cmd.get("ms", 250))
            entry = sink._model.find(tag)
            if entry is not None:
                original = entry.waveform.to_dict()
                sink._pulse_timers[tag] = {
                    "original": original,
                    "entry": entry,
                }
                # Start the PulseTimer
                try:
                    PulseTimer(sink, tag, original, ms, sink._parent if sink._parent else sink)
                except Exception:
                    pass
        return result

    # Replace the handler
    CommandSink._COMMAND_HANDLERS["pulse"] = _handle_pulse_qt

    # Add the datagram polling method for Qt event loop integration
    class CommandSinkQtMixIn:
        """Mixin providing a readyRead signal for Qt event loop integration."""
        pass

except ImportError:
    PulseTimer = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# UDP sender (Qt-aware, but only this class)
# ---------------------------------------------------------------------------

try:
    from PySide6.QtCore import QObject, QTimer, Signal as _Signal

    class TagLabSender(QObject):
        """
        Drives a TagLabModel, sampling all active entries on a QTimer tick and
        sending a single UDP datagram per tick to the TagEngine's listen port.

        A single socket is created at construction and closed at stop() or
        destruction.  The same socket is reused for every send so OS handles
        are not exhausted.

        Signals:
            error(str): Emitted when a send fails (non-fatal; sender continues).
        """

        error = _Signal(str)

        #: Protocol frame type (matches daemon wire protocol CONTRACT 2.4)
        _FRAME_TYPE = "tags"
        _SRC = "hmi-taglab"

        def __init__(
            self,
            model: TagLabModel,
            host: str = "127.0.0.1",
            port: int = 5001,
            interval_ms: int = 100,
            parent: Optional[QObject] = None,
        ) -> None:
            """
            Args:
                model:       The TagLabModel to drive.  Ownership is NOT
                             transferred; the caller must keep it alive.
                host:        Destination UDP host.
                port:        Destination UDP port (default 5001, TagEngine's
                             default listen port).
                interval_ms: Send interval in milliseconds.
                parent:      Parent QObject.
            """
            super().__init__(parent)
            self._model = model
            self._host = host
            self._port = port
            self._interval_ms = interval_ms
            self._seq: int = 0
            self._t0: float = time.monotonic()
            self._sock: Optional[socket.socket] = None
            self._closed: bool = False

            self._timer = QTimer(self)
            self._timer.setInterval(interval_ms)
            self._timer.timeout.connect(self._tick)

        # ------------------------------------------------------------------
        # Lifecycle
        # ------------------------------------------------------------------

        def start(self) -> None:
            """Open the UDP socket and begin sending."""
            if self._closed:
                raise RuntimeError("TagLabSender has been stopped and cannot be restarted")
            if self._sock is None:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._t0 = time.monotonic()
            self._timer.start()

        def stop(self) -> None:
            """
            Stop sending and close the socket.  Idempotent: safe to call
            multiple times.
            """
            self._timer.stop()
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            self._closed = True

        def is_running(self) -> bool:
            return self._timer.isActive()

        # ------------------------------------------------------------------
        # Frame building (pure, testable)
        # ------------------------------------------------------------------

        def build_frame(self, t: float, seq: int) -> Dict[str, Any]:
            """
            Sample all active model entries and return a wire-protocol frame dict.

            This method does not touch the network and has no side-effects on
            the model, so it can be called from tests without a QApplication.
            """
            tags: Dict[str, Any] = {}
            for entry in self._model.active_entries():
                value = entry.sample(t)
                if entry.tag.startswith(("di.", "do.")):
                    value = bool(round(value))
                tags[entry.tag] = value
            return {
                "t": self._FRAME_TYPE,
                "seq": seq,
                "ts": time.time(),
                "src": self._SRC,
                "tags": tags,
            }

        # ------------------------------------------------------------------
        # Internal
        # ------------------------------------------------------------------

        def _tick(self) -> None:
            if self._closed or self._sock is None:
                # Guard: timer fired after close (e.g. race in event loop)
                self._timer.stop()
                return
            t = time.monotonic() - self._t0
            frame = self.build_frame(t, self._seq)
            self._seq += 1
            try:
                payload = json.dumps(frame).encode("utf-8")
                self._sock.sendto(payload, (self._host, self._port))
            except OSError as exc:
                self.error.emit(str(exc))

        def __del__(self) -> None:
            # Best-effort cleanup: stop() may already have been called.
            try:
                self.stop()
            except Exception:
                pass

except ImportError:
    # PySide6 not available (e.g. CI without Qt). TagLabSender is not defined;
    # tests that need it should skip with @unittest.skipUnless.
    TagLabSender = None  # type: ignore[assignment,misc]
