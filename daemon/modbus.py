"""
modbus.py -- Modbus TCP client and simulator (stdlib only)
==========================================================

Layer 1 (hardware daemon). Implements the `mb.` tag family of CONTRACT 2.5.

Installed beside hmi_hwd.py as /usr/lib/hmi/modbus.py by both
deploy/provision_panel.py and the hmi-core Yocto recipe; the daemon is run
as a script, so its own directory is on sys.path and `import modbus`
resolves there. Standard library only, like everything on the panel.

Reads/Writes:
    MBAP header, function codes 1/2/3/4/5/6/16.
    Value types: int16, uint16, int32, uint32, float32, bool.
    32-bit word order: big or little endian.
    Scale/offset applied on read (raw -> engineering) and inverted on write.

ModbusSim:
    In-memory register/coil map with identical read/write interface.
    Used by --sim and by tests.
"""

import struct
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# ModbusError -- exception for protocol-level failures
# ---------------------------------------------------------------------------

class ModbusError(Exception):
    """Raised when the Modbus device returns an exception response.

    Attributes:
        code:  Modbus exception code (1=illegal_function, 2=illegal_address,
               3=illegal_value, 4=slave_device_failure).
    """
    def __init__(self, code: int) -> None:
        self.code = code
        labels = {1: "illegal_function", 2: "illegal_address",
                  3: "illegal_value", 4: "slave_device_failure"}
        super().__init__("Modbus exception %d (%s)" % (code, labels.get(code, "unknown")))


# ---------------------------------------------------------------------------
# MBAP header helpers
# ---------------------------------------------------------------------------

def _build_header(transaction_id: int, unit_id: int, function_code: int,
                  payload: bytes) -> bytes:
    """Build a complete Modbus TCP PDU (MBAP header + PDU).

    Args:
        transaction_id:  2-byte transaction ID (echoed by server).
        unit_id:         Modbus unit/slave ID.
        function_code:   Function code (FC).
        payload:         FC-specific data bytes.

    Returns:
        Bytes suitable for transmission over TCP.
    """
    mbap = struct.pack(">HHH", transaction_id, 0, 5 + len(payload))
    return mbap + struct.pack(">BB", unit_id, function_code) + payload


def _parse_header(data: bytes) -> Tuple[int, int, int]:
    """Parse the MBAP header and return transaction_id, unit_id, protocol_id.

    Args:
        data: received bytes (at least 8 bytes).

    Returns:
        (transaction_id, unit_id, protocol_id).

    Raises:
        ModbusError: if the protocol ID is not 0 (not Modbus TCP).
    """
    if len(data) < 6:
        raise ModbusError(4)  # slave_device_failure (garbage)
    transaction_id, protocol_id, length = struct.unpack(">HHH", data[:6])
    if protocol_id != 0:
        raise ModbusError(1)  # illegal_function
    unit_id = data[6] if len(data) > 6 else 0
    return transaction_id, unit_id, length


# ---------------------------------------------------------------------------
# Value encoding / decoding
# ---------------------------------------------------------------------------

# Mapping of type name -> struct format char(s) and byte count.
_TYPE_INFO: Dict[str, Tuple[str, int]] = {
    "int16":    (">h",  2),
    "uint16":   (">H",  2),
    "int32":    (">i",  4),
    "uint32":   (">I",  4),
    "float32":  (">f",  4),
    "bool":     ("",     1),  # handled specially (coil: 0x00/0xFF)
}


