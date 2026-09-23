"""tagsim: does the bench panel read like one aeroplane on one flight?

The simulator has one job -- take a deployed design and fly it -- and three
ways to get it wrong: contradict itself (nose down while the altimeter
climbs), sweep a needle off the dial it is drawn on, or drift away from the
kit's real scales. All three are tested here.
"""
import json
import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daemon import tagsim

DURATION = 240.0


def _project(widgets):
    return {"pages": [{"id": "main", "widgets": widgets}]}


def _widget(wtype, wid, bindings, properties=None, children=None):
    w = {"type": wtype, "id": wid, "bindings": bindings,
         "properties": properties or {}}
    if children is not None:
        w["widgets"] = children
    return w


def _samples(step=1.0):
    t = 0.0
    while t < DURATION:
        yield t, tagsim.state_at(t, DURATION)
        t += step


class FlightTests(unittest.TestCase):
    """One aeroplane, and every instrument agreeing about it."""

    def test_it_leaves_the_ground_and_comes_back(self):
        altitudes = [s["altitude"] for _, s in _samples()]
        self.assertAlmostEqual(altitudes[0], 0.0, places=3)
        self.assertGreater(max(altitudes), 30000)
        self.assertAlmostEqual(tagsim.state_at(DURATION, DURATION)["altitude"],
                               0.0, places=3)

    def test_the_nose_agrees_with_the_altimeter(self):
        # Wherever the aeroplane is climbing hard, the pitch is up; wherever
        # it is descending, the pitch is down. A screen that disagrees with
        # itself is the whole thing this replaces.
        # Thresholds are set past the transitions, where the nose is on its
        # way through level and either sign is right.
        for t, state in _samples(0.5):
            if state["vertical_speed"] > 500:
                self.assertGreater(state["pitch"], 0, "climbing nose-down at %.0fs" % t)
            elif state["vertical_speed"] < -1000:
                self.assertLess(state["pitch"], 0, "descending nose-up at %.0fs" % t)

    def test_the_vertical_speed_is_the_altimeter_moving(self):
        for t, state in _samples(2.0):
            ahead = tagsim.state_at(t + 2.0, DURATION)
            if t + 2.0 >= DURATION:
                continue
            climbed = ahead["altitude"] - state["altitude"]
            if abs(state["vertical_speed"]) > 800:
                self.assertEqual(climbed > 0, state["vertical_speed"] > 0,
                                 "vs and altitude disagree at %.0fs" % t)

    def test_the_wing_is_down_only_in_the_turn(self):
        for t, state in _samples(1.0):
            ahead = tagsim.state_at(t + 1.0, DURATION)
            turn = ahead["heading"] - state["heading"]
            if abs(turn) < 0.01:
                self.assertLess(abs(state["roll"]), 0.5,
                                "banked %.1f deg on a straight leg at %.0fs"
                                % (state["roll"], t))
            elif abs(turn) > 0.5:
                self.assertEqual(state["roll"] > 0, turn > 0,
                                 "banked the wrong way at %.0fs" % t)

    def test_the_bank_never_exceeds_the_limit(self):
        for _, state in _samples(0.5):
            self.assertLessEqual(abs(state["roll"]), tagsim.BANK_LIMIT + 1e-6)

    def test_fuel_only_ever_falls(self):
        previous = None
        for _, state in _samples(1.0):
            if previous is not None:
                self.assertLessEqual(state["fuel_left"], previous + 1e-9)
            previous = state["fuel_left"]
        self.assertLess(tagsim.state_at(DURATION * 0.99, DURATION)["fuel_left"],
                        tagsim.FUEL_FULL)

    def test_the_distance_flown_never_goes_backwards(self):
        previous = -1.0
        for _, state in _samples(1.0):
            self.assertGreaterEqual(state["distance"], previous - 1e-9)
            previous = state["distance"]

    def test_the_hot_end_follows_the_thrust(self):
        for _, state in _samples(2.0):
            self.assertEqual(state["n1"] > 80, state["egt"] > 695)

    def test_it_gets_colder_as_it_climbs(self):
        low = tagsim.state_at(DURATION * 0.02, DURATION)
        high = tagsim.state_at(DURATION * 0.45, DURATION)
        self.assertGreater(low["oat"], high["oat"])

    def test_the_gear_is_down_for_the_ground_and_up_for_the_cruise(self):
        self.assertTrue(tagsim.state_at(0.0, DURATION)["gear_down"])
        self.assertFalse(tagsim.state_at(DURATION * 0.45, DURATION)["gear_down"])
        self.assertTrue(tagsim.state_at(DURATION * 0.97, DURATION)["gear_down"])

    def test_the_next_flight_is_the_same_flight(self):
        first = tagsim.state_at(30.0, DURATION)
        second = tagsim.state_at(30.0 + DURATION, DURATION)
        for key, value in first.items():
            if isinstance(value, float):
                self.assertAlmostEqual(value, second[key], places=6, msg=key)

    def test_the_same_second_always_looks_the_same(self):
        self.assertEqual(tagsim.state_at(77.0, DURATION),
                         tagsim.state_at(77.0, DURATION))


