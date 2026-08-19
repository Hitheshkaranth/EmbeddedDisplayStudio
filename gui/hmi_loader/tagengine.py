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

import json
import logging
from typing import Any

from PySide6.QtCore import QByteArray, QObject, Property, QTimer, Signal, Slot
from PySide6.QtNetwork import QHostAddress, QUdpSocket
from PySide6.QtQml import QQmlPropertyMap

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

    def __init__(
        self,
        expected_tags: list[str],
        rx_port: int = 5001,
        daemon_host: str = "127.0.0.1",
        daemon_port: int = 5000,
        parent: QObject = None,
    ) -> None:
        """
        Args:
            expected_tags: dotted tag names the loaded app declares in its
                manifest (`tags_required`). Each is pre-seeded into the map as
                None so QML bindings resolve on the very first frame instead of
                erroring on an unknown property (CONTRACT section 7).
            rx_port: UDP port to bind for telemetry, 1..65535. Must match the
                daemon's configured static sink (default 5001).
            daemon_host: address of the command socket. Loopback only by
                design; the daemon does not listen off-box.
            daemon_port: the daemon's command port, 1..65535 (default 5000).
            parent: owning QObject, or None.

        Raises:
            Nothing. A failed socket bind is logged and leaves the engine
            permanently offline rather than taking the UI down with it.
        """
        super().__init__(parent)

        # Current link state. False until the first valid frame arrives.
        self._online = False

        # Cumulative count of datagrams rejected for any reason. Surfaced for
        # diagnostics; a climbing value means something is spraying the port.
        self._rx_errors = 0

        # Where commands are sent.
        self._daemon_addr = QHostAddress(daemon_host)
        self._daemon_port = daemon_port

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

        self._socket = QUdpSocket(self)
        if not self._socket.bind(QHostAddress("127.0.0.1"), rx_port):
            # A bind failure is usually a second GUI instance already running.
            # Degrade to permanently-offline instead of aborting startup.
            logger.error(
                "Could not bind telemetry port %d (%s); UI will run offline",
                rx_port, self._socket.errorString(),
            )
        self._socket.readyRead.connect(self._read_pending_datagrams)

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

    # Diagnostics counter, exposed read-only for status screens.
    rxErrors = Property(int, get_rx_errors, constant=True)

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
                self._rx_errors += 1
                continue

            datagram, _sender_host, _sender_port = self._socket.readDatagram(size)

            try:
                msg = json.loads(bytes(datagram).decode("utf-8"))
                if not isinstance(msg, dict):
                    self._rx_errors += 1
                    continue

                kind = msg.get("t")
                if kind == "tags":
                    self._handle_telemetry(msg)
                elif kind == "ack":
                    self._handle_ack(msg)
                else:
                    # Foreign traffic on our port; counted, not fatal.
                    self._rx_errors += 1
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._rx_errors += 1
            except Exception as exc:  # noqa: BLE001 - deliberate catch-all
                logger.debug("Unhandled error processing datagram: %s", exc)
                self._rx_errors += 1

    def _handle_telemetry(self, msg: dict) -> None:
        """
        Applies one telemetry frame to the map.

        Args:
            msg: parsed frame, expected to carry a "tags" object (CONTRACT 2.4).

        Side effects: restarts the watchdog and may flip `online`.
        """
        tags = msg.get("tags")
        if not isinstance(tags, dict):
            self._rx_errors += 1
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
            self._map.insert(tag, value)
            self._map.insert(alias, value)

    def _handle_ack(self, msg: dict) -> None:
        """
        Re-emits a command acknowledgement as a Qt signal.

        Args:
            msg: parsed ack frame (CONTRACT 2.3).
        """
        self.ackReceived.emit(
            str(msg.get("id", "")),
            bool(msg.get("ok", False)),
            str(msg.get("err", "")),
        )

    def _on_watchdog_timeout(self) -> None:
        """Declares the link lost after WATCHDOG_INTERVAL_MS without a frame."""
        self.set_online(False)

    # ---------------------------------------------------------------- egress

    def _subscribe_to_daemon(self) -> None:
        """Re-asserts our telemetry subscription so the daemon keeps streaming."""
        self._send_command({"cmd": "subscribe", "ttl": SUBSCRIBE_TTL_S})

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
        self._send_command({"cmd": "set", "tag": self._to_wire_name(tag), "value": value})

    @Slot(str, int)
    def pulse(self, tag: str, ms: int) -> None:
        """
        Drives an output active for a bounded time (CONTRACT 2.2 `pulse`).

        Args:
            tag: dotted or underscored output tag name.
            ms: pulse width in milliseconds, 1..10000 as enforced by the daemon.
        """
        self._send_command({"cmd": "pulse", "tag": self._to_wire_name(tag), "ms": ms})

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
        self._send_command({"cmd": "uart_tx", "data": data})

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
