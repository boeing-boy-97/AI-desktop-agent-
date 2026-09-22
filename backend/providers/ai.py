"""AIProvider abstraction.

Supported backends:
    * OpenAI-compatible   (any /v1 chat/completions endpoint, incl. local proxies)
    * Ollama              (built-in local /api/chat)
    * Mock                (deterministic, offline — used for tests & demos)

Configuration never contains hard-coded secrets; keys come from the runtime
settings object which reads environment variables (OPENAI_API_KEY etc).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from core.exceptions import ConfigError, ProviderError


@dataclass
class ChatMessage:
    role: str            # system | user | assistant | tool
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    def as_dict(self) -> dict:
        out: dict = {"role": self.role, "content": self.content}
        if self.name:
            out["name"] = self.name
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        return out


@dataclass
class ChatResponse:
    content: str
    raw: dict | None = None
    usage: dict | None = None

    def has_json(self) -> bool:
        from core.utils import robust_json_parse
        return robust_json_parse(self.content) != {}


class AIProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(self, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        raise NotImplementedError

    async def chat_json(self, messages: list[ChatMessage],
                        fallback: dict | None = None, **kwargs) -> dict:
        from core.utils import robust_json_parse
        resp = await self.chat(messages, **kwargs)
        return robust_json_parse(resp.content, fallback)

    async def available(self) -> tuple[bool, str]:
        return True, "provider stateless"

    async def embed(self, text: str) -> list[float]:
        return []


# ---------------------------------------------------------------------------
# OpenAI-compatible
# ---------------------------------------------------------------------------
class OpenAICompatProvider(AIProvider):
    name = "openai"

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None
        self._client_owner: str | None = None

    def _client_for(self, executor: Any) -> httpx.AsyncClient:
        if self._client_owner == id(executor):
            return self._client
        self._client = executor()
        self._client_owner = id(executor)
        return self._client

    async def chat(self, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        api_key = self.settings.openai_api_key()
        if not api_key:
            raise ConfigError(
                "No API key configured for the OpenAI provider. Set OPENAI_API_KEY "
                "or configure a local provider such as Ollama.")

        base = self.settings.get_str("ai.openai_base_url", "https://api.openai.com/v1").rstrip("/")
        model = self.settings.get_str("ai.openai_model", "gpt-4o-mini")
        temperature = kwargs.get("temperature", self.settings.get_float("ai.temperature", 0.2))
        timeout = self.settings.get_int("ai.timeout_seconds", 120)

        payload = {
            "model": model,
            "messages": [m.as_dict() for m in messages],
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._close_client()
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(f"{base}/chat/completions",
                                         json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise ProviderError(f"OpenAI provider network error: {exc}") from exc
            if resp.status_code != 200:
                raise ProviderError(f"OpenAI provider HTTP {resp.status_code}: {resp.text[:400]}")
            data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"Unexpected OpenAI response shape: {str(data)[:300]}") from exc
        return ChatResponse(content=content, raw=data, usage=data.get("usage"))

    async def available(self) -> tuple[bool, str]:
        if not self.settings.openai_api_key():
            return False, "OPENAI_API_KEY not set"
        try:
            base = self.settings.get_str("ai.openai_base_url").rstrip("/")
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{base}/models",
                                     headers={"Authorization": f"Bearer {self.settings.openai_api_key()}"})
            return r.status_code == 200, f"HTTP {r.status_code}"
        except Exception as exc:
            return False, str(exc)[:200]

    def _close_client(self) -> None:
        if self._client is not None:
            self._client = None
            self._client_owner = None


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    async def chat(self, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        base = self.settings.get_str("ai.ollama_base_url", "http://127.0.0.1:11434").rstrip("/")
        model = self.settings.get_str("ai.ollama_model", "llama3.1")
        timeout = self.settings.get_int("ai.timeout_seconds", 120)
        payload = {
            "model": model,
            "stream": False,
            "messages": [m.as_dict() for m in messages],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(f"{base}/api/chat", json=payload)
            except httpx.HTTPError as exc:
                raise ProviderError(f"Ollama reachable? {exc}") from exc
            if resp.status_code != 200:
                raise ProviderError(f"Ollama HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
        content = (data.get("message") or {}).get("content", "")
        return ChatResponse(content=content, raw=data)

    async def available(self) -> tuple[bool, str]:
        base = self.settings.get_str("ai.ollama_base_url").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{base}/api/tags")
            if r.status_code == 200:
                return True, f"Ollama up ({len(r.json().get('models', []))} models)"
            return False, f"HTTP {r.status_code}"
        except Exception as exc:
            return False, str(exc)[:200]


# ---------------------------------------------------------------------------
# Mock (deterministic offline provider used by tests and demo mode)
# ---------------------------------------------------------------------------
class MockProvider(AIProvider):
    name = "mock"

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    async def chat(self, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        text = "\n".join(m.content for m in messages if m.role == "user")
        return ChatResponse(content=_mock_reply(text))

    async def available(self) -> tuple[bool, str]:
        return True, "mock provider always available"


def _mock_reply(text: str) -> str:
    low = text.lower()
    if "plan" in low or "step" in low:
        # a captured plan request from the planner should get a structured plan
        return json.dumps({
            "goal": "echo the request through a safe shell command",
            "steps": [
                {"seq": 0, "tool": "shell.run", "arguments": {"command": "echo hello-nova"}}
            ],
        })
    if any(k in low for k in ("download", "error", "fail", "build")):
        return json.dumps({
            "goal": "simulated project scaffold",
            "steps": [
                {"seq": 0, "tool": "filesystem.create_file",
                 "arguments": {"path": "C:/nova-output/README.md", "content": "# Nova demo"}},
            ],
        }) if "error" not in low and "fail" not in low else (
            "I couldn't complete that because the simulated external service "
            "returned an authentication error.")
    return json.dumps({
        "goal": "perform a harmless demonstration action",
        "steps": [
            {"seq": 0, "tool": "shell.run", "arguments": {"command": "echo nova-mock"}},
        ],
    })


def create_ai_provider(settings: Any) -> AIProvider:
    name = (settings.get_str("ai.provider", "openai") or "openai").lower()
    if name in ("openai", "openai-compatible", "openai_compatible"):
        return OpenAICompatProvider(settings)
    if name in ("ollama",):
        return OllamaProvider(settings)
    if name in ("mock", "demo"):
        return MockProvider(settings)
    raise ConfigError(f"Unknown AI provider: {name} (expected openai|ollama|mock)")
