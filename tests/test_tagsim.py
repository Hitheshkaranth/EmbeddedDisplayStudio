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

    def test_a_metro_cab_reads_like_a_running_train(self):
        project = _project([
            _widget("ShSpeedArc", "s", {"value": {"tag": "mb.train.speed"},
                                        "target": {"tag": "mb.train.target_speed"}},
                    {"maximumValue": 100.0}),
            _widget("ShStationLine", "l", {"current": {"tag": "mb.train.station_index"}}),
            _widget("ShTrainConsist", "c", {"doorsLeft": {"tag": "mb.train.doors_left"},
                                            "doorsRight": {"tag": "mb.train.doors_right"}}),
            _widget("ShStatusCard", "h", {"status": {"tag": "mb.train.hvac_status"}}),
            _widget("ShStatusCard", "p", {"state": {"tag": "mb.train.pea_state"}}),
            _widget("ShProgress", "g", {"value": {"tag": "mb.train.segment_progress"}}),
        ])
        signals = tagsim.plan(project)
        for t, _state in _samples():
            values = tagsim.values_at(signals, t, DURATION)
            self.assertTrue(0 <= values["mb.train.speed"] <= 100)
            self.assertTrue(0 <= values["mb.train.station_index"] <= 3)
            self.assertTrue(0 <= values["mb.train.segment_progress"] <= 1)
            self.assertIn(values["mb.train.doors_left"], ("open", "closed"))
            self.assertEqual(values["mb.train.doors_right"], "disabled")
            self.assertEqual(values["mb.train.hvac_status"], "ACTIVE (21°C)")
            self.assertEqual(values["mb.train.pea_state"], "ok")
            if values["mb.train.speed"] > 0:
                self.assertEqual(values["mb.train.doors_left"], "closed")


class JourneyTests(unittest.TestCase):
    """A cab display describes one train: it gets to the next station."""

    STATIONS = ("Trinity", "Halasuru", "Indiranagar", "Swami Vivekananda Road",
                "Whitefield (Kadugodi)")

    def _cab(self):
        line = _widget("ShStationLine", "line",
                       {"current": {"tag": "train.station_index"},
                        "details": {"tag": "train.station_details"}},
                       {"stations": ",".join(self.STATIONS)})
        texts = [_widget("Text", name, {"text": {"tag": "train." + name}})
                 for name in ("next_station", "eta", "distance_to_go", "clock", "doors")]
        speed = _widget("ShSpeedArc", "arc", {"value": {"tag": "train.speed"}})
        return tagsim.plan(_project([line, speed] + texts))

    def test_a_speed_arc_alone_is_a_vehicle_not_a_train(self):
        """A haul truck's speedometer is a ShSpeedArc too: with no station
        line, consist or traction bar it is not a journey, and its gear and
        tyre readings are not driven as one."""
        signals = tagsim.plan(_project([
            _widget("ShSpeedArc", "arc", {"value": {"tag": "truck.speed"}}),
            _widget("ShGearIndicator", "gear", {"gear": {"tag": "truck.gear"}}, {"gears": "P,R,N,D,L"}),
        ]))
        self.assertFalse(any(sig.kind == "rail" for sig in signals.values()))

    def _run(self, seconds, step=1.0):
        signals = self._cab()
        return [tagsim.values_at(signals, i * step, DURATION) for i in range(int(seconds / step))]

    def test_the_next_station_changes_when_the_train_arrives(self):
        seen = []
        for values in self._run(400):
            if not seen or seen[-1] != values["train.next_station"]:
                seen.append(values["train.next_station"])
        self.assertEqual(seen[:3], ["Halasuru", "Indiranagar", "Swami Vivekananda Road"])

    def test_distance_and_eta_count_down_between_stations(self):
        run = self._run(70)                      # inside the first hop
        metres = [int(v["train.distance_to_go"].replace(",", "").split()[0]) for v in run]
        self.assertEqual(metres, sorted(metres, reverse=True))
        self.assertGreater(metres[0], metres[-1] + 500)
        self.assertRegex(run[0]["train.eta"], r"^(\d+m \d\ds|\d+s)$")

    def test_the_train_stops_at_the_platform_with_its_doors_open(self):
        open_ = [v for v in self._run(400) if v["train.doors"] == "OPEN"]
        self.assertTrue(open_)
        self.assertTrue(all(v["train.speed"] == 0 for v in open_))

    def test_the_station_line_follows_the_train(self):
        for values in self._run(400, step=5.0):
            details = values["train.station_details"].split(",")
            self.assertEqual(len(details), len(self.STATIONS))
            here = values["train.station_index"]
            self.assertTrue(all(d == "COMPLETED" for d in details[:here]))
            self.assertIn(values["train.next_station"], self.STATIONS)
            self.assertTrue(details[self.STATIONS.index(values["train.next_station"])].startswith("NEXT"))

    def test_the_clock_is_a_time_of_day(self):
        self.assertRegex(self._run(1)[0]["train.clock"], r"^\d\d:\d\d:\d\d [AP]M$")

    def test_a_design_without_rail_widgets_still_flies(self):
        signals = tagsim.plan(_project([_widget("Text", "t", {"text": {"tag": "trip.eta"}})]))
        self.assertNotEqual(signals["trip.eta"].kind, "rail")

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


