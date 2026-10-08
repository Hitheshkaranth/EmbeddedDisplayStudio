#!/usr/bin/env python3
"""plc_sim.py -- a Modbus TCP slave for the Studio's "Test against PLC".

    python3 daemon/plc_sim.py --config hwd.json [--host 127.0.0.1] [--port 1502]

Serves every tag of the config's "modbus" section (docs/CONTRACT.md 2.5):
read-only tags ramp inside a plausible range (0..100 in engineering units,
mapped back through scale/offset; enum tags step through their entries,
bits toggle), writable tags hold what was last written. Accepts FC 1/2/3/4
reads and FC 5/6/15/16 writes, answers any unit id, and prints one line per
write. Start hmi-hwd with --sim --modbus-live and point "modbus.host/port"
here. Standard library only.
"""
import argparse
import json
import socketserver
import struct
import sys
import threading
import time

PERIOD_S = 20.0
KINDS = ("coil", "discrete", "holding", "input")
LIMITS = {"int16": (-32768, 32767), "uint16": (0, 65535),
          "int32": (-(1 << 31), (1 << 31) - 1), "uint32": (0, (1 << 32) - 1)}


def words(raw, type_name, word_order):
    """Raw number -> list of 16-bit registers, as hmi-hwd decodes them."""
    if type_name not in ("int32", "uint32", "float32"):
        return [int(raw) & 0xFFFF]
    w = struct.unpack(">I", struct.pack(">f", raw))[0] if type_name == "float32" else int(raw) & 0xFFFFFFFF
    return [w & 0xFFFF, w >> 16] if word_order == "little" else [w >> 16, w & 0xFFFF]


