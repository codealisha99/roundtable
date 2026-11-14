"""Text-to-speech adapters. Each yields raw mono int16 PCM chunks at `sample_rate`."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

import httpx

DEFAULT_PIPER_VOICE = "en_US-lessac-medium"


class TTS(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> AsyncIterator[bytes]: ...


class PiperTTS:
    """Local Piper voice. The voice model is fetched once from Hugging Face into ROUNDTABLE_VOICE_DIR."""

    HF_REPO = "rhasspy/piper-voices"

    def __init__(self, voice_name: str | None = None) -> None:
        from piper import PiperVoice

        name = voice_name or os.environ.get(
            "ROUNDTABLE_PIPER_VOICE", DEFAULT_PIPER_VOICE
        )
        model_path = _ensure_piper_voice(name, self.HF_REPO)
        self._voice = PiperVoice.load(str(model_path))
        self.sample_rate = self._voice.config.sample_rate

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        chunks = await asyncio.to_thread(
            lambda: [c.audio_int16_bytes for c in self._voice.synthesize(text)]
        )
        for chunk in chunks:
            yield chunk


def _ensure_piper_voice(name: str, repo: str) -> Path:
    from huggingface_hub import hf_hub_download

    locale, speaker, quality = name.split("-")  # en_US-lessac-medium
    base = f"{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{name}"
    target = Path(
        os.environ.get(
            "ROUNDTABLE_VOICE_DIR", Path.home() / ".cache" / "roundtable" / "voices"
        )
    )
    target.mkdir(parents=True, exist_ok=True)
    for suffix in (".onnx", ".onnx.json"):
        hf_hub_download(repo_id=repo, filename=base + suffix, local_dir=target)
    return target / f"{base}.onnx"


class ElevenLabsTTS:
    """ElevenLabs REST, PCM 16 kHz output. Not exercised live in this repo: no key here."""

    def __init__(
        self, api_key: str, voice_id: str, model_id: str = "eleven_turbo_v2_5"
    ) -> None:
        self._key = api_key
        self._voice = voice_id
        self._model = model_id
        self.sample_rate = 16000

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice}"
        headers = {"xi-api-key": self._key}
        body = {"text": text, "model_id": self._model}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url, params={"output_format": "pcm_16000"}, headers=headers, json=body
            )
            response.raise_for_status()
        yield response.content


class OpenAITTS:
    """OpenAI speech endpoint, raw PCM (24 kHz). Not exercised live in this repo: no key here."""

    def __init__(
        self, api_key: str, voice: str = "alloy", model: str = "tts-1"
    ) -> None:
        self._key = api_key
        self._voice = voice
        self._model = model
        self.sample_rate = 24000

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        headers = {"Authorization": f"Bearer {self._key}"}
        body = {
            "model": self._model,
            "voice": self._voice,
            "input": text,
            "response_format": "pcm",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech", headers=headers, json=body
            )
            response.raise_for_status()
        yield response.content


def make_tts() -> TTS:
    """ROUNDTABLE_TTS=piper|elevenlabs|openai overrides; otherwise a key picks the cloud adapter."""
    choice = os.environ.get("ROUNDTABLE_TTS", "")
    if not choice:
        choice = "elevenlabs" if os.environ.get("ELEVENLABS_API_KEY") else "piper"
    if choice == "elevenlabs":
        return ElevenLabsTTS(
            os.environ["ELEVENLABS_API_KEY"],
            os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        )
    if choice == "openai":
        return OpenAITTS(os.environ["OPENAI_API_KEY"])
    return PiperTTS()
