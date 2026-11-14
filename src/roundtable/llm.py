"""LLM adapters behind one tiny protocol. Anthropic is the default with a key; scripted is keyless."""

from __future__ import annotations

import json
import os
from typing import Protocol

import httpx

DEFAULT_MODEL = "claude-sonnet-5-5"


class Brain(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


class ScriptedBrain:
    """Deterministic stand-in for tests and the keyless demo. `rules` map a prompt substring to a reply."""

    def __init__(
        self, rules: tuple[tuple[str, str], ...] = (), default: str = "Noted."
    ) -> None:
        self._rules = rules
        self._default = default
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        for needle, reply in self._rules:
            if needle in system or needle in user:
                return reply
        return self._default


class AnthropicBrain:
    def __init__(self, model: str | None = None, client: object | None = None) -> None:
        import anthropic

        self._model = model or os.environ.get("ROUNDTABLE_MODEL", DEFAULT_MODEL)
        self._client = client or anthropic.AsyncAnthropic()

    async def complete(self, system: str, user: str) -> str:
        message = await self._client.messages.create(  # type: ignore[attr-defined]
            model=self._model,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in message.content if block.type == "text")


class OpenAICompatBrain:
    """Any OpenAI-compatible /chat/completions endpoint (Ollama, OpenRouter, Groq)."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model

    async def complete(self, system: str, user: str) -> str:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self._url, json=body, headers={"Authorization": f"Bearer {self._key}"}
            )
            response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


def make_brain() -> Brain:
    """ROUNDTABLE_LLM=anthropic|openai|scripted; default anthropic when a key exists, else scripted."""
    choice = os.environ.get("ROUNDTABLE_LLM", "")
    if not choice:
        choice = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "scripted"
    if choice == "anthropic":
        return AnthropicBrain()
    if choice == "openai":
        return OpenAICompatBrain(
            os.environ.get("ROUNDTABLE_OPENAI_BASE_URL", "http://localhost:11434/v1"),
            os.environ.get("ROUNDTABLE_OPENAI_API_KEY", "none"),
            os.environ.get("ROUNDTABLE_MODEL", "llama3.1"),
        )
    from roundtable.demo_script import demo_brain

    return demo_brain()


def parse_gate(raw: str) -> tuple[bool, str]:
    """Parse the LLM gate's JSON. Anything malformed fails closed: stay silent."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        return False, ""
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return False, ""
    if not isinstance(data, dict) or data.get("speak") is not True:
        return False, ""
    return True, str(data.get("text", "")).strip()