def encode_value(raw: int, type_name: str) -> bytes:
    """Pack a raw integer into protocol bytes.

    Args:
        raw: the raw register value (signed or unsigned).
        type_name: one of the supported types.

    Returns:
        Big-endian bytes.

    Raises:
        KeyError: if type_name is unknown.
    """
    if type_name == "bool":
        return b"\xFF" if raw else b"\x00"
    if type_name not in _TYPE_INFO:
        raise KeyError("Unknown type: %s" % type_name)
    fmt, _ = _TYPE_INFO[type_name]
    # Clamp to the signed range for signed types, or unsigned range otherwise.
    if type_name == "int16":
        raw = max(-(1 << 15), min(raw, (1 << 15) - 1))
    elif type_name == "int32":
        raw = max(-(1 << 31), min(raw, (1 << 31) - 1))
    elif type_name == "uint32":
        raw = max(0, min(raw, (1 << 32) - 1))
    elif type_name == "uint16":
        raw = max(0, min(raw, (1 << 16) - 1))
    return struct.pack(fmt, raw)


def decode_value(data: bytes, type_name: str, word_order: str = "big") -> int:
    """Decode protocol bytes into a raw integer.

    Args:
        data:       1/2/4 byte payload (may be extended for word_order).
        type_name:  one of the supported types.
        word_order: for 32-bit types, byte ordering within the register block.

    Returns:
        Raw integer value.
    """
    if type_name == "bool":
        return 1 if data and data[0] != 0 else 0
    if type_name in ("int16", "uint16"):
        fmt, _ = _TYPE_INFO[type_name]
        return struct.unpack(fmt, data[:2])[0]
    # 32-bit types with word_order: the protocol returns 4 bytes.
    if type_name in ("int32", "uint32", "float32"):
        raw_bytes = data[:4]
        if word_order == "little":
            # Reverse all bytes for little-endian 32-bit
            raw_bytes = raw_bytes[::-1]
        fmt, _ = _TYPE_INFO[type_name]
        return struct.unpack(fmt, raw_bytes)[0]
    raise ValueError("Unknown type: %s" % type_name)


def scale_read(raw: int, type_name: str, scale: float, offset: float) -> Any:
    """Convert a raw value to engineering units.

    Args:
        raw:     raw integer from the device.
        type_name: type (float32 is returned as-is scaled).
        scale:   multiplier applied to the raw value.
        offset:  value added after scaling.

    Returns:
        Float engineering value.
    """
    if type_name == "float32":
        return raw * scale + offset
    return raw * scale + offset


def scale_write(eng_val: Any, type_name: str, scale: float, offset: float) -> int:
    """Convert an engineering value back to a raw register value.

    Args:
        eng_val: engineering value from the client (bool, int, float).
        type_name: type name.
        scale:   scale factor (inverse applied).
        offset:  offset (inverse applied).

    Returns:
        Raw integer suitable for the register.
    """
    if type_name == "bool":
        return 1 if eng_val else 0
    v = float(eng_val)
    v = (v - offset) / scale if scale != 0 else v
    if type_name == "int32":
        return max(-(1 << 31), min(int(round(v)), (1 << 31) - 1))
    if type_name == "uint32":
        return max(0, min(int(round(v)), (1 << 32) - 1))
    if type_name in ("int16",):
        return max(-(1 << 15), min(int(round(v)), (1 << 15) - 1))
    if type_name == "uint16":
        return max(0, min(int(round(v)), (1 << 16) - 1))
    return int(round(v))


# ---------------------------------------------------------------------------
# ModbusTcpClient -- stdlib-only TCP client
# ---------------------------------------------------------------------------

