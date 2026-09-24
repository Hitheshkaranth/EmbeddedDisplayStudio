"""
tools/hmi_deployer/ai_design.py -- OpenDesign connector and Qt/QML generator

Layer: 3 (Host Deployer)

Connects EmbeddedDisplay Studio to OpenDesign for AI-driven UI generation.
Supports two modes:

  1. **Daemon mode** -- talks to a local OpenDesign daemon (default
     localhost:7456).  Projects, briefs and model selection flow through the
     daemon's REST API.  Streaming uses SSE.

  2. **BYOK mode** -- no daemon required.  The Studio calls the upstream API
     directly (Ollama, OpenAI, Anthropic, etc.).  Every provider has a preset
     so the user only needs to paste an API key and pick a model.

Both modes surface the same **event stream** to the UI, using the same
vocabulary OpenDesign's daemon normalises its agent runtimes into
(``apps/daemon/src/runtimes/claude-stream.ts``):

    start            {model, provider, url, mode}
    status           {label: connecting|streaming, ttftMs?}
    thinking_start   {}
    thinking         {delta}
    thinking_tokens  {tokens}            -- running estimate for the live block
    delta            {delta}             -- answer text
    usage            {usage: {input_tokens, output_tokens, thinking_tokens?},
                      durationMs?, tokensPerSecond?}   -- only when reported
    error            {message}
    turn_end         {stopped: bool}

The generated JSON/QML is parsed by ``ai_generator`` and mapped onto the
designer canvas (DesignerProject + DesignerWidget model), so the author can
inspect and tweak the AI output before deploying to the panel.
"""
import json
import re
import time
import logging
import socket
import threading
import urllib.request
import urllib.error
import urllib.parse
import ssl

from typing import Generator, Iterable, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenDesign daemon defaults
# ---------------------------------------------------------------------------

DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 7456

# Output budget per turn.  Reasoning models (Qwen3, DeepSeek-R1, o-series)
# spend thousands of tokens thinking before the JSON even starts, and
# OpenAI-compatible servers count that against max_tokens -- 8k cut bigger
# briefs off mid-payload, which the UI then reported as "no design parsed".
MAX_OUTPUT_TOKENS = 16384
ANTHROPIC_MAX_OUTPUT_TOKENS = 8192

# How many prior turns ride along with a new brief so "make the gauge bigger"
# has something to refer to.  Kept small: embedded briefs are short and local
# models have small context windows.
HISTORY_TURNS = 3

# ---------------------------------------------------------------------------
# BYOK provider presets
# ---------------------------------------------------------------------------

BYOK_PRESETS = {
    "ollama": {
        "label": "Ollama (local)",
        "baseUrl": "http://127.0.0.1:11434",
        "apiVersion": "",
        "requiresApiKey": False,
        "apiKey": "",
        "protocol": "ollama",
        "models": [
            "qwen2.5:7b",
            "qwen2.5:14b",
            "qwen2.5:32b",
            "llama3.1:8b",
            "llama3.1:70b",
            "mistral3:8b",
        ],
    },
    "openai": {
        "label": "OpenAI",
        "baseUrl": "https://api.openai.com",
        "apiVersion": "",
        "requiresApiKey": True,
        "apiKey": "",
        "protocol": "openai",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "o3-mini",
            "nvidia/Qwen3.6-35B-A3B-NVFP4",
        ],
    },
    "vllm": {
        "label": "vLLM (Tailscale)",
        # The lab server moved to 8080 with Qwen3.8 on 2026-09-24, behind an
        # API key; nothing listens on 8000 any more.
        "baseUrl": "http://spark-ba51:8080",
        "apiVersion": "",
        "requiresApiKey": True,
        "apiKey": "",
        "protocol": "openai",
        "models": [
            "qwen3.8-35b-a3b",
        ],
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "baseUrl": "https://api.anthropic.com",
        "apiVersion": "2023-06-01",
        "requiresApiKey": True,
        "apiKey": "",
        "protocol": "anthropic",
        "models": [
            "claude-4-sonnet",
            "claude-4-opus",
            "claude-3-5-sonnet",
            "claude-3-5-haiku",
        ],
    },
    "google": {
        "label": "Google (Gemini)",
        "baseUrl": "https://generativelanguage.googleapis.com",
        "apiVersion": "",
        "requiresApiKey": True,
        "apiKey": "",
        "protocol": "google",
        "models": [
            "gemini-2.0-flash",
            "gemini-2.0-pro",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ],
    },
}

