"""The C hardware daemon end to end (docs/CONTRACT.md sections 2 and 14).

Runs only with HMI_HWD_CMD set to the built binary (Linux):

    HMI_HWD_CMD=native/hmi-hwd/out/hmi-hwd python3 -m unittest tests.test_hwd_native

The protocol itself is pinned by tests/test_daemon_protocol.py, which runs
against the C daemon under the same variable; this file covers what the
Python daemon never had: discovery, --modbus-live against a real Modbus TCP
server, Modbus RTU and a USB-style serial port over pseudo-terminals, enum
registers, and CAN when a vcan interface exists.
"""
import json
import os
import pty
import shlex
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tty
import unittest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import hwd_cmd  # noqa: E402

NATIVE = hwd_cmd.native()


def free_port(kind=socket.SOCK_DGRAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class FakePlc:
    """A Modbus slave's memory: coils, discrete inputs, holding and input
    registers, and the writes it received."""

    def __init__(self):
        self.coils = [0] * 64
        self.discrete = [0] * 64
        self.holding = [0] * 256
        self.input = [0] * 256
        self.writes = []

    def pdu(self, fc, body):
        if fc in (1, 2):
            addr, count = struct.unpack(">HH", body[:4])
            bits = (self.coils if fc == 1 else self.discrete)[addr:addr + count]
            out = bytearray((count + 7) // 8)
            for i, bit in enumerate(bits):
                if bit:
                    out[i // 8] |= 1 << (i % 8)
            return bytes([fc, len(out)]) + bytes(out)
        if fc in (3, 4):
            addr, count = struct.unpack(">HH", body[:4])
            regs = (self.holding if fc == 3 else self.input)[addr:addr + count]
            return bytes([fc, 2 * count]) + b"".join(struct.pack(">H", r) for r in regs)
        if fc == 5:
            addr, value = struct.unpack(">HH", body[:4])
            self.coils[addr] = 1 if value == 0xFF00 else 0
            self.writes.append(("coil", addr, self.coils[addr]))
            return bytes([fc]) + body[:4]
        if fc == 6:
            addr, value = struct.unpack(">HH", body[:4])
            self.holding[addr] = value
            self.writes.append(("holding", addr, value))
            return bytes([fc]) + body[:4]
        if fc == 16:
            addr, count, nbytes = struct.unpack(">HHB", body[:5])
            for i in range(count):
                self.holding[addr + i] = struct.unpack(">H", body[5 + 2 * i:7 + 2 * i])[0]
            self.writes.append(("holding", addr, list(self.holding[addr:addr + count])))
            return bytes([fc]) + body[:4]
        return bytes([fc | 0x80, 1])


class TcpPlc(threading.Thread):
    def __init__(self, plc):
        super().__init__(daemon=True)
        self.plc = plc
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.running = True

    def run(self):
        self.sock.settimeout(0.2)
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        conn.settimeout(0.5)
        with conn:
            while self.running:
                try:
                    head = conn.recv(7)
                    if len(head) < 7:
                        return
                    tid, _proto, length, unit = struct.unpack(">HHHB", head)
                    body = b""
                    while len(body) < length - 1:
                        body += conn.recv(length - 1 - len(body))
                except OSError:
                    if not self.running:
                        return
                    continue
                reply = self.plc.pdu(body[0], body[1:])
                conn.sendall(struct.pack(">HHHB", tid, 0, len(reply) + 1, unit) + reply)

    def stop(self):
        self.running = False
        self.sock.close()


class Daemon:
    """The C daemon on a temporary hwd.json, with a socket on its sink."""

    def __init__(self, test, config, extra=(), fail=()):
        self.dir = tempfile.TemporaryDirectory()
        test.addCleanup(self.dir.cleanup)
        self.cmd_port, self.sink_port = free_port(), free_port()
        config.setdefault("daemon", {})
        config["daemon"].update({"cmd_port": self.cmd_port, "poll_interval_ms": 50,
                                 "telemetry_sink": f"127.0.0.1:{self.sink_port}"})
        config["daemon"].setdefault("discovery", False)
        config.setdefault("gpio", {"chip": "/dev/gpiochip3"})
        self.path = os.path.join(self.dir.name, "hwd.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        self.sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sink.bind(("127.0.0.1", self.sink_port))
        self.sink.settimeout(1.0)
        test.addCleanup(self.sink.close)
        argv, env = hwd_cmd.command(self.path, extra=extra, fail=fail)
        self.proc = subprocess.Popen(argv, env=env)
        test.addCleanup(self.stop)
        self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd.settimeout(1.0)
        test.addCleanup(self.cmd.close)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def frame_where(self, pred, timeout=5.0):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                data, _ = self.sink.recvfrom(65536)
            except OSError:
                continue
            last = json.loads(data)
            if last.get("t") == "tags" and pred(last["tags"]):
                return last
        return last

    def send(self, msg, want_reply=True):
        self.cmd.sendto(json.dumps(msg).encode(), ("127.0.0.1", self.cmd_port))
        if not want_reply:
            return None
        end = time.time() + 3.0
        while time.time() < end:
            try:
                data, _ = self.cmd.recvfrom(65536)
            except OSError:
                continue
            reply = json.loads(data)
            if reply.get("id") == msg.get("id"):
                return reply
        return None


@unittest.skipUnless(NATIVE, "set HMI_HWD_CMD to the C daemon to run")
class Lifecycle(unittest.TestCase):
    def test_selftest_prints_one_frame_and_exits(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hwd.json")
            with open(path, "w") as fh:
                json.dump({"daemon": {}, "gpio": {"chip": "/dev/gpiochip3",
                           "outputs": {"do.relay1": {"offset": 1}}}}, fh)
            argv, env = hwd_cmd.command(path, extra=["--selftest"])
            out = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        frame = json.loads(lines[0])
        self.assertEqual(frame["t"], "tags")
        self.assertIn("do.relay1", frame["tags"])
        self.assertIn("sys.uptime", frame["tags"])

    def test_sigterm_exits_zero_and_quickly(self):
        d = Daemon(self, {})
        self.assertIsNotNone(d.frame_where(lambda t: True))
        t0 = time.time()
        d.proc.send_signal(signal.SIGTERM)
        self.assertEqual(d.proc.wait(timeout=3), 0)
        self.assertLess(time.time() - t0, 2.0)

    def test_sim_and_strict_are_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hwd.json")
            with open(path, "w") as fh:
                json.dump({"daemon": {}, "gpio": {}}, fh)
            argv, env = hwd_cmd.command(path, extra=["--strict"])
            out = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(out.returncode, 0)

    def test_a_bad_config_exits_one(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hwd.json")
            with open(path, "w") as fh:
                json.dump({"daemon": {"poll_interval_ms": 0}, "gpio": {}}, fh)
            argv, env = hwd_cmd.command(path)
            out = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 1)


@unittest.skipUnless(NATIVE, "set HMI_HWD_CMD to the C daemon to run")
class Discovery(unittest.TestCase):
    def test_a_discover_is_answered_with_a_hello(self):
        port = free_port()
        d = Daemon(self, {"daemon": {"discovery": True, "discovery_port": port}})
        d.frame_where(lambda t: True)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2.0)
        self.addCleanup(s.close)
        s.sendto(json.dumps({"cmd": "discover"}).encode(), ("127.0.0.1", port))
        hello = json.loads(s.recvfrom(4096)[0])
        self.assertEqual(hello["t"], "hello")
        self.assertEqual(hello["cmd_port"], d.cmd_port)
        self.assertEqual(hello["hwd"], "0.2.0")
        self.assertIn("host", hello)
        self.assertGreaterEqual(hello["tags"], 2)


@unittest.skipUnless(NATIVE, "set HMI_HWD_CMD to the C daemon to run")
class ModbusTcp(unittest.TestCase):
    def setUp(self):
        self.plc = FakePlc()
        self.plc.holding[100] = 0xFFF6            # int16 -10 -> -1.0 with scale 0.1
        self.plc.input[10] = 2                    # enum index
        self.plc.input[20:22] = [0x3FC0, 0x0000]  # float32 1.5
        self.plc.coils[0] = 1
        self.server = TcpPlc(self.plc)
        self.server.start()
        self.addCleanup(self.server.stop)
        cfg = {"modbus": {"host": "127.0.0.1", "port": self.server.port, "unit_id": 1,
                          "poll_interval_ms": 100, "reconnect_s": 0.5, "timeout_s": 0.5,
                          "tags": {
                              "mb.temp": {"kind": "holding", "address": 100, "type": "int16",
                                          "scale": 0.1, "writable": True},
                              "mb.next_station": {"kind": "input", "address": 10, "type": "uint16",
                                                  "enum": ["Hosahalli", "Vijayanagar", "Attiguppe"]},
                              "mb.speed": {"kind": "input", "address": 20, "type": "float32"},
                              "mb.run": {"kind": "coil", "address": 0, "type": "bool", "writable": True},
                              "mb.station_cmd": {"kind": "holding", "address": 30, "type": "uint16",
                                                 "writable": True, "enum": ["A", "B", "C"]}}}}
        self.d = Daemon(self, cfg, extra=["--modbus-live"])

    def test_registers_are_read_with_scale_type_and_enum(self):
        f = self.d.frame_where(lambda t: t.get("sys.modbus_online") is True and t.get("mb.speed") is not None)
        self.assertIsNotNone(f)
        tags = f["tags"]
        self.assertAlmostEqual(tags["mb.temp"], -1.0, places=6)
        self.assertEqual(tags["mb.next_station"], "Attiguppe")
        self.assertAlmostEqual(tags["mb.speed"], 1.5, places=6)
        self.assertIs(tags["mb.run"], True)

    def test_writes_reach_the_plc(self):
        self.d.frame_where(lambda t: t.get("sys.modbus_online") is True)
        r = self.d.send({"id": "w1", "cmd": "set", "tag": "mb.run", "value": False})
        self.assertTrue(r and r["ok"], r)
        r = self.d.send({"id": "w2", "cmd": "set", "tag": "mb.temp", "value": 2.5})
        self.assertTrue(r and r["ok"], r)
        r = self.d.send({"id": "w3", "cmd": "set", "tag": "mb.station_cmd", "value": "C"})
        self.assertTrue(r and r["ok"], r)
        r = self.d.send({"id": "w4", "cmd": "set", "tag": "mb.speed", "value": 1})
        self.assertEqual(r and r.get("err"), "not_writable")
        self.assertEqual(self.plc.coils[0], 0)
        self.assertEqual(self.plc.holding[100], 25)        # 2.5 / 0.1
        self.assertEqual(self.plc.holding[30], 2)          # "C" is index 2

    def test_a_lost_plc_reads_null_and_comes_back(self):
        self.d.frame_where(lambda t: t.get("sys.modbus_online") is True)
        self.server.stop()
        f = self.d.frame_where(lambda t: t.get("sys.modbus_online") is False, timeout=6)
        self.assertIsNotNone(f)
        self.assertIsNone(f["tags"]["mb.temp"])
        self.assertEqual(f.get("q", {}).get("mb.temp"), "bad")


@unittest.skipUnless(NATIVE, "set HMI_HWD_CMD to the C daemon to run")
class ModbusRtuAndSerial(unittest.TestCase):
    def _pty(self):
        master, slave = pty.openpty()
        tty.setraw(master)
        tty.setraw(slave)
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        return master, os.ttyname(slave)

    def test_rtu_slave_over_a_serial_line(self):
        master, name = self._pty()
        plc = FakePlc()
        plc.input[0] = 235                         # 23.5 with scale 0.1
        stop = threading.Event()

        def slave():
            buf = b""
            while not stop.is_set():
                try:
                    buf += os.read(master, 256)
                except OSError:
                    return
                while len(buf) >= 8:
                    frame, buf = buf[:8], buf[8:]
                    unit, fc = frame[0], frame[1]
                    if crc16(frame[:6]) != struct.unpack("<H", frame[6:8])[0]:
                        buf = b""
                        break
                    reply = bytes([unit]) + plc.pdu(fc, frame[2:6])
                    os.write(master, reply + struct.pack("<H", crc16(reply)))

        threading.Thread(target=slave, daemon=True).start()
        self.addCleanup(stop.set)
        d = Daemon(self, {"modbus_rtu": {"path": name, "baudrate": 19200, "parity": "N",
                                         "poll_interval_ms": 100, "timeout_s": 0.3,
                                         "tags": {"mb.rtu.temp": {"unit": 3, "kind": "input",
                                                                  "address": 0, "type": "int16",
                                                                  "scale": 0.1}}}},
                   extra=["--modbus-live"])
        f = d.frame_where(lambda t: t.get("mb.rtu.temp") is not None, timeout=6)
        self.assertIsNotNone(f)
        self.assertAlmostEqual(f["tags"]["mb.rtu.temp"], 23.5, places=6)
        self.assertIs(f["tags"].get("sys.modbus_rtu_online"), True)

    def test_a_serial_port_publishes_lines_and_sends(self):
        master, name = self._pty()
        d = Daemon(self, {"serial": {"ports": {"scan": {"path": name, "baudrate": 9600,
                                                        "eol": "\r\n"}}}})
        d.frame_where(lambda t: t.get("serial.scan.present") is True)
        os.write(master, b"P-412\r\n")
        f = d.frame_where(lambda t: t.get("serial.scan.rx") == "P-412")
        self.assertIsNotNone(f)
        self.assertEqual(f["tags"]["serial.scan.rx_count"], 1)
        r = d.send({"id": "tx", "cmd": "serial_tx", "port": "scan", "data": "ACK\r\n"})
        self.assertTrue(r and r["ok"], r)
        time.sleep(0.2)
        self.assertEqual(os.read(master, 64), b"ACK\r\n")


def _vcan():
    return os.path.exists("/sys/class/net/vcan0")


@unittest.skipUnless(NATIVE and _vcan(), "needs HMI_HWD_CMD and a vcan0 interface")
class Can(unittest.TestCase):
    def test_a_frame_updates_its_signal_and_a_write_sends_one(self):
        d = Daemon(self, {"can": {"interface": "vcan0", "signals": {
            "can.motor.rpm": {"id": "0x123", "start_bit": 0, "length": 16, "scale": 0.25},
            "can.motor.enable": {"id": "0x200", "start_bit": 0, "length": 1, "writable": True}}}})
        s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        s.bind(("vcan0",))
        s.settimeout(2.0)
        self.addCleanup(s.close)
        d.frame_where(lambda t: t.get("sys.can_online") is True)
        s.send(struct.pack("=IB3x8s", 0x123, 2, bytes([0x10, 0x27]) + bytes(6)))   # 10000 * 0.25
        f = d.frame_where(lambda t: t.get("can.motor.rpm") == 2500.0)
        self.assertIsNotNone(f)
        r = d.send({"id": "c1", "cmd": "set", "tag": "can.motor.enable", "value": True})
        self.assertTrue(r and r["ok"], r)
        end = time.time() + 2
        while time.time() < end:
            can_id, _dlc, data = struct.unpack("=IB3x8s", s.recv(16))
            if can_id == 0x200:
                self.assertEqual(data[0] & 1, 1)
                return
        self.fail("no 0x200 frame")


if __name__ == "__main__":
    unittest.main()