class ModbusTcpClient:
    """Synchronous Modbus TCP client over a plain socket.

    Implements function codes 1, 2, 3, 4, 5, 6, 16.  Connection errors
    mark the link down; no exception escapes read/write operations.

    Attributes:
        online:      True when the most recent connect succeeded.
        last_error:  Last error message string (or None).
    """

    def __init__(self, host: str, port: int = 502, unit_id: int = 1,
                 timeout_s: float = 1.0) -> None:
        """Initialise a Modbus TCP client.

        Args:
            host:      PLC/drive IP address or hostname.
            port:      Modbus TCP port (default 502).
            unit_id:   Modbus unit/slave ID.
            timeout_s: Socket read timeout in seconds.
        """
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout_s = timeout_s
        self.online: bool = False
        self.last_error: Optional[str] = None
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._txn_id: int = 0  # simple counter for transaction IDs

    def _connect(self) -> bool:
        """Establish a TCP connection to the Modbus server.

        Returns:
            True on success.
        """
        try:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout_s)
            s.connect((self.host, self.port))
            self._sock = s
            self.online = True
            self.last_error = None
            return True
        except Exception as exc:
            self.online = False
            self.last_error = str(exc)
            return False

    def _send_recv(self, payload: bytes) -> bytes:
        """Send a request and read the response.

        Args:
            payload: complete MBAP+PDU bytes to send.

        Returns:
            Response bytes.

        Raises:
            ModbusError: if an exception response is received.
            RuntimeError: if the connection fails.
        """
        with self._lock:
            if not self._sock or not self.online:
                if not self._connect():
                    raise RuntimeError(self.last_error or "connect failed")
            try:
                self._sock.sendall(payload)
            except socket.error:
                self.online = False
                self.last_error = "send failed"
                raise RuntimeError("send failed")

            response = b""
            # Modbus TCP response has at least 8 bytes header.
            while len(response) < 8:
                try:
                    chunk = self._sock.recv(8 - len(response))
                    if not chunk:
                        self.online = False
                        self.last_error = "connection closed"
                        raise RuntimeError("connection closed")
                    response += chunk
                except socket.timeout:
                    self.online = False
                    self.last_error = "read timeout"
                    raise RuntimeError("read timeout")

            # Read remaining bytes (length is in byte 4-5 of MBAP header).
            _, _, total_len = _parse_header(response)
            while len(response) < total_len:
                try:
                    chunk = self._sock.recv(min(total_len - len(response), 1024))
                    if not chunk:
                        self.online = False
                        self.last_error = "connection closed"
                        raise RuntimeError("connection closed")
                    response += chunk
                except socket.timeout:
                    self.online = False
                    self.last_error = "read timeout"
                    raise RuntimeError("read timeout")

            self.last_error = None
            return response

    def read_coils(self, address: int, quantity: int) -> bytearray:
        """FC 1: Read coil status.

        Args:
            address:  starting coil address (0-based).
            quantity: number of coils (1-2000).

        Returns:
            bytearray of coil values (0 or 1 per bit).

        Raises:
            ModbusError: if the device returns an exception.
        """
        if quantity < 1 or quantity > 2000:
            raise ModbusError(3)
        header = _build_header(self._next_txn(), self.unit_id, 1,
                               struct.pack(">HH", address, quantity))
        resp = self._send_recv(header)
        return self._check_exception(resp)

    def read_discrete_inputs(self, address: int, quantity: int) -> bytearray:
        """FC 2: Read discrete input status.

        Args:
            address:  starting address (0-based).
            quantity: number of inputs (1-2000).

        Returns:
            bytearray of input values (0 or 1 per bit).
        """
        if quantity < 1 or quantity > 2000:
            raise ModbusError(3)
        header = _build_header(self._next_txn(), self.unit_id, 2,
                               struct.pack(">HH", address, quantity))
        resp = self._send_recv(header)
        return self._check_exception(resp)

    def read_holding_registers(self, address: int, quantity: int) -> bytearray:
        """FC 3: Read holding register values.

        Args:
            address:  starting register address (0-based).
            quantity: number of registers (1-125).

        Returns:
            bytearray of register bytes (2 per register, big-endian).
        """
        if quantity < 1 or quantity > 125:
            raise ModbusError(3)
        header = _build_header(self._next_txn(), self.unit_id, 3,
                               struct.pack(">HH", address, quantity))
        resp = self._send_recv(header)
        return self._check_exception(resp)

    def read_input_registers(self, address: int, quantity: int) -> bytearray:
        """FC 4: Read input register values.

        Args:
            address:  starting register address (0-based).
            quantity: number of registers (1-125).

        Returns:
            bytearray of register bytes (2 per register, big-endian).
        """
        if quantity < 1 or quantity > 125:
            raise ModbusError(3)
        header = _build_header(self._next_txn(), self.unit_id, 4,
                               struct.pack(">HH", address, quantity))
        resp = self._send_recv(header)
        return self._check_exception(resp)

    def write_single_coil(self, address: int, value: int) -> None:
        """FC 5: Write a single coil.

        Args:
            address: coil address (0-based).
            value:   0x00 (OFF) or 0xFF00 (ON).

        Raises:
            ModbusError: on device exception.
        """
        header = _build_header(self._next_txn(), self.unit_id, 5,
                               struct.pack(">HH", address, 0xFF00 if value else 0))
        resp = self._send_recv(header)
        self._check_exception(resp)

    def write_single_register(self, address: int, value: int) -> None:
        """FC 6: Write a single holding register.

        Args:
            address: register address (0-based).
            value:   16-bit value.

        Raises:
            ModbusError: on device exception.
        """
        header = _build_header(self._next_txn(), self.unit_id, 6,
                               struct.pack(">HH", address, value & 0xFFFF))
        resp = self._send_recv(header)
        self._check_exception(resp)

    def write_multiple_registers(self, address: int, values: List[int]) -> None:
        """FC 16: Write multiple holding registers.

        Args:
            address:  starting address (0-based).
            values:   list of 16-bit values (1-121 registers).

        Raises:
            ModbusError: on device exception.
            ValueError: if values exceeds 121 registers.
        """
        if len(values) < 1 or len(values) > 121:
            raise ModbusError(3)
        byte_count = len(values) * 2
        payload = struct.pack(">HHB", address, len(values), byte_count)
        for v in values:
            payload += struct.pack(">H", v & 0xFFFF)
        header = _build_header(self._next_txn(), self.unit_id, 16, payload)
        resp = self._send_recv(header)
        self._check_exception(resp)

    def read_and_write_registers(self, read_address: int, read_count: int,
                                  write_address: int, values: List[int]) -> None:
        """FC 22: Read/Write multiple registers.

        Not required by C6 but available for future use.
        """
        raise NotImplementedError("FC22 not yet implemented")

    def _check_exception(self, resp: bytes) -> bytes:
        """Check for a Modbus exception response and raise if found.

        Args:
            resp: full response including MBAP header.

        Returns:
            The response payload (byte count + data) for normal responses.
        """
        fc = resp[7]  # function code is at byte 7 (MBAP=6 + unit_id=1)
        if fc & 0x80:
            exc_code = resp[8] if len(resp) > 8 else 4
            raise ModbusError(exc_code)
        # Normal response: return data after MBAP(6) + unit_id(1) + FC(1) + byte_count(1)
        return resp[9:]

    def _next_txn(self) -> int:
        """Return the next transaction ID."""
        self._txn_id = (self._txn_id + 1) & 0xFFFF
        return self._txn_id

    def close(self) -> None:
        """Close the TCP connection."""
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None