_SECRET_QUERY_RE = re.compile(r"([?&](?:key|api_key|apikey|token)=)[^&#]+", re.I)


def redact_url(url: str) -> str:
    """Mask credential-bearing query parameters before a URL reaches the UI or a log."""
    return _SECRET_QUERY_RE.sub(r"\1***", url or "")


DEFAULT_SYSTEM_PROMPT = (
    "You are an expert Qt/QML UI designer for embedded HMI panels. "
    "Generate clean, production-ready QML code using Shadcn-inspired "
    "widget styles. Focus on clarity, proper layout containers, and "
    "data binding to tag sources. Output ONLY QML code blocks."
)


@dataclass
class ModelOption:
    """A single selectable model within a provider."""
    id: str
    label: str
    default: bool = False


@dataclass
class ProviderConfig:
    """BYOK provider configuration (model + API key + base URL)."""
    provider: str  # key in BYOK_PRESETS
    model: str
    baseUrl: str = ""
    apiKey: str = ""
    apiVersion: str = ""
    requiresApiKey: bool = False
    models: list = field(default_factory=list)
    # Reasoning models (Qwen3, DeepSeek-R1, ...) think before they answer and
    # their reasoning counts against max_tokens, so a long think can spend the
    # whole budget and return no design.  Off unless the user asks for it.
    thinking: bool = False

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "baseUrl": self.baseUrl,
            "apiKey": self.apiKey,
            "apiVersion": self.apiVersion,
            "requiresApiKey": self.requiresApiKey,
            "thinking": self.thinking,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderConfig":
        filtered = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(
            provider=filtered.get("provider", "ollama"),
            model=filtered.get("model", ""),
            baseUrl=filtered.get("baseUrl", ""),
            apiKey=filtered.get("apiKey", ""),
            apiVersion=filtered.get("apiVersion", ""),
            requiresApiKey=filtered.get("requiresApiKey", False),
            thinking=bool(filtered.get("thinking", False)),
            models=filtered.get("models", []),
        )


@dataclass
class ChatMessage:
    """A single message in the conversation history."""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class GenerateResult:
    """Result of a design generation request."""
    success: bool
    qml: str = ""
    html: str = ""
    error: str = ""
    messages: list = field(default_factory=list)


class StreamCancelled(Exception):
    """Raised inside a stream loop when the user pressed Stop."""


# ---------------------------------------------------------------------------
# Pure stream parsers -- one per wire format, no I/O
# ---------------------------------------------------------------------------
#
# Each takes an iterable of decoded lines and yields events.  Keeping them
# free of sockets means the UI's whole event pipeline can be exercised from a
# unit test with a handful of literal lines.

def _sse_data_lines(lines: Iterable[str]):
    """Yield the JSON payload of each ``data:`` line, skipping keep-alives."""
    for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        yield payload


class _ThinkTagSplitter:
    """Route ``<think>…</think>`` spans (Qwen3 / DeepSeek-R1 style) to thinking.

    Some OpenAI-compatible servers inline the reasoning into ``content``
    instead of ``reasoning_content``.  The tag can be split across deltas, so
    a small carry buffer holds a partial ``<`` until it is resolved.
    """
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.in_think = False
        self.carry = ""

    def feed(self, text: str) -> list:
        """Return a list of ("thinking"|"delta", text) tuples."""
        out = []
        buf = self.carry + text
        self.carry = ""
        while buf:
            tag = self.CLOSE if self.in_think else self.OPEN
            idx = buf.find(tag)
            if idx >= 0:
                if idx:
                    out.append(("thinking" if self.in_think else "delta", buf[:idx]))
                self.in_think = not self.in_think
                buf = buf[idx + len(tag):]
                continue
            # No full tag: keep a possible tag prefix at the end for the next delta.
            keep = 0
            for n in range(min(len(tag) - 1, len(buf)), 0, -1):
                if tag.startswith(buf[-n:]):
                    keep = n
                    break
            emit, self.carry = (buf[:-keep], buf[-keep:]) if keep else (buf, "")
            if emit:
                out.append(("thinking" if self.in_think else "delta", emit))
            buf = ""
        return out

    def flush(self) -> list:
        if not self.carry:
            return []
        text, self.carry = self.carry, ""
        return [("thinking" if self.in_think else "delta", text)]


