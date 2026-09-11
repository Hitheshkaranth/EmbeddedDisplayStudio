"""Tests for the AI Design event stream: wire parsers, diffs, and console formatting.

Everything here runs without a network or a QApplication -- the parsers take
literal lines, the formatters take numbers.
"""
import json
import unittest


def sse(obj):
    return "data: " + json.dumps(obj)


class TestOpenAIStream(unittest.TestCase):
    def test_reasoning_content_and_usage(self):
        from tools.hmi_deployer.ai_design import parse_openai_stream
        lines = [
            sse({"choices": [{"delta": {"reasoning_content": "plan "}}]}),
            sse({"choices": [{"delta": {"reasoning_content": "layout"}}]}),
            sse({"choices": [{"delta": {"content": "Hello"}}]}),
            "",
            sse({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 34,
                                           "completion_tokens_details": {"reasoning_tokens": 20}}}),
            "data: [DONE]",
            sse({"choices": [{"delta": {"content": "ignored after DONE"}}]}),
        ]
        events = list(parse_openai_stream(lines))
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["thinking_start", "thinking", "thinking", "delta", "usage"])
        self.assertEqual("".join(e["delta"] for e in events if e["type"] == "thinking"), "plan layout")
        self.assertEqual(events[-1]["usage"], {"input_tokens": 12, "output_tokens": 34, "thinking_tokens": 20})

    def test_inline_think_tags_split_across_deltas(self):
        from tools.hmi_deployer.ai_design import parse_openai_stream
        lines = [
            sse({"choices": [{"delta": {"content": "<thi"}}]}),
            sse({"choices": [{"delta": {"content": "nk>deep"}}]}),
            sse({"choices": [{"delta": {"content": " thought</think>answer"}}]}),
        ]
        events = list(parse_openai_stream(lines))
        thinking = "".join(e["delta"] for e in events if e["type"] == "thinking")
        answer = "".join(e["delta"] for e in events if e["type"] == "delta")
        self.assertEqual(thinking, "deep thought")
        self.assertEqual(answer, "answer")
        self.assertEqual(events[0]["type"], "thinking_start")

    def test_error_object(self):
        from tools.hmi_deployer.ai_design import parse_openai_stream
        events = list(parse_openai_stream([sse({"error": {"message": "model not found"}})]))
        self.assertEqual(events, [{"type": "error", "message": "model not found"}])


class TestAnthropicStream(unittest.TestCase):
    def test_thinking_text_and_usage(self):
        from tools.hmi_deployer.ai_design import parse_anthropic_stream
        lines = [
            "event: message_start",
            sse({"type": "message_start", "message": {"usage": {"input_tokens": 40}}}),
            sse({"type": "content_block_start", "content_block": {"type": "thinking"}}),
            sse({"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hmm"}}),
            sse({"type": "content_block_start", "content_block": {"type": "text"}}),
            sse({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}),
            sse({"type": "message_delta", "usage": {"output_tokens": 9}}),
            sse({"type": "message_stop"}),
        ]
        events = list(parse_anthropic_stream(lines))
        self.assertEqual([e["type"] for e in events], ["thinking_start", "thinking", "delta", "usage"])
        self.assertEqual(events[2]["delta"], "Hi")
        self.assertEqual(events[3]["usage"], {"input_tokens": 40, "output_tokens": 9})


class TestOllamaStream(unittest.TestCase):
    def test_ndjson_with_server_measured_rate(self):
        from tools.hmi_deployer.ai_design import parse_ollama_stream
        lines = [
            json.dumps({"message": {"role": "assistant", "thinking": "let me see"}, "done": False}),
            json.dumps({"message": {"role": "assistant", "content": "Hel"}, "done": False}),
            json.dumps({"message": {"role": "assistant", "content": "lo"}, "done": False}),
            json.dumps({"message": {"role": "assistant", "content": ""}, "done": True,
                        "prompt_eval_count": 15, "eval_count": 50, "eval_duration": 2_000_000_000,
                        "total_duration": 2_500_000_000}),
        ]
        events = list(parse_ollama_stream(lines))
        self.assertEqual([e["type"] for e in events], ["thinking_start", "thinking", "delta", "delta", "usage"])
        usage = events[-1]
        self.assertEqual(usage["usage"], {"input_tokens": 15, "output_tokens": 50})
        self.assertAlmostEqual(usage["tokensPerSecond"], 25.0)
        self.assertAlmostEqual(usage["durationMs"], 2500.0)


