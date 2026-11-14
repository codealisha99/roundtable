"""Speech-to-text adapters. Local faster-whisper is the keyless default; cloud adapters need keys."""

from __future__ import annotations

import asyncio
import os
from typing import Protocol

import httpx

from roundtable.speech.audio import pcm16_to_float32, wav_bytes


class STT(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int) -> str: ...


class LocalWhisper:
    def __init__(self, model_size: str | None = None) -> None:
        from faster_whisper import WhisperModel

        size = model_size or os.environ.get("ROUNDTABLE_WHISPER_MODEL", "base.en")
        self._model = WhisperModel(size, device="cpu", compute_type="int8")

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        audio = pcm16_to_float32(pcm)
        return await asyncio.to_thread(self._run, audio)

    def _run(self, audio) -> str:  # type: ignore[no-untyped-def]
        segments, _ = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=False,
            initial_prompt=os.environ.get(
                "ROUNDTABLE_STT_PROMPT", "Roundtable meeting."
            ),
        )
        return " ".join(seg.text.strip() for seg in segments).strip()


class DeepgramSTT:
    """Deepgram pre-recorded REST API (raw linear16 body). Not exercised live in this repo: no key here."""

    URL = "https://api.deepgram.com/v1/listen"

    def __init__(self, api_key: str, model: str = "nova-3") -> None:
        self._key = api_key
        self._model = model

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        params = {
            "model": self._model,
            "encoding": "linear16",
            "sample_rate": sample_rate,
            "channels": 1,
            "smart_format": "true",
        }
        headers = {
            "Authorization": f"Token {self._key}",
            "Content-Type": "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.URL, params=params, headers=headers, content=pcm
            )
            response.raise_for_status()
        channels = response.json()["results"]["channels"]
        return channels[0]["alternatives"][0]["transcript"].strip()


class OpenAISTT:
    """OpenAI audio transcriptions (whisper-1). Not exercised live in this repo: no key here."""

    URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(self, api_key: str, model: str = "whisper-1") -> None:
        self._key = api_key
        self._model = model

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        files = {"file": ("speech.wav", wav_bytes(pcm, sample_rate), "audio/wav")}
        headers = {"Authorization": f"Bearer {self._key}"}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.URL, headers=headers, data={"model": self._model}, files=files
            )
            response.raise_for_status()
        return str(response.json()["text"]).strip()


def make_stt() -> STT:
    """ROUNDTABLE_STT=local|deepgram|openai overrides; otherwise a key picks the cloud adapter."""
    choice = os.environ.get("ROUNDTABLE_STT", "")
    if not choice:
        choice = "deepgram" if os.environ.get("DEEPGRAM_API_KEY") else "local"
    if choice == "deepgram":
        return DeepgramSTT(os.environ["DEEPGRAM_API_KEY"])
    if choice == "openai":
        return OpenAISTT(os.environ["OPENAI_API_KEY"])
    return LocalWhisper()