def parse_openai_stream(lines: Iterable[str]) -> Generator[dict, None, None]:
    """OpenAI-compatible ``/v1/chat/completions`` SSE (OpenAI, vLLM, Groq…).

    Handles ``delta.content``, ``delta.reasoning_content`` / ``delta.reasoning``
    (vLLM, DeepSeek), inline ``<think>`` tags, and the trailing ``usage``
    chunk sent when ``stream_options.include_usage`` is on.
    """
    splitter = _ThinkTagSplitter()
    thinking_started = False
    for payload in _sse_data_lines(lines):
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if obj.get("error"):
            err = obj["error"]
            yield {"type": "error", "message": err.get("message", str(err)) if isinstance(err, dict) else str(err)}
            continue
        choices = obj.get("choices") or []
        if choices:
            if choices[0].get("finish_reason") == "length":
                yield {"type": "status", "label": "truncated"}
            delta = choices[0].get("delta") or {}
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning:
                if not thinking_started:
                    thinking_started = True
                    yield {"type": "thinking_start"}
                yield {"type": "thinking", "delta": reasoning}
            content = delta.get("content")
            if content:
                for kind, text in splitter.feed(content):
                    if kind == "thinking" and not thinking_started:
                        thinking_started = True
                        yield {"type": "thinking_start"}
                    yield {"type": kind, "delta": text}
        usage = obj.get("usage")
        if usage and isinstance(usage, dict):
            details = usage.get("completion_tokens_details") or {}
            yield {"type": "usage", "usage": {
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "thinking_tokens": details.get("reasoning_tokens"),
            }}
    for kind, text in splitter.flush():
        yield {"type": kind, "delta": text}


def parse_anthropic_stream(lines: Iterable[str]) -> Generator[dict, None, None]:
    """Anthropic Messages API SSE: text/thinking deltas plus usage frames."""
    input_tokens = None
    for payload in _sse_data_lines(lines):
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        kind = obj.get("type")
        if kind == "message_start":
            usage = (obj.get("message") or {}).get("usage") or {}
            input_tokens = usage.get("input_tokens")
        elif kind == "content_block_start":
            if (obj.get("content_block") or {}).get("type") == "thinking":
                yield {"type": "thinking_start"}
        elif kind == "content_block_delta":
            delta = obj.get("delta") or {}
            if delta.get("type") == "thinking_delta" and delta.get("thinking"):
                yield {"type": "thinking", "delta": delta["thinking"]}
            elif delta.get("type") == "text_delta" and delta.get("text"):
                yield {"type": "delta", "delta": delta["text"]}
        elif kind == "message_delta":
            if (obj.get("delta") or {}).get("stop_reason") == "max_tokens":
                yield {"type": "status", "label": "truncated"}
            usage = obj.get("usage") or {}
            if usage.get("output_tokens") is not None:
                yield {"type": "usage", "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": usage.get("output_tokens"),
                }}
        elif kind == "error":
            err = obj.get("error") or {}
            yield {"type": "error", "message": err.get("message", "Anthropic stream error")}


def parse_ollama_stream(lines: Iterable[str]) -> Generator[dict, None, None]:
    """Ollama ``/api/chat`` NDJSON: ``message.content``/``message.thinking``.

    The final ``done`` object carries exact counts *and* the generation
    wall-clock, so tokens-per-second is measured by the server, not by us.
    """
    splitter = _ThinkTagSplitter()
    thinking_started = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("error"):
            yield {"type": "error", "message": str(obj["error"])}
            continue
        message = obj.get("message") or {}
        thinking = message.get("thinking")
        if thinking:
            if not thinking_started:
                thinking_started = True
                yield {"type": "thinking_start"}
            yield {"type": "thinking", "delta": thinking}
        content = message.get("content")
        if content:
            for kind, text in splitter.feed(content):
                if kind == "thinking" and not thinking_started:
                    thinking_started = True
                    yield {"type": "thinking_start"}
                yield {"type": kind, "delta": text}
        if obj.get("done"):
            for kind, text in splitter.flush():
                yield {"type": kind, "delta": text}
            if obj.get("done_reason") == "length":
                yield {"type": "status", "label": "truncated"}
            eval_count = obj.get("eval_count")
            eval_ns = obj.get("eval_duration")
            event = {"type": "usage", "usage": {
                "input_tokens": obj.get("prompt_eval_count"),
                "output_tokens": eval_count,
            }}
            if obj.get("total_duration"):
                event["durationMs"] = obj["total_duration"] / 1e6
            if eval_count and eval_ns:
                event["tokensPerSecond"] = eval_count / (eval_ns / 1e9)
            yield event