class Plc:
    def __init__(self, tags):
        self.lock = threading.Lock()
        self.held = {k: {} for k in KINDS}   # written values: address -> int
        self.owner = {k: {} for k in KINDS}  # address -> (name, cfg, word index, ramp shift)
        self.t0 = time.monotonic()
        self.count = 0
        for i, (name, cfg) in enumerate(sorted(tags.items())):
            kind = cfg.get("kind", "holding")
            if kind in KINDS:
                n = 2 if cfg.get("type") in ("int32", "uint32", "float32") else 1
                for k in range(n):
                    self.owner[kind][int(cfg.get("address", 0)) + k] = (name, cfg, k, i * 1.7)
                self.count += 1

    def ramp_raw(self, cfg, shift):
        """The read-only value of a tag now, as a raw (unscaled) number."""
        t = time.monotonic() - self.t0 + shift
        ttype = cfg.get("type", "bool")
        if cfg.get("kind") in ("coil", "discrete"):
            return 1 if (t % 6.0) < 3.0 else 0
        if cfg.get("enum"):
            return int(t / 4.0) % len(cfg["enum"])
        phase = (t % PERIOD_S) / PERIOD_S            # triangle 0..100..0 (engineering units)
        eng = 200.0 * (phase if phase < 0.5 else 1 - phase)
        raw = (eng - cfg.get("offset", 0)) / (cfg.get("scale", 1) or 1)
        if ttype == "float32":
            return raw
        lo, hi = LIMITS.get(ttype, (0, 65535))
        return max(lo, min(hi, int(round(raw))))

    def read(self, kind, addr):
        with self.lock:
            if addr in self.held[kind]:
                return self.held[kind][addr]
            own = self.owner[kind].get(addr)
        if own is None:
            return 0
        _name, cfg, k, shift = own
        raw = self.ramp_raw(cfg, shift)
        if kind in ("coil", "discrete"):
            return raw
        return words(raw, cfg.get("type"), cfg.get("word_order", "big"))[k]

    def write(self, kind, addr, values):
        with self.lock:
            for i, v in enumerate(values):
                self.held[kind][addr + i] = v
        own = self.owner[kind].get(addr)
        label = " (%s = %s)" % (own[0], self.engineering(kind, addr, own[1])) if own else ""
        print("write %s %d = %s%s" % (kind, addr, values[0] if len(values) == 1 else values, label), flush=True)

    def engineering(self, kind, addr, cfg):
        """A written value as the panel will publish it (scale/offset/enum)."""
        if kind == "coil":
            return bool(self.held[kind].get(addr, 0))
        ttype = cfg.get("type")
        regs = [self.held[kind].get(addr + i, 0) for i in range(2)]
        if cfg.get("word_order") == "little":
            regs.reverse()
        w = (regs[0] << 16) | regs[1]
        fmt = {"float32": ">f", "int32": ">i", "uint32": ">I"}.get(ttype)
        if fmt:
            raw = struct.unpack(fmt, struct.pack(">I", w))[0]
        else:
            raw = struct.unpack(">h" if ttype == "int16" else ">H", struct.pack(">H", self.held[kind].get(addr, 0)))[0]
        enum = cfg.get("enum")
        if enum and 0 <= raw < len(enum):
            return enum[int(raw)]
        return round(raw * cfg.get("scale", 1) + cfg.get("offset", 0), 6)

    def pdu(self, fc, body):
        if fc in (1, 2, 3, 4):
            addr, count = struct.unpack(">HH", body[:4])
            if not 1 <= count <= (2000 if fc <= 2 else 125) or addr + count > 65536:
                return bytes([fc | 0x80, 3 if not count else 2])
            kind = KINDS[fc - 1]
            vals = [self.read(kind, addr + i) for i in range(count)]
            if fc <= 2:
                out = bytearray((count + 7) // 8)
                for i, b in enumerate(vals):
                    if b:
                        out[i // 8] |= 1 << (i % 8)
                return bytes([fc, len(out)]) + bytes(out)
            return bytes([fc, 2 * count]) + b"".join(struct.pack(">H", v & 0xFFFF) for v in vals)
        if fc == 5:
            addr, value = struct.unpack(">HH", body[:4])
            if value not in (0, 0xFF00):
                return bytes([fc | 0x80, 3])
            self.write("coil", addr, [1 if value else 0])
            return bytes([fc]) + body[:4]
        if fc == 6:
            addr, value = struct.unpack(">HH", body[:4])
            self.write("holding", addr, [value])
            return bytes([fc]) + body[:4]
        if fc in (15, 16):
            addr, count, nbytes = struct.unpack(">HHB", body[:5])
            data = body[5:5 + nbytes]
            if fc == 16:
                vals = [struct.unpack(">H", data[2 * i:2 * i + 2])[0] for i in range(count)]
                self.write("holding", addr, vals)
            else:
                vals = [(data[i // 8] >> (i % 8)) & 1 for i in range(count)]
                self.write("coil", addr, vals)
            return bytes([fc]) + body[:4]
        return bytes([fc | 0x80, 1])


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        plc = self.server.plc
        try:
            while True:
                head = self.rfile.read(7)
                if len(head) < 7:
                    return
                tid, proto, length, unit = struct.unpack(">HHHB", head)
                body = self.rfile.read(length - 1) if length > 1 else b""
                if proto != 0 or not body or len(body) < length - 1:
                    return
                try:
                    reply = plc.pdu(body[0], body[1:])
                except (struct.error, IndexError):
                    reply = bytes([body[0] | 0x80, 3])
                self.request.sendall(struct.pack(">HHHB", tid, 0, len(reply) + 1, unit) + reply)
        except OSError:
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Modbus TCP slave serving hwd.json's modbus tags")
    ap.add_argument("--config", required=True, help="hwd.json")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1502)
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    tags = (cfg.get("modbus") or {}).get("tags") or {}
    if not tags:
        print("plc_sim: no modbus tags in %s" % args.config, file=sys.stderr)
    server = Server((args.host, args.port), Handler)
    server.plc = Plc(tags)
    print("plc_sim: %d tag(s) on %s:%d" % (server.plc.count, args.host, server.server_address[1]), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