class TestGoogleStream(unittest.TestCase):
    def test_thought_parts_and_usage_metadata(self):
        from tools.hmi_deployer.ai_design import parse_google_stream
        lines = [
            sse({"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}]}}],
                 "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}}),
            sse({"candidates": [{"content": {"parts": [{"text": "Answer"}]}}],
                 "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7, "thoughtsTokenCount": 3}}),
        ]
        events = list(parse_google_stream(lines))
        self.assertEqual([e["type"] for e in events], ["thinking_start", "thinking", "delta", "usage"])
        self.assertEqual(events[-1]["usage"], {"input_tokens": 5, "output_tokens": 7, "thinking_tokens": 3})


class TestDaemonStream(unittest.TestCase):
    def test_named_events_and_legacy_delta(self):
        from tools.hmi_deployer.ai_design import parse_daemon_stream
        lines = [
            "event: start", sse({"model": "claude"}), "",
            "event: thinking", sse({"delta": "reasoning"}), "",
            sse({"delta": "plain"}), "",
            "event: tool_use", sse({"id": "t1", "name": "Write", "input": {"file_path": "a/b.html"}}), "",
            "event: tool_result", sse({"id": "t1"}), "",
            "event: usage", sse({"usage": {"input_tokens": 1, "output_tokens": 2}, "costUsd": 0.01}), "",
            "event: error", sse({"message": "boom"}), "",
            "event: end", sse({}), "",
        ]
        events = list(parse_daemon_stream(lines))
        self.assertEqual([e["type"] for e in events],
                         ["start", "thinking", "delta", "tool_use", "tool_result", "usage", "error", "turn_end"])
        self.assertEqual(events[1]["delta"], "reasoning")
        self.assertEqual(events[2]["delta"], "plain")
        self.assertEqual(events[3]["name"], "Write")
        self.assertEqual(events[5]["usage"]["output_tokens"], 2)
        self.assertEqual(events[6]["message"], "boom")


class TestGenerateEvents(unittest.TestCase):
    def _connector(self, events):
        from tools.hmi_deployer.ai_design import ODConnector, ProviderConfig
        conn = ODConnector(mode="byok", byok=ProviderConfig(provider="vllm", model="m", baseUrl="http://x"))
        conn._stream_events = lambda url, payload, headers, parser: iter(events)
        return conn

    def test_wraps_start_and_turn_end_and_records_history(self):
        conn = self._connector([{"type": "delta", "delta": "He"}, {"type": "delta", "delta": "llo"}])
        events = list(conn.generate_events("brief"))
        self.assertEqual(events[0]["type"], "start")
        self.assertEqual(events[0]["model"], "m")
        self.assertEqual(events[-1], {"type": "turn_end", "stopped": False})
        self.assertIn({"type": "status", "label": "streaming"}, events)
        self.assertEqual([m.role for m in conn.conversation], ["user", "assistant"])
        self.assertEqual(conn.conversation[-1].content, "Hello")

    def test_text_wrapper_surfaces_errors_inline(self):
        conn = self._connector([{"type": "error", "message": "nope"}])
        self.assertEqual(list(conn.generate("brief")), ["[Error] nope"])

    def test_cancel_marks_turn_stopped(self):
        from tools.hmi_deployer.ai_design import StreamCancelled
        def source():
            yield {"type": "delta", "delta": "a"}
            raise StreamCancelled()
        conn = self._connector(source())
        events = list(conn.generate_events("brief"))
        self.assertEqual(events[-1], {"type": "turn_end", "stopped": True})

    def test_missing_api_key_is_an_error_before_any_request(self):
        from tools.hmi_deployer.ai_design import ODConnector, ProviderConfig, BYOK_PRESETS
        conn = ODConnector(mode="byok", byok=ProviderConfig.from_dict(dict(BYOK_PRESETS["openai"], provider="openai")))
        events = list(conn.generate_events("brief"))
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("API key", events[0]["message"])

    def test_history_rides_along(self):
        from tools.hmi_deployer.ai_design import ChatMessage
        captured = {}
        conn = self._connector([])
        def capture(url, payload, headers, parser):
            captured["payload"] = payload
            return iter([])
        conn._stream_events = capture
        conn.conversation = [ChatMessage("user", "first"), ChatMessage("assistant", "reply")]
        list(conn.generate_events("second"))
        roles = [m["role"] for m in captured["payload"]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(captured["payload"]["stream_options"], {"include_usage": True})


class TestProjectDiff(unittest.TestCase):
    def _project(self, widgets):
        from designer.model import DesignerProject, DesignerPage, DesignerWidget
        page = DesignerPage(widgets=[DesignerWidget(t, i, dict(g), dict(p)) for t, i, g, p in widgets])
        return DesignerProject(pages=[page])

    def test_added_removed_changed(self):
        from tools.hmi_deployer.ai_generator import diff_projects
        before = self._project([
            ("ShGauge", "rpm", {"x": 0, "y": 0, "width": 100, "height": 100}, {}),
            ("ShButton", "start", {"x": 0, "y": 0, "width": 100, "height": 40}, {"text": "Start"}),
        ])
        after = self._project([
            ("ShGauge", "rpm", {"x": 0, "y": 0, "width": 200, "height": 200}, {}),
            ("Text", "title", {"x": 0, "y": 0, "width": 100, "height": 20}, {}),
        ])
        diff = diff_projects(before, after)
        self.assertEqual([w["id"] for w in diff["added"]], ["title"])
        self.assertEqual([w["id"] for w in diff["removed"]], ["start"])
        self.assertEqual([w["id"] for w in diff["changed"]], ["rpm"])
        self.assertEqual(diff_projects(None, after)["added"].__len__(), 2)

    def test_summary_and_model_ids_kept(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator, summarize_widgets
        gen = AIDesignGenerator()
        text = 'Two sentences.\n```json\n' + json.dumps({"pages": [{"widgets": [
            {"type": "Gauge", "id": "rpmGauge", "geometry": {"x": 0, "y": 0, "width": 100, "height": 100}},
            {"type": "Gauge", "id": "rpmGauge", "geometry": {"x": 0, "y": 0, "width": 100, "height": 100}},
            {"type": "Button", "id": "Bad Id", "geometry": {"x": 0, "y": 0, "width": 100, "height": 40}},
        ]}]}) + '\n```\n'
        project = gen.generate(text)
        ids = [w.id for w in project.all_widgets()]
        self.assertEqual(ids[0], "rpmGauge")
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(summarize_widgets(project), "3 widgets: ShGauge x2, ShButton")

    def test_system_prompt_lists_registry_types(self):
        from tools.hmi_deployer.ai_generator import build_system_prompt
        from designer.palette.widget_registry import default_registry
        prompt = build_system_prompt(default_registry(), 1024, 600)
        self.assertIn("1024x600", prompt)
        self.assertIn("ShGauge", prompt)
        self.assertIn("```json", prompt)


class TestConsoleFormatting(unittest.TestCase):
    def test_formats_follow_opendesign_rules(self):
        from tools.hmi_deployer.ai_tab import (
            format_elapsed, format_shell_elapsed, format_tokens, format_rate, conclusion_prose,
        )
        self.assertEqual(format_elapsed(400), "0.4s")
        self.assertEqual(format_elapsed(72_000), "1m 12s")
        self.assertIsNone(format_shell_elapsed(900))          # never "0.0s"
        self.assertEqual(format_shell_elapsed(3_200), "3.2s")
        self.assertEqual(format_shell_elapsed(31_400), "31s")
        self.assertEqual(format_tokens(950), "950")
        self.assertEqual(format_tokens(1000), "1k")
        self.assertEqual(format_tokens(3278), "3.3k")          # rounded, not truncated
        self.assertEqual(format_tokens(3278, estimated=True), "~3.3k")
        self.assertIsNone(format_tokens(0))
        self.assertEqual(format_rate(47.94), "47.9 tok/s")
        self.assertEqual(format_rate(212.4), "212 tok/s")
        prose = conclusion_prose('Nice layout.\n```json\n{"pages": []}\n```\n')
        self.assertEqual(prose, "Nice layout.")


class TestReviewFixes(unittest.TestCase):
    def test_secret_query_params_are_redacted(self):
        from tools.hmi_deployer.ai_design import redact_url
        self.assertEqual(redact_url("https://g/v1?alt=sse&key=SECRET&x=1"), "https://g/v1?alt=sse&key=***&x=1")
        self.assertEqual(redact_url("http://h/v1/chat"), "http://h/v1/chat")

    def test_google_key_travels_in_header_not_url(self):
        from tools.hmi_deployer.ai_design import ODConnector, ProviderConfig, BYOK_PRESETS
        conn = ODConnector(mode="byok", byok=ProviderConfig.from_dict(
            dict(BYOK_PRESETS["google"], provider="google", apiKey="SECRET", model="gemini-2.5-flash")))
        seen = {}
        def capture(url, payload, headers, parser):
            seen.update(url=url, headers=headers)
            return iter([])
        conn._stream_events = capture
        events = list(conn.generate_events("brief"))
        self.assertNotIn("SECRET", seen["url"])
        self.assertEqual(seen["headers"]["x-goog-api-key"], "SECRET")
        self.assertNotIn("SECRET", events[0]["url"])

    def test_history_drops_orphaned_turns(self):
        from tools.hmi_deployer.ai_design import ODConnector, ProviderConfig, ChatMessage
        conn = ODConnector(mode="byok", byok=ProviderConfig(provider="vllm", model="m", baseUrl="http://x"))
        conn.conversation = [
            ChatMessage("user", "first"), ChatMessage("assistant", "reply"),
            ChatMessage("user", "cancelled"), ChatMessage("assistant", ""),   # aborted turn
            ChatMessage("user", "current"),
        ]
        roles = [(m["role"], m["content"]) for m in conn._history_messages()]
        self.assertEqual(roles, [("user", "first"), ("assistant", "reply")])

    def test_truncation_surfaces_as_status(self):
        from tools.hmi_deployer.ai_design import parse_openai_stream
        lines = [sse({"choices": [{"delta": {"content": "x"}, "finish_reason": None}]}),
                 sse({"choices": [{"delta": {}, "finish_reason": "length"}]})]
        self.assertIn({"type": "status", "label": "truncated"}, list(parse_openai_stream(lines)))

    def test_prose_keeps_brace_mentions(self):
        from tools.hmi_deployer.ai_tab import conclusion_prose
        text = 'Bound to {rpm} and {label}. {"pages": [{"widgets": []}]} Done.'
        self.assertEqual(conclusion_prose(text), "Bound to {rpm} and {label}.  Done.")

    def test_bindings_are_kept(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        gen = AIDesignGenerator()
        widgets = gen._convert_widgets([{"type": "ShGauge", "id": "rpm",
                                         "geometry": {"x": 0, "y": 0, "width": 10, "height": 10},
                                         "bindings": {"value": {"tag": "eng.rpm"}, "bad": 42}}])
        self.assertEqual(widgets[0].bindings["value"].tag, "eng.rpm")
        self.assertNotIn("bad", widgets[0].bindings)


if __name__ == "__main__":
    unittest.main()