def parse_google_stream(lines: Iterable[str]) -> Generator[dict, None, None]:
    """Gemini ``streamGenerateContent?alt=sse``: parts (thought or text) + usageMetadata."""
    thinking_started = False
    last_usage = None
    for payload in _sse_data_lines(lines):
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if obj.get("error"):
            err = obj["error"]
            yield {"type": "error", "message": err.get("message", str(err)) if isinstance(err, dict) else str(err)}
            continue
        for cand in obj.get("candidates") or []:
            if cand.get("finishReason") == "MAX_TOKENS":
                yield {"type": "status", "label": "truncated"}
            for part in (cand.get("content") or {}).get("parts") or []:
                text = part.get("text")
                if not text:
                    continue
                if part.get("thought"):
                    if not thinking_started:
                        thinking_started = True
                        yield {"type": "thinking_start"}
                    yield {"type": "thinking", "delta": text}
                else:
                    yield {"type": "delta", "delta": text}
        meta = obj.get("usageMetadata")
        if meta:
            last_usage = {
                "input_tokens": meta.get("promptTokenCount"),
                "output_tokens": meta.get("candidatesTokenCount"),
                "thinking_tokens": meta.get("thoughtsTokenCount"),
            }
    if last_usage:
        yield {"type": "usage", "usage": last_usage}


def parse_daemon_stream(lines: Iterable[str]) -> Generator[dict, None, None]:
    """OpenDesign daemon ``/api/chat`` SSE.

    The daemon names events on an ``event:`` line and puts the body on
    ``data:``; older builds only send ``data: {"delta": …}``.  Both are
    normalised onto the shared vocabulary above.
    """
    event_name = None
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            if not line:
                event_name = None
            continue
        payload = line[5:].strip()
        event_name, name = None, event_name
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            yield {"type": "delta", "delta": payload}
            continue
        if not isinstance(obj, dict):
            continue
        kind = name or obj.get("type")
        if kind in (None, "delta", "text") or ("delta" in obj and kind not in ("thinking", "thinking_delta")):
            if obj.get("delta"):
                yield {"type": "delta", "delta": obj["delta"]}
        elif kind in ("thinking", "thinking_delta"):
            text = obj.get("delta") or obj.get("thinking") or obj.get("text") or ""
            if text:
                yield {"type": "thinking", "delta": text}
        elif kind == "thinking_start":
            yield {"type": "thinking_start"}
        elif kind == "thinking_tokens":
            yield {"type": "thinking_tokens", "tokens": obj.get("tokens") or obj.get("estimated_tokens") or 0}
        elif kind == "usage":
            usage = obj.get("usage") or {}
            yield {"type": "usage", "usage": {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }, "durationMs": obj.get("durationMs"), "costUsd": obj.get("costUsd")}
        elif kind == "error":
            err = obj.get("error")
            message = obj.get("message") or (err.get("message") if isinstance(err, dict) else err) or "daemon error"
            yield {"type": "error", "message": str(message)}
        elif kind in ("tool_use", "tool_result", "status", "start"):
            out = dict(obj)
            out["type"] = kind
            yield out
        elif kind in ("end", "done", "turn_end"):
            yield {"type": "turn_end", "stopped": False}


