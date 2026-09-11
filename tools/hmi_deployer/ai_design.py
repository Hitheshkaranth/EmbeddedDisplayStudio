"""
tools/hmi_deployer/ai_design.py -- OpenDesign connector and Qt/QML generator

Layer: 3 (Host Deployer)

Connects EmbeddedDisplay Studio to OpenDesign for AI-driven UI generation.
Supports two modes:

  1. **Daemon mode** -- talks to a local OpenDesign daemon (default
     localhost:7456).  Projects, briefs and model selection flow through the
     daemon's REST API.  Streaming uses SSE.

  2. **BYOK mode** -- no daemon required.  The Studio calls the upstream API
     directly (Ollama, OpenAI, Anthropic, etc.) using the BYOK proxy wire
     format.  Every provider has a preset so the user only needs to paste an
     API key and pick a model.

The generated HTML/QML is parsed and mapped onto the existing designer
canvas (DesignerProject + DesignerWidget model), so the author can inspect
and tweak the AI output before deploying to the panel.
"""
import json
import sys
import time
import logging
import urllib.request
import urllib.error
import ssl

from typing import Generator, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenDesign daemon defaults
# ---------------------------------------------------------------------------

DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 7456

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
        "baseUrl": "http://spark-ba51:8000",
        "apiVersion": "",
        "requiresApiKey": False,
        "apiKey": "",
        "protocol": "openai",
        "models": [
            "nvidia/Qwen3.6-35B-A3B-NVFP4",
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

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "baseUrl": self.baseUrl,
            "apiKey": self.apiKey,
            "apiVersion": self.apiVersion,
            "requiresApiKey": self.requiresApiKey,
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


class ODConnector:
    """OpenDesign connector -- daemon mode or BYOK proxy mode.

    Daemon mode (default):
        POST /api/projects      -- create project
        POST /api/projects/:id/brief -- submit design brief
        POST /api/chat           -- run agent on the project
        GET  /api/daemon/status  -- health check

    BYOK mode (no daemon):
        POST /api/proxy/{provider}/stream  -- direct streaming proxy call
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
        self._available_models: list[ModelOption] = []
        self._connected = False

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
    # Chat / generation (daemon mode)
    # ------------------------------------------------------------------

    def generate(
        self,
        brief: str,
        model: Optional[str] = None,
        stream: bool = True,
    ) -> Generator[str, None, None]:
        """Generate UI from a brief.

        Yields streaming text deltas in daemon mode.
        Returns the full response text in BYOK mode.
        """
        self.conversation.append(ChatMessage(role="user", content=brief))

        if self.mode == "daemon":
            payload = {
                "message": brief,
                "projectId": self.project_id,
                "model": model,
                "reasoning": False,
                "locale": "en",
            }
            yield from self._daemon_chat_stream(payload)
        else:
            # BYOK mode: call the proxy directly.
            full_text = self._byok_chat(brief, model)
            self.conversation.append(ChatMessage(role="assistant", content=full_text))
            yield full_text

    def _daemon_chat_stream(self, payload: dict) -> Generator[str, None, None]:
        """Stream from the daemon's /api/chat endpoint (SSE)."""
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"http://{self.host}:{self.port}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                buffer = ""
                for raw in resp.stream():
                    buffer += raw.decode("utf-8", errors="replace")
                    # SSE lines end with \n\n
                    while "\n\n" in buffer:
                        chunk, buffer = buffer.split("\n\n", 1)
                        for line in chunk.split("\n"):
                            if line.startswith("data: "):
                                d = line[6:]
                                try:
                                    obj = json.loads(d)
                                    delta = obj.get("delta", "")
                                    if delta:
                                        yield delta
                                except json.JSONDecodeError:
                                    yield d
        except Exception as exc:
            logger.error("daemon chat stream failed: %s", exc)
            yield f"[Error] {exc}"

        self.conversation.append(
            ChatMessage(role="assistant", content="Generation complete.")
        )

    # ------------------------------------------------------------------
    # BYOK proxy mode (no daemon)
    # ------------------------------------------------------------------

    def _byok_chat(self, brief: str, model: Optional[str] = None) -> str:
        """Call the upstream API directly (no daemon proxy needed in BYOK mode)."""
        if not self.byok:
            return "[Error] No BYOK provider configured."

        prov = self.byok.provider
        model_name = model or self.byok.model

        system_prompt = (
            "You are an expert Qt/QML UI designer for embedded HMI panels. "
            "Generate clean, production-ready QML code using Shadcn-inspired "
            "widget styles. Focus on clarity, proper layout containers, and "
            "data binding to tag sources. Output ONLY QML code blocks."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": brief},
        ]

        if prov == "ollama":
            # Direct to Ollama /api/chat endpoint
            url = f"{self.byok.baseUrl}/api/chat"
            payload = {
                "model": model_name,
                "messages": messages,
                "stream": True,
            }
            full_text = self._stream_to(url, payload)
        elif prov in ("openai", "vllm"):
            # Direct to OpenAI-compatible /v1/chat/completions endpoint
            url = f"{self.byok.baseUrl}/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            if self.byok.apiKey:
                headers["Authorization"] = f"Bearer {self.byok.apiKey}"
            payload = {
                "model": model_name,
                "messages": messages,
                "stream": True,
                "max_tokens": 8192,
            }
            full_text = self._stream_to(url, payload, headers)
        elif prov == "anthropic":
            url = f"{self.byok.baseUrl}/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.byok.apiKey,
                "anthropic-version": self.byok.apiVersion or "2023-06-01",
            }
            payload = {
                "model": model_name,
                "messages": messages,
                "stream": True,
                "max_tokens": 8192,
            }
            full_text = self._stream_to(url, payload, headers)
        elif prov == "google":
            url = f"{self.byok.baseUrl}/v1beta/models/{model_name}:streamGenerateContent"
            if self.byok.apiKey:
                url += f"?key={self.byok.apiKey}"
            google_payload = {
                "contents": [{"parts": [{"text": m["content"]}] for m in messages}],
                "generationConfig": {"maxOutputTokens": 8192},
            }
            headers = {"Content-Type": "application/json"}
            full_text = self._stream_to(url, google_payload, headers, google_format=True)
        else:
            return f"[Error] Unsupported BYOK provider: {prov}"

        self.conversation.append(ChatMessage(role="assistant", content=full_text))
        return full_text

    def _stream_ollama(self, url: str, payload: dict) -> str:
        """Stream from an Ollama-compatible /api/chat endpoint (NDJSON)."""
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                full = ""
                for raw_line in resp.stream(4096):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        delta = obj.get("message", {}).get("content", "")
                        if delta:
                            full += delta
                    except json.JSONDecodeError:
                        pass
                return full
        except Exception as exc:
            logger.error("Ollama stream failed: %s", exc)
            return f"[Error] {exc}"

    def _stream_openai(self, url: str, payload: dict) -> str:
        """Stream from an OpenAI-compatible /v1/chat/completions endpoint."""
        prov = self.byok.provider
        headers = {"Content-Type": "application/json"}

        if prov == "anthropic":
            headers["x-api-key"] = self.byok.apiKey
            headers["anthropic-version"] = "2023-06-01"
            # Anthropic wire format
            anthropic_payload = {
                "model": payload["model"],
                "max_tokens": payload.get("maxTokens", 8192),
                "messages": payload["messages"],
                "stream": True,
            }
            stream_url = f"{payload['baseUrl']}/v1/messages"
        elif prov == "google":
            stream_url = f"{payload['baseUrl']}/v1beta/models/{payload['model']}:streamGenerateContent?key={self.byok.apiKey}"
            google_payload = {
                "contents": [
                    {"parts": [{"text": m["content"]}] for m in payload["messages"]}
                ],
                "generationConfig": {"maxOutputTokens": payload.get("maxTokens", 8192)},
            }
            data = json.dumps(google_payload).encode("utf-8")
            req = urllib.request.Request(stream_url, data=data, headers=headers, method="POST")
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                    full = ""
                    for raw in resp.stream(4096):
                        line = raw.decode("utf-8", errors="replace").strip()
                        if line.startswith("data: "):
                            d = json.loads(line[6:])
                            candidates = d.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for p in parts:
                                    if "text" in p:
                                        full += p["text"]
                    return full
            except Exception as exc:
                return f"[Error] Google stream failed: {exc}"
        else:
            # OpenAI default
            headers["Authorization"] = f"Bearer {self.byok.apiKey}"
            openai_payload = {
                "model": payload["model"],
                "messages": payload["messages"],
                "stream": True,
                "max_tokens": payload.get("maxTokens", 8192),
            }
            stream_url = f"{payload['baseUrl']}/v1/chat/completions"
            data = json.dumps(openai_payload).encode("utf-8")
            req = urllib.request.Request(stream_url, data=data, headers=headers, method="POST")
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                    full = ""
                    for raw in resp.stream(4096):
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line or not line.startswith("data: "):
                            continue
                        d = line[6:]
                        if d == "[DONE]":
                            break
                        try:
                            obj = json.loads(d)
                            delta = obj.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full += content
                        except (json.JSONDecodeError, IndexError):
                            pass
                    return full
            except Exception as exc:
                return f"[Error] OpenAI stream failed: {exc}"

        # Anthropic path
        try:
            data = json.dumps(anthropic_payload).encode("utf-8")
            req = urllib.request.Request(stream_url, data=data, headers=headers, method="POST")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                full = ""
                for raw in resp.stream(4096):
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    d = json.loads(line[6:])
                    if d.get("type") == "content_block_delta":
                        delta = d.get("delta", {})
                        text = delta.get("partial_text", "")
                        if text:
                            full += text
                return full
        except Exception as exc:
            return f"[Error] Anthropic stream failed: {exc}"

    # ------------------------------------------------------------------
    # Direct stream helper (BYOK mode)
    # ------------------------------------------------------------------

    def _stream_to(
        self,
        url: str,
        payload: dict,
        headers: Optional[dict] = None,
        google_format: bool = False,
    ) -> str:
        """Stream to an arbitrary URL with SSE response.

        Handles OpenAI-compatible (choices[].delta.content), Anthropic
        (content_block_delta.partial_text), Google (candidates[].content.parts),
        and Ollama (message.content) SSE formats.
        """
        if headers is None:
            headers = {"Content-Type": "application/json"}

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                full = ""
                buf = b""
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line_b, buf = buf.split(b"\n", 1)
                        line = line_b.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue

                        if google_format:
                            # Google Vertex AI SSE: data: {...}
                            if line.startswith("data: "):
                                d = json.loads(line[6:])
                                candidates = d.get("candidates", [])
                                if candidates:
                                    parts = candidates[0].get("content", {}).get("parts", [])
                                    for p in parts:
                                        if "text" in p:
                                            full += p["text"]
                        elif "message" in str(payload.get("model", "")) or "ollama" in str(headers):
                            # Ollama NDJSON: {"message": {"content": "..."}}
                            try:
                                obj = json.loads(line)
                                delta = obj.get("message", {}).get("content", "")
                                if delta:
                                    full += delta
                            except json.JSONDecodeError:
                                pass
                        else:
                            # OpenAI / Anthropic SSE: data: {...}
                            if not line.startswith("data: "):
                                continue
                            d = line[6:]
                            if d == "[DONE]":
                                break
                            try:
                                obj = json.loads(d)

                                # OpenAI format
                                if "choices" in obj:
                                    delta = obj.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        full += content

                                # Anthropic format
                                elif obj.get("type") == "content_block_delta":
                                    text = obj.get("delta", {}).get("partial_text", "")
                                    if text:
                                        full += text
                            except (json.JSONDecodeError, IndexError):
                                pass
                return full
        except Exception as exc:
            logger.error("stream_to %s failed: %s", url, exc)
            return f"[Error] {exc}"

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _daemon_get(self, path: str) -> Optional[dict]:
        url = f"http://{self.host}:{self.port}{path}"
        try:
            req = urllib.request.Request(url)
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

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

    def _http_get(self, url: str) -> Optional[dict]:
        try:
            req = urllib.request.Request(url)
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
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
            })
        return presets

    def get_config(self) -> dict:
        """Return current connector config."""
        return {
            "mode": self.mode,
            "host": self.host,
            "port": self.port,
            "project_id": self.project_id,
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