class PlanTests(unittest.TestCase):
    def test_every_bound_tag_gets_a_signal(self):
        project = _project([
            _widget("ShGauge", "g", {"value": {"tag": "eng1.egt"}}),
            _widget("ShAttitude", "a", {"pitch": {"tag": "nav.pitch"},
                                        "roll": {"tag": "nav.roll"}}),
        ])
        self.assertEqual(sorted(tagsim.plan(project)),
                         ["eng1.egt", "nav.pitch", "nav.roll"])

    def test_the_alarm_table_wildcard_is_not_a_value(self):
        project = _project([_widget("ShAlarmTable", "t", {"alarms": {"tag": "*"}})])
        self.assertEqual(tagsim.plan(project), {})

    def test_tags_inside_containers_are_found(self):
        project = _project([
            _widget("ShCard", "card", {}, children=[
                _widget("ShGauge", "g", {"value": {"tag": "deep.value"}})]),
        ])
        self.assertIn("deep.value", tagsim.plan(project))

    def test_a_plain_string_binding_is_a_tag_too(self):
        project = _project([_widget("ShGauge", "g", {"value": "short.form"})])
        self.assertIn("short.form", tagsim.plan(project))


class QuantityTests(unittest.TestCase):
    def test_a_tag_reports_what_its_name_measures(self):
        for tag, expected in (("alt.current", "altitude"),
                              ("vsi.rate", "vertical_speed"),
                              ("nav.heading", "heading"),
                              ("nav.mach", "mach"),
                              ("eng1.n1", "n1"),
                              ("eng1.egt", "egt"),
                              ("env.oat", "oat"),
                              ("nav.trip_dist", "distance")):
            with self.subTest(tag=tag):
                self.assertEqual(tagsim.quantity_for(tag, "value"), expected)

    def test_the_two_tanks_are_told_apart(self):
        self.assertEqual(tagsim.quantity_for("fuel.left.qty", "value"), "fuel_left")
        self.assertEqual(tagsim.quantity_for("fuel.right.qty", "value"), "fuel_right")

    def test_the_attitude_properties_name_themselves(self):
        self.assertEqual(tagsim.quantity_for("anything.at.all", "pitch"), "pitch")
        self.assertEqual(tagsim.quantity_for("anything.at.all", "roll"), "roll")

    def test_an_unknown_tag_still_rides_along_with_the_flight(self):
        self.assertEqual(tagsim.quantity_for("who.knows", "value"), "progress")