class ODConnector:
    """OpenDesign connector -- daemon mode or BYOK proxy mode.

    Daemon mode (default):
        POST /api/projects      -- create project
        POST /api/projects/:id/brief -- submit design brief
        POST /api/chat           -- run agent on the project
        GET  /api/daemon/status  -- health check

    BYOK mode (no daemon):
        the upstream provider API is called directly, streaming.
    """

    def __init__(
        self,
        host: str = DEFAULT_DAEMON_HOST,
        port: int = DEFAULT_DAEMON_PORT,
        mode: str = "daemon",
        byok: Optional[ProviderConfig] = None,
    ):
        self.host = host
        self.port = port
        self.mode = mode  # "daemon" or "byok"
        self.byok = byok
        self.project_id: Optional[str] = None
        self.conversation: list[ChatMessage] = []
        self.system_prompt = DEFAULT_SYSTEM_PROMPT
        self._available_models: list[ModelOption] = []
        self._connected = False
        self._cancel = threading.Event()
        self._active_resp = None

    # ------------------------------------------------------------------
    # Health / connectivity
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Check whether the daemon is reachable."""
        if self.mode == "daemon":
            return self._daemon_health() is not None
        return self.mode == "byok" and self.byok is not None

    def _daemon_health(self) -> Optional[dict]:
        try:
            data = self._http_get(f"http://{self.host}:{self.port}/api/daemon/status")
            if data:
                self._connected = True
                return data
        except Exception:
            pass
        self._connected = False
        return None

    def probe(self) -> dict:
        """Cheap reachability check for the active endpoint.

        Returns ``{"ok", "latency_ms", "detail", "models"}`` where ``models``
        is whatever the endpoint reports as installed/served (may be empty).
        Never raises: the UI shows the failure text next to the status pill.
        """
        started = time.monotonic()
        try:
            if self.mode == "daemon":
                data = self._http_get(f"http://{self.host}:{self.port}/api/daemon/status")
                ok = data is not None
                return self._probe_result(ok, started, "OpenDesign daemon" if ok else "daemon not reachable", [])
            if not self.byok:
                return self._probe_result(False, started, "no provider configured", [])
            prov, base = self.byok.provider, self.byok.baseUrl.rstrip("/")
            headers = {}
            label = BYOK_PRESETS.get(prov, {}).get("label", prov)
            unreachable = f"{label} unreachable at {base}"
            if prov == "ollama":
                url = f"{base}/api/tags"
                data = self._http_get(url, headers)
                models = [m.get("name") for m in (data or {}).get("models", []) if m.get("name")]
                return self._probe_result(data is not None, started, "Ollama" if data is not None else unreachable, models)
            if prov in ("openai", "vllm"):
                url = f"{base}/v1/models"
                if self.byok.apiKey:
                    headers["Authorization"] = f"Bearer {self.byok.apiKey}"
                status, data = self._http_get_status(url, headers)
                if status in (401, 403):
                    # The server answered: calling it unreachable sent people
                    # to check the network when the key was the problem.
                    detail = "API key rejected" if self.byok.apiKey else "API key required"
                    return self._probe_result(False, started, f"{label}: {detail}", [])
                models = [m.get("id") for m in (data or {}).get("data", []) if m.get("id")]
                return self._probe_result(data is not None, started, label if data is not None else unreachable, models)
            if prov == "anthropic":
                if not self.byok.apiKey:
                    return self._probe_result(False, started, "API key required", [])
                headers = {"x-api-key": self.byok.apiKey,
                           "anthropic-version": self.byok.apiVersion or "2023-06-01"}
                data = self._http_get(f"{base}/v1/models", headers)
                models = [m.get("id") for m in (data or {}).get("data", []) if m.get("id")]
                return self._probe_result(data is not None, started, "Anthropic" if data is not None else unreachable + " (or bad key)", models)
            if prov == "google":
                if not self.byok.apiKey:
                    return self._probe_result(False, started, "API key required", [])
                data = self._http_get(f"{base}/v1beta/models", {"x-goog-api-key": self.byok.apiKey})
                models = [str(m.get("name", "")).replace("models/", "")
                          for m in (data or {}).get("models", []) if m.get("name")]
                return self._probe_result(data is not None, started, "Google" if data is not None else unreachable + " (or bad key)", models)
            return self._probe_result(False, started, f"unsupported provider {prov}", [])
        except Exception as exc:  # pragma: no cover - defensive
            return self._probe_result(False, started, str(exc), [])

    @staticmethod
    def _probe_result(ok: bool, started: float, detail: str, models: list) -> dict:
        return {
            "ok": bool(ok),
            "latency_ms": (time.monotonic() - started) * 1000.0,
            "detail": detail,
            "models": models,
        }

    # ------------------------------------------------------------------
    # Model discovery
    # ------------------------------------------------------------------

    def discover_models(self) -> list[ModelOption]:
        """Return the list of available models.

        In daemon mode the list comes from the daemon's agent registry.
        In BYOK mode it comes from the preset's model list.
        """
        if self.mode == "byok" and self.byok:
            preset = BYOK_PRESETS.get(self.byok.provider, {})
            models = []
            for mid in preset.get("models", []):
                models.append(ModelOption(id=mid, label=mid, default=(mid == self.byok.model)))
            return models

        # Daemon mode -- probe /api/agents or fall back to defaults.
        agents = self._daemon_health()
        if agents:
            self._connected = True
            self._available_models = [
                ModelOption(id="default", label="Default (auto)", default=True),
            ]
            return self._available_models

        # Fallback: use the first BYOK preset.
        self.mode = "byok"
        self.byok = ProviderConfig.from_dict(BYOK_PRESETS.get("ollama", {}))
        return self.discover_models()

    # ------------------------------------------------------------------
    # Project management (daemon mode)
    # ------------------------------------------------------------------

    def create_project(
        self,
        name: str = "EmbeddedDisplay AI Design",
        kind: str = "prototype",
        platform: str = "responsive",
    ) -> Optional[str]:
        """Create a new OpenDesign project and return its ID."""
        payload = {
            "name": name,
            "kind": kind,
            "platform": platform,
            "platformTargets": [platform],
            "includeLandingPage": True,
        }
        result = self._daemon_post("/api/projects", payload)
        if result and "id" in result:
            self.project_id = result["id"]
            return self.project_id
        logger.warning("create_project returned unexpected response: %s", result)
        return None

    # ------------------------------------------------------------------
    # Brief submission (daemon mode)
    # ------------------------------------------------------------------

    def submit_brief(self, text: str) -> Optional[dict]:
        """Submit a design brief to the current project."""
        if not self.project_id:
            self.create_project()
        payload = {"prompt": text, "skipDiscoveryBrief": True}
        return self._daemon_post(f"/api/projects/{self.project_id}/brief", payload)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def cancel(self):
        """Stop the in-flight stream.

        Setting the flag alone is not enough: the worker may be parked inside
        ``readline()`` waiting for a slow model, and would only notice the
        flag when the next token (or the 300 s timeout) arrived.  Closing the
        response from here makes that read return immediately.
        """
        self._cancel.set()
        resp = self._active_resp
        if resp is not None:
            # The reader thread is blocked in recv() on the response socket.
            # HTTPResponse.close() only drops a reference, and on Windows even
            # shutdown() leaves the blocked call waiting until the server
            # speaks, so the socket is closed for real (socket._real_close is
            # the C-level closesocket; the public close() defers while the
            # response's file object still references the socket).
            try:
                sock = resp.fp.raw._sock
                try:
                    sock._real_close()
                except AttributeError:
                    sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                resp.close()
            except Exception:
                pass

    def generate(
        self,
        brief: str,
        model: Optional[str] = None,
        stream: bool = True,
    ) -> Generator[str, None, None]:
        """Generate UI from a brief, yielding answer-text deltas.

        Thin compatibility wrapper over :meth:`generate_events` for callers
        that only want the text (``AIDesignAgent``).  Errors surface inline
        as ``[Error] …`` so a plain text consumer still sees them.
        """
        for event in self.generate_events(brief, model):
            if event["type"] == "delta":
                yield event["delta"]
            elif event["type"] == "error":
                yield f"[Error] {event['message']}"

    def generate_events(
        self,
        brief: str,
        model: Optional[str] = None,
    ) -> Generator[dict, None, None]:
        """Generate UI from a brief as a structured event stream.

        Always begins with ``start`` and ends with ``turn_end``; the answer
        text is accumulated into the conversation history on the way out.
        """
        self._cancel.clear()
        self.conversation.append(ChatMessage(role="user", content=brief))
        answer_parts: list[str] = []
        stopped = False
        try:
            if self.mode == "daemon":
                source = self._daemon_events(brief, model)
            else:
                source = self._byok_events(brief, model)
            for event in source:
                if event["type"] == "delta":
                    answer_parts.append(event["delta"])
                if event["type"] == "turn_end":
                    # The wire said "end"; we still emit our own below.
                    continue
                yield event
        except StreamCancelled:
            stopped = True
        except Exception as exc:
            logger.error("generation failed: %s", exc)
            yield {"type": "error", "message": str(exc)}
        full_text = "".join(answer_parts)
        self.conversation.append(ChatMessage(role="assistant", content=full_text))
        yield {"type": "turn_end", "stopped": stopped}

    # ------------------------------------------------------------------
    # Daemon mode
    # ------------------------------------------------------------------

    def _daemon_events(self, brief: str, model: Optional[str]) -> Generator[dict, None, None]:
        url = f"http://{self.host}:{self.port}/api/chat"
        payload = {
            "message": brief,
            "projectId": self.project_id,
            "model": model,
            "reasoning": False,
            "locale": "en",
        }
        yield {"type": "start", "model": model or "default", "provider": "opendesign",
               "url": url, "mode": "daemon"}
        yield {"type": "status", "label": "connecting"}
        first = True
        for event in self._stream_events(url, payload, {"Content-Type": "application/json"}, parse_daemon_stream):
            if first and event["type"] in ("delta", "thinking"):
                first = False
                yield {"type": "status", "label": "streaming"}
            yield event

    # ------------------------------------------------------------------
    # BYOK mode (no daemon)
    # ------------------------------------------------------------------

    def _history_messages(self) -> list[dict]:
        """Prior turns (excluding the brief just appended), most recent last.

        Only complete user/assistant pairs are kept.  A cancelled or failed
        turn leaves an empty assistant reply behind; dropping just that reply
        would put two user messages back to back, which Anthropic and Gemini
        reject (roles must alternate), so the orphaned brief goes too.
        """
        prior = [m for m in self.conversation[:-1] if m.role in ("user", "assistant")]
        pairs: list[dict] = []
        i = 0
        while i + 1 < len(prior):
            user, reply = prior[i], prior[i + 1]
            if user.role == "user" and reply.role == "assistant":
                if user.content and reply.content:
                    pairs.append({"role": "user", "content": user.content})
                    pairs.append({"role": "assistant", "content": reply.content})
                i += 2
            else:
                i += 1
        return pairs[-(HISTORY_TURNS * 2):]

    def _byok_events(self, brief: str, model: Optional[str]) -> Generator[dict, None, None]:
        if not self.byok:
            yield {"type": "error", "message": "No BYOK provider configured."}
            return

        prov = self.byok.provider
        model_name = model or self.byok.model
        base = self.byok.baseUrl.rstrip("/")
        chat_messages = self._history_messages() + [{"role": "user", "content": brief}]
        messages = [{"role": "system", "content": self.system_prompt}] + chat_messages
        headers = {"Content-Type": "application/json"}

        if prov == "ollama":
            url = f"{base}/api/chat"
            payload = {"model": model_name, "messages": messages, "stream": True}
            parser = parse_ollama_stream
        elif prov in ("openai", "vllm"):
            url = f"{base}/v1/chat/completions"
            if self.byok.apiKey:
                headers["Authorization"] = f"Bearer {self.byok.apiKey}"
            payload = {
                "model": model_name,
                "messages": messages,
                "stream": True,
                "max_tokens": MAX_OUTPUT_TOKENS,
                # Ask for the trailing usage chunk so token counts are exact.
                "stream_options": {"include_usage": True},
            }
            if not self.byok.thinking:
                # Qwen-style templates render a reasoning pass unless told
                # otherwise; vLLM forwards these kwargs to the template.
                # Templates that do not know the flag ignore it, and a server
                # that rejects the field gets one retry without it below.
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            parser = parse_openai_stream
        elif prov == "anthropic":
            url = f"{base}/v1/messages"
            headers.update({
                "x-api-key": self.byok.apiKey,
                "anthropic-version": self.byok.apiVersion or "2023-06-01",
            })
            payload = {
                "model": model_name,
                "system": self.system_prompt,
                "messages": chat_messages,
                "stream": True,
                "max_tokens": ANTHROPIC_MAX_OUTPUT_TOKENS,
            }
            parser = parse_anthropic_stream
        elif prov == "google":
            url = f"{base}/v1beta/models/{model_name}:streamGenerateContent?alt=sse"
            if self.byok.apiKey:
                headers["x-goog-api-key"] = self.byok.apiKey
            payload = {
                "systemInstruction": {"parts": [{"text": self.system_prompt}]},
                "contents": [
                    {"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"]}]}
                    for m in chat_messages
                ],
                "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
            }
            parser = parse_google_stream
        else:
            yield {"type": "error", "message": f"Unsupported BYOK provider: {prov}"}
            return

        if self.byok.requiresApiKey and not self.byok.apiKey:
            yield {"type": "error", "message": f"{BYOK_PRESETS[prov]['label']} needs an API key."}
            return

        yield {"type": "start", "model": model_name, "provider": prov, "url": redact_url(url), "mode": "byok"}
        yield {"type": "status", "label": "connecting"}
        first = True
        for event in self._stream_events(url, payload, headers, parser):
            if first and event["type"] in ("delta", "thinking"):
                first = False
                yield {"type": "status", "label": "streaming"}
            yield event

    # ------------------------------------------------------------------
    # HTTP streaming
    # ------------------------------------------------------------------

    def _stream_events(self, url: str, payload: dict, headers: dict, parser) -> Generator[dict, None, None]:
        """POST ``payload`` and run ``parser`` over the response lines.

        HTTP errors carry the server's body (provider error JSON is far more
        useful than "400 Bad Request").  Cancellation is checked per chunk.
        """
        ctx = ssl.create_default_context()
        shown = redact_url(url)

        def _post(body_dict):
            req = urllib.request.Request(
                url, data=json.dumps(body_dict).encode("utf-8"),
                headers=headers, method="POST")
            return urllib.request.urlopen(req, timeout=300, context=ctx)

        try:
            try:
                resp = _post(payload)
            except urllib.error.HTTPError as exc:
                # A server whose chat template rejects unknown kwargs answers
                # 400; the request is worth one retry in its plainest form.
                if exc.code != 400 or "chat_template_kwargs" not in payload:
                    raise
                logger.info("retrying without chat_template_kwargs")
                plain = {k: v for k, v in payload.items() if k != "chat_template_kwargs"}
                resp = _post(plain)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:600]
            except Exception:
                pass
            yield {"type": "error", "message": f"HTTP {exc.code} {exc.reason}: {body or shown}"}
            return
        except urllib.error.URLError as exc:
            yield {"type": "error", "message": f"Cannot reach {shown}: {exc.reason}"}
            return
        except (OSError, ValueError) as exc:
            yield {"type": "error", "message": f"Request to {shown} failed: {exc}"}
            return
        self._active_resp = resp
        try:
            with resp:
                yield from parser(self._iter_lines(resp))
        except StreamCancelled:
            raise
        except Exception as exc:
            if self._cancel.is_set():
                raise StreamCancelled()
            yield {"type": "error", "message": f"Stream from {shown} broke: {exc}"}
        finally:
            self._active_resp = None

    def _iter_lines(self, resp) -> Generator[str, None, None]:
        # readline() returns as soon as one line is complete.  read(4096)
        # would block until 4 KB had arrived (http.client fills the whole
        # amount even across chunks), which turned a token stream into one
        # lump at the end of the run.
        while True:
            if self._cancel.is_set():
                raise StreamCancelled()
            try:
                line = resp.readline()
            except Exception:
                # cancel() shut the socket down under us -> that is the
                # cancel, not a fault; anything else is a real stream error.
                if self._cancel.is_set():
                    raise StreamCancelled()
                raise
            if not line:
                break
            yield line.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _daemon_get(self, path: str) -> Optional[dict]:
        return self._http_get(f"http://{self.host}:{self.port}{path}", timeout=10)

    def _daemon_post(self, path: str, payload: dict) -> Optional[dict]:
        url = f"http://{self.host}:{self.port}{path}"
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.error("daemon POST %s failed: %s", path, exc)
            return None

    def _http_get_status(self, url: str, headers: Optional[dict] = None,
                         timeout: float = 5) -> tuple:
        """GET url as JSON; return (HTTP status or None, parsed body or None).

        Unlike _http_get, an HTTP error keeps its status, so a server that
        answered 401 is not reported as one that did not answer.
        """
        try:
            req = urllib.request.Request(url, headers=headers or {})
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except Exception:
            return None, None

    def _http_get(self, url: str, headers: Optional[dict] = None, timeout: float = 5) -> Optional[dict]:
        try:
            req = urllib.request.Request(url, headers=headers or {})
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public API for the UI
    # ------------------------------------------------------------------

    def get_provider_presets(self) -> list[dict]:
        """Return all BYOK provider presets for the model picker UI."""
        presets = []
        for key, p in BYOK_PRESETS.items():
            presets.append({
                "key": key,
                "label": p["label"],
                "models": p["models"],
                "requiresApiKey": p["requiresApiKey"],
                "baseUrl": p["baseUrl"],
            })
        return presets

    def get_config(self) -> dict:
        """Return current connector config."""
        return {
            "mode": self.mode,
            "host": self.host,
            "port": self.port,
            "project_id": self.project_id,
            "byok": self.byok.to_dict() if self.byok else None,
            "conversation": [
                {"role": m.role, "content": m.content}
                for m in self.conversation
            ],
        }

    def set_config(self, config: dict):
        """Restore connector config from persisted settings."""
        self.mode = config.get("mode", "daemon")
        self.host = config.get("host", DEFAULT_DAEMON_HOST)
        self.port = config.get("port", DEFAULT_DAEMON_PORT)
        self.project_id = config.get("project_id")
        byok_cfg = config.get("byok")
        if byok_cfg:
            self.mode = "byok"
            self.byok = ProviderConfig.from_dict(byok_cfg)
        else:
            self.byok = None
        conv = config.get("conversation", [])
        self.conversation = [
            ChatMessage(role=m["role"], content=m["content"]) for m in conv
        ]