class TurnTests(unittest.TestCase):
    """The turn coordinator reports the turn the heading is making."""

    def test_the_turn_rate_is_the_heading_changing(self):
        for t, state in _samples(1.0):
            ahead = tagsim.state_at(t + 1.0, DURATION)
            turn = ahead["heading"] - state["heading"]
            if abs(turn) > 0.5:
                self.assertEqual(state["turn_rate"] > 0, turn > 0,
                                 "turn rate disagrees with the heading at %.0fs" % t)

    def test_the_bank_and_the_turn_rate_agree(self):
        for _, state in _samples(1.0):
            if abs(state["turn_rate"]) > 0.1:
                self.assertEqual(state["roll"] > 0, state["turn_rate"] > 0)

    def test_the_ball_stays_in_the_middle_of_a_steady_turn(self):
        # Slip comes from rolling in and out, not from being banked.
        steady = [s for _, s in _samples(1.0) if abs(s["turn_rate"]) > 0.3]
        self.assertTrue(steady, "no turn in the profile to test")
        self.assertLess(max(abs(s["slip"]) for s in steady), 1.0)

    def test_the_properties_name_their_own_quantity(self):
        self.assertEqual(tagsim.quantity_for("x.y", "turnRate"), "turn_rate")
        self.assertEqual(tagsim.quantity_for("x.y", "slip"), "slip")


class AlarmTests(unittest.TestCase):
    """A master warning lights because something is out of limits."""

    ALARMS = [{"tag": "eng1.egt", "label": "ENG 1 TEMP",
               "warning": {"op": ">", "value": 650.0},
               "critical": {"op": ">", "value": 700.0}}]

    def test_a_breach_is_found(self):
        self.assertEqual(tagsim.active_alarms(self.ALARMS, {"eng1.egt": 704.0}),
                         [("ENG 1 TEMP", "critical")])
        self.assertEqual(tagsim.active_alarms(self.ALARMS, {"eng1.egt": 660.0}),
                         [("ENG 1 TEMP", "warning")])
        self.assertEqual(tagsim.active_alarms(self.ALARMS, {"eng1.egt": 400.0}), [])

    def test_a_missing_or_odd_value_is_not_an_alarm(self):
        self.assertEqual(tagsim.active_alarms(self.ALARMS, {}), [])
        self.assertEqual(tagsim.active_alarms(self.ALARMS, {"eng1.egt": "hot"}), [])

    def test_the_master_warning_follows_the_alarms(self):
        signals = tagsim.plan(_project([
            _widget("ShGauge", "egt", {"value": {"tag": "eng1.egt"}},
                    {"minimum": 300.0, "maximum": 900.0}),
            _widget("ShTelltale", "mw", {"value": {"tag": "sys.master_warning"}}),
        ]))
        lit = any(tagsim.values_at(signals, t, DURATION, self.ALARMS)["sys.master_warning"]
                  for t in range(0, int(DURATION), 2))
        dark = any(not tagsim.values_at(signals, t, DURATION, self.ALARMS)["sys.master_warning"]
                   for t in range(0, int(DURATION), 2))
        self.assertTrue(lit, "the master warning never lit during a whole flight")
        self.assertTrue(dark, "the master warning never went out")

    def test_without_limits_the_lamp_stays_dark(self):
        signals = tagsim.plan(_project([
            _widget("ShTelltale", "mw", {"value": {"tag": "sys.master_warning"}})]))
        self.assertFalse(tagsim.values_at(signals, 30.0, DURATION, [])["sys.master_warning"])