class ScaleTests(unittest.TestCase):
    def test_the_design_scale_beats_every_default(self):
        sig = tagsim.signal_for("alt.current", "ShTape", "value",
                                {"minimumValue": 0.0, "maximumValue": 40000.0})
        self.assertEqual((sig.lo, sig.hi), (0.0, 40000.0))

    def test_the_kit_scale_beats_the_quantity(self):
        # A tape drawn 0..250 is swept 0..250 even by an altitude: a needle
        # pegged past the end of its scale reads as broken, not as flying.
        sig = tagsim.signal_for("alt.current", "ShTape", "value", {})
        self.assertEqual((sig.lo, sig.hi), (0.0, 250.0))

    def test_a_needle_never_leaves_its_dial(self):
        sig = tagsim.signal_for("alt.current", "ShTape", "value", {})
        for t, state in _samples(0.5):
            value = sig.at(dict(state, engaged_true=True))
            self.assertGreaterEqual(value, sig.lo)
            self.assertLessEqual(value, sig.hi)

    def test_a_full_scale_tape_reads_real_feet(self):
        sig = tagsim.signal_for("alt.current", "ShTape", "value",
                                {"minimumValue": 0.0, "maximumValue": 38000.0})
        cruise = dict(tagsim.state_at(DURATION * 0.45, DURATION), engaged_true=True)
        self.assertAlmostEqual(sig.at(cruise), 37000.0, delta=200.0)

    def test_lamps_are_lamps(self):
        self.assertEqual(tagsim.signal_for("a.b", "ShStatDot", "value", {}).kind, "bool")
        self.assertEqual(tagsim.signal_for("a.b", "ShTelltale", "value", {}).kind, "bool")

    def test_a_healthy_lamp_is_lit_and_a_fault_lamp_is_not(self):
        state = dict(tagsim.state_at(60.0, DURATION), engaged_true=True)
        healthy = tagsim.signal_for("sys.elec_ok", "ShStatDot", "value", {})
        fault = tagsim.signal_for("sys.fire_detected", "ShTelltale", "value", {})
        self.assertTrue(healthy.at(state))
        self.assertFalse(fault.at(state))

    def test_the_gear_lamp_follows_the_gear(self):
        sig = tagsim.signal_for("gear.warning", "ShTelltale", "value", {})
        self.assertTrue(sig.at(dict(tagsim.state_at(0.0, DURATION), engaged_true=True)))
        self.assertFalse(sig.at(dict(tagsim.state_at(DURATION * 0.45, DURATION),
                                     engaged_true=True)))

    def test_the_type_table_still_matches_the_kit(self):
        """The panel has no registry to ask, so the table is a copy.

        A kit change that moves a scale must move this table with it, or
        the bench sweeps a needle off its dial.
        """
        try:
            sys.path.insert(0, os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
            from designer.palette.widget_registry import default_registry
        except Exception as exc:                       # pragma: no cover
            self.skipTest("designer package not importable here: %s" % exc)
        registry = {d.type: dict(getattr(d, "defaults", {}) or {})
                    for d in default_registry().definitions()}
        for wtype, ranges in tagsim.TYPE_RANGES.items():
            defaults = registry.get(wtype)
            if defaults is None:
                continue
            stated = tagsim._explicit_range(defaults, "value")
            if stated is None:
                continue                # the kit gives no scale; ours is a choice
            with self.subTest(widget=wtype):
                self.assertEqual(stated, ranges.get("value"),
                                 "%s moved in the kit but not in tagsim" % wtype)


class ScreenTests(unittest.TestCase):
    """The whole panel, moving together."""

    def setUp(self):
        self.signals = tagsim.plan(_project([
            _widget("ShTape", "alt", {"value": {"tag": "alt.current"}}),
            _widget("ShVSI", "vsi", {"value": {"tag": "vsi.rate"}}),
            _widget("ShAttitude", "att", {"pitch": {"tag": "nav.pitch"},
                                          "roll": {"tag": "nav.roll"}}),
            _widget("ShEngineBar", "n1", {"value": {"tag": "eng1.n1"}}),
            _widget("ShNumDisplay", "hdg", {"value": {"tag": "nav.heading"}}),
        ]))

    def test_the_screen_changes_from_second_to_second(self):
        first = tagsim.values_at(self.signals, 20.0, DURATION)
        later = tagsim.values_at(self.signals, 26.0, DURATION)
        self.assertNotEqual(first, later)

    def test_altitude_and_vertical_speed_move_as_one(self):
        climb = 0.11 * DURATION
        before = tagsim.values_at(self.signals, climb, DURATION)
        after = tagsim.values_at(self.signals, climb + 5.0, DURATION)
        self.assertGreater(after["alt.current"], before["alt.current"])
        self.assertGreater(after["vsi.rate"], 0)
        self.assertGreater(after["nav.pitch"], 0)


class FrameTests(unittest.TestCase):
    def test_a_frame_is_what_the_runtime_expects(self):
        signals = {"alt.current": tagsim.signal_for("alt.current", "ShTape", "value", {})}
        payload = json.loads(tagsim.frame(signals, 1.0, 7, DURATION).decode("utf-8"))
        self.assertEqual(payload["t"], "tags")
        self.assertEqual(payload["seq"], 7)
        self.assertEqual(payload["src"], "tagsim")
        self.assertIn("alt.current", payload["tags"])

    def test_a_whole_panel_fits_in_one_datagram(self):
        # The runtime drops anything over 8192 bytes (tags.h).
        signals = {"tag.number%03d" % i:
                   tagsim.signal_for("tag.number%03d" % i, "ShGauge", "value", {})
                   for i in range(120)}
        self.assertLess(len(tagsim.frame(signals, 3.0, 1, DURATION)), 8192)


class ServeTests(unittest.TestCase):
    def test_a_subscriber_is_answered_and_then_flown(self):
        # N1, not altitude: the flight starts on the ground, where the
        # altimeter is legitimately still.
        signals = {"eng1.n1": tagsim.signal_for("eng1.n1", "ShEngineBar", "value", {})}
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.bind(("127.0.0.1", 0))
        client.settimeout(3.0)
        port = _free_port()
        thread = threading.Thread(
            target=tagsim.serve,
            args=(signals, port, 40.0, "127.0.0.1", 2.0, 20.0), daemon=True)
        thread.start()
        time.sleep(0.3)
        try:
            client.sendto(json.dumps({"cmd": "subscribe", "ttl": 5}).encode(),
                          ("127.0.0.1", port))
            seen = []
            for _ in range(4):
                data, _addr = client.recvfrom(8192)
                seen.append(json.loads(data.decode("utf-8")))
            self.assertTrue(all(f["t"] == "tags" for f in seen))
            values = [f["tags"]["eng1.n1"] for f in seen]
            self.assertGreater(len(set(values)), 1, "the panel is not moving")
        finally:
            client.close()
            thread.join(timeout=4)

    def test_a_command_from_the_glass_is_acknowledged(self):
        signals = {"alt.current": tagsim.signal_for("alt.current", "ShTape", "value", {})}
        port = _free_port()
        thread = threading.Thread(
            target=tagsim.serve,
            args=(signals, port, 20.0, "127.0.0.1", 2.0, 60.0), daemon=True)
        thread.start()
        time.sleep(0.3)
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(3.0)
        try:
            client.sendto(json.dumps({"cmd": "ping", "id": "qml-ping"}).encode(),
                          ("127.0.0.1", port))
            while True:
                data, _ = client.recvfrom(8192)
                msg = json.loads(data.decode("utf-8"))
                if msg.get("t") == "ack":
                    break
            self.assertTrue(msg["ok"])
            self.assertEqual(msg["id"], "qml-ping")
        finally:
            client.close()
            thread.join(timeout=4)


def _free_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


if __name__ == "__main__":
    unittest.main()
