"""
gui/hmi_loader/tagengine.py
Layer: 2 (GUI Loader)
Purpose: TagEngine, implementing CONTRACT section 2 (wire protocol and naming).

Listens for telemetry frames from hmi-hwd over UDP loopback, mirrors every tag
into a QQmlPropertyMap for declarative QML binding, and sends actuation
commands back to the daemon. It is a pure UDP client: no hardware access of any
kind lives here (CONTRACT section 1).

PLATFORM NOTE - why this is a QObject that OWNS a map, rather than a
QQmlPropertyMap subclass:

    In C++, subclassing QQmlPropertyMap and overriding updateValue() is the
    idiomatic way to build a write-through tag map. Under PySide6 it does not
    work. QQmlPropertyMap installs a QQmlOpenMetaObject over the instance,
    which replaces the metaobject PySide generated for the Python subclass.
    Empirically, on PySide6 6.11:

        - reading a dynamic key from QML  (Tags.ai_pot)      WORKS
        - calling an @Slot from QML       (Tags.write(...))  FAILS silently
        - overriding updateValue()        (Tags.x = 1)       NEVER CALLED
        - connecting a signal to a method (socket.readyRead) FAILS with
          "AttributeError: Slot 'QQmlPropertyMap::' not found."

    The last one is fatal: it means the telemetry socket is never serviced and
    the UI shows frozen placeholder values forever. So the engine is a normal
    QObject (where signals, slots and properties all behave) and it publishes
    an ordinary QQmlPropertyMap instance for value bindings.

QML therefore sees two context properties:

    Tags  - the QQmlPropertyMap: read-only value bindings, e.g. Tags.ai_pot,
            Tags.online. Dots in tag names are illegal in QML property syntax,
            so each tag is mirrored under its underscored alias (CONTRACT 2.5).
    Bus   - this engine: commands and safe lookups, e.g. Bus.write("do.relay1",
            true), Bus.pulse("do.relay1", 250), Bus.value("ai.pot", 0).
"""

import collections
import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from PySide6.QtCore import QEventLoop, QByteArray, QObject, Property, QTimer, Signal, Slot
from PySide6.QtNetwork import QHostAddress, QUdpSocket
from PySide6.QtQml import QQmlComponent, QQmlPropertyMap

logger = logging.getLogger("TagEngine")

# Largest datagram we will even attempt to parse, in bytes (CONTRACT 2).
# Anything bigger is drained and counted, never buffered.
MAX_DATAGRAM_BYTES = 8192

# Link is declared lost if no telemetry frame arrives within this window, in ms.
# The daemon publishes every 100 ms, so 2.5 s tolerates 24 consecutive misses.
WATCHDOG_INTERVAL_MS = 2500

# How often we re-assert our subscription with the daemon, in ms. The daemon
# expires subscribers after 5 s (CONTRACT 2.1), so 2 s gives two chances to
# refresh before expiry.
SUBSCRIBE_INTERVAL_MS = 2000

# Time-to-live we request for our subscription, in seconds (CONTRACT 2.2).
SUBSCRIBE_TTL_S = 5


