"""
tests/test_ai_probe.py
Layer: Test

The AI Design connection check against an OpenAI-compatible server (the lab
vLLM): a server that answers 401 is a key problem, not an unreachable one,
and a saved model the server no longer serves is replaced by one it does.
"""

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools.hmi_deployer.ai_design import ODConnector, ProviderConfig  # noqa: E402

KEY = "sk-lab-key"


class _Handler(BaseHTTPRequestHandler):
    """/v1/models behind a bearer key, like the lab server on :8080."""

    def do_GET(self):  # noqa: N802 - http.server's name
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "invalid API key"}}')
            return
        body = json.dumps({"data": [{"id": "qwen3.8-35b-a3b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ProbeReportsKeyProblems(unittest.TestCase):
    """What the status line says about a server that answers."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def probe(self, key, base=None):
        conn = ODConnector(mode="byok", byok=ProviderConfig(
            provider="vllm", model="m", baseUrl=base or self.base, apiKey=key))
        return conn.probe()

    def test_no_key_is_reported_as_missing_key(self):
        result = self.probe("")
        self.assertFalse(result["ok"])
        self.assertIn("API key required", result["detail"])
        self.assertNotIn("unreachable", result["detail"])

    def test_wrong_key_is_reported_as_rejected(self):
        result = self.probe("wrong")
        self.assertIn("API key rejected", result["detail"])

    def test_right_key_connects_and_lists_models(self):
        result = self.probe(KEY)
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"], ["qwen3.8-35b-a3b"])

    def test_nothing_listening_is_still_unreachable(self):
        result = self.probe(KEY, base="http://127.0.0.1:9")
        self.assertFalse(result["ok"])
        self.assertIn("unreachable", result["detail"])


class StaleModelIsReplaced(unittest.TestCase):
    """A saved model the server no longer serves would fail every request."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_switches_to_a_served_model(self):
        from PySide6.QtWidgets import QComboBox
        from tools.hmi_deployer.ai_tab import AIDesignTab

        tab = mock.MagicMock()
        tab._probe_pending = False
        tab.connector.byok.model = "nvidia/Qwen3.6-35B-A3B-NVFP4"
        combo = QComboBox()
        combo.setEditable(True)
        combo.setCurrentText("nvidia/Qwen3.6-35B-A3B-NVFP4")
        tab.model_combo = combo

        AIDesignTab._on_probe_result(tab, {
            "ok": True, "detail": "vLLM", "latency_ms": 3,
            "models": ["qwen3.8-35b-a3b"],
        })

        tab._fill_models.assert_called_once_with("qwen3.8-35b-a3b")
        tab._on_model_changed.assert_called_once_with("qwen3.8-35b-a3b")
        status = tab._render_status.call_args[0][0]
        self.assertIn("not served, using 'qwen3.8-35b-a3b'", status)

    def test_a_served_model_is_kept(self):
        from PySide6.QtWidgets import QComboBox
        from tools.hmi_deployer.ai_tab import AIDesignTab

        tab = mock.MagicMock()
        tab._probe_pending = False
        tab.connector.byok.model = "qwen3.8-35b-a3b"
        combo = QComboBox()
        combo.setEditable(True)
        combo.setCurrentText("qwen3.8-35b-a3b")
        tab.model_combo = combo

        AIDesignTab._on_probe_result(tab, {"ok": True, "detail": "vLLM", "latency_ms": 3,
                                     "models": ["qwen3.8-35b-a3b"]})

        tab._on_model_changed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
