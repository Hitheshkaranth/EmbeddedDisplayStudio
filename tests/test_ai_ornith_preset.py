"""The Ornith preset: Ornith 1.5 on the lab vLLM server, spoken to as vLLM.

A preset's key also chooses the request dialect; "ornith" names "vllm" as its
dialect, so its requests, probe and stream parsing are the vLLM ones.
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from tools.hmi_deployer.ai_design import BYOK_PRESETS, ODConnector, ProviderConfig, dialect  # noqa: E402


class OrnithPreset(unittest.TestCase):
    def test_it_is_listed_and_speaks_vllm(self):
        self.assertIn("ornith", [p["key"] for p in ODConnector().get_provider_presets()])
        self.assertEqual(dialect("ornith"), "vllm")
        self.assertEqual(dialect("openai"), "openai")          # a preset without one keeps its own

    def test_a_request_is_a_vllm_chat_request(self):
        conn = ODConnector(mode="byok", byok=ProviderConfig.from_dict(
            dict(BYOK_PRESETS["ornith"], provider="ornith", apiKey="k", model="ornith-1.5-35b-a3b")))
        conn.response_schema = {"type": "object"}
        url, headers, payload = conn.byok_request("a pump skid")
        self.assertEqual(url, "http://spark-ba51:8080/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer k")
        self.assertEqual(payload["model"], "ornith-1.5-35b-a3b")
        self.assertEqual(payload["guided_json"], {"type": "object"})      # vLLM's keyword
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})


if __name__ == "__main__":
    unittest.main()