class ColourTests(unittest.TestCase):
    def test_a_bound_colour_is_a_colour(self):
        sig = tagsim.signal_for("env.sky_colour", "Rectangle", "color", {})
        self.assertEqual(sig.kind, "colour")
        ground = dict(tagsim.state_at(0.0, DURATION), engaged_true=True)
        cruise = dict(tagsim.state_at(DURATION * 0.45, DURATION), engaged_true=True)
        self.assertRegex(sig.at(ground), r"^#[0-9a-f]{6}$")
        self.assertNotEqual(sig.at(ground), sig.at(cruise))


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


class PlantTests(unittest.TestCase):
    """A plant overview's readings have no dial to sweep: they move about the
    value the design shows, and its clock tells the time. On the flight's
    scale a blast furnace's blast volume of 76 600 read 0..0.5."""

    def _design(self):
        reading = lambda wid, tag, value, **props: {
            "type": "ShProcessValue", "id": wid, "properties": dict(value=value, **props),
            "bindings": {"value": {"tag": tag}}}
        return {"pages": [{"widgets": [
            reading("blastVol", "furnace.blast_vol", "76,600"),
            reading("sinter", "furnace.sinter_pellet", 63.0),
            reading("sulphur", "furnace.hm_sulphur", 0.033, decimals=3),
            {"type": "Text", "id": "clock", "properties": {"text": "12-10-2026 10:46:02"},
             "bindings": {"text": {"tag": "furnace.clock"}}},
            {"type": "ShClusterGauge", "id": "rpm", "properties": {"minimumValue": 0, "maximumValue": 3},
             "bindings": {"value": {"tag": "truck.rpm"}}}]}]}

    def test_readings_ramp_about_the_designs_values(self):
        signals = tagsim.plan(self._design())
        frames = [tagsim.values_at(signals, t, 240.0) for t in range(0, 41, 2)]
        vol = [f["furnace.blast_vol"] for f in frames]
        self.assertTrue(all(76600 * 0.969 <= v <= 76600 * 1.031 for v in vol), vol)
        self.assertGreater(max(vol) - min(vol), 76600 * 0.04, "it moves")
        self.assertTrue(all(abs(f["furnace.hm_sulphur"] - 0.033) < 0.002 for f in frames))
        self.assertEqual(frames[0]["furnace.hm_sulphur"], round(frames[0]["furnace.hm_sulphur"], 3))
        self.assertTrue(all(f["furnace.sinter_pellet"] == round(f["furnace.sinter_pellet"], 1) for f in frames))
        # Not in lockstep.
        self.assertNotEqual([round(f["furnace.blast_vol"] / 76600, 3) for f in frames[:5]],
                            [round(f["furnace.sinter_pellet"] / 63.0, 3) for f in frames[:5]])

    def test_a_dial_still_sweeps_its_own_scale_and_the_clock_tells_the_time(self):
        signals = tagsim.plan(self._design())
        values = tagsim.values_at(signals, 60.0, 240.0)
        self.assertEqual(signals["truck.rpm"].kind, "number")
        self.assertTrue(0 <= values["truck.rpm"] <= 3)
        self.assertRegex(values["furnace.clock"], r"^\d\d-\d\d-\d{4} \d\d:\d\d:\d\d$")


if __name__ == "__main__":
    unittest.main()