class TagEngine(QObject):
    """
    Owns the UDP link to hmi-hwd and the tag map that QML binds against.

    Signals:
        ackReceived(str id, bool ok, str err): a command acknowledgement
            arrived from the daemon (CONTRACT 2.3).
        onlineChanged(): the link state flipped; `online` has a new value.

    Side effects: binds a UDP socket on construction and starts two timers.
    """

    # Emitted for every well-formed ack. `id` is the opaque correlation id the
    # caller supplied, `ok` the daemon's verdict, `err` a CONTRACT 2.3 code.
    ackReceived = Signal(str, bool, str)

    # Emitted whenever the link watchdog changes the online state.
    onlineChanged = Signal()

    # Emitted when a datagram is rejected, so a diagnostics screen can bind to
    # rxErrors and see it move.
    rxErrorsChanged = Signal()

    # Emitted when `list_tags()` receives the daemon's catalogue.
    listReceived = Signal(object)

    # Emitted when `unsubscribe()` receives an ack.
    unsubscribed = Signal()

    # Emitted when the history version changes (once per telemetry frame).
    historyVersionChanged = Signal()

    # Emitted when the active alarms list changes (activation, clear, ack,
    # severity change); NOT fired on every frame to avoid re-evaluating all
    # alarm bindings in QML 10 times a second.
    activeAlarmsChanged = Signal()

    def __init__(
        self,
        expected_tags: list[str],
        rx_port: int = 5001,
        allow_any_port: bool = False,
        daemon_host: str = "127.0.0.1",
        daemon_port: int = 5000,
        history_depth: int = 600,
        alarm_defs: list[dict] = None,
        parent: QObject = None,
    ) -> None:
        """
        Args:
            expected_tags: dotted tag names the loaded app declares in its
                manifest (`tags_required`). Each is pre-seeded into the map as
                None so QML bindings resolve on the very first frame instead of
                erroring on an unknown property (CONTRACT section 7).
            allow_any_port: fall back to an ephemeral port when rx_port is
                taken. Only safe where the caller also owns the sender and
                can be told which port was chosen -- true of the host tool,
                false of the panel, where hmi-hwd sends to a fixed port.
            rx_port: UDP port to bind for telemetry, 1..65535. Must match the
                daemon's configured static sink (default 5001).
            daemon_host: address of the command socket. Loopback only by
                design; the daemon does not listen off-box.
            daemon_port: the daemon's command port, 1..65535 (default 5000).
            history_depth: maximum samples to keep per tag in the ring buffer.
                600 samples at 10 Hz = 60 seconds. Tags beyond this depth are
                silently dropped (oldest first). Default 600.
            alarm_defs: manifest-shaped alarm definitions (CONTRACT C2). Each
                item: {"tag": ..., "label": ..., "unit": ..., "warning": ...,
                "critical": ...}. Alarm tags are recorded alongside
                expected_tags. Default [].
            parent: owning QObject, or None.

        Raises:
            Nothing. A failed socket bind is logged and leaves the engine
            permanently offline rather than taking the UI down with it.
        """
        super().__init__(parent)
        # Pending correlation ids -> ack handler; set by slot calls, popped
        # by ackReceived. Per instance: a class-level dict was shared by every
        # engine in the process, so one engine could consume another's ack.
        self._pending_acks: dict[str, Any] = {}

        # Current link state. False until the first valid frame arrives.
        self._online = False

        # Cumulative count of datagrams rejected for any reason. Surfaced for
        # diagnostics; a climbing value means something is spraying the port.
        self._rx_errors = 0

        # Where commands are sent.
        self._daemon_addr = QHostAddress(daemon_host)
        self._daemon_port = daemon_port

        # Monotonic counter behind the correlation ids put on outgoing
        # commands. The daemon only acks a command that carries an "id"
        # (CONTRACT 2.3), so without one a rejected write -- not_writable,
        # bad_value, hw_error -- was silently dropped and ackReceived could
        # only ever fire for ping. An app had no way to tell a command that
        # took effect from one the daemon refused.
        self._cmd_seq = 0

        # Reverse lookup from QML-safe alias ("ai_pot") to wire name ("ai.pot"),
        # needed because commands must use the dotted form (CONTRACT 2.5).
        self._alias_to_tag: dict[str, str] = {}

        # The map QML binds to. A plain QQmlPropertyMap instance, NOT a
        # subclass - see the module docstring for why that distinction matters.
        self._map = QQmlPropertyMap(self)

        # Seed both spellings of every expected tag so no binding starts out
        # referencing a non-existent property.
        for tag in expected_tags or []:
            alias = tag.replace(".", "_")
            self._alias_to_tag[alias] = tag
            self._map.insert(tag, None)
            self._map.insert(alias, None)

        # Mirror the link state into the map as well, so QML can bind
        # `Tags.online` alongside the tag values without needing the engine.
        self._map.insert("online", False)

        # -- history ring buffers (CONTRACT C3) --------------------------------
        # Each recorded tag gets a deque(maxlen=history_depth). Numeric values
        # only: bool is converted to 0/1, null is skipped. Recording applies to
        # expected_tags plus alarm_tags (so the engine records everything the
        # alarm evaluator needs).
        self._history_depth = max(1, history_depth)
        self._history: dict[str, collections.deque] = {}
        self._history_version = 0  # incremented once per frame after buffers

        # -- alarm state (CONTRACT C2 + C3) -----------------------------------
        # The raw alarm definitions from the manifest (or empty list).
        self._alarm_defs: list[dict] = alarm_defs or []
        # Active alarms: {tag: {tag, label, severity, value, message, timestamp, acknowledged}}
        self._active_alarms: dict[str, dict] = {}
        # Set of alarm tags (union of tags_required and alarm tag definitions).
        self._alarm_tag_set: set[str] = set()
        # Collect alarm tags from definitions.
        for adef in self._alarm_defs:
            if isinstance(adef, dict):
                t = adef.get("tag")
                if isinstance(t, str):
                    self._alarm_tag_set.add(t)
                    # Also seed the underscore alias.
                    alias = t.replace(".", "_")
                    self._alias_to_tag.setdefault(alias, t)

        # Build the complete list of recorded tags = expected + alarm tags.
        self._recorded_tags: set[str] = set(expected_tags or []) | self._alarm_tag_set

        # Initialize ring buffers for all recorded tags.
        for tag in self._recorded_tags:
            self._history[tag] = collections.deque(maxlen=self._history_depth)

        self._socket = QUdpSocket(self)
        if not self._socket.bind(QHostAddress("127.0.0.1"), rx_port):
            # Usually a second instance, or one that exited without releasing
            # the port. On the panel there is nothing to fall back to: the
            # hardware daemon sends to a fixed port and cannot be told about a
            # different one, so this stays a permanent offline.
            #
            # A host tool owns both ends of this socket and can simply move,
            # which is what allow_any_port asks for. Running offline with dead
            # tags in a live preview is the worse answer wherever it can be
            # avoided.
            first_error = self._socket.errorString()
            if allow_any_port and self._socket.bind(QHostAddress("127.0.0.1"), 0):
                logger.warning(
                    "Telemetry port %d is taken (%s); listening on %d instead",
                    rx_port, first_error, self._socket.localPort(),
                )
            else:
                logger.error(
                    "Could not bind telemetry port %d (%s); UI will run offline",
                    rx_port, first_error,
                )
        self._socket.readyRead.connect(self._read_pending_datagrams)

        #: The port actually bound, which is not always the one asked for.
        #: 0 means nothing is listening and the engine is permanently offline.
        self.rx_port = self._socket.localPort()

        # Declares the link dead if it fires before a frame restarts it.
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._on_watchdog_timeout)
        self._watchdog.start()

        # Keeps our subscription alive at the daemon.
        self._sub_timer = QTimer(self)
        self._sub_timer.setInterval(SUBSCRIBE_INTERVAL_MS)
        self._sub_timer.timeout.connect(self._subscribe_to_daemon)
        self._sub_timer.start()

        self._subscribe_to_daemon()


    # ---------------------------------------------------------------- exposure

    def tagMap(self) -> QQmlPropertyMap:
        """Returns the map to publish to QML as the `Tags` context property."""
        return self._map

    # Same object, reachable from QML as Bus.tags for completeness.
    tags = Property(QQmlPropertyMap, tagMap, constant=True)

    def get_online(self) -> bool:
        """Returns True while telemetry is arriving within the watchdog window."""
        return self._online

    def set_online(self, state: bool) -> None:
        """
        Updates link state, notifying QML only on an actual transition.

        Args:
            state: the new link state.
        """
        if self._online != state:
            self._online = state
            # Keep the map's mirror in step so `Tags.online` bindings update.
            self._map.insert("online", state)
            self.onlineChanged.emit()

    # True while the daemon's telemetry is flowing; drives the "link lost" UI.
    online = Property(bool, get_online, set_online, notify=onlineChanged)

    def get_rx_errors(self) -> int:
        """Returns the cumulative count of rejected datagrams."""
        return self._rx_errors

    def _count_rx_error(self) -> None:
        """Increment the rejected-datagram counter and notify QML.

        Every ingress rejection goes through here so no path can bump the
        counter without emitting the change signal.
        """
        self._rx_errors += 1
        self.rxErrorsChanged.emit()

    # Diagnostics counter, exposed read-only for status screens.
    #
    # NOT constant: it was declared `constant=True` while incrementing on every
    # rejected datagram, which tells QML never to re-evaluate the binding. A
    # status screen bound to Bus.rxErrors showed 0 for ever, which is worse
    # than not exposing it at all.
    rxErrors = Property(int, get_rx_errors, notify=rxErrorsChanged)

    # ---------------------------------------------------------------- ingress

    def _read_pending_datagrams(self) -> None:
        """
        Drains the socket and dispatches each datagram.

        No exception may escape this method: it is the process's entire ingress
        surface, and a raise here would tear down the UI (CONTRACT section 7).
        """
        while self._socket.hasPendingDatagrams():
            size = self._socket.pendingDatagramSize()

            # Oversized frames are drained (so the socket does not stall) and
            # discarded without being parsed.
            if size > MAX_DATAGRAM_BYTES:
                self._socket.readDatagram(size)
                self._count_rx_error()
                continue

            datagram, _sender_host, _sender_port = self._socket.readDatagram(size)

            try:
                msg = json.loads(bytes(datagram).decode("utf-8"))
                if not isinstance(msg, dict):
                    self._count_rx_error()
                    continue

                kind = msg.get("t")
                if kind == "tags":
                    self._handle_telemetry(msg)
                elif kind == "ack":
                    self._handle_ack(msg)
                else:
                    # Foreign traffic on our port; counted, not fatal.
                    self._count_rx_error()
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._count_rx_error()
            except Exception as exc:  # noqa: BLE001 - deliberate catch-all
                logger.debug("Unhandled error processing datagram: %s", exc)
                self._count_rx_error()

    def _handle_telemetry(self, msg: dict) -> None:
        """
        Applies one telemetry frame to the map, history, and alarm engine.

        Args:
            msg: parsed frame, expected to carry a "tags" object (CONTRACT 2.4).

        Side effects: restarts the watchdog, updates history buffers,
        evaluates alarms, and notifies QML on state changes.
        """
        tags = msg.get("tags")
        if not isinstance(tags, dict):
            self._count_rx_error()
            return

        self.set_online(True)
        self._watchdog.start()  # restart: a frame arrived

        for tag, value in tags.items():
            if not isinstance(tag, str):
                continue
            alias = tag.replace(".", "_")
            # Learn tags the manifest did not declare, so an app can still bind
            # to anything the daemon happens to publish.
            self._alias_to_tag.setdefault(alias, tag)
            # Only write when the value actually moved. QQmlPropertyMap.insert
            # emits a change notification unconditionally, so writing every tag
            # under both spellings on every frame re-evaluated every binding in
            # the running app 10 times a second -- on a panel where most tags
            # are a digital input that changes once an hour.
            if self._map.value(tag) != value:
                self._map.insert(tag, value)
                self._map.insert(alias, value)

        # -- record history for tracked tags ------------------------------------
        # Record numeric values (bool -> 0/1) for every tag that appears in
        # the frame AND is tracked (expected_tags + alarm_tags).
        for tag in self._recorded_tags:
            raw = tags.get(tag)
            if raw is None:
                # null means a failed hardware read; skip the buffer.
                continue
            if isinstance(raw, bool):
                raw = 1 if raw else 0
            if isinstance(raw, (int, float)):
                buf = self._history.get(tag)
                if buf is not None:
                    buf.append(raw)

        # -- evaluate alarms --------------------------------------------------
        self._evaluate_alarms(tags)

        # -- bump history version (after buffers updated, before alarm notify) --
        self._history_version += 1
        self.historyVersionChanged.emit()

    def _handle_ack(self, msg: dict) -> None:
        """
        Re-emits a command acknowledgement as a Qt signal and dispatches
        any pending correlation handlers.

        Args:
            msg: parsed ack frame (CONTRACT 2.3).
        """
        cid = str(msg.get("id", ""))
        ok = bool(msg.get("ok", False))
        err = str(msg.get("err", ""))
        tags_list = msg.get("tags", [])

        # Fire pending correlation handlers before the general signal,
        # so a blocking slot can grab the result and return.
        handler = self._pending_acks.pop(cid, None)
        if handler is not None:
            handler(cid, ok, err, tags_list)

        self.ackReceived.emit(cid, ok, err)

    def _on_watchdog_timeout(self) -> None:
        """Declares the link lost after WATCHDOG_INTERVAL_MS without a frame."""
        self.set_online(False)

    # ---------------------------------------------------------------- history
    # History and alarm state live on the TagEngine (Bus), not on the QQmlPropertyMap
    # (Tags), because they are derived state that does not belong in the value map
    # (see the module docstring).

    def get_history_version(self) -> int:
        """Returns the current history version, incremented once per frame."""
        return self._history_version

    historyVersion = Property(int, get_history_version, notify=historyVersionChanged)

    @Slot(str, int, result="QVariantList")
    def history(self, tag: str, n: int = 100) -> list:
        """
        Returns the last <= n samples for a tracked tag, oldest first.

        Implements CONTRACT C3: `Bus.history(tag, n)`.

        Args:
            tag: dotted or underscored tag name.
            n: number of samples to return (default 100).

        Returns:
            A list of numeric samples, oldest first. Empty list for an
            unknown tag or one that has never received a value.
        """
        tag = self._to_wire_name(tag)
        buf = self._history.get(tag)
        if buf is None:
            return []
        items = list(buf)
        # deque is already in chronological order (oldest first, maxlen capped)
        if len(items) > n:
            items = items[-n:]
        return list(items)

    # ---------------------------------------------------------------- alarms
    # CONTRACT C2 + C3: manifest-driven alarm evaluation on every telemetry
    # frame. Hysteresis is out of scope (see CONTRACT 9).

    def _threshold_fired(self, value: float, op: str, threshold: float) -> bool:
        """Evaluate a single threshold against a value.

        Args:
            value: the current tag value (numeric).
            op: one of >, >=, <, <=, ==, !=.
            threshold: the threshold value.

        Returns:
            True when the condition is met.
        """
        if op == ">":
            return value > threshold
        elif op == ">=":
            return value >= threshold
        elif op == "<":
            return value < threshold
        elif op == "<=":
            return value <= threshold
        elif op == "==":
            return value == threshold
        elif op == "!=":
            return value != threshold
        return False

    def _evaluate_alarms(self, tags: dict) -> None:
        """Evaluate all alarm definitions against the current tag values.

        Args:
            tags: the tag values dict from the current telemetry frame.

        Side effects: updates _active_alarms and emits activeAlarmsChanged
        when the list actually changed (activation, severity change, clear,
        acknowledge).
        """
        if not self._alarm_defs:
            return

        # Determine which alarm tags have a current value.
        current_values: dict[str, Any] = {}
        for adef in self._alarm_defs:
            if not isinstance(adef, dict):
                continue
            tag = adef.get("tag")
            if not isinstance(tag, str):
                continue
            raw = tags.get(tag)
            current_values[tag] = raw

        # Build the set of alarms that should be active based on thresholds.
        # Track: tag -> {"severity": "critical"|"warning", ...}
        newly_active: dict[str, dict] = {}
        changed = False

        for adef in self._alarm_defs:
            if not isinstance(adef, dict):
                continue
            tag = adef.get("tag")
            if not isinstance(tag, str):
                continue
            value = current_values.get(tag)

            # null value -> alarm inactive (failed read is a link problem)
            if value is None:
                continue

            # Determine highest severity. Critical takes priority.
            severity = None

            # Check critical first
            critical = adef.get("critical")
            if isinstance(critical, dict):
                op = critical.get("op")
                val = critical.get("value")
                if isinstance(op, str) and isinstance(val, (int, float)) and value is not None:
                    if self._threshold_fired(float(value), op, float(val)):
                        severity = "critical"

            # Check warning (only if critical didn't fire)
            if severity is None:
                warning = adef.get("warning")
                if isinstance(warning, dict):
                    op = warning.get("op")
                    val = warning.get("value")
                    if isinstance(op, str) and isinstance(val, (int, float)) and value is not None:
                        if self._threshold_fired(float(value), op, float(val)):
                            severity = "warning"

            if severity is not None:
                # Build alarm item
                label = adef.get("label", tag)
                unit = adef.get("unit", "")
                message = f"{label} {value:g}{unit}"

                existing = self._active_alarms.get(tag)
                if existing is not None:
                    # Still active. It stays in the list whether or not the
                    # severity moved -- an alarm that merely persisted used
                    # to be dropped here and re-raised on the next frame, so
                    # the table flickered at the telemetry rate.
                    if existing["severity"] != severity:
                        existing["severity"] = severity
                        existing["value"] = value
                        existing["message"] = message
                        # Timestamp and acknowledged survive an escalation.
                        changed = True
                    newly_active[tag] = existing
                else:
                    # New alarm
                    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    newly_active[tag] = {
                        "tag": tag,
                        "label": label,
                        "severity": severity,
                        "value": value,
                        "message": message,
                        "timestamp": now,
                        "acknowledged": False,
                    }
                    changed = True

        # Determine which existing alarms are now cleared
        for tag in list(self._active_alarms.keys()):
            if tag not in newly_active:
                del self._active_alarms[tag]
                changed = True

        # Update with newly active/changed alarms
        self._active_alarms.update(newly_active)

        # Emit only when the list changed: the shell and any alarm table are
        # bound to it, and a frame that changed nothing must not repaint them.
        if changed:
            self.activeAlarmsChanged.emit()

    def get_active_alarms(self) -> list:
        """Returns the list of active alarms, sorted critical first then newest.

        Returns:
            A list of alarm dicts, sorted critical-first then by timestamp
            descending (newest first within severity group).
        """
        alarms = list(self._active_alarms.values())
        alarms.sort(key=lambda a: (0 if a["severity"] == "critical" else 1,
                                   a.get("timestamp", "")),
                    reverse=False)
        # critical first (0), then warning (1). Within same severity, newest first.
        alarms.sort(key=lambda a: (0 if a["severity"] == "critical" else 1))
        # Now within each severity group, reverse by timestamp (newest first)
        critical = [a for a in alarms if a["severity"] == "critical"]
        warning = [a for a in alarms if a["severity"] == "warning"]
        critical.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
        warning.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
        return critical + warning

    def get_alarm_count(self) -> int:
        """Returns the count of active alarms."""
        return len(self._active_alarms)

    activeAlarms = Property("QVariantList", get_active_alarms, notify=activeAlarmsChanged)
    alarmCount = Property(int, get_alarm_count, notify=activeAlarmsChanged)

    @Slot(str)
    def acknowledge(self, tag: str) -> None:
        """
        Marks an alarm as acknowledged until it clears.

        Implements CONTRACT C3: `Bus.acknowledge(tag)`. A re-activation
        creates a new, unacknowledged alarm entry.

        Args:
            tag: dotted or underscored tag name of the alarm to acknowledge.
        """
        tag = self._to_wire_name(tag)
        alarm = self._active_alarms.get(tag)
        if alarm is not None:
            alarm["acknowledged"] = True
            self.activeAlarmsChanged.emit()

    # ---------------------------------------------------------------- egress

    def _subscribe_to_daemon(self) -> None:
        """Re-asserts our telemetry subscription so the daemon keeps streaming."""
        self._send_command({"cmd": "subscribe", "ttl": SUBSCRIBE_TTL_S})

    def _next_id(self) -> str:
        """Return a fresh correlation id for an outgoing command.

        Returns:
            A short opaque string, well inside the 64-character limit
            CONTRACT 2.2 puts on the field.
        """
        self._cmd_seq += 1
        return "gui-%d" % self._cmd_seq

    def _send_command(self, cmd: dict) -> None:
        """
        Serialises and sends one command datagram.

        Args:
            cmd: command object per CONTRACT 2.2.

        A send failure (daemon down, socket unbound) is logged at debug level
        and swallowed: the UI must stay responsive with no daemon present.
        """
        try:
            payload = json.dumps(cmd).encode("utf-8")
            self._socket.writeDatagram(
                QByteArray(payload), self._daemon_addr, self._daemon_port
            )
        except Exception as exc:  # noqa: BLE001 - never let the UI die on I/O
            logger.debug("Failed to send command %s: %s", cmd.get("cmd"), exc)

    @Slot(str, "QVariant")
    def write(self, tag: str, value: Any) -> None:
        """
        Sets a writable tag (CONTRACT 2.2 `set`).

        Args:
            tag: dotted or underscored tag name; underscored aliases are
                translated back to the wire form automatically.
            value: bool/int/float. The daemon validates and may reject with
                `bad_value`; the local map is not optimistically updated, so
                the UI always reflects the hardware's actual read-back.
        """
        self._send_command({
            "id": self._next_id(),
            "cmd": "set",
            "tag": self._to_wire_name(tag),
            "value": value,
        })

    @Slot(str, int)
    def pulse(self, tag: str, ms: int) -> None:
        """
        Drives an output active for a bounded time (CONTRACT 2.2 `pulse`).

        Args:
            tag: dotted or underscored output tag name.
            ms: pulse width in milliseconds, 1..10000 as enforced by the daemon.
        """
        self._send_command({
            "id": self._next_id(),
            "cmd": "pulse",
            "tag": self._to_wire_name(tag),
            "ms": ms,
        })

    @Slot(str)
    def uart_tx(self, data: str) -> None:
        """
        Transmits a string on the daemon's serial link (CONTRACT 2.2 `uart_tx`).

        Without this slot the daemon's UART feature is unreachable from QML:
        an app could see `uart.rx` and `uart.last` arriving but had no way to
        send anything back.

        Args:
            data: payload to write, including any line terminator the device
                expects (the daemon does not append one). Keep it inside the
                8192-byte datagram limit.
        """
        self._send_command({"id": self._next_id(), "cmd": "uart_tx", "data": data})

    @Slot()
    def ping(self) -> None:
        """
        Sends a liveness probe (CONTRACT 2.2 `ping`).

        The reply arrives as an ack, so a screen wanting a synchronous-looking
        result should watch `ackReceived`. Routine link state is already exposed
        as `online`; this exists for diagnostic screens that want to force a
        round trip on demand.
        """
        self._send_command({"cmd": "ping", "id": "qml-ping"})

    @Slot(str, result="QVariant")
    @Slot(str, "QVariant", result="QVariant")
    def value(self, name: str, fallback: Any = None) -> Any:
        """
        Reads a tag defensively.

        This is how apps should read anything they are not certain exists: an
        undeployed sensor, an optional feature, a tag the daemon has not
        published yet. It never raises and never returns a QML error.

        Args:
            name: dotted or underscored tag name.
            fallback: returned when the tag is unknown or currently null.

        Returns:
            The tag's value, or `fallback`.
        """
        val = self._map.value(name)
        if val is None:
            val = self._map.value(name.replace(".", "_"))
        return fallback if val is None else val

    @Slot(result="QVariantList")
    def list_tags(self) -> list:
        """
        Requests the daemon's full tag catalogue (CONTRACT 2.2 `list`).

        Sends the command with a correlation id and blocks (briefly) on a
        local event-loop until the ack arrives, so a QML caller can use the
        returned list directly:

            var names = Bus.list_tags()

        Returns:
            A ``QVariantList`` of tag-name strings, or an empty list if the
            link is offline or the daemon does not respond within 2 s.
        """
        loop = QEventLoop()
        result: list = []

        def _handler(cid_: str, ok: bool, err: str, tags_list: list) -> None:
            if ok:
                result.extend(tags_list)
            loop.quit()

        cid = self._next_id()
        self._pending_acks[cid] = _handler
        self._send_command({"cmd": "list", "id": cid})

        QTimer.singleShot(2000, loop.quit)
        loop.exec()

        self._pending_acks.pop(cid, None)
        self.listReceived.emit(result)
        return result

    @Slot()
    def unsubscribe(self) -> None:
        """
        Removes this client from the daemon's telemetry sink list
        (CONTRACT 2.2 `unsubscribe`).

        The daemon stops streaming to this client after the ack arrives.
        A screen that no longer needs telemetry (e.g. about-to-close) should
        call this so the daemon's subscriber table does not leak addresses.
        """
        loop = QEventLoop()

        def _handler(cid_: str, ok: bool, err: str, tags_list: list) -> None:
            if ok:
                self.unsubscribed.emit()
            loop.quit()

        cid = self._next_id()
        self._pending_acks[cid] = _handler
        self._send_command({"cmd": "unsubscribe", "id": cid})

        QTimer.singleShot(2000, loop.quit)
        loop.exec()

        self._pending_acks.pop(cid, None)

    def _to_wire_name(self, name: str) -> str:
        """
        Normalises a tag name to the dotted wire form.

        Args:
            name: dotted ("do.relay1") or underscored ("do_relay1") name.

        Returns:
            The dotted name the daemon expects. Unknown underscored names are
            passed through unchanged so the daemon can reject them explicitly
            with `unknown_tag` rather than failing silently here.
        """
        if "." in name:
            return name
        return self._alias_to_tag.get(name, name)


