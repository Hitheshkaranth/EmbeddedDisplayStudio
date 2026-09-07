"""
sim_publisher.py  -  ci-test_1smoke live-data simulator
========================================================

Publishes sinusoidal tag values to the HMI TagEngine over UDP loopback
at 10 Hz, mimicking the wire protocol used by the real hmi-hwd daemon
(CONTRACT section 2).

Usage:
    python sim_publisher.py                    # default RX port 5001
    python sim_publisher.py --rx-port 5002     # if loader is on another port

The TagEngine in the GUI loader listens on UDP 127.0.0.1:5001 by default.
This script sends {"t": "tags", "tags": {...}} datagrams to that port.

Run this in a second terminal AFTER the Studio preview / GUI loader is open.
"""
import argparse
import json
import math
import socket
import time

# ---------------------------------------------------------------------------
# Tag table: (tag_name, lo, hi, phase_offset_rad)
# Values sweep: lo + (hi-lo) * (0.5 + 0.5*sin(t + phase))
# ---------------------------------------------------------------------------
TAGS = [
    # Flight dynamics
    ("sim.pitch",          -20.0,   20.0,  0.00),
    ("sim.roll",           -30.0,   30.0,  1.10),
    ("sim.ias",             60.0,  200.0,  0.40),
    ("sim.ground_speed",    80.0,  180.0,  0.30),
    ("sim.altitude",      1000.0, 5000.0,  0.70),
    ("sim.heading",          0.0,  359.0,  0.60),
    ("sim.heading_bug",      0.0,  359.0,  0.90),
    ("sim.vsi",          -1500.0, 1500.0,  1.20),
    # Flight director
    ("sim.fd_pitch",       -10.0,   10.0,  0.20),
    ("sim.fd_roll",        -15.0,   15.0,  0.80),
    # Turn coordinator
    ("sim.turn_rate",       -3.0,    3.0,  0.50),
    ("sim.slip",            -1.0,    1.0,  1.70),
    # Engines
    ("sim.n1_eng1",         50.0,   95.0,  0.00),
    ("sim.n1_eng2",         50.0,   95.0,  0.70),
    ("sim.oil_press_eng1",  20.0,   80.0,  0.00),
    ("sim.oil_press_eng2",  20.0,   80.0,  1.50),
    ("sim.oil_temp_eng1",   30.0,   90.0,  0.50),
    ("sim.oil_temp_eng2",   30.0,   90.0,  1.00),
    # Fuel
    ("sim.fuel_left",       10.0,   90.0,  0.00),
    ("sim.fuel_right",      10.0,   90.0,  0.40),
    ("sim.fuel2_left",       5.0,   80.0,  1.00),
    ("sim.fuel2_right",      5.0,   80.0,  1.60),
    # Environment
    ("sim.oat",            -20.0,   40.0,  2.00),
    ("sim.wind_speed",       0.0,   50.0,  1.30),
    ("sim.baro",            29.50,  30.50, 0.90),
]

LOW_FUEL_THRESHOLD = 25.0


def osc(lo, hi, t, phase):
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(t + phase))


def build_frame(t):
    tags = {}
    for name, lo, hi, phase in TAGS:
        tags[name] = round(osc(lo, hi, t, phase), 4)
    tags["sim.low_fuel"] = tags["sim.fuel_left"] < LOW_FUEL_THRESHOLD
    return json.dumps({"t": "tags", "tags": tags}, separators=(",", ":")).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Smoke-app live-data UDP simulator")
    parser.add_argument("--rx-port", type=int, default=5001,
                        help="UDP port the HMI loader listens on (default: 5001)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--rate", type=float, default=10.0,
                        help="Publish rate Hz (default: 10)")
    args = parser.parse_args()

    interval = 1.0 / args.rate
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"[sim] Publishing {len(TAGS)+1} tags -> {args.host}:{args.rx_port} "
          f"at {args.rate:.0f} Hz  (Ctrl-C to stop)")

    t0 = time.monotonic()
    try:
        while True:
            t = time.monotonic() - t0
            sock.sendto(build_frame(t), (args.host, args.rx_port))
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[sim] Stopped.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
