"""
tests/test_daemon_protocol.py
Layer: Test (W11)
Pins CONTRACT 2 behaviour for hmi_hwd.py daemon over UDP loopback.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

class TestDaemonProtocol(unittest.TestCase):
    """
    Tests for CONTRACT 2 (Wire protocol).
    Pins daemon UDP behaviour, telemetry, and error responses.
    """
    _port_counter = 5050

    def setUp(self):
        """
        Starts the daemon subprocess with --sim and a temporary hwd.json on a
        non-default port pair so it never collides with a running instance.
        """
        self.__class__._port_counter += 2
        self.cmd_port = self.__class__._port_counter
        self.telemetry_port = self.__class__._port_counter + 1

        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "hwd.json")
        config_data = {
            "daemon": {
                "cmd_port": self.cmd_port,
                "telemetry_sink": f"127.0.0.1:{self.telemetry_port}",
                "poll_interval_ms": 50
            },
            "gpio": {
                "chip": "/dev/gpiochip3",
                "inputs": {"di.estop": {"offset": 4, "active_low": True}},
                "outputs": {"do.relay1": {"offset": 5, "active_low": False, "initial": 0}}
            },
            "adc": {
                "device_name": "ads1015",
                "channels": {"ai.pot": {"channel_file": "in_voltage0_raw", "scale_file": "in_voltage0_scale"}}
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f)
            
        # We need to simulate a hardware read failure for ai.pot per CONTRACT.
        # Since --sim forces IioSim which never fails, we inject a wrapper.
        mock_script_path = os.path.join(self.temp_dir.name, "mock_runner.py")
        with open(mock_script_path, "w", encoding="utf-8") as f:
            f.write(
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "import daemon.hmi_hwd as hwd\n"
                "original = hwd.IioSim.read\n"
                "hwd.IioSim.read = lambda s, t: None if t == 'ai.pot' else original(s, t)\n"
                "hwd.main()\n"
            )
        cmd = [sys.executable, mock_script_path, "--config", self.config_path, "--sim"]
        
        # Start daemon
        self.daemon_proc = subprocess.Popen(cmd)
        
        # Sockets
        self.cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd_sock.settimeout(0.5)
        
        self.sink_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sink_sock.bind(("127.0.0.1", self.telemetry_port))
        self.sink_sock.settimeout(0.5)
        
        # Wait for daemon to become ready by listening for a telemetry frame
        for _ in range(20):
            try:
                data, _ = self.sink_sock.recvfrom(8192)
                if data:
                    break
            except socket.timeout:
                pass
        else:
            self.fail("Daemon did not produce telemetry within 10 seconds")

    def tearDown(self):
        """Always terminate the subprocess in tearDown, even on failure."""
        if self.daemon_proc.poll() is None:
            self.daemon_proc.terminate()
            try:
                self.daemon_proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.daemon_proc.kill()
        self.cmd_sock.close()
        self.sink_sock.close()
        self.temp_dir.cleanup()

    def _send_cmd(self, payload_bytes: bytes) -> dict:
        self.cmd_sock.sendto(payload_bytes, ("127.0.0.1", self.cmd_port))
        try:
            resp, _ = self.cmd_sock.recvfrom(8192)
            return json.loads(resp.decode("utf-8"))
        except socket.timeout:
            return None

    def test_valid_set_acked(self):
        """
        CONTRACT 2.2, 2.3: A valid 'set' is acked ok.
        """
        req = json.dumps({"id": "t1", "cmd": "set", "tag": "do.relay1", "value": 1}).encode("utf-8")
        resp = self._send_cmd(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.get("t"), "ack")
        self.assertEqual(resp.get("id"), "t1")
        self.assertTrue(resp.get("ok"))

    def test_error_codes(self):
        """
        CONTRACT 2.3: unknown tag -> unknown_tag, input -> not_writable, wrong type -> bad_value, oversized -> too_large.
        """
        # Unknown tag
        resp = self._send_cmd(json.dumps({"id": "t2", "cmd": "set", "tag": "do.nope", "value": 1}).encode("utf-8"))
        self.assertIsNotNone(resp)
        self.assertFalse(resp.get("ok"))
        self.assertEqual(resp.get("err"), "unknown_tag")
        
        # Write to input
        resp = self._send_cmd(json.dumps({"id": "t3", "cmd": "set", "tag": "di.estop", "value": 1}).encode("utf-8"))
        self.assertIsNotNone(resp)
        self.assertFalse(resp.get("ok"))
        self.assertEqual(resp.get("err"), "not_writable")

        # Wrong value type (string to bool)
        resp = self._send_cmd(json.dumps({"id": "t4", "cmd": "set", "tag": "do.relay1", "value": "on"}).encode("utf-8"))
        self.assertIsNotNone(resp)
        self.assertFalse(resp.get("ok"))
        self.assertEqual(resp.get("err"), "bad_value")
        
        # Oversized
        big_val = "x" * 8192
        resp = self._send_cmd(json.dumps({"id": "t5", "cmd": "set", "tag": "do.relay1", "value": big_val}).encode("utf-8"))
        self.assertIsNotNone(resp)
        self.assertFalse(resp.get("ok"))
        self.assertEqual(resp.get("err"), "too_large")

    def test_unparseable_input_nacks_when_an_id_is_recoverable(self):
        """
        CONTRACT 2.3 + 7: unparseable input is answered with ack{ok:false}
        when an id can be recovered, using the closed-set error code.

        This test previously asserted silence in both cases and passed for the
        wrong reason: RateLimitedLogger.warning() raised TypeError on the line
        before the nack, so the handler never reached _send_nack and the
        daemon went quiet. CONTRACT 7 is explicit -- "counted, rate-limited log
        line, ack{ok:false} if id present" -- and without a reply the bad_json
        and not_an_object codes in the 2.3 closed set were unreachable.
        """
        # Truncated JSON: the id is still recoverable by regex from the text.
        resp = self._send_cmd(b'{"id": "t6", "cmd": "set", ')
        self.assertIsNotNone(resp, "Malformed JSON carrying an id must be nacked")
        self.assertEqual(resp.get("id"), "t6")
        self.assertFalse(resp.get("ok"))
        self.assertEqual(resp.get("err"), "bad_json")

        # Well-formed JSON that is not an object has no addressable id member,
        # but the raw text still carries one.
        resp = self._send_cmd(b'[{"id": "t7", "cmd": "ping"}]')
        self.assertIsNotNone(resp, "Non-object JSON carrying an id must be nacked")
        self.assertEqual(resp.get("id"), "t7")
        self.assertFalse(resp.get("ok"))
        self.assertEqual(resp.get("err"), "not_an_object")

    def test_silence_when_no_id_can_be_recovered(self):
        """
        CONTRACT 2.3: no id, no reply.

        This is what stops the daemon being used as a UDP reflector: an
        attacker spoofing a source address gets nothing back unless they also
        supply a correlation id, and a reflector needs the reply to be larger
        than the request, which a bare ack never is.
        """
        for payload in (
            b'{"cmd": "set", ',            # malformed, no id
            b'[1, 2, 3]',                  # not an object, no id
            b'\x00\xff\xfe\x10',           # invalid UTF-8
            b'',                           # empty datagram
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(
                    self._send_cmd(payload),
                    f"Daemon must stay silent for {payload!r}",
                )

    def test_unknown_command_is_nacked(self):
        """
        CONTRACT 2.3: an unrecognised cmd with an id gets unknown_cmd.

        Untested before, and broken: the unknown_cmd path raised TypeError in
        its log call and returned without ever sending the nack.
        """
        resp = self._send_cmd(
            json.dumps({"id": "t9", "cmd": "definitely-not-a-command"}).encode("utf-8")
        )
        self.assertIsNotNone(resp)
        self.assertEqual(resp.get("id"), "t9")
        self.assertFalse(resp.get("ok"))
        self.assertEqual(resp.get("err"), "unknown_cmd")

    def test_noise_resilience(self):
        """
        CONTRACT 7: empty datagram, raw binary noise, invalid UTF-8 do not kill the process.
        """
        self.cmd_sock.sendto(b"", ("127.0.0.1", self.cmd_port))
        self.cmd_sock.sendto(b"\x00\xff\xfe\x10", ("127.0.0.1", self.cmd_port))
        
        time.sleep(0.2)
        self.assertIsNone(self.daemon_proc.poll(), "Daemon crashed after bad input")
        
        # Assert still alive and processing
        resp = self._send_cmd(json.dumps({"id": "t8", "cmd": "ping"}).encode("utf-8"))
        self.assertIsNotNone(resp)
        self.assertTrue(resp.get("ok"))

    def test_telemetry_frames(self):
        """
        CONTRACT 2.4: telemetry frames carry configured tags, seq increases,
        and a failed read publishes null.
        """
        # Drain the buffer first
        self.sink_sock.setblocking(False)
        while True:
            try:
                self.sink_sock.recvfrom(8192)
            except BlockingIOError:
                break
            except Exception:
                break
        self.sink_sock.setblocking(True)
        self.sink_sock.settimeout(1.0)
        
        # Get frame 1
        data, _ = self.sink_sock.recvfrom(8192)
        frame1 = json.loads(data.decode("utf-8"))
        seq1 = frame1.get("seq")
        
        # Get frame 2
        data, _ = self.sink_sock.recvfrom(8192)
        frame2 = json.loads(data.decode("utf-8"))
        seq2 = frame2.get("seq")
        
        self.assertGreater(seq2, seq1, "Sequence strictly increases")
        
        tags = frame2.get("tags", {})
        self.assertIn("di.estop", tags)
        self.assertIn("do.relay1", tags)
        self.assertIn("ai.pot", tags)
        self.assertIn("sys.uptime", tags)
        self.assertIn("sys.errors", tags)
        
        self.assertIsNone(tags.get("ai.pot"), "Failed hardware read should publish null")

if __name__ == "__main__":
    unittest.main()