# ---------------------------------------------------------------------------
# The Bus the application actually sees
#
# A QML binding such as ``value: Bus.value("ai.pot", 0)`` is only re-evaluated
# when something it *read through the QML engine* changes. Calling a Python
# slot reads nothing the engine can see: the slot looks the value up inside
# Python, returns it, and the binding is never touched again -- so every
# gauge bound that way showed its first value for ever, while ``Tags.ai_pot``
# beside it moved. The fix is to let the read happen in QML: ``Bus`` is a
# small QML object whose ``value()`` indexes ``Tags`` inside the caller's own
# binding, which the engine captures like any property read, and whose every
# other member forwards to the engine below it (``BusImpl``). The source lives
# here, not in a .qml file, so the panel image, a Studio checkout and the
# packaged Studio all carry it without an install step.
# ---------------------------------------------------------------------------
BUS_QML = b"""
import QtQuick 2.15

QtObject {
    id: bus

    // Live state, forwarded as bindable properties.
    readonly property bool online: BusImpl.online
    readonly property int rxErrors: BusImpl.rxErrors
    readonly property int historyVersion: BusImpl.historyVersion
    readonly property var activeAlarms: BusImpl.activeAlarms
    readonly property int alarmCount: BusImpl.alarmCount

    // Signals an app may connect to, re-emitted from the engine.
    signal ackReceived(string id, bool ok, string err)
    signal listReceived(var tags)
    signal unsubscribed()
    property var _forward: Connections {
        target: BusImpl
        function onAckReceived(id, ok, err) { bus.ackReceived(id, ok, err) }
        function onListReceived(tags) { bus.listReceived(tags) }
        function onUnsubscribed() { bus.unsubscribed() }
    }

    // A tag read that the binding calling it depends on. Dotted and
    // underscored names both work (CONTRACT 2.5); a missing or null tag
    // yields the fallback, never an error.
    function value(name, fallback) {
        var v = Tags[name]
        if (v === undefined || v === null) v = Tags[name.replace(/\\./g, "_")]
        if (v === undefined || v === null) return fallback === undefined ? null : fallback
        return v
    }

    function write(tag, value) { BusImpl.write(tag, value) }
    function pulse(tag, ms) { BusImpl.pulse(tag, ms) }
    function uart_tx(data) { BusImpl.uart_tx(data) }
    function ping() { BusImpl.ping() }
    function list_tags() { return BusImpl.list_tags() }
    function unsubscribe() { BusImpl.unsubscribe() }
    function history(tag, n) { return BusImpl.history(tag, n === undefined ? 100 : n) }
    function acknowledge(tag) { BusImpl.acknowledge(tag) }
}
"""


def expose_to_qml(engine, context, tag_engine):
    """
    Installs ``Tags``, ``BusImpl`` and ``Bus`` on a QML context.

    Args:
        engine:     the QQmlEngine the context belongs to (creates the shim).
        context:    the QQmlContext to populate (usually engine.rootContext()).
        tag_engine: the TagEngine instance.

    Returns:
        The object bound as ``Bus``: the QML shim, or the engine itself if
        the shim failed to build -- the app then keeps commands and one-shot
        reads and loses only live re-evaluation, which is logged, rather
        than losing its UI.

    Side effects: sets three context properties; parents the shim to the
    engine so it lives exactly as long as the tags do.
    """
    context.setContextProperty("Tags", tag_engine.tagMap())
    context.setContextProperty("BusImpl", tag_engine)
    component = QQmlComponent(engine)
    component.setData(QByteArray(BUS_QML), "")
    bus = component.create(context)
    if bus is None:
        logger.error("Bus shim failed to build; bindings on Bus.value() will not update: %s",
                     "; ".join(e.toString() for e in component.errors()))
        bus = tag_engine
    else:
        bus.setParent(tag_engine)
    context.setContextProperty("Bus", bus)
    return bus