# ---------------------------------------------------------------------------
# ModbusSim -- in-memory simulator
# ---------------------------------------------------------------------------

class ModbusSim:
    """In-memory Modbus simulator for tests and --sim mode.

    Maintains separate maps for coils, discrete inputs, holding registers,
    and input registers.  Writes are immediately visible to reads.

    Attributes:
        online: always True.
    """

    def __init__(self) -> None:
        """Initialise all maps to empty.
        
        Coils and discrete inputs are booleans.
        Holding and input registers are 16-bit unsigned integers.
        """
        self.coils: Dict[int, bool] = {}
        self.discrete_inputs: Dict[int, bool] = {}
        self.holding_registers: Dict[int, int] = {}
        self.input_registers: Dict[int, int] = {}
        self.online: bool = True
        self.last_error: Optional[str] = None

    def _get_coil(self, address: int) -> bool:
        """Get a coil value, defaulting to False."""
        return self.coils.get(address, False)

    def _set_coil(self, address: int, value: bool) -> None:
        """Set a coil value."""
        self.coils[address] = value

    def _get_discrete(self, address: int) -> bool:
        """Get a discrete input value, defaulting to False."""
        return self.discrete_inputs.get(address, False)

    def _get_holding(self, address: int) -> int:
        """Get a holding register value, defaulting to 0."""
        return self.holding_registers.get(address, 0)

    def _set_holding(self, address: int, value: int) -> None:
        """Set a holding register value."""
        self.holding_registers[address] = value & 0xFFFF

    def _get_input(self, address: int) -> int:
        """Get an input register value, defaulting to 0."""
        return self.input_registers.get(address, 0)

    def read_coils(self, address: int, quantity: int) -> bytearray:
        """FC 1: Read coil status."""
        bits = bytearray()
        for i in range(quantity):
            bits.append(1 if self._get_coil(address + i) else 0)
        return bits

    def read_discrete_inputs(self, address: int, quantity: int) -> bytearray:
        """FC 2: Read discrete input status."""
        bits = bytearray()
        for i in range(quantity):
            bits.append(1 if self._get_discrete(address + i) else 0)
        return bits

    def read_holding_registers(self, address: int, quantity: int) -> bytearray:
        """FC 3: Read holding register values."""
        result = bytearray()
        for i in range(quantity):
            val = self._get_holding(address + i)
            result.extend(struct.pack(">H", val))
        return result

    def read_input_registers(self, address: int, quantity: int) -> bytearray:
        """FC 4: Read input register values."""
        result = bytearray()
        for i in range(quantity):
            val = self._get_input(address + i)
            result.extend(struct.pack(">H", val))
        return result

    def write_single_coil(self, address: int, value: int) -> None:
        """FC 5: Write a single coil."""
        self._set_coil(address, value != 0)

    def write_single_register(self, address: int, value: int) -> None:
        """FC 6: Write a single holding register."""
        self._set_holding(address, value & 0xFFFF)

    def write_multiple_registers(self, address: int, values: List[int]) -> None:
        """FC 16: Write multiple holding registers."""
        for i, v in enumerate(values):
            self._set_holding(address + i, v & 0xFFFF)

    def poll_coils(self, address: int, quantity: int) -> bytearray:
        """Read coils (convenience, mirrors FC 1)."""
        return self.read_coils(address, quantity)

    def poll_holding_registers(self, address: int, quantity: int) -> bytearray:
        """Read holding registers (convenience, mirrors FC 3)."""
        return self.read_holding_registers(address, quantity)

    def poll_input_registers(self, address: int, quantity: int) -> bytearray:
        """Read input registers (convenience, mirrors FC 4)."""
        return self.read_input_registers(address, quantity)

    def poll_discrete_inputs(self, address: int, quantity: int) -> bytearray:
        """Read discrete inputs (convenience, mirrors FC 2)."""
        return self.read_discrete_inputs(address, quantity)

    def set_coil(self, address: int, value: bool) -> None:
        """Directly set a coil (for seeding from config)."""
        self._set_coil(address, value)

    def set_register(self, address: int, value: int) -> None:
        """Directly set a holding register (for seeding from config)."""
        self._set_holding(address, value & 0xFFFF)

    def set_discrete(self, address: int, value: bool) -> None:
        """Directly set a discrete input."""
        self.discrete_inputs[address] = value

    def set_input_register(self, address: int, value: int) -> None:
        """Directly set an input register."""
        self.input_registers[address] = value & 0xFFFF

    def get_coil_map(self) -> Dict[int, bool]:
        """Return the coil map for inspection."""
        return dict(self.coils)

    def get_register_map(self) -> Dict[int, int]:
        """Return the holding register map for inspection."""
        return dict(self.holding_registers)